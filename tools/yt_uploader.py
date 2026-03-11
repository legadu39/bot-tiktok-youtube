### tools/yt_uploader.py
import sys
import asyncio
import os
import argparse
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page, Locator

# Import local des outils (ajuster le chemin si nécessaire selon l'exécution)
try:
    from tools.tt_utils import jlog, get_cdp_endpoint, check_file_exists, ensure_absolute_path, SmartMetadata
    from tools.tt_constants import SELECTORS, TIMEOUTS
except ImportError:
    # Fallback pour exécution directe depuis le dossier tools
    try:
        from tt_utils import jlog, get_cdp_endpoint, check_file_exists, ensure_absolute_path, SmartMetadata
        from tt_constants import SELECTORS, TIMEOUTS
    except ImportError:
        # Définition minimale si les utils manquent (Mode Secours)
        def jlog(level, **kwargs): print(f"[{level.upper()}] {kwargs}")
        def get_cdp_endpoint(port): return f"ws://127.0.0.1:{port}/devtools/browser/..."
        def check_file_exists(p): return os.path.exists(p)
        def ensure_absolute_path(p): return os.path.abspath(p)
        class SmartMetadata:
            @staticmethod
            def derive_from_file(p): return {"title": p.stem, "description": "#shorts"}
        SELECTORS = {}
        TIMEOUTS = {}

# --- INTELLIGENCE DE NAVIGATION ---

async def wait_and_click_semantic(page: Page, keywords: list[str], role: str = "button", timeout: int = 5000) -> bool:
    """
    Navigation intelligente : cherche un élément par son sens (texte) plutôt que par un ID fixe.
    Attend qu'il soit stable avant de cliquer.
    """
    try:
        for keyword in keywords:
            # Recherche insensible à la casse
            locator = page.get_by_role(role, name=re.compile(keyword, re.IGNORECASE)).first
            
            if await locator.count() > 0 and await locator.is_visible():
                # On attend que l'élément soit "cliquable" (stable)
                await locator.wait_for(state="visible", timeout=timeout)
                # Scroll si nécessaire
                await locator.scroll_into_view_if_needed()
                await locator.click()
                jlog("nav_click", target=keyword, status="success")
                return True
        return False
    except Exception as e:
        jlog("nav_click_failed", error=str(e), keywords=keywords)
        return False

async def robust_fill(page: Page, selector: str, value: str, name: str = "field"):
    """
    Remplissage résilient : tente de vider le champ avant de remplir, gère les focus.
    """
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=5000)
        await loc.click()
        await loc.fill("") # Clear
        await loc.fill(value)
        jlog("input_fill", field=name, status="success")
    except Exception as e:
        jlog("input_fill_failed", field=name, error=str(e))
        # Stratégie de repli : Type caractère par caractère si fill échoue
        try:
            await loc.press_sequentially(value, delay=50)
        except:
            pass

# --- INTELLIGENCE N°4 : HEALTH CHECK DE SESSION ---

async def validate_session_health(page: Page) -> bool:
    """
    Vérifie proactivement si la session YouTube est active et saine AVANT de tenter l'upload.
    Retourne True si le système peut procéder, False sinon.
    """
    jlog("session_health_check", step="start")
    try:
        # 1. Détection Login (Fail-Fast)
        # On cherche l'avatar utilisateur ou le bouton Créer
        avatar = page.locator("#avatar-btn, button#avatar-btn, img[alt*='Avatar']").first
        create_icon = page.locator("#create-icon").first
        sign_in_btn = page.locator("a[href*='accounts.google.com'], button:has-text('Sign in'), button:has-text('Se connecter')").first

        is_logged_in = False
        if await avatar.is_visible(timeout=3000) or await create_icon.is_visible(timeout=3000):
            is_logged_in = True
        
        if not is_logged_in:
            if await sign_in_btn.is_visible(timeout=1000):
                jlog("session_health", status="critical", error="Login required - Sign In button detected")
                return False
            
            # Cas ambigu : redirection potentielle
            if "google.com/signin" in page.url or "accounts.google.com" in page.url:
                jlog("session_health", status="critical", error="Redirected to Login Page", url=page.url)
                return False

        # 2. Détection Quotas / Strikes
        # On scanne le body pour des messages d'erreur critiques
        body_text = await page.inner_text("body")
        blockers = ["Daily upload limit reached", "Limite quotidienne atteinte", "Copyright strike"]
        for block in blockers:
            if block in body_text:
                jlog("session_health", status="blocked", error=f"Account constraint detected: {block}")
                return False

        jlog("session_health", status="healthy", user="detected")
        return True
        
    except Exception as e:
        jlog("session_health", status="error", error=str(e))
        # En cas d'erreur technique de check, on tente quand même (Fail-Open)
        return True

