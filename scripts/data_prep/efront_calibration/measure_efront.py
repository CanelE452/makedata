"""READ-ONLY geometry probe for the "E-front 12-keypoint" feasibility check.

For each of the 4 production pallets (Pallet_0..3), reproduce the EXACT
label-generation geometry pipeline (get_normalized_scale -> set_object_pose_grounded
with ORIENTATION_OVERRIDES -> get_pallet_geometry) and measure, for each of the two
orthogonal vertical faces (the one whose horizontal width is longer = 'long', shorter
= 'short'):

  * nominal_dims_m   : the (W,D,H) the LABEL cuboid actually uses
                       (width_len_world, depth_len_world, height from corners_world)
  * mesh_aabb_m      : mesh AABB re-measured along the canonical axes (W,D,H)
  * face silhouette openings (fork holes) via a THIN FRONT-SLAB orthographic raster
    (only geometry whose triangle-centroid depth is within EPS_SLAB of the frontmost
    plane d_max is kept -> the through-tunnel back structure is discarded).

Outputs (into this folder only -- pipeline files untouched):
  * efront_measurements.json          the 8 records (4 pallet x 2 faces)
  * efront_P{k}_{face}.png            perspective front render (elev ~2deg, floor line)
  * efront_P{k}_{face}_mask.png       binary front-slab silhouette (holes BLACK)
  * debug/*                            per-face stats dumps

NOTHING in the production pipeline is modified. Materials are overridden only
in-memory for the render pass.
"""

import bpy, bmesh, os, sys, json, math
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BLENDER_DIR = os.path.join(REPO, "scripts", "data_prep", "blender")
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import blender_config as cfg  # noqa: E402
from blender_config import (  # noqa: E402
    ORIENTATION_OVERRIDES, PALLET_NAMES, PALLET_SOURCE_ASSETS, PALLET_SOURCE_DIR,
    TARGET_CANONICAL_DIMS,
)
from pallet_geometry import (  # noqa: E402
    get_pallet_geometry, get_normalized_scale, set_object_pose_grounded,
    set_render_visibility, iter_mesh_objects,
)
from randomizers import get_obj, setup_render  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from PIL import Image  # noqa: E402

# -- measurement params ------------------------------------------------------
PX_PER_M   = 1500      # raster resolution of the face grid
EPS_SLAB   = 0.10      # front-slab thickness (m): keep tris whose centroid depth is
#                        within EPS_SLAB of the frontmost plane d_max -> discard the
#                        back (through-tunnel) structure. Chosen large enough to
#                        capture RECESSED front feet/blocks (P1/P2 stringer sides sit
#                        3-8 cm behind the deck front edge) yet << the fork-tunnel
#                        clear depth (>0.3 m) so enclosed holes are never back-filled.
FILL_RECT  = 0.985     # rect_fill_ratio >= this -> corner_radius reported 0
MIN_OPEN_AREA_FRAC = 0.006  # ignore empty specks < this fraction of face area
MIN_OPEN_H = 0.030     # ignore empty regions shorter than this (m) -> kills the thin
#                        floor-line raster slivers, keeps real fork openings.

RES_X, RES_Y = 1280, 960
OUT_JSON = os.path.join(HERE, "efront_measurements.json")
DEBUG = os.path.join(HERE, "debug")
os.makedirs(DEBUG, exist_ok=True)


def _n(v):
    v = np.asarray(v, dtype=np.float64)
    nn = np.linalg.norm(v)
    return v / nn if nn > 1e-12 else v


