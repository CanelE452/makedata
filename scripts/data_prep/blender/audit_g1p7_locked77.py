"""§13 locked77 hard quality + efficiency gate (읽기 전용, bpy-free).

게이트 수치는 지시문 §13 에서 그대로 고정한다 (실행 전 확정, 사후 조정 금지).
score_callback count 는 진단값이며 PASS/FAIL 에 쓰지 않는다.
"""
import argparse
import io
import json
import os
import statistics as st
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

GATES = {
    "wall_total_s": 4279.0,              # 4,754.4 x 0.90
    "rejected_stage_runtime_s": 2118.4,  # 2,492.2 x 0.85
    "accepted_median_stage_s": 50.2,     # 45.6 x 1.10
    "failed_context_s": 40.0,
    "paired_median_delta": 0.01,
    "paired_p95_delta": 0.02,
}
BASELINE = {
    "wall_total_s": 4754.4, "stage_total_s": 4641.6,
    "accepted_stage_s": 2149.4, "rejected_stage_s": 2492.2,
    "accepted_median_stage_s": 45.6, "failed_context_s": 31.5,
}


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def load(path):
    return {int(json.loads(l)["proposal_index"]): json.loads(l)
            for l in io.open(path, encoding="utf-8") if l.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    os.makedirs(out, exist_ok=True)

    base = load(os.path.join(_abs(a.baseline), "replay_records.jsonl"))
    run = load(os.path.join(_abs(a.replay), "replay_records.jsonl"))
    ids = sorted(set(base) & set(run))
    legacy_acc = [i for i in ids if base[i].get("usable")]
    kept = [i for i in legacy_acc if run[i].get("usable")]
    acc_now = [i for i in ids if run[i].get("usable")]
    rej_now = [i for i in ids if not run[i].get("usable")]

    pairs = [(float(base[i]["explicit_abs_error_lowres"]),
              float(run[i]["explicit_abs_error_lowres"]))
             for i in kept
             if base[i].get("explicit_abs_error_lowres") is not None
             and run[i].get("explicit_abs_error_lowres") is not None]

    def p95(v):
        v = sorted(v)
        return v[min(len(v) - 1, int(0.95 * len(v)))] if v else None

    wall_total = sum(float(run[i]["replay_wall_s"]) for i in ids)
    rej_stage = sum(float(run[i].get("runtime_s") or 0) for i in rej_now)
    acc_median = (st.median([float(run[i].get("runtime_s") or 0)
                             for i in acc_now]) if acc_now else 0.0)
    failed_ctx = sum(float((run[i].get("stage_runtime_s") or {}).get("context")
                           or 0) for i in rej_now)

    q = {
        "accepted_recall": "%d/%d" % (len(kept), len(legacy_acc)),
        "accepted_recall_ok": len(kept) == len(legacy_acc),
        "paired_metrics_ok": sum(1 for i in kept
                                 if run[i].get("explicit_metrics_available")),
        "paired_visible_ok": sum(
            1 for i in kept
            if (run[i].get("explicit_occluder_visible_pixels") or 0) >= 8),
        "paired_side_ok": sum(1 for i in kept
                              if run[i].get("occluder_side_match")),
        "paired_n": len(pairs),
        "paired_median_base": st.median([p[0] for p in pairs]) if pairs else None,
        "paired_median_run": st.median([p[1] for p in pairs]) if pairs else None,
        "paired_p95_base": p95([p[0] for p in pairs]),
        "paired_p95_run": p95([p[1] for p in pairs]),
        "post_context_regression": sum(
            1 for i in legacy_acc
            if (run[i].get("n_context_visible") or 0)
            < (base[i].get("n_context_visible") or 0)),
        "accepted_budget_exhausted": sum(
            1 for i in acc_now
            if (run[i].get("explicit_reject_counts_by_reason") or {})
            .get("candidate_budget_exhausted")),
        "semantics_regression": sum(
            1 for i in legacy_acc
            if base[i].get("mode_semantics_pass")
            and not run[i].get("mode_semantics_pass")),
    }
    q["quality_pass"] = bool(
        q["accepted_recall_ok"]
        and q["paired_metrics_ok"] == len(kept)
        and q["paired_visible_ok"] == len(kept)
        and q["paired_side_ok"] == len(kept)
        and (q["paired_median_run"] is None or q["paired_median_run"]
             <= q["paired_median_base"] + GATES["paired_median_delta"])
        and (q["paired_p95_run"] is None or q["paired_p95_run"]
             <= q["paired_p95_base"] + GATES["paired_p95_delta"])
        and q["post_context_regression"] == 0
        and q["accepted_budget_exhausted"] == 0
        and q["semantics_regression"] == 0)

    e = {
        "wall_total_s": round(wall_total, 1),
        "wall_gate_s": GATES["wall_total_s"],
        "wall_pass": wall_total <= GATES["wall_total_s"],
        "wall_baseline_s": BASELINE["wall_total_s"],
        "wall_delta_pct": round(
            100 * (wall_total - BASELINE["wall_total_s"])
            / BASELINE["wall_total_s"], 2),
        "rejected_stage_s": round(rej_stage, 1),
        "rejected_stage_gate_s": GATES["rejected_stage_runtime_s"],
        "rejected_stage_pass": rej_stage <= GATES["rejected_stage_runtime_s"],
        "accepted_median_stage_s": round(acc_median, 1),
        "accepted_median_gate_s": GATES["accepted_median_stage_s"],
        "accepted_median_pass": acc_median <= GATES["accepted_median_stage_s"],
        "failed_context_s": round(failed_ctx, 1),
        "failed_context_gate_s": GATES["failed_context_s"],
        "failed_context_pass": failed_ctx <= GATES["failed_context_s"],
        # 진단 전용
        "score_callback_count_diagnostic": sum(
            int((run[i].get("explicit_reject_counts_by_reason") or {})
                .get("score_callback", 0)) for i in ids),
        "rescue_triggered": sum(1 for i in ids if run[i].get("rescue_triggered")),
        "rescue_won": sum(1 for i in ids if run[i].get("rescue_won")),
        "newly_accepted": sorted(i for i in ids
                                 if run[i].get("usable")
                                 and not base[i].get("usable")),
    }
    e["efficiency_pass"] = bool(e["wall_pass"] and e["rejected_stage_pass"]
                                and e["accepted_median_pass"]
                                and e["failed_context_pass"])
    verdict = {"cases": len(ids), "quality": q, "efficiency": e,
               "G1P7_LOCKED_PASS": bool(q["quality_pass"]
                                        and e["efficiency_pass"])}
    io.open(os.path.join(out, "locked77_gate.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(verdict, indent=2,
                                           ensure_ascii=False) + "\n")

    print("cases %d · accepted now %d (legacy %d)"
          % (len(ids), len(acc_now), len(legacy_acc)))
    print("\n=== §13 hard quality ===")
    for k in ("accepted_recall", "paired_metrics_ok", "paired_visible_ok",
              "paired_side_ok", "post_context_regression",
              "accepted_budget_exhausted", "semantics_regression"):
        print("  %-30s %s" % (k, q[k]))
    print("  paired median %s -> %s (gate <= +%.2f)"
          % (q["paired_median_base"], q["paired_median_run"],
             GATES["paired_median_delta"]))
    print("  paired p95    %s -> %s (gate <= +%.2f)"
          % (q["paired_p95_base"], q["paired_p95_run"],
             GATES["paired_p95_delta"]))
    print("  QUALITY_PASS =", q["quality_pass"])
    print("\n=== §13 hard efficiency ===")
    print("  %-34s %9.1f  <= %9.1f  %s"
          % ("CASE_WALL_TIME_S total", e["wall_total_s"], e["wall_gate_s"],
             "PASS" if e["wall_pass"] else "FAIL"))
    print("     baseline %.1f s -> %+.2f%%" % (e["wall_baseline_s"],
                                               e["wall_delta_pct"]))
    print("  %-34s %9.1f  <= %9.1f  %s"
          % ("rejected stage runtime", e["rejected_stage_s"],
             e["rejected_stage_gate_s"],
             "PASS" if e["rejected_stage_pass"] else "FAIL"))
    print("  %-34s %9.1f  <= %9.1f  %s"
          % ("accepted median stage", e["accepted_median_stage_s"],
             e["accepted_median_gate_s"],
             "PASS" if e["accepted_median_pass"] else "FAIL"))
    print("  %-34s %9.1f  <= %9.1f  %s"
          % ("failed context runtime", e["failed_context_s"],
             e["failed_context_gate_s"],
             "PASS" if e["failed_context_pass"] else "FAIL"))
    print("  EFFICIENCY_PASS =", e["efficiency_pass"])
    print("\n  (진단) score_callback count %d · rescue triggered %d · won %d"
          % (e["score_callback_count_diagnostic"], e["rescue_triggered"],
             e["rescue_won"]))
    print("\nG1P7_LOCKED_PASS =", verdict["G1P7_LOCKED_PASS"])
    return 0 if verdict["G1P7_LOCKED_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
