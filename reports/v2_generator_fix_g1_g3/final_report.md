# Phase G1–G3 최종 보고 — v2 generator mode semantics · controlled 효율

## 1. 목적과 판정

목적: (A) mode 의미가 빈 프레임이 usable 로 통과하는 결함 제거, (B) controlled
occlusion 생성 효율 개선. Phase G1(코드) → G2(100장 smoke) → G3(재현성)까지.

```
판정                                    결과      근거
──────────────────────────────────────────────────────────────────────────────
G1_MODE_SEMANTICS_COMPLETE              true      gate 구현 · public mask 불변 ·
                                                  865 tests pass · 5k digest 불변
G1_CONTROLLED_EFFICIENCY_COMPLETE       false     recall 49/49 는 통과했으나
                                                  G2 수율 20.8% < 35%
G2_MIXED100_PASS                        false     §16 효율 게이트 3개 전부 미달
G3_REPRODUCIBILITY_PASS                 NOT_RUN   §18 에 따라 실행하지 않음
──────────────────────────────────────────────────────────────────────────────
READY_FOR_NEW_PILOT                     false
```

의미가 빈 프레임 문제는 **해결됐다**(100/100). 남은 것은 controlled 생성 **효율**이고,
그 병목은 prefilter 로 더 줄일 수 있는 종류가 아니다(§10 참조).

## 2. current branch / HEAD / diff

```
branch        main
HEAD          0ebb41cb26feed567558ad9e94e06016c5d17430   (origin/main 과 일치)
commit        0 · push 0
지시서가 적은 base 7540428a 는 Stage 2-D2 시점. 그 뒤 pilot 작업이 3599114 · 0ebb41c
로 이미 commit 돼 있어 실제 HEAD 는 0ebb41c 다. 기존 작업을 지우지 않고 그 위에서 했다.

작업 시작 시 dirty     .last-compact-resume.md (허용) · 2026-08-01.md (compact hook 마커)
                      -> UNRELATED 0건, 중단 사유 없음
```

수정 전 상태는 `preflight/`(git_status.txt · current_diff.patch + sha256 ·
code_hashes_before.csv 123파일 · baseline_pilot_lock.json)에 고정했다.

## 3. 수정 전 baseline

```
mode                 결함                                            규모
──────────────────────────────────────────────────────────────────────────────
cargo-only           cargo 가 하나도 안 놓였는데 usable 통과          51 / 400
                     cargo 자체 화면 가시성 미측정                    400 / 400
context-rich         context 배치를 시도조차 안 함 (attempts=0)       39 / 600
controlled           f_target=0 plan 을 fallback 으로 렌더 가능        경로 존재
controlled           수율 17.6% · 비싼 reject 94건 4,936초            —
```

## 4. cargo 3.8% 해석 정정

baseline 의 "cargo 15건(3.8%)" 은 **cargo 가 팔레트를 가린 프레임 수**이지 cargo 가
화면에 보인 수가 아니다. public mask 는 팔레트 전용이라 그것으로 cargo 가시성을
추론할 수 없다. 그래서 §4 에서 cargo 자체 가시성을 **별도로 측정**했고, cargo-only 의
의미는 "cargo 가 보인다"로 정의했다 — 가림은 강제하지 않는다.

mixed100 결과: cargo visible 20/20, cargo 가 팔레트를 가린 프레임 **0/20**. 후자는
정상이며 게이트가 아니다.

## 5. mode interleave

`usable_diagnostic_modes(n)` 이 10장 주기 2/2/3/3 으로 배치한다. 총량은 기존
largest-remainder 그대로. n=10/100/2000 정확, n=1..250 전수 count 일치, 같은 n 이면
항상 같은 schedule, records mode(20/500) 무변경. mixed100 실측 20/20/30/30 · 10장 블록
위반 0.

## 6. cargo direct visibility 구현

context 와 **같은** 저해상도 object holdout(`_lowres_holdout(only_white=...)`)을 재사용.
새 full-resolution 마스크를 추가하지 않았고, 임시 PNG 는 `_lowres_holdout` 이 지운다.

