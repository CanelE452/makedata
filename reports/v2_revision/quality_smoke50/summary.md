# v2 pipeline revision — usable 50-frame quality smoke (Phase 9D) + final report (Phase 9E)

작성 2026-07-27. 대상 산출물 `data/pallet/_v2_smoke50_9d/`.
이 문서는 **50장 usable 프레임**에 대한 보고다. 500-frame pilot도 40k 본렌더도 수행하지 않았다.

관찰(수치·파일수·테스트 결과)과 판정(training-ready 여부)을 분리했고, 모든 사실에 `[확인]`(실행/파일/로그로
직접 검증) / `[추정]`(코드·주석·관례에서 추론, 미검증) 태그를 붙였다. 비율에는 항상 분모를 적었다.

---

## 0. 실행 명령과 소요 시간

```bash
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
  data/pallet/blender_scene/synth_data_scene.blend \
  --python scripts/data_prep/blender/run_v2_scene_logic.py -- \
  --out data/pallet/_v2_smoke50_9d \
  --seed 7000 --n 50 \
  --completion-mode usable --render-profile dataset-quality
```

- seed 7000을 쓴 이유: 9B(40k dry-run)·9C(20-frame exact smoke)와 **같은 proposal 스트림**이라 bpy-free 층과
  Blender 층의 plan 일치를 다시 대조할 수 있다. [확인]
- 사용자 GUI Blender(PID 16684)는 건드리지 않았다. headless 신규 프로세스 1개만 띄웠다. [확인]

```
지표                              실측
──────────────────────────────────────────────────────────
wall clock                        1925.7 s = 32.1 분  (exit code 0)
delivered usable                  50 / 50
proposals drawn                   107
render attempts                   75
delivered / render attempt        50/75 = 66.7 %
proposals / delivered             107/50 = 2.14
delivered 프레임 runtime          median 13.6 s (min 4.0 / max 56.2)
GPU                               OPTIX, dataset-quality(64 samples + OIDN)
```

Phase 7의 사전 추정은 "35~70분(중앙 ~50분)"이었다. **실측 32.1분**으로 추정 하한보다 빨랐다 — 추정은
usable10(32 s/배달)과 resume12(123 s/배달)의 폭으로 잡았는데, 실제로는 clean-static/cargo-only 슬롯이
4~6 s로 매우 빨라 평균이 내려갔다. [확인]

---

## 1. 9D 조건별 실측 (전부 PASS)

```
#   조건                                              실측                                   판정
──────────────────────────────────────────────────────────────────────────────────────────────────
1   usable RGB 정확히 50                              rgb/*.png = 50                         PASS
2   label 50                                          labels/*_label.json = 50               PASS
3   M0~M4 250 files (50x5)                            m0..m4 각 50, 합 250                   PASS
4   rejected proposal 별도 보존                       records_rejected.jsonl = 57행          PASS
5   camera distance > 10 m 인 usable 프레임 0         0/50 (max 9.737 m, limit 10.0)         PASS
6   empty M0 0                                        0/50 (min M0 = 550 px)                 PASS
7   corrupt RGB/mask/label 0                          strict decode fail 0 (250 mask+50 rgb) PASS
8   pixel-level mask inclusion fail 0                 0 frame / 0 pair / 0 px (50 검사)      PASS
9   evaluated exact collision 0                       exact_collision_count max 0            PASS
10  support fail 0                                    support_pass True 50/50                PASS
11  camera-clearance fail 0                           camera_clearance_pass True 50/50       PASS
12  ground-continuity fail 0 (is True)                ground_continuity_pass True 50/50      PASS
                                                      probe 11/frame, fail 0, max step 0.0 m
                                                      min floor edge margin 15.484 m
13  G5가 final-RGB 기준                               코드+라벨 확인 (아래 1.1)              PASS
14  solvePnP exact success 50/50                      50/50 (아래 1.2 단서 있음)             PASS*
15  detailed overlay 50/50                            overlay 50 + contact sheet 5장         PASS
16  source-mask sheet 생성                            3페이지 + 대표 1장                     PASS
17  continuous EDA 전 figure                          required 13/13 status=ok, 총 17/17     PASS
```

부가로 `audit_v2_scene_logic.py --expected-frame-count 50` 이 **status=PASS, failures=0, fatal 0**을 냈다. [확인]
G1~G5는 50/50 전원 통과, magenta max 0.0, RGB hash 중복 0, cross-frame mask duplicate 0,
within-frame byte-exact duplicate 0, hull bbox IoU(M0) median 0.963, hull-outside ratio max 0.0225(경고 임계 0.20). [확인]

### 1.1 G5가 final RGB 기준인지

- 코드: `v2_realize.safety_gates()`가 `meas["luma_pallet_final"] if "luma_pallet_final" in meas else
  meas.get("luma_pallet")`로 읽고 `g5 = lp >= G5_LUMA_MIN`을 판정한다. [확인]
