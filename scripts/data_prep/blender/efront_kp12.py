"""E-front 12-keypoint construction for the 4 warehouse pallets (ADDITIVE).

This module is fully self-contained and does NOT modify or import any dataset
generator. It turns the existing camera-dynamic 0123 cuboid label (perm_v4 +
8 world corners + per-frame dims) into 12 front-face keypoints:

    outer 4  = the FRONT side-face cuboid corners (FTL, FTR, FBR, FBL)
    opening 8 = 2 fork-opening rectangles x 4 corners, placed from INTRINSIC
                (dimensionless) ratios scaled by the per-frame actual face size.

Only DIMENSIONLESS ratios are baked in (EFRONT_RATIOS); every absolute length is
taken from the per-frame cuboid at runtime, so ratio-robust dim augmentation is
respected automatically.

Physical-face resolution
------------------------
compute_perm_v4 assigns the FRONT face new-ids {0,1,2,3}. Which of the two
footprint axes that face spans is recovered *camera-independently* from perm:
the FRONT face's ORIGINAL canonical corner indices (get_pallet_geometry /
canonical_corners_yup order) form one of four fixed side-face sets:

    {0,1,2,3} or {4,5,6,7}  -> spans WIDTH  (face_axis 'W')   [normal = depth]
    {0,3,4,7} or {1,2,5,6}  -> spans DEPTH  (face_axis 'D')   [normal = width]

This is why P2 (near-square footprint, W/D differ 6 mm) is handled correctly:
validity is keyed on the PHYSICAL axis, not on which side happens to be marginally
longer this frame.

Source of the ratios: P0/P1 from data/pallet/archive/superseded_runs/_efront_12kp_check/efront_measurements.json
(measured read-only from the baked scene, 2026-07; rebuild via build_ratio_table_from_json).
P2/P3 were re-measured for the 2026-07 re-bake (P2=J-Toastie, P3=EUR replaced the
removed NoAI wood pallets) from the registry key pallet_measurements
(data/pallet/assets/pallets/source/pallets_v2_add/measurements.json) (a
different schema, so build_ratio_table_from_json does NOT regenerate the P2/P3 rows).
"""

import numpy as np

