"""Pixel-level layout-contract check: archive reference overlays vs regenerated v2 overlays.

Every item is decided from pixel values plus the frame's own label, never by eye. Edges and dots
are checked against a REFERENCE RENDER of the same keypoints (`overlay_archive_trunc_style`
cuboid+dot layer on a sentinel background), because in the finished overlay a later element may
legitimately cover an earlier one:

  * dots (r=6) are drawn after the edges, so a distant pallet's 12 edges can be fully hidden;
  * the pose axes and the id labels are drawn after the dots, so a dot's centre pixel is often
    an axis colour or white.

A check therefore passes when the expected element is visible OR is covered only by an element the
archive draws later - never when it is simply absent or the wrong colour.

  X/Y/Z edge colour        (255,80,80)/(80,220,80)/(80,130,255) where the reference render has them
  keypoint 0..8 colours    a dot of KP_COLORS[i] centred on the label's projected corner i
                           (this is also the "keypoints lie on the cuboid projection" check)
  centroid white           a white r=7 disc at the projected centroid
  pose axes                >=1 axis segment drawn, in AXIS_COLORS, outside panel+legend
  info panel               (6,6) and (181,246) black, anti-aliased white text inside the rect
  axis legend              swatches at the exact archive offsets == (255,60,60)/(60,220,60)/(80,130,255)
  no external panel        overlay size == RGB size (also "output size equals RGB size")
  no full-width header     the top band is not a solid bar spanning the full width

Usage:
  python scripts/data_prep/blender/_verify_archive_style_pixels.py \
      --archive-indices 0,1,2,3,4,5,6,7,9,11,16,61 \
      --new-indices 0,2,7,8,10,12,14,22,24,31,40,49
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import overlay_archive_trunc_style as ARCHIVE  # noqa: E402
import overlay_v2_detailed as OV  # noqa: E402

REPO = _THIS_DIR.parents[2]
ARCHIVE_ROOT = REPO / "data/pallet/reference/golden_overlay/trunc_addon_v1_pilot"  # registry: golden_overlay_reference
NEW_ROOT = REPO / "data/pallet/archive/superseded_runs/_v2_smoke50_9d"

CHECKS = [
    "X edge red", "Y edge green", "Z edge blue", "keypoint 0~8 distinct colors",
    "centroid white", "pose X/Y/Z axes visible", "top-left in-image info panel",
    "bottom-right axis legend", "no external panel", "no full-width audit header",
    "keypoints on cuboid projection", "output size equals RGB size",
]


def count_color(arr: np.ndarray, rgb: tuple[int, int, int], mask: np.ndarray | None = None) -> int:
    hit = np.all(arr == np.array(rgb, dtype=arr.dtype), axis=-1)
    if mask is not None:
        hit = hit & mask
    return int(hit.sum())


def outside_chrome_mask(h: int, w: int) -> np.ndarray:
    """True everywhere except the info panel and the legend (so their swatches never count)."""
    m = np.ones((h, w), dtype=bool)
    m[ARCHIVE.PANEL_Y:ARCHIVE.PANEL_Y + ARCHIVE.PANEL_H + 1,
      ARCHIVE.PANEL_X:ARCHIVE.PANEL_X + ARCHIVE.PANEL_W + 1] = False
    lx = w - ARCHIVE.LEGEND_W - ARCHIVE.LEGEND_MARGIN
    ly = h - ARCHIVE.LEGEND_H - ARCHIVE.LEGEND_MARGIN
    m[ly:ly + ARCHIVE.LEGEND_H + 1, lx:lx + ARCHIVE.LEGEND_W + 1] = False
    return m


SENTINEL = (1, 2, 3)


def reference_layers(kps: list, w: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(edges only, edges+dots without id labels, id-label mask) on a sentinel background.

    Three layers, because two things are drawn over the edges/dots by the archive itself:
      * the r=6 dots (a distant pallet's 12 edges can be entirely inside them);
      * the anti-aliased id labels, whose pixels blend with whatever is underneath - in the real
        overlay that is the photo, here it would be the sentinel, so they can never be compared
        directly and are treated as "covered".
    """
    pts = ARCHIVE.normalize_keypoints(kps or [])
    edges = Image.new("RGB", (w, h), SENTINEL)
    plain = Image.new("RGB", (w, h), SENTINEL)
    labelled = Image.new("RGB", (w, h), SENTINEL)
    if len(pts) >= 9:
        pts2d = [(p[0], p[1]) for p in pts]
        for target in (edges, plain, labelled):
            d = ImageDraw.Draw(target)
            for a, b in ARCHIVE.EDGES:
                e = ((a, b) if (a, b) in ARCHIVE.X_EDGES | ARCHIVE.Y_EDGES | ARCHIVE.Z_EDGES
                     else (b, a))
                color = (ARCHIVE.COLOR_X_EDGE if e in ARCHIVE.X_EDGES else
                         ARCHIVE.COLOR_Y_EDGE if e in ARCHIVE.Y_EDGES else
                         ARCHIVE.COLOR_Z_EDGE if e in ARCHIVE.Z_EDGES else ARCHIVE.COLOR_OTHER_EDGE)
                d.line([pts2d[a], pts2d[b]], fill=color, width=ARCHIVE.EDGE_WIDTH)
            if target is edges:
                continue
            for idx, (x, y, z) in enumerate(pts):
                col = ARCHIVE.KP_COLORS.get(idx, (255, 255, 255))
                if not (0 <= x <= w and 0 <= y <= h and z > 0):
                    col = ARCHIVE.COLOR_KP_OFFSCREEN
                r = ARCHIVE.KP_RADIUS_CENTROID if idx == 8 else ARCHIVE.KP_RADIUS
                d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(0, 0, 0))
                if target is labelled:
                    d.text((x + r + 2, y - r - 2), str(idx), fill=(255, 255, 255),
                           font=ARCHIVE.FONT)
    plain_a, labelled_a = np.asarray(plain), np.asarray(labelled)
    return np.asarray(edges), plain_a, np.any(plain_a != labelled_a, axis=-1)


