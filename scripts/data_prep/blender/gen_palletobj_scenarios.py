"""
PalletObj 합성 데이터 생성기 (production-grade, 대규모 호환).

목적:
  - 10 시나리오 검증 모드: 각 케이스(원거리/근거리/truncation/occlusion 등)별 1프레임 명시 렌더
  - 대규모 생성 모드: scenarios 무작위 샘플링 + 시드별 jitter

핵심 보장:
  - Final visibility >= 4/8 (50% rule) — 사용자 false-positive 방지 요구
  - Occluder effectiveness: drop in [1, max_drop], else 재시도 또는 tier fallback
  - parent_clear + origin offset 보정 (industrial gltf의 EMPTY-parented mesh 대응)
  - Per-frame raycast 접지 (배경마다 floor_z 다름)
  - Per-frame intrinsics (FOV 다변화)

Blender 내부 Python에서 실행. Blender MCP 통해 호출하거나 CLI standalone.
"""

import bpy, os, json, math, random
from mathutils import Vector
import bpy_extras.object_utils as obj_utils
from PIL import Image, ImageDraw
import floor_and_mask as FM
import numpy as np
from blender_math import compute_perm_v4
import camera_effects as CE


# ============================================================
# CONFIG
# ============================================================
DEFAULT_OUT_BASE = r"E:/CODING/GitHub/FoundationPose/data/pallet/test_palletobj_v1"
PALLET_NAME = "pallet_full"
CAM_NAME = "Camera"
PALLET_DIMS = (1.10, 1.30, 0.12)  # X (width), Y (depth), Z (height) in world after grounding

# RealSense D435i Color 640x480 factory intrinsic (real inference camera). distortion=0.
D435I = {"fx": 605.9065, "fy": 605.9698, "cx": 317.5962, "cy": 256.2923}
SENSOR_W = 36.0
D435I_LENS = D435I["fx"] * SENSOR_W / 640.0  # ≈ 34.08mm  (fx = lens*W/sensor_w)
PALLET_HALF_EXTENT_XY = (0.55, 0.65)

BG_POSITIONS = {
    "BG_parking_lot": [(0, 0)],
    "BG_industrial": [(-3, 2), (-4, 1), (-4, 3)],
}

# Occluder size tiers — for fallback chain. Single-mesh only (avoid multi-part like metal_toolbox).
OCCLUDER_TIERS = {
    "large":  ["Barrel_Green Metal_0", "Barrel.001_Red Metal_0", "Barrel.002_Red Metal_0", "WetFloorSign_01"],
    "medium": ["Cardboard.001_Carton_0", "Cardboard.002_Carton_0", "Cardboard.003_Carton_0",
               "Cardboard.004_Carton_0", "Cardboard_Carton_0", "all_purpose_cleaner"],
    "small":  ["CheeseBox_01", "cleaner_tin_01"],
}

# Cargo (boxes/items placed ON TOP of the pallet) — varied shapes
# Includes irregular shapes (rocks/moon_rock) to simulate sandbags/sacks
CARGO_SOURCES = [
    # Boxes
    "Cardboard_Carton_0", "Cardboard.001_Carton_0", "Cardboard.002_Carton_0",
    "Cardboard.003_Carton_0", "Cardboard.004_Carton_0",
    "cardboard_box_01",   # bigger box variation
    "CheeseBox_01",
    # Industrial containers
    "cleaner_tin_01", "all_purpose_cleaner",
    "Barrel_01",          # small barrel for upright cargo
    # Irregular shapes (sandbags/sacks/piles)
    "moon_rock_01_LOD0",
    "moon_rock_02_LOD0",
]
SIZE_TIER = {n: t for t, names in OCCLUDER_TIERS.items() for n in names}
TIER_ORDER = {
    "large":  ["large", "medium", "small"],
    "medium": ["medium", "small", "large"],
    "small":  ["small", "medium", "large"],
}

CLOCK_AZIMUTH = {3: 0.0, 6: -90.0, 9: 180.0}

# Keypoint convention
KP_SIGN_TO_ID = {(-1,-1,+1):0, (+1,-1,+1):1, (+1,-1,-1):2, (-1,-1,-1):3,
                 (-1,+1,+1):4, (+1,+1,+1):5, (+1,+1,-1):6, (-1,+1,-1):7}
TOP_IDS = {0, 1, 4, 5}
EDGES = [(0,1),(1,5),(5,4),(4,0),(3,2),(2,6),(6,7),(7,3),(0,3),(1,2),(5,6),(4,7)]


# ============================================================
# SCENE HANDLES
# ============================================================
def get_scene_handles():
    scene = bpy.context.scene
    cam = bpy.data.objects[CAM_NAME]
    pal = bpy.data.objects[PALLET_NAME]
    cam.rotation_mode = 'XYZ'
    cam.data.clip_start = 0.005
    cam.data.sensor_width = SENSOR_W
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.lens = D435I_LENS
    # D435i principal point shift (cx,cy != image center). sign verified by reprojection.
    W, H = 640, 480
    # Blender HORIZONTAL fit, shift normalized by W. Verified empirically (reproj du/dv<1px):
    #   cx = W/2 - shift_x*W   (x flips) ;   cy = H/2 + shift_y*W
    cam.data.shift_x = (W / 2 - D435I["cx"]) / W
    cam.data.shift_y = (D435I["cy"] - H / 2) / W
    return scene, cam, pal


def get_world_hdri_nodes():
    world = bpy.context.scene.world
    env_node = map_node = bg_node = None
    for n in world.node_tree.nodes:
        if n.type == 'TEX_ENVIRONMENT': env_node = n
        elif n.type == 'MAPPING': map_node = n
        elif n.type == 'BACKGROUND': bg_node = n
    hdri_imgs = [img for img in bpy.data.images if '.hdr' in img.filepath.lower()]
    return env_node, map_node, bg_node, hdri_imgs


