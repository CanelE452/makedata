# v2 bpy-free dry-run — 40000 proposals (tag `40k`)

- generated: 2026-07-27 17:49:52 ; wall 92.1 s
- seed=7000 ; placement_mode=constrained ; stream=`run_v2_scene_logic.iter_proposals` (production draw order)
- budget unit = **proposals** (solve attempts), not accepted frames
- bpy imported: False ; renders: 0 ; images written: 0

> Scope [확인]: this exercises `sample_frame` + `solve_placement` only. It says NOTHING about RGB/mask/lighting quality and is not evidence of training-readiness.

## Checks

```
check                                                verdict  detail
----------------------------------------------------------------------------------------------------------------------
proposals run == requested                           PASS     40000 / 40000
camera_distance_target_m > 10.0 m                    PASS     count=0 ; max=9.999910 m (cap 10.0)
spec-implied distance > 10.0 m (incl. rejected)      PASS     count=0 ; max=9.999910 m
NaN / inf in spec or plan                            PASS     count=0
empty feasible projected-size interval               PASS     RuntimeError=None ; min feasible bins per draw=4
reject camera_distance_out_of_range                  PASS     count=0
same-seed determinism                                PASS     sha256 run1=066daafe45e60357… run2=066daafe45e60357… ; accepted 35792 vs 35792
solve acceptance >= 70%                              PASS     35792/40000 = 0.8948 (89.48%)
max-attempt exhaustion                               PASS     proposals needed per accepted frame = 1.118 <= budget factor 20
quota starvation (prescribed cell with 0 accepted)   PASS     count=0
unrelated marginal error <= 0.01                     PASS     max=0.00008 (v_target=8)
projected-size marginal error <= 0.01 (cap-related axis) PASS     max=0.00002
```

## Reject breakdown (share of proposals, 95% Wilson interval)

```
reason                              count     share               95% CI
------------------------------------------------------------------------
camera_distance_out_of_range            0    0.0000     [0.0000, 0.0001]
v_below_min                          1335    0.0334     [0.0317, 0.0352]
d_occ_fail                           1385    0.0346     [0.0329, 0.0365]
penetration                             9    0.0002     [0.0001, 0.0004]
resample_exhausted                      0    0.0000     [0.0000, 0.0001]
C1                                   1479    0.0370     [0.0352, 0.0389]
C2                                      0    0.0000     [0.0000, 0.0001]
------------------------------------------------------------------------
accepted                            35792    0.8948     [0.8918, 0.8978]
```

## accepted/rejected composition x projected-size bin, and distance | bin

```
bin  label          n   accept   v_below_min   d_occ_fail  penetration resample_exh           C1           C2   d_min   d_q25   d_q50   d_q75   d_max
--------------------------------------------------------------------------------------------------------------------------------------------
0    <10%        7192   0.9953            34            0            0            0            0            0    3.48    7.31    8.55    9.46   10.00
1    10-20%      7204   0.9938            45            0            0            0            0            0    1.81    4.39    5.73    7.02   10.00
2    20-40%      7193   0.9951            18           15            0            0            2            0    0.87    2.21    2.87    3.59    6.78
3    40-60%      7488   0.9559             7          200            1            0          122            0    0.58    1.38    1.78    2.13    3.37
4    >60%       10923   0.6554          1231         1170            8            0         1355            0    0.38    1.03    1.21    1.42    2.22
```

Distances are metres over the ACCEPTED plans of that bin (the conditional distribution of camera distance given projected size).

```
elev_bin   range_deg          n   accept   v_below_min   d_occ_fail  penetration resample_exh           C1           C2
------------------------------------------------------------------------------------------------------------
0          0.5-3.0         3186   0.8986            43          115            1            0          164            0
1          3.0-8.0         7242   0.8897           108          331            3            0          357            0
2          8.0-15.0        7952   0.9002           118          297            2            0          377            0
3          15.0-25.0       7901   0.9061           198          263            1            0          280            0
4          25.0-40.0       6308   0.9076           193          205            1            0          184            0
5          40.0-60.0       4059   0.8820           257          123            1            0           98            0
6          60.0-80.0       3352   0.8544           418           51            0            0           19            0
```

## Projected-size axis — prescription / feasibility-conditioned / empirical

```
bin  label    edges            presc  feas_rate  feas_cond  accepted  ratio_min  ratio_max
----------------------------------------------------------------------------------------
0    <10%     [0.00,0.10)      0.200     0.6898     0.1380    0.2000     0.0361     0.1000
1    10-20%   [0.10,0.20)      0.200     1.0000     0.2155    0.2000     0.1000     0.2000
2    20-40%   [0.20,0.40)      0.200     1.0000     0.2155    0.2000     0.2001     0.4000
3    40-60%   [0.40,0.60)      0.200     1.0000     0.2155    0.2000     0.4000     0.6000
4    >60%     [0.60,1.00)      0.200     1.0000     0.2155    0.2000     0.6000     1.0000
```

`feas_rate` = share of draws where the bin was reachable under the 10 m cap. `feas_cond` = prescription renormalised over the feasible bins of each draw (what a memoryless masked sampler would deliver); the accept-time quota deficit pulls the empirical column back to the flat prescription instead.

## Per-axis marginals (accepted set = the set the quota targets)

