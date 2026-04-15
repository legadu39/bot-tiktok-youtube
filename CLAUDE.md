# CLAUDE.md — nexus-auto-v3
> Référence technique du projet | Mise à jour : 2026-04-15

---

## 1. Stack technique confirmée

| Composant | Outil réel | Notes |
|-----------|-----------|-------|
| Language | Python 3.10+ | `pyproject.toml` — `nexus-auto-v3` v3.2.0 |
| Génération script | Gemini API (headless Playwright) | Via `gemini_headless/` — interaction navigateur CDP |
| Génération script (fallback) | `fallback.py` | Templates hardcodés, sans API |
| TTS audio | ElevenLabs API | `tools/tts_manager.py` — 4 voix : urgent/b2b/narrative/calm |
| TTS fallback | Silence synthétique (~13 chars/s) | Mode `TEST_MODE=true` |
| Rendu vidéo | PIL/Pillow + MoviePy + FFmpeg | Frame-by-frame PIL → assemblage FFmpeg |
| Synchronisation texte/audio | Timestamps ElevenLabs + custom sync | Pas de WhisperX — alignement via réponse API |
| Physique animation | Spring physics custom | `tools/physics.py` — k=900, ζ=0.50 |
| Upload TikTok | CDP WebSocket + Playwright fuzzy selectors | `tools/tt_uploader.py` / `tt_cdp.py` |
| Upload YouTube | Playwright (ARIA semantic navigation) | `tools/yt_uploader.py` |
| Orchestration | `nexus_daemon.py` → processus séparés | Brain + Arms comme sous-processus surveillés |
| Config | `config.yaml` + `common.py` (env var overrides) | ⚠️ Clés API en clair — migrer vers `.env` |
| Profils de prompt | `prompts/templates.py` | 4 identités : CLASH / INSIDER / MENTOR / NEWS |
| Rate limiting uploads | `PublicationPacer` dans `nexus_arms.py` | 5 uploads/jour, intervalle min 3h |
| Circuit breaker | `common.py` `CircuitBreaker` | 3 échecs max, reset 1800s |
| Anti-détection | `gemini_headless/utils/stealth_injector.py` | navigator.webdriver spoofing, fingerprint Chrome |

---

## 2. Architecture des fichiers

