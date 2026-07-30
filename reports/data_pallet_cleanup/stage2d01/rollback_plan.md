# Stage 2-D0.1 rollback plan

## 되돌릴 것이 무엇인가

이 단계는 **데이터를 하나도 옮기지 않았다.** 따라서 rollback 대상은 파일시스템이 아니라
**tracked 소스/문서 변경 + data/pallet 안의 텍스트 파일 1개**뿐이다.

```
변경 종류                                    되돌리는 방법
────────────────────────────────────────────────────────────────────────────────────
tracked 파일 30개 수정 + 1개 rename          git 으로 완전 복원
data/pallet/_DISTRIBUTION_EXCLUDE.txt        아래 수동 절차 (gitignored)
reports/data_pallet_cleanup/stage2d01/ 신규   폴더 삭제 (report artifact)
asset / dataset / package / blend / weight    **되돌릴 것 없음 — 변경 0**
```

## 1. tracked 변경 되돌리기

아직 commit 하지 않았다. 기준 커밋 `60e0860` 으로 전부 되돌린다:

```bash
# 확인 먼저
git status
git diff --stat 60e0860

# 전체 되돌리기 (working tree 를 기준 커밋 상태로)
git checkout 60e0860 -- \
  _docs/attribution_cc-by_appendix.md \
  _docs/data_pallet_layout.md \
  _docs/dataset_license_ledger.md \
  _docs/method/step1_synthetic_data.md \
  _docs/preprocessing/data_pipeline.md \
  config/default.yaml \
  config/stage3_selftrain.yaml \
  config/synthetic/blender_train_4000.yaml \
  config/synthetic/isaac_sim.yaml \
  reports/data_pallet_cleanup/README.md \
  reports/data_pallet_cleanup/rollback_plan.md \
  scripts/data_prep/blender/gen_palletobj_v1.py \
  scripts/data_prep/blender/gen_preview10.py \
  scripts/data_prep/blender/gen_topview_test.py \
  scripts/data_prep/blender/run_addon_v1.sh \
  scripts/data_prep/blender/run_trunc_addon.py \
  scripts/data_prep/compute_distractor_fill_ratio.py \
  scripts/data_prep/efront_calibration/README.md \
  scripts/data_prep/evaluate_on_val.py \
  scripts/data_prep/isaac_sim/debug_pallet_orientation.py \
  scripts/data_prep/isaac_sim/generate_all.sh \
  scripts/data_prep/manage_pallet_data_layout.py \
  scripts/data_prep/merge_and_validate.py \
  scripts/data_prep/postprocess_v3.py \
  scripts/data_prep/verify_keypoints.py \
  scripts/data_prep/visualize_inference.py \
  scripts/data_prep/visualize_pretrain.py \
  scripts/dope/run_dope_live.py \
  scripts/self_training/self_train.py

# grouped_inventory.csv rename 되돌리기
git mv reports/data_pallet_cleanup/grouped_inventory.csv \
       reports/data_pallet_cleanup/inventory.csv

# 신규 테스트 제거
rm scripts/data_prep/blender/tests/test_destination_additions.py

# report artifact 제거 (선택)
rm -rf reports/data_pallet_cleanup/stage2d01/
```

`_docs/history/2026-07-30.md` 는 이번 단계 Section 만 지운다 (그 위 Section 은 다른 단계
기록이므로 전체 checkout 하면 안 된다).

되돌린 뒤 확인:

```bash
python -m pytest scripts/data_prep/blender/tests/ -q          # 646 passed 로 돌아온다
python scripts/data_prep/blender/pallet_data_paths.py --audit  # ok=24 missing=0
```

## 2. `_DISTRIBUTION_EXCLUDE.txt` 되돌리기 (gitignored — 수동)

```
현재  3,586 B / active entry 16
이전  2,502 B / active entry 11
```

되돌릴 때 지울 블록은 3개다 (전부 주석 헤더와 함께):

```
# --- NoAI baked dataset 의 압축본 (Stage 2-D0.1 신규) ---
train_4pallet_mask_v1.zip

# --- NoAI 상속 미확정 파생 dataset (Stage 2-D0.1 신규, 보수적 제외) ---
archive/training_data_v4_split_GREYBUG/
archive/training_data_v4_split_bg1bak/
archive/training_data_v4_emptywood/
archive/training_data_v4_pilotA/
```

(세 번째 블록 `archive/packages/background_sources/` 는 **Stage 2-C2 것이므로 남긴다.**)

지운 뒤:

```bash
python scripts/data_prep/verify_distribution_exclusions.py \
  --csv /tmp/exclusion_rollback_check.csv     # entries 11 / problems 0 이어야 한다
```

**되돌리면 릴리스 게이트가 다시 뚫린다** — `train_4pallet_mask_v1.zip`(9.01 GiB, NoAI
baked 산출물의 압축본)이 릴리스에 포함될 수 있다. 되돌리기 전에 그 결과를 감수하는지
확인할 것.

## 3. rollback 이 필요 없는 것

```
data/pallet 파일 이동        0   (--apply / --rollback / mv / os.rename 실행 0회)
data/pallet 파일 삭제        0
ZIP 수정                     0
blend 저장                   0
weight 이동                  0
Stage 2-A/B/C2 원장 수정     0   (SHA256 4종 전부 불변)
Stage 2-D1 실행              0
Blender 렌더                 0
```

증거: `filesystem_invariance.json` — archive depth-1 166 · package 20 · blend 17 ·
weight 29 · legacy dataset 120 전수 대조에서 path/size/SHA256 불일치 **0**.
`data/pallet` 총계 delta = dirs 0 / files 0 / bytes +1,084 (= `_DISTRIBUTION_EXCLUDE.txt`
단독).

## 4. Stage 2-D1 rollback (이 단계가 아니라 다음 단계용)

Stage 2-D1 을 실행하게 되면 각 cohort 의 트랜잭션 원장이 유일한 rollback 근거다:

```bash
python scripts/data_prep/manage_pallet_data_layout.py --verify   --manifest <cohort>.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --rollback --manifest <cohort>.jsonl
```

`--rollback` 은 원장을 역순으로 읽어 같은 볼륨 rename 으로 되돌린다. 삭제 명령은 없다.
원장 파일을 잃으면 되돌릴 수 없으므로 cohort 실행 직후 원장을 반드시 commit 한다.
**이 단계에서는 --rollback 을 실행하지 않았다.**
