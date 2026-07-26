import bpy, sys, math
from mathutils import Vector

argv = sys.argv[sys.argv.index("--")+1:]
OBJ = argv[0]
OUT_PREFIX = argv[1]  # e.g. .../before

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
ob = [o for o in bpy.context.scene.objects if o.type=='MESH'][0]

# Mark boundary edges by assigning a bright emissive material to faces touching boundary?
# Simpler: just render textured. Texture should auto-load from mtl.

# Ensure material uses texture; if import gave material, keep. Add simple world light.
world = bpy.data.worlds.new("W"); bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs[0].default_value = (1,1,1,1)
bg.inputs[1].default_value = 1.5

# render settings - EEVEE
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 900
scene.render.resolution_y = 700
scene.render.film_transparent = False
scene.eevee.taa_render_samples = 16

# bbox center/size in WORLD (after import rotation)
import numpy as np
mw = ob.matrix_world
coords = [mw @ Vector(c) for c in ob.bound_box]
xs=[c.x for c in coords]; ys=[c.y for c in coords]; zs=[c.z for c in coords]
ctr = Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
size = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))

def add_cam(name, loc, look):
    cam_data = bpy.data.cameras.new(name); cam = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    d = (look - Vector(loc)).normalized()
    cam.rotation_euler = d.to_track_quat('-Z','Y').to_euler()
    cam_data.lens = 50
    return cam

def add_sun(rot):
    s = bpy.data.lights.new("S", 'SUN'); s.energy=3.0
    so = bpy.data.objects.new("Sun", s); bpy.context.scene.collection.objects.link(so)
    so.rotation_euler = rot
    return so

add_sun((math.radians(40),math.radians(20),math.radians(10)))
add_sun((math.radians(-50),math.radians(-30),math.radians(120)))

# views: front (looking -Y world?), side, bottom-tilt, perspective
r = size*1.6
views = {
  "side":  (ctr + Vector(( r*0.05, -r,  r*0.05)),),  # world -Y is the depth side after rotation
  "persp": (ctr + Vector(( r*0.8, -r*0.8, r*0.7)),),
  "bottom":(ctr + Vector(( r*0.5,  r*0.2, -r*0.9)),),
  "low":   (ctr + Vector(( r, -r*0.3, r*0.05)),),  # low angle along X to see stringer sides
}
for vname,(loc,) in views.items():
    cam = add_cam("cam_"+vname, loc, ctr)
    scene.camera = cam
    scene.render.filepath = f"{OUT_PREFIX}_{vname}.png"
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath)
print("DONE_RENDER")
