# 연구 가이드 — Pallet 6D Pose Geometry-aware Self-Training

> **논문 제목:** 파렛트 6D 포즈 추정을 위한 기하학적 제약 기반 준지도 도메인 적응
> **핵심 키워드:** 6D pose estimation, geometry-aware self-training, synthetic data, geometric filter, unsupervised domain adaptation
> **작성일:** 2026-03-25 (v5)
> **작성자:** 민재
> **중요** 이거는 논문과 github에 코드를 올려서 다른사람들도 테스트하거나 실험할수 있도록 재현성이 있어야됨 그래서 파일 구조와 정리가 중요

---

## 문서 구조

### 전처리 (`preprocessing/`)

| 파일 | 내용 |
|------|------|
| [keypoint_definition.md](preprocessing/keypoint_definition.md) | 키포인트 ID 매핑, 3D cuboid convention (Y=UP), 팔레트 규격 |
| [data_pipeline.md](preprocessing/data_pipeline.md) | 합성 데이터 생성/검증/병합 워크플로우 |

### 모델 아키텍처 (`method/`)

| 파일 | 내용 |
|------|------|
| [overview.md](method/overview.md) | 연구 개요, 문제 정의, 제안 해법, 전체 파이프라인 |
| [step1_synthetic_data.md](method/step1_synthetic_data.md) | Step 1: Isaac Sim 합성 데이터 생성 + DOPE 학습 |
| [step2_geometric_filter.md](method/step2_geometric_filter.md) | Step 2: 3단계 Geometric Filter + Pseudo-label 생성 |
| [step3_finetuning.md](method/step3_finetuning.md) | Step 3: Finetuning + 반복적 Self-Training 루프 |
| [generalization.md](method/generalization.md) | 다양한 팔레트 일반화 전략 + 데이터셋 구성 |
| [formulation.md](method/formulation.md) | 수식 정의 + 평가 메트릭 (ADD, Reproj, 5cm5°) |
| [implementation.md](method/implementation.md) | 구현 세부사항, Contribution, 참고문헌 |

### 실험 (`experiments/`)

| 파일 | 내용 |
|------|------|
| [experiments.md](experiments/experiments.md) | 실험 설계 (비교 테이블, Ablation, 수렴 분석) |

### 서베이 (`survey/`)

| 파일 | 내용 |
|------|------|
| [survey-6d-pose-estimation.md](survey/survey-6d-pose-estimation.md) | 6D Pose Estimation 분야 서베이 (방법론/학습 전략/메트릭 비교) |

### 작업 기록 (`history/`)

| 파일 | 내용 |
|------|------|
| [changelog.md](history/changelog.md) | 과거 작업 이력 (렌더링 개선, 학습, 트러블슈팅) |

---

## 변경 이력

| 날짜       | 버전 | 변경 내용 |
| ---------- | ---- | --------- |
| 2026-03-10 | v1   | 초안 작성 |
| 2026-03-10 | v2   | 팔레트 일반화 전략, NVIDIA 워크플로우 기반 Stage 1 보강 |
| 2026-03-10 | v3   | 실전 렌더링 가이드, 품질 체크리스트 추가 |
| 2026-03-13 | v3.2 | Stage 1 코드 기준 동기화, DR 상세 파라미터 |
| 2026-03-19 | v4   | **전면 구조 변경:** FixMatch 제거, 3-Step Geometry-aware Self-Training으로 전환. 3단계 Geo Filter 신규 설계. 수식 정의 추가. |
| 2026-03-25 | v5   | **문서 구조 재편:** preprocessing/method/experiments/survey/history 하위 폴더 분리. 키포인트 정의 복원. 합성 데이터 파이프라인 문서 추가. 작업 이력 정리. |
