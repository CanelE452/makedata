"""10-sample preview generator: scene_1/2/3 only, anisotropic ratio randomization,
camera-dynamic 0123 keypoint IDs (compute_perm_v4).

Run (headless):
    blender -b data/pallet/blender_scene/synth_data_scene.blend \
        --python scripts/data_prep/blender/gen_preview10.py
Outputs:
    data/pallet/_preview10/{images,json,overlay}/
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
# ---- override pallet selection: scene_1/2/3 only (Pallet_0 = scene.usd excluded) ----
cfg.PALLET_WEIGHTS = [0.0, 0.3333, 0.3333, 0.3333]
# Keep the pallet away from the industrial floor boundary so top-down views never
# look past the floor edge into the void (which renders as the magenta world).
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

# keep randomizers' view of the weights/placement in sync (randomizers imported
# these as module-level names, so patch them directly too)
randomizers.PALLET_WEIGHTS = cfg.PALLET_WEIGHTS
randomizers.PALLET_PLACEMENT_X_RANGE = cfg.PALLET_PLACEMENT_X_RANGE
randomizers.PALLET_PLACEMENT_Y_RANGE = cfg.PALLET_PLACEMENT_Y_RANGE

# prefer the full industrial scene; the parking_lot glTF is a thin ground patch
# that exposes large sky areas -> avoid here so previews stay realistic.
cfg.BACKGROUND_WEIGHTS = {"industrial": 1.0, "parking_lot": 0.0}
randomizers.BACKGROUND_WEIGHTS = cfg.BACKGROUND_WEIGHTS

N_SAMPLES = 10

# --- camera elevation constraint (problem 1: kill near-vertical top-down) --------
# Elevation = angle of the camera above the horizontal plane through the look-at
# point, measured from the look-at point:  elev = atan2(cam_z - look_z, horiz_dist).
#   0deg  = camera level with the pallet (grazing side view)
#   90deg = straight-down top-down (BANNED: flat-pallet side faces become
#           near-symmetric -> FRONT/0123 flips between frames).
# We sample an oblique band so ONE side face always clearly faces the camera.
ELEV_MIN_DEG = 25.0
ELEV_MAX_DEG = 65.0
CAM_DIST_RANGE = (1.6, 4.5)     # horizontal-ish look distance (m) to the pallet
# FRONT stability gate: facing margin = best-minus-second-best side-face facing cos
# (compute_perm_v4 return_margin). Below this the two top side faces tie and the
# FRONT(0123) axis assignment is ambiguous (~45deg corner-on view).
# Retuned 0.60->0.15 (2026-07-03): the FRONT-selection fix changed facing_margin's
# definition from front/rear-opposite diff to best/second (adjacent) diff, so the old
# scale no longer applies. 0.15 catches 100% of the id0-unstable band (unstable margin
# max 0.080 on a fine sweep) with ~2x buffer, rejecting only a ~+/-6deg az band per
# corner. Grazing (edge-on) is now handled solely by FRONT_FACING_COS_MIN below.
FACING_MARGIN_MIN = 6.0  # DEGREES since 2026-07-24 azimuth perm (was 0.15 cos-diff; 6deg reproduces old ~+/-6deg corner reject band). NOTE: comment above describes the OLD cos-diff semantics.
# FRONT grazing gate (primary, problem this revision fixes): the FRONT face itself
# must clearly face the camera, NOT be seen edge-on.  front_cos = dot(n_front,
# unit(cam - front_center)).  1=head-on, 0=edge-on(grazing -> FRONT projects to a
# thin slanted line, 0123 stops being a rectangle), <0=we are looking at its back.
#   [확인] measured on the previous 10 frames:
#     grazing frame02 = -0.082  (the exact failure: margin 0.418 passed but FRONT
#                                was edge-on; 0/3 stacked into a left vertical line)
#     thin    frame03 =  0.264  (FRONT a thin band, borderline)
#     edgey   frame07 =  0.381
#     OK      frame00 =  0.433 ... frame08 = 0.751  (clear 0123 rectangles)
#   Threshold 0.40 (~66deg off head-on) sits in the gap above the grazing/thin
#   cluster (<=0.381) and below the clean rectangles (>=0.433): kills frame02/03/07,
#   keeps every frame whose FRONT projected as a real rectangle.
FRONT_FACING_COS_MIN = 0.40


def sample_camera_elev(geom):
    """Sample a camera pose at a constrained elevation, looking at the pallet centroid.

    [확인] elevation 정의: look-at = pallet centroid (cen).  We draw spherical
    coords (azimuth in [0,2pi), elevation in [ELEV_MIN,ELEV_MAX]) and a slant range
    `dist`, then place
        cam = cen + dist * (cos(elev)*cos(az), cos(elev)*sin(az), sin(elev)).
    cam_z - cen_z = dist*sin(elev) > 0 and horiz = dist*cos(elev), so
    atan2(cam_z-cen_z, horiz) == elev exactly -> elevation is the literal angle
    above the pallet's horizontal plane.  azimuth is uniform on the full circle so
    FRONT rotates through all four side faces across frames.  look_at is the
    centroid (not the top), so the optical axis points at the pallet body.
    Returns (cam_pos, look_at, elev_deg, azimuth_deg).
    """
    import random as _r
    cen = np.asarray(geom["centroid_world"], dtype=np.float64)
    az = _r.uniform(0.0, 2.0 * math.pi)
    elev = math.radians(_r.uniform(ELEV_MIN_DEG, ELEV_MAX_DEG))
    dist = _r.uniform(*CAM_DIST_RANGE)
    cam = cen + dist * np.array([
        math.cos(elev) * math.cos(az),
        math.cos(elev) * math.sin(az),
        math.sin(elev),
    ], dtype=np.float64)
    cam_pos = (float(cam[0]), float(cam[1]), float(cam[2]))
    look_at = (float(cen[0]), float(cen[1]), float(cen[2]))
    # orient the Blender camera object to look at the centroid
    cam_obj = bpy.context.scene.camera
    if cam_obj is not None:
        cam_obj.location = cam_pos
        direction = mathutils.Vector(look_at) - mathutils.Vector(cam_pos)
        cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return cam_pos, look_at, math.degrees(elev), math.degrees(az)

# --- cuboid wireframe self-intersection oracle ---------------------------------
# A correctly-labeled cuboid drawn as a wireframe has NO connector(depth)-edge that
# crosses another connector edge.  Mislabeled rear corners (left/right mirrored vs
# the front face) make the four 0-4,1-5,2-6,3-7 connectors cross in an X -> a wrong
# perm.  We count connector-connector crossings (the robust signal); near edge-on
# flat pallets graze top/bottom edges harmlessly, so we report those separately.
CUBOID_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0),   # front
                (4, 5), (5, 6), (6, 7), (7, 4),   # rear
                (0, 4), (1, 5), (2, 6), (3, 7)]   # connectors
CONNECTOR_EDGES = [(0, 4), (1, 5), (2, 6), (3, 7)]


def _seg_proper_intersect(p1, p2, p3, p4):
    """True iff segments p1p2 and p3p4 properly cross (no shared endpoint)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def count_edge_crossings(uv8):
    """Return (connector_crossings, total_crossings) for the 12 cuboid edges.
    connector_crossings>0 => the 0/4,1/5,2/6,3/7 depth labeling is wrong (X-cross)."""
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

