# Step 2: Real 이미지 예측 → Geo Filter → Pseudo-label

## 4.1 개요

Step 1에서 학습된 DOPE 모델로 real unlabeled 이미지에 대해 inference를 수행하고, 3단계 기하학적 필터를 통과한 예측만 pseudo-label로 채택한다.

> 키포인트 ID 매핑 (0-7), 변(Edge) 정의, 팔레트 규격 → [keypoint_definition.md](../preprocessing/keypoint_definition.md) 참조.

## 4.2 Inference

```python
model.eval()
with torch.no_grad():
    belief_maps = model(real_image)          # (9, 50, 50)
    keypoints_2d = extract_peaks(belief_maps) # (9, 2) — 각 belief map의 peak
```

## 4.3 Geometric Filter — 3단계

### 필터 A: Augmentation Consistency

원본 이미지와 flip된 이미지에 대한 예측이 대칭적으로 일관적인지 검증한다.

```python
def filter_A_augmentation_consistency(model, image, tau_a=5.0):
    """
    원본 예측과 flip 예측이 대칭적으로 일관적인가?

    원리: 정확한 모델이라면 이미지를 flip해도
          keypoint 예측이 대칭적으로 동일해야 함.
          틀린 예측은 flip 시 비일관적인 결과를 냄.

    참고: CC-SSL (Mu et al., 2020), Animal Pose UDA (Li & Lee, 2021)
    """
    # 원본 예측
    kp_original = extract_peaks(model(image))             # (9, 2)

    # 좌우 flip 예측
    image_flipped = torch.flip(image, dims=[-1])
    kp_flipped = extract_peaks(model(image_flipped))      # (9, 2)

    # flip된 예측을 다시 원래 좌표계로 변환
    W = image.shape[-1]
    kp_flipped_back = kp_flipped.copy()
    kp_flipped_back[:, 0] = W - kp_flipped[:, 0]         # x좌표 반전

    # 대칭 keypoint 매핑 (좌↔우 대응)
    # 파렛트: 0↔1, 3↔2, 4↔5, 7↔6 (좌우 대칭 쌍)
    symmetric_pairs = [(0,1), (3,2), (4,5), (7,6)]
    kp_flipped_remapped = kp_flipped_back.copy()
    for (a, b) in symmetric_pairs:
        kp_flipped_remapped[a] = kp_flipped_back[b]
        kp_flipped_remapped[b] = kp_flipped_back[a]

    # 일관성 계산
    consistency_error = np.mean(
        np.linalg.norm(kp_original[:8] - kp_flipped_remapped[:8], axis=1)
    )

    return consistency_error < tau_a
```

### 필터 B: 변 길이 일관성 (직육면체 검증)

예측된 8개 keypoint가 직육면체의 기하학적 제약을 만족하는지 2D에서 직접 검증한다.

```python
def filter_B_edge_consistency(keypoints_2d, tau_b=0.3):
    """
    평행한 변 4쌍의 길이가 각각 비슷한가?

    직육면체에는 3방향(가로/세로/높이) × 4개 = 12개 변이 있고,
    같은 방향의 변 4개는 3D에서 길이가 동일.
    2D 투영에서는 perspective 때문에 정확히 같지는 않지만,
    변동계수(CV)가 낮아야 함.

    PnP를 거치지 않으므로 "PnP가 fitting해버리는 문제"를 우회함.
    """
    kp = keypoints_2d[:8]  # (8, 2)

    # 변 정의 (꼭짓점 인덱스 쌍)
    # 가로 변 4개
    width_edges = [(0,1), (3,2), (4,5), (7,6)]
    # 세로 변 4개
    depth_edges = [(0,3), (1,2), (4,7), (5,6)]
    # 높이 변 4개
    height_edges = [(0,4), (1,5), (2,6), (3,7)]

    def edge_lengths(edges):
        return [np.linalg.norm(kp[a] - kp[b]) for (a, b) in edges]

    def coefficient_of_variation(lengths):
        lengths = np.array(lengths)
        if np.mean(lengths) < 1e-6:
            return float('inf')
        return np.std(lengths) / np.mean(lengths)

    cv_width  = coefficient_of_variation(edge_lengths(width_edges))
    cv_depth  = coefficient_of_variation(edge_lengths(depth_edges))
    cv_height = coefficient_of_variation(edge_lengths(height_edges))

    return cv_width < tau_b and cv_depth < tau_b and cv_height < tau_b
```

