# Blender v2 usable 50-frame continuous EDA 결과 해석

작성일: 2026-07-27
대상 산출물: `data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/`

문서 상태: **usable 50장 배달셋의 연속변수 EDA 해석 — 500-frame pilot도 40k 본렌더도 아니다**

관련 기록:

- Phase 9D/9E 최종 보고서: [reports/v2_revision/quality_smoke50/summary.md](../../reports/v2_revision/quality_smoke50/summary.md)
- 오늘 작업 기록: [2026-07-27.md](../history/2026-07-27.md)
- 별도 데이터셋(구 500-record 진단) 해석: [v2_scene_logic_500_eda_results.md](v2_scene_logic_500_eda_results.md)

---

## 목적

[확인] 이 문서는 Phase 9D에서 생성된 **usable 50-frame quality smoke**의 연속변수 EDA 산출물
(figure 17개 + `continuous_metrics.csv` + `continuous_summary.json`)이 실제로 무엇을 보여주는지 글로
해석한 보고서다. 목적은 세 가지를 분리하는 것이다.

1. 이 그림들로 **주장할 수 있는 것**(처방-실현 정합, 가림 분해, 카메라/조명 커버리지, 생성 비용)
2. 이 그림들로 **주장할 수 없는 것**(게이트 판별력, 임계값 확정, 처방 분포의 대표성)
3. 표본 50과 usable 선택 때문에 **구조적으로 무정보가 된 그림**(figure 10/11/12)

[확인] 17개 PNG를 전부 개별 로드해 실제 그려진 내용을 확인한 뒤 작성했다. 수치는 이미지 눈대중이 아니라
`continuous_summary.json` / `continuous_metrics.csv` / `discrete_counts.csv`에서 인용했고, 일부는 원본
`records.jsonl` / `labels/*_label.json`에서 재계산해 대조했다.

---

## 입력 산출물

[확인] 아래 파일을 직접 읽었다.

```text
data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/*.png     17개 (전부 개별 확인)
data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/continuous_summary.json
data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/continuous_metrics.csv    215행
data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/discrete_counts.csv        60행
data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/paper_continuous_summary.md
reports/v2_revision/quality_smoke50/summary.md                        (Phase 9E 보고서)
reports/v2_revision/quality_smoke50/pnp/pnp_threshold_study.md
data/pallet/archive/superseded_runs/_v2_smoke50_9d/records.jsonl / labels/*_label.json        (수치 재계산용)
```

[확인] 같은 이름의 PDF 17개가 `figures_pdf/`에 있고, 내용은 PNG와 동일한 figure다(논문용 벡터 출력).

---

## 이 데이터셋의 성격 — 500-record 진단과 무엇이 다른가

[확인] 이것은 **usable 50장**이다. `--completion-mode usable`로 돌려서, 물리 검증(거리 상한·지면 연속성·
support·camera clearance·exact collision)과 G1~G5 게이트와 mask 무결성을 **전부 통과한 프레임만** 50장이
찰 때까지 proposal을 계속 뽑은 결과다.

```text
항목                                    9D usable 50셋              구 500-record 진단
─────────────────────────────────────────────────────────────────────────────────────────
completion mode                         usable (배달 수 고정)        records (proposal 수 고정)
분석에 들어간 frame row                 50                          435 rendered / 500 record
proposal drawn                          107                         500
render attempt                          75                          -
all_pass                                50/50 = 100 % (정의상)      364/435 = 83.68 %
render profile                          dataset-quality (64spp+OIDN) 별도
seed                                    7000                        7500
```

[판정] 따라서 **"500개 완료" 같은 표현은 이 산출물에 쓸 수 없다.** 그리고 baseline 2k나 구 500-record 셋과
비교할 때는 **descriptive** 비교만 가능하다 — proposal 스트림, acceptance 경로, render profile이 전부 다르다.
causal ablation이 아니다.

[확인] 가장 중요한 귀결은 **선택 편향**이다. 이 50장은 "게이트를 통과한 것만" 모은 집합이므로,
결과변수가 게이트 통과 여부인 그림(figure 10/11/12)은 정의상 상수가 된다. 자세한 설명은 아래 별도 섹션에 있다.

---

## 분모 해석 규칙

[확인] figure마다 분모가 다르다. 아래 구분 없이 수치를 섞으면 잘못된 결론이 나온다.

```text
분모                          사용 위치 / 의미
──────────────────────────────────────────────────────────────────────────────────
frame row n=50                기본 분모. 배달된 usable 프레임 전수
proposal row n=107            데이터셋 로드 단위(frame 50 + rejected proposal 57).
                              figure 본문에는 거의 쓰이지 않고 delivery 패널에만 등장
controlled rendered n=15      figure 09. controlled-occlusion 중 실제 배달된 프레임
controlled proposal n=38      figure 09 우측 delivery 패널. 실패 23건 포함
support-내 n=44               figure 11/13. projected_size_actual ∈ [0,1]인 행만
                              (6/50은 >1.0으로 과대추정되어 fit에서 제외)
X>0 조건부 n                  figure 06. f_static 1 / f_cargo 19 / f_context 3 /
                              f_explicit 15 / f_total 32
```

[판정] 논문/README에서 이 셋의 수치를 인용할 때는 반드시 **"usable 배달셋 50장 기준"**을 붙여야 한다.

---

## 결론 요약

[확인] 이 EDA가 실제로 보여준 것.

```text
관측                                                        근거 figure / 수치
──────────────────────────────────────────────────────────────────────────────────────
처방 -> 실현이 거리·고도에서 기계 정밀도로 일치            fig 01/03/07, elevation MAE 2.07e-06 deg
projected size만 계통적으로 과대 실현                       fig 02/08, bias +0.1954 (전부 양수)
controlled 가림은 배달된 15장에서 정밀(MAE 0.052)          fig 09
delivery는 낮음 — proposal 38 중 15 배달(39.5 %)           fig 09 우측 패널
가림원 분해가 zero-inflated로 정상 동작                     fig 06, P(X=0) 0.98/0.62/0.94/0.70
방위각은 균등에 가깝고 0/360 이음매 불연속 없음            fig 04, |f(0)-f(360)| = 0.000e+00
게이트 판별력은 측정 불가                                   fig 10/11/12 base rate 1.000
PnP eligibility만 비퇴화 곡선                               fig 13, base 0.909/0.773/0.727
생성 비용 median 13.6 s / 프레임                            fig 16
```

[판정] 이 50장은 **파이프라인 배관(배달·필드 배선·처방 정합·무결성)이 동작한다**는 증거다.
게이트 튜닝, 임계값 확정, 학습 적합성 판단에는 쓸 수 없다.

---

## 핵심 그림 미리보기

![가림원별 zero point mass와 조건부 ECDF](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/06_occlusion_source_zero_mass_and_positive_ecdf.png)