# ============================================================
# OCCLUDER MANAGEMENT
# ============================================================
def cleanup_occluders():
    for o in list(bpy.data.objects):
        if o.name.startswith("_OCCL_") or o.name.startswith("_OCCL_CARGO_"):
            bpy.data.objects.remove(o, do_unlink=True)


def cleanup_cargo():
    for o in list(bpy.data.objects):
        if "_CARGO_" in o.name:
            bpy.data.objects.remove(o, do_unlink=True)


def set_bg(name):
    """Show one BG collection, hide the other. OCCLUDER_POOL always hidden."""
    for cn in ("BG_parking_lot", "BG_industrial"):
        if cn in bpy.data.collections:
            h = (cn != name)
            for o in bpy.data.collections[cn].objects:
                if o.name.startswith("_OCCL_"): continue
                o.hide_viewport = h
                o.hide_render = h
    if "OCCLUDER_POOL" in bpy.data.collections:
        for o in bpy.data.collections["OCCLUDER_POOL"].objects:
            o.hide_viewport = True
            o.hide_render = True


def raycast_floor(scene, pal, x, y):
    pal.hide_viewport = True
    pal.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = scene.ray_cast(dg, Vector((x, y, 10.0)), Vector((0, 0, -1)))
    pal.hide_viewport = False
    pal.hide_render = False
    return float(loc.z) if hit else 0.0


def pallet_extent_xy(az):
    hx, hy = PALLET_HALF_EXTENT_XY
    cosx = abs(math.cos(az))
    siny = abs(math.sin(az))
    tx = hx / cosx if cosx > 1e-9 else float('inf')
    ty = hy / siny if siny > 1e-9 else float('inf')
    return min(tx, ty)


def count_corners_metrics(scene, cam, pal, corners_w):
    """Returns (n_in_frame, n_unoccluded, n_both)."""
    cam_pos = Vector(cam.location)
    pal.hide_viewport = True
    pal.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    n_in = n_unocc = n_both = 0
    for c in corners_w:
        co = obj_utils.world_to_camera_view(scene, cam, Vector(c))
        in_fr = (co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1)
        if in_fr: n_in += 1
        d = Vector(c) - cam_pos
        dist = d.length
        if dist < 1e-6: continue
        hit, *_ = scene.ray_cast(dg, cam_pos, d / dist, distance=dist * 0.97)
        unocc = not hit
        if unocc: n_unocc += 1
        if in_fr and unocc: n_both += 1
    pal.hide_viewport = False
    pal.hide_render = False
    return n_in, n_unocc, n_both


def get_visible_corners(scene, cam, pal, corners_w):
    cam_pos = Vector(cam.location)
    pal.hide_viewport = True
    pal.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for c in corners_w:
        co = obj_utils.world_to_camera_view(scene, cam, Vector(c))
        if not (co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1): continue
        d = Vector(c) - cam_pos
        dist = d.length
        if dist < 1e-6: continue
        hit, *_ = scene.ray_cast(dg, cam_pos, d / dist, distance=dist * 0.97)
        if not hit: out.append(c)
    pal.hide_viewport = False
    pal.hide_render = False
    return out


def _duplicate_and_normalize(src_name, idx_suffix):
    """Duplicate occluder, move to root collection, clear parent. Returns dup or None."""
    src = bpy.data.objects.get(src_name)
    if src is None: return None
    prev = (src.hide_viewport, src.hide_render)
    src.hide_viewport = False
    src.hide_render = False
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True)
    bpy.context.view_layer.objects.active = src
    bpy.ops.object.duplicate(linked=True)
    dup = bpy.context.active_object
    dup.name = f"_OCCL_{idx_suffix}_{src_name[:20]}"
    src.hide_viewport, src.hide_render = prev
    # Move to root collection
    for c in list(dup.users_collection):
        c.objects.unlink(dup)
    bpy.context.scene.collection.objects.link(dup)
    # Clear parent keeping current world transform
    if dup.parent is not None:
        bpy.ops.object.select_all(action='DESELECT')
        dup.select_set(True)
        bpy.context.view_layer.objects.active = dup
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.context.view_layer.update()
    return dup


def _place_dup_at(dup, target_xy, floor_z, yaw_rad):
    """Position dup so its geometry center lands at target_xy on floor_z."""
    bb_world = [dup.matrix_world @ Vector(c) for c in dup.bound_box]
    bb_center = sum(bb_world, Vector()) / 8.0
    bb_zmin = min(c.z for c in bb_world)
    origin_world = dup.matrix_world.translation
    xy_offset = Vector((bb_center.x - origin_world.x, bb_center.y - origin_world.y, 0))
    z_bottom_offset = bb_zmin - origin_world.z
    dup.location = (target_xy.x - xy_offset.x,
                    target_xy.y - xy_offset.y,
                    floor_z - z_bottom_offset)
    dup.rotation_euler = (dup.rotation_euler[0], dup.rotation_euler[1], yaw_rad)
    bpy.context.view_layer.update()


