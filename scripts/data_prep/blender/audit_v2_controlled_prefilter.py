"""controlled occluder prefilter 의 baseline recall 재현 (읽기 전용, bpy-free).

"사전 필터가 과거에 프레임을 살린 후보를 하나라도 버리지 않는가"를 실제 baseline 으로
검증한다.  임계를 건드릴 때마다 이 스크립트를 다시 돌려 recall 이 100% 인지 확인한다.

    python scripts/data_prep/blender/audit_v2_controlled_prefilter.py \
        --dir data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_public \
        --seed 7000 --out reports/v2_generator_fix_g1_g3/g1

절차
  1. baseline 의 accepted controlled record 에서 (proposal_index, 승리 오브젝트) 를 읽는다.
  2. 같은 seed 로 proposal stream 을 재생해 그 프레임의 Plan 을 복원한다.
  3. prefilter 를 끈 상태로 prepare_diagnostic_explicit_occluders 를 돌려 baseline 이
     실제로 봤던 6개 후보를 얻는다.
  4. 그중 승리 후보에 controlled_prefilter_reason 을 적용한다 — None 이어야 한다.
  5. 같은 프레임을 prefilter 켠 상태로도 돌려 후보 pool 축소량을 기록한다.
"""
import argparse
import csv
import io
import json
import os
import sys
from collections import Counter

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import run_v2_scene_logic as R      # noqa: E402
import scene_placement_v2 as SP2    # noqa: E402
import v2_pipeline as vp            # noqa: E402

