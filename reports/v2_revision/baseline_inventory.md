# v2 개편 0단계 — Baseline Inventory (문서 vs 코드 실측)

작성: 2026-07-27 / 대상 repo: `E:/CODING/GitHub/FoundationPose` (branch `main`, clean)
성격: **조사·문서화 전용.** 코드 무수정, git 무조작, Blender 실행 없음(정적 추적 + 파일 읽기).

태그 규약
- `[확인]` = 코드의 실행 흐름을 호출부까지 끝까지 추적했거나 파일 내용을 직접 읽어 검증.
- `[추정]` = 주석·변수명·문서 서술에서만 추론(미검증). 실행하지 않았다.

> 위치 주의: 이 파일은 상위 에이전트가 지정한 경로 `reports/v2_revision/`에 생성했다. 다만
> 프로젝트 `CLAUDE.md`는 "모든 프로젝트 문서는 `_docs/` 하위"를 규정하므로, 정착 문서로
> 남길 경우 `_docs/experiments/` 또는 `_docs/method/`로 옮기는 것이 프로젝트 규약에 맞다.

---

## 0. 읽은 대상

```
문서
  CLAUDE.md
  _docs/blender_mcp_onboarding.md
  _docs/history/2026-07-26.md
  _docs/history/2026-07-26-v2-attempt-log.md
  _docs/experiments/v2_scene_logic_500_eda_results.md
  _docs/method/v2_domain_randomization.md
코드 (scripts/data_prep/blender/)
  v2_pipeline.py            1913 L   Layer-1/2 (bpy-free)
  v2_realize.py             3776 L   Layer-3 (bpy)
  run_v2_scene_logic.py      860 L   500-record 진단 runner
  analyze_v2_scene_logic.py 2369 L   EDA(22 charts)
  audit_v2_scene_logic.py   1450 L   전수 감사
  camera_effects.py           55 L   RGB post-effect
  gen_trunc_addon.py        1173 L   레거시 생성기(상세 overlay 보유)
  blender_math.py            288 L   perm_v4 / view matrix
  tests/                     9 파일  (unit 5 + Blender probe 3 + determinism 1)
```

---

## 1. 파일별 — 문서와 현재 구현의 차이

### 1.1 `_docs/method/v2_domain_randomization.md`

- **[확인] 문서 헤더 "상태: 미구현"은 stale.** 문서가 "구현 대상"이라 부른 축은 대부분 이미
  `v2_pipeline.py`에 리터럴로 구현돼 있다. `ELEV_BIN_EDGES/FRAC`(L86-88), `PROJ_SIZE_EDGES`
  폭-비율(L105-107), `EXPOSURE_EV_RANGE=(-3.0,0.2)`(L151), `ASPECTS/ASPECT_FRAC`(L157-163),
  `FX_MODES/FX_FRAC/FX_RANDOM_RANGE`(L166-168), `lens_mm`(L1065). 라벨 스키마도
  `v2_realize.label()`(L3642~)에 존재.
- **[확인] ③ "surf_dist = 해상도 소거 형태로 단일 소스 통합"은 절반만 반영.**
  v2 경로는 해상도-소거형 역산(`v2_pipeline.py:1064`)을 쓰지만, 문서가 같이 고치라고 지목한
  `gen_trunc_addon.py:996-1001`은 **여전히 px-bin + `fx*1.3/px - 0.7`** 형태 그대로다.
  ```python
  # gen_trunc_addon.py:1001
  surf_dist = max(0.0, D435I["fx"] * 1.3 / random.uniform(*size_bin) - 0.7)
  ```
  (gen_trunc_addon은 레거시라 의도적으로 안 건드렸을 가능성 있음 — 그러나 문서 문면과는 불일치.)
- **[확인] ② "camera_effects를 효과별로 분리" 중 blur의 해상도 비례 스케일은 미구현.**
  `camera_effects.py:39`는 폭과 무관하게 `GaussianBlur(U(0.5,1.8))` 고정. 문서 처방은
  `blur_px ∝ width/640`. 나머지 3개는 문서와 일치: vignette은 정규화 반경(L31, 자동 OK),
  noise는 해상도 스케일 없음(L44, 대신 **darkness** 기반 `noise_scale`만 있음), JPEG는 렌더
  해상도 그대로(L51).
