# Stage 2-D1.2 transaction policy — `stage2d12-final-moves`

## 왜 새 policy 인가

기존 `stage2d11-residual-finalization` 은 D1.1 의 CSV 스키마(`scope` 열 등)를 기대한다.
D1.2 의 frozen scope 는 열 구성이 다르다 — 그대로 쓰면 `KeyError: 'scope'` 다.
**기존 policy 를 고치지 않고** 새 policy 를 추가했다. 기존 policy 를 수정하면 이미
검증이 끝난 D1/D1.1 원장의 재검증 의미가 바뀐다.

```python
POLICY_STAGE2D12 = "stage2d12-final-moves"
D12_SCHEMA_VERSION = "stage2d12.1"
D12_COHORTS = ("D12B_REFERENCE_MOVE", "D12C_PROVEN_NOAI_MOVE")
D12_NOAI_DEST_ROOT = "data/pallet/archive/legacy_datasets/noai_baked"
D12_FORBIDDEN_NOAI_DEST = ("/redistributable/", "/packages/", "/unidentified/",
                           "/release/", "/partial/")
```

## 이동 규칙 (Stage 2-A 부터 불변)

- **same-volume `os.rename` 만.** copy+delete 아님, cross-volume 아님.
- **destination overwrite 금지.** 목적지가 이미 있으면 거부한다.
- **삭제 없음.** ZIP 삭제·수정·해제 없음, package 병합 없음, symlink/junction 없음.
- **manifest 가 유일한 rollback 근거.** 원장에 없는 것은 되돌릴 수 없다.
- cohort = `transaction_group`. 한 row 라도 실패하면 그 group 전체를 **역순 rollback**.

## `_stage2d12_candidates()` 가 강제하는 것

```
1  scope SHA 결속        frozen_scope.csv 의 SHA256 이 frozen_scope.json 과 일치해야 한다
2  cohort 분할 거부      --move-ids / --only-source 로 cohort 일부만 고르면 거부
3  live reference 0      실행 표면이 source 를 리터럴로 가리키면 거부
4  PROVEN_NOAI 목적지    noai_baked/ 외 목적지 거부 (금지 접두 5종 명시)
5  registry key 유효성   키가 아직 source 를 가리키고 있어야 한다 (이동 전 상태)
6  registry_final_value  == destination 이어야 한다 (오타로 다른 곳을 가리키는 것 차단)
7  prior ledger flag     소속이 있으면 successor chain 필요 표시
```

## hash

`hash-mode=all` 고정. `--workers 1`. pre-hash 후 이동, 이동 후 post-hash 로 전수 대조.
`HashBudget` 은 **한 바이트도 읽기 전에** stat 기반으로 먼저 검사하고, 읽는 도중에도
검사한다. 초과하면 `HashBudgetExceeded` 로 **중단** — selective 로 자동 강등하지 않는다.

## verify 멱등성

원장은 **최초 검증만** 기록한다.

```python
if is_d1 and not row.get("verified_at"):
    # 재검증이 원장을 다시 쓰면 원장 SHA256 이 바뀌고,
    # 그 SHA 에 결속된 successor chain 이 깨진다 (Stage 2-D1.1 에서 실제 발생).
    row["hash_read_bytes_post"] = row_post_read
    row["verified_at"] = _now()
    touched = True
```

이게 없으면 재검증 때마다 `verified_at` 이 바뀌어 chain 의 `prior_manifest.sha256`
결속이 깨진다. D1.1 에서 실제로 발생했고(`spec e2c1a19f… vs actual 500da414…`) 고쳤다.
D1.2 에서 모든 원장을 재검증한 뒤 `git status` 로 원장 dirty 0 을 확인했다 [확인].

## successor ledger chain

prior 원장에서 "없어진" 파일을 통과시키는 **유일한** 근거는 3자 SHA256 동일성이다.

```
prior 원장의 (relative_path, size, sha256)
  == successor 원장 source 의 pre_hash
  == successor destination 의 실측 identity
```

broad missing/removal allow, expected-removal 목록만으로 통과 — 전부 금지.
`--successor-ledger-chain` 은 **반복 지정 가능**하며, 여러 chain 이 같은 prior key 를
중복 주장하면 exit 2 로 거부한다.