- 라벨: 50/50 프레임 모두 `v2_labels.luma_pallet_final`이 non-null이다 → 위 분기에서 **final 쪽**이 잡힌다. [확인]
- post-effect가 실제로 luma를 바꿨다: raw != final 이 **48/50** 프레임, 최대 |final−raw| = 5.94.
  final < raw 46건 / final > raw 2건. [확인]
- **한계**: 이번 50장은 `luma_pallet_final` 최소 16.35, `luma_pallet_raw` 최소 16.52로 **어느 쪽으로 재도
  G5 판정이 같다**(임계 12.0을 가로지르는 프레임 0/50). 즉 배달셋만으로는 raw/final을 *구분*하지 못한다.
  구분 근거는 코드 경로 + Phase 3에서 실측한 판정 뒤집힘 3건(12.34→10.66 등)이다. [확인]
- 렌더된 reject 3건에도 G5 실패는 없었다(G1 2건 / G3 1건). 이 실행에서 G5 탈락은 **0건**이다. [확인]

### 1.2 solvePnP exact success — 50/50이지만 그중 2건은 기하학적으로 발산

`audit_pnp_eligibility.py --dir data/pallet/_v2_smoke50_9d` 결과:

```
n_frames                     50
n_geometry_ok                50
n_pnp_exact_success          50 / 50      <- solver 반환 플래그 기준
n_physical_valid             50
n_gate_valid                 50
label_reproj_consistency_px  max 2.27e-13  <- 라벨 자체 정합성
tiny_warning                 4
pnp_stress                   26
```

지시된 조건("solvePnP exact success 50/50")은 **충족**이다. 다만 **조용히 넘어가면 안 되는 단서**가 있다:

```
frame   exact reproj mean   trans err        rot err    visible kp   elev
────────────────────────────────────────────────────────────────────────────
f0038         34.93 px      4.18e+11 cm      146.4 deg      5        8.48 deg
f0049         30.61 px      2.48e+07 cm      160.0 deg      5        4.60 deg
나머지 48     median 9.7e-06 px   median 2.4e-05 cm   median 8.7e-06 deg
```

- 즉 **48/50은 GT를 기계 정밀도로 복원**하고, **2/50은 solver가 success를 반환했지만 미러/뒤집힌 해**다. [확인]
- 두 프레임 모두 **visible keypoint 5개 + 저앙각(8.5도/4.6도)** — 평면 팔레트가 거의 edge-on이라 EPnP가
  퇴화하는 구성이다. 노이즈가 0(exact GT)인데도 발산하므로 **노이즈 문제가 아니라 구성(configuration) 문제**다. [확인]
- visible kp 5개 프레임은 50장 중 18장인데 발산은 2장뿐 → "5점이면 항상 실패"는 아니다. [확인]
- solver는 계획 확정대로 평가 코드와 동일(`cv2.solvePnPRansac` + `SOLVEPNP_EPNP`, reprojError 8.0,
  iterations 100)이며 **이번 세션에서 바꾸지 않았다**. 바꾸면 평가 코드와 어긋난다.
- 이 2건은 overlay에서 즉시 보인다(f0038 패널 `pnp reproj: 34.927 px`). [확인]

### 1.3 Monte-Carlo 섭동 표 (50 프레임, 시그마당 200 trial)

```
sigma   solve fail(mean)   5cm-5deg fail(mean)   trans q90 median(cm)   rot q90 median(deg)
────────────────────────────────────────────────────────────────────────────────────────────
1 px         0.000               0.303                   4.85                 1.46
2 px         0.000               0.445                  10.29                 2.84
3 px         0.000               0.527                  17.05                 4.32
```

크기별(visible keypoint bbox 최소변):

```
bbox_min_side_px     n   5cm-5deg fail@2px   trans q90@2px (cm)
────────────────────────────────────────────────────────────────
[    0,   16)        4        0.855               40.32
[   16,   24)        6        0.752               50.69
[   24,   32)        2        0.423               15.43
[   32,   64)       11        0.693               56.61
[   64,  128)       11        0.437               10.91
[  128,  256)       10        0.095                2.67
[  256,  inf)        6        0.014                2.60
```

435-frame(구 500셋) 스터디와 **정성적으로 같은 서열**이지만 중간 구간(32~64px)이 뒤집혀 있다 —
n=11의 소표본 요동으로 보이며, 이 50장으로 threshold를 확정할 근거는 되지 않는다. [확인]

후보별 통과 수(50 프레임): 2cell(16px) 46 pass / 3cell(24px) 40 / 4cell(32px) 38.
가장 엄격한 4cell을 통과한 38장조차 sigma=2px에서 5cm-5도 실패율 0.354다. [확인]

---

## 2. accepted / rejected (proposal 단위)

```
단계                                    건수    비고
───────────────────────────────────────────────────────────────────────────────
proposals drawn                          107
├ mode_filter skip                        24    controlled 슬롯인데 f_target=0인 plan (렌더 안 함)
├ solve reject                             8    C1 3 / v_below_min 3 / d_occ_fail 2
└ render attempt                          75
   ├ usable 배달                          50
   └ render reject                        25
      ├ realize 실패(bounded_local_search_exhausted)  22   전부 controlled-occlusion
      ├ gate_fail:G1                                    2   context-rich
      └ gate_fail:G3                                    1   controlled-occlusion
records_rejected.jsonl 총 행                57 = 24 + 8 + 25       [확인] 전부 개별 보존됨
```