- **[확인] "distractor 선택 배선 DISTRACTOR_NAMES(8) → 209 풀"은 v2 경로에서 해소됨.**
  `v2_pipeline._occluder_pool`(L753)이 `distractor_pool_v2` manifest를 쓴다.

### 1.2 `_docs/blender_mcp_onboarding.md`

- **[확인] §3.1 파일 레이아웃은 legacy 전용.** 온보딩은 `mask/f####_unocc|_aftercargo|_visible`
  3종 + `pilot_records.json`을 "정본"으로 기술하지만, constrained(500 진단) 경로는
  `mask/f####_m0..m4.png` 5종(`v2_realize.py:3406-3412`) + `records.jsonl`/`records.json`/
  `progress.json`(`run_v2_scene_logic.py:243-252`)이다. 3종 레이아웃은 `measure()`의 legacy
  분기(L3477-3486)에만 남아 있다.
- **[확인] §3.2 라벨 스키마도 구버전.** 현재 label에는 문서에 없는 필드가 다수 추가돼 있다:
  `objects[0].scene_placement_v2`, `v2_labels.{placement_mode,diagnostic_mode,f_static,
  f_context,f_explicit,mask_area_target_only/after_static/after_context,mask_invariants_pass,
  front_face_visibility,left/right_opening_visibility,cargo_on_prescribed}`
  (`v2_realize.py:3696-3772`).
- **[확인] §5A ⑫ "material_family 전 프레임 None" 서술은 원인이 다르다.**
  `FrameSpec.material_family`는 실제로 채워진다(`v2_pipeline.py:473,534`). 다만 **label()이
  이 필드를 아예 출력하지 않는다**(`v2_realize.py:3701-3772`에 `material_family` 키 없음).
  즉 "None으로 채움"이 아니라 "라벨 미출력". 집계는 여전히 `material_variant_target`로 조인해야 함.
- **[확인] §2.4 "net yield 31~40%, binding=G1"은 legacy 2k 기준.** constrained 500에서는
  렌더 성공 435/500(87.0%), gate all-pass 364/435(83.68%)이고, 주 손실은 G1이 아니라
  **렌더 전 realize 실패 65건(controlled bounded search 62)**이다.
- **[확인] §2.5 재현 커맨드에 500 진단 runner가 없다.** 현 정본 진입점은
  `run_v2_scene_logic.py`(`--n 20|500`만 허용, `run_v2_scene_logic.py:185`).

### 1.3 `_docs/history/2026-07-26.md`

- **[확인] "변경하지 않은 분포와 게이트" 표는 코드와 정확히 일치.** elevation 7-bin
  8/18/20/20/16/10/8, V 15/25/30/20/10, azimuth 12 uniform, proj-size 5×20%(첫 bin 하한 0),
  f_target 40/25/20/15, exposure U(-3.0,+0.2), 해상도 50/25/15/10, fx 70/30 — 모두
  `v2_pipeline.py` L86-168과 동일. G1~G5 정의도 `v2_realize.safety_gates`(L3600-3624)와 동일.
- **[확인] 미해결 8번(`occluder_side_count` source-field mismatch) 미수정.**
  `analyze_v2_scene_logic.py:1302`가 존재하지 않는 필드명 `"occluder_side"`를 집계한다
  (records는 `occluder_side_target`/`occluder_side_actual`). 결과 `(missing):500`.
  ```python
  # analyze_v2_scene_logic.py:1302
  "occluder_side_count": dict(counter_from(rows, "occluder_side", include_missing=True)),
  ```
  같은 계열로 `occluder_size_class_count`(L1303)도 runner가 기록하지 않는 키라 전량 missing.
- **[확인] 미해결 3번(최소 projected-size 게이트 없음) 미수정.** 코드에 크기 하한이 없다(§2-①).

