"""candidate-level binding-constraint 감사 (읽기 전용, bpy-free).

"실패 case 에서 실제로 막는 제약이 무엇이며, 그 제약에 맞춘 소규모 rescue 가 의미 있는
비용을 차지하는가"를 후보 단위로 판정한다.

수락 계약은 **코드에서 읽은 그대로** 재구성한다 (v2_realize `explicit_score`,
scene_placement_v2 `external_corner_gate_metrics`):

    HARD_PHYSICAL        support · collision · camera_clearance
                         (이 단계에서 탈락한 후보는 acceptance 를 보지도 못한다)
    ACCEPTANCE (5)       side_match
                         object_visible_pixels >= 8
                         abs_error <= EXPLICIT_TARGET_ABS_TOLERANCE
                         G1: V_vis >= 4
                         G2: 1 <= ext_occ_corners <= 4
    RANKING_ONLY         score = -(error + roi + 0.25*corner + screen + visibility)
                         임계가 아니라 정렬용.  동률일 때만 tie-break.

    python scripts/data_prep/blender/audit_v2_binding_constraints.py \
        --replay data/pallet/runs/diagnostics/_locked77_g1p6 \
        --out reports/v2_generator_fix_g1p7_g2d_g3/g1p7
"""
import argparse
import collections
import csv
import io
import json
import os
import statistics as st
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import scene_placement_v2 as SP2  # noqa: E402

TOL = SP2.EXPLICIT_TARGET_ABS_TOLERANCE
MIN_VISIBLE_PX = 8
G1_MIN_V_VIS = 4
G2_MIN_EXT, G2_MAX_EXT = 1, 4
HARD_REASONS = ("support", "collision", "camera_clearance")
ACCEPTANCE = ("side", "visibility", "target", "G1", "G2")


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def jsonl(path):
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def geometry_key(cand):
    """canonical geometry key — stage 이름만 다른 재평가를 하나로 센다.

    float 는 solver 가 실제로 쓰는 분해능(1e-6 m / rad)으로만 정규화한다.
    """
    center = cand.get("center") or ()
    parts = [str(cand.get("proposal_object")),
             str(cand.get("occluder_side_target"))]
    parts += ["%.6f" % float(v) for v in center]
    for key in ("yaw_rad", "u_offset", "v_offset", "depth_offset", "yaw_offset"):
        value = cand.get(key)
        parts.append("na" if value is None else "%.6f" % float(value))
    return "|".join(parts)


def constraint_view(cand):
    """후보 하나의 hard/acceptance 상태와 margin.  측정 안 된 값은 None 이다."""
    reason = cand.get("reason")
    hard_fail = reason in HARD_REASONS
    reached = cand.get("abs_error") is not None       # score callback 도달 여부

    side = cand.get("occluder_side_match")
    visible = cand.get("object_visible_pixels")
    error = cand.get("abs_error")
    v_vis = cand.get("candidate_V_vis")
    ext = cand.get("candidate_ext_occ_corners")

    view = {
        "hard_physical_pass": (not hard_fail),
        "hard_fail_reason": reason if hard_fail else None,
        "reached_acceptance": bool(reached),
        "side_pass": None if side is None else bool(side),
        "visibility_margin_px": (None if visible is None
                                 else int(visible) - MIN_VISIBLE_PX),
        "visibility_pass": (None if visible is None
                            else int(visible) >= MIN_VISIBLE_PX),
        "target_margin": None if error is None else TOL - float(error),
        "target_pass": (None if error is None
                        else float(error) <= TOL),
        "G1_margin": None if v_vis is None else int(v_vis) - G1_MIN_V_VIS,
        "G1_pass": None if v_vis is None else int(v_vis) >= G1_MIN_V_VIS,
        "G2_margin": (None if ext is None
                      else min(int(ext) - G2_MIN_EXT, G2_MAX_EXT - int(ext))),
        "G2_pass": (None if ext is None
                    else G2_MIN_EXT <= int(ext) <= G2_MAX_EXT),
        "V_vis": v_vis, "ext_occ_corners": ext,
        "visible_pixels": visible, "abs_error": error,
        "score": cand.get("score"), "score_accept": cand.get("score_accept"),
    }
    violated, unknown = [], []
    for name, key in (("side", "side_pass"), ("visibility", "visibility_pass"),
                      ("target", "target_pass"), ("G1", "G1_pass"),
                      ("G2", "G2_pass")):
        value = view[key]
        if value is None:
            unknown.append(name)
        elif not value:
            violated.append(name)
    view["violated"] = violated
    view["unknown"] = unknown
    view["violation_count"] = (None if unknown else len(violated))
    return view


