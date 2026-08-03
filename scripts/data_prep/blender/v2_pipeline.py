"""v2 dataset pipeline — pure sample/solve layer (v2 규약 order-4 split, Phase B).

ADDITIVE. The legacy generators (`gen_dataset_v4.py`, `gen_4pallet_mask.py`) keep
their sample->place->label loop untouched; this module adds the ORDER-4 pure-function
decomposition so a frame plan can be produced and *dry-run audited WITHOUT Blender*.

Pipeline (order 4):
    sample_frame(rng, quota_state) -> (FrameSpec, Picks)  # PURE read-only. Layer-1.
    solve_placement(spec, assets)  -> Plan | Reject       # PURE geometry. Layer-2.
    realize(plan)                                          # Blender. STUB (B3).
    measure(scene)                                         # Blender. STUB (B3).
    render(scene)                                          # Blender. STUB (B3).
    label(spec, plan, meas)                                # Blender. STUB (B3).

QUOTA TIMING (v2 규약 iter-B): sample_frame is pure-read — it only READS quota_state and
returns the chosen bin indices (Picks); the CALLER commits them via advance_quota() at the
right time. generate_specs (sample-only) commits every sample; generate_accepted commits
ONLY on accept, so the ACCEPTED set matches the prescription and rejected cells self-correct.

`sample_frame` and `solve_placement` MUST NOT import bpy (dry-run must run outside
Blender) and MUST be fully deterministic under a seeded rng (same seed => same
FrameSpec). Assets metadata (pallet types, material variants, distractor manifest
with fill_ratio/domain/bbox) load from csv/json/yaml only — no Blender.

Layer-1 stratification (order 5): MARGINAL (per-axis) greedy quota fill — each frame
picks the currently least-filled bin on each axis independently (deficit-weighted,
same pattern as gen_trunc_addon.plan_choice). EXCEPTION: elevation x V is forced by a
2-D JOINT table (low elevation -> low V = more truncation), because those two axes are
physically coupled. Free-random axes (material_variant) are drawn by their config
weights, not stratified.

Run the dry-run (no Blender):
    python scripts/data_prep/blender/v2_pipeline.py --n 1000 --seed 7000
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from collections import namedtuple
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

import numpy as np

# bpy-FREE local modules (verified: blender_math imports only numpy; distractor_pool_v2
# only csv/os). Both are on sys.path[0] for standalone `python v2_pipeline.py`.
from blender_math import build_view_matrix
import distractor_pool_v2 as _dp
import scene_placement_v2 as _sp2

# ---------------------------------------------------------------------------
# Paths (no bpy). Data paths come from the central registry
# (config/synthetic/pallet_paths.yaml via pallet_data_paths).
# ---------------------------------------------------------------------------
import pallet_data_paths as _pdp

_THIS = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = _pdp.load().project_root
DEFAULT_CONFIG = os.path.join(_PROJECT_ROOT, "config", "synthetic", "blender.yaml")
DEFAULT_MANIFEST = _pdp.get("distractor_manifest")

# D435i anchor intrinsics (gen_trunc_addon.py:44 / gen_palletobj_scenarios.py:37).
FX_ANCHOR = 605.9065
# Horizontal sensor width (mm) — blender_config.SENSOR_WIDTH / gen_trunc_addon.SENSOR_W.
# Only used to report the resolution-free focal-mm form of the camera-distance solve.
SENSOR_MM = 36.0


# ===========================================================================
# PRESCRIPTION (order-5 axis distributions).  Values that are prescribed in the
# v2 규약 are literal; values NOT prescribed are marked ASSUMED_UNIFORM.
# ===========================================================================

# --- elevation: 7-bin (v2 규약 Phase C, 2026-07-25). The old 6-bin lumped 25-60deg
#     into one wide bin; Phase C splits that mid/high band (25-40 / 40-60) and rebalances
#     so the informative 8-25deg working range carries 0.58 while very-low grazing and
#     top-down are each still sampled.
#     ★ 잠정 (PROVISIONAL): these per-bin fractions are a working guess. They MUST be
#     re-tuned once the evaluation set's real elevation distribution (from GT pose) is
#     measured on the separate meas machine ([[machine-role-synth-only]]) — do NOT
#     measure elevation here. See _docs/method/v2_domain_randomization.md ("잠정" note).
ELEV_BIN_EDGES = [(0.5, 3.0), (3.0, 8.0), (8.0, 15.0), (15.0, 25.0),
                  (25.0, 40.0), (40.0, 60.0), (60.0, 80.0)]
# 2026-08-03 재조정 — 1만 장 실측이 저앙각으로 심하게 쏠렸다(중앙 17.6°, 20° 미만 55%,
# 50° 이상 13%).  위 "잠정" 주석대로 평가셋 측정 전에는 확정할 수 없으나, 중간 뷰가
# 비는 것은 커버리지 결함이므로 **중간(15~40°)을 봉우리로 하고 양 끝을 꼬리로** 다시
# 배분했다.  극단(0.5~3°, 60~80°)은 남겨 두되 비중을 줄인다.
# 이전 값: [0.08, 0.18, 0.20, 0.20, 0.16, 0.10, 0.08]  (20° 미만 46% 처방)
ELEV_BIN_FRAC = [0.05, 0.10, 0.15, 0.24, 0.22, 0.15, 0.09]  # 잠정, sums to 1.00

# --- V (in-frame corner count) target — gen_trunc_addon.V_FRAC verbatim. --------
V_VALUES = [4, 5, 6, 7, 8]
# 2026-08-03 재조정 — V=4 는 PnP 최소치라 여유가 0 이고, 한 점만 틀려도 자세가 튄다.
# 1만 장 실측에서 visible_kp=4 인 265장 중에는 bbox 최소변이 1.7~2.9px 인 것도 있었다.
# **게이트로 버리지 않고 목표 배분에서 줄인다** — 만들고 버리면 생성 시간이 그대로
# 낭비되지만, 안 뽑으면 비용이 0 이다.
# 이전 값: [0.15, 0.25, 0.30, 0.20, 0.10]
V_FRAC = [0.04, 0.20, 0.30, 0.28, 0.18]

# --- scene_preset — prescribed. -------------------------------------------------
SCENE_PRESETS = ["indoor", "outdoor-day", "outdoor-night", "random-mix"]
SCENE_PRESET_FRAC = [0.25, 0.30, 0.25, 0.20]

# --- projected size — IMAGE-WIDTH-RATIO bins (v2_domain_randomization.md). -------
#     Per-bin fraction = UNIFORM 0.20 (v2 규약 Phase C, kept unchanged). Rationale:
#     the bin edges are (near-)geometric in the width ratio, and width-ratio is the
#     ONLY resize-invariant projected-size axis (§① of the doc). A geometric bin grid
#     sampled uniformly => camera distance drawn log-uniform => scale-invariant coverage
#     (no distance/size band is over/under-represented). So "uniform over geometric bins"
#     is the deliberate prescription here, not an ASSUMED_UNIFORM placeholder.
PROJ_SIZE_EDGES = [(0.0, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 1.0)]
PROJ_SIZE_LABELS = ["<10%", "10-20%", "20-40%", "40-60%", ">60%"]
PROJ_SIZE_FRAC = [0.20, 0.20, 0.20, 0.20, 0.20]  # uniform over geometric bins (prescribed)

# --- camera distance CAP (Phase 1, 2026-07-27). ---------------------------------
# solve_placement inverts the projected-size ratio into a camera distance
#   d = fx * PALLET_W / (proj_size_ratio * image_width),
# so a ratio near 0 (the open lower edge of PROJ_SIZE_EDGES[0]) puts the camera hundreds of
# metres away — physically meaningless for a warehouse pallet and useless for training. The
# cap is enforced at SAMPLING time (sample_frame narrows/masks the ratio bins so no frame can
# ever ask for d > cap) and re-checked as a hard defensive reject in solve_placement.
MAX_CAMERA_DISTANCE_M = 10.0

# --- camera distance FLOOR (2026-08-03, 1만 장 감사 결과). ----------------------
# 상한만 있고 하한이 없어서, ratio 가 큰 프레임은 카메라가 팔레트 안까지 들어갔다.
# 1만 장 실측: projected_size_actual 이 1.0 을 넘은 게 983장(9.83%), 최대 279.69
# (거리 0.82m).  실물을 열어보면 판자가 화면을 가득 채워 무엇인지 알 수 없다.
# 팔레트 긴 변이 1.1~1.27m 이므로 1.5m 아래에서는 프레임에 담기지 않는다.
MIN_CAMERA_DISTANCE_M = 1.5


def proj_size_feasible_upper(fx, image_width, min_distance_m=None):
    """거리 하한이 강제하는 projected-size ratio 상한.

    d = fx * PALLET_W / (ratio * W) 이므로 ratio 가 클수록 카메라가 가까워진다.
    `proj_size_feasible_lower` 의 대칭이다.
    """
    floor_m = MIN_CAMERA_DISTANCE_M if min_distance_m is None else float(min_distance_m)
    return fx * PALLET_W / (floor_m * float(image_width))

# --- azimuth — 30deg x 12 bins uniform. ----------------------------------------
AZIMUTH_NBINS = 12
AZIMUTH_BIN_DEG = 30.0
AZIMUTH_FRAC = [1.0 / AZIMUTH_NBINS] * AZIMUTH_NBINS

# --- f_target (target occlusion fraction) — prescribed. bin 0 is a point mass 0.0.
F_TARGET_EDGES = [(0.0, 0.0), (0.10, 0.20), (0.20, 0.35), (0.35, 0.45)]
F_TARGET_LABELS = ["0", "0.10-0.20", "0.20-0.35", "0.35-0.45"]
F_TARGET_FRAC = [0.40, 0.25, 0.20, 0.15]
# Cut-points for binning the MEASURED f_total (f_actual) into the same 4 bins. Same Phase-C
# principle as luma: f_actual is a downstream measured quantity -> AUDITED by these bins, never
# quota-forced (the sampler can't know f_actual before render; and occluder under-delivery is a
# 2D-alignment/C2 issue, so quota-forcing high-f would just spin render attempts). Labels/audit
# bin frames by f_actual so weak-occluder frames land in their TRUE bin, not the target bin.
F_ACTUAL_CUTS = [0.10, 0.20, 0.35]   # -> bin0 <0.10, bin1 [0.10,0.20), bin2 [0.20,0.35), bin3 >=0.35


def projected_size_actual(uv_points, image_width):
    """MEASURED projected width ratio = (max u - min u)/image_width over the 8 cuboid corners.

    Single-sourced here so the Blender label (v2_realize.label) and the bpy-free record
    (run_v2_scene_logic) report the identical quantity. KNOWN LIMITATION (unchanged in this
    phase): corners that fall off-screen or behind the camera still contribute their raw u, so
    a truncated frame can over-read. Returns None when unmeasurable."""
    if uv_points is None or not image_width:
        return None
    xs = [float(p[0]) for p in uv_points if math.isfinite(float(p[0]))]
    return (max(xs) - min(xs)) / float(image_width) if xs else None


def f_actual_bin(f_total):
    """Bin a MEASURED f_total into the 4 f bins (None -> None = unmeasurable)."""
    if f_total is None:
        return None
    f = float(f_total)
    for i, c in enumerate(F_ACTUAL_CUTS):
        if f < c:
            return i
    return len(F_ACTUAL_CUTS)

# --- position_mode — CONDITIONAL (only when f_target > 0). prescribed. ----------
POSITION_MODES = ["near-pallet", "near-camera"]
POSITION_MODE_FRAC = [0.60, 0.40]

# --- cargo on/off — prescribed 50/50. -------------------------------------------
CARGO_LABELS = ["off", "on"]
CARGO_FRAC = [0.50, 0.50]

# --- luma (v2 규약 Phase C 2026-07-25): the luma_bin QUOTA axis is REMOVED. Forcing a
#     uniform quota over a downstream *measured* quantity (rendered brightness) is wrong —
#     the sampler cannot know luma_actual before render. Instead we sample a control input,
#     exposure_ev = U(-3.0, +0.2) EV (dark-biased: warehouses/night skew dark, +0.2 caps
#     over-exposure). luma_actual is MEASURED in Layer-3 measure() (B3 stub) and only
#     AUDITED (coverage, no quota) against LUMA_ACTUAL_EDGES: each 0-255 bin must reach
#     >= LUMA_ACTUAL_MIN_COVER of frames (soft check, never rejects/forces a frame).
EXPOSURE_EV_RANGE = (-3.0, 0.2)
LUMA_ACTUAL_EDGES = [(0, 35), (35, 80), (80, 140), (140, 256)]   # mean-luma 0..255 bins
LUMA_ACTUAL_LABELS = ["<35", "35-80", "80-140", ">140"]
LUMA_ACTUAL_MIN_COVER = 0.10   # each bin must hold >=10% of frames (coverage audit only)

# --- aspect / resolution — prescribed. -----------------------------------------
ASPECTS = [
    ("4:3", (640, 480)),
    ("16:9", (960, 540)),
    ("3:2", (720, 480)),
    ("1:1", (560, 560)),
]
ASPECT_FRAC = [0.50, 0.25, 0.15, 0.10]

# --- fx — prescribed: 70% U[300,700]px random / 30% fixed D435i anchor. ---------
FX_MODES = ["random", "anchor"]
FX_FRAC = [0.70, 0.30]
FX_RANDOM_RANGE = (300.0, 700.0)


# ===========================================================================
# elevation x V JOINT table (the only forced joint; all other axes are marginal).
# ===========================================================================
def build_elev_v_joint(sigma=0.35, use_feasibility=True):
    """Construct P(elev_bin, V) whose row-marginal == ELEV_BIN_FRAC and col-marginal
    == V_FRAC, with a low-elevation->low-V coupling.

    Method (reported):
      1. bias[e][v] = gaussian_band(rank(e), rank(v)) * feasibility(e, v)
           gaussian_band couples elevation-rank to V-rank (low->low, high->high):
               exp(-((e/(E-1) - v/(V-1))**2) / (2*sigma**2))
           feasibility = gen_trunc_addon._v_feasibility_weight (odd V hard at low elev).
      2. Iterative Proportional Fitting (IPF / Sinkhorn) rescales rows then cols to
         the two prescribed marginals until convergence. IPF preserves the bias
         "shape" while forcing BOTH marginals exactly (any two marginals over a grid
         admit a joint, so this always converges from a strictly-positive bias).
    Returns joint[e][v] (list of lists), rows sum to ELEV_BIN_FRAC, cols to V_FRAC.
    """
    E, Vn = len(ELEV_BIN_FRAC), len(V_VALUES)

    def feasibility(e_idx, v):
        # gen_trunc_addon._v_feasibility_weight: low = elevation < 15deg = bins 0,1,2.
        if v == 8:
            return 1.0
        low = e_idx <= 2
        even = (v % 2 == 0)
        if low:
            return 1.0 if even else 0.35
        return 1.0 if not even else 0.6

    bias = [[0.0] * Vn for _ in range(E)]
    for e in range(E):
        re = e / (E - 1)
        for j, v in enumerate(V_VALUES):
            rv = j / (Vn - 1)
            band = math.exp(-((re - rv) ** 2) / (2.0 * sigma * sigma))
            f = feasibility(e, v) if use_feasibility else 1.0
            bias[e][j] = band * f

    joint = [row[:] for row in bias]
    for _ in range(200):
        # rows -> ELEV_BIN_FRAC
        for e in range(E):
            s = sum(joint[e])
            if s > 0:
                k = ELEV_BIN_FRAC[e] / s
                joint[e] = [x * k for x in joint[e]]
        # cols -> V_FRAC
        for j in range(Vn):
            s = sum(joint[e][j] for e in range(E))
            if s > 0:
                k = V_FRAC[j] / s
                for e in range(E):
                    joint[e][j] *= k
        # convergence check on row sums
        err = max(abs(sum(joint[e]) - ELEV_BIN_FRAC[e]) for e in range(E))
        if err < 1e-12:
            break
    return joint


ELEV_V_JOINT = build_elev_v_joint()


# ===========================================================================
# ASSETS (pure loaders — no bpy).
# ===========================================================================
def _load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # optional
        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


@dataclass
class Assets:
    pallet_types: list           # ["Pallet_0", ...] — all blend pallet types
    color_group_for_model: dict  # pallet -> "plastic"/"wood"
    color_variants: dict         # family -> [{"name","weight"}, ...]
    distractors: list            # manifest records (name/size_class/fill_ratio/domain/bbox)


def load_assets(config_path=DEFAULT_CONFIG, manifest_path=DEFAULT_MANIFEST) -> Assets:
    cfg = _load_config(config_path)
    assets_cfg = cfg["assets"]
    appear = cfg["appearance"]
    pallet_types = [str(n) for n in assets_cfg["pallet_names"]]
    group = {str(k): str(v) for k, v in appear["pallet_color_group_for_model"].items()}
    variants = {
        str(fam): [
            {"name": str(v["name"]), "weight": float(v.get("weight", 1.0))}
            for v in vlist
        ]
        for fam, vlist in appear["pallet_color_variants"].items()
    }
    distractors = _load_manifest(manifest_path)
    return Assets(pallet_types, group, variants, distractors)


def _load_manifest(manifest_path):
    records = []
    if not os.path.isfile(manifest_path):
        return records
    with open(manifest_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue

            def _f(key):
                try:
                    return float(row.get(key))
                except (TypeError, ValueError):
                    return None

            records.append({
                "name": name,
                "size_class": (row.get("folder") or "").strip().lower(),
                "bbox_m": (_f("bx"), _f("by"), _f("bz")),
                "fill_ratio_mean": _f("fill_ratio_mean"),
                "dp_indoor": (row.get("dp_indoor") or "1").strip() in ("1", "true", "True"),
                "dp_outdoor_day": (row.get("dp_outdoor_day") or "1").strip() in ("1", "true", "True"),
                "dp_outdoor_night": (row.get("dp_outdoor_night") or "1").strip() in ("1", "true", "True"),
            })
    return records


# ===========================================================================
# FrameSpec (serializable, dry-run logging).
# ===========================================================================
@dataclass
class FrameSpec:
    frame_index: int
    seed: int
    # -- pallet / appearance --
    pallet_type: str
    material_variant: Optional[str]      # free-random by config weight (not stratified)
    material_family: str
    # -- scene / illumination --
    scene_preset: str                    # indoor|outdoor-day|outdoor-night|random-mix
    exposure_ev: float                   # U(-3.0,+0.2) EV control input (luma_bin quota removed)
    # -- camera geometry --
    elev_bin: int                        # 0..6 (7-bin elevation)
    elevation_deg: float
    azimuth_bin: int                     # 0..11
    azimuth_deg: float
    v_target: int                        # 4..8 (in-frame corner count target; joint w/ elev)
    proj_size_bin: int                   # 0..4 (image-width ratio)
    proj_size_ratio: float               # target pallet width / image width
    proj_size_feasible_lower: float      # smallest ratio whose camera distance <= the cap
    # -- intrinsics / sensor --
    aspect: str
    resolution: tuple                    # (W, H)
    fx_mode: str                         # random|anchor
    fx: float                            # focal px
    # -- occlusion / placement --
    f_target_bin: int                    # 0..3
    f_target: float                      # target occlusion fraction (0 => no occluder)
    position_mode: Optional[str]         # near-pallet|near-camera|None (None iff f_target==0)
    # -- cargo --
    cargo_on: bool                       # count/shape/placement follow BOX_RANDOMIZATION (realize)
    cargo_seed: int                      # sub-seed so realize()'s box randomization is reproducible

    def to_dict(self):
        d = asdict(self)
        d["resolution"] = list(self.resolution)
        return d


# ===========================================================================
# QuotaState (order-5 greedy fill).
# ===========================================================================
@dataclass
class QuotaState:
    pallet: list
    scene_preset: list
    proj_size: list
    azimuth: list
    f_target: list
    position_mode: list        # conditional (only counted when f_target > 0)
    cargo: list
    aspect: list
    fx: list
    joint: list                # 2-D [elev][v] counts
    n: int = 0

    @staticmethod
    def new(assets: Assets):
        return QuotaState(
            pallet=[0] * len(assets.pallet_types),
            scene_preset=[0] * len(SCENE_PRESETS),
            proj_size=[0] * len(PROJ_SIZE_EDGES),
            azimuth=[0] * AZIMUTH_NBINS,
            f_target=[0] * len(F_TARGET_EDGES),
            position_mode=[0] * len(POSITION_MODES),
            cargo=[0] * len(CARGO_LABELS),
            aspect=[0] * len(ASPECTS),
            fx=[0] * len(FX_MODES),
            joint=[[0] * len(V_VALUES) for _ in range(len(ELEV_BIN_FRAC))],
        )


def _deficit_pick(frac, counts, rng, mask=None):
    """Greedy least-filled pick: choose among under-quota bins weighted by deficit
    (same pattern as gen_trunc_addon._weighted_pick over the deficit vector). Falls
    back to uniform when every bin is at/over quota. Deterministic under a seeded rng.

    mask: optional per-bin feasibility flags. A masked-out bin is not physically realisable
    for this frame (e.g. a projected-size bin whose camera distance would exceed the cap), so
    it gets selection probability 0; the deficit weights of the remaining bins are untouched,
    which keeps the greedy quota logic intact — an infeasible bin simply accrues deficit and
    is re-targeted on the next frame whose intrinsics make it feasible.
    """
    n = sum(counts)
    deficits = [max(0.0, f * (n + 1) - c) for f, c in zip(frac, counts)]
    if mask is None:
        allowed = list(range(len(frac)))
    else:
        allowed = [i for i, m in enumerate(mask) if m]
        if not allowed:
            raise ValueError("_deficit_pick: every bin is masked out as infeasible")
        deficits = [d if m else 0.0 for d, m in zip(deficits, mask)]
    tot = sum(deficits)
    if tot <= 0:
        return allowed[rng.randrange(len(allowed))]
    r = rng.uniform(0.0, tot)
    acc = 0.0
    for i in allowed:
        acc += deficits[i]
        if r <= acc:
            return i
    return allowed[-1]


def _deficit_pick_2d(joint_frac, counts, rng):
    """Greedy least-filled pick over a flattened 2-D joint table -> (row, col)."""
    E = len(joint_frac)
    Vn = len(joint_frac[0])
    n = sum(sum(r) for r in counts)
    flat_frac, flat_def, cells = [], [], []
    for e in range(E):
        for v in range(Vn):
            f = joint_frac[e][v]
            d = max(0.0, f * (n + 1) - counts[e][v])
            flat_frac.append(f)
            flat_def.append(d)
            cells.append((e, v))
    tot = sum(flat_def)
    if tot <= 0:
        return cells[rng.randrange(len(cells))]
    r = rng.uniform(0.0, tot)
    acc = 0.0
    for d, cell in zip(flat_def, cells):
        acc += d
        if r <= acc:
            return cell
    return cells[-1]


def _weighted_choice(items, weights, rng):
    tot = sum(weights)
    if tot <= 0:
        return rng.choice(items)
    r = rng.uniform(0.0, tot)
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if r <= acc:
            return it
    return items[-1]


# ===========================================================================
# LAYER-1: sample_frame  (PURE, no bpy, deterministic).  -- completed (B1).
# ===========================================================================
# The bin indices sample_frame chose, so the CALLER can advance the quota (see below).
Picks = namedtuple("Picks", "pi spi e_idx v_idx ai psi aspi fxi fti pm_idx ci")


def advance_quota(qs: QuotaState, picks: Picks):
    """Commit one frame's bin choices into the quota counts. The CALLER decides WHEN:
    the sample-only path (generate_specs) commits every sample; the accept-time path
    (generate_accepted) commits ONLY when solve_placement accepts, so rejected cells stay
    under-filled and get re-targeted on the next draw (self-correcting stratification)."""
    qs.pallet[picks.pi] += 1
    qs.scene_preset[picks.spi] += 1
    qs.joint[picks.e_idx][picks.v_idx] += 1
    qs.azimuth[picks.ai] += 1
    qs.proj_size[picks.psi] += 1
    qs.aspect[picks.aspi] += 1
    qs.fx[picks.fxi] += 1
    qs.f_target[picks.fti] += 1
    if picks.pm_idx is not None:
        qs.position_mode[picks.pm_idx] += 1
    qs.cargo[picks.ci] += 1
    qs.n += 1


def proj_size_feasible_lower(fx, image_width, max_distance_m=None):
    """Smallest projected width-ratio whose inverted camera distance still obeys the cap.

    solve_placement uses d = fx * PALLET_W / (ratio * image_width); requiring d <= cap gives
    ratio >= fx * PALLET_W / (image_width * cap). (PALLET_W is bound further down in this
    module — it exists by the time sample_frame runs.)
    """
    cap = MAX_CAMERA_DISTANCE_M if max_distance_m is None else float(max_distance_m)
    return float(fx) * PALLET_W / (float(image_width) * cap)


def sample_frame(rng: random.Random, quota_state: QuotaState, assets: Assets,
                 frame_index: int = -1, seed: int = -1):
    """Sample one FrameSpec by marginal greedy quota fill (+ elev x V joint).

    PURE & side-effect-free on the quota: sample_frame only READS quota_state (deficit
    picks) and NEVER advances it (v2 규약 iter-B — truly pure). It returns (spec, picks);
    the caller advances the quota via advance_quota(qs, picks) at the chosen time (every
    sample, or accept-only). Same (rng state, quota_state) => same (spec, picks).
    """
    qs = quota_state

    # -- pallet_type: all blend types uniform --
    pi = _deficit_pick([1.0 / len(assets.pallet_types)] * len(assets.pallet_types),
                        qs.pallet, rng)
    pallet_type = assets.pallet_types[pi]
    family = assets.color_group_for_model.get(pallet_type, "plastic")

    # -- material_variant: FREE RANDOM by config weight (not stratified) --
    vlist = assets.color_variants.get(family) or assets.color_variants.get("plastic", [])
    if vlist:
        v = _weighted_choice(vlist, [x["weight"] for x in vlist], rng)
        material_variant = v["name"]
    else:
        material_variant = None

    # -- scene_preset --
    spi = _deficit_pick(SCENE_PRESET_FRAC, qs.scene_preset, rng)
    scene_preset = SCENE_PRESETS[spi]

    # -- exposure_ev: free-random control input (luma_bin quota removed; luma_actual is
    #    measured & coverage-audited in Layer-3, not quota-forced here) --
    exposure_ev = rng.uniform(*EXPOSURE_EV_RANGE)

    # -- elevation x V JOINT --
    e_idx, v_idx = _deficit_pick_2d(ELEV_V_JOINT, qs.joint, rng)
    elo, ehi = ELEV_BIN_EDGES[e_idx]
    elevation_deg = rng.uniform(elo, ehi)
    v_target = V_VALUES[v_idx]

    # -- azimuth (12 x 30deg uniform) --
    ai = _deficit_pick(AZIMUTH_FRAC, qs.azimuth, rng)
    azimuth_deg = rng.uniform(ai * AZIMUTH_BIN_DEG, (ai + 1) * AZIMUTH_BIN_DEG)

    # -- aspect / resolution -- (BEFORE projected size: the camera-distance cap below needs
    #    the image width and fx, so the intrinsics must be settled first.)
    aspi = _deficit_pick(ASPECT_FRAC, qs.aspect, rng)
    aspect, resolution = ASPECTS[aspi]

    # -- fx --
    fxi = _deficit_pick(FX_FRAC, qs.fx, rng)
    fx_mode = FX_MODES[fxi]
    fx = FX_ANCHOR if fx_mode == "anchor" else rng.uniform(*FX_RANDOM_RANGE)

    # -- projected size (image-width ratio), capped by MAX_CAMERA_DISTANCE_M --
    #    solve_placement will invert this ratio into d = fx*PALLET_W/(ratio*W), so ratios
    #    below `lower` are unreachable for THIS frame's intrinsics. Bins entirely below the
    #    floor are masked out (probability 0, no clamping => no point mass at the floor);
    #    a partially-feasible bin is narrowed to [max(lo, lower), hi) and sampled
    #    continuous-uniform inside the narrowed interval.
    lower = proj_size_feasible_lower(fx, resolution[0])
    # 거리 하한(MIN_CAMERA_DISTANCE_M)이 강제하는 ratio 상한.  하한이 없던 시절에는
    # 카메라가 팔레트 안까지 들어가 화면크기가 279배까지 튀었다.
    upper = proj_size_feasible_upper(fx, resolution[0])
    feasible = [max(lo, lower) < min(hi, upper) for lo, hi in PROJ_SIZE_EDGES]
    if not any(feasible):
        raise RuntimeError(
            "no feasible proj_size bin: camera-distance range "
            f"[{MIN_CAMERA_DISTANCE_M}, {MAX_CAMERA_DISTANCE_M}] m forces ratio in "
            f"[{lower:.4f}, {upper:.4f}] but no bin overlaps it "
            f"(fx={fx:.2f}, image_width={resolution[0]})"
        )
    psi = _deficit_pick(PROJ_SIZE_FRAC, qs.proj_size, rng, mask=feasible)
    plo, phi = PROJ_SIZE_EDGES[psi]
    proj_size_ratio = rng.uniform(max(plo, lower), min(phi, upper))

    # -- f_target (occlusion) --
    fti = _deficit_pick(F_TARGET_FRAC, qs.f_target, rng)
    flo, fhi = F_TARGET_EDGES[fti]
    f_target = 0.0 if fti == 0 else rng.uniform(flo, fhi)

    # -- position_mode: CONDITIONAL, only when f_target > 0 --
    if fti == 0:
        position_mode = None
    else:
        pmi = _deficit_pick(POSITION_MODE_FRAC, qs.position_mode, rng)
        position_mode = POSITION_MODES[pmi]

    # -- cargo on/off --
    ci = _deficit_pick(CARGO_FRAC, qs.cargo, rng)
    cargo_on = (ci == 1)
    cargo_seed = rng.randrange(2 ** 31)

    spec = FrameSpec(
        frame_index=frame_index, seed=seed,
        pallet_type=pallet_type, material_variant=material_variant, material_family=family,
        scene_preset=scene_preset, exposure_ev=exposure_ev,
        elev_bin=e_idx, elevation_deg=elevation_deg,
        azimuth_bin=ai, azimuth_deg=azimuth_deg, v_target=v_target,
        proj_size_bin=psi, proj_size_ratio=proj_size_ratio,
        proj_size_feasible_lower=lower,
        aspect=aspect, resolution=resolution, fx_mode=fx_mode, fx=fx,
        f_target_bin=fti, f_target=f_target, position_mode=position_mode,
        cargo_on=cargo_on, cargo_seed=cargo_seed,
    )

    # -- NO quota advance here (pure read). Return the picks so the caller can commit. --
    pm_idx = None if fti == 0 else POSITION_MODES.index(position_mode)
    picks = Picks(pi=pi, spi=spi, e_idx=e_idx, v_idx=v_idx, ai=ai, psi=psi,
                  aspi=aspi, fxi=fxi, fti=fti, pm_idx=pm_idx, ci=ci)
    return spec, picks


# ===========================================================================
# LAYER-2: solve_placement  (PURE analytic geometry, no bpy).  -- completed (B2).
# ===========================================================================
# --- geometry constants -----------------------------------------------------
NEAR_PLANE = 0.005          # cam.data.clip_start (gen_trunc_addon.get_scene_handles).
RESAMPLE_MAX = 30           # occluder asset resample cap N (same f_target kept). Swept
# 12->60: d_occ_fail (finite-sampling misses, size-weighting favours large=too-deep
# occluders) falls with N; 30 balances yield (~82% accept, ~66% in position band) vs
# per-frame tries (mean ~8.6). Genuine geometric d_occ_fail (far pallet, tiny A_target)
# persists past any N.
TRUNC_L_FACTOR = 0.62       # lateral aim-shift max = 0.62*d  (gen_trunc_addon L_MAX).
TRUNC_V_FACTOR = 0.50       # vertical aim-shift max = 0.50*d (gen_trunc_addon V_MAX).
V_SCAN_STEPS = 16           # alpha scan resolution (gen_trunc_addon generate_frame N=16).
OCC_SCALE_JITTER = 0.20     # occluder scale jitter +-20% (no forced up-scaling).
C1_SURF_MARGIN = 0.20       # camera must clear every mesh surface by >0.2 m (gate C1).
PALLET_HARD_FRAC = 0.90     # occluder depth hard ceiling = 0.90*d_pallet (in front).
# occluder fill-ratio floor for the high-occlusion f_target bins (v2 규약 Phase C / B2-2):
# when spec.f_target_bin >= F_TARGET_HIGH_BIN (i.e. f_target >= 0.20) restrict the occluder
# candidate pool to fill_ratio >= OCC_HIGH_FILL_MIN. A low-fill (sparse silhouette) asset
# inverted for a large A_target lands implausibly deep (near the hard ceiling) and inflates
# d_occ_fail; requiring a denser silhouette keeps the depth solve physical.
F_TARGET_HIGH_BIN = 2
OCC_HIGH_FILL_MIN = 0.25
# occluder LATERAL-OFFSET placement (v2 규약 iter-B, 2026-07-25). The occluder need only
# OVERLAP the pallet silhouette by A_target — it does NOT have to sit wholly inside it. A
# large asset can occlude just one side/strip of the pallet from an in-band depth (physically
# realistic AND the fix that lets large occluders be USED: the old whole-silhouette solve
# forced d_occ = fx*sqrt(area/A_target), so big assets landed past the 0.9 hard ceiling ->
# 96% d_occ_fail, large never used). `side` chooses which strip is covered; center = the old
# contained solve (small assets). Toggle drives the dry-run before/after A-B.
LATERAL_OFFSET_ENABLED = True
SIDE_LABELS = ["left", "right", "bottom", "center"]
SIDE_WEIGHTS = [0.30, 0.30, 0.25, 0.15]   # edges (partial overlap) favoured; center=contained
# position_mode depth band (x d_pallet). near-camera prescribed (0.3-0.7). near-pallet lower
# relaxed 0.70 -> 0.55 (v2 규약 iter-B, 0.90 upper kept): 0.70-0.90 was too tight against the
# 0.90 hard ceiling (iter-A: 45% of near-pallet occluders fell short -> downgraded); 0.55-0.90
# gives the lateral-offset depth sampler room to seat the occluder in-band.
POSITION_BANDS = {"near-pallet": (0.55, 0.90), "near-camera": (0.30, 0.70)}
# nominal cargo box on the pallet top (f_cargo estimate only; real cargo = realize()/
# BOX_RANDOMIZATION). Footprint half-extents = place_cargo_on_pallet inner (0.40,0.50).
CARGO_HALF_XY = (0.40, 0.50)
CARGO_NOMINAL_H = 0.35
# cargo silhouette fill_ratio (v2 규약 Phase C / B2-3): a cargo box is a convex cuboid, so
# its silhouette fills its projected 2-D bbox analytically = 1.0 (0.85-1.0 once yaw-rotated;
# we use the axis-aligned upper bound 1.0). This RELEASES the earlier "측정불가" (unknown
# fill) flag for cargo — f_cargo below multiplies the cargo/pallet bbox overlap by this.
CARGO_FILL_RATIO = 1.0


def _load_pallet_dims():
    """Pallet cuboid dims (m) from config canonical_bbox (Y-up: x=width, y=up, z=depth);
    every pallet type is normalised to these (pallet_geometry.get_normalized_scale ->
    TARGET_CANONICAL_DIMS). KS T-11 1100x1100x150mm. Falls back to (1.1,1.1,0.15)."""
    try:
        g = _load_config(DEFAULT_CONFIG)["geometry"]
        mn, mx = g["canonical_bbox_min"], g["canonical_bbox_max"]
        w = float(mx[0] - mn[0]); h = float(mx[1] - mn[1]); d = float(mx[2] - mn[2])
        if w > 0 and h > 0 and d > 0:
            return w, d, h
    except Exception:
        pass
    return 1.1, 1.1, 0.15


PALLET_W, PALLET_D, PALLET_H = _load_pallet_dims()


# --- pure geometry helpers (numpy only) -------------------------------------
def _project(pts_world, cam_pos, look_target, fx, fy, cx, cy):
    """Pinhole-project world points. build_view_matrix (blender_math, bpy-free) gives the
    OpenCV world->camera (R,t) with z forward, y down. Returns (uv[N,2], z[N])."""
    R, t = build_view_matrix(cam_pos, look_target)
    P = np.asarray(pts_world, dtype=np.float64)
    cam = (R @ P.T).T + t
    z = cam[:, 2]
    uv = np.full((len(P), 2), np.nan)
    ok = z > 1e-9
    uv[ok, 0] = fx * cam[ok, 0] / z[ok] + cx
    uv[ok, 1] = fy * cam[ok, 1] / z[ok] + cy
    return uv, z


def _unproject(u, v, z, cam_pos, look_target, fx, fy, cx, cy):
    """Inverse of _project for ONE pixel at camera-depth z -> world point. build_view_matrix
    gives world->cam (R,t): cam_pt = R@world + t, so world = R^T @ (cam_pt - t). Used by the
    lateral-offset occluder solve to place an occluder at a chosen image pixel + depth."""
    R, t = build_view_matrix(cam_pos, look_target)
    cam_pt = np.array([(u - cx) / fx * z, (v - cy) / fy * z, z], dtype=np.float64)
    return R.T @ (cam_pt - np.asarray(t, dtype=np.float64))


def _analytic_v_probe(corners_world, cam_pos, look_target, fx, fy, cx, cy, W, H):
    """In-frame corner count V (0..8). Analytic re-implementation of gen_trunc_addon
    count_in_frame_only (in_front z>0 AND 0<=u<=W AND 0<=v<=H), replacing its bpy
    world_to_camera_view with pinhole projection so it runs outside Blender."""
    uv, z = _project(corners_world, cam_pos, look_target, fx, fy, cx, cy)
    n = 0
    for i in range(len(z)):
        if z[i] > 1e-9 and 0.0 <= uv[i, 0] <= W and 0.0 <= uv[i, 1] <= H:
            n += 1
    return n


def _hull_area(pts):
    """Convex-hull (silhouette) area of 2D points (monotone chain + shoelace)."""
    P = sorted(set((round(float(x), 4), round(float(y), 4)) for x, y in pts))
    if len(P) < 3:
        return 0.0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in P:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(P):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    a = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _bbox2d(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlap_frac(a, b):
    """Overlap area of bbox a inside bbox b, as fraction of b's area (0..1)."""
    if a is None or b is None:
        return 0.0
    ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    if area_b <= 1e-9:
        return 0.0
    return (ox * oy) / area_b