### 1.4 `_docs/history/2026-07-26-v2-attempt-log.md`

- **[확인] "시행착오가 현재 코드에 남은 위치" 표의 라인 번호는 대체로 유효.**
  `v2_realize._realize_constrained`는 L676(문서와 일치), `deterministic_rgb_render_settings`는
  L3202(일치). `scene_placement_v2` / `scene_visibility_v2` 라인은 이번 조사 범위 밖이라 미검증
  `[추정]`.
- **[확인] exact determinism 설정(CPU + adaptive off + denoise off + threads=1)은 코드에 존재**
  (`v2_realize.py:3209-3213`), 그리고 runner가 `deterministic_cpu=True`로만 호출한다
  (`run_v2_scene_logic.py:755`). production 기본값은 `deterministic_cpu=False`(L3224) 유지 —
  문서 서술과 일치.

### 1.5 `_docs/experiments/v2_scene_logic_500_eda_results.md`

- **[확인] Fig.16/17/18에 대한 line 지목이 정확하다.** 문서가 적은 `analyze:1856`, `analyze:1865`,
  `analyze:1609`가 실제 버그 위치와 정확히 일치(§2-⑤).
- **[확인] 문서가 안 짚은 같은 계열 결함이 더 있다** — §3 참조(azimuth_bin 0, V_actual 0,
  cross_tab의 f_target_bin 0, runner의 `luma_frame or 128.0`).

---

## 2. 6개 항목 검증 결과

### ① proj_size_ratio로부터 camera distance를 역산하는가 — **[확인] YES**

`v2_pipeline.solve_placement` 단계 (1)에서 역산한다.

```python
# v2_pipeline.py:1057-1065
# --- (1) camera distance from proj_size_ratio ---------------------------
# d = fx * W_pallet / (proj_size_ratio * IMAGE_WIDTH)   (pinhole, projected width in px)
#   == focal_mm * W_pallet / (sensor_mm * proj_size_ratio)  (resolution-free lens form ...)
proj = max(float(spec.proj_size_ratio), 1e-3)
d_pallet = fx * PALLET_W / (proj * W)
lens_mm  = fx * SENSOR_MM / W
```
- 입력 `spec.proj_size_ratio`는 `sample_frame`이 5개 폭-비율 bin에서 uniform 추출
  (`v2_pipeline.py:502-504`, `PROJ_SIZE_EDGES=[(0,0.10),(0.10,0.20),(0.20,0.40),(0.40,0.60),(0.60,1.0)]`).
- 카메라는 이 `d_pallet`을 반지름으로 elevation/azimuth 구면 배치(`L1067-1071`).
- **[확인] 거리 상한(clamp)이 없다.** 유일한 보호는 `max(ratio, 1e-3)`이므로 bin0 꼬리에서
  `ratio→1e-3`이면 `d ≈ fx·1.1/(1e-3·W)` = fx 600 / W 640 기준 **약 1030 m**까지 나온다.
  실제 500 진단의 `projected_size_target` 최소값이 0.00016(EDA Fig.21)이라, 그 프레임은
  1e-3로 클램프돼도 수백 m대다. → "카메라 거리 상한" 도입은 코드 근거 있음.

### ② Plan에 `cam_distance_m` 필드가 존재하는가 — **[확인] YES (단, 500 runner는 기록 안 함)**

```python
# v2_pipeline.py:777-786 (dataclass Plan)
cam_distance_m: float         # euclidean camera->pallet-centre distance (the "Z")
# v2_pipeline.py:1224 (생성부)
cam_distance_m=float(d_pallet),
```
- **[확인] 소비처는 3곳뿐**: `_b3_asset_check.py:82-85`(필터), `_v2_calib_200.py:99`,
  `_v2_pilot_2k.py:116`(둘 다 record에 저장).
