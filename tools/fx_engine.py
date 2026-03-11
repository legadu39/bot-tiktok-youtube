# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/fx_engine.py
import os
import random
import numpy as np
from pathlib import Path
from moviepy.editor import VideoFileClip, CompositeVideoClip, vfx, ColorClip, AudioFileClip, CompositeAudioClip
from moviepy.audio.AudioClip import AudioClip

# Import tolérant de l'AssetVault pour l'accès aux SFX
try:
    from tools.asset_vault import AssetVault
except ImportError:
    try:
        from asset_vault import AssetVault
    except ImportError:
        AssetVault = None

class FXEngine:
    """
    Gestionnaire intelligent des effets.
    INTELLIGENCE V7.2 (Minimalist Mode + Sound Design) : 
    - Désactivation totale des effets visuels (Lights/Wipes) pour garder l'aspect clinique pur.
    - Ajout du mixage audio procédural (Pops/Whooshes) en se basant sur la timeline textuelle
      ou les pics audio de la voix TTS.
    """
    
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.portable_root = self.script_dir.parent / "assets" / "transitions"
        self.user_root = Path(r"C:\Users\Mathieu\Desktop\Gemini headless\assets\transitions")
        
        self.transitions_root = None
        
        # On force la désactivation des effets visuels parasites pour le style Apple Minimaliste
        self.effects_disabled = True 
        self.lights_dir = None
        self.wipes_dir = None

        self.TRIGGERS = {
            "DANGER": 0.5, "STOP": 0.5, "ATTENTION": 0.4, "CRASH": 0.5, "SCAM": 0.5, 
            "PERTE": 0.4, "URGENT": 0.5, "VITE": 0.3, "ALERTE": 0.5,
            "PROFIT": 0.3, "GAIN": 0.3, "ARGENT": 0.2, "DOLLAR": 0.2, "€": 0.2, "$": 0.2,
            "SECRET": 0.2, "IMPORTANT": 0.2, "CONCEPT": 0.1,
            "LIEN": 0.1, "BIO": 0.1, "CLIQUE": 0.1
        }
        
        self.DECAY_RATE = 0.15
        self.TRIGGER_THRESHOLD = 0.65
        
        self.used_assets_history = []
        self.MAX_HISTORY = 5  
        
        # Initialisation du lien avec la librairie d'assets (pour les sons)
        try:
            self.vault = AssetVault() if AssetVault else None
        except Exception as e:
            print(f"⚠️ FXEngine n'a pas pu initialiser l'AssetVault pour l'audio: {e}")
            self.vault = None

    def _get_random_asset(self, folder_path):
        return None # Rendu obsolète par le mode Minimaliste

    def _apply_screen_mode(self, clip):
        mask = clip.to_mask()
        return clip.set_mask(mask)

    def _analyze_frame_contrast(self, frame_image):
        return 1.0, 1.0, 1.0 # Neutre absolu pour ne rien altérer

    def _digitalize_look(self, clip, tension_score=0.5, ref_frame=None):
        return clip # Pas de filtre de couleur dans le mode minimaliste

    def _create_synthetic_flash(self, duration=0.5):
        # On ne crée plus de flash pour préserver la clarté visuelle
        return None

    def _analyze_audio_peaks(self, video_clip, threshold_factor=1.8):
        """
        Détection des pics de voix (pour caler des bruitages quand on n'a pas 
        accès à la timeline des mots exacts).
        """
        if not video_clip.audio:
            return []
            
        try:
            sound_array = video_clip.audio.to_soundarray(fps=20) 
            volume = np.abs(sound_array).mean(axis=1)
            
            avg_volume = np.mean(volume)
            threshold = avg_volume * threshold_factor
            
            peaks = []
            min_gap = 2.0 
            last_peak = -10.0
            
            for i, vol in enumerate(volume):
                t = i / 20.0 
                if vol > threshold:
                    if (t - last_peak) > min_gap:
                        peaks.append(t)
                        last_peak = t
                        
            return peaks
        except Exception as e:
            print(f"⚠️ FX Audio Analysis Failed: {e}")
            return []

    def _safe_load_audio_clip(self, filepath, fallback_duration=0.1):
        """
        🚀 INTELLIGENCE N°3 : Dégradation Harmonieuse (Graceful Degradation)
        Si un son est manquant ou corrompu, on ne fait pas crasher l'encodeur final.
        """
        try:
            if not filepath or not os.path.exists(filepath):
                raise FileNotFoundError()
            return AudioFileClip(filepath)
        except Exception as e:
            print(f"⚠️ Ressource esthétique audio manquante ({filepath}). Remplacement par silence de sécurité.")
            # Tentative de charger le silence synthétique garanti par le Pre-Flight
            fallback_path = os.path.join(self.script_dir.parent, "assets_vault", "sfx", "synthetic_click.wav")
            try:
                if os.path.exists(fallback_path):
                    return AudioFileClip(fallback_path).subclip(0, fallback_duration)
            except:
                pass
            # Fallback absolu mathématique
            return AudioClip(make_frame=lambda t: [0, 0] if not isinstance(t, np.ndarray) else np.zeros((len(t), 2)), duration=fallback_duration)

    def apply_smart_effects(self, main_video, subtitle_data=None):
        """
        Dans cette version Minimaliste, l'aspect visuel N'EST PAS altéré.
        Cependant, nous appliquons un Sound Design (SFX) chirurgical basé sur
        le contexte (mots-clés) ou le rythme de la voix (peaks en fallback).
        """
        # Si on n'a ni audio de base, ni librairie chargée, on bypass tout (sécurité absolue)
        if not main_video.audio or not self.vault:
            return main_video
            
        audio_clips = [main_video.audio]
        last_sfx_time = -1.0
        
        # STRATÉGIE 1 : Sound Design Contextuel (Basé sur les sous-titres Whisper)
        if subtitle_data:
            SUCCESS_WORDS = ["profit", "gain", "win", "hausse", "argent", "cash", "réussite", "succès", "secret"]
            ALERT_WORDS = ["perte", "loss", "crash", "baisse", "risque", "stop", "danger", "faux", "attention", "urgent"]
            
            for start, end, text in subtitle_data:
                clean_text = text.lower()
                
                # Anti-Spam : On évite la cacophonie
                if start - last_sfx_time < 0.4:  
                    continue
                    
                sfx_type = None
                
                # Mots forts = Effets de transition lourds ou gratifiants
                if any(w in clean_text for w in SUCCESS_WORDS):
                    sfx_type = "success"
                elif any(w in clean_text for w in ALERT_WORDS):
                    sfx_type = "whoosh"
                # Mots normaux mais d'une certaine longueur = Petit rythme "Pop"
                elif len(clean_text) >= 5 and random.random() > 0.6: 
                    sfx_type = "pop" 
                    
                if sfx_type:
                    sfx_path = self.vault.get_random_sfx(sfx_type)
                    # 🛡️ Application de la Dégradation Harmonieuse
                    sfx_clip = self._safe_load_audio_clip(sfx_path).volumex(0.3).set_start(start)
                    audio_clips.append(sfx_clip)
                    last_sfx_time = start

        # STRATÉGIE 2 : Fallback Rythmique (Si on n'a pas la data Whisper)
        else:
            peaks = self._analyze_audio_peaks(main_video, threshold_factor=1.8)
            for peak in peaks:
                if peak - last_sfx_time < 0.5:
                    continue
                    
                sfx_path = self.vault.get_random_sfx("pop")
                # 🛡️ Application de la Dégradation Harmonieuse
                sfx_clip = self._safe_load_audio_clip(sfx_path).volumex(0.2).set_start(peak)
                audio_clips.append(sfx_clip)
                last_sfx_time = peak

        # Finalisation du mixage
        if len(audio_clips) > 1:
            try:
                new_audio = CompositeAudioClip(audio_clips)
                main_video = main_video.set_audio(new_audio)
                print(f"🎶 Sound Design : {len(audio_clips) - 1} SFX intégrés avec succès.")
            except Exception as e:
                print(f"⚠️ Erreur critique lors du mixage audio final: {e}")
                
        return main_video

    def get_wipe_transition(self):
        # Aucune transition visuelle complexe en minimalisme, on favorise le Cut sec.
        return None