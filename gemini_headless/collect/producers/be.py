### gemini_headless/collect/producers/be.py
# -*- coding: utf-8 -*-
# ✅ ARCHITECT UPDATE V16 "VISUAL TRUTH & DEEP SCAN"
# - Feature: Déduplication Structurelle (Anti-Loop)
# - Feature: Resynchronisation de Flux (Zipper)
# - Feature: Nettoyage des Débris
# - Feature: "Deep Image Scan" -> Extraction des URLs d'images directement depuis les RPCs (Network Layer)

from __future__ import annotations
import asyncio
import json
import re
import time
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple, Set
from playwright.async_api import Page, Response
from urllib.parse import urlparse, parse_qs

# --- Imports pour les Patches ---
import json as _json
import re as _re

try:
    from ..utils.logs import jlog
except ImportError:
    def jlog(*_a, **_k): pass

# ============================================================================
# INTELLIGENCE N°4 : NETTOYAGE SYNTAXIQUE & DÉBRIS
# ============================================================================

def _clean_start_debris(text: str) -> str:
    """
    Nettoie les fragments de phrase en début de texte (souvent dus à une coupe CoT imparfaite).
    Ex: " sur les réseaux sociaux." -> "Sur les réseaux sociaux." (ou suppression si trop court)
    """
    if not text: return text
    
    # 1. Si commence par une ponctuation de liaison ou minuscule bizarre
    # Ex: ", et donc..." ou " sur le..."
    bad_start_pat = re.compile(r'^\s*([,;:.?!])\s*')
    if bad_start_pat.match(text):
        text = bad_start_pat.sub('', text)

    # 2. Capitalisation de la première lettre si c'est du texte propre
    s = text.lstrip()
    if s and s[0].islower() and len(s) > 1:
        # On ne capitalise que si ce n'est pas un code ou un truc spécial
        text = s[0].upper() + s[1:]
        
    return text