```
nexus-auto-v3/
│
├── nexus_daemon.py          # Orchestrateur principal — lance Brain + Arms, surveillance process
├── nexus_brain.py           # Pipeline vidéo complet (90K) — script → TTS → rendu → OUTPUT_VIDEO/
├── nexus_arms.py            # Publication — lit OUTPUT_VIDEO/, upload TikTok + YouTube
├── nexus_system.log         # Logs d'exécution (rotatif)
│
├── common.py                # Config chargement, CircuitBreaker, VideoValidator (FFprobe)
├── fallback.py              # Génération d'urgence sans API (templates hardcodés)
├── collect_cli.py           # CLI de collecte de données via Gemini headless
├── timeout_manager.py       # Sync timeouts cross-process, heartbeat, adaptive multiplier
│
├── config.yaml              # ⚠️ Config active avec CLÉS API — ne pas committer
├── config.example.yaml      # Template safe sans secrets
├── pyproject.toml           # Dépendances Poetry
│
├── prompts/
│   └── templates.py         # 4 profils d'identité + directives visuelles (BROLL/ICON/PRICE/REPEATER)
│
├── tools/                   # Moteur de rendu + upload
│   ├── graphics.py          # Rendu PIL, CapHeightNormalizer, B-roll procedural, CTA cards
│   ├── burner.py            # Moteur sous-titres animés — spring physics, sparkle, zoom
│   ├── tts_manager.py       # ElevenLabs API, cache hash-based, 4 voix
│   ├── compositor.py        # Assemblage final PIL → MoviePy → FFmpeg
│   ├── animator.py          # Animation de scène
│   ├── scene_animator.py    # Orchestration scènes
│   ├── motion_profiles.py   # Profils cinétiques sémantiques par classe de mot
│   ├── physics.py           # Simulation spring physics (k, ζ, masse)
│   ├── timeline.py          # Gestion temporelle des scènes
│   ├── text_engine.py       # Mise en page typographique
│   ├── effects.py           # Effets visuels (blur, glow, overlay)
│   ├── fx_engine.py         # Pipeline effets
│   ├── easing.py            # Fonctions d'interpolation
│   ├── layout.py            # Calcul de layout
│   ├── asset_vault.py       # Gestion des assets (vault + evergreen)
│   ├── config.py            # Config outils + profils de police
│   ├── context.py           # Wrapper contexte (minimal)
│   ├── vfx.py               # VFX supplémentaires (partiel)
│   ├── tt_uploader.py       # TikTok upload — fuzzy selectors CDP
│   ├── tt_dom.py            # DOM TikTok — cache sélecteurs 7j, LatencyContext
│   ├── tt_cdp.py            # CDP WebSocket SSL ("Ghost Socket")
│   ├── tt_runner.py         # State machine upload TikTok
│   ├── tt_constants.py      # Constantes TikTok
│   ├── tt_utils.py          # Utilitaires TikTok
│   └── yt_uploader.py       # YouTube upload — Playwright ARIA
│
├── gemini_headless/         # Librairie d'interaction Gemini via navigateur headless
│   ├── collect/             # Orchestrateur multi-producteur (SSE, WS, BE, DOM)
│   ├── connectors/          # Connecteurs Gemini + CDP + UI interaction
│   └── utils/               # Fingerprint, stealth, session guardian
│
├── fonts/
│   ├── Inter-ExtraBold.ttf  # Police principale (titres, mots-clés)
│   └── Inter-SemiBold.ttf   # Police secondaire (corps de texte)
│
├── assets/
│   ├── cache/tts/           # Cache audio TTS (~25 Mo, hash-based)
│   ├── placeholders/        # Images de fallback
│   ├── sfx/                 # Effets sonores
│   └── vault/storage/       # Assets visuels permanents
│
├── assets_vault/sfx/        # synthetic_click.wav
├── evergreen_vault/used/    # Assets réutilisables
│
├── INPUT_VIDEO/             # Vidéos d'entrée (pour traitement futur)
├── OUTPUT_VIDEO/            # Vidéos finales générées — lues par nexus_arms.py
├── BUFFER/                  # Données temporaires inter-processus
├── HOLDING/                 # pacer_state.json (régulation de publication)
├── REJECTED/                # Éléments rejetés avec timestamps
├── ARCHIVE/                 # Archives
│
├── video_referencement.mp4  # ← VIDÉO DE RÉFÉRENCE (1.4 Mo) — analyser manuellement
│
├── healing_history.json     # Mémoire auto-réparation
├── history_topics.json      # Historique sujets générés (anti-répétition)
├── HOLDING/pacer_state.json # État du rate limiter publication
│
├── STATUS.md                # ← Analyse fichiers (ce projet)
├── BACKLOG.md               # ← Tâches prioritisées
└── CLAUDE.md                # ← Ce fichier
```

---

## 3. Format vidéo cible

### Paramètres confirmés (déduits du code — `video_referencement.mp4` à analyser manuellement)

| Paramètre | Valeur | Source |
|-----------|--------|--------|
| Résolution | **1080 × 1920** (9:16 vertical) | `tools/config.py`, `nexus_brain.py` |
| Framerate | **30 fps** | `tools/compositor.py` |
| Durée cible | **30 – 90 secondes** | `common.py` VideoValidator |
| Scènes cibles | **42 – 55 scènes** pour 40–50s | `prompts/templates.py` |
| Format de sortie | MP4 (H.264) | FFmpeg final render |
| Fond | Blanc ou noir uni selon profil | `tools/graphics.py` palettes |
| Police principale | **Inter ExtraBold** | `fonts/Inter-ExtraBold.ttf` |
| Police secondaire | **Inter SemiBold** | `fonts/Inter-SemiBold.ttf` |
| Style texte | Kinetic Text — mot par mot synchronisé | `tools/burner.py` |
| Position texte | Centre vertical, marges latérales adaptatives | `tools/layout.py`, `tools/graphics.py` |
| Animation | Spring physics (k=900, ζ=0.50) + zoom/sparkle | `tools/physics.py`, `tools/burner.py` |
| B-rolls | Cartes procédurales (5 palettes, dégradés diagonaux) | `tools/graphics.py` |
| End screen | CTA card avec handle @username | `tools/graphics.py` |
| Audio | ElevenLabs voix off synchronisée | `tools/tts_manager.py` |
| Langue | Français (contenu trading/PropFirm/mindset) | `prompts/templates.py` |

