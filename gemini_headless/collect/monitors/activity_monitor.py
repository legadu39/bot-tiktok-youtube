### gemini_headless/collect/monitors/activity_monitor.py
#
# ============================================================================
# VERSION MISE À JOUR V32 (INTELLIGENT NETWORK AWARENESS + SYNTAX CHECK)
#
# CHANGEMENTS :
# - INTELLIGENCE N°3 : Analyse de syntaxe (Code Blocks, Listes) pour étendre les timeouts.
# - DYNAMIQUE : Les seuils de timeout intègrent la latence réseau estimée.
# - MAINTIEN : Logique "Thinking" et "Semantic Keep-Alive" conservée.
# ============================================================================

from __future__ import annotations
import asyncio
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from playwright.async_api import Page, Error as PlaywrightError

try:
    from gemini_headless.collect.utils.logs import jlog
    from gemini_headless.collect.producers.dom import _GET_BEST_TEXT_JS, safe_frame_evaluate
except ImportError:
    # Fallback critique
    import sys, json
    def jlog(evt="unknown", **_k):
        print(json.dumps({"evt": evt, "ts": time.time(), **_k}), file=sys.stderr, flush=True)
    
    _GET_BEST_TEXT_JS = "() => document.body.innerText || ''"
    async def safe_frame_evaluate(frame, script):
        return await frame.evaluate(script)

# --- Constantes ---
ACTIVITY_PROBE_INTERVAL_S: float = float(os.getenv("GH_ACTIVITY_PROBE_INTERVAL_S", "15.0"))
SNAPSHOT_REQUEST_TIMEOUT_S: float = 4.5

# Mots-clés indiquant une activité cérébrale
KEEP_ALIVE_TOKENS = [
    "Visualizing", "Analyzing", "Searching", "Reading documents", "Rerunning",
    "Création de l'image", "Analyse en cours", "Recherche", "Génération",
    "Creating image", "Gathering", "Thinking", "Pensée", "Réflexion",
    "Envisioning", "Picturing", "Developing", "Sketching", "Drafting",
    "Refining", "Composing", "Detailing", "Defining"
]

# ============================================================================
# COMPOSANT INTELLIGENT N°3 : ESTIMATEUR DE LATENCE
# ============================================================================

class NetworkLatencyEstimator:
    """Estime la santé du réseau pour adapter les timeouts."""
    def __init__(self):
        self.rtt_samples = []
        self.last_ping = time.monotonic()
        self.current_lag_factor = 1.0 # 1.0 = Normal, 2.0 = Lent

    def record_interaction(self, start_ts: float):
        """Enregistre une durée d'aller-retour (approximative)."""
        duration = time.monotonic() - start_ts
        self.rtt_samples.append(duration)
        if len(self.rtt_samples) > 10:
            self.rtt_samples.pop(0)
        self._recalc()

    def _recalc(self):
        if not self.rtt_samples:
            self.current_lag_factor = 1.0
            return
        avg = sum(self.rtt_samples) / len(self.rtt_samples)
        # Si la moyenne des interactions > 0.5s, on considère qu'il y a du lag
        if avg > 0.5:
            self.current_lag_factor = 1.0 + (avg * 2.0) # E.g., 1s delay -> factor 3.0
        else:
            self.current_lag_factor = 1.0
        
        self.current_lag_factor = min(self.current_lag_factor, 4.0) # Cap à 4x

# ============================================================================
# PHASE 1: KILL SWITCH D'URGENCE (AVEC RÉSEAU AWARE & SYNTAX CHECK)
# ============================================================================