*그림 P1 (fig 06). 5개 가림원(static / cargo / context / explicit / total)을 zero-inflated 분포로 다룬다.
왼쪽 막대는 P(X=0)을 점질량으로 그대로 표시하고, 오른쪽은 X>0에만 조건부 ECDF와 KDE를 얹는다.
분모는 전부 50이고, X>0 표본은 각각 1 / 19 / 3 / 15 / 32다. KDE는 0 스파이크를 절대 매끄럽게 만들지 않는다 —
이게 이 그림의 방법론적 핵심이다. n=1(f_static), n=3(f_context) 패널은 ECDF 계단 자체가 표본이며 분포로
읽으면 안 된다.*

![projected size target vs actual](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/08_projected_size_target_vs_actual.png)

*그림 P2 (fig 08). 50쌍 전부가 y=x 위쪽에 있다. 잔차 ECDF가 0 왼쪽에 아무 질량도 갖지 않는 것(signed residual
최솟값 > 0)이 그 시각적 증거다. bias_mean = +0.1954로 MAE와 정확히 같다(= 모든 잔차가 양수라는 뜻).
이건 랜덤 오차가 아니라 `projected_size_actual`이 큐보이드 코너가 화면 밖으로 나가거나 카메라 뒤로 갈 때
과대 읽히는 **계통 결함**(blocker B5)이다.*

![controlled occlusion f_target vs f_explicit_actual](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/09_f_target_vs_f_explicit_actual.png)

*그림 P3 (fig 09). 왼쪽은 배달된 15장의 정밀도(MAE 0.052, Pearson r 0.907), 오른쪽 막대는 proposal-level
delivery(38 제안 → 15 배달 → 15 쌍)를 **같은 숫자에 섞지 않고** 따로 보여준다. 이 두 패널을 분리한 것이
핵심이다 — 왼쪽만 보면 solver가 정확해 보이고, 오른쪽만 보면 실패만 보인다.*

![P(all_pass) vs f_total](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/12_allpass_probability_vs_f_total.png)

*그림 P4 (fig 12). **무정보 그림의 대표 사례.** 곡선 3개가 전부 y=1.0에 겹쳐 있고, rug의 negative 줄에는
눈금이 하나도 없다. usable 셋에는 실패 사례가 0이라 base rate가 1.000이고 LOO Brier가 8.1e-33이다.
"가림이 커져도 게이트 통과율이 안 떨어진다"로 읽으면 안 된다 — 애초에 떨어질 사례가 배달셋에 들어올 수 없다.*

![PnP eligibility vs projected size](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/13_pnp_stability_vs_projected_size.png)

*그림 P5 (fig 13). 이 셋에서 **유일하게 비퇴화한 pass-probability 그림**이다. PnP eligibility는 배달 조건이
아니라 사후 측정값이라 0과 1이 모두 존재한다(base 0.909 / 0.773 / 0.727). 다만 200 격자점 중 신뢰 구간
(n_eff >= 20)이 **0개**라 전 구간이 점선이다. 큰 projected size에서 넓게 벌어진 부트스트랩 밴드는 신호가
아니라 표본 희박이다.*

![scene preset별 final-RGB luma ECDF](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/05_final_luma_ecdf_by_scene.png)

*그림 P6 (fig 05). post-effect가 적용된 **final** RGB 기준 luma다(G5가 실제로 보는 픽셀). 왼쪽은 팔레트
영역, 오른쪽은 프레임 전체. 4개 preset 표본이 16/12/11/11로 작아 계단이 거칠다. 눈에 띄는 건 outdoor-day의
팔레트 luma가 가장 왼쪽(어두움)이고 outdoor-night가 그보다 오른쪽이라는 점인데, preset 이름과 팔레트
밝기가 단조 대응하지 않는다는 뜻이다.*

![이산 변수 카운트](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/A01_discrete_variable_counts.png)

*그림 P7 (A01). 21개 이산 변수의 카운트. `(missing)` 버킷을 회색으로 **분리**해 그리고 0/False와 절대
합치지 않는다(구 analyzer의 falsy-0 버그를 고친 결과). G1~G5와 all_pass가 전부 True 한 막대만 갖는 것이
이 셋이 usable 배달셋임을 한눈에 보여준다.*

---

## 17개 figure별 해석

### Fig. 01 — Camera distance: target vs actual

파일: [01_camera_distance_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/01_camera_distance_ecdf.png)

[확인] 분모 50, target n=50 / actual n=50, missing 0. ECDF(주) + KDE(보조, Silverman robust h=1.197,
reflection 경계보정, [0,10] m로 clip).

[확인] target 곡선(파랑)이 actual 곡선(주황)에 완전히 가려 보이지 않는다. 두 계열의 평균 차이는
4.347543792730921 − 4.347543783639067 = **9.1e-09 m**다. 즉 처방 거리가 그대로 실현됐다.

```text
                q05      q25      q50      q75      q95      min      max
camera dist    1.157    1.994    3.180    7.072    9.295    0.816    9.737
```

[확인] `MAX_CAMERA_DISTANCE_M = 10.0` 상한을 넘는 프레임은 0/50이고, 최댓값 9.737 m는 상한에 붙지도
않았다. 구 500셋에서 435 rendered 중 72장이 10 m를 넘고 최대 1015.6 m였던 것과 대비된다(descriptive).

[확인] KDE는 이봉형이다 — 약 2 m에 주봉, 6.2 m 부근에서 최소, 8~9 m에서 다시 상승한다. ECDF에도
약 5.0~6.6 m 구간에 계단이 없는 평탄부가 있다.

과해석 금지:

- [판정] 이봉형은 "설계된 두 개의 거리 모드"가 아니라 projected-size bin별 feasible interval 샘플링의
  부산물일 수 있다. n=50에서 봉우리 개수를 주장하면 안 된다.
- [확인] 이 값은 **배달된** 50장의 거리 분포다. 렌더 시도 75회나 proposal 107건의 거리 분포가 아니다.
- [확인] Phase 9E 보고서 4.5절은 같은 데이터의 q50/q75/q95를 3.44 / 7.11 / 9.33으로 적었는데, 이는
  `np.quantile(method='higher')` 결과다(정렬 26번째 값 = 3.4362). EDA와 이 문서는 numpy 기본
  linear 보간(3.1796 / 7.0723 / 9.2947)을 쓴다. **분포가 다른 게 아니라 분위수 규약이 다르다** —
  원본 50개 값에서 두 규약을 모두 재계산해 확인했다. min/max/q05/q25는 양쪽이 같다.

### Fig. 02 — Projected size ratio: target vs actual (ECDF)

파일: [02_projected_size_target_actual_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/02_projected_size_target_actual_ecdf.png)

[확인] 분모 50. target n=50, actual n=50이지만 actual 중 **6개가 nominal support [0,1] 밖**(최대 2.624)이다.
이 6개는 ECDF에는 남기고 density와 x축 표시에서만 제외했다.

```text
                        q05      q25      q50      q75      q95      mean
projected_size_target  0.0714   0.1277   0.2409   0.4638   0.7766   0.3285
projected_size_actual  0.0965   0.1778   0.3489   0.7245   1.4909   0.5240
```

[확인] actual ECDF(주황)가 target ECDF(파랑)보다 전 구간에서 아래에 있다 = actual이 확률적으로 더 크다.
actual ECDF는 x=1.0에서 0.88까지만 올라가고 나머지 12 %(6/50)는 그림 밖에 있다.

