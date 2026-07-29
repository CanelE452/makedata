"""Large-scale dataset generator for camera-dynamic 0123 labels (compute_perm_v4).

Engine is identical to gen_topview_test.py (same gates, perm_v4 azimuth-facing FRONT,
raycast visibility, ratio randomization, Cycles render). This is the PRODUCTION
generator: it adds CLI args, resume-by-count, split-aware output.

Output layout = test_palletobj_r3 (DOPE-ready, flat):
    <split_dir>/000000.png  000000.json  ...   (png + json colocated in root)
    <split_dir>/overlay/000000.png ...          (full overlays, --overlay_every 1)
Chunk stats are written to <parent>/logs/ (outside the batch folder) so the dataset
folder holds only png/json/overlay. Resume = count of root {6d}.png in split_dir.

Labels: camera-facing dynamic 0123 (compute_perm_v4, azimuth-facing FRONT).
Camera: max diversity. elevation 15..65deg sampled; FRONT is now picked by azimuth
(elevation-independent), but the front_cos>=0.40 VISIBILITY gate still rejects frames
where the chosen FRONT face is grazing (near-vertical view), so high elevation is
capped by visibility, not by face-selection. azimuth 0..360 full range (pallet's 4
sides each get to be FRONT), dist 1.6..4.5m.
Gates (kept, semantics under azimuth rule): front_cos>=0.40 = VISIBILITY gate (FRONT
face not grazing; sigma-scaling input), facing_margin>=6deg = corner-ambiguity gate
(margin now in DEGREES, was cos-diff), connector_cross==0, visibility (in-frame +
area + raycast).

This script renders ONE CHUNK per invocation (a fresh Blender process per chunk
avoids the known memory-leak crash). The bash wrapper run_dataset_v4.sh drives the
chunks for train then val. Resume = count existing PNGs in the split dir.

Run (one chunk, headless):
    blender -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
        --python scripts/data_prep/blender/gen_dataset_v4.py -- \
        --split train --start_idx 0 --num_frames 100 --seed 7000 \
        --out_dir data/pallet/training_data_v4 --overlay_every 1
"""

import argparse
import json
import math
import os
import random
import sys
import time

import bpy
import mathutils
import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import blender_config as cfg
# 4-pallet mask dataset: ALL FOUR pallets. scene.usd(Pallet_0) 50% + scene_1/2/3
# each ~16.67% (user-specified, fixed). Pallet_0 was excluded in gen_dataset_v4
# (emissive_strength material) -- here it is INCLUDED and its emission is killed
# defensively after appearance (_kill_pallet_emission). This blend already ships
# Pallet_0 with non-emissive PalletVariant_plastic_*_blinn1 materials, but the
# guard makes the pipeline robust to a fresh raw-USD re-import.
cfg.PALLET_WEIGHTS = [0.5, 1.0 / 6.0, 1.0 / 6.0, 1.0 / 6.0]
# --- emptywood opt-in (env flags; default OFF -> v4_split reproducibility intact) ---
# EMPTYWOOD_WOOD_ONLY=1: wooden pallets only. Pallet_2=scene_2.usd, Pallet_3=scene_3.usd
#   are wood (pallet_color_group_for_model: wood); Pallet_1=scene_1.usd is plastic.
#   Pallet_0=scene.usd already excluded.
EMPTYWOOD_WOOD_ONLY = os.environ.get("EMPTYWOOD_WOOD_ONLY", "0") == "1"
# EMPTYWOOD_NO_CARGO=1: empty deck. randomize_boxes(..., target_box_count=0) hides all
#   cargo boxes (floor/around distractors are unaffected).
EMPTYWOOD_NO_CARGO = os.environ.get("EMPTYWOOD_NO_CARGO", "0") == "1"
if EMPTYWOOD_WOOD_ONLY:
    cfg.PALLET_WEIGHTS = [0.0, 0.0, 0.5, 0.5]  # wood-only: scene_2 + scene_3
cfg.PALLET_PLACEMENT_X_RANGE = (-11.0, -7.0)
cfg.PALLET_PLACEMENT_Y_RANGE = (-11.0, -4.0)

from blender_config import (
    IMAGE_WIDTH, IMAGE_HEIGHT, K, ORIENTATION_OVERRIDES, CORNER_COLORS_RGB,
    PALLET_SOURCE_ASSETS, VISIBLE_MIN_FRACTION, CAMERA_VIEW_MODES,
    MIN_PROJECTED_AREA_RATIO, MAX_FRAME_RETRIES,
    DISTRACTOR_NAMES, BOX_NAMES,
)
from blender_math import (
    rotation_matrix_to_quat_xyzw, rotation_matrix_to_euler_deg,
    build_view_matrix, compute_perm_v4,
)
from pallet_geometry import (
    get_pallet_geometry, snap_object_to_ground,
    object_bottom_z_world, object_top_z_world,
)
from efront_kp12 import compute_efront_kp12, efront_result_to_json  # ADDITIVE (E-front 12kp)
import distractor_pool_v2 as dpool  # ADDITIVE (v2 occlusion pool: 209 CC0/CC-BY)
import randomizers
from randomizers import (
    get_obj, setup_render, randomize_boxes,
    randomize_distractors, randomize_hdri, randomize_background,
    choose_next_pallet_index, choose_camera_mode_name,
    randomize_pallet_appearance, randomize_pallet, check_raycast_visibility,
    randomize_floor, mesh_overlap,
)
# palletobj "latest format" modules: visible-mask COCO encode + RGB sensor post.
# mask_png_to_coco is a pure reader (reused as-is). The holdout RENDER is done by a
# local hierarchy-aware variant (render_holdout_mask_hier) because the USD pallets
# are an EMPTY wrapper whose meshes are children -- floor_and_mask.render_holdout_mask
# marks white only where `ob is pal`, which would yield an all-black mask here.
from floor_and_mask import mask_png_to_coco
import camera_effects as CE