def place_cargo_on_pallet(num_items, pal_world_pos_xy, pallet_top_z, idx_base=1000):
    """
    Place 1-3 cargo items on top of pallet.
    Pallet footprint half-extents: 0.55 (X) x 0.65 (Y), centered at pal_world_pos_xy.
    Items placed with margin so they don't dangle off the edge.
    Returns list of (dup_obj, src_name).
    """
    hx_inner = 0.40  # leave 15cm margin from edge in X
    hy_inner = 0.50  # leave 15cm margin from edge in Y
    placed = []
    placed_xy_radii = []  # (x, y, radius) for overlap check between cargo items
    px, py = pal_world_pos_xy
    for k in range(num_items):
        for attempt in range(8):
            src = random.choice(CARGO_SOURCES)
            dup = _duplicate_and_normalize(src, f"CARGO_{idx_base}_{k}_a{attempt}")
            if dup is None: continue
            # Get dimensions
            bb = [dup.matrix_world @ Vector(c) for c in dup.bound_box]
            sx = max(c.x for c in bb) - min(c.x for c in bb)
            sy = max(c.y for c in bb) - min(c.y for c in bb)
            sz = max(c.z for c in bb) - min(c.z for c in bb)
            half_radius_xy = max(sx, sy) / 2.0
            # Random position within pallet inner footprint
            tx = px + random.uniform(-(hx_inner - half_radius_xy*0.5), (hx_inner - half_radius_xy*0.5))
            ty = py + random.uniform(-(hy_inner - half_radius_xy*0.5), (hy_inner - half_radius_xy*0.5))
            # Overlap check with previously placed cargo
            ok = True
            for (ox, oy, orad) in placed_xy_radii:
                d = math.hypot(tx - ox, ty - oy)
                if d < (half_radius_xy + orad) * 0.85:  # allow 15% touching
                    ok = False; break
            if not ok:
                bpy.data.objects.remove(dup, do_unlink=True)
                continue
            yaw = random.uniform(0, 2 * math.pi)
            _place_dup_at(dup, Vector((tx, ty, 0)), pallet_top_z, yaw)  # bottom on pallet top
            placed.append((dup, src))
            placed_xy_radii.append((tx, ty, half_radius_xy))
            break
        # If all 8 attempts failed, skip this cargo slot
    return placed


def place_occluder_robust(preferred_src, scene, cam, pal, corners_w, floor_z,
                          vis_baseline, min_vis=4, max_drop=4, idx=0):
    """
    Production-grade occluder placement.
    Tries preferred + fallback to smaller tiers when overkill, larger when ineffective.
    Acceptance: 1 <= vis_drop <= max_drop AND vis_after >= min_vis.
    Returns: (dup_or_None, vis_after, src_used_or_None, log_str)
    """
    if vis_baseline < min_vis:
        return None, vis_baseline, None, "baseline_below_min"
    visible_corners = get_visible_corners(scene, cam, pal, corners_w)
    if not visible_corners:
        return None, vis_baseline, None, "no_visible_corners"

    # Build candidate source list with tier fallback diversity
    pref_tier = SIZE_TIER.get(preferred_src, "medium")
    tiers = TIER_ORDER[pref_tier]
    candidate_srcs = [preferred_src] if preferred_src else []
    for tier in tiers:
        for n in OCCLUDER_TIERS[tier]:
            if n != preferred_src and n not in candidate_srcs:
                candidate_srcs.append(n)
    # Limit total attempts but maintain tier diversity
    attempts_per_src = 4
    max_sources = 5  # preferred + 4 fallbacks (will span tiers)
    candidate_srcs = candidate_srcs[:max_sources]

    best_candidate = None  # (score, vis_after, dup, src)

    def _safe_remove(obj):
        if obj is not None:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

    for src in candidate_srcs:
        for attempt in range(attempts_per_src):
            dup = _duplicate_and_normalize(src, f"{idx}_a{attempt}_t{SIZE_TIER.get(src,'?')[0]}")
            if dup is None: continue
            tc = Vector(random.choice(visible_corners))
            cam_v = Vector(cam.location)
            t = random.uniform(0.45, 0.82)
            target_xy = cam_v.lerp(tc, t)
            forward = (tc - cam_v).normalized()
            perp = Vector((-forward.y, forward.x, 0.0))
            if perp.length > 1e-6:
                perp = perp.normalized()
                # Wider perp range for large tier (helps avoid full coverage)
                perp_range = 0.5 if SIZE_TIER.get(src) == "large" else 0.35
                target_xy += perp * random.uniform(-perp_range, perp_range)
            yaw = random.uniform(0, 2 * math.pi)
            _place_dup_at(dup, target_xy, floor_z, yaw)
            _, _, vis_after = count_corners_metrics(scene, cam, pal, corners_w)
            drop = vis_baseline - vis_after

            if vis_after >= min_vis and 1 <= drop <= max_drop:
                # SUCCESS — cleanup any stale best_candidate
                if best_candidate and best_candidate[2] is not dup:
                    _safe_remove(best_candidate[2])
                return dup, vis_after, src, f"ok drop={drop} src={src} att{attempt}"

            if vis_after >= min_vis:
                # Acceptable visibility but drop=0 (ineffective) — keep as fallback
                score = abs(drop - 2) if drop > 0 else 10  # heavily penalize drop=0
                if best_candidate is None or score < best_candidate[0]:
                    if best_candidate:
                        _safe_remove(best_candidate[2])
                    best_candidate = (score, vis_after, dup, src)
                    continue
            # Reject this dup
            _safe_remove(dup)

    if best_candidate:
        return best_candidate[2], best_candidate[1], best_candidate[3], \
               f"fallback_best drop={vis_baseline-best_candidate[1]} src={best_candidate[3]}"
    return None, vis_baseline, None, "all_attempts_failed"


# ============================================================
# RENDERING + JSON + OVERLAY
# ============================================================
def reorder(corners):
    c = sum(corners, Vector()) / 8
    out = [None] * 8
    for v in corners:
        sx = +1 if v.x > c.x else -1
        sy = +1 if v.y > c.y else -1
        sz = +1 if v.z > c.z else -1
        out[KP_SIGN_TO_ID[(sx, sy, sz)]] = v
    return out


def project(scene, cam, p, W, H):
    co = obj_utils.world_to_camera_view(scene, cam, Vector(p))
    return (co.x * W, (1 - co.y) * H, co.z)


def hfov(lens, sw=36.0):
    return 2 * math.degrees(math.atan(sw / (2 * lens)))


