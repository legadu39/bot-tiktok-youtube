#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V30 Migration Script — Apply all corrections automatically.

Usage:
    python apply_v30_patches.py --tools-dir ./tools

This script:
1. Replaces config.py entirely (already provided as V30 file)
2. Updates version comments in burner.py (V29→V30)
3. Updates version comments in scene_animator.py (V29→V30)

No code logic is changed in burner.py or scene_animator.py because they
import all constants from config.py. The V30 config.py corrections
propagate automatically.
"""

import os
import re
import sys
import shutil
from pathlib import Path


def patch_file(filepath: Path, replacements: list):
    """Apply a list of (old, new) string replacements to a file."""
    if not filepath.exists():
        print(f"  ⚠️  File not found: {filepath}")
        return False
    
    content = filepath.read_text(encoding='utf-8')
    original = content
    
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"  ✓ Patched: {old[:60]}...")
        else:
            print(f"  ⚠️  Pattern not found: {old[:60]}...")
    
    if content != original:
        # Backup
        backup = filepath.with_suffix('.py.v29_backup')
        shutil.copy2(filepath, backup)
        filepath.write_text(content, encoding='utf-8')
        print(f"  ✅ File patched. Backup: {backup.name}")
        return True
    else:
        print(f"  ℹ️  No changes needed in {filepath.name}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Apply V30 patches")
    parser.add_argument("--tools-dir", default="./tools", help="Path to tools/ directory")
    args = parser.parse_args()
    
    tools_dir = Path(args.tools_dir)
    if not tools_dir.exists():
        print(f"ERROR: {tools_dir} not found")
        sys.exit(1)
    
    print("=" * 60)
    print("NEXUS V30 Migration — Applying calibration patches")
    print("=" * 60)
    
    # ── 1. config.py (full replacement) ──
    print("\n[1/3] config.py — Full replacement")
    config_v30 = Path(__file__).parent / "tools" / "config.py"
    config_dest = tools_dir / "config.py"
    if config_v30.exists():
        backup = config_dest.with_suffix('.py.v29_backup')
        if config_dest.exists():
            shutil.copy2(config_dest, backup)
        shutil.copy2(config_v30, config_dest)
        print(f"  ✅ Replaced config.py with V30 version. Backup: {backup.name}")
    else:
        print(f"  ⚠️  V30 config.py not found at {config_v30}")
        print(f"  → Copy the provided config.py into {tools_dir}/")
    
    # ── 2. burner.py (comment updates) ──
    print("\n[2/3] burner.py — Version comment updates")
    burner_patches = [
        # Header version tag
        (
            "# ARCHITECTURE_MASTER_V29: SubtitleBurner — Pipeline Complet Définitif.",
            "# ARCHITECTURE_MASTER_V30: SubtitleBurner — Pipeline Complet Définitif (V30 Recalibration).",
        ),
        # TEXT_ANCHOR_Y comment
        (
            "# ARCHITECTURE_MASTER_V29: ancrage Y=0.4951H FIXE",
            "# ARCHITECTURE_MASTER_V30: ancrage Y=0.4993H FIXE (recalibré V30, 24 frames)",
        ),
        # Inversion timestamps docstring
        (
            "V29: [(12.07, 12.77), (40.20, 44.10)] — mesures frame-exact.",
            "V30: [(12.000, 12.733), (40.033, 44.033)] — mesures frame-exact recalibrées.",
        ),
        # BROLL center comment
        (
            "ARCHITECTURE_MASTER_V29: B-Roll card à BROLL_CARD_CENTER_Y_RATIO=0.471.",
            "ARCHITECTURE_MASTER_V30: B-Roll card à BROLL_CARD_CENTER_Y_RATIO=0.474 (recalibré).",
        ),
        # Burn subtitles docstring
        (
            "ARCHITECTURE_MASTER_V29: Point d'entrée principal.",
            "ARCHITECTURE_MASTER_V30: Point d'entrée principal (V30 recalibration).",
        ),
    ]
    patch_file(tools_dir / "burner.py", burner_patches)
    
    # ── 3. scene_animator.py (comment updates) ──
    print("\n[3/3] scene_animator.py — Version comment updates")
    animator_patches = [
        (
            "# ARCHITECTURE_MASTER_V29: SceneAnimator — positions broll DÉFINITIVES.",
            "# ARCHITECTURE_MASTER_V30: SceneAnimator — positions broll DÉFINITIVES (V30 Recalibration).",
        ),
        (
            "ARCHITECTURE_MASTER_V29: B-Roll card avec toutes corrections V29.",
            "ARCHITECTURE_MASTER_V30: B-Roll card avec corrections V30 (BROLL_CENTER_Y=0.474).",
        ),
        (
            "# ARCHITECTURE_MASTER_V29: BROLL_CARD_CENTER_Y_RATIO = 0.471",
            "# ARCHITECTURE_MASTER_V30: BROLL_CARD_CENTER_Y_RATIO = 0.474",
        ),
    ]
    patch_file(tools_dir / "scene_animator.py", animator_patches)
    
    print("\n" + "=" * 60)
    print("Migration complete. Summary of changes:")
    print("  • TEXT_ANCHOR_Y_RATIO: 0.4951 → 0.4993 (+4.3px @1024p)")
    print("  • INVERSION #1: (12.07,12.77) → (12.000,12.733) (-70ms)")
    print("  • INVERSION #2: (40.20,44.10) → (40.033,44.033) (-167ms)")
    print("  • BROLL_CENTER_Y: 0.471 → 0.474 (+3px)")
    print("=" * 60)


if __name__ == "__main__":
    main()