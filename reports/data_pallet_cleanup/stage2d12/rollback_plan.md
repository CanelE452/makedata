# Stage 2-D1.2 rollback plan

## 원칙

**manifest 가 유일한 rollback 근거다.** 원장에 없는 것은 되돌릴 수 없다.
이동은 전부 same-volume `os.rename` 이라 rollback 도 rename 이다 — 복사·삭제가 없다.

## cohort = transaction group

```
D12B_REFERENCE_MOVE     4 row   reports/data_pallet_cleanup/stage2d12/transactions/d12b_reference_move.jsonl
D12C_PROVEN_NOAI_MOVE   4 row   reports/data_pallet_cleanup/stage2d12/transactions/d12c_noai_move.jsonl
```

한 row 라도 실패하면 그 group **전체**를 역순으로 되돌린다. 일부만 남기지 않는다.

## 되돌리는 방법

```bash
# cohort 단위 (권장)
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d12/transactions/d12c_noai_move.jsonl

python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d12/transactions/d12b_reference_move.jsonl
```

**순서가 중요하다** — D12C 를 먼저 되돌리고 D12B 를 나중에. D12B 의 `training_data` 가
`noai_baked/` 를 만들었고 D12C 가 그 안으로 들어갔기 때문이다.

## rollback 후 반드시 같이 되돌려야 하는 것

파일만 되돌리면 상태가 어긋난다. 아래 4가지가 함께 움직인다.

```
1  registry   config/synthetic/pallet_paths.yaml 의 키 4개를 value_before 로 되돌린다
              (registry_transition.csv 의 value_before 열이 정본)
              -> python scripts/data_prep/blender/pallet_data_paths.py --audit  (ok=28 기대)

2  exclusion  data/pallet/_DISTRIBUTION_EXCLUDE.txt
              noai_baked/training_data/ -> archive/training_data/
              noai_baked/training_data_v4_split_GREYBUG/ -> archive/training_data_v4_split_GREYBUG/  (외 3종)
              -> python scripts/data_prep/verify_distribution_exclusions.py  (problems 0 기대)

3  chain      reports/data_pallet_cleanup/stage2d12/chains/c2c_distractor_scene_to_d12.json
              을 제거한다. 그러면 C2C 검증은 stage2d11 chain 하나만으로 통과한다
              (D1.2 이동이 없어졌으므로).

4  manifest   data/pallet/manifests/{archive,path_map,assets}.csv 의 d12_* 열 / 2D1.2 row
              reports/data_pallet_cleanup/grouped_inventory.csv
              -> git 이 추적하는 것은 grouped_inventory.csv 뿐이다.
                 data/pallet/manifests/ 는 gitignored 라 백업본에서 복구해야 한다.
```

## rollback 하면 안 되는 것

```
D11A (blend backup 10)          이미 검증 끝난 별도 transaction 이다
Stage 2-A / 2-B / 2-C2 / 2-D1   전부 별도 transaction
```

지시가 "기존 verified transaction 재apply / 기존 원장 rewrite" 를 금지한다.

## rollback 후 검증

```bash
# 1. 원장이 rollback 을 기록했는지
python scripts/data_prep/manage_pallet_data_layout.py --verify --manifest <각 원장>

# 2. C2C 는 chain 1개(stage2d11)만으로 통과해야 한다
python scripts/data_prep/manage_pallet_data_layout.py --verify \
  --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl \
  --expected-destination-additions reports/data_pallet_cleanup/stage2d01/c2c_expected_additions.json \
  --successor-ledger-chain reports/data_pallet_cleanup/stage2d11/c2c_successor_chain.json

# 3. 파일 수 불변
#    363,090 이어야 한다 (rollback 은 이동이지 삭제가 아니다)
```

## rollback 비용

되돌릴 때도 hash 를 다시 읽는다 — D12B 16.14 GiB + D12C 14.52 GiB. same-volume rename
이므로 실제 데이터 이동은 없고 메타데이터만 바뀐다.

## 지금 상태

rollback **하지 않았다.** 두 cohort 모두 `MOVED` + `verified_at` 기록 완료,
`checkpoint.json` 의 `all_complete = true`, verify failures 0.
