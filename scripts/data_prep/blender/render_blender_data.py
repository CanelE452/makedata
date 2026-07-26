"""Blender 합성 데이터 렌더링 메인 스크립트.

사용법:
    # Blender GUI에서 실행 (MCP execute_blender_code)
    # 또는 커맨드라인:
    blender synth_data_scene.blend --background --python render_blender_data.py
"""

import json
import os
import sys

import bpy
import numpy as np

# 이 파일의 디렉토리를 sys.path에 추가 (모듈 import 용)
_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

from blender_config import (
    NUM_FRAMES, IMAGE_WIDTH, IMAGE_HEIGHT, K,
    OUTPUT_DIR, OVERLAY_DIR, SAVE_OVERLAY,
    ORIENTATION_OVERRIDES, CUBOID_EDGES, CORNER_COLORS_RGB, PALLET_NAMES,
    PALLET_SOURCE_ASSETS, VISIBLE_MIN_FRACTION,
    OCCLUSION_HEAVY_RAY_RANGE, OCCLUSION_LIGHT_RAY_RANGE,
    MIN_PROJECTED_AREA_RATIO, FAR_VIEW_MIN_PROJECTED_AREA_RATIO,
    CAMERA_DISTANCE_BUCKETS, CAMERA_VIEW_MODES,
    MAX_FRAME_RETRIES, THREE_BOX_PROBABILITY, EMPTY_PALLET_PROBABILITY,
    HEAVY_OCCLUSION_PROBABILITY, ULTRA_FAR_HEAVY_OCCLUSION_PROBABILITY,
)
from blender_math import (
    euler_to_rotation_matrix, rotation_matrix_to_quat_xyzw,
    rotation_matrix_to_euler_deg, build_view_matrix,
)
from pallet_geometry import (
    get_local_bbox as _get_local_bbox,
    get_pallet_geometry,
    is_ground_contact_ok,
    object_bottom_z_world,
)
from randomizers import (
    get_obj, setup_render,
    randomize_pallet, randomize_camera, randomize_distractors,
    randomize_boxes, randomize_hdri, mesh_overlap, randomize_background,
    choose_next_pallet_index,
    check_raycast_visibility,
    choose_camera_mode_name, randomize_pallet_appearance,
)
from blender_config import DISTRACTOR_NAMES, BOX_NAMES


def _get_pallet_local_bbox(pallet_obj):
    return _get_local_bbox(pallet_obj)


