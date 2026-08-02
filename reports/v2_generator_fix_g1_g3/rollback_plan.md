# Phase G1–G3 — rollback plan

commit 하지 않았으므로 되돌리기는 worktree 조작만으로 끝난다.
**`git checkout` / `git reset` / `git stash` 로 통째로 날리지 않는다** — 되돌릴 파일을
지정해서 되돌린다.

## 1. 지금 상태

```
HEAD          0ebb41cb26feed567558ad9e94e06016c5d17430  (origin/main 과 일치)
commit        없음
push          없음
수정 파일      scripts/data_prep/blender/{run_v2_scene_logic,scene_placement_v2,
                                          v2_pipeline,v2_realize}.py
              scripts/data_prep/blender/tests/{test_scene_placement_v2,
                                               test_usable_completion_mode,
                                               test_v2_pilot_resume_reproducibility}.py
신규 파일      scripts/data_prep/blender/audit_v2_controlled_prefilter.py
              scripts/data_prep/blender/audit_v2_mode_semantics.py
              scripts/data_prep/blender/audit_v2_bpyfree_determinism.py
              scripts/data_prep/blender/audit_v2_dataset_quality_probe.py
              scripts/data_prep/blender/build_v2_overlay_review.py
              scripts/data_prep/blender/tests/test_mode_semantics.py
              scripts/data_prep/blender/tests/test_controlled_prefilter.py
              scripts/data_prep/blender/tests/fixtures/controlled_prefilter_winners.json
              reports/v2_generator_fix_g1_g3/**
신규 데이터    data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public
              (100장, engineering smoke — 논문 Figure/학습용 아님)
```

수정 전 파일 SHA256 은 `preflight/code_hashes_before.csv`,
수정 전 diff 는 `preflight/current_diff.patch` (sha256 `preflight/current_diff_sha256.txt`).

## 2. 전면 rollback

```bash
git checkout -- scripts/data_prep/blender/run_v2_scene_logic.py \
                scripts/data_prep/blender/scene_placement_v2.py \
                scripts/data_prep/blender/v2_pipeline.py \
                scripts/data_prep/blender/v2_realize.py \
                scripts/data_prep/blender/tests/test_scene_placement_v2.py \
                scripts/data_prep/blender/tests/test_usable_completion_mode.py \
                scripts/data_prep/blender/tests/test_v2_pilot_resume_reproducibility.py
# 신규 파일은 추적되지 않으므로 남는다.  지울지 여부는 사람이 판단한다 (자동 삭제 금지).
```

되돌린 뒤 확인:

```bash
python -m pytest scripts/data_prep/blender/tests/ -q          # 802 passed 로 복귀
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 --dump <tmp>
#   sha256 938f387d…  (수정 전후 불변이므로 이 값은 rollback 판단 근거가 아니다)
```

## 3. 부분 rollback (권장 순서)

효율 게이트만 미달이고 semantics 는 전부 통과했으므로, 통째로 되돌릴 이유는 없다.
되돌린다면 다음 단위로 나뉜다.

```
단위                          파일                              되돌리면 잃는 것
────────────────────────────────────────────────────────────────────────────────
mode interleave               run_v2_scene_logic.py             prefix 대표성
                              (USABLE_MODE_CYCLE,
                               usable_diagnostic_modes)
cargo 자체 가시성              v2_realize.py (cargo 단계)         cargo-only 의미 보장
context ground-ring fallback  scene_placement_v2.py             attempts=0 39장 복구
                              (image_space_context_poses)
controlled fallback 제거       run_v2_scene_logic.py (run_usable) occluder 없는 controlled 차단
mode semantics gate           scene_placement_v2.py +           mode 의미 강제 전체
                              run_v2_scene_logic.py +
                              v2_realize.py
controlled prefilter          scene_placement_v2.py +           0초 조기 배제 12건
                              v2_pipeline.py
```

각 단위는 서로 독립이다. 단, **mode semantics gate 를 되돌리면 cargo/context 가시성
필드가 gate 에서 쓰이지 않게 되므로** 측정 코드만 남는다(무해).

## 4. 데이터

```
baseline pilot  data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_public
                1,449장 · 읽기 전용 · 이번 작업에서 한 바이트도 건드리지 않았다
                (preflight/baseline_pilot_lock.json 의 SHA256 으로 확인)
smoke100        data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public
                100장 · engineering smoke.  삭제해도 코드 rollback 과 무관하다.
                삭제 여부는 사람이 판단한다.
```

## 5. 되돌리면 안 되는 것

- baseline pilot 1,449장 (다음 비교의 기준선)
- `reports/v2_pilot_2k_seed7000/**` (baseline 감사 근거)
- `preflight/**` (수정 전 상태의 유일한 증거)
- `tests/fixtures/controlled_prefilter_winners.json` (prefilter recall 회귀 픽스처)
