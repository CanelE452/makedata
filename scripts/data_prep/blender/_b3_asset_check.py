"""B3 asset-check (<=10 frames): exercise realize/measure/gate/label on the PRODUCTION
blend and run the 3 mandatory checks. NOT the 200-frame calibration (Phase D).

  1) Distractors_v2 render-enable: force-enable + confirm an occluder actually renders.
  2) mask_unoccluded path: pallet-only mask must be NON-empty (it is the f_* denominator).
  3) floor x glTF magenta: force the floor magenta -> magenta ratio above threshold, AND a
     NEW (non-name-matching) warehouse ground is hidden by the GEOMETRIC detector.

Run:
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
      --python scripts/data_prep/blender/_b3_asset_check.py -- --out <dir> --seed 7000
"""
import argparse
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import bpy
import numpy as np
from PIL import Image, ImageDraw

import v2_pipeline as vp
import v2_realize as vr

CUBOID_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)]


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/pallet/runs/diagnostics/_v2_b3_check")
    p.add_argument("--seed", type=int, default=7000)
    p.add_argument("--n", type=int, default=6)
    return p.parse_args(argv)


def draw_overlay(rgb_path, ov_path, uv8, cent, title_lines):
    img = Image.open(rgb_path).convert("RGBA")
    d = ImageDraw.Draw(img)
    for i, j in CUBOID_EDGES:
        d.line([tuple(uv8[i]), tuple(uv8[j])], fill=(0, 255, 0, 220), width=2)
    for i in range(8):
        x, y = int(uv8[i][0]), int(uv8[i][1])
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 80, 0, 255), outline=(0, 0, 0, 255))
        d.text((x + 7, y - 8), str(i), fill=(255, 255, 0, 255))
    d.ellipse([int(cent[0]) - 5, int(cent[1]) - 5, int(cent[0]) + 5, int(cent[1]) + 5],
              fill=(255, 255, 255, 230), outline=(0, 0, 0, 255))
    y = 4
    for ln in title_lines:
        d.rectangle([(3, y), (3 + 8 * len(ln), y + 13)], fill=(0, 0, 0, 170))
        d.text((5, y), ln, fill=(0, 255, 255, 255))
        y += 14
    img.convert("RGB").save(ov_path)