```
신규 record 필드  n_cargo_visible · cargo_visible_pixels ·
                 cargo_visible_pixel_ratio · cargo_visibility_measured
hard gate        cargo_visible_pixels > 0   (1px 이 최종 기준이라는 뜻은 아니다)
분포 (n=20)      min 16 · median 164 · p95/max 1,906 px @96p
```

## 7. context requested=0 원인

`image_space_context_poses` 는 이미지 좌우 띠의 픽셀 → 지면 교점으로 푼다. 저앙각에서
그 광선이 지평선 위로 가거나 교점이 `max_camera_distance=8m` 밖으로 나가 후보가 전멸했다.

```
absent 39프레임 · 후보 22,464개 기각 사유
   camera_distance_out_of_band   14,421   64.2%
   ray_up (above horizon)         5,049   22.5%
   too_close_to_pallet            2,992   13.3%
   ok                                 2    0.0%
```

## 8. context semantics 수정

같은 물리 제약(카메라 거리 밴드 · 팔레트 최소 이격 · 화면 안)을 유지한 채 순서만 뒤집은
ground-ring fallback 을 추가했다. 1차 sampler 가 하나라도 성공하면 돌지 않으므로 기존
561장의 배치는 변하지 않는다.

```
              수정 전                  수정 후
absent 39     poses 0: 38건            poses 18: 38건 · 1: 1건
present 561   poses>0: 559 / 0: 2      poses>0: 561
mixed100      —                        attempts=0 프레임 0/30 · visible 30/30
```

## 9. controlled failure matrix

`g1/controlled_failure_matrix.{csv,md}` (278행) + `controlled_candidate_labels.csv`
(848 후보). ★ 이전 보고 정정: 비싼 reject 94건은 **RGB 를 한 장도 렌더하지 않았다**
(`rendered=False`). 비용은 Blender 안 저해상도 탐색(explicit 3,118초) + 그 앞의 context
배치(1,424초)다.

## 10. prefilter 설계 근거

계획 단계 기하만 쓰는 결정적 규칙 5개. ML 아님 · frame blacklist 아님 · seed 무관.

```
규칙                                   임계          근거 (winner 49건 범위)
──────────────────────────────────────────────────────────────────────────────
side_geometry_infeasible               side=center   baseline 30회 시도 0회 성공
floor_support_infeasible               bottom/높이   winner -0.535 ~ 1.751
                                       ∉[-0.60,1.90] 접지 스냅 변위가 탐색 범위 초과
fill_ratio_too_low                     <0.45         winner 최소 0.480
insufficient_projected_area            실루엣/A_target<1.15   winner 최소 1.192
                                       실루엣/A_pallet>22.0   winner 최대 19.92
position_band_infeasible               band 밖       기존 solver 제약 재확인
```

분포 무변경: FrameSpec · f_target · side · elevation · projected size 그대로.
걸러지는 것은 후보뿐이고, 후보가 전멸한 프레임은 baseline 에서도 실패하던 프레임이다.

## 11. accepted baseline recall

```
accepted 49건의 승리 후보 보존   49 / 49    PASS
accepted 프레임 탈락             0          PASS
```

회귀 픽스처 `tests/fixtures/controlled_prefilter_winners.json` 로 고정 — 임계를 바꾸면
`test_controlled_prefilter.py::BaselineRecall` 이 먼저 깨진다.

## 12. 조기 제거된 비싼 실패 수

```
baseline replay      비싼 실패 프레임 94건 중 12건(12.8%)을 0초에 조기 배제
                     후보 pool 29,725 -> 20,013 (32.7% 제거)
mixed100 실행        prefilter 소진 12건 (Blender 미기동, 0초)
```

§7 의 engineering target(비싼 실패의 30% 이상 제거)은 후보 단위로는 31.3% 달성,
프레임 단위로는 12.8% 에 그쳤다.

## 13. mode-specific gate

`scene_placement_v2.mode_semantics_verdict()` (bpy-free)를 **두 곳에서** 강제한다 —
realize 안(최종 RGB 전에 realize_ok=False) + `usable_conditions`(최종 record 재판정).
short-circuit 없이 전부 평가하고, None 은 통과가 아니다.

## 14. public mask schema 불변

