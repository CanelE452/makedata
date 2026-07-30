"""Top-down stress test for camera-dynamic 0123 (compute_perm_v4).

Purpose (fixed): prove with DATA whether the new 0123 tagging (compute_perm_v4
normal-facing FRONT + front_cos grazing gate) holds up at HIGH camera elevation
(near-vertical top-down).  Two questions answered numerically:
  (1) Does the grazing/margin gate AUTO-REJECT ambiguous near-vertical top views?
      -> bin every evaluated candidate by reject-reason x elevation bucket.
  (2) Of the frames that PASS, are the high-elevation ones still correct
      (0123 a real rectangle, FRONT = camera-facing side, connector-cross 0)?

Differences vs gen_preview10.py (which is LEFT UNTOUCHED):
  - ELEV range widened 20deg..88deg (includes near-vertical top-down).
  - front_cos>=0.40 and facing_margin>=0.60 gates KEPT (ambiguity rejection).
  - EVERY candidate pose is logged (reason + elevation), not just the last retry.
  - N target = 24, outputs to data/pallet/_test_topview/ (does NOT touch _preview10).

Run (headless):
    blender -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
        --python scripts/data_prep/blender/gen_topview_test.py
"""

import json
import math
import os
import sys

import bpy
import mathutils
import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import blender_config as cfg
# scene_1/2/3 only (Pallet_0 = scene.usd excluded), same as preview10.
cfg.PALLET_WEIGHTS = [0.0, 0.3333, 0.3333, 0.3333]
cfg.PALLET_PLACEMENT_X_RANGE = (-11.0, -7.0)
cfg.PALLET_PLACEMENT_Y_RANGE = (-11.0, -4.0)

from blender_config import (
    IMAGE_WIDTH, IMAGE_HEIGHT, K, ORIENTATION_OVERRIDES, CORNER_COLORS_RGB,
    PALLET_SOURCE_ASSETS, VISIBLE_MIN_FRACTION, CAMERA_VIEW_MODES,
    MIN_PROJECTED_AREA_RATIO, MAX_FRAME_RETRIES,
)
from blender_math import (
    rotation_matrix_to_quat_xyzw, rotation_matrix_to_euler_deg,
    build_view_matrix, compute_perm_v4,
)
from pallet_geometry import (
    get_pallet_geometry, snap_object_to_ground, object_bottom_z_world,
)
import randomizers
from randomizers import (
    get_obj, setup_render, randomize_camera, randomize_boxes,
    randomize_distractors, randomize_hdri, randomize_background,
    choose_next_pallet_index, choose_camera_mode_name,
    randomize_pallet_appearance, randomize_pallet, check_raycast_visibility,
)

randomizers.PALLET_WEIGHTS = cfg.PALLET_WEIGHTS
randomizers.PALLET_PLACEMENT_X_RANGE = cfg.PALLET_PLACEMENT_X_RANGE
randomizers.PALLET_PLACEMENT_Y_RANGE = cfg.PALLET_PLACEMENT_Y_RANGE

cfg.BACKGROUND_WEIGHTS = {"industrial": 1.0, "parking_lot": 0.0}
randomizers.BACKGROUND_WEIGHTS = cfg.BACKGROUND_WEIGHTS

N_SAMPLES = 24

# --- WIDENED elevation band to include near-vertical top-down (the test) -------
ELEV_MIN_DEG = 20.0
ELEV_MAX_DEG = 88.0
CAM_DIST_RANGE = (1.6, 4.5)

# Gates KEPT identical to gen_preview10 so we measure their behaviour at top-down.
# facing_margin = best-minus-second-best side-face facing cos (compute_perm_v4).
# Retuned 0.60->0.15 (2026-07-03) after the FRONT-selection fix changed its definition
# (front/rear-opposite -> best/second adjacent). 0.15 rejects only ~45deg corner-on
# ambiguity (id0-unstable margin max 0.080); grazing handled by FRONT_FACING_COS_MIN.
FACING_MARGIN_MIN = 6.0  # DEGREES since 2026-07-24 azimuth perm (was 0.15 cos-diff; 6deg reproduces old ~+/-6deg corner reject band). NOTE: comment above describes the OLD cos-diff semantics.
FRONT_FACING_COS_MIN = 0.40