class FrozenStateDetector:
    """Détecte quand Gemini est gelé avec un seuil de tolérance intelligent."""
    
    def __init__(self):
        self.start_time = time.monotonic()
        self.last_text_progress_time: Optional[float] = None
        self.last_text_size = 0
        self.last_check_time = time.monotonic()
        
        # Intelligence: Velocity Tracking & Network
        self.current_velocity_cps = 0.0 
        self.network_health = NetworkLatencyEstimator()
        
        self.frozen_alert_sent = False
        self.critical_alert_sent = False
        self._last_diagnostics: Dict[str, Any] = {"status": "init"}

    def start_generation_timer(self) -> None:
        # Appelé une seule fois lorsque la génération commence
        now = time.monotonic()
        self.last_text_progress_time = now
        self.last_check_time = now
        self.last_text_size = 0
        self.frozen_alert_sent = False
        self.critical_alert_sent = False
        self._last_diagnostics = {"status": "armed", "action": None}

    def _analyze_syntax_state(self, current_text_buffer: str) -> bool:
        """
        Intelligence N°3: Analyse si la syntaxe est incomplète (bloc de code ouvert, liste non finie).
        Retourne True si l'état est 'incomplet', justifiant une extension de timeout.
        """
        if not current_text_buffer: return False
        
        # 1. Code Block Check
        code_block_count = current_text_buffer.count("```")
        in_code_block = (code_block_count % 2 != 0)
        
        # 2. List Item Check (Dernière ligne commence par "- " ou "1." mais est très courte)
        lines = current_text_buffer.split('\n')
        if lines:
            last_line = lines[-1].strip()
            # Si la dernière ligne ressemble à un début de puce et fait moins de 50 chars, c'est probablement en cours
            in_list_item = len(last_line) > 0 and len(last_line) < 50 and (last_line.startswith('- ') or (len(last_line) > 2 and last_line[0].isdigit() and last_line[1] == '.'))
        else:
            in_list_item = False
            
        return in_code_block or in_list_item

    def _calculate_dynamic_thresholds(self, text_size: int, is_complex_content: bool = False, is_thinking: bool = False, syntax_incomplete: bool = False) -> tuple[float, float, float]:
        """
        Calcule les seuils de timeout en fonction de la taille, complexité, phase ET RÉSEAU.
        """
        # Base patience boost based on size
        bonus_seconds = (text_size / 100.0) * 1.0 # 1 sec pour 100 chars
        bonus_seconds = min(bonus_seconds, 180.0)
        
        # Intelligence: Complexity & Network Lag Multiplier
        complexity_mult = 1.5 if is_complex_content else 1.0
        lag_mult = self.network_health.current_lag_factor # Facteur réseau (1.0 à 4.0)
        
        # Intelligence V12: Thinking Phase Multiplier
        if is_thinking:
             complexity_mult = 5.0 # Boost encore plus agressif
        
        # Intelligence N°3: Syntax Incomplete Multiplier
        # Si on est au milieu d'un bloc de code, on est BEAUCOUP plus patient
        if syntax_incomplete:
             complexity_mult = max(complexity_mult, 3.0)

        # Combinaison des facteurs (on est prudent, on ne multiplie pas tout aveuglément)
        total_mult = max(complexity_mult, lag_mult) 
        
        warn_t = (60.0 + (bonus_seconds * 0.5)) * total_mult
        crit_t = (90.0 + (bonus_seconds * 0.8)) * total_mult
        abort_t = (120.0 + bonus_seconds) * total_mult
        
        # Hard cap de sécurité augmenté en cas de lag réseau avéré
        base_cap = 900.0 if is_thinking else 300.0
        if is_complex_content and not is_thinking: base_cap = 480.0
        
        max_cap = base_cap * lag_mult # Si le réseau rame, on attend proportionnellement plus
        
        abort_t = min(abort_t, max_cap)
        
        return warn_t, crit_t, abort_t

    def update(self, text_size: int, aria_busy: bool, content_sample: str = "", is_thinking: bool = False) -> Dict[str, Any]:
        """Met à jour l'état du détecteur et retourne une action si nécessaire."""
        now = time.monotonic()
        
        # Enregistrement simple d'activité pour le moniteur réseau (simulation ping via update call frequency)
        self.network_health.record_interaction(self.last_check_time)

        # Tant que la génération n’a pas démarré, rester passif
        if self.last_text_progress_time is None:
            self._last_diagnostics = {
                "status": "idle",
                "action": None,
                "aria_busy": aria_busy,
                "text_growing": False,
                "velocity_cps": 0.0,
                "lag_factor": self.network_health.current_lag_factor
            }
            return self._last_diagnostics

        # --- INTELLIGENCE V16: Semantic Keep-Alive ---
        is_semantic_alive = False
        if content_sample:
            recent_sample = content_sample[-800:] 
            if any(token.lower() in recent_sample.lower() for token in KEEP_ALIVE_TOKENS):
                is_semantic_alive = True
                is_thinking = True
        
        # --- INTELLIGENCE: Calcul de Vélocité ---
        delta_time = now - self.last_check_time
        if delta_time > 0.1:
            delta_chars = max(0, text_size - self.last_text_size)
            instant_cps = delta_chars / delta_time
            self.current_velocity_cps = (self.current_velocity_cps * 0.7) + (instant_cps * 0.3)
        
        self.last_check_time = now

        # Détection de progrès (Physique OU Sémantique)
        if text_size > self.last_text_size or (is_semantic_alive and aria_busy):
            self.last_text_progress_time = now
            self.last_text_size = text_size
            self.frozen_alert_sent = False
            self.critical_alert_sent = False
            
            status_msg = "progressing"
            if is_semantic_alive:
                status_msg = "semantic_keep_alive"

            self._last_diagnostics = {
                "status": status_msg, 
                "action": None,
                "text_growing": (text_size > self.last_text_size),
                "aria_busy": aria_busy,
                "velocity_cps": round(self.current_velocity_cps, 2),
                "lag_factor": round(self.network_health.current_lag_factor, 2)
            }
            return self._last_diagnostics
        
        # Calculer temps sans progrès
        time_without_progress = now - self.last_text_progress_time
        
        is_effectively_stagnant = (self.current_velocity_cps < 0.5)
        
        # Intelligence N°3: Syntax Awareness
        is_syntax_incomplete = self._analyze_syntax_state(content_sample)

        self._last_diagnostics = {
            "status": "stagnant" if is_effectively_stagnant else "slow_progress",
            "action": None,
            "time_without_progress": time_without_progress,
            "aria_busy": aria_busy,
            "last_text_size": self.last_text_size,
            "text_growing": False,
            "velocity_cps": round(self.current_velocity_cps, 2),
            "is_thinking": is_thinking,
            "syntax_incomplete": is_syntax_incomplete,
            "lag_factor": round(self.network_health.current_lag_factor, 2)
        }
        
        if not is_effectively_stagnant:
             self.last_text_progress_time = now
             return self._last_diagnostics

        # 🚀 INTELLIGENCE V11: Détection de Complexité
        is_complex = False
        if content_sample:
            if "```" in content_sample or "{" in content_sample or "}" in content_sample:
                is_complex = True
            elif "analyse" in content_sample.lower() or "calcul" in content_sample.lower():
                is_complex = True

        # 🚀 DYNAMIC TIMEOUTS (Avec Network Aware & Syntax Aware)
        WARN_T, CRIT_T, ABORT_T = self._calculate_dynamic_thresholds(
            self.last_text_size, 
            is_complex, 
            is_thinking, 
            is_syntax_incomplete
        )

        # NIVEAU 1: WARNING
        if (time_without_progress > WARN_T and aria_busy and not self.frozen_alert_sent):
            self.frozen_alert_sent = True
            self._last_diagnostics.update({
                "action": "warn",
                "message": f"Stagnation (Lag={self.network_health.current_lag_factor:.1f}x, Syntax={is_syntax_incomplete}): {time_without_progress:.1f}s > {WARN_T:.1f}s"
            })
            return self._last_diagnostics
        
        # NIVEAU 2: CRITICAL
        if (time_without_progress > CRIT_T and aria_busy and not self.critical_alert_sent):
            self.critical_alert_sent = True
            self._last_diagnostics.update({
                "action": "critical",
                "message": f"État critique (Lag={self.network_health.current_lag_factor:.1f}x, Syntax={is_syntax_incomplete}): {time_without_progress:.1f}s > {CRIT_T:.1f}s"
            })
            return self._last_diagnostics
        
        # NIVEAU 3: ABORT
        if time_without_progress > ABORT_T and aria_busy:
            self._last_diagnostics.update({
                "action": "abort",
                "message": f"ABORT (Lag={self.network_health.current_lag_factor:.1f}x, Syntax={is_syntax_incomplete}): {time_without_progress:.1f}s > {ABORT_T:.1f}s"
            })
            return self._last_diagnostics
        
        return self._last_diagnostics

    def get_last_diagnostics(self) -> Dict[str, Any]:
        """Retourne le dernier état de diagnostic."""
        if self._last_diagnostics.get("status") == "stagnant" and self.last_text_progress_time:
             self._last_diagnostics["time_without_progress"] = time.monotonic() - self.last_text_progress_time
        return self._last_diagnostics

