"""Generate surface_fps_v1.json — visibility-constrained surface FPS keypoints
for pallet_full.obj (PVNet surface-point comparison).

Pipeline (plan §4): area-weighted surface sample -> drop bottom faces ->
operating-viewpoint visibility raycast (drop internal/occluded) -> deterministic
FPS 8 points. Saves object-frame points + mesh hash + seed.

obj frame: Y = up/height (extents X1.10 Y0.12 Z1.30). Pallet is intrinsically
flat so planarity ~0.09 is the object limit (box corner is 0.092 too).
"""
import trimesh, numpy as np, json, hashlib, os

OBJ = "data/palletobj/pallet_full.obj"
OUT = "data/pallet/train_palletobj_v3_post_v1/surface_fps_v1.json"
SEED = 1234


def fps(P, k, seed, w=None):
    rng = np.random.default_rng(seed)
    Pw = P * w if w is not None else P
    i0 = int(rng.integers(len(P))); idx = [i0]
    d = np.linalg.norm(Pw - Pw[i0], axis=1)
    for _ in range(k - 1):
        j = int(d.argmax()); idx.append(j)
        d = np.minimum(d, np.linalg.norm(Pw - Pw[j], axis=1))
    return P[idx], idx


def main():
    mesh = trimesh.load(OBJ, force='mesh')
    rng = np.random.default_rng(SEED)
    # 1) area-weighted sample + drop bottom faces (normal_Y < -0.3)
    pts, fid = trimesh.sample.sample_surface(mesh, 80000, seed=SEED)
    nrm = mesh.face_normals[fid]
    keep = nrm[:, 1] > -0.3
    cand, cn = pts[keep], nrm[keep]
    # subsample for raycast cost
    sub = rng.choice(len(cand), size=min(800, len(cand)), replace=False)
    cand, cn = cand[sub], cn[sub]
    # 2) operating-viewpoint visibility raycast (obj Y-up; elev 12~60, azim 360)
    cams = []
    for el in np.radians([15, 30, 45, 55]):
        for az in np.radians(range(0, 360, 45)):
            cams.append(3.0 * np.array([np.cos(el)*np.cos(az), np.sin(el), np.cos(el)*np.sin(az)]))
    cams = np.array(cams)  # 32 viewpoints
    vis = np.zeros(len(cand))
    for i, (p, n) in enumerate(zip(cand, cn)):
        org = p + n * 2e-3
        seen = 0
        for c in cams:
            d = c - p; dist = np.linalg.norm(d); dirn = d / dist
            if np.dot(n, dirn) <= 0.05:        # back-facing for this view
                continue
            locs, _, _ = mesh.ray.intersects_location([org], [dirn])
            if len(locs) == 0:
                seen += 1                       # nothing between point and camera
            else:
                hd = np.linalg.norm(locs - org, axis=1).min()
                if hd > dist - 1e-2:
                    seen += 1
        vis[i] = seen / len(cams)
    visible = cand[vis > 0.25]                  # seen from >=25% of operating views
    print(f"candidate {len(cand)} -> visible {len(visible)} (vis>0.25)")
    # 3) deterministic FPS 8 (Y-weighted to spread across height/sides)
    f8, _ = fps(visible, 8, SEED, w=np.array([1., 6., 1.]))
    c = f8 - f8.mean(0); sv = np.linalg.svd(c, compute_uv=False)
    print("FPS 8 (obj):"); print(f8.round(3))
    print(f"Y range [{f8[:,1].min():.3f},{f8[:,1].max():.3f}] planarity {sv.min()/sv.max():.4f} "
          f"(객체 한계 ~0.09; box corner 0.092)")
    # save
    sha = hashlib.sha256(open(OBJ, "rb").read()).hexdigest()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({
        "version": "surface_fps_v1", "seed": SEED, "mesh_sha256": sha,
        "obj_path": OBJ, "up_axis": "Y",
        "points_object_frame": f8.round(5).tolist(),
        "planarity": round(float(sv.min()/sv.max()), 4),
        "symmetry_permutations": [[0, 1, 2, 3, 4, 5, 6, 7]],  # 대칭 분석은 다음 단계
        "note": "visibility-constrained surface sample + deterministic FPS; flat pallet planarity ~box corner"
    }, open(OUT, "w"), indent=2)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
