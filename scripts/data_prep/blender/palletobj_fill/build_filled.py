"""Hole-fill the palletobj mesh while preserving UV/texture and exact bbox.

Strategy (texture+dimension preserving):
  1. holes_fill on boundary edges with sides<=SIDES  (fills small/medium tears,
     adds only faces from EXISTING verts -> bbox unchanged, UVs interpolated).
  2. (optional) recalc normals outward so no black faces.
Does NOT remesh, does NOT add verts outside hull -> dimensions guaranteed.
"""
import bpy, bmesh, sys, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--")+1:]
SIDES = int(argv[0])
OUT_OBJ = argv[1]
OBJ = r"E:/CODING/GitHub/FoundationPose/data/palletobj/pallet_full.obj"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
ob = [o for o in bpy.context.scene.objects if o.type=='MESH'][0]
me = ob.data

def stats(me, tag):
    bm = bmesh.new(); bm.from_mesh(me); bm.edges.ensure_lookup_table()
    boundary=[e for e in bm.edges if len(e.link_faces)==1]
    nm=[e for e in bm.edges if len(e.link_faces)>2]
    xs=[v.co.x for v in bm.verts]; ys=[v.co.y for v in bm.verts]; zs=[v.co.z for v in bm.verts]
    print(f"[{tag}] verts={len(bm.verts)} faces={len(bm.faces)} boundary={len(boundary)} nonmanifold={len(nm)} "
          f"X={max(xs)-min(xs):.6f} Y={max(ys)-min(ys):.6f} Z={max(zs)-min(zs):.6f}")
    bm.free()
    return len(boundary)

stats(me, "BEFORE")

# --- fill via edit-mode operator (handles non-planar holes better than bmesh.ops) ---
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
# fill holes operator: 'sides' = max sides, 0 = no limit
bpy.ops.mesh.fill_holes(sides=SIDES)
# recalc normals consistent outside (avoid dark inverted faces)
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')

stats(me, f"AFTER(sides={SIDES})")

# export OBJ keeping materials + uv
bpy.ops.object.select_all(action='DESELECT')
ob.select_set(True)
bpy.context.view_layer.objects.active = ob
bpy.ops.wm.obj_export(filepath=OUT_OBJ, export_selected_objects=True,
                      export_materials=True, export_uv=True, export_normals=True,
                      forward_axis='NEGATIVE_Z', up_axis='Y')
print("EXPORTED", OUT_OBJ)