def _clean_syntax_artifacts(text: str) -> str:
    """
    Nettoie les artefacts spécifiques aux LLM.
    """
    if not text: return text
    
    # 1. Suppression des citations de type 【1:0†source】 ou [1]
    text = re.sub(r'【\d+:\d+†source】', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    
    # 2. Normalisation des sauts de ligne (Max 2 consécutifs)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 3. Nettoyage des espaces insécables ou invisibles
    text = text.replace('\u00a0', ' ').replace('\u200b', '')
    
    return text

# ============================================================================
# INTELLIGENCE N°1 : DÉTECTION DE FRONTIÈRE SÉMANTIQUE (ANTI-COT V3)
# ============================================================================

def _strip_thinking_process(text: str) -> str:
    """
    Supprime le 'Thinking Process' (CoT) du modèle.
    """
    if not text: return text
    
    # Vocabulaire élargi
    verbs = (
        r"Analyz|Unpack|Structur|Refin|Draft|Explor|Plan|Think|Defin|Identif|"
        r"Drill|Div|Summariz|Initiat|Focus|Calculat|Review|Check|Catalog|Organiz"
    )
    
    # Regex Headers
    thought_header_pat = re.compile(
        rf'(?m)^\s*[\*#-]+\s*(?:{verbs})ing.*?(?:[\*:-]|$)'
    )
    
    # Regex Voix Interne
    internal_voice_pat = re.compile(r"(?i)\b(i'm|i've|i'd|i am|my (focus|plan|goal|step)|i (will|ll|have|need))\b")
    
    # Regex Fragment
    fragment_pat = re.compile(r"^\s*([a-z]|[.,;])")

    has_header = bool(thought_header_pat.search(text))
    has_internal = bool(internal_voice_pat.search(text[:300]))
    
    if not has_header and not has_internal:
        return text

    parts = re.split(r'(\n\s*\n)', text)
    clean_buffer = []
    in_thinking_mode = False
    
    for i, part in enumerate(parts):
        if not part.strip():
            if not in_thinking_mode: clean_buffer.append(part)
            continue

        is_header = bool(thought_header_pat.search(part))
        is_internal = bool(internal_voice_pat.search(part))
        is_fragment = bool(fragment_pat.match(part))
        
        # Purge rétroactive
        if is_header and not in_thinking_mode:
            if len(clean_buffer) > 0 and len(clean_buffer) < 4:
                first_content = next((s for s in clean_buffer if s.strip()), "")
                if fragment_pat.match(first_content) or internal_voice_pat.search(first_content):
                    clean_buffer = [] 
            in_thinking_mode = True
            continue

        if in_thinking_mode:
            if is_internal or is_header: continue
            
            if part.strip().startswith("###") or part.strip().startswith("# "):
                in_thinking_mode = False
                clean_buffer.append(part)
            elif len(part) > 150 and not is_internal:
                in_thinking_mode = False
                clean_buffer.append(part)
            else:
                continue
        else:
            if i == 0 and has_header and (is_fragment or is_internal):
                in_thinking_mode = True
                continue
            
            clean_buffer.append(part)

    res = "".join(clean_buffer).strip()
    if res.startswith(". ") and len(res) > 2: res = res[2:]
    return res

def _is_likely_useful_text(text: str, previous_context: str = "", blacklist: Set[str] = None) -> bool:
    if not text: return False
    s = text.strip()
    if len(s) < 3: return False
    
    if blacklist and s in blacklist: return False
    if "null,null" in s or "false,false" in s: return False
        
    if len(s) > 50:
        indicators = (":", "code", "json", "data", "tableau", "suivante", "```", "[")
        expecting_data = any(previous_context.strip().endswith(ind) for ind in indicators)
        min_ratio = 0.05 if expecting_data else 0.10
        letter_count = sum(1 for c in s if c.isalpha())
        ratio = letter_count / len(s)
        if ratio < min_ratio:
            return False
            
    return True

# ============================================================================
# INTELLIGENCE N°2 : RECONSTRUCTION DE FLUX "ZIPPER" & ANTI-LOOP
# ============================================================================

def _find_header_overlap(existing: str, new_chunk: str) -> Optional[int]:
    """
    Cherche si un Header Markdown majeur (ex: '### 5.') présent dans new_chunk
    existe déjà dans existing. Retourne l'index de début dans existing si trouvé.
    C'est le signe d'une réécriture (Loop/Refinement).
    """
    # On cherche les titres de niveau 2 ou 3 (ex: ### Titre)
    # On extrait le premier header du new_chunk
    header_match = re.search(r'(?m)^(#{2,4})\s+(.*?)$', new_chunk)
    if not header_match:
        return None
    
    header_full = header_match.group(0).strip()
    # Si ce header est trop court (ex: '## '), on ignore
    if len(header_full) < 5: return None
    
    # On cherche ce header EXACT dans existing
    # On cherche en partant de la fin pour trouver l'occurrence la plus récente
    idx = existing.rfind(header_full)
    
    if idx != -1:
        # Trouvé ! C'est probablement un point de resynchronisation
        # Vérifions que c'est bien à une limite de ligne pour éviter les faux positifs
        if idx == 0 or existing[idx-1] == '\n':
            return idx
            
    return None

def _smart_merge_text(existing: str, new_chunk: str) -> str:
    """
    Fusion intelligente avec gestion de recouvrement (Zipper) ET de Refinement (Anti-Loop).
    """
    if not existing: return new_chunk
    if not new_chunk: return existing
    
    s_existing = existing.rstrip()
    s_new = new_chunk.lstrip()
    
    # 1. Overlap check Standard (Zipper)
    check_len = min(len(s_existing), len(s_new), 300)
    for k in range(check_len, 5, -1):
        suffix = s_existing[-k:]
        if s_new.startswith(suffix):
            return existing + new_chunk[len(suffix):]
            
    # 2. Structural Resync (Anti-Loop)
    # Si le zipper échoue, le modèle a peut-être réécrit une section entière.
    resync_idx = _find_header_overlap(existing, new_chunk)
    if resync_idx is not None:
        # On a détecté une boucle de structure !
        # On coupe 'existing' juste avant le header dupliqué et on colle le 'new_chunk'
        # On suppose que la nouvelle version est la "bonne" (Refinement)
        jlog("be_merge_structural_resync", header=new_chunk.split('\n')[0][:30])
        return existing[:resync_idx] + new_chunk

    # 3. Jonction Standard (Append)
    last_char = s_existing[-1] if s_existing else ""
    first_char = s_new[0] if s_new else ""
    
    if existing.count("```") % 2 != 0: return existing + new_chunk 
    
    sep = ""
    if last_char in ".!?:;" or (first_char.isupper() and len(s_new) > 1 and s_new[1].islower()):
         sep = "\n" 
    if existing.endswith("\n"): sep = ""
    
    return existing + sep + new_chunk

# ============================================================================
# INTELLIGENCE N°3 : RÉPARATION JSON SPÉCULATIVE
# ============================================================================

def _try_repair_json(s: str) -> str:
    s = s.strip()
    if s.endswith("\\"): s = s[:-1]
    if s.count('"') % 2 != 0: s += '"'
    s += ']' * (s.count('[') - s.count(']'))
    s += '}' * (s.count('{') - s.count('}'))
    return s

def _extract_string_content_speculative(raw_seg: str) -> Optional[str]:
    candidates = re.findall(r'"((?:[^"\\]|\\.)+)"', raw_seg)
    if not candidates: return None
    best_cand = max(candidates, key=len)
    if len(best_cand) > 20 and " " in best_cand:
        try: return best_cand.encode().decode('unicode_escape')
        except: return best_cand
    return None

def _json_loads_safe(s: str, allow_repair: bool = True):
    try: return _json.loads(s)
    except Exception:
        if allow_repair:
            try: return _json.loads(_try_repair_json(s))
            except Exception: pass
            spec_text = _extract_string_content_speculative(s)
            if spec_text:
                return ["wrb.fr", "unknown", [[spec_text, None, None, None]]]
        return None

# ============================================================================
# PARSING BATCHEXECUTE & HELPERS
# ============================================================================

_XSSI_PREFIX = ")]}'"
_LEN_LINE_RE = _re.compile(r'(?m)^(\d+)\n')

def _strip_xssi_prefix(body: str) -> str:
    if not body: return body
    if body.startswith(_XSSI_PREFIX):
        nl = body.find('\n')
        return body[nl+1:] if nl != -1 else ''
    return body

def _split_bex_segments(body: str) -> list[str]:
    segments = []
    i = 0
    while i < len(body):
        m = _LEN_LINE_RE.search(body, i)
        if not m: break
        try: seg_len = int(m.group(1))
        except ValueError: break 
        start = m.end()
        end = start + seg_len
        if end > len(body): break
        segments.append(body[start:end])
        i = end
    return segments

def _json_loads_multi(s: str, max_depth: int = 3):
    cur = s
    for _ in range(max_depth):
        obj = _json_loads_safe(cur)
        if isinstance(obj, (dict, list)): return obj
        if isinstance(cur, str):
            cur = cur.strip().strip('"').replace('\\"', '"').replace('\\\\n', '\n')
        else: break
    return None

def _extract_known_gemini_paths(obj) -> list[str]:
    out = []
    try:
        cands = obj.get("candidates") if isinstance(obj, dict) else None
        if isinstance(cands, list):
            for c in cands:
                parts = ((((c or {}).get("content") or {}).get("parts")) or [])
                if isinstance(parts, list):
                    for p in parts:
                        t = (p or {}).get("text")
                        if isinstance(t, str) and len(t.strip()) >= 1: out.append(t.strip())
                            
        for k in ("markdown", "text", "html", "answer"):
            v = obj.get(k) if isinstance(obj, dict) else None
            if isinstance(v, str) and len(v.strip()) >= 1: out.append(v.strip())
    except Exception: pass
    return out

# --- INTELLIGENCE V16: DEEP SCAN FOR IMAGES ---
def _deep_scan_for_images(obj: Any, found_images: List[Dict[str, Any]], seen_urls: Set[str]) -> None:
    """
    Scanner récursif pour trouver des URLs d'images générées dans les profondeurs du JSON.
    Cible: https://*.googleusercontent.com/...
    """
    try:
        if isinstance(obj, str):
            if "googleusercontent.com" in obj and obj.startswith("http"):
                # C'est une URL candidate
                if obj not in seen_urls:
                    seen_urls.add(obj)
                    found_images.append({
                        "src": obj,
                        "alt": "Network Intercepted Image",
                        "source": "batchexecute_deep_scan"
                    })
            return
        
        if isinstance(obj, list):
            for item in obj:
                _deep_scan_for_images(item, found_images, seen_urls)
            return
            
        if isinstance(obj, dict):
            # Check keys
            for k, v in obj.items():
                if k in ["image_url", "url", "src"] and isinstance(v, str):
                     if "googleusercontent.com" in v or v.startswith("http"):
                         if v not in seen_urls:
                            seen_urls.add(v)
                            found_images.append({"src": v, "alt": "Network Key Match", "source": "batchexecute_key"})
                else:
                    _deep_scan_for_images(v, found_images, seen_urls)
            return
    except Exception: pass


def _deep_collect_strings(obj, out: list[str], blacklist: Set[str] = None, *, min_len: int = 5, max_len: int = 50000):
    NEG_PAT = ('wrb.fr', 'batchexecute', 'PCck7e', 'ESY5D', 'af.httprm', 'XSRF_TOKEN', 'f.req')
    if obj is None: return
    try:
        if isinstance(obj, str):
            s = obj.strip()
            if min_len <= len(s) <= max_len:
                if not any(t in s for t in NEG_PAT):
                    if _is_likely_useful_text(s, blacklist=blacklist):
                        if s not in out: out.append(s)
            return
        if isinstance(obj, (list, tuple)):
            for it in obj: _deep_collect_strings(it, out, blacklist=blacklist, min_len=min_len, max_len=max_len)
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                _deep_collect_strings(k, out, blacklist=blacklist, min_len=min_len, max_len=max_len)
                _deep_collect_strings(v, out, blacklist=blacklist, min_len=min_len, max_len=max_len)
    except Exception: pass

def _scan_for_stop_signals(data: Any) -> bool:
    try:
        if isinstance(data, dict):
            if data.get("finishReason") in ["STOP", "MAX_TOKENS", "SAFETY"]: return True
            if data.get("isFinal") is True: return True
            for v in data.values():
                if isinstance(v, (dict, list)) and _scan_for_stop_signals(v): return True
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)) and _scan_for_stop_signals(item): return True
    except: pass
    return False

