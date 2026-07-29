"""Generate synthetic data for palletobj (data/palletobj/pallet_full.obj).

Run with:
  blender -b data/pallet/blender_scene/_sandbox_parking_lot_check.blend \
          --python scripts/data_prep/blender/gen_palletobj_v1.py -- \
          --out data/pallet/test_palletobj_v1 --n 10 --seed 42
"""
import bpy, os, sys, json, math, random, argparse, subprocess, time
from mathutils import Vector, Matrix
from bpy_extras import object_utils as obj_utils

# ---------- argparse (after `--`) ----------
argv = sys.argv
if "--" in argv:
    argv = argv[argv.index("--") + 1:]
else:
    argv = []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--seed", type=int, default=42)
args = ap.parse_args(argv)

random.seed(args.seed)
OUT = os.path.abspath(args.out)
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "overlay"), exist_ok=True)
os.makedirs(os.path.join(OUT, "mask"), exist_ok=True)

# ---------- ensure Pillow ----------
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    print("[setup] installing Pillow into Blender bundled python...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

# ---------- scene refs ----------
scene = bpy.context.scene
cam = bpy.data.objects.get("Camera")
pal = bpy.data.objects.get("pallet_full")
if cam is None or pal is None:
    raise RuntimeError("Camera or pallet_full missing")

# Render setup
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 640
scene.render.resolution_y = 480
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
try:
    scene.eevee.taa_render_samples = 16
except Exception:
    pass
# Camera intrinsics setup
cam.data.sensor_width = 36.0
cam.data.clip_start = 0.005
cam.data.clip_end = 200.0

IW, IH = scene.render.resolution_x, scene.render.resolution_y
SW = cam.data.sensor_width

# ---------- bg collections ----------
COL_PARK = bpy.data.collections.get("BG_parking_lot")
COL_IND = bpy.data.collections.get("BG_industrial")

def set_collection_hidden(coll, hidden):
    if coll is None:
        return
    # Use layer collection to hide for both viewport and render
    def find_layer(lc, name):
        if lc.collection.name == name: return lc
        for ch in lc.children:
            r = find_layer(ch, name)
            if r: return r
        return None
    lc = find_layer(scene.view_layers[0].layer_collection, coll.name)
    if lc:
        lc.hide_viewport = hidden
    # also per-object hide_render so render skips
    for o in coll.objects:
        o.hide_render = hidden
    coll.hide_render = hidden

# ---------- HDRI ----------
HDRI_DIR = os.path.abspath("data/pallet/assets/lighting/hdri/library")  # Stage 2-B: registry hdri_root
HDRI_FILES = [
    "construction_yard_2k.hdr",
    "factory_yard_2k.hdr",
    "freight_station_2k.hdr",
    "mall_parking_lot_2k.hdr",
    "overcast_industrial_courtyard_2k.hdr",
]

def ensure_world_nodes():
    w = scene.world
    if w is None:
        w = bpy.data.worlds.new("World"); scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    mapping = nt.nodes.new("ShaderNodeMapping")
    texcoord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return env, bg, mapping

ENV_NODE, BG_NODE, MAP_NODE = ensure_world_nodes()

def set_hdri(name, strength, rot_z):
    path = os.path.join(HDRI_DIR, name)
    img = bpy.data.images.load(path, check_existing=True)
    ENV_NODE.image = img
    BG_NODE.inputs["Strength"].default_value = strength
    MAP_NODE.inputs["Rotation"].default_value[2] = rot_z

# ---------- occluder source pool (look up by name each time) ----------
OCCLUDER_NAMES = ["Barrel", "Barrel.001", "Barrel.002",
                  "Cardboard", "Cardboard.001", "Cardboard.002", "Cardboard.003", "Cardboard.004"]
def get_occluder_sources():
    out = []
    for nm in OCCLUDER_NAMES:
        o = bpy.data.objects.get(nm)
        if o is not None:
            out.append(o)
    return out
print(f"[setup] occluder source names: {OCCLUDER_NAMES}")

# ---------- pallet keypoints ----------
KP_SIGN_TO_ID = {
    (-1,-1,+1):0, (+1,-1,+1):1, (+1,-1,-1):2, (-1,-1,-1):3,
    (-1,+1,+1):4, (+1,+1,+1):5, (+1,+1,-1):6, (-1,+1,-1):7,
}
# Edges (per project convention)
EDGES_TOP    = [(0,1),(1,5),(5,4),(4,0)]
EDGES_BOTTOM = [(3,2),(2,6),(6,7),(7,3)]
EDGES_VERT   = [(0,3),(1,2),(5,6),(4,7)]

def pallet_corners_world():
    mw = pal.matrix_world
    corners = [mw @ Vector(c) for c in pal.bound_box]
    # reorder by sign
    cx = sum(v.x for v in corners)/8
    cy = sum(v.y for v in corners)/8
    cz = sum(v.z for v in corners)/8
    out = [None]*8
    for v in corners:
        sx = +1 if v.x>cx else -1
        sy = +1 if v.y>cy else -1
        sz = +1 if v.z>cz else -1
        out[KP_SIGN_TO_ID[(sx,sy,sz)]] = v
    centroid = Vector((cx,cy,cz))
    return out, centroid

# Pallet half-extent along world XY for a given azimuth
PAL_HX = 0.55  # along world X (1.10/2)
PAL_HY = 0.65  # along world Y (1.30/2)
def pallet_extent_along_az(az_rad):
    cosx = abs(math.cos(az_rad)); siny = abs(math.sin(az_rad))
    a = PAL_HX/cosx if cosx > 1e-9 else float('inf')
    b = PAL_HY/siny if siny > 1e-9 else float('inf')
    return min(a, b)

# ---------- raycast utilities ----------
def raycast_floor(x, y, exclude_obj=None):
    # exclude pallet by hiding it
    saved = None
    if exclude_obj:
        saved = (exclude_obj.hide_viewport, exclude_obj.hide_render)
        exclude_obj.hide_viewport = True; exclude_obj.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = scene.ray_cast(dg, Vector((x, y, 10.0)), Vector((0,0,-1)))
    if exclude_obj:
        exclude_obj.hide_viewport, exclude_obj.hide_render = saved
    return float(loc.z) if hit else None

def count_corners_in_frame(corners_w):
    n = 0
    for c in corners_w:
        co = obj_utils.world_to_camera_view(scene, cam, c)
        if co.z > 0 and 0.0 <= co.x <= 1.0 and 0.0 <= co.y <= 1.0:
            n += 1
    return n

def count_corners_unoccluded(corners_w):
    saved = (pal.hide_viewport, pal.hide_render)
    pal.hide_viewport = True; pal.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    n = 0
    for c in corners_w:
        d = c - cam.location
        dist = d.length
        if dist < 1e-6: continue
        hit, *_ = scene.ray_cast(dg, cam.location, d/dist, distance=dist*0.97)
        if not hit:
            n += 1
    pal.hide_viewport, pal.hide_render = saved
    bpy.context.view_layer.update()
    return n

def corner_in_frame_and_unoccluded(corner_w):
    co = obj_utils.world_to_camera_view(scene, cam, corner_w)
    in_frame = (co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1)
    if not in_frame:
        return False, False
    saved = (pal.hide_viewport, pal.hide_render)
    pal.hide_viewport = True; pal.hide_render = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    d = corner_w - cam.location; dist = d.length
    hit, *_ = scene.ray_cast(dg, cam.location, d/dist, distance=dist*0.97)
    pal.hide_viewport, pal.hide_render = saved
    bpy.context.view_layer.update()
    return True, not hit

# ---------- camera placement ----------
def aim_camera(pos, look_at):
    cam.location = pos
    d = (Vector(look_at) - Vector(pos))
    # Blender camera looks along -Z, up is +Y of camera
    rot_q = d.to_track_quat('-Z', 'Y')
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = rot_q
    bpy.context.view_layer.update()

# ---------- occluder spawn ----------
SPAWNED = []
def cleanup_spawned():
    for o in SPAWNED:
        try:
            # delete the object and its mesh children (linked dupes share data; just remove objects)
            for ch in list(o.children):
                bpy.data.objects.remove(ch, do_unlink=True)
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            pass
    SPAWNED.clear()

def duplicate_with_children(src):
    """Duplicate an EMPTY parent with all its mesh children (linked obj data).
    Use bpy.data.batch_remove-safe approach: copy() each, re-parent, link to scene.
    """
    # Temporarily unhide source for selection
    src_hidden = (src.hide_viewport, src.hide_render)
    src.hide_viewport = False
    for ch in src.children:
        ch.hide_viewport = False

    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True)
    for ch in src.children:
        if ch.name in bpy.context.view_layer.objects:
            ch.select_set(True)
    bpy.context.view_layer.objects.active = src
    bpy.ops.object.duplicate(linked=True)
    new_parent = bpy.context.active_object

    # restore source hidden state
    src.hide_viewport, src.hide_render = src_hidden
    for ch in bpy.data.objects.get(src.name).children:
        ch.hide_viewport = src_hidden[0]
        ch.hide_render = src_hidden[1]

    # make duplicate visible, move it to scene root collection
    # (so BG_industrial collection hide doesn't kill the occluder)
    main_coll = scene.collection
    for o in [new_parent] + list(new_parent.children):
        for c in list(o.users_collection):
            try:
                c.objects.unlink(o)
            except Exception:
                pass
        try:
            main_coll.objects.link(o)
        except Exception:
            pass
        o.hide_viewport = False
        o.hide_render = False
    return new_parent

