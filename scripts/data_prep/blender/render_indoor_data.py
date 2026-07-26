"""
Indoor environment synthetic data renderer for DOPE training.
Generates diverse training images with NDDS JSON annotations.

Usage:
    blender synth_data_scene_indoor.blend --background --python render_indoor_data.py -- --num_frames 1000
"""

import bpy
import os
import sys
import json
import math
import random
import numpy as np
from mathutils import Vector, Matrix, Euler, Quaternion

# ─────────────────────────── CLI args ───────────────────────────
argv = sys.argv
if "--" in argv:
    argv = argv[argv.index("--") + 1:]
else:
    argv = []

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--num_frames", type=int, default=1000)
parser.add_argument("--output_dir", type=str,
                    default="C:/Users/User/Documents/GitHub/FoundationPose/data/pallet/test_indoor_v1")
parser.add_argument("--samples", type=int, default=64)
args = parser.parse_args(argv)

NUM_FRAMES = args.num_frames
OUTPUT_DIR = args.output_dir
OVERLAY_DIR = os.path.join(OUTPUT_DIR, "overlay")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(OVERLAY_DIR, exist_ok=True)

# ─────────────────────────── Constants ───────────────────────────
FX = FY = 615.111
CX, CY = 320.0, 240.0
IMG_W, IMG_H = 640, 480
SENSOR_WIDTH = 36.0

# Pallet canonical bbox (Y=UP in NDDS convention)
CANONICAL_BBOX_MIN = np.array([0.0, 0.0, 0.0])
CANONICAL_BBOX_MAX = np.array([1.1, 0.15, 1.1])
ORIENTATION_OVERRIDE = [90, 0, 90]  # Pallet_0

# 8 cuboid corners
def get_canonical_corners():
    mn, mx = CANONICAL_BBOX_MIN, CANONICAL_BBOX_MAX
    return np.array([
        [mn[0], mn[1], mn[2]], [mx[0], mn[1], mn[2]],
        [mx[0], mx[1], mn[2]], [mn[0], mx[1], mn[2]],
        [mn[0], mn[1], mx[2]], [mx[0], mn[1], mx[2]],
        [mx[0], mx[1], mx[2]], [mn[0], mx[1], mx[2]],
    ])

CUBOID_EDGES = [
    [0,1],[1,2],[2,3],[3,0],
    [4,5],[5,6],[6,7],[7,4],
    [0,4],[1,5],[2,6],[3,7],
]
CORNER_COLORS = [
    (255,0,0),(255,128,0),(255,255,0),(0,255,0),
    (0,0,255),(0,128,255),(128,0,255),(255,0,255),
]

# ─────────────────────────── Randomization configs ───────────────────────────

PALLET_COLORS = [
    {"name": "black",      "color": (0.02, 0.02, 0.02), "roughness": 0.72, "weight": 0.35},
    {"name": "charcoal",   "color": (0.05, 0.05, 0.06), "roughness": 0.68, "weight": 0.25},
    {"name": "dark_gray",  "color": (0.08, 0.08, 0.09), "roughness": 0.65, "weight": 0.20},
    {"name": "dark_green", "color": (0.02, 0.06, 0.03), "roughness": 0.60, "weight": 0.10},
    {"name": "dark_blue",  "color": (0.02, 0.03, 0.08), "roughness": 0.62, "weight": 0.10},
]

FLOOR_COLORS = [
    {"name": "light_gray_tile",  "color": (0.38, 0.37, 0.35), "roughness": 0.80, "weight": 0.25},
    {"name": "warm_beige",       "color": (0.42, 0.38, 0.32), "roughness": 0.78, "weight": 0.15},
    {"name": "dark_concrete",    "color": (0.18, 0.17, 0.16), "roughness": 0.85, "weight": 0.15},
    {"name": "medium_gray",      "color": (0.28, 0.27, 0.26), "roughness": 0.82, "weight": 0.15},
    {"name": "epoxy_light",      "color": (0.45, 0.44, 0.40), "roughness": 0.35, "weight": 0.10},
    {"name": "wood_floor",       "color": (0.22, 0.15, 0.08), "roughness": 0.70, "weight": 0.10},
    {"name": "dark_tile",        "color": (0.12, 0.12, 0.11), "roughness": 0.75, "weight": 0.10},
]

