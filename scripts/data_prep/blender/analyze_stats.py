"""Statistical analysis of generated synthetic pallet dataset."""
import json, os, sys, glob
from collections import Counter, defaultdict
import statistics

if len(sys.argv) < 2:
    OUT_DIR = r"E:/CODING/GitHub/FoundationPose/data/pallet/train_palletobj_v1"
else:
    OUT_DIR = sys.argv[1]

json_files = sorted(glob.glob(os.path.join(OUT_DIR, "[0-9][0-9][0-9][0-9][0-9][0-9].json")))
print(f"Analyzing {len(json_files)} JSON files in {OUT_DIR}")
print("=" * 72)

# Aggregate
bg_count = Counter()
clock_count = Counter()
T_count = 0
O_count = 0
C_count = 0
TO_count = 0  # T+O
TC_count = 0  # T+C
OC_count = 0  # O+C
TOC_count = 0  # T+O+C
no_aug = 0  # nothing

dist_vals = []
height_vals = []
lens_vals = []
hfov_vals = []
azimuth_vals = []

vis_vals = []
in_fr_vals = []
unocc_vals = []
vis_drop_vals = []

occluder_used = Counter()
occluder_preferred = Counter()
occluder_fallback_count = 0  # preferred != actual

cargo_count_vals = []
cargo_assets_used = Counter()

# Defects to flag
defect_vis_low = 0       # vis < 5
defect_occ_ineffective = 0  # do_occ=True but no occluder placed
defect_trunc_no_realize = 0  # do_trunc=True but in_fr == 8
defect_occ_overkill = 0  # vis_drop >= 5 (heavy occlusion)

for jp in json_files:
    try:
        with open(jp) as f:
            ann = json.load(f)
    except Exception as e:
        print(f"  skip {os.path.basename(jp)}: {e}")
        continue
    m = ann["frame_meta"]
    o = ann["objects"][0]
    intr = ann["camera_data"]["intrinsics"]

    bg = m.get("background_3d", "?")
    bg_count[bg] += 1
    clock_count[m.get("clock_position", "?")] += 1
    T = m.get("truncation_applied", False)
    O = m.get("occlusion_applied", False)
    C = m.get("cargo_applied", False)
    if T: T_count += 1
    if O: O_count += 1
    if C: C_count += 1
    if T and O: TO_count += 1
    if T and C: TC_count += 1
    if O and C: OC_count += 1
    if T and O and C: TOC_count += 1
    if not (T or O or C): no_aug += 1

    dist_vals.append(m.get("camera_dist_from_pallet_surface_m", 0))
    height_vals.append(m.get("camera_height_above_floor_m", 0))
    lens_vals.append(intr.get("lens_mm", 0))
    hfov_vals.append(intr.get("hfov_deg", 0))
    azimuth_vals.append(m.get("azimuth_deg", 0))

    vis_vals.append(o.get("num_corners_visible", 0))
    in_fr_vals.append(o.get("num_corners_in_frame", 0))
    unocc_vals.append(o.get("num_corners_unoccluded", 0))
    vis_drop_vals.append(m.get("vis_drop", 0))

    pref = m.get("occluder_preferred")
    actual = m.get("occluder_actual")
    if O:
        if actual:
            occluder_used[actual] += 1
            if pref and pref != actual:
                occluder_fallback_count += 1
        if pref:
            occluder_preferred[pref] += 1
        if not actual:
            defect_occ_ineffective += 1

    n_cargo = m.get("cargo_count", 0)
    if C:
        cargo_count_vals.append(n_cargo)
        for asset in m.get("cargo_assets", []):
            cargo_assets_used[asset] += 1

    vis = o.get("num_corners_visible", 0)
    if vis < 5:
        defect_vis_low += 1
    if T and o.get("num_corners_in_frame", 8) == 8:
        defect_trunc_no_realize += 1
    if m.get("vis_drop", 0) >= 5:
        defect_occ_overkill += 1

# Print report
N = len(json_files)
def pct(n):
    return f"{n/N*100:.1f}%" if N else "?"

def histogram(vals, bins=10, label=""):
    if not vals: return
    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx > mn else 1
    bin_size = rng / bins
    buckets = [0] * bins
    for v in vals:
        idx = min(int((v - mn) / bin_size), bins - 1)
        buckets[idx] += 1
    max_count = max(buckets)
    bar_w = 30
    print(f"\n{label} (n={len(vals)}, min={mn:.2f}, max={mx:.2f}, mean={statistics.mean(vals):.2f}, median={statistics.median(vals):.2f})")
    for i, c in enumerate(buckets):
        lo = mn + i * bin_size
        hi = lo + bin_size
        bar = '#' * int(c / max_count * bar_w) if max_count > 0 else ''
        print(f"  [{lo:6.2f} ~ {hi:6.2f}]  {c:5d} ({c/N*100:5.1f}%) {bar}")

print(f"\n=== 1. Background Distribution ===")
for k, v in bg_count.most_common():
    print(f"  {k:20s} {v:5d} ({pct(v)})")

