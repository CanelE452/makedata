# §4 controlled-occlusion 전수 감사 — usable_id 1400..1448 (49장, 목표 600)

## Accepted — 기능은 정확히 동작한다

```
occluder placed                    49 / 49    (100%)
occluder visible pixels > 0        49 / 49    (100%)
occluder side  target == actual    49 / 49    (match 100%)
   target  left 16 · right 18 · bottom 15
   actual  left 16 · right 18 · bottom 15

visible_fraction   median 0.770   min 0.500   max 0.982
f_target           median 0.183
f_total (actual)   median 0.230
target 대비 오차    median -0.003   p95 +0.216      ← 중앙값은 거의 정확

occluder asset  utility_box 15 · water_dispenser 13 · chinese_screen 8 ·
                Shelf 5 · construction_sign 2 · Closetmaid 1 …
accepted runtime  median 44.0  p95 85.5  max 111.6 초   합계 2,445 초
```

배치·가시성·측면 일치·목표 가림률 모두 정상이다. **기능 결함이 아니다.**

## ★ 병목 — 분모를 나눠 본 수율

```
분모                              분자   분모    수율     95% Wilson
─────────────────────────────────────────────────────────────────────
usable / 전체 proposal             49    278    17.6%    13.6 ~ 22.5 %
usable / render attempt            49    180    27.2%    21.2 ~ 34.1 %
비싼 reject / render attempt       98    180    54.4%
```

`proposal_skip` 98건은 solve 단계에서 걸러져 **비용이 0초**다. 문제는 나머지다 —
**렌더까지 마친 180회 중 98회(54.4%)가 버려진다.**

## reject 사유별 runtime

```
사유                                            n     합계(초)  median   max
──────────────────────────────────────────────────────────────────────────────
usable_reject: rendered | realize_occluder…     94     4,936    47.9   127.7   ★
gate_fail:G5                                     2       127    63.4    65.9
gate_fail:G3                                     1        50    50.4    50.4
usable_reject: ground_continuity_pass            1        33    33.2    33.2
proposal_skip: mode_requires_explicit_occluder  98         0     0.0     0.0
solve_reject: C1                                15         0     0.0     0.0
solve_reject: d_occ_fail / v_below_min          17         0     0.0     0.0
```

**usable 49장을 얻는 데 reject 로만 4,936초를 썼다** — accepted 전체(2,445초)의 2.0배다.
버려지는 프레임 하나가 median 47.9초로, 살아남는 프레임(44.0초)보다 오히려 비싸다.

## 판독

기능은 정상이고 분포도 의도대로다. 문제는 **비싼 실패가 늦게 발견된다**는 것이다.
`realize_occluder` 단계는 렌더를 마친 뒤에 판정하므로, 실패 비용이 성공 비용과 같다.
남은 551장을 현재 설정으로 채우려면 실측 기준 약 44시간이 필요하다.

산출: `controlled_accepted.csv` · `controlled_rejected.csv` ·
`controlled_runtime_by_reason.csv`
