"""mechanism config sweep 분석 + 설정 선택 (읽기 전용, bpy-free).

같은 subset 을 여러 config 로 돌린 결과를 baseline(현재 채택 G1.5)과 대조한다.
선택 순서는 §6 그대로다.

    1. accepted protection recall 100%
    2. explicit quality 비열화 없음
    3. post-context regression 0
    4. total runtime 최소
    5. score_callback reject 최소
    6. total candidate eval 최소

    python scripts/data_prep/blender/audit_mechanism_sweep.py \
        --baseline data/pallet/runs/diagnostics/_replay_controlled_g1p5 \
        --sweep-root data/pallet/runs/diagnostics --prefix _sweep_ \
        --subset reports/v2_generator_fix_g1p6_g2c_g3/g1p6/mechanism_subset_ids.txt \
        --out reports/v2_generator_fix_g1p6_g2c_g3/g1p6
"""
import argparse
import csv
import glob
import io
import json
import os
import statistics as st

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def jsonl(path):
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize(records, label):
    accepted = [r for r in records if r.get("usable")]
    rejected = [r for r in records if not r.get("usable")]
    errors = sorted(float(e) for e in
                    (r.get("explicit_abs_error_lowres") for r in accepted)
                    if e is not None)
    return {
        "config": label,
        "cases": len(records),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "explicit_metrics_available": sum(
            1 for r in accepted if r.get("explicit_metrics_available") is True),
        "side_match": sum(1 for r in accepted
                          if r.get("occluder_side_match") is True),
        "explicit_visible_gt0": sum(
            1 for r in accepted
            if num(r.get("explicit_occluder_visible_pixels")) > 0),
        "semantics_pass": sum(1 for r in accepted
                              if r.get("mode_semantics_pass") is True),
        "context_visible_ge1": sum(1 for r in accepted
                                   if num(r.get("n_context_visible")) >= 1),
        "abs_error_median": st.median(errors) if errors else None,
        "abs_error_p95": (errors[min(len(errors) - 1, int(0.95 * len(errors)))]
                          if errors else None),
        "total_runtime_s": round(sum(num(r.get("runtime_s"))
                                     for r in records), 1),
        "accepted_runtime_median_s": (
            round(st.median([num(r.get("runtime_s")) for r in accepted]), 1)
            if accepted else None),
        "rejected_runtime_s": round(
            sum(num(r.get("runtime_s")) for r in rejected), 1),
        "score_callback_rejects": sum(
            int((r.get("explicit_reject_counts_by_reason") or {})
                .get("score_callback", 0)) for r in records),
        "candidate_budget_exhausted": sum(
            int((r.get("explicit_reject_counts_by_reason") or {})
                .get("candidate_budget_exhausted", 0)) for r in records),
        "total_candidate_evals": sum(
            int(num(r.get("coarse_eval_count"))
                + num(r.get("refine_feedback_eval_count"))) for r in records),
        "fine_triggered": sum(1 for r in records if r.get("fine_triggered")),
        "fine_won": sum(1 for r in records if r.get("fine_won")),
        "fine_eval_count": sum(int(num(r.get("fine_eval_count")))
                               for r in records),
        "fine_runtime_s": round(sum(num(r.get("fine_runtime_s"))
                                    for r in records), 1),
        "target_seed_free_used": sum(int(num(r.get("target_seed_free_used")))
                                     for r in records),
        "target_seed_paid_used": sum(int(num(r.get("target_seed_paid_used")))
                                     for r in records),
        "explicit_stage_runtime_s": round(sum(
            num((r.get("stage_runtime_s") or {}).get("explicit"))
            for r in records), 1),
        "_accepted_ids": sorted(int(r["proposal_index"]) for r in accepted),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--sweep-root", required=True)
    ap.add_argument("--prefix", default="_sweep_")
    ap.add_argument("--subset", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    subset = {int(x) for x in io.open(_abs(args.subset), encoding="utf-8")
              .read().strip().split(",") if x.strip()}
    base = [r for r in jsonl(os.path.join(_abs(args.baseline),
                                          "replay_records.jsonl"))
            if int(r["proposal_index"]) in subset]
    rows = [summarize(base, "baseline_g1p5")]
    protected = set(rows[0]["_accepted_ids"])

    for path in sorted(glob.glob(os.path.join(_abs(args.sweep_root),
                                              args.prefix + "*"))):
        records_path = os.path.join(path, "replay_records.jsonl")
        if os.path.isfile(records_path):
            rows.append(summarize(jsonl(records_path),
                                  os.path.basename(path)[len(args.prefix):]))

    baseline = rows[0]
    for row in rows:
        accepted_ids = set(row.pop("_accepted_ids"))
        row["protection_kept"] = len(protected & accepted_ids)
        row["protection_of"] = len(protected)
        row["protection_recall_pass"] = bool(protected <= accepted_ids)
        row["recovered_cases"] = len(accepted_ids - protected)
        row["lost_cases"] = sorted(protected - accepted_ids)
        row["quality_pass"] = bool(
            row["explicit_metrics_available"] == row["accepted"]
            and row["side_match"] == row["accepted"]
            and row["explicit_visible_gt0"] == row["accepted"]
            and (row["abs_error_median"] is None
                 or baseline["abs_error_median"] is None
                 or row["abs_error_median"] <= baseline["abs_error_median"] + 0.01)
            and (row["abs_error_p95"] is None
                 or baseline["abs_error_p95"] is None
                 or row["abs_error_p95"] <= baseline["abs_error_p95"] + 0.02))
        row["post_context_pass"] = bool(
            row["semantics_pass"] == row["accepted"]
            and row["context_visible_ge1"] == row["accepted"])

    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)
    fields = list(rows[0])
    with io.open(os.path.join(out, "config_sweep.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False)
                                 if isinstance(v, list) else v)
                             for k, v in row.items()})

    candidates = [r for r in rows if r["config"] != "baseline_g1p5"]
    eligible = [r for r in candidates
                if r["protection_recall_pass"] and r["quality_pass"]
                and r["post_context_pass"]]
    eligible.sort(key=lambda r: (r["total_runtime_s"],
                                 r["score_callback_rejects"],
                                 r["total_candidate_evals"], r["config"]))
    selected = eligible[0] if eligible else None

    params = None
    if selected is not None:
        cap, thr = selected["config"].split("_")
        params = {"target_seed_free_cap": int(cap[1:]),
                  "near_miss_gap_threshold_label": thr,
                  "near_miss_gap_threshold": 0.0607 if thr == "p25" else 0.1114}
        io.open(os.path.join(out, "selected_config.json"), "w",
                encoding="utf-8", newline="\n").write(json.dumps(
                    {"config": selected["config"], **params,
                     "metrics": {k: v for k, v in selected.items()
                                 if not isinstance(v, list)}},
                    indent=2, ensure_ascii=False) + "\n")
    io.open(os.path.join(out, "config_sweep.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(
                {"eligible": [r["config"] for r in eligible],
                 "selected": None if selected is None else selected["config"],
                 "selected_params": params, "rows": rows},
                indent=2, ensure_ascii=False) + "\n")

    header = ("config        acc  prot   qual  ctx   runtime  rej_rt  sc_rej "
              "evals budget fine(t/w) ts_free/paid")
    lines = ["# §6 mechanism config sweep", "",
             f"subset {len(subset)}건 · config {len(candidates)}개 · "
             "baseline = 현재 채택 G1.5", "", "```", header, "-" * len(header)]
    for row in rows:
        lines.append(
            "%-13s %3d  %d/%-4d %-5s %-5s %8.1f %7.1f %6d %5d %6d %3d/%-3d %5d/%d"
            % (row["config"], row["accepted"], row["protection_kept"],
               row["protection_of"], "OK" if row["quality_pass"] else "FAIL",
               "OK" if row["post_context_pass"] else "FAIL",
               row["total_runtime_s"], row["rejected_runtime_s"],
               row["score_callback_rejects"], row["total_candidate_evals"],
               row["candidate_budget_exhausted"], row["fine_triggered"],
               row["fine_won"], row["target_seed_free_used"],
               row["target_seed_paid_used"]))
    lines += ["```", "", "accepted 의 abs_error (저해상도):", "```"]
    for row in rows:
        lines.append("%-13s median %-9s p95 %-9s  lost %s"
                     % (row["config"],
                        "-" if row["abs_error_median"] is None
                        else "%.4f" % row["abs_error_median"],
                        "-" if row["abs_error_p95"] is None
                        else "%.4f" % row["abs_error_p95"],
                        row["lost_cases"] or "없음"))
    lines += ["```", "", "## 선택 결과", ""]
    if selected is None:
        lines += ["**적격 config 없음** — §6 에 따라 locked 77 replay 를 실행하지 "
                  "않고 중단한다.", ""]
    else:
        lines += [f"적격 {len(eligible)}개 중 **`{selected['config']}`** 선택 "
                  f"(K={params['target_seed_free_cap']}, "
                  f"threshold={params['near_miss_gap_threshold']})", "",
                  "선택 순서: protection recall -> explicit quality -> "
                  "post-context -> total runtime -> score_callback -> eval 수", ""]
    io.open(os.path.join(out, "config_sweep.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(lines) + "\n")

    print("\n".join(lines[4:]))
    return 0 if selected is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
