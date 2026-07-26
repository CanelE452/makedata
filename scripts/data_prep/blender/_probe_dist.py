"""Predict realized elevation + V marginals of the trunc_addon driver WITHOUT rendering.
Faithfully replays the driver loop (plan_choice + relaxing v_gate) but the gate records the
searched V and always returns False so no frame renders. Prints the marginals to compare
against the prescription before committing to the ~10 min render run.
"""
import bpy, sys, os, argparse, collections
argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []
p = argparse.ArgumentParser()
p.add_argument("--n", type=int, default=300)
p.add_argument("--seed", type=int, default=1234)
p.add_argument("--worst_frac", type=float, default=0.20)
p.add_argument("--k_soft", type=int, default=14)
p.add_argument("--k_hard", type=int, default=30)
p.add_argument("--k_slot_max", type=int, default=45)
args = p.parse_args(argv)

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
import gen_trunc_addon as G
import glob as _glob, random

scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 640, 480
try:
    scene.render.engine = 'BLENDER_EEVEE'
except Exception:
    pass
handles = G.get_scene_handles()
for hf in sorted(_glob.glob(r"E:/CODING/GitHub/FoundationPose/data/pallet/hdri/*.hdr")):
    im = bpy.data.images.load(hf, check_existing=True); im.use_fake_user = True
env, mp, bgn, hdris = G.get_world_hdri_nodes()
W, H = 640, 480
overlay = r"C:/Users/User/AppData/Local/Temp/claude/tmp_overlay_probe"
os.makedirs(overlay, exist_ok=True)

N = args.n
elev_target = [int(round(f * N)) for f in G.ELEV_BIN_FRAC]
elev_target[2] += N - sum(elev_target)
v_target = {v: int(round(f * N)) for v, f in G.V_FRAC.items()}
v_target[6] += N - sum(v_target.values())
elev_filled = [0, 0, 0, 0, 0]
v_filled = {v: 0 for v in (4, 5, 6, 7, 8)}

random.seed(args.seed)
frame_idx = 0
total_attempts = 0
accepted = []   # (elev_bin, V, elev_deg, mode)
safety = N * 80

while frame_idx < N and total_attempts < safety:
    b, elev_deg, tv, fw = G.plan_choice(elev_filled, v_filled, elev_target, v_target,
                                        worst_frac=args.worst_frac, rng=random)
    placed = False
    slot = 0
    while slot < args.k_slot_max and not placed and total_attempts < safety:
        slot += 1
        total_attempts += 1
        sc = G.sample_trunc_scenario(total_attempts, target_v=tv, force_worst=fw,
                                     elev_override=elev_deg)
        rec = {}

        def vgate(v, rec=rec, slot=slot):
            rec['v'] = v
            if slot >= args.k_hard:
                acc = True
            elif slot >= args.k_soft:
                acc = v_filled.get(v, 0) < v_target.get(v, 0)
            else:
                acc = (v == tv)
            rec['acc'] = acc
            return False  # never render

        ok, log, m = G.generate_frame(*handles, 0, sc, overlay, overlay,
                                      env, mp, bgn, hdris, W, H, v_gate=vgate)
        v = rec.get('v', m.get('v_probe'))
        if v is None or not rec.get('acc'):
            continue
        v_filled[v] += 1
        elev_filled[b] += 1
        accepted.append((b, v, sc['elev_deg'], sc['trunc_mode']))
        frame_idx += 1
        placed = True

# --- report ---
elev_counts = collections.Counter(a[0] for a in accepted)
vcounts = collections.Counter(a[1] for a in accepted)
n = len(accepted)
labels = ["<3", "3-8", "8-15", "15-25", "25+"]
print(f"\n=== PROBE_DIST n={n} attempts={total_attempts} ratio={total_attempts/max(1,n):.1f}x ===")
print("ELEV realized vs target:")
for i in range(5):
    print(f"  bin {labels[i]:6s}: {100*elev_counts[i]/n:5.1f}%  (target {100*G.ELEV_BIN_FRAC[i]:.0f}%)")
print(f"  <15deg total: {100*(elev_counts[0]+elev_counts[1]+elev_counts[2])/n:.1f}% (target 70%)")
print("V realized vs target:")
for v in (4, 5, 6, 7, 8):
    print(f"  V{v}: {100*vcounts[v]/n:5.1f}%  (target {100*G.V_FRAC[v]:.0f}%)")
# odd-V elevation (where do odd V land?)
odd_low = sum(1 for a in accepted if a[1] in (5, 7) and a[2] < 15)
odd_tot = sum(1 for a in accepted if a[1] in (5, 7))
print(f"odd-V (5,7): {odd_tot} frames, {odd_low} of them <15deg")
modes = collections.Counter(a[3] for a in accepted)
print(f"trunc modes: {dict(modes)}")
sys.stdout.flush()