def magenta_ratio(png):
    a = np.array(Image.open(png).convert("RGB")).astype(np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    mag = (R > 140) & (B > 140) & (G < 90)
    return float(mag.mean())


def run():
    args = _args()
    out = args.out if os.path.isabs(args.out) else os.path.join(
        os.path.abspath(os.path.join(_THIS, "..", "..", "..")), args.out)
    os.makedirs(out, exist_ok=True)
    import random as _r
    _r.seed(args.seed)  # reproducible bg/hdri/floor choices across runs
    gpu = vr.enable_gpu()
    print(f"[B3] gpu={gpu} out={out}")

    assets = vp.load_assets()
    # Generate more than we need so we can pick an occluder frame + a low-elev frame.
    plans, rej, qs, att = vp.generate_accepted(40, args.seed, assets)
    occ_plans = [p for p in plans if p.occluder is not None
                 and 1.0 < p.cam_distance_m < 6.0 and p.spec.proj_size_bin in (1, 2, 3)]
    lowel_plans = [p for p in plans if p.spec.elev_bin in (2, 3)
                   and 1.0 < p.cam_distance_m < 6.0 and p.spec.proj_size_bin in (2, 3)]
    mix_plans = [p for p in plans if 1.0 < p.cam_distance_m < 6.0
                 and p.spec.proj_size_bin in (1, 2, 3)]

    report = {"gpu": gpu, "frames": [], "checks": {}}
    frames_done = 0

    # CHECK 1a: prove force_distractors_v2_enabled() un-excludes the collection even when a
    # (re-baked) blend had EXCLUDED it — the silent-0-distractor risk the task warns about.
    lc = vr._find_layer_collection(vr.DIST_COLLECTION)
    excl_test = {"collection_found": lc is not None}
    if lc is not None:
        lc.exclude = True  # simulate a re-bake that excluded the pool
        info = vr.force_distractors_v2_enabled()
        excl_test.update({"was_excluded_before_force": bool(info.get("was_excluded")),
                          "excluded_after_force": bool(lc.exclude),
                          "n_dist_roots": info.get("n_dist_roots")})

    # ---- pipeline frames (mixed) : exercises realize/render/measure/gate/label ----
    chosen = []
    if occ_plans:
        chosen.append(("occ", occ_plans[0]))          # CHECK 1 target
    for p in mix_plans:
        if len(chosen) >= args.n:
            break
        if all(p is not q for _, q in chosen):
            chosen.append(("mix", p))

    unocc_all_nonempty = True
    check1_best = {"dist_only_area_px": 0}
    check1_occ_frames = []

    for tag, plan in chosen[:args.n]:
        idx = frames_done
        rs = vr.realize(plan, floor_mode="plane", place_occluder=True)
        if rs is None:
            print(f"[B3] frame {idx}: realize returned None (skip)")
            continue
        rgb = os.path.join(out, f"f{idx:02d}_rgb.png")
        rs["rgb_path"] = rgb
        rs["mask_prefix"] = os.path.join(out, f"f{idx:02d}")
        vr.render(rs, rgb, samples=16)
        meas = vr.measure(rs)
        gates = vr.safety_gates(meas, plan)
        lab = vr.label(plan.spec, plan, meas, rs)
        # sensor post (dark -> more noise), on a COPY so overlay uses the clean render.
        try:
            vr.render_post(rgb, args.seed + idx, meas.get("luma_frame") or 128)
        except Exception as e:
            print("  [warn] render_post:", e)
        # overlay
        uv8 = meas["uv8_v4"]
        ov = os.path.join(out, f"f{idx:02d}_overlay.png")
        draw_overlay(rgb, ov, uv8, meas["cent_uv"], [
            f"f{idx} {rs['pallet_name']} occ={rs['occluder'] is not None} floor={rs['floor_mode']}",
            f"Vtgt={plan.spec.v_target} Vact={meas['V_inframe']} Vvis={meas['V_vis']} extocc={meas['ext_occ_corners']}",
            f"ftgt={plan.spec.f_target:.2f} fcargo={meas.get('f_cargo')} focc={meas.get('f_occ')} ftot={meas.get('f_total')}",
            f"unocc={meas.get('area_unocc')} vis={meas.get('area_visible')} luma={meas.get('luma_frame')}",
            f"gatesPASS={gates['all_pass']} {[k for k,v in gates.items() if k!='all_pass' and not v]}",
        ])
        with open(os.path.join(out, f"f{idx:02d}_label.json"), "w") as f:
            json.dump(lab, f, indent=2)

        au = meas.get("area_unocc")
        if not (au and au > 0):
            unocc_all_nonempty = False

        # CHECK 1: distractor-only holdout white area when an occluder is placed. Aggregate
        # over ALL occluder frames (a single frame's occluder can project off-screen; the
        # collection-render fact is proven if ANY placed occluder renders visible pixels).
        dist_area = None
        if rs["occluder"] is not None:
            dpath = os.path.join(out, f"f{idx:02d}_distonly.png")
            dist_area, _ = vr._render_holdout(rs["scene"], rs["pallet"], dpath, only_white=rs["occluder"])
            check1_occ_frames.append({"frame": idx, "occluder": (plan.occluder or {}).get("name"),
                                      "dist_only_area_px": dist_area})
            if (dist_area or 0) > (check1_best.get("dist_only_area_px") or 0):
                check1_best = {"frame": idx, "occluder": (plan.occluder or {}).get("name"),
                               "dist_only_area_px": dist_area,
                               "overlay": os.path.basename(ov), "rgb": os.path.basename(rgb)}
        report["frames"].append({
            "idx": idx, "tag": tag, "pallet": rs["pallet_name"],
            "occluder_placed": rs["occluder"] is not None,
            "occluder_asset": (plan.occluder or {}).get("name") if plan.occluder else None,
            "dist_only_area_px": dist_area,
            "floor_mode": rs["floor_mode"], "ground_hidden": rs["ground_hidden"][0],
            "res": [rs["W"], rs["H"]], "fx": round(float(rs["K"][0, 0]), 1),
            "V_target": plan.spec.v_target, "V_actual": meas["V_inframe"], "V_vis": meas["V_vis"],
            "ext_occ": meas["ext_occ_corners"], "occ_frac": meas["occlusion_fraction"],
            "f_target": round(plan.spec.f_target, 3), "f_cargo": meas.get("f_cargo"),
            "f_occ": meas.get("f_occ"), "f_total": meas.get("f_total"),
            "area_unocc": meas.get("area_unocc"), "area_visible": meas.get("area_visible"),
            "luma": meas.get("luma_frame"), "luma_pallet": meas.get("luma_pallet"),
            "front_cos": meas["front_cos"], "facing_margin": meas["facing_margin_deg"],
            "exposure_ev": round(plan.spec.exposure_ev, 3),
            "gates": gates,
        })
        print(f"[B3] frame {idx} {rs['pallet_name']} occ={rs['occluder'] is not None} "
              f"unocc={meas.get('area_unocc')} vis={meas.get('area_visible')} "
              f"Vact={meas['V_inframe']} gates={gates['all_pass']} distarea={dist_area}")
        frames_done += 1

    report["checks"]["check2_mask_unoccluded"] = {
        "PASS": bool(unocc_all_nonempty),
        "note": "every measured frame area_unocc > 0"}
    # CHECK 1 PASS = (a) force-enable un-excludes a previously-EXCLUDED collection AND
    #                (b) at least one placed occluder actually renders visible distractor px.
    c1_unexclude = bool(excl_test.get("collection_found")
                        and excl_test.get("was_excluded_before_force")
                        and not excl_test.get("excluded_after_force"))
    c1_renders = (check1_best.get("dist_only_area_px") or 0) > 50
    report["checks"]["check1_distractors_v2"] = {
        "PASS": bool(c1_unexclude and c1_renders),
        "force_unexclude_test": excl_test,
        "max_dist_only_area_px": check1_best.get("dist_only_area_px"),
        "evidence_frame": check1_best,
        "all_occluder_frames": check1_occ_frames}

    # ---- CHECK 3: floor x glTF magenta + geometric ground detector ----
    c3 = magenta_check(assets, lowel_plans or mix_plans, out, args.seed)
    report["checks"]["check3_floor_magenta"] = c3

    # ---- summary ----
    c1 = report["checks"]["check1_distractors_v2"].get("PASS", False)
    c2 = report["checks"]["check2_mask_unoccluded"]["PASS"]
    c3p = c3.get("PASS", False)
    report["ALL_PASS"] = bool(c1 and c2 and c3p)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=lambda o: None)
    print("\n=== B3 CHECK SUMMARY ===")
    print(f"  CHECK1 Distractors_v2 render : {'PASS' if c1 else 'FAIL'}  ({report['checks']['check1_distractors_v2']})")
    print(f"  CHECK2 mask_unoccluded       : {'PASS' if c2 else 'FAIL'}")
    print(f"  CHECK3 floor magenta+geom    : {'PASS' if c3p else 'FAIL'}  ({c3})")
    print(f"  ALL_PASS = {report['ALL_PASS']}")
    print(f"  report -> {os.path.join(out, 'report.json')}")


