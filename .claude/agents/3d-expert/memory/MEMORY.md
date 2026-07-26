# 3d-expert 경험 인덱스

| 날짜 | 주제 | 파일 |
|------|------|------|
| 2026-06-15 | compute_perm_v4 (카메라 동적 0123 keypoint ID + 비율 랜덤) | 2026-06-15_compute_perm_v4.md |
| 2026-06-15 | 탑뷰(elev 20~88°) 게이트 stress test — front_cos가 >=60° 자동배제, 통과라벨 정확 | 2026-06-15_topview-gate-stress-test.md |
| 2026-06-16 | run_dataset_v4 폴더 분할(폴더당 200장 독립 DOPE 데이터셋) + resume | 2026-06-16_folder-split-driver.md |

## 빠른 참조
- 카메라 동적 keypoint ID: `blender_math.compute_perm_v4()`. flat 물체 검증은 3D 거리 아닌 **투영면적+기하 내부정합**으로.
- 비율 랜덤: obj.scale per-axis 곱 → get_pallet_geometry 가 GT corner 자동 재계산.
- 프리뷰 생성기: `scripts/data_prep/blender/gen_preview10.py` (헤드리스 standalone).
