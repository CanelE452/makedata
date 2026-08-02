# mechanism subset (결정적 선정, manual pick 없음)

locked 77 중 **22건** — accepted 7 · rejected 15
상한 24건 · tie-break 는 proposal_index

## 선정 규칙별 case

```
accepted_max_target_seed_free              [183]
accepted_p75_target_seed_free              [26]
accepted_winning_stage:corner-contact-refine [166]
accepted_winning_stage:gate-overlap-refine [113]
accepted_winning_stage:preprobe            [18]
accepted_winning_stage:primary             [93]
accepted_winning_stage:target-seed         [8]
protected_previously_lost                  [113, 166]
reject_f_target_p10                        [55]
reject_f_target_p40                        [30]
reject_f_target_p70                        [242]
reject_f_target_p95                        [29]
reject_max_budget_exhausted                [192]
reject_median_budget_exhausted             [109]
reject_near_miss_gap_p05                   [136]
reject_near_miss_gap_p25                   [229]
reject_near_miss_gap_p50                   [237]
reject_near_miss_gap_p75                   [62]
reject_near_miss_no_fine_p25               [225]
reject_near_miss_no_fine_p75               [184]
reject_projected_size_high                 [7]
reject_projected_size_low                  [173]
reject_projected_size_mid                  [201]
```

## case 목록

```
pi    outcome    winning stage           ts_free  budget_ex  nm  gap
──────────────────────────────────────────────────────────────────────────────
7     rejected                                0          2   0  -
8     accepted   target-seed                  8          0   1  0.0794
18    accepted   preprobe                     8          4   2  0.0134
26    accepted   target-seed                 16          0  11  0.0026
29    rejected                                8          9  10  0.0564
30    rejected                               16          6   0  -
55    rejected                                8         10   0  -
62    rejected                               24         10   3  0.1147
93    accepted   primary                      8          3   2  0.0331
109   rejected                               16          9   0  -
113   accepted   gate-overlap-refine          8          3  16  0.0417
136   rejected                                0          9   2  0.0035
166   accepted   corner-contact-refine        8          1   0  -
173   rejected                               24          9   0  -
183   accepted   primary                     24          7   0  -
184   rejected                               24         11  16  0.0735
192   rejected                               24         12   0  -
201   rejected   target-seed                 16          4   0  -
225   rejected                                8         10   1  0.1840
229   rejected   target-seed                 16          3   3  0.0100
237   rejected                               24         10  32  0.0488
242   rejected                               23         11   0  -
```

