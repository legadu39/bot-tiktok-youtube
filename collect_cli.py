# -*- coding: utf-8 -*-
from __future__ import annotations
# VERSION 8.16.0-NexusV5-Unbreakable (Fix: Path Resolution Bypass)

# ===== Imports stdlib =====
import sys
import os
import traceback
from pathlib import Path
import json
import time
import argparse
import asyncio
import random
import math
import re
from typing import Optional, Dict, Any, List, Tuple

# ===== Imports Nexus V3 Core (CORRECTION IMPORTS) =====
# On ajoute le chemin racine pour trouver common.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Variable globale pour diagnostiquer le Failover
FALLBACK_IMPORT_ERROR = None

try:
    from common import jlog as nexus_log, CONFIG as NEXUS_CONFIG
    from fallback import FallbackProvider as ContentFallback 
except ImportError as e:
    # Capture de l'erreur exacte pour le diagnostic
    FALLBACK_IMPORT_ERROR = str(e)
    
    # Fallback pour éviter le crash immédiat si environnement mal configuré
    def nexus_log(*args, **kwargs): print(f"[LOG] {kwargs.get('msg', 'No msg')}", file=sys.stderr)
    NEXUS_CONFIG = {"BUFFER_PATH": Path("./buffer")}
    ContentFallback = None

# ===== Imports Prompts V3 =====
try:
    from prompts.templates import wrap_prompt
except ImportError:
    # Si exécuté depuis la racine
    sys.path.append(os.getcwd())
    try:
        from prompts.templates import wrap_prompt
    except ImportError:
         def wrap_prompt(p, m=""): return p

# ===== Imports Playwright =====
from playwright.async_api import (
    async_playwright, Page, Error as PlaywrightError, BrowserContext,
    TimeoutError as PWTimeoutError, Locator
)

# ===== Imports Gemini Headless (Bibliothèque) =====
IMPORT_ERROR = None
SIGNAL_DIR = Path("./temp_signals") # Valeur par défaut de sécurité

try:
    # --- FIX CRITIQUE V5.4 : Bypass de la résolution complexe de chemin ---
    # On définit SIGNAL_DIR manuellement pour éviter le crash '_resolve_signal_dir'
    SIGNAL_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "temp_signals"
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)

    from gemini_headless.collect.orchestrator import Orchestrator
    from gemini_headless.collect.utils.logs import jlog as legacy_jlog
    from gemini_headless.collect.producers.dom import _GET_BEST_TEXT_JS, safe_frame_evaluate
    from gemini_headless.collect.monitors.activity_monitor import (
        FrozenStateDetector,
        stagnation_monitor_task,
        activity_probe_task
    )
    from gemini_headless.connectors.main import fast_send_prompt
    from gemini_headless.utils.sandbox_profile import SandboxProfile
    from gemini_headless.utils.session_guardian import SessionGuardian
    from gemini_headless.utils.fingerprint import Fingerprint, build_launch_args, DOMSignatureLearner
    from gemini_headless.utils.stealth_injector import apply_stealth
    from timeout_manager import CrossProcessTimeoutManager
    from gemini_headless.cli.config import (
        calculate_adaptive_timeouts, 
        MODEL_TIMEOUT_CONFIGS, 
        DEFAULT_TIMEOUT_CONFIG
    )
    from gemini_headless.cli.upload_handler import handle_file_upload
    from gemini_headless.cli.utils import get_browser_executable_path
    # Note: On n'importe PLUS _resolve_signal_dir pour éviter le crash

except Exception as e: # On catch TOUT (pas juste ImportError) pour garantir la survie
    IMPORT_ERROR = str(e)
    nexus_log("warning", msg=f"Erreur initialisation modules Gemini: {e}")
    # On garde le SIGNAL_DIR par défaut défini plus haut


# ============================================================================
# SMART AGENT UTILITIES (BIO-MIMICRY & STEALTH)
# ============================================================================