def intrinsics(lens, sw, iw, ih):
    # D435i fixed intrinsic (camera is aligned to the real inference camera).
    return {"fx": D435I["fx"], "fy": D435I["fy"], "cx": D435I["cx"], "cy": D435I["cy"]}


def render_frame(scene, cam, pal, frame_idx, out_dir, overlay_dir,
                 meta_extra, hdri_imgs, env_node, map_node, bg_node, W, H):
    """Renders, computes annotation, writes JSON + overlay."""
    # HDRI random
    hdri = random.choice(hdri_imgs)
    env_node.image = hdri
    map_node.inputs['Rotation'].default_value[2] = random.uniform(0, 2 * math.pi)
    bg_node.inputs['Strength'].default_value = random.uniform(0.55, 0.95)
    scene.view_settings.exposure = random.uniform(-0.3, 0.2)
    bpy.context.view_layer.update()

    img_path = os.path.join(out_dir, f"{frame_idx:06d}.png")
    scene.render.filepath = img_path
    bpy.ops.render.render(write_still=True)

    # visible(modal) mask via 2-pass holdout (occlusion auto-excluded)
    mask_dir = os.path.join(out_dir, "mask")
    os.makedirs(mask_dir, exist_ok=True)
    mask_path = os.path.join(mask_dir, f"{frame_idx:06d}.png")
    FM.render_holdout_mask(scene, pal, mask_path)
    mask_coco = FM.mask_png_to_coco(mask_path)
    CE.apply(img_path, frame_idx)  # camera/sensor effects (RGB only), after mask, before overlay

    corners_w = [pal.matrix_world @ Vector(c) for c in pal.bound_box]
    # camera-facing dynamic 0123 (compute_perm_v4) instead of fixed object-frame order
    uv8 = [project(scene, cam, c, W, H) for c in corners_w]
    perm = compute_perm_v4(
        np.array([[c.x, c.y, c.z] for c in corners_w]),
        np.array([[u[0], u[1]] for u in uv8]),
        cam_pos=np.array([cam.location.x, cam.location.y, cam.location.z]))
    kps_world = [corners_w[int(perm[k])] for k in range(8)]
    centroid_w = sum(kps_world, Vector()) / 8
    kps_3d = kps_world + [centroid_w]
    kps_2d = [project(scene, cam, p, W, H) for p in kps_3d]
    in_frame = [bool(0 <= kp[0] <= W and 0 <= kp[1] <= H and kp[2] > 0) for kp in kps_2d]

    n_in, n_unocc, n_both = count_corners_metrics(scene, cam, pal, corners_w)

    pal_loc = pal.matrix_world.to_translation()
    pal_q = pal.matrix_world.to_quaternion()
    cam_loc = cam.location
    cam_q = cam.matrix_world.to_quaternion()
    lens = cam.data.lens
    intr = intrinsics(lens, 36.0, W, H)
    hfov_deg = hfov(lens)

    ann = {
        "camera_data": {
            "location_worldframe": [round(cam_loc.x, 4), round(cam_loc.y, 4), round(cam_loc.z, 4)],
            "quaternion_xyzw_worldframe": [round(cam_q.x, 5), round(cam_q.y, 5), round(cam_q.z, 5), round(cam_q.w, 5)],
            "intrinsics": {**intr, "lens_mm": lens, "sensor_width_mm": 36.0,
                           "resolution": [W, H], "hfov_deg": round(hfov_deg, 2)}
        },
        "objects": [{
            "class": "pallet", "name": "palletobj_v1",
            "location": [round(pal_loc.x, 4), round(pal_loc.y, 4), round(pal_loc.z, 4)],
            "quaternion_xyzw": [round(pal_q.x, 5), round(pal_q.y, 5), round(pal_q.z, 5), round(pal_q.w, 5)],
            "cuboid_dimensions_m": list(PALLET_DIMS),
            "keypoint_convention": "camera_dynamic_0123_v4",
            "keypoints_3d_world": [[round(p.x, 4), round(p.y, 4), round(p.z, 4)] for p in kps_3d],
            "projected_cuboid": [[round(kp[0], 2), round(kp[1], 2)] for kp in kps_2d[:8]],
            "projected_cuboid_centroid": [round(kps_2d[8][0], 2), round(kps_2d[8][1], 2)],
            "keypoint_in_frame": in_frame,
            "num_corners_in_frame": n_in,
            "num_corners_unoccluded": n_unocc,
            "num_corners_visible": n_both,
            "visible_mask": f"mask/{frame_idx:06d}.png",
            "mask_bbox_xywh": mask_coco["bbox_xywh"],
            "mask_area_px": mask_coco["area_px"],
            "mask_rle": mask_coco["rle"],
        }],
        "frame_meta": {
            **meta_extra,
            "hdri": hdri.name,
            "exposure_ev": round(scene.view_settings.exposure, 3),
        },
    }
    with open(os.path.join(out_dir, f"{frame_idx:06d}.json"), "w") as f:
        json.dump(ann, f, indent=2)

    # === Detailed Overlay ===
    # Retry loop for PIL OSError "broken data stream" (race with Blender PNG write)
    import time as _time
    img = None
    for _attempt in range(5):
        try:
            with Image.open(img_path) as _tmp:
                img = _tmp.convert("RGB")
            break
        except (OSError, IOError) as _e:
            _time.sleep(0.2 + _attempt * 0.3)
    if img is None:
        print(f"[render_frame] WARNING: PIL failed to read {img_path}, skipping overlay")
        return {"vis": n_both, "in_fr": n_in, "unocc": n_unocc}
    drw = ImageDraw.Draw(img)
    pts2d = [(kp[0], kp[1]) for kp in kps_2d]

    # Pose info: pallet euler angles + quaternion
    pal_euler = pal.matrix_world.to_euler('XYZ')
    pitch_deg = math.degrees(pal_euler.x)
    yaw_deg = math.degrees(pal_euler.z)
    roll_deg = math.degrees(pal_euler.y)

    # Camera-to-pallet distance (center)
    cam_pal_dist = (Vector(cam.location) - pal_loc).length

    # Area % (projected pallet polygon area / image area, approximated by convex hull of 8 corner projections)
    # Simple bbox-based area
    in_pts = [(p[0], p[1]) for p in kps_2d[:8] if 0 <= p[0] <= W and 0 <= p[1] <= H and p[2] > 0]
    if in_pts:
        x_coords = [p[0] for p in in_pts]
        y_coords = [p[1] for p in in_pts]
        area_pct = ((max(x_coords) - min(x_coords)) * (max(y_coords) - min(y_coords))) / (W * H) * 100.0
    else:
        area_pct = 0.0

    kpt_vis_pct = (n_in / 8.0) * 100.0
    ray_vis_pct = (n_unocc / 8.0) * 100.0

    # ---- Draw cuboid edges (per-axis color: connecting Y-axis = green, X-axis = red, Z-axis = blue) ----
    # ID layout for axis identification:
    #   X-axis edges (along world X): 0-1, 4-5, 3-2, 7-6
    #   Y-axis edges (along world Y in canonical = up): 0-4, 1-5, 3-7, 2-6 (vertical, top<->bot)
    #   Z-axis edges (along world Y in our setup, = depth): 0-3, 1-2, 4-7, 5-6
    X_EDGES = {(0,1),(4,5),(3,2),(7,6)}
    Y_EDGES = {(0,4),(1,5),(3,7),(2,6)}
    Z_EDGES = {(0,3),(1,2),(4,7),(5,6)}
    for a, b in EDGES:
        e = (a, b) if (a, b) in X_EDGES | Y_EDGES | Z_EDGES else (b, a)
        if e in X_EDGES: color = (255, 80, 80)
        elif e in Y_EDGES: color = (80, 220, 80)
        elif e in Z_EDGES: color = (80, 130, 255)
        else: color = (200, 200, 200)
        drw.line([pts2d[a], pts2d[b]], fill=color, width=2)

    # ---- Keypoint dots with per-ID distinct colors ----
    KP_COLORS = {
        0: (255, 165, 0),   # orange
        1: (255, 255, 0),   # yellow
        2: (100, 100, 255), # light blue
        3: (255, 100, 200), # pink
        4: (180, 0, 180),   # magenta
        5: (0, 200, 200),   # cyan
        6: (160, 80, 255),  # purple
        7: (255, 50, 50),   # red
        8: (255, 255, 255), # centroid white
    }
    for idx, (x, y, z) in enumerate(kps_2d):
        col = KP_COLORS.get(idx, (255, 255, 255))
        if not (0 <= x <= W and 0 <= y <= H and z > 0):
            col = (130, 130, 130)
        r = 7 if idx == 8 else 6
        drw.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(0, 0, 0))
        # ID label
        drw.text((x + r + 2, y - r - 2), str(idx), fill=(255, 255, 255))

    # ---- Pose axes at centroid (X red, Y green, Z blue) ----
    AXIS_LEN_M = 0.5
    centroid_world = pal_loc + Vector((0, 0, PALLET_DIMS[2] / 2.0))
    rot_mat = pal.matrix_world.to_3x3()
    for axis_idx, color in [(0, (255, 60, 60)), (1, (60, 220, 60)), (2, (80, 130, 255))]:
        axis_dir = rot_mat.col[axis_idx].normalized() * AXIS_LEN_M
        endpoint_w = centroid_world + axis_dir
        c_proj = project(scene, cam, centroid_world, W, H)
        e_proj = project(scene, cam, endpoint_w, W, H)
        if c_proj[2] > 0 and e_proj[2] > 0:
            drw.line([(c_proj[0], c_proj[1]), (e_proj[0], e_proj[1])], fill=color, width=3)
            drw.ellipse([e_proj[0]-4, e_proj[1]-4, e_proj[0]+4, e_proj[1]+4], fill=color, outline=(0,0,0))
            label = ["X", "Y", "Z"][axis_idx]
            drw.text((e_proj[0]+5, e_proj[1]+5), label, fill=color)

    # ---- Info panel (top-left) ----
    panel_x, panel_y, panel_w, panel_h = 6, 6, 175, 220
    drw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h], fill=(0, 0, 0, 200))
    pal_q_short = [round(pal_q.x, 2), round(pal_q.y, 2), round(pal_q.z, 2), round(pal_q.w, 2)]
    size_mm = (int(PALLET_DIMS[0] * 1000), int(PALLET_DIMS[2] * 1000), int(PALLET_DIMS[1] * 1000))
    info_lines = [
        f"Frame: {frame_idx:06d}",
        f"Object: palletobj_v1",
        f"Scenario: {meta_extra.get('scenario','-')[:18]}",
        f"BG: {meta_extra.get('background_3d','-')}",
        f"Distance: {cam_pal_dist:.2f}m",
        f"Cam dist(surf): {meta_extra.get('camera_dist_from_pallet_surface_m','?')}m",
        f"Cam height: {meta_extra.get('camera_height_above_floor_m','?')}m",
        f"Lens: {lens:.0f}mm  HFOV: {hfov_deg:.1f}°",
        f"Kpt Vis: {kpt_vis_pct:.0f}% ({n_in}/8)",
        f"Ray Vis: {ray_vis_pct:.0f}% ({n_unocc}/8)",
        f"Combined: {n_both}/8",
        f"Area: {area_pct:.1f}%",
        f"Pitch: {pitch_deg:+.1f}°",
        f"Yaw: {yaw_deg:+.1f}°",
        f"Roll: {roll_deg:+.1f}°",
        f"Q: [{pal_q_short[0]},{pal_q_short[1]},{pal_q_short[2]},{pal_q_short[3]}]",
        f"Size: {size_mm[0]}x{size_mm[1]}x{size_mm[2]}mm",
        f"Cam: ({cam_loc.x:.1f},{cam_loc.y:.1f},{cam_loc.z:.1f})",
        f"Trunc: {'Y' if meta_extra.get('truncation_applied') else 'N'} "
        f"Occ: {'Y' if meta_extra.get('occlusion_applied') else 'N'} "
        f"Cargo: {meta_extra.get('cargo_count', 0)}",
    ]
    for i, line in enumerate(info_lines):
        drw.text((panel_x + 5, panel_y + 4 + i * 11), line, fill=(255, 255, 255))

    # ---- Axis legend (bottom-right) ----
    leg_w, leg_h = 90, 60
    leg_x, leg_y = W - leg_w - 6, H - leg_h - 6
    drw.rectangle([leg_x, leg_y, leg_x + leg_w, leg_y + leg_h], fill=(0, 0, 0, 200))
    drw.rectangle([leg_x + 5, leg_y + 7, leg_x + 15, leg_y + 17], fill=(255, 60, 60))
    drw.text((leg_x + 20, leg_y + 7), "X axis", fill=(255, 255, 255))
    drw.rectangle([leg_x + 5, leg_y + 22, leg_x + 15, leg_y + 32], fill=(60, 220, 60))
    drw.text((leg_x + 20, leg_y + 22), "Y axis", fill=(255, 255, 255))
    drw.rectangle([leg_x + 5, leg_y + 37, leg_x + 15, leg_y + 47], fill=(80, 130, 255))
    drw.text((leg_x + 20, leg_y + 37), "Z axis", fill=(255, 255, 255))

    img.save(os.path.join(overlay_dir, f"{frame_idx:06d}.png"))

    return {"vis": n_both, "in_fr": n_in, "unocc": n_unocc}