def _aabb_overlap(amin, amax, bmin, bmax):
    return all(amin[i] <= bmax[i] and bmin[i] <= amax[i] for i in range(3))


def _aabb_contains(bmin, bmax, p):
    return all(bmin[i] <= p[i] <= bmax[i] for i in range(3))


def _point_aabb_dist(p, bmin, bmax):
    d = 0.0
    for i in range(3):
        v = max(bmin[i] - p[i], 0.0, p[i] - bmax[i])
        d += v * v
    return math.sqrt(d)


def _ray_aabb_t(orig, direction, bmin, bmax):
    """First forward hit parameter t (>=0) of ray orig+t*direction with an AABB, or None
    if it misses. Slab method."""
    tmin, tmax = -math.inf, math.inf
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            if orig[i] < bmin[i] or orig[i] > bmax[i]:
                return None
        else:
            t1 = (bmin[i] - orig[i]) / direction[i]
            t2 = (bmax[i] - orig[i]) / direction[i]
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
    if tmax < max(tmin, 0.0):
        return None
    return tmin if tmin > 0.0 else 0.0


def _solve_seed(spec: "FrameSpec"):
    """Deterministic per-spec rng seed (avoids PYTHONHASHSEED-randomised hash())."""
    s = int(spec.seed) & 0xFFFFFFFF
    fi = int(spec.frame_index) & 0xFFFFFFFF
    return (s * 2654435761 + fi * 40503 + 0x9E3779B9) & 0xFFFFFFFF


