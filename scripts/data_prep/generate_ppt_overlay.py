"""PPT용 overlay 이미지 생성 — visualize_annotations.py 스타일 100% 재현 + 업스케일.

v70 overlay와 동일: 녹색 cuboid edges, 컬러 번호 keypoints, RGB 축 라벨,
yaw/pitch/roll + visibility 텍스트, 흰색 centroid.
"""

import argparse
import json
import os

import cv2
import numpy as np


CUBOID_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]

CORNER_COLORS = [
    (0, 0, 255),    # 0: red
    (0, 128, 255),  # 1: orange
    (0, 255, 255),  # 2: yellow
    (0, 255, 0),    # 3: green
    (255, 0, 0),    # 4: blue
    (255, 128, 0),  # 5: teal
    (255, 0, 128),  # 6: purple
    (255, 0, 255),  # 7: magenta
]
CENTROID_COLOR = (255, 255, 255)
EDGE_COLOR = (0, 255, 0)


def draw_cuboid(img, pts_2d, centroid_2d, s=1.0):
    """8 cuboid corners + edges + centroid — visualize_annotations.py 동일."""
    h, w = img.shape[:2]
    line_w = max(1, round(2 * s))
    dot_r = max(4, round(6 * s))
    center_r = max(5, round(8 * s))
    font_scale = 0.45 * s
    font_thick = max(1, round(1 * s))

    for i, j in CUBOID_EDGES:
        p1 = tuple(pts_2d[i])
        p2 = tuple(pts_2d[j])
        if all(0 <= p1[k] < [w, h][k] for k in range(2)) or \
           all(0 <= p2[k] < [w, h][k] for k in range(2)):
            cv2.line(img, p1, p2, EDGE_COLOR, line_w, cv2.LINE_AA)

    for i, pt in enumerate(pts_2d):
        if 0 <= pt[0] < w and 0 <= pt[1] < h:
            cv2.circle(img, tuple(pt), dot_r, CORNER_COLORS[i], -1, cv2.LINE_AA)
            cv2.circle(img, tuple(pt), dot_r, (0, 0, 0), max(1, round(s)), cv2.LINE_AA)
            cv2.putText(img, str(i),
                        (pt[0] + round(8 * s), pt[1] - round(4 * s)),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                        (255, 255, 255), font_thick, cv2.LINE_AA)

    cx, cy = centroid_2d
    if 0 <= cx < w and 0 <= cy < h:
        cv2.circle(img, (cx, cy), center_r, CENTROID_COLOR, -1, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), center_r, (0, 0, 0), max(1, round(1.5 * s)), cv2.LINE_AA)
        cv2.putText(img, "C",
                    (cx + round(10 * s), cy - round(4 * s)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5 * s,
                    (255, 255, 255), max(1, round(2 * s)), cv2.LINE_AA)


def draw_pose_axes(img, obj, K, s=1.0):
    """XYZ 축 + 라벨 — visualize_annotations.py 동일."""
    pose = np.array(obj["pose_transform"])
    R = pose[:3, :3]
    t = pose[:3, 3]

    K_mat = np.array([
        [K["fx"], 0, K["cx"]],
        [0, K["fy"], K["cy"]],
        [0, 0, 1],
    ])

    origin_px = K_mat @ t
    origin_px = (origin_px[:2] / origin_px[2]).astype(int)

    axis_len = 0.3
    axis_colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]
    axis_labels = ["X", "Y", "Z"]
    line_w = max(2, round(3 * s))

    h, w = img.shape[:2]
    for i in range(3):
        direction = R[:, i] * axis_len
        end_3d = t + direction
        end_px = K_mat @ end_3d
        end_px = (end_px[:2] / end_px[2]).astype(int)

        if 0 <= origin_px[0] < w and 0 <= origin_px[1] < h:
            cv2.arrowedLine(img, tuple(origin_px), tuple(end_px),
                            axis_colors[i], line_w, tipLength=0.15,
                            line_type=cv2.LINE_AA)
            cv2.putText(img, axis_labels[i],
                        (end_px[0] + round(5 * s), end_px[1] - round(5 * s)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6 * s,
                        axis_colors[i], max(1, round(2 * s)), cv2.LINE_AA)


def draw_info_text(img, obj, s=1.0):
    """euler angles + visibility — visualize_annotations.py 동일."""
    euler = obj["euler_angles"]
    vis = obj["visibility"]
    color_var = obj.get("pallet_color_variant", "")
    boxes = obj.get("box_count", "")
    cam_dist = obj.get("camera_distance", 0)

    lines = [
        f"pitch: {euler['pitch']:.1f}",
        f"yaw:   {euler['yaw']:.1f}",
        f"roll:  {euler['roll']:.1f}",
        f"vis:   {vis:.2f}",
    ]
    if color_var:
        lines.append(f"color: {color_var}")
    if boxes != "":
        lines.append(f"boxes: {boxes}")
    if cam_dist:
        lines.append(f"dist:  {cam_dist:.2f}m")

    font_scale = 0.55 * s
    font_thick = max(1, round(1 * s))
    y0 = round(25 * s)
    line_h = round(22 * s)

    for i, line in enumerate(lines):
        # 배경 반투명 박스
        text_size = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX,
                                    font_scale, font_thick)[0]
        x0 = round(10 * s)
        y_text = y0 + i * line_h
        cv2.rectangle(img,
                      (x0 - 2, y_text - text_size[1] - 4),
                      (x0 + text_size[0] + 4, y_text + 4),
                      (0, 0, 0), -1)
        cv2.putText(img, line, (x0, y_text),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    (0, 255, 255), font_thick, cv2.LINE_AA)


