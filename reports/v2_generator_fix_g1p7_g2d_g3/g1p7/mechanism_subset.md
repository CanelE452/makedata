# G1.7 §11 mechanism subset

quantile 기반 결정적 선정 (tie-break=case_id).  manual cherry-pick 없음.

```
지표                                     값
──────────────────────────────────────────────────
cases                                   24 / 24
  accepted (protection)                 11
  rejected                              13
subset CASE_WALL_TIME_S 합              1606.1 s
  그중 SIDE/G1 actionable (중복 없음)   704.5 s  (9 case)
```

## 선정된 case

```
case  outcome    primary signature            wall_s   선정 사유
────────────────────────────────────────────────────────────────────────────────
4     rejected   ONE_MISS_G1                     59.1  rejected:near_feasible_4of5
8     accepted   ACCEPTED                        41.4  accepted:stage=target-seed
18    accepted   ACCEPTED                        35.8  accepted:stage=fine|accepted:fine_recovered
29    accepted   ACCEPTED                        57.6  accepted:fine_recovered
58    rejected   ONE_MISS_SIDE                   65.3  rejected:SIDE_median
69    rejected   ONE_MISS_G2                     96.7  fill:rejected_wall_top
79    rejected   MULTI_CONSTRAINT                32.9  rejected:no_feasible
93    accepted   ACCEPTED                        38.6  accepted:stage=primary
98    rejected   ONE_MISS_G1                    137.0  rejected:G1_p95
109   rejected   ONE_MISS_G1                     45.8  rejected:SIDE+G1_both
112   rejected   ONE_MISS_G1                     32.5  rejected:G1_p05
113   accepted   ACCEPTED                        92.1  accepted:stage=gate-overlap-refine
118   rejected   ONE_MISS_G1                     47.6  rejected:G1_median
136   accepted   ACCEPTED                        27.1  accepted:runtime_p05
147   accepted   ACCEPTED                        72.8  accepted:large_projected
166   accepted   ACCEPTED                        55.0  accepted:stage=corner-contact-refine
187   accepted   ACCEPTED                        36.4  accepted:stage=preprobe
201   rejected   ACCEPTED                        59.8  rejected:downstream_gate
202   accepted   ACCEPTED                        47.1  accepted:runtime_median
209   rejected   ONE_MISS_G1                    104.7  rejected:budget_exhausted_actionable
211   accepted   ACCEPTED                       115.1  accepted:runtime_p95
222   rejected   ONE_MISS_SIDE                  170.7  rejected:SIDE_p95
229   rejected   ACCEPTED                        93.3  fill:rejected_wall_top
238   rejected   ONE_MISS_SIDE                   41.9  rejected:SIDE_p05
```

## 커버리지 확인

```
accepted:fine_recovered                    OK
accepted:large_projected                   OK
accepted:runtime_median                    OK
accepted:runtime_p05                       OK
accepted:runtime_p95                       OK
accepted:stage=corner-contact-refine       OK
accepted:stage=fine                        OK
accepted:stage=gate-overlap-refine         OK
accepted:stage=preprobe                    OK
accepted:stage=primary                     OK
accepted:stage=target-seed                 OK
fill:rejected_wall_top                     OK
rejected:G1_median                         OK
rejected:G1_p05                            OK
rejected:G1_p95                            OK
rejected:SIDE+G1_both                      OK
rejected:SIDE_median                       OK
rejected:SIDE_p05                          OK
rejected:SIDE_p95                          OK
rejected:budget_exhausted_actionable       OK
rejected:downstream_gate                   OK
rejected:near_feasible_4of5                OK
rejected:no_feasible                       OK
```
