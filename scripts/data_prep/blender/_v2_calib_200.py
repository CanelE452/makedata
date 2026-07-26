"""v2 규약 Phase D — 200-frame CALIBRATION render (target vs actual measurement).

Renders every one of the 200 ACCEPTED plans from generate_accepted (accept-time quota),
measures the ACTUAL frame quantities (f_cargo/f_occ/f_total via holdout masks, V_actual,
occlusion_fraction, luma, elevation_actual, perm), evaluates the hard safety gates G1..G5,
labels, and writes an aggregate record per frame for the 6 downstream analyses.

This is calibration ONLY (task: "렌더 허용 (D 캘리브 전용)"). NOT the 2k pilot, NOT the v2
main render. Does NOT commit anything and does NOT change any prescription.

Run:
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
      --python scripts/data_prep/blender/_v2_calib_200.py -- \
      --out data/pallet/_v2_calib_200 --seed 7000 --n 200

Resumable: re-running skips frames whose rgb already exists (deterministic plan list).
"""
import argparse
import json
import os
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import numpy as np  # noqa: E402

import v2_pipeline as vp   # noqa: E402
import v2_realize as vr    # noqa: E402


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/pallet/_v2_calib_200")
    p.add_argument("--seed", type=int, default=7000)
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--samples", type=int, default=16)
    return p.parse_args(argv)


def _abspath(out):
    if os.path.isabs(out):
        return out
    root = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
    return os.path.join(root, out)


def _record(idx, plan, rs, meas, gates):
    spec = plan.spec
    occ = plan.occluder
    return {
        "idx": idx,
        "attempt_frame_index": spec.frame_index,
        "pallet": rs["pallet_name"],
        "scene_preset": spec.scene_preset,
        # -- analysis 1: f_target vs f_actual --
        "f_target": round(float(spec.f_target), 4),
        "f_target_bin": spec.f_target_bin,
        "f_cargo_plan": round(float(plan.f_cargo), 4),
        "f_need_plan": round(float(plan.f_need), 4),
        "f_cargo_meas": meas.get("f_cargo"),
        "f_occ_meas": meas.get("f_occ"),
        "f_total_meas": meas.get("f_total"),
        # -- analysis 2: elevation target vs actual --
        "elev_bin": spec.elev_bin,
        "elev_target": round(float(spec.elevation_deg), 3),
        "elev_actual": round(vr._actual_elevation_deg(rs["cam_pos"], meas["centroid_world"]), 3),
        "azimuth_target": round(float(spec.azimuth_deg), 3),
        # -- V --
        "v_target": spec.v_target,
        "V_actual": meas["V_inframe"],
        "V_vis": meas["V_vis"],
        "ext_occ": meas["ext_occ_corners"],
        # -- analysis 3 + 4: occluder size_class + side --
        "occluder_placed": rs["occluder"] is not None,
        "occluder_name": (occ or {}).get("name") if occ else None,
        "occluder_size_class": (occ or {}).get("size_class") if occ else None,
        "occluder_side": (occ or {}).get("side") if occ else None,
        "occluder_d_occ": round(float((occ or {}).get("d_occ_m")), 4) if occ else None,
        "occluder_in_band": (occ or {}).get("in_position_band") if occ else None,
        "position_mode": spec.position_mode,
        # -- analysis 5: gates --
        "gates": gates,
        # -- extras --
        "cargo_on": bool(spec.cargo_on),
        "n_cargo": rs.get("n_cargo"),
        "luma_frame": meas.get("luma_frame"),
        "luma_pallet": meas.get("luma_pallet"),
        "front_cos": meas["front_cos"],
        "facing_margin": meas["facing_margin_deg"],
        "fx": round(float(rs["K"][0, 0]), 2),
        "fx_mode": spec.fx_mode,
        "res": [rs["W"], rs["H"]],
        "aspect": spec.aspect,
        "floor_mode": rs.get("floor_mode"),
        "cam_distance_m": round(float(plan.cam_distance_m), 4),
        "mask_area_unocc": meas.get("area_unocc"),
        "mask_area_visible": meas.get("area_visible"),
    }


