# Blender v2 scene logic 500-record EDA 결과 해석

작성일: 2026-07-27  
대상 산출물: `data/pallet/_v2_scene_logic_500_seed7500/eda`

문서 상태: **진단 결과 보고서 — 40k 본렌더 승인 문서가 아님**

관련 기록:

- 최종 구현·검증 요약: [2026-07-26.md](../history/2026-07-26.md)
- 133개 보존 실행의 전체 시행착오: [2026-07-26-v2-attempt-log.md](../history/2026-07-26-v2-attempt-log.md)
- EDA 산출물 인덱스: [EDA README](../../data/pallet/_v2_scene_logic_500_seed7500/eda/README.md)

## 목적

[확인] 이 문서는 500-record Blender v2 scene logic 진단 산출물의 차트, 표, 이미지 감사 결과를 글로 해석한 보고서다. 목적은 “40k 본렌더로 진행해도 되는가”, “어떤 sampler/validator를 먼저 고쳐야 하는가”, “논문/공개 데이터 설명에서 어떤 수치를 주장할 수 있는가”를 분리해서 판단하는 것이다.

## 입력 산출물

[확인] 원본 데이터와 분석 산출물은 아래 파일에서 직접 확인했다.

- `data/pallet/_v2_scene_logic_500_seed7500/eda/summary.json`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/baseline_vs_new.json`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/frame_metrics.csv`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/reject_reasons.csv`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/audit_summary.json`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/audit_frames.csv`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/manual_audit/audit_000_499_summary.md`
- `data/pallet/_v2_scene_logic_500_seed7500/eda/charts/*.png`

## 결론 요약

[확인] 새 500-record 진단의 **렌더된 부분집합**에서는 이전 2k pilot보다 낮은 gate fail rate가 관측됐다. baseline 2k의 rendered 기준 all-pass는 800/2000=40.00%였고, 새 진단의 rendered 기준 all-pass는 364/435=83.68%다.

[판정] 이 차이는 causal ablation 결과가 아니다. 두 실행은 runner, diagnostic mode 배정, proposal 분포, constrained acceptance, 렌더 전 fail-closed 동작이 다르다. 따라서 “v2 로직 때문에 성능이 43.68%p 향상됐다”가 아니라 “새 진단에서 실현된 435장 중 gate 통과율이 더 높게 관측됐다”고만 써야 한다.

[확인] 하지만 전체 record 기준으로는 364/500=72.80%다. 차이는 65개가 렌더되지 않았기 때문이다. 이 65개 중 62개는 controlled-occlusion bounded search exhaustion, 3개는 anchor reject다.

[판정] 따라서 현재 상태는 “scene logic이 연구용 진단 단계에서는 유효하고, fatal defect는 0에 가깝게 통제되었지만, 40k production default로 켜기에는 아직 controlled-occlusion delivery와 tiny-target 문제가 남아 있음”이다.

핵심 수치:

```text
항목                                      값
전체 record                              500
렌더 성공                                435 / 500 = 87.00%
렌더 실패 / realize fail                 65 / 500 = 13.00%
렌더 기준 G1-G5 all-pass                 364 / 435 = 83.68%
전체 record 기준 all-pass                364 / 500 = 72.80%
automated audit pass                     493 / 500
automated audit fail                       7 / 500
fatal visual defect                      0
strict RGB decode failure                0
magenta / corrupt RGB / corrupt mask     0 / 0 / 0
empty target mask                        4
exact BVH collision count                0 / 497 evaluated
```

## 분모 해석 규칙

[확인] 이 EDA는 차트마다 분모가 다르다. 아래 구분 없이 수치를 섞으면 잘못된 결론이 나온다.

```text
분모 종류                    사용 위치 / 의미
전체 record n=500            mode별 all-pass, reject reason, camera prescription
렌더 성공 n=435              G1-G5 gate fail rate, RGB/label/mask 기반 품질
metric valid n               f_static/f_cargo/f_context 등 empty mask 때문에 NaN이 빠진 수치
controlled 전체 n=150        target bin / actual bin chart에서 missing actual 포함
controlled rendered n=87     실제 explicit occluder가 렌더되어 전달된 프레임
manual audit n=500           overlay 또는 diagnostic placeholder 포함 전수 시각 감사
```

[판정] 논문 또는 공개 데이터셋 문서에서 all-pass를 말할 때는 `rendered conditional all-pass`와 `proposal/record all-pass`를 반드시 분리해야 한다.

## 결과 서사 구조

### 1. 이전 2k pilot보다 rendered subset의 gate fail rate가 낮게 관측됨

[확인] baseline 2k 대비 새 500-record 진단은 G1, G2, G3, G5 실패율이 모두 감소했다.

```text
gate    baseline 2k fail         new 500 rendered fail
G1      875/2000 = 43.75%        44/435 = 10.11%
G2      393/2000 = 19.65%        0/435 = 0.00%
G3      635/2000 = 31.75%        10/435 = 2.30%
G4      14/2000 = 0.70%          1/435 = 0.23%
G5      210/2000 = 10.50%        19/435 = 4.37%
```

[판정] 렌더된 435장에서는 G2 실패가 없었다. 다만 controlled proposal 63개가 렌더 전에 탈락했으므로, 이 결과만으로 proposal-level 외부 가림 contract가 완전히 해결됐다고 주장할 수는 없다.

### 2. source-decomposed occlusion은 의도대로 분리됨

[확인] clean-static에서 `f_static`은 사실상 0이고, cargo-only에서는 `f_cargo`, context-rich에서는 `f_context`, controlled-occlusion에서는 `f_explicit`이 주로 움직인다.

