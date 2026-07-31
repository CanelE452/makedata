# Stage 2-D2 rollback plan

## 원칙

**manifest 가 유일한 rollback 근거다.** 이동은 전부 same-volume `os.rename` 이라
rollback 도 rename 이다 — 복사도 삭제도 없다.

## cohort = transaction group

```
D2_LEGACY_DATASETS   64 row  /  1,963 파일  /    607,410,306 B
  reports/data_pallet_cleanup/stage2d2/transactions/d2_legacy_datasets.jsonl
D2_SUPERSEDED_RUNS  135 row  / 21,321 파일  /  5,268,927,072 B
  reports/data_pallet_cleanup/stage2d2/transactions/d2_superseded_runs.jsonl
```

한 row 라도 실패하면 그 group **전체**를 역순으로 되돌린다. 일부만 남기지 않는다.

## 되돌리는 방법

```bash
# 적용의 역순
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d2/transactions/d2_superseded_runs.jsonl

python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d2/transactions/d2_legacy_datasets.jsonl
```

## 파일과 **함께** 되돌려야 하는 것

파일만 되돌리면 상태가 어긋난다.

```
1  참조 전환 (38 치환)  git checkout d5e1ba1 -- \
                          scripts/data_prep/blender/{_b3_asset_check,_v2_calib_200,
                            _g5_reverify,_v2_pilot_2k,run_v2_scene_logic,audit_v2_dryrun,
                            _v2_calib_200_analyze,_v2_pilot_overlay_all,_v2_pilot_audit,
                            analyze_v2_scene_logic,overlay_v2_detailed,audit_v2_scene_logic,
                            audit_pnp_eligibility,analyze_v2_continuous,
                            _verify_archive_style_pixels,_make_archive_vs_new_sheet,
                            efront_kp12}.py \
                          scripts/data_prep/blender/{run_pilot_2k,run_addon_v1}.sh \
                          scripts/data_prep/{visualize_pretrain,visualize_inference,
                            evaluate_on_val,verify_keypoints}.py \
                          scripts/data_prep/efront_calibration/README.md \
                          config/synthetic/isaac_sim.yaml
                       -> 확인: 이동 전 경로를 가리키는 live ref 가 다시 14건이 된다

2  exclusion            data/pallet/_DISTRIBUTION_EXCLUDE.txt 의 4 entry 를
                        archive/superseded_runs/_X/ -> archive/_X/ 로 되돌린다
                        (재구축 명세는 distribution_exclusion_rebuild_spec.md)
                     -> python scripts/data_prep/verify_distribution_exclusions.py

3  문서                 _docs/blender_mcp_onboarding.md · dataset_license_ledger.md ·
                        experiments/v2_smoke50_continuous_eda_results.md (40 치환)

4  local manifests      data/pallet/manifests/{archive,path_map,assets}.csv
                        reports/data_pallet_cleanup/grouped_inventory.csv
                        ⚠️ manifests/ 는 gitignored 라 git 으로 못 되돌린다.
                           백업: scratchpad/_bak_gi_d2.csv (grouped_inventory)
```

## rollback 하면 안 되는 것

```
Stage 2-A / 2-B / 2-C2 / 2-D1 / 2-D1.1 / 2-D1.2 원장   전부 별도 transaction
기존 successor chain 2종                               수정 금지
```

## 전체 rollback 트리거

active scene SHA 변화 · registry missing · current broken ref · release leak ·
prior ledger unmapped missing · 기존 원장 SHA 변화 · unit/integration/golden 실패 ·
5k digest 변화 · data file count 변화 · SHA256 mismatch.

순서: 마지막 VERIFIED cohort → 최초 cohort → (empty-source relocation: **없음**) →
registry(변경 없음) → exclusion → manifests/docs.

## 지금 상태

rollback **하지 않았다.** 두 cohort 모두 MOVED + verified_at 기록,
`checkpoint.json` 의 `all_verified = true`, failures 0.
rollback manifest 와 chain 은 실패 증거로 보존한다.

## ⚠️ gitignored 파일 주의

`data/pallet/_DISTRIBUTION_EXCLUDE.txt` 와 `data/pallet/manifests/*.csv` 는 gitignored 다.
git 으로 되돌릴 수 없으므로 위 명세·백업을 근거로 손으로 복구해야 한다.
