import numpy as np
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/pallet/test_fix_axis/000001.json"
with open(path) as f:
    data = json.load(f)

obj = data["objects"][0]
c = np.array(obj["cuboid"])
R = np.array(obj["pose_transform"])[:3, :3]

e01 = c[1] - c[0]
e03 = c[3] - c[0]
e04 = c[4] - c[0]

print(f"=== {path} ===")
print(f"0->1: {e01}  len={np.linalg.norm(e01):.3f}m (medium, should be +x)")
print(f"0->3: {e03}  len={np.linalg.norm(e03):.3f}m (long, should be -y)")
print(f"0->4: {e04}  len={np.linalg.norm(e04):.3f}m (height, should be -z)")

print(f"\nPose R columns (canonical axes in camera):")
print(f"  R[:,0] X/med:    {R[:,0]}")
print(f"  R[:,1] Y/long:   {R[:,1]}")
print(f"  R[:,2] Z/height: {R[:,2]}")

top_z = np.mean([c[i][2] for i in [0,1,2,3]])
bot_z = np.mean([c[i][2] for i in [4,5,6,7]])
print(f"\nTop face (0-1-2-3) mean Z: {top_z:.3f}")
print(f"Bot face (4-5-6-7) mean Z: {bot_z:.3f}")
print(f"Top > Bot (cargo face = 0-1-2-3): {top_z > bot_z}")

# Check: R[:,0] should be parallel to 0->1 in camera coords
# cuboid is in world coords, so we need R_w2c to transform
# Instead, check cross(0->1, 0->3) direction vs 0->4
cross_01_03 = np.cross(e01, e03)
cross_dir = cross_01_03 / np.linalg.norm(cross_01_03)
e04_dir = e04 / np.linalg.norm(e04)
rhr = np.dot(cross_dir, e04_dir)
print(f"\ncross(0->1, 0->3) . (0->4) = {rhr:.3f} (should be ~-1 for right-hand rule with +x,-y,-z)")

# Parallel edges
e12 = c[2] - c[1]; e32 = c[2] - c[3]
cos_03_12 = np.dot(e03, e12) / (np.linalg.norm(e03) * np.linalg.norm(e12))
cos_01_32 = np.dot(e01, e32) / (np.linalg.norm(e01) * np.linalg.norm(e32))
print(f"\nParallel check:")
print(f"  1->2 || 0->3: cos={cos_03_12:.4f}")
print(f"  3->2 || 0->1: cos={cos_01_32:.4f}")
