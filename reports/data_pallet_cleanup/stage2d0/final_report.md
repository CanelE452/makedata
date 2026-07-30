# Stage 2-D0 최종 보고 — 잔여 대용량 자료 비파괴 감사

## 1. 목적과 판정

data/pallet 에 남은 legacy dataset · 압축 package · scene backup · 라이선스 격리 자료 ·
Isaac 자산 · weight 를 **근거 기반으로 분류**하고 Stage 2-D1 계획만 작성한다.

**판정: 완료.** 데이터 이동·삭제·rename 0건. 중단 기준 해당 없음.
파일시스템 delta **dirs +0 / files +0 / bytes +0**.

## 2. branch / HEAD

```
분기 기준     75a3f71c22a7eee4b689cb4ef59c38d1c3420e5d  (= main = origin/main)
작업 branch   chore/data-pallet-stage2d0-archive-audit
작업 전 상태   clean, 실행 중 blender.exe 0개
commit/push   0 / 0
```

실행 중 python 5개는 전부 **다른 프로젝트**(Algorithmic-Trading 수집기 4개 + blender_mcp
브리지)이고 data/pallet 를 건드리지 않아 그대로 두었다.

## 3. 감사 전후 파일시스템 불변 [확인]

```
                    감사 전                감사 후                delta
──────────────────────────────────────────────────────────────────────────
dirs                  2,560                  2,560                 +0
files               363,090                363,090                 +0
bytes       192,468,045,942        192,468,045,942                 +0
active scene sha256   8cb4109a…              8cb4109a…            불변
C1 rollback           5cad94e5…              5cad94e5…            불변
original rollback     46f436dc…              46f436dc…            불변
Stage 2-A 원장        fe1adc26…              fe1adc26…            불변
Stage 2-B B1/B2       43461e47… / 0d0c06a8…  동일                  불변
Stage 2-C2 C2C        241f5c56…              241f5c56…            불변
```

신규 파일은 `reports/data_pallet_cleanup/stage2d0/` 아래에만 생성했다.

## 4~6. 남은 규모와 archive 분류

```
data/pallet 전체              179.25 GB / 363,090 파일 / 2,560 dirs
감사 대상 (정리완료 4영역 제외)  170.34 GB / 85 top-level entries
archive/                      82.589 GB / 166 entries / 327,650 파일
```

★ **Stage 2-A 가 만든 semantic 하위폴더 7개가 전부 비어 있다** (`legacy_datasets`,
`legacy_scenes`, `legacy_assets`, `corrupt`, `nonredistributable`, `superseded_runs`,
`unidentified`). "archive/legacy_datasets 87.7GB" 는 **계획된 목적지 이름**이었고 실제
dataset 156개는 `archive/` 최상단에 평평하게 놓여 있다. 상세: `remaining_tree.md`.

## 7. legacy dataset 분류 (120개 / 82.34 GB)

```
분류                        개수    비고
──────────────────────────────────────────────────────────────────────────────
COMPLETE_LEGACY_DATASET       17    image>=100 && json>=100
NOAI_BAKED_DATASET             4    training_data · v4 · v4_split · train_4pallet_mask_v1
PARTIAL_DATASET               99    소규모 진단/테스트 출력
UNKNOWN_DATASET                0
```

첫 분류에서 `rgb=0` 이 여러 건 나왔는데, 이는 탐지기가 `train_batch_NNN/` 배치 레이아웃을
놓친 것이었다. 확장자 기반으로 고쳐 재분류했다(UNKNOWN 5 → 0).
zero-byte 파일 보유: `archive/training_data`, `archive/train_palletobj_v3_post_v1`.

## 8~12. package 감사와 ★ 중복 판정

```
archive 총계          20개 / 84.92 GB   (최상위 14 + archive 내 6)
open 성공             19
open 실패             1   train_palletobj_v1.zip
encrypted entry       0
duplicate entry path  0
```

### 손상 package 1건 [확인]

```
train_palletobj_v1.zip   4,529,431,174 bytes
  head   PK\x03\x04 (정상 local file header)
  tail   ...49454e44ae426082  = PNG IEND 청크
  EOCD   마지막 1MB 내 미검출 -> zipfile: BadZipFile
판정     CORRUPT_PACKAGE (truncated — PNG 저장 중 기록이 끊기고 central directory 미기록)
```