WALL_COLORS = [
    {"name": "gray",        "color": (0.35, 0.34, 0.33), "weight": 0.30},
    {"name": "light_gray",  "color": (0.50, 0.49, 0.47), "weight": 0.25},
    {"name": "warm_white",  "color": (0.60, 0.58, 0.54), "weight": 0.20},
    {"name": "blue_gray",   "color": (0.30, 0.33, 0.38), "weight": 0.15},
    {"name": "dark_gray",   "color": (0.20, 0.20, 0.19), "weight": 0.10},
]

CAMERA_MODES = [
    {"name": "oblique",     "dist": (2.0, 4.0), "height": (1.4, 2.5), "weight": 0.30},
    {"name": "high_angle",  "dist": (1.5, 3.5), "height": (2.3, 2.8), "weight": 0.20},
    {"name": "close_low",   "dist": (1.2, 2.2), "height": (1.0, 1.8), "weight": 0.15},
    {"name": "cctv",        "dist": (3.0, 5.0), "height": (2.5, 2.8), "weight": 0.15},
    {"name": "top_down",    "dist": (0.5, 1.5), "height": (2.5, 2.8), "weight": 0.10},
    {"name": "far",         "dist": (4.0, 6.0), "height": (1.5, 2.5), "weight": 0.10},
]

# ─────────────────────────── Helper functions ───────────────────────────

def get_principled(mat):
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def weighted_choice(items):
    weights = [item["weight"] for item in items]
    return random.choices(items, weights=weights, k=1)[0]


def set_material_color(mat_name, color, roughness=None):
    mat = bpy.data.materials.get(mat_name)
    bsdf = get_principled(mat)
    if bsdf:
        r, g, b = color
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        if roughness is not None:
            bsdf.inputs["Roughness"].default_value = roughness


def randomize_pallet_color():
    variant = weighted_choice(PALLET_COLORS)
    set_material_color("PalletVariant_plastic_red_blinn1", variant["color"], variant["roughness"])
    return variant["name"]


def randomize_floor():
    variant = weighted_choice(FLOOR_COLORS)
    set_material_color("IndoorFloor_Mat", variant["color"], variant["roughness"])
    return variant["name"]


def randomize_walls():
    variant = weighted_choice(WALL_COLORS)
    set_material_color("IndoorWall_Mat", variant["color"], 0.85)
    return variant["name"]


def randomize_pallet_yaw(pallet_obj):
    yaw = random.uniform(0, 2 * math.pi)
    pallet_obj.rotation_euler.z = yaw
    return math.degrees(yaw)


def randomize_lighting():
    light1 = bpy.data.objects.get("IndoorLight1")
    light2 = bpy.data.objects.get("IndoorLight2")

    if light1:
        light1.data.energy = random.uniform(200, 800)
        # Random position offset
        light1.location.x = -9.0 + random.uniform(-2, 2)
        light1.location.y = -9.0 + random.uniform(-2, 2)
        # Color temperature variation
        temp = random.choice(["warm", "neutral", "cool"])
        if temp == "warm":
            light1.data.color = (1.0, 0.92, 0.85)
        elif temp == "cool":
            light1.data.color = (0.90, 0.95, 1.0)
        else:
            light1.data.color = (1.0, 0.98, 0.95)

    if light2:
        # 50% chance second light is off (single-source lighting)
        if random.random() < 0.3:
            light2.data.energy = 0
        else:
            light2.data.energy = random.uniform(100, 500)
            light2.location.x = -9.0 + random.uniform(-3, 3)
            light2.location.y = -9.0 + random.uniform(-3, 3)

    # HDRI rotation and strength
    world = bpy.context.scene.world
    if world and world.use_nodes:
        for node in world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                node.inputs["Strength"].default_value = random.uniform(0.1, 0.5)

    return f"L1={light1.data.energy:.0f}" if light1 else ""


