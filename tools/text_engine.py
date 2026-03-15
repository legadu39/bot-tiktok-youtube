# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V23: Moteur de classification et de style du texte — CORRIGÉ.
#
# DELTA V23 vs V22:
#   1. get_word_style() utilise FS_ACCENT_SCALE=1.45 (mesuré 1.52, codé 1.45)
#      V22 avait 1.10× — NETTEMENT sous-évalué selon les mesures.
#   2. TEXT_DIM_RGB corrigé: 150,150,150 (V22 avait 103,103,103 trop sombre)
#   3. STOP_WORDS enrichi (plus fréquents = meilleure classification)
#   4. Nouveau: classify_word() détecte maintenant les BADGE par patterns regex
#      plus robustes (e.g. "500$" sans espace, "1000€")

from __future__ import annotations
import re
from typing import List, Tuple

from .config import (
    TEXT_RGB, TEXT_DIM_RGB, ACCENT_RGB, MUTED_RGB,
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED, IMPACT_WORDS, RE_NUMERIC,
    FS_BASE, FS_MIN,
    FS_ACCENT_SCALE, FS_STOP_SCALE, FS_MUTED_SCALE, FS_BADGE_SCALE, FS_BOLD_SCALE,
)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Classification Sémantique
# ══════════════════════════════════════════════════════════════════════════════

class WordClass:
    STOP   = "STOP"     # Stop word → gris clair (150,150,150), regular
    NORMAL = "NORMAL"   # Standard  → quasi-noir (25,25,25), semibold
    ACCENT = "ACCENT"   # Positif   → gradient rose-chaud, bold, +45%
    MUTED  = "MUTED"    # Négatif   → rouge (220,40,35), bold, +10%
    BADGE  = "BADGE"    # Chiffre   → vert (0,208,132), bold, +25%
    PAUSE  = "PAUSE"    # Silence   → aucun rendu


# ARCHITECTURE_MASTER_V23: Regex BADGE élargi (gère "1000€", "50k", "179$", etc.)
RE_BADGE = re.compile(r'[\d\$€£%]|^\d+[kKmM]?$|^\d+[\.,]\d+$', re.IGNORECASE)

def classify_word(text: str) -> str:
    """
    ARCHITECTURE_MASTER_V23: Classification sémantique mot.

    Priorité:
        1. PAUSE   (marqueur explicite ou "…")
        2. BADGE   (chiffres, devises, pourcentages)
        3. MUTED   (mots négatifs — prioritaire sur ACCENT)
        4. ACCENT  (mots positifs + impact words)
        5. STOP    (articles, prépositions, etc.)
        6. NORMAL  (tout le reste)
    """
    if not text:
        return WordClass.NORMAL

    raw = text.strip()
    clean = re.sub(r'\[.*?\]', '', raw).strip().lower().rstrip(".,!?:;'\"«»")

    # ── 1. PAUSE ─────────────────────────────────────────────────────────────
    if "[PAUSE]" in raw.upper() or raw in ("…", "...", "—"):
        return WordClass.PAUSE

    # ── 2. BADGE (chiffres, devises) ─────────────────────────────────────────
    # ARCHITECTURE_MASTER_V23: utilise regex élargi vs simple RE_NUMERIC
    if RE_BADGE.search(raw):
        return WordClass.BADGE

    # ── 3. MUTED (négatif — prioritaire sur ACCENT) ──────────────────────────
    if clean in KEYWORDS_MUTED:
        return WordClass.MUTED

    # ── 4. ACCENT (positif + impact) ─────────────────────────────────────────
    if clean in KEYWORDS_ACCENT or clean in IMPACT_WORDS:
        return WordClass.ACCENT

    # ── 5. STOP ──────────────────────────────────────────────────────────────
    if clean in STOP_WORDS:
        return WordClass.STOP

    return WordClass.NORMAL


