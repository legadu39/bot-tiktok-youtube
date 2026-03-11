### bot tiktok youtube/tools/tt_utils.py
import requests
import json
import re
import os
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# --- CONFIGURATION GLOBALE ---
RUN_ID = f"run_{int(time.time())}"
ABS_PATH_ENFORCE = True
# PATCH CORRECTIF : Variable manquante ajoutée pour tt_runner
POST_SETFILE_DISPATCH = True

def jlog(status: str, **kwargs):
    """JSON Logger standardisé"""
    entry = {"status": status, "timestamp": time.time(), **kwargs}
    print(json.dumps(entry, ensure_ascii=False), flush=True)

def get_cdp_endpoint(port=9222):
    """Récupère l'URL WebSocket du navigateur via l'API HTTP CDP."""
    try:
        response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        if response.status_code == 200:
            data = response.json()
            return data.get("webSocketDebuggerUrl")
    except requests.exceptions.RequestException:
        return None
    return None

def check_file_exists(path_str: str) -> bool:
    return Path(path_str).exists()

def ensure_absolute_path(path_str: str) -> str:
    return str(Path(path_str).resolve())

def _preflight_resolve_path(raw_path: str) -> Tuple[bool, Any]:
    p = Path(raw_path)
    if not p.exists():
        return False, None
    return True, p.resolve()

def iter_candidate_files(directory: str):
    """Générateur simple pour scanner un dossier"""
    p = Path(directory)
    if not p.is_dir():
        return
    for f in p.glob("*.*"):
        if f.suffix.lower() in ['.mp4', '.mov', '.mkv']:
            yield f

def mark_file_done(file_path: Path):
    """Marque un fichier comme traité (renommage .done)"""
    try:
        new_name = file_path.with_suffix(file_path.suffix + ".done")
        file_path.rename(new_name)
    except Exception as e:
        jlog("warning", msg="Impossible de marquer le fichier comme fait", error=str(e))

# --- INTELLIGENCE N°1 : MÉMOIRE CONTEXTUELLE & SÉRIES ---

