# §11 stable 승격

## 승격 게이트 [확인, 전부 통과]

```
조건                                        결과                                     판정
────────────────────────────────────────────────────────────────────────────────────────
source SHA256 불변                          46f436dc… (작업 전 == 작업 후)            ✓
candidate 재개방 성공                        새 headless 프로세스에서 open OK          ✓
absolute external path                      0                                        ✓
user-specific **절대** path                  0                                        ✓
missing path                                0                                        ✓
mapping SHA256 mismatch                     0 / 228                                  ✓
구조 diff                                    0                                        ✓
no-render audit                             전 항목 통과 (registry 0 missing 등)      ✓
unit tests                                  614 passed, skip 0, fail 0               ✓
local integration                            26 passed, skip 0, fail 0               ✓
golden overlay                               51 passed, skip 0                       ✓
5k dry-run FrameSpec checksum               938f387d… 동일 (덤프 파일 byte 동일)       ✓
5k dry-run proposals digest                 3cd365ee… 동일, 12/12 PASS               ✓
candidate smoke                             2 / 2 delivered, 87 검사 실패 0           ✓
magenta                                     0 (record + 픽셀 실측)                    ✓
registry source 경로 audit                   ok=22 missing=0                          ✓
```

## 승격 절차 [확인, 실행함]

```
1. stable 경로 부재 확인                    synth_data_scene_portable.blend 없음        ✓
2. same-volume rename (overwrite 없음)      candidate -> stable                        ✓
3. rename 전후 SHA256                       5cad94e5… == 5cad94e5…                     ✓
4. candidate 경로 소멸 확인                  존재하지 않음                                ✓
5. 원본 유지                                 존재, SHA256 불변, mtime 불변               ✓
6. 원본을 archive 로 이동하지 않음            그대로 blender_scene/ 에 있음                ✓
7. 원본 이름 변경하지 않음                    synth_data_scene.blend                     ✓
```

```
파일                                              크기          SHA256        mtime
──────────────────────────────────────────────────────────────────────────────────────────
synth_data_scene.blend            (rollback)  358,917,479   46f436dc…   2026-07-24 19:39:00.380291100
synth_data_scene_portable.blend   (active)    358,898,907   5cad94e5…   2026-07-29 16:56:38.267575100
```

두 파일은 별개다(`os.path.samefile` = False). 크기 차 18,572 bytes = 절대경로가 상대경로로
짧아진 만큼.

## registry 변경

`config/synthetic/pallet_paths.yaml`

```
key                              before                                          after
──────────────────────────────────────────────────────────────────────────────────────────────
production_scene                 blender_scene/synth_data_scene.blend            blender_scene/synth_data_scene_portable.blend
production_scene_rollback_source (없음)                                           blender_scene/synth_data_scene.blend   ← 신규
production_scene_textures        blender_scene/textures                          (변경 없음)
experimental_scene               blender_scene/_sandbox_palletobj_production.blend (변경 없음 — 지시대로)
그 외 18키                        (변경 없음)
```

`pallet_data_paths.py --audit` → **ok=22 missing=0 absent_optional=0**
(21 → 22 는 `production_scene_rollback_source` 키가 늘어난 것.)

원본을 registry 에서 지우지 않고 **명시적 rollback source 키로 남긴 이유**: 이 저장소 규칙상
registry 는 "지금 실제로 있는 경로"를 담는다. 원본은 실재하고 rollback 대상이므로 이름을 갖고
있어야 한다. 이름이 없으면 다음 단계에서 "정체불명의 큰 .blend" 로 보여 정리 대상이 될 위험이 있다.

## 테스트로 못박은 불변식 (신규)

```
unit  (test_pallet_data_paths_unit.py, RegistryContentRules)
  - production_scene 은 portable blend 여야 한다
  - production_scene_rollback_source 는 원본이어야 하고 둘은 달라야 한다
  - registry 어느 키도 "_candidate_" 가 들어간 날짜 임시 파일명을 가리키면 안 된다

integration (test_pallet_data_paths_local.py)
  - production_scene basename == synth_data_scene_portable.blend, rollback 은 원본이고 실재
  - production_scene 이 dated candidate 가 아님
  - 원본 .blend 의 SHA256 이 46f436dc… 여야 한다 (보존 회귀 방지)
```