def compute_annotation(pallet_name, pallet_obj, cam_pos, look_at):
    """Compute NDDS annotation from canonical cuboid geometry."""
    import bpy
    bpy.context.view_layer.update()

    pallet_geom = get_pallet_geometry(
        pallet_name,
        pallet_obj,
        ORIENTATION_OVERRIDES,
    )
    if pallet_geom is None:
        return {}, np.zeros((9, 2)), 0.0, (0, 0, 0), 0.0, None

    corners_world = pallet_geom["corners_world"]
    centroid_world = pallet_geom["centroid_world"]
    points_3d = np.vstack([corners_world, centroid_world[np.newaxis, :]])

    # Project to camera
    R_w2c, t_w2c = build_view_matrix(cam_pos, look_at, up=(0, 0, 1))
    pts_cam = (R_w2c @ points_3d.T).T + t_w2c
    projected = (K @ pts_cam.T).T
    uv = projected[:, :2] / projected[:, 2:3]

    in_frame = ((uv[:, 0] >= 0) & (uv[:, 0] < IMAGE_WIDTH) &
                (uv[:, 1] >= 0) & (uv[:, 1] < IMAGE_HEIGHT))
    visibility = float(in_frame.sum()) / 9.0

    # Projected cuboid area as fraction of image (detect too-small pallets)
    corners_uv = uv[:8]
    clipped = np.clip(corners_uv, [0, 0], [IMAGE_WIDTH, IMAGE_HEIGHT])
    u_span = clipped[:, 0].max() - clipped[:, 0].min()
    v_span = clipped[:, 1].max() - clipped[:, 1].min()
    area_ratio = (u_span * v_span) / (IMAGE_WIDTH * IMAGE_HEIGHT)

    # Pose: object frame relative to camera
    t_obj_cam = R_w2c @ centroid_world + t_w2c
    R_obj_cam = R_w2c @ pallet_geom["r_for_pose"]

    quat_xyzw = rotation_matrix_to_quat_xyzw(R_obj_cam)
    pitch, yaw, roll = rotation_matrix_to_euler_deg(R_obj_cam)

    pose_4x4 = np.eye(4)
    pose_4x4[:3, :3] = R_obj_cam
    pose_4x4[:3, 3] = t_obj_cam

    width_m = float(np.linalg.norm(corners_world[1] - corners_world[0]))
    height_m = float(np.linalg.norm(corners_world[3] - corners_world[0]))
    depth_m = float(np.linalg.norm(corners_world[4] - corners_world[0]))

    data = {
        "camera_data": {
            "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT,
            "intrinsics": {"fx": float(K[0, 0]), "fy": float(K[1, 1]),
                           "cx": float(K[0, 2]), "cy": float(K[1, 2])},
            "location_worldframe": [float(v) for v in cam_pos],
        },
        "objects": [{
            "class": "pallet", "name": pallet_name,
            "source_asset": PALLET_SOURCE_ASSETS.get(pallet_name, pallet_name),
            "visibility": visibility,
            "location": [float(v) for v in t_obj_cam],
            "quaternion_xyzw": quat_xyzw,
            "euler_angles": {"pitch": pitch, "yaw": yaw, "roll": roll},
            "pose_transform": pose_4x4.tolist(),
            "projected_cuboid_centroid": [float(uv[8, 0]), float(uv[8, 1])],
            "projected_cuboid": [[float(uv[k, 0]), float(uv[k, 1])] for k in range(8)],
            "cuboid": [[float(points_3d[k, j]) for j in range(3)] for k in range(8)],
            "dimensions_m": {"width": width_m, "height": height_m, "depth": depth_m},
            "dimensions_mm": {
                "width": round(width_m * 1000.0, 1),
                "height": round(height_m * 1000.0, 1),
                "depth": round(depth_m * 1000.0, 1),
            },
        }],
    }
    return data, uv, visibility, (pitch, yaw, roll), area_ratio, pallet_geom


def _get_pallet_ray_targets(pallet_geom, n_grid=5):
    """Sample points on the pallet surface for ray casting visibility check."""
    if pallet_geom is None:
        return []

    points = []
    top_face = pallet_geom["top_face_world"]
    origin = top_face[0]
    width_vec = top_face[1] - top_face[0]
    depth_vec = top_face[2] - top_face[0]
    for i in range(n_grid):
        for j in range(n_grid):
            u = (i + 0.5) / n_grid
            v = (j + 0.5) / n_grid
            world_pt = origin + width_vec * u + depth_vec * v
            points.append(tuple(world_pt))
    return points


