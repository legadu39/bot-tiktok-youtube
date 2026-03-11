### gemini_headless/collect/filters/cleaner.py
from __future__ import annotations
import os
import re
import unicodedata
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional, Any
import logging

# --- Setup Basic Logging ---
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(os.getenv("CLEANER_LOG_LEVEL", "INFO").upper())

# --- Constants ---
_INVISIBLE = frozenset([0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2060, 0xFEFF])
_TRANS = {c: None for c in _INVISIBLE}
_TRANS[0x00A0] = 0x0020 # Replace non-breaking space with regular space

# --- UI Patterns ---
_UI_LINE_PATS_RAW = [
    r"(?:gemini|bard)\s+(?:est\s+en\s+train\s+d['’]?(?:e|é)crire|(?:e|é)crit|a\s+r(?:e|é)pondu|is\s+typing|has\s+replied)",
    r"(?:un\s+instant|veuillez\s+patienter|one\s+moment|please\s+wait)",
    r"(?:copier|copy|r(?:e|é)g(?:e|é)n(?:e|é)rer|regenerate|envoyer|send|try\s+again|r(?:e|é)essayer|share|feedback|like|dislike|partager|aimer|ne\s+plus\s+aimer)",
    r"(?:nouvelle\s+discussion|new\s+chat)",
    r"(?:d(?:e|é)couvrir\s+les\s+gems|discover\s+gems?)",
    r"(?:discussions?\s+r(?:e|é)centes?|recent\s+chats?)",
    r"(?:activit(?:e|é)|activity)",
    r"(?:param(?:e|è)tres?\s+et\s+aide|settings?\s+and\s+help|settings?|help|aide)",
    r"(?:se\s+connecter|connexion|log\s*in|sign\s*in)",
    r"(?:google\s+search|recherche\s+google)",
    r"(?:gathering\s+.*\s+inspiration|rassemblement\s+d'inspiration)",
    r"(?:votre\s+question\s+ici|please\s+enter\s+your\s+question\s+here|saisissez\s+une\s+invite)",
    r"(?:mettre\s+(?:a|à)\s+jour\s+la\s+position|update\s+location)",
    r"(?:d['’]apr(?:e|è)s\s+vos\s+adresses\s*\(domicile\)|based\s+on\s+your\s+places\s*\(home\))",
    r"(?:afficher\s+(?:le\s+)?raisonnement|masquer\s+(?:le\s+)?raisonnement|show\s+reasoning|hide\s+reasoning|autres\s+suggestions|more\s+drafts)",
    r"•", r"\*{1,3}", r"-{2,}", r"={2,}", r"_{2,}",
]

def _rx_any(parts: List[str], flags: int = re.IGNORECASE) -> Optional[re.Pattern]:
    try:
        wrapped = [rf"^\s*[\-•·\u2022\*]*\s*(?:{p})\s*[\.…!]*\s*$" for p in parts]
        combined = "|".join(wrapped)
        return re.compile(combined, flags)
    except re.error as e:
        logger.error(f"Regex compilation failed for UI patterns: {e}")
        return None

_RX_UI_LINE = _rx_any(_UI_LINE_PATS_RAW, re.IGNORECASE)

_UI_RESIDUAL_PATS_RAW = [
    r"(?:est\s+en\s+train\s+d['’]?(?:e|é)crire|(?:e|é)crit|is\s+typing|has\s+replied|a\s+r(?:e|é)pondu)",
    r"(?:un\s+instant|veuillez\s+patienter|one\s+moment|please\s+wait)",
    r"(?:copier|copy|r(?:e|é)g(?:e|é)n(?:e|é)rer|regenerate|envoyer|send|try\s+again|r(?:e|é)essayer)",
]
_RX_UI_RESIDUAL = _rx_any(_UI_RESIDUAL_PATS_RAW, re.IGNORECASE)

_RX_BE_METADATA_LINE = re.compile(r"^\s*\[{2,}") # Pour [[...]]

# --- Regex pour trouver ET supprimer les motifs [null,"..."] ---
_RX_BE_NULL_WRAPPER_FINDALL = re.compile(r"""
    \[\s*null\s*,\s*"        # Match [null, "
    ((?:[^"\\]|\\.)*?)        # Capture content non-greedily (group 1)
    "                         # Match closing quote
    (?:\s*,.*?)?              # Optionally match comma and following content non-greedily
    \s*\]                     # Match closing bracket
""", re.VERBOSE | re.DOTALL)