randomizers.PALLET_WEIGHTS = cfg.PALLET_WEIGHTS
randomizers.PALLET_PLACEMENT_X_RANGE = cfg.PALLET_PLACEMENT_X_RANGE
randomizers.PALLET_PLACEMENT_Y_RANGE = cfg.PALLET_PLACEMENT_Y_RANGE
cfg.BACKGROUND_WEIGHTS = {"industrial": 1.0, "parking_lot": 0.0}
randomizers.BACKGROUND_WEIGHTS = cfg.BACKGROUND_WEIGHTS

# --- camera sampling band (max diversity; gate caps effective top at ~58deg) ----
ELEV_MIN_DEG = 15.0
ELEV_MAX_DEG = 65.0
CAM_DIST_RANGE = (1.6, 4.5)

# --- v2 occlusion pool (ADDITIVE) -------------------------------------------
# scene_preset drives BOTH the distractor domain filter (distractor_pool_v2) and the
# scene_preset LABEL. indoor/outdoor-day/outdoor-night classification is the
# Illumination-DR Layer (future); until it lands every frame uses "random-mix" = the
# full 209 pool. Sketchfab_model x3 are not in that pool, so they are never selected.
SCENE_PRESET = "random-mix"
# per-frame distractor count band (from blender.yaml randomization.distractors).
DISTRACTOR_COUNT_RANGE = (
    int(cfg.DISTRACTOR_RANDOMIZATION["min_count"]),
    int(cfg.DISTRACTOR_RANDOMIZATION["max_count_light"]),
)

# Gates identical to gen_preview10 / gen_topview_test.
# facing_margin = 45 - |dphi| in DEGREES (compute_perm_v4 azimuth rule, 2026-07-24):
# dphi = az(center->cam) - az(chosen FRONT face normal). 45=head-on, 0=45deg corner-on
# (FRONT ambiguous between two adjacent faces). Rejects the corner-on band where the
# FRONT(0123) axis assignment flips.
#   [gate porting -- SILENT-BREAK NOTE] the OLD gate was 0.15 in COS-DIFF units
#   (best-minus-second facing cos). Under the old comment, 0.15 rejected a ~+/-6deg
#   azimuth band around each corner (passRate ~84%) with ~2x buffer over the truly
#   id0-unstable band (~+/-3deg). To reproduce THE SAME reject band in the new degree
#   units, |dphi|>=39deg must be rejected, i.e. facing_margin(=45-|dphi|) < 6deg -> so
#   the ported threshold is 6.0 deg. This keeps ~84% passRate and ~2x buffer over the
#   ~+/-3deg unstable band. [!! NEEDS USER CONFIRMATION: 6.0deg is first exercised at
#   v2 gen; the +/-6deg<->0.15cos equivalence is inferred from the old comment, not a
#   fresh sweep. Re-verify on the first v2 pilot.]
FACING_MARGIN_MIN = 6.0  # DEGREES (was 0.15 cos-diff; see note above)
FRONT_FACING_COS_MIN = 0.40  # VISIBILITY gate: chosen FRONT face not grazing
MIN_AREA_FLOOR = 0.045
# Raycast visibility gate on 10 BASE/SIDE silhouette points (top cargo box does NOT
# occlude these; occlusion here = external distractors/walls in front of the pallet).
# Relaxed 0.55 -> 0.30 to KEEP partial-occlusion frames (robustness, CLAUDE.md), while
# the area/vis gate (in-frame >= 0.60, area >= 0.045) still rejects nearly-invisible /
# too-small pallets. 0.30 = at least 3 of 10 base-side points must be unoccluded.
MIN_RAYCAST_VIS = 0.30

RATIO_PROB = 0.40
RATIO_RANGE = (0.88, 1.12)

