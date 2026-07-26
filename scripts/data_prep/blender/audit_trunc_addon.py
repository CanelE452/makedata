"""Self-audit for the trunc_addon_v1 pilot. Standalone (numpy + PIL, no bpy).

Checks (PASS gates):
  1. convention reproj error: reproject keypoints_3d_world with K + camera extrinsic
     (rebuilt from stored camera quaternion+location) vs projected_cuboid. p99 < 1px.
  2. realized elevation distribution vs the 5-bin prescription.
  3. realized V (num in-frame corners) distribution vs target.
  4. per-corner label existence/format + internal consistency.
  5. rear-corner (ids 4-7) survival in low-elevation (<15deg) frames.
Also copies representative frames' overlays into an audit_eye/ folder for eye-verification.

Usage:  python audit_trunc_addon.py --dir E:/.../data/pallet/trunc_addon_v1
"""
import os, json, glob, argparse, math, collections, shutil
import numpy as np

ELEV_EDGES = [(0.5, 3.0), (3.0, 8.0), (8.0, 15.0), (15.0, 25.0), (25.0, 60.0)]
ELEV_LABEL = ["<3", "3-8", "8-15", "15-25", "25+"]
ELEV_TARGET = [10, 30, 30, 15, 15]
V_TARGET = {4: 15, 5: 25, 6: 30, 7: 20, 8: 10}