```
public 프로필      mask_amodal + mask_visible 두 폴더뿐
mixed100 실측      mask_amodal 100 · mask_visible 100 · M1~M3 0 · 임시 마스크 잔존 0
visible ⊄ amodal   위반 0
```

## 15. unit / integration / golden

```
unit          865 passed  skip 0  fail 0      (수정 전 802 → 신규 63개 추가)
integration    31 passed  skip 0
golden         51 passed  skip 0
registry      ok=28 missing=0
active scene  8cb4109a…  358,898,838 bytes    (불변)
```

## 16. 5k digest

```
5k FrameSpec   938f387d…  accepted 4,313 / rejected 687     불변
5k proposal    3cd365ee…  accepted 4,439 · 12/12 checks     불변
```

## 17. checkpoint10

mode 2/2/3/3 · semantics 10/10 · cargo 2/2 · context 3/3 · controlled 3/3(side match 3/3)
· 파일 각 10 · 무결성 위반 0 · reproj 1.27e-13 px. **PASS** → 90장 진행.

## 18. mixed100 mode counts

clean-static 20 · cargo-only 20 · context-rich 30 · controlled-occlusion 30 (전부 정확),
10장 블록 위반 0.

## 19. cargo semantics 결과

placed 20/20 · visible px>0 20/20 · semantics 20/20. 팔레트를 실제로 가린 프레임 0/20
(강제하지 않는 지표).

## 20. context semantics 결과

visible>=1 30/30 · ratio>0 30/30 · attempts=0 **0/30** · semantics 30/30.

## 21. controlled accepted 품질

```
placed 30/30 · explicit visible px>0 30/30 · side match 30/30
explicit visible px  min 187 · median 829 · p95 11,123 · max 12,513
f_target 정확도 게이트   BLOCKED — f_explicit_actual 이 baseline 49건도 신규 30건도
                                  모두 None (public 은 마스크 분해 불가, 저해상도
                                  explicit_actual 은 record 에 미저장).
                                  §15 대로 f_total 로 대체하지 않았다.
```

★ 정정: 이전 세션의 "controlled target 오차 median −0.003" 은 f_total 기반이었고
explicit solver 정확도가 아니다.

## 22. controlled 수율

```
지표                                    baseline   mixed100   기준     판정
──────────────────────────────────────────────────────────────────────────
A usable / 전체 proposal                 17.6%      20.8%    >=35%   FAIL
B usable / attempt(mode filter 제외)     27.2%      32.3%    —       —
B' usable / Blender 를 실제로 연 횟수      33.3%      39.0%    —       —
C 비싼 reject / attempt                  54.4%      50.5%    <=30%   FAIL
```

## 23. controlled runtime

```
runtime  reject 3168s / accepted 1781s = 1.78   (baseline 2.02)   <=1.0   FAIL
usable controlled 1장당 실효 wall time  165.0 s   (baseline 154.9 s)
```

⚠️ interleave 로 controlled 슬롯에 걸리는 proposal 자체가 달라졌으므로 단계 runtime
차이를 코드 변경 탓으로만 돌릴 수 없다. 게이트는 절대 기준이라 판정에는 영향 없다.

## 24. 무결성

```
rgb 100 · labels 100 · mask_amodal 100 · mask_visible 100 · usable_id 0..99 연속
missing 0 · duplicate 0 · corrupt 0 · empty amodal 0 · visible⊄amodal 0 ·
magenta 0 · 거리>10m 0 · annotation invalid 0 · gate(all_pass) 실패 0
reprojection max 4.55e-13 px  (gate 1e-04, PASS)
```

## 25. G2 판정

```
G2_MIXED100_PASS = false
```

통과: mode count · semantics 100/100 · 무결성 0 · accepted 품질(측정 가능한 항목).
미달: 효율 3개.

### 남은 실패의 원인 (비싼 실패 47건 전수)