LATER_COLORS = list(ARCHIVE.AXIS_COLORS) + [(255, 255, 255), (0, 0, 0)]


def is_aa_blend(actual: np.ndarray, ref_color: np.ndarray, tol: float = 3.0) -> bool:
    """True if `actual` is a convex blend of `ref_color` with a colour drawn later.

    The axis letters X/Y/Z are anti-aliased and at this size never reach their full colour, so an
    edge pixel under one is neither the edge colour nor the axis colour but a mix of the two.
    """
    for c in LATER_COLORS:
        c = np.asarray(c, dtype=float)
        d = ref_color - c
        denom = float(d @ d)
        if denom == 0:
            continue
        alpha = float((actual - c) @ d) / denom
        alpha = min(1.0, max(0.0, alpha))
        if np.abs(actual - (alpha * ref_color + (1 - alpha) * c)).max() <= tol:
            return True
    return False


def matches_or_covered(arr: np.ndarray, ref: np.ndarray, sel: np.ndarray,
                       later: np.ndarray) -> tuple[int, int, int, int]:
    """(n selected, n identical to the reference, n covered by a later element, n unexplained)."""
    n = int(sel.sum())
    same = np.all(arr == ref, axis=-1)
    ok = int((sel & same).sum())
    rest = sel & ~same
    cov = int((rest & later).sum())
    bad = 0
    h, w = arr.shape[:2]
    ys, xs = np.where(rest & ~later)
    for y, x in zip(ys, xs):
        want = ref[y, x]
        # 1 px rasterisation drift: the archive JSON rounds the projection to 2 decimals, so a
        # diagonal line can land one pixel off. The colour is still there, next door.
        window = arr[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
        if np.any(np.all(window == want, axis=-1)):
            continue
        if not is_aa_blend(arr[y, x].astype(float), want.astype(float)):
            bad += 1
    return n, ok, n - ok - bad, bad


def dilate1(mask: np.ndarray) -> np.ndarray:
    """1 px 8-neighbour dilation (no scipy dependency)."""
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def disc(cx: float, cy: float, r: int, w: int, h: int) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def check_one(overlay_path: Path, rgb_path: Path, kps: list, axes_drawn: int) -> dict:
    im = Image.open(overlay_path).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]
    rgb_size = Image.open(rgb_path).size
    out = {}
    free = outside_chrome_mask(h, w)
    ref_edges, ref_full, text_mask = reference_layers(kps, w, h)
    pts = ARCHIVE.normalize_keypoints(kps or [])

    # Elements the archive draws AFTER the cuboid/dot layer: the id labels, the 3 pose axes (line +
    # end dot with a black outline + letter), then the panel and the legend rectangles.
    later = text_mask.copy()
    for c in list(ARCHIVE.AXIS_COLORS) + [(0, 0, 0), (255, 255, 255)]:
        later |= np.all(arr == np.array(c, dtype=arr.dtype), axis=-1)
    # the axis letters are anti-aliased, so an edge pixel next to one is a blend, not a wrong colour
    later = dilate1(later)
    later |= ~free

    detail_edges = {}
    for name, color in (("X edge red", ARCHIVE.COLOR_X_EDGE),
                        ("Y edge green", ARCHIVE.COLOR_Y_EDGE),
                        ("Z edge blue", ARCHIVE.COLOR_Z_EDGE)):
        drawn = int(np.all(ref_edges == np.array(color, dtype=ref_edges.dtype), axis=-1).sum())
        sel = np.all(ref_full == np.array(color, dtype=ref_full.dtype), axis=-1)
        n, ok, cov, bad = matches_or_covered(arr, ref_full, sel, later)
        out[name] = drawn > 0 and bad == 0
        detail_edges[name] = (f"drawn {drawn}px, survives dots {n}px, "
                              f"{ok} match + {cov} covered, {bad} bad")

    # A dot of KP_COLORS[i] centred on the label's projected corner i. The reference has the same
    # draw order, so a dot hidden under a LATER DOT is compared against what the archive shows too.
    kp_hits, kp_total = 0, 0
    for i, (x, y, z) in enumerate(pts):
        if i >= 9 or not (0 <= x <= w - 1 and 0 <= y <= h - 1 and z > 0):
            continue
        px, py = int(round(x)), int(round(y))
        kp_total += 1
        expected = tuple(int(v) for v in ref_full[py, px])
        actual = tuple(int(v) for v in arr[py, px])
        if expected != SENTINEL and (actual == expected or later[py, px]
                                     or is_aa_blend(arr[py, px].astype(float),
                                                    ref_full[py, px].astype(float))):
            kp_hits += 1
    out["keypoints on cuboid projection"] = kp_total > 0 and kp_hits == kp_total

    # every keypoint colour the reference puts on screen is on screen (or covered) in the overlay
    kp_seen, kp_expected = 0, 0
    for c in ARCHIVE.KP_COLORS.values():
        sel = np.all(ref_full == np.array(c, dtype=ref_full.dtype), axis=-1)
        if not sel.any():
            continue
        kp_expected += 1
        n, ok, cov, bad = matches_or_covered(arr, ref_full, sel, later)
        kp_seen += int(bad == 0)
    out["keypoint 0~8 distinct colors"] = kp_expected >= 2 and kp_seen == kp_expected

    white_in_disc = -1
    # Same bounds the archive itself uses to decide a keypoint is on screen (`<= W`, `<= H`,
    # not w-1/h-1): a centroid on the very last row is drawn, just clipped by the canvas.
    if len(pts) >= 9 and 0 <= pts[8][0] <= w and 0 <= pts[8][1] <= h:
        d = disc(pts[8][0], pts[8][1], ARCHIVE.KP_RADIUS_CENTROID, w, h)
        sel = d & np.all(ref_full == np.array((255, 255, 255), dtype=ref_full.dtype), axis=-1)
        n, ok, cov, bad = matches_or_covered(arr, ref_full, sel, later)
        white_in_disc = ok
        out["centroid white"] = n > 0 and bad == 0
    else:
        out["centroid white"] = False

    out["pose X/Y/Z axes visible"] = axes_drawn > 0 and any(
        count_color(arr, c, free) > 0 for c in ARCHIVE.AXIS_COLORS)

    px_tl = tuple(int(v) for v in arr[ARCHIVE.PANEL_Y, ARCHIVE.PANEL_X])
    px_br = tuple(int(v) for v in arr[ARCHIVE.PANEL_Y + ARCHIVE.PANEL_H,
                                      ARCHIVE.PANEL_X + ARCHIVE.PANEL_W])
    panel_box = arr[ARCHIVE.PANEL_Y:ARCHIVE.PANEL_Y + ARCHIVE.PANEL_H,
                    ARCHIVE.PANEL_X:ARCHIVE.PANEL_X + ARCHIVE.PANEL_W]
    panel_ink = int((panel_box.min(axis=-1) > 120).sum())  # AA white text, cores near 240
    out["top-left in-image info panel"] = (px_tl == (0, 0, 0) and px_br == (0, 0, 0)
                                           and panel_ink > 200)

    lx = w - ARCHIVE.LEGEND_W - ARCHIVE.LEGEND_MARGIN
    ly = h - ARCHIVE.LEGEND_H - ARCHIVE.LEGEND_MARGIN
    swatches = [((lx + 5, ly + 7), (255, 60, 60)), ((lx + 5, ly + 22), (60, 220, 60)),
                ((lx + 5, ly + 37), (80, 130, 255))]
    out["bottom-right axis legend"] = all(
        tuple(int(v) for v in arr[y, x]) == c for (x, y), c in swatches)

    out["no external panel"] = (w, h) == rgb_size
    out["output size equals RGB size"] = (w, h) == rgb_size

    # a full-width audit header would be a solid uniform band across the whole first rows
    top_band = arr[0:6, :, :]
    out["no full-width audit header"] = bool(top_band.reshape(-1, 3).std(axis=0).max() > 1.0)

    out["_detail"] = {
        "size": [w, h], "rgb_size": list(rgb_size),
        "panel_tl": px_tl, "panel_br": px_br, "panel_ink_px": panel_ink,
        "legend_swatches": [tuple(int(v) for v in arr[y, x]) for (x, y), _ in swatches],
        "kp_on_projection": f"{kp_hits}/{kp_total}",
        "kp_colors_ok": f"{kp_seen}/{kp_expected}",
        "centroid_white_px_in_disc": white_in_disc,
        "edges": detail_edges,
        "axes_drawn": axes_drawn,
    }
    return out


