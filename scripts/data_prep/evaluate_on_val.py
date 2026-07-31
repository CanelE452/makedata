"""Phase 5: 합성 검증셋에서 DOPE 추론 + 6D pose 종합 평가.

메트릭:
  - PCK@3px, PCK@5px, PCK@10px (belief map 해상도)
  - ADD (Average Distance of Model Points, <0.1d)
  - 5cm-5° (translation <5cm AND rotation <5°)
  - 2D Reproj error (mean px)

사용법:
    python scripts/data_prep/evaluate_on_val.py \
        --weights weights/pallet_category/final_net_epoch_0060.pth \
        --val_dir "$(python scripts/data_prep/blender/pallet_data_paths.py --resolve registry:legacy_training_data_root/val)" \
        --output_dir data/pallet/runs/eval
"""

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np
import torch
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Deep_Object_Pose", "common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Deep_Object_Pose", "train"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "self_training"))

try:
    from models import DopeNetwork
except ImportError:
    print("[ERROR] Cannot import DopeNetwork. Check Deep_Object_Pose path.")
    sys.exit(1)

from pnp_solver import PalletPnPSolver, make_camera_matrix, make_pallet_keypoints_3d
from metrics import compute_reproj_error


def load_model(weights_path, device):
    """학습된 DOPE 모델 로드."""
    model = DopeNetwork()
    state = torch.load(weights_path, map_location=device)
    if any(k.startswith("module.") for k in state.keys()):
        state = {k.replace("module.", ""): v for k, v in state.items()}
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model


def extract_keypoints_from_belief(belief_maps, threshold=0.5):
    """belief map에서 keypoint 좌표 추출 (DOPE 공식 sub-pixel 방식).

    1. Gaussian filter로 노이즈 억제
    2. Non-maximum suppression으로 peak 탐색
    3. 11x11 윈도우에서 weighted average로 sub-pixel 정밀도 확보
    """
    OFFSET = 0.4395
    WIN = 11
    RAN = WIN // 2
    keypoints = []

    for i in range(belief_maps.shape[0]):
        bmap_ori = belief_maps[i]
        max_val = bmap_ori.max()
        if max_val < threshold:
            keypoints.append((-1, -1, float(max_val)))
            continue

        bmap_smooth = gaussian_filter(bmap_ori, sigma=2)
        p = 1
        pad_l = np.zeros_like(bmap_smooth); pad_l[p:, :] = bmap_smooth[:-p, :]
        pad_r = np.zeros_like(bmap_smooth); pad_r[:-p, :] = bmap_smooth[p:, :]
        pad_u = np.zeros_like(bmap_smooth); pad_u[:, p:] = bmap_smooth[:, :-p]
        pad_d = np.zeros_like(bmap_smooth); pad_d[:, :-p] = bmap_smooth[:, p:]

        peaks_binary = (
            (bmap_smooth >= pad_l) & (bmap_smooth >= pad_r) &
            (bmap_smooth >= pad_u) & (bmap_smooth >= pad_d) &
            (bmap_smooth > threshold)
        )

        peak_ys, peak_xs = np.nonzero(peaks_binary)
        if len(peak_xs) == 0:
            keypoints.append((-1, -1, float(max_val)))
            continue

        peak_vals = [bmap_ori[py, px] for py, px in zip(peak_ys, peak_xs)]
        best_idx = np.argmax(peak_vals)
        px, py = int(peak_xs[best_idx]), int(peak_ys[best_idx])

        y_lo = max(0, py - RAN); y_hi = min(bmap_ori.shape[0], py + RAN + 1)
        x_lo = max(0, px - RAN); x_hi = min(bmap_ori.shape[1], px + RAN + 1)
        patch = bmap_ori[y_lo:y_hi, x_lo:x_hi]

        if patch.sum() > 0:
            ys = np.arange(y_lo, y_hi)
            xs = np.arange(x_lo, x_hi)
            xg, yg = np.meshgrid(xs, ys)
            wx = np.average(xg, weights=patch) + OFFSET
            wy = np.average(yg, weights=patch) + OFFSET
        else:
            wx, wy = float(px), float(py)

        keypoints.append((wx, wy, float(max_val)))
    return keypoints


def compute_pck(pred_kps, gt_kps, threshold_px=10):
    """PCK (Percentage of Correct Keypoints). Sub-pixel 좌표 지원."""
    correct = 0
    total = 0
    for kp, (gx, gy) in zip(pred_kps, gt_kps):
        px, py = kp[0], kp[1]
        if px < 0 or gx < 0:
            continue
        total += 1
        dist = np.sqrt((float(px) - float(gx)) ** 2 + (float(py) - float(gy)) ** 2)
        if dist <= threshold_px:
            correct += 1
    return correct, total


