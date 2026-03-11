### timeout_manager.py
import os
import time
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

class CrossProcessTimeoutManager:
    """
    Gestionnaire de timeout partagé entre les processus (CLI, Browser, Workers).
    Permet la synchronisation de l'état réseau (latence), des signaux de vie (Heartbeat)
    et du Circuit Breaker.
    INTELLIGENCE V4 : Profilage Horaire (Adaptive Pacing)
    """
    def __init__(self, context_id: str = "default"):
        self.context_id = context_id
        # Utilisation du dossier temporaire système pour éviter les problèmes de droits/chemins
        self.temp_dir = Path(tempfile.gettempdir()) / "gemini_headless_stats"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.stats_file = self.temp_dir / f"network_stats_{context_id}.json"
        self.heartbeat_file = self.temp_dir / f"worker_heartbeat_{context_id}.ts"
        self.circuit_file = self.temp_dir / f"circuit_breaker_{context_id}.json"
        
        # Initialisation si absent
        if not self.stats_file.exists():
            self._save_stats({"latency_avg": 1000.0, "samples": 0, "hourly_latency": {}})
        
        if not self.circuit_file.exists():
            self._save_json(self.circuit_file, {"failures": 0, "last_failure_ts": 0, "is_open": False})

    def _load_json(self, path: Path, default: Any = None) -> Any:
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return default

    def _save_json(self, path: Path, data: Any):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_stats(self) -> dict:
        return self._load_json(self.stats_file, {"latency_avg": 1000.0, "samples": 0, "hourly_latency": {}})

    def _save_stats(self, stats: dict):
        self._save_json(self.stats_file, stats)

    # --- Network Stats & Pacing (Intelligent) ---

    def get_network_stats(self) -> float:
        """Retourne la latence moyenne actuelle en ms."""
        stats = self._load_stats()
        return float(stats.get("latency_avg", 1000.0))

    def update_network_stats(self, latency_ms: float):
        """Met à jour la moyenne mobile de la latence ET le profil horaire."""
        if latency_ms <= 0: return
        
        stats = self._load_stats()
        current = stats.get("latency_avg", 1000.0)
        samples = stats.get("samples", 0)
        
        # Moyenne mobile pondérée globale (Alpha = 0.2)
        new_avg = (current * 0.8) + (latency_ms * 0.2)
        
        # Profilage Horaire (Learning)
        hour = str(time.localtime().tm_hour)
        hourly = stats.get("hourly_latency", {})
        hour_avg = hourly.get(hour, new_avg)
        
        # Mise à jour de la moyenne horaire
        hourly[hour] = (hour_avg * 0.9) + (latency_ms * 0.1)
        
        stats["latency_avg"] = new_avg
        stats["samples"] = samples + 1
        stats["hourly_latency"] = hourly
        
        self._save_stats(stats)

    def get_adaptive_multiplier(self) -> float:
        """Calcul un multiplicateur de timeout basé sur l'heure actuelle."""
        stats = self._load_stats()
        hour = str(time.localtime().tm_hour)
        hourly = stats.get("hourly_latency", {})
        
        current_hour_latency = hourly.get(hour)
        global_avg = stats.get("latency_avg", 1000.0)
        
        if current_hour_latency and global_avg > 0:
            # Si cette heure est historiquement plus lente, on augmente le temps
            ratio = current_hour_latency / global_avg
            # On borne le ratio entre 0.8 (rapide) et 2.5 (très lent)
            return max(0.8, min(ratio, 2.5))
        
        return 1.0

    # --- Timeouts Configuration (Setters & Getters) ---

    def set_timeouts(self, heartbeat_s: float = 120.0, generation_s: float = 480.0, activity_probe_s: float = 15.0, **kwargs):
        """Enregistre les timeouts calculés dynamiquement par le CLI."""
        stats = self._load_stats()
        stats["config"] = {
            "heartbeat_s": heartbeat_s,
            "generation_s": generation_s,
            "activity_probe_s": activity_probe_s,
            "updated_ts": time.time(),
            **kwargs
        }
        self._save_stats(stats)

    def get_generation_timeout_s(self) -> float:
        """
        Récupère le timeout de génération configuré APPLIQUÉ au multiplicateur horaire.
        """
        stats = self._load_stats()
        config = stats.get("config", {})
        base_timeout = float(config.get("generation_s", 480.0))
        
        multiplier = self.get_adaptive_multiplier()
        final_timeout = base_timeout * multiplier
        
        return final_timeout

    def get_heartbeat_timeout_s(self) -> float:
        """Récupère le timeout de heartbeat configuré."""
        stats = self._load_stats()
        config = stats.get("config", {})
        return float(config.get("heartbeat_s", 120.0))

    # --- Heartbeat & Activity ---

    def signal_worker_activity(self, is_progress: bool = False, extension_s: float = 30.0, reason: str = "unknown"):
        """Signale que le worker est actif."""
        try:
            now = time.time()
            data = {
                "last_beat": now,
                "is_progress": is_progress,
                "extension_request": extension_s,
                "reason": reason
            }
            self._save_json(self.heartbeat_file, data)
        except Exception:
            pass

    def extend_on_activity(self, seconds: float):
        """Alias compatible."""
        self.signal_worker_activity(extension_s=seconds, reason="alias_call")

    def get_last_heartbeat(self) -> float:
        try:
            if self.heartbeat_file.exists():
                return self.heartbeat_file.stat().st_mtime
        except Exception:
            pass
        return 0.0

    # --- Circuit Breaker ---

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Retourne l'état du disjoncteur."""
        data = self._load_json(self.circuit_file, {"failures": 0, "is_open": False})
        return data

    def report_failure(self, error_type: str = "unknown"):
        """Signale une erreur critique."""
        data = self.get_circuit_breaker_status()
        data["failures"] = data.get("failures", 0) + 1
        data["last_failure_ts"] = time.time()
        
        # Seuil basique : 3 erreurs consécutives sans reset = Open
        if data["failures"] >= 3:
            data["is_open"] = True
            
        self._save_json(self.circuit_file, data)

    def reset_circuit(self):
        """Réinitialise le disjoncteur (succès observé)."""
        self._save_json(self.circuit_file, {"failures": 0, "is_open": False, "reset_ts": time.time()})

    # --- Headless Specifics (Compatibilité Connector) ---

    def reset_headless_failures(self):
        """
        Réinitialise les compteurs d'échecs.
        Appelé par GeminiConnector lors d'un succès.
        """
        self.reset_circuit()

    def record_headless_failure(self):
        """
        Enregistre un échec critique venant du connecteur.
        Appelé par GeminiConnector lors d'un crash.
        """
        self.report_failure("headless_crash")