# ============================================================================
# PHASE 2: SCHEDULER ADAPTATIF INTELLIGENT
# ============================================================================

class AdaptiveProbeScheduler:
    """Ajuste la fréquence des probes en fonction de l'état et de la VÉLOCITÉ."""
    
    def __init__(self, normal_interval: float = 15.0):
        self.last_interval = normal_interval
        self.state = "normal"
        self._normal_interval = normal_interval

    def compute_interval(self,
                        time_without_progress: float,
                        aria_busy: bool,
                        text_growing: bool,
                        velocity_cps: float = 0.0) -> float:
        """Retourne le prochain intervalle de probe en secondes."""
        
        # State 0: High Velocity (Flux intense)
        if velocity_cps > 10.0:
            self.state = "turbo"
            self.last_interval = 20.0
            return self.last_interval

        # State 1: Texte arrive vite (fluent)
        if text_growing and time_without_progress < 15:
            self.state = "fluent"
            self.last_interval = 30.0
            return self.last_interval
        
        # State 2: Normal
        elif aria_busy and text_growing:
            self.state = "normal"
            self.last_interval = self._normal_interval
            return self.last_interval
        
        # State 3: Lent mais pas encore gelé
        elif aria_busy and time_without_progress < 60:
            self.state = "slow"
            self.last_interval = self._normal_interval
            return self.last_interval
        
        # State 4: Peut-être gelé
        elif aria_busy and 60 <= time_without_progress < 90:
            self.state = "suspicious"
            self.last_interval = 10.0
            return self.last_interval
        
        # State 5: Presque sur gelé
        elif aria_busy and time_without_progress >= 90:
            self.state = "critical"
            self.last_interval = 5.0
            return self.last_interval
        
        # State 6: Pas occupé (probablement terminé)
        elif not aria_busy and time_without_progress > 10:
             self.state = "idle"
             self.last_interval = 20.0
             return self.last_interval

        else:
            self.state = "unknown"
            self.last_interval = self._normal_interval
            return self.last_interval

    def get_state(self) -> str:
        return self.state


