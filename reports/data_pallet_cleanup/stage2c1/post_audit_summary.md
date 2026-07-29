# §7 candidate 재개방 검증 · §9 no-render 감사

candidate 는 저장 후 Blender 를 **완전히 종료하고 새 headless 프로세스**에서 다시 열었다.
저장 직전 메모리 상태가 아니라 디스크에 기록된 결과를 검증한 것이다.

원자료: `post_audit/external_paths.csv` · `post_audit/verify_result.json` ·
`post_audit/structure_diff.json` · `post_audit/referenced_file_hashes.csv` ·
`post_audit/mapping_crosscheck.json` · `candidate_no_render_audit.json`

## 1. 외부경로 [확인, 실행함]

```
항목                                     before(원본)   after(portable)   기대   판정
──────────────────────────────────────────────────────────────────────────────────────
image datablock 총계                        603            603           동일    ✓
BLOCKED_ABSOLUTE                            228              0             0     ✓
MISSING_CURRENT                               1              0             0     ✓
SAFE_RELATIVE                               286            515             -     ✓ (286+228+1)
SAFE_PACKED_OR_GENERATED                     88             88           동일    ✓
raw 가 드라이브 절대경로                      229              0             0     ✓
raw 가 사용자별 절대경로                        1              0             0     ✓
non-packed 상대경로인데 resolve 실패            0              0             0     ✓
//textures\ 참조                            158            158           동일    ✓
//..\distractors\ 참조                      128            356        128+228    ✓
packed 총계                                  86             86           동일    ✓
```

## 2. mapping SHA256 대조 [확인, 실행함]

계획 228건 각각에 대해 **변환 전 절대경로가 가리키던 파일의 SHA256** 과
**재개방 후 상대경로가 resolve 한 파일의 SHA256** 을 비교했다.

```
mapping 검사 수            228 / 228
SHA256 mismatch              0
경로 mismatch                0   (저장된 raw 를 슬래시 정규화해 계획값과 비교)
resolve 실패                 0
basename 충돌로 인한 오결선   0   (같은 basename 이 서로 다른 내용을 갖는 경우 0건)
```

절대경로를 basename 으로 다시 찾지 않았다. 계획은 **기존 절대경로가 가리키던 그 파일**을
기준으로만 만들었고, 파일이 없거나 허용 루트를 벗어나면 BLOCKED 로 떨어지게 했다
(`blend_path_utils.build_mapping`).

## 3. 계획 외 변경 [확인]

```
image 이름 집합 (603개)      before == after                       ✓
경로가 바뀐 datablock          229 = 228 (재작성) + 1 (repoint)      ✓
계획에 없는 변경                 0                                   ✓
계획됐는데 안 바뀐 것             0                                   ✓
제거된 datablock                0                                   ✓
```

## 4. 구조 diff [확인]

`post_audit/structure_diff.json` — **diffs = 0**.

비교 대상: scenes / view_layers / collections / objects / meshes / materials / node_groups /
worlds / cameras / lights / images / textures 개수, object·collection·material·world·camera·
node_group **이름 집합**, active scene, render engine·해상도·resolution_percentage·
film_transparent·output filepath, Cycles samples, EEVEE taa_render_samples,
color management(view_transform / look / exposure / gamma / display_device / sequencer),
카메라 matrix_world(4x4, 소수 9자리) · lens · sensor_width · sensor_fit · shift_x/y,
Pallet_* 목록, Dist_ root 목록.

```
scenes 1   view_layers 1   collections 2   objects 1,122   meshes 597   materials 350
node_groups 1   worlds 1   cameras 1   lights 1   images 603   textures 0
Pallet_0~3      Dist_ root 209      active camera RenderCamera
BLENDER_EEVEE 640x480   Filmic / Medium Contrast / gamma 1.05 / sRGB
(before / after 두 열이 전부 동일)
```

## 5. §9 no-render 감사 (candidate / 승격 후 stable 동일 결과) [확인, 실행함]

```
검사                                      결과
──────────────────────────────────────────────────────────────
blender_config import                     OK
pallet_data_paths import                  OK
v2_realize import                         OK
registry missing                          0
Pallet_0~3                                존재
Distractors_v2 컬렉션                      존재
Dist_ root                                209
distractor manifest rows                  209
background root / configured assets       존재
image missing                             0
material·world·nodegroup image node 누락    0   (마젠타 원인 후보 0)
//textures resolve                        158 / 158
//../distractors resolve                  356 / 356
HDRI decode                               30 / 30   (v2 constrained pool = 28)
floor texture decode                      42 / 42
wood texture decode                       27 / 27
```

## 6. 잔존 사항 — 정직한 기록

### packed datablock 17건이 옛 임시폴더 경로 문자열을 들고 있다 [확인, 수정 안 함]

```
예) //..\..\..\..\..\..\AppData\Local\Temp\tmpg7cv8vw7\textures\Barrel_01_explosive_diff_1k.jpg
```

- 17건 **전부 packed** (픽셀이 `.blend` 안에 들어 있어 파일을 읽지 않는다)
- 전부 `//` 상대표기 — 드라이브 절대경로가 아니다
- **원본과 candidate 가 완전히 동일**(이번 작업이 만든 것도, 건드린 것도 아니다)
- 과거 Poly Haven/Sketchfab 자산을 임시폴더에 풀어 import 한 흔적

§6 규칙 "packed image 는 수정하지 않음" 에 따라 그대로 두었다.
**"absolute user-specific path 0"** 게이트는 충족한다(위 표의 `raw 가 사용자별 절대경로 = 0`).
남은 것은 inert 한 문자열이다.

### 상대경로 구분자는 Windows 백슬래시다 [확인]

`img.filepath` 에 forward-slash(`//../distractors/...`)로 넣었으나 Blender 가 저장 시
네이티브 구분자로 정규화해 `//..\distractors\...` 로 기록했다. 기존 158건(`//textures\`)·
128건과 **같은 표기**라 파일 내부는 일관적이다. 다른 OS 에서 여는 경우의 구분자 처리는
Blender 쪽 동작이라 여기서 검증하지 않았다 — `[추정]` 으로 남긴다.

### Blender 백업 파일 1개가 새로 생겼다 [확인]

`data/pallet/blender_scene/synth_data_scene_portable_candidate_20260729.blend1`
(358,917,479 bytes, SHA256 `46f436dc…` = **원본과 동일 바이트**).
`save_as_mainfile` 이 자동 생성한 직전본이다. 삭제하지 않았다.
이름이 이미 없는 candidate 를 가리키므로 Stage 2-C2 정리 대상으로 남긴다.