# ---------------------------------------------------------------------------
# geometry gathering
# ---------------------------------------------------------------------------
def gather_world_tris(obj):
    """All child-mesh triangles in WORLD space -> (N,3,3)."""
    dg = bpy.context.evaluated_depsgraph_get()
    tris = []
    n_meshes = 0
    for mesh_obj in iter_mesh_objects(obj):
        n_meshes += 1
        bm = bmesh.new()
        try:
            bm.from_object(mesh_obj, dg)
            bm.transform(mesh_obj.matrix_world)
            bmesh.ops.triangulate(bm, faces=bm.faces)
            for f in bm.faces:
                vs = f.verts
                if len(vs) != 3:
                    continue
                tris.append([[vs[0].co.x, vs[0].co.y, vs[0].co.z],
                             [vs[1].co.x, vs[1].co.y, vs[1].co.z],
                             [vs[2].co.x, vs[2].co.y, vs[2].co.z]])
        finally:
            bm.free()
    return np.asarray(tris, dtype=np.float64), n_meshes


def raster_polys(polys, u_lo, u_hi, v_lo, v_hi, px_per_m):
    """Fill a boolean occupancy grid from a list of (u,v) triangle polygons.
    STANDARD image orientation: occ[0]=top (v_hi), occ[-1]=floor (v_lo);
    occ[:,0]=left (u_lo), occ[:,-1]=right (u_hi)."""
    from PIL import ImageDraw
    W = max(4, int(round((u_hi - u_lo) * px_per_m)))
    H = max(4, int(round((v_hi - v_lo) * px_per_m)))
    img = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(img)

    def to_px(u, v):
        ix = (u - u_lo) / (u_hi - u_lo) * (W - 1)
        iy = (v_hi - v) / (v_hi - v_lo) * (H - 1)   # v_hi->row0 (top), v_lo->row H-1
        return ix, iy

    for poly in polys:
        dr.polygon([to_px(u, v) for (u, v) in poly], fill=255)
    occ = (np.asarray(img) > 127)
    return occ, W, H


def connected_components(mask):
    """4-connected components of True cells. Returns label array + count."""
    H, W = mask.shape
    lab = np.zeros((H, W), dtype=np.int32)
    cur = 0
    for r0 in range(H):
        for c0 in range(W):
            if not mask[r0, c0] or lab[r0, c0]:
                continue
            cur += 1
            stack = [(r0, c0)]
            lab[r0, c0] = cur
            while stack:
                r, c = stack.pop()
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < H and 0 <= cc < W and mask[rr, cc] and not lab[rr, cc]:
                        lab[rr, cc] = cur
                        stack.append((rr, cc))
    return lab, cur


def detect_openings(occ, u_lo, u_hi, v_lo, v_hi):
    """Openings = empty components enclosed on left/right/top; the FLOOR (bottom) edge
    may be open (bottom_open). occ is standard-oriented: row0=top(v_hi),
    row H-1=floor(v_lo)."""
    H, W = occ.shape
    empty = ~occ
    lab, n = connected_components(empty)
    cell_area = ((u_hi - u_lo) / W) * ((v_hi - v_lo) / H)
    face_area = (u_hi - u_lo) * (v_hi - v_lo)
    openings = []
    for k in range(1, n + 1):
        ys, xs = np.where(lab == k)
        if xs.size == 0:
            continue
        area = xs.size * cell_area
        if area < MIN_OPEN_AREA_FRAC * face_area:
            continue
        v_ext = (ys.max() - ys.min()) / max(1, H - 1) * (v_hi - v_lo)
        if v_ext < MIN_OPEN_H:
            continue                          # thin floor-line sliver, not a fork hole
        touch_left = (xs.min() == 0)
        touch_right = (xs.max() == W - 1)
        touch_top = (ys.min() == 0)          # row 0 -> v_hi (deck/top)
        touch_bottom = (ys.max() == H - 1)   # row H-1 -> v_lo (floor)
        if touch_left or touch_right or touch_top:
            continue                          # exterior background, not an opening
        # bbox in metres (row0=top=v_hi)
        um = u_lo + xs.min() / (W - 1) * (u_hi - u_lo)
        uM = u_lo + xs.max() / (W - 1) * (u_hi - u_lo)
        vM = v_hi - ys.min() / (H - 1) * (v_hi - v_lo)   # top of hole (higher v)
        vm = v_hi - ys.max() / (H - 1) * (v_hi - v_lo)   # bottom of hole
        bbox_area = max(1e-9, (uM - um) * (vM - vm))
        fill = area / bbox_area
        if fill >= FILL_RECT:
            corner_r_mm = 0.0
        else:
            miss = max(0.0, (1.0 - fill) * bbox_area)
            corner_r_mm = math.sqrt(miss / (4.0 * (1.0 - math.pi / 4.0))) * 1000.0
        openings.append({
            "u_min": round(float(um), 4), "u_max": round(float(uM), 4),
            "v_min": round(float(vm), 4), "v_max": round(float(vM), 4),
            "bottom_open": bool(touch_bottom),
            "rect_fill_ratio": round(float(fill), 3),
            "corner_radius_mm": round(float(corner_r_mm), 1),
            "_area_m2": round(float(area), 5),
        })
    openings.sort(key=lambda o: o["u_min"])
    return openings


