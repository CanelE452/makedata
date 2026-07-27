"""Phase 6 tests for overlay_v2_detailed.py (bpy-free).

Three things must not regress:
  1. absent vs null vs present-but-falsy (0 / 0.0 / False) never collapse into one "N/A"
  2. the colour contract (FRONT red / REAR blue / connector yellow / pose axes X,Y,Z)
  3. the panel layout: every row lands on its own line inside its column, clipped to the column
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


MODULE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "overlay_v2_detailed.py")
)


def _load_module():
    spec = importlib.util.spec_from_file_location("overlay_v2_detailed", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("overlay_v2_detailed", module)
    spec.loader.exec_module(module)
    return module


OV = _load_module()

# Front square and a rear square offset diagonally, so no front/rear/connector edge is collinear
# with another one and a single pixel identifies exactly one edge class.
UV8 = [[20, 20], [80, 20], [80, 80], [20, 80],
       [40, 40], [100, 40], [100, 100], [40, 100]]
CUBOID_3D = [[-0.5, -0.5, 0.1], [0.5, -0.5, 0.1], [0.5, -0.5, 0.0], [-0.5, -0.5, 0.0],
             [-0.5, 0.5, 0.1], [0.5, 0.5, 0.1], [0.5, 0.5, 0.0], [-0.5, 0.5, 0.0]]


def make_label(width=200, height=160, cam=(0.0, -3.0, 1.0), pose_t=(0.0, 0.0, 2.0),
               extra_obj=None):
    obj = {
        "class": "pallet",
        "keypoint_convention": "camera_dynamic_0123_v4",
        "location": list(pose_t),
        "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
        "euler_angles": {"pitch": 1.0, "yaw": -2.0, "roll": 3.0},
        "pose_transform": [[1.0, 0.0, 0.0, pose_t[0]], [0.0, 1.0, 0.0, pose_t[1]],
                           [0.0, 0.0, 1.0, pose_t[2]], [0.0, 0.0, 0.0, 1.0]],
        "cuboid": CUBOID_3D,
        "projected_cuboid": UV8,
        "projected_cuboid_centroid": [60.0, 60.0],
        "dimensions_m": {"width": 1.1, "height": 0.15, "depth": 1.1},
        "scene_placement_v2": {"diagnostic_mode": "clean-static", "support_ground_z": 0.0},
        "safety_gates": {"G1_Vvis>=4": True, "G2_extocc_1to4": True, "G3_visible>=0.5unocc": True,
                         "G4_center_inframe": True, "G5_luma_floor": False, "all_pass": False},
        "v2_labels": {"pallet_type": "Pallet_0", "V_vis_actual": 8, "V_actual": 8},
    }
    if extra_obj:
        obj.update(extra_obj)
    return {
        "camera_data": {
            "width": width, "height": height,
            "intrinsics": {"fx": 100.0, "fy": 100.0, "cx": 100.0, "cy": 80.0},
            "location_worldframe": list(cam), "look_worldframe": [0.0, 0.0, 0.05],
            "lens_mm": 30.0, "scene_preset": "fixture", "background_asset": "industrial",
            "floor_mode": "plane", "exposure_ev": -1.5,
        },
        "objects": [obj],
    }


def make_ctx(rec=None, audit=None, pnp=None, masks=None, lab=None):
    lab = lab or make_label()
    obj = lab["objects"][0]
    return OV.build_context(Path("."), 0, lab, obj, obj.get("v2_labels"), rec, audit, pnp,
                            masks or {})


def rows_by_label(rows):
    return {r.label: r for r in rows if r.kind == "field"}


# ------------------------------------------------------------------------------------------
# 1. absent / null / falsy-present
# ------------------------------------------------------------------------------------------

class TestValueModel(unittest.TestCase):
    def test_pick_absent(self):
        val = OV.pick([("rec", {})], "camera_distance_actual_m")
        self.assertFalse(val.present)
        self.assertEqual(OV.render_value(val)[0], OV.MISSING_TEXT)

    def test_pick_null_is_not_absent(self):
        val = OV.pick([("rec", {"camera_distance_actual_m": None})], "camera_distance_actual_m")
        self.assertTrue(val.present)
        self.assertFalse(val.known)
        self.assertEqual(OV.render_value(val)[0], OV.NULL_TEXT)

    def test_zero_is_present_not_na(self):
        for zero in (0, 0.0, -0.0):
            val = OV.pick([("rec", {"camera_distance_actual_m": zero})], "camera_distance_actual_m")
            self.assertTrue(val.present)
            self.assertTrue(val.known)
            txt, color = OV.render_value(val, OV.num(3, " m"))
            self.assertEqual(txt, "0.000 m")
            self.assertNotEqual(color, OV.TEXT_NA)

    def test_false_is_present_not_na(self):
        val = OV.pick([("rec", {"ground_continuity_pass": False})], "ground_continuity_pass")
        txt, color = OV.status_value(val)
        self.assertEqual(txt, "FAIL")
        self.assertEqual(color, OV.TEXT_FAIL)

    def test_empty_string_becomes_null(self):
        val = OV.pick([("audit", {"failures": ""})], "failures")
        self.assertTrue(val.present)
        self.assertIsNone(val.value)

    def test_first_source_wins_even_when_zero(self):
        val = OV.pick([("rec", {"f_total": 0.0}), ("v2", {"f_total": 0.9})], "f_total")
        self.assertEqual(val.value, 0.0)
        self.assertEqual(val.source, "rec")

    def test_status_absent_is_gray(self):
        txt, color = OV.status_value(OV.pick([("rec", {})], "x"))
        self.assertEqual(txt, OV.MISSING_TEXT)
        self.assertEqual(color, OV.TEXT_NA)

    def test_pair_val_absent_only_when_both_missing(self):
        self.assertFalse(OV.pair_val([("rec", {})], ["a"], ["b"]).present)
        val = OV.pair_val([("rec", {"a": 0.0})], ["a"], ["b"])
        self.assertTrue(val.present)
        self.assertEqual(val.value, "0.000 / -")

    def test_pair_val_keeps_zeros(self):
        val = OV.pair_val([("rec", {"f_static": 0.0, "f_cargo": 0.0})], ["f_static"], ["f_cargo"])
        self.assertEqual(val.value, "0.000 / 0.000")
        self.assertEqual(OV.render_value(val)[1], OV.TEXT)

    def test_csv_coercion(self):
        self.assertIsNone(OV._coerce_csv(""))
        self.assertIs(OV._coerce_csv("True"), True)
        self.assertIs(OV._coerce_csv("False"), False)
        self.assertEqual(OV._coerce_csv("0"), 0)
        self.assertEqual(OV._coerce_csv("0.0"), 0.0)
        self.assertEqual(OV._coerce_csv("clean-static"), "clean-static")


# ------------------------------------------------------------------------------------------
# 2. sections: which rows exist and how legacy gaps are reported
# ------------------------------------------------------------------------------------------

class TestSections(unittest.TestCase):
    def test_legacy_record_marks_phase_fields_absent(self):
        rows = rows_by_label(OV.build_sections(make_ctx(rec={"rendered": True})))
        for label in ("dist actual (rec)", "dist limit (rec)", "ground contin.", "noise tier",
                      "gaussian sigma", "luma final f/p", "proj size floor"):
            self.assertTrue(rows[label].is_absent, f"{label} should read as field-absent")
            self.assertEqual(rows[label].text, OV.MISSING_TEXT)

    def test_phase_fields_render_when_present(self):
        rec = {
            "rendered": True, "camera_distance_actual_m": 4.5, "camera_distance_limit_m": 10.0,
            "camera_distance_target_m": 4.4, "ground_continuity_pass": True,
            "ground_probe_count": 12, "ground_probe_fail_count": 0,
            "ground_probe_max_step_m": 0.0, "procedural_floor_edge_risk": False,
            "noise_tier": 2, "gaussian_sigma": 3.5, "luma_frame_final": 40.0,
            "luma_pallet_final": 22.0, "projected_size_feasible_lower": 0.08,
        }
        rows = rows_by_label(OV.build_sections(make_ctx(rec=rec)))
        self.assertEqual(rows["dist actual (rec)"].text, "4.500 m")
        self.assertEqual(rows["ground contin."].text, "PASS")
        self.assertEqual(rows["ground fails"].text, "0")          # falsy int stays a number
        self.assertEqual(rows["ground step"].text, "0.000 m")     # falsy float stays a number
        self.assertEqual(rows["floor edge risk"].text, "ok")
        self.assertEqual(rows["noise tier"].text, "2")
        self.assertEqual(rows["gaussian sigma"].text, "3.500")
        self.assertEqual(rows["luma final f/p"].text, "40.00 / 22.00")

    def test_noise_tier_zero_is_shown(self):
        rows = rows_by_label(OV.build_sections(make_ctx(rec={"noise_tier": 0})))
        self.assertEqual(rows["noise tier"].text, "0")
        self.assertFalse(rows["noise tier"].is_na)

    def test_pnp_eligibility_rows(self):
        pnp = {"bbox_vis_min_side_px": 41.0, "pnp_eligible_candidate_2cell": True,
               "pnp_eligible_candidate_3cell": True, "pnp_eligible_candidate_4cell": False,
               "tiny_warning": False, "pnp_stress": True}
        rows = rows_by_label(OV.build_sections(make_ctx(pnp=pnp)))
        self.assertEqual(rows["elig 2cell(16px)"].text, "YES")
        self.assertEqual(rows["elig 4cell(32px)"].text, "NO")
        self.assertEqual(rows["elig 4cell(32px)"].color, OV.TEXT_FAIL)
        self.assertEqual(rows["tiny_warning"].text, "no")
        self.assertEqual(rows["tiny_warning"].color, OV.TEXT_PASS)   # inverted: False is good
        self.assertEqual(rows["pnp_stress"].text, "STRESS")
        self.assertEqual(rows["pnp_stress"].color, OV.TEXT_FAIL)

    def test_pnp_csv_distance_is_not_reported_as_recorded(self):
        """camera_distance_used_m from the Phase 4 CSV is label-recomputed, not a Phase 1 record."""
        rows = rows_by_label(OV.build_sections(make_ctx(pnp={"camera_distance_used_m": 3.3})))
        self.assertTrue(rows["dist actual (rec)"].is_absent)

    def test_failures_empty_cell_reads_as_none(self):
        rows = rows_by_label(OV.build_sections(make_ctx(audit={"audit_pass": True, "failures": None})))
        self.assertEqual(rows["failures"].text, "none")
        self.assertEqual(rows["failures"].color, OV.TEXT_PASS)

    def test_mask_inclusion_from_audit_csv(self):
        audit = {"mask_pixel_inclusion_ok": False, "mask_pixel_inclusion_violation_px": 17,
                 "mask_m0_hull_bbox_iou": 0.9, "mask_m4_hull_bbox_iou": 0.4}
        rows = rows_by_label(OV.build_sections(make_ctx(audit=audit)))
        self.assertEqual(rows["mask incl."].text, "FAIL")
        self.assertEqual(rows["mask incl."].color, OV.TEXT_FAIL)
        self.assertEqual(rows["mask incl. px"].text, "17 px")
        self.assertEqual(rows["hull IoU M0/M4"].text, "0.900 / 0.400")

    def test_derived_camera_geometry(self):
        rows = rows_by_label(OV.build_sections(make_ctx(rec={"rendered": True})))
        # camera at (0,-3,1), cuboid centroid at (0,0,0.05) -> sqrt(9 + 0.9025) = 3.147 m
        self.assertEqual(rows["dist centroid"].text, "3.147 m")
        self.assertEqual(rows["resolution"].text, "200x160")
        self.assertEqual(rows["HFOV"].text, "90.00 deg")     # fx=100, W=200
        self.assertEqual(rows["cam height"].text, "1.000 m")  # support_ground_z = 0.0

    def test_dimensions_and_pose_rows(self):
        rows = rows_by_label(OV.build_sections(make_ctx()))
        self.assertEqual(rows["dims WxDxH"].text, "1100x1100x150 mm")
        self.assertEqual(rows["quat xyzw"].text, "[0.00, 0.00, 0.00, 1.00]")
        self.assertEqual(rows["pitch"].text, "1.00 deg")
        self.assertEqual(rows["centroid uv"].text, "(60.0, 60.0)")

    def test_gate_line_flags_failure(self):
        rows = OV.build_sections(make_ctx())
        gate = [r for r in rows if r.label.startswith("G1..G5")][0]
        self.assertIn("G5:N", gate.text)
        self.assertEqual(gate.color, OV.TEXT_FAIL)


# ------------------------------------------------------------------------------------------
# 3. distance-cap violation row (Phase 1)
# ------------------------------------------------------------------------------------------

class TestDistanceViolation(unittest.TestCase):
    def row(self, rec, geom_dist=None):
        geom = {"camera_distance_m": geom_dist} if geom_dist is not None else {}
        return OV._distance_violation_row(
            OV.pick([("rec", rec)], "camera_distance_actual_m"),
            OV.pick([("rec", rec)], "camera_distance_limit_m"), geom)

    def test_violation(self):
        row = self.row({"camera_distance_actual_m": 12.0, "camera_distance_limit_m": 10.0})
        self.assertIn("VIOLATION", row.text)
        self.assertEqual(row.color, OV.TEXT_FAIL)

    def test_zero_distance_is_ok_not_na(self):
        row = self.row({"camera_distance_actual_m": 0.0, "camera_distance_limit_m": 10.0})
        self.assertTrue(row.text.startswith("ok"))
        self.assertEqual(row.color, OV.TEXT_PASS)

    def test_legacy_falls_back_to_label_distance_and_says_so(self):
        row = self.row({}, geom_dist=1015.6)
        self.assertIn("VIOLATION", row.text)
        self.assertIn("derived", row.text)
        self.assertIn("fb", row.text)

    def test_no_distance_at_all_is_absent(self):
        self.assertEqual(self.row({}).text, OV.MISSING_TEXT)


# ------------------------------------------------------------------------------------------
# 4. geometry / pose axes / contours
# ------------------------------------------------------------------------------------------

class TestGeometry(unittest.TestCase):
    def test_frame_geometry_distance_and_reprojection(self):
        lab = make_label()
        geom = OV.frame_geometry(lab, lab["objects"][0])
        self.assertAlmostEqual(geom["camera_distance_m"], float(np.linalg.norm(
            np.array([0.0, 0.0, 0.05]) - np.array([0.0, -3.0, 1.0]))), places=6)
        self.assertLess(geom["nearest_corner_distance_m"], geom["camera_distance_m"])
        self.assertEqual(geom["uv8"].shape, (8, 2))

    def test_pose_axes_projection(self):
        lab = make_label()
        geom = OV.frame_geometry(lab, lab["objects"][0])
        axes = OV.pose_axis_endpoints(geom, length=0.5)
        self.assertEqual(len(axes), 3)
        self.assertTrue(all(a["ok"] for a in axes))
        self.assertEqual([a["label"] for a in axes], ["X", "Y", "Z"])
        self.assertEqual([a["color"] for a in axes], list(OV.AXIS_COLORS))
        np.testing.assert_allclose(axes[0]["start"], (100.0, 80.0), atol=1e-6)
        np.testing.assert_allclose(axes[0]["end"], (125.0, 80.0), atol=1e-6)   # +0.5 m in X at z=2
        np.testing.assert_allclose(axes[1]["end"], (100.0, 105.0), atol=1e-6)  # +0.5 m in Y

    def test_pose_axes_behind_camera_not_drawn(self):
        lab = make_label(pose_t=(0.0, 0.0, -2.0))
        geom = OV.frame_geometry(lab, lab["objects"][0])
        axes = OV.pose_axis_endpoints(geom)
        self.assertTrue(all(not a["ok"] for a in axes))

    def test_mask_boundary_is_the_perimeter(self):
        fg = np.zeros((20, 20), dtype=bool)
        fg[5:15, 5:15] = True
        edge = OV.mask_boundary(fg)
        self.assertEqual(int(edge.sum()), 10 * 10 - 8 * 8)
        self.assertTrue(edge[5, 5])
        self.assertFalse(edge[9, 9])

    def test_mask_boundary_thickness(self):
        fg = np.zeros((20, 20), dtype=bool)
        fg[5:15, 5:15] = True
        thin = OV.mask_boundary(fg, thickness=1)
        thick = OV.mask_boundary(fg, thickness=3)
        self.assertGreater(int(thick.sum()), int(thin.sum()))

    def test_mask_boundary_none(self):
        self.assertIsNone(OV.mask_boundary(None))

    def test_hfov(self):
        self.assertAlmostEqual(OV.hfov_deg_from_fx(100.0, 200.0), 90.0, places=6)
        self.assertIsNone(OV.hfov_deg_from_fx(None, 200.0))

    def test_in_image_count(self):
        uv = np.array([[10.0, 10.0], [-5.0, 10.0], [10.0, 500.0]])
        self.assertEqual(OV.in_image_count(uv, 200, 160), 1)


# ------------------------------------------------------------------------------------------
# 5. drawing: colour contract and layout
# ------------------------------------------------------------------------------------------

class TestDrawing(unittest.TestCase):
    def test_edge_colors(self):
        base = Image.new("RGB", (200, 160), (0, 0, 0))
        ctx = make_ctx()
        OV.draw_scene_layer(base, ctx)
        px = base.load()
        self.assertEqual(px[50, 20], OV.COLOR_FRONT)   # front edge 0-1
        self.assertEqual(px[70, 40], OV.COLOR_REAR)    # rear edge 4-5
        self.assertEqual(px[30, 30], OV.COLOR_CONN)    # connector 0-4
        self.assertEqual(px[60, 60], OV.COLOR_CENTROID)

    def test_offscreen_keypoint_is_gray(self):
        lab = make_label()
        lab["objects"][0]["projected_cuboid"] = [[-50, -50]] + UV8[1:]
        base = Image.new("RGB", (200, 160), (0, 0, 0))
        ctx = make_ctx(lab=lab)
        stats = OV.draw_scene_layer(base, ctx)
        self.assertTrue(stats["cuboid_drawn"])
        # corner 0 is off-image: nothing of its marker colour may appear inside the frame
        arr = np.asarray(base)
        self.assertFalse(np.any(np.all(arr == np.array(OV.COLOR_OFFSCREEN_KP), axis=-1)[:, 60:]))

    def test_contours_are_painted(self):
        fg0 = np.zeros((160, 200), dtype=bool)
        fg0[40:100, 40:120] = True
        fg4 = np.zeros((160, 200), dtype=bool)
        fg4[40:100, 40:80] = True
        ctx = make_ctx(masks={"m0": {"fg": fg0, "area": int(fg0.sum())},
                              "m4": {"fg": fg4, "area": int(fg4.sum())}})
        base = Image.new("RGB", (200, 160), (0, 0, 0))
        stats = OV.draw_scene_layer(base, ctx)
        self.assertGreater(stats["contour_m0_px"], 0)
        self.assertGreater(stats["contour_m4_px"], 0)
        arr = np.asarray(base)
        self.assertTrue(np.any(np.all(arr == np.array(OV.COLOR_M0_CONTOUR), axis=-1)))
        self.assertTrue(np.any(np.all(arr == np.array(OV.COLOR_M4_CONTOUR), axis=-1)))

    def test_contour_shape_mismatch_is_skipped(self):
        ctx = make_ctx(masks={"m0": {"fg": np.ones((10, 10), dtype=bool)}})
        base = Image.new("RGB", (200, 160), (0, 0, 0))
        stats = OV.draw_scene_layer(base, ctx)
        self.assertEqual(stats["contour_m0_px"], 0)

    def test_layout_rows_are_unique_and_ordered(self):
        rows = OV.build_sections(make_ctx())
        placed = OV.layout_rows(rows, 30)
        seen = set()
        for item in placed:
            key = (item["col"], item["line"])
            self.assertNotIn(key, seen, "two rows share one panel line")
            seen.add(key)
            self.assertLess(item["line"], 30)
        self.assertEqual(len(placed), len(rows))

    def test_layout_never_orphans_a_section_header(self):
        rows = OV.build_sections(make_ctx())
        placed = OV.layout_rows(rows, 24)
        for i, item in enumerate(placed[:-1]):
            if item["row"].kind == "section":
                self.assertEqual(placed[i + 1]["col"], item["col"],
                                 "section header left alone at the end of a column")

    def test_fit_text_clips_long_values(self):
        dr = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        long = "ok [derived, limit 10m fb] " * 4
        clipped = OV.fit_text(dr, long, 120)
        self.assertTrue(clipped.endswith("~"))
        self.assertLessEqual(dr.textlength(clipped, font=OV.SMALL_FONT), 120 + 6)
        self.assertEqual(OV.fit_text(dr, "ok", 120), "ok")

    def test_render_overlay_composition(self):
        base = Image.new("RGB", (200, 160), (10, 10, 10))
        ctx = make_ctx(rec={"rendered": True})
        canvas, stats = OV.render_overlay(base, ctx)
        self.assertEqual(canvas.width, 200 + OV.PANEL_COL_W * OV.PANEL_COLS)
        self.assertGreaterEqual(canvas.height, 160)
        self.assertTrue(stats["rgb_present"])
        self.assertEqual(stats["axes_drawn"], 3)
        self.assertIn("dist actual (rec)", stats["na_absent"])
        # the RGB half must still be the image, not panel background
        self.assertNotEqual(canvas.getpixel((5, 100)), OV.PANEL_BG)

    def test_render_overlay_without_rgb(self):
        ctx = make_ctx()
        canvas, stats = OV.render_overlay(None, ctx)
        self.assertFalse(stats["rgb_present"])
        self.assertGreater(canvas.width, OV.PANEL_COL_W)


# ------------------------------------------------------------------------------------------
# 6. dataset runner (end to end)
# ------------------------------------------------------------------------------------------

def write_fixture(root: Path, n=3, phase_fields=False, mask_violation=False):
    (root / "rgb").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "mask").mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(n):
        Image.new("RGB", (200, 160), (30, 40, 50)).save(root / "rgb" / f"f{i:04d}_rgb.png")
        (root / "labels" / f"f{i:04d}_label.json").write_text(json.dumps(make_label()),
                                                              encoding="utf-8")
        for j, name in enumerate(["m0", "m1", "m2", "m3", "m4"]):
            arr = np.zeros((160, 200), dtype=np.uint8)
            if mask_violation and name == "m4":
                arr[10:30, 150:190] = 255           # outside M0 -> inclusion violation
            else:
                arr[40:100 - j, 40:120 - j] = 255
            Image.fromarray(arr).save(root / "mask" / f"f{i:04d}_{name}.png")
        rec = {"idx": i, "rendered": True, "diagnostic_mode": "clean-static",
               "pallet_type": "Pallet_0", "f_static": 0.0, "f_total": 0.0,
               "all_pass": True, "G1_pass": True, "G2_pass": True, "G3_pass": True,
               "G4_pass": True, "G5_pass": True}
        if phase_fields:
            rec.update({"camera_distance_actual_m": 3.2, "camera_distance_limit_m": 10.0,
                        "ground_continuity_pass": True, "noise_tier": 1, "gaussian_sigma": 2.0,
                        "luma_frame_final": 41.0, "luma_pallet_final": 20.0})
        records.append(rec)
    with (root / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


class TestRunner(unittest.TestCase):
    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            write_fixture(root, n=3)
            out = root / "eda_phase6"
            proc = subprocess.run(
                [sys.executable, MODULE_PATH, "--dir", str(root), "--out", str(out),
                 "--sheet-frames", "2"],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            pngs = sorted((out / OV.OVERLAY_DIRNAME).glob("*.png"))
            self.assertEqual(len(pngs), 3)
            sheets = sorted((out / "contact_sheets").glob("detailed_*.png"))
            self.assertEqual(len(sheets), 2)
            manifest = json.loads((out / "overlay_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["frames"], 3)
            self.assertEqual(manifest["na_field_absent_counts"]["noise tier"], 3)
            self.assertEqual(manifest["na_field_absent_counts"]["ground contin."], 3)
            self.assertEqual(manifest["per_frame"][0]["axes_drawn"], 3)
            self.assertGreater(manifest["per_frame"][0]["contour_m0_px"], 0)
            with Image.open(pngs[0]) as im:
                self.assertEqual(im.width, 200 + OV.PANEL_COL_W * OV.PANEL_COLS)

    def test_cli_reports_phase_fields_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            write_fixture(root, n=2, phase_fields=True)
            out = root / "eda_phase6"
            proc = subprocess.run([sys.executable, MODULE_PATH, "--dir", str(root),
                                   "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            manifest = json.loads((out / "overlay_manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("noise tier", manifest["na_field_absent_counts"])
            self.assertNotIn("ground contin.", manifest["na_field_absent_counts"])
            self.assertNotIn("luma final f/p", manifest["na_field_absent_counts"])

    def test_mask_inclusion_fallback_without_audit_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            write_fixture(root, n=1, mask_violation=True)
            masks = {n: OV.load_mask_foreground(root, 0, n)
                     for n in ["m0", "m1", "m2", "m3", "m4"]}
            lab, obj, v2 = OV.AUDIT.load_label(root, 0)
            geom = OV.frame_geometry(lab, obj)
            computed = OV.compute_mask_fallback(masks, ["m0", "m1", "m2", "m3", "m4"], geom)
            self.assertIs(computed["mask_pixel_inclusion_ok"], False)
            self.assertGreater(computed["mask_pixel_inclusion_violation_px"], 0)
            rows = rows_by_label(OV.build_sections(
                OV.build_context(root, 0, lab, obj, v2, None, None, None, masks, computed, geom)))
            self.assertEqual(rows["mask incl."].text, "FAIL")

    def test_guard_refuses_existing_audit_overlay_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            (root / "eda").mkdir(parents=True)
            with self.assertRaises(SystemExit):
                OV.guard_output_dir(root, root / "eda" / "overlay_all")

    def test_guard_allows_phase6_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ds"
            root.mkdir(parents=True)
            OV.guard_output_dir(root, root / "eda_phase6")   # must not raise


if __name__ == "__main__":
    unittest.main()
