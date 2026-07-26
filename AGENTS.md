# Pallet 6D Pose — Geometry-aware Self-Training

팔레트 6D 포즈 추정을 위한 기하학적 제약 기반 준지도 DA 프레임워크.
Python + PyTorch + Isaac Sim + DOPE.

## 연구 가이드

최신 연구 설계: `docs/` (README.md에서 목차 확인)
도메인 서베이: `docs/survey-6d-pose-estimation.md` (방법론/학습전략/메트릭 비교)

## 문서 관리

- 모든 프로젝트 문서는 `_docs/` 하위에 저장 — 디렉토리 구조와 각 폴더 역할은 `_docs/README.md` 참조
- 작업 완료 시 `_docs/history/YYYY-MM-DD.md`에 그날 수행한 내용을 상세히 기록하고, `_docs/history/changelog.md`에 한 줄 요약 추가
- history 파일은 **새 LLM 세션이 이 파일만 읽고도 동일하게 이어서 작업할 수 있을 만큼** 구체적으로 작성: 무엇을 했는지, 어떤 접근을 시도했는지, 어떤 것이 성공/실패했는지, 미해결 이슈와 다음 TODO까지 포함
- 핵심 코드 위치(파일:라인, 함수명)를 명시하여 코드 탐색 시간을 최소화

## Commands

### Step 1: 합성 데이터 생성 + DOPE Pretrain
- 합성 데이터 생성 (단일): Isaac Sim에서 `scripts/data_prep/isaac_sim/gen_replicator_data.py` 실행
- 합성 데이터 생성 (배치): `bash scripts/data_prep/isaac_sim/generate_all.sh` (200프레임/배치, train 10 + val 3)
- DOPE pretrain: `bash scripts/train_dope.sh` (epochs=60, batch=4, lr=1e-4, imagesize=448, sigma=4.0, workers=4)

### Step 2-3: Self-Training + 평가
- Self-training: `python scripts/self_training/self_train.py` (설정: `config/stage3_selftrain.yaml`)
- 평가: `python scripts/data_prep/evaluate_on_val.py --weights <path> --val_dir <path>` (PCK@3/5/10px + PnP 성공률 + Reproj error)

### 유틸리티
- Annotation 시각화: `python scripts/data_prep/visualize_annotations.py`
- 데이터 검증: `python scripts/data_prep/merge_and_validate.py`, `verify_keypoints.py`
- 실시간 추론: `docker compose up` → RealSense D435i + DOPE live

## Architecture

- **Pose 표현**: Keypoint-based (DOPE) — 팔레트는 비대칭 직육면체로 keypoint 방식에 적합
- 3단계 파이프라인: Step 1 (합성데이터+DOPE학습) → Step 2 (Geo Filter+Pseudo-label) → Step 3 (Finetuning) → 반복
- DOPE 모델: `Deep_Object_Pose/` 서브모듈 (VGG-19 backbone, 9 belief maps + 16 affinity fields)
- **PnP**: EPnP + RANSAC (`scripts/self_training/pnp_solver.py`) — keypoint → 6D 포즈 복원
- 합성 데이터: Isaac Sim 4.5.0 + Omniverse Replicator, NDDS 포맷 JSON annotation
- USD 모델: `data/pallet/models_usd/scene*.usd` (4종 팔레트)
- Geometric Filter: 3단계 (A: Augmentation Consistency, B: 변 길이 일관성, C: 규격 비율)
- Keypoint convention: Y=UP, 8 cuboid corners + centroid (memory 참조)
- **평가**: PCK@3/5/10px + PnP Reproj (val) / ADD, 5cm5° (real test, camera extrinsic 필요) — `scripts/data_prep/evaluate_on_val.py`
- 실시간 추론: `scripts/dope/run_dope_live.py` + RealSense D435i (Docker container)
- 팔레트 규격: KS T-11형 1100×1100×150mm (config에서 관리)

## Code Style

- conda env: `pallet-pose`
- Isaac Sim 스크립트는 standalone 실행 (Isaac Sim 내장 Python)
- DOPE 데이터 로더: CleanVisiiDopeLoader (`{i:06d}.png` + `{i:06d}.json` 쌍)
- 하이퍼파라미터는 `config/stage3_selftrain.yaml` 또는 argparse로 관리 (코드 내 하드코딩 대신)
- Docker: `docker-compose.yml` (실시간 추론), `.devcontainer/` (Codex 개발환경)

## Blender 씬 작업 규칙

- 변경 작업 전 .blend 파일 저장 먼저 실행
- Blender MCP 코드 실행 후 반드시 결과를 검증 (스크린샷 + 좌표/크기 출력으로 확인), 문제 발견 시 사용자에게 물어보지 않고 즉시 수정
  - 고아 오브젝트(부모 없는 Object_* 등) 자동 삭제
  - 머티리얼 미적용(검은색) 시 자동 재설정
  - 스케일/회전 이상(팔레트가 세로, 거대 등) 시 자동 수정
  - 중복 임포트(Pallet_0.001 등) 자동 정리
  - 검증용 보조 오브젝트(wireframe, 키포인트 구체, 축 화살표, 텍스트 라벨)는 검증 완료 후 자동 삭제
  - 배경 glTF 임포트 시 우리 팔레트(Pallet_0~3)와 혼동되는 다른 팔레트/목재팔레트(WoodenPalet 등) 자동 삭제
