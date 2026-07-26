# 2026-06-15 perm_v4(camera-facing) vs 기존 라벨(object-frame) 정합성 감사

## 결론 (핵심 숫자)
- 기존 train_batch / v11 train(4000) 라벨 = **object-frame 고정** (canonical_corners_yup, 카메라 무관).
- compute_perm_v4(camera-facing) 재적용 시 **FRONT 불일치 ~53%, PERM 불일치 ~59%** (2000장+4000장 전수).
- → 두 정의는 호환 불가. 섞으면 절반 프레임에서 라벨 모순.

## 근거 file:line
- render_blender_data.py:62,70,122 — get_pallet_geometry corners_world 순서 그대로 projected_cuboid. compute_perm 호출 없음.
- pallet_geometry.py:217 canonical_corners_yup(cbmin,cbmax) — bbox만으로 corner 순서.
- blender_math.py:85 canonical_corners_yup, :138 compute_perm_v4(world z=height 사용, cam-frame 미사용).
- 감사 스크립트: scripts/data_prep/blender/_audit_perm_disagreement.py (numpy만, conda 불필요).

## 좌표/부호 함정 점검
- train_batch/train/preview10 전부 world Z-up, cam world 좌표 (top_z>bot_z=0).
- compute_perm_v4 는 cam-frame z 부호 안 씀 → v3 폐기 원인(USD z<0 vs OpenCV z>0) 재발 불가.

## 모델 현황
- pallet_v11 = train/(4000) object-frame 라벨로 학습. preview10 만 keypoint_convention=camera_dynamic_0123_v4.
- paper_base/mixed_v8/convert_to_camera_facing_v4.py 는 이 repo 부재(사용자 인용은 다른 맥락).

## front_cos 게이트
- front_cos<0.40 = 45.7% (저각도 대거 컷). 드롭 대신 라벨신뢰도 down-weight 권장.

## 권장
- 혼용 절대 금지. 단기는 object-frame 통일(비용~0), 동적 원하면 신규데이터만 v4 + v11 폐기.
