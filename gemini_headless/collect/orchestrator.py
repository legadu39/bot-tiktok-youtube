from __future__ import annotations
import asyncio, time, os, inspect, traceback, re, json, sys
from pathlib import Path
from collections import deque
from typing import Dict, Optional, Tuple, Any, Callable, List, Set
from playwright.async_api import Page, Download, TimeoutError as PWTimeout

try:
    from .utils.logs import jlog
    from gemini_headless.connectors.ui_interaction import RecoveryHandler, DownloadHandler
except ImportError:
    import sys
    def jlog(evt="unknown", **_k): pass
    class RecoveryHandler:
        @staticmethod
        async def attempt_generic_retry(page): return False
    class DownloadHandler:
        @staticmethod
        async def fallback_download_via_fetch(page, url, dest_path): return False

# --- Imports des Producteurs ---
try:
    from .producers.sse import SSEProducer
    from .producers.ws import WSProducer
    from .producers.be import BEProducer, parse_gemini_response_intelligent_v14
    from .producers.dom import DOMProducer, _GET_BEST_TEXT_JS
    from .filters.cleaner import clean_text_with_stats, clean_text, is_response_semantically_complete, repair_structure, is_head_semantically_valid, normalize_stream_artifacts
except ImportError:
    class BaseProducerPlaceholder:
        def __init__(self, *args, **kwargs): self.done = False
        async def snapshot_now(self): return {"text": ""}
        async def start(self): pass
        async def stop(self): pass
        async def scavenge_images(self, *args): return []
        async def trigger_download_action(self): return {"triggered": False}
    SSEProducer = WSProducer = BEProducer = DOMProducer = BaseProducerPlaceholder
    async def parse_gemini_response_intelligent_v14(*args, **kwargs): return None
    def clean_text_with_stats(x, **k): return x, {}
    def is_response_semantically_complete(text, **k): return True, "fallback_ok", "OK"
    def is_head_semantically_valid(text): return True
    def repair_structure(text): return text
    def normalize_stream_artifacts(text): return text

# ============================================================================
# CONFIGURATION V32 (INTELLIGENCE UPDATE: SEMANTIC CLEANING + VISUAL HEURISTICS)
# ============================================================================
SENTINELS = ("<<NEXUS_END>>", "<>")
PRIO = ["sse", "ws", "be", "dom"]

# Fail-Fast Patterns for critical errors
FATAL_PATTERNS = [
    r"(limite|quota).*(atteint|décidé|épuisé)",
    r"je ne peux pas (générer|créer|dessiner)",
    r"policy violation",
    r"cannot generate.*image",
    r"unable to create",
    r"violation de (la )?politique",
    r"reach(ed)?.*(limit|quota)"
]

# Footers connus de l'interface Google à supprimer lors du Golden Copy
STATIC_FOOTERS = [
    "Vos discussions EMD",
    "Votre confidentialité et Gemini",
    "Vérifiez les réponses de Gemini",
    "Gemini peut afficher des informations inexactes",
    "Gemini peut se tromper",
    "S'ouvre dans une nouvelle fenêtre",
    "Les réponses de Gemini sont générées par une IA"
]

class HealingMemory:
    """Système de mémoire persistant pour l'auto-réparation (Immune System)."""
    FILE_PATH = Path("healing_history.json")
    
    @classmethod
    def load(cls) -> Dict:
        if cls.FILE_PATH.exists():
            try:
                with open(cls.FILE_PATH, "r") as f: return json.load(f)
            except: pass
        return {}

    @classmethod
    def update(cls, level: int, success: bool):
        data = cls.load()
        key = str(level)
        if key not in data: data[key] = {"success": 0, "fail": 0}
        
        if success: data[key]["success"] += 1
        else: data[key]["fail"] += 1
        
        try:
            with open(cls.FILE_PATH, "w") as f: json.dump(data, f)
        except: pass

    @classmethod
    def get_best_strategy(cls) -> List[int]:
        data = cls.load()
        # Calculer le score (Taux de succès)
        scores = []
        default_levels = [1, 2, 3, 4]
        
        for level in default_levels:
            stats = data.get(str(level), {"success": 0, "fail": 0})
            total = stats["success"] + stats["fail"]
            ratio = (stats["success"] / total) if total > 0 else 0.5 # 0.5 par défaut
            scores.append((level, ratio))
            
        # Trier par ratio décroissant
        scores.sort(key=lambda x: x[1], reverse=True)
        return [x[0] for x in scores]


