# E-front 12kp 개구부 캘리브레이션

`scripts/data_prep/blender/efront_kp12.py`의 `EFRONT_RATIOS`(팔레트 앞면 fork 개구부
비율 테이블)를 **측정으로부터 재생성·검증**하는 도구. 하드코딩 테이블이 유일 권위가
되지 않도록 provenance를 버전관리한다.

## measure_efront.py
Blender 5.1로 P0~P3 × 앞면 2종의 개구부 기하 8레코드를 측정:
- 닫힌 2홀 면: see-through 정사영 hole 검출
- bottom_open 면(P1 short, P2 long): front slab + 데크 밑면 cap + 바닥 seal
- 출력 JSON = data/pallet/archive/_efront_12kp_check/efront_measurements.json (대용량 산출물이라 gitignore)
- efront_kp12.py의 build_ratio_table_from_json()과 대조 시 mismatch 0 이어야 함

실행:
  blender -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
    --python scripts/data_prep/efront_calibration/measure_efront.py

## 관련
- 테이블 소비: scripts/data_prep/blender/efront_kp12.py (compute_efront_kp12)
- 배선: gen_4pallet_mask.py / gen_dataset_v4.py compute_annotation_v4
- 이력: _docs/history/2026-07-23.md
