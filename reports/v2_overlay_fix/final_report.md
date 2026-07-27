# v2 mask output policy + canonical overlay 복원 — 최종 보고서

작성 2026-07-28 / repo `E:/CODING/GitHub/FoundationPose` / branch `main` / HEAD `cf98fc6`(미커밋 작업)

이 문서는 **관찰(실측 수치·파일 수·테스트 결과)**과 **판정(설계가 타당한가)**을 분리해서 쓴다.
모든 사실 문장에 `[확인]`(실행흐름을 끝까지 추적했거나 실제로 돌려서 본 것) / `[추정]`(주석·변수명·관례에서
추론했고 미검증) 태그를 붙인다. 비율은 항상 분모를 함께 적는다.

세부 작업 로그는 `_docs/history/2026-07-28.md`(Section 1~9). 이 문서는 지시가 요구한 12항목 요약본이다.

---

## 1. 왜 현재 overlay가 archive 스타일이 아니었는지

관찰
- 2026-07-27 세션에서 v2 파이프라인 진단용으로 `scripts/data_prep/blender/overlay_v2_detailed.py`를
  **새로 작성**했다. 이 도구는 Phase 1~5에서 추가된 진단 필드(거리 상한 위반, ground continuity,
  noise tier, PnP eligibility, mask 포함관계, G1~G5 게이트)를 한 화면에서 보기 위한 것이라,
  RGB 오른쪽에 **영상 밖 패널 열을 덧붙이고**(캔버스 폭 = RGB 폭 + `PANEL_COL_W * PANEL_COLS`),
  상단에 full-width audit header를 그리고, 큐보이드를 FRONT(빨강)/REAR(파랑)/connector(노랑)로
  칠하고, M0/M4 마스크 컨투어를 함께 그렸다. [확인] — `tests/test_overlay_v2_detailed.py::
  TestRunner::test_cli_end_to_end`가 출력 폭이 `200 + PANEL_COL_W*PANEL_COLS`임을 단언한다.
- 반면 사용자가 정본으로 지목한 그림은 `data/pallet/archive/trunc_addon_v1_pilot/overlay/*.png`
  (300장)이고, 이것을 그린 코드는 `scripts/data_prep/blender/gen_trunc_addon.py::render_frame()`의
  `# === Detailed Overlay ===` 블록이다. 이 블록은 **RGB 파일을 열어 그 위에 직접 그리고 같은 크기로
  저장**한다(새 캔버스 생성·paste·concat 없음). [확인] — 새 테스트
  `test_archive_draws_no_external_panel_or_header`가 해당 소스 구간에 `Image.new` / `.paste(` /
  `np.concatenate` / `np.hstack` / `np.vstack`이 하나도 없음을 단언한다.
- 즉 두 그림은 같은 코드의 변형이 아니라 **서로 다른 시기에 다른 목적으로 쓰인 별개 코드**다.
  어제 도구는 archive를 참고하지 않고 처음부터 작성됐고, archive 블록은 v2 파이프라인 어디에서도
  호출되지 않는 상태였다(`gen_trunc_addon.py`는 palletobj 계열 생성기이며 v2 드라이버와 무관). [확인]

판정
- 원인은 "스타일이 조금 어긋난 것"이 아니라 **정본이 코드로 존재하지 않았던 것**이다. 따라서 이번
  작업의 올바른 해법은 어제 overlay를 archive처럼 보이게 튜닝하는 것이 아니라, archive 블록을
  그대로 추출해 정본으로 삼고 어제 것을 secondary로 격하하는 것이다(실제로 그렇게 했다).

---

## 2. 실제로 재사용한 `gen_trunc_addon.py` 코드 범위

관찰 — 이식한 원본 구간(모두 `gen_trunc_addon.py`) [확인]

```
원본 위치         내용                                   이식된 곳 (overlay_archive_trunc_style.py)
──────────────────────────────────────────────────────────────────────────────────────────────
L90              EDGES 12개 리스트                        EDGES
L603-611         Area% 정의 (in-frame 코너 bbox / 이미지)  corner_bbox_area_pct()
L616-651         큐보이드 엣지 + keypoint dot + ID 라벨     _draw_cuboid_and_keypoints()
  L621-623         X/Y/Z_EDGES 집합                        X_EDGES / Y_EDGES / Z_EDGES
  L626-630         엣지색 3종 + else + width=2             COLOR_*_EDGE, EDGE_WIDTH
  L633-643         KP_COLORS 9종                          KP_COLORS
  L646-649         off-screen 회색 + r=7/6 + 검은 외곽선    COLOR_KP_OFFSCREEN, KP_RADIUS*
L653-666         pose 축 3개 + 끝점 dot(r=4) + X/Y/Z 글자  _draw_pose_axes()
L668-699         info panel (6,6,175,240) + 20줄           _draw_info_panel(), format_panel_lines()
L701-710         axis legend 90x60 at (W-96, H-66)        _draw_axis_legend()
```

