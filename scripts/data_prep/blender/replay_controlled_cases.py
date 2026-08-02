"""고정된 controlled 사례를 현재 코드로 replay 한다 (Blender 안에서 실행).

`build_controlled_case_lock.py` 가 잠근 입력(FrameSpec/Plan/seed)을 그대로 다시 만들어
같은 파이프라인(`_process_frame` + `usable_conditions`)에 통과시킨다.  generator 를
고친 뒤 "같은 프레임에서" 무엇이 좋아졌고 무엇이 나빠졌는지 보는 것이 목적이다.

    blender -b <scene> --python scripts/data_prep/blender/replay_controlled_cases.py -- \
        --cases reports/v2_generator_fix_g1p5_g2b/g1p5/locked_controlled_cases.json \
        --out data/pallet/runs/diagnostics/_replay_controlled_g1p5 \
        --render-profile dataset-quality --samples 64 --mask-profile public

프레임 하나당 record 한 줄을 `replay_records.jsonl` 로 남긴다.  원본 run 은 건드리지
않는다 (읽기 전용).
"""
import argparse
import io
import json
import os
import sys
import time
from types import SimpleNamespace

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import mask_profiles as MP        # noqa: E402
import run_v2_scene_logic as R    # noqa: E402


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=None,
                    help="생략하면 lock 파일의 seed 를 쓴다")
    ap.add_argument("--render-profile", default="dataset-quality")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--noise-tier", default="auto")
    ap.add_argument("--mask-profile", default="public")
    ap.add_argument("--magenta-max-fraction", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cases-filter", default=None,
                    help="쉼표로 구분한 proposal_index 목록 (mechanism subset 용)")
    ap.add_argument("--target-seed-free-cap", type=int, default=None)
    ap.add_argument("--near-miss-gap-threshold", type=float, default=None)
    ap.add_argument("--constraint-rescue-mode", default=None)
    ap.add_argument("--constraint-rescue-beam", type=int, default=None)
    ap.add_argument("--constraint-rescue-eval-max", type=int, default=None)
    ap.add_argument("--constraint-rescue-category-max", type=int, default=None)
    ap.add_argument("--holdout-engine", default="cycles",
                    choices=("cycles", "eevee"))
    ap.add_argument("--tag", default=None, help="로그·요약에 남길 config 이름")
    return ap.parse_args(argv)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parse_args(argv)

    payload = json.load(io.open(_abs(args.cases), encoding="utf-8"))
    cases = payload["cases"]
    if args.cases_filter:
        wanted_ids = {int(x) for x in args.cases_filter.split(",") if x.strip()}
        cases = [c for c in cases if int(c["proposal_index"]) in wanted_ids]
    if args.limit:
        cases = cases[:args.limit]
    seed = int(args.seed if args.seed is not None else payload["seed"])

    out = _abs(args.out)
    dirs = {"out": out, "rgb": os.path.join(out, "rgb"),
            "mask": os.path.join(out, "mask"),
            "labels": os.path.join(out, "labels"),
            "logs": os.path.join(out, "logs")}
    profile_dirs = [os.path.join(out, name)
                    for name in MP.mask_dirnames(args.mask_profile)]
    for path in (out, dirs["rgb"], *profile_dirs, dirs["labels"], dirs["logs"]):
        os.makedirs(path, exist_ok=True)

    import numpy as np
    import v2_pipeline as vp
    import v2_realize as vr

    runner_args = SimpleNamespace(
        out=out, seed=seed, n=max(c["usable_slot"] for c in cases) + 1,
        completion_mode="usable", max_attempts=None,
        magenta_max_fraction=args.magenta_max_fraction, samples=args.samples,
        render_profile=args.render_profile, noise_tier=args.noise_tier,
        mask_profile=args.mask_profile, start=0, count=0, rerun_failures=False,
        session_usable_cap=None,
        target_seed_free_cap=args.target_seed_free_cap,
        near_miss_gap_threshold=args.near_miss_gap_threshold,
    )

    vr.set_holdout_engine(args.holdout_engine)
    tuning = vr.set_search_tuning(
        target_seed_free_cap=args.target_seed_free_cap,
        near_miss_gap_threshold=args.near_miss_gap_threshold,
        constraint_rescue_mode=args.constraint_rescue_mode,
        constraint_rescue_beam=args.constraint_rescue_beam,
        constraint_rescue_eval_max=args.constraint_rescue_eval_max,
        constraint_rescue_category_max=args.constraint_rescue_category_max,
    )
    print(f"[REPLAY] tag={args.tag} tuning={tuning}", flush=True)
    gpu = vr.enable_gpu()
    assets = vp.load_assets()
    wanted = {int(c["proposal_index"]): c for c in cases}
    print(f"[REPLAY] gpu={gpu} cases={len(cases)} seed={seed} out={out}",
          flush=True)

    flush_overheads = []
    plans = {}
    for proposal_index, plan, _reject in R.iter_proposals(
            seed, assets, vp, placement_mode="constrained",
            max_proposals=max(wanted) + 1):
        if proposal_index in wanted and plan is not None:
            plans[proposal_index] = plan
    print(f"[REPLAY] plans replayed {len(plans)}/{len(wanted)}", flush=True)

    records_path = os.path.join(out, "replay_records.jsonl")
    started = time.time()
    with io.open(records_path, "w", encoding="utf-8", newline="\n") as fh:
        for order, case in enumerate(cases):
            proposal_index = int(case["proposal_index"])
            plan = plans.get(proposal_index)
            if plan is None:
                print(f"[REPLAY] ! plan 없음 proposal={proposal_index}", flush=True)
                continue
            slot = int(case["usable_slot"])
            t0 = time.time()
            processed = R._process_frame(
                slot, plan, "controlled-occlusion", runner_args, assets, dirs,
                vp, vr, np, write_label=False)
            record = processed["record"]
            record["proposal_index"] = proposal_index
            record["usable_slot"] = slot
            record["completion_mode"] = "replay"
            meas = processed["meas"]
            if meas is not None:
                record.update(R._mask_integrity_fields(
                    meas.get("mask_paths"), meas.get("mask_profile")))
                keypoints = R._visible_keypoint_metrics(meas)
                record.update(keypoints)
                record.update(R.pnp_size_fields(
                    keypoints.get("bbox_vis_min_side_px"),
                    record.get("mask_m0_area_px")))
            verdict = R.usable_conditions(
                record, magenta_max=runner_args.magenta_max_fraction,
                seen_m0_hashes=set())
            record["usable"] = verdict["usable"]
            record["usable_failed_conditions"] = verdict["failed_conditions"]
            record["usable_reject_reasons"] = verdict["reject_reasons"]
            record["mode_semantics_pass"] = verdict["mode_semantics_pass"]
            record["replay_wall_s"] = round(time.time() - t0, 3)
            record["old_outcome"] = case["old_outcome"]
            record["old_runtime_s"] = case["old_runtime_s"]
            record["old_stage_context_s"] = case["old_stage_context_s"]
            record["old_stage_explicit_s"] = case["old_stage_explicit_s"]
            record["old_explicit_visible_pixels"] = case[
                "old_explicit_visible_pixels"]
            record["old_side_match"] = case["old_side_match"]
            record["old_realization_attempt_count"] = case[
                "old_realization_attempt_count"]
            record["config_tag"] = args.tag
            record["config_target_seed_free_cap"] = args.target_seed_free_cap
            record["config_near_miss_gap_threshold"] = args.near_miss_gap_threshold
            record["config_holdout_engine"] = args.holdout_engine
            fh.write(json.dumps(record, ensure_ascii=False,
                                default=R._json_default) + "\n")
            fh.flush()
            # §13 CASE_WALL_TIME_S 의 정의는 "최종 record flush 완료"까지다.
            # replay_wall_s 는 G1.6 baseline 과 직접 비교해야 하므로 정의를 바꾸지
            # 않고, flush 까지 포함한 값을 따로 재서 차이를 보고한다.
            flush_overheads.append(round(time.time() - t0
                                         - record["replay_wall_s"], 6))
            print("[REPLAY] %3d/%d proposal=%d slot=%d old=%s new=%s %.1fs"
                  % (order + 1, len(cases), proposal_index, slot,
                     case["old_outcome"],
                     "accepted" if verdict["usable"] else "rejected",
                     record["replay_wall_s"]), flush=True)

    total_flush = sum(flush_overheads)
    io.open(os.path.join(out, "wall_time_definition.json"), "w",
            encoding="utf-8", newline="\n").write(json.dumps({
                "replay_wall_s_covers":
                    "case 시작 ~ record 완성 (직렬화 직전)",
                "excluded": "json.dumps + write + flush",
                "flush_overhead_total_s": round(total_flush, 6),
                "flush_overhead_max_s": (round(max(flush_overheads), 6)
                                         if flush_overheads else 0.0),
                "cases": len(flush_overheads),
            }, indent=2, ensure_ascii=False) + "\n")
    print("[REPLAY] flush overhead total %.4f s (max %.4f s)"
          % (total_flush, max(flush_overheads) if flush_overheads else 0.0),
          flush=True)
    print("[REPLAY] DONE %d cases in %.1f s -> %s"
          % (len(cases), time.time() - started, records_path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
