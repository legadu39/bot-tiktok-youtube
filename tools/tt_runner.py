### tools/tt_runner.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TikTok Uploader — Classes de processus (Runner / Guard).
Contient les classes de haut niveau qui gèrent l'état et
le flux de l'upload et de la publication.
"""

# Imports natifs
import json
import random
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

# Imports du projet
from tt_cdp import CdpClient
from tt_utils import jlog, POST_SETFILE_DISPATCH

# Imports des modules refactorisés
import tt_dom
from tt_constants import *

if TYPE_CHECKING:
    import tt_runner


# -------------------------
# Runner (upload)
# -------------------------

class UploadRunner:
    def __init__(self, client: CdpClient):
        self.cd = client
        self._upload_active = 0
        self._upload_started = False
        self._exit_last_ts = 0.0
        self._cta_last_ts = 0.0
        self.cd.on_event(self._on_event)
        self._last_net_error = None
        
        # INTELLIGENCE V3: Fichier de persistance pour la stratégie d'upload
        self.strategy_cache_file = Path("upload_strategy_cache.json")

    def eval(self, expression: str, returnByValue: bool = True, timeout: float = 6.0):
        return self.cd.eval(expression, timeout=timeout, returnByValue=returnByValue)

    def _on_event(self, method, params):
        if method == "Network.requestWillBeSent":
            req = params.get("request", {})
            if req.get("method") == "POST":
                headers = {k.lower(): v for k, v in (req.get("headers", {}) or {}).items()}
                ct = headers.get("content-type", "").lower()
                url = (req.get("url") or "")
                if ("multipart/form-data" in ct) and re.search(r"/upload.*video|/video.*upload", url, re.I):
                    self._upload_started = True
                    self._upload_active += 1
                    jlog("upload_chunk_start", stage="upload", upload_state={"active": self._upload_active}, action="chunk_start", decision_reason="multipart+video")
        elif method == "Network.loadingFinished":
            if self._upload_started and self._upload_active > 0:
                self._upload_active -= 1
                jlog("upload_chunk_finish", stage="upload", upload_state={"active": self._upload_active}, action="chunk_finish")
        
        elif method == "Network.loadingFailed":
            if self._upload_started and self._upload_active > 0:
                self._upload_active -= 1
            
            error_text = params.get("errorText", "")
            
            if "ERR_ABORTED" in error_text:
                jlog("net_error_aborted", stage="net",
                     decision_reason=error_text,
                     action="Network.loadingFailed",
                     suggestion="Retry exponential recommended")
                self._last_net_error = "ERR_ABORTTE"
                
            elif "ERR_CONNECTION" in error_text:
                jlog("net_error_connection", stage="net",
                     decision_reason=error_text,
                     suggestion="Check network stability")
                
            elif "ERR_NETWORK_CHANGED" in error_text:
                jlog("net_error_network_changed", stage="net",
                     decision_reason=error_text,
                     suggestion="Retry with backoff")
                
            else:
                jlog("net_noise", stage="net",
                     decision_reason=error_text,
                     action=method)

    def enable_domains(self):
        for m in ("Page.enable", "Runtime.enable", "Network.enable"):
            try:
                self.cd.send(m, {}, timeout=6)
            except Exception:
                pass
        try:
            self.cd.send("DOM.enable", {}, timeout=6)
        except Exception:
            pass

    def _eval(self, expression: str, returnByValue: bool = True, timeout: float = 6.0):
        return self.cd.eval(expression, timeout=timeout, returnByValue=returnByValue)

    def _dismiss_exit_modal(self, backoff=2.0):
        now = time.monotonic()
        if now - self._exit_last_ts < backoff:
            return False
        try:
            res = self._eval(JS_EXIT_MODAL_DISMISS, True) or {}
            if res.get("dismissed"):
                self._exit_last_ts = now
                jlog("exit_modal_dismissed", stage="ui", action="dismiss")
                return True
        except Exception:
            pass
        return False

    def current_url(self) -> str:
        try:
            return str(self._eval("location.href", True) or "")
        except Exception:
            return ""

    def page_upload_ready(self):
        snap = self._eval(JS_PAGE_UPLOAD_READY, True) or {}
        return bool(snap.get("ready")), snap

    def _detect_cta(self):
        info = self._eval(JS_DETECT_CTA, True) or {}
        if info.get("cta"):
            jlog("g0_cta_detected", stage="g0", gate="G0", ui_state=info)
            return True
        return False

    def _maybe_click_cta(self, backoff_s=2.0):
        now = time.monotonic()
        if now - self._cta_last_ts < backoff_s:
            return False
        res = self._eval(JS_CLICK_TRIGGER, True) or {}
        if res.get("clicked"):
            self._cta_last_ts = now
            jlog("g0_trigger_clicked", stage="g0", action="click_trigger", ui_state=res)
            return True
        return False

    def wait_upload_gate(self, timeout_s=15.0):
        t0 = time.monotonic()
        last = {}
        while (time.monotonic() - t0) < timeout_s:
            ok, snap = self.page_upload_ready()
            last = snap or {}
            if ok:
                jlog("page_upload_ready", stage="g0", gate="G0", outcome="success", ui_state=snap)
                return True
            if self._detect_cta():
                self._maybe_click_cta()
            time.sleep(0.5)
        jlog("page_upload_not_ready", stage="g0", gate="G0", outcome="timeout", ui_state=last, error_signature="g0_timeout")
        return False

    def navigate_to(self, url: str, wait_s=12.0):
        try:
            self.cd.send("Page.navigate", {"url": url}, timeout=6)
        except Exception as e:
            jlog("navigate_error", stage="g0", error_signature="navigate_error", decision_reason=str(e))
            return False
        return self.wait_upload_gate(timeout_s=wait_s)

    def _collect_frame_ids(self):
        frames = []
        try:
            ft = self.cd.send("Page.getFrameTree", {}) or {}
            def walk(node):
                if not node:
                    return
                f = node.get("frame", {})
                fid = f.get("id")
                if fid:
                    frames.append(fid)
                for c in (node.get("childFrames") or []):
                    walk(c)
            walk(ft.get("frameTree"))
        except Exception:
            pass
        return frames or [None]

    def _find_file_input_node(self):
        """
        VERSION DIAMOND (CRITICAL MODE ++):
        Implémente une 'Attente Heuristique Progressive' pour détecter l'input file.
        INTELLIGENCE V3: Utilise le cache Darwinien pour tester le dernier sélecteur gagnant.
        """
        # 1. Scan initial rapide
        info = self._eval(JS_FIND_INPUTS, True) or {}
        jlog("inputs_scan", stage="g0", ui_state={"inputs_count": info.get("count", 0), "inputs_visible": info.get("visible", 0)})

        # Liste de sélecteurs par ordre de priorité standard
        base_selectors = [
            'input[type="file"][accept*="video"]',
            'input[type="file"][accept*="mp4"]',
            'input[type="file"]'
        ]

        # Priorisation Darwinienne: On met le gagnant précédent en tête
        winner = tt_dom.DomDarwinCache.get_winner("file_input")
        if winner and winner in base_selectors:
            base_selectors.remove(winner)
            base_selectors.insert(0, winner)
        elif winner:
            base_selectors.insert(0, winner)

        def _scan_frames():
            # Tentative rapide sur la racine
            try:
                doc = self.cd.send("DOM.getDocument", {"depth": -1, "pierce": True}, timeout=1.0)
                root_id = doc["result"]["root"]["nodeId"] if "result" in doc else doc["root"]["nodeId"]
                for selector in base_selectors:
                    try:
                        q = self.cd.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
                        nid = q.get("result", {}).get("nodeId")
                        if nid: 
                            # Si on trouve, on valide ce sélecteur pour la prochaine fois
                            tt_dom.DomDarwinCache.save_winner("file_input", selector)
                            return nid
                    except Exception: continue
            except Exception: pass

            # Scan complet récursif
            frame_ids = self._collect_frame_ids()
            for fid in frame_ids:
                try:
                    doc = self.cd.send("DOM.getDocument", {"depth": -1, "pierce": True, **({"frameId": fid} if fid else {})}, timeout=1.5)
                    if "result" in doc: doc = doc["result"]
                    if "root" not in doc: continue
                    root_id = doc["root"]["nodeId"]
                    for selector in base_selectors:
                        try:
                            q = self.cd.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
                            nid = q.get("result", {}).get("nodeId")
                            if nid: 
                                tt_dom.DomDarwinCache.save_winner("file_input", selector)
                                return nid
                        except Exception: continue
                except Exception: continue
            return None

        # Tentative 1 : Scan immédiat (si la page est déjà prête)
        nid = _scan_frames()
        if nid: return nid

        # Tentative 2 : Clic Trigger + Polling Actif (Le Correctif)
        try:
            if self._maybe_click_cta():
                jlog("g0_cta_clicked_wait_input", stage="g0", action="wait_animation_polling")
                
                # BOUCLE DE POLLING (3.5s max)
                t_start = time.time()
                while time.time() - t_start < 3.5:
                    time.sleep(0.4) 
                    nid = _scan_frames()
                    if nid:
                        jlog("input_found_delayed", stage="g0", delay=round(time.time()-t_start, 2))
                        return nid
        except Exception as e:
            jlog("find_input_error", stage="g0", error=str(e))

        return None

    # --- INTELLIGENCE V3: STRATEGY CACHE METHODS ---

    def _load_strategy(self) -> str:
        """Lit la dernière stratégie gagnante."""
        try:
            if self.strategy_cache_file.exists():
                with open(self.strategy_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("preferred_method", "input")
        except Exception:
            pass
        return "input"

    def _save_strategy(self, method: str):
        """Enregistre la stratégie gagnante pour le futur."""
        try:
            with open(self.strategy_cache_file, "w", encoding="utf-8") as f:
                json.dump({"preferred_method": method, "last_updated": time.time()}, f)
        except Exception:
            pass

    # ------------------------------------------------

    def set_file(self, filepath: Path, dragdrop_timeout_s: float = 20.0) -> bool:
        """
        Stratégie multi-niveau intelligente & adaptative (Intelligence N°4):
        1. Consulte le cache pour savoir quelle méthode a marché la dernière fois.
        2. Essaie la méthode favorite en premier.
        3. Fallback sur les autres méthodes si échec.
        4. Met à jour le cache en cas de succès.
        """
        
        preferred = self._load_strategy()
        jlog("upload_strategy_init", preferred_method=preferred)

        # -- DEFINITION DES WORKERS --
        
        def attempt_input_node() -> bool:
            nid = self._find_file_input_node()
            if nid:
                try:
                    self.cd.send("DOM.setFileInputFiles", 
                                {"files": [str(filepath)], "nodeId": nid},
                                timeout=20)
                    jlog("file_set", stage="g1", action="setFileInputFiles", ui_state={"file": str(filepath)})
                    if POST_SETFILE_DISPATCH:
                        time.sleep(1.0)
                        res = self._eval(JS_DISPATCH_FILE_CHANGE_ROBUST, True) or {}
                        jlog("post_setfile_dispatch", stage="g1", action="dispatch_change_robust", ui_state=res)
                    return True
                except Exception as e:
                    jlog("warning", stage="g1", error=f"input_node_failed: {e}")
            return False

        def attempt_dragdrop() -> bool:
            if tt_dom.upload_via_dragdrop_intelligent(self.cd, filepath, timeout_s=dragdrop_timeout_s):
                jlog("g1_fallback_success", stage="g1", strategy="dragdrop")
                return True
            return False

        # -- ORCHESTRATION DYNAMIQUE --

        methods = []
        if preferred == "dragdrop":
            methods = [("dragdrop", attempt_dragdrop), ("input", attempt_input_node)]
        else:
            methods = [("input", attempt_input_node), ("dragdrop", attempt_dragdrop)]

        # Exécution principale
        for name, func in methods:
            jlog("upload_attempt", method=name)
            if func():
                self._save_strategy(name) # Récompense l'apprentissage
                return True

        # -- ULTIMATE FALLBACK : FORCE INJECT --
        
        jlog("g1_fallback_attempt_force", stage="g1", strategy="force_inject")
        inject_script = """
        (function() {
            let input = document.querySelector('[data-forced-file-input]');
            if (input) input.remove();
            
            input = document.createElement('input');
            input.type = 'file';
            input.accept = 'video/*';
            input.setAttribute('data-forced-file-input', 'true');
            input.style.display = 'none';
            
            document.body.appendChild(input);
            return { injected: true };
        })();
        """
        
        try:
            resp = self.cd.send("Runtime.evaluate", {
                "expression": inject_script,
                "returnByValue": True
            }, timeout=5)
            
            if resp.get("result", {}).get("result", {}).get("value", {}).get("injected"):
                jlog("g1_force_inject_success", stage="g1")
                time.sleep(1.0)
                
                if tt_dom.upload_via_dragdrop_intelligent(self.cd, filepath, timeout_s=dragdrop_timeout_s):
                    # On ne sauvegarde PAS force_inject comme favori, c'est une mesure d'urgence
                    return True
        
        except Exception as e:
            jlog("g1_force_inject_error", stage="g1", error=str(e))
        
        jlog("g1_all_fallbacks_failed", stage="g1", error_signature="no_upload_method_found")
        return False

    def wait_upload_ack(self, timeout_s: float = 40.0, retry_backoff: bool = True) -> bool:
        t0 = time.monotonic()
        sleep_delay = 0.5
        
        while (time.monotonic() - t0) < timeout_s:
            if self._upload_active == 0 and self._upload_started:
                jlog("upload_ack_received", stage="g2", gate="G2", outcome="success", upload_state={"active": 0})
                return True
            
            try:
                snap = self._eval(JS_UPLOAD_SIGNS, True) or {}
                
                if snap.get("uploaded") or snap.get("replace"):
                    jlog("upload_signs_detected", stage="g2", ui_state=snap)
                    return True
                    
            except Exception:
                pass
            
            if retry_backoff:
                time.sleep(sleep_delay)
                sleep_delay = min(sleep_delay * 1.5, 3.0)
            else:
                time.sleep(0.5)
        
        jlog("upload_ack_timeout", stage="g2", gate="G2", outcome="timeout", error_signature="upload_ack_timeout", ui_state={"last_net_error": self._last_net_error})
        return False

class LightPostGuard:
    def __init__(self, runner: 'UploadRunner', nudge_after=10.0, max_wait_post=90.0, dry_run=False):
        self.runner = runner
        self.cd = runner.cd
        self.nudge_after = float(nudge_after)
        self.max_wait_post = float(max_wait_post)
        self.dry_run = bool(dry_run)
        self._g4_enter = None

    def _eval(self, js, returnByValue: bool = True, timeout: float = 6.0):
        return self.runner.eval(js, timeout=timeout, returnByValue=returnByValue)

    def wait_for_post_button(self):
        self._g4_enter = time.monotonic()
        jlog("gate", stage="g4", gate="G4_POST_WATCH_START", outcome="enter")

        while (time.monotonic() - self._g4_enter) < self.max_wait_post:
            try:
                snap = self._eval(JS_SNAPSHOT_POST, True) or {}
            except Exception:
                snap = {}
            post_state = snap or {}

            is_enabled = (post_state.get("present") and post_state.get("visible") and not bool(post_state.get("disabled")))

            if is_enabled:
                jlog("gate", stage="g4", gate="G4_POST_ENABLED", outcome="success", ui_state=post_state)
                time.sleep(0.5)
                return True

            time.sleep(1.0 + random.random() * 0.3)

        jlog("stop_rule_SR_POST_DEAD", stage="g6", gate="SR_POST_DEAD", outcome="draft_fallback", error_signature="post_button_not_enabled_in_time")
        try:
            self._eval(r"""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/(save\s*draft|brouillon)/i.test((x.innerText||x.textContent||''))); if(b){b.click(); return {clicked:true};} return {clicked:false};})()""", True)
        except Exception:
            pass
            
        try:
            self._eval("(function(){ try{ if(window.__ttCaptionGuard) __ttCaptionGuard.disconnect(); }catch(_){}})()", True, 1.5)
            jlog("g6_guard_stop_timeout", stage="g6", action="stop_long_guard_timeout")
        except Exception as e:
            jlog("g6_guard_stop_failed", stage="g6", error=str(e))
            
        return False