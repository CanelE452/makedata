"""v2_pipeline dry-run design-validation harness (v2 규약 Phase C / iter-B).

Runs sample_frame + solve_placement ONLY (bpy=NONE, render=NONE). ACCEPT-TIME quota:
generate_accepted() advances the quota only when a frame is accepted, so the ACCEPTED set
matches the prescription (rejected cells self-correct). Produces an A-B of the occluder
geometry — LEGACY (whole-silhouette, iter-A) vs LATERAL (partial-overlap, iter-B) — to show
that the lateral-offset fix RESTORES large-asset usage (the real goal), while keeping the
pass rate >= 70% (NOT chasing a higher pass rate).

Outputs (abs paths printed at end):
  accept-distribution (a) on the ACCEPTED set vs prescription (+ attempted set for ref)
  reject breakdown + C1-by-mesh, LEGACY vs LATERAL
  occluder USAGE: per size_class + per asset, LEGACY vs LATERAL   <- success criterion
  side distribution (sampled over tries + placed on accepted)
  position_mode downgrade (should ~vanish: depth sampled in-band)
  (e) per-cell reject heatmaps ; (f) elev x V joint fill (accepted)
  before/after comparison table (pass rate, reasons, size_class usage, accept-dist)

Usage:
  python scripts/data_prep/blender/audit_v2_dryrun.py --n 40000 --seed 7000
"""

from __future__ import annotations

import argparse
import os
import time
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import v2_pipeline as vp

_THIS = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "data", "pallet", "runs", "diagnostics", "v2_dryrun_audit")

SIZE_ORDER = ["large", "road", "medium", "indoor", "small"]


def _parse_c1_mesh(detail):
    return detail.split("=", 1)[1] if detail.startswith("mesh=") else "unknown"


# ---------------------------------------------------------------------------
def run_mode(lateral, n_target, seed, assets):
    """One accept-time run in a given occluder mode. Returns a dict of stats + raw."""
    vp.LATERAL_OFFSET_ENABLED = lateral
    trace = []
    accepted, rejects, qs, attempts = vp.generate_accepted(
        n_target, seed, assets, trace=trace)
    return {
        "lateral": lateral, "accepted": accepted, "rejects": rejects,
        "attempts": attempts, "trace": trace,
        "pass_rate": len(accepted) / attempts if attempts else 0.0,
    }


# ---- axis distribution (reused for accepted + attempted spec lists) --------
def axis_rows(specs, assets):
    summ = vp.summarize(specs)
    n = summ["_n"]
    rows = []
    pal = {p: 1.0 / len(assets.pallet_types) for p in assets.pallet_types}

    def add(axis, tally, frac_map, denom):
        for k, c in tally.items():
            rows.append((axis, str(k), c, c / denom if denom else 0.0, frac_map.get(k)))

    add("scene_preset", summ["scene_preset"], dict(zip(vp.SCENE_PRESETS, vp.SCENE_PRESET_FRAC)), n)
    add("proj_size_bin", summ["proj_size_bin"], dict(enumerate(vp.PROJ_SIZE_FRAC)), n)
    add("elev_bin", summ["elev_bin"], dict(enumerate(vp.ELEV_BIN_FRAC)), n)
    add("v_target", summ["v_target"], dict(zip(vp.V_VALUES, vp.V_FRAC)), n)
    add("f_target_bin", summ["f_target_bin"], dict(enumerate(vp.F_TARGET_FRAC)), n)
    add("position_mode", summ["position_mode"],
        dict(zip(vp.POSITION_MODES, vp.POSITION_MODE_FRAC)), summ["_n_occluded"])
    add("cargo_on", summ["cargo_on"], {False: vp.CARGO_FRAC[0], True: vp.CARGO_FRAC[1]}, n)
    add("aspect", summ["aspect"], dict(zip([a for a, _ in vp.ASPECTS], vp.ASPECT_FRAC)), n)
    add("pallet_type", summ["pallet_type"], pal, n)
    add("fx_mode", summ["fx_mode"], dict(zip(vp.FX_MODES, vp.FX_FRAC)), n)
    return rows