def spawn_occluder_targeted(cam_pos, target_corner, floor_z):
    sources = get_occluder_sources()
    if not sources:
        return None, None
    src = random.choice(sources)
    new_parent = duplicate_with_children(src)
    new_parent.name = f"_OCCL_{len(SPAWNED)}_{src.name}"

    cam_v = Vector(cam_pos); tgt = Vector(target_corner)
    t = random.uniform(0.55, 0.78)
    pos = cam_v.lerp(tgt, t)
    fwd = (tgt - cam_v); fwd.z = 0
    if fwd.length < 1e-6:
        perp = Vector((1,0,0))
    else:
        fwd.normalize()
        perp = Vector((-fwd.y, fwd.x, 0)).normalized()
    pos += perp * random.uniform(-0.15, 0.15)

    # Drop to floor (use bbox lowest z)
    new_parent.location = (pos.x, pos.y, floor_z + 5.0)  # temp high
    new_parent.rotation_euler = (0, 0, random.uniform(0, 2*math.pi))
    bpy.context.view_layer.update()
    # compute min z over children meshes
    zmin = None
    for ch in new_parent.children:
        if ch.type != 'MESH': continue
        mw = ch.matrix_world
        for v in ch.bound_box:
            wz = (mw @ Vector(v)).z
            zmin = wz if zmin is None else min(zmin, wz)
    if zmin is None:
        # fallback: empty itself
        new_parent.location.z = floor_z
    else:
        new_parent.location.z += (floor_z - zmin)
    bpy.context.view_layer.update()
    SPAWNED.append(new_parent)
    return new_parent, src.name

