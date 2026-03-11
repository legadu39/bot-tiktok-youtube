### bot tiktok youtube/nexus_arms.py
import asyncio
import os
import json
import logging
import sys
import shutil
import time
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

# Import Core (On utilise common.py pour paths et config)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from common import move_to_archive, move_to_failed, jlog, CONFIG, ensure_directories, resolve_path

# Configuration Logging via Common (plus besoin de logger local ici)
# logger = logging.getLogger("NexusArms") -> On utilise jlog pour uniformité

# --- IMPORT OUTILS AVEC SÉCURITÉ ET DIAGNOSTIC ---
try:
    from tools.tt_uploader import TikTokUploader
except ImportError as e:
    # CHIRURGIE : On affiche l'erreur réelle au lieu de la masquer
    jlog("fatal", msg=f"Impossible d'importer 'tools.tt_uploader'. Dépendance manquante ou erreur de syntaxe.", error=str(e))
    print("-" * 60)
    traceback.print_exc()
    print("-" * 60)
    print("CONSEIL : Vérifiez d'avoir installé : pip install requests websocket-client")
    sys.exit(1)

try:
    from tools.yt_uploader import YoutubeUploader
except ImportError:
    jlog("warning", msg="Module 'tools.yt_uploader' manquant. Le flux s'arrêtera à TikTok.")
    YoutubeUploader = None

# --- CONSTANTES METIER (V3) ---
AFFILIATE_LINK = CONFIG.get("api_keys", {}).get("affiliate_link", "")

# --- INTELLIGENCE TEMPORELLE (PACER) ---

class PublicationPacer:
    """
    Régulateur de flux pour éviter le SPAM et optimiser l'algorithme.
    Gère les Quotas Journaliers et les Intervalles de Sécurité.
    """
    def __init__(self, storage_dir: Path):
        self.state_file = storage_dir / "pacer_state.json"
        self.MAX_DAILY_UPLOADS = 5      # Limite haute par jour
        self.MIN_INTERVAL_HOURS = 3     # Délai min entre 2 vidéos TikTok (en heures)
        self.START_HOUR = 8             # Heure de début (08:00)
        self.END_HOUR = 23              # Heure de fin (23:00)
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
            except:
                self.state = {"daily_count": 0, "last_upload_ts": 0, "date": ""}
        else:
            self.state = {"daily_count": 0, "last_upload_ts": 0, "date": ""}

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f)
        except Exception as e:
            jlog("error", msg="Pacer save error", error=str(e))

    def _reset_quota_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("date") != today:
            jlog("pacer", msg=f"📅 Nouveau jour détecté. Reset des quotas ({today}).")
            self.state["daily_count"] = 0
            self.state["date"] = today
            self._save_state()

    def can_publish_new_video(self, is_priority: bool = False) -> Tuple[bool, str]:
        """
        Décide si on peut injecter une NOUVELLE vidéo dans le pipeline.
        Les vidéos prioritaires (Manuelles) bypassent certaines règles.
        """
        self._reset_quota_if_needed()
        now = time.time()
        current_hour = datetime.now().hour

        # 1. Règle des Heures Ouvrées (Sauf Priorité)
        if not is_priority:
            if not (self.START_HOUR <= current_hour < self.END_HOUR):
                return False, f"Hors horaires ({current_hour}h)"

        # 2. Règle du Quota (Sauf Priorité)
        if not is_priority and self.state["daily_count"] >= self.MAX_DAILY_UPLOADS:
            return False, f"Quota atteint ({self.state['daily_count']}/{self.MAX_DAILY_UPLOADS})"

        # 3. Règle du Délai (Cool-down)
        last_ts = self.state.get("last_upload_ts", 0)
        elapsed = now - last_ts
        min_wait = self.MIN_INTERVAL_HOURS * 3600
        
        # Si c'est prioritaire, on réduit le délai drastiquement (ex: 15 min) mais on garde une sécurité
        if is_priority:
            min_wait = 900 # 15 min

        if elapsed < min_wait:
            wait_min = int((min_wait - elapsed) / 60)
            return False, f"Cool-down actif (Encore {wait_min} min)"

        return True, "OK"

    def register_upload(self):
        """Enregistre une publication réussie."""
        self._reset_quota_if_needed()
        self.state["daily_count"] += 1
        self.state["last_upload_ts"] = time.time()
        self._save_state()
        jlog("pacer", msg=f"📈 Pacer mis à jour : {self.state['daily_count']}/{self.MAX_DAILY_UPLOADS} auj.")

