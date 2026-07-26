# monkeypatch test: run gen with floor forced to pure red emission
import os, sys
sys.argv=['gen','--','--split','train','--start_idx','0','--num_frames','3','--seed','909',
          '--out_dir','data/pallet/_floor_emit','--flat_out','--overlay_every','0']
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import randomizers as R
_orig=R._build_floor_material
def patched(mat,name,uv,tint):
    mat.use_nodes=True; nt=mat.node_tree; nt.nodes.clear()
    out=nt.nodes.new("ShaderNodeOutputMaterial"); em=nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value=(1,0,0,1); em.inputs["Strength"].default_value=1.0
    nt.links.new(em.outputs["Emission"],out.inputs["Surface"])
R._build_floor_material=patched
import gen_dataset_v4
gen_dataset_v4.main()