# ---------------------------------------------------------------------------
# generalized BOTTOM-OPEN fork detection (front-slab, deck-underside capped)
# ---------------------------------------------------------------------------
# `detect_openings` on the see-through projection handles every face whose fork
# openings are ENCLOSED head-on -- including bottom-open feet faces with a SOLID
# deck front rail (e.g. P1 short: the fork enters between 3 feet with no bottom
# board, the solid deck caps the top, so open_proj already reports it bottom_open).
# It FAILS on a face whose deck is SLATTED and/or whose pallet is a 4-way BLOCK
# type: each floor-open fork gap then leaks up through the deck slats to the sky
# (touch_top -> dropped) and the interior 4-way channels interconnect the tunnels
# in the see-through projection, so open_proj collapses to 0 (P2 long).
#
# The generalisation below recovers those faces from the FRONT-SLAB silhouette
# (front-block faces separate the tunnels; no see-through interconnect): seal each
# floor-reaching gap with its left/right neighbour blocks + the deck underside
# (top cap) so the gaps become enclosed bottom-open openings, then run the SAME
# detect_openings and restore the true floor-open geometry. This is the standard
# path for both P1 short (via open_proj) and P2 long (via this detector); both
# yield n=2 bottom-open openings under one measure_efront.py run.
def find_gaps_lowerband(occ, band_frac=0.28):
    """Floor-reaching empty column runs (fork gaps between grounded blocks/feet) in
    the lower band of a front-slab silhouette. Returns (gaps, col_occ); each gap is a
    (c_lo, c_hi) column-index run not touching the L/R image edge and >= 6% of width."""
    H, W = occ.shape
    lo_row = int(round(H * (1.0 - band_frac)))       # rows near the floor (bottom band)
    band = occ[lo_row:, :]
    col_occ = band.mean(axis=0)                       # per-column occupancy in bottom band
    empty_col = col_occ < 0.15
    runs = []
    c = 0
    while c < W:
        if empty_col[c]:
            c0 = c
            while c < W and empty_col[c]:
                c += 1
            runs.append((c0, c - 1))
        else:
            c += 1
    gaps = [(a, b) for (a, b) in runs
            if a > 0 and b < W - 1 and (b - a) >= 0.06 * W]
    return gaps, col_occ


def deck_underside_over_gap(occ, c_lo, c_hi, v_hi, thresh=0.5, floor_skip_m=0.02):
    """Fork-tunnel roof (= deck underside) over one gap. Scan from the FLOOR up: the
    tunnel is empty; the first row (going up) whose deck coverage over the gap columns
    reaches >= thresh is the tunnel roof. Returns (deck_row, v_metres).
    row0=top(v_hi) .. row H-1=floor(0)."""
    H, W = occ.shape
    sub = occ[:, c_lo:c_hi + 1]
    row_occ = sub.mean(axis=1)                        # per-row deck coverage over the gap
    skip = int(round(floor_skip_m / v_hi * (H - 1)))  # ignore floor-line raster sliver
    deck_row = 0
    for r in range(H - 1 - skip, -1, -1):             # floor -> up
        if row_occ[r] >= thresh:
            deck_row = r
            break
    v_metres = v_hi - deck_row / (H - 1) * v_hi
    return deck_row, float(v_metres)