# ---- reject + C1 mesh ------------------------------------------------------
def reject_stats(res):
    rej = res["rejects"]
    reason = Counter(r.reason for r in rej)
    c1 = Counter(_parse_c1_mesh(r.detail) for r in rej if r.reason == "C1")
    return reason, c1


# ---- occluder usage (THE success metric) -----------------------------------
def usage_stats(res):
    occ = [p.occluder for p in res["accepted"] if p.occluder is not None]
    by_sc = Counter(o["size_class"] for o in occ)
    by_asset = Counter(o["name"] for o in occ)
    return len(occ), by_sc, by_asset


# ---- side distribution -----------------------------------------------------
def side_stats(res):
    placed = Counter(p.occluder.get("side") for p in res["accepted"]
                     if p.occluder is not None)
    sampled = Counter(t.get("side") for t in res["trace"])   # every try (incl fails)
    return placed, sampled


# ---- position_mode downgrade ----------------------------------------------
def downgrade_stats(res):
    stat = defaultdict(lambda: {"placed": 0, "down": 0})
    for p in res["accepted"]:
        o = p.occluder
        if o is None or o.get("position_mode") is None:
            continue
        stat[o["position_mode"]]["placed"] += 1
        if not o.get("in_position_band"):
            stat[o["position_mode"]]["down"] += 1
    return stat


# ---- cell reject heatmap ---------------------------------------------------
def cell_grid(res, row_of, col_of, n_rows, n_cols):
    total = np.zeros((n_rows, n_cols))
    rej = np.zeros((n_rows, n_cols))
    for p in res["accepted"]:
        total[row_of(p.spec), col_of(p.spec)] += 1
    for p in res["rejects"]:
        r, c = row_of(p.spec), col_of(p.spec)
        total[r, c] += 1
        rej[r, c] += 1
    rate = np.divide(rej, total, out=np.full_like(rej, np.nan), where=total > 0)
    return rate, total


# ---- elev x V joint fill (accepted) ----------------------------------------
def joint_fill(accepted):
    E, Vn = len(vp.ELEV_BIN_EDGES), len(vp.V_VALUES)
    cnt = np.zeros((E, Vn))
    for p in accepted:
        cnt[p.spec.elev_bin, vp.V_VALUES.index(p.spec.v_target)] += 1
    emp = cnt / max(1, len(accepted))
    presc = np.array(vp.ELEV_V_JOINT)
    fill = np.divide(emp, presc, out=np.full_like(emp, np.nan), where=presc > 1e-9)
    return emp, presc, fill


# ===========================================================================
# figures
# ===========================================================================
def fig_usage_sizeclass(before, after, path):
    scb = usage_stats(before)[1]
    sca = usage_stats(after)[1]
    nb = sum(scb.values()) or 1
    na = sum(sca.values()) or 1
    x = np.arange(len(SIZE_ORDER))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    ax1.bar(x - 0.2, [scb.get(s, 0) / nb for s in SIZE_ORDER], 0.4,
            label="LEGACY (before)", color="#B0B0B0")
    ax1.bar(x + 0.2, [sca.get(s, 0) / na for s in SIZE_ORDER], 0.4,
            label="LATERAL (after)", color="#DD8452")
    ax1.set_xticks(x); ax1.set_xticklabels(SIZE_ORDER)
    ax1.set_ylabel("fraction of placed occluders")
    ax1.set_title("occluder USAGE by size_class (fraction)")
    ax1.legend()
    ax2.bar(x - 0.2, [scb.get(s, 0) for s in SIZE_ORDER], 0.4,
            label="LEGACY (before)", color="#B0B0B0")
    ax2.bar(x + 0.2, [sca.get(s, 0) for s in SIZE_ORDER], 0.4,
            label="LATERAL (after)", color="#DD8452")
    ax2.set_xticks(x); ax2.set_xticklabels(SIZE_ORDER)
    ax2.set_ylabel("count")
    ax2.set_title("occluder USAGE by size_class (count)")
    ax2.legend()
    for i, s in enumerate(SIZE_ORDER):
        ax2.text(i - 0.2, scb.get(s, 0), str(scb.get(s, 0)), ha="center", va="bottom", fontsize=7)
        ax2.text(i + 0.2, sca.get(s, 0), str(sca.get(s, 0)), ha="center", va="bottom", fontsize=7)
    fig.suptitle("large-asset usage recovery (success criterion)", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=110); plt.close(fig)