# ============================================================
# FRAME GENERATION (single)
# ============================================================
def generate_frame(scene, cam, pal, frame_idx, scenario, out_dir, overlay_dir,
                   env_node, map_node, bg_node, hdri_imgs, W, H):
    """
    scenario = dict with keys:
      name, bg (BG_parking_lot|BG_industrial), surf_dist, h_above, lens, clock,
      az_jitter, do_trunc, lookat_shift_m, do_occ, occluder_src (or None),
      do_cargo (bool), num_cargo (1-3)
    Returns: (success_bool, log_str, metrics_dict)
    """
    cleanup_occluders()
    cleanup_cargo()
    bg = scenario["bg"]
    set_bg(bg)

    px, py = random.choice(BG_POSITIONS[bg])
    pal.location.x = float(px)
    pal.location.y = float(py)
    # Fresh randomized floor plane under the pallet (both backgrounds, 14 textures).
    # Must run after set_bg() and before raycast_floor so the raycast lands on it.
    floor_desc = FM.randomize_floor((px, py))
    floor_z = raycast_floor(scene, pal, px, py)
    zmin_p = min((pal.matrix_world @ v.co).z for v in pal.data.vertices)
    pal.location.z += (floor_z - zmin_p)
    bpy.context.view_layer.update()
    zmin_p = min((pal.matrix_world @ v.co).z for v in pal.data.vertices)
    zmax_p = max((pal.matrix_world @ v.co).z for v in pal.data.vertices)
    target_z = (zmin_p + zmax_p) / 2

    cam.data.lens = D435I_LENS  # fixed D435i lens (no per-frame zoom)
    if "azimuth_deg" in scenario:
        az_deg = scenario["azimuth_deg"]
    else:
        az_deg = CLOCK_AZIMUTH[scenario["clock"]] + scenario.get("az_jitter", 0)
    az = math.radians(az_deg)
    dist_from_center = pallet_extent_xy(az) + scenario["surf_dist"]
    # elevation 기반 카메라 높이로 구도 다양화 (elev_deg 없으면 SCENARIOS_10용 h_above fallback)
    if "elev_deg" in scenario:
        h_above = dist_from_center * math.tan(math.radians(scenario["elev_deg"]))
    else:
        h_above = scenario["h_above"]
    cam.location = (px + dist_from_center * math.cos(az),
                    py + dist_from_center * math.sin(az),
                    floor_z + h_above)

    if scenario.get("do_trunc"):
        shift = scenario["lookat_shift_m"]
        shift_dir = math.radians(random.uniform(0, 360))
        target = Vector((float(px) + shift * math.cos(shift_dir),
                         float(py) + shift * math.sin(shift_dir),
                         target_z + random.uniform(-0.1, 0.1)))
    else:
        target = Vector((float(px), float(py), target_z))
    direction = target - Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()

    corners_w = [pal.matrix_world @ Vector(c) for c in pal.bound_box]

    # === CARGO on pallet (placed BEFORE visibility baseline so it counts as scene clutter) ===
    cargo_placed = []
    if scenario.get("do_cargo"):
        # Determine pallet top Z in world
        pallet_top_z = max((pal.matrix_world @ v.co).z for v in pal.data.vertices)
        num_cargo = scenario.get("num_cargo", random.randint(1, 3))
        cargo_placed = place_cargo_on_pallet(num_cargo, (px, py), pallet_top_z, idx_base=frame_idx * 100)
        bpy.context.view_layer.update()

    n_in_b, n_unocc_b, vis_baseline = count_corners_metrics(scene, cam, pal, corners_w)

    if n_in_b < 4:
        return False, f"truncation_gate_fail in_frame={n_in_b}/8", {}

    actual_src = None
    occ_log = "none"
    if scenario.get("do_occ") and scenario.get("occluder_src"):
        dup, vis_after, src_used, log = place_occluder_robust(
            scenario["occluder_src"], scene, cam, pal, corners_w, floor_z,
            vis_baseline, min_vis=4, max_drop=4, idx=frame_idx)
        actual_src = src_used
        occ_log = log
        bpy.context.view_layer.update()

    n_in, n_unocc, n_both = count_corners_metrics(scene, cam, pal, corners_w)
    if n_both < 4:
        cleanup_occluders()
        return False, f"final_vis_fail vis={n_both}/8 ({occ_log})", {}

    meta = {
        "scenario": scenario.get("name", "ad_hoc"),
        "background_3d": bg.replace("BG_", ""),
        "pallet_pos_xy": [px, py],
        "floor_z_m": round(floor_z, 4),
        "camera_height_above_floor_m": round(h_above, 3),
        "camera_elevation_deg": round(scenario.get("elev_deg", 0.0), 1),
        "camera_dist_from_pallet_surface_m": scenario["surf_dist"],
        "clock_position": scenario["clock"],
        "azimuth_deg": round(az_deg, 1),
        "truncation_applied": bool(scenario.get("do_trunc")),
        "lookat_shift_m": scenario.get("lookat_shift_m", 0.0),
        "occlusion_applied": bool(scenario.get("do_occ")),
        "occluder_preferred": scenario.get("occluder_src"),
        "occluder_actual": actual_src,
        "occluder_log": occ_log,
        "vis_baseline": vis_baseline,
        "vis_drop": vis_baseline - n_both,
        "cargo_applied": bool(scenario.get("do_cargo")),
        "cargo_count": len(cargo_placed),
        "cargo_assets": [src for (_, src) in cargo_placed],
        "floor": floor_desc,
    }
    metrics = render_frame(scene, cam, pal, frame_idx, out_dir, overlay_dir,
                           meta, hdri_imgs, env_node, map_node, bg_node, W, H)
    metrics["actual_src"] = actual_src
    metrics["occ_log"] = occ_log
    metrics["baseline"] = vis_baseline
    return True, "ok", metrics


