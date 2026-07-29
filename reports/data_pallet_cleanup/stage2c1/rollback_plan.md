# §16 Rollback 계획

데이터 파일 **삭제를 쓰지 않는다.** 원본은 이미 무손상으로 보존돼 있으므로 롤백은
"registry 를 되돌리고 새로 만든 파일을 치워두는 것"이 전부다.

## 전제 [확인]

```
원본  data/pallet/blender_scene/synth_data_scene.blend
      sha256 46f436dc8d9302a6f857c62c1abcaf4e6fefdc10042ee646e9ef3dc3acbb7fb9
      size 358,917,479   mtime 2026-07-24 19:39:00.380291100 (작업 전과 동일)
      Stage 2-C1 은 이 파일을 열어 저장한 적이 **없다** (save 계열 API 는 candidate 를 연
      프로세스에서만, 그것도 `bpy.data.filepath == candidate` 확인 후에만 호출)
```

## A. 승격 전 실패였다면 (해당 없음 — 참고용)

1. candidate 파일은 삭제하지 않고 실패 증거로 보존
2. registry 는 원본을 계속 가리킴
3. 원본 SHA256 확인
4. 후속 단계 중단

## B. 승격 후 롤백 (현재 적용 가능한 절차)

```bash
cd E:/CODING/GitHub/FoundationPose

# 1. registry 를 원본으로 복구 (tracked 파일이므로 git 으로 되돌리면 된다)
git checkout -- config/synthetic/pallet_paths.yaml

# 2. tracked 코드·문서 복구
git checkout -- \
  scripts/data_prep/blender/run_dataset_v4.sh \
  scripts/data_prep/blender/run_4pallet_mask.sh \
  scripts/data_prep/blender/run_pilot_2k.sh \
  scripts/data_prep/blender/run_v2_scene_logic.py \
  scripts/data_prep/blender/gen_dataset_v4.py \
  scripts/data_prep/blender/gen_4pallet_mask.py \
  scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py \
  scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py \
  scripts/data_prep/efront_calibration/README.md \
  _docs/data_pallet_layout.md _docs/blender_mcp_onboarding.md
# 신규 파일(untracked)은 두어도 무해하다:
#   scripts/data_prep/blender/blend_path_utils.py
#   scripts/data_prep/blender/manage_blend_external_paths.py
#   scripts/data_prep/blender/audit_blend_assets.py
#   scripts/data_prep/blender/tests/test_blend_external_paths.py
#   reports/data_pallet_cleanup/stage2c1/

# 3. portable 파일은 삭제하지 않고 same-volume rename 으로 치운다
mkdir -p "data/pallet/archive/legacy_scenes/stage2c1_failed_$(date +%Y%m%d_%H%M%S)"
mv data/pallet/blender_scene/synth_data_scene_portable.blend \
   "data/pallet/archive/legacy_scenes/stage2c1_failed_<timestamp>/synth_data_scene_portable.blend"
# (Blender 가 만든 백업도 같이)
mv data/pallet/blender_scene/synth_data_scene_portable_candidate_20260729.blend1 \
   "data/pallet/archive/legacy_scenes/stage2c1_failed_<timestamp>/"

# 4. 원본 SHA256 확인 — 46f436dc… 여야 한다
sha256sum data/pallet/blender_scene/synth_data_scene.blend

# 5. registry audit — ok=21 missing=0 으로 돌아와야 한다
python scripts/data_prep/blender/pallet_data_paths.py --audit

# 6. 테스트 재실행 (롤백 후 기준값)
python -m pytest scripts/data_prep/blender/tests/ -q                    # 568 + 43(신규 helper) 
PALLET_DATA_INTEGRATION=1 python -m pytest \
    scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py -q   # 23
python -m pytest scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py -q  # 51

# 7. 5k dry-run 재실행 (두 하네스 모두)
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 \
    --dump reports/data_pallet_cleanup/stage2c1/dryrun/_raw_framespec_5k_rollback.jsonl
#   -> accepted 4,313 / rejected 687 / sha256 938f387d…
python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 \
    --tag 5k_rollback --out reports/data_pallet_cleanup/stage2c1/dryrun
#   -> 12/12 PASS, digest 3cd365ee…

# 8. Stage 2-A / 2-B 원장 verify
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2a/move_transaction.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b1_reference_materials.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b2_lighting_models.jsonl

# 9. 추가 수정 중단
```

로컬 manifest(`data/pallet/manifests/assets.csv` · `path_map.csv`)는 gitignored 라
git 으로 되돌릴 수 없다. 롤백 시 `production_scene` 행의 `active` 를 `false` 로,
`production_scene_rollback_source` 행을 다시 `production_scene` 으로 되돌려야 한다.

## rollback 에서 금지

- overwrite (destination 이 이미 있으면 중단)
- 데이터 파일 삭제
- 원본 `.blend` 수정
- Stage 2-A / 2-B transaction manifest 수정

## 재생성 경로 (롤백 대신 다시 만들고 싶을 때)

원본이 무손상이므로 portable 은 **언제든 결정적으로 재생성**할 수 있다:

```bash
python - <<'PY'
import shutil
shutil.copy2("data/pallet/blender_scene/synth_data_scene.blend",
             "data/pallet/blender_scene/synth_data_scene_portable_candidate_<date>.blend")
PY
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
  data/pallet/blender_scene/synth_data_scene_portable_candidate_<date>.blend \
  --python scripts/data_prep/blender/manage_blend_external_paths.py -- \
  --apply-candidate --role candidate --strict \
  --source-blend data/pallet/blender_scene/synth_data_scene.blend \
  --candidate-blend data/pallet/blender_scene/synth_data_scene_portable_candidate_<date>.blend \
  --expect-source-sha256 46f436dc8d9302a6f857c62c1abcaf4e6fefdc10042ee646e9ef3dc3acbb7fb9 \
  --repoint "factory_yard_2k.hdr=$(pwd)/data/pallet/assets/lighting/hdri/library/factory_yard_2k.hdr" \
  --report-dir reports/data_pallet_cleanup/stage2c1/apply_rerun
```

(`.blend` 저장은 압축 스트림이라 byte 재현이 보장되지는 않는다 — 재생성물의 SHA256 이
`5cad94e5…` 와 다를 수 있다. 동등성은 `--verify` 의 외부경로 0/0 + 구조 diff 0 으로 판정한다.)
