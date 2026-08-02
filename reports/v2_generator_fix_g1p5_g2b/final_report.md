# Phase G1.5 / G2b 최종 보고 — controlled solver 개선 + mixed100b

## 1. 목적과 최종 판정

목적: (A) explicit 저해상도 측정을 record 에 남겨 public 프로필에서도 품질을 재고,
(B) controlled 에서 explicit 을 context 앞으로 옮겨 실패 비용을 없애고,
(C) target mask 기반 초기 seed 로 탐색을 개선한 뒤, locked benchmark 와 mixed100b 로 검증.

```
판정                                결과       근거
──────────────────────────────────────────────────────────────────────────────
G1P5_EXPLICIT_METRICS_COMPLETE      true       replay 31/31 · smoke100b 30/30
G1P5_ACCEPTED_RECALL_PASS           true       locked replay 30/30
G1P5_QUALITY_PASS                   true       side match·visible·오차 게이트 전부 통과
G1P5_RUNTIME_TARGET(-50%)           missed     +1.4% (locked 77건 기준)
G2B_SEMANTICS_PASS                  true       100/100
G2B_INTEGRITY_PASS                  true       위반 0
G2B_OVERLAY_PASS                    true       100/100 (크기·패널·범례)
G2B_QUALITY_PASS                    true       비열화 없음
G2B_EFFICIENCY                      PARTIAL    runtime 계열 개선 · 비율 계열 유의성 미확보
──────────────────────────────────────────────────────────────────────────────
G2B_MIXED100_PASS                   false      §12 강한 기준 3개 미달
READY_FOR_NEW_PILOT                 false
```

## 2. current branch / HEAD / diff

```
branch main · HEAD 0ebb41cb26feed567558ad9e94e06016c5d17430 (= origin/main)
commit 0 · push 0
작업 시작 시 dirty 19건 전부 직전 단계(G1~G3) 작업물 · UNRELATED 0
```

## 3. baseline lock 확인

```
pilot 1,449장   records.jsonl SHA256 불변 확인   rgb/labels/amodal/visible 각 1,449
smoke100        records.jsonl SHA256 불변 확인   rgb/labels/amodal/visible 각 100
                (report 쪽 overlay 100 · dataset 쪽 overlay 0 — 그대로)
active scene    8cb4109a… 불변
```

두 데이터셋 모두 이번 작업에서 **읽기 전용**이었고, 새 출력은
`v2_mode_semantics_smoke100b_seed7000_public`(신규 디렉토리)로만 썼다.

## 4. G1.5 에서 바꾼 코드 요약

```
v2_realize.py           explicit 단계를 context 앞으로 재배열(P->E->C) · explicit_blocked
                        · 저해상도 실제 가림 통계 · target-seed 단계 · 탐색 계측 ·
                        post-explicit 코너 기준 · 예산 회계에서 target-seed 제외
scene_placement_v2.py   explicit_lowres_metrics() · explicit_search_metrics() ·
                        context_corner_no_regression()
run_v2_scene_logic.py   신규 18 필드를 record 3경로에 전파 · manifest 4열 추가
build_v2_overlay_review.py  --dataset-overlay-dir · --audit · sheet_extreme_* 3종
신규 도구               build_controlled_case_lock.py · replay_controlled_cases.py ·
                        audit_controlled_replay.py
신규 테스트             test_explicit_lowres_metrics.py (23) → unit 865 -> 888
```

## 5. explicit metrics 추가 내용 (§2)

탐색이 **이미 찍는** holdout 두 장(`explicit_before_mask`, `final_mask`)의 차집합에서
숫자만 뽑는다. 새 마스크를 렌더하지도, 파일을 저장하지도 않는다.

```
explicit_metrics_available · explicit_target_pixels · explicit_actual_pixels_lowres
f_explicit_target · f_explicit_actual_lowres · explicit_abs_error_lowres
explicit_target_centroid_u/v · explicit_actual_centroid_u/v_lowres
explicit_target_bbox_u0v0u1v1 · explicit_actual_bbox_u0v0u1v1_lowres
```