```
bounded search 후보 기각 사유 (누적 2,114회)
   score_callback              1,032   48.8%   ← 놓을 수는 있으나 목표 가림률 미달
   candidate_budget_exhausted    486   23.0%
   support                       378   17.9%
   camera_clearance              129    6.1%
   collision                      89    4.2%

실패 vs 성공 (pre-realize)
   projected_size   실패 med 0.300 p95 0.901  |  성공 med 0.160 p95 0.528
   camera_distance  실패 med 2.58 m           |  성공 med 4.97 m
   candidates_after_prefilter  실패 med 128   |  성공 med 123   ← 후보 부족이 아니다
   realization_attempts        실패 med 20(상한 21) | 성공 med 4
```

**투영 크기가 큰(카메라가 가까운) 프레임이 실패한다.** 팔레트가 화면을 채우면
A_target 이 커져, 접지된 occluder 로 그 면적만 정확히 덮으면서 팔레트를 삼키지도
충돌하지도 않는 배치가 사실상 없다. 이것은 계획 기하로 예측 가능한 실패가 아니므로
prefilter 로 더 줄일 수 없고, 투영 크기로 프레임을 거르는 것은 **금지**다.

다음에 손댈 곳(이번 단계에서는 하지 않았다):
1. 탐색 초기화를 `explicit_target_mask_stats`(목표 측면 마스크의 bbox/centroid)로
   시드해 `score_callback` 실패를 줄인다.
2. explicit 탐색을 context 배치 **앞으로** 옮겨, 실패 시 context 비용(median 21초)을
   물지 않게 한다.
3. 저해상도 `explicit_actual`/`explicit_error` 를 record 에 남겨 public 프로필에서도
   §15 정확도 게이트를 계산 가능하게 한다.

## 26. bpy-free reproducibility

Phase G3 미실행. 도구는 준비돼 있다
(`audit_v2_bpyfree_determinism.py` · `build_v2_repro_lock.py`).

## 27. exact20 결과

미실행 (G2 미통과).

## 28. public mask reproducibility

미실행 (G2 미통과). mixed100 에서 public 스키마 불변은 확인했다(§14).

## 29. dataset-quality replay

미실행 (G2 미통과). 도구 준비 완료 (`audit_v2_dataset_quality_probe.py`).

## 30. 최종 READY_FOR_NEW_PILOT

```
READY_FOR_NEW_PILOT = false
```

500장 · 2,000장 · 40k · 논문 Figure · 최종 데이터 생성 **모두 시작하지 않았다**.

## 31. git diff

```
 scripts/data_prep/blender/run_v2_scene_logic.py    +145 -13
 scripts/data_prep/blender/scene_placement_v2.py    +241
 scripts/data_prep/blender/v2_pipeline.py            +50
 scripts/data_prep/blender/v2_realize.py             +62
 scripts/data_prep/blender/tests/*.py                +120
 신규 도구 5 · 신규 테스트 2 + fixture 1 · reports/v2_generator_fix_g1_g3/**
```

## 32. commit / push 여부

```
commit = 0
push   = 0
```

---

# 마감 지표

```
지표                                   값
──────────────────────────────────────────────────────────────────────
baseline cargo placed / visible        349 / 400  ·  미측정
smoke cargo placed / visible           20 / 20    ·  20 / 20
baseline context visible               561 / 600
smoke context visible                  30 / 30
baseline controlled yield (A)          17.6%
smoke controlled yield (A)             20.8%
baseline expensive reject share (C)    54.4%
smoke expensive reject share (C)       50.5%
baseline reject/accepted runtime       2.02
smoke reject/accepted runtime          1.78
accepted baseline prefilter recall     49 / 49
controlled target error baseline/new   BLOCKED (f_explicit_actual 양쪽 모두 None)
exact20 schedule mismatch              미실행
exact20 outcome mismatch               미실행
exact20 FrameSpec mismatch             미실행
exact20 Plan mismatch                  미실행
exact20 label mismatch                 미실행
exact20 RGB mismatch                   미실행
exact20 amodal mismatch                미실행
exact20 visible mismatch               미실행
unit fail / skip                       0 / 0   (865 passed)
integration fail / skip                0 / 0   (31 passed)
5k digest change                       0  (938f387d · 3cd365ee 불변)
baseline dataset modified              0
sampler distribution changes           0
public mask schema changes             0
500 render                             0
2k render                              0
40k render                             0
model inference                        0
model training                         0
commit                                 0
push                                   0
```
