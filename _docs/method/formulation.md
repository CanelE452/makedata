# 9. 수식 정의

> 키포인트 ID 매핑 및 3D 좌표 convention → [keypoint_definition.md](../preprocessing/keypoint_definition.md) 참조.

## 9.1 기호 정의 (Notation)

| 기호 | 정의 |
| ---- | ---- |
| x | 입력 이미지 |
| f_θ | DOPE 모델 (파라미터 θ) |
| f_θ(x) | 모델이 예측한 belief map → peak extraction → 8개 keypoint |
| p̂ᵢ = (ûᵢ, v̂ᵢ) | 예측된 i번째 keypoint 2D 좌표 (i = 1,...,8) |
| pᵢ = (uᵢ, vᵢ) | GT i번째 keypoint 2D 좌표 |
| D_s = {(xⱼˢ, yⱼˢ)} | synthetic labeled dataset |
| D_r = {xⱼʳ} | real unlabeled dataset |
| D̃_r = {(xⱼʳ, ỹⱼʳ)} | geo filter 통과한 pseudo-labeled real dataset |
| K | 카메라 내부 파라미터 행렬 |
| P = {Pᵢ ∈ R³} | 파렛트 3D 모델의 8개 꼭짓점 좌표 |

## 9.2 Loss 정의

**Keypoint Loss (단일 이미지):**

```
                    8
   L_pose(x, y) = Σ ‖ p̂ᵢ - pᵢ ‖²
                   i=1
```

**Synthetic Loss:**

```
                        1
   L_pose_syn = ──── Σ  L_pose(xⱼˢ, yⱼˢ)
                |D_s| j
```

**Real Loss (pseudo-label):**

```
                          1
   L_pose_real = ────── Σ  L_pose(xⱼʳ, ỹⱼʳ)
                 |D̃_r|  j
```

**Total Loss:**

```
   L = L_pose_syn + α · L_pose_real

   (α는 pseudo-label 가중치, 기본값 1.0)
```

## 9.3 Geometric Filter 조건

**D̃_r에 포함되려면 아래 3조건을 모두 만족:**

```
[A] Augmentation Consistency:
    ‖ flip(f_θ(xⱼʳ)) - f_θ(flip(xⱼʳ)) ‖ < τ_a

[B] 변 길이 일관성:
    평행한 변 쌍 (eₖ₁, eₖ₂, eₖ₃, eₖ₄)에 대해
    CV(eₖ₁, eₖ₂, eₖ₃, eₖ₄) < τ_b    ∀ 3방향

[C] 파렛트 규격 비율:
    PnP(p̂, P, K) → (R, t)
    |width/depth - expected_wh| / expected_wh < τ_c
    |height/width - expected_hw| / expected_hw < τ_c
```

---

# 10. 평가 메트릭

## 10.1 ADD (Average Distance of Model Points)

```python
def compute_ADD(R_gt, t_gt, R_pred, t_pred, model_points):
    transformed_gt = (R_gt @ model_points.T).T + t_gt
    transformed_pred = (R_pred @ model_points.T).T + t_pred
    add = np.mean(np.linalg.norm(transformed_gt - transformed_pred, axis=1))
    diameter = compute_diameter(model_points)
    return add, add < 0.1 * diameter  # ADD < 10% diameter → 성공
```

## 10.2 Reprojection Error

```python
def compute_reproj_error(kp_gt_2d, kp_pred_2d):
    return np.mean(np.linalg.norm(kp_gt_2d - kp_pred_2d, axis=1))
```

## 10.3 5cm 5° Metric

```python
def compute_5cm_5deg(R_gt, t_gt, R_pred, t_pred):
    trans_error = np.linalg.norm(t_gt - t_pred) * 100  # cm
    R_diff = R_gt @ R_pred.T
    angle_error = np.degrees(np.arccos(np.clip((np.trace(R_diff)-1)/2, -1, 1)))
    return (trans_error < 5.0) and (angle_error < 5.0)
```
