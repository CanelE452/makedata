# Phase G2 — 100-frame mixed-mode public smoke

출력 `data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public`
seed 7000 · n=100 usable · completion-mode usable · render-profile dataset-quality ·
samples 64 · noise auto · **mask-profile public** · magenta-max 0.0 · Blender process 1개

세션 2회(10 + 90), 둘 다 exit 0. `usable_delivered=100` `complete=True`
`render_attempts=162` `proposals_drawn=226`.

## 판정

```
G2_MIXED100_PASS = false
```

mode 배분 · mode semantics · 무결성 · accepted 품질은 **전부 통과**했다.
**§16 효율 게이트 3개가 전부 미달**이라 §18 에 따라 Phase G3 를 실행하지 않는다.

## 1. mode 배분 — PASS

```
mode                     기대   실측   판정
────────────────────────────────────────────
clean-static               20     20   PASS
cargo-only                 20     20   PASS
context-rich               30     30   PASS
controlled-occlusion       30     30   PASS
```

10장 블록마다 2/2/3/3 위반 0건.

## 2. mode semantics 전수 — PASS (100/100)

```
mode                    n    semantics   세부
──────────────────────────────────────────────────────────────────────────────
clean-static           20      20/20     explicit 없음 · cargo 안 보임 · context 안 보임
cargo-only             20      20/20     placed 20/20 · visible px>0 20/20
context-rich           30      30/30     visible>=1 30/30 · ratio>0 30/30
controlled-occlusion   30      30/30     placed 30/30 · visible px>0 30/30 · side match 30/30
```

record 의 `mode_semantics_pass` 와 감사에서의 재계산 결과 불일치 0건.

### baseline 과의 대비

```
지표                              baseline(1,449)      mixed100(100)
──────────────────────────────────────────────────────────────────────
cargo placed                      349 / 400            20 / 20
cargo 자체 가시성                  측정 안 함             20 / 20  (>0 px)
context visible                   561 / 600            30 / 30
context placement attempts=0      39 / 600             0 / 30
controlled occluder placed        49 / 49              30 / 30
controlled side match             49 / 49              30 / 30
```

**cargo 가 팔레트를 실제로 가린 프레임은 0/20 이다.** 이는 결함이 아니다 — §4 가
"cargo 가 팔레트를 가리도록 강제하지 않는다"고 못박았고, cargo-only 의 의미는
"cargo 가 화면에 보인다"이지 "팔레트를 가린다"가 아니다.

### cargo 가시성 분포 (최소 임계 후보 — 이번 단계에서 확정하지 않는다)

```
visible pixels (96p 저해상도)   min 16 · median 164 · p95 1,906 · max 1,906   (n=20)
visible ratio                  min 0.002 · median 0.011 · p95 0.16 · max 0.16
n_cargo_visible                min 1 · median 2 · max 2
```

현재 hard gate 는 `>0` 뿐이다. n=20 이라 p95 와 max 가 같은 프레임이며, 최소 임계를
정하기에는 표본이 부족하다. 후보 구간은 8~16 px 이나 **확정하지 않는다**.

## 3. 무결성 — PASS (위반 0)

```
rgb 100 · labels 100 · mask_amodal 100 · mask_visible 100
usable_id 0..99 연속 True · missing 0 · duplicate 0
corrupt 0 · empty amodal 0 · visible 가 amodal 밖 0
magenta 0 · 카메라거리>10m 0 · annotation invalid 0
gate(all_pass) 실패 0
reprojection max 4.55e-13 px  (gate 1e-04 — PASS)
```

public mask 스키마 무변경: `mask_amodal` + `mask_visible` 두 폴더뿐, M1~M3 0개,
cargo/context 가시성용 임시 마스크 잔존 0개.

## 4. controlled accepted 품질 — 부분 PASS / 일부 BLOCKED

```
필수 조건                     결과
────────────────────────────────────────
explicit occluder placed      30 / 30   PASS
explicit visible pixels > 0   30 / 30   PASS
side match                    30 / 30   PASS
explicit visible px 분포      min 187 · median 829 · p95 11,123 · max 12,513
```

### ★ f_target 정확도 게이트는 BLOCKED

`f_explicit_actual` 이 **baseline 49건도, 신규 30건도 모두 None** 이다. public 프로필은
M1~M3 를 렌더하지 않아 마스크 분해로 f_explicit 을 얻을 수 없고, Blender 탐색이 내부에서
쓰는 저해상도 `explicit_actual` 은 record 에 저장되지 않는다.

§15 는 "baseline 필드가 누락돼 정확히 계산할 수 없으면 **임의 f_total 로 대체하지 않고
BLOCKED 로 보고**한다"고 했다. 따라서:

```
CONTROLLED_TARGET_ACCURACY_GATE = BLOCKED  (계산 불가, 대체 금지)
```

**정정**: 이전 세션이 보고한 "controlled target 오차 median −0.003" 은
`f_total_from_mask − f_target` 이었다. f_total 은 cargo·context·static 의 영향이 섞인
전체 가림률이라 explicit solver 정확도가 아니다. 그 수치를 solver 정확도로 읽으면 안 된다.

→ 후속 필요: 저해상도 `explicit_actual`/`explicit_error` 를 record 에 남기면
public 프로필에서도 이 게이트가 계산 가능해진다 (public mask 스키마는 그대로).

## 5. ★ controlled 효율 — 3개 게이트 전부 FAIL

