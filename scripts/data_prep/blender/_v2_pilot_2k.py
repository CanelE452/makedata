"""v2 규약 PILOT — 2000-frame render (chunk-resumable, FULL live-label path).

Renders ACCEPTED plans (generate_accepted, accept-time quota) through the FULL live path:
    realize -> render -> measure -> render_post(noise) -> safety_gates -> label(f_actual_bin)

This is the PILOT (task-authorized: 2000 RENDERED, not gate-passing 2000). It is NOT the 40k
full render (that needs pilot-audit pass + explicit user approval). Calibration/diagnostic
ONLY; commits nothing; changes no prescription. Invariants unchanged (EXPOSURE_EV_RANGE lower
-3.0, ELEV 7-bin, F_TARGET_*, G5_LUMA_MIN=12); occluder solve / C2 untouched.

Chunk-resumable (OOM bound): --max_render caps frames rendered THIS Blender session; a fresh
Blender process per chunk keeps memory bounded (no mid-run restart). Re-running skips frames
whose rgb already exists (generate_accepted is deterministic -> same plan list every session).

Adds over _v2_calib_200.py (the two live-label wirings that did not run at calib time):
  - render_post(noise): dark-frame sensor-noise scaling ACTUALLY applied to the saved RGB.
  - f_actual_bin + noise_scale recorded from the LIVE label()/measure (were absent in calib).
  - per-frame global-random seed so bg/hdri/floor is chunk-boundary-independent (reproducible).

Run one chunk:
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
      --python scripts/data_prep/blender/_v2_pilot_2k.py -- \
      --out data/pallet/runs/diagnostics/_v2_pilot_2k --seed 7000 --n 2000 --max_render 200
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
    p.add_argument("--out", default="data/pallet/runs/diagnostics/_v2_pilot_2k")
    p.add_argument("--seed", type=int, default=7000)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--max_render", type=int, default=200,
                   help="cap frames rendered THIS session (chunk); 0 = no cap")
    return p.parse_args(argv)


def _abspath(out):
    if os.path.isabs(out):
        return out
    root = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
    return os.path.join(root, out)


def _record(idx, plan, rs, meas, gates, noise_scale, f_actual_bin):
    spec = plan.spec
    occ = plan.occluder
    return {
        "idx": idx,
        "attempt_frame_index": spec.frame_index,
        "pallet": rs["pallet_name"],
        "scene_preset": spec.scene_preset,
        # -- analysis 1: f_target vs f_actual (+ f_actual_bin, was absent in calib) --
        "f_target": round(float(spec.f_target), 4),
        "f_target_bin": spec.f_target_bin,
        "f_cargo_plan": round(float(plan.f_cargo), 4),
        "f_need_plan": round(float(plan.f_need), 4),
        "f_cargo_meas": meas.get("f_cargo"),
        "f_occ_meas": meas.get("f_occ"),
        "f_total_meas": meas.get("f_total"),
        "f_actual_bin": f_actual_bin,
        # -- analysis 2: elevation target vs actual --
        "elev_bin": spec.elev_bin,
        "elev_target": round(float(spec.elevation_deg), 3),
        "elev_actual": round(vr._actual_elevation_deg(rs["cam_pos"], meas["centroid_world"]), 3),
        "azimuth_bin": spec.azimuth_bin,
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
        # -- occlusion_fraction[9] continuous per-corner (audit: NOT binary) --
        "occlusion_fraction": meas.get("occlusion_fraction"),
        # -- extras --
        "cargo_on": bool(spec.cargo_on),
        "n_cargo": rs.get("n_cargo"),
        "luma_frame": meas.get("luma_frame"),
        "luma_pallet": meas.get("luma_pallet"),
        "noise_scale": round(float(noise_scale), 4),
        "front_cos": meas["front_cos"],
        "facing_margin": meas["facing_margin_deg"],
        "perm": meas["perm"],
        "proj_size_bin": spec.proj_size_bin,
        "proj_size_ratio": round(float(spec.proj_size_ratio), 4),
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
    gpu = vr.enable_gpu()
    print(f"[PILOT] gpu={gpu} out={out} n={args.n} seed={args.seed} "
          f"max_render={args.max_render}", flush=True)

    assets = vp.load_assets()
    t_gen = time.time()
    plans, rejects, qs, attempts = vp.generate_accepted(args.n, args.seed, assets)
    print(f"[PILOT] generate_accepted: accepted={len(plans)} rejects={len(rejects)} "
          f"attempts={attempts} pass_rate={len(plans)/max(1,attempts):.3f} "
          f"({time.time()-t_gen:.1f}s)", flush=True)
    if len(plans) < args.n:
        print(f"[PILOT][WARN] only {len(plans)} plans (< {args.n}) — solve pass-rate limited",
              flush=True)

    jsonl_path = os.path.join(out, "pilot_records.jsonl")
    done = set()
    if os.path.isfile(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["idx"])
                except Exception:
                    pass

    t0 = time.time()
    n_ok = 0
    n_this_session = 0
    for idx, plan in enumerate(plans):
        rgb = os.path.join(rgb_dir, f"f{idx:04d}_rgb.png")
        if idx in done and os.path.isfile(rgb):
            continue
        if args.max_render and n_this_session >= args.max_render:
            print(f"[PILOT] session cap reached ({args.max_render}); exiting (resume next chunk)",
                  flush=True)
            break
        # per-frame global-random seed: bg/hdri/floor deterministic & chunk-boundary-independent.
        _r.seed(args.seed * 100003 + idx)
        try:
            rs = vr.realize(plan, floor_mode=None, place_occluder=True)
        except Exception as e:
            print(f"[PILOT] frame {idx}: realize EXC {e}", flush=True)
            rs = None
        if rs is None:
            rec = {"idx": idx, "realize_ok": False, "occluder_placed": None,
                   "attempt_frame_index": plan.spec.frame_index}
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            n_this_session += 1
            print(f"[PILOT] frame {idx}: realize None (skip)", flush=True)
            continue
        rs["rgb_path"] = rgb
        rs["mask_prefix"] = os.path.join(mask_dir, f"f{idx:04d}")
        vr.render(rs, rgb, samples=args.samples)
        meas = vr.measure(rs)
        # render_post: dark-frame sensor-noise scaling APPLIED to the saved RGB (Illumination DR).
        noise_scale = vr.render_post(rgb, args.seed + idx, meas.get("luma_frame") or 128.0)
        gates = vr.safety_gates(meas, plan)
        lab = vr.label(plan.spec, plan, meas, rs)
        f_actual_bin = lab["objects"][0]["v2_labels"]["f_actual_bin"]
        with open(os.path.join(lab_dir, f"f{idx:04d}_label.json"), "w", encoding="utf-8") as f:
            json.dump(lab, f, indent=2, default=lambda o: None)
        rec = _record(idx, plan, rs, meas, gates, noise_scale, f_actual_bin)
        rec["realize_ok"] = True
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=lambda o: None) + "\n")
        n_ok += 1
        n_this_session += 1

        if n_ok % 10 == 0:
            el = time.time() - t0
            per = el / max(1, n_ok)
            print(f"[PILOT] session {n_this_session} (idx {idx}) ok={n_ok} "
                  f"occ={rec['occluder_placed']} gatesPASS={gates['all_pass']} "
                  f"scene={rec['scene_preset']} elevA={rec['elev_actual']} "
                  f"lumaP={rec['luma_pallet']} noise={rec['noise_scale']} "
                  f"fActBin={rec['f_actual_bin']} | {per:.1f}s/f", flush=True)

    # aggregate merge (de-dup by idx, keep last).
    allrecs = []
    if os.path.isfile(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    allrecs.append(json.loads(line))
                except Exception:
                    pass
    by_idx = {}
    for r in allrecs:
        by_idx[r["idx"]] = r
    allrecs = [by_idx[k] for k in sorted(by_idx)]
    with open(os.path.join(out, "pilot_records.json"), "w", encoding="utf-8") as f:
        json.dump(allrecs, f, indent=2, default=lambda o: None)

    n_rendered = sum(1 for r in allrecs if r.get("realize_ok"))
    summary = {
        "gpu": gpu, "seed": args.seed, "n_target": args.n,
        "accepted_plans": len(plans), "solve_rejects": len(rejects),
        "solve_attempts": attempts,
        "solve_pass_rate": round(len(plans) / max(1, attempts), 4),
        "frames_recorded": len(allrecs),
        "frames_rendered_ok": n_rendered,
        "realize_failed": sum(1 for r in allrecs if not r.get("realize_ok")),
        "rendered_this_session": n_this_session,
        "elapsed_session_s": round(time.time() - t0, 1),
        "complete": n_rendered >= args.n,
    }
    with open(os.path.join(out, "driver_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[PILOT] SESSION DONE {summary}", flush=True)


if __name__ == "__main__":
    run()