같은 내용이 `train_palletobj_v1 (2).zip`(30,012 entries) · `pallet.zip/train_palletobj_v1`
(30,012) · 추출본 `archive/train_palletobj_v1`(30,012 파일) 에 남아 있어 **유일본이 아니다.**
삭제하지 않고 `archive/packages/corrupt/` 보존 이동만 제안한다.

### ★ 증거 레벨을 나눈 결과 — "중복" 은 하나도 확정되지 않았다 [판정]

```
LEVEL 3 STRUCTURAL_MATCH (path + 각 파일 size 일치)   12건
LEVEL 4 CONTENT_VERIFIED_BY_CRC                      1건 (modular zip ×2, 29 entries)
LEVEL 5 SHA256 전수                                   0건 (미실시)
PACKAGE_BUNDLE                                       pallet.zip = v1(30,012) + v2(30,010)
```

**read 0바이트**로 ZIP 끼리 central-directory CRC 를 대조해 결정적 사실을 얻었다.

```
비교                                        entries   path size CRC        결론
────────────────────────────────────────────────────────────────────────────────────────
train_palletobj_v2.zip vs (2).zip            30,010    ✓    ✓   ✗ 3건 불일치
pallet.zip/train_palletobj_v1 vs (2).zip     30,012    ✓    ✓   ✗ 4건 불일치
pallet.zip/train_palletobj_v2 vs v2.zip      30,010    ✓    ✓   ✗ 4건 불일치
test_blender_v68 vs v70 vs test_indoor_v1     3,000    ✓    ✗   ✗   크기부터 다름
modular_buildings_industrial_area(.)zip ×2       29    ✓    ✓   ✓   CONTENT_VERIFIED
```

불일치 파일만 표적 CRC 검증(3.3MB read)한 결과:

```
train_palletobj_v2 : 4건 중 (2).zip 이 4/4 추출본과 일치, v2.zip 1/4, pallet.zip 3/4
train_palletobj_v1 : 4건 중 어느 것도 4/4 아님 — (2).zip 3/4, pallet.zip 1/4
```

→ **세 사본(추출본 · ZIP · bundle)이 서로 조금씩 다르다.** 같은 파일명·같은 크기인데 내용이
다른 PNG 가 3~4개씩 있다. **파일 수 + bytes 만 봤다면 "중복이니 ZIP 삭제 가능" 으로 갔을
것이다.** 어느 것도 exact duplicate 로 부를 수 없어 전부 보존한다.

## 13~14. blend / rollback-critical

```
blend·blend1 17개 / 4.55 GB
  ACTIVE_RUNTIME       2   stage2c2.blend · _sandbox_palletobj_production.blend
  ROLLBACK_CRITICAL    4   original · C1 portable + 각각의 candidate .blend1 (byte-identical)
  COLD_ARCHIVE        11   legacy snapshot 8 + .blend1 3
byte-identical 쌍      3   DUPLICATE_FILE_EXACT — 그래도 둘 다 보존
```

`.blend1` 을 이름만 보고 불필요로 판정하지 않았다. `BACKUP_OF` 는 구조 signature 를 읽지
않았으므로 **선언하지 않았다**(3개는 [추정] 으로만 남김). 상세: `blend_retention_plan.md`.

## 15~16. isaac_assets · NoAI quarantine

```
isaac_assets                4,543 파일 / 4.052 GB / registry 참조 0 / exclusion 등록
  판정 LICENSE_QUARANTINE (NVIDIA EULA, ledger B6). REPRO_REFERENCE 성격 겸함
  ledger B2 는 오탐 종료 — 프로덕션 blend 에 Isaac 지문 0 -> 렌더 산출물에 baked 안 됨
archive/_noai_quarantine_usd   3 파일 / 738,082 bytes / 참조 0 / exclusion 등록
  판정 LICENSE_QUARANTINE. **이동하지 않음** — 격리 경로 자체가 provenance 근거
```

## 17~20. weight 색인

