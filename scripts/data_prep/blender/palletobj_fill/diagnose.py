import bpy, bmesh, sys, math
from mathutils import Vector

OBJ = r"E:/CODING/GitHub/FoundationPose/data/palletobj/pallet_full.obj"

# clean scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Blender 5.x OBJ importer (Y-up forward -Z by default for wavefront)
bpy.ops.wm.obj_import(filepath=OBJ)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
print("imported mesh objects:", [o.name for o in objs])
ob = objs[0]
me = ob.data

bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
bm.edges.ensure_lookup_table()
bm.faces.ensure_lookup_table()

n_verts = len(bm.verts)
n_faces = len(bm.faces)
n_edges = len(bm.edges)

# boundary edges = edges with exactly 1 linked face
boundary = [e for e in bm.edges if len(e.link_faces) == 1]
# non-manifold edges = edges with >2 linked faces OR 0
nonmanifold_edges = [e for e in bm.edges if len(e.link_faces) > 2]
wire_edges = [e for e in bm.edges if len(e.link_faces) == 0]

# count boundary loops (holes). Build adjacency among boundary edges via shared verts
import collections
bset = set(e.index for e in boundary)
vert_b_edges = collections.defaultdict(list)
for e in boundary:
    vert_b_edges[e.verts[0].index].append(e.index)
    vert_b_edges[e.verts[1].index].append(e.index)

# connected components over boundary edge graph
visited = set()
loops = []
edge_by_idx = {e.index: e for e in boundary}
for e in boundary:
    if e.index in visited:
        continue
    stack = [e.index]
    comp = []
    while stack:
        ei = stack.pop()
        if ei in visited:
            continue
        visited.add(ei)
        comp.append(ei)
        ed = edge_by_idx[ei]
        for v in ed.verts:
            for ne in vert_b_edges[v.index]:
                if ne not in visited:
                    stack.append(ne)
    loops.append(comp)

# loop sizes = number of edges
loop_sizes = sorted(len(c) for c in loops)

# bbox in local coords (OBJ Y-up). Apply object matrix? import keeps transform; get world bbox via verts*matrix
mw = ob.matrix_world
xs=[]; ys=[]; zs=[]
for v in bm.verts:
    co = mw @ v.co
    xs.append(co.x); ys.append(co.y); zs.append(co.z)
def rng(a): return (min(a), max(a), max(a)-min(a))
print("=== DIAGNOSIS ===")
print("verts:", n_verts, "edges:", n_edges, "faces:", n_faces)
print("boundary_edges:", len(boundary))
print("nonmanifold_edges(>2 faces):", len(nonmanifold_edges))
print("wire_edges(0 faces):", len(wire_edges))
print("num_boundary_loops(holes):", len(loops))
print("boundary_loop_sizes (edge count per loop, sorted):", loop_sizes)
# histogram of loop sizes
hist = collections.Counter(loop_sizes)
print("loop_size_histogram:", dict(sorted(hist.items())))
# small holes (<=12 edges) vs large openings
small = [s for s in loop_sizes if s <= 12]
print("small_loops(<=12 edges):", len(small), "| sizes:", small)
print("large_loops(>12 edges):", [s for s in loop_sizes if s>12])
print("WORLD bbox X:", rng(xs))
print("WORLD bbox Y:", rng(ys))
print("WORLD bbox Z:", rng(zs))
# also local (pre-matrix)
xs=[v.co.x for v in bm.verts]; ys=[v.co.y for v in bm.verts]; zs=[v.co.z for v in bm.verts]
print("LOCAL bbox X:", rng(xs))
print("LOCAL bbox Y:", rng(ys))
print("LOCAL bbox Z:", rng(zs))
print("matrix_world:", [list(r) for r in mw])
bm.free()
print("=== END ===")
