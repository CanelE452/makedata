# Phase G2b — mixed100b 재실행 (overlay 포함)

출력 `data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public`
seed 7000 · n=100 usable · dataset-quality · samples 64 · **mask public** ·
magenta 0.0 · Blender 1개 · **신규 디렉토리(덮어쓰기 없음)**

세션 2회(10 + 90) 둘 다 exit 0 · `usable_delivered=100` `complete=True`
`render_attempts=147` `proposals_drawn=201`.

## 판정

```
G2B_MIXED100_PASS = false
```

mode 배분 · semantics · 무결성 · overlay · **controlled 품질**은 전부 통과했다.
§12 **강한 효율 기준 3개가 모두 미달**이라 §14 대로 false 다. 다만 §12 가 요구한 대로
"숨기지 말고 정확히" 적으면 **효율은 PARTIAL** — runtime 계열은 분명히 개선됐고,
비율 계열(A·C)은 개선 방향이지만 95% 신뢰구간이 겹쳐 유의하다고 말할 수 없다.

## 1. mode 배분 — PASS

```
clean-static 20 · cargo-only 20 · context-rich 30 · controlled-occlusion 30
10장 블록 2/2/3/3 위반 0건
```

## 2. mode semantics — PASS (100/100)

```
mode                    n    semantics   세부
──────────────────────────────────────────────────────────────────────────────
clean-static           20      20/20     explicit 없음 · cargo 안 보임 · context 안 보임
cargo-only             20      20/20     placed 20/20 · visible px>0 20/20
context-rich           30      30/30     visible>=1 30/30 · ratio>0 30/30
controlled-occlusion   30      30/30     placed 30/30 · visible px>0 30/30
                                side match 30/30 · **metrics_available 30/30**
```

record 의 `mode_semantics_pass` 와 감사 재계산 불일치 0건.

## 3. 무결성 — PASS (위반 0)

```
rgb 100 · labels 100 · mask_amodal 100 · mask_visible 100 · overlay 100
usable_id 0..99 연속 True · missing 0 · duplicate 0
corrupt 0 · empty amodal 0 · visible 가 amodal 밖 0
magenta 0 · 거리>10m 0 · annotation invalid 0
gate(all_pass) 실패 0 · reprojection max 4.55e-13 px (gate 1e-04 PASS)
_incomplete_attempts 0
```

public mask 스키마 무변경 — `mask_amodal` + `mask_visible` 두 폴더뿐, M1~M3 0개,
explicit/cargo/context 가시성용 임시 마스크 잔존 0개.

## 4. controlled 품질 (§11) — PASS

baseline 은 **locked replay**(구 smoke100 의 accepted 30건을 현재 코드로 재실행)다.
구 smoke100 record 자체에는 `explicit_abs_error_lowres` 가 없으므로(그때는 필드가
없었다) 같은 지표로 비교하려면 이 방법뿐이다. `f_total` 대체는 하지 않았다.

```
지표                              baseline(30)     smoke100b(30)    게이트
──────────────────────────────────────────────────────────────────────────────
side match                        30/30            30/30           = 30/30   PASS
explicit visible px > 0           30/30            30/30           = 30/30   PASS
explicit_metrics_available        30/30            30/30           = 30/30   PASS
explicit_abs_error_lowres median  0.0375           0.0434          <= base+0.01  PASS
explicit_abs_error_lowres p95     0.1139           0.1139          <= base+0.02  PASS
centroid 오차 median (lowres px)   14.85            13.07
explicit visible px median         895          829
```

**품질 저하 없음** → §12 의 "accepted 품질 저하가 있으면 무조건 FAIL" 조항에 걸리지 않는다.

## 5. controlled 효율 (§12)

