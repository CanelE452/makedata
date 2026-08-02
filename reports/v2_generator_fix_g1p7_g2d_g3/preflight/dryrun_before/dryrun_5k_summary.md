# v2 bpy-free dry-run — 5000 proposals (tag `5k`)

- generated: 2026-08-01 22:41:29 ; wall 24.8 s
- seed=7000 ; placement_mode=constrained ; stream=`run_v2_scene_logic.iter_proposals` (production draw order)
- budget unit = **proposals** (solve attempts), not accepted frames
- bpy imported: False ; renders: 0 ; images written: 0

> Scope [확인]: this exercises `sample_frame` + `solve_placement` only. It says NOTHING about RGB/mask/lighting quality and is not evidence of training-readiness.

## Checks

```
check                                                verdict  detail
----------------------------------------------------------------------------------------------------------------------
proposals run == requested                           PASS     5000 / 5000
camera_distance_target_m > 10.0 m                    PASS     count=0 ; max=9.999785 m (cap 10.0)
spec-implied distance > 10.0 m (incl. rejected)      PASS     count=0 ; max=9.999785 m
NaN / inf in spec or plan                            PASS     count=0
empty feasible projected-size interval               PASS     RuntimeError=None ; min feasible bins per draw=4
reject camera_distance_out_of_range                  PASS     count=0
same-seed determinism                                PASS     sha256 run1=3cd365eec96d1009… run2=3cd365eec96d1009… ; accepted 4439 vs 4439
solve acceptance >= 70%                              PASS     4439/5000 = 0.8878 (88.78%)
max-attempt exhaustion                               PASS     proposals needed per accepted frame = 1.126 <= budget factor 20
quota starvation (prescribed cell with 0 accepted)   PASS     count=0
unrelated marginal error <= 0.01                     PASS     max=0.00063 (elev_bin=2)
projected-size marginal error <= 0.01 (cap-related axis) PASS     max=0.00018
```

## Reject breakdown (share of proposals, 95% Wilson interval)

```
reason                              count     share               95% CI
------------------------------------------------------------------------
camera_distance_out_of_range            0    0.0000     [0.0000, 0.0008]
v_below_min                           185    0.0370     [0.0321, 0.0426]
d_occ_fail                            187    0.0374     [0.0325, 0.0430]
penetration                             1    0.0002     [0.0000, 0.0011]
resample_exhausted                      0    0.0000     [0.0000, 0.0008]
C1                                    188    0.0376     [0.0327, 0.0432]
C2                                      0    0.0000     [0.0000, 0.0008]
------------------------------------------------------------------------
accepted                             4439    0.8878     [0.8788, 0.8963]
```

## accepted/rejected composition x projected-size bin, and distance | bin

```
bin  label          n   accept   v_below_min   d_occ_fail  penetration resample_exh           C1           C2   d_min   d_q25   d_q50   d_q75   d_max
--------------------------------------------------------------------------------------------------------------------------------------------
0    <10%         892   0.9955             4            0            0            0            0            0    3.48    7.32    8.54    9.48   10.00
1    10-20%       898   0.9889            10            0            0            0            0            0    1.91    4.23    5.69    6.97    9.99
2    20-40%       890   0.9978             0            2            0            0            0            0    1.09    2.24    2.92    3.66    6.43
3    40-60%       931   0.9538             0           25            0            0           18            0    0.71    1.39    1.81    2.18    3.37
4    >60%        1389   0.6386           171          160            1            0          170            0    0.52    1.02    1.21    1.43    2.22
```

Distances are metres over the ACCEPTED plans of that bin (the conditional distribution of camera distance given projected size).