- 지시가 지목한 범위는 L577-712이고, 그중 **그리기와 무관한 부분(PIL 재시도 루프 L577-591,
  bpy 의존 pose/거리 계산 L594-601, 저장 L712)은 이식하지 않았다.** 대신 그 값들은 호출자가
  `metadata` dict로 넣어준다(bpy-free 유지). [확인]
- 이식이 "비슷하게 다시 쓴 것"이 아니라 **원본과 상수 단위로 동일**함은 이번 Section 8에서
  추가한 9개 테스트(`TestMatchesTheArchiveSource`)가 `gen_trunc_addon.py` 소스를 직접 파싱해
  값을 꺼내 비교하는 방식으로 고정했다. [확인]
- 어제 `overlay_v2_detailed.py`에서 재사용한 것은 **데이터 쪽뿐**이다(`frame_geometry`,
  `pose_axis_endpoints`, label 로더). 그리기 코드는 재사용하지 않았다. [확인]

판정
- "verbatim 이식"이라는 표현은 그리기 블록에 한해 정확하다. 다만 원본의 인라인 색 리터럴을
  이름 있는 상수로 올리고 4개 내부 함수로 분할했으므로 **바이트 단위 복사는 아니다**. 값이
  동일하다는 것이 테스트로 보장되는 형태다(2번 방식이 1번보다 회귀에 강하다고 판단).

---

## 3. 변경 파일

신규 (7개, 전부 untracked)

```
파일                                                              행수   역할
────────────────────────────────────────────────────────────────────────────────────────
scripts/data_prep/blender/mask_profiles.py                        273   mask 출력 프로파일 단일 정의(bpy-free)
scripts/data_prep/blender/overlay_archive_trunc_style.py          374   canonical overlay(archive 블록 이식)
scripts/data_prep/blender/tests/test_mask_profiles.py             489   프로파일 테스트 30개
scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py 561 정본 exact-match 테스트 51개
scripts/data_prep/blender/_verify_archive_style_pixels.py         367   12항목 픽셀 판정(일회성 검증 도구)
scripts/data_prep/blender/_make_archive_vs_new_sheet.py            82   정본 vs 신규 비교 시트(일회성)
_docs/history/2026-07-28.md                                       —     작업 기록
```

수정 (8개, tracked)

```
파일                                                    변경    주요 내용
────────────────────────────────────────────────────────────────────────────────────
scripts/data_prep/blender/v2_realize.py                105줄   홀드아웃 5회 하드코딩 -> MP.holdout_passes 루프,
                                                               label에 mask_profile 등 3필드 추가
scripts/data_prep/blender/run_v2_scene_logic.py         69줄   --mask-profile, 프로파일별 디렉토리/경로 주입,
                                                               _mask_integrity_fields가 프로파일 stage 사용
scripts/data_prep/blender/audit_v2_scene_logic.py      126줄   --mask-profile {auto,...}, 경로 해석 3함수
scripts/data_prep/blender/audit_pnp_eligibility.py       4줄   M0 조회를 MP.resolve_frame_mask_path로
scripts/data_prep/blender/overlay_v2_detailed.py       283줄   --style {archive,frontrear-debug}(기본 archive),
                                                               v2->archive 어댑터, resolve_mask_names,
                                                               --overlay-dirname/--sheet-dirname
scripts/data_prep/blender/tests/test_overlay_v2_detailed.py 214줄  style 인자 명시 + 어댑터/정본 테스트
scripts/data_prep/blender/tests/test_usable_completion_mode.py 3줄  가짜 args에 mask_profile 필드
_docs/history/changelog.md                               4줄   Section 1/2/5/6 요약
```

- 기존 테스트를 **삭제하거나 임계값을 완화한 곳은 없다**. `test_overlay_v2_detailed.py`의
  runner 테스트 2개는 `--style frontrear-debug`를 명시하는 인자만 추가했고 단언은 그대로다.
  Section 5에서 폰트 테스트 3개를 수정했는데, 이는 완화가 아니라 **틀린 가정(비트맵 폰트)을
  정본 픽셀로 반증하고 교체**한 것이다(4·10절). [확인]

---

## 4. canonical archive overlay와 secondary debug overlay 구분

```
                     canonical (정본)                    secondary (debug)
─────────────────────────────────────────────────────────────────────────────────────
--style 값           archive  (기본값)                    frontrear-debug
그리는 코드          overlay_archive_trunc_style.py       overlay_v2_detailed.draw_scene_layer
                     (gen_trunc_addon L577-712 이식)      (2026-07-27 신규 작성)
출력 폴더            <out>/overlay/                       <out>/overlay_frontrear_debug/
매니페스트           overlay_manifest.json                overlay_manifest_frontrear_debug.json
컨택트시트           <out>/contact_sheets/                <out>/contact_sheets_frontrear_debug/
캔버스               = 입력 RGB 크기                       RGB 폭 + 패널 열(외부 패널)
큐보이드 색          world X/Y/Z = 빨강/초록/파랑           FRONT 빨강 / REAR 파랑 / connector 노랑
keypoint             ID별 9색, 화면밖·뒤 = 회색            동일 개념이나 색 팔레트가 다름
mask 컨투어          없음 (mask 파일을 로드조차 안 함)      M0/M4 컨투어 표시
상단 header          없음                                  full-width audit header
정보 표시            좌상단 175x240 패널 20줄 (in-image)    영상 밖 다열 패널 (Phase 1~5 전 필드)
용도                 정본 — 데이터셋과 함께 배포/검수        convention·게이트 진단 전용
```

