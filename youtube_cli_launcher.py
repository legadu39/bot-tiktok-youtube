# -*- coding: utf-8 -*-
"""
youtube_cli_launcher.py -- Lanceur YouTube Studio avec profil Sandbox persistant.

Pattern identique a collect_cli.py :
  SandboxProfile + Fingerprint + launch_persistent_context + apply_stealth

Modes :
  --login            : ouvre YouTube Studio, attend connexion manuelle, persiste la session
  --dry-run (defaut) : valide le flux upload sans cliquer Publier
  --publish          : publication reelle (desactive --dry-run)

Usage :
    # Premiere execution -- connexion manuelle YouTube
    python youtube_cli_launcher.py --login

    # Dry-run validation
    python youtube_cli_launcher.py --dry-run --privacy private \
           --video "workspace\\nexus_final_20260510_171350_664414_26555c_V38_MASTER.mp4"

    # Override sandbox (optionnel -- sticky session par defaut)
    python youtube_cli_launcher.py --user-id yt_studio \
           --profile-base "C:/Nexus_Data" --dry-run ...
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# --- Config projet ---
try:
    from common import CONFIG as NEXUS_CONFIG
except ImportError:
    NEXUS_CONFIG = {}

# --- Composants Sandbox (pattern identique a collect_cli.py) ---
from gemini_headless.utils.sandbox_profile import SandboxProfile
from gemini_headless.utils.fingerprint import Fingerprint, build_launch_args
from gemini_headless.utils.stealth_injector import apply_stealth
from gemini_headless.cli.utils import get_browser_executable_path

from playwright.async_api import async_playwright

# --- Flux dry-run YouTube (import depuis test_youtube_upload) ---
from test_youtube_upload import run_upload_dry_run

# ── Constantes ────────────────────────────────────────────────────────────────

_SESSION_FILE = BASE / ".nexus_yt_session.json"

_DEFAULT_USER_ID      = "yt_studio"
_DEFAULT_PROFILE_BASE = str(NEXUS_CONFIG.get("SENTINEL_PROFILE", "C:/Nexus_Data"))

_VIDEO_DEFAULT = str(
    BASE / "workspace" / "nexus_final_20260510_171350_664414_26555c_V38_MASTER.mp4"
)

_TITLE_DEFAULT = (
    "Psychologie trading : pourquoi 90% perdent | Mindset #trading #shorts"
)
_DESC_DEFAULT = (
    "Le trading c'est pas une question de strategie -- c'est une question de tete.\n"
    "Maitrise tes emotions. Gere ton risque. Repete.\n\n"
    "#trading #mindset #propfirm #tradingpsychologie #shorts"
)

# Args stealth identiques a collect_cli.py
_STEALTH_EXTRA: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
    "--start-maximized",
    "--window-size=1920,1080",
    "--ignore-certificate-errors",
    "--ignore-ssl-errors",
    "--allow-insecure-localhost",
]

_IGNORE_DEFAULT_ARGS: list[str] = ["--enable-automation"]


# ── Session sticky ─────────────────────────────────────────────────────────────

def _load_session() -> dict:
    if _SESSION_FILE.exists():
        try:
            return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_session(user_id: str, profile_base: str) -> None:
    try:
        _SESSION_FILE.write_text(
            json.dumps(
                {"user_id": user_id, "profile_base": profile_base, "last_used": time.time()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Launcher principal ─────────────────────────────────────────────────────────

async def launch_youtube(
    user_id: str,
    profile_base: str,
    video_path: str,
    title: str,
    description: str,
    privacy: str,
    dry_run: bool,
    login_mode: bool,
) -> bool:

    # 1. Sandbox
    profile = SandboxProfile(user_id=user_id, base_dir=profile_base)
    profile.ensure_dirs()
    print(f"[launcher] Sandbox      : {profile.user_data_dir}")

    # 2. Fingerprint + chemin browser
    fp = Fingerprint.load_or_seed(profile)
    browser_path = get_browser_executable_path()
    if not browser_path:
        print("[launcher] [KO] Browser executable introuvable -- verifier l'installation Chrome")
        return False

    launch_args = build_launch_args(fp) + _STEALTH_EXTRA
    print(f"[launcher] Browser path : {browser_path}")

    # 3. Lancement persistent context (pattern collect_cli.py)
    async with async_playwright() as pw:
        print("[launcher] Lancement launch_persistent_context ...")
        context = await pw.chromium.launch_persistent_context(
            profile.user_data_dir,
            headless=False,
            executable_path=browser_path,
            args=launch_args,
            ignore_default_args=_IGNORE_DEFAULT_ARGS,
            viewport=None,
            timeout=120000,
            ignore_https_errors=True,
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await apply_stealth(page, fingerprint=fp.__dict__)

        # 4a. Mode login : ouvre YouTube Studio, attend fermeture manuelle
        if login_mode:
            print("[launcher] Mode login active.")
            print("           Connectez-vous a YouTube Studio dans la fenetre qui s'ouvre,")
            print("           puis fermez-la pour sauvegarder la session dans le sandbox.")
            await page.goto(
                "https://studio.youtube.com",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_event("close", timeout=0)
            await context.close()
            print("[launcher] Session YouTube persistee dans le sandbox.")
            return True

        # 4b. Dry-run / publication
        success = False
        try:
            success = await run_upload_dry_run(
                page,
                video_path=video_path,
                title=title,
                description=description,
                privacy=privacy,
                dry_run=dry_run,
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await context.close()

    return success


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    sticky = _load_session()

    ap = argparse.ArgumentParser(description="Lanceur YouTube Studio (Sandbox persistant)")
    ap.add_argument(
        "--user-id",
        default=sticky.get("user_id", _DEFAULT_USER_ID),
        help=f"ID sandbox YouTube (defaut: {sticky.get('user_id', _DEFAULT_USER_ID)})",
    )
    ap.add_argument(
        "--profile-base",
        default=sticky.get("profile_base", _DEFAULT_PROFILE_BASE),
        help=f"Dossier racine sandboxes (defaut: {sticky.get('profile_base', _DEFAULT_PROFILE_BASE)})",
    )
    ap.add_argument("--video",       default=_VIDEO_DEFAULT)
    ap.add_argument("--title",       default=_TITLE_DEFAULT)
    ap.add_argument("--description", default=_DESC_DEFAULT)
    ap.add_argument(
        "--privacy",
        default="private",
        choices=["public", "private", "unlisted"],
        help="Visibilite de la video (defaut: private)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Arret avant clic Publier (defaut: True)",
    )
    ap.add_argument(
        "--publish",
        action="store_true",
        help="Publication reelle (desactive --dry-run)",
    )
    ap.add_argument(
        "--login",
        action="store_true",
        help="Connexion manuelle : ouvre YouTube Studio et attend fermeture pour persister la session",
    )
    args = ap.parse_args()

    if args.publish:
        args.dry_run = False

    # Validation du fichier video (ignoree en mode login)
    video_path = Path(args.video)
    if not video_path.is_absolute():
        video_path = BASE / video_path
    if not args.login and not video_path.exists():
        print(f"[KO] Video introuvable : {video_path}")
        sys.exit(1)

    _save_session(args.user_id, args.profile_base)

    print("=" * 60)
    print("YOUTUBE CLI LAUNCHER")
    print("=" * 60)
    print(f"  user-id      : {args.user_id}")
    print(f"  profile-base : {args.profile_base}")
    print(f"  video        : {video_path}")
    print(f"  privacy      : {args.privacy}")
    print(f"  dry-run      : {args.dry_run}")
    print(f"  login mode   : {args.login}")
    print("=" * 60)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    success = asyncio.run(
        launch_youtube(
            user_id=args.user_id,
            profile_base=args.profile_base,
            video_path=str(video_path.resolve()),
            title=args.title,
            description=args.description,
            privacy=args.privacy,
            dry_run=args.dry_run,
            login_mode=args.login,
        )
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