def fig_usage_assets(after, path, top=30):
    _, _, by_asset = usage_stats(after)
    items = by_asset.most_common(top)
    names = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(11, 10))
    y = np.arange(len(names))
    ax.barh(y, vals, color="#8172B3")
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8); ax.invert_yaxis()
    ax.set_xlabel("times placed (accepted frames)")
    ax.set_title(f"(after) top {len(names)} occluder assets by usage")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_side(after, path):
    placed, sampled = side_stats(after)
    labs = vp.SIDE_LABELS
    ns = sum(sampled.values()) or 1
    npl = sum(placed.values()) or 1
    x = np.arange(len(labs))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - 0.2, [sampled.get(s, 0) / ns for s in labs], 0.4,
           label="sampled (all tries)", color="#4C72B0")
    ax.bar(x + 0.2, [placed.get(s, 0) / npl for s in labs], 0.4,
           label="placed (accepted)", color="#55A868")
    ax.set_xticks(x); ax.set_xticklabels(labs)
    ax.set_ylabel("fraction"); ax.set_title("(after) occluder side: sampled vs placed")
    ax.legend()
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_reject_compare(before, after, path):
    order = ["camera_distance_out_of_range", "v_below_min", "d_occ_fail",
             "penetration", "resample_exhausted", "C1", "C2"]
    rb, cb = reject_stats(before)
    ra, ca = reject_stats(after)
    x = np.arange(len(order))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    ax1.bar(x - 0.2, [rb.get(k, 0) for k in order], 0.4, label="LEGACY", color="#B0B0B0")
    ax1.bar(x + 0.2, [ra.get(k, 0) for k in order], 0.4, label="LATERAL", color="#C44E52")
    ax1.set_xticks(x); ax1.set_xticklabels(order, rotation=25, ha="right")
    ax1.set_ylabel("reject count"); ax1.set_title("reject reasons: LEGACY vs LATERAL")
    ax1.legend()
    mesh = ["pallet", "cargo", "distractor", "background", "unknown"]
    xm = np.arange(len(mesh))
    ax2.bar(xm - 0.2, [cb.get(m, 0) for m in mesh], 0.4, label="LEGACY", color="#B0B0B0")
    ax2.bar(xm + 0.2, [ca.get(m, 0) for m in mesh], 0.4, label="LATERAL", color="#55A868")
    ax2.set_xticks(xm); ax2.set_xticklabels(mesh)
    ax2.set_ylabel("C1 count"); ax2.set_title("C1 by mesh: LEGACY vs LATERAL (clearance)")
    ax2.legend()
    for i, m in enumerate(mesh):
        ax2.text(i - 0.2, cb.get(m, 0), str(cb.get(m, 0)), ha="center", va="bottom", fontsize=7)
        ax2.text(i + 0.2, ca.get(m, 0), str(ca.get(m, 0)), ha="center", va="bottom", fontsize=7)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_accept_dist(after_acc, attempted_specs, assets, path):
    acc_rows = axis_rows([p.spec for p in after_acc], assets)
    att_rows = axis_rows(attempted_specs, assets)
    axes = ["scene_preset", "proj_size_bin", "elev_bin", "v_target",
            "f_target_bin", "position_mode", "cargo_on", "aspect"]
    att_map = {(a, k): emp for a, k, c, emp, pr in att_rows}
    fig, axs = plt.subplots(2, 4, figsize=(20, 9))
    for ax_name, sp in zip(axes, axs.ravel()):
        sub = [r for r in acc_rows if r[0] == ax_name]
        keys = [r[1] for r in sub]
        acc_emp = [r[3] for r in sub]
        presc = [r[4] if r[4] is not None else 0.0 for r in sub]
        att_emp = [att_map.get((ax_name, k), 0.0) for k in keys]
        x = np.arange(len(keys))
        sp.bar(x - 0.25, presc, 0.25, label="prescribed", color="#4C72B0")
        sp.bar(x, acc_emp, 0.25, label="ACCEPT dist", color="#DD8452")
        sp.bar(x + 0.25, att_emp, 0.25, label="attempted", color="#CCCCCC")
        sp.set_title(ax_name)
        sp.set_xticks(x); sp.set_xticklabels(keys, rotation=45, ha="right", fontsize=8)
        sp.legend(fontsize=7)
    fig.suptitle("(a) ACCEPT distribution vs prescription (attempted = grey ref)", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=110); plt.close(fig)


