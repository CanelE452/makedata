"""§12 G1.7 mechanism Config A/B 비교 + §4 wall-time micro-gate (읽기 전용).

saving_s = baseline_case_wall_s - rescue_case_wall_s   (§4 정의 그대로)

금지사항을 코드로 강제한다:
  - stage runtime 차이를 wall-time 절감으로 대체하지 않는다 (별도 열로만 보고)
  - score_callback count 를 시간처럼 쓰지 않는다 (진단 열)
  - 같은 case 를 category 별로 중복 합산하지 않는다 (case 단위 union)
  - rescue 자체 runtime 을 제외하지 않는다 (wall 에 이미 포함)
"""
import argparse
import csv
import io
import json
import os
import statistics as st
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
NEEDED_TOTAL_S = 475.4          # 4,754.4 -> 4,279.0
STRICT_CEILING_S = 263.8        # G1.7-A 엄격 near-miss 상한
NEEDED_EXTRA_S = 211.5          # §4 SIDE/G1 이 추가로 벌어야 하는 양


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def load(path):
    return {int(json.loads(l)["proposal_index"]): json.loads(l)
            for l in io.open(path, encoding="utf-8") if l.strip()}


def quality(base, run, ids):
    """§12 1-3: accepted recall · paired 품질 · post-context regression."""
    legacy = [i for i in ids if base[i].get("usable")]
    kept = [i for i in legacy if run.get(i, {}).get("usable")]
    pairs = []
    for i in legacy:
        if i not in run or not run[i].get("usable"):
            continue
        b, r = base[i], run[i]
        if b.get("explicit_abs_error_lowres") is None:
            continue
        if r.get("explicit_abs_error_lowres") is None:
            continue
        pairs.append((float(b["explicit_abs_error_lowres"]),
                      float(r["explicit_abs_error_lowres"])))
    metrics_ok = sum(1 for i in kept
                     if run[i].get("explicit_metrics_available"))
    visible_ok = sum(1 for i in kept
                     if (run[i].get("explicit_occluder_visible_pixels") or 0) >= 8)
    side_ok = sum(1 for i in kept if run[i].get("occluder_side_match"))
    ctx_reg = sum(1 for i in legacy
                  if i in run
                  and (run[i].get("n_context_visible") or 0)
                  < (base[i].get("n_context_visible") or 0))
    return {
        "protected_accepted": len(legacy), "recall": len(kept),
        "recall_ok": len(kept) == len(legacy),
        "paired": len(pairs),
        "median_base": st.median([p[0] for p in pairs]) if pairs else None,
        "median_run": st.median([p[1] for p in pairs]) if pairs else None,
        "p95_base": (sorted(p[0] for p in pairs)[
            min(len(pairs) - 1, int(0.95 * len(pairs)))] if pairs else None),
        "p95_run": (sorted(p[1] for p in pairs)[
            min(len(pairs) - 1, int(0.95 * len(pairs)))] if pairs else None),
        "metrics_ok": metrics_ok, "visible_ok": visible_ok, "side_ok": side_ok,
        "quality_ok": (metrics_ok == len(kept) and visible_ok == len(kept)
                       and side_ok == len(kept)),
        "post_context_regression": ctx_reg,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--config", action="append", required=True,
                    metavar="NAME=PATH")
    ap.add_argument("--actionable-wall-locked77", type=float, default=1385.2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    os.makedirs(out, exist_ok=True)

    base = load(os.path.join(_abs(a.baseline), "replay_records.jsonl"))
    subset = list(csv.DictReader(io.open(_abs(a.subset), encoding="utf-8")))
    ids = [int(r["case_id"]) for r in subset]
    # SIDE/G1 actionable 은 case 단위 union — category 별 중복 합산 금지
    act = [int(r["case_id"]) for r in subset
           if {"ONE_MISS_SIDE", "ONE_MISS_G1"}
           & set(r["all_actionable_signatures"].split("|"))]
    act_wall_base = sum(float(base[i]["replay_wall_s"]) for i in act)

    results = []
    for spec in a.config:
        name, path = spec.split("=", 1)
        run = load(os.path.join(_abs(path), "replay_records.jsonl"))
        present = [i for i in ids if i in run]
        wall_base = sum(float(base[i]["replay_wall_s"]) for i in present)
        wall_run = sum(float(run[i]["replay_wall_s"]) for i in present)
        act_present = [i for i in act if i in run]
        act_run = sum(float(run[i]["replay_wall_s"]) for i in act_present)
        act_b = sum(float(base[i]["replay_wall_s"]) for i in act_present)
        q = quality(base, run, present)
        triggered = [i for i in present if run[i].get("rescue_triggered")]
        won = [i for i in triggered if run[i].get("rescue_won")]
        newly = [i for i in present
                 if run[i].get("usable") and not base[i].get("usable")]
        results.append({
            "config": name, "path": path, "cases": len(present),
            "wall_baseline_s": round(wall_base, 1),
            "wall_run_s": round(wall_run, 1),
            "saving_s": round(wall_base - wall_run, 1),
            "actionable_cases": len(act_present),
            "actionable_wall_baseline_s": round(act_b, 1),
            "actionable_wall_run_s": round(act_run, 1),
            "actionable_saving_s": round(act_b - act_run, 1),
            "rescue_triggered": len(triggered), "rescue_won": len(won),
            "rescue_eval_total": sum(int(run[i].get("rescue_eval_count") or 0)
                                     for i in present),
            "rescue_runtime_s": round(sum(float(run[i].get("rescue_runtime_s")
                                                or 0) for i in present), 1),
            "rescue_duplicate_skips": sum(
                int(run[i].get("rescue_duplicate_skips") or 0) for i in present),
            "newly_accepted": len(newly), "newly_accepted_ids": newly,
            # 진단 전용 — PASS/FAIL 에 쓰지 않는다
            "stage_runtime_baseline_s": round(sum(
                float(base[i].get("runtime_s") or 0) for i in present), 1),
            "stage_runtime_run_s": round(sum(
                float(run[i].get("runtime_s") or 0) for i in present), 1),
            "score_callback_count": sum(
                int((run[i].get("explicit_reject_counts_by_reason") or {})
                    .get("score_callback", 0)) for i in present),
            "lowres_render_rejected": sum(
                int(run[i].get("lowres_render_count") or 0)
                for i in present if not run[i].get("usable")),
            **{"q_" + k: v for k, v in q.items()},
        })

    # ---- §4 micro-gate --------------------------------------------------
    coverage = act_wall_base / a.actionable_wall_locked77
    for r in results:
        s = r["actionable_saving_s"]
        r["coverage_fraction"] = round(coverage, 4)
        r["bound_conservative_s"] = round(s, 1)           # 미커버는 0 절감 가정
        r["bound_proportional_s"] = round(s / coverage, 1) if coverage else 0.0
        r["bound_half_haircut_s"] = round(0.5 * s / coverage, 1) if coverage else 0.0
        r["micro_gate_pass"] = bool(
            r["bound_conservative_s"] >= NEEDED_EXTRA_S
            or r["bound_half_haircut_s"] >= NEEDED_EXTRA_S)
        r["gate123_pass"] = bool(r["q_recall_ok"] and r["q_quality_ok"]
                                 and r["q_post_context_regression"] == 0)

    with io.open(os.path.join(out, "mechanism_compare.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        for r in results:
            w.writerow({k: (json.dumps(v, ensure_ascii=False)
                            if isinstance(v, list) else v)
                        for k, v in r.items()})

    eligible = [r for r in results if r["gate123_pass"] and r["micro_gate_pass"]]
    chosen = None
    if eligible:
        chosen = min(eligible, key=lambda r: (
            r["wall_run_s"], r["lowres_render_rejected"], r["rescue_eval_total"],
            r["config"]))
    verdict = {
        "needed_total_reduction_s": NEEDED_TOTAL_S,
        "strict_ceiling_s": STRICT_CEILING_S,
        "needed_extra_from_side_g1_s": NEEDED_EXTRA_S,
        "subset_actionable_wall_baseline_s": round(act_wall_base, 1),
        "locked77_actionable_wall_s": a.actionable_wall_locked77,
        "coverage_fraction": round(coverage, 4),
        "configs": results,
        "chosen": chosen["config"] if chosen else None,
        "MICRO_GATE_PASS": bool(chosen),
        "next": ("locked77 전체 replay 1회" if chosen else "OFFLINE_CLOSURE"),
    }
    io.open(os.path.join(out, "mechanism_gate.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(verdict, indent=2,
                                           ensure_ascii=False) + "\n")

    print("subset actionable wall(baseline) %.1f s = locked77 actionable 의 %.1f%%"
          % (act_wall_base, 100 * coverage))
    print()
    print("%-10s %6s %9s %9s %8s %8s %7s %7s %6s %6s"
          % ("config", "cases", "wall_base", "wall_run", "saving", "act_sav",
             "trig", "won", "new", "gate"))
    for r in results:
        print("%-10s %6d %9.1f %9.1f %8.1f %8.1f %7d %7d %6d %6s"
              % (r["config"], r["cases"], r["wall_baseline_s"], r["wall_run_s"],
                 r["saving_s"], r["actionable_saving_s"], r["rescue_triggered"],
                 r["rescue_won"], r["newly_accepted"],
                 "PASS" if (r["gate123_pass"] and r["micro_gate_pass"])
                 else "FAIL"))
    print()
    for r in results:
        print("[%s] recall %d/%d · quality_ok %s · ctx_reg %d · "
              "paired median %s->%s"
              % (r["config"], r["q_recall"], r["q_protected_accepted"],
                 r["q_quality_ok"], r["q_post_context_regression"],
                 (round(r["q_median_base"], 4) if r["q_median_base"] is not None
                  else None),
                 (round(r["q_median_run"], 4) if r["q_median_run"] is not None
                  else None)))
        print("    bounds: conservative %.1f s · half-haircut %.1f s · "
              "proportional %.1f s  (필요 %.1f s) -> micro_gate %s"
              % (r["bound_conservative_s"], r["bound_half_haircut_s"],
                 r["bound_proportional_s"], NEEDED_EXTRA_S,
                 "PASS" if r["micro_gate_pass"] else "FAIL"))
    print()
    print("MICRO_GATE_PASS =", verdict["MICRO_GATE_PASS"],
          "· chosen =", verdict["chosen"], "· next =", verdict["next"])
    return 0 if verdict["MICRO_GATE_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
