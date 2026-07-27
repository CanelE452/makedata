# 작업 기록

## 개요

팔레트 6D 포즈 추정 프로젝트의 주요 작업 이력. 최신순 정렬.

- 2026-07-27: Phase 9D usable 50-frame continuous EDA의 17개 figure(PNG 전수 확인)를 [결과 해석 문서](../experiments/v2_smoke50_continuous_eda_results.md)로 정리했다. 표본 50·usable 선택 편향을 전제로 못 박고, figure 10/11/12가 tautology(base rate 1.000, LOO Brier ~1e-32, 신뢰 격자점 0~2/200)로 무정보인 이유를 별도 섹션으로 설명했다. 부수 확인: camera distance q50 3.44 vs 3.180은 분위수 규약(higher vs linear) 차이, fig 14의 0.32 계단은 anchor fx 605.9065 16장 점질량, fig 08 잔차 전부 양수(계통 결함 B5), V_vis=4가 17/50(G1 경계). 상세 [2026-07-27.md](2026-07-27.md).
- 2026-07-27: Blender v2 scene logic 500-record EDA의 22개 chart, 500-frame manual audit, contact sheet, 표 결과를 [결과 해석 문서](../experiments/v2_scene_logic_500_eda_results.md)로 정리했다. proposal/rendered 분모, controlled error 이중 분모, automated audit 493 vs manual clean 286을 구분하고, chart 16-18 grouping 결함을 발견해 교정표와 재생성 조건을 기록했다. 상세 [2026-07-27.md](2026-07-27.md).
- 2026-07-26: Blender v2 constrained scene assembly를 additive opt-in으로 구현하고 exact 20-frame smoke 및 500-record/435-render 진단을 검증했다. fatal defect 0, rendered 조건 all-pass 83.68%; controlled delivery 58%와 tiny target 때문에 production default는 legacy로 유지한다. 최종 요약은 [2026-07-26.md](2026-07-26.md), 133개 보존 실행의 전체 시행착오는 [2026-07-26-v2-attempt-log.md](2026-07-26-v2-attempt-log.md)에 기록했다.
- 2026-07-25: v2 규약 구현(B3 realize/measure/G1~5/규약 realize측 + D 캘리브200 + G5 dark폐기버그 visible-luma 수정) 후 파일럿 2k 렌더·전축감사(perm/night/12kp PASS, 야간 G5 22→10%)·전수오버레이로 ★마젠타 배경오염 45장 all_pass 발견·전 DR축 분포EDA(처방완벽 max|Δ|≤0.05pp·실측 f_actual+27.6pp·occluder center 2%·all_pass 40%)·진단패키지(diagnosis/pilot_frames.csv 2480행+solve_reject480 재현+code+온보딩md, ★f_cargo가 배경 벽/선반 가림 오집계 45.4%·center occluder d_occ 1차+C2 62% 드롭·통과율40% 주범=G1 코너가림)·온보딩md(blender_mcp_onboarding.md 40실패). launcher 무한루프 OOM 사고(복구·데이터무결). 40k 미승인·commit 안 함. 상세 [2026-07-25.md](2026-07-25.md).
- 2026-07-23: E-단면 12kp(efront_kp12) 스킴 측정→결정→구현. 4팔레트×앞면2 개구부 실측(P2 long=닫힌개구부0=4-way아님, P1 short=bottom_open, ±면대칭→축쌍2). efront_kp12.py 신규(intrinsic 비율×per-frame dims, kp12_valid=물리축 기준). gen 2개 compute_annotation_v4에 additive 배선(스모크 EXIT0·기존키 불변·outer4 0.0px·1만장 재생성X). 부수: scene_noemit.usd(emissive 세척본), 4팔레트 카탈로그 렌더.

- 2026-06-16: gen_dataset_v4.py + run_dataset_v4.sh 신규(camera-facing 0123 대규모 생성, CLI/resume/chunk재시작). 파일럿 120장 라벨 전수통과(conn0/front_near/simple-quad 120/120, 마젠타0), elev15~58·scene1/3·ratio42%·azim360 분산. raycast 86% reject=병목, 15.4s/frame → 5000장 ~21.6h. 저장 data/pallet/training_data_v4/.

---

- 2026-06-15: preview10 grazing 배제 게이트 추가 — FRONT 면 정면도 front_cos>=0.40(edge-on 차단) + facing_margin 0.30→0.60. compute_perm_v4가 front_cos 반환. 재생성 10/10 PASS(0123 직사각). → `_docs/history/2026-06-15.md`
- 2026-06-15: compute_perm_v4 (카메라 동적 0123 keypoint ID) + 비등방 비율 랜덤(40%/±12%) 구현, scene_1/2/3 10샘플 프리뷰 생성·검증 (전수 PASS). → `_docs/history/2026-06-15.md`

## 2026-04

### 실내 환경 합성 데이터 테스트 (04-07)
- 실제 추론 환경(연구실)과 합성 데이터 간 domain gap 분석, Blender에 실내 방 환경 구축 + 10프레임 테스트 렌더링
- 상세: [2026-04-07.md](2026-04-07.md)

### Blender 합성 데이터 대량 생성 v65~v70 (04-06)
- 탑다운 뷰/엣지크롭/어두운 색상/빈 팔레트 추가, 총 ~8100프레임 생성
- 상세: [2026-04-06.md](2026-04-06.md)

---

## 2026-03

### Blender 렌더링 파이프라인 구축 + Cuboid 정합 (03-27)
- 상세: [2026-03-27.md](2026-03-27.md)

### Blender 합성 데이터 씬 구성 (03-25)
- 상세: [2026-03-25.md](2026-03-25.md)