과해석 금지:

- [판정] "실현된 팔레트가 처방보다 크게 찍혔다"로 읽으면 안 된다. 이는 대부분 `projected_size_actual`
  **측정 결함**(코너가 프레임을 벗어나거나 카메라 뒤로 갈 때 과대 읽힘)이다. blocker B5.
- [확인] actual의 q95 = 1.4909는 물리적으로 불가능한 값이다(이미지 폭 비율). 이 지표를 x축으로 쓰는
  모든 그림(11, 13)이 같은 오염을 공유한다.

### Fig. 03 — Camera elevation: target vs actual (density)

파일: [03_elevation_target_actual_density.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/03_elevation_target_actual_density.png)

[확인] 분모 50, missing 0. density는 처방 범위 (0.5, 80.0) deg로 clip, h=7.396.

```text
                       q05      q25      q50      q75      q95      min      max
elevation_deg_target   2.98     8.05    17.90    32.29    63.42     1.89    75.54
elevation_deg_actual   2.98     8.05    17.90    32.29    63.42     1.89    75.54
```

[확인] 두 계열이 소수점 6자리까지 겹쳐 target 곡선이 보이지 않는다. 평균 차이 8.3e-08 deg.

[확인] 분포는 강한 저앙각 편중이다 — q25가 8.05도, 중앙값 17.9도이고 KDE 최대는 하한(1.9도) 쪽에 있다.
Phase 9E 보고서에 따르면 elev < 5도가 8장, < 10도가 17장(분모 50)이다.

과해석 금지:

- [판정] 저앙각 편중은 **처방이 그렇게 설계된 것**이며 실현 오차가 아니다. 다만 이 셋의 위험 인자
  (tiny 4장 중 3장, PnP 발산 2장 전부)가 저앙각에 몰려 있으므로, 저앙각 비중은 품질 문제와 함께 봐야 한다.
- [확인] 이 분포는 배달된 50장이다. 저앙각 proposal이 렌더 전에 더 많이/적게 탈락했는지는 이 그림으로
  알 수 없다.

### Fig. 04 — Azimuth prescription: von Mises circular KDE

파일: [04_azimuth_circular_kde.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/04_azimuth_circular_kde.png)

[확인] 분모 50, missing 0. 극좌표 밀도(왼쪽)와 0~360 펼친 뷰(오른쪽) 두 패널.

```text
kappa (LOO likelihood CV)          0.2   (탐색 격자 30개의 최소값 = 경계에 붙음)
equivalent angular sd              128.12 deg
uniform reference density          0.159155
observed density range             [0.156984, 0.161618]
|f(0 deg) - f(360 deg)|            0.000e+00
seam step / local median step      1.032
```

[확인] 관측 밀도 범위가 균등 기준선(0.1592)의 ±1.6 % 안에 들어간다. 극좌표 그림에서 KDE 곡선과 균등
기준 점선이 거의 완전히 겹친다. 0/360 이음매도 국소 격자 간격의 1.03배로 매끈하다.

과해석 금지:

- [확인] `kappa_at_grid_boundary: true`다. LOO CV가 격자 최소값(0.2)을 골랐다는 것은 "데이터가 더 매끈한
  쪽을 원했지만 격자가 거기서 끝났다"는 뜻이다. 즉 **이 그림은 균등성의 상한만 보여준다** — 실제 분포가
  균등이라는 검정이 아니다.
- [판정] "방위각 커버리지가 균등하다"는 주장은 n=50에서 이 그림만으로 하면 안 된다. 균등을 반증할 만한
  구조는 없다는 정도가 정확한 표현이다.
- [확인] `azimuth_deg_target`(처방)이다. 실현 방위각이 아니다.

### Fig. 05 — Final-RGB luma ECDF by scene preset

파일: [05_final_luma_ecdf_by_scene.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/05_final_luma_ecdf_by_scene.png)

[확인] 분모 50. `luma_pallet_final` n=50, `luma_frame_final` n=50, scene_preset 4그룹
(outdoor-day 16 / random-mix 12 / indoor 11 / outdoor-night 11).

```text
luma_pallet_final       n     q05      q25      q50      q75      q95
outdoor-day            16    23.21    25.11    33.47    40.63    66.17
random-mix             12    19.33    25.69    42.11    62.93    76.53
indoor                 11    24.09    30.40    40.23    51.23    66.28
outdoor-night          11    18.72    26.64    36.86    59.06    82.65

luma_frame_final        n     q05      q25      q50      q75      q95
outdoor-day            16    28.65    38.09    49.15    74.37   103.96
random-mix             12    18.60    29.66    44.10    62.71    93.80
indoor                 11    32.60    37.83    54.11    67.13   104.39
outdoor-night          11    31.30    35.71    51.73    81.36   113.04
```

[확인] 팔레트 luma 중앙값 서열은 random-mix(42.1) > indoor(40.2) > outdoor-night(36.9) > outdoor-day(33.5)다.
즉 **outdoor-day가 가장 어둡다.** 이는 노출 EV 처방이 −3.0~+0.2 EV로 전체적으로 하향돼 있고(fig 15),
preset이 절대 밝기를 결정하지 않기 때문이다.

[확인] `luma_pallet_final` 최솟값은 16.35(Phase 9E 보고서 f0034)로, G5 임계 12.0보다 4.35 위에 있다.
즉 **이 50장에는 G5 임계를 가로지르는 프레임이 하나도 없다.**

과해석 금지:

- [판정] 그룹당 n이 11~16이라 ECDF 계단이 거칠다. preset 간 밝기 차이를 정량 주장하면 안 된다.
- [확인] G5가 raw가 아니라 final luma를 본다는 것은 코드 경로(`v2_realize.safety_gates()`)와 Phase 3에서
  관측된 판정 뒤집힘 3건이 근거이며, **이 50장만으로는 raw/final을 구분할 수 없다**(어느 쪽으로 재도 G5
  판정이 같다).
- [확인] 이 분포는 배달된 프레임이다. G5로 탈락한 프레임은 이 실행에서 0건이라 어차피 빠질 것이 없었지만,
  일반적으로 이 그림은 "게이트 통과 후" 분포다.

### Fig. 06 — Occlusion sources: zero point mass + conditional ECDF

파일: [06_occlusion_source_zero_mass_and_positive_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/06_occlusion_source_zero_mass_and_positive_ecdf.png)

[확인] 분모 50, 5개 변수 전부 missing 0. 좌측은 P(X=0) 막대, 우측은 X>0 조건부 ECDF(+ n>=15일 때만 KDE).

```text
변수          n_zero   n_pos   P(X=0)    q50|X>0   q95|X>0   mean|X>0
f_static        49       1     0.9800    9.59e-06  9.59e-06  9.59e-06
f_cargo         31      19     0.6200    0.1459    0.2403    0.1447
f_context       47       3     0.9400    0.0181    0.1007    0.0429
f_explicit      35      15     0.7000    0.1746    0.3647    0.2042
f_total         18      32     0.3600    0.1644    0.3550    0.1856
```

