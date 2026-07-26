"""Restructure existing v4 batch folders to the r3 (DOPE-ready flat) layout.

Converts folders written by the OLD gen_dataset_v4.py (images/, json/, overlay/,
_crop/, _stats/ subdirs) into the test_palletobj_r3 layout WITHOUT re-rendering:

    <batch>/000000.png  000000.json  ...   (png + json moved to folder root)
    <batch>/overlay/000000.png ...          (FULL overlays, redrawn from json+png)

- png/json are MOVED from images/ and json/ to the folder root (content untouched).
- overlay/ is FULLY regenerated (every frame) from each json's projected_cuboid +
  the rendered png. Old sparse overlay_*.png are removed first.
- _crop/ is deleted (superseded by full overlay).
- _stats/*.json is MOVED to <parent>/logs/ (preserved, renamed with the batch tag).

draw_overlay_from_json() is importable so the verification step can reuse the exact
same drawing path as the (post-restructure) generator.

Usage:
    python scripts/data_prep/blender/_restructure_to_r3.py \
        --root data/pallet/training_data_v4_split \
        --batches train_batch_000 train_batch_001 \
        --delete train_batch_002
"""

import argparse
import json
import os
import shutil

from PIL import Image, ImageDraw

CORNER_COLORS_RGB = [
    (255, 0, 0), (255, 128, 0), (255, 255, 0), (0, 255, 0),
    (0, 0, 255), (0, 128, 255), (128, 0, 255), (255, 0, 255),
]
CUBOID_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)]


def _hud_lines(ann):
    """Best-effort HUD reconstructed from the json (matches generator fields)."""
    o = ann["objects"][0]
    cam = ann.get("camera_data", {})
    src = o.get("source_asset", o.get("name", "?"))
    rf = o.get("ratio_factors")
    if o.get("ratio_randomized") and rf:
        ratio_str = "YES " + ",".join(f"{x:.2f}" for x in rf)
    else:
        ratio_str = "no"
    return [
        f"{src}",
        f"ratio_rand: {ratio_str}",
        f"vis {o.get('visibility', 0):.0%}  "
        f"ray {o.get('raycast_visibility', 0):.0%}",
        f"elev {o.get('camera_elevation_deg', 0):.1f}deg  "
        f"azim {o.get('camera_azimuth_deg', 0):.1f}deg",
        f"FRONT facing cos {o.get('front_facing_cos', 0):.3f} (>=0.40)",
        f"facing margin {o.get('facing_margin', 0):.3f} (>=0.60)",
        f"FRONT=0123 cam-near? {'YES' if o.get('front_is_camera_near') else 'NO'}",
        f"connector-cross: {o.get('edge_connector_crossings', 0)} (0=ok)",
    ]


def draw_overlay_from_json(png_path, json_path, out_path):
    """Redraw the 9-keypoint cuboid overlay from json's projected_cuboid + png.

    Identical visual style to gen_dataset_v4.draw_overlay (face fills, green edges,
    numbered corner dots, white centroid, cyan HUD), but sourced from the json so it
    needs no Blender / re-render.
    """
    with open(json_path) as f:
        ann = json.load(f)
    o = ann["objects"][0]
    pc = o["projected_cuboid"]               # 8 corners
    cen = o["projected_cuboid_centroid"]     # centroid
    uv = [(float(x), float(y)) for x, y in pc] + [(float(cen[0]), float(cen[1]))]

    img = Image.open(png_path).convert("RGBA")
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)

    def poly(idxs, color):
        fd.polygon([(int(uv[i][0]), int(uv[i][1])) for i in idxs], fill=color)

    poly([0, 1, 2, 3], (0, 255, 0, 55))      # FRONT face
    poly([0, 1, 5, 4], (0, 200, 255, 35))    # top band
    img = Image.alpha_composite(img, face)

    draw = ImageDraw.Draw(img)
    for i, j in CUBOID_EDGES:
        draw.line([(int(uv[i][0]), int(uv[i][1])),
                   (int(uv[j][0]), int(uv[j][1]))],
                  fill=(0, 255, 0, 220), width=2)
    for i in range(8):
        cx, cy = int(uv[i][0]), int(uv[i][1])
        r = 7
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=CORNER_COLORS_RGB[i] + (255,), outline=(0, 0, 0, 255))
        draw.text((cx + 9, cy - 10), str(i), fill=(255, 255, 0, 255))
    cx, cy = int(uv[8][0]), int(uv[8][1])
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6],
                 fill=(255, 255, 255, 220), outline=(0, 0, 0, 255))
    draw.text((cx + 8, cy - 10), "8", fill=(255, 255, 255, 255))

    lines = _hud_lines(ann)
    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    bd.rectangle([(3, 3), (3 + 330, 3 + 14 * len(lines) + 6)], fill=(0, 0, 0, 180))
    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)
    y = 6
    for ln in lines:
        draw.text((8, y), ln, fill=(0, 255, 255, 255))
        y += 14
    img.convert("RGB").save(out_path)


