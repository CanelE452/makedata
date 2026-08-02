# §2 score-gap · 후보 예산 감사 (offline, 1회)

대상: locked replay 77건(현재 채택 G1.5 상태) + smoke100b controlled 68건.
**코드를 바꾸기 전** 상태다.

## 1. ★ 수락 조건을 코드에서 읽었다 — score 에는 임계가 없다

`v2_realize` 의 `explicit_score()` 실제 반환:

```python
candidate_accept = bool(
    side_match
    and int(object_visible_stats["visible_pixels"]) >= 8
    and target_error_ok                    # abs_error <= EXPLICIT_TARGET_ABS_TOLERANCE
    and corner_metrics["joint_pass"]       # = G1_pass and G2_pass
)
score = -(error + 1.0*roi_penalty + 0.25*corner_penalty
          + screen_penalty + visibility_penalty)
```

즉 **`score` 는 임계를 넘는 값이 아니라 랭킹용 음수 비용**(높을수록 좋고 최대 0)이고,
수락은 **불리언 4개의 논리곱**이다. "score_callback" reject 는 그 논리곱이 거짓이라는 뜻.

따라서 canonical margin 은 **유일하게 임계가 있는 축**인 목표 오차에 둔다.

```
score_margin = EXPLICIT_TARGET_ABS_TOLERANCE - abs_error   (TOL = 0.12)
   > 0 통과측 · = 0 경계 · < 0 실패측
```

## 2. ★ 목표 오차만으로 막힌 후보는 소수다

수락을 막고 있는 조건 조합 (locked replay, 후보 2,892개):

```
막고 있는 조건                                              후보 수    비율
────────────────────────────────────────────────────────────────────────────
side_match | target_error_ok | corner_joint_pass              778     26.9%
side_match | visible_px | target_error_ok | corner_joint_pass 260      9.0%
corner_joint_pass                                             215      7.4%
target_error_ok  ← 이것만                                     199      6.9%
side_match | corner_joint_pass                                122      4.2%
target_error_ok | corner_joint_pass                           148      5.1%
side_match | target_error_ok                                  152      5.3%
side_match                                                     99      3.4%
그 외                                                          53      1.8%
(막는 조건 없음 = 다른 이유로 reject 되거나 수락)              866     29.9%
```

**fine refinement 이 손댈 수 있는 것은 `target_error_ok` 하나만 막고 있는
199개(6.9%)뿐이다.** 나머지는 side / 코너 / 가시성이 함께 막고 있어
좌표 미세 조정으로 살아나지 않는다 (§4 가 "hard physical reject 를 fine search 로 살리려
하지 않는다"고 한 것과 같은 취지).

## 3. score-gap 분포

```
집합                                    n      p05      p25      median   p75      p95
──────────────────────────────────────────────────────────────────────────────────────
locked · score_callback reject 전체     2026  0.0091  0.0550  0.1138  0.2624  0.6172
locked · near-miss 만                    199  0.0114  0.0607  0.1114  0.1728  0.2624
smoke100b · near-miss 만                 157  0.0089  0.0452  0.0912  0.1599  0.2251
```

⚠️ near-miss 의 median gap 이 0.111 인데 TOL 이 0.12 다 — 즉 median near-miss 는
abs_error 가 허용치의 약 **1.9배**다. `±0.5 × coarse step` 규모의 보정으로 그만큼을
좁힐 수 있다고 가정하면 안 된다. **p25(0.0607) 쪽이 현실적**이고, 그래서 §4 가 지정한
p25 / p50 두 후보를 그대로 sweep 에 넣는다.

## 4. target-seed free eval 감사

```
집합                            n    min  p10  p25  median  p75  p95  max   합계
────────────────────────────────────────────────────────────────────────────────
locked 전체                     77   0    4    8    16      23   24   24   1,050
locked accepted 만              31   0    8    8    8      16   16   24   324
smoke100b accepted 만           30   0    8    8    8      16   16   24   312
```

**accepted 의 median 은 8 이고 p75 는 16, max 는 24 다.** 즉 K=8 이면 accepted 의 절반
이상은 영향이 없지만 상위 25%는 일반 예산에서 8~16을 더 써야 한다 — 그것이 recall 을
깨는지는 **sweep 이 답해야 한다**(K=8 을 정답으로 미리 고정하지 않는다).

중복 geometry 는 canonical key(asset · side · center · yaw · offsets)로 셌고,
target-seed 안에서 **중복은 0**이었다(unique == total). 전체 후보에서는
locked 130개 / smoke100b 118개가 stage 만 다른 중복이다.

## 5. fine_eval_count 는 실제로 0 이다

```
locked 77건 · smoke100b 68건 모두 fine_eval_count = 0 (min=median=max=0)
```

refine / feedback stage 가 한 번도 실행되지 않았다 — coarse 단계에서 이기거나,
아니면 예산이 소진돼 도달하지 못한다.

## 6. ★ "score_callback runtime 1,723초" 는 초가 아니라 **개수**다

직전 보고서의 `F score_callback reject 누적 1,338 -> 1,723` 은 **reject 카운트**였다.
현재 코드에는 score_callback 만 따로 재는 타이머가 없다. 측정 가능한 것은 explicit
단계 전체 시간이다.

```
집합              score_callback reject 수    explicit 단계 runtime 합계
──────────────────────────────────────────────────────────────────────────
locked replay              2,026                    3,496 s
smoke100b                  1,723                    3,020 s
```

따라서 §7·§16 의 "score_callback runtime <= 1,465 / 1,379초" 는 **같은 감축률
(-15% / -20%)을 카운트에 적용**해 판정하고, explicit 단계 초 단위도 함께 보고한다.
숫자를 초로 바꿔 부르지 않는다.

또 하나: §7 은 locked 의 score_callback 기준을 1,723 로 적었지만 **locked 77건의 실제
기준값은 2,026** 이다(1,723 은 smoke100b 값). 두 모집단이 다르므로 아래 sweep·
locked77 판정에서는 **각 모집단의 자기 기준값**과 지시서 절대값을 함께 적는다.

## 7. candidate budget 소진

```
locked 77건 누적 candidate_budget_exhausted   434
smoke100b 68건 누적                            360
```

## 8. 승리 stage

```
locked replay accepted 31건   {"target-seed": 21, "preprobe": 3, "primary": 2, "gate-overlap-refine": 3, "corner-contact-refine": 2}
smoke100b accepted 30건        {"target-seed": 20, "preprobe": 4, "primary": 2, "gate-overlap-refine": 3, "corner-contact-refine": 1}
```

## 9. 산출

```
score_gap_candidates.csv    5,368행 — 후보 단위 (canonical key · blocking · margin)
score_gap_cases.csv         145행 — case 단위 (예산 · stage · runtime · 기하)
target_seed_budget_audit.csv  case 단위 target-seed 예산
score_gap_summary.json      위 수치의 기계 판독본
```