def randomize_furniture():
    """Move indoor furniture to random positions near/far from pallet."""
    room_cx, room_cy = -9.0, -9.0

    # Table 1
    t1 = bpy.data.objects.get("IndoorTable1")
    if t1:
        t1.location.x = room_cx + random.uniform(-3.0, 3.0)
        t1.location.y = room_cy + random.uniform(-3.0, 3.0)
        t1.rotation_euler.z = random.uniform(0, math.pi)
        # Move legs with table
        for i in range(2):
            leg = bpy.data.objects.get(f"IndoorTable1_Leg{i}")
            if leg:
                offset = -0.4 + 0.8 * i
                leg.location.x = t1.location.x + offset * math.cos(t1.rotation_euler.z)
                leg.location.y = t1.location.y + offset * math.sin(t1.rotation_euler.z)

    # Stand
    stand = bpy.data.objects.get("IndoorStand")
    if stand:
        stand.location.x = room_cx + random.uniform(-3.0, 3.0)
        stand.location.y = room_cy + random.uniform(-3.0, 3.0)

    # 30% chance: furniture very close to pallet (occlusion)
    if random.random() < 0.3 and t1:
        pallet = bpy.data.objects.get("Pallet_0")
        if pallet:
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(0.6, 1.2)
            t1.location.x = pallet.location.x + dist * math.cos(angle)
            t1.location.y = pallet.location.y + dist * math.sin(angle)


def setup_camera(pallet_center):
    cam = bpy.data.objects.get("ForkliftCam")
    mode = weighted_choice(CAMERA_MODES)

    dist = random.uniform(*mode["dist"])
    height = random.uniform(*mode["height"])
    angle = random.uniform(0, 2 * math.pi)

    cam_x = pallet_center.x + dist * math.cos(angle)
    cam_y = pallet_center.y + dist * math.sin(angle)
    cam_z = height

    # Clamp to room bounds (-13 to -5)
    cam_x = max(-12.5, min(-5.5, cam_x))
    cam_y = max(-12.5, min(-5.5, cam_y))

    cam.location = (cam_x, cam_y, cam_z)

    # Look at pallet with slight offset (edge crop simulation)
    look_offset = Vector((
        random.uniform(-0.3, 0.3),
        random.uniform(-0.3, 0.3),
        0
    ))
    # 20% chance: larger offset for edge-crop
    if random.random() < 0.2:
        look_offset *= 3.0

    look_target = pallet_center + look_offset
    direction = look_target - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    return cam, mode["name"], dist


def get_pallet_world_corners(pallet_obj):
    """Compute 8 cuboid corners in world space using canonical bbox + orientation override."""
    corners_local = get_canonical_corners()  # (8, 3)
    # Center the corners
    center = (CANONICAL_BBOX_MIN + CANONICAL_BBOX_MAX) / 2
    corners_centered = corners_local - center

    # Apply orientation override
    ox, oy, oz = [math.radians(a) for a in ORIENTATION_OVERRIDE]
    R_override = Euler((ox, oy, oz), 'XYZ').to_matrix()

    # Get pallet world transform
    pallet_mat = pallet_obj.matrix_world

    world_corners = []
    for c in corners_centered:
        # Apply override rotation
        v = R_override @ Vector(c)
        # Apply pallet world transform
        v_world = pallet_mat @ Vector((v.x, v.y, v.z))
        world_corners.append(v_world)

    return world_corners


def project_3d_to_2d(point_3d, cam_obj):
    """Project a 3D world point to 2D image coordinates."""
    scene = bpy.context.scene
    cam_mat = cam_obj.matrix_world.normalized().inverted()

    # World to camera space
    p_cam = cam_mat @ Vector((point_3d[0], point_3d[1], point_3d[2], 1.0))

    # Camera to image (pinhole model)
    if p_cam.z >= 0:  # Behind camera
        return None

    x = FX * (-p_cam.x / -p_cam.z) + CX
    y = FY * (-p_cam.y / -p_cam.z) + CY

    return [round(x, 2), round(y, 2)]