- 두 스타일을 같은 `--out`에 돌려도 파일이 겹치지 않는다. [확인] —
  `test_both_styles_coexist_in_one_out_dir` (overlay/ 1장 + overlay_frontrear_debug/ 1장, manifest 2개).
- 정본에는 Phase 1~5 진단 필드가 **없다**. 그 값이 필요하면 debug style을 써야 한다.
  판정: 정본에 기능을 얹지 않는 것이 이번 지시의 핵심이므로 의도된 제약이다.

---

## 5. M0~M4의 의미

`v2_realize.measure_geometry_and_masks()`의 constrained 경로가 프레임마다 도는 홀드아웃 렌더 패스다.
각 패스는 지정한 그룹을 **숨긴 채** 타깃 팔레트의 실루엣을 렌더한다. [확인] — 숨김 대상은
`mask_profiles.STAGE_HIDDEN_GROUPS`, 실제 객체 매핑은 `v2_realize.py:3605` `hide_groups`.

```
stage  숨기는 것                        남은 가림 요인            의미
──────────────────────────────────────────────────────────────────────────────────────
M0     모든 비-타깃 메시                 없음                     amodal 실루엣 (가림 0 기준면적)
M1     cargo + context + explicit        정적 씬(바닥/벽/선반 등)  정적 배경까지 반영한 실루엣
M2     context + explicit                정적 씬 + cargo          적재물까지 반영
M3     explicit                          정적 씬 + cargo + ctx    문맥 디스트랙터까지 반영
M4     (아무것도 숨기지 않음)             전부                     최종 visible 실루엣
```

여기서 파생되는 분해값 (full-audit에서만 계산)

```
f_static   = 1 - M1/M0     정적 씬 기하가 가린 비율
f_cargo    = 1 - M2/M1     적재물이 추가로 가린 비율
f_context  = 1 - M3/M2     문맥 디스트랙터가 추가로 가린 비율
f_explicit = 1 - M4/M3     명시적 occluder가 추가로 가린 비율   (= f_occ alias)
f_total    = 1 - M4/M0     전체 가림 비율  (M0·M4만으로 계산 가능)
```

- 면적은 단조 감소(M0 >= M1 >= M2 >= M3 >= M4)여야 하고, 픽셀 수준에서는 visible ⊆ amodal이어야 한다.
  위반은 감사기에서 fatal이다. [확인] — `test_public_inclusion_violation_is_still_fatal`.
- 실측 예시(8-frame public smoke): `f_total` = 0.0 / 0.0 / 0.00593 / 0.0 / 0.0 / 0.2324 / 0.1673 / 0.4663
  (8/8 프레임 non-null). [확인]

---

## 6. public에서는 왜 M0/M4만 남겼는지

관찰
- 학습/배포용 데이터셋이 실제로 쓰는 것은 amodal(M0)과 visible(M4) 2장뿐이다. M1~M3는
  **가림 원인 귀속(누가 얼마나 가렸나)**을 위한 진단 산출물이다.
- 비용: 프레임당 홀드아웃 패스가 5회 -> 2회. public 셋의 Blender 로그 `Saved:` 줄이 프레임당 3개
  (rgb + amodal + visible)뿐이다. 즉 **렌더 후 삭제가 아니라 애초에 렌더하지 않는다**. [확인]
- 이름: `mask/f0000_m0.png`처럼 암호 같은 접미사 대신 `mask_amodal/f0000.png` +
  `mask_visible/f0000.png`로 저장한다. public 셋에는 `mask/` 디렉토리가 생성되지 않는다. [확인]
- 정보 손실은 **정직하게 표기**한다: public에서 f_static/f_cargo/f_context/f_explicit는
  `None`(JSON null)이고 0.0이 아니다. `occlusion_decomposition_available=false`가 라벨에 기록된다.
  `f_total`은 M0/M4만으로 정확히 계산되므로 public에서도 exact다. [확인]
- 같은 seed(7500) 2프레임을 두 프로파일로 렌더해 mask 면적이 완전히 일치했다
  (f0000 14304, f0001 80813). 프로파일은 **저장 정책만** 바꾸고 씬/기하를 바꾸지 않는다. [확인]

판정
- 0(측정된 가림 없음)과 None(측정 안 함)을 구분해 저장하는 설계가 옳다. 이걸 0.0으로 채웠다면
  public 셋으로 만든 EDA가 "정적 가림이 전혀 없는 데이터"라고 잘못 결론냈을 것이다.