def _annotation_quality_report(annotation):
    """Validate canonical cuboid geometry before saving a frame."""
    obj = annotation["objects"][0]
    cuboid = np.array(obj["cuboid"], dtype=np.float64)
    rotation = np.array(obj["pose_transform"], dtype=np.float64)[:3, :3]
    errors = []

    e01 = np.linalg.norm(cuboid[1] - cuboid[0])
    e03 = np.linalg.norm(cuboid[3] - cuboid[0])
    e04 = np.linalg.norm(cuboid[4] - cuboid[0])

    if e03 >= e01:
        errors.append(f"height>=width ({e03:.3f}>={e01:.3f})")
    if e03 >= e04:
        errors.append(f"height>=depth ({e03:.3f}>={e04:.3f})")

    basis = {
        "01-03": (cuboid[1] - cuboid[0], cuboid[3] - cuboid[0]),
        "01-04": (cuboid[1] - cuboid[0], cuboid[4] - cuboid[0]),
        "03-04": (cuboid[3] - cuboid[0], cuboid[4] - cuboid[0]),
    }
    for name, (va, vb) in basis.items():
        cos_theta = np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-12)
        angle = np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0)))
        if abs(angle - 90.0) > 5.0:
            errors.append(f"{name} angle={angle:.1f}")

    det_r = np.linalg.det(rotation)
    if abs(det_r - 1.0) > 0.05:
        errors.append(f"det(R)={det_r:.3f}")
    orth_err = np.max(np.abs(rotation @ rotation.T - np.eye(3)))
    if orth_err > 0.05:
        errors.append(f"orth_err={orth_err:.3f}")

    top_z = cuboid[[0, 1, 4, 5], 2]
    bottom_z = cuboid[[2, 3, 6, 7], 2]
    if top_z.mean() <= bottom_z.mean():
        errors.append("top face is not above bottom face")
    if np.max(np.abs(top_z - top_z.mean())) > 0.03:
        errors.append("top face is not horizontal")
    if np.max(np.abs(bottom_z - bottom_z.mean())) > 0.03:
        errors.append("bottom face is not horizontal")

    return len(errors) == 0, errors


def _collect_overlap_list(pallet_obj):
    overlap_list = []
    for dname in DISTRACTOR_NAMES:
        dobj = get_obj(dname)
        if dobj and not dobj.hide_render and mesh_overlap(pallet_obj, dobj):
            overlap_list.append(dname)
    for bname in BOX_NAMES:
        bobj = get_obj(bname)
        if not bobj or bobj.hide_render:
            continue
        for dname in DISTRACTOR_NAMES:
            dobj = get_obj(dname)
            if dobj and not dobj.hide_render and mesh_overlap(bobj, dobj):
                overlap_list.append(f"{bname}<>{dname}")
    return sorted(set(overlap_list))


def _ground_contact_report(pallet_obj, pallet_geom):
    details = []
    ok = True

    if abs(pallet_geom["bottom_z_world"]) > 0.02:
        ok = False
        details.append(f"pallet bottom z={pallet_geom['bottom_z_world']:.3f}")

    for dname in DISTRACTOR_NAMES:
        dobj = get_obj(dname)
        if dobj and not dobj.hide_render and not is_ground_contact_ok(dobj, target_z=0.0):
            ok = False
            details.append(f"{dname} ground z={object_bottom_z_world(dobj):.3f}")

    pallet_top_z = pallet_geom["top_z_world"]
    for bname in BOX_NAMES:
        bobj = get_obj(bname)
        if bobj and not bobj.hide_render and object_bottom_z_world(bobj) < pallet_top_z - 0.02:
            ok = False
            details.append(f"{bname} below top plane")

    return ok, details


def _project_axis(centroid_world, R_obj_world, cam_pos, look_at, axis_len=0.3):
    """Project 3D pose axes (X=R, Y=G, Z=B) to 2D for overlay."""
    R_w2c, t_w2c = build_view_matrix(cam_pos, look_at, up=(0, 0, 1))
    origin_cam = R_w2c @ centroid_world + t_w2c
    origin_uv = (K @ origin_cam) / origin_cam[2]

    axes_uv = []
    for col in range(3):
        axis_world = centroid_world + R_obj_world[:, col] * axis_len
        axis_cam = R_w2c @ axis_world + t_w2c
        if axis_cam[2] > 0:
            uv = (K @ axis_cam) / axis_cam[2]
            axes_uv.append((uv[0], uv[1]))
        else:
            axes_uv.append(None)
    return (origin_uv[0], origin_uv[1]), axes_uv


def _edge_len_3d(points_3d, i, j):
    """3D distance between two cuboid corners."""
    return float(np.linalg.norm(points_3d[i] - points_3d[j]))


def _mid_2d(uv, i, j):
    """Midpoint of two projected points."""
    return (int((uv[i, 0] + uv[j, 0]) / 2), int((uv[i, 1] + uv[j, 1]) / 2))