### Profils d'identité
- **CLASH** — ton provocateur, confrontation, audience jeune
- **INSIDER** — conseils exclusifs, secrets du marché
- **MENTOR** — pédagogique, bienveillant, étapes claires
- **NEWS** — actualité marché, ton factuel et urgent

### Directives visuelles dans les prompts
- `[BROLL: description]` → génère une carte B-roll procédurale
- `[ICON: nom]` → icône SVG ou placeholder
- `[PRICE: montant]` → affichage chiffre stylisé
- `[REPEATER: texte]` → effet répétition de mot

---

## 4. Conventions de code

### Généralités
- Python 3.10+ — utiliser les `match/case`, `f-strings`, `dataclasses`
- Pas de type hints obligatoires dans le code existant — en ajouter uniquement sur les nouvelles fonctions
- Commentaires en **français** (cohérent avec le reste du projet)
- Nommage : `snake_case` pour fonctions/variables, `PascalCase` pour classes

### Configuration
- Toute valeur de config doit passer par `common.py` → `load_config()`
- Ne jamais hardcoder de clés API dans le code — toujours lire depuis config
- Les overrides env var sont supportés dans `common.py` (priorité : env var > config.yaml)

### Fichiers de travail
- `STATUS.md` : mise à jour par `str_replace` ligne par ligne — **jamais réécrire en entier**
- `BACKLOG.md` : idem — `str_replace` ciblé sur la ligne/tâche concernée
- `CLAUDE.md` : idem — sections modifiées par `str_replace` ciblé

### Pipeline vidéo
- Toute modification de timing dans `burner.py` doit être testée avec une fixture audio connue
- Les profils de motion dans `motion_profiles.py` sont les seules sources de vérité pour les paramètres d'animation — ne pas hardcoder dans `burner.py`
- Le rendu est CPU-bound (PIL) — éviter les boucles imbriquées inutiles sur les frames

### Uploads
- Ne jamais modifier `tt_constants.py` sans tester contre l'UI TikTok actuelle (les sélecteurs changent)
- Le `PublicationPacer` dans `nexus_arms.py` doit toujours être respecté — ne pas bypass le rate limiting
- `OUTPUT_VIDEO/` est le seul répertoire que `nexus_arms.py` surveille — toujours y déposer les vidéos finales

### Sécurité
- `config.yaml` ne doit **jamais** être commité — ajouter à `.gitignore`
- Utiliser `config.example.yaml` comme template dans les PR/docs
- Les clés API ne doivent jamais apparaître dans les logs (`nexus_system.log`)

---

## 5. État du projet

| Composant | État | Notes |
|-----------|------|-------|
| Pipeline génération vidéo | ✅ Terminé | `nexus_brain.py` V38 stable |
| Moteur de rendu (burner + graphics) | ✅ Terminé | Spring physics, cap-height, B-rolls |
| TTS ElevenLabs | ✅ Terminé | Cache hash, 4 voix, mode test |
| Upload TikTok | ✅ Terminé | Fuzzy CDP, auto-retry |
| Upload YouTube | ✅ Terminé | Playwright ARIA |
| Orchestration daemon | ✅ Terminé | Multi-process, heartbeat, circuit breaker |
| Collecte Gemini headless | ✅ Terminé | Multi-producteur, healing memory |
| Sécurité config | ❌ Manquant | Clés API exposées dans `config.yaml` |
| Tests unitaires | ❌ Manquant | Aucun test dans le projet |
| Documentation | 🔄 En cours | STATUS/BACKLOG/CLAUDE en création |
| `video_referencement.mp4` analysée | 🔄 En cours | Présente mais pas encore analysée manuellement |