def _pick_trunc_mode(v_target, rng):
    """gen_trunc_addon.sample_trunc_scenario._pick_mode: odd V needs a single-corner clip
    (vertical/diag), even V a lateral column clip."""
    if v_target in (5, 7):
        return _weighted_choice(["vertical", "diag", "lateral"], [0.45, 0.40, 0.15], rng)
    return _weighted_choice(["lateral", "diag", "vertical"], [0.55, 0.25, 0.20], rng)


def _occluder_pool(assets: "Assets", scene_preset, min_fill_ratio=0.0):
    """scene_preset + domain_plausible pool (distractor_pool_v2.filter_by_scene_preset),
    then drop records lacking bbox_m / fill_ratio_mean (can't invert d_occ). When
    min_fill_ratio > 0 (high-occlusion f_target bins, B2-2) also drop sparse-silhouette
    assets with fill_ratio_mean < min_fill_ratio."""
    recs = _dp.filter_by_scene_preset(assets.distractors, scene_preset)
    out = []
    for r in recs:
        bb = r.get("bbox_m")
        fr = r.get("fill_ratio_mean")
        if not bb or any(v is None for v in bb) or fr is None or fr <= 0:
            continue
        if fr < min_fill_ratio:
            continue
        out.append(r)
    return out


def _weighted_sample_rec(pool, rng):
    """One weighted draw (with replacement across resamples) by size_class weight."""
    w = [max(1e-6, _dp.SIZE_CLASS_WEIGHTS.get(r["size_class"], 1.0)) for r in pool]
    return rng.choices(pool, weights=w, k=1)[0]