# --- Initialisation explicite à None pour éviter les erreurs Pylance ---
_RX_PREFIX_LABEL = None
_RX_ONLY_SYMBOLS = None
_RX_ONLY_BULLET = None
_RX_BOILER = None
_ECHO_PAT_FR = None
_ECHO_PAT_EN = None
_RX_EXCESS_NEWLINES = None
_RX_TRAILING_SPACE_NEWLINE = None

try:
    _RX_PREFIX_LABEL = re.compile(r"^\s*(?:assistant|assistante|gemini|bard|bot|you|tu|user|utilisateur)\s*:?\s*", re.IGNORECASE)
    _RX_ONLY_SYMBOLS = re.compile(r"^\s*[-=~_*#\u2500-\u25FF<>|/\\+]+$", re.UNICODE)
    _RX_ONLY_BULLET = re.compile(r"^\s*[•\u2022·\*\-+]+\s*$")
    _DROP_BOILERPLATE = bool(int(os.environ.get("CLEANER_DROP_BOILERPLATE", "1")))
    _RX_BOILER = re.compile(r"^\s*(?:bien\s*sûr[,!\s]*\s*voici\b|voici\b|here(?:'s| is)\b|ok[,!\s]*\s*here is\b).{0,150}\b(?:po[èe]me|réponse|summary|solution|code|script|list|table|texte|résumé|voici)\b.*$", re.IGNORECASE | re.DOTALL) if _DROP_BOILERPLATE else None
    
    _ECHO_PAT_FR_STR = os.environ.get("CLEANER_ECHO_PAT_FR", r"^\s*(?:écris|rédige|donne|génère|liste|fais|crée)\s+(un|une|le|la|les|des)\s+.+")
    _ECHO_PAT_EN_STR = os.environ.get("CLEANER_ECHO_PAT_EN", r"^\s*(?:write|compose|draft|give|generate|list|create|make)\s+(a|an|the)\s+.+")
    
    _ECHO_PAT_FR = re.compile(_ECHO_PAT_FR_STR, re.IGNORECASE) if _ECHO_PAT_FR_STR else None
    _ECHO_PAT_EN = re.compile(_ECHO_PAT_EN_STR, re.IGNORECASE) if _ECHO_PAT_EN_STR else None
    
    _ORIGINAL_PROMPT = os.environ.get("CLEANER_ORIGINAL_PROMPT", "").strip()
    
    _RX_EXCESS_NEWLINES = re.compile(r"\n{3,}")
    _RX_TRAILING_SPACE_NEWLINE = re.compile(r"[ \t]+(\n)")

except re.error as e:
     logger.error(f"Regex compilation failed: {e}", exc_info=True)
     # Les variables restent à None si l'assignation a échoué


# --- Helper Functions ---
def _normalize_soft(s: str) -> str:
    if not isinstance(s, str): return ""
    try: s_norm = unicodedata.normalize("NFKC", s); return s_norm.translate(_TRANS)
    except Exception as e: logger.warning(f"Soft normalization failed: {e}", exc_info=False); return s
def _h_line(s: str) -> str:
    if not isinstance(s, str): return ""
    try: return hashlib.blake2b(s.encode("utf-8", errors='replace'), digest_size=16).hexdigest()
    except Exception as e: logger.warning(f"Hashing failed: {e}", exc_info=False); return ""
def _remove_diacritics(s: str) -> str:
    if not isinstance(s, str): return ""
    try: s_nfd = unicodedata.normalize("NFD", s); return "".join(ch for ch in s_nfd if not unicodedata.combining(ch))
    except Exception as e: logger.warning(f"Removing diacritics failed: {e}", exc_info=False); return s
def _tokenize_fuzzy(s: str) -> List[str]:
    if not isinstance(s, str): return []
    try:
        s_no_accents = _remove_diacritics(s.lower())
        s_no_punct = re.sub(r"[^a-z0-9\s]+", " ", s_no_accents, flags=re.UNICODE)
        s_collapsed = re.sub(r"\s{2,}", " ", s_no_punct).strip()
        return s_collapsed.split() if s_collapsed else []
    except Exception as e: logger.warning(f"Fuzzy tokenization failed: {e}", exc_info=False); return []
def _jaccard(a: List[str], b: List[str]) -> float:
    if not isinstance(a, list) or not isinstance(b, list) or not a or not b: return 0.0
    try: A, B = set(a), set(b); intersection = len(A.intersection(B)); union = len(A.union(B)); return (intersection / union) if union else 0.0
    except Exception as e: logger.warning(f"Jaccard calculation failed: {e}", exc_info=False); return 0.0

