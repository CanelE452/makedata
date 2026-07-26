import bpy, bmesh, collections
from mathutils import Vector

OBJ = r"E:/CODING/GitHub/FoundationPose/data/palletobj/pallet_full.obj"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
ob = [o for o in bpy.context.scene.objects if o.type=='MESH'][0]
me = ob.data
bm = bmesh.new(); bm.from_mesh(me)
bm.edges.ensure_lookup_table()

boundary = [e for e in bm.edges if len(e.link_faces)==1]
vert_b_edges = collections.defaultdict(list)
for e in boundary:
    vert_b_edges[e.verts[0].index].append(e.index)
    vert_b_edges[e.verts[1].index].append(e.index)
edge_by_idx = {e.index:e for e in boundary}
visited=set(); loops=[]
for e in boundary:
    if e.index in visited: continue
    stack=[e.index]; comp=[]
    while stack:
        ei=stack.pop()
        if ei in visited: continue
        visited.add(ei); comp.append(ei)
        for v in edge_by_idx[ei].verts:
            for ne in vert_b_edges[v.index]:
                if ne not in visited: stack.append(ne)
    loops.append(comp)

# For each loop: edge count, centroid (LOCAL OBJ coords; Y is height), bbox extent
print("LOCAL coords: X=width(1.1), Y=height(0.12), Z=depth(1.3)")
print(f"{'idx':>3} {'nEdges':>6} {'cx':>7} {'cy':>7} {'cz':>7} {'dx':>6} {'dy':>6} {'dz':>6}  note")
rows=[]
for c in loops:
    vids=set()
    for ei in c:
        for v in edge_by_idx[ei].verts: vids.add(v.index)
    bm.verts.ensure_lookup_table()
    pts=[bm.verts[i].co for i in vids]
    cx=sum(p.x for p in pts)/len(pts); cy=sum(p.y for p in pts)/len(pts); cz=sum(p.z for p in pts)/len(pts)
    dx=max(p.x for p in pts)-min(p.x for p in pts)
    dy=max(p.y for p in pts)-min(p.y for p in pts)
    dz=max(p.z for p in pts)-min(p.z for p in pts)
    rows.append((len(c),cx,cy,cz,dx,dy,dz))
rows.sort(key=lambda r:-r[0])
for r in rows:
    n,cx,cy,cz,dx,dy,dz=r
    note=""
    if n>100: note="LARGE-opening(keep?)"
    elif n<=12: note="small-defect"
    print(f"{'':>3} {n:>6} {cx:>7.3f} {cy:>7.3f} {cz:>7.3f} {dx:>6.3f} {dy:>6.3f} {dz:>6.3f}  {note}")
bm.free()
