# §7-8 locked 77 replay + G1.6 판정 (정정 기준 적용)

선택 config **K=8 · near-miss threshold 0.0607(p25) · FINE_MAX_EVALS 8 ·
case 당 fine 후보 1개** 로 77건을 **1회** replay 했다 (§25 상한 준수).
replay 는 `DONE 77 cases in 4754.4 s`(exit 0)로 끝났고, 그 뒤 코드·scene·process 를
건드리지 않은 상태에서 **재렌더 없이** 아래 기준으로 재집계했다.

## 0. 적용한 정정 기준

```
1. score_callback 은 runtime 초가 아니라 **reject count** — gate 는 <= 1,722(count).
   시간은 explicit_stage_runtime_s / fine_runtime_s / total_runtime_s 로 별도 보고.
2. K=8 은 per-proposal unique target-seed 최대(8)와 같아 unlimited 와 동작이 같다
   (실측 target_seed_paid_used = 0).  -> 효율 변화는 **fine refinement 에만** 귀속.
3. explicit 품질은 legacy accepted **30건 paired** 로만 비교.  회복분은 섞지 않는다.
4. runtime 은 **77건 전체** — 회복분의 최종 렌더 비용도 빼지 않는다.
5. hard gate 하나라도 실패하면 G2c·G3 를 시작하지 않는다.
```

## 판정

```
G1P6_ACCEPTED_RECALL_PASS      true
G1P6_EXPLICIT_QUALITY_PASS     true
G1P6_POST_CONTEXT_PASS         true
G1P6_LOCKED_EFFICIENCY_PASS    false
──────────────────────────────────────
G1P6_LOCKED_PASS               false   -> G2c·G3 미시작 (기준 5)
```

## 1. 품질 — legacy accepted 30건 paired, **전부 통과**

같은 proposal_index 끼리 짝지어 비교했다. 회복된 4건은 포함하지 않는다.

```
게이트                              값                                       판정
──────────────────────────────────────────────────────────────────────────────────
accepted recall                     30/30                                    PASS
explicit_metrics_available          30/30                                    PASS
explicit visible px > 0             30/30                                    PASS
side match                          30/30                                    PASS
abs error median <= baseline +0.01  0.0360 <= 0.0460 (paired baseline 0.0360)   PASS
abs error p95    <= baseline +0.02  0.1139 <= 0.1339 (paired baseline 0.1139)   PASS
```

★ paired 로 보면 **abs error 가 median·p95 모두 완전히 동일**하다
(median 0.0360 · p95 0.1139). 값이 달라진 case 는 **1건([18])** 뿐이고
그것도 개선 방향이다 (delta mean -0.000224 · max +0.0000).

> 앞선 보고에서 median 0.0375 -> 0.0405 로 적었던 것은 **회복된 4건이 섞인 비교**였다.
> 회복분은 원래 실패하던 프레임이라 오차가 크고, 그것을 baseline 비교에 넣으면
> 품질이 나빠진 것처럼 보인다. paired 로 보면 **품질 변화는 사실상 없다**.

## 2. 효율 — 77건 전체, 2/5 미달

```
게이트                                 baseline    G1.6        기준          판정
──────────────────────────────────────────────────────────────────────────────────
total runtime                          5,020 s     4,642 s     <= 4,518 s    FAIL
score_callback reject **count**        2,026       2,058       <= 1,722      FAIL
accepted median runtime                45.7 s      45.6 s      <= +10%       PASS
실패 프레임 context 낭비                31.8 s      31.5 s      <= 40 s       PASS
candidate budget 상한 인상 없음         —           —           —             PASS
```

### 시간 지표 (개수와 분리해서 보고)

```
지표                          baseline     G1.6        변화
──────────────────────────────────────────────────────────────
total_runtime_s                5,019.5     4,641.6    -7.5%
  accepted 분                  2,127.0     2,149.4    +1.1%
  rejected 분                  2,892.5     2,492.2    -13.8%
explicit_stage_runtime_s       3,495.7     3,191.2    -8.7%
context_stage_runtime_s          939.4       916.1    -2.5%
fine_runtime_s                     0.0        61.2    신규
```

## 3. 효율 변화의 귀속 — 전부 fine refinement 다

```
target_seed_free_used   1,050
target_seed_paid_used   0      <- K=8 이 한 번도 물리지 않았다
```

per-proposal unique target-seed 후보가 실측 **8**(38 proposal)·7(1)이라 K=8 은 unlimited
와 동작이 같다. 따라서 아래 변화는 **모두 fine refinement 의 효과**다.

```
fine triggered / evals / won        8 / 50 / 4
fine runtime                        61.2 s
회복된 case                          [29, 80, 136, 183]
  그 4건의 렌더 비용                  구 295 s -> 신 356 s
accepted 총계                        31 -> 34
```

**총시간이 378초 줄었는데(-7.5%) fine 자체는 61초를 더 썼다.** 순감의 출처는
rejected 분이다 (2,892 -> 2,492 s, -13.8%) — 예전에는 탐색 상한까지 다 쓰고
버려지던 4건이 이제 fine 으로 일찍 성공하기 때문이다. 그래도 -10% 기준에는 못 미친다.

`score_callback` reject count 는 2,026 -> 2,058 로 **+32(+1.6%)** 늘었다.
fine 이 near-miss 후보를 추가로 평가하므로 실패 평가 자체는 늘어난다. gate 1,722 는
baseline(2,026)보다도 낮은 값이라, 이번 두 메커니즘으로는 도달할 수 없는 목표다.

## 4. §8 조치 (기준 5)

- G2c mixed100c **미시작**
- G3 exact20 · dataset-quality probe **미시작**
- 새 heuristic 자동 추가 없음
- 보고 후 중단