def detect_bottom_open_fork(occ, u_lo, u_hi, v_lo, v_hi):
    """General bottom-open fork detector on a FRONT-SLAB silhouette `occ`
    (row0=top=v_hi, row H-1=floor=v_lo=0). Steps:

      1. find the 2 floor-reaching fork gaps between the grounded blocks,
      2. cap each gap at the deck underside (fork-tunnel roof) and seal the empty
         raster floor-sliver so the blocks separate the tunnels -> enclosed openings,
      3. run the SAME detect_openings, then
      4. restore the true bottom-open geometry (v_min=0) and recompute rect_fill /
         corner_radius over the opening rectangle from the ORIGINAL (uncapped) slab.

    Returns (openings, meta) with exactly 2 bottom-open openings, or (None, meta) when
    the face is not a clean 3-block / 2-gap floor-open fork face."""
    H, W = occ.shape
    gaps, _ = find_gaps_lowerband(occ)
    if len(gaps) != 2:
        return None, {"reason": f"expected 2 floor-open fork gaps, found {len(gaps)}"}

    deck_rows, deck_vs = [], []
    for (a, b) in gaps:
        dr, dv = deck_underside_over_gap(occ, a, b, v_hi)
        deck_rows.append(dr)
        deck_vs.append(dv)
    v_max_shared = float(min(deck_vs))                # lower (conservative) shared roof
    deck_row = int(max(deck_rows))                    # larger row idx = lower v

    occ_cap = occ.copy()
    occ_cap[:deck_row + 1, :] = True                  # make the deck band solid (top cap)

    # Seal ONLY the empty raster floor-sliver at v~0: grounded block bottoms sit on the
    # last row, which PIL polygon-fill leaves empty, so an all-empty few-px floor row
    # would connect both tunnels + exterior into one component. The blocks are solid
    # floor->deck (bottom band occupancy ~1 above ~2 cm), so this is a true bottom-open
    # fork face; sealing the sliver lets the blocks separate the two tunnels.
    floor_seal = 0
    for r in range(H - 1, -1, -1):
        if occ[r].mean() < 0.20:
            floor_seal = H - r
        else:
            break
    if floor_seal > 0:
        occ_cap[H - floor_seal:, :] = True

    openings = detect_openings(occ_cap, u_lo, u_hi, v_lo, v_hi)
    if len(openings) != 2:
        return None, {"reason": f"cap+seal enclosed {len(openings)} openings (need 2)",
                      "deck_underside_v_per_gap_m": [round(x, 4) for x in deck_vs]}

    # restore the true bottom-open geometry (v_min=0, bottom_open=True) and recompute
    # rect_fill / corner_radius over the TRUE opening [u_min,u_max]x[0,v_max] from the
    # ORIGINAL (uncapped, unsealed) slab silhouette -- same convention as P1 short.
    for o in openings:
        c0 = int(round((o["u_min"] - u_lo) / (u_hi - u_lo) * (W - 1)))
        c1 = int(round((o["u_max"] - u_lo) / (u_hi - u_lo) * (W - 1)))
        r_top = int(round((v_hi - o["v_max"]) / (v_hi - v_lo) * (H - 1)))
        sub = occ[r_top:H, c0:c1 + 1]                 # deck underside -> floor
        empty = int((~sub).sum())
        total = int(sub.size)
        fill = empty / max(1, total)
        if fill >= FILL_RECT:
            corner_r_mm = 0.0
        else:
            bbox_area = (o["u_max"] - o["u_min"]) * o["v_max"]
            miss = max(0.0, (1.0 - fill) * bbox_area)
            corner_r_mm = math.sqrt(miss / (4.0 * (1.0 - math.pi / 4.0))) * 1000.0
        o["v_min"] = 0.0
        o["bottom_open"] = True
        o["rect_fill_ratio"] = round(float(fill), 3)
        o["corner_radius_mm"] = round(float(corner_r_mm), 1)

    meta = {"method": "front_slab_bottom_open_capped_sealed",
            "deck_underside_v_per_gap_m": [round(x, 4) for x in deck_vs],
            "v_max_shared_m": round(v_max_shared, 4),
            "floor_seal_rows": int(floor_seal)}
    return openings, meta