def quat_xyzw_to_R(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


# 4 vertical SIDE faces by reindexed corner id (camera_dynamic_0123_v4 adjacency):
#   0=f-top-L 1=f-top-R 2=f-bot-R 3=f-bot-L / 4=r-top-L 5=r-top-R 6=r-bot-R 7=r-bot-L
# front{0,1,2,3} rear{4,5,6,7} left{0,3,4,7} right{1,2,5,6}. (verified vs frame 000002 world coords)
SIDE_FACES = {"front": (0, 1, 2, 3), "rear": (4, 5, 6, 7),
              "left": (0, 3, 4, 7), "right": (1, 2, 5, 6)}
CAMFACE_EPS = 0.05  # tie tolerance (near-45deg corner views two faces can tie)


def side_face_facings(corners8, cam):
    """Independent (NOT via compute_perm_v4) facing of each vertical side face:
    dot(outward_normal, unit(cam - face_center)). FRONT should be the argmax."""
    centroid = corners8.mean(axis=0)
    out = {}
    for name, idx in SIDE_FACES.items():
        fc = corners8[list(idx)].mean(axis=0)
        nrm = fc - centroid
        vv = cam - fc
        nn, vn = np.linalg.norm(nrm), np.linalg.norm(vv)
        out[name] = float(np.dot(nrm / nn, vv / vn)) if (nn > 1e-9 and vn > 1e-9) else -1.0
    return out


def elev_bin(e):
    for i, (lo, hi) in enumerate(ELEV_EDGES):
        if e < hi:
            return i
    return 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    jsons = sorted(glob.glob(os.path.join(args.dir, "0*.json")))
    print(f"audit dir: {args.dir}")
    print(f"json frames: {len(jsons)}")
    if not jsons:
        print("NO FRAMES"); return

    # accumulators
    all_du, all_dv = [], []          # per in-front keypoint reprojection residuals (px)
    per_id_res = collections.defaultdict(list)
    elev_bins = collections.Counter()
    Vc = collections.Counter()
    label_fail = []
    bitmask_fail = 0
    vgeom_fail = 0
    rear_infront = 0; rear_infront_tot = 0
    rear_inside = 0; rear_inside_tot = 0
    lowelev_frames = 0
    lowelev_rear_all_infront = 0
    behind_kp_frames = 0
    per_id_infront = collections.Counter(); per_id_inside = collections.Counter(); per_id_n = collections.Counter()
    camface_pass = 0                       # FRONT(0-3) == camera max-facing side face
    camface_fail = []                      # (frame, should_be_front, front_facing, max_facing)
    camface_argmax = collections.Counter() # when FRONT wrong, which face truly max-faces cam
    frames_meta = []

    REQ = ["keypoint_in_front_of_camera", "keypoint_inside_image", "keypoint_visible",
           "V_geom", "missing_corner_bitmask"]

    for jf in jsons:
        d = json.load(open(jf))
        cam = d["camera_data"]
        K = cam["intrinsics"]
        fx, fy, cx, cy = K["fx"], K["fy"], K["cx"], K["cy"]
        cpos = np.array(cam["location_worldframe"], dtype=np.float64)
        R_c2w = quat_xyzw_to_R(cam["quaternion_xyzw_worldframe"])
        # Blender cam -> OpenCV: x=right(+X), y=down(-Y_local), z=forward(-Z_local)
        R_w2c = np.stack([R_c2w[:, 0], -R_c2w[:, 1], -R_c2w[:, 2]], axis=0)

        o = d["objects"][0]
        kp3d = np.array(o["keypoints_3d_world"], dtype=np.float64)          # (9,3)
        proj = np.array(o["projected_cuboid"], dtype=np.float64)            # (8,2)
        projc = np.array(o["projected_cuboid_centroid"], dtype=np.float64)  # (2,)
        proj_all = np.vstack([proj, projc[None, :]])                        # (9,2)

        e = d["frame_meta"].get("camera_elevation_deg", 0.0)
        b = elev_bin(e)
        elev_bins[b] += 1

        # --- (8) camera-facing permutation check (independent of compute_perm_v4) ---
        facings = side_face_facings(kp3d[:8], cpos)
        max_face = max(facings, key=facings.get)
        if facings["front"] >= facings[max_face] - CAMFACE_EPS:
            camface_pass += 1
        else:
            camface_argmax[max_face] += 1
            if len(camface_fail) < 8:
                camface_fail.append((os.path.basename(jf)[:6], max_face,
                                     round(facings["front"], 2), round(facings[max_face], 2)))

        # --- label existence/format ---
        missing = [k for k in REQ if k not in o]
        if missing:
            label_fail.append((os.path.basename(jf), missing))
            frames_meta.append((jf, d["frame_meta"], o.get("V_geom")))
            continue
        inf = o["keypoint_in_front_of_camera"]
        ins = o["keypoint_inside_image"]
        vis = o["keypoint_visible"]
        vgeom = o["V_geom"]
        bmask = o["missing_corner_bitmask"]
        oklen = (len(inf) == 9 and len(ins) == 9 and len(vis) == 9)
        if not oklen:
            label_fail.append((os.path.basename(jf), "len!=9"))

        Vc[vgeom] += 1

        # bitmask + V_geom consistency (8 corners)
        exp_mask = 0
        exp_vgeom = 0
        for k in range(8):
            in_frame_k = bool(inf[k] and ins[k])
            if in_frame_k:
                exp_vgeom += 1
            else:
                exp_mask |= (1 << k)
        if exp_mask != bmask:
            bitmask_fail += 1
        if exp_vgeom != vgeom:
            vgeom_fail += 1

        # per-id in_front/inside stats
        for k in range(8):
            per_id_n[k] += 1
            if inf[k]:
                per_id_infront[k] += 1
            if ins[k]:
                per_id_inside[k] += 1
        if not all(inf[k] for k in range(8)):
            behind_kp_frames += 1

        # --- reprojection over in-front keypoints (raw, no clamp) ---
        for k in range(9):
            if not inf[k]:
                continue
            Xc = R_w2c @ (kp3d[k] - cpos)
            if Xc[2] <= 1e-6:
                continue
            u = fx * Xc[0] / Xc[2] + cx
            v = fy * Xc[1] / Xc[2] + cy
            du = u - proj_all[k, 0]
            dv = v - proj_all[k, 1]
            all_du.append(du); all_dv.append(dv)
            per_id_res[k].append(math.hypot(du, dv))

        # --- rear-corner (ids 4-7) survival, low elevation ---
        if e < 15.0:
            lowelev_frames += 1
            rall = True
            for k in (4, 5, 6, 7):
                rear_infront_tot += 1; rear_inside_tot += 1
                if inf[k]:
                    rear_infront += 1
                else:
                    rall = False
                if ins[k]:
                    rear_inside += 1
            if rall:
                lowelev_rear_all_infront += 1

        frames_meta.append((jf, d["frame_meta"], vgeom))

    n = len(jsons)
    du = np.array(all_du); dv = np.array(all_dv)
    res = np.hypot(du, dv)
    print("\n" + "=" * 64)
    print("1) CONVENTION REPROJ ERROR (in-front keypoints, px)")
    print(f"   samples={len(res)}")
    print(f"   |du|  p50={np.percentile(np.abs(du),50):.4f}  p99={np.percentile(np.abs(du),99):.4f}  max={np.abs(du).max():.4f}")
    print(f"   |dv|  p50={np.percentile(np.abs(dv),50):.4f}  p99={np.percentile(np.abs(dv),99):.4f}  max={np.abs(dv).max():.4f}")
    print(f"   dist  p50={np.percentile(res,50):.4f}  p99={np.percentile(res,99):.4f}  max={res.max():.4f}")
    reproj_pass = np.percentile(res, 99) < 1.0
    print(f"   PASS(p99<1px): {reproj_pass}")

    print("\n2) ELEVATION DISTRIBUTION (realized vs prescription)")
    print(f"   {'bin':8s} {'realized':>9s} {'target':>7s}")
    for i in range(5):
        print(f"   {ELEV_LABEL[i]:8s} {100*elev_bins[i]/n:8.1f}% {ELEV_TARGET[i]:6d}%")
    low = 100 * (elev_bins[0] + elev_bins[1] + elev_bins[2]) / n
    print(f"   <15deg total: {low:.1f}% (target 70%)")

    print("\n3) V DISTRIBUTION (realized vs target)")
    for v in (4, 5, 6, 7, 8):
        print(f"   V{v}: {100*Vc[v]/n:6.1f}%  (target {V_TARGET[v]}%)")
    extra = {k: Vc[k] for k in Vc if k not in (4, 5, 6, 7, 8)}
    if extra:
        print(f"   OUT-OF-RANGE V (should be none): {extra}")

    print("\n4) PER-CORNER LABEL VALIDATION")
    print(f"   frames missing label fields: {len(label_fail)}")
    if label_fail[:5]:
        print(f"     e.g. {label_fail[:5]}")
    print(f"   bitmask inconsistent frames: {bitmask_fail}/{n}")
    print(f"   V_geom inconsistent frames : {vgeom_fail}/{n}")
    print(f"   frames with >=1 camera-behind corner (in_front=false): {behind_kp_frames}")
    print("   per-id in_front% / inside_image% (id order = camera_dynamic_0123_v4):")
    for k in range(8):
        tag = "REAR" if k >= 4 else "front"
        print(f"     id{k}({tag}): in_front {100*per_id_infront[k]/max(1,per_id_n[k]):5.1f}%  "
              f"inside {100*per_id_inside[k]/max(1,per_id_n[k]):5.1f}%")

    print("\n5) REAR-CORNER (ids 4-7) SURVIVAL @ low elevation (<15deg)")
    print(f"   low-elev frames: {lowelev_frames}")
    if rear_infront_tot:
        print(f"   rear-corner in_front:      {100*rear_infront/rear_infront_tot:.1f}%")
        print(f"   rear-corner inside_image:  {100*rear_inside/rear_inside_tot:.1f}%")
        print(f"   frames with ALL 4 rear in_front: {100*lowelev_rear_all_infront/max(1,lowelev_frames):.1f}%")

    print("\n6) PER-ID REPROJ (px, in-front only)")
    for k in range(9):
        if per_id_res[k]:
            arr = np.array(per_id_res[k])
            tag = "centroid" if k == 8 else ("REAR" if k >= 4 else "front")
            print(f"     id{k}({tag}): p50={np.percentile(arr,50):.4f} p99={np.percentile(arr,99):.4f} n={len(arr)}")

    print("\n*** CONVENTION PERMUTATION: FRONT(0-3) == camera max-facing side face ***")
    print(f"   (independent of compute_perm_v4; catches 0123 mis-assignment that reproj cannot)")
    print(f"   PASS frames: {camface_pass}/{n} ({100*camface_pass/n:.1f}%)  eps={CAMFACE_EPS}")
    camface_ok = (camface_pass == n)
    if camface_fail:
        print(f"   MISLABELED e.g. (frame, should_be_front, front_facing, max_facing):")
        for row in camface_fail:
            print(f"     {row}")
    if camface_argmax:
        print(f"   when FRONT wrong, true max-facing face: {dict(camface_argmax)}")

    # eye-check selection
    eye = os.path.join(args.dir, "audit_eye")
    os.makedirs(eye, exist_ok=True)
    picks = {"lowelev_trunc": [], "worst": [], "rear_missing": [], "close": []}
    for jf, fm, vg in frames_meta:
        stem = os.path.basename(jf)[:6]
        e = fm.get("camera_elevation_deg", 0.0)
        if fm.get("worst_combo") and len(picks["worst"]) < 3:
            picks["worst"].append(stem)
        elif fm.get("truncation_applied") and e < 15 and len(picks["lowelev_trunc"]) < 3:
            picks["lowelev_trunc"].append(stem)
        elif fm.get("camera_dist_from_pallet_surface_m", 9) < 0.6 and len(picks["close"]) < 2:
            picks["close"].append(stem)
    # a frame where a rear corner is missing (bitmask has bit 4-7)
    for jf in jsons:
        o = json.load(open(jf))["objects"][0]
        bm = o.get("missing_corner_bitmask", 0)
        if any(bm & (1 << k) for k in (4, 5, 6, 7)) and len(picks["rear_missing"]) < 3:
            picks["rear_missing"].append(os.path.basename(jf)[:6])
    copied = []
    for cat, stems in picks.items():
        for s in stems:
            src = os.path.join(args.dir, "overlay", f"{s}.png")
            if os.path.isfile(src):
                dst = os.path.join(eye, f"{cat}_{s}.png")
                shutil.copy(src, dst)
                copied.append(dst)
    print("\n7) EYE-CHECK FRAMES copied to audit_eye/:")
    for c in copied:
        print(f"   {c}")

    print("\n" + "=" * 64)
    print("VERDICT SUMMARY")
    print(f"  reproj p99<1px         : {reproj_pass}")
    print(f"  elevation <15deg ~70%  : {low:.1f}%")
    print(f"  V in [4..8] only       : {len(extra)==0}")
    print(f"  labels present/consistent: {len(label_fail)==0 and bitmask_fail==0 and vgeom_fail==0}")
    print(f"  0123==camera max-facing : {camface_pass}/{n} ({100*camface_pass/n:.1f}%)  PASS={camface_ok}")
    if rear_infront_tot:
        print(f"  rear in_front @lowelev : {100*rear_infront/rear_infront_tot:.1f}%")


if __name__ == "__main__":
    main()