class HumanLikeInterface:
    """
    Simule des interactions humaines avancées (Chaos contrôlé, loi de Fitts, Overshoot).
    """
    
    @staticmethod
    def _bezier_point(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
        return (1-t)**3 * p0 + 3*(1-t)**2 * t * p1 + 3*(1-t) * t**2 * p2 + t**3 * p3

    @staticmethod
    async def natural_mouse_move(page: Page, start_x: float, start_y: float, end_x: float, end_y: float, steps: int = None):
        """
        Déplace la souris avec une trajectoire courbe, vitesse variable et overshoot potentiel.
        """
        # Calcul de la distance pour ajuster dynamiquement les étapes
        distance = math.hypot(end_x - start_x, end_y - start_y)
        if steps is None:
            # Plus c'est loin, plus il faut d'étapes, mais pas trop pour rester rapide
            steps = max(15, min(int(distance / 5), 60))

        # Logique d'Overshoot (dépassement de cible caractéristique de l'humain rapide)
        should_overshoot = distance > 300 and random.random() > 0.4
        
        target_x = end_x
        target_y = end_y
        
        if should_overshoot:
            overshoot_amt = random.uniform(5, 20)
            target_x += overshoot_amt * (1 if end_x > start_x else -1)
            target_y += overshoot_amt * (1 if end_y > start_y else -1)

        # Points de contrôle Bézier (Gigue)
        ctrl1_x = start_x + (target_x - start_x) * random.uniform(0.1, 0.4) + random.uniform(-20, 20)
        ctrl1_y = start_y + (target_y - start_y) * random.uniform(0.1, 0.4) + random.uniform(-20, 20)
        ctrl2_x = start_x + (target_x - start_x) * random.uniform(0.6, 0.9) + random.uniform(-20, 20)
        ctrl2_y = start_y + (target_y - start_y) * random.uniform(0.6, 0.9) + random.uniform(-20, 20)

        for i in range(steps + 1):
            t = i / steps
            # Lissage (Ease-in-out)
            t_smooth = t * t * (3 - 2 * t)
            
            x = HumanLikeInterface._bezier_point(t_smooth, start_x, ctrl1_x, ctrl2_x, target_x)
            y = HumanLikeInterface._bezier_point(t_smooth, start_y, ctrl1_y, ctrl2_y, target_y)
            
            # Micro-tremblements (bruit moteur humain)
            noise_x = random.uniform(-0.5, 0.5)
            noise_y = random.uniform(-0.5, 0.5)
            
            await page.mouse.move(x + noise_x, y + noise_y)
            
            # Vitesse variable : rapide au milieu, lent aux extrémités
            wait_time = random.uniform(0.001, 0.005) if 0.2 < t < 0.8 else random.uniform(0.005, 0.015)
            await asyncio.sleep(wait_time)

        # Correction de l'Overshoot (retour à la cible réelle)
        if should_overshoot:
            await asyncio.sleep(random.uniform(0.05, 0.15)) # Temps de réaction oculaire
            await page.mouse.move(end_x, end_y, steps=5)

    @staticmethod
    async def smart_click(page: Page, selector: str = None, locator: Locator = None):
        try:
            target = locator if locator else page.locator(selector)
            if not await target.is_visible(): return False
            
            box = await target.bounding_box()
            if not box: return False
            
            # Position actuelle de la souris
            # Note: Playwright ne donne pas la pos actuelle facilement sans state, 
            # on assume un départ aléatoire si inconnu ou 0,0
            start_x, start_y = random.uniform(0, 100), random.uniform(0, 100)
            
            # Cible aléatoire DANS l'élément (pas au centre exact, c'est un bot flag)
            target_x = box['x'] + box['width'] * random.uniform(0.15, 0.85)
            target_y = box['y'] + box['height'] * random.uniform(0.15, 0.85)
            
            await HumanLikeInterface.natural_mouse_move(page, start_x, start_y, target_x, target_y)
            
            await asyncio.sleep(random.uniform(0.08, 0.22))
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.06, 0.14)) # Durée du clic
            await page.mouse.up()
            return True
        except Exception as e:
            if IMPORT_ERROR is None: legacy_jlog("smart_click_failed", error=str(e), level="WARN")
            return False

    @staticmethod
    async def human_type_text(page: Page, text: str):
        """Tape du texte de manière rythmique et cognitive (Keystroke Dynamics)."""
        words = text.split(" ")
        for i, word in enumerate(words):
            for char in word:
                # Vitesse de base (rapide mais variable)
                delay = random.gauss(0.05, 0.015)
                delay = max(0.02, min(0.15, delay))
                
                # Ralentissement sur majuscules et symboles
                if char.isupper() or char in "{[(!?@#":
                    delay += random.uniform(0.05, 0.1)
                
                await page.keyboard.press(char)
                await asyncio.sleep(delay)
            
            # Espace entre les mots
            if i < len(words) - 1:
                await page.keyboard.press("Space")
                # Pause cognitive aléatoire (réflexion) tous les 6-10 mots
                if i > 0 and i % random.randint(6, 10) == 0:
                    await asyncio.sleep(random.uniform(0.3, 0.8))