def classify(case_views):
    """case 하나의 binding signature (§9).

    signature 는 **어떤 제약이 막았는가**만으로 정한다.  예산 소진 여부는 직교하는
    축이므로 여기서 섞지 않는다 (섞으면 모든 case 가 BUDGET_EXHAUSTED 로 뭉쳐
    binding 정보가 사라진다).

    best = 최소 violation 수.  동수 tie-break 는 §9 대로 **deterministic constraint
    name 순서**다 (runtime 영향이 큰 순서나 빈도 순서가 아니다).
    """
    if any(v["score_accept"] for v in case_views):
        return "ACCEPTED", []
    evaluated = [v for v in case_views
                 if v["reached_acceptance"] and v["violation_count"] is not None]
    if not evaluated:
        return "HARD_PHYSICAL_ONLY", []
    actionable = sorted({
        ("ONE_MISS_" + v["violated"][0].upper()) if len(v["violated"]) == 1
        else ("TWO_MISS_" + "_".join(sorted(s.upper() for s in v["violated"])))
        for v in evaluated if 1 <= v["violation_count"] <= 2})
    best = min(v["violation_count"] for v in evaluated)
    if best == 0:
        return "ACCEPTED", actionable      # gate 밖 사유로 실패한 경우
    tied = [v for v in evaluated if v["violation_count"] == best]
    if best == 1:
        return "ONE_MISS_" + sorted(v["violated"][0]
                                    for v in tied)[0].upper(), actionable
    if best == 2:
        return "TWO_MISS_" + sorted("_".join(sorted(s.upper()
                                                    for s in v["violated"]))
                                    for v in tied)[0], actionable
    return "MULTI_CONSTRAINT", actionable


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wall-field", default="replay_wall_s",
                    help="CASE_WALL_TIME_S 로 쓸 record 필드")
    args = ap.parse_args(argv)
    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)

    records = jsonl(os.path.join(_abs(args.replay), "replay_records.jsonl"))

    cand_rows, case_rows, dedup_rows = [], [], []
    for rec in records:
        pi = int(rec["proposal_index"])
        log = rec.get("explicit_candidate_log") or []
        seen, views, raw_stage = {}, [], collections.Counter()
        stage_cross = 0
        for order, cand in enumerate(log):
            key = geometry_key(cand)
            raw_stage[cand.get("stage")] += 1
            duplicate = key in seen
            if duplicate and seen[key] != cand.get("stage"):
                stage_cross += 1
            view = constraint_view(cand)
            cand_rows.append({
                "case_id": pi, "candidate_id": "%d:%d" % (pi, order),
                "order": order, "stage": cand.get("stage"),
                "asset": cand.get("proposal_object"),
                "geometry_key": key, "duplicate_geometry": duplicate,
                "reject_reason": cand.get("reason"),
                "hard_physical_pass": view["hard_physical_pass"],
                "hard_fail_reason": view["hard_fail_reason"],
                "reached_acceptance": view["reached_acceptance"],
                "side_pass": view["side_pass"],
                "visible_pixels": view["visible_pixels"],
                "visibility_margin_px": view["visibility_margin_px"],
                "abs_error": view["abs_error"],
                "target_margin": view["target_margin"],
                "V_vis": view["V_vis"], "G1_margin": view["G1_margin"],
                "ext_occ_corners": view["ext_occ_corners"],
                "G2_margin": view["G2_margin"],
                "violated": "|".join(view["violated"]),
                "unknown": "|".join(view["unknown"]),
                "violation_count": view["violation_count"],
                "score": view["score"], "score_accept": view["score_accept"],
                "u_offset": cand.get("u_offset"), "v_offset": cand.get("v_offset"),
                "depth_offset": cand.get("depth_offset"),
                "yaw_offset": cand.get("yaw_offset"),
            })
            if not duplicate:
                seen[key] = cand.get("stage")
                views.append(view)
        signature, actionable = classify(views)
        accepted = bool(rec.get("usable"))
        budget_ex = int((rec.get("explicit_reject_counts_by_reason") or {})
                        .get("candidate_budget_exhausted", 0))
        near45 = sum(1 for v in views if v["violation_count"] == 1)
        near35 = sum(1 for v in views if v["violation_count"] == 2)
        case_rows.append({
            "case_id": pi, "usable_slot": rec.get("usable_slot"),
            "old_outcome": rec.get("old_outcome"),
            "outcome": "accepted" if accepted else "rejected",
            "primary_binding_signature": ("ACCEPTED" if accepted else signature),
            # §9 의 나머지 두 분류는 primary 와 직교하는 축이라 별도 열로 둔다.
            "case_class": (
                "ACCEPTED" if accepted
                else "HARD_PHYSICAL_ONLY" if signature == "HARD_PHYSICAL_ONLY"
                else "BUDGET_EXHAUSTED_WITH_ACTIONABLE_CANDIDATE"
                if budget_ex and (near45 or near35)
                else "NO_FEASIBLE_CANDIDATE_FOUND" if not actionable
                else "ACTIONABLE_NO_BUDGET_EXHAUSTION"),
            "budget_exhausted_with_near_feasible": bool(
                (not accepted) and budget_ex and (near45 or near35)),
            "min_violation_count": (min((v["violation_count"] for v in views
                                         if v["violation_count"] is not None),
                                        default=None)),
            "all_actionable_signatures": "|".join(actionable),
            "near_feasible_4of5": near45, "near_feasible_3of5": near35,
            "raw_candidates": len(log), "unique_candidates": len(seen),
            "duplicate_candidates": len(log) - len(seen),
            "stage_crossing_duplicates": stage_cross,
            "hard_only_candidates": sum(1 for v in views
                                        if not v["hard_physical_pass"]),
            "candidate_budget_exhausted": budget_ex,
            "case_wall_time_s": rec.get(args.wall_field),
            "stage_runtime_total_s": rec.get("runtime_s"),
            "stage_explicit_s": (rec.get("stage_runtime_s") or {}).get("explicit"),
            "lowres_render_count": rec.get("lowres_render_count"),
            "winning_stage": rec.get("explicit_selected_stage"),
            "projected_size": rec.get("projected_size_target"),
            "f_target": rec.get("f_target"), "side": rec.get("occluder_side_target"),
        })
        dedup_rows.append({
            "case_id": pi, "raw_candidates": len(log),
            "unique_geometry": len(seen),
            "duplicates": len(log) - len(seen),
            "stage_crossing_duplicates": stage_cross,
            "stages": json.dumps(dict(raw_stage), ensure_ascii=False),
        })

    def write(name, rows):
        with io.open(os.path.join(out, name), "w", encoding="utf-8",
                     newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    write("binding_candidates.csv", cand_rows)
    write("binding_cases.csv", case_rows)
    write("candidate_dedup_audit.csv", dedup_rows)

    # ---- §10 runtime 기준 집계 ------------------------------------------
    rejected = [c for c in case_rows if c["outcome"] == "rejected"]
    rej_wall = sum(float(c["case_wall_time_s"] or 0) for c in rejected)
    groups = collections.defaultdict(list)
    for c in rejected:
        groups[c["primary_binding_signature"]].append(c)

    runtime_rows = []
    for name, rows in sorted(groups.items(),
                             key=lambda kv: -sum(float(c["case_wall_time_s"] or 0)
                                                 for c in kv[1])):
        wall = [float(c["case_wall_time_s"] or 0) for c in rows]
        runtime_rows.append({
            "binding_signature": name, "cases": len(rows),
            "case_fraction": len(rows) / len(rejected),
            "wall_time_s": round(sum(wall), 1),
            "wall_fraction": (sum(wall) / rej_wall) if rej_wall else 0.0,
            "wall_median_s": round(st.median(wall), 1),
            "wall_p95_s": round(sorted(wall)[min(len(wall) - 1,
                                                 int(0.95 * len(wall)))], 1),
            "stage_runtime_s": round(sum(float(c["stage_runtime_total_s"] or 0)
                                         for c in rows), 1),
            "unique_candidates_median": st.median(
                [c["unique_candidates"] for c in rows]),
            "lowres_render_median": st.median(
                [float(c["lowres_render_count"] or 0) for c in rows]),
            "budget_exhausted_cases": sum(1 for c in rows
                                          if c["candidate_budget_exhausted"]),
            "near_feasible_4of5_cases": sum(1 for c in rows
                                            if c["near_feasible_4of5"]),
        })
    write("binding_runtime.csv", runtime_rows)

    # actionable = 최선 후보가 1개 또는 2개 제약만 어긴 case (= 국소 rescue 사정권)
    actionable_rows = [r for r in runtime_rows
                       if r["binding_signature"].startswith("ONE_MISS_")
                       or r["binding_signature"].startswith("TWO_MISS_")]
    top2 = actionable_rows[:2]
    near45_wall = sum(float(c["case_wall_time_s"] or 0) for c in rejected
                      if c["near_feasible_4of5"] > 0)
    hard_only_wall = sum(float(c["case_wall_time_s"] or 0) for c in rejected
                         if c["primary_binding_signature"] == "HARD_PHYSICAL_ONLY")
    nofeasible_wall = sum(
        float(c["case_wall_time_s"] or 0) for c in rejected
        if c["primary_binding_signature"].startswith("MULTI_CONSTRAINT"))

    readiness = {
        "rejected_cases": len(rejected),
        "rejected_wall_time_s": round(rej_wall, 1),
        "wall_field": args.wall_field,
        "gate_A_top2_actionable": {
            "categories": [r["binding_signature"] for r in top2],
            "wall_time_s": round(sum(r["wall_time_s"] for r in top2), 1),
            "fraction": (sum(r["wall_time_s"] for r in top2) / rej_wall)
            if rej_wall else 0.0,
            "pass": (sum(r["wall_time_s"] for r in top2) / rej_wall >= 0.50)
            if rej_wall else False},
        "gate_B_near_feasible_4of5": {
            "cases": sum(1 for c in rejected if c["near_feasible_4of5"] > 0),
            "wall_time_s": round(near45_wall, 1),
            "fraction": (near45_wall / rej_wall) if rej_wall else 0.0,
            "pass": (near45_wall / rej_wall >= 0.50) if rej_wall else False},
        "hard_physical_only": {
            "cases": sum(1 for c in rejected
                         if c["primary_binding_signature"] == "HARD_PHYSICAL_ONLY"),
            "wall_fraction": (hard_only_wall / rej_wall) if rej_wall else 0.0},
        "multi_constraint_no_feasible": {
            "cases": sum(1 for c in rejected
                         if c["primary_binding_signature"]
                         .startswith("MULTI_CONSTRAINT")),
            "wall_fraction": (nofeasible_wall / rej_wall) if rej_wall else 0.0},
        "budget_exhausted_with_near_feasible": {
            "cases": sum(1 for c in rejected
                         if c["budget_exhausted_with_near_feasible"]),
            "wall_time_s": round(sum(float(c["case_wall_time_s"] or 0)
                                     for c in rejected
                                     if c["budget_exhausted_with_near_feasible"]), 1)},
        "actionable_categories": actionable_rows,
    }
    readiness["not_dominated_by_hard_physical"] = (
        readiness["hard_physical_only"]["wall_fraction"] < 0.50)
    readiness["not_dominated_by_no_feasible"] = (
        readiness["multi_constraint_no_feasible"]["wall_fraction"] < 0.50)
    readiness["RESCUE_READY"] = bool(
        (readiness["gate_A_top2_actionable"]["pass"]
         or readiness["gate_B_near_feasible_4of5"]["pass"])
        and readiness["not_dominated_by_hard_physical"]
        and readiness["not_dominated_by_no_feasible"])
    io.open(os.path.join(out, "rescue_readiness.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(readiness, indent=2,
                                           ensure_ascii=False) + "\n")

    summary = {
        "cases": len(case_rows),
        "accepted": sum(1 for c in case_rows if c["outcome"] == "accepted"),
        "rejected": len(rejected),
        "raw_candidates": sum(c["raw_candidates"] for c in case_rows),
        "unique_candidates": sum(c["unique_candidates"] for c in case_rows),
        "duplicates": sum(c["duplicate_candidates"] for c in case_rows),
        "stage_crossing_duplicates": sum(c["stage_crossing_duplicates"]
                                         for c in case_rows),
        "signature_counts": dict(collections.Counter(
            c["primary_binding_signature"] for c in case_rows)),
        "runtime_rows": runtime_rows,
        "readiness": readiness,
    }
    io.open(os.path.join(out, "binding_summary.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(summary, indent=2,
                                           ensure_ascii=False) + "\n")

    print("cases %d (accepted %d · rejected %d)"
          % (summary["cases"], summary["accepted"], summary["rejected"]))
    print("candidates raw %d · unique %d · duplicate %d (stage-crossing %d)"
          % (summary["raw_candidates"], summary["unique_candidates"],
             summary["duplicates"], summary["stage_crossing_duplicates"]))
    print("\n=== binding signature (rejected, CASE_WALL_TIME_S 기준 정렬) ===")
    print("%-46s %5s %8s %8s %8s" % ("signature", "cases", "wall_s", "wall%", "med_s"))
    for r in runtime_rows:
        print("%-46s %5d %8.1f %7.1f%% %8.1f"
              % (r["binding_signature"], r["cases"], r["wall_time_s"],
                 100 * r["wall_fraction"], r["wall_median_s"]))
    print("\nrejected wall total %.1f s" % rej_wall)
    print("\n=== §11 rescue readiness ===")
    print("  A top2 actionable %s  %.1f s (%.1f%%)  pass=%s"
          % (readiness["gate_A_top2_actionable"]["categories"],
             readiness["gate_A_top2_actionable"]["wall_time_s"],
             100 * readiness["gate_A_top2_actionable"]["fraction"],
             readiness["gate_A_top2_actionable"]["pass"]))
    print("  B near-feasible 4/5  %d cases  %.1f s (%.1f%%)  pass=%s"
          % (readiness["gate_B_near_feasible_4of5"]["cases"],
             readiness["gate_B_near_feasible_4of5"]["wall_time_s"],
             100 * readiness["gate_B_near_feasible_4of5"]["fraction"],
             readiness["gate_B_near_feasible_4of5"]["pass"]))
    print("  hard-physical-only %.1f%% · multi-constraint %.1f%%"
          % (100 * readiness["hard_physical_only"]["wall_fraction"],
             100 * readiness["multi_constraint_no_feasible"]["wall_fraction"]))
    print("  budget-exhausted with near-feasible: %d cases %.1f s"
          % (readiness["budget_exhausted_with_near_feasible"]["cases"],
             readiness["budget_exhausted_with_near_feasible"]["wall_time_s"]))
    print("  RESCUE_READY =", readiness["RESCUE_READY"])
    return 0 if readiness["RESCUE_READY"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
