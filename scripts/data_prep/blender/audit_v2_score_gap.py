"""controlled explicit 탐색의 score-gap · 후보 예산 감사 (읽기 전용, bpy-free).

수락 조건은 **코드에서 읽어 그대로 재구성**한다 (v2_realize `explicit_score`):

    accept = side_match
             and object_visible_pixels >= 8
             and abs_error <= EXPLICIT_TARGET_ABS_TOLERANCE
             and (G1_pass and G2_pass)

`score` 는 임계가 있는 값이 아니라 **랭킹용 음수 비용**(높을수록 좋음, 최대 0)이다.
따라서 canonical margin 은 유일하게 임계가 있는 축인 목표 오차에 둔다.

    score_margin = EXPLICIT_TARGET_ABS_TOLERANCE - abs_error
        > 0  통과측 · = 0 경계 · < 0 실패측

near-miss = **막고 있는 조건이 target_error_ok 하나뿐**이고 |margin| 이 작은 후보.
support / collision / camera_clearance 같은 hard 실패는 near-miss 가 아니다.

    python scripts/data_prep/blender/audit_v2_score_gap.py \
        --replay data/pallet/runs/diagnostics/_replay_controlled_g1p5 \
        --smoke  data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public \
        --out reports/v2_generator_fix_g1p6_g2c_g3/g1p6
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import scene_placement_v2 as SP2  # noqa: E402

TOL = SP2.EXPLICIT_TARGET_ABS_TOLERANCE
HARD_REASONS = ("support", "collision", "camera_clearance")
SUB_CONDITIONS = ("side_match", "visible_pixels_ge8", "target_error_ok",
                  "corner_joint_pass")


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def jsonl(path):
    if not os.path.isfile(path):
        return []
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def quant(values):
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return {}
    n = len(v)

    def at(q):
        return v[min(n - 1, max(0, int(round(q * (n - 1)))))]

    return {"n": n, "min": v[0], "p05": at(0.05), "p10": at(0.10),
            "p25": at(0.25), "median": at(0.50), "p75": at(0.75),
            "p95": at(0.95), "max": v[-1], "sum": sum(v)}


def canonical_key(candidate):
    """같은 geometry 를 stage 이름만 바꿔 재평가한 것을 하나로 센다."""
    center = candidate.get("center") or []
    parts = [str(candidate.get("proposal_object")),
             str(candidate.get("occluder_side_target"))]
    parts += ["%.6f" % float(value) for value in center]
    for key in ("yaw_rad", "u_offset", "v_offset", "depth_offset", "yaw_offset"):
        value = candidate.get(key)
        parts.append("na" if value is None else "%.6f" % float(value))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def blocking_conditions(candidate):
    """수락을 막고 있는 sub-condition 목록 (측정 안 됨은 unknown 으로 남긴다)."""
    blocking, unknown = [], []
    side = candidate.get("occluder_side_match")
    if side is None:
        unknown.append("side_match")
    elif not side:
        blocking.append("side_match")
    visible = candidate.get("object_visible_pixels")
    if visible is None:
        unknown.append("visible_pixels_ge8")
    elif int(visible) < 8:
        blocking.append("visible_pixels_ge8")
    ok = candidate.get("target_error_ok")
    if ok is None:
        unknown.append("target_error_ok")
    elif not ok:
        blocking.append("target_error_ok")
    g1, g2 = candidate.get("candidate_G1_pass"), candidate.get("candidate_G2_pass")
    if g1 is None or g2 is None:
        unknown.append("corner_joint_pass")
    elif not (g1 and g2):
        blocking.append("corner_joint_pass")
    return blocking, unknown


def load_controlled(root):
    """(record, outcome) 목록 — accepted 와 실제 Blender 를 돌린 reject 만."""
    out = []
    for rec in jsonl(os.path.join(root, "records.jsonl")):
        if rec.get("diagnostic_mode") == "controlled-occlusion":
            out.append((rec, "accepted" if rec.get("usable") is not False
                        else "rejected"))
    for row in jsonl(os.path.join(root, "records_rejected.jsonl")):
        if row.get("diagnostic_mode") != "controlled-occlusion":
            continue
        rec = row.get("record") or {}
        if row.get("stage") != "render":
            continue
        if rec.get("explicit_solver_fail_reason") == \
                "diagnostic_explicit_prefilter_exhausted":
            continue
        out.append((rec, "rejected"))
    return out


def load_replay(root):
    out = []
    for rec in jsonl(os.path.join(root, "replay_records.jsonl")):
        out.append((rec, "accepted" if rec.get("usable") else "rejected"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--replay", required=True, help="locked replay 출력 디렉토리")
    ap.add_argument("--smoke", required=True, help="mixed smoke 출력 디렉토리")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)

    sources = [("locked_replay", load_replay(_abs(args.replay))),
               ("smoke100b", load_controlled(_abs(args.smoke)))]

    cand_rows, case_rows, budget_rows = [], [], []
    for source, records in sources:
        for rec, outcome in records:
            case_id = "%s:%s" % (source, rec.get("proposal_index"))
            log = rec.get("explicit_candidate_log") or []
            stage_rt = rec.get("stage_runtime_s") or {}
            seen_keys = {}
            per_stage = collections.Counter()
            near_margins = []
            for order, cand in enumerate(log):
                key = canonical_key(cand)
                duplicate = key in seen_keys
                seen_keys.setdefault(key, order)
                blocking, unknown = blocking_conditions(cand)
                error = cand.get("abs_error")
                margin = None if error is None else TOL - float(error)
                stage = cand.get("stage")
                per_stage[stage] += 1
                near = bool(blocking == ["target_error_ok"] and not unknown)
                if near and margin is not None:
                    near_margins.append(abs(margin))
                cand_rows.append({
                    "source": source, "case_id": case_id,
                    "proposal_index": rec.get("proposal_index"),
                    "usable_slot": rec.get("usable_slot"),
                    "case_outcome": outcome,
                    "order": order, "stage": stage,
                    "proposal_object": cand.get("proposal_object"),
                    "canonical_key": key, "duplicate_geometry": duplicate,
                    "reject_reason": cand.get("reason"),
                    "score": cand.get("score"),
                    "score_accept": cand.get("score_accept"),
                    "abs_error": error,
                    "accept_threshold_abs_error": TOL,
                    "score_margin": margin,
                    "abs_score_gap": None if margin is None else abs(margin),
                    "blocking_conditions": "|".join(blocking),
                    "unknown_conditions": "|".join(unknown),
                    "is_near_miss": near,
                    "hard_reject": cand.get("reason") in HARD_REASONS,
                    "object_visible_pixels": cand.get("object_visible_pixels"),
                    "occluder_side_match": cand.get("occluder_side_match"),
                    "candidate_G1_pass": cand.get("candidate_G1_pass"),
                    "candidate_G2_pass": cand.get("candidate_G2_pass"),
                    "object_screen_gap_px": cand.get("object_screen_gap_px"),
                })
            ts_total = per_stage.get("target-seed", 0)
            ts_keys = {canonical_key(c) for c in log if c.get("stage") == "target-seed"}
            case_rows.append({
                "source": source, "case_id": case_id,
                "proposal_index": rec.get("proposal_index"),
                "usable_slot": rec.get("usable_slot"),
                "old_outcome": rec.get("old_outcome"),
                "current_outcome": outcome,
                "solver_fail_reason": rec.get("explicit_solver_fail_reason"),
                "winning_stage": rec.get("explicit_selected_stage"),
                "candidates_logged": len(log),
                "unique_candidates": len(seen_keys),
                "duplicate_candidates": len(log) - len(seen_keys),
                "target_seed_candidate_count": ts_total,
                "target_seed_unique_candidate_count": len(ts_keys),
                "target_seed_free_evals": ts_total,      # 현재는 전부 free
                "target_seed_paid_evals": 0,
                "total_budgeted_evals": len(log) - ts_total,
                "gate_overlap_evals": per_stage.get("gate-overlap-refine", 0),
                "corner_contact_evals": per_stage.get("corner-contact-refine", 0),
                "primary_evals": per_stage.get("primary", 0),
                "rescue_evals": per_stage.get("rescue", 0),
                "refine_evals": per_stage.get("refine", 0),
                "feedback_evals": per_stage.get("feedback", 0),
                "fine_eval_count": rec.get("fine_eval_count"),
                "candidate_budget_exhausted": int(
                    (rec.get("explicit_reject_counts_by_reason") or {})
                    .get("candidate_budget_exhausted", 0)),
                "score_callback_rejects": int(
                    (rec.get("explicit_reject_counts_by_reason") or {})
                    .get("score_callback", 0)),
                "near_miss_candidates": len(near_margins),
                "best_near_miss_gap": min(near_margins) if near_margins else None,
                "runtime_s": rec.get("runtime_s"),
                "stage_explicit_s": stage_rt.get("explicit"),
                "stage_context_s": stage_rt.get("context"),
                "stage_explicit_prep_s": stage_rt.get("explicit_prep"),
                "projected_size": rec.get("projected_size_target"),
                "f_target": rec.get("f_target"),
                "side": rec.get("occluder_side_target"),
                "elevation_deg": rec.get("elev_target"),
                "camera_distance_m": rec.get("camera_distance_target_m"),
            })
            budget_rows.append({
                "source": source, "case_id": case_id,
                "case_outcome": outcome,
                "old_outcome": rec.get("old_outcome"),
                "target_seed_candidate_count": ts_total,
                "target_seed_unique_candidate_count": len(ts_keys),
                "target_seed_duplicate_count": ts_total - len(ts_keys),
                "budgeted_evals_excluding_target_seed": len(log) - ts_total,
                "candidate_budget_exhausted": int(
                    (rec.get("explicit_reject_counts_by_reason") or {})
                    .get("candidate_budget_exhausted", 0)),
                "winning_stage": rec.get("explicit_selected_stage"),
            })

    def write(name, rows):
        with io.open(os.path.join(out, name), "w", encoding="utf-8",
                     newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write("score_gap_candidates.csv", cand_rows)
    write("score_gap_cases.csv", case_rows)
    write("target_seed_budget_audit.csv", budget_rows)

    # ---- 요약 ------------------------------------------------------------
    summary = {"accept_rule": (
        "side_match AND object_visible_pixels>=8 AND "
        "abs_error<=%.4f AND (G1_pass AND G2_pass)" % TOL),
        "score_semantics": "score = -(cost); 높을수록 좋음, 임계 없음 (랭킹용)",
        "score_margin": "EXPLICIT_TARGET_ABS_TOLERANCE - abs_error",
        "tolerance": TOL}
    for source, _ in sources:
        cands = [c for c in cand_rows if c["source"] == source]
        cases = [c for c in case_rows if c["source"] == source]
        acc = [c for c in cases if c["current_outcome"] == "accepted"]
        rej = [c for c in cases if c["current_outcome"] != "accepted"]
        sc_rej = [c for c in cands if c["reject_reason"] == "score_callback"]
        near = [c for c in cands if c["is_near_miss"]]
        summary[source] = {
            "cases": len(cases), "accepted": len(acc), "rejected": len(rej),
            "candidates": len(cands),
            "duplicate_candidates": sum(1 for c in cands
                                        if c["duplicate_geometry"]),
            "score_callback_rejects": len(sc_rej),
            "near_miss_candidates": len(near),
            "blocking_condition_counts": dict(collections.Counter(
                c["blocking_conditions"] for c in cands if c["blocking_conditions"])),
            "reject_reason_counts": dict(collections.Counter(
                c["reject_reason"] for c in cands)),
            "abs_score_gap_all_score_callback": quant(
                [c["abs_score_gap"] for c in sc_rej]),
            "abs_score_gap_near_miss": quant([c["abs_score_gap"] for c in near]),
            "target_seed_free_evals": quant(
                [c["target_seed_candidate_count"] for c in cases]),
            "target_seed_free_evals_accepted": quant(
                [c["target_seed_candidate_count"] for c in acc]),
            "target_seed_unique": quant(
                [c["target_seed_unique_candidate_count"] for c in cases]),
            "fine_eval_count": quant([c["fine_eval_count"] for c in cases]),
            "candidate_budget_exhausted_total": sum(
                c["candidate_budget_exhausted"] for c in cases),
            "explicit_runtime_s": quant([c["stage_explicit_s"] for c in cases]),
            "winning_stage_counts": dict(collections.Counter(
                c["winning_stage"] for c in acc)),
        }
    io.open(os.path.join(out, "score_gap_summary.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(summary, indent=2,
                                           ensure_ascii=False) + "\n")

    for key, value in summary.items():
        if isinstance(value, dict):
            print("\n=== %s ===" % key)
            for k2, v2 in value.items():
                print("  %-38s %s" % (k2, json.dumps(v2, ensure_ascii=False)
                                      if isinstance(v2, dict) else v2))
        else:
            print("%-18s %s" % (key, value))
    print("\n-> " + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