# ============================================================
# SCENARIO DEFINITIONS (10 verification cases)
# ============================================================
SCENARIOS_10 = [
    dict(name="S0_normal_mid_parking",    bg="BG_parking_lot", surf_dist=2.5, h_above=0.30, lens=35.0, clock=6, az_jitter=+5,  do_trunc=False, lookat_shift_m=0.0, do_occ=False, occluder_src=None),
    dict(name="S1_normal_far_industrial", bg="BG_industrial",  surf_dist=4.5, h_above=0.30, lens=35.0, clock=9, az_jitter=-10, do_trunc=False, lookat_shift_m=0.0, do_occ=False, occluder_src=None),
    dict(name="S2_close_natural_trunc",   bg="BG_parking_lot", surf_dist=0.10,h_above=0.20, lens=28.0, clock=3, az_jitter=0,   do_trunc=False, lookat_shift_m=0.0, do_occ=False, occluder_src=None),
    dict(name="S3_far_trunc_lookat",      bg="BG_parking_lot", surf_dist=4.0, h_above=0.40, lens=32.0, clock=9, az_jitter=+15, do_trunc=True,  lookat_shift_m=1.6, do_occ=False, occluder_src=None),
    dict(name="S4_mid_trunc_lookat",      bg="BG_industrial",  surf_dist=2.0, h_above=0.35, lens=30.0, clock=6, az_jitter=-8,  do_trunc=True,  lookat_shift_m=0.9, do_occ=False, occluder_src=None),
    dict(name="S5_mid_occ_barrel",        bg="BG_industrial",  surf_dist=2.0, h_above=0.30, lens=35.0, clock=6, az_jitter=+10, do_trunc=False, lookat_shift_m=0.0, do_occ=True,  occluder_src="Barrel_Green Metal_0"),
    dict(name="S6_mid_occ_cardboard",     bg="BG_parking_lot", surf_dist=1.8, h_above=0.30, lens=32.0, clock=3, az_jitter=+5,  do_trunc=False, lookat_shift_m=0.0, do_occ=True,  occluder_src="Cardboard.001_Carton_0"),
    dict(name="S7_mid_occ_wetfloorsign",  bg="BG_parking_lot", surf_dist=2.2, h_above=0.40, lens=38.0, clock=9, az_jitter=-15, do_trunc=False, lookat_shift_m=0.0, do_occ=True,  occluder_src="WetFloorSign_01"),
    dict(name="S8_far_occ_barrel",        bg="BG_parking_lot", surf_dist=3.5, h_above=0.30, lens=30.0, clock=6, az_jitter=+5,  do_trunc=False, lookat_shift_m=0.0, do_occ=True,  occluder_src="Barrel.001_Red Metal_0"),
    dict(name="S9_combo_trunc_occ",       bg="BG_parking_lot", surf_dist=2.5, h_above=0.30, lens=35.0, clock=3, az_jitter=-10, do_trunc=True,  lookat_shift_m=0.7, do_occ=True,  occluder_src="CheeseBox_01"),
]


