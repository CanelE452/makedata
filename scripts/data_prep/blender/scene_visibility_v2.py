"""Constrained Blender scene-visibility helpers for v2 realization.

This module is Blender-side only: it imports ``bpy`` and is intended to be
imported lazily by ``v2_realize.py``.  It does not save or delete scene data.

Coordinate system used throughout this file:
  - Blender world coordinates, +Z up.
  - Camera local-search offsets are expressed in a camera-derived frame:
    +depth from camera toward look-at, +u camera-right, +v camera-up.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from contextlib import contextmanager

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils.bvhtree import BVHTree

try:
    import blender_config as cfg
except Exception:  # pragma: no cover - only relevant for partial Blender shells
    cfg = None

import distractor_pool_v2 as dpool
import scene_placement_v2 as placement
from pallet_geometry import (
    get_obj_aabb_world,
    get_pallet_geometry,
    mesh_overlap,
    object_bottom_z_world,
    object_top_z_world,
    set_object_pose_grounded,
    set_render_visibility,
    temporary_visible_hierarchy,
)
from randomizers import get_obj


ROLE_KEY = "sv2_role"
BASE_LOC_KEY = "sv2_base_loc_xyz"
BASE_SCALE_KEY = "sv2_base_scale_xyz"
BASE_ROT_KEY = "sv2_base_rot_euler_xyz"

ROLE_PALLET = "pallet"
ROLE_SUPPORT = "support"
ROLE_STATIC_BACKGROUND = "static_background"
ROLE_CARGO = "cargo"
ROLE_CONTEXT = "context"
ROLE_EXPLICIT_OCCLUDER = "explicit_occluder"

VALID_ROLES = {
    ROLE_PALLET,
    ROLE_SUPPORT,
    ROLE_STATIC_BACKGROUND,
    ROLE_CARGO,
    ROLE_CONTEXT,
    ROLE_EXPLICIT_OCCLUDER,
}


# ---------------------------------------------------------------------------
# Basic object, AABB, and hierarchy utilities
# ---------------------------------------------------------------------------
def _np3(v):
    arr = np.asarray(v, dtype=np.float64)
    if arr.shape != (3,):
        arr = arr.reshape(3)
    return arr


def _vec(v):
    return mathutils.Vector(tuple(float(x) for x in _np3(v)))


def _obj_name(obj):
    return obj.name if obj is not None else None


def _as_obj(obj_or_name):
    if obj_or_name is None:
        return None
    if isinstance(obj_or_name, str):
        return get_obj(obj_or_name)
    return obj_or_name


def _as_obj_list(items):
    if not items:
        return []
    out = []
    for item in items:
        obj = _as_obj(item)
        if obj is not None and obj not in out:
            out.append(obj)
    return out


def _hierarchy_members(obj):
    if obj is None:
        return []
    return [obj, *obj.children_recursive]


def _hierarchy_set(obj):
    return set(_hierarchy_members(obj))


def _iter_mesh_objects(obj):
    for member in _hierarchy_members(obj):
        if member.type == "MESH" and member.data and len(member.data.vertices) > 0:
            yield member


def _has_mesh(obj):
    return any(True for _ in _iter_mesh_objects(obj))


def _hierarchy_root(obj):
    root = obj
    while root is not None and root.parent is not None:
        root = root.parent
    return root


def _hierarchy_visible(obj, render=True):
    if obj is None:
        return False
    attr = "hide_render" if render else "hide_viewport"
    for member in _hierarchy_members(obj):
        if member.type == "MESH" and not bool(getattr(member, attr)):
            return True
    return False


def _aabb_np(obj):
    mn, mx = get_obj_aabb_world(obj)
    return np.asarray(mn, dtype=np.float64), np.asarray(mx, dtype=np.float64)


def _aabb_center(amin, amax):
    return 0.5 * (_np3(amin) + _np3(amax))


def _aabb_size(amin, amax):
    return np.maximum(0.0, _np3(amax) - _np3(amin))


def _aabb_corners(amin, amax):
    mn, mx = _np3(amin), _np3(amax)
    return np.array(
        [
            [x, y, z]
            for x in (mn[0], mx[0])
            for y in (mn[1], mx[1])
            for z in (mn[2], mx[2])
        ],
        dtype=np.float64,
    )


def _aabb_overlap(amin, amax, bmin, bmax, inflate=0.0):
    amin = _np3(amin) - float(inflate)
    amax = _np3(amax) + float(inflate)
    bmin = _np3(bmin)
    bmax = _np3(bmax)
    return bool(
        amin[0] <= bmax[0]
        and amax[0] >= bmin[0]
        and amin[1] <= bmax[1]
        and amax[1] >= bmin[1]
        and amin[2] <= bmax[2]
        and amax[2] >= bmin[2]
    )


def _aabb_contains(amin, amax, point, margin=0.0):
    mn = _np3(amin) - float(margin)
    mx = _np3(amax) + float(margin)
    p = _np3(point)
    return bool(np.all(p >= mn) and np.all(p <= mx))


def _aabb_volume(amin, amax):
    size = _aabb_size(amin, amax)
    return float(size[0] * size[1] * size[2])


def _point_aabb_distance(point, amin, amax):
    p = _np3(point)
    mn = _np3(amin)
    mx = _np3(amax)
    delta = np.maximum(np.maximum(mn - p, p - mx), 0.0)
    return float(np.linalg.norm(delta))


def _object_center(obj):
    amin, amax = _aabb_np(obj)
    return _aabb_center(amin, amax)


def _camera_basis(cam_pos, look_at):
    cam = _np3(cam_pos)
    look = _np3(look_at)
    forward = look - cam
    nf = float(np.linalg.norm(forward))
    if nf <= 1e-9:
        forward = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    else:
        forward = forward / nf
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    nr = float(np.linalg.norm(right))
    if nr <= 1e-9:
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        right = np.cross(forward, world_up)
        nr = float(np.linalg.norm(right))
    right = right / max(nr, 1e-9)
    up = np.cross(right, forward)
    up = up / max(float(np.linalg.norm(up)), 1e-9)
    return right, up, forward


def _aim_camera_object(camera_obj, cam_pos, cam_look):
    if camera_obj is None or cam_look is None:
        return
    camera_obj.location = tuple(float(v) for v in _np3(cam_pos))
    direction = _vec(cam_look) - _vec(cam_pos)
    if direction.length > 1e-9:
        camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


@contextmanager
def _temporary_hidden(objects):
    state = []
    seen = set()
    for obj in _as_obj_list(objects):
        for member in _hierarchy_members(obj):
            if member.name in seen:
                continue
            seen.add(member.name)
            state.append((member, member.hide_viewport, member.hide_render))
            member.hide_viewport = True
            member.hide_render = True
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for member, hide_viewport, hide_render in state:
            member.hide_viewport = hide_viewport
            member.hide_render = hide_render
        bpy.context.view_layer.update()


def _root_contains_obj(root, obj):
    return obj is not None and obj in _hierarchy_set(root)


def _hit_root(hit_obj, roots):
    for root in roots:
        if _root_contains_obj(root, hit_obj):
            return root
    return None


def _json_point(v):
    return [float(x) for x in _np3(v)]


def _json_aabb(obj):
    amin, amax = _aabb_np(obj)
    return {"min": _json_point(amin), "max": _json_point(amax)}


# ---------------------------------------------------------------------------
# Role registry and static inventory
# ---------------------------------------------------------------------------
def register_role(obj_or_name, role, recursive=True):
    """Tag an object hierarchy with a v2 role via custom properties."""
    if role not in VALID_ROLES:
        raise ValueError(f"unknown scene role {role!r}; expected one of {sorted(VALID_ROLES)}")
    obj = _as_obj(obj_or_name)
    if obj is None:
        return {"ok": False, "role": role, "name": str(obj_or_name), "tagged": []}
    members = _hierarchy_members(obj) if recursive else [obj]
    for member in members:
        member[ROLE_KEY] = role
    return {"ok": True, "role": role, "name": obj.name, "tagged": [m.name for m in members]}


def register_roles(role_map=None, recursive=True, **role_names):
    """Bulk role tagging.

    ``role_map`` may be ``{role: [object_name, ...]}``. Keyword arguments use
    role names directly, for example ``support=[floor_obj]``.
    """
    combined = {}
    if role_map:
        combined.update(role_map)
    combined.update({k: v for k, v in role_names.items() if v is not None})
    results = []
    for role, names in combined.items():
        if isinstance(names, (str, bytes)) or not hasattr(names, "__iter__"):
            names = [names]
        for name in names:
            results.append(register_role(name, role, recursive=recursive))
    return {
        "ok": all(r.get("ok") for r in results),
        "roles": dict(Counter(r["role"] for r in results if r.get("ok"))),
        "missing": [r["name"] for r in results if not r.get("ok")],
        "results": results,
    }


def get_role(obj_or_name, inherit=True):
    obj = _as_obj(obj_or_name)
    if obj is None:
        return None
    cur = obj
    while cur is not None:
        role = cur.get(ROLE_KEY)
        if role:
            return str(role)
        cur = cur.parent if inherit else None
    return None


def objects_by_role(role, visible_only=False, hierarchy_roots=True):
    """Return Blender objects tagged with ``role``."""
    if role not in VALID_ROLES:
        raise ValueError(f"unknown scene role {role!r}")
    out = []
    seen = set()
    for obj in bpy.data.objects:
        if get_role(obj, inherit=False) != role:
            continue
        root = _hierarchy_root(obj) if hierarchy_roots else obj
        if root.name in seen:
            continue
        if visible_only and not _hierarchy_visible(root):
            continue
        if not _has_mesh(root):
            continue
        seen.add(root.name)
        out.append(root)
    return out


def _default_movable_names():
    names = set()
    if cfg is not None:
        names.update(getattr(cfg, "PALLET_NAMES", []) or [])
        names.update(getattr(cfg, "BOX_NAMES", []) or [])
    try:
        names.update(dpool.all_object_names())
    except Exception:
        pass
    return names


def _looks_like_support_name(name):
    lower = (name or "").lower()
    return any(token in lower for token in ("floor", "ground", "plane", "terrain"))


def collect_visible_static_inventory(
    support_names=None,
    obstacle_names=None,
    floor_obj=None,
    exclude_objects=None,
    include_untagged=True,
    infer_support_from_name=True,
    render_visibility=True,
):
    """Collect visible static mesh roots, split into supports and obstacles.

    The returned object lists are for Blender callers.  The nested ``metrics``
    dict contains only JSON-serializable values.
    """
    explicit_support = set(_as_obj_list(support_names))
    explicit_obstacle = set(_as_obj_list(obstacle_names))
    floor = _as_obj(floor_obj)
    if floor is not None:
        explicit_support.add(floor)
    excluded = set()
    for obj in _as_obj_list(exclude_objects):
        excluded.update(_hierarchy_set(obj))
        excluded.add(_hierarchy_root(obj))

    movable_names = _default_movable_names()
    support_roots = []
    obstacle_roots = []
    skipped = Counter()
    seen = set()

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        # Background imports are commonly wrapped as
        # BG_root -> importer empty -> semantic empty -> mesh.  Collapsing every
        # mesh to the absolute hierarchy root turns an entire warehouse into one
        # giant AABB/BVH, so a valid anchor can never clear broad phase.  Static
        # inventory is intentionally mesh-granular; explicitly supplied support
        # or obstacle roots still classify all of their descendants below.
        root = obj
        if root.name in seen:
            continue
        seen.add(root.name)
        if root in excluded or obj in excluded:
            skipped["excluded"] += 1
            continue
        if not _has_mesh(root):
            skipped["no_mesh"] += 1
            continue
        if not _hierarchy_visible(root, render=render_visibility):
            skipped["hidden"] += 1
            continue

        role = get_role(root) or get_role(obj)
        if role in {ROLE_PALLET, ROLE_CARGO, ROLE_CONTEXT, ROLE_EXPLICIT_OCCLUDER}:
            skipped[f"role_{role}"] += 1
            continue
        is_explicit_support = any(
            root is candidate or root in _hierarchy_set(candidate)
            for candidate in explicit_support
        )
        is_explicit_obstacle = any(
            root is candidate or root in _hierarchy_set(candidate)
            for candidate in explicit_obstacle
        )
        if role == ROLE_SUPPORT or is_explicit_support:
            support_roots.append(root)
            continue
        if role == ROLE_STATIC_BACKGROUND or is_explicit_obstacle:
            obstacle_roots.append(root)
            continue
        if root.name in movable_names or obj.name in movable_names:
            skipped["known_movable"] += 1
            continue
        if not include_untagged:
            skipped["untagged"] += 1
            continue
        lineage_name = "/".join(
            member.name
            for member in (root, root.parent, root.parent.parent if root.parent else None)
            if member is not None
        )
        if infer_support_from_name and _looks_like_support_name(lineage_name):
            support_roots.append(root)
        else:
            obstacle_roots.append(root)

    support_roots = _dedupe_objects(support_roots)
    obstacle_roots = [o for o in _dedupe_objects(obstacle_roots) if o not in set(support_roots)]
    return {
        "support_objects": support_roots,
        "static_obstacle_objects": obstacle_roots,
        "all_static_objects": support_roots + obstacle_roots,
        "metrics": {
            "support": [_obj_name(o) for o in support_roots],
            "static_obstacles": [_obj_name(o) for o in obstacle_roots],
            "n_support": len(support_roots),
            "n_static_obstacles": len(obstacle_roots),
            "skipped": dict(skipped),
        },
    }


def _dedupe_objects(objects):
    out = []
    seen = set()
    for obj in objects:
        if obj is None or obj.name in seen:
            continue
        seen.add(obj.name)
        out.append(obj)
    return out


def ensure_base_transform(obj_or_name):
    """Persist the original root transform used to reset reusable objects."""
    obj = _as_obj(obj_or_name)
    if obj is None:
        return None
    if BASE_LOC_KEY not in obj:
        obj[BASE_LOC_KEY] = [float(v) for v in obj.location]
    if BASE_SCALE_KEY not in obj:
        obj[BASE_SCALE_KEY] = [float(v) for v in obj.scale]
    if BASE_ROT_KEY not in obj:
        obj[BASE_ROT_KEY] = [float(v) for v in obj.rotation_euler]
    return {
        "location": [float(v) for v in obj[BASE_LOC_KEY]],
        "scale": [float(v) for v in obj[BASE_SCALE_KEY]],
        "rotation": [float(v) for v in obj[BASE_ROT_KEY]],
    }


def restore_base_transform(obj_or_name, visible=None):
    """Restore a reusable asset to its cached import-time transform."""
    obj = _as_obj(obj_or_name)
    base = ensure_base_transform(obj)
    if obj is None or base is None:
        return {"ok": False, "object": _obj_name(obj)}
    obj.location = tuple(float(v) for v in base["location"])
    obj.scale = tuple(float(v) for v in base["scale"])
    obj.rotation_euler = tuple(float(v) for v in base["rotation"])
    if visible is not None:
        set_render_visibility(obj, bool(visible))
    bpy.context.view_layer.update()
    return {"ok": True, "object": obj.name, "base": base}


def fresh_world_aabb(obj_or_name):
    """Measure a hierarchy after forcing hidden child matrices to refresh."""
    obj = _as_obj(obj_or_name)
    if obj is None:
        raise ValueError("object could not be resolved")
    with temporary_visible_hierarchy(obj):
        bpy.context.view_layer.update()
        return get_obj_aabb_world(obj)


def restore_base_transforms(objects, visible=None):
    results = []
    for obj in _as_obj_list(objects):
        results.append(restore_base_transform(obj, visible=visible))
    return {
        "ok": all(result.get("ok") for result in results),
        "count": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Ray, support, line-of-sight, and clearance checks
# ---------------------------------------------------------------------------
def _pallet_geometry(pallet_obj, pallet_name=None, orientation_overrides=None):
    if pallet_obj is None:
        return None
    if orientation_overrides is None and cfg is not None:
        orientation_overrides = getattr(cfg, "ORIENTATION_OVERRIDES", {})
    if orientation_overrides is None:
        orientation_overrides = {}
    return get_pallet_geometry(pallet_name or pallet_obj.name, pallet_obj, orientation_overrides)


def _pallet_support_points(pallet_obj, pallet_name=None, orientation_overrides=None):
    geom = _pallet_geometry(pallet_obj, pallet_name=pallet_name, orientation_overrides=orientation_overrides)
    if geom is not None:
        corners = np.asarray(geom["corners_world"], dtype=np.float64)
        idx = np.argsort(corners[:, 2])[:4]
        bottom = corners[idx]
        center = bottom.mean(axis=0)
        return [center] + [bottom[i] for i in range(len(bottom))]

    amin, amax = _aabb_np(pallet_obj)
    z = float(amin[2])
    pts = [
        np.array([(amin[0] + amax[0]) * 0.5, (amin[1] + amax[1]) * 0.5, z]),
        np.array([amin[0], amin[1], z]),
        np.array([amin[0], amax[1], z]),
        np.array([amax[0], amin[1], z]),
        np.array([amax[0], amax[1], z]),
    ]
    return pts


def _aabb_support_points(obj, inset_fraction=0.02):
    amin, amax = _aabb_np(obj)
    z = float(amin[2])
    mn = _np3(amin)
    mx = _np3(amax)
    cx = 0.5 * (mn[0] + mx[0])
    cy = 0.5 * (mn[1] + mx[1])
    ix = max(0.0, float(inset_fraction)) * max(0.0, mx[0] - mn[0])
    iy = max(0.0, float(inset_fraction)) * max(0.0, mx[1] - mn[1])
    return [
        np.array([cx, cy, z], dtype=np.float64),
        np.array([mn[0] + ix, mn[1] + iy, z], dtype=np.float64),
        np.array([mn[0] + ix, mx[1] - iy, z], dtype=np.float64),
        np.array([mx[0] - ix, mn[1] + iy, z], dtype=np.float64),
        np.array([mx[0] - ix, mx[1] - iy, z], dtype=np.float64),
    ]


def _spread_contact_points(points, max_points=12):
    """Select deterministic, spatially spread members of real contact vertices."""
    unique = {}
    for point in points:
        value = np.asarray(point, dtype=np.float64)
        key = tuple(round(float(axis), 6) for axis in value)
        unique.setdefault(key, value)
    values = [unique[key] for key in sorted(unique)]
    limit = max(1, int(max_points))
    if len(values) <= limit:
        return values

    xy = np.asarray([value[:2] for value in values], dtype=np.float64)
    centroid = xy.mean(axis=0)
    first = max(
        range(len(values)),
        key=lambda idx: (
            float(np.linalg.norm(xy[idx] - centroid)),
            tuple(-float(axis) for axis in values[idx]),
        ),
    )
    selected = [first]
    remaining = set(range(len(values))) - {first}
    while remaining and len(selected) < limit:
        next_idx = max(
            remaining,
            key=lambda idx: (
                min(
                    float(np.linalg.norm(xy[idx] - xy[chosen]))
                    for chosen in selected
                ),
                tuple(-float(axis) for axis in values[idx]),
            ),
        )
        selected.append(next_idx)
        remaining.remove(next_idx)
    return [values[idx] for idx in selected]


def _object_support_points(
    obj,
    inset_fraction=0.02,
    bottom_band_fraction=0.005,
    max_points=12,
):
    vertices = [
        np.asarray(vertex, dtype=np.float64)
        for vertex in _mesh_vertices_world(obj)
    ]
    if not vertices:
        return _aabb_support_points(obj, inset_fraction=inset_fraction)

    z_values = [float(vertex[2]) for vertex in vertices]
    z_min = min(z_values)
    height = max(z_values) - z_min
    band = max(
        1.0e-4,
        min(0.01, float(height) * max(0.0, float(bottom_band_fraction))),
    )
    bottom = [
        vertex
        for vertex in vertices
        if float(vertex[2]) <= z_min + band
    ]
    contacts = _spread_contact_points(bottom, max_points=max_points)
    if len({(round(float(p[0]), 6), round(float(p[1]), 6)) for p in contacts}) < 3:
        return _aabb_support_points(obj, inset_fraction=inset_fraction)
    return contacts


def _support_roots_and_set(support_objects):
    roots = _as_obj_list(support_objects)
    support_set = set()
    for root in roots:
        support_set.update(_hierarchy_set(root))
    return roots, support_set


def _support_probe_points(
    points,
    support_objects,
    *,
    ray_start_above=0.5,
    ray_distance=2.0,
    min_support_normal_z=0.5,
    height_tolerance=0.02,
    hide_objects=None,
    analytic_floor_z=None,
):
    support_roots, support_set = _support_roots_and_set(support_objects)
    if not support_set and analytic_floor_z is None:
        return {"ok": False, "reason": "no_support_objects", "samples": []}

    rows = []
    ok = True
    depsgraph = bpy.context.evaluated_depsgraph_get()
    with _temporary_hidden(_as_obj_list(hide_objects)):
        for idx, point in enumerate(points):
            point = _np3(point)
            if not support_set and analytic_floor_z is not None:
                err = float(point[2] - float(analytic_floor_z))
                row_ok = abs(err) <= float(height_tolerance)
                rows.append(
                    {
                        "idx": idx,
                        "sample": _json_point(point),
                        "mode": "analytic_plane",
                        "support": None,
                        "support_z": float(analytic_floor_z),
                        "height_error": err,
                        "normal_z": 1.0,
                        "ok": row_ok,
                    }
                )
                ok = ok and row_ok
                continue

            origin = _vec(point + np.array([0.0, 0.0, float(ray_start_above)]))
            hit, loc, normal, face_idx, hit_obj, matrix = bpy.context.scene.ray_cast(
                depsgraph,
                origin,
                mathutils.Vector((0.0, 0.0, -1.0)),
                distance=float(ray_start_above) + float(ray_distance),
            )
            support_root = _hit_root(hit_obj, support_roots)
            normal_z = float(normal.z) if hit else None
            support_z = float(loc.z) if hit and support_root is not None else None
            err = float(point[2] - support_z) if support_z is not None else None
            row_ok = bool(
                hit
                and support_root is not None
                and err is not None
                and abs(err) <= float(height_tolerance)
                and normal_z is not None
                and abs(normal_z) >= float(min_support_normal_z)
            )
            rows.append(
                {
                    "idx": idx,
                    "sample": _json_point(point),
                    "mode": "ray",
                    "hit": bool(hit),
                    "hit_object": _obj_name(hit_obj),
                    "support": _obj_name(support_root),
                    "support_z": support_z,
                    "height_error": err,
                    "normal_z": normal_z,
                    "ok": row_ok,
                }
            )
            ok = ok and row_ok
    return {"ok": bool(ok), "reason": None if ok else "support_footprint", "samples": rows}


def check_object_support(
    obj_or_name,
    support_objects=None,
    *,
    floor_z=None,
    height_tolerance=0.02,
    ray_start_above=0.5,
    ray_distance=2.0,
    min_support_normal_z=0.5,
    hide_objects=None,
    inset_fraction=0.02,
):
    """Check center plus four footprint samples under one arbitrary object."""
    obj = _as_obj(obj_or_name)
    if obj is None:
        return {"ok": False, "reason": "missing_object", "samples": []}
    points = _object_support_points(obj, inset_fraction=inset_fraction)
    hidden = [obj]
    hidden.extend(_as_obj_list(hide_objects))
    return _support_probe_points(
        points,
        support_objects or [],
        ray_start_above=ray_start_above,
        ray_distance=ray_distance,
        min_support_normal_z=min_support_normal_z,
        height_tolerance=height_tolerance,
        hide_objects=hidden,
        analytic_floor_z=floor_z if not support_objects else None,
    )


def check_pallet_support(
    pallet_obj,
    support_objects=None,
    floor_mode="plane",
    floor_obj=None,
    floor_z=0.0,
    height_tolerance=0.02,
    ray_start_above=0.5,
    ray_distance=2.0,
    min_support_normal_z=0.5,
    pallet_name=None,
    orientation_overrides=None,
):
    """Check five downward support samples under the pallet footprint."""
    support_roots = _as_obj_list(support_objects)
    floor = _as_obj(floor_obj)
    if floor is not None and floor not in support_roots:
        support_roots.append(floor)

    points = _pallet_support_points(
        pallet_obj,
        pallet_name=pallet_name,
        orientation_overrides=orientation_overrides,
    )[:5]
    return _support_probe_points(
        points,
        support_roots,
        ray_start_above=ray_start_above,
        ray_distance=ray_distance,
        min_support_normal_z=min_support_normal_z,
        height_tolerance=height_tolerance,
        hide_objects=[pallet_obj],
        analytic_floor_z=float(floor_z) if floor_mode == "plane" and not support_roots else None,
    )


def support_surface_at_xy(
    x,
    y,
    support_objects,
    ray_start_z,
    ray_distance=20.0,
    min_support_normal_z=0.5,
    hide_objects=None,
):
    """Return the first valid support hit below one world-space XY location."""
    support_roots = _as_obj_list(support_objects)
    support_set = set()
    for root in support_roots:
        support_set.update(_hierarchy_set(root))
    if not support_set:
        return {
            "ok": False,
            "reason": "no_support_objects",
            "support": None,
            "support_z": None,
            "normal_z": None,
        }

    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = mathutils.Vector((float(x), float(y), float(ray_start_z)))
    with _temporary_hidden(_as_obj_list(hide_objects)):
        hit, loc, normal, face_idx, hit_obj, matrix = bpy.context.scene.ray_cast(
            depsgraph,
            origin,
            mathutils.Vector((0.0, 0.0, -1.0)),
            distance=float(ray_distance),
        )
    support_root = _hit_root(hit_obj, support_roots)
    normal_z = float(normal.z) if hit else None
    ok = bool(
        hit
        and support_root is not None
        and normal_z is not None
        and abs(normal_z) >= float(min_support_normal_z)
    )
    return {
        "ok": ok,
        "reason": None if ok else (
            "non_support_first_hit" if hit else "support_ray_miss"
        ),
        "hit_object": _obj_name(hit_obj),
        "support": _obj_name(support_root),
        "support_z": float(loc.z) if hit and support_root is not None else None,
        "normal_z": normal_z,
    }


def _pallet_los_samples(pallet_obj, cam_pos, pallet_name=None, orientation_overrides=None):
    geom = _pallet_geometry(pallet_obj, pallet_name=pallet_name, orientation_overrides=orientation_overrides)
    if geom is not None:
        corners = np.asarray(geom["corners_world"], dtype=np.float64)
        centroid = np.asarray(geom["centroid_world"], dtype=np.float64)
    else:
        amin, amax = _aabb_np(pallet_obj)
        corners = _aabb_corners(amin, amax)
        centroid = _aabb_center(amin, amax)
    to_cam = _np3(cam_pos) - centroid
    n = float(np.linalg.norm(to_cam))
    if n <= 1e-9:
        near_idx = np.argsort(np.linalg.norm(corners - centroid[None, :], axis=1))[:4]
    else:
        scores = (corners - centroid[None, :]) @ (to_cam / n)
        near_idx = np.argsort(scores)[-4:]
    near = corners[near_idx]
    near_center = near.mean(axis=0)
    return [centroid, near_center] + [near[i] for i in range(len(near))]


def check_static_los(
    pallet_obj,
    cam_pos,
    static_blockers=None,
    samples=None,
    distance_epsilon=1e-4,
    pallet_name=None,
    orientation_overrides=None,
):
    """Check that static meshes do not block rays to pallet centroid/front samples."""
    blockers = _as_obj_list(static_blockers)
    blocker_set = set()
    for root in blockers:
        blocker_set.update(_hierarchy_set(root))
    pallet_set = _hierarchy_set(pallet_obj)
    if samples is None:
        samples = _pallet_los_samples(
            pallet_obj,
            cam_pos,
            pallet_name=pallet_name,
            orientation_overrides=orientation_overrides,
        )

    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = _vec(cam_pos)
    rows = []
    ok = True
    for idx, sample in enumerate(samples):
        sample = _np3(sample)
        target = _vec(sample)
        direction = target - origin
        dist = float(direction.length)
        if dist <= 1e-9:
            rows.append({"idx": idx, "target": _json_point(sample), "ok": False, "reason": "zero_distance"})
            ok = False
            continue
        direction.normalize()
        hit, loc, normal, face_idx, hit_obj, matrix = bpy.context.scene.ray_cast(
            depsgraph,
            origin,
            direction,
            distance=max(0.0, dist - float(distance_epsilon)),
        )
        blocked_by = None
        if hit and hit_obj not in pallet_set and hit_obj in blocker_set:
            blocked_by = hit_obj
        row_ok = blocked_by is None
        rows.append(
            {
                "idx": idx,
                "target": _json_point(sample),
                "hit": bool(hit),
                "hit_object": _obj_name(hit_obj),
                "blocked_by_static": _obj_name(blocked_by),
                "ok": row_ok,
            }
        )
        ok = ok and row_ok
    return {"ok": bool(ok), "samples": rows}


def _bvh_from_mesh_obj(mesh_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    try:
        try:
            bm.from_object(mesh_obj, depsgraph)
            bm.transform(mesh_obj.matrix_world)
            return BVHTree.FromBMesh(bm)
        except Exception:
            eval_obj = mesh_obj.evaluated_get(depsgraph)
            mesh = None
            try:
                mesh = eval_obj.to_mesh()
                if mesh is None or not mesh.vertices or not mesh.polygons:
                    return None
                matrix = eval_obj.matrix_world
                verts = [matrix @ vertex.co for vertex in mesh.vertices]
                faces = [tuple(poly.vertices) for poly in mesh.polygons]
                return BVHTree.FromPolygons(verts, faces)
            finally:
                if mesh is not None:
                    eval_obj.to_mesh_clear()
    finally:
        bm.free()


def _nearest_surface_distance(obj, point):
    point_v = _vec(point)
    best = None
    for mesh_obj in _iter_mesh_objects(obj):
        try:
            bvh = _bvh_from_mesh_obj(mesh_obj)
            if bvh is None:
                continue
            loc, normal, index, dist = bvh.find_nearest(point_v)
        except Exception:
            continue
        if loc is None:
            continue
        dist = float(dist)
        if best is None or dist < best:
            best = dist
    return best


def _point_inside_bvh_direction(bvh, point, direction):
    direction = mathutils.Vector(tuple(float(v) for v in direction))
    direction.normalize()
    origin = _vec(point)
    hit_distances = []
    travelled = 0.0
    remaining = 1.0e6
    epsilon = 1.0e-5
    for _ in range(2048):
        loc, normal, index, distance = bvh.ray_cast(origin, direction, remaining)
        if loc is None:
            break
        distance = max(float(distance), 0.0)
        hit_at = travelled + distance
        if not hit_distances or abs(hit_at - hit_distances[-1]) > 1.0e-4:
            hit_distances.append(hit_at)
        step = distance + epsilon
        origin = origin + direction * step
        travelled += step
        remaining -= step
        if remaining <= 0.0:
            break
    return bool(len(hit_distances) % 2)


def _point_inside_bvh(bvh, point):
    directions = (
        (1.0, 0.3713906763541037, 0.1931173525494168),
        (0.2718281828459045, 1.0, 0.3141592653589793),
        (0.1618033988749895, 0.5772156649015329, 1.0),
    )
    votes = 0
    for direction in directions:
        try:
            votes += int(_point_inside_bvh_direction(bvh, point, direction))
        except Exception:
            continue
    return votes >= 2


def _point_inside_bvh_legacy(bvh, point):
    direction = mathutils.Vector((1.0, 0.3713906763541037, 0.1931173525494168))
    direction.normalize()
    origin = _vec(point)
    intersections = 0
    remaining = 1.0e6
    epsilon = 1.0e-5
    for _ in range(2048):
        loc, normal, index, distance = bvh.ray_cast(origin, direction, remaining)
        if loc is None:
            break
        intersections += 1
        step = max(float(distance), 0.0) + epsilon
        origin = origin + direction * step
        remaining -= step
        if remaining <= 0.0:
            break
    return bool(intersections % 2)


def _point_inside_mesh_root(obj, point):
    for mesh_obj in _iter_mesh_objects(obj):
        try:
            bvh = _bvh_from_mesh_obj(mesh_obj)
        except Exception:
            continue
        if bvh is not None and _point_inside_bvh(bvh, point):
            return True
    return False


def _mesh_vertices_world(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    usable_meshes = 0
    errors = []
    for mesh_obj in _iter_mesh_objects(obj):
        bm = bmesh.new()
        try:
            try:
                bm.from_object(mesh_obj, depsgraph)
                usable_meshes += 1
                bm.transform(mesh_obj.matrix_world)
                for vertex in bm.verts:
                    yield vertex.co.copy()
            except Exception as exc:
                errors.append(exc)
                eval_obj = mesh_obj.evaluated_get(depsgraph)
                mesh = None
                try:
                    mesh = eval_obj.to_mesh()
                    if mesh is None or not mesh.vertices:
                        continue
                    usable_meshes += 1
                    matrix = eval_obj.matrix_world
                    for vertex in mesh.vertices:
                        yield matrix @ vertex.co
                except Exception as fallback_exc:
                    errors.append(fallback_exc)
                finally:
                    if mesh is not None:
                        eval_obj.to_mesh_clear()
                continue
        finally:
            bm.free()
    if usable_meshes == 0 and errors:
        raise errors[0]


def _root_bvhs_or_raise(obj):
    bvhs = []
    errors = []
    for mesh_obj in _iter_mesh_objects(obj):
        try:
            bvh = _bvh_from_mesh_obj(mesh_obj)
        except Exception as exc:
            errors.append(exc)
            continue
        if bvh is not None:
            bvhs.append(bvh)
    if not bvhs and errors:
        raise errors[0]
    return bvhs


def _surface_overlap_or_raise(obj_a, obj_b):
    bvhs_a = _root_bvhs_or_raise(obj_a)
    bvhs_b = _root_bvhs_or_raise(obj_b)
    if not bvhs_a or not bvhs_b:
        return False
    for bvh_a in bvhs_a:
        for bvh_b in bvhs_b:
            if bvh_a.overlap(bvh_b):
                return True
    return False


def _nearest_distance_to_bvhs(bvhs, point):
    point_v = _vec(point)
    best = None
    for bvh in bvhs:
        loc, normal, index, dist = bvh.find_nearest(point_v)
        if loc is None:
            continue
        dist = float(dist)
        if best is None or dist < best:
            best = dist
    return best


def _sample_mesh_points(obj, max_points=256):
    vertices = list(_mesh_vertices_world(obj))
    if not vertices:
        return []
    limit = max(1, int(max_points))
    if len(vertices) <= limit:
        return vertices
    step = (len(vertices) - 1) / float(max(1, limit - 1))
    return [
        vertices[int(round(i * step))]
        for i in range(limit)
    ]


def _point_inside_root_strict(obj, point, obj_bvhs=None, surface_epsilon=1.0e-4):
    bvhs = obj_bvhs if obj_bvhs is not None else _root_bvhs_or_raise(obj)
    if not bvhs:
        return False
    dist = _nearest_distance_to_bvhs(bvhs, point)
    if dist is None or dist <= float(surface_epsilon):
        return False
    return any(_point_inside_bvh(bvh, point) for bvh in bvhs)


def _containment_report(obj_a, obj_b, max_samples=256, surface_epsilon=1.0e-4):
    amin, amax = _aabb_np(obj_a)
    bmin, bmax = _aabb_np(obj_b)
    bvhs_b = _root_bvhs_or_raise(obj_b)
    bvhs_a = _root_bvhs_or_raise(obj_a)

    def samples_inside(query, target, target_min, target_max, target_bvhs):
        for point in _sample_mesh_points(query, max_points=max_samples):
            if not _aabb_contains(target_min, target_max, point):
                continue
            if _point_inside_root_strict(
                target,
                point,
                obj_bvhs=target_bvhs,
                surface_epsilon=surface_epsilon,
            ):
                return _json_point(point)
        return None

    a_volume = _aabb_volume(amin, amax)
    b_volume = _aabb_volume(bmin, bmax)
    if a_volume <= b_volume:
        point = samples_inside(obj_a, obj_b, bmin, bmax, bvhs_b)
        if point is not None:
            return {"collision": True, "reason": "mesh_containment", "sample": point, "contained": obj_a.name, "container": obj_b.name}
        point = samples_inside(obj_b, obj_a, amin, amax, bvhs_a)
        if point is not None:
            return {"collision": True, "reason": "mesh_containment", "sample": point, "contained": obj_b.name, "container": obj_a.name}
    else:
        point = samples_inside(obj_b, obj_a, amin, amax, bvhs_a)
        if point is not None:
            return {"collision": True, "reason": "mesh_containment", "sample": point, "contained": obj_b.name, "container": obj_a.name}
        point = samples_inside(obj_a, obj_b, bmin, bmax, bvhs_b)
        if point is not None:
            return {"collision": True, "reason": "mesh_containment", "sample": point, "contained": obj_a.name, "container": obj_b.name}
    return {"collision": False, "reason": None}


def solid_mesh_collision_report(obj_a, obj_b, max_containment_samples=256, surface_epsilon=1.0e-4):
    """Return exact collision details, including full containment misses."""
    if obj_a is None or obj_b is None:
        return {"collision": True, "reason": "missing_object", "error": None}
    if not _has_mesh(obj_a) or not _has_mesh(obj_b):
        return {"collision": False, "reason": None, "error": None}
    try:
        if _surface_overlap_or_raise(obj_a, obj_b):
            return {"collision": True, "reason": "surface_overlap", "error": None}
        contained = _containment_report(
            obj_a,
            obj_b,
            max_samples=max_containment_samples,
            surface_epsilon=surface_epsilon,
        )
        if contained["collision"]:
            contained["error"] = None
            return contained
        return {"collision": False, "reason": None, "error": None}
    except Exception as exc:
        return {
            "collision": True,
            "reason": "collision_check_error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def solid_mesh_overlap(obj_a, obj_b, **kwargs):
    return bool(solid_mesh_collision_report(obj_a, obj_b, **kwargs)["collision"])


def _mesh_root_clearance(query_obj, surface_obj, stop_below=None):
    surface_bvhs = []
    for mesh_obj in _iter_mesh_objects(surface_obj):
        try:
            bvh = _bvh_from_mesh_obj(mesh_obj)
        except Exception:
            continue
        if bvh is not None:
            surface_bvhs.append(bvh)
    if not surface_bvhs:
        return None

    best = None
    stop = None if stop_below is None else float(stop_below)
    for point in _mesh_vertices_world(query_obj):
        for bvh in surface_bvhs:
            loc, normal, index, dist = bvh.find_nearest(point)
            if loc is None:
                continue
            dist = float(dist)
            if best is None or dist < best:
                best = dist
                if stop is not None and best < stop:
                    return best
    return best


def camera_clearance_report(camera_pos, objects, min_clearance=0.0, exact=False):
    """Return camera clearance/inside diagnostics for a set of object roots."""
    cam = _np3(camera_pos)
    rows = []
    min_row = None
    ok = True
    for obj in _as_obj_list(objects):
        if not _has_mesh(obj):
            continue
        amin, amax = _aabb_np(obj)
        inside_aabb = _aabb_contains(amin, amax, cam)
        dist_aabb = 0.0 if inside_aabb else _point_aabb_distance(cam, amin, amax)
        needs_exact = bool(
            exact
            and (
                inside_aabb
                or dist_aabb < float(min_clearance)
            )
        )
        dist_surface = _nearest_surface_distance(obj, cam) if needs_exact else None
        inside_mesh = _point_inside_mesh_root(obj, cam) if needs_exact else False
        inside = inside_mesh if exact else inside_aabb
        clearance = (
            0.0
            if inside
            else (dist_surface if dist_surface is not None else dist_aabb)
        )
        row_ok = (not inside) and clearance >= float(min_clearance)
        row = {
            "object": obj.name,
            "inside_aabb": bool(inside_aabb),
            "inside_mesh": bool(inside_mesh),
            "clearance": float(clearance),
            "aabb_clearance": float(dist_aabb),
            "surface_clearance": None if dist_surface is None else float(dist_surface),
            "ok": row_ok,
        }
        rows.append(row)
        if min_row is None or row["clearance"] < min_row["clearance"]:
            min_row = row
        ok = ok and row_ok
    return {
        "ok": bool(ok),
        "min_clearance": None if min_row is None else float(min_row["clearance"]),
        "min_object": None if min_row is None else min_row["object"],
        "objects": rows,
    }


def _pallet_static_collision_report(pallet_obj, static_objects, broad_inflate=0.0):
    pmin, pmax = _aabb_np(pallet_obj)
    broad_hits = []
    exact_hits = []
    clearance_hits = []
    clearance_distances = {}
    for obj in _as_obj_list(static_objects):
        omin, omax = _aabb_np(obj)
        broad = _aabb_overlap(pmin, pmax, omin, omax, inflate=float(broad_inflate))
        if not broad:
            continue
        broad_hits.append(obj.name)
        exact_report = solid_mesh_collision_report(pallet_obj, obj)
        if exact_report["collision"]:
            exact_hits.append(obj.name)
            continue
        if float(broad_inflate) > 0.0:
            clearance = _mesh_root_clearance(
                pallet_obj,
                obj,
                stop_below=float(broad_inflate),
            )
            clearance_distances[obj.name] = (
                None if clearance is None else float(clearance)
            )
            if clearance is not None and clearance < float(broad_inflate):
                clearance_hits.append(obj.name)
    return {
        "ok": not exact_hits and not clearance_hits,
        "broad_hits": broad_hits,
        "exact_hits": exact_hits,
        "clearance_hits": clearance_hits,
        "clearance_distances": clearance_distances,
    }


# ---------------------------------------------------------------------------
# Background-aware pallet anchor solver
# ---------------------------------------------------------------------------
def _resolve_camera_plan(camera_plan=None, cam_pos=None, cam_look=None):
    if camera_plan is not None:
        if isinstance(camera_plan, dict):
            cam_pos = camera_plan.get("cam_pos", camera_plan.get("position", cam_pos))
            cam_look = camera_plan.get("cam_look", camera_plan.get("look_at", cam_look))
        elif len(camera_plan) >= 2:
            cam_pos, cam_look = camera_plan[0], camera_plan[1]
    if cam_pos is None:
        raise ValueError("camera position is required")
    return _np3(cam_pos), None if cam_look is None else _np3(cam_look)


def _anchor_candidate_deltas(
    seed,
    attempts,
    current_location,
    candidate_translations=None,
    xy_bounds=None,
    z_value=None,
):
    current = _np3(current_location)
    if candidate_translations is not None:
        for tr in candidate_translations:
            yield _np3(tr)
        return

    if xy_bounds is None:
        yield np.zeros(3, dtype=np.float64)
        return

    rng = random.Random(int(seed))
    x_bounds, y_bounds = xy_bounds
    for _ in range(int(attempts)):
        x = rng.uniform(float(x_bounds[0]), float(x_bounds[1]))
        y = rng.uniform(float(y_bounds[0]), float(y_bounds[1]))
        z = current[2] if z_value is None else float(z_value)
        yield np.array([x - current[0], y - current[1], z - current[2]], dtype=np.float64)


def solve_pallet_anchor(
    pallet_obj,
    camera_plan=None,
    cam_pos=None,
    cam_look=None,
    floor_mode="plane",
    floor_obj=None,
    seed=0,
    attempts=1,
    static_inventory=None,
    candidate_translations=None,
    xy_bounds=None,
    anchor_z=None,
    floor_z=0.0,
    support_height_tolerance=0.02,
    support_ray_start_above=0.5,
    support_ray_distance=2.0,
    min_support_normal_z=0.5,
    broad_aabb_inflate=0.0,
    camera_clearance=0.0,
    support_camera_clearance=0.0,
    camera_clearance_exact=False,
    camera_obj=None,
    pallet_name=None,
    orientation_overrides=None,
    static_los_samples=None,
    keep_attempt_log=True,
):
    """Move a placed pallet and camera plan by the same world translation.

    On success, the pallet (and optional Blender camera object) are left at the
    accepted pose.  On failure, their original transforms are restored.
    """
    pallet_obj = _as_obj(pallet_obj)
    if pallet_obj is None:
        raise ValueError("pallet_obj could not be resolved")
    cam0, look0 = _resolve_camera_plan(camera_plan, cam_pos=cam_pos, cam_look=cam_look)
    cam_obj = _as_obj(camera_obj)

    if static_inventory is None:
        static_inventory = collect_visible_static_inventory(
            floor_obj=floor_obj,
            exclude_objects=[pallet_obj],
        )
    support_objects = _as_obj_list(static_inventory.get("support_objects", []))
    obstacle_objects = _as_obj_list(static_inventory.get("static_obstacle_objects", []))
    floor = _as_obj(floor_obj)
    if floor is not None and floor not in support_objects:
        support_objects.append(floor)

    original_loc = pallet_obj.location.copy()
    original_cam_loc = cam_obj.location.copy() if cam_obj is not None else None
    original_cam_rot = cam_obj.rotation_euler.copy() if cam_obj is not None else None
    reject_counts = Counter()
    attempt_log = []
    best_failure = None
    accepted = None

    candidates = list(
        _anchor_candidate_deltas(
            seed,
            attempts,
            original_loc,
            candidate_translations=candidate_translations,
            xy_bounds=xy_bounds,
            z_value=anchor_z,
        )
    )
    if attempts and candidate_translations is None and xy_bounds is not None:
        candidates = candidates[: int(attempts)]

    for idx, candidate_delta in enumerate(candidates):
        delta = _np3(candidate_delta).copy()
        pallet_obj.location = original_loc + mathutils.Vector(tuple(delta))
        t_cam = cam0 + delta
        t_look = None if look0 is None else look0 + delta
        _aim_camera_object(cam_obj, t_cam, t_look)
        bpy.context.view_layer.update()

        support_probe = check_pallet_support(
            pallet_obj,
            support_objects=support_objects,
            floor_mode=floor_mode,
            floor_obj=floor,
            floor_z=float(floor_z),
            height_tolerance=float("inf"),
            ray_start_above=support_ray_start_above,
            ray_distance=support_ray_distance,
            min_support_normal_z=min_support_normal_z,
            pallet_name=pallet_name,
            orientation_overrides=orientation_overrides,
        )
        if support_probe["ok"]:
            snap = placement.compute_support_snap(
                sample_zs=[row["sample"][2] for row in support_probe["samples"]],
                support_zs=[row["support_z"] for row in support_probe["samples"]],
                normal_zs=[row["normal_z"] for row in support_probe["samples"]],
                height_tolerance=support_height_tolerance,
                min_abs_normal_z=min_support_normal_z,
            )
        else:
            snap = {
                "ok": False,
                "vertical_offset": None,
                "max_height_residual": None,
                "reason": "support_probe",
            }
        if snap["ok"]:
            delta[2] += float(snap["vertical_offset"])
            pallet_obj.location = original_loc + mathutils.Vector(tuple(delta))
            t_cam = cam0 + delta
            t_look = None if look0 is None else look0 + delta
            _aim_camera_object(cam_obj, t_cam, t_look)
            bpy.context.view_layer.update()

        record = {
            "idx": idx,
            "translation": _json_point(delta),
            "vertical_snap": snap,
        }
        if not snap["ok"]:
            reject_counts["support"] += 1
            record["support_ok"] = False
            record["reason"] = "support"
            record["support_probe"] = support_probe
            attempt_log.append(record)
            best_failure = record
            continue

        support = check_pallet_support(
            pallet_obj,
            support_objects=support_objects,
            floor_mode=floor_mode,
            floor_obj=floor,
            floor_z=float(floor_z),
            height_tolerance=support_height_tolerance,
            ray_start_above=support_ray_start_above,
            ray_distance=support_ray_distance,
            min_support_normal_z=min_support_normal_z,
            pallet_name=pallet_name,
            orientation_overrides=orientation_overrides,
        )
        record["support_ok"] = bool(support["ok"])
        if not support["ok"]:
            reject_counts["support"] += 1
            record["reason"] = "support"
            record["support"] = support
            attempt_log.append(record)
            best_failure = record
            continue

        coll = _pallet_static_collision_report(
            pallet_obj,
            obstacle_objects,
            broad_inflate=broad_aabb_inflate,
        )
        record["broad_hits"] = list(coll["broad_hits"])
        record["exact_hits"] = list(coll["exact_hits"])
        record["clearance_hits"] = list(coll["clearance_hits"])
        record["clearance_distances"] = dict(coll["clearance_distances"])
        if coll["exact_hits"]:
            reject_counts["pallet_static_collision"] += 1
            record["reason"] = "pallet_static_collision"
            attempt_log.append(record)
            best_failure = record
            continue
        if coll["clearance_hits"]:
            reject_counts["pallet_static_clearance"] += 1
            record["reason"] = "pallet_static_clearance"
            attempt_log.append(record)
            best_failure = record
            continue

        obstacle_clearance = camera_clearance_report(
            t_cam,
            obstacle_objects,
            min_clearance=camera_clearance,
            exact=camera_clearance_exact,
        )
        support_clearance = camera_clearance_report(
            t_cam,
            support_objects,
            min_clearance=support_camera_clearance,
            exact=camera_clearance_exact,
        )
        clearance_rows = [
            row
            for row in (obstacle_clearance, support_clearance)
            if row.get("min_clearance") is not None
        ]
        minimum = min(
            clearance_rows,
            key=lambda row: row["min_clearance"],
            default=None,
        )
        clearance = {
            "ok": bool(obstacle_clearance["ok"] and support_clearance["ok"]),
            "min_clearance": (
                None if minimum is None else minimum["min_clearance"]
            ),
            "min_object": None if minimum is None else minimum["min_object"],
            "obstacles": obstacle_clearance,
            "supports": support_clearance,
        }
        record["camera_clearance"] = {
            "ok": clearance["ok"],
            "min_clearance": clearance["min_clearance"],
            "min_object": clearance["min_object"],
        }
        if not clearance["ok"]:
            reject_counts["camera_clearance"] += 1
            record["reason"] = "camera_clearance"
            record["camera_clearance_detail"] = clearance
            attempt_log.append(record)
            best_failure = record
            continue

        candidate_los_samples = None
        if static_los_samples is not None:
            candidate_los_samples = [
                _np3(sample) + delta for sample in static_los_samples
            ]
        los = check_static_los(
            pallet_obj,
            t_cam,
            static_blockers=obstacle_objects,
            samples=candidate_los_samples,
            pallet_name=pallet_name,
            orientation_overrides=orientation_overrides,
        )
        record["los_ok"] = bool(los["ok"])
        if not los["ok"]:
            reject_counts["static_los"] += 1
            record["reason"] = "static_los"
            record["los"] = los
            attempt_log.append(record)
            best_failure = record
            continue

        accepted = {
            "idx": idx,
            "translation": _json_point(delta),
            "cam_pos": _json_point(t_cam),
            "cam_look": None if t_look is None else _json_point(t_look),
            "support": support,
            "collision": coll,
            "camera_clearance": clearance,
            "los": los,
            "pallet_aabb": _json_aabb(pallet_obj),
        }
        attempt_log.append({**record, "reason": None})
        break

    if accepted is None:
        pallet_obj.location = original_loc
        if cam_obj is not None:
            cam_obj.location = original_cam_loc
            cam_obj.rotation_euler = original_cam_rot
        bpy.context.view_layer.update()
        return {
            "success": False,
            "reject_counts": dict(reject_counts),
            "attempts": len(candidates),
            "last_failure": best_failure,
            "attempt_log": attempt_log if keep_attempt_log else [],
        }

    return {
        "success": True,
        "reject_counts": dict(reject_counts),
        "attempts": len(candidates),
        "accepted": accepted,
        "attempt_log": attempt_log if keep_attempt_log else [],
    }


# ---------------------------------------------------------------------------
# Deterministic cargo top-surface packer
# ---------------------------------------------------------------------------
def _default_box_names():
    if cfg is not None and getattr(cfg, "BOX_NAMES", None):
        return list(cfg.BOX_NAMES)
    return sorted(o.name for o in bpy.data.objects if o.name.startswith("PalletBox"))


def _object_footprint_inside_pallet(obj, pallet_geom, margin=0.0):
    amin, amax = _aabb_np(obj)
    corners = _aabb_corners(amin, amax)
    top_center = np.asarray(pallet_geom["top_center_world"], dtype=np.float64)
    width_dir = np.asarray(pallet_geom["width_dir_world"], dtype=np.float64)
    depth_dir = np.asarray(pallet_geom["depth_dir_world"], dtype=np.float64)
    hw = 0.5 * float(pallet_geom["width_len_world"]) - float(margin)
    hd = 0.5 * float(pallet_geom["depth_len_world"]) - float(margin)
    rel = corners - top_center[None, :]
    u = rel @ width_dir
    v = rel @ depth_dir
    return bool(np.all(np.abs(u) <= hw + 1e-9) and np.all(np.abs(v) <= hd + 1e-9))


def _cargo_candidate_uvs(seed, candidate_uvs=None):
    if candidate_uvs is not None:
        return [(float(u), float(v)) for u, v in candidate_uvs]
    coords = [-0.30, 0.0, 0.30]
    pairs = [(u, v) for u in coords for v in coords]
    rng = random.Random(int(seed))
    rng.shuffle(pairs)
    return pairs


def _far_side_score(u, v, pallet_geom, camera_pos):
    if camera_pos is None:
        return 0.0
    top_center = np.asarray(pallet_geom["top_center_world"], dtype=np.float64)
    width_dir = np.asarray(pallet_geom["width_dir_world"], dtype=np.float64)
    depth_dir = np.asarray(pallet_geom["depth_dir_world"], dtype=np.float64)
    cam_rel = _np3(camera_pos) - top_center
    cam_uv = np.array([float(cam_rel @ width_dir), float(cam_rel @ depth_dir)])
    n = float(np.linalg.norm(cam_uv))
    if n <= 1e-9:
        return 0.0
    candidate_uv = np.array([float(u), float(v)])
    return float(candidate_uv @ (-cam_uv / n))


def pack_cargo_top_surface(
    pallet_obj,
    box_names=None,
    count=None,
    seed=0,
    camera_pos=None,
    static_objects=None,
    context_objects=None,
    candidate_uvs=None,
    yaw_options=None,
    footprint_margin=0.0,
    contact_tolerance=0.02,
    broad_aabb_inflate=0.0,
    hide_unplaced=True,
    pallet_name=None,
    orientation_overrides=None,
):
    """Place PalletBox objects on the pallet top surface deterministically."""
    pallet_obj = _as_obj(pallet_obj)
    if pallet_obj is None:
        raise ValueError("pallet_obj could not be resolved")
    if box_names is None:
        box_names = _default_box_names()
    box_objs = [_as_obj(name) for name in box_names]
    box_objs = [o for o in box_objs if o is not None]
    if count is None:
        count = len(box_objs)
    count = max(0, min(int(count), len(box_objs)))
    yaw_options = [0.0] if yaw_options is None else [float(v) for v in yaw_options]
    blockers = _as_obj_list(static_objects) + _as_obj_list(context_objects)

    pallet_geom = _pallet_geometry(
        pallet_obj,
        pallet_name=pallet_name,
        orientation_overrides=orientation_overrides,
    )
    if pallet_geom is None:
        if hide_unplaced:
            for obj in box_objs:
                set_render_visibility(obj, False)
        return {"placed_objects": [], "placed_names": [], "metrics": {"success": False, "reason": "no_pallet_geometry"}}

    for obj in box_objs:
        register_role(obj, ROLE_CARGO, recursive=True)
        set_render_visibility(obj, False)

    top_center = np.asarray(pallet_geom["top_center_world"], dtype=np.float64)
    top_z = float(pallet_geom["top_z_world"])
    width_dir = np.asarray(pallet_geom["width_dir_world"], dtype=np.float64)
    depth_dir = np.asarray(pallet_geom["depth_dir_world"], dtype=np.float64)
    width_len = float(pallet_geom["width_len_world"])
    depth_len = float(pallet_geom["depth_len_world"])
    pallet_yaw = math.atan2(float(width_dir[1]), float(width_dir[0]))

    candidates = _cargo_candidate_uvs(seed, candidate_uvs=candidate_uvs)
    candidates = sorted(
        candidates,
        key=lambda uv: (-_far_side_score(uv[0], uv[1], pallet_geom, camera_pos), uv[0], uv[1]),
    )
    reject_counts = Counter()
    placed = []
    placements = []

    for obj in box_objs:
        if len(placed) >= count:
            break
        base_scale = tuple(float(v) for v in obj.scale)
        placed_this = False
        for u, v in candidates:
            for yaw in yaw_options:
                obj.scale = base_scale
                set_render_visibility(obj, True)
                xy = top_center + width_dir * (u * width_len) + depth_dir * (v * depth_len)
                set_object_pose_grounded(
                    obj,
                    float(xy[0]),
                    float(xy[1]),
                    pallet_yaw + float(yaw),
                    ground_z=top_z,
                )
                bpy.context.view_layer.update()

                if not _object_footprint_inside_pallet(obj, pallet_geom, margin=footprint_margin):
                    reject_counts["footprint_outside"] += 1
                    continue
                contact_err = float(object_bottom_z_world(obj) - top_z)
                if abs(contact_err) > float(contact_tolerance):
                    reject_counts["support_contact"] += 1
                    continue
                hit = _first_collision(obj, placed + blockers, broad_aabb_inflate=broad_aabb_inflate)
                if hit is not None:
                    reject_counts["collision"] += 1
                    continue

                placed.append(obj)
                placements.append(
                    {
                        "name": obj.name,
                        "u": float(u),
                        "v": float(v),
                        "yaw_rad": float(pallet_yaw + yaw),
                        "contact_error": contact_err,
                        "aabb": _json_aabb(obj),
                        "far_side_score": _far_side_score(u, v, pallet_geom, camera_pos),
                    }
                )
                placed_this = True
                break
            if placed_this:
                break
        if not placed_this and hide_unplaced:
            set_render_visibility(obj, False)

    if hide_unplaced:
        for obj in box_objs:
            if obj not in placed:
                set_render_visibility(obj, False)

    return {
        "placed_objects": placed,
        "placed_names": [obj.name for obj in placed],
        "metrics": {
            "success": len(placed) >= count,
            "requested": int(count),
            "placed": len(placed),
            "reject_counts": dict(reject_counts),
            "placements": placements,
        },
    }


def _first_collision(obj, others, broad_aabb_inflate=0.0):
    amin, amax = _aabb_np(obj)
    for other in _as_obj_list(others):
        if other is obj or not _has_mesh(other):
            continue
        omin, omax = _aabb_np(other)
        if not _aabb_overlap(amin, amax, omin, omax, inflate=float(broad_aabb_inflate)):
            continue
        if solid_mesh_collision_report(obj, other)["collision"]:
            return other
    return None


# ---------------------------------------------------------------------------
# Deterministic context placer
# ---------------------------------------------------------------------------
def _context_candidate_poses(seed, attempts, xy_bounds=None, yaw_values=None, candidate_poses=None):
    if candidate_poses is not None:
        for pose in candidate_poses:
            if isinstance(pose, dict):
                yield float(pose["x"]), float(pose["y"]), float(pose.get("yaw", pose.get("yaw_rad", 0.0)))
            else:
                yield float(pose[0]), float(pose[1]), float(pose[2] if len(pose) > 2 else 0.0)
        return
    if xy_bounds is None:
        return
    yaw_values = [0.0] if yaw_values is None else [float(v) for v in yaw_values]
    rng = random.Random(int(seed))
    x_bounds, y_bounds = xy_bounds
    for _ in range(int(attempts)):
        x = rng.uniform(float(x_bounds[0]), float(x_bounds[1]))
        y = rng.uniform(float(y_bounds[0]), float(y_bounds[1]))
        for yaw in yaw_values:
            yield x, y, yaw


def _callback_accepts(callback, *args):
    if callback is None:
        return True, {"accept": True}
    result = callback(*args)
    if isinstance(result, dict):
        accept = bool(result.get("accept", result.get("ok", True)))
        return accept, _jsonable_dict(result)
    if isinstance(result, bool):
        return result, {"accept": result}
    if isinstance(result, (int, float)):
        return True, {"accept": True, "score": float(result)}
    return bool(result), {"accept": bool(result)}


def _jsonable_dict(d):
    out = {}
    for k, v in dict(d).items():
        if isinstance(v, np.generic):
            out[k] = v.item()
        elif isinstance(v, np.ndarray):
            out[k] = v.astype(float).tolist()
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [
                x.item() if isinstance(x, np.generic) else x
                for x in v
                if isinstance(x, (str, int, float, bool, np.generic)) or x is None
            ]
        else:
            out[k] = str(v)
    return out


def place_context_objects(
    candidate_names,
    pallet_obj,
    camera_plan=None,
    cam_pos=None,
    cam_look=None,
    floor_z=0.0,
    floor_contact_tolerance=0.02,
    seed=0,
    max_count=None,
    attempts_per_object=1,
    xy_bounds=None,
    yaw_values=None,
    candidate_poses=None,
    support_objects=None,
    support_ray_start_z=5.0,
    support_ray_distance=20.0,
    min_support_normal_z=0.5,
    static_objects=None,
    cargo_objects=None,
    existing_context_objects=None,
    reserved_aabbs=None,
    camera_clearance=0.0,
    camera_clearance_exact=False,
    broad_aabb_inflate=0.0,
    occlusion_budget_callback=None,
    hide_rejected=True,
):
    """Place context clutter on the floor with hard collision rejects.

    ``occlusion_budget_callback`` is optional and called after a hard-valid pose:
    ``callback(obj, placed_objects, metrics_so_far)``.  It can defer or perform
    min-visible-pixel / accidental-pallet-occlusion checks.
    """
    pallet_obj = _as_obj(pallet_obj)
    cam, _ = _resolve_camera_plan(camera_plan, cam_pos=cam_pos, cam_look=cam_look)
    candidates = [_as_obj(name) for name in candidate_names]
    candidates = [o for o in candidates if o is not None]
    if max_count is None:
        max_count = len(candidates)
    max_count = max(0, min(int(max_count), len(candidates)))

    static_objects = _as_obj_list(static_objects)
    support_objects = _as_obj_list(support_objects)
    cargo_objects = _as_obj_list(cargo_objects)
    placed = _as_obj_list(existing_context_objects)
    reserved_aabbs = list(reserved_aabbs or ())
    new_placed = []
    reject_counts = Counter()
    placements = []

    for obj_idx, obj in enumerate(candidates):
        if len(new_placed) >= max_count:
            break
        register_role(obj, ROLE_CONTEXT, recursive=True)
        base_scale, base_rot = _store_base_transform_if_needed(obj)
        set_render_visibility(obj, True)
        accepted = False
        poses_for_obj = candidate_poses
        if isinstance(candidate_poses, dict):
            poses_for_obj = candidate_poses.get(obj.name, [])
        poses = list(
            _context_candidate_poses(
                int(seed) + obj_idx,
                attempts_per_object,
                xy_bounds=xy_bounds,
                yaw_values=yaw_values,
                candidate_poses=poses_for_obj,
            )
        )
        for x, y, yaw in poses:
            support = None
            candidate_floor_z = float(floor_z)
            if support_objects:
                support = support_surface_at_xy(
                    x,
                    y,
                    support_objects,
                    ray_start_z=support_ray_start_z,
                    ray_distance=support_ray_distance,
                    min_support_normal_z=min_support_normal_z,
                    hide_objects=[obj],
                )
                if not support["ok"]:
                    reject_counts["support"] += 1
                    continue
                candidate_floor_z = float(support["support_z"])

            obj.scale = tuple(float(v) for v in base_scale)
            set_object_pose_grounded(
                obj,
                x,
                y,
                yaw,
                base_rot_rad=base_rot,
                ground_z=candidate_floor_z,
            )
            bpy.context.view_layer.update()
            if support_objects:
                support = check_object_support(
                    obj,
                    support_objects=support_objects,
                    height_tolerance=floor_contact_tolerance,
                    ray_start_above=0.5,
                    ray_distance=support_ray_distance,
                    min_support_normal_z=min_support_normal_z,
                    hide_objects=[obj],
                )
                if not support["ok"]:
                    reject_counts["support"] += 1
                    continue
            contact_err = float(
                object_bottom_z_world(obj) - candidate_floor_z
            )
            if abs(contact_err) > float(floor_contact_tolerance):
                reject_counts["floor_contact"] += 1
                continue

            candidate_min, candidate_max = get_obj_aabb_world(obj)
            if any(
                placement.aabb_overlap(
                    candidate_min,
                    candidate_max,
                    reserved["aabb_min"],
                    reserved["aabb_max"],
                )
                for reserved in reserved_aabbs
            ):
                reject_counts["reserved_zone"] += 1
                continue

            blockers = [pallet_obj] + static_objects + cargo_objects + placed + new_placed
            collision = _first_collision(obj, blockers, broad_aabb_inflate=broad_aabb_inflate)
            if collision is not None:
                reject_counts["collision"] += 1
                continue

            clearance = camera_clearance_report(
                cam,
                [obj],
                min_clearance=camera_clearance,
                exact=camera_clearance_exact,
            )
            if not clearance["ok"]:
                reject_counts["camera_clearance"] += 1
                continue

            current_metrics = {
                "name": obj.name,
                "x": float(x),
                "y": float(y),
                "yaw_rad": float(yaw),
                "contact_error": contact_err,
                "support": support,
                "camera_clearance": clearance,
            }
            cb_ok, cb_metrics = _callback_accepts(occlusion_budget_callback, obj, new_placed, current_metrics)
            current_metrics["occlusion_callback"] = cb_metrics
            if not cb_ok:
                reject_counts["occlusion_budget"] += 1
                continue

            accepted = True
            new_placed.append(obj)
            placements.append({**current_metrics, "aabb": _json_aabb(obj)})
            break

        if not accepted and hide_rejected:
            set_render_visibility(obj, False)

    return {
        "placed_objects": new_placed,
        "placed_names": [obj.name for obj in new_placed],
        "metrics": {
            "success": len(new_placed) >= max_count,
            "requested": int(max_count),
            "placed": len(new_placed),
            "reject_counts": dict(reject_counts),
            "placements": placements,
            "minimum_visible_pixel_deferred": occlusion_budget_callback is None,
        },
    }


# ---------------------------------------------------------------------------
# Explicit occluder initial placement and local search
# ---------------------------------------------------------------------------
def _store_base_transform_if_needed(obj):
    ensure_base_transform(obj)
    return (
        np.asarray(obj[BASE_SCALE_KEY], dtype=np.float64),
        np.asarray(obj[BASE_ROT_KEY], dtype=np.float64),
    )


def _resolve_plan_value(plan, key, default=None):
    if plan is None:
        return default
    if isinstance(plan, dict):
        return plan.get(key, default)
    return getattr(plan, key, default)


def place_initial_explicit_occluder(
    occluder_obj=None,
    plan=None,
    center=None,
    scale=None,
    yaw_rad=None,
    visible=True,
    ground_z=None,
):
    """Place a planned occluder by world AABB center without cumulative scale drift."""
    obj = _as_obj(occluder_obj or _resolve_plan_value(plan, "obj_name"))
    if obj is None:
        raise ValueError("occluder object could not be resolved")
    register_role(obj, ROLE_EXPLICIT_OCCLUDER, recursive=True)
    base_scale, base_rot = _store_base_transform_if_needed(obj)
    obj.location = tuple(float(v) for v in obj[BASE_LOC_KEY])
    center = _resolve_plan_value(plan, "center", center)
    if center is None:
        raise ValueError("occluder center is required")
    scale = float(_resolve_plan_value(plan, "scale", 1.0 if scale is None else scale))
    yaw_rad = float(_resolve_plan_value(plan, "yaw_rad", 0.0 if yaw_rad is None else yaw_rad))
    yaw_value = _resolve_plan_value(plan, "yaw", None)
    if yaw_value is not None:
        yaw_rad = float(yaw_value)

    obj.scale = tuple(float(v) for v in (base_scale * scale))
    rot = base_rot.copy()
    rot[2] += yaw_rad
    obj.rotation_euler = tuple(float(v) for v in rot)
    set_render_visibility(obj, bool(visible))
    bpy.context.view_layer.update()

    before_min, before_max = fresh_world_aabb(obj)
    before_center = _aabb_center(before_min, before_max)
    delta = _np3(center) - before_center
    obj.location = obj.location + mathutils.Vector(tuple(delta))
    bpy.context.view_layer.update()
    if ground_z is not None:
        grounded_min, _ = fresh_world_aabb(obj)
        obj.location.z += float(ground_z) - float(grounded_min[2])
        bpy.context.view_layer.update()
    after_min, after_max = fresh_world_aabb(obj)
    after_center = _aabb_center(after_min, after_max)
    return {
        "object": obj.name,
        "center": _json_point(after_center),
        "target_center": _json_point(center),
        "center_error": float(np.linalg.norm(after_center - _np3(center))),
        "scale": [float(v) for v in obj.scale],
        "base_scale": [float(v) for v in base_scale],
        "yaw_rad": yaw_rad,
        "ground_z": None if ground_z is None else float(ground_z),
        "support_error": (
            None
            if ground_z is None
            else float(after_min[2] - float(ground_z))
        ),
    }


def _score_result(score_callback, obj, metrics):
    if score_callback is None:
        return True, 0.0, {"accept": True, "score": 0.0}
    value = score_callback(obj, metrics)
    if isinstance(value, dict):
        accept = bool(value.get("accept", value.get("ok", True)))
        score = float(value.get("score", 0.0))
        return accept, score, _jsonable_dict(value)
    if isinstance(value, bool):
        return value, 1.0 if value else 0.0, {"accept": value, "score": 1.0 if value else 0.0}
    if isinstance(value, (int, float, np.generic)):
        return True, float(value), {"accept": True, "score": float(value)}
    return bool(value), 0.0, {"accept": bool(value), "score": 0.0}


def _set_occluder_candidate(obj, center, yaw_rad, ground_z=None):
    base_scale, base_rot = _store_base_transform_if_needed(obj)
    rot = base_rot.copy()
    rot[2] += float(yaw_rad)
    obj.rotation_euler = tuple(float(v) for v in rot)
    bpy.context.view_layer.update()
    current = _object_center(obj)
    obj.location = obj.location + mathutils.Vector(tuple(_np3(center) - current))
    bpy.context.view_layer.update()
    if ground_z is not None:
        obj.location.z += float(ground_z) - float(object_bottom_z_world(obj))
        bpy.context.view_layer.update()


def search_explicit_occluder_local(
    occluder_obj=None,
    plan=None,
    pallet_obj=None,
    camera_plan=None,
    cam_pos=None,
    cam_look=None,
    score_callback=None,
    static_objects=None,
    cargo_objects=None,
    context_objects=None,
    u_offsets=(0.0,),
    v_offsets=(0.0,),
    depth_offsets=(0.0,),
    yaw_offsets=(0.0,),
    candidate_offsets=None,
    camera_clearance=0.0,
    camera_clearance_exact=False,
    broad_aabb_inflate=0.0,
    restore_on_fail=True,
    ground_z=None,
    support_objects=None,
    support_ray_start_z=5.0,
    support_ray_distance=20.0,
    min_support_normal_z=0.5,
    support_contact_tolerance=0.02,
):
    """Deterministic local search over camera-frame u/v/depth/yaw offsets."""
    obj = _as_obj(occluder_obj or _resolve_plan_value(plan, "obj_name"))
    if obj is None:
        raise ValueError("occluder object could not be resolved")
    pallet_obj = _as_obj(pallet_obj)
    cam, look = _resolve_camera_plan(camera_plan, cam_pos=cam_pos, cam_look=cam_look)
    if look is None:
        if pallet_obj is not None:
            look = _object_center(pallet_obj)
        else:
            look = cam + np.array([1.0, 0.0, 0.0], dtype=np.float64)

    original = {
        "location": obj.location.copy(),
        "rotation": obj.rotation_euler.copy(),
        "scale": obj.scale.copy(),
        "hide_render": obj.hide_render,
        "hide_viewport": obj.hide_viewport,
    }
    support_objects = _as_obj_list(support_objects)
    initial = place_initial_explicit_occluder(
        obj,
        plan=plan,
        ground_z=None if support_objects else ground_z,
    )
    base_center = _np3(initial["center"])
    base_yaw = float(_resolve_plan_value(plan, "yaw_rad", _resolve_plan_value(plan, "yaw", 0.0)))
    right, up, forward = _camera_basis(cam, look)
    rel = base_center - cam
    base_depth = float(rel @ forward)
    base_u = float(rel @ right)
    base_v = float(rel @ up)
    blockers = []
    if pallet_obj is not None:
        blockers.append(pallet_obj)
    blockers += _as_obj_list(static_objects) + _as_obj_list(cargo_objects) + _as_obj_list(context_objects)

    reject_counts = Counter()
    candidate_log = []
    best = None
    best_rejected = None

    offsets = (
        itertools.product(u_offsets, v_offsets, depth_offsets, yaw_offsets)
        if candidate_offsets is None
        else candidate_offsets
    )
    for cand_idx, offset in enumerate(offsets):
        if len(offset) != 4:
            raise ValueError(
                "each explicit candidate offset must be (u, v, depth, yaw)"
            )
        du, dv, dd, dyaw = offset
        center = cam + (base_depth + float(dd)) * forward + (base_u + float(du)) * right + (base_v + float(dv)) * up
        yaw = base_yaw + float(dyaw)
        candidate_ground_z = ground_z
        support = None
        if support_objects:
            support = support_surface_at_xy(
                center[0],
                center[1],
                support_objects,
                ray_start_z=support_ray_start_z,
                ray_distance=support_ray_distance,
                min_support_normal_z=min_support_normal_z,
                hide_objects=[obj],
            )
            if not support["ok"]:
                reject_counts["support"] += 1
                candidate_log.append(
                    {
                        "idx": cand_idx,
                        "u_offset": float(du),
                        "v_offset": float(dv),
                        "depth_offset": float(dd),
                        "yaw_offset": float(dyaw),
                        "center": _json_point(center),
                        "yaw_rad": float(yaw),
                        "support": support,
                        "reason": "support",
                    }
                )
                continue
            candidate_ground_z = float(support["support_z"])

        _set_occluder_candidate(
            obj,
            center,
            yaw,
            ground_z=candidate_ground_z,
        )
        if support_objects:
            support = check_object_support(
                obj,
                support_objects=support_objects,
                height_tolerance=support_contact_tolerance,
                ray_start_above=0.5,
                ray_distance=support_ray_distance,
                min_support_normal_z=min_support_normal_z,
                hide_objects=[obj],
            )
            if not support["ok"]:
                reject_counts["support"] += 1
                candidate_log.append(
                    {
                        "idx": cand_idx,
                        "u_offset": float(du),
                        "v_offset": float(dv),
                        "depth_offset": float(dd),
                        "yaw_offset": float(dyaw),
                        "center": _json_point(center),
                        "yaw_rad": float(yaw),
                        "support": support,
                        "reason": "support",
                    }
                )
                continue
        contact_error = (
            None
            if candidate_ground_z is None
            else float(object_bottom_z_world(obj) - candidate_ground_z)
        )
        record = {
            "idx": cand_idx,
            "u_offset": float(du),
            "v_offset": float(dv),
            "depth_offset": float(dd),
            "yaw_offset": float(dyaw),
            "center": _json_point(center),
            "yaw_rad": float(yaw),
            "support": support,
            "support_error": contact_error,
        }
        if (
            contact_error is not None
            and abs(contact_error) > float(support_contact_tolerance)
        ):
            reject_counts["support_contact"] += 1
            record["reason"] = "support_contact"
            candidate_log.append(record)
            continue

        collision = _first_collision(obj, blockers, broad_aabb_inflate=broad_aabb_inflate)
        if collision is not None:
            reject_counts["collision"] += 1
            record["reason"] = "collision"
            record["collision_object"] = collision.name
            candidate_log.append(record)
            continue

        clearance = camera_clearance_report(
            cam,
            [obj] + blockers,
            min_clearance=camera_clearance,
            exact=camera_clearance_exact,
        )
        record["camera_clearance"] = {
            "ok": clearance["ok"],
            "min_clearance": clearance["min_clearance"],
            "min_object": clearance["min_object"],
        }
        if not clearance["ok"]:
            reject_counts["camera_clearance"] += 1
            record["reason"] = "camera_clearance"
            candidate_log.append(record)
            continue

        accept, score, score_metrics = _score_result(score_callback, obj, record)
        record["score"] = float(score)
        record["score_callback"] = score_metrics
        if not accept:
            reject_counts["score_callback"] += 1
            record["reason"] = "score_callback"
            candidate_log.append(record)
            if (
                best_rejected is None
                or score > best_rejected["score"]
            ):
                best_rejected = {
                    "score": float(score),
                    "record": record,
                }
            continue

        record["reason"] = None
        candidate_log.append(record)
        if best is None or score > best["score"]:
            best = {
                "score": float(score),
                "record": record,
                "location": obj.location.copy(),
                "rotation": obj.rotation_euler.copy(),
                "scale": obj.scale.copy(),
            }

    if best is not None:
        obj.location = best["location"]
        obj.rotation_euler = best["rotation"]
        obj.scale = best["scale"]
        set_render_visibility(obj, True)
        bpy.context.view_layer.update()
        return {
            "success": True,
            "object": obj.name,
            "best": best["record"],
            "best_rejected": (
                None
                if best_rejected is None
                else best_rejected["record"]
            ),
            "reject_counts": dict(reject_counts),
            "candidates": len(candidate_log),
            "candidate_log": candidate_log,
            "initial": initial,
        }

    if restore_on_fail:
        obj.location = original["location"]
        obj.rotation_euler = original["rotation"]
        obj.scale = original["scale"]
        obj.hide_render = original["hide_render"]
        obj.hide_viewport = original["hide_viewport"]
        bpy.context.view_layer.update()

    return {
        "success": False,
        "object": obj.name,
        "best": None,
        "best_rejected": (
            None
            if best_rejected is None
            else best_rejected["record"]
        ),
        "reject_counts": dict(reject_counts),
        "candidates": len(candidate_log),
        "candidate_log": candidate_log,
        "initial": initial,
    }


# ---------------------------------------------------------------------------
# Exact collision audit
# ---------------------------------------------------------------------------
def _pair_iter(forbidden_pairs=None, objects=None):
    if forbidden_pairs is not None:
        for a, b in forbidden_pairs:
            yield _as_obj(a), _as_obj(b)
        return
    objs = _as_obj_list(objects)
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            yield objs[i], objs[j]


def audit_collisions_and_camera_clearance(
    forbidden_pairs=None,
    objects=None,
    camera_pos=None,
    camera_clearance_objects=None,
    min_camera_clearance=0.0,
    camera_clearance_exact=True,
):
    """Audit exact BVH collisions for every forbidden pair and camera clearance."""
    pair_rows = []
    collisions = []
    for a, b in _pair_iter(forbidden_pairs=forbidden_pairs, objects=objects):
        if a is None or b is None:
            pair_rows.append(
                {
                    "a": _obj_name(a),
                    "b": _obj_name(b),
                    "ok": False,
                    "reason": "missing_object",
                    "broad_overlap": None,
                    "mesh_overlap": None,
                }
            )
            continue
        amin, amax = _aabb_np(a)
        bmin, bmax = _aabb_np(b)
        broad = _aabb_overlap(amin, amax, bmin, bmax)
        exact = False
        reason = None
        error = None
        if broad:
            report = solid_mesh_collision_report(a, b)
            exact = bool(report["collision"])
            reason = report.get("reason")
            error = report.get("error")
        row = {
            "a": a.name,
            "b": b.name,
            "ok": not exact,
            "reason": reason if exact else None,
            "error": error,
            "broad_overlap": bool(broad),
            "mesh_overlap": bool(exact),
        }
        pair_rows.append(row)
        if exact:
            collisions.append({"a": a.name, "b": b.name, "reason": reason, "error": error})

    clearance = None
    if camera_pos is not None:
        clearance_objs = camera_clearance_objects
        if clearance_objs is None:
            clearance_objs = objects
        clearance = camera_clearance_report(
            camera_pos,
            _as_obj_list(clearance_objs),
            min_clearance=min_camera_clearance,
            exact=camera_clearance_exact,
        )

    camera_ok = True if clearance is None else bool(clearance["ok"])
    return {
        "ok": not collisions and camera_ok,
        "collisions": collisions,
        "pairs": pair_rows,
        "camera_clearance": clearance,
        "min_camera_clearance": None if clearance is None else clearance["min_clearance"],
    }