def _find_rpc_payload(data: Any, target_rpcid: Optional[str] = None) -> List[Tuple[str, str, bool]]:
    found_payloads = []
    if isinstance(data, list):
        if len(data) >= 3 and isinstance(data[0], str):
            method = data[0]
            if len(method) < 20: 
                rpcid = str(data[1]) if len(data) > 1 else "unknown"
                payload = data[2] if len(data) > 2 and isinstance(data[2], str) else None
                if payload and (payload.startswith('[') or payload.startswith('{')):
                     if target_rpcid is None or rpcid == target_rpcid:
                        found_payloads.append((rpcid, payload, False))
        for item in data: found_payloads.extend(_find_rpc_payload(item, target_rpcid))
    elif isinstance(data, dict):
        for value in data.values(): found_payloads.extend(_find_rpc_payload(value, target_rpcid))
    return found_payloads

def _try_decode_batchexecute_to_text(body: str, blacklist: Set[str] = None) -> tuple[str, dict]:
    meta = {"segments": 0, "rpcids": {}, "strings": 0, "stop_signal": False, "images": []}
    text_segments: list[str] = []
    seen_urls = set()
    
    bex = _strip_xssi_prefix(body)
    segments = _split_bex_segments(bex)
    meta["segments"] = len(segments)

    for seg in segments:
        arr = _json_loads_safe(seg, allow_repair=True)
        if not isinstance(arr, list): continue
        payloads = _find_rpc_payload(arr)
        
        for rpcid, payload_str, _ in payloads:
            meta["rpcids"][rpcid] = meta["rpcids"].get(rpcid, 0) + 1
            inner = _json_loads_multi(payload_str, max_depth=3)
            
            if inner is not None:
                if _scan_for_stop_signals(inner):
                    meta["stop_signal"] = True
                
                # INTELLIGENCE V16: Deep Image Scan on Network Layer
                _deep_scan_for_images(inner, meta["images"], seen_urls)
                
                knowns = _extract_known_gemini_paths(inner)
                for s in knowns:
                    if s not in text_segments: text_segments.append(s)
                if not knowns: _deep_collect_strings(inner, text_segments, blacklist=blacklist, min_len=5)

    meta["strings"] = len(text_segments)
    full_text = ""
    for seg in text_segments:
        if seg: full_text = _smart_merge_text(full_text, seg)
    
    full_text = _clean_syntax_artifacts(full_text)
    full_text = _clean_start_debris(full_text)
    final_clean = _strip_thinking_process(full_text.strip())
    
    return final_clean, meta

