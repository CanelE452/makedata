"""Non-destructive annotation normalization for train_palletobj_v3.

Reads original v3 (read-only), writes a NEW batch-structured tree:
  <out>/batch_xxx/mask_binary/{i:06d}.png   RLE-decoded binary {0,255}
  <out>/batch_xxx/annotations/{i:06d}.json  state-field keypoints
  <out>/{surface_fps_v1.json, manifest.json, audit_report.json}

Stage 1 (this file): RLE->binary mask, box(8)+center keypoint state fields,
world-point reprojection check, V_geom. Surface FPS keypoints are added when
surface_fps_v1.json is present (--surface-fps).

Projection convention (CONFIRMED on v3, median 0.02px vs projected_cuboid):
  Xc = Rcw^T (Xw - camt);  Xcv = Xc * [1,-1,-1];  u=fx Xcv.x/Xcv.z+cx; depth=Xcv.z

Run: python scripts/data_prep/postprocess_v3.py --batches batch_000 --dry-run
"""
import argparse, json, os, glob, tempfile, math
import numpy as np
from PIL import Image
import os          # noqa: E402  (Stage 2-D1.1 registry 조회용)
import sys         # noqa: E402
# Stage 2-D1.1: 경로 정본은 config/synthetic/pallet_paths.yaml 이다.
#   리터럴을 다시 적지 않고 registry 로 조회한다.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "blender"))
import pallet_data_paths as _pdp  # noqa: E402


EPS = 1e-6
CONV = np.array([1.0, -1.0, -1.0])  # render(Blender) -> OpenCV camera, confirmed


def quat_to_R(q):  # xyzw -> 3x3 rotation (cam->world)
    x, y, z, w = q
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)]])


def find_pallet(objects):
    pals = [o for o in objects if o.get("class") == "pallet"
            or "palletobj" in str(o.get("name", "")).lower()]
    if len(pals) != 1:
        raise ValueError(f"expected exactly 1 pallet object, got {len(pals)}")
    return pals[0]


def decode_rle(rle):
    """COCO column-major uncompressed RLE -> HxW uint8 {0,255}."""
    H, W = rle["size"]
    counts = rle["counts"]
    if not isinstance(counts, (list, tuple)):
        raise ValueError("compressed RLE string not supported; expected int counts")
    flat = np.zeros(H * W, np.uint8)
    pos, val = 0, 0
    for c in counts:
        flat[pos:pos + c] = val
        pos += c
        val ^= 1
    if pos != H * W:
        raise ValueError(f"RLE counts sum {pos} != {H*W}")
    return (flat.reshape((H, W), order="F") * 255).astype(np.uint8)


def project_world(Xw, camt, Rcw, fx, fy, cx, cy):
    """Xw: (N,3) world points -> uv (N,2), depth (N,)."""
    Xc = (np.asarray(Xw) - camt) @ Rcw          # Rcw^T (Xw-t) per row
    Xcv = Xc * CONV
    depth = Xcv[:, 2].copy()
    safe = np.where(np.abs(depth) < EPS, EPS, depth)
    u = fx * Xcv[:, 0] / safe + cx
    v = fy * Xcv[:, 1] / safe + cy
    return np.stack([u, v], 1), depth


def kp_states(uv, depth, W, H, mask, win=2):
    """Per-keypoint state dicts (heatmap/vector split + mask_support fraction)."""
    out = []
    for (u, v), d in zip(uv, depth):
        projectable = bool(d > EPS)
        inside = bool(0 <= u < W and 0 <= v < H)
        if inside:
            ui, vi = int(round(u)), int(round(v))
            y0, y1 = max(0, vi-win), min(H, vi+win+1)
            x0, x1 = max(0, ui-win), min(W, ui+win+1)
            patch = mask[y0:y1, x0:x1]
            frac = float((patch == 255).mean()) if patch.size else 0.0
            support = bool(frac > 0.5)
        else:
            frac, support = None, None
        out.append({
            "xy": [round(float(u), 2), round(float(v), 2)],
            "depth_camera": round(float(d), 4),
            "projectable": projectable,
            "in_front_of_camera": projectable,
            "inside_image": inside,
            "heatmap_valid": bool(projectable and inside),
            "vector_valid": projectable,
            "mask_support_fraction": (round(frac, 3) if frac is not None else None),
            "mask_support": support,
            "visibility_source": "mask_window_proxy",
        })
    return out


def atomic_write_json(path, obj):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=d)
    os.close(fd)
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def atomic_write_png(path, arr):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=d)
    os.close(fd)
    Image.fromarray(arr).save(tmp, format="PNG")
    os.replace(tmp, path)


