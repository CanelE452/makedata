"""Blender-side regression for deterministic base-transform reuse."""

import math
import os
import sys

import bpy


SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import scene_visibility_v2 as sv2
import v2_realize as vr
from pallet_geometry import get_obj_aabb_world


def cube_mesh(name, size):
    s = float(size) / 2.0
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [
            (-s, -s, -s),
            (s, -s, -s),
            (s, s, -s),
            (-s, s, -s),
            (-s, -s, s),
            (s, -s, s),
            (s, s, s),
            (-s, s, s),
        ],
        [],
        [
            (0, 1, 2, 3),
            (4, 7, 6, 5),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        ],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)

obj = cube_mesh("ReusableDistractor", 1.0)
obj.location = (1.0, 2.0, 3.0)
obj.rotation_euler = (0.1, 0.2, 0.3)
obj.scale = (1.0, 2.0, 0.5)
bpy.context.view_layer.update()

sv2.ensure_base_transform(obj)

obj.location = (-7.0, 8.0, 9.0)
obj.rotation_euler = (0.0, 0.0, 2.0)
obj.scale = (3.0, 3.0, 3.0)
sv2.restore_base_transform(obj, visible=False)

assert tuple(round(v, 6) for v in obj.location) == (1.0, 2.0, 3.0)
assert tuple(round(v, 6) for v in obj.scale) == (1.0, 2.0, 0.5)
assert tuple(round(v, 6) for v in obj.rotation_euler) == (0.1, 0.2, 0.3)
assert obj.hide_render is True

sv2.place_initial_explicit_occluder(
    obj,
    center=(0.0, 0.0, 0.5),
    scale=2.0,
    yaw_rad=0.4,
    ground_z=0.0,
)

assert tuple(round(v, 6) for v in obj.scale) == (2.0, 4.0, 1.0)
assert abs(float(obj.rotation_euler.z) - 0.7) < 1e-6
amin, amax = get_obj_aabb_world(obj)
assert abs(float(amin[2]) - 0.0) < 1e-6

sv2.restore_base_transform(obj, visible=False)
sv2.place_initial_explicit_occluder(
    obj,
    center=(0.0, 0.0, 0.5),
    scale=2.0,
    yaw_rad=0.4,
    ground_z=0.0,
)

assert tuple(round(v, 6) for v in obj.scale) == (2.0, 4.0, 1.0)
assert abs(float(obj.rotation_euler.z) - 0.7) < 1e-6

root = bpy.data.objects.new("HiddenHierarchyRoot", None)
bpy.context.scene.collection.objects.link(root)
child = cube_mesh("HiddenHierarchyChild", 1.0)
child.parent = root
child.location = (1.25, 0.25, 0.5)
child.scale = (0.5, 1.5, 0.75)
bpy.context.view_layer.update()

sv2.ensure_base_transform(root)
base_min, base_max = sv2.fresh_world_aabb(root)
root.rotation_euler.z = 0.9
bpy.context.view_layer.update()
sv2.restore_base_transform(root, visible=False)
fresh_min, fresh_max = sv2.fresh_world_aabb(root)

base_dims = tuple(round(float(base_max[i] - base_min[i]), 6) for i in range(3))
fresh_dims = tuple(round(float(fresh_max[i] - fresh_min[i]), 6) for i in range(3))
assert fresh_dims == base_dims
assert root.hide_render is True
assert child.hide_render is True

hidden_target = (2.5, -1.25, 1.75)
hidden_result = sv2.place_initial_explicit_occluder(
    root,
    center=hidden_target,
    scale=1.4,
    yaw_rad=0.6,
    visible=False,
    ground_z=None,
)
hidden_min, hidden_max = sv2.fresh_world_aabb(root)
hidden_center = tuple(
    0.5 * (float(hidden_min[i]) + float(hidden_max[i]))
    for i in range(3)
)
assert max(
    abs(hidden_center[i] - hidden_target[i])
    for i in range(3)
) < 1e-6
assert max(
    abs(float(hidden_result["center"][i]) - hidden_target[i])
    for i in range(3)
) < 1e-6
assert root.hide_render is True
assert child.hide_render is True

scene = bpy.context.scene
scene.cycles.device = "GPU"
scene.cycles.use_adaptive_sampling = True
scene.cycles.use_denoising = True
scene.render.threads_mode = "AUTO"
threads_before = scene.render.threads
with vr.deterministic_rgb_render_settings(scene):
    assert scene.cycles.device == "CPU"
    assert scene.cycles.use_adaptive_sampling is False
    assert scene.cycles.use_denoising is False
    assert scene.render.threads_mode == "FIXED"
    assert scene.render.threads == 1
assert scene.cycles.device == "GPU"
assert scene.cycles.use_adaptive_sampling is True
assert scene.cycles.use_denoising is True
assert scene.render.threads_mode == "AUTO"
assert scene.render.threads == threads_before

print("[transform-reset-regression] PASS")