[확인] 배경(static) 가림은 사실상 없다 — 유일한 양수값이 9.6e-06이다. cargo가 켜진 프레임은 22/50인데
`f_cargo > 0`는 19건이고, 그 조건부 중앙값 0.146 / q95 0.240으로 **25 % 미만에 갇혀 있다.**
explicit occluder는 배달 15건 전부에서 양수이고 조건부 중앙값 0.175다.

[판정] 역할별 가림원 분해가 의도대로 작동한다. static은 0, cargo는 중간, explicit이 가장 크다.

과해석 금지:

- [확인] f_static(n=1)과 f_context(n=3) 패널은 **분포가 아니라 개별 관측 3개 이하**다. 조건부 q95를
  인용하면 안 된다.
- [판정] 분해량은 M0→M4 mask 순서에 의존한다. 여러 가림원이 겹치는 픽셀의 귀속은 이 순서가 정한다.
- [확인] `f_static`은 배치 카운터가 없고 면적 유래 값만 있다(blocker B10). "static이 가리지 않았다"를
  mask로 반증할 수단이 없다.

### Fig. 07 — Elevation: target vs actual (scatter + residual)

파일: [07_elevation_target_vs_actual.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/07_elevation_target_vs_actual.png)

[확인] 분모 50, rendered-only. 좌측 산점도는 y=x 위에 완전히 눕고, 우측 잔차 ECDF의 x축 단위는 **1e-5**다.

```text
MAE          2.067e-06 deg
median AE    7.363e-08 deg
q90 AE       8.486e-06 deg
q95 AE       1.280e-05 deg
Pearson r    1.0000
Spearman rho 1.0000
bias_mean    8.340e-08 deg
```

[판정] 고도 처방은 기계 정밀도로 실현된다. 잔차는 부동소수점 왕복 오차 수준이고 부호도 대칭이다
(signed residual ECDF가 0을 중심으로 양쪽에 질량이 있다).

과해석 금지:

- [확인] 이건 **정밀도(precision)**이지 delivery가 아니다. 렌더에 실패한 proposal 57건은 이 그림에 없다.
- [판정] r=1.0000은 모델 적합이 좋다는 뜻이 아니라 "우리가 설정한 값을 우리가 다시 읽었다"는 항등식에
  가깝다. 회귀 성능 지표처럼 인용하면 안 된다.

### Fig. 08 — Projected size: target vs actual (scatter + residual)

파일: [08_projected_size_target_vs_actual.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/08_projected_size_target_vs_actual.png)

[확인] 분모 50, rendered-only. 6/50 쌍이 support [0,1] 밖(최대 2.624)이라 산점도는 clip됐지만 **통계는
50쌍 전부**를 쓴다.

```text
MAE          0.19542
median AE    0.09626
q90 AE       0.32788
q95 AE       0.63224
Pearson r    0.9082
Spearman rho 0.9893
bias_mean    +0.19542   (= MAE와 동일 -> 모든 잔차가 양수)
```

[확인] 산점도의 50개 점이 **하나도 빠짐없이 y=x 위쪽**에 있고, 잔차 ECDF는 0에서 시작해 오른쪽으로만
간다. Spearman(0.989)이 Pearson(0.908)보다 높은 것은 순서는 잘 지키되 스케일이 계통적으로 어긋난다는 신호다.

[판정] 이건 랜덤 오차가 아니라 측정 정의 결함이다(blocker B5). 500-record 셋에서는 87/435 = 20 %가 1.0을
넘고 최대 39.09였으니, 9D의 12 % / 2.62는 **더 낫지만 여전히 존재한다**(descriptive 비교).

과해석 금지:

- [확인] "실현 크기가 처방보다 20 %p 크다"고 쓰면 안 된다. actual 쪽 계산이 틀린 것이지 렌더가 틀린 게 아니다.
- [판정] 이 지표를 x축으로 쓰는 fig 11/13의 x축은 같은 오염을 물려받는다. 두 그림이 [0,1] 밖 6행을 뺀 것은
  타당한 방어지만, 남은 44행이 깨끗하다는 보장은 아니다.

### Fig. 09 — Controlled occlusion: f_target vs delivered f_explicit_actual

파일: [09_f_target_vs_f_explicit_actual.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/09_f_target_vs_f_explicit_actual.png)

[확인] 분모 **15**(controlled-occlusion 배달분). 3패널: 산점도 / 잔차 ECDF / proposal delivery 막대.

```text
정밀도(배달된 15장)          delivery(proposal 기준)
────────────────────────     ──────────────────────────
MAE          0.05246         proposals            38
median AE    0.03813         rendered             15
q90 AE       0.09224         failed proposals     23
q95 AE       0.10130         delivery rate     39.47 %
Pearson r    0.9068
Spearman rho 0.8607
bias_mean   -0.04025
```

[확인] bias가 **음수**다 — 배달된 프레임의 실제 explicit 가림이 처방보다 평균 4 %p 작다. 산점도에서도
점 대부분이 y=x 아래에 있다.

[판정] solver는 성공한 장면에서 꽤 정확하지만(중앙 오차 0.038), **가림을 처방보다 약하게 만드는 쪽으로
치우쳐 있고**, 어려운 target을 fail-closed로 버리는 비율이 높다(23/38 = 60.5 %).

과해석 금지:

- [확인] 왼쪽 두 패널은 **성공 사례만** 본다. 실패한 23 proposal은 점으로 나타나지 않는다.
- [확인] 오른쪽 delivery 막대는 정밀도가 아니다. 두 숫자를 하나로 합치면 안 된다
  (analyzer 캡션도 "never mixed into the same numbers"라고 명시한다).
- [판정] n=15에서 bias −0.040을 "체계적 과소 가림"으로 확정하면 안 된다. 500-frame records-mode로
  재확인이 필요하다.

### Fig. 10 — P(all_pass) vs camera distance

파일: [10_allpass_probability_vs_distance.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/10_allpass_probability_vs_distance.png)

[확인] 분모 50. 세 outcome: `all_pass`(base 1.000), `physical_valid`(base 1.000), `pnp_eligible_3cell`
(base 0.800).

[확인] **all_pass / physical_valid 두 곡선은 y=1.0에 붙은 점선이고 신뢰 격자점이 0/200이다.**
rug의 negative 줄에는 눈금이 하나도 찍히지 않는다(음성 사례 0건). 왜 무정보인지는 아래 별도 섹션 참조.

[확인] 이 그림에서 **정보가 있는 것은 빨간 `pnp_eligible_3cell` 곡선뿐**이다.

```text
pnp_eligible_3cell     n=50, positive 40, base rate 0.800
bandwidth              2.291 m (LOO Brier 선택), LOO Brier 0.1378
신뢰 격자점            177 / 200  (n_eff >= 20)
p_hat 신뢰구간 범위    0.563 ~ 0.950
평균 CI 폭             0.248
```

[확인] 곡선은 0.8 m에서 약 0.95, 8.7 m에서 약 0.56으로 **단조 감소**한다. 부트스트랩 95 % 밴드는 먼
거리에서 0.31~0.78까지 벌어진다.

과해석 금지:

- [판정] "거리가 멀수록 PnP 적격률이 떨어진다"는 descriptive association이다. 거리와 projected size와
  고도가 같이 움직이므로 거리의 독립 효과가 아니다.
