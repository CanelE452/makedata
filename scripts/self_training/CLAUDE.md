# scripts/self_training/

FixMatch 기반 준지도 Self-Training 파이프라인. Step 2-3에 해당.
설정: `config/stage3_selftrain.yaml`

## 스크립트

| 파일 | 역할 | 타입 |
|------|------|------|
| `self_train.py` | 메인 Self-Training 루프 (pseudo-label 생성 → 필터링 → 학습 반복) | 실행 |
| `geometric_filter.py` | Pseudo-label 기하학적 검증 (reproj error, cuboid 기하, 물리 크기) | 모듈 |
| `pnp_solver.py` | EPnP + RANSAC로 2D keypoint → 6D pose 복원 | 모듈 |
| `augmentations.py` | FixMatch weak/strong augmentation (photometric only, 좌표 불변) | 모듈 |
| `metrics.py` | 6D 포즈 평가 메트릭 (ADD, 5cm-5°, reproj error) | 모듈 |

## 파이프라인 흐름

```
Real image → Weak aug → DOPE inference → PnP solver → Geometric filter
                                                            ↓
                                                    Pseudo-label (통과)
                                                            ↓
                            Synthetic (GT) + Real (pseudo) → Mixed training
                                                            ↓
                                                    다음 라운드 반복
```

## 사용법

```bash
python scripts/self_training/self_train.py --config config/stage3_selftrain.yaml
```

## Geometric Filter 3단계

1. **Reprojection error** — PnP 결과를 재투영하여 원본 keypoint와 비교 (`tau_reproj`)
2. **Cuboid geometry** — 대변 길이 비율, 인접변 각도 검증 (`tau_ratio`, `tau_angle`)
3. **Physical size** — 추정된 팔레트 실제 크기가 합리적 범위인지 (`tau_size`)

임계값은 `config/stage3_selftrain.yaml`의 `geometric_filter` 섹션에서 관리.