- **[확인] `run_v2_scene_logic._record_rendered`(L316-480)에도, `v2_realize.label()`(L3662-3776)
  에도 `cam_distance_m`가 없다.** 즉 **500-record 진단 산출물(records/labels/frame_metrics.csv)
  에는 카메라 거리가 존재하지 않는다.** 거리 상한/거리-성능 분석을 하려면 필드 배선이 먼저 필요.
  (대체 가능한 근사치는 `camera_data.location_worldframe`과 `objects[0].location`(=t_obj_cam)
  으로 사후 계산 가능 `[추정]` — 계산식 자체는 자명하나 실제로 돌려보지는 않았다.)

### ③ post-effect **이전** raw luma가 gate/label 판정에 들어가는가 — **[확인] YES (버그 성립)**

호출 순서를 runner에서 끝까지 추적했다.

```python
# run_v2_scene_logic.py:751-764
vr.render(rs, rgb_path, samples=args.samples, deterministic_cpu=True)   # (1) Cycles → PNG 저장
meas = vr.measure(rs)                                                    # (2) 이 PNG를 읽어 luma 측정
noise_scale = vr.render_post(rgb_path, frame_seed,
                             meas.get("luma_frame") or 128.0)            # (3) PNG를 in-place 덮어씀
gates = vr.safety_gates(meas, plan)                                      # (4) (2)의 luma로 G5 판정
label = vr.label(plan.spec, plan, meas, rs)                              # (5) (2)의 luma를 라벨에 기록
```

- **[확인] (2) `measure()`가 luma를 읽는 지점**: `v2_realize.py:3491-3510` —
  `arr = Image.open(rs["rgb_path"]).convert("L")` → `luma_frame = arr.mean()`,
  `luma_pallet = arr[visible_mask].mean()`. 이 시점의 PNG는 **post-effect 미적용 원본**.
- **[확인] (3) `render_post()`는 파일을 실제로 덮어쓴다**: `v2_realize.py:3239-3246` →
  `camera_effects.apply()` → `camera_effects.py:55` `img.save(img_path, format="PNG")`.
  적용 효과: 채널 gain U(0.92,1.08), vignette(반경² 계수 U(0.10,0.35), p=0.7),
  GaussianBlur(p=0.3), gaussian noise σ=U(2,8)×noise_scale(최대 2.5배, p=0.75),
  JPEG q70-95(p=0.6).
- **[확인] (4) G5는 (2)의 값을 쓴다**: `safety_gates`(L3618-3619) `lp = meas.get("luma_pallet");
  g5 = (lp is None or lp >= G5_LUMA_MIN=12.0)`.
- **[확인] 후처리 이후 luma를 재측정하는 코드는 repo 어디에도 없다.** `audit_v2_scene_logic.py`
  에 `luma` 문자열 자체가 0회, `analyze_v2_scene_logic.py`의 `luma_frame/luma_pallet`(L893-894)은
  record/label 값을 그대로 읽는다.
- **결론**: 디스크에 남은 최종 RGB는 vignette(최대 −35%)·noise·JPEG를 거친 이미지인데,
  **G5 통과 판정과 `luma_actual`/`luma_pallet_actual` 라벨은 모두 그 이전 이미지 기준**이다.
  → 학습이 보는 픽셀과 게이트가 본 픽셀이 다르다. 어두운 프레임일수록 괴리가 커진다
  (noise_scale이 어두울수록 커지도록 설계돼 있어 편차도 커짐).
- **[확인] 동일 순서가 다른 드라이버에도 동일**: `_v2_pilot_2k.py:186-187`,
  `_b3_asset_check.py:131`, `_g5_reverify.py:71-72` 전부 measure→render_post 순서.
- 부수 결함 **[확인]**: `run_v2_scene_logic.py:761`의 `meas.get("luma_frame") or 128.0`은
  **완전 검정 프레임(luma_frame==0.0)을 결측으로 오인**해 noise_scale=1.0을 적용한다
  (의도는 2.5배). agent memory의 `noise_bad2` 사례와 동일 패턴.

### ④ audit가 mask 면적 단조성만 보는가 (pixel inclusion / mask hash 없음) — **[확인] YES**

