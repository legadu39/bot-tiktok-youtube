# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import random
import warnings
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
import numpy as np

# Imports internes
from .config import (
    TEXT_RGB, TEXT_RGB_INV, ACCENT_RGB, ACCENT_RGB_INV, 
    MUTED_RGB, MUTED_RGB_INV, TEXT_DIM_INV, 
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED
)
from .physics import ease_in_out_sine
from .vfx import build_sparkles
from .graphics import load_asset_image, render_phrase_rgba
from .text_engine import compute_phrase_style, group_into_phrases
from .compositor import WordClip, compose_frame, apply_continuous_zoom

warnings.filterwarnings("ignore")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from moviepy.editor import VideoClip as MpVideoClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("⚠️  moviepy manquant")


class SubtitleBurner:
    VID_W  = 1080
    VID_H  = 1920
    SAFE_W = 960

    FS_NORMAL = 75
    FS_IMPACT = 105
    FS_STOP   = 58
    FS_BADGE  = 95

    CY = 1920 // 2

    ENTRY_DUR      = 0.20
    EXIT_DUR       = 0.14
    STAGGER        = 0.00
    PRE_ROLL       = 0.08
    OVERLAP_OFFSET = 0.08
    SLIDE_OUT_PX   = 500
    GAP            = 30

    INVERSION_WORD_MIN = 10
    INVERSION_WORD_MAX = 14

    SFX_MAP = {
        "ACTION": "click", "ACCENT": "click",
        "BADGE":  "click_deep", "MUTED": "swoosh",
        "STOP":   None, "PAUSE": None,
    }

    def __init__(self, model_size: str = "base", platform: str = "shorts", font: str = "Inter-Bold", font_regular: str = "Inter-Regular", fontsize: int = None):
        self.available    = WHISPER_AVAILABLE
        self.model        = None
        self.model_size   = model_size
        self.platform     = platform
        self.fontsize     = fontsize or self.FS_NORMAL

        safe_v = {"shorts": 420, "tiktok": 520, "reels": 320}.get(platform, 420)
        mh     = int(1080 * 0.15)

        self.ass_header = f"""[Script Info]
Title: Nexus V22 Master — Spring Physics
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TekiyoBold,{font},{self.FS_NORMAL},&H00111111&,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,3,0,1,0,1,2,{mh},{mh},{safe_v},1
Style: TekiyoRegular,{font_regular},{self.FS_STOP},&H004D4A4A&,&H000000FF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,{mh},{mh},{safe_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    @staticmethod
    def strip_tags(text: str) -> str:
        return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

    def _is_stop(self, text: str) -> bool:
        words = text.lower().strip(".,!?:;'\"").split()
        return bool(words) and all(w.strip(".,!?;:") in STOP_WORDS for w in words)

    def get_semantic_class(self, text: str) -> str:
        clean = self.strip_tags(text).strip()
        if not clean or "[PAUSE]" in text.upper():
            return "PAUSE"
        if "[BADGE]" in text or re.search(r'\d+[\$€%]|[\$€]\d+|\d{2,}', clean):
            return "BADGE"
        if "[BOLD]" in text:
            return "ACTION"
        if "[LIGHT]" in text:
            return "STOP"
        low = clean.lower()
        if any(k in low for k in KEYWORDS_ACCENT):
            return "ACCENT"
        if any(k in low for k in KEYWORDS_MUTED):
            return "MUTED"
        if self._is_stop(clean):
            return "STOP"
        return "ACTION"

    def get_sfx_type(self, text: str) -> Optional[str]:
        return self.SFX_MAP.get(self.get_semantic_class(text))

    def _compute_inversion_intervals(self, all_clips: List[WordClip]) -> List[Tuple[float, float]]:
        intervals    = []
        sorted_clips = sorted(all_clips, key=lambda c: c.t_start)
        inv_active   = False
        inv_start    = 0.0
        word_count   = 0
        threshold    = random.randint(self.INVERSION_WORD_MIN, self.INVERSION_WORD_MAX)

        for clip in sorted_clips:
            word_count += 1
            if word_count >= threshold:
                if not inv_active:
                    inv_active = True
                    inv_start  = clip.t_start
                else:
                    inv_active = False
                    intervals.append((inv_start, clip.t_start))
                word_count = 0
                threshold  = random.randint(self.INVERSION_WORD_MIN, self.INVERSION_WORD_MAX)

        if inv_active and sorted_clips:
            intervals.append((inv_start, sorted_clips[-1].t_full_end))

        return intervals

    def _build_phrase_group(self, entries: List[Tuple[float, float, str]], next_grp_start: Optional[float], is_conclusion: bool) -> List[WordClip]:
        if not entries:
            return []

        phrase_start = entries[0][0]
        phrase_end   = entries[-1][1]
        phrase_text  = " ".join(self.strip_tags(e[2]) for e in entries).strip()

        if not phrase_text or "[PAUSE]" in phrase_text.upper():
            return []

        sems = [self.get_semantic_class(e[2]) for e in entries]
        sem_priority = ["MUTED","ACCENT","ACTION","BADGE","NORMAL","STOP","PAUSE"]
        sem = max(sems, key=lambda s: sem_priority.index(s) if s in sem_priority else 99)
        sem = "ACTION" if sem not in sem_priority[:6] else sem

        fs_base = self.FS_STOP if sem == "STOP" else (
                  self.FS_BADGE if sem == "BADGE" else
                  self.FS_IMPACT if sem in ("ACTION","ACCENT","MUTED") else
                  self.FS_NORMAL)

        fs, weight, color = compute_phrase_style(phrase_text, sem, fs_base)
        is_kw = sem in ("ACTION", "ACCENT", "MUTED", "BADGE")

        asset_arr = load_asset_image(phrase_text)
        if asset_arr is not None:
            target_h = max(60, int(fs * 1.2))
            ratio    = target_h / max(1, asset_arr.shape[0])
            target_w = max(1, int(asset_arr.shape[1] * ratio))
            pil_img  = Image.fromarray(asset_arr).resize((target_w, target_h), Image.LANCZOS)
            arr_n    = np.array(pil_img)
            arr_i    = arr_n
        else:
            arr_n = render_phrase_rgba(phrase_text, fs, weight=weight, color=color, max_w=self.SAFE_W, inverted=False)
            inv_color = (TEXT_RGB_INV if color == TEXT_RGB else
                         ACCENT_RGB_INV if color == ACCENT_RGB else
                         MUTED_RGB_INV if color == MUTED_RGB else
                         TEXT_DIM_INV)
            arr_i = render_phrase_rgba(phrase_text, fs, weight=weight, color=inv_color, max_w=self.SAFE_W, inverted=True)

        ph, pw = arr_n.shape[:2]
        x = (self.VID_W - pw) // 2
        y = self.CY - ph // 2

        t_start     = max(0.0, phrase_start - self.PRE_ROLL)
        t_entry_end = t_start + self.ENTRY_DUR

        if next_grp_start is not None:
            t_exit_start = next_grp_start - self.EXIT_DUR * 0.5
            t_full_end   = next_grp_start + self.OVERLAP_OFFSET
        else:
            t_exit_start = phrase_end - self.EXIT_DUR
            t_full_end   = phrase_end + 0.04

        return [WordClip(
            arr          = arr_n,
            arr_inv      = arr_i,
            target_x     = x,
            target_y     = y,
            t_start      = t_start,
            t_entry_end  = t_entry_end,
            t_exit_start = t_exit_start,
            t_full_end   = t_full_end,
            is_keyword   = is_kw,
            slide_px_out = self.SLIDE_OUT_PX,
        )]

    def burn_subtitles(self, video_clip, timeline: List[Tuple[float, float, str]]):
        if not MOVIEPY_AVAILABLE:
            return video_clip
        if not timeline:
            print("⚠️  [V22] Timeline vide.")
            return video_clip

        groups = group_into_phrases(timeline, max_chars=28, max_per_group=5)
        print(f"🎬  V22 Phrase Engine — {len(timeline)} entrées → {len(groups)} phrases")

        all_clips: List[WordClip] = []
        for i, grp in enumerate(groups):
            if len(grp) == 1 and "[PAUSE]" in grp[0][2].upper():
                continue
            next_start = None
            for future in groups[i+1:]:
                if not (len(future) == 1 and "[PAUSE]" in future[0][2].upper()):
                    next_start = future[0][0]
                    break
            is_conclusion = (i > 0 and grp[-1][2].strip().endswith((".", "!", "?")))
            all_clips.extend(self._build_phrase_group(grp, next_start, is_conclusion))

        inversion_intervals = self._compute_inversion_intervals(all_clips)
        print(f"🎨  V22 Inversions : {len(inversion_intervals)} intervalle(s)")

        particles_by_interval: List[List] = []
        for (t0, t1) in inversion_intervals:
            t_mid   = (t0 + t1) / 2
            active  = [c for c in all_clips if c.t_start <= t_mid <= c.t_full_end]
            if active:
                c  = active[0]
                cx = c.target_x + c.w // 2
                cy = c.target_y + c.h // 2
            else:
                cx, cy = self.VID_W // 2, self.VID_H // 2
            particles_by_interval.append(build_sparkles(cx, cy, n=4, orbit_rx=cx - c.target_x + 30 if active else 80, orbit_ry=30))
        print(f"✨  V22 Sparkles : {sum(len(p) for p in particles_by_interval)} particules générées")

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        last_valid_frame = None

        def make_frame(t: float) -> np.ndarray:
            nonlocal last_valid_frame
            try:
                base_frame       = video_clip.get_frame(t)
                last_valid_frame = base_frame
            except Exception:
                base_frame = (last_valid_frame if last_valid_frame is not None else np.zeros((vid_h, vid_w, 3), dtype=np.uint8))

            is_inverted = False
            active_particles = []
            for idx, (t0, t1) in enumerate(inversion_intervals):
                if t0 <= t <= t1:
                    is_inverted = True
                    if idx < len(particles_by_interval):
                        active_particles = particles_by_interval[idx]
                    break

            if is_inverted:
                base_frame = (255 - base_frame).astype(np.uint8)

            composite = compose_frame(t, all_clips, vid_w, vid_h, base_frame=base_frame, inverted=is_inverted, particles=active_particles)

            zoom_p     = ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = 1.0 + 0.04 * zoom_p
            composite  = apply_continuous_zoom(composite, zoom_scale)

            return composite

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)

        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    def _seconds_to_ass(self, s: float) -> str:
        h  = int(s // 3600)
        m  = int((s % 3600) // 60)
        sc = int(s % 60)
        cs = int((s - int(s)) * 100)
        return f"{h}:{m:02d}:{sc:02d}.{cs:02d}"

    def _load_model(self):
        if not self.model and self.available:
            print(f"⏳  Whisper '{self.model_size}'…")
            self.model = whisper.load_model(self.model_size)

    def _fin_chunk(self, chunks, wl):
        if wl:
            chunks.append({
                "start": wl[0]["start"],
                "end":   wl[-1]["end"],
                "text":  " ".join(w["word"] for w in wl).strip()
            })

    def _split_into_chunks(self, words: list) -> list:
        chunks, cur = [], []
        for wo in words:
            clean = wo["word"].replace("\\", "").replace("\n", " ").strip()
            if not clean:
                continue
            cur.append({"word": clean, "start": wo["start"], "end": wo["end"]})
            has_punct  = clean[-1] in ".?!:," if clean else False
            chunk_full = len(cur) >= 2
            if (not self._is_stop(clean)) or has_punct or chunk_full:
                self._fin_chunk(chunks, cur)
                cur = []
        if cur:
            self._fin_chunk(chunks, cur)
        return self._sanitize(chunks)

    def _sanitize(self, chunks):
        out, i = [], 0
        while i < len(chunks):
            c = chunks[i].copy()
            if c["end"] - c["start"] < 0.08 and i < len(chunks) - 1:
                nxt       = chunks[i+1]
                c["text"] = f"{c['text']} {nxt['text']}"
                c["end"]  = nxt["end"]
                out.append(c)
                i += 2
            else:
                out.append(c)
                i += 1
        return out

    def generate_ass_file(self, audio_path: Path, output_ass: Path) -> bool:
        if not self.available:
            return False
        self._load_model()
        try:
            result    = self.model.transcribe(str(audio_path), word_timestamps=True)
            all_words = [w for seg in result["segments"] for w in seg.get("words", [])]
            chunks    = self._split_into_chunks(all_words)
            with open(output_ass, "w", encoding="utf-8") as f:
                f.write(self.ass_header)
                for c in chunks:
                    st  = self._seconds_to_ass(c["start"])
                    en  = self._seconds_to_ass(c["end"])
                    txt = c["text"].replace("\\", "")
                    sem = self.get_semantic_class(txt)
                    sty = "TekiyoBold" if sem in ("ACTION","ACCENT","BADGE","MUTED") else "TekiyoRegular"
                    pop = (
                        r"{\fscx0\fscy0\alpha&HFF&"
                        r"\t(0,120,\fscx115\fscy115\alpha&H00&)"
                        r"\t(120,200,\fscx100\fscy100)}"
                    )
                    f.write(f"Dialogue: 0,{st},{en},{sty},,0,0,0,,{pop}{txt}\n")
            return True
        except Exception as e:
            print(f"❌  Whisper error: {e}")
            return False