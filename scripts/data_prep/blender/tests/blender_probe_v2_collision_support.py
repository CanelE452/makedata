"""Blender-side regression for v2 solid collision and footprint support checks."""

import os
import sys

import bpy


SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import scene_visibility_v2 as sv2


def cube_mesh(name, size):
    return cuboid_mesh(name, (size, size, size))


def cuboid_mesh(name, size_xyz):
    sx, sy, sz = (float(value) / 2.0 for value in size_xyz)
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [
            (-sx, -sy, -sz),
            (sx, -sy, -sz),
            (sx, sy, -sz),
            (-sx, sy, -sz),
            (-sx, -sy, sz),
            (sx, -sy, sz),
            (sx, sy, sz),
            (-sx, sy, sz),
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


def plane_mesh(name, half_extent):
    h = float(half_extent)
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)

outer = cube_mesh("OuterClosedCube", 2.0)
inner = cube_mesh("InnerContainedCube", 0.4)
inner.location = (0.1, -0.1, 0.0)
bpy.context.view_layer.update()

contained = sv2.audit_collisions_and_camera_clearance(
    forbidden_pairs=[(inner, outer)],
)
assert not contained["ok"], contained
assert contained["pairs"][0]["reason"] in {"mesh_containment", "surface_overlap"}, contained

separate = cube_mesh("SeparateCube", 0.4)
separate.location = (4.0, 0.0, 0.0)
bpy.context.view_layer.update()
separated = sv2.audit_collisions_and_camera_clearance(
    forbidden_pairs=[(separate, outer)],
)
assert separated["ok"], separated

small_support = plane_mesh("SmallSupport", 0.2)
large_support = plane_mesh("LargeSupport", 2.0)
large_support.location.x = 5.0
large = cube_mesh("LargeFootprintObject", 1.0)
large.location = (0.0, 0.0, 0.5)
bpy.context.view_layer.update()

small_report = sv2.check_object_support(
    large,
    support_objects=[small_support],
    height_tolerance=0.01,
    ray_start_above=0.5,
    ray_distance=2.0,
    hide_objects=[large],
)
assert not small_report["ok"], small_report

large.location = (5.0, 0.0, 0.5)
bpy.context.view_layer.update()
large_report = sv2.check_object_support(
    large,
    support_objects=[large_support],
    height_tolerance=0.01,
    ray_start_above=0.5,
    ray_distance=2.0,
    hide_objects=[large],
)
assert large_report["ok"], large_report

overhang_floor = plane_mesh("OverhangFloor", 3.0)
overhang_root = bpy.data.objects.new("LeggedOverhang", None)
bpy.context.scene.collection.objects.link(overhang_root)
for name, dims, location in (
    ("OverhangLeftFoot", (0.2, 0.2, 1.0), (-0.6, 0.0, 0.5)),
    ("OverhangRightFoot", (0.2, 0.2, 1.0), (0.6, 0.0, 0.5)),
    ("OverhangTopBar", (1.4, 0.2, 0.2), (0.0, 0.0, 1.1)),
):
    member = cuboid_mesh(name, dims)
    member.location = location
    member.parent = overhang_root
central_blocker = cuboid_mesh("CentralBlocker", (0.4, 0.4, 0.4))
central_blocker.location = (0.0, 0.0, 0.2)
bpy.context.view_layer.update()

overhang_collision = sv2.audit_collisions_and_camera_clearance(
    forbidden_pairs=[(overhang_root, central_blocker)],
)
assert overhang_collision["ok"], overhang_collision
overhang_support = sv2.check_object_support(
    overhang_root,
    support_objects=[overhang_floor],
    height_tolerance=0.01,
    ray_start_above=0.5,
    ray_distance=2.0,
    hide_objects=[overhang_root],
)
assert overhang_support["ok"], overhang_support

mixed_root = bpy.data.objects.new("MixedUsableRoot", None)
bpy.context.scene.collection.objects.link(mixed_root)
mixed_usable = cube_mesh("MixedUsableMesh", 0.4)
mixed_usable.location = (-2.0, 0.0, 0.2)
mixed_usable.parent = mixed_root
mixed_unusable = cube_mesh("MixedUnusableHelper", 0.4)
mixed_unusable.location = (2.0, 0.0, 0.2)
mixed_unusable.parent = mixed_root
mixed_gap_probe = cube_mesh("MixedGapProbe", 0.2)
mixed_gap_probe.location = (0.0, 0.0, 0.2)
bpy.context.view_layer.update()

original_bvh_builder = sv2._bvh_from_mesh_obj


def fail_one_helper(mesh_obj):
    if mesh_obj.name == mixed_unusable.name:
        raise ValueError("synthetic unusable helper mesh")
    return original_bvh_builder(mesh_obj)


sv2._bvh_from_mesh_obj = fail_one_helper
try:
    mixed_report = sv2.audit_collisions_and_camera_clearance(
        forbidden_pairs=[(mixed_root, mixed_gap_probe)],
    )
finally:
    sv2._bvh_from_mesh_obj = original_bvh_builder
assert mixed_report["ok"], mixed_report

fallback_outer = cube_mesh("FallbackOuterClosedCube", 2.0)
fallback_inner = cube_mesh("FallbackInnerContainedCube", 0.4)
fallback_inner.location = (0.05, 0.05, 0.0)
bpy.context.view_layer.update()

original_bmesh_new = sv2.bmesh.new


class FailingBMesh:
    def from_object(self, mesh_obj, depsgraph):
        raise ValueError("synthetic from_object failure")

    def transform(self, matrix):
        pass

    def free(self):
        pass


sv2.bmesh.new = lambda: FailingBMesh()
try:
    fallback_report = sv2.audit_collisions_and_camera_clearance(
        forbidden_pairs=[(fallback_inner, fallback_outer)],
    )
finally:
    sv2.bmesh.new = original_bmesh_new
assert not fallback_report["ok"], fallback_report
assert fallback_report["pairs"][0]["reason"] in {
    "mesh_containment",
    "surface_overlap",
}, fallback_report
assert fallback_report["pairs"][0].get("error") is None, fallback_report

print("[collision-support-regression] PASS")