async def parse_gemini_response_intelligent_v14(
    raw_response: str,
    attempt: int = 1,
    max_attempts: int = 3,
    debug: bool = True,
    validate_gemini_signatures: bool = False,
    allow_raw_fallback: bool = True,
    blacklist: Set[str] = None
) -> Optional[Dict[str, Any]]:
    if not raw_response or not isinstance(raw_response, str): return None
    captured_text = ""
    extraction_method = "unknown"
    captured_images = []

    cand, meta = _try_decode_batchexecute_to_text(raw_response, blacklist=blacklist)
    if meta.get("images"):
        captured_images = meta["images"]

    if cand and _is_likely_useful_text(cand, blacklist=blacklist):
        captured_text = cand
        extraction_method = "bex_decoded_full"

    if (not captured_text) and allow_raw_fallback:
        candidates = re.findall(r'"([^"]{50,})"', raw_response)
        valid_cands = [c for c in candidates if _is_likely_useful_text(c, blacklist=blacklist)]
        if valid_cands:
            best_cand = max(valid_cands, key=len)
            best_cand = best_cand.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
            if _is_likely_useful_text(best_cand, blacklist=blacklist):
                captured_text = best_cand
                extraction_method = "raw_fallback_longest_valid_string"
    
    if captured_text or captured_images:
        return {
            'titre': "Réponse Gemini", 
            'description': captured_text, 
            'images': captured_images,
            '_method': extraction_method, 
            '_attempt': attempt
        }
    return None

