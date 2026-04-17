# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/asset_vault.py
import os
import io
import json
import time
import shutil
import random
import re
import glob
import wave
import math
import struct
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# Imports Core
try:
    from common import jlog, CONFIG, resolve_path
except ImportError:
    # Fallback pour tests isolés
    def jlog(status, **kwargs): print(f"[{status.upper()}] {kwargs}")
    CONFIG = {"directories": {"assets": "./assets", "downloads": "./downloads"}}
    def resolve_path(p): return Path(p)

class AssetVault:
    """
    📚 THE LIBRARIAN (Asset Vault V4.3 - HYBRID STRATEGY + PROACTIVE SFX MODULE)
    Gère l'indexation, la recherche sémantique et le cycle de vie des assets visuels.
    INTELLIGENCE : 
    - Séparation Hook (Frais) vs Body (Recyclé).
    - Indexation Inversée & Matching Flou.
    - Repose sur la mutation visuelle (SceneAnimator) pour permettre un haut volume de réutilisation.
    - Ajout du module SFX pour scanner les banques audio (ex: Epic Stock Media).
    - [NOUVEAU] Auto-provisioning des SFX pour éviter les crashs silencieux.
    """
    
    INDEX_FILE = "vault_index.json"
    MAX_USAGE_COUNT = 15  
    SIMILARITY_THRESHOLD = 0.60  

    def __init__(self):
        self.assets_dir = resolve_path("assets_vault")
        self.downloads_dir = resolve_path("downloads")
        self.index_path = self.assets_dir / self.INDEX_FILE
        
        # --- CORRECTION CHEMINS SFX (ROBUSTESSE) ---
        # Configuration SFX via le YAML avec validation du chemin
        configured_sfx = CONFIG.get("directories", {}).get(
            "sfx_folder", 
            r"C:\Users\Mathieu\Desktop\Gemini headless\assets\Epic Stock Media - Smart UI\One_Shots\Favorites"
        )
        
        if configured_sfx and os.path.exists(configured_sfx):
            self.sfx_dir = configured_sfx
        else:
            # Fallback sur un dossier local si le dossier distant/YAML n'existe pas
            self.sfx_dir = self.assets_dir / "sfx"
            jlog("warning", msg=f"Chemin SFX configuré introuvable, utilisation du fallback interne : {self.sfx_dir}")

        # Création structure
        os.makedirs(self.sfx_dir, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # Chargement Mémoire
        self.index = self._load_index()
        self._sync_index_integrity() # Auto-réparation au démarrage
        
        # Initialisation du module audio
        self.sfx_cache = self._index_sfx()
        self._validate_or_provision_sfx() # 🚀 INTEL N°1: Auto-Provisioning

    def _load_index(self) -> Dict:
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                jlog("warning", msg="Index Vault corrompu, réinitialisation.", error=str(e))
        return {"assets": [], "last_sync": 0}

    def _save_index(self):
        self.index["last_sync"] = time.time()
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            jlog("error", msg="Echec sauvegarde index Vault", error=str(e))

    def _sync_index_integrity(self):
        valid_assets = []
        for asset in self.index.get("assets", []):
            if os.path.exists(asset["local_path"]):
                valid_assets.append(asset)
        
        if len(valid_assets) != len(self.index.get("assets", [])):
            jlog("maintenance", msg=f"Nettoyage Index : {len(self.index['assets']) - len(valid_assets)} fantômes supprimés.")
            self.index["assets"] = valid_assets
            self._save_index()

    # -------------------------------------------------------------------------
    # MODULE SFX (SOUND DESIGN)
    # -------------------------------------------------------------------------
    def _index_sfx(self) -> Dict[str, List[str]]:
        """Indexe les bruitages (SFX) par catégorie sémantique."""
        sfx_index = {'pop': [], 'whoosh': [], 'success': [], 'click': []}
        
        if not self.sfx_dir or not os.path.exists(self.sfx_dir):
            jlog("warning", msg=f"Dossier SFX introuvable ou non configuré : {self.sfx_dir}")
            return sfx_index
            
        for file in glob.glob(os.path.join(self.sfx_dir, "*.wav")):
            filename = os.path.basename(file).lower()
            
            if 'pop' in filename or 'bubble' in filename:
                sfx_index['pop'].append(file)
            elif 'swipe' in filename or 'whoosh' in filename or 'transition' in filename:
                sfx_index['whoosh'].append(file)
            elif 'success' in filename or 'chime' in filename or 'bell' in filename:
                sfx_index['success'].append(file)
            else:
                sfx_index['click'].append(file)
                
        counts = {k: len(v) for k, v in sfx_index.items()}
        jlog("vault", msg="🎶 SFX Vault Indexé", stats=counts)
        return sfx_index

    def _validate_or_provision_sfx(self):
        """🚀 INTEL N°1 : Génère un bruit de clic de secours si le dossier SFX est vide."""
        if not any(self.sfx_cache.values()):
            jlog("warning", msg="Aucun SFX trouvé. Auto-génération d'un 'click' de secours...")
            # Utilise self.sfx_dir défini dans l'__init__ pour garantir que le fallback fonctionne
            fallback_path = Path(self.sfx_dir) / "synthetic_click.wav"
            
            if not fallback_path.exists():
                self._generate_synthetic_click(str(fallback_path))
                
            if fallback_path.exists():
                self.sfx_cache['click'].append(str(fallback_path))

    def _generate_synthetic_click(self, path: str):
        """Génère un signal audio (click percussif) mathématiquement sans fichier source."""
        try:
            with wave.open(path, 'w') as wav_file:
                nchannels, sampwidth, framerate = 1, 2, 44100
                nframes = int(framerate * 0.05) # 50 millisecondes
                wav_file.setparams((nchannels, sampwidth, framerate, nframes, "NONE", "not compressed"))
                for i in range(nframes):
                    # Génération d'un Transient (décroissance exponentielle rapide)
                    value = int(32767 * math.exp(-i/(framerate*0.01)) * math.sin(2 * math.pi * 1000 * i / framerate))
                    wav_file.writeframesraw(struct.pack('<h', value))
            jlog("success", msg=f"SFX de secours généré : {path}")
        except Exception as e:
            jlog("error", msg=f"Échec création SFX synthétique : {e}")

    def get_random_sfx(self, category="pop") -> Optional[str]:
        if category in self.sfx_cache and self.sfx_cache[category]:
            return random.choice(self.sfx_cache[category])
        all_sfx = [f for sfx_list in self.sfx_cache.values() for f in sfx_list]
        if all_sfx:
            return random.choice(all_sfx)
        return None

    # -------------------------------------------------------------------------
    # INTELLIGENCE SÉMANTIQUE (VISUELLE)
    # -------------------------------------------------------------------------
    def _tokenize(self, text: str) -> set:
        if not text: return set()
        text = text.lower().replace("'", " ").replace("-", " ")
        words = re.findall(r'\w+', text)
        stop_words = {
            "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou", "a", "en", "sur", "pour", "par",
            "the", "a", "an", "of", "and", "or", "in", "on", "for", "by", "to", "with", "is", "image", "photo", "generate"
        }
        return {w for w in words if w not in stop_words and len(w) > 2}

    def _calculate_similarity(self, query_tokens: set, asset_tokens: set) -> float:
        if not query_tokens or not asset_tokens: return 0.0
        intersection = query_tokens.intersection(asset_tokens)
        union = query_tokens.union(asset_tokens)
        return len(intersection) / len(union)

    # -------------------------------------------------------------------------
    # API PUBLIQUE
    # -------------------------------------------------------------------------
    def find_best_match(self, query: str, context_tags: List[str] = [], is_hook: bool = False) -> Optional[Dict]:
        if is_hook:
            jlog("vault", msg="🔒 HOOK DETECTED -> Bypassing Vault to force fresh generation.")
            return None

        q_tokens = self._tokenize(query)
        for tag in context_tags:
            q_tokens.add(tag.lower())

        candidates = []
        for asset in self.index["assets"]:
            if asset.get("usage_count", 0) >= self.MAX_USAGE_COUNT:
                continue

            asset_tokens = set(asset.get("keywords", []))
            score = self._calculate_similarity(q_tokens, asset_tokens)
            
            if score >= self.SIMILARITY_THRESHOLD:
                candidates.append((score, asset))

        if not candidates:
            jlog("vault", msg=f"No match for '{query[:30]}...' (Body context)")
            return None

        candidates.sort(key=lambda x: (x[0], -x[1].get("usage_count", 0)), reverse=True)
        best_score, best_asset = candidates[0]
        jlog("vault", msg=f"♻️ MATCH FOUND (Score: {best_score:.2f}, Used: {best_asset.get('usage_count',0)}) : {Path(best_asset['local_path']).name}")
        
        return best_asset

    def register_asset(self, local_path: str, prompt: str, source: str = "generated", meta_content: str = ""):
        path_obj = Path(local_path)
        if not path_obj.exists(): return

        final_path = self.assets_dir / path_obj.name
        if final_path.exists():
             new_name = f"{path_obj.stem}_{int(time.time())}{path_obj.suffix}"
             final_path = self.assets_dir / new_name

        if path_obj.parent != self.assets_dir:
            try:
                shutil.copy2(str(path_obj), str(final_path))
            except Exception as e:
                jlog("error", msg=f"Copy error to vault: {e}")
                return str(path_obj)
        
        tokens = self._tokenize(prompt)
        if meta_content:
            tokens.update(self._tokenize(meta_content))

        asset_entry = {
            "id": f"AST_{int(time.time())}_{random.randint(1000,9999)}",
            "local_path": str(final_path),
            "prompt": prompt,
            "keywords": list(tokens),
            "source": source,
            "created_at": time.time(),
            "last_used": 0,
            "usage_count": 0
        }
        
        self.index["assets"].append(asset_entry)
        self._save_index()
        jlog("vault", msg=f"Indexed new asset: {final_path.name}")
        return str(final_path)

    def mark_as_used(self, local_path: str):
        found = False
        for asset in self.index["assets"]:
            if Path(asset["local_path"]).name == Path(local_path).name:
                asset["usage_count"] = asset.get("usage_count", 0) + 1
                asset["last_used"] = time.time()
                found = True
                break
        if found:
            self._save_index()

    # -------------------------------------------------------------------------
    # PEXELS AUTO-FEED
    # -------------------------------------------------------------------------

    _FR_TO_EN = {
        "argent": "money", "argents": "money", "finances": "finance", "financier": "finance",
        "trading": "trading", "trader": "trader", "bourse": "stock market",
        "investissement": "investment", "investir": "investment",
        "graphique": "chart", "graphiques": "chart",
        "entreprise": "business", "entreprises": "business",
        "stratégie": "strategy", "stratégies": "strategy",
        "succès": "success", "réussite": "success",
        "comptable": "accounting", "comptabilité": "accounting",
        "fiscalité": "tax", "impôt": "tax", "impôts": "tax",
        "croissance": "growth", "profit": "profit", "gain": "gain",
        "smartphone": "smartphone", "téléphone": "phone",
        "ordinateur": "computer", "écran": "screen",
        "cerveau": "brain", "feu": "fire", "fusée": "rocket",
        "diamant": "diamond", "cadenas": "lock", "alerte": "alert",
        "données": "data", "code": "code", "technologie": "technology",
        "marché": "market", "économie": "economy",
        "main": "hand", "mains": "hands", "bureau": "desk", "travail": "work",
        "réunion": "meeting", "équipe": "team", "personne": "person",
        "homme": "man", "femme": "woman", "affaires": "business",
        "propriété": "property", "immobilier": "real estate",
        "voiture": "car", "nature": "nature", "ville": "city",
    }

    def _extract_pexels_query(self, description: str) -> str:
        clean = re.sub(r'\[.*?\]', '', description).strip()
        words = re.findall(r'[a-zA-ZÀ-ÿ]+', clean)
        stop_fr = {
            "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou",
            "en", "sur", "pour", "par", "avec", "dans", "que", "qui", "est",
            "sont", "une", "aux", "au", "ce", "cette", "ces", "son", "sa",
            "ses", "leur", "leurs", "il", "elle", "ils", "elles", "on",
            "the", "a", "an", "of", "and", "or", "in", "on", "for", "by",
            "to", "with", "is", "image", "photo", "generate", "cinematic",
            "abstract", "background", "pattern", "repeater", "grid",
        }
        keywords = []
        for w in words:
            w_low = w.lower()
            if w_low in stop_fr or len(w_low) < 3:
                continue
            translated = self._FR_TO_EN.get(w_low, w_low)
            if translated not in keywords:
                keywords.append(translated)
            if len(keywords) >= 3:
                break
        return " ".join(keywords) if keywords else ""

    def fetch_and_cache(self, description: str, timeout: int = 5) -> Optional[str]:
        """
        Cherche une photo Pexels correspondant à la description, la redimensionne
        en 1080×1920 et la met en cache dans assets_vault/.
        Retourne le chemin local ou None en cas d'échec.
        """
        import requests
        from PIL import Image as _PIL

        api_key = os.getenv("PEXELS_API_KEY", "")
        if not api_key or api_key in ("YOUR_PEXELS_KEY_HERE", ""):
            return None

        query = self._extract_pexels_query(description)
        if not query:
            return None

        query_hash = hashlib.md5(query.lower().encode()).hexdigest()[:12]
        cache_path = self.assets_dir / f"pexels_{query_hash}.jpg"

        # Cache hit — index
        for asset in self.index.get("assets", []):
            if asset.get("pexels_query_hash") == query_hash:
                lp = asset.get("local_path", "")
                if os.path.exists(lp):
                    return lp

        # Cache hit — fichier sur disque (index désynchronisé)
        if cache_path.exists():
            return str(cache_path)

        # Appel API
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": 5,
                    "size": "large",
                },
                timeout=timeout,
            )
        except Exception as e:
            jlog("warning", msg=f"[VAULT] Pexels search timeout/error: {e}")
            return None

        if resp.status_code != 200:
            jlog("warning", msg=f"[VAULT] Pexels API {resp.status_code} pour '{query}'")
            return None

        photos = resp.json().get("photos", [])
        if not photos:
            jlog("vault", msg=f"[VAULT] Pexels: aucune photo pour '{query}'")
            return None

        # Meilleure photo : portrait le plus grand
        best = max(photos, key=lambda p: p.get("height", 0))
        src = best.get("src", {})
        img_url = src.get("original") or src.get("large2x") or src.get("large")
        pexels_id = best.get("id", "")

        if not img_url:
            return None

        # Téléchargement
        try:
            img_resp = requests.get(img_url, timeout=timeout)
        except Exception as e:
            jlog("warning", msg=f"[VAULT] Pexels download timeout: {e}")
            return None

        if img_resp.status_code != 200:
            return None

        # Crop centré + resize 1080×1920
        try:
            img = _PIL.open(io.BytesIO(img_resp.content)).convert("RGB")
            target_w, target_h = 1080, 1920
            img_w, img_h = img.size
            scale = max(target_w / img_w, target_h / img_h)
            new_w, new_h = int(img_w * scale), int(img_h * scale)
            resample = getattr(_PIL, "LANCZOS", getattr(_PIL, "Resampling", None))
            if hasattr(resample, "LANCZOS"):
                resample = resample.LANCZOS
            img = img.resize((new_w, new_h), resample)
            left = (new_w - target_w) // 2
            top  = (new_h - target_h) // 2
            img  = img.crop((left, top, left + target_w, top + target_h))
            img.save(str(cache_path), quality=90, optimize=True)
        except Exception as e:
            jlog("warning", msg=f"[VAULT] Pexels image processing error: {e}")
            return None

        # Enregistrement dans l'index
        tokens = self._tokenize(description)
        tokens.update(self._tokenize(query))
        asset_entry = {
            "id":                 f"AST_{int(time.time())}_{random.randint(1000, 9999)}",
            "local_path":         str(cache_path),
            "prompt":             description,
            "keywords":           list(tokens),
            "source":             "pexels",
            "pexels_id":          pexels_id,
            "pexels_query":       query,
            "pexels_query_hash":  query_hash,
            "created_at":         time.time(),
            "last_used":          0,
            "usage_count":        0,
        }
        self.index.setdefault("assets", []).append(asset_entry)
        self._save_index()
        jlog("vault", msg=f"[VAULT] Pexels → '{query}' sauvegardé ({cache_path.name})")
        return str(cache_path)

    async def fetch_image(self, query: str, keywords: List[str] = []) -> str:
        match = self.find_best_match(query, keywords, is_hook=False)
        if match:
            return match["local_path"]
        return None