# ============================================================================
# TÂCHE DE MONITORING
# ============================================================================

async def _take_last_gasp_snapshot(page: Page, profile_dir: Path) -> bool:
    """Prend un snapshot DOM de la dernière chance."""
    snapshot_text = ""
    try:
        jlog("last_gasp_snapshot_attempt", timeout_s=SNAPSHOT_REQUEST_TIMEOUT_S)
        snap_js_expr = _GET_BEST_TEXT_JS
        
        if 'safe_frame_evaluate' in globals():
            snapshot_text_raw = await asyncio.wait_for(
                safe_frame_evaluate(page.main_frame, snap_js_expr),
                timeout=SNAPSHOT_REQUEST_TIMEOUT_S
            )
        else:
            snapshot_text_raw = await asyncio.wait_for(
                page.main_frame.evaluate(snap_js_expr),
                timeout=SNAPSHOT_REQUEST_TIMEOUT_S
            )
        
        if isinstance(snapshot_text_raw, dict):
             snapshot_text_raw = snapshot_text_raw.get("text", "")

        if snapshot_text_raw and isinstance(snapshot_text_raw, str):
            snapshot_text = snapshot_text_raw.strip()
            jlog("last_gasp_snapshot_captured", raw_len=len(snapshot_text_raw), final_len=len(snapshot_text), level="INFO")
            return True
        else:
            jlog("last_gasp_snapshot_empty", level="WARN")
            return False
            
    except asyncio.TimeoutError:
        jlog("last_gasp_snapshot_timeout", level="ERROR")
        return False
    except asyncio.CancelledError:
        jlog("last_gasp_snapshot_cancelled", level="WARN")
        return False
    except Exception as snap_err:
        jlog("last_gasp_snapshot_error", error=str(snap_err), level="ERROR")
        return False


