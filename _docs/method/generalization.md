# 7. 다양한 형태의 팔레트 일반화 전략

## 7.1 핵심 관찰

플라스틱 팔레트는 내부 슬롯 패턴, 다리 형태, 색상은 종류마다 다르지만,
**외곽 형상은 직육면체로 거의 동일하다.** 이것이 일반화가 가능한 근거이다.

## 7.2 일반화 4단계

```
전략 1: 다종 3D 모델 혼합 학습 (Step 1)
        → 공통 구조(직육면체 외곽)에 집중하도록 유도

전략 2: 극단적 재질/텍스처 Domain Randomization (Step 1)
        → 내부 디테일 의존성 제거, edge/corner 의존성 강화

전략 3: Self-Training (Step 2~3) ← 핵심
        → synthetic에서 학습 못한 다양한 형태에 자동 적응
        → Geometric filter가 형태 무관하게 "직육면체인가?" 검증

전략 4: 반복적 개선 (NVIDIA 공식 프로세스)
        → 실패 사례 분석 → 해당 변형 합성 데이터 추가 → 반복
```

## 7.3 실험 검증

```
Test Set:
  (a) Seen pallet:   학습에 사용한 3D 모델과 동일한 종류의 실제 팔레트
  (b) Unseen pallet: 학습에 사용하지 않은 종류의 플라스틱 팔레트

→ Unseen에서의 개선폭이 크면
  "self-training이 일반화 성능을 향상시킨다"는 강력한 주장 가능
```

---

# 8. 데이터셋 구성

> 합성 데이터 생성/검증/병합 파이프라인 → [data_pipeline.md](../preprocessing/data_pipeline.md) 참조.

| 데이터셋           | 출처                  | 라벨    | 용도                | 목표 수량      |
| ------------------ | --------------------- | ------- | ------------------- | -------------- |
| Synthetic Train    | Isaac Sim             | 자동 GT | Step 1 학습         | 5,000~15,000장 |
| Synthetic Test     | Isaac Sim (별도 시드) | 자동 GT | upper bound         | 500~1,000장    |
| Real Unlabeled     | 직접 촬영             | 없음    | Step 2~3 self-train | 500~1,000장    |
| Real Test — Seen   | 직접 촬영 + AprilTag  | GT 있음 | Seen 평가           | 50~100장       |
| Real Test — Unseen | 직접 촬영 + AprilTag  | GT 있음 | Unseen 일반화 평가  | 50~100장       |
