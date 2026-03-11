#!/usr/bin/env python3
# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/tt_uploader.py

"""
TikTok Uploader V4 — Module Intelligent (Fuzzy Logic & Resilience)
Intègre le scoring heuristique pour trouver les éléments DOM même après mise à jour TikTok.
"""

import sys
import os
import argparse
import json
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict

# --- CORRECTIF PATH CRITIQUE (Guerison ModuleNotFoundError) ---
# Ajoute le dossier courant 'tools' au sys.path pour permettre les imports entre voisins
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# --- PATCH DIAMOND: VACCINATION UNICODE ---
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# --- IMPORTS ROBUSTES (Grace au correctif Path) ---
try:
    from tt_utils import (
        jlog, RUN_ID, ABS_PATH_ENFORCE,
        iter_candidate_files, mark_file_done, _preflight_resolve_path,
    )
    from tt_cdp import CdpClient, list_targets, pick_tiktok_target
    from tt_runner import UploadRunner, LightPostGuard
    from tt_dom import (
        _make_neutral_upload_copy,
        find_and_click_next_button,
        validate_redirect_to_description_page,
        capture_page_state_hash,
        set_description_robust,
        revalidate_caption_before_post,
        guard_mutation_js,
    )
    from tt_constants import (
        NEUTRALIZE_FILENAME_FOR_PREFILL,
        JS_UPLOAD_SIGNS,
        JS_SNAPSHOT_POST,
        JS_CLICK_POST,
        JS_CLICK_CONFIRM_POST,
    )
except ImportError as e:
    # Diagnostic d'urgence si ça échoue encore
    print(f"CRITICAL IMPORT ERROR in tt_uploader: {e}")
    # On tente les imports relatifs au cas où (fallback context root)
    try:
        from tools.tt_utils import jlog, _preflight_resolve_path
        from tools.tt_cdp import CdpClient
        from tools.tt_runner import UploadRunner
    except ImportError:
        raise e

# -----------------------------------------------------------------------------
# INTELLIGENCE V4: FUZZY SELECTOR LOGIC
# -----------------------------------------------------------------------------

def _get_fuzzy_finder_js(text_to_insert: str) -> str:
    """
    Génère un script JS qui scanne le DOM et note les éléments pour trouver
    le meilleur candidat 'Description', au lieu de dépendre d'un sélecteur fixe.
    """
    escaped_text = json.dumps(text_to_insert)
    return r"""
    (function() {
        const candidates = document.querySelectorAll('div[contenteditable="true"], textarea, input[type="text"]');
        let bestEl = null;
        let maxScore = 0;
        
        candidates.forEach(el => {
            let score = 0;
            const html = el.outerHTML.toLowerCase();
            const placeholder = (el.getAttribute('placeholder') || "").toLowerCase();
            const dataE2E = (el.getAttribute('data-e2e') || "").toLowerCase();
            const ariaLabel = (el.getAttribute('aria-label') || "").toLowerCase();
            
            // Heuristiques positives
            if (dataE2E.includes('caption') || dataE2E.includes('description')) score += 50;
            if (html.includes('mention') || html.includes('hashtag')) score += 20;
            if (placeholder.includes('tell us') || placeholder.includes('dites-nous')) score += 30;
            if (el.tagName === 'DIV') score += 15; // TikTok préfère les DIVs
            
            // Heuristiques négatives (champs titre ou search)
            if (placeholder.includes('title') || placeholder.includes('titre')) score -= 50;
            if (dataE2E.includes('search')) score -= 100;

            if (score > maxScore) {
                maxScore = score;
                bestEl = el;
            }
        });

        if (bestEl && maxScore > 20) {
            // Action sur le gagnant
            bestEl.focus();
            
            // Nettoyage si texte existant (ex: nom de fichier)
            if(bestEl.innerText.length < 50) bestEl.innerText = "";
            
            // Injection safe
            const text = %s;
            document.execCommand('insertText', false, text);
            bestEl.dispatchEvent(new Event('input', {bubbles: true}));
            
            return { found: true, score: maxScore, tag: bestEl.tagName };
        }
        return { found: false, best_score: maxScore };
    })();
    """ % escaped_text