@dataclass
class Plan:
    """Resolved analytic placement for one frame. All fields are pure geometry targets
    (camera pose, truncation aim, occluder depth/pose); realize() (B3) instantiates them."""
    spec: FrameSpec
    cam_pos: list                 # world camera position
    cam_look: list                # world aim point (after truncation shift)
    cam_distance_m: float         # euclidean camera->pallet-centre distance (the "Z")
    lens_mm: float                # focal in mm (resolution-free form; fx*sensor/W)
    v_probe: int                  # analytic in-frame corner count achieved
    trunc_mode: str               # none|lateral|vertical|diag
    trunc_alpha: float            # 0..1 aim-shift scale chosen to hit v_target
    trunc_shift_m: float          # applied lateral aim shift (m)
    trunc_vshift_m: float         # applied vertical aim shift (m)
    pallet_dims_m: list           # [W, D, H]
    pallet_silhouette_px2: float  # projected pallet convex-hull area (A_pallet)
    f_target: float
    f_cargo: float                # estimated cargo silhouette coverage of pallet
    f_need: float                 # residual occlusion the occluder must supply
    occluder: Optional[dict]      # None | {name, obj_name, d_occ, center, bbox_m, ...}
    reason: Optional[str] = None  # always None for a Plan (present for symmetry)
    camera_distance_limit_m: float = MAX_CAMERA_DISTANCE_M  # cap in force at solve time

    @property
    def camera_distance_target_m(self):
        """Alias of cam_distance_m under the Phase-1 camera-distance naming (the sampled
        TARGET distance; the REALIZED one is measured after realize())."""
        return float(self.cam_distance_m)

    def to_dict(self):
        d = asdict(self)
        d["spec"] = self.spec.to_dict()
        d["camera_distance_target_m"] = self.camera_distance_target_m
        return d


@dataclass
class Reject:
    """A FrameSpec no analytic placement can satisfy. reason is a code for dry-run
    breakdown: C1 | C2 | d_occ_fail | penetration | resample_exhausted | v_below_min."""
    spec: FrameSpec
    reason: str
    detail: str = ""

    def to_dict(self):
        d = asdict(self)
        d["spec"] = self.spec.to_dict()
        return d


def _reject(spec, reason, detail=""):
    return Reject(spec=spec, reason=reason, detail=detail)


def _occ_trace(trace, spec, rec, outcome, d, side):
    if trace is not None:
        trace.append({"frame": spec.frame_index, "asset": rec["name"],
                      "size_class": rec["size_class"], "outcome": outcome,
                      "d_occ": (float(d) if d is not None else None), "side": side})


def _occluder_legacy(spec, rng, trace, pool, A_target, d_pallet, lo_d, hi_d, hard_hi,
                     cam, az, p_center, p_bmin, p_bmax, hw, fx):
    """LEGACY occluder solve (iter-A whole-silhouette): d_occ = fx*sqrt(bbox_cross*fill/
    A_target) so the WHOLE occluder silhouette == A_target, placed off-centre. Kept so the
    dry-run can A-B it against the lateral solve (this is why large assets fail: for a small
    A_target a big bbox_cross forces d_occ past the 0.9 hard ceiling). Returns
    (occluder|None, reason|None, detail)."""
    fail = {"d_occ_fail": 0, "penetration": 0}
    best_valid = None
    chosen = None
    tries = 0
    while tries < RESAMPLE_MAX:
        tries += 1
        rec = _weighted_sample_rec(pool, rng)
        bx, by, bz = rec["bbox_m"]
        fr = float(rec["fill_ratio_mean"])
        dims = sorted([bx, by, bz], reverse=True)
        bbox_cross = dims[0] * dims[1]
        scale = 1.0 + rng.uniform(-OCC_SCALE_JITTER, OCC_SCALE_JITTER)
        bbox_cross_s = bbox_cross * scale * scale
        if bbox_cross_s <= 0:
            fail["d_occ_fail"] += 1
            _occ_trace(trace, spec, rec, "d_occ_fail", None, "legacy")
            continue
        d_occ = fx * math.sqrt(bbox_cross_s * fr / A_target)
        if not (NEAR_PLANE < d_occ < hard_hi):
            fail["d_occ_fail"] += 1
            _occ_trace(trace, spec, rec, "d_occ_fail", d_occ, "legacy")
            continue
        occ_half = 0.5 * np.array(
            _sp2.manifest_bbox_to_blender_dimensions((bx, by, bz))
        ) * scale
        occ_half_xy = float(max(occ_half[0], occ_half[1]))
        side2 = rng.choice((-1.0, 1.0))
        perp = np.array([-math.sin(az), math.cos(az), 0.0])
        r_base = rng.uniform(0.25, 0.5) * hw
        r_clear = (occ_half_xy + 0.10) * d_pallet / max(d_occ, 1e-6)
        r_off = min(max(r_base, r_clear), 1.2 * hw)
        z_off = rng.uniform(0.0, PALLET_H / 2.0)
        target_pt = p_center + side2 * perp * r_off - np.array([0.0, 0.0, z_off])
        ray = target_pt - cam
        nray = np.linalg.norm(ray)
        if nray < 1e-9:
            fail["d_occ_fail"] += 1
            _occ_trace(trace, spec, rec, "d_occ_fail", d_occ, "legacy")
            continue
        ray = ray / nray
        occ_center = cam + d_occ * ray
        occ_bmin = occ_center - occ_half
        occ_bmax = occ_center + occ_half
        if _aabb_overlap(occ_bmin, occ_bmax, p_bmin, p_bmax):
            fail["penetration"] += 1
            _occ_trace(trace, spec, rec, "penetration", d_occ, "legacy")
            continue
        _occ_trace(trace, spec, rec, "valid", d_occ, "legacy")
        in_band = (lo_d <= d_occ <= hi_d)
        cand = {
            "name": rec["name"], "obj_name": _dp.DIST_OBJ_PREFIX + rec["name"],
            "size_class": rec["size_class"], "bbox_m": [bx, by, bz],
            "bbox_cross_m2": bbox_cross, "fill_ratio": fr, "scale": scale,
            "d_occ_m": d_occ, "center": occ_center.tolist(),
            "bmin": occ_bmin.tolist(), "bmax": occ_bmax.tolist(),
            "position_mode": spec.position_mode, "in_position_band": in_band,
            "side": "legacy", "resample_tries": tries,
        }
        if in_band:
            chosen = cand
            break
        if best_valid is None:
            best_valid = cand
    occluder = chosen if chosen is not None else best_valid
    if occluder is None:
        reason = "penetration" if fail["penetration"] > fail["d_occ_fail"] else "d_occ_fail"
        return None, reason, f"{RESAMPLE_MAX} tries all failed hard gate, fails={fail}"
    return occluder, None, ""