```python
# audit_v2_scene_logic.py:547-551
masks = {name: mask_area(root / "mask" / f"{frame}_{name}.png") for name in mask_names}
areas = [masks[name]["area"] for name in mask_names if masks[name]["decode_ok"]]
mask_monotonic_ok = None
if len(areas) == len(mask_names):
    mask_monotonic_ok = all(areas[i] >= areas[i + 1] for i in range(len(areas) - 1))
```
- **[확인] `mask_area()`(L344-358)는 `(arr > 127).sum()` 스칼라 면적만 반환**(이미지 객체는
  contact sheet 그리기용으로만 보관). 픽셀 집합 포함관계(M4⊆M3⊆M2⊆M1⊆M0)는 어디서도 검사 안 함.
- **[확인] mask 해시 없음.** `sha256_file`(L331)은 존재하지만 호출부는
  `collect_hash_duplicates`(L727-733)뿐이고 **`rgb/f*_rgb.png`만** 순회한다. mask는 해시 대상 아님.
- **[확인] 생성 측 검증도 면적 기반**: `v2_realize.measure()`가 호출하는
  `SP2.validate_mask_decomposition(a0,a1,a2,a3,a4)`(`v2_realize.py:3445`)는 **스칼라 5개**를 받는다
  (`scene_placement_v2.py:1496-1529`, 면적 단조성 + 가법성만 확인).
- **[확인] 테스트도 동일 한계**: `tests/test_scene_placement_v2.py`의
  `test_mask_areas_decompose_into_additive_occlusion_fractions`(L1317),
  `test_mask_validator_reports_negative_nonmonotonic_and_nonadditive_data`(L1350) 모두 스칼라 입력.
  픽셀 포함관계 테스트는 없다.
- **함의**: 면적은 단조 감소인데 실제 마스크 영역이 어긋나는 경우(예: occluder가 팔레트 일부를
  가리면서 동시에 다른 곳에서 마스크가 새는 경우)를 현 감사로는 검출 불가.

### ⑤ EDA Fig.16/17의 bin 0 처리, Fig.18의 False/missing 혼합 — **[확인] 셋 다 falsy fallback 버그**

```python
# analyze_v2_scene_logic.py:1856 (Fig.16)
all_pass_rate_by_derived(rows, lambda r: str(r.get("elev_bin_target") or
    numeric_bin(r.get("elev_target"), [10,20,30,40,50], "elev"))),
# analyze_v2_scene_logic.py:1865 (Fig.17)
all_pass_rate_by_derived(rows, lambda r: str(r.get("proj_size_bin_target") or
    numeric_bin(r.get("projected_size_target"), [0.05,0.10,0.20,0.35], "size"))),
# analyze_v2_scene_logic.py:1609 (Fig.18의 그룹핑 함수 all_pass_rate_by)
groups[str(r.get(group_key) or "(missing)")].append(r)
```
- **[확인] Fig.16**: `elev_bin_target`은 정수(라벨 `v2_labels.elev_bin_target`, 값 0..6). **0은
  falsy**라 `or` 우측으로 떨어져 `"elev [-inf,10)"` 같은 문자열 범주가 된다. 동시에 렌더 실패
  65건은 라벨 자체가 없어 `None`→같은 문자열 fallback → **bin 0과 non-rendered가 한 막대에 섞인다.**
- **[확인] Fig.17**: `proj_size_bin_target` 동일 구조. bin 0(<10% 폭비율)이 문자열 fallback으로 이동.
- **[확인] Fig.18**: `cargo_on`은 Boolean. **`False`가 falsy**라 `"(missing)"`로 바뀌고 렌더 실패
  65건과 합쳐진다. EDA 문서가 계산한 `199/(220+65)=0.698`와 정확히 일치하는 메커니즘.
- **[확인] 왜 Fig.8은 같은 버그가 안 보이나**: `f_explicit_actual_bin`은 L932-935에서 **무조건
  `str()`로 변환**되어 `"0"`(truthy)이 된다. 반면 `f_target_bin`은 값이 이미 있으면 int로 남는다
  (L926-928은 `is None`일 때만 문자열화) → **controlled 모드에선 f_target>0이라 bin0이 안 나와
  현재는 잠복(latent)**. proposal 분포를 바꿔 f_target_bin=0이 controlled에 들어오면 즉시 발현.
