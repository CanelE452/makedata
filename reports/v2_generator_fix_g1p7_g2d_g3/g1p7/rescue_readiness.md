# G1.7 §11 — rescue 진행 게이트

## 게이트 판정

```
조건                                                     값              판정
──────────────────────────────────────────────────────────────────────────────────
A. top 2 actionable category 가 rejected wall 의 >= 50%   54.2%          PASS
     ONE_MISS_SIDE + ONE_MISS_G1
B. 4/5 near-feasible case 가 rejected wall 의 >= 50%      70.6% (26 case)  PASS
그리고
   hard physical only 가 지배하지 않음                     0.0%           PASS
   no feasible candidate found 가 지배하지 않음            16.5%          PASS
──────────────────────────────────────────────────────────────────────────────────
RESCUE_READY                                                             true
```

A·B 중 하나만 만족하면 되는데 **둘 다 만족**한다.

## 그러나 — 게이트 통과가 §23 통과를 뜻하지는 않는다

게이트는 "rescue 사정권 안의 비용이 충분히 큰가"만 본다.  실제로 절감 가능한
시간은 별개이고, 그것을 먼저 계산했다.

**rescue 는 proposal loop 안에서 돈다** (`v2_realize.py:2245`).  proposal p 에서
성공하면 `v2_realize.py:2295-2308` 의 break 로 남은 proposal 을 건너뛴다
(case 당 proposal 3개, `EXPLICIT_PROPOSAL_SEARCH_LIMIT=3`) [확인].
따라서 절감 상한 = 성공 시점 **이후** proposal 들의 비용이다.

```
가정                                                  대상    절감 상한   필요
──────────────────────────────────────────────────────────────────────────────
A 엄격 near-miss (연속 margin 이 실제로 작음)          9 case    263.8 s   475.3 s  미달
B 문헌적 4/5 near-feasible (side 포함)                26 case    870.0 s   475.3 s  달성
C 절대 상한 (acceptance 도달 후보면 무조건 구제)      43 case   1474.8 s   475.3 s  달성
```

- 상한은 전부 **낙관적** 이다: rescue 자체 비용 0, 성공 즉시 이후 proposal 전부
  생략, explicit stage 시간을 후보 수에 비례 배분 [추정].
- 실제로는 `abs_error > 0.05` 면 break 조건이 proposal 2개를 요구하므로
  (`EXPLICIT_MIN_PROPOSALS_BEFORE_TOLERANCE_STOP=2`) 절감분은 이보다 작다.

### 무엇이 갈림길인가

엄격 기준만으로는 §23 primary(−10%, 475.3 s 감축)에 **미달**한다.  달성하려면
`side` 로 막힌 case 를 실제로 구제해야 하는데, side 는:

- 연속 margin 이 없다 (boolean 범주 일치).
- rejected 43건 중 target side 를 한 번이라도 달성한 case 는 22건,
  **한 번도 못 한 case 가 9건**, actual side 자체를 못 잰 case 가 12건이다.
- side_match=False 이면서 actual=None 인 후보가 832건 — occluder 가 팔레트를
  전혀 안 덮어 side 를 산출할 수 없는 상태다.

즉 "4/5 를 만족한다"가 곧 "국소 이동으로 고칠 수 있다"를 뜻하지 않는다.
반대로 G2 실패의 1028/1152 건은 `ext_occ=0` 으로 **딱 1개만 더 가리면 되는** 상태라
국소 이동이 잘 맞는다.

## 판정

**RESCUE_READY = true** — §11 이 정한 조건을 A·B 모두 충족하므로 G1.7-B 를
진행한다.  다만 위 상한 분석에 따라 §23 primary gate 통과는 side 구제 성공 여부에
달려 있고, 그것은 [미검증] 이다.  이 사실을 구현 전에 기록해 둔다.

JSON: `rescue_readiness.json`