### 필터 C: 파렛트 규격 비율 검증

PnP로 3D pose를 복원한 뒤, 복원된 3D 크기가 알려진 파렛트 규격과 일치하는지 검증한다.

```python
def filter_C_pallet_ratio(keypoints_2d, pallet_3d_kp, camera_matrix,
                          expected_wh_ratio=1.0,     # 1100/1100
                          expected_hw_ratio=0.136,    # 150/1100
                          tau_c=0.15):                # 15% 허용 오차
    """
    PnP → 3D 복원 → 가로:세로:높이 비율이 표준 규격과 일치하는가?

    이 필터는 파렛트 도메인에 특화된 constraint.
    다른 물체의 bounding box도 직육면체지만,
    알려진 규격 비율이 있는 것은 파렛트의 특성.

    표준 파렛트 규격:
      KS T-11형: 1100×1100×150mm → wh=1.0, hw=0.136
      EUR 파렛트: 1200×800×144mm  → wh=1.5, hw=0.12
    """
    # PnP로 pose 복원
    success, rvec, tvec = cv2.solvePnP(
        pallet_3d_kp[:8].astype(np.float64),
        keypoints_2d[:8].astype(np.float64),
        camera_matrix, None,
        flags=cv2.SOLVEPNP_EPNP
    )
    if not success:
        return False

    # 3D 모델 점을 카메라 좌표계로 변환
    R, _ = cv2.Rodrigues(rvec)
    points_cam = (R @ pallet_3d_kp[:8].T + tvec).T

    # 가로, 세로, 높이 계산
    width  = np.linalg.norm(points_cam[1] - points_cam[0])
    depth  = np.linalg.norm(points_cam[3] - points_cam[0])
    height = np.linalg.norm(points_cam[4] - points_cam[0])

    # 비율 검증
    if depth < 1e-6 or width < 1e-6:
        return False

    wh_ratio = width / depth
    hw_ratio = height / width

    ratio_ok_1 = abs(wh_ratio - expected_wh_ratio) / expected_wh_ratio < tau_c
    ratio_ok_2 = abs(hw_ratio - expected_hw_ratio) / expected_hw_ratio < tau_c

    return ratio_ok_1 and ratio_ok_2
```

### 통합 필터

```python
def geometric_filter(model, image, keypoints_2d, pallet_3d_kp, camera_matrix,
                     tau_a=5.0, tau_b=0.3, tau_c=0.15):
    """3단계 필터 전부 통과해야 pseudo-label로 채택"""

    # [A] Augmentation Consistency
    if not filter_A_augmentation_consistency(model, image, tau_a):
        return False, "filter_A_failed"

    # [B] 변 길이 일관성
    if not filter_B_edge_consistency(keypoints_2d, tau_b):
        return False, "filter_B_failed"

    # [C] 파렛트 규격 비율
    if not filter_C_pallet_ratio(keypoints_2d, pallet_3d_kp, camera_matrix, tau_c=tau_c):
        return False, "filter_C_failed"

    return True, "passed"
```

## 4.4 필터 설계 근거

| 필터 | 검증 내용 | 수준 | 잡을 수 있는 오류 | 참고 |
| ---- | --------- | ---- | ------------------ | ---- |
| A    | 예측의 불변성 | 일반적 | 불안정한 예측 (augmentation에 민감) | CC-SSL, Animal Pose |
| B    | 직육면체 구조 | 반일반적 | keypoint 일부가 크게 빗나간 경우 | UDA-COPE에서 영감 |
| C    | 파렛트 규격 | domain-specific | 파렛트가 아닌 물체를 잘못 검출한 경우 | 본 연구 contribution |