- 진단이 필요하면 full-audit로 소량 셋을 따로 뽑는 것이 맞다(대량 셋에 M1~M3를 붙이는 것보다 싸다).

---

## 7. 기존 50장 overlay 재생성 결과

관찰
- 대상 `data/pallet/_v2_smoke50_9d` — **50/50 재생성** (RGB 재렌더 0, Blender 미실행, label/record만 사용). [확인]
- 산출: `overlay_archive_style/f0000.png … f0049.png` **50장**,
  `contact_sheets_archive_style/detailed_001..005.png` **5장**,
  `overlay_archive_style_manifest.json`. 기존 `eda/`·`eda_phase6/overlay_detailed/`(50장)는 미변경. [확인]
- 지시에 있던 `_v2_cleanbase_smoke20_seed7100`은 **존재하지 않아 건너뜀**(`data/pallet/`에
  `*cleanbase*` 이름 0개). 생성하지 않았다. [확인]
- 12항목 픽셀/시각 검증: **archive 정본 12/12장, 신규 12/12장이 각각 12항목 전부 PASS**. [확인]
  (24장을 Read 도구로 직접 열람 + `_verify_archive_style_pixels.py`로 픽셀 판정 병행)
- 상수 샘플링 24/24 일치: 패널 `(6,6)`·`(181,246)` = `(0,0,0)`, legend 스와치
  `(255,60,60)/(60,220,60)/(80,130,255)` @ `(W-91, H-59/-44/-29)`, canvas == RGB. [확인]
- **이 과정에서 폰트 버그 1건을 잡아 고쳤다.** Section 2~4는 "Pillow 10.1이 `load_default()`를
  AA TrueType으로 바꿨으니 비트맵을 강제해야 archive와 같다"고 가정했는데, 정본 PNG가 이를 반증했다
  (정본 패널 안 순백 픽셀 0개, legend 박스 91x61 골든 diff: `load_default()` **0 px** vs
  비트맵 **482 px**). `load_default()`로 교체하고 전량 재생성했다. [확인]

판정
- 검증 기준을 신규본에 적용하기 전에 **정본 자신에게 먼저 통과시킨 것**이 이번 검증의 핵심이다.
  초기 기준은 정본도 FAIL시켰고(원인은 전부 정본의 정상 동작 — 13.7 m 프레임에서 엣지가 dot에
  완전히 가려짐, 축 글자 AA가 순수 축색 픽셀을 남기지 않음, JSON 좌표 소수 2자리 반올림으로 1 px
  편차), 기준을 고친 뒤에야 신규본을 판정했다.

---

## 8. 8-frame public mask smoke 결과

관찰 — 실행 [확인]
- `--out data/pallet/_v2_publicmask_overlay_smoke8 --seed 7000 --n 8 --completion-mode usable
  --mask-profile public --render-profile dataset-quality --noise-tier clean`,
  headless Blender 5.1, **wall clock 299 s, exit 0, 8장 배달**
  (proposal 12 · render 시도 9 · 배달 8 · render reject 1 · mode-filter skip 3).
- overlay는 기본 `--style archive`로 `<dataset>/overlay/` 8장.

6.3 필수 결과 **15/15 PASS** [확인]

```
요구                                        실측    기대   판정
──────────────────────────────────────────────────────────────
RGB                                          8       8    PASS
label                                        8       8    PASS
mask_amodal                                  8       8    PASS
mask_visible                                 8       8    PASS
M1/M2/M3 파일                                0       0    PASS
전체 영구 mask 파일                          16      16    PASS
f_total non-null                             8       8    PASS
f_static/f_cargo/f_context/f_explicit null   8       8    PASS
occlusion_decomposition_available=false      8       8    PASS
mask_profile=public                          8       8    PASS
pixel inclusion visible ⊆ amodal             8       8    PASS
archive-style overlay                        8       8    PASS
overlay canvas size == RGB size              8       8    PASS
외부 오른쪽 panel                            0       0    PASS
상단 full-width header                       0       0    PASS
```

- 감사기 auto 감지 PASS(frames 8, failures 0, fatal 0, `mask_profile="public"`,
  `mask_names=['m0','m4']`). [확인]
- overlay 8장을 Read로 전량 열람 + 픽셀 판정 12항목 **8/8**. mask_amodal/mask_visible도 crop 시트로
  육안 확인(가림 영역이 실제 occluder footprint와 일치, 포크홀 구멍까지 실루엣에 반영). [확인]
- **위험 항목은 스모크만으로는 검증되지 않았다**: 이 실행의 유일한 render reject가 realize 실패라
  record에 `mask_paths`가 없어 cleanup 경로를 타지 않았다. 그래서 `--magenta-max-fraction=-1.0`으로
  **렌더 성공 후 gate reject를 강제**한 1-frame probe를 별도로 돌려
  `removed_files=3`(rgb + mask_amodal + mask_visible), 잔재 파일 0, 출력 PNG 0을 확인했다. [확인]

