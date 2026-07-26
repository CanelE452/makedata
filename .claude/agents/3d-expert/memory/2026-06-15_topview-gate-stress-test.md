# 2026-06-15 Top-down stress test — does new 0123 (perm_v4) survive high elevation?

## 질문
"이제 태그 제대로 하는 법 아니까 탑뷰에서도 잘 되나?" → 말 말고 데이터로.
compute_perm_v4(normal-facing FRONT) + front_cos grazing 게이트(>=0.40) + facing_margin(>=0.60)
를 elevation 20~88°(거의 수직 포함)로 넓혀 샘플 → 게이트 동작 + 통과 라벨 정확도 정량화.

## 스크립트
`scripts/data_prep/blender/gen_topview_test.py` (gen_preview10 복제 + 수정, preview10 미변경).
- ELEV 20~88°, 게이트는 preview10과 동일 유지.
- **핵심 차이**: 모든 candidate(retry 포함)를 reason×elevation 버킷으로 집계
  (preview10은 마지막 reject reason만 print해 통계 불가).
- N=24, out=`data/pallet/_test_topview/`, `_summary.json` 기계판독 덤프.
- Blender 5.1 headless, synth_data_scene.blend, Cycles 24spp. ~10분.

## 결과 (seed 20260615, candidates=1186, saved=24)
게이트 reject (elevation 버킷별):
```
reason               20-40  40-60  60-70  70-80  80-88   total
front_cos(grazing)     14     26     36    110    145     331
facing_margin            0      0      0      0      0       0
connector_cross          0      0      0      0      0       0
raycast                314    288    121     68      5     796   (occlusion, elev무관)
PASS                    10     14      0      0      0      24
```
- **>=60° PASS = 0**. 가장 수직에 가까운 통과 프레임 elev = **58.4°**(frame2).
- front_cos 게이트가 고각도 reject를 단독 담당: 70-80°→110, 80-88°→145 (elevation 단조증가).
  → 거의 수직 탑뷰는 FRONT가 edge-on(얇은 띠)이 되어 front_cos<0.40으로 **자동 배제**됨. (a) 답.
- facing_margin·connector_cross reject 0 — front_cos가 먼저 다 걸러서 뒤 게이트까지 안 감.

통과 24장: **전부 conn_x=0, front_near=true**. 크롭 육안검증(frame 2/10/12/16/17/18/21 등):
FRONT(녹색 0123 quad)=카메라 마주보는 side, 박스가 팔레트에 밀착, X-cross 없음. → (b) 답 yes.

## 결론
탑뷰에서 새 방법은 (a) 모호한 거의-수직 탑뷰(>=60°)를 front_cos 게이트로 **100% 자동 배제**하고,
(b) 통과시킨 24장은 0123 라벨이 전부 맞음(conn_x=0, FRONT=cam-facing).
즉 "탑뷰에서 잘 되나?" → **통과시키는 것은 정확, 진짜 수직 탑뷰는 학습셋에서 빠진다**(ill-posed라 의도된 배제).
수직 탑뷰 자체를 데이터에 넣고 싶으면 다른 convention(예: top-face 기준 yaw-only)이 필요.

## 삽질 / 교훈
- **rect_ok 오라클 함정(재발)**: 내가 추가한 is_rectangleish(aspect>=0.10)가 통과 24장 중 12장을
  rect_ok=false로 찍었는데, 크롭 육안+conn_x=0+front_near=true로 보면 전부 정상 라벨.
  flat 팔레트의 FRONT side면은 본래 1.1m×0.11m → 투영 aspect~0.10 경계라 정상인데도 false.
  → flat 물체 keypoint 정합 판정은 aspect 같은 단일 임계 말고 **conn_x(연결변 X-cross)+front_near+육안**으로.
  (compute_perm_v4 메모와 동일 교훈: 3D거리/aspect 단일 오라클 금지.)
- Python print는 파이프로 묶이면 full-buffered → headless Blender stdout이 종료까지 안 보임.
  진행 모니터링은 images/ 폴더 frame 수 폴링으로. 통계는 종료 후 _summary.json/_run.log에서.
- 고각도 candidate는 raycast(796)·front_cos(331)로 대량 reject → 24장 모으는 데 candidate 1186,
  reject streak로 프레임 생성이 들쭉날쭉(burst). 정상.

## 저장
- `data/pallet/_test_topview/{images,json,overlay,_crop}/` + `_summary.json` + `_run.log`.
- 스크립트 `scripts/data_prep/blender/gen_topview_test.py`.
