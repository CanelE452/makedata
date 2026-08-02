"""locked controlled replay 의 before/after 비교 (읽기 전용, bpy-free).

    python scripts/data_prep/blender/audit_controlled_replay.py \
        --cases reports/v2_generator_fix_g1p5_g2b/g1p5/locked_controlled_cases.json \
        --replay data/pallet/runs/diagnostics/_replay_controlled_g1p5 \
        --out reports/v2_generator_fix_g1p5_g2b/g1p5

필수 게이트 (§5)
    accepted recall 30/30 · explicit visible px>0 유지 · side match 유지 ·
    explicit_metrics_available 전건 · explicit_abs_error_lowres 악화 없음
효율
    total Blender time · 실패 프레임의 context 낭비 · attempt 수 · budget 소진
"""
import argparse
import collections
import csv
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def q(values):
    values = sorted(float(v) for v in values if v is not None)
    if not values:
        return {}
    n = len(values)
    return {"n": n, "min": values[0], "median": values[n // 2],
            "p95": values[min(n - 1, int(0.95 * n))], "max": values[-1],
            "sum": sum(values)}


def fmt(stats, unit=""):
    if not stats:
        return "-"
    return ("n=%d min %.3f med %.3f p95 %.3f max %.3f%s"
            % (stats["n"], stats["min"], stats["median"], stats["p95"],
               stats["max"], unit))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    payload = json.load(io.open(_abs(args.cases), encoding="utf-8"))
    cases = {int(c["proposal_index"]): c for c in payload["cases"]}
    replay = {}
    for line in io.open(os.path.join(_abs(args.replay), "replay_records.jsonl"),
                        encoding="utf-8"):
        if line.strip():
            record = json.loads(line)
            replay[int(record["proposal_index"])] = record
    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)

    rows = []
    for proposal_index in sorted(cases):
        case = cases[proposal_index]
        new = replay.get(proposal_index)
        stage = (new or {}).get("stage_runtime_s") or {}
        rows.append({
            "proposal_index": proposal_index,
            "usable_slot": case["usable_slot"],
            "old_outcome": case["old_outcome"],
            "new_outcome": (None if new is None
                            else ("accepted" if new.get("usable")
                                  else "rejected")),
            "replayed": new is not None,
            "old_runtime_s": case["old_runtime_s"],
            "new_runtime_s": (new or {}).get("runtime_s"),
            "old_stage_context_s": case["old_stage_context_s"],
            "new_stage_context_s": stage.get("context"),
            "old_stage_explicit_s": case["old_stage_explicit_s"],
            "new_stage_explicit_s": stage.get("explicit"),
            "new_stage_explicit_prep_s": stage.get("explicit_prep"),
            "old_explicit_visible_pixels": case["old_explicit_visible_pixels"],
            "new_explicit_visible_pixels": (new or {}).get(
                "explicit_occluder_visible_pixels"),
            "old_side_match": case["old_side_match"],
            "new_side_match": (new or {}).get("occluder_side_match"),
            "new_metrics_available": (new or {}).get("explicit_metrics_available"),
            "new_f_explicit_target": (new or {}).get("f_explicit_target"),
            "new_f_explicit_actual_lowres": (new or {}).get(
                "f_explicit_actual_lowres"),
            "new_explicit_abs_error_lowres": (new or {}).get(
                "explicit_abs_error_lowres"),
            "old_realization_attempt_count": case["old_realization_attempt_count"],
            "new_realization_attempt_count": (new or {}).get(
                "realization_attempt_count"),
            "new_coarse_eval_count": (new or {}).get("coarse_eval_count"),
            "new_fine_eval_count": (new or {}).get("fine_eval_count"),
            "new_search_winning_stage": (new or {}).get("search_winning_stage"),
            "new_solver_fail_reason": (new or {}).get(
                "explicit_solver_fail_reason"),
            "old_solver_fail_reason": case["old_solver_fail_reason"],
            "new_context_skipped": (new or {}).get(
                "context_skipped_due_to_explicit_failure"),
            "new_reject_counts": json.dumps(
                (new or {}).get("explicit_reject_counts_by_reason") or {},
                sort_keys=True, ensure_ascii=False),
        })
    with io.open(os.path.join(out, "replay_before_after.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    old_acc = [r for r in rows if r["old_outcome"] == "accepted"]
    old_exp = [r for r in rows if r["old_outcome"] == "expensive_reject"]
    recall = sum(1 for r in old_acc if r["new_outcome"] == "accepted")
    recovered = sum(1 for r in old_exp if r["new_outcome"] == "accepted")
    new_acc = [r for r in rows if r["new_outcome"] == "accepted"]

    old_total = sum(float(r["old_runtime_s"] or 0) for r in rows)
    new_total = sum(float(r["new_runtime_s"] or 0) for r in rows)
    old_ctx_waste = sum(float(r["old_stage_context_s"] or 0) for r in old_exp)
    new_ctx_waste = sum(float(r["new_stage_context_s"] or 0) for r in rows
                        if r["new_outcome"] == "rejected")
    budget_old = sum(json.loads(cases[r["proposal_index"]]["old_reject_counts"])
                     .get("candidate_budget_exhausted", 0) for r in rows)
    budget_new = sum(json.loads(r["new_reject_counts"])
                     .get("candidate_budget_exhausted", 0) for r in rows)
    score_old = sum(json.loads(cases[r["proposal_index"]]["old_reject_counts"])
                    .get("score_callback", 0) for r in rows)
    score_new = sum(json.loads(r["new_reject_counts"])
                    .get("score_callback", 0) for r in rows)

    summary = {
        "n_cases": len(rows),
        "replayed": sum(1 for r in rows if r["replayed"]),
        "accepted_recall": {"kept": recall, "of": len(old_acc),
                            "pass": recall == len(old_acc)},
        "recovered_from_expensive_reject": recovered,
        "new_accepted_total": len(new_acc),
        "explicit_visible_gt0": sum(1 for r in new_acc
                                    if (r["new_explicit_visible_pixels"] or 0) > 0),
        "side_match": sum(1 for r in new_acc if r["new_side_match"] is True),
        "metrics_available": sum(1 for r in new_acc
                                 if r["new_metrics_available"] is True),
        "abs_error_lowres": q([r["new_explicit_abs_error_lowres"]
                               for r in new_acc]),
        "runtime": {
            "old_total_s": round(old_total, 1),
            "new_total_s": round(new_total, 1),
            "delta_pct": (round(100.0 * (new_total - old_total) / old_total, 1)
                          if old_total else None),
            "old_context_waste_on_failure_s": round(old_ctx_waste, 1),
            "new_context_waste_on_failure_s": round(new_ctx_waste, 1),
        },
        "attempts": {
            "old": q([r["old_realization_attempt_count"] for r in rows]),
            "new": q([r["new_realization_attempt_count"] for r in rows]),
        },
        "candidate_budget_exhausted": {"old": budget_old, "new": budget_new},
        "score_callback_rejects": {"old": score_old, "new": score_new},
        "winning_stage_counts": dict(collections.Counter(
            r["new_search_winning_stage"] for r in new_acc)),
        "new_solver_fail_counts": dict(collections.Counter(
            r["new_solver_fail_reason"] for r in rows
            if r["new_outcome"] == "rejected")),
    }
    io.open(os.path.join(out, "replay_before_after.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    lines = [
        "# locked controlled benchmark — before / after",
        "",
        f"고정 사례 {summary['n_cases']}건 "
        f"(old accepted {len(old_acc)} · old expensive reject {len(old_exp)})",
        f"replay `{args.replay}` · 같은 seed · 같은 FrameSpec/Plan · dataset-quality",
        "",
        "## 1. 필수 게이트",
        "```",
        f"accepted recall              {recall} / {len(old_acc)}"
        f"   {'PASS' if recall == len(old_acc) else 'FAIL'}",
        f"explicit visible px > 0      {summary['explicit_visible_gt0']} / {len(new_acc)}",
        f"side match                   {summary['side_match']} / {len(new_acc)}",
        f"explicit_metrics_available   {summary['metrics_available']} / {len(new_acc)}",
        f"abs error (lowres)           {fmt(summary['abs_error_lowres'])}",
        "```",
        "",
        "## 2. 효율",
        "```",
        f"total Blender time           {old_total:,.0f} s  ->  {new_total:,.0f} s"
        f"   ({summary['runtime']['delta_pct']:+.1f}%)",
        f"실패 프레임의 context 낭비    {old_ctx_waste:,.0f} s  ->  {new_ctx_waste:,.0f} s",
        f"score_callback reject 누적    {score_old:,}  ->  {score_new:,}",
        f"candidate_budget_exhausted   {budget_old:,}  ->  {budget_new:,}",
        f"realization attempts (med)   "
        f"{summary['attempts']['old'].get('median')}  ->  "
        f"{summary['attempts']['new'].get('median')}",
        f"expensive reject 에서 복구    {recovered} 건",
        "```",
        "",
        "## 3. 승리 stage 분포 (새 accepted)",
        "```",
    ]
    for stage_name, count in sorted(summary["winning_stage_counts"].items(),
                                    key=lambda kv: -kv[1]):
        lines.append(f"{str(stage_name):<28} {count}")
    lines += ["```", "", "## 4. 새 실패 사유", "```"]
    for reason, count in sorted(summary["new_solver_fail_counts"].items(),
                                key=lambda kv: -kv[1]):
        lines.append(f"{str(reason):<44} {count}")
    lines += ["```", ""]
    io.open(os.path.join(out, "replay_before_after.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(lines) + "\n")

    print("\n".join(lines[3:]))
    return 0 if recall == len(old_acc) else 1


if __name__ == "__main__":
    raise SystemExit(main())
