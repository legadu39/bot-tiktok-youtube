"""
test_kinetic_render.py — Test visuel et validation E2E du rendu kinetic apex.

Modes :
  classic   : render_apex_animated_scenes(on_frame=None) → accumulation → MP4
              (mode isolation, frames accumulées en mémoire)
  streaming : render_apex_animated_scenes(on_frame=queue.put) + ThreadPoolExecutor → FFmpeg stdin pipe
              (reproduit fidèlement le chemin nexus_brain.py, zéro accumulation mémoire)

Usage :
    python test_kinetic_render.py
    python test_kinetic_render.py --mode streaming
    python test_kinetic_render.py --mode streaming --words "Alpha Signal Rupture" --variant 7
    python test_kinetic_render.py --mode streaming --edge-cases
    python test_kinetic_render.py --fps 30 --duration 1.5
"""

import os
import sys
import argparse
import subprocess
import queue as _queue_mod
import concurrent.futures as _cf
import time
from pathlib import Path
from PIL import Image

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from tools.kinetic_renderer import render_apex_animated_scenes

# ── Paramètres par défaut ─────────────────────────────────────────────────────

DEFAULT_WORDS    = ["Vitesse", "Précision", "Impact", "Confiance", "Résultats"]
DEFAULT_FPS      = 30
DEFAULT_DURATION = 1.2   # secondes par mot


# ── Mock FFmpeg (FFMPEG_PATH=mock) ────────────────────────────────────────────

class _MockProcess:
    """
    Simule subprocess.Popen pour valider le pipeline Python sans binaire FFmpeg.
    Active quand FFMPEG_PATH=mock. Compte les octets reçus sans les écrire.
    """

    class _MockStdin:
        def __init__(self):
            self.bytes_written = 0

        def write(self, data: bytes):
            self.bytes_written += len(data)

        def close(self):
            pass

    def __init__(self):
        self.stdin = self._MockStdin()
        self.returncode = 0

    def communicate(self):
        return b"", b""


