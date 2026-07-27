"""Camera/sensor post-effects for the RGB render (real D435i appearance gap).

Applied to the RGB image only (mask png / keypoints unaffected). Overwrites the PNG
in place. Call AFTER the holdout mask render and BEFORE overlay drawing so the
overlay is drawn on the final post-processed image.

Two modes:

``tier=None``  LEGACY mode — the exact pre-Phase-3 behaviour (every effect drawn
               independently, sensor sigma globally scaled by ``noise_scale``).
               Kept bit-exact for the legacy production generators
               (``gen_trunc_addon.py``, ``gen_4pallet_mask.py``) and the v2
               diagnostic drivers that already shipped datasets with it.

``tier=...``   TIERED mode (v2 Phase 3) — one degradation tier is drawn per frame
               from :data:`NOISE_TIER_FRAC`; the tier decides *which* effects run
               and the (non-overlapping) band each strength is drawn from.  A
               ``clean`` frame gets no sensor noise, no blur and no JPEG
               re-compression at all, so the dataset keeps a majority of sharp
               frames instead of degrading every single one.

Both modes return a dict of the values that were ACTUALLY applied, so the label /
record can carry the degradation as metadata instead of it being invisible.
"""
import io
import numpy as np
from PIL import Image, ImageFilter


# ---------------------------------------------------------------------------
# CONFIG (tier selection + per-tier strength bands)
# ---------------------------------------------------------------------------
# Tier mixture. [미검증 시작값] — chosen so the majority of the set stays sharp
# (clean) while a thin tail carries heavy sensor degradation for robustness.
NOISE_TIER_LABELS = ("clean", "low", "medium", "high")
NOISE_TIER_FRAC = (0.60, 0.25, 0.12, 0.03)

# Per-tier effect probabilities and strength bands.  The gaussian-sigma bands are
# deliberately NON-OVERLAPPING ([0], [1,3), [3,6), [6,12]) so `noise_tier` alone
# identifies the sigma regime of a frame in the EDA.  [미검증 시작값]
NOISE_TIER_PARAMS = {
    "clean": {
        "wb_gain": (0.98, 1.02),
        "vignette_p": 0.50, "vignette": (0.03, 0.10),
        "blur_p": 0.0, "blur": None,
        "noise_p": 0.0, "sigma": None,
        "jpeg_p": 0.0, "jpeg": None,
    },
    "low": {
        "wb_gain": (0.96, 1.04),
        "vignette_p": 0.70, "vignette": (0.05, 0.18),
        "blur_p": 0.15, "blur": (0.3, 0.6),
        "noise_p": 1.0, "sigma": (1.0, 3.0),
        "jpeg_p": 0.35, "jpeg": (88, 97),
    },
    "medium": {
        "wb_gain": (0.94, 1.06),
        "vignette_p": 0.80, "vignette": (0.10, 0.25),
        "blur_p": 0.40, "blur": (0.6, 1.2),
        "noise_p": 1.0, "sigma": (3.0, 6.0),
        "jpeg_p": 0.70, "jpeg": (78, 88),
    },
    "high": {
        "wb_gain": (0.92, 1.08),
        "vignette_p": 0.90, "vignette": (0.18, 0.35),
        "blur_p": 0.60, "blur": (1.2, 2.0),
        "noise_p": 1.0, "sigma": (6.0, 12.0),
        "jpeg_p": 0.90, "jpeg": (60, 78),
    },
}

# How far a pitch-black frame may push the sensor sigma toward the TOP of its own
# tier band (0 = no dark scaling, 1 = pitch-black always lands at the band max).
# The push is applied inside the band, so it can never cross a tier boundary.
DARK_SIGMA_PUSH = 0.5


def _rng(seed):
    return np.random.default_rng(int(seed) * 2654435761 % (2**32))


def _tier_rng(seed):
    """Independent stream for tier selection: keeps the effect stream identical in
    structure to the legacy one (only the tier draw is new)."""
    return np.random.default_rng((int(seed) * 40503 + 0x9E3779B9) % (2**32))


def choose_tier(seed, probs=NOISE_TIER_FRAC, labels=NOISE_TIER_LABELS):
    """Deterministic per-frame tier draw from the configured mixture."""
    weights = np.asarray(probs, dtype=np.float64)
    weights = weights / weights.sum()
    index = int(_tier_rng(seed).choice(len(labels), p=weights))
    return labels[index]


def _empty_effects(tier):
    return {
        "noise_tier": tier,
        "wb_gain_rgb": None,
        "vignette_applied": False,
        "vignette_strength": None,
        "blur_applied": False,
        "blur_radius_px": None,
        "gaussian_noise_applied": False,
        "gaussian_sigma": None,
        "jpeg_applied": False,
        "jpeg_quality": None,
    }


