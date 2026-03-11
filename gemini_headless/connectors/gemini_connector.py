### Gemini headless/gemini_headless/connectors/gemini_connector.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Gemini Headless — Connector (Critical Mode++)
Objectif : piloter l’UI avec intelligence adaptative (Pacing, Healing, Strategy).
Updates V_Final: 
- Semantic Timeouts (Ajustement du temps d'attente selon complexité prompt)
- Maintenance Prédictive (Heartbeat Loop en tâche de fond)
- Verrouillage d'état (_is_busy) pour coordination
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from playwright.async_api import Page

# Imports internes
try:
    from .page_manager import prepare_page  # type: ignore
except Exception:
    async def prepare_page(cfg: Any, *, logger=None, network_debug: bool = False, consent_timeout_s: float = 4.0) -> Dict[str, Any]:
        raise RuntimeError("prepare_page not available")

try:
    from .network_sniffer import GeminiNetworkTap  # type: ignore
except Exception:
    GeminiNetworkTap = None

try:
    from .awaiter_engine import build_awaiter, await_answer  # type: ignore
except Exception:
    async def build_awaiter(page, sniffer=None, logger=None, **kwargs):
        raise RuntimeError("build_awaiter not available")
    async def await_answer(awaiter, dom_snaps=None, t0_ms=None, logger=None, **kwargs):
        raise RuntimeError("await_answer not available")

from .ui_interaction import InputHandler, SubmitHandler

# Import Smart Pacing Manager - LOGIQUE ROBUSTE (Fix Path Hell)
try:
    # 1. Tentative d'import standard (si PYTHONPATH est correct)
    from timeout_manager import CrossProcessTimeoutManager
except ImportError:
    try:
        # 2. Tentative de résolution relative depuis la racine du projet
        # On remonte de gemini_headless/connectors/ (2 niveaux) vers gemini_headless (3) vers root (4)
        project_root = Path(__file__).resolve().parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.append(str(project_root))
        from timeout_manager import CrossProcessTimeoutManager
    except ImportError:
        # 3. Fallback Mock pour ne pas crasher le connecteur si le manager est absent
        class CrossProcessTimeoutManager:
            def __init__(self, *args, **kwargs): pass
            def get_network_stats(self): return 1000.0
            def update_network_stats(self, val): pass
            def set_timeouts(self, *args, **kwargs): pass
            # --- PATCH: Méthodes ajoutées pour éviter AttributeError ---
            def reset_headless_failures(self): pass
            def record_headless_failure(self): pass
            def signal_worker_activity(self, *args, **kwargs): pass

# -----------------------------------------------------------------------------
# Logging helper
# -----------------------------------------------------------------------------

def _jlog(logger, evt: str, **payload) -> None:
    payload.setdefault("ts", time.time())
    rec = {"evt": evt, **payload}
    try:
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        line = json.dumps({"evt": evt, "unserializable": True}, ensure_ascii=False)
    try:
        if logger and hasattr(logger, "info"):
            logger.info(line)
        else:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
    except Exception:
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass

# -----------------------------------------------------------------------------
# GeminiConnector — API publique
# -----------------------------------------------------------------------------

class GeminiConnector:
    """
    Connecteur Intelligent avec gestion d'état, autoréparation et maintenance prédictive.
    V_Final: Intègre le Heartbeat Loop et les Semantic Timeouts.
    """

    # Temps max d'inactivité avant vérification proactive (Soft TTL)
    SOFT_TTL_SEC = 300 
    
    DEFAULT_SELECTORS = [
        'div[role="textbox"][aria-label*="Gemini"]',
        'textarea[data-testid="chat-input"]',
        "textarea[aria-label]",
        "[contenteditable='true'][role='textbox']"
    ]

    def __init__(
        self,
        *,
        logger: Any | None = None,
        user_id: Optional[str] = None,
        profile_root: Optional[str] = None,
        headless: Optional[bool] = None,
        network_debug: Optional[bool] = None,
        login_timeout_s: Optional[int] = None,
        cdp_url: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.logger = logger
        self.user_id = user_id
        self.profile_root = profile_root
        self.headless = headless
        self.network_debug = bool(network_debug) if network_debug is not None else False
        self.login_timeout_s = login_timeout_s
        self.cdp_url = cdp_url
        self._cfg: Dict[str, Any] = {
            "user_id": self.user_id,
            "profile_root": self.profile_root,
            "headless": self.headless,
            "network_debug": self.network_debug,
            "cdp_url": self.cdp_url,
            **kwargs,
        }
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        self.epoch: Optional[int] = None
        self.hook_queue: Optional[asyncio.Queue] = None
        self.sniffer = None
        self.awaiter = None
        self._opened = False
        
        # État : Verrouillage d'activité pour éviter conflits avec maintenance
        self._is_busy = False
        self._maintenance_task: Optional[asyncio.Task] = None
        
        # Intelligence : États dynamiques
        self.input_handler = InputHandler()
        self.last_interaction_ts = 0.0
        
        # [Smart Selector] Chargement des stats
        self.selector_stats: Dict[str, int] = {s: 0 for s in self.DEFAULT_SELECTORS}
        
        # [Smart Pacing] Chargement de la mémoire historique
        try:
            self.tm = CrossProcessTimeoutManager()
            loaded_latency = self.tm.get_network_stats()
            self.avg_response_time_ms = max(500.0, min(30000.0, float(loaded_latency)))
            _jlog(self.logger, "smart_pacing_loaded", latency_ms=int(self.avg_response_time_ms))
        except Exception:
            self.tm = None
            self.avg_response_time_ms = 1000.0

        self.alpha_pacing = 0.2

    # --------------------- context manager ---------------------

    async def __aenter__(self) -> "GeminiConnector":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # --------------------- lifecycle ---------------------------

    async def open(self) -> None:
        """
        Prépare la page et démarre la maintenance prédictive (Heartbeat).
        """
        prep = await prepare_page(self._cfg, logger=self.logger, network_debug=self.network_debug)
        self.browser = prep.get("browser")
        self.context = prep.get("context")
        self.page = prep.get("page")
        self.epoch = prep.get("epoch")
        self.hook_queue = prep.get("hook_queue")

        if GeminiNetworkTap is None:
            raise RuntimeError("GeminiNetworkTap not available")
        self.sniffer = GeminiNetworkTap(self.page, logger=self.logger)
        await self.sniffer.start()

        awaiter_kwargs = {
            "anti_dom_window_ms": int(float(os.getenv("ANTI_DOM_WINDOW_S", "2.0")) * 1000),
            "hard_timeout_ms": int(os.getenv("ANSWER_HARD_TIMEOUT_MS", "35000")),
            "be_max_coalesce_bytes": int(os.getenv("BE_MAX_COALESCE_BYTES", "131072")),
        }
        self.awaiter = await build_awaiter(
            self.page,
            sniffer=self.sniffer,
            logger=self.logger,
            hook_queue=self.hook_queue,
            **awaiter_kwargs
        )

        self.last_interaction_ts = time.time()
        self._opened = True
        
        # Démarrage Heartbeat Loop
        self._maintenance_task = asyncio.create_task(self._maintenance_loop(), name="gemini_heartbeat")
        
        _jlog(
            self.logger,
            "connector_ready",
            ok=True,
            headless=bool(self.headless),
            epoch=self.epoch,
        )

    async def close(self) -> None:
        # Arrêt Heartbeat
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            self._maintenance_task = None

        stop_tasks = []
        if self.awaiter and hasattr(self.awaiter, "stop"):
             stop_tasks.append(asyncio.create_task(self.awaiter.stop(), name="stop_awaiter"))
        if self.sniffer and hasattr(self.sniffer, "stop"):
             stop_tasks.append(asyncio.create_task(self.sniffer.stop(), name="stop_sniffer"))

        if stop_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*stop_tasks, return_exceptions=True), timeout=5.0)
                _jlog(self.logger, "connector_closed_components_stopped")
            except Exception as e:
                _jlog(self.logger, "connector_close_error", error=str(e), level="WARN")

        self._opened = False
        _jlog(self.logger, "connector_closed")

    # --------------------- Intelligence Helpers ----------------------

    def _predict_complexity_score(self, prompt: str) -> float:
        """
        Calcule un score de complexité pour anticiper le temps de réponse.
        Base 1.0 (Simple) -> >2.0 (Très complexe)
        """
        score = 1.0
        # Mots-clés impliquant une lourde charge cognitive pour le modèle
        heavy_tasks = ["script complet", "analyse détaillée", "tableau comparatif", "step-by-step", "code", "refactor", "essay"]
        if any(w in prompt.lower() for w in heavy_tasks):
            score += 1.5
        
        # Longueur du prompt (contexte)
        score += len(prompt) / 500.0 
        
        return score

    async def _maintenance_loop(self) -> None:
        """Tâche de fond: Heartbeat prédictif."""
        from gemini_headless.utils.session_guardian import SessionGuardian
        
        guardian = None
        try:
            guardian = SessionGuardian(self.profile_root or ".", self.logger)
        except Exception:
            return

        while self._opened:
            try:
                # Vérif toutes les 60s
                await asyncio.sleep(60)
                
                # Si le connecteur est en train de travailler (ask), on ne touche à rien
                if self._is_busy:
                    continue
                
                if not self.page or self.page.is_closed():
                    continue

                # Check rapide de santé
                health = await guardian.health(self.page)
                
                # Décision intelligente
                if guardian.is_maintenance_due(health, self.last_interaction_ts):
                    _jlog(self.logger, "heartbeat_maintenance_trigger", status=health.get("status"))
                    # On verrouille même si c'est une tache de fond pour éviter race condition
                    self._is_busy = True 
                    try:
                        await guardian.repair_if_needed(self.page)
                        self.last_interaction_ts = time.time() # Refresh timer
                    finally:
                        self._is_busy = False
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                _jlog(self.logger, "heartbeat_error", error=str(e))
                await asyncio.sleep(60)

    async def _proactive_healing(self) -> None:
        """Vérification manuelle (legacy / pre-ask safety check)."""
        now = time.time()
        delta = now - self.last_interaction_ts
        
        if delta > self.SOFT_TTL_SEC or self.last_interaction_ts == 0.0:
            _jlog(self.logger, "proactive_healing_check", delta_sec=int(delta))
            try:
                from gemini_headless.utils.session_guardian import SessionGuardian
                guardian = SessionGuardian(self.profile_root or ".", self.logger)
                health = await guardian.health(self.page)
                if not health.get("ok") or health.get("status") == "stale":
                    await guardian.repair_if_needed(self.page)
                    await asyncio.sleep(1)
            except Exception as e:
                _jlog(self.logger, "proactive_healing_error", error=str(e))
        
        self.last_interaction_ts = now

    def _update_pacing(self, duration_ms: float) -> None:
        if duration_ms > 0:
            self.avg_response_time_ms = (
                (1 - self.alpha_pacing) * self.avg_response_time_ms + 
                self.alpha_pacing * duration_ms
            )
            if self.tm:
                try:
                    self.tm.update_network_stats(self.avg_response_time_ms)
                except Exception:
                    pass
                    
    def _get_sorted_selectors(self) -> List[str]:
        sorted_keys = sorted(self.selector_stats, key=self.selector_stats.get, reverse=True)
        result = []
        for k in sorted_keys:
            if k in self.DEFAULT_SELECTORS: result.append(k)
        for d in self.DEFAULT_SELECTORS:
            if d not in result: result.append(d)
        return result

    def _record_selector_success(self, selector: str):
        if selector in self.selector_stats:
            self.selector_stats[selector] += 1
        else:
            self.selector_stats[selector] = 1
        _jlog(self.logger, "smart_selector_update", selector=selector, new_score=self.selector_stats[selector])

    # --------------------- high level API ----------------------

    async def ask(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        """
        Enchaîne : focus → type → submit, avec intelligence (healing, pacing, smart selectors, semantic timeout).
        """
        if not self._opened:
            await self.open()
        if not self.page or self.page.is_closed():
             raise RuntimeError("Page is not available or closed.")

        self._is_busy = True # Lock pour le Heartbeat
        try:
            # 1. Maintenance Proactive (Legacy check au cas où le Heartbeat n'a pas suffi)
            await self._proactive_healing()

            # 2. Focus Intelligent
            smart_candidates = self._get_sorted_selectors()
            focus_timeout = max(3000, min(10000, int(self.avg_response_time_ms * 2)))
            
            element, used_selector = await self.input_handler.locate_input_field(
                self.page, 
                timeout_ms=focus_timeout,
                extra_selectors=smart_candidates
            )
            
            if element and used_selector:
                self._record_selector_success(used_selector)
            
            if not element:
                _jlog(self.logger, "ask_focus_failed", level="ERROR")
                try:
                    await self.page.locator("body").click()
                    await self.page.keyboard.press("Tab")
                except:
                    pass
            
            # 3. Typing (Uses new InputHandler smart typing)
            type_ok = await self.input_handler.type_text(
                self.page, 
                prompt, 
                element=element,
                delay_ms=10
            )
            
            if not type_ok:
                 _jlog(self.logger, "ask_type_failed_aborting", level="ERROR")
                 return "", {"src": "error", "error": "typing_failed"}

            # 4. Smart Submit
            submit_timeout = max(2000, int(self.avg_response_time_ms))
            submit_ok, submit_method = await SubmitHandler.smart_submit(self.page, timeout_ms=submit_timeout)
            
            if not submit_ok:
                _jlog(self.logger, "ask_submit_failed_aborting", level="ERROR")
                return "", {"src": "error", "error": "submit_failed"}

            # 5. Semantic Timeout Calculation (SMART PACING V2)
            base_timeout = max(
                int(os.getenv("ANSWER_HARD_TIMEOUT_MS", "35000")), 
                int(self.avg_response_time_ms * 10)
            )
            
            complexity_score = self._predict_complexity_score(prompt)
            # Facteur de réseau (Network Condition)
            # On prend le max entre une latence standard (1000ms) et la latence moyenne observée
            network_factor = max(1000.0, self.avg_response_time_ms) / 1000.0 
            
            # Calcul : Base + (Score * 20s) * NetworkFactor
            # Exemple : Prompt complexe (Score 2.5) sur réseau lent (Factor 1.5) = Base + (50s * 1.5)
            dynamic_bonus = (complexity_score * 20000) * network_factor
            
            final_hard_timeout = int(base_timeout + dynamic_bonus)
            # Plafond de sécurité (5 minutes)
            final_hard_timeout = min(final_hard_timeout, 300000)
            
            _jlog(self.logger, "semantic_timeout_calculated", 
                  base=base_timeout, 
                  score=f"{complexity_score:.2f}", 
                  network=f"{network_factor:.2f}",
                  final=final_hard_timeout)

            t0_ms = int(time.monotonic() * 1000)
            
            try:
                ans = await await_answer(
                    self.awaiter,
                    t0_ms=t0_ms,
                    logger=self.logger,
                    hard_timeout_ms=final_hard_timeout
                )
            except Exception as await_err:
                 _jlog(self.logger, "await_answer_exception", error=str(await_err), level="ERROR")
                 return "", {"src": "error", "error": "await_answer_failed", "details": str(await_err)}

            # 6. Mise à jour Intelligence
            t1_ms = int(time.monotonic() * 1000)
            duration = t1_ms - t0_ms
            self._update_pacing(duration)
            self.last_interaction_ts = time.time()

            src = ans.get("src", "unknown")
            text = ans.get("text") or ""
            
            meta = {
                "src": src,
                "t0_ms": t0_ms,
                "t1_ms": t1_ms,
                "latency_ms": duration,
                "pacing_avg_ms": int(self.avg_response_time_ms),
                "stats": getattr(self.awaiter, "stats", lambda: {})(),
                **(ans.get("meta", {}))
            }
            
            _jlog(self.logger, "ask_completed", src=src, len=len(text), latency=duration)
            return text, meta
        
        finally:
            self._is_busy = False # Release Lock

    async def ask_with_file(self, prompt: str, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Variante pour fichier : timeouts étendus.
        """
        if not self._opened:
            await self.open()
        
        self._is_busy = True
        try:
            await self._proactive_healing()

            smart_candidates = self._get_sorted_selectors()
            element, used_selector = await self.input_handler.locate_input_field(
                self.page, 
                timeout_ms=5000,
                extra_selectors=smart_candidates
            )
            
            if element and used_selector:
                 self._record_selector_success(used_selector)
            
            if not await self.input_handler.type_text(self.page, prompt, element=element):
                return "", {"src": "error", "error": "typing_failed"}

            if not (await SubmitHandler.smart_submit(self.page))[0]:
                return "", {"src": "error", "error": "submit_failed"}

            t0_ms = int(time.monotonic() * 1000)
            hard_timeout = 180000 
            
            try:
                ans = await await_answer(
                    self.awaiter,
                    t0_ms=t0_ms,
                    logger=self.logger,
                    hard_timeout_ms=hard_timeout
                )
            except Exception as e:
                 return "", {"src": "error", "error": str(e)}

            self._update_pacing(int(time.monotonic() * 1000) - t0_ms)
            self.last_interaction_ts = time.time()
            
            text = ans.get("text") or ""
            return text, {"src": ans.get("src"), "file_mode": True}
            
        finally:
            self._is_busy = False

    async def run_once(self, context: Any, *, prompt: str, network_debug: bool = False, t0_ms: Optional[int] = None) -> Dict[str, Any]:
        _ = context
        _ = t0_ms
        self.network_debug = bool(network_debug)
        txt, meta = await self.ask(prompt)
        return {"text": txt, "meta": meta}

    async def ask_text(self, prompt: str) -> str:
        txt, _ = await self.ask(prompt)
        return txt

    async def _focus_input(self, page: Page, **kwargs) -> bool:
        el, _ = await self.input_handler.locate_input_field(page, **kwargs)
        return bool(el)

    async def _type_prompt(self, page: Page, prompt: str, **kwargs) -> bool:
        return await self.input_handler.type_text(page, prompt, **kwargs)

    async def _submit(self, page: Page, **kwargs) -> bool:
        ok, _ = await SubmitHandler.smart_submit(page)
        return ok

__all__ = ["GeminiConnector"]