```text
mode                    n(valid)   mean f_static   mean f_cargo   mean f_context   mean f_explicit
cargo-only              100        ~0.0000008      0.1119         0.0000           0.0000
clean-static             99        ~0.0000001      0.0000         0.0000           0.0000
context-rich            145        ~0.0000007      0.0555         0.0117           0.0000
controlled-occlusion     87        ~0.0000001      0.0527         0.0005           0.2123
```

[판정] 이전 문제였던 “배경/화물/명시적 occluder가 한 가림값에 섞이는 문제”는 이번 진단 산출물에서는 상당히 분리되어 있다.

### 3. controlled occlusion은 렌더된 경우에는 전달되지만 proposal delivery가 낮음

[확인] controlled-occlusion은 전체 150개 target 중 87개만 렌더됐다. 렌더된 87개에서는 explicit occluder visible count가 87/87이고, target side와 actual side가 모두 일치했다.

[확인] 그러나 전체 target 기준으로는 visible delivery가 87/150=58.00%다. 실패 63개 중 62개는 bounded local search exhaustion이고 1개는 anchor_fail이다.

```text
controlled-occlusion 전체 target       150
controlled-occlusion 렌더 성공          87
controlled-occlusion all-pass           77
bounded search exhaustion               62
anchor fail                              1
rendered 기준 explicit abs error q50    0.0382
rendered 기준 explicit abs error q90    0.1031
rendered 기준 explicit abs error q95    0.1111
center actual count                      3 / 87 = 3.45%
```

[판정] solver는 성공한 장면에서는 꽤 정확하지만, 어려운 controlled target을 fail-closed로 버리는 비율이 높다. production 40k에서 controlled 비중을 그대로 유지하면 렌더 낭비가 커진다.

### 4. 물리/파일 fatal defect는 통제됨

[확인] automated audit 기준 fatal defect는 0이다. RGB decode fail, magenta, missing texture suspect, mask monotonic fail, evaluated exact collision, support fail 모두 0이다.

[확인] 남은 audit fail 7개는 empty target mask 4개와 anchor reject placeholder 3개다.

```text
audit failure type      count
empty_target_mask       4
anchor_reject           3
fatal_failure           0
```

[판정] 데이터 파일 무결성 측면에서는 이전 magenta/corrupt/missing-texture 문제보다 훨씬 안정적이다.

### 5. 작은 물체와 큰 projected-size bin이 별도 문제로 남음

[확인] projected-size target bin 4는 all-pass가 56/95=58.95%로 가장 낮다. 반대로 작은 projected-size target bin 0,1은 all-pass가 높지만, manual audit에서는 G1-G5 accepted 중 12개가 M0 mask area 100px 미만이라 supervision으로 부적절하다고 수동 reject됐다.

[판정] “all-pass가 높다”와 “학습에 유효하다”는 같은 말이 아니다. production manifest에는 architecture-derived minimum target size 또는 별도 `tiny_warning/reject` policy가 필요하다.

### 6. 생성 비용은 controlled/context에서 병목이 남음

[확인] 전체 runtime median은 25.64초, q90은 56.35초, q95는 64.48초다. mode별 median runtime은 clean-static 13.69초, cargo-only 18.16초, context-rich 26.11초, controlled-occlusion 46.64초다.

[판정] 40k로 확대하기 전에 controlled solver의 bounded-search 실패율과 runtime을 줄여야 한다. 그렇지 않으면 “렌더 성공률”보다 “proposal 소모와 시간”이 병목이 된다.

## 핵심 차트 미리보기

![Baseline 2k와 새 진단의 gate fail rate](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/01_baseline_2k_vs_new_500_gate_fail_rate.png)

*그림 C1. 이전 2k pilot과 새 진단의 rendered-frame gate fail rate. 표본수는 각각 2,000과 435이며, 새 진단의 렌더 전 실패 65개는 포함되지 않는다. 두 실행의 proposal/acceptance 경로가 달라 이 비교는 descriptive diagnostic이지 causal ablation이 아니다.*

![Diagnostic mode별 proposal all-pass](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/02_all_pass_rate_by_diagnostic_mode.png)

*그림 C2. 전체 proposal을 분모로 한 mode별 all-pass. controlled-occlusion의 0.513은 77/150이며, 렌더된 87장만 분모로 하면 77/87=0.885다. 이 그림은 품질과 proposal delivery를 함께 반영한다.*

![Mode별 source-decomposed occlusion 평균](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/03_occlusion_source_stacked_contribution_by_mode.png)

*그림 C3. mode별 static, cargo, context, explicit 가림 기여의 평균. 역할별 주 가림원이 의도한 source에 대체로 대응하지만, 평균값이고 M0가 비어 metric을 계산할 수 없는 row는 제외된다. 분해량은 M0→M4 순서에 의존한다.*

![Controlled target과 actual explicit occlusion](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/07_controlled_occlusion_f_target_vs_f_explicit.png)

*그림 C4. target과 actual 값이 모두 존재하는 controlled rendered 87장의 scatter. 성공한 placement의 정밀도를 보여주지만, 렌더 전에 실패한 controlled target 63개는 점으로 나타나지 않는다.*

![앞면과 포크 개구부 가시성](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/19_front_opening_visibility_distributions.png)

*그림 C5. rendered valid row의 camera-facing 앞면 및 좌·우 포크 개구부 가시성 분포. 대부분 1.0 부근이지만 `<0.5` 사례가 front 29, left 39, right 44건 존재해 alignment eligibility를 G1-G5와 별도로 관리해야 한다.*