# ---------- intrinsics ----------
def hfov_deg_from_lens(lens_mm):
    return 2 * math.degrees(math.atan(SW / (2 * lens_mm)))

def intrinsics_dict(lens_mm):
    fx = lens_mm * IW / SW
    return {"fx": fx, "fy": fx, "cx": IW/2.0, "cy": IH/2.0,
            "lens_mm": lens_mm, "sensor_mm": SW, "hfov_deg": hfov_deg_from_lens(lens_mm),
            "width": IW, "height": IH}

# ---------- one frame generation ----------
def project_kp(world_pos):
    co = obj_utils.world_to_camera_view(scene, cam, world_pos)
    px = co.x * IW
    py = (1.0 - co.y) * IH
    in_frame = (co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1)
    return (px, py, in_frame, co.z)

def generate_frame(idx):
    max_retry = 10
    for attempt in range(max_retry):
        cleanup_spawned()

        # 1) background toggle
        bg_choice = random.choice(["parking_lot", "industrial"])
        if bg_choice == "parking_lot":
            set_collection_hidden(COL_PARK, False)
            set_collection_hidden(COL_IND, True)
            pal_xy = (0.0, 0.0)
        else:
            set_collection_hidden(COL_PARK, True)
            set_collection_hidden(COL_IND, False)
            # pick free position
            pal_xy = random.choice([(-4,1),(-4,2),(-4,3),(-4,4),(-3,1),(-3,2),(-3,3),(-3,4),(-2,2)])

        # 2) place pallet & ground it via raycast
        pal.location.x = pal_xy[0]
        pal.location.y = pal_xy[1]
        # initial z high so raycast under pallet works
        pal.location.z = 0.1
        bpy.context.view_layer.update()
        floor_z = raycast_floor(pal_xy[0], pal_xy[1], exclude_obj=pal)
        if floor_z is None:
            floor_z = 0.0
        # ground pallet bottom to floor
        mw = pal.matrix_world
        zmin_p = min((mw @ Vector(v.co)).z for v in pal.data.vertices)
        pal.location.z += (floor_z - zmin_p)
        bpy.context.view_layer.update()

        corners, centroid = pallet_corners_world()

        # 3) sample camera params
        az_base = random.choice([0.0, -math.pi/2, math.pi])  # 3,6,9 o'clock
        az = az_base + math.radians(random.uniform(-25, 25))
        surf_dist = random.uniform(0.03, 5.0)
        cam_height = random.uniform(0.15, 0.50)
        lens_mm = random.uniform(24.0, 50.0)
        cam.data.lens = lens_mm

        ext = pallet_extent_along_az(az)
        radius = ext + surf_dist
        cam_pos = (centroid.x + radius*math.cos(az),
                   centroid.y + radius*math.sin(az),
                   floor_z + cam_height)
        # lookat = pallet centroid (xy) at floor+0.06 (pallet vertical mid)
        look_at = Vector((centroid.x, centroid.y, floor_z + 0.06))

        # truncation
        do_trunc = (surf_dist >= 0.5) and (random.random() < 0.4)
        if do_trunc:
            shift_mag = random.uniform(0.3, 0.8)
            shift_dir = random.uniform(0, 2*math.pi)
            look_at = Vector((look_at.x + shift_mag*math.cos(shift_dir),
                              look_at.y + shift_mag*math.sin(shift_dir),
                              look_at.z))

        aim_camera(cam_pos, look_at)

        # 4) check visibility (baseline)
        n_in = count_corners_in_frame(corners)
        if n_in < 4:
            continue
        n_un_base = count_corners_unoccluded(corners)
        # both in frame and unoccluded
        n_both_base = sum(1 for c in corners if all(corner_in_frame_and_unoccluded(c)))
        if n_un_base < 4 or n_both_base < 4:
            continue

        # 5) occlusion
        occluder_name = None
        do_occ = (surf_dist >= 1.0) and (random.random() < 0.5)
        if do_occ and get_occluder_sources():
            # pick a corner that's currently visible to target
            visible = [c for c in corners if all(corner_in_frame_and_unoccluded(c))]
            if visible:
                target = random.choice(visible)
                _, occluder_name = spawn_occluder_targeted(cam_pos, target, floor_z)
                # check effectiveness: corner count should drop, but still >=4
                n_un_after = count_corners_unoccluded(corners)
                n_both_after = sum(1 for c in corners if all(corner_in_frame_and_unoccluded(c)))
                if n_un_after >= n_un_base:
                    # not effective
                    cleanup_spawned()
                    occluder_name = None
                elif n_both_after < 4:
                    # too much occlusion -> reject this attempt
                    continue
                else:
                    pass  # ok

        # 6) HDRI
        hdri_name = random.choice(HDRI_FILES)
        hdri_strength = random.uniform(0.5, 1.4)
        hdri_rot = random.uniform(0, 2*math.pi)
        set_hdri(hdri_name, hdri_strength, hdri_rot)

        # 7) final visibility recount (after occluder + hdri)
        n_in_final = count_corners_in_frame(corners)
        n_un_final = count_corners_unoccluded(corners)
        n_both_final = sum(1 for c in corners if all(corner_in_frame_and_unoccluded(c)))
        if n_in_final < 4 or n_un_final < 4 or n_both_final < 4:
            continue

        # 8) render
        img_path = os.path.join(OUT, f"{idx:06d}.png")
        scene.render.filepath = img_path
        bpy.ops.render.render(write_still=True)

        # 9) annotation
        kp_proj = [project_kp(c) for c in corners]
        c_proj = project_kp(centroid)
        ann = {
            "frame": idx,
            "bg": bg_choice,
            "pallet_xy": list(pal_xy),
            "floor_z": floor_z,
            "camera": {
                "location": list(cam.location),
                "rotation_quaternion_wxyz": list(cam.rotation_quaternion),
                "look_at": list(look_at),
                "azimuth_deg": math.degrees(az),
                "surf_dist_m": surf_dist,
                "height_m": cam_height,
            },
            "intrinsics": intrinsics_dict(lens_mm),
            "objects": [{
                "name": "pallet_full",
                "class": "pallet",
                "location": list(pal.location),
                "rotation_euler_xyz": list(pal.rotation_euler),
                "dimensions": list(pal.dimensions),
                "cuboid_centroid_world": list(centroid),
                "cuboid_corners_world": [list(c) for c in corners],
                "projected_cuboid": [[p[0], p[1]] for p in kp_proj],
                "projected_cuboid_centroid": [c_proj[0], c_proj[1]],
                "cuboid_corner_in_frame": [p[2] for p in kp_proj],
            }],
            "visibility": {
                "n_corners_in_frame": n_in_final,
                "n_corners_unoccluded": n_un_final,
                "n_corners_in_frame_and_unoccluded": n_both_final,
                "fraction_visible": n_both_final / 8.0,
            },
            "occluder": occluder_name,
            "truncation": do_trunc,
            "hdri": {"name": hdri_name, "strength": hdri_strength, "rot_z": hdri_rot},
            "attempt": attempt,
        }
        with open(os.path.join(OUT, f"{idx:06d}.json"), "w") as f:
            json.dump(ann, f, indent=2)

        # 10) overlay
        draw_overlay(img_path, ann, kp_proj, c_proj)
        return ann
    cleanup_spawned()
    return None