def process_frame(rgb_path, json_path, output_path, target_size=None):
    img = cv2.imread(rgb_path)
    if img is None:
        print(f"  [SKIP] cannot read {rgb_path}")
        return False

    with open(json_path) as f:
        data = json.load(f)

    orig_h, orig_w = img.shape[:2]
    s = 1.0
    pad_top = pad_left = 0

    if target_size:
        tw, th = target_size
        s = min(tw / orig_w, th / orig_h)
        new_w, new_h = int(orig_w * s), int(orig_h * s)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        pad_top = (th - new_h) // 2
        pad_left = (tw - new_w) // 2
        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        canvas[pad_top:pad_top + new_h, pad_left:pad_left + new_w] = img
        img = canvas

    K = data["camera_data"]["intrinsics"]

    for obj in data["objects"]:
        pts_2d = np.array(obj["projected_cuboid"], dtype=np.float64)
        centroid = obj["projected_cuboid_centroid"]

        if target_size:
            pts_2d = pts_2d * s
            pts_2d[:, 0] += pad_left
            pts_2d[:, 1] += pad_top
        pts_2d = pts_2d.astype(int)

        centroid_2d = (int(centroid[0] * s) + pad_left,
                       int(centroid[1] * s) + pad_top) if target_size else \
                      (int(centroid[0]), int(centroid[1]))

        K_scaled = {
            "fx": K["fx"] * s, "fy": K["fy"] * s,
            "cx": K["cx"] * s + pad_left, "cy": K["cy"] * s + pad_top,
        } if target_size else K

        draw_cuboid(img, pts_2d, centroid_2d, s)
        draw_pose_axes(img, obj, K_scaled, s)
        draw_info_text(img, obj, s)

    cv2.imwrite(output_path, img)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--frames", nargs="+", type=int, required=True)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    target_size = (args.width, args.height)

    for idx in args.frames:
        basename = f"{idx:06d}"
        rgb_path = os.path.join(args.data_dir, f"{basename}.png")
        json_path = os.path.join(args.data_dir, f"{basename}.json")
        if not os.path.exists(rgb_path) or not os.path.exists(json_path):
            print(f"  [SKIP] {basename}")
            continue
        output_path = os.path.join(args.output_dir, f"ppt_{basename}.png")
        if process_frame(rgb_path, json_path, output_path, target_size):
            print(f"  {basename} -> {os.path.basename(output_path)}")

    print(f"\nDone! -> {args.output_dir}")


if __name__ == "__main__":
    main()
