# Stage 2-D2 — hash read 예산

## 승인 한도 (§8)

```
D2 이동 pre+post hash            16 GiB
final protected-area hash audit  12 GiB
chain·manifest 검증 reserve       4 GiB
────────────────────────────────────────
전체                             32 GiB
```

`worker=1` · `hash-mode=all` · selective 강등 금지.

## 계획 시점 추정 (frozen_final_plan.json, 실측 bytes 기반)

읽기량 = 이동 bytes x 2 (pre 1회 + post 1회). 파일 수·bytes 는 이동 직전 파일시스템을
다시 재서 얻었다(D1.2 보고서 숫자를 재사용하지 않았다).

```
cohort                  rows   files     bytes            추정 읽기
──────────────────────────────────────────────────────────────────────
D2_SUPERSEDED_RUNS      135   21,321    5,268,927,072     9.81 GiB
D2_LEGACY_DATASETS       64    1,963      607,410,306     1.13 GiB
──────────────────────────────────────────────────────────────────────
합계                    199   23,284    5,876,337,378    10.95 GiB / 16 GiB
```

`within = true`. 초과 시 도구는 hashing 시작 전 `HashBudgetExceeded` 로 중단하고
selective 로 자동 강등하지 않는다.

## 실제 사용량

```
cohort                  pre-hash        post-hash       합계
──────────────────────────────────────────────────────────────────
D2_LEGACY_DATASETS        0.57 GiB        0.57 GiB      1.13 GiB
D2_SUPERSEDED_RUNS        4.91 GiB        4.91 GiB      9.81 GiB
──────────────────────────────────────────────────────────────────
합계                      5.47 GiB        5.47 GiB     10.95 GiB / 16 GiB (68.4%)
```

추정치와 실사용이 일치한다 — 예산 초과 0, hash-mode 강등 0, unhashed 0.

## 예산 밖 (별도 집계)

- 기존 원장 14종 재검증: 이동을 수반하지 않는 post-hash 재확인.
- `--max-hash-read-gib 12` 를 계획 단계에 걸어 cohort 별 사전 stat 검사를 강제했다.
