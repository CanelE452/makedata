"""Mask OUTPUT profiles for the v2 constrained pipeline (bpy-free).

A profile decides which holdout masks a run keeps on disk, and therefore which occlusion
fractions can be measured at all.

``full-audit`` (default, unchanged 500-record diagnostic behaviour)
    The source-separated sequence M0..M4 is rendered and kept::

        <out>/mask/fNNNN_m0.png   target only          (amodal silhouette)
        <out>/mask/fNNNN_m1.png   after static
        <out>/mask/fNNNN_m2.png   after static+cargo
        <out>/mask/fNNNN_m3.png   after static+cargo+context
        <out>/mask/fNNNN_m4.png   final visible

    f_static / f_cargo / f_context / f_explicit are EXACT.

``public`` (training / publication sets)
    Only the two masks such a set needs, under readable names::

        <out>/mask_amodal/fNNNN.png    (M0)
        <out>/mask_visible/fNNNN.png   (M4)

    M1..M3 are NOT RENDERED (three fewer holdout passes per frame), so the per-source
    fractions are NOT MEASURED and are reported as ``None`` - never 0.0, never a low-res
    approximation.  ``f_total`` stays EXACT because M0 and M4 alone determine it.

Nothing here imports bpy, so both the Blender runner and the offline audit/EDA tools share
one definition of "where does mask X of frame N live".
"""

from __future__ import annotations

import os

import scene_placement_v2 as SP2


FULL_AUDIT = "full-audit"
PUBLIC = "public"
MASK_PROFILES = (FULL_AUDIT, PUBLIC)
DEFAULT_MASK_PROFILE = FULL_AUDIT

AMODAL_STAGE = "m0"
VISIBLE_STAGE = "m4"

_STAGES = {
    FULL_AUDIT: ("m0", "m1", "m2", "m3", "m4"),
    PUBLIC: (AMODAL_STAGE, VISIBLE_STAGE),
}
# stage -> (sub directory under the run dir, file-name suffix appended to the frame stem)
_LAYOUT = {
    FULL_AUDIT: {name: ("mask", "_%s.png" % name) for name in _STAGES[FULL_AUDIT]},
    PUBLIC: {
        AMODAL_STAGE: ("mask_amodal", ".png"),
        VISIBLE_STAGE: ("mask_visible", ".png"),
    },
}
# Which scene component removes target pixels on each transition of a profile's stage list.
_STAGE_OCCLUDER_SOURCE = {
    FULL_AUDIT: {"m1": "static", "m2": "cargo", "m3": "context", "m4": "explicit"},
    # public collapses every source into the single M0 -> M4 transition, so no individual
    # source can be attributed to it.
    PUBLIC: {VISIBLE_STAGE: "all"},
}
SOURCE_FRACTION_KEYS = ("f_static", "f_cargo", "f_context", "f_explicit")
# Which scene groups are HIDDEN while a stage is rendered.  "all_nonpallet" hides every
# non-target mesh (M0 = amodal silhouette); an empty tuple hides nothing (M4 = final visible).
# The renderer resolves these names to Blender objects; keeping the plan here is what makes
# "public renders two passes, not five" checkable without bpy.
STAGE_HIDDEN_GROUPS = {
    "m0": ("all_nonpallet",),
    "m1": ("cargo", "context", "explicit"),
    "m2": ("context", "explicit"),
    "m3": ("explicit",),
    "m4": (),
}


def normalize_profile(profile):
    """Return a valid profile name.  ``None`` means "caller did not choose" -> default."""
    if profile is None:
        return DEFAULT_MASK_PROFILE
    name = str(profile)
    if name not in MASK_PROFILES:
        raise ValueError(
            f"unknown mask profile {profile!r} (expected one of {list(MASK_PROFILES)})"
        )
    return name


def mask_stages(profile=None):
    """Holdout stages this profile renders AND keeps, in occlusion order."""
    return _STAGES[normalize_profile(profile)]


def mask_dirnames(profile=None):
    """Run-dir subdirectories this profile writes masks into (creation order)."""
    layout = _LAYOUT[normalize_profile(profile)]
    seen = []
    for stage in mask_stages(profile):
        dirname = layout[stage][0]
        if dirname not in seen:
            seen.append(dirname)
    return tuple(seen)


def holdout_passes(profile, hide_groups):
    """((stage, objects to hide), ...) - exactly the holdout passes this profile renders.

    ``hide_groups`` maps the group names of STAGE_HIDDEN_GROUPS to the scene objects they
    stand for.  public yields two passes, so M1..M3 are never rendered at all (not rendered
    and then deleted): three fewer full-resolution passes per frame.
    """
    return tuple(
        (
            stage,
            [obj for name in STAGE_HIDDEN_GROUPS[stage] for obj in hide_groups[name]],
        )
        for stage in mask_stages(profile)
    )


def stage_occluder_source(profile=None):
    """stage -> the occlusion source that the previous stage's transition removed."""
    return dict(_STAGE_OCCLUDER_SOURCE[normalize_profile(profile)])


def occlusion_decomposition_available(profile=None):
    """True when the per-source fractions (f_static/f_cargo/f_context/f_explicit) are exact."""
    return normalize_profile(profile) == FULL_AUDIT


def frame_stem(idx):
    return f"f{int(idx):04d}"


def frame_mask_paths(out_dir, idx, profile=None):
    """{stage: path} for one frame under ``out_dir`` (the run dir, not the mask dir)."""
    profile = normalize_profile(profile)
    layout = _LAYOUT[profile]
    stem = frame_stem(idx)
    return {
        stage: os.path.join(str(out_dir), layout[stage][0], stem + layout[stage][1])
        for stage in _STAGES[profile]
    }


