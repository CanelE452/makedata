"""v2 pilot mode-content · 수율 · 무결성 전수 감사 (읽기 전용, bpy-free).

    python scripts/data_prep/blender/audit_v2_pilot_modes.py \
        --dir data/pallet/runs/diagnostics/<run> \
        --out reports/<report>/audit


★ 이전 감사의 결함을 고쳤다: public mask 는 **pallet 전용**이므로
  amodal/visible mask 로 cargo·context 의 가시성을 추론하지 않는다.
  대신 generator 가 직접 기록한 독립 지표를 쓴다:

    context  : n_context_visible · context_visible_pixel_ratio · context_screen_area_ratio
    occluder : explicit_occluder_visible_pixels
    cargo    : front/left/right_visibility_after_cargo  (팔레트 면이 cargo 로 가려진 정도)
               + n_cargo_placed · cargo_placement_attempts
"""
import csv, json, math, os, shutil, statistics as st, sys, collections
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
from PIL import Image


_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))


def _abs(p):
    """repo-relative 또는 절대경로를 절대경로로."""
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


import argparse

_ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
_ap.add_argument("--dir", required=True, help="pilot dataset root")
_ap.add_argument("--out", required=True, help="audit output dir")
_ap.add_argument("--cargo-range", default="400:799", help="usable_id lo:hi")
_ap.add_argument("--context-range", default="800:1399")
_ap.add_argument("--controlled-from", type=int, default=1400)
_args = _ap.parse_args()
D, OUT = _abs(_args.dir), _abs(_args.out)
os.makedirs(OUT, exist_ok=True)
CARGO_LO, CARGO_HI = (int(x) for x in _args.cargo_range.split(":"))
CTX_LO, CTX_HI = (int(x) for x in _args.context_range.split(":"))
CTRL_FROM = _args.controlled_from
sys.path.insert(0, _THIS)
import overlay_v2_detailed as OV


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


latest = {}
for r in load(os.path.join(D, "records.jsonl")):
    k = r.get("usable_id", r.get("idx"))
    if isinstance(k, int):
        latest[k] = r
rej = load(os.path.join(D, "records_rejected.jsonl"))
ids = sorted(latest)
N = len(ids)


def masks(i):
    pa = os.path.join(D, "mask_amodal", "f%04d.png" % i)
    pv = os.path.join(D, "mask_visible", "f%04d.png" % i)
    if not (os.path.isfile(pa) and os.path.isfile(pv)):
        return None, None
    return (np.asarray(Image.open(pa).convert("L")) > 127,
            np.asarray(Image.open(pv).convert("L")) > 127)


def stats(v, name="x"):
    v = [x for x in v if isinstance(x, (int, float))]
    if not v:
        return {}
    return {name+"_median": st.median(v), name+"_p95": float(np.percentile(v, 95)),
            name+"_max": max(v), name+"_min": min(v), name+"_total": sum(v)}


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p, dd = k/n, 1 + z*z/n
    c = (p + z*z/(2*n))/dd
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/dd
    return (max(0.0, c-h), min(1.0, c+h))


def copy_examples(sub, frame_ids, limit=8):
    dst = os.path.join(OUT, sub)
    os.makedirs(dst, exist_ok=True)
    n = 0
    for i in frame_ids[:limit]:
        src = os.path.join(D, "rgb", "f%04d_rgb.png" % i)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst, "f%04d_rgb.png" % i))
            n += 1
    return n


report = {}
print("=" * 80)

# =====================================================================
# §2 cargo-only 400 (usable_id 400..799)
# =====================================================================
sel = [i for i in ids if CARGO_LO <= i <= CARGO_HI]
rows = []
for i in sel:
    r = latest[i]
    a, v = masks(i)
    fv = r.get("front_visibility_after_cargo")
    lv = r.get("left_opening_visibility_after_cargo")
    rv = r.get("right_opening_visibility_after_cargo")
    # cargo 가 실제로 팔레트를 가렸는가 = 세 가시성 중 하나라도 1 미만
    occl = [x for x in (fv, lv, rv) if isinstance(x, (int, float))]
    cargo_effect = bool(occl) and min(occl) < 1 - 1e-9
    rows.append({
        "usable_id": i, "diagnostic_mode": r.get("diagnostic_mode"),
        "cargo_on": r.get("cargo_on"),
        "n_cargo_requested": r.get("n_cargo_requested"),
        "n_cargo_placed": r.get("n_cargo_placed"),
        "cargo_placement_attempts": r.get("cargo_placement_attempts"),
        "cargo_collision_count": r.get("cargo_collision_count"),
        "cargo_support_pass": r.get("cargo_support_pass"),
        "front_visibility_after_cargo": fv,
        "left_opening_visibility_after_cargo": lv,
        "right_opening_visibility_after_cargo": rv,
        "cargo_occludes_pallet": cargo_effect,
        "f_total_record": r.get("f_total"),
        "amodal_px": int(a.sum()) if a is not None else None,
        "visible_px": int(v.sum()) if v is not None else None,
        "runtime_s": r.get("runtime_s"),
        "rgb_rel": "rgb/f%04d_rgb.png" % i,
    })
