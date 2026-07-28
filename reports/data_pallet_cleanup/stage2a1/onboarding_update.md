# §5 `_docs/blender_mcp_onboarding.md` 최신화

문서가 두 세대 뒤처져 있었다 — mask 는 `_unocc`/`_aftercargo`/`_visible` 3종,
overlay 정본은 FRONT 빨강/REAR 파랑/connector 노랑, 전수 오버레이는 `overlay_all/`.
현행(커밋 ff972c2)은 M0~M4 5-stage(full-audit) / M0·M4 2-stage(public), overlay canonical 은
`--style archive` → `<dataset>/overlay/` 다.

## 5-A. mask 규약

`§3.1.1` 절을 신설하고 옛 "마스크 3종 의미" 블록을 대체했다.

```
수정 위치                내용
──────────────────────────────────────────────────────────────────────────────
L17  (§0 TL;DR)         "visible mask 3종" -> "holdout mask(full-audit 5-stage 또는
                        public 2-stage, §3.1.1)"
L32  (§1.1 목표)         "unoccluded / after-cargo / visible" -> M0~M4 / M0·M4,
                        "옛 접미사는 폐지됨" 명시
L124 (G3 게이트)         area_unocc -> area_amodal(M0), area_visible -> M4
§3.1 레이아웃 트리        mask/f*_unocc|aftercargo|visible.png -> mask/f*_m0..m4.png +
                        mask_amodal/ + mask_visible/ + overlay/ + overlay_frontrear_debug/
§3.1.1 (신설)           두 프로파일 대비표, M0~M4 의미, None vs 0.0, mask_profiles API
§3.2 label 스키마        mask_area_unocc/after_cargo/visible ->
                        mask_area_amodal/visible + mask_profile +
                        occlusion_decomposition_available (+ full-audit 전용 3종)
```

신설 절이 명시하는 것:

- public 은 `mask_amodal/` + `mask_visible/` 2장, **M1~M3 는 렌더 자체를 하지 않는다**
  (렌더 후 삭제가 아님 → 프레임당 3패스 절약).
- full-audit 은 `mask/f*_m0..m4.png` 5장, source 별 가림 분해 가능.
- M0 = target-only amodal / M1 = static 반영 / M2 = +cargo / M3 = +context / M4 = final visible.
- **None = 미측정, 0.0 = 측정됐고 가림 없음.** public 에서 source fraction 을 0 으로 채우면
  "가림이 없었다"는 거짓 정보가 된다. public 에서 M1~M3 부재는 결측이 아니라 정상이다.
- 경로는 `mask_profiles.py`(`detect_profile` / `mask_stages` / `frame_mask_paths` /
  `resolve_frame_mask_path` / `decompose`)로 얻는다.

## 5-B. overlay 규약

`§4.1` 제목을 `(2026-07-28 현행 — canonical = --style archive)` 로 바꾸고 스타일 표를 교체했다.

```
canonical (--style archive)  ->  <dataset>/overlay/          ★정본
  world X/Y/Z 축별 edge 색, ID별 keypoint 색, centroid 흰색, off-screen 회색,
  pose X/Y/Z axes(z>0), 좌상단 in-image 패널, 우하단 축 범례,
  입력 RGB 와 동일 canvas — 외부 패널·full-width header·mask contour 없음

secondary debug (--style frontrear-debug)  ->  <dataset>/overlay_frontrear_debug/
  FRONT 빨강 / REAR 파랑 / connector 노랑 + 외부 진단 패널 + audit header + M0/M4 contour
  convention·gate 진단 전용. canonical 이 아니다.

archive 정본 reference: data/pallet/archive/trunc_addon_v1_pilot/  (현재 위치 불변)
  tests/test_overlay_archive_trunc_style.py 가 overlay/000000.png 를 픽셀 비교한다.
```

`overlay_all/` 언급은 canonical 자리에서 내려오고, 옛 스크립트 호출은
"(구) 파일럿 당시 전수 오버레이 스크립트 (재현용, canonical 아님)" 로 표시해 남겼다.
체크리스트(L542)의 "`overlay_all/` 전수"도 "canonical `overlay/` 전수(`--style archive`)"로 갱신.

## 5-C. 경로 registry

`§2.5` 를 신설해 registry 사용법을 넣었다(기존 재현 커맨드 절은 §2.6 으로 밀림).

```
config/synthetic/pallet_paths.yaml               runtime source of truth
scripts/data_prep/blender/pallet_data_paths.py   resolver (bpy import 없음)

import pallet_data_paths as pdp;  pdp.get("production_scene")
python scripts/data_prep/blender/pallet_data_paths.py [--audit|--key K]
PALLET_DATA_ROOT=... 로 root 만 override
```

+ `manifests/*.csv` 는 snapshot 이지 runtime config 가 아님을 명시.
+ **"이름이 archive/ 인데 현역인 자산"** 경고(`archive/textures_wood`,
  `archive/textures_floor`, `archive/trunc_addon_v1_pilot`).

## 5-D. 실행 예시

```
(e) 파일럿 2k  ->  "mask 레이아웃 선택: 진단용 --mask-profile full-audit (기본),
                   공개용 --mask-profile public" 주석 추가
(g)  overlay_v2_detailed.py --dir <dataset> --style archive            (canonical)
(g-2) overlay_v2_detailed.py --dir <dataset> --style frontrear-debug   (debug)
(구)  _v2_pilot_overlay_all.py                                          (재현용 표시)
```

### 구현 여부 확인 [확인, 실행함]

문서에 적은 옵션이 실제로 존재하는지 소스로 확인했다.

```
overlay_v2_detailed.py   --dir (L1385)  --style (L1387, choices=STYLES)   존재
run_v2_scene_logic.py    --mask-profile (L543)                            존재
analyze_v2_scene_logic.py --mask-profile                                  이번에 추가
camera-postprocess none                                                   존재하지 않음
                                                                          -> 문서에 쓰지 않았다
```

## 수정하지 않은 것

- `§5` 과거 실패 사례의 당시 경로·당시 규약(예: L372 `luma_pallet` 마스크를 unocc→visible 로
  교체한 기록)은 **그대로 뒀다.** 과거 기록을 현재 규약으로 소급 수정하지 않는다.
- 옛 접미사 이동 교훈(일괄 shutil 처리)은 "당시 규약 기준 — 현행은 §3.1.1" 주석만 덧붙였다.
