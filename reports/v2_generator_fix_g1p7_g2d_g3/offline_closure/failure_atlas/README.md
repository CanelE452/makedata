# G1.7 failure atlas

locked77 의 rejected 43건을 binding category 별로 정리한다.  렌더는 하지 않았고
기존 산출물만 사용했다 (대표 RGB 12장 복사).

```
파일                              건수   설명
────────────────────────────────────────────────────────────────────────
side_cases.csv                     11    ONE_MISS_SIDE 를 actionable 로 가진 case
g1_cases.csv                       10    ONE_MISS_G1 를 가진 case
side_g1_overlap_cases.csv           1    둘 다 가진 case (wall 중복 합산 금지)
downstream_g3_g5_cases.csv          2    explicit 은 성공, frame gate 에서 탈락
no_feasible_cases.csv              11    최선 후보가 3개 이상 위반
all_rejected_cases.csv             43    전체
```

## SIDE 가 왜 국소 rescue 로 안 되는가

`_occlusion_side_from_masks` (`v2_realize.py:3516`) 는 **가려진 픽셀 centroid** 의 화면
위치로 side 를 정하고 **bottom 을 가장 먼저** 검사한다.  occluder 는 support 제약 때문에
접지 상태를 유지해야 하므로 화면에서 세로로 자유롭게 못 움직인다.

SIDE actionable 11건 중 target side 를 **한 번도 달성하지 못한** case: **7건**.

```
case   target   달성한 side 분포
──────────────────────────────────────────────────
34     bottom   {"right": 16, "center": 10, "left": 15, "bottom": 2}
55     bottom   {"left": 2, "right": 2, "center": 8}
58     bottom   {"center": 44, "left": 7, "right": 6}
109    bottom   {"center": 34, "bottom": 1, "left": 3, "right": 3}
128    right    {"center": 9, "bottom": 16}
173    left     {"bottom": 27}
199    right    {}
222    bottom   {"center": 49, "left": 5, "right": 5, "bottom": 1}
225    left     {"bottom": 9, "center": 4, "left": 2}
238    right    {}
242    right    {"bottom": 37}
```