def compute_visibility(pallet_center, cam_obj):
    """Simple visibility estimate based on projected corners in frame."""
    corners = get_pallet_world_corners(bpy.data.objects.get("Pallet_0"))
    in_frame = 0
    total = len(corners)
    for c in corners:
        p2d = project_3d_to_2d(c, cam_obj)
        if p2d and 0 <= p2d[0] <= IMG_W and 0 <= p2d[1] <= IMG_H:
            in_frame += 1
    return in_frame / total if total > 0 else 0


def generate_annotation(frame_idx, cam_obj, pallet_obj, pallet_color, floor_color,
                         wall_color, cam_mode, cam_dist, yaw_deg, vis):
    """Generate NDDS-format JSON annotation."""
    # Camera data
    cam_loc = cam_obj.matrix_world.translation

    # Pallet world location
    pallet_loc = pallet_obj.matrix_world.translation

    # Pallet quaternion (world)
    pallet_quat = pallet_obj.matrix_world.to_quaternion()

    # 3D cuboid corners
    corners_3d = get_pallet_world_corners(pallet_obj)

    # Project to 2D
    corners_2d = []
    for c in corners_3d:
        p = project_3d_to_2d(c, cam_obj)
        corners_2d.append(p if p else [-1, -1])

    # Centroid
    centroid_3d = sum(corners_3d, Vector()) / 8
    centroid_2d = project_3d_to_2d(centroid_3d, cam_obj)
    if centroid_2d is None:
        centroid_2d = [-1, -1]

    annotation = {
        "camera_data": {
            "width": IMG_W,
            "height": IMG_H,
            "intrinsics": {"fx": FX, "fy": FY, "cx": CX, "cy": CY},
            "location_worldframe": [round(cam_loc.x, 4), round(cam_loc.y, 4), round(cam_loc.z, 4)],
        },
        "objects": [{
            "class": "pallet",
            "name": "Pallet_0",
            "visibility": round(vis, 3),
            "location": [round(pallet_loc.x, 4), round(pallet_loc.y, 4), round(pallet_loc.z, 4)],
            "quaternion_xyzw": [
                round(pallet_quat.x, 6), round(pallet_quat.y, 6),
                round(pallet_quat.z, 6), round(pallet_quat.w, 6),
            ],
            "projected_cuboid_centroid": centroid_2d,
            "projected_cuboid": corners_2d,
            "cuboid": [[round(c.x, 4), round(c.y, 4), round(c.z, 4)] for c in corners_3d],
        }],
        "metadata": {
            "pallet_color": pallet_color,
            "floor_color": floor_color,
            "wall_color": wall_color,
            "camera_mode": cam_mode,
            "camera_distance": round(cam_dist, 2),
            "pallet_yaw_deg": round(yaw_deg, 1),
        }
    }

    json_path = os.path.join(OUTPUT_DIR, f"{frame_idx:06d}.json")
    with open(json_path, 'w') as f:
        json.dump(annotation, f, indent=2)

    return annotation