# --- Stats Dataclass ---
@dataclass
class _Stats:
    removed_ui: int = 0; removed_symbols: int = 0; removed_echo: int = 0; removed_boiler: int = 0
    removed_dup_lines: int = 0; removed_dup_paras_exact: int = 0; removed_dup_paras_fuzzy: int = 0
    replaced_paras_fuzzy: int = 0; normalized_lines: int = 0; code_blocks: int = 0
    odd_fence_closed: bool = False; repaired_initial_chars: int = 0
    lines_processed: int = 0; initial_char_count: int = 0; final_char_count: int = 0
    removed_be_metadata: int = 0
    extracted_be_null_wrapper: int = 0
    removed_be_null_wrapper_patterns: int = 0
    dom_dup_ratio: float = field(init=False, default=0.0)
    def calculate_final_stats(self):
        self.initial_char_count = max(self.initial_char_count, self.final_char_count)
        if self.initial_char_count > 0:
            removed_chars = self.initial_char_count - self.final_char_count
            self.dom_dup_ratio = removed_chars / self.initial_char_count
        else: self.dom_dup_ratio = 0.0

# --- Core Cleaning Logic ---
def _split_code_blocks(s: str) -> List[Tuple[bool, str]]:
    chunks: List[Tuple[bool, str]] = []; in_code = False; buf: List[str] = []; lines: List[str] = []
    if not isinstance(s, str): return []
    try: lines = s.split("\n")
    except Exception as e: logger.warning(f"String split failed: {e}", exc_info=False); lines = [s]
    for line in lines:
        if not isinstance(line, str): line = ""
        is_fence = False
        try: is_fence = line.strip().startswith("```")
        except Exception: pass
        if is_fence:
            if buf: chunks.append((in_code, "\n".join(buf))); buf = []
            in_code = not in_code; chunks.append((True, line)) # Add the fence itself
        else: buf.append(line)
    if buf: chunks.append((in_code, "\n".join(buf)))
    return chunks

def _collapse_consecutive_dups(lines: List[str]) -> Tuple[List[str], int]:
    if not isinstance(lines, list) or not lines: return [], 0
    out: List[str] = []; removed = 0; prev_line: Optional[str] = None
    for ln in lines:
        if not isinstance(ln, str): continue
        ln_strip = ln.strip()
        if prev_line is not None and ln == prev_line and ln_strip:
            removed += 1; continue
        out.append(ln); prev_line = ln
    return out, removed

def _paragraphs_from_lines(lines: List[str]) -> List[List[str]]:
    if not isinstance(lines, list): return []
    paras: List[List[str]] = []; buf: List[str] = []; lines_iterable = list(lines) + [""]
    for ln in lines_iterable:
        if not isinstance(ln, str): ln = ""
        ln_strip = ln.strip()
        if not ln_strip and buf and any(isinstance(l, str) and l.strip() for l in buf):
            clean_buf = [l for l in buf if isinstance(l, str)]
            while clean_buf and not clean_buf[0].strip(): clean_buf.pop(0)
            while clean_buf and not clean_buf[-1].strip(): clean_buf.pop()
            if clean_buf: paras.append(clean_buf)
            buf = []
        elif isinstance(ln, str): buf.append(ln)
    return paras

def _rejoin_paragraphs(paras: List[List[str]]) -> List[str]:
    if not isinstance(paras, list): return []
    out: List[str] = []; num_paras = len(paras)
    for i, p in enumerate(paras):
        if isinstance(p, list) and p:
             out.extend(item for item in p if isinstance(item, str))
             if i < num_paras - 1:
                 next_p_idx = i + 1
                 if next_p_idx < num_paras:
                    next_p = paras[next_p_idx]
                    if isinstance(next_p, list) and any(isinstance(line, str) and line.strip() for line in next_p):
                        out.append("")
    return out

def _collapse_duplicate_paragraphs_exact(paras: List[List[str]]) -> Tuple[List[List[str]], int]:
    if not isinstance(paras, list): return [], 0
    seen_hashes: Set[str] = set(); kept: List[List[str]] = []; removed_paras = 0
    for p in paras:
        if not isinstance(p, list) or not p or not any(isinstance(line, str) and line.strip() for line in p): continue
        sig_content_lines = [line.strip() for line in p if isinstance(line, str) and line.strip()]
        if not sig_content_lines: continue
        sig_content = "\n".join(sig_content_lines); sig = _h_line(sig_content)
        if not sig: continue
        if sig in seen_hashes: removed_paras += 1; continue
        seen_hashes.add(sig); kept.append(p)
    return kept, removed_paras

