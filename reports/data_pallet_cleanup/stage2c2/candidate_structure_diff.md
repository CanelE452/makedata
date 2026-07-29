# §12 candidate 재개방 검증 · 구조 diff

candidate 는 저장 후 Blender 를 완전히 종료하고 **새 headless 프로세스**에서 다시 열었다.

원자료: `candidate_post_audit.csv` · `candidate_post_audit_paths.csv` ·
`candidate_structure_diff.json` · `candidate_referenced_hashes.csv` · `candidate_crosscheck.json`

## 1. 외부경로 [확인, 실행함]

```
항목                              이동 전(C1 portable)   이동 후(C2 candidate)   기대   판정
──────────────────────────────────────────────────────────────────────────────────────────
image datablock 총계                     603                   603              동일    ✓
절대 외부경로                              0                     0                0     ✓
사용자별 **절대** 경로                       0                     0                0     ✓
missing path                              0                     0                0     ✓
packed                                   86                    86              동일    ✓
textures resolve                        158                   158              158    ✓
distractor resolve                      356                   356              356    ✓
HDRI 외부 상대경로                          1                     1                1     ✓
```

resolve 기준(문자열 형태 무관)으로 셌다. 문자열은 바뀌었지만 **가리키는 파일은 그대로**다.

## 2. target manifest 대조 [확인]

이동 **전에** 각 datablock 이 가리키던 파일의 절대경로 + SHA256 을 고정해 두고
(`blend_rebase_target_manifest.csv`), 이동 후 그 정체가 유지되는지 대조했다.

```
target manifest rows              603
  SKIP_PACKED_OR_GENERATED         88   (수정하지 않음)
  KEEP_RELATIVE                   158   //textures/... — blend 와 함께 이동해 문자열 그대로 유효
  REBASE                          357   distractor 356 + HDRI 1
  BLOCKED                           0   unknown root 없음

대조 결과
  검사 대상 row                     515
  target path mismatch               0
  target SHA256 mismatch             0
  datablock 누락                     0
  실제 변경된 datablock              357   (= REBASE 수)
  계획 외 변경                        0
  계획됐는데 안 바뀐 것                 0
```

### 실제 계산된 새 상대경로 (하드코딩 아님)

```
분류        이동 전                                          이동 후
──────────────────────────────────────────────────────────────────────────────────────────────
textures    //textures\Image_0.jpg                           //textures/Image_0.jpg      (동일)
distractor  //..\distractors\medium\ph__SchoolChair_01\...    //../../../distractors/library/medium/ph__SchoolChair_01/...
HDRI        //..\assets\lighting\hdri\library\factory_yard…   //../../../lighting/hdri/library/factory_yard_2k.hdr
```

`bpy.path` 없이 검증된 helper(`blend_path_utils.to_blend_relative`)로 **계산**했고,
계산 결과가 정본이다. 저장 시 Blender 가 네이티브 구분자(백슬래시)로 정규화한다.

factory_yard: `//..\..\..\lighting\hdri\library\factory_yard_2k.hdr` — resolve 후 SHA256
`71d5b32c0e179f5b…` 로 이동 전과 동일.

## 3. 구조 diff: **0**

```
항목                    이동 전   이동 후
────────────────────────────────────────
scenes                     1        1
view_layers                1        1
collections                2        2
objects                1,122    1,122
meshes                   597      597
materials                350      350
node_groups                1        1
worlds                     1        1
cameras                    1        1
lights                     1        1
images                   603      603
textures                   0        0
packed images             86       86
```

이름 집합(objects / collections / materials / worlds / cameras / node_groups),
active scene, render engine·해상도·resolution_percentage·film_transparent·output filepath,
Cycles samples, EEVEE taa_render_samples, color management(view_transform / look / exposure /
gamma / display_device / sequencer), 카메라 matrix_world(4×4 소수 9자리)·lens·sensor_width·
sensor_fit·shift_x/y, `Pallet_0~3`, `Dist_` root 209 — **전부 동일**.

허용되지 않은 차이 0건 → 승격 게이트 통과.
