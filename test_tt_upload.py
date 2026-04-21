#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test standalone upload TikTok — publication réelle.
Flux correct CDP :
  1. Page.setInterceptFileChooserDialog(enabled=true)
  2. Click trigger (G0) → ouvre dialog natif
  3. Page.fileChooserOpened event → Page.handleFileChooser(accept, files)
  4. TikTok React reçoit le fichier comme un vrai utilisateur → upload réel
  5. Attente form description + injection caption
  6. Click Post
"""
import sys
import os
import json
import time
import threading
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

VIDEO_PATH = ROOT / "workspace" / "nexus_final_20260420_203111_602251_0266dd_V38_MASTER.mp4"
DESCRIPTION = "Ma stratégie SMC expliquée 🎯\n\nJe t'explique comment j'analyse le marché chaque matin.\n\n#trading #smc #propfirm #stratégie #forex"
PORT = 9222

# JS : détection form description RÉELLE (exclu nav/sidebar)
JS_FORM_READY = r"""
(function() {
  const postBtn = [...document.querySelectorAll('button')]
    .find(b => /^(post|publier)$/i.test((b.innerText||b.textContent||'').trim())
           && !b.closest('nav') && !b.closest('[class*="SideNav"]') && !b.closest('[class*="sidebar"]'));

  const capEl = document.querySelector('[data-e2e*="caption"] div[contenteditable]')
             || document.querySelector('[data-e2e*="description"] div[contenteditable]');

  let genericEl = null;
  if (!capEl) {
    genericEl = [...document.querySelectorAll('div[contenteditable]')]
      .find(el => {
        const ph = (el.getAttribute('placeholder') || el.dataset.placeholder || '').toLowerCase();
        return /tell us|dites.nous|caption|description|hashtag/i.test(ph);
      });
  }

  const captionEl = capEl || genericEl;
  return {
    ready: !!(postBtn && captionEl),
    has_post_btn: !!postBtn,
    has_caption: !!captionEl,
    caption_len: captionEl ? (captionEl.innerText || '').length : -1,
    post_btn_text: postBtn ? (postBtn.innerText || '').trim().slice(0, 20) : null,
    post_btn_disabled: postBtn ? !!(postBtn.disabled || postBtn.getAttribute('aria-disabled')==='true') : null,
  };
})()
"""

JS_DIAG = r"""
(function() {
  function vis(n){ if(!n) return false; const s=getComputedStyle(n); return s.display!=='none'&&s.visibility!=='hidden'&&n.offsetParent!==null;}
  function text(n){return (n&&(n.innerText||n.textContent)||'').trim();}
  const btns = [...document.querySelectorAll('button')].filter(vis).map(b => ({
    t: text(b).slice(0, 25),
    dis: !!(b.disabled || b.getAttribute('aria-disabled')==='true'),
    nav: !!b.closest('nav'),
    pe: getComputedStyle(b).pointerEvents,
    op: getComputedStyle(b).opacity,
  }));
  const cap = document.querySelector('[data-e2e*="caption"] div[contenteditable]')
           || document.querySelector('div[contenteditable]');
  const prog = document.querySelector('progress, [role="progressbar"]');
  return {
    btns: btns.slice(0, 8),
    caption_len: cap ? (cap.innerText||'').length : -1,
    has_progress: !!prog,
    prog_val: prog ? prog.value : null,
    prog_max: prog ? prog.max : null,
    url: location.href.slice(-60),
  };
})()
"""

def step(msg):
    print(f"\n{'='*60}\n[STEP] {msg}\n{'='*60}")

def main():
    step("Vérification fichier vidéo")
    if not VIDEO_PATH.exists():
        print(f"ERREUR: {VIDEO_PATH} introuvable")
        sys.exit(1)
    size_mb = VIDEO_PATH.stat().st_size / 1_048_576
    print(f"OK — {VIDEO_PATH.name} ({size_mb:.1f} Mo)")

    step("Import modules")
    from tt_utils import jlog, _preflight_resolve_path
    from tt_cdp import CdpClient, list_targets, pick_tiktok_target
    from tt_runner import UploadRunner
    from tt_dom import _make_neutral_upload_copy
    from tt_constants import (
        NEUTRALIZE_FILENAME_FOR_PREFILL, JS_CLICK_TRIGGER,
        JS_CLICK_POST, JS_CLICK_CONFIRM_POST, JS_SNAPSHOT_POST,
    )
    from tt_uploader import _get_fuzzy_finder_js
    print("OK")

    step(f"Connexion CDP port {PORT}")
    targets = list_targets(PORT)
    print(f"Targets: {len(targets)}")
    tgt = pick_tiktok_target(targets, url_substr="tiktok.com")
    if not tgt:
        print("ERREUR: aucun onglet tiktok.com sur port 9222")
        sys.exit(1)
    print(f"Onglet: {tgt.get('url','?')[:80]}")

    step("Ouverture WebSocket CDP")
    cd = CdpClient(tgt.get("webSocketDebuggerUrl"))
    cd.connect()
    print("OK")

    try:
        step("Navigation + reload page upload")
        cd.eval("window.location.href = 'https://www.tiktok.com/tiktokstudio/upload'", timeout=5.0)
        deadline = time.time() + 25
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                count = cd.eval("document.querySelectorAll('input[type=\"file\"]').length", timeout=3.0)
                if count and int(count) > 0:
                    print(f"  Page prête (input[file] count={count})")
                    break
            except Exception:
                pass
        else:
            print("  WARN: timeout — on continue")

        step("Résolution chemin")
        ok_path, resolved = _preflight_resolve_path(VIDEO_PATH)
        if not ok_path:
            print("ERREUR: chemin invalide")
            sys.exit(1)

        upload_path_obj = resolved
        if NEUTRALIZE_FILENAME_FOR_PREFILL:
            try:
                upload_path_str, _tmp_dir = _make_neutral_upload_copy(resolved)
                upload_path_obj = Path(upload_path_str)
                print(f"Copie neutre: {upload_path_obj.name}")
            except Exception as e:
                print(f"Copie neutre échouée ({e}), original utilisé")

        step("G0+G1 — Interception FileChooser + Click trigger")
        runner = UploadRunner(cd)
        runner.enable_domains()

        # Activer l'interception du file chooser dialog natif
        try:
            cd.send("Page.enable", {}, timeout=5)
        except Exception:
            pass

        file_chooser_event = threading.Event()
        chooser_backend_node_id = [None]

        def handle_cdp_event(method, params):
            if method == "Page.fileChooserOpened":
                chooser_backend_node_id[0] = params.get("backendNodeId")
                print(f"\n  [EVENT] Page.fileChooserOpened backendNodeId={chooser_backend_node_id[0]}")
                file_chooser_event.set()

        cd.on_event(handle_cdp_event)

        # Activer interception avant le clic
        try:
            res = cd.send("Page.setInterceptFileChooserDialog", {"enabled": True}, timeout=5)
            print(f"  setInterceptFileChooserDialog: {res}")
        except Exception as e:
            print(f"  WARN: setInterceptFileChooserDialog échoué ({e})")

        # Cliquer l'input[type=file] directement avec userGesture:true
        JS_CLICK_FILE_INPUT = r"""
        (function() {
            const input = document.querySelector('input[type="file"]');
            if (input) { input.click(); return {clicked: 'input_direct'}; }
            return {clicked: false, reason: 'no_input_found'};
        })()
        """
        trigger_res = cd.send("Runtime.evaluate", {
            "expression": JS_CLICK_FILE_INPUT,
            "returnByValue": True,
            "userGesture": True,
            "awaitPromise": False,
        }, timeout=5) or {}
        val = (trigger_res.get("result") or {}).get("value", trigger_res)
        print(f"  Trigger clic (userGesture=true): {val}")

        # Attendre l'événement fileChooserOpened (max 8s)
        got_chooser = file_chooser_event.wait(timeout=8.0)

        if got_chooser and chooser_backend_node_id[0]:
            print(f"  ✅ File chooser intercepté — DOM.setFileInputFiles avec backendNodeId={chooser_backend_node_id[0]}")
            try:
                # Utiliser backendNodeId (pas nodeId) — c'est l'API correcte quand file chooser est intercepté
                set_res = cd.send("DOM.setFileInputFiles", {
                    "files": [str(upload_path_obj)],
                    "backendNodeId": chooser_backend_node_id[0],
                }, timeout=15)
                print(f"  DOM.setFileInputFiles (backendNodeId): {set_res}")
            except Exception as e:
                print(f"  ERREUR DOM.setFileInputFiles backendNodeId: {e}")
                sys.exit(1)
        else:
            print(f"  WARN: file chooser pas intercepté en 8s — fallback DOM.setFileInputFiles nodeId")
            if not runner.set_file(upload_path_obj, dragdrop_timeout_s=25.0):
                print("ERREUR: set_file fallback échoué")
                sys.exit(1)

        step("G2 — Attente VRAIE form description (max 240s)")
        deadline_form = time.time() + 240
        form_ready = False
        last_diag = 0
        while time.time() < deadline_form:
            try:
                fstate = runner.eval(JS_FORM_READY, True) or {}
                elapsed = int(time.time() - (deadline_form - 240))
                if time.time() - last_diag >= 10:
                    diag = runner.eval(JS_DIAG, True) or {}
                    btns_short = [(b['t'], '✗' if b['dis'] else '✓', 'nav' if b['nav'] else '') for b in (diag.get('btns') or [])[:6]]
                    print(f"  [{elapsed}s] form={fstate.get('ready')} cap_len={fstate.get('caption_len')} post='{fstate.get('post_btn_text')}' | btns={btns_short} | prog={diag.get('has_progress')}")
                    last_diag = time.time()
                if fstate.get("ready"):
                    print(f"  ✅ Form prête ! post_btn_text='{fstate.get('post_btn_text')}' caption_len={fstate.get('caption_len')}")
                    form_ready = True
                    break
            except Exception as e:
                print(f"  [form poll error] {e}")
            time.sleep(2.0)

        if not form_ready:
            print("ERREUR: form description jamais apparue en 240s")
            sys.exit(1)

        time.sleep(1.5)

        step("G3 — Injection description")
        fuzzy_js = _get_fuzzy_finder_js(DESCRIPTION)
        fuzzy_res = runner.eval(fuzzy_js) or {}
        if fuzzy_res.get("found"):
            print(f"OK — description injectée (score: {fuzzy_res.get('score')})")
        else:
            print(f"Fuzzy échoué ({fuzzy_res}), fallback execCommand...")
            fallback_js = """
            (function() {
                const el = document.querySelector('[data-e2e*="caption" i] div[contenteditable="true"]')
                       || document.querySelector('div[contenteditable="true"]');
                if (!el) return {ok: false, reason: 'no_element'};
                el.focus();
                el.innerText = '';
                document.execCommand('insertText', false, %s);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                return {ok: true, len: el.innerText.length};
            })()
            """ % json.dumps(DESCRIPTION)
            res = runner.eval(fallback_js)
            print(f"Fallback résultat: {res}")

        time.sleep(1.0)

        step("G4 — Attente bouton Post ACTIF (max 600s)")
        deadline_post = time.time() + 600
        post_ready = False
        last_diag2 = 0
        while time.time() < deadline_post:
            try:
                snap = runner.eval(JS_SNAPSHOT_POST, True) or {}
                elapsed = int(time.time() - (deadline_post - 600))
                if time.time() - last_diag2 >= 15:
                    diag = runner.eval(JS_DIAG, True) or {}
                    print(f"  [{elapsed}s] snap={snap} | cap_len={diag.get('caption_len')} | prog={diag.get('has_progress')} val={diag.get('prog_val')}/{diag.get('prog_max')}")
                    last_diag2 = time.time()
                is_enabled = snap.get("present") and snap.get("visible") and not snap.get("disabled")
                if is_enabled:
                    print(f"  ✅ Bouton Post ACTIF — snap={snap}")
                    post_ready = True
                    break
            except Exception as e:
                print(f"  [post poll error] {e}")
            time.sleep(2.0)

        if not post_ready:
            print("ERREUR: bouton Post jamais activé en 600s")
            sys.exit(1)

        step("G5 — Clic Post (publication réelle)")
        ok = True
        try:
            res = runner.eval(JS_CLICK_POST, True) or {}
            if not res.get("clicked"):
                ok = False
                print(f"WARN: JS_CLICK_POST retour={res}")
            else:
                print(f"  Clic Post: {res}")
        except Exception as e:
            print(f"ERREUR clic Post: {e}")
            ok = False

        time.sleep(1.5)

        try:
            confirm_res = runner.eval(JS_CLICK_CONFIRM_POST, True) or {}
            if confirm_res.get("modal_found"):
                print(f"  Modale confirmation: clicked={confirm_res.get('clicked')}")
        except Exception as e:
            print(f"  Modale (non bloquant): {e}")

        if ok:
            print("\n" + "=" * 60)
            print("✅ PUBLICATION RÉELLE ENVOYÉE")
            print("   Vérifie TikTok Studio pour confirmer.")
            print("=" * 60)
        else:
            print("❌ Clic Post échoué")
            sys.exit(1)

    finally:
        cd.close()
        print("\nWebSocket fermé.")

if __name__ == "__main__":
    main()