def _open_ffmpeg(width: int, height: int, fps: int, out_path: Path):
    """Retourne _MockProcess si FFMPEG_PATH=mock, sinon subprocess.Popen réel."""
    ffmpeg = os.environ.get("FFMPEG_PATH", "ffmpeg")
    if ffmpeg == "mock":
        return _MockProcess()
    cmd = [
        ffmpeg, "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}",
        "-framerate", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def _frames_to_mp4(frames_bytes: list, width: int, height: int, fps: int, out_path: Path):
    """Pipe une liste de frames RGB24 brutes vers FFmpeg (ou mock) → MP4."""
    proc = _open_ffmpeg(width, height, fps, out_path)
    for fb in frames_bytes:
        proc.stdin.write(fb)
    proc.stdin.close()
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{stderr.decode(errors='replace')}")


def _expected_frame_count(durations: list, fps: int) -> int:
    return sum(max(1, int(round(d * fps))) for d in durations)


# ── Mode streaming — chemin nexus_brain ──────────────────────────────────────

def _streaming_to_mp4(
    words:           list,
    durations:       list,
    variant_indices: list,
    metadata_list:   list,
    fps:             int,
    width:           int,
    height:          int,
    out_path:        Path,
) -> int:
    """
    Reproduit fidèlement le chemin nexus_brain.py :
      - render_apex_animated_scenes(on_frame=fq.put) tourne dans un ThreadPoolExecutor
      - thread principal consomme la queue → FFmpeg stdin pipe
    Retourne le nombre de frames écrites.
    Lève RuntimeError si Playwright ou FFmpeg échoue, AssertionError si le
    frame count ne correspond pas à l'attendu.
    """
    expected = _expected_frame_count(durations, fps)

    fq    = _queue_mod.Queue(maxsize=120)
    _DONE = object()
    _err  = [None]
    n_written = [0]

    def _run_playwright():
        try:
            render_apex_animated_scenes(
                scene_words     = words,
                durations       = durations,
                variant_indices = variant_indices,
                metadata_list   = metadata_list,
                fps             = fps,
                width           = width,
                height          = height,
                on_frame        = fq.put,
            )
        except Exception as exc:
            _err[0] = exc
        finally:
            fq.put(_DONE)

    mock_mode = os.environ.get("FFMPEG_PATH") == "mock"
    proc = _open_ffmpeg(width, height, fps, out_path)

    with _cf.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(_run_playwright)
        while True:
            item = fq.get()
            if item is _DONE:
                break
            proc.stdin.write(item)
            n_written[0] += 1

    proc.stdin.close()
    _, stderr = proc.communicate()

    if _err[0]:
        raise RuntimeError(f"Playwright: {_err[0]}")
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg:\n{stderr.decode(errors='replace')}")
    if not mock_mode and (not out_path.exists() or out_path.stat().st_size == 0):
        raise AssertionError("MP4 absent ou vide apres encodage")
    if n_written[0] != expected:
        raise AssertionError(
            f"Frame count incorrect — attendu {expected}, reçu {n_written[0]}"
        )

    return n_written[0]


# ── Cas limites streaming ─────────────────────────────────────────────────────

_EDGE_CASES = [
    {
        "label":    "1 scene courte (0.5s)",
        "words":    ["Alpha"],
        "duration": 0.5,
        "variant":  0,
    },
    {
        "label":    "10 scenes variant max (7)",
        "words":    ["Alpha", "Signal", "Rupture", "Precision", "Impact",
                     "Confiance", "Resultats", "Vitesse", "Elan", "Force"],
        "duration": 0.8,
        "variant":  7,
    },
    {
        "label":    "Mots unicode",
        "words":    ["Resumé", "Précision"],
        "duration": 1.0,
        "variant":  3,
    },
    {
        "label":    "Duree sub-frame (0.01s -> 1 frame)",
        "words":    ["Test"],
        "duration": 0.01,
        "variant":  0,
    },
]


# ── Runners ───────────────────────────────────────────────────────────────────

def run_classic(words: list, fps: int, duration: float, variant: int):
    from tools.config import WIDTH, HEIGHT
    w, h = WIDTH, HEIGHT

    durations       = [duration] * len(words)
    variant_indices = [variant]  * len(words)
    metadata_list   = [{}]       * len(words)

    print("[classic] Lancement du rendu Playwright...")
    t0 = time.perf_counter()
    all_scenes = render_apex_animated_scenes(
        scene_words     = words,
        durations       = durations,
        variant_indices = variant_indices,
        metadata_list   = metadata_list,
        fps             = fps,
        on_frame        = None,
    )
    elapsed = time.perf_counter() - t0

    all_frames = [fb for scene in all_scenes for fb in scene]
    total      = len(all_frames)
    expected   = _expected_frame_count(durations, fps)
    print(f"[classic] Frames rendues : {total} (attendu {expected}) — {elapsed:.2f}s")

    if total != expected:
        print(f"[classic] WARN frame count incorrect : attendu {expected}, reçu {total}")

    thumbs_dir = BASE / "test_kinetic_thumbs"
    thumbs_dir.mkdir(exist_ok=True)
    key_indices = sorted({0, total // 4, total // 2, 3 * total // 4, total - 1})
    for idx in key_indices:
        fb  = all_frames[idx]
        img = Image.frombytes("RGB", (w, h), fb)
        out = thumbs_dir / f"frame_{idx:04d}.png"
        img.save(str(out))
        print(f"[classic] Thumb : {out.name}")

    out_mp4 = BASE / "test_kinetic_preview.mp4"
    print(f"[classic] Assemblage MP4 -> {out_mp4.name} ...")
    _frames_to_mp4(all_frames, w, h, fps, out_mp4)
    size_mb = out_mp4.stat().st_size / 1_000_000
    print(f"[classic] OK — {out_mp4.name} ({size_mb:.1f} Mo)")

    print(f"\nRésumé classic :")
    print(f"  - Frames     : {total}")
    print(f"  - Thumbs PNG : {thumbs_dir.resolve()}")
    print(f"  - Vidéo      : {out_mp4.resolve()}")


def run_streaming(words: list, fps: int, duration: float, variant: int, edge_cases: bool = False):
    from tools.config import WIDTH, HEIGHT
    w, h = WIDTH, HEIGHT

    cases = _EDGE_CASES if edge_cases else [
        {"label": "cas principal", "words": words, "duration": duration, "variant": variant}
    ]

    results = []

    for case in cases:
        ws  = case["words"]
        dur = case["duration"]
        var = case["variant"]
        lbl = case["label"]

        durations       = [dur] * len(ws)
        variant_indices = [var] * len(ws)
        metadata_list   = [{}]  * len(ws)
        expected        = _expected_frame_count(durations, fps)

        slug    = "".join(c if c.isalnum() else "_" for c in lbl)
        out_mp4 = BASE / f"test_kinetic_streaming_{slug}.mp4"

        print(f"\n[streaming] Cas : {lbl}")
        print(f"  Mots            : {ws}")
        print(f"  Durée/mot       : {dur}s  |  Variant : {var}")
        print(f"  Frames attendues: {expected}")
        print(f"  Sortie          : {out_mp4.name}")

        try:
            t0 = time.perf_counter()
            n  = _streaming_to_mp4(ws, durations, variant_indices, metadata_list, fps, w, h, out_mp4)
            elapsed = time.perf_counter() - t0
            size_info = f"{out_mp4.stat().st_size / 1_000_000:.1f} Mo" if out_mp4.exists() else "mock"
            print(f"  [OK] {n} frames en {elapsed:.2f}s — {size_info}")
            results.append((lbl, True, f"{n} frames / {elapsed:.2f}s"))
        except (RuntimeError, AssertionError) as exc:
            print(f"  [KO] {exc}")
            results.append((lbl, False, str(exc)))

    print(f"\n{'='*60}")
    print("Résumé streaming :")
    for lbl, ok, detail in results:
        status = "OK" if ok else "KO"
        print(f"  [{status}] {lbl} — {detail}")
    print("=" * 60)

    if any(not ok for _, ok, _ in results):
        sys.exit(1)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test rendu kinetic apex")
    parser.add_argument(
        "--mode",
        choices=["classic", "streaming"],
        default="classic",
        help="classic : accumulation mémoire | streaming : queue+pipe FFmpeg (chemin nexus_brain)",
    )
    parser.add_argument("--words",      default=None,  help="Mots séparés par des espaces")
    parser.add_argument("--fps",        type=int,      default=DEFAULT_FPS)
    parser.add_argument("--duration",   type=float,    default=DEFAULT_DURATION, help="Durée par mot (s)")
    parser.add_argument("--variant",    type=int,      default=0, help="Variant index (0-7)")
    parser.add_argument(
        "--edge-cases",
        action="store_true",
        help="[streaming uniquement] Lance les 4 cas limites en série",
    )
    args = parser.parse_args()

    words = args.words.split() if args.words else DEFAULT_WORDS

    print(f"[test] Mode       : {args.mode}")
    print(f"[test] Mots       : {words}")
    print(f"[test] FPS        : {args.fps}")
    print(f"[test] Durée/mot  : {args.duration}s")
    print(f"[test] Variant    : {args.variant}")
    print(f"[test] Durée tot  : {len(words) * args.duration:.1f}s")
    print()

    if args.mode == "streaming":
        run_streaming(words, args.fps, args.duration, args.variant, edge_cases=args.edge_cases)
    else:
        run_classic(words, args.fps, args.duration, args.variant)


if __name__ == "__main__":
    main()