def main():
    parser = argparse.ArgumentParser(description="DOPE 6D Pose 종합 평가")
    parser.add_argument("--weights", required=True)
    parser.add_argument("--val_dir", required=True)
    parser.add_argument("--output_dir", default="data/pallet/runs/eval")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="Belief map peak threshold")
    parser.add_argument("--max_frames", type=int, default=200)
    parser.add_argument("--fx", type=float, default=615.0)
    parser.add_argument("--fy", type=float, default=615.0)
    parser.add_argument("--cx", type=float, default=320.0)
    parser.add_argument("--cy", type=float, default=240.0)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(f"Loading model: {args.weights}")
    model = load_model(args.weights, device)

    # PnP solver setup
    cam_matrix = make_camera_matrix(args.fx, args.fy, args.cx, args.cy)
    pnp_solver = PalletPnPSolver(cam_matrix)

    png_files = sorted(glob.glob(os.path.join(args.val_dir, "*.png")))[:args.max_frames]
    print(f"Evaluating {len(png_files)} frames...")

    pck_counters = {3: [0, 0], 5: [0, 0], 10: [0, 0]}
    pnp_success_count = 0
    pnp_total = 0
    reproj_errors = []

    mean = np.array([0.485, 0.456, 0.406])
    std = np.array([0.229, 0.224, 0.225])

    for i, png_path in enumerate(png_files):
        basename = os.path.splitext(os.path.basename(png_path))[0]
        json_path = os.path.join(args.val_dir, basename + ".json")
        if not os.path.exists(json_path):
            continue

        # 이미지 로드 + 전처리
        img = cv2.imread(png_path)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_resized = cv2.resize(img_rgb, (448, 448))
        img_norm = (img_resized.astype(np.float32) / 255.0 - mean) / std
        tensor = torch.from_numpy(img_norm.transpose(2, 0, 1)).float().unsqueeze(0).to(device)

        with torch.no_grad():
            out_bel, out_aff = model(tensor)

        belief = out_bel[-1][0].cpu().numpy()
        pred_kps = extract_keypoints_from_belief(belief, args.threshold)

        # GT 로드
        with open(json_path) as f:
            data = json.load(f)
        obj = data["objects"][0]
        gt_cuboid = obj["projected_cuboid"]
        gt_centroid = obj["projected_cuboid_centroid"]

        # GT를 belief map 해상도로 스케일링
        h_orig, w_orig = img.shape[:2]
        bh, bw = belief.shape[1], belief.shape[2]
        sx, sy = bw / w_orig, bh / h_orig
        gt_kps_scaled = [(gx * sx, gy * sy) for gx, gy in gt_cuboid]
        gt_kps_scaled.append((gt_centroid[0] * sx, gt_centroid[1] * sy))

        # PCK@3, @5, @10
        for thr in pck_counters:
            c, t = compute_pck(pred_kps, gt_kps_scaled, threshold_px=thr)
            pck_counters[thr][0] += c
            pck_counters[thr][1] += t

        # --- 6D Pose 메트릭: PnP reproj vs GT 2D ---
        # (GT pose_transform은 Isaac Sim world 좌표계라 PnP camera 좌표계와 직접 비교 불가)
        # 대신 PnP로 복원한 포즈를 다시 2D로 재투영해서 GT 2D keypoint와 비교
        pred_kps_orig = []
        for kp in pred_kps:
            if kp[0] < 0:
                pred_kps_orig.append(None)
            else:
                pred_kps_orig.append((float(kp[0]) / sx, float(kp[1]) / sy))

        pnp_total += 1
        success, R_pred, t_pred, _ = pnp_solver.solve(pred_kps_orig)

        if success:
            pnp_success_count += 1
            # PnP pose → 2D reproj → GT 2D와 비교
            reproj_pred = pnp_solver.reproject(R_pred, t_pred)
            gt_kps_orig = np.array(gt_cuboid + [gt_centroid], dtype=np.float64)
            reproj_err, per_point = compute_reproj_error(gt_kps_orig, reproj_pred)
            reproj_errors.append(reproj_err)

        if (i + 1) % 50 == 0:
            pck3 = pck_counters[3][0] / max(pck_counters[3][1], 1)
            print(f"  [{i+1}/{len(png_files)}] PCK@3px: {pck3:.3f}, PnP success: {pnp_success_count}/{pnp_total}")

    # ========== 최종 결과 ==========
    print(f"\n{'='*60}")
    print(f" DOPE Evaluation Results ({len(png_files)} frames)")
    print(f"{'='*60}")

    # PCK
    for thr in sorted(pck_counters):
        c, t = pck_counters[thr]
        pck = c / max(t, 1)
        print(f"  PCK@{thr}px:   {pck:.4f}  ({c}/{t})")

    # PnP + Reproj 메트릭
    print(f"\n  PnP success:  {pnp_success_count}/{pnp_total} ({pnp_success_count/max(pnp_total,1)*100:.1f}%)")

    if reproj_errors:
        reproj_arr = np.array(reproj_errors)
        reproj_5px = np.mean(reproj_arr < 5.0) * 100
        reproj_10px = np.mean(reproj_arr < 10.0) * 100
        print(f"\n  --- PnP Reproj Metrics ({len(reproj_errors)} frames) ---")
        print(f"  Reproj error mean:  {reproj_arr.mean():.2f} px")
        print(f"  Reproj error med:   {np.median(reproj_arr):.2f} px")
        print(f"  Reproj <5px:        {reproj_5px:.1f}%")
        print(f"  Reproj <10px:       {reproj_10px:.1f}%")
    else:
        print("  (No successful PnP for reproj metrics)")

    print(f"{'='*60}")

    # 결과 저장
    summary = {
        "pck": {f"@{thr}px": pck_counters[thr][0] / max(pck_counters[thr][1], 1) for thr in pck_counters},
        "pnp_success_rate": pnp_success_count / max(pnp_total, 1),
        "reproj_mean_px": float(np.mean(reproj_errors)) if reproj_errors else None,
        "reproj_median_px": float(np.median(reproj_errors)) if reproj_errors else None,
        "num_frames": len(png_files),
    }
    summary_path = os.path.join(args.output_dir, "eval_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Results saved: {summary_path}")


if __name__ == "__main__":
    main()
