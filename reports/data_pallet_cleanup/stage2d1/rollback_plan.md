# Stage 2-D1 rollback plan

## 되돌릴 대상

```
cohort                상태          rollback 근거 원장
────────────────────────────────────────────────────────────────────────────
D1B_CORRUPT           VERIFIED      transactions/d1b_corrupt.jsonl          (1건)
D1D_BLEND_BACKUPS     ROLLED_BACK   transactions/d1d_blend_backups.jsonl    (이미 되돌림)
D1A_PACKAGES          VERIFIED      transactions/d1a_packages.jsonl        (14건)
D1C_LEGACY_DATASETS   VERIFIED      transactions/d1c_legacy_datasets.jsonl (15건)
```

각 row 에 `rollback_source`(원위치) · `rollback_destination`(현위치) ·
`source_sha256`(전 파일 해시) 이 박혀 있다. **원장을 잃으면 되돌릴 수 없다.**

## cohort 하나만 되돌리기

```bash
T=scripts/data_prep/manage_pallet_data_layout.py
M=reports/data_pallet_cleanup/stage2d1/transactions

# 되돌리기 전에 현재 상태 확인
python $T --verify --manifest $M/d1a_packages.jsonl

# 역순 rename (삭제·덮어쓰기 없음)
python $T --rollback --manifest $M/d1a_packages.jsonl
```

되돌린 뒤 반드시:

```bash
python scripts/data_prep/blender/pallet_data_paths.py --audit          # missing 0
python scripts/data_prep/verify_distribution_exclusions.py \
  --csv reports/data_pallet_cleanup/stage2d1/_rollback_check.csv       # problems 0
python -m pytest scripts/data_prep/blender/tests/ -q                  # 714 passed
```

## cohort 별 부수 복구 — exclusion 파일 (gitignored, 수동)

`data/pallet/_DISTRIBUTION_EXCLUDE.txt` 는 `.gitignore` 대상이라 git 으로 되돌아오지
않는다. cohort 를 되돌리면 아래를 손으로 되돌린다.

### D1A 를 되돌리면

```
현재  archive/packages/dataset_bundles/train_4pallet_mask_v1.zip
복구  train_4pallet_mask_v1.zip
```

### D1C 를 되돌리면

```
현재  archive/legacy_datasets/noai_baked/training_data_v4/
      archive/legacy_datasets/noai_baked/training_data_v4_split/
      archive/legacy_datasets/noai_baked/train_4pallet_mask_v1/
복구  archive/training_data_v4/
      archive/training_data_v4_split/
      archive/train_4pallet_mask_v1/
```

`archive/training_data/` 는 D1 이 옮기지 않았으므로 손대지 않는다.

복구 후:

```bash
python scripts/data_prep/verify_distribution_exclusions.py --csv /tmp/chk.csv
# entries 16 / problems 0 / leaks 0 / stale 0 이어야 한다
```

**되돌리면서 exclusion 을 안 고치면 stale 이 생기고, 반대로 새 경로만 남기면
release leak 이 생긴다.** 이동과 exclusion 은 항상 같이 움직인다.

## 전체 D1 rollback (§17 순서)

전역 불변식이 깨졌을 때만. 순서를 지킨다 (뒤에서 앞으로):

```
1  registry·tracked config 를 D1 전 상태로            git checkout 0129078 -- config/ ...
2  D1C rollback                                       --rollback d1c_legacy_datasets.jsonl
3  D1A rollback                                       --rollback d1a_packages.jsonl
4  D1D                                                이미 rollback 완료 — 할 일 없음
5  D1B rollback                                       --rollback d1b_corrupt.jsonl
6  exclusion 파일 복구                                 위 수동 절차 (D1C -> D1A 순)
7  local manifests 복구                                git checkout -- data/pallet/manifests/
8  grouped inventory 복구                              git checkout -- reports/.../grouped_inventory.csv
9  source file count·bytes·SHA256 확인                 원장 verify 로 대조
10 전체 회귀 검증                                       unit·integration·golden·registry·5k
```

`git checkout` 대상은 tracked 파일뿐이다. `data/pallet/` 은 gitignored 이므로 데이터는
반드시 `--rollback` 으로 되돌린다.

## rollback 에서도 금지

```
파일 삭제        없음 — --rollback 은 역순 rename 이다
destination overwrite  거부 (이미 있으면 실패하고 멈춘다)
cross-volume     거부
```

## 지금 되돌릴 수 있는가 [확인]

```
d1b_corrupt.jsonl           1행 MOVED  · rollback_source/destination 기록됨
d1a_packages.jsonl         14행 MOVED  · 같음
d1c_legacy_datasets.jsonl  15행 MOVED  · 같음 (relative_files 191,503 경로 포함)
d1d_blend_backups.jsonl    10행 ROLLED_BACK · rollback_status OK@… 기록됨
source 잔존                  0 / 30   (전부 이동 완료 상태)
destination 존재            30 / 30
```

세 원장이 모두 살아 있고 원위치·해시가 기록돼 있으므로 **되돌릴 수 있다.**
