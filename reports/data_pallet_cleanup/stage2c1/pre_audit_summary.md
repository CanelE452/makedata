# §3 원본 `.blend` 읽기 전용 재감사

- 대상: `data/pallet/blender_scene/synth_data_scene.blend`
- Blender 5.1.1 headless, **읽기만** — render / save / pack / unpack / make_paths_* / filepath 변경 없음
- 실행 전후 SHA256 `46f436dc…` **동일**
- 원자료: `pre_audit/external_paths.csv` (603행) · `pre_audit/external_paths.json` ·
  `pre_audit/source_structure.json` · `pre_audit/source_blend_sha256.txt`

## 결과 [확인, 실행함]

```
verdict                      건수   내용
─────────────────────────────────────────────────────────────────────────────────────
BLOCKED_ABSOLUTE             228   data/pallet/distractors/... 를 가리키는 드라이브 절대경로
                                   예) E:\CODING\GitHub\FoundationPose\data\pallet\distractors\
                                       medium\ph__SchoolChair_01\textures\SchoolChair_01_diff_1k.jpg
                                   파일은 전부 실재(exists=True). 경로가 이 머신에 못박혀 있다.
SAFE_RELATIVE                286   //textures\... 158 + //..\distractors\... 128 (둘 다 non-packed)
SAFE_PACKED_OR_GENERATED      88   packed 86 (그중 84 는 //.. 경로 문자열 보유) + VIEWER 2
MISSING_CURRENT                1   factory_yard_2k.hdr ->
                                   C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\...
                                   (다른 워크스페이스 경로. 이동 이전부터 깨져 있었다)
─────────────────────────────────────────────────────────────────────────────────────
합계                         603
libraries / movieclips / fonts / sounds / cache_files / volumes / modifier cache : 0
```

원시 문자열 기준(판정 로직을 거치지 않은 사실):

```
filepath_raw 가 '//' 로 시작        370   (packed 84 + non-packed 286)
filepath_raw 가 드라이브 절대경로    229   (228 + factory_yard 1)
filepath_raw 가 빈 문자열             4   (packed 2 + VIEWER 2)
──────────────────────────────────────
                                    603
```

## 씬 구조 [확인]

```
scenes 1 (Scene) · view_layers 1 · collections 2 (Collection, Distractors_v2)
objects 1,122 · meshes 597 · materials 350 · node_groups 1 · worlds 1 (World)
cameras 1 (RenderCamera, active) · lights 1 · images 603 · textures 0
Pallet_0~3 존재 · Dist_ root 209
render BLENDER_EEVEE 640x480 · color management Filmic / Medium Contrast / gamma 1.05 / sRGB
```

## ★ Stage 2-B 보고값(356 / 158)과 다른 이유 [확인, 추적함]

지시서와 Stage 2-B 보고서는 `BLOCKED_ABSOLUTE=356`, `//textures=158`, `SAFE_RELATIVE=246` 을
기대했다. 이번 감사는 `228 / 158 / 286+88` 이 나왔다. **파일이 바뀐 것이 아니다** —
SHA256 은 `_docs/history/2026-07-26.md:10` 이 기록한 값과 지금까지 동일하다.

원인은 Stage 2-B 판정 로직의 **과다계상**이다. Stage 2-B 자신이 커밋한
`stage2b/blend_external_paths.csv` 를 열어 `BLOCKED_ABSOLUTE` 356행의 `filepath_raw` 를 세면:

```
raw 가 드라이브 절대경로   228
raw 가 '//' 로 시작        128    <- 이미 blend-상대경로인데 ABSOLUTE 로 분류됨
────────────────────────────
                          356
```

예: `//..\distractors\small\gso__Clue_Board_Game_Classic_Edition\materials\textures\texture.png`
— Stage 2-B CSV 에서 verdict=`BLOCKED_ABSOLUTE` 인데 raw 는 `//` 로 시작한다.
(Stage 2-B 는 감사 중 `//textures` 158건 오탐을 한 번 고쳤지만, `//..\distractors` 128건은
남아 있었다. 두 보고서의 "514" 라는 중간값이 그 흔적이다: 158+356 = 286+228 = 514.)

따라서 **실제 재작성 대상은 228건**이다. 차이가 전부 설명되므로 중단 기준에 해당하지 않는다.

### 이 정정이 Stage 2-C2 에 주는 의미

`distractors/` 이동 차단 사유가 바뀐다. "절대참조 356건 때문에 못 옮긴다"가 아니라
**"이미 128건이 `//..\distractors` 상대경로였고, 이번에 228건이 더해져 356건이 됐다.
폴더를 옮기면 이 356건의 상대경로를 rebase 해야 한다"** 가 정확한 서술이다.
절대경로였을 때와 마찬가지로 폴더 이동은 여전히 `.blend` 수정을 요구한다.