# --- visibility gate (problem 3): reject frames where the pallet is too small or
#     too occluded by EXTERNAL objects (fences/walls/distractors) to be inferable.
#     Cargo boxes sitting on the pallet top are legitimate, so raycast samples the
#     pallet base + side faces (not the box-covered top) to measure the silhouette. ---
MIN_AREA_FLOOR = 0.045         # projected bbox must cover >= 4.5% of the image
MIN_RAYCAST_VIS = 0.55         # >= 55% of base/side sample points unoccluded


def _pallet_silhouette_points(geom):
    """Sample world points on the pallet base + lower side edges for raycasting.
    Avoids the top face, which cargo boxes legitimately cover."""
    C = geom["corners_world"]
    cen = geom["centroid_world"]
    bottom = C[[2, 3, 6, 7]]                 # 4 bottom corners (canonical order)
    pts = [*bottom]
    # bottom edge midpoints
    for a, b in [(2, 3), (3, 7), (7, 6), (6, 2)]:
        pts.append((C[a] + C[b]) / 2.0)
    # a point at the pallet centroid height projected to the base center
    base_center = bottom.mean(axis=0)
    pts.append(base_center)
    pts.append(np.array([cen[0], cen[1], base_center[2]]))
    return np.array(pts, dtype=np.float64)
