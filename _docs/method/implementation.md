# 12. 구현 세부사항

## 12.1 코드 구조

```
FoundationPose/
├── config/
│   └── self_training.yaml          # Self-training 설정
├── data/pallet/
│   ├── models_usd/                 # USD 팔레트 모델
│   ├── training_data/              # 합성 데이터
│   └── isaac_assets/               # Isaac Sim 에셋
├── scripts/
│   ├── data_prep/
│   │   ├── gen_replicator_data.py  # Step 1: 합성 데이터 생성
│   │   └── visualize_annotations.py
│   ├── self_training/
│   │   ├── geo_filter.py           # Step 2: 3단계 기하학적 필터
│   │   ├── pseudo_label.py         # Step 2: pseudo-label 생성
│   │   ├── finetune.py             # Step 3: finetuning
│   │   ├── self_train_loop.py      # Step 2~3 반복 루프
│   │   └── augmentations.py        # Strong/Weak augmentation
│   ├── evaluate/
│   │   ├── compute_add.py          # ADD metric
│   │   └── evaluate_real.py        # Real test set 평가
│   └── train_dope.sh               # Step 1: DOPE 학습
├── Deep_Object_Pose/               # DOPE 서브모듈
├── weights/                        # 학습된 모델 가중치
└── _docs/                           # 문서
```

## 12.2 핵심 의존성

```
# Isaac Sim 환경
Isaac Sim 4.5.0, python >= 3.10, numpy, Pillow

# DOPE 학습/평가
python >= 3.8, pytorch >= 1.12, opencv-python >= 4.5

# Self-Training
위 + torchvision, scipy

# Real Data GT
apriltag (AprilTag 기반 GT 생성용)
```

---

# 13. 논문 Contribution 정리

## 13.1 Contribution Statement

> **C1:** 플라스틱 팔레트 6D 포즈 추정을 위한 Isaac Sim 기반 합성 데이터 생성 파이프라인을 설계하고, 다종 3D 모델 혼합 및 재질 무작위화를 통한 도메인 무작위화 전략을 제안한다.

> **C2:** Keypoint regression task에서 pseudo-label의 신뢰도를 검증하기 위한 3단계 기하학적 필터를 제안한다. Augmentation consistency(일반적), 변 길이 일관성(직육면체 검증), 파렛트 규격 비율(domain-specific)의 3단계로 구성되어, 기존 confidence 기반 필터 대비 task-specific한 검증이 가능하다.

> **C3:** 합성 데이터 사전 학습과 geometry-aware self-training의 결합을 통해, 실제 환경의 labeled 데이터 없이도 효과적인 domain adaptation이 가능함을 실험적으로 입증하고, 학습에 사용하지 않은 형태의 팔레트에 대한 일반화 성능을 검증한다.

## 13.2 논문 프레이밍

```
❌ 엔지니어링 리포트식:
"Isaac Sim으로 데이터를 만들고 DOPE로 학습하고
 self-training으로 fine-tune했더니 성능이 올랐다"

✅ 학술 논문식:
"Keypoint regression task에서 semi-supervised self-training의
 pseudo-label 신뢰도를 task-specific geometric constraint로
 검증하는 방법을 제안한다. 3단계 기하학적 필터 — augmentation
 consistency, 직육면체 변 길이 일관성, 파렛트 규격 비율 검증 —
 를 통해 기존 confidence 기반 필터 대비 우수한 pseudo-label 품질을
 확보하고, 학습에 사용하지 않은 형태의 산업용 팔레트에 대해서도
 일반화된 6D 포즈 추정이 가능함을 실험적으로 입증한다."
```

## 13.3 Related Work 위치

```
관련 연구 분류:
├── 6D Pose Estimation: DOPE, PVNet, BB8, GDR-Net
├── Synthetic-to-Real DA: Domain Randomization, CUT, CycleGAN
├── Self-Training for Pose: UDA-COPE, Animal Pose UDA, PseudoFlow
├── Geometric Consistency: CC-SSL, 3DUDA
└── Self-supervised 6DoF: Self6D, RKHSPose, TexPose
```

---

# 14. 참고 문헌 및 리소스

## 14.1 핵심 논문

1. **DOPE:** Tremblay et al., "Deep Object Pose Estimation," CoRL 2018
2. **UDA-COPE:** Lee et al., "Unsupervised Domain Adaptation for Category-level Object Pose Estimation," CVPR 2022
3. **3DUDA:** Kaushik et al., "Source-Free and Image-Only UDA for Category Level Object Pose Estimation," ICLR 2024
4. **Animal Pose UDA:** Li & Lee, "From Synthetic to Real: UDA for Animal Pose Estimation," CVPR 2021
5. **RKHSPose:** Wu & Greenspan, "Pseudo-keypoint RKHS Learning for Self-supervised 6DoF Pose Estimation," ECCV 2024
6. **PseudoFlow:** Hai et al., "Pseudo Flow Consistency for Self-Supervised 6D Object Pose Estimation," ICCV 2023
7. **CC-SSL:** Mu et al., "Learning from Synthetic Animals," CVPR 2020

## 14.2 NVIDIA 공식 자료

- **팔레트 감지 모델:** https://developer.nvidia.com/ko-kr/blog/developing-a-pallet-detection-model-using-openusd-and-synthetic-data/
- **SDG Training Workflow:** https://github.com/NVIDIA-AI-IOT/synthetic_data_generation_training_workflow
- **Isaac Sim 문서:** https://docs.omniverse.nvidia.com/isaacsim/
