"""Build before/after contact sheets from _material_compare PNGs (PIL only)."""
import os
import glob
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "..", "data", "pallet", "_material_compare")
BASE = os.path.abspath(BASE)

PALETTES = ["current", "woodA", "mixedB", "wood_drC"]
PALLETS = ["Pallet_1", "Pallet_2", "Pallet_3"]
SRC = {"Pallet_1": "scene_1 (plastic)", "Pallet_2": "scene_2 (wood)",
       "Pallet_3": "scene_3 (wood)"}

try:
    FONT = ImageFont.truetype("arial.ttf", 16)
    FBIG = ImageFont.truetype("arial.ttf", 20)
except Exception:
    FONT = ImageFont.load_default()
    FBIG = FONT

CELL = (320, 240)
PAD = 6
LABEL_H = 26


def cell_for(pallet, palette):
    files = sorted(glob.glob(os.path.join(BASE, f"{pallet}_{palette}_*.png")))
    if not files:
        return None
    # take first variant as representative
    return files[0]


def labeled(path, label):
    img = Image.open(path).convert("RGB").resize(CELL)
    canvas = Image.new("RGB", (CELL[0], CELL[1] + LABEL_H), (30, 30, 30))
    canvas.paste(img, (0, LABEL_H))
    d = ImageDraw.Draw(canvas)
    d.text((4, 4), label, fill=(255, 255, 255), font=FONT)
    return canvas


def per_pallet_sheet(pallet):
    cells = []
    for pal in PALETTES:
        f = cell_for(pallet, pal)
        if f:
            tag = "BEFORE" if pal == "current" else pal
            cells.append(labeled(f, f"{tag}"))
    if not cells:
        return
    w = sum(c.width for c in cells) + PAD * (len(cells) + 1)
    h = cells[0].height + PAD * 2 + 24
    sheet = Image.new("RGB", (w, h), (15, 15, 15))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 4), f"{pallet}  [{SRC[pallet]}]   (left=current/before, rest=candidates)",
           fill=(255, 230, 120), font=FBIG)
    x = PAD
    for c in cells:
        sheet.paste(c, (x, 28))
        x += c.width + PAD
    out = os.path.join(BASE, f"_sheet_{pallet}.png")
    sheet.save(out)
    print(f"[sheet] {out}")


def woodA_variants_sheet():
    """Show the variation within the recommended woodA / wood_drC palette."""
    for pallet in PALLETS:
        for pal in ("woodA", "wood_drC"):
            files = sorted(glob.glob(os.path.join(BASE, f"{pallet}_{pal}_*.png")))
            if len(files) < 2:
                continue
            cells = [labeled(f, os.path.basename(f).replace(".png", "").split("_", 2)[-1])
                     for f in files]
            w = sum(c.width for c in cells) + PAD * (len(cells) + 1)
            h = cells[0].height + 28 + PAD
            sheet = Image.new("RGB", (w, h), (15, 15, 15))
            d = ImageDraw.Draw(sheet)
            d.text((PAD, 4), f"{pallet} {pal} variation", fill=(255, 230, 120), font=FBIG)
            x = PAD
            for c in cells:
                sheet.paste(c, (x, 28))
                x += c.width + PAD
            out = os.path.join(BASE, f"_var_{pallet}_{pal}.png")
            sheet.save(out)
            print(f"[var] {out}")


def main():
    for p in PALLETS:
        per_pallet_sheet(p)
    woodA_variants_sheet()


if __name__ == "__main__":
    main()