async def stagnation_monitor_task(
    detector: FrozenStateDetector, 
    done_evt: asyncio.Event,
    page: Page,
    profile_dir: Path,
    signal_dir: Path
):
    """
    Tâche de fond qui observe le 'detector' et déclenche un snapshot
    si l'état "abort" est atteint.
    """
    jlog("stagnation_monitor_task_started_v10", check_interval_s=5.0)
    pid = os.getpid()
    snapshotsignalfile = signal_dir / f"{pid}.snapshot_request"
    
    try:
        while not done_evt.is_set():
            await asyncio.sleep(5.0) 
            
            diagnostics = detector.get_last_diagnostics()
            action = diagnostics.get("action")

            if action == "abort":
                jlog("stagnation_monitor_detected_abort",
                     reason=diagnostics.get("message"),
                     level="CRITICAL")
                
                try:
                    signal_dir.mkdir(parents=True, exist_ok=True)
                    snapshotsignalfile.touch(exist_ok=True)
                except Exception as e:
                    jlog("snapshot_request_signal_file_error", error=str(e), level="ERROR")
                
                await _take_last_gasp_snapshot(page, profile_dir)
                break 

    except asyncio.CancelledError:
        jlog("stagnation_monitor_task_cancelled")
    except Exception as e:
        jlog("stagnation_monitor_task_error", error=str(e), level="ERROR")
    finally:
        jlog("stagnation_monitor_task_stopped")


# ============================================================================
# SONDE D'ACTIVITÉ
# ============================================================================

async def _activity_probe(page: Page) -> Dict[str, Any]:
    """Sonde l'activité réelle (aria-busy) et visuelle (Thinking blocks)."""
    probe_status: Dict[str, Any] = {"busy": False, "source": "init", "text_growing": False, "visual_thinking": False}
    try:
        # Priorité 1: Thinking Process Visual Indicators
        thinking_js = """() => {
            const thinking = document.querySelectorAll('.thinking-process, [aria-label*="Thinking"], [aria-label*="Analysis"]');
            for (const el of thinking) {
                if (el.offsetParent !== null) return true;
            }
            if (document.body.innerText.includes('Analyzing...') || document.body.innerText.includes('Thinking...')) return true;
            return false;
        }"""
        try:
            is_visually_thinking = await page.evaluate(thinking_js)
            if is_visually_thinking:
                probe_status = {"busy": True, "source": "visual_thinking_indicator", "visual_thinking": True}
                return probe_status
        except: pass

        # Priorité 2: aria-busy
        busy_locator = page.locator('[aria-busy="true"]').first
        count = await busy_locator.count()
        if count > 0:
            probe_status = {"busy": True, "source": "aria-busy"}
            jlog("activity_probe_status", busy=True, source="aria-busy", level="DEBUG")
            return probe_status

        # Priorité 3: Spinner
        spinner_locator = page.locator('mat-spinner, [role="progressbar"]').first
        if await spinner_locator.count() > 0:
            probe_status = {"busy": True, "source": "spinner"}
            jlog("activity_probe_status", busy=True, source="spinner", level="DEBUG")
            return probe_status
            
        jlog("activity_probe_status", busy=False, source="no_indicator_found", level="DEBUG")
        return probe_status

    except Exception as e:
        jlog("activity_probe_generic_error", error=str(e), level="WARN")
        probe_status["error"] = str(e)
        return probe_status