```
지표                                   구 smoke100   smoke100b    강한 기준   판정
──────────────────────────────────────────────────────────────────────────────────
A usable / 전체 proposal                 20.8%        24.4%       >=35%      미달
B usable / Blender 실제 시도             39.0%        44.1%       —          —
C 비싼 reject / attempt                  50.5%        48.1%       <=30%      미달
runtime reject / accepted                 1.78         1.33       <=1.0      미달
D controlled 총 Blender time (s)        4,949      4,241      —          -14.3%
E context-before-explicit 낭비 (s)      1,151         44      —          -96.1%  ★
F score_callback reject 누적            1,338        1,723      —          +28.8%
G usable 1장당 실효 wall time (s)         165.0        141.4      —          -14.3%
```

### "분명히 개선"인가 — 지표별로 다르다

```
A  30/144 -> 30/123
   95% CI  (0.150, 0.282)  ->  (0.177, 0.327)   ← 크게 겹친다
C  47/93 -> 38/79
   95% CI  (0.406, 0.605)  ->  (0.374, 0.589)   ← 크게 겹친다
```

A(+3.6pt)·C(−2.4pt)는 방향은 맞지만 n=123/79 에서 **신뢰구간이 겹쳐 유의하다고 말할 수
없다**. 반면 runtime 계열(D −14.3% · E −96.1% · G −14.3% · ratio −25.2%)은 비율 추정이
아니라 합계라 신뢰구간 문제가 없고 폭도 크다.

```
G2B_EFFICIENCY = PARTIAL
   runtime 계열 분명히 개선 (E 가 §3 의 목표를 직접 달성)
   비율 계열(A·C) 개선 방향이나 유의성 미확보
   강한 기준 3개 전부 미달
```

### F 가 늘어난 이유

`score_callback` reject 가 1,338 → 1,723 로 늘었다. G1.5 §5 에서 **해석적 seed 단계를
후보 예산에서 제외**했기 때문이다(그러지 않으면 accepted recall 이 28/30 으로 떨어졌다).
실패 프레임이 후보를 더 많이 평가하는 대신 recall 과 회복을 얻은 trade 다.

## 6. overlay (§8 · §13) — PASS (100/100)

```
overlay 생성            100 / 100      실패 0
크기 == 해당 RGB        100 / 100
정보 패널(Pitch/Yaw/Roll) 100 / 100
우하단 축 범례           100 / 100
overlay_ok(셋 다)       100 / 100
해상도 분포             {'640x480': 48, '720x480': 17, '960x540': 27, '560x560': 8}
```

★ 지시서는 "640x480 원본 크기"라 했지만 이 generator 는 **프레임마다 해상도가 다르다**.
640x480 고정은 나머지 52%를 리사이즈하는 것이라 같은 문장의 "원본 크기"와 모순된다.
그래서 **native 해상도**로 만들고 감사 항목을 "overlay 크기 == 그 프레임 RGB 크기"로
바꿨다 (`size_matches_rgb`).

생성 위치 2곳 — 데이터셋 `…smoke100b_seed7000_public/overlay/` 와 보고서
`g2b/overlay_review/all/`. 정본 `draw_archive_style_overlay()` + `archive_metadata()`
경로만 쓰고, 프레임이 usable 로 확정된 **뒤** label/record 로 후처리 생성하므로
generator semantics 에 영향이 없다.

contact sheet: `sheet_clean` · `sheet_cargo` · `sheet_context` · `sheet_controlled` ·
`sheet_extreme_runtime` · `sheet_extreme_visibility` · `sheet_extreme_error` ·
`overlay_index.csv` · `extreme_cases.csv`(선정 규칙 명시, manual pick 없음).

## 7. 산출

```
audit_summary.json · gates.json · records_audit.csv · mode_semantics_audit.csv ·
controlled_efficiency.csv · controlled_quality.csv · runtime_by_stage.csv ·
checkpoint10/(audit.csv · audit.md · contact_sheet.png · overlays/) ·
overlay_review/(all 100 · sheet_*.png 7 · overlay_audit.json · overlay_index.csv ·
extreme_cases.csv) · logs/(checkpoint10.log · mixed100b.log)
```