# ---------------------------------------------------------------------------
# INTRINSIC (dimensionless) opening-ratio table, keyed "P{id}|{face_axis}".
#   opW_ratio        = opening_width  / faceW
#   opH_ratio        = opening_height / faceH
#   side_margin_ratio= outer_margin   / faceW   (left edge of the left opening)
#   top_off_ratio    = (faceH - opening_top) / faceH   (deck offset from top)
#   u_center_ratios  = [left, right] opening centre u in [0,1] (mirror-symmetric)
#   bottom_open      = opening's lower edge sits on the floor (no bottom board)
# face_axis == the footprint axis the face SPANS ('W' width / 'D' depth).
# ---------------------------------------------------------------------------
EFRONT_RATIOS = {
    "P0|D": {"face_type": "long",  "valid": True, "n_openings": 2,
             "opW_ratio": 0.2079, "opH_ratio": 0.5585, "side_margin_ratio": 0.1985,
             "top_off_ratio": 0.2030, "bottom_open": False, "rect_fill_ratio": 0.996,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.3024, 0.6971]},
    "P0|W": {"face_type": "short", "valid": True, "n_openings": 2,
             "opW_ratio": 0.2549, "opH_ratio": 0.5901, "side_margin_ratio": 0.1412,
             "top_off_ratio": 0.2030, "bottom_open": False, "rect_fill_ratio": 0.996,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.2686, 0.7307]},
    "P1|D": {"face_type": "long",  "valid": True, "n_openings": 2,
             "opW_ratio": 0.2904, "opH_ratio": 0.7095, "side_margin_ratio": 0.1466,
             "top_off_ratio": 0.1820, "bottom_open": False, "rect_fill_ratio": 1.001,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.2918, 0.7076]},
    # P1 short face: fork enters between 3 feet, NO bottom board -> bottom_open.
    # feet are trapezoidal -> circumscribed rectangle (rect_fill 0.928, r~54mm).
    "P1|W": {"face_type": "short", "valid": True, "n_openings": 2,
             "opW_ratio": 0.3152, "opH_ratio": 0.8180, "side_margin_ratio": 0.1084,
             "top_off_ratio": 0.1820, "bottom_open": True, "rect_fill_ratio": 0.928,
             "corner_radius_mm": 54.0, "u_center_ratios": [0.2660, 0.7334]},
    # P2 = J-Toastie 4-way BLOCK pallet (CC-BY 3.0, wood-textured). Replaced the removed
    # NoAI "Old Wooden Pallet" in the 2026-07 re-bake. Both face pairs are open 4-way
    # (n_openings=2 each -> both valid). Ratios from pallets_v2_add/measurements.json
    # (WOODBLOCK_jtoastie); canonicalization-invariant (rigid rot + uniform scale).
    # Face mapping (W=canonical X, D=canonical Z): measurement face_A_normalW_spansD ->
    # P2|D (spans DEPTH=Z, long footprint edge, has bottom deck board -> bottom_open=False);
    # face_B_normalD_spansW -> P2|W (spans WIDTH=X, short edge, fork tunnels floor-open).
    "P2|D": {"face_type": "long",  "valid": True, "n_openings": 2,
             "opW_ratio": 0.270, "opH_ratio": 0.661, "side_margin_ratio": 0.150,
             "top_off_ratio": 0.202, "bottom_open": False, "rect_fill_ratio": 1.0,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.287, 0.713]},
    "P2|W": {"face_type": "short", "valid": True, "n_openings": 2,
             "opW_ratio": 0.304, "opH_ratio": 0.688, "side_margin_ratio": 0.123,
             "top_off_ratio": 0.312, "bottom_open": True, "rect_fill_ratio": 1.0,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.277, 0.726]},
    # P3 = EUR/EPAL 4-way BLOCK pallet (CC0, wood texture + EPAL stamp). Replaced the
    # removed NoAI wood pallet. Metric 800x1200x144 mm. Both faces open (n_openings=2).
    # Ratios from pallets_v2_add/measurements.json (EURPALLET_blenderkit). Face mapping
    # (W=canonical X, D=canonical Z): face_A_normalW_spansD -> P3|D (spans DEPTH=Z, the
    # 1200 mm long edge, bottom board present -> bottom_open=False); face_B_normalD_spansW
    # -> P3|W (spans WIDTH=X, the 800 mm short edge, floor-open fork tunnels).
    "P3|D": {"face_type": "long",  "valid": True, "n_openings": 2,
             "opW_ratio": 0.319, "opH_ratio": 0.679, "side_margin_ratio": 0.120,
             "top_off_ratio": 0.156, "bottom_open": False, "rect_fill_ratio": 1.0,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.280, 0.721]},
    "P3|W": {"face_type": "short", "valid": True, "n_openings": 2,
             "opW_ratio": 0.262, "opH_ratio": 0.697, "side_margin_ratio": 0.145,
             "top_off_ratio": 0.303, "bottom_open": True, "rect_fill_ratio": 1.0,
             "corner_radius_mm": 0.0, "u_center_ratios": [0.276, 0.724]},
}

# FRONT face original-canonical index sets (canonical_corners_yup order).
_WIDTH_SPAN_SETS = (frozenset({0, 1, 2, 3}), frozenset({4, 5, 6, 7}))
_DEPTH_SPAN_SETS = (frozenset({0, 3, 4, 7}), frozenset({1, 2, 5, 6}))

# 12kp semantic labels + a suggested colour scheme (BGR) for overlays.
KP12_LABELS = ["out_TL", "out_TR", "out_BR", "out_BL",
               "L_TL", "L_TR", "L_BR", "L_BL",
               "R_TL", "R_TR", "R_BR", "R_BL"]
KP12_COLORS_BGR = [(0, 0, 255)] * 4 + [(0, 255, 0)] * 4 + [(255, 128, 0)] * 4
# 12kp edges (outer rect + 2 opening rects) for wireframe overlays.
KP12_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0),
              (4, 5), (5, 6), (6, 7), (7, 4),
              (8, 9), (9, 10), (10, 11), (11, 8)]


def _norm_pid(pallet_id):
    s = str(pallet_id)
    if s.startswith("Pallet_"):
        return "P" + s.split("_", 1)[1]
    return s


def front_face_axis_from_perm(perm):
    """Recover the physical footprint axis the FRONT face spans from perm_v4.

    Returns 'W', 'D', or None (if the front id-set is not a recognised side face)."""
    perm = [int(p) for p in perm]
    front = frozenset(perm[:4])
    if front in _WIDTH_SPAN_SETS:
        return "W"
    if front in _DEPTH_SPAN_SETS:
        return "D"
    return None