- 오브젝트 삭제 시 구체적 목록을 사용자에게 보여주고 승인 후 실행
- 씬 구성 변경 후 memory(`project_blender_scene.md`)에 현재 상태 기록
- Blender MCP의 undo는 불안정 — 저장이 유일한 안전장치

## Gotchas

- Isaac Sim DLL 충돌: `CUDA_MODULE_LOADING=LAZY` + `PYTHONUNBUFFERED=1` 설정 필요
- Isaac Sim ~2분/프레임, 200프레임마다 재시작 (메모리 누수)
- Replicator `rep.distribution.choice()`는 머티리얼 생성 시 1회만 평가됨 → USD API로 직접 변경
- 팔레트 기울기 없이 바닥 수평 고정 (tilt=0)
- 어려운 케이스(낮은 대비, 유사 색상)는 유지 — 모델 로버스트니스에 필수
- Belief map sigma=4.0 유지 (sigma<1은 gradient vanishing 발생, `docs/step1_synthetic_data.md` 3.6절 참조)
- 합성 데이터 생성 시 실제 창고/공장 사진처럼 보여야 함:
  - 물체는 바닥/표면 위에 접지 (공중에 떠있으면 안 됨)
  - primitive 도형(빈 직사각형 등) 대신 실제 에셋(glTF/USD) 사용, 텍스처 필수
  - 팔레트 머티리얼은 실제 목재 질감 + 어두운 톤 (밝은 회색/흰색 금지, 실제 창고 조명 기준)
  - 전체 씬 색조는 실제 환경 참고 — 어둡고 자연스러운 조명, 과도한 밝기 금지
- 3D/렌더링 문제는 3D expert agent에게 먼저 상담 후 수정
- 장시간 작업(데이터 생성, 학습 등) 실행 중에는 주기적으로 로그/프로세스를 확인하여 정상 진행 여부를 모니터링한다
- 렌더링/합성 데이터 생성 후 "완료"를 선언하기 전에 반드시 이미지를 직접 로드하여 다음을 검증한다:
  - 물체가 공중에 떠있지 않은지 (모든 오브젝트 바닥/표면 접지 확인)
  - 물체가 다른 물체를 관통/겹치지 않는지 — 썸네일 크기의 이미지로는 겹침을 신뢰성 있게 판단할 수 없다. "겹침 없음"이라고 확신하려면 Blender ray casting 또는 BVH mesh intersection 등 코드 기반 검증 결과를 근거로 제시한다. 눈으로만 보고 "없다"고 단정하지 않는다
  - overlay annotation이 정상 생성되었는지 (keypoint 좌표가 팔레트 위에 올바르게 표시되는지)
  - 검증 없이 "잘 됐다"고 보고하지 않는다 — 로그의 vis 수치만 보고 판단하지 않고 실제 이미지를 열어 확인한다
- 전수 검증 시 프레임별 테이블을 작성하여 사용자 요구사항 충족 여부를 명시한다:
  - 모든 프레임의 overlay 이미지를 개별 로드하여 확인
  - 각 프레임마다 (팔레트 가시성, 접지, 겹침, overlay 정확도, 판정) 기록
  - JSON에서 팔레트 종류 분포, visibility 수치도 함께 집계
  - 사용자가 요청한 구체적 항목(카메라 뷰, 배경 변화, 디스트랙터 위치 등)의 충족 여부를 판정에 반영

## Self-Verification

- [ ] 연구 설계 변경 시 `docs/`의 해당 문서도 함께 업데이트했는가?
- [ ] Isaac Sim 스크립트 수정 시 ORIENTATION_OVERRIDES 건드리지 않았는가?
- [ ] 새 스크립트 추가 시 재현성을 위한 config/argparse 지원이 있는가?
- [ ] Geometric Filter 임계값 변경 시 `config/stage3_selftrain.yaml`에 반영했는가?
- [ ] Docker 관련 변경 시 `docker-compose.yml`과 Dockerfile 일관성 유지했는가?
- [ ] 학습 설정(sigma, batch, lr) 변경 시 `scripts/train_dope.sh`와 `docs/step1_synthetic_data.md` 3.6절 동기화했는가?
- [ ] 생성된 이미지/overlay 확인 시 각 프레임을 개별 로드하여 변경 사항(적재물, 카메라 높이, 배경 등)이 실제 반영되었는지 눈으로 검증했는가? 로그만 보고 판단하지 않는다.
- [ ] 3D 오브젝트(메시, 마커, GT) 변환 시, 연관된 모든 오브젝트(키포인트, 축 화살표, 바운딩박스)에도 동일 변환을 적용하고, 적용 후 스크린샷으로 시각적 검증까지 완료했는가?
- [ ] 합성 데이터 렌더링 결과가 현실적인가? (물체 접지, 실제 에셋 사용, 어두운 톤, 팔레트 목재 질감 확인)
- [ ] 렌더링된 이미지를 직접 열어 물체 부유/관통/겹침이 없는지 확인했는가? (로그 수치만 보고 통과시키지 않는다)
- [ ] overlay annotation을 생성하고 keypoint 위치가 팔레트에 정확히 대응하는지 시각적으로 검증했는가?
