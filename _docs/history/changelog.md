# 작업 기록

## 개요

팔레트 6D 포즈 추정 프로젝트의 주요 작업 이력. 최신순 정렬.

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
