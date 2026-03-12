# -*- coding: utf-8 -*-
### bot tiktok youtube/nexus_brain.py
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# --- INTEL 4: AUTO-DÉCOUVERTE DES DÉPENDANCES (PORTABILITÉ) ---
try:
    from moviepy.config import change_settings
    magick_path = shutil.which("magick") or shutil.which("convert")
    if magick_path:
        change_settings({"IMAGEMAGICK_BINARY": magick_path})
    elif os.path.exists(r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"):
        change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})
except Exception as e:
    pass

import aiohttp
try:
    from moviepy.editor import AudioFileClip, concatenate_videoclips, ImageClip, CompositeAudioClip
except ImportError:
    print("CRITICAL: MoviePy not installed or incompatible version. Run 'pip install \"moviepy<2.0.0\"'")
    sys.exit(1)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common import jlog, CONFIG, ensure_directories, resolve_path
from prompts.templates import wrap_v3_prompt, get_manual_ingestion_prompt, get_brainstorm_prompt
from tools.asset_vault import AssetVault
from tools.tts_manager import OpenAITTS
from tools.scene_animator import SceneAnimator
from tools.subtitle_burner import SubtitleBurner
from fallback import FallbackProvider

class SemanticException(Exception):
    """Exception levée quand l'IA hallucine ou ne respecte pas les règles sémantiques."""
    pass

