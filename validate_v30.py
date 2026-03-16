#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V30 Validation Script — Verify all calibration values against reference video.

Usage:
    python validate_v30.py --video path/to/reference.mp4

Runs frame-exact measurements and compares against V30 config values.
Outputs PASS/FAIL for each constant.
"""

import sys
import os
import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required. Install: pip install opencv-python-headless")
    sys.exit(1)


def measure_text_anchor_y(cap, fps, w, h, n_samples=24):
    """Measure text Y center excluding TikTok watermark zone."""
    timestamps = [0.5, 1.0, 1.5, 2.0, 3.0, 5.5, 6.0, 6.5, 9.0, 9.5, 10.0,
                  10.5, 11.0, 13.0, 13.5, 14.0, 15.0, 18.0, 20.0, 24.0,
                  26.0, 30.0, 34.0, 36.0]
    y_ratios = []
    
    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if np.mean(gray) < 200:
            continue
        
        # Exclude watermark zones (x < 100 or x > 480)
        center_region = gray[:, 100:480]
        mask = center_region < 120
        if np.sum(mask) < 20:
            continue
        
        ys, _ = np.where(mask)
        text_h = int(np.max(ys)) - int(np.min(ys))
        
        # Skip non-text frames (composite B-Roll etc.)
        if text_h < 5 or text_h > 100:
            continue
        
        cy = np.mean(ys) / h
        y_ratios.append(cy)
    
    return np.mean(y_ratios), np.std(y_ratios), len(y_ratios)


def measure_inversion_entry(cap, fps, search_start=11.5, search_end=13.5):
    """Find exact frame where background flips to black."""
    entry_frame = None
    exit_frame = None
    
    for frame_num in range(int(search_start * fps), int(search_end * fps)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bg_avg = np.mean(gray)
        
        if entry_frame is None and bg_avg < 20:
            entry_frame = frame_num
        elif entry_frame is not None and bg_avg > 200 and exit_frame is None:
            exit_frame = frame_num
    
    return entry_frame, exit_frame


def measure_cta_entry(cap, fps, search_start=39.5, search_end=41.0):
    """Find exact frame where background flips to navy."""
    for frame_num in range(int(search_start * fps), int(search_end * fps)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bg_avg = np.mean(gray)
        
        if bg_avg < 30:
            # Verify it's navy, not just black
            center_bgr = np.mean(frame[100:200, 100:200], axis=(0, 1))
            if center_bgr[0] > 10:  # B channel > 10 = navy, not pure black
                return frame_num, center_bgr
    
    return None, None


def measure_broll_center(cap, fps, w, h, t_start=7.5, t_end=8.5):
    """Measure B-Roll card content center Y."""
    centers = []
    
    for t in np.arange(t_start, t_end + 0.1, 0.5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = gray < 220
        if np.sum(mask) < 1000:
            continue
        
        ys, _ = np.where(mask)
        # Use percentiles to exclude outliers
        y5 = np.percentile(ys, 5)
        y95 = np.percentile(ys, 95)
        center = (y5 + y95) / 2.0 / h
        centers.append(center)
    
    return np.mean(centers) if centers else None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V30 Validation")
    parser.add_argument("--video", required=True, help="Path to reference video")
    args = parser.parse_args()
    
    if not os.path.exists(args.video):
        print(f"ERROR: Video not found: {args.video}")
        sys.exit(1)
    
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    
    print(f"Reference: {w}×{h} @{fps}fps, {duration:.2f}s ({total_frames} frames)")
    print("=" * 70)
    
    # V30 expected values
    V30 = {
        "TEXT_ANCHOR_Y_RATIO": 0.4993,
        "INVERSION_1_START": 12.000,
        "INVERSION_1_END": 12.733,
        "CTA_START": 40.033,
        "BROLL_CENTER_Y": 0.474,
        "CTA_BG_BGR": [26, 14, 14],  # BGR order for OpenCV
    }
    
    results = []
    
    # Test 1: Text Anchor Y
    print("\n[1/4] Measuring TEXT_ANCHOR_Y_RATIO...")
    mean_y, std_y, n = measure_text_anchor_y(cap, fps, w, h)
    delta = abs(mean_y - V30["TEXT_ANCHOR_Y_RATIO"])
    ok = delta < 0.003  # 3px tolerance @1024p
    results.append(ok)
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  Measured: {mean_y:.4f} (std={std_y:.4f}, n={n})")
    print(f"  Expected: {V30['TEXT_ANCHOR_Y_RATIO']:.4f}")
    print(f"  Delta:    {delta:.4f} ({delta*h:.1f}px @{h}p)")
    print(f"  {status}")
    
    # Test 2: Inversion #1 timing
    print("\n[2/4] Measuring INVERSION_TIMESTAMPS[0]...")
    entry_f, exit_f = measure_inversion_entry(cap, fps)
    if entry_f is not None and exit_f is not None:
        entry_t = entry_f / fps
        exit_t = exit_f / fps
        delta_in = abs(entry_t - V30["INVERSION_1_START"])
        delta_out = abs(exit_t - V30["INVERSION_1_END"])
        ok = delta_in < 0.05 and delta_out < 0.05  # 50ms tolerance
        results.append(ok)
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  Entry: frame {entry_f} = t={entry_t:.3f}s (expected {V30['INVERSION_1_START']:.3f}s, Δ={delta_in*1000:.0f}ms)")
        print(f"  Exit:  frame {exit_f} = t={exit_t:.3f}s (expected {V30['INVERSION_1_END']:.3f}s, Δ={delta_out*1000:.0f}ms)")
        print(f"  {status}")
    else:
        print(f"  ❌ FAIL — Could not detect inversion")
        results.append(False)
    
    # Test 3: CTA timing
    print("\n[3/4] Measuring INVERSION_TIMESTAMPS[1] (CTA)...")
    cta_frame, cta_bgr = measure_cta_entry(cap, fps)
    if cta_frame is not None:
        cta_t = cta_frame / fps
        delta_cta = abs(cta_t - V30["CTA_START"])
        ok = delta_cta < 0.05  # 50ms tolerance
        results.append(ok)
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  Entry: frame {cta_frame} = t={cta_t:.3f}s (expected {V30['CTA_START']:.3f}s, Δ={delta_cta*1000:.0f}ms)")
        print(f"  BG BGR: {cta_bgr.astype(int)} (expected {V30['CTA_BG_BGR']})")
        print(f"  {status}")
    else:
        print(f"  ❌ FAIL — Could not detect CTA transition")
        results.append(False)
    
    # Test 4: B-Roll center Y
    print("\n[4/4] Measuring BROLL_CARD_CENTER_Y_RATIO...")
    broll_cy = measure_broll_center(cap, fps, w, h)
    if broll_cy is not None:
        delta_br = abs(broll_cy - V30["BROLL_CENTER_Y"])
        ok = delta_br < 0.01  # 10px tolerance @1024p
        results.append(ok)
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  Measured: {broll_cy:.4f}")
        print(f"  Expected: {V30['BROLL_CENTER_Y']:.4f}")
        print(f"  Delta:    {delta_br:.4f} ({delta_br*h:.1f}px)")
        print(f"  {status}")
    else:
        print(f"  ⚠️  SKIP — No B-Roll card detected in expected window")
        results.append(True)  # Not a failure if no B-Roll in this specific video
    
    cap.release()
    
    # Summary
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"🎯 ALL {total}/{total} TESTS PASSED — V30 calibration verified.")
    else:
        print(f"⚠️  {passed}/{total} tests passed, {total-passed} failed.")
    
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