def process_frame(jp, src_root, out_root, surface_obj=None, dry=False):
    rel = os.path.relpath(jp, src_root)            # batch_xxx/000000.json
    batch = rel.split(os.sep)[0]
    stem = os.path.splitext(os.path.basename(jp))[0]
    rgb = os.path.join(src_root, batch, stem + ".png")
    d = json.load(open(jp))
    cd = d["camera_data"]; K = cd["intrinsics"]
    fx, fy, cx, cy = K["fx"], K["fy"], K["cx"], K["cy"]
    W, H = K["resolution"]
    Rcw = quat_to_R(cd["quaternion_xyzw_worldframe"])
    camt = np.array(cd["location_worldframe"])
    ob = find_pallet(d["objects"])

    # --- mask ---
    mask = decode_rle(ob["mask_rle"])
    uniq = set(np.unique(mask).tolist())
    area = int((mask == 255).sum())
    # rgb resolution
    with Image.open(rgb) as im:
        rgb_wh = im.size  # (W,H)
    audit = {
        "frame": f"{batch}/{stem}",
        "mask_unique_ok": uniq.issubset({0, 255}),
        "mask_area_match": area == ob.get("mask_area_px"),
        "mask_empty": area == 0,
        "mask_full": area == W * H,
        "mask_size_match": (mask.shape == (H, W)) and (rgb_wh == (W, H)),
    }

    # --- box(8)+center keypoints: reproject from keypoints_3d_world ---
    kp3d = np.array(ob["keypoints_3d_world"])      # (9,3): 8 corners + center
    uv, depth = project_world(kp3d, camt, Rcw, fx, fy, cx, cy)
    # stage-1 convention check vs projected_cuboid (8 corners, ordered)
    pc = np.array(ob["projected_cuboid"])
    ord_err = np.abs(uv[:8] - pc)
    audit["reproj_ordered_max"] = float(ord_err.max())
    states = kp_states(uv, depth, W, H, mask)
    box_states, center_state = states[:8], states[8]
    V_geom = sum(s["heatmap_valid"] for s in box_states)
    V_proxy = sum(1 for s in box_states if s["heatmap_valid"] and s["mask_support"])
    audit["V_geom"] = V_geom
    audit["V_proxy_visible"] = V_proxy
    audit["keypoint_in_frame_orig"] = int(ob.get("num_corners_in_frame", -1))

    # --- surface keypoints (optional, stage-2) ---
    surf_states = None
    if surface_obj is not None:
        Row = quat_to_R(ob["quaternion_xyzw"])     # object->world
        tow = np.array(ob["location"])
        Xw_s = (surface_obj @ Row.T) + tow         # (8,3)
        uvs, ds = project_world(Xw_s, camt, Rcw, fx, fy, cx, cy)
        surf_states = kp_states(uvs, ds, W, H, mask)

    new_ann = {
        "camera_data": cd,
        "frame_meta": d.get("frame_meta", {}),
        "pallet": {
            "class": ob.get("class"), "name": ob.get("name"),
            "location": ob["location"], "quaternion_xyzw": ob["quaternion_xyzw"],
            "cuboid_dimensions_m": ob["cuboid_dimensions_m"],
            "keypoint_convention": ob.get("keypoint_convention"),
            "box_keypoints": box_states,        # 8 corners
            "center_keypoint": center_state,
            "surface_keypoints": surf_states,   # 8 or null
            "V_geom": V_geom, "V_proxy_visible": V_proxy,
            "num_box_corners_in_frame": V_geom,
            "num_box_corners_mask_supported": V_proxy,
            "binary_mask": f"mask_binary/{stem}.png",
            "mask_area_px": ob.get("mask_area_px"),
        },
    }
    if not dry:
        mb_dir = os.path.join(out_root, batch, "mask_binary")
        an_dir = os.path.join(out_root, batch, "annotations")
        os.makedirs(mb_dir, exist_ok=True); os.makedirs(an_dir, exist_ok=True)
        atomic_write_png(os.path.join(mb_dir, stem + ".png"), mask)
        atomic_write_json(os.path.join(an_dir, stem + ".json"), new_ann)
    return audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root",
                    default=_pdp.get("legacy_train_palletobj_v3_root"),
                    help="Stage 2-D1.1: registry legacy_train_palletobj_v3_root")
    ap.add_argument("--output-root",
                    default=_pdp.get("legacy_train_palletobj_v3_post_v1_root"))
    ap.add_argument("--batches", nargs="*", default=None, help="e.g. batch_000")
    ap.add_argument("--surface-fps", default=None, help="surface_fps_v1.json path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src = os.path.abspath(args.source_root); out = os.path.abspath(args.output_root)
    if out == src or out.startswith(src + os.sep):
        raise SystemExit("ABORT: output-root inside/equal source-root")

    surface_obj = None
    if args.surface_fps and os.path.isfile(args.surface_fps):
        sf = json.load(open(args.surface_fps))
        surface_obj = np.array(sf["points_object_frame"])
        print(f"[surface] loaded {len(surface_obj)} pts from {args.surface_fps}")

    batches = args.batches or [os.path.basename(p) for p in
                               sorted(glob.glob(os.path.join(src, "batch_*"))) if os.path.isdir(p)]
    audits = []; errors = []
    for b in batches:
        files = sorted(glob.glob(os.path.join(src, b, "[0-9]*.json")))
        if args.limit: files = files[:args.limit]
        for jp in files:
            try:
                audits.append(process_frame(jp, src, out, surface_obj, args.dry_run))
            except Exception as e:
                errors.append({"frame": os.path.relpath(jp, src), "error": str(e)})
    # summary
    n = len(audits)
    def rate(k): return sum(1 for a in audits if a.get(k))
    summary = {
        "n_frames": n, "n_errors": len(errors),
        "mask_unique_ok": rate("mask_unique_ok"),
        "mask_area_match": rate("mask_area_match"),
        "mask_empty": rate("mask_empty"),
        "mask_full": rate("mask_full"),
        "mask_size_match": rate("mask_size_match"),
        "reproj_ordered_max_p99": float(np.percentile([a["reproj_ordered_max"] for a in audits], 99)) if n else None,
        "reproj_ordered_max_worst": float(np.max([a["reproj_ordered_max"] for a in audits])) if n else None,
        "V_geom_hist": {str(v): sum(1 for a in audits if a["V_geom"]==v) for v in range(9)},
        "errors": errors[:50],
    }
    print(json.dumps(summary, indent=2))
    if not args.dry_run and n:
        os.makedirs(out, exist_ok=True)
        atomic_write_json(os.path.join(out, "audit_report.json"),
                          {"summary": summary, "frames": audits})


if __name__ == "__main__":
    main()
