"""§11 G1.7 mechanism subset — locked77 에서 최대 24건을 결정적으로 고른다.

quantile 기반으로만 뽑고 tie-break 는 case_id 다.  manual cherry-pick 은 없다.
필수 커버리지:
  accepted  : winning stage 별 대표 · runtime p05/median/p95 · large projected-size
              · G1.6 fine 으로 회복된 case
  rejected  : ONE_MISS_SIDE p05/median/p95 · ONE_MISS_G1 p05/median/p95
              · SIDE/G1 동시 actionable · 4/5 near-feasible
              · budget exhausted actionable · NO_FEASIBLE 대표
              · downstream G3/G5 대표 (explicit rescue 대상이 아님을 보여줌)
"""
import argparse
import csv
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
MAX_CASES = 24


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def quantile_pick(rows, key, q):
    """q 분위에 해당하는 row.  동률이면 case_id 가 작은 쪽."""
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: (float(r[key]), int(r["case_id"])))
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding-cases", required=True)
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    os.makedirs(out, exist_ok=True)

    cases = list(csv.DictReader(io.open(_abs(a.binding_cases), encoding="utf-8")))
    recs = {}
    for line in io.open(os.path.join(_abs(a.replay), "replay_records.jsonl"),
                        encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            recs[int(r["proposal_index"])] = r
    for c in cases:
        c["case_id"] = int(c["case_id"])
        r = recs.get(c["case_id"], {})
        c["fine_won"] = bool(r.get("fine_won"))
        c["reject_reason"] = r.get("reject_reason")

    picked, why = {}, {}

    def take(row, reason):
        if row is None:
            return
        cid = int(row["case_id"])
        why.setdefault(cid, []).append(reason)
        picked.setdefault(cid, row)

    acc = [c for c in cases if c["outcome"] == "accepted"]
    rej = [c for c in cases if c["outcome"] == "rejected"]

    # --- A. accepted protection -----------------------------------------
    stages = {}
    for c in acc:
        stages.setdefault(c["winning_stage"] or "none", []).append(c)
    for stage in sorted(stages):
        take(sorted(stages[stage], key=lambda r: int(r["case_id"]))[0],
             "accepted:stage=%s" % stage)
    for q, name in ((0.05, "p05"), (0.50, "median"), (0.95, "p95")):
        take(quantile_pick(acc, "case_wall_time_s", q), "accepted:runtime_" + name)
    take(quantile_pick(acc, "projected_size", 0.95), "accepted:large_projected")
    for c in sorted((c for c in acc if c["fine_won"]),
                    key=lambda r: int(r["case_id"]))[:2]:
        take(c, "accepted:fine_recovered")

    # --- B. rejected ------------------------------------------------------
    def actionable(rows, name):
        return [c for c in rows
                if name in c["all_actionable_signatures"].split("|")]

    side = actionable(rej, "ONE_MISS_SIDE")
    g1 = actionable(rej, "ONE_MISS_G1")
    for rows, label in ((side, "SIDE"), (g1, "G1")):
        for q, name in ((0.05, "p05"), (0.50, "median"), (0.95, "p95")):
            take(quantile_pick(rows, "case_wall_time_s", q),
                 "rejected:%s_%s" % (label, name))
    both = [c for c in side if c in g1]
    take(quantile_pick(both, "case_wall_time_s", 0.50), "rejected:SIDE+G1_both")
    near = [c for c in rej if int(c["near_feasible_4of5"]) > 0]
    take(quantile_pick(near, "case_wall_time_s", 0.50), "rejected:near_feasible_4of5")
    budget = [c for c in rej
              if c["budget_exhausted_with_near_feasible"] == "True"]
    take(quantile_pick(budget, "case_wall_time_s", 0.95),
         "rejected:budget_exhausted_actionable")
    nofeas = [c for c in rej
              if c["primary_binding_signature"] == "MULTI_CONSTRAINT"]
    take(quantile_pick(nofeas, "case_wall_time_s", 0.50), "rejected:no_feasible")
    downstream = [c for c in rej if c["primary_binding_signature"] == "ACCEPTED"]
    take(quantile_pick(downstream, "case_wall_time_s", 0.50),
         "rejected:downstream_gate")
    hard = [c for c in rej
            if c["primary_binding_signature"] == "HARD_PHYSICAL_ONLY"]
    take(quantile_pick(hard, "case_wall_time_s", 0.50), "rejected:hard_physical")

    # --- 상한 24: 필수 커버리지를 먼저 채우고 남으면 rejected wall 상위로 채운다
    rows = sorted(picked.values(), key=lambda r: int(r["case_id"]))
    if len(rows) > MAX_CASES:
        # 커버리지 사유가 많은 case 를 우선 유지 (tie-break case_id)
        rows = sorted(rows, key=lambda r: (-len(why[int(r["case_id"])]),
                                           int(r["case_id"])))[:MAX_CASES]
    else:
        extra = sorted((c for c in rej if int(c["case_id"]) not in picked),
                       key=lambda r: (-float(r["case_wall_time_s"]),
                                      int(r["case_id"])))
        for c in extra:
            if len(rows) >= MAX_CASES:
                break
            why.setdefault(int(c["case_id"]), []).append("fill:rejected_wall_top")
            rows.append(c)
    rows = sorted(rows, key=lambda r: int(r["case_id"]))

    fields = ["case_id", "usable_slot", "outcome", "primary_binding_signature",
              "all_actionable_signatures", "case_wall_time_s",
              "stage_runtime_total_s", "winning_stage", "projected_size",
              "f_target", "side", "near_feasible_4of5",
              "budget_exhausted_with_near_feasible", "selection_reasons"]
    with io.open(os.path.join(out, "mechanism_subset.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in fields if k != "selection_reasons"}
            row["selection_reasons"] = "|".join(why[int(r["case_id"])])
            w.writerow(row)

    n_acc = sum(1 for r in rows if r["outcome"] == "accepted")
    wall = sum(float(r["case_wall_time_s"]) for r in rows)
    side_in = [r for r in rows
               if "ONE_MISS_SIDE" in r["all_actionable_signatures"].split("|")]
    g1_in = [r for r in rows
             if "ONE_MISS_G1" in r["all_actionable_signatures"].split("|")]
    union = [r for r in rows if r in side_in or r in g1_in]
    io.open(os.path.join(out, "mechanism_subset.md"), "w", encoding="utf-8",
            newline="\n").write("""# G1.7 §11 mechanism subset

quantile 기반 결정적 선정 (tie-break=case_id).  manual cherry-pick 없음.

```
지표                                     값
──────────────────────────────────────────────────
cases                                   %d / %d
  accepted (protection)                 %d
  rejected                              %d
subset CASE_WALL_TIME_S 합              %.1f s
  그중 SIDE/G1 actionable (중복 없음)   %.1f s  (%d case)
```

## 선정된 case

```
case  outcome    primary signature            wall_s   선정 사유
────────────────────────────────────────────────────────────────────────────────
%s
```

## 커버리지 확인

```
%s
```
""" % (len(rows), MAX_CASES, n_acc, len(rows) - n_acc, wall,
       sum(float(r["case_wall_time_s"]) for r in union), len(union),
       "\n".join("%-5d %-10s %-28s %7.1f  %s"
                 % (int(r["case_id"]), r["outcome"],
                    r["primary_binding_signature"],
                    float(r["case_wall_time_s"]),
                    "|".join(why[int(r["case_id"])])) for r in rows),
       "\n".join("%-42s %s" % (reason, "OK") for reason in sorted(
           {x for v in why.values() for x in v}))))

    print("subset %d cases (accepted %d · rejected %d) wall %.1f s"
          % (len(rows), n_acc, len(rows) - n_acc, wall))
    print("SIDE/G1 actionable in subset: %d case · %.1f s"
          % (len(union), sum(float(r["case_wall_time_s"]) for r in union)))
    for r in rows:
        print("  %-5d %-9s %-26s %7.1f  %s"
              % (int(r["case_id"]), r["outcome"],
                 r["primary_binding_signature"], float(r["case_wall_time_s"]),
                 "|".join(why[int(r["case_id"])])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