class SmartVision:
    """Système de fallback pour trouver des éléments via heuristiques sémantiques."""
    @staticmethod
    async def find_upload_button(page: Page, dom_learner: Any = None) -> Optional[Locator]:
        if IMPORT_ERROR is None: legacy_jlog("smart_vision_scanning_for_upload", level="DEBUG")
        
        # INTELLIGENCE N°2: Utiliser la connaissance apprise si disponible
        if dom_learner:
            learned_sel = dom_learner.get_best_selector("upload_button", None)
            if learned_sel:
                try:
                    btn = page.locator(learned_sel).first
                    if await btn.is_visible():
                        nexus_log("info", msg="Utilisation du sélecteur d'upload appris.")
                        return btn
                except: pass

        candidates = await page.get_by_role("button").all()
        candidates.extend(await page.locator("div[role='button'], span[role='button']").all())
        best_score = -1
        best_candidate = None
        keywords = ["upload", "importer", "add", "plus", "joint", "file"]
        
        for idx, btn in enumerate(candidates):
            try:
                if not await btn.is_visible(): continue
                score = 0
                text = (await btn.text_content() or "").lower()
                aria = (await btn.get_attribute("aria-label") or "").lower()
                tooltip = (await btn.get_attribute("data-tooltip") or "").lower()
                html = await btn.inner_html()
                combined_text = f"{text} {aria} {tooltip}"
                for kw in keywords:
                    if kw in combined_text: score += 3
                if "<svg" in html and ("d=\"M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z\"" in html or "plus" in html):
                     score += 5
                if score > best_score:
                    best_score = score
                    best_candidate = btn
            except: continue
        
        if best_score > 2: 
            return best_candidate
        return None


# ============================================================================
# CONTENT GENERATOR CLASS (MODULAR V4.2 - INTELLIGENT ROUTING)
# ============================================================================

