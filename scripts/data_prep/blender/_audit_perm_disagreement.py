"""기존 train_batch 0123 라벨(object-frame 고정) vs compute_perm_v4(camera-facing) 정합성 정량 감사.

기존 라벨: render_blender_data.py가 get_pallet_geometry -> canonical_corners_yup 순서를 그대로 사용.
           즉 입력 corner i 의 라벨 ID = i (identity).
v4 라벨  : compute_perm_v4(corners_world=cuboid, uv8=projected_cuboid, cam_pos=cam_loc).
           perm[k] = 새 ID k 에 배정된 입력 corner index.
           => 입력 corner i 의 v4 ID = inv_perm[i].

disagreement:
  - perm 불일치: inv_perm != identity 인 프레임 (어떤 corner의 ID라도 바뀜).
  - FRONT 불일치: 기존 FRONT set {0,1,2,3} (입력 corner 0..3) vs v4 FRONT = perm[0:4] (입력 corner index).
                  두 집합이 다르면 FRONT 면 자체가 다른 물리면을 가리킴.
"""
import json, glob, os, re, sys
import numpy as np

_d = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _d)
from blender_math import compute_perm_v4

TRAIN_DIR = sys.argv[1] if len(sys.argv) > 1 else \
    "E:/CODING/GitHub/FoundationPose/data/pallet/training_data"

batches = [b for b in glob.glob(os.path.join(TRAIN_DIR, "train_batch_*")) if os.path.isdir(b)]
batches.sort(key=lambda p: int(re.search(r"(\d+)$", p).group(1)))

IDENT = np.arange(8)
n_total = 0
n_perm_diff = 0
n_front_diff = 0
n_no_campos = 0
front_cos_list = []
# camera elevation bucket: angle of cam above pallet centroid horizontal plane
bucket_stats = {}  # bucket -> [n, front_diff, perm_diff]

def elevation_deg(cam, centroid):
    v = cam - centroid
    horiz = np.hypot(v[0], v[1])
    return np.degrees(np.arctan2(v[2], horiz + 1e-9))

for b in batches:
    for jp in sorted(glob.glob(os.path.join(b, "*.json"))):
        try:
            d = json.load(open(jp))
            o = d["objects"][0]
            cub = np.array(o["cuboid"], dtype=np.float64)
            uv = np.array(o["projected_cuboid"], dtype=np.float64)
            cam = d["camera_data"].get("location_worldframe")
        except Exception:
            continue
        if cub.shape != (8, 3) or uv.shape != (8, 2):
            continue
        n_total += 1
        if cam is None:
            n_no_campos += 1
            continue
        cam = np.array(cam, dtype=np.float64)
        centroid = cub.mean(axis=0)
        perm, margin, front_cos = compute_perm_v4(cub, uv, cam_pos=cam, return_margin=True)
        front_cos_list.append(float(front_cos))
        inv = np.argsort(perm)  # inv[i] = v4 ID of input corner i
        perm_diff = not np.array_equal(inv, IDENT)
        # FRONT set comparison: existing front = input corners {0,1,2,3}; v4 front = perm[0:4]
        front_diff = set(perm[:4].tolist()) != {0, 1, 2, 3}
        if perm_diff:
            n_perm_diff += 1
        if front_diff:
            n_front_diff += 1
        # elevation bucket
        el = elevation_deg(cam, centroid)
        if el < 15:
            bk = "low (<15deg, forklift-like)"
        elif el < 35:
            bk = "mid (15-35deg)"
        elif el < 60:
            bk = "high (35-60deg)"
        else:
            bk = "top-down (>=60deg)"
        s = bucket_stats.setdefault(bk, [0, 0, 0])
        s[0] += 1
        s[1] += int(front_diff)
        s[2] += int(perm_diff)

print(f"TOTAL frames scanned : {n_total}")
print(f"frames w/o cam_pos   : {n_no_campos}")
n_eval = n_total - n_no_campos
print(f"frames evaluated     : {n_eval}")
print()
print(f"PERM disagreement    : {n_perm_diff}/{n_eval} = {100.0*n_perm_diff/max(n_eval,1):.1f}%")
print(f"FRONT disagreement   : {n_front_diff}/{n_eval} = {100.0*n_front_diff/max(n_eval,1):.1f}%")
print()
fc = np.array(front_cos_list)
print("front_cos distribution (FRONT-face facing cos, v4):")
print(f"  min={fc.min():.3f} p10={np.percentile(fc,10):.3f} med={np.median(fc):.3f} "
      f"p90={np.percentile(fc,90):.3f} max={fc.max():.3f}")
for thr in (0.40, 0.0):
    print(f"  frac front_cos < {thr:.2f} : {100.0*(fc<thr).mean():.1f}%")
print()
print("by camera elevation bucket:  bucket | n | FRONT_diff% | PERM_diff%")
for bk in ["low (<15deg, forklift-like)", "mid (15-35deg)", "high (35-60deg)", "top-down (>=60deg)"]:
    if bk in bucket_stats:
        n, fd, pd = bucket_stats[bk]
        print(f"  {bk:30s} n={n:4d}  FRONT={100.0*fd/n:5.1f}%  PERM={100.0*pd/n:5.1f}%")
