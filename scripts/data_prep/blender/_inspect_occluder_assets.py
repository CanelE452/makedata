"""Find candidate occluder assets in industrial collection."""
import bpy
from mathutils import Vector

KEYWORDS = ("barrel", "cardboard", "card_board", "box", "drum", "cleaner", "toolbox", "cheese", "tin", "wetfloor", "sign")
print("--- Candidate occluder assets (top-level in BG_industrial) ---")
ind = bpy.data.collections.get("BG_industrial")
if ind:
    for o in ind.objects:
        nm = o.name.lower()
        if any(k in nm for k in KEYWORDS):
            mw = o.matrix_world
            bbox = [mw @ Vector(c) for c in o.bound_box]
            xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
            dim = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
            print(f"  {o.type:6s} {o.name:50s} dim_world=({dim[0]:.2f},{dim[1]:.2f},{dim[2]:.2f}) hidden_v={o.hide_viewport}")

# all empties / mesh keyword groups across whole data
print("\n--- All bpy.data.objects matching keywords ---")
for o in bpy.data.objects:
    nm = o.name.lower()
    if any(k in nm for k in KEYWORDS):
        print(f"  {o.type:6s} {o.name}")

# any collections we missed
print("\n--- All collections ---")
for c in bpy.data.collections:
    print(f"  [COL] {c.name} ({len(c.objects)} objs)")