```
axis             key              presc  accepted  attempted   abs_err       n
------------------------------------------------------------------------------
scene_preset     indoor          0.2500    0.2500     0.2512   0.00000    8948
scene_preset     outdoor-day     0.3000    0.3000     0.2979   0.00001   10738
scene_preset     outdoor-night   0.2500    0.2500     0.2514   0.00000    8948
scene_preset     random-mix      0.2000    0.2000     0.1995   0.00001    7158

elev_bin         0               0.0800    0.0800     0.0796   0.00001    2863
elev_bin         1               0.1800    0.1800     0.1810   0.00001    6443
elev_bin         2               0.2000    0.2000     0.1988   0.00001    7158
elev_bin         3               0.2000    0.2000     0.1975   0.00002    7159
elev_bin         4               0.1600    0.1600     0.1577   0.00005    5725
elev_bin         5               0.1000    0.1000     0.1015   0.00002    3580
elev_bin         6               0.0800    0.0800     0.0838   0.00002    2864

azimuth_bin      0               0.0833    0.0833     0.0815   0.00001    2983
azimuth_bin      1               0.0833    0.0833     0.0863   0.00002    2982
azimuth_bin      2               0.0833    0.0833     0.0829   0.00001    2983
azimuth_bin      3               0.0833    0.0833     0.0820   0.00001    2983
azimuth_bin      4               0.0833    0.0833     0.0858   0.00002    2982
azimuth_bin      5               0.0833    0.0833     0.0814   0.00001    2983
azimuth_bin      6               0.0833    0.0833     0.0820   0.00001    2983
azimuth_bin      7               0.0833    0.0833     0.0851   0.00002    2982
azimuth_bin      8               0.0833    0.0833     0.0824   0.00001    2983
azimuth_bin      9               0.0833    0.0833     0.0826   0.00002    2982
azimuth_bin      10              0.0833    0.0833     0.0867   0.00001    2983
azimuth_bin      11              0.0833    0.0833     0.0815   0.00001    2983

v_target         4               0.1500    0.1500     0.1515   0.00002    5368
v_target         5               0.2500    0.2500     0.2497   0.00003    8947
v_target         6               0.3000    0.3000     0.2957   0.00001   10738
v_target         7               0.2000    0.2000     0.1977   0.00004    7157
v_target         8               0.1000    0.1001     0.1055   0.00008    3582

f_target_bin     0               0.4000    0.4000     0.3926   0.00001   14317
f_target_bin     1               0.2500    0.2500     0.2480   0.00000    8948
f_target_bin     2               0.2000    0.2000     0.2014   0.00001    7158
f_target_bin     3               0.1500    0.1500     0.1580   0.00001    5369

aspect           4:3             0.5000    0.5000     0.4825   0.00000   17896
aspect           16:9            0.2500    0.2500     0.2763   0.00000    8948
aspect           3:2             0.1500    0.1500     0.1480   0.00001    5369
aspect           1:1             0.1000    0.1000     0.0932   0.00001    3579

fx_mode          random          0.7000    0.7000     0.7115   0.00001   25054
fx_mode          anchor          0.3000    0.3000     0.2885   0.00001   10738

cargo_on         0               0.5000    0.5000     0.5012   0.00000   17896
cargo_on         1               0.5000    0.5000     0.4988   0.00000   17896

proj_size_bin    0               0.2000    0.2000     0.1798   0.00001    7158
proj_size_bin    1               0.2000    0.2000     0.1801   0.00002    7159
proj_size_bin    2               0.2000    0.2000     0.1798   0.00001    7158
proj_size_bin    3               0.2000    0.2000     0.1872   0.00001    7158
proj_size_bin    4               0.2000    0.2000     0.2731   0.00002    7159

pallet_type      Pallet_0        0.2500    0.2500     0.2504   0.00000    8948
pallet_type      Pallet_1        0.2500    0.2500     0.2503   0.00000    8948
pallet_type      Pallet_2        0.2500    0.2500     0.2490   0.00000    8948
pallet_type      Pallet_3        0.2500    0.2500     0.2503   0.00000    8948

position_mode    near-pallet     0.6000    0.6000     0.5986   0.00000   12885
position_mode    near-camera     0.4000    0.4000     0.4014   0.00000    8590
```

## Continuous variables (accepted set unless noted)

```
field                                        n       min       q05       q25       q50       q75       q95       max      mean
----------------------------------------------------------------------------------------------------------------------
camera_distance_target_m                 35792    0.3834    0.9909    1.5417    2.8168    6.3503    9.5250    9.9999    4.0074
camera_distance_spec_m(all proposals)    40000    0.3615    0.7387    1.3083    2.4108    5.9220    9.4689    9.9999    3.6859
proj_size_ratio                          35792    0.0361    0.0777    0.1271    0.3000    0.5481    0.8563    1.0000    0.3608
proj_size_feasible_lower                 35792    0.0344    0.0486    0.0690    0.0852    0.1041    0.1190    0.1375    0.0844
elevation_deg                            35792    0.5003    2.0315    7.6916   17.1007   33.4104   67.4140   79.9987   23.2196
azimuth_deg                              35792    0.0136   18.0400   90.0036  179.9797  270.0019  341.9965  359.9998  179.9729
fx                                       35792  300.0140  333.7945  456.0078  592.4337  605.9065  672.8585  699.9912  537.3680
f_target                                 35792    0.0000    0.0000    0.0000    0.1403    0.2738    0.4175    0.4500    0.1525
exposure_ev                              35792   -2.9999   -2.8435   -2.2063   -1.4020   -0.6062    0.0424    0.1999   -1.4048
```

## Artefacts

- `reports/v2_revision/dryrun_40k_joint_eda.png`
- `reports/v2_revision/dryrun_40k_joint_eda.pdf`
- `reports/v2_revision/dryrun_40k_axis_marginals.csv`
- `reports/v2_revision/dryrun_40k_proposals.csv`
- `reports/v2_revision/dryrun_40k_summary.md`