### config 통합 및 TensorBoard 설정
- `config/default.yaml` 생성 — 모든 하이퍼파라미터 단일 소스로 통합
- `train_dope.sh`를 `default.yaml`에서 값을 읽도록 리팩토링
- `scripts/launch_tensorboard.py` 추가 — 실험별 loss 비교, 요약 출력
- TensorBoard 설치 (`pallet-pose` conda env)
- scripts/ 하위 디렉토리에 CLAUDE.md 추가 (data_prep, dope, self_training)

### docs 구조 재편
- `_docs/` 하위를 preprocessing, method, experiments, survey, history로 분리
- 키포인트 정의 문서 복원 (`preprocessing/keypoint_definition.md`)
- 합성 데이터 파이프라인 문서 추가 (`preprocessing/data_pipeline.md`)

### 상태줄 최적화
- `statusline.sh` Windows 최적화: jq 8회 → 1회 호출, 12초 → 0.15초
- ccusage 직접 호출 제거 (Claude Code 자식 프로세스 대기 문제) → JSON 내장 비용 데이터 사용

---

## 2026-02 ~ 2026-03 (합성 데이터 v11)

### 렌더링 파이프라인 안정화
- Isaac Sim 4.5.0 DLL 충돌 해결: `CUDA_MODULE_LOADING=LAZY`
- 200프레임/배치 재시작 전략 (메모리 누수 대응)
- DLSS 완전 비활성화: `anti_aliasing=0` + `/rtx/post/dlss/enabled=False`

### Domain Randomization 개선 (iter1 → iter13)
- **iter3-5**: 팔레트 색상 override — `diffuse_texture` disconnect + opacity/metallic 고정
- **iter4**: Distractor 색상 — per-distractor material 생성 (`stage.Traverse` 방식 폐기)
- **iter13**: 바닥/벽 텍스처 — USD API `Sdf.AssetPath` 직접 변경 (Replicator API 불가 확인)
- **v11**: 조명 상한 하향 (DomeLight 5000→3500, Main 400K→300K), brightness skip 240으로 완화

### 키포인트 Convention 확립 (Y=UP, v2)
- 메시 노멀 분석 방식 폐기 (팔레트에서 불안정)
- Canonical bbox 방식 도입: `R_canonical = R_yz_swap @ euler(base_rot)`
- ORIENTATION_OVERRIDES 4개 모델 전수 검증 완료
- 검증 스크립트: `verify_keypoints.py`, `DIAGNOSE_MODELS=1` 환경변수 진단 모드

### Nucleus Props 대체
- Isaac Sim 4.5에서 `Simple_Warehouse/Props/` 에셋 없음 확인
- Enhanced primitive fallback: cube 60% + cylinder 20% + cone 10% + sphere 10%

---

## 2026-01 ~ 2026-02 (DOPE 학습)

### Pretrain (pallet_category)
- 합성 데이터 ~2,000장으로 60 epoch 학습
- sigma=4.0 설정 (sigma<1은 gradient vanishing)
- 최종 loss: belief=0.043, affinity=0.004

### Fine-tune (pallet_v11)
- pretrain weight에서 91 epoch 추가 학습 (lr=5e-5)
- 최종 loss: total=0.044 (epoch 117)

### 평가 체계 구축
- `evaluate_on_val.py`: PCK@3/5/10px + PnP reproj error + ADD + 5cm-5°
- `visualize_inference.py`: belief heatmap + keypoint + cuboid wireframe
- `visualize_pretrain.py`: 종합 시각화 (belief + cuboid + PnP yaw/pitch/roll)

---

## 2025-12 ~ 2026-01 (프로젝트 초기)

### 아키텍처 결정
- DOPE (keypoint-based) 선택 — 팔레트는 비대칭 직육면체로 keypoint 방식에 적합
- Depth-free (RGB only) 접근 — 산업 현장 카메라 호환성
- 3단계 파이프라인 설계: 합성데이터 → Geometric Filter → Self-Training

### 환경 구축
- conda env `pallet-pose` (PyTorch 2.10 + CUDA 12.6)
- Isaac Sim 4.5.0 standalone 실행 환경
- Docker 실시간 추론 환경 (RealSense D435i)
- Deep_Object_Pose 서브모듈 통합 + Windows 호환 패치

