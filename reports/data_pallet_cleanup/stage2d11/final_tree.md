# Stage 2-D1.1 최종 구조 감사

전수 조사: `data/pallet` depth 1 + `archive/` depth 1~3 = **233 entry** (`final_tree.csv`)

## data/pallet top-level (74)

```
권장 구조                     상태
────────────────────────────────────────────────────────────────
assets/                      유지 (D1.1 미접촉 — SHA256 재확인 변경 0)
reference/                   유지
runs/                        유지
manifests/                   D1.1 에서 갱신 (archive/path_map/assets)
release/                     유지 (비어 있음)
archive/                     ★ D1.1 이 정리한 대상
README.md                    관리 파일
_DISTRIBUTION_EXCLUDE.txt    관리 파일 (gitignored)
────────────────────────────────────────────────────────────────
isaac_assets/                KEEP_QUARANTINE — NVIDIA EULA (ledger B6), 4.05 GiB
그 외 65개                    잔여 — 아래
```

### 권장 구조 밖 65개 (4.27 GiB) — 전부 성격 확정

```
분류                        n   bytes(MiB)   성격
──────────────────────────────────────────────────────────────────────
RESIDUAL_DIAGNOSTIC_RUN    10    4,349.29   _v2_* · _tmp_ph · _trunc_*_example
RESIDUAL_OUTPUT_DIR         3       12.14   eval_results · logs · v2_dryrun_audit
RESIDUAL_LOG               40        8.30   생성·렌더 로그
RESIDUAL_DIAGNOSTIC_IMAGE   1        0.95   _floor_catalog.png
RESIDUAL_ONE_OFF_SCRIPT    11        0.03   일회성 repack/zip/stress 스크립트
──────────────────────────────────────────────────────────────────────
                           65    4,370.71
```

```
UNKNOWN / 미분류            0     ← 65개 전부 분류됨
분류되지 않은 top-level ZIP  0     ← 루트 ZIP 0개 (Stage 2-D1 에서 전부 이동)
역할 불명 dataset            0
current path / old path 중복  0
이동 완료 source 잔존        0
```

이 65개는 **이번 범위(3 cohort)에 포함되지 않았다.** 48개는 Stage 2-A `archive.csv` 에
이동 계획이 있으나 `executed=no` 다.

## archive/ 구조 (depth 1 = 151)

```
archive/packages/
├── background_sources/        3   Stage 2-C2 C2A
├── dataset_bundles/          14   Stage 2-D1 D1A       (75.21 GiB)
└── corrupt/                   1   Stage 2-D1 D1B       (BadZipFile 보존)
archive/legacy_datasets/
├── redistributable/          11   Stage 2-D1 D1C
├── noai_baked/                3   Stage 2-D1 D1C       (릴리스 제외)
└── partial/                   1   Stage 2-D1 D1C
archive/legacy_scenes/
├── snapshots/                 6   ★ Stage 2-D1.1 D11A
└── blender_backups/           4   ★ Stage 2-D1.1 D11A
archive/legacy_assets/         0   Stage 2-A 뼈대 (빈 폴더, 삭제하지 않음)
archive/superseded_runs/       0   같음
archive/nonredistributable/    0   같음 — UNRESOLVED_LICENSE 0건이라 쓰지 않았다
archive/unidentified/          0   같음
archive/corrupt/               0   같음 (실제 corrupt 는 packages/corrupt/)
archive/_noai_quarantine_usd/  3   KEEP_QUARANTINE (scene_2.usd · scene_3.usd · README)
그 외 136                          진단·중간 산출물 (Stage 2-A 계획 미실행분)
```

`legacy_scenes/` 가 **처음으로 채워졌다** — Stage 2-D1 에서 rollback 했던 10건이
chained-ledger 로 검증 사슬을 유지하며 들어갔다.

빈 폴더 7개는 그대로 두었다 (**삭제 금지**).

## 남은 KEEP (문서화된 것)

```
항목                             위치                                   유지 이유
────────────────────────────────────────────────────────────────────────────────────
production_scene                assets/scenes/production/blender_scene/  registry active
experimental_scene              같은 폴더                                registry active
rollback blend 4                같은 폴더                                rollback 사슬
  synth_data_scene.blend / _portable.blend /
  _portable_candidate_20260729.blend1 / _portable_stage2c2_candidate.blend1
UNREFERENCED_WEIGHT 4           weights/                                data/pallet 밖 ·
                                                                        gitignored · 목적지 미정
                                                                        삭제 후보 아님
```

## 남은 quarantine (배포 금지 문서화)

```
data/pallet/isaac_assets/                    4.05 GiB  NVIDIA EULA (ledger B6)
data/pallet/archive/_noai_quarantine_usd/    0.70 MiB  NoAI USD (ledger B1)
                                                       — 격리 위치 자체가 라이선스 근거
data/pallet/archive/legacy_datasets/noai_baked/  3개   NoAI baked 렌더 산출물
```

전부 `_DISTRIBUTION_EXCLUDE.txt` 에 등록돼 있다 (problems 0 / leaks 0 / stale 0).

## 판정

### D11_SCOPE_COMPLETE → **부분 달성 (D11A 만)**

```
조건                                              결과
──────────────────────────────────────────────────────────────────────────
D1D 10건 chained-ledger verify                    ✓ 10/10 · C2C failures 0
BLOCKED_REFERENCE 전부 registry 전환·이동          ◐ 전환 완료 / 이동 미실행
BLOCKED_UNKNOWN 전부 provenance 판정·이동          ◐ 판정 완료 / 이동 미실행
SHA256 mismatch = 0                               ✓
rollback 가능                                     ✓
```

이동이 2/3 cohort 에서 미실행이므로 `D11_SCOPE_COMPLETE` 라고 쓰지 않는다.
사유는 **hash read 예산**이다 (§6 상한 20 GiB vs 필요 61.33 GiB).

### FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE → **false**

```
UNKNOWN remaining = 0                    ✓
unclassified top-level entry = 0         ✓ (65개 전부 분류됨)
current broken ref = 0                   ✓
exclusion leak = 0                       ✓
prior ledger chain 전부 검증              ✓ (C2C chain 10/10, 나머지 원장은 chain 불필요)
남은 KEEP 최종 위치·이유 문서화            ✓ (위)
남은 quarantine 최종 위치·배포금지 문서화   ✓ (위)
BLOCKED 8건 처리 완료                     ✗ 이동 미실행
```

### FULL_PHYSICAL_MINIMAL_TREE → **false**

top-level 에 권장 8 + `isaac_assets`(quarantine) + 잔여 65 = 74. 최소 트리가 아니다.

## 남은 일

```
1  D11B 이동   registry 전환 완료 상태. 예산 승인 후 이동 + 키 값 1줄 변경
              (D1-003 은 successor chain 추가 필요 — C2C 구성원)
2  D11C 이동   PROVEN_NOAI 판정 완료. 예산 승인 후 이동 + exclusion 4경로 정정
3  잔여 65+136 Stage 2-A archive.csv 계획(executed=no 202행) 재활성화 검토
4  weight 4    목적지 결정 + 별도 승인
```