이전 단계에서 BLOCKED 였던 controlled 품질 게이트가 **계산 가능해졌다**.
`f_total` 은 이 경로의 입력에도 출력에도 없다(테스트로 고정).

## 6. controlled 순서 변경 내용 (§3)

```
before   cargo -> context -> explicit 탐색   (실패 시 context 비용 전액 낭비)
after    cargo -> explicit_prep -> explicit 탐색 -> (성공 시) context
```

`explicit_blocked` 이면 context 를 아예 시도하지 않는다. 부수 정합성: explicit
baseline 에서 context 제거 · context 예산 측정 시 배치된 occluder 를 가림 ·
swept 예약 대신 실제 배치된 occluder 를 static 으로 전달 · `stage_runtime_s` 에
`explicit_prep` 분리.

★ 이 재배열이 만든 회귀 1건을 잡아 고쳤다 — `explicit_corner_reserve_pass` 는 배치
**전** 예약 계약(`ext_occ<=1`)이라, occluder 를 먼저 놓자 모든 context 후보가 탈락했다
(context median 14 -> 225초). 배치 **후** 기준 `context_corner_no_regression` 으로 교체.

## 7. target-mask-conditioned search (§4)

목표 마스크 통계(centroid·bbox·area)로 만드는 해석적 정렬을 `target-seed` 로
**preprobe 바로 다음**에 배치했다. 같은 offset 을 뒤에서 계산하던 구 `prealign` 은
중복이라 제거했다. 계측 7종(`search_init_strategy` 등) 추가.

```
승리 stage        구 smoke100(30)   locked replay(31)   smoke100b(30)
target-seed/prealign    16                21                20
```

## 8. locked controlled benchmark 결과 (§5)

고정 사례 77건(old accepted 30 · old expensive reject 47)을 같은 seed·FrameSpec·Plan 으로
현재 코드에 다시 통과시켰다.

```
accepted recall              30 / 30    PASS
expensive reject 에서 회복    1 건
explicit visible px > 0      31 / 31
side match                   31 / 31
explicit_metrics_available   31 / 31
abs error (lowres)           med 0.0375 · p95 0.1139
total Blender time           4,949 s -> 5,020 s  (+1.4%)
실패 프레임 context 낭비      1,151 s -> 32 s  (-97%)
```

### recall vs runtime — 실측 3회

```
구성                                      recall   total time   context 낭비
(1) target-seed 추가 + 구 prealign 유지     28/30    -23.3%       1,151 -> 31 s
(2) 구 prealign 제거(중복)                  28/30    -22.1%       1,151 -> 32 s
(3) target-seed 를 예산에서 제외  ★채택      30/30    +1.4%        1,151 -> 32 s
```

(1)(2)에서 잃은 2건은 둘 다 `candidate_budget_exhausted` 였다. 구 파이프라인도 같은
offset 을 같은 빈도로 시도했으므로(위치만 뒤), 해석적 seed 를 예산 회계에서 빼는 것은
**원상 복구**지 게이트 완화가 아니다. §5 가 "미달이어도 recall 우선"이라 (3)을 택했다.

## 9. accepted recall

```
locked replay   30 / 30   PASS   (+ expensive reject 1건 회복)
```

## 10. controlled 품질 지표 (§11)

```
지표                              baseline(30)   smoke100b(30)   게이트         판정
──────────────────────────────────────────────────────────────────────────────────
side match                        30/30          30/30          = 30/30       PASS
explicit visible px > 0           30/30          30/30          = 30/30       PASS
explicit_metrics_available        30/30          30/30          = 30/30       PASS
explicit_abs_error_lowres median  0.0375         0.0434        <= base+0.01  PASS
explicit_abs_error_lowres p95     0.1139         0.1139        <= base+0.02  PASS
centroid 오차 median (lowres px)   14.85          13.07
```