class ContentGenerator:
    """
    Le Cerveau de génération V4.2.
    """
    
    # [Intelligence] Configuration Circuit Breaker
    CB_MAX_CONSECUTIVE_FAILURES = 3
    
    def __init__(self, user_id: str, profile_base: str, model: str = "gemini-1.5-flash"):
        self.user_id = user_id
        self.profile_base = profile_base
        self.model = model
        self.failure_reason = "unknown_init"
        self.downloaded_files_registry = set() # Pour éviter les doublons
        
        if IMPORT_ERROR:
            nexus_log("error", msg=f"ContentGenerator initialisé avec des dépendances manquantes: {IMPORT_ERROR}")

    def save_to_nexus_buffer(self, data: Dict[str, Any], prompt: str):
        """Sauvegarde le résultat dans la Zone Tampon V3 avec extraction intelligente."""
        try:
            safe_prompt = "".join([c if c.isalnum() else "_" for c in prompt[:30]])
            timestamp_int = int(time.time())
            filename = f"{timestamp_int}_{safe_prompt}.json"
            buffer_dir = NEXUS_CONFIG["directories"].get("buffer_folder", Path("./buffer"))
            filepath = buffer_dir / filename
            
            # --- INTELLIGENCE N°3: EXTRACTION DE CODE ---
            self._extract_smart_content(data.get("text", ""), safe_prompt, buffer_dir, timestamp_int)
            
            final_payload = {
                "meta": {
                    "prompt": prompt,
                    "timestamp": time.time(),
                    "source": data.get("source", "unknown"),
                    "version": "8.12-NexusV4-Intelligent"
                },
                "content": data
            }
            
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(final_payload, f, indent=4, ensure_ascii=False)
                
            nexus_log("success", msg=f"Contenu livré dans la Zone Tampon : {filename}")
            return True
        except Exception as e:
            nexus_log("fatal", msg="Echec écriture Zone Tampon", error=str(e))
            return False
            
    def _extract_smart_content(self, text: str, safe_prompt: str, output_dir: Path, ts: int):
        """Détecte et extrait les blocs de code vers des fichiers dédiés."""
        try:
            pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
            matches = pattern.findall(text)
            
            for idx, (lang, content) in enumerate(matches):
                lang = lang.lower().strip() if lang else "txt"
                ext_map = {"python": "py", "javascript": "js", "typescript": "ts", "json": "json", "html": "html", "css": "css", "sql": "sql", "csv": "csv"}
                ext = ext_map.get(lang, lang)
                
                if len(content.strip()) < 10: continue
                
                fname = f"EXT_{ts}_{safe_prompt}_{idx}.{ext}"
                fpath = output_dir / fname
                
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
                nexus_log("info", msg=f"🧠 Extraction intelligente : Code ({lang}) sauvegardé dans {fname}")
                
        except Exception as e:
            nexus_log("warning", msg="Echec extraction intelligente", error=str(e))

    def _check_circuit_breaker(self, tm: CrossProcessTimeoutManager) -> bool:
        """
        [Intelligence] Vérifie si on doit skipper le headless.
        """
        try:
            status = tm.get_circuit_breaker_status()
            failures = status.get("failures", 0)
            last_ts = status.get("last_ts", 0.0)
            
            if failures < self.CB_MAX_CONSECUTIVE_FAILURES:
                return False
                
            backoff_factor = max(0, failures - 1)
            retry_delay = min(300 * (2 ** backoff_factor), 3600)
            
            elapsed = time.time() - last_ts
            remaining = retry_delay - elapsed
            
            if remaining > 0:
                nexus_log("warning", msg=f"🛡️ CIRCUIT BREAKER ACTIF: {failures} échecs. Backoff: {int(remaining)}s restants. Skip Headless.")
                return True
            else:
                nexus_log("info", msg=f"🛡️ CIRCUIT BREAKER: Délai écoulé ({int(retry_delay)}s). Tentative de sondage (Probe)...")
                return False
                
        except Exception as e:
            nexus_log("error", msg="Erreur lecture Circuit Breaker", error=str(e))
            return False

    async def _process_download_queue(self, page: Page, queue: asyncio.Queue, output_dir: Path, prompt_tag: str):
        """Worker asynchrone pour télécharger les images en arrière-plan."""
        while True:
            try:
                img_meta = await queue.get()
                if img_meta is None: # Signal d'arrêt
                    queue.task_done()
                    break
                
                src = img_meta.get("src", "")
                if not src or src in self.downloaded_files_registry:
                    queue.task_done()
                    continue
                
                if src.startswith("http"):
                    try:
                        response = await page.request.get(src, timeout=10000)
                        if response.status == 200:
                            buffer = await response.body()
                            if len(buffer) > 10000: # Seuil 10KB
                                filename = f"IMG_{int(time.time())}_{prompt_tag}_{len(self.downloaded_files_registry)}.png"
                                filepath = output_dir / filename
                                
                                with open(filepath, "wb") as f:
                                    f.write(buffer)
                                    
                                self.downloaded_files_registry.add(src)
                                img_meta["local_path"] = str(filepath.absolute())
                                img_meta["filename"] = filename
                                nexus_log("success", msg=f"⚡ Streaming Download : {filename} matérialisé.")
                            else:
                                nexus_log("debug", msg=f"Image ignorée (taille {len(buffer)} bytes)")
                    except Exception as e:
                        nexus_log("warning", msg=f"Echec Streaming Download {src[:20]}", error=str(e))
                
                elif src.startswith("file://"):
                     self.downloaded_files_registry.add(src)

                queue.task_done()
                
            except Exception as e:
                nexus_log("error", msg="Erreur critique worker download", error=str(e))
                queue.task_done()

    async def run(self, prompt: str, file_path: str = None, upload_selector: str = None, 
                  login_mode: bool = False, debug_selectors: bool = False) -> Dict[str, Any]:
        """
        Exécute la séquence de génération : Headless -> Validation -> Failover -> Buffer.
        Intègre maintenant le Stealth Mode et le Warm-up de session.
        """
        
        shared_manager = None
        circuit_breaker_active = False

        if IMPORT_ERROR:
             nexus_log("warning", msg="Imports critiques manquants, basculement forcé vers API.")
             headless_success = False
        else:
             final_prompt = wrap_prompt(prompt) if prompt else prompt
             try:
                 shared_manager = CrossProcessTimeoutManager()
                 if not login_mode and not debug_selectors:
                     circuit_breaker_active = self._check_circuit_breaker(shared_manager)
                 else:
                     circuit_breaker_active = False
             except Exception:
                 pass
                 
             headless_success = False
        
        extracted_data = {}
        context: Optional[BrowserContext] = None
        playwright_instance = None
        download_worker_task = None
        download_queue = asyncio.Queue()
        
        # --- PHASE 1 : HEADLESS (STEALTH MODE) ---
        if not IMPORT_ERROR and not circuit_breaker_active:
            try:
                # Setup Timeouts
                video_size_mb = None
                if file_path and os.path.exists(file_path):
                     video_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                
                timeouts = calculate_adaptive_timeouts(model_name=self.model, video_size_mb=video_size_mb)
                if shared_manager:
                    shared_manager.set_timeouts(
                        base_heartbeat_s=timeouts['heartbeat_timeout_s'],
                        generation_timeout_s=timeouts['generation_timeout_s']
                    )

                profile = SandboxProfile(user_id=self.user_id, base_dir=self.profile_base)
                profile.ensure_dirs()
                
                # INTELLIGENCE N°2: Chargement du Learner DOM & Fingerprint
                fp = Fingerprint.load_or_seed(profile)
                dom_learner = DOMSignatureLearner(Path(profile.profile_dir))
                
                browser_path = get_browser_executable_path()
                if not browser_path: raise Exception("Browser executable not found")

                playwright_instance = await async_playwright().start()
                is_interactive = bool(login_mode or debug_selectors)
                
                # --- STRATEGIE STEALTH : ARGS DE LANCEMENT CRITIQUES ---
                base_args = build_launch_args(fp)
                # On désactive explicitement les drapeaux d'automatisation
                ignore_defaults = ["--enable-automation"] 
                stealth_args = [
                    "--disable-blink-features=AutomationControlled", # Cache navigator.webdriver
                    "--no-sandbox",
                    "--disable-infobars",
                    "--start-maximized",
                    # Emulation écran standard pour éviter fingerprint 800x600
                    f"--window-size={1920},{1080}",
                    # FIX CRITIQUE: Bypass SSL pour éviter ERR_CERT_COMMON_NAME_INVALID (Antivirus/Proxy)
                    "--ignore-certificate-errors",
                    "--ignore-ssl-errors",
                    "--allow-insecure-localhost"
                ]
                final_launch_args = base_args + stealth_args

                nexus_log("info", msg="Lancement Navigateur en mode Stealth...")
                context = await playwright_instance.chromium.launch_persistent_context(
                    profile.user_data_dir,
                    headless=False,
                    executable_path=browser_path,
                    args=final_launch_args,
                    ignore_default_args=ignore_defaults, # CRITIQUE POUR L'INDÉTECTABILITÉ
                    viewport=None, # Laisser la fenêtre décider
                    timeout=120000,
                    ignore_https_errors=True # FIX CRITIQUE: Accepter les certificats auto-signés/interceptés
                )

                page = context.pages[0] if context.pages else await context.new_page()
                await apply_stealth(page, fingerprint=fp.__dict__)

                # --- BRANCH LOGIN ---
                if login_mode:
                    nexus_log("info", msg="Mode Login Activé. Connexion manuelle requise.")
                    await page.goto("https://gemini.google.com/app")
                    nexus_log("info", msg="Navigateur ouvert. Fermez la fenêtre manuellement quand la connexion est réussie.")
                    await page.wait_for_event("close", timeout=0)
                    return {}

                # --- BRANCH GENERATION AVEC WARM-UP ---
                nexus_log("info", msg="Navigation vers Gemini...")
                await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
                
                guardian = SessionGuardian(profile_root=Path(profile.profile_dir), logger=None)
                repair = await guardian.repair_if_needed(page, timeout_s=30.0)
                if repair.get("need_reset"): raise Exception("Session Invalide - Login requis")

                # --- INTELLIGENCE SESSION : WARM-UP ---
                # Si c'est une nouvelle session, on simule une petite activité humaine avant de "bombarder"
                # pour éviter les analyses comportementales immédiates.
                try:
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    # Scroll aléatoire pour montrer de la vie
                    await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
                except: pass

                if file_path:
                    nexus_log("info", msg=f"Upload du fichier : {file_path}")
                    up_ok, reason = await handle_file_upload(page, file_path, upload_selector, Path(profile.profile_dir))
                    if not up_ok:
                        nexus_log("warning", msg="Echec upload standard, tentative Smart Vision...")
                        # On passe le dom_learner au SmartVision
                        btn = await SmartVision.find_upload_button(page, dom_learner)
                        if btn:
                            # Apprentissage du sélecteur
                            try:
                                selector_to_learn = await btn.evaluate("el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.getAttribute('aria-label') ? '[aria-label=\"' + el.getAttribute('aria-label') + '\"]' : '')")
                                dom_learner.learn_success("upload_button", selector_to_learn)
                            except: pass

                            async with page.expect_file_chooser() as fc_info:
                                await HumanLikeInterface.smart_click(page, locator=btn)
                            (await fc_info.value).set_files(file_path)
                            await asyncio.sleep(5)
                        else:
                            raise Exception("Impossible d'uploader le fichier (Bouton introuvable)")

                # --- INTELLIGENCE V21: PRE-PROMPT SNAPSHOT ---
                nexus_log("info", msg="Capture de l'état visuel initial...")
                existing_images_snapshot = []
                try:
                    existing_images_snapshot = await page.evaluate("""() => {
                        try {
                            return Array.from(document.images).map(i => i.src).filter(s => s.length > 0);
                        } catch(e) { return []; }
                    }""")
                except Exception as e:
                    nexus_log("warning", msg="Echec du snapshot visuel", error=str(e))

                # --- DEMARRAGE WORKER DOWNLOAD ---
                output_dir = Path(self.profile_base) / "downloads"
                output_dir.mkdir(parents=True, exist_ok=True)
                safe_tag = "".join([c if c.isalnum() else "" for c in (prompt or "img")])[:15]
                
                download_worker_task = asyncio.create_task(
                    self._process_download_queue(page, download_queue, output_dir, safe_tag)
                )
                
                async def on_image_detected(img_meta):
                    await download_queue.put(img_meta)

                nexus_log("info", msg="Envoi du prompt...")
                # Utilisation de fast_send_prompt (qui contient déjà des optimisations, mais on bénéficie ici des launch_args)
                if not await fast_send_prompt(page, final_prompt, is_post_upload=bool(file_path)):
                    raise Exception("Echec envoi prompt")

                nexus_log("info", msg="Attente de la réponse...")
                
                if shared_manager:
                    stagnation_timeout_ms = int(shared_manager.get_generation_timeout_s() * 1000)
                else:
                    stagnation_timeout_ms = 90000

                orch = Orchestrator(
                    page, 
                    stagnation_timeout_ms=stagnation_timeout_ms,
                    prompt=final_prompt,
                    existing_images=existing_images_snapshot,
                    on_image_detected=on_image_detected
                )
                
                stagnation_detector = FrozenStateDetector()
                tasks = [
                    asyncio.create_task(activity_probe_task(page, orch._done_evt, stagnation_detector, orch)),
                    asyncio.create_task(stagnation_monitor_task(stagnation_detector, orch._done_evt, page, Path(profile.profile_dir), SIGNAL_DIR))
                ]
                
                text, meta, _, _ = await orch.runfastpath()
                for t in tasks: t.cancel()

                # Fin du streaming
                await download_queue.put(None) 
                if download_worker_task:
                    await download_worker_task

                # Consolidation Finale
                valid_images = []
                downloaded_paths = []
                
                raw_images = meta.get("images", [])
                for img in raw_images:
                    if "local_path" in img:
                        valid_images.append(img)
                        downloaded_paths.append(img["local_path"])
                    else:
                        if img.get("src") not in self.downloaded_files_registry:
                             pass

                if not text or len(text) < 10:
                    raise Exception("Réponse invalide ou vide du Headless")

                extracted_data = {
                    "text": text,
                    "images": valid_images,
                    "downloaded_files": downloaded_paths,
                    "source": "headless_browser"
                }
                headless_success = True
                
                if shared_manager:
                    shared_manager.reset_headless_failures()
                    
                nexus_log("success", msg="Génération Headless réussie.")

            except Exception as e:
                nexus_log("error", msg=f"Echec du Headless Browser: {str(e)}")
                
                # --- AJOUTER CE BLOC POUR LA PHOTO ---
                if context and context.pages:
                    try:
                        await context.pages[0].screenshot(path="CAPTURE_ERREUR_GEMINI.png")
                        nexus_log("info", msg="📸 Capture de l'erreur sauvegardée: CAPTURE_ERREUR_GEMINI.png")
                    except:
                        pass
                # ------------------------------------
                
                self.failure_reason = str(e)
                headless_success = False
                
                if shared_manager:
                    shared_manager.report_headless_failure()

            finally:
                if download_worker_task and not download_worker_task.done():
                    download_worker_task.cancel()
                if context: await context.close()
                if playwright_instance: await playwright_instance.stop()

        # --- PHASE 2 : FAILOVER ---
        if not headless_success and not login_mode and not debug_selectors:
            if circuit_breaker_active:
                nexus_log("warning", msg="MODE CIRCUIT BREAKER: BASCULEMENT IMMÉDIAT SUR API DE SECOURS.")
            else:
                nexus_log("warning", msg="BASCULEMENT SUR API DE SECOURS (FAILOVER)")
                
            if ContentFallback is None:
                 nexus_log("fatal", msg=f"Failover impossible : {FALLBACK_IMPORT_ERROR or 'Module manquant'}")
                 raise Exception(f"Failover Module Missing: {FALLBACK_IMPORT_ERROR}")
                 
            fallback = ContentFallback()
            prompt_to_use = locals().get("final_prompt", prompt)
            res = await fallback.generate_text(prompt_to_use)
            
            if res:
                extracted_data = {"text": res}
                extracted_data["source"] = "official_api_fallback"
                nexus_log("success", msg="Contenu sauvé par l'API de secours.")
            else:
                nexus_log("fatal", msg="Echec total (Headless + API). Abandon.")
                raise Exception("Generation Failed on both Headless and API")

        # --- PHASE 3 : LIVRAISON ---
        if extracted_data and prompt:
            self.save_to_nexus_buffer(extracted_data, prompt)
            
        return extracted_data