def archive_frames(indices: list[int]) -> list[dict]:
    rows = []
    for i in indices:
        meta = json.loads((ARCHIVE_ROOT / f"{i:06d}.json").read_text(encoding="utf-8"))
        obj = meta["objects"][0]
        front = obj.get("keypoint_in_front_of_camera") or [True] * 9
        pts = list(obj["projected_cuboid"]) + [obj["projected_cuboid_centroid"]]
        kps = [(p[0], p[1], 1.0 if front[j] else -1.0) for j, p in enumerate(pts)]
        rows.append({
            "name": f"{i:06d}.png",
            "overlay": ARCHIVE_ROOT / "overlay" / f"{i:06d}.png",
            "rgb": ARCHIVE_ROOT / f"{i:06d}.png",
            "kps": kps,
            # the archive always drew all three axes from the pose it had
            "axes_drawn": 3,
        })
    return rows


def new_frames(indices: list[int], root: Path = NEW_ROOT,
               overlay_dirname: str = "overlay_archive_style") -> list[dict]:
    rows = []
    for i in indices:
        lab, obj, _v2 = OV.AUDIT.load_label(root, i)
        geom = OV.frame_geometry(lab, obj) or {}
        kps = OV.archive_keypoints(geom)
        axes = OV.pose_axis_endpoints(geom, length=ARCHIVE.AXIS_LEN_M) or []
        rows.append({
            "name": f"f{i:04d}.png",
            "overlay": root / overlay_dirname / f"f{i:04d}.png",
            "rgb": root / "rgb" / f"f{i:04d}_rgb.png",
            "kps": kps,
            "axes_drawn": sum(1 for a in axes if a.get("ok")),
        })
    return rows