- [확인] 평균 CI 폭이 0.248이다. n=50에서 이 곡선으로 임계 거리를 정하면 안 된다.
- [확인] bandwidth 2.291 m는 데이터 범위(0.82~9.74 m)의 약 1/4다. 이 정도로 넓으면 국소 구조는 전부 뭉갠다.

### Fig. 11 — P(all_pass) vs projected size

파일: [11_allpass_probability_vs_projected_size.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/11_allpass_probability_vs_projected_size.png)

[확인] 분모 50이지만 fit에 쓰인 n=44다(projected_size_actual > 1.0인 6행 제외, 최대 관측 2.624).

[확인] **세 곡선 전부 신뢰 격자점 0/200이라 전 구간이 점선이다.** all_pass / physical_valid는 y=1.0에
붙어 있고, pnp_eligible_3cell(base 0.773)은 0.08에서 0.38로 시작해 0.25 부근에서 1.0에 도달한 뒤
0.7 근처에서 다시 0.85까지 내려가는 요철을 보인다.

[확인] all_pass의 선택된 bandwidth는 **0.01264**로 x축 범위(0.076~0.940)의 1.3 %에 불과하다. LOO Brier가
1.43e-32이라 "가장 좁은 bandwidth가 최적"으로 뽑힌 것이며, 이는 잔차가 정확히 0인 퇴화 상황의 산물이다.

과해석 금지:

- [판정] 0.7 부근의 하강은 **구조가 아니라 표본 희박**이다. 그 구간 밴드가 0.56~1.00으로 벌어져 있다.
- [확인] x축 자체가 fig 08에서 확인된 과대추정 지표다. 6행을 제외했다고 나머지가 정확하다는 뜻은 아니다.
- [확인] 신뢰 격자점 0/200 = **이 그림에서 정량 주장할 수 있는 지점이 하나도 없다.**

### Fig. 12 — P(all_pass) vs total occlusion fraction

파일: [12_allpass_probability_vs_f_total.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/12_allpass_probability_vs_f_total.png)

[확인] 분모 50, 세 outcome(all_pass / G1_pass / G3_pass) **전부 base rate 1.000**.

[확인] 그림에는 x=0 부근의 아주 짧은 실선 조각과 x≈0.37까지 이어지는 y=1.0 점선만 있다. 신뢰 격자점은
**2/200**이고, 그 2점의 p_hat은 0.9999999999999998~1.0, CI 폭 5.0e-16이다. 그 2점은 f_total=0인 18개 프레임이
몰려 있는 x≈0 근방이다(bandwidth 0.006163).

[확인] rug의 negative 줄은 완전히 비어 있다. x_max = 0.36807.

과해석 금지:

- [판정] "가림 37 %까지 게이트가 100 % 통과한다"로 읽으면 **틀린다**. 게이트를 못 넘은 프레임은 이 셋에
  들어올 수 없다. 그리고 이 셋의 f_total 최댓값이 0.368이라는 사실 자체가 게이트/솔버가 그 위를 잘라냈다는
  뜻이다.
- [확인] G1/G3 곡선이 all_pass와 완전히 동일한 이유는 세 outcome이 이 셋에서 같은 상수 벡터이기 때문이다.
  세 개의 독립된 증거가 아니다.

### Fig. 13 — PnP eligibility probability vs projected size

파일: [13_pnp_stability_vs_projected_size.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/13_pnp_stability_vs_projected_size.png)

[확인] 분모 50, fit n=44(>1.0인 6행 제외). 세 후보 임계 곡선.

```text
후보                 임계     base rate   bandwidth   LOO Brier   신뢰 격자점
2-cell (16 px)        16 px    0.9091      0.04321     0.06930      0 / 200
3-cell (24 px)        24 px    0.7727      0.05039     0.13653      0 / 200
4-cell (32 px)        32 px    0.7273      0.05039     0.15145      0 / 200
```

[확인] 세 곡선 모두 작은 projected size(0.08)에서 0.26~0.61로 시작해 0.25~0.3 부근에서 1.0에 접근한다.
서열은 2cell > 3cell > 4cell로 임계가 엄격할수록 낮다 — 정의상 당연한 포함관계다.

[판정] 이 셋에서 **유일하게 결과변수가 배달 조건이 아닌 그림**이라 곡선이 퇴화하지 않았다. 다만 신뢰
격자점이 0/200이라 여전히 전 구간 점선이다.

과해석 금지:

- [확인] "projected size가 0.3을 넘으면 PnP 적격"이라고 임계를 읽으면 안 된다. Phase 4 스터디 결론은
  **확정 불가**이며, 가장 엄격한 4cell 통과 집합조차 sigma=2px에서 5cm-5도 실패율이 0.354다.
  **크기 통과 ≠ PnP 신뢰**다.
- [확인] 0.4 부근과 0.7 부근의 밴드 함몰은 표본 공백이다(rug을 보면 그 구간에 눈금이 드물다).
- [확인] x축은 fig 08의 과대추정 지표다.

### Fig. 14 — Supplementary: focal length fx

파일: [14_fx_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/14_fx_ecdf.png)

[확인] 분모 50, missing 0, 경계보정 없음(domain null), h=39.28.

```text
       q05      q25      q50      q75      q95      min      max      mean
fx    356.33   477.16   599.83   605.91   652.92   335.44   692.19   541.33
```

[확인] ECDF에 **x = 605.9065 px에서 0.50 → 0.82로 뛰는 수직 계단**이 있다. 원본 라벨 50개를 재확인한
결과 `fx = 605.9065`이면서 `fx_mode = "anchor"`인 프레임이 정확히 **16개**(0.32)로, 이 계단의 높이와 일치한다.
나머지 34개는 `fx_mode = "random"`이고 fx 값이 전부 서로 다르다.

[판정] fx 분포는 "연속 랜덤 34개 + 실측 앵커 1점에 16개가 겹친 혼합분포"다. KDE(오른쪽)는 이 점질량을
600 px 부근의 완만한 봉우리로 뭉개므로 **ECDF가 정확하고 KDE는 오해를 부른다.**

과해석 금지:

- [확인] KDE의 600 px 봉우리를 "카메라가 그 초점거리를 선호한다"로 읽으면 안 된다. 16개의 동일값 점질량이다.
- [확인] 605.9065는 D435i 계열 앵커 intrinsic으로 보이나, 이 문서에서 소스 파일까지 추적하지는 않았다. [추정]

### Fig. 15 — Supplementary: exposure EV

파일: [15_exposure_ev_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/15_exposure_ev_ecdf.png)

[확인] 분모 50, missing 0, 처방 범위 (−3.0, +0.2) EV, reflection 경계보정, h=0.3532.

```text
             q05      q25      q50      q75      q95      min      max      mean
exposure_ev  -2.619   -2.037   -1.288   -0.654   -0.049   -2.925   +0.110   -1.314
```

[확인] ECDF가 −2.9에서 +0.1까지 거의 직선으로 올라간다 = 처방 구간 위에서 대체로 균등하다.
KDE는 −1.1 EV 부근에서 완만한 최대를 보이지만 최대/최소 밀도 차이는 약 2배 이내다.

