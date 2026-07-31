# stage2d2/chains/ — successor ledger chain

## 결론: 이번 단계는 새 chain 이 필요 없다

frozen plan 199 row 의 source 를 prior ledger **7종 전체**와 대조했다
(`MPL.find_prior_ledger_conflict` 전수 조회).

```
prior ledger 구성원인 source   0 건
필요한 신규 chain              0 개
```

"chain 이 안 만들어졌으니 없겠지"로 넘기지 않고 직접 조회한 결과다.
Stage 2-D1.2 는 sandbox blend 1건이 C2C 구성원이라 chain 이 필요했지만, D2 의 대상
(archive/ depth-1 진단 산출물 · data/pallet depth-1 로그)은 어느 원장도 옮긴 적이 없다.

## 기존 chain 은 그대로 쓴다 (수정 0)

C2C 원장 검증에는 여전히 **두 chain 을 모두** 전달해야 한다.

```
reports/data_pallet_cleanup/stage2d11/c2c_successor_chain.json          (mapping 10)
reports/data_pallet_cleanup/stage2d12/chains/c2c_distractor_scene_to_d12.json (mapping 1)
-> successor chain: 11 file(s) from 2 chain(s) / 인정된 이관 11 / failures 0
```

음성 확인(Stage 2-D1.2 에서 실측): chain 하나만 주면 다른 쪽 이관이 MISSING 으로 실패한다
(D11A 만 -> failures 2, D12 만 -> failures 11).

## 재현

```bash
python scripts/data_prep/manage_pallet_data_layout.py --verify \
  --manifest reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl \
  --expected-destination-additions reports/data_pallet_cleanup/stage2d01/c2c_expected_additions.json \
  --successor-ledger-chain reports/data_pallet_cleanup/stage2d11/c2c_successor_chain.json \
  --successor-ledger-chain reports/data_pallet_cleanup/stage2d12/chains/c2c_distractor_scene_to_d12.json
```