- `camera_distance_out_of_range` reject **0건**(9B 40k와 동일). 거리 상한은 sampling 단계에서 이미 닫힌다. [확인]
- 모드별 렌더 성공률:

```
mode                    render attempts   delivered   success
──────────────────────────────────────────────────────────────
clean-static                   10             10       100 %
cargo-only                     10             10       100 %
context-rich                   17             15        88 %
controlled-occlusion           38             15        39 %
```

배달된 50장의 mode 구성은 **처방 그대로** 10 / 10 / 15 / 15 다(슬롯이 stratum을 소유하는 Phase 7 설계가
의도대로 동작). 비용만 controlled 쪽으로 쏠렸다(38/75 = 전체 렌더 시도의 51 %). [확인]

### 2.1 controlled-occlusion side 구성비 — 처방 대비 실측

먼저 지시문의 전제를 정정한다. 처방은 **균등이 아니다**: `v2_pipeline.SIDE_WEIGHTS = [0.30, 0.30, 0.25, 0.15]`
(left / right / bottom / center). [확인]

```
side      처방     render 시도(n=38)   배달(n=15)     시도->배달 성공률
────────────────────────────────────────────────────────────────────────
left      0.30      14 (0.368)          7 (0.467)          50 %
right     0.30      11 (0.289)          6 (0.400)          55 %
bottom    0.25      12 (0.316)          2 (0.133)          17 %   *
center    0.15       1 (0.026)          0 (0.000)           0 %   *
```

**9C의 예측이 재현됐다.** bottom은 시도 단계에서는 처방(0.25)에 가까운 0.316을 유지하지만, realize 성공률
17 %(2/12) 때문에 배달셋에서 0.133으로 **거의 반토막**난다. 9C가 500셋에서 관측한 27 %보다 더 낮다(단
n=12 소표본, 95 % CI는 넓다). [확인]

center는 그보다 심하다 — **렌더 시도 단계에서 이미 0.026**이라 배달은 0건이다. 원인은 solve 단계에 있다:
`_occluder_lateral()`(v2_pipeline.py:994-1027)은 최대 30회 resample 루프 안에서 **매 시도마다 side를 다시
뽑고**, center는 "contained" 조건 때문에 depth가 방정식으로 고정돼 밴드 안에 안 들어가면 그냥 `continue`
한다. 즉 실패한 center 추첨은 solve reject로 기록되지 않고 조용히 다른 side로 대체된다. [확인]
그래서 `SIDE_WEIGHTS`는 "그리는 확률"이지 "얻는 비율"이 아니다.

**결과**: 학습셋에 하단 가림과 중앙(전면 포함) 가림 사례가 구조적으로 부족해진다. 40k에서 그대로 두면
bottom 실사례가 처방의 약 1/2, center는 거의 0이 된다. [추정 — 50장 표본을 40k로 외삽한 값]

---

## 3. 대표 프레임 (실제 프레임 인덱스)

이미지는 전부 직접 열어 확인했다. [확인]

```
분류            frame   근거 수치                                                     판정
────────────────────────────────────────────────────────────────────────────────────────────────
tiny            f0008   bbox min side 11.4 px, M0 550 px, dist 7.32 m, elev 2.96도    gate 전원 PASS인데
                        tiny_warning=TINY, elig 2/3/4cell 전부 NO                     학습 가치 의심
                f0024   14.4 px / 944 px      f0025 14.9 px / 1451 px
                f0047   11.9 px / 881 px      (tiny_warning 4/50 = 8 %)
high-noise      f0025   noise tier medium, gaussian sigma 5.44 (이번 셋 최대)
                f0018   medium, sigma 5.15    f0035 medium, sigma 4.89
                        ※ high tier는 0/50 (기대 1.5장)
dark            f0034   luma_pallet_final 16.35 (셋 최저), G5 임계 12.0 대비 여유 4.35
                f0030   16.39                 f0018 luma_frame_final 15.45 (프레임 최저)
ground-risk     f0033   floor edge margin 15.484 m (셋 최소), dist 9.737 m (셋 최대)
                        procedural_floor_edge_risk = 0/50, probe fail 0/550           위험 프레임 없음
PnP 발산        f0038   exact reproj 34.93 px, rot err 146도, elev 8.48도, vis kp 5
                f0049   exact reproj 30.61 px, rot err 160도, elev 4.60도, vis kp 5
bottom 가림     f0036   old_tyre, f_explicit 0.313, side target=actual=bottom          배달된 bottom 2장 중 1장
                f0039   f_explicit 0.072, f_total 0.270
```

**저앙각 프레임이 이번 셋의 공통 위험 인자**다 — elev < 5도 8장 / < 10도 17장(분모 50). tiny 4장 중 3장과
PnP 발산 2장이 모두 저앙각이다. [확인]

