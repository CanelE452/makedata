# Phase G1.5 / G2b — rollback plan

commit 하지 않았으므로 되돌리기는 worktree 조작만으로 끝난다.
**`git checkout .` / `git reset` / `git stash` 로 통째로 날리지 않는다** — 직전 단계
(G1~G3)의 작업물이 같은 worktree 에 함께 있다.

## 1. 지금 상태

```
HEAD          0ebb41cb26feed567558ad9e94e06016c5d17430  (= origin/main)
commit 0 · push 0
```

이번 단계에서 **수정**한 파일:

```
scripts/data_prep/blender/v2_realize.py            단계 재배열 · explicit 저해상도 통계 ·
                                                   target-seed · 탐색 계측 · 코너 기준
scripts/data_prep/blender/scene_placement_v2.py    explicit_lowres_metrics ·
                                                   explicit_search_metrics ·
                                                   context_corner_no_regression
scripts/data_prep/blender/run_v2_scene_logic.py    신규 18 필드 전파 · manifest 4열
scripts/data_prep/blender/build_v2_overlay_review.py  --dataset-overlay-dir · --audit ·
                                                   sheet_extreme_*
scripts/data_prep/blender/audit_v2_mode_semantics.py  저해상도 품질 필드 집계
scripts/data_prep/blender/tests/test_usable_completion_mode.py  고정 스키마 갱신
```

이번 단계에서 **신규**:

```
scripts/data_prep/blender/build_controlled_case_lock.py
scripts/data_prep/blender/replay_controlled_cases.py
scripts/data_prep/blender/audit_controlled_replay.py
scripts/data_prep/blender/tests/test_explicit_lowres_metrics.py
reports/v2_generator_fix_g1p5_g2b/**
data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public   (100장 + overlay 100)
data/pallet/runs/diagnostics/_replay_controlled_g1p5                        (locked replay 77건)
```

수정 전 파일 SHA256 은 `preflight/code_hashes_before.csv`, 수정 전 diff 는
`preflight/current_diff.patch`(sha256 `preflight/current_diff_sha256.txt`).
그 diff 는 **직전 단계까지의 변경**이므로, 이번 단계만 되돌리려면 아래 3·4 를 쓴다.

## 2. 이번 단계 전체 되돌리기 (직전 G1~G3 는 유지)

`preflight/current_diff.patch` 가 "이번 단계 시작 시점"의 diff 다. 따라서:

```bash
git stash push -- scripts/data_prep/blender      # 현재 변경 임시 보관 (삭제 아님)
git checkout -- scripts/data_prep/blender        # HEAD 로 되돌림 (= G1~G3 도 사라짐)
git apply reports/v2_generator_fix_g1p5_g2b/preflight/current_diff.patch
# -> G1~G3 상태로 복귀.  신규 파일은 추적되지 않으므로 그대로 남는다.
```

되돌린 뒤 확인:

```bash
python -m pytest scripts/data_prep/blender/tests/ -q     # 865 passed 로 복귀
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 --dump <tmp>
#   sha256 938f387d…  (이번 단계 전후 불변이라 rollback 판단 근거는 아니다)
```

## 3. 부분 rollback (권장 — 단위별로 독립이다)

```
단위                          되돌릴 대상                        잃는 것
────────────────────────────────────────────────────────────────────────────────
explicit 저해상도 품질 지표    scene_placement_v2.explicit_lowres  public 에서 품질 게이트
                              _metrics + v2_realize 의 호출/계산   계산 불가 (BLOCKED 복귀)
단계 재배열(explicit 먼저)     v2_realize 의 P->E->C 순서 +        실패 프레임 context 낭비
                              explicit_blocked                    1,151초 복귀
post-explicit 코너 기준        context_corner_no_regression        재배열과 **세트** —
                                                                  되돌리면 context 전멸
target-seed 우선 + 예산 면제   v2_realize 의 target-seed 블록 +    승리 stage 21/31 상실
                              attempted_for_proposal 필터
overlay 데이터셋 출력·감사     build_v2_overlay_review 옵션 2개    overlay 감사 불가
```

⚠️ **단계 재배열과 post-explicit 코너 기준은 반드시 함께 되돌린다.** 재배열만 남기고
코너 기준을 되돌리면 context 후보가 전멸해 context 단계가 14초 -> 225초로 폭증한다
(1차 replay 실측).

## 4. 데이터

```
읽기 전용 유지   v2_pilot_2k_seed7000_public          1,449장 (다음 비교의 기준선)
읽기 전용 유지   v2_mode_semantics_smoke100_seed7000_public  100장 (이번 비교의 baseline)
삭제해도 무방     v2_mode_semantics_smoke100b_seed7000_public 100장 (engineering smoke)
삭제해도 무방     _replay_controlled_g1p5                     77건 (locked benchmark 산출)
```

두 baseline 의 `records.jsonl` SHA256 은 `preflight/baseline_*_lock.json` 에 있고,
작업 종료 시 **둘 다 불변**임을 확인했다.

## 5. 되돌리면 안 되는 것

- `preflight/**` (이번 단계 시작 상태의 유일한 증거)
- `g1p5/locked_controlled_cases.{json,csv}` (다음 비교의 고정 입력)
- `reports/v2_generator_fix_g1_g3/**` (직전 단계 근거)
- `tests/fixtures/controlled_prefilter_winners.json` (prefilter recall 회귀 픽스처)