판정
- 이 표본은 **n=8, seed 1개**다. 수율(배달 8 / 렌더 시도 9)을 일반화하면 안 된다 — 같은 seed의
  9D 50장 실행 수율은 **66.7%**였다. 이번 8장은 "기능이 end-to-end로 동작한다"는 증거이지
  수율/분포에 대한 증거가 아니다.
- `--noise-tier clean`을 camera-postprocess none 대용으로 썼다(효과를 완전히 끄는 CLI 옵션이 없다).
  clean 티어는 blur/noise/jpeg 확률 0.0이고 wb_gain·vignette만 남는 최약 티어다. [확인]

---

## 9. archive reference와 새 overlay 비교 이미지 경로

```
reports/v2_overlay_fix/archive_reference_vs_new.png     1310 x 3098, 6쌍, 양쪽 원본 크기 유지
reports/v2_overlay_fix/visual_verification.md           12항목 x (정본 12 / 신규 12) 판정표
reports/v2_overlay_fix/final_report.md                  (이 문서)
```

비교 6쌍 (좌 archive 정본 / 우 신규) [확인]

```
케이스              archive        new
────────────────────────────────────────
near/truncated      000004         f0002
far                 000005         f0008
low elevation       000001         f0000
high elevation      000061         f0007
cargo               000009         f0010
occluder            000011         f0040
```

- 야간 조건은 archive 파일럿 300장에 없다(HDRI 9종 전부 주간). 정본 쪽으로는 커버 불가이고
  신규 쪽에만 포함된다. [확인]
- 8-frame public smoke의 overlay는 `data/pallet/_v2_publicmask_overlay_smoke8/overlay/f0000..f0007.png`.
- `archive_reference_vs_new.png`는 확장자 단위 ignore 규칙 때문에 git untracked 목록에 나오지 않는다
  (파일은 디스크에 존재, 4.99 MB). [확인]

---

## 10. unit test 결과

지시가 요구한 12개 필수 항목의 커버 대응표 (Section 8에서 전수 확인) [확인]

