"""v2 pilot — 논문용 composite Figure 2개 + supporting table.

    Figure 1  Geometric and Camera Coverage
              (a) azimuth x elevation joint density (circular KDE on azimuth)
              (b) camera distance x projected size joint density (bounded KDE)
              (c) deterministic representative montage (12)

    Figure 2  Occlusion and Annotation Quality
              (a) projected size x visible fraction (zero-inflated: point mass 분리)
              (b) annotation reprojection error ECDF (all keypoints / per-frame max)
              (c) annotation overlay montage (6, deterministic anchors)

**새 metric 을 만들지 않는다.** generator 가 이미 저장한 분포와 annotation 만 쓴다.
projection convention 은 재구현하지 않고 `overlay_v2_detailed.frame_geometry()` /
`project_cam_points()` 를 재사용한다(그 helper 가 label 의 projected_cuboid 를
~1e-14 px 로 재현함이 이미 검증돼 있다).

    python scripts/data_prep/blender/build_v2_pilot_paper_figures.py \
        --dir  data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_fullaudit \
        --out  reports/v2_pilot_2k_seed7000/paper_figures \
        --seed 7000
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.patches import Polygon                # noqa: E402

import analyze_v2_continuous as AC                    # noqa: E402  (loader 재사용)
import overlay_v2_detailed as OV                      # noqa: E402  (projection 재사용)
# ★ canonical overlay = --style archive. golden reference
#   (registry: golden_overlay_reference)와 51개 golden 테스트가 이 스타일을 고정한다.
#   Figure 2(c) 는 이걸 그대로 쓴다 — cuboid 만 직접 그리면 pose 축과
#   Pitch/Yaw/Roll 패널이 빠져 규약에서 벗어난다.
import overlay_archive_trunc_style as ARCH            # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

# ---------------------------------------------------------------------------
# plot style — 논문용, colorblind-safe, grayscale 에서도 contour 구분 가능
# ---------------------------------------------------------------------------
PLOT_SEED = 7000
CMAP = "viridis"                 # perceptually uniform · colorblind-safe · grayscale 단조
CONTOUR_COLOR = "0.15"
FIG_DPI = 300
KDE_GRID = 256                   # 축당 grid 수 (figure_manifest 에 기록)
KDE_BW_RULE = "scott"            # bandwidth 규칙 (figure_manifest 에 기록)
BASE_STYLE = {
    "figure.facecolor": "white", "savefig.facecolor": "white",
    "axes.facecolor": "white", "axes.grid": False,
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 9,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "lines.linewidth": 1.1,
    "pdf.fonttype": 42, "ps.fonttype": 42,       # 편집 가능한 vector text
    "svg.fonttype": "none",
    "figure.autolayout": False,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _json_default(o):
    """numpy scalar -> python scalar. canonical JSON 에 numpy 타입이 새면 안 된다."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=_json_default)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return sha_file(path)


