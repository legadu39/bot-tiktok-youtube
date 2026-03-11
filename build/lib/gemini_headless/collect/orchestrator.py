# gemini_headless/collect/orchestrator.py
from __future__ import annotations
import asyncio, time, os, inspect, traceback, re, json
from collections import deque
from typing import Dict, Optional, Tuple, Any, Callable, List, Set
from playwright.async_api import Page

try:
    from .utils.logs import jlog
except ImportError:
    import sys
    def jlog(evt="unknown", **_k): pass

# --- Imports des Producteurs ---
try:
    from .producers.sse import SSEProducer
    from .producers.ws import WSProducer
    from .producers.be import BEProducer, parse_gemini_response_intelligent_v14
    from .producers.dom import DOMProducer, _GET_BEST_TEXT_JS
    from .filters.cleaner import clean_text_with_stats, clean_text
except ImportError:
    # Stubs minimaux pour éviter le crash si appel partiel
    class BaseProducerPlaceholder:
        def __init__(self, *args, **kwargs): self.done = False
        async def snapshot_now(self): return {"text": ""}
    SSEProducer = WSProducer = BEProducer = DOMProducer = BaseProducerPlaceholder
    async def parse_gemini_response_intelligent_v14(*args, **kwargs): return None
    def clean_text_with_stats(x, **k): return x, {}

# ============================================================================
# CONFIGURATION V3 : SENTINELLES STRICTES & VÉLOCITÉ
# ============================================================================
SENTINELS = ("<<NEXUS_END>>", "<>")

PRIO = ["sse", "ws", "be", "dom"]

class IntelligentGenerationCompleteDetector:
    """
    Détecteur V4 (Velocity-Based): Analyse le flux texte pour trouver le marqueur de fin
    OU détecter une stagnation/extension basée sur la vitesse de génération.
    """
    def __init__(self):
        self.total_cycles = 0
        self.hard_limit_cycles = 600 # ~5 minutes par défaut (0.5s par cycle)
        
        # Velocity Tracking
        self.last_text_len = 0
        self.velocity_history = deque(maxlen=10) # Fenêtre glissante des 10 derniers cycles
        self.extended_count = 0
        self.max_extensions = 5 # On peut étendre 5 fois max (5 x 100 cycles)

    def analyze_generation_complete(self, current_text: str, aria_busy: bool = True) -> tuple[bool, str]:
        """Retourne (is_complete, reason)"""
        self.total_cycles += 1
        current_len = len(current_text)
        
        # 1. Calcul de la vélocité (chars par cycle)
        delta = current_len - self.last_text_len
        # On ignore les deltas négatifs (nettoyage) pour la moyenne
        if delta >= 0:
            self.velocity_history.append(delta)
        
        self.last_text_len = current_len
        
        avg_velocity = 0.0
        if self.velocity_history:
            avg_velocity = sum(self.velocity_history) / len(self.velocity_history)

        # 2. Check Sentinelle (Preuve absolue - Priorité 1)
        for s in SENTINELS:
            if s in current_text:
                return True, f"sentinel_detected_{s}"

        # 3. Heuristique de Stagnation Dynamique (Auto-Cut)
        # Si après 50 cycles (~25s) on produit moins de 0.5 char/cycle en moyenne, c'est mort.
        if self.total_cycles > 50 and avg_velocity < 0.5:
            # Sécurité: on vérifie qu'on n'est pas juste au tout début d'un gros bloc de code
            # Si aria-busy est false, c'est encore plus suspect
            if not aria_busy:
                return True, f"velocity_stalled_avg_{avg_velocity:.2f}"
            # Si c'est busy mais très lent pendant longtemps
            if self.total_cycles > 100 and avg_velocity < 0.2:
                return True, "deep_stagnation"

        # 4. Heuristique d'Extension de Temps (Auto-Extend)
        # Si on approche de la limite (ex: cycle 550/600) MAIS que la vélocité est haute (> 20 chars/cycle)
        # C'est que Gemini est en train de coder furieusement, on ne coupe pas !
        if self.total_cycles > (self.hard_limit_cycles - 50) and avg_velocity > 15:
            if self.extended_count < self.max_extensions:
                self.hard_limit_cycles += 100
                self.extended_count += 1
                return False, f"generating_extended_high_velocity_{avg_velocity:.1f}"

        # 5. Check Timeout Ultime (Sécurité)
        if self.total_cycles > self.hard_limit_cycles: 
            return True, "hard_timeout_limit_reached"
            
        return False, "generating"

