# BACKLOG.md — nexus-auto-v3
> Généré le 2026-04-15 | Version 3.2.0

## Légende
- **P0** : Bloquant — sans ça rien ne tourne
- **P1** : Nécessaire pour une vidéo complète de bout en bout
- **P2** : Amélioration de qualité ou robustesse
- **P3** : Nice-to-have, optimisation

---

## P0 — Bloquant

| Priorité | Tâche | Fichier concerné | Taille | Dépend de |
|----------|-------|-----------------|--------|-----------|
| P0 | **Sécuriser les clés API** — migrer `config.yaml` vers `.env` ou vault chiffré ; ajouter `config.yaml` à `.gitignore` pour éviter une fuite publique | `config.yaml`, `.gitignore`, `common.py` | S | — |
| P0 | **Vérifier la présence de FFmpeg** dans le PATH — `nexus_daemon.py` fait un pre-flight check mais n'installe pas FFmpeg si absent | `nexus_daemon.py`, `common.py` | S | FFmpeg binaire |
| P0 | **Vérifier la clé ElevenLabs** dans `config.yaml` — `tts_manager.py` ne démarre pas sans clé valide ; le mode test (silence synthétique) doit être explicitement activé | `tools/tts_manager.py`, `config.yaml` | S | ElevenLabs API |
| P0 | **Analyser `video_referencement.mp4`** manuellement pour valider les paramètres visuels exacts (police, taille, position, couleurs, rythme) utilisés dans `burner.py` / `graphics.py` | `video_referencement.mp4`, `tools/burner.py`, `tools/graphics.py` | M | Lecture vidéo |

---

## P1 — Nécessaire pour une vidéo complète

| Priorité | Tâche | Fichier concerné | Taille | Dépend de |
|----------|-------|-----------------|--------|-----------|
| P1 | **Valider le pipeline end-to-end** — exécuter `nexus_daemon.py` en mode test avec `TEST_MODE=true` et vérifier qu'une vidéo est générée et placée dans `OUTPUT_VIDEO/` | `nexus_daemon.py`, `nexus_brain.py` | M | P0 complet |
| P1 | **Corriger `.gitignore`** — ajouter `config.yaml`, `nexus_system.log`, `BUFFER/`, `REJECTED/`, `assets/cache/`, `*.mp4` (sauf référence), `*.json` de session | `.gitignore` | S | — |
| P1 | **Ajouter `requirements.txt`** (ou `poetry.lock`) pour reproductibilité — actuellement seul `pyproject.toml` est présent sans lockfile visible | `pyproject.toml`, nouveau `requirements.txt` | S | — |
| P1 | **Documenter le lancement** — README minimal ou section dans `CLAUDE.md` avec les commandes exactes pour démarrer le daemon, collecter des données et lancer une génération manuelle | `CLAUDE.md`, nouveau `README.md` | M | — |
| P1 | **Vérifier la compatibilité MoviePy** — `pyproject.toml` spécifie `moviepy` mais la version (1.x vs 2.x) change l'API ; `compositor.py` doit utiliser la bonne version | `tools/compositor.py`, `pyproject.toml` | S | — |
| P1 | **Valider le TTS en mode test** — vérifier que `tts_manager.py` génère bien du silence synthétique calculé (`~13 chars/s`) sans appel API quand `TEST_MODE=true` | `tools/tts_manager.py` | S | P0 ElevenLabs |
| P1 | **Tester l'upload TikTok** — exécuter `nexus_arms.py` avec une vidéo de test pour valider le fuzzy selector CDP contre l'UI TikTok actuelle | `nexus_arms.py`, `tools/tt_uploader.py` | M | Vidéo générée |
| P1 | **Tester l'upload YouTube** — même vérification pour `yt_uploader.py` avec Playwright | `tools/yt_uploader.py` | M | Vidéo générée |

---

## P2 — Qualité et robustesse

| Priorité | Tâche | Fichier concerné | Taille | Dépend de |
|----------|-------|-----------------|--------|-----------|
| P2 | **Écrire des tests unitaires** pour `tools/physics.py`, `tools/easing.py`, `tools/timeline.py` — noyau critique sans couverture | `tests/` (à créer) | M | — |
| P2 | **Écrire des tests pour `burner.py`** — vérifier que les timestamps de synchronisation texte/audio sont corrects avec des fixtures connues | `tests/test_burner.py` | L | pytest, PIL |
| P2 | **Valider la gestion des erreurs ElevenLabs** — timeout, quota dépassé, voice_id invalide ; s'assurer que le fallback `pyttsx3` / silence synthétique se déclenche correctement | `tools/tts_manager.py`, `nexus_brain.py` | M | — |
| P2 | **Ajouter monitoring de la qualité vidéo** — vérifier après rendu que la vidéo est bien 1080×1920, 30fps, durée 30–90s avant upload | `common.py` (VideoValidator), `nexus_brain.py` | S | FFprobe |
| P2 | **Rotation des profils d'identité** — s'assurer que le sélecteur de profil (CLASH/INSIDER/MENTOR/NEWS) évite la répétition sur des runs consécutifs | `prompts/templates.py`, `nexus_brain.py` | S | `history_topics.json` |
| P2 | **Nettoyage automatique du cache TTS** — `assets/cache/tts/` grossit indéfiniment ; ajouter une purge des fichiers > 30 jours | `tools/tts_manager.py` | S | — |
| P2 | **Documenter `fallback.py`** — les templates hardcodés ne couvrent que quelques sujets ; étendre pour les 4 profils d'identité | `fallback.py` | M | `prompts/templates.py` |
| P2 | **Vérifier `tools/vfx.py` et `tools/context.py`** — fichiers incomplets détectés ; documenter ou compléter | `tools/vfx.py`, `tools/context.py` | S | — |

---

## P3 — Nice-to-have / Optimisation

| Priorité | Tâche | Fichier concerné | Taille | Dépend de |
|----------|-------|-----------------|--------|-----------|
| P3 | **Ajouter un Makefile** avec cibles : `make run`, `make test`, `make clean`, `make generate`, `make upload` | `Makefile` (à créer) | S | — |
| P3 | **Dashboard de monitoring** — visualiser l'état du daemon, les vidéos générées, les uploads, les erreurs en temps réel (ex: simple HTML ou Streamlit) | Nouveau fichier | L | `nexus_system.log` |
| P3 | **Variété des B-rolls** — enrichir le vault avec de vraies illustrations SVG / PNG catégorisées par thème (PropFirm, trading, mindset) | `assets/vault/`, `tools/asset_vault.py` | L | — |
| P3 | **Sous-titres bilingues** — option pour générer des vidéos EN + FR pour cibler les deux audiences | `prompts/templates.py`, `tools/burner.py` | L | P1 complet |
| P3 | **Optimisation rendu GPU** — `burner.py` utilise PIL/CPU pour le rendu frame-by-frame ; explorer MoviePy avec accélération numpy ou CUDA (Pillow-SIMD) | `tools/burner.py`, `tools/compositor.py` | L | P2 tests |
| P3 | **Scheduler cron** — remplacer la surveillance manuelle par un cron job ou APScheduler intégré à `nexus_daemon.py` | `nexus_daemon.py` | M | P1 complet |
| P3 | **Intégration WhisperX** — optionnel pour forcer l'alignement parole/texte si ElevenLabs ne renvoie pas de timestamps précis | `tools/tts_manager.py`, `nexus_brain.py` | L | whisperx lib |
| P3 | **Publication Instagram Reels** — étendre `nexus_arms.py` avec un uploader Instagram (même format 9:16) | `nexus_arms.py`, `tools/` (nouveau) | L | P1 complet |