```
총 29개 / 5.298 GB / 전부 .pth / weights/ 아래 / .gitignore:6 로 제외됨
고유 SHA256 29 -> **DUPLICATE_WEIGHT 0건** (크기가 전부 191.8MB 로 같아 반드시 확인해야 했다)

ACTIVE_WEIGHT        1   weights/pallet_category/final_net_epoch_0060.pth
                         (config/default.yaml:32 pretrained_weights 가 직접 지정)
REPRO_CHECKPOINT    24   pallet_category 12 + pallet_v11 12 (config output_dir 아래 epoch 스냅샷)
UNREFERENCED_WEIGHT  4   pallet_category_test ×2 · 2024-01-11 model_best · 2023-10-28 model_best
UNKNOWN_WEIGHT       0
```

UNREFERENCED 를 **삭제 후보라고 부르지 않는다.** 2023/2024 model_best 2개는 FoundationPose
upstream 계열로 보이며 [추정] provenance 확인 전에는 REPRO 가능성이 있다.

### ★ broken weight reference 2건 [확인]

```
config/stage3_selftrain.yaml:83   weights/pallet_category/net_pallet_best.pth   -> 파일 없음
scripts/dope/run_dope_live.py:160 data/pallet/ndds3_pallet.pth (기본값)          -> 파일 없음
```

self-training / live 추론을 지금 실행하면 이 두 경로에서 실패한다.

## 21. license / exclusion 상태

```
검증기  entries 11 / problems 0 / release leaks 0 / exit 0
```

★ **exclusion 미등록 5건 검토 필요** (`license_crosscheck.csv`):
`train_4pallet_mask_v1.zip`(NoAI 추출본은 등록됐는데 ZIP 은 미등록 → 누출 경로) ·
`pallet.zip`(bundle) · `training_data_v4_split_GREYBUG` · `_bg1bak` ·
`training_data_v4_emptywood`(v4 파생 추정이나 NoAI 상속을 **파일 근거로 확인하지 않음** →
이름 유사성만으로 단정하지 않았다).

검증기 출력은 `--csv` 로 stage2d0 를 명시해 **Stage 2-B/2-C 스냅샷을 덮어쓰지 않았다**
(git status clean 으로 확인).

## 22. ★ current reference blocker — Stage 2-C2 보고 정정

참조 그래프를 **literal + join-form 양쪽**으로 다시 만들었다(365건, stale 226).
stale 대부분은 테스트 fixture 리터럴·완료된 이동의 source 기록·스크립트 자체 출력경로이고,
**진짜 깨진 입력 참조는 8건**(`stale_reference_actionable.csv`)이다.

```
severity  파일                                                 없는 target        깨뜨린 단계
──────────────────────────────────────────────────────────────────────────────────────────────
HIGH      scripts/data_prep/compute_distractor_fill_ratio.py:49  distractors      ★ Stage 2-C2 (내 이동)
HIGH      scripts/data_prep/isaac_sim/debug_pallet_orientation.py:10  models_usd  Stage 2-B
MED       scripts/data_prep/merge_and_validate.py:13-19          training_data    archive 이동
MED       config/default.yaml:53                                 training_data    archive 이동
MED       config/stage3_selftrain.yaml:81-83                     training_data 등  archive 이동 + weight
MED       scripts/dope/run_dope_live.py:160                       ndds3_pallet.pth 원본 미보존
LOW       config/synthetic/blender_train_4000.yaml:20             training_data
LOW       config/synthetic/isaac_sim.yaml:3,6,9                   pallet_scene 등
```

**Stage 2-C2 에서 "옛 경로 runtime 참조 0" 이라고 보고했는데 그건 리터럴 grep 만 본 결과였다.**
`os.path.join(root,"data","pallet",X)` 형태를 놓쳤고, 그 중 하나(`compute_distractor_fill_ratio.py:49`)는
**내가 distractors 를 옮겨서 깨진 것**이다. Stage 2-A 가 이미 배운 교훈을 2-C2 에서 다시 놓쳤다.
(감사 스크립트가 `rg` 를 subprocess 로 못 찾아 조용히 빈 결과를 낸 것도 도중에 발견해 고쳤다 —
그대로 뒀다면 "차단 0건" 이라는 틀린 안심을 보고할 뻔했다.)

`blender_config.py:200` · `floor_and_mask.py:22` 는 **주석**이라 가짜 양성이었다(수동 확인).

## 23~25. archive 구조 제안 · Stage 2-D1 계획 · 추가 비용