def _draw_heat(ax, rate, tot, row_lbl, col_lbl, title):
    im = ax.imshow(rate, cmap="Reds", vmin=0, vmax=max(0.5, np.nanmax(rate)))
    ax.set_xticks(range(len(col_lbl))); ax.set_xticklabels(col_lbl, rotation=20, ha="right")
    ax.set_yticks(range(len(row_lbl))); ax.set_yticklabels(row_lbl)
    ax.set_title(title)
    for i in range(rate.shape[0]):
        for j in range(rate.shape[1]):
            if tot[i, j] > 0:
                ax.text(j, i, f"{rate[i, j]:.2f}\nn={int(tot[i, j])}", ha="center",
                        va="center", fontsize=8, color="white" if rate[i, j] > 0.3 else "black")
    plt.colorbar(im, ax=ax, fraction=0.046)


def fig_heatmaps(after, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    r1, t1 = cell_grid(after, lambda s: 1 if s.cargo_on else 0, lambda s: s.f_target_bin, 2, 4)
    _draw_heat(ax1, r1, t1, ["cargo=off", "cargo=on"], vp.F_TARGET_LABELS,
               "(e) reject rate: cargo x f_target (after)")
    r2, t2 = cell_grid(after, lambda s: s.elev_bin, lambda s: s.f_target_bin,
                       len(vp.ELEV_BIN_EDGES), 4)
    elab = [f"{lo:.0f}-{hi:.0f}" for lo, hi in vp.ELEV_BIN_EDGES]
    _draw_heat(ax2, r2, t2, elab, vp.F_TARGET_LABELS, "(e) reject rate: elev x f_target (after)")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_joint(after, path):
    emp, presc, fill = joint_fill(after["accepted"])
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    elab = [f"{lo:.0f}-{hi:.0f}" for lo, hi in vp.ELEV_BIN_EDGES]
    im1 = ax1.imshow(emp, cmap="viridis"); ax1.set_title("(f) elev x V empirical (accepted)")
    im2 = ax2.imshow(fill, cmap="RdYlGn", vmin=0.5, vmax=1.5)
    ax2.set_title("(f) fill = empirical / prescribed")
    for ax, M, im in ((ax1, emp, im1), (ax2, fill, im2)):
        ax.set_xticks(range(len(vp.V_VALUES))); ax.set_xticklabels(vp.V_VALUES)
        ax.set_yticks(range(len(elab))); ax.set_yticklabels(elab)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, f"{M[i, j]:.3f}", ha="center", va="center", fontsize=7)
        plt.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


