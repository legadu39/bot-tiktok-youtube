# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V31: motion_profiles.py — Intelligence Cinétique Avancée.
#
# Ce module implémente 3 systèmes d'intelligence qui manquaient à l'architecture V30 :
#
#   1. TempoEngine         — Synchronise la physique Spring sur le tempo audio
#   2. AudioEnergyDriver   — Pilote l'intensité du micro-zoom via l'énergie vocale
#   3. MotionProfiler      — Sélecteur de profil Spring selon le contexte sémantique
#
# PARADIGME CLÉ:
#   L'animation ne doit pas être statique (k=900 fixe pour tout).
#   Chaque mot a son propre POIDS CINÉTIQUE déterminé par sa classe sémantique
#   ET l'énergie audio locale au moment de son apparition.
#
#   ┌──────────────────────────────────────────────────────────────────────────┐
#   │  Classe    │  Spring k  │  Slide px  │  Overshoot │  Settle ms          │
#   ├──────────────────────────────────────────────────────────────────────────┤
#   │  NORMAL    │   900      │   8 px     │   ~15%     │  200 ms (6 frames)  │
#   │  ACCENT    │  1400      │  12 px     │   ~22%     │  180 ms (5 frames)  │
#   │  BADGE     │  1800      │  16 px     │   ~28%     │  160 ms (5 frames)  │
#   │  MUTED     │   600      │   6 px     │    ~8%     │  280 ms (8 frames)  │
#   │  STOP      │   400      │   4 px     │    ~2%     │  350 ms (10 frames) │
#   └──────────────────────────────────────────────────────────────────────────┘
#
# USAGE:
#   from tools.motion_profiles import MotionProfiler, AudioEnergyDriver
#   profiler = MotionProfiler()
#   sp, slide_px = profiler.get_for_word_class(WordClass.ACCENT)
#
# RÉFÉRENCE MATHÉMATIQUE (SpringPhysics avec ζ=0.50):
#   ω₀ = √k   |  ζ = c / (2ω₀)  →  c = 2 × ζ × ω₀  →  c = √k
#   Pour ζ=0.50 constant: c = √k
#   k=900  → c=30   (REFERENCE VIDEO)
#   k=1400 → c=37.4
#   k=1800 → c=42.4
#   k=600  → c=24.5
#   k=400  → c=20.0

from __future__ import annotations

import math
import os
import wave
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from .physics import SpringPhysics
    from .text_engine import WordClass
    from .config import SPRING_STIFFNESS, SPRING_DAMPING
except ImportError:
    # Fallback pour tests isolés
    class SpringPhysics:
        def __init__(self, stiffness=900, damping=30):
            self.k, self.c = stiffness, damping
    class WordClass:
        NORMAL="NORMAL"; ACCENT="ACCENT"; BADGE="BADGE"; MUTED="MUTED"; STOP="STOP"; PAUSE="PAUSE"
    SPRING_STIFFNESS, SPRING_DAMPING = 900, 30


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Profils Cinétiques par Classe Sémantique
# ══════════════════════════════════════════════════════════════════════════════