def measure_face(tris, geom, axis, name, face_label):
    # The pallet is grounded upright, so WORLD +Z is the unambiguous vertical axis
    # (v=0 at the floor = min world z). Do NOT derive 'up' from the canonical corners:
    # its sign is inverted for some pallets, which flips v and makes floor-open fork
    # notches register as touching the 'top' -> wrongly dropped as exterior.
    centroid = np.asarray(geom["centroid_world"], dtype=np.float64)
    w_dir = _n(geom["width_dir_world"])
    d_dir = _n(geom["depth_dir_world"])
    up = np.array([0.0, 0.0, 1.0])
    # horizontalise the two footprint axes (remove any tiny z component)
    w_dir = _n(w_dir - up * float(w_dir @ up))
    d_dir = _n(d_dir - up * float(d_dir @ up))
    W = float(geom["width_len_world"])
    D = float(geom["depth_len_world"])

    if axis == "W":            # face spans width; outward normal = depth
        u_axis, depth_axis, face_w = w_dir, d_dir, W
    else:                       # face spans depth; outward normal = width
        u_axis, depth_axis, face_w = d_dir, w_dir, D

    Pall = tris.reshape(-1, 3)
    Z = Pall[:, 2]
    z_min, z_max = float(Z.min()), float(Z.max())
    H = z_max - z_min
    P = Pall - centroid
    U = (P @ u_axis).reshape(-1, 3)
    Vf = (Z - z_min).reshape(-1, 3)          # v=0 at floor
    Dd = (P @ depth_axis).reshape(-1, 3)

    d_max = float(Dd.max())
    cen_d = Dd.mean(axis=1)
    keep = cen_d >= (d_max - EPS_SLAB)
    # depth histogram (distance behind frontmost plane) to justify EPS_SLAB
    behind = d_max - cen_d
    hist, edges = np.histogram(behind, bins=[0, 0.02, 0.05, 0.10, 0.20, 0.40, 10.0])

    Uk, Vk = U[keep], Vf[keep]
    if Uk.shape[0] == 0:
        return None, None
    u_lo, u_hi = float(Uk.min()), float(Uk.max())
    v_lo, v_hi = 0.0, H

    u_all_lo, u_all_hi = float(U.min()), float(U.max())
    u_lo = min(u_lo, u_all_lo); u_hi = max(u_hi, u_all_hi)

    # (a) thin front slab silhouette: front-face APPEARANCE (captures recessed feet,
    #     shows floor-open notches). Fails when the deck front edge is broken into
    #     board-ends (no continuous top rail) -> notch reads open-top.
    polys = [list(zip(Uk[i], Vk[i])) for i in range(Uk.shape[0])]
    occ_slab, gW, gH = raster_polys(polys, u_lo, u_hi, v_lo, v_hi, PX_PER_M)
    open_slab = detect_openings(occ_slab, u_lo, u_hi, v_lo, v_hi)

    # (b) full-depth orthographic projection = TRUE see-through silhouette. A through
    #     fork tunnel stays empty (hole); the deck/bottom boards + blocks project into
    #     solid bands/columns even when their front edges are broken. This is what a
    #     labeller sees looking head-on at the face.
    polys_all = [list(zip(U[i], Vf[i])) for i in range(U.shape[0])]
    occ_proj, _, _ = raster_polys(polys_all, u_lo, u_hi, v_lo, v_hi, PX_PER_M)
    open_proj = detect_openings(occ_proj, u_lo, u_hi, v_lo, v_hi)

    # Primary = the head-on see-through projection (matches the labelling view). It
    # encloses fork openings whenever the deck front rail is continuous, including
    # bottom-open feet faces with a SOLID deck (P1 short). When it FAILS to enclose 2
    # openings (slatted deck leaks each floor-open gap to the sky and/or a 4-way block
    # pallet interconnects the tunnels -> P2 long -> open_proj=0), fall back to the
    # general bottom-open fork detector on the FRONT SLAB (deck-underside capped +
    # floor-sliver sealed). Both branches emit the SAME bottom_open convention.
    if len(open_proj) == 2:
        openings, occ = open_proj, occ_proj
        method = "full_depth_orthographic_projection (see-through)"
        bmeta = None
    else:
        open_bottom, bmeta = detect_bottom_open_fork(occ_slab, u_lo, u_hi, v_lo, v_hi)
        if open_bottom is not None:
            openings, occ = open_bottom, occ_slab
            method = ("front_slab bottom-open fork (deck-underside capped + "
                      "floor-sliver sealed); see-through leaks slatted deck / 4-way "
                      "block channels")
        else:
            openings, occ = open_proj, occ_proj
            method = ("full_depth_orthographic_projection (see-through; no enclosed "
                      "opening, bottom-open fallback: %s)" % bmeta.get("reason", "n/a"))

    def _save_mask(occ_arr, suffix):
        im = Image.fromarray((occ_arr.astype(np.uint8)) * 255, mode="L")
        s = RES_X / occ_arr.shape[1]
        im = im.resize((RES_X, max(1, int(round(occ_arr.shape[0] * s)))), Image.NEAREST)
        p = os.path.join(HERE, f"efront_{name.replace('Pallet_', 'P')}_{face_label}{suffix}.png")
        im.convert("RGB").save(p)
        return p

    mask_path = _save_mask(occ, "_mask")       # the CHOSEN silhouette (slab for P2 long)
    _save_mask(occ_slab, "_maskslab")

    with open(os.path.join(DEBUG, f"{name}_{face_label}.txt"), "w") as f:
        f.write(f"axis={axis} face_w={face_w:.4f} H={H:.4f} d_max={d_max:.4f} "
                f"n_tris={tris.shape[0]} n_keep={int(keep.sum())} grid={gW}x{gH}\n")
        f.write(f"u_lo={u_lo:.4f} u_hi={u_hi:.4f} occ_slab_fill={occ_slab.mean():.3f} "
                f"occ_proj_fill={occ_proj.mean():.3f}\n")
        f.write(f"n_slab={len(open_slab)} n_proj={len(open_proj)} method={method}\n")
        if bmeta is not None:
            f.write(f"bottom_open_meta={json.dumps(bmeta)}\n")
        f.write(f"depth_behind_hist(bins 0/2/5/10/20/40/+cm)={hist.tolist()}\n")
        f.write("-- proj openings --\n")
        for o in open_proj:
            f.write(json.dumps(o) + "\n")
        f.write("-- slab openings --\n")
        for o in open_slab:
            f.write(json.dumps(o) + "\n")

    rec = {
        "face": face_label,
        "face_axis": axis,
        "face_width_m": round(face_w, 4),
        "face_height_m": round(H, 4),
        "nominal_dims_m": {"W": round(W, 4), "D": round(D, 4), "H": round(H, 4)},
        "silhouette_method": "%s; slab eps=%.2fm kept for cross-check" % (method, EPS_SLAB),
        "n_openings": len(openings),
        "n_openings_slab_xcheck": len(open_slab),
        "openings": openings,
        "mask_png": mask_path,
    }
    if bmeta is not None:
        rec["bottom_open_meta"] = bmeta
    return rec, {"n_keep": int(keep.sum()), "grid": f"{gW}x{gH}",
                 "n_slab": len(open_slab), "n_proj": len(open_proj)}