def run():
    args = _args()
    out = _abspath(args.out)
    rgb_dir = os.path.join(out, "rgb")
    mask_dir = os.path.join(out, "mask")
    lab_dir = os.path.join(out, "labels")
    for d in (out, rgb_dir, mask_dir, lab_dir):
        os.makedirs(d, exist_ok=True)

    import random as _r
    _r.seed(args.seed)  # reproducible bg/hdri/floor sequence
    gpu = vr.enable_gpu()
    print(f"[D] gpu={gpu} out={out} n={args.n} seed={args.seed}", flush=True)

    assets = vp.load_assets()
    t_gen = time.time()
    plans, rejects, qs, attempts = vp.generate_accepted(args.n, args.seed, assets)
    print(f"[D] generate_accepted: accepted={len(plans)} rejects={len(rejects)} "
          f"attempts={attempts} pass_rate={len(plans)/max(1,attempts):.3f} "
          f"({time.time()-t_gen:.1f}s)", flush=True)
    if len(plans) < args.n:
        print(f"[D][WARN] only {len(plans)} plans (< {args.n}) — solve pass-rate limited", flush=True)

    jsonl_path = os.path.join(out, "calib_records.jsonl")
    # resume: which idx already have an rgb on disk.
    done = set()
    if os.path.isfile(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass
    records = []
    t0 = time.time()
    n_ok = 0
    for idx, plan in enumerate(plans):
        rgb = os.path.join(rgb_dir, f"f{idx:04d}_rgb.png")
        if idx in done and os.path.isfile(rgb):
            continue
        try:
            rs = vr.realize(plan, floor_mode=None, place_occluder=True)
        except Exception as e:
            print(f"[D] frame {idx}: realize EXC {e}", flush=True)
            rs = None
        if rs is None:
            rec = {"idx": idx, "realize_ok": False, "occluder_placed": None,
                   "attempt_frame_index": plan.spec.frame_index}
            records.append(rec)
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[D] frame {idx}: realize None (skip)", flush=True)
            continue
        rs["rgb_path"] = rgb
        rs["mask_prefix"] = os.path.join(mask_dir, f"f{idx:04d}")
        vr.render(rs, rgb, samples=args.samples)
        meas = vr.measure(rs)
        gates = vr.safety_gates(meas, plan)
        lab = vr.label(plan.spec, plan, meas, rs)
        with open(os.path.join(lab_dir, f"f{idx:04d}_label.json"), "w", encoding="utf-8") as f:
            json.dump(lab, f, indent=2, default=lambda o: None)
        rec = _record(idx, plan, rs, meas, gates)
        rec["realize_ok"] = True
        records.append(rec)
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=lambda o: None) + "\n")
        n_ok += 1

        if n_ok % 10 == 0 or idx == len(plans) - 1:
            el = time.time() - t0
            per = el / max(1, n_ok)
            eta = per * (len(plans) - idx - 1)
            print(f"[D] {idx+1}/{len(plans)} ok={n_ok} occ={rec['occluder_placed']} "
                  f"gatesPASS={gates['all_pass']} ftgt={rec['f_target']} ftot={rec['f_total_meas']} "
                  f"elevT={rec['elev_target']} elevA={rec['elev_actual']} "
                  f"| {per:.1f}s/f eta={eta/60:.1f}min", flush=True)

    # final aggregate (merge resumed jsonl for completeness).
    allrecs = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                allrecs.append(json.loads(line))
            except Exception:
                pass
    # de-dup by idx (keep last).
    by_idx = {}
    for r in allrecs:
        by_idx[r["idx"]] = r
    allrecs = [by_idx[k] for k in sorted(by_idx)]
    with open(os.path.join(out, "calib_records.json"), "w", encoding="utf-8") as f:
        json.dump(allrecs, f, indent=2, default=lambda o: None)

    summary = {
        "gpu": gpu, "seed": args.seed, "n_target": args.n,
        "accepted_plans": len(plans), "solve_rejects": len(rejects),
        "solve_attempts": attempts,
        "solve_pass_rate": round(len(plans) / max(1, attempts), 4),
        "frames_recorded": len(allrecs),
        "realize_failed": sum(1 for r in allrecs if not r.get("realize_ok")),
        "elapsed_render_s": round(time.time() - t0, 1),
    }
    with open(os.path.join(out, "driver_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[D] DONE {summary}", flush=True)
    print(f"[D] records -> {os.path.join(out, 'calib_records.json')}", flush=True)


if __name__ == "__main__":
    run()
