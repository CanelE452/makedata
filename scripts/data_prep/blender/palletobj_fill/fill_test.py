import bpy, bmesh, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--")+1:]
SIDES = int(argv[0])  # fill_holes 'sides' param: only fill holes with <= sides edges. 0 = all
OBJ = r"E:/CODING/GitHub/FoundationPose/data/palletobj/pallet_full.obj"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
ob = [o for o in bpy.context.scene.objects if o.type=='MESH'][0]
me = ob.data

def stats(me, tag):
    bm = bmesh.new(); bm.from_mesh(me)
    bm.edges.ensure_lookup_table()
    boundary = [e for e in bm.edges if len(e.link_faces)==1]
    nm = [e for e in bm.edges if len(e.link_faces)>2]
    xs=[v.co.x for v in bm.verts]; ys=[v.co.y for v in bm.verts]; zs=[v.co.z for v in bm.verts]
    print(f"[{tag}] verts={len(bm.verts)} faces={len(bm.faces)} boundary={len(boundary)} nonmanifold={len(nm)}")
    print(f"[{tag}] bbox(LOCAL m) X={max(xs)-min(xs):.6f} Y(height)={max(ys)-min(ys):.6f} Z={max(zs)-min(zs):.6f}")
    print(f"[{tag}]   Xr=({min(xs):.5f},{max(xs):.5f}) Yr=({min(ys):.5f},{max(ys):.5f}) Zr=({min(zs):.5f},{max(zs):.5f})")
    bm.free()

stats(me, "BEFORE")

# fill_holes via bmesh op
bm = bmesh.new(); bm.from_mesh(me)
# select nothing needed; bmesh.ops.holes_fill operates on given edges
boundary_edges = [e for e in bm.edges if len(e.link_faces)==1]
res = bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=SIDES)
bm.to_mesh(me)
bm.free()

stats(me, f"AFTER(sides={SIDES})")
