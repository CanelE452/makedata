"""G5 fix small-scale re-verification (live Blender path).

Renders a small set of ACCEPTED plans through the FULL live path (realize -> render ->
measure -> render_post -> safety_gates -> label) to confirm, in Blender (not just static
re-analysis of the calib set):
  1. measure() now reports luma_pallet over the VISIBLE mask (task ①).
  2. safety_gates() G5 uses luma_pallet only (luma_frame dropped) (task ①).
  3. render_post() raises sensor noise_scale on dark frames (task ① sub-item).
  4. no bad frame leaks: a G5-pass frame with an invisible pallet is caught by G3.

Calibration/diagnostic ONLY. No commit. Writes data/pallet/runs/diagnostics/_v2_g5_reverify/.

Run:
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
      --python scripts/data_prep/blender/_g5_reverify.py -- --n 16 --seed 7000
"""
import argparse, json, os, sys, time
_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
import numpy as np  # noqa: E402
import v2_pipeline as vp   # noqa: E402
import v2_realize as vr    # noqa: E402


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/pallet/runs/diagnostics/_v2_g5_reverify")
    p.add_argument("--seed", type=int, default=7000)
    p.add_argument("--n", type=int, default=16)
    p.add_argument("--samples", type=int, default=16)
    return p.parse_args(argv)


def _abspath(out):
    if os.path.isabs(out):
        return out
    return os.path.join(os.path.abspath(os.path.join(_THIS, "..", "..", "..")), out)


def run():
    a = _args()
    out = _abspath(a.out)
    rgb_dir, mask_dir = os.path.join(out, "rgb"), os.path.join(out, "mask")
    for d in (out, rgb_dir, mask_dir):
        os.makedirs(d, exist_ok=True)
    import random as _r
    _r.seed(a.seed)
    gpu = vr.enable_gpu()
    assets = vp.load_assets()
    plans, rejects, qs, attempts = vp.generate_accepted(a.n, a.seed, assets)
    print(f"[G5RV] gpu={gpu} accepted={len(plans)} attempts={attempts} "
          f"pass_rate={len(plans)/max(1,attempts):.3f}", flush=True)

    recs = []
    t0 = time.time()
    for idx, plan in enumerate(plans):
        rgb = os.path.join(rgb_dir, f"f{idx:04d}_rgb.png")
        try:
            rs = vr.realize(plan, floor_mode=None, place_occluder=True)
        except Exception as e:
            print(f"[G5RV] f{idx} realize EXC {e}", flush=True)
            rs = None
        if rs is None:
            continue
        rs["rgb_path"] = rgb
        rs["mask_prefix"] = os.path.join(mask_dir, f"f{idx:04d}")
        vr.render(rs, rgb, samples=a.samples)
        meas = vr.measure(rs)
        # render_post: dark-frame sensor-noise scaling (task ① sub-item). Uses luma_frame.
        noise_scale = vr.render_post(rgb, a.seed + idx, meas.get("luma_frame") or 128.0)
        gates = vr.safety_gates(meas, plan)
        rec = dict(idx=idx, scene=plan.spec.scene_preset,
                   exposure_ev=round(float(plan.spec.exposure_ev), 3),
                   luma_frame=meas.get("luma_frame"),
                   luma_pallet_visible=meas.get("luma_pallet"),
                   noise_scale=round(float(noise_scale), 3),
                   area_unocc=meas.get("area_unocc"), area_visible=meas.get("area_visible"),
                   occluder=rs["occluder"] is not None, cargo=bool(plan.spec.cargo_on),
                   f_total=meas.get("f_total"),
                   G1=gates["G1_Vvis>=4"], G2=gates["G2_extocc_1to4"],
                   G3=gates["G3_visible>=0.5unocc"], G4=gates["G4_center_inframe"],
                   G5=gates["G5_luma_floor"], all_pass=gates["all_pass"])
        recs.append(rec)
        print(f"[G5RV] f{idx:02d} {rec['scene']:12s} ev={rec['exposure_ev']:+.2f} "
              f"lf={rec['luma_frame']} lp_vis={rec['luma_pallet_visible']} "
              f"noise={rec['noise_scale']} a_vis={rec['area_visible']} "
              f"G5={rec['G5']} all={rec['all_pass']}", flush=True)

    json.dump(recs, open(os.path.join(out, "g5_reverify_records.json"), "w"), indent=2,
              default=lambda o: None)

    # ---- summary / assertions ----
    print("\n[G5RV] ===== SUMMARY =====", flush=True)
    dark = [r for r in recs if r["luma_frame"] is not None and r["luma_frame"] < 40]
    print(f"  frames={len(recs)}  dark(luma_frame<40)={len(dark)}", flush=True)
    # (3) noise rises on dark frames
    if dark:
        print("  dark-frame noise_scale (expect >1.0, up to 2.5):", flush=True)
        for r in sorted(dark, key=lambda z: z["luma_frame"]):
            exp = round(1.0 + max(0.0, (60.0 - r["luma_frame"]) / 60.0) * 1.5, 3)
            ok = abs(exp - r["noise_scale"]) < 1e-2
            print(f"    lf={r['luma_frame']:5.1f} -> noise={r['noise_scale']} (formula {exp}) {'OK' if ok else 'MISMATCH'}", flush=True)
    # (4) leak guard: G5 pass but pallet invisible -> must be G3-rejected
    leak = [r for r in recs if r["G5"] and (r["luma_pallet_visible"] is None) and r["all_pass"]]
    print(f"  LEAK CHECK: G5-pass + invisible pallet + all_pass = {len(leak)} (must be 0)", flush=True)
    # (2) confirm G5 == (lp_vis is None or >=12)
    bad_g5 = [r for r in recs
              if r["G5"] != (r["luma_pallet_visible"] is None or r["luma_pallet_visible"] >= 12.0)]
    print(f"  G5-LOGIC CHECK: gates.G5 matches visible-luma-only rule mismatches = {len(bad_g5)} (must be 0)", flush=True)
    print(f"  all_pass count = {sum(r['all_pass'] for r in recs)}  ({time.time()-t0:.1f}s)", flush=True)


if __name__ == "__main__":
    run()