def _occluder_lateral(spec, rng, trace, pool, A_target, pallet_bb, d_pallet, lo_d, hi_d,
                      cam, look, p_bmin, p_bmax, fx, fy, cx, cy):
    """LATERAL-OFFSET occluder solve (iter-B). The occluder only OVERLAPS the pallet
    silhouette by A_target; it may hang off a `side` (left/right/bottom) so a LARGE asset
    seated at an in-band depth occludes just a strip. Depth d_occ is sampled inside the band
    (clearance-clamped) and the lateral offset is solved so overlap == A_target — depth and
    offset are solved TOGETHER. `center` = the contained (whole-silhouette) fallback for
    small assets. Camera clearance is a placement CONSTRAINT here (band lower bound), not a
    post-gate. Returns (occluder|None, reason|None, detail)."""
    px0, py0, px1, py1 = pallet_bb
    Wp = max(px1 - px0, 1e-6)
    Hp = max(py1 - py0, 1e-6)
    pcx, pcy = 0.5 * (px0 + px1), 0.5 * (py0 + py1)
    fail = {"d_occ_fail": 0, "penetration": 0}
    best_valid = None
    chosen = None
    tries = 0
    while tries < RESAMPLE_MAX:
        tries += 1
        rec = _weighted_sample_rec(pool, rng)
        bx, by, bz = rec["bbox_m"]
        fr = float(rec["fill_ratio_mean"])
        dims = sorted([bx, by, bz], reverse=True)   # [largest, mid, smallest]
        scale = 1.0 + rng.uniform(-OCC_SCALE_JITTER, OCC_SCALE_JITTER)
        # silhouette rectangle real dims (two largest, fill applied as sqrt per axis so the
        # rect area == fill*w*h). orientation ignored -> largest maps to image-x.
        sfr = math.sqrt(fr)
        wmax_m = dims[0] * scale * sfr
        hmax_m = dims[1] * scale * sfr
        occ_half = 0.5 * np.array(
            _sp2.manifest_bbox_to_blender_dimensions((bx, by, bz))
        ) * scale
        occ_view_half = float(np.max(occ_half))           # conservative along-view half-extent
        # Fix-2 clearance CONSTRAINT: occluder centre >= C1_SURF_MARGIN + its half-extent from
        # the camera. Clamp the band lower bound (never below near plane).
        d_lo = max(lo_d, NEAR_PLANE, C1_SURF_MARGIN + occ_view_half)
        d_hi = hi_d
        if d_lo >= d_hi:  # can't seat this asset in-band with the clearance margin
            fail["d_occ_fail"] += 1
            _occ_trace(trace, spec, rec, "d_occ_fail", None, "clearance")
            continue
        side = _weighted_choice(SIDE_LABELS, SIDE_WEIGHTS, rng)
        if side == "center":
            # contained: whole silhouette == A_target -> depth fixed; must land in the band.
            d_occ = fx * math.sqrt((dims[0] * scale) * (dims[1] * scale) * fr / A_target)
            if not (d_lo <= d_occ <= d_hi):
                fail["d_occ_fail"] += 1
                _occ_trace(trace, spec, rec, "d_occ_fail", d_occ, side)
                continue
            wo = wmax_m * fx / d_occ
            ox = pcx + rng.choice((-1.0, 1.0)) * 0.5 * wo   # nudge off centroid (-> C2 pass)
            oy = pcy
        else:
            # partial overlap: sample depth in band, solve offset so covered strip == A_target.
            d_occ = rng.uniform(d_lo, d_hi)
            wo = wmax_m * fx / d_occ
            ho = hmax_m * fy / d_occ
            if side in ("left", "right"):
                vov = min(ho, Hp)
                hov = A_target / vov
                if hov > min(wo, Wp) + 1e-6:   # occluder too small to cover the strip
                    fail["d_occ_fail"] += 1
                    _occ_trace(trace, spec, rec, "d_occ_fail", d_occ, side)
                    continue
                oy = pcy
                ox = (px0 + hov - wo / 2.0) if side == "left" else (px1 - hov + wo / 2.0)
            else:  # bottom
                hov = min(wo, Wp)
                vov = A_target / hov
                if vov > min(ho, Hp) + 1e-6:
                    fail["d_occ_fail"] += 1
                    _occ_trace(trace, spec, rec, "d_occ_fail", d_occ, side)
                    continue
                ox = pcx
                oy = py1 - vov + ho / 2.0
        occ_center = _unproject(ox, oy, d_occ, cam, look, fx, fy, cx, cy)
        occ_bmin = occ_center - occ_half
        occ_bmax = occ_center + occ_half
        if _aabb_overlap(occ_bmin, occ_bmax, p_bmin, p_bmax):   # HARD gate: pallet penetration
            fail["penetration"] += 1
            _occ_trace(trace, spec, rec, "penetration", d_occ, side)
            continue
        _occ_trace(trace, spec, rec, "valid", d_occ, side)
        in_band = (lo_d <= d_occ <= hi_d)   # always True (d_occ sampled inside [d_lo,d_hi])
        cand = {
            "name": rec["name"], "obj_name": _dp.DIST_OBJ_PREFIX + rec["name"],
            "size_class": rec["size_class"], "bbox_m": [bx, by, bz],
            "bbox_cross_m2": dims[0] * dims[1], "fill_ratio": fr, "scale": scale,
            "d_occ_m": d_occ, "center": occ_center.tolist(),
            "bmin": occ_bmin.tolist(), "bmax": occ_bmax.tolist(),
            "position_mode": spec.position_mode, "in_position_band": in_band,
            "side": side, "overlap_target_px2": float(A_target), "resample_tries": tries,
        }
        if in_band:
            chosen = cand
            break
        if best_valid is None:
            best_valid = cand
    occluder = chosen if chosen is not None else best_valid
    if occluder is None:
        reason = "penetration" if fail["penetration"] > fail["d_occ_fail"] else "d_occ_fail"
        return None, reason, f"{RESAMPLE_MAX} tries all failed hard gate, fails={fail}"
    return occluder, None, ""


