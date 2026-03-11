# -*- coding: utf-8 -*-
### bot tiktok youtube/common.py
import os
import json
import time
import logging
import subprocess
import shutil
import sys
from enum import Enum
from pathlib import Path
import yaml

# --- FIX CRITIQUE WINDOWS : ENCODAGE EMOJIS ---
# Force la console à accepter l'UTF-8 pour éviter les crashs "Logging error"
# lors de l'affichage d'emojis (🚀, 🛡️, etc.) sur Windows.
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        # On ne peut pas logger ici car le logger n'est pas encore prêt
        print(f"Warning: Impossible de configurer l'encodage UTF-8: {e}", file=sys.stderr)

# --- CONFIGURATION LOGGING AMÉLIORÉE (DOCKER READY) ---
# On privilégie stdout pour Docker, fichier seulement si demandé.
handlers = [logging.StreamHandler(sys.stdout)]

# Si on n'est pas en conteneur (dev local), on ajoute le fichier
if not os.getenv("DOCKER_CONTAINER"):
    handlers.append(logging.FileHandler("nexus_system.log", encoding='utf-8'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=handlers
)
logger = logging.getLogger("NEXUS_CORE")

def get_project_root() -> Path:
    """Retourne la racine absolue du projet."""
    return Path(__file__).parent.absolute()

def resolve_path(path_str: str) -> Path:
    """
    Convertit un chemin (relatif ou absolu) en chemin absolu sécurisé OS-agnostic.
    """
    if not path_str:
        return get_project_root() / "temp"
    
    p = Path(path_str)
    if p.is_absolute():
        return p
    
    # Si relatif, on le colle à la racine du projet
    return get_project_root() / p

def load_config():
    """
    Charge la configuration depuis le fichier YAML de manière sécurisée.
    PRIORITÉ : Variables d'environnement > Config YAML (Fallback).
    Résout dynamiquement les chemins relatifs en absolus.
    """
    root = get_project_root()
    config_path = root / "config.yaml"
    
    raw_config = {}
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"❌ Erreur de syntaxe dans config.yaml : {e}")
        except Exception as e:
            logger.error(f"❌ Erreur lecture config : {e}")
    else:
        logger.warning("⚠️ Fichier config.yaml introuvable, utilisation des defaults/ENV uniquement.")

    # --- INJECTION SÉCURISÉE DES VARIABLES D'ENVIRONNEMENT ---
    # Permet de surcharger les clés API sans modifier le fichier (Docker Secrets compatible)
    
    # API Keys
    if "api_keys" not in raw_config: raw_config["api_keys"] = {}
    
    if os.getenv("GEMINI_API_KEY"):
        raw_config["api_keys"]["gemini"] = os.getenv("GEMINI_API_KEY")
    
    if os.getenv("OPENAI_API_KEY"):
        raw_config["api_keys"]["openai"] = os.getenv("OPENAI_API_KEY")
        
    if os.getenv("AFFILIATE_LINK"):
        raw_config["api_keys"]["affiliate_link"] = os.getenv("AFFILIATE_LINK")

    # Options Globales
    if os.getenv("LOG_LEVEL"):
        raw_config["log_level"] = os.getenv("LOG_LEVEL")

    # --- RESOLUTION DES CHEMINS ---
    
    # 1. Sentinel Profile
    if "SENTINEL_PROFILE" in raw_config:
        raw_config["SENTINEL_PROFILE"] = resolve_path(raw_config["SENTINEL_PROFILE"])
        
    # 2. Dossiers
    if "directories" in raw_config:
        new_dirs = {}
        for key, val in raw_config["directories"].items():
            new_dirs[key] = resolve_path(val)
        raw_config["directories"] = new_dirs
        
    # 3. Cookies tools
    if "tools" in raw_config:
        for tool in ["tiktok", "youtube"]:
            if tool in raw_config["tools"] and "cookies_path" in raw_config["tools"][tool]:
                raw_config["tools"][tool]["cookies_path"] = resolve_path(raw_config["tools"][tool]["cookies_path"])

    return raw_config

# Chargement initial de la configuration
CONFIG = load_config()

def jlog(event: str, **kwargs):
    """
    Système de logging unifié et structuré (JSON).
    Filtre automatiquement les clés sensibles (API Keys).
    """
    msg = kwargs.get("msg", "")
    if "msg" in kwargs:
        del kwargs["msg"]
    
    # Filtrage de sécurité (basic)
    sanitized_kwargs = {}
    SENSITIVE_KEYS = ["api_key", "password", "token", "secret", "gemini", "openai"]
    
    for k, v in kwargs.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            sanitized_kwargs[k] = "***REDACTED***"
        else:
            sanitized_kwargs[k] = v

    extra_info = ""
    if sanitized_kwargs:
        try:
            extra_info = f" | {json.dumps(sanitized_kwargs, ensure_ascii=False)}"
        except TypeError:
            extra_info = " | [Data Unserializable]"
    
    full_msg = f"[{event.upper()}] {msg}{extra_info}"
    
    if event in ["error", "critical", "fatal", "exception"]:
        logger.error(full_msg)
    elif event in ["warning", "wait", "retry"]:
        logger.warning(full_msg)
    elif event in ["debug", "trace"]:
        logger.debug(full_msg)
    else:
        logger.info(full_msg)

