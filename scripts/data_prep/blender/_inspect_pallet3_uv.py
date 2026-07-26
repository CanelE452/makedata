import bpy

def report(name):
    obj = bpy.data.objects.get(name)
    print(f"\n===== {name} =====")
    if obj is None:
        print("  NOT FOUND")
        # try fuzzy
        for o in bpy.data.objects:
            if name.lower() in o.name.lower():
                print("  fuzzy match:", o.name, o.type)
        return
    meshes = [obj, *obj.children_recursive]
    mesh_meshes = [m for m in meshes if m.type == "MESH"]
    print(f"  total nodes={len(meshes)} mesh nodes={len(mesh_meshes)}")
    nouv = 0
    mats = {}
    polys_total = 0
    polys_with_uv0 = 0
    for m in mesh_meshes:
        me = m.data
        uvc = len(me.uv_layers)
        if uvc == 0:
            nouv += 1
        polys_total += len(me.polygons)
        for slot in me.materials:
            mats[slot.name if slot else "<None>"] = mats.get(slot.name if slot else "<None>", 0) + 1
    print(f"  mesh nodes with NO uv layer: {nouv}/{len(mesh_meshes)}")
    print(f"  total polygons: {polys_total}")
    # sample a few meshes
    for m in mesh_meshes[:6]:
        me = m.data
        uvnames = [u.name for u in me.uv_layers]
        matnames = [ (s.name if s else "<None>") for s in me.materials]
        # uv extent
        ext = ""
        if me.uv_layers:
            us = [d.uv[0] for d in me.uv_layers[0].data]
            vs = [d.uv[1] for d in me.uv_layers[0].data]
            if us:
                ext = f" u[{min(us):.2f},{max(us):.2f}] v[{min(vs):.2f},{max(vs):.2f}]"
        print(f"    {m.name}: uv={uvnames} mats={matnames}{ext}")
    print("  material slot histogram:")
    for k, v in sorted(mats.items(), key=lambda x:-x[1]):
        print(f"    {v:4d} x {k}")

for n in ["Pallet_2", "Pallet_3", "Pallet_1", "Pallet_0"]:
    report(n)

# also dump material node teal check for source mats
print("\n===== source material base colors =====")
for mname in ["lambert16", "blinn1", "lambert16.001", "blinn1.001"]:
    m = bpy.data.materials.get(mname)
    if m and m.use_nodes:
        for node in m.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                bc = node.inputs.get("Base Color")
                print(f"  {mname}: baseColor={tuple(round(x,3) for x in bc.default_value)} linked={bc.is_linked}")