---

## 4. 산출물 인덱스

### 4.1 50-frame 전수 overlay + contact sheet (Phase 6)

- 개별: `data/pallet/_v2_smoke50_9d/eda_phase6/overlay_detailed/f0000.png` … `f0049.png` (50장)
- contact sheet: `data/pallet/_v2_smoke50_9d/eda_phase6/contact_sheets/detailed_001.png` … `detailed_005.png`
- manifest: `data/pallet/_v2_smoke50_9d/eda_phase6/overlay_manifest.json`
- 이번 렌더에서 `field absent`로 남은 패널 항목은 **단 1종**(`floor tex`, native floor 프레임 10장). Phase 1~5
  필드는 전부 실제 값으로 채워졌다 — 구 500셋에서 14종이 absent였던 것과 대조된다. [확인]

### 4.2 M0~M4 source-mask sheet (Phase 5)

- 대표: `reports/v2_revision/quality_smoke50/mask_integrity/mask_integrity_source_masks.png`
- 전수 3페이지: `data/pallet/_v2_smoke50_9d/eda/contact_sheets/mask_integrity_source_masks_001..003.png`
- 해시/중복/위반: `mask_hashes.csv`(250행) / `mask_duplicate_groups.json` /
  `mask_pixel_inclusion_failures.csv`(헤더만 — 위반 0)
- within-frame duplicate 분류: `expected_no_op` 50, `no_op_placed_but_not_occluding` 20,
  `unexpected_identical_stage` **0**, byte-exact **0**. [확인]

### 4.3 PnP (Phase 4)

- `reports/v2_revision/quality_smoke50/pnp/pnp_threshold_study.csv` (50행 × 101열)
- `.../pnp_threshold_study.md`, `.../pnp_stability_continuous.pdf`
- `.../pnp_eligibility_manifest.csv` + `.json` (`frames_deleted: 0`)

### 4.4 continuous EDA (Phase 8)

- 루트: `data/pallet/_v2_smoke50_9d/eda/paper_continuous/`
  (`figures_png/` 17 + `figures_pdf/` 17 + `continuous_metrics.csv` + `continuous_summary.json` +
  `discrete_counts.csv` + `paper_continuous_summary.md`)
- 입력 107행(frame 50 + rejected proposal 57), rendered 50.
- **required 13/13 전부 `status=ok`, missing 0** — 구 500셋에서 N/A였던 01(거리) / 05(final luma) /
  10(거리별 pass)이 이번엔 실제 곡선으로 나온다. Phase 1/3 필드가 record·label에 정상 배선됐다는 회귀 확인이다. [확인]
- PnP manifest join은 provenance 검사를 통과했다(`pnp_manifest_join_note: null`, 50/50 join).
  단 `pnp_threshold_study.csv`는 sibling JSON이 없어 **provenance 미검증 상태로 idx join**됐다고 기록돼 있다
  (`pnp_study_join_note`). 이번엔 같은 실행에서 만든 파일이므로 실질 위험은 없다. [확인]

**주의 — figure 10/11/12는 이 데이터셋에서 구조적으로 무정보다.** usable 셋은 정의상 전원 all-pass라
`all_pass` / `physical_valid` 곡선의 base rate가 **1.000**, LOO Brier 1.4e-32, `n_grid_points_reliable = 0`
(200 격자점 전부 n_eff<20)이다. pass-probability 곡선은 **실패가 포함된 records-mode 데이터셋**에서만
의미가 있다. figure 13(PnP eligibility)만 배달 조건이 아니라서 비퇴화 곡선이 나온다
(2cell base 0.909 / 3cell 0.773 / 4cell 0.727). [확인]

### 4.5 기타 수치

```
camera distance (m)    q05 1.16  q25 1.99  q50 3.44  q75 7.11  q95 9.33   (min 0.816 / max 9.737)
target vs actual       elevation MAE 0.0 · projected size MAE 0.195 · f_target->f_explicit MAE 0.053
zero-inflated P(X=0)   f_static 0.98 · f_cargo 0.62 · f_context 0.94 · f_explicit 0.70 · f_total 0.36
scene preset           outdoor-day 16 / random-mix 12 / indoor 11 / outdoor-night 11
```

---

## 5. noise tier — target vs 실측 (분모 50)

```
tier      target   기대 n   실측 n   two-sided exact p
──────────────────────────────────────────────────────
clean      0.60     30.0      26         0.252
low        0.25     12.5      19         0.048
medium     0.12      6.0       5         0.829
high       0.03      1.5       0         0.407
chi2 = 5.58 (df=3, 임계 .05 = 7.815) -> 처방과 불일치라고 말할 근거 없음
```

- low가 개별 p=0.048로 걸리지만 4개 동시비교라 다중성 보정 후 유의하지 않다. **quota를 강제하지 않았다**
  (지시문 그대로) — tier는 프레임마다 독립 추첨이다. [확인]