def _collapse_duplicate_paragraphs_fuzzy_fast(paras: List[List[str]], jacc_thresh: float) -> Tuple[List[List[str]], int, int]:
    """
    Optimisation linéaire O(N) pour la déduplication floue.
    Utilise un index inversé simplifié pour éviter la complexité quadratique.
    """
    if not paras: return [], 0, 0
    
    kept_paras: List[List[str]] = []
    # Index inversé: token -> list[para_index]
    token_index: Dict[str, List[int]] = {} 
    # Stocker les tokens des paragraphes gardés pour recalcul rapide Jaccard
    kept_tokens_cache: Dict[int, List[str]] = {}
    
    removed_count = 0
    replaced_count = 0

    for p in paras:
        if not isinstance(p, list) or not p: continue
        current_lines = [line for line in p if isinstance(line, str)]
        current_text = "\n".join(current_lines).strip()
        if not current_text: continue
        
        tokens = _tokenize_fuzzy(current_text)
        if not tokens: continue
        tokens_set = set(tokens)
        
        # Recherche des candidats potentiels via l'index
        candidates_indices: Set[int] = set()
        for t in tokens:
            if t in token_index:
                candidates_indices.update(token_index[t])
        
        best_match_idx = -1
        highest_jaccard = -1.0
        
        # Comparaison uniquement avec les candidats pertinents
        for candidate_idx in candidates_indices:
            candidate_tokens = kept_tokens_cache.get(candidate_idx)
            if not candidate_tokens: continue
            
            # Calcul Jaccard
            cand_set = set(candidate_tokens)
            intersection = len(tokens_set.intersection(cand_set))
            union = len(tokens_set.union(cand_set))
            j = (intersection / union) if union else 0.0
            
            if j >= jacc_thresh:
                if j > highest_jaccard:
                    highest_jaccard = j
                    best_match_idx = candidate_idx
        
        if best_match_idx != -1:
            # Doublon trouvé
            existing_para = kept_paras[best_match_idx]
            existing_text = "\n".join(existing_para).strip()
            
            # Remplacement si le nouveau est "mieux" (plus long ou plus de tokens)
            current_len = len(current_text)
            existing_len = len(existing_text)
            candidate_tokens = kept_tokens_cache[best_match_idx]
            
            is_identical = (current_text == existing_text)
            
            if current_len > existing_len or (current_len == existing_len and len(tokens) > len(candidate_tokens)):
                # Remplacer l'existant
                kept_paras[best_match_idx] = current_lines
                kept_tokens_cache[best_match_idx] = tokens # Mettre à jour le cache tokens
                # Mettre à jour l'index pour les nouveaux tokens
                for t in tokens_set:
                    if t not in token_index: token_index[t] = []
                    token_index[t].append(best_match_idx)
                
                if not is_identical:
                    replaced_count += 1
            else:
                # Garder l'ancien, jeter le nouveau
                if not is_identical:
                    removed_count += 1
        else:
            # Nouveau paragraphe unique
            new_idx = len(kept_paras)
            kept_paras.append(current_lines)
            kept_tokens_cache[new_idx] = tokens
            
            # Indexer les tokens
            for t in tokens_set:
                if t not in token_index: token_index[t] = []
                token_index[t].append(new_idx)

    return kept_paras, removed_count, replaced_count

def _should_drop_line_for_echo(line: str, first_content_line: Optional[str]) -> bool:
    if not isinstance(line, str) or not line.strip(): return False
    L_strip = line.strip()
    try:
        if _ECHO_PAT_FR and _ECHO_PAT_FR.match(L_strip): return True
        if _ECHO_PAT_EN and _ECHO_PAT_EN.match(L_strip): return True
    except Exception as e: logger.warning(f"Echo regex match failed: {e}", exc_info=False)
    if _ORIGINAL_PROMPT:
         try:
             prompt_tokens = _tokenize_fuzzy(_ORIGINAL_PROMPT)
             line_tokens = _tokenize_fuzzy(L_strip)
             if prompt_tokens and len(prompt_tokens) >= 2 and line_tokens == prompt_tokens:
                  logger.debug(f"Dropping echo line matching prompt: {L_strip[:80]}...")
                  return True
         except Exception as e: logger.warning(f"Echo prompt comparison failed: {e}", exc_info=False)
    return False