```
proposed_stage2d1_moves.csv   60행
  SAFE_MOVE_CANDIDATE          47   (D1A 14 · D1C 22 · D1D 11)
  CORRUPT_ARCHIVE_CANDIDATE     1   (D1B, 삭제 금지)
  BLOCKED_ACTIVE                2   registry active blend
  BLOCKED_ROLLBACK              4   rollback blend (별도 승인)
  KEEP_QUARANTINE               2   isaac_assets · NoAI
  KEEP_CURRENT                  4   UNREFERENCED_WEIGHT (목적지 미정)
이동 후보 48건 / 163.03 GB
UNKNOWN 은 계획에서 제외 (해당 0건)
```

```
hash / read budget      상한 20 GB
실제 읽은 bytes           9.48 GB (47%) — refused 0
  metadata·package-signature   0     (압축 해제 0, testzip 미실행)
  weight SHA256                5.298 GB
  blend + NoAI SHA256          4.183 GB
  표적 CRC 검증                0.003 GB
읽지 않고 남긴 것
  LEVEL 4 CRC 전수 (12건)      55.18 GB  -> 예산 초과, 사용자 승인 대기
  Stage 2-D1 실행 시           326.07 GB (source+dest 양쪽, hash-mode all)
```

`packages/duplicates/` 는 **비워 둔다** — CRC 로 확인된 중복이 없다.

## 26~27. inventory rename · memory sync

`inventory.csv` 는 전 파일 manifest 가 아니라 그룹 집계다(코드 참조 0) →
`grouped_inventory.csv` rename 은 문서 1줄만 고치면 된다. 이번 단계에서는 하지 않았다.
Stage 2-C1 memory 가 "Stage 2-C2 rebase 필요"·"active = C1 portable" 로 남아 있어 갱신 대상이다.
상세: `inventory_rename_plan.md` · `memory_sync_plan.md`.

## 28. 남은 사용자 결정

```
1. LEVEL 4 CRC 전수 검증 (55.18 GB read) 승인 여부
2. Stage 2-D1 실행 승인 (163 GB 이동 / 326 GB hash read)
   -> cohort 분할 실행 권장: D1B(4.2GB) -> D1D(3.0GB) -> D1A(84.9GB) -> D1C(82.3GB)
3. exclusion 미등록 5건 처리 방향 (특히 train_4pallet_mask_v1.zip 누출 경로)
4. v4_split 파생 3종의 NoAI 상속 확인 (라벨 metadata 판독 필요)
5. UNREFERENCED_WEIGHT 4개의 보존 위치
6. broken reference 8건 정정 시점 (D1 과 함께 / 별도 tracked commit)
7. inventory.csv rename 시점
8. memory 갱신 승인
```

## 29~30. git diff / commit

```
수정   scripts/data_prep/manage_pallet_data_layout.py   (--allow-destination-additions 추가,
                                                        기본 동작 불변)
       scripts/data_prep/verify_distribution_exclusions.py  (기본 --csv 를 stage 중립 경로로)
신규   scripts/data_prep/audit_pallet_archives.py      (감사 도구)
       reports/data_pallet_cleanup/stage2d0/
       reports/data_pallet_cleanup/distribution_exclusion_audit.csv
commit 0 / push 0
```

---

```
감사한 directory 수                2,560 (data/pallet 전체) / 집중 감사 251
감사한 file 수                     363,090 색인 / 내용 감사 대상 170.34 GB
metadata-only files               대부분 (inventory·package signature)
selective/full hash files          29 weight + 17 blend + 3 NoAI + 8 PNG = 57
실제 hash read bytes               10,180,000,000 (9.48 GB / 예산 20 GB)
ZIP package 수                     20
corrupt package 수                 1
exact duplicate file group 수       3 (blend, SHA256 동일)
structural match 수                12 (LEVEL 3)
content-verified package 수         1 (LEVEL 4, modular zip ×2)
legacy dataset 수                  120
rollback-critical blend 수          4
quarantine 항목 수                  2
weight 수                          29
active weight 수                   1
unreferenced weight 수             4
duplicate weight 수                0
unknown 항목 수                    0
proposed Stage 2-D1 move 수        48 (계획 60행 중)
data 이동                          0
data 삭제                          0
data rename                       0
ZIP 수정                           0
압축 해제                          0
Blender 렌더                       0
Stage 2-D1 실행                    0
commit                            0
push                              0
```
