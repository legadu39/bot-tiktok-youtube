# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V23: NexusBrain — Pipeline unifié, corrections pixel-exact.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V23 vs V22 (corrections basées sur reverse-engineering vidéo réf.)  ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  FIX #1  — FS_BASE: 75 → 70px (mesuré text_h=27px@1024p → ~68px@1920p)    ║
# ║  FIX #2  — _step_2_visuals(): retourne Tuple[List[str], List[int]]         ║
# ║            asset_paths + broll_indices (indices scènes avec image réelle)   ║
# ║            Les cards ne sont PLUS pré-rendues ici — délégué au burner.      ║
# ║  FIX #3  — _step_4_assembly(): accepte broll_indices, calcule broll_schedule║
# ║            et le passe à burn_subtitles() → pipeline unifié V23             ║
# ║  FIX #4  — burn_subtitles() appelé avec broll_schedule pour intégration    ║
# ║            inline des B-Roll cards (Smart Layout + spring entry)            ║
# ║  FIX #5  — run_da_mode() et run_daemon() mis à jour pour dépackager le     ║
# ║            tuple retourné par _step_2_visuals()                             ║
# ║  FIX #6  — Sound Design: sfx_cursor corrigé (n'avançait pas en V22 quand  ║
# ║            sfx_type was None — le cursor doit avancer dans tous les cas)    ║
# ║  FIX #7  — Mode DA: test scenes enrichies avec prompts visuels valides      ║
# ║  FIX #8  — _step_4_assembly() suffix renommé _V23_UNIFIED                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

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

# ARCHITECTURE_MASTER_V23: FS_BASE = 70px (corrigé depuis 75px via mesures pixel)
from tools.config import FS_BASE


class SemanticException(Exception):
    """Exception levée quand l'IA hallucine ou ne respecte pas les règles sémantiques."""
    pass


_VISUAL_PROMPT_RENDER_INSTRUCTIONS = [
    "fond blanc", "fond noir", "background blanc", "background noir",
    "#ffffff", "#000000", "strict", "aucun visuel", "no image",
    "transition:", "slide", "fade",
]


def _sanitize_visual_prompt(raw_prompt: str) -> Optional[str]:
    if not raw_prompt:
        return None
    low = raw_prompt.strip().lower()
    for keyword in _VISUAL_PROMPT_RENDER_INSTRUCTIONS:
        if keyword in low:
            return None
    if len(low) < 4:
        return None
    return raw_prompt.strip()