# Bias sampling toward HIGH elevation so we actually exercise the top-down regime
# (uniform 20..88 still gives plenty of >60/>70 candidates; we also report the
# distribution of the candidate elevations so the bias is transparent).
def sample_elev_deg():
    import random as _r
    return _r.uniform(ELEV_MIN_DEG, ELEV_MAX_DEG)


def sample_camera_elev(geom, elev_deg):
    import random as _r
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    az = _r.uniform(0.0, 2.0 * math.pi)
    elev = math.radians(elev_deg)
    dist = _r.uniform(*CAM_DIST_RANGE)
    cam = cen + dist * np.array([
        math.cos(elev) * math.cos(az),
        math.cos(elev) * math.sin(az),
        math.sin(elev),
    ], dtype=np.float64)
    cam_pos = (float(cam[0]), float(cam[1]), float(cam[2]))
    look_at = (float(cen[0]), float(cen[1]), float(cen[2]))
    cam_obj = bpy.context.scene.camera
    if cam_obj is not None:
        cam_obj.location = cam_pos
        direction = mathutils.Vector(look_at) - mathutils.Vector(cam_pos)
        cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return cam_pos, look_at, math.degrees(elev), math.degrees(az)


CUBOID_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)]
CONNECTOR_EDGES = [(0, 4), (1, 5), (2, 6), (3, 7)]


def _seg_proper_intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def count_edge_crossings(uv8):
    conn = 0
    for i in range(len(CONNECTOR_EDGES)):
        for j in range(i + 1, len(CONNECTOR_EDGES)):
            a, b = CONNECTOR_EDGES[i]
            c, d = CONNECTOR_EDGES[j]
            if _seg_proper_intersect(uv8[a], uv8[b], uv8[c], uv8[d]):
                conn += 1
    total = 0
    for i in range(len(CUBOID_EDGES)):
        for j in range(i + 1, len(CUBOID_EDGES)):
            a, b = CUBOID_EDGES[i]
            c, d = CUBOID_EDGES[j]
            if len({a, b, c, d}) < 4:
                continue
            if _seg_proper_intersect(uv8[a], uv8[b], uv8[c], uv8[d]):
                total += 1
    return conn, total


def is_rectangleish(uv8_v4):
    """Quantify whether the projected 0123 FRONT quad still looks like a rectangle.
    Returns (ok, area_px, min_side_px, aspect). Degenerate (grazing) FRONT collapses
    to a thin sliver -> tiny area / tiny min side / aspect ~ 0."""
    q = np.asarray(uv8_v4[[0, 1, 2, 3]], dtype=np.float64)
    area = 0.5 * abs(np.dot(q[:, 0], np.roll(q[:, 1], -1)) -
                     np.dot(q[:, 1], np.roll(q[:, 0], -1)))
    sides = [np.linalg.norm(q[(i + 1) % 4] - q[i]) for i in range(4)]
    e_top = np.linalg.norm(uv8_v4[1] - uv8_v4[0])
    e_bot = np.linalg.norm(uv8_v4[2] - uv8_v4[3])
    e_left = np.linalg.norm(uv8_v4[3] - uv8_v4[0])
    e_right = np.linalg.norm(uv8_v4[2] - uv8_v4[1])
    w_mean = (e_top + e_bot) / 2.0
    h_mean = (e_left + e_right) / 2.0
    aspect = float(min(w_mean, h_mean) / max(max(w_mean, h_mean), 1e-9))
    min_side = float(min(sides))
    ok = bool(area >= 80.0 and min_side >= 6.0 and aspect >= 0.10)
    return ok, float(area), min_side, aspect


MIN_AREA_FLOOR = 0.045
MIN_RAYCAST_VIS = 0.55


def _pallet_silhouette_points(geom):
    C = geom["corners_world"]
    cen = geom["centroid_world"]
    bottom = C[[2, 3, 6, 7]]
    pts = [*bottom]
    for a, b in [(2, 3), (3, 7), (7, 6), (6, 2)]:
        pts.append((C[a] + C[b]) / 2.0)
    base_center = bottom.mean(axis=0)
    pts.append(base_center)
    pts.append(np.array([cen[0], cen[1], base_center[2]]))
    return np.array(pts, dtype=np.float64)