```
elev_bin   range_deg          n   accept   v_below_min   d_occ_fail  penetration resample_exh           C1           C2
------------------------------------------------------------------------------------------------------------
0          0.5-3.0          392   0.9107             7           15            0            0           13            0
1          3.0-8.0          904   0.8838            14           47            0            0           44            0
2          8.0-15.0         986   0.8976            13           35            0            0           53            0
3          15.0-25.0       1000   0.8880            34           37            1            0           40            0
4          25.0-40.0        782   0.9079            23           26            0            0           23            0
5          40.0-60.0        513   0.8655            39           18            0            0           12            0
6          60.0-80.0        423   0.8416            55            9            0            0            3            0
```

## Projected-size axis — prescription / feasibility-conditioned / empirical

```
bin  label    edges            presc  feas_rate  feas_cond  accepted  ratio_min  ratio_max
----------------------------------------------------------------------------------------
0    <10%     [0.00,0.10)      0.200     0.6866     0.1373    0.2000     0.0397     0.1000
1    10-20%   [0.10,0.20)      0.200     1.0000     0.2157    0.2000     0.1000     0.1998
2    20-40%   [0.20,0.40)      0.200     1.0000     0.2157    0.2000     0.2001     0.4000
3    40-60%   [0.40,0.60)      0.200     1.0000     0.2157    0.2000     0.4001     0.6000
4    >60%     [0.60,1.00)      0.200     1.0000     0.2157    0.1998     0.6004     1.0000
```

`feas_rate` = share of draws where the bin was reachable under the 10 m cap. `feas_cond` = prescription renormalised over the feasible bins of each draw (what a memoryless masked sampler would deliver); the accept-time quota deficit pulls the empirical column back to the flat prescription instead.

## Per-axis marginals (accepted set = the set the quota targets)

```
axis             key              presc  accepted  attempted   abs_err       n
------------------------------------------------------------------------------
scene_preset     indoor          0.2500    0.2501     0.2540   0.00006    1110
scene_preset     outdoor-day     0.3000    0.3001     0.2956   0.00007    1332
scene_preset     outdoor-night   0.2500    0.2498     0.2496   0.00017    1109
scene_preset     random-mix      0.2000    0.2000     0.2008   0.00005     888

elev_bin         0               0.0800    0.0804     0.0784   0.00042     357
elev_bin         1               0.1800    0.1800     0.1808   0.00000     799
elev_bin         2               0.2000    0.1994     0.1972   0.00063     885
elev_bin         3               0.2000    0.2000     0.2000   0.00005     888
elev_bin         4               0.1600    0.1599     0.1564   0.00005     710
elev_bin         5               0.1000    0.1000     0.1026   0.00002     444
elev_bin         6               0.0800    0.0802     0.0846   0.00020     356

azimuth_bin      0               0.0833    0.0834     0.0810   0.00002     370
azimuth_bin      1               0.0833    0.0831     0.0852   0.00021     369
azimuth_bin      2               0.0833    0.0834     0.0846   0.00002     370
azimuth_bin      3               0.0833    0.0834     0.0812   0.00002     370
azimuth_bin      4               0.0833    0.0834     0.0842   0.00002     370
azimuth_bin      5               0.0833    0.0834     0.0802   0.00002     370
azimuth_bin      6               0.0833    0.0834     0.0812   0.00002     370
azimuth_bin      7               0.0833    0.0834     0.0842   0.00002     370
azimuth_bin      8               0.0833    0.0834     0.0830   0.00002     370
azimuth_bin      9               0.0833    0.0834     0.0854   0.00002     370
azimuth_bin      10              0.0833    0.0834     0.0880   0.00002     370
azimuth_bin      11              0.0833    0.0834     0.0818   0.00002     370

v_target         4               0.1500    0.1500     0.1514   0.00003     666
v_target         5               0.2500    0.2503     0.2492   0.00028    1111
v_target         6               0.3000    0.2996     0.2938   0.00038    1330
v_target         7               0.2000    0.2000     0.1992   0.00005     888
v_target         8               0.1000    0.1000     0.1064   0.00002     444

f_target_bin     0               0.4000    0.4001     0.3920   0.00009    1776
f_target_bin     1               0.2500    0.2501     0.2476   0.00006    1110
f_target_bin     2               0.2000    0.1998     0.1998   0.00018     887
f_target_bin     3               0.1500    0.1500     0.1606   0.00003     666

aspect           4:3             0.5000    0.4999     0.4828   0.00011    2219
aspect           16:9            0.2500    0.2501     0.2764   0.00006    1110
aspect           3:2             0.1500    0.1500     0.1470   0.00003     666
aspect           1:1             0.1000    0.1000     0.0938   0.00002     444

fx_mode          random          0.7000    0.6999     0.7110   0.00007    3107
fx_mode          anchor          0.3000    0.3001     0.2890   0.00007    1332

cargo_on         0               0.5000    0.5001     0.5008   0.00011    2220
cargo_on         1               0.5000    0.4999     0.4992   0.00011    2219

proj_size_bin    0               0.2000    0.2000     0.1784   0.00005     888
proj_size_bin    1               0.2000    0.2000     0.1796   0.00005     888
proj_size_bin    2               0.2000    0.2000     0.1780   0.00005     888
proj_size_bin    3               0.2000    0.2000     0.1862   0.00005     888
proj_size_bin    4               0.2000    0.1998     0.2778   0.00018     887

pallet_type      Pallet_0        0.2500    0.2498     0.2488   0.00017    1109
pallet_type      Pallet_1        0.2500    0.2501     0.2530   0.00006    1110
pallet_type      Pallet_2        0.2500    0.2501     0.2444   0.00006    1110
pallet_type      Pallet_3        0.2500    0.2501     0.2538   0.00006    1110

position_mode    near-pallet     0.6000    0.6001     0.5980   0.00008    1598
position_mode    near-camera     0.4000    0.3999     0.4020   0.00008    1065
```

