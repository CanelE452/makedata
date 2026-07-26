"""Force-Pallet_3 regen to verify the aged_brown fix (no teal/cold-gray)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_dataset_v4 as G

# Force scene_3 only (Pallet_3). Weights index = [P0,P1,P2,P3].
G.cfg.PALLET_WEIGHTS = [0.0, 0.0, 0.0, 1.0]

# Build argv for G.main()'s parse_args (after "--")
sys.argv = ["blender", "--",
            "--split", "train",
            "--start_idx", "0",
            "--num_frames", "6",
            "--seed", "20260616",
            "--out_dir", "data/pallet/_mat_test10d_scene3",
            "--overlay_every", "1"]
G.main()
