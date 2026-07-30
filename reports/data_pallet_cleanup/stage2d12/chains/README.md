# stage2d12/chains/ — successor ledger chain

## 이게 뭔가

Stage 2-C2 의 `c2c_distractor_scene.jsonl` 은 `blender_scene/` 폴더를
`assets/scenes/production/blender_scene/` 로 옮긴 원장이다. 그 원장은 자기가 옮긴
**폴더 안의 파일 목록**을 pre-hash manifest 로 갖고 있다.

이후 D1.1 이 그 폴더에서 blend 백업 10개를, D1.2 가 sandbox blend 1개를 다시
`archive/legacy_scenes/` 로 옮겼다. 그러면 C2C 원장을 재검증할 때 그 11개가
**MISSING** 으로 잡힌다 — 실제로는 없어진 게 아니라 다음 원장이 이관한 것이다.

chain 은 그 이관을 **증명**하는 파일이다. "없어져도 된다"는 허가가 아니다.

## 통과 조건 — 3자 SHA256 동일성

```
prior 원장의 (relative_path, size, sha256)
  == successor 원장 source 의 pre_hash identity
  == successor destination 의 지금 실측 identity
```

셋이 전부 같아야 한다. 하나라도 어긋나면 실패다. broad missing allow,
expected-removal 목록만으로 통과 — 금지.

## 이 폴더의 chain

```
파일                              prior 원장                mapping
──────────────────────────────────────────────────────────────────────────
c2c_distractor_scene_to_d12.json  c2c_distractor_scene      1
                                  _sandbox_parking_lot_check.blend
                                  -> archive/legacy_scenes/snapshots/
```

D1.1 이 만든 `stage2d11/c2c_successor_chain.json`(mapping 10)은 **수정하지 않았다.**
새 chain 을 별도 파일로 추가했다.

## ★ chain 은 자기 mapping 만 책임진다

C2C 원장을 검증할 때 **두 chain 을 모두** 줘야 한다.

```
D11A chain 만  -> D1.2 가 옮긴 1개가 MISSING   (failures 2)
D12  chain 만  -> D1.1 이 옮긴 10개가 MISSING  (failures 11)
둘 다          -> successor chain: 11 file(s) from 2 chain(s)   failures 0
```

그래서 `--successor-ledger-chain` 을 **반복 지정 가능**하게 만들었다. 여러 chain 이 같은
prior key 를 중복 주장하면 exit 2 로 거부한다(한 파일의 행방을 두 원장이 서로 다르게
주장하는 상황을 조용히 넘기지 않는다).

## 재현

```bash
python scripts/data_prep/manage_pallet_data_layout.py --verify \
  --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl \
  --expected-destination-additions reports/data_pallet_cleanup/stage2d01/c2c_expected_additions.json \
  --successor-ledger-chain reports/data_pallet_cleanup/stage2d11/c2c_successor_chain.json \
  --successor-ledger-chain reports/data_pallet_cleanup/stage2d12/chains/c2c_distractor_scene_to_d12.json
```

chain 생성은 손으로 값을 적지 않는다 — prior/successor 원장에서 읽어 만든다
(`_chains_index.json` 이 생성 결과 인덱스).