# --- look_at jitter (anti-center-bias) -------------------------------------
# Without jitter, look_at == pallet centroid, so the centroid ALWAYS projects to
# image center (cx, cy) == (320, 240): zero screen-position diversity (see memory
# 2026-06-16_cam-test10-composition-check). We jitter look_at in the CAMERA image
# plane so the centroid lands at a random normalized screen position in
# [LOOKAT_JITTER_NORM_LO, HI] x [..] of the frame (0.5,0.5 = center). The corners
# spread AROUND that point; the in-frame visibility gate auto-rejects jitter that
# pushes any of the 8 corners out of frame (truncation excluded). 0.20..0.80 keeps
# the centroid within +-30% of the half-frame from center while leaving margin for
# the corner spread, so pass-rate stays healthy.
LOOKAT_JITTER = True
LOOKAT_JITTER_NORM_LO = 0.25
LOOKAT_JITTER_NORM_HI = 0.75
# For THIS test we additionally require all 8 corners strictly in-frame (no
# truncation) on top of the standard 0.60 visibility gate. Set False for the full
# production run if you want to KEEP some truncated frames (robustness).
REQUIRE_ALL_CORNERS_IN_FRAME = True

CUBOID_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)]
CONNECTOR_EDGES = [(0, 4), (1, 5), (2, 6), (3, 7)]

ELEV_BUCKETS = [(15, 25), (25, 35), (35, 45), (45, 55), (55, 65.0001)]
REASONS = ["area/vis", "raycast", "front_cos(grazing)", "facing_margin(ambig)",
           "connector_cross", "PASS"]


def _current_hdri_name():
    """Name of the HDRI image currently bound to the world environment node."""
    world = bpy.context.scene.world
    if world is None or not world.use_nodes:
        return "none"
    for node in world.node_tree.nodes:
        if node.type == "TEX_ENVIRONMENT" and node.image is not None:
            return node.image.name
    return "none"


def elev_bucket(e):
    for lo, hi in ELEV_BUCKETS:
        if lo <= e < hi:
            return f"{lo}-{int(hi)}"
    return "oob"


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


def sample_camera_elev(geom):
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

    # look_at jitter: shift the aim point in the camera image plane so the centroid
    # projects to a random screen position instead of always (cx, cy).
    look_at_vec = cen.copy()
    nx, ny = 0.5, 0.5
    if LOOKAT_JITTER:
        # camera frame looking at the (un-jittered) centroid; OpenCV convention
        # (right = R_w2c[0], image-down = -cam_up, forward = R_w2c[2]).
        R_w2c0, _ = build_view_matrix(cam_pos, tuple(cen), up=(0, 0, 1))
        right = R_w2c0[0]
        cam_up = -R_w2c0[1]   # world vector that maps to image-UP
        d = float(np.linalg.norm(cen - np.asarray(cam_pos)))  # cam->centroid depth
        nx = _r.uniform(LOOKAT_JITTER_NORM_LO, LOOKAT_JITTER_NORM_HI)
        ny = _r.uniform(LOOKAT_JITTER_NORM_LO, LOOKAT_JITTER_NORM_HI)
        du = (nx - 0.5) * IMAGE_WIDTH    # desired pixel offset of centroid from cx
        dv = (ny - 0.5) * IMAGE_HEIGHT   # +dv = lower on screen
        dx_world = du * d / float(K[0, 0])
        dy_world = dv * d / float(K[1, 1])
        # move the aim point: +right shifts centroid LEFT in image (camera turns
        # right), so to push centroid to +du we move look_at by -right*dx_world;
        # +cam_up moves centroid UP (-dv), so for +dv we move look_at by -cam_up*dy.
        look_at_vec = cen - right * dx_world - cam_up * dy_world

    look_at = (float(look_at_vec[0]), float(look_at_vec[1]), float(look_at_vec[2]))
    cam_obj = bpy.context.scene.camera
    if cam_obj is not None:
        cam_obj.location = cam_pos
        direction = mathutils.Vector(look_at) - mathutils.Vector(cam_pos)
        cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return cam_pos, look_at, math.degrees(elev), math.degrees(az)


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


def _weighted_pallet_index():
    """True weighted draw honoring PALLET_WEIGHTS=[0.5,1/6,1/6,1/6] exactly.
    randomizers.choose_next_pallet_index uses a bag sampler that seeds ONE of each
    pallet per cycle (+ a few weighted extras), which flattens Pallet_0 to ~33%
    regardless of its 0.5 weight (that suited v4's equal-thirds). Here the spec is
    Pallet_0 ~50%, so draw directly from the weights instead."""
    valid = [i for i, n in enumerate(cfg.PALLET_NAMES)
             if get_obj(n) is not None and randomizers._has_mesh_children(get_obj(n))
             and cfg.PALLET_WEIGHTS[i] > 0]
    if not valid:
        return -1
    w = [cfg.PALLET_WEIGHTS[i] for i in valid]
    return random.choices(valid, weights=w, k=1)[0]