```
필수 항목                          커버하는 테스트 (파일::클래스::함수)
────────────────────────────────────────────────────────────────────────────────────────────
archive edge set + RGB exact       test_overlay_archive_trunc_style.py
                                     TestEdges::test_edge_list_matches_archive
                                     TestEdges::test_axis_edge_sets_match_archive
                                     TestEdges::test_edge_colors_are_the_archive_rgb
                                     TestEdges::test_edges_are_painted_with_those_colors
                                     TestEdges::test_edge_width_is_two_pixels
                                   ★TestMatchesTheArchiveSource::test_edge_set_is_the_archive_edge_set
                                   ★TestMatchesTheArchiveSource::test_edge_rgb_and_width_are_the_archive_values
keypoint 0~8 color exact           TestKeypoints::test_kp_colors_match_archive
                                     TestKeypoints::test_every_dot_uses_its_id_color
                                     TestKeypoints::test_behind_camera_dot_is_gray
                                     TestKeypoints::test_off_image_dot_is_gray_and_its_color_never_appears
                                     TestKeypoints::test_corner_radius_6_and_centroid_radius_7
                                   ★TestMatchesTheArchiveSource::test_keypoint_colors_radii_and_grey_are_the_archive_values
panel rectangle exact position     TestPanel::test_panel_constants
                                     TestPanel::test_panel_rectangle_is_exactly_where_the_archive_put_it
                                     TestPanel::test_each_of_the_20_lines_lands_in_its_own_11px_band
                                     TestPanel::test_text_starts_at_panel_x_plus_5
                                   ★TestMatchesTheArchiveSource::test_panel_rectangle_and_line_spacing_are_the_archive_values
                                   ★TestMatchesTheArchiveSource::test_panel_lines_keep_the_archive_labels_and_order
legend exact position              TestLegend::test_legend_constants
                                     TestLegend::test_legend_box_and_swatches
                                     TestLegend::test_legend_follows_the_image_size
                                     TestLegend::test_legend_is_pixel_identical_to_the_archive  (골든 diff)
                                   ★TestMatchesTheArchiveSource::test_legend_geometry_and_swatches_are_the_archive_values
output canvas size unchanged       TestCanvas::test_canvas_is_exactly_the_input_rgb   (3 해상도)
                                     TestCanvas::test_input_image_is_not_mutated
                                     test_overlay_v2_detailed.py
                                       TestArchiveAdapter::test_render_archive_overlay_keeps_the_rgb_size
                                       TestRunner::test_cli_default_style_is_archive  (디스크 PNG 크기)
                                   ★TestMatchesTheArchiveSource::test_archive_draws_no_external_panel_or_header
0/False가 N/A로 바뀌지 않음        TestPanelText::test_zero_and_false_are_never_na
                                     TestAreaPct::test_no_in_frame_corner_is_zero
                                     test_overlay_v2_detailed.py
                                       TestArchiveAdapter::test_zero_and_false_survive_the_adapter
                                       TestValueModel::test_zero_is_present_not_na / test_false_is_present_not_na
                                     test_mask_profiles.py
                                       ::test_unoccluded_public_frame_reports_zero_not_none
                                       ::test_full_audit_zero_occlusion_stays_zero
missing 값만 N/A                   TestPanelText::test_missing_fields_are_na_not_zero
                                     TestPanelText::test_scenario_is_clipped_to_18_chars
                                     test_overlay_v2_detailed.py
                                       TestArchiveAdapter::test_missing_v2_fields_stay_none
                                       TestArchiveAdapter::test_missing_fields_are_reported_in_the_stats
                                     test_mask_profiles.py::test_empty_amodal_mask_is_unmeasurable_not_zero
pose axis projection fixture       test_overlay_v2_detailed.py
                                       TestArchiveAdapter::test_pose_axis_projection_reaches_the_canvas
                                         (K fx=fy=100, cx=400, cy=300 / R=I, t=(0,0,2)
                                          -> X끝 (425,300), Y끝 (400,325) + 그 픽셀의 축색 확인)
                                       TestGeometry::test_pose_axes_projection
                                       TestGeometry::test_pose_axes_behind_camera_not_drawn
                                     test_overlay_archive_trunc_style.py
                                       TestPoseAxes::test_axis_constants / test_axes_are_drawn_in_axis_colors
                                       TestPoseAxes::test_dict_form_respects_ok_flag / test_no_axes_at_all
                                       TestPoseAxes::test_axis_endpoint_dot_and_label
                                   ★TestMatchesTheArchiveSource::test_pose_axis_constants_are_the_archive_values
public mask profile output count   test_mask_profiles.py
                                       ::test_public_keeps_exactly_two_masks_per_image_and_no_m1_m2_m3
                                          (3 프레임 -> PNG 6개, m1/m2/m3 0개, mask/ 미생성)
                                       ::test_public_renders_two_passes_not_five
                                       ::test_hidden_object_sets_match_the_pre_refactor_holdout_calls
                                       ::test_realize_supplies_every_hide_group_the_plan_needs
                                   ★::test_only_the_profile_mask_directories_are_created
visible mask ⊆ amodal (픽셀)       test_mask_profiles.py
                                       ::test_mask_integrity_checks_visible_subset_of_amodal_for_public
                                       ::test_mask_integrity_catches_visible_pixels_outside_amodal (m4!<=m0)
                                       ::test_visible_larger_than_amodal_fails_the_invariant
                                       ::test_public_inclusion_violation_is_still_fatal (감사기 서브프로세스)
full-audit backward compatibility  test_mask_profiles.py
                                       ::test_full_audit_keeps_five_masks_at_the_historical_paths
                                       ::test_full_audit_source_fractions_stay_exact (0.10/0.20/0.05/0.15/0.50)
                                       ::test_full_audit_zero_occlusion_stays_zero
                                       ::test_broken_full_audit_decomposition_keeps_observed_areas
                                       ::test_legacy_prefix_paths_are_unchanged_for_full_audit
                                       ::test_default_profile_is_full_audit
                                       ::test_full_audit_integrity_still_uses_all_five_stages
                                       ::test_full_audit_dataset_is_unaffected_by_the_new_flag (감사기)
                                     test_usable_completion_mode.py
                                       ::test_records_mode_record_schema_is_unchanged (146키 frozen)
label/keypoint convention 불변     test_mask_profiles.py
                                       ::test_keypoint_convention_and_pose_fields_are_untouched
                                          (camera_dynamic_0123_v4 / projected_cuboid / perm_v4 /
                                           pose_transform / quaternion_xyzw 소스 계약 6종)
                                       ::test_orientation_overrides_are_still_imported_unmodified
                                     test_overlay_v2_detailed.py
                                       TestArchiveAdapter::test_keypoints_are_8_corners_plus_centroid_with_camera_depth
                                   ★TestArchiveAdapter::test_corner_ids_follow_the_label_projected_cuboid_order
                                   ★TestRunner::test_overlay_run_never_rewrites_the_dataset
```

★ = Section 8에서 **새로 추가**한 테스트 (12개)

추가한 이유
- 기존 테스트는 색·좌표 리터럴을 **테스트 파일 안에** 적어두고 비교했다. 복사가 틀렸어도 리터럴이
  같이 틀렸다면 통과한다. `TestMatchesTheArchiveSource` 9개는 `gen_trunc_addon.py` 소스를 정규식으로
  파싱해 상수를 꺼내 비교하므로, "archive와 exact match"가 진짜 diff가 된다. 여기에는 archive의
  **inclusive 경계 조건**(`0 <= x <= W`, Section 6의 f0004 centroid 오판 원인)과 Area% 정의,
  패널 20줄 라벨 순서도 포함된다.
