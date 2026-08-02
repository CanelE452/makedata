# G1.7 §10 — runtime 기준 병목 집계

primary clock 은 **CASE_WALL_TIME_S** (`replay_wall_s`) 다.  stage runtime 합계는
secondary diagnostic 이며 둘을 섞지 않았다.

```
전체 77 case   CASE_WALL_TIME_S 합   4754.3 s
  accepted 34                        2199.5 s   (median 47.6 s)
  rejected 43                        2554.7 s   (median 57.0 s)
```

## rejected category 별 (CASE_WALL_TIME_S 내림차순)

```
signature                  cases  case%    wall_s   wall%   med_s   p95_s  stage_s  uniq  lowres  budget
────────────────────────────────────────────────────────────────────────────────────────────────────────────
ONE_MISS_SIDE                 10  23.3%     734.0   28.7%    67.3   170.7    716.1  55.0   114.5      10
ONE_MISS_G1                   10  23.3%     651.2   25.5%    49.1   137.0    637.4  56.5   107.5      10
MULTI_CONSTRAINT              11  25.6%     421.6   16.5%    32.9    68.9    405.5    41    68.0      11
ONE_MISS_G2                    3   7.0%     227.5    8.9%    67.7    96.7    223.3    60   135.0       3
TWO_MISS_G1_SIDE               3   7.0%     180.6    7.1%    63.8    71.9    177.4    55   132.0       3
ACCEPTED                       2   4.7%     153.1    6.0%    76.5    93.3    149.1  28.5    90.5       2
ONE_MISS_TARGET                2   4.7%      97.0    3.8%    48.5    53.4     94.6  50.0    62.5       2
TWO_MISS_SIDE_TARGET           2   4.7%      89.8    3.5%    44.9    72.6     88.8  26.0    37.0       2
```

- `stage_s` 는 secondary(stage_runtime 합), `uniq` 는 unique candidate 중앙값,
  `lowres` 는 저해상도 렌더 수 중앙값, `budget` 은 candidate budget 소진 case 수.
- **score_callback count 는 이 표에 넣지 않았다.**  §10·§23 대로 진단값으로만
  두고 PASS/FAIL 판정에 쓰지 않는다.

CSV: `binding_runtime.csv`