RATIO_PROB = 0.40
RATIO_RANGE = (0.88, 1.12)

OUT_BASE = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_test_topview")
IMG_DIR = os.path.join(OUT_BASE, "images")
JSON_DIR = os.path.join(OUT_BASE, "json")
OV_DIR = os.path.join(OUT_BASE, "overlay")
CROP_DIR = os.path.join(OUT_BASE, "_crop")


# --- elevation bucketing for the gate-behaviour statistics ----------------------
ELEV_BUCKETS = [(20, 40), (40, 60), (60, 70), (70, 80), (80, 88.0001)]


def elev_bucket(e):
    for lo, hi in ELEV_BUCKETS:
        if lo <= e < hi:
            return f"{lo}-{int(hi)}"
    return "oob"


# reason categories (coarse) for the reject histogram
REASONS = ["area/vis", "raycast", "front_cos(grazing)", "facing_margin(ambig)",
           "connector_cross", "PASS"]


def save_crop(render_path, crop_path, uv, pad_frac=0.18, upscale=2):
    from PIL import Image
    img = Image.open(render_path).convert("RGB")
    W, H = img.size
    pts = np.asarray(uv[:8], dtype=np.float64)
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    x0 -= bw * pad_frac; x1 += bw * pad_frac
    y0 -= bh * pad_frac; y1 += bh * pad_frac
    x0 = int(max(0, x0)); y0 = int(max(0, y0))
    x1 = int(min(W, x1)); y1 = int(min(H, y1))
    if x1 <= x0 or y1 <= y0:
        return
    crop = img.crop((x0, y0, x1, y1))
    crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    crop.save(crop_path)


def apply_ratio_randomization(pallet_obj):
    factors = np.array([
        np.random.uniform(*RATIO_RANGE),
        np.random.uniform(*RATIO_RANGE),
        np.random.uniform(*RATIO_RANGE),
    ], dtype=np.float64)
    base = np.array(pallet_obj.scale, dtype=np.float64)
    pallet_obj.scale = tuple(base * factors)
    bpy.context.view_layer.update()
    snap_object_to_ground(pallet_obj, ground_z=0.0)
    bpy.context.view_layer.update()
    return factors


