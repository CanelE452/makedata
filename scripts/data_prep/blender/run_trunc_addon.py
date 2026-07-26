"""
trunc_addon driver — low-elevation + truncation dataset with stratified V-rejection.

Usage (CLI standalone):
  "/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
     data/pallet/blender_scene/_sandbox_palletobj_production.blend \
     --python scripts/data_prep/blender/run_trunc_addon.py -- \
     --num_frames 300 --out data/pallet/trunc_addon_v1 --seed 1234

Argparse args are AFTER `--`. Logs to stdout (redirect to file).

Gap (B) — V (in-frame corner count) distribution targeting via STRATIFIED REJECTION:
  target fractions V4:0.15 V5:0.25 V6:0.30 V7:0.20 V8:0.10.
  Each output slot is assigned a target V (bin with largest remaining deficit, weighted
  random). The scenario sampler biases distance/truncation toward that V, and a cheap
  pre-render v_gate (in gen_trunc_addon.generate_frame) rejects mismatched frames BEFORE
  any render. Soft-relax after K_SOFT attempts (accept any V still in deficit), full-relax
  after K_HARD (accept any valid render) to guarantee progress.
"""
import bpy, sys, os, argparse, time, json, gc, random
import glob as _glob

argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []

parser = argparse.ArgumentParser()
parser.add_argument("--num_frames", type=int, default=300)
parser.add_argument("--out", type=str,
                    default=r"E:/CODING/GitHub/FoundationPose/data/pallet/trunc_addon_v1")
parser.add_argument("--seed", type=int, default=1234)
parser.add_argument("--start_idx", type=int, default=0)
parser.add_argument("--progress_every", type=int, default=10)
parser.add_argument("--purge_every", type=int, default=50)
parser.add_argument("--worst_frac", type=float, default=0.20)
parser.add_argument("--k_soft", type=int, default=14)
parser.add_argument("--k_hard", type=int, default=30)
parser.add_argument("--k_slot_max", type=int, default=45)
args = parser.parse_args(argv)

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import gen_trunc_addon as G

os.makedirs(os.path.join(args.out, "overlay"), exist_ok=True)

scene = bpy.context.scene
scene.render.resolution_x = 640
scene.render.resolution_y = 480
scene.render.image_settings.file_format = 'PNG'
try:
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 16
except Exception:
    pass

scene_handles = G.get_scene_handles()

# (Re)load all HDRIs from disk; protect from orphans_purge.
HDRI_DIR = r"E:/CODING/GitHub/FoundationPose/data/pallet/hdri"
hdri_files = sorted(_glob.glob(os.path.join(HDRI_DIR, "*.hdr")))
print(f"[trunc_addon] HDRI files on disk: {len(hdri_files)}")
for hf in hdri_files:
    img = bpy.data.images.load(hf, check_existing=True)
    img.use_fake_user = True
sys.stdout.flush()

if "OCCLUDER_POOL" in bpy.data.collections:
    for o in bpy.data.collections["OCCLUDER_POOL"].objects:
        o.use_fake_user = True
        if o.type == 'MESH' and o.data:
            o.data.use_fake_user = True
for cn in ("BG_parking_lot", "BG_industrial"):
    if cn in bpy.data.collections:
        for o in bpy.data.collections[cn].objects:
            o.use_fake_user = True
            if o.type == 'MESH' and o.data:
                o.data.use_fake_user = True
pal_obj = bpy.data.objects.get("pallet_full")
if pal_obj:
    pal_obj.use_fake_user = True
    if pal_obj.data:
        pal_obj.data.use_fake_user = True

env_node, map_node, bg_node, hdri_imgs = G.get_world_hdri_nodes()
W, H = scene.render.resolution_x, scene.render.resolution_y
overlay_dir = os.path.join(args.out, "overlay")

# --- elevation-PRIMARY + V-secondary stratified targeting ---
N = args.num_frames
elev_target = [int(round(f * N)) for f in G.ELEV_BIN_FRAC]
elev_target[2] += N - sum(elev_target)          # absorb rounding into a 30% bin
v_target = {v: int(round(f * N)) for v, f in G.V_FRAC.items()}
v_target[6] += N - sum(v_target.values())       # absorb rounding into the largest bin
elev_filled = [0, 0, 0, 0, 0]
v_filled = {v: 0 for v in (4, 5, 6, 7, 8)}

