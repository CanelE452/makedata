"""locked 77 에서 mechanism sweep 용 결정적 subset 을 고른다 (읽기 전용, bpy-free).

모든 설정을 77건 전체로 반복하지 않기 위한 축소 표본이다.  손으로 고르지 않는다 —
아래 규칙(보호 사례 · 승리 stage 대표 · 실패 quantile 대표)에 해당하는 case 를
규칙 이름과 함께 뽑고, tie-break 는 case_id 로 한다.

    python scripts/data_prep/blender/build_mechanism_subset.py \
        --score-gap reports/v2_generator_fix_g1p6_g2c_g3/g1p6 \
        --protected 113,166 --max-cases 24 \
        --out reports/v2_generator_fix_g1p6_g2c_g3/g1p6
"""
import argparse
import csv
import io
import json
import os

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def fnum(value):
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def quantile_pick(rows, key, q):
    usable = [r for r in rows if fnum(r.get(key)) is not None]
    if not usable:
        return None
    usable.sort(key=lambda r: (fnum(r[key]), int(r["proposal_index"])))
    index = min(len(usable) - 1, max(0, int(round(q * (len(usable) - 1)))))
    return usable[index]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--score-gap", required=True, help="score_gap_cases.csv 가 있는 폴더")
    ap.add_argument("--protected", default="",
                    help="반드시 포함할 proposal_index (쉼표 구분)")
    ap.add_argument("--max-cases", type=int, default=24)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    src = os.path.join(_abs(args.score_gap), "score_gap_cases.csv")
    rows = [r for r in csv.DictReader(io.open(src, encoding="utf-8"))
            if r["source"] == "locked_replay"]
    accepted = [r for r in rows if r["current_outcome"] == "accepted"]
    rejected = [r for r in rows if r["current_outcome"] != "accepted"]

    picked, reasons = {}, {}

    def take(row, reason):
        if row is None:
            return
        key = int(row["proposal_index"])
        reasons.setdefault(key, []).append(reason)
        picked.setdefault(key, row)

    # --- A. accepted 보호 -------------------------------------------------
    protected = {int(x) for x in args.protected.split(",") if x.strip()}
    for row in rows:
        if int(row["proposal_index"]) in protected:
            take(row, "protected_previously_lost")
    # target-seed free eval 이 가장 큰 accepted (예산 상한의 영향을 가장 크게 받는다)
    take(quantile_pick(accepted, "target_seed_free_evals", 1.0),
         "accepted_max_target_seed_free")
    take(quantile_pick(accepted, "target_seed_free_evals", 0.75),
         "accepted_p75_target_seed_free")
    # 승리 stage 별 accepted 최소 1건 (stage 이름순 -> case_id 순)
    by_stage = {}
    for row in sorted(accepted, key=lambda r: (str(r["winning_stage"]),
                                               int(r["proposal_index"]))):
        by_stage.setdefault(str(row["winning_stage"]), row)
    for stage, row in sorted(by_stage.items()):
        take(row, "accepted_winning_stage:" + stage)

    # --- B. 실패 사례 ------------------------------------------------------
    for q in (0.05, 0.25, 0.50, 0.75):
        take(quantile_pick(rejected, "best_near_miss_gap", q),
             "reject_near_miss_gap_p%02d" % int(q * 100))
    budget = [r for r in rejected if int(r["candidate_budget_exhausted"] or 0) > 0]
    take(quantile_pick(budget, "candidate_budget_exhausted", 1.0),
         "reject_max_budget_exhausted")
    take(quantile_pick(budget, "candidate_budget_exhausted", 0.5),
         "reject_median_budget_exhausted")
    # near-miss 인데 fine 이 한 번도 안 돌았던 사례 (지금은 전부 그렇다)
    nm = [r for r in rejected
          if int(r["near_miss_candidates"] or 0) > 0
          and int(r["fine_eval_count"] or 0) == 0]
    for q in (0.25, 0.75):
        take(quantile_pick(nm, "near_miss_candidates", q),
             "reject_near_miss_no_fine_p%02d" % int(q * 100))
    for q, name in ((0.05, "low"), (0.50, "mid"), (0.95, "high")):
        take(quantile_pick(rejected, "projected_size", q),
             "reject_projected_size_" + name)
    # f_target 4분위 대표
    for q in (0.10, 0.40, 0.70, 0.95):
        take(quantile_pick(rejected, "f_target", q),
             "reject_f_target_p%02d" % int(q * 100))

    ordered = sorted(picked)
    if len(ordered) > args.max_cases:
        # 보호 사례를 먼저 남기고, 나머지는 case_id 순으로 자른다 (결정적).
        must = [k for k in ordered
                if any(r.startswith("protected") for r in reasons[k])]
        rest = [k for k in ordered if k not in must]
        ordered = sorted(must + rest[:max(0, args.max_cases - len(must))])

    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)
    subset = []
    for key in ordered:
        row = picked[key]
        subset.append({
            "proposal_index": key,
            "usable_slot": row["usable_slot"],
            "selection_reasons": "|".join(sorted(set(reasons[key]))),
            "current_outcome": row["current_outcome"],
            "old_outcome": row["old_outcome"],
            "winning_stage": row["winning_stage"],
            "target_seed_free_evals": row["target_seed_free_evals"],
            "candidate_budget_exhausted": row["candidate_budget_exhausted"],
            "near_miss_candidates": row["near_miss_candidates"],
            "best_near_miss_gap": row["best_near_miss_gap"],
            "score_callback_rejects": row["score_callback_rejects"],
            "projected_size": row["projected_size"],
            "f_target": row["f_target"],
            "side": row["side"],
            "runtime_s": row["runtime_s"],
        })
    with io.open(os.path.join(out, "mechanism_subset.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(subset[0]))
        writer.writeheader()
        writer.writerows(subset)

    acc_n = sum(1 for s in subset if s["current_outcome"] == "accepted")
    lines = [
        "# mechanism subset (결정적 선정, manual pick 없음)",
        "",
        f"locked 77 중 **{len(subset)}건** — accepted {acc_n} · rejected {len(subset) - acc_n}",
        f"상한 {args.max_cases}건 · tie-break 는 proposal_index",
        "",
        "## 선정 규칙별 case",
        "",
        "```",
    ]
    rule_map = {}
    for entry in subset:
        for reason in entry["selection_reasons"].split("|"):
            rule_map.setdefault(reason, []).append(entry["proposal_index"])
    for reason, ids in sorted(rule_map.items()):
        lines.append("%-42s %s" % (reason, ids))
    lines += ["```", "", "## case 목록", "",
              "```",
              "pi    outcome    winning stage           ts_free  budget_ex  nm  gap"]
    lines.append("─" * 78)
    for entry in subset:
        gap = fnum(entry["best_near_miss_gap"])
        lines.append("%-5s %-10s %-22s %7s %10s %3s  %s"
                     % (entry["proposal_index"], entry["current_outcome"],
                        str(entry["winning_stage"])[:22],
                        entry["target_seed_free_evals"],
                        entry["candidate_budget_exhausted"],
                        entry["near_miss_candidates"],
                        "-" if gap is None else "%.4f" % gap))
    lines += ["```", ""]
    io.open(os.path.join(out, "mechanism_subset.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(lines) + "\n")

    io.open(os.path.join(out, "mechanism_subset_ids.txt"), "w",
            encoding="utf-8", newline="\n").write(
        ",".join(str(s["proposal_index"]) for s in subset) + "\n")
    print("subset %d cases (accepted %d · rejected %d)"
          % (len(subset), acc_n, len(subset) - acc_n))
    print(",".join(str(s["proposal_index"]) for s in subset))
    for reason, ids in sorted(rule_map.items()):
        print("  %-42s %s" % (reason, ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
