"""Inspect sandbox scene - list collections and objects (run via Blender CLI)."""
import bpy, json, sys
from mathutils import Vector

print("=" * 60)
print("SCENE INSPECT")
print("=" * 60)

scene = bpy.context.scene
print(f"Scene: {scene.name}")
print(f"Total objects: {len(scene.objects)}")

# All collections
def walk(coll, depth=0):
    print("  " * depth + f"[COL] {coll.name}: {len(coll.objects)} objs, {len(coll.children)} subcolls")
    for c in coll.children:
        walk(c, depth + 1)

walk(scene.collection)

# Top-level objects (no parent)
print("\n--- Top-level objects (no parent) ---")
for o in scene.objects:
    if o.parent is None:
        dim = o.dimensions
        loc = o.location
        coll_names = ",".join(c.name for c in o.users_collection)
        print(f"  {o.type:8s} {o.name:45s} loc=({loc.x:+.2f},{loc.y:+.2f},{loc.z:+.2f}) dim=({dim.x:.2f},{dim.y:.2f},{dim.z:.2f}) coll=[{coll_names}] hidden_v={o.hide_viewport} hidden_r={o.hide_render}")

# Pallet specifics
print("\n--- pallet_full inspection ---")
pal = bpy.data.objects.get("pallet_full")
if pal is None:
    # try variants
    for o in bpy.data.objects:
        if "pallet" in o.name.lower() and "wooden" not in o.name.lower():
            print(f"  found candidate: {o.name}")
else:
    print(f"  loc={tuple(pal.location)}")
    print(f"  dim={tuple(pal.dimensions)}")
    print(f"  rot_euler={tuple(pal.rotation_euler)}")
    print(f"  scale={tuple(pal.scale)}")
    print(f"  parent={pal.parent.name if pal.parent else None}")
    print(f"  materials: {[s.material.name for s in pal.material_slots if s.material]}")
    # world bbox
    mw = pal.matrix_world
    bbox_world = [mw @ Vector(c) for c in pal.bound_box]
    xs = [v.x for v in bbox_world]; ys = [v.y for v in bbox_world]; zs = [v.z for v in bbox_world]
    print(f"  bbox_world X[{min(xs):.3f},{max(xs):.3f}] Y[{min(ys):.3f},{max(ys):.3f}] Z[{min(zs):.3f},{max(zs):.3f}]")

# Occluder pool
print("\n--- OCCLUDER_POOL ---")
op = bpy.data.collections.get("OCCLUDER_POOL")
if op:
    for o in op.objects:
        print(f"  {o.type:8s} {o.name:45s} dim=({o.dimensions.x:.2f},{o.dimensions.y:.2f},{o.dimensions.z:.2f}) children={len(o.children)} hidden_v={o.hide_viewport}")

# Cameras
print("\n--- Cameras ---")
for o in scene.objects:
    if o.type == 'CAMERA':
        print(f"  {o.name} lens={o.data.lens}mm sensor_w={o.data.sensor_width}")

print("\n--- World / Render ---")
print(f"  Render engine: {scene.render.engine}")
print(f"  Res: {scene.render.resolution_x}x{scene.render.resolution_y}")
print(f"  World: {scene.world.name if scene.world else None}")

print("=" * 60)
print("DONE INSPECT")