- **[확인] 같은 계열 추가 결함(문서 미기재)**:
  - `analyze:1381` `azimuth_bin_count`: `r.get("azimuth_bin") or "(missing)"` → **azimuth bin 0
    (12개 중 유효 bin)이 missing으로 집계**된다.
  - `analyze:1375-1376` `V_actual_count`/`V_vis_count`: V=0이 missing으로 집계(가능한 값).
  - `analyze:1673` `cross_tab_plot`: 행/열 키 모두 `or "(missing)"` → Fig.8/Fig.10 공통 위험.
- **[확인] 회귀 테스트 부재**: `tests/test_analyze_v2_scene_logic.py`의 12개 테스트 중 bin-0/
  Boolean-False 그룹핑을 다루는 것은 없다.

### ⑥ gen_trunc_addon.py의 "상세 overlay" 구현 잔존 여부 — **[확인] YES, 통째로 남아 있음**

- 함수: **`render_frame()`**, `scripts/data_prep/blender/gen_trunc_addon.py:487-714`.
  오버레이 블록은 `# === Detailed Overlay ===` 주석(L577)부터 `img.save(...)`(L712)까지.
- 구성 요소(전부 [확인], 라인 지정):
  ```
  L581-590  PIL 재시도 로드(Blender PNG write race, 5회 backoff)
  L616-630  cuboid 12 edge를 축별 색으로 (X=red / Y=green / Z=blue, X_EDGES/Y_EDGES/Z_EDGES)
  L632-651  keypoint 9점 per-ID 고유색 + 화면밖은 회색 + ID 텍스트
  L653-666  ★pose axis: centroid에서 AXIS_LEN_M=0.5 m, matrix_world 3x3 col(0/1/2) 투영, X/Y/Z 라벨
  L668-699  ★info panel(좌상단 175x240): Frame / Object / Scenario / BG /
            Distance(cam-pallet) / Cam dist(surf) / Cam height / Elev + V:n_in/8 /
            Lens mm + HFOV° / Kpt Vis% / Ray Vis% / Combined n_both /
            Area%(bbox 면적비) / Pitch / Yaw / Roll / ★Quaternion / Size mm /
            Cam 좌표 / Trunc·Occ·Cargo 플래그
  L701-710  축 범례(우하단)
  ```
- **[확인] 다만 요청 항목 중 2개는 이 구현에 없다**: **azimuth**는 `meta_extra`에 존재하나
  패널에 인쇄되지 않고, **projected size target vs actual**도 없다(대신 bbox 기반 `Area%` 1개).
- **[확인] 대조 — 현 v2 오버레이는 훨씬 빈약**: `audit_v2_scene_logic.draw_overlay`(L427-459)는
  cuboid 라인 + 코너 번호 + centroid 점 + 헤더 1줄(`mode/audit/gate/fail`)이 전부다.
  pose axis·거리·HFOV·quaternion·가시율 없음. `_v2_pilot_overlay_all.py:48`도 동급.
- **[확인] gen_trunc_addon의 post-effect 순서는 v2와 다르다**: `CE.apply(img_path, frame_idx)`가
  **mask 렌더 직후, 오버레이 그리기 직전**(L508)에 호출된다 → 오버레이는 post-effect가 적용된
  최종 이미지 위에 그려진다. (v2 constrained 경로는 render_post가 measure 뒤라 오버레이 재생성
  시점 기준으로는 결과적으로 동일하지만, **판정(G5)이 raw에서 이뤄지는 건 v2 고유 문제**.)

---

## 3. 추가로 확인된 불일치 (계획에 영향 있는 것만)

1. **[확인] projected-size 하한 게이트 부재.** `v2_pipeline`·`v2_realize`·`run_v2_scene_logic`
   어디에도 최소 투영 크기/최소 mask area 조건이 없다. G1~G5 중 크기 관련 조건은 없고
   (`v2_realize.py:3600-3624`), 500 진단에서 M0<100px 프레임 12건이 all-pass로 통과한 이유.
