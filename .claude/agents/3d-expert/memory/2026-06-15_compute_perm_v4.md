# 2026-06-15 compute_perm_v4 — 카메라 동적 0123 keypoint ID + 비율 랜덤

## 작업
FoundationPose Blender 합성 파이프라인에 (A) 카메라 기준 동적 0123 keypoint ID 재배정,
(B) 비등방 비율 랜덤(40%, 축당 ±12%), (C) scene_1/2/3 전용 10샘플 프리뷰 생성.

## 핵심 위치
- `scripts/data_prep/blender/blender_math.py`
  - `compute_perm_v4(corners_world, uv8, cam_pos=None)` (L117~) — ID 재배정.
  - `_polyarea_2d(pts2d)` (L110) — shoelace.
- `scripts/data_prep/blender/gen_preview10.py` — 프리뷰 생성기(헤드리스 Blender standalone).
  - `compute_annotation_v4()` — get_pallet_geometry → 9pt 투영 → compute_perm_v4 로 재정렬.
  - `apply_ratio_randomization()` — obj.scale 에 per-axis factor 곱 + 재접지. GT 는 변형 메시에서 재계산되므로 자동 정합.

## compute_perm_v4 알고리즘 핵심 (검증된 형태)
1. world z 로 top4/bot4 분리.
2. vertical pairing: top vtx ↔ xy 최근접 bot vtx.
3. top4 를 평행 2-edge 로 split (cos≥0.95, 대각선 배제).
4. **두 후보 면을 2D 투영 → shoelace area 큰 면 = FRONT**(원근으로 카메라 near 가 크게 투영).
   - 면적비 <5% (축정렬 카메라 등 degenerate) 일 때만 cam_pos 3D 거리로 tiebreak.
5. FRONT-TOP edge 에서 image x 작은 쪽=0, 큰 쪽=1. vertical 짝 → 3,2.
6. REAR-TOP edge 동일 → 4,5, vertical 짝 → 7,6. 8=centroid.

## 삽질 / 교훈 (중요)
- **테스트 오라클 함정**: "FRONT=카메라 near"를 *3D 면중심-카메라 거리*로 검증하면 120중 79 FAIL 처럼 보임.
  그러나 이는 오라클이 틀린 것. 평평한 팔레트를 비스듬히 보면 **투영면적이 큰 면**과
  **3D 거리상 가까운 면**이 진짜로 불일치할 수 있다(카메라가 한 축 위에 있을 때).
  사용자 스펙은 명시적으로 *투영면적*을 FRONT 기준으로 택함. 올바른 오라클(투영면적 + 내부정합:
  top>bot, 0/4 left of 1/5, vertical pairing)로 검증 시 240/240 PASS.
  → flat 물체 keypoint 검증은 3D 거리 말고 **투영면적 + 기하 내부정합**으로 판정할 것.
- degenerate(square 1.1×1.1, 축정렬 카메라)에서 front/rear 면적이 tie → cam_pos 3D 거리 tiebreak 추가로 해결.
- 비율 랜덤은 obj.scale 에 per-axis 곱만 하면 get_pallet_geometry 가 matrix_world 로 bbox 를
  다시 읽으므로 GT corner 가 자동으로 변형 메시에 정합. 별도 corner 재계산 불필요.

## 결과 (10 샘플, seed=20260615)
- scene 분포: scene_1=2, scene_2=6, scene_3=2 (n=10 이라 균일에서 변동, 가중치는 1/3 균등).
- 비율 랜덤: 3/10 적용 (기대 40%, n=10 변동 범위).
- 전 프레임 v4 convention PASS (top>bot, frontBig, 0L1, 4L5, vpair).
- 저장: `data/pallet/_preview10/{images,json,overlay}/`.

## 주의 (학습 영향)
- 카메라 동적 0123 는 사용자가 "object-frame 고정이 DOPE 학습에 안전" 경고를 인지하고 명시 선택.
  같은 팔레트라도 카메라 위치 따라 같은 물리 코너의 ID 가 바뀜 → belief map target 이
  뷰 의존. 학습 안정성/수렴은 추후 관찰 필요 (이번 작업 범위 밖).
- ORIENTATION_OVERRIDES 는 건드리지 않음(팔레트 정렬 유지, ID 배정만 카메라 기준).
- 큰 카메라 거리(far/top_down) 프레임은 cuboid 가 작아 overlay 육안 판정 어려움 → JSON 수치 검증 병행 필수.
