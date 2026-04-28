#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test standalone upload YouTube Shorts — privacy=private (dry-run safe).
"""
import sys
import os
import asyncio
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

VIDEO_PATH  = ROOT / "workspace" / "nexus_final_20260420_203111_602251_0266dd_V38_MASTER.mp4"
TITLE       = "Ma stratégie SMC expliquée 🎯 #trading #smc #shorts"
DESCRIPTION = "Je t'explique comment j'analyse le marché chaque matin.\n\n#trading #smc #propfirm #stratégie #forex"
PRIVACY     = "private"
PORT        = 9222

def step(msg):
    print(f"\n{'='*60}\n[STEP] {msg}\n{'='*60}", flush=True)

async def main():
    step("Vérification fichier vidéo")
    if not VIDEO_PATH.exists():
        print(f"ERREUR: {VIDEO_PATH} introuvable")
        sys.exit(1)
    size_mb = VIDEO_PATH.stat().st_size / 1_048_576
    print(f"OK — {VIDEO_PATH.name} ({size_mb:.1f} Mo)")

    step("Import YoutubeUploader")
    from tools.yt_uploader import YoutubeUploader, upload_sequence, validate_session_health
    print("OK")

    step(f"Connexion CDP port {PORT}")
    from tt_utils import get_cdp_endpoint
    ws_url = get_cdp_endpoint(PORT)
    if not ws_url:
        print(f"ERREUR: CDP port {PORT} inaccessible")
        sys.exit(1)
    print(f"ws_url: {ws_url}")

    step("Playwright CDP connect + upload")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(ws_url)
        print(f"Contextes existants: {len(browser.contexts)}")

        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = await browser.new_context()

        page = await context.new_page()
        print(f"Nouvelle page ouverte")

        step("Health check session YouTube")
        healthy = await validate_session_health(page)
        print(f"Session healthy: {healthy}")
        if not healthy:
            print("ERREUR: session YouTube invalide — connecte-toi à studio.youtube.com dans Chrome")
            await page.close()
            sys.exit(1)

        step(f"Upload sequence (privacy={PRIVACY})")
        print(f"  Titre   : {TITLE}")
        print(f"  Desc    : {DESCRIPTION[:60]}...")
        print(f"  Privacy : {PRIVACY}")

        success = await upload_sequence(
            page,
            str(VIDEO_PATH),
            title=TITLE,
            description=DESCRIPTION,
            privacy=PRIVACY,
        )

        try:
            await page.close()
        except Exception:
            pass

    if success:
        print("\n" + "="*60)
        print("✅ UPLOAD YOUTUBE TERMINÉ (privacy=private)")
        print("   Vérifie YouTube Studio → Vidéos → Privées")
        print("="*60)
    else:
        print("❌ Upload YouTube échoué")
        sys.exit(1)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