- **high tier 0장**은 정상 범위다(n=50에서 기대 1.5장, P(X=0)=0.22). 다만 이 표본으로는 high tier 경로가
  실제 렌더에서 동작하는지 **확인되지 않았다** — Phase 3의 1000-프레임 통계에서 21장 나온 것이 유일한 근거다. [확인]
- tier는 렌더 시도(75회)마다 뽑히고 배달 50장은 그 부분집합이다. 이번 실행에서 G5 탈락이 0건이므로
  tier→G5→배달 경로의 선택 편향은 발생하지 않았다. [확인]

---

## 6. Phase 1~8 변경 파일 목록

`_docs/history/2026-07-27.md` 기준 요약.

```
Phase  파일                                                        변경 요지
──────────────────────────────────────────────────────────────────────────────────────────────
1      scripts/data_prep/blender/v2_pipeline.py                    MAX_CAMERA_DISTANCE_M=10.0,
                                                                   feasible-interval 샘플링, _deficit_pick mask,
                                                                   solve_placement 방어 reject
1      scripts/data_prep/blender/v2_realize.py                     camera_distance_actual_m() + label 7필드
1      scripts/data_prep/blender/run_v2_scene_logic.py             record 7필드 배선
1      scripts/data_prep/blender/audit_v2_dryrun.py                신규 reject 사유
1      tests/test_camera_distance_cap.py                           신규 24
2      scripts/data_prep/blender/scene_placement_v2.py             ground probe 기하 (bpy-free)
2      scripts/data_prep/blender/scene_visibility_v2.py            check_ground_continuity()
2      v2_realize.py / run_v2_scene_logic.py / audit_v2_scene_logic.py   8지표 배선 + 감사
2      tests/test_ground_continuity.py                             신규 20
3      scripts/data_prep/blender/camera_effects.py                 전면 재작성(tier + 효과 dict, 레거시 bit-exact)
3      v2_realize.py                                               measure 분리, render profile 2종, G5 final luma
3      run_v2_scene_logic.py                                       호출 순서 변경, falsy-0 수정, CLI 3종
3      tests/test_camera_effects_tiers.py                          신규 16
4      scripts/data_prep/blender/audit_pnp_eligibility.py          신규 (~900줄)
4      tests/test_audit_pnp_eligibility.py                         신규 41
5      scripts/data_prep/blender/audit_v2_scene_logic.py           strict decode / pixel inclusion / hash / hull
5      tests/test_audit_v2_mask_integrity.py                       신규 40
6      scripts/data_prep/blender/overlay_v2_detailed.py            신규 (상세 패널 overlay + sheet)
6      tests/test_overlay_v2_detailed.py                           신규 46
7      run_v2_scene_logic.py                                       --completion-mode usable, records_rejected.jsonl,
                                                                   usable_conditions 19개, iter_proposals
7      tests/test_usable_completion_mode.py                        신규 26
8      scripts/data_prep/blender/analyze_v2_continuous.py          신규 (논문용 연속 EDA)
8      scripts/data_prep/blender/analyze_v2_scene_logic.py         falsy-0 15곳 수정
8      tests/test_analyze_v2_continuous.py                         신규 35
9B     scripts/data_prep/blender/dryrun_v2_proposals.py            신규 (bpy-free proposal dry-run)
```

`ORIENTATION_OVERRIDES`, keypoint convention, 레거시 production default, 레거시 드라이버 4종
(`_v2_pilot_2k.py` / `_b3_asset_check.py` / `_g5_reverify.py` / `_v2_calib_200.py`)은 **건드리지 않았다**. [확인]

---

## 7. 테스트 명령과 실제 결과 (9A~9D)

```
단계  명령                                                                     결과
────────────────────────────────────────────────────────────────────────────────────────────────
9A    pytest scripts/data_prep/blender/tests/ -q                               358 passed, 0 failed (78.4 s)
                                                                               (100k spec bulk draw 포함)
9B    python .../dryrun_v2_proposals.py --proposals 5000 --seed 7000            12/12 PASS, accept 88.78 %
      python .../dryrun_v2_proposals.py --proposals 40000 --seed 7000           12/12 PASS, accept 89.48 %
                                                                               max dist 9.99991 m, NaN 0,
                                                                               digest 066daafe45e60357... 재현
9C    blender -b ... --completion-mode records --n 20 --render-profile          결정성 축(3~6) 전부 PASS
      diagnostic-exact  (fresh 프로세스 2회, seed 7000)                         record 20/20 · label 18/18 ·
                                                                               RGB byte 18/18 · mask px 90/90
                                                                               mismatch 0
                                                                               조건 1'(20 rendered)/2(realize
                                                                               fail 0) FAIL -> 사용자 승인 하에
                                                                               예외 기록 후 9D 진행
9D    blender -b ... --completion-mode usable --n 50 --render-profile           delivered 50/50, 1925.7 s
      dataset-quality  (seed 7000)                                             17개 조건 전부 PASS (1절)
9D    python .../audit_v2_scene_logic.py --expected-frame-count 50              status=PASS, failures 0
9D    python .../audit_pnp_eligibility.py                                       exact success 50/50 (2건 발산)
9D    python .../overlay_v2_detailed.py                                         50 overlay + 5 sheet
9D    python .../analyze_v2_continuous.py                                       17 figure, required 13/13 ok
```

