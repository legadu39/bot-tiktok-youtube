import json
import os
import time
from typing import Dict, Optional, List, Tuple

class SelectorCache:
    def __init__(self, cache_path: str = "inputs_cache.json"):
        self.cache_path = cache_path
        self.cache_data = self._load_cache()

    def _load_cache(self) -> Dict:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        return {}
                    if not isinstance(content, dict):
                         return {}
                    return content
            except Exception:
                return {}
        return {}

    def get_best_selector(self, key: str) -> Optional[str]:
        """
        Analyse les candidats disponibles pour une clé donnée et retourne 
        le sélecteur ayant le score de confiance le plus élevé, pondéré par le temps.
        """
        if not key or not isinstance(key, str): return None
        
        entry = self.cache_data.get(key)
        if not entry:
            return None
        
        if isinstance(entry, str):
            return entry

        candidates = entry.get("candidates", [])
        if not candidates:
            return entry.get("selector")

        ranked = self._get_ranked_candidates(candidates)
        
        if not ranked:
            return None
            
        best_selector, best_score = ranked[0]
        
        if best_score > -10:
            return best_selector
        return None

    def _get_ranked_candidates(self, candidates: List[Dict]) -> List[Tuple[str, float]]:
        """
        Retourne une liste de tuples (selecteur, score_effectif) triée par pertinence.
        Applique une décroissance temporelle (Time Decay).
        """
        now = time.time()
        ranked = []
        
        for c in candidates:
            # Calcul de l'ancienneté en jours
            last_used = c.get("last_used", now)
            days_unused = (now - last_used) / 86400.0
            
            # Pénalité : 0.5 point par jour d'inactivité
            decay = days_unused * 0.5
            raw_score = c.get("score", 0)
            
            # Le score effectif ne modifie pas la donnée stockée
            effective_score = raw_score - decay
            
            ranked.append((c["selector"], effective_score))
            
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def set_selector(self, key: str, selector: str, success: bool = True):
        """
        Enregistre ou met à jour un sélecteur avec un système de scoring dynamique.
        """
        if not key or not isinstance(key, str): return
        
        # Initialisation sécurisée de la structure
        if key not in self.cache_data or not isinstance(self.cache_data[key], dict):
             # Si c'était une string (vieux format), on la récupère comme point de départ
             old_selector = self.cache_data.get(key) if isinstance(self.cache_data.get(key), str) else None
             self.cache_data[key] = {"candidates": []}
             if old_selector:
                self.cache_data[key]["candidates"].append({
                    "selector": old_selector,
                    "score": 5,
                    "last_used": time.time()
                })

        # Double check post-initialisation
        if "candidates" not in self.cache_data[key]:
             self.cache_data[key]["candidates"] = []

        candidates = self.cache_data[key]["candidates"]
        
        found = False
        for c in candidates:
            if c.get("selector") == selector:
                if success:
                    c["score"] = min(c.get("score", 0) + 1, 50) 
                else:
                    c["score"] = c.get("score", 0) - 5 
                
                c["last_used"] = time.time()
                found = True
                break
        
        if not found and success:
            candidates.append({
                "selector": selector,
                "score": 1,
                "last_used": time.time()
            })

        # Nettoyage préventif
        self.cache_data[key]["candidates"] = sorted(
            [c for c in candidates if c.get("score", 0) > -15],
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:5]

        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # --- Alias de compatibilité pour ui_interaction.py ---
    
    def get(self, key: str) -> Optional[str]:
        return self.get_best_selector(key)

    def set(self, key: str, selector: str, success: bool = True):
        self.set_selector(key, selector, success)

# Alias pour compatibilité descendante
InputLocatorCache = SelectorCache