# ============================================================
# RANDOM SCENARIO SAMPLER (for mass production)
# ============================================================
def sample_random_scenario(seed_idx):
    """Sample a randomized scenario for mass production."""
    bg = random.choice(["BG_parking_lot", "BG_industrial"])
    # addon: projected-size-balanced distance (5 bins). pallet ~1.3m, fx 606.
    size_bin = random.choice([(40, 64), (64, 128), (128, 256), (256, 384), (384, 560)])
    surf_dist = max(0.0, D435I["fx"] * 1.3 / random.uniform(*size_bin) - 0.7)
    h_above = random.uniform(0.15, 0.50)
    elev_deg = random.uniform(0.0, 60.0)       # addon: low forklift 0~12 included
    azimuth_deg = random.uniform(0.0, 360.0)   # addon: fill empty azimuth, uniform 360
    lens = D435I_LENS; clock = 6; az_jitter = 0.0  # placeholders (azimuth_deg is used)
    # Truncation: distance-aware shift so far frames actually clip
    do_trunc = (random.random() < 0.4) and (surf_dist >= 0.5)
    if do_trunc:
        # Shift proportional to distance: closer → smaller shift, farther → larger.
        # At d=0.5m: shift 0.2-0.4m. At d=5m: shift 1.5-3.0m. Yields meaningful clipping in image.
        lookat_shift_m = random.uniform(0.4, 0.7) * surf_dist
    else:
        lookat_shift_m = 0.0
    do_occ = (random.random() < 0.5) and (surf_dist >= 1.0)
    if do_occ:
        all_srcs = [s for srcs in OCCLUDER_TIERS.values() for s in srcs]
        # Pick by distance: far → small/medium preferred; close → large OK
        if surf_dist >= 3.0:
            tier_weights = ["small"] * 3 + ["medium"] * 4 + ["large"] * 1
        elif surf_dist >= 1.5:
            tier_weights = ["medium"] * 4 + ["small"] * 2 + ["large"] * 2
        else:
            tier_weights = ["medium"] * 3 + ["large"] * 3 + ["small"] * 1
        chosen_tier = random.choice(tier_weights)
        occluder_src = random.choice(OCCLUDER_TIERS[chosen_tier])
    else:
        occluder_src = None
    # Cargo on pallet (was missing in v1 — caused 0% cargo)
    do_cargo = random.random() < 0.55  # ~55% of frames have cargo
    num_cargo = random.choice([1, 1, 2, 2, 3]) if do_cargo else 0  # weighted toward 1-2 items
    return dict(name=f"R{seed_idx:06d}", bg=bg, surf_dist=surf_dist, h_above=h_above,
                elev_deg=elev_deg, azimuth_deg=azimuth_deg,
                lens=lens, clock=clock, az_jitter=az_jitter,
                do_trunc=do_trunc, lookat_shift_m=lookat_shift_m,
                do_occ=do_occ, occluder_src=occluder_src,
                do_cargo=do_cargo, num_cargo=num_cargo)


