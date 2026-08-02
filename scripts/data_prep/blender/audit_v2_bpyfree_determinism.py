"""bpy-free 결정성 감사 — 같은 seed·n 을 두 번 돌려 전 항목을 비교한다 (렌더 없음).

비교 항목 (§20)
  interleaved mode schedule · proposal index · FrameSpec canonical JSON ·
  Plan canonical JSON · controlled prefilter 결과와 사유 · frame seed ·
  attempt seed · resume 위치 (chunked replay == uninterrupted stream)

    python scripts/data_prep/blender/audit_v2_bpyfree_determinism.py \
        --seed 7000 --n 100 --proposals 400 \
        --out reports/v2_generator_fix_g1_g3/g3/reproducibility
"""
import argparse
import hashlib
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import run_v2_scene_logic as R      # noqa: E402
import scene_placement_v2 as SP2    # noqa: E402
import v2_pipeline as vp            # noqa: E402


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect(seed, n, proposals, assets, resume_from=0):
    """(schedule, per-proposal rows) — resume_from 앞의 proposal 은 건너뛴다."""
    schedule = R.usable_diagnostic_modes(n)
    rows = []
    for proposal_index, plan, reject in R.iter_proposals(
            seed, assets, vp, placement_mode="constrained",
            max_proposals=proposals):
        if proposal_index < resume_from:
            continue
        spec = plan.spec if plan is not None else reject.spec
        row = {
            "proposal_index": proposal_index,
            "outcome": "plan" if plan is not None else "reject",
            "reject_reason": None if plan is not None else reject.reason,
            "framespec_sha": sha(canon(spec.to_dict())),
            "plan_sha": None if plan is None else sha(canon(plan.to_dict())),
            "frame_seed": R._frame_seed(seed, proposal_index % max(1, n),
                                        spec.frame_index),
            "prefilter": None,
            "prefilter_reasons": None,
        }
        if plan is not None and float(spec.f_target) > 1e-6:
            adjusted = vp.prepare_diagnostic_explicit_occluders(plan, assets)
            if isinstance(adjusted, vp.Reject):
                row["prefilter"] = f"reject:{adjusted.reason}"
                row["prefilter_reasons"] = adjusted.detail
            else:
                occ = adjusted.occluder
                row["prefilter"] = "%d/%d" % (
                    occ.get("candidates_after_prefilter", -1),
                    occ.get("candidates_before_prefilter", -1))
                row["prefilter_reasons"] = canon(
                    occ.get("prefilter_reject_counts_by_reason") or {})
                row["selected_objects"] = canon(
                    [occ.get("obj_name")]
                    + [c.get("obj_name")
                       for c in (occ.get("diagnostic_resample_proposals") or [])])
        rows.append(row)
    return schedule, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--proposals", type=int, default=400,
                    help="비교할 proposal 개수 (controlled prefilter 는 비싸다)")
    ap.add_argument("--resume-cut", type=int, default=None,
                    help="chunked replay 검증 지점 (기본: proposals//3)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    out = _abs(args.out)
    os.makedirs(out, exist_ok=True)
    cut = args.resume_cut if args.resume_cut is not None else args.proposals // 3

    assets = vp.load_assets()
    schedule_a, rows_a = collect(args.seed, args.n, args.proposals, assets)
    schedule_b, rows_b = collect(args.seed, args.n, args.proposals, assets)
    _schedule_c, rows_c = collect(args.seed, args.n, args.proposals, assets,
                                  resume_from=cut)

    mismatches = {
        "mode_schedule": 0 if schedule_a == schedule_b else 1,
        "proposal_index": sum(1 for a, b in zip(rows_a, rows_b)
                              if a["proposal_index"] != b["proposal_index"]),
        "outcome": sum(1 for a, b in zip(rows_a, rows_b)
                       if a["outcome"] != b["outcome"]),
        "reject_reason": sum(1 for a, b in zip(rows_a, rows_b)
                             if a["reject_reason"] != b["reject_reason"]),
        "framespec": sum(1 for a, b in zip(rows_a, rows_b)
                         if a["framespec_sha"] != b["framespec_sha"]),
        "plan": sum(1 for a, b in zip(rows_a, rows_b)
                    if a["plan_sha"] != b["plan_sha"]),
        "frame_seed": sum(1 for a, b in zip(rows_a, rows_b)
                          if a["frame_seed"] != b["frame_seed"]),
        "prefilter_outcome": sum(1 for a, b in zip(rows_a, rows_b)
                                 if a["prefilter"] != b["prefilter"]),
        "prefilter_reason": sum(1 for a, b in zip(rows_a, rows_b)
                                if a["prefilter_reasons"] != b["prefilter_reasons"]),
        "selected_objects": sum(
            1 for a, b in zip(rows_a, rows_b)
            if a.get("selected_objects") != b.get("selected_objects")),
        "row_count": abs(len(rows_a) - len(rows_b)),
    }
    tail_a = [r for r in rows_a if r["proposal_index"] >= cut]
    mismatches["chunked_resume_rows"] = abs(len(tail_a) - len(rows_c))
    mismatches["chunked_resume_fields"] = sum(
        1 for a, c in zip(tail_a, rows_c) if a != c)

    report = {
        "seed": args.seed, "n": args.n, "proposals": args.proposals,
        "resume_cut": cut,
        "schedule_sha": sha(canon(schedule_a)),
        "stream_sha_run_a": sha(canon(rows_a)),
        "stream_sha_run_b": sha(canon(rows_b)),
        "controlled_rows": sum(1 for r in rows_a if r["prefilter"] is not None),
        "mismatches": mismatches,
        "all_zero": all(v == 0 for v in mismatches.values()),
    }
    io.open(os.path.join(out, "bpyfree_determinism.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    for key, value in mismatches.items():
        print("  %-26s %d" % (key, value))
    print("stream sha A", report["stream_sha_run_a"][:16])
    print("stream sha B", report["stream_sha_run_b"][:16])
    print("ALL ZERO:", report["all_zero"])
    return 0 if report["all_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
