import os, glob, json
import numpy as np
import cv2

D = r"E:/CODING/GitHub/FoundationPose/data/pallet/_floor_smoke10"
OV = os.path.join(D, "overlay")
pngs = sorted(glob.glob(os.path.join(D, "[0-9]"*6 + ".png")))

def label(img, txt):
    img = img.copy()
    cv2.rectangle(img, (0,0), (img.shape[1], 34), (0,0,0), -1)
    cv2.putText(img, txt, (8,24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0,255,255), 2)
    return img

cell = 480
def fit(img):
    h,w = img.shape[:2]
    s = cell/float(w)
    return cv2.resize(img,(cell,int(h*s)))

# two sheets: raw (floor visibility) and overlay (labels)
for kind, src_dir in [("raw", D), ("overlay", OV)]:
    cells=[]
    for p in pngs:
        fr = os.path.splitext(os.path.basename(p))[0]
        jp = os.path.join(D, fr+".json")
        ann = json.load(open(jp))
        floor = ann["camera_data"]["floor"]["floor_texture"]
        sp = os.path.join(src_dir, fr+".png")
        img = cv2.imread(sp)
        img = fit(label(img, f"{fr} {floor}"))
        cells.append(img)
    # pad to multiple of 5
    while len(cells)%5: cells.append(np.zeros_like(cells[0]))
    rows=[np.hstack(cells[i:i+5]) for i in range(0,len(cells),5)]
    sheet=np.vstack(rows)
    out=os.path.join(D, f"_sheet_{kind}.jpg")
    cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("saved", out, sheet.shape)
