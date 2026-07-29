# §3 production `.blend` 외부경로 읽기 전용 감사

- 대상: `data/pallet/blender_scene/synth_data_scene.blend`
- Blender 5.1.1 headless, **읽기만** — render / save / pack / unpack / make_paths_* / 수정 일체 없음
- 원자료: `blend_external_paths.csv` (603행) · `blend_dependency_audit.json`

## 결과 요약 [확인, 실행함]

```
verdict                건수   내용
────────────────────────────────────────────────────────────────────────────────
BLOCKED_ABSOLUTE       356   전부 data/pallet/distractors/... 를 가리키는 **절대경로**
                             예) E:\CODING\GitHub\FoundationPose\data\pallet\distractors\
                                 small\ph__adjustable_wrench\textures\adjustable_wrench_diff_1k.jpg
                             파일은 실재하지만(exists=True) 경로가 이 머신에 못박혀 있다.
SAFE_RELATIVE          246   //textures/... 상대참조 158 + packed 86 + generated 2
MISSING_CURRENT          1   factory_yard_2k.hdr ->
                             C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\...
                             (**다른 워크스페이스** 경로. 이동 이전부터 이미 깨져 있었다)
────────────────────────────────────────────────────────────────────────────────
libraries(링크된 .blend)  0   외부 .blend 링크 없음
movieclips/fonts/sounds  0
```

씬 구성: images 603 · materials 350 · objects 1,122 · collections 2(`Collection`, `Distractors_v2`)
· `Dist_*` 209 · `Pallet_0~3` 4 · `blender_scene/textures/` 158 파일.

## 감사 도중 잡은 자체 버그 [확인]

첫 실행에서 `BLOCKED_ABSOLUTE=514` 가 나왔는데, 그중 158건은 오탐이었다.
`is_within()` 이 `os.path.commonpath()` 결과(백슬래시)와 forward-slash 로 정규화한 문자열을
비교해 **항상 False** 였다. `normcase` 만 쓰도록 고치고 재실행해 위 표의 값을 얻었다.
(같은 실수를 Stage 2-A.1 에서 트랜잭션 스크립트에 심을 뻔했고, 거기서는 commonpath 를
제대로 쓰고 있다.)

## 판정

### `data/pallet/distractors` → **이동 BLOCKED**

production `.blend` 안의 이미지 356개가 이 폴더를 **절대경로**로 참조한다.
폴더를 옮기면 그 356개가 전부 끊기고, 씬은 텍스처 없이(회색/마젠타) 렌더된다.
복구하려면 `.blend` 를 rewrite 해야 하는데 이번 단계에서 금지되어 있다.

> **부수 발견**: 이 절대경로들 때문에 `synth_data_scene.blend` 는 **이미 이 머신에 못박혀 있다.**
> 다른 워크스테이션에서 열면 distractor 텍스처 356개가 전부 깨진다.
> `MISSING_CURRENT` 1건이 바로 그 증거다 — 과거에 `C:\Users\User\Documents\GitHub\...` 에서
> 작업한 흔적이 그대로 남아 있다. Stage 2-C 에서 `make_paths_relative` + 재저장으로
> 해소해야 할 별도 과제다.

### `data/pallet/blender_scene` (B4) → **이동 BLOCKED**

§3 이동 조건 대비:

```
조건                                          결과
──────────────────────────────────────────────────────────────────────
BLOCKED_ABSOLUTE = 0                          ✗ 356
MISSING_CURRENT = 0                           ✗ 1
blender_scene/textures 내부 상대경로 전부 존재    ✓ 158/158
companion texture count                       ✓ 158
.blend 자체 수정 불필요                          ✓ (수정 안 함)
```

두 조건을 채우지 못했으므로 B4 는 계획에서 제외했다.
**`.blend` 를 고쳐서 억지로 통과시키지 않았다.**

### 다른 cohort 에는 영향 없음 [확인]

`.blend` 가 참조하는 외부 경로 중 `hdri` · `models_usd` · `pallets_v2_add` · `background` ·
`textures_wood` · `textures_floor` · `trunc_addon_v1_pilot` · `real_data` 를 가리키는 것은
**0건**이다(단 하나 있는 hdri 참조는 위의 다른 워크스페이스 경로라 이 트리와 무관).
따라서 B1/B2 와 background 는 `.blend` 관점에서 안전하다.

## 이동 후 재확인 [확인, 실행함]

`postmove_blender_asset_audit.json`:

```
missing_images        1   (이동 전과 **동일한** factory_yard_2k.hdr — 신규 파손 0)
missing_libraries     0
Pallet_0~3            존재
Distractors_v2        존재, Dist_ = 209
//textures resolve    158 성공 / 0 실패
HDRI load             30/30 성공 (새 경로 assets/lighting/hdri/library)
floor texture decode  42/42 성공
wood texture decode   27/27 성공
pallet model 파일      8
background glTF        2
distractor manifest    209 rows
registry audit         ok=21 missing=0
```