# ===========================================================================
def write_report(path, n, seed, before, after, assets, elapsed):
    L = []
    L.append(f"# v2_pipeline dry-run audit (iter-B)  n_accept={n} seed={seed}")
    L.append(f"generated in {elapsed:.1f}s ; bpy=NONE ; render=NONE ; ACCEPT-TIME quota\n")

    def blk(res, tag):
        pr = res["pass_rate"]
        L.append(f"## [{tag}] pass = {len(res['accepted'])}/{res['attempts']} = {pr:.4f} ({pr:.1%})")
        reason, c1 = reject_stats(res)
        for k in ["camera_distance_out_of_range", "v_below_min", "d_occ_fail",
             "penetration", "resample_exhausted", "C1", "C2"]:
            L.append(f"    {k:<20} n={reason.get(k, 0)}")
        L.append("    C1 by mesh: " + ", ".join(
            f"{m}={c1.get(m,0)}" for m in ["pallet", "cargo", "distractor", "background"]))
        nocc, by_sc, _ = usage_stats(res)
        L.append(f"    occluders placed = {nocc} ; size_class usage: " +
                 ", ".join(f"{s}={by_sc.get(s,0)}" for s in SIZE_ORDER))
        L.append("")

    blk(before, "LEGACY (before / whole-silhouette)")
    blk(after, "LATERAL (after / partial-overlap)")

    L.append("## before/after comparison (size_class usage)")
    _, scb, _ = usage_stats(before)
    _, sca, _ = usage_stats(after)
    nb = sum(scb.values()) or 1
    na = sum(sca.values()) or 1
    L.append("  size_class   LEGACY_n  LEGACY_%   LATERAL_n  LATERAL_%")
    for s in SIZE_ORDER:
        L.append(f"  {s:<10}  {scb.get(s,0):>7}   {100*scb.get(s,0)/nb:6.1f}%   "
                 f"{sca.get(s,0):>7}   {100*sca.get(s,0)/na:6.1f}%")
    L.append(f"  pass rate:   LEGACY {before['pass_rate']:.1%}   LATERAL {after['pass_rate']:.1%}")
    L.append("")

    placed, sampled = side_stats(after)
    ns = sum(sampled.values()) or 1
    npl = sum(placed.values()) or 1
    L.append("## (after) occluder side distribution")
    L.append("  side      sampled(all tries)   placed(accepted)")
    for s in vp.SIDE_LABELS:
        L.append(f"  {s:<8}  {sampled.get(s,0):>8} ({100*sampled.get(s,0)/ns:4.1f}%)   "
                 f"{placed.get(s,0):>8} ({100*placed.get(s,0)/npl:4.1f}%)")
    L.append(f"  (SIDE_WEIGHTS prescribed = {dict(zip(vp.SIDE_LABELS, vp.SIDE_WEIGHTS))})")
    L.append("")

    L.append("## (after) position_mode downgrade (occluder out of requested band)")
    for pm, v in downgrade_stats(after).items():
        rate = v["down"] / v["placed"] if v["placed"] else 0.0
        L.append(f"  {pm:<12} placed={v['placed']:<6} downgraded={v['down']:<5} rate={rate:.3f}")
    L.append("  (near-pallet band relaxed 0.55-0.90; depth sampled in-band -> ~0 downgrade)")
    L.append("")

    L.append("## (a) ACCEPT distribution vs prescription (after)  [attempted for ref]")
    acc_rows = axis_rows([p.spec for p in after["accepted"]], assets)
    att_specs = [p.spec for p in after["accepted"]] + [r.spec for r in after["rejects"]]
    att_rows = axis_rows(att_specs, assets)
    att_map = {(a, k): emp for a, k, c, emp, pr in att_rows}
    cur = None
    for axis, key, cnt, emp, presc in acc_rows:
        if axis != cur:
            L.append(f"  [{axis}]"); cur = axis
        ps = f"{presc:6.3f}" if presc is not None else "  -   "
        L.append(f"    {key:<14} accept={emp:6.3f}  presc={ps}  "
                 f"attempted={att_map.get((axis, key), 0):6.3f}")
    L.append("")

    emp, presc, fill = joint_fill(after["accepted"])
    elab = [f"{lo:.0f}-{hi:.0f}" for lo, hi in vp.ELEV_BIN_EDGES]
    L.append("## (f) elev x V joint fill (accept / prescribed)")
    L.append("  elev\\V  " + "".join(f"{v:>8}" for v in vp.V_VALUES))
    for i, lb in enumerate(elab):
        cells = "".join(f"{(emp[i][j]/presc[i][j] if presc[i][j]>1e-9 else 0):8.2f}"
                        for j in range(len(vp.V_VALUES)))
        L.append(f"  {lb:<7}{cells}")
    L.append("")

    _, _, by_asset = usage_stats(after)
    L.append("## (after) top 20 occluder assets by usage")
    for name, c in by_asset.most_common(20):
        L.append(f"  {name:<32} {c}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description="v2_pipeline iter-B dry-run audit (no Blender)")
    ap.add_argument("--n", type=int, default=40000, help="target ACCEPTED frames")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--out", type=str, default=DEFAULT_OUT)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    assets = vp.load_assets()
    print(f"[assets] pallets={assets.pallet_types} distractors={len(assets.distractors)}")

    t0 = time.time()
    before = run_mode(False, args.n, args.seed, assets)  # LEGACY
    after = run_mode(True, args.n, args.seed, assets)     # LATERAL
    vp.LATERAL_OFFSET_ENABLED = True
    elapsed = time.time() - t0

    import sys
    import json
    acc2, _, _, att2 = vp.generate_accepted(2000, args.seed, assets)
    pk = lambda p: json.dumps(p.to_dict(), sort_keys=True)
    det = all(pk(a) == pk(b) for a, b in zip(after["accepted"][:2000], acc2))
    print(f"[determinism] lateral accept subset identical={det}  bpy_in_modules={'bpy' in sys.modules}")
    print(f"[timing] {elapsed:.1f}s  LEGACY att={before['attempts']} LATERAL att={after['attempts']}")

    p = lambda name: os.path.join(args.out, name)
    fig_usage_sizeclass(before, after, p("usage_size_class.png"))
    fig_usage_assets(after, p("usage_asset_top.png"))
    fig_side(after, p("side_dist.png"))
    fig_reject_compare(before, after, p("reject_compare.png"))
    att_specs = [pp.spec for pp in after["accepted"]] + [r.spec for r in after["rejects"]]
    fig_accept_dist(after["accepted"], att_specs, assets, p("a_accept_dist.png"))
    fig_heatmaps(after, p("e_cell_reject_heatmap.png"))
    fig_joint(after, p("f_elev_v_joint_fill.png"))

    report = p("v2_dryrun_report.md")
    write_report(report, args.n, args.seed, before, after, assets, elapsed)

    nb = sum(usage_stats(before)[1].values()) or 1
    na = sum(usage_stats(after)[1].values()) or 1
    lb = usage_stats(before)[1].get("large", 0)
    la = usage_stats(after)[1].get("large", 0)
    print(f"\n[large usage]  LEGACY {lb} ({100*lb/nb:.1f}%)  ->  LATERAL {la} ({100*la/na:.1f}%)")
    print(f"[pass rate]  LEGACY {before['pass_rate']:.1%}  ->  LATERAL {after['pass_rate']:.1%}")
    print(f"[report] {report}")
    for name in ["usage_size_class.png", "usage_asset_top.png", "side_dist.png",
                 "reject_compare.png", "a_accept_dist.png", "e_cell_reject_heatmap.png",
                 "f_elev_v_joint_fill.png"]:
        print(f"[figure] {p(name)}")

    pr = after["pass_rate"]
    print("\n[judgment]")
    print(f"  pass rate {pr:.1%} {'OK (>=70%)' if pr >= 0.70 else '! < 70%'}")
    r1, t1 = cell_grid(after, lambda s: 1 if s.cargo_on else 0, lambda s: s.f_target_bin, 2, 4)
    labs = ["cargo=off", "cargo=on"]
    hot = [f"{labs[i]} x {vp.F_TARGET_LABELS[j]}={r1[i,j]:.1%}"
           for i in range(2) for j in range(4) if t1[i, j] > 0 and r1[i, j] > 0.50]
    print("  cells >50% reject: " + (", ".join(hot) if hot else "none"))


if __name__ == "__main__":
    main()