baseline 은 **locked replay 의 accepted 30건**이다 — 구 smoke100 record 에는 이 필드가
없어(그때 필드가 존재하지 않았다) 같은 지표로 비교하려면 이 방법뿐이고, `f_total`
대체는 하지 않았다.

## 11. controlled 효율 지표 (§12)

```
지표                                   구 smoke100   smoke100b    강한 기준   판정
──────────────────────────────────────────────────────────────────────────────────
A usable / 전체 proposal                 20.8%        24.4%       >=35%      미달
B usable / Blender 실제 시도             39.0%        44.1%       —          —
C 비싼 reject / attempt                  50.5%        48.1%       <=30%      미달
runtime reject / accepted                 1.78         1.33       <=1.0      미달
D controlled 총 Blender time (s)        4,949      4,241      —          -14.3%
E context-before-explicit 낭비 (s)      1,151         44      —          -96.1%
F score_callback reject 누적            1,338        1,723      —          +28.8%
G usable 1장당 실효 wall time (s)         165.0        141.4      —          -14.3%
```

A·C 는 방향은 맞지만 95% 신뢰구간이 크게 겹친다
(A 0.150~0.282 -> 0.177~0.327 ·
C 0.406~0.605 -> 0.374~0.589) — **유의하다고 말할 수 없다**.
runtime 계열은 합계라 그 문제가 없고 폭도 크다. 그래서 `G2B_EFFICIENCY = PARTIAL`.

## 12. mode semantics smoke100b 결과

```
clean-static 20/20 · cargo-only 20/20 · context-rich 30/30 · controlled 30/30
cargo placed 20/20 · visible px>0 20/20
context visible>=1 30/30 · ratio>0 30/30
controlled placed 30/30 · visible 30/30 · side match 30/30 ·
           metrics_available 30/30
```

## 13. integrity 결과

```
rgb 100 · labels 100 · mask_amodal 100 · mask_visible 100 · overlay 100
usable_id 0..99 연속 · missing 0 · duplicate 0 · corrupt 0 · empty amodal 0
visible 가 amodal 밖 0 · magenta 0 · 거리>10m 0 · annotation invalid 0
gate(all_pass) 실패 0 · reprojection max 4.55e-13 px · _incomplete_attempts 0
```

## 14. overlay 생성 결과

```
데이터셋   data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public/overlay/  100장
보고서     reports/v2_generator_fix_g1p5_g2b/g2b/overlay_review/all/                          100장
```

정본 `draw_archive_style_overlay()` + `archive_metadata()` 만 사용(직접 구현 없음).
usable 확정 **후** label/record 로 후처리 생성 → generator semantics 무영향.

## 15. overlay audit 결과

```
overlay 생성 100/100 · 실패 0 · 깨진 PNG 0
크기 == 해당 RGB 100/100 · 정보 패널 100/100 · 축 범례 100/100
해상도 분포 {'640x480': 48, '720x480': 17, '960x540': 27, '560x560': 8}
```

★ 지시서의 "640x480 원본 크기"는 이 generator 에 성립하지 않는다(해상도 4종).
640x480 고정은 52%를 리사이즈하는 것이라 "원본 크기"와 모순되므로 **native 해상도**로
만들고 감사 항목을 "크기 == 그 프레임 RGB 크기"로 바꿨다.

## 16. mode별 contact sheet 요약

```
sheet_clean.png 20 · sheet_cargo.png 20 · sheet_context.png 30 · sheet_controlled.png 30
sheet_extreme_runtime.png 3 · sheet_extreme_visibility.png 6 · sheet_extreme_error.png 3
overlay_index.csv · extreme_cases.csv (min/median/max 고정 규칙, manual pick 없음)
```

## 17. baseline 대비 개선 / 미개선