2. **[확인] magenta 임계가 3중으로 다르다.**
   - `run_v2_scene_logic._magenta_fraction`(L282): `R>140 & B>140 & G<90`
   - `audit_v2_scene_logic`(L322) / `analyze_v2_scene_logic`(L593): `R>180 & G<90 & B>180`
   analyze는 decoded 값을 record 값보다 우선한다(L761-765)라 최종 수치는 180-기준으로 수렴하지만,
   `records.jsonl`의 `magenta_fraction` 컬럼만 보면 서로 다른 정의가 섞인다.
3. **[확인] `projected_size_actual`은 in-frame 여부·in-front 여부를 무시한다.**
   `run_v2_scene_logic._projected_size_actual`(L286-291)은 `uv8_v4`의 x 범위 폭을
   `(max-min)/W`로 계산 — 화면 밖 코너와 카메라 뒤 코너(z<0으로 발산한 u)도 포함된다.
   truncation/근접 프레임에서 actual 폭비율이 과대 추정될 수 있다.
4. **[확인] `f_actual_bin` 정의가 label에만 있고 500 record에는 없다.**
   label `v2_labels.f_actual_bin`(`v2_realize.py:3726`)은 있으나 runner record에는 없어
   analyze는 `f_total`에서 재계산한다(`analyze:929-931`).
5. **[확인] `cargo_on` 정의가 두 개다.** label은 constrained일 때
   `n_cargo_requested>0`(요청 기준), legacy일 때 `spec.cargo_on`(처방 기준)
   (`v2_realize.py:3729-3737`). 별도로 `cargo_on_prescribed`도 기록. record는
   `bool(placement.get("n_cargo_requested",0))`(`run_v2_scene_logic.py:365`).
   → EDA에서 "cargo" 축을 말할 때 requested/placed/prescribed 중 무엇인지 명시 필요.

---

## 4. 현재 500-record 진단의 정본 수치

출처: `_docs/experiments/v2_scene_logic_500_eda_results.md` + `_docs/history/2026-07-26.md`
(원본 산출물 `data/pallet/_v2_scene_logic_500_seed7500/eda/`). 아래 수치는 **문서 인용**이며
이번 세션에서 원본 csv/json을 재집계하지는 않았다 `[추정: 재계산 미수행]`.

```
항목                                      값
────────────────────────────────────────────────────────────
전체 record                               500
렌더 성공                                 435 / 500 = 87.00%
realize 실패                              65 / 500 = 13.00%
  controlled / bounded_local_search_exhausted   62
  controlled / anchor_fail                       1
  context-rich / anchor_fail                     2
rendered 기준 G1-G5 all-pass              364 / 435 = 83.68%
proposal(record) 기준 all-pass            364 / 500 = 72.80%
automated audit pass / fail               493 / 7
fatal visual defect                       0
magenta / corrupt RGB / corrupt mask      0 / 0 / 0
empty target mask                         4  (idx 48, 321, 453, 478)
anchor reject placeholder                 3  (idx 103, 220, 286)
exact BVH collision                       0 / 497 evaluated
mask monotonicity failure                 0
```

게이트별 실패율 (분모: rendered 435, 괄호는 baseline 2k = rendered 2000)

```
gate   baseline 2k fail        new 500 rendered fail
G1     875/2000 = 43.75%       44/435 = 10.11%
G2     393/2000 = 19.65%        0/435 =  0.00%
G3     635/2000 = 31.75%       10/435 =  2.30%
G4      14/2000 =  0.70%        1/435 =  0.23%
G5     210/2000 = 10.50%       19/435 =  4.37%
all-pass  40.00%                        83.68%
```
※ 두 실행은 runner·proposal 분포·acceptance 경로가 달라 **causal ablation이 아니다**(문서 판정).

diagnostic mode별