async def activity_probe_task(
    page: Page,
    done_evt: asyncio.Event,
    frozen_detector: FrozenStateDetector,
    orchestrator_instance: Any
):
    """
    VERSION V11 - CONTENT AWARE PROBE
    """
    
    jlog("activity_probe_v11_started", mode="passive_velocity_aware_content_aware")
    
    probe_scheduler = AdaptiveProbeScheduler(normal_interval=ACTIVITY_PROBE_INTERVAL_S)
    stagnation_flag_set = False 
    gen_timer_armed = False 
    
    try:
        while not done_evt.is_set():
            try:
                # === Probe aria-busy & Thinking ===
                status = await _activity_probe(page)
                aria_busy = status.get("busy", False)
                visual_thinking = status.get("visual_thinking", False)

                # === One-shot Timer Start ===
                if getattr(orchestrator_instance, "generation_has_started", False) and not gen_timer_armed:
                    if hasattr(frozen_detector, "start_generation_timer"):
                        frozen_detector.start_generation_timer()
                        jlog("frozen_detector_generation_timer_started")
                    gen_timer_armed = True
                
                # === Content Sample Extraction ===
                content_sample = ""
                try:
                    if hasattr(orchestrator_instance, '_buf'):
                        best_len = -1
                        best_k = "dom"
                        for k in ["sse", "ws", "dom", "be"]:
                            if k in orchestrator_instance._buf and len(orchestrator_instance._buf[k]) > best_len:
                                best_len = len(orchestrator_instance._buf[k])
                                best_k = k
                        content_sample = orchestrator_instance._buf[best_k][-2000:] 
                except Exception: pass

                # === Update Detector ===
                current_text_size = getattr(orchestrator_instance, 'last_text_size', 0)
                is_thinking_state = getattr(orchestrator_instance, 'is_thinking', False) or visual_thinking
                
                # Pass content_sample AND is_thinking to update
                result = frozen_detector.update(
                    current_text_size, 
                    aria_busy, 
                    content_sample=content_sample,
                    is_thinking=is_thinking_state
                )
                
                action = result.get("action")
                velocity = result.get("velocity_cps", 0.0)
                lag = result.get("lag_factor", 1.0)
                
                # === Decision Logic ===
                if action == "warn":
                    if not stagnation_flag_set:
                        jlog("activity_probe_v11_warning",
                            time_stagnant=result.get("time_without_progress"),
                            velocity=velocity,
                            lag=lag,
                            level="WARN")
                
                elif action == "critical":
                    if not stagnation_flag_set:
                        jlog("activity_probe_v11_critical",
                            time_stagnant=result.get("time_without_progress"),
                            velocity=velocity,
                            lag=lag,
                            level="CRITICAL")
                
                elif action == "abort":
                    if not stagnation_flag_set:
                        jlog("activity_probe_v11_abort",
                            time_stagnant=result.get("time_without_progress"),
                            velocity=velocity,
                            lag=lag,
                            level="ERROR")
                        
                        if hasattr(orchestrator_instance, '_stagnation_flag'):
                            orchestrator_instance._stagnation_flag = True
                        
                        stagnation_flag_set = True
                
                # === Compute Next Interval ===
                time_without_progress = result.get('time_without_progress', 0)
                if time_without_progress is None: time_without_progress = 0
                text_growing = result.get('text_growing', False)
                
                next_interval = probe_scheduler.compute_interval(
                    time_without_progress=time_without_progress,
                    aria_busy=aria_busy,
                    text_growing=text_growing,
                    velocity_cps=velocity
                )
                
                await asyncio.sleep(next_interval)
                
            except asyncio.CancelledError:
                jlog("activity_probe_v11_cancelled")
                break
            except Exception as e:
                jlog("activity_probe_v11_cycle_error", error=str(e)[:100], level="WARN")
                await asyncio.sleep(5.0)
    
    finally:
        jlog("activity_probe_v11_stopped")