class NexusBrain:
    """
    NEXUS BRAIN V9.0 — ARCHITECTURE_MASTER_V23.

    Pipeline unifié: SubtitleBurner intègre les B-Roll cards directement dans
    make_frame(t) via broll_schedule, avec Smart Layout (collision detection)
    et inversion basée sur timestamps mesurés (t=12.0s→12.7s, t=40.1s→fin).
    """

    MAX_SCENES = 25
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

        # ARCHITECTURE_MASTER_V23: fontsize=FS_BASE=70px (corrigé depuis 75px)
        self.subtitle_burner = SubtitleBurner(
            model_size        = "base",
            fontsize          = FS_BASE,
            spring_stiffness  = 900,
            spring_damping    = 30,
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

        # ARCHITECTURE_MASTER_V23: durée minimale d'une scène pour afficher une B-Roll card
        # Si la scène dure moins que ce seuil, pas de card (évite les flashes trop courts)
        self.broll_min_scene_duration = video_cfg.get("broll_min_scene_duration", 2.5)

        self.last_run_date = None
        self.signals_dir   = Path("./temp_signals")
        self.signals_dir.mkdir(exist_ok=True)

        jlog("info", msg=f"Nexus Brain V9.0 initialized (V23 Unified Pipeline, fontsize={FS_BASE}px)")

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

        self._clean_buffer()

        cmd = [
            sys.executable,
            str(cli_script),
            "--prompt", prompt,
            "--user-id", "admin",
            "--profile-base", CONFIG.get("SENTINEL_PROFILE", r"C:/Nexus_Data"),
        ]

        healing_state = self._read_healing_history()
        if healing_state.get("last_error") == "wait_network_idle_timeout":
            cmd.extend(["--generation-timeout", "60000"])
            jlog("info", msg="Auto-guérison: Timeout étendu (60s)")

        env                             = os.environ.copy()
        current_pythonpath              = env.get("PYTHONPATH", "")
        env["PYTHONPATH"]               = self.base_path + os.pathsep + current_pythonpath
        env["PYTHONIOENCODING"]         = "utf-8"
        env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8"

        process = None
        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.base_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            stdout, stderr = process.communicate(timeout=600)

            if process.returncode == 130:
                raise KeyboardInterrupt("Arrêt manuel détecté.")

            if process.returncode != 0:
                stderr_preview = stderr[:2000] if stderr else "No stderr"
                jlog("warning", msg="CLI Agent error", code=process.returncode, stderr=stderr_preview)
                if "wait_network_idle_timeout" in str(stderr):
                    self._write_healing_history({"last_error": "wait_network_idle_timeout"})
                else:
                    self._write_healing_history({"last_error": "unknown_cli_error"})
            else:
                self._write_healing_history({"last_error": None})

        except subprocess.TimeoutExpired:
            if process: process.kill()
            jlog("error", msg="CLI Agent timeout")
            return None
        except KeyboardInterrupt:
            if process: process.kill()
            raise
        except Exception as e:
            if process: process.kill()
            jlog("error", msg="CLI Agent failed", error=str(e))
            return None

        return self._retrieve_latest_buffer_content()

    def _clean_buffer(self):
        try:
            for f in self.buffer_dir.glob("*.json"):
                try: os.remove(f)
                except Exception: pass
        except Exception:
            pass

    def _retrieve_latest_buffer_content(self) -> Optional[str]:
        try:
            files = list(self.buffer_dir.glob("*.json"))
            if not files:
                jlog("warning", msg="CLI Agent: aucun payload dans BUFFER.")
                return None
            latest_file = max(files, key=os.path.getmtime)
            jlog("success", msg=f"Payload récupéré: {latest_file.name}")
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
    # ÉTAPE 0 : BRAINSTORMING
    # ─────────────────────────────────────────────────────────────────────

    async def _step_0_brainstorm_topic(self) -> str:
        jlog("step", msg="Step 0: Brainstorming (CLI Delegation)")

        all_topics     = self._get_recent_topics(limit=None)
        recent_context = ", ".join(all_topics[-20:]) if all_topics else ""
        day_theme      = self._get_smart_theme()
        topic          = None
        ai_context     = f"Thème actuel imposé : '{day_theme}'. Sujets déjà traités récemment (à éviter) : {recent_context}."

        previous_error = None
        max_retries    = 3
        is_invalid     = True

        for attempt in range(1, max_retries + 1):
            prompt       = get_brainstorm_prompt(ai_context, previous_error)
            raw_response = await self._invoke_cli_agent(prompt, context_tag=f"brainstorm_try_{attempt}")

            if not raw_response:
                previous_error = "Aucune réponse récupérée."
                continue

            try:
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

                title_len = len(topic_candidate)
                if title_len < 5 or title_len > 80:
                    raise SemanticException(f"Longueur anormale ({title_len} chars).")

                if topic_candidate in all_topics:
                    raise SemanticException(f"Sujet dupliqué: '{topic_candidate}'.")

                topic      = topic_candidate
                is_invalid = False
                jlog("success", msg=f"Topic validé: {topic}")
                break

            except SemanticException as e:
                jlog("warning", msg=f"Alerte sémantique: {e}")
                previous_error = str(e)

        if is_invalid:
            fallback_matrix = {
                "Vente & Conversion PropFirm (Preuves de gains/Payout)": [
                    "Les secrets de FTMO", "Mon premier Payout PropFirm",
                    "Comment valider un challenge PropFirm",
                ],
                "Motivation & Discipline (Psychologie du Trader)": [
                    "Le Mindset Trader", "Pourquoi tu perds en trading",
                    "La discipline de fer en Bourse",
                ],
                "Technique & Analyse (Stratégie pure)": [
                    "Ma stratégie SMC expliquée", "Le secret de l'Order Block",
                    "Trouver la bonne entrée en trading",
                ],
            }
            base_topics = fallback_matrix.get(day_theme, ["Le Mindset Trader","Pourquoi tu perds"])
            topic       = random.choice([t for t in base_topics if t not in all_topics] or base_topics)
            jlog("warning", msg=f"Fallback brainstorm activé ({day_theme}).")

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

        available_scripts = list(evergreen_dir.glob("*.json"))
        if available_scripts:
            selected = available_scripts[0]
            try:
                with open(selected, "r", encoding="utf-8") as f:
                    script_data = json.load(f)
                shutil.move(str(selected), str(used_dir / selected.name))
                if "meta" not in script_data: script_data["meta"] = {}
                script_data["meta"]["is_fallback"] = False
                script_data["meta"]["source"]      = "evergreen_vault"
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
                except Exception:
                    pass

        if script_data and "scenes" in script_data:
            nb_scenes = len(script_data["scenes"])
            if nb_scenes > self.MAX_SCENES:
                jlog("warning", msg=f"Script trop long: {nb_scenes} → tronqué à {self.MAX_SCENES}")
                script_data["scenes"] = script_data["scenes"][:self.MAX_SCENES]

        if script_data:
            return script_data

        jlog("warning", msg="CLI parsing échoué. Vérification Evergreen Vault...")
        evergreen_script = self._get_evergreen_script()
        if evergreen_script:
            return evergreen_script

        jlog("warning", msg="Engagement Fallback Protocol (Mode Dégradé)")
        fallback_script = self.fallback.generate_script(topic)
        if fallback_script:
            if "meta" not in fallback_script: fallback_script["meta"] = {}
            fallback_script["meta"]["is_fallback"] = True
        return fallback_script

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 2 : VISUALS — ARCHITECTURE_MASTER_V23
    # ─────────────────────────────────────────────────────────────────────

    async def _step_2_visuals(
        self,
        scenes: List[Dict],
    ) -> Tuple[List[str], List[int]]:
        """
        ARCHITECTURE_MASTER_V23: Retourne (asset_paths, broll_indices).

        DELTA vs V22:
            V22 → retournait List[str] avec des cards pré-rendues (PNG temporaires)
            V23 → retourne Tuple[List[str], List[int]] :
                  • asset_paths  : chemin bg_white pour toutes les scènes (fond vidéo)
                  • broll_indices: indices des scènes qui ont une image vault valide

        Les B-Roll cards ne sont PLUS pré-rendues ici. Elles sont passées au
        SubtitleBurner via broll_schedule dans _step_4_assembly() pour être
        intégrées inline dans make_frame(t) avec spring entry + Smart Layout.

        Avantages:
            - Pas de fichiers PNG temporaires inutiles
            - La card s'anime par-dessus le fond blanc (z_index=5 < texte z_index=10)
            - Smart Layout: le texte se repositionne automatiquement pour éviter
              la collision avec la card
        """
        jlog("step", msg=f"Step 2: Visuels (Fond {self.bg_style.upper()} — V23 Unified Pipeline)")

        bg_filename = "bg_white_ffffff.jpg" if self.bg_style == "white" else "bg_cream_f5f5f7.jpg"
        bg_path     = os.path.join(self.root_dir, bg_filename)

        if os.path.exists(bg_path):
            try: os.remove(bg_path)
            except Exception: pass

        self.animator.create_background(bg_path, style=self.bg_style)
        jlog("info", msg=f"Fond {self.bg_style} généré: {bg_filename}")

        # ARCHITECTURE_MASTER_V23: On vérifie juste que vault est dispo
        broll_available = True
        try:
            from tools.graphics import render_broll_card
        except ImportError:
            broll_available = False
            jlog("warning", msg="tools.graphics non dispo — B-Roll désactivé")

        # Toutes les scènes utilisent le fond blanc comme clip vidéo de base
        asset_paths   = [bg_path] * len(scenes)
        broll_indices = []     # NOUVEAU V23: indices des scènes avec image réelle
        broll_count   = 0
        skipped_count = 0

        for i, scene in enumerate(scenes):
            raw_prompt   = scene.get("visual_prompt", "")
            clean_prompt = _sanitize_visual_prompt(raw_prompt)

            if not clean_prompt:
                skipped_count += 1
                continue

            matched_asset = self.vault.find_best_match(
                clean_prompt,
                context_tags=scene.get("keywords_overlay", []),
                is_hook=(i == 0),
            )

            if matched_asset and os.path.exists(matched_asset.get("local_path", "")) and broll_available:
                img_path = matched_asset["local_path"]
                self.vault.mark_as_used(img_path)
                # ARCHITECTURE_MASTER_V23: stocker le chemin RAW de l'image (pas une card pré-rendue)
                # asset_paths reste bg_path (fond de clip), la card sera composée par le burner
                # On stocke juste l'index pour que _step_4_assembly construise le broll_schedule
                broll_indices.append(i)
                # Stocker le chemin image dans la scène pour récupération ultérieure
                scene["_broll_image_path"] = img_path
                broll_count += 1
                jlog("info", msg=f"  B-Roll schedulé: scène {i+1} ← {Path(img_path).name}")

        jlog("info", msg=(
            f"Visuels: {broll_count} B-Roll schedulés + "
            f"{len(scenes) - broll_count - skipped_count} fonds blancs purs + "
            f"{skipped_count} prompts ignorés"
        ))
        return asset_paths, broll_indices

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 3 : AUDIO (inchangée vs V22)
    # ─────────────────────────────────────────────────────────────────────

    async def _step_3_audio(self, scenes: List[Dict], speed: float = 1.0) -> str:
        jlog("step", msg="Step 3: Génération Audio")

        def clean_for_tts(text: str) -> str:
            return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

        full_text  = " ".join([clean_for_tts(s["text"]) for s in scenes])
        audio_path = await self.tts.generate(full_text, speed=speed)

        if hasattr(self.tts, "last_generation_cached") and self.tts.last_generation_cached:
            jlog("warning", msg="🛡️ TEST MODE ou Cache TTS détecté.")

        if not audio_path or not os.path.exists(audio_path):
            raise Exception("TTS Generation failed")
        return audio_path

    # ─────────────────────────────────────────────────────────────────────
    # ÉTAPE 4 : ASSEMBLAGE — ARCHITECTURE_MASTER_V23
    # ─────────────────────────────────────────────────────────────────────

    async def _step_4_assembly(
        self,
        script_data:   Dict,
        visual_assets: List[str],
        broll_indices: List[int],   # NOUVEAU V23: indices scènes B-Roll (depuis _step_2)
        audio_path:    str,
        safe_mode:     bool = False,
    ) -> Optional[str]:
        """
        ARCHITECTURE_MASTER_V23: Assembly avec pipeline unifié B-Roll + sous-titres.

        DELTA vs V22:
            • Nouveau paramètre broll_indices: indices des scènes avec image B-Roll
            • Calcul du broll_schedule (timestamps réels une fois l'audio connu)
            • burn_subtitles() appelé avec broll_schedule → cards animées inline
            • FIX sfx_cursor: avance dans tous les cas (même si sfx_type=None)
        """
        mode_label = "SAFE MODE" if safe_mode else "V23 UNIFIED PIPELINE"
        jlog("step", msg=f"Step 4: Assembly [{mode_label}]")

        clips            = []
        final_video_path = None

        try:
            audio_clip     = AudioFileClip(audio_path)
            total_duration = audio_clip.duration
            scenes         = script_data.get("scenes", [])

            if not scenes:
                raise ValueError("Aucune scène dans les données de script.")

            min_required_duration = len(scenes) * 0.35
            if total_duration < min_required_duration:
                jlog("warning", msg=f"Audio trop court ({total_duration:.1f}s) → rallongé à {min_required_duration:.1f}s")
                total_duration = min_required_duration

            def estimate_reading_weight(text: str) -> float:
                clean    = re.sub(r'\[.*?\]', '', text).strip()
                base_len = len(clean)
                pauses   = (clean.count('.') * 8 + clean.count(',') * 3
                            + clean.count('!') * 5 + clean.count('?') * 5)
                return float(base_len + pauses + 1)

            weights       = [estimate_reading_weight(s.get("text", "")) for s in scenes]
            total_weight  = sum(weights)
            raw_durations = [(w / total_weight) * total_duration for w in weights]

            durations = []
            for s, d in zip(scenes, raw_durations):
                if "[PAUSE]" in s.get("text", "").upper():
                    durations.append(max(d, self.pause_min_duration))
                else:
                    durations.append(d)

            dur_sum = sum(durations)
            if dur_sum > 0:
                durations = [d * total_duration / dur_sum for d in durations]

            # ── ARCHITECTURE_MASTER_V23: Construire le B-Roll schedule ────
            # Maintenant qu'on connaît les durées exactes, on peut calculer
            # les timestamps réels de chaque card B-Roll.
            broll_schedule: List[Tuple[float, float, str]] = []
            cursor_b = 0.0
            for i, d in enumerate(durations):
                if i in broll_indices:
                    img_path = scenes[i].get("_broll_image_path", "")
                    if img_path and os.path.exists(img_path):
                        # Seuil: scène trop courte → pas de card (évite les flashes)
                        if d >= self.broll_min_scene_duration:
                            broll_schedule.append((cursor_b, cursor_b + d, img_path))
                            jlog("info", msg=(
                                f"  📸 B-Roll card: scène {i+1} "
                                f"t=[{cursor_b:.2f}s, {cursor_b+d:.2f}s] "
                                f"({Path(img_path).name})"
                            ))
                        else:
                            jlog("info", msg=f"  ⏭ B-Roll scène {i+1} ignorée (dur={d:.2f}s < seuil {self.broll_min_scene_duration}s)")
                cursor_b += d

            if broll_schedule:
                jlog("info", msg=f"📸 V23 B-Roll schedule: {len(broll_schedule)} cards actives")

            keywords_per_scene = [
                " ".join(s.get("keywords_overlay", []) + [s.get("text", "")])
                for s in scenes
            ]

            # ── Génération des clips vidéo (fond blanc uniquement) ────────
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
                    scene_ctx = SceneContext()
                except ImportError:
                    scene_ctx = None

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
                            clip, intensity=self.micro_zoom_intensity,
                        )

                    if scene_transition == "none" and scenes_since_last_trans >= 3:
                        scene_transition = random.choice(["slide", "fade"])

                    if i > 0 and len(clips) > 0:
                        transition_applied = False

                        if scene_transition == "slide" and self.enable_slide_trans:
                            try:
                                direction = self.animator.get_slide_direction(i)
                                trans     = self.animator.create_slide_transition(
                                    clips[-1], clip,
                                    transition_duration=0.28,
                                    direction=direction,
                                    spring=True,
                                )
                                clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.28))
                                clips.append(trans.set_duration(0.28))
                                jlog("info", msg=f"↔ Slide {direction} → scène {i+1}")
                                transition_applied = True
                            except Exception as te:
                                jlog("warning", msg=f"Slide skipped: {te}")

                        elif scene_transition == "fade" and self.enable_fade_trans:
                            try:
                                trans = self.animator.create_fade_transition(
                                    clips[-1], clip, transition_duration=0.10,
                                )
                                clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.10))
                                clips.append(trans.set_duration(0.10))
                                jlog("info", msg=f"~ Fade → scène {i+1}")
                                transition_applied = True
                            except Exception as te:
                                jlog("warning", msg=f"Fade skipped: {te}")

                        scenes_since_last_trans = 0 if transition_applied else scenes_since_last_trans + 1

                    clips.append(clip)

            if not clips:
                raise Exception("Aucun clip valide généré")

            video_track = concatenate_videoclips(clips, method="compose")

            if self.enable_slowzoom and not safe_mode and not self.enable_micro_zoom:
                video_track = self.animator.apply_global_slowzoom(
                    video_track, start_scale=1.0, end_scale=1.05,
                )

            if self.enable_motion_blur and not safe_mode:
                video_track = self.animator.apply_motion_blur(video_track, strength=0.35)

            # ── Timeline des sous-titres (proportionnelle) ────────────────
            subtitle_timeline = []
            cursor = 0.0
            for i, d in enumerate(durations):
                subtitle_timeline.append((cursor, cursor + d, scenes[i].get("text", "")))
                cursor += d

            # ── Garde-fou densité Whisper ─────────────────────────────────
            if self.subtitle_burner.available:
                try:
                    jlog("info", msg="🎤 Whisper disponible — transcription word-level")
                    word_timeline = self.subtitle_burner.transcribe_to_timeline(audio_path)

                    if word_timeline and len(word_timeline) > 0:
                        density      = len(word_timeline) / max(total_duration, 1e-6)
                        min_expected = total_duration * self.MIN_WHISPER_WORDS_PER_SECOND

                        if len(word_timeline) >= min_expected:
                            subtitle_timeline = word_timeline
                            jlog("success", msg=(
                                f"  Word-level: {len(word_timeline)} mots "
                                f"({density:.2f} mots/s) — timeline proportionnel remplacé."
                            ))
                        else:
                            jlog("warning", msg=(
                                f"  Whisper: {len(word_timeline)} mots / {total_duration:.1f}s "
                                f"({density:.2f} mots/s < seuil {self.MIN_WHISPER_WORDS_PER_SECOND}). "
                                f"Silence synthétique probable — fallback proportionnel."
                            ))
                    else:
                        jlog("warning", msg="  Whisper transcript vide — fallback proportionnel.")
                except Exception as we:
                    jlog("warning", msg=f"  Whisper échoué ({we}) — fallback proportionnel.")

            # ── Sound Design ──────────────────────────────────────────────
            jlog("info", msg="🎧 Sound Design V23...")
            sfx_clips  = []
            sfx_cursor = 0.0

            for i, d in enumerate(durations):
                scene_text = scenes[i].get("text", "")
                sfx_type   = self.subtitle_burner.get_sfx_type(scene_text)

                # ARCHITECTURE_MASTER_V23: FIX — sfx_cursor avance TOUJOURS
                # V22 avait un `continue` qui ne faisait pas avancer sfx_cursor
                # → décalage progressif du sound design sur les longues vidéos
                if sfx_type is not None:
                    sfx_path = (
                        self.vault.get_random_sfx(sfx_type)
                        or self.vault.get_random_sfx("click")
                        or self.vault.get_random_sfx("pop")
                    )
                    if sfx_path and os.path.exists(sfx_path):
                        try:
                            vol_map = {"click_deep": 0.28, "click": 0.22, "swoosh": 0.13}
                            vol     = vol_map.get(sfx_type, 0.18)
                            sfx_c   = AudioFileClip(sfx_path).volumex(vol).set_start(sfx_cursor)
                            sfx_clips.append(sfx_c)
                        except Exception as se:
                            jlog("warning", msg=f"SFX skip: {se}")

                sfx_cursor += d  # TOUJOURS avancer, même si sfx_type=None

            if sfx_clips:
                final_audio = CompositeAudioClip([audio_clip] + sfx_clips)
                video_track = video_track.set_audio(final_audio).set_duration(total_duration)
            else:
                video_track = video_track.set_audio(audio_clip).set_duration(total_duration)

            # ── ARCHITECTURE_MASTER_V23: burn_subtitles avec broll_schedule ──
            jlog("info", msg=(
                f"🔥 V23 Burn: {len(subtitle_timeline)} entrées"
                f"{f' + {len(broll_schedule)} B-Roll cards' if broll_schedule else ''}"
            ))
            final_clip = self.subtitle_burner.burn_subtitles(
                video_clip      = video_track,
                timeline        = subtitle_timeline,
                broll_schedule  = broll_schedule,   # NOUVEAU V23: cards inline
            )

            # ── Export ────────────────────────────────────────────────────
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            unique_hash = str(uuid.uuid4())[:6]
            suffix      = "_SAFE" if safe_mode else "_V23_UNIFIED"
            filename    = f"nexus_final_{timestamp}_{unique_hash}{suffix}.mp4"
            output_path = os.path.join(self.root_dir, filename)

            final_clip.write_videofile(
                output_path,
                fps         = 24 if safe_mode else 30,
                codec       = "libx264",
                audio_codec = "aac",
                preset      = "faster",
                threads     = 4,
                logger      = None,
            )

            final_clip.close()
            audio_clip.close()
            for c in clips:
                try: c.close()
                except Exception: pass

            final_video_path = output_path
            jlog("success", msg=f"✅ Vidéo V23: {filename}")

        except Exception as e:
            if not safe_mode:
                jlog("error", msg="HQ render failed → Safe Mode", error=str(e))
                return await self._step_4_assembly(
                    script_data, visual_assets, broll_indices, audio_path, safe_mode=True,
                )
            else:
                jlog("fatal", msg="Assembly failure", error=str(e))
                return None

        return final_video_path

    # ─────────────────────────────────────────────────────────────────────
    # LIVRAISON & UPLOAD (inchangée)
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
    # MODE DA (FAST TEST) — ARCHITECTURE_MASTER_V23
    # ─────────────────────────────────────────────────────────────────────

    async def run_da_mode(self):
        jlog("info", msg="🎨 FAST DA TEST MODE V23 ACTIVATED")

        script_data = {
            "meta": {
                "title":     "TEST DA MODE V23 — Unified Pipeline",
                "tags":      ["test", "da", "premium"],
                "tts_speed": 1.0,
            },
            "scenes": [
                {"text": "90% des traders",       "visual_prompt": "trader devant écrans",     "keywords_overlay": ["traders"], "transition": "none"},
                {"text": "perdent tout",            "visual_prompt": "graphique rouge chute",    "keywords_overlay": ["perdent"], "transition": "none"},
                {"text": "leur argent.",             "visual_prompt": "pièces dorées sol",        "keywords_overlay": [],          "transition": "none"},
                {"text": "[PAUSE]",                  "visual_prompt": "",                         "keywords_overlay": [],          "transition": "none"},
                {"text": "Le vrai marché",           "visual_prompt": "analyse technique chart",  "keywords_overlay": ["marché"],  "transition": "slide"},
                {"text": "ratio des banques",        "visual_prompt": "immeuble banque finance",  "keywords_overlay": ["ratio"],   "transition": "none"},
                {"text": "179$",                     "visual_prompt": "billet dollar argent",     "keywords_overlay": ["badge"],   "transition": "none"},
                {"text": "[PAUSE]",                  "visual_prompt": "",                         "keywords_overlay": [],          "transition": "none"},
                {"text": "C'est possible.",          "visual_prompt": "succès victoire trophée",  "keywords_overlay": ["possible"],"transition": "fade"},
                {"text": "mais pas pour tous.",      "visual_prompt": "foule anonyme rue",        "keywords_overlay": [],          "transition": "none"},
            ],
        }

        audio_path = os.path.join(self.root_dir, "temp_audio.mp3")
        if not os.path.exists(audio_path):
            jlog("error", msg=f"Audio manquant: {audio_path}")
            jlog("info",  msg="Placez 'temp_audio.mp3' dans workspace/")
            return

        jlog("info", msg="Génération des visuels de test...")
        # ARCHITECTURE_MASTER_V23: dépackager le tuple
        imgs, broll_indices = await self._step_2_visuals(script_data["scenes"])

        vid = await self._step_4_assembly(
            script_data, imgs, broll_indices, audio_path, safe_mode=False
        )

        if vid:
            jlog("success", msg=f"✅ Test DA V23 terminé: {vid}")

    # ─────────────────────────────────────────────────────────────────────
    # INGESTION MANUELLE (inchangée)
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
                        jlog("success", msg="Métadonnées enrichies par l'IA.")
                except Exception as e:
                    jlog("warning", msg="Parsing JSON ingestion manuelle échoué", error=str(e))

            smart_meta["file"] = str(dest)
            with open(dest.with_suffix('.json'), "w", encoding="utf-8") as f:
                json.dump(smart_meta, f, indent=2)

    # ─────────────────────────────────────────────────────────────────────
    # MAIN LOOP — ARCHITECTURE_MASTER_V23
    # ─────────────────────────────────────────────────────────────────────

    async def run_daemon(self):
        jlog("info", msg="Nexus Brain V9.0 Daemon Started (V23 Unified Pipeline)")

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
                        jlog("warning", msg="🛡️ Script de secours — arrêt du cycle.")
                        await asyncio.sleep(300)
                        continue

                    speed = script.get("meta", {}).get("tts_speed", 1.0)

                    # ARCHITECTURE_MASTER_V23: dépackager le tuple de _step_2
                    imgs, broll_indices = await self._step_2_visuals(script["scenes"])
                    audio_path          = await self._step_3_audio(script["scenes"], speed)

                    # ARCHITECTURE_MASTER_V23: passer broll_indices à l'assemblage
                    vid = await self._step_4_assembly(script, imgs, broll_indices, audio_path)

                    if vid:
                        await self._deliver_package(vid, script)
                        self.last_run_date = current_date
                        jlog("success", msg=f"Cycle complet V23: {current_date}")
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
    parser = argparse.ArgumentParser(description="Nexus Brain V9.0 (V23 Unified Pipeline)")
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