```
mode                    frames  rendered  all-pass  /frames   /rendered
clean-static             100      100        92     92.00%    92.00%
cargo-only               100      100        85     85.00%    85.00%
context-rich             150      148       110     73.33%    74.32%
controlled-occlusion     150       87        77     51.33%    88.51%
```

source-decomposed occlusion (mode별 mean)

```
mode                   n(valid)  f_static     f_cargo   f_context  f_explicit
cargo-only              100      ~0.0000008   0.1119    0.0000     0.0000
clean-static             99      ~0.0000001   0.0000    0.0000     0.0000
context-rich            145      ~0.0000007   0.0555    0.0117     0.0000
controlled-occlusion     87      ~0.0000001   0.0527    0.0005     0.2123
```

controlled occlusion 전달

```
target 150 → rendered 87 (58.00%) → all-pass 77
explicit visible               87/87 rendered = 100%
|f_explicit - f_target|        rendered-only n=87: q50 0.0382 / q90 0.1031 / q95 0.1111
                               전체 target n=149:  q50 0.0984 / q90 0.3682 / q95 0.3931
actual side                    left 32 / right 43 / bottom 9 / center 3  (center 3.45%)
```

주요 실패 원인·리스크 (문서 판정)

```
1  controlled bounded search exhaustion 62/150 = proposal delivery 최대 병목
2  center occluder 3/87 = center 커버리지 사실상 없음
3  tiny target: accepted 중 M0<100px 12건 (idx 4,41,125,230,246,284,290,359,392,416,467,481)
   → architecture-derived 최소 projected-size 게이트 부재
4  front/opening visibility <0.5: front 29 / left 39 / right 44 (rendered 435 기준)
   → G1-G5와 별개의 alignment eligibility 축 필요
5  runtime: 전체 median 25.64s (clean 13.69 / cargo 18.16 / context 26.11 / controlled 46.64)
6  chart 16/17/18은 analyzer 수정 전 정량 인용 불가 (§2-⑤)
```

교정표(문서가 frame_metrics.csv에서 재집계한 값, rendered 435 기준)

```
elev_bin   각도        rendered  all-pass  rate        size_bin  범위        rendered  all-pass  rate
0          0.5-3°       38        32       84.21%      0         0.00-0.10    88        80       90.91%
1          3-8°         74        59       79.73%      1         0.10-0.20    86        80       93.02%
2          8-15°        86        73       84.88%      2         0.20-0.40    81        76       93.83%
3          15-25°       77        63       81.82%      3         0.40-0.60    85        72       84.71%
4          25-40°       75        63       84.00%      4         0.60-1.00    95        56       58.95%
5          40-60°       44        37       84.09%
6          60-80°       41        37       90.24%      cargo_on  False 220/199 = 90.45%
합계                    435       364      83.68%                True  215/165 = 76.74%
```

manual visual audit (500 전수)

```
pass 286 / auto-gate reject 67 / not-rendered 65 / manual extreme-small 12 /
audit-fail 4 / very-small warning 39 / dark warning 22 / noise warning 5
→ G1-G5 accepted 364 = pass 286 + extreme-small 12 + warning 66
```

---

## 5. 이번 조사에서 검증하지 않은 것 (정직 표기)

- `[추정]` `scene_placement_v2.py` / `scene_visibility_v2.py` 내부(contact matrix, bounded search,
  anchor/LOS)는 호출 인터페이스(`validate_mask_decomposition`, `external_corner_gate_metrics`,
  `constrained_hdri_paths`)만 확인했고 본체 로직은 읽지 않았다.
- `[추정]` 500 진단의 원본 `frame_metrics.csv` / `summary.json`을 직접 재집계하지 않았다.
  §4 수치는 EDA 문서 인용이다.
- `[추정]` 어떤 스크립트도 실행하지 않았다(unit test 포함). 따라서 "현재 코드가 실제로 이렇게
  동작한다"는 주장은 **정적 실행흐름 추적** 근거이며, 렌더 재현으로 확인한 것은 아니다.
  단 §2의 6개 항목은 호출부→피호출부를 끊김 없이 추적했으므로 `[확인]`으로 표기했다.