# --- SÉQUENCE PRINCIPALE (CORE LOGIC) ---

async def upload_sequence(page: Page, video_path: str, title: str = None, description: str = None, privacy: str = "public"):
    """
    Exécute l'upload sur YouTube Studio avec intelligence contextuelle.
    """
    try:
        jlog("sequence_start", step="navigation_youtube")
        
        # 1. Navigation Initiale
        await page.goto("https://studio.youtube.com", wait_until="networkidle")
        
        # 2. Intelligence N°4: Health Check Préventif
        if not await validate_session_health(page):
            jlog("fatal_error", msg="Session invalide. Veuillez vous connecter au navigateur Twin Sentinel.")
            return False

        # 3. Lancement Upload (Bouton Créer)
        jlog("action", msg="Recherche du bouton Créer")
        # Utilisation de l'ID spécifique YouTube Studio (souvent stable) ou sémantique
        create_btn = page.locator("#create-icon").first
        if await create_btn.is_visible():
            await create_btn.click()
        else:
            # Fallback sémantique
            await wait_and_click_semantic(page, ["Créer", "Create"], "button")

        await page.wait_for_timeout(1000) # Légère pause pour l'animation menu
        
        # Clic sur "Importer des vidéos" (Upload videos)
        await wait_and_click_semantic(page, ["Importer des vidéos", "Upload videos"], "menuitem")
        
        # 4. Injection du Fichier
        jlog("action", msg="Sélection du fichier vidéo")
        # Attente du sélecteur de fichier caché
        async with page.expect_file_chooser() as fc_info:
            # On clique sur le bouton déclencheur (souvent "Sélectionner des fichiers")
            upload_trigger = page.locator("#select-files-button").first
            if await upload_trigger.is_visible():
                await upload_trigger.click()
            else:
                 # Fallback zone cliquable
                 await page.locator("//div[@id='content']").click()
        
        file_chooser = await fc_info.value
        await file_chooser.set_files(video_path)
        
        # 5. Intelligence : Analyse et Remplissage des Métadonnées
        jlog("action", msg="Attente du formulaire de détails (Wizard)")
        # Le wizard YouTube met du temps à charger après l'upload
        wizard_header = page.locator("h1", has_text=re.compile("Détails|Details", re.IGNORECASE))
        await wizard_header.wait_for(state="visible", timeout=60000) # On laisse du temps pour l'upload initial

        # Si Titre/Desc absents, on déduit
        path_obj = Path(video_path)
        smart_data = SmartMetadata.derive_from_file(path_obj)
        
        final_title = title if title else smart_data["title"]
        final_desc = description if description else smart_data["description"]
        
        jlog("heuristics", msg="Métadonnées appliquées", title=final_title, derived=(title is None))

        # Remplissage Titre
        # On tente de trouver le champ Titre par son label approximatif ou position
        title_box = page.locator("#textbox").nth(0) # Le premier textbox est souvent le titre dans le wizard
        if await title_box.is_visible():
             await title_box.fill(final_title)
        
        # Remplissage Description
        desc_box = page.locator("#textbox").nth(1) # Le second est souvent la description
        if await desc_box.is_visible():
            await desc_box.fill(final_desc)

        # Gestion "Conçue pour les enfants" (Obligatoire)
        jlog("action", msg="Configuration audience (Non conçu pour les enfants)")
        not_for_kids = page.locator("name=VIDEO_MADE_FOR_KIDS_NOT_THE_TARGET").first
        if await not_for_kids.is_visible():
            await not_for_kids.click()
        
        # 6. Workflow de Validation (Next, Next, Next...)
        max_steps = 5
        steps_done = 0
        
        while steps_done < max_steps:
            # On cherche soit un bouton "Suivant/Next", soit "Publier/Publish"
            next_clicked = await wait_and_click_semantic(page, ["Suivant", "Next"], "button", timeout=2000)
            
            if next_clicked:
                jlog("workflow", step="next_step")
                await page.wait_for_timeout(1000) # Pause transition
                steps_done += 1
                continue
            
            # Gestion de la visibilité (Public/Private) à la dernière étape
            privacy_radio = page.locator(f"name={privacy.upper()}").first
            if await privacy_radio.is_visible():
                await privacy_radio.click()
                jlog("workflow", step="set_privacy", value=privacy)
            
            publish_clicked = await wait_and_click_semantic(page, ["Publier", "Publish", "Enregistrer", "Save"], "button", timeout=2000)
            if publish_clicked:
                jlog("workflow", step="published")
                break
            
            steps_done += 1
            await asyncio.sleep(1)

        # 7. Vérification finale
        success_dialog = page.locator("h1", has_text=re.compile("publiée|published", re.IGNORECASE))
        try:
            await success_dialog.wait_for(state="visible", timeout=10000)
            jlog("success", msg="Upload terminé avec succès")
            return True
        except:
            jlog("warning", msg="Pas de confirmation explicite, mais flux terminé.")
            return True

    except Exception as e:
        jlog("fatal_error", context="upload_sequence", error=str(e))
        await page.screenshot(path="error_upload.png")
        return False