# ============================================================================
# MAIN EXECUTION (CLI WRAPPER)
# ============================================================================

SESSION_FILE = Path(".nexus_session.json")

def load_sticky_context() -> Dict[str, str]:
    """Charge les paramètres de la dernière session réussie."""
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_sticky_context(user_id: str, profile_base: str):
    """Sauvegarde les paramètres pour la prochaine fois."""
    try:
        data = {"user_id": user_id, "profile_base": profile_base, "last_used": time.time()}
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except: pass

def detect_intent_and_adjust_profile(prompt: str, current_user: str, profile_base: str) -> Tuple[str, str]:
    """
    Routage de profil intelligent et détection d'intention.
    """
    if not prompt: return current_user, profile_base
    
    prompt_lower = prompt.lower()
    visual_keywords = ["image", "dessine", "photo", "génère", "style", "paint", "draw"]
    
    is_visual = any(k in prompt_lower for k in visual_keywords)
    
    # Si on demande du visuel mais qu'on est sur un profil qui semble financier ou admin strict
    if is_visual and "admin" in current_user:
        nexus_log("info", msg="🚀 INTENT: Visuel détecté. Bascule logique potentielle (log only).")
        # Ici on pourrait switcher de profil, pour l'instant on garde la stabilité
        
    return current_user, profile_base

