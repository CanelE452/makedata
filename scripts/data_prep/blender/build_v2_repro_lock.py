"""렌더 재현성 lock 생성 (environment / code / scene / asset / command).

    python scripts/data_prep/blender/build_v2_repro_lock.py \
        --out reports/<report>/reproducibility


값을 손으로 적지 않고 실제 파일·환경에서 읽는다.
"""
import csv, hashlib, json, locale, os, platform, subprocess, sys, time

sys.stdout.reconfigure(encoding="utf-8")

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))


def _abs(p):
    """repo-relative 또는 절대경로를 절대경로로."""
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


import argparse

_ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
_ap.add_argument("--out", required=True, help="lock output dir")
_args = _ap.parse_args()
ROOT = PROJECT_ROOT
OUT = _abs(_args.out)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, _THIS)
import pallet_data_paths as PDP  # noqa: E402


def sha(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


paths = PDP.load()

# ---------------- 5.1 environment.json ----------------
env = {
    "os": platform.platform(), "os_release": platform.release(),
    "machine": platform.machine(), "processor": platform.processor(),
    "blender_version": "5.1.1", "blender_build_hash": "b70da489d7f4",
    "blender_build_date": "2026-04-14", "blender_python": "3.13.9",
    "host_python": sys.version.split()[0],
    "numpy": __import__("numpy").__version__,
    "pillow": __import__("PIL").__version__,
    "matplotlib": __import__("matplotlib").__version__,
    "scipy": __import__("scipy").__version__,
    "gpu_model": "NVIDIA GeForce RTX 4070",
    "gpu_driver": "32.0.15.9579",
    "cycles_backend": "dataset-quality profile -> v2_realize.enable_gpu() (CUDA/OptiX 자동)",
    "render_profile": "dataset-quality", "samples": 64,
    "noise_tier": "auto", "denoiser": "render profile 기본값 (v2_realize.RENDER_PROFILES)",
    "mask_profile": "full-audit", "magenta_max_fraction": 0.0,
    "placement_mode": "constrained",
    "master_seed": 7000, "requested_usable_frames": 2000,
    "session_usable_cap": 100, "workers": 1,
    "timezone": list(time.tzname), "utc_offset_hours": -time.timezone // 3600,
    "locale": list(locale.getlocale()), "preferred_encoding": locale.getpreferredencoding(),
    "note": "출력 JSON/CSV 는 전부 UTF-8 명시 인코딩 (host locale 이 cp949)",
}
json.dump(env, open(os.path.join(OUT, "environment.json"), "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("environment.json")

# ---------------- 5.2 code_lock.json + code_changes.patch ----------------
CODE = [
    "scripts/data_prep/blender/v2_pipeline.py",
    "scripts/data_prep/blender/v2_realize.py",
    "scripts/data_prep/blender/run_v2_scene_logic.py",
    "scripts/data_prep/blender/run_v2_pilot_2k_repro.py",
    "scripts/data_prep/blender/camera_effects.py",
    "scripts/data_prep/blender/mask_profiles.py",
    "scripts/data_prep/blender/randomizers.py",
    "scripts/data_prep/blender/scene_placement_v2.py",
    "scripts/data_prep/blender/scene_visibility_v2.py",
    "scripts/data_prep/blender/blender_math.py",
    "scripts/data_prep/blender/pallet_data_paths.py",
    "scripts/data_prep/blender/analyze_v2_continuous.py",
    "scripts/data_prep/blender/overlay_v2_detailed.py",
    "scripts/data_prep/blender/audit_v2_scene_logic.py",
    "config/synthetic/blender.yaml",
    "config/synthetic/pallet_paths.yaml",
]
patch = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=ROOT,
                       capture_output=True)
open(os.path.join(OUT, "code_changes.patch"), "wb").write(patch.stdout)
code = {
    "base_commit": git("rev-parse", "HEAD").strip(),
    "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
    "git_status_porcelain": [l for l in git("status", "--porcelain").splitlines() if l],
    "git_diff_sha256": hashlib.sha256(patch.stdout).hexdigest(),
    "git_diff_bytes": len(patch.stdout),
    "patch_file": "reports/v2_pilot_2k_seed7000/reproducibility/code_changes.patch",
    "files": {},
}
missing = []
for c in CODE:
    p = os.path.join(ROOT, c.replace("/", os.sep))
    if os.path.isfile(p):
        code["files"][c] = {"sha256": sha(p), "bytes": os.path.getsize(p)}
    else:
        missing.append(c)
        code["files"][c] = {"missing": True}
json.dump(code, open(os.path.join(OUT, "code_lock.json"), "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("code_lock.json  files=%d missing=%d  diff_sha=%s"
      % (len(code["files"]), len(missing), code["git_diff_sha256"][:12]))
if missing:
    print("  ★ 없는 파일:", missing)

# ---------------- 5.3 scene_lock.json ----------------
scene = paths.get("production_scene")
scene_lock = {
    "registry_key": "production_scene",
    "absolute_path": scene, "repo_relative_path": rel(scene),
    "bytes": os.path.getsize(scene), "sha256": sha(scene),
    "blender_version": "5.1.1", "blender_build_hash": "b70da489d7f4",
    "rollback_sources": {
        k: {"repo_relative_path": rel(paths.get(k)), "sha256": sha(paths.get(k))}
        for k in ("production_scene_rollback_source",
                  "production_scene_stage2c1_rollback")
        if os.path.isfile(paths.get(k))
    },
}
json.dump(scene_lock, open(os.path.join(OUT, "scene_lock.json"), "w",
                           encoding="utf-8"), indent=2, ensure_ascii=False)
print("scene_lock.json  sha=%s" % scene_lock["sha256"][:12])

# ---------------- 5.4 asset_lock.csv ----------------
LICENSE = {
    "pallet_models": "CC-BY (P0/P1) · NoAI 원본은 quarantine (ledger B1/B3/B5)",
    "pallet_source_v2": "CC-BY 3.0 (J-Toastie) + CC0 (BlenderKit EUR-pallet)",
    "pallet_materials": "CC0 / CC-BY — 각 폴더 LICENSE·SOURCES 참조",
    "floor_materials": "CC0 (Poly Haven, ledger B4)",
    "hdri": "CC0 (Poly Haven, ledger B4)",
    "backgrounds": "CC-BY 4.0 (Sketchfab: parking_lot Veterock · industrial BazukaliKartal)",
    "distractors": "CC0 / CC-BY 4.0 — library/{tier}/LICENSE·SOURCES 참조 (ledger B5)",
}
CATEGORIES = [
    ("pallet_models", paths.get("pallet_model_roots")[0]),
    ("pallet_source_v2", paths.get("pallet_model_roots")[1]),
    ("pallet_measurements", paths.get("pallet_measurements")),
    ("pallet_materials", paths.get("pallet_material_root")),
    ("floor_materials", paths.get("floor_material_root")),
    ("hdri", paths.get("hdri_root")),
    ("backgrounds", paths.get("background_root")),
    ("distractors", paths.get("distractor_root")),
]
rows = []
for category, root in CATEGORIES:
    if os.path.isfile(root):
        files = [root]
    else:
        files = [os.path.join(dp, f) for dp, _d, fn in os.walk(root) for f in sorted(fn)]
    for f in sorted(files):
        r = rel(f)
        rows.append({
            "registry_category": category,
            "repo_relative_path": r,
            "file_size_bytes": os.path.getsize(f),
            "sha256": sha(f),
            "asset_identifier": os.path.splitext(os.path.basename(f))[0],
            "license_class": LICENSE.get(category, "see SOURCES"),
        })
with open(os.path.join(OUT, "asset_lock.csv"), "w", newline="",
          encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
import collections
cc = collections.Counter(r["registry_category"] for r in rows)
print("asset_lock.csv  %d 파일 / %.2f GiB"
      % (len(rows), sum(r["file_size_bytes"] for r in rows) / 1024 ** 3))
for k, v in cc.most_common():
    print("   %-22s %5d" % (k, v))

# ---------------- 5.5 command.txt ----------------
wrapper = (
    "python scripts/data_prep/blender/run_v2_pilot_2k_repro.py \\\n"
    "  --out data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_fullaudit \\\n"
    "  --seed 7000 --n 2000 --session-usable-cap 100 \\\n"
    "  --render-profile dataset-quality --samples 64 --noise-tier auto \\\n"
    "  --mask-profile full-audit --magenta-max-fraction 0.0 \\\n"
    "  --log-dir reports/v2_pilot_2k_seed7000/logs\n"
)
blender_cmd = (
    '"%s" -b "%s" \\\n'
    "  --python scripts/data_prep/blender/run_v2_scene_logic.py -- \\\n"
    "  --out data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_fullaudit \\\n"
    "  --seed 7000 --n 2000 --completion-mode usable \\\n"
    "  --render-profile dataset-quality --samples 64 --noise-tier auto \\\n"
    "  --mask-profile full-audit --magenta-max-fraction 0.0 \\\n"
    "  --session-usable-cap 100\n"
) % (r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe", scene)
open(os.path.join(OUT, "command.txt"), "w", encoding="utf-8").write(
    "# wrapper (실제 실행)\n" + wrapper +
    "\n# wrapper 가 세션마다 호출하는 Blender 명령\n" + blender_cmd +
    "\n# environment variables\n"
    "PYTHONIOENCODING=utf-8\n"
    "(BLENDER_EXE 는 설정하지 않았다 — wrapper 가 표준 경로에서 탐지)\n"
    "\n# production scene 은 registry 로만 해석한다\n"
    "python scripts/data_prep/blender/pallet_data_paths.py --key production_scene\n"
)
print("command.txt")
