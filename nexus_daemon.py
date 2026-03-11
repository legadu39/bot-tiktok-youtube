# -*- coding: utf-8 -*-
### bot tiktok youtube/nexus_daemon.py
import asyncio
import sys
import os
import signal
import multiprocessing
import time
import shutil
import wave # Ajouté pour l'auto-réparation audio
from pathlib import Path
from typing import List, Optional

# Import composants NEXUS
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common import jlog, ensure_directories, resolve_path
from nexus_brain import NexusBrain
from nexus_arms import NexusArms

# --- WORKER FUNCTIONS ---

def launch_brain_process():
    """Wrapper pour lancer le Cerveau dans son propre process."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    jlog("init", msg="🧠 [Process Brain] Démarrage...")
    try:
        brain = NexusBrain()
        asyncio.run(brain.run_daemon())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        jlog("critical", msg="🔥 [Process Brain] Crash Fatal", error=str(e))
        sys.exit(1)

def launch_arms_process():
    """Wrapper pour lancer les Bras dans leur propre process."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    jlog("init", msg="💪 [Process Arms] Démarrage...")
    try:
        arms = NexusArms()
        asyncio.run(arms.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        jlog("critical", msg="🔥 [Process Arms] Crash Fatal", error=str(e))
        sys.exit(1)

# --- DAEMON CLASS ---

class NexusDaemon:
    """
    L'Orchestrateur (Daemon) - VERSION 9.0 (Lean Edition).
    ALLÉGÉ : Ne gère PLUS le Sentinel (Chrome).
    RÔLE : Surveillance des processus Brain (Command Center) et Arms (Uploader).
    """
    def __init__(self):
        self.running = False
        self.processes: List[multiprocessing.Process] = []
        
        # Crash History (Backoff Exponentiel)
        self.crash_history = {
            "NexusBrain-Proc": [],
            "NexusArms-Proc": []
        }
        self.BACKOFF_RESET_TIME = 3600
        self.MAX_BACKOFF_S = 300

    def _get_backoff_delay(self, proc_name: str) -> float:
        now = time.time()
        self.crash_history[proc_name] = [t for t in self.crash_history.get(proc_name, []) if now - t < self.BACKOFF_RESET_TIME]
        
        crash_count = len(self.crash_history[proc_name])
        if crash_count == 0: return 0.0
            
        delay = min(self.MAX_BACKOFF_S, (2 ** (crash_count - 1)))
        return float(delay)

    def preflight_checks(self):
        """
        🧠 INTELLIGENCE N°1 : Vérification Pré-vol (Fail-Fast Heuristique)
        Valide l'environnement avant de lancer les processus pour éviter un Late Failure.
        """
        jlog("init", msg="🔍 Lancement des vérifications pré-vol (Pre-flight checks)...")
        critical_errors = []
        warnings = []

        # 1. Vérification de FFMPEG (Critique)
        if not shutil.which("ffmpeg"):
            critical_errors.append("FFMPEG est introuvable dans le PATH système.")

        # 2. Vérification des Variables d'Environnement / Config
        if not os.environ.get("ELEVENLABS_API_KEY"):
            warnings.append("ELEVENLABS_API_KEY absente des variables d'environnement (Vérifiez le config.yaml si elle y est gérée).")

        # 3. Auto-réparation des assets mineurs (Graceful Degradation)
        try:
            sfx_path = resolve_path("assets_vault/sfx/synthetic_click.wav")
            if not os.path.exists(sfx_path):
                warnings.append(f"SFX manquant détecté : {sfx_path}. Auto-réparation en cours...")
                os.makedirs(os.path.dirname(sfx_path), exist_ok=True)
                # Création d'un fichier audio muet (silence) 100% valide pour MoviePy
                with wave.open(sfx_path, 'w') as f:
                    f.setnchannels(1)
                    f.setsampwidth(2)
                    f.setframerate(44100)
                    f.writeframes(b'')
                jlog("init", msg="🔧 Auto-réparation: Fichier synthétique audio vide généré avec succès.")
        except Exception as e:
            warnings.append(f"Impossible de vérifier ou réparer les assets audio : {e}")

        # Arrêt brutal si dépendance critique manquante
        if critical_errors:
            for err in critical_errors:
                jlog("critical", msg=f"❌ PREFLIGHT ERROR: {err}")
            raise RuntimeError("Échec fatal des Pre-flight checks. Démarrage annulé pour préserver les ressources.")
        
        # Affichage des avertissements non bloquants
        for w in warnings:
            jlog("warning", msg=f"⚠️ PREFLIGHT WARNING: {w}")
            
        jlog("init", msg="✅ Tous les systèmes sont nominaux. Autorisation de lancement accordée.")

    def start(self):
        self.running = True
        ensure_directories()
        
        jlog("init", msg="🚀 Démarrage de NEXUS AUTO V9.0 (Daemon Allégé)")
        
        # 🛡️ Appel de la nouvelle intelligence avant l'instanciation des processus
        self.preflight_checks()
        
        # Nettoyage préventif des signaux
        try:
            shutil.rmtree("./temp_signals", ignore_errors=True)
            os.makedirs("./temp_signals", exist_ok=True)
        except: pass

        # Setup Processus
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        # On lance Brain et Arms
        p_brain = multiprocessing.Process(target=launch_brain_process, name="NexusBrain-Proc")
        p_arms = multiprocessing.Process(target=launch_arms_process, name="NexusArms-Proc")
        
        self.processes = [p_brain, p_arms]

        for p in self.processes:
            p.start()
            jlog("info", msg=f"Processus lancé : {p.name} (PID: {p.pid})")

        # Boucle de surveillance simple
        try:
            while self.running:
                for p in list(self.processes): 
                    if not p.is_alive():
                        jlog("critical", msg=f"⚠️ Processus {p.name} mort.")
                        self.restart_process(p)
                
                # Le Daemon consomme très peu maintenant, pas besoin de check Sentinel
                time.sleep(10)
        except KeyboardInterrupt:
            self.handle_exit(None, None)

    def restart_process(self, dead_process):
        name = dead_process.name
        if dead_process in self.processes:
            self.processes.remove(dead_process)
            
        self.crash_history.setdefault(name, []).append(time.time())
        
        delay = self._get_backoff_delay(name)
        if delay > 0:
            jlog("warning", msg=f"⏳ Circuit Breaker {name}. Attente {delay}s...")
            time.sleep(delay)
        
        if "Brain" in name:
            new_p = multiprocessing.Process(target=launch_brain_process, name="NexusBrain-Proc")
        else:
            new_p = multiprocessing.Process(target=launch_arms_process, name="NexusArms-Proc")
        
        new_p.start()
        self.processes.append(new_p)
        jlog("retry", msg=f"♻️ {new_p.name} relancé.")

    def handle_exit(self, signum, frame):
        if not self.running: return
        self.running = False
        jlog("shutdown", msg="🛑 Arrêt du Daemon...")
        
        for p in self.processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=3)
                if p.is_alive(): p.kill()
        
        sys.exit(0)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    daemon = NexusDaemon()
    daemon.start()