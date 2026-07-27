"""Side-by-side sheet: archive reference overlay (left) vs regenerated v2 archive-style (right).

One-off report helper for reports/v2_overlay_fix/. Both sides are pasted at NATIVE size (no
resize) so the layout contract — panel origin/size, legend corner, dot radii — can be compared
pixel for pixel.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import sys

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from overlay_archive_trunc_style import FONT  # noqa: E402

REPO = _THIS_DIR.parents[2]
ARCHIVE_OVERLAY = REPO / "data/pallet/archive/trunc_addon_v1_pilot/overlay"
NEW_OVERLAY = REPO / "data/pallet/_v2_smoke50_9d/overlay_archive_style"

# (condition, archive frame, new frame)
PAIRS = [
    ("near / truncated", 4, 2),
    ("far", 5, 8),
    ("low elevation", 1, 0),
    ("high elevation", 61, 7),
    ("cargo", 9, 10),
    ("occluder", 11, 40),
]

GAP = 10
LABEL_H = 18
HEADER_H = 40
BG = (24, 24, 28)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "reports/v2_overlay_fix/archive_reference_vs_new.png"))
    args = ap.parse_args()

    rows = []
    for cond, a_idx, n_idx in PAIRS:
        left = Image.open(ARCHIVE_OVERLAY / f"{a_idx:06d}.png").convert("RGB")
        right = Image.open(NEW_OVERLAY / f"f{n_idx:04d}.png").convert("RGB")
        rows.append((cond, a_idx, n_idx, left, right))

    col_w = max(max(l.width for _, _, _, l, _ in rows), max(r.width for *_, r in rows))
    row_hs = [max(l.height, r.height) for _, _, _, l, r in rows]
    W = 2 * col_w + 3 * GAP
    H = HEADER_H + sum(h + LABEL_H + GAP for h in row_hs) + GAP

    sheet = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(sheet)
    dr.text((GAP, 8), "archive_reference_vs_new  |  LEFT: archive/trunc_addon_v1_pilot/overlay"
                      "   RIGHT: _v2_smoke50_9d/overlay_archive_style (regenerated, no Blender)",
            fill=(255, 255, 255), font=FONT)
    dr.text((GAP, 22), "both pasted at native size: panel (6,6,175x240), legend 90x60 bottom-right,"
                       " canvas == RGB size", fill=(180, 200, 255), font=FONT)

    y = HEADER_H
    for (cond, a_idx, n_idx, left, right), rh in zip(rows, row_hs):
        dr.text((GAP, y), f"[{cond}]  archive {a_idx:06d}.png", fill=(255, 220, 120), font=FONT)
        dr.text((col_w + 2 * GAP, y), f"[{cond}]  new f{n_idx:04d}.png", fill=(140, 255, 180), font=FONT)
        y += LABEL_H
        sheet.paste(left, (GAP, y))
        sheet.paste(right, (col_w + 2 * GAP, y))
        y += rh + GAP

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"[sheet] {out}  ({W}x{H}, {len(rows)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