RATIO_PROB = 0.40           # 40% of frames get anisotropic ratio randomization
RATIO_RANGE = (0.88, 1.12)  # +/-12% per axis

OUT_BASE = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_preview10")
IMG_DIR = os.path.join(OUT_BASE, "images")
JSON_DIR = os.path.join(OUT_BASE, "json")
OV_DIR = os.path.join(OUT_BASE, "overlay")
CROP_DIR = os.path.join(OUT_BASE, "_crop")


def save_crop(render_path, crop_path, uv, pad_frac=0.18, upscale=2):
    """Tight crop around the pallet's projected cuboid, then upscale for eyeballing.

    uv : (9,2) projected keypoints (8 corners + centroid)."""
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
    """Multiply per-axis factors onto current (uniform) object scale, re-ground.
    GT corners are recomputed from the deformed mesh afterwards, so they stay exact."""
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
    """get_pallet_geometry -> project 9 pts -> reorder by compute_perm_v4."""
    bpy.context.view_layer.update()
    geom = get_pallet_geometry(pallet_name, pallet_obj, ORIENTATION_OVERRIDES)
    if geom is None:
        return None

    corners_world = geom["corners_world"]           # (8,3) object-frame canonical order
    centroid_world = geom["centroid_world"]

    R_w2c, t_w2c = build_view_matrix(cam_pos, look_at, up=(0, 0, 1))
    pts_cam = (R_w2c @ corners_world.T).T + t_w2c
    proj = (K @ pts_cam.T).T
    uv8 = proj[:, :2] / proj[:, 2:3]

    # --- camera-dynamic 0123 ID reassignment (+ FRONT facing margin / front_cos) ---
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

    # dims from v4 corners: 0-1 = front-top width, 0-3 = front vertical (height),
    # 0..front->rear depth = corner0 to its rear partner (id4)
    width_m = float(np.linalg.norm(corners_v4[1] - corners_v4[0]))
    height_m = float(np.linalg.norm(corners_v4[3] - corners_v4[0]))
    depth_m = float(np.linalg.norm(corners_v4[4] - corners_v4[0]))

    # FRONT face image aspect (short/long) as a secondary edge-on guard:
    # mean top/bottom edge length vs mean left/right edge length of the 0123 quad.
    e_top = np.linalg.norm(uv8_v4[1] - uv8_v4[0])
    e_bot = np.linalg.norm(uv8_v4[2] - uv8_v4[3])
    e_left = np.linalg.norm(uv8_v4[3] - uv8_v4[0])
    e_right = np.linalg.norm(uv8_v4[2] - uv8_v4[1])
    w_mean = (e_top + e_bot) / 2.0
    h_mean = (e_left + e_right) / 2.0
    front_aspect = float(min(w_mean, h_mean) / max(max(w_mean, h_mean), 1e-9))

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
            "dimensions_m": {"width": width_m, "height": height_m, "depth": depth_m},
        }],
    }
    return (data, uv, visibility, (pitch, yaw, roll), area_ratio, geom,
            float(facing_margin), float(front_cos), front_aspect)


