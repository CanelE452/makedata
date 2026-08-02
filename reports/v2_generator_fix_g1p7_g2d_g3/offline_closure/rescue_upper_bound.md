# G1.7 §24.2 rescue upper-bound

## 필요량

```
G1.6 CASE_WALL_TIME_S            4,754.4 s
§13 gate                        <= 4,279.0 s
필요 절감                          475.4 s
엄격 near-miss 절감 상한            263.8 s   (G1.7-A)
SIDE/G1 이 추가로 벌어야 하는 양     211.5 s
```

## category 별 절감 상한 (G1.7-A, 낙관적 가정)

```
가정                                   대상      절감상한
────────────────────────────────────────────────────────
엄격 near-miss (연속 margin 이 작음)    9 case    263.8 s
문헌적 4/5 (side 포함)                 26 case    870.0 s
절대 상한 (acceptance 도달이면 구제)    43 case  1,474.8 s
```

## SIDE/G1 실제 절감 (mechanism subset 실측)

```
A            subset 1606.1 -> 1872.1 (-266.0) · actionable  704.5 ->  833.7 (-129.2) · trig 12 won 1
B            subset 1606.1 -> 1888.2 (-282.1) · actionable  704.5 ->  853.6 (-149.1) · trig 12 won 1
```

## remaining gap 과 판정

실측은 절감이 아니라 **증가**다.  rescue 는 기존 search 가 실패한 뒤에 추가로 도는
단계라, 성공하지 못하면 그 비용이 그대로 순증한다.  성공해도 이득은 "남은 proposal 을
건너뛴 만큼"으로 제한되는데, 실측 성공률이 낮아 기대값이 음수가 된다.

**local rescue 로 §13 primary gate 에 도달할 수 없다** — 근거:

1. 엄격 near-miss 상한(263.8 s)이 필요량(475.4 s)에 이미 못 미친다.
2. 부족분을 메우려면 SIDE 를 구제해야 하는데, SIDE 는 연속 margin 이 없고
   판정기가 bottom 을 먼저 검사한다.  occluder 는 접지 제약으로 화면에서 세로
   이동이 자유롭지 않아, 국소 offset 으로 side 범주를 바꾸기 어렵다.
3. mechanism subset 실측에서 rescue 는 wall 을 늘렸다.

따라서 다음 축은 "실패한 후보를 더 잘 고치는 것"이 아니라
**"그 후보를 애초에 만들지 않는 것"** 이다 (next_design_options.md).
