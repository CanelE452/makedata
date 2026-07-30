# Stage 2-D1.1 rollback plan

## 이번 단계에서 실제로 옮긴 것

```
D11A_BLEND_BACKUPS   10건 / 2.24 GiB
  reports/data_pallet_cleanup/stage2d11/transactions/d11a_blend_backups.jsonl
```

D11B / D11C 는 **이동하지 않았다** (hash 예산 초과). 되돌릴 데이터가 없다.
단, D11B 는 **registry 전환(코드/config)** 을 했으므로 그 부분은 되돌릴 대상이다.

## D1.1-A rollback

```bash
T=scripts/data_prep/manage_pallet_data_layout.py
M=reports/data_pallet_cleanup/stage2d11/transactions/d11a_blend_backups.jsonl

python $T --verify --manifest $M        # 되돌리기 전 상태 확인
python $T --rollback --manifest $M      # 역순 rename
```

되돌린 뒤 **반드시** 확인한다:

```bash
# 파일이 원위치로 돌아왔으므로 chain 없이도 C2C 가 통과해야 한다
python $T --verify \
  --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl \
  --expected-destination-additions reports/data_pallet_cleanup/stage2d01/c2c_expected_additions.json
# -> failures 0

python scripts/data_prep/blender/pallet_data_paths.py --audit     # ok=28 missing=0
python -m pytest scripts/data_prep/blender/tests/ -q              # 745 passed
```

`c2c_successor_chain.json` 은 **삭제하지 않는다** — 실패 증거로 보존한다.
rollback 후에는 chain 의 successor destination 이 사라져 chain 검증이 실패하는데,
그것이 정상이다(파일이 원위치에 있으니 chain 없이 통과해야 한다).

빈 `archive/legacy_scenes/{snapshots,blender_backups}/` 는 남는다 — **삭제하지 않는다.**

## D1.1-B — registry 전환 되돌리기 (데이터 이동은 없었다)

이동 전이므로 데이터 rollback 은 없다. 코드/config 만 되돌린다:

```bash
git checkout 1577e25 -- \
  config/synthetic/pallet_paths.yaml config/default.yaml config/stage3_selftrain.yaml \
  scripts/train_dope.sh scripts/self_training/self_train.py \
  scripts/data_prep/postprocess_v3.py scripts/data_prep/visualize_pretrain.py \
  scripts/data_prep/visualize_inference.py scripts/data_prep/evaluate_on_val.py \
  scripts/data_prep/isaac_sim/generate_all.sh \
  scripts/data_prep/blender/gen_palletobj_v1.py \
  scripts/data_prep/blender/pallet_data_paths.py
```

registry key 4개가 사라지므로 `--audit` 은 ok=24 로 돌아간다. 확인:

```bash
python scripts/data_prep/blender/pallet_data_paths.py --audit   # ok=24 missing=0
python -m pytest scripts/data_prep/blender/tests/ -q            # 714 passed (신규 31 사라짐)
```

**이동을 실행한 뒤 되돌리는 경우**의 순서:

```
1  pallet_paths.yaml 의 legacy_* 키 4개를 이동 전 경로로 되돌린다
2  python $T --rollback --manifest .../d11b_blocked_reference.jsonl
3  python scripts/data_prep/postprocess_v3.py --help              (경로 해석 확인)
4  python .../pallet_data_paths.py --resolve registry:legacy_training_data_root/train
5  canonical broken ref 0 확인
```

## D1.1-C — 이동을 실행했을 경우

```bash
python $T --rollback --manifest reports/data_pallet_cleanup/stage2d11/transactions/d11c_license_resolution.jsonl
```

`provenance_decisions.csv` / `provenance_report.md` 는 **보존한다** — 이동을 되돌려도
"PROVEN_NOAI" 라는 판정 사실은 변하지 않는다.

## `_DISTRIBUTION_EXCLUDE.txt` — gitignored, 수동 복구

이 파일은 `.gitignore` 대상(`data/` 전체)이라 **새 clone 에서 자동 복원되지 않고**
git 으로 되돌릴 수도 없다. **tracked 정본 기록은 `_docs/dataset_license_ledger.md`** 다.

```
현재 상태 (D1.1 에서 변경 없음)
  entries 16 / problems 0 / leaks 0 / stale 0
```

D11C 를 실행했다면 되돌릴 항목 4개:

```
archive/legacy_datasets/noai_baked/training_data_v4_split_GREYBUG/
  -> archive/training_data_v4_split_GREYBUG/
archive/legacy_datasets/noai_baked/training_data_v4_split_bg1bak/
  -> archive/training_data_v4_split_bg1bak/
archive/legacy_datasets/noai_baked/training_data_v4_emptywood/
  -> archive/training_data_v4_emptywood/
archive/legacy_datasets/noai_baked/training_data_v4_pilotA/
  -> archive/training_data_v4_pilotA/
```

D11B 를 실행했다면 추가로:

```
archive/legacy_datasets/noai_baked/training_data/  -> archive/training_data/
```

복구 후 반드시:

```bash
python scripts/data_prep/verify_distribution_exclusions.py --csv /tmp/chk.csv
# entries 16 / problems 0 / leaks 0 / stale 0
```

## 전체 rollback 순서 (§16)

```
1  D1.1-C rollback   (미실행 — 할 일 없음)
2  D1.1-B rollback   데이터 미실행. registry/config 만 git checkout
3  D1.1-A rollback   --rollback d11a_blend_backups.jsonl
4  registry/config   git checkout 1577e25 -- <위 12개 파일>
5  exclusion         변경 없음 (D1.1 에서 손대지 않았다)
6  manifests         data/pallet/manifests/*.csv 는 gitignored -> 수동
                     (archive.csv 10행 · path_map.csv 10행 · assets.csv 열 제거)
   grouped inventory git checkout 1577e25 -- reports/.../grouped_inventory.csv
7  회귀 검증          unit·integration·golden·registry·exclusion·5k·C2C
```

삭제·overwrite 금지. `--rollback` 은 역순 rename 이다.

## 지금 되돌릴 수 있는가 [확인]

```
d11a_blend_backups.jsonl   10행 MOVED · rollback_source/destination 기록 ·
                           source_sha256 10개 전부 기록
source 잔존                 0 / 10
destination 존재            10 / 10
D1D 원장 (ROLLED_BACK)      수정하지 않았다 — 실패 증거로 유효
C2C 원장                    수정하지 않았다 (SHA256 241f5c569d2be924… 불변)
registry 전환               tracked 파일이라 git 으로 완전 복원 가능
```

원장이 살아 있고 원위치·해시가 기록돼 있으므로 **되돌릴 수 있다.**