---

## Format vidéo de référence — Paramètres extraits
> ⚠️ VÉRITÉ DE RÉFÉRENCE — déduits par analyse pixel frame-by-frame de `video_referencement.mp4`
> Toute décision de rendu doit s'aligner sur ces valeurs mesurées.

### Specs techniques de la vidéo de référence

| Paramètre | Valeur mesurée |
|-----------|---------------|
| Résolution réelle | **576 × 1024** (référence basse-résolution) |
| Ratio | **9:16** ✅ confirmé (`display_aspect_ratio: 9:16`) |
| FPS | **30 fps** |
| Durée totale | **44.03 secondes** |
| Codec | H.264 High Profile, AAC stereo 44100 Hz |
| Résolution cible production | **1080 × 1920** (facteur de scale : ×1.875 vs référence) |

### Couleurs exactes (mesures pixel)

| Élément | Couleur | Valeur hex | Source mesure |
|---------|---------|-----------|---------------|
| Fond | Blanc pur | `#FFFFFF` | Coin haut-gauche, RGB(255,255,255) constant |
| Texte normal | Noir quasi-pur | `#000000` / `#030303` | Pixel le plus sombre sur 10 frames |
| Texte gradient accent | Violet → or | avg RGB(187,154,196) → dégradé vers jaune/or | Frame t=3s "marché." |
| Texte prix/counter | Gris clair | `#B8B8B8` → `#C2C2C2` | Frame t=6s "$ 008", avg RGB(194,194,194) |
| Icône flat | Noir pur | `#000000` | Frame t=18s (œil) |
| Icône animée | Bleu | `#455CA2` | Frame t=22s (cercle) |
| Fond REPEATER | Gris moyen | `#838383` | Frame t=28s (emoji tiling) |
| End screen fond | Bleu nuit quasi-noir | `#0D1019` | Frames t=41-44s |

### Typographie

| Paramètre | Valeur mesurée | Calcul |
|-----------|---------------|--------|
| Police | **Sans-serif regular** (Inter-like, Double-story 'a') | Analyse forme des glyphes |
| Poids | **Regular / Light** (strokes fins) | ⚠️ PAS ExtraBold — différent des .ttf en dossier `fonts/` |
| Taille à 576px | **~36px** | bbox glyphe 27-30px ÷ ratio ascendeur Inter (0.8) |
| Taille à 1080px (cible) | **~68px** | 36 × 1.875 (facteur de scale) |
| Couleur | `#000000` | Mesure directe |
| Effets | Aucun (ni ombre, ni outline, ni glow) | Pixels de bord = anti-alias seulement |

### Position du texte

| Paramètre | Valeur mesurée |
|-----------|---------------|
| Ancre horizontale | **Centre exact — x = 50%** (287-290 / 576 px, constant sur toutes les frames) |
| Ancre verticale | **Centre exact — y = 50%** (509-511 / 1024 px, constant sur toutes les frames) |
| Alignement | **Centre / Centre** (le mot tourne autour du point central absolu) |
| Coordonnées cible 1080×1920 | **x = 540, y = 960** |
| Zone de texte max (largeur) | ~400px à 576 → **~750px à 1080** (marges ≈ 15% de chaque côté) |

### Rythme de synchronisation

