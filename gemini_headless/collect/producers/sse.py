# gemini_headless/collect/producers/sse.py
# CORRIGÉ FINAL : Harmonisation des fonctions d'extraction avec be.py
# 🚀 INTELLIGENCE ADDITIONNELLE (ADAPTIVE SILENCE & CONTEXT AWARENESS) :
# - Calcul dynamique du seuil de silence basé sur la vélocité des tokens.
# - Remplacement de la constante fixe par une moyenne glissante.
# - [NOUVEAU] Context Awareness : Détection des blocs de code pour étendre le timeout.

from __future__ import annotations
import json, re, time, random 
from typing import Callable, Dict, Optional, Set, Any, List
from playwright.async_api import Page, Error as PlaywrightError
import asyncio
import traceback

try:
    # Use relative import within the package
    from ...connectors.cdp_multiattach import CDPMultiTarget
except ImportError:
    # Fallback for running script directly or package structure issues
    try:
        from gemini_headless.connectors.cdp_multiattach import CDPMultiTarget # type: ignore
    except Exception:
        CDPMultiTarget = None  # type: ignore

try:
    from ...utils.logs import jlog
except Exception:
    try:
        from utils.logs import jlog # type: ignore
    except Exception:
        import sys
        def jlog(evt: str, **_k):
            try:
                payload = {"evt": evt, "ts": time.time(), "level": "INFO", "module": "sse.py", **_k}
                print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr)
                sys.stderr.flush()
            except Exception:
                print(f'{{"evt":"jlog_sse_fallback","original_evt":"{evt}"}}', file=sys.stderr)

_DONE_EVENTS: Set[str] = {"done", "complete", "completed", "finish", "finished", "end", "ended"}

# --- Heuristique V2 (Copiée de be.py) ---
def _looks_like_potential_answer_text(s: str) -> bool:
    """Heuristic V2: Stricter rejection of metadata, better prose detection"""
    if not s: return False
    s_strip = s.strip()
    if len(s_strip) < 5: return False # Minimum length

    low = s_strip.lower()
    if low in {"null", "{}", "[]", "true", "false", "ok", "[start]", "[end]", "ping"}: return False

    # *** Explicit rejection of known metadata patterns ***
    if s_strip.startswith('[[[[') or \
       s_strip.startswith('[[["me"') or \
       s_strip.startswith('[null,'): # Stricter check
        jlog("sse_heuristic_reject_reason", reason="starts_with_metadata_pattern", head=s_strip[:60])
        return False

    # Reject simple URLs/paths or pure JSON structures
    if re.fullmatch(r"https?://\S+", s_strip): return False
    if re.fullmatch(r"\{.*\}", s_strip): return False
    if re.fullmatch(r"\[.*\]", s_strip): return False

    # Must contain at least some letters and spaces
    if not re.search(r"[A-Za-zÀ-ÿ]", s_strip): return False
    return True

def _collect_texts_robust(node: Any, acc: List[str], seen: Set[int], max_depth: int = 12, depth: int = 0) -> None:
    """DFS over any JSON-like structure, extracting human text; avoids duplicates & metadata."""
    if depth > max_depth: return
    try:
        if id(node) in seen: return
        seen.add(id(node))
    except Exception:
        pass

    if isinstance(node, str):
        st = node.strip()
        if _looks_like_potential_answer_text(st) and st not in acc: acc.append(st)
        return

    if isinstance(node, dict):
        candidates = node.get("candidates")
        if isinstance(candidates, list):
            for c in candidates:
                try:
                    content = c.get("content") if isinstance(c, dict) else None
                    if isinstance(content, dict):
                        parts = content.get("parts")
                        if isinstance(parts, list):
                            for p in parts:
                                text = p.get("text") if isinstance(p, dict) else None
                                if isinstance(text, str):
                                    st = text.strip()
                                    if st and _looks_like_potential_answer_text(st) and st not in acc: acc.append(st)
                except Exception as e_cand:
                    jlog("collect_texts_candidate_error", error=str(e_cand), level="DEBUG")

        # Generic keys
        for key in ("text", "content", "message", "snippet", "title"):
            value = node.get(key)
            try:
                value_id = id(value); hash(value)
                if value_id in seen: continue
            except Exception:
                pass
            _collect_texts_robust(value, acc, seen, max_depth, depth+1)

    elif isinstance(node, list):
        for it in node:
            _collect_texts_robust(it, acc, seen, max_depth, depth+1)

# --- Intelligence : Helper de contexte ---
def _is_generating_code(text: str) -> bool:
    """Detects if we are currently inside an open code block."""
    if not text: return False
    # Compte les occurrences de ```
    # Si impair, un bloc est ouvert.
    count = text.count("```")
    return (count % 2) != 0