def draw_overlay(render_path, overlay_path, uv, info):
    from PIL import Image, ImageDraw
    img = Image.open(render_path).convert("RGBA")
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)

    def poly(idxs, color):
        pts = [(int(uv[i, 0]), int(uv[i, 1])) for i in idxs]
        fd.polygon(pts, fill=color)

    poly([0, 1, 2, 3], (0, 255, 0, 55))      # FRONT face (camera-near, big)
    poly([0, 1, 5, 4], (0, 200, 255, 35))    # TOP face
    img = Image.alpha_composite(img, face)
    draw = ImageDraw.Draw(img)

    edges = [(0, 1), (1, 2), (2, 3), (3, 0),   # front
             (4, 5), (5, 6), (6, 7), (7, 4),   # rear
             (0, 4), (1, 5), (2, 6), (3, 7)]   # connectors
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
        f"FRONT=0123 cam-near? {info.get('front_ok', '?')}  0=TL 1=TR 2=BR 3=BL",
        f"edge connector-cross: {info.get('conn_x', 0)} (0=ok wireframe)",
    ]
    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    bd.rectangle([(3, 3), (3 + 320, 3 + 14 * len(lines) + 6)], fill=(0, 0, 0, 180))
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

    # Restrict HDRIs to clean warehouse/industrial-toned ones.
    #  - mall_parking_lot: strong magenta/purple cast washes the floor (unrealistic)
    #  - factory_yard: intermittently fails to decode -> renders the world magenta
    # Keep the three reliable industrial yards.
    _DROP = ("mall_parking_lot", "factory_yard")
    _hdris = randomizers._collect_hdri_images()
    _keep = [im for im in _hdris if not any(d in im.name.lower() for d in _DROP)]
    randomizers._hdri_cache[:] = _keep
    print(f"  [HDRI] preview pool: {[im.name for im in _keep]}")

    # Use Cycles for the preview: EEVEE intermittently fails to upload the HDRI to
    # the GPU ("Failed to create GPU texture") which tints the whole frame magenta.
    # Cycles has no such per-frame GPU-upload step, so the world renders reliably.
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass

    saved = 0
    attempts = 0
    scene_count = {"scene_1.usd": 0, "scene_2.usd": 0, "scene_3.usd": 0}
    ratio_applied_total = 0

    while saved < N_SAMPLES and attempts < N_SAMPLES * 40:
        attempts += 1
        target_idx = choose_next_pallet_index()
        if target_idx < 0:
            print("[ERR] no valid pallet")
            break
        cam_mode = choose_camera_mode_name()
        mode_cfg = CAMERA_VIEW_MODES.get(cam_mode, {})
        min_area = mode_cfg.get("min_area_ratio", MIN_PROJECTED_AREA_RATIO)

        accepted = False
        reject_reason = "n/a"
        for _ in range(MAX_FRAME_RETRIES):
            bg = randomize_background()
            pallet_name, _ = randomize_pallet(chosen_idx=target_idx)
            if pallet_name is None:
                break
            pobj = get_obj(pallet_name)

            # --- anisotropic ratio randomization (40%) ---
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

            # Elevation-constrained oblique camera (NOT randomize_camera): bans
            # near-vertical top-down so one side face always clearly faces the cam.
            cam_pos, look_at, elev_deg, azim_deg = sample_camera_elev(geom)
            if cam_pos is None:
                break
            randomize_boxes(pobj, pallet_name, occlusion_target="light", target_box_count=2)
            randomize_distractors(pallet_pos, cam_pos, prefer_occlusion=False)
            randomize_hdri()
            bpy.context.view_layer.update()

            res = compute_annotation_v4(pallet_name, pobj, cam_pos, look_at)
            if res is None:
                continue
            ann, uv, vis, rot, area, geom, facing_margin, front_cos, front_aspect = res

            # gate (a) keypoints in-frame, (b) projected bbox area floor
            area_gate = max(min_area, MIN_AREA_FLOOR)
            if vis < VISIBLE_MIN_FRACTION or area < area_gate:
                reject_reason = f"area {area:.3f}<{area_gate:.3f} or vis {vis:.2f}"
                continue

            # gate (c) raycast occlusion against EXTERNAL objects only (base/side).
            sample_pts = _pallet_silhouette_points(geom)
            ray_vis = check_raycast_visibility(pobj, cam_pos, sample_pts)
            if ray_vis < MIN_RAYCAST_VIS:
                reject_reason = f"ray_vis {ray_vis:.2f}<{MIN_RAYCAST_VIS}"
                continue

            # gate (d) FRONT grazing: the FRONT face itself must clearly face the
            #          camera (NOT edge-on).  This is the primary fix for the
            #          frame02-type failure where FRONT projects to a thin slanted
            #          line and 0123 stops being a rectangle.  front_cos<thr means
            #          we are grazing/looking at the back of the chosen FRONT face.
            if not (front_cos >= FRONT_FACING_COS_MIN):
                reject_reason = (f"front_cos {front_cos:.3f}"
                                 f"<{FRONT_FACING_COS_MIN} (FRONT edge-on/grazing)")
                continue

            # gate (e) FRONT stability: the two candidate side faces must differ
            #          clearly in how much they face the camera, else 0123 is
            #          ambiguous (which side is FRONT can flip between frames).
            if not (facing_margin >= FACING_MARGIN_MIN):
                reject_reason = (f"facing_margin {facing_margin:.3f}"
                                 f"<{FACING_MARGIN_MIN} (FRONT ambiguous)")
                continue

            # gate (f) cuboid wireframe must not self-cross on the connectors
            #          (a wrong rear left/right labeling -> X-shaped wireframe).
            conn_x, total_x = count_edge_crossings(uv[:8])
            if conn_x > 0:
                reject_reason = f"connector_cross {conn_x} (perm mislabel)"
                continue

            ann["objects"][0]["raycast_visibility"] = float(ray_vis)
            ann["objects"][0]["edge_connector_crossings"] = int(conn_x)
            ann["objects"][0]["edge_total_crossings"] = int(total_x)
            ann["objects"][0]["camera_elevation_deg"] = float(elev_deg)
            ann["objects"][0]["camera_azimuth_deg"] = float(azim_deg)
            accepted = True
            break

        if not accepted:
            print(f"[REJECT] attempt {attempts} mode={cam_mode}: {reject_reason}")
            continue

        src = PALLET_SOURCE_ASSETS.get(pallet_name, pallet_name)
        frame = saved
        render_path = os.path.join(IMG_DIR, f"{frame:06d}.png")
        scene.render.filepath = render_path
        bpy.ops.render.render(write_still=True)

        # verify FRONT(0123) is the camera-near side face (problem 1 check)
        cub = np.array(ann["objects"][0]["cuboid"], dtype=np.float64)
        cam_np = np.array(cam_pos, dtype=np.float64)
        d_front = np.linalg.norm(cub[[0, 1, 2, 3]].mean(axis=0) - cam_np)
        d_rear = np.linalg.norm(cub[[4, 5, 6, 7]].mean(axis=0) - cam_np)
        front_ok = bool(d_front <= d_rear)

        ann["objects"][0]["ratio_randomized"] = bool(ratio_applied)
        ann["objects"][0]["ratio_factors"] = [float(f) for f in factors]
        ann["objects"][0]["front_is_camera_near"] = front_ok
        ann["camera_data"]["background_asset"] = bg
        ann["camera_data"]["camera_mode"] = cam_mode
        with open(os.path.join(JSON_DIR, f"{frame:06d}.json"), "w") as f:
            json.dump(ann, f, indent=2)

        conn_x = ann["objects"][0]["edge_connector_crossings"]
        ratio_str = ("YES " + ",".join(f"{x:.2f}" for x in factors)) if ratio_applied else "no"
        ov_path = os.path.join(OV_DIR, f"overlay_{frame:06d}.png")
        draw_overlay(render_path, ov_path,
                     uv, {"frame": frame, "scene": src, "ratio_str": ratio_str,
                          "vis": vis, "area": area, "ray": ray_vis,
                          "front_ok": "YES" if front_ok else "NO", "conn_x": conn_x,
                          "elev": elev_deg, "azim": azim_deg, "fmargin": facing_margin,
                          "front_cos": front_cos, "aspect": front_aspect})

        # verification crop: tight pallet bbox -> 2x upscale (crop the overlay so
        # the 0123 IDs/edges are visible at high zoom for eyeball checking).
        save_crop(ov_path, os.path.join(CROP_DIR, f"crop_{frame:06d}.png"), uv)

        scene_count[src] = scene_count.get(src, 0) + 1
        ratio_applied_total += int(ratio_applied)
        print(f"[OK] frame {frame:02d} {src} ratio={ratio_str} vis={vis:.2f} "
              f"area={area:.3f} ray={ray_vis:.2f} front_near={front_ok} "
              f"elev={elev_deg:.1f} azim={azim_deg:.1f} front_cos={front_cos:.3f} "
              f"fmargin={facing_margin:.3f} aspect={front_aspect:.2f} "
              f"perm={ann['objects'][0]['perm_v4']}")
        saved += 1

    print(f"\n=== DONE {saved}/{N_SAMPLES} (attempts={attempts}) ===")
    print(f"scene dist: {scene_count}")
    print(f"ratio randomized: {ratio_applied_total}/{saved}")


if __name__ == "__main__":
    main()
