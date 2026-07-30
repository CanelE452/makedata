# Stage 2-D1.1 §15 전체 회귀 검증

전부 **실제 실행**했다 [확인].

```
항목                                     기대치              실측                       판정
─────────────────────────────────────────────────────────────────────────────────────────────
A unit                                   714 + 신규          745 passed, skip 0, fail 0  PASS
B integration                            >=31, skip 0         31 passed, skip 0, fail 0  PASS
C golden                                 >=51, skip 0         51 passed, skip 0, fail 0  PASS
D registry                               24 + 신규 key        ok=28 missing=0            PASS
E exclusion                              problems 0           entries 16 / problems 0 /  PASS
                                         leaks 0 stale 0      leaks 0 / stale 0
F 기존 원장                               failures 0           8원장 전부 0               PASS
   C2C (exact + successor chain)         failures 0           failures 0                 PASS
G 신규 원장 D11A                          all/unhashed 0/      10행 · all · unhashed 0 ·  PASS
                                         mismatch 0           mismatch 0 · failures 0
H 5k FrameSpec                           4,313/687 938f387d   동일                       PASS
I 5k proposals                           4,439 3cd365ee 12/12 동일                       PASS
J Blender no-render                      abs 0 missing 0      abs 0 · missing 0 ·        PASS
                                         Dist_ 209            Dist_ 209 · node 누락 0
K 파일 수 불변                             files delta 0        363,090 -> 363,090         PASS
```

## A. Unit — 714 → 745 (+31)

```
python -m pytest scripts/data_prep/blender/tests/ -q -rs
-> 745 passed in 148.27s     (skip 0)
```

신규 31개 전부 `tests/test_successor_ledger_chain.py` (tmpdir 전용). §4 가 요구한 22개
항목을 모두 담고, 실행 중 발견한 것을 더해 31개가 됐다.

```
요구 항목 커버                            클래스
────────────────────────────────────────────────────────────────────────
1   valid one-hop chain                  ValidChain
19  chain 없이 missing 은 기존처럼 실패     ValidChain
2   prior manifest SHA mismatch          PriorSideChecks
4-7 prior row 부재 · relpath · size ·     PriorSideChecks
    SHA mismatch
3   successor manifest SHA mismatch      SuccessorSideChecks
8   successor source != prior dest       SuccessorSideChecks
9   successor row not VERIFIED           SuccessorSideChecks
10  successor destination missing        SuccessorSideChecks
11  successor destination SHA mismatch   SuccessorSideChecks
12  duplicate prior mapping              StructuralChecks
13  duplicate successor mapping          StructuralChecks
14  unmapped prior missing               StructuralChecks
15  path escape                          StructuralChecks
16  ledger cycle                         StructuralChecks
17  unrelated addition 실패               WithExpectedAdditions
18  expected addition + chain 동시 통과    WithExpectedAdditions
20-22 Stage 2-A/B/C2/D1 회귀 없음         NoRegression

실행 중 발견해 추가                        이유
────────────────────────────────────────────────────────────────────────
prior destination 에 아직 있는 파일 거부    현재 존재하는 파일을 chain 으로 우회 금지
prior_manifest.path mismatch              chain 이 다른 원장을 가리키는 것 차단
prior destination path mismatch
empty mappings / 필수 필드 누락
★ verify 멱등성 2개                       재검증이 원장 SHA 를 바꿔 chain 이 깨졌다
실제 저장소 C2C 원장 확인 1개              D1D 10개가 C2C 구성원임을 읽기 전용으로 확인
```

## F. 기존 원장 — 회귀 없음

```
원장                          failures   비고
──────────────────────────────────────────────────────────────────────
stage2a/move_transaction          0
stage2b b1 / b2                   0
stage2c2 c2a / c2b                0
stage2d1 d1b / d1a                0
stage2c2 c2c (exact only)        11      ← chain 없이는 실패한다 (정상 · 설계대로)
stage2c2 c2c (exact + chain)      0      ★ 정본 검증
```

원장 SHA256 은 **한 바이트도 바뀌지 않았다** — chain 은 별도 JSON 이고 기존 manifest 를
수정하지 않는다. D1D 원장(ROLLED_BACK 증거)도 그대로다.

## G. 신규 원장 D11A

```
rows 10 · files 10 · bytes 2,400,984,463 (2.24 GiB)
hash_mode all · unhashed 0 · sha256 checked 10 · mismatch 0
pre read 2.24 GiB + post read 2.24 GiB = 4.47 GiB / 한도 20 GiB (22.4%)
source 잔존 0 / destination 존재 10 / verified 10
failures 0
```

## K. 파일 수 불변

```
data/pallet  before  dirs 2,567 · files 363,090 · bytes 192,468,081,042
             after   dirs 2,567 · files 363,090 · bytes 192,468,097,791
             delta   dirs 0 · files 0 · bytes +16,749
```

bytes 변화 원인 (파일별):

```
data/pallet/manifests/archive.csv      D11A 10행 추가 + D1.1 열 5개
data/pallet/manifests/path_map.csv     D11A 10행 추가 + 열 2개
data/pallet/manifests/assets.csv       stage2d11_status 열 추가 (17행)
```

`_DISTRIBUTION_EXCLUDE.txt` 는 **변경 없다** — D11A 는 blend 이동이고 배포 제외 대상이
아니다. D11B/D11C 가 미실행이므로 exclusion 경로 변경도 없다.

**files delta 0 = 삭제 0 · 생성 0.** D11A 는 rename 이다.


## ★ 작업 중 규율 위반 1건 — 발견하고 되돌렸다

`§작업 규율: 기존 Stage 2-A/B/C/D 원장 수정 금지`

§1-F 기준선 검증에서 `--verify` 를 돌릴 때, **verify 멱등 수정을 하기 전**이었으므로
Stage 2-D1 원장 2개의 `verified_at` 타임스탬프가 갱신됐다.

```
d1b_corrupt.jsonl    D1-001        verified_at 2026-07-30T16:21:42 -> 18:51:39
d1a_packages.jsonl   D1-019~032    verified_at 16:21:5x -> 18:51:5x  (14행)
```

바뀐 것은 **타임스탬프뿐**이다 — source/destination/relative_files/pre_hash_manifest/
source_sha256/file_count/total_bytes 는 모두 동일했다(전 행 diff 로 확인). 데이터 무결성
문제는 없다.

그래도 규율 위반이므로 `git checkout 1577e25 -- <두 파일>` 로 원상복구했다.

```
복구 후 git status         stage2d1/transactions dirty 0
복구 후 verify 재실행       failures 0 · 원장 sha c5d49da6… -> c5d49da6… (멱등)
```

**재발 방지**: verify 멱등 수정(첫 검증에만 기록)이 이미 들어갔으므로 앞으로 verify 는
원장을 건드리지 않는다. 테스트 2개로 고정했다. 이 문제를 발견한 계기는 chain 결속 실패
(`spec e2c1a19f… vs actual 500da414…`)였고, 같은 수정이 두 문제를 함께 해결했다.

## 실행하지 않은 것

```
Blender 렌더        0   (no-render 감사만)
데이터 생성          0
모델 학습           0
파일 삭제           0
빈 폴더 삭제         0
ZIP 수정·압축해제    0
weight 이동         0
isaac_assets 이동   0
NoAI USD 이동       0
D11B / D11C 실이동  0   (hash 예산 초과 — §6/§17)
commit / push       0
```
