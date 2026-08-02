"""ext_occ=0 조기 종료 가능성 offline 진단 (렌더 0회, bpy-free, 읽기 전용).

G2 는 `1 <= ext_occ <= 4` 다.  실패의 대부분이 `ext_occ=0`(전혀 안 가림)이라
"어떤 stage 까지 계속 0 이면 그 proposal 을 포기해도 되는가"를 묻는다.

**이 도구는 자료만 만든다.**  generator 코드나 feature flag 를 바꾸지 않는다.
false negative(조기 종료했으면 잃었을 accepted)가 1건이라도 있으면 그 stage 는
안전하지 않다.
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
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def load_records(path):
    return [json.loads(l) for l in io.open(_abs(path), encoding="utf-8")
            if l.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", action="append", required=True,
                    metavar="NAME=PATH")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    os.makedirs(out, exist_ok=True)

    # proposal 단위로 stage 순서를 복원한다.  후보 로그는 평가 순서대로 쌓인다.
    per_proposal, sources = [], {}
    for spec in a.records:
        name, path = spec.split("=", 1)
        recs = load_records(path)
        sources[name] = {"path": path, "records": len(recs),
                         "with_candidate_log": 0}
        for rec in recs:
            log = rec.get("explicit_candidate_log") or []
            if not log:
                continue
            sources[name]["with_candidate_log"] += 1
            accepted_case = bool(rec.get("usable"))
            selected_stage = rec.get("explicit_selected_stage")
            by_prop = collections.defaultdict(list)
            for order, c in enumerate(log):
                by_prop[c.get("proposal_index")].append((order, c))
            for pidx, items in sorted(by_prop.items(),
                                      key=lambda kv: (kv[0] is None, kv[0])):
                stages, seen_stage_order = [], []
                any_accept = False
                first_nonzero_at = None
                for i, (order, c) in enumerate(items):
                    ext = c.get("candidate_ext_occ_corners")
                    stage = c.get("stage")
                    if stage not in seen_stage_order:
                        seen_stage_order.append(stage)
                    stages.append({"i": i, "stage": stage, "ext": ext,
                                   "accept": bool(c.get("score_accept"))})
                    if c.get("score_accept"):
                        any_accept = True
                    if ext is not None and int(ext) > 0 and first_nonzero_at is None:
                        first_nonzero_at = i
                measured = [s for s in stages if s["ext"] is not None]
                per_proposal.append({
                    "source": name,
                    "case_id": rec.get("proposal_index"),
                    "usable_id": rec.get("usable_id", rec.get("usable_slot")),
                    "proposal_index": pidx,
                    "case_accepted": accepted_case,
                    "case_selected_stage": selected_stage,
                    "proposal_had_accept": any_accept,
                    "candidates": len(stages),
                    "measured_candidates": len(measured),
                    "stage_sequence": "|".join(seen_stage_order),
                    "first_nonzero_ext_index": first_nonzero_at,
                    "first_nonzero_ext_stage": (
                        stages[first_nonzero_at]["stage"]
                        if first_nonzero_at is not None else None),
                    "all_ext_zero": bool(measured) and all(
                        int(s["ext"]) == 0 for s in measured),
                    "_stages": stages,
                })

    # ---- stage 별: "이 stage 까지 전부 ext=0" 이면 포기했을 때의 손익 ----
    stage_order = []
    for p in per_proposal:
        for s in p["stage_sequence"].split("|"):
            if s and s not in stage_order:
                stage_order.append(s)

    rows = []
    for cutoff in stage_order:
        false_neg, true_stop, saved_candidates = 0, 0, 0
        for p in per_proposal:
            seq = p["stage_sequence"].split("|")
            if cutoff not in seq:
                continue
            upto = seq[:seq.index(cutoff) + 1]
            head = [s for s in p["_stages"]
                    if s["stage"] in upto and s["ext"] is not None]
            if not head:
                continue
            if not all(int(s["ext"]) == 0 for s in head):
                continue          # 규칙이 발동하지 않는 proposal
            # 규칙 발동: 여기서 이 proposal 을 포기한다
            tail = [s for s in p["_stages"] if s["stage"] not in upto]
            if p["proposal_had_accept"]:
                false_neg += 1     # 나중에 수락됐을 후보를 잃는다
            else:
                true_stop += 1
                saved_candidates += len(tail)
        rows.append({"cutoff_stage": cutoff,
                     "rule_fired_proposals": false_neg + true_stop,
                     "false_negatives": false_neg,
                     "safe_stops": true_stop,
                     "saved_candidate_evals": saved_candidates,
                     "safe": false_neg == 0})

    with io.open(os.path.join(out, "stage_summary.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    recovery = [p for p in per_proposal
                if p["proposal_had_accept"] and p["first_nonzero_ext_index"]]
    failed = [p for p in per_proposal
              if not p["proposal_had_accept"] and p["all_ext_zero"]]
    fields = [k for k in per_proposal[0] if k != "_stages"]
    for name, data in (("accepted_recovery_cases.csv", recovery),
                       ("failed_cases.csv", failed)):
        with io.open(os.path.join(out, name), "w", encoding="utf-8",
                     newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    safe = [r for r in rows if r["safe"] and r["rule_fired_proposals"] > 0]
    earliest = safe[0] if safe else None
    verdict = {
        "sources": sources,
        "proposals_analyzed": len(per_proposal),
        "proposals_all_ext_zero": sum(1 for p in per_proposal if p["all_ext_zero"]),
        "proposals_with_accept": sum(1 for p in per_proposal
                                     if p["proposal_had_accept"]),
        "recovered_after_zero_ext": len(recovery),
        "stage_rows": rows,
        "earliest_safe_stage": earliest["cutoff_stage"] if earliest else None,
        "EXT_OCC_EARLY_TERMINATION_READY": bool(earliest),
        "applied_to_pilot500": False,
        "note": "자료 전용 — 이번 500 pilot 에 적용하지 않는다 (feature flag 없음).",
    }
    io.open(os.path.join(out, "final_judgment.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(verdict, indent=2,
                                           ensure_ascii=False) + "\n")

    recov_stages = collections.Counter(
        p["first_nonzero_ext_stage"] for p in recovery)
    io.open(os.path.join(out, "estimated_upper_bound.md"), "w",
            encoding="utf-8", newline="\n").write("""# ext_occ=0 조기 종료 — offline 상한 추정