def apply(img_path, seed, noise_scale=1.0, tier=None, dark_factor=0.0):
    """Apply the sensor post-effects to ``img_path`` in place.

    tier=None            -> legacy behaviour (bit-exact), ``noise_scale`` scales sigma globally.
    tier="auto"          -> draw a tier from NOISE_TIER_FRAC using ``seed``.
    tier in NOISE_TIER_LABELS -> use that tier.

    ``dark_factor`` in [0,1] (tiered mode only) pushes the sensor sigma toward the top
    of the SELECTED TIER's band; it never moves a frame to another tier.

    Returns a dict of the values actually applied.
    """
    if tier is None:
        return _apply_legacy(img_path, seed, noise_scale)
    if tier == "auto":
        tier = choose_tier(seed)
    if tier not in NOISE_TIER_PARAMS:
        raise ValueError(f"unknown noise tier: {tier!r}")
    return _apply_tiered(img_path, seed, tier, dark_factor)


def _apply_legacy(img_path, seed, noise_scale=1.0):
    """Pre-Phase-3 behaviour, unchanged. noise_scale (>=1) raises the sensor read-noise
    sigma for dark frames (v2 Illumination DR)."""
    rng = _rng(seed)
    img = Image.open(img_path).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    H, W = arr.shape[:2]
    effects = _empty_effects("legacy")

    # 1) white balance / color cast (auto-WB drift, per-channel gain)
    gain = rng.uniform(0.92, 1.08, 3)
    arr *= gain
    effects["wb_gain_rgb"] = [float(g) for g in gain]

    # 2) vignette (lens radial falloff)
    if rng.random() < 0.7:
        yy, xx = np.mgrid[0:H, 0:W]
        cx, cy = W / 2.0, H / 2.0
        r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.sqrt(cx * cx + cy * cy)
        strength = rng.uniform(0.10, 0.35)
        arr *= (1.0 - strength * (r ** 2))[..., None]
        effects["vignette_applied"] = True
        effects["vignette_strength"] = float(strength)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 3) defocus / motion blur (occasional, mild)
    if rng.random() < 0.30:
        radius = rng.uniform(0.5, 1.8)
        img = img.filter(ImageFilter.GaussianBlur(radius))
        effects["blur_applied"] = True
        effects["blur_radius_px"] = float(radius)

    # 4) sensor noise (gaussian read noise); sigma scaled up for dark frames.
    arr = np.asarray(img).astype(np.float32)
    if rng.random() < 0.75:
        sigma = rng.uniform(2.0, 8.0) * float(noise_scale)
        arr += rng.normal(0.0, sigma, arr.shape)
        effects["gaussian_noise_applied"] = True
        effects["gaussian_sigma"] = float(sigma)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 5) JPEG (stream) compression artifacts
    if rng.random() < 0.6:
        quality = int(rng.uniform(70, 95))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        effects["jpeg_applied"] = True
        effects["jpeg_quality"] = quality

    img.save(img_path, format="PNG")
    return effects


def _apply_tiered(img_path, seed, tier, dark_factor=0.0):
    params = NOISE_TIER_PARAMS[tier]
    rng = _rng(seed)
    img = Image.open(img_path).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    H, W = arr.shape[:2]
    effects = _empty_effects(tier)
    dark = min(1.0, max(0.0, float(dark_factor)))

    # 1) white balance / colour cast (always on, tier-scaled amplitude)
    lo, hi = params["wb_gain"]
    gain = rng.uniform(lo, hi, 3)
    arr *= gain
    effects["wb_gain_rgb"] = [float(g) for g in gain]

    # 2) vignette (lens radial falloff)
    if params["vignette_p"] > 0.0 and rng.random() < params["vignette_p"]:
        yy, xx = np.mgrid[0:H, 0:W]
        cx, cy = W / 2.0, H / 2.0
        r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.sqrt(cx * cx + cy * cy)
        strength = float(rng.uniform(*params["vignette"]))
        arr *= (1.0 - strength * (r ** 2))[..., None]
        effects["vignette_applied"] = True
        effects["vignette_strength"] = strength

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 3) defocus / motion blur
    if params["blur_p"] > 0.0 and rng.random() < params["blur_p"]:
        radius = float(rng.uniform(*params["blur"]))
        img = img.filter(ImageFilter.GaussianBlur(radius))
        effects["blur_applied"] = True
        effects["blur_radius_px"] = radius

    # 4) sensor read noise, sigma drawn INSIDE the tier band.  A dark frame biases
    #    the draw toward the band top (never out of the band).
    if params["noise_p"] > 0.0 and rng.random() < params["noise_p"]:
        s_lo, s_hi = params["sigma"]
        frac = float(rng.random())
        frac = frac + (1.0 - frac) * dark * DARK_SIGMA_PUSH
        sigma = float(s_lo + (s_hi - s_lo) * frac)
        arr = np.asarray(img).astype(np.float32)
        arr += rng.normal(0.0, sigma, arr.shape)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        effects["gaussian_noise_applied"] = True
        effects["gaussian_sigma"] = sigma

    # 5) JPEG (stream) compression artifacts
    if params["jpeg_p"] > 0.0 and rng.random() < params["jpeg_p"]:
        q_lo, q_hi = params["jpeg"]
        quality = int(rng.integers(int(q_lo), int(q_hi) + 1))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        effects["jpeg_applied"] = True
        effects["jpeg_quality"] = quality

    img.save(img_path, format="PNG")
    return effects