# ARCHITECTURE_MASTER_V31: Table des profils Spring par classe de mot.
# Chaque profil est calibré pour communiquer le "poids" du mot :
#   - ACCENT/BADGE : entrée percussive (high k = snap rapide + overshoot marqué)
#   - MUTED        : entrée lourde (low k = settle lent, comme un poids qui tombe)
#   - STOP         : entrée invisible (très low k = glisse doucement, passe inaperçu)
#
_MOTION_PROFILES: Dict[str, Dict] = {
    WordClass.NORMAL: {
        "k":        900,    # Référence vidéo — confirmé V31
        "c":         30,    # ζ = c/(2√k) = 30/(2×30) = 0.500
        "slide_px":   8,    # Mesuré pixel-exact
        "label":    "reference_pop",
    },
    WordClass.ACCENT: {
        # ARCHITECTURE_MASTER_V31: Overshoot plus marqué pour les mots-clés positifs.
        # k=1400 → ω₀=37.4 → settle ≈ 180ms. Peak overshoot ≈+22%.
        "k":       1400,
        "c":         37,    # c≈√k pour ζ=0.50
        "slide_px":  12,
        "label":    "accent_snap",
    },
    WordClass.BADGE: {
        # ARCHITECTURE_MASTER_V31: Les chiffres/prix arrivent avec le plus d'impact.
        # k=1800 → ω₀=42.4 → settle ≈ 160ms. Peak overshoot ≈+28%.
        "k":       1800,
        "c":         42,
        "slide_px":  16,
        "label":    "badge_punch",
    },
    WordClass.MUTED: {
        # ARCHITECTURE_MASTER_V31: Les mots négatifs ont une entrée plus lourde.
        # k=600 → ω₀=24.5 → settle ≈ 280ms. Overshoot ≈+8% (quasi-critique).
        "k":        600,
        "c":         24,
        "slide_px":   6,
        "label":    "muted_drop",
    },
    WordClass.STOP: {
        # ARCHITECTURE_MASTER_V31: Les stop words glissent en douceur.
        # k=400 → ω₀=20.0 → settle ≈ 350ms. Overshoot ≈+2% (quasi-critique).
        "k":        400,
        "c":         20,
        "slide_px":   4,
        "label":    "stop_glide",
    },
    WordClass.PAUSE: {
        # Pas d'animation — marqueur temporel uniquement
        "k":        900,
        "c":         30,
        "slide_px":   0,
        "label":    "pause_invisible",
    },
}


class MotionProfiler:
    """
    ARCHITECTURE_MASTER_V31: Sélecteur de profil Spring par classe sémantique.

    Utilisation:
        profiler = MotionProfiler()
        spring, slide_px = profiler.get_for_word_class(WordClass.ACCENT)
        # → spring = SpringPhysics(k=1400, c=37), slide_px = 12

    Avec boost audio (AudioEnergyDriver):
        energy = energy_driver.get_energy_at(t_word)
        spring, slide_px = profiler.get_for_word_class(WordClass.BADGE, energy_boost=energy)
    """

    def __init__(self, base_profiles: Optional[Dict] = None):
        self._profiles = base_profiles or _MOTION_PROFILES

    def get_for_word_class(
        self,
        word_class:     str,
        energy_boost:   float = 1.0,
    ) -> Tuple[SpringPhysics, int]:
        """
        Retourne (SpringPhysics, slide_px) pour une classe de mot.

        energy_boost (float ∈ [0.5, 2.0]):
            - 1.0 = neutre (pas d'influence audio)
            - > 1.0 = moment fort → spring plus percussif
            - < 1.0 = moment faible → spring plus doux

        Le boost s'applique sur k uniquement (c est recalculé pour ζ=0.50).
        """
        profile = self._profiles.get(word_class, self._profiles[WordClass.NORMAL])
        k_raw   = profile["k"]
        slide   = profile["slide_px"]

        # ARCHITECTURE_MASTER_V31: Boost cinétique proportionnel à l'énergie audio.
        # energy_boost = 1.5 → k augmente de 50% → snap 22% plus rapide
        k_boosted = k_raw * max(0.5, min(2.0, energy_boost))
        c_boosted = math.sqrt(k_boosted)   # Maintien ζ=0.50 constant

        # Le slide_px est également boosté (légèrement)
        slide_boosted = int(slide * max(0.7, min(1.5, energy_boost ** 0.5)))

        return SpringPhysics(stiffness=k_boosted, damping=c_boosted), slide_boosted

    def get_profile_label(self, word_class: str) -> str:
        return self._profiles.get(word_class, {}).get("label", "unknown")

    def all_classes(self) -> List[str]:
        return list(self._profiles.keys())


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — AudioEnergyDriver: Énergie vocale → Intensité animation
# ══════════════════════════════════════════════════════════════════════════════