- `test_only_the_profile_mask_directories_are_created`: `MP.mask_dirnames`가 어떤 테스트에도
  걸려 있지 않았고, "public 셋에 빈 `mask/`를 남기지 않는다"는 조건이 스모크로만 확인돼 있었다.
- `test_corner_ids_follow_the_label_projected_cuboid_order`: keypoint convention 가드가
  `v2_realize.py` 소스 텍스트 검사뿐이라 **그리기 쪽**은 비어 있었다. label의 `projected_cuboid`
  인덱스 i가 archive 색 i로 칠해지는지를 픽셀로 확인한다(오버레이가 순서를 재배열하지 못하게).
- `test_overlay_run_never_rewrites_the_dataset`: overlay는 view여야 한다. CLI 실행 전후로
  labels/records/mask/rgb의 SHA-256을 비교한다.

최종 실행

```
명령: python -m pytest scripts/data_prep/blender/tests/ -q
결과: 455 passed, 0 failed, 0 skipped, 142.61 s
```

```
파일                                  이전   이후   증가
────────────────────────────────────────────────────────
test_overlay_archive_trunc_style.py    42     51     +9
test_overlay_v2_detailed.py            60     62     +2
test_mask_profiles.py                  29     30     +1
그 외 (18개 파일)                     312    312      0
────────────────────────────────────────────────────────
합계                                  443    455    +12
```

- 기존 테스트 **삭제 0건, 임계값 완화 0건**. [확인]

판정
- 12개 필수 항목은 전부 커버되며, 그중 5개(edge/keypoint/panel/legend/canvas)는 이제 archive
  소스와의 직접 diff로 이중 고정된다. 남은 약점은 아래 11절 참조.

---

## 11. 남은 문제

이번 작업 범위에서 발견/미해결

1. **`analyze_v2_scene_logic.py`(L471, L968)와 `compare_v2_determinism.py`(L217)가 아직
   `root/"mask"`를 하드코딩한다.** [확인] public 레이아웃 셋에 돌리면 크래시는 아니지만 mask 관련
   컬럼/해시가 전부 결측이 된다. `MP.resolve_frame_mask_path`로 배선하면 되고, 40k 본생성 전에
   해두는 편이 안전하다. (`analyze_v2_scene_logic.py` L2019/2024는 self-test fixture 생성부라
   별도.)
2. **정본 경로가 문서에 명시돼 있지 않다.** `reports/v2_revision/quality_smoke50/summary.md:246`이
   여전히 `eda_phase6/overlay_detailed/`를 가리킨다. [확인] 이는 어제 실제로 만든 산출물의 기록이라
   고치지 않는 게 맞지만, **앞으로 정본은 `<out>/overlay/`(style=archive)**라는 사실이 어딘가에
   적혀 있어야 한다. 현재는 이 보고서와 `_docs/history/2026-07-28.md`에만 있다.
3. **M1이 배경(벽/선반/바닥)을 숨기지 않으므로 `f_static`이 배경 가림을 흡수한다.** [확인] —
   `v2_realize.py:3605` `hide_groups`에서 M1은 cargo/context/explicit만 숨긴다. 따라서 full-audit의
   `f_static`은 "정적 씬 기하에 의한 가림"이며 여기에는 배경 에셋(벽·선반·기둥)이 포함된다.
   full-audit 분해값으로 EDA할 때 이 정의를 모르면 "정적 가림이 왜 이렇게 많나"를 오독하게 된다.
   public 셋은 애초에 분해값이 없으므로 해당 없음.
4. **8-frame 스모크는 표본 8, seed 1개다.** 수율 8/9를 일반화하면 안 된다(9D 50장은 66.7%).
   mode별 reject 분포도 이 표본으로 판단 불가.
5. **일회성 검증 도구 2개가 `scripts/data_prep/blender/` 루트에 남아 있다**
   (`_verify_archive_style_pixels.py`, `_make_archive_vs_new_sheet.py`). `_` 접두 관례를 따랐지만
   정리 위치는 미결정. [확인]
6. **정본 12장 비교에 야간 케이스가 없다.** archive 파일럿 300장이 전부 주간 HDRI 9종이라
   구조적으로 커버 불가. 신규본 쪽만 야간을 포함한다. [확인]

어제 세션에서 넘어온 blocker (이번 작업 범위 밖이지만 **여전히 유효**) [확인]

7. controlled-occlusion realize 실패율 — 특히 `occluder_side=bottom`(9D 50장에서 성공 2/12=17%),
   `center`는 렌더 시도 자체가 1/38. 9C 20프레임에서도 idx 15·18이 같은 이유로 탈락.
8. PnP threshold 확정 불가 — usable 셋은 정의상 전원 all-pass라 pass-probability 곡선이 퇴화
   (base rate 1.000). 게이트 튜닝은 records-mode 셋이 필요.