def compute_annotation_v4(pallet_name, pallet_obj, cam_pos, look_at):
    bpy.context.view_layer.update()
    geom = get_pallet_geometry(pallet_name, pallet_obj, ORIENTATION_OVERRIDES)
    if geom is None:
        return None

    corners_world = geom["corners_world"]
    centroid_world = geom["centroid_world"]

    R_w2c, t_w2c = build_view_matrix(cam_pos, look_at, up=(0, 0, 1))
    pts_cam = (R_w2c @ corners_world.T).T + t_w2c
    proj = (K @ pts_cam.T).T
    uv8 = proj[:, :2] / proj[:, 2:3]

    perm, facing_margin, front_cos = compute_perm_v4(corners_world, uv8,
                                                     cam_pos=cam_pos,
                                                     return_margin=True)
    corners_v4 = corners_world[perm]
    uv8_v4 = uv8[perm]

    cent_cam = R_w2c @ centroid_world + t_w2c
    cent_uv = (K @ cent_cam)[:2] / cent_cam[2]

    uv = np.vstack([uv8_v4, cent_uv[np.newaxis, :]])
    points_3d = np.vstack([corners_v4, centroid_world[np.newaxis, :]])

    in_frame = ((uv[:, 0] >= 0) & (uv[:, 0] < IMAGE_WIDTH) &
                (uv[:, 1] >= 0) & (uv[:, 1] < IMAGE_HEIGHT))
    visibility = float(in_frame.sum()) / 9.0

    clipped = np.clip(uv8_v4, [0, 0], [IMAGE_WIDTH, IMAGE_HEIGHT])
    area_ratio = ((clipped[:, 0].max() - clipped[:, 0].min()) *
                  (clipped[:, 1].max() - clipped[:, 1].min())) / (IMAGE_WIDTH * IMAGE_HEIGHT)

    t_obj_cam = R_w2c @ centroid_world + t_w2c
    R_obj_cam = R_w2c @ geom["r_for_pose"]
    pose_4x4 = np.eye(4)
    pose_4x4[:3, :3] = R_obj_cam
    pose_4x4[:3, 3] = t_obj_cam
    pitch, yaw, roll = rotation_matrix_to_euler_deg(R_obj_cam)

    width_m = float(np.linalg.norm(corners_v4[1] - corners_v4[0]))
    height_m = float(np.linalg.norm(corners_v4[3] - corners_v4[0]))
    depth_m = float(np.linalg.norm(corners_v4[4] - corners_v4[0]))

    rect_ok, rect_area, rect_minside, front_aspect = is_rectangleish(uv8_v4)

    data = {
        "camera_data": {
            "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT,
            "intrinsics": {"fx": float(K[0, 0]), "fy": float(K[1, 1]),
                           "cx": float(K[0, 2]), "cy": float(K[1, 2])},
            "location_worldframe": [float(v) for v in cam_pos],
        },
        "objects": [{
            "class": "pallet", "name": pallet_name,
            "source_asset": PALLET_SOURCE_ASSETS.get(pallet_name, pallet_name),
            "keypoint_convention": "camera_dynamic_0123_v4",
            "visibility": visibility,
            "location": [float(v) for v in t_obj_cam],
            "quaternion_xyzw": rotation_matrix_to_quat_xyzw(R_obj_cam),
            "euler_angles": {"pitch": pitch, "yaw": yaw, "roll": roll},
            "pose_transform": pose_4x4.tolist(),
            "projected_cuboid_centroid": [float(uv[8, 0]), float(uv[8, 1])],
            "projected_cuboid": [[float(uv[k, 0]), float(uv[k, 1])] for k in range(8)],
            "cuboid": [[float(points_3d[k, j]) for j in range(3)] for k in range(8)],
            "perm_v4": [int(p) for p in perm],
            "facing_margin": float(facing_margin),
            "front_facing_cos": float(front_cos),
            "front_image_aspect": front_aspect,
            "front_rect_ok": bool(rect_ok),
            "front_rect_area_px": float(rect_area),
            "front_rect_min_side_px": float(rect_minside),
            "dimensions_m": {"width": width_m, "height": height_m, "depth": depth_m},
        }],
    }
    return (data, uv, visibility, (pitch, yaw, roll), area_ratio, geom,
            float(facing_margin), float(front_cos), front_aspect,
            rect_ok, rect_area, rect_minside)


def draw_overlay(render_path, overlay_path, uv, info):
    from PIL import Image, ImageDraw
    img = Image.open(render_path).convert("RGBA")
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)

    def poly(idxs, color):
        pts = [(int(uv[i, 0]), int(uv[i, 1])) for i in idxs]
        fd.polygon(pts, fill=color)

    poly([0, 1, 2, 3], (0, 255, 0, 55))
    poly([0, 1, 5, 4], (0, 200, 255, 35))
    img = Image.alpha_composite(img, face)
    draw = ImageDraw.Draw(img)

    edges = [(0, 1), (1, 2), (2, 3), (3, 0),
             (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    for i, j in edges:
        draw.line([(int(uv[i, 0]), int(uv[i, 1])), (int(uv[j, 0]), int(uv[j, 1]))],
                  fill=(0, 255, 0, 220), width=2)

    for i in range(8):
        cx, cy = int(uv[i, 0]), int(uv[i, 1])
        r = 7
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=CORNER_COLORS_RGB[i] + (255,), outline=(0, 0, 0, 255))
        draw.text((cx + 9, cy - 10), str(i), fill=(255, 255, 0, 255))
    cx, cy = int(uv[8, 0]), int(uv[8, 1])
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(255, 255, 255, 220), outline=(0, 0, 0, 255))
    draw.text((cx + 8, cy - 10), "8", fill=(255, 255, 255, 255))

    lines = [
        f"Frame {info['frame']:02d}  {info['scene']}",
        f"ratio_rand: {info['ratio_str']}",
        f"vis {info['vis']:.0%}  area {info['area']:.1%}  ray {info.get('ray', 0):.0%}",
        f"elev {info.get('elev', 0):.1f}deg  azim {info.get('azim', 0):.1f}deg",
        f"FRONT facing cos {info.get('front_cos', 0):.3f} (>=0.40 not grazing)",
        f"facing margin {info.get('fmargin', 0):.3f} (>=0.60 stable)  aspect {info.get('aspect', 0):.2f}",
        f"FRONT=0123 cam-near? {info.get('front_ok', '?')}  rect_ok {info.get('rect_ok','?')}",
        f"edge connector-cross: {info.get('conn_x', 0)} (0=ok wireframe)",
    ]
    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    bd.rectangle([(3, 3), (3 + 330, 3 + 14 * len(lines) + 6)], fill=(0, 0, 0, 180))
    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)
    y = 6
    for ln in lines:
        draw.text((8, y), ln, fill=(0, 255, 255, 255))
        y += 14
    img.convert("RGB").save(overlay_path)


