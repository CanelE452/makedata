"""Blender-side regression for shared-mesh holdout material restoration."""

import os
import sys
import tempfile

import bpy


SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import v2_realize as realize


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.resolution_percentage = 100

mesh = bpy.data.meshes.new("SharedCargoMesh")
mesh.from_pydata(
    [(-0.4, -0.4, 0.0), (0.4, -0.4, 0.0), (0.4, 0.4, 0.0), (-0.4, 0.4, 0.0)],
    [],
    [(0, 1, 2, 3)],
)
mesh.update()
original = bpy.data.materials.new("OriginalCargoMaterial")
original.diffuse_color = (0.45, 0.22, 0.08, 1.0)
mesh.materials.append(original)

left = bpy.data.objects.new("SharedCargoLeft", mesh)
right = bpy.data.objects.new("SharedCargoRight", mesh)
left.location.x = -0.5
right.location.x = 0.5
scene.collection.objects.link(left)
scene.collection.objects.link(right)

camera_data = bpy.data.cameras.new("Camera")
camera = bpy.data.objects.new("Camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0.0, 0.0, 3.0)
camera.rotation_euler = (0.0, 0.0, 0.0)
scene.camera = camera

with tempfile.TemporaryDirectory() as temp_dir:
    realize._render_holdout(
        scene,
        left,
        os.path.join(temp_dir, "shared_material_mask.png"),
        only_white=[left],
    )

assert list(mesh.materials) == [original], [
    material.name if material else None for material in mesh.materials
]
assert left.material_slots[0].material == original
assert right.material_slots[0].material == original
print("[shared-material-regression] PASS")
