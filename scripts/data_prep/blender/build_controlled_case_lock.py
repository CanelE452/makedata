"""controlled 사례를 고정 입력으로 잠근다 (읽기 전용, bpy-free).

기존 run 의 controlled accepted / expensive-reject 프레임을 뽑아, 그 프레임을 다시
만들기 위한 입력(FrameSpec · Plan · seed)과 당시 결과·비용을 한 파일에 고정한다.
generator 를 고친 뒤 **같은 입력**으로 replay 해 개선 여부를 재는 것이 목적이다.

    python scripts/data_prep/blender/build_controlled_case_lock.py \
        --dir data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public \
        --seed 7000 --out reports/v2_generator_fix_g1p5_g2b/g1p5
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import run_v2_scene_logic as R  # noqa: E402
import v2_pipeline as vp        # noqa: E402

PREFILTER_EXHAUSTED = "diagnostic_explicit_prefilter_exhausted"


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="원본 run (읽기 전용)")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    root, out = _abs(args.dir), _abs(args.out)
    os.makedirs(out, exist_ok=True)

    accepted, expensive = {}, {}
    for rec in jsonl(os.path.join(root, "records.jsonl")):
        if rec.get("diagnostic_mode") == "controlled-occlusion":
            accepted[rec["proposal_index"]] = rec
    for rec in jsonl(os.path.join(root, "records_rejected.jsonl")):
        if rec.get("diagnostic_mode") != "controlled-occlusion":
            continue
        inner = rec.get("record") or {}
        if (rec.get("stage") == "render"
                and inner.get("explicit_solver_fail_reason") != PREFILTER_EXHAUSTED):
            expensive[rec["proposal_index"]] = rec
    want = set(accepted) | set(expensive)
    if not want:
        raise SystemExit("controlled 사례를 찾지 못했습니다: " + root)

    assets = vp.load_assets()
    plans = {}
    for proposal_index, plan, _reject in R.iter_proposals(
            args.seed, assets, vp, placement_mode="constrained",
            max_proposals=max(want) + 1):
        if proposal_index in want and plan is not None:
            plans[proposal_index] = plan

    cases = []
    for proposal_index in sorted(want):
        plan = plans.get(proposal_index)
        if plan is None:
            print("  ! plan 없음", proposal_index)
            continue
        is_accepted = proposal_index in accepted
        outer = accepted.get(proposal_index) or expensive.get(proposal_index)
        rec = outer if is_accepted else (outer.get("record") or {})
        stage_rt = rec.get("stage_runtime_s") or {}
        adjusted = vp.prepare_diagnostic_explicit_occluders(plan, assets)
        occ = None if isinstance(adjusted, vp.Reject) else adjusted.occluder
        cases.append({
            "proposal_index": int(proposal_index),
            "usable_slot": int(outer.get("usable_slot")),
            "diagnostic_mode": "controlled-occlusion",
            "framespec_canonical_sha256": sha(canon(plan.spec.to_dict())),
            "plan_canonical_sha256": sha(canon(plan.to_dict())),
            "frame_seed": int(R._frame_seed(args.seed, int(outer["usable_slot"]),
                                            plan.spec.frame_index)),
            "attempt_seed": rec.get("attempt_seed") or rec.get("seed"),
            "target_side": rec.get("occluder_side_target"),
            "f_target": float(plan.spec.f_target),
            "elevation_deg": float(plan.spec.elevation_deg),
            "projected_size_ratio": float(plan.spec.proj_size_ratio),
            "camera_distance_m": float(plan.cam_distance_m),
            "selected_assets": (
                None if occ is None
                else [occ.get("obj_name")]
                + [c.get("obj_name")
                   for c in (occ.get("diagnostic_resample_proposals") or [])]),
            "target_mask_stats": rec.get("explicit_target_mask_stats"),
            "old_outcome": "accepted" if is_accepted else "expensive_reject",
            "old_solver_fail_reason": rec.get("explicit_solver_fail_reason"),
            "old_explicit_visible_pixels": rec.get(
                "explicit_occluder_visible_pixels"),
            "old_side_actual": rec.get("occluder_side_actual"),
            "old_side_match": rec.get("occluder_side_match"),
            "old_realization_attempt_count": rec.get("realization_attempt_count"),
            "old_lowres_render_count": rec.get("lowres_render_count"),
            "old_runtime_s": rec.get("runtime_s"),
            "old_stage_cargo_s": stage_rt.get("cargo"),
            "old_stage_context_s": stage_rt.get("context"),
            "old_stage_explicit_s": stage_rt.get("explicit"),
            "old_reject_counts": json.dumps(
                rec.get("explicit_reject_counts_by_reason") or {},
                sort_keys=True, ensure_ascii=False),
        })

    payload = {
        "source_run": os.path.relpath(root, PROJECT_ROOT).replace(os.sep, "/"),
        "seed": args.seed,
        "n_cases": len(cases),
        "n_accepted": sum(1 for c in cases if c["old_outcome"] == "accepted"),
        "n_expensive_reject": sum(1 for c in cases
                                  if c["old_outcome"] == "expensive_reject"),
        "cases": cases,
    }
    io.open(os.path.join(out, "locked_controlled_cases.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    with io.open(os.path.join(out, "locked_controlled_cases.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(cases[0]))
        writer.writeheader()
        writer.writerows(cases)

    print("locked %d cases (accepted %d · expensive %d) -> %s"
          % (payload["n_cases"], payload["n_accepted"],
             payload["n_expensive_reject"], out))
    old_total = sum(float(c["old_runtime_s"] or 0) for c in cases)
    old_ctx = sum(float(c["old_stage_context_s"] or 0) for c in cases
                  if c["old_outcome"] == "expensive_reject")
    print("old total Blender time %.1f s · 실패 프레임의 context 낭비 %.1f s"
          % (old_total, old_ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
