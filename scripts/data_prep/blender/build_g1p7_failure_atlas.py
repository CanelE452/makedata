"""§24.1/§24.2 OFFLINE_CLOSURE — failure atlas + rescue upper-bound (읽기 전용, bpy-free).

hard gate 실패 후 solver 를 더 고치지 않고, 지금까지의 결과만으로 "무엇이 왜 막혔는지"를
남긴다.  새 heuristic 을 구현하지 않는다.
"""
import argparse
import collections
import csv
import io
import json
import os
import shutil
import statistics as st
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
NEEDED_TOTAL_S = 475.4
NEEDED_EXTRA_S = 211.5
STRICT_CEILING_S = 263.8


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def load(path):
    return {int(json.loads(l)["proposal_index"]): json.loads(l)
            for l in io.open(path, encoding="utf-8") if l.strip()}


def write_csv(path, rows, fields):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding-cases", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--mech", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    atlas = os.path.join(out, "failure_atlas")
    shots = os.path.join(atlas, "case_overlays")
    os.makedirs(shots, exist_ok=True)

    cases = {int(r["case_id"]): r for r in csv.DictReader(
        io.open(_abs(a.binding_cases), encoding="utf-8"))}
    base = load(os.path.join(_abs(a.baseline), "replay_records.jsonl"))
    mech = {}
    for spec in a.mech:
        name, path = spec.split("=", 1)
        p = os.path.join(_abs(path), "replay_records.jsonl")
        if os.path.exists(p):
            mech[name] = load(p)

    rows = []
    for cid, c in sorted(cases.items()):
        if c["outcome"] != "rejected":
            continue
        r = base[cid]
        log = r.get("explicit_candidate_log") or []
        achieved = collections.Counter(
            x.get("occluder_side_actual") for x in log
            if x.get("occluder_side_actual"))
        best = None
        for x in log:
            if x.get("abs_error") is None:
                continue
            v = {"side": bool(x.get("occluder_side_match")),
                 "vis": (x.get("object_visible_pixels") or 0) - 8,
                 "target": 0.12 - float(x["abs_error"]),
                 "G1": (x.get("candidate_V_vis") or 0) - 4,
                 "G2": min((x.get("candidate_ext_occ_corners") or 0) - 1,
                           4 - (x.get("candidate_ext_occ_corners") or 0))}
            n_pass = (int(v["side"]) + int(v["vis"] >= 0) + int(v["target"] >= 0)
                      + int(v["G1"] >= 0) + int(v["G2"] >= 0))
            if best is None or n_pass > best[0]:
                best = (n_pass, v)
        row = {
            "case_id": cid,
            "baseline_wall_s": c["case_wall_time_s"],
            "primary_binding_signature": c["primary_binding_signature"],
            "all_actionable_signatures": c["all_actionable_signatures"],
            "target_side": r.get("occluder_side_target"),
            "achieved_sides": json.dumps(dict(achieved), ensure_ascii=False),
            "target_side_ever_achieved": bool(
                r.get("occluder_side_target") in achieved),
            "best_pass_count": (best[0] if best else None),
            "best_constraint_vector": (json.dumps(best[1], ensure_ascii=False)
                                       if best else None),
            "failure_reason": r.get("reject_reason") or "explicit_search_failed",
            "projected_size": c["projected_size"], "f_target": c["f_target"],
            "unique_candidates": c["unique_candidates"],
            "budget_exhausted": c["candidate_budget_exhausted"],
        }
        for name, recs in mech.items():
            m = recs.get(cid)
            row["%s_wall_s" % name] = (m or {}).get("replay_wall_s")
            row["%s_rescue_triggered" % name] = (m or {}).get("rescue_triggered")
            row["%s_rescue_evals" % name] = (m or {}).get("rescue_eval_count")
            row["%s_rescue_won" % name] = (m or {}).get("rescue_won")
            row["%s_accepted" % name] = (m or {}).get("usable")
            if m is not None and row["baseline_wall_s"]:
                row["%s_delta_s" % name] = round(
                    float(m["replay_wall_s"]) - float(row["baseline_wall_s"]), 1)
        rows.append(row)

    fields = list(rows[0]) if rows else ["case_id"]
    sig = lambda r, n: n in r["all_actionable_signatures"].split("|")  # noqa: E731
    groups = {
        "side_cases.csv": [r for r in rows if sig(r, "ONE_MISS_SIDE")],
        "g1_cases.csv": [r for r in rows if sig(r, "ONE_MISS_G1")],
        "side_g1_overlap_cases.csv": [r for r in rows
                                      if sig(r, "ONE_MISS_SIDE")
                                      and sig(r, "ONE_MISS_G1")],
        "downstream_g3_g5_cases.csv": [
            r for r in rows if r["primary_binding_signature"] == "ACCEPTED"],
        "no_feasible_cases.csv": [
            r for r in rows
            if r["primary_binding_signature"] == "MULTI_CONSTRAINT"],
    }
    write_csv(os.path.join(atlas, "all_rejected_cases.csv"), rows, fields)
    for name, g in groups.items():
        write_csv(os.path.join(atlas, name), g, fields)

    # 대표 RGB 복사 (렌더 없이 기존 산출물에서만)
    copied = 0
    for r in sorted(rows, key=lambda x: -float(x["baseline_wall_s"]))[:12]:
        slot = base[int(r["case_id"])].get("usable_slot")
        for root in [_abs(a.baseline)] + [_abs(s.split("=", 1)[1])
                                          for s in a.mech]:
            src = os.path.join(root, "rgb", "f%04d_rgb.png" % int(slot or 0))
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(
                    shots, "case%04d_slot%04d.png" % (int(r["case_id"]),
                                                      int(slot or 0))))
                copied += 1
                break

    side_rows = groups["side_cases.csv"]
    never = [r for r in side_rows if not r["target_side_ever_achieved"]]
    io.open(os.path.join(atlas, "README.md"), "w", encoding="utf-8",
            newline="\n").write("""# G1.7 failure atlas

locked77 의 rejected %d건을 binding category 별로 정리한다.  렌더는 하지 않았고
기존 산출물만 사용했다 (대표 RGB %d장 복사).

```
파일                              건수   설명
────────────────────────────────────────────────────────────────────────
side_cases.csv                    %3d    ONE_MISS_SIDE 를 actionable 로 가진 case
g1_cases.csv                      %3d    ONE_MISS_G1 를 가진 case
side_g1_overlap_cases.csv         %3d    둘 다 가진 case (wall 중복 합산 금지)
downstream_g3_g5_cases.csv        %3d    explicit 은 성공, frame gate 에서 탈락
no_feasible_cases.csv             %3d    최선 후보가 3개 이상 위반
all_rejected_cases.csv            %3d    전체
```

## SIDE 가 왜 국소 rescue 로 안 되는가

`_occlusion_side_from_masks` (`v2_realize.py:3516`) 는 **가려진 픽셀 centroid** 의 화면
위치로 side 를 정하고 **bottom 을 가장 먼저** 검사한다.  occluder 는 support 제약 때문에
접지 상태를 유지해야 하므로 화면에서 세로로 자유롭게 못 움직인다.

SIDE actionable %d건 중 target side 를 **한 번도 달성하지 못한** case: **%d건**.

```
case   target   달성한 side 분포
──────────────────────────────────────────────────
%s
```
""" % (len(rows), copied, len(side_rows), len(groups["g1_cases.csv"]),
       len(groups["side_g1_overlap_cases.csv"]),
       len(groups["downstream_g3_g5_cases.csv"]),
       len(groups["no_feasible_cases.csv"]), len(rows),
       len(side_rows), len(never),
       "\n".join("%-6d %-8s %s" % (r["case_id"], r["target_side"],
                                   r["achieved_sides"]) for r in side_rows)))

    # ---- §24.2 upper bound ---------------------------------------------
    lines = []
    for name, recs in mech.items():
        present = [cid for cid in cases if cid in recs]
        wb = sum(float(cases[c]["case_wall_time_s"]) for c in present)
        wr = sum(float(recs[c]["replay_wall_s"]) for c in present)
        act = [c for c in present
               if {"ONE_MISS_SIDE", "ONE_MISS_G1"}
               & set(cases[c]["all_actionable_signatures"].split("|"))]
        ab = sum(float(cases[c]["case_wall_time_s"]) for c in act)
        ar = sum(float(recs[c]["replay_wall_s"]) for c in act)
        lines.append("%-12s subset %6.1f -> %6.1f (%+.1f) · actionable %6.1f -> "
                     "%6.1f (%+.1f) · trig %d won %d"
                     % (name, wb, wr, wb - wr, ab, ar, ab - ar,
                        sum(1 for c in present if recs[c].get("rescue_triggered")),
                        sum(1 for c in present if recs[c].get("rescue_won"))))
    io.open(os.path.join(out, "rescue_upper_bound.md"), "w", encoding="utf-8",
            newline="\n").write("""# G1.7 §24.2 rescue upper-bound

## 필요량

```
G1.6 CASE_WALL_TIME_S            4,754.4 s
§13 gate                        <= 4,279.0 s
필요 절감                          %.1f s
엄격 near-miss 절감 상한            %.1f s   (G1.7-A)
SIDE/G1 이 추가로 벌어야 하는 양     %.1f s
```

## category 별 절감 상한 (G1.7-A, 낙관적 가정)

```
가정                                   대상      절감상한
────────────────────────────────────────────────────────
엄격 near-miss (연속 margin 이 작음)    9 case    263.8 s
문헌적 4/5 (side 포함)                 26 case    870.0 s
절대 상한 (acceptance 도달이면 구제)    43 case  1,474.8 s
```

## SIDE/G1 실제 절감 (mechanism subset 실측)

```
%s
```

## remaining gap 과 판정

실측은 절감이 아니라 **증가**다.  rescue 는 기존 search 가 실패한 뒤에 추가로 도는
단계라, 성공하지 못하면 그 비용이 그대로 순증한다.  성공해도 이득은 "남은 proposal 을
건너뛴 만큼"으로 제한되는데, 실측 성공률이 낮아 기대값이 음수가 된다.

**local rescue 로 §13 primary gate 에 도달할 수 없다** — 근거:

1. 엄격 near-miss 상한(263.8 s)이 필요량(475.4 s)에 이미 못 미친다.
2. 부족분을 메우려면 SIDE 를 구제해야 하는데, SIDE 는 연속 margin 이 없고
   판정기가 bottom 을 먼저 검사한다.  occluder 는 접지 제약으로 화면에서 세로
   이동이 자유롭지 않아, 국소 offset 으로 side 범주를 바꾸기 어렵다.
3. mechanism subset 실측에서 rescue 는 wall 을 늘렸다.

따라서 다음 축은 "실패한 후보를 더 잘 고치는 것"이 아니라
**"그 후보를 애초에 만들지 않는 것"** 이다 (next_design_options.md).
""" % (NEEDED_TOTAL_S, STRICT_CEILING_S, NEEDED_EXTRA_S,
       "\n".join(lines) or "(mechanism run 없음)"))

    print("failure atlas -> %s" % os.path.relpath(atlas, PROJECT_ROOT))
    for name, g in groups.items():
        print("  %-32s %3d" % (name, len(g)))
    print("  대표 RGB 복사 %d장" % copied)
    print("SIDE actionable %d건 중 target side 미달성 %d건"
          % (len(side_rows), len(never)))
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
