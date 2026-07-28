"""v2 occlusion distractor pool: select from the 209 CC0/CC-BY distractor set.

Replaces the legacy hard-coded DISTRACTOR_NAMES (old 8, which included the unknown-
license Sketchfab_model x3) as the SOURCE of occlusion distractors. This module is
pure-python (no bpy import) so the selection logic is unit-testable outside Blender;
Blender-side placement (randomize_distractors) resolves the returned names to the
`Dist_<name>` objects that were appended to the hidden `Distractors_v2` collection
during the 2026-07-24 blend integration.

Selection criteria (task spec): size_class + domain_plausible + scene_preset.
  - scene_preset "indoor" / "outdoor-day" / "outdoor-night"  (80% of frames):
        keep only rows whose dp_<domain> flag is True.
  - scene_preset "random-mix" / None                          (20% of frames):
        the full 209 pool (no domain filter).
  - size_class weighting (SIZE_CLASS_WEIGHTS) biases the draw toward physically
    larger occluders (large/road/medium) so tiny consumer clutter does not dominate
    the sample; all classes stay reachable.

The 209 names come from distractors_manifest.csv (name column). None of them is
`Sketchfab_model` / `Sketchfab_model.001` / `.002`, so those can never be selected by
this path. domain_plausible + fill_ratio columns are produced by
scripts/data_prep/compute_distractor_fill_ratio.py; if they are absent (manifest not
yet enriched) the loader degrades to size-class-only selection with all-domain=True.
"""

import csv
import os

# manifest path comes from the central registry (config/synthetic/pallet_paths.yaml)
# so that relocating data/pallet is a one-line config change, not a code hunt.
import pallet_data_paths as _pdp

_PROJECT_ROOT = _pdp.load().project_root
DEFAULT_MANIFEST = _pdp.get("distractor_manifest")

# Blender object-name prefix used when the 209 were appended (history 2026-07-24).
DIST_OBJ_PREFIX = "Dist_"

# size-class draw weights (folder column). Larger real occluders favoured; every
# class stays reachable. Tunable -- reported in the Phase A note.
SIZE_CLASS_WEIGHTS = {
    "large": 3.0,
    "road": 3.0,
    "medium": 2.0,
    "indoor": 1.0,
    "small": 0.6,
}

_SCENE_PRESET_TO_DOMAIN = {
    "indoor": "dp_indoor",
    "outdoor-day": "dp_outdoor_day",
    "outdoor_day": "dp_outdoor_day",
    "outdoor-night": "dp_outdoor_night",
    "outdoor_night": "dp_outdoor_night",
}

_pool_cache = {}


def _as_bool(v, default=True):
    s = str(v).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return default


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_pool(manifest_path=DEFAULT_MANIFEST):
    """Load the 209 distractor records from the manifest. Cached by path.

    Each record: {name, obj_name, size_class, dp_indoor, dp_outdoor_day,
                  dp_outdoor_night, fill_ratio_mean, fill_ratio_std, source, license}.
    """
    if manifest_path in _pool_cache:
        return _pool_cache[manifest_path]
    records = []
    with open(manifest_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            records.append({
                "name": name,
                "obj_name": DIST_OBJ_PREFIX + name,
                "size_class": (row.get("folder") or "").strip().lower(),
                "source": (row.get("source") or "").strip().lower(),
                "license": (row.get("license") or "").strip(),
                "dp_indoor": _as_bool(row.get("dp_indoor"), True),
                "dp_outdoor_day": _as_bool(row.get("dp_outdoor_day"), True),
                "dp_outdoor_night": _as_bool(row.get("dp_outdoor_night"), True),
                "fill_ratio_mean": _as_float(row.get("fill_ratio_mean")),
                "fill_ratio_std": _as_float(row.get("fill_ratio_std")),
            })
    _pool_cache[manifest_path] = records
    return records


def filter_by_scene_preset(records, scene_preset):
    """Return the domain-plausible subset for a scene_preset.

    'random-mix'/None -> all records; indoor/outdoor-day/outdoor-night -> dp flag."""
    domain_key = _SCENE_PRESET_TO_DOMAIN.get(
        (scene_preset or "").strip().lower().replace(" ", "-")
    )
    if domain_key is None:
        return list(records)  # random-mix / unknown -> full pool
    return [r for r in records if r.get(domain_key, True)]


def select_distractor_object_names(scene_preset, n, rng, manifest_path=DEFAULT_MANIFEST):
    """Pick n distinct `Dist_<name>` object names for one frame.

    scene_preset  indoor | outdoor-day | outdoor-night | random-mix | None
    n             number of distractors to place this frame
    rng           a random.Random (or the random module) providing .choices/.sample
    Returns a list of object names (never contains 'Sketchfab_model*').
    """
    records = load_pool(manifest_path)
    pool = filter_by_scene_preset(records, scene_preset)
    if not pool or n <= 0:
        return []
    n = min(int(n), len(pool))
    weights = [max(1e-6, SIZE_CLASS_WEIGHTS.get(r["size_class"], 1.0)) for r in pool]
    # weighted sampling WITHOUT replacement (draw one at a time, remove).
    chosen, idxs = [], list(range(len(pool)))
    w = list(weights)
    for _ in range(n):
        pick = rng.choices(idxs, weights=w, k=1)[0]
        pos = idxs.index(pick)
        idxs.pop(pos)
        w.pop(pos)
        chosen.append(pool[pick]["obj_name"])
    return chosen


def all_object_names(manifest_path=DEFAULT_MANIFEST):
    """Every `Dist_<name>` in the pool (used to hide the whole set before placing)."""
    return [r["obj_name"] for r in load_pool(manifest_path)]