def run(rows: list[dict], title: str) -> list[dict]:
    results = []
    print(f"\n===== {title} =====")
    for r in rows:
        res = check_one(r["overlay"], r["rgb"], r["kps"], r["axes_drawn"])
        detail = res.pop("_detail")
        fails = [k for k in CHECKS if not res[k]]
        print(f"{r['name']:14s} {'PASS' if not fails else 'FAIL ' + ','.join(fails)}  {detail}")
        results.append({"frame": r["name"], "overlay": str(r["overlay"]),
                        "checks": res, "detail": detail})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-indices", default="0,1,2,3,4,5,6,7,9,11,16,61")
    ap.add_argument("--new-indices", default="0,2,7,8,10,12,14,22,24,31,40,49")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--new-root", default=str(NEW_ROOT))
    ap.add_argument("--new-overlay-dirname", default="overlay_archive_style")
    ap.add_argument("--skip-archive", action="store_true")
    args = ap.parse_args()

    a_idx = [int(x) for x in args.archive_indices.split(",") if x.strip()]
    n_idx = [int(x) for x in args.new_indices.split(",") if x.strip()]
    new_root = Path(args.new_root)
    out = {
        "archive": ([] if args.skip_archive
                    else run(archive_frames(a_idx), "ARCHIVE REFERENCE")),
        "new": run(new_frames(n_idx, new_root, args.new_overlay_dirname),
                   "NEW v2 archive-style"),
    }
    for side in ("archive", "new"):
        if not out[side]:
            continue
        per_check = {c: sum(1 for r in out[side] if r["checks"][c]) for c in CHECKS}
        print(f"\n[{side}] {len(out[side])} frames: " +
              ", ".join(f"{c}={v}/{len(out[side])}" for c, v in per_check.items()))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