def generate_overlay(frame_idx, cam_obj):
    """Generate overlay image with cuboid wireframe."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return  # Skip if PIL not available

    img_path = os.path.join(OUTPUT_DIR, f"{frame_idx:06d}.png")
    if not os.path.exists(img_path):
        return

    img = Image.open(img_path)
    draw = ImageDraw.Draw(img)

    corners_3d = get_pallet_world_corners(bpy.data.objects.get("Pallet_0"))
    corners_2d = []
    for c in corners_3d:
        p = project_3d_to_2d(c, cam_obj)
        corners_2d.append(p if p else None)

    # Draw edges
    for edge in CUBOID_EDGES:
        p1, p2 = corners_2d[edge[0]], corners_2d[edge[1]]
        if p1 and p2:
            draw.line([p1[0], p1[1], p2[0], p2[1]], fill=(255, 255, 0), width=2)

    # Draw corners
    for i, p in enumerate(corners_2d):
        if p:
            r = 4
            color = CORNER_COLORS[i]
            draw.ellipse([p[0]-r, p[1]-r, p[0]+r, p[1]+r], fill=color)

    # Draw centroid
    centroid_3d = sum(corners_3d, Vector()) / 8
    centroid_2d = project_3d_to_2d(centroid_3d, cam_obj)
    if centroid_2d:
        r = 5
        draw.ellipse([centroid_2d[0]-r, centroid_2d[1]-r,
                       centroid_2d[0]+r, centroid_2d[1]+r], fill=(255, 255, 255))

    overlay_path = os.path.join(OVERLAY_DIR, f"overlay_{frame_idx:06d}.png")
    img.save(overlay_path)


# ─────────────────────────── Main rendering loop ───────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Indoor Synthetic Data Generator")
    print(f"  Frames: {NUM_FRAMES}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Samples: {args.samples}")
    print(f"{'='*60}\n")

    # Scene setup
    scene = bpy.context.scene
    scene.render.resolution_x = IMG_W
    scene.render.resolution_y = IMG_H
    scene.render.resolution_percentage = 100
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'
    scene.cycles.samples = args.samples
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'

    cam = bpy.data.objects.get("ForkliftCam")
    cam.data.sensor_width = SENSOR_WIDTH
    cam.data.lens = FX * SENSOR_WIDTH / IMG_W
    scene.camera = cam

    pallet = bpy.data.objects.get("Pallet_0")

    # Get pallet center dynamically
    def get_pallet_center():
        all_corners = []
        for child in pallet.children_recursive:
            if child.type == 'MESH':
                for corner in child.bound_box:
                    all_corners.append(child.matrix_world @ Vector(corner))
        if not all_corners:
            return pallet.location
        center = sum(all_corners, Vector()) / len(all_corners)
        return center

    # Stats
    stats = {"colors": {}, "floors": {}, "modes": {}, "walls": {}}

    for frame_idx in range(NUM_FRAMES):
        # ─── Randomize everything ───
        pallet_color = randomize_pallet_color()
        floor_color = randomize_floor()
        wall_color = randomize_walls()
        yaw_deg = randomize_pallet_yaw(pallet)
        light_info = randomize_lighting()
        randomize_furniture()

        # Update scene to get correct transforms
        bpy.context.view_layer.update()

        pallet_center = get_pallet_center()
        cam, cam_mode, cam_dist = setup_camera(pallet_center)

        # Visibility check
        bpy.context.view_layer.update()
        vis = compute_visibility(pallet_center, cam)

        # Skip if pallet not visible enough
        if vis < 0.3:
            # Re-try with centered camera
            cam.location = (pallet_center.x + random.uniform(-1, 1),
                           pallet_center.y + random.uniform(1, 2),
                           random.uniform(1.5, 2.5))
            direction = pallet_center - cam.location
            cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
            bpy.context.view_layer.update()
            vis = compute_visibility(pallet_center, cam)

        # ─── Render ───
        scene.render.filepath = os.path.join(OUTPUT_DIR, f"{frame_idx:06d}.png")
        bpy.ops.render.render(write_still=True)

        # ─── Annotation ───
        annotation = generate_annotation(
            frame_idx, cam, pallet, pallet_color, floor_color,
            wall_color, cam_mode, cam_dist, yaw_deg, vis
        )

        # ─── Overlay ───
        generate_overlay(frame_idx, cam)

        # ─── Stats ───
        for key, val in [("colors", pallet_color), ("floors", floor_color),
                          ("modes", cam_mode), ("walls", wall_color)]:
            stats[key][val] = stats[key].get(val, 0) + 1

        # ─── Log ───
        if (frame_idx + 1) % 10 == 0 or frame_idx == 0:
            print(f"Frame {frame_idx:04d}/{NUM_FRAMES}: "
                  f"color={pallet_color}, floor={floor_color}, "
                  f"mode={cam_mode}, dist={cam_dist:.1f}m, "
                  f"yaw={yaw_deg:.0f}°, vis={vis:.2f}")

    # ─── Summary ───
    print(f"\n{'='*60}")
    print(f"DONE! {NUM_FRAMES} frames -> {OUTPUT_DIR}")
    print(f"\nPallet colors: {stats['colors']}")
    print(f"Floor colors:  {stats['floors']}")
    print(f"Camera modes:  {stats['modes']}")
    print(f"Wall colors:   {stats['walls']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