---

## 8. Section 10 — 6개 질문

### Q1. 무슨 문제를 고쳤나? (Phase 0 baseline의 6개 [확인]된 버그)

```
#  baseline 버그                                       조치                                        검증 근거
────────────────────────────────────────────────────────────────────────────────────────────────────────────
1  거리 상한 없음 (bin0 꼬리에서 최대 ~1000 m)         sample_frame에서 bin별 feasible interval     40k dry-run max 9.99991 m,
                                                       narrowing + solve_placement 방어 reject      9D 50장 max 9.737 m,
                                                                                                    out-of-range reject 0/40000
2  cam_distance_m가 record/label 미배선                7필드 배선(limit/target/actual/error +        9D 50/50 프레임에 값 존재,
                                                       projected_size feasible_lower/target/actual)  |actual-target| max 0.0000 m
3  G5/라벨 luma가 post-effect 이전 raw                 measure 분리 + 호출순서 변경,                 9D에서 raw != final 48/50,
                                                       G5가 luma_pallet_final 사용                   Phase 3에서 판정 뒤집힘 3건
4  mask 감사가 면적 단조성만 검사                      strict decode + pixel inclusion + sha256 2종  9D 50 프레임 위반 0 px,
                                                       + cross/within-frame duplicate 분류           duplicate 0, drifting fixture
                                                                                                    로 검출력 테스트 통과
5  EDA falsy-0 버그 (Fig.16/17/18 + azimuth/V/cross)   group_label / bin_or_numeric_fallback 15곳    500셋 재집계에서 Fig18 결론이
                                                                                                    뒤집힘(cargo off 0.698->0.905)
6  최소 projected-size 게이트 부재                     **게이트로 만들지 않았다.**                   9D 50장 중 tiny 4장(8 %)이
                                                       audit_pnp_eligibility가 tiny_warning /        gate 통과한 채 배달됨
                                                       pnp_size_eligible_2/3/4cell로 측정만          (f0008/f0024/f0025/f0047)
```

6번은 **의도적으로 미해결**이다 — Phase 4에서 threshold를 지목할 근거가 나오지 않았고(Q3 참조), 근거
없이 하드 임계를 박으면 데이터를 임의로 버리게 된다. 측정만 하고 판정은 미뤘다.

### Q2. 왜 이 방법인가?

- **거리 상한을 feasibility 샘플링으로**: 가장 쉬운 방법은 역산된 거리를 10 m로 클램프하는 것인데, 그러면
  `d = 10 m` 지점에 point mass가 생겨 처방 분포가 오염된다. 대신 `min_ratio_10m = fx*W_pallet/(W*10)`을
  구해 **각 projected-size bin의 하한을 밀어 올리고**, infeasible bin은 선택 확률 0으로 마스킹했다.
  quota-deficit이 마스킹 손실을 회수하는지가 관건이었는데, 40k에서 bin0는 draw의 68.98 %에서만 feasible한데도
  accepted marginal이 **0.2000(처방과 동일)**로 나왔다. 마스킹만 하는 sampler였다면 0.138로 주저앉는다. [확인]
- **final-RGB 기준 게이트**: 게이트가 본 픽셀과 학습이 보는 픽셀이 다르면 게이트는 학습에 대해 아무것도
  보장하지 못한다. vignette는 최대 -35 %라 임계 근처에서 실제로 판정이 뒤집힌다(Phase 3에서 3건 실측). [확인]
- **pixel-level mask inclusion**: 면적 단조성은 "M4 면적 <= M3 면적"만 본다. 인위적 fixture(면적은 단조인데
  사각형이 좌상단으로 흐르는 `drifting_masks`)에서 면적 검사는 통과하고 pixel 검사만 4쌍 전부 검출했다.
  즉 두 검사는 서로 다른 결함 클래스를 잡는다. [확인]
- **usable-count runner**: `--n`이 proposal 수였기 때문에 "N장짜리 셋"을 만들 방법이 없었다. 슬롯이
  stratum을 소유하게 해서 재시도 횟수와 무관하게 최종 구성비가 처방대로 나오게 했다
  (9D 실측 10/10/15/15 = 처방). reject는 전량 `records_rejected.jsonl`에 보존해 사후 추적 가능하게 했다. [확인]
- **overlay를 오른쪽 패널로**: 항목이 20 -> ~70개로 늘어 640x480 위에 얹으면 팔레트를 가린다.

### Q3. 거리·크기·노이즈·마스크 기준의 근거는?

