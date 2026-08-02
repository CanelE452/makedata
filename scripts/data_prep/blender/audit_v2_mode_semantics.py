"""mode semantics · controlled 효율 · 무결성 전수 감사 (읽기 전용, bpy-free).

`audit_v2_pilot_modes.py` 는 usable_id 구간으로 mode 를 가정한다.  10장 주기 interleave
이후에는 그 가정이 성립하지 않으므로, 여기서는 record 의 `diagnostic_mode` 로 묶는다.

    python scripts/data_prep/blender/audit_v2_mode_semantics.py \
        --dir data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public \
        --out reports/v2_generator_fix_g1_g3/g2 \
        [--expect-modes clean-static=20,cargo-only=20,context-rich=30,controlled-occlusion=30]
        [--baseline-controlled reports/v2_pilot_2k_seed7000/audit/controlled_accepted.csv]

원칙
  - cargo 가시성을 public pallet mask 로 추론하지 않는다 (팔레트 전용 마스크다).
  - None 은 통과가 아니다.  0 은 실제 0.
  - 표본 수·분모를 항상 같이 적는다.
"""
import argparse
import collections
import csv
import io
import json
import math
import os
import statistics as st
import sys

import numpy as np
from PIL import Image

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import overlay_v2_detailed as OV       # noqa: E402
import scene_placement_v2 as SP2       # noqa: E402

MODES = ("clean-static", "cargo-only", "context-rich", "controlled-occlusion")
EXPENSIVE = "usable_reject:rendered|usable_reject:realize_ok"


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def load_jsonl(path):
    if not os.path.isfile(path):
        return []
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


