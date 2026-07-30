# Stage 2-D1.1 hash read budget

## 전역 상한 20 GiB — 범위 전체는 들어가지 않는다

이동 전 실측 bytes 로 계산했다 (pre-hash + post-hash = bytes × 2).

```
cohort                     bytes        예상 read     실사용        판정
──────────────────────────────────────────────────────────────────────────────
D11A_BLEND_BACKUPS        2.24 GiB      4.47 GiB     4.47 GiB     예산 내 · 실행
D11B_REFERENCE_TRANSITION 16.14 GiB    32.29 GiB        —         ★ 초과 · 미실행
D11C_LICENSE_RESOLUTION   14.52 GiB    29.04 GiB        —         ★ 초과 · 미실행
──────────────────────────────────────────────────────────────────────────────
합계                      32.90 GiB    65.80 GiB     4.47 GiB     상한의 3.3배
```

§6 "예상 read 가 20GiB 를 넘으면 apply 전에 중단" · §17 "hash read 20GiB 초과 → 중단" ·
"selective 강등 금지" 세 조건을 동시에 만족시킬 방법이 없다. **예산을 지키는 쪽을
택했다.**

## 왜 쪼개지 않았는가

남은 예산 15.53 GiB 안에 들어가는 조합은 있다 (D1-003 0.26 + D1-053 0.14 + D1-038 11.98
= 12.38 GiB). 그러나 cohort = `transaction_group` 이고 **한 건 실패 시 cohort 전체 역순
rollback** 이 이 설계의 안전장치다. cohort 를 쪼개면 그 원자성이 깨지고, "3/4 만 옮긴
cohort" 는 rollback 경계가 모호해진다. 그래서 cohort 단위로 전부 들어가거나 전부
미실행으로 두었다.

## 구현 (Stage 2-D1 에서 도입, D1.1 에서 재사용)

```
--max-hash-read-gib <GiB> / --max-hash-read-bytes <bytes>
  1) 해시 시작 전: stat 으로 전체 크기를 재고 초과 예상이면 exit 2 (한 바이트도 안 읽음)
  2) 읽는 중: _sha256 이 1MB 블록마다 budget.add() -> 넘으면 즉시 중단
  옵션 생략 시 무제한 = 기존 정책 동작 불변 (회귀 테스트로 고정)
```

worker = 1 (순차). cohort 병렬 hash 0.

## D11A 실측

```
plan  (pre-hash)   10 파일 / 2,400,984,463 B (2.24 GiB) / unhashed 0
verify (post-hash) 10 파일 / 2,400,984,463 B (2.24 GiB) / mismatch 0
합계 read          4,801,968,926 B (4.47 GiB) / 한도 20 GiB (22.4%)
```

C2C 재검증(chain 포함)은 별도로 1,324 파일 SHA256 을 읽는다 — prior 원장 검증분이며
D11A 이동 예산과 구분된다. chain 이 인정한 10건은 **다시 읽지 않는다**(successor 쪽에서
이미 검증했으므로).

## prior identity 는 기존 해시를 쓴다

§6 규칙대로, **prior 원장과의 identity 연결에는 C2C 가 이미 기록한 SHA256** 을 쓰고
(새로 읽지 않는다), **새 이동 자체에는 새 pre/post SHA256** 을 계산했다. 즉 기존 해시를
새 이동의 post-hash 대신 쓰지 않았다.
