# Phase G1.6 / G2c / G3 최종 보고 (정정 기준 적용)

## 1. 목적과 판정

목적: controlled solver 의 남은 효율 병목을 (1) target-seed free budget 상한화,
(2) near-miss 한정 fine refinement 로 해결하고 G1.6 -> G2c -> G3 순으로 검증.

```
G1P6_SCORE_GAP_AUDIT_COMPLETE   true
G1P6_CONFIG_SELECTED            true    K=8 · threshold 0.0607(p25)
G1P6_ACCEPTED_RECALL_PASS       true    legacy accepted 30/30
G1P6_EXPLICIT_QUALITY_PASS      true    paired 비교에서 median·p95 동일
G1P6_POST_CONTEXT_PASS          true
G1P6_LOCKED_EFFICIENCY_PASS     false   total runtime · score_callback count 미달
──────────────────────────────────────────────────────────────────────
G1P6_LOCKED_PASS                false
G2C_* / G3_*                    NOT_RUN
READY_FOR_NEW_500_PILOT         false
```

## 2. 적용한 정정 기준

```
1. score_callback = reject **count** (초 아님).  gate <= 1,722(count).
   시간은 explicit_stage_runtime_s / fine_runtime_s / total_runtime_s 로 별도.
2. K=8 은 unlimited 와 동작 동일(paid_used 0) -> 효율 변화는 fine 에만 귀속.
3. explicit 품질은 legacy accepted 30건 **paired** 비교 (회복분 제외).
4. runtime 은 77건 전체 (회복분 최종 렌더 비용 포함).
5. hard gate 하나라도 실패하면 G2c·G3 미시작.
```

## 3. branch / HEAD / baseline lock

```
branch main · HEAD 0ebb41cb… (= origin/main) · commit 0 · push 0 · UNRELATED 0
pilot_1449 / smoke100 / smoke100b  records.jsonl SHA256 **전부 불변**
active scene 8cb4109a… 불변 · locked cases 77건 sha256 고정
```

## 4. score-gap 분포 (§2 감사)

수락 조건은 코드에서 읽었다 — **`score` 에는 임계가 없다**.

```python
accept = side_match AND visible_px>=8 AND abs_error<=0.12 AND (G1 AND G2)
score  = -(error + roi + 0.25*corner + screen + visibility)   # 랭킹용 음수 비용
```

막고 있는 조건 조합(locked 2,892 후보): `side|target|corner` 778(26.9%) ·
`corner 만` 215 · **`target_error_ok 만` 199(6.9%)** ← fine 이 손댈 수 있는 유일한 부류.
near-miss gap: p25 0.0607 · median 0.1114.

## 5. target-seed free cap 감사

```
프레임당 합계        median 16 · max 24     (proposal 최대 3개 x 8)
proposal 당 unique   8 (38 proposal) · 7 (1)   <- 상한이 걸리는 단위
실측 paid_used       0
```

**K=8 은 무동작**이고, K=4 만 물리는데 protection 6/7 로 탈락한다 -> 이 축은 소진됐다.

## 6~8. subset · sweep · 선택

subset 22건(규칙 기반, manual pick 0). 1차 6 config 후 **fine 이 한 번도 평가하지
못했음**을 발견(일반 예산 검사를 같이 통과시킨 구현 결함) — 수정 후 확인 run 1회 추가
(총 7 config). p50 은 p25 의 상위집합이라 한 번으로 두 threshold 답을 얻었고,
p25 가 같은 3건을 회복하면서 trigger 1건과 8 eval 을 아껴 **K=8 · p25** 채택.

## 9. accepted recall

```
legacy accepted 30 유지     30 / 30    PASS
accepted 총계               31 -> 34
회복                        [29, 80, 136, 183]
```

## 10. explicit 품질 (paired, legacy 30)

```
지표                baseline    G1.6        기준            판정
────────────────────────────────────────────────────────────────
abs error median    0.0360      0.0360      <= base+0.01    PASS
abs error p95       0.1139      0.1139      <= base+0.02    PASS
metrics/visible/side 30/30      30/30       = 30/30         PASS
값이 바뀐 case      —           [18]       (개선 방향)
```

## 11. post-context

mode semantics 34/34 PASS. accepted 중 1건(pi 136)은 context 배치 0
(180회 시도·support 165 탈락) — 새로 회복된 controlled 프레임이고 controlled 의
semantics 계약은 explicit occluder 에 대한 것이라 gate 는 정당히 통과한다.
baseline 에 같은 사례 0건이므로 **회귀가 아니라 신규 사례**다.

## 12. locked77 runtime (77건 전체)