def _move_flatten(batch_dir, sub):
    """Move <batch>/<sub>/{6d}.<ext> up to <batch>/ root. Returns moved count."""
    src = os.path.join(batch_dir, sub)
    if not os.path.isdir(src):
        return 0
    moved = 0
    for fn in os.listdir(src):
        s = os.path.join(src, fn)
        d = os.path.join(batch_dir, fn)
        if os.path.isfile(s):
            shutil.move(s, d)
            moved += 1
    # remove the now-empty subdir
    try:
        os.rmdir(src)
    except OSError:
        pass
    return moved


def restructure_batch(batch_dir, logs_dir):
    name = os.path.basename(batch_dir.rstrip("/\\"))
    print(f"\n=== restructure {name} ===")

    n_img = _move_flatten(batch_dir, "images")
    n_json = _move_flatten(batch_dir, "json")
    print(f"  moved images->root: {n_img}   json->root: {n_json}")

    # move _stats -> logs (preserve, tag with batch name)
    stats_dir = os.path.join(batch_dir, "_stats")
    n_stats = 0
    if os.path.isdir(stats_dir):
        os.makedirs(logs_dir, exist_ok=True)
        for fn in os.listdir(stats_dir):
            s = os.path.join(stats_dir, fn)
            if os.path.isfile(s):
                shutil.move(s, os.path.join(logs_dir, f"stats_{name}_{fn}"))
                n_stats += 1
        try:
            os.rmdir(stats_dir)
        except OSError:
            pass
    print(f"  moved _stats->logs: {n_stats}")

    # delete _crop
    crop_dir = os.path.join(batch_dir, "_crop")
    if os.path.isdir(crop_dir):
        shutil.rmtree(crop_dir)
        print("  deleted _crop/")

    # fully regenerate overlay/ from json+png
    ov_dir = os.path.join(batch_dir, "overlay")
    if os.path.isdir(ov_dir):
        shutil.rmtree(ov_dir)
    os.makedirs(ov_dir, exist_ok=True)

    pngs = sorted(f for f in os.listdir(batch_dir)
                  if f.endswith(".png") and f[:-4].isdigit())
    n_ov = 0
    missing = []
    for fn in pngs:
        stem = fn[:-4]
        jp = os.path.join(batch_dir, stem + ".json")
        if not os.path.isfile(jp):
            missing.append(stem)
            continue
        draw_overlay_from_json(os.path.join(batch_dir, fn), jp,
                               os.path.join(ov_dir, stem + ".png"))
        n_ov += 1
    print(f"  regenerated overlays: {n_ov}/{len(pngs)}"
          + (f"  MISSING json: {missing}" if missing else ""))

    # final tally
    root_png = len([f for f in os.listdir(batch_dir)
                    if f.endswith(".png") and f[:-4].isdigit()])
    root_json = len([f for f in os.listdir(batch_dir)
                     if f.endswith(".json") and f[:-5].isdigit()])
    ov_png = len(os.listdir(ov_dir))
    subdirs = sorted(d for d in os.listdir(batch_dir)
                     if os.path.isdir(os.path.join(batch_dir, d)))
    print(f"  RESULT: root png={root_png} json={root_json} overlay={ov_png} "
          f"subdirs={subdirs}")
    return root_png, root_json, ov_png


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--batches", nargs="*", default=[])
    ap.add_argument("--delete", nargs="*", default=[],
                    help="batch folders to delete entirely (e.g. partial chunks).")
    args = ap.parse_args()

    root = args.root if os.path.isabs(args.root) else os.path.abspath(args.root)
    logs_dir = os.path.join(root, "logs")

    for name in args.delete:
        d = os.path.join(root, name)
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"[DELETE] {name} (removed)")
        else:
            print(f"[DELETE] {name} (not found, skip)")

    for name in args.batches:
        restructure_batch(os.path.join(root, name), logs_dir)


if __name__ == "__main__":
    main()
