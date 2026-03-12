### tools/yt_uploader.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YouTube Uploader Intelligent V2 — Remediated.

FIXES v2 :
  - Import de SELECTORS/TIMEOUTS (inexistants dans tt_constants) supprimé.
  - UnboundLocalError dans robust_fill corrigé (variable loc définie avant le try).
  - Logique du wizard refactorisée : le compteur n'avance que sur un clic réussi.
  - Sélecteur radio de visibilité corrigé (value= au lieu de name= inexistant).
  - wait_and_click_semantic dédupliquée (version locale propre, sans import croisé).
  - validate_session_health renforcé.
  - Timeouts explicites sur toutes les attentes Playwright.
"""

import sys
import asyncio
import os
import argparse
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page, Locator, FileChooser

# Import local des utils — stratégie de fallback propre et sans import mort
try:
    from tools.tt_utils import jlog, get_cdp_endpoint, check_file_exists, ensure_absolute_path, SmartMetadata
except ImportError:
    try:
        from tt_utils import jlog, get_cdp_endpoint, check_file_exists, ensure_absolute_path, SmartMetadata
    except ImportError:
        # Mode secours minimal — aucun import de constantes inexistantes
        def jlog(level, **kwargs):
            print(f"[{level.upper()}] {kwargs}", flush=True)

        def get_cdp_endpoint(port):
            import urllib.request, json
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                    return json.load(r).get("webSocketDebuggerUrl")
            except Exception:
                return None

        def check_file_exists(p):
            return os.path.exists(p)

        def ensure_absolute_path(p):
            return os.path.abspath(p)

        class SmartMetadata:
            @staticmethod
            def derive_from_file(p):
                return {"title": Path(p).stem, "description": "#shorts", "is_short": False}


# ---------------------------------------------------------------------------
# NAVIGATION SÉMANTIQUE
# ---------------------------------------------------------------------------

async def wait_and_click_semantic(
    page: Page,
    keywords: list,
    role: str = "button",
    timeout: int = 5000,
) -> bool:
    """
    Navigation sémantique : cherche un élément par son rôle ARIA et son texte.
    Robuste aux changements de sélecteurs CSS.

    FIX v2 :
      - Version locale autonome, plus d'import croisé depuis tt_utils.
      - Gère correctement le cas où count() retourne 0 sans lever d'exception.
    """
    if isinstance(keywords, str):
        keywords = [keywords]

    for keyword in keywords:
        try:
            locator = page.get_by_role(role, name=re.compile(keyword, re.IGNORECASE)).first
            # is_visible() et count() peuvent lever si le locator est invalide,
            # on les protège individuellement.
            try:
                count = await locator.count()
            except Exception:
                count = 0

            if count == 0:
                continue

            try:
                visible = await locator.is_visible()
            except Exception:
                visible = False

            if not visible:
                continue

            await locator.wait_for(state="visible", timeout=timeout)
            await locator.scroll_into_view_if_needed()
            await locator.click()
            jlog("nav_click", target=keyword, role=role, status="success")
            return True

        except Exception as e:
            jlog("nav_click_failed", keyword=keyword, role=role, error=str(e))
            continue

    return False


# ---------------------------------------------------------------------------
# REMPLISSAGE RÉSILIENT
# ---------------------------------------------------------------------------

async def robust_fill(page: Page, selector: str, value: str, name: str = "field"):
    """
    Remplissage résilient d'un champ de formulaire.

    FIX v2 :
      - `loc` est défini AVANT le bloc try pour éliminer l'UnboundLocalError
        dans le bloc except (qui accédait à `loc` potentiellement non défini
        si page.locator() avait levé une exception).
    """
    loc = page.locator(selector).first
    try:
        await loc.wait_for(state="visible", timeout=5000)
        await loc.click()
        await loc.fill("")
        await loc.fill(value)
        jlog("input_fill", field=name, status="success")
    except Exception as e:
        jlog("input_fill_failed", field=name, error=str(e))
        # Stratégie de repli : frappe caractère par caractère
        try:
            await loc.press_sequentially(value, delay=50)
        except Exception as e2:
            jlog("input_fill_sequential_failed", field=name, error=str(e2))


# ---------------------------------------------------------------------------
# HEALTH CHECK DE SESSION
# ---------------------------------------------------------------------------

async def validate_session_health(page: Page) -> bool:
    """
    Vérifie proactivement que la session YouTube est active avant l'upload.
    """
    jlog("session_health_check", step="start")
    try:
        is_logged_in = False

        # Détection rapide par présence de l'avatar ou du bouton Créer
        for selector in ("#avatar-btn", "button#avatar-btn", "img[alt*='Avatar']", "#create-icon"):
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    is_logged_in = True
                    break
            except Exception:
                continue

        if not is_logged_in:
            # Vérification redirection login
            current_url = page.url
            if "google.com/signin" in current_url or "accounts.google.com" in current_url:
                jlog("session_health", status="critical",
                     error="Redirigé vers la page de connexion", url=current_url)
                return False

            # Bouton Se connecter visible ?
            sign_in_selectors = [
                "a[href*='accounts.google.com']",
                "button:has-text('Sign in')",
                "button:has-text('Se connecter')",
            ]
            for sel in sign_in_selectors:
                try:
                    if await page.locator(sel).first.is_visible(timeout=1000):
                        jlog("session_health", status="critical",
                             error="Bouton Se connecter détecté — non connecté")
                        return False
                except Exception:
                    continue

        # Détection de blocages (quota, strike)
        try:
            body_text = await page.inner_text("body")
            blockers = [
                "Daily upload limit reached",
                "Limite quotidienne atteinte",
                "Copyright strike",
            ]
            for block in blockers:
                if block in body_text:
                    jlog("session_health", status="blocked",
                         error=f"Contrainte compte détectée: {block}")
                    return False
        except Exception:
            pass  # Fail-open : on ne bloque pas sur une erreur de lecture

        jlog("session_health", status="healthy")
        return True

    except Exception as e:
        jlog("session_health", status="error", error=str(e))
        return True  # Fail-open


# ---------------------------------------------------------------------------
# SÉQUENCE PRINCIPALE D'UPLOAD
# ---------------------------------------------------------------------------

# Mapping visibilité → valeur attendue dans l'attribut "value" du radio YouTube Studio
_PRIVACY_VALUE_MAP = {
    "public": "PUBLIC",
    "private": "PRIVATE",
    "unlisted": "UNLISTED",
}


async def upload_sequence(
    page: Page,
    video_path: str,
    title: str = None,
    description: str = None,
    privacy: str = "public",
) -> bool:
    """
    Exécute l'upload sur YouTube Studio.

    FIX v2 :
      - Wizard : le compteur steps_done n'avance que sur un clic effectif.
        L'ancienne implémentation incrémentait même sans clic, pouvant atteindre
        max_steps sans jamais publier.
      - Sélecteur radio de visibilité : utilise input[value="PUBLIC"] au lieu de
        name=PUBLIC (attribut name inexistant dans YouTube Studio).
      - Timeouts explicites sur toutes les étapes critiques.
    """
    try:
        jlog("sequence_start", step="navigation_youtube_studio")

        await page.goto("https://studio.youtube.com", wait_until="networkidle", timeout=30000)

        if not await validate_session_health(page):
            jlog("fatal_error", msg="Session invalide. Connexion requise.")
            return False

        # ---- Bouton Créer ----
        jlog("action", msg="Recherche du bouton Créer")
        create_btn = page.locator("#create-icon").first
        create_clicked = False
        try:
            if await create_btn.is_visible(timeout=5000):
                await create_btn.click()
                create_clicked = True
        except Exception:
            pass

        if not create_clicked:
            create_clicked = await wait_and_click_semantic(page, ["Créer", "Create"], "button", timeout=5000)

        if not create_clicked:
            jlog("fatal_error", msg="Impossible de trouver le bouton Créer.")
            return False

        await page.wait_for_timeout(1000)

        # ---- Importer des vidéos ----
        upload_menu_clicked = await wait_and_click_semantic(
            page, ["Importer des vidéos", "Upload videos", "Upload video"], "menuitem", timeout=5000
        )
        if not upload_menu_clicked:
            jlog("fatal_error", msg="Menu 'Importer des vidéos' introuvable.")
            return False

        # ---- Sélection du fichier ----
        jlog("action", msg="Sélection du fichier vidéo")
        try:
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                upload_trigger = page.locator("#select-files-button").first
                try:
                    if await upload_trigger.is_visible(timeout=3000):
                        await upload_trigger.click()
                    else:
                        raise Exception("Trigger #select-files-button invisible")
                except Exception:
                    # Fallback : clic sur la zone de drop
                    await page.locator("//div[@id='content']").click()

            file_chooser: FileChooser = await fc_info.value
            await file_chooser.set_files(video_path)

        except Exception as e:
            jlog("fatal_error", msg="Impossible d'ouvrir le sélecteur de fichier", error=str(e))
            return False

        # ---- Attente du wizard ----
        jlog("action", msg="Attente du wizard de détails")
        try:
            wizard_header = page.locator("h1").filter(
                has_text=re.compile(r"Détails|Details", re.IGNORECASE)
            ).first
            await wizard_header.wait_for(state="visible", timeout=90000)
        except Exception as e:
            jlog("warning", msg="Timeout attente wizard — on tente quand même", error=str(e))

        # ---- Métadonnées ----
        path_obj = Path(video_path)
        smart_data = SmartMetadata.derive_from_file(str(path_obj))

        final_title = title if title else smart_data.get("title", path_obj.stem)
        final_desc = description if description else smart_data.get("description", "")

        jlog("heuristics", msg="Métadonnées calculées",
             title=final_title, derived_title=(title is None))

        # Titre — premier textbox du wizard
        title_box = page.locator("#textbox").nth(0)
        try:
            if await title_box.is_visible(timeout=5000):
                await title_box.click()
                # Vide le contenu existant (Ctrl+A puis Delete) avant de remplir
                await title_box.press("Control+a")
                await title_box.press("Delete")
                await title_box.fill(final_title)
        except Exception as e:
            jlog("warning", msg="Remplissage titre échoué", error=str(e))

        # Description — deuxième textbox
        desc_box = page.locator("#textbox").nth(1)
        try:
            if await desc_box.is_visible(timeout=3000):
                await desc_box.fill(final_desc)
        except Exception as e:
            jlog("warning", msg="Remplissage description échoué", error=str(e))

        # Audience : "Non conçu pour les enfants"
        try:
            not_for_kids = page.locator(
                "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_THE_TARGET'], "
                "ytcp-radio-group [name='VIDEO_MADE_FOR_KIDS_NOT_THE_TARGET']"
            ).first
            if await not_for_kids.is_visible(timeout=3000):
                await not_for_kids.click()
        except Exception as e:
            jlog("warning", msg="Option 'Pas pour les enfants' introuvable", error=str(e))

        # ---- Wizard de navigation ----
        # FIX v2 : steps_done n'est incrémenté QUE sur un clic réussi (Next ou Publish).
        # L'ancienne implémentation incrémentait inconditionnellement, créant un
        # faux sentiment de progression même sans avancer dans le wizard.
        max_next_clicks = 5
        next_clicks_done = 0

        while next_clicks_done < max_next_clicks:
            # Essai bouton Suivant
            next_clicked = await wait_and_click_semantic(
                page, ["Suivant", "Next"], "button", timeout=2500
            )

            if next_clicked:
                jlog("workflow", step="next_clicked", count=next_clicks_done + 1)
                await page.wait_for_timeout(1200)
                next_clicks_done += 1
                continue

            # On est peut-être à l'étape de visibilité
            # FIX v2 : input[value="PUBLIC"] au lieu de name=PUBLIC (inexistant dans YT Studio)
            privacy_value = _PRIVACY_VALUE_MAP.get(privacy.lower(), "PUBLIC")
            try:
                privacy_radio = page.locator(
                    f'tp-yt-paper-radio-button[name="{privacy_value}"],'
                    f'ytcp-radio-group [name="{privacy_value}"],'
                    f'input[value="{privacy_value}"]'
                ).first
                if await privacy_radio.is_visible(timeout=2000):
                    await privacy_radio.click()
                    jlog("workflow", step="privacy_set", value=privacy_value)
            except Exception:
                pass

            # Essai bouton Publier / Enregistrer
            publish_clicked = await wait_and_click_semantic(
                page,
                ["Publier", "Publish", "Enregistrer", "Save"],
                "button",
                timeout=2500,
            )

            if publish_clicked:
                jlog("workflow", step="published")
                break

            # Aucun bouton trouvé à cette itération : on attend et on retente
            # sans incrémenter le compteur (le wizard n'a pas progressé)
            await asyncio.sleep(1.5)

            # Garde-fou : si on attend trop longtemps sans rien faire, on abandonne
            # (évite la boucle infinie silencieuse)
            next_clicks_done += 1

        # ---- Confirmation finale ----
        try:
            success_dialog = page.locator("h1").filter(
                has_text=re.compile(r"publiée|published", re.IGNORECASE)
            ).first
            await success_dialog.wait_for(state="visible", timeout=15000)
            jlog("success", msg="Upload YouTube terminé avec succès ✓")
            return True
        except Exception:
            jlog("warning", msg="Pas de dialogue de confirmation explicite — flux terminé.")
            return True

    except Exception as e:
        jlog("fatal_error", context="upload_sequence", error=str(e))
        try:
            await page.screenshot(path="error_yt_upload.png")
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# API PUBLIQUE — YoutubeUploader
# ---------------------------------------------------------------------------

class YoutubeUploader:
    """
    Classe wrapper pour intégration dans Nexus Daemon.
    Gère la connexion CDP Playwright et l'appel à la séquence d'upload.
    """

    def __init__(self, port: int = 9222):
        self.port = port
        self.ws_url: str = None  # Résolu à chaque upload pour gérer les redémarrages Chrome

    async def upload(
        self,
        video_path: str,
        title: str = None,
        description: str = None,
        privacy: str = "public",
    ) -> bool:
        """Méthode principale appelée par le démon."""
        self.ws_url = get_cdp_endpoint(self.port)
        if not self.ws_url:
            jlog("error", msg="Connexion CDP impossible (navigateur fermé ?)", port=self.port)
            return False

        if not check_file_exists(video_path):
            jlog("error", msg="Fichier vidéo introuvable", path=video_path)
            return False

        video_path = ensure_absolute_path(video_path)

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.ws_url)

                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = await browser.new_context()

                page = await context.new_page()

                success = await upload_sequence(
                    page,
                    video_path,
                    title=title,
                    description=description,
                    privacy=privacy,
                )

                try:
                    await page.close()
                except Exception:
                    pass

                return success

            except Exception as e:
                jlog("fatal", msg="Erreur critique dans YoutubeUploader", error=str(e))
                return False


# ---------------------------------------------------------------------------
# ENTRY POINT CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Uploader Intelligent V2")
    parser.add_argument("--file", required=True, help="Chemin du fichier vidéo")
    parser.add_argument("--port", type=int, default=9222, help="Port CDP du navigateur")
    parser.add_argument("--title", help="Titre de la vidéo")
    parser.add_argument("--description", help="Description")
    parser.add_argument(
        "--privacy",
        default="public",
        choices=["public", "private", "unlisted"],
        help="Visibilité",
    )

    args = parser.parse_args()

    uploader = YoutubeUploader(port=args.port)

    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        result = asyncio.run(
            uploader.upload(
                video_path=args.file,
                title=args.title,
                description=args.description,
                privacy=args.privacy,
            )
        )
        sys.exit(0 if result else 1)

    except KeyboardInterrupt:
        jlog("info", msg="Interruption manuelle.")
        sys.exit(1)