"""Camera/sensor post-effects for add-on render (real D435i appearance gap).

Applied to the RGB image only (mask png / keypoints unaffected). General ranges,
not over-randomized: white balance / color cast, vignette, slight defocus/motion
blur, sensor noise, JPEG (stream) compression. Overwrites the PNG in place.

Call AFTER the holdout mask render and BEFORE overlay drawing so the overlay is
drawn on the final post-processed image.
"""
import io
import numpy as np
from PIL import Image, ImageFilter


def apply(img_path, seed, noise_scale=1.0):
    """noise_scale (>=1) raises the sensor read-noise sigma for dark frames (v2
    Illumination DR). Default 1.0 = legacy behaviour (callers passing only (path, seed)
    are unaffected)."""
    rng = np.random.default_rng(int(seed) * 2654435761 % (2**32))
    img = Image.open(img_path).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    H, W = arr.shape[:2]

    # 1) white balance / color cast (auto-WB drift, per-channel gain)
    arr *= rng.uniform(0.92, 1.08, 3)

    # 2) vignette (lens radial falloff)
    if rng.random() < 0.7:
        yy, xx = np.mgrid[0:H, 0:W]
        cx, cy = W / 2.0, H / 2.0
        r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.sqrt(cx * cx + cy * cy)
        arr *= (1.0 - rng.uniform(0.10, 0.35) * (r ** 2))[..., None]

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 3) defocus / motion blur (occasional, mild)
    if rng.random() < 0.30:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.8)))

    # 4) sensor noise (gaussian read noise); sigma scaled up for dark frames.
    arr = np.asarray(img).astype(np.float32)
    if rng.random() < 0.75:
        arr += rng.normal(0.0, rng.uniform(2.0, 8.0) * float(noise_scale), arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 5) JPEG (stream) compression artifacts
    if rng.random() < 0.6:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(rng.uniform(70, 95)))
        buf.seek(0)
        img = Image.open(buf).convert("RGB")

    img.save(img_path, format="PNG")
