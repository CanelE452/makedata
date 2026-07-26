import bpy, sys, os, json, mathutils
from bpy_extras import view3d_utils
sys.path.insert(0, os.path.dirname(__file__))
import blender_config as cfg, randomizers as R
import numpy as np
R.setup_render()  # full gen setup incl FloorRandPlane? no - need to build plane
R._hide_floor_grating()
plane=R._ensure_floor_plane(); plane.location=(0,0,cfg.FLOOR_PLANE_Z); plane.hide_render=False
# emission red so we know which is plane
mat=plane.data.materials[0]; mat.use_nodes=True; nt=mat.node_tree; nt.nodes.clear()
o=nt.nodes.new("ShaderNodeOutputMaterial"); e=nt.nodes.new("ShaderNodeEmission"); e.inputs[0].default_value=(1,0,0,1)
nt.links.new(e.outputs[0],o.inputs["Surface"])
# set camera to 000002
d=json.load(open("data/pallet/_floor_test10b/000002.json"))
loc=d["camera_data"]["location_worldframe"]
cam=bpy.context.scene.camera; cam.location=loc
cam.rotation_euler=(mathutils.Vector((0,0,0.1))-mathutils.Vector(loc)).to_track_quat('-Z','Y').to_euler()
bpy.context.view_layer.update()
deps=bpy.context.evaluated_depsgraph_get()
sc=bpy.context.scene
# cast rays from camera through near-floor screen positions (lower center & corners)
W,H=cfg.IMAGE_WIDTH,cfg.IMAGE_HEIGHT
camobj=cam
def ray_through(px,py):
    # normalized 0..1 screen -> view vector
    co2d=(px,1.0-py)  # blender uses bottom-left origin for region? use camera frame
    # build ray from camera using camera frame
    import math
    fr=camobj.data.view_frame(scene=sc)  # 4 corners at -1 depth in cam space
    # interpolate
    tl,bl,br,tr=fr[3],fr[0],fr[1],fr[2] if len(fr)==4 else (fr[0],fr[1],fr[2],fr[3])
    # fr order: top-right, top-left, bottom-left, bottom-right (approx). Use bilinear
    # simpler: use mathutils
    mw=camobj.matrix_world
    # corners
    c=[mw @ v for v in fr]
    # fr = [tr, br?, ...]; just bilinear over c[0..3]
    top=c[0].lerp(c[1],px); bot=c[3].lerp(c[2],px)
    target=top.lerp(bot,py)
    origin=mw.translation
    dirv=(target-origin).normalized()
    hit,hloc,n,idx,obj,m=sc.ray_cast(deps,origin,dirv)
    return obj.name if obj else None, round(hloc.z,2) if hit else None
for name,(px,py) in [("lower-center",(0.5,0.9)),("lower-left",(0.15,0.9)),("lower-right",(0.85,0.9)),("mid-center",(0.5,0.65)),("near-pallet",(0.45,0.75))]:
    obj,z=ray_through(px,py)
    print(f"  screen {name}: hit={obj} z={z}")