![파일 및 mask 결함 수](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/22_magenta_corrupt_empty_mask_counts.png)

*그림 C6. 전체 500 record의 결함 집계. strict magenta, corrupt RGB, corrupt mask는 0건이며 empty target mask는 4건이다. non-rendered 65건은 corrupt RGB가 아니라 RGB 파일이 생성되지 않은 reject record다.*

## 22개 차트별 해석

### Fig. 01 — Baseline 2k vs New 500 Gate Fail Rate

파일: [01_baseline_2k_vs_new_500_gate_fail_rate.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/01_baseline_2k_vs_new_500_gate_fail_rate.png)

[확인] 표본수는 baseline rendered n=2000, new rendered n=435다. baseline all-pass는 40.00%, new rendered all-pass는 83.68%다.

핵심 결과:

```text
G1 fail: 43.75% -> 10.11%
G2 fail: 19.65% -> 0.00%
G3 fail: 31.75% -> 2.30%
G4 fail: 0.70%  -> 0.23%
G5 fail: 10.50% -> 4.37%
```

과해석 금지:

- [확인] new의 gate fail rate는 렌더 성공 435장 기준이다. 65개 realize fail은 이 차트의 gate fail rate에는 들어가지 않는다.
- [판정] 따라서 “전체 proposal 성공률”을 말하려면 364/500=72.80%를 함께 적어야 한다.
- [판정] 두 실행은 동일 proposal 분포와 동일 acceptance 경로를 공유하지 않으므로, 이 그림은 causal improvement나 공정한 ablation을 증명하지 않는다.

### Fig. 02 — All-pass Rate by Diagnostic Mode

파일: [02_all_pass_rate_by_diagnostic_mode.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/02_all_pass_rate_by_diagnostic_mode.png)

[확인] 이 차트는 전체 row를 mode별 분모로 사용한다.

```text
mode                    frames   rendered   all-pass   all-pass / frames   all-pass / rendered
clean-static            100      100        92         92.00%              92.00%
cargo-only              100      100        85         85.00%              85.00%
context-rich            150      148        110        73.33%              74.32%
controlled-occlusion    150       87         77        51.33%              88.51%
```

핵심 결과:

- [확인] clean-static과 cargo-only는 렌더 실패가 없다.
- [확인] controlled-occlusion은 렌더된 경우 all-pass가 높지만, 전체 target 기준 all-pass는 51.33%까지 내려간다.

과해석 금지:

- [판정] controlled-occlusion의 51.33%는 렌더 품질이 나빠서라기보다 solver가 fail-closed로 렌더 전 중단한 영향이 크다.

### Fig. 03 — Occlusion Source Contribution by Mode

파일: [03_occlusion_source_stacked_contribution_by_mode.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/03_occlusion_source_stacked_contribution_by_mode.png)

[확인] mode별 valid numeric row에서 source별 평균 가림률을 그린 차트다.

핵심 결과:

- clean-static: `f_static` mean이 거의 0이다.
- cargo-only: `f_cargo` mean 0.1119가 주 가림원이다.
- context-rich: `f_context` mean은 0.0117이고, cargo가 켜진 row에서는 `f_cargo` 영향이 더 크다.
- controlled-occlusion: `f_explicit` mean 0.2123이 주 가림원이다.

과해석 금지:

- [확인] empty target mask 4개는 source metric이 NaN이라 source 평균에서 빠진다.
- [판정] stacked mean은 “평균 기여”이지, 개별 프레임의 occlusion contract 충족을 보장하지 않는다.

### Fig. 04 — Clean-static f_static Histogram

파일: [04_clean_static_f_static_histogram.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/04_clean_static_f_static_histogram.png)

[확인] clean-static은 100장 렌더됐고, `f_static` valid n=99다. 1장은 empty target mask로 metric이 NaN이다.

핵심 결과:

```text
f_static q50 = 0.0
f_static q90 = 0.0
f_static q95 = 0.0
f_static max = 0.0000058
f_static >= 0.35 count = 0
```

[판정] static background가 우연히 pallet을 크게 가리던 이전 문제는 이 smoke에서는 재현되지 않았다.

과해석 금지:

- [추정] industrial/parking_lot 중심의 제한된 배경 조합에서는 안정적이라는 뜻이다. 더 많은 배경 glTF를 추가하면 anchor cache와 static LOS 검증을 다시 해야 한다.

### Fig. 05 — Cargo-only f_cargo Histogram

파일: [05_cargo_only_f_cargo_histogram.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/05_cargo_only_f_cargo_histogram.png)

[확인] cargo-only rendered n=100이며 모두 `cargo_on=True`다.

핵심 결과:

```text
f_cargo mean = 0.1119
f_cargo q50  = 0.1208
f_cargo q90  = 0.2219
f_cargo q95  = 0.2395
f_cargo max  = 0.2465
```

[판정] cargo 가림은 이전처럼 평균 0.35 수준으로 과하게 지배하지 않고, 대체로 25% 미만으로 제한됐다.

과해석 금지:

- [확인] cargo-only의 all-pass는 85/100이다. `f_cargo`가 낮아졌다는 것과 corner visibility 문제가 완전히 해결됐다는 것은 다르다.

### Fig. 06 — Context-rich f_context Histogram

파일: [06_context_rich_f_context_histogram.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/06_context_rich_f_context_histogram.png)

[확인] context-rich는 150 target, 148 rendered, `f_context` valid n=145다. 3개 rendered row는 empty target mask로 source metric이 NaN이다.

핵심 결과:

```text
f_context mean = 0.0117
f_context q50  = 0.0000
f_context q90  = 0.0621
f_context q95  = 0.0831
f_context max  = 0.1197
```