async def main() -> int:
    # --- INTELLIGENCE V13: STICKY SESSION ---
    sticky_ctx = load_sticky_context()
    default_user = sticky_ctx.get("user_id")
    default_profile = sticky_ctx.get("profile_base")
    
    ap = argparse.ArgumentParser(description="Client CLI Gemini Headless (Nexus V4 - Stealth).")
    
    # Les arguments deviennent optionnels si on a un contexte sticky
    ap.add_argument("--user-id", required=(not default_user), default=default_user, 
                    help=f"ID Utilisateur (Défaut: {default_user})")
    ap.add_argument("--profile-base", required=(not default_profile), default=default_profile,
                    help=f"Dossier Profil (Défaut: {default_profile})")
                    
    ap.add_argument("--prompt", help="Requis sauf si --login.")
    ap.add_argument("--file", help="Optionnel : chemin fichier.")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--debug-selectors", action="store_true")
    ap.add_argument("--upload-selector", type=str, default=None)
    ap.add_argument("--model", type=str, default="gemini-1.5-flash")
    ap.add_argument("--screenshot-on-fail", action="store_true") 
    ap.add_argument("--heartbeat-timeout", type=float, default=None)
    ap.add_argument("--generation-timeout", type=float, default=None)
    ap.add_argument("--prompt-2", type=str, default=None)
    
    args = ap.parse_args()
    
    if IMPORT_ERROR:
        print(json.dumps({"evt": "fatal_error", "error": IMPORT_ERROR}), file=sys.stderr)
        return 1

    final_user, final_profile_base = detect_intent_and_adjust_profile(args.prompt, args.user_id, args.profile_base)

    save_sticky_context(final_user, final_profile_base)

    nexus_log("init", msg=f"Démarrage Collect CLI Stealth pour : {args.prompt[:50] if args.prompt else 'Login'}...")

    if not args.login and not args.prompt and not args.debug_selectors:
        nexus_log("fatal", msg="Prompt manquant")
        return 1

    generator = ContentGenerator(user_id=final_user, profile_base=final_profile_base, model=args.model)
    
    try:
        await generator.run(
            prompt=args.prompt,
            file_path=args.file,
            upload_selector=args.upload_selector,
            login_mode=args.login,
            debug_selectors=args.debug_selectors
        )
        return 0
    except Exception:
        return 1

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)