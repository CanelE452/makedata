"""v2 규약 Phase D — analysis of the 200-frame calibration render (6 analyses).

Reads calib_records.json (from _v2_calib_200.py) and produces the 6 figures + tables the
task asks for. NO Blender; runs in a matplotlib env (base). Measures target vs actual and
diagnoses systematic bias — it does NOT change any prescription (correction is PROPOSAL ONLY).

Run:
  python scripts/data_prep/blender/_v2_calib_200_analyze.py \
      --records data/pallet/archive/superseded_runs/_v2_calib_200/calib_records.json
"""
import argparse
import json
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# prescription constants (mirror v2_pipeline so we don't need bpy/import).
SIZE_ORDER = ["large", "road", "medium", "indoor", "small"]
SIZE_CLASS_WEIGHTS = {"large": 3.0, "road": 3.0, "medium": 2.0, "indoor": 1.0, "small": 0.6}
POOL_COUNTS = {"large": 18, "road": 13, "medium": 21, "indoor": 40, "small": 117}
SIDE_LABELS = ["left", "right", "bottom", "center"]
SIDE_WEIGHTS = [0.30, 0.30, 0.25, 0.15]
F_TARGET_LABELS = ["0", "0.10-0.20", "0.20-0.35", "0.35-0.45"]
GATE_KEYS = ["G1_Vvis>=4", "G2_extocc_1to4", "G3_visible>=0.5unocc",
             "G4_center_inframe", "G5_luma_floor"]
DRYRUN_LARGE_FRAC = 0.299   # reference from the dry-run audit (LATERAL mode)


def _fnum(x):
    return None if x is None else float(x)


def load(records_path):
    recs = json.load(open(records_path, encoding="utf-8"))
    return [r for r in recs if r.get("realize_ok")]


# ===========================================================================
# ANALYSIS 1: f_target vs f_actual
# ===========================================================================
def analysis1_f(recs, out, lines):
    # measurable = f_total not None
    meas = [r for r in recs if _fnum(r.get("f_total_meas")) is not None]
    unmeasurable = [r for r in recs if _fnum(r.get("f_total_meas")) is None]
    ft = np.array([r["f_target"] for r in meas])
    ftot = np.array([_fnum(r["f_total_meas"]) for r in meas])
    cargo = np.array([bool(r["cargo_on"]) for r in meas])
    occ = np.array([bool(r["occluder_placed"]) for r in meas])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    # panel A: f_target vs f_total (all measurable)
    for mask, c, lab in [(occ, "#C44E52", "occluder placed"),
                         (~occ, "#4C72B0", "no occluder (cargo/none)")]:
        ax1.scatter(ft[mask], ftot[mask], s=28, alpha=0.7, c=c, label=lab, edgecolors="none")
    ax1.plot([0, 0.5], [0, 0.5], "k--", lw=1, label="ideal y=x")
    ax1.set_xlabel("f_target (occlusion target)")
    ax1.set_ylabel("f_total_actual (measured cargo+occluder)")
    ax1.set_title("(1) f_target vs f_total_actual")
    ax1.legend(fontsize=8); ax1.grid(alpha=0.3)

    # panel B: occluder-only delivery — f_occ_meas vs f_need_plan
    occ_recs = [r for r in meas if r["occluder_placed"] and _fnum(r.get("f_occ_meas")) is not None]
    fn = np.array([r["f_need_plan"] for r in occ_recs])
    fo = np.array([_fnum(r["f_occ_meas"]) for r in occ_recs])
    if len(occ_recs):
        ax2.scatter(fn, fo, s=30, alpha=0.75, c="#DD8452", edgecolors="none")
        m = max(0.5, float(np.nanmax(fn)) if len(fn) else 0.5)
        ax2.plot([0, m], [0, m], "k--", lw=1, label="ideal y=x")
    ax2.set_xlabel("f_need_plan (occluder residual target)")
    ax2.set_ylabel("f_occ_actual (measured occluder-only)")
    ax2.set_title(f"(1b) occluder delivery  (n={len(occ_recs)})")
    ax2.legend(fontsize=8); ax2.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(out, "a1_f_target_vs_actual.png"), dpi=110)
    plt.close(fig)

    lines.append("=" * 78)
    lines.append("ANALYSIS 1: f_target vs f_actual (f_total)")
    lines.append("-" * 78)
    lines.append(f"  measurable frames (f_total != None): {len(meas)}  |  "
                 f"unmeasurable (empty pallet mask): {len(unmeasurable)}")
    lines.append("")
    lines.append("  per f_target_bin: f_total_actual vs f_target (bias = actual - target)")
    lines.append("  bin  label        n    ftgt_mean  ftot_mean  bias_mean  bias_std")
    lines.append("  " + "-" * 66)
    bin_bias = {}
    for b in range(4):
        sub = [r for r in meas if r["f_target_bin"] == b]
        if not sub:
            lines.append(f"  {b}    {F_TARGET_LABELS[b]:<11}  0")
            continue
        tgt = np.array([r["f_target"] for r in sub])
        act = np.array([_fnum(r["f_total_meas"]) for r in sub])
        bias = act - tgt
        bin_bias[b] = (float(bias.mean()), float(bias.std()))
        lines.append(f"  {b}    {F_TARGET_LABELS[b]:<11}  {len(sub):<3}  "
                     f"{tgt.mean():8.3f}   {act.mean():8.3f}   {bias.mean():+8.3f}   {bias.std():7.3f}")
    lines.append("")
    # occluder-only bias
    if occ_recs:
        obias = fo - fn
        lines.append(f"  occluder-only delivery (n={len(occ_recs)}): "
                     f"f_occ_actual mean={fo.mean():.3f} vs f_need_plan mean={fn.mean():.3f}  "
                     f"bias_mean={obias.mean():+.3f} std={obias.std():.3f}")
    # cargo-only inflation on f_target==0 frames
    z = [r for r in meas if r["f_target_bin"] == 0]
    zc = [r for r in z if r["cargo_on"]]
    if z:
        zf = np.array([_fnum(r["f_total_meas"]) for r in z])
        lines.append(f"  f_target==0 frames (n={len(z)}): f_total mean={zf.mean():.3f} "
                     f"(cargo_on={len(zc)} inflate silhouette even with no occluder)")
    lines.append("")
    return bin_bias, {"measurable": len(meas), "unmeasurable": len(unmeasurable),
                      "occ_bias": (float((fo-fn).mean()), float((fo-fn).std())) if occ_recs else None}


