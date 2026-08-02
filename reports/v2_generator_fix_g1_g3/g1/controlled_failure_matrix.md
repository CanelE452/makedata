# §2 controlled failure matrix — 수정 전 실패 구조

출처: `reports/v2_pilot_2k_seed7000/audit/` (1,449장 baseline, 읽기 전용) +
seed 7000 proposal stream 재생(bpy-free). 수치를 추정하지 않았다.

## 1. ★ 이전 보고의 정정 — "렌더를 마친 뒤 판정한다"는 틀렸다

controlled 의 비싼 reject 94건은 **RGB 를 한 장도 렌더하지 않았다**.

```
94건 전부   rendered = False      realize_ok = False
solver      bounded_local_search_exhausted 93 · diagnostic_explicit_proposal_failed 1
```

비용은 최종 렌더가 아니라 **Blender 안에서 도는 저해상도 탐색과 그 앞의 배치**에 있다.

```
단계             비싼 reject 94건 합계(초)      accepted 49건 합계(초)
──────────────────────────────────────────────────────────────────────
explicit            3,117.7                   1,115.3
context             1,423.9                     924.1
cargo                 226.0                     131.0
anchor                 28.7                      12.8
collision_audit        21.2                      10.3
background              2.4                       1.0
```

`explicit`(bounded local search)가 63%, 그 앞에 이미 끝난 `context` 배치가 29%다.
→ **판정을 Blender 진입 전으로 옮기면 두 단계 모두 통째로 절약된다.**

## 2. controlled 파이프라인 실제 순서 [확인]

```
solve_placement (bpy-free)
   └ f_need = f_target - f_cargo_est ;  f_need>0 이면 lateral occluder 해석적 배치
_process_frame
   └ mode == controlled-occlusion 이고 f_target>0 이면
       prepare_diagnostic_explicit_occluders(plan, assets)      ← bpy-free, nonce 0..640
         · cargo_on=False 로 재해석 → 같은 seed_side 후보만 모음
         · select_diagnostic_explicit_proposals 로 6개 선정
realize (Blender)
   background → anchor → cargo → context → explicit(bounded local search) → collision
```

`f_need=0`(cargo 추정만으로 목표를 채움)인 프레임도 `prepare_…` 가 occluder 를
붙여 주므로 accepted 49장은 전부 실제 explicit occluder 를 갖는다 — 여기는 결함이 아니다.

## 3. 후보 단위 라벨 — 무엇이 실패하는가

`prepare_…` 가 고른 proposal 6개 각각에 대해 Blender 탐색 결과를 `explicit_search_runs`
로 라벨링했다(오브젝트 이름으로 join — run 의 proposal_index 는 realize 내부 dedup 을
거친 index 라 순서가 어긋난다).

```
후보 총계 848   실제로 탐색까지 간 것 364   미시도 484
  성공(search_success) 57      winner(프레임을 살린 것) 49
  시도했으나 실패            307
```

`explicit_reject_counts_by_reason` 상위: `score_callback`(목표 오차 미달) ·
`support`(접지 실패) · `candidate_budget_exhausted` · `camera_clearance`.

## 4. winner vs 시도-실패 후보의 pre-realize 분포

```
지표                       winner(min~max)              시도-실패(min~max)
────────────────────────────────────────────────────────────────────────────
planned_bottom_z / 높이    -0.535 ~ 1.751               -8.5 이하까지 ·  최대 3.0
fill_ratio                  0.480 ~ 0.981                0.200 ~ 0.981
silhouette / A_target       1.192 ~ 78.85                1.000 ~ 1423
screen_area / A_pallet      0.167 ~ 19.92                더 넓게 퍼짐
side                        left/right/bottom 만          center 15건 포함 (성공 0)
```

물리적으로 읽으면:

- **접지 불가** — 계획된 AABB 바닥이 자기 높이의 절반 넘게 지면 아래로 파묻혀 있으면,
  Blender 가 접지시키며 올리는 변위가 bounded search 의 u/v/depth 범위를 넘는다.
- **실루엣 여유 없음** — 실루엣이 요구 겹침면적의 1.2배도 안 되면 어떤 섭동도 목표를 놓친다.
- **성긴 실루엣** — fill_ratio 가 낮은 에셋(격자·펜스)은 조밀한 겹침을 만들지 못한다.
- **center side** — 통째로 포함되어야 하므로 접지된 occluder 로는 만족시킬 수 없다(0/30).

## 5. 코드 수정 전에 명시하는 기대 결과

1. accepted baseline 49건의 **winner 후보는 사전 필터가 전부 보존**해야 한다 (recall 49/49).
2. 비싼 실패의 일부는 Blender 상세 realization **전에** 제거돼야 한다 (목표 ≥30%).
3. accepted 의 f_target 정확도·side 일치는 **악화되면 안 된다**.
4. cargo/context mode 의 의미는 "그 물체가 실제로 화면에 보이는가"로 보장돼야 한다.

## 6. 산출

```
controlled_failure_matrix.csv          278행 (accepted 49 + rejected 229) · pre-realize 변수 전량
controlled_failure_matrix_summary.json 분포·단계별 runtime
controlled_candidate_labels.csv        848행 — 후보 단위 라벨 (prefilter 설계 근거)
mode_semantics_baseline.json           cargo/context/controlled 의미 기준값
```