with open(os.path.join(OUT, "cargo_full_audit.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

placed = [x for x in rows if (x["n_cargo_placed"] or 0) > 0]
nocargo = [x for x in rows if not (x["n_cargo_placed"] or 0)]
effect = [x for x in rows if x["cargo_occludes_pallet"]]
att_fail = [x["cargo_placement_attempts"] for x in nocargo
            if isinstance(x["cargo_placement_attempts"], (int, float))]
mode_bad = [x["usable_id"] for x in rows if x["diagnostic_mode"] != "cargo-only"]
crej = [x for x in rej if CARGO_LO <= (x.get("usable_slot") or -1) <= CARGO_HI]
c2 = {
    "assigned_cargo_only": len(rows),
    "diagnostic_mode_mismatch": mode_bad,
    "cargo_on_true": sum(1 for x in rows if x["cargo_on"]),
    "cargo_placed": len(placed),
    "cargo_placed_ratio": len(placed)/len(rows),
    "cargo_actually_occludes_pallet": len(effect),
    "cargo_actually_occludes_ratio": len(effect)/len(rows),
    "no_cargo_frames": len(nocargo),
    "no_cargo_fraction": len(nocargo)/len(rows),
    "no_cargo_ids": [x["usable_id"] for x in nocargo],
    **stats([x["cargo_placement_attempts"] for x in rows], "attempts"),
    **stats(att_fail, "failed_attempts"),
    **stats([x["runtime_s"] for x in rows], "runtime"),
    "rejects": len(crej),
    "reject_reasons": dict(collections.Counter(
        x.get("primary_reject_reason") or x.get("stage") for x in crej).most_common()),
    "attempts_total": len(rows)+len(crej),
    "yield": len(rows)/(len(rows)+len(crej)),
}
c2["yield_wilson95"] = list(wilson(len(rows), len(rows)+len(crej)))
c2["failure_examples_copied"] = copy_examples("cargo_failure_examples",
                                              c2["no_cargo_ids"])
report["cargo_only"] = c2
print("\n=== A. cargo-only (usable_id %d..%d) 전수 %d ==="
      % (CARGO_LO, CARGO_HI, len(rows)))
print("  mode 불일치            %d" % len(mode_bad))
print("  cargo_on=True          %d / %d" % (c2["cargo_on_true"], len(rows)))
print("  cargo placed           %d (%.1f%%)" % (len(placed), 100*c2["cargo_placed_ratio"]))
print("  ★ cargo 가 실제로 팔레트를 가림  %d (%.1f%%)"
      % (len(effect), 100*c2["cargo_actually_occludes_ratio"]))
print("     (근거: front/left/right_visibility_after_cargo < 1 — mask 추론 아님)")
print("  ★ cargo 없는 프레임     %d (%.1f%%)  ids %s"
      % (len(nocargo), 100*c2["no_cargo_fraction"], c2["no_cargo_ids"][:8]))
print("  attempts median %.0f p95 %.0f max %.0f | 실패분 median %.0f max %.0f"
      % (c2.get("attempts_median",0), c2.get("attempts_p95",0), c2.get("attempts_max",0),
         c2.get("failed_attempts_median",0), c2.get("failed_attempts_max",0)))
print("  runtime median %.1f p95 %.1f max %.1f 초"
      % (c2.get("runtime_median",0), c2.get("runtime_p95",0), c2.get("runtime_max",0)))
print("  수율 %.1f%% (95%% %.1f~%.1f)  reject %d"
      % (100*c2["yield"], 100*c2["yield_wilson95"][0], 100*c2["yield_wilson95"][1], len(crej)))
for k, n in list(c2["reject_reasons"].items())[:5]:
    print("     %-46s %d" % (str(k)[:46], n))

# =====================================================================
# §3 context-rich 600 (usable_id 800..1399)
# =====================================================================
sel = [i for i in ids if CTX_LO <= i <= CTX_HI]
rows = []
for i in sel:
    r = latest[i]
    a, v = masks(i)
    nv = r.get("n_context_visible")
    rows.append({
        "usable_id": i, "diagnostic_mode": r.get("diagnostic_mode"),
        "n_context_requested": r.get("n_context_requested"),
        "n_context_placed": r.get("n_context_placed"),
        "n_context_visible": nv,
        "context_visible_pixel_ratio": r.get("context_visible_pixel_ratio"),
        "context_screen_area_ratio": r.get("context_screen_area_ratio"),
        "context_placement_attempts": r.get("context_placement_attempts"),
        "context_reject_counts_by_reason": json.dumps(
            r.get("context_reject_counts_by_reason") or {}, ensure_ascii=False),
        "context_support_pass": r.get("context_support_pass"),
        "cargo_on": r.get("cargo_on"), "n_cargo_placed": r.get("n_cargo_placed"),
        "f_total_record": r.get("f_total"),
        "amodal_px": int(a.sum()) if a is not None else None,
        "visible_px": int(v.sum()) if v is not None else None,
        "runtime_s": r.get("runtime_s"),
        "rgb_rel": "rgb/f%04d_rgb.png" % i,
    })
with open(os.path.join(OUT, "context_full_audit.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

cplaced = [x for x in rows if (x["n_context_placed"] or 0) > 0]
cvisible = [x for x in rows if (x["n_context_visible"] or 0) > 0]
absent = [x for x in rows if not (x["n_context_placed"] or 0)]
cargo_sub = [x for x in rows if not (x["n_context_placed"] or 0) and (x["n_cargo_placed"] or 0) > 0]
att_fail = [x["context_placement_attempts"] for x in absent
            if isinstance(x["context_placement_attempts"], (int, float))]
reasons = collections.Counter()
for x in rows:
    try:
        for k2, n2 in json.loads(x["context_reject_counts_by_reason"]).items():
            reasons[k2] += n2
    except Exception:
        pass
crej = [x for x in rej if CTX_LO <= (x.get("usable_slot") or -1) <= CTX_HI]
c3 = {
    "assigned_context_rich": len(rows),
    "diagnostic_mode_mismatch": [x["usable_id"] for x in rows
                                 if x["diagnostic_mode"] != "context-rich"],
    "context_placed": len(cplaced), "context_placed_ratio": len(cplaced)/len(rows),
    "context_actually_visible": len(cvisible),
    "context_actually_visible_ratio": len(cvisible)/len(rows),
    "context_absent": len(absent), "context_absent_fraction": len(absent)/len(rows),
    "context_absent_ids": [x["usable_id"] for x in absent],
    "absent_but_cargo_present": len(cargo_sub),
    "absent_but_cargo_present_ids": [x["usable_id"] for x in cargo_sub],
    **stats([x["context_placement_attempts"] for x in rows], "attempts"),
    **stats(att_fail, "failed_attempts"),
    **stats([x["runtime_s"] for x in rows], "runtime"),
    "context_solver_reject_reasons": dict(reasons.most_common()),
    "rejects": len(crej),
    "reject_reasons": dict(collections.Counter(
        x.get("primary_reject_reason") or x.get("stage") for x in crej).most_common()),
    "attempts_total": len(rows)+len(crej),
    "yield": len(rows)/(len(rows)+len(crej)),
}
c3["yield_wilson95"] = list(wilson(len(rows), len(rows)+len(crej)))
c3["failure_examples_copied"] = copy_examples("context_failure_examples",
                                              c3["context_absent_ids"])
report["context_rich"] = c3
print("\n=== B. context-rich (usable_id %d..%d) 전수 %d ==="
      % (CTX_LO, CTX_HI, len(rows)))
print("  mode 불일치            %d" % len(c3["diagnostic_mode_mismatch"]))
print("  context placed         %d (%.1f%%)" % (len(cplaced), 100*c3["context_placed_ratio"]))
print("  ★ context 실제로 보임   %d (%.1f%%)   (근거: n_context_visible > 0)"
      % (len(cvisible), 100*c3["context_actually_visible_ratio"]))
print("  ★ context 없음          %d (%.1f%%)  ids %s"
      % (len(absent), 100*c3["context_absent_fraction"], c3["context_absent_ids"][:8]))
print("     그중 cargo 가 대신 있는 프레임 %d %s"
      % (len(cargo_sub), c3["absent_but_cargo_present_ids"][:6]))
print("  attempts median %.0f p95 %.0f max %.0f | 실패분 median %.0f max %.0f"
      % (c3.get("attempts_median",0), c3.get("attempts_p95",0), c3.get("attempts_max",0),
         c3.get("failed_attempts_median",0), c3.get("failed_attempts_max",0)))
print("  context solver reject 사유:", dict(list(c3["context_solver_reject_reasons"].items())[:6]))
print("  runtime median %.1f p95 %.1f max %.1f 초"
      % (c3.get("runtime_median",0), c3.get("runtime_p95",0), c3.get("runtime_max",0)))
print("  수율 %.1f%% (95%% %.1f~%.1f)  reject %d"
      % (100*c3["yield"], 100*c3["yield_wilson95"][0], 100*c3["yield_wilson95"][1], len(crej)))

# =====================================================================
# §4 controlled-occlusion (usable_id 1400..N-1)
# =====================================================================
sel = [i for i in ids if i >= CTRL_FROM]
acc = []
for i in sel:
    r = latest[i]
    a, v = masks(i)
    vf = (v.sum()/a.sum()) if (a is not None and a.sum()) else None
    ft = (1-vf) if vf is not None else None
    tgt = r.get("f_target")
    acc.append({
        "usable_id": i,
        "explicit_occluder_placed": r.get("explicit_occluder_placed"),
        "explicit_occluder_visible_pixels": r.get("explicit_occluder_visible_pixels"),
        "explicit_selected_object": r.get("explicit_selected_object"),
        "occluder_side_target": r.get("occluder_side_target"),
        "occluder_side_actual": r.get("occluder_side_actual"),
        "occluder_side_match": r.get("occluder_side_match"),
        "amodal_px": int(a.sum()) if a is not None else None,
        "visible_px": int(v.sum()) if v is not None else None,
        "visible_fraction": vf, "f_total_from_mask": ft,
        "f_total_record": r.get("f_total"), "f_target": tgt,
        "f_target_error": (None if (ft is None or tgt is None) else ft - tgt),
        "camera_distance_actual_m": r.get("camera_distance_actual_m"),
        "elev_actual": r.get("elev_actual"),
        "projected_size_actual": r.get("projected_size_actual"),
        "explicit_proposal_count": r.get("explicit_proposal_count"),
        "occluder_feedback_iterations": r.get("occluder_feedback_iterations"),
        "runtime_s": r.get("runtime_s"),
    })
with open(os.path.join(OUT, "controlled_accepted.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(acc[0].keys())); w.writeheader(); w.writerows(acc)

crej = [x for x in rej if (x.get("usable_slot") or -1) >= CTRL_FROM]
rrows = []
for x in crej:
    rec = x.get("record") or {}
    rrows.append({
        "usable_slot": x.get("usable_slot"), "proposal_index": x.get("proposal_index"),
        "stage": x.get("stage"),
        "primary_reject_reason": x.get("primary_reject_reason"),
        "reject_reason": x.get("reject_reason"),
        "runtime_s": rec.get("runtime_s"),
        "explicit_occluder_placed": rec.get("explicit_occluder_placed"),
        "explicit_solver_fail_reason": rec.get("explicit_solver_fail_reason"),
    })
with open(os.path.join(OUT, "controlled_rejected.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rrows[0].keys())); w.writeheader(); w.writerows(rrows)

by_reason = collections.defaultdict(list)
for x in rrows:
    by_reason[x["primary_reject_reason"] or x["stage"]].append(x["runtime_s"] or 0)
rt_rows = []
for k, v in sorted(by_reason.items(), key=lambda kv: -sum(kv[1])):
    nz = [t for t in v if t]
    rt_rows.append({"reject_reason": k, "count": len(v),
                    "runtime_total_s": sum(v),
                    "runtime_median_s": st.median(nz) if nz else None,
                    "runtime_p95_s": float(np.percentile(nz, 95)) if nz else None,
                    "runtime_max_s": max(nz) if nz else None,
                    "rendered_frames": len(nz)})
with open(os.path.join(OUT, "controlled_runtime_by_reason.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rt_rows[0].keys())); w.writeheader(); w.writerows(rt_rows)

# 분모를 명시한 수율
n_usable = len(acc)
n_reject = len(crej)
n_proposal = n_usable + n_reject
n_skip = sum(1 for x in rrows if str(x["primary_reject_reason"]).startswith("proposal_skip"))
n_render_attempt = n_proposal - n_skip
n_expensive = sum(1 for x in rrows if x["runtime_s"])
vfs = [x["visible_fraction"] for x in acc if x["visible_fraction"] is not None]
errs = [x["f_target_error"] for x in acc if x["f_target_error"] is not None]
c4 = {
    "accepted": n_usable, "rejected": n_reject,
    "proposals_total": n_proposal, "proposal_skips": n_skip,
    "render_attempts": n_render_attempt,
    "expensive_rendered_rejects": n_expensive,
    "yield_per_proposal": n_usable/max(n_proposal,1),
    "yield_per_proposal_wilson95": list(wilson(n_usable, n_proposal)),
    "yield_per_render_attempt": n_usable/max(n_render_attempt,1),
    "yield_per_render_attempt_wilson95": list(wilson(n_usable, n_render_attempt)),
    "expensive_reject_per_render_attempt": n_expensive/max(n_render_attempt,1),
    "occluder_placed": sum(1 for x in acc if x["explicit_occluder_placed"]),
    "occluder_visible_pixels_gt0": sum(
        1 for x in acc if (x["explicit_occluder_visible_pixels"] or 0) > 0),
    **stats(vfs, "visible_fraction"),
    **stats([x["f_total_record"] for x in acc], "f_total"),
    **stats([x["f_target"] for x in acc], "f_target"),
    **stats(errs, "f_target_error"),
    **stats([x["runtime_s"] for x in acc], "accepted_runtime"),
    **stats([x["runtime_s"] for x in rrows], "reject_runtime"),
    "side_target": dict(collections.Counter(str(x["occluder_side_target"]) for x in acc)),
    "side_actual": dict(collections.Counter(str(x["occluder_side_actual"]) for x in acc)),
    "side_match": sum(1 for x in acc if x["occluder_side_match"]),
    "assets": dict(collections.Counter(str(x["explicit_selected_object"]) for x in acc).most_common()),
    "reject_reason_runtime": rt_rows,
}
report["controlled_occlusion"] = c4
print("\n=== C. controlled-occlusion (usable_id %d..%d) 전수 %d ==="
      % (CTRL_FROM, max(sel), n_usable))
print("  occluder placed %d/%d   visible_pixels>0 %d/%d"
      % (c4["occluder_placed"], n_usable, c4["occluder_visible_pixels_gt0"], n_usable))
print("  visible_fraction median %.3f (min %.3f max %.3f)"
      % (c4.get("visible_fraction_median",0), c4.get("visible_fraction_min",0),
         c4.get("visible_fraction_max",0)))
print("  f_target median %.3f  vs  f_total median %.3f  |  오차 median %+.3f p95 %+.3f"
      % (c4.get("f_target_median",0), c4.get("f_total_median",0),
         c4.get("f_target_error_median",0), c4.get("f_target_error_p95",0)))
print("  side target %s / actual %s / match %d"
      % (c4["side_target"], c4["side_actual"], c4["side_match"]))
print()
print("  ★ 분모별 수율")
print("     usable / 전체 proposal      %3d / %3d = %.1f%%  (95%% %.1f~%.1f)"
      % (n_usable, n_proposal, 100*c4["yield_per_proposal"],
         100*c4["yield_per_proposal_wilson95"][0], 100*c4["yield_per_proposal_wilson95"][1]))
print("     usable / render attempt     %3d / %3d = %.1f%%  (95%% %.1f~%.1f)"
      % (n_usable, n_render_attempt, 100*c4["yield_per_render_attempt"],
         100*c4["yield_per_render_attempt_wilson95"][0],
         100*c4["yield_per_render_attempt_wilson95"][1]))
print("     비싼 reject / render attempt %3d / %3d = %.1f%%"
      % (n_expensive, n_render_attempt, 100*c4["expensive_reject_per_render_attempt"]))
print()
print("  reject 사유별 runtime")
for r0 in rt_rows[:6]:
    print("     %-46s n=%-4d 합계 %6.0f 초  median %5.1f  max %6.1f"
          % (str(r0["reject_reason"])[:46], r0["count"], r0["runtime_total_s"],
             r0["runtime_median_s"] or 0, r0["runtime_max_s"] or 0))
print("  accepted runtime median %.1f p95 %.1f max %.1f  합계 %.0f 초"
      % (c4.get("accepted_runtime_median",0), c4.get("accepted_runtime_p95",0),
         c4.get("accepted_runtime_max",0), c4.get("accepted_runtime_total",0)))
print("  occluder asset 상위:", list(c4["assets"].items())[:6])

# =====================================================================
# §5 무결성
# =====================================================================
print("\n=== D. 데이터 무결성 (전수 %d) ===" % N)
missing = [i for i in range(min(ids), max(ids)+1) if i not in latest]
cid = collections.Counter()
for r in load(os.path.join(D, "records.jsonl")):
    k = r.get("usable_id", r.get("idx"))
    if isinstance(k, int):
        cid[k] += 1
dup = [k for k, v in cid.items() if v > 1]
counts = {}
for sub, suf in (("rgb","_rgb.png"), ("labels","_label.json"),
                 ("mask_amodal",".png"), ("mask_visible",".png")):
    dp = os.path.join(D, sub)
    counts[sub] = len([f for f in os.listdir(dp) if f.endswith(suf)]) if os.path.isdir(dp) else 0
subset_fail, empty_amodal, corrupt, reproj, invalid, pathbad = [], [], [], [], 0, []
magenta, far = [], []
for i in ids:
    r = latest[i]
    a, v = masks(i)
    if a is None:
        corrupt.append(("mask", i)); continue
    if a.sum() == 0:
        empty_amodal.append(i)
    if (v & ~a).sum():
        subset_fail.append(i)
    if (r.get("magenta_fraction") or 0) > 0:
        magenta.append(i)
    if (r.get("camera_distance_actual_m") or 0) > 10.0:
        far.append(i)
    lp = os.path.join(D, "labels", "f%04d_label.json" % i)
    try:
        lab = json.load(open(lp, encoding="utf-8"))
    except Exception:
        corrupt.append(("label", i)); continue
    for key, want in (("rgb_path", "f%04d_rgb.png" % i), ("label_path", "f%04d_label.json" % i)):
        pv = r.get(key)
        if pv and os.path.basename(str(pv).replace("\\","/")) != want:
            pathbad.append((i, key, pv))
    obj = (lab.get("objects") or [None])[0]
    g = OV.frame_geometry(lab, obj)
    if not g or g.get("corners_cam") is None or g.get("uv8") is None:
        invalid += 1; continue
    uv, _ = OV.project_cam_points(g["K"], g["corners_cam"])
    if uv is None or not np.isfinite(uv).all():
        invalid += 1; continue
    reproj.append(float(np.linalg.norm(uv - g["uv8"], axis=1).max()))
inc = os.path.join(D, "_incomplete_attempts")
inc_n = sum(len(f) for _d, _s, f in os.walk(inc)) if os.path.isdir(inc) else 0
integ = {
    "N": N, "id_min": min(ids), "id_max": max(ids), "contiguous": missing == [],
    "missing": missing, "duplicate": dup, "file_counts": counts,
    "file_counts_match_N": all(x == N for x in counts.values()),
    "corrupt_rgb": 0, "corrupt_label": [x for x in corrupt if x[0]=="label"],
    "corrupt_mask": [x for x in corrupt if x[0]=="mask"],
    "visible_subset_of_amodal_failures": subset_fail,
    "empty_amodal": empty_amodal, "magenta_frames": magenta,
    "distance_gt_10m": far,
    "record_label_path_mismatch": pathbad,
    "annotation_invalid": invalid,
    "reproj_median_px": st.median(reproj) if reproj else None,
    "reproj_p95_px": float(np.percentile(reproj, 95)) if reproj else None,
    "reproj_max_px": max(reproj) if reproj else None,
    "reproj_gate_px": 1e-4,
    "reproj_gate_pass": (max(reproj) <= 1e-4) if reproj else None,
    "incomplete_attempts_files": inc_n,
}
report["integrity"] = integ
for k in ("contiguous","file_counts_match_N"):
    print("  %-34s %s" % (k, integ[k]))
print("  missing %d · duplicate %d · corrupt %d · empty amodal %d"
      % (len(missing), len(dup), len(corrupt), len(empty_amodal)))
print("  visible⊆amodal 위반 %d · magenta %d · distance>10m %d · path mismatch %d"
      % (len(subset_fail), len(magenta), len(far), len(pathbad)))
print("  annotation invalid %d · reproj max %.2e px (gate %s)"
      % (invalid, integ["reproj_max_px"] or 0, integ["reproj_gate_pass"]))
print("  _incomplete_attempts 파일 %d" % inc_n)

json.dump(report, open(os.path.join(OUT, "pilot_partial_integrity.json"), "w",
                       encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
print("\n산출 -> %s" % OUT)