def mask_paths_from_prefix(prefix, profile=None):
    """{stage: path} derived from the legacy ``<out>/mask/fNNNN`` prefix.

    full-audit keeps the historical ``<prefix>_mN.png`` names byte for byte; public resolves
    the run dir from the prefix (``<out>/mask/fNNNN`` -> ``<out>``) and writes the readable
    two-file layout.  Kept so callers that only carry ``rs['mask_prefix']`` still work.
    """
    profile = normalize_profile(profile)
    prefix = str(prefix)
    layout = _LAYOUT[profile]
    if profile == FULL_AUDIT:
        return {stage: prefix + layout[stage][1] for stage in _STAGES[profile]}
    stem = os.path.basename(prefix)
    out_dir = os.path.dirname(os.path.dirname(prefix))
    return {
        stage: os.path.join(out_dir, layout[stage][0], stem + layout[stage][1])
        for stage in _STAGES[profile]
    }


def detect_profile(root):
    """Guess the profile of an EXISTING run dir from the directories it actually has."""
    root = str(root)
    public_dirs = mask_dirnames(PUBLIC)
    if all(os.path.isdir(os.path.join(root, name)) for name in public_dirs):
        return PUBLIC
    return FULL_AUDIT


def resolve_frame_mask_path(root, idx, stage=AMODAL_STAGE):
    """Compatibility lookup: where does mask ``stage`` of frame ``idx`` live in ``root``?

    Checks every profile layout and returns the first path that EXISTS, so a reader does not
    need to know how the set was produced.  When nothing exists it returns the path the
    detected profile would use, which keeps "missing file" reporting intact.
    """
    for profile in MASK_PROFILES:
        if stage not in _STAGES[profile]:
            continue
        path = frame_mask_paths(root, idx, profile)[stage]
        if os.path.isfile(path):
            return path
    profile = detect_profile(root)
    if stage in _STAGES[profile]:
        return frame_mask_paths(root, idx, profile)[stage]
    # Legacy/explicit suffix outside every profile (e.g. the pre-M0..M4 unocc/visible names).
    return os.path.join(str(root), "mask", f"{frame_stem(idx)}_{stage}.png")


def _full_audit_decomposition(areas):
    a0, a1, a2, a3, a4 = (float(areas[stage]) for stage in _STAGES[FULL_AUDIT])
    invariant = SP2.validate_mask_decomposition(a0, a1, a2, a3, a4)
    if invariant["valid"]:
        decomposition = SP2.decompose_mask_areas(a0, a1, a2, a3, a4)
    else:
        # Preserve the observed areas for diagnosis instead of dropping the frame's numbers.
        base = a0
        decomposition = {
            "mask_area_target_only": a0,
            "mask_area_after_static": a1,
            "mask_area_after_cargo": a2,
            "mask_area_after_context": a3,
            "mask_area_visible": a4,
            "f_static": (float(a0 - a1) / base) if base else None,
            "f_cargo": (float(a1 - a2) / base) if base else None,
            "f_context": (float(a2 - a3) / base) if base else None,
            "f_explicit": (float(a3 - a4) / base) if base else None,
            "f_total": (float(a0 - a4) / base) if base else None,
            "occlusion_decomposition_order": ["M0", "M1", "M2", "M3", "M4"],
        }
    decomposition["mask_area_amodal"] = a0
    return decomposition, invariant


def _public_invariant(a0, a4, tol=1e-9):
    """The only invariant two masks can carry: a non-empty M0 that contains M4."""
    errors = []
    if a0 <= tol:
        errors.append("mask_area_target_only must be greater than tol")
    if a0 < -tol or a4 < -tol:
        errors.append("mask areas must be nonnegative")
    if a4 > a0 + tol:
        errors.append("mask areas must be monotonic M0 >= M4")
    return {"valid": not errors, "errors": errors}


def _public_decomposition(areas, tol=1e-9):
    a0 = float(areas[AMODAL_STAGE])
    a4 = float(areas[VISIBLE_STAGE])
    invariant = _public_invariant(a0, a4, tol=tol)
    decomposition = {
        "mask_area_target_only": a0,
        "mask_area_amodal": a0,
        # M1..M3 were never rendered: NOT MEASURED, not zero.
        "mask_area_after_static": None,
        "mask_area_after_cargo": None,
        "mask_area_after_context": None,
        "mask_area_visible": a4,
        "f_static": None,
        "f_cargo": None,
        "f_context": None,
        "f_explicit": None,
        # exact: M0 and M4 alone determine the total occluded fraction.
        "f_total": (1.0 - a4 / a0) if a0 > 0.0 else None,
        "occlusion_decomposition_order": ["M0", "M4"],
    }
    return decomposition, invariant


def decompose(areas, profile=None, tol=1e-9):
    """(decomposition, invariant) for the measured stage areas of one frame.

    ``areas`` maps stage -> foreground pixel count and must hold exactly the stages of
    ``profile``.  full-audit reproduces the historical M0..M4 decomposition (SP2 validated,
    with the observed-area fallback); public fills the unmeasurable per-source fractions with
    ``None`` and keeps f_total exact.
    """
    profile = normalize_profile(profile)
    missing = [stage for stage in _STAGES[profile] if stage not in (areas or {})]
    if missing:
        raise KeyError(
            f"mask profile {profile!r} needs areas for {list(_STAGES[profile])}, missing {missing}"
        )
    if profile == PUBLIC:
        return _public_decomposition(areas, tol=tol)
    return _full_audit_decomposition(areas)