def _filter_ui_line(norm_line: str, ui_strict: bool) -> bool:
    if not isinstance(norm_line, str): return False
    try:
        if _RX_ONLY_SYMBOLS and _RX_ONLY_SYMBOLS.match(norm_line): return True
        if _RX_ONLY_BULLET and _RX_ONLY_BULLET.match(norm_line): return True
        if _RX_UI_LINE and _RX_UI_LINE.match(norm_line): return True
        if ui_strict and _RX_UI_RESIDUAL and _RX_UI_RESIDUAL.match(norm_line): return True
    except Exception as e: logger.warning(f"UI filter regex match failed: {e}", exc_info=False)
    return False

def _repair_initial_line_chars(lines: List[str], stats: _Stats) -> List[str]:
    if not isinstance(lines, list): return []
    repaired_lines: List[str] = []; repaired_count = 0; prev_line_had_content = False; prev_line_ends_sentence = True
    for i, line in enumerate(lines):
        if not isinstance(line, str): repaired_lines.append(line); prev_line_had_content = False; prev_line_ends_sentence = True; continue
        line_strip = line.strip(); current_line_has_content = bool(line_strip)
        if current_line_has_content and line_strip[0].islower():
            if prev_line_had_content and not prev_line_ends_sentence: repaired_count += 1
        repaired_lines.append(line)
        prev_line_had_content = current_line_has_content
        if current_line_has_content:
             try: prev_line_ends_sentence = line.rstrip()[-1] in ".?!):»>]\"'"
             except IndexError: prev_line_ends_sentence = False
        else: prev_line_ends_sentence = True
    stats.repaired_initial_chars = repaired_count
    return repaired_lines

def _apply_formatting_heuristics(text: str, stats: _Stats) -> str:
    """Applies final formatting rules, including BE null wrapper removal."""
    if not isinstance(text, str): return ""
    cleaned = text
    try:
        if _RX_BE_NULL_WRAPPER_FINDALL:
             original_len = len(cleaned)
             cleaned = _RX_BE_NULL_WRAPPER_FINDALL.sub("", cleaned)
             removed_count = original_len - len(cleaned)
             if removed_count > 0:
                 stats.removed_be_null_wrapper_patterns += removed_count
                 logger.debug(f"Removed BE null wrapper patterns. Chars removed: {removed_count}")

        if _RX_TRAILING_SPACE_NEWLINE: cleaned = _RX_TRAILING_SPACE_NEWLINE.sub(r"\1", cleaned)
        if _RX_EXCESS_NEWLINES: cleaned = _RX_EXCESS_NEWLINES.sub("\n\n", cleaned)
        return cleaned.strip()
    except Exception as e:
        logger.warning(f"Formatting heuristics failed: {e}", exc_info=False)
        return text.strip()


def _process_text_chunk(chunk: str, *, ui_markup: bool, stats: _Stats, ui_strict: bool, jacc_thresh: float) -> str:
    """Processes a single non-code chunk of text."""
    if not isinstance(chunk, str): return ""
    processed_chunk = chunk

    try:
        lines = processed_chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    except Exception as e:
        logger.warning(f"Line splitting failed: {e}", exc_info=False)
        return chunk

    stats.lines_processed += len(lines)
    norm_lines: List[str] = []
    first_content_line: Optional[str] = None

    for raw_line in lines:
        if not isinstance(raw_line, str): continue
        s_norm = _normalize_soft(raw_line); s_strip = s_norm.strip()
        if not s_strip: norm_lines.append(s_norm); continue

        temp_s = s_strip

        if _RX_BE_METADATA_LINE and _RX_BE_METADATA_LINE.match(temp_s):
            if logger.isEnabledFor(logging.DEBUG): logger.debug(f"Cleaner removing BE metadata line: {temp_s[:80]}...")
            stats.removed_be_metadata += 1
            continue

        if ui_markup and _RX_PREFIX_LABEL:
            try:
                s_no_label = _RX_PREFIX_LABEL.sub("", temp_s).strip()
                if s_no_label != temp_s: stats.normalized_lines += 1; temp_s = s_no_label
            except Exception as e: logger.warning(f"Prefix label regex failed: {e}", exc_info=False)
            if not temp_s: continue

        if _filter_ui_line(temp_s, ui_strict):
            is_symbol = (_RX_ONLY_SYMBOLS and _RX_ONLY_SYMBOLS.match(temp_s)) or \
                        (_RX_ONLY_BULLET and _RX_ONLY_BULLET.match(temp_s))
            if is_symbol: stats.removed_symbols += 1
            else: stats.removed_ui += 1
            continue

        if _DROP_BOILERPLATE and _RX_BOILER:
            try:
                 if _RX_BOILER.match(temp_s): stats.removed_boiler += 1; continue
            except Exception as e: logger.warning(f"Boilerplate regex failed: {e}", exc_info=False)

        norm_lines.append(s_norm)
        if not first_content_line: first_content_line = temp_s

    if not norm_lines: return ""
    kept_lines: List[str] = []
    for s_norm in norm_lines:
        s_strip = s_norm.strip() if isinstance(s_norm, str) else ""
        if s_strip and _should_drop_line_for_echo(s_strip, first_content_line):
            stats.removed_echo += 1; continue
        kept_lines.append(s_norm)
    norm_lines = kept_lines
    if not norm_lines: return ""

    norm_lines = _repair_initial_line_chars(norm_lines, stats)
    norm_lines, removed_consec = _collapse_consecutive_dups(norm_lines)
    stats.removed_dup_lines += removed_consec

    paras = _paragraphs_from_lines(norm_lines)
    paras, removed_exact_paras = _collapse_duplicate_paragraphs_exact(paras)
    stats.removed_dup_paras_exact += removed_exact_paras
    
    if jacc_thresh > 0.0:
        paras, removed_fuzzy_paras, replaced_fuzzy_paras = \
            _collapse_duplicate_paragraphs_fuzzy_fast(paras, jacc_thresh=jacc_thresh)
        stats.removed_dup_paras_fuzzy += removed_fuzzy_paras
        stats.replaced_paras_fuzzy += replaced_fuzzy_paras

    final_lines = _rejoin_paragraphs(paras)
    final_text = "\n".join(final_lines)
    final_text = _apply_formatting_heuristics(final_text, stats)
    return final_text