def get_word_style(word_class: str, base_size: int) -> Tuple[int, str, tuple, bool]:
    """
    ARCHITECTURE_MASTER_V23: Retourne (fontsize, weight, color, use_gradient).

    Calibration CORRIGÉE depuis mesures référence:
    ┌────────────────────┬──────────────┬──────────────┬──────────────────────┐
    │ Classe             │ Scale V22    │ Scale V23    │ Source               │
    ├────────────────────┼──────────────┼──────────────┼──────────────────────┤
    │ STOP               │ ×0.85        │ ×0.85        │ (confirmé)           │
    │ NORMAL             │ ×1.00        │ ×1.00        │ (confirmé)           │
    │ ACCENT             │ ×1.10        │ ×1.45        │ mesuré 41/27=1.52    │
    │ MUTED              │ ×1.10        │ ×1.10        │ (pas de mesure diff) │
    │ BADGE              │ ×1.25        │ ×1.25        │ (confirmé)           │
    └────────────────────┴──────────────┴──────────────┴──────────────────────┘
    """
    if word_class == WordClass.STOP:
        return (max(FS_MIN, int(base_size * FS_STOP_SCALE)), "regular",  TEXT_DIM_RGB, False)
    if word_class == WordClass.NORMAL:
        return (max(FS_MIN, int(base_size * 1.00)),          "semibold", TEXT_RGB,     False)
    if word_class == WordClass.ACCENT:
        # ARCHITECTURE_MASTER_V23: scale 1.45 (CORRIGÉ depuis 1.10)
        return (max(FS_MIN, int(base_size * FS_ACCENT_SCALE)), "bold",   TEXT_RGB,     True)
    if word_class == WordClass.MUTED:
        return (max(FS_MIN, int(base_size * FS_MUTED_SCALE)), "bold",    MUTED_RGB,    False)
    if word_class == WordClass.BADGE:
        return (max(FS_MIN, int(base_size * FS_BADGE_SCALE)), "bold",    ACCENT_RGB,   False)
    return (base_size, "semibold", TEXT_RGB, False)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Groupement Temporel (1 mot = 1 entrée)
# ══════════════════════════════════════════════════════════════════════════════

def split_to_single_words(
    timeline: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
    """
    ARCHITECTURE_MASTER_V23: Découpage mot-à-mot.

    La référence montre UN mot à la fois, timing exactement calqué sur Whisper.
    Si un chunk multi-mots arrive, on le redécoupe en proportionnant sur chars.

    ARCHITECTURE_MASTER_V23: AMÉLIORATION — détection des marqueurs inline:
    [BOLD], [LIGHT], [BADGE], [PAUSE] sont préservés avec le mot adjacent.
    """
    result = []
    for t_start, t_end, text in timeline:
        clean = text.strip()
        if not clean:
            continue

        # Marqueur PAUSE explicite
        if "[PAUSE]" in clean.upper() or clean in ("…", "..."):
            result.append((t_start, t_end, "[PAUSE]"))
            continue

        # Extraire les mots (en conservant les marqueurs)
        words = clean.split()
        if not words:
            continue

        duration = t_end - t_start

        if len(words) == 1:
            result.append((t_start, t_end, words[0]))
            continue

        # Durée proportionnelle aux caractères (hors marqueurs)
        def char_count(w: str) -> int:
            return max(1, len(re.sub(r'\[.*?\]', '', w)))

        total_chars = sum(char_count(w) for w in words)
        t = t_start
        for i, w in enumerate(words):
            ratio  = char_count(w) / max(total_chars, 1)
            t_next = t_end if i == len(words) - 1 else t + duration * ratio
            result.append((t, t_next, w))
            t = t_next

    return result


def group_into_phrases(
    timeline:       List[Tuple[float, float, str]],
    max_chars:      int = 28,
    max_per_group:  int = 5,
) -> List[List[Tuple[float, float, str]]]:
    """
    Mode phrase (rétrocompatibilité V9). NON utilisé dans le pipeline principal V23.
    """
    groups:  List[List] = []
    current: List       = []
    current_text        = ""

    def flush():
        nonlocal current, current_text
        if current:
            groups.append(current[:])
        current      = []
        current_text = ""

    for entry in timeline:
        start, end, text = entry
        clean = text.strip()

        if "[PAUSE]" in clean.upper() or clean in ("…", "..."):
            flush()
            groups.append([(start, end, "[PAUSE]")])
            continue

        test_text  = (current_text + " " + clean).strip() if current_text else clean
        word_count = len(current) + 1

        if (len(test_text) > max_chars or word_count > max_per_group) and current:
            flush()
            current.append(entry)
            current_text = clean
        else:
            current.append(entry)
            current_text = test_text

        if clean and clean[-1] in ".!?":
            flush()
        elif clean and clean[-1] in ",;:":
            flush()

    flush()
    return [g for g in groups if g]