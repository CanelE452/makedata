"""Shared geometry helpers for Blender pallet rendering."""

import math
from contextlib import contextmanager

import bmesh
import bpy
import numpy as np
from mathutils import Vector as MathVector
from mathutils.bvhtree import BVHTree

from blender_math import canonical_corners_yup, euler_to_rotation_matrix
from blender_config import TARGET_CANONICAL_DIMS


R_YZ_SWAP = np.array(
    [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
    dtype=np.float64,
)
_normalization_cache = {}


@contextmanager
def temporary_visible_hierarchy(obj):
    """Temporarily unhide an object hierarchy so Blender updates matrix_world."""
    members = [obj, *obj.children_recursive]
    state = [(member, member.hide_render, member.hide_viewport) for member in members]
    changed = False
    for member, hide_render, hide_viewport in state:
        if hide_render or hide_viewport:
            member.hide_render = False
            member.hide_viewport = False
            changed = True
    if changed:
        bpy.context.view_layer.update()
    try:
        yield
    finally:
        if changed:
            for member, hide_render, hide_viewport in state:
                member.hide_render = hide_render
                member.hide_viewport = hide_viewport
            bpy.context.view_layer.update()


def iter_mesh_objects(obj):
    """Yield this object and all child meshes that have real geometry."""
    if obj.type == "MESH" and obj.data and len(obj.data.vertices) > 0:
        yield obj
    for child in obj.children_recursive:
        if child.type == "MESH" and child.data and len(child.data.vertices) > 0:
            yield child


def has_mesh_geometry(obj):
    return any(True for _ in iter_mesh_objects(obj))


def set_render_visibility(obj, visible):
    """Toggle render and viewport visibility for an object hierarchy."""
    hidden = not visible
    obj.hide_render = hidden
    obj.hide_viewport = hidden
    for child in obj.children_recursive:
        child.hide_render = hidden
        child.hide_viewport = hidden


def get_local_bbox(obj):
    """Get parent-local bbox covering all child meshes."""
    inv = obj.matrix_world.inverted()
    all_local = []
    for mesh_obj in iter_mesh_objects(obj):
        for corner in mesh_obj.bound_box:
            all_local.append(inv @ mesh_obj.matrix_world @ MathVector(corner))
    if not all_local:
        return None, None
    xs = [pt.x for pt in all_local]
    ys = [pt.y for pt in all_local]
    zs = [pt.z for pt in all_local]
    return np.array([min(xs), min(ys), min(zs)]), np.array([max(xs), max(ys), max(zs)])


def get_bbox_corners(bbox_min, bbox_max):
    """Return 8 corners of an axis-aligned bbox."""
    mn = np.array(bbox_min, dtype=np.float64)
    mx = np.array(bbox_max, dtype=np.float64)
    return np.array(
        [
            [mn[0], mn[1], mn[2]],
            [mx[0], mn[1], mn[2]],
            [mx[0], mx[1], mn[2]],
            [mn[0], mx[1], mn[2]],
            [mn[0], mn[1], mx[2]],
            [mx[0], mn[1], mx[2]],
            [mx[0], mx[1], mx[2]],
            [mn[0], mx[1], mx[2]],
        ],
        dtype=np.float64,
    )


def get_obj_aabb_world(obj):
    """Get world-space AABB including all child meshes."""
    all_world = []
    for mesh_obj in iter_mesh_objects(obj):
        for corner in mesh_obj.bound_box:
            all_world.append(mesh_obj.matrix_world @ MathVector(corner))
    if not all_world:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs = [pt[0] for pt in all_world]
    ys = [pt[1] for pt in all_world]
    zs = [pt[2] for pt in all_world]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def transform_local_points_world(obj, points_local):
    """Transform parent-local points into world space with full object matrix."""
    return np.array(
        [np.array(obj.matrix_world @ MathVector(tuple(pt))) for pt in points_local],
        dtype=np.float64,
    )


def extract_world_rotation_matrix(obj):
    """Return pure rotation without scale/shear."""
    _, rot_quat, _ = obj.matrix_world.decompose()
    return np.array(rot_quat.to_matrix(), dtype=np.float64)


def get_canonical_rotation(base_rot_deg):
    """Map raw pallet-local coordinates into canonical Y=UP coordinates."""
    return R_YZ_SWAP @ euler_to_rotation_matrix(base_rot_deg)


def get_normalized_scale(obj, base_rot_deg, target_dims=None):
    """Return a uniform parent scale that preserves the source pallet proportions."""
    target_dims = np.array(
        TARGET_CANONICAL_DIMS if target_dims is None else target_dims,
        dtype=np.float64,
    )
    cache_key = (obj.name, tuple(base_rot_deg), tuple(np.round(target_dims, 6)))
    if cache_key in _normalization_cache:
        return _normalization_cache[cache_key]

    with temporary_visible_hierarchy(obj):
        base_scale = np.array(obj.scale, dtype=np.float64)
        saved_location = obj.location.copy()
        saved_rotation = obj.rotation_euler.copy()
        saved_scale = obj.scale.copy()

        rx, ry, rz = [math.radians(v) for v in base_rot_deg]
        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_euler = (rx, ry, rz)
        obj.scale = tuple(base_scale)
        bpy.context.view_layer.update()

        pallet_geom = get_pallet_geometry(obj.name, obj, {obj.name: base_rot_deg})

        obj.location = saved_location
        obj.rotation_euler = saved_rotation
        obj.scale = saved_scale
        bpy.context.view_layer.update()

    if pallet_geom is None:
        _normalization_cache[cache_key] = base_scale
        return base_scale

    current_dims = np.array(
        [
            np.linalg.norm(pallet_geom["corners_world"][1] - pallet_geom["corners_world"][0]),
            np.linalg.norm(pallet_geom["corners_world"][3] - pallet_geom["corners_world"][0]),
            np.linalg.norm(pallet_geom["corners_world"][4] - pallet_geom["corners_world"][0]),
        ],
        dtype=np.float64,
    )
    valid = current_dims > 1e-8
    if not np.any(valid):
        _normalization_cache[cache_key] = base_scale
        return base_scale

    dims_fit = current_dims[valid]
    target_fit = target_dims[valid]
    denom = float(np.dot(dims_fit, dims_fit))
    if denom <= 1e-12:
        uniform_ratio = 1.0
    else:
        # Least-squares fit keeps the mesh aspect ratio intact while bringing the
        # overall object close to the canonical pallet size.
        uniform_ratio = float(np.dot(dims_fit, target_fit) / denom)
    if not np.isfinite(uniform_ratio) or uniform_ratio <= 0:
        ratios = target_fit / np.maximum(dims_fit, 1e-8)
        uniform_ratio = float(np.median(ratios))
    if not np.isfinite(uniform_ratio) or uniform_ratio <= 0:
        uniform_ratio = 1.0

    uniform_scale = base_scale * uniform_ratio
    _normalization_cache[cache_key] = uniform_scale
    return uniform_scale


def get_pallet_geometry(pallet_name, pallet_obj, orientation_overrides):
    """Build canonical cuboid + pose info for a pallet object."""
    with temporary_visible_hierarchy(pallet_obj):
        local_min, local_max = get_local_bbox(pallet_obj)
        if local_min is None:
            return None

        local_bbox_corners = get_bbox_corners(local_min, local_max)
        base_rot_deg = orientation_overrides.get(pallet_name, (0, 0, 0))
        r_canonical = get_canonical_rotation(base_rot_deg)

        rotated = (r_canonical @ local_bbox_corners.T).T
        cbmin = rotated.min(axis=0)
        cbmax = rotated.max(axis=0)

        corners_canonical = canonical_corners_yup(cbmin, cbmax)
        centroid_canonical = (cbmin + cbmax) / 2.0

        corners_local = (r_canonical.T @ corners_canonical.T).T
        centroid_local = r_canonical.T @ centroid_canonical

        corners_world = transform_local_points_world(pallet_obj, corners_local)
        centroid_world = transform_local_points_world(pallet_obj, [centroid_local])[0]
        r_obj_world = extract_world_rotation_matrix(pallet_obj)
        r_for_pose = r_obj_world @ r_canonical.T

        top_face_world = corners_world[[0, 1, 4, 5]]
        bottom_face_world = corners_world[[2, 3, 6, 7]]
        width_vec = corners_world[1] - corners_world[0]
        depth_vec = corners_world[4] - corners_world[0]

        width_len = np.linalg.norm(width_vec)
        depth_len = np.linalg.norm(depth_vec)
        width_dir = width_vec / width_len if width_len > 1e-8 else np.array([1.0, 0.0, 0.0])
        depth_dir = depth_vec / depth_len if depth_len > 1e-8 else np.array([0.0, -1.0, 0.0])

        return {
            "base_rot_deg": base_rot_deg,
            "local_bbox_min": local_min,
            "local_bbox_max": local_max,
            "canonical_bbox_min": cbmin,
            "canonical_bbox_max": cbmax,
            "r_canonical": r_canonical,
            "r_obj_world": r_obj_world,
            "r_for_pose": r_for_pose,
            "corners_local": corners_local,
            "centroid_local": centroid_local,
            "corners_world": corners_world,
            "centroid_world": centroid_world,
            "top_face_world": top_face_world,
            "bottom_face_world": bottom_face_world,
            "top_center_world": top_face_world.mean(axis=0),
            "bottom_center_world": bottom_face_world.mean(axis=0),
            "top_z_world": float(top_face_world[:, 2].mean()),
            "bottom_z_world": float(bottom_face_world[:, 2].mean()),
            "width_dir_world": width_dir,
            "depth_dir_world": depth_dir,
            "width_len_world": float(width_len),
            "depth_len_world": float(depth_len),
        }


def object_bottom_z_world(obj):
    return float(get_obj_aabb_world(obj)[0][2])


def object_top_z_world(obj):
    return float(get_obj_aabb_world(obj)[1][2])


def object_height_world(obj):
    aabb_min, aabb_max = get_obj_aabb_world(obj)
    return float(aabb_max[2] - aabb_min[2])


def snap_object_to_ground(obj, ground_z=0.0):
    """Shift an object vertically so its lowest world-space point touches ground_z."""
    bpy.context.view_layer.update()
    bottom_z = object_bottom_z_world(obj)
    obj.location.z += ground_z - bottom_z
    bpy.context.view_layer.update()
    return object_bottom_z_world(obj)


def set_object_pose_grounded(
    obj,
    x,
    y,
    yaw_rad,
    base_rot_deg=(0, 0, 0),
    ground_z=0.0,
    base_rot_rad=None,
):
    """Apply base rotation + yaw and snap object to the target ground plane."""
    if base_rot_rad is not None:
        rx, ry, rz = base_rot_rad
    else:
        rx, ry, rz = [math.radians(v) for v in base_rot_deg]
    obj.rotation_euler = (rx, ry, rz + yaw_rad)
    obj.location = (x, y, ground_z)
    return snap_object_to_ground(obj, ground_z=ground_z)


def is_ground_contact_ok(obj, target_z=0.0, tolerance=0.02):
    return abs(object_bottom_z_world(obj) - target_z) <= tolerance


def _bvh_from_mesh_obj(mesh_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    try:
        bm.from_object(mesh_obj, depsgraph)
        bm.transform(mesh_obj.matrix_world)
        return BVHTree.FromBMesh(bm)
    finally:
        bm.free()


def mesh_overlap(obj_a, obj_b):
    """Check intersection between any mesh pair under two object hierarchies."""
    meshes_a = list(iter_mesh_objects(obj_a))
    meshes_b = list(iter_mesh_objects(obj_b))
    if not meshes_a or not meshes_b:
        return False

    for mesh_a in meshes_a:
        try:
            bvh_a = _bvh_from_mesh_obj(mesh_a)
        except Exception:
            continue
        for mesh_b in meshes_b:
            try:
                bvh_b = _bvh_from_mesh_obj(mesh_b)
            except Exception:
                continue
            if bvh_a and bvh_b and bvh_a.overlap(bvh_b):
                return True
    return False