# ============================================================
# RUNNERS
# ============================================================
def run_scenarios(scenarios, out_base, seed=99, render_resolution=(640, 480)):
    """Run a fixed list of scenarios. Outputs frame N for scenario N (index)."""
    scene, cam, pal = get_scene_handles()
    scene.render.resolution_x, scene.render.resolution_y = render_resolution
    scene.render.image_settings.file_format = 'PNG'
    try:
        scene.render.engine = 'BLENDER_EEVEE'
    except Exception:
        pass
    env_node, map_node, bg_node, hdri_imgs = get_world_hdri_nodes()
    W, H = render_resolution

    overlay_dir = os.path.join(out_base, "overlay")
    os.makedirs(overlay_dir, exist_ok=True)

    random.seed(seed)
    results = []
    for i, sc in enumerate(scenarios):
        ok, log, metrics = generate_frame(scene, cam, pal, i, sc,
                                          out_base, overlay_dir,
                                          env_node, map_node, bg_node, hdri_imgs, W, H)
        results.append({"i": i, "name": sc.get("name", "?"), "ok": ok, "log": log, **metrics})
        print(f"  [{i}] {sc.get('name','?'):30s} {'OK' if ok else 'FAIL'} | {log} | "
              f"vis={metrics.get('vis','?')}/8 baseline={metrics.get('baseline','?')} "
              f"drop={metrics.get('baseline',0)-metrics.get('vis',0) if metrics else '?'} "
              f"src={metrics.get('actual_src','-')}")
    cleanup_occluders()
    return results


def run_mass_production(num_frames, out_base, seed=42, render_resolution=(640, 480),
                        max_retries_per_frame=5):
    """
    Mass production: each frame is sampled randomly. If a frame fails (visibility gate etc),
    re-sample with new seed up to max_retries_per_frame.
    """
    scene, cam, pal = get_scene_handles()
    scene.render.resolution_x, scene.render.resolution_y = render_resolution
    scene.render.image_settings.file_format = 'PNG'
    try:
        scene.render.engine = 'BLENDER_EEVEE'
    except Exception:
        pass
    env_node, map_node, bg_node, hdri_imgs = get_world_hdri_nodes()
    W, H = render_resolution

    overlay_dir = os.path.join(out_base, "overlay")
    os.makedirs(overlay_dir, exist_ok=True)

    random.seed(seed)
    results = []
    frame_idx = 0
    total_attempts = 0
    safety = num_frames * max_retries_per_frame
    while frame_idx < num_frames and total_attempts < safety:
        total_attempts += 1
        sc = sample_random_scenario(total_attempts)
        ok, log, metrics = generate_frame(scene, cam, pal, frame_idx, sc,
                                          out_base, overlay_dir,
                                          env_node, map_node, bg_node, hdri_imgs, W, H)
        if ok:
            results.append({"i": frame_idx, "scenario": sc.get("name"), **metrics, **{k: sc[k] for k in ("bg", "surf_dist", "h_above", "lens", "clock", "do_trunc", "do_occ", "occluder_src")}})
            frame_idx += 1
            if frame_idx % 50 == 0:
                print(f"  progress: {frame_idx}/{num_frames} (attempts={total_attempts})")
    cleanup_occluders()
    print(f"=== Mass production done: {frame_idx}/{num_frames} frames in {total_attempts} attempts ===")
    return results


if __name__ == "__main__":
    # Default: run scenarios for verification
    results = run_scenarios(SCENARIOS_10, DEFAULT_OUT_BASE)
    print("\nFinal summary:")
    for r in results:
        print(f"  {r}")