# --- PUBLISHERS (WRAPPERS AVEC BUSINESS LOGIC) ---

class TikTokPublisher:
    """Wrapper spécialisé TikTok avec injection SEO & Affiliation."""
    def __init__(self):
        self.name = "TikTok"
        self.uploader = TikTokUploader()

    def _prepare_caption(self, metadata: Dict) -> str:
        """Construit la légende optimisée conversion + SEO."""
        base_desc = metadata.get('description', '')
        title = metadata.get('title', '')
        tags_list = metadata.get('tags', [])
        
        # Conversion tags list -> string hashtags
        tags_str = " ".join([f"#{t.replace(' ', '')}" for t in tags_list if t])
        
        # Assemblage "Diamond" (Titre + Desc + Lien + Tags)
        caption_parts = []
        if title: caption_parts.append(title)
        caption_parts.append(base_desc)
        
        # Injection Lien Affiliation (Vital pour Business Logic)
        if AFFILIATE_LINK:
            caption_parts.append(f"🔥 Info Exclusive : {AFFILIATE_LINK}")
            
        if tags_str: caption_parts.append(f"\n{tags_str}")
        
        full_caption = "\n\n".join(caption_parts)
        return full_caption[:2000] # Limite TikTok

    async def publish(self, video_path: str, metadata: Dict) -> bool:
        try:
            full_caption = self._prepare_caption(metadata)
            jlog("info", msg="Préparation Upload TikTok", caption_len=len(full_caption))
            
            return await self.uploader.upload(
                video_path=video_path,
                title=full_caption,
                privacy=metadata.get("privacy", "public")
            )
        except Exception as e:
            jlog("error", msg=f"TikTok Exception: {e}")
            return False

class YouTubePublisher:
    """Wrapper spécialisé YouTube Shorts avec injection SEO & Affiliation."""
    def __init__(self):
        self.name = "YouTube Shorts"
        self.uploader = YoutubeUploader() if YoutubeUploader else None

    def _prepare_description(self, metadata: Dict) -> str:
        """Construit la description YouTube."""
        base_desc = metadata.get('description', '')
        tags_list = metadata.get('tags', [])
        tags_str = " ".join([f"#{t.replace(' ', '')}" for t in tags_list if t])
        
        desc_parts = [base_desc]
        
        if AFFILIATE_LINK:
             desc_parts.append(f"\n👇 REJOINS L'ÉLITE ICI 👇\n{AFFILIATE_LINK}")
             
        if tags_str:
            desc_parts.append(f"\n\n{tags_str}")
            
        return "\n".join(desc_parts)

    async def publish(self, video_path: str, metadata: Dict) -> bool:
        if not self.uploader: return False
        try:
            full_desc = self._prepare_description(metadata)
            
            # Note: Pour Shorts, le titre contient souvent des hashtags aussi
            title = metadata.get("title", "Short")
            if len(title) < 80 and metadata.get('tags'):
                title += f" #{metadata['tags'][0].replace(' ', '')}"

            return await self.uploader.upload(
                video_path=video_path,
                title=title,
                description=full_desc,
                privacy=metadata.get("privacy", "public")
            )
        except Exception as e:
            jlog("error", msg=f"YouTube Exception: {e}")
            return False

# --- ORCHESTRATEUR PRINCIPAL ---