[판정] 노출이 전 구간 음수 쪽으로 치우친 것은 **의도된 처방**이다(야간 커버리지 확보). 이 값을 상향하면
야간 시나리오가 사라진다.

과해석 금지:

- [확인] 이건 처방된 EV 값이지 실제 렌더 밝기가 아니다. 결과 밝기는 fig 05의 final luma로 봐야 한다.
- [확인] EV −3.0 하한에 점질량은 없다(최솟값 −2.925). 클램프 흔적이 아니라 연속 샘플링이다.

### Fig. 16 — Supplementary: per-frame runtime

파일: [16_runtime_ecdf.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/16_runtime_ecdf.png)

[확인] 분모 50(배달된 프레임만), 비음수 support, h=6.092.

```text
             q05      q25      q50      q75      q95      min      max      mean
runtime_s    4.38     6.93    13.62    30.23    47.45     3.99    56.23    19.11
```

[확인] 강한 우측 꼬리다. 하위 25 %가 7초 미만인데 상위 5 %는 47초를 넘는다. Phase 9E 실측 mode별 렌더
성공률(clean-static 100 % / cargo-only 100 % / context-rich 88 % / controlled 39 %)과 함께 보면, 빠른 쪽은
clean-static/cargo-only 슬롯이고 느린 쪽은 controlled다.

[확인] 전체 wall clock은 1925.7초(32.1분)인데 배달 50장의 runtime 합은 그보다 작다 —
**실패한 렌더 시도 25건의 시간이 이 ECDF에 없기 때문**이다.

과해석 금지:

- [판정] 이 ECDF로 40k 예산을 선형 외삽하면 **과소추정**한다. 실패 시도와 프로세스 오버헤드가 빠져 있다.
- [확인] 특정 개발 PC + OPTIX + dataset-quality(64 samples + OIDN) 조건의 측정값이다. 다른 하드웨어로
  일반화하면 안 된다.

### Fig. A01 — Appendix: discrete variable counts

파일: [A01_discrete_variable_counts.png](../../data/pallet/archive/superseded_runs/_v2_smoke50_9d/eda/paper_continuous/figures_png/A01_discrete_variable_counts.png)

[확인] 분모 50, 21개 이산 변수의 카운트 막대. `(missing)`은 회색으로 분리되며 0이나 False와 절대 합쳐지지
않는다.

```text
pallet_type        Pallet_0 13 / Pallet_1 11 / Pallet_2 12 / Pallet_3 14
scene_preset       outdoor-day 16 / random-mix 12 / indoor 11 / outdoor-night 11
background_asset   parking_lot 29 / industrial 21
aspect             4:3 25 / 16:9 12 / 3:2 8 / 1:1 5
resolution         640x480 25 / 960x540 12 / 720x480 8 / 560x560 5
fx_mode            random 34 / anchor 16
cargo_on           False 28 / True 22
diagnostic_mode    context-rich 15 / controlled-occlusion 15 / cargo-only 10 / clean-static 10
noise_tier         clean 26 / low 19 / medium 5 / (high 0 - 막대 자체가 없음)
v_target           4:4  5:11  6:14  7:16  8:5
V_actual           4:4  5:2   6:17  7:5   8:22
V_vis              4:17 5:6   6:14  7:3   8:10
occluder_side_*    (missing) 35 / left 7 / right 6 / bottom 2   (target/actual 동일)
reject_reason      accepted 50
G1~G5, all_pass    True 50 (각 변수 막대 1개)
```

[확인] `diagnostic_mode`가 처방(10/10/15/15)과 **정확히 일치**한다. Phase 7의 "슬롯이 stratum을 소유한다"
설계가 재시도 횟수와 무관하게 최종 구성비를 지킨 결과다.

[확인] `V_actual`(in-frame 코너 수)은 8이 22건으로 최빈인데, `V_vis`(in-frame + 외부 미가림)는 **4가 17건**
으로 최빈이다. G1 게이트가 `V_vis >= 4`이므로(`v2_realize.py:3784`), 배달 프레임의 34 %가 **G1 경계에 정확히
걸쳐 있다.**

과해석 금지:

- [확인] `noise_tier`에 high 막대가 없는 것은 "high가 0건"이라는 관측이지 "high 경로가 없다"가 아니다.
- [확인] `occluder_side_*`의 `(missing) 35`는 결측이 아니라 **controlled가 아닌 35개 프레임**을 뜻한다.
- [판정] G1~G5/all_pass 막대가 True 하나뿐인 것은 품질 성과가 아니라 **usable 배달셋의 정의**다.

---

## Fig. 10 / 11 / 12는 왜 무정보인가

[판정] 이 세 그림은 "곡선이 평평하고 높으니 파이프라인이 좋다"는 근거로 **절대 쓸 수 없다.**
이유는 통계적 성질이 아니라 **표본 정의 자체**에 있다.

### 1. Tautology — 결과변수가 표본 선정 조건과 같다

[확인] `--completion-mode usable`은 "G1~G5 all_pass + physical_valid + mask 무결성"을 만족하는 프레임만
배달한다. 그런데 fig 10/11/12의 결과변수가 바로 그 `all_pass`, `physical_valid`, `G1_pass`, `G3_pass`다.

```text
outcome            n_total   n_positive   base rate
all_pass              50         50         1.000
physical_valid        50         50         1.000
G1_pass               50         50         1.000
G3_pass               50         50         1.000
```

즉 P(all_pass | x)를 추정하려는데 **모든 x에서 y가 1로 고정**돼 있다. 이건 조건부 확률 추정이 아니라
상수함수의 커널 회귀다.

### 2. 진단 지표가 퇴화를 그대로 보여준다

[확인] 세 figure의 진단값이 전부 퇴화 신호다.

```text
figure   outcome           LOO Brier    선택 bandwidth   신뢰 격자점(n_eff>=20)
10       all_pass          1.45e-32     0.1958 m         0 / 200
10       physical_valid    1.45e-32     0.1958 m         0 / 200
11       all_pass          1.43e-32     0.01264          0 / 200
11       physical_valid    1.43e-32     0.01264          0 / 200
12       all_pass          8.14e-33     0.006163         2 / 200
12       G1_pass           8.14e-33     0.006163         2 / 200
12       G3_pass           8.14e-33     0.006163         2 / 200
```

[확인] LOO Brier ~1e-32는 부동소수점 0이다. 상수를 예측하는 데 오차가 없는 건 당연하다.
그 결과 **bandwidth 선택이 무너진다** — LOO Brier가 모든 bandwidth에서 0이므로 격자의 최솟값이 뽑히고
(fig 11에서 0.01264 = x 범위의 1.3 %, fig 12에서 0.006163), 그 좁은 커널로는 어느 격자점도 유효표본
20을 못 채워 **200개 중 0~2개만 신뢰 구간**이 된다.

### 3. rug이 직접 증언한다

[확인] 세 그림 모두 하단 rug의 `negative` 줄에 눈금이 **하나도 없다**. 그림 안에 "실패가 없다"가 이미
그려져 있다.

