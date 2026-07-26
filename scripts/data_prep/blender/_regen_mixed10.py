"""Mixed scene_1/2/3 regen (default v4 weights) to confirm fix in context."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_dataset_v4 as G
sys.argv = ["blender", "--",
            "--split", "train",
            "--start_idx", "0",
            "--num_frames", "10",
            "--seed", "16062026",
            "--out_dir", "data/pallet/_mat_test10d",
            "--overlay_every", "1"]
G.main()
