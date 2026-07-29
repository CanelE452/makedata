"""Canonical pallet overlay — the archive `trunc_addon_v1_pilot/overlay` style (bpy-free).

This module is the EXTRACTED ORIGINAL, not a re-interpretation. Every constant, colour, radius,
rectangle and format string below is copied verbatim from the `# === Detailed Overlay ===` block of
`gen_trunc_addon.py::render_frame()` (L577-L712), which produced
`data/pallet/reference/golden_overlay/trunc_addon_v1_pilot/overlay/*.png`
(registry key golden_overlay_reference). That block lived inside a bpy render loop
and could not be reused; here it is the same code with the bpy calls (project(), pal.matrix_world,
meta_extra) replaced by plain arguments.

What the canonical overlay draws, and nothing else:

  1. 12 cuboid edges, coloured per WORLD AXIS  (X red / Y green / Z blue)
  2. 9 keypoint dots with per-ID colours, black outline, id text; off-screen dots go grey
  3. the object pose axes at the centroid (X/Y/Z), with an arrow-less line + end dot + letter
  4. a 175x240 info panel at (6, 6) — 20 lines, 11 px apart
  5. a 90x60 axis legend in the bottom-right corner

It explicitly does NOT draw (these belong to the secondary debug overlay):
  - a full-width black header bar
  - an external multi-column panel beside the image (the output canvas is EXACTLY the input RGB size)
  - M0/M4 mask contours, hulls, audit-failure footers
  - FRONT/REAR/connector edge colours

Data adaptation (v2 labels -> `metadata`) is deliberately NOT done here; see
`overlay_v2_detailed.archive_metadata()`. Drawing code and field mapping stay separated.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont


def _archive_font():
    """The font the archive overlays were actually drawn with: `ImageFont.load_default()`.

    `gen_trunc_addon.py` called `drw.text(...)` with no font. On Pillow >= 10.1 that means the
    anti-aliased TrueType face, and the archive PNGs prove that is what ran: their panel/legend text
    has no pure-white pixel at all (glyph cores peak at 240) and re-rendering the fixed legend with
    `load_default()` reproduces `archive/trunc_addon_v1_pilot/overlay/*.png` with a ZERO pixel diff,
    while the classic 6x11 bitmap face differs on 482 px of that same 91x61 legend box.
    Do not "restore" the bitmap font here — see tests/test_overlay_archive_trunc_style.py.
    """
    return ImageFont.load_default()


FONT = _archive_font()

# --------------------------------------------------------------------------------------
# Constants — verbatim from gen_trunc_addon.py
# --------------------------------------------------------------------------------------

# gen_trunc_addon.py L90
EDGES = [(0, 1), (1, 5), (5, 4), (4, 0), (3, 2), (2, 6), (6, 7), (7, 3),
         (0, 3), (1, 2), (5, 6), (4, 7)]

# gen_trunc_addon.py L621-623
X_EDGES = {(0, 1), (4, 5), (3, 2), (7, 6)}
Y_EDGES = {(0, 4), (1, 5), (3, 7), (2, 6)}
Z_EDGES = {(0, 3), (1, 2), (4, 7), (5, 6)}

COLOR_X_EDGE = (255, 80, 80)
COLOR_Y_EDGE = (80, 220, 80)
COLOR_Z_EDGE = (80, 130, 255)
COLOR_OTHER_EDGE = (200, 200, 200)
EDGE_WIDTH = 2

# gen_trunc_addon.py L633-643
KP_COLORS = {
    0: (255, 165, 0),    # orange
    1: (255, 255, 0),    # yellow
    2: (100, 100, 255),  # light blue
    3: (255, 100, 200),  # pink
    4: (180, 0, 180),    # magenta
    5: (0, 200, 200),    # cyan
    6: (160, 80, 255),   # purple
    7: (255, 50, 50),    # red
    8: (255, 255, 255),  # centroid white
}
COLOR_KP_OFFSCREEN = (130, 130, 130)
KP_RADIUS = 6
KP_RADIUS_CENTROID = 7

# gen_trunc_addon.py L654-666
AXIS_LEN_M = 0.5
AXIS_COLORS = ((255, 60, 60), (60, 220, 60), (80, 130, 255))
AXIS_LABELS = ("X", "Y", "Z")
AXIS_WIDTH = 3
AXIS_END_RADIUS = 4

# gen_trunc_addon.py L669 / L698-699
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 6, 6, 175, 240
PANEL_LINE_H = 11
PANEL_TEXT_DX, PANEL_TEXT_DY = 5, 4
PANEL_BG = (0, 0, 0, 200)      # kept as-is; on an RGB canvas PIL ignores the alpha (opaque black)
PANEL_TEXT = (255, 255, 255)

# gen_trunc_addon.py L702-710
LEGEND_W, LEGEND_H = 90, 60
LEGEND_MARGIN = 6

# Values the panel could not be given. 0 / False are REAL values and never map to these.
MISSING_TEXT = "N/A"
MISSING_FLAG = "?"

# The archive never hit absurd projections, but a truncated v2 corner can project millions of px
# away. Sanitising happens in the input normalisation below, never inside the copied drawing code.
DRAW_CLAMP_PX = 20000.0


# --------------------------------------------------------------------------------------
# Input normalisation (not part of the copied block)
# --------------------------------------------------------------------------------------

def _finite(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(-DRAW_CLAMP_PX, min(DRAW_CLAMP_PX, f))


def normalize_keypoints(points: Sequence[Any]) -> list[tuple[float, float, float]]:
    """9 keypoints as (x, y, z_cam). A 2-tuple means "depth unknown" -> treated as in front.

    z is only used for the archive's off-screen test (`z > 0`), so an unknown depth must not
    silently turn a visible corner grey.
    """
    out: list[tuple[float, float, float]] = []
    for p in points:
        seq = list(p)
        x, y = _finite(seq[0]), _finite(seq[1])
        if len(seq) >= 3 and seq[2] is not None:
            try:
                z = float(seq[2])
            except (TypeError, ValueError):
                z = 1.0
            if z != z:
                z = 1.0
        else:
            z = 1.0
        out.append((x, y, z))
    return out


def normalize_axes(pose_axis_points_2d: Iterable[Any] | None) -> list[tuple | None]:
    """3 items: ((x0, y0), (x1, y1)) for a drawable axis, or None when it must not be drawn.

    Accepts the dict form returned by `overlay_v2_detailed.pose_axis_endpoints()`
    ({'ok', 'start', 'end', ...}) as well as plain (start, end) pairs.
    """
    axes: list[tuple | None] = [None, None, None]
    if not pose_axis_points_2d:
        return axes
    for i, item in enumerate(list(pose_axis_points_2d)[:3]):
        if item is None:
            continue
        if isinstance(item, dict):
            if not item.get("ok") or item.get("start") is None or item.get("end") is None:
                continue
            start, end = item["start"], item["end"]
        else:
            start, end = item
            if start is None or end is None:
                continue
        axes[i] = ((_finite(start[0]), _finite(start[1])), (_finite(end[0]), _finite(end[1])))
    return axes


def corner_bbox_area_pct(keypoints_9: Sequence[Any], width: float, height: float) -> float:
    """gen_trunc_addon.py L605-611 — bbox of the IN-FRAME corners over the image area, in %.

    This is the archive's definition of the panel's `Area:` field (corner bbox, NOT a mask area).
    """
    kps_2d = normalize_keypoints(keypoints_9)
    W, H = float(width), float(height)
    in_pts = [(p[0], p[1]) for p in kps_2d[:8] if 0 <= p[0] <= W and 0 <= p[1] <= H and p[2] > 0]
    if in_pts:
        x_coords = [p[0] for p in in_pts]
        y_coords = [p[1] for p in in_pts]
        area_pct = ((max(x_coords) - min(x_coords)) * (max(y_coords) - min(y_coords))) / (W * H) * 100.0
    else:
        area_pct = 0.0
    return area_pct


# --------------------------------------------------------------------------------------
# Panel text (format strings verbatim from L673-697; only the missing-value guard is new)
# --------------------------------------------------------------------------------------

def _fmt(value: Any, spec: str = "{}") -> str:
    """Format a value, or `N/A` when it is missing. 0 / 0.0 / False are values, not gaps."""
    if value is None:
        return MISSING_TEXT
    try:
        return spec.format(value)
    except (TypeError, ValueError):
        return str(value)


def _yn(value: Any) -> str:
    """'Y' / 'N' for a known flag, '?' when the flag itself is unknown (never a silent 'N')."""
    if value is None:
        return MISSING_FLAG
    return "Y" if value else "N"


def _count(value: Any) -> str:
    return MISSING_FLAG if value is None else str(value)


def format_panel_lines(metadata: dict[str, Any]) -> list[str]:
    """The 20 info-panel lines, in archive order.

    metadata keys (all optional; a missing key renders as N/A / ?):
      frame, object_name, scenario, background, distance_m, cam_dist_surface_m, cam_height_m,
      elevation_deg, worst_combo, lens_mm, hfov_deg, n_in, n_unocc, n_both, area_pct,
      pitch_deg, yaw_deg, roll_deg, quaternion_xyzw, size_mm (W, H, D), camera_xyz,
      truncated, occluded, cargo_count
    """
    m = metadata or {}
    n_in = m.get("n_in")
    n_unocc = m.get("n_unocc")
    n_both = m.get("n_both")
    # L613-614
    kpt_vis_pct = None if n_in is None else (n_in / 8.0) * 100.0
    ray_vis_pct = None if n_unocc is None else (n_unocc / 8.0) * 100.0

    scenario = m.get("scenario")
    scenario_text = MISSING_TEXT if scenario is None else str(scenario)[:18]

    quat = m.get("quaternion_xyzw")
    if isinstance(quat, (list, tuple)) and len(quat) == 4:
        q = [round(float(v), 2) for v in quat]
        quat_text = f"[{q[0]},{q[1]},{q[2]},{q[3]}]"
    else:
        quat_text = MISSING_TEXT

    size_mm = m.get("size_mm")
    if isinstance(size_mm, (list, tuple)) and len(size_mm) == 3:
        size_text = f"{int(size_mm[0])}x{int(size_mm[1])}x{int(size_mm[2])}mm"
    else:
        size_text = MISSING_TEXT

    cam_xyz = m.get("camera_xyz")
    if isinstance(cam_xyz, (list, tuple)) and len(cam_xyz) == 3:
        cam_text = f"({cam_xyz[0]:.1f},{cam_xyz[1]:.1f},{cam_xyz[2]:.1f})"
    else:
        cam_text = MISSING_TEXT

    return [
        f"Frame: {_fmt(m.get('frame'), '{:06d}')}",
        f"Object: {_fmt(m.get('object_name'))}",
        f"Scenario: {scenario_text}",
        f"BG: {_fmt(m.get('background'))}",
        f"Distance: {_fmt(m.get('distance_m'), '{:.2f}m')}",
        f"Cam dist(surf): {_fmt(m.get('cam_dist_surface_m'), '{}m')}",
        f"Cam height: {_fmt(m.get('cam_height_m'), '{}m')}",
        f"Elev: {_fmt(m.get('elevation_deg'), '{}')}deg  V:{_count(n_in)}/8"
        f"{'  WORST' if m.get('worst_combo') else ''}",
        f"Lens: {_fmt(m.get('lens_mm'), '{:.0f}mm')}  HFOV: {_fmt(m.get('hfov_deg'), '{:.1f}°')}",
        f"Kpt Vis: {_fmt(kpt_vis_pct, '{:.0f}%')} ({_count(n_in)}/8)",
        f"Ray Vis: {_fmt(ray_vis_pct, '{:.0f}%')} ({_count(n_unocc)}/8)",
        f"Combined: {_count(n_both)}/8",
        f"Area: {_fmt(m.get('area_pct'), '{:.1f}%')}",
        f"Pitch: {_fmt(m.get('pitch_deg'), '{:+.1f}°')}",
        f"Yaw: {_fmt(m.get('yaw_deg'), '{:+.1f}°')}",
        f"Roll: {_fmt(m.get('roll_deg'), '{:+.1f}°')}",
        f"Q: {quat_text}",
        f"Size: {size_text}",
        f"Cam: {cam_text}",
        f"Trunc: {_yn(m.get('truncated'))} "
        f"Occ: {_yn(m.get('occluded'))} "
        f"Cargo: {_count(m.get('cargo_count'))}",
    ]


# --------------------------------------------------------------------------------------
# Drawing — the copied block
# --------------------------------------------------------------------------------------

def _draw_cuboid_and_keypoints(drw: ImageDraw.ImageDraw,
                               kps_2d: list[tuple[float, float, float]],
                               W: float, H: float) -> None:
    pts2d = [(kp[0], kp[1]) for kp in kps_2d]

    # ---- Draw cuboid edges (per-axis color: connecting Y-axis = green, X-axis = red, Z-axis = blue) ----
    for a, b in EDGES:
        e = (a, b) if (a, b) in X_EDGES | Y_EDGES | Z_EDGES else (b, a)
        if e in X_EDGES: color = COLOR_X_EDGE
        elif e in Y_EDGES: color = COLOR_Y_EDGE
        elif e in Z_EDGES: color = COLOR_Z_EDGE
        else: color = COLOR_OTHER_EDGE
        drw.line([pts2d[a], pts2d[b]], fill=color, width=EDGE_WIDTH)

    # ---- Keypoint dots with per-ID distinct colors ----
    for idx, (x, y, z) in enumerate(kps_2d):
        col = KP_COLORS.get(idx, (255, 255, 255))
        if not (0 <= x <= W and 0 <= y <= H and z > 0):
            col = COLOR_KP_OFFSCREEN
        r = KP_RADIUS_CENTROID if idx == 8 else KP_RADIUS
        drw.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(0, 0, 0))
        # ID label
        drw.text((x + r + 2, y - r - 2), str(idx), fill=(255, 255, 255), font=FONT)


def _draw_pose_axes(drw: ImageDraw.ImageDraw, pose_axis_points_2d: Iterable[Any] | None) -> int:
    drawn = 0
    # ---- Pose axes at centroid (X red, Y green, Z blue) ----
    for axis_idx, segment in enumerate(normalize_axes(pose_axis_points_2d)):
        if segment is None:
            continue
        color = AXIS_COLORS[axis_idx]
        (c_x, c_y), (e_x, e_y) = segment
        drw.line([(c_x, c_y), (e_x, e_y)], fill=color, width=AXIS_WIDTH)
        drw.ellipse([e_x - AXIS_END_RADIUS, e_y - AXIS_END_RADIUS,
                     e_x + AXIS_END_RADIUS, e_y + AXIS_END_RADIUS], fill=color, outline=(0, 0, 0))
        label = AXIS_LABELS[axis_idx]
        drw.text((e_x + 5, e_y + 5), label, fill=color, font=FONT)
        drawn += 1
    return drawn


def _draw_info_panel(drw: ImageDraw.ImageDraw, metadata: dict[str, Any] | None) -> None:
    # ---- Info panel (top-left) ----
    panel_x, panel_y, panel_w, panel_h = PANEL_X, PANEL_Y, PANEL_W, PANEL_H
    drw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h], fill=PANEL_BG)
    info_lines = format_panel_lines(metadata or {})
    for i, line in enumerate(info_lines):
        drw.text((panel_x + PANEL_TEXT_DX, panel_y + PANEL_TEXT_DY + i * PANEL_LINE_H), line,
                 fill=PANEL_TEXT, font=FONT)


def _draw_axis_legend(drw: ImageDraw.ImageDraw, W: int, H: int) -> None:
    # ---- Axis legend (bottom-right) ----
    leg_w, leg_h = LEGEND_W, LEGEND_H
    leg_x, leg_y = W - leg_w - LEGEND_MARGIN, H - leg_h - LEGEND_MARGIN
    drw.rectangle([leg_x, leg_y, leg_x + leg_w, leg_y + leg_h], fill=(0, 0, 0, 200))
    drw.rectangle([leg_x + 5, leg_y + 7, leg_x + 15, leg_y + 17], fill=(255, 60, 60))
    drw.text((leg_x + 20, leg_y + 7), "X axis", fill=(255, 255, 255), font=FONT)
    drw.rectangle([leg_x + 5, leg_y + 22, leg_x + 15, leg_y + 32], fill=(60, 220, 60))
    drw.text((leg_x + 20, leg_y + 22), "Y axis", fill=(255, 255, 255), font=FONT)
    drw.rectangle([leg_x + 5, leg_y + 37, leg_x + 15, leg_y + 47], fill=(80, 130, 255))
    drw.text((leg_x + 20, leg_y + 37), "Z axis", fill=(255, 255, 255), font=FONT)


def draw_archive_style_overlay(rgb_image: Image.Image,
                               projected_keypoints_9: Sequence[Any] | None,
                               pose_axis_points_2d: Iterable[Any] | None = None,
                               metadata: dict[str, Any] | None = None,
                               output_path: Any = None) -> Image.Image:
    """Draw the canonical overlay on a copy of `rgb_image` and (optionally) save it.

    The returned canvas has EXACTLY the size of `rgb_image` — nothing is appended around it.
    `projected_keypoints_9` must hold the 8 cuboid corners followed by the centroid; anything
    shorter (or None) means "no cuboid for this frame" and only the panel/legend are drawn, so a
    label without a usable projection still produces a readable overlay instead of an exception.
    """
    img = rgb_image.convert("RGB").copy()
    W, H = img.size
    drw = ImageDraw.Draw(img)

    kps_2d = normalize_keypoints(projected_keypoints_9 or [])
    if len(kps_2d) >= 9:
        _draw_cuboid_and_keypoints(drw, kps_2d, W, H)
    _draw_pose_axes(drw, pose_axis_points_2d)
    _draw_info_panel(drw, metadata)
    _draw_axis_legend(drw, W, H)

    if output_path is not None:
        img.save(output_path)
    return img