def _kill_pallet_emission(pallet_obj):
    """Defensive: zero any emission on the chosen pallet's materials so scene.usd
    (Pallet_0) can never glow (raw USD ships emissive_strength=10000). No-op when
    the material already has emission 0 (current baked blend). Idempotent."""
    fixed = 0
    for mesh_obj in [pallet_obj, *pallet_obj.children_recursive]:
        if mesh_obj.type != "MESH":
            continue
        for slot in mesh_obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes or not mat.node_tree:
                continue
            nt = mat.node_tree
            for node in list(nt.nodes):
                if node.type == "BSDF_PRINCIPLED":
                    es = node.inputs.get("Emission Strength")
                    ec = node.inputs.get("Emission Color") or node.inputs.get("Emission")
                    if es is not None:
                        for link in list(es.links):
                            nt.links.remove(link)
                        if es.default_value != 0.0:
                            es.default_value = 0.0
                            fixed += 1
                    if ec is not None:
                        for link in list(ec.links):
                            nt.links.remove(link)
                        ec.default_value = (0.0, 0.0, 0.0, 1.0)
                elif node.type == "EMISSION":
                    # standalone emission shader feeding the output -> mute to black
                    s = node.inputs.get("Strength")
                    if s is not None:
                        for link in list(s.links):
                            nt.links.remove(link)
                        if s.default_value != 0.0:
                            s.default_value = 0.0
                            fixed += 1
    return fixed


def _audit_frame(pobj, distractor_names=None):
    """Code-based physical-plausibility evidence for the ACCEPTED frame (written to
    JSON so no fragile seed-replay is needed for verification):
      - pallet_bottom_z: lowest world-z of the pallet mesh (grounded => ~0).
      - distractor_overlap: BVH mesh-intersection of the pallet vs each VISIBLE
        external distractor (barrels/cones/barriers). These are placed AROUND the
        pallet, so any True = real penetration (defect). Cargo boxes are excluded
        because they REST on the deck (surface contact is expected, not a defect).
      - cargo_min_bottom_z / pallet_top_z: cargo boxes must sit ON the deck, so the
        lowest cargo bottom should be >= ~pallet_top_z (not sunk through / floating
        below ground)."""
    bottom_z = float(object_bottom_z_world(pobj))
    top_z = float(object_top_z_world(pobj))
    overlaps = []
    # v2: the distractors actually placed this frame (Dist_<name>); fall back to the
    # legacy hard-coded set when the v2 pool was not used.
    audit_names = distractor_names if distractor_names else DISTRACTOR_NAMES
    for dn in audit_names:
        d = get_obj(dn)
        if d is None or d.hide_render:
            continue
        try:
            if mesh_overlap(pobj, d):
                overlaps.append(dn)
        except Exception:
            pass
    cargo_bottoms = []
    for bn in BOX_NAMES:
        b = get_obj(bn)
        if b is None or b.hide_render:
            continue
        try:
            cargo_bottoms.append(float(object_bottom_z_world(b)))
        except Exception:
            pass
    return {
        "pallet_bottom_z": round(bottom_z, 4),
        "pallet_top_z": round(top_z, 4),
        "grounded": bool(abs(bottom_z) <= 0.02),
        "distractor_overlap_names": overlaps,
        "distractor_penetration": bool(overlaps),
        "n_cargo_visible": len(cargo_bottoms),
        "cargo_min_bottom_z": round(min(cargo_bottoms), 4) if cargo_bottoms else None,
        "cargo_on_deck": bool(all(cb >= -0.02 for cb in cargo_bottoms)) if cargo_bottoms else True,
    }


# --- visible(modal) mask: hierarchy-aware 2-pass holdout -----------------------
_MASK_MATS = {}


def _get_mask_mats():
    if not _MASK_MATS:
        for nm, v in (("__MASK_WHITE", 1.0), ("__MASK_BLACK", 0.0)):
            m = bpy.data.materials.get(nm) or bpy.data.materials.new(nm)
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            e = nt.nodes.new("ShaderNodeEmission")
            e.inputs["Color"].default_value = (v, v, v, 1.0)
            e.inputs["Strength"].default_value = 1.0
            o = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(e.outputs["Emission"], o.inputs["Surface"])
            m.use_fake_user = True
            _MASK_MATS[nm] = m
    return _MASK_MATS["__MASK_WHITE"], _MASK_MATS["__MASK_BLACK"]


