# G1.7 무인 실행 — 최종 아침 보고

**한 줄 결론: constraint-directed local rescue 는 accepted 품질을 완벽히 보존하지만
CASE_WALL_TIME_S 를 줄이지 못하고 오히려 늘린다.  §4 micro-gate 실패로 locked77·G2d·G3
를 실행하지 않고 OFFLINE_CLOSURE 로 마감했다.  commit/push 0, 실렌더 0.**

## 1. 밤새 실제로 실행한 단계

```
단계                                   상태     결과
────────────────────────────────────────────────────────────────────────────────
PRE_FLIGHT/snapshot                    RUNNING  
PRE_FLIGHT/snapshot                    PASS     UNRELATED=0 · blender=0 · HEAD==origin/main
BASELINE/regression                    RUNNING  
BASELINE/regression                    PASS     registry ok=28 · unit 919 · integ 31 · golden 51 · 938f387d/
G1P7B/implement                        PASS     SP2 rescue layer + v2_realize stage + runner/replay CLI · un
G1P7B/mechanism_subset                 RUNNING  
G1P7B/mechanism_configA                RUNNING  
G1P7B/seed_sign_defect                 FAIL     
G1P7B/mechanism_configA_prefix         FAIL     wall +288.5s · act_saving -137.1s · trig 12 won 1 · 품질 보존 · 
G1P7B/mechanism_configA                PASS     완주 · 품질1-3 PASS · micro-gate FAIL(-129.2s)
G1P7B/mechanism_configB                PASS     완주 · 품질1-3 PASS · micro-gate FAIL(-149.1s)
G1P7B/micro_gate                       FAIL     MICRO_GATE_PASS=false · 필요 +211.5s vs 실측 -129.2/-149.1s
OFFLINE_CLOSURE/atlas                  RUNNING  
```

## 2. 소요시간

```
overnight elapsed                2.20 h  (상한 12 h)
Blender elapsed (replay 3회)     1.57 h  (5655.1 s)
offline elapsed                  0.63 h
```

## 3. 최종 도달 phase

**G1.7-B mechanism 비교까지.**  locked77 전체 replay 는 §4/§12 규칙에 따라 **미실행**.

## 4. G1.7-A 정본

acceptance 계약을 코드에서 직접 확정했다 (`v2_realize.py:1838-1843`) [확인]:
`side_match AND visible_pixels>=8 AND abs_error<=0.12 AND (G1 AND G2)`.
`score` 는 임계가 아니라 ranking 전용이다.

```
binding signature (rejected 43건, CASE_WALL_TIME_S 기준)
────────────────────────────────────────────────────────────
ONE_MISS_SIDE          10 case   734.0 s   28.7%
ONE_MISS_G1            10 case   651.2 s   25.5%
MULTI_CONSTRAINT       11 case   421.6 s   16.5%
ONE_MISS_G2             3 case   227.5 s    8.9%
TWO_MISS_G1_SIDE        3 case   180.6 s    7.1%
ACCEPTED(=frame gate)   2 case   153.1 s    6.0%   <- explicit 성공, G3/G5 에서 탈락
ONE_MISS_TARGET         2 case    97.0 s    3.8%
TWO_MISS_SIDE_TARGET    2 case    89.8 s    3.5%
```

- `HARD_PHYSICAL_ONLY` **0건** · 중복 후보 128/2,918 은 **전부 stage-crossing**
- §11 rescue readiness: A 54.2% · B 70.6% -> **RESCUE_READY=true**
- 그러나 절감 상한: 엄격 near-miss **263.8 s** < 필요 **475.4 s** (사전 경고 기록)

## 5. mechanism Config A/B

```
config                     A (beam2/eval6)   B (beam3/eval8)
──────────────────────────────────────────────────────────────
subset CASE_WALL_TIME_S       1872.1 s           1888.2 s
  baseline                    1606.1 s           1606.1 s
  saving                      -266.0 s           -282.1 s
SIDE/G1 actionable saving     -129.2 s           -149.1 s
rescue triggered / won      12 / 1            12 / 1 
newly accepted               1                 1
품질 gate 1-3 (recall/품질/post-context)  PASS          PASS
§4 micro-gate (>= +211.5 s)               FAIL          FAIL
```

예산을 키운 B 가 **더 나쁘다** — rescue 는 기존 탐색이 실패한 뒤에 붙는 단계라
성공하지 못하면 비용이 순증하고, 성공해도 이득은 "남은 proposal 건너뛰기"로 제한된다.

부호 결함 1건을 실행 중 발견해 수정했다 (`side_specific_lift` 의 bottom 분기가
실측 감도 대신 부호를 추측). 수정 전/후를 분리 측정한 결과 seed 분포는 바뀌었지만
(`side_specific_lift` 14회 -> `side_specific_shift` 5회) **rescue 성공은 1건으로 동일**해,
실패 원인이 그 결함이 아님을 확인했다 [확인].

## 6. 선택 config

**없음.**  둘 다 §4 micro-gate 미달 -> `chosen=null`, `next=OFFLINE_CLOSURE`.

## 7. locked77 결과

**미실행.**  §12 "둘 중 하나가 1~3 은 통과하지만 추가 절감 211.5 s 미달 -> locked77 실행
금지" 에 해당한다.

