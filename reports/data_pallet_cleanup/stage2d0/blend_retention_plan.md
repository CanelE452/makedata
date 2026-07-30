# §9 blend / blend1 보존 계획

대상: `data/pallet/assets/scenes/production/blender_scene/` 의 `.blend` · `.blend1` **17개** (4.55 GB)
원자료: `blend_inventory.csv` · `blend_relationships.csv`

## 역할 판정 — 이름이 아니라 SHA256 과 registry 로 [확인]

```
파일                                                    bytes         sha256        역할
──────────────────────────────────────────────────────────────────────────────────────────────────
synth_data_scene_portable_stage2c2.blend            358,898,838  8cb4109adc6d  ACTIVE_RUNTIME (registry)
_sandbox_palletobj_production.blend                 157,014,946  b497bea8f008  ACTIVE_RUNTIME
                                                                               (registry experimental_scene)
synth_data_scene.blend                              358,917,479  46f436dc8d93  ROLLBACK_CRITICAL
synth_data_scene_portable_candidate_20260729.blend1 358,917,479  46f436dc8d93  ROLLBACK_CRITICAL (동일 내용)
synth_data_scene_portable.blend                     358,898,907  5cad94e59d67  ROLLBACK_CRITICAL
synth_data_scene_portable_stage2c2_candidate.blend1 358,898,907  5cad94e59d67  ROLLBACK_CRITICAL (동일 내용)
──────────────────────────────────────────────────────────────────────────────────────────────────
synth_data_scene121.blend                           265,089,901  6a087f9893d5  COLD_ARCHIVE
synth_data_scene12.blend1                           265,089,900  429d0055c0dc  COLD_ARCHIVE
synth_data_scene12.blend                            257,666,344  8bcd9fea01c0  COLD_ARCHIVE
synth_data_scene.REBAKE_WIP.blend1                  246,594,559  36bea3b9dd47  COLD_ARCHIVE
synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend 245,967,843 0acddbf5864b  COLD_ARCHIVE
synth_data_scene.REBAKE_WIP.blend                   245,967,843  0acddbf5864b  COLD_ARCHIVE (동일 내용)
synth_data_scene.blend1                             245,862,236  1464c8b60f25  COLD_ARCHIVE
synth_data_scene_indoor.blend                       245,480,818  492f906e4a5a  COLD_ARCHIVE
synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend 245,475,973 a66e06b310bb  COLD_ARCHIVE
_sandbox_parking_lot_check.blend1                   137,789,046  379cd41c5cc8  COLD_ARCHIVE
_sandbox_parking_lot_check.blend                    137,789,005  d0b13149285c  COLD_ARCHIVE
```

`.blend1` 5개를 **이름만 보고 불필요로 판정하지 않았다** — SHA256 으로 내용을 확인했고,
그 결과 2개가 rollback-critical 파일과 byte-identical 이었다.

## byte-identical 쌍 3건 — DUPLICATE_FILE_EXACT [확인]

```
sha256      파일 A                                             파일 B
─────────────────────────────────────────────────────────────────────────────────────────────
46f436dc…   synth_data_scene.blend                             …_portable_candidate_20260729.blend1
5cad94e5…   synth_data_scene_portable.blend                    …_portable_stage2c2_candidate.blend1
0acddbf5…   synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend  synth_data_scene.REBAKE_WIP.blend
```

앞 2쌍은 Stage 2-C1 / 2-C2 가 candidate 를 저장할 때 Blender 가 만든 자동 백업이고,
그 내용은 각각 직전 원본과 같은 바이트다. `DUPLICATE_FILE_EXACT` 이지만 **둘 다 보존**한다 —
`.blend1` 쪽을 치우면 rollback 사슬의 이중 안전장치가 사라진다.

## BACKUP_OF 를 선언하지 않은 이유

지시서의 `BACKUP_OF` 는 ① Blender 내부 구조 signature 일치 ② 생성 시점과 history 일치
③ 역할이 문서로 확인 — 3조건을 요구한다. `.blend1` 5개 중 2개는 SHA256 이 원본과 같아 ①이
자동 충족되지만, 나머지 3개(`synth_data_scene.blend1`, `synth_data_scene12.blend1`,
`_sandbox_parking_lot_check.blend1`)는 **구조 signature 를 읽지 않았다**(Blender 를 여러 번
띄워야 하고 이번 단계는 개방을 최소화했다).

따라서 그 3개는 `COLD_ARCHIVE` 로만 두고 `BACKUP_OF` 를 선언하지 않는다.
[추정] 이름·크기·mtime 상 각 원본의 직전본으로 보이지만 **검증하지 않았다.**

## Stage 2-D1 제안

```
status               대상                                        목적지
──────────────────────────────────────────────────────────────────────────────────────────────
BLOCKED_ACTIVE       stage2c2.blend · _sandbox_palletobj_production   (이동 없음)
BLOCKED_ROLLBACK     synth_data_scene.blend · portable.blend +
                     두 candidate .blend1                             (이동 없음, 별도 승인 필요)
SAFE_MOVE_CANDIDATE  COLD_ARCHIVE 11개 (2.87 GB)                      archive/legacy_scenes/
                                                                      ├ snapshots/       .blend 8개
                                                                      └ blender_backups/ .blend1 3개
```

주의: `_sandbox_parking_lot_check.blend` 는 registry 에 없지만 과거 실행 스크립트가 이름을
언급한다(`_raw_refs` 기록). 이동 시 그 스크립트의 실행 가능성이 깨지는지 D1 실행 전에
재확인해야 한다.
