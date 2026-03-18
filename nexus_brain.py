# -*- coding: utf-8 -*-
# MASTER_NEXUS_V37: NexusBrain — Pipeline unifié, correctifs post-audit V36.
#
# DELTA V37 vs V36:
#
#   FIX #1 — FOND BLANC STATIQUE (correction régression V36 critique):
#     V36: _step_2_visuals() générait 47 fonds différents (dark_navy, pitch_black,
#          warm_cream, chart_ghost, minimal_white) changeant à chaque scène.
#          → chaos visuel, texte illisible sur pitch_black, alternance chaotique.
#     V37: asset_paths = [BG_WHITE_MASTER] * len(scenes)
#          Un seul fond blanc #FFFFFF partagé par toutes les scènes.
#          Les styles premium V36 sont réservés UNIQUEMENT aux B-Roll overlay cards.
#          Les inversions (noir à 12s, navy à 40s) restent gérées par SubtitleBurner.
#
#   FIX #2 — PRE-RENDER PIL→RAWVIDEO→FFMPEG (bypass MoviePy, ×50 speedup):
#     V36: _prerender_base_video_ffmpeg() rendait chaque scène via MoviePy ImageClip
#          → .write_videofile() → 47 × ~2.9s = 134.9s de pre-render.
#     V37: _prerender_base_video_pil_ffmpeg() ouvre chaque JPG via PIL.Image,
#          réplique le frame (duration × fps) fois, pipe rawvideo vers FFmpeg.
#          Gain estimé: 134.9s → ~2-3s (×50 speedup sur le pre-render).
#
#   FIX #3 — TIMELINE SYNTHÉTIQUE HUMANISÉE:
#     V36: _build_synthetic_word_timeline() distribuait les mots uniformément
#          (durée_scène / n_mots) → rythme métronome parfaitement régulier.
#     V37: _build_synthetic_word_timeline_humanized() pondère par syllabes
#          + jitter gaussien ±15% → variabilité humaine simulée.
#
#   FIX #4 — BROLLSCHEDULER NON-MÉCANIQUE:
#     V36: pattern détecté → beat régulier toutes les 4 scènes (8,12,16,20...)
#          + 4 B-Roll consécutifs au début (0,1,2,3).
#     V37: minimum 3 scènes de gap entre deux B-Roll consécutifs,
#          bonus score sur mots-clés sémantiques forts plutôt que beat régulier.
#
#   CONSERVÉ V36 (inchangé):
#     Compensation cap-height (_font_compensated), modèle phonémique V36,
#     SpringLUT @60fps, anticipation -40ms, spring k=900 c=30 ζ=0.50,
#     SubtitleBurner V34, BRoll chrome via render_broll_card().

import asyncio
import sys
import os
import time
import json
import shutil
import random
import math
import subprocess
import glob
import re
import uuid
import copy
import tempfile
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from moviepy.config import change_settings
    magick_path = shutil.which("magick") or shutil.which("convert")
    if magick_path:
        change_settings({"IMAGEMAGICK_BINARY": magick_path})
    elif os.path.exists(r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"):
        change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})
except Exception:
    pass

import aiohttp
try:
    from moviepy.editor import (
        AudioFileClip, VideoFileClip, concatenate_videoclips,
        ImageClip, CompositeAudioClip,
    )
except ImportError:
    print("CRITICAL: MoviePy non installé. Run 'pip install \"moviepy<2.0.0\"'")
    sys.exit(1)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common import jlog, CONFIG, ensure_directories, resolve_path
from prompts.templates import wrap_v3_prompt, get_manual_ingestion_prompt, get_brainstorm_prompt
from tools.asset_vault import AssetVault
from tools.tts_manager import OpenAITTS
from tools.scene_animator import SceneAnimator
from tools.burner import SubtitleBurner
from fallback import FallbackProvider

from tools.config import FS_BASE
from tools.physics import SpringLUT
from tools.graphics import generate_procedural_broll_card


# ─────────────────────────────────────────────────────────────────────────────
# MOTION_ENGINE_V32: Constantes globales
# ─────────────────────────────────────────────────────────────────────────────

AUDIO_ANTICIPATION_OFFSET: float = -0.040
VIRTUAL_CAMERA_ZOOM_START: float =  1.000
VIRTUAL_CAMERA_ZOOM_END:   float =  1.030
SPRING_K_REFERENCE:        float =  900.0
SPRING_C_REFERENCE:        float =   30.0
SCENE_DETECTION_WORD_THRESHOLD: int = 3
TYPO_SCALE_NORMAL:  float = 1.00
TYPO_SCALE_ACCENT:  float = 1.45
TYPO_SCALE_BADGE:   float = 1.25
TYPO_SCALE_MUTED:   float = 1.10
TYPO_SCALE_STOP:    float = 0.85
BROLL_MAX_COVERAGE_RATIO: float = 0.70

SCRIPT_MIN_SCENES: int = 8
SCRIPT_MIN_WORDS:  int = 60
SCRIPT_TTS_WORDS_PER_SEC: float = 2.5

# MASTER_NEXUS_V37: Couverture B-Roll cible
BROLL_TARGET_COVERAGE_RATIO:  float = 0.35
# Gap minimum entre deux B-Roll consécutifs (fix pattern mécanique)
BROLL_MIN_GAP_SCENES:         int   = 3


class SemanticException(Exception):
    pass


_VISUAL_PROMPT_RENDER_INSTRUCTIONS = [
    "fond blanc", "fond noir", "background blanc", "background noir",
    "#ffffff", "#000000", "strict", "aucun visuel", "no image",
    "transition:", "transition :", "slide", "fade", "strictement"
]

_GHOST_TEXT_BLACKLIST = frozenset([
    "votre phrase", "d'accroche ici", "la suite de votre idée",
    "un point fort.", "chiffrecle", "mot_impact", "mot_liaison",
    "mot_fort", "chiffre_cle", "insert_ton_texte", "premier mot ou groupe",
    "deuxième mot ou groupe", "[titre accrocheur", "schéma-scene",
    "exemple de structure", "ton premier vrai mot", "ton vrai premier mot",
    "vrai contenu sur", "placeholder",
])


def _is_ghost_text(scene_text: str) -> bool:
    if not scene_text:
        return False
    t = scene_text.lower().strip()
    t_clean = re.sub(r'\[(?:BOLD|LIGHT|BADGE|PAUSE)\]', '', t).strip()
    return any(ghost in t_clean for ghost in _GHOST_TEXT_BLACKLIST)


def _sanitize_visual_prompt(raw_prompt: str) -> str:
    if not raw_prompt:
        return "cinematic trading abstract"
    low = raw_prompt.lower()
    for keyword in _VISUAL_PROMPT_RENDER_INSTRUCTIONS:
        low = low.replace(keyword, "")
    clean = low.strip(" \t\n\r-:;,.#")
    if len(clean) < 3:
        return "cinematic trading abstract"
    return clean


_VISUAL_PROMPT_POOL = [
    "candlestick chart trading screen glow",
    "financial dashboard bloomberg terminal dark",
    "stock market graph uptrend green",
    "forex trading setup multiple monitors",
    "crypto price action chart blue neon",
    "focused trader at desk morning light",
    "person studying laptop finance notebook",
    "confident businessman suit city skyline",
    "hands typing keyboard financial data",
    "young entrepreneur smiling success",
    "abstract gold particles dark background",
    "luxury minimal white marble texture",
    "neon green financial data stream",
    "premium dark gradient geometric shapes",
    "cinematic money notes falling slow motion",
    "funded account dashboard profit green",
    "prop trading firm challenge results",
    "trading performance report analytics",
    "risk management metrics display",
    "capital allocation financial growth",
]


def _diversify_visual_prompts(scenes: List[Dict]) -> List[Dict]:
    sanitized = [_sanitize_visual_prompt(s.get("visual_prompt", "")) for s in scenes]
    unique    = set(sanitized)
    if len(unique) > 1:
        return scenes
    jlog("info", msg=(
        f"FIX V35.1: Auto-diversification de {len(scenes)} visual_prompts "
        f"(tous = '{list(unique)[0]}')"
    ))
    pool = _VISUAL_PROMPT_POOL.copy()
    for i in range(len(scenes)):
        scenes[i]["visual_prompt"] = pool[i % len(pool)]
    jlog("success", msg=(
        f"FIX V35.1: {len(scenes)} prompts diversifiés depuis le pool "
        f"({len(_VISUAL_PROMPT_POOL)} templates)"
    ))
    return scenes


# ─────────────────────────────────────────────────────────────────────────────
# MOTION_ENGINE_V32: Easing & Spring
# ─────────────────────────────────────────────────────────────────────────────

def _ease_out_back(p: float, overshoot: float = 1.70158) -> float:
    p  = max(0.0, min(1.0, p))
    c1 = overshoot
    c3 = c1 + 1.0
    return 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2