def solve_placement(
    spec: FrameSpec,
    assets: Assets,
    trace=None,
    placement_mode="legacy",
    occluder_nonce=0,
):
    """PURE analytic geometry (NO bpy): turn a FrameSpec target into a concrete Plan or a
    Reject with a reason code. Deterministic (same spec => same Plan). Pipeline order:

      1. camera distance from the target projected size,
      2. truncation aim -> analytic V-probe to hit v_target,
      3. occlusion ordering: cargo first (f_cargo), then occluder depth d_occ inverted
         from the residual f_need (asset-first, size preserved, position_mode band),
      4. pre-render gates C1 (camera in/near a mesh) and C2 (pallet centre occluded).

    trace: optional list. When supplied, each occluder resample TRY appends a dict
      {frame, asset, size_class, outcome, d_occ} (outcome = valid|d_occ_fail|penetration)
      for the dry-run per-asset audit (output c). Off by default -> zero cost & no effect
      on the rng sequence / determinism (append is a pure side-record).
    """
    if placement_mode not in ("legacy", "constrained"):
        raise ValueError(
            f"unknown placement_mode={placement_mode!r}; expected 'legacy' or 'constrained'"
        )
    occluder_nonce = int(occluder_nonce)
    if occluder_nonce < 0:
        raise ValueError("occluder_nonce must be non-negative")
    rng = random.Random(_solve_seed(spec))
    W, H = spec.resolution
    fx = fy = float(spec.fx)
    # principal point at image centre for the analytic probe (exact cx/cy = realize()/B3).
    cx, cy = W / 2.0, H / 2.0

    # pallet cuboid (world, grounded, square 1.1x1.1 footprint, yaw=0; camera orbits it).
    hw, hd = PALLET_W / 2.0, PALLET_D / 2.0
    p_center = np.array([0.0, 0.0, PALLET_H / 2.0])
    corners = np.array(
        [[sx * hw, sy * hd, (PALLET_H if sz else 0.0)]
         for sx in (-1, 1) for sy in (-1, 1) for sz in (0, 1)],
        dtype=np.float64,
    )
    p_bmin = np.array([-hw, -hd, 0.0])
    p_bmax = np.array([hw, hd, PALLET_H])

    # --- (1) camera distance from proj_size_ratio ---------------------------
    # NOTE (semantic->real): the task's f_size (target projected size, image-width ratio)
    # is spec.proj_size_ratio here; the task's f_target axis is the OCCLUSION fraction.
    # d = fx * W_pallet / (proj_size_ratio * IMAGE_WIDTH)   (pinhole, projected width in px)
    #   == focal_mm * W_pallet / (sensor_mm * proj_size_ratio)  (resolution-free lens form,
    #      inverse of gen_trunc_addon D435I_LENS = fx*sensor/W).
    proj = max(float(spec.proj_size_ratio), 1e-3)
    d_pallet = fx * PALLET_W / (proj * W)
    lens_mm = fx * SENSOR_MM / W
    # DEFENSIVE (Phase 1): sample_frame already narrows the ratio bins so the cap holds, so a
    # correct sampler yields 0 of these. It fires only if a hand-built / externally-loaded
    # FrameSpec asks for a distance no camera in this dataset should ever take.
    if d_pallet > MAX_CAMERA_DISTANCE_M + 1e-6:
        return _reject(spec, "camera_distance_out_of_range",
                       f"d_pallet={d_pallet:.3f}m > cap={MAX_CAMERA_DISTANCE_M}m "
                       f"(fx={fx:.2f} W={W} ratio={proj:.5f})")
    if d_pallet < MIN_CAMERA_DISTANCE_M - 1e-6:
        return _reject(spec, "camera_distance_out_of_range",
                       f"d_pallet={d_pallet:.3f}m < floor={MIN_CAMERA_DISTANCE_M}m "
                       f"(fx={fx:.2f} W={W} ratio={proj:.5f})")

    e = math.radians(spec.elevation_deg)
    az = math.radians(spec.azimuth_deg)
    horiz = d_pallet * math.cos(e)
    cam = p_center + np.array([horiz * math.cos(az), horiz * math.sin(az),
                               d_pallet * math.sin(e)])

    # --- (2) truncation aim -> V-probe to hit v_target ----------------------
    look = p_center.copy()
    trunc_mode = "none"
    alpha = 0.0
    shift = vshift = 0.0
    vt = int(spec.v_target)
    if vt <= 7:
        side = rng.choice((-1.0, 1.0))
        shift_dir = az + side * (math.pi / 2.0)  # lateral: perpendicular to view azimuth
        L = TRUNC_L_FACTOR * d_pallet
        Vv = TRUNC_V_FACTOR * d_pallet
        trunc_mode = _pick_trunc_mode(vt, rng)
        sx = sy = sz = 0.0
        if trunc_mode == "lateral":
            sx, sy = L * math.cos(shift_dir), L * math.sin(shift_dir)
        elif trunc_mode == "vertical":
            sz = rng.choice((-1.0, 1.0)) * Vv
        else:  # diag
            sx, sy = 0.78 * L * math.cos(shift_dir), 0.78 * L * math.sin(shift_dir)
            sz = rng.choice((-1.0, 1.0)) * 0.78 * Vv
        svec = np.array([sx, sy, sz])
        best = None  # ((|v-vt|, |a-0.55|), alpha, look, v)
        for i in range(V_SCAN_STEPS + 1):
            a = i / V_SCAN_STEPS
            cand = look + a * svec
            v = _analytic_v_probe(corners, cam, cand, fx, fy, cx, cy, W, H)
            key = (abs(v - vt), abs(a - 0.55))
            if best is None or key < best[0]:
                best = (key, a, cand, v)
        alpha, look, v_probe = best[1], best[2], best[3]
        shift = alpha * math.hypot(sx, sy)
        vshift = alpha * sz
    else:
        v_probe = _analytic_v_probe(corners, cam, look, fx, fy, cx, cy, W, H)

    if v_probe < 4:
        return _reject(spec, "v_below_min", f"v_probe={v_probe}")

    # pallet silhouette (px^2) under the actual (truncated) render view.
    uv, z = _project(corners, cam, look, fx, fy, cx, cy)
    front = [tuple(uv[i]) for i in range(8) if z[i] > 1e-9]
    A_pallet = _hull_area(front)
    pallet_bb = _bbox2d(front)

    # --- (3a) cargo first -> f_cargo estimate -------------------------------
    # cargo_box (world AABB) is built whenever cargo is on, independent of projection, so
    # gate C1 (step 4) can test the camera against the cargo mesh too (B2-1 mesh tracking).
    cargo_box = None
    f_cargo = 0.0
    if spec.cargo_on:
        chw, chd = CARGO_HALF_XY
        cargo_box = (np.array([-chw, -chd, PALLET_H]),
                     np.array([chw, chd, PALLET_H + CARGO_NOMINAL_H]))
    if spec.cargo_on and pallet_bb is not None:
        chw, chd = CARGO_HALF_XY
        cargo = np.array(
            [[sx * chw, sy * chd, PALLET_H + (CARGO_NOMINAL_H if sz else 0.0)]
             for sx in (-1, 1) for sy in (-1, 1) for sz in (0, 1)],
            dtype=np.float64,
        )
        cuv, cz = _project(cargo, cam, look, fx, fy, cx, cy)
        cfront = [tuple(cuv[i]) for i in range(8) if cz[i] > 1e-9]
        # cargo silhouette fill_ratio is analytic (=CARGO_FILL_RATIO, convex cuboid; B2-3):
        # coverage of the pallet silhouette = fill_ratio * (cargo_bbox ∩ pallet_bbox)/pallet.
        f_cargo = min(1.0, CARGO_FILL_RATIO * _bbox_overlap_frac(_bbox2d(cfront), pallet_bb))

    # --- (3b) residual occlusion need ---------------------------------------
    f_need = max(0.0, float(spec.f_target) - f_cargo)

    # --- (3c) occluder: overlap the pallet silhouette by A_target ----------
    # LATERAL mode (default): occluder need only OVERLAP by A_target (partial, off a side);
    # depth is sampled in-band and the offset solved together -> large assets USABLE. Camera
    # clearance is a placement CONSTRAINT (band lower bound). LEGACY mode (A-B toggle): the
    # old whole-silhouette solve. Empty pool -> resample_exhausted; genuine per-try exhaustion
    # -> dominant cause (d_occ_fail | penetration).
    occluder = None
    if f_need > 1e-6:
        occ_rng = rng
        if occluder_nonce:
            occ_rng = random.Random(
                (
                    _solve_seed(spec)
                    + occluder_nonce * 0x85EBCA6B
                    + 0xC2B2AE35
                )
                & 0xFFFFFFFF
            )
        A_target = f_need * A_pallet
        band = POSITION_BANDS.get(spec.position_mode, (0.30, PALLET_HARD_FRAC))
        lo_d, hi_d = band[0] * d_pallet, band[1] * d_pallet
        hard_hi = PALLET_HARD_FRAC * d_pallet
        # B2-2: high-occlusion bins (f_target >= 0.20) require a denser occluder silhouette.
        min_fr = OCC_HIGH_FILL_MIN if spec.f_target_bin >= F_TARGET_HIGH_BIN else 0.0
        pool = _occluder_pool(assets, spec.scene_preset, min_fill_ratio=min_fr)
        if not pool or A_target <= 1e-9:
            return _reject(spec, "resample_exhausted",
                           "empty pool" if not pool else "A_target~0")
        if LATERAL_OFFSET_ENABLED:
            occluder, reason, detail = _occluder_lateral(
                spec, occ_rng, trace, pool, A_target, pallet_bb, d_pallet, lo_d, hi_d,
                cam, look, p_bmin, p_bmax, fx, fy, cx, cy)
        else:
            occluder, reason, detail = _occluder_legacy(
                spec, occ_rng, trace, pool, A_target, d_pallet, lo_d, hi_d, hard_hi,
                cam, az, p_center, p_bmin, p_bmax, hw, fx)
        if occluder is None:
            return _reject(spec, reason, detail)

    # --- (4) pre-render gates C1 / C2 (projection + raycast only) -----------
    occ_boxes = []
    if occluder is not None:
        occ_boxes.append((np.array(occluder["bmin"]), np.array(occluder["bmax"])))
    # C1: camera inside, or within C1_SURF_MARGIN of, any mesh surface. B2-1: attribute the
    # reject to the mesh TYPE the camera is nearest/inside (background-glTF | distractor |
    # cargo | pallet) and record it as "mesh=<type>" in Reject.detail for the dry-run (b)
    # breakdown. Meshes modeled in this PURE layer: pallet, cargo (if on), distractor
    # (=occluder). Background glTF is NOT modeled here (no AABB) so it can never be a C1
    # cause in the pure layer -> its bucket stays 0 by construction; realize()/B3 owns
    # background collision. The nearest violating mesh wins (smallest surface clearance).
    c1_meshes = [("pallet", p_bmin, p_bmax)]
    if cargo_box is not None:
        c1_meshes.append(("cargo", cargo_box[0], cargo_box[1]))
    for bmn, bmx in occ_boxes:
        c1_meshes.append(("distractor", bmn, bmx))
    c1_hit = None  # (clearance, mesh_type)
    for mesh_type, bmn, bmx in c1_meshes:
        inside = _aabb_contains(bmn, bmx, cam)
        clr = 0.0 if inside else _point_aabb_dist(cam, bmn, bmx)
        if inside or clr < C1_SURF_MARGIN:
            if c1_hit is None or clr < c1_hit[0]:
                c1_hit = (clr, mesh_type)
    if c1_hit is not None:
        return _reject(spec, "C1", f"mesh={c1_hit[1]}")
    # C2: legacy keeps the original analytic centre-ray hard reject. In constrained mode
    # this check is deferred ONLY for the intentional explicit occluder: Blender validates
    # the static-scene line of sight first, then the low-resolution mask feedback solver
    # judges the deliberate occlusion using the unchanged G1/G3 gates and ROI metrics.
    if placement_mode == "legacy":
        raydir = p_center - cam
        nrd = np.linalg.norm(raydir)
        raydir = raydir / nrd if nrd > 1e-9 else raydir
        t_pallet = _ray_aabb_t(cam, raydir, p_bmin, p_bmax)
        for bmn, bmx in occ_boxes:
            t_occ = _ray_aabb_t(cam, raydir, bmn, bmx)
            if t_occ is not None and (t_pallet is None or t_occ < t_pallet):
                return _reject(spec, "C2", "pallet centre occluded")

    return Plan(
        spec=spec,
        cam_pos=cam.tolist(),
        cam_look=look.tolist(),
        cam_distance_m=float(d_pallet),
        lens_mm=float(lens_mm),
        v_probe=int(v_probe),
        trunc_mode=trunc_mode,
        trunc_alpha=float(alpha),
        trunc_shift_m=float(shift),
        trunc_vshift_m=float(vshift),
        pallet_dims_m=[PALLET_W, PALLET_D, PALLET_H],
        pallet_silhouette_px2=float(A_pallet),
        f_target=float(spec.f_target),
        f_cargo=float(f_cargo),
        f_need=float(f_need),
        occluder=occluder,
        camera_distance_limit_m=float(MAX_CAMERA_DISTANCE_M),
    )


