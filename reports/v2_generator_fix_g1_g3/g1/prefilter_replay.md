# controlled prefilter — baseline recall replay

baseline `data\pallet\runs\diagnostics\v2_pilot_2k_seed7000_public` · seed 7000

```
accepted frame                49
  winner 보존                 49 / 49   (PASS)
  prefilter 로 프레임 탈락    0   (PASS)
expensive reject frame        94
  Blender 진입 전 조기 탈락   12  (12.8%)
후보 pool                     29,725 -> 20,013  (32.7% 제거)
```

## 제거 사유

```
prefilter_fill_ratio_too_low               4,936
prefilter_floor_support_infeasible         3,634
prefilter_insufficient_projected_area      1,142
```

