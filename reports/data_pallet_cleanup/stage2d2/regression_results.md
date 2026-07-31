# Stage 2-D2 §19 전체 회귀 검증

전부 **실제 실행**했다 [확인]. 수치는 실행 출력에서 옮겼다.

```
항목                                  기대치                실측                        판정
────────────────────────────────────────────────────────────────────────────────────────────
A unit                                745 + 신규            778 passed, skip 0, fail 0  PASS
B integration                         >=31, skip 0          31 passed, skip 0           PASS
C golden                              >=51, skip 0          51 passed, skip 0           PASS
D registry                            missing=0             ok=28 missing=0             PASS
E exclusion                           0/0/0/0               entries 16 / problems 0 /   PASS
                                                            leaks 0 / stale 0 / dup 0
F 기존 원장 12종                        failures 0            전부 0                      PASS
  C2C (exact + chain x2)              failures 0            11 file(s) from 2 chain(s)  PASS
G D2 원장 2종                          VERIFIED / all /      199/199 verified · all ·     PASS
                                      unhashed 0            unhashed 0 · mismatch 0
H 5k FrameSpec                        4,313 / 687 /         동일                        PASS
                                      938f387d
I 5k proposal                         4,439 / 3cd365ee /    동일                        PASS
                                      12-12
J Blender no-render                   8cb4109a · abs 0 ·    동일 (images 603 ·          PASS
                                      missing 0 · Dist_ 209 node 누락 0)
K data file count                     363,090               363,090 -> 363,090          PASS
L 원장 멱등성                          재검증 후 SHA 불변      5599c7d78b035d60 동일       PASS
```

## A. Unit — 745 → 778 (+33)

```
python -m pytest scripts/data_prep/blender/tests/ -q
-> 778 passed in 89.29s   (skip 0)
```

신규 33개 전부 `tests/test_stage2d2_layout_completion.py` (tmpdir fixture 전용 +
읽기전용 회귀 클래스). §9 이 요구한 30항목을 클래스로 나눠 담았다:

```
PlanBinding(7)          frozen plan SHA 일치/불일치 · row 수 · 파일 부재 ·
                        기록된 policy 문제 · hash 예산 사전 초과
CohortRules(5)          cohort 전량 선택 · escape hatch · 미지 cohort ·
                        중복 destination · 중첩 source
DestinationPolicy(6)    승인 root 밖 · archive 밖 · path escape ·
                        제한 라이선스→redistributable 거부 · noai_baked 허용 ·
                        ZIP→packages 강제
ReferenceGuards(4)      live runtime · live test · registry 소유 · doc-only 는 통과
PolicyContainerGuards(3) 최종 container 이동 거부 · container 인식 · payload 오인 금지
EmptyDirectoryHandling(2) 빈 디렉토리 계획 · 상대경로 보존(basename 평탄화 금지)
PriorLedgerGuards(1)    prior member 탐지
NoRegressionOnRealLedgers(4) 기존 policy 6개 무변경 · D2 policy 등록 ·
                        D2 원장 all/unhashed 0 · RESOLVED_EXCLUSIONS 기록 유지
```

## E. Exclusion — 검증기가 stale 4건을 잡았다

이동 직후 1차 검사에서 `problems 4 (STALE_ENTRY)` 가 나왔다:

```
archive/_pallet_catalog_0123 · _efront_12kp_check · _floor_applied14 · _floor_compare
```

새 경로(`archive/superseded_runs/...`)로 갱신하고 재검사해 0 을 얻었다.

## G. D2 원장 — ★ 도구 결함 1건을 실측으로 잡았다

첫 verify 는 `verified moves: 64 / failures 0` 을 보고했는데 원장의 `verified_at` 은
**199행 전부 비어 있었다.** 원인:

```python
is_d1 = row.get("schema_version") in (D1_SCHEMA_VERSION, D11_SCHEMA_VERSION,
                                      D12_SCHEMA_VERSION)   # D2 가 빠짐
```

`stage2d2.1` 이 화이트리스트에 없어 post-hash 기록·`verified_at` 기록 경로를 타지 않았다.
"verify 가 통과했다"는 **선언**과 원장의 **실제 상태**가 달랐던 것이다.
`D2_SCHEMA_VERSION` 을 추가하고 재검증해 199/199 기록 + post-hash 전수 기록을 확인했다.

## K. 파일 수 불변 — bytes 증가분을 전부 특정했다

```
data/pallet  before  dirs 2,567  files 363,090  bytes 192,468,109,581
             after   dirs 2,567  files 363,090  bytes 192,468,260,125
             delta   dirs 0      files 0        bytes +150,544
```

```
data/pallet/manifests/*.csv       +150,286   archive(+17행·+16열) · path_map(+191행) ·
                                             assets(stage2d2_status 열)
data/pallet/_DISTRIBUTION_EXCLUDE.txt  +258   4 entry 새 경로 + 근거 주석
────────────────────────────────────────────
                                  +150,544
```

`archive/` 는 +4,583,026,386 B / +19,192 파일, 그만큼이 depth-1 잔여에서 빠졌다
(같은 볼륨 이동이므로 총량 불변). **새 data file 생성 0.**

## 실행하지 않은 것

```
파일 삭제 0 · 빈 폴더 삭제 0 · ZIP 삭제/수정/해제 0 · package 병합 0 ·
weight 삭제 0 · isaac_assets 이동 0 · NoAI USD 이동 0 · active scene 이동/저장 0 ·
rollback-critical scene 이동 0 · 현역 asset/reference/run 이동 0 ·
Blender 렌더 0 · 데이터 생성 0 · 모델 학습 0 · Stage 3 시작 0 ·
git add -A 0 · git add . 0 · commit 0 · push 0
```
