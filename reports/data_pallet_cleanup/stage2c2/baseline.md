# Stage 2-C2 이동 전 기준선

일시: 2026-07-29 / branch `chore/data-pallet-stage2c2-final-layout` (26f2194 = main = origin/main 에서 분기)

## PRE-FLIGHT [확인, 실행함]

```
repo root              E:/CODING/GitHub/FoundationPose
branch (작업 전)         main
HEAD / origin/main     26f21942b5ea38bf34af2659a6955a481a2c97b8  (동일)
git status             clean
작업 branch             chore/data-pallet-stage2c2-final-layout  (신규, 기존 동명 branch 없음)
디스크 E:               free 1,261.7 GB
실행 중 blender.exe     0개
source/destination     전부 같은 볼륨 E:  -> rename 이동 가능
```

## 이동 대상 3 source [확인]

```
source                       files    bytes            GB      archive  license
──────────────────────────────────────────────────────────────────────────────────
data/pallet/background          77      291,054,721   0.271       3        2
data/pallet/distractors      1,161    1,958,754,064   1.824       0       10
data/pallet/blender_scene      173    3,836,556,170   3.573       0        0
──────────────────────────────────────────────────────────────────────────────────
합계                         1,411    6,086,364,955   6.086      (상한 10GB 이내)
symlink/reparse 0 · 접근 불가 0
```

## Stage 2-C1 산출물 무결성 [확인]

```
synth_data_scene.blend           358,917,479  46f436dc8d9302a6…  (원본, 수정 0)
synth_data_scene_portable.blend  358,898,907  5cad94e59d678b01…  (active)
```

## 기준 측정값 [확인, 실행함]

```
항목                          값                          기대치            일치
──────────────────────────────────────────────────────────────────────────────────
A registry audit              ok=22 missing=0             missing=0         ✓
                              production_scene=portable   portable          ✓
                              rollback_source=original    original          ✓
B default unit                614 passed, skip 0          >=614             ✓
C local integration            26 passed, skip 0          >=26              ✓
D golden overlay               51 passed, skip 0          >=51              ✓
E Stage 2-A 원장               146 / 6,921 / failures 0    146 / 6,921       ✓
                              sha256 fe1adc26…            불변              ✓
F Stage 2-B B1                 4 / 3,220, hash all         unhashed 0       ✓
  Stage 2-B B2                 3 / 68,   hash all          failures 0       ✓
                              B1 sha256 43461e47… / B2 0d0c06a8…            (기록)
G blend audit (active scene)  absolute 0 / missing 0                        ✓
                              //textures 158 · //../distractors 356         ✓
                              Dist_ root 209 · Pallet_0~3 · HDRI 30/30      ✓
                              floor 42/42 · wood 27/27 · node 누락 0         ✓
H 5k FrameSpec                accepted 4,313 / rejected 687                  ✓
                              sha256 938f387d…                              ✓
I 5k proposals                accepted 4,439 / digest 3cd365ee… / 12/12     ✓
```

> 5k dry-run 은 하네스가 두 개이고 값이 다르다(`v2_pipeline --dump` = 4,313 / `938f387d…`,
> `dryrun_v2_proposals` = 4,439 / `3cd365ee…`). 둘 다 측정했다. 상세는 Stage 2-C1 `baseline.md`.

## background archive 3개 [확인, 실측]

```
파일                                        bytes        entries  uncompressed  open  SHA256
────────────────────────────────────────────────────────────────────────────────────────────────
parking_lot.zip                          101,186,943      45     103,254,269   yes   b5d36f5fd413e3bd…
modular_buildings_industrial_area.zip     28,110,712      30      29,569,627   yes   3f233a6be04a71ef…
modular_buildings_industrial_area..zip    28,110,712      30      29,569,627   yes   3f233a6be04a71ef…
────────────────────────────────────────────────────────────────────────────────────────────────
합계                                     157,408,367
```

`modular_buildings_industrial_area(.)zip` 2개는 **SHA256 동일**(이름에 점이 하나 더 있는 중복 다운로드).
둘 다 보존 이동한다 — 삭제하지 않는다.

runtime/code/config/test 참조 **0건**, gltf/mtl 의존 **0건**
(`scene.gltf` 의 buffers/images URI 는 전부 `scene.bin` / `textures/*` 상대경로).

## `.blend` 계열 분류 [확인, SHA256 기준]

이름이 아니라 해시로 역할을 판정했다.

```
파일                                                   bytes       sha256        역할
────────────────────────────────────────────────────────────────────────────────────────────────
synth_data_scene.blend                             358,917,479  46f436dc…  ORIGINAL_ROLLBACK_SOURCE
synth_data_scene_portable_candidate_20260729.blend1 358,917,479 46f436dc…  BLENDER_AUTO_BACKUP
                                                                            (내용은 원본과 동일 바이트)
synth_data_scene_portable.blend                    358,898,907  5cad94e5…  ACTIVE_PORTABLE (Stage 2-C1)
synth_data_scene121.blend                          265,089,901  6a087f98…  LEGACY_SCENE_SNAPSHOT
synth_data_scene12.blend1                          265,089,900  429d0055…  BLENDER_AUTO_BACKUP
synth_data_scene12.blend                           257,666,344  8bcd9fea…  LEGACY_SCENE_SNAPSHOT
synth_data_scene.REBAKE_WIP.blend1                 246,594,559  36bea3b9…  BLENDER_AUTO_BACKUP
synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend 245,967,843 0acddbf5… LEGACY_SCENE_SNAPSHOT
synth_data_scene.REBAKE_WIP.blend                  245,967,843  0acddbf5…  LEGACY_SCENE_SNAPSHOT
synth_data_scene.blend1                            245,862,236  1464c8b6…  BLENDER_AUTO_BACKUP
synth_data_scene_indoor.blend                      245,480,818  492f906e…  LEGACY_SCENE_SNAPSHOT
synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend 245,475,973 a66e06b3… LEGACY_SCENE_SNAPSHOT
_sandbox_palletobj_production.blend                157,014,946  b497bea8…  EXPERIMENTAL (registry)
_sandbox_parking_lot_check.blend1                  137,789,046  379cd41c…  BLENDER_AUTO_BACKUP
_sandbox_parking_lot_check.blend                   137,789,005  d0b13149…  EXPERIMENTAL
```

동일 내용 그룹 2쌍:
`synth_data_scene.blend` == `..._candidate_20260729.blend1`,
`...POSTBAKE_CLEAN...` == `...REBAKE_WIP.blend`.

**이번 단계에서는 어느 것도 삭제·개별 이동하지 않았다.** blender_scene 폴더째 옮겼을 뿐이다.
`.blend1` 정리(ARCHIVE_BACKUP 후보)는 Stage 2-D 로 넘긴다.

기계 판독용 사본: `baseline_checksums.json` · `source_inventory.csv` · `source_hashes.csv`