- **10 m**: [확인] 사후 근거 — 구 500셋 435 rendered 중 72장이 10 m 초과(최대 1015.6 m)였고, plane 모드
  337장 중 16장(4.7 %)에서 지면 프로브가 50 m floor 밖으로 나갔다. 거리를 10 m로 제한하면 그 16장이
  **전부 사라지고** min edge margin이 +15.29 m가 된다. 즉 10 m는 "floor edge 노출이 사라지는 지점"이라는
  기하학적 근거가 있다. 9D 50장에서도 min margin 15.484 m로 재현됐다.
  단 **10.0이라는 정확한 값 자체는 라운드 넘버**다 — 12 m나 15 m가 왜 안 되는지에 대한 근거는 없다. [추정]
- **크기 임계**: belief map 1 cell = 원본 8 px([확인] — VGG19 트렁크 MaxPool 3개 + 학습 로더가 픽셀 등가
  `RandomCrop(400,400)`을 쓰므로 원본<->입력 스케일 변화 없음). 2/3/4 cell = 16/24/32 px.
  **최종 threshold는 확정하지 못했다**: 1~8 cell 스윕에서 accepted-set의 5cm-5도 실패율이 0.418->0.207로
  매끄럽게 단조 감소하고, 최대 단차가 중앙 단차의 1.20배(knee 기준 2.0배 미달)라 데이터가 특정 값을
  지목하지 않는다. 게다가 4cell 통과 집합조차 sigma=2px 실패율 0.293(435셋) / 0.354(50셋)이라
  "크기 통과 = PnP 신뢰"가 성립하지 않는다. [확인]
- **noise tier 확률 (.60/.25/.12/.03)**: `[미검증 시작값]`으로 명시돼 있고 지금도 그렇다. 실제 센서
  통계에서 온 값이 아니다. sigma 밴드를 서로 겹치지 않게 잡은 것(1-3 / 3-6 / 6-12)만 설계 근거가 있다 —
  `noise_tier` 라벨 하나로 프레임의 노이즈 영역을 식별할 수 있게 하기 위함. [확인]
- **mask pixel tolerance = 0**: 포함관계 위반은 **0 px 허용**이다. M4 ⊆ M0은 렌더 파이프라인의 정의상
  성립해야 하는 항등식이라 오차 허용 개념이 없다. 실측 위반도 0이다(50 프레임, 200 pair). [확인]
  반면 hull-outside 비율은 래스터화 오차가 원리상 존재하므로 hard fail로 만들지 않고 경고(0.20)로 뒀다.
- **ground step tolerance 0.05 m**: KS T-11 팔레트 높이 150 mm의 1/3, 기존 support contact tolerance
  (20 mm)의 2배 이상. procedural plane의 6 mm 오프셋은 통과하고 팔레트 스케일의 턱은 실패한다. [확인]

### Q4. 20 exact와 50 quality 결과가 설계를 지지하는가?

**부분적으로 지지한다.**

지지하는 것:
- 거리 상한: 9B 40k(target) 0 위반, 9C 20장(actual) max 9.328 m, 9D 50장 max 9.737 m — 세 층에서 일관. [확인]
- 결정성: 9C에서 record 20/20 · label 18/18 · RGB byte 18/18 · mask pixel 90/90 mismatch 0.
  realize 실패 위치·사유·수치까지 재현됐다. [확인]
- Phase 1~3 필드 배선: 9D의 continuous EDA에서 구 500셋이 N/A였던 figure 01/05/10이 실제 값으로 채워졌다. [확인]
- usable runner: 배달 50/50, id 0..49 연속, mode 구성비 처방 일치, reject 57건 전량 보존, 잔여 파일 0. [확인]
- mask/ground/collision/clearance: 50장 전원 통과, 위반 0. [확인]

지지하지 않는(또는 답하지 못하는) 것:
- **9C의 "20/20 rendered"는 실패했다.** 원인은 이번 변경이 아니라 기존 occluder 솔버의 구조적 실패율
  (500셋에서 controlled 42 % 실패)이며, 9D에서 61 %(23/38)로 **더 나쁘게 재현**됐다. [확인]
- **50장은 게이트 판별력을 검증하지 못한다.** 전원 all-pass라 pass-probability 곡선이 퇴화하고(4.4절),
  G5의 raw/final 차이도 임계를 가로지르지 않아 구분되지 않는다(1.1절).
- **PnP threshold는 여전히 확정 불가**이고, 50장에서는 크기 구간별 실패율 서열이 일부 뒤집혔다(1.3절).
- **exact-GT PnP가 2/50에서 발산**한다(1.2절). 이건 9C에서는 보이지 않던 새 관찰이다.

**판정: 이 50장 셋은 파이프라인 배관(배달·필드·무결성·재현성)이 동작한다는 것을 보인다.
training-ready라고 부를 수 없다** — 산출물 자체도 `delivery_level: "gate_valid (physical + G1..G5);
NOT final training-ready"`로 스스로 표기한다. [확인]

### Q5. 여전히 production을 막는 것은 무엇인가?