렌더 0회.  기존 record 의 candidate log 만 사용했다.

## 입력

```
%s
```

## 관측

```
분석한 proposal                       %6d
  전 후보가 ext_occ=0                 %6d
  수락 후보를 가진 proposal            %6d
  ext_occ=0 이후 ext>0 으로 회복       %6d   <- 조기 종료의 false negative 후보
```

회복이 처음 일어난 stage 분포:

```
%s
```

## stage 별 "여기까지 전부 ext=0 이면 포기" 규칙의 손익

```
cutoff stage             발동    false_neg   safe_stop   절약 후보평가   안전
────────────────────────────────────────────────────────────────────────────────
%s
```

## 판정

```
EXT_OCC_EARLY_TERMINATION_READY = %s
가장 이른 안전 stage             = %s
```

**이번 500 pilot 에는 적용하지 않는다.**  generator 코드도 feature flag 도 바꾸지
않았다.  이 문서는 다음 설계 논의를 위한 자료다.
""" % ("\n".join("%-12s %s (records %d · candidate log %d)"
                 % (k, v["path"], v["records"], v["with_candidate_log"])
                 for k, v in sources.items()),
       len(per_proposal), verdict["proposals_all_ext_zero"],
       verdict["proposals_with_accept"], len(recovery),
       "\n".join("  %-24s %d" % (k, v) for k, v in recov_stages.most_common())
       or "  (없음)",
       "\n".join("%-24s %6d %11d %11d %14d   %s"
                 % (r["cutoff_stage"], r["rule_fired_proposals"],
                    r["false_negatives"], r["safe_stops"],
                    r["saved_candidate_evals"], "예" if r["safe"] else "아니오")
                 for r in rows),
       verdict["EXT_OCC_EARLY_TERMINATION_READY"],
       verdict["earliest_safe_stage"]))

    print("proposals %d · all-ext-zero %d · with-accept %d · recovered %d"
          % (len(per_proposal), verdict["proposals_all_ext_zero"],
             verdict["proposals_with_accept"], len(recovery)))
    print()
    print("%-24s %6s %11s %11s %14s %6s"
          % ("cutoff stage", "발동", "false_neg", "safe_stop", "절약평가", "안전"))
    for r in rows:
        print("%-24s %6d %11d %11d %14d %6s"
              % (r["cutoff_stage"], r["rule_fired_proposals"],
                 r["false_negatives"], r["safe_stops"],
                 r["saved_candidate_evals"], "예" if r["safe"] else "아니오"))
    print()
    print("EXT_OCC_EARLY_TERMINATION_READY =",
          verdict["EXT_OCC_EARLY_TERMINATION_READY"],
          "· earliest safe stage =", verdict["earliest_safe_stage"])
    print("→ 이번 500 pilot 에 적용하지 않음 (자료 전용)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
