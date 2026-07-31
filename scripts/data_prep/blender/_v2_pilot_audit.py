"""v2 규약 PILOT 2k — audit (bpy-FREE, base python: PIL + numpy).

Reads the pilot render (data/pallet/archive/superseded_runs/_v2_pilot_2k: pilot_records.json + labels/ + rgb/ + mask/)
and runs the task audit item-by-item. Produces overlays + a machine report. NO Blender, NO
render, NO commit. Uses only the on-disk labels/masks/rgb.

Items (priority order):
  W  live-label wiring : f_actual_bin + noise_scale present & non-trivial; G5 == visible-luma.
  H1 perm azimuth      : elev_bin 6 (60-80deg) 9kp overlays (FRONT face highlighted) +
                         front_is_camera_near computed for ALL frames.
  H2 outdoor-night     : night G5 survival + pallet-region visible luma + G5 discard BEFORE
                         (luma_frame&unocc) vs AFTER (visible) recomputed from disk masks.
  M1 12kp              : efront_kp12 applied to labels, all pallets x face-axis, extreme dims;
                         12-point overlays following the fork openings.
  M2 occlusion_fraction: per-corner values are CONTINUOUS in (0,1), not binary.
  M3 luma_actual       : dark bin (<35) coverage + noise_scale<->luma coupling.
  S  standard          : prescription==measured +-2%p / reproj p99 / connector_cross 0 /
                         empty_mask 0 / front_is_camera_near 100%.

Run:
  C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/_v2_pilot_audit.py \
      --dir data/pallet/archive/superseded_runs/_v2_pilot_2k [--n_overlay 30]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import v2_pipeline as vp                 # noqa: E402  (bpy-free)
from blender_math import build_view_matrix  # noqa: E402  (bpy-free)
import efront_kp12 as ek                 # noqa: E402  (bpy-free)


# ---------------------------------------------------------------------------
def _load_records(d):
    p = os.path.join(d, "pilot_records.json")
    if os.path.isfile(p):
        recs = json.load(open(p, encoding="utf-8"))
    else:  # fall back to the streaming jsonl
        recs = []
        jp = os.path.join(d, "pilot_records.jsonl")
        seen = {}
        for line in open(jp, encoding="utf-8"):
            try:
                r = json.loads(line)
                seen[r["idx"]] = r
            except Exception:
                pass
        recs = [seen[k] for k in sorted(seen)]
    return [r for r in recs if r.get("realize_ok")]


def _label_path(d, idx):
    return os.path.join(d, "labels", f"f{idx:04d}_label.json")


def _rgb_path(d, idx):
    return os.path.join(d, "rgb", f"f{idx:04d}_rgb.png")


def _load_label(d, idx):
    p = _label_path(d, idx)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def _K_Rt_from_label(lab):
    cam = lab["camera_data"]
    K = np.array([[cam["intrinsics"]["fx"], 0, cam["intrinsics"]["cx"]],
                  [0, cam["intrinsics"]["fy"], cam["intrinsics"]["cy"]],
                  [0, 0, 1]], dtype=np.float64)
    R, t = build_view_matrix(np.array(cam["location_worldframe"]),
                             np.array(cam["look_worldframe"]), up=(0, 0, 1))
    return K, R, np.asarray(t, dtype=np.float64).reshape(3)


# ---------------------------------------------------------------------------
# 9kp cuboid overlay (FRONT face 0-1-2-3 highlighted -> eyeball camera-facing).
_FRONT_E = [(0, 1), (1, 2), (2, 3), (3, 0)]
_REAR_E = [(4, 5), (5, 6), (6, 7), (7, 4)]
_CONN_E = [(0, 4), (1, 5), (2, 6), (3, 7)]


def _draw_cuboid_overlay(d, idx, lab, out_path, tag=""):
    rgb = _rgb_path(d, idx)
    if not os.path.isfile(rgb):
        return False
    im = Image.open(rgb).convert("RGB")
    dr = ImageDraw.Draw(im)
    obj = lab["objects"][0]
    pc = obj["projected_cuboid"]
    cc = obj["projected_cuboid_centroid"]

    def L(a, b, col, w=3):
        dr.line([tuple(pc[a]), tuple(pc[b])], fill=col, width=w)

    for a, b in _REAR_E:
        L(a, b, (60, 120, 255), 2)      # rear = blue
    for a, b in _CONN_E:
        L(a, b, (255, 210, 0), 2)       # connectors = yellow
    for a, b in _FRONT_E:
        L(a, b, (255, 30, 30), 4)       # FRONT = thick red
    for k, (x, y) in enumerate(pc):
        col = (255, 30, 30) if k < 4 else (60, 120, 255)
        dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=col, outline=(255, 255, 255))
        dr.text((x + 6, y - 6), str(k), fill=(255, 255, 0))
    dr.ellipse([cc[0] - 4, cc[1] - 4, cc[0] + 4, cc[1] + 4], fill=(0, 255, 0))
    fc = obj.get("front_visibility_cos")
    fm = obj.get("facing_margin")
    vl = obj["v2_labels"]
    hdr = (f"f{idx} {obj['name']} elevA={vl['elevation_deg_actual']} az={vl['azimuth_deg_target']} "
           f"fcos={fc} fmarg={fm} {tag}")
    dr.rectangle([0, 0, im.width, 16], fill=(0, 0, 0))
    dr.text((3, 3), hdr, fill=(255, 255, 255))
    im.save(out_path)
    return True


def _front_is_camera_near(lab):
    """FRONT face (cuboid 0-3) centroid nearer to camera than REAR (4-7)?"""
    obj = lab["objects"][0]
    C = np.array(obj["cuboid"], dtype=np.float64)
    cam = np.array(lab["camera_data"]["location_worldframe"], dtype=np.float64)
    df = np.linalg.norm(C[:4].mean(0) - cam)
    dr = np.linalg.norm(C[4:].mean(0) - cam)
    return bool(df < dr), float(df), float(dr)


def _seg_int(p1, p2, p3, p4):
    """Proper segment intersection (excluding shared endpoints)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    if len({tuple(p1), tuple(p2), tuple(p3), tuple(p4)}) < 4:
        return False
    d1 = ccw(p3, p4, p1); d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3); d4 = ccw(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _connector_crossings(pc):
    """# of connector-connector (0-4,1-5,2-6,3-7) 2D crossings."""
    segs = [(pc[a], pc[b]) for a, b in _CONN_E]
    n = 0
    for i in range(4):
        for j in range(i + 1, 4):
            if _seg_int(segs[i][0], segs[i][1], segs[j][0], segs[j][1]):
                n += 1
    return n


# ---------------------------------------------------------------------------
def _mask_luma(rgb_arr_L, mask_path):
    if not os.path.isfile(mask_path):
        return None
    mk = np.array(Image.open(mask_path).convert("L")) > 127
    if mk.shape != rgb_arr_L.shape or mk.sum() == 0:
        return None
    return float(rgb_arr_L[mk].mean())


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/pallet/archive/superseded_runs/_v2_pilot_2k")
    ap.add_argument("--n_overlay", type=int, default=30)
    args = ap.parse_args()
    d = args.dir if os.path.isabs(args.dir) else os.path.join(
        os.path.abspath(os.path.join(_THIS, "..", "..", "..")), args.dir)
    aud = os.path.join(d, "audit")
    for sub in ("overlay_perm_azimuth", "overlay_night", "overlay_kp12"):
        os.makedirs(os.path.join(aud, sub), exist_ok=True)

    recs = _load_records(d)
    N = len(recs)
    print(f"[AUDIT] rendered frames = {N}")
    rep = {"n_rendered": N}

    # ================= W. live-label wiring =================
    fab = [r.get("f_actual_bin") for r in recs]
    fab_present = sum(1 for x in fab if x is not None)
    fab_bins = {b: sum(1 for x in fab if x == b) for b in (0, 1, 2, 3)}
    # f_actual_bin is None IFF f_total is None (unmeasurable mask) — a legitimate case, not a
    # wiring failure. Consistency = for every frame, (f_total None) == (f_actual_bin None).
    fab_consistent = sum(1 for r in recs
                         if (r.get("f_total_meas") is None) == (r.get("f_actual_bin") is None))
    f_total_none = sum(1 for r in recs if r.get("f_total_meas") is None)
    ns = [r.get("noise_scale") for r in recs if r.get("noise_scale") is not None]
    # noise formula check
    ns_ok = 0; ns_bad = 0
    for r in recs:
        lf = r.get("luma_frame"); nsv = r.get("noise_scale")
        if lf is None or nsv is None:
            continue
        exp = 1.0 + max(0.0, (60.0 - lf) / 60.0) * 1.5
        if abs(exp - nsv) < 1e-2:
            ns_ok += 1
        else:
            ns_bad += 1
    # G5 == visible-luma rule
    g5_bad = 0
    for r in recs:
        lp = r.get("luma_pallet")
        g5 = r["gates"]["G5_luma_floor"]
        if g5 != (lp is None or lp >= 12.0):
            g5_bad += 1
    rep["W_live_label"] = {
        "f_actual_bin_present": f"{fab_present}/{N}", "f_actual_bin_bins": fab_bins,
        "f_actual_bin_consistent_with_f_total": f"{fab_consistent}/{N}",
        "f_total_none_unmeasurable": f_total_none,
        "noise_scale_present": len(ns), "noise_scale_min": (round(min(ns), 3) if ns else None),
        "noise_scale_max": (round(max(ns), 3) if ns else None),
        "noise_formula_ok": ns_ok, "noise_formula_bad": ns_bad,
        "g5_visible_rule_mismatch": g5_bad,
        "PASS": bool(fab_consistent == N and len(ns) == N and ns_bad == 0 and g5_bad == 0),
    }
    print(f"[W] f_actual_bin present {fab_present}/{N} (consistent {fab_consistent}/{N}, "
          f"f_total None={f_total_none}) bins={fab_bins} | noise {len(ns)}/{N} "
          f"range[{rep['W_live_label']['noise_scale_min']},{rep['W_live_label']['noise_scale_max']}] "
          f"formula_bad={ns_bad} | G5_mismatch={g5_bad} -> PASS={rep['W_live_label']['PASS']}")

    # ================= S. standard: front_is_camera_near / connector / empty_mask =====
    fnear_ok = 0; fnear_tot = 0; conn_cross_frames = 0; empty_mask = 0
    empty_mask_gatefail = 0
    reproj_p99_list = []
    for r in recs:
        idx = r["idx"]
        lab = _load_label(d, idx)
        if lab is None:
            continue
        fnear_tot += 1
        near, dfr, drr = _front_is_camera_near(lab)
        if near:
            fnear_ok += 1
        pc = lab["objects"][0]["projected_cuboid"]
        if _connector_crossings(pc) > 0:
            conn_cross_frames += 1
        if not r.get("mask_area_unocc"):
            empty_mask += 1
            if not r["gates"]["all_pass"]:
                empty_mask_gatefail += 1
        # reproj consistency: reproject label cuboid via rebuilt K,R,t vs stored projected_cuboid
        K, R, t = _K_Rt_from_label(lab)
        C = np.array(lab["objects"][0]["cuboid"], dtype=np.float64)
        cam = (R @ C.T).T + t
        uv = (K @ cam.T).T
        uv = uv[:, :2] / uv[:, 2:3]
        err = np.linalg.norm(uv - np.array(pc), axis=1)
        reproj_p99_list.append(float(err.max()))
    reproj_p99 = float(np.percentile(reproj_p99_list, 99)) if reproj_p99_list else None
    rep["S_standard"] = {
        "front_is_camera_near": f"{fnear_ok}/{fnear_tot}",
        "front_near_frac": round(fnear_ok / max(1, fnear_tot), 4),
        "connector_cross_frames": conn_cross_frames,
        "empty_mask_frames": empty_mask,
        "empty_mask_gate_rejected": empty_mask_gatefail,
        "reproj_p99_px": (round(reproj_p99, 4) if reproj_p99 is not None else None),
    }
    print(f"[S] front_is_camera_near {fnear_ok}/{fnear_tot} "
          f"({rep['S_standard']['front_near_frac']*100:.1f}%) | connector_cross {conn_cross_frames} "
          f"| empty_mask {empty_mask} (gate-rejected {empty_mask_gatefail}) "
          f"| reproj_p99 {rep['S_standard']['reproj_p99_px']}px")

    # ---- prescription vs measured (accept-set spec axes) +-2%p ----
    def frac(counts):
        tot = sum(counts.values())
        return {k: (v / tot if tot else 0.0) for k, v in counts.items()}

    def tally(key):
        c = {}
        for r in recs:
            c[r.get(key)] = c.get(r.get(key), 0) + 1
        return c

    presc = {
        "scene_preset": dict(zip(vp.SCENE_PRESETS, vp.SCENE_PRESET_FRAC)),
        "f_target_bin": {i: f for i, f in enumerate(vp.F_TARGET_FRAC)},
        "elev_bin": {i: f for i, f in enumerate(vp.ELEV_BIN_FRAC)},
        "v_target": dict(zip(vp.V_VALUES, vp.V_FRAC)),
        "aspect": dict(zip([a for a, _ in vp.ASPECTS], vp.ASPECT_FRAC)),
        "fx_mode": dict(zip(vp.FX_MODES, vp.FX_FRAC)),
        "proj_size_bin": {i: f for i, f in enumerate(vp.PROJ_SIZE_FRAC)},
    }
    presc_rep = {}
    for axis, pr in presc.items():
        meas = frac(tally(axis))
        worst = 0.0; rows = {}
        for k, pf in pr.items():
            mf = meas.get(k, 0.0)
            worst = max(worst, abs(mf - pf))
            rows[str(k)] = {"presc": round(pf, 4), "meas": round(mf, 4),
                            "dpp": round((mf - pf) * 100, 2)}
        presc_rep[axis] = {"rows": rows, "max_abs_dpp": round(worst * 100, 2),
                           "within_2pp": bool(worst <= 0.02)}
    rep["S_prescription"] = presc_rep
    print("[S] prescription vs measured (max |Δ| percentage-points, want <=2.0):")
    for axis, v in presc_rep.items():
        print(f"     {axis:14s} maxΔ={v['max_abs_dpp']:5.2f}pp  within2pp={v['within_2pp']}")

    # ================= M2. occlusion_fraction continuous =================
    allof = []
    for r in recs:
        of = r.get("occlusion_fraction")
        if of:
            allof.extend([x for x in of if x is not None])
    allof = np.array(allof) if allof else np.array([])
    if allof.size:
        strict = int(((allof > 1e-6) & (allof < 1 - 1e-6)).sum())
        rep["M2_occlusion_fraction"] = {
            "n_values": int(allof.size),
            "n_strictly_between_0_1": strict,
            "frac_continuous": round(strict / allof.size, 4),
            "n_zero": int((allof <= 1e-6).sum()), "n_one": int((allof >= 1 - 1e-6).sum()),
            "distinct_values": int(np.unique(np.round(allof, 4)).size),
            "CONTINUOUS": bool(strict > 0 and np.unique(np.round(allof, 4)).size > 3),
        }
        print(f"[M2] occlusion_fraction: {strict}/{allof.size} strictly in (0,1), "
              f"{rep['M2_occlusion_fraction']['distinct_values']} distinct -> "
              f"CONTINUOUS={rep['M2_occlusion_fraction']['CONTINUOUS']}")

    # ================= M3. luma_actual dark bin + noise coupling =================
    lumas = [r.get("luma_frame") for r in recs if r.get("luma_frame") is not None]
    fr, passes, allp = vp.audit_luma_actual(lumas) if lumas else ([], [], False)
    dark = [r for r in recs if r.get("luma_frame") is not None and r["luma_frame"] < 35]
    dark_noise_up = sum(1 for r in dark if (r.get("noise_scale") or 0) > 1.0)
    rep["M3_luma"] = {
        "luma_bins_frac": {lab: round(f, 4) for lab, f in zip(vp.LUMA_ACTUAL_LABELS, fr)},
        "coverage_pass": {lab: bool(p) for lab, p in zip(vp.LUMA_ACTUAL_LABELS, passes)},
        "dark_lt35_count": len(dark),
        "dark_noise_scaled_up": f"{dark_noise_up}/{len(dark)}",
    }
    print(f"[M3] luma bins {rep['M3_luma']['luma_bins_frac']} | dark<35 n={len(dark)} "
          f"noise>1 {dark_noise_up}/{len(dark)}")

    # ================= H2. outdoor-night G5 before/after =================
    night = [r for r in recs if r.get("scene_preset") == "outdoor-night"]
    old_reject = 0; new_reject = 0; vis_bright = 0; n_measurable = 0
    for r in night:
        idx = r["idx"]
        rgb = _rgb_path(d, idx)
        if not os.path.isfile(rgb):
            continue
        arrL = np.array(Image.open(rgb).convert("L")).astype(np.float32)
        lu = _mask_luma(arrL, os.path.join(d, "mask", f"f{idx:04d}_unocc.png"))
        lv = _mask_luma(arrL, os.path.join(d, "mask", f"f{idx:04d}_visible.png"))
        lf = r.get("luma_frame")
        # OLD rule (pre-fix): luma_frame>=12 AND unocc-mask luma>=12
        old_g5 = (lf is not None and lf >= 12.0) and (lu is not None and lu >= 12.0)
        # NEW rule (fix): visible-mask luma None or >=12
        new_g5 = (lv is None or lv >= 12.0)
        n_measurable += 1
        if not old_g5:
            old_reject += 1
        if not new_g5:
            new_reject += 1
        if lv is not None and lv >= 12.0:
            vis_bright += 1
    rep["H2_night_g5"] = {
        "n_night": len(night), "n_measurable": n_measurable,
        "g5_reject_BEFORE_frame&unocc": (round(old_reject / n_measurable, 4) if n_measurable else None),
        "g5_reject_AFTER_visible": (round(new_reject / n_measurable, 4) if n_measurable else None),
        "night_G5_pass_frac": round(sum(r["gates"]["G5_luma_floor"] for r in night) / max(1, len(night)), 4),
        "night_all_pass_frac": round(sum(r["gates"]["all_pass"] for r in night) / max(1, len(night)), 4),
        "night_visible_pallet_bright_frac": (round(vis_bright / n_measurable, 4) if n_measurable else None),
    }
    print(f"[H2] night n={len(night)}: G5 reject BEFORE={rep['H2_night_g5']['g5_reject_BEFORE_frame&unocc']} "
          f"AFTER={rep['H2_night_g5']['g5_reject_AFTER_visible']} | "
          f"night G5 pass={rep['H2_night_g5']['night_G5_pass_frac']} "
          f"visible-bright={rep['H2_night_g5']['night_visible_pallet_bright_frac']}")

    # night overlays (prefer G5-pass night frames so the pallet is actually visible)
    night_sorted = sorted(night, key=lambda r: (not r["gates"]["all_pass"], r["idx"]))
    no = 0
    for r in night_sorted:
        if no >= args.n_overlay:
            break
        lab = _load_label(d, r["idx"])
        if lab is None:
            continue
        op = os.path.join(aud, "overlay_night", f"f{r['idx']:04d}_night.png")
        if _draw_cuboid_overlay(d, r["idx"], lab, op,
                                tag=f"lumaP={r.get('luma_pallet')} G5={r['gates']['G5_luma_floor']} all={r['gates']['all_pass']}"):
            no += 1
    rep["H2_night_g5"]["overlay_dir"] = os.path.join(aud, "overlay_night")
    rep["H2_night_g5"]["n_overlay"] = no

    # ================= H1. perm azimuth (elev_bin 6, 60-80deg) =================
    eb6 = [r for r in recs if r.get("elev_bin") == 6]
    # spread azimuth bins for coverage
    eb6_sorted = sorted(eb6, key=lambda r: (r.get("azimuth_bin", 0), r["idx"]))
    po = 0
    for r in eb6_sorted:
        if po >= args.n_overlay:
            break
        lab = _load_label(d, r["idx"])
        if lab is None:
            continue
        near, dfr, drr = _front_is_camera_near(lab)
        op = os.path.join(aud, "overlay_perm_azimuth", f"f{r['idx']:04d}_elev6_az{r.get('azimuth_bin')}.png")
        if _draw_cuboid_overlay(d, r["idx"], lab, op, tag=f"frontNear={near}"):
            po += 1
    rep["H1_perm_azimuth"] = {
        "n_elev_bin6": len(eb6),
        "front_near_frac_all": rep["S_standard"]["front_near_frac"],
        "overlay_dir": os.path.join(aud, "overlay_perm_azimuth"),
        "n_overlay": po,
    }
    print(f"[H1] elev_bin6 n={len(eb6)} overlays={po} -> {os.path.join(aud, 'overlay_perm_azimuth')}")

    # ================= M1. 12kp (efront) all pallets x face-axis =========
    # group by (pallet, front_face_axis). NOTE: the render scales every pallet to canonical
    # dims (no per-frame ratio DR); efront uses per-frame actual dims so it is ratio-robust by
    # construction. Pick per group the best-framed FRONTAL views (V=8 + high front_cos) so the
    # fork openings are actually visible for the eyeball check.
    groups = {}
    for r in recs:
        lab = _load_label(d, r["idx"])
        if lab is None:
            continue
        obj = lab["objects"][0]
        axis = ek.front_face_axis_from_perm(obj["perm_v4"])
        gk = f"{obj['name']}|{axis}"
        fcos = obj.get("front_visibility_cos") or 0.0
        # quality: all 8 corners in frame first, then most front-facing.
        qual = (r.get("V_actual", 0) == 8, fcos)
        groups.setdefault(gk, []).append((qual, r["idx"]))
    kp12_summary = {}
    ko = 0
    for gk, items in sorted(groups.items()):
        items.sort(key=lambda x: x[0], reverse=True)   # best-framed frontal first
        picks = [idx for _, idx in items[:3]]
        gk_valid = None
        for idx in picks:
            lab = _load_label(d, idx)
            obj = lab["objects"][0]
            K, R, t = _K_Rt_from_label(lab)
            res = ek.compute_efront_kp12(
                obj["name"], np.array(obj["cuboid"]), obj["perm_v4"], K, R, t,
                actual_face_dims=obj["dimensions_m"],
                image_wh=(lab["camera_data"]["width"], lab["camera_data"]["height"]))
            gk_valid = res["kp12_valid"]
            if not res["kp12_valid"]:
                continue
            # overlay
            im = Image.open(_rgb_path(d, idx)).convert("RGB")
            dr = ImageDraw.Draw(im)
            kp = res["kp12_2d"]
            cols = [(c[2], c[1], c[0]) for c in ek.KP12_COLORS_BGR]  # BGR->RGB
            for a, b in ek.KP12_EDGES:
                dr.line([tuple(kp[a]), tuple(kp[b])], fill=(255, 255, 255), width=1)
            for k, (x, y) in enumerate(kp):
                dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=cols[k], outline=(0, 0, 0))
            dims = obj["dimensions_m"]
            dr.rectangle([0, 0, im.width, 16], fill=(0, 0, 0))
            dr.text((3, 3), f"{gk} type={res['front_face_type']} "
                            f"W={dims['width']:.3f} D={dims['depth']:.3f} H={dims['height']:.3f}",
                    fill=(255, 255, 255))
            im.save(os.path.join(aud, "overlay_kp12", f"f{idx:04d}_{gk.replace('|','_')}.png"))
            ko += 1
        kp12_summary[gk] = {"n_frames": len(items), "kp12_valid": bool(gk_valid),
                            "picks": picks}
    rep["M1_kp12"] = {"groups": kp12_summary, "n_overlay": ko,
                      "overlay_dir": os.path.join(aud, "overlay_kp12")}
    print(f"[M1] kp12 groups: " + ", ".join(f"{g}:valid={v['kp12_valid']}" for g, v in kp12_summary.items()))
    print(f"[M1] kp12 overlays={ko} -> {os.path.join(aud, 'overlay_kp12')}")

    # dims spread (is ratio DR active?)
    ws = [_load_label(d, r["idx"])["objects"][0]["dimensions_m"] for r in recs[:min(N, 2000)]]
    wratio = np.array([w["width"] / max(w["depth"], 1e-6) for w in ws])
    rep["dims_ratio_spread"] = {"min": round(float(wratio.min()), 4),
                                "max": round(float(wratio.max()), 4),
                                "std": round(float(wratio.std()), 4)}
    print(f"[i] width/depth ratio spread min={wratio.min():.3f} max={wratio.max():.3f} std={wratio.std():.3f}")

    json.dump(rep, open(os.path.join(aud, "pilot_audit_report.json"), "w"), indent=2,
              default=lambda o: None)
    print(f"\n[AUDIT] report -> {os.path.join(aud, 'pilot_audit_report.json')}")


if __name__ == "__main__":
    main()