# ---------- overlay ----------
def draw_overlay(img_path, ann, kp_proj, c_proj):
    im = Image.open(img_path).convert("RGB")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        font_small = ImageFont.truetype("arial.ttf", 10)
    except Exception:
        font = ImageFont.load_default(); font_small = font

    TOP_IDS = {0,1,4,5}
    BOT_IDS = {2,3,6,7}

    def col_for(i):
        if i in TOP_IDS: return (0, 255, 0)
        if i in BOT_IDS: return (255, 60, 60)
        return (255, 255, 0)

    # edges
    def line(a, b, color):
        if not kp_proj[a][2] and not kp_proj[b][2]:
            color = (128,128,128)
        elif not kp_proj[a][2] or not kp_proj[b][2]:
            color = (160,160,80)
        dr.line([(kp_proj[a][0], kp_proj[a][1]), (kp_proj[b][0], kp_proj[b][1])], fill=color, width=2)
    for a,b in EDGES_TOP:    line(a, b, (0,255,0))
    for a,b in EDGES_BOTTOM: line(a, b, (255,60,60))
    for a,b in EDGES_VERT:   line(a, b, (255,160,0))

    # corner dots + ID labels
    for i, (x, y, ok, _z) in enumerate(kp_proj):
        c = col_for(i) if ok else (160,160,160)
        r = 4
        dr.ellipse([x-r,y-r,x+r,y+r], outline=(0,0,0), fill=c)
        dr.text((x+5, y-12), str(i), fill=c, font=font_small)
    # centroid
    cx, cy, cok, _ = c_proj
    if cok:
        r = 5
        dr.ellipse([cx-r,cy-r,cx+r,cy+r], outline=(0,0,0), fill=(255,255,0))
        dr.text((cx+6, cy-14), "8", fill=(255,255,0), font=font_small)

    # top metadata bar
    bar_h = 22
    bar = Image.new("RGB", (IW, bar_h), (0,0,0))
    bd = ImageDraw.Draw(bar)
    v = ann["visibility"]
    txt = (f"#{ann['frame']:03d} bg={ann['bg']:<11s} "
           f"d={ann['camera']['surf_dist_m']:.2f}m h={ann['camera']['height_m']:.2f}m "
           f"lens={ann['intrinsics']['lens_mm']:.1f}mm hfov={ann['intrinsics']['hfov_deg']:.0f}deg "
           f"vis={v['n_corners_in_frame_and_unoccluded']}/8 "
           f"T={'Y' if ann['truncation'] else 'N'} O={ann['occluder'] or 'N'}")
    bd.text((4, 4), txt, fill=(255,255,255), font=font)
    out_img = Image.new("RGB", (IW, IH + bar_h), (0,0,0))
    out_img.paste(bar, (0, 0))
    out_img.paste(im, (0, bar_h))
    overlay_path = os.path.join(OUT, "overlay", f"{ann['frame']:06d}.png")
    out_img.save(overlay_path)