# ---------------------------------------------------------------------------
# rendering (perspective front photo)
# ---------------------------------------------------------------------------
def _neutral_material():
    m = bpy.data.materials.get("EFrontNeutral")
    if m:
        return m
    m = bpy.data.materials.new("EFrontNeutral")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = (0.42, 0.40, 0.38, 1.0)
        if "Roughness" in b.inputs:
            b.inputs["Roughness"].default_value = 0.85
        em = b.inputs.get("Emission Strength")
        if em is not None:
            em.default_value = 0.0
    return m


def override_materials(obj, mat):
    for mo in iter_mesh_objects(obj):
        mo.data.materials.clear()
        mo.data.materials.append(mat)


def setup_world_floor_sun():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    try:
        scene.eevee.taa_render_samples = 48
    except Exception:
        pass
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    world = scene.world or bpy.data.worlds.new("EFrontWorld")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.16, 0.30, 0.42, 1.0)   # contrasting blue-grey
    bg.inputs["Strength"].default_value = 0.7
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=60.0, location=(0, 0, -0.004))
    floor = bpy.context.active_object
    floor.name = "EFrontFloor"
    fm = bpy.data.materials.new("EFrontFloorMat")
    fm.use_nodes = True
    fb = fm.node_tree.nodes.get("Principled BSDF")
    if fb:
        fb.inputs["Base Color"].default_value = (0.55, 0.55, 0.57, 1.0)
    floor.data.materials.append(fm)

    ld = bpy.data.lights.new("EFrontSun", type="SUN")
    ld.energy = 3.5
    ld.angle = math.radians(4.0)
    sun = bpy.data.objects.new("EFrontSun", ld)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(48.0), math.radians(8.0), math.radians(28.0))
    return floor, sun


