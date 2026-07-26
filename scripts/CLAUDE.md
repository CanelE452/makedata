# scripts/

팔레트 6D 포즈 추정 파이프라인의 실행 스크립트 모음.

## 디렉토리 구조

```
scripts/
├── data_prep/
│   ├── isaac_sim/              ← Isaac Sim 합성 데이터 생성 (Isaac Sim 내장 Python)
│   │   ├── gen_replicator_data.py   메인 진입점
│   │   ├── sdg_config.py           상수/설정
│   │   ├── sdg_math.py             좌표 변환, 카메라 행렬
│   │   ├── sdg_annotation.py       NDDS JSON, visibility
│   │   ├── sdg_usd_xform.py        USD xformOp 제어
│   │   ├── sdg_scene.py            씬 구성 (warehouse, props, 조명)
│   │   ├── sdg_distractors.py      적재물/디스트랙터 배치
│   │   ├── debug_pallet_orientation.py
│   │   ├── list_isaac_assets.py
│   │   ├── generate_all.sh         배치 생성
│   │   └── run_iter_verification.sh
│   ├── evaluate_on_val.py      ← PyTorch (conda: pallet-pose)
│   ├── visualize_annotations.py
│   ├── visualize_inference.py
│   ├── visualize_pretrain.py
│   ├── merge_and_validate.py
│   ├── verify_keypoints.py
│   └── _check_axis.py
├── self_training/              ← PyTorch Self-Training (conda: pallet-pose)
│   ├── self_train.py
│   ├── geometric_filter.py
│   ├── pnp_solver.py
│   ├── augmentations.py
│   └── metrics.py
├── dope/                       ← Docker 실시간 추론
│   └── run_dope_live.py
├── train_dope.sh               ← DOPE 학습 (conda: pallet-pose)
├── launch_tensorboard.py
└── launch_v2.ps1               ← Docker 런처 (PowerShell)
```

## 환경 구분

| 환경 | 디렉토리/파일 | 실행 방법 |
|------|--------------|-----------|
| **Isaac Sim** | `data_prep/isaac_sim/` | Isaac Sim 내장 Python으로 standalone 실행 |
| **PyTorch** | `data_prep/*.py`, `self_training/`, `train_dope.sh` | `conda activate pallet-pose` |
| **Docker** | `dope/`, `launch_v2.ps1` | `docker compose up` |

## 설정 파일 참조

- 모든 하이퍼파라미터: `config/default.yaml`
- Self-Training 전용: `config/stage3_selftrain.yaml`
