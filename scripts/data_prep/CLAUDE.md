# scripts/data_prep/

합성 데이터 생성 및 검증 파이프라인. Step 1에 해당.

## Isaac Sim (`isaac_sim/`)

Isaac Sim 내장 Python으로만 실행. conda 환경 아님.

| 모듈 | 역할 |
|------|------|
| `gen_replicator_data.py` | 메인 진입점 (SimulationApp, generate_data, main) |
| `sdg_config.py` | 모든 상수/설정값 (경로, 카메라, 색상, 에셋) |
| `sdg_math.py` | 수학 헬퍼 (euler, quat, bbox, camera matrix) |
| `sdg_annotation.py` | NDDS JSON 작성, visibility 계산 |
| `sdg_usd_xform.py` | USD xformOp 제어, prim path resolve |
| `sdg_scene.py` | 씬 구성 (warehouse, props, 조명, 텍스처) |
| `sdg_distractors.py` | 디스트랙터/적재물 배치, 카메라 포즈 |
| `generate_all.sh` | 배치 생성 (200프레임/배치, Isaac Sim 재시작) |
| `run_iter_verification.sh` | iter 단위 배치 검증 |
| `debug_pallet_orientation.py` | USD 모델별 orientation 진단 렌더링 |
| `list_isaac_assets.py` | Isaac Sim Nucleus/S3 에셋 경로 탐색 |

## PyTorch 검증/시각화 (루트)

conda env `pallet-pose`에서 실행.

| 파일 | 설명 | 사용법 |
|------|------|--------|
| `evaluate_on_val.py` | Val set 평가 (PCK@3/5/10px, PnP reproj, ADD, 5cm-5°) | `python scripts/data_prep/evaluate_on_val.py --weights <path> --val_dir <path>` |
| `visualize_annotations.py` | 9-point cuboid keypoint + pose axis overlay 렌더링 | |
| `visualize_inference.py` | DOPE 추론 시각화 (belief + keypoint + cuboid) | `--weights`, `--val_dir`, `--real_dir` |
| `visualize_pretrain.py` | Pretrain 결과 종합 시각화 | |
| `merge_and_validate.py` | 배치별 출력 병합 + visibility 필터링 | |
| `verify_keypoints.py` | Keypoint 기하학 자동 검증 | |
| `_check_axis.py` | 단일 JSON의 edge 길이 + 회전행렬 검증 | |

## 주의사항

- `isaac_sim/` 내 스크립트는 Isaac Sim standalone으로만 실행 (conda 환경 아님)
- Isaac Sim ~2분/프레임, 200프레임마다 재시작 필수 (메모리 누수)
- `ORIENTATION_OVERRIDES` 절대 수정 금지 (검증 완료된 값)
- 어려운 케이스(낮은 대비, 유사 색상)는 의도된 것 — 제거하지 말 것