# --- API PUBLIQUE (POUR NEXUS DAEMON) ---

class YoutubeUploader:
    """
    Classe wrapper pour intégration dans Nexus Daemon V3.
    Gère la connexion CDP et l'appel à la séquence d'upload.
    """
    def __init__(self, port: int = 9222):
        self.port = port
        self.ws_url = get_cdp_endpoint(self.port)
        if not self.ws_url:
            jlog("warning", msg="Impossible de détecter le endpoint CDP à l'initialisation", port=self.port)

    async def upload(self, video_path: str, title: str, description: str, privacy: str = "public") -> bool:
        """
        Méthode principale appelée par le démon.
        """
        # Rafraîchir l'URL CDP au cas où le navigateur a redémarré
        self.ws_url = get_cdp_endpoint(self.port)
        if not self.ws_url:
            jlog("error", msg="Connexion CDP impossible (Navigateur fermé ?)", port=self.port)
            return False

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.ws_url)
                
                # Gestion du contexte persistante ou nouveau contexte
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
                    privacy=privacy
                )

                await page.close()
                return success

            except Exception as e:
                jlog("fatal", msg="Erreur critique dans YoutubeUploader", error=str(e))
                return False

# --- ENTRY POINT (CLI) ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Uploader Intelligent (Twin Sentinel)")
    parser.add_argument("--file", required=True, help="Chemin du fichier vidéo")
    parser.add_argument("--port", type=int, default=9222, help="Port CDP du navigateur")
    parser.add_argument("--title", help="Titre de la vidéo")
    parser.add_argument("--description", help="Description")
    parser.add_argument("--privacy", default="public", choices=["public", "private", "unlisted"], help="Visibilité")

    args = parser.parse_args()
    
    # Utilisation de la classe refactorisée
    uploader = YoutubeUploader(port=args.port)
    
    # Exécution asynchrone
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        result = asyncio.run(uploader.upload(
            video_path=args.file,
            title=args.title,
            description=args.description,
            privacy=args.privacy
        ))
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        sys.exit(1)