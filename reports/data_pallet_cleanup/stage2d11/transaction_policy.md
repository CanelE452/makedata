# Stage 2-D1.1 transaction policy

`manage_pallet_data_layout.py` 에 policy 를 **추가**했다. 기존 4개
(`stage2a-runs` · `stage2b-active-assets` · `stage2c2-final-layout` ·
`stage2d1-archive-finalization`)는 한 글자도 바꾸지 않았고 회귀 테스트로 고정한다.

```
policy   stage2d11-residual-finalization
prefix   S2D11 (단, move_id 는 residual_scope.csv 의 D1-0xx 를 그대로 쓴다)
schema   stage2d11.1
```

## D1 policy 와 다른 두 가지

### (1) allowlist 가 계획 CSV 가 아니라 **재계산된 범위**

D1 은 Stage 2-D0.1 이 확정한 `proposed_stage2d1_moves_final.csv` 에 결속됐다.
D1.1 은 그 계획의 BLOCKED row 를 **현재 파일시스템에서 다시 측정한**
`residual_scope.csv` + `frozen_scope.json` 에 결속된다.

```
--d11-scope         reports/data_pallet_cleanup/stage2d11/frozen_scope.json
--d11-scope-sha256  <hex>
```

`frozen_scope.json` 이 `residual_scope.csv` 의 SHA256 도 담고 있어 **두 단계로 결속**된다.
어느 하나라도 바뀌면 plan 이 exit 2 로 거부한다.

### (2) prior ledger 구성원 이동을 **조건부로** 허용

D1 은 앞선 원장 구성원을 무조건 거부했다 (그 guard 가 D1D 를 막았다). D1.1 은
`--d11-allow-prior-ledger-with-chain` 이 있을 때만 허용한다. 이 플래그는 "이동 후
successor chain 으로 prior 원장 검증을 통과시킬 계획이 있다"는 선언이고, 실제로
통과시키지 않으면 검증 사슬이 끊긴 상태가 남는다 — 그래서 §7 절차가 chain 생성과
C2C 재검증을 필수로 둔다.

## 거부 규칙 (전부 exit 2)

```
frozen scope SHA256 불일치 / residual_scope.csv 변경
목적지가 archive/ 밖 · 정규화 후 archive/ 이탈(escape) · 경로에 ..
current runtime/test 참조 > 0        -> registry 전환이 선행돼야 한다
registry 가 직접 가리키는 경로
UNKNOWN license (D11C 이외 cohort)
prior ledger 구성원인데 chain 플래그 없음
--hash-mode 가 all 이 아님
해시 예산 초과 (사전 stat 검사 + 읽는 중 검사)
```

## 원장 필드 (§5 요구 전부)

기존 스키마를 유지하고 D1.1 전용 필드를 덧붙였다.

```
schema_version · scope_path · scope_sha256 · cohort · move_id · source · destination ·
entry_kind · classification · evidence_level · license_status · license_decision ·
provenance_evidence · source_file_count · source_total_bytes · source_sha256 ·
hashed_file_count · unhashed_file_count · hash_read_bytes_pre · hash_read_bytes_post ·
applied_at · verified_at · rollback_source · rollback_destination ·
prior_ledger_members · prior_manifest_path · prior_manifest_sha256 · prior_move_id ·
prior_relative_path · prior_ledger_sha256 · successor_chain_required ·
registry_keys_before · registry_keys_after · exclusion_before · exclusion_after ·
transaction_group
```

## ★ verify 멱등성 (실행 중 발견해 고친 것)

chain 은 successor 원장의 SHA256 에 결속된다. 그런데 verify 가 재실행마다
`verified_at` 타임스탬프를 갱신하면 원장 SHA256 이 바뀌어 **chain 결속이 깨진다.**
실제로 발생했다:

```
successor chain 오류: successor manifest sha256 불일치
  spec   e2c1a19f29c59470…
  actual 500da4140372ecd3…
```

원장은 "언제 **처음** 검증됐는가"를 기록하는 immutable 기록이어야 한다. 첫 검증에만
기록하도록 고쳤다. 테스트 2개(`test_successor_verify_is_idempotent` ·
`test_chain_survives_successor_reverify`)로 고정했다.

## 삭제 기능 없음

이 도구에는 파일 삭제 경로가 존재하지 않는다. `--rollback` 도 역순 rename 이다.