class Orchestrator:
    """
    Superviseur de collecte. Écoute tous les canaux (SSE, WS, DOM)
    et s'arrête dès que la sentinelle V3 est reçue ou décision heuristique.
    """
    def __init__(self, page: Page, stagnation_timeout_ms: int = 180000, **kwargs):
        self.page = page
        self.stagnation_timeout_ms = stagnation_timeout_ms
        
        # Initialisation des producteurs
        self.sse = SSEProducer(page, self._on_progress("sse"), self._on_done)
        self.ws = WSProducer(page, self._on_progress("ws"), self._on_done)
        self.be = BEProducer(page, self._on_progress("be"), self._on_done)
        self.dom = DOMProducer(page, self._on_progress("dom"), self._on_done)
        
        self._buf = {k: "" for k in PRIO}
        self._done_evt = asyncio.Event()
        self._exit_code = 1
        self._emit_text = ""
        self._emit_meta = {}

    def _on_progress(self, src: str):
        def _cb(chunk: str):
            if self._done_evt.is_set(): return
            
            # Accumulation simple
            self._buf[src] = (self._buf.get(src, "") + chunk)[-1000000:] # Capacité augmentée pour gros code
            
            # Check rapide de sentinelle pour sortir au plus vite (Fast Path)
            if any(s in chunk for s in SENTINELS):
                jlog("fast_exit_sentinel_in_chunk", src=src)
                self._on_done(src)
        return _cb

    async def _on_done(self, src: str, final_text: str = None, **kwargs):
        """Appelé quand un producteur pense avoir fini ou sur détection."""
        if self._done_evt.is_set(): return
        
        # Consolidation du texte
        text = final_text if final_text else self._buf.get(src, "")
        
        # Nettoyage Sentinelle
        for s in SENTINELS:
            if s in text:
                # On coupe tout ce qui est après la sentinelle (garbage)
                text = text.split(s)[0].strip()
                self._emit_text = text
                self._emit_meta = {"source": src, "clean_exit": True}
                self._exit_code = 0
                self._done_evt.set()
                return

    def _buffer_consolidate(self) -> str:
        """Retourne le buffer le plus long/complet."""
        # Priorité : SSE > WS > DOM
        best_len = 0
        best_txt = ""
        for k in ["sse", "ws", "dom"]:
            curr = self._buf.get(k, "")
            if len(curr) > best_len:
                best_len = len(curr)
                best_txt = curr
        return best_txt

    async def runfastpath(self) -> Tuple[str, Dict, int, int]:
        """Boucle principale d'attente (Blocking)."""
        
        # Démarrage
        await asyncio.gather(
            self.sse.start(), self.ws.start(), self.be.start(), self.dom.start(),
            return_exceptions=True
        )
        
        start_ts = time.monotonic()
        detector = IntelligentGenerationCompleteDetector()
        
        try:
            while not self._done_evt.is_set():
                # Timeout global de sécurité (Watchdog ultime)
                if (time.monotonic() - start_ts) * 1000 > (self.stagnation_timeout_ms * 1.5):
                    jlog("orchestrator_watchdog_timeout", level="ERROR")
                    break
                
                # Consolidation et Analyse
                current_text = self._buffer_consolidate()
                
                # On check aussi l'attribut busy du DOM pour aider l'heuristique
                aria_busy = False
                try:
                    # Check léger, on ne veut pas bloquer
                    # aria_busy = await self.page.get_attribute("...", "aria-busy") == "true"
                    pass 
                except: pass

                is_done, reason = detector.analyze_generation_complete(current_text, aria_busy)
                
                if is_done:
                    jlog("orchestrator_decision", reason=reason)
                    # Force le flush du meilleur buffer
                    await self._on_done("consolidated", current_text)
                    break
                
                # Si l'heuristique a étendu le temps, on log de temps en temps
                if "extended" in reason and detector.total_cycles % 20 == 0:
                     jlog("orchestrator_extending", reason=reason, cycles=detector.total_cycles)
                
                await asyncio.sleep(0.5)
                
        finally:
            await self._stop_all()
            
        return self._emit_text, self._emit_meta, self._exit_code, 0

    async def _stop_all(self):
        for prod in [self.sse, self.ws, self.be, self.dom]:
            if hasattr(prod, "stop"):
                await prod.stop()