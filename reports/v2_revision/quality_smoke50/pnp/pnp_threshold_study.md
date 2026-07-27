# PnP eligibility / threshold study (v2 revision, Phase 4)

- dataset: `E:\CODING\GitHub\FoundationPose\data\pallet\_v2_smoke50_9d`
- frames evaluated: 50 (labels present: 50, geometry usable: 50)
- Monte-Carlo: sigma = 1.0, 2.0, 3.0 px, 200 trials/frame/sigma, base seed 20260727 (deterministic)
- solver: `cv2.solvePnPRansac` + `SOLVEPNP_EPNP`, reprojectionError=8.0px, iterationsCount=100 (`scripts/self_training/pnp_solver.py:133-139`, identical to the evaluation path)
- pose correctness: 5.0cm / 5.0deg (`scripts/self_training/metrics.py:143`)
- **no frame is deleted or filtered by this script** - it only measures and adds manifest fields.

## 1. Threshold candidates: where 16 / 24 / 32 px come from

`Deep_Object_Pose/common/models.py:26-40` - the VGG19 trunk keeps 3 `MaxPool2d(2)` and every
later conv has stride 1, so the belief map is 1/8 of the network input (`config/default.yaml:13-14`: 448 -> 56). [확인]

`Deep_Object_Pose/common/utils.py:340,356-372,419` - the training loader takes a **pixel-identity**
`A.RandomCrop(400,400)` of the source PNG and feeds that crop to the network unscaled; only the
keypoints are rescaled into the belief-map grid. There is no image resize between the source
image and the network input, so **1 belief-map cell = 8 source-image pixels**. [확인]

```
candidate   cells   px (source image)
─────────────────────────────────────
2cell       2       16
3cell       3       24
4cell       4       32
```

### Why min(bbox_w, bbox_h) and not the diagonal or the area

A pallet is a flat slab: its short projected side (usually the 0.11-0.15 m height) collapses
first. If that side spans fewer than k belief-map cells, the top and the bottom corner rows
fall into the same cells and their Gaussian peaks merge - the network cannot express them as
separate maxima regardless of how long the pallet looks. The diagonal and the area are both
dominated by the LONG side, so they happily accept a line-like target whose short side is
sub-cell; that is exactly the degenerate case this study is meant to catch. The measurement is
taken over the **visible** keypoints (in-frame AND external occlusion < 0.5), because
those are the only points the network can be supervised on. `mask_m0_min_side_px` and
`bbox_all_min_side_px` are reported next to it as cross-checks.

## 2. Correspondence source (important deviation)

The 3D<->2D correspondence is taken from the label's own `cuboid` (world) and
`projected_cuboid`, which `v2_realize.label()` writes from the SAME `perm_v4` permutation, and
re-expressed in a centroid-centred object frame. A FIXED canonical object frame
(`pnp_solver.make_pallet_keypoints_3d`) does **not** describe these labels: the
`camera_dynamic_0123_v4` convention re-assigns which physical corner is index 0 per frame.
Measured on this dataset: projecting the canonical point set through the labelled
`pose_transform` is off by hundreds of px; solving PnP with it reaches a mean reprojection
error of up to 34.867 px (`canonical3d_exact_reproj_mean_px`). [확인]

Self-check: max |K[R|t]cuboid - projected_cuboid| over all frames = 0.000000 px, i.e. the world-frame
correspondence reproduces the label exactly.

## 3. Frame-level results

```
quantity                       value
────────────────────────────────────
frames                         50
geometry usable                50
exact-GT PnP success           50
physical_valid                 50
gate_valid (G1..G5)            50
tiny_warning                   4
pnp_stress                     26
```

### Monte-Carlo stability by projected size (visible-keypoint bbox min side)