class SSEProducer:
    def __init__(self, page: Page, on_progress: Callable[[str], None], on_done: Callable[[str, Optional[str]], None]):
        self.page = page
        self.on_progress_cb = on_progress
        self.on_done_cb = on_done
        self.seen = False
        self.done = False
        self._mt: Optional[CDPMultiTarget] = None
        self._buf: Dict[int, str] = {}
        self._token_count = 0
        self._active_es: Set[str] = set()
        self._last_message_ts: Optional[float] = None
        self._silence_check_task: Optional[asyncio.Task] = None
        
        # INTELLIGENCE: Tracking vélocité pour seuil dynamique
        self._arrival_deltas: List[float] = [] # Stores last 10 delays

    async def start(self) -> None:
        if self._mt is not None:
            jlog("sse_start_skipped_already_started", level="WARN"); return
        if self.page.is_closed() or self.page.context.is_closed():
            jlog("sse_start_fail_page_closed"); return
        try:
            self.seen = False; self.done = False; self._token_count = 0
            self._buf.clear(); self._active_es.clear(); self._last_message_ts = None
            self._arrival_deltas = []

            self._mt = CDPMultiTarget(self.page)
            self._mt.on("Network.responseReceived", self._on_response_received)
            self._mt.on("Network.eventSourceMessageReceived", self._on_sse_message)
            self._mt.on("Network.loadingFinished", self._on_loading_finished)
            await self._mt.start()
            jlog('sse_start_ok_cdp_ready')
            if self._silence_check_task is None or self._silence_check_task.done():
                self._silence_check_task = asyncio.create_task(self._check_silence_loop(), name="sse_silence_check")
                jlog("sse_start_ok_silence_task_created")
            else:
                jlog("sse_start_ok_silence_task_reused", level="WARN")
        except Exception as e:
            jlog("sse_start_error", error=str(e), error_type=type(e).__name__, traceback=traceback.format_exc(limit=3), level="CRITICAL")
            await self._cleanup_resources()

    async def _cleanup_resources(self):
        jlog("sse_cleanup_resources_start")
        try:
            if self._silence_check_task and not self._silence_check_task.done():
                self._silence_check_task.cancel()
                try: await asyncio.wait_for(self._silence_check_task, timeout=0.5)
                except Exception: pass
        finally:
            self._silence_check_task = None
        try:
            if self._mt:
                await self._mt.stop()
        except Exception as e:
            jlog("sse_cleanup_mt_stop_error", error=str(e), level="WARN")
        finally:
            self._mt = None
        jlog("sse_cleanup_resources_end")

    def _on_response_received(self, params: Dict) -> None:
        if self.done: return
        try:
            r = params.get("response", {})
            req_id = params.get("requestId")
            mime = r.get("mimeType", ""); url = (r.get('url') or '')
            if isinstance(mime, str) and "event-stream" in mime and req_id:
                if req_id not in self._active_es:
                    self._active_es.add(req_id)
                    self._last_message_ts = time.monotonic()
                    jlog("sse_seen_stream", requestId=req_id, mimeType=mime, url=url, active_count=len(self._active_es))
        except Exception as e:
            jlog("sse_on_response_received_error", error=str(e), error_type=type(e).__name__, level="WARN", params_head=str(params)[:200])

    def _on_loading_finished(self, params: Dict) -> None:
        if self.done: return
        try:
            req_id = params.get("requestId")
            if req_id in self._active_es:
                jlog("sse_loading_finished_for_active_stream", requestId=req_id)
        except Exception as e:
            jlog("sse_on_loading_finished_error", error=str(e), error_type=type(e).__name__, level="WARN", params_head=str(params)[:200])

    def _on_sse_message(self, params: Dict) -> None:
        jlog("_on_sse_message_invoked_debug", requestId=params.get("requestId","unknown_reqid"), params_keys=list(params.keys()), level="DEBUG")
        req_id = params.get("requestId", "unknown_reqid")
        jlog("sse_on_message_callback_invoked_debug", requestId=req_id, params_keys=list(params.keys()), level="DEBUG")
        if self.done: return

        try:
            if self._active_es and req_id not in self._active_es:
                jlog("sse_ignore_inactive_stream_message", requestId=req_id, active_ids=list(self._active_es), level="DEBUG")
                return

            self.seen = True
            now = time.monotonic()
            
            # INTELLIGENCE: Calcul vélocité
            if self._last_message_ts:
                delta = now - self._last_message_ts
                self._arrival_deltas.append(delta)
                if len(self._arrival_deltas) > 10: self._arrival_deltas.pop(0)
            
            self._last_message_ts = now
            self._token_count += 1

            event_name = (params.get("eventName") or "").strip().lower()
            data = params.get("data") or ""

            jlog("sse_raw_message_data_debug", requestId=req_id, event_name=event_name, data_head=str(data)[:200], data_len=len(str(data)), level="DEBUG")

            text = self._extract_text_robust(str(data))
            if text:
                # Concat simple par incrément (clé = token count)
                self._buf[self._token_count] = text
                self.on_progress_cb(text)
                jlog("sse_progress_text_added", token=self._token_count, inc_len=len(text), snapshot_len=len(self._snapshot() or ""))

            # Check fin de flux
            if event_name in _DONE_EVENTS:
                self.done = True
                final_txt = self._snapshot() or ""
                self.on_done_cb(final_txt, "sse")
                jlog("sse_done_event", event=event_name, final_len=len(final_txt))
        except Exception as e:
            jlog("sse_on_message_error", error=str(e), error_type=type(e).__name__, level="ERROR",
                 traceback=traceback.format_exc(),
                 raw_params_head=str(params)[:200])

    def _snapshot(self) -> Optional[str]:
        if not self._buf: return None
        full_text = " ".join(self._buf[k] for k in sorted(self._buf.keys())).strip()
        if full_text:
            full_text = full_text.replace("\r\n","\n").replace("\r","\n")
            full_text = re.sub(r"[ \t]+\n", "\n", full_text)
            full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        return full_text if full_text else None

    async def _check_silence_loop(self) -> None:
        # Initial wait
        await asyncio.sleep(2.0)
        jlog("sse_silence_check_loop_started")
        
        try:
            while not self.done:
                # INTELLIGENCE : Calcul dynamique du seuil
                current_threshold = 2.5 # Fallback default
                
                if self._arrival_deltas:
                    avg_speed = sum(self._arrival_deltas) / len(self._arrival_deltas)
                    # On laisse 4x le temps moyen d'arrivée d'un token, min 1s, max 5s
                    current_threshold = max(1.0, min(5.0, avg_speed * 4.0))
                
                # INTELLIGENCE : Contexte (Bloc de Code)
                current_text = self._snapshot()
                if current_text and _is_generating_code(current_text):
                     # On triple la patience si on est au milieu d'un bloc de code
                     current_threshold *= 3.0
                     # jlog("sse_silence_extended_code_block", new_threshold=round(current_threshold, 1), level="DEBUG")

                # Check silence
                if self.seen and self._last_message_ts is not None:
                    silence_duration = time.monotonic() - self._last_message_ts
                    
                    if silence_duration >= current_threshold:
                        jlog("sse_silence_threshold_reached_dynamic", 
                             silence_duration=round(silence_duration,2), 
                             threshold=round(current_threshold,2),
                             avg_token_speed=round(sum(self._arrival_deltas)/len(self._arrival_deltas),3) if self._arrival_deltas else "N/A",
                             in_code_block=_is_generating_code(current_text or ""))
                        
                        final_text_snapshot = self._snapshot()
                        if final_text_snapshot and not self.done:
                            self.on_done_cb(final_text_snapshot, "sse")
                            self.done = True
                            jlog("sse_mark_done_on_silence", total_tokens=self._token_count, final_len=len(final_text_snapshot))
                        else:
                            # Pas de texte utile malgré SSE
                            jlog("sse_silence_no_text_snapshot", tokens=self._token_count)
                
                # Sleep adaptatif (moitié du seuil actuel)
                sleep_time = max(0.2, current_threshold / 2)
                await asyncio.sleep(sleep_time + random.uniform(0.05, 0.1))
                if self.done: break

        except asyncio.CancelledError:
            jlog("sse_silence_check_cancelled")
        except Exception as e:
            jlog("sse_silence_check_error", error=str(e), error_type=type(e).__name__, level="WARN")

    def _extract_text_robust(self, raw: str) -> str:
        s = raw
        if s.lstrip().startswith("data:"): s = s.lstrip()[len("data:"):]
        s_strip = s.strip()
        if not s_strip: return ""

        texts_found: List[str] = []
        try:
            obj = json.loads(s_strip)
            _collect_texts_robust(obj, texts_found, set(), max_depth=15)
            if texts_found:
                joined_text = " ".join(t.strip() for t in texts_found if t.strip())
                if _looks_like_potential_answer_text(joined_text):
                    return joined_text
                else:
                    jlog("sse_extract_text_robust_rejected_post_collect", head=joined_text[:100], level="DEBUG")
                    return ""
            else:
                return ""
        except json.JSONDecodeError:
            if _looks_like_potential_answer_text(s_strip):
                return s_strip
            else:
                jlog("sse_extract_text_robust_rejected_raw", head=s_strip[:100], level="DEBUG")
                return ""
        except Exception as e:
            jlog("sse_extract_text_robust_unexpected_error", error=str(e), error_type=type(e).__name__, raw_head=raw[:100], level="WARN")
            if _looks_like_potential_answer_text(s_strip): return s_strip
        return ""