[판정] context object는 화면에는 많이 보일 수 있지만, pallet target mask를 크게 가리는 빈도는 낮게 유지됐다.

과해석 금지:

- [확인] context-rich의 G1 fail은 여전히 존재한다. 낮은 `f_context` 평균은 모든 context object가 학습에 무해하다는 뜻이 아니다.

### Fig. 07 — Controlled-occlusion f_target vs f_explicit

파일: [07_controlled_occlusion_f_target_vs_f_explicit.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/07_controlled_occlusion_f_target_vs_f_explicit.png)

[확인] scatter에 들어간 point는 `f_target`과 `f_explicit`이 모두 있는 controlled rendered n=87이다.

핵심 결과:

- [확인] explicit occluder가 렌더된 87장에서는 모두 visible pixel이 0보다 크다.
- [확인] rendered 기준 explicit abs error는 q50=0.0382, q90=0.1031, q95=0.1111이다.
- [확인] `f_explicit` mean은 0.2123, q50은 0.1757이다.

과해석 금지:

- [판정] 이 scatter만 보면 성공한 case만 보게 된다. 실패한 63 controlled targets는 chart 8~10의 missing/low bin과 reject reason에서 같이 봐야 한다.

### Fig. 08 — f_target Bin vs f_explicit Actual Bin

파일: [08_f_target_bin_vs_f_explicit_actual_bin.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/08_f_target_bin_vs_f_explicit_actual_bin.png)

[확인] 이 heatmap은 controlled 전체 n=150을 사용한다. fail-closed row는 actual bin이 낮거나 missing으로 남는다.

전체 controlled 기준:

```text
target bin  actual 0   actual 1   actual 2   actual 3   missing
1           36         21         4          0          0
2           24          9        14          3          0
3           18          0         9         11          1
```

rendered-only 기준:

```text
target bin  actual 0   actual 1   actual 2   actual 3
1           16         21         4          0
2            0          9        14          3
3            0          0         9         11
```

[판정] 성공한 controlled render에서는 bin delivery가 어느 정도 따라오지만, 전체 target 기준에서는 bounded-search 실패가 actual low/missing으로 남아 target distribution을 깎는다.

과해석 금지:

- [확인] 이 heatmap의 off-diagonal은 모두 occluder placement 오차만 의미하지 않는다. 렌더 전 실패와 missing actual도 섞여 있다.

### Fig. 09 — Explicit Absolute Error Histogram and Quantiles

파일: [09_explicit_abs_error_histogram_quantiles.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/09_explicit_abs_error_histogram_quantiles.png)

[확인] chart 09의 `explicit_abs_error` valid n은 controlled 전체 기준 149다. 이 경우 q50=0.0984, q90=0.3682, q95=0.3931이다.

[확인] 별도 summary의 controlled rendered-only error는 n=87, q50=0.0382, q90=0.1031, q95=0.1111이다.

[판정] 두 수치는 서로 다른 질문에 답한다.

```text
전체 controlled target error     proposal delivery 포함
rendered-only error              solver가 성공한 장면의 occlusion 정밀도
```

과해석 금지:

- [판정] chart 09만 보고 “explicit solver 오차 q95가 39%p”라고 쓰면 너무 비관적이다. 반대로 rendered-only q95만 쓰면 fail-closed delivery 문제를 숨긴다.

### Fig. 10 — Occluder Side Target vs Actual

파일: [10_occluder_side_target_vs_actual.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/10_occluder_side_target_vs_actual.png)

[확인] controlled 전체 n=150 기준 target-vs-actual side crosstab이다. actual side가 missing인 row는 대부분 렌더 실패다.

전체 controlled 기준:

```text
target    actual missing   bottom   center   left   right
bottom    24               9        0        0      0
center     3               0        3        0      0
left      19               0        0       32      0
right     16               0        0        0     43
missing    1               0        0        0      0
```

rendered-only 기준:

```text
bottom 9/9 matched
center 3/3 matched
left   32/32 matched
right  43/43 matched
```

[판정] side classification itself is stable once rendered. 실제 문제는 center/side mismatch가 아니라 center sample 수와 proposal delivery다.

과해석 금지:

- [확인] center actual은 3/87=3.45%뿐이다. “center occlusion도 충분히 커버했다”고 주장하면 안 된다.

### Fig. 11 — Anchor Reject Reason Distribution

파일: [11_anchor_reject_reason_distribution.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/11_anchor_reject_reason_distribution.png)

[확인] 전체 500 record 중 anchor reject reason은 대부분 missing이고, 실제 anchor_fail은 3개다.

```text
missing          497
static_los         2
camera_clearance   1
```

[판정] anchor solver는 이번 smoke에서 거의 안정적이다.

과해석 금지:

- [확인] `missing=497`은 결측 문제가 아니라 “anchor reject가 없었다”는 의미로 해석해야 한다.

### Fig. 12 — Collision Reject Reason Distribution

파일: [12_collision_reject_reason_distribution.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/12_collision_reject_reason_distribution.png)

[확인] `collision_reject_reason`은 500개 모두 missing이다. `exact_collision_count`가 평가된 497개 record의 sum/max는 0/0이고, anchor 단계에서 탈락한 3개는 exact collision 미측정이다.

[판정] exact BVH가 평가된 최종 scene에는 collision이 기록되지 않았다.

과해석 금지:

- [확인] 이 차트는 “후보 placement 중 collision으로 reject된 시도 수”를 보여주지 않는다. 최종 record의 reject reason과 audit field만 보여준다.

### Fig. 13 — Context Object Count vs Screen Area