EXPENSIVE = "usable_reject:rendered|usable_reject:realize_ok"


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def _jsonl(path):
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="baseline pilot dataset root")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--out", required=True, help="report output dir")
    args = ap.parse_args(argv)

    root, out = _abs(args.dir), _abs(args.out)
    os.makedirs(out, exist_ok=True)

    accepted, expensive = {}, {}
    for rec in _jsonl(os.path.join(root, "records.jsonl")):
        if rec.get("diagnostic_mode") == "controlled-occlusion":
            accepted[rec["proposal_index"]] = rec
    for rec in _jsonl(os.path.join(root, "records_rejected.jsonl")):
        if (rec.get("diagnostic_mode") == "controlled-occlusion"
                and rec.get("primary_reject_reason") == EXPENSIVE):
            expensive[rec["proposal_index"]] = rec.get("record") or {}
    want = set(accepted) | set(expensive)
    if not want:
        raise SystemExit(f"controlled frame 을 찾지 못했습니다: {root}")

    assets = vp.load_assets()
    plans = {}
    for proposal_index, plan, _reject in R.iter_proposals(
            args.seed, assets, vp, placement_mode="constrained",
            max_proposals=max(want) + 1):
        if proposal_index in want and plan is not None:
            plans[proposal_index] = plan

    rows = []
    for proposal_index in sorted(want):
        plan = plans.get(proposal_index)
        rec = accepted.get(proposal_index) or expensive.get(proposal_index)
        is_accepted = proposal_index in accepted
        if plan is None:
            rows.append({"proposal_index": proposal_index,
                         "frame_outcome": "accepted" if is_accepted else "expensive",
                         "status": "plan_missing"})
            continue
        baseline = vp.prepare_diagnostic_explicit_occluders(plan, assets,
                                                            prefilter=False)
        filtered = vp.prepare_diagnostic_explicit_occluders(plan, assets,
                                                            prefilter=True)
        if isinstance(baseline, vp.Reject):
            rows.append({"proposal_index": proposal_index,
                         "frame_outcome": "accepted" if is_accepted else "expensive",
                         "status": f"baseline_reject:{baseline.reason}"})
            continue
        cands = [baseline.occluder,
                 *(baseline.occluder.get("diagnostic_resample_proposals") or [])]
        winner_name = rec.get("explicit_selected_object")
        winner = next((c for c in cands if c.get("obj_name") == winner_name), None)
        winner_reason = None
        if winner is not None:
            winner_reason = SP2.controlled_prefilter_reason(
                winner, plan.pallet_silhouette_px2,
                screen_area_px2=vp.occluder_screen_silhouette_px2(
                    baseline.spec, winner),
            )
        removed = [c for c in cands
                   if SP2.controlled_prefilter_reason(
                       c, plan.pallet_silhouette_px2,
                       screen_area_px2=vp.occluder_screen_silhouette_px2(
                           baseline.spec, c)) is not None]
        occ = filtered.occluder if not isinstance(filtered, vp.Reject) else None
        rows.append({
            "proposal_index": proposal_index,
            "usable_slot": rec.get("usable_slot"),
            "frame_outcome": "accepted" if is_accepted else "expensive",
            "status": ("ok" if not isinstance(filtered, vp.Reject)
                       else f"filtered_reject:{filtered.reason}"),
            "winner_object": winner_name,
            "winner_in_baseline_proposals": winner is not None,
            "winner_prefilter_reason": winner_reason,
            "winner_kept": (winner is not None and winner_reason is None),
            "baseline_proposals": len(cands),
            "baseline_proposals_removed": len(removed),
            "candidates_before_prefilter": (occ or {}).get(
                "candidates_before_prefilter"),
            "candidates_after_prefilter": (occ or {}).get(
                "candidates_after_prefilter"),
            "prefilter_reject_count": (occ or {}).get("prefilter_reject_count"),
            "prefilter_reject_counts_by_reason": json.dumps(
                (occ or {}).get("prefilter_reject_counts_by_reason") or {},
                sort_keys=True),
        })

    fields = sorted({k for row in rows for k in row})
    fields = (["proposal_index", "usable_slot", "frame_outcome", "status"]
              + [f for f in fields
                 if f not in {"proposal_index", "usable_slot", "frame_outcome",
                              "status"}])
    with io.open(os.path.join(out, "prefilter_replay.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})

    acc_rows = [r for r in rows if r["frame_outcome"] == "accepted"]
    exp_rows = [r for r in rows if r["frame_outcome"] == "expensive"]
    kept = sum(1 for r in acc_rows if r.get("winner_kept"))
    reasons = Counter()
    for r in rows:
        for k, v in json.loads(r.get("prefilter_reject_counts_by_reason")
                               or "{}").items():
            reasons[k] += v
    exp_early = sum(1 for r in exp_rows
                    if str(r.get("status", "")).startswith("filtered_reject"))
    acc_early = sum(1 for r in acc_rows
                    if str(r.get("status", "")).startswith("filtered_reject"))
    before = sum(int(r.get("candidates_before_prefilter") or 0) for r in rows)
    after = sum(int(r.get("candidates_after_prefilter") or 0) for r in rows)

    md = [
        "# controlled prefilter — baseline recall replay",
        "",
        f"baseline `{os.path.relpath(root, PROJECT_ROOT)}` · seed {args.seed}",
        "",
        "```",
        f"accepted frame                {len(acc_rows)}",
        f"  winner 보존                 {kept} / {len(acc_rows)}"
        f"   ({'PASS' if kept == len(acc_rows) else 'FAIL'})",
        f"  prefilter 로 프레임 탈락    {acc_early}"
        f"   ({'PASS' if acc_early == 0 else 'FAIL'})",
        f"expensive reject frame        {len(exp_rows)}",
        f"  Blender 진입 전 조기 탈락   {exp_early}"
        f"  ({100.0 * exp_early / max(1, len(exp_rows)):.1f}%)",
        f"후보 pool                     {before:,} -> {after:,}"
        f"  ({100.0 * (before - after) / max(1, before):.1f}% 제거)",
        "```",
        "",
        "## 제거 사유",
        "",
        "```",
    ]
    for reason, count in reasons.most_common():
        md.append(f"{reason:<42} {count:,}")
    md += ["```", ""]
    io.open(os.path.join(out, "prefilter_replay.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(md) + "\n")

    print(f"accepted winner kept {kept}/{len(acc_rows)}")
    print(f"accepted frames dropped by prefilter {acc_early}")
    print(f"expensive frames early-rejected {exp_early}/{len(exp_rows)}")
    print(f"candidate pool {before} -> {after}")
    print("-> " + os.path.join(out, "prefilter_replay.csv"))
    return 0 if (kept == len(acc_rows) and acc_early == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