## 8. G2d 결과 또는 미실행 사유

**미실행.**  `G1P7_LOCKED_PASS` 가 성립하지 않았다 (§14 전제 불충족).

## 9. G3 결과 또는 미실행 사유

**미실행.**  §20 전제(`G1P7_LOCKED_PASS AND G2D_MIXED100_PASS`) 불충족.

## 10. 500 준비 패키지

**미생성.**  `READY_FOR_NEW_500_PILOT` 이 false 이므로 §23 전제 불충족.
(500/2,000/40,000 실렌더 0, 모델 학습·추론 0, ADD/ADD-S 0.)

## 11. hard gate 실패 항목

```
게이트                                    기준          실측              판정
──────────────────────────────────────────────────────────────────────────────
§4 micro-gate SIDE/G1 추가 절감           >= +211.5 s   A -129.2 / B -149.1 s   FAIL
§13 CASE_WALL_TIME_S (locked77)           <= 4,279.0 s  미측정(실행 안 함)     N/A
품질 gate 1-3 (recall·paired·post-ctx)    회귀 0        회귀 0                PASS
```

## 12. baseline 불변

```
5k FrameSpec digest      938f387d   (기대 938f387d)  unchanged=True
5k proposal digest       3cd365ee   (기대 3cd365ee, 12/12)  unchanged=True
active scene SHA         8cb4109adc6d   unchanged=True
baseline dataset 수정                     0건
locked77 G1.6 replay record 불변          True
public mask schema (['m0', 'm4'] / ['mask_amodal', 'mask_visible'])  unchanged=True
```

## 13. 남은 문제

1. **SIDE 는 국소 이동으로 고쳐지지 않는다.**  `_occlusion_side_from_masks`
   (`v2_realize.py:3516`) 는 가려진 픽셀 centroid 의 화면 위치로 side 를 정하고
   **bottom 을 가장 먼저** 검사한다.  occluder 는 support 제약으로 접지해야 해
   화면에서 세로 이동이 자유롭지 않다.  SIDE actionable 11건 중 target side 를
   한 번도 달성하지 못한 case 가 **7건**이다.
2. **G2 는 고칠 여지가 가장 크지만 위치가 나쁘다.**  G2 실패 1,152건 중 1,028건이
   `ext_occ=0`(딱 1개만 더 가리면 됨) 인데, rescue 가 탐색 **끝**에 있어 이미
   예산을 다 쓴 뒤에야 시도한다.
3. **acceptance 도달 전 탈락이 25.1%** (support 463 · camera_clearance 157 ·
   collision 112) — rescue 는 이 구간을 전혀 건드리지 않는다.

## 14. 다음 한 가지 권장 행동

`offline_closure/next_design_options.md` 의 **후보 2 (ext_occ=0 조기 종료)** 를
**offline 판별 실험부터** 하는 것.  렌더 0회로 가능하다: locked77 accepted 34건의
`explicit_selected_stage` 를 집계해, 승리 후보가 coarse 이후 stage 에서 나온 비율을 본다.
그 비율이 높으면 이 방향도 폐기해야 한다.  이것이 **절감이 순증하는 유일한 구조**다
(rescue 는 실패 시 비용이 순증하지만, 조기 종료는 실패 시 비용을 줄인다).

## 15. commit / push

**commit 0 · push 0.**  사용자 승인 없이 하지 않는다.

---

## 최종 표

```
항목                                   값
────────────────────────────────────────────────────────────────
overnight elapsed                      2.20 h
Blender elapsed                        1.57 h (replay 3회)
offline elapsed                        0.63 h
locked cases expected / actual         77 / 0 (locked77 미실행)
mechanism configs run                  3 (A 수정전 trial + A + B)
accepted recall (subset protection)    11/11 · 11/11
paired explicit median / p95           0.0573 -> 0.0573 (변화 없음)
post-context regression                0
wall time before / after (subset)      1,606.1 -> A 1872.1 / B 1888.2 s
rejected stage runtime before/after    locked77 미실행 — N/A
accepted median before / after         locked77 미실행 — N/A
additional SIDE/G1 saving              A -129.2 s · B -149.1 s  (필요 +211.5 s)
checkpoint10 pass                      미실행
mixed100 semantics                     미실행
integrity failures                     미실행
overlay count / broken / size mismatch 미실행
A / C / runtime ratio                  미실행
exact20 mismatch counts                미실행
dataset-quality RGB mismatch           미실행
500 preparation complete               false (전제 불충족)
unit fail / skip                       0 / 0  (959 passed)
integration fail / skip                0 / 0  (31 passed)
golden fail / skip                     0 / 0  (51 passed)
5k digest change                       0
scene SHA change                       0
baseline modified                      0
public schema changed                  0
500 render                             0
2k render                              0
40k render                             0
model training                         0
model inference                        0
commit                                 0
push                                   0
```

## §27 최종 상태

```
G1P7_LOCKED_PASS                false  (미실행 — micro-gate 에서 중단)
G2D_MIXED100_PASS               false  (미실행)
G3_REPRODUCIBILITY_PASS         false  (미실행)
READY_FOR_NEW_500_PILOT         false
NEXT_500_PREPARATION_COMPLETE   false
OFFLINE_CLOSURE_COMPLETE        true
```
