# §23 Rollback 계획

**삭제를 쓰지 않는다.** 전부 같은 볼륨 rename 역이동이고, 각 그룹의 manifest 가 rollback 근거다.
overwrite 금지 — destination(=원위치)에 이미 뭔가 있으면 그 자리에서 중단한다.

## 역순 (적용의 반대)

```
적용 순서:  C2A(ZIP)  ->  C2B(background)  ->  C2C(distractors + blender_scene)
롤백 순서:  C2C       ->  C2B             ->  C2A
```

## 절차

```bash
cd E:/CODING/GitHub/FoundationPose

# 1. registry 를 Stage 2-C1 값으로 복구 (tracked 파일)
git checkout -- config/synthetic/pallet_paths.yaml

# 2. tracked 코드·config·테스트 복구
git checkout -- \
  config/synthetic/blender.yaml config/synthetic/blender_train_4000.yaml \
  scripts/data_prep/manage_pallet_data_layout.py \
  scripts/data_prep/blender/blender_config.py \
  scripts/data_prep/blender/manage_blend_external_paths.py \
  scripts/data_prep/blender/audit_blend_assets.py \
  scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py \
  scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py \
  _docs/data_pallet_layout.md _docs/blender_mcp_onboarding.md
# 신규 untracked 파일(tests/test_stage2c2_layout_policy.py, reports/.../stage2c2/)은 두어도 무해

# 3. Stage 2-C2 stable / candidate 는 삭제하지 않고 실패 증거로 남긴다
#    (registry 가 더 이상 가리키지 않으므로 active 가 아니다)

# 4. C2C group rollback  (blender_scene -> 원위치, distractors -> 원위치. 역순 자동)
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
    --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl

# 5. C2B rollback  (background -> 원위치)
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
    --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2b_background_asset.jsonl

# 6. C2A rollback  (ZIP -> background 원래 상대경로)
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
    --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2a_background_packages.jsonl

# 7. source file count / bytes / SHA256 확인
#    background 77 / 291,054,721   distractors 1,161 / 1,958,754,064
#    blender_scene 173 / 3,836,556,170     (합계 1,411 / 6,086,364,955)

# 8. Stage 2-C1 portable 이 다시 active 로 정상 resolve 되는지
SCENE="$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)"
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b "$SCENE" \
  --python scripts/data_prep/blender/audit_blend_assets.py -- \
  --report-dir reports/data_pallet_cleanup/stage2c2/rollback --tag rollback
#   -> absolute 0 / missing 0 / textures 158 / distractors 356 / Dist_ 209

# 9. registry audit          -> ok=22 missing=0
# 10. unit / integration / golden
python -m pytest scripts/data_prep/blender/tests/ -q                         # 614 + 30(신규 정책)
PALLET_DATA_INTEGRATION=1 python -m pytest scripts/data_prep/blender/integration_tests/ -q
python -m pytest scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py -q   # 51
# 11. Stage 2-A / 2-B 원장 verify (원장 sha256 불변 확인)
# 12. 5k 두 하네스 재검증  -> 938f387d… / 4,313 · 3cd365ee… / 4,439 12/12
```

## 부분 실패 시

```
상황                                    조치
──────────────────────────────────────────────────────────────────────────────────
C2A 후 background 에 archive 잔존         C2A rollback, C2B 시작 금지
C2B 실패                                 C2B rollback -> C2A rollback -> 중단
C2C 중 한쪽만 이동                        도구가 **자동으로** 그룹 역순 rollback 한다
                                        (apply 안에서 처리, 수동 개입 불필요)
candidate rebase 실패                    candidate 는 실패 증거로 보존.
                                        registry 는 아직 Stage 2-C1 을 가리키므로
                                        C2C/C2B/C2A rollback 만 하면 원상복구
승격 후 실패                             위 1~12 전체 절차
```

## 금지

- overwrite (destination 존재 시 중단)
- 데이터 파일 삭제
- Stage 2-C1 portable / original blend 수정
- Stage 2-A / 2-B transaction manifest 수정

## 로컬 manifest

`data/pallet/manifests/{assets,path_map,archive}.csv` 는 gitignored 라 git 으로 되돌릴 수 없다.
롤백 시 `production_scene` 을 다시 Stage 2-C1 portable 로, `distractor_root`/`background_root` 를
옛 경로로 되돌리고 `background_package_archive` 행을 제거해야 한다.
