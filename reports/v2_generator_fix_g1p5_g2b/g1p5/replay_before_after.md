# locked controlled benchmark — before / after

고정 사례 77건 (old accepted 30 · old expensive reject 47)
replay `data/pallet/runs/diagnostics/_replay_controlled_g1p5` · 같은 seed · 같은 FrameSpec/Plan · dataset-quality

## 1. 필수 게이트
```
accepted recall              30 / 30   PASS
explicit visible px > 0      31 / 31
side match                   31 / 31
explicit_metrics_available   31 / 31
abs error (lowres)           n=31 min 0.002 med 0.037 p95 0.114 max 0.116
```

## 2. 효율
```
total Blender time           4,949 s  ->  5,020 s   (+1.4%)
실패 프레임의 context 낭비    1,151 s  ->  32 s
score_callback reject 누적    1,338  ->  2,026
candidate_budget_exhausted   543  ->  434
realization attempts (med)   17.0  ->  17.0
expensive reject 에서 복구    1 건
```

## 3. 승리 stage 분포 (새 accepted)
```
target-seed                  21
preprobe                     3
gate-overlap-refine          3
primary                      2
corner-contact-refine        2
```

## 4. 새 실패 사유
```
bounded_local_search_exhausted               44
None                                         2
```