# -----------------------------------------------------------------------------
# CORE LOGIC : Single File Processing
# -----------------------------------------------------------------------------

def ensure_studio_context(cd: CdpClient):
    """Garantit que le navigateur est sur la page d'upload Studio."""
    nav_script = r"""
    (() => {
      const studioUrl = "https://www.tiktok.com/tiktokstudio/upload";
      try {
        const here = window.location.href || "";
        if (here.startsWith(studioUrl)) return "already_on_studio";
        window.location.href = studioUrl;
        return "navigating_to_studio";
      } catch (e) {
        return "nav_error:" + String(e);
      }
    })()
    """
    try:
        res = cd.eval(nav_script, timeout=5.0)
        if res == "navigating_to_studio":
            time.sleep(2.0)
        else:
            time.sleep(1.0)
    except Exception:
        pass

def run_one_file(
    cd: CdpClient,
    file_path: Path,
    and_guard: bool,
    ack_timeout: float,
    nudge_after: float,
    max_wait_post: float,
    dry_run: bool,
    title: Optional[str],
    description: Optional[str],
    safe_post: bool = False,
    dragdrop_timeout_s: float = 20.0,
) -> bool:
    
    # 1. Préparation Environnement & Reset
    jlog("state_reset", stage="init", action="force_nav_to_upload")
    ensure_studio_context(cd)
    
    jlog("processing_file", stage="run", ui_state={"file": str(file_path)})

    # 2. Résolution Chemin
    ok_path, resolved = _preflight_resolve_path(file_path)
    if not ok_path:
        jlog("failure", error="file_path_invalid", path=str(file_path))
        return False

    runner = UploadRunner(cd)
    runner.enable_domains()
    
    # 3. Stratégie "Zero-Copy" / Neutralisation
    upload_path_obj = resolved
    if NEUTRALIZE_FILENAME_FOR_PREFILL:
        try:
            upload_path_str = _make_neutral_upload_copy(resolved)
            upload_path_obj = Path(upload_path_str)
            jlog("info", msg="Neutral copy created", path=upload_path_str)
        except Exception as e:
            jlog("warning", msg="Neutral copy failed, using original", error=str(e))

    # 4. Injection Fichier via CDP
    if not runner.set_file(upload_path_obj, dragdrop_timeout_s=dragdrop_timeout_s):
        jlog("failure", error="set_file_failed")
        return False

    if not runner.wait_upload_ack(timeout_s=ack_timeout):
        jlog("failure", error="upload_ack_timeout")
        return False
    
    # 5. Validation Redirection
    jlog("g2_5_ultra_start", stage="g2_5_ultra", action="init")
    validation = validate_redirect_to_description_page(runner, timeout_s=15.0) 
    
    if not validation.get('success'):
        jlog("stop_rule_G2_5", stage="g2_5_ultra", outcome="stop",
             error_signature="description_page_validation_failed",
             details=validation.get('reason'))
        return False
        
    jlog("g2_5_ultra_success", stage="g2_5_ultra", action="complete_validated")

    # 6. Injection des Métadonnées (INTELLIGENCE V4)
    description = description or ""
    
    # Utilisation du Fuzzy Finder pour la description
    jlog("intelligence", msg="🧠 Recherche Heuristique du champ Description...")
    fuzzy_js = _get_fuzzy_finder_js(description)
    fuzzy_res = runner.eval(fuzzy_js, await_promise=False)
    
    if fuzzy_res and fuzzy_res.get("found"):
        jlog("success", msg=f"Description injectée (Score: {fuzzy_res.get('score')})")
    else:
        jlog("warning", msg="Fuzzy finder échoué, tentative Fallback classique...")
        # Fallback sur les sélecteurs hardcodés
        desc_selector = '[data-e2e*="caption" i] div[contenteditable="true"], [data-e2e*="description" i] div[contenteditable="true"]'
        set_description_robust(runner, desc_selector, description, max_attempts=4)

    # 7. Mutation Guard (Anti-Ecrasement)
    # On utilise un sélecteur large pour le guard
    desc_selector_guard = 'div[contenteditable="true"]'
    try:
        runner.eval(guard_mutation_js(json.dumps(desc_selector_guard), json.dumps(description), 5000), True, 2.0)
    except Exception: pass

    # 8. Post Guard & Clic Final
    if and_guard:
        guard = LightPostGuard(runner, nudge_after=nudge_after, max_wait_post=max_wait_post, dry_run=dry_run)
        
        if not guard.wait_for_post_button():
            jlog("failure", error="post_button_timeout")
            return False

        if dry_run: return True
        
        # Clic Final
        ok = True
        try:
            res = runner.eval(JS_CLICK_POST, True) or {}
            if not res.get("clicked"):
                ok = False
        except Exception:
            ok = False
        
        time.sleep(1.5)
        
        # Gestion Modale Confirmation
        try:
            confirm_res = runner.eval(JS_CLICK_CONFIRM_POST, True) or {}
            if confirm_res.get('modal_found') and not confirm_res.get('clicked'):
                 ok = False
        except Exception: pass

        # Cleanup
        try:
            runner.eval("(function(){ try{ if(window.__ttCaptionGuard) __ttCaptionGuard.disconnect(); }catch(_){}})()", True, 1.5)
        except: pass

        return bool(ok)
    else:
        jlog("success", msg="Upload Ready (Manual Post Required)")
        return True