### Self-Training 모듈 개발
- `scripts/self_training/` 5개 모듈 구현
- Geometric Filter 3단계 설계 (Augmentation Consistency + Edge Consistency + Pallet Ratio)
- PnP solver: EPnP + RANSAC wrapper
- FixMatch augmentation: photometric-only (좌표 불변)
- 2026-06-15 preview10 수정: FRONT(0123)=카메라 near 면(평면 팔레트 2D면적 far오판→3D거리), 배경 magenta 제거(parking_lot/broken HDRI 제외+Cycles), visibility gate(area>=4.5%+base/측면 raycast). 10/10 검증.
- 2026-06-15 compute_perm_v4 FRONT 판정 normal-facing 교체: 면 중심 3D 거리 → dot(outward_normal, cam-center) max. top-down 평면 팔레트 near 흔들림 해결(거리차 0.04~0.11m→facing margin 0.46~0.87). preview10 10/10 PASS, connector_cross=0, magenta 0.
- 2026-06-16: gen_dataset_v4 배경 다양화(Polyhaven HDRI 7종, magenta 0 검증) + raycast 가림완화(0.55→0.30, partial-occ 84%, x3 속도, GT reproj 0.000px). 재파일럿 80/80 통과. 5000장 ~6.9h.
- 2026-06-16: 팔레트 머티리얼 단색→Polyhaven 실사 나무 결 텍스처(albedo+normal+rough) 전환, 밝기DR=albedo×multiply tint. 10장+클로즈업 검증(grain 0.11~0.19, conn0/front_near/magenta0 전수). config만 교체, USD 무수정.
- 2026-06-16: scene_3(Pallet_3) deck "청록/회색" 진단 — 머티리얼/UV/노드 버그 아님(308메시 전부 UV+텍스처 정상, 실제 픽셀 cool_frac=0.00 warm). 원인=faded_gray 변종(brown_planks_03 중립회색)이 cool HDRI에서 청록으로 읽힘+녹색 오버레이 착시. 수정=config 1줄 faded_gray→aged_brown(웜). _mat_test10d 10장 scene_3 R-B+38~+58 teal0 conn0 검증. USD/코드 무수정 라벨무영향.
- 2026-06-16: gen_dataset_v4 출력 구조를 test_palletobj_r3(flat)로 전환 — png+json 폴더 루트 colocated, overlay/{6d}.png 전수(every1), stats→out_root/logs, _crop/_stats subdir 제거. resume=폴더 루트 png 카운트. 후처리 _restructure_to_r3.py(재렌더 없이 train_batch_000/001 변환, 002 삭제). 소량 검증(새 구조+SKIP+부분 이어감 png==json==overlay) 통과.
- 2026-06-16: 목재 팔레트(scene_2/3) 나무 스킨 다양화 — Polyhaven 나무 판자 6종 추가(textures_wood 9 base/27 png), config wood 그룹 6→11 variant(밝은pine~tan~cabin~dark_knot~grey~reddish, uv_scale 0.85~1.15, weight합1.0). 코드무변경 config-only(plastic/floor 불변). 카탈로그 시트 11장+랜덤적용 8장 검증(살짝씩다른 결/색/톤·자연접지·마젠타0·conn0/front_near 전수) → data/pallet/_wood_skin_compare/. split 미변경.
- 2026-06-16: 바닥 텍스처 항상 회색 버그 수정 — floor_texture 라벨 무관 회색. 원인=randomize_background가 매프레임 BG_industrial 재노출→자체 `Floor*_Asphalt_0` 20장(z≈0)이 FloorRandPlane(z=-6mm) 가림(raycast plane 0.7%↔asphalt 93%, 사용자 가설 CONFIRMED). 수정=blender_config FLOOR_BG_GROUND_HIDE + randomizers `_hide_bg_ground()`(매프레임, randomize_floor서 호출). 검증 plane 93.7%, 6종 RGB stddev R25/G24/B36(red_brick/tile_white/wood 라벨일치) → data/pallet/_floor_fix_test/_sheet.png. 접지/raycast/라벨 무영향, USD/씬 무수정.
- 2026-06-17: emptywood 보조셋(목재 scene_2/3 + 빈 데크 + distractor 유지) 설정 검증 — gen_dataset_v4.py EMPTYWOOD_WOOD_ONLY/NO_CARGO env 플래그(기존 구현) 동작 확인, 15장 smoke pass 15/15(scene_1=0,connX=0,front_near=True,데크 cargo 없음,distractor 유지), 풀 3000 커맨드 확정.
- 2026-07-03: train_palletobj_addon_v1(D435i 정합 6000장) 재생성 런처 `scripts/data_prep/blender/run_addon_v1.sh` 신규 — gen 로그에서 실제 명령 복원(run_mass_10k.py, seed 7777, 6000장, _sandbox_palletobj_production.blend, Blender 5.1 EEVEE). preflight 의존물 확인 + 기존셋 덮어쓰기 가드(--force/--start_idx/--out variant). 결정성 확인(random 단일 시드→시나리오 bit재현, camera_effects frame_idx 결정적). ⚠️ 재현 스크립트 5개 git 미추적 상태.
- 2026-07-26: makedata 저장소 분리 push — FoundationPose fork(NVlabs origin, 46커밋/120.8MB, assets mp4·jpg가 과거 blob에 상주)에서 orphan `main`으로 새 히스토리 시작(커밋 4819fb6, 194 entries/2.49MB). 기존 main→`legacy/foundationpose-main` rename으로 로컬 보존, remote는 origin=CanelE452/makedata + upstream=NVlabs/FoundationPose. `git rm --cached`가 orphan에서 거부→`git read-tree --empty` + `git add --pathspec-from-file`로 실존 192개만 정밀 스테이징. .gitignore에 이미지/영상/모델/3D 확장자 차단 추가(추가 전후 후보 대조 → 누락 0). Deep_Object_Pose는 서브모듈(035f8e7=NVlabs master tip), 로컬 수정 62줄은 `scripts/dope/deep_object_pose_local.patch`로 보존. 원격 검증: ls-tree 194, 이미지·영상·모델 매칭 0건.
- 2026-07-26: makedata 에서 Deep_Object_Pose 서브모듈 제거 — 저장소 참조만 해제하고 로컬 폴더(로컬 수정 62줄 포함)는 유지. `.git` 이 디렉토리(미흡수, .git/modules 없음)임을 확인한 뒤 `git rm --cached` + `.gitmodules` 제거 + `git config --remove-section submodule.*`. `deinit -f` 는 서브모듈 워킹트리를 삭제하므로 미사용. `.gitignore` 에 `Deep_Object_Pose/` 추가(clone·patch 적용법 주석 병기). `scripts/dope/deep_object_pose_local.patch` 는 복원용으로 유지.
- 2026-07-27: v2 개편 Phase 4 — PnP eligibility 감사기 `scripts/data_prep/blender/audit_pnp_eligibility.py` 신규(bpy-free). belief map stride 8px(원본 기준, DOPE 로더 crop이 픽셀 등가라 리스케일 없음) → threshold 후보 16/24/32px, visible-kp bbox min side 기준. 평가 코드와 동일한 solvePnPRansac+EPNP(8.0px/100iter)로 exact-GT PnP + sigma=1/2/3px 가우시안 keypoint 섭동 200회 Monte-Carlo(435프레임 실행). 3D 점은 canonical object frame이 아니라 라벨 자신의 world cuboid를 centroid로 옮겨 사용(camera_dynamic_0123_v4 perm이 프레임마다 달라 canonical은 최대 426px 어긋남, 실측). 결과: 1~8 cell 스윕에서 knee 없음 + 최엄격 후보도 sigma=2px에서 29.3% 5cm-5도 실패 → **최종 threshold 확정 불가(근거 부족)**로 보고, manifest에 physical_valid/gate_valid/pnp_eligible_candidate_2·3·4cell/tiny_warning/pnp_stress만 추가(프레임 삭제 0). 산출물 reports/v2_revision/pnp_threshold_study.{csv,md} + pnp_stability_continuous.pdf + pnp_eligibility_manifest.{csv,json}. 테스트 211 passed(신규 41).
- 2026-07-27: v2 개편 Phase 5 — mask 무결성 감사를 면적 단조성에서 픽셀 단위로 승격(`audit_v2_scene_logic.py` 확장, `mask_area()`는 Phase 4 호환 위해 보존). strict decode(verify+load, LOAD_TRUNCATED_IMAGES=False 고정) + 바이트 sha256 + content sha256(전경 packbits) + `M4⊆M3⊆M2⊆M1⊆M0` boolean 비교 + frame내/frame간 duplicate 분리 + projected-cuboid convex hull 정렬(monotone chain + Sutherland-Hodgman 클립, numpy/PIL만) + RGB↔mask 해상도 일치. 실측이 설계를 바꾼 3건: ①all-black mask는 sub-threshold noise 때문에 sha256이 전부 달라 content 기준 그룹핑 없이는 empty-target duplicate가 0건 검출(→`__all_black__` 키) ②같은 실루엣도 바이트가 달라 content 해시 필요(435프레임 within-frame 그룹 617개 중 byte-exact 3개) ③"occluder 놨는데 mask 동일"은 결함이 아님(f_context==0이면 정상) → 4상태 판정으로 false-positive 4건 제거. 435+20프레임 실행: inclusion 위반 0, stale duplicate 0, empty M0 4(48/321/453/478)가 단일 empty_target_defect 그룹, hull IoU 중앙값 0.970. 산출물 reports/v2_revision/mask_hashes.csv + mask_duplicate_groups.json + mask_pixel_inclusion_failures.csv + mask_integrity_source_masks.png. 테스트 251 passed(신규 40).
- 2026-07-27: v2 개편 Phase 6 — 상세 overlay 복원 `scripts/data_prep/blender/overlay_v2_detailed.py` 신규(bpy-free, PIL+numpy만). 현재 audit overlay(cuboid+centroid+헤더 1줄)에 gen_trunc_addon의 pose axis/카메라 거리·높이/elevation/lens·HFOV/가시율/pitch·yaw·roll/quaternion/info panel/범례를 복원하고, Phase 1~5 신규 지표(dist>limit violation, ground continuity, noise tier·sigma·final luma, pnp eligibility 2/3/4cell·tiny·stress, mask pixel inclusion·hull IoU, M0/M4 컨투어)를 추가. 핵심 설계는 **absent/null/present(0) 3상태 분리** — 구 렌더에 없는 필드를 조용히 0으로 채우지 않고 `N/A (field absent)`로 명시(falsy-0 버그 방지). pose axis는 pose_transform이 object→CAMERA임을 실측 확인(centroid 투영 정확 일치, cuboid 재현 1e-14px) 후 K@(R·0.5m+t)로 투영. 500프레임 + smoke20 전수 overlay + contact sheet 44장을 `<ds>/eda_phase6/`에 생성(기존 eda/eda_phase5 overlay는 guard로 보호). 육안 검증 11장 + 시트 2장: 컨투어·cuboid·축 정합 OK, 텍스트 겹침 0. 발견: gate PASS인데 94m/1015m 거리·M0 13px인 프레임이 빨간 VIOLATION으로 즉시 식별됨. 테스트 297 passed(신규 46).
- 2026-07-27: v2 개편 Phase 7 — `run_v2_scene_logic.py`에 `--completion-mode {records,usable}` 추가 (기본 records = 기존 20/500 proposal 동작 그대로). usable 모드는 usable N장을 정확히 채울 때까지 proposal을 계속 뽑고(`iter_proposals` 제너레이터, generate_accepted와 동일 draw·accept-time quota 규칙), 배달 id는 0..N-1 연속, 각 record에 proposal_index/attempt_seed 기록. usable 조건 19개를 **각각 독립 계산 후 AND**(`usable_conditions`, None=미측정은 절대 통과 아님): physical(Phase1 거리<=10m·Phase2 ground continuity·collision·support·clearance·corrupt·M0 non-empty) + magenta + Phase5 픽셀 포함관계·cross-frame stale mask + G1~G5(Phase3 final luma). 모든 reject를 `records_rejected.jsonl`에 보존(신설; stage=solve/mode_filter/render, 사유 `solve_reject:C1`·`gate_fail:G5`·`usable_reject:*`), reject된 시도의 이미지는 삭제. PnP threshold는 Phase 4에서 미확정이므로 조건에 넣지 않고 manifest에 SIZE 축만 `pnp_size_eligible_2/3/4cell`로 기록(cv2가 Blender에 없어 solve 축은 audit_pnp_eligibility.py 몫), README/manifest에 **"final training-ready 아님"** 명시. 실측 usable 10장: proposal 21·render 14(71% 통과)·324s, reject 사유는 G5 1건뿐이고 실제 병목은 controlled-occlusion의 explicit occluder realize 실패(6/8). 배달 10장 중 1장이 9.77m·11px(tiny, 2cell 미달)로 Phase 4 threshold 필요성 재확인. records 모드 회귀: 5프레임 비교에서 record 146필드 diff 0·RGB 바이트 동일·mask 픽셀 동일(label은 stage_runtime_s만 상이). 테스트 323 passed(신규 26).
- 2026-07-27: v2 개편 Phase 8 — 논문용 continuous EDA `scripts/data_prep/blender/analyze_v2_continuous.py` 신규(bpy-free, matplotlib+numpy만) + 기존 `analyze_v2_scene_logic.py`의 falsy-0 버그 15곳 회귀 수정. 수정은 `group_label()`(None/공백만 missing)과 `bin_or_numeric_fallback()`(bin 존재 판정을 `is not None`으로) 두 헬퍼로 통일 — 실측 효과: Fig18 all_pass by cargo_on이 `(missing) 285장 0.6982 / True 215장 0.7674`에서 `(missing) 65 / False 220장 0.9045 / True 215장 0.7674`로 바뀌어 **cargo=off가 나쁘다는 결론이 뒤집혔고**(0.698<0.767 → 0.905>0.767), Fig17은 bin0 88장이 다른 binning 체계의 가짜 bin 2개(45+43)로 분열돼 있던 것이 단일 bin(0.9091)으로 복원, Fig16 bin0 38장·azimuth_bin 0 36장·V_vis 0 1장도 missing에서 분리(이들 변수의 실제 missing은 0건). 신규 모듈은 ECDF 주 + bandwidth 명시 KDE 보조(bounded는 reflection 보정, domain 밖 밀도 0), azimuth는 von Mises circular KDE(kappa는 LOO 우도 CV; 실측 |f(0)-f(360)|=2.78e-17, 이음매 step/인근 median step=0.9978), zero-inflated는 P(X=0) 점질량과 X>0 조건부 분리(f_total P0=0.434 등), pass-probability는 순수 numpy Nadaraya-Watson + LOO Brier bandwidth + seed 1000·1000 bootstrap pointwise 95% CI + Kish n_eff<20 점선, 이산변수 42개는 `DISCRETE_FIELDS`에 등록해 KDE 호출 시 `DiscreteVariableError` raise(코드로 강제, 테스트로 검증). 필수 13 figure + 보조 4를 PNG 300dpi·PDF 양쪽 생성, 캡션마다 denominator·missing 수 기재. 435프레임 legacy셋(Phase 1/3 필드 없음 → 01/05/10을 "N/A: field not present" 패널로 명시, raw luma 무단 대체 금지)과 ph7 usable10셋(01/05 정상 출력) 양쪽 실행 17/17. 발견: `projected_size_actual`이 435장 중 87장(20%) >1.0·최대 39.09로 과대읽기 → Pearson 0.371 vs Spearman 0.985로 갈림(fit은 [0,1]로 제한하고 제외 건수·최대값 기록, ECDF는 전량 유지); 감사 manifest는 frame_id가 데이터셋 간 중복이라 형제 JSON의 `dataset`으로 출처를 확인해 불일치 시 join 거부(가드 없을 때 ph7 10장 분석에 500셋 435행이 섞여 rows=446 재현). 테스트 358 passed(신규 35).
- 2026-07-27: v2 개편 Phase 9A/9B — 전체 unit test 358 passed(failed 0, 78.4s; `test_camera_distance_cap.py`의 100k spec bulk draw 포함) 최종 확인 후, bpy-free dry-run 하네스 `scripts/data_prep/blender/dryrun_v2_proposals.py` 신규(렌더 0, bpy import 0). 기존 `audit_v2_dryrun.py`는 accepted 목표 + LEGACY/LATERAL A/B 구조라 예산 단위가 달라 별도 파일로 만들되 스트림은 Phase 7의 production `iter_proposals`, 통계는 Phase 8의 `ecdf/pearson/spearman`을 재사용. 결정성은 proposal canonical JSON의 SHA-256 스트리밍 해시로 비교. **B1 5,000 proposal 12/12 PASS**(거리>10m 0건 max 9.999785m, NaN/inf 0, 빈 feasible interval 0(draw당 최소 4 bin), out_of_range reject 0, digest 3cd365eec96d1009 일치, acceptance 4439/5000=88.78%, exhaustion 0(1.126≤20), 무관 marginal 최대 0.00063). B1 통과 후 **B2 40,000 proposal 12/12 PASS**(max 9.999910m, out_of_range 0, NaN 0, digest 066daafe45e60357 일치, acceptance 35792/40000=89.48% [Wilson .8918-.8978], starvation 0, 무관 marginal 최대 0.00008, 92s). 핵심 실측: bin0(<10%)이 draw의 68.98%에서만 feasible한데 accepted marginal은 정확히 0.2000 — masking-only sampler라면 0.138로 주저앉을 값을 accept-time quota deficit이 복원(Phase 1 설계 주장 40k 실증); 거리는 projected size에만 반응(log d vs log ratio Pearson -0.9381 / log fx +0.0107 / log W -0.0029)이라 상한이 fx·aspect 커플링을 만들지 않음; 항등식 잔차 max 0.000e+00; reject는 bin4(>60%, 0.38-2.22m)에 집중(accept 0.6554, C1 1355/d_occ_fail 1170/v_below_min 1231)이고 나머지 bin은 0.956-0.995. B3(100k accepted)은 지시대로 미수행. 산출물 reports/v2_revision/dryrun_{5k,40k}_summary.md + checks.json + axis_marginals.csv + proposals.csv + joint_eda.png/pdf(distance x fx x aspect x projected-size 6패널). ⚠️ RGB/mask/조명 미검증 — training-ready 선언 불가.
- 2026-07-27: v2 개편 Phase 9C — 20-frame exact determinism smoke를 fresh headless Blender 프로세스로 2회 실행(seed 7000, `--completion-mode records --n 20 --render-profile diagnostic-exact`, out=`data/pallet/_v2_smoke20_9c_run1|run2`, 각 619s). **결정성 축은 완전 통과**: record 20/20·label 18/18 semantic mismatch 0, RGB 18/18 sha256 바이트 동일, mask 90/90 디코드 픽셀 동일(PNG 바이트는 90/90 상이 — Blender 인코더 비결정성, 기지), realize 실패 위치·사유·수치까지 재현. 감사(`audit_v2_scene_logic.py`) 두 실행 모두 status=PASS(fatal 0, strict decode fail 0, magenta 0, empty M0 0, pixel inclusion 위반 0, ground continuity 18/18, hull IoU median 0.963), 거리 위반 0(actual/target 최대 9.3277m ≤ 10m). 9B 40k dry-run(seed 7000) 첫 20 accepted proposal의 target 거리가 이번 20 record와 20/20 일치 → pure층↔Blender층 plan 스트림 동일 [확인]. **다만 "20 rendered / realize fail 0" 조건은 FAIL(18/20)**: 두 실행 모두 idx 15·18(controlled-occlusion, occluder_side=bottom, f_target 0.446/0.223)에서 `bounded_local_search_exhausted`. 이는 요구 가림률을 못 만든 프레임을 잘못 렌더하지 않고 버리는 설계 경로(`v2_realize.py:2428` + `explicit_requirement_failure`)이고, 손대지 않은 기존 500셋도 435/500 rendered·실패 62건 중 63/65가 controlled-occlusion이라 **Phase 1~8 회귀가 아님**. controlled 슬롯 realize 실패율 42%(side=bottom은 27%로 최약) → records 모드에서 20/20 rendered가 나올 확률 ≈6.6%로, 조건 자체가 `--completion-mode records` 정의와 양립하지 않음(정확히 N장 렌더는 Phase 7 usable 모드 역할). 지시대로 수정하지 않고 blocker 보고, 9D로 넘어가지 않음. 산출물 `reports/v2_revision/smoke20_9c_determinism.json`.
- 2026-07-27: v2 개편 Phase 9D/9E — usable 50-frame quality smoke(`--completion-mode usable --n 50 --render-profile dataset-quality`, seed 7000, out=`data/pallet/_v2_smoke50_9d`) **50/50 배달, 32.1분**(Phase 7 추정 35~70분보다 빠름; proposal 107·render 시도 75·수율 66.7%·배달당 median 13.6s). 지시된 17개 조건 전부 PASS: rgb/label/mask 50/50/250, records_rejected.jsonl 57행(mode_filter 24+solve 8+render 25) 전량 보존, 거리>10m 0(max 9.737m), empty M0 0, strict decode fail 0/300, 픽셀 포함관계 위반 0px, exact collision 0, support/clearance/ground continuity 50/50(probe fail 0/550, min floor edge margin 15.484m), G1~G5 50/50, audit status=PASS(failures 0), overlay 50+sheet 5, source-mask sheet 3페이지, continuous EDA required 13/13 status=ok(구 500셋에서 N/A였던 figure 01·05·10이 실제 곡선 → Phase 1/3 필드 배선 회귀 확인). G5가 final RGB 기준임은 코드 경로+라벨로 [확인](raw≠final 48/50, max Δ5.94)이나 이번 50장은 최소 luma 16.35라 임계 12.0을 가로지르는 프레임이 0이어서 배달셋만으로는 raw/final 구분 불가. **신규 발견 2건**: ①solvePnP exact success는 50/50이지만 그중 f0038·f0049 2건이 미러/뒤집힌 해(reproj 34.9/30.6px, rot err 146°/160°) — 둘 다 visible kp 5 + 저앙각(8.5°/4.6°)이고 노이즈 0인 exact GT에서 발산하므로 EPnP의 평면 퇴화 구성 문제(평가 코드와 일치시키기로 한 solver는 미변경) ②usable 셋은 정의상 전원 all-pass라 continuous EDA figure 10/11/12의 pass-probability 곡선이 퇴화(base rate 1.000, 신뢰 격자점 0/200) → 게이트 튜닝은 records-mode 셋 필요. 9C 예측 재현: controlled-occlusion side 배달 구성이 처방(SIDE_WEIGHTS .30/.30/.25/.15, **균등 아님**) 대비 left 7·right 6·bottom 2·center 0으로, bottom 성공률 17%(2/12)·center는 solve 단계 resample이 side를 매번 재추첨하는 탓에 렌더 시도조차 0.026(1/38). noise tier 실측 clean 26/low 19/medium 5/high 0(chi2 5.58, df=3 → 처방과 불일치 근거 없음; high는 n=50에서 기대 1.5장). 보고서 `reports/v2_revision/quality_smoke50/summary.md`(534행) 작성 — Section 10 6개 질문 답변 + blocker 11건(B1 controlled realize 실패 61%, B2 side 편향, B3 PnP threshold 확정 불가, B4 exact-GT PnP 발산, B5 projected_size_actual 과대추정 12%, B6 tiny 배달 8%, B7 high tier 미검증, B8 GPU 비재현성, B9 usable셋 판별력 부재, B10 f_static 카운터 부재, B11 40k 감사 비용). 500-frame pilot·40k 본렌더·commit/push 없음.
- 2026-07-28: v2 mask output profile — `--mask-profile {full-audit,public}` 신규(기본 full-audit = 기존 500-record 진단 동작 완전 보존). 신규 bpy-free 모듈 `scripts/data_prep/blender/mask_profiles.py`가 stage 목록·경로 레이아웃·홀드아웃 패스·분해를 단일 정의하고, `v2_realize.measure_geometry_and_masks`는 하드코딩 5회 렌더 대신 `MP.holdout_passes(profile, hide_groups)`를 돈다. public은 **M1~M3를 렌더 자체를 안 함**(렌더 후 삭제 아님 — 2프레임 Blender 스모크 로그의 `Saved:` 줄이 프레임당 3개[rgb+2]로 [확인])이고 `mask_amodal/fNNNN.png` + `mask_visible/fNNNN.png` 2장만 남긴다(`mask/` 디렉토리 미생성, m0/m4 중복 저장 없음). label: `mask_profile`·`occlusion_decomposition_available`·`mask_area_amodal` 추가, public에서 f_static/f_cargo/f_context/f_explicit는 **`None`(0.0 아님)**, `f_total`은 `1-visible/amodal` exact — 실측으로 가림 0 프레임의 f_total이 `0.0`(≠None)임을 확인(0/False→None 금지 규칙). 같은 seed 2프레임을 두 프로파일로 렌더해 mask 면적 동일(14304/80813) → 프로파일은 저장 정책만 바꾼다. 감사기는 `--mask-profile auto`(디렉토리로 감지)로 public 셋을 2-mask 기준(`visible ⊆ amodal`)으로 검사해 status=PASS, 위반 시에는 여전히 fatal. compatibility lookup `MP.resolve_frame_mask_path`로 audit_pnp_eligibility·overlay_v2_detailed를 1행씩 배선(레거시 셋 동작 불변). record 스키마(146키 frozen)는 미변경, 기존 데이터셋 삭제·이동 없음. 테스트 387 passed(358→+29). 미배선: analyze_v2_scene_logic·compare_v2_determinism의 `root/"mask"` 하드코딩, usable 모드에서의 public 파일 정리 경로.
- 2026-07-28: canonical overlay 복원 — `gen_trunc_addon.py`의 `# === Detailed Overlay ===` 블록(L577-712)을 신규 bpy-free 모듈 `scripts/data_prep/blender/overlay_archive_trunc_style.py`로 **verbatim 추출**해 archive `trunc_addon_v1_pilot/overlay` 스타일을 정본으로 복원. 엣지 per-world-axis 색 (255,80,80)/(80,220,80)/(80,130,255)·keypoint 9색·off-screen (130,130,130)·r=6/centroid r=7·패널 (6,6,175,240) 줄간격 11·레전드 90x60 at (W-96,H-66)까지 상수 그대로이고, **출력 캔버스 = 입력 RGB 크기**(상단 header·외부 우측 패널·M0/M4 contour·FRONT/REAR 색 전부 제거). `overlay_v2_detailed.py`에 `--style {archive,frontrear-debug}` 추가(**기본 archive -> `<out>/overlay/`**, 어제 만든 FRONT/REAR 넓은 패널은 `overlay_frontrear_debug/`로 격하). v2 어댑터 `archive_metadata()`는 20개 패널 필드를 label/record에서 채우고 없는 값만 `N/A`/`?`로, **0·False는 값으로 그대로 표시**(Trunc는 in-image 코너<8, Occ는 f_total>0, Size는 프레임별 `dimensions_m` — 하드코딩 없음). pose 축은 `pose_transform` 회전+K 투영, z>0일 때만 그림. Pillow 10.1 이후 `load_default()`가 TrueType으로 바뀐 탓에 패널 글꼴이 달라지는 문제를 `load_default_imagefont()`로 고정. 부수적으로 `MASK_NAMES` 5개 하드코딩을 `resolve_mask_names()`(mask profile 감지)로 교체. smoke50 3프레임(f0000/f0003/f0007)을 스크래치패드에 생성해 육안 검증(패널·색·레전드가 archive 원본과 동일, N/A 0건). 테스트 441 passed(387->+54, 기존 테스트 삭제·완화 없음). 데이터셋 재생성/Blender 렌더/commit 없음.
- 2026-07-28: archive-style overlay 재생성 + 정본 대조 검증 — Blender/RGB 재렌더 없이 `_v2_smoke50_9d` 50장 전량을 canonical overlay로 재생성(`overlay_archive_style/` 50 + `contact_sheets_archive_style/` 5, 기존 `eda/`·`eda_phase6/` 미변경). `overlay_v2_detailed.py`에 leaf 폴더명 override `--overlay-dirname`/`--sheet-dirname` 추가(기본값 = 기존 `overlay/`·`contact_sheets` 동작 그대로). `_v2_cleanbase_smoke20_seed7100`은 존재하지 않아 건너뜀. **버그 1건 수정**: Section 2~4의 `_archive_bitmap_font()`가 PIL 고전 6x11 비트맵을 강제했으나 정본은 Pillow>=10.1의 AA TrueType(`load_default()`)으로 그려진 것이 픽셀로 반증됨 — 정본 panel 순백 픽셀 0개(글자 코어 240), 고정 내용인 legend 박스(91x61) 골든 diff가 `load_default()`는 **0px**, 비트맵은 **482px**, 패널 1행만도 442px 차이. `_archive_font()`로 교체 후 전량 재생성하고 골든 테스트 `test_legend_is_pixel_identical_to_the_archive`로 회귀 고정(테스트 3개는 잘못된 가정 교체 — 순백 매칭 -> AA ink 임계 120, 20번째 줄 descender 1px 허용). 검증은 신규 `_verify_archive_style_pixels.py`로 12항목을 픽셀 판정: 완성 오버레이를 같은 keypoint의 참조 레이어(edge 전용/edge+dot)와 비교하고 나중 요소의 덮음·AA convex blend·1px 래스터 편차(정본 JSON 소수 2자리 반올림)만 허용. **판정 기준 자체를 정본 12장이 12/12 통과하는지로 먼저 검증**(초기 기준은 정본도 FAIL시킴 — 13.7m 프레임은 엣지가 dot에 완전히 가려지고, 축 글자 AA가 순수 축색 픽셀을 하나도 안 남김). 최종: archive 12장·신규 12장 **각각 12항목 전부 PASS**(Read로 24장 육안 확인 병행), panel (6,6)/(181,246)=(0,0,0)·legend swatch (255,60,60)/(60,220,60)/(80,130,255)·canvas==RGB 24/24 일치. 산출물 `reports/v2_overlay_fix/archive_reference_vs_new.png`(6쌍, 양쪽 원본 크기)·`visual_verification.md`. 테스트 443 passed(441->+2). commit/push 없음.
- 2026-07-28: 8-frame public-mask + archive-overlay end-to-end 스모크(실제 Blender) — `--completion-mode usable --n 8 --mask-profile public --render-profile dataset-quality --noise-tier clean`, seed 7000, out=`data/pallet/_v2_publicmask_overlay_smoke8`, **299 s / exit 0 / 8장 배달**(proposal 12·render 시도 9·reject 1). 6.3 필수 결과 **15/15 PASS**: rgb/label/mask_amodal/mask_visible 각 8, M1/M2/M3 파일 0, 영구 mask 16, `f_total` 8/8 non-null(0.0~0.4663, 가림 0은 None 아닌 0.0 유지)·`f_static/f_cargo/f_context/f_explicit` 8/8 null·`occlusion_decomposition_available=false` 8/8·`mask_profile="public"` 8/8, visible⊆amodal 8/8(위반 0 px), archive overlay 8장 canvas==RGB 8/8·외부 패널 0·full-width header 0. `mask/` 디렉토리 미생성, 프레임당 `Saved:` 3줄(M1~M3 렌더 자체 없음). 감사기 auto 감지 PASS(frames 8, failures 0, `mask_names=['m0','m4']`). **Section 1이 남긴 미검증 항목(usable reject cleanup on public paths)은 스모크만으로는 검증 불가**였다 — 유일한 render reject가 realize 실패라 record에 `mask_paths`가 없어 cleanup 경로를 타지 않음. 그래서 `--magenta-max-fraction=-1.0`으로 **렌더 성공 후 gate reject를 강제**한 1-frame probe를 스크래치패드에 별도 실행해, `removed_files` 3건(rgb + `mask_amodal/` + `mask_visible/`)·잔재 0·PNG 0으로 public 경로 정리 동작을 [확인]. overlay 8장 Read로 전량 열람 + 픽셀 판정 12항목 8/8, mask 시트로 amodal(가림 포함 전체 실루엣, 포크홀 구멍까지) vs visible(가림 반영) 육안 확인. 판정 스크립트 `_verify_archive_style_pixels.py`의 centroid on-screen 조건이 `<= h-1`이라 y=539.82(H=540)인 f0004를 오판 → archive 원본과 동일한 `<= H`로 수정(정본 12 + 신규 12 재실행해 회귀 없음 확인), `--new-root`/`--new-overlay-dirname`/`--skip-archive` 추가(기본값 = 기존 동작). camera-postprocess를 완전히 끄는 CLI 옵션은 없어 최약 티어 `--noise-tier clean`(blur/noise/jpeg 확률 0)을 사용. 프로덕션 코드 무변경, 테스트 443 passed 유지.
- 2026-07-28: 테스트 커버리지 검증 + 최종 보고서 — 지시가 요구한 필수 unit test 12항목이 어느 테스트 함수에 있는지 전수 대응표를 만들어 확인(전문은 `reports/v2_overlay_fix/final_report.md` 10절). 12항목 모두 커버되고 있었으나 4가지가 약해서 **테스트 12개를 신규 추가**(기존 삭제 0·완화 0). ① 신규 클래스 `TestMatchesTheArchiveSource`(9) — edge/keypoint/panel/legend/축/Area%/캔버스 상수를 테스트 파일 리터럴이 아니라 **`gen_trunc_addon.py` 소스를 정규식+`ast.literal_eval`로 파싱해 꺼낸 값**과 비교하므로 "archive와 exact match"가 진짜 diff가 된다(복사와 리터럴이 함께 틀리는 경우를 잡는다). 여기에 archive의 **inclusive on-screen 조건**(`0 <= x <= W`, Section 6의 f0004 centroid 오판 원인)과 "블록 안에 Image.new/paste/concatenate/hstack/vstack이 하나도 없다(= 캔버스 불변)"도 고정. ② `test_only_the_profile_mask_directories_are_created` — `MP.mask_dirnames`가 어떤 테스트에도 안 걸려 있었고 "public 셋에 빈 `mask/`를 안 남긴다"가 스모크로만 확인돼 있었다. ③ `test_corner_ids_follow_the_label_projected_cuboid_order` — keypoint convention 가드가 v2_realize 소스 텍스트뿐이라 **그리기 쪽이 비어 있었다**: label `projected_cuboid` 인덱스 i가 archive 색 i로 칠해지는지 픽셀로 8/8+centroid 확인. ④ `test_overlay_run_never_rewrites_the_dataset` — overlay는 view여야 하므로 CLI 실행 전후 labels/records/mask/rgb SHA-256 동일 검증. **전체 455 passed(443->+12, failed 0, skip 0, 142.6s)**. 최종 보고서 `reports/v2_overlay_fix/final_report.md` 작성(지시 12항목 순서대로: overlay가 archive가 아니었던 이유=정본이 코드로 존재하지 않았음 / 재사용 범위 L90·L603-611·L616-710 매핑표 / 변경파일 신규7·수정8 / canonical vs debug 11축 비교 / M0~M4 의미와 f_* 정의 / public이 M0·M4만 남기는 이유 / 50장 재생성 12항목 12/12 / 8-frame smoke 15/15 + reject cleanup probe / 비교 이미지 경로 / 테스트 대응표 / 남은 문제 11건 / git diff). 완료 조건 5개 전부 충족(archive형 canonical, public 2장, full-audit만 5장, 500·40k 미실행, commit·push 미실행). 남은 문제: analyze/compare의 `root/"mask"` 하드코딩 미배선, 정본 경로 문서화, **M1이 배경을 안 숨겨 f_static이 배경 가림을 흡수하는 구조**, n=8 수율 일반화 금지(9D 50장 66.7%), 어제 blocker(controlled realize 실패·PnP threshold·EPnP 발산 등) 유효. 프로덕션 코드 변경 0, Blender 미실행, commit/push 없음.