```
bbox_min_side_px    n    PnP ok   fail@1px  fail@2px  fail@3px  trans_q90@2px  rot_q90@2px
───────────────────────────────────────────────────────────────────────────────────────────
[    0,     8)     0      0         n/a       n/a       n/a            n/a          n/a
[    8,    16)     4      4       0.680     0.855     0.938         40.323        3.473
[   16,    24)     6      6       0.553     0.753     0.845         50.685        3.696
[   24,    32)     2      2       0.290     0.423     0.490         15.425        2.293
[   32,    64)    11     11       0.529     0.693     0.782         56.611        7.372
[   64,   128)    11     11       0.235     0.437     0.521         10.910        3.017
[  128,   256)    10     10       0.014     0.095     0.173          2.672        1.020
[  256,   inf)     6      6       0.000     0.014     0.079          2.600        1.897
```

`fail@Npx` = mean fraction of the 200 perturbed solves that miss 5cm-5deg. `trans_q90`/`rot_q90` are medians over frames of the per-frame q90.

## 4. Threshold candidate comparison

```
candidate  thr_px  n_pass  n_fail  fail@2px(pass)  fail@2px(fail)  stress_in_pass  clean_in_fail
──────────────────────────────────────────────────────────────────────────────────────────────
2cell          16      46       4           0.409           0.855              22              0
3cell          24      40      10           0.358           0.793              17              1
4cell          32      38      12           0.354           0.732              16              2
```

- `fail@2px(pass)` = mean 5cm-5deg failure rate among the frames the candidate ACCEPTS (lower is better).
- `stress_in_pass` = accepted frames that are nevertheless flagged `pnp_stress` (the candidate lets an unstable frame through).
- `clean_in_fail` = rejected frames that are NOT `pnp_stress` (the candidate throws away a usable frame).

### Is one of them a data-identified breakpoint? (1..8 cell sweep)

```
cells  thr_px  n_accept  accept_frac  fail@2px(accepted)  step_drop  stress_accepted
──────────────────────────────────────────────────────────────────────────────────────
    1       8        50        1.000               0.445          -               26
    2 *    16        46        0.920               0.409      0.036               22
    3 *    24        40        0.800               0.358      0.051               17
    4 *    32        38        0.760               0.354      0.003               16
    5      40        37        0.740               0.340      0.015               15
    6      48        32        0.640               0.260      0.079               10
    7      56        29        0.580               0.252      0.008                9
    8      64        27        0.540               0.216      0.035                7
```

`*` marks the three candidates. A threshold is only *identified by the data* if the
accepted-set failure rate DROPS at it; a smooth decay means the choice is a pure
yield-vs-quality trade-off with no breakpoint.

median step = 0.035, largest step = 0.079 (at 6 cells, 2.24x the median) -> knee detected: **True**

## 5. Manifest fields added

```
field                          definition
──────────────────────────────────────────────────────────────────────────────────────
physical_valid                 no KNOWN physical violation: rendered, realize_ok,
                               exact_collision_count==0, camera_clearance_pass,
                               support_pass, mask_invariants_pass, ground_continuity_pass,
                               not corrupt_rgb/mask, M0 area>0, camera distance <= limit
                               (Phase 1; recomputed from the label when the record predates
                               Phase 1). Missing inputs are listed in physical_unknown
                               instead of silently passing.
gate_valid                     G1..G5 all_pass (record first, label safety_gates fallback).
pnp_eligible_candidate_Ncell   pnp_exact_success AND bbox_vis_min_side_px >= N*8 px.
tiny_warning                   bbox_vis_min_side_px < 16 px OR mask_m0_area < 256 px^2.
pnp_stress                     exact PnP failed OR sigma=2px 5cm-5deg failure rate > 0.5
                               OR divergence rate > 0.05.
```

## 6. Decision

**확정 불가, 근거 부족.** No hard threshold is fixed by this study. Reasons:

- no candidate delivers a stable accepted set in absolute terms: the best of the three (4cell) still leaves 0.354 mean 5cm-5deg failure rate at sigma=2px, far above the 0.10 target [미검증 시작값]. Passing a size threshold therefore does NOT imply the frame is PnP-reliable, so a size threshold alone cannot be the training-ready criterion.

The three candidates stay side by side in the manifest (`pnp_eligible_candidate_2cell/3cell/4cell`) and `pnp_stress` is reported independently; Phase 7 must keep treating them as candidates, not as a delivered filter.

