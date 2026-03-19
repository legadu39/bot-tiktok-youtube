# -*- coding: utf-8 -*-
# NEXUS_MASTER_V38: Moteur de classification et de style du texte.
#
# DELTA V38 vs V23:
#
#   FIX #1 — regroup_stop_with_next() (NOUVEAU):
#     V23: split_to_single_words() décompose TOUT en mots uniques.
#          "le meilleur" → ["le", "meilleur"] affichés séquentiellement.
#     V38: regroup_stop_with_next() fusionne article/préposition + mot suivant
#          "le meilleur" → ["le meilleur"] affiché comme un bloc.
#          Préserve le timing: t_start du premier, t_end du second.
#
#   FIX #2 — get_word_style() utilise get_effective_fs_base():
#     V23: FS_BASE hardcodé = toujours 70px même avec font fallback.
#     V38: get_effective_fs_base() retourne 50px si font dégradée.
#
#   CONSERVÉ V23:
#     classify_word(), WordClass, split_to_single_words(), group_into_phrases().

from __future__ import annotations
import re
from typing import List, Tuple

from .config import (
    TEXT_RGB, TEXT_DIM_RGB, ACCENT_RGB, MUTED_RGB,
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED, IMPACT_WORDS, RE_NUMERIC,
    FS_BASE, FS_MIN,
    FS_ACCENT_SCALE, FS_STOP_SCALE, FS_MUTED_SCALE, FS_BADGE_SCALE, FS_BOLD_SCALE,
    get_effective_fs_base,
)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Classification Sémantique
# ══════════════════════════════════════════════════════════════════════════════

class WordClass:
    STOP   = "STOP"
    NORMAL = "NORMAL"
    ACCENT = "ACCENT"
    MUTED  = "MUTED"
    BADGE  = "BADGE"
    PAUSE  = "PAUSE"


RE_BADGE = re.compile(r'[\d\$€£%]|^\d+[kKmM]?$|^\d+[\.,]\d+$', re.IGNORECASE)

def classify_word(text: str) -> str:
    """
    Classification sémantique mot.
    Priorité: PAUSE > BADGE > MUTED > ACCENT > STOP > NORMAL
    """
    if not text:
        return WordClass.NORMAL

    raw = text.strip()
    clean = re.sub(r'\[.*?\]', '', raw).strip().lower().rstrip(".,!?:;'\"«»")

    if "[PAUSE]" in raw.upper() or raw in ("…", "...", "—"):
        return WordClass.PAUSE

    if RE_BADGE.search(raw):
        return WordClass.BADGE

    if clean in KEYWORDS_MUTED:
        return WordClass.MUTED

    if clean in KEYWORDS_ACCENT or clean in IMPACT_WORDS:
        return WordClass.ACCENT

    if clean in STOP_WORDS:
        return WordClass.STOP

    return WordClass.NORMAL


