"""Diagnostic: natural V (in-frame corner count) reachability per target_v, no render.
Runs generate_frame with a v_gate that records V then rejects (so nothing renders).
Tallies V distribution and mean elevation per V, to tune the sampler before the full run.
"""
import bpy, sys, os, argparse, collections
argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []
p = argparse.ArgumentParser()
p.add_argument("--n_per", type=int, default=120)
p.add_argument("--seed", type=int, default=5)
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
random.seed(args.seed)

overlay = r"C:/Users/User/AppData/Local/Temp/claude/tmp_overlay_probe"
os.makedirs(overlay, exist_ok=True)

results = {}
for tv in [4, 5, 6, 7, 8, None]:
    vc = collections.Counter()
    elev_by_v = collections.defaultdict(list)
    rec = {}
    def vgate(v, rec=rec):
        rec['v'] = v
        return False  # always reject -> no render
    for i in range(args.n_per):
        fw = (tv is not None and tv <= 7 and random.random() < 0.2)
        sc = G.sample_trunc_scenario(i, target_v=tv, force_worst=fw)
        rec.clear()
        ok, log, m = G.generate_frame(*handles, 0, sc, overlay, overlay,
                                      env, mp, bgn, hdris, W, H, v_gate=vgate)
        v = m.get("v_probe", rec.get('v'))
        if v is None:
            continue
        vc[v] += 1
        elev_by_v[v].append(sc["elev_deg"])
    results[str(tv)] = (dict(vc), {k: round(sum(x)/len(x), 1) for k, x in elev_by_v.items()})
    tot = sum(vc.values())
    dist = {v: f"{100*vc[v]/tot:.0f}%" for v in sorted(vc)}
    print(f"target_v={tv}: N={tot} Vdist={dist}")
    sys.stdout.flush()

print("=== elev-mean by V (target=None free sampler) ===")
print(results['None'][1])
sys.stdout.flush()