def render_holdout_mask_hier(scene, pallet_root, mask_path):
    """Binary visible mask: the pallet HIERARCHY (wrapper empty + all child meshes)
    = white, everything else (occluders/cargo/floor/bg) = black, world = black.
    Occlusion is automatic -- anything rendered in front of the pallet paints those
    pixels black -> modal (visible) mask. Restores all materials/settings after."""
    white, black = _get_mask_mats()
    pal_set = {pallet_root, *pallet_root.children_recursive}
    backup = {}
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        backup[ob.name] = [s.material for s in ob.material_slots]
        tgt = white if ob in pal_set else black
        if not ob.material_slots:
            ob.data.materials.append(tgt)
        else:
            for s in ob.material_slots:
                s.material = tgt
    wbk = scene.world
    scene.world = None
    vbk = scene.view_settings.view_transform
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    fbk = scene.render.filepath
    cbk = scene.render.image_settings.color_mode
    # flat emission -> denoise/high-spp wasteful; drop to 1 sample for the mask pass
    sbk = scene.cycles.samples
    dbk = scene.cycles.use_denoising
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.filepath = mask_path
    scene.render.image_settings.color_mode = "BW"
    bpy.ops.render.render(write_still=True)
    # restore
    scene.cycles.samples = sbk
    scene.cycles.use_denoising = dbk
    scene.render.filepath = fbk
    scene.render.image_settings.color_mode = cbk
    scene.world = wbk
    scene.view_settings.view_transform = vbk
    for name, mats in backup.items():
        ob = bpy.data.objects.get(name)
        if not ob:
            continue
        if not mats:
            ob.data.materials.clear()
        else:
            for i, m in enumerate(mats):
                if i < len(ob.material_slots):
                    ob.material_slots[i].material = m
    return mask_path


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
            # --- v2 schema (ADDITIVE) --- per-frame resolution + aspect; scene_preset
            # is "random-mix" until the Illumination-DR Layer classifies indoor/outdoor.
            "resolution": [IMAGE_WIDTH, IMAGE_HEIGHT],
            "aspect_ratio": round(float(IMAGE_WIDTH) / float(IMAGE_HEIGHT), 6),
            "scene_preset": SCENE_PRESET,
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
            "facing_margin": float(facing_margin),  # DEGREES (45-|dphi|), NOT cos-diff
            "front_visibility_cos": float(front_cos),  # 3D facing cos of FRONT face; visibility / sigma-scaling input (renamed from front_facing_cos; no longer selects FRONT)
            "front_image_aspect": front_aspect,
            "front_rect_ok": bool(rect_ok),
            "dimensions_m": {"width": width_m, "height": height_m, "depth": depth_m},
            # --- v2 label schema (ADDITIVE) ------------------------------------
            # Filled now: pallet_type. Filled in main(): material_variant.
            # The rest are Layer placeholders (kept null with the owning Layer noted).
            # occlusion_fraction = per-corner[9] CONTINUOUS occlusion in [0,1]; there
            # is currently NO per-corner binary field -- the closest existing signals
            # are objects[0].raycast_visibility (aggregate over 10 silhouette pts) and
            # efront_kp12.kp12_visible (per-12kp binary, currently null: raycast_fn=None).
            # front_cos / facing_margin_deg ALREADY EXIST (see _existing_refs); not
            # duplicated here.
            "v2_labels": {
                "pallet_type": pallet_name,          # determined now
                "material_variant": None,            # filled in main() (randomize_pallet_appearance)
                "position_mode": None,               # Placement Layer (per-distractor near-pallet/near-camera)
                "occlusion_fraction": None,          # Layer2 (per-corner[9] continuous)
                "f_cargo": None,                     # Layer2
                "f_occ": None,                       # Layer2
                "f_total": None,                     # Layer2
                "luma_actual": None,                 # Illumination-DR Layer
                "edge_map": None,                    # Layer (deferred)
                "_existing_refs": {
                    "front_cos": "objects[0].front_visibility_cos",
                    "facing_margin_deg": "objects[0].facing_margin",
                    "binary_occlusion": "objects[0].raycast_visibility (aggregate); efront_kp12.kp12_visible (per-12kp, null)",
                },
            },
        }],
    }
    # --- E-front 12kp (ADDITIVE; existing 9-pt cuboid label above is unchanged) ---
    # raycast_fn=None: no per-point raycast helper is in this scope (the 8 cuboid
    # corners themselves are gated by in-frame only), so kp12_visible stays None and
    # only kp12_in_frame is filled -- matching the 8-corner treatment.
    _efront = compute_efront_kp12(
        pallet_name, corners_v4, perm, K, R_w2c, t_w2c,
        actual_face_dims={"width": width_m, "height": height_m, "depth": depth_m},
        image_wh=(IMAGE_WIDTH, IMAGE_HEIGHT), raycast_fn=None,
    )
    data["objects"][0]["efront_kp12"] = efront_result_to_json(_efront)
    return (data, uv, visibility, area_ratio, geom,
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
    for i, j in CUBOID_EDGES:
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
        f"{info['split']} #{info['frame']:06d}  {info['scene']}",
        f"ratio_rand: {info['ratio_str']}",
        f"vis {info['vis']:.0%}  area {info['area']:.1%}  ray {info.get('ray', 0):.0%}",
        f"elev {info.get('elev', 0):.1f}deg  azim {info.get('azim', 0):.1f}deg",
        f"FRONT vis cos {info.get('front_cos', 0):.3f} (>=0.40)",
        f"facing margin {info.get('fmargin', 0):.1f}deg (>=6deg)  aspect {info.get('aspect', 0):.2f}",
        f"FRONT=0123 cam-near? {info.get('front_ok', '?')}",
        f"connector-cross: {info.get('conn_x', 0)} (0=ok)",
        f"floor: {info.get('floor', '?')}",
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


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True, choices=["train", "val"])
    p.add_argument("--start_idx", type=int, default=0,
                   help="first frame index for THIS chunk (resume offset).")
    p.add_argument("--num_frames", type=int, required=True,
                   help="frames to generate in THIS chunk.")
    p.add_argument("--seed", type=int, default=7000)
    p.add_argument("--out_dir", default="data/pallet/training_data_v4")
    p.add_argument("--overlay_every", type=int, default=1,
                   help="save overlay every N frames (1 = all, r3 default). 0 = none.")
    p.add_argument("--flat_out", action="store_true",
                   help="write images/json/... directly under --out_dir instead of "
                        "under --out_dir/<split>. Used by the folder-split driver where "
                        "each 200-frame batch folder is its own self-contained dataset.")
    return p.parse_args(argv)


