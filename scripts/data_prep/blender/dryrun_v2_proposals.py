"""Phase 9B — PROPOSAL-driven bpy-free dry-run of sample_frame + solve_placement.

Different from ``audit_v2_dryrun.py`` (which targets a number of ACCEPTED frames and does a
LEGACY-vs-LATERAL occluder A/B): here the budget is a number of PROPOSALS (solve attempts),
which is what Section 9B asks for.  The proposal stream is the production one —
``run_v2_scene_logic.iter_proposals`` — so the draw order and the accept-time quota rule are
identical to the runner's ``--completion-mode usable`` path.

Nothing here touches bpy: only ``sample_frame`` (sampling) and ``solve_placement`` (pure
analytic geometry) run.  This validates numbers, NOT pixels: no statement about RGB/mask
quality or "training-ready" can be derived from it.

Checks (all reported as PASS/FAIL in the summary):
  1. camera_distance_target_m > MAX_CAMERA_DISTANCE_M            -> 0
  2. NaN / inf anywhere in the spec or the plan                   -> 0
  3. empty feasible projected-size interval (RuntimeError)        -> 0
  4. reject reason ``camera_distance_out_of_range``               -> 0
  5. same-seed determinism (streaming SHA-256 over the proposals) -> identical
  6. solve acceptance                                             -> >= 70 %
  7. max-attempt exhaustion / quota starvation                    -> 0
  8. unrelated-axis marginal error vs prescription                -> <= 0.01

Usage:
  python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 --tag 5k
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import v2_pipeline as vp  # noqa: E402
from analyze_v2_continuous import ecdf, pearson, spearman  # noqa: E402

_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "reports", "v2_revision")

ACCEPTANCE_MIN = 0.70
MARGINAL_TOL = 0.01
REJECT_ORDER = [
    "camera_distance_out_of_range",
    "v_below_min",
    "d_occ_fail",
    "penetration",
    "resample_exhausted",
    "C1",
    "C2",
]
QUANTS = [0.0, 0.05, 0.25, 0.50, 0.75, 0.95, 1.0]


def load_runner():
    """Import run_v2_scene_logic without executing it (it is bpy-free at import time)."""
    path = os.path.join(_THIS, "run_v2_scene_logic.py")
    spec = importlib.util.spec_from_file_location("run_v2_scene_logic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------
def nonfinite_paths(obj, prefix=""):
    """Every leaf path under `obj` whose float value is NaN or inf."""
    bad = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            bad.extend(nonfinite_paths(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            bad.extend(nonfinite_paths(value, f"{prefix}[{i}]"))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        if not math.isfinite(float(obj)):
            bad.append(prefix)
    return bad


def spec_target_distance(spec):
    """solve_placement step (1) recomputed from the spec alone (works for rejects too)."""
    ratio = max(float(spec.proj_size_ratio), 1e-3)
    return float(spec.fx) * vp.PALLET_W / (ratio * float(spec.resolution[0]))


def feasible_bins(fx, image_width):
    lower = vp.proj_size_feasible_lower(fx, image_width)
    return [max(lo, lower) < hi for lo, hi in vp.PROJ_SIZE_EDGES], lower


def canonical(proposal_index, plan, reject):
    payload = {
        "i": proposal_index,
        "accepted": plan is not None,
        "plan": plan.to_dict() if plan is not None else None,
        "reject": reject.to_dict() if reject is not None else None,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def quantile_row(values):
    arr = np.asarray([v for v in values if v is not None and math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return {}
    out = {f"q{int(q * 100):02d}": float(np.quantile(arr, q)) for q in QUANTS}
    out["mean"] = float(arr.mean())
    out["n"] = int(arr.size)
    return out


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def run_stream(runner, assets, n_proposals, seed, collect=True):
    """Drive iter_proposals for exactly n_proposals attempts.

    Returns dict with rows (or None), reject counter, digest, exception info.
    """
    rows = [] if collect else None
    rejects = Counter()
    n_accepted = 0
    nonfinite = []
    over_cap = []
    infeasible_error = None
    hasher = hashlib.sha256()

    stream = runner.iter_proposals(
        seed, assets, vp, placement_mode="constrained", max_proposals=n_proposals
    )
    n_seen = 0
    try:
        for proposal_index, plan, reject in stream:
            n_seen += 1
            hasher.update(canonical(proposal_index, plan, reject).encode("utf-8"))
            spec = plan.spec if plan is not None else reject.spec
            if plan is not None:
                n_accepted += 1
            else:
                rejects[reject.reason] += 1
            if not collect:
                continue

            payload = plan.to_dict() if plan is not None else reject.to_dict()
            bad = nonfinite_paths(payload)
            if bad:
                nonfinite.append((proposal_index, bad))

            d_spec = spec_target_distance(spec)
            d_plan = float(plan.camera_distance_target_m) if plan is not None else None
            if d_spec > vp.MAX_CAMERA_DISTANCE_M + 1e-6:
                over_cap.append((proposal_index, "spec", d_spec))
            if d_plan is not None and d_plan > vp.MAX_CAMERA_DISTANCE_M + 1e-6:
                over_cap.append((proposal_index, "plan", d_plan))

            feas, lower = feasible_bins(spec.fx, spec.resolution[0])
            lo, hi = vp.PROJ_SIZE_EDGES[spec.proj_size_bin]
            rows.append({
                "proposal_index": proposal_index,
                "accepted": int(plan is not None),
                "reject_reason": "" if plan is not None else reject.reason,
                "pallet_type": spec.pallet_type,
                "scene_preset": spec.scene_preset,
                "exposure_ev": spec.exposure_ev,
                "elev_bin": spec.elev_bin,
                "elevation_deg": spec.elevation_deg,
                "azimuth_bin": spec.azimuth_bin,
                "azimuth_deg": spec.azimuth_deg,
                "v_target": spec.v_target,
                "proj_size_bin": spec.proj_size_bin,
                "proj_size_ratio": spec.proj_size_ratio,
                "proj_size_feasible_lower": spec.proj_size_feasible_lower,
                "proj_size_bin_lo": lo,
                "proj_size_bin_hi": hi,
                "n_feasible_bins": sum(feas),
                "bin_feasible": int(feas[spec.proj_size_bin]),
                "aspect": spec.aspect,
                "image_width": spec.resolution[0],
                "image_height": spec.resolution[1],
                "fx_mode": spec.fx_mode,
                "fx": spec.fx,
                "f_target_bin": spec.f_target_bin,
                "f_target": spec.f_target,
                "position_mode": spec.position_mode or "",
                "cargo_on": int(spec.cargo_on),
                "camera_distance_spec_m": d_spec,
                "camera_distance_target_m": d_plan if d_plan is not None else "",
                "v_probe": plan.v_probe if plan is not None else "",
                "trunc_mode": plan.trunc_mode if plan is not None else "",
                "occluder": (plan.occluder or {}).get("name", "") if plan is not None else "",
            })
    except RuntimeError as exc:
        infeasible_error = f"{type(exc).__name__}: {exc}"

    return {
        "rows": rows,
        "rejects": rejects,
        "n_seen": n_seen,
        "n_accepted": n_accepted,
        "digest": hasher.hexdigest(),
        "nonfinite": nonfinite,
        "over_cap": over_cap,
        "infeasible_error": infeasible_error,
    }


# ---------------------------------------------------------------------------
# distributions
# ---------------------------------------------------------------------------
AXES = [
    # (name, row key, ordered keys, prescription, "related to the cap?")
    ("scene_preset", "scene_preset", vp.SCENE_PRESETS, vp.SCENE_PRESET_FRAC, False),
    ("elev_bin", "elev_bin", list(range(len(vp.ELEV_BIN_FRAC))), vp.ELEV_BIN_FRAC, False),
    ("azimuth_bin", "azimuth_bin", list(range(vp.AZIMUTH_NBINS)), vp.AZIMUTH_FRAC, False),
    ("v_target", "v_target", vp.V_VALUES, vp.V_FRAC, False),
    ("f_target_bin", "f_target_bin", list(range(len(vp.F_TARGET_FRAC))), vp.F_TARGET_FRAC, False),
    ("aspect", "aspect", [a for a, _ in vp.ASPECTS], vp.ASPECT_FRAC, False),
    ("fx_mode", "fx_mode", vp.FX_MODES, vp.FX_FRAC, False),
    ("cargo_on", "cargo_on", [0, 1], vp.CARGO_FRAC, False),
    ("proj_size_bin", "proj_size_bin", list(range(len(vp.PROJ_SIZE_FRAC))), vp.PROJ_SIZE_FRAC, True),
]


def axis_table(rows, assets):
    """Per-axis prescribed vs empirical (accepted set = the quota's target set)."""
    acc = [r for r in rows if r["accepted"]]
    out = []
    for name, key, keys, presc, related in AXES:
        acc_t = Counter(r[key] for r in acc)
        att_t = Counter(r[key] for r in rows)
        for k, want in zip(keys, presc):
            out.append({
                "axis": name,
                "key": str(k),
                "prescribed": want,
                "accepted_frac": acc_t.get(k, 0) / len(acc) if acc else 0.0,
                "attempted_frac": att_t.get(k, 0) / len(rows) if rows else 0.0,
                "accepted_n": acc_t.get(k, 0),
                "abs_err_accepted": abs((acc_t.get(k, 0) / len(acc) if acc else 0.0) - want),
                "cap_related": int(related),
            })
    # pallet_type (uniform over the blend types)
    ptypes = list(assets.pallet_types)
    acc_t = Counter(r["pallet_type"] for r in acc)
    att_t = Counter(r["pallet_type"] for r in rows)
    for k in ptypes:
        want = 1.0 / len(ptypes)
        out.append({
            "axis": "pallet_type", "key": k, "prescribed": want,
            "accepted_frac": acc_t.get(k, 0) / len(acc) if acc else 0.0,
            "attempted_frac": att_t.get(k, 0) / len(rows) if rows else 0.0,
            "accepted_n": acc_t.get(k, 0),
            "abs_err_accepted": abs((acc_t.get(k, 0) / len(acc) if acc else 0.0) - want),
            "cap_related": 0,
        })
    # position_mode is CONDITIONAL on f_target > 0 -> its own denominator
    occ_acc = [r for r in acc if r["position_mode"]]
    occ_att = [r for r in rows if r["position_mode"]]
    acc_t = Counter(r["position_mode"] for r in occ_acc)
    att_t = Counter(r["position_mode"] for r in occ_att)
    for k, want in zip(vp.POSITION_MODES, vp.POSITION_MODE_FRAC):
        out.append({
            "axis": "position_mode", "key": k, "prescribed": want,
            "accepted_frac": acc_t.get(k, 0) / len(occ_acc) if occ_acc else 0.0,
            "attempted_frac": att_t.get(k, 0) / len(occ_att) if occ_att else 0.0,
            "accepted_n": acc_t.get(k, 0),
            "abs_err_accepted": abs((acc_t.get(k, 0) / len(occ_acc) if occ_acc else 0.0) - want),
            "cap_related": 0,
        })
    return out


def proj_size_three_way(rows):
    """prescription / feasibility-conditioned / empirical for the projected-size axis."""
    acc = [r for r in rows if r["accepted"]]
    out = []
    for b, (lo, hi) in enumerate(vp.PROJ_SIZE_EDGES):
        n_feas = sum(
            1 for r in rows
            if max(lo, r["proj_size_feasible_lower"]) < hi
        )
        feas_rate = n_feas / len(rows) if rows else 0.0
        # feasibility-conditioned prescription: the mass a masked bin cannot take is
        # redistributed over the bins that ARE feasible on that draw.
        share = 0.0
        for r in rows:
            fe = [max(x, r["proj_size_feasible_lower"]) < y for x, y in vp.PROJ_SIZE_EDGES]
            tot = sum(f for f, fe_ok in zip(vp.PROJ_SIZE_FRAC, fe) if fe_ok)
            if fe[b] and tot > 0:
                share += vp.PROJ_SIZE_FRAC[b] / tot
        cond = share / len(rows) if rows else 0.0
        ratios = [r["proj_size_ratio"] for r in acc if r["proj_size_bin"] == b]
        out.append({
            "bin": b,
            "label": vp.PROJ_SIZE_LABELS[b],
            "edges": f"[{lo:.2f},{hi:.2f})",
            "prescribed": vp.PROJ_SIZE_FRAC[b],
            "feasible_rate": feas_rate,
            "feasibility_conditioned": cond,
            "accepted_frac": len(ratios) / len(acc) if acc else 0.0,
            "ratio_min": min(ratios) if ratios else float("nan"),
            "ratio_max": max(ratios) if ratios else float("nan"),
        })
    return out


def wilson_ci(k, n, z=1.96):
    """95% Wilson interval for a reject-reason share (stability of the estimate)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cross_tabs(rows):
    """accepted/rejected composition and the distance|projected-size conditional."""
    by_bin = []
    for b, (lo, hi) in enumerate(vp.PROJ_SIZE_EDGES):
        sub = [r for r in rows if r["proj_size_bin"] == b]
        acc = [r for r in sub if r["accepted"]]
        d = np.array([float(r["camera_distance_target_m"]) for r in acc]) if acc else np.array([])
        reasons = Counter(r["reject_reason"] for r in sub if not r["accepted"])
        by_bin.append({
            "bin": b, "label": vp.PROJ_SIZE_LABELS[b], "n": len(sub),
            "accept_rate": len(acc) / len(sub) if sub else 0.0,
            "reasons": reasons,
            "d_min": float(d.min()) if d.size else float("nan"),
            "d_q25": float(np.quantile(d, .25)) if d.size else float("nan"),
            "d_q50": float(np.quantile(d, .50)) if d.size else float("nan"),
            "d_q75": float(np.quantile(d, .75)) if d.size else float("nan"),
            "d_max": float(d.max()) if d.size else float("nan"),
        })
    by_elev = []
    for e in range(len(vp.ELEV_BIN_FRAC)):
        sub = [r for r in rows if r["elev_bin"] == e]
        acc = [r for r in sub if r["accepted"]]
        by_elev.append({
            "elev_bin": e, "edges": vp.ELEV_BIN_EDGES[e], "n": len(sub),
            "accept_rate": len(acc) / len(sub) if sub else 0.0,
            "reasons": Counter(r["reject_reason"] for r in sub if not r["accepted"]),
        })
    return by_bin, by_elev


def continuous_table(rows):
    acc = [r for r in rows if r["accepted"]]
    fields = {
        "camera_distance_target_m": [r["camera_distance_target_m"] for r in acc],
        "camera_distance_spec_m(all proposals)": [r["camera_distance_spec_m"] for r in rows],
        "proj_size_ratio": [r["proj_size_ratio"] for r in acc],
        "proj_size_feasible_lower": [r["proj_size_feasible_lower"] for r in acc],
        "elevation_deg": [r["elevation_deg"] for r in acc],
        "azimuth_deg": [r["azimuth_deg"] for r in acc],
        "fx": [r["fx"] for r in acc],
        "f_target": [r["f_target"] for r in acc],
        "exposure_ev": [r["exposure_ev"] for r in acc],
    }
    out = []
    for name, values in fields.items():
        vals = [float(v) for v in values if v != "" and v is not None]
        row = {"field": name}
        row.update(quantile_row(vals))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# joint EDA: distance x fx x aspect x projected size
# ---------------------------------------------------------------------------
def joint_eda_figure(rows, path_png, path_pdf, tag):
    acc = [r for r in rows if r["accepted"]]
    d = np.array([float(r["camera_distance_target_m"]) for r in acc])
    ratio = np.array([r["proj_size_ratio"] for r in acc])
    fx = np.array([r["fx"] for r in acc])
    width = np.array([float(r["image_width"]) for r in acc])
    aspects = [r["aspect"] for r in acc]

    fig, axs = plt.subplots(2, 3, figsize=(19, 11))

    # (1) the governing identity d = fx*W_pallet/(ratio*image_width)
    ax = axs[0, 0]
    sc = ax.scatter(ratio, d, c=fx, s=4, alpha=0.35, cmap="viridis")
    grid = np.linspace(0.02, 1.0, 200)
    for fxv, wv, style in ((300.0, 960.0, "--"), (605.9, 640.0, "-"), (700.0, 560.0, ":")):
        ax.plot(grid, fxv * vp.PALLET_W / (grid * wv), style, color="crimson", lw=1.2,
                label=f"fx={fxv:.0f}, W={wv:.0f}")
    ax.axhline(vp.MAX_CAMERA_DISTANCE_M, color="black", lw=1.4)
    ax.text(0.98, vp.MAX_CAMERA_DISTANCE_M, f" cap {vp.MAX_CAMERA_DISTANCE_M:.0f} m",
            va="bottom", ha="right", fontsize=8)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("projected size (pallet width / image width)")
    ax.set_ylabel("camera distance target [m]")
    ax.set_title("(1) distance vs projected size (colour = fx px)")
    ax.legend(fontsize=7)
    plt.colorbar(sc, ax=ax, fraction=0.046, label="fx [px]")

    # (2) distance ECDF per aspect
    ax = axs[0, 1]
    for name, _res in vp.ASPECTS:
        sel = d[[i for i, a in enumerate(aspects) if a == name]]
        if sel.size:
            x, y = ecdf(sel)
            ax.step(x, y, where="post", label=f"{name} (n={sel.size})")
    ax.set_xlabel("camera distance target [m]"); ax.set_ylabel("ECDF")
    ax.set_xlim(0, vp.MAX_CAMERA_DISTANCE_M)
    ax.set_title("(2) distance ECDF by aspect")
    ax.legend(fontsize=7)

    # (3) distance ECDF per projected-size bin
    ax = axs[0, 2]
    bins = np.array([r["proj_size_bin"] for r in acc])
    for b in range(len(vp.PROJ_SIZE_EDGES)):
        sel = d[bins == b]
        if sel.size:
            x, y = ecdf(sel)
            ax.step(x, y, where="post", label=f"bin{b} {vp.PROJ_SIZE_LABELS[b]} (n={sel.size})")
    ax.set_xlabel("camera distance target [m]"); ax.set_ylabel("ECDF")
    ax.set_xlim(0, vp.MAX_CAMERA_DISTANCE_M)
    ax.set_title("(3) distance ECDF by projected-size bin")
    ax.legend(fontsize=7)

    # (4) distance vs fx, colour = projected-size bin
    ax = axs[1, 0]
    for b in range(len(vp.PROJ_SIZE_EDGES)):
        m = bins == b
        ax.scatter(fx[m], d[m], s=4, alpha=0.35, label=f"bin{b}")
    ax.axhline(vp.MAX_CAMERA_DISTANCE_M, color="black", lw=1.4)
    ax.set_yscale("log")
    ax.set_xlabel("fx [px]"); ax.set_ylabel("camera distance target [m]")
    ax.set_title("(4) distance vs fx by projected-size bin")
    ax.legend(fontsize=7, ncol=2)

    # (5) hexbin of the scale-free driver fx/image_width against distance
    ax = axs[1, 1]
    hb = ax.hexbin(fx / width, d, gridsize=40, cmap="magma", bins="log")
    ax.axhline(vp.MAX_CAMERA_DISTANCE_M, color="white", lw=1.2)
    ax.set_xlabel("fx / image_width  (angular scale, aspect-folded)")
    ax.set_ylabel("camera distance target [m]")
    ax.set_title("(5) distance vs fx/image_width density")
    plt.colorbar(hb, ax=ax, fraction=0.046, label="log10 count")

    # (6) numeric panel
    ax = axs[1, 2]; ax.axis("off")
    logd, logr = np.log(d), np.log(ratio)
    lines = [
        f"n accepted = {len(acc)}   (proposals = {len(rows)})",
        f"max distance          = {d.max():.4f} m   (cap {vp.MAX_CAMERA_DISTANCE_M})",
        f"distance q50 / q95    = {np.quantile(d, .5):.3f} / {np.quantile(d, .95):.3f} m",
        "",
        "Pearson / Spearman (accepted set)",
        f"  log d  vs log ratio : {pearson(logd, logr):+.4f} / {spearman(logd, logr):+.4f}",
        f"  log d  vs log fx    : {pearson(logd, np.log(fx)):+.4f} / {spearman(logd, np.log(fx)):+.4f}",
        f"  log d  vs log width : {pearson(logd, np.log(width)):+.4f} / {spearman(logd, np.log(width)):+.4f}",
        f"  log d  vs log(fx/W) : {pearson(logd, np.log(fx / width)):+.4f} / "
        f"{spearman(logd, np.log(fx / width)):+.4f}",
        "",
        "identity residual  d - fx*1.1/(ratio*W)",
    ]
    resid = d - fx * vp.PALLET_W / (ratio * width)
    lines.append(f"  max |residual|      = {np.abs(resid).max():.3e} m")
    lines.append("")
    lines.append("distance q50 [m] by aspect x projected-size bin")
    lines.append("  aspect    " + "".join(f"{f'bin{b}':>9}" for b in range(5)))
    for name, _res in vp.ASPECTS:
        idx = np.array([i for i, a in enumerate(aspects) if a == name], dtype=int)
        cells = ""
        for b in range(5):
            sel = d[idx[bins[idx] == b]] if idx.size else np.array([])
            cells += f"{np.quantile(sel, .5):9.2f}" if sel.size else "        -"
        lines.append(f"  {name:<9} " + cells)
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=9)
    ax.set_title("(6) joint relationship summary", loc="left")

    fig.suptitle(
        f"v2 bpy-free dry-run [{tag}] — camera distance x fx x aspect x projected size "
        f"(geometry only; no RGB/mask evidence)", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path_png, dpi=300)
    fig.savefig(path_pdf)
    plt.close(fig)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def build_checks(result, result2, rows, axis_rows, n_proposals, runner):
    acc = result["n_accepted"]
    n = result["n_seen"]
    acceptance = acc / n if n else 0.0
    unrelated = [r for r in axis_rows if not r["cap_related"]]
    max_unrelated = max((r["abs_err_accepted"] for r in unrelated), default=0.0)
    worst = max(unrelated, key=lambda r: r["abs_err_accepted"]) if unrelated else None
    related = [r for r in axis_rows if r["cap_related"]]
    max_related = max((r["abs_err_accepted"] for r in related), default=0.0)
    d_all = [r["camera_distance_spec_m"] for r in rows]
    d_acc = [float(r["camera_distance_target_m"]) for r in rows if r["accepted"]]
    # operational definition of "max-attempt exhaustion": the production runner budgets
    # USABLE_PROPOSAL_STREAM_FACTOR proposals per delivered frame (and generate_accepted
    # budgets n_target*20). Exhaustion happens iff 1/acceptance exceeds that factor.
    factor = getattr(runner, "USABLE_PROPOSAL_STREAM_FACTOR", 20)
    need = (1.0 / acceptance) if acceptance > 0 else float("inf")
    starved = [
        r for r in axis_rows
        if r["prescribed"] > 0 and r["accepted_n"] == 0
    ]

    checks = [
        ("proposals run == requested", n == n_proposals, f"{n} / {n_proposals}"),
        ("camera_distance_target_m > 10.0 m",
         len([x for x in d_acc if x > vp.MAX_CAMERA_DISTANCE_M + 1e-6]) == 0,
         f"count=0 ; max={max(d_acc):.6f} m (cap {vp.MAX_CAMERA_DISTANCE_M})"
         if d_acc else "no accepted plans"),
        ("spec-implied distance > 10.0 m (incl. rejected)",
         len([x for x in d_all if x > vp.MAX_CAMERA_DISTANCE_M + 1e-6]) == 0,
         f"count={len([x for x in d_all if x > vp.MAX_CAMERA_DISTANCE_M + 1e-6])} ; "
         f"max={max(d_all):.6f} m"),
        ("NaN / inf in spec or plan", len(result["nonfinite"]) == 0,
         f"count={len(result['nonfinite'])}"),
        ("empty feasible projected-size interval",
         result["infeasible_error"] is None
         and all(r["n_feasible_bins"] > 0 and r["bin_feasible"] for r in rows),
         f"RuntimeError={result['infeasible_error']} ; "
         f"min feasible bins per draw={min(r['n_feasible_bins'] for r in rows)}"),
        ("reject camera_distance_out_of_range",
         result["rejects"].get("camera_distance_out_of_range", 0) == 0,
         f"count={result['rejects'].get('camera_distance_out_of_range', 0)}"),
        ("same-seed determinism", result["digest"] == result2["digest"],
         f"sha256 run1={result['digest'][:16]}… run2={result2['digest'][:16]}… ; "
         f"accepted {result['n_accepted']} vs {result2['n_accepted']}"),
        ("solve acceptance >= 70%", acceptance >= ACCEPTANCE_MIN,
         f"{acc}/{n} = {acceptance:.4f} ({acceptance:.2%})"),
        ("max-attempt exhaustion", need <= factor,
         f"proposals needed per accepted frame = {need:.3f} <= budget factor {factor}"),
        ("quota starvation (prescribed cell with 0 accepted)", len(starved) == 0,
         f"count={len(starved)}"
         + ("" if not starved else " ; " + ", ".join(f"{s['axis']}={s['key']}" for s in starved))),
        ("unrelated marginal error <= 0.01", max_unrelated <= MARGINAL_TOL,
         f"max={max_unrelated:.5f}"
         + (f" ({worst['axis']}={worst['key']})" if worst else "")),
        ("projected-size marginal error <= 0.01 (cap-related axis)",
         max_related <= MARGINAL_TOL, f"max={max_related:.5f}"),
    ]
    return checks, acceptance


def write_summary(path, tag, args, result, checks, acceptance, rows, axis_rows, ps_rows,
                  cont_rows, elapsed, fig_rel):
    n = result["n_seen"]
    L = []
    L.append(f"# v2 bpy-free dry-run — {n} proposals (tag `{tag}`)")
    L.append("")
    L.append(f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')} ; wall {elapsed:.1f} s")
    L.append(f"- seed={args.seed} ; placement_mode=constrained ; "
             f"stream=`run_v2_scene_logic.iter_proposals` (production draw order)")
    L.append(f"- budget unit = **proposals** (solve attempts), not accepted frames")
    L.append(f"- bpy imported: {'bpy' in sys.modules} ; renders: 0 ; images written: 0")
    L.append("")
    L.append("> Scope [확인]: this exercises `sample_frame` + `solve_placement` only. It says "
             "NOTHING about RGB/mask/lighting quality and is not evidence of training-readiness.")
    L.append("")
    L.append("## Checks")
    L.append("")
    L.append("```")
    L.append(f"{'check':<52} {'verdict':<8} detail")
    L.append("-" * 118)
    for name, ok, detail in checks:
        L.append(f"{name:<52} {'PASS' if ok else 'FAIL':<8} {detail}")
    L.append("```")
    L.append("")

    L.append("## Reject breakdown (share of proposals, 95% Wilson interval)")
    L.append("")
    L.append("```")
    L.append(f"{'reason':<32} {'count':>8} {'share':>9} {'95% CI':>20}")
    L.append("-" * 72)
    for reason in REJECT_ORDER:
        c = result["rejects"].get(reason, 0)
        lo, hi = wilson_ci(c, n)
        L.append(f"{reason:<32} {c:>8} {c / n:>9.4f} {f'[{lo:.4f}, {hi:.4f}]':>20}")
    other = {k: v for k, v in result["rejects"].items() if k not in REJECT_ORDER}
    for reason, c in sorted(other.items()):
        lo, hi = wilson_ci(c, n)
        L.append(f"{reason + ' (other)':<32} {c:>8} {c / n:>9.4f} {f'[{lo:.4f}, {hi:.4f}]':>20}")
    L.append("-" * 72)
    lo, hi = wilson_ci(result["n_accepted"], n)
    L.append(f"{'accepted':<32} {result['n_accepted']:>8} {acceptance:>9.4f} "
             f"{f'[{lo:.4f}, {hi:.4f}]':>20}")
    L.append("```")
    L.append("")

    by_bin, by_elev = cross_tabs(rows)
    L.append("## accepted/rejected composition x projected-size bin, and distance | bin")
    L.append("")
    L.append("```")
    L.append(f"{'bin':<4} {'label':<8} {'n':>7} {'accept':>8} " +
             "".join(f"{r[:12]:>13}" for r in REJECT_ORDER[1:]) +
             f"{'d_min':>8}{'d_q25':>8}{'d_q50':>8}{'d_q75':>8}{'d_max':>8}")
    L.append("-" * 140)
    for r in by_bin:
        cells = "".join(f"{r['reasons'].get(k, 0):>13}" for k in REJECT_ORDER[1:])
        L.append(f"{r['bin']:<4} {r['label']:<8} {r['n']:>7} {r['accept_rate']:>8.4f} " + cells +
                 f"{r['d_min']:>8.2f}{r['d_q25']:>8.2f}{r['d_q50']:>8.2f}"
                 f"{r['d_q75']:>8.2f}{r['d_max']:>8.2f}")
    L.append("```")
    L.append("")
    L.append("Distances are metres over the ACCEPTED plans of that bin "
             "(the conditional distribution of camera distance given projected size).")
    L.append("")
    L.append("```")
    L.append(f"{'elev_bin':<10} {'range_deg':<12} {'n':>7} {'accept':>8} " +
             "".join(f"{r[:12]:>13}" for r in REJECT_ORDER[1:]))
    L.append("-" * 108)
    for r in by_elev:
        cells = "".join(f"{r['reasons'].get(k, 0):>13}" for k in REJECT_ORDER[1:])
        lo_e, hi_e = r["edges"]
        L.append(f"{r['elev_bin']:<10} {f'{lo_e:.1f}-{hi_e:.1f}':<12} {r['n']:>7} "
                 f"{r['accept_rate']:>8.4f} " + cells)
    L.append("```")
    L.append("")

    L.append("## Projected-size axis — prescription / feasibility-conditioned / empirical")
    L.append("")
    L.append("```")
    L.append(f"{'bin':<4} {'label':<8} {'edges':<14} {'presc':>7} {'feas_rate':>10} "
             f"{'feas_cond':>10} {'accepted':>9} {'ratio_min':>10} {'ratio_max':>10}")
    L.append("-" * 88)
    for r in ps_rows:
        L.append(f"{r['bin']:<4} {r['label']:<8} {r['edges']:<14} {r['prescribed']:>7.3f} "
                 f"{r['feasible_rate']:>10.4f} {r['feasibility_conditioned']:>10.4f} "
                 f"{r['accepted_frac']:>9.4f} {r['ratio_min']:>10.4f} {r['ratio_max']:>10.4f}")
    L.append("```")
    L.append("")
    L.append("`feas_rate` = share of draws where the bin was reachable under the 10 m cap. "
             "`feas_cond` = prescription renormalised over the feasible bins of each draw "
             "(what a memoryless masked sampler would deliver); the accept-time quota deficit "
             "pulls the empirical column back to the flat prescription instead.")
    L.append("")

    L.append("## Per-axis marginals (accepted set = the set the quota targets)")
    L.append("")
    L.append("```")
    L.append(f"{'axis':<16} {'key':<14} {'presc':>7} {'accepted':>9} {'attempted':>10} "
             f"{'abs_err':>9} {'n':>7}")
    L.append("-" * 78)
    cur = None
    for r in axis_rows:
        if r["axis"] != cur:
            if cur is not None:
                L.append("")
            cur = r["axis"]
        L.append(f"{r['axis']:<16} {r['key']:<14} {r['prescribed']:>7.4f} "
                 f"{r['accepted_frac']:>9.4f} {r['attempted_frac']:>10.4f} "
                 f"{r['abs_err_accepted']:>9.5f} {r['accepted_n']:>7}")
    L.append("```")
    L.append("")

    L.append("## Continuous variables (accepted set unless noted)")
    L.append("")
    L.append("```")
    head = ["field", "n", "min", "q05", "q25", "q50", "q75", "q95", "max", "mean"]
    L.append(f"{head[0]:<38} {head[1]:>7} " + " ".join(f"{h:>9}" for h in head[2:]))
    L.append("-" * 118)
    for r in cont_rows:
        L.append(f"{r['field']:<38} {r['n']:>7} "
                 f"{r['q00']:>9.4f} {r['q05']:>9.4f} {r['q25']:>9.4f} {r['q50']:>9.4f} "
                 f"{r['q75']:>9.4f} {r['q95']:>9.4f} {r['q100']:>9.4f} {r['mean']:>9.4f}")
    L.append("```")
    L.append("")
    L.append("## Artefacts")
    L.append("")
    for rel in fig_rel:
        L.append(f"- `{rel}`")
    L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def rel(path):
    try:
        return os.path.relpath(path, _PROJECT_ROOT).replace("\\", "/")
    except ValueError:          # different drive (e.g. --out on another mount)
        return path.replace("\\", "/")


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--proposals", type=int, default=5000, help="solve ATTEMPTS to run")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--tag", type=str, default="", help="file tag, default derived from --proposals")
    ap.add_argument("--out", type=str, default=DEFAULT_OUT)
    ap.add_argument("--no-proposal-csv", action="store_true")
    args = ap.parse_args(argv)

    tag = args.tag or (f"{args.proposals // 1000}k" if args.proposals >= 1000
                       else str(args.proposals))
    os.makedirs(args.out, exist_ok=True)

    runner = load_runner()
    assets = vp.load_assets()
    print(f"[assets] pallets={assets.pallet_types} distractors={len(assets.distractors)}")
    print(f"[run] {args.proposals} proposals, seed={args.seed}, tag={tag}", flush=True)

    t0 = time.time()
    result = run_stream(runner, assets, args.proposals, args.seed, collect=True)
    t1 = time.time()
    print(f"[run1] {result['n_accepted']}/{result['n_seen']} accepted in {t1 - t0:.1f}s",
          flush=True)
    result2 = run_stream(runner, assets, args.proposals, args.seed, collect=False)
    elapsed = time.time() - t0
    print(f"[run2] determinism replay done in {time.time() - t1:.1f}s", flush=True)

    rows = result["rows"]
    axis_rows = axis_table(rows, assets)
    ps_rows = proj_size_three_way(rows)
    cont_rows = continuous_table(rows)
    checks, acceptance = build_checks(result, result2, rows, axis_rows, args.proposals, runner)

    png = os.path.join(args.out, f"dryrun_{tag}_joint_eda.png")
    pdf = os.path.join(args.out, f"dryrun_{tag}_joint_eda.pdf")
    joint_eda_figure(rows, png, pdf, tag)

    axes_csv = os.path.join(args.out, f"dryrun_{tag}_axis_marginals.csv")
    write_csv(axes_csv, axis_rows)
    artefacts = [rel(p) for p in (png, pdf, axes_csv)]
    if not args.no_proposal_csv:
        prop_csv = os.path.join(args.out, f"dryrun_{tag}_proposals.csv")
        write_csv(prop_csv, rows)
        artefacts.append(rel(prop_csv))

    summary = os.path.join(args.out, f"dryrun_{tag}_summary.md")
    write_summary(summary, tag, args, result, checks, acceptance, rows, axis_rows, ps_rows,
                  cont_rows, elapsed, artefacts + [rel(summary)])

    json_path = os.path.join(args.out, f"dryrun_{tag}_checks.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({
            "tag": tag, "proposals": args.proposals, "seed": args.seed,
            "accepted": result["n_accepted"], "acceptance": acceptance,
            "digest": result["digest"], "digest_replay": result2["digest"],
            "rejects": dict(result["rejects"]),
            "checks": [{"check": c, "pass": bool(ok), "detail": d} for c, ok, d in checks],
            "elapsed_s": elapsed,
        }, fh, indent=2)

    print("")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<52} {detail}")
    n_fail = sum(1 for _, ok, _ in checks if not ok)
    print(f"\n[summary] {summary}")
    print(f"[figure]  {png}")
    print(f"[verdict] {len(checks) - n_fail}/{len(checks)} checks passed"
          f"{'' if n_fail == 0 else '  <-- FAILURES PRESENT'}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
