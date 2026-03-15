# -*- coding: utf-8 -*-
import re
from typing import List, Tuple

from .config import (
    TEXT_RGB, TEXT_DIM_RGB, ACCENT_RGB, MUTED_RGB,
    RE_NUMERIC, IMPACT_WORDS
)

def compute_phrase_style(text: str, sem: str, base_size: int) -> Tuple[int, str, tuple]:
    clean  = re.sub(r'[^\w\$€%]', '', text.lower())
    letters = re.sub(r'[^a-zA-ZÀ-ÿ]', '', clean)

    if RE_NUMERIC.search(text):
        return (max(20, int(base_size * 1.20)), "bold", ACCENT_RGB)
    if len(letters) <= 3:
        return (max(20, int(base_size * 0.70)), "regular", TEXT_DIM_RGB)
    if clean in IMPACT_WORDS:
        return (max(20, int(base_size * 1.25)), "extrabold", TEXT_RGB)
    if sem == "ACCENT":
        return (max(20, int(base_size * 1.15)), "bold", ACCENT_RGB)
    if sem == "MUTED":
        return (max(20, int(base_size * 1.15)), "bold", MUTED_RGB)
    if sem == "ACTION":
        return (max(20, int(base_size * 1.10)), "bold", TEXT_RGB)
    if sem == "STOP":
        return (max(20, int(base_size * 0.75)), "regular", TEXT_DIM_RGB)
    if sem == "BADGE":
        return (max(20, int(base_size * 1.20)), "bold", ACCENT_RGB)

    return (base_size, "regular", TEXT_RGB)

def group_into_phrases(timeline: List[Tuple[float, float, str]], max_chars: int = 28, max_per_group: int = 5) -> List[List[Tuple[float, float, str]]]:
    groups: List[List] = []
    current: List      = []
    current_text       = ""

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

        test_text = (current_text + " " + clean).strip() if current_text else clean
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

def group_into_tableaux(timeline: List[Tuple[float, float, str]], max_per_tableau: int = 4) -> List[List[Tuple[float, float, str]]]:
    """Alias pour rétrocompatibilité."""
    return group_into_phrases(timeline, max_chars=28, max_per_group=max_per_tableau)