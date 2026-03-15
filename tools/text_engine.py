# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Moteur de classification et de style du texte.
#
# PARADIGME CLÉ (rupture avec V9) :
#   V9 : groupe les mots en "phrases" (3-5 mots)
#   V22 : UN MOT PAR FRAME — c'est ce que la référence utilise systématiquement.
#
# MESURES RÉFÉRENCE :
#   - Chaque word dure exactement sa durée audio (pas de padding artificiel)
#   - Stop words  : gris rgb(160,160,160), poids "regular"
#   - Mots normaux: quasi-noir rgb(17,17,17), poids "semibold"
#   - Mots ACCENT : gradient violet→mauve, poids "bold"
#   - Mots MUTED  : rouge rgb(230,45,35), poids "bold"
#   - Chiffres    : vert rgb(0,208,132), poids "bold", taille +20%

from __future__ import annotations
import re
from typing import List, Tuple

from .config import (
    TEXT_RGB, TEXT_DIM_RGB, ACCENT_RGB, MUTED_RGB,
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED, IMPACT_WORDS, RE_NUMERIC,
)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Classification Sémantique
# ══════════════════════════════════════════════════════════════════════════════

class WordClass:
    STOP   = "STOP"     # Stop word → gris, regular
    NORMAL = "NORMAL"   # Mot standard → quasi-noir, semibold
    ACCENT = "ACCENT"   # Mot positif → gradient violet, bold
    MUTED  = "MUTED"    # Mot négatif → rouge, bold
    BADGE  = "BADGE"    # Chiffre/valeur → vert, bold, taille+
    PAUSE  = "PAUSE"    # Silence audio → aucun rendu


def classify_word(text: str) -> str:
    """
    ARCHITECTURE_MASTER_V22 : Classification sémantique d'un mot.

    Priorité de détection :
        1. PAUSE   (marqueur explicite)
        2. BADGE   (chiffres, symboles monétaires)
        3. ACCENT  (mots positifs de la liste)
        4. MUTED   (mots négatifs de la liste)
        5. STOP    (articles, prépositions, etc.)
        6. NORMAL  (tout le reste)
    """
    clean = text.strip().lower().rstrip(".,!?:;'\"")

    if "[PAUSE]" in text.upper() or text.strip() in ("…", "..."):
        return WordClass.PAUSE

    if RE_NUMERIC.search(text):
        return WordClass.BADGE

    # ARCHITECTURE_MASTER_V22 : MUTED prioritaire sur ACCENT (un mot négatif
    # comme "crash" ne peut pas être classé positif même s'il est dans IMPACT_WORDS)
    if clean in KEYWORDS_MUTED:
        return WordClass.MUTED

    if clean in KEYWORDS_ACCENT or clean in IMPACT_WORDS:
        return WordClass.ACCENT

    if clean in STOP_WORDS:
        return WordClass.STOP

    return WordClass.NORMAL


def get_word_style(word_class: str, base_size: int) -> Tuple[int, str, tuple, bool]:
    """
    ARCHITECTURE_MASTER_V22 : Retourne (fontsize, weight, color, use_gradient).

    use_gradient=True  → appeler render_text_gradient() au lieu de render_text_solid()

    Calibration depuis la référence :
        STOP   : size × 0.85, regular,  rgb(160,160,160), no gradient
        NORMAL : size × 1.00, semibold, rgb(17,17,17),    no gradient
        ACCENT : size × 1.10, bold,     gradient,          YES gradient
        MUTED  : size × 1.10, bold,     rgb(230,45,35),   no gradient
        BADGE  : size × 1.25, bold,     rgb(0,208,132),   no gradient
    """
    if word_class == WordClass.STOP:
        return (max(20, int(base_size * 0.85)), "regular",  TEXT_DIM_RGB,       False)
    if word_class == WordClass.NORMAL:
        return (max(20, int(base_size * 1.00)), "semibold", TEXT_RGB,            False)
    if word_class == WordClass.ACCENT:
        return (max(20, int(base_size * 1.10)), "bold",     TEXT_RGB,            True)
    if word_class == WordClass.MUTED:
        return (max(20, int(base_size * 1.10)), "bold",     MUTED_RGB,           False)
    if word_class == WordClass.BADGE:
        return (max(20, int(base_size * 1.25)), "bold",     ACCENT_RGB,          False)
    # NORMAL par défaut
    return (base_size, "semibold", TEXT_RGB, False)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Groupement Temporel (1 mot = 1 groupe dans la référence)
# ══════════════════════════════════════════════════════════════════════════════

def split_to_single_words(
    timeline: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
    """
    ARCHITECTURE_MASTER_V22 : Découpage mot-à-mot.

    La référence montre systématiquement UN mot à la fois.
    Si whisper donne des chunks multi-mots, on les redécoupe
    en proportionnant la durée sur le nombre de caractères.

    Input  : [(t_start, t_end, "deux mots"), ...]
    Output : [(t_start, t_mid, "deux"), (t_mid, t_end, "mots"), ...]
    """
    result = []
    for t_start, t_end, text in timeline:
        clean = text.strip()
        if not clean or "[PAUSE]" in clean.upper():
            result.append((t_start, t_end, "[PAUSE]"))
            continue

        words    = clean.split()
        duration = t_end - t_start
        if not words:
            continue

        if len(words) == 1:
            result.append((t_start, t_end, words[0]))
            continue

        # Durée proportionnelle au nombre de caractères
        total_chars = sum(len(w) for w in words)
        t = t_start
        for i, w in enumerate(words):
            ratio  = len(w) / max(total_chars, 1)
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
    ARCHITECTURE_MASTER_V22 : Mode phrase (héritage V9).
    Conservé pour rétrocompatibilité mais NON utilisé dans le burner principal.
    La référence utilise split_to_single_words().
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