## Continuous variables (accepted set unless noted)

```
field                                        n       min       q05       q25       q50       q75       q95       max      mean
----------------------------------------------------------------------------------------------------------------------
camera_distance_target_m                  4439    0.5166    0.9870    1.5579    2.8407    6.3558    9.5578    9.9998    4.0037
camera_distance_spec_m(all proposals)     5000    0.3691    0.7242    1.3019    2.4137    5.8715    9.4700    9.9998    3.6621
proj_size_ratio                           4439    0.0397    0.0783    0.1276    0.3020    0.5478    0.8588    1.0000    0.3608
proj_size_feasible_lower                  4439    0.0344    0.0482    0.0691    0.0861    0.1041    0.1190    0.1374    0.0847
elevation_deg                             4439    0.5003    1.9641    7.6869   17.0828   33.2041   67.7365   79.9793   23.1965
azimuth_deg                               4439    0.0587   18.3811   90.1780  180.0391  270.0313  341.7690  359.9998  180.0939
fx                                        4439  300.3789  335.0689  458.5998  595.6305  605.9065  675.9647  699.8838  539.1524
f_target                                  4439    0.0000    0.0000    0.0000    0.1427    0.2767    0.4160    0.4498    0.1530
exposure_ev                               4439   -2.9999   -2.8509   -2.2089   -1.3980   -0.5801    0.0462    0.1987   -1.3960
```

## Artefacts

- `reports/v2_generator_fix_g1p7_g2d_g3/preflight/dryrun_before/dryrun_5k_joint_eda.png`
- `reports/v2_generator_fix_g1p7_g2d_g3/preflight/dryrun_before/dryrun_5k_joint_eda.pdf`
- `reports/v2_generator_fix_g1p7_g2d_g3/preflight/dryrun_before/dryrun_5k_axis_marginals.csv`
- `reports/v2_generator_fix_g1p7_g2d_g3/preflight/dryrun_before/dryrun_5k_proposals.csv`
- `reports/v2_generator_fix_g1p7_g2d_g3/preflight/dryrun_before/dryrun_5k_summary.md`