| Paramètre | Valeur mesurée |
|-----------|---------------|
| Changements de contenu / seconde | **~3.5 transitions/s** (mesure à 5fps sur 20s) |
| Mots affichés / seconde (estimation) | **~2.0–2.5 mots/s** (en tenant compte des frames d'animation spring) |
| Durée typique d'un mot à l'écran | **~0.4–0.6 s** |
| Groupements | 1 mot seul (majorité) ou 2 mots regroupés (stop words : "le plus", "un client", "vous étiez") |

### Effets visuels observés

| Effet | Description | Exemple frame |
|-------|-------------|---------------|
| **Texte kinétique standard** | 1 mot, noir `#000000`, spring pop-in, centre | Toutes les frames de texte |
| **Gradient accent** | Dégradé violet-or sur un mot-clé | t=3s "marché." |
| **Counter prix** | Texte gris clair `#B8B8B8`, espacement large entre chiffres | t=6s "$ 008" |
| **Icône flat** | SVG/emoji noir pur, ~97×58px à 576 (≈182×109px à 1080), centré | t=18s œil 👁️ |
| **Icône animée** | Cercle bleu `#455CA2`, ~46×46px à 576, animation | t=22s 🔵 |
| **REPEATER** | Fond plein gris `#838383`, emoji 🏢 tilé en grille, mot overlay au centre | t=28s "doublé" |
| **B-roll image seule** | Photo produit petite, centrée sur fond blanc, sans carte | t=4s iPhone |
| **B-roll carte** | Rect arrondi (~r=20px), fond noir, image produit + texte overlay, ~300×220px à 576 | t=8-9s iPhone 17 PRO |
| **B-roll technique** | Screenshot Figma/design spec (lignes pointillées bleues, annotations px) | t=30s |

### Structure de la vidéo

| Segment | Durée | Contenu |
|---------|-------|---------|
| **Corps** | t=0 → t=38s (~38s) | Kinetic text alterné avec B-rolls (pas d'intro distincte — texte démarre immédiatement) |
| **End screen** | t=38 → t=44s (**6 secondes**) | Fond `#0D1019`, logo TikTok centré, barre de recherche, handle `@tekiyo_` |

### End screen détaillé

| Élément | Description |
|---------|-------------|
| Fond | `#0D1019` (bleu nuit quasi-noir) |
| Logo | TikTok officiel, centré horizontalement, ~40% du haut |
| Animation | Barre de progression pink/cyan (couleurs brand TikTok) → search bar |
| Handle | **`@tekiyo_`** dans une barre de recherche TikTok stylisée |
| Position handle | Centre horizontal, ~55% vertical |
| Police handle | Blanc sur fond sombre, même sans-serif regular |

### Watermark TikTok natif (overlay plateforme)

| Frames | Position | Taille approx |
|--------|----------|---------------|
| t=0-5s | Bas-gauche (x≈45, y≈508) | ~80×60px à 576 |
| t=6-44s | Bas-droite (x≈535, y≈815) | ~50×40px à 576 |
> Note : ce watermark est ajouté par TikTok à l'enregistrement, non par le pipeline de génération.

### ⚠️ Écarts à corriger dans le pipeline

| Écart détecté | Impact | Correction |
|---------------|--------|-----------|
| ~~Police pipeline : Inter ExtraBold/SemiBold vs référence Regular/Light~~ | ✅ **Résolu 2026-04-15** | `Inter-Regular.ttf` + `Inter-Light.ttf` extraits d'Inter v4.1 → `fonts/` ; `render_text_solid()` weight par défaut → `"regular"` |
| Résolution référence **576×1024** vs cible **1080×1920** | Aucun impact (le pipeline vise déjà 1080×1920) | RAS |
| Font-size pipeline : `FS_BASE=70` vs **68px mesuré** | ±3 % (dans marge JPEG) — tolérance acceptable | RAS — `FS_BASE=70` ≈ 68 px confirmé |

---

## 6. Prochaine tâche P0

> **Sécuriser les clés API avant tout autre travail**

1. Créer un fichier `.env` avec les clés actuelles de `config.yaml`
2. Modifier `common.py` → `load_config()` pour lire depuis `.env` en priorité (via `python-dotenv`)
3. Ajouter `config.yaml` et `.env` dans `.gitignore`
4. Vérifier que `config.example.yaml` ne contient aucune clé réelle

**Commande de démarrage (après sécurisation) :**
```bash
# Lancer le pipeline complet
python nexus_daemon.py

# Lancer Brain seul (génération vidéo uniquement)
python nexus_brain.py

# Lancer Arms seul (upload uniquement, lit OUTPUT_VIDEO/)
python nexus_arms.py

# Mode test (sans appels API ElevenLabs ni upload)
TEST_MODE=true python nexus_brain.py
```
