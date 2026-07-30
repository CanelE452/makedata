# Stage 2-D1 hash read budget

이번 단계는 READY 파일을 **이동 전·후로 두 번** SHA256 한다. 그래서 read 량이 데이터
크기의 2배다. 예산 없이 돌리면 어디까지 읽었는지 모르는 상태로 디스크를 장시간 점유한다.

## 구현

`manage_pallet_data_layout.py` 에 `HashBudget` 을 추가했다.

```
--max-hash-read-gib <GiB>     (편의 형태)
--max-hash-read-bytes <bytes> (정확 형태 — 둘 다 주면 이 값이 이긴다)
```

두 지점에서 검사한다.

```
1  해시 시작 전   stat 으로 전체 크기를 먼저 재고 (한 바이트도 읽지 않은 상태)
                 read_bytes + 예상치 > 한도 이면 HashBudgetExceeded -> exit 2
2  읽는 중        _sha256 이 1MB 블록마다 budget.add(len(block)) -> 넘으면 즉시 중단
```

**selective 로 자동 강등하지 않는다.** 예산이 부족하면 멈추고 사람이 결정한다
(정책이 `require_hash_mode=all` 이므로 강등 자체가 정책 위반이다).

옵션을 생략하면 `limit=None` 으로 무제한 — 기존 정책(Stage 2-A/B/C2) 동작에 영향이 없다.
회귀 테스트로 고정했다 (`test_no_budget_option_keeps_previous_behaviour`).

## worker

**worker = 1 (순차).** `snapshot()` 은 파일을 하나씩 읽는다. 병렬화하지 않은 이유:
- 디스크 thrashing 방지 (D1C 는 191,503개 소파일)
- 여러 cohort 를 동시에 읽지 않는다는 규율을 코드 구조로 보장
지시문 상한은 worker=2 이지만 필요하지 않았다 — 실측 처리율이 충분했다.

## cohort 별 예산과 실측

예산은 **cohort 총량(pre+post)** 이다. 드라이버가 `verify` 에 넘기는 한도를
`budget - pre_read` 로 깎아 주므로 합계가 한도를 넘을 수 없다. cohort 간 이월은 없다.

```
cohort                예산      pre(GiB)   post(GiB)  합계(GiB)  사용률   판정
──────────────────────────────────────────────────────────────────────────────
D1B_CORRUPT           10 GiB      4.22       4.22       8.44     84.4%   OK
D1D_BLEND_BACKUPS      6 GiB      2.24       2.24       4.47     74.5%   OK (뒤에 rollback)
D1A_PACKAGES         160 GiB     75.21      75.21     150.43     94.0%   OK
D1C_LEGACY_DATASETS  110 GiB     47.22      47.22      94.44     85.9%   OK
──────────────────────────────────────────────────────────────────────────────
상한 합계            286 GiB
실사용 합계                                            257.78 GiB
```

D1D 는 apply·verify 까지 성공했으나 앞선 원장(C2C) 충돌로 rollback 했다 — read 는
실제로 발생했으므로 위 표에 남긴다.

D1C 의 pre/post 가 계획 추정치(50.70 GiB)보다 작은 것은, 계획의 `total_bytes` 가
Stage 2-D0 시점 집계였고 실제 해시는 이동 시점 실측이라 그렇다. 파일 수·바이트는
pre/post 가 서로 정확히 일치한다(verify failures 0).

## 예산 초과 시 동작 (테스트로 고정)

```
test_budget_refuses_before_reading_anything   1바이트 한도 -> plan exit 2, manifest 미생성
test_budget_trips_mid_read                    누적이 넘으면 HashBudgetExceeded
test_no_budget_option_keeps_previous_behaviour  옵션 없으면 기존 동작
```