# ---------- save baseline ----------
print(f"[setup] saving sandbox backup before run...")
try:
    bpy.ops.wm.save_as_mainfile(filepath="data/pallet/blender_scene/_sandbox_parking_lot_check.blend", copy=True)
except Exception as e:
    print(f"[warn] could not save: {e}")

# ---------- run ----------
results = []
t0 = time.time()
for i in range(args.n):
    ts = time.time()
    r = generate_frame(i)
    cleanup_spawned()
    dt = time.time() - ts
    if r is None:
        print(f"[frame {i:03d}] FAILED after retries")
        results.append(None)
    else:
        v = r["visibility"]
        print(f"[frame {i:03d}] {dt:.1f}s bg={r['bg']:<11s} d={r['camera']['surf_dist_m']:.2f} h={r['camera']['height_m']:.2f} "
              f"lens={r['intrinsics']['lens_mm']:.1f} vis={v['n_corners_in_frame_and_unoccluded']}/8 "
              f"T={r['truncation']} O={r['occluder']}")
        results.append(r)

print(f"[done] total {time.time()-t0:.1f}s, {sum(1 for r in results if r)}/{args.n} ok")

# Write summary
with open(os.path.join(OUT, "_summary.json"), "w") as f:
    json.dump({
        "n_requested": args.n,
        "n_ok": sum(1 for r in results if r),
        "seed": args.seed,
        "results": [{"frame": i, "ok": r is not None,
                     "bg": r["bg"] if r else None,
                     "surf_dist_m": r["camera"]["surf_dist_m"] if r else None,
                     "height_m": r["camera"]["height_m"] if r else None,
                     "lens_mm": r["intrinsics"]["lens_mm"] if r else None,
                     "vis": r["visibility"]["n_corners_in_frame_and_unoccluded"] if r else None,
                     "truncation": r["truncation"] if r else None,
                     "occluder": r["occluder"] if r else None}
                    for i, r in enumerate(results)],
    }, f, indent=2)

print("[done] summary saved")