# ===== TIMEOUT MANAGER & SIGNALING =====
_TIMEOUT_MANAGER = None
def _get_timeout_manager():
    global _TIMEOUT_MANAGER
    if _TIMEOUT_MANAGER is not None: return _TIMEOUT_MANAGER
    try:
        from timeout_manager import CrossProcessTimeoutManager
        _TIMEOUT_MANAGER = CrossProcessTimeoutManager()
        return _TIMEOUT_MANAGER
    except ImportError: return None
    except Exception: return None

def _safe_signal_activity(is_progress: bool = False, extension_s: float = 30.0):
    try:
        manager = _get_timeout_manager()
        if manager:
            manager.signal_worker_activity(is_progress=is_progress, extension_s=extension_s, reason="be_producer_signal")
            return True
        elif hasattr(manager, 'extend_on_activity'):
            manager.extend_on_activity(extension_s)
            return True
    except Exception: pass
    return False

def _calculate_stream_score(text: str) -> int:
    if not text: return 0
    score = len(text) 
    score += text.count("```") * 50  
    score += text.count("**") * 10   
    score += text.count("\n- ") * 5  
    if "http" in text and "{" in text and "}" in text: score -= 20
    return score

# ============================================================================
# INTELLIGENCE N°2 (Core) : BE PRODUCER AVEC TAMPON DE COHÉRENCE
# ============================================================================