# -----------------------------------------------------------------------------
# CLASS WRAPPER FOR NEXUS INTEGRATION
# -----------------------------------------------------------------------------

class TikTokUploader:
    """Interface compatible Nexus V4."""
    def __init__(self, port: int = 9222, url_substr: str = "tiktok.com"):
        self.port = port
        self.url_substr = url_substr
    
    async def upload(self, video_path: str, title: str = "", privacy: str = "public") -> bool:
        jlog("info", msg="Demande Upload TikTok reçue", video=Path(video_path).name)
        try:
            return await asyncio.to_thread(self._upload_sync, video_path, title)
        except Exception as e:
            jlog("error", msg="Exception TikTok Upload Wrapper", error=str(e))
            return False

    def _upload_sync(self, video_path: str, description: str) -> bool:
        cd = None
        try:
            targets = list_targets(self.port)
            tgt = pick_tiktok_target(targets, url_substr=self.url_substr)
            
            if not tgt:
                jlog("error", msg="Aucun onglet TikTok détecté")
                return False
            
            cd = CdpClient(tgt.get("webSocketDebuggerUrl"))
            cd.connect()
            
            success = run_one_file(
                cd=cd,
                file_path=Path(video_path),
                and_guard=True,
                ack_timeout=60.0,
                nudge_after=10.0,
                max_wait_post=120.0,
                dry_run=False,
                title=None,
                description=description,
                safe_post=True
            )
            return success
        except Exception as e:
            jlog("fatal", msg="Erreur interne TikTokUploader", error=str(e))
            return False
        finally:
            if cd: cd.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="tt_uploader")
    sub = ap.add_subparsers(dest="cmd")
    
    runp = sub.add_parser("run")
    runp.add_argument("--port", type=int, default=9222)
    runp.add_argument("--file", type=str, required=True)
    runp.add_argument("--description", type=str)
    
    args = ap.parse_args()
    
    if args.cmd == "run":
        uploader = TikTokUploader(port=args.port)
        res = asyncio.run(uploader.upload(args.file, title=args.description))
        sys.exit(0 if res else 1)