def quant(values):
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return {}
    n = len(v)
    return {"n": n, "min": v[0], "p05": v[max(0, int(0.05 * n) - 1)],
            "median": v[n // 2], "p95": v[min(n - 1, int(0.95 * n))],
            "max": v[-1]}


def write_csv(path, rows, fields=None):
    if not rows:
        io.open(path, "w", encoding="utf-8", newline="").write("")
        return
    fields = fields or list(rows[0])
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-modes", default=None,
                    help="mode=count,mode=count (없으면 개수 검사 생략)")
    ap.add_argument("--baseline-controlled", default=None,
                    help="비열화 비교용 baseline controlled_accepted.csv")
    args = ap.parse_args(argv)

    root, out = _abs(args.dir), _abs(args.out)
    os.makedirs(out, exist_ok=True)

    records = load_jsonl(os.path.join(root, "records.jsonl"))
    rejected = load_jsonl(os.path.join(root, "records_rejected.jsonl"))
    latest = {}
    for rec in records:
        key = rec.get("usable_id", rec.get("idx"))
        if isinstance(key, int):
            latest[key] = rec
    ids = sorted(latest)
    if not ids:
        raise SystemExit(f"records.jsonl 이 비어 있습니다: {root}")

    report = {"dir": os.path.relpath(root, PROJECT_ROOT).replace(os.sep, "/"),
              "n_usable": len(ids)}

    # ---------------- A. mode 배분 -------------------------------------
    counts = collections.Counter(latest[i].get("diagnostic_mode") for i in ids)
    report["mode_counts"] = dict(counts)
    expect = None
    if args.expect_modes:
        expect = {}
        for part in args.expect_modes.split(","):
            name, value = part.split("=")
            expect[name.strip()] = int(value)
        report["mode_counts_expected"] = expect
        report["mode_counts_match"] = all(
            counts.get(k, 0) == v for k, v in expect.items())

    # 10장 블록마다 2/2/3/3 인가 (완결된 블록만)
    block_bad = []
    for start in range(0, (len(ids) // 10) * 10, 10):
        block = collections.Counter(latest[i].get("diagnostic_mode")
                                    for i in ids[start:start + 10])
        if dict(block) != {"clean-static": 2, "cargo-only": 2,
                           "context-rich": 3, "controlled-occlusion": 3}:
            block_bad.append((start, dict(block)))
    report["ten_block_violations"] = block_bad

    # ---------------- B. mode semantics 전수 ---------------------------
    sem_rows, sem_fail = [], []
    for i in ids:
        rec = latest[i]
        mode = rec.get("diagnostic_mode")
        verdict = SP2.mode_semantics_verdict(mode, rec)
        row = {
            "usable_id": i, "diagnostic_mode": mode,
            "semantics_pass": verdict["pass"],
            "failed": "|".join(verdict["failed_conditions"]),
            "unknown": "|".join(verdict["unknown_conditions"]),
            "recorded_pass": rec.get("mode_semantics_pass"),
            "n_cargo_requested": rec.get("n_cargo_requested"),
            "n_cargo_placed": rec.get("n_cargo_placed"),
            "n_cargo_visible": rec.get("n_cargo_visible"),
            "cargo_visible_pixels": rec.get("cargo_visible_pixels"),
            "cargo_visible_pixel_ratio": rec.get("cargo_visible_pixel_ratio"),
            "n_context_requested": rec.get("n_context_requested"),
            "n_context_placed": rec.get("n_context_placed"),
            "n_context_visible": rec.get("n_context_visible"),
            "context_visible_pixel_ratio": rec.get("context_visible_pixel_ratio"),
            "explicit_occluder_placed": rec.get("explicit_occluder_placed"),
            "explicit_occluder_visible_pixels": rec.get(
                "explicit_occluder_visible_pixels"),
            "occluder_side_target": rec.get("occluder_side_target"),
            "occluder_side_actual": rec.get("occluder_side_actual"),
            "occluder_side_match": rec.get("occluder_side_match"),
            "f_explicit_target": rec.get("f_explicit_target"),
            "f_explicit_actual": rec.get("f_explicit_actual"),
            # §2 저해상도 explicit 품질 (public 프로필에서 유일하게 계산 가능한 값).
            "explicit_metrics_available": rec.get("explicit_metrics_available"),
            "f_explicit_actual_lowres": rec.get("f_explicit_actual_lowres"),
            "explicit_abs_error_lowres": rec.get("explicit_abs_error_lowres"),
            "explicit_target_pixels": rec.get("explicit_target_pixels"),
            "explicit_actual_pixels_lowres": rec.get(
                "explicit_actual_pixels_lowres"),
            "explicit_target_centroid_u": rec.get("explicit_target_centroid_u"),
            "explicit_target_centroid_v": rec.get("explicit_target_centroid_v"),
            "explicit_actual_centroid_u_lowres": rec.get(
                "explicit_actual_centroid_u_lowres"),
            "explicit_actual_centroid_v_lowres": rec.get(
                "explicit_actual_centroid_v_lowres"),
            "search_winning_stage": rec.get("search_winning_stage"),
            "coarse_eval_count": rec.get("coarse_eval_count"),
            "fine_eval_count": rec.get("fine_eval_count"),
            "runtime_s": rec.get("runtime_s"),
        }
        sem_rows.append(row)
        if not verdict["pass"] or rec.get("mode_semantics_pass") is not True:
            sem_fail.append(row)
    write_csv(os.path.join(out, "mode_semantics_audit.csv"), sem_rows)
    report["mode_semantics_failures"] = len(sem_fail)
    report["mode_semantics_disagreements"] = [
        r["usable_id"] for r in sem_rows
        if bool(r["semantics_pass"]) != bool(r["recorded_pass"])]

    per_mode = {}
    for mode in MODES:
        rows = [r for r in sem_rows if r["diagnostic_mode"] == mode]
        entry = {"n": len(rows),
                 "semantics_pass": sum(1 for r in rows if r["semantics_pass"])}
        if mode == "cargo-only":
            entry["placed_ge1"] = sum(1 for r in rows
                                      if (r["n_cargo_placed"] or 0) >= 1)
            entry["visible_px_gt0"] = sum(
                1 for r in rows if (r["cargo_visible_pixels"] or 0) > 0)
            entry["visible_pixels"] = quant(
                [r["cargo_visible_pixels"] for r in rows])
            entry["visible_ratio"] = quant(
                [r["cargo_visible_pixel_ratio"] for r in rows])
        elif mode == "context-rich":
            entry["visible_ge1"] = sum(1 for r in rows
                                       if (r["n_context_visible"] or 0) >= 1)
            entry["ratio_gt0"] = sum(
                1 for r in rows if (r["context_visible_pixel_ratio"] or 0) > 0)
            entry["visible_ratio"] = quant(
                [r["context_visible_pixel_ratio"] for r in rows])
        elif mode == "controlled-occlusion":
            entry["placed"] = sum(1 for r in rows
                                  if r["explicit_occluder_placed"] is True)
            entry["visible_px_gt0"] = sum(
                1 for r in rows
                if (r["explicit_occluder_visible_pixels"] or 0) > 0)
            entry["side_match"] = sum(1 for r in rows
                                      if r["occluder_side_match"] is True)
            errors = [abs(float(r["f_explicit_actual"]) - float(r["f_explicit_target"]))
                      for r in rows
                      if r["f_explicit_actual"] is not None
                      and r["f_explicit_target"] is not None]
            entry["abs_target_error"] = quant(errors)
            entry["metrics_available"] = sum(
                1 for r in rows if r["explicit_metrics_available"] is True)
            entry["abs_target_error_lowres"] = quant(
                [r["explicit_abs_error_lowres"] for r in rows])
            entry["centroid_error_px_lowres"] = quant([
                math.hypot(
                    float(r["explicit_actual_centroid_u_lowres"])
                    - float(r["explicit_target_centroid_u"]),
                    float(r["explicit_actual_centroid_v_lowres"])
                    - float(r["explicit_target_centroid_v"]))
                for r in rows
                if r["explicit_actual_centroid_u_lowres"] is not None
                and r["explicit_target_centroid_u"] is not None])
            entry["winning_stage"] = dict(collections.Counter(
                str(r["search_winning_stage"]) for r in rows))
        per_mode[mode] = entry
    report["per_mode"] = per_mode

    # ---------------- C. controlled 효율 -------------------------------
    ctrl_rej = [r for r in rejected
                if r.get("diagnostic_mode") == "controlled-occlusion"]
    stage_counts = collections.Counter(r.get("stage") for r in ctrl_rej)
    reason_counts = collections.Counter(r.get("primary_reject_reason")
                                        for r in ctrl_rej)
    ctrl_acc = [latest[i] for i in ids
                if latest[i].get("diagnostic_mode") == "controlled-occlusion"]
    usable_n = len(ctrl_acc)
    proposals = usable_n + len(ctrl_rej)
    # 0초 reject 세 종류(비용 없음): mode filter skip · pure solve reject ·
    # bpy-free prefilter 소진.  나머지가 실제로 Blender 시간을 쓴 것이다.
    mode_filter = sum(1 for r in ctrl_rej if r.get("stage") == "mode_filter")
    solve_rej = sum(1 for r in ctrl_rej if r.get("stage") == "solve")
    prefilter_exhausted = sum(
        1 for r in ctrl_rej
        if (r.get("record") or {}).get("explicit_solver_fail_reason")
        == "diagnostic_explicit_prefilter_exhausted")
    # prefilter 소진은 stage 가 render 로 기록되지만 Blender 를 열지 않았다
    # (runtime 은 bpy-free 준비 시간 ~0.6초뿐).  비싼 reject 에서 제외한다.
    expensive_rows = [
        r for r in ctrl_rej
        if r.get("stage") == "render"
        and (r.get("record") or {}).get("explicit_solver_fail_reason")
        != "diagnostic_explicit_prefilter_exhausted"]
    expensive = len(expensive_rows)
    # 지시서 baseline(180)과 같은 분모: 전체 proposal 에서 mode filter skip 만 뺀 것.
    attempts_incl_free = proposals - mode_filter
    blender_attempts = usable_n + expensive
    exp_runtime = sum(float((r.get("record") or {}).get("runtime_s") or 0.0)
                      for r in expensive_rows)
    acc_runtime = sum(float(r.get("runtime_s") or 0.0) for r in ctrl_acc)
    eff = {
        "usable": usable_n,
        "all_proposals": proposals,
        "yield_all_proposals": (usable_n / proposals) if proposals else None,
        "yield_all_proposals_ci95": wilson(usable_n, proposals),
        "mode_filter_skips": mode_filter,
        "solve_rejects": solve_rej,
        "prefilter_exhausted_rejects": prefilter_exhausted,
        "attempts_excluding_mode_filter": attempts_incl_free,
        "yield_attempts_excluding_mode_filter": (
            usable_n / attempts_incl_free) if attempts_incl_free else None,
        "expensive_reject_share_excluding_mode_filter": (
            expensive / attempts_incl_free) if attempts_incl_free else None,
        "blender_attempts": blender_attempts,
        "yield_blender_attempts": (usable_n / blender_attempts)
        if blender_attempts else None,
        "yield_blender_attempts_ci95": wilson(usable_n, blender_attempts),
        "expensive_rejects": expensive,
        "expensive_reject_share_blender": (expensive / blender_attempts)
        if blender_attempts else None,
        "reject_runtime_s": round(exp_runtime, 1),
        "accepted_runtime_s": round(acc_runtime, 1),
        "reject_over_accepted_runtime": (exp_runtime / acc_runtime)
        if acc_runtime else None,
        "wall_time_per_usable_controlled_s": (
            (exp_runtime + acc_runtime) / usable_n) if usable_n else None,
        "stage_counts": dict(stage_counts),
        "primary_reject_reason_counts": dict(reason_counts),
        "prefilter_reject_count_total": sum(
            int(r.get("prefilter_reject_count") or 0) for r in ctrl_acc),
        "candidates_before_prefilter_total": sum(
            int(r.get("candidates_before_prefilter") or 0) for r in ctrl_acc),
        "candidates_after_prefilter_total": sum(
            int(r.get("candidates_after_prefilter") or 0) for r in ctrl_acc),
    }
    report["controlled_efficiency"] = eff
    write_csv(os.path.join(out, "controlled_efficiency.csv"), [
        {"metric": k, "value": json.dumps(v, ensure_ascii=False)
         if isinstance(v, (dict, list, tuple)) else v}
        for k, v in eff.items()], fields=["metric", "value"])

    write_csv(os.path.join(out, "controlled_quality.csv"), [
        {"usable_id": r["usable_id"],
         "f_explicit_target": r["f_explicit_target"],
         "f_explicit_actual": r["f_explicit_actual"],
         "abs_error": (abs(float(r["f_explicit_actual"]) - float(r["f_explicit_target"]))
                       if r["f_explicit_actual"] is not None
                       and r["f_explicit_target"] is not None else None),
         "occluder_side_target": r["occluder_side_target"],
         "occluder_side_actual": r["occluder_side_actual"],
         "occluder_side_match": r["occluder_side_match"],
         "explicit_occluder_visible_pixels": r["explicit_occluder_visible_pixels"],
         "runtime_s": r["runtime_s"]}
        for r in sem_rows if r["diagnostic_mode"] == "controlled-occlusion"])

    if args.baseline_controlled:
        base_rows = list(csv.DictReader(
            io.open(_abs(args.baseline_controlled), encoding="utf-8")))
        base_err = sorted(abs(float(r["f_target_error"])) for r in base_rows
                          if r.get("f_target_error"))
        n = len(base_err)
        report["baseline_controlled"] = {
            "n": n,
            "abs_error_median": base_err[n // 2] if n else None,
            "abs_error_p95": base_err[min(n - 1, int(0.95 * n))] if n else None,
            "side_match_rate": (sum(1 for r in base_rows
                                    if r.get("occluder_side_match") == "True")
                                / max(1, len(base_rows))),
            "visible_pixels": quant(
                [float(r["explicit_occluder_visible_pixels"]) for r in base_rows]),
        }

    # ---------------- D. runtime by stage ------------------------------
    rt_rows = []
    for i in ids:
        rec = latest[i]
        stage = rec.get("stage_runtime_s") or {}
        rt_rows.append({
            "usable_id": i, "diagnostic_mode": rec.get("diagnostic_mode"),
            "runtime_s": rec.get("runtime_s"),
            "proposal_prepare_s": rec.get("proposal_prepare_s"),
            "realization_attempt_count": rec.get("realization_attempt_count"),
            "lowres_render_count": rec.get("lowres_render_count"),
            "candidates_before_prefilter": rec.get("candidates_before_prefilter"),
            "candidates_after_prefilter": rec.get("candidates_after_prefilter"),
            "prefilter_reject_count": rec.get("prefilter_reject_count"),
            **{f"stage_{k}": v for k, v in stage.items()},
        })
    write_csv(os.path.join(out, "runtime_by_stage.csv"), rt_rows,
              fields=sorted({k for r in rt_rows for k in r}))

    # ---------------- E. 무결성 ----------------------------------------
    missing = [i for i in range(min(ids), max(ids) + 1) if i not in latest]
    seen = collections.Counter()
    for rec in records:
        key = rec.get("usable_id", rec.get("idx"))
        if isinstance(key, int):
            seen[key] += 1
    duplicate = [k for k, v in seen.items() if v > 1]
    file_counts = {}
    for sub, suffix in (("rgb", "_rgb.png"), ("labels", "_label.json"),
                        ("mask_amodal", ".png"), ("mask_visible", ".png")):
        path = os.path.join(root, sub)
        file_counts[sub] = (len([f for f in os.listdir(path)
                                 if f.endswith(suffix)])
                            if os.path.isdir(path) else 0)

    subset_fail, empty_amodal, corrupt, reproj = [], [], [], []
    magenta, far, invalid = [], [], 0
    for i in ids:
        rec = latest[i]
        try:
            amodal = np.array(Image.open(
                os.path.join(root, "mask_amodal", "f%04d.png" % i)).convert("L")) > 127
            visible = np.array(Image.open(
                os.path.join(root, "mask_visible", "f%04d.png" % i)).convert("L")) > 127
        except Exception:
            corrupt.append(("mask", i))
            continue
        if amodal.sum() == 0:
            empty_amodal.append(i)
        if (visible & ~amodal).sum():
            subset_fail.append(i)
        if (rec.get("magenta_fraction") or 0) > 0:
            magenta.append(i)
        if (rec.get("camera_distance_actual_m") or 0) > 10.0:
            far.append(i)
        try:
            label = json.load(io.open(
                os.path.join(root, "labels", "f%04d_label.json" % i),
                encoding="utf-8"))
        except Exception:
            corrupt.append(("label", i))
            continue
        obj = (label.get("objects") or [None])[0]
        geom = OV.frame_geometry(label, obj)
        if not geom or geom.get("corners_cam") is None or geom.get("uv8") is None:
            invalid += 1
            continue
        uv, _ = OV.project_cam_points(geom["K"], geom["corners_cam"])
        if uv is None or not np.isfinite(uv).all():
            invalid += 1
            continue
        reproj.append(float(np.linalg.norm(uv - geom["uv8"], axis=1).max()))

    report["integrity"] = {
        "id_min": min(ids), "id_max": max(ids),
        "contiguous": missing == [], "missing": missing, "duplicate": duplicate,
        "file_counts": file_counts,
        "visible_subset_amodal_violations": subset_fail,
        "empty_amodal": empty_amodal,
        "corrupt": corrupt, "magenta_frames": magenta,
        "camera_distance_over_10m": far,
        "annotation_invalid": invalid,
        "reproj_max_px": max(reproj) if reproj else None,
        "reproj_median_px": st.median(reproj) if reproj else None,
        "reproj_gate_px": 1e-4,
        "reproj_gate_pass": (max(reproj) <= 1e-4) if reproj else None,
        "gate_failures": [i for i in ids
                          if latest[i].get("all_pass") is not True],
    }

    with io.open(os.path.join(out, "audit_summary.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
        fh.write("\n")
    write_csv(os.path.join(out, "records_audit.csv"), sem_rows)

    integ = report["integrity"]
    print("=== mode counts ===", dict(counts))
    if expect:
        print("  expected", expect, "match", report["mode_counts_match"])
    print("  10-블록 위반", len(block_bad))
    print("=== mode semantics ===  실패", len(sem_fail),
          " record 와 불일치", len(report["mode_semantics_disagreements"]))
    for mode in MODES:
        print("   %-22s %s" % (mode, json.dumps(
            {k: v for k, v in per_mode[mode].items()
             if not isinstance(v, dict)}, ensure_ascii=False)))
    def pct(value):
        return "-" if value is None else "%.1f%%" % (100.0 * value)

    print("=== controlled 효율 ===")
    print("   A usable/proposal            %s/%s = %s"
          % (eff["usable"], eff["all_proposals"],
             pct(eff["yield_all_proposals"])))
    print("   B usable/attempt(-modefilter) %s/%s = %s"
          % (eff["usable"], eff["attempts_excluding_mode_filter"],
             pct(eff["yield_attempts_excluding_mode_filter"])))
    print("   B' usable/Blender attempt     %s/%s = %s"
          % (eff["usable"], eff["blender_attempts"],
             pct(eff["yield_blender_attempts"])))
    print("   C expensive/attempt(-modefilter) %s/%s = %s"
          % (eff["expensive_rejects"], eff["attempts_excluding_mode_filter"],
             pct(eff["expensive_reject_share_excluding_mode_filter"])))
    print("   free rejects: mode_filter %s · solve %s · prefilter %s"
          % (eff["mode_filter_skips"], eff["solve_rejects"],
             eff["prefilter_exhausted_rejects"]))
    print("   runtime reject %.1fs / accepted %.1fs = %s  (usable 1장당 %s초)"
          % (eff["reject_runtime_s"], eff["accepted_runtime_s"],
             None if eff["reject_over_accepted_runtime"] is None
             else round(eff["reject_over_accepted_runtime"], 3),
             None if eff["wall_time_per_usable_controlled_s"] is None
             else round(eff["wall_time_per_usable_controlled_s"], 1)))
    print("=== 무결성 ===")
    print("   files", file_counts, "contiguous", integ["contiguous"])
    print("   missing %d dup %d corrupt %d empty %d subset위반 %d magenta %d "
          ">10m %d invalid %d gate실패 %d"
          % (len(missing), len(duplicate), len(corrupt), len(empty_amodal),
             len(subset_fail), len(magenta), len(far), invalid,
             len(integ["gate_failures"])))
    print("   reproj max %s (gate %s)" % (integ["reproj_max_px"],
                                          integ["reproj_gate_pass"]))
    print("-> " + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
