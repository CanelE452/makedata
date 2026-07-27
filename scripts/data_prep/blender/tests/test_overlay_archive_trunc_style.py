"""Exact-match tests for the canonical archive overlay (overlay_archive_trunc_style.py).

The point of this module is that it IS the old `gen_trunc_addon.render_frame()` drawing block, so
these tests pin the literal constants of `data/pallet/archive/trunc_addon_v1_pilot/overlay`:
colours, radii, the 175x240 panel at (6, 6) with 11 px line spacing, the 90x60 bottom-right legend,
and the rule that the output canvas is exactly the input RGB.
"""
import ast
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


MODULE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "overlay_archive_trunc_style.py")
)
# The file the canonical block was lifted from (`render_frame()` L577-712).
ARCHIVE_SOURCE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "gen_trunc_addon.py")
)


def _load_module():
    spec = importlib.util.spec_from_file_location("overlay_archive_trunc_style", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("overlay_archive_trunc_style", module)
    spec.loader.exec_module(module)
    return module


AR = _load_module()

# One real archive overlay, used as the golden reference for the fixed-content legend box.
ARCHIVE_SAMPLE = (Path(__file__).resolve().parents[4]
                  / "data/pallet/archive/trunc_addon_v1_pilot/overlay/000000.png")

W, H = 640, 480
BG = (30, 40, 50)
# Front square / rear square, kept clear of the info panel (x<=181, y<=246) and of the legend.
KPS = [(220, 80), (500, 80), (500, 360), (220, 360),
       (260, 120), (540, 120), (540, 400), (260, 400),
       (380, 240)]


def kps_with_z(z_by_index=None):
    z_by_index = z_by_index or {}
    return [(x, y, z_by_index.get(i, 2.0)) for i, (x, y) in enumerate(KPS)]


def _runs(indices):
    """[(start, length), ...] for the contiguous runs of a sorted index array."""
    runs = []
    for i in indices:
        if runs and i == runs[-1][0] + runs[-1][1]:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((int(i), 1))
    return runs


def render(keypoints=None, axes=None, metadata=None, size=(W, H)):
    base = Image.new("RGB", size, BG)
    img = AR.draw_archive_style_overlay(base, keypoints if keypoints is not None else kps_with_z(),
                                        axes, metadata or {})
    return img, img.load()


# ------------------------------------------------------------------------------------------
# 1. edges: membership + exact RGB + width
# ------------------------------------------------------------------------------------------

class TestEdges(unittest.TestCase):
    def test_edge_list_matches_archive(self):
        self.assertEqual(AR.EDGES, [(0, 1), (1, 5), (5, 4), (4, 0), (3, 2), (2, 6), (6, 7), (7, 3),
                                    (0, 3), (1, 2), (5, 6), (4, 7)])

    def test_axis_edge_sets_match_archive(self):
        self.assertEqual(AR.X_EDGES, {(0, 1), (4, 5), (3, 2), (7, 6)})
        self.assertEqual(AR.Y_EDGES, {(0, 4), (1, 5), (3, 7), (2, 6)})
        self.assertEqual(AR.Z_EDGES, {(0, 3), (1, 2), (4, 7), (5, 6)})
        # every drawn edge belongs to exactly one axis class (no grey fallback in practice)
        classified = AR.X_EDGES | AR.Y_EDGES | AR.Z_EDGES
        for a, b in AR.EDGES:
            self.assertTrue((a, b) in classified or (b, a) in classified, f"edge {(a, b)}")

    def test_edge_colors_are_the_archive_rgb(self):
        self.assertEqual(AR.COLOR_X_EDGE, (255, 80, 80))
        self.assertEqual(AR.COLOR_Y_EDGE, (80, 220, 80))
        self.assertEqual(AR.COLOR_Z_EDGE, (80, 130, 255))
        self.assertEqual(AR.COLOR_OTHER_EDGE, (200, 200, 200))
        self.assertEqual(AR.EDGE_WIDTH, 2)

    def test_edges_are_painted_with_those_colors(self):
        _, px = render()
        self.assertEqual(px[360, 80], (255, 80, 80))    # 0-1, X edge
        self.assertEqual(px[240, 100], (80, 220, 80))   # 0-4, Y edge
        self.assertEqual(px[220, 220], (80, 130, 255))  # 0-3, Z edge

    def test_edge_width_is_two_pixels(self):
        img, _ = render()
        arr = np.asarray(img)
        column = arr[:, 360, :]                      # vertical slice: 4 horizontal X-axis edges
        painted = np.where(np.all(column == np.array([255, 80, 80]), axis=-1))[0]
        runs = _runs(painted)
        self.assertEqual(len(runs), 4)
        for start, length in runs:
            self.assertEqual(length, AR.EDGE_WIDTH)


# ------------------------------------------------------------------------------------------
# 2. keypoints: per-id colour, off-screen grey, radii
# ------------------------------------------------------------------------------------------

class TestKeypoints(unittest.TestCase):
    def test_kp_colors_match_archive(self):
        self.assertEqual(AR.KP_COLORS, {
            0: (255, 165, 0), 1: (255, 255, 0), 2: (100, 100, 255), 3: (255, 100, 200),
            4: (180, 0, 180), 5: (0, 200, 200), 6: (160, 80, 255), 7: (255, 50, 50),
            8: (255, 255, 255),
        })
        self.assertEqual(AR.COLOR_KP_OFFSCREEN, (130, 130, 130))
        self.assertEqual(AR.KP_RADIUS, 6)
        self.assertEqual(AR.KP_RADIUS_CENTROID, 7)

    def test_every_dot_uses_its_id_color(self):
        _, px = render()
        for i, (x, y) in enumerate(KPS):
            self.assertEqual(px[x, y], AR.KP_COLORS[i], f"keypoint {i}")

    def test_behind_camera_dot_is_gray(self):
        _, px = render(keypoints=kps_with_z({5: -1.0}))
        self.assertEqual(px[540, 120], (130, 130, 130))
        self.assertEqual(px[500, 80], AR.KP_COLORS[1])   # its neighbours keep their colour

    def test_off_image_dot_is_gray_and_its_color_never_appears(self):
        pts = kps_with_z()
        pts[1] = (W + 40.0, 80.0, 2.0)                   # right of the image border
        img, _ = render(keypoints=pts)
        arr = np.asarray(img)
        self.assertFalse(np.any(np.all(arr == np.array(AR.KP_COLORS[1]), axis=-1)))

    def test_corner_radius_6_and_centroid_radius_7(self):
        _, px = render()
        self.assertEqual(px[220, 80 - 7], BG)              # outside the r=6 marker
        self.assertEqual(px[220, 80 - 6], (0, 0, 0))       # the marker outline
        self.assertEqual(px[380, 240 - 8], BG)             # outside the r=7 centroid marker
        self.assertEqual(px[380, 240 - 7], (0, 0, 0))

    def test_missing_projection_draws_panel_only(self):
        img, px = render(keypoints=[])
        self.assertEqual(img.size, (W, H))
        self.assertEqual(px[6, 6], (0, 0, 0))              # panel still there
        arr = np.asarray(img)
        self.assertFalse(np.any(np.all(arr == np.array(AR.KP_COLORS[0]), axis=-1)))


# ------------------------------------------------------------------------------------------
# 3. pose axes
# ------------------------------------------------------------------------------------------

class TestPoseAxes(unittest.TestCase):
    AXES = [((300, 240), (400, 240)), ((300, 240), (300, 140)), ((300, 240), (360, 300))]

    def test_axis_constants(self):
        self.assertEqual(AR.AXIS_COLORS, ((255, 60, 60), (60, 220, 60), (80, 130, 255)))
        self.assertEqual(AR.AXIS_LABELS, ("X", "Y", "Z"))
        self.assertEqual(AR.AXIS_LEN_M, 0.5)
        self.assertEqual(AR.AXIS_WIDTH, 3)

    def test_axes_are_drawn_in_axis_colors(self):
        _, px = render(axes=self.AXES)
        self.assertEqual(px[350, 240], (255, 60, 60))
        self.assertEqual(px[300, 190], (60, 220, 60))
        self.assertEqual(px[330, 270], (80, 130, 255))

    def test_dict_form_respects_ok_flag(self):
        _, px = render(axes=[{"ok": False, "start": (300, 240), "end": (400, 240)},
                             {"ok": True, "start": (300, 240), "end": (300, 140)},
                             None])
        self.assertEqual(px[350, 240], BG)            # ok=False axis not drawn
        self.assertEqual(px[330, 270], BG)            # None axis not drawn
        self.assertEqual(px[300, 190], (60, 220, 60))

    def test_no_axes_at_all(self):
        _, px = render(axes=None)
        for x, y in ((350, 240), (300, 190), (330, 270)):
            self.assertEqual(px[x, y], BG)

    def test_axis_endpoint_dot_and_label(self):
        _, px = render(axes=[((300, 240), (400, 240)), None, None])
        self.assertEqual(px[400, 240], (255, 60, 60))          # end dot, r=4
        self.assertEqual(px[400, 240 - AR.AXIS_END_RADIUS], (0, 0, 0))   # its black outline


# ------------------------------------------------------------------------------------------
# 4. info panel: exact rectangle, exact line spacing
# ------------------------------------------------------------------------------------------

class TestPanel(unittest.TestCase):
    def test_panel_constants(self):
        self.assertEqual((AR.PANEL_X, AR.PANEL_Y, AR.PANEL_W, AR.PANEL_H), (6, 6, 175, 240))
        self.assertEqual(AR.PANEL_LINE_H, 11)
        self.assertEqual((AR.PANEL_TEXT_DX, AR.PANEL_TEXT_DY), (5, 4))

    def test_panel_rectangle_is_exactly_where_the_archive_put_it(self):
        _, px = render()
        self.assertEqual(px[6, 6], (0, 0, 0))
        self.assertEqual(px[6 + 175, 6 + 240], (0, 0, 0))
        self.assertEqual(px[5, 6], BG)
        self.assertEqual(px[6, 5], BG)
        self.assertEqual(px[6 + 176, 6 + 240], BG)
        self.assertEqual(px[6, 6 + 241], BG)

    def test_twenty_lines(self):
        self.assertEqual(len(AR.format_panel_lines({})), 20)

    def test_uses_the_font_the_archive_was_drawn_with(self):
        """`gen_trunc_addon.py` passed no font, i.e. Pillow's anti-aliased `load_default()` face.

        Proof, not preference: `test_legend_is_pixel_identical_to_the_archive` below re-renders the
        fixed legend and diffs it against a real archive PNG. The classic 6x11 bitmap face fails
        that diff on 482 px; this one matches exactly.
        """
        self.assertEqual(type(AR.FONT).__name__, "FreeTypeFont")

    def test_panel_text_is_antialiased_like_the_archive(self):
        """The archive panel has NO pure-white pixel: AA glyph cores top out around 240."""
        img, _ = render(metadata=FULL_META)
        panel = np.asarray(img)[AR.PANEL_Y:AR.PANEL_Y + AR.PANEL_H,
                                AR.PANEL_X:AR.PANEL_X + AR.PANEL_W, :]
        self.assertEqual(int(np.all(panel == 255, axis=-1).sum()), 0)
        self.assertGreater(int(panel.max()), 200)

    def test_each_of_the_20_lines_lands_in_its_own_11px_band(self):
        img, _ = render(metadata=FULL_META)
        arr = np.asarray(img)
        panel = arr[AR.PANEL_Y:AR.PANEL_Y + AR.PANEL_H, AR.PANEL_X:AR.PANEL_X + AR.PANEL_W, :]
        ink = panel.min(axis=-1) > 120  # AA text: grey glyph cores, never pure white
        text_rows = set(int(r) for r in np.where(np.any(ink, axis=1))[0])
        self.assertTrue(text_rows)
        for i in range(20):
            band = range(AR.PANEL_TEXT_DY + i * AR.PANEL_LINE_H,
                         AR.PANEL_TEXT_DY + (i + 1) * AR.PANEL_LINE_H)
            self.assertTrue(text_rows & set(band), f"panel line {i} is empty")
        # nothing above the first band, and at most a descender past the 20th: spacing IS 11 px
        # (the archive's AA face is 12 px tall, so 'g'/'y' reach 1 px into the next row).
        self.assertFalse([r for r in text_rows if r < AR.PANEL_TEXT_DY])
        self.assertFalse([r for r in text_rows
                          if r > AR.PANEL_TEXT_DY + 20 * AR.PANEL_LINE_H])

    def test_text_starts_at_panel_x_plus_5(self):
        img, _ = render(metadata=FULL_META)
        arr = np.asarray(img)
        panel = arr[AR.PANEL_Y:AR.PANEL_Y + AR.PANEL_H, AR.PANEL_X:AR.PANEL_X + AR.PANEL_W, :]
        ink = panel.min(axis=-1) > 120  # AA text: grey glyph cores, never pure white
        cols = np.where(np.any(ink, axis=0))[0]
        self.assertEqual(int(cols.min()), AR.PANEL_TEXT_DX)


# ------------------------------------------------------------------------------------------
# 5. legend: exact position and swatch colours
# ------------------------------------------------------------------------------------------

class TestLegend(unittest.TestCase):
    def test_legend_constants(self):
        self.assertEqual((AR.LEGEND_W, AR.LEGEND_H), (90, 60))
        self.assertEqual(AR.LEGEND_MARGIN, 6)

    def test_legend_box_and_swatches(self):
        _, px = render()
        leg_x, leg_y = W - 90 - 6, H - 60 - 6
        self.assertEqual((leg_x, leg_y), (544, 414))
        self.assertEqual(px[leg_x, leg_y], (0, 0, 0))
        self.assertEqual(px[leg_x + 90, leg_y + 60], (0, 0, 0))
        self.assertEqual(px[leg_x - 1, leg_y], BG)
        self.assertEqual(px[leg_x + 10, leg_y + 12], (255, 60, 60))
        self.assertEqual(px[leg_x + 10, leg_y + 27], (60, 220, 60))
        self.assertEqual(px[leg_x + 10, leg_y + 42], (80, 130, 255))

    def test_legend_follows_the_image_size(self):
        _, px = render(keypoints=[], size=(320, 240))
        leg_x, leg_y = 320 - 96, 240 - 66
        self.assertEqual(px[leg_x + 10, leg_y + 12], (255, 60, 60))

    @unittest.skipUnless(ARCHIVE_SAMPLE.exists(), f"archive sample missing: {ARCHIVE_SAMPLE}")
    def test_legend_is_pixel_identical_to_the_archive(self):
        """Golden diff against a real archive PNG: the legend box is fixed content, so it must

        match bit for bit — swatch colours, offsets AND the font. This is the test that caught the
        classic-bitmap-font regression (482 differing px in this 91x61 box).
        """
        ref = np.asarray(Image.open(ARCHIVE_SAMPLE).convert("RGB")).astype(int)
        h, w = ref.shape[:2]
        img, _ = render(keypoints=[], size=(w, h))
        got = np.asarray(img).astype(int)
        lx, ly = w - AR.LEGEND_W - AR.LEGEND_MARGIN, h - AR.LEGEND_H - AR.LEGEND_MARGIN
        box = (slice(ly, ly + AR.LEGEND_H + 1), slice(lx, lx + AR.LEGEND_W + 1))
        diff = np.abs(ref[box] - got[box]).max(axis=-1)
        self.assertEqual(int((diff > 0).sum()), 0)


# ------------------------------------------------------------------------------------------
# 6. canvas size / output
# ------------------------------------------------------------------------------------------

class TestCanvas(unittest.TestCase):
    def test_canvas_is_exactly_the_input_rgb(self):
        for size in ((640, 480), (960, 540), (320, 240)):
            img, _ = render(keypoints=[], size=size)
            self.assertEqual(img.size, size)

    def test_input_image_is_not_mutated(self):
        base = Image.new("RGB", (W, H), BG)
        AR.draw_archive_style_overlay(base, kps_with_z(), None, {})
        self.assertEqual(base.getpixel((6, 6)), BG)

    def test_saves_to_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "f0000.png"
            out.parent.mkdir(parents=True)
            AR.draw_archive_style_overlay(Image.new("RGB", (W, H), BG), kps_with_z(), None, {},
                                          output_path=out)
            with Image.open(out) as im:
                self.assertEqual(im.size, (W, H))


# ------------------------------------------------------------------------------------------
# 7. panel text: falsy values are values, only missing keys are N/A
# ------------------------------------------------------------------------------------------

FULL_META = {
    "frame": 3, "object_name": "Pallet_0", "scenario": "clean-static", "background": "industrial",
    "distance_m": 1.8912, "cam_dist_surface_m": 0.9581839707221871, "cam_height_m": 1.03,
    "elevation_deg": 32.5, "worst_combo": False, "lens_mm": 34.08, "hfov_deg": 55.74,
    "n_in": 4, "n_unocc": 8, "n_both": 4, "area_pct": 12.9,
    "pitch_deg": 90.0, "yaw_deg": 0.0, "roll_deg": -0.0,
    "quaternion_xyzw": [0.71, 0.0, 0.0, 0.71], "size_mm": (1100, 120, 1300),
    "camera_xyz": [-3.7, 1.4, 1.0], "truncated": True, "occluded": False, "cargo_count": 0,
}


class TestPanelText(unittest.TestCase):
    def lines(self, meta):
        return AR.format_panel_lines(meta)

    def test_full_metadata_reproduces_the_archive_lines(self):
        lines = self.lines(FULL_META)
        self.assertEqual(lines[0], "Frame: 000003")
        self.assertEqual(lines[1], "Object: Pallet_0")
        self.assertEqual(lines[2], "Scenario: clean-static")
        self.assertEqual(lines[3], "BG: industrial")
        self.assertEqual(lines[4], "Distance: 1.89m")
        self.assertEqual(lines[5], "Cam dist(surf): 0.9581839707221871m")
        self.assertEqual(lines[6], "Cam height: 1.03m")
        self.assertEqual(lines[7], "Elev: 32.5deg  V:4/8")
        self.assertEqual(lines[8], "Lens: 34mm  HFOV: 55.7°")
        self.assertEqual(lines[9], "Kpt Vis: 50% (4/8)")
        self.assertEqual(lines[10], "Ray Vis: 100% (8/8)")
        self.assertEqual(lines[11], "Combined: 4/8")
        self.assertEqual(lines[12], "Area: 12.9%")
        self.assertEqual(lines[13], "Pitch: +90.0°")
        self.assertEqual(lines[14], "Yaw: +0.0°")
        self.assertEqual(lines[15], "Roll: -0.0°")
        self.assertEqual(lines[16], "Q: [0.71,0.0,0.0,0.71]")
        self.assertEqual(lines[17], "Size: 1100x120x1300mm")
        self.assertEqual(lines[18], "Cam: (-3.7,1.4,1.0)")
        self.assertEqual(lines[19], "Trunc: Y Occ: N Cargo: 0")

    def test_zero_and_false_are_never_na(self):
        meta = dict(FULL_META, elevation_deg=0.0, cargo_count=0, truncated=False, occluded=False,
                    n_in=0, n_unocc=0, n_both=0, area_pct=0.0, distance_m=0.0, hfov_deg=0.0)
        lines = self.lines(meta)
        self.assertEqual(lines[4], "Distance: 0.00m")
        self.assertEqual(lines[7], "Elev: 0.0deg  V:0/8")
        self.assertEqual(lines[9], "Kpt Vis: 0% (0/8)")
        self.assertEqual(lines[12], "Area: 0.0%")
        self.assertEqual(lines[19], "Trunc: N Occ: N Cargo: 0")
        for line in lines:
            self.assertNotIn(AR.MISSING_TEXT, line)
            self.assertNotIn(AR.MISSING_FLAG, line)

    def test_missing_fields_are_na_not_zero(self):
        lines = self.lines({})
        self.assertEqual(lines[0], "Frame: N/A")
        self.assertEqual(lines[4], "Distance: N/A")
        self.assertEqual(lines[7], "Elev: N/Adeg  V:?/8")
        self.assertEqual(lines[9], "Kpt Vis: N/A (?/8)")
        self.assertEqual(lines[12], "Area: N/A")
        self.assertEqual(lines[16], "Q: N/A")
        self.assertEqual(lines[17], "Size: N/A")
        self.assertEqual(lines[18], "Cam: N/A")
        self.assertEqual(lines[19], "Trunc: ? Occ: ? Cargo: ?")
        self.assertNotIn("0", lines[19])

    def test_worst_combo_suffix(self):
        self.assertTrue(self.lines(dict(FULL_META, worst_combo=True))[7].endswith("  WORST"))
        self.assertFalse(self.lines(FULL_META)[7].endswith("  WORST"))

    def test_scenario_is_clipped_to_18_chars(self):
        line = self.lines(dict(FULL_META, scenario="a-very-long-diagnostic-mode-name"))[2]
        self.assertEqual(line, "Scenario: a-very-long-diagno")


# ------------------------------------------------------------------------------------------
# 8. area definition (archive: bbox of the IN-FRAME corners)
# ------------------------------------------------------------------------------------------

class TestAreaPct(unittest.TestCase):
    def test_in_frame_corner_bbox_ratio(self):
        pct = AR.corner_bbox_area_pct(kps_with_z(), W, H)
        # corners span x 220..540, y 80..400 -> 320*320 / (640*480)
        self.assertAlmostEqual(pct, (320 * 320) / (640 * 480) * 100.0, places=6)

    def test_corners_behind_camera_are_excluded(self):
        pts = kps_with_z({k: -1.0 for k in (4, 5, 6, 7)})
        pct = AR.corner_bbox_area_pct(pts, W, H)
        self.assertAlmostEqual(pct, (280 * 280) / (640 * 480) * 100.0, places=6)

    def test_no_in_frame_corner_is_zero(self):
        pts = [(-10.0, -10.0, 2.0)] * 9
        self.assertEqual(AR.corner_bbox_area_pct(pts, W, H), 0.0)


# ------------------------------------------------------------------------------------------
# 9. input normalisation
# ------------------------------------------------------------------------------------------

class TestNormalisation(unittest.TestCase):
    def test_unknown_depth_counts_as_in_front(self):
        pts = AR.normalize_keypoints([(10, 10)])
        self.assertEqual(pts[0][2], 1.0)

    def test_non_finite_is_sanitised_and_clamped(self):
        pts = AR.normalize_keypoints([(float("nan"), float("inf"), 1.0), (1e9, -1e9, 1.0)])
        self.assertEqual(pts[0][0], 0.0)
        self.assertEqual(pts[0][1], AR.DRAW_CLAMP_PX)
        self.assertEqual(pts[1], (AR.DRAW_CLAMP_PX, -AR.DRAW_CLAMP_PX, 1.0))

    def test_normalize_axes_forms(self):
        axes = AR.normalize_axes([((0, 0), (1, 1)), {"ok": True, "start": (2, 2), "end": (3, 3)},
                                  {"ok": False, "start": (4, 4), "end": (5, 5)}])
        self.assertEqual(axes[0], ((0.0, 0.0), (1.0, 1.0)))
        self.assertEqual(axes[1], ((2.0, 2.0), (3.0, 3.0)))
        self.assertIsNone(axes[2])

    def test_normalize_axes_empty(self):
        self.assertEqual(AR.normalize_axes(None), [None, None, None])


# ------------------------------------------------------------------------------------------
# 10. cross-check against gen_trunc_addon.py itself
#
# Everything above pins literals that live in THIS test file, so a wrong copy would only be
# caught if the literal happened to be right. These tests read the constants back out of the
# archive generator's source and compare, so "exact match with the archive" is a real diff.
# ------------------------------------------------------------------------------------------

SRC = (Path(ARCHIVE_SOURCE_PATH).read_text(encoding="utf-8")
       if os.path.exists(ARCHIVE_SOURCE_PATH) else "")


@unittest.skipUnless(SRC, f"archive generator missing: {ARCHIVE_SOURCE_PATH}")
class TestMatchesTheArchiveSource(unittest.TestCase):
    def grab(self, pattern, flags=0):
        m = re.search(pattern, SRC, flags)
        self.assertIsNotNone(m, f"pattern not found in gen_trunc_addon.py: {pattern}")
        return m

    def lit(self, pattern, flags=0):
        return ast.literal_eval(self.grab(pattern, flags).group(1))

    def test_edge_set_is_the_archive_edge_set(self):
        self.assertEqual(AR.EDGES, list(self.lit(r"^EDGES = (\[.*\])$", re.M)))
        self.assertEqual(AR.X_EDGES, self.lit(r"^\s*X_EDGES = (\{.*\})$", re.M))
        self.assertEqual(AR.Y_EDGES, self.lit(r"^\s*Y_EDGES = (\{.*\})$", re.M))
        self.assertEqual(AR.Z_EDGES, self.lit(r"^\s*Z_EDGES = (\{.*\})$", re.M))

    def test_edge_rgb_and_width_are_the_archive_values(self):
        self.assertEqual(AR.COLOR_X_EDGE, self.lit(r"if e in X_EDGES: color = (\([^)]*\))"))
        self.assertEqual(AR.COLOR_Y_EDGE, self.lit(r"elif e in Y_EDGES: color = (\([^)]*\))"))
        self.assertEqual(AR.COLOR_Z_EDGE, self.lit(r"elif e in Z_EDGES: color = (\([^)]*\))"))
        self.assertEqual(AR.COLOR_OTHER_EDGE, self.lit(r"else: color = (\([^)]*\))"))
        self.assertEqual(AR.EDGE_WIDTH, self.lit(
            r"drw\.line\(\[pts2d\[a\], pts2d\[b\]\], fill=color, width=(\d+)\)"))

    def test_keypoint_colors_radii_and_grey_are_the_archive_values(self):
        self.assertEqual(AR.KP_COLORS, self.lit(r"KP_COLORS = (\{.*?\n    \})", re.S))
        self.assertEqual(AR.COLOR_KP_OFFSCREEN, self.lit(r"col = (\(130, 130, 130\))"))
        m = self.grab(r"r = (\d+) if idx == 8 else (\d+)")
        self.assertEqual((AR.KP_RADIUS_CENTROID, AR.KP_RADIUS), (int(m.group(1)), int(m.group(2))))
        # the archive greys a dot only when it leaves the frame OR sits behind the camera,
        # and its border test is INCLUSIVE (`<= W`, `<= H`) - see the f0004 centroid finding
        self.grab(r"if not \(0 <= x <= W and 0 <= y <= H and z > 0\):")

    def test_pose_axis_constants_are_the_archive_values(self):
        self.assertEqual(AR.AXIS_LEN_M, self.lit(r"AXIS_LEN_M = ([\d.]+)"))
        self.assertEqual(
            AR.AXIS_COLORS,
            tuple(c for _, c in self.lit(r"for axis_idx, color in (\[.*?\]):", re.S)))
        self.assertEqual(list(AR.AXIS_LABELS), self.lit(r'label = (\["X", "Y", "Z"\])'))
        self.assertEqual(AR.AXIS_WIDTH, self.lit(
            r"drw\.line\(\[\(c_proj\[0\], c_proj\[1\]\), \(e_proj\[0\], e_proj\[1\]\)\], "
            r"fill=color, width=(\d+)\)"))
        self.assertEqual(AR.AXIS_END_RADIUS, self.lit(r"drw\.ellipse\(\[e_proj\[0\]-(\d+),"))

    def test_panel_rectangle_and_line_spacing_are_the_archive_values(self):
        self.assertEqual((AR.PANEL_X, AR.PANEL_Y, AR.PANEL_W, AR.PANEL_H),
                         self.lit(r"panel_x, panel_y, panel_w, panel_h = ([\d, ]+)\n"))
        self.assertEqual(AR.PANEL_BG, self.lit(
            r"drw\.rectangle\(\[panel_x, panel_y, panel_x \+ panel_w, panel_y \+ panel_h\], "
            r"fill=(\([\d, ]+\))\)"))
        m = self.grab(r"drw\.text\(\(panel_x \+ (\d+), panel_y \+ (\d+) \+ i \* (\d+)\), line, "
                      r"fill=(\([\d, ]+\))\)")
        self.assertEqual((AR.PANEL_TEXT_DX, AR.PANEL_TEXT_DY, AR.PANEL_LINE_H),
                         (int(m.group(1)), int(m.group(2)), int(m.group(3))))
        self.assertEqual(AR.PANEL_TEXT, ast.literal_eval(m.group(4)))

    def test_panel_lines_keep_the_archive_labels_and_order(self):
        block = self.grab(r"info_lines = \[(.*?)\n    \]", re.S).group(1)
        src_labels = re.findall(r'^\s+f"([A-Za-z][^:"]*):', block, re.M)
        # the archive builds line 20 from three adjacent f-strings
        self.assertEqual(src_labels[19:], ["Trunc", "Occ", "Cargo"])
        got = [line.split(":")[0] for line in AR.format_panel_lines({})]
        self.assertEqual(got, src_labels[:19] + ["Trunc"])
        self.assertIn(" Occ: ", AR.format_panel_lines({})[19])
        self.assertIn(" Cargo: ", AR.format_panel_lines({})[19])

    def test_legend_geometry_and_swatches_are_the_archive_values(self):
        self.assertEqual((AR.LEGEND_W, AR.LEGEND_H), self.lit(r"leg_w, leg_h = ([\d, ]+)\n"))
        m = self.grab(r"leg_x, leg_y = W - leg_w - (\d+), H - leg_h - (\d+)")
        self.assertEqual((AR.LEGEND_MARGIN, AR.LEGEND_MARGIN),
                         (int(m.group(1)), int(m.group(2))))
        swatches = re.findall(
            r"drw\.rectangle\(\[leg_x \+ \d+, leg_y \+ (\d+), leg_x \+ \d+, leg_y \+ \d+\], "
            r"fill=(\([\d, ]+\))\)", SRC)
        self.assertEqual([int(dy) for dy, _ in swatches], [7, 22, 37])
        self.assertEqual(tuple(ast.literal_eval(c) for _, c in swatches), AR.AXIS_COLORS)

    def test_area_pct_uses_the_archive_in_frame_definition(self):
        self.grab(r"in_pts = \[\(p\[0\], p\[1\]\) for p in kps_2d\[:8\] "
                  r"if 0 <= p\[0\] <= W and 0 <= p\[1\] <= H and p\[2\] > 0\]")
        self.grab(r"area_pct = \(\(max\(x_coords\) - min\(x_coords\)\) \* "
                  r"\(max\(y_coords\) - min\(y_coords\)\)\) / \(W \* H\) \* 100\.0")

    def test_archive_draws_no_external_panel_or_header(self):
        """The canonical overlay writes onto the RGB frame: no new canvas, no paste, no concat."""
        block = SRC[SRC.index("# === Detailed Overlay ==="):SRC.index('img.save(os.path.join(overlay_dir')]
        for forbidden in ("Image.new", ".paste(", "np.concatenate", "np.hstack", "np.vstack"):
            self.assertNotIn(forbidden, block, f"archive block does not {forbidden}")
        self.assertIn("img = _tmp.convert(\"RGB\")", block)


if __name__ == "__main__":
    unittest.main()
