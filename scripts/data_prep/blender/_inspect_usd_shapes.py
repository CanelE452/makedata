import bpy
import os
import math
from mathutils import Vector

USD_DIR = r"E:\CODING\GitHub\FoundationPose\data\pallet\models_usd"
OUT_DIR = r"E:\CODING\GitHub\FoundationPose\data\pallet\models_usd\_shape_inspect"
os.makedirs(OUT_DIR, exist_ok=True)

SCENES = ["scene_1.usd", "scene_2.usd", "scene_3.usd"]
TARGET = 1.2  # normalize longest dim to this many BU


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for b in list(block):
            if b.users == 0:
                block.remove(b)


def import_usd(path):
    before = set(bpy.data.objects)
    bpy.ops.wm.usd_import(filepath=path)
    after = set(bpy.data.objects)
    return list(after - before)


def world_bbox(objs):
    mins = Vector((1e18, 1e18, 1e18))
    maxs = Vector((-1e18, -1e18, -1e18))
    found = False
    for o in objs:
        if o.type != 'MESH':
            continue
        found = True
        for c in o.bound_box:
            wc = o.matrix_world @ Vector(c)
            for i in range(3):
                mins[i] = min(mins[i], wc[i])
                maxs[i] = max(maxs[i], wc[i])
    if not found:
        return None, None
    return mins, maxs


def parent_to_empty(objs, name):
    empty = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(empty)
    for o in objs:
        if o.parent is None:
            o.parent = empty
            o.matrix_parent_inverse = empty.matrix_world.inverted()
    return empty


def setup_camera(loc, look_at, lens=50):
    cam_data = bpy.data.cameras.new("InspCam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("InspCam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = loc
    d = (Vector(look_at) - Vector(loc))
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


def add_lights():
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
    sun.data.energy = 3.0
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(20), math.radians(30))
    bpy.context.scene.world = bpy.data.worlds.new("W")
    bpy.context.scene.world.use_nodes = True
    bg = bpy.context.scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.25, 0.25, 0.28, 1)
        bg.inputs[1].default_value = 0.6


def render(path, res=900):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.filepath = path
    sc.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)


def report_dims(objs, label):
    mn, mx = world_bbox(objs)
    if mn is None:
        print(f"[{label}] NO MESH")
        return None
    dx, dy, dz = (mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2])
    nmesh = sum(1 for o in objs if o.type == 'MESH')
    print(f"[{label}] dims(X={dx:.3f} Y={dy:.3f} Z={dz:.3f}) meshes={nmesh}")
    return (dx, dy, dz, nmesh)


# ---- Per-scene individual top-angled render ----
collected = {}
for sc_name in SCENES:
    clear_scene()
    add_lights()
    path = os.path.join(USD_DIR, sc_name)
    objs = import_usd(path)
    raw = report_dims(objs, sc_name + " RAW")
    # normalize: scale so longest of bbox = TARGET, center at origin
    mn, mx = world_bbox(objs)
    size = mx - mn
    longest = max(size)
    s = TARGET / longest if longest > 0 else 1.0
    empty = parent_to_empty(objs, "root_" + sc_name)
    empty.scale = (s, s, s)
    bpy.context.view_layer.update()
    mn, mx = world_bbox(objs)
    center = (mn + mx) * 0.5
    empty.location -= center
    bpy.context.view_layer.update()
    norm = report_dims(objs, sc_name + " NORM")
    collected[sc_name] = {"raw": raw, "norm": norm}
    # camera: angled top-down looking at origin
    setup_camera(loc=(1.6, -1.6, 1.4), look_at=(0, 0, 0), lens=45)
    render(os.path.join(OUT_DIR, sc_name.replace(".usd", "_angle.png")))
    # pure top view
    setup_camera(loc=(0, 0, 3.0), look_at=(0, 0, 0), lens=45)
    render(os.path.join(OUT_DIR, sc_name.replace(".usd", "_top.png")))

# ---- Side-by-side comparison ----
clear_scene()
add_lights()
offsets = {"scene_1.usd": -1.6, "scene_2.usd": 0.0, "scene_3.usd": 1.6}
for sc_name in SCENES:
    objs = import_usd(os.path.join(USD_DIR, sc_name))
    mn, mx = world_bbox(objs)
    size = mx - mn
    longest = max(size)
    s = TARGET / longest if longest > 0 else 1.0
    empty = parent_to_empty(objs, "root_cmp_" + sc_name)
    empty.scale = (s, s, s)
    bpy.context.view_layer.update()
    mn, mx = world_bbox(objs)
    center = (mn + mx) * 0.5
    empty.location -= center
    bpy.context.view_layer.update()
    empty.location.x += offsets[sc_name]

setup_camera(loc=(0.0, -4.5, 3.2), look_at=(0, 0, 0), lens=40)
render(os.path.join(OUT_DIR, "compare_angle.png"), res=1400)
setup_camera(loc=(0.0, 0.0, 6.0), look_at=(0, 0, 0), lens=40)
render(os.path.join(OUT_DIR, "compare_top.png"), res=1400)

print("DONE")
for k, v in collected.items():
    print(k, v)
