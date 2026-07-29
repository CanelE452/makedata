"""
Mass production runner — 10,000 frames.
Usage:
  blender -b _sandbox_palletobj_production.blend --python run_mass_10k.py -- --num_frames 10000 --out <dir> --seed 42

Argparse args are AFTER `--`. Logs to stdout (redirect to file).
"""
import bpy, sys, os, argparse, time, json

# Parse args after --
argv = sys.argv
if "--" in argv:
    argv = argv[argv.index("--") + 1:]
else:
    argv = []

parser = argparse.ArgumentParser()
parser.add_argument("--num_frames", type=int, default=10000)
parser.add_argument("--out", type=str, default=r"E:/CODING/GitHub/FoundationPose/data/pallet/train_palletobj_v1")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--start_idx", type=int, default=0)
parser.add_argument("--progress_every", type=int, default=10)
parser.add_argument("--purge_every", type=int, default=50)
parser.add_argument("--chunk_size", type=int, default=1000)
args = parser.parse_args(argv)

# Add script dir to path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import gen_palletobj_scenarios as G
import random
import gc

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

# Explicitly (re)load all HDRIs from disk — sandbox blend may have only 1 active
import glob as _glob
HDRI_DIR = r"E:/CODING/GitHub/FoundationPose/data/pallet/assets/lighting/hdri/library"  # Stage 2-B: registry hdri_root
hdri_files = sorted(_glob.glob(os.path.join(HDRI_DIR, "*.hdr")))
print(f"[Mass10k] HDRI files on disk: {len(hdri_files)}")
for hf in hdri_files:
    img = bpy.data.images.load(hf, check_existing=True)
    img.use_fake_user = True   # protect from orphans_purge
    print(f"  loaded: {os.path.basename(hf)} (fake_user={img.use_fake_user})")
sys.stdout.flush()

# Protect occluder source objects + their mesh data from orphans_purge
if "OCCLUDER_POOL" in bpy.data.collections:
    for o in bpy.data.collections["OCCLUDER_POOL"].objects:
        o.use_fake_user = True
        if o.type == 'MESH' and o.data:
            o.data.use_fake_user = True
# Protect BG collection objects too (when hidden, they could be flagged unused)
for cn in ("BG_parking_lot", "BG_industrial"):
    if cn in bpy.data.collections:
        for o in bpy.data.collections[cn].objects:
            o.use_fake_user = True
            if o.type == 'MESH' and o.data:
                o.data.use_fake_user = True
# Protect pallet
pal_obj = bpy.data.objects.get("pallet_full")
if pal_obj:
    pal_obj.use_fake_user = True
    if pal_obj.data:
        pal_obj.data.use_fake_user = True
print(f"[Mass10k] Fake-user protection applied to HDRIs + assets")
sys.stdout.flush()

env_node, map_node, bg_node, hdri_imgs = G.get_world_hdri_nodes()
W, H = scene.render.resolution_x, scene.render.resolution_y

print(f"[Mass10k] start: num_frames={args.num_frames}, out={args.out}, seed={args.seed}")
print(f"[Mass10k] OCCLUDER_POOL objs: {sum(1 for o in (bpy.data.collections.get('OCCLUDER_POOL').objects if 'OCCLUDER_POOL' in bpy.data.collections else []))}")
print(f"[Mass10k] HDRIs: {len(hdri_imgs)}")
sys.stdout.flush()

random.seed(args.seed)
t_start = time.time()
frame_idx = args.start_idx
total_attempts = 0
safety = args.num_frames * 5
rejection_log = []
success_log = []

while frame_idx < args.start_idx + args.num_frames and total_attempts < safety:
    total_attempts += 1
    sc = G.sample_random_scenario(total_attempts)
    ok, log, metrics = G.generate_frame(*scene_handles, frame_idx, sc, args.out,
                                        os.path.join(args.out, "overlay"),
                                        env_node, map_node, bg_node, hdri_imgs, W, H)
    if ok:
        success_log.append({
            "i": frame_idx, "scenario": sc["name"],
            "bg": sc["bg"], "d": round(sc["surf_dist"], 2), "h": round(sc["h_above"], 2),
            "lens": round(sc["lens"], 1), "T": sc["do_trunc"], "O": sc["do_occ"],
            "cargo": sc.get("do_cargo", False),
            "vis": metrics.get("vis"), "in_fr": metrics.get("in_fr"), "unocc": metrics.get("unocc"),
            "actual_src": metrics.get("actual_src"),
        })
        frame_idx += 1
        # Periodic memory purge to avoid 0x1A MEMORY_MANAGEMENT BSOD
        if frame_idx % args.purge_every == 0:
            G.cleanup_occluders()
            G.cleanup_cargo()
            # Conservative purge: only local ids, no linked, no recursive
            # (recursive cleans things still referenced; we use fake_user to protect HDRIs/assets)
            try:
                bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=False)
            except Exception:
                pass
            gc.collect()
        # Incremental summary save every chunk
        if frame_idx % args.chunk_size == 0:
            with open(os.path.join(args.out, "_summary_partial.json"), "w") as f:
                json.dump({"frames_done": frame_idx, "elapsed_s": time.time() - t_start,
                           "attempts": total_attempts, "rejections": len(rejection_log)}, f, indent=2)
        if frame_idx % args.progress_every == 0:
            elapsed = time.time() - t_start
            rate = (frame_idx - args.start_idx) / elapsed if elapsed > 0 else 0
            remaining = (args.start_idx + args.num_frames - frame_idx) / rate if rate > 0 else 0
            print(f"[Mass10k] progress: {frame_idx}/{args.start_idx + args.num_frames}  "
                  f"attempts={total_attempts}  elapsed={elapsed:.0f}s  rate={rate:.2f}fps  "
                  f"eta={remaining/60:.1f}min")
            sys.stdout.flush()
    else:
        rejection_log.append({"frame_target": frame_idx, "log": log, "scenario": sc.get("name")})

# Save summary
summary = {
    "total_frames": frame_idx - args.start_idx,
    "total_attempts": total_attempts,
    "elapsed_s": time.time() - t_start,
    "rejection_count": len(rejection_log),
    "seed": args.seed,
    "out": args.out,
}
with open(os.path.join(args.out, "_summary.json"), "w") as f:
    json.dump({"summary": summary, "rejections": rejection_log[:200], "success_first50": success_log[:50]}, f, indent=2)
print(f"[Mass10k] DONE: {frame_idx}/{args.num_frames}  attempts={total_attempts}  elapsed={time.time()-t_start:.0f}s")
sys.stdout.flush()
