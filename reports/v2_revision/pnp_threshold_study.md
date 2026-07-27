# PnP eligibility / threshold study (v2 revision, Phase 4)

- dataset: `E:\CODING\GitHub\FoundationPose\data\pallet\_v2_scene_logic_500_seed7500`
- frames evaluated: 435 (labels present: 435, geometry usable: 435)
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
error of up to 153.507 px (`canonical3d_exact_reproj_mean_px`). [확인]

Self-check: max |K[R|t]cuboid - projected_cuboid| over all frames = 0.000000 px, i.e. the world-frame
correspondence reproduces the label exactly.

## 3. Frame-level results

```
quantity                       value
────────────────────────────────────
frames                         435
geometry usable                435
exact-GT PnP success           414
physical_valid                 363
gate_valid (G1..G5)            364
tiny_warning                   55
pnp_stress                     217
```

### Monte-Carlo stability by projected size (visible-keypoint bbox min side)

```
bbox_min_side_px    n    PnP ok   fail@1px  fail@2px  fail@3px  trans_q90@2px  rot_q90@2px
───────────────────────────────────────────────────────────────────────────────────────────
[    0,     8)    23     19       0.990     0.997     1.000       3064.291      129.268
[    8,    16)    30     27       0.909     0.963     0.982        487.871       38.828
[   16,    24)    28     27       0.810     0.906     0.938        145.338       33.564
[   24,    32)    34     33       0.549     0.737     0.834         32.169        3.741
[   32,    64)    86     85       0.343     0.519     0.631         18.255        2.723
[   64,   128)    87     80       0.155     0.301     0.411          5.760        1.883
[  128,   256)   105    101       0.091     0.172     0.264          3.271        1.698
[  256,   inf)    42     42       0.055     0.115     0.204          2.413        2.357
```

`fail@Npx` = mean fraction of the 200 perturbed solves that miss 5cm-5deg. `trans_q90`/`rot_q90` are medians over frames of the per-frame q90.

## 4. Threshold candidate comparison

```
candidate  thr_px  n_pass  n_fail  fail@2px(pass)  fail@2px(fail)  stress_in_pass  clean_in_fail
──────────────────────────────────────────────────────────────────────────────────────────────
2cell          16     368      67           0.378           0.977             150              0
3cell          24     341      94           0.336           0.951             124              1
4cell          32     308     127           0.293           0.885              94              4
```

- `fail@2px(pass)` = mean 5cm-5deg failure rate among the frames the candidate ACCEPTS (lower is better).
- `stress_in_pass` = accepted frames that are nevertheless flagged `pnp_stress` (the candidate lets an unstable frame through).
- `clean_in_fail` = rejected frames that are NOT `pnp_stress` (the candidate throws away a usable frame).

### Is one of them a data-identified breakpoint? (1..8 cell sweep)

```
cells  thr_px  n_accept  accept_frac  fail@2px(accepted)  step_drop  stress_accepted
──────────────────────────────────────────────────────────────────────────────────────
    1       8       395        0.908               0.418          -              177
    2 *    16       368        0.846               0.378      0.040              150
    3 *    24       341        0.784               0.336      0.042              124
    4 *    32       308        0.708               0.293      0.043               94
    5      40       280        0.644               0.258      0.036               73
    6      48       263        0.605               0.240      0.018               63
    7      56       245        0.563               0.219      0.020               53
    8      64       223        0.513               0.207      0.012               44
```

`*` marks the three candidates. A threshold is only *identified by the data* if the
accepted-set failure rate DROPS at it; a smooth decay means the choice is a pure
yield-vs-quality trade-off with no breakpoint.

median step = 0.036, largest step = 0.043 (at 4 cells, 1.20x the median) -> knee detected: **False**

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

- no breakpoint: over the 1..8 cell sweep the accepted-set 5cm-5deg failure rate decays smoothly (largest step 0.043 = 1.20x the median step 0.036, below the 2.0x knee criterion). Raising the threshold monotonically improves stability and monotonically lowers yield, so the data identifies a trade-off curve, not a particular threshold.
- no candidate delivers a stable accepted set in absolute terms: the best of the three (4cell) still leaves 0.293 mean 5cm-5deg failure rate at sigma=2px, far above the 0.10 target [미검증 시작값]. Passing a size threshold therefore does NOT imply the frame is PnP-reliable, so a size threshold alone cannot be the training-ready criterion.

The three candidates stay side by side in the manifest (`pnp_eligible_candidate_2cell/3cell/4cell`) and `pnp_stress` is reported independently; Phase 7 must keep treating them as candidates, not as a delivered filter.