# ===========================================================================
# ANALYSIS 2: elevation target vs actual
# ===========================================================================
def analysis2_elev(recs, out, lines):
    et = np.array([r["elev_target"] for r in recs])
    ea = np.array([r["elev_actual"] for r in recs])
    d = ea - et
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    ax1.scatter(et, ea, s=26, alpha=0.7, c="#55A868", edgecolors="none")
    m = max(et.max(), ea.max()) * 1.05
    ax1.plot([0, m], [0, m], "k--", lw=1, label="y=x")
    ax1.set_xlabel("elevation_target (deg)"); ax1.set_ylabel("elevation_actual (deg)")
    ax1.set_title("(2) elevation target vs actual"); ax1.legend(); ax1.grid(alpha=0.3)
    ax2.hist(d, bins=40, color="#55A868")
    ax2.axvline(0, color="k", ls="--")
    ax2.set_xlabel("Delta = actual - target (deg)"); ax2.set_ylabel("count")
    ax2.set_title(f"(2) Delta hist  mean={d.mean():+.4f} std={d.std():.4f} max|d|={np.abs(d).max():.4f}")
    fig.tight_layout(); fig.savefig(os.path.join(out, "a2_elev_target_vs_actual.png"), dpi=110)
    plt.close(fig)

    lines.append("=" * 78)
    lines.append("ANALYSIS 2: elevation target vs actual (B3 centroid-alignment fix validation)")
    lines.append("-" * 78)
    lines.append(f"  n={len(recs)}  Delta=actual-target: mean={d.mean():+.5f} std={d.std():.5f} "
                 f"max|Delta|={np.abs(d).max():.5f} deg")
    worst = recs[int(np.argmax(np.abs(d)))]
    lines.append(f"  worst frame idx={worst['idx']} elevT={worst['elev_target']} "
                 f"elevA={worst['elev_actual']} (Delta={worst['elev_actual']-worst['elev_target']:+.4f})")
    verdict = "MATCH (Delta~0 maintained on 200)" if np.abs(d).max() < 0.5 else "DRIFT - investigate"
    lines.append(f"  verdict: {verdict}")
    lines.append("")
    return {"mean": float(d.mean()), "std": float(d.std()), "maxabs": float(np.abs(d).max())}


