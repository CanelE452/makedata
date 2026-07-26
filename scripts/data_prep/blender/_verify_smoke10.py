import os, json, glob
import numpy as np
import cv2

D = r"E:/CODING/GitHub/FoundationPose/data/pallet/_floor_smoke10"
pngs = sorted(glob.glob(os.path.join(D, "[0-9]"*6 + ".png")))

# expected floor dominant-channel signature (rough): which channel should lead, light/dark
FLOOR_HINT = {
    "tile_white":   "bright, near-neutral light",
    "wood_laminate":"warm honey (R>G>B)",
    "tile_brown":   "warm terracotta (R>G>B)",
    "red_brick":    "red/orange (R>>B)",
    "dirt_ground":  "olive-brown",
    "red_earth":    "reddish (R>B)",
    "brick_floor_02":"dark brown",
    "asphalt_02":   "dark grey neutral",
    "concrete_floor_02":"mid grey neutral",
    "cobblestone_floor_08":"light grey",
    "gravel_concrete_02":"light warm grey",
}

def magenta_stats(img):
    # img BGR uint8. Magenta/pink = high R and high B, low G.
    b = img[:,:,0].astype(np.int32); g = img[:,:,1].astype(np.int32); r = img[:,:,2].astype(np.int32)
    # classic decode-fail magenta ~ (255,0,255): r,b high, g low
    mag = (r > 150) & (b > 150) & (g < r - 60) & (g < b - 60)
    frac = mag.mean()*100
    return frac

def floor_patch_color(img):
    # sample bottom strip (foreground floor) avoiding center pallet
    h,w = img.shape[:2]
    strip = img[int(h*0.80):h, :, :]   # bottom 20%
    # also corners of bottom to avoid pallet shadow
    bgr = strip.reshape(-1,3).mean(0)
    return bgr  # B,G,R

print(f"{'frame':6} {'floor_texture':22} {'scene':12} {'hdri':30} {'floorBGR(meanbottom)':24} {'mag%':6} {'#kp':4} {'conn_x':6} {'front_near':10}")
print("-"*150)

rows=[]
mags=[]
for p in pngs:
    fr = os.path.splitext(os.path.basename(p))[0]
    jp = p[:-4]+".json"
    img = cv2.imread(p)
    with open(jp) as f: ann = json.load(f)
    cam = ann.get("camera_data",{})
    objs = ann.get("objects",[])
    o = objs[0] if objs else {}
    floor = cam.get("floor",{}).get("floor_texture")
    hdri = cam.get("hdri_environment","?")
    scene = o.get("source_asset") or o.get("name","?")
    pc = o.get("projected_cuboid")
    kp = len(pc) if pc else None
    conn_x = o.get("edge_connector_crossings")
    fn = o.get("front_is_camera_near")
    bgr = floor_patch_color(img)
    mag = magenta_stats(img)
    mags.append(mag)
    rows.append((fr, floor, scene, hdri, bgr, mag, kp, conn_x, fn))
    print(f"{fr:6} {str(floor):22} {str(scene):12} {str(hdri):30} "
          f"[{bgr[2]:5.0f},{bgr[1]:5.0f},{bgr[0]:5.0f}]      {mag:6.3f} {str(kp):4} {str(conn_x):6} {str(fn):10}")

print("\n=== MAGENTA SCAN (whole image, %% pixels) ===")
print(f"max magenta frac across 10 frames: {max(mags):.4f}%   mean: {np.mean(mags):.4f}%")
print("PASS (0 magenta cast)" if max(mags) < 0.01 else "FAIL: magenta present")

print("\n=== FLOOR TEXTURE DISTRIBUTION ===")
from collections import Counter
c = Counter(r[1] for r in rows)
for k,v in c.items():
    print(f"  {k:22} x{v}   hint={FLOOR_HINT.get(k,'?')}")
print(f"  distinct floors in 10 frames: {len(c)}")