### 4. 그럼 이 그림들에서 뭘 읽을 수 있나

[확인] fig 10의 `pnp_eligible_3cell` 곡선(base 0.800, 신뢰 격자점 177/200)과 fig 13 전체는 결과변수가
배달 조건이 **아니므로** 퇴화하지 않았다. 이 두 곳만 읽으면 된다.

[판정] 게이트 판별력(어떤 x에서 게이트가 떨어지는가)을 측정하려면 **실패가 보존된 records-mode 데이터셋**이
필요하다. usable 셋으로는 원리적으로 불가능하다(blocker B9). 다음 500 pilot의 1순위 항목이다.

[확인] 참고로 rejected proposal 57건은 `records_rejected.jsonl`에 전량 보존돼 있고 continuous EDA도
107행을 로드한다. 그러나 frame-level figure는 렌더된 50행만 쓰므로, 현재 analyzer 구성으로는 이 57건이
pass-probability 곡선에 들어가지 않는다.

---

## 이 셋의 특수성 — 그림 밖에서 같이 봐야 하는 것

### noise tier: 처방과 불일치라고 말할 근거 없음, 단 high tier는 미확인

[확인] 분모 50, 처방 확률 clean .60 / low .25 / medium .12 / high .03.

```text
tier      처방     기대 n     실측 n     개별 two-sided exact p
clean     0.60      30.0        26              0.252
low       0.25      12.5        19              0.048
medium    0.12       6.0         5              0.829
high      0.03       1.5         0              0.407
chi2 = 5.58 (df=3), 유의수준 .05 임계 7.815  ->  기각 못 함
```

[판정] low가 개별 p=0.048로 걸리지만 4개 동시비교라 다중성 보정 후 유의하지 않다. quota를 강제하지 않고
프레임마다 독립 추첨하므로 이 정도 요동은 정상이다.

[확인] **high tier 0장은 통계적으로 정상**이다(n=50에서 기대 1.5, P(X=0)=0.22). 하지만 그렇기 때문에
이 셋으로는 high tier 렌더 경로가 실제로 동작하는지 **확인되지 않았다**. 유일한 근거는 Phase 3의 1000-프레임
통계에서 21장이 나온 것이다(blocker B7).

[확인] tier 확률 자체가 `[미검증 시작값]`이다. 실제 센서 통계에서 온 값이 아니다.

### occluder side: bottom/center가 구조적으로 결손

[확인] 먼저 전제 정정 — 처방은 균등이 아니다. `v2_pipeline.SIDE_WEIGHTS = [0.30, 0.30, 0.25, 0.15]`
(left / right / bottom / center)다.

```text
side      처방      render 시도(n=38)    배달(n=15)      시도->배달
left      0.30       14 (0.368)           7 (0.467)        50 %
right     0.30       11 (0.289)           6 (0.400)        55 %
bottom    0.25       12 (0.316)           2 (0.133)        17 %   *
center    0.15        1 (0.026)           0 (0.000)         0 %   *
```

[확인] 배달된 15장에서 `occluder_side_target == occluder_side_actual`이 **15/15**다(records.jsonl에서
행 단위로 재확인). 즉 side 분류 자체는 렌더만 되면 정확하다.

[확인] 문제는 두 단계에서 각각 발생한다.
- **bottom**: 시도 단계에서는 처방(0.25)에 가까운 0.316을 유지하지만, realize 성공률이 17 %(2/12)라
  배달셋에서 0.133으로 반토막 난다.
- **center**: 시도 단계에서 이미 0.026이다. `_occluder_lateral()`(`v2_pipeline.py:994-1027`)이 최대 30회
  resample 루프 안에서 **매 시도마다 side를 다시 뽑고**, center는 contained 조건 때문에 depth가 방정식으로
  고정돼 밴드에 안 들어가면 조용히 `continue` 한다. 실패한 center 추첨이 reject로 기록되지 않고 다른
  side로 대체된다.

[판정] `SIDE_WEIGHTS`는 "그리는 확률"이지 "얻는 비율"이 아니다. 40k에서 그대로 두면 하단 가림은 처방의
약 1/2, 중앙 가림은 거의 0이 된다. [추정 — 50장 표본을 40k로 외삽]

[확인] fig A01의 `occluder_side_*` 패널이 이 결손을 그대로 보여준다(bottom 2, center 막대 없음).

### PnP: exact success 50/50이지만 2건은 기하학적으로 발산

[확인] `audit_pnp_eligibility.py` 결과는 `n_pnp_exact_success = 50/50`이다. 이건 **solver 반환 플래그**
기준이다. 실제 해를 보면 2건이 미러/뒤집힌 해다.

```text
frame    exact reproj mean    trans err        rot err     visible kp   elev
f0038         34.93 px        4.18e+11 cm      146.4 deg        5       8.48 deg
f0049         30.61 px        2.48e+07 cm      160.0 deg        5       4.60 deg
나머지 48     median 9.7e-06 px  median 2.4e-05 cm  median 8.7e-06 deg
```

[확인] 48/50은 GT를 기계 정밀도로 복원하고, 2/50은 success를 반환했지만 해가 뒤집혔다.
**노이즈가 0(exact GT)인데도 발산하므로 노이즈 문제가 아니라 구성(configuration) 문제**다 —
평면 팔레트 + 저앙각(8.5도 / 4.6도) + visible keypoint 5개에서 EPnP가 퇴화한다.

[확인] visible kp 5개인 프레임은 50장 중 18장인데 발산은 2장뿐이다. "5점이면 항상 실패"는 아니다.

[판정] 그래서 이 셋의 PnP 성공률을 **"50/50 성공"이라고만 쓰면 안 된다.** 반드시 "solver 플래그 기준
50/50, 그중 2건은 기하학적으로 발산"이라고 써야 한다. 이 프로젝트 체크리스트의 "flat 물체 PnP" 항목과
직접 연결된 관측이다(평가 코드와 동일한 EPnP를 유지했고 이번 세션에서 바꾸지 않았다).

### tiny / ground-risk / high-noise

```text
항목                     실측         비고
─────────────────────────────────────────────────────────────────────────
tiny_warning             4 / 50 (8 %)  f0008(11.4px/550) f0047(11.9/881)
                                       f0024(14.4/944) f0025(14.9/1451)
                                       G1~G5 전원 통과인데 2/3/4cell 전부 미달
ground-risk 실제 위반    0 / 50        probe 11/frame, fail 0, max step 0.0 m
                                       min floor edge margin 15.484 m
high noise tier          0 / 50        기대 1.5장
projected_size > 1.0     6 / 50 (12 %) max 2.624
```

[판정] tiny 4장은 **의도적으로 게이트로 막지 않았다.** Phase 4에서 임계를 지목할 근거가 나오지 않았고
(1~8 cell 스윕이 매끄러운 단조 감소), 근거 없이 하드 임계를 박으면 데이터를 임의로 버리게 된다.
측정만 하고 판정은 미뤘다(blocker B6).

[확인] ground-risk는 "위험 프레임 0"이 아니라 "**probe 550회 전부 통과, 실제 위반 0**"이다. 거리 상한
10 m가 floor edge 노출을 닫는다는 기하학적 근거가 여기서 재현됐다.