def _project(points_world, K, R_w2c, t_w2c):
    """Project (N,3) world points -> (N,2) pixels using the pipeline convention
    (same as compute_annotation_v4): x_cam = R_w2c @ X + t_w2c ; uv = K x_cam / z."""
    P = np.asarray(points_world, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    R = np.asarray(R_w2c, dtype=np.float64)
    t = np.asarray(t_w2c, dtype=np.float64).reshape(3)
    cam = (R @ P.T).T + t
    proj = (K @ cam.T).T
    z = proj[:, 2:3]
    z_safe = np.where(np.abs(z) < 1e-9, 1e-9, z)
    return proj[:, :2] / z_safe, cam[:, 2]


def _bilinear_face(BL, BR, TL, TR, uf, vf):
    """Point on the planar FRONT-face rectangle. uf: 0=left..1=right, vf: 0=floor..1=top."""
    bottom = (1.0 - uf) * BL + uf * BR
    top = (1.0 - uf) * TL + uf * TR
    return (1.0 - vf) * bottom + vf * top


def build_kp12_3d(front_corners_world, ratios):
    """12 world keypoints from the 4 FRONT-face corners + intrinsic ratios.

    front_corners_world: (4,3) in v4 FRONT order [FTL, FTR, FBR, FBL]."""
    C = np.asarray(front_corners_world, dtype=np.float64)
    TL, TR, BR, BL = C[0], C[1], C[2], C[3]

    sm = ratios["side_margin_ratio"]
    ow = ratios["opW_ratio"]
    to = ratios["top_off_ratio"]
    oh = ratios["opH_ratio"]
    bottom_open = ratios["bottom_open"]

    vf_top = 1.0 - to
    vf_bot = 0.0 if bottom_open else (1.0 - to - oh)

    # left opening u-fractions, right opening = mirror about u=0.5
    uf_pairs = [(sm, sm + ow), (1.0 - sm - ow, 1.0 - sm)]

    pts = [TL, TR, BR, BL]                     # outer 4
    for uf_lo, uf_hi in uf_pairs:              # each opening: TL,TR,BR,BL
        pts.append(_bilinear_face(BL, BR, TL, TR, uf_lo, vf_top))
        pts.append(_bilinear_face(BL, BR, TL, TR, uf_hi, vf_top))
        pts.append(_bilinear_face(BL, BR, TL, TR, uf_hi, vf_bot))
        pts.append(_bilinear_face(BL, BR, TL, TR, uf_lo, vf_bot))
    return np.array(pts, dtype=np.float64)     # (12,3)


def compute_efront_kp12(pallet_id, cuboid_corners_world, perm, K, R_w2c, t_w2c,
                        actual_face_dims=None, image_wh=None, raycast_fn=None):
    """Build the E-front 12 keypoints for one labelled pallet instance.

    Args
      pallet_id            'P0'..'P3' or 'Pallet_0'..'Pallet_3'.
      cuboid_corners_world (8,3) world cuboid corners in v4 order (label 'cuboid').
      perm                 perm_v4 (len-8): perm[k] = original index of v4-id k.
      K, R_w2c, t_w2c      camera (same convention as compute_annotation_v4).
      actual_face_dims     optional {'width','height','depth'} (label dimensions_m);
                           if None, derived from the cuboid. Used only to derive
                           front_face_type (long/short); geometry uses the corners.
      image_wh             optional (W,H) to compute kp12_in_frame.
      raycast_fn           optional callable(pts_world)->bool[N] for kp12_visible.

    Returns dict:
      kp12_2d, kp12_3d, kp12_valid, front_face_axis, front_face_type,
      kp12_in_frame, kp12_visible, opening_meta, ratios_used
    """
    pid = _norm_pid(pallet_id)
    C = np.asarray(cuboid_corners_world, dtype=np.float64)

    axis = front_face_axis_from_perm(perm)
    # FRONT face corners are always v4 ids 0..3 (FTL, FTR, FBR, FBL)
    front_corners = C[[0, 1, 2, 3]]
    faceW = float(np.linalg.norm(front_corners[1] - front_corners[0]))
    faceH = float(np.linalg.norm(front_corners[0] - front_corners[3]))

    if actual_face_dims is not None:
        w = float(actual_face_dims.get("width", faceW))
        d = float(actual_face_dims.get("depth", faceW))
    else:
        w = faceW
        d = float(np.linalg.norm(C[4] - C[0]))       # front->rear edge
    front_face_type = "long" if w >= d else "short"

    key = f"{pid}|{axis}" if axis is not None else None
    ratios = EFRONT_RATIOS.get(key)

    result = {
        "kp12_valid": False,
        "front_face_axis": axis,
        "front_face_type": front_face_type,
        "faceW_m": faceW, "faceH_m": faceH,
        "kp12_2d": None, "kp12_3d": None,
        "kp12_in_frame": None, "kp12_visible": None,
        "opening_meta": None, "ratios_used": key,
    }

    if axis is None:
        result["opening_meta"] = {"reason": "front id-set is not a side face (perm anomaly)"}
        return result
    if ratios is None or not ratios.get("valid", False):
        result["opening_meta"] = {
            "reason": f"{pid} {axis}-span face has no enclosed opening (n_openings="
                      f"{(ratios or {}).get('n_openings', '?')})",
            "n_openings": (ratios or {}).get("n_openings", 0),
        }
        return result

    kp12_3d = build_kp12_3d(front_corners, ratios)
    kp12_2d, _z = _project(kp12_3d, K, R_w2c, t_w2c)

    in_frame = None
    if image_wh is not None:
        W, H = image_wh
        in_frame = ((kp12_2d[:, 0] >= 0) & (kp12_2d[:, 0] < W) &
                    (kp12_2d[:, 1] >= 0) & (kp12_2d[:, 1] < H))
    visible = None
    if raycast_fn is not None:
        visible = np.asarray(raycast_fn(kp12_3d), dtype=bool)

    fill = ratios["rect_fill_ratio"]
    result.update({
        "kp12_valid": True,
        "kp12_3d": kp12_3d,
        "kp12_2d": kp12_2d,
        "kp12_in_frame": in_frame,
        "kp12_visible": visible,
        "opening_meta": {
            "bottom_open": bool(ratios["bottom_open"]),
            "rect_fill_ratio": float(fill),
            "corner_radius_mm": float(ratios["corner_radius_mm"]),
            "convention": ratios.get("convention") or
                          ("circumscribed_rect" if fill < 0.98 else "rect"),
            "n_openings": 2,
            "axis_residual_note": ratios.get("axis_residual_note"),
        },
        "ratios_used": key,
    })
    return result


def efront_result_to_json(res):
    """JSON-serialisable view of a compute_efront_kp12() result (numpy -> lists)."""
    def _l(a):
        return None if a is None else np.asarray(a).tolist()
    return {
        "kp12_valid": bool(res["kp12_valid"]),
        "front_face_axis": res["front_face_axis"],
        "front_face_type": res["front_face_type"],
        "faceW_m": float(res["faceW_m"]),
        "faceH_m": float(res["faceH_m"]),
        "kp12_2d": _l(res["kp12_2d"]),
        "kp12_3d": _l(res["kp12_3d"]),
        "kp12_in_frame": None if res["kp12_in_frame"] is None
                         else [bool(x) for x in res["kp12_in_frame"]],
        "kp12_visible": None if res["kp12_visible"] is None
                        else [bool(x) for x in res["kp12_visible"]],
        "opening_meta": res["opening_meta"],
        "ratios_used": res["ratios_used"],
    }


def build_ratio_table_from_json(json_path):
    """Reproducibility helper: recompute EFRONT_RATIOS from efront_measurements.json."""
    import json
    recs = json.load(open(json_path))
    table = {}
    for r in recs:
        pid = r["pallet_id"]; ax = r["face_axis"]
        fw, fh = r["face_width_m"], r["face_height_m"]
        if r["n_openings"] != 2:
            table[f"{pid}|{ax}"] = {"face_type": r["face"], "valid": False,
                                    "n_openings": r["n_openings"]}
            continue
        o0, o1 = sorted(r["openings"], key=lambda o: o["u_min"])
        opW = o0["u_max"] - o0["u_min"]; opH = o0["v_max"] - o0["v_min"]
        table[f"{pid}|{ax}"] = {
            "face_type": r["face"], "valid": True, "n_openings": 2,
            "opW_ratio": opW / fw, "opH_ratio": opH / fh,
            "side_margin_ratio": (o0["u_min"] + fw / 2) / fw,
            "top_off_ratio": (fh - o0["v_max"]) / fh,
            "bottom_open": bool(o0["bottom_open"]),
            "rect_fill_ratio": min(o0["rect_fill_ratio"], o1["rect_fill_ratio"]),
            "corner_radius_mm": max(o0["corner_radius_mm"], o1["corner_radius_mm"]),
            "u_center_ratios": [((o0["u_min"] + o0["u_max"]) / 2 + fw / 2) / fw,
                                ((o1["u_min"] + o1["u_max"]) / 2 + fw / 2) / fw],
        }
    return table