def ensure_directories():
    """Crée l'arborescence nécessaire si elle n'existe pas."""
    dirs = CONFIG.get("directories", {})
    for key, path_obj in dirs.items():
        # path_obj est déjà un Path grâce à load_config
        try:
            path_obj.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Impossible de créer le dossier {key}: {e}")
    
    # Dossiers système par défaut
    resolve_path("temp").mkdir(exist_ok=True)
    resolve_path("assets/cache/tts").mkdir(parents=True, exist_ok=True)
    resolve_path("assets/vault/storage").mkdir(parents=True, exist_ok=True) # Ajout pour AssetVault

class TaskPriority(Enum):
    """Définition des priorités pour la file d'attente."""
    URGENT_MANUAL = 0
    HIGH_RETRY = 1
    NORMAL_AUTO = 10
    LOW_BACKGROUND = 20

class CircuitBreaker:
    """Gestionnaire de résilience (Pattern Circuit Breaker)."""
    def __init__(self, service_name):
        self.service_name = service_name
        self.max_failures = CONFIG.get('resilience', {}).get('circuit_breaker', {}).get('max_failures', 3)
        self.reset_timeout = CONFIG.get('resilience', {}).get('circuit_breaker', {}).get('reset_timeout', 1800)
        
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"[{self.service_name}] Échec enregistré ({self.failure_count}/{self.max_failures})")
        
        if self.failure_count >= self.max_failures:
            self.state = "OPEN"
            logger.error(f"[{self.service_name}] 🛡️ Circuit OUVERT. Passage en mode Fallback forcé pour {self.reset_timeout}s.")

    def record_success(self):
        if self.state != "CLOSED":
            logger.info(f"[{self.service_name}] ✅ Service rétabli. Circuit FERMÉ.")
        self.failure_count = 0
        self.state = "CLOSED"

    def is_available(self):
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.reset_timeout:
                self.state = "HALF_OPEN"
                logger.info(f"[{self.service_name}] ⏳ Tentative de réouverture (HALF_OPEN)...")
                return True 
            return False
            
        return True 

class VideoValidator:
    """Analyse prédictive des fichiers vidéo pour le Fail-Fast."""
    @staticmethod
    def validate_for_platform(file_path, platform="tiktok"):
        path = str(file_path)
        if not os.path.exists(path):
            return False, "Fichier introuvable"

        try:
            cmd = [
                "ffprobe", 
                "-v", "error", 
                "-show_entries", "format=duration", 
                "-show_entries", "stream=width,height", 
                "-of", "default=noprint_wrappers=1:nokey=1", 
                path
            ]
            # Timeout ajouté pour éviter les blocages
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode().split()
            values = [float(x) for x in output if x.replace('.', '', 1).isdigit()]
            
            if len(values) < 3:
                return True, "Impossible d'analyser (FFprobe échoué), on tente quand même."

            width, height, duration = values[0], values[1], values[2]
            rules = CONFIG.get('validation', {}).get(platform, {})
            
            if width > height:
                 return False, f"Format Paysage détecté ({int(width)}x{int(height)}). Requis: Vertical."
            
            max_dur = rules.get('max_duration', 60)
            if duration > max_dur + 2:
                return False, f"Durée trop longue ({duration:.1f}s). Max: {max_dur}s."
            
            return True, "OK"

        except subprocess.TimeoutExpired:
             return True, "Timeout FFprobe (Validation ignorée)"
        except Exception:
            return True, "Bypass validation (Outil manquant)"

def smart_move(src, dest_folder):
    """Déplace un fichier de manière sécurisée vers un dossier destination."""
    try:
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder)
        filename = os.path.basename(src)
        dst = os.path.join(dest_folder, filename)
        shutil.move(src, dst)
        logger.info(f"Fichier déplacé vers : {dest_folder}")
        return dst
    except Exception as e:
        logger.error(f"Erreur déplacement fichier: {e}")
        return None

async def move_to_archive(json_path: Path):
    try:
        archive_dir = CONFIG.get("directories", {}).get("archive_folder")
        if not archive_dir: return
        
        dst = archive_dir / json_path.name
        shutil.move(str(json_path), str(dst))
    except Exception as e:
        logger.error(f"Archive Error: {e}")

async def move_to_failed(json_path: Path, reason: str = "Unknown"):
    try:
        failed_dir = CONFIG.get("directories", {}).get("rejected_folder")
        if not failed_dir: return
        
        try:
            with open(json_path, 'r+') as f:
                data = json.load(f)
                data["error_reason"] = reason
                f.seek(0)
                json.dump(data, f, indent=4)
        except: pass

        dst = failed_dir / json_path.name
        shutil.move(str(json_path), str(dst))
    except Exception as e:
        logger.error(f"Failed Move Error: {e}")