```
지표                                   baseline   mixed100   기준      판정
──────────────────────────────────────────────────────────────────────────────
A usable / 전체 proposal                17.6%      20.8%     >= 35%   FAIL
C 비싼 reject / attempt(mode filter 제외) 54.4%      50.5%     <= 30%   FAIL
runtime  reject / accepted               2.02       1.78      <= 1.0   FAIL
```

세 지표 모두 **baseline 보다는 나아졌지만** 목표에는 못 미쳤다.

### 분모를 나눈 전체 내역

```
controlled proposal 총계                    144
  ├ mode filter skip (0초)                  51
  ├ pure solve reject (0초)                 4
  ├ prefilter 소진 (0초, Blender 미기동)      12
  ├ 비싼 realize reject                     47
  └ usable                                  30

B  usable / attempt(mode filter 제외)       30/93 = 32.3%
B' usable / Blender 를 실제로 연 횟수        30/77 = 39.0%
runtime  reject 3168s / accepted 1781s
usable controlled 1장당 실효 wall time      165.0 s  (baseline 154.9 s)
```

**prefilter 는 설계대로 동작했다** — 12건을 Blender 를 열기도 전에 0초로 버렸고,
baseline recall 은 49/49 를 지켰다. 그런데도 게이트에 못 미친 이유는 아래다.

### 남은 실패의 원인 (n=47 전수 분해)

```
solver fail reason
   bounded_local_search_exhausted            46
   (기타)                                      1

bounded search 후보 기각 사유 (누적 2,114회)
   score_callback              1,032   48.8%   ← 놓을 수는 있는데 목표 가림률을 못 맞춤
   candidate_budget_exhausted    486   23.0%
   support                       378   17.9%
   camera_clearance              129    6.1%
   collision                      89    4.2%
```

`score_callback` 이 절반이다. 이것은 **배치는 유효한데(접지·충돌·클리어런스 통과)
실제로 만들어진 가림률이 목표 오차 안에 안 들어온다**는 뜻이고, 계획 단계 기하만으로는
예측할 수 없다 — prefilter 가 더 손댈 수 있는 종류의 실패가 아니다.

### 어떤 프레임이 실패하는가

```
지표                    비싼 실패(n=47)          accepted(n=30)
────────────────────────────────────────────────────────────────
projected_size          med 0.300  p95 0.901    med 0.160  p95 0.528
camera_distance_m       med 2.58                 med 4.97
f_target                med 0.241                med 0.258
elevation_deg           med 16.6                 med 23.7
candidates_after_prefilter med 128               med 123
realization_attempts    med 20  (상한 21)         med 4
```

**투영 크기가 큰(=카메라가 가까운) 프레임이 실패한다.** 팔레트가 화면을 채우면
A_target = f_target x A_pallet 이 커지고, 접지된 occluder 로 그 면적만 정확히 덮으면서
팔레트를 통째로 삼키지도, 충돌하지도 않는 배치가 사실상 없다.

`candidates_after_prefilter` 는 실패(128)와 성공(123)이 같다 — **prefilter 가 후보를
굶겨서 실패한 것이 아니다.** 실패 프레임은 탐색 상한(21회)까지 다 쓰고 못 찾는다.

⚠️ 투영 크기로 프레임을 거르는 것은 **금지**다(projected-size 분포 변경). 따라서 이
실패는 "걸러서 없앨" 대상이 아니라 "탐색을 고쳐서 줄일" 대상이다.

## 6. runtime 이 baseline 보다 비싸진 이유

```
단계          baseline accepted   mixed100 accepted   baseline reject   mixed100 reject
──────────────────────────────────────────────────────────────────────────────────────
cargo (med)        1.61 s              0.02 s            1.63 s            0.02 s
context (med)     14.17 s             15.78 s           12.41 s           21.03 s
explicit (med)    20.53 s             22.49 s           28.00 s           36.54 s
total (med)       43.96 s             47.63 s           48.43 s           65.01 s
```

⚠️ **like-for-like 비교가 아니다.** interleave 때문에 어떤 proposal 이 controlled 슬롯에
걸리는지가 바뀌었다 — baseline 의 controlled 49장은 proposal 1,900~2,180 구간에서,
신규 30장은 0~226 구간에서 뽑혔다. 즉 FrameSpec 자체가 다르므로 단계 runtime 차이를
코드 변경 탓으로만 돌릴 수 없다. 게이트는 절대 기준이므로 판정에는 영향이 없다.

cargo 단계가 1.61s → 0.02s 로 줄어든 것은 controlled 슬롯에서 cargo 가 꺼진
프레임 비중이 달라진 것이지, cargo 가시성 측정을 뺀 것이 아니다(측정은 추가됐다).

## 7. 정성 검토

```
overlay_review/all/            100장 · 원본 해상도 · canonical archive overlay
                               (cuboid + 9 keypoint + pose 축 + Pitch/Yaw/Roll 패널)
overlay_review/contact_*.png   mode별 4장 (clean 20 · cargo 20 · context 30 · controlled 30)
overlay_review/contact_extremes.png + extreme_cases.csv
```

극단 사례는 손으로 고르지 않았다 — `min/median/max` 고정 quantile 규칙이고 선정 규칙과
frame id 를 CSV 에 남겼다 (cargo visible px · context visible ratio ·
controlled target error · controlled runtime).

## 8. 산출

```
audit_summary.json · records_audit.csv · mode_semantics_audit.csv ·
controlled_efficiency.csv · controlled_quality.csv · runtime_by_stage.csv ·
controlled_expensive_rejects.csv · baseline_vs_mixed100.txt ·
checkpoint10/ (audit.md · audit_summary.json · overlays/) ·
overlay_review/ · logs/checkpoint10.log · logs/mixed100.log
```
