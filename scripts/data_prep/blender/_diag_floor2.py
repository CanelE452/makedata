"""Confirm the Floor.NNN_Asphalt_0 meshes belong to BG_industrial and live at
z~=0, so they (not FloorRandPlane) are the visible grey ground. Also list the
exact set of name prefixes we must add to the hide list."""
import os, sys
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import blender_config as cfg
import randomizers
from randomizers import get_obj


def ancestors(o):
    out = []
    p = o.parent
    while p is not None:
        out.append(p.name)
        p = p.parent
    return out


def main():
    randomizers.initialize_backgrounds()
    bg = get_obj("BG_industrial")
    print(f"BG_industrial exists = {bg is not None}")
    industrial_set = set()
    if bg is not None:
        for c in bg.children_recursive:
            industrial_set.add(c.name)
    print(f"BG_industrial children_recursive count = {len(industrial_set)}")

    # all Floor* asphalt meshes
    floors = [o for o in bpy.data.objects
              if o.type == "MESH" and o.name.startswith("Floor")]
    print(f"\nTotal 'Floor*' meshes = {len(floors)}")
    in_bg = sum(1 for o in floors if o.name in industrial_set)
    print(f"  of which children of BG_industrial = {in_bg}")
    # z range of the asphalt ground
    zmins, zmaxs = [], []
    for o in floors:
        ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
        zs = [v.z for v in ws]
        zmins.append(min(zs)); zmaxs.append(max(zs))
    if floors:
        print(f"  Floor* z span: zmin in [{min(zmins):.3f},{max(zmins):.3f}], "
              f"zmax in [{min(zmaxs):.3f},{max(zmaxs):.3f}]")
        ex = floors[0]
        print(f"  example {ex.name}: ancestors={ancestors(ex)}")

    # what distinct name-prefixes among SHOWN low ground meshes (excluding our plane)
    print("\n=== distinct prefixes of BG_industrial GROUND-level meshes (z<=0.30) ===")
    pref = {}
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name == "FloorRandPlane":
            continue
        if o.name not in industrial_set:
            continue
        ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
        zs = [v.z for v in ws]
        if min(zs) > 0.30:
            continue
        # prefix up to first dot/underscore-number
        base = o.name.split(".")[0]
        pref.setdefault(base, [0, 999.0, -999.0])
        pref[base][0] += 1
        pref[base][1] = min(pref[base][1], min(zs))
        pref[base][2] = max(pref[base][2], max(zs))
    for k, (c, zl, zh) in sorted(pref.items()):
        print(f"  {k:24s} n={c:3d}  z[{zl:.3f},{zh:.3f}]")


if __name__ == "__main__":
    main()
