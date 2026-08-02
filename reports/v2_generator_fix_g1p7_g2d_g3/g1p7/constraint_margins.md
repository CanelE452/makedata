# G1.7 §8 — constraint margin

acceptance 를 실제로 평가받은 후보 **2186 / 2918** 건 기준.  나머지 732 건은 hard
physical 단계에서 탈락해 margin 이 존재하지 않는다(None, pass 아님).

## 정의 (boolean 에 연속 margin 을 지어내지 않았다)

```
조건          margin 정의                              종류
──────────────────────────────────────────────────────────────────────
visibility    visible_pixels - 8                       연속 (정수 px)
target        0.12 - abs_error                         연속 (무차원)
G1            V_vis - 4                                연속 (정수 코너)
G2            min(ext_occ - 1, 4 - ext_occ)            연속 (정수 코너)
side          없음 — boolean pass/fail                 boolean
hard physical 없음 — boolean                            boolean
```

G1/G2 의 연속 margin 은 지어낸 값이 아니라 gate 함수가 실제로 세는 코너 개수다.
side 는 범주형 일치라 연속 margin 이 **존재하지 않으므로 만들지 않았다.**

## 실패 후보의 margin 분포

```
조건          분포
──────────────────────────────────────────────────────────────────────────────────
target        n=1594  min -0.7372  p25 -0.2837  med -0.1574  p75 -0.07119 max -0.002064
G1            n=504   min -4       p25 -3       med -2       p75 -1       max -1
G2            n=1152  min -4       p25 -1       med -1       p75 -1       max -1
visibility    n=310   min -8       p25 -8       med -8       p75 -8       max -1
side          n=1467  (연속 margin 없음)
```

## 해석 — 이 분포가 rescue 설계를 좌우한다

- **target**: 실패 1594 건 중 경계에서 0.02 이내는 **84 건(5.3%)**, 0.05 이내는
  248 건뿐이다.  중앙값 margin 은 -0.157 로 허용오차(0.12)의 배가 넘게 벗어나 있다.
  즉 target 실패의 대다수는 "아깝게 빗나감"이 아니다.
- **G2**: 실패 1152 건 중 **1068 건이 margin −1**, 그중 **1028 건이 ext_occ=0** 이다.
  가림이 하나도 없어 딱 1개만 더 가리면 되는 상태 — 국소 이동으로 가장 고치기
  쉬운 유형이다.
- **G1**: 실패 504 건 중 margin −1 이 177 건.  코너 1개만 더 보이면 된다.
- **visibility**: 실패 중앙값이 −8 = **0 px**.  occluder 가 화면에 아예 안
  보이는 경우가 대부분이라 near-miss 가 아니다.
- **side**: 1467 건.  연속 margin 이 없을 뿐 아니라, occluder 가 팔레트를 전혀
  덮지 않아 actual side 를 못 구한 후보가 832 건이다.

## 단독 위반 분포 (violation_count == 1)

```
target         221
G2             172
side           103
G1              41
```

normalized margin 은 분석용으로만 썼고 acceptance 조건은 바꾸지 않았다.