# ===========================================================================
# ANALYSIS 3: occluder size_class distribution
# ===========================================================================
def analysis3_sizeclass(recs, out, lines):
    occ = [r for r in recs if r["occluder_placed"] and r.get("occluder_size_class")]
    by_sc = Counter(r["occluder_size_class"] for r in occ)
    n = sum(by_sc.values()) or 1
    # weighted availability reference
    tot_w = sum(SIZE_CLASS_WEIGHTS[s] * POOL_COUNTS[s] for s in SIZE_ORDER)
    avail = {s: SIZE_CLASS_WEIGHTS[s] * POOL_COUNTS[s] / tot_w for s in SIZE_ORDER}

    x = np.arange(len(SIZE_ORDER))
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(x - 0.2, [by_sc.get(s, 0) / n for s in SIZE_ORDER], 0.4,
           label="Phase D placed (200 render)", color="#DD8452")
    ax.bar(x + 0.2, [avail[s] for s in SIZE_ORDER], 0.4,
           label="weighted pool availability", color="#B0B0B0")
    ax.axhline(DRYRUN_LARGE_FRAC, color="#C44E52", ls="--", lw=1,
               label=f"dry-run large={DRYRUN_LARGE_FRAC:.1%}")
    ax.set_xticks(x); ax.set_xticklabels(SIZE_ORDER)
    ax.set_ylabel("fraction of placed occluders")
    ax.set_title(f"(3) occluder size_class distribution (n_placed={n})")
    ax.legend(fontsize=8)
    for i, s in enumerate(SIZE_ORDER):
        ax.text(i - 0.2, by_sc.get(s, 0) / n, str(by_sc.get(s, 0)), ha="center", va="bottom", fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(out, "a3_occluder_size_class.png"), dpi=110)
    plt.close(fig)

    large_frac = by_sc.get("large", 0) / n
    lines.append("=" * 78)
    lines.append("ANALYSIS 3: occluder size_class distribution (large usage retention)")
    lines.append("-" * 78)
    lines.append(f"  placed occluders n={n}")
    lines.append("  size_class   placed_n   placed_%   pool_avail_%   dry-run_ref")
    lines.append("  " + "-" * 60)
    for s in SIZE_ORDER:
        ref = f"{DRYRUN_LARGE_FRAC:.1%}" if s == "large" else "-"
        lines.append(f"  {s:<10}   {by_sc.get(s,0):>6}    {100*by_sc.get(s,0)/n:6.1f}%    "
                     f"{100*avail[s]:6.1f}%       {ref}")
    lines.append("")
    lines.append(f"  LARGE actual usage = {large_frac:.1%}  (dry-run reference {DRYRUN_LARGE_FRAC:.1%})")
    delta = large_frac - DRYRUN_LARGE_FRAC
    if abs(delta) <= 0.08:
        verdict = f"MAINTAINED (within +-8pp of dry-run; delta={delta:+.1%})"
    elif delta < 0:
        verdict = (f"DROPPED (delta={delta:+.1%}) -> possible C2 2D-alignment signal "
                   f"(JUDGMENT MATERIAL ONLY, do NOT fix)")
    else:
        verdict = f"HIGHER (delta={delta:+.1%})"
    lines.append(f"  verdict: {verdict}")
    lines.append("")
    return {"n_placed": n, "by_size_class": dict(by_sc), "large_frac": large_frac,
            "large_delta_vs_dryrun": float(delta)}