def fnum(v):
    """float 또는 None. missing 을 0 으로 대체하지 않는다 (§18 금지 항목)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# KDE (SciPy gaussian_kde, 경계 보정은 reflection)
# ---------------------------------------------------------------------------
def kde_2d(x, y, xlim, ylim, grid=KDE_GRID, circular_x=None, reflect=True):
    """bounded 2D KDE.

    circular_x: (lo, hi) 이면 x 를 주기 변수로 보고 +-period 복제로 seam 을 잇는다.
    reflect   : 경계에서 반사 복제(reflection)로 boundary bias 를 줄인다.
    """
    from scipy.stats import gaussian_kde

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    xs, ys = [x], [y]
    if circular_x is not None:
        period = circular_x[1] - circular_x[0]
        xs += [x - period, x + period]
        ys += [y, y]
    elif reflect:
        xs += [2 * xlim[0] - x, 2 * xlim[1] - x]
        ys += [y, y]
    if reflect:
        base_x = np.concatenate(xs)
        base_y = np.concatenate(ys)
        xs = [base_x, base_x, base_x]
        ys = [base_y, 2 * ylim[0] - base_y, 2 * ylim[1] - base_y]
    sx, sy = np.concatenate(xs), np.concatenate(ys)
    kde = gaussian_kde(np.vstack([sx, sy]), bw_method=KDE_BW_RULE)
    gx = np.linspace(xlim[0], xlim[1], grid)
    gy = np.linspace(ylim[0], ylim[1], grid)
    mx, my = np.meshgrid(gx, gy)
    z = kde(np.vstack([mx.ravel(), my.ravel()])).reshape(mx.shape)
    area = (gx[1] - gx[0]) * (gy[1] - gy[0])
    total = z.sum() * area
    if total > 0:
        z = z / total                    # support 안에서 적분 1 로 정규화
    return gx, gy, z, {"bandwidth_rule": KDE_BW_RULE, "grid": grid,
                       "boundary_correction": ("circular+reflection" if circular_x
                                               else "reflection"),
                       "n_points": int(x.size),
                       "factor": float(kde.factor)}


def density_panel(ax, gx, gy, z, xlabel, ylabel, levels=6):
    im = ax.pcolormesh(gx, gy, z, cmap=CMAP, shading="auto", rasterized=True)
    cs = ax.contour(gx, gy, z, levels=levels, colors=CONTOUR_COLOR,
                    linewidths=0.5, linestyles="solid")
    ax.clabel(cs, inline=True, fontsize=5, fmt="%.2g")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return im


# ---------------------------------------------------------------------------
# deterministic maximin selection (seed 없음 — 순수 결정적)
# ---------------------------------------------------------------------------
def maximin_select(features, ids, k):
    """feature 공간 z-score 후 maximin. 시작점·tie-break 전부 id 오름차순."""
    f = np.asarray(features, dtype=np.float64)
    mu, sd = np.nanmean(f, axis=0), np.nanstd(f, axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    z = (f - mu) / sd
    order = np.argsort(np.asarray(ids))          # id 오름차순으로 고정
    z, ids = z[order], list(np.asarray(ids)[order])
    # 시작점: 중심에서 가장 먼 점 (동률이면 가장 작은 id)
    d0 = np.linalg.norm(z, axis=1)
    chosen = [int(np.argmax(d0 == d0.max()) if False else np.flatnonzero(d0 == d0.max())[0])]
    dist = np.linalg.norm(z - z[chosen[0]], axis=1)
    while len(chosen) < min(k, len(ids)):
        cand = np.flatnonzero(dist == dist.max())
        pick = int(cand[0])                      # tie-break = 가장 작은 index(=id)
        chosen.append(pick)
        dist = np.minimum(dist, np.linalg.norm(z - z[pick], axis=1))
    return [ids[i] for i in chosen], [z[i].tolist() for i in chosen]


# ---------------------------------------------------------------------------
# dataset -> analysis rows
# ---------------------------------------------------------------------------
def build_frames(root: Path):
    """usable frame 별 geometry/visibility/annotation 지표.

    generator 가 이미 저장한 값을 쓰고, azimuth 만 label 의 camera/centroid 로
    계산한다(레코드에 azimuth_actual 이 없다 — azimuth_bin 은 target bin 이다).
    """
    rows, meta = AC.load_dataset(root)
    frames, invalid = [], []
    for r in rows:
        rec = r.get("_rec") if isinstance(r.get("_rec"), dict) else None
        idx = r.get("idx")
        if idx is None:
            continue
        frames.append((idx, r, rec))
    return frames, meta


def frame_metrics(root: Path, idx: int, rec: dict):
    """label + record 로부터 figure 에 필요한 값 전부."""
    stem = "f%04d" % int(idx)
    label_path = root / "labels" / f"{stem}_label.json"
    if not label_path.is_file():
        return None
    label = json.loads(label_path.read_text(encoding="utf-8"))
    objs = label.get("objects") or []
    obj = objs[0] if objs else None
    geom = OV.frame_geometry(label, obj)          # ★ projection convention 재사용
    if geom is None:
        return None

    cam = geom.get("cam_pos")
    cen = geom.get("centroid_w")
    azimuth = elevation = distance = None
    if cam is not None and cen is not None:
        d = np.asarray(cam) - np.asarray(cen)
        azimuth = float(np.degrees(np.arctan2(d[1], d[0])) % 360.0)
        rho = float(np.hypot(d[0], d[1]))
        distance = float(np.linalg.norm(d))
        if distance > 0:
            elevation = float(np.degrees(np.arctan2(d[2], rho)))

    # reprojection: 3D cuboid + centroid 를 K·extrinsic 으로 재투영 -> 저장된 2D 와 비교
    reproj_pts, reproj_max, reproj_centroid = None, None, None
    if (geom.get("corners_cam") is not None and geom.get("uv8") is not None):
        uv, _z = OV.project_cam_points(geom["K"], geom["corners_cam"])
        if uv is not None and np.isfinite(uv).all():
            err = np.linalg.norm(uv - geom["uv8"], axis=1)
            reproj_pts = err.tolist()
            reproj_max = float(err.max())
    if (geom.get("pose_t") is not None and geom.get("uv_centroid") is not None):
        uvc, _ = OV.project_cam_points(geom["K"], geom["pose_t"].reshape(1, 3))
        if uvc is not None and np.isfinite(uvc).all():
            reproj_centroid = float(np.linalg.norm(uvc[0] - geom["uv_centroid"]))
            if reproj_pts is not None:
                reproj_pts.append(reproj_centroid)
                reproj_max = max(reproj_max, reproj_centroid)

    m_vis = fnum(rec.get("mask_area_visible"))
    m_tgt = fnum(rec.get("mask_area_target_only"))
    visible_fraction = (m_vis / m_tgt) if (m_vis is not None and m_tgt and m_tgt > 0) else None

    return {
        "usable_id": int(idx), "frame_id": stem,
        "azimuth_deg": azimuth, "elevation_deg": elevation,
        "camera_distance_m": distance,
        "camera_distance_record_m": fnum(rec.get("camera_distance_actual_m")),
        "elev_actual_record_deg": fnum(rec.get("elev_actual")),
        "projected_size_actual": fnum(rec.get("projected_size_actual")),
        "projected_size_target": fnum(rec.get("projected_size_target")),
        "mask_area_visible": m_vis, "mask_area_target_only": m_tgt,
        "visible_fraction": visible_fraction,
        "occlusion_fraction_from_mask": (None if visible_fraction is None
                                         else 1.0 - visible_fraction),
        "f_total_record": fnum(rec.get("f_total")),
        "f_target": fnum(rec.get("f_target")),
        "diagnostic_mode": rec.get("diagnostic_mode"),
        "pallet_type": rec.get("pallet_type"),
        "background_asset": rec.get("background_asset"),
        "scene_preset": rec.get("scene_preset"),
        "floor_mode": rec.get("floor_mode"),
        "cargo_on": rec.get("cargo_on"),
        "noise_tier": rec.get("noise_tier"),
        "luma_frame_final": fnum(rec.get("luma_frame_final")),
        "luma_pallet_final": fnum(rec.get("luma_pallet_final")),
        "blur_radius_px": fnum(rec.get("blur_radius_px")),
        "gaussian_sigma": fnum(rec.get("gaussian_sigma")),
        "jpeg_quality": fnum(rec.get("jpeg_quality")),
        "reproj_errors_px": reproj_pts,
        "reproj_max_px": reproj_max,
        "reproj_centroid_px": reproj_centroid,
        "reproj_consistency_px": fnum(geom.get("reproj_consistency_px")),
        "K_valid": bool(geom.get("K") is not None),
        "pose_valid": bool(geom.get("pose_R") is not None
                           and geom.get("pose_t") is not None),
        "rgb_rel": f"rgb/{stem}_rgb.png",
        "label_rel": f"labels/{stem}_label.json",
        "_geom": geom, "_label": label, "_obj": obj, "_rec": rec,
    }


def save_fig(fig, out, stem):
    """PDF vector + PNG 300dpi. metadata timestamp 를 제거해 재실행 hash 를 고정한다."""
    meta_pdf = {"CreationDate": None, "Creator": None, "Producer": None}
    meta_png = {"Software": None}
    pdf = out / f"{stem}.pdf"
    png = out / f"{stem}.png"
    fig.savefig(pdf, format="pdf", metadata=meta_pdf, bbox_inches="tight")
    fig.savefig(png, format="png", dpi=FIG_DPI, metadata=meta_png,
                bbox_inches="tight")
    plt.close(fig)
    return {"pdf": sha_file(pdf), "png": sha_file(png)}


def load_rgb(root, rel):
    from PIL import Image
    p = root / rel
    if not p.is_file():
        return None
    with Image.open(p) as im:
        return np.asarray(im.convert("RGB"))


def canonical_overlay(root, frame):
    """canonical overlay(`--style archive`)를 그려 ndarray 로 돌려준다.

    직접 그리지 않는다 — `overlay_archive_trunc_style.draw_archive_style_overlay()` 가
    golden reference(registry: golden_overlay_reference)와 51개 golden 테스트로 고정된
    정본이고, cuboid 뿐 아니라 **pose 축 3종 + Pitch/Yaw/Roll 정보 패널 + 축 범례**를
    함께 그린다.
    """
    from PIL import Image

    p = root / frame["rgb_rel"]
    if not p.is_file():
        return None
    geom = frame["_geom"] or {}
    obj = frame["_obj"] or {}
    lab = frame["_label"] or {}

    kps9 = None
    uv8 = geom.get("uv8")
    cen = geom.get("uv_centroid")
    if uv8 is not None and cen is not None:
        kps9 = [list(map(float, uv8[i])) for i in range(len(uv8))] + \
               [list(map(float, cen))]
    axes = OV.pose_axis_endpoints(geom)
    ctx = OV.build_context(root, frame["usable_id"], lab, obj, None,
                           frame.get("_rec") or {}, None, None, None, geom=geom)
    meta = OV.archive_metadata(ctx)
    with Image.open(p) as im:
        out = ARCH.draw_archive_style_overlay(im.convert("RGB"), kps9, axes, meta)
    return np.asarray(out)


# ---------------------------------------------------------------------------
# Figure 1 — Geometric and Camera Coverage
# ---------------------------------------------------------------------------
def build_figure1(frames, root, out, src, args):
    panels = {}
    az = [(f["usable_id"], f["azimuth_deg"], f["elevation_deg"]) for f in frames
          if f["azimuth_deg"] is not None and f["elevation_deg"] is not None]
    ds = [(f["usable_id"], f["camera_distance_m"], f["projected_size_actual"])
          for f in frames
          if f["camera_distance_m"] is not None
          and f["projected_size_actual"] is not None]

    # frame-level source (모든 frame, missing 은 빈칸으로 남긴다 — 0 으로 대체 금지)
    fig1_frames = [{k: f[k] for k in (
        "usable_id", "frame_id", "azimuth_deg", "elevation_deg",
        "camera_distance_m", "camera_distance_record_m", "elev_actual_record_deg",
        "projected_size_actual", "projected_size_target", "diagnostic_mode",
        "pallet_type", "background_asset", "scene_preset", "cargo_on")}
        for f in frames]
    panels["fig1_frames_csv_sha256"] = write_csv(src / "fig1_frames.csv", fig1_frames)

    # (a) azimuth x elevation — azimuth 는 circular KDE, elevation support 0.5~80
    ELEV_LO, ELEV_HI = 0.5, 80.0
    a_ids = [i for i, a, e in az if ELEV_LO <= e <= ELEV_HI]
    a_x = np.array([a for i, a, e in az if ELEV_LO <= e <= ELEV_HI])
    a_y = np.array([e for i, a, e in az if ELEV_LO <= e <= ELEV_HI])
    elev_out = [(i, e) for i, a, e in az if not (ELEV_LO <= e <= ELEV_HI)]
    gx1, gy1, z1, kmeta1 = kde_2d(a_x, a_y, (0.0, 360.0), (ELEV_LO, ELEV_HI),
                                  circular_x=(0.0, 360.0))
    panels["panel_a_kde"] = kmeta1
    panels["panel_a_elevation_support"] = [ELEV_LO, ELEV_HI]
    panels["panel_a_outside_support"] = {"count": len(elev_out),
                                         "ids": [i for i, _e in elev_out][:50]}
    write_csv(src / "fig1_density_azimuth_elevation.csv",
              [{"azimuth_deg": float(x), "elevation_deg": float(y),
                "density": float(z1[j, i])}
               for j, y in enumerate(gy1) for i, x in enumerate(gx1)])

    # (b) distance x projected size — bounded, 1 초과는 clip 하지 않고 별도 집계
    DIST_LO, DIST_HI, PS_LO, PS_HI = 0.0, 10.0, 0.0, 1.0
    ps_all = np.array([p for _i, _d, p in ds])
    over = [(i, p) for i, _d, p in ds if p > PS_HI]
    keep = [(i, d, p) for i, d, p in ds if PS_LO <= p <= PS_HI]
    b_x = np.array([d for _i, d, _p in keep])
    b_y = np.array([p for _i, _d, p in keep])
    gx2, gy2, z2, kmeta2 = kde_2d(b_x, b_y, (DIST_LO, DIST_HI), (PS_LO, PS_HI))
    panels["panel_b_kde"] = kmeta2
    panels["panel_b_excluded_projected_size_gt1"] = {
        "count": len(over), "fraction": len(over) / max(len(ds), 1),
        "max_projected_size": float(ps_all.max()) if ps_all.size else None,
        "ids": [i for i, _p in over][:50],
        "note": "truncation 의 raw-corner 때문에 1 을 넘는 frame 은 clip 하지 않고 제외 집계",
    }
    panels["panel_b_distance_max_m"] = float(max(d for _i, d, _p in ds)) if ds else None
    panels["panel_b_distance_gt10_count"] = sum(1 for _i, d, _p in ds if d > DIST_HI)
    write_csv(src / "fig1_density_distance_scale.csv",
              [{"camera_distance_m": float(x), "projected_size": float(y),
                "density": float(z2[j, i])}
               for j, y in enumerate(gy2) for i, x in enumerate(gx2)])

    # (c) deterministic maximin montage
    feat_ids, feats = [], []
    for f in frames:
        vals = (f["azimuth_deg"], f["elevation_deg"], f["camera_distance_m"],
                f["projected_size_actual"])
        if all(v is not None for v in vals):
            feat_ids.append(f["usable_id"])
            a = math.radians(vals[0])
            feats.append([math.cos(a), math.sin(a), vals[1], vals[2], vals[3]])
    sel_ids, sel_z = maximin_select(feats, feat_ids, args.montage_n)
    by_id = {f["usable_id"]: f for f in frames}
    sel_rows = [{
        "rank": r, "usable_id": i, "frame_id": by_id[i]["frame_id"],
        "azimuth_deg": by_id[i]["azimuth_deg"],
        "elevation_deg": by_id[i]["elevation_deg"],
        "camera_distance_m": by_id[i]["camera_distance_m"],
        "projected_size_actual": by_id[i]["projected_size_actual"],
        "diagnostic_mode": by_id[i]["diagnostic_mode"],
        "selection_rule": "deterministic maximin in z-scored "
                          "(cos az, sin az, elevation, distance, projected size); "
                          "tie-break = smallest usable_id; no random seed",
    } for r, i in enumerate(sel_ids)]
    panels["fig1_selected_csv_sha256"] = write_csv(
        src / "fig1_selected_frames.csv", sel_rows)
    panels["panel_c_selected_ids"] = sel_ids

    # ---- compose ----
    fig = plt.figure(figsize=(7.2, 6.4))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.0, 1.0, 1.25], hspace=0.42,
                          wspace=0.28)
    ax_a = fig.add_subplot(gs[0, :])
    im = density_panel(ax_a, gx1, gy1, z1,
                       "Realized camera azimuth [deg]",
                       "Realized camera elevation [deg]")
    ax_a.set_xlim(0, 360); ax_a.set_xticks([0, 90, 180, 270, 360])
    ax_a.set_ylim(ELEV_LO, ELEV_HI)
    ax_a.set_title("(a) Azimuth x elevation joint density (circular KDE in azimuth)",
                   loc="left")
    fig.colorbar(im, ax=ax_a, pad=0.01, label="density")

    ax_b = fig.add_subplot(gs[1, :])
    im2 = density_panel(ax_b, gx2, gy2, z2,
                        "Realized camera distance [m]",
                        "Realized projected size [image-width ratio]")
    ax_b.set_xlim(DIST_LO, DIST_HI); ax_b.set_ylim(PS_LO, PS_HI)
    ax_b.set_title("(b) Camera distance x projected size joint density", loc="left")
    fig.colorbar(im2, ax=ax_b, pad=0.01, label="density")

    gsc = gs[2, :].subgridspec(2, 6, hspace=0.55, wspace=0.06)
    for n, fid in enumerate(sel_ids):
        ax = fig.add_subplot(gsc[n // 6, n % 6])
        img = load_rgb(root, by_id[fid]["rgb_rel"])
        if img is not None:
            ax.imshow(img, interpolation="nearest")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_linewidth(0.4)
        f = by_id[fid]
        ax.set_xlabel(
            "%s\n%.1fm  az %.0f°\nel %.0f°  s %.2f"
            % (f["frame_id"], f["camera_distance_m"], f["azimuth_deg"],
               f["elevation_deg"], f["projected_size_actual"]),
            fontsize=4.6, labelpad=1.5)
    fig.text(0.012, 0.305, "(c) Deterministic representative montage",
             fontsize=9, ha="left")
    panels["fig1_files"] = save_fig(fig, out, "fig1_geometric_camera_coverage")

    # 단독 panel
    for stem, builder in (
        ("fig1a_azimuth_elevation",
         lambda ax: (density_panel(ax, gx1, gy1, z1,
                                   "Realized camera azimuth [deg]",
                                   "Realized camera elevation [deg]"),
                     ax.set_xlim(0, 360), ax.set_ylim(ELEV_LO, ELEV_HI))),
        ("fig1b_distance_projected_size",
         lambda ax: (density_panel(ax, gx2, gy2, z2,
                                   "Realized camera distance [m]",
                                   "Realized projected size [image-width ratio]"),
                     ax.set_xlim(DIST_LO, DIST_HI), ax.set_ylim(PS_LO, PS_HI))),
    ):
        f1 = plt.figure(figsize=(3.4, 2.4))
        builder(f1.add_subplot(111))
        panels[stem] = save_fig(f1, out, stem)
    return panels


# ---------------------------------------------------------------------------
# Figure 2 — Occlusion and Annotation Quality
# ---------------------------------------------------------------------------
def build_figure2(frames, root, out, src, args):
    panels = {}
    vis_rows = [{
        "usable_id": f["usable_id"], "frame_id": f["frame_id"],
        "projected_size_actual": f["projected_size_actual"],
        "mask_area_visible": f["mask_area_visible"],
        "mask_area_target_only": f["mask_area_target_only"],
        "visible_fraction": f["visible_fraction"],
        "occlusion_fraction_from_mask": f["occlusion_fraction_from_mask"],
        "f_total_record": f["f_total_record"], "f_target": f["f_target"],
        "f_total_vs_mask_abs_diff": (
            None if (f["f_total_record"] is None
                     or f["occlusion_fraction_from_mask"] is None)
            else abs(f["f_total_record"] - f["occlusion_fraction_from_mask"])),
        "diagnostic_mode": f["diagnostic_mode"],
    } for f in frames]
    panels["fig2_visibility_csv_sha256"] = write_csv(src / "fig2_visibility.csv",
                                                     vis_rows)
    diffs = [r["f_total_vs_mask_abs_diff"] for r in vis_rows
             if r["f_total_vs_mask_abs_diff"] is not None]
    panels["f_total_vs_mask_ratio"] = {
        "compared": len(diffs),
        "max_abs_diff": float(max(diffs)) if diffs else None,
        "note": "record 의 f_total 과 mask ratio 로 재계산한 값의 차이",
    }

    usable = [(f["projected_size_actual"], f["visible_fraction"], f["usable_id"])
              for f in frames
              if f["projected_size_actual"] is not None
              and f["visible_fraction"] is not None]
    full_vis = [t for t in usable if t[1] >= 1.0 - 1e-9]
    partial = [t for t in usable if t[1] < 1.0 - 1e-9]
    panels["panel_a_point_mass"] = {
        "n_total": len(usable), "n_fully_visible": len(full_vis),
        "p_fully_visible": len(full_vis) / max(len(usable), 1),
        "note": "zero-inflated — visible_fraction=1 은 point mass 로 분리해 그린다",
    }
    PS_LO, PS_HI = 0.0, 1.0
    gx3 = gy3 = z3 = kmeta3 = None
    px = np.array([min(max(p, PS_LO), PS_HI) for p, _v, _i in partial])
    pv = np.array([v for _p, v, _i in partial])
    if px.size >= 8:
        gx3, gy3, z3, kmeta3 = kde_2d(px, pv, (PS_LO, PS_HI), (0.0, 1.0))
        write_csv(src / "fig2_density_scale_visibility.csv",
                  [{"projected_size": float(x), "visible_fraction": float(y),
                    "density": float(z3[j, i])}
                   for j, y in enumerate(gy3) for i, x in enumerate(gx3)])
    panels["panel_a_kde"] = kmeta3

    pt_rows, fr_rows = [], []
    for f in frames:
        for kpi, e in enumerate(f["reproj_errors_px"] or []):
            pt_rows.append({"usable_id": f["usable_id"], "keypoint_index": kpi,
                            "reprojection_error_px": e})
        fr_rows.append({"usable_id": f["usable_id"], "frame_id": f["frame_id"],
                        "reproj_max_px": f["reproj_max_px"],
                        "reproj_centroid_px": f["reproj_centroid_px"],
                        "reproj_consistency_px": f["reproj_consistency_px"],
                        "K_valid": f["K_valid"], "pose_valid": f["pose_valid"]})
    panels["fig2_reprojection_points_csv_sha256"] = write_csv(
        src / "fig2_reprojection_points.csv", pt_rows)
    panels["fig2_reprojection_frames_csv_sha256"] = write_csv(
        src / "fig2_reprojection_frames.csv", fr_rows)
    all_err = np.array([r["reprojection_error_px"] for r in pt_rows], dtype=float)
    max_err = np.array([r["reproj_max_px"] for r in fr_rows
                        if r["reproj_max_px"] is not None], dtype=float)

    def q(a, p):
        return float(np.percentile(a, p)) if a.size else None

    panels["panel_b_stats"] = {
        "keypoints": int(all_err.size),
        "median_px": q(all_err, 50), "p95_px": q(all_err, 95),
        "p99_px": q(all_err, 99),
        "max_px": float(all_err.max()) if all_err.size else None,
        "frames_with_valid_annotation": int(max_err.size),
        "invalid_K": sum(1 for r in fr_rows if not r["K_valid"]),
        "invalid_pose": sum(1 for r in fr_rows if not r["pose_valid"]),
        "invalid_frames": sum(1 for f in frames if not f["reproj_errors_px"]),
        "gate_rule": "label 이 float 좌표를 그대로 저장하므로 max <= 1e-4 px",
        "gate_threshold_px": 1e-4,
        "unit_note": "픽셀 단위 — annotation 의 기하 자기일관성이지 모델 성능이 아니다",
    }

    anchors, used = [], set()
    ps_sorted = sorted(usable, key=lambda t: (t[0], t[2]))
    for name, tv in (("fully visible", 1.0), ("mildly occluded", 0.90),
                     ("moderately occluded", 0.65), ("strongly occluded", 0.35)):
        pool = [t for t in usable if t[2] not in used] or usable
        t = min(pool, key=lambda x: (abs(x[1] - tv), x[2]))
        used.add(t[2])
        anchors.append({"anchor": name, "target_visible_fraction": tv,
                        "usable_id": t[2], "projected_size_actual": t[0],
                        "visible_fraction": t[1],
                        "selection_rule": "closest visible_fraction to target; "
                                          "tie-break smallest usable_id"})
    for name, pos in (("small projected size", 0), ("large projected size", -1)):
        cand = [t for t in ps_sorted if t[2] not in used] or ps_sorted
        t = cand[pos]
        used.add(t[2])
        anchors.append({"anchor": name, "target_visible_fraction": None,
                        "usable_id": t[2], "projected_size_actual": t[0],
                        "visible_fraction": t[1],
                        "selection_rule": "extreme projected size; "
                                          "tie-break smallest usable_id"})
    panels["fig2_selected_csv_sha256"] = write_csv(src / "fig2_selected_frames.csv",
                                                   anchors)
    panels["panel_c_anchor_ids"] = [a["usable_id"] for a in anchors]

    by_id = {f["usable_id"]: f for f in frames}
    fig = plt.figure(figsize=(7.2, 6.6))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.0, 1.0, 1.15], hspace=0.46,
                          wspace=0.30)
    ax_a = fig.add_subplot(gs[0, :])
    if gx3 is not None:
        im = density_panel(ax_a, gx3, gy3, z3,
                           "Realized projected size [image-width ratio]",
                           "Visible fraction of the pallet")
        fig.colorbar(im, ax=ax_a, pad=0.01, label="density")
    ax_a.set_xlim(PS_LO, PS_HI)
    ax_a.set_ylim(0.0, 1.0)
    if full_vis:
        ax_a.scatter([t[0] for t in full_vis], [1.005] * len(full_vis),
                     s=2.0, marker="|", color="0.1", clip_on=False,
                     label="fully visible (P=%.3f)"
                           % (len(full_vis) / max(len(usable), 1)))
        ax_a.legend(loc="lower left", frameon=False)
    ax_a.set_title("(a) Projected size x visible fraction "
                   "(point mass at 1 shown separately)", loc="left")

    ax_b = fig.add_subplot(gs[1, :])
    for arr, lab, ls, cl in ((all_err, "all keypoints", "-", "0.15"),
                             (max_err, "per-frame maximum", "--", "0.45")):
        if arr.size:
            s = np.sort(arr)
            ax_b.step(s, np.arange(1, s.size + 1) / s.size, where="post",
                      linestyle=ls, label=lab, color=cl)
    ax_b.set_xscale("log")
    ax_b.axvline(1e-4, color="#D55E00", linewidth=0.7, linestyle="--",
                 label="serialization gate (1e-4 px)")
    ax_b.axvline(1.0, color="0.6", linewidth=0.7, linestyle=":", label="1 px")
    ax_b.set_xlim(1e-16, 10.0)
    ax_b.set_xlabel("Reprojection error [px]  (log scale)")
    ax_b.set_ylabel("Cumulative fraction")
    ax_b.set_ylim(0, 1.02)
    ax_b.legend(loc="center left", frameon=False)
    st = panels["panel_b_stats"]
    ax_b.set_title("(b) Annotation reprojection error ECDF "
                   "(median %.2e, p95 %.2e, p99 %.2e, max %.2e px; invalid %d)"
                   % (st["median_px"] or 0, st["p95_px"] or 0, st["p99_px"] or 0,
                      st["max_px"] or 0, st["invalid_frames"]), loc="left")

    gsc = gs[2, :].subgridspec(1, 6, wspace=0.06)
    for n, a in enumerate(anchors):
        ax = fig.add_subplot(gsc[0, n])
        f = by_id[a["usable_id"]]
        img = canonical_overlay(root, f)          # ★ --style archive 정본
        if img is not None:
            ax.imshow(img, interpolation="nearest")
            ax.set_xlim(0, img.shape[1])
            ax.set_ylim(img.shape[0], 0)
            ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlabel("%s\n%s  v=%.2f" % (a["anchor"], f["frame_id"],
                                          a["visible_fraction"]),
                      fontsize=4.6, labelpad=1.5)
    fig.text(0.012, 0.30,
             "(c) Annotation overlay montage — canonical archive style "
             "(GT cuboid + pose axes + pitch/yaw/roll panel)",
             fontsize=9, ha="left")
    panels["fig2_files"] = save_fig(fig, out, "fig2_occlusion_annotation_quality")

    f2a = plt.figure(figsize=(3.4, 2.4))
    axa = f2a.add_subplot(111)
    if gx3 is not None:
        density_panel(axa, gx3, gy3, z3, "Realized projected size",
                      "Visible fraction")
    axa.set_xlim(PS_LO, PS_HI)
    axa.set_ylim(0, 1)
    panels["fig2a_scale_visibility"] = save_fig(f2a, out, "fig2a_scale_visibility")

    f2b = plt.figure(figsize=(3.4, 2.4))
    axb = f2b.add_subplot(111)
    for arr, lab, ls, cl in ((all_err, "all keypoints", "-", "0.15"),
                             (max_err, "per-frame maximum", "--", "0.45")):
        if arr.size:
            s = np.sort(arr)
            axb.step(s, np.arange(1, s.size + 1) / s.size, where="post",
                     linestyle=ls, label=lab, color=cl)
    axb.set_xscale("log")
    axb.axvline(1e-4, color="#D55E00", linewidth=0.7, linestyle="--")
    axb.axvline(1.0, color="0.6", linewidth=0.7, linestyle=":")
    axb.set_xlim(1e-16, 10.0)
    axb.set_xlabel("Reprojection error [px]  (log scale)")
    axb.set_ylabel("Cumulative fraction")
    axb.legend(loc="center left", frameon=False)
    panels["fig2b_reprojection_ecdf"] = save_fig(f2b, out, "fig2b_reprojection_ecdf")
    return panels


# ---------------------------------------------------------------------------
# §14 supporting table
# ---------------------------------------------------------------------------
def build_table(frames, recs, out, meta):
    import collections

    def col(key):
        return np.array([f[key] for f in frames if f[key] is not None], dtype=float)

    def q4(a):
        return "%.3f / %.3f / %.3f / %.3f" % (a.min(), np.median(a),
                                              np.percentile(a, 95), a.max())

    dist, ps = col("camera_distance_m"), col("projected_size_actual")
    elev, vis = col("elevation_deg"), col("visible_fraction")
    err = np.array([e for f in frames for e in (f["reproj_errors_px"] or [])],
                   dtype=float)
    modes = collections.Counter(f["diagnostic_mode"] for f in frames)
    rows = [
        ("usable frame count", len(frames)),
        ("resolution / aspect", "640x480 / 4:3"),
        ("camera distance [m] min/median/p95/max", q4(dist) if dist.size else "n/a"),
        ("projected size min/median/p95/max", q4(ps) if ps.size else "n/a"),
        ("elevation [deg] min/median/p95/max", q4(elev) if elev.size else "n/a"),
        ("fully visible fraction",
         "%.4f" % float((vis >= 1.0 - 1e-9).mean()) if vis.size else "n/a"),
        ("occluded fraction",
         "%.4f" % float((vis < 1.0 - 1e-9).mean()) if vis.size else "n/a"),
        ("visible fraction p05/median/p95",
         "%.3f / %.3f / %.3f" % (np.percentile(vis, 5), np.median(vis),
                                 np.percentile(vis, 95)) if vis.size else "n/a"),
    ]
    for m in ("clean-static", "cargo-only", "context-rich", "controlled-occlusion"):
        rows.append(("scene mode: %s" % m, modes.get(m, 0)))
    lf, br, gsg, jq = (col("luma_frame_final"), col("blur_radius_px"),
                       col("gaussian_sigma"), col("jpeg_quality"))
    rows += [
        ("cargo on / off", "%d / %d" % (sum(1 for f in frames if f["cargo_on"]),
                                        sum(1 for f in frames if not f["cargo_on"]))),
        ("distinct backgrounds",
         len({f["background_asset"] for f in frames if f["background_asset"]})),
        ("distinct pallet types",
         len({f["pallet_type"] for f in frames if f["pallet_type"]})),
        ("distinct scene presets",
         len({f["scene_preset"] for f in frames if f["scene_preset"]})),
        ("frame luma p05/median/p95",
         "%.3f / %.3f / %.3f" % tuple(np.percentile(lf, [5, 50, 95]))
         if lf.size else "n/a"),
        ("blur radius [px] median/max",
         "%.2f / %.2f" % (np.median(br), br.max()) if br.size else "n/a"),
        ("gaussian sigma median/max",
         "%.4f / %.4f" % (np.median(gsg), gsg.max()) if gsg.size else "n/a"),
        ("jpeg quality median/min",
         "%.0f / %.0f" % (np.median(jq), jq.min()) if jq.size else "n/a"),
        ("annotation invalid count",
         sum(1 for f in frames if not f["reproj_errors_px"])),
        ("reprojection median/p95/p99/max [px]",
         "%.2e / %.2e / %.2e / %.2e" % (np.median(err), np.percentile(err, 95),
                                        np.percentile(err, 99), err.max())
         if err.size else "n/a"),
    ]
    csv_sha = write_csv(out / "table_dataset_statistics.csv",
                        [{"metric": k, "value": str(v)} for k, v in rows])
    tex = ["\\begin{tabular}{ll}", "\\toprule", "Metric & Value \\\\", "\\midrule"]
    for k, v in rows:
        tex.append("%s & %s \\\\" % (str(k).replace("_", "\\_"),
                                     str(v).replace("_", "\\_")))
    tex += ["\\bottomrule", "\\end{tabular}", ""]
    (out / "table_dataset_statistics.tex").write_text("\n".join(tex),
                                                      encoding="utf-8")
    return {"csv_sha256": csv_sha,
            "tex_sha256": sha_file(out / "table_dataset_statistics.tex")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="pilot dataset root")
    ap.add_argument("--out", required=True, help="figure output dir")
    ap.add_argument("--seed", type=int, default=PLOT_SEED)
    ap.add_argument("--montage-n", type=int, default=12)
    ap.add_argument("--overlay-n", type=int, default=6)
    args = ap.parse_args(argv)

    root = Path(args.dir if os.path.isabs(args.dir)
                else os.path.join(PROJECT_ROOT, args.dir))
    out = Path(args.out if os.path.isabs(args.out)
               else os.path.join(PROJECT_ROOT, args.out))
    src = out / "figure_source"
    out.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update(BASE_STYLE)
    np.random.seed(args.seed)                    # plot seed 고정 (§11)

    # ---- load ----
    rows, meta = AC.load_dataset(root)
    recs = {}
    with open(root / "records.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                key = r.get("usable_id", r.get("idx"))
                if isinstance(key, int):
                    recs[key] = r
    frames = []
    for idx in sorted(recs):
        m = frame_metrics(root, idx, recs[idx])
        if m is not None:
            frames.append(m)
    if not frames:
        raise SystemExit(f"프레임을 하나도 읽지 못했습니다: {root}")
    print(f"[FIG] frames={len(frames)}  root={root}", flush=True)

    manifest = {
        "dataset_root": os.path.relpath(root, PROJECT_ROOT).replace(os.sep, "/"),
        "frames": len(frames), "plot_seed": args.seed,
        "kde": {"library": "scipy.stats.gaussian_kde",
                "bandwidth_rule": KDE_BW_RULE, "grid_per_axis": KDE_GRID,
                "normalization": "support 안 적분 1",
                "note": "discrete 변수에는 KDE 를 쓰지 않는다"},
        "style": {"cmap": CMAP, "dpi": FIG_DPI, "font_pt": BASE_STYLE["font.size"],
                  "vector_text": "pdf.fonttype=42", "raster": "density mesh only"},
        "panels": {},
    }
    manifest["panels"].update(build_figure1(frames, root, out, src, args))
    manifest["panels"].update(build_figure2(frames, root, out, src, args))
    manifest["table"] = build_table(frames, recs, out, meta)

    # 산출물 hash (재현성 비교용)
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "figure_manifest.json":
            files[str(p.relative_to(out)).replace(os.sep, "/")] = sha_file(p)
    manifest["output_sha256"] = files
    (out / "figure_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True,
                   default=_json_default),
        encoding="utf-8")
    print(f"[FIG] wrote {len(files)} files -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
