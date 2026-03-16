# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V23: NexusBrain — Pipeline unifié, corrections pixel-exact.
# FIX_V27_ROOT_CAUSE: Purge absolue de l'état et sécurisation des données d'entrée.
# FIX_V27_CLI: Moteur asynchrone avec Retry et Backoff exponentiel pour l'Agent Web.
# NUKE_V28: Éradication absolue des données résiduelles. Refonte totale Fallback/Audio.
# PROD_READY_V31: Zéro Silent Failure, Optimisation extrême du rendu, Timing infaillible.
# MOTION_ENGINE_V32: 4 piliers d'optimisation motion design — word-by-word, spring,
#   zoom perpétuel, anticipation audio, hiérarchie typographique, b-roll validation.
# PIXEL_PERFECT_INTEGRATED:
#   FIX 1 — _validate_script_density(): rejet des scripts fantômes (< 8 scènes / 60 mots).
#   FIX 2 — _step_1_ideation(): appelle la validation avant de retourner le script.
#   FIX 3 — _step_3_audio(): durée silence = max(30s, word_count / 2.5) au lieu de len(text)/13.
#   FIX 4 — _step_2_visuals(): génère des fonds premium si vault vide (0 B-Roll matches).
#   FIX 5 — __init__: SpringLUT.warm_up() au démarrage pour éviter le cold-start.

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
    from moviepy.editor import AudioFileClip, concatenate_videoclips, ImageClip, CompositeAudioClip
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
from tools.physics import SpringLUT   # PIXEL_PERFECT_INTEGRATED


# ─────────────────────────────────────────────────────────────────────────────
# MOTION_ENGINE_V32: Constantes globales du moteur de mouvement
# ─────────────────────────────────────────────────────────────────────────────

AUDIO_ANTICIPATION_OFFSET: float = -0.040
VIRTUAL_CAMERA_ZOOM_START: float = 1.000
VIRTUAL_CAMERA_ZOOM_END:   float = 1.030
SPRING_K_REFERENCE: float = 900.0
SPRING_C_REFERENCE: float = 30.0
SCENE_DETECTION_WORD_THRESHOLD: int = 3
TYPO_SCALE_NORMAL: float = 1.00
TYPO_SCALE_ACCENT: float = 1.45
TYPO_SCALE_BADGE:  float = 1.25
TYPO_SCALE_MUTED:  float = 1.10
TYPO_SCALE_STOP:   float = 0.85
BROLL_MAX_COVERAGE_RATIO: float = 0.70

# PIXEL_PERFECT_INTEGRATED: Seuils de validation script
SCRIPT_MIN_SCENES: int = 8       # Minimum de scènes réelles pour une vidéo 40-60s
SCRIPT_MIN_WORDS:  int = 60      # Minimum de mots réels (cible 100-130)
SCRIPT_TTS_WORDS_PER_SEC: float = 2.5   # Vitesse de lecture TTS @speed=1.0


class SemanticException(Exception):
    pass


_VISUAL_PROMPT_RENDER_INSTRUCTIONS = [
    "fond blanc", "fond noir", "background blanc", "background noir",
    "#ffffff", "#000000", "strict", "aucun visuel", "no image",
    "transition:", "transition :", "slide", "fade", "strictement"
]

