"""Blender-side regression for the Phase-2 ground-continuity audit.

Builds a minimal scene (finite procedural floor quad + pallet-sized cuboid + camera) and
checks that `scene_visibility_v2.check_ground_continuity` raycasts report what the audit
contract promises: 11 probes from the camera ground-projection to the pallet centroid, a
support hit under each, a bounded height step between neighbours, and an edge flag whenever a
probe leaves the finite plane.

Also measures, over a 24-configuration camera sweep bounded by the Phase-1 10 m distance cap,
how much floor half-extent is actually consumed — the evidence for keeping or growing
FLOOR_PLANE_SIZE.

Run:
    blender -b --factory-startup --python <this file>
"""

import math
import os
import sys

import bpy


SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import blender_config as cfg
import scene_placement_v2 as sp2
import scene_visibility_v2 as sv2


PALLET_W = 1.1
PALLET_H = 0.15
FLOOR_Z = float(cfg.FLOOR_PLANE_Z)
CENTROID = (0.0, 0.0, PALLET_H / 2.0)


def cuboid(name, size_xyz, location):
    sx, sy, sz = (float(value) / 2.0 for value in size_xyz)
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [
            (-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
            (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz),
        ],
        [],
        [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def plane(name, size, location):
    h = float(size) / 2.0
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def camera_at(distance_m, elevation_deg, azimuth_deg):
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    return (
        CENTROID[0] + distance_m * math.cos(elevation) * math.cos(azimuth),
        CENTROID[1] + distance_m * math.cos(elevation) * math.sin(azimuth),
        CENTROID[2] + distance_m * math.sin(elevation),
    )


bpy.ops.wm.read_factory_settings(use_empty=True)

floor = plane(cfg.FLOOR_PLANE_NAME, cfg.FLOOR_PLANE_SIZE, (0.0, 0.0, FLOOR_Z))
pallet = cuboid("Pallet", (PALLET_W, PALLET_W, PALLET_H), (0.0, 0.0, PALLET_H / 2.0))
bpy.context.view_layer.update()

assert cfg.FLOOR_PLANE_SIZE == 50.0, cfg.FLOOR_PLANE_SIZE
assert sp2.GROUND_PROBE_COUNT == 11, sp2.GROUND_PROBE_COUNT


def audit(cam_pos, *, target=(0.0, 0.0), support=None, hide=None, plane_size=None,
          plane_center=None):
    return sv2.check_ground_continuity(
        cam_pos,
        target,
        [floor] if support is None else support,
        floor_object=floor,
        plane_size=cfg.FLOOR_PLANE_SIZE if plane_size is None else plane_size,
        plane_center_xy=(0.0, 0.0) if plane_center is None else plane_center,
        hide_objects=[pallet] if hide is None else hide,
    )


# --- 1. 24-configuration sweep inside the Phase-1 10 m cap ---------------------------------
sweep_margins = []
sweep_steps = []
sweep_count = 0
for distance in (1.5, 3.0, 6.0, 10.0):
    for elevation in (12.0, 35.0, 60.0):
        for azimuth in (0.0, 135.0):
            cam = camera_at(distance, elevation, azimuth)
            report = audit(cam)
            sweep_count += 1
            assert report["ground_continuity_pass"] is True, (distance, elevation, azimuth, report)
            assert report["ground_probe_count"] == 11, report
            assert report["ground_probe_fail_count"] == 0, report
            assert report["procedural_floor_edge_risk"] is False, report
            assert report["ground_continuity_reason"] is None, report
            kinds = [row["kind"] for row in report["ground_probe_hit_objects"]]
            assert kinds == ["floor"] * 11, (distance, elevation, azimuth, kinds)
            for row in report["ground_probe_hit_objects"]:
                assert abs(row["support_z"] - FLOOR_Z) < 1e-4, row
            expected_margin = 25.0 - max(abs(cam[0]), abs(cam[1]))
            assert abs(report["procedural_floor_edge_margin_m"] - expected_margin) < 1e-3, (
                report["procedural_floor_edge_margin_m"], expected_margin
            )
            sweep_margins.append(report["procedural_floor_edge_margin_m"])
            sweep_steps.append(report["ground_probe_max_step_m"])

assert sweep_count == 24, sweep_count
min_margin = min(sweep_margins)
assert min_margin >= 15.0, min_margin

# --- 2. the pallet must be hidden, otherwise the last probe reads the pallet ---------------
cam_default = camera_at(6.0, 25.0, 20.0)
unhidden = audit(cam_default, hide=[])
assert unhidden["ground_continuity_pass"] is False, unhidden
assert unhidden["ground_probe_hit_objects"][-1]["kind"] == "other", unhidden
assert unhidden["ground_probe_hit_objects"][-1]["hit_object"] == "Pallet", unhidden

# --- 3. a non-support obstacle on the ground segment is a probe failure unless hidden ------
crate = cuboid("Crate", (0.8, 0.8, 0.8), (cam_default[0] * 0.5, cam_default[1] * 0.5, 0.4))
bpy.context.view_layer.update()
blocked = audit(cam_default)
assert blocked["ground_continuity_pass"] is False, blocked
assert blocked["ground_probe_fail_count"] >= 1, blocked
assert any(
    row["kind"] == "other" and row["hit_object"] == "Crate"
    for row in blocked["ground_probe_hit_objects"]
), blocked
cleared = audit(cam_default, hide=[pallet, crate])
assert cleared["ground_continuity_pass"] is True, cleared
crate.hide_viewport = True
crate.hide_render = True
bpy.context.view_layer.update()

# --- 4. a raised support ledge breaks the height-continuity condition ----------------------
ledge = plane("Ledge", 3.0, (cam_default[0] * 0.6, cam_default[1] * 0.6, 0.30))
bpy.context.view_layer.update()
stepped = audit(cam_default, support=[floor, ledge])
assert stepped["ground_continuity_pass"] is False, stepped
assert stepped["ground_probe_fail_count"] == 0, stepped
assert stepped["ground_probe_max_step_m"] > sp2.GROUND_PROBE_STEP_TOLERANCE_M, stepped
assert "support_z_discontinuity" in stepped["ground_continuity_reason"], stepped
ledge.location.z = FLOOR_Z + 0.02
bpy.context.view_layer.update()
gentle = audit(cam_default, support=[floor, ledge])
assert gentle["ground_continuity_pass"] is True, gentle
ledge.hide_viewport = True
ledge.hide_render = True
bpy.context.view_layer.update()

# --- 5. a plane too small for the camera distance: miss + edge risk ------------------------
floor.data.clear_geometry()
floor.data.from_pydata(
    [(-6.0, -6.0, 0.0), (6.0, -6.0, 0.0), (6.0, 6.0, 0.0), (-6.0, 6.0, 0.0)],
    [],
    [(0, 1, 2, 3)],
)
floor.data.update()
bpy.context.view_layer.update()
cam_far = camera_at(10.0, 15.0, 0.0)
small = audit(cam_far, plane_size=12.0)
assert small["ground_continuity_pass"] is False, small
assert small["procedural_floor_edge_risk"] is True, small
assert small["procedural_floor_edge_margin_m"] < 0.0, small
assert small["ground_probe_fail_count"] >= 1, small
assert small["ground_probe_hit_objects"][0]["kind"] == "miss", small
assert "procedural_floor_edge" in small["ground_continuity_reason"], small

# --- 6. a pallet parked over a void: the target-side probes miss ---------------------------
void_report = sv2.check_ground_continuity(
    camera_at(4.0, 30.0, 180.0),
    (9.0, 0.0),
    [floor],
    floor_object=floor,
    plane_size=12.0,
    plane_center_xy=(0.0, 0.0),
    hide_objects=[pallet],
)
assert void_report["ground_continuity_pass"] is False, void_report
assert void_report["ground_probe_hit_objects"][-1]["kind"] == "miss", void_report
assert void_report["ground_probe_hit_objects"][-1]["support_z"] is None, void_report

# --- 7. no support objects at all -> not measurable, never a silent pass -------------------
unmeasurable = sv2.check_ground_continuity(
    cam_default,
    (0.0, 0.0),
    [],
    floor_object=None,
    plane_size=None,
)
assert unmeasurable["ground_continuity_pass"] is None, unmeasurable
assert unmeasurable["ground_continuity_reason"] == "no_support_objects", unmeasurable

# --- 8. native floor mode (no procedural plane) skips the bounds test ----------------------
native_ground = plane("NativeGround", 200.0, (0.0, 0.0, 0.0))
bpy.context.view_layer.update()
native = sv2.check_ground_continuity(
    camera_at(10.0, 20.0, 45.0),
    (0.0, 0.0),
    [native_ground],
    floor_object=None,
    plane_size=None,
    hide_objects=[pallet],
)
assert native["ground_continuity_pass"] is True, native
assert native["procedural_floor_edge_risk"] is False, native
assert native["procedural_floor_edge_margin_m"] is None, native
assert [row["kind"] for row in native["ground_probe_hit_objects"]] == ["support"] * 11, native

print(
    "[ground-continuity-regression] sweep_configs=%d min_floor_edge_margin_m=%.3f "
    "max_probe_step_m=%.5f floor_half_extent_m=%.1f"
    % (sweep_count, min_margin, max(sweep_steps), cfg.FLOOR_PLANE_SIZE / 2.0)
)
print("[ground-continuity-regression] PASS")