def _ease_in_out_sine(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return -(math.cos(math.pi * p) - 1.0) / 2.0


def _spring_value(
    t: float,
    k: float = SPRING_K_REFERENCE,
    c: float = SPRING_C_REFERENCE,
) -> float:
    t      = max(0.0, t)
    omega0 = math.sqrt(max(k, 1e-6))
    zeta   = c / (2.0 * omega0)
    if zeta < 1.0 - 1e-6:
        omega_d   = omega0 * math.sqrt(max(1.0 - zeta**2, 1e-12))
        sin_coeff = zeta / math.sqrt(max(1.0 - zeta**2, 1e-12))
        env       = math.exp(-zeta * omega0 * t)
        return 1.0 - env * (math.cos(omega_d * t) + sin_coeff * math.sin(omega_d * t))
    elif zeta > 1.0 + 1e-6:
        sq = math.sqrt(max(zeta**2 - 1.0, 1e-12))
        r1 = omega0 * (-zeta + sq)
        r2 = omega0 * (-zeta - sq)
        d  = r2 - r1 if abs(r2 - r1) > 1e-12 else 1e-12
        return 1.0 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / d
    else:
        env = math.exp(-omega0 * t)
        return 1.0 - env * (1.0 + omega0 * t)


def _spring_clamped(
    t: float,
    k: float = SPRING_K_REFERENCE,
    c: float = SPRING_C_REFERENCE,
) -> float:
    return max(0.0, min(1.0, _spring_value(t, k, c)))


# ─────────────────────────────────────────────────────────────────────────────
# MASTER_NEXUS_V37: Timeline Processing
# ─────────────────────────────────────────────────────────────────────────────

def _count_syllables_fr(word: str) -> int:
    """
    MASTER_NEXUS_V37: Comptage syllabique simplifié (français/anglais).
    Utilisé pour pondérer la durée des mots dans la timeline humanisée.
    Heuristique: groupes voyelles consécutifs = 1 syllabe.
    """
    clean = re.sub(r'\[.*?\]', '', word).lower().strip(".,!?;:\"'«»")
    if not clean:
        return 1
    vowels  = re.findall(r'[aeiouyéèêëàâùûîïôœæ]+', clean)
    count   = len(vowels)
    # Correction: "e" muet en fin de mot français (-e, -es, -ent)
    if clean.endswith(('e', 'es', 'ent')) and count > 1:
        count -= 1
    return max(1, count)


def _build_synthetic_word_timeline_humanized(
    scene_timeline: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
    """
    MASTER_NEXUS_V37: Timeline synthétique avec variabilité humaine.

    Vs V36 (_build_synthetic_word_timeline):
        V36: poids = len(char) → distribution proportionnelle aux caractères
             → métronome parfait, aucune variabilité.
        V37: poids = syllables × gauss(1.0, σ=0.15) + bonus sémantique
             → variabilité ±15% par mot, mots courts plus rapides,
             mots d'impact plus longs, cohérent avec la parole humaine.

    Effets:
        Mot court (de, le)   : ~0.12-0.18s
        Mot normal (trading) : ~0.30-0.45s
        Mot long (stratégie) : ~0.45-0.65s
        Jitter gaussien      : ±15% par mot (σ=0.15)
    """
    # Mots qui méritent une durée plus longue (emphase)
    EMPHASIS_WORDS = {
        "secret", "argent", "profit", "gain", "succès", "méthode",
        "stratégie", "funded", "trading", "vérité", "réalité",
        "comptable", "fiscal", "payout", "capital", "champion",
    }
    # Stop words : durée courte
    SHORT_WORDS = {
        "le", "la", "les", "un", "une", "des", "de", "du", "à", "au",
        "et", "en", "ne", "se", "sa", "son", "ses", "on", "y", "il",
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and",
    }

    result = []
    for t_start, t_end, text in scene_timeline:
        clean = re.sub(r'\[.*?\]', '', text).strip()
        words = clean.split() if clean else []
        if not words:
            continue
        if len(words) == 1:
            result.append((t_start, t_end, words[0]))
            continue

        duration = max(t_end - t_start, 0.05)

        # Calcul des poids syllabiques avec jitter humain
        weights = []
        for w in words:
            w_clean = w.lower().rstrip(".,!?;:")
            syl     = _count_syllables_fr(w_clean)

            # Jitter gaussien ±15% (σ=0.15, clamp [0.6, 1.6])
            jitter = max(0.6, min(1.6, random.gauss(1.0, 0.15)))

            # Bonus emphase
            if w_clean in EMPHASIS_WORDS:
                jitter *= 1.25
            elif w_clean in SHORT_WORDS:
                jitter *= 0.65

            weights.append(max(0.2, syl * jitter))

        total_w = sum(weights)
        cursor  = t_start

        for i, (word, w) in enumerate(zip(words, weights)):
            proportion = w / max(total_w, 1e-6)
            w_end      = cursor + duration * proportion
            if i == len(words) - 1:
                w_end = t_end
            result.append((cursor, min(w_end, t_end), word))
            cursor = w_end

    return result


def _is_word_level_timeline(timeline: List[Tuple[float, float, str]]) -> bool:
    if not timeline:
        return True
    sample    = timeline[:min(10, len(timeline))]
    avg_words = sum(len(t[2].split()) for t in sample) / len(sample)
    return avg_words <= SCENE_DETECTION_WORD_THRESHOLD


def _apply_anticipation_offset(
    timeline: List[Tuple[float, float, str]],
    offset:   float = AUDIO_ANTICIPATION_OFFSET,
) -> List[Tuple[float, float, str]]:
    if not timeline or abs(offset) < 1e-6:
        return timeline
    adjusted = []
    for t_start, t_end, word in timeline:
        new_start = max(0.0, t_start + offset)
        if t_end - new_start < 0.050:
            new_start = max(0.0, t_end - 0.050)
        adjusted.append((new_start, t_end, word))
    return adjusted


def _close_word_gaps(
    timeline: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
    if len(timeline) < 2:
        return timeline
    result = list(timeline)
    for i in range(len(result) - 1):
        t_s, t_e, word = result[i]
        next_start     = result[i + 1][0]
        gap_ms         = (next_start - t_e) * 1000.0
        if gap_ms > 1.0 and "[PAUSE]" not in word.upper():
            result[i] = (t_s, next_start, word)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MASTER_NEXUS_V37: BRollScheduler — scoring sémantique, gap minimum garanti
# ─────────────────────────────────────────────────────────────────────────────

_BROLL_ACCENT_WORDS = {
    "secret", "profit", "gain", "winner", "argent", "succès", "champion",
    "payout", "capital", "système", "méthode", "stratégie", "révèle",
    "découverte", "clé", "maîtrise", "comptable", "fiscal", "vérité",
    "réalité", "cashflow", "performance", "funded", "ftmo", "apex",
    "optimiser", "récupérer", "trading", "trader", "challenge",
}
_BROLL_NEGATIVE_WORDS = {
    "perte", "crash", "danger", "stop", "alerte", "faux", "piège",
    "erreur", "risque", "échec", "impossible",
}


def _compute_broll_schedule_v37(
    scenes:       List[Dict],
    target_ratio: float = BROLL_TARGET_COVERAGE_RATIO,
    min_gap:      int   = BROLL_MIN_GAP_SCENES,
) -> List[int]:
    """
    MASTER_NEXUS_V37: BRollScheduler avec gap minimum garanti.

    Corrections vs V36:
        1. Gap minimum de `min_gap` scènes entre deux B-Roll consécutifs.
           → Élimine les patterns 0,1,2,3 consécutifs et les beats 4,8,12,16.
        2. Score sémantique privilégié sur le beat régulier.
           → Les B-Roll apparaissent aux moments émotionnels, pas à intervalles fixes.
        3. Hook (i=0) et dernière scène conservent le score 100 (toujours sélectionnés).
        4. Algorithme de sélection greedy avec contrainte de gap:
           On trie par score décroissant, on sélectionne les candidats en respectant
           le gap minimum entre sélections.

    Gap minimum = 3 scènes (≈ 2.3s à 0.77s/scène).
    """
    n            = len(scenes)
    target_count = max(3, int(n * target_ratio))

    # ── Calcul des scores ──────────────────────────────────────────────────
    scored: List[Tuple[int, int]] = []   # (scene_idx, score)

    for i, scene in enumerate(scenes):
        text        = scene.get("text", "")
        clean       = re.sub(r'\[(?:BOLD|LIGHT|BADGE|PAUSE)\]', '', text, flags=re.IGNORECASE).lower()
        words_lower = [w.rstrip('.,!?;:') for w in clean.split() if w]

        # Scènes [PAUSE] → exclure
        if "[PAUSE]" in text.upper():
            scored.append((i, -1))
            continue

        score = 0

        # Cas prioritaires absolus
        if i == 0:       score += 100    # hook
        if i == n - 1:   score += 100    # dernière scène

        # Contenu sémantique — score élevé pour moments forts
        if any(re.search(r'[\d%€$£]', w) for w in text.split()):
            score += 8                   # chiffre/stat → moment fort
        if any(w in _BROLL_ACCENT_WORDS for w in words_lower):
            score += 6                   # mot positif fort
        if "[BADGE]" in text:            score += 10
        if "[BOLD]" in text:             score += 4
        if any(w in _BROLL_NEGATIVE_WORDS for w in words_lower):
            score += 3                   # négatif: aussi un moment fort
        # NOTE V37: Suppression du bonus "beat régulier toutes les 4 scènes"
        #           → remplacé par la contrainte de gap minimum ci-dessous

        scored.append((i, score))

    # ── Sélection greedy avec contrainte de gap minimum ────────────────────
    # Trier par score décroissant (exclure score < 0)
    valid_candidates = [(idx, s) for idx, s in scored if s >= 0]
    valid_candidates.sort(key=lambda x: x[1], reverse=True)

    selected:      List[int] = []
    last_selected: int       = -min_gap - 1   # Sentinelle

    for idx, score in valid_candidates:
        if len(selected) >= target_count:
            break

        # Vérifier le gap minimum
        if selected and abs(idx - last_selected) < min_gap:
            # Si c'est le hook (idx=0) ou la dernière scène, forcer l'ajout quand même
            if idx not in (0, n - 1):
                continue

        selected.append(idx)
        last_selected = idx

    # Si on n'a pas atteint la cible (à cause du gap), relâcher et compléter
    if len(selected) < target_count:
        selected_set = set(selected)
        remaining    = [(idx, s) for idx, s in valid_candidates if idx not in selected_set]
        for idx, _ in remaining:
            if len(selected) >= target_count:
                break
            # Gap relaxé à 2 si on n'atteint pas la cible
            if not selected or min(abs(idx - s) for s in selected) >= max(2, min_gap - 1):
                selected.append(idx)

    selected = sorted(set(selected))
    coverage = len(selected) / max(n, 1)

    jlog("info", msg=(
        f"MASTER_NEXUS_V37: BRollScheduler → "
        f"{len(selected)}/{n} scènes "
        f"({coverage:.0%} couverture, cible {target_ratio:.0%}, gap_min={min_gap})"
    ))
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# MASTER_NEXUS_V36: Modèle phonémique (conservé V37)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_audio_duration_v36(
    scenes:       List[Dict],
    speed:        float = 1.0,
    min_duration: float = 30.0,
) -> float:
    """
    MASTER_NEXUS_V36 (conservé V37): Estimation durée TTS avec modèle phonémique.

    Modèle ElevenLabs v2:
        Débit            : 2.50 mots/s × speed_factor
        Pause [PAUSE]    : 0.700s
        Inter-scène      : 0.080s
        Fin de phrase    : 0.350s
        Virgule/pt-virgule: 0.180s
        Inhale (>5 mots) : 0.120s
    """
    ELEVENLABS_WPS_BASE = 2.50
    wps_effective       = ELEVENLABS_WPS_BASE * max(speed, 0.5)

    total_words  = 0
    pause_budget = 0.0
    prev_words   = 0

    for i, scene in enumerate(scenes):
        text  = scene.get("text", "")
        clean = re.sub(r'\[(?:BOLD|LIGHT|BADGE)\]', '', text, flags=re.IGNORECASE).strip()

        if "[PAUSE]" in text.upper():
            pause_budget += 0.700
            prev_words    = 0
            continue

        words   = [w for w in clean.split() if re.sub(r'[^\w]', '', w)]
        n_words = len(words)
        total_words += n_words

        if i > 0:
            pause_budget += 0.080

        last_word = words[-1] if words else ""
        stripped  = last_word.rstrip("'\"»")
        if stripped.endswith(('.', '!', '?')):
            pause_budget += 0.350
        elif stripped.endswith((',', ';')):
            pause_budget += 0.180

        if n_words > 5 and prev_words > 5:
            pause_budget += 0.120

        prev_words = n_words

    speech_duration = total_words / max(wps_effective, 0.1)
    estimated       = max(min_duration, speech_duration + pause_budget)

    jlog("info", msg=(
        f"MASTER_NEXUS_V37: Audio fallback — "
        f"{total_words} mots / {wps_effective:.2f} WPS = {speech_duration:.2f}s "
        f"+ {pause_budget:.2f}s pauses → durée finale {estimated:.2f}s "
        f"(speed={speed:.2f})"
    ))
    return estimated


class NexusBrain:
    MAX_SCENES = 999
    MIN_WHISPER_WORDS_PER_SECOND = 0.3

    def __init__(self):
        self.root_dir   = resolve_path("workspace")
        self.hot_root   = resolve_path("hot_folder")
        self.buffer_dir = resolve_path("BUFFER")
        self.base_path  = os.path.dirname(os.path.abspath(__file__))

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.hot_root.mkdir(parents=True, exist_ok=True)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)

        if not shutil.which("ffmpeg"):
            ffmpeg_bin_path = r"C:\ffmpeg\bin"
            if os.path.exists(ffmpeg_bin_path):
                if ffmpeg_bin_path not in os.environ["PATH"]:
                    os.environ["PATH"] += os.pathsep + ffmpeg_bin_path
                    jlog("info", msg="FFMPEG path forced", path=ffmpeg_bin_path)
            else:
                jlog("fatal", msg="FFMPEG introuvable.")
                sys.exit(1)

        self.history_file = resolve_path("history_topics.json")
        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f)

        self.vault    = AssetVault()
        self.tts      = OpenAITTS()
        self.fallback = FallbackProvider()
        self.animator = SceneAnimator()

        self.subtitle_burner = SubtitleBurner(
            model_size        = "base",
            fontsize          = FS_BASE,
            spring_stiffness  = int(SPRING_K_REFERENCE),
            spring_damping    = int(SPRING_C_REFERENCE),
        )

        video_cfg = CONFIG.get("video", {})
        self.enable_slowzoom          = video_cfg.get("enable_slowzoom",       True)
        self.enable_slide_trans       = video_cfg.get("enable_slide_trans",    True)
        self.enable_fade_trans        = video_cfg.get("enable_fade_trans",     True)
        self.enable_motion_blur       = video_cfg.get("enable_motion_blur",    False)
        self.enable_micro_zoom        = video_cfg.get("enable_micro_zoom",     True)
        self.micro_zoom_intensity     = video_cfg.get("micro_zoom_intensity",  0.008)
        self.bg_style                 = video_cfg.get("background_style",      "white")
        self.pause_min_duration       = video_cfg.get("pause_min_duration",    1.0)
        self.broll_min_scene_duration = video_cfg.get("broll_min_scene_duration", 2.5)

        self.last_run_date = None
        self.signals_dir   = Path("./temp_signals")
        self.signals_dir.mkdir(exist_ok=True)

        self.prerender_dir = Path(tempfile.gettempdir()) / "nexus_prerender"
        self.prerender_dir.mkdir(exist_ok=True)

        SpringLUT.warm_up(fps=60)

        jlog("info", msg=f"Nexus Brain V37 initialized (MASTER_NEXUS_V37)")
        jlog("info", msg=f"  Anticipation offset : {AUDIO_ANTICIPATION_OFFSET*1000:.0f}ms")
        jlog("info", msg=f"  Zoom caméra virtuelle : {VIRTUAL_CAMERA_ZOOM_START:.3f}→{VIRTUAL_CAMERA_ZOOM_END:.3f}")
        jlog("info", msg=f"  Spring k={SPRING_K_REFERENCE:.0f} c={SPRING_C_REFERENCE:.0f} ζ=0.50")
        jlog("info", msg=f"  SpringLUT warmed up @60fps — {len(SpringLUT._cache)} profils en cache")
        jlog("info", msg=f"  BRollScheduler target: {BROLL_TARGET_COVERAGE_RATIO:.0%}, gap_min={BROLL_MIN_GAP_SCENES}")
        jlog("info", msg=f"  Fond: BLANC STATIQUE #FFFFFF (correctif V37)")

    # ─────────────────────────────────────────────────────────────────────
    # INTELLIGENCE DÉLÉGUÉE & MÉMOIRE
    # ─────────────────────────────────────────────────────────────────────

    def _read_healing_history(self) -> Dict:
        hist_file = resolve_path("healing_history.json")
        if hist_file.exists():
            try:
                with open(hist_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_error": None}

    def _write_healing_history(self, state: Dict):
        hist_file = resolve_path("healing_history.json")
        try:
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            pass

    async def _invoke_cli_agent(self, prompt: str, context_tag: str = "general") -> Optional[str]:
        jlog("brain", msg=f"📡 Delegation CLI Agent [Tag: {context_tag}]...")

        cli_script = resolve_path("collect_cli.py")
        if not cli_script.exists():
            jlog("fatal", msg="collect_cli.py introuvable !")
            return None

        cmd = [
            sys.executable,
            str(cli_script),
            "--prompt", prompt,
            "--user-id", "admin",
            "--profile-base", CONFIG.get("SENTINEL_PROFILE", r"C:/Nexus_Data"),
        ]

        healing_state = self._read_healing_history()
        timeout_val   = 600
        if healing_state.get("last_error") == "wait_network_idle_timeout":
            cmd.extend(["--generation-timeout", "90000"])
            timeout_val = 900
            jlog("info", msg="Auto-guérison: Timeout étendu activé.")

        env                             = os.environ.copy()
        current_pythonpath              = env.get("PYTHONPATH", "")
        env["PYTHONPATH"]               = self.base_path + os.pathsep + current_pythonpath
        env["PYTHONIOENCODING"]         = "utf-8"
        env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8"

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            self._clean_buffer()
            start_time = time.time()
            jlog("info", msg=f"Tentative CLI {attempt}/{max_retries}...")
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=self.base_path,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_val
                )
                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')

                if process.returncode == 0:
                    content = self._retrieve_latest_buffer_content(start_time)
                    if content:
                        self._write_healing_history({"last_error": None})
                        return content
                    else:
                        jlog("warning", msg="CLI terminé sans erreur mais aucun buffer valide trouvé.")
                elif process.returncode == 130:
                    raise KeyboardInterrupt("Arrêt manuel détecté.")
                else:
                    stderr_preview = stderr[:1000] if stderr else "No stderr"
                    jlog("warning", msg=f"Erreur CLI (Code {process.returncode}): {stderr_preview}")
                    if "timeout" in stderr.lower() or "wait_network_idle" in stderr.lower():
                        self._write_healing_history({"last_error": "wait_network_idle_timeout"})
                    else:
                        self._write_healing_history({"last_error": "unknown_cli_error"})

            except asyncio.TimeoutError:
                if process:
                    try: process.kill()
                    except: pass
                jlog("error", msg=f"CLI Agent Timeout (>{timeout_val}s) à la tentative {attempt}")
            except Exception as e:
                if process:
                    try: process.kill()
                    except: pass
                jlog("error", msg=f"CLI Agent Exception: {str(e)}")

            if attempt < max_retries:
                backoff = 2 ** attempt * 5
                jlog("info", msg=f"Retry dans {backoff}s...")
                await asyncio.sleep(backoff)

        jlog("error", msg="CLI Agent a échoué définitivement après tous les retrys.")
        return None

    def _clean_buffer(self):
        try:
            for f in self.buffer_dir.glob("*.json"):
                try: os.remove(f)
                except: pass
        except Exception:
            pass

    def _retrieve_latest_buffer_content(self, start_time: float = 0.0) -> Optional[str]:
        try:
            files = list(self.buffer_dir.glob("*.json"))
            if not files:
                return None
            valid_files = [f for f in files if os.path.getmtime(f) >= start_time - 1.0]
            if not valid_files:
                jlog("warning", msg="Fichiers buffer ignorés (fantômes).")
                return None
            latest_file = max(valid_files, key=os.path.getmtime)
            jlog("success", msg=f"Payload valide récupéré: {latest_file.name}")
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            content = data.get("content", {})
            return content.get("text", None)
        except Exception as e:
            jlog("error", msg="Erreur lecture Buffer", error=str(e))
            return None

    # ─────────────────────────────────────────────────────────────────────
    # INTELLIGENCE LOGIQUE & HEURISTIQUES
    # ─────────────────────────────────────────────────────────────────────

    def _get_smart_sleep_duration(self) -> int:
        now              = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")
        if self.last_run_date == current_date_str:
            tomorrow_8am    = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
            seconds_to_wait = (tomorrow_8am - now).total_seconds()
            jitter          = random.randint(0, 2700)
            total_sleep     = max(60, int(seconds_to_wait + jitter))
            jlog("pacer", msg=f"Quota done. Smart Sleep: réveil dans {total_sleep/3600:.2f}h")
            return total_sleep
        if 2 <= now.hour < 6:
            target_time = now.replace(hour=6, minute=0, second=0)
            seconds     = int((target_time - now).total_seconds())
            jlog("pacer", msg=f"Night Mode. Sleep {seconds/3600:.2f}h")
            return max(60, seconds)
        return 60

    def _get_smart_theme(self) -> str:
        recent_topics = self._get_recent_topics(limit=10)
        counts = {"mindset": 0, "technique": 0, "propfirm": 0}
        for t in recent_topics:
            t_low = t.lower()
            if any(k in t_low for k in ["mindset","discipline","psychologie","motivation","secret","perds"]):
                counts["mindset"] += 1
            elif any(k in t_low for k in ["ftmo","apex","funded","payout"]):
                counts["propfirm"] += 1
            else:
                counts["technique"] += 1
        total = sum(counts.values())
        if counts["propfirm"] == 0 and total >= 4:
            return "Vente & Conversion PropFirm (Preuves de gains/Payout)"
        if counts["mindset"] < 2:
            return "Motivation & Discipline (Psychologie du Trader)"
        return "Technique & Analyse (Stratégie pure)"

    def _heuristic_tagging(self, filename: str) -> Dict:
        name_lower = filename.lower()
        tags       = ["shorts", "finance"]
        rules = {
            "crypto":   ["crypto","bitcoin","btc","eth","solana"],
            "trading":  ["trading","forex","scalping","chart","analyse","ict","smc"],
            "mindset":  ["mindset","motivation","discipline","succès","fail"],
            "propfirm": ["ftmo","apex","funded","payout","topstep","eval"],
        }
        detected_category = "Trading"
        for category, keywords in rules.items():
            if any(k in name_lower for k in keywords):
                tags.append(category)
                for k in keywords:
                    if k in name_lower and k != category:
                        tags.append(k)
                detected_category = category.capitalize()
        now      = datetime.now()
        day_tags = {0:"#NewWeek",4:"#FridayFeeling",5:"#WeekendVibes",6:"#SundayReset"}
        if now.weekday() in day_tags:
            tags.append(day_tags[now.weekday()])
        clean_name = Path(filename).stem.replace("_"," ").replace("-"," ").title()
        if len(clean_name) < 10:
            clean_name = f"{clean_name} : Le Secret Dévoilé"
        return {
            "title":          f"{clean_name} #{detected_category}",
            "description":    f"Découvrez {clean_name}.\n\nABONNE-TOI pour plus de {detected_category}.",
            "tags":           list(set(tags)),
            "created_at":     str(datetime.now()),
            "auto_generated": True,
        }

    # ─────────────────────────────────────────────────────────────────────
    # GESTION HISTORIQUE
    # ─────────────────────────────────────────────────────────────────────

    def _get_recent_topics(self, limit: int = None) -> List[str]:
        try:
            if not os.path.exists(self.history_file):
                return []
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list): return []
                if limit: return data[-limit:]
                return data
        except Exception:
            return []

    def _save_topic_to_history(self, topic: str):
        try:
            data = self._get_recent_topics()
            data.append(topic)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            jlog("error", msg="Erreur sauvegarde topic", error=str(e))

    def _parse_script_from_text(self, text: str) -> Optional[Dict]:
        try:
            title_match = re.search(r"TITRE\s*:\s*(.*)", text, re.IGNORECASE)
            title       = title_match.group(1).strip(" \t\n\r\\\"'*") if title_match else "Sujet Mystère"
            tags_match  = re.search(r"TAGS\s*:\s*(.*)", text, re.IGNORECASE)
            tags_list   = [t.strip(" \t\n\r\\\"'*") for t in tags_match.group(1).split(",")] if tags_match else []

            scenes       = []
            scene_blocks = re.split(r"SCENE\s*\d+", text, flags=re.IGNORECASE)

            for i, block in enumerate(scene_blocks[1:], 1):
                block = block.strip()
                if not block: continue

                text_match    = re.search(r"TEXTE\s*:\s*(.*?)(?=\n(?:VISUEL|OVERLAY)|$)", block, re.IGNORECASE | re.DOTALL)
                scene_text    = text_match.group(1).strip() if text_match else ""
                visuel_match  = re.search(r"VISUEL\s*:\s*(.*?)(?=\n(?:TEXTE|OVERLAY)|$)", block, re.IGNORECASE | re.DOTALL)
                scene_visuel  = visuel_match.group(1).strip() if visuel_match else "abstract trading background"
                overlay_match = re.search(r"OVERLAY\s*:\s*(.*?)(?=\n|$)", block, re.IGNORECASE)
                keywords      = [k.strip() for k in overlay_match.group(1).split(",")] if overlay_match else []

                transition_type = "none"
                if "TRANSITION: SLIDE" in scene_visuel.upper() or "TRANSITION : SLIDE" in scene_visuel.upper():
                    transition_type = "slide"
                elif "TRANSITION: FADE" in scene_visuel.upper() or "TRANSITION : FADE" in scene_visuel.upper():
                    transition_type = "fade"

                if scene_text and _is_ghost_text(scene_text):
                    jlog("warning", msg=f"FIX_GHOST_TEXT: Scène {i} rejetée — texte fantôme: «{scene_text[:60]}»")
                    continue

                if scene_text:
                    scenes.append({
                        "id":               i,
                        "text":             scene_text,
                        "visual_prompt":    scene_visuel,
                        "keywords_overlay": keywords,
                        "transition":       transition_type,
                    })

            if not scenes: return None
            return {"meta": {"title": title, "tags": tags_list, "tts_speed": 1.1}, "scenes": scenes}
        except Exception as e:
            jlog("error", msg="Text Parsing failed", error=str(e))
            return None

    # ─────────────────────────────────────────────────────────────────────
    # VALIDATION DENSITÉ
    # ─────────────────────────────────────────────────────────────────────

    def _validate_script_density(self, script_data: Dict) -> bool:
        if not script_data or "scenes" not in script_data:
            jlog("warning", msg="Script None ou sans 'scenes'.")
            return False

        scenes      = script_data["scenes"]
        n_scenes    = len(scenes)
        total_words = sum(
            len(re.sub(r'\[.*?\]', '', s.get("text", "")).split())
            for s in scenes
        )

        if n_scenes < SCRIPT_MIN_SCENES:
            jlog("warning", msg=f"Script rejeté — {n_scenes} scènes (minimum {SCRIPT_MIN_SCENES}).")
            return False

        if total_words < SCRIPT_MIN_WORDS:
            jlog("warning", msg=f"Script rejeté — {total_words} mots (minimum {SCRIPT_MIN_WORDS}).")
            return False

        avg_words_per_scene = total_words / max(n_scenes, 1)
        if avg_words_per_scene < 1.80:
            jlog("warning", msg=(
                f"Script rejeté — densité {avg_words_per_scene:.2f} mots/scène "
                f"(minimum 1.80). Pattern word-by-word détecté."
            ))
            return False

        unique_prompts = set(
            _sanitize_visual_prompt(s.get("visual_prompt", "")) for s in scenes
        )
        if len(unique_prompts) <= 1 and n_scenes > 10:
            jlog("warning", msg=(
                f"Alerte qualité — tous les visual_prompt identiques "
                f"({list(unique_prompts)}). Auto-diversification activée."
            ))
            if "meta" not in script_data:
                script_data["meta"] = {}
            script_data["meta"]["_needs_prompt_diversification"] = True

        est_duration = total_words / SCRIPT_TTS_WORDS_PER_SEC
        jlog("info", msg=(
            f"Script validé ✓ — {n_scenes} scènes | {total_words} mots | "
            f"{avg_words_per_scene:.1f} mots/scène | "
            f"durée estimée {est_duration:.1f}s | "
            f"{len(unique_prompts)} prompt(s) distincts"
        ))
        return True

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 0 : BRAINSTORMING
    # ─────────────────────────────────────────────────────────────────────

    async def _step_0_brainstorm_topic(self) -> str:
        jlog("step", msg="Step 0: Brainstorming (CLI Delegation)")

        all_topics     = self._get_recent_topics(limit=None)
        recent_context = ", ".join(all_topics[-20:]) if all_topics else ""
        day_theme      = self._get_smart_theme()
        ai_context     = (
            f"Thème actuel imposé : '{day_theme}'. "
            f"Sujets déjà traités récemment (à éviter) : {recent_context}."
        )

        prompt       = get_brainstorm_prompt(ai_context, None)
        raw_response = await self._invoke_cli_agent(prompt, context_tag="brainstorm")
        topic        = None

        try:
            if not raw_response:
                raise SemanticException("Aucune réponse récupérée.")

            topic_candidate = None
            title_match     = re.search(r'(?:TITRE|TITLE)\s*:\s*(.+)', raw_response, re.IGNORECASE)
            if title_match:
                topic_candidate = title_match.group(1).strip(" \t\n\r\\\"'*")
            else:
                json_match = re.search(r'\{.*?\}', raw_response.strip(), re.DOTALL)
                if json_match:
                    try:
                        data            = json.loads(json_match.group(0))
                        topic_candidate = data.get("title", "").strip(" \t\n\r\\\"'*")
                    except json.JSONDecodeError:
                        pass

            if not topic_candidate:
                raise SemanticException("Format incompréhensible.")

            t_low = topic_candidate.lower()
            if any(k in t_low for k in ["error","http","://","www.",".com"]):
                raise SemanticException(f"URL/erreur IA dans le titre '{topic_candidate}'.")

            if topic_candidate in all_topics:
                raise SemanticException(f"Sujet dupliqué: '{topic_candidate}'.")

            topic = topic_candidate
            jlog("success", msg=f"Topic validé: {topic}")

        except SemanticException as e:
            jlog("warning", msg=f"Alerte sémantique: {e}. Activation du Fallback interne.")
            fallback_matrix = {
                "Vente & Conversion PropFirm (Preuves de gains/Payout)": [
                    "Les secrets de FTMO", "Mon premier Payout PropFirm",
                ],
                "Motivation & Discipline (Psychologie du Trader)": [
                    "Le Mindset Trader", "Pourquoi tu perds en trading",
                ],
                "Technique & Analyse (Stratégie pure)": [
                    "Ma stratégie SMC expliquée", "Le secret de l'Order Block",
                ],
            }
            base_topics = fallback_matrix.get(day_theme, ["Le Mindset Trader","Pourquoi tu perds"])
            topic       = random.choice([t for t in base_topics if t not in all_topics] or base_topics)

        self._save_topic_to_history(topic)
        jlog("info", msg=f"Topic sélectionné: {topic}")
        return topic

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 1 : IDEATION
    # ─────────────────────────────────────────────────────────────────────

    def _get_evergreen_script(self) -> Optional[Dict]:
        evergreen_dir = resolve_path("evergreen_vault")
        evergreen_dir.mkdir(parents=True, exist_ok=True)
        used_dir = evergreen_dir / "used"
        used_dir.mkdir(parents=True, exist_ok=True)

        for selected in list(evergreen_dir.glob("*.json")):
            try:
                with open(selected, "r", encoding="utf-8") as f:
                    script_data = json.load(f)
                if "scenes" in script_data and any(
                    "90%" in str(s.get("text", "")) for s in script_data["scenes"]
                ):
                    jlog("warning", msg=f"☢️ Fichier infecté ('90%') détecté. Destruction: {selected.name}")
                    os.remove(selected)
                    continue
                shutil.move(str(selected), str(used_dir / selected.name))
                if "meta" not in script_data: script_data["meta"] = {}
                script_data["meta"]["is_fallback"] = False
                script_data["meta"]["source"]      = f"evergreen_vault/{selected.name}"
                jlog("success", msg=f"Evergreen: {selected.name}")
                return script_data
            except Exception as e:
                jlog("error", msg=f"Evergreen load failed: {selected.name}", error=str(e))
        return None

    async def _step_1_ideation(self, topic: str, profile_type: str = "INSIDER") -> Dict:
        jlog("step", msg=f"Step 1: Ideation pour '{topic}'")
        sys_prompt   = wrap_v3_prompt(topic, profile_type)
        raw_response = await self._invoke_cli_agent(sys_prompt, context_tag="scripting")
        script_data  = None

        if raw_response:
            if "=== DEBUT SCRIPT ===" in raw_response or "SCENE 1" in raw_response:
                jlog("info", msg="Format structuré détecté → Titanium Regex Parser")
                script_data = self._parse_script_from_text(raw_response)

            if not script_data:
                try:
                    clean_json = raw_response
                    if "```json" in raw_response:
                        clean_json = raw_response.split("```json")[1].split("```")[0]
                    elif "```" in raw_response:
                        clean_json = raw_response.split("```")[1].split("```")[0]
                    possible_json = json.loads(clean_json)
                    if "scenes" in possible_json:
                        script_data = possible_json
                        if script_data and "scenes" in script_data:
                            original_count = len(script_data["scenes"])
                            script_data["scenes"] = [
                                s for s in script_data["scenes"]
                                if not _is_ghost_text(s.get("text", ""))
                            ]
                            purged = original_count - len(script_data["scenes"])
                            if purged > 0:
                                jlog("warning", msg=f"FIX_GHOST_TEXT: {purged} scène(s) fantôme(s) purgée(s).")
                except Exception:
                    pass

        if script_data and "scenes" in script_data:
            if not self._validate_script_density(script_data):
                jlog("warning", msg="Script CLI rejeté par validation densité → Evergreen Vault.")
                script_data = None

        if script_data and "scenes" in script_data:
            nb_scenes = len(script_data["scenes"])
            if nb_scenes > self.MAX_SCENES:
                script_data["scenes"] = script_data["scenes"][:self.MAX_SCENES]
            if "meta" not in script_data: script_data["meta"] = {}
            script_data["meta"]["source"] = "agent_cli_dynamique"
            return script_data

        jlog("warning", msg="CLI parsing échoué ou rejeté → Evergreen Vault...")
        evergreen_script = self._get_evergreen_script()
        if evergreen_script:
            if self._validate_script_density(evergreen_script):
                return evergreen_script
            else:
                jlog("warning", msg="Evergreen rejeté — densité insuffisante.")

        jlog("warning", msg="Engagement Fallback Protocol (Mode Dégradé)")
        fallback_script = self.fallback.generate_script(topic)

        if fallback_script and "scenes" in fallback_script:
            if any("90%" in s.get("text", "") for s in fallback_script["scenes"]):
                fallback_script["scenes"].clear()
                fallback_script["scenes"] = [
                    {"id": 1, "text": f"Sujet du jour : {topic}.", "visual_prompt": "modern abstract", "keywords_overlay": [], "transition": "none"},
                    {"id": 2, "text": "Une analyse stricte s'impose.", "visual_prompt": "data charts", "keywords_overlay": [], "transition": "none"}
                ]
            if "meta" not in fallback_script: fallback_script["meta"] = {}
            fallback_script["meta"]["is_fallback"] = True
            fallback_script["meta"]["source"]      = "fallback_interne"

        return fallback_script

    # ─────────────────────────────────────────────────────────────────────
    # MASTER_NEXUS_V37: ÉTAPE 2 — VISUALS
    # Fond blanc statique unique + B-Roll overlay colorés
    # ─────────────────────────────────────────────────────────────────────

    async def _step_2_visuals(
        self,
        scenes: List[Dict],
    ) -> Tuple[List[str], List[int]]:
        jlog("step", msg="Step 2: Visuels V37 (fond blanc statique + B-Roll overlay)")

        # Diversification des prompts visuels si nécessaire
        scenes = _diversify_visual_prompts(scenes)

        # ── MASTER_NEXUS_V37: FIX #1 — FOND BLANC STATIQUE ───────────────
        # Un seul fond blanc #FFFFFF partagé par TOUTES les scènes.
        # Principe: fond invariant = lisibilité absolue du texte.
        # Les styles premium (dark_navy, pitch_black...) restent dans les B-Roll cards.
        # Les inversions (noir à 12s, navy à 40s) sont gérées par SubtitleBurner.
        BG_WHITE_MASTER = os.path.join(self.root_dir, "bg_white_master_v37.jpg")
        if not os.path.exists(BG_WHITE_MASTER):
            from PIL import Image
            img = Image.new("RGB", (1080, 1920), (255, 255, 255))
            img.save(BG_WHITE_MASTER, quality=98)
            jlog("info", msg="MASTER_NEXUS_V37: Fond blanc maître créé → bg_white_master_v37.jpg")

        # Toutes les scènes partagent le MÊME fond blanc
        asset_paths = [BG_WHITE_MASTER] * len(scenes)
        jlog("info", msg=(
            f"MASTER_NEXUS_V37: {len(scenes)} scènes → fond blanc statique unique "
            f"(élimine les 47 fonds rotatifs de V36)"
        ))

        # ── BRollScheduler V37 (non-mécanique) ───────────────────────────
        broll_indices = _compute_broll_schedule_v37(
            scenes,
            target_ratio = BROLL_TARGET_COVERAGE_RATIO,
            min_gap      = BROLL_MIN_GAP_SCENES,
        )

        broll_available = True
        try:
            from tools.graphics import render_broll_card
        except ImportError:
            broll_available = False

        broll_count    = 0
        broll_rejected = 0
        vault_misses   = 0

        # Tentative de match vault pour les B-Roll réels
        for i, scene in enumerate(scenes):
            raw_prompt   = scene.get("visual_prompt", "")
            clean_prompt = _sanitize_visual_prompt(raw_prompt)

            matched_asset = self.vault.find_best_match(
                clean_prompt,
                context_tags=scene.get("keywords_overlay", []),
                is_hook=(i == 0),
            )

            if matched_asset and os.path.exists(matched_asset.get("local_path", "")) and broll_available:
                img_path = matched_asset["local_path"]
                broll_ok = True

                try:
                    from PIL import Image as _PilImg
                    with _PilImg.open(img_path) as _im:
                        _iw, _ih = _im.size
                    canvas_pixels = 1080 * 1920
                    coverage = (_iw * _ih) / canvas_pixels
                    if coverage > BROLL_MAX_COVERAGE_RATIO:
                        broll_ok = False
                        broll_rejected += 1
                        jlog("warning", msg=f"B-Roll rejeté scène {i} (couverture={coverage:.0%})")
                except Exception:
                    pass

                if broll_ok:
                    self.vault.mark_as_used(img_path)
                    scene["_broll_image_path"] = img_path
                    if i not in broll_indices:
                        broll_indices.append(i)
                        broll_indices.sort()
                    broll_count += 1
            else:
                vault_misses += 1

        # Génération B-Roll procéduraux pour les scènes planifiées sans vault
        for i in broll_indices:
            if i >= len(scenes):
                continue
            scene = scenes[i]
            if scene.get("_broll_image_path") and os.path.exists(scene["_broll_image_path"]):
                continue  # Déjà un asset vault

            broll_path = os.path.join(self.root_dir, f"broll_v37_{i:03d}.jpg")
            try:
                generate_procedural_broll_card(
                    scene_text  = scene.get("text", ""),
                    output_path = broll_path,
                    canvas_w    = 1080,
                    scene_index = i,
                    is_hook     = (i == 0),
                )
                # RÈGLE INVARIANTE: asset_paths[i] = fond blanc (inchangé)
                # scene["_broll_image_path"] = overlay B-Roll uniquement
                scene["_broll_image_path"] = broll_path
                broll_count += 1
                jlog("info", msg=(
                    f"MASTER_NEXUS_V37: B-Roll overlay scène {i} → "
                    f"{Path(broll_path).name} (fond: blanc statique)"
                ))
            except Exception as e:
                jlog("warning", msg=f"B-Roll procédural échoué scène {i}: {e}")

        proc_count = sum(
            1 for i in broll_indices
            if i < len(scenes)
            and 'broll_v37' in str(scenes[i].get("_broll_image_path", ""))
        )
        jlog("info", msg=(
            f"MASTER_NEXUS_V37: Visuels finalisés — "
            f"{broll_count} B-Roll ({proc_count} procéduraux overlay), "
            f"{broll_rejected} rejetés, "
            f"{vault_misses}/{len(scenes)} vault misses"
        ))
        return asset_paths, broll_indices

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 3 : AUDIO
    # ─────────────────────────────────────────────────────────────────────

    async def _step_3_audio(self, scenes: List[Dict], speed: float = 1.0) -> str:
        jlog("step", msg="Step 3: Génération Audio [MASTER_NEXUS_V37]")

        def clean_for_tts(text: str) -> str:
            return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text, flags=re.IGNORECASE).strip()

        is_test_mode = getattr(self.tts, "test_mode", False)

        if is_test_mode:
            jlog("warning", msg="🛡️ TEST MODE / FALLBACK AUDIO ACTIF.")

            estimated_duration = _compute_audio_duration_v36(
                scenes       = scenes,
                speed        = speed,
                min_duration = 30.0,
            )

            dummy_audio_path = os.path.join(self.root_dir, "silence_nexus_v37.mp3")
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(estimated_duration), "-q:a", "9",
                "-acodec", "libmp3lame", dummy_audio_path
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.exists(dummy_audio_path):
                    return dummy_audio_path
                raise FileNotFoundError("FFmpeg n'a pas généré le fichier.")
            except Exception:
                from moviepy.editor import AudioClip
                make_frame   = lambda t: [0, 0]
                silence_clip = AudioClip(make_frame, duration=estimated_duration, fps=44100)
                silence_clip.write_audiofile(dummy_audio_path, logger=None, fps=44100)
                silence_clip.close()
                return dummy_audio_path

        texts_to_read = [clean_for_tts(s.get("text", "")) for s in scenes]
        full_text     = " ".join(texts_to_read)
        audio_path    = await self.tts.generate(full_text, speed=speed)
        if not audio_path or not os.path.exists(audio_path):
            raise Exception("TTS Generation failed in normal mode")
        return audio_path

    # ─────────────────────────────────────────────────────────────────────
    # MASTER_NEXUS_V37: FIX #2 — Pre-render PIL→rawvideo→FFmpeg (×50 speedup)
    # ─────────────────────────────────────────────────────────────────────

    def _prerender_base_video_pil_ffmpeg(
        self,
        visual_assets: List[str],
        durations:     List[float],
        fps:           int   = 30,
        resolution:    Tuple = (1080, 1920),
        run_id:        str   = "default",
    ) -> Optional[str]:
        """
        MASTER_NEXUS_V37: FIX #2 — Pre-render ultra-rapide PIL→rawvideo→FFmpeg.

        Bypass total de MoviePy pour la génération de la vidéo de base.

        Pipeline:
            1. Pour chaque fond JPEG: PIL.Image.open() → resize(1080×1920) → tobytes()
            2. Répliquer le frame (duration × fps) fois → écrire sur stdin FFmpeg
            3. FFmpeg encode H264 ultrafast depuis rawvideo stdin

        Gain vs V36 (_prerender_base_video_ffmpeg avec MoviePy):
            V36: 47 × ImageClip.write_videofile() ≈ 134.9s
            V37: 47 × PIL.open() + pipe rawvideo ≈ 2-4s
            Speedup: ×33-67

        Note: tous les fonds étant identiques en V37 (blanc statique),
        PIL charge UNE image et la réutilise pour toutes les scènes.
        La frame blanche est mise en cache une seule fois → allocation mémoire minimale.
        """
        from PIL import Image

        W, H        = resolution
        output_dir  = self.prerender_dir / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "base_prerendered.mp4")

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f",       "rawvideo",
            "-vcodec",  "rawvideo",
            "-s",       f"{W}x{H}",
            "-pix_fmt", "rgb24",
            "-r",       str(fps),
            "-i",       "pipe:0",
            "-vcodec",  "libx264",
            "-preset",  "ultrafast",
            "-pix_fmt", "yuv420p",
            "-an",                      # Pas d'audio dans la base
            output_path,
        ]

        t0 = time.time()
        jlog("info", msg=(
            f"MASTER_NEXUS_V37: Pre-render PIL→rawvideo "
            f"({len(visual_assets)} scènes, {fps}fps, {W}×{H}) → pipe FFmpeg"
        ))

        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdin  = subprocess.PIPE,
                stdout = subprocess.DEVNULL,
                stderr = subprocess.DEVNULL,
            )
        except Exception as e:
            jlog("error", msg=f"MASTER_NEXUS_V37: Impossible de démarrer FFmpeg: {e}")
            return None

        # Cache des frames PIL (en V37, toutes les scènes ont le même fond blanc)
        _frame_cache: Dict[str, bytes] = {}
        frames_written = 0

        try:
            for img_path, duration in zip(visual_assets, durations):
                n_frames = max(1, int(round(duration * fps)))

                # Cache par chemin de fichier
                if img_path not in _frame_cache:
                    try:
                        img = Image.open(img_path).convert("RGB")
                        if img.size != (W, H):
                            img = img.resize((W, H), Image.LANCZOS)
                        _frame_cache[img_path] = img.tobytes()   # 1080×1920×3 = 6.22 MB
                    except Exception:
                        # Fond blanc de secours si erreur
                        img = Image.new("RGB", (W, H), (255, 255, 255))
                        _frame_cache[img_path] = img.tobytes()

                raw_frame = _frame_cache[img_path]

                for _ in range(n_frames):
                    process.stdin.write(raw_frame)
                    frames_written += 1

            process.stdin.close()
            process.wait(timeout=120)

        except Exception as e:
            jlog("error", msg=f"MASTER_NEXUS_V37: Erreur pipe rawvideo: {e}")
            try:
                process.kill()
            except: pass
            return None

        elapsed = time.time() - t0

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            jlog("error", msg="MASTER_NEXUS_V37: Fichier pré-rendu vide ou absent.")
            return None

        jlog("success", msg=(
            f"MASTER_NEXUS_V37: Base pré-rendue → {Path(output_path).name} "
            f"(Δ={elapsed:.1f}s, {frames_written} frames, "
            f"{len(_frame_cache)} frame(s) unique(s) en cache)"
        ))
        return output_path

    # ─────────────────────────────────────────────────────────────────────
    # MASTER_NEXUS_V37: ÉTAPE 4 — ASSEMBLY
    # ─────────────────────────────────────────────────────────────────────

    async def _step_4_assembly(
        self,
        script_data:   Dict,
        visual_assets: List[str],
        broll_indices: List[int],
        audio_path:    str,
        safe_mode:     bool = False,
    ) -> Optional[str]:
        mode_label = "SAFE MODE" if safe_mode else "V37 MASTER_NEXUS"
        jlog("step", msg=f"Step 4: Assembly [{mode_label}]")

        clips             = []
        subtitle_timeline = []
        broll_schedule: List[Tuple[float, float, str]] = []
        sfx_clips         = []
        final_video_path  = None
        base_clip         = None
        prerendered_path  = None

        try:
            audio_clip     = AudioFileClip(audio_path)
            total_duration = audio_clip.duration
            scenes         = copy.deepcopy(script_data.get("scenes", []))

            if not scenes:
                raise ValueError("Aucune scène dans les données de script clonées.")

            # Purge des ghost texts résiduels
            scenes = [s for s in scenes if not _is_ghost_text(s.get("text", ""))]

            if len(scenes) > 0 and "90%" in scenes[0].get("text", ""):
                raise ValueError("KILL SWITCH : données fantômes résiduelles détectées.")

            min_required_duration = len(scenes) * 0.35
            if total_duration < min_required_duration:
                total_duration = min_required_duration

            def estimate_reading_weight(text: str) -> float:
                clean    = re.sub(r'\[.*?\]', '', text).strip()
                base_len = max(1, len(clean))
                pauses   = (clean.count('.') * 8 + clean.count(',') * 3
                            + clean.count('!') * 5 + clean.count('?') * 5)
                return float(base_len + pauses)

            weights      = [estimate_reading_weight(s.get("text", "")) for s in scenes]
            total_weight = sum(weights)

            if total_weight > 0:
                raw_durations = [(w / total_weight) * total_duration for w in weights]
            else:
                raw_durations = [total_duration / len(scenes) for _ in scenes]

            durations = []
            for s, d in zip(scenes, raw_durations):
                if "[PAUSE]" in s.get("text", "").upper():
                    durations.append(max(d, self.pause_min_duration))
                else:
                    durations.append(d)

            dur_sum = sum(durations)
            if dur_sum > 0:
                durations = [d * (total_duration / dur_sum) for d in durations]
            else:
                durations = [total_duration / len(scenes) for _ in scenes]

            # B-Roll schedule (timestamps absolus)
            cursor_b = 0.0
            for i, d in enumerate(durations):
                if i in broll_indices:
                    img_path = scenes[i].get("_broll_image_path", "")
                    if img_path and os.path.exists(img_path):
                        if d >= self.broll_min_scene_duration:
                            broll_schedule.append((cursor_b, cursor_b + d, img_path))
                cursor_b += d

            # ── MASTER_NEXUS_V37: FIX #2 — Pre-render PIL→rawvideo→FFmpeg ─
            if not safe_mode:
                run_id_str       = datetime.now().strftime("%H%M%S%f")
                prerendered_path = self._prerender_base_video_pil_ffmpeg(
                    visual_assets = visual_assets,
                    durations     = durations,
                    fps           = 30,
                    resolution    = (1080, 1920),
                    run_id        = run_id_str,
                )

            if prerendered_path and os.path.exists(prerendered_path):
                jlog("info", msg="MASTER_NEXUS_V37: Base pré-rendue chargée (O(1) seek actif)")
                base_clip = VideoFileClip(prerendered_path, audio=False)

                if self.enable_slowzoom and not self.enable_micro_zoom:
                    base_clip = self.animator.apply_global_slowzoom(
                        base_clip,
                        start_scale=VIRTUAL_CAMERA_ZOOM_START,
                        end_scale=VIRTUAL_CAMERA_ZOOM_END,
                    )
                if self.enable_motion_blur:
                    base_clip = self.animator.apply_motion_blur(base_clip, strength=0.35)

                video_track = base_clip

            else:
                # Fallback: MoviePy classique si pré-render échoué
                jlog("warning", msg="MASTER_NEXUS_V37: Fallback MoviePy (pré-render PIL indisponible)")

                if safe_mode:
                    for img_path, dur in zip(visual_assets, durations):
                        if not os.path.isfile(str(img_path)): continue
                        clip = ImageClip(str(img_path)).set_duration(dur)
                        clip = clip.resize(height=1920)
                        if clip.w < 1080: clip = clip.resize(width=1080)
                        clips.append(clip.set_position("center"))
                else:
                    scenes_since_last_trans = 0
                    for i, (img_path, dur) in enumerate(zip(visual_assets, durations)):
                        if not os.path.isfile(str(img_path)): continue
                        scene_transition = scenes[i].get("transition", "none") if i < len(scenes) else "none"
                        clip = self.animator.create_scene(
                            img_path, dur + 0.1,
                            effect=None, resolution=(1080, 1920), apply_mutation=False,
                        )
                        if self.enable_micro_zoom:
                            clip = self.animator.apply_micro_zoom_continuous(
                                clip, intensity=self.micro_zoom_intensity
                            )
                        if scene_transition == "none" and scenes_since_last_trans >= 3:
                            scene_transition = random.choice(["slide", "fade"])
                        if i > 0 and len(clips) > 0:
                            transition_applied = False
                            if scene_transition == "slide" and self.enable_slide_trans:
                                try:
                                    direction = self.animator.get_slide_direction(i)
                                    trans     = self.animator.create_slide_transition(
                                        clips[-1], clip, transition_duration=0.28,
                                        direction=direction, spring=True,
                                    )
                                    clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.28))
                                    clips.append(trans.set_duration(0.28))
                                    transition_applied = True
                                except Exception: pass
                            elif scene_transition == "fade" and self.enable_fade_trans:
                                try:
                                    trans = self.animator.create_fade_transition(
                                        clips[-1], clip, transition_duration=0.10
                                    )
                                    clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.10))
                                    clips.append(trans.set_duration(0.10))
                                    transition_applied = True
                                except Exception: pass
                            scenes_since_last_trans = 0 if transition_applied else scenes_since_last_trans + 1
                        clips.append(clip)

                if not clips:
                    raise Exception("Aucun clip valide généré (fallback MoviePy)")

                video_track = concatenate_videoclips(clips, method="compose")

                if self.enable_slowzoom and not safe_mode and not self.enable_micro_zoom:
                    video_track = self.animator.apply_global_slowzoom(
                        video_track,
                        start_scale=VIRTUAL_CAMERA_ZOOM_START,
                        end_scale=VIRTUAL_CAMERA_ZOOM_END,
                    )
                if self.enable_motion_blur and not safe_mode:
                    video_track = self.animator.apply_motion_blur(video_track, strength=0.35)

            # ── Timeline sous-titres ──────────────────────────────────────
            cursor = 0.0
            for i, d in enumerate(durations):
                subtitle_timeline.append((cursor, cursor + d, scenes[i].get("text", "")))
                cursor += d

            is_tts_test_mode = getattr(self.tts, "test_mode", False)

            if not is_tts_test_mode and self.subtitle_burner.available:
                try:
                    word_timeline = self.subtitle_burner.transcribe_to_timeline(audio_path)
                    if word_timeline and len(word_timeline) > 0:
                        min_expected = total_duration * self.MIN_WHISPER_WORDS_PER_SECOND
                        if len(word_timeline) >= min_expected:
                            subtitle_timeline = word_timeline
                except Exception:
                    pass

            # MASTER_NEXUS_V37: FIX #3 — Timeline synthétique humanisée
            if not _is_word_level_timeline(subtitle_timeline):
                jlog("warning", msg=(
                    "MASTER_NEXUS_V37: Timeline scène → "
                    "découpage synthétique HUMANISÉ (syllabes + jitter ±15%)."
                ))
                subtitle_timeline = _build_synthetic_word_timeline_humanized(subtitle_timeline)
                jlog("success", msg=(
                    f"MASTER_NEXUS_V37: Timeline humanisée → "
                    f"{len(subtitle_timeline)} mots avec variabilité syllabique."
                ))

            before_gap        = len(subtitle_timeline)
            subtitle_timeline = _close_word_gaps(subtitle_timeline)
            jlog("info", msg=f"MOTION_ENGINE_V32: Gaps inter-mots comblés ({before_gap} mots).")

            subtitle_timeline = _apply_anticipation_offset(
                subtitle_timeline,
                offset=AUDIO_ANTICIPATION_OFFSET,
            )
            jlog("info", msg=(
                f"MOTION_ENGINE_V32: Anticipation audio appliquée "
                f"({AUDIO_ANTICIPATION_OFFSET*1000:.0f}ms) sur {len(subtitle_timeline)} mots."
            ))

            # ── SFX ───────────────────────────────────────────────────────
            sfx_cursor = 0.0
            for i, d in enumerate(durations):
                scene_text = scenes[i].get("text", "")
                sfx_type   = self.subtitle_burner.get_sfx_type(scene_text)
                if sfx_type is not None:
                    sfx_path = (self.vault.get_random_sfx(sfx_type) or
                                self.vault.get_random_sfx("click") or
                                self.vault.get_random_sfx("pop"))
                    if sfx_path and os.path.exists(sfx_path):
                        try:
                            vol_map = {"click_deep": 0.28, "click": 0.22, "swoosh": 0.13}
                            vol     = vol_map.get(sfx_type, 0.18)
                            sfx_c   = AudioFileClip(sfx_path).volumex(vol).set_start(sfx_cursor)
                            sfx_clips.append(sfx_c)
                        except Exception: pass
                sfx_cursor += d

            if sfx_clips:
                final_audio = CompositeAudioClip([audio_clip] + sfx_clips)
                video_track = video_track.set_audio(final_audio).set_duration(total_duration)
            else:
                video_track = video_track.set_audio(audio_clip).set_duration(total_duration)

            # ── SubtitleBurner ────────────────────────────────────────────
            final_clip = self.subtitle_burner.burn_subtitles(
                video_clip     = video_track,
                timeline       = subtitle_timeline,
                broll_schedule = broll_schedule,
            )

            # ── Export final ──────────────────────────────────────────────
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            unique_hash = str(uuid.uuid4())[:6]
            suffix      = "_SAFE" if safe_mode else "_V37_MASTER"
            filename    = f"nexus_final_{timestamp}_{unique_hash}{suffix}.mp4"
            output_path = os.path.join(self.root_dir, filename)

            final_clip.write_videofile(
                output_path,
                fps         = 24 if safe_mode else 30,
                codec       = "libx264",
                audio_codec = "aac",
                preset      = "ultrafast",
                threads     = 8,
                logger      = None,
            )

            final_clip.close()
            audio_clip.close()
            if base_clip:
                try: base_clip.close()
                except: pass
            for c in clips:
                try: c.close()
                except: pass

            # Nettoyage pré-render
            if prerendered_path and os.path.exists(prerendered_path):
                try: os.remove(prerendered_path)
                except: pass

            final_video_path = output_path
            jlog("success", msg=f"✅ Vidéo V37 MASTER_NEXUS générée : {filename}")

        except Exception as e:
            if not safe_mode:
                jlog("error", msg="HQ render failed → Safe Mode activé.", error=str(e))
                return await self._step_4_assembly(
                    script_data, visual_assets, broll_indices, audio_path, safe_mode=True,
                )
            else:
                jlog("fatal", msg="Assembly failure absolu", error=str(e))
                return None

        return final_video_path

    # ─────────────────────────────────────────────────────────────────────
    # LIVRAISON
    # ─────────────────────────────────────────────────────────────────────

    async def _deliver_package(self, video_path: str, script_data: Dict):
        meta  = script_data.get("meta", {})
        title = meta.get("title", "Video Finance")
        tags  = meta.get("tags", [])
        for t in ["trading", "propfirm", "finance", "business"]:
            if t not in tags: tags.append(t)

        meta_path = video_path.replace(".mp4", ".json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "title":       title,
                "description": meta.get("description", ""),
                "tags":        tags,
                "file":        video_path,
                "created_at":  str(datetime.now()),
            }, f, indent=2)
        jlog("info", msg=f"Package livré: {Path(video_path).name}")

    # ─────────────────────────────────────────────────────────────────────
    # MODE DA (FAST TEST)
    # ─────────────────────────────────────────────────────────────────────

    async def run_da_mode(self, script_data: Optional[Dict] = None):
        jlog("info", msg="🎨 FAST DA TEST MODE V37 ACTIVATED")

        if not script_data:
            topic       = await self._step_0_brainstorm_topic()
            script_data = await self._step_1_ideation(topic, "INSIDER")

        if not script_data or not script_data.get("scenes"):
            jlog("error", msg="DA Mode: Impossible de récupérer un vrai script.")
            return

        audio_path = os.path.join(self.root_dir, "temp_audio.mp3")
        if not os.path.exists(audio_path):
            audio_path = await self._step_3_audio(script_data["scenes"], speed=1.0)

        imgs, broll_indices = await self._step_2_visuals(script_data["scenes"])
        vid = await self._step_4_assembly(script_data, imgs, broll_indices, audio_path, safe_mode=False)

        if vid:
            jlog("success", msg=f"✅ Test DA V37 terminé: {vid}")

    # ─────────────────────────────────────────────────────────────────────
    # INGESTION MANUELLE
    # ─────────────────────────────────────────────────────────────────────

    async def _process_manual_ingestion(self, video_file: Path):
        jlog("info", msg=f"Ingestion manuelle: {video_file.name}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{video_file.stem}_{timestamp}{video_file.suffix}"
        dest      = self.root_dir / safe_name
        shutil.move(str(video_file), str(dest))

        possible_meta = video_file.with_suffix('.json')
        if possible_meta.exists():
            shutil.move(str(possible_meta), str(dest.with_suffix('.json')))
        else:
            smart_meta    = self._heuristic_tagging(video_file.name)
            prompt_manual = get_manual_ingestion_prompt(video_file.name)
            raw_ai        = await self._invoke_cli_agent(prompt_manual, "manual_meta")
            if raw_ai:
                try:
                    json_match = re.search(r'\{.*?\}', raw_ai, re.DOTALL)
                    if json_match:
                        ai_data = json.loads(json_match.group(0))
                        smart_meta.update(ai_data)
                except Exception:
                    pass
            smart_meta["file"] = str(dest)
            with open(dest.with_suffix('.json'), "w", encoding="utf-8") as f:
                json.dump(smart_meta, f, indent=2)

    # ─────────────────────────────────────────────────────────────────────
    # MAIN LOOP
    # ─────────────────────────────────────────────────────────────────────

    async def run_daemon(self):
        jlog("info", msg="Nexus Brain Daemon Started (V37 MASTER_NEXUS)")

        while True:
            manual_files = sorted(list(self.hot_root.glob("*.*")))
            videos       = [f for f in manual_files if f.suffix.lower() in ['.mp4', '.mov', '.avi']]
            if videos:
                await self._process_manual_ingestion(videos[0])
                continue

            smart_wait = self._get_smart_sleep_duration()
            if smart_wait > 300:
                await asyncio.sleep(smart_wait)
                continue

            current_date = datetime.now().strftime("%Y-%m-%d")
            try:
                topic  = await self._step_0_brainstorm_topic()
                script = await self._step_1_ideation(topic, "INSIDER")

                if (script
                        and "scenes" in script
                        and isinstance(script["scenes"], list)
                        and len(script["scenes"]) > 0):

                    if script.get("meta", {}).get("is_fallback", False):
                        await asyncio.sleep(300)
                        continue

                    speed = script.get("meta", {}).get("tts_speed", 1.0)

                    imgs, broll_indices = await self._step_2_visuals(script["scenes"])
                    audio_path          = await self._step_3_audio(script["scenes"], speed)
                    vid = await self._step_4_assembly(script, imgs, broll_indices, audio_path)

                    if vid:
                        await self._deliver_package(vid, script)
                        self.last_run_date = current_date
                        jlog("success", msg=f"Cycle complet V37: {current_date}")
                else:
                    jlog("error", msg="Script invalide (pas de 'scenes'). Abandon du cycle.")

            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                jlog("info", msg="Brain arrêté par l'utilisateur.")
                sys.exit(0)
            except Exception as e:
                jlog("error", msg="Erreur cycle auto", error=str(e))
                await asyncio.sleep(300)

            await asyncio.sleep(60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Nexus Brain V37 (MASTER_NEXUS)")
    parser.add_argument("--da", action="store_true", help="Mode DA test sans API.")
    args, _ = parser.parse_known_args()

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    brain = NexusBrain()
    try:
        if args.da:
            asyncio.run(brain.run_da_mode())
        else:
            asyncio.run(brain.run_daemon())
    except KeyboardInterrupt:
        jlog("info", msg="Brain arrêté (Graceful exit).")
        sys.exit(0)