# ===========================================================================
# ANALYSIS 4: side distribution + side-wise f deviation
# ===========================================================================
def analysis4_side(recs, out, lines):
    occ = [r for r in recs if r["occluder_placed"] and r.get("occluder_side")]
    by_side = Counter(r["occluder_side"] for r in occ)
    n = sum(by_side.values()) or 1

    # side-wise occluder delivery bias (f_occ_meas - f_need_plan), measurable only
    side_bias = {}
    for s in SIDE_LABELS:
        sub = [r for r in occ if r["occluder_side"] == s
               and _fnum(r.get("f_occ_meas")) is not None]
        if sub:
            b = np.array([_fnum(r["f_occ_meas"]) - r["f_need_plan"] for r in sub])
            side_bias[s] = (len(sub), float(b.mean()), float(b.std()))
        else:
            side_bias[s] = (0, float("nan"), float("nan"))

    x = np.arange(len(SIDE_LABELS))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    ax1.bar(x - 0.2, [by_side.get(s, 0) / n for s in SIDE_LABELS], 0.4,
            label="placed (Phase D)", color="#55A868")
    ax1.bar(x + 0.2, SIDE_WEIGHTS, 0.4, label="prescribed SIDE_WEIGHTS", color="#4C72B0")
    ax1.set_xticks(x); ax1.set_xticklabels(SIDE_LABELS)
    ax1.set_ylabel("fraction"); ax1.set_title(f"(4) occluder side dist (n={n})")
    ax1.legend(fontsize=8)
    for i, s in enumerate(SIDE_LABELS):
        ax1.text(i - 0.2, by_side.get(s, 0) / n, str(by_side.get(s, 0)), ha="center", va="bottom", fontsize=8)
    means = [side_bias[s][1] for s in SIDE_LABELS]
    stds = [side_bias[s][2] for s in SIDE_LABELS]
    ax2.bar(x, means, yerr=stds, color="#DD8452", capsize=4)
    ax2.axhline(0, color="k", ls="--", lw=1)
    ax2.set_xticks(x); ax2.set_xticklabels(SIDE_LABELS)
    ax2.set_ylabel("f_occ_actual - f_need_plan")
    ax2.set_title("(4) side-wise occluder delivery bias")
    fig.tight_layout(); fig.savefig(os.path.join(out, "a4_occluder_side.png"), dpi=110)
    plt.close(fig)

    lines.append("=" * 78)
    lines.append("ANALYSIS 4: occluder side distribution + side-wise f deviation")
    lines.append("-" * 78)
    lines.append(f"  placed occluders n={n}")
    lines.append("  side      placed_n   placed_%   presc_%    f_occ_bias_mean   bias_std")
    lines.append("  " + "-" * 68)
    for i, s in enumerate(SIDE_LABELS):
        nb, bm, bs = side_bias[s]
        bm_s = f"{bm:+.3f}" if nb else "   -  "
        bs_s = f"{bs:.3f}" if nb else "  -  "
        lines.append(f"  {s:<8}  {by_side.get(s,0):>6}    {100*by_side.get(s,0)/n:6.1f}%   "
                     f"{100*SIDE_WEIGHTS[i]:5.1f}%      {bm_s:>8}         {bs_s}")
    lines.append("")
    return {"by_side": dict(by_side), "n_placed": n,
            "side_bias": {s: side_bias[s] for s in SIDE_LABELS}}


# ===========================================================================
# ANALYSIS 5: gate pass rate + discard reason distribution
# ===========================================================================
def analysis5_gates(recs, out, lines):
    n = len(recs)
    passed = [r for r in recs if r["gates"]["all_pass"]]
    fail_counter = Counter()
    for r in recs:
        if r["gates"]["all_pass"]:
            continue
        for g in GATE_KEYS:
            if not r["gates"].get(g, True):
                fail_counter[g] += 1
    n_fail = n - len(passed)

    x = np.arange(len(GATE_KEYS))
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(x, [fail_counter.get(g, 0) for g in GATE_KEYS], color="#C44E52")
    ax.set_xticks(x); ax.set_xticklabels([g.split("_")[0] for g in GATE_KEYS])
    ax.set_ylabel("frames failing this gate")
    ax.set_title(f"(5) gate failures  pass={len(passed)}/{n} ({100*len(passed)/max(1,n):.1f}%)  "
                 f"discarded={n_fail}")
    for i, g in enumerate(GATE_KEYS):
        ax.text(i, fail_counter.get(g, 0), str(fail_counter.get(g, 0)), ha="center", va="bottom")
    fig.tight_layout(); fig.savefig(os.path.join(out, "a5_gates.png"), dpi=110)
    plt.close(fig)

    lines.append("=" * 78)
    lines.append("ANALYSIS 5: safety-gate pass rate + discard (G1-G5) breakdown")
    lines.append("-" * 78)
    lines.append(f"  frames rendered (realize_ok) = {n}")
    lines.append(f"  ALL_PASS (kept)  = {len(passed)} ({100*len(passed)/max(1,n):.1f}%)")
    lines.append(f"  discarded (>=1 gate fail) = {n_fail} ({100*n_fail/max(1,n):.1f}%)")
    lines.append("  per-gate fail counts (a frame may fail several):")
    for g in GATE_KEYS:
        lines.append(f"    {g:<22} {fail_counter.get(g,0):>4}  ({100*fail_counter.get(g,0)/max(1,n):.1f}% of rendered)")
    lines.append("")
    return {"rendered": n, "kept": len(passed), "discarded": n_fail,
            "gate_fail_counts": dict(fail_counter)}


