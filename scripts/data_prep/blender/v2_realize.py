"""v2 pipeline Layer-3 (Blender side): realize / render / measure / label + safety gates.

ADDITIVE. This is the bpy implementation that the STUBs in `v2_pipeline.py`
(realize/measure/render/label) delegate to. It is imported LAZILY (only when those
functions are actually called inside Blender), so `v2_pipeline` stays importable for
the pure dry-run (audit_v2_dryrun.py) without bpy.

It turns a solved `Plan` (pure geometry, pallet at world origin, yaw=0) into a concrete
Blender scene, renders the RGB + the three holdout masks needed for the occlusion
measurement, measures the ACTUAL frame quantities, evaluates the hard safety gates
(G1..G5), and builds the v2 label (both TARGET and ACTUAL recorded — 실측배정).

규약 realize측 (wired here):
  - perm 방위각 : compute_perm_v4 (blender_math) — azimuth-facing FRONT, already implemented.
  - Intrinsics DR: per-frame resolution + fx (lens_mm) + per-frame K recorded. Principal-point
                   jitter is parameterised (principal_jitter) but left 0 by default pending a
                   shift-sign verification (see _set_camera_intrinsics).
  - Illumination DR: exposure_ev applied via view_settings.exposure; luma_actual measured;
                   sensor-noise sigma raised for dark frames (measure -> render_post).
  - Resolution/aspect DR: per-frame resolution_x/y (v2_domain_randomization.md 5-companion).
  - 바닥×glTF : geometric ground detector (_hide_ground_geometric: XY>10m & Zthick<0.3m &
                   centre-z~=0) hides warehouse-style grounds that the name pattern misses,
                   plus a "native" floor option (keep the scene's own ground).

Reuses the legacy Blender helpers unchanged (randomizers / pallet_geometry / floor_and_mask
/ camera_effects) — the legacy generators are untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
import math
import os
import random
import tempfile
import time

import bpy
import mathutils
import numpy as np

import blender_config as cfg
from blender_config import ORIENTATION_OVERRIDES, SENSOR_WIDTH, PALLET_SOURCE_ASSETS
from blender_math import (
    build_view_matrix, compute_perm_v4,
    rotation_matrix_to_quat_xyzw, rotation_matrix_to_euler_deg,
)
from pallet_geometry import (
    get_pallet_geometry, get_obj_aabb_world, set_render_visibility,
    set_object_pose_grounded, temporary_visible_hierarchy,
)
import randomizers
from randomizers import (
    get_obj, setup_render, randomize_boxes, randomize_hdri, randomize_background,
    randomize_pallet_appearance, randomize_floor,
    initialize_pallet_assets, _has_mesh_children,
    _get_or_create_pallet_variant_material, _fallback_material_for_pallet,
    _resolve_material_replacement, _material_source_name,
)
from pallet_geometry import object_bottom_z_world, object_top_z_world
import distractor_pool_v2 as dpool
import camera_effects as CE
import mask_profiles as MP
import scene_placement_v2 as SP2
import scene_visibility_v2 as SV2
from efront_kp12 import compute_efront_kp12, efront_result_to_json

DIST_COLLECTION = "Distractors_v2"
GROUND_XY_MIN = 10.0        # geometric ground detector: XY extent (m) both axes
GROUND_Z_THICK_MAX = 0.30   # ...thin slab
GROUND_CZ_TOL = 0.15        # ...centred near z=0
NATIVE_FLOOR_PROB = 0.20    # fraction of frames that keep the scene's own ground
CONSTRAINED_HDRI_EXCLUDE = {
    "factory_yard_2k.hdr",
    "mall_parking_lot_2k.hdr",
}
_CONSTRAINED_HDRI_POOL_READY = False


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------
def _prepare_constrained_hdri_pool():
    """Bind constrained renders only to decoded HDRIs under the current repo."""
    global _CONSTRAINED_HDRI_POOL_READY
    if _CONSTRAINED_HDRI_POOL_READY and randomizers._hdri_cache:
        return randomizers._hdri_cache

    disk_paths = []
    if os.path.isdir(cfg.HDRI_DIR):
        disk_paths = [
            os.path.join(cfg.HDRI_DIR, name)
            for name in os.listdir(cfg.HDRI_DIR)
        ]
    candidates = SP2.constrained_hdri_paths(
        disk_paths,
        excluded_names=CONSTRAINED_HDRI_EXCLUDE,
    )
    valid = []
    for path in candidates:
        name = os.path.basename(path)
        try:
            image = bpy.data.images.get(name)
            if image is None:
                image = bpy.data.images.load(path, check_existing=True)
            image.filepath = path
            image.reload()
            if image.size[0] <= 0 or image.size[1] <= 0:
                print(f"  [HDRI-CONSTRAINED] DROP (no pixels): {name}")
                continue
            valid.append(image)
        except Exception as exc:
            print(f"  [HDRI-CONSTRAINED] DROP (decode error): {name}: {exc}")
    if not valid:
        raise RuntimeError(
            f"no decoded constrained HDRI is available under {cfg.HDRI_DIR}"
        )
    randomizers._hdri_cache[:] = valid
    _CONSTRAINED_HDRI_POOL_READY = True
    print(
        f"  [HDRI-CONSTRAINED] adopted pool ({len(valid)}): "
        f"{[image.name for image in valid]}"
    )
    return valid


def enable_gpu():
    """Best-effort Cycles GPU. Falls back silently to CPU."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dt in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = dt
                prefs.get_devices()
                if any(d.type == dt or d.type != "CPU" for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = (d.type != "CPU")
                    return dt
            except Exception:
                continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# CHECK #1 infra: force the Distractors_v2 collection render-enabled.
# ---------------------------------------------------------------------------
def _find_layer_collection(name, lc=None):
    if lc is None:
        lc = bpy.context.view_layer.layer_collection
    if lc.collection.name == name:
        return lc
    for child in lc.children:
        found = _find_layer_collection(name, child)
        if found is not None:
            return found
    return None


def force_distractors_v2_enabled():
    """A view-layer-EXCLUDED collection renders 0 distractors SILENTLY even when the
    per-object visibility is on (no error, no fallback). Force the whole path enabled:
    layer-collection un-exclude + collection.hide_render/hide_viewport off. Returns an
    info dict for the asset-check gate."""
    coll = bpy.data.collections.get(DIST_COLLECTION)
    if coll is None:
        return {"found": False}
    lc = _find_layer_collection(DIST_COLLECTION)
    was_excluded = bool(lc.exclude) if lc is not None else None
    if lc is not None:
        lc.exclude = False
        lc.hide_viewport = False
    coll.hide_render = False
    coll.hide_viewport = False
    return {"found": True, "was_excluded": was_excluded,
            "n_dist_roots": sum(1 for o in coll.all_objects
                                if o.name.startswith(dpool.DIST_OBJ_PREFIX)
                                and (o.parent is None
                                     or not o.parent.name.startswith(dpool.DIST_OBJ_PREFIX)))}


# ---------------------------------------------------------------------------
# Pallet
# ---------------------------------------------------------------------------
def _select_and_place_pallet(pallet_type, translate):
    """Show `pallet_type` (hide the others), normalise its scale, and ground it at the
    (translated) world origin with yaw=0 — the pose solve_placement assumed."""
    from pallet_geometry import get_normalized_scale
    initialize_pallet_assets()
    pobj = get_obj(pallet_type)
    if pobj is None or not _has_mesh_children(pobj):
        return None
    for n in cfg.PALLET_NAMES:
        o = get_obj(n)
        if o is not None:
            set_render_visibility(o, n == pallet_type)
    pobj.scale = tuple(get_normalized_scale(pobj, ORIENTATION_OVERRIDES.get(pallet_type, (0, 0, 0))))
    bpy.context.view_layer.update()
    set_object_pose_grounded(pobj, float(translate[0]), float(translate[1]), 0.0,
                             base_rot_deg=ORIENTATION_OVERRIDES.get(pallet_type, (0, 0, 0)),
                             ground_z=0.0)
    bpy.context.view_layer.update()
    return pobj


def _kill_pallet_emission(pallet_obj):
    """Defensive: zero any emission so scene.usd (Pallet_0) can't glow (raw USD ships
    emissive_strength=10000). No-op when already 0. Copied from gen_4pallet_mask to avoid
    importing that heavy module."""
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
                        es.default_value = 0.0
                    if ec is not None:
                        for link in list(ec.links):
                            nt.links.remove(link)
                        ec.default_value = (0.0, 0.0, 0.0, 1.0)
                elif node.type == "EMISSION":
                    s = node.inputs.get("Strength")
                    if s is not None:
                        for link in list(s.links):
                            nt.links.remove(link)
                        s.default_value = 0.0


def _apply_named_variant(pobj, pallet_name, variant_name):
    """Apply the exact material_variant chosen in sample_frame (not a random one).
    Falls back to randomize_pallet_appearance (random) if the name is not found."""
    family = cfg.PALLET_COLOR_GROUP_FOR_MODEL.get(pallet_name, "plastic")
    variants = cfg.PALLET_COLOR_VARIANTS.get(family) or cfg.PALLET_COLOR_VARIANTS.get("plastic", [])
    variant = next((v for v in variants if v["name"] == variant_name), None)
    if variant is None:
        return randomize_pallet_appearance(pobj, pallet_name)
    slots = 0
    for mesh_obj in [pobj, *pobj.children_recursive]:
        if mesh_obj.type != "MESH":
            continue
        materials = mesh_obj.data.materials
        if not materials:
            materials.append(_get_or_create_pallet_variant_material(
                _fallback_material_for_pallet(pallet_name), pallet_name, family, variant))
            slots += 1
            continue
        for idx, cur in enumerate(materials):
            src_name = _material_source_name(cur)
            src = bpy.data.materials.get(src_name) if src_name else None
            src = src or _resolve_material_replacement(cur, pallet_name)
            materials[idx] = _get_or_create_pallet_variant_material(src, pallet_name, family, variant)
            slots += 1
    return {"family": family, "name": variant["name"], "slots_updated": slots}


# ---------------------------------------------------------------------------
# CHECK #3 infra: geometric ground detector + native floor option.
# ---------------------------------------------------------------------------
def _hide_ground_geometric(keep_objs):
    """Hide any large thin slab sitting at z~=0 (a warehouse/native ground) that the
    name-pattern hides miss. Geometry-only test so a NEW background (unknown mesh names)
    is still caught. keep_objs = objects that must stay visible (pallet set, floor plane,
    occluder, cargo, distractors)."""
    keep = set()
    for o in keep_objs:
        if o is None:
            continue
        keep.add(o.name)
        for c in o.children_recursive:
            keep.add(c.name)
    n = 0
    hidden = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render or o.name in keep:
            continue
        amin, amax = get_obj_aabb_world(o)
        ex, ey = amax[0] - amin[0], amax[1] - amin[1]
        ez = amax[2] - amin[2]
        cz = 0.5 * (amax[2] + amin[2])
        if ex > GROUND_XY_MIN and ey > GROUND_XY_MIN and ez < GROUND_Z_THICK_MAX and abs(cz) < GROUND_CZ_TOL:
            o.hide_render = True
            o.hide_viewport = True
            n += 1
            hidden.append(o.name)
    return n, hidden


# ---------------------------------------------------------------------------
# Occluder
# ---------------------------------------------------------------------------
def _place_occluder(occluder, delta):
    """Place the Plan occluder (Dist_<name>) so its world-AABB centre == occ_center + delta
    (delta = the rigid plan->world alignment shift)."""
    if occluder is None:
        return None
    obj = get_obj(occluder["obj_name"])
    if obj is None:
        return None
    s = float(occluder.get("scale", 1.0))
    obj.scale = tuple(v * s for v in obj.scale)
    set_render_visibility(obj, True)
    bpy.context.view_layer.update()
    amin, amax = get_obj_aabb_world(obj)
    cur_center = np.array([(amin[i] + amax[i]) / 2.0 for i in range(3)])
    tgt = np.array(occluder["center"], dtype=np.float64) + np.asarray(delta, dtype=np.float64)
    obj.location = tuple(np.array(obj.location) + (tgt - cur_center))
    bpy.context.view_layer.update()
    return obj


def _hide_distractor_pool(except_name=None, resolve_truncated=False, restore_transforms=False):
    for name in dpool.all_object_names():
        resolved = (
            _resolve_distractor_object_name(name)
            if resolve_truncated
            else name
        )
        if not resolved:
            continue
        if resolved == except_name or name == except_name:
            continue
        o = get_obj(resolved)
        if o is not None:
            if restore_transforms:
                SV2.restore_base_transform(o, visible=False)
            else:
                SV2.ensure_base_transform(o)
            set_render_visibility(o, False)


# ---------------------------------------------------------------------------
# Camera intrinsics
# ---------------------------------------------------------------------------
def _set_camera_intrinsics(scene, W, H, fx, principal_jitter=0.0):
    """Per-frame resolution + focal (fx -> lens_mm) + principal point. Returns per-frame K.

    Intrinsics DR: lens_mm = fx * sensor_width / W (pinhole, sensor_fit HORIZONTAL). fy=fx
    (square pixels). Principal jitter: cx/cy offset realised through camera shift. Sign of
    the shift vs the K-based projection is UNVERIFIED, so principal_jitter defaults 0 (K then
    has cx=W/2, cy=H/2, which the analytic solve also assumed) — enable only after the overlay
    alignment is confirmed in Phase D."""
    scene.render.resolution_x = int(W)
    scene.render.resolution_y = int(H)
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    cam = scene.camera
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = SENSOR_WIDTH
    cam.data.lens = fx * SENSOR_WIDTH / float(W)
    dx = dy = 0.0
    if principal_jitter:
        dx = (principal_jitter * (W / 2.0))
        dy = (principal_jitter * (H / 2.0))
    cx = W / 2.0 + dx
    cy = H / 2.0 + dy
    cam.data.shift_x = -dx / float(W)
    cam.data.shift_y = dy / float(W)
    return np.array([[fx, 0.0, cx], [0.0, fx, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def _aim_camera(scene, cam_pos, cam_look):
    cam = scene.camera
    cam.location = tuple(cam_pos)
    d = mathutils.Vector(tuple(cam_look)) - mathutils.Vector(tuple(cam_pos))
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()


# ---------------------------------------------------------------------------
# Constrained-scene deterministic helpers
# ---------------------------------------------------------------------------
def _seed_stage(seed):
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    try:
        bpy.context.scene.cycles.seed = seed & 0x7FFFFFFF
    except Exception:
        pass


def _resolve_distractor_object_name(name):
    """Resolve Blender's 63-byte-truncated object names deterministically."""
    if not name:
        return None
    exact = get_obj(name)
    if exact is not None:
        return exact.name
    candidates = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.name.startswith(dpool.DIST_OBJ_PREFIX)
        and (str(name).startswith(obj.name) or obj.name.startswith(str(name)))
    )
    return candidates[0] if len(candidates) == 1 else None


def _background_root(background_key):
    item = cfg.BACKGROUND_ASSETS.get(background_key, {})
    return get_obj(item.get("root_name")) if item else None


def _horizontal_support_meshes(background_key, top_z_limit=0.15):
    root = _background_root(background_key)
    if root is None:
        return []
    result = []
    for obj in [root, *root.children_recursive]:
        if obj.type != "MESH" or obj.hide_render:
            continue
        amin, amax = get_obj_aabb_world(obj)
        ex = float(amax[0] - amin[0])
        ey = float(amax[1] - amin[1])
        ez = float(amax[2] - amin[2])
        if ex >= 5.0 and ey >= 5.0 and ez <= 0.20 and float(amax[2]) <= top_z_limit:
            result.append(obj)
    return result


def _anchor_candidate_translations(pallet_obj, seed, background_key, attempts=24):
    rng = random.Random(int(seed))
    current = np.asarray(pallet_obj.location, dtype=np.float64)
    candidates = [np.zeros(3, dtype=np.float64)]
    if background_key == "parking_lot":
        x_bounds, y_bounds = (-12.0, -6.0), (-6.5, -1.5)
    else:
        x_bounds = tuple(float(v) for v in cfg.PALLET_PLACEMENT_X_RANGE)
        y_bounds = tuple(float(v) for v in cfg.PALLET_PLACEMENT_Y_RANGE)
    while len(candidates) < int(attempts):
        target = np.array(
            [
                rng.uniform(*x_bounds),
                rng.uniform(*y_bounds),
                float(current[2]),
            ],
            dtype=np.float64,
        )
        candidates.append(target - current)
    return candidates


def _diagnostic_flags(mode, spec):
    policy = SP2.diagnostic_policy(mode)
    cargo_mode = getattr(policy, "cargo_mode", None)
    if cargo_mode == "off":
        cargo = False
    elif cargo_mode == "force_on":
        cargo = True
    elif cargo_mode == "spec":
        cargo = bool(spec.cargo_on)
    else:
        cargo = bool(policy.include_cargo)
    return {
        "policy": policy,
        "cargo": cargo,
        "context": bool(policy.include_context),
        "explicit": bool(policy.include_explicit_occluder),
    }


def _context_candidate_poses(
    pallet_center,
    camera_pos,
    camera_look,
    K,
    image_wh,
    ground_z,
    seed,
    attempts=18,
):
    return SP2.image_space_context_poses(
        pallet_center=pallet_center,
        camera_pos=camera_pos,
        camera_look=camera_look,
        fx=float(K[0, 0]),
        fy=float(K[1, 1]),
        cx=float(K[0, 2]),
        cy=float(K[1, 2]),
        image_wh=image_wh,
        ground_z=ground_z,
        seed=seed,
        attempts=attempts,
    )


def _anchor_static_los_samples(
    pallet_obj,
    pallet_name,
    cam_pos,
    cam_look,
    K,
    image_wh,
):
    """Build dense front-face and fork-opening samples before anchor translation."""
    geom = get_pallet_geometry(
        pallet_name,
        pallet_obj,
        ORIENTATION_OVERRIDES,
    )
    corners = np.asarray(geom["corners_world"], dtype=np.float64)
    centroid = np.asarray(geom["centroid_world"], dtype=np.float64)
    R, t = build_view_matrix(cam_pos, cam_look, up=(0, 0, 1))
    uv, _ = _project(K, R, t, corners)
    perm, _, _ = compute_perm_v4(
        corners,
        uv,
        cam_pos=np.asarray(cam_pos, dtype=np.float64),
        return_margin=True,
    )
    corners_v4 = corners[perm]
    samples = [centroid, *_bilinear_grid(corners_v4[:4], steps=5)]
    kp12 = compute_efront_kp12(
        pallet_name,
        corners_v4,
        perm,
        K,
        R,
        t,
        image_wh=image_wh,
    )
    if kp12.get("kp12_valid") and kp12.get("kp12_3d") is not None:
        samples.extend(np.asarray(kp12["kp12_3d"], dtype=np.float64)[4:])
    return [np.asarray(sample, dtype=np.float64) for sample in samples]


def _pair_key(a, b):
    return tuple(sorted((a.name, b.name)))


def _forbidden_collision_pairs(
    pallet,
    support_objects,
    static_objects,
    cargo,
    context,
    explicit,
):
    return SP2.forbidden_collision_pairs(
        {
            SP2.ROLE_PALLET: [] if pallet is None else [pallet],
            SP2.ROLE_SUPPORT: support_objects,
            SP2.ROLE_STATIC_BACKGROUND: static_objects,
            SP2.ROLE_CARGO: cargo,
            SP2.ROLE_CONTEXT: context,
            SP2.ROLE_EXPLICIT_OCCLUDER: (
                [] if explicit is None else [explicit]
            ),
        }
    )


# ---------------------------------------------------------------------------
# REALIZE
# ---------------------------------------------------------------------------
def realize(plan, translate=(0.0, 0.0, 0.0), floor_mode=None, principal_jitter=0.0,
            place_occluder=True, placement_mode="legacy", diagnostic_mode=None,
            frame_seed=None):
    """Build a concrete Blender scene from a solved Plan. Returns a RealizedScene dict that
    measure()/render()/label() consume. `translate` shifts the whole (origin-based) plan to a
    clear world spot (pallet stays grounded, camera+occluder shift with it)."""
    if placement_mode not in {"legacy", "constrained"}:
        raise ValueError("placement_mode must be 'legacy' or 'constrained'")
    if placement_mode == "constrained":
        if diagnostic_mode is None:
            raise ValueError("diagnostic_mode is required for constrained placement")
        if frame_seed is None:
            raise ValueError("frame_seed is required for constrained placement")
        return _realize_constrained(
            plan,
            translate=translate,
            floor_mode=floor_mode,
            principal_jitter=principal_jitter,
            place_occluder=place_occluder,
            diagnostic_mode=diagnostic_mode,
            frame_seed=frame_seed,
        )

    spec = plan.spec
    scene = bpy.context.scene
    setup_render()
    scene.render.engine = "CYCLES"
    scene.cycles.use_denoising = True
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass

    # (CHECK 1) force the distractor collection render-enabled BEFORE anything else.
    dist_info = force_distractors_v2_enabled()

    W, H = spec.resolution
    K = _set_camera_intrinsics(scene, W, H, float(spec.fx), principal_jitter=principal_jitter)

    # pallet at (translated) origin, yaw=0, exact material variant.
    pobj = _select_and_place_pallet(spec.pallet_type, translate)
    if pobj is None:
        return None
    mat = _apply_named_variant(pobj, spec.pallet_type, spec.material_variant)
    _kill_pallet_emission(pobj)
    geom0 = get_pallet_geometry(spec.pallet_type, pobj, ORIENTATION_OVERRIDES)
    centroid0 = np.asarray(geom0["centroid_world"], dtype=np.float64)
    pallet_pos = tuple(centroid0)
    # RIGID plan->world alignment: solve_placement defined the camera relative to the pallet
    # CENTROID at [0,0,H/2]. The USD pallet's OBJECT ORIGIN is offset from its geometric
    # centroid, so placing the origin at the world origin leaves the centroid off — which
    # tilts the realised elevation/azimuth away from the target. delta re-aligns camera +
    # occluder to the actual centroid so realised geometry matches the plan.
    from blender_config import TARGET_CANONICAL_DIMS
    p_center_plan = np.array([0.0, 0.0, float(TARGET_CANONICAL_DIMS[1]) / 2.0])
    delta = centroid0 - p_center_plan

    # background + illumination + floor.
    bg = randomize_background()
    randomize_hdri()
    # Illumination DR: exposure_ev as a global EV knob (dark-biased sample from Layer-1).
    try:
        scene.view_settings.exposure = float(spec.exposure_ev)
    except Exception:
        pass
    if floor_mode is None:
        import random as _r
        floor_mode = "native" if _r.random() < NATIVE_FLOOR_PROB else "plane"
    floor_info = None
    if floor_mode == "plane":
        floor_info = randomize_floor(pallet_pos)

    # camera per plan, rigidly aligned to the actual pallet centroid.
    cam_pos = list(np.array(plan.cam_pos) + delta)
    cam_look = list(np.array(plan.cam_look) + delta)
    _aim_camera(scene, cam_pos, cam_look)

    # cargo.
    n_cargo = 0
    if spec.cargo_on:
        n_cargo = randomize_boxes(pobj, spec.pallet_type, occlusion_target="light", target_box_count=2)
    else:
        randomize_boxes(pobj, spec.pallet_type, occlusion_target="light", target_box_count=0)
    cargo_objs = [get_obj(n) for n in cfg.BOX_NAMES
                  if get_obj(n) is not None and not get_obj(n).hide_render]

    # occluder (targeted): hide the whole pool, then show + place the chosen one.
    occ_obj = None
    if place_occluder and plan.occluder is not None:
        _hide_distractor_pool(except_name=plan.occluder["obj_name"])
        occ_obj = _place_occluder(plan.occluder, delta)
    else:
        _hide_distractor_pool()

    # (CHECK 3) geometric ground hide (after bg shown) — catches non-name-matching grounds.
    keep = [pobj, get_obj("FloorRandPlane"), occ_obj, *cargo_objs]
    ground_hidden = _hide_ground_geometric(keep)
    bpy.context.view_layer.update()

    return {
        "spec": spec, "plan": plan, "scene": scene, "pallet": pobj,
        "pallet_name": spec.pallet_type, "cam_pos": cam_pos, "cam_look": cam_look,
        "K": K, "W": int(W), "H": int(H), "translate": tuple(translate),
        "occluder": occ_obj, "cargo": cargo_objs, "n_cargo": n_cargo,
        "material_variant_actual": (mat or {}).get("name"),
        "background": bg, "floor_mode": floor_mode, "floor_info": floor_info,
        "dist_info": dist_info, "ground_hidden": ground_hidden,
        "exposure_ev": float(spec.exposure_ev),
    }


def _realize_constrained(
    plan,
    translate,
    floor_mode,
    principal_jitter,
    place_occluder,
    diagnostic_mode,
    frame_seed,
):
    """Blender-side constrained assembly used only by the diagnostic runner."""
    spec = plan.spec
    scene = bpy.context.scene
    stage_t0 = time.perf_counter()
    stage_runtime = {}
    stage_seeds = SP2.derive_stage_seeds(int(frame_seed))
    flags = _diagnostic_flags(diagnostic_mode, spec)

    # Warm lazy caches before applying the per-frame seed.  Otherwise the first
    # frame of a fresh Blender process can consume a different random sequence
    # than the same frame rendered later in a chunk.
    randomizers.initialize_backgrounds()
    _prepare_constrained_hdri_pool()

    setup_render()
    scene.render.engine = "CYCLES"
    scene.cycles.use_denoising = True
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass
    dist_info = force_distractors_v2_enabled()
    W, H = spec.resolution
    K = _set_camera_intrinsics(
        scene,
        W,
        H,
        float(spec.fx),
        principal_jitter=principal_jitter,
    )
    lowres96 = SP2.aspect_preserving_lowres_size(W, H, base_height=96)
    lowres128 = SP2.aspect_preserving_lowres_size(W, H, base_height=128)
    lowres96_area = int(lowres96[0]) * int(lowres96[1])
    lowres128_long_edge = float(max(lowres128))
    lowres_render_count_start = _LOWRES_RENDER_COUNT

    # Background/floor policy is selected before the target is assembled.
    _seed_stage(stage_seeds["background"])
    background = randomize_background()
    randomize_hdri()
    try:
        scene.view_settings.exposure = float(spec.exposure_ev)
    except Exception:
        pass
    floor_mode_requested = floor_mode
    if floor_mode is None:
        floor_mode = (
            "native"
            if random.Random(stage_seeds["background"] ^ 0xF100).random()
            < NATIVE_FLOOR_PROB
            else "plane"
        )
    floor_fallback_reason = None
    if (
        floor_mode_requested is None
        and floor_mode == "native"
        and not _horizontal_support_meshes(background)
    ):
        floor_mode = "plane"
        floor_fallback_reason = "selected_background_has_no_horizontal_native_support"
    stage_runtime["background"] = time.perf_counter() - stage_t0

    # Reset every dynamic object before static inventory is collected.
    _hide_distractor_pool(resolve_truncated=True, restore_transforms=True)
    pobj = _select_and_place_pallet(spec.pallet_type, translate)
    if pobj is None:
        return {
            "realize_ok": False,
            "constrained_metrics": {
                "failure_reason": "missing_pallet",
                "stage_runtime_s": stage_runtime,
            },
        }
    randomize_boxes(
        pobj,
        spec.pallet_type,
        occlusion_target="light",
        target_box_count=0,
    )
    wood_texture_dir = getattr(randomizers, "WOOD_TEXTURE_DIR", None)
    if not wood_texture_dir or not os.path.isfile(
        os.path.join(wood_texture_dir, "wood_planks_diff.png")
    ):
        # Registry-resolved (config/synthetic/pallet_paths.yaml). Was a hardcoded
        # `data/pallet/archive/textures_wood` join; Stage 2-B moved it to
        # assets/materials/pallet/textures_wood and the registry owns that fact.
        archive_wood_dir = cfg.PALLET_PATHS.get("pallet_material_root")
        if os.path.isfile(
            os.path.join(archive_wood_dir, "wood_planks_diff.png")
        ):
            randomizers.WOOD_TEXTURE_DIR = archive_wood_dir
            wood_texture_dir = archive_wood_dir
    mat = _apply_named_variant(pobj, spec.pallet_type, spec.material_variant)
    _kill_pallet_emission(pobj)
    SV2.register_role(pobj, SV2.ROLE_PALLET, recursive=True)

    geom0 = get_pallet_geometry(spec.pallet_type, pobj, ORIENTATION_OVERRIDES)
    centroid0 = np.asarray(geom0["centroid_world"], dtype=np.float64)
    from blender_config import TARGET_CANONICAL_DIMS

    p_center_plan = np.array(
        [0.0, 0.0, float(TARGET_CANONICAL_DIMS[1]) / 2.0],
        dtype=np.float64,
    )
    plan_alignment = centroid0 - p_center_plan
    cam0 = np.asarray(plan.cam_pos, dtype=np.float64) + plan_alignment
    look0 = np.asarray(plan.cam_look, dtype=np.float64) + plan_alignment

    floor_info = None
    floor_obj = get_obj(cfg.FLOOR_PLANE_NAME)
    floor_texture_dir = getattr(randomizers, "FLOOR_TEXTURE_DIR", None)
    if floor_mode == "plane":
        probe_name = cfg.FLOOR_CANDIDATES[0] + "_diff.png"
        if not floor_texture_dir or not os.path.isfile(
            os.path.join(floor_texture_dir, probe_name)
        ):
            # Registry-resolved (config/synthetic/pallet_paths.yaml).
            archive_floor_dir = cfg.PALLET_PATHS.get("floor_material_root")
            if os.path.isfile(os.path.join(archive_floor_dir, probe_name)):
                randomizers.FLOOR_TEXTURE_DIR = archive_floor_dir
                floor_texture_dir = archive_floor_dir
    _seed_stage(stage_seeds["background"] ^ 0xF10A)
    if floor_mode == "plane":
        # randomize_background() recursively re-shows the chosen hierarchy.
        # The legacy floor helper caches this hide operation, so force it to
        # re-apply on every constrained plane frame to prevent cross-frame
        # grating/fence state leakage into the anchor inventory.
        if hasattr(randomizers, "_floor_grating_hidden"):
            randomizers._floor_grating_hidden = False
        floor_info = randomize_floor(tuple(centroid0))
        floor_obj = get_obj(cfg.FLOOR_PLANE_NAME)
        ground_hidden = _hide_ground_geometric([pobj, floor_obj])
    else:
        if floor_obj is not None:
            set_render_visibility(floor_obj, False)
        ground_hidden = (0, [])
    if floor_obj is not None and floor_mode == "plane":
        SV2.register_role(floor_obj, SV2.ROLE_SUPPORT, recursive=True)

    native_support = (
        _horizontal_support_meshes(background) if floor_mode == "native" else []
    )
    inventory = SV2.collect_visible_static_inventory(
        support_names=native_support,
        floor_obj=floor_obj if floor_mode == "plane" else None,
        exclude_objects=[pobj, *[get_obj(n) for n in cfg.BOX_NAMES]],
    )
    support_objects = inventory["support_objects"]
    static_objects = inventory["static_obstacle_objects"]
    for obj in static_objects:
        SV2.register_role(obj, SV2.ROLE_STATIC_BACKGROUND, recursive=False)

    anchor_t0 = time.perf_counter()
    _seed_stage(stage_seeds["anchor"])
    anchor_candidates = _anchor_candidate_translations(
        pobj,
        stage_seeds["anchor"],
        background,
        attempts=max(24, int(cfg.PALLET_PLACEMENT_ATTEMPTS)),
    )
    static_los_samples = _anchor_static_los_samples(
        pobj,
        spec.pallet_type,
        cam0,
        look0,
        K,
        (int(W), int(H)),
    )
    anchor = SV2.solve_pallet_anchor(
        pobj,
        cam_pos=cam0,
        cam_look=look0,
        floor_mode=floor_mode,
        floor_obj=floor_obj if floor_mode == "plane" else None,
        seed=stage_seeds["anchor"],
        attempts=len(anchor_candidates),
        static_inventory=inventory,
        candidate_translations=anchor_candidates,
        floor_z=float(cfg.FLOOR_PLANE_Z if floor_mode == "plane" else 0.0),
        support_height_tolerance=0.015,
        broad_aabb_inflate=0.05,
        camera_clearance=SP2.camera_clearance_for_role(
            SP2.ROLE_STATIC_BACKGROUND
        ),
        support_camera_clearance=SP2.camera_clearance_for_role(
            SP2.ROLE_SUPPORT
        ),
        camera_clearance_exact=True,
        camera_obj=scene.camera,
        pallet_name=spec.pallet_type,
        orientation_overrides=ORIENTATION_OVERRIDES,
        static_los_samples=static_los_samples,
    )
    stage_runtime["anchor"] = time.perf_counter() - anchor_t0
    if not anchor["success"]:
        last_failure = anchor.get("last_failure") or {}
        return {
            "realize_ok": False,
            "constrained_metrics": {
                "failure_reason": "anchor_fail",
                "background_asset": background,
                "anchor_translation": None,
                "anchor_attempts": len(anchor.get("attempt_log", [])),
                "anchor_reject_reason": last_failure.get("reason"),
                "anchor_reject_counts_by_reason": anchor.get("reject_counts", {}),
                "anchor_last_failure": last_failure,
                "support_surface_name": None,
                "min_camera_clearance": (
                    (last_failure.get("camera_clearance") or {}).get(
                        "min_clearance"
                    )
                ),
                "support_pass": bool(last_failure.get("support_ok", False)),
                "static_collision_pass": not bool(
                    last_failure.get("exact_hits")
                    or last_failure.get("clearance_hits")
                ),
                "static_los_pass": bool(last_failure.get("los_ok", False)),
                "floor_mode_requested": floor_mode_requested,
                "floor_mode_actual": floor_mode,
                "floor_fallback_reason": floor_fallback_reason,
                "floor_texture_dir": floor_texture_dir,
                "wood_texture_dir": wood_texture_dir,
                "stage_runtime_s": stage_runtime,
            },
        }

    accepted_anchor = anchor["accepted"]
    procedural_support_shift = SP2.procedural_support_shift(
        floor_mode,
        accepted_anchor["translation"],
    )
    if (
        floor_obj is not None
        and any(abs(value) > 1e-12 for value in procedural_support_shift)
    ):
        floor_obj.location = floor_obj.location + mathutils.Vector(
            procedural_support_shift
        )
        bpy.context.view_layer.update()
    cam_pos = list(accepted_anchor["cam_pos"])
    cam_look = list(accepted_anchor["cam_look"])
    _aim_camera(scene, cam_pos, cam_look)
    support_names = [
        row.get("support")
        for row in accepted_anchor["support"]["samples"]
        if row.get("support")
    ]
    support_surface_name = support_names[0] if support_names else (
        floor_obj.name if floor_obj is not None and floor_mode == "plane" else None
    )
    support_z_values = [
        float(row["support_z"])
        for row in accepted_anchor["support"]["samples"]
        if row.get("support_z") is not None
    ]
    dynamic_ground_z = (
        float(np.median(support_z_values))
        if support_z_values
        else float(cfg.FLOOR_PLANE_Z if floor_mode == "plane" else 0.0)
    )
    support_ray_start_z = max(
        dynamic_ground_z + 4.0,
        float(object_top_z_world(pobj)) + 3.0,
    )

    # Cargo is a deterministic top-surface pack with a low-resolution occlusion
    # budget; failed cargo is removed rather than accepted as floating/penetrating.
    cargo_t0 = time.perf_counter()
    _seed_stage(stage_seeds["cargo"])
    for box_name in cfg.BOX_NAMES:
        box = get_obj(box_name)
        if box is not None:
            try:
                randomizers._reset_box_scale(box)
            except Exception:
                pass
            set_render_visibility(box, False)
    pre_cargo_corner_reserve = None
    enforce_explicit_corner_reserve = False
    if flags["explicit"]:
        pre_cargo_corner_reserve = _candidate_corner_gate_metrics(
            scene,
            cam_pos,
            cam_look,
            pobj,
            spec.pallet_type,
            K,
            int(W),
            int(H),
        )
        enforce_explicit_corner_reserve = SP2.explicit_corner_reserve_pass(
            pre_cargo_corner_reserve
        )
    cargo_requested = 2 if flags["cargo"] else 0
    cargo_result = {
        "placed_objects": [],
        "placed_names": [],
        "metrics": {
            "success": cargo_requested == 0,
            "requested": cargo_requested,
            "placed": 0,
            "reject_counts": {},
            "placements": [],
        },
    }
    if cargo_requested:
        box_names = [name for name in cfg.BOX_NAMES if get_obj(name) is not None]
        random.Random(stage_seeds["cargo"]).shuffle(box_names)
        cargo_result = SV2.pack_cargo_top_surface(
            pobj,
            box_names=box_names,
            count=cargo_requested,
            seed=stage_seeds["cargo"],
            camera_pos=cam_pos,
            static_objects=static_objects,
            candidate_uvs=[
                (-0.36, -0.36), (0.0, -0.36), (0.36, -0.36),
                (-0.36, 0.0), (0.36, 0.0),
                (-0.36, 0.36), (0.0, 0.36), (0.36, 0.36),
                (0.0, 0.0),
            ],
            yaw_options=(0.0, math.pi / 2.0),
            footprint_margin=0.015,
            contact_tolerance=0.01,
            broad_aabb_inflate=0.0,
            pallet_name=spec.pallet_type,
            orientation_overrides=ORIENTATION_OVERRIDES,
        )
    cargo_objs = list(cargo_result["placed_objects"])
    cargo_attempts = (
        sum(cargo_result["metrics"].get("reject_counts", {}).values())
        + len(cargo_objs)
    )
    cargo_lowres = {"f_cargo": 0.0}
    if cargo_requested:
        cargo_lowres = _lowres_stage_areas(
            scene,
            pobj,
            cargo_objs,
            [],
            None,
            token=f"{frame_seed}_cargo",
            size=lowres96,
        )
        while cargo_objs and cargo_lowres["f_cargo"] > 0.25:
            removed = cargo_objs.pop()
            set_render_visibility(removed, False)
            cargo_lowres = _lowres_stage_areas(
                scene,
                pobj,
                cargo_objs,
                [],
                None,
                token=f"{frame_seed}_cargo_trim_{len(cargo_objs)}",
                size=lowres96,
            )
    cargo_corner_reserve = None
    if flags["explicit"]:
        cargo_corner_reserve = _candidate_corner_gate_metrics(
            scene,
            cam_pos,
            cam_look,
            pobj,
            spec.pallet_type,
            K,
            int(W),
            int(H),
        )
        while (
            enforce_explicit_corner_reserve
            and
            cargo_objs
            and not SP2.explicit_corner_reserve_pass(cargo_corner_reserve)
        ):
            removed = cargo_objs.pop()
            set_render_visibility(removed, False)
            reject_counts = cargo_result["metrics"].setdefault(
                "reject_counts",
                {},
            )
            reject_counts["explicit_corner_reserve"] = (
                int(reject_counts.get("explicit_corner_reserve", 0)) + 1
            )
            cargo_lowres = _lowres_stage_areas(
                scene,
                pobj,
                cargo_objs,
                [],
                None,
                token=f"{frame_seed}_cargo_corner_trim_{len(cargo_objs)}",
                size=lowres96,
            )
            cargo_corner_reserve = _candidate_corner_gate_metrics(
                scene,
                cam_pos,
                cam_look,
                pobj,
                spec.pallet_type,
                K,
                int(W),
                int(H),
            )
    cargo_visibility = _measure_front_opening_visibility(
        {
            "scene": scene,
            "pallet": pobj,
            "pallet_name": spec.pallet_type,
            "cam_pos": cam_pos,
            "cam_look": cam_look,
            "K": K,
            "W": int(W),
            "H": int(H),
        }
    )
    # CARGO 자체의 화면 가시성.  front/left/right_visibility_after_cargo 는 "팔레트가
    # 가려졌는가"이지 "cargo 가 보이는가"가 아니고, public mask 는 팔레트 전용이라
    # 그것으로도 추론할 수 없다.  context 와 똑같은 저해상도 holdout 을 쓰고 저장하지
    # 않는다 (임시 PNG 는 _lowres_holdout 이 지운다).
    cargo_visible_union = 0
    cargo_visible_count = 0
    if cargo_objs:
        cargo_visible_union, _ = _lowres_holdout(
            scene,
            pobj,
            only_white=cargo_objs,
            token=f"{frame_seed}_cargo_union",
            size=lowres96,
        )
        for cargo_idx, cargo_obj in enumerate(cargo_objs):
            cargo_px, _ = _lowres_holdout(
                scene,
                pobj,
                only_white=cargo_obj,
                token=f"{frame_seed}_cargo_visible_{cargo_idx}",
                size=lowres96,
            )
            cargo_visible_count += int(cargo_px >= 8)
    cargo_visible_ratio = float(cargo_visible_union) / float(lowres96_area)
    stage_runtime["cargo"] = time.perf_counter() - cargo_t0

    # EXPLICIT FIRST (2026-08-01).  controlled-occlusion 에서 explicit 탐색이
    # 실패하면 그 앞에서 배치한 context 비용이 통째로 낭비된다 (baseline: 실패
    # 프레임의 context 단계 median 21초).  그래서 순서를 바꿨다 —
    #   proposal 해석/공간 reserve -> explicit 탐색 -> (성공 시) context 배치.
    # explicit 이 꺼진 mode 에서는 아래 블록이 통째로 no-op 이므로 순서 변경의
    # 영향이 없다.
    explicit_prep_t0 = time.perf_counter()
    explicit_proposals = []
    explicit_proposal_dimension_rejects = []
    explicit_proposal_dimension_normalizations = []
    if flags["explicit"] and place_occluder and plan.occluder is not None:
        raw_proposals = [
            plan.occluder,
            *(plan.occluder.get("diagnostic_resample_proposals") or []),
        ]
        seen_proposal_objects = set()
        for proposal_idx, raw_proposal in enumerate(raw_proposals):
            proposal = dict(raw_proposal)
            resolved_name = _resolve_distractor_object_name(
                proposal.get("obj_name")
            )
            if resolved_name in seen_proposal_objects:
                continue
            if resolved_name is not None:
                resolved_obj = get_obj(resolved_name)
                if resolved_obj is not None:
                    base_transform = SV2.ensure_base_transform(resolved_obj)
                    dimension_transform_state = {
                        "location": [
                            float(value) for value in resolved_obj.location
                        ],
                        "rotation_euler": [
                            float(value) for value in resolved_obj.rotation_euler
                        ],
                        "scale": [
                            float(value) for value in resolved_obj.scale
                        ],
                        "base_transform": base_transform,
                    }
                    actual_min, actual_max = SV2.fresh_world_aabb(
                        resolved_obj
                    )
                    dimension_report = SP2.validate_occluder_dimensions(
                        proposal["bbox_m"],
                        [
                            float(actual_max[axis] - actual_min[axis])
                            for axis in range(3)
                        ],
                    )
                    proposal["dimension_validation"] = dimension_report
                    if not dimension_report["valid"]:
                        if dimension_report["uniformly_rescalable"]:
                            original_scale = float(proposal.get("scale", 1.0))
                            normalization_scale = float(
                                dimension_report["normalization_scale"]
                            )
                            proposal["scale"] = (
                                original_scale * normalization_scale
                            )
                            proposal["dimension_scale_before_normalization"] = (
                                original_scale
                            )
                            proposal["dimension_normalization_scale"] = (
                                normalization_scale
                            )
                            explicit_proposal_dimension_normalizations.append(
                                {
                                    "proposal_index": int(proposal_idx),
                                    "proposal_object": resolved_name,
                                    "reason": "manifest_uniform_scale_normalized",
                                    "sampled_scale": original_scale,
                                    "normalization_scale": normalization_scale,
                                    "effective_scale": float(proposal["scale"]),
                                    "dimension_validation": dimension_report,
                                    "dimension_transform_state": (
                                        dimension_transform_state
                                    ),
                                }
                            )
                        else:
                            explicit_proposal_dimension_rejects.append(
                                {
                                    "proposal_index": int(proposal_idx),
                                    "proposal_object": resolved_name,
                                    "reason": "manifest_dimension_mismatch",
                                    "dimension_validation": dimension_report,
                                    "dimension_transform_state": (
                                        dimension_transform_state
                                    ),
                                }
                            )
                            continue
                seen_proposal_objects.add(resolved_name)
            proposal["resolved_obj_name"] = resolved_name
            proposal["diagnostic_proposal_index"] = int(proposal_idx)
            explicit_proposals.append(proposal)
    explicit_proposals = SP2.order_explicit_proposals_for_search(
        explicit_proposals,
        target_fraction=(
            float(spec.f_target) if flags["explicit"] else 0.0
        ),
        target_side=(
            (plan.occluder or {}).get("side")
            if plan.occluder is not None
            else None
        ),
    )
    explicit_name = (
        explicit_proposals[0].get("resolved_obj_name")
        if explicit_proposals
        else None
    )
    explicit_candidate_names = {
        proposal["resolved_obj_name"]
        for proposal in explicit_proposals
        if proposal.get("resolved_obj_name") is not None
    }
    rigid_shift = np.asarray(cam_pos) - np.asarray(plan.cam_pos)
    explicit_reservation_objects = []
    explicit_reservations = []
    explicit_swept_reservations = []
    for search_idx, proposal in enumerate(explicit_proposals):
        proposal_name = proposal.get("resolved_obj_name")
        proposal_obj = get_obj(proposal_name) if proposal_name else None
        if proposal_obj is None:
            continue
        reservation_plan = SP2.translated_explicit_proposal(
            proposal,
            rigid_shift,
        )
        reservation_plan["obj_name"] = proposal_name
        reservation = SV2.place_initial_explicit_occluder(
            proposal_obj,
            plan=reservation_plan,
            visible=True,
            ground_z=dynamic_ground_z,
        )
        # Blender does not reliably refresh hidden child matrices after moving
        # an EMPTY hierarchy, so place it visible first and hide only afterward.
        set_render_visibility(proposal_obj, False)
        reservation_min, reservation_max = SV2.fresh_world_aabb(proposal_obj)
        explicit_reservation_objects.append(proposal_obj)
        reservation_record = {
            "proposal_object": proposal_name,
            "center": reservation["center"],
            "aabb_min": [float(value) for value in reservation_min],
            "aabb_max": [float(value) for value in reservation_max],
        }
        explicit_reservations.append(reservation_record)
        if search_idx == 0:
            swept = SP2.explicit_swept_reservation_aabb(
                reservation_min,
                reservation_max,
                horizontal_margin_m=1.5,
            )
            swept["proposal_object"] = proposal_name
            explicit_swept_reservations.append(swept)
    stage_runtime["explicit_prep"] = (
        time.perf_counter() - explicit_prep_t0
    )
    # The pure-solver pose is only the initial proposal.  A bounded, deterministic
    # low-resolution mask search selects the final collision-free placement.
    explicit_t0 = time.perf_counter()
    _seed_stage(stage_seeds["occluder"])
    occ_obj = None
    explicit_search = None
    explicit_solver_fail = None
    explicit_visible_pixels = 0
    explicit_side_actual = None
    explicit_target_mask_stats = None
    explicit_actual_mask_stats = None
    explicit_target = float(spec.f_target) if flags["explicit"] else 0.0
    explicit_actual = 0.0
    explicit_error = abs(explicit_target - explicit_actual)
    explicit_feedback_depth_step = None
    if flags["explicit"] and place_occluder and plan.occluder is not None:
        resolved_proposals = [
            proposal
            for proposal in explicit_proposals
            if proposal.get("resolved_obj_name") is not None
        ]
        if not resolved_proposals:
            explicit_solver_fail = "planned_occluder_object_missing"
        else:
            explicit_objects = [
                get_obj(proposal["resolved_obj_name"])
                for proposal in resolved_proposals
            ]
            explicit_objects = [obj for obj in explicit_objects if obj is not None]
            for obj in explicit_objects:
                set_render_visibility(obj, False)

            # context 는 아직 배치 전이다 -> explicit 기여분만 고립해서 잰다.
            explicit_baseline = _lowres_stage_areas(
                scene,
                pobj,
                cargo_objs,
                [],
                None,
                token=f"{frame_seed}_explicit_base",
                size=lowres128,
            )
            _, explicit_before_mask = _lowres_holdout(
                scene,
                pobj,
                extra_hide=explicit_objects,
                token=f"{frame_seed}_explicit_before",
                size=lowres128,
            )
            target_rows, target_cols = np.nonzero(
                explicit_before_mask > 127
            )
            explicit_target_mask_stats = SP2.mask_index_stats(
                target_rows,
                target_cols,
                height=explicit_before_mask.shape[0],
                width=explicit_before_mask.shape[1],
            )
            score_counter = {"count": 0}
            aggregate_rejects = {}
            aggregate_log = []
            search_runs = []
            initial_proposals = []
            global_best = None
            schedule = SP2.explicit_search_schedule()
            explicit_feedback_depth_step = (
                SP2.optical_depth_step_for_ground(
                    cam_pos,
                    cam_look,
                    ground_step=0.10,
                )
            )

            def merge_search_result(
                result,
                proposal_idx,
                proposal_name,
                stage_name,
            ):
                for reason, count in result.get("reject_counts", {}).items():
                    aggregate_rejects[reason] = (
                        aggregate_rejects.get(reason, 0) + int(count)
                    )
                for candidate in result.get("candidate_log", []):
                    score_metrics = candidate.get("score_callback") or {}
                    support = candidate.get("support") or {}
                    clearance = candidate.get("camera_clearance") or {}
                    aggregate_log.append(
                        {
                            "proposal_index": int(proposal_idx),
                            "proposal_object": proposal_name,
                            "stage": stage_name,
                            "idx": candidate.get("idx"),
                            "u_offset": candidate.get("u_offset"),
                            "v_offset": candidate.get("v_offset"),
                            "depth_offset": candidate.get("depth_offset"),
                            "yaw_offset": candidate.get("yaw_offset"),
                            "center": candidate.get("center"),
                            "yaw_rad": candidate.get("yaw_rad"),
                            "reason": candidate.get("reason"),
                            "collision_object": candidate.get(
                                "collision_object"
                            ),
                            "support_reason": support.get("reason"),
                            "support_hit_objects": list(
                                SP2.support_hit_objects(support)
                            ),
                            "support_error": candidate.get("support_error"),
                            "camera_clearance_ok": clearance.get("ok"),
                            "camera_clearance_min": clearance.get(
                                "min_clearance"
                            ),
                            "camera_clearance_object": clearance.get(
                                "min_object"
                            ),
                            "score": candidate.get("score"),
                            "score_accept": score_metrics.get("accept"),
                            "f_explicit_actual": score_metrics.get(
                                "f_explicit_actual"
                            ),
                            "abs_error": score_metrics.get("abs_error"),
                            "target_error_ok": score_metrics.get(
                                "target_error_ok"
                            ),
                            "roi_penalty": score_metrics.get("roi_penalty"),
                            "roi_score_weight": score_metrics.get(
                                "roi_score_weight"
                            ),
                            "corner_gate_penalty": score_metrics.get(
                                "corner_gate_penalty"
                            ),
                            "candidate_corner_occlusion_fractions": (
                                score_metrics.get(
                                    "candidate_corner_occlusion_fractions"
                                )
                            ),
                            "candidate_ext_occ_corners": score_metrics.get(
                                "candidate_ext_occ_corners"
                            ),
                            "candidate_V_inframe": score_metrics.get(
                                "candidate_V_inframe"
                            ),
                            "candidate_V_vis": score_metrics.get(
                                "candidate_V_vis"
                            ),
                            "candidate_G1_pass": score_metrics.get(
                                "candidate_G1_pass"
                            ),
                            "candidate_G2_pass": score_metrics.get(
                                "candidate_G2_pass"
                            ),
                            "front_face_visibility": score_metrics.get(
                                "front_face_visibility"
                            ),
                            "left_opening_visibility": score_metrics.get(
                                "left_opening_visibility"
                            ),
                            "right_opening_visibility": score_metrics.get(
                                "right_opening_visibility"
                            ),
                            "opening_visibility_reason": score_metrics.get(
                                "opening_visibility_reason"
                            ),
                            "object_screen_gap_px": score_metrics.get(
                                "object_screen_gap_px"
                            ),
                            "object_screen_penalty": score_metrics.get(
                                "object_screen_penalty"
                            ),
                            "object_visibility_penalty": score_metrics.get(
                                "object_visibility_penalty"
                            ),
                            "occluder_side_target": score_metrics.get(
                                "occluder_side_target"
                            ),
                            "occluder_side_actual": score_metrics.get(
                                "occluder_side_actual"
                            ),
                            "occluder_side_match": score_metrics.get(
                                "occluder_side_match"
                            ),
                            "object_visible_pixels": score_metrics.get(
                                "object_visible_pixels"
                            ),
                            "object_visible_bbox_px": score_metrics.get(
                                "object_visible_bbox_px"
                            ),
                            "object_visible_centroid_px": score_metrics.get(
                                "object_visible_centroid_px"
                            ),
                            "object_amodal_pixels": score_metrics.get(
                                "object_amodal_pixels"
                            ),
                            "object_amodal_bbox_px": score_metrics.get(
                                "object_amodal_bbox_px"
                            ),
                            "object_amodal_centroid_px": score_metrics.get(
                                "object_amodal_centroid_px"
                            ),
                            "object_projected_bbox_px": score_metrics.get(
                                "object_projected_bbox_px"
                            ),
                            "object_projected_centroid_px": score_metrics.get(
                                "object_projected_centroid_px"
                            ),
                        }
                    )
                initial_proposals.append(
                    {
                        "proposal_index": int(proposal_idx),
                        "proposal_object": proposal_name,
                        "stage": stage_name,
                        "initial": result.get("initial"),
                    }
                )
                search_runs.append(
                    {
                        "proposal_index": int(proposal_idx),
                        "proposal_object": proposal_name,
                        "stage": stage_name,
                        "success": bool(result.get("success")),
                        "candidates": int(result.get("candidates", 0)),
                        "reject_counts": dict(
                            result.get("reject_counts", {})
                        ),
                        "best_score": (
                            (result.get("best") or {}).get("score")
                        ),
                        "best_abs_error": (
                            (
                                (result.get("best") or {}).get(
                                    "score_callback"
                                )
                                or {}
                            ).get("abs_error")
                        ),
                        "best_rejected_score": (
                            (result.get("best_rejected") or {}).get(
                                "score"
                            )
                        ),
                        "best_rejected_screen_gap_px": (
                            (
                                (
                                    result.get("best_rejected") or {}
                                ).get("score_callback")
                                or {}
                            ).get("object_screen_gap_px")
                        ),
                    }
                )

            def remember_current_best(
                result,
                obj,
                proposal,
                stage_name,
            ):
                nonlocal global_best
                if not result.get("success"):
                    return
                record = result.get("best")
                if record is None:
                    return
                candidate = {
                    "score": float(record["score"]),
                    "record": record,
                    "object_name": obj.name,
                    "proposal": dict(proposal),
                    "stage": stage_name,
                    "location": obj.location.copy(),
                    "rotation": obj.rotation_euler.copy(),
                    "scale": obj.scale.copy(),
                }
                if (
                    global_best is None
                    or candidate["score"] > global_best["score"]
                ):
                    global_best = candidate

            # §4 탐색 계측.  coarse = 자세를 찾는 단계, fine = 목표 오차를 좁히는 단계.
            FINE_STAGES = ("refine", "feedback", SP2.FINE_STAGE)
            # §9 fine 과 rescue 가 같은 geometry 를 두 번 평가하지 않도록 공유한다.
            rescue_state = {
                "evals": 0, "triggered": False, "won": False,
                "beam_size": 0, "duplicate_skips": 0, "runtime_s": 0.0,
                "axis_sequence": [], "seed_types": [], "categories": [],
                "binding_signatures": [], "constraint_before": None,
                "constraint_after": None, "final_constraint_vector": None,
            }
            evaluated_geometry_keys = set()
            # 평가 前 dedup 용 (plan, offset) 키.  evaluated_geometry_keys 는 평가
            # 결과(center)가 있어야 만들 수 있어 constraint-rescue 에서만 쓸 수 있다.
            evaluated_offset_keys = set()
            fine_state = {
                "evals": 0, "triggered": False, "trigger_reason": None,
                "source_stage": None, "source_score": None,
                "margin_before": None, "best_score": None,
                "margin_after": None, "won": False, "runtime_s": 0.0,
            }
            search_stats = {
                "search_seed_count": 0,
                "coarse_eval_count": 0,
                "fine_eval_count": 0,
                "best_seed_score": None,
                "final_seed_score": None,
                "winning_stage": None,
            }

            def run_search_stage(
                obj,
                proposal,
                proposal_idx,
                stage_name,
                stage_plan,
                candidate_offsets=None,
            ):
                offsets = (
                    schedule[stage_name]["candidates"]
                    if candidate_offsets is None
                    else tuple(candidate_offsets)
                )
                if stage_name in (SP2.FINE_STAGE, SP2.CONSTRAINT_RESCUE_STAGE):
                    # fine / constraint-rescue 는 **일반 예산을 통과하지 않는다** —
                    # 자체 상한만 적용한다.  (일반 예산 검사를 같이 태우면, 예산이
                    #  소진돼 실패한 프레임에서 이 단계가 항상 0개를 평가한다.
                    #  G1.6 의 첫 sweep 이 실제로 그랬다.)
                    if stage_name == SP2.FINE_STAGE:
                        offsets = tuple(offsets)[:max(
                            0, SP2.FINE_MAX_EVALS - fine_state["evals"])]
                    else:
                        offsets = tuple(offsets)[:max(
                            0, int(SEARCH_TUNING["constraint_rescue_eval_max"])
                            - rescue_state["evals"])]
                    if not offsets:
                        return {"success": False, "object": obj.name, "best": None,
                                "best_rejected": None, "reject_counts": {},
                                "candidates": 0, "candidate_log": [],
                                "initial": None}
                else:
                    # 이미 평가한 (plan, offset) 조합은 결과가 같으므로 다시 렌더하지
                    # 않는다.  primary 격자의 (0,0,0) 이 preprobe 와 겹치는 게 대표적
                    # 이고, 실측 후보의 5.2%(primary 11.1% / prealign-primary 20.6%)가
                    # 재평가였다.  **예산 trim 앞에서** 걸러야 빈 자리를 새 후보가 쓴다.
                    offsets, _ = SP2.dedup_candidate_offsets(
                        stage_plan,
                        offsets,
                        evaluated_offset_keys,
                    )
                    # ★ 해석적 seed 단계(target-seed)는 **앞 K개 unique 후보만** 예산에서
                    # 면제된다 (G1.6).  K=None 이면 G1.5 의 무제한 면제와 같다.
                    attempted_for_proposal = SP2.budgeted_attempt_count(
                        aggregate_log,
                        int(proposal_idx),
                        SEARCH_TUNING["target_seed_free_cap"],
                    )
                    offsets = SP2.bounded_candidate_offsets(
                        offsets,
                        attempted=attempted_for_proposal,
                        limit=SP2.EXPLICIT_CANDIDATE_LIMIT_PER_PROPOSAL,
                    )
                    # 예산에 살아남은 것만 기록한다 (잘린 것은 평가되지 않았다).
                    for offset in offsets:
                        evaluated_offset_keys.add(
                            SP2.planned_offset_key(stage_plan, offset))
                if not offsets:
                    result = {
                        "success": False,
                        "object": obj.name,
                        "best": None,
                        "best_rejected": None,
                        "reject_counts": {
                            "candidate_budget_exhausted": 1,
                        },
                        "candidates": 0,
                        "candidate_log": [],
                        "initial": None,
                    }
                    merge_search_result(
                        result,
                        proposal_idx,
                        obj.name,
                        stage_name,
                    )
                    return result

                def explicit_score(candidate_obj, candidate_metrics):
                    score_counter["count"] += 1
                    area, candidate_mask = _lowres_holdout(
                        scene,
                        pobj,
                        token=(
                            f"{frame_seed}_explicit_"
                            f"{proposal_idx}_{stage_name}_"
                            f"{score_counter['count']}"
                        ),
                        size=lowres128,
                    )
                    m0 = explicit_baseline["mask_area_target_only"]
                    m3 = explicit_baseline["mask_area_after_context"]
                    f_value = (
                        max(0.0, float(m3 - area) / float(m0))
                        if m0 > 0
                        else 0.0
                    )
                    vis = _measure_front_opening_visibility(
                        {
                            "scene": scene,
                            "pallet": pobj,
                            "pallet_name": spec.pallet_type,
                            "cam_pos": cam_pos,
                            "cam_look": cam_look,
                            "K": K,
                            "W": int(W),
                            "H": int(H),
                        }
                    )
                    penalty = 0.0
                    front_visibility = vis.get("front_face_visibility")
                    left_opening_visibility = vis.get(
                        "left_opening_visibility"
                    )
                    right_opening_visibility = vis.get(
                        "right_opening_visibility"
                    )
                    if front_visibility is not None:
                        penalty += 0.5 * max(
                            0.0,
                            SP2.EXPLICIT_FRONT_MIN_VISIBILITY
                            - front_visibility,
                        )
                    for key in (
                        "left_opening_visibility",
                        "right_opening_visibility",
                    ):
                        if vis.get(key) is not None:
                            penalty += 0.5 * max(
                                0.0,
                                SP2.EXPLICIT_OPENING_MIN_VISIBILITY
                                - vis[key],
                            )
                    corner_metrics = _candidate_corner_gate_metrics(
                        scene,
                        cam_pos,
                        cam_look,
                        pobj,
                        spec.pallet_type,
                        K,
                        int(W),
                        int(H),
                    )
                    corner_penalty = 0.0
                    if not corner_metrics["G2_pass"]:
                        corner_penalty += 0.25
                        if corner_metrics["ext_occ_corners"] == 0:
                            corner_penalty += corner_metrics[
                                "corner_threshold_gap"
                            ]
                        else:
                            corner_penalty += max(
                                0.0,
                                (
                                    corner_metrics["ext_occ_corners"] - 4
                                )
                                / 4.0,
                            )
                    if not corner_metrics["G1_pass"]:
                        corner_penalty += 0.25 + max(
                            0.0,
                            (4 - corner_metrics["V_vis"]) / 4.0,
                        )
                    error = abs(f_value - explicit_target)
                    side_actual = _occlusion_side_from_masks(
                        explicit_before_mask,
                        candidate_mask,
                    )
                    side_target = proposal.get("side")
                    side_match = SP2.explicit_side_matches(
                        side_target,
                        side_actual,
                    )
                    object_visible_area, object_visible_mask = (
                        _lowres_holdout(
                            scene,
                            pobj,
                            only_white=candidate_obj,
                            token=(
                                f"{frame_seed}_explicit_object_visible_"
                                f"{proposal_idx}_{stage_name}_"
                                f"{score_counter['count']}"
                            ),
                            size=lowres128,
                        )
                    )
                    visible_rows, visible_cols = np.nonzero(
                        object_visible_mask > 127
                    )
                    object_visible_stats = SP2.mask_index_stats(
                        visible_rows,
                        visible_cols,
                        height=object_visible_mask.shape[0],
                        width=object_visible_mask.shape[1],
                    )
                    object_amodal_stats = None
                    if object_visible_area <= 0:
                        _, object_amodal_mask = _lowres_holdout(
                            scene,
                            pobj,
                            extra_hide=_all_nonpallet_visible(
                                candidate_obj
                            ),
                            only_white=candidate_obj,
                            token=(
                                f"{frame_seed}_explicit_object_amodal_"
                                f"{proposal_idx}_{stage_name}_"
                                f"{score_counter['count']}"
                            ),
                            size=lowres128,
                        )
                        amodal_rows, amodal_cols = np.nonzero(
                            object_amodal_mask > 127
                        )
                        object_amodal_stats = SP2.mask_index_stats(
                            amodal_rows,
                            amodal_cols,
                            height=object_amodal_mask.shape[0],
                            width=object_amodal_mask.shape[1],
                        )
                    object_min, object_max = get_obj_aabb_world(
                        candidate_obj
                    )
                    object_corners = np.asarray(
                        [
                            [x, y, z]
                            for x in (object_min[0], object_max[0])
                            for y in (object_min[1], object_max[1])
                            for z in (object_min[2], object_max[2])
                        ],
                        dtype=np.float64,
                    )
                    projection_R, projection_t = build_view_matrix(
                        cam_pos,
                        cam_look,
                        up=(0, 0, 1),
                    )
                    object_uv, object_depth = _project(
                        K,
                        projection_R,
                        projection_t,
                        object_corners,
                    )
                    object_projected_stats = SP2.projected_bbox_stats(
                        object_uv,
                        object_depth,
                        source_size=(int(W), int(H)),
                        target_size=lowres128,
                    )
                    reference_stats = object_visible_stats
                    if reference_stats.get("bbox_px") is None:
                        reference_stats = object_amodal_stats or {}
                    if reference_stats.get("bbox_px") is None:
                        reference_stats = object_projected_stats
                    screen_gap_px = SP2.bbox_gap_px(
                        explicit_target_mask_stats["bbox_px"],
                        reference_stats["bbox_px"],
                    )
                    screen_penalty = (
                        1.0
                        if screen_gap_px is None
                        else float(screen_gap_px) / lowres128_long_edge
                    )
                    visibility_penalty = max(
                        0.0,
                        (
                            8.0
                            - float(object_visible_stats["visible_pixels"])
                        )
                        / 8.0,
                    )
                    target_error_ok = (
                        error <= SP2.EXPLICIT_TARGET_ABS_TOLERANCE
                    )
                    candidate_accept = bool(
                        side_match
                        and int(object_visible_stats["visible_pixels"]) >= 8
                        and target_error_ok
                        and corner_metrics["joint_pass"]
                    )
                    roi_score_weight = SP2.EXPLICIT_ROI_SCORE_WEIGHT
                    corner_score_weight = 0.25
                    return {
                        "accept": candidate_accept,
                        "score": -(
                            error
                            + roi_score_weight * penalty
                            + corner_score_weight * corner_penalty
                            + screen_penalty
                            + visibility_penalty
                        ),
                        "f_explicit_actual": f_value,
                        "abs_error": error,
                        "target_error_ok": target_error_ok,
                        "roi_penalty": penalty,
                        "roi_score_weight": roi_score_weight,
                        "corner_gate_penalty": corner_penalty,
                        "corner_score_weight": corner_score_weight,
                        "candidate_corner_occlusion_fractions": (
                            corner_metrics["occlusion_fractions"]
                        ),
                        "candidate_ext_occ_corners": (
                            corner_metrics["ext_occ_corners"]
                        ),
                        "candidate_V_inframe": corner_metrics["V_inframe"],
                        "candidate_V_vis": corner_metrics["V_vis"],
                        "candidate_G1_pass": corner_metrics["G1_pass"],
                        "candidate_G2_pass": corner_metrics["G2_pass"],
                        "front_face_visibility": front_visibility,
                        "left_opening_visibility": left_opening_visibility,
                        "right_opening_visibility": right_opening_visibility,
                        "opening_visibility_reason": vis.get(
                            "opening_visibility_reason"
                        ),
                        "object_screen_gap_px": screen_gap_px,
                        "object_screen_penalty": screen_penalty,
                        "object_visibility_penalty": visibility_penalty,
                        "occluder_side_target": side_target,
                        "occluder_side_actual": side_actual,
                        "occluder_side_match": side_match,
                        "object_visible_pixels": (
                            object_visible_stats["visible_pixels"]
                        ),
                        "object_visible_bbox_px": (
                            object_visible_stats["bbox_px"]
                        ),
                        "object_visible_centroid_px": (
                            object_visible_stats["centroid_px"]
                        ),
                        "object_amodal_pixels": (
                            None
                            if object_amodal_stats is None
                            else object_amodal_stats["visible_pixels"]
                        ),
                        "object_amodal_bbox_px": (
                            None
                            if object_amodal_stats is None
                            else object_amodal_stats["bbox_px"]
                        ),
                        "object_amodal_centroid_px": (
                            None
                            if object_amodal_stats is None
                            else object_amodal_stats["centroid_px"]
                        ),
                        "object_projected_bbox_px": (
                            object_projected_stats["bbox_px"]
                        ),
                        "object_projected_centroid_px": (
                            object_projected_stats["centroid_px"]
                        ),
                    }

                result = SV2.search_explicit_occluder_local(
                    occluder_obj=obj,
                    plan=stage_plan,
                    pallet_obj=pobj,
                    cam_pos=cam_pos,
                    cam_look=cam_look,
                    score_callback=explicit_score,
                    static_objects=static_objects,
                    cargo_objects=cargo_objs,
                    # context 는 explicit 뒤로 옮겨졌으므로 이 시점에는 아직 없다.
                    context_objects=(),
                    candidate_offsets=offsets,
                    camera_clearance=SP2.camera_clearance_for_role(
                        SP2.ROLE_EXPLICIT_OCCLUDER
                    ),
                    camera_clearance_exact=True,
                    broad_aabb_inflate=0.0,
                    ground_z=dynamic_ground_z,
                    support_objects=support_objects,
                    support_ray_start_z=support_ray_start_z,
                    support_ray_distance=20.0,
                    min_support_normal_z=0.5,
                    support_contact_tolerance=0.01,
                )
                merge_search_result(
                    result,
                    proposal_idx,
                    obj.name,
                    stage_name,
                )
                remember_current_best(
                    result,
                    obj,
                    proposal,
                    stage_name,
                )
                evaluated = int(result.get("candidates") or 0)
                for logged in (result.get("candidate_log") or []):
                    evaluated_geometry_keys.add(
                        SP2.candidate_geometry_key(logged))
                if stage_name == SP2.CONSTRAINT_RESCUE_STAGE:
                    rescue_state["evals"] += evaluated
                elif stage_name in FINE_STAGES:
                    search_stats["fine_eval_count"] += evaluated
                    if stage_name == SP2.FINE_STAGE:
                        fine_state["evals"] += evaluated
                else:
                    search_stats["coarse_eval_count"] += evaluated
                for key in ("best", "best_rejected"):
                    candidate = result.get(key) or {}
                    score = candidate.get("score")
                    if score is None:
                        continue
                    current = search_stats["best_seed_score"]
                    if current is None or float(score) > float(current):
                        search_stats["best_seed_score"] = float(score)
                best = result.get("best") or {}
                if best.get("score") is not None:
                    # 최종 선택은 stage 단위 success 가 아니라 global_best 가 한다.
                    search_stats["final_seed_score"] = float(best["score"])
                return result

            def guided_bbox_alignment_offsets(result, side):
                seed = SP2.best_explicit_search_seed(result)
                if seed is None:
                    return ()
                score_metrics = seed.get("score_callback") or {}
                if not score_metrics:
                    return ()
                try:
                    center = np.asarray(seed["center"], dtype=np.float64)
                    camera = np.asarray(cam_pos, dtype=np.float64)
                    look = np.asarray(cam_look, dtype=np.float64)
                    forward = look - camera
                    forward_norm = float(np.linalg.norm(forward))
                    if forward_norm <= 1e-9:
                        return ()
                    forward = forward / forward_norm
                    depth = float(np.dot(center - camera, forward))
                    if not math.isfinite(depth) or depth <= 1e-9:
                        return ()
                    low_w, low_h = lowres128
                    fx_low = float(K[0, 0]) * float(low_w) / float(W)
                    fy_low = float(K[1, 1]) * float(low_h) / float(H)
                    if fx_low <= 0.0 or fy_low <= 0.0:
                        return ()
                    return SP2.explicit_bbox_alignment_offsets(
                        explicit_target_mask_stats,
                        score_metrics,
                        side,
                        meters_per_pixel_u=depth / fx_low,
                        meters_per_pixel_v=depth / fy_low,
                        depth_step_m=explicit_feedback_depth_step,
                        yaw_step_degrees=(15.0,),
                    )
                except (KeyError, TypeError, ValueError):
                    return ()

            searched_proposals = resolved_proposals[
                :SP2.EXPLICIT_PROPOSAL_SEARCH_LIMIT
            ]
            for proposal_idx, proposal in enumerate(searched_proposals):
                proposal_name = proposal["resolved_obj_name"]
                proposal_obj = get_obj(proposal_name)
                if proposal_obj is None:
                    continue
                for candidate_obj in explicit_objects:
                    set_render_visibility(candidate_obj, False)

                occ_plan = dict(proposal)
                occ_plan["obj_name"] = proposal_name
                occ_plan["center"] = list(
                    np.asarray(proposal["center"], dtype=np.float64)
                    + rigid_shift
                )
                SV2.place_initial_explicit_occluder(
                    proposal_obj,
                    plan=occ_plan,
                    visible=False,
                    ground_z=None,
                )
                proposal_min, proposal_max = SV2.fresh_world_aabb(proposal_obj)
                grounded_center_z = float(dynamic_ground_z) + 0.5 * float(
                    proposal_max[2] - proposal_min[2]
                )
                corrected_center = SP2.camera_ray_point_at_z(
                    cam_pos,
                    occ_plan["center"],
                    grounded_center_z,
                )
                if corrected_center is not None:
                    original_center = list(occ_plan["center"])
                    occ_plan["center"] = list(corrected_center)
                    occ_plan["planned_center_before_ground_correction"] = (
                        original_center
                    )
                    occ_plan["grounded_center_z"] = grounded_center_z
                    occ_plan["ground_center_correction_m"] = float(
                        np.linalg.norm(
                            np.asarray(corrected_center, dtype=np.float64)
                            - np.asarray(original_center, dtype=np.float64)
                        )
                    )
                primary = run_search_stage(
                    proposal_obj,
                    proposal,
                    proposal_idx,
                    "preprobe",
                    occ_plan,
                    candidate_offsets=((0.0, 0.0, 0.0, 0.0),),
                )
                coarse_results = [primary]
                search_stats["search_seed_count"] += 1
                # ★ §4 (2026-08-01): target-mask-conditioned 정렬을 **맨 앞으로**.
                # preprobe 한 번으로 얻은 실측(projected bbox·f_actual)을 목표 마스크
                # 통계(centroid/bbox/area)에 맞추는 해석적 offset 이 가장 싼 수정이다.
                # 예전에는 gate-overlap / corner-contact 휴리스틱 뒤에 있었고, 그
                # 결과 실패 프레임의 절반(48.8%)이 score_callback 으로 죽었다.
                if not primary.get("success"):
                    seed_offsets = guided_bbox_alignment_offsets(
                        primary,
                        proposal.get("side"),
                    )
                    if seed_offsets:
                        coarse_results.append(
                            run_search_stage(
                                proposal_obj,
                                proposal,
                                proposal_idx,
                                "target-seed",
                                occ_plan,
                                candidate_offsets=seed_offsets,
                            )
                        )
                if not any(result.get("success") for result in coarse_results):
                    gate_seed = (
                        SP2.best_explicit_gate_side_seed(primary)
                        or SP2.best_explicit_gate_seed(primary)
                    )
                    if gate_seed is not None:
                        gate_metrics = (
                            gate_seed.get("score_callback") or {}
                        )
                        overlap_offsets = (
                            SP2.explicit_overlap_refinement_offsets(
                                proposal.get("side"),
                                gate_metrics.get("f_explicit_actual", 0.0),
                                explicit_target,
                            )
                        )
                        if overlap_offsets:
                            gate_plan = SP2.explicit_refine_plan(
                                occ_plan,
                                gate_seed,
                            )
                            coarse_results.append(
                                run_search_stage(
                                    proposal_obj,
                                    proposal,
                                    proposal_idx,
                                    "gate-overlap-refine",
                                    gate_plan,
                                    candidate_offsets=overlap_offsets,
                                )
                            )

                if not any(
                    result.get("success") for result in coarse_results
                ):
                    missing_corner_seed = (
                        SP2.best_explicit_missing_corner_seed(
                            *coarse_results
                        )
                    )
                    if missing_corner_seed is not None:
                        corner_offsets = (
                            SP2.explicit_corner_contact_refinement_offsets(
                                proposal.get("side")
                            )
                        )
                        corner_plan = SP2.explicit_refine_plan(
                            occ_plan,
                            missing_corner_seed,
                        )
                        coarse_results.append(
                            run_search_stage(
                                proposal_obj,
                                proposal,
                                proposal_idx,
                                "corner-contact-refine",
                                corner_plan,
                                candidate_offsets=corner_offsets,
                            )
                        )

                # (구 "prealign" 단계는 제거했다.  preprobe 결과로부터 같은 offset 을
                #  계산하는 중복이었고, 위 "target-seed" 가 그 자리를 대신한다.
                #  두 단계를 모두 두면 proposal 당 후보 예산을 두 배로 먹어
                #  candidate_budget_exhausted 로 이어진다 — replay 에서 실제로
                #  accepted 2건을 잃었다.)
                if not any(result.get("success") for result in coarse_results):
                    primary = run_search_stage(
                        proposal_obj,
                        proposal,
                        proposal_idx,
                        "primary",
                        occ_plan,
                    )
                    coarse_results.append(primary)
                    prealign_offsets = guided_bbox_alignment_offsets(
                        primary,
                        proposal.get("side"),
                    )
                    if prealign_offsets:
                        coarse_results.append(
                            run_search_stage(
                                proposal_obj,
                                proposal,
                                proposal_idx,
                                "prealign-primary",
                                occ_plan,
                                candidate_offsets=prealign_offsets,
                            )
                        )

                if not any(result.get("success") for result in coarse_results):
                    rescue = run_search_stage(
                        proposal_obj,
                        proposal,
                        proposal_idx,
                        "rescue",
                        occ_plan,
                    )
                    coarse_results.append(rescue)
                    prealign_offsets = guided_bbox_alignment_offsets(
                        rescue,
                        proposal.get("side"),
                    )
                    if prealign_offsets:
                        coarse_results.append(
                            run_search_stage(
                                proposal_obj,
                                proposal,
                                proposal_idx,
                                "prealign-rescue",
                                occ_plan,
                                candidate_offsets=prealign_offsets,
                            )
                        )

                if not any(result.get("success") for result in coarse_results):
                    refine_seed = SP2.best_explicit_search_seed(*coarse_results)
                    refined_plan = SP2.explicit_refine_plan(
                        occ_plan,
                        refine_seed,
                    )
                    refined = run_search_stage(
                        proposal_obj,
                        proposal,
                        proposal_idx,
                        "refine",
                        refined_plan,
                    )
                    feedback_seed = SP2.best_explicit_side_seed(
                        refined,
                        *coarse_results,
                    ) or SP2.best_explicit_search_seed(
                        refined,
                        *coarse_results,
                    )
                    if feedback_seed is not None:
                        feedback_offsets = SP2.explicit_feedback_offsets(
                            explicit_target_mask_stats,
                            feedback_seed.get("score_callback") or {},
                            proposal.get("side"),
                            depth_step_m=explicit_feedback_depth_step,
                        )
                        if feedback_offsets:
                            feedback_plan = SP2.explicit_refine_plan(
                                refined_plan,
                                feedback_seed,
                            )
                            run_search_stage(
                                proposal_obj,
                                proposal,
                                proposal_idx,
                                "feedback",
                                feedback_plan,
                                candidate_offsets=feedback_offsets,
                            )

                # §4 near-miss fine refinement — 목표 오차 **하나만** 막고 있고 그
                # 간격이 작은 후보 1개에만, 자체 상한(FINE_MAX_EVALS) 안에서 돈다.
                # coarse step 의 절반을 재사용하고 새 절대 단위를 만들지 않는다.
                if (
                    global_best is None
                    and SEARCH_TUNING["near_miss_gap_threshold"] is not None
                    and fine_state["evals"] < SP2.FINE_MAX_EVALS
                ):
                    seed = SP2.select_near_miss_seed(
                        [c for c in aggregate_log
                         if c.get("proposal_index") == int(proposal_idx)],
                        SEARCH_TUNING["near_miss_gap_threshold"],
                    )
                    if seed is not None:
                        fine_t0 = time.perf_counter()
                        fine_state.update({
                            "triggered": True,
                            "trigger_reason": "target_error_only",
                            "source_stage": seed["stage"],
                            "source_score": seed["score"],
                            "margin_before": seed["score_margin"],
                        })
                        refine = schedule["refine"]["candidates"]
                        u_step = max(abs(float(o[0])) for o in refine) or 0.15
                        v_step = max(abs(float(o[1])) for o in refine) or 0.15
                        d_step = max(abs(float(o[2])) for o in refine) or 0.175
                        plane, depth = SP2.fine_refinement_offsets(
                            u_step, v_step, d_step)
                        fine_plan = SP2.explicit_refine_plan(
                            occ_plan, seed["candidate"])
                        plane_result = run_search_stage(
                            proposal_obj, proposal, proposal_idx,
                            SP2.FINE_STAGE, fine_plan, candidate_offsets=plane)
                        best_plane = SP2.best_explicit_search_seed(plane_result)
                        depth_plan = (
                            SP2.explicit_refine_plan(fine_plan, best_plane)
                            if best_plane is not None else fine_plan)
                        depth_result = run_search_stage(
                            proposal_obj, proposal, proposal_idx,
                            SP2.FINE_STAGE, depth_plan, candidate_offsets=depth)
                        best_fine = (SP2.best_explicit_search_seed(depth_result)
                                     or best_plane)
                        if best_fine is not None:
                            metrics = best_fine.get("score_callback") or {}
                            fine_state["best_score"] = best_fine.get("score")
                            error = metrics.get("abs_error")
                            fine_state["margin_after"] = (
                                None if error is None
                                else SP2.EXPLICIT_TARGET_ABS_TOLERANCE - float(error))
                        fine_state["won"] = bool(global_best is not None)
                        fine_state["runtime_s"] += time.perf_counter() - fine_t0

                # §7-§9 constraint-directed rescue — 기존 search 가 모두 실패한
                # 뒤에만, 자체 상한 안에서 돈다.  acceptance gate 는 우회하지
                # 않는다 (성공 판정은 평소와 같은 5조건 실측이다).
                if (
                    global_best is None
                    and SEARCH_TUNING["constraint_rescue_mode"] != "off"
                    and rescue_state["evals"]
                    < int(SEARCH_TUNING["constraint_rescue_eval_max"])
                ):
                    proposal_log = [c for c in aggregate_log
                                    if c.get("proposal_index") == int(proposal_idx)]
                    refine_offsets = schedule["refine"]["candidates"]
                    steps = (
                        max(abs(float(o[0])) for o in refine_offsets) or 0.15,
                        max(abs(float(o[1])) for o in refine_offsets) or 0.15,
                        max(abs(float(o[2])) for o in refine_offsets) or 0.175,
                    )
                    target_bbox = (explicit_target_mask_stats or {}).get("bbox_px")
                    plan_rescue = SP2.constraint_rescue_plan(
                        proposal_log, target_bbox,
                        (plan.occluder or {}).get("side"), steps,
                        mode=SEARCH_TUNING["constraint_rescue_mode"],
                        beam_max=SEARCH_TUNING["constraint_rescue_beam"],
                        eval_max=(int(SEARCH_TUNING["constraint_rescue_eval_max"])
                                  - rescue_state["evals"]),
                        category_max=SEARCH_TUNING[
                            "constraint_rescue_category_max"],
                        evaluated_keys=evaluated_geometry_keys,
                    )
                    rescue_state["duplicate_skips"] += int(
                        plan_rescue["duplicate_skips"])
                    if plan_rescue["evaluations"]:
                        rescue_t0 = time.perf_counter()
                        rescue_state.update({
                            "triggered": True,
                            "beam_size": len(plan_rescue["beam"]),
                        })
                        rescue_state["axis_sequence"].extend(
                            plan_rescue["axis_sequence"])
                        rescue_state["categories"] = sorted(
                            set(rescue_state["categories"])
                            | set(plan_rescue["categories"]))
                        first = plan_rescue["evaluations"][0]
                        if rescue_state["constraint_before"] is None:
                            rescue_state["constraint_before"] = dict(
                                first["constraint_before"])
                        rescue_state["binding_signatures"] = sorted(
                            set(rescue_state["binding_signatures"])
                            | {"ONE_MISS_%s" % e["category"].upper()
                               for e in plan_rescue["evaluations"]})
                        rescue_state["seed_types"].extend(
                            e["seed_type"] for e in plan_rescue["evaluations"])
                        rescue_plan_base = SP2.explicit_refine_plan(occ_plan, None)
                        rescue_result = run_search_stage(
                            proposal_obj, proposal, proposal_idx,
                            SP2.CONSTRAINT_RESCUE_STAGE, rescue_plan_base,
                            candidate_offsets=[e["offset"]
                                               for e in plan_rescue["evaluations"]])
                        best_rescue = SP2.best_explicit_search_seed(rescue_result)
                        if best_rescue is not None:
                            rescue_state["constraint_after"] = (
                                SP2.candidate_constraint_vector(
                                    best_rescue.get("score_callback") or {}))
                        rescue_state["won"] = bool(global_best is not None)
                        if global_best is not None:
                            rescue_state["final_constraint_vector"] = (
                                SP2.candidate_constraint_vector(
                                    global_best["record"].get("score_callback")
                                    or {}))
                        rescue_state["runtime_s"] += (
                            time.perf_counter() - rescue_t0)

                set_render_visibility(proposal_obj, False)
                if global_best is not None:
                    best_metrics = (
                        global_best["record"].get("score_callback") or {}
                    )
                    best_error = float(best_metrics.get("abs_error", 1.0))
                    if (
                        bool(best_metrics.get("target_error_ok"))
                        and (
                            best_error <= SP2.EXPLICIT_PRECISE_ABS_TOLERANCE
                            or int(proposal_idx + 1)
                            >= SP2.EXPLICIT_MIN_PROPOSALS_BEFORE_TOLERANCE_STOP
                        )
                    ):
                        break

            explicit_search = {
                "success": global_best is not None,
                "best": (
                    None if global_best is None else global_best["record"]
                ),
                "reject_counts": aggregate_rejects,
                "candidates": len(aggregate_log),
                "candidate_log": aggregate_log,
                "initial": initial_proposals,
                "proposal_count": len(resolved_proposals),
                "proposal_search_limit": (
                    SP2.EXPLICIT_PROPOSAL_SEARCH_LIMIT
                ),
                "min_proposals_before_tolerance_stop": (
                    SP2.EXPLICIT_MIN_PROPOSALS_BEFORE_TOLERANCE_STOP
                ),
                "candidate_limit_per_proposal": (
                    SP2.EXPLICIT_CANDIDATE_LIMIT_PER_PROPOSAL
                ),
                "proposal_names": [
                    proposal["resolved_obj_name"]
                    for proposal in resolved_proposals
                ],
                "search_runs": search_runs,
                "selected_object": (
                    None
                    if global_best is None
                    else global_best["object_name"]
                ),
                "selected_stage": (
                    None if global_best is None else global_best["stage"]
                ),
                "target_mask_stats": explicit_target_mask_stats,
                "search_stats": dict(
                    search_stats,
                    winning_stage=(None if global_best is None
                                   else global_best["stage"]),
                ),
                "fine_state": dict(fine_state),
                "rescue_state": dict(rescue_state),
                "target_seed_budget": SP2.target_seed_budget_usage(
                    aggregate_log, 0, SEARCH_TUNING["target_seed_free_cap"]),
                "target_seed_budget_all": [
                    SP2.target_seed_budget_usage(
                        aggregate_log, idx,
                        SEARCH_TUNING["target_seed_free_cap"])
                    for idx in range(len(resolved_proposals))
                ],
                "tuning": dict(SEARCH_TUNING),
            }
            if global_best is not None:
                explicit_name = global_best["object_name"]
                occ_obj = get_obj(explicit_name)
                occ_obj.location = global_best["location"]
                occ_obj.rotation_euler = global_best["rotation"]
                occ_obj.scale = global_best["scale"]
                set_render_visibility(occ_obj, True)
                bpy.context.view_layer.update()
                final_area, final_mask = _lowres_holdout(
                    scene,
                    pobj,
                    token=f"{frame_seed}_explicit_final",
                    size=lowres128,
                )
                explicit_visible_pixels, _ = _lowres_holdout(
                    scene,
                    pobj,
                    only_white=occ_obj,
                    token=f"{frame_seed}_explicit_object",
                    size=lowres128,
                )
                m0 = explicit_baseline["mask_area_target_only"]
                m3 = explicit_baseline["mask_area_after_context"]
                explicit_actual = (
                    max(0.0, float(m3 - final_area) / float(m0))
                    if m0 > 0
                    else 0.0
                )
                explicit_error = abs(explicit_actual - explicit_target)
                explicit_side_actual = _occlusion_side_from_masks(
                    explicit_before_mask,
                    final_mask,
                )
                # §2 저해상도 실제 가림 통계.  public 프로필은 M1~M3 를 저장하지
                # 않아 마스크 분해로 f_explicit 을 얻을 수 없다.  탐색이 이미 찍은
                # holdout 두 장의 차집합에서 숫자만 뽑는다 (파일 저장 없음).
                explicit_lost_mask = (
                    (np.asarray(explicit_before_mask) > 127)
                    & ~(np.asarray(final_mask) > 127)
                )
                lost_rows, lost_cols = np.nonzero(explicit_lost_mask)
                explicit_actual_mask_stats = SP2.mask_index_stats(
                    lost_rows,
                    lost_cols,
                    height=explicit_lost_mask.shape[0],
                    width=explicit_lost_mask.shape[1],
                )
                if explicit_visible_pixels <= 0:
                    set_render_visibility(occ_obj, False)
                    occ_obj = None
                    explicit_solver_fail = "explicit_occluder_not_visible"
            else:
                explicit_solver_fail = "bounded_local_search_exhausted"
                for candidate_obj in explicit_objects:
                    set_render_visibility(candidate_obj, False)
    elif flags["explicit"] and explicit_target > 0.0:
        explicit_solver_fail = "pure_plan_has_no_explicit_occluder"
    stage_runtime["explicit"] = time.perf_counter() - explicit_t0

    # explicit 이 요구 조건을 못 맞춘 controlled 프레임은 여기서 context 를
    # 아예 시도하지 않는다 — 어차피 버려질 프레임에 배치 비용을 쓰지 않는다.
    explicit_blocked = bool(
        flags["explicit"]
        and SP2.explicit_requirement_failure(
            flags["explicit"],
            place_occluder,
            explicit_target,
            occ_obj is not None,
            explicit_solver_fail,
            explicit_actual=explicit_actual,
            side_target=(plan.occluder or {}).get("side"),
            side_actual=explicit_side_actual,
            visible_pixels=explicit_visible_pixels,
        )
        is not None
    )
    explicit_placed_objects = [] if occ_obj is None else [occ_obj]
    # explicit 이 이미 놓였다면 코너 기준을 "배치 전 여유 확보"에서 "배치 후 비열화"로
    # 바꾼다.  가리는 것이 본업인 occluder 를 예약 계약으로 재평가하면 context 후보가
    # 전멸한다 (replay 실측: context 14초 -> 225초, 저해상도 렌더 52 -> 351).
    post_explicit_corner_reserve = None
    if explicit_placed_objects:
        post_explicit_corner_reserve = _candidate_corner_gate_metrics(
            scene,
            cam_pos,
            cam_look,
            pobj,
            spec.pallet_type,
            K,
            int(W),
            int(H),
        )

    # Context objects are domain-filtered, disjoint from the planned explicit
    # occluder, grounded, collision checked, screen-visible, and constrained to
    # a small accidental-pallet-occlusion budget.
    context_t0 = time.perf_counter()
    _seed_stage(stage_seeds["context"])
    context_requested = 3 if flags["context"] else 0
    context_candidates = []
    if context_requested:
        rng = random.Random(stage_seeds["context"])
        raw_candidates = dpool.select_distractor_object_names(
            spec.scene_preset,
            max(12, context_requested * 4),
            rng,
        )
        for raw_name in raw_candidates:
            resolved = _resolve_distractor_object_name(raw_name)
            if (
                resolved
                and resolved not in explicit_candidate_names
                and resolved not in context_candidates
            ):
                context_candidates.append(resolved)

    pallet_center = np.asarray(
        get_pallet_geometry(
            spec.pallet_type,
            pobj,
            ORIENTATION_OVERRIDES,
        )["centroid_world"],
        dtype=np.float64,
    )
    context_baseline = None
    if context_requested and not explicit_blocked:
        # explicit 은 이미 놓였다 -> m2 에서 가려 두고 context 기여분만 재도록 한다.
        context_baseline = _lowres_stage_areas(
            scene,
            pobj,
            cargo_objs,
            [],
            occ_obj,
            token=f"{frame_seed}_context_base",
            size=lowres96,
        )
    context_callback_attempts = {"count": 0}

    def context_budget_callback(obj, placed, current_metrics):
        context_callback_attempts["count"] += 1
        # 배치된 explicit occluder 는 가리고 잰다 — 그래야 f_context 가 context
        # 기여분만 담는다 (의도된 explicit 가림을 예산에 넣지 않는다).
        area, _ = _lowres_holdout(
            scene,
            pobj,
            extra_hide=explicit_placed_objects,
            only_white=None,
            token=f"{frame_seed}_ctx_pal_{context_callback_attempts['count']}",
            size=lowres96,
        )
        visible_px, _ = _lowres_holdout(
            scene,
            pobj,
            extra_hide=(),
            only_white=obj,
            token=f"{frame_seed}_ctx_obj_{context_callback_attempts['count']}",
            size=lowres96,
        )
        m0 = context_baseline["mask_area_target_only"]
        m2 = context_baseline["mask_area_after_cargo"]
        f_context_now = (
            max(0.0, float(m2 - area) / float(m0)) if m0 > 0 else 1.0
        )
        screen_ratio = float(visible_px) / float(lowres96_area)
        corner_metrics = None
        corner_reserve_pass = True
        if enforce_explicit_corner_reserve:
            corner_metrics = _candidate_corner_gate_metrics(
                scene,
                cam_pos,
                cam_look,
                pobj,
                spec.pallet_type,
                K,
                int(W),
                int(H),
            )
            corner_reserve_pass = (
                SP2.explicit_corner_reserve_pass(corner_metrics)
                if post_explicit_corner_reserve is None
                else SP2.context_corner_no_regression(
                    corner_metrics,
                    post_explicit_corner_reserve,
                )
            )
        return {
            "accept": bool(
                visible_px >= 8
                and screen_ratio >= 0.0005
                and f_context_now <= 0.12
                and corner_reserve_pass
            ),
            "visible_pixels": int(visible_px),
            "screen_area_ratio": screen_ratio,
            "f_context": f_context_now,
            "explicit_corner_reserve_pass": corner_reserve_pass,
            "preexplicit_V_inframe": (
                None
                if corner_metrics is None
                else corner_metrics["V_inframe"]
            ),
            "preexplicit_ext_occ_corners": (
                None
                if corner_metrics is None
                else corner_metrics["ext_occ_corners"]
            ),
            "preexplicit_V_vis": (
                None if corner_metrics is None else corner_metrics["V_vis"]
            ),
        }

    context_result = {
        "placed_objects": [],
        "placed_names": [],
        "metrics": {
            "success": context_requested == 0,
            "requested": context_requested,
            "placed": 0,
            "reject_counts": {},
            "placements": [],
        },
    }
    if context_requested and not explicit_blocked:
        context_result = SV2.place_context_objects(
            context_candidates,
            pobj,
            cam_pos=cam_pos,
            cam_look=cam_look,
            floor_z=dynamic_ground_z,
            floor_contact_tolerance=0.01,
            support_objects=support_objects,
            support_ray_start_z=support_ray_start_z,
            support_ray_distance=20.0,
            min_support_normal_z=0.5,
            seed=stage_seeds["context"],
            max_count=context_requested,
            attempts_per_object=18,
            candidate_poses=_context_candidate_poses(
                pallet_center,
                cam_pos,
                cam_look,
                K,
                (int(W), int(H)),
                dynamic_ground_z,
                stage_seeds["context"],
                attempts=18,
            ),
            static_objects=[
                *static_objects,
                *explicit_placed_objects,
            ],
            cargo_objects=cargo_objs,
            # occluder 는 이미 놓였으므로 후보 전체의 swept 예약은 필요 없다.
            reserved_aabbs=(),
            camera_clearance=SP2.camera_clearance_for_role(SP2.ROLE_CONTEXT),
            camera_clearance_exact=True,
            broad_aabb_inflate=0.0,
            occlusion_budget_callback=context_budget_callback,
        )
    context_objs = list(context_result["placed_objects"])
    context_attempts = (
        sum(context_result["metrics"].get("reject_counts", {}).values())
        + len(context_objs)
    )
    context_visible_count = 0
    context_visible_union = 0
    if context_objs:
        context_visible_union, _ = _lowres_holdout(
            scene,
            pobj,
            only_white=context_objs,
            token=f"{frame_seed}_context_union",
            size=lowres96,
        )
        for obj_idx, obj in enumerate(context_objs):
            visible_px, _ = _lowres_holdout(
                scene,
                pobj,
                only_white=obj,
                token=f"{frame_seed}_context_visible_{obj_idx}",
                size=lowres96,
            )
            context_visible_count += int(visible_px >= 8)
    context_screen_ratio = float(context_visible_union) / float(lowres96_area)
    context_visible_ratio = (
        float(context_visible_count) / float(len(context_objs))
        if context_objs
        else 0.0
    )
    stage_runtime["context"] = time.perf_counter() - context_t0

    collision_t0 = time.perf_counter()
    forbidden_pairs = _forbidden_collision_pairs(
        pobj,
        support_objects,
        static_objects,
        cargo_objs,
        context_objs,
        occ_obj,
    )
    collision_audit = SV2.audit_collisions_and_camera_clearance(
        forbidden_pairs=forbidden_pairs,
        camera_pos=None,
    )
    target_clearance = SV2.camera_clearance_report(
        cam_pos,
        [pobj],
        min_clearance=SP2.camera_clearance_for_role(SP2.ROLE_PALLET),
        exact=True,
    )
    obstacle_clearance = SV2.camera_clearance_report(
        cam_pos,
        [
            *static_objects,
            *cargo_objs,
            *context_objs,
            *([occ_obj] if occ_obj is not None else []),
        ],
        min_clearance=SP2.camera_clearance_for_role(
            SP2.ROLE_STATIC_BACKGROUND
        ),
        exact=True,
    )
    support_clearance = SV2.camera_clearance_report(
        cam_pos,
        support_objects,
        min_clearance=SP2.camera_clearance_for_role(SP2.ROLE_SUPPORT),
        exact=True,
    )
    clearance_rows = [
        row
        for row in (target_clearance, obstacle_clearance, support_clearance)
        if row.get("min_clearance") is not None
    ]
    min_clearance_row = min(
        clearance_rows,
        key=lambda row: row["min_clearance"],
        default=None,
    )
    collision_audit["camera_clearance"] = {
        "ok": bool(
            target_clearance["ok"]
            and obstacle_clearance["ok"]
            and support_clearance["ok"]
        ),
        "min_clearance": (
            None
            if min_clearance_row is None
            else min_clearance_row["min_clearance"]
        ),
        "min_object": (
            None
            if min_clearance_row is None
            else min_clearance_row["min_object"]
        ),
        "target": target_clearance,
        "obstacles": obstacle_clearance,
        "supports": support_clearance,
    }
    stage_runtime["collision_audit"] = time.perf_counter() - collision_t0
    exact_hits = collision_audit["collisions"]
    collision_names = {
        tuple(sorted((row["a"], row["b"]))) for row in exact_hits
    }

    def count_hits(objects_a, objects_b=None):
        left = {obj.name for obj in objects_a if obj is not None}
        right = left if objects_b is None else {
            obj.name for obj in objects_b if obj is not None
        }
        return sum(
            1
            for a, b in collision_names
            if (a in left and b in right) or (a in right and b in left)
        )

    pallet_obstacle_collisions = count_hits(
        [pobj],
        [*static_objects, *context_objs, *([occ_obj] if occ_obj else [])],
    )
    cargo_collisions = count_hits(
        cargo_objs,
        [
            *cargo_objs,
            *support_objects,
            *static_objects,
            *context_objs,
            *([occ_obj] if occ_obj else []),
        ],
    )
    context_context_collisions = count_hits(context_objs)
    broad_hits = sum(
        1 for row in collision_audit["pairs"] if row.get("broad_overlap")
    )
    cargo_support_pass = bool(
        all(
            abs(
                float(object_bottom_z_world(obj))
                - float(object_top_z_world(pobj))
            )
            <= 0.01
            for obj in cargo_objs
        )
    )
    context_support_rows = [
        placement.get("support")
        for placement in context_result["metrics"].get("placements", [])
    ]
    context_support_pass = bool(
        len(context_support_rows) == len(context_objs)
        and all(
            row
            and row.get("ok")
            and placement.get("contact_error") is not None
            and abs(float(placement["contact_error"])) <= 0.01
            for row, placement in zip(
                context_support_rows,
                context_result["metrics"].get("placements", []),
            )
        )
    )
    explicit_best = (
        (explicit_search or {}).get("best")
        if explicit_search is not None
        else None
    )
    explicit_support_pass = bool(
        occ_obj is None
        or (
            explicit_best
            and (explicit_best.get("support") or {}).get("ok")
            and explicit_best.get("support_error") is not None
            and abs(float(explicit_best["support_error"])) <= 0.01
        )
    )
    overall_support_pass = bool(
        accepted_anchor["support"]["ok"]
        and cargo_support_pass
        and context_support_pass
        and explicit_support_pass
    )
    camera_ok = bool(
        (collision_audit.get("camera_clearance") or {}).get("ok", True)
    )
    collision_ok = not exact_hits
    metrics = {
        "failure_reason": None,
        "diagnostic_mode": diagnostic_mode,
        "stage_seeds": stage_seeds,
        "floor_mode_requested": floor_mode_requested,
        "floor_mode_actual": floor_mode,
        "floor_fallback_reason": floor_fallback_reason,
        "floor_texture_dir": floor_texture_dir,
        "wood_texture_dir": wood_texture_dir,
        "procedural_support_shift": list(procedural_support_shift),
        "anchor_translation": accepted_anchor["translation"],
        "anchor_attempts": int(accepted_anchor["idx"]) + 1,
        "anchor_reject_reason": None,
        "anchor_reject_counts_by_reason": anchor.get("reject_counts", {}),
        "support_surface_name": support_surface_name,
        "support_ground_z": dynamic_ground_z,
        "static_los_sample_count": len(static_los_samples),
        "min_camera_clearance": (
            (collision_audit.get("camera_clearance") or {}).get(
                "min_clearance"
            )
        ),
        "camera_clearance_pass": camera_ok,
        "support_pass": overall_support_pass,
        "pallet_support_pass": bool(accepted_anchor["support"]["ok"]),
        "context_support_pass": context_support_pass,
        "explicit_support_pass": explicit_support_pass,
        "static_collision_pass": bool(accepted_anchor["collision"]["ok"]),
        "static_los_pass": bool(accepted_anchor["los"]["ok"]),
        "n_context_requested": int(context_requested),
        "n_context_placed": len(context_objs),
        "n_context_visible": int(context_visible_count),
        "context_visible_pixel_ratio": context_visible_ratio,
        "context_screen_area_ratio": context_screen_ratio,
        "context_placement_attempts": int(context_attempts),
        "context_reject_counts_by_reason": context_result["metrics"].get(
            "reject_counts", {}
        ),
        "n_cargo_requested": int(cargo_requested),
        "n_cargo_placed": len(cargo_objs),
        "n_cargo_visible": int(cargo_visible_count),
        "cargo_visible_pixels": int(cargo_visible_union),
        "cargo_visible_pixel_ratio": cargo_visible_ratio,
        "cargo_visibility_measured": True,
        "cargo_placement_attempts": int(cargo_attempts),
        "cargo_support_pass": cargo_support_pass,
        "cargo_collision_pass": cargo_collisions == 0,
        "explicit_corner_reserve_enforced": (
            bool(enforce_explicit_corner_reserve)
        ),
        "pre_cargo_corner_reserve_pass": (
            None
            if pre_cargo_corner_reserve is None
            else SP2.explicit_corner_reserve_pass(
                pre_cargo_corner_reserve
            )
        ),
        "pre_cargo_V_inframe": (
            None
            if pre_cargo_corner_reserve is None
            else pre_cargo_corner_reserve["V_inframe"]
        ),
        "pre_cargo_ext_occ_corners": (
            None
            if pre_cargo_corner_reserve is None
            else pre_cargo_corner_reserve["ext_occ_corners"]
        ),
        "pre_cargo_V_vis": (
            None
            if pre_cargo_corner_reserve is None
            else pre_cargo_corner_reserve["V_vis"]
        ),
        "front_visibility_after_cargo": cargo_visibility.get(
            "front_face_visibility"
        ),
        "left_opening_visibility_after_cargo": cargo_visibility.get(
            "left_opening_visibility"
        ),
        "right_opening_visibility_after_cargo": cargo_visibility.get(
            "right_opening_visibility"
        ),
        "f_explicit_target": explicit_target,
        "f_explicit_actual": explicit_actual,
        "explicit_abs_error": explicit_error,
        "explicit_feedback_depth_step_m": explicit_feedback_depth_step,
        "occluder_feedback_iterations": (
            0 if explicit_search is None else int(explicit_search["candidates"])
        ),
        "explicit_reject_counts_by_reason": (
            {}
            if explicit_search is None
            else dict(explicit_search.get("reject_counts", {}))
        ),
        "explicit_candidate_log": (
            []
            if explicit_search is None
            else list(explicit_search.get("candidate_log", []))
        ),
        "explicit_target_mask_stats": (
            None
            if explicit_search is None
            else explicit_search.get("target_mask_stats")
        ),
        # §2 저해상도 explicit 품질 지표 (숫자만, 마스크 파일은 저장하지 않는다).
        # public 프로필은 M1~M3 를 렌더하지 않아 마스크 분해로 f_explicit 을 얻을 수
        # 없다.  f_total 로 대체하면 cargo/context/static 이 섞이므로 금지 —
        # 대신 탐색이 이미 찍은 두 장의 holdout 차집합에서 통계를 뽑는다.
        **SP2.explicit_lowres_metrics(
            explicit_target_mask_stats,
            explicit_actual_mask_stats,
            explicit_target,
            explicit_actual,
        ),
        # §4 탐색 계측.  explicit 이 꺼진 mode 에서는 전부 None 이다.
        **SP2.explicit_search_metrics(explicit_search),
        # §3 target-seed 예산 회계 · §4 near-miss fine refinement 계측
        **_target_seed_budget_fields(explicit_search),
        **_fine_refinement_fields(explicit_search),
        # §9 constraint-directed rescue 계측 (mode=off 면 triggered=False)
        **_constraint_rescue_fields(explicit_search),
        "context_skipped_due_to_explicit_failure": bool(explicit_blocked),
        "explicit_initial_proposal": (
            None
            if explicit_search is None
            else explicit_search.get("initial")
        ),
        "explicit_proposal_count": (
            0
            if explicit_search is None
            else int(explicit_search.get("proposal_count", 0))
        ),
        "explicit_proposal_names": (
            []
            if explicit_search is None
            else list(explicit_search.get("proposal_names", []))
        ),
        "explicit_proposal_dimension_rejects": (
            explicit_proposal_dimension_rejects
        ),
        "explicit_proposal_dimension_normalizations": (
            explicit_proposal_dimension_normalizations
        ),
        "explicit_reservation_count": len(explicit_reservation_objects),
        "explicit_reservations": explicit_reservations,
        "explicit_swept_reservations": explicit_swept_reservations,
        "explicit_search_runs": (
            []
            if explicit_search is None
            else list(explicit_search.get("search_runs", []))
        ),
        "explicit_selected_object": (
            None
            if explicit_search is None
            else explicit_search.get("selected_object")
        ),
        "explicit_selected_stage": (
            None
            if explicit_search is None
            else explicit_search.get("selected_stage")
        ),
        "occluder_side_target": (
            (plan.occluder or {}).get("side") if flags["explicit"] else None
        ),
        "occluder_side_actual": explicit_side_actual,
        "occluder_side_match": SP2.explicit_side_matches(
            (plan.occluder or {}).get("side"),
            explicit_side_actual,
        ) if flags["explicit"] and explicit_side_actual is not None else None,
        # mode semantics 가 realize 안에서(=렌더 전에) 판정할 수 있도록, runner 가
        # rs["occluder"] 로 유도하던 값을 metrics 에도 같이 남긴다.
        "explicit_occluder_placed": bool(occ_obj is not None),
        "explicit_occluder_visible_pixels": int(explicit_visible_pixels),
        "explicit_collision_pass": not any(
            occ_obj is not None and occ_obj.name in hit
            for hit in collision_names
        ),
        "explicit_solver_fail_reason": explicit_solver_fail,
        "tested_collision_pairs": len(collision_audit["pairs"]),
        "broad_phase_hits": int(broad_hits),
        "exact_collision_hits": exact_hits,
        "exact_collision_count": len(exact_hits),
        "collision_reject_reason": (
            "mesh_overlap" if exact_hits else (
                "camera_clearance" if not camera_ok else None
            )
        ),
        "pallet_obstacle_collision_count": int(pallet_obstacle_collisions),
        "cargo_collision_count": int(cargo_collisions),
        "context_context_collision_count": int(context_context_collisions),
        "stage_runtime_s": {
            key: round(float(value), 6) for key, value in stage_runtime.items()
        },
        # Blender 안에서 실제로 돌린 explicit 배치 탐색 횟수와 저해상도 렌더 횟수.
        "realization_attempt_count": (
            0 if explicit_search is None
            else len(explicit_search.get("search_runs", []))
        ),
        "lowres_render_count": int(
            _LOWRES_RENDER_COUNT - lowres_render_count_start
        ),
    }
    explicit_requirement_failure = SP2.explicit_requirement_failure(
        flags["explicit"],
        place_occluder,
        explicit_target,
        occ_obj is not None,
        explicit_solver_fail,
        explicit_actual=explicit_actual,
        side_target=(plan.occluder or {}).get("side"),
        side_actual=explicit_side_actual,
        visible_pixels=explicit_visible_pixels,
    )
    if explicit_requirement_failure is not None:
        metrics["explicit_solver_fail_reason"] = (
            metrics["explicit_solver_fail_reason"]
            or explicit_requirement_failure
        )
    # MODE SEMANTICS — "이 프레임이 정말 그 mode 의 내용을 담고 있는가".  최종 RGB 를
    # 렌더하기 전(=realize 반환 전)에 판정하므로, 의미가 빈 프레임은 렌더 비용을 쓰지
    # 않고 버려진다.
    semantics = SP2.mode_semantics_verdict(diagnostic_mode, metrics)
    metrics["mode_semantics_pass"] = bool(semantics["pass"])
    metrics["mode_semantics_conditions"] = dict(semantics["conditions"])
    metrics["mode_semantics_failed_conditions"] = list(
        semantics["failed_conditions"]
    )
    metrics["mode_semantics_unknown_conditions"] = list(
        semantics["unknown_conditions"]
    )
    metrics["mode_semantics_reason"] = semantics["reason"]
    if (
        not collision_ok
        or not camera_ok
        or not overall_support_pass
        or explicit_requirement_failure is not None
        or not semantics["pass"]
    ):
        metrics["failure_reason"] = (
            explicit_requirement_failure
            or metrics["collision_reject_reason"]
            or ("support_contact" if not overall_support_pass else None)
            or semantics["reason"]
        )
        return {
            "realize_ok": False,
            "constrained_metrics": metrics,
        }

    geom_final = get_pallet_geometry(
        spec.pallet_type,
        pobj,
        ORIENTATION_OVERRIDES,
    )
    elevation_actual = _actual_elevation_deg(
        cam_pos,
        geom_final["centroid_world"],
    )
    return {
        "realize_ok": True,
        "placement_mode": "constrained",
        "diagnostic_mode": diagnostic_mode,
        "spec": spec,
        "plan": plan,
        "scene": scene,
        "pallet": pobj,
        "pallet_name": spec.pallet_type,
        "cam_pos": cam_pos,
        "cam_look": cam_look,
        "K": K,
        "W": int(W),
        "H": int(H),
        "translate": tuple(translate),
        "occluder": occ_obj,
        "cargo": cargo_objs,
        "context": context_objs,
        "support_objects": support_objects,
        "static_objects": static_objects,
        "n_cargo": len(cargo_objs),
        "material_variant_actual": (mat or {}).get("name"),
        "background": background,
        "floor_mode": floor_mode,
        "floor_info": floor_info,
        "dist_info": dist_info,
        "ground_hidden": ground_hidden,
        "exposure_ev": float(spec.exposure_ev),
        "elevation_deg_actual": elevation_actual,
        "explicit_occluder_present": occ_obj is not None,
        "constrained_metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Holdout masks (hierarchy-aware) + RGB render
# ---------------------------------------------------------------------------
_MASK_MATS = {}


def _mask_mats():
    if not _MASK_MATS:
        for nm, v in (("__V2_WHITE", 1.0), ("__V2_BLACK", 0.0)):
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
    return _MASK_MATS["__V2_WHITE"], _MASK_MATS["__V2_BLACK"]


#   engine : holdout 마스크(탐색용 저해상도 + 배포용 최종)를 어떤 엔진으로 뽑을지.
#            기본은 "eevee" — controlled 6케이스 replay 에서 154.6s -> 84.1s (1.84배),
#            6/6 accepted 판정 동일.  _render_holdout 이 렌더 직전에 모든 재질을
#            순백/순흑 Emission 으로 갈아끼우고 world=None 이라 알파·투명 경로가 없고,
#            남는 차이는 경계 래스터화뿐이라 실측 최대 3px(19,729 -> 19,728 / 73,793 ->
#            73,796, 0.005%) 였다.  "cycles" 는 이전 정본이며 기존 데이터셋과 픽셀
#            단위로 이어붙일 때 쓴다 (엔진이 다르면 exact-repro 락이 깨진다).
HOLDOUT_ENGINES = ("cycles", "eevee")
HOLDOUT_TUNING = {"engine": "eevee"}


def set_holdout_engine(engine=None):
    """holdout 마스크 렌더 엔진을 고른다 (프로세스당 1회, 렌더 시작 전)."""
    value = "cycles" if engine is None else str(engine)
    if value not in HOLDOUT_ENGINES:
        raise ValueError("unknown holdout engine: %r" % (engine,))
    HOLDOUT_TUNING["engine"] = value
    return dict(HOLDOUT_TUNING)


def _eevee_engine_name():
    """이 Blender 빌드가 실제로 가진 EEVEE enum 이름 (없으면 None)."""
    for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            bpy.context.scene.render.engine = bpy.context.scene.render.engine
        except Exception:
            pass
        if hasattr(bpy.types, "RenderSettings"):
            items = [i.identifier for i in
                     bpy.types.RenderSettings.bl_rna.properties["engine"]
                     .enum_items]
            if name in items:
                return name
    # enum_items 조회가 불완전한 빌드가 있다 (실측: CYCLES 가 목록에 없어도 동작).
    # 그 경우 BLENDER_EEVEE 를 시도해 보고 설정이 먹으면 사용한다.
    scene = bpy.context.scene
    prev = scene.render.engine
    try:
        scene.render.engine = "BLENDER_EEVEE"
        ok = scene.render.engine == "BLENDER_EEVEE"
    except Exception:
        ok = False
    finally:
        scene.render.engine = prev
    return "BLENDER_EEVEE" if ok else None


def _render_holdout(scene, pallet_root, path, extra_hide=(), only_white=None):
    """Binary holdout mask: pallet hierarchy=white, else=black, world=black. Occlusion is
    automatic (visible occluders paint black over the pallet). `extra_hide` objects are
    hidden for this pass (their occlusion removed). `only_white`, if given, is the object
    whose hierarchy is painted white INSTEAD of the pallet (used for the distractor-only
    visibility mask). Restores everything."""
    white, black = _mask_mats()
    roots = only_white if only_white is not None else [pallet_root]
    if not isinstance(roots, (list, tuple, set)):
        roots = [roots]
    pal_set = set()
    for root in roots:
        if root is not None:
            pal_set.update({root, *root.children_recursive})
    hide_backup = []
    for o in extra_hide:
        if o is None:
            continue
        for m in [o, *o.children_recursive]:
            hide_backup.append((m, m.hide_render, m.hide_viewport))
            m.hide_render = True
            m.hide_viewport = True
    mesh_objects = [ob for ob in bpy.data.objects if ob.type == "MESH"]
    data_backup = {}
    object_slot_backup = {}
    for ob in mesh_objects:
        data_key = int(ob.data.as_pointer())
        data_backup.setdefault(data_key, (ob.data, list(ob.data.materials)))
        object_slot_backup[ob.name] = [
            (slot.link, slot.material)
            for slot in ob.material_slots
        ]
    for mesh_data, materials in data_backup.values():
        if not materials:
            mesh_data.materials.append(black)
    for ob in mesh_objects:
        tgt = white if ob in pal_set else black
        for slot in ob.material_slots:
            slot.link = "OBJECT"
            slot.material = tgt
    wbk, scene.world = scene.world, None
    vbk = scene.view_settings.view_transform
    ebk = scene.view_settings.exposure
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.exposure = 0.0
    except Exception:
        pass
    fbk = scene.render.filepath
    cbk = scene.render.image_settings.color_mode
    sbk = scene.cycles.samples
    dbk = scene.cycles.use_denoising
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    # holdout 은 흑백 이진 마스크라 path tracing 이 필요 없다.  EEVEE 로 뽑으면
    # 같은 픽셀을 2.2~5.4 배 빠르게 얻는다 (실측 15건 diff 0, 씬이 복잡할수록 큼).
    # **기본은 OFF** — production 동작을 바꾸지 않는다.
    ebk_engine = scene.render.engine
    eevee_restore = {}
    if HOLDOUT_TUNING["engine"] == "eevee":
        target = _eevee_engine_name()
        if target is not None:
            scene.render.engine = target
            ee = getattr(scene, "eevee", None)
            if ee is not None:
                for attr, value in (("taa_render_samples", 1),
                                    ("use_gtao", False), ("use_ssr", False),
                                    ("use_soft_shadows", False)):
                    if hasattr(ee, attr):
                        eevee_restore[attr] = getattr(ee, attr)
                        setattr(ee, attr, value)
    scene.render.filepath = path
    scene.render.image_settings.color_mode = "BW"
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        _ee = getattr(scene, "eevee", None)
        for attr, value in eevee_restore.items():
            if _ee is not None:
                setattr(_ee, attr, value)
        scene.render.engine = ebk_engine
        scene.cycles.samples = sbk
        scene.cycles.use_denoising = dbk
        scene.render.filepath = fbk
        scene.render.image_settings.color_mode = cbk
        scene.world = wbk
        scene.view_settings.view_transform = vbk
        scene.view_settings.exposure = ebk
        for mesh_data, materials in data_backup.values():
            mesh_data.materials.clear()
            for material in materials:
                mesh_data.materials.append(material)
        for name, slots in object_slot_backup.items():
            ob = bpy.data.objects.get(name)
            if not ob:
                continue
            for index, (link, material) in enumerate(slots):
                if index >= len(ob.material_slots):
                    continue
                slot = ob.material_slots[index]
                slot.link = link
                slot.material = material
        for m, hr, hv in hide_backup:
            m.hide_render = hr
            m.hide_viewport = hv
        bpy.context.view_layer.update()
    return _mask_area(path)


def _mask_area(path):
    from PIL import Image
    arr = np.array(Image.open(path).convert("L"))
    return int((arr > 127).sum()), arr


# G1.6 탐색 조정값.  프로세스당 CLI 인자로 한 번만 설정하고, 모든 record 에 그대로
# 기록되므로 어떤 설정으로 만든 프레임인지 사후에 확인할 수 있다.
#   target_seed_free_cap : 앞 K개 unique target-seed 후보만 예산 면제 (None=무제한)
#   near_miss_gap_threshold : 이 값 이하의 목표오차 간격만 fine refinement 대상
#   constraint_rescue_* : G1.7 constraint-directed rescue.  기본은 "off" 이며
#     production 동작을 바꾸지 않는다 (§5) — benchmark 에서만 "side_g1" 을 준다.
SEARCH_TUNING = {
    "target_seed_free_cap": None,
    "near_miss_gap_threshold": None,
    "constraint_rescue_mode": SP2.CONSTRAINT_RESCUE_DEFAULT_MODE,
    "constraint_rescue_beam": SP2.RESCUE_BEAM_MAX,
    "constraint_rescue_eval_max": SP2.RESCUE_EVAL_MAX_PER_CASE,
    "constraint_rescue_category_max": SP2.RESCUE_EVAL_MAX_PER_CATEGORY,
}


def set_search_tuning(target_seed_free_cap=None, near_miss_gap_threshold=None,
                      constraint_rescue_mode=None, constraint_rescue_beam=None,
                      constraint_rescue_eval_max=None,
                      constraint_rescue_category_max=None):
    """탐색 조정값을 설정한다 (프로세스당 1회, 렌더 시작 전)."""
    SEARCH_TUNING["target_seed_free_cap"] = (
        None if target_seed_free_cap is None else int(target_seed_free_cap))
    SEARCH_TUNING["near_miss_gap_threshold"] = (
        None if near_miss_gap_threshold is None
        else float(near_miss_gap_threshold))
    mode = (SP2.CONSTRAINT_RESCUE_DEFAULT_MODE if constraint_rescue_mode is None
            else str(constraint_rescue_mode))
    if mode not in SP2.CONSTRAINT_RESCUE_MODES:
        raise ValueError("unknown constraint_rescue_mode: %r" % (mode,))
    SEARCH_TUNING["constraint_rescue_mode"] = mode
    SEARCH_TUNING["constraint_rescue_beam"] = (
        SP2.RESCUE_BEAM_MAX if constraint_rescue_beam is None
        else int(constraint_rescue_beam))
    SEARCH_TUNING["constraint_rescue_eval_max"] = (
        SP2.RESCUE_EVAL_MAX_PER_CASE if constraint_rescue_eval_max is None
        else int(constraint_rescue_eval_max))
    SEARCH_TUNING["constraint_rescue_category_max"] = (
        SP2.RESCUE_EVAL_MAX_PER_CATEGORY
        if constraint_rescue_category_max is None
        else int(constraint_rescue_category_max))
    return dict(SEARCH_TUNING)


_LOWRES_RENDER_COUNT = 0


def _lowres_holdout(
    scene,
    pallet_root,
    extra_hide=(),
    only_white=None,
    token="mask",
    size=128,
):
    # 저해상도 holdout 이 controlled 파이프라인 비용의 대부분이다 (baseline: 실패
    # 94건의 explicit 단계 3,118초).  프레임별로 몇 번 돌았는지 세어 record 에 남긴다.
    global _LOWRES_RENDER_COUNT
    _LOWRES_RENDER_COUNT += 1
    old_x = scene.render.resolution_x
    old_y = scene.render.resolution_y
    old_pct = scene.render.resolution_percentage
    tmp_dir = bpy.app.tempdir or tempfile.gettempdir()
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(
        tmp_dir,
        f"sv2_{os.getpid()}_{str(token).replace(os.sep, '_')}.png",
    )
    try:
        if isinstance(size, (list, tuple)):
            if len(size) != 2:
                raise ValueError("lowres size tuple must be (width, height)")
            lowres_w = int(size[0])
            lowres_h = int(size[1])
        else:
            lowres_w = int(size)
            lowres_h = int(size)
        if lowres_w <= 0 or lowres_h <= 0:
            raise ValueError("lowres size must be positive")
        scene.render.resolution_x = lowres_w
        scene.render.resolution_y = lowres_h
        scene.render.resolution_percentage = 100
        return _render_holdout(
            scene,
            pallet_root,
            path,
            extra_hide=extra_hide,
            only_white=only_white,
        )
    finally:
        scene.render.resolution_x = old_x
        scene.render.resolution_y = old_y
        scene.render.resolution_percentage = old_pct
        try:
            os.remove(path)
        except OSError:
            pass


def _lowres_stage_areas(
    scene,
    pallet,
    cargo,
    context,
    explicit,
    token,
    size=128,
):
    dynamic = [*cargo, *context, *([explicit] if explicit is not None else [])]
    m0, _ = _lowres_holdout(
        scene,
        pallet,
        extra_hide=_all_nonpallet_visible(pallet),
        token=f"{token}_m0",
        size=size,
    )
    m1, _ = _lowres_holdout(
        scene,
        pallet,
        extra_hide=dynamic,
        token=f"{token}_m1",
        size=size,
    )
    m2, _ = _lowres_holdout(
        scene,
        pallet,
        extra_hide=[*context, *([explicit] if explicit is not None else [])],
        token=f"{token}_m2",
        size=size,
    )
    m3, _ = _lowres_holdout(
        scene,
        pallet,
        extra_hide=[explicit] if explicit is not None else [],
        token=f"{token}_m3",
        size=size,
    )
    m4, _ = _lowres_holdout(
        scene,
        pallet,
        token=f"{token}_m4",
        size=size,
    )
    try:
        return SP2.decompose_mask_areas(m0, m1, m2, m3, m4, tol=1.0)
    except ValueError:
        # Preserve observed areas for diagnosis.  The final-resolution measure
        # remains authoritative and marks the invariant failure explicitly.
        return {
            "mask_area_target_only": float(m0),
            "mask_area_after_static": float(m1),
            "mask_area_after_cargo": float(m2),
            "mask_area_after_context": float(m3),
            "mask_area_visible": float(m4),
            "f_static": max(0.0, float(m0 - m1) / m0) if m0 else 0.0,
            "f_cargo": max(0.0, float(m1 - m2) / m0) if m0 else 0.0,
            "f_context": max(0.0, float(m2 - m3) / m0) if m0 else 0.0,
            "f_explicit": max(0.0, float(m3 - m4) / m0) if m0 else 0.0,
            "f_total": max(0.0, float(m0 - m4) / m0) if m0 else 0.0,
            "occlusion_decomposition_order": ["M0", "M1", "M2", "M3", "M4"],
        }


def _polygon_area(points):
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


def _bilinear_grid(quad, steps=5):
    quad = np.asarray(quad, dtype=np.float64)
    tl, tr, br, bl = quad
    values = np.linspace(0.1, 0.9, int(steps))
    points = []
    for v in values:
        left = (1.0 - v) * tl + v * bl
        right = (1.0 - v) * tr + v * br
        for u in values:
            points.append((1.0 - u) * left + u * right)
    return np.asarray(points, dtype=np.float64)


def _ray_visibility_fraction(scene, camera_pos, points):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = mathutils.Vector(tuple(float(v) for v in camera_pos))
    visible = 0
    total = 0
    for point in np.asarray(points, dtype=np.float64):
        target = mathutils.Vector(tuple(float(v) for v in point))
        direction = target - origin
        distance = float(direction.length)
        if distance <= 1e-6:
            continue
        direction.normalize()
        hit, _, _, _, _, _ = scene.ray_cast(
            depsgraph,
            origin,
            direction,
            distance=max(0.0, distance * 0.995),
        )
        total += 1
        visible += int(not hit)
    return (float(visible) / float(total)) if total else None


def _measure_front_opening_visibility(rs):
    scene = rs["scene"]
    pobj = rs["pallet"]
    cam_pos = np.asarray(rs["cam_pos"], dtype=np.float64)
    cam_look = np.asarray(rs["cam_look"], dtype=np.float64)
    K = np.asarray(rs["K"], dtype=np.float64)
    geom = get_pallet_geometry(rs["pallet_name"], pobj, ORIENTATION_OVERRIDES)
    corners = np.asarray(geom["corners_world"], dtype=np.float64)
    R, t = build_view_matrix(cam_pos, cam_look, up=(0, 0, 1))
    uv, _ = _project(K, R, t, corners)
    perm, _, _ = compute_perm_v4(
        corners,
        uv,
        cam_pos=cam_pos,
        return_margin=True,
    )
    corners_v4 = corners[perm]
    uv_v4 = uv[perm]
    front_area = _polygon_area(uv_v4[:4])
    base = {
        "front_face_visibility": None,
        "left_opening_visibility": None,
        "right_opening_visibility": None,
        "opening_visibility_reason": None,
        "kp12": None,
    }
    if not math.isfinite(front_area) or front_area < 25.0:
        base["opening_visibility_reason"] = "front_projection_too_small"
        return base

    kp12 = compute_efront_kp12(
        rs["pallet_name"],
        corners_v4,
        perm,
        K,
        R,
        t,
        image_wh=(rs["W"], rs["H"]),
    )
    base["kp12"] = efront_result_to_json(kp12)
    front_visibility = _ray_visibility_fraction(
        scene,
        cam_pos,
        _bilinear_grid(corners_v4[:4], steps=5),
    )
    base["front_face_visibility"] = (
        None if front_visibility is None else round(front_visibility, 4)
    )
    if not kp12.get("kp12_valid"):
        reason = (kp12.get("opening_meta") or {}).get("reason")
        base["opening_visibility_reason"] = reason or "kp12_invalid"
        return base

    kp3 = np.asarray(kp12["kp12_3d"], dtype=np.float64)
    kp2 = np.asarray(kp12["kp12_2d"], dtype=np.float64)
    if _polygon_area(kp2[4:8]) < 4.0 or _polygon_area(kp2[8:12]) < 4.0:
        base["opening_visibility_reason"] = "opening_projection_too_small"
        return base
    left = _ray_visibility_fraction(
        scene,
        cam_pos,
        _bilinear_grid(kp3[4:8], steps=3),
    )
    right = _ray_visibility_fraction(
        scene,
        cam_pos,
        _bilinear_grid(kp3[8:12], steps=3),
    )
    base["left_opening_visibility"] = None if left is None else round(left, 4)
    base["right_opening_visibility"] = None if right is None else round(right, 4)
    return base


def _target_seed_budget_fields(explicit_search):
    """§3 target-seed 예산 회계를 프레임 단위로 합산해 record 에 남긴다."""
    if explicit_search is None:
        return {"target_seed_free_cap": None, "target_seed_unique_count": None,
                "target_seed_free_used": None, "target_seed_paid_used": None,
                "target_seed_duplicate_count": None}
    per_proposal = explicit_search.get("target_seed_budget_all") or []
    tuning = explicit_search.get("tuning") or {}
    return {
        "target_seed_free_cap": tuning.get("target_seed_free_cap"),
        "target_seed_unique_count": sum(
            int(entry.get("target_seed_unique_count") or 0)
            for entry in per_proposal),
        "target_seed_free_used": sum(
            int(entry.get("target_seed_free_used") or 0)
            for entry in per_proposal),
        "target_seed_paid_used": sum(
            int(entry.get("target_seed_paid_used") or 0)
            for entry in per_proposal),
        "target_seed_duplicate_count": sum(
            int(entry.get("target_seed_duplicate_count") or 0)
            for entry in per_proposal),
    }


def _fine_refinement_fields(explicit_search):
    """§4 near-miss fine refinement 계측 (실행 안 됐으면 triggered=False)."""
    keys = ("fine_triggered", "fine_trigger_reason", "fine_source_stage",
            "fine_source_score", "fine_score_margin_before", "fine_eval_count",
            "fine_best_score", "fine_score_margin_after", "fine_won",
            "fine_runtime_s", "near_miss_gap_threshold")
    if explicit_search is None:
        return {key: None for key in keys}
    state = explicit_search.get("fine_state") or {}
    tuning = explicit_search.get("tuning") or {}
    return {
        "fine_triggered": bool(state.get("triggered")),
        "fine_trigger_reason": state.get("trigger_reason"),
        "fine_source_stage": state.get("source_stage"),
        "fine_source_score": state.get("source_score"),
        "fine_score_margin_before": state.get("margin_before"),
        "fine_eval_count": int(state.get("evals") or 0),
        "fine_best_score": state.get("best_score"),
        "fine_score_margin_after": state.get("margin_after"),
        "fine_won": bool(state.get("won")),
        "fine_runtime_s": round(float(state.get("runtime_s") or 0.0), 6),
        "near_miss_gap_threshold": tuning.get("near_miss_gap_threshold"),
    }


RESCUE_RECORD_KEYS = (
    "rescue_triggered", "rescue_binding_signatures", "rescue_beam_size",
    "rescue_eval_count", "rescue_duplicate_skips", "rescue_axis_sequence",
    "rescue_seed_types", "rescue_categories", "rescue_constraint_before",
    "rescue_constraint_after", "rescue_won", "rescue_runtime_s",
    "rescue_final_constraint_vector", "constraint_rescue_mode",
    "constraint_rescue_beam", "constraint_rescue_eval_max",
    "constraint_rescue_category_max",
)


def _vector_summary(vector):
    """record 에 넣을 constraint vector 요약 (JSON 직렬화 가능한 값만)."""
    if not vector:
        return None
    keep = ("side_pass", "visibility_margin_px", "target_margin", "G1_margin",
            "G2_margin", "acceptance_pass_count", "accepted")
    out = {k: vector.get(k) for k in keep if k in vector}
    if vector.get("violated") is not None:
        out["violated"] = list(vector["violated"])
    return out or None


def _constraint_rescue_fields(explicit_search):
    """§9 constraint-directed rescue 계측 (실행 안 됐으면 triggered=False)."""
    if explicit_search is None:
        return {key: None for key in RESCUE_RECORD_KEYS}
    state = explicit_search.get("rescue_state") or {}
    tuning = explicit_search.get("tuning") or {}
    return {
        "rescue_triggered": bool(state.get("triggered")),
        "rescue_binding_signatures": list(state.get("binding_signatures") or ()),
        "rescue_beam_size": int(state.get("beam_size") or 0),
        "rescue_eval_count": int(state.get("evals") or 0),
        "rescue_duplicate_skips": int(state.get("duplicate_skips") or 0),
        "rescue_axis_sequence": list(state.get("axis_sequence") or ()),
        "rescue_seed_types": list(state.get("seed_types") or ()),
        "rescue_categories": list(state.get("categories") or ()),
        "rescue_constraint_before": _vector_summary(
            state.get("constraint_before")),
        "rescue_constraint_after": _vector_summary(
            state.get("constraint_after")),
        "rescue_won": bool(state.get("won")),
        "rescue_runtime_s": round(float(state.get("runtime_s") or 0.0), 6),
        "rescue_final_constraint_vector": _vector_summary(
            state.get("final_constraint_vector")),
        "constraint_rescue_mode": tuning.get("constraint_rescue_mode"),
        "constraint_rescue_beam": tuning.get("constraint_rescue_beam"),
        "constraint_rescue_eval_max": tuning.get("constraint_rescue_eval_max"),
        "constraint_rescue_category_max": tuning.get(
            "constraint_rescue_category_max"),
    }


def _occlusion_side_from_masks(before, after):
    before = np.asarray(before) > 127
    after = np.asarray(after) > 127
    if before.shape != after.shape:
        return None
    lost = before & ~after
    ys, xs = np.nonzero(lost)
    target_ys, target_xs = np.nonzero(before)
    if xs.size == 0 or target_xs.size == 0:
        return None
    x = float(xs.mean())
    y = float(ys.mean())
    x0, x1 = float(target_xs.min()), float(target_xs.max())
    y0, y1 = float(target_ys.min()), float(target_ys.max())
    if y >= y0 + (2.0 / 3.0) * max(1.0, y1 - y0):
        return "bottom"
    if x <= x0 + (1.0 / 3.0) * max(1.0, x1 - x0):
        return "left"
    if x >= x0 + (2.0 / 3.0) * max(1.0, x1 - x0):
        return "right"
    return "center"


@contextmanager
def deterministic_rgb_render_settings(scene):
    """Use the deterministic CPU path for one final RGB render, then restore."""
    device_backup = scene.cycles.device
    adaptive_backup = scene.cycles.use_adaptive_sampling
    denoising_backup = scene.cycles.use_denoising
    threads_mode_backup = scene.render.threads_mode
    threads_backup = scene.render.threads
    scene.cycles.device = "CPU"
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 1
    try:
        yield
    finally:
        scene.cycles.device = device_backup
        scene.cycles.use_adaptive_sampling = adaptive_backup
        scene.cycles.use_denoising = denoising_backup
        scene.render.threads_mode = threads_mode_backup
        scene.render.threads = threads_backup


@contextmanager
def quality_rgb_render_settings(scene, denoiser="OPENIMAGEDENOISE"):
    """GPU + adaptive sampling + OIDN denoise for one final RGB render, then restore.

    NOT bit-reproducible (GPU + adaptive) — that is what `diagnostic-exact` is for.
    This path exists so a *clean*-tier training frame does not ship Cycles speckle."""
    device_backup = scene.cycles.device
    adaptive_backup = scene.cycles.use_adaptive_sampling
    denoising_backup = scene.cycles.use_denoising
    denoiser_backup = getattr(scene.cycles, "denoiser", None)
    try:
        scene.cycles.device = "GPU"
    except Exception:
        pass
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = denoiser
    except Exception:
        pass
    try:
        yield
    finally:
        scene.cycles.device = device_backup
        scene.cycles.use_adaptive_sampling = adaptive_backup
        scene.cycles.use_denoising = denoising_backup
        if denoiser_backup is not None:
            try:
                scene.cycles.denoiser = denoiser_backup
            except Exception:
                pass


# Render profiles.  `diagnostic-exact` is the shipped 500-record diagnostic path and must
# stay byte-reproducible.  `dataset-quality` is the training-frame path: 64 samples + OIDN
# was measured (4 brightest-exposure frames, Immerkaer noise estimate vs a 1024-sample
# reference) as the cheapest setting whose excess noise is |<=0.01| grey levels — 16 samples
# without denoise leaves +0.39..+1.97, 16+OIDN OVER-smooths (-0.23), 32+OIDN still -0.03,
# and 128+OIDN only buys ~10% more RMSE for ~30% more time.  See _docs/history/2026-07-27.md.
RENDER_PROFILES = {
    "diagnostic-exact": {
        "samples": 16,
        "deterministic_cpu": True,
    },
    "dataset-quality": {
        "samples": 64,
        "deterministic_cpu": False,
        "denoiser": "OPENIMAGEDENOISE",
    },
}
DEFAULT_RENDER_PROFILE = "diagnostic-exact"


def render(rs, rgb_path, samples=None, deterministic_cpu=False, profile=None):
    """Render the RGB frame (Cycles).

    profile=None keeps the legacy call contract (explicit samples + deterministic_cpu).
    profile in RENDER_PROFILES selects samples/device/denoise as a set; an explicit
    `samples` argument still wins so a smoke run can lower the cost."""
    scene = rs["scene"]
    settings = RENDER_PROFILES[profile] if profile else {}
    n_samples = int(samples) if samples is not None else int(settings.get("samples", 16))
    exact = bool(settings["deterministic_cpu"]) if profile else bool(deterministic_cpu)
    scene.cycles.samples = n_samples
    scene.render.filepath = rgb_path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    if exact:
        with deterministic_rgb_render_settings(scene):
            bpy.ops.render.render(write_still=True)
    elif profile:
        with quality_rgb_render_settings(scene, settings.get("denoiser", "OPENIMAGEDENOISE")):
            bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(write_still=True)
    return rgb_path


def dark_factor(luma_actual):
    """0 (bright) .. 1 (pitch black) from the RAW frame luma; drives the in-tier sigma push."""
    if luma_actual is None:
        return 0.0
    return min(1.0, max(0.0, (60.0 - float(luma_actual)) / 60.0))


def render_post(rgb_path, seed, luma_actual, tier=None):
    """Sensor post-effects on the saved RGB.

    tier=None (legacy drivers): unchanged behaviour, returns the float noise_scale.
    tier="auto"/<tier name>: tiered degradation, returns the applied-effects dict
    (noise_tier / wb_gain_rgb / vignette_* / blur_* / gaussian_* / jpeg_*)."""
    if tier is None:
        noise_scale = 1.0 + dark_factor(luma_actual) * 1.5  # dark -> up to 2.5x
        try:
            CE.apply(rgb_path, seed, noise_scale=noise_scale)
        except TypeError:
            CE.apply(rgb_path, seed)  # legacy signature (no noise_scale)
        return noise_scale
    effects = CE.apply(rgb_path, seed, tier=tier, dark_factor=dark_factor(luma_actual))
    effects["dark_factor"] = round(dark_factor(luma_actual), 4)
    return effects


# ---------------------------------------------------------------------------
# MEASURE
# ---------------------------------------------------------------------------
def _project(K, R, t, pts):
    cam = (R @ np.asarray(pts).T).T + t
    uv = (K @ cam.T).T
    uv2 = uv[:, :2] / uv[:, 2:3]
    return uv2, cam[:, 2]


def _corner_occlusion(scene, cam, corner_world, pallet_set, image_dir_px=6.0, K=None, R=None, t=None):
    """Continuous per-corner external occlusion in [0,1]: cast 9 rays (corner + 8 jittered by
    ~image_dir_px pixels in the image plane) and return the fraction blocked by a NON-pallet
    mesh nearer than the corner. Raises with the corner in the air still measure the line of
    sight to that 3D point."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = mathutils.Vector(tuple(cam))
    base = np.asarray(corner_world, dtype=np.float64)
    # image-plane basis at the corner depth (approx) using camera right/up from R.
    right = R[0]
    up = -R[1]
    offs = [(0, 0)]
    for a in range(8):
        ang = a * math.pi / 4.0
        offs.append((math.cos(ang), math.sin(ang)))
    dist_corner = float(np.linalg.norm(base - np.asarray(cam)))
    world_px = dist_corner / float(K[0, 0]) * image_dir_px if K is not None else 0.02
    blocked = 0
    total = 0
    for ox, oy in offs:
        tgt = base + right * (ox * world_px) + up * (oy * world_px)
        d = mathutils.Vector(tuple(tgt)) - origin
        L = d.length
        if L < 1e-6:
            continue
        d = d / L
        hit, loc, nrm, idx, ob, mat = scene.ray_cast(depsgraph, origin, d, distance=L * 0.999)
        total += 1
        if hit and ob is not None and ob not in pallet_set:
            if (mathutils.Vector(loc) - origin).length < L - 1e-4:
                blocked += 1
    return (blocked / total) if total else 0.0


def _candidate_corner_gate_metrics(
    scene,
    cam_pos,
    cam_look,
    pallet_obj,
    pallet_name,
    K,
    width,
    height,
):
    """Measure the same external-corner contract used by final G1/G2."""
    geometry = get_pallet_geometry(
        pallet_name,
        pallet_obj,
        ORIENTATION_OVERRIDES,
    )
    corners = np.asarray(geometry["corners_world"], dtype=np.float64)
    R, t = build_view_matrix(cam_pos, cam_look, up=(0, 0, 1))
    uv, depth = _project(K, R, t, corners)
    permutation, _, _ = compute_perm_v4(
        corners,
        uv,
        cam_pos=cam_pos,
        return_margin=True,
    )
    corners_v4 = corners[permutation]
    uv_v4 = uv[permutation]
    depth_v4 = depth[permutation]
    in_frame = [
        bool(
            depth_v4[index] > 1e-9
            and 0.0 <= uv_v4[index, 0] <= width
            and 0.0 <= uv_v4[index, 1] <= height
        )
        for index in range(8)
    ]
    pallet_set = {pallet_obj, *pallet_obj.children_recursive}
    fractions = [
        _corner_occlusion(
            scene,
            cam_pos,
            corners_v4[index],
            pallet_set,
            K=K,
            R=R,
            t=t,
        )
        for index in range(8)
    ]
    metrics = SP2.external_corner_gate_metrics(in_frame, fractions)
    metrics["in_frame"] = in_frame
    metrics["occlusion_fractions"] = fractions
    return metrics


def _measure_ground_continuity(rs, centroid_world):
    """Ground-continuity audit for the realized frame (Phase 2).

    The procedural floor is a FINITE 50 m quad centred under the pallet assembly, so a
    far camera can shoot past its border and expose bare HDRI; a floating pallet/camera
    shows up the same way (rays under the segment stop hitting a support surface). Probing
    the camera->pallet ground segment catches both. Dynamic objects are hidden so each ray
    reports the ground itself, not the cargo/occluder standing on it."""
    pobj = rs["pallet"]
    floor_mode = rs.get("floor_mode")
    floor_obj = get_obj(cfg.FLOOR_PLANE_NAME) if floor_mode == "plane" else None
    if floor_obj is not None and floor_obj.hide_render:
        floor_obj = None

    support_objects = list(rs.get("support_objects") or [])
    if not support_objects and floor_obj is not None:
        support_objects = [floor_obj]

    hide = [pobj, *(rs.get("cargo") or []), *(rs.get("context") or [])]
    if rs.get("occluder") is not None:
        hide.append(rs["occluder"])

    plane_size = float(cfg.FLOOR_PLANE_SIZE) if floor_obj is not None else None
    plane_center_xy = (
        (float(floor_obj.location.x), float(floor_obj.location.y))
        if floor_obj is not None
        else None
    )
    cam_pos = np.asarray(rs["cam_pos"], dtype=np.float64)
    start_z = max(float(cam_pos[2]), float(object_top_z_world(pobj)), 0.0) + 2.0
    return SV2.check_ground_continuity(
        cam_pos,
        (float(centroid_world[0]), float(centroid_world[1])),
        support_objects,
        floor_object=floor_obj,
        plane_size=plane_size,
        plane_center_xy=plane_center_xy,
        hide_objects=hide,
        ray_start_z=start_z,
        ray_distance=start_z + 10.0,
    )


def _visible_mask_path(rs, masks, prefix):
    """Path of the mask holding the ACTUALLY-VISIBLE pallet pixels (M4 / _visible.png)."""
    if rs.get("placement_mode") == "constrained":
        return (masks.get("mask_paths") or {}).get("m4")
    return (prefix + "_visible.png") if prefix else None


def _load_visible_mask(path):
    """Decode a holdout mask into a boolean array (True = pallet pixel). None if absent."""
    if not path or not os.path.isfile(path):
        return None
    from PIL import Image

    return np.array(Image.open(path).convert("L")) > 127


def _measure_luma(rgb_path, visible_mask):
    """(frame mean, visible-pallet mean) luma of the RGB currently on disk.

    Called twice per frame: once on the raw render, once on the post-effect image. The mask
    is passed in (never re-rendered) so both calls index exactly the same pixels."""
    if not rgb_path or not os.path.isfile(rgb_path):
        return None, None
    from PIL import Image

    arr = np.array(Image.open(rgb_path).convert("L")).astype(np.float32)
    luma_frame = float(round(arr.mean(), 2))
    luma_pallet = None
    # pallet-region luma via the VISIBLE mask (actually-visible pixels), so G5 judges the
    # brightness of what the camera really sees. (unocc mask would report a bright pallet
    # even when the visible part is dark/occluded.) If nothing is visible -> None.
    if visible_mask is not None and visible_mask.shape == arr.shape and visible_mask.sum() > 0:
        luma_pallet = float(round(arr[visible_mask].mean(), 2))
    return luma_frame, luma_pallet


def measure_final_rgb_quality(rs, meas=None):
    """Re-read the FINAL RGB (post-effects already applied in place) and re-measure luma.

    Reuses the visible mask decoded by measure_geometry_and_masks — no mask is re-rendered
    and no geometry is recomputed. This is what G5 and the label must judge, because it is
    the image the training run actually sees."""
    mask = None
    if isinstance(meas, dict):
        mask = meas.get("_visible_mask")
        if mask is None:
            mask = _load_visible_mask(meas.get("visible_mask_path"))
    luma_frame, luma_pallet = _measure_luma(rs.get("rgb_path"), mask)
    return {"luma_frame_final": luma_frame, "luma_pallet_final": luma_pallet}


def measure(rs):
    """Backward-compatible wrapper: geometry/mask measurement + final-RGB quality.

    NOTE: called before render_post (the legacy driver order) the *_final values simply equal
    the raw ones, because nothing has degraded the PNG yet. New callers must use
    measure_geometry_and_masks -> render_post -> measure_final_rgb_quality so that the gates
    and the label describe the image on disk."""
    meas = measure_geometry_and_masks(rs)
    meas.update(measure_final_rgb_quality(rs, meas))
    return meas


def measure_geometry_and_masks(rs):
    """Measure the ACTUAL realized frame. Renders the 3 holdout masks (unoccluded / after-cargo
    / visible), the per-corner occlusion by raycast, V_actual, RAW luma, ground continuity and
    the azimuth-facing perm/front_cos/facing_margin. Everything here is independent of the RGB
    post-effects. Returns a meas dict (values missing -> None = 측정불가)."""
    scene = rs["scene"]
    pobj = rs["pallet"]
    K = rs["K"]
    W, H = rs["W"], rs["H"]
    cam_pos = np.array(rs["cam_pos"], dtype=np.float64)
    cam_look = np.array(rs["cam_look"], dtype=np.float64)

    geom = get_pallet_geometry(rs["pallet_name"], pobj, ORIENTATION_OVERRIDES)
    corners_world = geom["corners_world"]
    centroid_world = geom["centroid_world"]
    R, t = build_view_matrix(cam_pos, cam_look, up=(0, 0, 1))
    uv8, z8 = _project(K, R, t, corners_world)
    perm, facing_margin, front_cos = compute_perm_v4(corners_world, uv8, cam_pos=cam_pos,
                                                     return_margin=True)
    corners_v4 = corners_world[perm]
    uv8_v4 = uv8[perm]
    z8_v4 = z8[perm]
    cent_uv, cent_z = _project(K, R, t, centroid_world[np.newaxis, :])
    cent_uv = cent_uv[0]

    def _inframe(u, v, zc):
        return bool(zc > 1e-9 and 0.0 <= u <= W and 0.0 <= v <= H)

    in_frame8 = [_inframe(uv8_v4[i, 0], uv8_v4[i, 1], z8_v4[i]) for i in range(8)]
    center_in_frame = _inframe(cent_uv[0], cent_uv[1], cent_z[0])

    # per-corner external occlusion (0..1) in the reordered 0..8 order (8 = centroid).
    pal_set = {pobj, *pobj.children_recursive}
    occ_frac = []
    for i in range(8):
        occ_frac.append(round(_corner_occlusion(scene, cam_pos, corners_v4[i], pal_set,
                                                 K=K, R=R, t=t), 4))
    occ_frac.append(round(_corner_occlusion(scene, cam_pos, centroid_world, pal_set,
                                            K=K, R=R, t=t), 4))

    # V metrics.
    corner_gate = SP2.external_corner_gate_metrics(
        in_frame8,
        occ_frac[:8],
    )
    V_inframe = corner_gate["V_inframe"]
    ext_occ_corners = corner_gate["ext_occ_corners"]
    V_vis = corner_gate["V_vis"]

    # Ground continuity: measured BEFORE the holdout mask passes, while the scene still
    # carries its final render visibility.
    ground = _measure_ground_continuity(rs, centroid_world)

    # Occlusion masks (paths under the run dir supplied by driver via rs['mask_prefix'] or
    # rs['mask_paths']). Legacy keeps its original three passes; constrained renders the
    # stages of its mask profile (mask_profiles.py): full-audit = M0..M4, public = M0/M4.
    prefix = rs.get("mask_prefix")
    masks = {}
    if prefix:
        if rs.get("placement_mode") == "constrained":
            cargo = list(rs.get("cargo") or [])
            context = list(rs.get("context") or [])
            explicit = rs.get("occluder")
            # Which masks this run keeps decides which holdout passes run at all: the public
            # profile renders M0/M4 only (three passes fewer) and reports the per-source
            # fractions as None, because they are NOT MEASURED - not zero.
            profile = MP.normalize_profile(rs.get("mask_profile"))
            mask_paths = rs.get("mask_paths")
            if mask_paths is None:
                mask_paths = MP.mask_paths_from_prefix(prefix, profile)
            for path in mask_paths.values():
                os.makedirs(os.path.dirname(path), exist_ok=True)
            hide_groups = {
                "all_nonpallet": _all_nonpallet_visible(pobj),
                "cargo": cargo,
                "context": context,
                "explicit": [explicit] if explicit is not None else [],
            }
            areas = {}
            for stage, extra_hide in MP.holdout_passes(profile, hide_groups):
                areas[stage], _ = _render_holdout(
                    scene,
                    pobj,
                    mask_paths[stage],
                    extra_hide=extra_hide,
                )
            decomposition, invariant = MP.decompose(areas, profile)
            masks = {
                **decomposition,
                "mask_profile": profile,
                "occlusion_decomposition_available": (
                    MP.occlusion_decomposition_available(profile)
                ),
                "mask_paths": mask_paths,
                "mask_invariants_pass": bool(invariant["valid"]),
                "mask_invariant_errors": invariant["errors"],
                # Legacy aliases remain available for downstream readers.
                "area_unocc": areas[MP.AMODAL_STAGE],
                "area_after_cargo": areas.get("m2"),
                "area_visible": areas[MP.VISIBLE_STAGE],
                "f_occ": decomposition.get("f_explicit"),
            }
        else:
            a_unocc, _ = _render_holdout(scene, pobj, prefix + "_unocc.png",
                                         extra_hide=_all_nonpallet_visible(pobj))
            a_cargo, _ = _render_holdout(scene, pobj, prefix + "_aftercargo.png",
                                         extra_hide=([rs["occluder"]] if rs["occluder"] else []))
            a_vis, _ = _render_holdout(scene, pobj, prefix + "_visible.png", extra_hide=[])
            f_cargo = (1.0 - a_cargo / a_unocc) if a_unocc > 0 else None
            f_total = (1.0 - a_vis / a_unocc) if a_unocc > 0 else None
            f_occ = (f_total - f_cargo) if (f_total is not None and f_cargo is not None) else None
            masks = {"area_unocc": a_unocc, "area_after_cargo": a_cargo, "area_visible": a_vis,
                     "f_cargo": _r4(f_cargo), "f_total": _r4(f_total), "f_occ": _r4(f_occ)}
    else:
        masks = {"area_unocc": None, "area_after_cargo": None, "area_visible": None,
                 "f_cargo": None, "f_total": None, "f_occ": None}

    # RAW luma: measured on the RGB render BEFORE the sensor post-effects. Kept for the
    # raw-vs-final delta; the gates/label judge the *_final values (measure_final_rgb_quality).
    visible_mask_path = _visible_mask_path(rs, masks, prefix)
    visible_mask = _load_visible_mask(visible_mask_path)
    luma_frame, luma_pallet = _measure_luma(rs.get("rgb_path"), visible_mask)

    visibility = (
        _measure_front_opening_visibility(rs)
        if rs.get("placement_mode") == "constrained"
        else {}
    )
    if rs.get("placement_mode") == "constrained":
        explicit_target = float(
            (rs.get("constrained_metrics") or {}).get("f_explicit_target", 0.0)
        )
        masks["f_explicit_target"] = explicit_target
        masks["f_explicit_actual"] = masks.get("f_explicit")
        masks["explicit_abs_error"] = (
            abs(float(masks["f_explicit"]) - explicit_target)
            if masks.get("f_explicit") is not None
            else None
        )
        metrics = rs.get("constrained_metrics") or {}
        metrics.update(
            {
                **{
                    key: masks.get(key)
                    for key in (
                        "mask_area_target_only",
                        "mask_area_after_static",
                        "mask_area_after_cargo",
                        "mask_area_after_context",
                        "mask_area_visible",
                        "f_static",
                        "f_cargo",
                        "f_context",
                        "f_explicit",
                        "f_total",
                        "occlusion_decomposition_order",
                        "f_explicit_target",
                        "f_explicit_actual",
                        "explicit_abs_error",
                    )
                },
                "front_face_visibility": visibility.get(
                    "front_face_visibility"
                ),
                "left_opening_visibility": visibility.get(
                    "left_opening_visibility"
                ),
                "right_opening_visibility": visibility.get(
                    "right_opening_visibility"
                ),
                "opening_visibility_reason": visibility.get(
                    "opening_visibility_reason"
                ),
            }
        )
        rs["constrained_metrics"] = metrics

    return {
        "perm": [int(p) for p in perm],
        "corners_v4": corners_v4, "uv8_v4": uv8_v4, "cent_uv": cent_uv,
        "centroid_world": centroid_world, "r_for_pose": geom["r_for_pose"],
        "R_w2c": R, "t_w2c": t,
        "front_cos": _r4(front_cos), "facing_margin_deg": _r4(facing_margin),
        "in_frame8": in_frame8, "center_in_frame": center_in_frame,
        "V_inframe": V_inframe, "V_vis": V_vis, "ext_occ_corners": ext_occ_corners,
        "occlusion_fraction": occ_frac,
        # legacy aliases (== raw): existing drivers/records keep reading these.
        "luma_frame": luma_frame, "luma_pallet": luma_pallet,
        "luma_frame_raw": luma_frame, "luma_pallet_raw": luma_pallet,
        "visible_mask_path": visible_mask_path,
        "_visible_mask": visible_mask,   # cached for measure_final_rgb_quality (no re-render)
        "explicit_occluder_present": bool(
            rs.get("explicit_occluder_present", rs["plan"].occluder is not None)
        ),
        **ground,
        **visibility,
        **masks,
    }


def _all_nonpallet_visible(pobj):
    pal = {pobj, *pobj.children_recursive}
    return [o for o in bpy.data.objects
            if o.type == "MESH" and not o.hide_render and o not in pal]


def _r4(x):
    return None if x is None else round(float(x), 4)


# ---------------------------------------------------------------------------
# SAFETY GATES (hard)
# ---------------------------------------------------------------------------
G5_LUMA_MIN = 12.0   # VISIBLE pallet-region mean-luma floor (0..255). pitch-black-pallet reject.


def safety_gates(meas, plan):
    """Hard gates (only these reject; target!=actual does NOT). Returns per-gate bool + all."""
    occluder_present = bool(
        meas.get("explicit_occluder_present", plan.occluder is not None)
    )
    g1 = meas["V_vis"] >= 4
    if occluder_present:
        g2 = 1 <= meas["ext_occ_corners"] <= 4
    else:
        g2 = True  # no occluder placed -> G2 not applicable
    au = meas.get("area_unocc")
    av = meas.get("area_visible")
    g3 = (au is not None and av is not None and au > 0 and av >= 0.5 * au)
    g4 = bool(meas["center_in_frame"])
    # G5 judges the VISIBLE pallet region of the FINAL image (after vignette/noise/JPEG), i.e.
    # the pixels training actually sees. A dark BACKGROUND (e.g. night HDRI + low exposure)
    # must NOT reject a frame whose visible pallet is bright — so luma_frame (whole-frame mean)
    # is intentionally NOT used. lp=None => pallet not visible (0px); G3 rejects those via
    # area_visible<0.5*area_unocc, so G5 stays permissive there.
    # (luma_pallet fallback: meas dicts produced before the raw/final split.)
    lp = (
        meas["luma_pallet_final"]
        if "luma_pallet_final" in meas
        else meas.get("luma_pallet")
    )
    g5 = (lp is None or lp >= G5_LUMA_MIN)
    gates = {"G1_Vvis>=4": bool(g1), "G2_extocc_1to4": bool(g2),
             "G3_visible>=0.5unocc": bool(g3), "G4_center_inframe": bool(g4),
             "G5_luma_floor": bool(g5)}
    gates["all_pass"] = all(gates.values())
    return gates


# ---------------------------------------------------------------------------
# LABEL  (target + actual, 실측배정)
# ---------------------------------------------------------------------------
def _actual_elevation_deg(cam_pos, centroid):
    v = np.asarray(cam_pos) - np.asarray(centroid)
    horiz = math.hypot(v[0], v[1])
    return float(math.degrees(math.atan2(v[2], horiz)))


def _f_actual_bin(f_total):
    """Bin the MEASURED f_total into the 4 f bins (single-sourced cut-points in v2_pipeline)."""
    import v2_pipeline as _vp
    return _vp.f_actual_bin(f_total)


def camera_distance_actual_m(cam_pos, centroid):
    """REALIZED camera->pallet-centroid distance (m), recomputed from the final scene.

    Deliberately NOT a copy of plan.cam_distance_m: realize() re-seats the camera on the
    pallet CENTROID (not its origin) and the constrained placer translates the anchor, so the
    realized distance can drift from the sampled target. Labelling the measured value is what
    makes the camera-distance cap auditable (실측배정)."""
    v = np.asarray(cam_pos, dtype=np.float64) - np.asarray(centroid, dtype=np.float64)
    return float(np.linalg.norm(v))


def label(spec, plan, meas, rs):
    """Build the v2 label dict: per-frame K + camera-facing 0123 cuboid + TARGET and ACTUAL
    quantities + safety-gate result. Missing measured values stay None (측정불가)."""
    import v2_pipeline as _vp

    K = rs["K"]
    corners_v4 = meas["corners_v4"]
    uv8_v4 = meas["uv8_v4"]
    cent_uv = meas["cent_uv"]
    R, t = meas["R_w2c"], meas["t_w2c"]
    centroid = meas["centroid_world"]
    R_obj_cam = R @ meas["r_for_pose"]
    t_obj_cam = R @ centroid + t
    pose = np.eye(4)
    pose[:3, :3] = R_obj_cam
    pose[:3, 3] = t_obj_cam
    pitch, yaw, roll = rotation_matrix_to_euler_deg(R_obj_cam)
    width_m = float(np.linalg.norm(corners_v4[1] - corners_v4[0]))
    height_m = float(np.linalg.norm(corners_v4[3] - corners_v4[0]))
    depth_m = float(np.linalg.norm(corners_v4[4] - corners_v4[0]))
    gates = safety_gates(meas, plan)
    # camera distance: sampled TARGET vs distance RE-MEASURED from the realized scene.
    cam_dist_target = float(plan.cam_distance_m)
    cam_dist_actual = camera_distance_actual_m(rs["cam_pos"], centroid)

    return {
        "camera_data": {
            "width": rs["W"], "height": rs["H"],
            "resolution": [rs["W"], rs["H"]],
            "aspect_ratio": round(rs["W"] / rs["H"], 6),
            "aspect_label": spec.aspect,
            "intrinsics": {"fx": float(K[0, 0]), "fy": float(K[1, 1]),
                           "cx": float(K[0, 2]), "cy": float(K[1, 2])},
            "lens_mm": round(float(K[0, 0]) * SENSOR_WIDTH / rs["W"], 4),
            "fx_mode": spec.fx_mode,
            "location_worldframe": [float(v) for v in rs["cam_pos"]],
            "look_worldframe": [float(v) for v in rs["cam_look"]],
            "scene_preset": spec.scene_preset,
            "exposure_ev": round(float(spec.exposure_ev), 4),
            "background_asset": rs.get("background"),
            "floor_mode": rs.get("floor_mode"),
            "floor": rs.get("floor_info"),
        },
        "objects": [{
            "class": "pallet", "name": rs["pallet_name"],
            "source_asset": PALLET_SOURCE_ASSETS.get(rs["pallet_name"], rs["pallet_name"]),
            "keypoint_convention": "camera_dynamic_0123_v4",
            "location": [float(v) for v in t_obj_cam],
            "quaternion_xyzw": rotation_matrix_to_quat_xyzw(R_obj_cam),
            "euler_angles": {"pitch": pitch, "yaw": yaw, "roll": roll},
            "pose_transform": pose.tolist(),
            "projected_cuboid": [[float(uv8_v4[k, 0]), float(uv8_v4[k, 1])] for k in range(8)],
            "projected_cuboid_centroid": [float(cent_uv[0]), float(cent_uv[1])],
            "cuboid": [[float(corners_v4[k, j]) for j in range(3)] for k in range(8)],
            "perm_v4": meas["perm"],
            "front_visibility_cos": meas["front_cos"],
            "facing_margin": meas["facing_margin_deg"],
            "dimensions_m": {"width": width_m, "height": height_m, "depth": depth_m},
            "efront_kp12": meas.get("kp12"),
            "scene_placement_v2": (
                rs.get("constrained_metrics")
                if rs.get("placement_mode") == "constrained"
                else None
            ),
            "v2_labels": {
                "pallet_type": rs["pallet_name"],
                # --- controlled inputs (target == what realize applied) ---
                "material_variant_target": spec.material_variant,
                "material_variant_actual": rs.get("material_variant_actual"),
                "position_mode": spec.position_mode,
                # --- camera geometry: target (sampled) vs actual (measured) ---
                "elev_bin_target": spec.elev_bin,
                "elevation_deg_target": round(float(spec.elevation_deg), 3),
                "elevation_deg_actual": round(_actual_elevation_deg(rs["cam_pos"], centroid), 3),
                "azimuth_deg_target": round(float(spec.azimuth_deg), 3),
                "proj_size_bin_target": spec.proj_size_bin,
                "proj_size_ratio_target": round(float(spec.proj_size_ratio), 4),
                # --- projected size / camera distance cap (Phase 1) ---
                # projected_size_actual measures the rendered cuboid u-extent; it can OVER-read
                # when corners fall off-screen or behind the camera (known limitation, unchanged).
                "projected_size_target": round(float(spec.proj_size_ratio), 4),
                "projected_size_actual": _vp.projected_size_actual(uv8_v4, rs["W"]),
                "projected_size_feasible_lower": round(
                    float(spec.proj_size_feasible_lower), 5),
                "camera_distance_limit_m": float(plan.camera_distance_limit_m),
                "camera_distance_target_m": round(cam_dist_target, 4),
                "camera_distance_actual_m": round(cam_dist_actual, 4),
                "camera_distance_error_m": round(cam_dist_actual - cam_dist_target, 4),
                "v_target": spec.v_target,
                "V_actual": meas["V_inframe"],
                "V_vis_actual": meas["V_vis"],
                "ext_occ_corners_actual": meas["ext_occ_corners"],
                # --- occlusion: target f + measured f (실측배정) ---
                "f_target": round(float(spec.f_target), 4),
                "f_target_bin": spec.f_target_bin,
                "f_cargo": meas.get("f_cargo"),
                "f_occ": meas.get("f_occ"),
                "f_total": meas.get("f_total"),
                # measured f_total binned into the 4 f bins (실측배정: audit/label by ACTUAL, so
                # a weak-occluder frame lands in its TRUE bin, not spec.f_target_bin).
                "f_actual_bin": _f_actual_bin(meas.get("f_total")),
                "occlusion_fraction": meas["occlusion_fraction"],
                "cargo_on_prescribed": bool(spec.cargo_on),
                "cargo_on": (
                    bool(
                        (rs.get("constrained_metrics") or {}).get(
                            "n_cargo_requested", 0
                        )
                    )
                    if rs.get("placement_mode") == "constrained"
                    else bool(spec.cargo_on)
                ),
                "n_cargo_actual": rs.get("n_cargo"),
                # --- illumination ---
                # raw = the Cycles render, final = after the sensor post-effects (what the
                # PNG on disk holds and what G5 judges). luma_actual/luma_pallet_actual keep
                # their original raw meaning so existing EDA is not silently redefined.
                "exposure_ev": round(float(spec.exposure_ev), 4),
                "luma_actual": meas.get("luma_frame_raw", meas.get("luma_frame")),
                "luma_pallet_actual": meas.get("luma_pallet_raw", meas.get("luma_pallet")),
                "luma_frame_raw": meas.get("luma_frame_raw", meas.get("luma_frame")),
                "luma_pallet_raw": meas.get("luma_pallet_raw", meas.get("luma_pallet")),
                "luma_frame_final": meas.get("luma_frame_final"),
                "luma_pallet_final": meas.get("luma_pallet_final"),
                # --- sensor post-effects actually applied (Phase 3 tier) ---
                "noise_tier": meas.get("noise_tier"),
                "wb_gain_rgb": meas.get("wb_gain_rgb"),
                "vignette_applied": meas.get("vignette_applied"),
                "vignette_strength": meas.get("vignette_strength"),
                "blur_applied": meas.get("blur_applied"),
                "blur_radius_px": meas.get("blur_radius_px"),
                "gaussian_noise_applied": meas.get("gaussian_noise_applied"),
                "gaussian_sigma": meas.get("gaussian_sigma"),
                "jpeg_applied": meas.get("jpeg_applied"),
                "jpeg_quality": meas.get("jpeg_quality"),
                # --- occluder placement ---
                "occluder_asset": (plan.occluder or {}).get("name") if plan.occluder else None,
                "occluder_placed": rs.get("occluder") is not None,
                # --- mask areas ---
                "mask_area_unocc": meas.get("area_unocc"),
                "mask_area_after_cargo": meas.get("area_after_cargo"),
                "mask_area_visible": meas.get("area_visible"),
                # --- constrained source-separated visibility (additive) ---
                "placement_mode": rs.get("placement_mode", "legacy"),
                "diagnostic_mode": rs.get("diagnostic_mode"),
                "mask_area_target_only": meas.get("mask_area_target_only"),
                "mask_area_amodal": meas.get("mask_area_amodal"),
                "mask_area_after_static": meas.get("mask_area_after_static"),
                "mask_area_after_context": meas.get("mask_area_after_context"),
                "f_static": meas.get("f_static"),
                "f_context": meas.get("f_context"),
                "f_explicit": meas.get("f_explicit"),
                # Which masks this frame kept, and whether the per-source fractions above are
                # exact (full-audit) or NOT MEASURED = None (public: M1..M3 never rendered).
                "mask_profile": meas.get("mask_profile"),
                "occlusion_decomposition_available": meas.get(
                    "occlusion_decomposition_available"
                ),
                "occlusion_decomposition_order": meas.get(
                    "occlusion_decomposition_order"
                ),
                "mask_invariants_pass": meas.get("mask_invariants_pass"),
                # --- ground continuity (Phase 2) ---
                "ground_continuity_pass": meas.get("ground_continuity_pass"),
                "ground_probe_count": meas.get("ground_probe_count"),
                "ground_probe_fail_count": meas.get("ground_probe_fail_count"),
                "ground_probe_hit_objects": meas.get("ground_probe_hit_objects"),
                "ground_probe_max_step_m": meas.get("ground_probe_max_step_m"),
                "ground_probe_step_tolerance_m": meas.get(
                    "ground_probe_step_tolerance_m"
                ),
                "ground_continuity_reason": meas.get("ground_continuity_reason"),
                "procedural_floor_edge_risk": meas.get(
                    "procedural_floor_edge_risk"
                ),
                "procedural_floor_edge_margin_m": meas.get(
                    "procedural_floor_edge_margin_m"
                ),
                "front_face_visibility": meas.get("front_face_visibility"),
                "left_opening_visibility": meas.get(
                    "left_opening_visibility"
                ),
                "right_opening_visibility": meas.get(
                    "right_opening_visibility"
                ),
                "opening_visibility_reason": meas.get(
                    "opening_visibility_reason"
                ),
            },
            "safety_gates": gates,
        }],
    }