print(f"[trunc_addon] start: num_frames={N} out={args.out} seed={args.seed}")
print(f"[trunc_addon] elev_target(bins {G.ELEV_BIN_EDGES})={elev_target}")
print(f"[trunc_addon] V_target={v_target}  HDRIs={len(hdri_imgs)} "
      f"OCCLUDER_POOL={sum(1 for _ in (bpy.data.collections.get('OCCLUDER_POOL').objects if 'OCCLUDER_POOL' in bpy.data.collections else []))}")
sys.stdout.flush()

random.seed(args.seed)
t_start = time.time()
frame_idx = args.start_idx
total_attempts = 0
safety = N * 80
success_log = []
reject_counter = {}

while frame_idx < args.start_idx + N and total_attempts < safety:
    b, elev_deg, tv, force_worst = G.plan_choice(elev_filled, v_filled, elev_target, v_target,
                                                 worst_frac=args.worst_frac, rng=random)
    placed = False
    slot_attempt = 0
    while slot_attempt < args.k_slot_max and not placed and total_attempts < safety:
        slot_attempt += 1
        total_attempts += 1
        sc = G.sample_trunc_scenario(total_attempts, target_v=tv, force_worst=force_worst,
                                     elev_override=elev_deg)
        if slot_attempt >= args.k_hard:
            def vgate(v):  # full relax: accept any valid render (elevation bin still filled)
                return True
        elif slot_attempt >= args.k_soft:
            def vgate(v, _vt=v_target, _vf=v_filled):  # soft relax: accept any V still in deficit
                return _vf.get(v, 0) < _vt.get(v, 0)
        else:
            def vgate(v, _tv=tv):  # strict: only the assigned target V
                return v == _tv

        ok, log, m = G.generate_frame(*scene_handles, frame_idx, sc, args.out, overlay_dir,
                                      env_node, map_node, bg_node, hdri_imgs, W, H, v_gate=vgate)
        if ok:
            v = m.get("in_fr")
            v_filled[v] = v_filled.get(v, 0) + 1
            elev_filled[b] += 1
            success_log.append({
                "i": frame_idx, "elev_bin": b, "target_v": tv, "V": v,
                "elev": round(sc["elev_deg"], 1), "mode": sc["trunc_mode"],
                "bg": sc["bg"], "d": round(sc["surf_dist"], 2),
                "T": sc["do_trunc"], "worst": force_worst, "O": sc["do_occ"],
                "vis": m.get("vis"), "unocc": m.get("unocc"),
            })
            frame_idx += 1
            placed = True
            if frame_idx % args.purge_every == 0:
                G.cleanup_occluders()
                G.cleanup_cargo()
                try:
                    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False,
                                                   do_recursive=False)
                except Exception:
                    pass
                gc.collect()
            if frame_idx % args.progress_every == 0:
                el = time.time() - t_start
                rate = (frame_idx - args.start_idx) / el if el > 0 else 0
                print(f"[trunc_addon] {frame_idx}/{args.start_idx + N} "
                      f"attempts={total_attempts} rate={rate:.2f}fps "
                      f"elev={elev_filled} V={v_filled}")
                sys.stdout.flush()
        else:
            key = log.split()[0]
            reject_counter[key] = reject_counter.get(key, 0) + 1

summary = {
    "total_frames": frame_idx - args.start_idx,
    "total_attempts": total_attempts,
    "elapsed_s": round(time.time() - t_start, 1),
    "seed": args.seed,
    "elev_bin_edges": G.ELEV_BIN_EDGES,
    "elev_target": elev_target,
    "elev_filled": elev_filled,
    "v_target": v_target,
    "v_filled": v_filled,
    "reject_counter": reject_counter,
    "out": args.out,
}
with open(os.path.join(args.out, "_summary.json"), "w") as f:
    json.dump({"summary": summary, "success_log": success_log}, f, indent=2)
print(f"[trunc_addon] DONE: {frame_idx - args.start_idx}/{args.num_frames} "
      f"attempts={total_attempts} elapsed={time.time()-t_start:.0f}s")
print(f"[trunc_addon] v_filled={v_filled} rejects={reject_counter}")
sys.stdout.flush()