def magenta_check(assets, plans, out, seed):
    """Force floor magenta; add a NEW (non-name-matching) warehouse ground; confirm the
    GEOMETRIC detector hides it and the floor renders magenta above threshold.

    Uses an EXPLICIT oblique camera (not a plan's) so the magenta ground is guaranteed to
    fill the lower frame — the test is about floor-material rendering + geometric ground
    hiding, independent of any sampled camera."""
    import random as _r
    _r.seed(seed + 999)
    if not plans:
        return {"PASS": False, "reason": "no suitable plan"}
    plan = plans[0]
    rs = vr.realize(plan, floor_mode="plane", place_occluder=False)
    if rs is None:
        return {"PASS": False, "reason": "realize None"}
    scene = rs["scene"]
    # explicit near-top-down camera: only the ground plane (magenta) + pallet are in view, so
    # no background wall/container can occlude the floor. Standard view transform + exposure 0
    # so the emission magenta reads crisp (Filmic would desaturate/darken it).
    vr._aim_camera(scene, (0.6, 0.6, 5.0), (0.0, 0.0, 0.05))
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass

    # (a) force the floor plane pure magenta (emission, lighting-independent).
    plane = vr.get_obj("FloorRandPlane")
    if plane is None:
        return {"PASS": False, "reason": "no floor plane"}
    mat = plane.data.materials[0]
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (1.0, 0.0, 1.0, 1.0)
    e.inputs["Strength"].default_value = 2.5
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs["Emission"], o.inputs["Surface"])

    # (b) add a NEW warehouse-style ground with a NON-matching name + grey emission. If the
    #     geometric detector fails, this grey slab occludes the magenta -> ratio collapses.
    gname = "WarehouseGroundTest_new"
    gm = bpy.data.meshes.new(gname)
    gobj = bpy.data.objects.new(gname, gm)
    scene.collection.objects.link(gobj)
    h = 50.0
    gm.from_pydata([(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)], [], [(0, 1, 2, 3)])
    gm.update()
    gmat = bpy.data.materials.new("WarehouseGroundGrey")
    gmat.use_nodes = True
    gnt = gmat.node_tree
    gnt.nodes.clear()
    ge = gnt.nodes.new("ShaderNodeEmission")
    ge.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    go = gnt.nodes.new("ShaderNodeOutputMaterial")
    gnt.links.new(ge.outputs["Emission"], go.inputs["Surface"])
    gm.materials.append(gmat)
    gobj.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    # render WITH the geometric hide OFF the new ground -> baseline occlusion.
    rgb_before = os.path.join(out, "c3_magenta_BEFORE_geomhide.png")
    scene.view_settings.exposure = 0.0
    vr.render(rs, rgb_before, samples=8)
    mag_before = magenta_ratio(rgb_before)

    # now run the GEOMETRIC detector (should hide the NEW ground by geometry, not name).
    n_hidden, hidden_names = vr._hide_ground_geometric([rs["pallet"], plane])
    detected = gname in hidden_names
    bpy.context.view_layer.update()
    rgb_after = os.path.join(out, "c3_magenta_AFTER_geomhide.png")
    vr.render(rs, rgb_after, samples=8)
    mag_after = magenta_ratio(rgb_after)

    THRESH = 0.12
    return {
        "PASS": bool(detected and mag_after >= THRESH),
        "geometric_detected_new_ground": bool(detected),
        "hidden_by_geom": hidden_names,
        "magenta_ratio_before_geomhide": round(mag_before, 4),
        "magenta_ratio_after_geomhide": round(mag_after, 4),
        "threshold": THRESH,
        "rgb_before": os.path.basename(rgb_before),
        "rgb_after": os.path.basename(rgb_after),
        "elev_bin": plan.spec.elev_bin,
    }


if __name__ == "__main__":
    run()