```
total            5,020 s -> 4,642 s  (-7.5%)   기준 <= 4,518 s   FAIL
  accepted 분     2,127 s -> 2,149 s  (+1.1%)
  rejected 분     2,892 s -> 2,492 s  (-13.8%)
explicit stage   3,496 s -> 3,191 s  (-8.7%)
fine stage       0 s -> 61 s
accepted median  45.7 s -> 45.6 s               기준 <= +10%      PASS
실패 context 낭비 31.8 s -> 31.5 s               기준 <= 40 s      PASS
```

## 13. score_callback (count)

```
reject count   2,026 -> 2,058  (+1.6%)   기준 <= 1,722   FAIL
```

gate 1,722 는 이 모집단의 baseline(2,026)보다 낮다. fine 은 near-miss 후보를
**추가로** 평가하므로 이 지표는 구조적으로 늘어난다 — 이번 두 메커니즘으로는 도달 불가.

## 14. candidate budget

```
누적 소진   434 -> 428     상한(EXPLICIT_CANDIDATE_LIMIT_PER_PROPOSAL) 무변경
```

## 15~24. G2c / G3

기준 5 에 따라 **미시작**. checkpoint10 · mixed100c · overlay 100 · exact20 ·
dataset-quality probe 전부 실행하지 않았다.

## 25. 전체 회귀

```
unit 919 passed(skip 0 fail 0) · integration 31 · golden 51 · registry ok=28
5k FrameSpec 938f387d 불변 · 5k proposal 3cd365ee 4,439 12/12 불변
active scene 8cb4109a 불변 · baseline 3종 records.jsonl SHA256 불변
public mask schema 무변경
```

## 26. READY_FOR_NEW_500_PILOT

```
false
```

## 27. git diff

```
_docs/history/.last-compact-resume.md              |   8 +-
 _docs/history/2026-08-01.md                        | 449 ++++++++++++
 _docs/history/changelog.md                         |   3 +
 scripts/data_prep/blender/run_v2_scene_logic.py    | 249 ++++++-
 scripts/data_prep/blender/scene_placement_v2.py    | 450 ++++++++++++
 .../blender/tests/test_scene_placement_v2.py       |  56 ++
 .../blender/tests/test_usable_completion_mode.py   |  66 +-
 .../tests/test_v2_pilot_resume_reproducibility.py  |  20 +
 scripts/data_prep/blender/v2_pipeline.py           |  50 ++
 scripts/data_prep/blender/v2_realize.py            | 781 +++++++++++++++------
 10 files changed, 1897 insertions(+), 235 deletions(-)
```

## 28. commit / push

```
commit = 0
push   = 0
```

---

# 마감 수치

```
지표                                     값
────────────────────────────────────────────────────────────────────────
target-seed selected cap                 8  (paid_used 0 — 무동작)
near-miss selected threshold             0.0607 (p25)
fine triggered / won / recovered         8 / 4 / 4
locked accepted recall (paired 30)       30 / 30
paired explicit median / p95  before     0.0360 / 0.1139
paired explicit median / p95  after      0.0360 / 0.1139
post-context regression                  0
locked runtime before / after            5,020 s / 4,642 s  (-7.5%)
explicit stage runtime before / after    3,496 s / 3,191 s
fine runtime                             61.2 s
score_callback count before / after      2,026 / 2,058
candidate budget exhausted before/after  434 / 428
checkpoint10 / mixed100c / overlay       미실행
A / C / runtime ratio (mixed100c)        미측정
exact20 mismatches                       미실행
dataset-quality RGB mismatch             미실행
unit fail / skip                         0 / 0  (919 passed)
integration fail / skip                  0 / 0  (31 passed)
golden fail / skip                       0 / 0  (51 passed)
5k digest change                         0
scene SHA change                         0
baseline modified                        0
public schema changed                    0
500 / 2k / 40k render                    0 / 0 / 0
model training / inference               0 / 0
commit / push                            0 / 0
```

# 남은 병목과 다음 제안

`score_callback` 은 여전히 주 실패 사유이고, **이번 두 메커니즘으로는 줄지 않는다**.

- **target-seed 축은 소진** — per-proposal 후보가 8개뿐이라 상한을 둘 여지가 없다.
- **fine 은 품질 손상 없이 4건을 회복하고 총시간을 7.5% 줄였지만**, near-miss 후보를
  추가로 평가하므로 `score_callback` count 는 오히려 늘어난다. count 기준 gate 와
  근본적으로 상충한다.

효율을 더 얻으려면 **후보를 더 잘 고르는 것이 아니라 후보 자체를 덜 만드는** 방향이
필요하다 — 목표 마스크로 proposal 자체를 사전 랭킹하거나, `corner_joint_pass`
(단독 차단 215건 · 조합 포함 1,300건 이상)를 배치 단계에서 미리 만족시키는 규칙.
이번 지시 범위 밖이라 **자동으로 시도하지 않았다**.