파일: [13_context_object_count_vs_screen_area.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/13_context_object_count_vs_screen_area.png)

[확인] chart 13은 전체 rows를 사용하고, `n_context_visible`과 `context_screen_area_ratio`를 diagnostic mode 색상으로 표시한다.

context-rich rendered n=148 기준:

```text
n_context_visible   count   screen_area mean   screen_area median
0                   27      0.0000             0.0000
1                    7      0.2093             0.2154
2                   16      0.2490             0.2177
3                   98      0.1652             0.1440
```

[확인] context-rich에서 `n_context_visible`과 `context_screen_area_ratio`의 상관은 약 0.37이다.

과해석 금지:

- [판정] visible object count가 많다고 화면 점유율이 항상 커지는 것은 아니다. object scale, depth, crop 위치가 같이 작용한다.

### Fig. 14 — Context Screen Area vs f_context

파일: [14_context_screen_area_vs_f_context.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/14_context_screen_area_vs_f_context.png)

[확인] context-rich rendered subset에서 `context_screen_area_ratio`와 `f_context`의 상관은 약 0.214다.

핵심 결과:

- [확인] context object가 화면에 보여도 target mask와 많이 겹치지 않는 경우가 많다.
- [확인] context-rich `f_context` q95는 0.0831, max는 0.1197이다.

과해석 금지:

- [판정] 화면 복잡도와 target occlusion은 다른 축이다. dense-looking scene을 만들려면 context screen area를, occlusion 난이도를 만들려면 `f_context` 또는 explicit occluder를 따로 제어해야 한다.

### Fig. 15 — G1/G3 Fail Rate by Occlusion Source

파일: [15_g1_g3_fail_rate_by_occlusion_source.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/15_g1_g3_fail_rate_by_occlusion_source.png)

[확인] dominant source별 전체 row 기준 실패율이다.

```text
dominant source   n    G1 fail       G3 fail
missing           69   0 / 69        4 / 69 = 5.80%
f_cargo          140   28 / 140=20%  0 / 140
f_context         23   5 / 23=21.7%  0 / 23
f_explicit        77   0 / 77        6 / 77=7.79%
f_static           4   0 / 4         0 / 4
none             187   11 / 187=5.88% 0 / 187
```

[판정] G1 실패는 주로 cargo/context 쪽에서, G3 실패는 explicit 또는 missing/empty-mask 쪽에서 나타난다.

과해석 금지:

- [확인] dominant source는 가장 큰 source만 고른 단순 집계다. 여러 source가 동시에 작용하는 row의 인과를 완전히 분해하지 않는다.

### Fig. 16 — All-pass by Elevation Bin

파일: [16_all_pass_by_elevation_bin.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/16_all_pass_by_elevation_bin.png)

[확인] **현재 PNG는 정량 주장에 사용하면 안 된다.** `analyze_v2_scene_logic.py:1856`의 `r.get("elev_bin_target") or ...`에서 정수 bin `0`이 falsy로 처리되고, bin field가 없는 non-rendered row는 별도의 문자열 bin으로 다시 계산된다. 그 결과 그림 안에 숫자 `1..6`과 `elev [...]` 문자열 범주가 동시에 생겼다.

[확인] 아래 표는 PNG의 막대값이 아니라 `frame_metrics.csv`에서 `elev_bin_target`이 실제로 기록된 rendered 435장만 다시 집계한 교정표다.

```text
elev_bin   각도 범위       rendered   all-pass   rate
0          0.5-3°          38         32         84.21%
1          3-8°            74         59         79.73%
2          8-15°           86         73         84.88%
3          15-25°          77         63         81.82%
4          25-40°          75         63         84.00%
5          40-60°          44         37         84.09%
6          60-80°          41         37         90.24%
합계                         435        364        83.68%
```

[판정] 교정표의 rendered subset에서는 특정 elevation bin만 크게 붕괴하는 패턴은 보이지 않는다. 그러나 렌더 전에 탈락한 65개의 bin field가 비어 있으므로 proposal-level elevation delivery를 이 표로 평가할 수는 없다.

과해석 금지:

- [확인] 표본수는 bin별 38~86으로 작다. paper_s2 real 3~8도 회귀 같은 downstream 성능 결론을 이 차트만으로 내릴 수 없다.
- [확인] PNG를 논문이나 README에 넣기 전에 bin 0 처리와 non-rendered bin 보존을 수정하고 재생성해야 한다.

### Fig. 17 — All-pass by Projected-size Bin

파일: [17_all_pass_by_projected_size_bin.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/17_all_pass_by_projected_size_bin.png)

[확인] **현재 PNG는 정량 주장에 사용하면 안 된다.** Fig. 16과 같은 `or` fallback 문제가 `analyze_v2_scene_logic.py:1865`에 있어 숫자 bin과 문자열 fallback bin이 한 축에 섞였다.

[확인] 아래 표는 `frame_metrics.csv`에서 `proj_size_bin_target`이 기록된 rendered 435장만 다시 집계한 교정표다.

```text
size_bin   target 범위       rendered   all-pass   rate
0          0.00-0.10        88         80         90.91%
1          0.10-0.20        86         80         93.02%
2          0.20-0.40        81         76         93.83%
3          0.40-0.60        85         72         84.71%
4          0.60-1.00        95         56         58.95%
합계                         435        364        83.68%
```

[판정] rendered subset에서는 큰 projected-size target bin에서 all-pass율이 낮다. 이는 large/truncated/near-camera geometry와 gate failure가 연관된다는 진단 신호이며, 단독 인과효과는 아니다.

과해석 금지:

- [확인] 작은 bin의 all-pass가 높아도 manual audit에서는 accepted extreme-small 12건과 very-small warning 39건이 있었다. 작은 물체 유효성은 G1-G5와 별도 기준이다.
- [확인] PNG를 논문이나 README에 넣기 전에 bin 처리 오류를 수정해 재생성해야 한다.

### Fig. 18 — All-pass by Cargo On

파일: [18_all_pass_by_cargo_on.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/18_all_pass_by_cargo_on.png)

[확인] **현재 PNG의 `(missing)` 막대는 cargo-off를 뜻하지 않는다.** `analyze_v2_scene_logic.py:1609`의 `r.get(group_key) or "(missing)"`가 Boolean `False`를 missing으로 바꾸고, 실제 non-rendered missing 65개와 같은 그룹에 합친다. 따라서 그림의 `(missing)=0.698`은 `199/(cargo-off 220 + non-rendered 65)`로 계산된 혼합값이다.

[확인] 아래 표는 rendered 435장만 `cargo_on`의 실제 Boolean 값으로 다시 집계한 교정표다.

```text
cargo_on   rendered   all-pass   rate
False      220        199        90.45%
True       215        165        76.74%
합계       435        364        83.68%
```

[판정] rendered subset에서 cargo-on과 낮은 all-pass가 연관되어 있다. mode, occlusion, projected size 등 다른 변수가 함께 달라질 수 있으므로 cargo의 독립적인 인과효과로 해석하면 안 된다.

과해석 금지:

- [확인] 현재 PNG는 `False`와 `missing`을 구분하도록 analyzer를 수정하기 전까지 사용하지 않는다.

### Fig. 19 — Front and Opening Visibility Distributions

파일: [19_front_opening_visibility_distributions.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/19_front_opening_visibility_distributions.png)

[확인] visibility metric valid n은 front 415, left opening 414, right opening 414다.

```text
metric                     mean    q50   q90   q95   count < 0.5
front_face_visibility      0.8947  1.0   1.0   1.0   29
left_opening_visibility    0.9050  1.0   1.0   1.0   39
right_opening_visibility   0.9007  1.0   1.0   1.0   44
```

[판정] 대부분은 front/opening visibility가 높지만, alignment-eligible manifest를 만들려면 `<0.5` row를 별도로 제외하거나 태그해야 한다.

과해석 금지:

- [확인] 이 visibility는 rendered/valid row 기준이다. empty target mask와 non-rendered row는 이 분포에서 빠진다.

### Fig. 20 — Placement Attempts and Runtime Distribution

파일: [20_placement_attempt_count_and_runtime_distribution.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/20_placement_attempt_count_and_runtime_distribution.png)

[확인] 전체 500 record 기준 runtime/attempt 분포다.

```text
metric                         q50      q90       q95       max
placement_attempts             2        2         2         24
anchor_attempts                2        2         2         24
context_placement_attempts     6        185       199       216
cargo_placement_attempts       9        70        92        117
occluder_feedback_iterations   0        36        36        36
runtime_s                      25.64    56.35     64.48     156.73
```

mode별 runtime median:

```text
clean-static            13.69 s
cargo-only              18.16 s
context-rich            26.11 s
controlled-occlusion    46.64 s
```

[판정] context placement와 controlled occluder feedback이 비용 병목이다.

과해석 금지:

- [확인] 이 runtime은 현재 개발 PC/Blender 설정의 측정값이다. 다른 GPU/CPU/Blender 버전으로 일반화하면 안 된다.
- [확인] PNG는 초, attempt count, iteration count처럼 단위가 다른 여섯 분포를 한 x축에 겹쳐 그렸다. 변수 간 크기를 시각적으로 직접 비교하지 말고 위의 수치표를 사용해야 한다.

### Fig. 21 — Camera and Geometry Prescription Distribution

파일: [21_camera_geometry_prescription_distribution.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/21_camera_geometry_prescription_distribution.png)

[확인] 이 다중 패널 그림은 target prescription과 realized camera field를 함께 보여준다. pallet, azimuth, V, elevation, projected-size target은 proposal 측 정보이고, exposure, `fx`, aspect, resolution은 non-rendered row에서 비어 있어 realized 435장 또는 missing 범주를 포함한다.

핵심 결과:

```text
pallet                 Pallet_0/1/2/3 각각 125
azimuth_bin            각 bin 41~42로 거의 균등
v_target               4:76, 5:123, 6:150, 7:101, 8:50
scene_preset           outdoor-day 150, outdoor-night 125, indoor 125, random-mix 100
aspect/resolution      4:3 215, 16:9 110, 3:2 62, 1:1 48, missing 65
elev_target            min 0.62, q50 17.31, q95 67.56, max 79.84
projected_size_target  min 0.00016, q50 0.2999, q95 0.8533, max 0.9978
exposure_ev            rendered n=435, q50 -1.3503, q95 0.0406
fx                     rendered n=435, q50 601.03, range 300.01~698.84
```

[판정] pallet ID와 azimuth target은 proposal coverage 근거로 쓸 수 있다. 반면 aspect/resolution 막대는 realized subset 분포이며, 최종 공개 데이터의 prescription 또는 accepted 분포와 동일하다고 볼 수 없다.

과해석 금지:

- [확인] `fx`와 `exposure_ev`는 rendered n=435에서만 집계된다. non-rendered row에는 카메라 실현값이 없다.

### Fig. 22 — Magenta, Corrupt, and Empty-mask Counts

파일: [22_magenta_corrupt_empty_mask_counts.png](../../data/pallet/_v2_scene_logic_500_seed7500/eda/charts/22_magenta_corrupt_empty_mask_counts.png)