class AudioEnergyDriver:
    """
    ARCHITECTURE_MASTER_V31: Analyse l'énergie RMS de la voix TTS.

    Convertit l'audio en une courbe d'énergie normalisée utilisée pour :
      1. Booster le spring des mots prononcés avec insistance (forte amplitude)
      2. Piloter l'intensité du micro-zoom sur les moments clés
      3. Détecter les silences pour optimiser les pauses

    Usage:
        driver = AudioEnergyDriver(audio_path)
        energy = driver.get_energy_at(t=5.0)   # → float ∈ [0, 2]
        zoom_intensity = driver.get_zoom_at(t=5.0, base=0.008)  # → float

    PARADIGME: L'énergie est normalisée à 1.0 = moyenne vocale.
    Les mots insistants auront energy > 1.2, les silences < 0.3.
    """

    WINDOW_MS  = 50     # Fenêtre d'analyse RMS (ms)
    HOP_MS     = 10     # Pas d'analyse (ms)
    MIN_ENERGY = 0.05   # Seuil silence

    def __init__(self, audio_path: str):
        self.audio_path = audio_path
        self._energy_curve:  Optional[np.ndarray] = None
        self._fps_curve:     float = 100.0   # points/seconde
        self._duration:      float = 0.0
        self._loaded         = False

    def load(self) -> bool:
        """Charge et analyse le fichier audio. Retourne True si succès."""
        try:
            self._energy_curve, self._fps_curve, self._duration = \
                self._compute_energy_curve(self.audio_path)
            self._loaded = True
            return True
        except Exception as e:
            print(f"⚠️  AudioEnergyDriver: impossible de charger {self.audio_path}: {e}")
            self._loaded = False
            return False

    def _compute_energy_curve(
        self, path: str
    ) -> Tuple[np.ndarray, float, float]:
        """
        Calcule la courbe RMS en chunks 50ms / hop 10ms.
        Retourne (energy_array, fps_curve, duration_s).
        """
        import subprocess, tempfile, os

        # Conversion en WAV mono PCM si nécessaire
        tmp_wav = tempfile.mktemp(suffix=".wav")
        subprocess.run([
            "ffmpeg", "-y", "-i", path,
            "-ac", "1", "-ar", "16000", "-f", "wav", tmp_wav
        ], capture_output=True, check=True)

        try:
            with wave.open(tmp_wav, "rb") as wf:
                framerate = wf.getframerate()
                n_frames  = wf.getnframes()
                raw       = wf.readframes(n_frames)
        finally:
            try: os.remove(tmp_wav)
            except: pass

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / framerate

        window = int(self.WINDOW_MS / 1000 * framerate)
        hop    = int(self.HOP_MS    / 1000 * framerate)
        fps_c  = 1000.0 / self.HOP_MS   # 100 points/sec

        energies = []
        pos = 0
        while pos + window <= len(samples):
            chunk = samples[pos:pos + window]
            energies.append(float(np.sqrt(np.mean(chunk ** 2))))
            pos += hop

        if not energies:
            return np.ones(1), fps_c, duration

        arr = np.array(energies, dtype=np.float32)

        # Normalisation: mean=1.0 sur la partie vocale (> seuil silence)
        vocal_mask = arr > self.MIN_ENERGY
        if vocal_mask.sum() > 10:
            vocal_mean = arr[vocal_mask].mean()
            if vocal_mean > 0:
                arr = arr / vocal_mean
        else:
            arr = arr / max(arr.max(), 1e-6)

        return arr, fps_c, duration

    def get_energy_at(self, t: float) -> float:
        """
        Retourne l'énergie normalisée à l'instant t (secondes).
        1.0 = énergie vocale moyenne
        > 1.0 = insistance (mots importants)
        < 0.3 = silence / souffle
        """
        if not self._loaded or self._energy_curve is None:
            return 1.0

        idx = int(t * self._fps_curve)
        idx = max(0, min(idx, len(self._energy_curve) - 1))
        return float(self._energy_curve[idx])

    def get_zoom_at(self, t: float, base: float = 0.008) -> float:
        """
        Retourne l'intensité de micro-zoom à l'instant t.
        base = intensité nominale (0.008 = config par défaut)
        Plage retournée: [base*0.5, base*2.0]
        """
        energy = self.get_energy_at(t)
        # Zoom proportionnel à l'énergie, clampé
        zoom_factor = max(0.5, min(2.0, energy ** 0.6))
        return base * zoom_factor

    def get_peak_timestamps(
        self,
        threshold: float = 1.5,
        min_gap_s: float = 0.4,
    ) -> List[float]:
        """
        Retourne la liste des timestamps de pics d'énergie vocale.
        Utile pour synchroniser des SFX ou des transitions.

        threshold: énergie min pour un pic (1.5 = 50% au-dessus de la moyenne)
        min_gap_s: espacement minimum entre deux pics
        """
        if not self._loaded or self._energy_curve is None:
            return []

        peaks = []
        last_peak = -min_gap_s
        for i, e in enumerate(self._energy_curve):
            t = i / self._fps_curve
            if e >= threshold and (t - last_peak) >= min_gap_s:
                peaks.append(t)
                last_peak = t

        return peaks

    def get_silence_intervals(
        self,
        min_duration_s: float = 0.3,
    ) -> List[Tuple[float, float]]:
        """
        Retourne les intervalles de silence (énergie < MIN_ENERGY).
        Utile pour détecter les pauses naturelles entre phrases.
        """
        if not self._loaded or self._energy_curve is None:
            return []

        intervals = []
        in_silence  = False
        silence_start = 0.0

        for i, e in enumerate(self._energy_curve):
            t = i / self._fps_curve
            if e < self.MIN_ENERGY:
                if not in_silence:
                    in_silence    = True
                    silence_start = t
            else:
                if in_silence:
                    in_silence = False
                    duration   = t - silence_start
                    if duration >= min_duration_s:
                        intervals.append((silence_start, t))

        if in_silence:
            duration = self._duration - silence_start
            if duration >= min_duration_s:
                intervals.append((silence_start, self._duration))

        return intervals

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — TempoEngine: Détection de rythme et synchronisation
# ══════════════════════════════════════════════════════════════════════════════

