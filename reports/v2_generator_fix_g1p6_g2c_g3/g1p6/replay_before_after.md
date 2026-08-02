# locked controlled benchmark — before / after

고정 사례 77건 (old accepted 30 · old expensive reject 47)
replay `data/pallet/runs/diagnostics/_locked77_g1p6` · 같은 seed · 같은 FrameSpec/Plan · dataset-quality

## 1. 필수 게이트
```
accepted recall              30 / 30   PASS
explicit visible px > 0      34 / 34
side match                   34 / 34
explicit_metrics_available   34 / 34
abs error (lowres)           n=34 min 0.002 med 0.043 p95 0.114 max 0.116
```

## 2. 효율
```
total Blender time           4,949 s  ->  4,642 s   (-6.2%)
실패 프레임의 context 낭비    1,151 s  ->  32 s
score_callback reject 누적    1,338  ->  2,058
candidate_budget_exhausted   543  ->  428
realization attempts (med)   17.0  ->  16.0
expensive reject 에서 복구    4 건
```

## 3. 승리 stage 분포 (새 accepted)
```
target-seed                  21
fine                         4
gate-overlap-refine          3
primary                      2
corner-contact-refine        2
preprobe                     2
```

## 4. 새 실패 사유
```
bounded_local_search_exhausted               41
None                                         2
```