9. `projected_size_actual` 과대추정 약 12%.
10. exact GT에서도 EPnP가 발산하는 프레임 존재(9D f0038·f0049: reproj 34.9/30.6 px, rot err 146°/160°,
    둘 다 visible kp 5 + 저앙각). 평면 퇴화 구성 문제로 보이며 solver는 평가 코드와 맞추기 위해 미변경.
    (프로젝트 규칙상 flat 물체는 `SOLVEPNP_ITERATIVE` 권장 — 별도 결정 사항.)
11. tiny 배달 8%, high noise tier 미검증(n=50에서 기대 1.5장), GPU 렌더 비결정성(PNG 바이트),
    f_static 카운터 부재, 40k 감사 비용 — 9D 보고서 blocker B5~B11 그대로.

---

## 12. git diff 요약

`git status --porcelain` / `git diff --stat` 실제 실행 결과 (2026-07-28, 작업 종료 시점) [확인]

```
수정(tracked) 8개                                              +/-
──────────────────────────────────────────────────────────────────
_docs/history/changelog.md                                       4 +
scripts/data_prep/blender/audit_pnp_eligibility.py               4 +-
scripts/data_prep/blender/audit_v2_scene_logic.py              126 ++-
scripts/data_prep/blender/overlay_v2_detailed.py               283 +++-
scripts/data_prep/blender/run_v2_scene_logic.py                 69 ++-
scripts/data_prep/blender/tests/test_overlay_v2_detailed.py    214 ++-
scripts/data_prep/blender/tests/test_usable_completion_mode.py   3 +-
scripts/data_prep/blender/v2_realize.py                        105 +--
──────────────────────────────────────────────────────────────────
8 files changed, 678 insertions(+), 130 deletions(-)
```

```
신규(untracked) 8 entry                                        행수
──────────────────────────────────────────────────────────────────
_docs/history/2026-07-28.md                                     710
reports/v2_overlay_fix/                                          —   (디렉토리)
  ├ visual_verification.md                                      142
  ├ final_report.md                                              —   (이 문서)
  └ archive_reference_vs_new.png                                 —   (4.99 MB, gitignore 대상)
scripts/data_prep/blender/mask_profiles.py                      273
scripts/data_prep/blender/overlay_archive_trunc_style.py        374
scripts/data_prep/blender/tests/test_mask_profiles.py           489
scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py  561
scripts/data_prep/blender/_verify_archive_style_pixels.py       367
scripts/data_prep/blender/_make_archive_vs_new_sheet.py          82
```

- 데이터 산출물은 `data/pallet/` 아래(gitignore 대상):
  `_v2_publicmask_overlay_smoke8/`(신규, 8프레임), `_v2_smoke50_9d/overlay_archive_style/`(50) +
  `contact_sheets_archive_style/`(5) + `overlay_archive_style_manifest.json`(추가). [확인]
- **git add / commit / push 미실행.** working tree만 변경돼 있고 HEAD는 `cf98fc6` 그대로다. [확인]

---

## 완료 조건 점검

```
조건                                                        판정   근거
──────────────────────────────────────────────────────────────────────────────────────
① 두 번째(archive) 형태로 canonical overlay 생성            충족   --style 기본값 archive -> <out>/overlay/.
                                                                   정본 12장 + 신규 12장 12항목 12/12 PASS,
                                                                   8-frame smoke overlay 8/8 PASS.
                                                                   legend 골든 diff 0 px. [확인]
② public mask profile은 이미지당 2장만 영구 저장            충족   8-frame smoke: mask_amodal 8 + mask_visible 8
                                                                   = 16 파일 / 8 프레임, M1~M3 0개,
                                                                   mask/ 디렉토리 미생성. 프레임당 Saved 3줄
                                                                   (렌더 자체 2패스). [확인]
③ full-audit에서만 M0~M4 5장 저장                           충족   같은 seed full-audit 렌더 = 프레임당 5장
                                                                   mask/fNNNN_m0..m4.png, 분수 exact.
                                                                   기본값이 full-audit이라 기존 동작 불변. [확인]
④ 500 / 40k 미실행                                          충족   오늘(2026-07-28) mtime 데이터셋은
                                                                   _v2_publicmask_overlay_smoke8(8프레임) 와
                                                                   _v2_smoke50_9d(overlay만 추가, RGB 재렌더 0)
                                                                   뿐. 500/40k 디렉토리 신규 생성 0. [확인]
⑤ commit / push 미실행                                      충족   git status = 8 modified + 8 untracked,
                                                                   HEAD cf98fc6 유지, staged 0. [확인]
```

부가 조건(지시 본문)

```
- 기존 테스트 삭제·완화 없음                                충족   삭제 0, 완화 0. 인자 추가 2건,
                                                                   틀린 가정 교체 3건(폰트, 정본 픽셀로 반증). [확인]
- 전체 pytest 통과                                          충족   455 passed / 0 failed / 142.61 s. [확인]
- 사용자 GUI Blender 미접촉                                 충족   이번 Section 8-9는 Blender 미실행. [확인]
- 기존 데이터 삭제·이동 없음                                충족   eda/, eda_phase6/, archive/ 미변경. [확인]
```