```
#   blocker                                                근거(분모 명시)                        영향
──────────────────────────────────────────────────────────────────────────────────────────────────────────
B1  controlled-occlusion realize 실패                      9D 23/38 시도 실패(61 %),              40k 예산의 절반이
    (bounded_local_search_exhausted)                       9C 2/2 실패, 500셋 63/150(42 %)        controlled에서 소모
B2  occluder side 편향: bottom 17 %(2/12), center 0 %(0/1) 9D 실측                                하단·중앙 가림 사례가
                                                                                                  학습셋에서 구조적 결손
B3  PnP threshold 확정 불가                                435셋 1~8cell 스윕 knee 1.20x          "training-ready" 정의를
                                                           (기준 2.0x), 4cell 통과집합도           내릴 수 없음
                                                           fail@2px 0.29~0.35
B4  exact-GT PnP 발산 2/50                                 f0038(146도) f0049(160도),             평면+저앙각+5 visible kp
    (EPnP + 평면 + 저앙각)                                 둘 다 elev<9도, vis kp 5               에서 GT조차 못 푼다
B5  projected_size_actual 과대추정                         9D 6/50(12 %) >1.0, max 2.62;          크기 기반 판정·EDA의
                                                           500셋 87/435(20 %), max 39.09           x축이 오염
B6  tiny 프레임이 gate를 통과해 배달됨                     9D 4/50(8 %) tiny_warning,             학습셋에 무의미 프레임
                                                           2cell 미달 4/50                         혼입
B7  noise tier 확률이 [미검증 시작값]                      high tier 0/50 관측                    센서 현실성 미검증
B8  dataset-quality는 byte 재현성 없음                     GPU+adaptive+OIDN                      감사에서 RGB sha 비교 불가
                                                                                                  (설계상 의도, 기록용)
B9  usable 셋으로는 게이트 판별력 측정 불가                figure 10/11/12 base rate 1.000,       게이트 튜닝은
                                                           n_grid_points_reliable 0/200            records-mode 셋 필요
B10 f_static은 배치 카운터가 없다                          면적 유래 값만 존재                    static 가림 주장을
                                                                                                  mask로 반증 불가
B11 40k 규모 감사 비용                                     435프레임 mask 감사 1분 36초,          전수 감사 2시간+,
                                                           overlay 500장 3분                       overlay 전수 4시간
```

### Q6. 다음 500 pilot에서 무엇을 검증해야 하는가?

1. **B1/B2 정량화**: `--completion-mode records`로 (usable이 아니라) 500 proposal을 돌려
   controlled-occlusion side별 realize 성공률의 95 % CI를 구한다. bottom n>=50, center n>=30을 확보해야
   9D의 n=12/n=1 표본을 넘어선다. 그 다음에 solver 예산·수용 기준 수정 여부를 결정한다.
2. **게이트 판별력**: records-mode 500셋(실패 포함)으로 figure 10/11/12의 pass-probability 곡선을
   비퇴화 상태로 다시 그린다. usable 셋으로는 원리상 불가능하다(4.4절).
3. **B4 재현율**: 저앙각(elev<10도) x visible kp 5 조합의 exact-GT PnP 발산율을 500장에서 센다.
   9D는 2/50이지만 해당 조합의 조건부 분모는 작다. 발산율이 유의하면 (a) 저앙각 quota 조정 또는
   (b) 라벨에 `pnp_degenerate` 플래그 추가를 검토한다. **평가 코드의 solver는 바꾸지 않는다.**
4. **B5 수정 검증**: `projected_size_actual`을 화면 클리핑 후 계산하도록 고치고, >1.0 비율이
   12 %(9D) / 20 %(500셋)에서 0으로 떨어지는지 확인한다.
5. **B3 재스윕**: 500장(9D의 10배)에서 1~8 cell 스윕을 다시 돌려 knee가 나타나는지 본다. 이번에도
   단조 감소만 나오면 "크기 단일 임계"를 포기하고 `tiny_warning` + `pnp_stress` 2축을 유지한다는 결론을 확정한다.
6. **B7**: high tier 프레임이 실제로 렌더되는지(기대 15장/500) 확인하고 sigma 밴드·JPEG q 실측이
   `NOISE_TIER_PARAMS`와 일치하는지 대조한다.
7. **G5 임계 재검토**: final luma 분포를 500장에서 보고 임계 12.0의 위치를 정한다. 9D 50장은
   최소 16.35라 임계를 논할 표본이 아니다.
8. **비용 측정**: 500장 usable 소요 시간과 감사·overlay 시간을 실측해 40k 예산을 산정한다
   (9D 선형 외삽은 5.3시간/40k지만 controlled 비중과 GPU 상태에 좌우된다 [추정]).

---

## 9. 이 문서에서 쓰지 않은 표현

- "500개 완료" 류의 표현은 쓰지 않았다. **이번 산출물은 usable RGB 50장**이다.
- baseline 2k / 구 500-record와 이번 50장의 비교는 **descriptive**로만 적었다. proposal 스트림·acceptance
  경로·render profile이 전부 다르므로 causal improvement가 아니다.
- "training-ready"는 쓰지 않았다. 산출물의 `delivery_level`도 `gate_valid ... NOT final training-ready`다.