class IntelligentGenerationCompleteDetector:
    """
    Détecteur V29 (Visual Satisfaction + Grace Period + Draconian Filter).
    """
    def __init__(self, page: Page = None, expected_format: str = None):
        self.page = page
        self.total_cycles = 0
        self.hard_limit_cycles = 800 # ~6-7 minutes
        self.expected_format = expected_format
        
        # Velocity Tracking
        self.last_text_len = 0
        self.velocity_history = deque(maxlen=15)
        self.extended_count = 0
        self.max_extensions = 15
        
        # State Tracking
        self.consecutive_stagnation_cycles = 0
        self.is_in_code_block = False
        self.current_phase = "GENERATING" 
        
        # Calibration
        self.baseline_history = []
        self.dynamic_threshold = 0.2
        self.is_calibrating = True
        
        # Visual Logic
        self.has_visual_intent = False
        self.visual_lock_start_ts = 0.0
        self.spinner_stopped_ts = 0.0 
        self.visual_satisfaction_ts = 0.0 # V29: Timestamp quand on a enfin l'image
        
        if expected_format and expected_format.upper() in ["VISUAL", "IMAGE"]:
            self.has_visual_intent = True
            jlog("detector_visual_intent_activated", expected=expected_format)

    def set_phase(self, phase: str):
        if phase != self.current_phase:
            self.current_phase = phase

    def reset_stagnation(self, reason: str):
        if self.consecutive_stagnation_cycles > 0:
            jlog("detector_stagnation_reset", reason=reason, previous_cycles=self.consecutive_stagnation_cycles)
            self.consecutive_stagnation_cycles = 0
            self.hard_limit_cycles += 100

    def _analyze_syntax_debt(self, text: str) -> Tuple[bool, str]:
        if not text: return False, "empty"
        if self.expected_format == "JSON" or text.strip().startswith("{"):
            open_braces = text.count("{")
            close_braces = text.count("}")
            if open_braces > close_braces:
                return True, f"json_debt_{open_braces - close_braces}"
        backticks = text.count("```")
        if backticks % 2 != 0:
            return True, "code_block_open"
        return False, "balanced"
    
    def _check_fatal_errors(self, text: str) -> Tuple[bool, str]:
        text_lower = text.lower()
        for pattern in FATAL_PATTERNS:
            if re.search(pattern, text_lower):
                return True, f"FATAL_ERROR_DETECTED: {pattern}"
        return False, "ok"
        
    def _analyze_creative_thinking(self, text: str) -> bool:
        tokens = ["Envisioning", "Picturing", "Developing", "Drafting", "Visualizing", "Refining", "Detailing"]
        sample = text[-500:] 
        return any(t in sample for t in tokens)

    async def _check_visual_thinking_state(self) -> bool:
        if not self.page: return False
        try:
            return await self.page.evaluate("""() => {
                const thinkingBlocks = document.querySelectorAll('deep-thinking-block, .thinking-process, [aria-label*="thinking"]');
                for (const block of thinkingBlocks) {
                    if (block.offsetParent !== null) { 
                        if (block.classList.contains('animating') || block.getAttribute('aria-expanded') === 'true') return true;
                        return true; 
                    }
                }
                const skeletons = document.querySelectorAll('.skeleton, [class*="skeleton"]');
                if (skeletons.length > 2) return true;
                return false;
            }""")
        except:
            return False

    async def analyze_generation_complete(
        self, 
        current_text: str, 
        aria_busy: bool = True,
        images_count: int = 0,
        dom_status: str = "normal" 
    ) -> tuple[bool, str]:
        
        self.total_cycles += 1
        
        # 0. Fail-Fast
        is_fatal, fatal_reason = self._check_fatal_errors(current_text)
        if is_fatal: return True, fatal_reason

        current_len = len(current_text)
        delta = current_len - self.last_text_len
        self.velocity_history.append(delta if delta >= 0 else 0.5)
        self.last_text_len = current_len
        
        avg_velocity = sum(self.velocity_history) / len(self.velocity_history) if self.velocity_history else 0.0

        if self.is_calibrating:
            if self.total_cycles <= 20:
                if delta > 0: self.baseline_history.append(delta)
            else:
                self.is_calibrating = False
                if self.baseline_history:
                    avg = sum(self.baseline_history) / len(self.baseline_history)
                    self.dynamic_threshold = max(0.1, avg * 0.15)

        # 1. Sentinelles
        for s in SENTINELS:
            if s in current_text: return True, f"sentinel_detected_{s}"

        norm_text = normalize_stream_artifacts(current_text)
        is_semantically_valid, broken_reason, severity = is_response_semantically_complete(
            norm_text, 
            expected_format=self.expected_format,
            has_images=(images_count > 0)
        )
        is_broken = not is_semantically_valid
        self.is_in_code_block = (norm_text.count("```") % 2 != 0)

        # --- INTELLIGENCE V29: LOGIC REFINEMENT ---
        
        # Deep Thinking Check
        is_visual_thinking = await self._check_visual_thinking_state()
        if is_visual_thinking:
            self.current_phase = "THINKING_VISUAL"
            self.consecutive_stagnation_cycles = 0
            return False, "visual_thinking_block_active"

        if dom_status == "generating_media":
            self.current_phase = "AWAITING_MEDIA_RENDER"
            self.consecutive_stagnation_cycles = 0 
            return False, "dom_reports_generating_media_wait"

        # VISUAL INTENT MANAGEMENT
        if self.has_visual_intent:
            if images_count == 0:
                # CAS 1: Pas encore d'image
                self.current_phase = "VISUAL_DELIVERY"
                if self.visual_lock_start_ts == 0.0: self.visual_lock_start_ts = time.monotonic()
                elapsed_lock = time.monotonic() - self.visual_lock_start_ts
                
                # Grace Period post-spinner (si le spinner s'arrête avant l'image)
                if not aria_busy:
                    if self.spinner_stopped_ts == 0.0: self.spinner_stopped_ts = time.monotonic()
                    if (time.monotonic() - self.spinner_stopped_ts) < 15.0:
                        self.consecutive_stagnation_cycles = 0
                        return False, "visual_delivery_grace_period"
                else:
                    self.spinner_stopped_ts = 0.0
                
                if aria_busy:
                    self.consecutive_stagnation_cycles = 0 
                    return False, "visual_generation_busy"
                
                if elapsed_lock < 25.0:
                    return False, f"waiting_for_visual_delivery_grace_{elapsed_lock:.1f}s"
            else:
                 # CAS 2 (V29): On a l'image ! ("Satisfaction")
                 if self.visual_satisfaction_ts == 0.0: self.visual_satisfaction_ts = time.monotonic()
                 # On reset le lock d'attente
                 self.visual_lock_start_ts = 0.0
                 
                 # Si on a l'image et que le texte stagne, on peut ignorer le spinner s'il traîne.
                 # Cela corrige le bug "deep_stagnation_while_busy" alors qu'on a l'image.

        stagnation_threshold = self.dynamic_threshold
        if self.current_phase == "THINKING" or self.current_phase == "THINKING_VISUAL": 
            stagnation_threshold = 0.0

        # 3. Text Stagnation Logic
        if self.total_cycles > 40 and avg_velocity <= stagnation_threshold:
            if self._analyze_creative_thinking(current_text) and aria_busy:
                self.consecutive_stagnation_cycles = 0
                return False, "creative_thinking_in_progress"

            has_debt, debt_reason = self._analyze_syntax_debt(norm_text)
            if has_debt:
                self.consecutive_stagnation_cycles = 0 
                self.hard_limit_cycles += 50 
                return False, f"stagnation_ignored_due_to_syntax_debt_{debt_reason}"

            self.consecutive_stagnation_cycles += 1
            stagnation_duration_approx = self.consecutive_stagnation_cycles * 0.5 
            
            # --- V29: EARLY EXIT FOR VISUAL SATISFACTION ---
            # Si on a l'intention visuelle, qu'on a au moins 1 image, et que le texte est stable depuis 5s
            # On sort "Succès" même si aria-busy est True.
            if self.has_visual_intent and images_count > 0 and stagnation_duration_approx > 5.0:
                 if not is_broken:
                     return True, "visual_satisfaction_early_exit"

            if not aria_busy:
                limit = 30
                if "THINKING" in self.current_phase: limit = 120

                if is_broken: 
                    if severity == "LOW" and stagnation_duration_approx > 15.0:
                         if "THINKING" in self.current_phase: return False, "thinking_wait_low_severity"
                         return True, "veto_decay_forced_completion_low_severity"
                    
                    if severity == "CRITICAL" and stagnation_duration_approx > 45.0:
                         return False, "request_active_recovery" 
                    limit = 150 
                
                if self.consecutive_stagnation_cycles > limit:
                    if is_broken:
                         if severity == "CRITICAL": return False, "request_active_recovery_busy"
                         return False, "veto_broken_structure_wait_busy"
                    return True, "deep_stagnation_while_busy"
            else:
                # Si busy, on tolère plus longtemps, MAIS on finit par couper
                if self.consecutive_stagnation_cycles > 60: # 30s de stagnation busy
                    return True, "deep_stagnation_while_busy" # C'est ce qui s'est passé dans vos logs
        else:
            if avg_velocity > stagnation_threshold:
                self.consecutive_stagnation_cycles = 0

        # 4. Auto-Extend
        if self.total_cycles > (self.hard_limit_cycles - 50) and avg_velocity > 5:
            if self.extended_count < self.max_extensions:
                self.hard_limit_cycles += 100
                self.extended_count += 1
                return False, f"generating_extended_high_velocity_{avg_velocity:.1f}"

        if self.total_cycles > self.hard_limit_cycles: 
            return True, "hard_timeout_limit_reached"
            
        return False, "generating"

