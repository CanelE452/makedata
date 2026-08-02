# Phase G1.6 — rollback plan

commit 하지 않았다. 되돌리기는 worktree 조작만으로 끝나지만, 같은 worktree 에
**직전 단계(G1~G2b)의 작업물이 함께 있으므로** `git checkout .` / `reset` / `stash` 로
통째로 날리지 않는다.

## 1. 지금 상태

```
HEAD    0ebb41cb26feed567558ad9e94e06016c5d17430  (= origin/main)
commit 0 · push 0
```

이번 단계에서 **수정**한 파일:

```
scripts/data_prep/blender/v2_realize.py             SEARCH_TUNING · target-seed 예산
                                                    회계 · fine 단계 · fine 계측 필드
scripts/data_prep/blender/scene_placement_v2.py     candidate_geometry_key ·
                                                    target_seed_budget_usage ·
                                                    budgeted_attempt_count ·
                                                    near_miss_candidates ·
                                                    select_near_miss_seed ·
                                                    fine_refinement_offsets
scripts/data_prep/blender/run_v2_scene_logic.py     CLI 2개 · set_search_tuning 호출 ·
                                                    신규 17 필드 전파
scripts/data_prep/blender/replay_controlled_cases.py  --cases-filter · --tag · config 2개
scripts/data_prep/blender/tests/{test_usable_completion_mode,
                                 test_explicit_lowres_metrics}.py   스키마·이름 갱신
```

이번 단계에서 **신규**:

```
scripts/data_prep/blender/audit_v2_score_gap.py
scripts/data_prep/blender/build_mechanism_subset.py
scripts/data_prep/blender/audit_mechanism_sweep.py
scripts/data_prep/blender/tests/test_target_seed_budget_and_fine.py
reports/v2_generator_fix_g1p6_g2c_g3/**
data/pallet/runs/diagnostics/_sweep_*            (7개, mechanism sweep)
data/pallet/runs/diagnostics/_locked77_g1p6      (77건 replay)
```

수정 전 상태: `preflight/code_hashes_before.csv` (134 파일 SHA256) ·
`preflight/current_diff.patch` (+ sha256).

## 2. 이번 단계만 되돌리기 (직전 G1~G2b 는 유지)

`preflight/current_diff.patch` 가 **이번 단계 시작 시점**의 diff 다.

```bash
git stash push -- scripts/data_prep/blender          # 보관 (삭제 아님)
git checkout -- scripts/data_prep/blender            # HEAD 로 되돌림
git apply reports/v2_generator_fix_g1p6_g2c_g3/preflight/current_diff.patch
# -> G1~G2b 상태로 복귀.  신규 파일은 추적되지 않으므로 그대로 남는다.
python -m pytest scripts/data_prep/blender/tests/ -q   # 888 passed 로 복귀
```

## 3. 부분 rollback

두 메커니즘은 **서로 독립**이고, 기본값(`None`)이면 둘 다 G1.5 동작과 동일하다.

```
단위                    되돌리는 법                          잃는 것
──────────────────────────────────────────────────────────────────────────────
target-seed 상한        --target-seed-free-cap 생략          없음 (실측상 무동작)
near-miss fine          --near-miss-gap-threshold 생략       회복 4건 · fine 승리 4
코드 자체 제거          v2_realize 의 fine 블록 +            위와 같음 + 계측 필드
                        SP2 의 near_miss_* / fine_*
```

⚠️ **CLI 를 생략하면 코드가 남아 있어도 동작이 G1.5 와 같다** (`SEARCH_TUNING` 기본값이
둘 다 `None`). 따라서 급히 되돌려야 하면 코드를 만지지 말고 **인자를 빼는 것으로 충분**하다.

## 4. 데이터

```
읽기 전용 유지   v2_pilot_2k_seed7000_public                 1,449장
읽기 전용 유지   v2_mode_semantics_smoke100_seed7000_public   100장
읽기 전용 유지   v2_mode_semantics_smoke100b_seed7000_public  100장 + overlay 100
삭제해도 무방     _replay_controlled_g1p5                      77건 (G1.5 기준선)
삭제해도 무방     _sweep_*                                     7개 (mechanism sweep)
삭제해도 무방     _locked77_g1p6                               77건 (이번 replay)
```

세 baseline 의 `records.jsonl` SHA256 은 `preflight/baseline_locks.json` 에 있고,
작업 종료 시 **전부 불변**임을 확인했다.

## 5. 되돌리면 안 되는 것

- `preflight/**` (이번 단계 시작 상태의 유일한 증거)
- `g1p6/locked_controlled_cases_ref.json` (다음 비교의 고정 입력)
- `g1p6/score_gap_*.csv` · `mechanism_subset*` (설정 선택의 근거)
- `reports/v2_generator_fix_g1_g3/**` · `reports/v2_generator_fix_g1p5_g2b/**`
- `tests/fixtures/controlled_prefilter_winners.json`