def hide_all_except(keep):
    keepset = set()
    for o in keep:
        keepset.add(o)
        keepset.update(o.children_recursive)
    for obj in bpy.data.objects:
        if obj.type == "CAMERA" or obj in keepset:
            continue
        obj.hide_render = True
        obj.hide_viewport = True


def front_face_corners(geom, axis):
    centroid = np.asarray(geom["centroid_world"], dtype=np.float64)
    cw = np.asarray(geom["corners_world"], dtype=np.float64)
    depth_axis = _n(geom["depth_dir_world"]) if axis == "W" else _n(geom["width_dir_world"])
    dd = (cw - centroid) @ depth_axis
    order = np.argsort(dd)
    return cw[order[4:]], _n(depth_axis)   # 4 frontmost corners, outward normal


def render_front(name, face_label, obj, geom, axis, floor, mask=False):
    import mathutils
    scene = bpy.context.scene
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    fcorners, n_out = front_face_corners(geom, axis)
    face_center = fcorners.mean(axis=0)
    # camera sits outward along +normal, elevation ~2deg
    elev = math.radians(2.0)
    dist = 3.2
    cam = scene.camera
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = 36.0
    cam.data.lens = 90.0
    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0

    up = np.array([0.0, 0.0, 1.0])
    cam_pos = face_center + n_out * dist
    cam_pos[2] = face_center[2] + dist * math.tan(elev)
    cam.location = mathutils.Vector([float(v) for v in cam_pos])
    look = mathutils.Vector([float(v) for v in face_center])
    direction = look - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()

    # fit lens so the 4 face corners fill ~0.82 of frame
    pts = [mathutils.Vector([float(x) for x in c]) for c in fcorners]

    def maxfrac():
        m = 0.0
        for p in pts:
            co = world_to_camera_view(scene, cam, p)
            if co.z <= 0:
                continue
            m = max(m, abs(co.x - 0.5), abs(co.y - 0.5))
        return m

    for _ in range(8):
        cur = maxfrac()
        if cur <= 1e-6:
            break
        cam.data.lens *= 0.41 / cur
        cam.data.lens = max(20.0, min(300.0, cam.data.lens))
        bpy.context.view_layer.update()

    if mask:
        # white emissive slab-only render on black; floor hidden
        pass  # handled by caller building temp slab mesh
    out = os.path.join(HERE, f"efront_{name.replace('Pallet_', 'P')}_{face_label}.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"  [RENDER] {out} lens={cam.data.lens:.1f} frac={maxfrac():.3f}")
    return out


# ---------------------------------------------------------------------------
def main():
    setup_render()                      # imports/binds the 4 USD pallets (hidden)
    floor, sun = setup_world_floor_sun()
    neutral = _neutral_material()

    records = []
    # place + scale ALL pallets first (matches production ordering), keep hidden
    placed = {}
    for name in PALLET_NAMES:
        obj = get_obj(name)
        if obj is None:
            print(f"  [MISSING] {name}")
            continue
        obj.scale = tuple(get_normalized_scale(obj, ORIENTATION_OVERRIDES.get(name, (0, 0, 0))))
        bpy.context.view_layer.update()
        set_object_pose_grounded(obj, 0.0, 0.0, 0.0,
                                 base_rot_deg=ORIENTATION_OVERRIDES.get(name, (0, 0, 0)),
                                 ground_z=0.0)
        placed[name] = obj

    for name in PALLET_NAMES:
        obj = placed.get(name)
        if obj is None:
            continue
        set_render_visibility(obj, True)
        bpy.context.view_layer.update()
        geom = get_pallet_geometry(name, obj, ORIENTATION_OVERRIDES)
        tris, n_meshes = gather_world_tris(obj)
        W = float(geom["width_len_world"]); D = float(geom["depth_len_world"])
        Pall = tris.reshape(-1, 3)
        H = float(Pall[:, 2].max() - Pall[:, 2].min())      # world-Z (upright) height

        # mesh AABB along canonical horizontal axes + world-Z height
        centroid = np.asarray(geom["centroid_world"])
        up = np.array([0.0, 0.0, 1.0])
        w_dir = _n(geom["width_dir_world"]); d_dir = _n(geom["depth_dir_world"])
        w_dir = _n(w_dir - up * float(w_dir @ up)); d_dir = _n(d_dir - up * float(d_dir @ up))
        P = Pall - centroid
        mesh_W = float((P @ w_dir).max() - (P @ w_dir).min())
        mesh_D = float((P @ d_dir).max() - (P @ d_dir).min())
        mesh_H = float(Pall[:, 2].max() - Pall[:, 2].min())

        # long / short assignment by horizontal width
        faces = []
        if W >= D:
            faces = [("W", "long"), ("D", "short")]
        else:
            faces = [("D", "long"), ("W", "short")]

        for axis, label in faces:
            rec, dbg = measure_face(tris, geom, axis, name, label)
            if rec is None:
                print(f"  [WARN] {name} {label}: empty slab")
                continue
            rec["pallet_id"] = name.replace("Pallet_", "P")
            rec["pallet_name"] = name
            rec["source_usd"] = os.path.join(PALLET_SOURCE_DIR, PALLET_SOURCE_ASSETS[name])
            rec["n_child_meshes"] = n_meshes
            rec["mesh_aabb_m"] = {"W": round(mesh_W, 4), "D": round(mesh_D, 4), "H": round(mesh_H, 4)}
            rec["aabb_vs_nominal_mm"] = {
                "W": round((mesh_W - W) * 1000, 1),
                "D": round((mesh_D - D) * 1000, 1),
                "H": round((mesh_H - H) * 1000, 1),
            }
            records.append(rec)
            print(f"  [MEAS] {rec['pallet_id']} {label} n_openings={rec['n_openings']} "
                  f"face_w={rec['face_width_m']} H={rec['face_height_m']} {dbg}")

        # --- render pass for this pallet's two faces ---
        override_materials(obj, neutral)
        hide_all_except([obj, floor])
        floor.hide_render = False; floor.hide_viewport = False
        for axis, label in faces:
            try:
                render_front(name, label, obj, geom, axis, floor, mask=False)
            except Exception as e:
                print(f"  [RENDER-ERR] {name} {label}: {e}")
        set_render_visibility(obj, False)

    with open(OUT_JSON, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  [JSON] {OUT_JSON}  ({len(records)} records)")
    print("  [DONE]")


if __name__ == "__main__":
    main()