class BEProducer:
    """BE producer : Récupère et assemble le flux textuel intelligemment."""
    def __init__(self, page: Page, on_progress: Callable[[str], None], on_done: Callable[[str, Optional[str]], None]) -> None:
        self.page = page
        self.on_progress_cb = on_progress
        self.on_done_cb = on_done
        self._resp_handler = self._on_response
        self._start_ts: Optional[float] = None
        self._agg: Dict[str, Dict[str, Any]] = {} 
        self._fallback_buffer = ""
        self._agg_window_max_s = 60.0 
        self._is_content_finalized = False
        self._finalized_text_cache = ""
        
        self._last_emitted_len = 0
        self._noise_candidates: Dict[str, int] = {}
        self._session_blacklist: Set[str] = set()
        
        self._last_flush_ts = 0.0
        self._flush_timeout_s = 2.0 

    def _agg_push(self, rpc_meta: dict, cand: str) -> str:
        now = time.monotonic()
        for rpcid in (rpc_meta or {}).keys():
            buf_info = self._agg.get(rpcid, {"start_ts": now, "last_ts": now, "buf": ""})
            if cand:
                buf_info["buf"] = _smart_merge_text(buf_info["buf"], cand)
                buf_info["last_ts"] = now
            self._agg[rpcid] = buf_info
            
        to_del = [k for k, v in self._agg.items() if now - v["start_ts"] > self._agg_window_max_s]
        for k in to_del: self._agg.pop(k, None)
        
        if not self._agg: return ""
        return max(
            self._agg.values(), 
            key=lambda v: (_calculate_stream_score(v["buf"] or ""), v["last_ts"]), 
            default={"buf": ""}
        )["buf"]

    def _fallback_agg_push(self, cand: str) -> str:
        self._fallback_buffer = _smart_merge_text(self._fallback_buffer, cand)
        return self._fallback_buffer

    async def start(self) -> None:
        if self.page.is_closed(): return
        try: 
            self.page.on("response", self._resp_handler)
            self._start_ts = time.monotonic()
            self._last_flush_ts = time.monotonic()
            jlog("be_start_ok")
        except Exception as e: jlog("be_start_error", error=str(e))

    async def stop(self) -> None:
        try:
            if not self.page.is_closed():
                 if hasattr(self.page, "remove_listener"): self.page.remove_listener("response", self._resp_handler)
                 elif hasattr(self.page, "off"): self.page.off("response", self._resp_handler)
            jlog("be_stop_ok")
        except Exception: pass

    async def _on_response(self, resp: Response) -> None:
        try:
            url = resp.url or ""
            if "google" not in url and "batchexecute" not in url: return
            
            resource_type = resp.request.resource_type
            if resource_type in ("image", "stylesheet", "font", "media"): return
            if not (200 <= resp.status < 300): return

            _safe_signal_activity(is_progress=False, extension_s=60.0)

            try: body = await asyncio.wait_for(resp.text(), timeout=120.0)
            except (asyncio.TimeoutError, Exception): return
                
            if not body or len(body) < 10: return
            
            if len(body) < 50:
                snippet = body.strip()
                self._noise_candidates[snippet] = self._noise_candidates.get(snippet, 0) + 1
                if self._noise_candidates[snippet] > 5:
                    self._session_blacklist.add(snippet)
            
            cand, meta = _try_decode_batchexecute_to_text(body, blacklist=self._session_blacklist)
            
            should_force_flush = False
            if meta.get("stop_signal"):
                jlog("be_predictive_stop_signal_received")
                should_force_flush = True
            
            # Capture Images from Network (Deep Scan)
            found_images = meta.get("images", [])
            
            final_text = ""
            if meta.get("rpcids") and cand:
                final_text = self._agg_push(meta.get("rpcids"), cand)
            else:
                body_filtered = cand if len(cand) > 10 else body
                parsed_data = await parse_gemini_response_intelligent_v14(
                    body_filtered, allow_raw_fallback=True, blacklist=self._session_blacklist
                )
                if parsed_data:
                    if parsed_data.get('description'):
                        final_text = self._fallback_agg_push(parsed_data['description'])
                    if parsed_data.get('images'):
                        found_images.extend(parsed_data['images'])

            if final_text or found_images:
                if not self._is_content_finalized:
                    tail = final_text[-300:]
                    end_markers = ["Sources", "Afficher les suggestions", "thumb_up", "thumb_down", "Recherches associées"]
                    
                    if any(m in tail for m in end_markers):
                        self._is_content_finalized = True
                        clean_text = final_text
                        for m in end_markers:
                            if m in clean_text: clean_text = clean_text.split(m)[0]
                        self._finalized_text_cache = clean_text.strip()
                        final_text = self._finalized_text_cache
                else:
                    if len(final_text) > len(self._finalized_text_cache) * 1.3:
                         self._is_content_finalized = False 
                         self._finalized_text_cache = ""
                         self._last_emitted_len = 0 
                
                delta = final_text[self._last_emitted_len:]
                
                # Check flush condition
                now = time.monotonic()
                can_flush = False
                
                if delta.strip() and delta.strip()[-1] in ".!?:;\n": can_flush = True
                elif (now - self._last_flush_ts) > self._flush_timeout_s: can_flush = True
                elif "```" in delta: can_flush = True
                elif should_force_flush: can_flush = True
                elif found_images: can_flush = True # Flush immediately if images found

                if can_flush and (delta or found_images):
                    payload = {
                        "text": delta,
                        "images": found_images,
                        "meta": {"source": "be_producer"}
                    }
                    self.on_progress_cb(payload)
                    
                    self._last_emitted_len = len(final_text)
                    self._last_flush_ts = now
                    _safe_signal_activity(is_progress=True, extension_s=60.0)
                    jlog("be_update_sent", len=len(delta), images=len(found_images))

        except Exception as e:
             if not self.page.is_closed():
                  jlog("be_on_response_error", error=str(e))