def main():
    args = parse_args()
    out_root = os.path.join(cfg.PROJECT_ROOT, args.out_dir) \
        if not os.path.isabs(args.out_dir) else args.out_dir
    # --flat_out: the batch folder (out_dir) IS the dataset root (used by the
    # folder-split driver, which encodes the split in the batch folder name).
    # Otherwise keep the legacy out_dir/<split>/ layout.
    split_dir = out_root if args.flat_out else os.path.join(out_root, args.split)
    # r3 layout: png + json live directly in split_dir root; overlay/ holds full
    # overlays named {frame:06d}.png. Chunk stats go to <out_root>/logs (outside the
    # batch folder) so the dataset folder stays clean (png/json/overlay only).
    img_dir = split_dir
    json_dir = split_dir
    ov_dir = os.path.join(split_dir, "overlay")
    mask_dir = os.path.join(split_dir, "mask")
    # stats_dir: for --flat_out the batch folder IS split_dir, so push stats one
    # level up to <parent>/logs; otherwise <out_root>/logs.
    stats_parent = os.path.dirname(split_dir.rstrip("/\\")) if args.flat_out else out_root
    stats_dir = os.path.join(stats_parent, "logs")
    for d in (img_dir, json_dir, ov_dir, mask_dir, stats_dir):
        os.makedirs(d, exist_ok=True)

    # seed varies per chunk via start_idx so resumed chunks are not identical
    np.random.seed(args.seed + args.start_idx)
    import random
    random.seed(args.seed + args.start_idx)

    print(f"  [EMPTYWOOD] wood_only={EMPTYWOOD_WOOD_ONLY} no_cargo={EMPTYWOOD_NO_CARGO} "
          f"PALLET_WEIGHTS={cfg.PALLET_WEIGHTS}")
    setup_render()
    scene = bpy.context.scene

    # Drop HDRIs with known magenta/purple-cast or decode-failure history.
    # mall_parking_lot = strong purple cast (content); factory_yard = intermittent
    # decode failure -> magenta world. The 4 newly-added industrial HDRIs
    # (empty_warehouse_01, hangar_interior, autoshop_01, industrial_workshop_foundry)
    # plus the 3 originals (construction_yard, freight_station,
    # overcast_industrial_courtyard) are real photographic and screened below.
    _DROP = ("mall_parking_lot", "factory_yard")
    _hdris = randomizers._collect_hdri_images()
    _keep = []
    for im in _hdris:
        nm = im.name.lower()
        if any(d in nm for d in _DROP):
            print(f"  [HDRI] DROP (history): {im.name}")
            continue
        # decode-failure guard: 0-size = no pixels -> magenta world.
        if im.size[0] == 0 or im.size[1] == 0:
            print(f"  [HDRI] DROP (no pixels): {im.name}")
            continue
        _keep.append(im)
    randomizers._hdri_cache[:] = _keep
    print(f"  [HDRI] adopted pool ({len(_keep)}): {[im.name for im in _keep]}")

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass

    target_end = args.start_idx + args.num_frames
    saved_this_chunk = 0
    candidates = 0
    attempts = 0
    scene_count = {"scene.usd": 0, "scene_1.usd": 0, "scene_2.usd": 0, "scene_3.usd": 0}
    bg_count = {}
    hdri_count = {}
    partial_occ_count = 0  # saved frames with ray_vis in [0.30, 0.55): newly admitted partial occlusion
    ratio_applied_total = 0
    elev_vals = []
    azim_vals = []
    fcos_vals = []
    stats = {r: {elev_bucket((lo + hi) / 2): 0 for lo, hi in ELEV_BUCKETS}
             for r in REASONS}

    t0 = time.time()
    frame = args.start_idx
    MAX_TOTAL_ATTEMPTS = args.num_frames * 60

    while frame < target_end and attempts < MAX_TOTAL_ATTEMPTS:
        attempts += 1
        # Preview sheets (FLOOR_FORCE_SEQUENCE=1) cycle floors by ACCEPTED frame
        # index so each saved frame shows a distinct floor (the inner retry loop
        # re-calls randomize_floor, but we key the forced index off `frame`).
        randomizers._floor_force_state["i"] = frame
        target_idx = _weighted_pallet_index()
        if target_idx < 0:
            print("[ERR] no valid pallet")
            break
        cam_mode = choose_camera_mode_name()
        mode_cfg = CAMERA_VIEW_MODES.get(cam_mode, {})
        min_area = mode_cfg.get("min_area_ratio", MIN_PROJECTED_AREA_RATIO)

        accepted = False
        last_reason = None
        pack = None
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
            mat_variant = randomize_pallet_appearance(pobj, pallet_name)  # ADDITIVE: captured for label
            _kill_pallet_emission(pobj)  # guard: scene.usd raw material can be emissive
            floor_info = randomize_floor(pallet_pos)

            cam_pos, look_at, elev_deg, azim_deg = sample_camera_elev(geom)
            if cam_pos is None:
                break
            bkt = elev_bucket(elev_deg)
            _box_count = 0 if EMPTYWOOD_NO_CARGO else 2
            randomize_boxes(pobj, pallet_name, occlusion_target="light", target_box_count=_box_count)
            # v2 occlusion: select from the 209 pool (size_class + domain_plausible +
            # scene_preset). Fall back to the legacy pool only if nothing was selected.
            _dsel = dpool.select_distractor_object_names(
                SCENE_PRESET, random.randint(*DISTRACTOR_COUNT_RANGE), random)
            if _dsel:
                randomize_distractors(pallet_pos, cam_pos, prefer_occlusion=False,
                                      distractor_names=_dsel,
                                      hide_names=dpool.all_object_names())
            else:
                randomize_distractors(pallet_pos, cam_pos, prefer_occlusion=False)
            randomize_hdri()
            hdri_name = _current_hdri_name()
            bpy.context.view_layer.update()

            res = compute_annotation_v4(pallet_name, pobj, cam_pos, look_at)
            if res is None:
                continue
            (ann, uv, vis, area, geom, facing_margin, front_cos,
             front_aspect, rect_ok, rect_area, rect_minside) = res

            conn_x, total_x = count_edge_crossings(uv[:8])
            area_gate = max(min_area, MIN_AREA_FLOOR)
            sample_pts = _pallet_silhouette_points(geom)
            ray_vis = check_raycast_visibility(pobj, cam_pos, sample_pts)

            all_in_frame = bool(
                (uv[:8, 0] >= 0).all() and (uv[:8, 0] < IMAGE_WIDTH).all() and
                (uv[:8, 1] >= 0).all() and (uv[:8, 1] < IMAGE_HEIGHT).all())

            if vis < VISIBLE_MIN_FRACTION or area < area_gate:
                reason = "area/vis"
            elif REQUIRE_ALL_CORNERS_IN_FRAME and not all_in_frame:
                reason = "area/vis"  # truncation: any of 8 corners off-frame
            elif ray_vis < MIN_RAYCAST_VIS:
                reason = "raycast"
            elif not (front_cos >= FRONT_FACING_COS_MIN):
                # VISIBILITY gate: azimuth-chosen FRONT face is grazing (3D facing cos
                # < 0.40). Under the azimuth rule this no longer changes WHICH face is
                # FRONT; it only rejects frames where that FRONT face is too edge-on.
                reason = "front_cos(grazing)"
            elif not (facing_margin >= FACING_MARGIN_MIN):
                # corner-ambiguity gate: facing_margin now in DEGREES (45-|dphi|);
                # < 6deg => camera within ~6deg of a corner, FRONT(0123) axis unstable.
                reason = "facing_margin(ambig)"
            elif conn_x > 0:
                reason = "connector_cross"
            else:
                reason = "PASS"

            stats[reason][bkt] = stats[reason].get(bkt, 0) + 1

            if reason != "PASS":
                last_reason = reason
                continue

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
                        conn_x=conn_x, hdri_name=hdri_name, ray_vis_val=ray_vis,
                        floor_info=floor_info,
                        mat_variant=mat_variant, placed_distractors=_dsel)
            break

        if not accepted:
            if last_reason:
                print(f"[REJECT] attempt {attempts}: {last_reason}")
            continue

        p = pack
        src = PALLET_SOURCE_ASSETS.get(p["pallet_name"], p["pallet_name"])
        render_path = os.path.join(img_dir, f"{frame:06d}.png")
        scene.render.filepath = render_path
        bpy.ops.render.render(write_still=True)

        # --- visible(modal) mask (holdout) + COCO RLE, then RGB sensor post ------
        # Order (palletobj convention): RGB render -> holdout mask -> camera_effects
        # on the RGB (in place) -> overlay drawn on the post-processed RGB below.
        pobj = get_obj(p["pallet_name"])
        # audit checks BVH penetration against the distractors ACTUALLY placed this
        # frame (v2 pool names when used, else the legacy DISTRACTOR_NAMES set).
        audit = _audit_frame(pobj, p["placed_distractors"])
        mask_path = os.path.join(mask_dir, f"{frame:06d}.png")
        render_holdout_mask_hier(scene, pobj, mask_path)
        mask_coco = mask_png_to_coco(mask_path)
        CE.apply(render_path, frame)

        cub = np.array(p["ann"]["objects"][0]["cuboid"], dtype=np.float64)
        cam_np = np.array(p["cam_pos"], dtype=np.float64)
        d_front = np.linalg.norm(cub[[0, 1, 2, 3]].mean(axis=0) - cam_np)
        d_rear = np.linalg.norm(cub[[4, 5, 6, 7]].mean(axis=0) - cam_np)
        front_ok = bool(d_front <= d_rear)

        ann = p["ann"]
        ann["objects"][0]["ratio_randomized"] = bool(p["ratio_applied"])
        ann["objects"][0]["ratio_factors"] = [float(f) for f in p["factors"]]
        ann["objects"][0]["front_is_camera_near"] = front_ok
        # visible(modal) mask fields (palletobj "latest format")
        ann["objects"][0]["visible_mask"] = f"mask/{frame:06d}.png"
        ann["objects"][0]["mask_bbox_xywh"] = mask_coco["bbox_xywh"]
        ann["objects"][0]["mask_area_px"] = mask_coco["area_px"]
        ann["objects"][0]["mask_rle"] = mask_coco["rle"]
        ann["objects"][0]["physical_audit"] = audit
        ann["objects"][0]["v2_labels"]["material_variant"] = p["mat_variant"]  # ADDITIVE
        ann["camera_data"]["background_asset"] = p["bg"]
        ann["camera_data"]["hdri_environment"] = p["hdri_name"]
        ann["camera_data"]["floor"] = p["floor_info"]
        ann["camera_data"]["camera_mode"] = p["cam_mode"]
        with open(os.path.join(json_dir, f"{frame:06d}.json"), "w") as f:
            json.dump(ann, f, indent=2)

        do_overlay = (args.overlay_every > 0 and frame % args.overlay_every == 0)
        if do_overlay:
            ratio_str = ("YES " + ",".join(f"{x:.2f}" for x in p["factors"])) if p["ratio_applied"] else "no"
            # r3 naming: overlay/{frame:06d}.png (matches the colocated png/json).
            ov_path = os.path.join(ov_dir, f"{frame:06d}.png")
            draw_overlay(render_path, ov_path, p["uv"],
                         {"split": args.split, "frame": frame, "scene": src,
                          "ratio_str": ratio_str, "vis": p["vis"], "area": p["area"],
                          "ray": p["ray_vis"], "front_ok": "YES" if front_ok else "NO",
                          "conn_x": p["conn_x"], "elev": p["elev_deg"],
                          "azim": p["azim_deg"], "fmargin": p["facing_margin"],
                          "front_cos": p["front_cos"], "aspect": p["front_aspect"],
                          "floor": p["floor_info"]["floor_texture"]})

        scene_count[src] = scene_count.get(src, 0) + 1
        bg_count[p["bg"]] = bg_count.get(p["bg"], 0) + 1
        hdri_count[p["hdri_name"]] = hdri_count.get(p["hdri_name"], 0) + 1
        if 0.30 <= p["ray_vis_val"] < 0.55:
            partial_occ_count += 1
        ratio_applied_total += int(p["ratio_applied"])
        elev_vals.append(p["elev_deg"])
        azim_vals.append(p["azim_deg"])
        fcos_vals.append(p["front_cos"])

        if saved_this_chunk % 10 == 0:
            dt = time.time() - t0
            rate = dt / max(saved_this_chunk, 1)
            pass_rate = (frame - args.start_idx + 1) / max(candidates, 1)
            print(f"[OK] {args.split} #{frame:06d} {src} elev={p['elev_deg']:.1f} "
                  f"azim={p['azim_deg']:.1f} fcos={p['front_cos']:.2f} "
                  f"| {rate:.1f}s/frame pass={pass_rate:.1%} cand={candidates}")
        frame += 1
        saved_this_chunk += 1

    dt = time.time() - t0
    chunk_summary = {
        "split": args.split,
        "start_idx": args.start_idx,
        "saved_this_chunk": saved_this_chunk,
        "candidates_evaluated": candidates,
        "attempts": attempts,
        "wall_seconds": dt,
        "sec_per_frame": dt / max(saved_this_chunk, 1),
        "pass_rate": saved_this_chunk / max(candidates, 1),
        "reject_stats": stats,
        "scene_dist": scene_count,
        "bg_dist": bg_count,
        "hdri_dist": hdri_count,
        "partial_occlusion_count": partial_occ_count,
        "raycast_gate": MIN_RAYCAST_VIS,
        "ratio_randomized": ratio_applied_total,
        "elev": elev_vals,
        "azim": azim_vals,
        "front_cos": fcos_vals,
    }
    # include the batch-folder name so chunks from different folders sharing the
    # shared <parent>/logs dir do not collide.
    _tag = os.path.basename(split_dir.rstrip("/\\")) if args.flat_out else args.split
    sname = os.path.join(stats_dir, f"stats_{_tag}_chunk_{args.start_idx:06d}.json")
    with open(sname, "w") as f:
        json.dump(chunk_summary, f, indent=2)
    print(f"\n[CHUNK DONE] {args.split} {saved_this_chunk} frames in {dt:.0f}s "
          f"({dt/max(saved_this_chunk,1):.1f}s/frame, pass={saved_this_chunk/max(candidates,1):.1%})")
    print(f"[STATS] {sname}")


if __name__ == "__main__":
    main()