# --- Public API ---

# 🚀 NOUVEAUTÉ V11: Head Integrity Check
def is_head_semantically_valid(text: str) -> bool:
    """
    Vérifie si le texte commence correctement.
    Retourne False si le début semble tronqué (ex: commence par une minuscule, une virgule, etc.)
    """
    if not text or len(text.strip()) < 2: return True # Trop court pour juger
    
    clean = text.strip()
    first_char = clean[0]
    
    # 1. Check Code Block start (Exception pour le code)
    if clean.startswith("```") or clean.startswith("import ") or clean.startswith("def ") or clean.startswith("class "):
        return True
        
    # 2. Check JSON-like corruption (ex: '"key": value')
    if first_char == '"' and ":" in clean[:20] and not clean.startswith('{"'):
         # Exception: citation ("Ceci est une citation")
         if not clean.endswith('"'): return False
    
    # 3. Check Punctuation Start (Truncation brutale)
    if first_char in [",", ";", ".", "!", "?", ")", "]", "}"]:
        return False
        
    # 4. Check Lowercase Start (Probable milieu de phrase)
    # On ignore si c'est un chiffre ou un symbole
    if first_char.islower():
        # Exception: Mots courants qui peuvent commencer une puce ou une liste
        first_word = clean.split()[0].lower()
        if first_word not in ["http", "https", "www", "ftp"]:
            return False
            
    # 5. Check "Middle of sentence" words
    starts_with_connector = re.match(r"^(?:et|ou|mais|donc|or|ni|car|and|but|or|so|because)\s", clean, re.IGNORECASE)
    if starts_with_connector:
        return False
        
    return True


# 🚀 NOUVEAUTÉ V12: Normalisation de Flux (Backslash Cleaner)
def normalize_stream_artifacts(text: str) -> str:
    """
    Nettoie les artefacts techniques de streaming (fin de flux cassée, backslashes).
    Ceci est exécuté AVANT la validation sémantique.
    """
    if not text: return ""
    
    # 1. Strip whitespace
    text = text.strip()
    
    # 2. Retrait des backslashes de fin (ex: "Texte... \\\n")
    # On boucle tant que ça finit par un truc moche
    while text.endswith("\\") or text.endswith("\\\n") or text.endswith("\\n"):
        text = text.rstrip("\\n").rstrip("\\")
        text = text.strip()
        
    return text


