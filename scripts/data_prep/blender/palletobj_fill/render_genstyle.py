"""Render from generation-style cameras: low height (0.15-0.5m), looking at centroid,
with a floor plane + simple background so we can see 'see-through' holes against floor."""
import bpy, sys, math
from mathutils import Vector

argv = sys.argv[sys.argv.index("--")+1:]
OBJ = argv[0]; OUT_PREFIX = argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
ob = [o for o in bpy.context.scene.objects if o.type=='MESH'][0]

# world bbox (after import +90X rotation): Y world = depth, Z world = height
mw = ob.matrix_world
coords=[mw@Vector(c) for c in ob.bound_box]
xs=[c.x for c in coords]; ys=[c.y for c in coords]; zs=[c.z for c in coords]
ctr=Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
zmin=min(zs)
# ground the pallet so bottom sits at z=0
ob.location.z -= zmin
bpy.context.view_layer.update()
mw=ob.matrix_world
coords=[mw@Vector(c) for c in ob.bound_box]
xs=[c.x for c in coords]; ys=[c.y for c in coords]; zs=[c.z for c in coords]
ctr=Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
height=max(zs)-min(zs)

# floor plane (bright) so see-through holes show as bright spots
bpy.ops.mesh.primitive_plane_add(size=20, location=(ctr.x,ctr.y,0.0))
floor=bpy.context.active_object
m=bpy.data.materials.new("floor"); m.use_nodes=True
bsdf=m.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value=(0.85,0.80,0.70,1)
floor.data.materials.append(m)

# world light
w=bpy.data.worlds.new("W"); bpy.context.scene.world=w; w.use_nodes=True
bg=w.node_tree.nodes.get("Background"); bg.inputs[0].default_value=(0.6,0.65,0.7,1); bg.inputs[1].default_value=1.0
s=bpy.data.lights.new("S",'SUN'); s.energy=3.5
so=bpy.data.objects.new("Sun",s); bpy.context.scene.collection.objects.link(so)
so.rotation_euler=(math.radians(45),math.radians(15),math.radians(30))

scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.render.resolution_x=900; scene.render.resolution_y=600
scene.eevee.taa_render_samples=16

def add_cam(name,loc,look,lens=35):
    cd=bpy.data.cameras.new(name); c=bpy.data.objects.new(name,cd)
    bpy.context.scene.collection.objects.link(c)
    c.location=loc
    d=(look-Vector(loc)).normalized()
    c.rotation_euler=d.to_track_quat('-Z','Y').to_euler()
    cd.lens=lens
    return c

# gen-style: surf_dist ~0.6-1.2m, height 0.15-0.45, azimuth at side (look through fork)
r=1.0
look=Vector((ctr.x,ctr.y,0.06))
cams={
  "eye_side": (Vector((ctr.x, min(ys)-r, 0.18)), 35),     # low, looking at the fork-opening side
  "eye_3q":   (Vector((min(xs)-r*0.8, min(ys)-r*0.8, 0.30)), 35),
  "eye_close":(Vector((ctr.x+0.1, min(ys)-0.5, 0.15)), 28),
}
for nm,(loc,lens) in cams.items():
    cam=add_cam("c_"+nm,loc,look,lens)
    scene.camera=cam
    scene.render.filepath=f"{OUT_PREFIX}_{nm}.png"
    bpy.ops.render.render(write_still=True)
    print("rendered",scene.render.filepath)
print("DONE")
