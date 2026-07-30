# Stage 2-D1 §16 최종 전체 검증

전부 **실제 실행**했다 [확인].

```
항목                                     기대치              실측                        판정
──────────────────────────────────────────────────────────────────────────────────────────────
A unit                                   기존 664 + 신규      714 passed, skip 0, fail 0   PASS
B integration                            >=31, skip 0          31 passed, skip 0, fail 0   PASS
C golden overlay                         >=51, skip 0          51 passed, skip 0, fail 0   PASS
D registry                               ok=24 missing=0      ok=24 missing=0 absent=0     PASS
E exclusion                              problems 0           entries 16 / problems 0 /    PASS
                                         leaks 0 stale 0      leaks 0 / stale 0 / dup 0
F 기존 transaction                        failures 0           7원장 전부 0                 PASS
                                         원장 SHA256 불변      4종 불변 확인
G Stage 2-D1 transaction                 all / unhashed 0 /   3원장 30행 / unhashed 0 /    PASS
                                         mismatch 0            mismatch 0 / failures 0
H 5k FrameSpec                           4,313 / 687          4,313 / 687                  PASS
                                         938f387d             938f387dd65258e0…            일치
I 5k proposals                           4,439 / 3cd365ee     4,439 / 3cd365eec96d1009…    PASS
                                         12/12                12/12 checks passed
J Blender no-render                      abs 0 missing 0      abs 0 · missing 0 ·          PASS
                                         Dist_ 209            Dist_ 209 · node 누락 0
```

## A. Unit — 664 → 714 (+50)

```
python -m pytest scripts/data_prep/blender/tests/ -q -rs
-> 714 passed in 150.15s
```

신규 50개 전부 `tests/test_stage2d1_archive_finalization.py` (tmpdir 전용, 실제
data/pallet 미접촉). skip 0 — `-rs` 로 확인했다.

지시문이 요구한 28개 검사 항목을 모두 담았고, 실행 중 발견한 것 3가지를 테스트로
추가해 50개가 됐다:

```
요구 28개 커버                     클래스
────────────────────────────────────────────────────────────────────
1-2   READY file/directory plan     ReadyRowsPlan
3-4   BLOCKED / KEEP 거부           ForbiddenStatus
5-6   wrong plan SHA / 변경 후 거부  PlanBinding
7-11  source missing · collision ·  SourceDestinationChecks
      different drive · escape ·
      symlink
12-13 selective 거부 · unhashed     HashModeEnforcement
14-15 budget 사전·도중              HashBudgetTests
16-17 ZIP D1A/D1B · corrupt D1B     ArchiveCohortRules
18-21 rollback-critical · active ·  ProtectedSources
      quarantine · weight
22-24 relpath · SHA256 · license     VerifyFailures
25    apply->verify->rollback        RoundTrip
26-28 Stage 2-A/B/C2 회귀           NoRegressionInOlderPolicies

실행 중 발견해 추가                  이유
────────────────────────────────────────────────────────────────────
PriorLedgerConflict (4개)            D1D 실패 — 앞선 원장 구성원 이동 차단
  그중 1개는 실제 저장소 원장으로 검증
mixed cohort 선택 (2개)              D1D cohort 는 READY 10 + KEEP 7 로 섞여 있다
dataset 안의 ZIP (2개)               D1C 의 training_data_v4_split.zip
```

## F. 기존 transaction — 회귀 없음

```
원장                          files    failures   SHA256
──────────────────────────────────────────────────────────────────────
stage2a/move_transaction      6,921        0      fe1adc266bd91963…  불변
stage2b b1_reference_materials 3,220       0      43461e4749898529…  불변
stage2b b2_lighting_models       68        0      0d0c06a849fcf201…  불변
stage2b b3_scene_assets           0        0
stage2c2 c2a_background_pkgs      3        0
stage2c2 c2b_background_asset    74        0
stage2c2 c2c_distractor_scene 1,336        0 ★    241f5c569d2be924…  불변
```

★ C2C 는 exact expected-addition 모드다. broad allow 를 쓰지 않았다.
**D1D 를 적용했던 동안에는 이 값이 11 이었다** — 그래서 rollback 했다
(`cohort_d1d_report.md`).

## G. Stage 2-D1 transaction

```
원장                       rows  verified  post==pre  src 잔존  dst 존재  hash_mode  unhashed
──────────────────────────────────────────────────────────────────────────────────────────────
d1b_corrupt                  1      1         1          0        1      all=1         0
d1a_packages                14     14        14          0       14      all=14        0
d1c_legacy_datasets         15     15        15          0       15      all=15        0
──────────────────────────────────────────────────────────────────────────────────────────────
합계                        30     30        30          0       30                    0
                            191,518 파일 / 139,733,678,407 B (130.14 GiB)
                            pre-hash read 130.14 GiB · post-hash read 130.14 GiB = 260.27 GiB
```

`failures 0` 은 각 cohort 의 verify 실행에서 얻은 값이고 원장의 `verified_at` /
`hash_read_bytes_post` 에 기록돼 있다.

**D1C 는 두 번째 verify 를 돌리지 않았다** — 50.70 GiB 를 다시 읽으면 그 cohort 의
110 GiB 예산(이미 101.41 GiB 사용)을 넘긴다. 예산을 지키는 쪽을 택하고, 근거로
원장 기록(15/15 verified · post==pre · src 잔존 0 · dst 존재 15)을 쓴다. 재검증이
필요하면 예산을 명시적으로 올려서 돌려야 한다.

## §12 파일시스템 불변

```
영역                      대조 대상   불일치   비고
────────────────────────────────────────────────────────────────────────
blend                         17        0     path/size/SHA256 (이동분은 새 경로 추적)
weight                        29        0     path/size/SHA256 — D1 미접촉
package (ZIP)                 20        0     path/size (이동분 새 경로)
legacy dataset               120        0     path/file_count/total_bytes
────────────────────────────────────────────────────────────────────────
                                        0     hash read 9.48 GiB

data/pallet  before  dirs 2,560 · files 363,090 · bytes 192,468,047,026
             after   dirs 2,567 · files 363,090 · bytes 192,468,047,650
             delta   dirs +7 · files 0 · bytes +624
```

```
dirs +7    D1 이 만든 semantic 하위폴더 7개
             packages/{corrupt,dataset_bundles} · legacy_datasets/{redistributable,
             noai_baked,partial} · legacy_scenes/{snapshots,blender_backups}
             (뒤 2개는 D1D rollback 후 비었지만 삭제하지 않았다)
files 0    한 파일도 늘거나 줄지 않았다 = 삭제 0 · 생성 0
bytes +624 data/pallet/_DISTRIBUTION_EXCLUDE.txt 3,586 -> 4,210 (허용 변경)
```

top-level: ZIP 15개 removed / added 0. archive depth-1: 166 → 151.

## 실행하지 않은 것

```
Blender 렌더        0   (no-render 감사 스크립트만)
500장·40k 생성      0
모델 학습           0
파일 삭제           0
ZIP 수정·압축해제    0
weight 이동         0
isaac_assets 이동   0
NoAI USD 이동       0
commit / push       0
```