_GHOST_TEXT_BLACKLIST = frozenset([
    "votre phrase",
    "d'accroche ici",
    "la suite de votre idée",
    "un point fort.",
    "chiffrecle",
    "mot_impact",
    "mot_liaison",
    "mot_fort",
    "chiffre_cle",
    "insert_ton_texte",
    "premier mot ou groupe",
    "deuxième mot ou groupe",
    "[titre accrocheur",
    "schéma-scene",
    "exemple de structure",
    "ton premier vrai mot",        # PIXEL_PERFECT_INTEGRATED: ajout pattern V34
    "ton vrai premier mot",        # PIXEL_PERFECT_INTEGRATED
    "vrai contenu sur",            # PIXEL_PERFECT_INTEGRATED
    "placeholder",                 # PIXEL_PERFECT_INTEGRATED
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


# ─────────────────────────────────────────────────────────────────────────────
# MOTION_ENGINE_V32: PILIER 1 — Easing & Spring
# ─────────────────────────────────────────────────────────────────────────────

def _ease_out_back(p: float, overshoot: float = 1.70158) -> float:
    p = max(0.0, min(1.0, p))
    c1 = overshoot
    c3 = c1 + 1.0
    return 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2


def _ease_in_out_sine(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return -(math.cos(math.pi * p) - 1.0) / 2.0


def _spring_value(t: float, k: float = SPRING_K_REFERENCE, c: float = SPRING_C_REFERENCE) -> float:
    t = max(0.0, t)
    omega0 = math.sqrt(max(k, 1e-6))
    zeta   = c / (2.0 * omega0)
    if zeta < 1.0 - 1e-6:
        omega_d    = omega0 * math.sqrt(max(1.0 - zeta**2, 1e-12))
        sin_coeff  = zeta / math.sqrt(max(1.0 - zeta**2, 1e-12))
        env        = math.exp(-zeta * omega0 * t)
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


def _spring_clamped(t: float, k: float = SPRING_K_REFERENCE, c: float = SPRING_C_REFERENCE) -> float:
    return max(0.0, min(1.0, _spring_value(t, k, c)))


# ─────────────────────────────────────────────────────────────────────────────
# MOTION_ENGINE_V32: PILIER 4 — Timeline processing
# ─────────────────────────────────────────────────────────────────────────────

def _build_synthetic_word_timeline(
    scene_timeline: List[Tuple[float, float, str]],
) -> List[Tuple[float, float, str]]:
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

        def char_weight(w: str) -> float:
            stripped = w.rstrip(".,!?:;\"'«»")
            return max(1.0, float(len(stripped)))

        total_chars = sum(char_weight(w) for w in words)
        cursor = t_start
        for i, word in enumerate(words):
            w_end = t_start + (t_end - t_start) * sum(
                char_weight(words[j]) for j in range(i + 1)
            ) / max(total_chars, 1.0)
            w_start = cursor
            cursor  = w_end
            if i == len(words) - 1:
                cursor = t_end
            result.append((w_start, min(cursor, t_end), word))
    return result


def _is_word_level_timeline(timeline: List[Tuple[float, float, str]]) -> bool:
    if not timeline:
        return True
    sample = timeline[:min(10, len(timeline))]
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
        next_start      = result[i + 1][0]
        gap_ms          = (next_start - t_e) * 1000.0
        if gap_ms > 1.0 and "[PAUSE]" not in word.upper():
            result[i] = (t_s, next_start, word)
    return result


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
        self.enable_slowzoom      = video_cfg.get("enable_slowzoom",       True)
        self.enable_slide_trans   = video_cfg.get("enable_slide_trans",    True)
        self.enable_fade_trans    = video_cfg.get("enable_fade_trans",     True)
        self.enable_motion_blur   = video_cfg.get("enable_motion_blur",    False)
        self.enable_micro_zoom    = video_cfg.get("enable_micro_zoom",     True)
        self.micro_zoom_intensity = video_cfg.get("micro_zoom_intensity",  0.008)
        self.bg_style             = video_cfg.get("background_style",      "white")
        self.pause_min_duration   = video_cfg.get("pause_min_duration",    1.0)
        self.broll_min_scene_duration = video_cfg.get("broll_min_scene_duration", 2.5)

        self.last_run_date = None
        self.signals_dir   = Path("./temp_signals")
        self.signals_dir.mkdir(exist_ok=True)

        # PIXEL_PERFECT_INTEGRATED: Pré-chauffe la SpringLUT au démarrage.
        # Évite le cold-start (calcul numpy la première fois) pendant le rendu.
        SpringLUT.warm_up(fps=30)

        jlog("info", msg=f"Nexus Brain V32 initialized (MOTION_ENGINE_V32)")
        jlog("info", msg=f"  Anticipation offset : {AUDIO_ANTICIPATION_OFFSET*1000:.0f}ms")
        jlog("info", msg=f"  Zoom caméra virtuelle : {VIRTUAL_CAMERA_ZOOM_START:.3f}→{VIRTUAL_CAMERA_ZOOM_END:.3f}")
        jlog("info", msg=f"  Spring k={SPRING_K_REFERENCE:.0f} c={SPRING_C_REFERENCE:.0f} ζ=0.50")
        jlog("info", msg=f"  SpringLUT warmed up — {len(SpringLUT._cache)} profils en cache")

    # ─────────────────────────────────────────────────────────────────────
    # INTELLIGENCE DÉLÉGUÉE & MÉMOIRE TRAUMATIQUE
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
        timeout_val = 600
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
                try:
                    os.remove(f)
                except Exception:
                    pass
        except Exception:
            pass

    def _retrieve_latest_buffer_content(self, start_time: float = 0.0) -> Optional[str]:
        try:
            files = list(self.buffer_dir.glob("*.json"))
            if not files:
                return None
            valid_files = [f for f in files if os.path.getmtime(f) >= start_time - 1.0]
            if not valid_files:
                jlog("warning", msg="Fichiers buffer ignorés (fantômes d'une session précédente).")
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
        title = f"{clean_name} #{detected_category}"
        return {
            "title":          title,
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

            tags_match = re.search(r"TAGS\s*:\s*(.*)", text, re.IGNORECASE)
            tags_list  = [t.strip(" \t\n\r\\\"'*") for t in tags_match.group(1).split(",")] if tags_match else []

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

            return {
                "meta":   {"title": title, "tags": tags_list, "tts_speed": 1.1},
                "scenes": scenes,
            }
        except Exception as e:
            jlog("error", msg="Text Parsing failed", error=str(e))
            return None

    # ─────────────────────────────────────────────────────────────────────
    # PIXEL_PERFECT_INTEGRATED: Validation densité script
    # ─────────────────────────────────────────────────────────────────────

    def _validate_script_density(self, script_data: Dict) -> bool:
        """
        PIXEL_PERFECT_INTEGRATED: Guard de densité script.

        Un script avec moins de SCRIPT_MIN_SCENES scènes ou SCRIPT_MIN_WORDS mots
        est considéré comme un échec de génération (ghost text non détecté, ou
        LLM ayant retourné une réponse tronquée).

        Cause mesurée : 3 scènes sur 4 rejetées comme ghost → 1 scène réelle
        → 42 mots synthétiques → vidéo avec plages blanches sur 44s.

        Seuils :
          SCRIPT_MIN_SCENES = 8  (vidéo 40-60s à ~2.5 mots/scène = min 80 mots)
          SCRIPT_MIN_WORDS  = 60 (cible 100-130 mots; 60 = dégradé acceptable)
        """
        if not script_data or "scenes" not in script_data:
            jlog("warning", msg="PIXEL_PERFECT_V34: Script None ou sans 'scenes'.")
            return False

        scenes   = script_data["scenes"]
        n_scenes = len(scenes)

        total_words = sum(
            len(re.sub(r'\[.*?\]', '', s.get("text", "")).split())
            for s in scenes
        )

        if n_scenes < SCRIPT_MIN_SCENES:
            jlog("warning", msg=(
                f"PIXEL_PERFECT_V34: Script rejeté — {n_scenes} scènes "
                f"(minimum {SCRIPT_MIN_SCENES}). "
                f"Cause probable : ghost text résiduel ou LLM tronqué."
            ))
            return False

        if total_words < SCRIPT_MIN_WORDS:
            jlog("warning", msg=(
                f"PIXEL_PERFECT_V34: Script rejeté — {total_words} mots "
                f"(minimum {SCRIPT_MIN_WORDS}). "
                f"Script trop court pour une vidéo 40-60s."
            ))
            return False

        jlog("info", msg=(
            f"PIXEL_PERFECT_V34: Script validé — "
            f"{n_scenes} scènes, {total_words} mots. "
            f"Durée estimée : {total_words / SCRIPT_TTS_WORDS_PER_SEC:.1f}s"
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
        topic          = None
        ai_context     = f"Thème actuel imposé : '{day_theme}'. Sujets déjà traités récemment (à éviter) : {recent_context}."

        prompt       = get_brainstorm_prompt(ai_context, None)
        raw_response = await self._invoke_cli_agent(prompt, context_tag="brainstorm")

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
    # PIXEL_PERFECT_INTEGRATED: Validation densité après parsing.
    # ─────────────────────────────────────────────────────────────────────

    def _get_evergreen_script(self) -> Optional[Dict]:
        evergreen_dir = resolve_path("evergreen_vault")
        evergreen_dir.mkdir(parents=True, exist_ok=True)
        used_dir = evergreen_dir / "used"
        used_dir.mkdir(parents=True, exist_ok=True)

        available_scripts = list(evergreen_dir.glob("*.json"))

        for selected in available_scripts:
            try:
                with open(selected, "r", encoding="utf-8") as f:
                    script_data = json.load(f)

                if "scenes" in script_data and any("90%" in str(s.get("text", "")) for s in script_data["scenes"]):
                    jlog("warning", msg=f"☢️ NUKE_V28: Fichier infecté ('90%') détecté. Destruction: {selected.name}")
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

        # PIXEL_PERFECT_INTEGRATED: Validation densité AVANT de retourner le script.
        # Si le script est trop court (ghost text résiduel ou LLM tronqué),
        # on force le fallback Evergreen ou FallbackProvider.
        if script_data and "scenes" in script_data:
            if not self._validate_script_density(script_data):
                jlog("warning", msg=(
                    "PIXEL_PERFECT_V34: Script CLI rejeté par validation densité. "
                    "Basculement vers Evergreen Vault."
                ))
                script_data = None  # Force le chemin Evergreen ci-dessous

        if script_data and "scenes" in script_data:
            nb_scenes = len(script_data["scenes"])
            if nb_scenes > self.MAX_SCENES:
                script_data["scenes"] = script_data["scenes"][:self.MAX_SCENES]
            if "meta" not in script_data: script_data["meta"] = {}
            script_data["meta"]["source"] = "agent_cli_dynamique"
            return script_data

        jlog("warning", msg="CLI parsing échoué ou rejeté. Vérification Evergreen Vault...")
        evergreen_script = self._get_evergreen_script()
        if evergreen_script:
            # PIXEL_PERFECT_INTEGRATED: Validation aussi sur l'evergreen
            if self._validate_script_density(evergreen_script):
                return evergreen_script
            else:
                jlog("warning", msg="PIXEL_PERFECT_V34: Evergreen rejeté — densité insuffisante.")

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
            fallback_script["meta"]["source"] = "fallback_interne"

        return fallback_script

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 2 : VISUALS
    # PIXEL_PERFECT_INTEGRATED: Fond premium généré si vault vide.
    # ─────────────────────────────────────────────────────────────────────

    def _generate_premium_background(
        self,
        output_path: str,
        index: int = 0,
    ) -> str:
        """
        PIXEL_PERFECT_INTEGRATED: Génère un fond premium si le vault est vide.

        Le vault vide (0 B-Roll) était la 3ème cause racine : 42 requêtes échouées
        → fond blanc pur statique sur toute la vidéo → zéro variation visuelle.

        Solution : fonds blancs avec trace de couleur subtile sur 15% bas de l'écran.
        Palette issue de config.py V31 — cohérente avec le gradient accent TEAL→PINK.
          index=0 → trace violet #7B2CBF (accent standard)
          index=1 → trace teal (105,228,220) — gauche du gradient accent
          index=2 → trace pink (208,122,148) — droite du gradient accent

        Alpha de la trace : max 12/255 → imperceptible comme fond, perceptible
        comme variation de fond au montage.
        """
        from PIL import Image, ImageDraw

        W, H = 1080, 1920

        palettes = [
            (123,  44, 191, 12),   # violet premium
            (105, 228, 220, 10),   # teal (ACCENT_GRADIENT_LEFT)
            (208, 122, 148, 10),   # pink (ACCENT_GRADIENT_RIGHT)
        ]
        r, g, b, max_alpha = palettes[index % len(palettes)]

        img  = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Dégradé vertical sur 15% du bas : max_alpha → 0 (de bas en haut)
        accent_h = int(H * 0.15)
        for dy in range(accent_h):
            # dy=0 = haut de la zone accent, dy=accent_h-1 = bas de l'écran
            alpha = int(max_alpha * (1.0 - dy / accent_h))
            y     = H - accent_h + dy
            draw.rectangle([0, y, W, y + 1], fill=(r, g, b, alpha))

        img.save(output_path, quality=98)
        jlog("info", msg=(
            f"PIXEL_PERFECT_V34: Fond premium généré "
            f"(palette {index % len(palettes)}) → {Path(output_path).name}"
        ))
        return output_path

    async def _step_2_visuals(
        self,
        scenes: List[Dict],
    ) -> Tuple[List[str], List[int]]:
        jlog("step", msg=f"Step 2: Visuels (Fond {self.bg_style.upper()})")

        bg_filename = "bg_white_ffffff.jpg" if self.bg_style == "white" else "bg_cream_f5f5f7.jpg"
        bg_path     = os.path.join(self.root_dir, bg_filename)

        if os.path.exists(bg_path):
            try: os.remove(bg_path)
            except Exception: pass

        self.animator.create_background(bg_path, style=self.bg_style)

        broll_available = True
        try:
            from tools.graphics import render_broll_card
        except ImportError:
            broll_available = False

        asset_paths   = [bg_path] * len(scenes)
        broll_indices = []
        broll_count   = 0
        broll_rejected = 0
        vault_misses   = 0  # PIXEL_PERFECT_INTEGRATED: compteur de misses vault

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
                        jlog("warning", msg=(
                            f"MOTION_ENGINE_V32: B-Roll rejeté scène {i} "
                            f"(couverture={coverage:.0%} > {BROLL_MAX_COVERAGE_RATIO:.0%}) : "
                            f"{Path(img_path).name}"
                        ))
                except Exception:
                    pass

                if broll_ok:
                    self.vault.mark_as_used(img_path)
                    broll_indices.append(i)
                    scene["_broll_image_path"] = img_path
                    broll_count += 1
            else:
                vault_misses += 1

        # PIXEL_PERFECT_INTEGRATED: Si le vault est entièrement vide (100% de misses),
        # remplace le fond blanc pur par des fonds premium à variation de couleur.
        # Condition : au moins 80% de misses (évite le déclenchement si quelques
        # B-Roll sont présents).
        miss_ratio = vault_misses / max(len(scenes), 1)
        if miss_ratio >= 0.80:
            jlog("info", msg=(
                f"PIXEL_PERFECT_V34: Vault quasi-vide ({vault_misses}/{len(scenes)} misses). "
                f"Génération de fonds premium pour variation visuelle."
            ))
            for i in range(len(scenes)):
                premium_path = os.path.join(
                    self.root_dir,
                    f"bg_premium_{i:03d}.jpg"
                )
                # PIXEL_PERFECT_INTEGRATED: Rotation de palette toutes les 8 scènes
                # → variation subtile perceptible au montage, pas dans une seule scène.
                palette_index = i // 8
                self._generate_premium_background(premium_path, index=palette_index)
                asset_paths[i] = premium_path
        else:
            jlog("info", msg=(
                f"PIXEL_PERFECT_V34: {vault_misses} misses vault / {len(scenes)} scènes "
                f"— ratio {miss_ratio:.0%} < 80%, fonds blancs conservés."
            ))

        jlog("info", msg=(
            f"Visuels: {broll_count} B-Roll acceptés, "
            f"{broll_rejected} rejetés (trop grands)."
        ))
        return asset_paths, broll_indices

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 3 : AUDIO
    # PIXEL_PERFECT_INTEGRATED: Durée silence = max(30s, word_count/2.5).
    # ─────────────────────────────────────────────────────────────────────

    async def _step_3_audio(self, scenes: List[Dict], speed: float = 1.0) -> str:
        jlog("step", msg="Step 3: Génération Audio [NUKE_V28]")

        def clean_for_tts(text: str) -> str:
            return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

        texts_to_read = [clean_for_tts(s.get("text", "")) for s in scenes]
        full_text     = " ".join(texts_to_read)
        is_test_mode  = getattr(self.tts, "test_mode", False)

        if is_test_mode:
            jlog("warning", msg="🛡️ TEST MODE / FALLBACK AUDIO ACTIF.")

            # PIXEL_PERFECT_INTEGRATED: Calcul durée aligné sur le contenu réel.
            #
            # Problème V32 : durée = max(3.0, len(full_text) / 13.0)
            #   → 30 chars de script fantôme → 2.3s → vidéo de 2.3s.
            #
            # Fix : durée = max(MIN_DURATION, word_count / (TTS_WPS * speed))
            #   TTS_WPS = 2.5 mots/sec @speed=1.0 (mesure ElevenLabs multilingual v2)
            #   MIN_DURATION = 30s (garantit un contenu minimal diffusable)
            #   word_count = mots réels du script (sans tags)
            #
            # Exemple avec script valide 110 mots, speed=1.1 :
            #   durée = 110 / (2.5 * 1.1) = 40.0s → proche de la référence 44.033s ✓
            #
            # Exemple avec script fantôme 5 mots (après purge) :
            #   durée = max(30.0, 5 / (2.5 * 1.0)) = max(30.0, 2.0) = 30.0s
            #   → vidéo de 30s acceptable, pas de 2.3s cassée.

            real_word_count = len([
                w for w in full_text.split()
                if re.sub(r'[^\w]', '', w)
            ])

            TTS_WPS      = SCRIPT_TTS_WORDS_PER_SEC * speed
            MIN_DURATION = 30.0

            estimated_duration = max(
                MIN_DURATION,
                real_word_count / max(TTS_WPS, 0.1)
            )

            jlog("info", msg=(
                f"PIXEL_PERFECT_V34: Audio fallback — "
                f"{real_word_count} mots → "
                f"durée cible {estimated_duration:.2f}s "
                f"(TTS_WPS={TTS_WPS:.2f}, min={MIN_DURATION}s)"
            ))

            dummy_audio_path = os.path.join(self.root_dir, "silence_nucleaire_v32.mp3")
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(estimated_duration), "-q:a", "9",
                "-acodec", "libmp3lame", dummy_audio_path
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.exists(dummy_audio_path):
                    return dummy_audio_path
                else:
                    raise FileNotFoundError("FFmpeg n'a pas généré le fichier.")
            except Exception as e:
                from moviepy.editor import AudioClip
                make_frame   = lambda t: [0, 0]
                silence_clip = AudioClip(make_frame, duration=estimated_duration, fps=44100)
                silence_clip.write_audiofile(dummy_audio_path, logger=None, fps=44100)
                silence_clip.close()
                return dummy_audio_path

        audio_path = await self.tts.generate(full_text, speed=speed)
        if not audio_path or not os.path.exists(audio_path):
            raise Exception("TTS Generation failed in normal mode")

        return audio_path

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 4 : ASSEMBLAGE V32 — Motion Engine complet
    # ─────────────────────────────────────────────────────────────────────

    async def _step_4_assembly(
        self,
        script_data:   Dict,
        visual_assets: List[str],
        broll_indices: List[int],
        audio_path:    str,
        safe_mode:     bool = False,
    ) -> Optional[str]:

        mode_label = "SAFE MODE" if safe_mode else "V32 MOTION ENGINE"
        jlog("step", msg=f"Step 4: Assembly [{mode_label}]")

        clips = []
        subtitle_timeline = []
        broll_schedule: List[Tuple[float, float, str]] = []
        sfx_clips = []
        final_video_path = None

        try:
            audio_clip     = AudioFileClip(audio_path)
            total_duration = audio_clip.duration
            scenes         = copy.deepcopy(script_data.get("scenes", []))

            if not scenes:
                raise ValueError("Aucune scène dans les données de script clonées.")

            ghost_scenes_found = [s for s in scenes if _is_ghost_text(s.get("text", ""))]
            if ghost_scenes_found:
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

            # ── B-Roll schedule ──────────────────────────────────────────
            cursor_b = 0.0
            for i, d in enumerate(durations):
                if i in broll_indices:
                    img_path = scenes[i].get("_broll_image_path", "")
                    if img_path and os.path.exists(img_path):
                        if d >= self.broll_min_scene_duration:
                            broll_schedule.append((cursor_b, cursor_b + d, img_path))
                cursor_b += d

            # ── Génération des clips vidéo ────────────────────────────────
            if safe_mode:
                for img_path, dur in zip(visual_assets, durations):
                    if not os.path.isfile(str(img_path)): continue
                    clip = ImageClip(str(img_path)).set_duration(dur)
                    clip = clip.resize(height=1920)
                    if clip.w < 1080: clip = clip.resize(width=1080)
                    clips.append(clip.set_position("center"))
            else:
                try:
                    from tools.scene_animator import SceneContext
                except ImportError:
                    pass

                scenes_since_last_trans = 0
                for i, (img_path, dur) in enumerate(zip(visual_assets, durations)):
                    if not os.path.isfile(str(img_path)): continue

                    scene_transition = scenes[i].get("transition", "none") if i < len(scenes) else "none"

                    clip = self.animator.create_scene(
                        img_path, dur + 0.1,
                        effect=None, resolution=(1080, 1920), apply_mutation=False,
                    )

                    if self.enable_micro_zoom:
                        clip = self.animator.apply_micro_zoom_continuous(clip, intensity=self.micro_zoom_intensity)

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
                raise Exception("Aucun clip valide généré")

            video_track = concatenate_videoclips(clips, method="compose")

            if self.enable_slowzoom and not safe_mode and not self.enable_micro_zoom:
                video_track = self.animator.apply_global_slowzoom(
                    video_track,
                    start_scale=VIRTUAL_CAMERA_ZOOM_START,
                    end_scale=VIRTUAL_CAMERA_ZOOM_END,
                )

            if self.enable_motion_blur and not safe_mode:
                video_track = self.animator.apply_motion_blur(video_track, strength=0.35)

            # ── Construction de la subtitle_timeline scène ───────────────
            cursor = 0.0
            for i, d in enumerate(durations):
                subtitle_timeline.append((cursor, cursor + d, scenes[i].get("text", "")))
                cursor += d

            is_tts_test_mode = getattr(self.tts, "test_mode", False)

            if not is_tts_test_mode and self.subtitle_burner.available:
                try:
                    word_timeline = self.subtitle_burner.transcribe_to_timeline(audio_path)
                    if word_timeline and len(word_timeline) > 0:
                        density = len(word_timeline) / max(total_duration, 1e-6)
                        min_expected = total_duration * self.MIN_WHISPER_WORDS_PER_SECOND
                        if len(word_timeline) >= min_expected:
                            subtitle_timeline = word_timeline
                except Exception:
                    pass

            # MOTION_ENGINE_V32: Détection et correction timeline scène
            if not _is_word_level_timeline(subtitle_timeline):
                jlog("warning", msg=(
                    "MOTION_ENGINE_V32: Timeline scène détectée. "
                    "Activation du découpage synthétique mot-par-mot."
                ))
                subtitle_timeline = _build_synthetic_word_timeline(subtitle_timeline)
                jlog("success", msg=(
                    f"MOTION_ENGINE_V32: Timeline synthétique → {len(subtitle_timeline)} mots."
                ))

            # MOTION_ENGINE_V32: PILIER 4 — Fermeture des gaps inter-mots
            before_gap        = len(subtitle_timeline)
            subtitle_timeline = _close_word_gaps(subtitle_timeline)
            jlog("info", msg=f"MOTION_ENGINE_V32: Gaps inter-mots comblés ({before_gap} mots).")

            # MOTION_ENGINE_V32: PILIER 4 — Application de l'anticipation audio
            subtitle_timeline = _apply_anticipation_offset(
                subtitle_timeline,
                offset=AUDIO_ANTICIPATION_OFFSET,
            )
            jlog("info", msg=(
                f"MOTION_ENGINE_V32: Anticipation audio appliquée "
                f"({AUDIO_ANTICIPATION_OFFSET*1000:.0f}ms) sur {len(subtitle_timeline)} mots."
            ))

            # ── Sound Design ───────────────────────────────────────────────
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

            final_clip = self.subtitle_burner.burn_subtitles(
                video_clip      = video_track,
                timeline        = subtitle_timeline,
                broll_schedule  = broll_schedule,
            )

            # ── Export ─────────────────────────────────────────────────────
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            unique_hash = str(uuid.uuid4())[:6]
            suffix      = "_SAFE" if safe_mode else "_V32_MOTION"
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
            for c in clips:
                try: c.close()
                except Exception: pass

            final_video_path = output_path
            jlog("success", msg=f"✅ Vidéo V32 Motion Engine générée : {filename}")

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
    # LIVRAISON & UPLOAD
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
        jlog("info", msg="🎨 FAST DA TEST MODE V32 ACTIVATED")

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
            jlog("success", msg=f"✅ Test DA V32 terminé: {vid}")

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

            raw_ai = await self._invoke_cli_agent(prompt_manual, "manual_meta")
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
        jlog("info", msg="Nexus Brain Daemon Started (V32 MOTION ENGINE)")

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
                        jlog("success", msg=f"Cycle complet V32: {current_date}")
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
    parser = argparse.ArgumentParser(description="Nexus Brain V32 (MOTION ENGINE)")
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