def _classify_distance_bucket(distance_m):
    for bucket_name, (d_min, d_max) in CAMERA_DISTANCE_BUCKETS.items():
        if d_min <= distance_m < d_max:
            return bucket_name
    max_bucket = max(CAMERA_DISTANCE_BUCKETS.items(), key=lambda item: item[1][1])[0]
    return max_bucket if distance_m >= CAMERA_DISTANCE_BUCKETS[max_bucket][0] else "close"


def draw_overlay(render_path, overlay_path, uv, visibility, rot_info,
                 ray_vis=None, pallet_name=None, cam_pos=None,
                 centroid_world=None, R_obj_world=None, look_at=None,
                 area_ratio=None, distance=None, points_3d=None,
                 frame_idx=None, quat=None):
    """Draw rich overlay: cuboid, axes, edge lengths, face fills, stats panel."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("[WARN] PIL not available, skipping overlay")
        return

    img = Image.open(render_path).convert("RGBA")
    # Transparent layer for face fills
    face_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    face_draw = ImageDraw.Draw(face_layer)

    # --- Semi-transparent face fills per keypoint_definition.md ---
    # Top={0,1,4,5}, Bottom={2,3,6,7}, Front={0,1,2,3}, Back={4,5,6,7}
    def _poly(indices, color_rgba):
        pts = [(int(uv[i, 0]), int(uv[i, 1])) for i in indices]
        if all(0 <= p[0] < IMAGE_WIDTH and 0 <= p[1] < IMAGE_HEIGHT for p in pts):
            face_draw.polygon(pts, fill=color_rgba)

    _poly([0, 1, 5, 4], (0, 255, 200, 40))    # top face (적재면)
    _poly([0, 1, 2, 3], (0, 255, 0, 30))       # front face
    _poly([1, 2, 6, 5], (200, 200, 0, 25))     # right face

    img = Image.alpha_composite(img, face_layer)
    draw = ImageDraw.Draw(img)

    # --- Cuboid wireframe per keypoint_definition.md ---
    # Top={0,1,4,5}, Bottom={2,3,6,7}
    top_edges = [(0, 1), (1, 5), (5, 4), (4, 0)]    # top face (적재면)
    bot_edges = [(2, 3), (3, 7), (7, 6), (6, 2)]    # bottom face (바닥)
    vert_edges = [(0, 3), (1, 2), (4, 7), (5, 6)]   # height edges (top↔bottom)

    for i, j in top_edges:
        x0, y0 = int(uv[i, 0]), int(uv[i, 1])
        x1, y1 = int(uv[j, 0]), int(uv[j, 1])
        draw.line([(x0, y0), (x1, y1)], fill=(0, 255, 0, 255), width=2)
    for i, j in bot_edges:
        x0, y0 = int(uv[i, 0]), int(uv[i, 1])
        x1, y1 = int(uv[j, 0]), int(uv[j, 1])
        draw.line([(x0, y0), (x1, y1)], fill=(0, 180, 0, 255), width=2)
    for i, j in vert_edges:
        x0, y0 = int(uv[i, 0]), int(uv[i, 1])
        x1, y1 = int(uv[j, 0]), int(uv[j, 1])
        draw.line([(x0, y0), (x1, y1)], fill=(200, 200, 0, 200), width=1)

    # --- Edge length labels (mm) on selected edges ---
    if points_3d is not None:
        label_edges = [(0, 1, "W"), (0, 3, "H"), (0, 4, "D")]
        for i, j, name in label_edges:
            length_m = _edge_len_3d(points_3d, i, j)
            mx, my = _mid_2d(uv, i, j)
            if 0 <= mx < IMAGE_WIDTH and 0 <= my < IMAGE_HEIGHT:
                label = f"{name}:{length_m * 1000:.0f}mm"
                draw.text((mx + 4, my - 6), label, fill=(255, 200, 0, 255))

    # --- Corner keypoints with color coding ---
    for i in range(8):
        cx, cy = int(uv[i, 0]), int(uv[i, 1])
        if 0 <= cx < IMAGE_WIDTH and 0 <= cy < IMAGE_HEIGHT:
            r = 6
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=CORNER_COLORS_RGB[i] + (255,), outline=(0, 0, 0, 255))
            draw.text((cx + 9, cy - 9), str(i), fill=(255, 255, 255, 255))

    # --- Centroid with crosshair ---
    cent_x, cent_y = int(uv[8, 0]), int(uv[8, 1])
    if 0 <= cent_x < IMAGE_WIDTH and 0 <= cent_y < IMAGE_HEIGHT:
        r = 8
        draw.ellipse([cent_x - r, cent_y - r, cent_x + r, cent_y + r],
                     fill=(255, 255, 255, 200), outline=(0, 0, 0, 255))
        # Crosshair
        cr = 14
        draw.line([(cent_x - cr, cent_y), (cent_x + cr, cent_y)], fill=(255, 255, 255, 150), width=1)
        draw.line([(cent_x, cent_y - cr), (cent_x, cent_y + cr)], fill=(255, 255, 255, 150), width=1)
        draw.text((cent_x + 12, cent_y - 10), "C", fill=(255, 255, 255, 255))

    # --- 3D Pose Axes (X=Red, Y=Green, Z=Blue) with arrowheads ---
    if centroid_world is not None and R_obj_world is not None and cam_pos is not None and look_at is not None:
        origin_2d, axes_2d = _project_axis(centroid_world, R_obj_world, cam_pos, look_at, axis_len=0.3)
        ox, oy = int(origin_2d[0]), int(origin_2d[1])
        axis_colors = [(255, 50, 50, 255), (50, 255, 50, 255), (80, 80, 255, 255)]
        axis_labels = ["X", "Y", "Z"]
        for k, (color, label) in enumerate(zip(axis_colors, axis_labels)):
            if axes_2d[k] is not None:
                ax, ay = int(axes_2d[k][0]), int(axes_2d[k][1])
                draw.line([(ox, oy), (ax, ay)], fill=color, width=3)
                # Arrowhead circle
                draw.ellipse([ax - 4, ay - 4, ax + 4, ay + 4], fill=color)
                if 0 <= ax < IMAGE_WIDTH and 0 <= ay < IMAGE_HEIGHT:
                    draw.text((ax + 6, ay - 6), label, fill=color)

    # --- Info panel (top-left, semi-transparent background) ---
    pitch, yaw, roll = rot_info
    panel_lines = []
    if frame_idx is not None:
        panel_lines.append(f"Frame: {frame_idx:06d}")
    if pallet_name:
        panel_lines.append(f"Object: {pallet_name}")
    if distance is not None:
        panel_lines.append(f"Distance: {distance:.2f}m")
    panel_lines.append(f"Kpt Vis: {visibility:.0%}")
    if ray_vis is not None:
        panel_lines.append(f"Ray Vis: {ray_vis:.0%}")
    if area_ratio is not None:
        panel_lines.append(f"Area: {area_ratio:.1%}")
    panel_lines.append(f"Pitch: {pitch:.1f}")
    panel_lines.append(f"Yaw: {yaw:.1f}")
    panel_lines.append(f"Roll: {roll:.1f}")
    if quat is not None:
        panel_lines.append(f"Q: [{quat[0]:.2f},{quat[1]:.2f},")
        panel_lines.append(f"    {quat[2]:.2f},{quat[3]:.2f}]")
    if points_3d is not None:
        w = _edge_len_3d(points_3d, 0, 1) * 1000
        h = _edge_len_3d(points_3d, 0, 3) * 1000
        d = _edge_len_3d(points_3d, 0, 4) * 1000
        panel_lines.append(f"Size: {w:.0f}x{h:.0f}x{d:.0f}mm")
    if cam_pos is not None:
        panel_lines.append(f"Cam: ({cam_pos[0]:.1f},{cam_pos[1]:.1f},{cam_pos[2]:.1f})")

    # Draw panel background
    line_h = 14
    panel_w = 160
    panel_h = len(panel_lines) * line_h + 8
    panel_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(panel_bg)
    bg_draw.rectangle([(3, 3), (3 + panel_w, 3 + panel_h)], fill=(0, 0, 0, 180))
    img = Image.alpha_composite(img, panel_bg)
    draw = ImageDraw.Draw(img)

    y_pos = 7
    for line in panel_lines:
        draw.text((7, y_pos), line, fill=(0, 255, 255, 255))
        y_pos += line_h

    # --- Bottom-right: axis legend ---
    legend_x = IMAGE_WIDTH - 75
    legend_y = IMAGE_HEIGHT - 50
    legend_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lg_draw = ImageDraw.Draw(legend_bg)
    lg_draw.rectangle([(legend_x - 4, legend_y - 4),
                       (IMAGE_WIDTH - 4, IMAGE_HEIGHT - 4)], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, legend_bg)
    draw = ImageDraw.Draw(img)
    for k, (label, color) in enumerate([("X axis", (255, 80, 80)),
                                         ("Y axis", (80, 255, 80)),
                                         ("Z axis", (100, 100, 255))]):
        draw.rectangle([(legend_x, legend_y + k * 14),
                        (legend_x + 10, legend_y + k * 14 + 10)], fill=color)
        draw.text((legend_x + 14, legend_y + k * 14 - 1), label, fill=(220, 220, 220))

    img.convert("RGB").save(overlay_path)


def _detect_completed_frames(output_dir):
    png_indices = {
        int(os.path.splitext(name)[0])
        for name in os.listdir(output_dir)
        if name.endswith(".png") and os.path.splitext(name)[0].isdigit()
    }
    json_indices = {
        int(os.path.splitext(name)[0])
        for name in os.listdir(output_dir)
        if name.endswith(".json") and os.path.splitext(name)[0].isdigit()
    }
    next_idx = 0
    for idx in sorted(png_indices & json_indices):
        if idx != next_idx:
            break
        next_idx += 1
    return next_idx


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if SAVE_OVERLAY and OVERLAY_DIR is not None:
        os.makedirs(OVERLAY_DIR, exist_ok=True)

    setup_render()
    scene = bpy.context.scene

    print(f"[render] Rendering {NUM_FRAMES} frames to {OUTPUT_DIR}")
    saved_frames = _detect_completed_frames(OUTPUT_DIR)
    total_attempts = 0
    remaining_frames = max(0, NUM_FRAMES - saved_frames)
    max_total_attempts = max(remaining_frames * MAX_FRAME_RETRIES * 3, remaining_frames + 100)

    if saved_frames > 0:
        print(f"[render] Resuming from frame {saved_frames:06d}")

    while saved_frames < NUM_FRAMES and total_attempts < max_total_attempts:
        frame_idx = saved_frames
        total_attempts += 1
        print(f"\n--- Frame {frame_idx:06d} (attempt {total_attempts}) ---")

        vis_pre = 0.0
        pallet_name = pallet_pos = cam_pos = look_at = None
        pallet_geom = None
        annotation = {}
        ray_vis = 0.0
        area_pre = 0.0
        overlap_list = []
        background_key = None
        occlusion_target = "light"
        ground_contact_ok = False
        annotation_ok = False
        quality_errors = []
        retry_count = 0
        frame_accepted = False
        ray_vis_range = OCCLUSION_LIGHT_RAY_RANGE
        target_pallet_idx = choose_next_pallet_index()
        box_count = 0
        camera_mode_name = choose_camera_mode_name()
        camera_mode_cfg = CAMERA_VIEW_MODES.get(camera_mode_name, {})
        if np.random.rand() < EMPTY_PALLET_PROBABILITY:
            target_box_count = 0
        elif camera_mode_name == "ultra_far":
            target_box_count = 2
        else:
            target_box_count = 3 if np.random.rand() < THREE_BOX_PROBABILITY else 2
        min_area_ratio = camera_mode_cfg.get("min_area_ratio", MIN_PROJECTED_AREA_RATIO)
        distance_bucket = None
        pallet_appearance = None
        heavy_occlusion_prob = (
            ULTRA_FAR_HEAVY_OCCLUSION_PROBABILITY
            if camera_mode_name == "ultra_far"
            else HEAVY_OCCLUSION_PROBABILITY
        )

        for retry in range(MAX_FRAME_RETRIES):
            retry_count = retry + 1
            occlusion_target = "heavy" if np.random.rand() < heavy_occlusion_prob else "light"
            ray_vis_range = (
                OCCLUSION_HEAVY_RAY_RANGE
                if occlusion_target == "heavy"
                else OCCLUSION_LIGHT_RAY_RANGE
            )
            if target_box_count >= 3:
                ray_vis_range = (max(0.35, ray_vis_range[0] - 0.10), ray_vis_range[1])
            if camera_mode_name == "ultra_far":
                ray_vis_range = (max(0.30, ray_vis_range[0] - 0.05), ray_vis_range[1])
            background_key = randomize_background()
            pallet_name, _ = randomize_pallet(chosen_idx=target_pallet_idx)
            if pallet_name is None:
                print("  [SKIP] No valid pallet with mesh")
                break
            pallet_obj = get_obj(pallet_name)
            pallet_geom = get_pallet_geometry(
                pallet_name,
                pallet_obj,
                ORIENTATION_OVERRIDES,
            )
            if pallet_geom is None:
                continue
            pallet_pos = tuple(pallet_geom["centroid_world"])
            pallet_appearance = randomize_pallet_appearance(pallet_obj, pallet_name)

            cam_pos, look_at = randomize_camera(
                pallet_pos,
                pallet_geom=pallet_geom,
                camera_mode_name=camera_mode_name,
            )
            if cam_pos is None:
                break

            box_count = randomize_boxes(
                pallet_obj,
                pallet_name,
                occlusion_target=occlusion_target,
                target_box_count=target_box_count,
            )
            boxes_ok = box_count == target_box_count
            randomize_distractors(
                pallet_pos,
                cam_pos,
                prefer_occlusion=(occlusion_target == "heavy"),
            )
            randomize_hdri()
            bpy.context.view_layer.update()

            annotation, _, vis_pre, _, area_pre, pallet_geom = compute_annotation(
                pallet_name,
                pallet_obj,
                cam_pos,
                look_at,
            )
            if not annotation:
                continue
            ray_vis = check_raycast_visibility(pallet_obj, cam_pos,
                                                _get_pallet_ray_targets(pallet_geom))
            overlap_list = _collect_overlap_list(pallet_obj)
            ground_contact_ok, ground_errors = _ground_contact_report(pallet_obj, pallet_geom)
            annotation_ok, annotation_errors = _annotation_quality_report(annotation)
            quality_errors = ground_errors + annotation_errors
            boxes_close_enough = (
                box_count == 0 if target_box_count == 0
                else box_count >= max(target_box_count - 1, 2)
            )
            if (
                vis_pre >= VISIBLE_MIN_FRACTION
                and area_pre >= min_area_ratio
                and ray_vis >= ray_vis_range[0]
                and ray_vis <= ray_vis_range[1]
                and boxes_close_enough
                and ground_contact_ok
                and annotation_ok
                and not overlap_list
            ):
                frame_accepted = True
                break
            print(
                f"  [RETRY {retry + 1}] vis={vis_pre:.2f}, area={area_pre:.3f}, "
                f"ray={ray_vis:.2f}, boxes={box_count}/{target_box_count}, mode={camera_mode_name}, target={occlusion_target}, bg={background_key}, "
                f"overlap={len(overlap_list)}, quality={'; '.join(quality_errors[:2])}"
            )

        if not frame_accepted:
            print("  [SKIP] No valid frame after retries")
            continue

        overlap_str = "NONE" if not overlap_list else ", ".join(overlap_list)
        print(f"  {pallet_name} at ({pallet_pos[0]:.1f}, {pallet_pos[1]:.1f}), vis={vis_pre:.2f}, area={area_pre:.3f}, ray={ray_vis:.2f}, overlap={overlap_str}")

        render_path = os.path.join(OUTPUT_DIR, f"{frame_idx:06d}.png")
        scene.render.filepath = render_path
        bpy.ops.render.render(write_still=True)

        annotation, uv, visibility, rot_info, area_final, pallet_geom = compute_annotation(
            pallet_name, pallet_obj, cam_pos, look_at)
        annotation["objects"][0]["ray_visibility"] = round(ray_vis, 4)
        annotation["objects"][0]["area_ratio"] = round(area_final, 4)
        annotation["objects"][0]["overlap"] = overlap_list
        annotation["objects"][0]["occlusion_target"] = occlusion_target
        annotation["objects"][0]["ground_contact_ok"] = ground_contact_ok
        annotation["objects"][0]["annotation_ok"] = annotation_ok
        annotation["objects"][0]["retry_count"] = retry_count
        annotation["objects"][0]["box_count"] = box_count
        annotation["objects"][0]["target_box_count"] = target_box_count
        annotation["objects"][0]["quality_errors"] = quality_errors
        annotation["camera_data"]["background_asset"] = background_key
        annotation["camera_data"]["visible_min_fraction"] = VISIBLE_MIN_FRACTION
        annotation["camera_data"]["min_area_ratio"] = min_area_ratio

        # Compute distance and world rotation for overlay
        cam_arr = np.array(cam_pos)
        dist = float(np.linalg.norm(cam_arr - pallet_geom["centroid_world"]))
        distance_bucket = _classify_distance_bucket(dist)
        annotation["objects"][0]["camera_distance"] = round(dist, 3)
        annotation["objects"][0]["distance_bucket"] = distance_bucket
        annotation["objects"][0]["camera_mode"] = camera_mode_name
        if pallet_appearance is not None:
            annotation["objects"][0]["pallet_color_variant"] = pallet_appearance["name"]
            annotation["objects"][0]["pallet_color_family"] = pallet_appearance["family"]
            annotation["objects"][0]["pallet_color_rgb"] = pallet_appearance["base_color"]
            annotation["objects"][0]["pallet_material_slots"] = pallet_appearance["slots_updated"]
            annotation["objects"][0]["pallet_roughness"] = pallet_appearance["roughness"]
            annotation["objects"][0]["pallet_specular"] = pallet_appearance["specular"]
        annotation["camera_data"]["camera_mode"] = camera_mode_name

        # Get centroid and rotation for axis drawing
        centroid_w = pallet_geom["centroid_world"]
        R_obj_w = pallet_geom["r_for_pose"]

        json_path = os.path.join(OUTPUT_DIR, f"{frame_idx:06d}.json")
        with open(json_path, "w") as f:
            json.dump(annotation, f, indent=2)

        # Extract 3D points and quaternion for overlay
        pts_3d = None
        quat_xyzw = annotation["objects"][0].get("quaternion_xyzw")
        cuboid_data = annotation["objects"][0].get("cuboid")
        if cuboid_data:
            pts_3d = np.array(cuboid_data)

        if SAVE_OVERLAY and OVERLAY_DIR is not None:
            overlay_path = os.path.join(OVERLAY_DIR, f"overlay_{frame_idx:06d}.png")
            draw_overlay(render_path, overlay_path, uv, visibility, rot_info,
                         ray_vis=ray_vis, pallet_name=pallet_name,
                         cam_pos=cam_pos, centroid_world=centroid_w,
                         R_obj_world=R_obj_w, look_at=look_at,
                         area_ratio=area_final, distance=dist,
                         points_3d=pts_3d, frame_idx=frame_idx,
                         quat=quat_xyzw)

        print(f"  Rendered (vis={visibility:.2f}, ray={ray_vis:.2f}, dist={dist:.1f}m)")
        saved_frames += 1

    if saved_frames < NUM_FRAMES:
        print(f"\n[render] WARNING: saved {saved_frames}/{NUM_FRAMES} frames after {total_attempts} attempts")
    else:
        print(f"\n[render] Done! {saved_frames} frames -> {OUTPUT_DIR} ({total_attempts} attempts)")


if __name__ == "__main__":
    main()