class Orchestrator:
    """
    Superviseur V32 (Streaming Callback + Immune Memory + Enhanced Security).
    """
    def __init__(self, page: Page, stagnation_timeout_ms: int = 180000, intent: str = None, 
                 existing_images: List[str] = None, on_image_detected: Callable = None, **kwargs):
        self.page = page
        self.stagnation_timeout_ms = stagnation_timeout_ms
        self.intent = intent 
        self.existing_images = existing_images or []
        self.original_prompt = kwargs.get('prompt', '') 
        self.download_path = kwargs.get('download_path', './downloads') 
        self.on_image_detected = on_image_detected # Streaming Callback
        
        prompt_text = kwargs.get('prompt', '').lower()
        if not self.intent and prompt_text:
            visual_triggers = [
                r"image", r"dessine", r"draw", r"photo", r"illustration", 
                r"g[ée]n[èe]re\s+une?", r"cr[ée][ée]\s+une?", r"paint", r"sketch",
                r"visuel", r"rendering"
            ]
            combined_regex = "|".join(visual_triggers)
            if re.search(combined_regex, prompt_text, re.IGNORECASE | re.UNICODE):
                self.intent = "VISUAL"
                jlog("orchestrator_inferred_visual_intent", prompt_extract=prompt_text[:30])
        
        self.contract = {
            "must_have_image": (self.intent == "VISUAL"),
            "visual_scavenge_attempts": 0,
            "visual_scavenge_max": 3,
            "min_text_len_valid": 10
        }
        
        self.sse = SSEProducer(page, self._on_progress("sse"), self._on_done)
        self.ws = WSProducer(page, self._on_progress("ws"), self._on_done)
        self.be = BEProducer(page, self._on_progress("be"), self._on_done)
        self.dom = DOMProducer(page, self._on_progress("dom"), self._on_done)
        
        self._buf = {k: "" for k in PRIO}
        self._images_buf = [] 
        self._emitted_image_srcs = set() # Pour éviter les doublons dans le streaming
        
        self._done_evt = asyncio.Event()
        self._exit_code = 1
        self._emit_text = ""
        self._emit_meta = {}
        
        self._finalizing = False
        self._last_stagnation_heal_ts = 0
        self._heal_count = 0
        self._active_recovery_attempts = 0
        self._fatal_error_encountered = False
        
        self.last_text_size = 0
        self.generation_has_started = False
        self._stagnation_flag = False
        self._detector_ref = None 
        
        self._continuation_opportunity = None
        
        self.is_thinking = False 
        self.consecutive_validation_failures = 0
        self.virtualization_detected = False 
        self.dom_status_report = "normal" 

    async def _snapshot_image_urls(self) -> List[str]:
        try:
            return await self.page.evaluate("""() => {
                return Array.from(document.images).map(img => img.src).filter(src => src.length > 0);
            }""")
        except Exception:
            return []

    def _is_valid_image(self, img: Dict) -> bool:
        """
        Intelligence N°2 (V32+): Filtrage Visuel HEURISTIQUE (Anti-Avatar Renforcé).
        """
        src = img.get('src', '').lower()
        if not src: return False
        
        # 1. Blacklist Critique (Renforcée)
        if 'profile/picture' in src: return False
        if 'profile/photo' in src: return False
        if 'img.icons8.com' in src: return False
        if 'lh3.googleusercontent.com' in src and '/a/' in src: return False # Pattern avatar classique
        # Sécurité supplémentaire : Avatar par défaut Google
        if 's32-c' in src or 's64-c' in src: return False
        
        # 2. Scoring System & Heuristics
        score = 0
        w = img.get('width', 0)
        h = img.get('height', 0)
        
        # Règle HEURISTIQUE 1: L'interdiction formelle des avatars (Ratio Carré parfait et petite taille)
        # Les images générées sont rarement des carrés parfaits de < 512px, les avatars Google SI.
        if w > 0 and h > 0 and w == h and w < 512:
            return False

        # Règle HEURISTIQUE 2: L'entropie de l'URL
        # Les images réelles ont souvent des IDs longs ou des blobs. 
        # "profile/picture/0" est suspect car très court/générique.
        if "profile" in src and len(src.split('/')[-1]) < 5:
            return False

        # Règle HEURISTIQUE 3: Contexte (Alt text)
        alt = img.get('alt', '').lower()
        if "photo de profil" in alt or "compte" in alt:
             return False

        # a. Analyse de Surface
        area = w * h
        if area > 250000: score += 50
        elif area > 100000: score += 30
        elif area < 40000: score -= 50
        
        # b. Analyse de Ratio
        if h > 0:
            ratio = w / h
            if 0.6 <= ratio <= 1.8: score += 20
            else: score -= 20
        
        # c. Analyse de Source & Contexte
        if "googleusercontent.com" in src and "blob:" not in src:
            score -= 30 
        
        if "blob:" in src: score += 40
        if "data:image" in src:
            if len(src) > 50000: score += 20 
            else: score -= 40
            
        if "généré" in alt or "image" in alt or "generated" in alt: score += 20
        if "avatar" in alt or "profile" in alt: score -= 200 # Pénalité fatale
        
        # Seuil strict
        is_valid = score >= 60
        if not is_valid and score > -20:
             jlog("image_discarded_strict_score", src=src[:30], score=score, area=area)
            
        return is_valid

    def _on_progress(self, src: str):
        def _cb(chunk_or_payload: Any):
            if self._done_evt.is_set() or self._finalizing: return
            
            text_chunk = ""
            if isinstance(chunk_or_payload, dict):
                text_chunk = chunk_or_payload.get("text", "")
                
                if src in ["sse", "ws"]:
                     current_sse_len = len(self._buf.get(src, "") + text_chunk)
                     current_dom_len = len(self._buf.get("dom", ""))
                     if current_dom_len > 0 and current_sse_len > 1000:
                         ratio = current_sse_len / current_dom_len
                         if ratio > 1.5 and not self.virtualization_detected:
                             self.virtualization_detected = True
                             jlog("virtualization_detected_realtime", ratio=f"{ratio:.2f}", src=src)

                if "images" in chunk_or_payload and chunk_or_payload["images"]:
                    current_srcs = {i['src'] for i in self._images_buf}
                    existing_set = set(self.existing_images) 
                    
                    for img in chunk_or_payload["images"]:
                        img_src = img['src']
                        if img_src and img_src not in current_srcs:
                            if img_src in existing_set or not self._is_valid_image(img):
                                continue
                            self._images_buf.append(img)
                            jlog("orchestrator_image_captured", src=img_src[:30], source_producer=src)
                            
                            # --- STREAMING CALLBACK ---
                            if self.on_image_detected and img_src not in self._emitted_image_srcs:
                                self._emitted_image_srcs.add(img_src)
                                try:
                                    # Lancement non-bloquant du callback
                                    asyncio.create_task(self.on_image_detected(img))
                                    jlog("streaming_callback_dispatched", src=img_src[:30])
                                except Exception as e:
                                    jlog("streaming_callback_error", error=str(e))

                if "meta" in chunk_or_payload:
                    meta = chunk_or_payload["meta"]
                    if "dom_status" in meta: self.dom_status_report = meta["dom_status"]
                    if meta.get("continuation_candidate"):
                        self._continuation_opportunity = meta["continuation_candidate"]
                        if self._heal_count > 0: 
                             asyncio.create_task(self._heal_stagnation(level=3, target=self._continuation_opportunity))
                    
                    new_thinking_state = meta.get("is_thinking_state", False)
                    if self.is_thinking and not new_thinking_state:
                         jlog("orchestrator_thinking_phase_ended_reset_watchdog")
                         if self._detector_ref: self._detector_ref.reset_stagnation("thinking_phase_end")
                    
                    self.is_thinking = new_thinking_state
                    if self._detector_ref:
                        self._detector_ref.set_phase("THINKING" if self.is_thinking else "GENERATING")

            else:
                text_chunk = str(chunk_or_payload)

            self._buf[src] = (self._buf.get(src, "") + text_chunk)[-2000000:] 
            
            if any(s in text_chunk for s in SENTINELS):
                asyncio.create_task(self._on_done(src, self._buf[src]))
                
        return _cb

    async def _on_done(self, src: str, final_text: str = None, **kwargs):
        if self._done_evt.is_set(): return
        
        text = final_text if final_text is not None else self._buf.get(src, "")
        self._buf[src] = text 
        text = normalize_stream_artifacts(text)

        len_be = len(self._buf.get("be", ""))
        len_dom = len(text)
        
        bypass_validation = False
        if self.consecutive_validation_failures >= 3:
            bypass_validation = True
        
        if self._detector_ref:
             is_fatal, _ = self._detector_ref._check_fatal_errors(text)
             if is_fatal:
                 self._fatal_error_encountered = True

        if not bypass_validation and len_be > 500 and len_dom > 0:
            ratio = len_be / len_dom
            threshold = 2.5 if self.virtualization_detected else 1.3
            
            if ratio > threshold: 
                if not self.virtualization_detected:
                    self.virtualization_detected = True
                    jlog("virtualization_detected_on_done_check", ratio=f"{ratio:.2f}")
                
                if src == "dom" or src == "forced_completion_call":
                    src = "forced_hybrid_mismatch" 

        if not bypass_validation and src != "forced_hybrid_mismatch" and not self._fatal_error_encountered:
             if len(text) > 20 and not is_head_semantically_valid(text):
                 jlog("head_integrity_failure_detected", src=src, len=len(text))
                 clipboard_text = await self._harvest_via_clipboard_resilient(force_verification=True)
                 if clipboard_text and is_head_semantically_valid(clipboard_text):
                      jlog("head_integrity_saved_by_clipboard", len_clip=len(clipboard_text))
                      text = clipboard_text
                      src = "clipboard_recovery"
                 else:
                     if self._active_recovery_attempts < 3:
                         self.consecutive_validation_failures += 1
                         await self._heal_stagnation(level=4) 
                         self._active_recovery_attempts += 1
                         if self._detector_ref: self._detector_ref.reset_stagnation("head_integrity_failure")
                         return 

        found_sentinel = False
        clean_text_val = text
        for s in SENTINELS:
            if s in text:
                clean_text_val = text.split(s)[0].strip()
                found_sentinel = True
                break
        
        if found_sentinel or src.startswith("clipboard") or src == "forced" or src == "forced_completion_call" or src == "forced_hybrid_mismatch" or self._fatal_error_encountered:
            self._finalizing = True
            
            clipboard_text = None
            if not src.startswith("clipboard"):
                force_verify = (src == "forced_hybrid_mismatch" or self.virtualization_detected)
                if not force_verify and src == "forced_completion_call" and not self._fatal_error_encountered: force_verify = True
                
                if force_verify: jlog("triggering_golden_copy_proactive", reason=src)
                clipboard_text = await self._harvest_via_clipboard_resilient(force_verification=(force_verify and not bypass_validation))
            
            current_buffer = self._buffer_consolidate()
            use_clipboard = False
            
            if clipboard_text:
                clipboard_text = normalize_stream_artifacts(clipboard_text) 
                len_clip = len(clipboard_text)
                len_buf = len(current_buffer)
                
                clip_head_ok = is_head_semantically_valid(clipboard_text) or bypass_validation
                buf_head_ok = is_head_semantically_valid(current_buffer) or bypass_validation

                if clip_head_ok and not buf_head_ok:
                     clean_text_val = clipboard_text
                     use_clipboard = True
                elif not clip_head_ok and buf_head_ok:
                     pass
                elif len_clip >= len_buf * 0.9: 
                    clean_text_val = clipboard_text
                    use_clipboard = True
            
            for s in SENTINELS: clean_text_val = clean_text_val.split(s)[0].strip()
            final_output = repair_structure(normalize_stream_artifacts(clean_text_val))
            
            # LAST RESORT IMAGE FETCH
            if self.contract["must_have_image"] and len(self._images_buf) == 0 and not self._fatal_error_encountered:
                jlog("orchestrator_final_check_last_resort_fetch")
                try:
                    last_img_url = await self.page.evaluate("""() => { 
                         const imgs = Array.from(document.querySelectorAll('img'));
                         let best = null;
                         let maxArea = 0;
                         for (let i of imgs) {
                             if (i.src.includes('profile')) continue;
                             let area = i.naturalWidth * i.naturalHeight;
                             if (area > 100000 && area > maxArea) {
                                 maxArea = area;
                                 best = i.src;
                             }
                         }
                         return best;
                    }""")
                    
                    if last_img_url:
                        dest_fetch = Path(self.download_path) / f"fetched_last_resort_{int(time.time())}.png"
                        if await DownloadHandler.fallback_download_via_fetch(self.page, last_img_url, str(dest_fetch)):
                             img_meta = {
                                 "src": f"file://{dest_fetch.absolute()}", 
                                 "alt": "Last Resort Fetched", 
                                 "width": 1024, "height": 1024
                             }
                             self._images_buf.append(img_meta)
                             jlog("orchestrator_last_resort_fetch_success")
                             
                             # Notifier aussi le streaming
                             if self.on_image_detected:
                                 asyncio.create_task(self.on_image_detected(img_meta))
                except: pass

            self._emit_text = final_output
            self._emit_meta = {
                "source": "clipboard" if use_clipboard else src, 
                "clean_exit": True, 
                "sentinel": found_sentinel,
                "intent_satisfied": not self._fatal_error_encountered,
                "images": self._images_buf,
                "fatal_error": self._fatal_error_encountered
            }
            self._exit_code = 0 if not self._fatal_error_encountered else 1
            self._done_evt.set()
            return
        
        jlog("producer_finished_without_sentinel", src=src)

    async def _handle_download(self, download: Download):
        try:
            suggested_filename = download.suggested_filename
            jlog("download_started", filename=suggested_filename)
            
            dest_dir = Path(self.download_path)
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            path = await download.path()
            if not path:
                return

            file_size = os.path.getsize(path)
            if file_size < 1024:
                jlog("download_integrity_fail_too_small", size=file_size, filename=suggested_filename)
                return

            dest_path = dest_dir / f"{int(time.time())}_{suggested_filename}"
            await download.save_as(dest_path)
            
            jlog("download_completed_verified", path=str(dest_path), size=file_size)
            
            img_meta = {
                "src": f"file://{dest_path.absolute()}",
                "alt": f"Downloaded: {suggested_filename}",
                "width": 1024, 
                "height": 1024,
                "confidence": 100 
            }
            self._images_buf.append(img_meta)
            
            if self.on_image_detected:
                asyncio.create_task(self.on_image_detected(img_meta))
            
            if self.contract["must_have_image"]:
                jlog("visual_contract_satisfied_by_download")
                if self._detector_ref: self._detector_ref.reset_stagnation("download_success")
                
        except Exception as e:
            jlog("download_handling_error", error=str(e))

    async def _harvest_via_clipboard_resilient(self, force_verification: bool = False) -> Optional[str]:
        try:
            try: await self.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            except: pass

            jlog("golden_copy_strategy_keyboard_focus")
            
            try:
                await self.page.click("body", timeout=500)
                await self.page.keyboard.press("Escape") 
                await asyncio.sleep(0.2)
                
                target_sel = ".model-response-text"
                if await self.page.locator(target_sel).count() > 0:
                     await self.page.locator(target_sel).last.click(force=True, timeout=1000)
                else:
                     await self.page.click("article", timeout=1000)
            except: 
                pass 

            await asyncio.sleep(0.3)
            modifier = "Meta" if sys.platform == "darwin" else "Control"
            
            await self.page.keyboard.down(modifier)
            await self.page.keyboard.press("a")
            await self.page.keyboard.up(modifier)
            await asyncio.sleep(0.2)
            
            await self.page.keyboard.down(modifier)
            await self.page.keyboard.press("c")
            await self.page.keyboard.up(modifier)
            await asyncio.sleep(0.3)
            
            content = await self.page.evaluate("navigator.clipboard.readText()")
            
            if content and len(content) > 10:
                content = normalize_stream_artifacts(content)
                
                # 1. Nettoyage du Début (Contextual Anchoring)
                if self.original_prompt:
                    anchor = self.original_prompt[:50].lower() 
                    content_lower = content.lower()
                    last_occurrence = content_lower.rfind(anchor)
                    
                    if last_occurrence != -1:
                         cut_index = last_occurrence + len(self.original_prompt)
                         cleaned_content = content[cut_index:].strip()
                         cleaned_content = re.sub(r'^\d{1,2}:\d{2}\s+', '', cleaned_content).strip()
                         content = cleaned_content
                         jlog("golden_copy_contextual_anchoring_success", removed_chars=cut_index)

                # 2. Nettoyage de la Fin (Intelligence N°1 : Semantic Footer Stripping)
                # On cherche la position la plus "haute" d'un footer connu pour couper AVANT.
                cut_index_end = len(content)
                footer_found = False
                content_lower_final = content.lower()
                
                for footer_phrase in STATIC_FOOTERS:
                    idx = content_lower_final.find(footer_phrase.lower())
                    if idx != -1 and idx < cut_index_end:
                        cut_index_end = idx
                        footer_found = True
                
                if footer_found:
                    content = content[:cut_index_end].strip()
                    jlog("golden_copy_semantic_footer_stripped", kept_len=len(content))
                
                if len(content) > 0:
                    return content
                
            return None

        except Exception as e:
            jlog("golden_copy_error_keyboard", error=str(e))
            return None

    def _buffer_consolidate(self) -> str:
        best_len = -1
        best_txt = ""
        for k in ["sse", "ws", "dom", "be"]:
            curr = self._buf.get(k, "")
            curr_clean = normalize_stream_artifacts(curr)
            if len(curr_clean) > best_len:
                best_len = len(curr_clean)
                best_txt = curr_clean
        return best_txt

    async def _heal_stagnation(self, level: int, target: Optional[Dict] = None):
        """
        Système de réparation intelligent (Immune System).
        Si target est None, utilise la meilleure stratégie connue.
        """
        now = time.monotonic()
        if level < 3 and now - self._last_stagnation_heal_ts < 5.0: return
        self._last_stagnation_heal_ts = now
        self._heal_count += 1
        
        # Intelligence: Choix de la stratégie
        strategies = HealingMemory.get_best_strategy() if not target else [level]
        # Si on est en mode générique (pas de target), on itère sur les meilleures strats
        current_level = strategies[0] if not target else level
        
        jlog("orchestrator_healing_attempt", level=current_level, count=self._heal_count, specific_target=bool(target))
        
        success = False
        try:
            if current_level == 4:
                clicked = await RecoveryHandler.attempt_generic_retry(self.page)
                if clicked:
                    jlog("orchestrator_healing_triggered_retry_button")
                    if self._detector_ref: self._detector_ref.reset_stagnation("auto_retry_click")
                    self._active_recovery_attempts += 1
                    success = True

            elif target and current_level == 3:
                sel = target.get("selector")
                try:
                    await self.page.click(sel, timeout=1000)
                    if self._detector_ref: self._detector_ref.reset_stagnation("targeted_click_success")
                    self._continuation_opportunity = None 
                    success = True
                except: pass

            elif current_level == 1:
                await self.page.evaluate("document.body.focus()")
                await self.page.mouse.move(100, 100)
                await self.page.evaluate("window.scrollBy(0, 10);")
                success = True
                
            elif current_level == 2:
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                success = True
                
            elif current_level == 3 and not target: 
                 await self.page.evaluate("document.body.click()")
                 success = True
            
            # Apprentissage
            HealingMemory.update(current_level, success)

        except Exception as e:
            jlog("healing_error", error=str(e))
            HealingMemory.update(current_level, False)

    async def runfastpath(self) -> Tuple[str, Dict, int, int]:
        self.page.on("download", lambda download: asyncio.create_task(self._handle_download(download)))
        
        if not self.existing_images:
             self.existing_images = await self._snapshot_image_urls()
             jlog("orchestrator_baseline_snapshot_taken", count=len(self.existing_images))

        await asyncio.gather(
            self.sse.start(), self.ws.start(), self.be.start(), self.dom.start(),
            return_exceptions=True
        )
        
        start_ts = time.monotonic()
        detector = IntelligentGenerationCompleteDetector(page=self.page, expected_format=self.intent)
        self._detector_ref = detector 
        
        try:
            while not self._done_evt.is_set():
                elapsed_ms = (time.monotonic() - start_ts) * 1000
                if elapsed_ms > (self.stagnation_timeout_ms * 2.5): 
                    jlog("orchestrator_watchdog_timeout", level="ERROR")
                    break
                
                if self._stagnation_flag: break

                current_text = self._buffer_consolidate()
                self.last_text_size = len(current_text)
                if self.last_text_size > 10: self.generation_has_started = True

                aria_busy = False
                try: aria_busy = await self.page.evaluate("() => document.querySelector('[aria-busy=\"true\"]') !== null")
                except: pass

                is_done, reason = await detector.analyze_generation_complete(
                    current_text, 
                    aria_busy,
                    images_count=len(self._images_buf),
                    dom_status=self.dom_status_report
                )
                
                if "FATAL_ERROR" in reason:
                    self._fatal_error_encountered = True
                    is_done = True
                    jlog("orchestrator_aborting_due_to_fatal_error", reason=reason)

                if is_done and self.contract["must_have_image"] and len(self._images_buf) == 0 and not self._fatal_error_encountered:
                    if detector.current_phase == "AWAITING_MEDIA_RENDER" or detector.current_phase == "THINKING_VISUAL":
                         is_done = False
                         jlog("orchestrator_waiting_visual_processing")
                    
                    elif self.contract["visual_scavenge_attempts"] < self.contract["visual_scavenge_max"]:
                        self.contract["visual_scavenge_attempts"] += 1
                        jlog("orchestrator_enforcing_visual_contract_scavenge", attempt=self.contract["visual_scavenge_attempts"])
                        
                        scavenged_imgs = await self.dom.scavenge_images(existing_images_blacklist=self.existing_images)
                        
                        valid_scavenged = [img for img in scavenged_imgs if self._is_valid_image(img)]
                        
                        if valid_scavenged:
                            jlog("orchestrator_scavenge_success", count=len(valid_scavenged))
                            self._images_buf.extend(valid_scavenged)
                            # Notifier le streaming
                            if self.on_image_detected:
                                for img in valid_scavenged:
                                    if img['src'] not in self._emitted_image_srcs:
                                        self._emitted_image_srcs.add(img['src'])
                                        asyncio.create_task(self.on_image_detected(img))
                            
                            is_done = False
                            detector.reset_stagnation("visual_contract_scavenge_success")
                        else:
                            jlog("orchestrator_attempting_download_action")
                            # Trigger Fallback Fetch si le bouton échoue (via UI Interaction)
                            clicked = await self.dom.trigger_download_action()
                            
                            if not clicked.get("triggered") or self.contract["visual_scavenge_attempts"] >= 2:
                                jlog("orchestrator_initiating_fallback_fetch_strategy")
                                last_img_url = await self.page.evaluate("""() => { 
                                    const imgs = Array.from(document.querySelectorAll('img'));
                                    let best = null;
                                    let maxArea = 0;
                                    for (let i of imgs) {
                                        let area = i.naturalWidth * i.naturalHeight;
                                        if (area > 50000 && area > maxArea && i.src.startsWith('http')) {
                                            maxArea = area;
                                            best = i.src;
                                        }
                                    }
                                    return best;
                                }""")
                                
                                if last_img_url:
                                     dest_fetch = Path(self.download_path) / f"fetched_{int(time.time())}.png"
                                     dest_fetch.parent.mkdir(parents=True, exist_ok=True)
                                     
                                     success = await DownloadHandler.fallback_download_via_fetch(self.page, last_img_url, str(dest_fetch))
                                     if success:
                                         img_meta = {
                                             "src": f"file://{dest_fetch.absolute()}", 
                                             "alt": "Fetched Fallback", 
                                             "width": 1024, 
                                             "height": 1024,
                                             "confidence": 90
                                         }
                                         self._images_buf.append(img_meta)
                                         if self.on_image_detected: asyncio.create_task(self.on_image_detected(img_meta))
                                         detector.reset_stagnation("fallback_fetch_success")
                                         is_done = False # On laisse un cycle pour valider

                            await asyncio.sleep(2.0)
                            is_done = False 
                            if self.contract["visual_scavenge_attempts"] == self.contract["visual_scavenge_max"]:
                                jlog("orchestrator_visual_contract_failed_giving_up", level="WARN")
                                is_done = True 
                    else:
                        is_done = True

                if "request_active_recovery" in reason:
                     await self._heal_stagnation(4)
                     continue 

                stagnation_cycles = detector.consecutive_stagnation_cycles
                if stagnation_cycles > 0:
                    is_veto = "veto" in reason or "visual" in reason or "thinking" in reason or "debt" in reason
                    if is_veto:
                        pass 
                    elif stagnation_cycles % 20 == 0:
                        asyncio.create_task(self._heal_stagnation(1 if stagnation_cycles < 60 else 2))

                if is_done:
                    jlog("orchestrator_decision", reason=reason)
                    final_txt = current_text
                    await self._on_done("forced_completion_call", final_txt)
                    
                    if not self._done_evt.is_set():
                        jlog("orchestrator_decision_overruled_by_head_check")
                        continue
                    break
                
                await asyncio.sleep(0.5)
                
        finally:
            await self._stop_all()
            
        if not self._emit_text:
             self._emit_text = repair_structure(self._buffer_consolidate())
             
        return self._emit_text, self._emit_meta, self._exit_code, 0

    async def _stop_all(self):
        stop_tasks = []
        for prod in [self.sse, self.ws, self.be, self.dom]:
            if hasattr(prod, "stop"):
                stop_tasks.append(asyncio.create_task(prod.stop()))
        if stop_tasks:
            await asyncio.wait(stop_tasks, timeout=2.0)