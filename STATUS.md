# STATUS.md — Analyse des fichiers du projet nexus-auto-v3
> Généré le 2026-04-15 | Version 3.2.0

| Fichier | Statut | Dépendances | Ce qui manque |
|---------|--------|-------------|---------------|
| **RACINE** | | | |
| `nexus_brain.py` | ✅ complet | `tools/graphics.py`, `tools/burner.py`, `tools/tts_manager.py`, `tools/compositor.py`, `tools/animator.py`, `tools/timeline.py`, `common.py`, `prompts/templates.py`, ElevenLabs API, FFmpeg | FIX 2026-04-15 : scène 0 exclue des broll_indices. FIX 2026-04-16 : `_DARK_TRIGGER_WORDS` + `_inject_dark_tags()` → injection `[DARK]` sur 2 mots forts par script (run_da_mode + run_daemon). FIX 2026-04-17 : collecte `dark_scene_intervals` depuis la timeline scène AVANT humanisation (re.sub strippait les tags) → passage explicite à `burn_subtitles()` |
| `nexus_arms.py` | ✅ complet | `tools/tt_uploader.py`, `tools/yt_uploader.py`, `common.py`, `HOLDING/pacer_state.json` | — |
| `nexus_daemon.py` | ✅ complet | `nexus_brain.py`, `nexus_arms.py`, `common.py`, FFmpeg (pre-flight) | — |
| `common.py` | ✅ complet | `config.yaml`, `pyproject.toml`, FFprobe | — |
| `fallback.py` | 🔄 partiel | Aucune dépendance externe | Templates hardcodés minimalistes, pas de génération variée |
| `collect_cli.py` | ✅ complet | `gemini_headless/`, Playwright, `config.yaml` | — |
| `timeout_manager.py` | ✅ complet | `common.py`, `temp_signals/` | — |
| `config.yaml` | ⚠️ ALERTE | — | **CLÉS API EXPOSÉES EN CLAIR** — migrer vers .env ou vault |
| `config.example.yaml` | ✅ complet | — | — |
| `pyproject.toml` | ✅ complet | — | MoviePy borné à `<2.0` (2026-04-15) — 5 fichiers utilisent API 1.x (`moviepy.editor`, `.set_fps`, `.volumex`, `.subclip`) |
| `.gitignore` | ✅ complet | — | Complété 2026-04-15 : `BUFFER/`, `REJECTED/`, `OUTPUT_VIDEO/`, `assets/cache/`, `nexus_system.log`, `*.mp4` + `!video_referencement.mp4`, JSONs de session |
| **TOOLS/** | | | |
| `tools/graphics.py` | ✅ complet | PIL/Pillow, `fonts/Inter-Regular.ttf` *(police principale)*, `fonts/Inter-Light.ttf`, `fonts/Inter-SemiBold.ttf`, `fonts/Inter-Bold.ttf`, `fonts/Inter-ExtraBold.ttf`, numpy | FIX 2026-04-15 : logo TikTok refait (note 'd' + trait vertical + glitch 3px) ; search pill → bordure bicolore cyan/rouge + mini logo + Inter-Regular |
| `tools/burner.py` | ✅ complet | `tools/graphics.py`, `tools/motion_profiles.py`, `tools/physics.py`, PIL, numpy | FIX 2026-04-16 : SparkleEngine → ★ statiques #7B2FD9 ±80px ; `_get_inversion_bg_color` noir pour toutes sauf CTA ; `_is_sparkle_inversion` toutes inversions noires. FIX 2026-04-17 : `burn_subtitles()` accepte `dark_scene_intervals` (List[Tuple[float,float]]) — remplace la détection word-level inopérante par injection directe des intervalles pré-calculés |
| `tools/tts_manager.py` | ✅ complet | ElevenLabs API, aiohttp, `assets/cache/tts/` | Voix hardcodées (4 profils) — OK pour l'usage actuel |
| `tools/motion_profiles.py` | ✅ complet | `tools/physics.py`, numpy | — |
| `tools/physics.py` | ✅ complet | numpy | — |
| `tools/animator.py` | ✅ complet | `tools/motion_profiles.py`, `tools/physics.py`, PIL | — |
| `tools/scene_animator.py` | ✅ complet | `tools/animator.py`, `tools/effects.py`, `tools/graphics.py` | — |
| `tools/compositor.py` | ✅ complet | `tools/burner.py`, `tools/graphics.py`, MoviePy, FFmpeg | — |
| `tools/timeline.py` | ✅ complet | numpy | — |
| `tools/text_engine.py` | ✅ complet | PIL, `fonts/` | — |
| `tools/effects.py` | ✅ complet | PIL, numpy | — |
| `tools/fx_engine.py` | ✅ complet | `tools/effects.py`, numpy | — |
| `tools/easing.py` | ✅ complet | numpy | — |
| `tools/layout.py` | ✅ complet | `tools/text_engine.py` | — |
| `tools/asset_vault.py` | ✅ complet | `assets/vault/`, `evergreen_vault/` | — |
| `tools/config.py` | ✅ complet | `common.py`, `config.yaml` | — (profils de police configurés) |
| `tools/context.py` | 🔄 partiel | `tools/config.py` | Contenu minimal — wrapper de contexte |
| `tools/vfx.py` | 🔄 partiel | PIL, numpy | Fonctions VFX supplémentaires non documentées |
| `tools/tt_uploader.py` | ✅ complet | `tools/tt_dom.py`, `tools/tt_cdp.py`, `tools/tt_runner.py`, `tools/tt_constants.py`, `tools/tt_utils.py`, Playwright | — (fuzzy selector logic) |
| `tools/tt_dom.py` | ✅ complet | Playwright, `tools/tt_constants.py` | — (cache sélecteurs 7 jours) |
| `tools/tt_cdp.py` | ✅ complet | websockets (SSL), Playwright | — ("Ghost Socket" Edition) |
| `tools/tt_runner.py` | ✅ complet | `tools/tt_uploader.py`, `tools/tt_dom.py` | — |
| `tools/tt_constants.py` | ✅ complet | — | — |
| `tools/tt_utils.py` | ✅ complet | `tools/tt_constants.py` | — |
| `tools/yt_uploader.py` | ✅ complet | Playwright, `common.py` | — |
| **GEMINI_HEADLESS/** | | | |
| `gemini_headless/__init__.py` | ✅ complet | — | — |
| `gemini_headless/collect/orchestrator.py` | ✅ complet | Tous les producers, `filters/cleaner.py`, `monitors/activity_monitor.py` | — (48K, architecture multi-producteur) |
| `gemini_headless/collect/producers/be.py` | ✅ complet | aiohttp, `collect/utils/` | — |
| `gemini_headless/collect/producers/dom.py` | ✅ complet | Playwright, `collect/utils/` | — |
| `gemini_headless/collect/producers/sse.py` | ✅ complet | aiohttp | — |
| `gemini_headless/collect/producers/ws.py` | ✅ complet | websockets | — |
| `gemini_headless/collect/filters/cleaner.py` | ✅ complet | — | — |
| `gemini_headless/collect/monitors/activity_monitor.py` | ✅ complet | — | — |
| `gemini_headless/connectors/gemini_connector.py` | ✅ complet | Playwright, `connectors/ui_interaction.py`, `connectors/timing.py` | — |
| `gemini_headless/connectors/ui_interaction.py` | ✅ complet | Playwright, `utils/consent_detector.py` | — |
| `gemini_headless/connectors/main.py` | ✅ complet | `connectors/gemini_connector.py` | — |
| `gemini_headless/connectors/cdp_manager.py` | ✅ complet | Playwright CDP | — |
| `gemini_headless/connectors/cdp_multiattach.py` | ✅ complet | `connectors/cdp_manager.py` | — |
| `gemini_headless/connectors/timing.py` | ✅ complet | — | — |
| `gemini_headless/connectors/cache.py` | ✅ complet | — | — |
| `gemini_headless/connectors/config.py` | ✅ complet | `config.yaml` | — |
| `gemini_headless/connectors/logger.py` | ✅ complet | — | — |
| `gemini_headless/utils/fingerprint.py` | ✅ complet | — | — |
| `gemini_headless/utils/session_guardian.py` | ✅ complet | — | — |
| `gemini_headless/utils/stealth_injector.py` | ✅ complet | Playwright CDP | — |
| `gemini_headless/utils/consent_detector.py` | ✅ complet | Playwright | — |
| `gemini_headless/utils/sandbox_profile.py` | ✅ complet | — | — |
| `gemini_headless/cli/` | 🔄 partiel | `common.py` | CLI helpers — fonctionnels mais non documentés |
| **PROMPTS/** | | | |
| `prompts/templates.py` | ✅ complet | — | — (4 profils: CLASH/INSIDER/MENTOR/NEWS, directives BROLL/ICON/PRICE) |
| **ASSETS & DATA** | | | |
| `fonts/Inter-ExtraBold.ttf` | ✅ complet | — | — |
| `fonts/Inter-SemiBold.ttf` | ✅ complet | — | — |
| `video_referencement.mp4` | ✅ analysé | — | Paramètres extraits → section "Format vidéo de référence" dans CLAUDE.md |
| `assets/cache/tts/` | ✅ complet | — | Cache opérationnel (~25 Mo) |
| `assets_vault/sfx/synthetic_click.wav` | ✅ complet | — | — |
| `healing_history.json` | ✅ complet | — | — |
| `history_topics.json` | ✅ complet | — | Contient des sorties LLM verbosées en cache |
| `HOLDING/pacer_state.json` | ✅ complet | — | — |
| **ABSENTS / MANQUANTS** | | | |
| `.env` | ❌ absent | — | Devrait contenir les clés API (sécurité) |
| `requirements.txt` | ✅ complet | `pyproject.toml` | Généré 2026-04-15 via `pip freeze` — 167 packages, Python 3.12.10 |
| `Makefile` | ❌ absent | — | Serait utile pour les commandes courantes |
| `tests/` | ❌ absent | — | Aucun test unitaire ni d'intégration |
| `STATUS.md` | ❌ absent (créé) | — | Ce fichier |
| `BACKLOG.md` | ❌ absent (créé) | — | Fichier suivant |
| `CLAUDE.md` | ❌ absent (créé) | — | Fichier suivant |