def attach_diagnostic_explicit_occluder(plan: Plan, assets: Assets):
    """Attach a full-target occluder proposal for controlled diagnostics.

    The production solver models ``f_target`` as total occlusion and subtracts
    its nominal cargo estimate.  The controlled diagnostic intentionally
    measures ``f_target`` against the explicit source alone, so a cargo-heavy
    analytic plan may otherwise contain no occluder proposal.  Re-solving a
    temporary cargo-off copy preserves the sampled FrameSpec and camera while
    supplying only the missing initial occluder pose.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if float(plan.spec.f_target) <= 1e-6 or plan.occluder is not None:
        return plan

    proposal_spec = replace(plan.spec, cargo_on=False)
    proposal = solve_placement(
        proposal_spec,
        assets,
        placement_mode="constrained",
    )
    if isinstance(proposal, Reject):
        return Reject(
            spec=plan.spec,
            reason="diagnostic_explicit_proposal_failed",
            detail=f"{proposal.reason}: {proposal.detail}",
        )

    occluder = dict(proposal.occluder)
    occluder["diagnostic_fallback"] = "cargo_off_resolve"
    occluder["diagnostic_f_explicit_target"] = float(plan.spec.f_target)
    return replace(
        plan,
        f_need=float(plan.spec.f_target),
        occluder=occluder,
    )


def diagnostic_explicit_side(
    requested_side,
    elevation_deg,
    target_fraction=0.0,
):
    """Choose a floor-supported occlusion side feasible for the view elevation."""
    if requested_side not in SIDE_LABELS:
        raise ValueError(f"unknown occluder side: {requested_side!r}")
    elevation = float(elevation_deg)
    if not math.isfinite(elevation):
        raise ValueError("elevation_deg must be finite")
    target = float(target_fraction)
    if not math.isfinite(target) or target < 0.0 or target > 1.0:
        raise ValueError("target_fraction must be finite and in [0, 1]")
    if elevation >= 60.0:
        return "bottom"
    return requested_side


def diagnostic_explicit_seed_side(
    requested_side,
    elevation_deg,
    target_fraction=0.0,
):
    """Choose placement geometry without changing the audited target side."""
    target_side = diagnostic_explicit_side(
        requested_side,
        elevation_deg,
        target_fraction,
    )
    elevation = float(elevation_deg)
    target = float(target_fraction)
    if (
        target_side in {"left", "right"}
        and elevation >= 30.0
        and target >= 0.30
    ):
        return "bottom"
    return target_side


def diagnostic_proposal_utility(candidate):
    """Score diagnostic alternatives by upright height and filled silhouette."""
    scale = float(candidate.get("scale", 1.0))
    height = float(candidate["bbox_m"][1]) * scale
    filled_area = (
        float(candidate["bbox_cross_m2"])
        * float(candidate["fill_ratio"])
        * scale
        * scale
    )
    return height * filled_area


def select_diagnostic_explicit_proposals(proposals, max_proposals):
    """Keep the primary draw, then select deterministic shape-diverse fallbacks."""
    max_proposals = int(max_proposals)
    if max_proposals < 1:
        raise ValueError("max_proposals must be positive")

    unique = []
    seen_names = set()
    for candidate in proposals:
        name = candidate.get("obj_name")
        if name in seen_names:
            continue
        seen_names.add(name)
        unique.append(candidate)
    if not unique:
        return []

    selected = [unique[0]]
    selected_names = {unique[0].get("obj_name")}

    def shape(candidate):
        scale = float(candidate.get("scale", 1.0))
        width = float(candidate["bbox_m"][0]) * scale
        height = float(candidate["bbox_m"][1]) * scale
        fill = float(candidate["fill_ratio"])
        return width, height, fill

    def rank(candidates, score):
        return sorted(
            candidates,
            key=lambda candidate: (
                tuple(-float(value) for value in score(candidate)),
                int(candidate.get("diagnostic_proposal_nonce", 0)),
                candidate.get("obj_name", ""),
            ),
        )

    def add_best(score, eligible=lambda candidate: True):
        if len(selected) >= max_proposals:
            return
        available = [
            candidate
            for candidate in unique[1:]
            if candidate.get("obj_name") not in selected_names
            and eligible(candidate)
        ]
        if not available:
            return
        winner = rank(available, score)[0]
        selected.append(winner)
        selected_names.add(winner.get("obj_name"))

    def compact_solid(candidate):
        width, height, fill = shape(candidate)
        return (
            width <= 0.75
            and height >= 0.75
            and height >= 1.5 * width
            and fill >= 0.75
        )

    def thin_upright(candidate):
        scale = float(candidate.get("scale", 1.0))
        width, height, fill = shape(candidate)
        footprint_depth = float(candidate["bbox_m"][2]) * scale
        return (
            width >= 0.75
            and height >= 0.75
            and footprint_depth <= 0.15
            and height >= 6.0 * footprint_depth
            and fill >= 0.35
        )

    def dense_upright_panel(candidate):
        scale = float(candidate.get("scale", 1.0))
        width, height, fill = shape(candidate)
        footprint_depth = float(candidate["bbox_m"][2]) * scale
        return (
            width >= 0.75
            and height >= 1.20
            and footprint_depth <= 0.45
            and fill >= 0.75
        )

    def tall_shallow(candidate):
        scale = float(candidate.get("scale", 1.0))
        width, height, fill = shape(candidate)
        footprint_depth = float(candidate["bbox_m"][2]) * scale
        return (
            width >= 0.75
            and height >= 1.40
            and footprint_depth <= 0.25
            and height >= 6.0 * footprint_depth
            and fill >= 0.70
        )

    add_best(
        lambda candidate: (
            shape(candidate)[1]
            * shape(candidate)[2]
            / max(float(candidate["bbox_m"][2]) * float(candidate.get("scale", 1.0)), 1e-9),
            diagnostic_proposal_utility(candidate),
        ),
        thin_upright,
    )
    add_best(
        lambda candidate: (
            shape(candidate)[0] * shape(candidate)[1] * shape(candidate)[2],
            shape(candidate)[1],
            diagnostic_proposal_utility(candidate),
        ),
        dense_upright_panel,
    )
    add_best(
        lambda candidate: (
            shape(candidate)[1]
            * shape(candidate)[2]
            / max(
                float(candidate["bbox_m"][2])
                * float(candidate.get("scale", 1.0)),
                1e-9,
            ),
            diagnostic_proposal_utility(candidate),
        ),
        tall_shallow,
    )
    add_best(
        lambda candidate: (
            diagnostic_proposal_utility(candidate),
            shape(candidate)[1],
        ),
        compact_solid,
    )
    add_best(
        lambda candidate: (
            shape(candidate)[1]
            * shape(candidate)[2]
            / max(shape(candidate)[0], 1e-9),
            diagnostic_proposal_utility(candidate),
        ),
        compact_solid,
    )
    add_best(
        lambda candidate: (
            shape(candidate)[1],
            diagnostic_proposal_utility(candidate),
        )
    )
    add_best(
        lambda candidate: (
            diagnostic_proposal_utility(candidate),
            shape(candidate)[1],
        )
    )

    remaining = [
        candidate
        for candidate in unique[1:]
        if candidate.get("obj_name") not in selected_names
    ]
    for candidate in rank(
        remaining,
        lambda candidate: (
            diagnostic_proposal_utility(candidate),
            shape(candidate)[1],
        ),
    ):
        if len(selected) >= max_proposals:
            break
        selected.append(candidate)
        selected_names.add(candidate.get("obj_name"))
    return selected


def occluder_screen_silhouette_px2(spec, candidate):
    """계획된 occluder 실루엣의 화면 면적(px^2).  `_occluder_lateral` 이 depth 를 풀 때
    쓴 것과 같은 식이다 (두 축 중 큰 둘 * scale * sqrt(fill), 원근 나눗셈).  Plan 의
    occluder dict 를 건드리지 않으려고 여기서 되짚는다 (5k dry-run digest 보존)."""
    bx, by, bz = candidate["bbox_m"]
    dims = sorted([float(bx), float(by), float(bz)], reverse=True)
    fill = float(candidate["fill_ratio"])
    scale = float(candidate.get("scale", 1.0))
    d_occ = float(candidate["d_occ_m"])
    if d_occ <= 1e-9:
        return None
    sfr = math.sqrt(fill)
    fx = float(spec.fx)
    fy = float(getattr(spec, "fy", spec.fx))
    return (dims[0] * scale * sfr * fx / d_occ) * (dims[1] * scale * sfr * fy / d_occ)


def prepare_diagnostic_explicit_occluders(
    plan: Plan,
    assets: Assets,
    max_proposals=6,
    max_nonce=640,
    prefilter=True,
):
    """Prepare deterministic full-target proposals for controlled diagnostics.

    Production plans model ``f_target`` as total occlusion after cargo.  The
    controlled diagnostic instead audits the explicit source itself, so its
    proposal set is solved with cargo disabled while the original FrameSpec,
    camera, cargo realization, quotas, and gates remain unchanged.  At high
    elevations, a floor-supported lateral occluder cannot overlap the pallet
    without sharing its footprint, so the diagnostic proposal uses the
    camera-near image-bottom side while retaining the original side as
    metadata.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if float(plan.spec.f_target) <= 1e-6:
        return plan

    max_proposals = int(max_proposals)
    max_nonce = int(max_nonce)
    if max_proposals < 1:
        raise ValueError("max_proposals must be positive")
    if max_nonce < 0:
        raise ValueError("max_nonce must be non-negative")

    proposal_spec = replace(plan.spec, cargo_on=False)
    requested_side = (
        (plan.occluder or {}).get("side")
        if plan.occluder is not None
        else None
    )
    effective_side = (
        diagnostic_explicit_side(
            requested_side,
            plan.spec.elevation_deg,
            plan.spec.f_target,
        )
        if requested_side is not None
        else None
    )
    placement_seed_side = (
        diagnostic_explicit_seed_side(
            requested_side,
            plan.spec.elevation_deg,
            plan.spec.f_target,
        )
        if requested_side is not None
        else None
    )
    proposals = []
    seen = set()
    failures = []
    prefilter_rejects = {}
    candidates_before_prefilter = 0

    for nonce in range(max_nonce + 1):
        proposal = solve_placement(
            proposal_spec,
            assets,
            placement_mode="constrained",
            occluder_nonce=nonce,
        )
        if isinstance(proposal, Reject):
            failures.append(f"{nonce}:{proposal.reason}")
            continue
        candidate = proposal.occluder
        if candidate is None:
            failures.append(f"{nonce}:missing_occluder")
            continue
        if requested_side is None:
            requested_side = candidate.get("side")
            effective_side = diagnostic_explicit_side(
                requested_side,
                plan.spec.elevation_deg,
                plan.spec.f_target,
            )
            placement_seed_side = diagnostic_explicit_seed_side(
                requested_side,
                plan.spec.elevation_deg,
                plan.spec.f_target,
            )
        if candidate.get("side") != placement_seed_side:
            continue

        candidate = dict(candidate)
        candidate["diagnostic_placement_seed_side"] = candidate["side"]
        candidate["diagnostic_placement_seed_decoupled"] = bool(
            placement_seed_side != effective_side
        )
        candidate["side"] = effective_side
        candidate["diagnostic_proposal_nonce"] = int(nonce)
        candidate["diagnostic_f_explicit_target"] = float(
            plan.spec.f_target
        )
        candidate["diagnostic_original_side_target"] = requested_side
        candidate["diagnostic_effective_side_target"] = effective_side
        candidate["diagnostic_side_feasibility_override"] = bool(
            effective_side != requested_side
        )
        key = (
            candidate.get("obj_name"),
            tuple(round(float(value), 8) for value in candidate["center"]),
            round(float(candidate.get("scale", 1.0)), 8),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates_before_prefilter += 1
        # FEASIBILITY PREFILTER (bpy-free): 접지시키면 목표를 맞출 수 없는 후보를
        # Blender 상세 realization 에 넘기기 전에 버린다.  분포를 바꾸지 않는다 —
        # FrameSpec 도 f_target 도 side 도 그대로고, 걸러지는 것은 "이 프레임에 쓸
        # occluder 후보"뿐이다.
        if prefilter:
            screen_px2 = occluder_screen_silhouette_px2(proposal_spec, candidate)
            reason = _sp2.controlled_prefilter_reason(
                candidate,
                plan.pallet_silhouette_px2,
                screen_area_px2=screen_px2,
            )
            if reason is not None:
                prefilter_rejects[reason] = prefilter_rejects.get(reason, 0) + 1
                continue
        proposals.append(candidate)

    if not proposals:
        detail = ",".join(failures[:8]) or "no same-side proposal"
        if prefilter and prefilter_rejects:
            detail = "prefilter:" + ",".join(
                f"{k}={v}" for k, v in sorted(prefilter_rejects.items()))
            return Reject(
                spec=plan.spec,
                reason="diagnostic_explicit_prefilter_exhausted",
                detail=detail,
            )
        return Reject(
            spec=plan.spec,
            reason="diagnostic_explicit_proposal_failed",
            detail=detail,
        )

    selected = select_diagnostic_explicit_proposals(
        proposals,
        max_proposals=max_proposals,
    )
    primary = dict(selected[0])
    selected_alternatives = selected[1:]

    primary["diagnostic_fallback"] = "cargo_off_full_target"
    primary["diagnostic_resample_strategy"] = (
        "ground_feasible_side_distinct_asset_shape_diverse"
    )
    primary["diagnostic_original_f_need"] = float(plan.f_need)
    primary["diagnostic_original_occluder_name"] = (
        (plan.occluder or {}).get("name")
    )
    primary["diagnostic_resample_proposals"] = [
        dict(candidate) for candidate in selected_alternatives
    ]
    primary["candidates_before_prefilter"] = int(candidates_before_prefilter)
    primary["candidates_after_prefilter"] = int(len(proposals))
    primary["prefilter_reject_count"] = int(
        sum(prefilter_rejects.values())
    )
    primary["prefilter_reject_counts_by_reason"] = dict(prefilter_rejects)
    primary["prefilter_enabled"] = bool(prefilter)
    return replace(
        plan,
        f_need=float(plan.spec.f_target),
        occluder=primary,
    )


# ---------------------------------------------------------------------------
# LAYER-3 (Blender). Implemented in v2_realize.py and imported LAZILY so this module
# stays bpy-FREE for the pure dry-run (audit_v2_dryrun.py). The heavy Blender logic
# (scene build, holdout masks, raycast occlusion, gates, label) lives in v2_realize
# to keep sample_frame/solve_placement above it pure. See v2_realize.py.
# ---------------------------------------------------------------------------
def realize(plan: Plan, **kwargs):
    """Blender: instantiate pallet/occluder/cargo/camera from a Plan -> RealizedScene."""
    import v2_realize
    return v2_realize.realize(plan, **kwargs)


def measure(scene):
    """Blender: measure the realized frame (masks -> f_cargo/f_occ/f_total, V_actual,
    occlusion_fraction[9], luma, front_cos/facing_margin)."""
    import v2_realize
    return v2_realize.measure(scene)


def render(scene, rgb_path, samples=16):
    """Blender: render the RGB frame (Cycles)."""
    import v2_realize
    return v2_realize.render(scene, rgb_path, samples=samples)


def label(spec: FrameSpec, plan: Plan, meas, rs=None):
    """Build the v2 label JSON from spec + plan + measured values (target AND actual)."""
    import v2_realize
    return v2_realize.label(spec, plan, meas, rs)


def safety_gates(meas, plan: Plan):
    """Hard safety gates G1..G5 (only these reject; target != actual does not)."""
    import v2_realize
    return v2_realize.safety_gates(meas, plan)


# ===========================================================================
# DRY-RUN entry (no Blender): determinism proof + 1000-sample distribution audit.
# ===========================================================================
def generate_specs(n, seed, assets=None):
    """Produce n FrameSpecs deterministically from a single seed (fresh quota).

    SAMPLE-ONLY path (Layer-1 --v2_plan emit): there is no solve, so the quota is committed
    on EVERY sample (advance_quota each iteration) — external behaviour unchanged from B1."""
    if assets is None:
        assets = load_assets()
    rng = random.Random(seed)
    qs = QuotaState.new(assets)
    specs = []
    for i in range(n):
        spec, picks = sample_frame(rng, qs, assets, frame_index=i, seed=seed)
        advance_quota(qs, picks)
        specs.append(spec)
    return specs, qs


def generate_accepted(n_target, seed, assets=None, max_attempts=None, trace=None,
                      placement_mode="legacy"):
    """ACCEPT-TIME quota path (v2 규약 iter-B). Sample -> solve; advance the quota ONLY when
    solve_placement accepts (Plan). Rejected cells stay under-filled and are re-targeted on
    the next draw, so the ACCEPTED set — not the attempted set — matches the prescription.
    Deterministic under seed. Returns (accepted_plans, rejects, qs, attempts).

    NB frame_index = attempt counter (unique per solve) so per-spec solve seeds stay distinct
    and the run is reproducible."""
    if assets is None:
        assets = load_assets()
    rng = random.Random(seed)
    qs = QuotaState.new(assets)
    if max_attempts is None:
        max_attempts = n_target * 20
    accepted, rejects = [], []
    attempts = 0
    while len(accepted) < n_target and attempts < max_attempts:
        spec, picks = sample_frame(rng, qs, assets, frame_index=attempts, seed=seed)
        plan = solve_placement(
            spec,
            assets,
            trace=trace,
            placement_mode=placement_mode,
        )
        attempts += 1
        if isinstance(plan, Plan):
            advance_quota(qs, picks)   # commit ONLY on accept
            accepted.append(plan)
        else:
            rejects.append(plan)
    return accepted, rejects, qs, attempts


def solve_specs(specs, assets):
    """Run solve_placement over a spec list (pure geometry, no Blender)."""
    return [solve_placement(s, assets) for s in specs]


def _tally(values, keys):
    c = {k: 0 for k in keys}
    for v in values:
        c[v] = c.get(v, 0) + 1
    return c


def audit_luma_actual(luma_values):
    """Coverage audit (NOT a quota) of measured mean-luma over LUMA_ACTUAL_EDGES (B2/③).

    luma_values: per-frame mean-luma in [0,255] from Layer-3 measure() (B3 stub). Returns
    (fracs, passes, all_pass): each 0-255 bin passes iff it holds >= LUMA_ACTUAL_MIN_COVER
    of frames. This is the audit DEFINITION/틀 only — with measure() stubbed the dry-run has
    no luma_actual, so it becomes runnable once B3 lands (exposure_ev -> render -> luma)."""
    n = len(luma_values)
    counts = [0] * len(LUMA_ACTUAL_EDGES)
    for lv in luma_values:
        for i, (lo, hi) in enumerate(LUMA_ACTUAL_EDGES):
            if lo <= lv < hi:
                counts[i] += 1
                break
    fracs = [c / n if n else 0.0 for c in counts]
    passes = [f >= LUMA_ACTUAL_MIN_COVER for f in fracs]
    return fracs, passes, all(passes)


def summarize(specs):
    """Return per-axis empirical fractions for the audit table."""
    n = len(specs)
    out = {}
    out["pallet_type"] = _tally([s.pallet_type for s in specs],
                                sorted({s.pallet_type for s in specs}))
    out["scene_preset"] = _tally([s.scene_preset for s in specs], SCENE_PRESETS)
    out["proj_size_bin"] = _tally([s.proj_size_bin for s in specs], range(len(PROJ_SIZE_EDGES)))
    out["elev_bin"] = _tally([s.elev_bin for s in specs], range(len(ELEV_BIN_EDGES)))
    out["v_target"] = _tally([s.v_target for s in specs], V_VALUES)
    out["azimuth_bin"] = _tally([s.azimuth_bin for s in specs], range(AZIMUTH_NBINS))
    out["f_target_bin"] = _tally([s.f_target_bin for s in specs], range(len(F_TARGET_EDGES)))
    out["cargo_on"] = _tally([s.cargo_on for s in specs], [False, True])
    out["aspect"] = _tally([s.aspect for s in specs], [a for a, _ in ASPECTS])
    out["fx_mode"] = _tally([s.fx_mode for s in specs], FX_MODES)
    pm = [s.position_mode for s in specs if s.position_mode is not None]
    out["position_mode"] = _tally(pm, POSITION_MODES)
    ev = [s.exposure_ev for s in specs]
    out["exposure_ev"] = ({"min": min(ev), "max": max(ev), "mean": sum(ev) / len(ev)}
                          if ev else {})
    out["_n"] = n
    out["_n_occluded"] = len(pm)
    return out


def _fmt_axis(title, tally, frac_map, n):
    lines = [f"  {title}"]
    for k, c in tally.items():
        emp = c / n if n else 0.0
        pres = frac_map.get(k)
        pres_s = f"{pres:6.3f}" if pres is not None else "   -  "
        lines.append(f"    {str(k):<14} n={c:<6} emp={emp:6.3f}  presc={pres_s}")
    return "\n".join(lines)


def _main():
    ap = argparse.ArgumentParser(description="v2_pipeline dry-run (no Blender)")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--dump", type=str, default="", help="write FrameSpecs as JSONL to this path")
    args = ap.parse_args()

    assets = load_assets()
    print(f"[assets] pallet_types={assets.pallet_types} "
          f"families={list(assets.color_variants)} distractors={len(assets.distractors)}")

    # --- determinism proof: same seed twice => identical spec stream ---
    s1, _ = generate_specs(args.n, args.seed, assets)
    s2, _ = generate_specs(args.n, args.seed, assets)
    ident = all(a.to_dict() == b.to_dict() for a, b in zip(s1, s2))
    s3, _ = generate_specs(args.n, args.seed + 1, assets)
    differs = any(a.to_dict() != b.to_dict() for a, b in zip(s1, s3))
    print(f"[determinism] same seed identical={ident}  different seed differs={differs}")

    # --- distribution audit ---
    specs, qs = generate_specs(args.n, args.seed, assets)
    summ = summarize(specs)
    n = summ["_n"]
    print(f"\n[distribution audit]  n={n}  occluded(f_target>0)={summ['_n_occluded']}")
    pallet_presc = {p: 1.0 / len(assets.pallet_types) for p in assets.pallet_types}
    print(_fmt_axis("pallet_type (uniform)", summ["pallet_type"], pallet_presc, n))
    print(_fmt_axis("scene_preset", summ["scene_preset"], dict(zip(SCENE_PRESETS, SCENE_PRESET_FRAC)), n))
    print(_fmt_axis("proj_size_bin (uniform/geometric)", summ["proj_size_bin"], dict(enumerate(PROJ_SIZE_FRAC)), n))
    print(_fmt_axis("elev_bin", summ["elev_bin"], dict(enumerate(ELEV_BIN_FRAC)), n))
    print(_fmt_axis("v_target (joint w/ elev)", summ["v_target"], dict(zip(V_VALUES, V_FRAC)), n))
    print(_fmt_axis("azimuth_bin (uniform)", summ["azimuth_bin"], dict(enumerate(AZIMUTH_FRAC)), n))
    print(_fmt_axis("f_target_bin", summ["f_target_bin"], dict(enumerate(F_TARGET_FRAC)), n))
    print(_fmt_axis("position_mode (cond.)", summ["position_mode"],
                    dict(zip(POSITION_MODES, POSITION_MODE_FRAC)), summ["_n_occluded"]))
    print(_fmt_axis("cargo_on", summ["cargo_on"], {False: CARGO_FRAC[0], True: CARGO_FRAC[1]}, n))
    print(_fmt_axis("aspect", summ["aspect"], dict(zip([a for a, _ in ASPECTS], ASPECT_FRAC)), n))
    print(_fmt_axis("fx_mode", summ["fx_mode"], dict(zip(FX_MODES, FX_FRAC)), n))
    ev = summ.get("exposure_ev", {})
    if ev:
        print(f"  exposure_ev (U{EXPOSURE_EV_RANGE}, free-random control input): "
              f"min={ev['min']:.3f} mean={ev['mean']:.3f} max={ev['max']:.3f}")
    print(f"  luma_actual: MEASURED in Layer-3 (B3 stub) -> coverage-audit only over "
          f"{LUMA_ACTUAL_LABELS} (>= {LUMA_ACTUAL_MIN_COVER:.0%}/bin, no quota)")

    # --- elevation x V joint table ---
    print("\n[elev x V joint table] rows=elev bins, cols=V; cell=joint P")
    header = "    elev\\V        " + "".join(f"{v:>8}" for v in V_VALUES) + "     rowsum  presc"
    print(header)
    for e in range(len(ELEV_BIN_EDGES)):
        lo, hi = ELEV_BIN_EDGES[e]
        rowsum = sum(ELEV_V_JOINT[e])
        cells = "".join(f"{ELEV_V_JOINT[e][j]:8.3f}" for j in range(len(V_VALUES)))
        print(f"    [{lo:>4.1f},{hi:>4.1f}) {cells}   {rowsum:7.3f}  {ELEV_BIN_FRAC[e]:5.3f}")
    colsum = "".join(f"{sum(ELEV_V_JOINT[e][j] for e in range(len(ELEV_BIN_EDGES))):8.3f}"
                     for j in range(len(V_VALUES)))
    print(f"    colsum       {colsum}")
    print(f"    V presc      " + "".join(f"{f:8.3f}" for f in V_FRAC))

    # --- solve_placement dry-run (PURE geometry, no Blender): reject breakdown -------
    plans = solve_specs(specs, assets)
    # determinism: same seed -> identical spec stream -> identical Plans/Rejects.
    specs_b, _ = generate_specs(args.n, args.seed, assets)
    plans_b = solve_specs(specs_b, assets)

    def _pk(p):
        return json.dumps(p.to_dict(), sort_keys=True)

    plan_ident = all(_pk(a) == _pk(b) for a, b in zip(plans, plans_b))
    accepted = [p for p in plans if isinstance(p, Plan)]
    rejects = [p for p in plans if isinstance(p, Reject)]
    print(f"\n[solve_placement dry-run]  n={len(plans)}  bpy=NONE  "
          f"determinism(same spec => same Plan)={plan_ident}")
    print(f"  accepted={len(accepted)} ({100*len(accepted)/max(1,len(plans)):.1f}%)  "
          f"rejected={len(rejects)}")
    reason_order = ["camera_distance_out_of_range", "v_below_min", "d_occ_fail",
                    "penetration", "resample_exhausted", "C1", "C2"]
    rc = _tally([r.reason for r in rejects], reason_order)
    print("  reject reason breakdown:")
    for k in reason_order:
        c = rc.get(k, 0)
        print(f"    {k:<20} n={c:<6} {100*c/max(1,len(plans)):5.1f}% of all  "
              f"{100*c/max(1,len(rejects)):5.1f}% of rejects")
    with_occ = [p for p in accepted if p.occluder is not None]
    occ_needed = [p for p in accepted if p.f_need > 1e-6]
    print(f"  accepted with occluder placed={len(with_occ)}  "
          f"(f_need>0 among accepted={len(occ_needed)})")
    if with_occ:
        tries = [p.occluder["resample_tries"] for p in with_occ]
        in_band = sum(1 for p in with_occ if p.occluder.get("in_position_band"))
        print(f"  occluder resample tries: mean={sum(tries)/len(tries):.2f} "
              f"min={min(tries)} max={max(tries)} (cap N={RESAMPLE_MAX})")
        print(f"  occluder in position_mode band={in_band}/{len(with_occ)} "
              f"(rest best-effort within 0.9*d_pallet hard gate)")
    if accepted:
        vhit = sum(1 for p in accepted if p.v_probe == p.spec.v_target)
        print(f"  v_target hit exactly among accepted: {vhit}/{len(accepted)} "
              f"({100*vhit/len(accepted):.1f}%)")

    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            for s in specs:
                f.write(json.dumps(s.to_dict()) + "\n")
        print(f"\n[dump] {len(specs)} FrameSpecs -> {args.dump}")


if __name__ == "__main__":
    _main()