# ===========================================================================
# ANALYSIS 6: correction proposal (PROPOSAL ONLY — do not change f_target dist)
# ===========================================================================
def analysis6_correction(bin_bias, f_meta, side_res, lines):
    lines.append("=" * 78)
    lines.append("ANALYSIS 6: correction-coefficient PROPOSAL (do NOT apply / do NOT change f dist)")
    lines.append("-" * 78)
    # occluder-only systematic bias (the actuator we can adjust)
    occ_bias = f_meta.get("occ_bias")
    if occ_bias is None:
        lines.append("  no occluder-delivery data -> no proposal.")
        lines.append("")
        return {}
    bm, bs = occ_bias
    lines.append(f"  occluder delivery bias (f_occ_actual - f_need_plan): mean={bm:+.3f} std={bs:.3f}")
    # ratio-form suggestion: if occluder consistently over/under-delivers, scale A_target.
    # f_occ ~ f_need + bm ; to hit f_need, aim A_target' = A_target * f_need/(f_need+bm) ~ (1 - bm/mean_fneed).
    if abs(bm) < 0.02:
        lines.append("  -> occluder delivery within +-0.02: NO correction warranted.")
        prop = {"occluder": "none (bias<0.02)"}
    else:
        sign = "over" if bm > 0 else "under"
        lines.append(f"  -> occluder systematically {sign}-delivers by {bm:+.3f}. PROPOSAL (not applied):")
        lines.append(f"       scale the occluder overlap target A_target by factor ~ f_need/(f_need+{bm:+.3f})")
        lines.append(f"       (additive alternative: subtract {bm:+.3f} from f_need before inverting d_occ).")
        prop = {"occluder_bias_mean": bm, "suggested": "scale A_target toward f_need/(f_need+bias)"}
    # per-bin note
    lines.append("  per-f_target_bin total-occlusion bias (cargo+occluder, for reference):")
    for b in range(4):
        if b in bin_bias:
            lines.append(f"    bin{b} {F_TARGET_LABELS[b]:<11} bias_mean={bin_bias[b][0]:+.3f} std={bin_bias[b][1]:.3f}")
    lines.append("  NOTE: f_target bin fractions are FIXED by prescription - this proposal only")
    lines.append("        concerns the occluder depth/overlap SOLVE, never the f_target sampling.")
    lines.append("")
    return prop


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="data/pallet/archive/superseded_runs/_v2_calib_200/calib_records.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    records_path = args.records
    if not os.path.isabs(records_path):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        records_path = os.path.join(root, records_path)
    out = args.out or os.path.join(os.path.dirname(records_path), "analysis")
    os.makedirs(out, exist_ok=True)

    recs = load(records_path)
    lines = []
    lines.append(f"# v2 Phase D calibration analysis  (n_realized={len(recs)})")
    lines.append(f"# records: {records_path}")
    lines.append("")

    bin_bias, f_meta = analysis1_f(recs, out, lines)
    elev_res = analysis2_elev(recs, out, lines)
    sc_res = analysis3_sizeclass(recs, out, lines)
    side_res = analysis4_side(recs, out, lines)
    gate_res = analysis5_gates(recs, out, lines)
    prop = analysis6_correction(bin_bias, f_meta, side_res, lines)

    report = os.path.join(out, "phaseD_analysis_report.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    summ = {"n_realized": len(recs), "analysis1_f": f_meta, "analysis2_elev": elev_res,
            "analysis3_sizeclass": sc_res, "analysis4_side": side_res,
            "analysis5_gates": gate_res, "analysis6_proposal": prop}
    with open(os.path.join(out, "phaseD_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, indent=2, default=lambda o: None)

    print("\n".join(lines))
    print(f"\n[figures + report] {out}")


if __name__ == "__main__":
    main()