class MetadataHistory:
    """
    Gère la persistance des métadonnées pour détecter les séries et assurer la continuité.
    Sauvegarde le dernier état connu pour une 'racine' de fichier donnée.
    """
    HISTORY_FILE = Path("history_meta.json")

    @classmethod
    def load(cls) -> Dict[str, Any]:
        if not cls.HISTORY_FILE.exists():
            return {}
        try:
            with open(cls.HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def save(cls, data: Dict[str, Any]):
        try:
            with open(cls.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def extract_series_key(filename: str) -> Optional[str]:
        """
        Déduit une clé de série en retirant les nombres et dates variables.
        Ex: 'Minecraft_Survival_Ep05.mp4' -> 'minecraft_survival_ep'
        """
        stem = Path(filename).stem.lower()
        # Retire les séquences de chiffres en fin de mot (numéros d'épisode, dates)
        # Regex: cherche un séparateur suivi de chiffres, ou des chiffres en fin de chaine
        base = re.sub(r'[_ -]?\d+$', '', stem)
        base = re.sub(r'\d+', '', base) # Nettoyage agressif des chiffres restants
        
        # Nettoie les séparateurs multiples
        base = re.sub(r'[_\-\s]+', '_', base).strip('_')
        
        # On ne considère comme série que si la base est assez longue (évite les faux positifs sur "vidéo")
        return base if len(base) > 3 else None

class SmartMetadata:
    """
    Analyse intelligente des fichiers avec support de l'historique (Séries).
    INTELLIGENCE V4: Rotation de tags (Pools) pour éviter le fingerprinting algorithmique.
    """
    @staticmethod
    def derive_from_file(filepath_str: str, use_history: bool = True):
        path = Path(filepath_str)
        if not path.exists():
            return {"title": "Untitled Video", "description": "", "is_short": False}

        raw_name = path.stem
        # Titre propre : Remplace underscores/tirets et met en majuscules les premières lettres
        clean_title = raw_name.replace("_", " ").replace("-", " ").title()
        
        # 1. Gestion de l'Héritage (Séries)
        history = MetadataHistory.load()
        series_key = MetadataHistory.extract_series_key(raw_name)
        
        inherited_tags = []
        # On prépare une description de base si pas d'héritage
        final_description = ""
        
        if use_history and series_key and series_key in history:
            prev_data = history[series_key]
            # On vérifie que la donnée n'est pas trop vieille (ex: 30 jours)
            if time.time() - prev_data.get("last_seen", 0) < 30 * 86400:
                inherited_tags = prev_data.get("tags", [])
                jlog("intelligence", msg="Série détectée, application du contexte précédent", series=series_key)
        
        # 2. Déduction de tags avec ROTATION (Anti-Fingerprinting)
        # Structure: "key": {"mandatory": [...], "pool": [...]}
        keywords_map = {
            "gaming": {
                "mandatory": ["#gaming"],
                "pool": ["#gameplay", "#gamers", "#gaminglife", "#pcgaming", "#console", "#playstation", "#xbox", "#videogames", "#streamer"]
            },
            "tuto": {
                "mandatory": ["#tutorial", "#howto"],
                "pool": ["#education", "#learn", "#tips", "#tricks", "#guide", "#stepbystep", "#hack", "#lifehack", "#knowledge"]
            },
            "review": {
                "mandatory": ["#review"],
                "pool": ["#tech", "#unboxing", "#opinion", "#test", "#product", "#rating", "#gadget", "#comparison"]
            },
            "vlog": {
                "mandatory": ["#vlog"],
                "pool": ["#lifestyle", "#daily", "#life", "#story", "#travel", "#moment", "#diary", "#adventure"]
            },
            "minecraft": {
                "mandatory": ["#minecraft"],
                "pool": ["#mcpe", "#minecraftbuilds", "#minecrafter", "#blockgame", "#survival", "#creative", "#redstone", "#minecraftshorts"]
            },
            "fortnite": {
                "mandatory": ["#fortnite"],
                "pool": ["#battleroyale", "#fortniteclips", "#victoryroyale", "#epicgames", "#fortnitegame", "#fortnitememes"]
            },
            "finance": {
                "mandatory": ["#finance", "#trading"],
                "pool": ["#crypto", "#bitcoin", "#money", "#investing", "#stocks", "#wealth", "#business", "#entrepreneur", "#mindset"]
            }
        }
        
        tags = set(inherited_tags)
        lower_title = clean_title.lower()
        
        # Logique de détection par mots-clés
        for key, config in keywords_map.items():
            if key in lower_title:
                # Ajout des obligatoires
                for t in config["mandatory"]:
                    tags.add(t)
                
                # Ajout aléatoire depuis le pool (Rotation)
                # Cela garantit que chaque vidéo d'une même série a une signature unique
                pool = [t for t in config["pool"] if t not in tags]
                if pool:
                    # On pioche entre 2 et 4 tags supplémentaires au hasard
                    sample_size = min(len(pool), random.randint(2, 4))
                    random_tags = random.sample(pool, sample_size)
                    tags.update(random_tags)
        
        # 3. Logique Shorts (Détection auto basique via taille ou durée si disponible, ici taille)
        try:
            # Heuristique : Moins de 50MB est souvent un short ou TikTok
            is_likely_short = path.stat().st_size < 50 * 1024 * 1024 
        except:
            is_likely_short = False

        if is_likely_short:
            tags.add("#Shorts")
            tags.add("#ShortsVideo")
            tags.add("#fyp")
            
        final_tags_list = list(tags)
        # Mélange final pour ne pas avoir toujours le même ordre (évite détection bot)
        random.shuffle(final_tags_list)
        
        # Construction description
        final_description = f"{clean_title}\n\n{' '.join(final_tags_list)}"
        
        # 4. Sauvegarde pour le futur (Mise à jour de l'historique)
        if series_key:
            history[series_key] = {
                "last_seen": time.time(),
                "last_file": raw_name,
                "tags": final_tags_list # On sauve ceux utilisés cette fois-ci comme base future
            }
            MetadataHistory.save(history)

        return {
            "title": clean_title,
            "description": final_description,
            "tags": final_tags_list,
            "is_short": is_likely_short
        }

async def wait_and_click_semantic(page, keywords, role="button", timeout=5000):
    """Navigation Sémantique compatible Playwright"""
    if isinstance(keywords, str): keywords = [keywords]
    for keyword in keywords:
        try:
            # Regex insensible à la casse
            locator = page.get_by_role(role, name=re.compile(keyword, re.IGNORECASE))
            if await locator.count() > 0 and await locator.first.is_visible():
                btn = locator.first
                await btn.wait_for(state="visible", timeout=timeout)
                await btn.scroll_into_view_if_needed()
                await btn.click()
                return True
        except Exception:
            continue
    return False

# Snippets JS de masquage
def get_stealth_scripts():
    return [
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })",
        "Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] })",
        "window.chrome = { runtime: {} };",
        "Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });"
    ]