[확인] 전체 500 record 기준 defect count다.

```text
magenta_fraction_gt_0   0
corrupt_rgb             0
corrupt_mask            0
empty_target_mask       4
strict RGB decode fail  0
```

[확인] empty target mask indices는 48, 321, 453, 478이다.

과해석 금지:

- [확인] `rgb_decode_ok=False`처럼 보이는 65개는 non-rendered/missing RGB placeholder이며 strict decode failure가 아니다. 엄밀한 decode failure는 0이다.

## 이미지/오버레이/표 산출물 해석

### 이미지 산출물 인벤토리

[확인] EDA 폴더의 이미지/표 산출물 수는 아래와 같다.

```text
charts/*.png                 22
overlay_all/*.png            500
contact_sheets/*.png         117
failure_examples/*.png       7
debug_geometry/*.png         20
manual_audit/*.{md,csv,json} 7
```

[확인] audit summary의 파일 카운트는 다음과 같다.

```text
records      500
rgb          435
labels       435
mask_files   2175
overlays     500
```

### 대표 contact sheet

[확인] 아래 이미지는 실제 생성된 contact sheet를 직접 확인한 결과다. 시각 판독은 overlay 정렬, 조명, target 크기, placeholder 유형을 확인하는 근거로 사용했다. 3D 관통 없음은 thumbnail로 판정하지 않았으며 exact BVH field를 별도 근거로 사용했다.

#### 대표 자동 게이트 통과 프레임

![자동 품질 게이트 통과 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/pass_examples.png)

*그림 V1. 자동 G1-G5 게이트를 통과한 대표 20장. RGB 위의 2D cuboid와 keypoint가 서로 다른 조명, 바닥, 시점, 팔레트 외관에서 target과 대체로 정렬됨을 보여준다. 이 시트는 시각적 정합성 확인용이며, 미세한 corner error와 3D 충돌 여부를 증명하지 않는다.*

#### Clean-static 모드

![Clean-static 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/mode_clean-static_002.png)

*그림 V2. 외부 cargo/context/explicit occluder 없이 거리, 고도, 조명, 바닥 텍스처, 팔레트 외관을 변화시킨 clean-static 예시. 같은 모드 안에도 매우 작거나 어두운 target이 포함되므로 clean-static은 “쉬운 프레임”과 동의어가 아니다.*

#### Cargo-only 모드

![Cargo-only 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/mode_cargo-only_003.png)

*그림 V3. 적재물이 팔레트 상부와 개구부 일부를 가리는 cargo-only 예시. cuboid는 visible contour가 아니라 전체 3D 팔레트의 투영을 나타낸다. cargo의 접촉·관통 품질은 thumbnail이 아니라 support 및 exact BVH audit로 판정했다.*

#### Context-rich 모드

![Context-rich 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/mode_context-rich_003.png)

*그림 V4. 산업 현장형 배경 물체와 distractor를 배치한 context-rich 예시. 화면 복잡도는 증가하지만 Fig. 14가 보이듯 screen area와 target occlusion은 같은 변수가 아니며, 작은 target과 강한 가림은 별도 품질 등급으로 관리해야 한다.*

#### Geometry debug overlay

![Context 및 controlled geometry debug 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/debug_geometry_context_controlled_examples.png)

*그림 V5. context-rich와 controlled-occlusion 장면의 cuboid/keypoint debug overlay. 투영 라벨과 영상 내 target 위치를 점검하기 위한 그림이며 collision detector의 시각화가 아니다.*

#### Source mask M0-M4

![Source mask 단계별 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/source_masks_001.png)

*그림 V6. RGB와 M0 target-only, M1 static, M2 cargo, M3 context, M4 explicit/full 단계 mask를 함께 표시한 예시. mask 면적 감소는 source별 2D 가림 기여를 설명하지만, 분해 순서에 의존하며 3D 관통의 근거가 아니다. 이 페이지에는 tiny target과 non-rendered placeholder도 포함된다.*

#### Audit fail

![Audit fail 예시](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/audit_fail_001.png)

*그림 V7. automated/manual audit에서 분리된 7개 사례. rendered frame의 empty target mask 4건과 RGB가 없는 anchor-reject placeholder 3건을 한 시트에 모았다. 실패 시트는 전체 분포의 대표 표본이 아니라 reject 경로를 설명하는 근거다.*

추가 전체 시트:

- [G1-G5 failure examples](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/failure_examples.png)
- [empty target mask 4건](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/failure_reason_empty_target_mask_001.png)
- [source mask 첫 요약 시트](../../data/pallet/_v2_scene_logic_500_seed7500/eda/contact_sheets/source_masks.png)

[판정] 논문/README에는 V1, V5, V6, V7을 묶어 “라벨 정합성, 역할별 가림 분해, reject 사례”를 보여주는 구성이 가장 안전하다. 모드별 다양성을 강조할 때만 V2-V4를 추가한다.

### manual visual audit 결과

[확인] manual audit는 500/500 unique continuous indices를 모두 덮었고, RGB 435/435와 overlay/diagnostic placeholder 500/500을 개별 decode했다.

manual verdict:

```text
pass                          286
reject_auto_gate               67
reject_not_rendered            65
reject_manual_extreme_small    12
reject_audit_fail               4
warn_very_small                39
warn_dark                      22
warn_noise                      5
total                         500
```

[확인] G1-G5 accepted 364장은 아래처럼 나뉜다.

```text
pass                          286
manual extreme-small reject    12
very-small warning             39
dark warning                   22
noise warning                   5
total accepted                364
```