# 🚀 NOUVEAUTÉ V18: FUZZY REPAIR (Auto-Heal Structurel)
def _repair_json_fuzzy(text: str) -> str:
    """
    Tente de réparer du JSON cassé par des LLMs (clés sans quotes, virgules en trop).
    """
    repaired = text
    
    # 1. Ajouter des quotes aux clés non quotées: { key: "val" } -> { "key": "val" }
    # Pattern: mot clé suivi de :
    repaired = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', repaired)
    
    # 2. Supprimer virgules traînantes: [1, 2, ] -> [1, 2]
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    
    # 3. Fermer les structures ouvertes (Stack based)
    stack = []
    in_string = False
    escaped = False
    
    for char in repaired:
        if in_string:
            if char == '"' and not escaped: in_string = False
            elif char == '\\' and not escaped: escaped = True
            else: escaped = False
        else:
            if char == '"': in_string = True
            elif char in '{[': stack.append('}' if char == '{' else ']')
            elif char in '}]':
                if stack and stack[-1] == char: stack.pop()
    
    if in_string: repaired += '"'
    while stack: repaired += stack.pop()
    
    return repaired

def repair_structure(text: str) -> str:
    """
    Tente de réparer les structures JSON ou Code non fermées.
    Applique une fermeture 'best-effort' des parenthèses/accolades.
    """
    if not text: return ""
    
    # Normalisation avant réparation
    repaired = normalize_stream_artifacts(text)
    repaired = repaired.strip()
    
    # 1. Nettoyage des caractères de fin parasites
    while repaired and repaired[-1] in ('\\', ',', ':') and not repaired.endswith('\\\\'):
        repaired = repaired[:-1].rstrip()
    
    # 2. Fermeture des Code Blocks
    fences = repaired.count("```")
    if fences % 2 != 0:
        repaired += "\n```"
        
    # 3. Stack-based repair pour JSON/Lists
    # On ne répare que si ça ressemble à un objet structuré
    if repaired.startswith("{") or repaired.startswith("["):
        # Tenter d'abord la réparation fuzzy avancée
        repaired = _repair_json_fuzzy(repaired)
    
    return repaired


# 🚀 NOUVEAUTÉ V16: Sévérité pour Veto Decay & INTENT VALIDATION (Text + Image)
def is_response_semantically_complete(
    text: str, 
    expected_format: str = None,
    has_images: bool = False
) -> Tuple[bool, str, str]:
    """
    Analyse si la réponse est valide.
    Intègre désormais la validation par INTENTION (expected_format) et MULTIMODALE (images).
    
    Returns: (isValid, Reason, Severity)
    Severity: 'CRITICAL' (structure cassée), 'LOW' (ponctuation), 'OK' (valide)
    """
    
    # --- 0. Validation Visuelle (Priority Override) ---
    if expected_format and expected_format.upper() in ["VISUAL", "IMAGE"]:
        if has_images:
            return True, "valid_visual_content", "OK"
        # Si on attend une image et qu'on n'en a pas, le texte seul ne suffit pas
        # Sauf si le texte dit "Je ne peux pas générer d'image" (Error catching) -> A gérer plus haut
        # Pour l'instant on considère que pas d'image = Incomplet
        if not text:
             return False, "waiting_for_image", "CRITICAL"
             
    if not text:
        return True, "Empty", "OK" 
    
    # On normalise avant d'analyser pour éviter les faux positifs sur les backslashes
    stripped = normalize_stream_artifacts(text)
    
    # --- 1. Validation Typée (Text Intent) ---
    if expected_format:
        fmt = expected_format.upper()
        
        if fmt == "JSON":
            try:
                # Nettoyage Markdown json éventuel
                json_candidate = stripped
                if "```json" in json_candidate:
                    parts = json_candidate.split("```json")
                    if len(parts) > 1:
                        json_candidate = parts[1].split("```")[0]
                elif "```" in json_candidate:
                     parts = json_candidate.split("```")
                     if len(parts) > 1:
                        json_candidate = parts[1]
                
                # Tentative de parse
                json.loads(json_candidate.strip())
                return True, "valid_json_format", "OK"
            except json.JSONDecodeError:
                # Si ça rate, on tente de voir si notre repair fonctionnerait
                repaired_candidate = _repair_json_fuzzy(json_candidate.strip())
                try:
                    json.loads(repaired_candidate)
                    return True, "valid_json_format_after_fuzzy_repair", "OK"
                except:
                    if stripped.endswith("}") or stripped.endswith("]"):
                         return True, "json_structure_seems_closed_but_invalid", "LOW"
                    return False, "invalid_json_format", "CRITICAL"

        elif fmt == "CODE":
            if stripped.count("```") % 2 != 0:
                return False, "unclosed_code_block", "CRITICAL"
            return True, "valid_code_block", "OK"

    # --- 2. Validation Standard (Fallback) ---
    # Check Markdown Code Blocks
    if stripped.count("```") % 2 != 0:
        return False, "Unclosed Code Block", "CRITICAL"
    
    # Check JSON/Array integrity
    if stripped.startswith("{") and not stripped.endswith("}"):
        return False, "Unclosed JSON Object", "CRITICAL"
    if stripped.startswith("[") and not stripped.endswith("]"):
        return False, "Unclosed JSON Array", "CRITICAL"

    # Check Abrupt Ending (Logic)
    if len(stripped) > 0:
        last_char = stripped[-1]
        
        # Backslash isolé = Low severity
        if last_char == "\\":
             return False, "Abrupt Ending Char '\\'", "LOW"
        
        if last_char in [":", ",", ";", "(", "[", "{"]:
            if last_char in "[{(":
                 return False, f"Abrupt Structure Opening '{last_char}'", "CRITICAL"
            return False, f"Abrupt Ending Char '{last_char}'", "LOW"
        
        # Check ending words
        last_words = stripped.split()[-3:] if len(stripped.split()) >= 3 else []
        if last_words:
            last_word = last_words[-1].lower()
            if last_word in ["et", "de", "le", "la", "les", "un", "une", "and", "or", "the", "a"]:
                return False, f"Abrupt Ending Word '{last_word}'", "LOW"

    return True, "OK", "OK"