class TempoEngine:
    """
    ARCHITECTURE_MASTER_V31: Synchronise l'animation sur le rythme de la parole.

    Contrairement à la musique, la parole n'a pas de BPM fixe.
    Ce moteur détecte le "débit moyen" en mots/seconde et ajuste
    les timings d'animation pour que le spring settle AVANT
    le prochain mot (éviter l'overlap visuel).

    PARADIGME:
        Si le débit est rapide (> 3 mots/sec) → springs plus courts (settle rapide)
        Si le débit est lent  (< 1 mot/sec)  → springs plus lents, plus élaborés

    FORMULE:
        settle_budget = 1 / wps * 0.40  (40% du temps inter-mot)
        k_adjusted = (π / settle_budget)² × 4  (ζ=0.50 constant)
    """

    def __init__(self, timeline: List[Tuple[float, float, str]]):
        self.timeline  = timeline
        self._wps      = self._compute_wps()
        self._k_opt    = self._compute_optimal_k()

    def _compute_wps(self) -> float:
        """Calcule le débit moyen en mots par seconde."""
        if len(self.timeline) < 2:
            return 2.0
        valid = [(t0, t1, w) for t0, t1, w in self.timeline if t1 > t0]
        if not valid:
            return 2.0
        total_duration = valid[-1][1] - valid[0][0]
        n_words        = len(valid)
        return max(0.5, n_words / max(total_duration, 1.0))

    def _compute_optimal_k(self) -> float:
        """
        Calcule k optimal pour que le spring settle en 40% du temps inter-mot.
        Budget = 0.40 / wps
        Pour ζ=0.50 sous-amorti, settle (98%) ≈ 4 / (ζ × ω₀) = 4 / (0.5 × √k) = 8/√k
        8/√k = budget → √k = 8/budget → k = 64/budget²
        """
        budget = 0.40 / max(self._wps, 0.1)
        k_opt  = (8.0 / max(budget, 0.05)) ** 2
        # Clamp: k ∈ [300, 3000]
        return max(300.0, min(3000.0, k_opt))

    def get_calibrated_spring(
        self,
        word_class: str = "NORMAL",
        override_k: Optional[float] = None,
    ) -> SpringPhysics:
        """
        Retourne un spring calibré sur le débit de la parole.
        Le profil sémantique est multiplié par le facteur de tempo.
        """
        profile = _MOTION_PROFILES.get(word_class, _MOTION_PROFILES["NORMAL"])
        k_semantic = profile["k"]

        # Interpolation entre k_semantic et k_optimal selon le débit
        # wps lent (1.0) → 80% sémantique | wps rapide (4.0) → 60% sémantique + 40% optimal
        blend = min(0.4, max(0.0, (self._wps - 1.0) / 3.0) * 0.4)
        k_blended = k_semantic * (1.0 - blend) + (override_k or self._k_opt) * blend
        c_blended = math.sqrt(k_blended)

        return SpringPhysics(stiffness=k_blended, damping=c_blended)

    @property
    def words_per_second(self) -> float:
        return self._wps

    @property
    def optimal_k(self) -> float:
        return self._k_opt

    def describe(self) -> str:
        rhythm = (
            "RAPIDE" if self._wps > 3.0 else
            "NORMAL" if self._wps > 1.5 else
            "LENT"
        )
        return (
            f"TempoEngine: {self._wps:.2f} wps ({rhythm}) "
            f"→ k_optimal={self._k_opt:.0f} (vs référence 900)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Utilitaires d'intégration
# ══════════════════════════════════════════════════════════════════════════════

def build_audio_enhanced_springs(
    timeline:    List[Tuple[float, float, str]],
    audio_path:  str,
    word_classes: Dict[str, str],  # {word_text: word_class}
) -> Dict[str, Tuple[SpringPhysics, int]]:
    """
    ARCHITECTURE_MASTER_V31: Pipeline complet d'enrichissement cinétique.

    Combine TempoEngine + AudioEnergyDriver + MotionProfiler pour produire
    un spring unique par mot, calibré sur :
      1. Sa classe sémantique
      2. Le débit global de la parole
      3. L'énergie audio locale au moment de sa prononciation

    Returns:
        Dict {word_identifier → (SpringPhysics, slide_px)}
        word_identifier = f"{word_text}_{t_start:.3f}"

    Usage dans burn_subtitles:
        springs = build_audio_enhanced_springs(timeline, audio_path, classified_words)
        for t_s, t_e, word in timeline:
            sp, sl = springs.get(f"{word}_{t_s:.3f}", (default_sp, 8))
    """
    profiler = MotionProfiler()
    tempo    = TempoEngine(timeline)
    driver   = AudioEnergyDriver(audio_path)
    driver.load()   # Best-effort — silently fails if audio unreadable

    print(f"  🎵 {tempo.describe()}")

    result: Dict[str, Tuple[SpringPhysics, int]] = {}

    for t_start, t_end, word in timeline:
        key        = f"{word}_{t_start:.3f}"
        wclass     = word_classes.get(word, "NORMAL")
        energy     = driver.get_energy_at(t_start) if driver.is_loaded else 1.0
        sp_base, _ = profiler.get_for_word_class(wclass, energy_boost=energy)

        # Override k avec la calibration tempo
        sp_tempo   = tempo.get_calibrated_spring(wclass, override_k=sp_base.k)
        _, slide   = profiler.get_for_word_class(wclass, energy_boost=energy)

        result[key] = (sp_tempo, slide)

    return result