def get_word_style(word_class: str, base_size: int = None) -> Tuple[int, str, tuple, bool]:
    """
    NEXUS_MASTER_V38: Retourne (fontsize, weight, color, use_gradient).
    Utilise get_effective_fs_base() pour adapter la taille à la font active.
    """
    if base_size is None:
        base_size = get_effective_fs_base()

    if word_class == WordClass.STOP:
        return (max(FS_MIN, int(base_size * FS_STOP_SCALE)), "regular",  TEXT_DIM_RGB, False)
    if word_class == WordClass.NORMAL:
        return (max(FS_MIN, int(base_size * 1.00)),          "semibold", TEXT_RGB,     False)
    if word_class == WordClass.ACCENT:
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
    Découpage mot-à-mot.
    La référence montre UN mot à la fois, timing calqué sur Whisper.
    """
    result = []
    for t_start, t_end, text in timeline:
        clean = text.strip()
        if not clean:
            continue

        if "[PAUSE]" in clean.upper() or clean in ("…", "..."):
            result.append((t_start, t_end, "[PAUSE]"))
            continue

        words = clean.split()
        if not words:
            continue

        duration = t_end - t_start

        if len(words) == 1:
            result.append((t_start, t_end, words[0]))
            continue

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


# ══════════════════════════════════════════════════════════════════════════════
# NEXUS_MASTER_V38: BLOC 2B — Regroupement Stop Words
# ══════════════════════════════════════════════════════════════════════════════

def regroup_stop_with_next(
    words: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
    """
    NEXUS_MASTER_V38: Regroupe article/préposition avec le mot suivant.

    Vidéo référence: "le meilleur" apparaît comme UN SEUL bloc à l'écran.
    V37: "le" puis "meilleur" → deux écrans séparés (stop word isolé = vide visuel).
    V38: "le meilleur" → un seul écran, timing fusionné.

    Règles:
        1. Si mot[i] ∈ STOP_WORDS ET mot[i+1] existe ET mot[i+1] ∉ STOP_WORDS:
           → Fusionner en "{mot[i]} {mot[i+1]}" avec t_start[i], t_end[i+1]
        2. Si mot[i] ∈ STOP_WORDS ET mot[i+1] ∈ STOP_WORDS:
           → Ne pas fusionner (deux stop words consécutifs = trop long)
        3. Si mot[i] est un [PAUSE], ne jamais fusionner.
        4. Maximum 3 mots par groupe (évite les blocs trop longs).

    Exemples:
        ["le", "meilleur"]      → ["le meilleur"]
        ["dérange", "de"]       → ["dérange de"]        (postposition)
        ["de", "la", "marque"]  → ["de", "la marque"]   (stop+stop→skip, stop+nom→fuse)
        ["c'est", "le", "prix"] → ["c'est", "le prix"]
    """
    if not words:
        return words

    result = []
    i = 0

    while i < len(words):
        t_s, t_e, w = words[i]
        clean = re.sub(r'\[.*?\]', '', w).strip().lower().rstrip(".,!?:;")

        # Marqueur PAUSE → jamais fusionner
        if "[PAUSE]" in w.upper() or w in ("…", "...", "—"):
            result.append((t_s, t_e, w))
            i += 1
            continue

        # Si c'est un stop word ET il y a un mot suivant
        if clean in STOP_WORDS and i + 1 < len(words):
            t_s2, t_e2, w2 = words[i + 1]
            clean2 = re.sub(r'\[.*?\]', '', w2).strip().lower().rstrip(".,!?:;")

            # Ne pas fusionner si le suivant est aussi un stop word
            # (sinon on aurait "de la" qui n'est pas mieux que "de" seul)
            if clean2 not in STOP_WORDS and "[PAUSE]" not in w2.upper():
                # Fusion: "le" + "meilleur" → "le meilleur"
                merged = f"{w} {w2}"
                result.append((t_s, t_e2, merged))
                i += 2
                continue

        # NEXUS_MASTER_V38: Vérifier aussi si le MOT SUIVANT est un stop word
        # isolé en position finale (ex: "dérange de" → fusionner)
        if i + 1 < len(words):
            t_s2, t_e2, w2 = words[i + 1]
            clean2 = re.sub(r'\[.*?\]', '', w2).strip().lower().rstrip(".,!?:;")
            if clean2 in STOP_WORDS and clean not in STOP_WORDS:
                # Le mot suivant est un stop word orphelin → l'absorber
                # Ex: "dérange" + "de" → "dérange de"
                # Mais seulement si c'est le dernier ou si le mot d'après n'est pas un stop
                absorb = False
                if i + 2 >= len(words):
                    absorb = True  # Dernier stop word → toujours absorber
                elif i + 2 < len(words):
                    t_s3, t_e3, w3 = words[i + 2]
                    clean3 = re.sub(r'\[.*?\]', '', w3).strip().lower().rstrip(".,!?:;")
                    if clean3 not in STOP_WORDS:
                        # Le mot d'après le stop n'est PAS un stop → c'est mieux
                        # de laisser le stop se fusionner avec ce mot d'après
                        absorb = False
                    else:
                        absorb = True

                if absorb:
                    merged = f"{w} {w2}"
                    result.append((t_s, t_e2, merged))
                    i += 2
                    continue

        # Pas de fusion → conserver tel quel
        result.append((t_s, t_e, w))
        i += 1

    return result


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 3 — Mode phrase (rétrocompatibilité)
# ══════════════════════════════════════════════════════════════════════════════

def group_into_phrases(
    timeline:       List[Tuple[float, float, str]],
    max_chars:      int = 28,
    max_per_group:  int = 5,
) -> List[List[Tuple[float, float, str]]]:
    """
    Mode phrase (rétrocompatibilité V9). NON utilisé dans le pipeline principal.
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