def clean_text_with_stats(
    x: str, 
    *, 
    src: str = "unknown", 
    ui_markup: bool = False, 
    expected_format: str = None,
    has_images: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """Cleans the input text using various filters and returns cleaned text + stats."""
    # 🚀 INTELLIGENCE V12: Normalisation Proactive du Flux
    x = normalize_stream_artifacts(x)
    
    stats = _Stats()
    if not isinstance(x, str): x = ""
    stats.initial_char_count = len(x)
    if not x.strip():
        stats.final_char_count = 0; stats.calculate_final_stats(); return "", stats.__dict__

    try: s = x.replace("\r\n", "\n").replace("\r", "\n")
    except Exception: s = x

    chunks = _split_code_blocks(s)
    ui_strict = os.environ.get("CLEANER_UI_STRICT", "1") == "1"
    close_odd_fence = os.environ.get("CLEANER_CLOSE_ODD_FENCE", "1") == "1"
    jacc_thresh_env = os.environ.get("CLEANER_FUZZY_JACCARD", "0.92")
    try: jacc_thresh = max(0.0, min(1.0, float(jacc_thresh_env)))
    except (ValueError, TypeError): jacc_thresh = 0.92

    out_parts: List[str] = []; code_open = False
    for is_code, chunk in chunks:
        if not isinstance(chunk, str): continue
        if is_code:
            cleaned_chunk = chunk
            out_parts.append(cleaned_chunk)
            if chunk.strip().startswith("```"):
                code_open = not code_open
                if not code_open: stats.code_blocks += 1
        else:
            cleaned_text = _process_text_chunk(
                chunk, ui_markup=ui_markup, stats=stats, ui_strict=ui_strict, jacc_thresh=jacc_thresh
            )
            if cleaned_text: out_parts.append(cleaned_text)

    out = "\n".join(out_parts)
    out = _apply_formatting_heuristics(out, stats)

    final_fence_count = out.count("```")
    if close_odd_fence and final_fence_count % 2 == 1:
        if not out.rstrip().endswith("\n```"):
             out += "\n```"; stats.odd_fence_closed = True
             logger.debug("Added closing code fence.")

    stats.final_char_count = len(out); stats.calculate_final_stats()
    stats_dict = stats.__dict__
    stats_dict["dom_dup_ratio"] = round(stats_dict.get("dom_dup_ratio", 0.0), 4)

    is_valid, reason, severity = is_response_semantically_complete(
        out, 
        expected_format=expected_format,
        has_images=has_images
    )
    stats_dict["is_semantically_complete"] = is_valid
    stats_dict["incompleteness_reason"] = reason
    stats_dict["severity"] = severity

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Cleaner Stats (src={src}): {stats_dict}")
    return out, stats_dict

def clean_text(
    x: str, 
    *, 
    src: str = "unknown", 
    ui_markup: bool = False, 
    expected_format: str = None,
    has_images: bool = False
) -> str:
    """Cleans the input text and returns only the cleaned string."""
    out, _ = clean_text_with_stats(
        x, 
        src=src, 
        ui_markup=ui_markup, 
        expected_format=expected_format,
        has_images=has_images
    )
    return out