class NexusArms:
    """
    Les Bras (Consommateur) - V3.1 SCALABLE & PACED.
    Intègre désormais le 'PublicationPacer' et une logique multi-plateformes.
    Correction : Priorisation stricte 'HIGH' via calcul de score.
    """
    def __init__(self):
        self.running = False
        self.tt_publisher = TikTokPublisher()
        self.yt_publisher = YouTubePublisher()
        
        # Chemins (Résolus via common.py)
        self.buffer_dir = CONFIG.get("directories", {}).get("buffer_folder") or resolve_path("BUFFER")
        self.holding_dir = CONFIG.get("directories", {}).get("holding_folder") or resolve_path("HOLDING")
        ensure_directories()
        
        # Heartbeat
        self.heartbeat_file = resolve_path("temp/nexus_arms.hb")
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialisation du Pacer
        self.pacer = PublicationPacer(self.holding_dir)
            
    def _update_heartbeat(self):
        """Signale au Daemon que les Bras sont actifs."""
        try:
            self.heartbeat_file.touch()
        except Exception:
            pass
            
    def _get_smart_delay(self) -> int:
        """Délai intra-vidéo (TikTok -> Autres)."""
        delay = int(random.gauss(300, 60))
        delay = max(120, min(600, delay))
        if random.random() < 0.1: delay += random.randint(300, 900)
        return delay

    async def _transition_to_holding_state(self, json_path: Path, video_path: Path, metadata: Dict, next_state: str):
        """Transaction Atomique Buffer -> Holding."""
        try:
            release_time = int(time.time()) + self._get_smart_delay()
            
            published_list = metadata["meta"].get("published_on", [])
            if "tiktok" not in published_list:
                 published_list.append("tiktok")

            metadata["meta"].update({
                "published_on": published_list,
                "workflow_state": next_state,
                "release_next_at": release_time,
                "video_path": str((self.holding_dir / video_path.name).resolve())
            })

            dest_video_path = self.holding_dir / video_path.name
            shutil.move(str(video_path), str(dest_video_path))

            dest_json_path = self.holding_dir / json_path.name
            temp_json_path = self.holding_dir / f"{json_path.stem}.tmp"
            
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            os.replace(temp_json_path, dest_json_path)
            
            if json_path.exists(): os.remove(json_path)
            
            # On notifie le Pacer qu'une publication a eu lieu (Slot consommé)
            self.pacer.register_upload()
            
            jlog("success", msg=f"Transition State : {next_state} pour {dest_video_path.name}")
            return True

        except Exception as e:
            jlog("fatal", msg="Echec transaction Buffer->Holding", error=str(e))
            await move_to_failed(json_path, reason="MoveToHoldingError")
            if 'temp_json_path' in locals() and temp_json_path.exists():
                os.remove(temp_json_path)
            return False

    async def process_buffer_queue(self):
        """
        PHASE 1 : Entrée Pipeline (TikTok) SOUS CONTRÔLE DU PACER.
        C'est le point d'entrée unique.
        """
        # 1. Lecture et Tri
        tasks_data = []
        raw_files = list(self.buffer_dir.glob("*.json"))
        
        for json_path in raw_files:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                meta = data.get("meta", {})
                content = data.get("content", {})
                priority = content.get("priority_level", "NORMAL")
                
                score = meta.get("timestamp", 0)
                
                # Gestion Priorité : HIGH passe avant tout (score négatif artificiel)
                if priority == "HIGH": 
                    score -= 1_000_000_000 
                elif priority == "LOW": 
                    score += 1_000_000
                
                tasks_data.append((score, json_path, priority == "HIGH"))
            except:
                tasks_data.append((float('inf'), json_path, False))

        # Tri : Les scores les plus bas d'abord
        tasks_data.sort(key=lambda x: x[0])
        
        # 2. Traitement Régulé
        for _, json_path, is_priority in tasks_data:
            if not self.running: break
            
            # --- LE CHECKPOINT DU PACER ---
            can_pub, reason = self.pacer.can_publish_new_video(is_priority=is_priority)
            
            if not can_pub:
                if is_priority:
                     jlog("warning", msg=f"⛔ Tâche PRIORITAIRE bloquée par Pacer (Hard Limit) : {reason}")
                break 
            # ------------------------------

            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                meta = data.get("meta", {})
                content = data.get("content", {})
                video_path_str = meta.get("video_path")
                
                if not video_path_str or not Path(video_path_str).exists():
                    await move_to_failed(json_path, reason="MissingVideoFile")
                    continue
                
                video_path = Path(video_path_str)
                
                jlog("info", msg=f"🚀 Publication TikTok autorisée : {video_path.name}")
                
                # Si par hasard déjà publié (reprise crash), on skip l'upload réel
                if "tiktok" in meta.get("published_on", []):
                     success = True
                else:
                     success = await self.tt_publisher.publish(str(video_path), content)
                
                if success:
                    # Transition vers l'état suivant (Scalable: WAITING_YOUTUBE par défaut)
                    await self._transition_to_holding_state(json_path, video_path, data, next_state="WAITING_YOUTUBE")
                    # IMPORTANT : Une seule publication par cycle pour le Pacing
                    break 
                else:
                    jlog("error", msg="❌ Echec Publication TikTok")
                    await move_to_failed(json_path, reason="TikTokUploadFailed")
                    
            except Exception as e:
                jlog("error", msg=f"Erreur Buffer {json_path.name}", error=str(e))
                await move_to_failed(json_path, reason="CrashBufferLoop")

    async def process_holding_queue(self):
        """
        PHASE 2 : Holding (Scalable Workflow).
        Gère les publications secondaires (YouTube, et potentiellement Instagram plus tard).
        """
        tasks = list(self.holding_dir.glob("*.json"))
        
        for json_path in tasks:
            if not self.running: break
            
            # PATCH CRITIQUE : Ignorer le fichier d'état du Pacer
            # Sinon il est lu comme une tâche vidéo et fait crasher le processus
            if json_path.name == "pacer_state.json":
                continue

            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                meta = data.get("meta", {})
                state = meta.get("workflow_state", "UNKNOWN")
                release_time = meta.get("release_next_at", 0)
                
                # Attente du délai intelligent
                if time.time() < release_time:
                    continue
                
                video_path = Path(meta.get("video_path"))
                content = data.get("content", {})
                
                if not video_path.exists():
                     await move_to_failed(json_path, reason="VideoLostInHolding")
                     continue

                # --- ROUTAGE SCALABLE DES ETATS ---
                
                # ETAPE : YOUTUBE
                if state == "WAITING_YOUTUBE":
                    jlog("info", msg=f"🚀 Publication YouTube : {video_path.name}")
                    success = await self.yt_publisher.publish(str(video_path), content)
                    
                    if success:
                        published_list = meta.get("published_on", [])
                        if "youtube" not in published_list:
                            published_list.append("youtube")
                        data["meta"]["published_on"] = published_list
                        
                        jlog("success", msg="✅ Cycle Complet. Archivage.")
                        await move_to_archive(json_path)
                        
                        # Nettoyage vidéo défensif
                        if video_path.exists():
                            try:
                                archive_dir = CONFIG.get("directories", {}).get("archive_folder")
                                if archive_dir:
                                    dest = archive_dir / video_path.name
                                    shutil.move(str(video_path), str(dest))
                            except Exception:
                                try: os.remove(video_path)
                                except: pass
                    else:
                        jlog("warning", msg="YouTube Upload Failed (Retry later)")
                        await move_to_failed(json_path, reason="YouTubeUploadFailed")

                # ETAT INCONNU / FINI
                elif state == "UNKNOWN":
                    await move_to_archive(json_path)

            except Exception as e:
                jlog("error", msg=f"Erreur Holding {json_path.name}", error=str(e))

    async def run(self):
        self.running = True
        jlog("init", msg=f"💪 NEXUS ARMS V3.2 - ONLINE (Link: {AFFILIATE_LINK or 'NONE'})")
        
        while self.running:
            self._update_heartbeat()
            try:
                await self.process_buffer_queue()
                await self.process_holding_queue()
                await asyncio.sleep(10)
            except Exception as e:
                jlog("critical", msg="Crash Loop Arms", error=str(e))
                await asyncio.sleep(30)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    arms = NexusArms()
    try:
        asyncio.run(arms.run())
    except KeyboardInterrupt:
        pass