def main():
    np.random.seed(20260615)
    import random
    random.seed(20260615)
    for d in (IMG_DIR, JSON_DIR, OV_DIR, CROP_DIR):
        os.makedirs(d, exist_ok=True)

    setup_render()
    scene = bpy.context.scene

    _DROP = ("mall_parking_lot", "factory_yard")
    _hdris = randomizers._collect_hdri_images()
    _keep = [im for im in _hdris if not any(d in im.name.lower() for d in _DROP)]
    randomizers._hdri_cache[:] = _keep
    print(f"  [HDRI] preview pool: {[im.name for im in _keep]}")

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass

    saved = 0
    attempts = 0          # number of distinct frame-acceptance attempts
    candidates = 0        # number of camera poses evaluated (incl. all retries)
    scene_count = {"scene_1.usd": 0, "scene_2.usd": 0, "scene_3.usd": 0}
    ratio_applied_total = 0

    # stats[reason][bucket] = count  over ALL evaluated candidates
    stats = {r: {elev_bucket((lo + hi) / 2): 0 for lo, hi in ELEV_BUCKETS}
             for r in REASONS}
    # also keep per-candidate rows for forensic dump
    cand_rows = []
    pass_rows = []

    MAX_TOTAL_ATTEMPTS = N_SAMPLES * 60
    while saved < N_SAMPLES and attempts < MAX_TOTAL_ATTEMPTS:
        attempts += 1
        target_idx = choose_next_pallet_index()
        if target_idx < 0:
            print("[ERR] no valid pallet")
            break
        cam_mode = choose_camera_mode_name()
        mode_cfg = CAMERA_VIEW_MODES.get(cam_mode, {})
        min_area = mode_cfg.get("min_area_ratio", MIN_PROJECTED_AREA_RATIO)

        accepted = False
        last_pack = None
        for _ in range(MAX_FRAME_RETRIES):
            candidates += 1
            bg = randomize_background()
            pallet_name, _ = randomize_pallet(chosen_idx=target_idx)
            if pallet_name is None:
                break
            pobj = get_obj(pallet_name)

            if np.random.rand() < RATIO_PROB:
                factors = apply_ratio_randomization(pobj)
                ratio_applied = True
            else:
                factors = np.array([1.0, 1.0, 1.0])
                ratio_applied = False

            geom = get_pallet_geometry(pallet_name, pobj, ORIENTATION_OVERRIDES)
            if geom is None:
                continue
            pallet_pos = tuple(geom["centroid_world"])
            randomize_pallet_appearance(pobj, pallet_name)

            elev_target = sample_elev_deg()
            cam_pos, look_at, elev_deg, azim_deg = sample_camera_elev(geom, elev_target)
            if cam_pos is None:
                break
            bkt = elev_bucket(elev_deg)
            randomize_boxes(pobj, pallet_name, occlusion_target="light", target_box_count=2)
            randomize_distractors(pallet_pos, cam_pos, prefer_occlusion=False)
            randomize_hdri()
            bpy.context.view_layer.update()

            res = compute_annotation_v4(pallet_name, pobj, cam_pos, look_at)
            if res is None:
                continue
            (ann, uv, vis, rot, area, geom, facing_margin, front_cos,
             front_aspect, rect_ok, rect_area, rect_minside) = res

            conn_x, total_x = count_edge_crossings(uv[:8])

            # classify this candidate (gates applied in the SAME order as preview10)
            area_gate = max(min_area, MIN_AREA_FLOOR)
            sample_pts = _pallet_silhouette_points(geom)
            ray_vis = check_raycast_visibility(pobj, cam_pos, sample_pts)

            if vis < VISIBLE_MIN_FRACTION or area < area_gate:
                reason = "area/vis"
            elif ray_vis < MIN_RAYCAST_VIS:
                reason = "raycast"
            elif not (front_cos >= FRONT_FACING_COS_MIN):
                reason = "front_cos(grazing)"
            elif not (facing_margin >= FACING_MARGIN_MIN):
                reason = "facing_margin(ambig)"
            elif conn_x > 0:
                reason = "connector_cross"
            else:
                reason = "PASS"

            stats[reason][bkt] = stats[reason].get(bkt, 0) + 1
            cand_rows.append((elev_deg, azim_deg, front_cos, facing_margin,
                              conn_x, reason))

            if reason != "PASS":
                last_pack = (reason, elev_deg)
                continue

            # PASS: stash everything needed to render
            ann["objects"][0]["raycast_visibility"] = float(ray_vis)
            ann["objects"][0]["edge_connector_crossings"] = int(conn_x)
            ann["objects"][0]["edge_total_crossings"] = int(total_x)
            ann["objects"][0]["camera_elevation_deg"] = float(elev_deg)
            ann["objects"][0]["camera_azimuth_deg"] = float(azim_deg)
            accepted = True
            pack = dict(ann=ann, uv=uv, vis=vis, area=area, ray_vis=ray_vis,
                        cam_pos=cam_pos, pallet_name=pallet_name, bg=bg,
                        cam_mode=cam_mode, factors=factors,
                        ratio_applied=ratio_applied, elev_deg=elev_deg,
                        azim_deg=azim_deg, facing_margin=facing_margin,
                        front_cos=front_cos, front_aspect=front_aspect,
                        conn_x=conn_x, total_x=total_x, rect_ok=rect_ok,
                        rect_area=rect_area, rect_minside=rect_minside)
            break

        if not accepted:
            if last_pack:
                print(f"[REJECT] attempt {attempts}: {last_pack[0]} @ elev {last_pack[1]:.1f}")
            continue

        p = pack
        src = PALLET_SOURCE_ASSETS.get(p["pallet_name"], p["pallet_name"])
        frame = saved
        render_path = os.path.join(IMG_DIR, f"{frame:06d}.png")
        scene.render.filepath = render_path
        bpy.ops.render.render(write_still=True)

        cub = np.array(p["ann"]["objects"][0]["cuboid"], dtype=np.float64)
        cam_np = np.array(p["cam_pos"], dtype=np.float64)
        d_front = np.linalg.norm(cub[[0, 1, 2, 3]].mean(axis=0) - cam_np)
        d_rear = np.linalg.norm(cub[[4, 5, 6, 7]].mean(axis=0) - cam_np)
        front_ok = bool(d_front <= d_rear)

        ann = p["ann"]
        ann["objects"][0]["ratio_randomized"] = bool(p["ratio_applied"])
        ann["objects"][0]["ratio_factors"] = [float(f) for f in p["factors"]]
        ann["objects"][0]["front_is_camera_near"] = front_ok
        ann["camera_data"]["background_asset"] = p["bg"]
        ann["camera_data"]["camera_mode"] = p["cam_mode"]
        with open(os.path.join(JSON_DIR, f"{frame:06d}.json"), "w") as f:
            json.dump(ann, f, indent=2)

        ratio_str = ("YES " + ",".join(f"{x:.2f}" for x in p["factors"])) if p["ratio_applied"] else "no"
        ov_path = os.path.join(OV_DIR, f"overlay_{frame:06d}.png")
        draw_overlay(render_path, ov_path, p["uv"],
                     {"frame": frame, "scene": src, "ratio_str": ratio_str,
                      "vis": p["vis"], "area": p["area"], "ray": p["ray_vis"],
                      "front_ok": "YES" if front_ok else "NO", "conn_x": p["conn_x"],
                      "elev": p["elev_deg"], "azim": p["azim_deg"],
                      "fmargin": p["facing_margin"], "front_cos": p["front_cos"],
                      "aspect": p["front_aspect"], "rect_ok": p["rect_ok"]})
        save_crop(ov_path, os.path.join(CROP_DIR, f"crop_{frame:06d}.png"), p["uv"])

        pass_rows.append((frame, src, p["elev_deg"], p["azim_deg"], p["front_cos"],
                          p["facing_margin"], p["conn_x"], p["rect_ok"],
                          p["rect_area"], p["rect_minside"], front_ok))

        scene_count[src] = scene_count.get(src, 0) + 1
        ratio_applied_total += int(p["ratio_applied"])
        print(f"[OK] frame {frame:02d} {src} elev={p['elev_deg']:.1f} azim={p['azim_deg']:.1f} "
              f"front_cos={p['front_cos']:.3f} fmargin={p['facing_margin']:.3f} "
              f"conn_x={p['conn_x']} rect_ok={p['rect_ok']} front_near={front_ok} "
              f"perm={ann['objects'][0]['perm_v4']}")
        saved += 1

    # ---- dump statistics ------------------------------------------------------
    print("\n=== GATE BEHAVIOUR (all evaluated candidates) ===")
    print(f"candidates_evaluated={candidates} attempts={attempts} saved={saved}/{N_SAMPLES}")
    buckets = [elev_bucket((lo + hi) / 2) for lo, hi in ELEV_BUCKETS]
    header = "reason".ljust(22) + "".join(b.rjust(9) for b in buckets) + "    total"
    print(header)
    for r in REASONS:
        row = r.ljust(22)
        tot = 0
        for b in buckets:
            c = stats[r].get(b, 0)
            tot += c
            row += str(c).rjust(9)
        row += str(tot).rjust(9)
        print(row)
    # column totals (candidates per bucket)
    coltot = "ALL_CANDIDATES".ljust(22)
    grand = 0
    for b in buckets:
        c = sum(stats[r].get(b, 0) for r in REASONS)
        grand += c
        coltot += str(c).rjust(9)
    coltot += str(grand).rjust(9)
    print(coltot)

    print("\n=== PASS frames ===")
    print("frame scene        elev   azim  front_cos fmargin conn_x rect_ok rect_area minside front_near")
    for row in pass_rows:
        (fr, sc, el, az, fc, fm, cx, rok, ra, ms, fn) = row
        print(f"{fr:5d} {sc:12s} {el:5.1f} {az:6.1f} {fc:9.3f} {fm:7.3f} "
              f"{cx:6d} {str(rok):7s} {ra:9.0f} {ms:7.1f} {str(fn)}")

    print(f"\nscene dist: {scene_count}")
    print(f"ratio randomized: {ratio_applied_total}/{saved}")

    # machine-readable summary for the agent to read back
    summary = {
        "candidates_evaluated": candidates,
        "attempts": attempts,
        "saved": saved,
        "buckets": buckets,
        "stats": stats,
        "pass_rows": [
            {"frame": fr, "scene": sc, "elev": el, "azim": az, "front_cos": fc,
             "facing_margin": fm, "conn_x": cx, "rect_ok": bool(rok),
             "rect_area_px": ra, "rect_min_side_px": ms, "front_near": bool(fn)}
            for (fr, sc, el, az, fc, fm, cx, rok, ra, ms, fn) in pass_rows
        ],
        "scene_dist": scene_count,
        "ratio_randomized": ratio_applied_total,
    }
    with open(os.path.join(OUT_BASE, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[SUMMARY] written {os.path.join(OUT_BASE, '_summary.json')}")
    print(f"=== DONE {saved}/{N_SAMPLES} ===")


if __name__ == "__main__":
    main()