print(f"\n=== 2. Clock (azimuth direction) ===")
for k, v in sorted(clock_count.items()):
    print(f"  clock={k:>3} {v:5d} ({pct(v)})")

print(f"\n=== 3. Augmentation Flags ===")
print(f"  Truncation: {T_count:5d} ({pct(T_count)})")
print(f"  Occlusion : {O_count:5d} ({pct(O_count)})")
print(f"  Cargo     : {C_count:5d} ({pct(C_count)})")
print(f"  T+O       : {TO_count:5d} ({pct(TO_count)})")
print(f"  T+C       : {TC_count:5d} ({pct(TC_count)})")
print(f"  O+C       : {OC_count:5d} ({pct(OC_count)})")
print(f"  T+O+C     : {TOC_count:5d} ({pct(TOC_count)})")
print(f"  None of T/O/C: {no_aug:5d} ({pct(no_aug)})")

histogram(dist_vals, bins=10, label="=== 4. Camera Distance (surface, m) ===")
histogram(height_vals, bins=8, label="=== 5. Camera Height (m) ===")
histogram(lens_vals, bins=8, label="=== 6. Lens (mm) ===")
histogram(hfov_vals, bins=8, label="=== 7. HFOV (deg) ===")
histogram(azimuth_vals, bins=12, label="=== 8. Azimuth (deg) ===")

print(f"\n=== 9. Visibility Distribution (num_corners_visible) ===")
vis_counter = Counter(vis_vals)
for v in sorted(vis_counter):
    bar = '#' * int(vis_counter[v] / max(vis_counter.values()) * 40)
    print(f"  vis={v}/8: {vis_counter[v]:5d} ({pct(vis_counter[v])}) {bar}")
print(f"  Mean visible: {statistics.mean(vis_vals):.2f}/8")

print(f"\n=== 10. Occluder Asset Usage ===")
total_occ = sum(occluder_used.values())
print(f"  Total occluder placements: {total_occ}  (fallback rate: {occluder_fallback_count}/{O_count} = {occluder_fallback_count/max(O_count,1)*100:.1f}%)")
for k, v in occluder_used.most_common():
    print(f"  {k:35s} {v:5d} ({pct(v)})")

print(f"\n=== 11. Cargo Asset Usage ===")
print(f"  Total cargo placements: {sum(cargo_assets_used.values())}")
print(f"  Mean cargo items per frame (when used): {statistics.mean(cargo_count_vals):.2f}" if cargo_count_vals else "  N/A")
for k, v in cargo_assets_used.most_common():
    print(f"  {k:35s} {v:5d} ({pct(v)})")

print(f"\n=== 12. Defect Flags ===")
print(f"  vis < 5/8 (학습용 부적합):       {defect_vis_low:5d} ({pct(defect_vis_low)})")
print(f"  occlusion intended but skipped: {defect_occ_ineffective:5d} ({pct(defect_occ_ineffective)})")
print(f"  truncation intended, no clip:   {defect_trunc_no_realize:5d} ({pct(defect_trunc_no_realize)})")
print(f"  occlusion drop>=5 (heavy):      {defect_occ_overkill:5d} ({pct(defect_occ_overkill)})")

# Save numeric summary
summary = {
    "total_frames": N,
    "bg_distribution": dict(bg_count),
    "clock_distribution": dict(clock_count),
    "augmentation": {
        "truncation_pct": T_count/N*100,
        "occlusion_pct": O_count/N*100,
        "cargo_pct": C_count/N*100,
        "T_and_O_pct": TO_count/N*100,
        "T_and_C_pct": TC_count/N*100,
        "O_and_C_pct": OC_count/N*100,
        "T_and_O_and_C_pct": TOC_count/N*100,
        "no_aug_pct": no_aug/N*100,
    },
    "stats": {
        "distance_m": {"mean": statistics.mean(dist_vals), "median": statistics.median(dist_vals), "min": min(dist_vals), "max": max(dist_vals)},
        "height_m": {"mean": statistics.mean(height_vals), "median": statistics.median(height_vals), "min": min(height_vals), "max": max(height_vals)},
        "lens_mm": {"mean": statistics.mean(lens_vals), "median": statistics.median(lens_vals), "min": min(lens_vals), "max": max(lens_vals)},
        "hfov_deg": {"mean": statistics.mean(hfov_vals), "median": statistics.median(hfov_vals), "min": min(hfov_vals), "max": max(hfov_vals)},
        "visibility_mean": statistics.mean(vis_vals),
    },
    "occluder_usage": dict(occluder_used.most_common()),
    "cargo_usage": dict(cargo_assets_used.most_common()),
    "defects": {
        "vis_low_count": defect_vis_low,
        "occ_skipped_when_intended": defect_occ_ineffective,
        "trunc_not_realized": defect_trunc_no_realize,
        "occ_heavy_overkill": defect_occ_overkill,
    },
}
with open(os.path.join(OUT_DIR, "_stats_report.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nReport saved: {os.path.join(OUT_DIR, '_stats_report.json')}")