class NexusBrain:
    """
    🧠 NEXUS BRAIN V8.7 (TITANIUM PARSER — ANTI-CRASH & SMART TIMING)
    ARCHITECTURE : Délègue l'intelligence à 'collect_cli.py'.
    """
    def __init__(self):
        self.root_dir   = resolve_path("workspace")
        self.hot_root   = resolve_path("hot_folder")
        self.buffer_dir = resolve_path("BUFFER")
        self.base_path  = os.path.dirname(os.path.abspath(__file__))

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.hot_root.mkdir(parents=True, exist_ok=True)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)

        # --- AUTO-DÉCOUVERTE FFMPEG ROBUSTE ---
        if not shutil.which("ffmpeg"):
            ffmpeg_bin_path = r"C:\ffmpeg\bin"
            if os.path.exists(ffmpeg_bin_path):
                if ffmpeg_bin_path not in os.environ["PATH"]:
                    os.environ["PATH"] += os.pathsep + ffmpeg_bin_path
                    jlog("info", msg="FFMPEG path forced programmatically", path=ffmpeg_bin_path)
            else:
                jlog("fatal", msg="FFMPEG introuvable. Vérifiez que ffmpeg.exe est bien dans le PATH système.")
                sys.exit(1)

        self.history_file = resolve_path("history_topics.json")
        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f)

        self.vault    = AssetVault()
        self.tts      = OpenAITTS()
        self.fallback = FallbackProvider()
        self.animator = SceneAnimator()

        # ── Phase 1 : Polices géométriques premium V8 (Inter prioritaire) ────
        font_bold    = CONFIG.get("video", {}).get("subtitle_font",         "Inter-ExtraBold")
        font_regular = CONFIG.get("video", {}).get("subtitle_font_regular",  "Inter-Light")
        font_size    = CONFIG.get("video", {}).get("subtitle_size",          None)

        self.subtitle_burner = SubtitleBurner(
            font=font_bold,
            font_regular=font_regular,
            fontsize=font_size
        )

        # ── Feature flags (config.json → section "video") ─────────────────
        video_cfg = CONFIG.get("video", {})
        self.enable_slowzoom      = video_cfg.get("enable_slowzoom",       True)
        self.enable_slide_trans   = video_cfg.get("enable_slide_trans",    True)
        self.enable_fade_trans    = video_cfg.get("enable_fade_trans",     True)
        self.enable_motion_blur   = video_cfg.get("enable_motion_blur",    False)
        self.enable_micro_zoom    = video_cfg.get("enable_micro_zoom",     True)
        self.micro_zoom_intensity = video_cfg.get("micro_zoom_intensity",  0.008)
        self.bg_style             = video_cfg.get("background_style",      "white")

        # ── Phase 4 : Durée minimale garantie d'une scène [PAUSE] ─────────
        self.pause_min_duration = video_cfg.get("pause_min_duration", 1.0)

        self.last_run_date = None
        self.signals_dir   = Path("./temp_signals")
        self.signals_dir.mkdir(exist_ok=True)

        jlog("info", msg="Nexus Brain V8.7 initialized (Titanium Parser & Smart Timing)")

    # -------------------------------------------------------------------------
    # INTELLIGENCE DÉLÉGUÉE & MÉMOIRE TRAUMATIQUE
    # -------------------------------------------------------------------------
    def _read_healing_history(self) -> Dict:
        hist_file = resolve_path("healing_history.json")
        if hist_file.exists():
            try:
                with open(hist_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass
        return {"last_error": None}

    def _write_healing_history(self, state: Dict):
        hist_file = resolve_path("healing_history.json")
        try:
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except: pass

    async def _invoke_cli_agent(self, prompt: str, context_tag: str = "general") -> Optional[str]:
        jlog("brain", msg=f"📡 Delegation to CLI Agent [Tag: {context_tag}]...")

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
            "--profile-base", CONFIG.get("SENTINEL_PROFILE", r"C:/Nexus_Data")
        ]

        healing_state = self._read_healing_history()
        if healing_state.get("last_error") == "wait_network_idle_timeout":
            cmd.extend(["--generation-timeout", "60000"])
            jlog("info", msg="Heuristique d'auto-guérison activée : Timeout étendu (60s)")

        env = os.environ.copy()
        current_pythonpath = env.get("PYTHONPATH", "")
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
                encoding='utf-8',
                errors='replace'
            )
            
            stdout, stderr = process.communicate(timeout=600)

            if process.returncode == 130:
                jlog("info", msg="Interruption utilisateur détectée (Code 130) dans le CLI Agent.")
                raise KeyboardInterrupt("Arrêt manuel détecté par le sous-processus.")

            if process.returncode != 0:
                stderr_preview = stderr[:2000] if stderr else "No stderr"
                jlog("warning", msg="CLI Agent returned error code", code=process.returncode, stderr=stderr_preview)
                if "wait_network_idle_timeout" in str(stderr):
                    self._write_healing_history({"last_error": "wait_network_idle_timeout"})
                else:
                    self._write_healing_history({"last_error": "unknown_cli_error"})
            else:
                self._write_healing_history({"last_error": None})

        except subprocess.TimeoutExpired:
            if process:
                process.kill()
            jlog("error", msg="CLI Agent timed out (Mission Aborted)")
            return None
        except KeyboardInterrupt:
            if process:
                process.kill()
            raise 
        except Exception as e:
            if process:
                process.kill()
            jlog("error", msg="CLI Agent invocation failed", error=str(e))
            return None

        return self._retrieve_latest_buffer_content()

    def _clean_buffer(self):
        try:
            for f in self.buffer_dir.glob("*.json"):
                try: os.remove(f)
                except: pass
        except: pass

    def _retrieve_latest_buffer_content(self) -> Optional[str]:
        try:
            files = list(self.buffer_dir.glob("*.json"))
            if not files:
                jlog("warning", msg="CLI Agent did not leave any payload in BUFFER.")
                return None
            latest_file = max(files, key=os.path.getmtime)
            jlog("success", msg=f"Payload retrieved: {latest_file.name}")
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            content = data.get("content", {})
            return content.get("text", None)
        except Exception as e:
            jlog("error", msg="Failed to read Buffer payload", error=str(e))
            return None

    # -------------------------------------------------------------------------
    # INTELLIGENCE LOGIQUE & HEURISTIQUES
    # -------------------------------------------------------------------------
    def _get_smart_sleep_duration(self) -> int:
        now              = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")

        if self.last_run_date == current_date_str:
            tomorrow_8am    = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
            seconds_to_wait = (tomorrow_8am - now).total_seconds()
            jitter          = random.randint(0, 2700)
            total_sleep     = max(60, int(seconds_to_wait + jitter))
            jlog("pacer", msg=f"Quota done. Smart Sleep active: Waking up in {total_sleep/3600:.2f} hours")
            return total_sleep

        if 2 <= now.hour < 6:
            target_time = now.replace(hour=6, minute=0, second=0)
            seconds     = int((target_time - now).total_seconds())
            jlog("pacer", msg=f"Night Mode. Sleeping {seconds/3600:.2f} hours")
            return max(60, seconds)

        return 60

    def _get_smart_theme(self) -> str:
        recent_topics = self._get_recent_topics(limit=10)
        counts = {"mindset": 0, "technique": 0, "propfirm": 0}

        for t in recent_topics:
            t_low = t.lower()
            if any(k in t_low for k in ["mindset", "discipline", "psychologie", "motivation", "secret", "perds"]):
                counts["mindset"] += 1
            elif any(k in t_low for k in ["ftmo", "apex", "funded", "payout"]):
                counts["propfirm"] += 1
            else:
                counts["technique"] += 1

        total = sum(counts.values())

        if counts["propfirm"] == 0 and total >= 4:
            jlog("info", msg="Matrice : Carence en contenu de conversion. Forçage du thème PropFirm.")
            return "Vente & Conversion PropFirm (Preuves de gains/Payout)"

        if counts["mindset"] < 2:
            return "Motivation & Discipline (Psychologie du Trader)"

        return "Technique & Analyse (Stratégie pure)"

    def _heuristic_tagging(self, filename: str) -> Dict:
        name_lower = filename.lower()
        tags       = ["shorts", "finance"]

        rules = {
            "crypto":   ["crypto", "bitcoin", "btc", "eth", "solana"],
            "trading":  ["trading", "forex", "scalping", "chart", "analyse", "ict", "smc"],
            "mindset":  ["mindset", "motivation", "discipline", "succès", "fail"],
            "propfirm": ["ftmo", "apex", "funded", "payout", "topstep", "eval"]
        }

        detected_category = "Trading"
        for category, keywords in rules.items():
            if any(k in name_lower for k in keywords):
                tags.append(category)
                for k in keywords:
                    if k in name_lower and k != category:
                        tags.append(k)
                detected_category = category.capitalize()

        now     = datetime.now()
        day_tags = {0: "#NewWeek", 4: "#FridayFeeling", 5: "#WeekendVibes", 6: "#SundayReset"}
        if now.weekday() in day_tags:
            tags.append(day_tags[now.weekday()])

        clean_name = Path(filename).stem.replace("_", " ").replace("-", " ").title()
        if len(clean_name) < 10:
            clean_name = f"{clean_name} : Le Secret Dévoilé"
        title = f"{clean_name} #{detected_category}"

        return {
            "title":       title,
            "description": f"Découvrez {clean_name}. \n\nABONNE-TOI pour plus de {detected_category}.",
            "tags":        list(set(tags)),
            "created_at":  str(datetime.now()),
            "auto_generated": True
        }

    # -------------------------------------------------------------------------
    # GESTION HISTORIQUE
    # -------------------------------------------------------------------------
    def _get_recent_topics(self, limit: int = None) -> List[str]:
        try:
            if not os.path.exists(self.history_file): return []
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list): return []
                if limit: return data[-limit:]
                return data
        except Exception: return []

    def _save_topic_to_history(self, topic: str):
        try:
            data = self._get_recent_topics()
            data.append(topic)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            jlog("error", msg="Failed to save topic history", error=str(e))

    def _parse_script_from_text(self, text: str) -> Optional[Dict]:
        try:
            # INTELLIGENCE V8.7: Blindage contre les espaces parasites \s*
            title_match = re.search(r"TITRE\s*:\s*(.*)", text, re.IGNORECASE)
            title       = title_match.group(1).strip(" \t\n\r\\\"'*") if title_match else "Sujet Mystère"

            tags_match = re.search(r"TAGS\s*:\s*(.*)", text, re.IGNORECASE)
            tags_list  = [t.strip(" \t\n\r\\\"'*") for t in tags_match.group(1).split(",")] if tags_match else []

            scenes       = []
            scene_blocks = re.split(r"SCENE\s*\d+", text, flags=re.IGNORECASE)

            for i, block in enumerate(scene_blocks[1:], 1):
                block = block.strip()
                if not block:
                    continue

                # INTELLIGENCE V8.7: Tolérance extrême sur les ":"
                text_match  = re.search(r"TEXTE\s*:\s*(.*?)(?=\n(?:VISUEL|OVERLAY)|$)", block, re.IGNORECASE | re.DOTALL)
                scene_text  = text_match.group(1).strip() if text_match else ""

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

            if not scenes:
                return None

            return {
                "meta": {
                    "title":     title,
                    "tags":      tags_list,
                    "tts_speed": 1.1
                },
                "scenes": scenes
            }
        except Exception as e:
            jlog("error", msg="Text Parsing failed", error=str(e))
            return None

    # -------------------------------------------------------------------------
    # ÉTAPE 0 : BRAINSTORMING (Parseur Hybride Sécurisé)
    # -------------------------------------------------------------------------
    async def _step_0_brainstorm_topic(self) -> str:
        jlog("step", msg="Step 0: Brainstorming (CLI Delegation avec Titanium Parser)")

        all_topics    = self._get_recent_topics(limit=None)
        recent_context = ", ".join(all_topics[-20:]) if all_topics else ""
        day_theme     = self._get_smart_theme()
        topic = None
        
        ai_context = f"Thème actuel imposé : '{day_theme}'. Sujets déjà traités récemment (à éviter) : {recent_context}."
        
        previous_error = None
        max_retries = 3
        is_invalid = True

        for attempt in range(1, max_retries + 1):
            prompt = get_brainstorm_prompt(ai_context, previous_error)
            
            raw_response = await self._invoke_cli_agent(prompt, context_tag=f"brainstorm_try_{attempt}")

            if not raw_response:
                previous_error = "Aucune réponse récupérée (Timeout ou erreur CLI de l'Agent)."
                jlog("warning", msg=f"Brainstorming attempt {attempt} échoué: {previous_error}")
                continue

            try:
                topic_candidate = None
                
                # INTELLIGENCE V8.7 : Regex Indestructible (tolère les espaces et nettoie le gras markdown)
                title_match = re.search(r'(?:TITRE|TITLE)\s*:\s*(.+)', raw_response, re.IGNORECASE)
                if title_match:
                    topic_candidate = title_match.group(1).strip(" \t\n\r\\\"'*")
                else:
                    json_match = re.search(r'\{.*?\}', raw_response.strip(), re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(0))
                            topic_candidate = data.get("title", "").strip(" \t\n\r\\\"'*")
                        except json.JSONDecodeError:
                            pass
                
                if not topic_candidate:
                    raise SemanticException("Format incompréhensible. Ni texte structuré (TITRE:), ni JSON valide trouvés.")
                
                # Validation Sémantique
                t_low = topic_candidate.lower()
                if any(k in t_low for k in ["error", "http", "://", "www.", ".com"]):
                    raise SemanticException(f"URL ou message d'erreur d'IA détecté dans le titre généré '{topic_candidate}'.")
                    
                title_len = len(topic_candidate)
                if title_len < 5 or title_len > 80:
                    raise SemanticException(f"Longueur de titre anormale ({title_len} chars). Le titre DOIT être cohérent.")
                    
                if topic_candidate in all_topics:
                    raise SemanticException(f"Sujet dupliqué (déjà traité) : '{topic_candidate}'. Trouve un angle TOTALEMENT NOUVEAU.")

                # Si on arrive ici, le contenu est parfait
                topic = topic_candidate
                is_invalid = False
                jlog("success", msg=f"Topic validé via Titanium Parser: {topic}")
                break

            except SemanticException as e:
                error_msg = str(e)
                jlog("warning", msg=f"Alerte Sémantique: {error_msg}")
                jlog("warning", msg=f"Brainstorming attempt {attempt} échoué. Déclenchement de l'Auto-Heal.")
                previous_error = error_msg

        if is_invalid:
            fallback_matrix = {
                "Vente & Conversion PropFirm (Preuves de gains/Payout)": [
                    "Les secrets de FTMO", "Mon premier Payout PropFirm", "Comment valider un challenge PropFirm"
                ],
                "Motivation & Discipline (Psychologie du Trader)": [
                    "Le Mindset Trader", "Pourquoi tu perds en trading", "La discipline de fer en Bourse"
                ],
                "Technique & Analyse (Stratégie pure)": [
                    "Ma stratégie SMC expliquée", "Le secret de l'Order Block", "Trouver la bonne entrée en trading"
                ]
            }
            base_topics = fallback_matrix.get(day_theme, ['Le Mindset Trader', 'Pourquoi tu perds'])
            topic = random.choice([t for t in base_topics if t not in all_topics] or base_topics)
            jlog("warning", msg=f"CLI Brainstorm failed/hallucinated totalement. Fallback theme preserved ({day_theme}).")

        self._save_topic_to_history(topic)
        jlog("info", msg=f"Topic selected: {topic}")
        return topic

    # -------------------------------------------------------------------------
    # ÉTAPE 1 : IDEATION & FALLBACK ACTIF
    # -------------------------------------------------------------------------
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
                if "meta" not in script_data:
                    script_data["meta"] = {}
                script_data["meta"]["is_fallback"] = False
                script_data["meta"]["source"]      = "evergreen_vault"
                jlog("success", msg=f"Evergreen Script chargé avec succès : {selected.name}")
                return script_data
            except Exception as e:
                jlog("error", msg=f"Failed to load evergreen script {selected.name}", error=str(e))
        return None

    async def _step_1_ideation(self, topic: str, profile_type: str = "INSIDER") -> Dict:
        jlog("step", msg=f"Step 1: Ideation for '{topic}'")
        sys_prompt   = wrap_v3_prompt(topic, profile_type)
        raw_response = await self._invoke_cli_agent(sys_prompt, context_tag="scripting")
        script_data  = None

        if raw_response:
            if "=== DEBUT SCRIPT ===" in raw_response or "SCENE 1" in raw_response:
                jlog("info", msg="Detected Structured Text Format. Engaging Titanium Regex Parser.")
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
                except: pass

        if script_data:
            return script_data

        jlog("warning", msg="CLI parsing failed. Checking Evergreen Vault...")
        evergreen_script = self._get_evergreen_script()
        if evergreen_script:
            return evergreen_script

        jlog("warning", msg="Engaging Fallback Protocol for Scripting (Mode Dégradé)")
        fallback_script = self.fallback.generate_script(topic)

        if fallback_script:
            if "meta" not in fallback_script:
                fallback_script["meta"] = {}
            fallback_script["meta"]["is_fallback"] = True

        return fallback_script

    # -------------------------------------------------------------------------
    # ÉTAPE 2 : VISUALS
    # -------------------------------------------------------------------------
    async def _step_2_visuals(self, scenes: List[Dict]) -> List[str]:
        jlog("step", msg=f"Step 2: Visual Asset (Fond {self.bg_style.upper()} — Phase V8)")

        bg_filename = "bg_white_ffffff.jpg" if self.bg_style == "white" else "bg_cream_f5f5f7.jpg"
        bg_path     = os.path.join(self.root_dir, bg_filename)

        # 🛡️ CORRECTION 1 : Détruire le fond pollué (qui contient le vieux texte gravé)
        if os.path.exists(bg_path):
            try:
                os.remove(bg_path)
            except Exception:
                pass

        self.animator.create_background(bg_path, style=self.bg_style)
        jlog("info", msg=f"Fond {self.bg_style} généré à neuf : {bg_filename}")

        return [bg_path for _ in scenes]

    # -------------------------------------------------------------------------
    # ÉTAPE 3 : AUDIO
    # -------------------------------------------------------------------------
    async def _step_3_audio(self, scenes: List[Dict], speed: float = 1.0) -> str:
        jlog("step", msg="Step 3: Audio Generation")

        def clean_for_tts(text: str) -> str:
            return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

        full_text = " ".join([clean_for_tts(s["text"]) for s in scenes])
        audio_path = await self.tts.generate(full_text, speed=speed)
        
        if hasattr(self.tts, "last_generation_cached") and self.tts.last_generation_cached:
            jlog("warning", msg="🛡️ TEST MODE ACTIF ou Cache détecté. Vérifiez vos crédits ou votre config TTS.")
            
        if not audio_path or not os.path.exists(audio_path):
            raise Exception("TTS Generation failed")
        return audio_path

    # -------------------------------------------------------------------------
    # ÉTAPE 4 : ASSEMBLAGE (Intelligent Timing & Transitions)
    # -------------------------------------------------------------------------
    async def _step_4_assembly(
        self,
        script_data:   Dict,
        visual_assets: List[str],
        audio_path:    str,
        safe_mode:     bool = False
    ) -> Optional[str]:
        mode_label = "SAFE MODE" if safe_mode else "HQ PREMIUM MOTION"
        jlog("step", msg=f"Step 4: Assembly [{mode_label}]")

        clips            = []
        final_video_path = None

        try:
            audio_clip     = AudioFileClip(audio_path)
            total_duration = audio_clip.duration
            scenes         = script_data.get("scenes", [])
            
            if not scenes:
                raise ValueError("Aucune scène n'a été trouvée dans les données de script.")

            # 🛡️ CORRECTION 2 : Sauvegarde mathématique pour le Fallback Audio
            # Si on a 48 scènes sur un audio de 5s, les mots durent 0.1s et sont transparents.
            # On force une durée minimale (ex: 0.35s par mot) pour l'affichage DA/Test.
            min_required_duration = len(scenes) * 0.35
            if total_duration < min_required_duration:
                jlog("warning", msg=f"Audio trop court ({total_duration}s). Rallongement artificiel à {min_required_duration:.1f}s pour permettre l'animation des sous-titres.")
                total_duration = min_required_duration

            def estimate_reading_weight(text: str) -> float:
                clean = re.sub(r'\[.*?\]', '', text).strip()
                base_len = len(clean)
                pauses = clean.count('.') * 8 + clean.count(',') * 3 + clean.count('!') * 5 + clean.count('?') * 5
                return float(base_len + pauses + 1)

            weights = [estimate_reading_weight(s.get("text", "")) for s in scenes]
            total_weight = sum(weights)

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

            keywords_per_scene = [
                " ".join(s.get("keywords_overlay", []) + [s.get("text", "")])
                for s in scenes
            ]

            if safe_mode:
                for img_path, dur in zip(visual_assets, durations):
                    if not os.path.isfile(str(img_path)):
                        continue
                    clip = ImageClip(str(img_path)).set_duration(dur)
                    clip = clip.resize(height=1920)
                    if clip.w < 1080:
                        clip = clip.resize(width=1080)
                    clips.append(clip.set_position("center"))

            else:
                try:
                    from tools.scene_animator import SceneContext
                    scene_ctx = SceneContext()
                except ImportError:
                    scene_ctx = None

                prev_keywords = ""
                scenes_since_last_trans = 0 

                for i, (img_path, dur) in enumerate(zip(visual_assets, durations)):
                    if not os.path.isfile(str(img_path)):
                        continue

                    curr_kw         = keywords_per_scene[i] if i < len(keywords_per_scene) else ""
                    scene_transition = scenes[i].get("transition", "none") if i < len(scenes) else "none"

                    clip = self.animator.create_scene(
                        img_path,
                        dur + 0.1,
                        effect=None,
                        resolution=(1080, 1920),
                        apply_mutation=False
                    )

                    if self.enable_micro_zoom and not safe_mode:
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
                                    clips[-1], clip,
                                    transition_duration=0.28,
                                    direction=direction,
                                    spring=True 
                                )
                                clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.28))
                                clips.append(trans.set_duration(0.28))
                                jlog("info", msg=f"↔ Slide {direction} (spring) → scène {i+1}")
                                transition_applied = True
                            except Exception as te:
                                jlog("warning", msg=f"Slide skipped: {te}")

                        elif scene_transition == "fade" and self.enable_fade_trans:
                            try:
                                trans = self.animator.create_fade_transition(
                                    clips[-1], clip,
                                    transition_duration=0.10
                                )
                                clips[-1] = clips[-1].set_duration(max(0.05, clips[-1].duration - 0.10))
                                clips.append(trans.set_duration(0.10))
                                jlog("info", msg=f"~ Fade → scène {i+1}")
                                transition_applied = True
                            except Exception as te:
                                jlog("warning", msg=f"Fade skipped: {te}")
                                
                        if transition_applied:
                            scenes_since_last_trans = 0
                        else:
                            scenes_since_last_trans += 1

                    clips.append(clip)
                    prev_keywords = curr_kw

            if not clips:
                raise Exception("No valid clips generated")

            video_track = concatenate_videoclips(clips, method="compose")

            if self.enable_slowzoom and not safe_mode and not self.enable_micro_zoom:
                video_track = self.animator.apply_global_slowzoom(
                    video_track, start_scale=1.0, end_scale=1.05
                )

            if self.enable_motion_blur and not safe_mode:
                video_track = self.animator.apply_motion_blur(video_track, strength=0.35)

            subtitle_timeline = []
            cursor = 0.0
            for i, d in enumerate(durations):
                subtitle_timeline.append((cursor, cursor + d, scenes[i].get("text", "")))
                cursor += d

            jlog("info", msg="🎧 Sound Design V8 (click / swoosh / click_deep / silence)…")
            sfx_clips = []

            for start, end, text in subtitle_timeline:
                sfx_type = self.subtitle_burner.get_sfx_type(text)
                if sfx_type is None:
                    continue  

                sfx_path = (
                    self.vault.get_random_sfx(sfx_type)
                    or self.vault.get_random_sfx("click")
                    or self.vault.get_random_sfx("pop")
                )

                if sfx_path and os.path.exists(sfx_path):
                    try:
                        vol_map = {"click_deep": 0.28, "click": 0.22, "swoosh": 0.13}
                        vol     = vol_map.get(sfx_type, 0.18)
                        sfx_c   = AudioFileClip(sfx_path).volumex(vol).set_start(start)
                        sfx_clips.append(sfx_c)
                    except Exception as se:
                        jlog("warning", msg=f"SFX skip: {se}")

            if sfx_clips:
                final_audio = CompositeAudioClip([audio_clip] + sfx_clips)
                video_track = video_track.set_audio(final_audio).set_duration(total_duration)
            else:
                video_track = video_track.set_audio(audio_clip).set_duration(total_duration)

            final_clip = self.subtitle_burner.burn_subtitles(video_track, subtitle_timeline)

            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix      = "_SAFE" if safe_mode else "_PREMIUM"
            filename    = f"nexus_final_{timestamp}{suffix}.mp4"
            output_path = os.path.join(self.root_dir, filename)

            final_clip.write_videofile(
                output_path,
                fps=24 if safe_mode else 30,
                codec="libx264",
                audio_codec="aac",
                preset="faster" if safe_mode else "medium",
                threads=4,
                logger=None
            )

            final_clip.close()
            audio_clip.close()
            for c in clips:
                try: c.close()
                except: pass

            final_video_path = output_path
            jlog("success", msg=f"✅ Vidéo Premium Motion : {filename}")

        except Exception as e:
            if not safe_mode:
                jlog("error", msg="HQ render failed → Safe Mode", error=str(e))
                return await self._step_4_assembly(
                    script_data, visual_assets, audio_path, safe_mode=True
                )
            else:
                jlog("fatal", msg="Assembly failure", error=str(e))
                return None

        return final_video_path

    # -------------------------------------------------------------------------
    # LIVRAISON & UPLOAD
    # -------------------------------------------------------------------------
    async def _deliver_package(self, video_path: str, script_data: Dict):
        meta  = script_data.get("meta", {})
        title = meta.get("title", "Video Finance")
        tags  = meta.get("tags", [])

        fintech_tags = ["trading", "propfirm", "finance", "business"]
        for t in fintech_tags:
            if t not in tags:
                tags.append(t)

        meta_path = video_path.replace(".mp4", ".json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "title":       title,
                "description": meta.get("description", ""),
                "tags":        tags,
                "file":        video_path,
                "created_at":  str(datetime.now())
            }, f, indent=2)
        jlog("info", msg=f"Package delivered: {Path(video_path).name}")

    # -------------------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------------------
    async def _process_manual_ingestion(self, video_file: Path):
        jlog("info", msg=f"Processing manual file: {video_file.name}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{video_file.stem}_{timestamp}{video_file.suffix}"
        dest = self.root_dir / safe_name
        
        shutil.move(str(video_file), str(dest))

        possible_meta = video_file.with_suffix('.json')
        if possible_meta.exists():
            shutil.move(str(possible_meta), str(dest.with_suffix('.json')))
        else:
            smart_meta = self._heuristic_tagging(video_file.name)
            prompt_manual = get_manual_ingestion_prompt(video_file.name)

            raw_ai = await self._invoke_cli_agent(prompt_manual, "manual_meta")
            if raw_ai:
                try:
                    json_match = re.search(r'\{.*?\}', raw_ai, re.DOTALL)
                    if json_match:
                        ai_data = json.loads(json_match.group(0))
                        smart_meta.update(ai_data)
                        jlog("success", msg="Métadonnées enrichies par l'IA pour l'ingestion manuelle.")
                except Exception as e:
                    jlog("warning", msg="Échec du parsing JSON pour l'ingestion manuelle", error=str(e))

            smart_meta["file"] = str(dest)
            with open(dest.with_suffix('.json'), "w", encoding="utf-8") as f:
                json.dump(smart_meta, f, indent=2)

    # -------------------------------------------------------------------------
    # MODE DIRECTEUR ARTISTIQUE (FAST TEST)
    # -------------------------------------------------------------------------
    async def run_da_mode(self):
        jlog("info", msg="🎨 FAST DA TEST MODE V8 ACTIVATED (Bypassing AI & TTS)")

        script_data = {
            "meta": {
                "title":     "TEST DA MODE V8 — Premium Motion",
                "tags":      ["test", "da", "premium"],
                "tts_speed": 1.0
            },
            "scenes": [
                {"text": "[LIGHT]90% [BOLD]des traders",    "visual_prompt": "abstract", "keywords_overlay": ["traders"],   "transition": "none"},
                {"text": "[BOLD]perdent tout",               "visual_prompt": "abstract", "keywords_overlay": ["perdent"],   "transition": "none"},
                {"text": "[LIGHT]leur argent.",              "visual_prompt": "abstract", "keywords_overlay": [],            "transition": "none"},
                {"text": "[PAUSE]",                          "visual_prompt": "abstract", "keywords_overlay": [],            "transition": "none"},
                {"text": "[LIGHT]Le vrai [BOLD]ratio",       "visual_prompt": "abstract", "keywords_overlay": ["ratio"],     "transition": "slide"},
                {"text": "[BOLD]ratio [LIGHT]des banques",   "visual_prompt": "abstract", "keywords_overlay": ["ratio"],     "transition": "none"},
                {"text": "[BADGE]179$",                      "visual_prompt": "abstract", "keywords_overlay": ["badge"],     "transition": "none"},
                {"text": "[PAUSE]",                          "visual_prompt": "abstract", "keywords_overlay": [],            "transition": "none"},
                {"text": "[BOLD]C'est possible.",            "visual_prompt": "abstract", "keywords_overlay": ["possible"],  "transition": "fade"},
                {"text": "[LIGHT]mais [BOLD]pas pour tous.", "visual_prompt": "abstract", "keywords_overlay": [],            "transition": "none"},
            ]
        }

        audio_path = os.path.join(self.root_dir, "temp_audio.mp3")
        if not os.path.exists(audio_path):
            jlog("error", msg=f"Fichier audio manquant pour le test: {audio_path}")
            jlog("info",  msg="Veuillez placer un fichier vocal nommé 'temp_audio.mp3' dans workspace/")
            return

        jlog("info", msg="Génération des visuels de test (fond blanc #FFFFFF)…")
        imgs = await self._step_2_visuals(script_data["scenes"])

        vid = await self._step_4_assembly(script_data, imgs, audio_path, safe_mode=False)

        if vid:
            jlog("success", msg=f"✅ Test DA V8 terminé ! Vidéo : {vid}")

    async def run_daemon(self):
        jlog("info", msg="Nexus Brain V8 Daemon Started (Premium Motion Mode)")

        while True:
            manual_files = sorted(list(self.hot_root.glob("*.*")))
            videos = [f for f in manual_files if f.suffix.lower() in ['.mp4', '.mov', '.avi']]
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

                if script and "scenes" in script and isinstance(script["scenes"], list) and len(script["scenes"]) > 0:
                    if script.get("meta", {}).get("is_fallback", False):
                        jlog("warning", msg="🛡️ SÉCURITÉ QUOTA : Script de secours détecté. Arrêt du cycle.")
                        await asyncio.sleep(300)
                        continue

                    speed      = script.get("meta", {}).get("tts_speed", 1.0)
                    imgs       = await self._step_2_visuals(script["scenes"])
                    audio_path = await self._step_3_audio(script["scenes"], speed)

                    vid = await self._step_4_assembly(script, imgs, audio_path)

                    if vid:
                        await self._deliver_package(vid, script)
                        self.last_run_date = current_date
                        jlog("success", msg=f"Daily cycle complete for {current_date}")
                else:
                    jlog("error", msg="Script généré invalide (absence de la clé 'scenes'). Abandon du cycle pour éviter le crash.")

            except asyncio.CancelledError:
                raise 
            except KeyboardInterrupt:
                jlog("info", msg="Brain stopped by user (Graceful exit).")
                sys.exit(0)
            except Exception as e:
                jlog("error", msg="Cycle Auto Error", error=str(e))
                await asyncio.sleep(300)

            await asyncio.sleep(60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Nexus Brain V8")
    parser.add_argument("--da", action="store_true", help="Lance le mode DA pour tester le montage sans requêtes API.")
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
        jlog("info", msg="Brain stopped by user (Graceful exit).")
        sys.exit(0)