[판정] “G1-G5 accepted”만으로 production training manifest를 만들면 tiny/dark/noise warning을 모두 학습에 넣게 된다. 공개 데이터에는 보존하되, 학습 manifest는 `accepted_clean`, `accepted_with_warnings`, `tiny_reject`를 분리하는 편이 안전하다.

## 불일치처럼 보이는 수치와 정확한 해석

### automated audit pass 493 vs manual clean pass 286

[확인] `audit_summary.json`의 `audit_pass_count=493`은 자동 파일·mask·overlay 감사 조건을 통과한 row 수다. 반면 manual audit의 `pass=286`은 G1-G5 accepted 중 사람이 “학습에 그대로 써도 좋다”고 본 clean pass 수다.

[확인] 짧게 쓰면 automated audit pass는 493이고 manual clean pass는 286이다.

[판정] 두 값은 모순이 아니다. 서로 다른 기준이다.

### RGB decode fail 0 vs rgb_decode_ok False 65

[확인] strict RGB decode failure는 0이다. `frame_metrics.csv`에서 65개가 RGB decode ok가 아닌 것처럼 보이는 이유는 non-rendered row에 RGB 파일이 없기 때문이다.

[판정] 문서에서는 “corrupt/decode failure 0, non-rendered/missing RGB 65”로 써야 한다.

### controlled error q95 0.393 vs 0.111

[확인] chart 09는 controlled 전체 target 중 valid `explicit_abs_error` n=149를 사용해서 q95=0.3931이다. controlled summary는 rendered-only n=87을 사용해서 q95=0.1111이다.

[판정] proposal delivery까지 평가하면 0.393, 렌더 성공 후 placement 정밀도를 평가하면 0.111이다. 둘 다 적어야 한다.

## 과해석 금지 목록

- [확인] 500-record smoke는 production 40k의 분포 보장이 아니다.
- [확인] baseline 2k와 새 500-record 진단은 runner, proposal 분포, acceptance 경로가 달라 causal ablation이 아니다.
- [확인] chart 1의 gate fail rate는 rendered 기준이다. 전체 proposal 성공률과 다르다.
- [확인] chart 8~10은 controlled 전체 target과 rendered-only 해석이 다르다.
- [확인] chart 16과 17은 bin `0`/fallback 혼합, chart 18은 Boolean `False`/missing 혼합 때문에 현재 PNG를 정량 그림으로 사용할 수 없다.
- [확인] source-dominant chart는 복합 가림의 인과 분해가 아니다.
- [확인] no exact collision count는 최종 record 기준이다. 모든 후보 placement가 collision-free였다는 뜻은 아니다.
- [확인] manual visual audit는 사람 판단을 포함한다. tiny/dark/noise warning 정책은 downstream model architecture에 맞춰 확정해야 한다.
- [추정] 현재 배경 조합에서는 static occlusion이 안정적이지만, 새 배경 asset을 추가하면 anchor/LOS/cache 검증을 다시 해야 한다.

## 논문/README용 추천 구성

### 결과 그림 묶음

```text
Figure A: baseline 2k vs new 500 gate fail rate
  - chart 01

Figure B: diagnostic mode별 all-pass와 source-decomposed occlusion
  - chart 02, 03

Figure C: source별 가림 분포
  - chart 04, 05, 06

Figure D: controlled occlusion delivery
  - chart 07, 08, 09, 10

Figure E: placement validity and generation cost
  - chart 11, 12, 20, plus audit summary

Figure F: camera coverage and alignment eligibility
  - chart 19, 21
  - elevation/projected-size/cargo는 이 문서의 교정표 사용
  - chart 16, 17, 18은 analyzer 수정·재생성 전 제외

Figure G: visual quality audit
  - chart 22, V1 pass examples, V6 source masks, V7 audit fail
```

### 본문에 바로 쓸 수 있는 핵심 문장

[확인] “The rendered subset of the 500-record constrained-scene diagnostic achieved an 83.68% all-pass rate, compared with 40.00% in the earlier 2k pilot; this comparison is descriptive because the proposal and acceptance pipelines differ.”

[확인] “The source-decomposed masks show that static-scene occlusion was near zero in clean-static frames, cargo occlusion was bounded below 0.25 in cargo-only frames, and explicit occlusion dominated controlled-occlusion frames.”

[확인] “The main remaining limitation is proposal-level delivery for controlled occlusion: only 87 of 150 controlled targets rendered successfully, although all rendered controlled frames contained a visible explicit occluder.”

[확인] “The automated and manual audits found no fatal file, magenta, texture, support, or evaluated exact-collision defect, but identified four empty target masks and twelve all-pass frames that were too small for useful supervision.”

## 다음 결정

[판정] 40k 본렌더 전에 아래 6개를 먼저 처리해야 한다.

1. controlled-occlusion bounded search exhaustion 62/150을 줄이거나, controlled quota를 actual accepted 기준으로 채우는 pool/manifest 방식으로 바꾼다.
2. center occluder actual 3/87 문제를 별도 quota와 solver target으로 보강한다.
3. tiny target policy를 G1-G5와 분리해 `tiny_reject` 또는 `tiny_warning` manifest로 기록한다.
4. chart 09처럼 전체 target 기준과 rendered-only 기준이 갈리는 지표는 README와 논문에서 분모를 명시한다.
5. `analyze_v2_scene_logic.py`의 chart 16/17 bin fallback과 chart 18 Boolean grouping을 수정하고 22개 차트를 재생성한다.
6. 새 배경/asset을 추가하기 전에는 anchor cache, static LOS, source mask decomposition을 같은 500-record smoke로 다시 검증한다.