---

## 수치가 어긋나 보이는 지점과 정확한 해석

### camera distance q50: 3.44 vs 3.180

[확인] Phase 9E 보고서 4.5절은 3.44 / 7.11 / 9.33, continuous EDA는 3.180 / 7.072 / 9.295다.
원본 50개 값으로 두 규약을 모두 재계산한 결과, 전자는 `np.quantile(method='higher')`(정렬 26번째 = 3.4362),
후자는 numpy 기본 linear 보간이다. **분포가 다른 게 아니라 분위수 규약이 다르다.** min/max/q05/q25는 일치한다.

[판정] 문서 간 인용 시에는 EDA figure와 일관되게 linear 보간 값을 쓰는 편이 안전하다.

### exact PnP success 50/50 vs 발산 2건

[확인] 앞 섹션 참조. 두 수치는 모순이 아니라 서로 다른 기준이다 — 하나는 solver 반환 플래그, 하나는
복원된 포즈의 기하학적 타당성이다.

### f_explicit 배달 15 vs controlled proposal 38

[확인] fig 09의 왼쪽 두 패널(n=15)과 오른쪽 delivery 패널(38 → 15)은 다른 질문에 답한다.
정밀도 MAE 0.052는 성공 사례 조건부 값이고, delivery 39.5 %가 proposal 소모를 말한다. 둘 다 적어야 한다.

### diagnostic_mode 15/15 vs render attempt 38/17

[확인] 배달 구성비는 처방대로 10/10/15/15인데, 렌더 시도는 controlled 38 / context 17 / cargo 10 /
clean 10으로 편중돼 있다. **구성비는 지켜졌지만 비용은 controlled로 쏠렸다**(전체 렌더 시도의 51 %).

---

## 과해석 금지 목록

- [확인] 이 산출물은 **usable RGB 50장**이다. "500개 완료" 류 표현을 쓰면 안 된다.
- [확인] baseline 2k / 구 500-record와의 비교는 **descriptive**만 가능하다. proposal 스트림, acceptance
  경로, render profile이 전부 다르다.
- [확인] fig 10/11/12의 all_pass / physical_valid / G1 / G3 곡선은 base rate 1.000이라 **무정보**다.
  게이트 품질의 증거로 쓰면 안 된다.
- [확인] fig 07의 r = 1.0000은 모델 성능이 아니라 설정값 왕복 항등식이다.
- [확인] fig 02/08/11/13의 `projected_size_actual`은 12 %(6/50)가 물리적으로 불가능한 >1.0 값이다.
- [확인] fig 04의 kappa는 격자 경계(0.2)에 붙었다. "방위각이 균등하다"의 검정이 아니라 상한 관측이다.
- [확인] fig 06의 f_static(n=1), f_context(n=3) 조건부 분위수는 분포가 아니라 개별 관측이다.
- [확인] fig 14의 KDE 600 px 봉우리는 anchor fx 16개의 점질량을 뭉갠 것이다. ECDF를 봐야 한다.
- [확인] fig 16의 runtime은 배달 프레임만 포함한다. 실패 시도 25건이 빠져 있어 예산 외삽이 과소추정된다.
- [확인] `noise_tier` high 0건, `occluder_side` center 0건은 표본 부족과 solver 결손이 섞여 있다.
  이 셋으로는 두 원인을 분리할 수 없다.
- [확인] "solvePnP 50/50 성공"만 쓰면 안 된다. 2건이 미러 해다.
- [확인] G1~G5 전원 통과는 품질 성과가 아니라 usable 배달셋의 정의다.
- [판정] 이 셋은 **training-ready가 아니다.** 산출물 스스로 `delivery_level: "gate_valid (physical +
  G1..G5); NOT final training-ready"`로 표기한다.

---

## 논문/README에 바로 쓸 수 있는 문장

[확인] "We rendered a 50-frame usable smoke set in which every delivered frame satisfies the physical
validity checks and all five quality gates; the set is therefore a plumbing and prescription-fidelity
check, not a gate-discriminability study."

[확인] "Prescribed camera distance and elevation are realised to machine precision (elevation MAE
2.07e-06 deg, distance mean difference 9.1e-09 m), whereas the projected-size readout is systematically
over-estimated (bias +0.195, 6/50 values above the physically possible ratio of 1.0), which we report as
a measurement defect rather than a rendering error."

[확인] "Source-decomposed occlusion behaves as designed: static-scene occlusion is effectively zero
(P(f_static = 0) = 0.98), cargo occlusion stays below 0.25 conditional on being present (q95 = 0.240),
and explicit occluders dominate the controlled-occlusion frames (median 0.175 given X > 0)."

[확인] "Controlled occlusion is accurate when it is delivered (MAE 0.052, Pearson r 0.907 over 15 frames)
but is delivered for only 15 of 38 proposals (39.5%); the precision and the delivery rate are reported as
separate numbers and are never combined."

[확인] "Pass-probability curves conditioned on distance, projected size and total occlusion are
uninformative on this set by construction: the usable completion mode requires all gates to pass, so the
base rate is 1.000, the leave-one-out Brier score is numerically zero, and 0 of 200 grid points reach the
minimum effective sample size. Gate discriminability requires a records-mode set in which failures are
retained."

[확인] "Exact-ground-truth PnP returned success for all 50 frames, but two of them (both flat, low
elevation at 8.5 deg and 4.6 deg, with five visible keypoints) converged to mirrored solutions with
146 deg and 160 deg rotation error; a solver success flag is therefore not sufficient evidence of pose
recoverability for planar targets."

[확인] "Explicit-occluder side delivery is structurally biased: against a prescription of
left/right/bottom/center = 0.30/0.30/0.25/0.15, the delivered set contains 7 left, 6 right, 2 bottom and
0 center frames, because bottom placements realise at 17% and center placements are silently resampled
away inside the lateral solver."

---

## 다음 결정

[판정] 이 EDA가 다음 단계에 요구하는 것은 아래 5개다(Phase 9E blocker와 연결).

1. **records-mode 500 pilot**으로 fig 10/11/12를 비퇴화 상태로 다시 그린다. usable 셋으로는 원리상 불가능하다(B9).
2. `projected_size_actual`을 화면 클리핑 후 계산하도록 고치고, >1.0 비율이 12 %(9D) / 20 %(500셋)에서
   0으로 떨어지는지 확인한다(B5). 이 수정 전에는 fig 02/08/11/13의 x축을 논문에 쓰지 않는다.
3. controlled-occlusion side별 realize 성공률의 95 % CI를 bottom n>=50, center n>=30으로 구한다(B1/B2).
4. 저앙각(elev<10도) × visible kp 5 조합의 exact-GT PnP 발산율을 500장에서 센다. 유의하면
   `pnp_degenerate` 라벨 플래그를 검토한다. **평가 코드의 solver는 바꾸지 않는다**(B4).
5. high noise tier가 실제로 렌더되는지(기대 15장/500) 확인하고 sigma 밴드·JPEG q 실측을
   `NOISE_TIER_PARAMS`와 대조한다(B7).
