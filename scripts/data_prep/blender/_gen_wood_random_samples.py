"""Random-applied wood-skin samples: run the v4 preview pipeline but force the
wood pallets (scene_2 + scene_3) so each frame draws a random wood skin from the
new 11-variant pool.  Confirms diverse skins + correct 0123 labels + grounding.

Run (headless, separate process):
  blender -b data/pallet/blender_scene/synth_data_scene.blend \
     --python scripts/data_prep/blender/_gen_wood_random_samples.py

Outputs: data/pallet/_wood_skin_compare/random_applied/{images,overlay,json}/
(training_data_v4_split is NOT touched.)
"""
import os
import sys

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

# Import the full v4 preview module, then retarget its outputs + pallet pool to
# wood-only and render a handful of frames.
import gen_preview10 as P
import blender_config as cfg
import randomizers

# wood pallets only: Pallet_2 (scene_2) + Pallet_3 (scene_3)
cfg.PALLET_WEIGHTS = [0.0, 0.0, 0.5, 0.5]
randomizers.PALLET_WEIGHTS = cfg.PALLET_WEIGHTS

# redirect outputs so we never touch _preview10 or any training split
OUT_BASE = os.path.join(cfg.PROJECT_ROOT, "data", "pallet", "_wood_skin_compare", "random_applied")
P.OUT_BASE = OUT_BASE
P.IMG_DIR = os.path.join(OUT_BASE, "images")
P.JSON_DIR = os.path.join(OUT_BASE, "json")
P.OV_DIR = os.path.join(OUT_BASE, "overlay")
P.CROP_DIR = os.path.join(OUT_BASE, "_crop")
P.N_SAMPLES = 8


def main():
    # different seed than preview so we get fresh skin draws
    np.random.seed(20260616)
    import random
    random.seed(20260616)
    for d in (P.IMG_DIR, P.JSON_DIR, P.OV_DIR, P.CROP_DIR):
        os.makedirs(d, exist_ok=True)
    P.main()


if __name__ == "__main__":
    main()