```
개선     explicit 품질 측정 가능(BLOCKED -> 30/30) · 실패 프레임 context 낭비 -96.1% ·
         controlled 총 Blender time -14.3% · usable 1장당 wall time -14.3% ·
         runtime ratio 1.78 -> 1.33 · locked replay 에서 expensive reject 1건 회복
미개선   A 20.8% -> 24.4% (강한 기준 35% 미달, CI 겹침) ·
         C 50.5% -> 48.1% (강한 기준 30% 미달, CI 겹침) ·
         score_callback reject +28.8% (recall 을 지키기 위한 trade)
```

## 18. READY_FOR_NEW_PILOT

```
false
```

exact20(G3) · 500 · 2k · 40k · 논문 Figure 최종본 **전부 시작하지 않았다**.

## 19. 남은 병목

`score_callback` 이 여전히 실패의 주된 사유다(누적 1,723). 이는 "놓을 수는 있는데 목표
가림률을 못 맞춘다"는 뜻이고, 계획 단계 기하로는 예측되지 않는다. 투영 크기가 큰
(카메라가 가까운) 프레임에 몰려 있는데, 투영 크기로 프레임을 거르는 것은 분포 변경이라
금지다.

## 20. 다음 추천 작업

1. **target-seed 예산 면제를 상한 있는 허용치로**. 후보 수는 median 16 · max 24 인데
   보호가 필요했던 두 프레임은 8개만 썼다. 상한을 두면 recall 을 지키면서 F(+28.8%)와
   총시간을 되찾을 여지가 있다. (replay 1회 ≈ 66분)
2. **fine feedback 단계 활성화** — 현재 `fine_eval_count` 가 대부분 0 이다. coarse 에서
   목표에 근접했을 때 미세 조정을 돌리면 `score_callback` 실패를 줄일 수 있다.
3. 위 둘 뒤 mixed100c 재측정 → 강한 기준 재판정 → 통과 시 G3(exact20).

## 21. git diff

```
_docs/history/.last-compact-resume.md              |   8 +-
 _docs/history/2026-08-01.md                        | 158 ++++++
 _docs/history/changelog.md                         |   1 +
 scripts/data_prep/blender/run_v2_scene_logic.py    | 191 ++++++-
 scripts/data_prep/blender/scene_placement_v2.py    | 317 +++++++++++
 .../blender/tests/test_scene_placement_v2.py       |  56 ++
 .../blender/tests/test_usable_completion_mode.py   |  54 +-
 .../tests/test_v2_pilot_resume_reproducibility.py  |  20 +
 scripts/data_prep/blender/v2_pipeline.py           |  50 ++
 scripts/data_prep/blender/v2_realize.py            | 610 ++++++++++++++-------
 10 files changed, 1240 insertions(+), 225 deletions(-)
```

## 22. commit / push 여부

```
commit = 0
push   = 0
```

---

# 마감 표

```
지표                                   값
──────────────────────────────────────────────────────────────────────
accepted replay recall                 30 / 30
baseline controlled A / new A          20.8% / 24.4%
baseline controlled C / new C          50.5% / 48.1%
baseline runtime ratio / new           1.78 / 1.33
baseline score_callback / new          1,338 / 1,723
cargo semantics 20/20                  예 (20/20)
context semantics 30/30                예 (30/30)
controlled semantics 30/30             예 (30/30)
integrity failure count                0
overlay count                          100
overlay broken count                   0
overlay canonical style pass count     100
unit fail / skip                       0 / 0   (888 passed)
integration fail / skip                0 / 0   (31 passed)
golden fail / skip                     0 / 0   (51 passed)
5k digest change                       0  (938f387d · 3cd365ee 불변)
baseline 1449 modified                 0
baseline smoke100 modified             0
public schema changed                  0
exact20 run                            0
500 render                             0
2k render                              0
40k render                             0
model training                         0
model inference                        0
commit                                 0
push                                   0
```
