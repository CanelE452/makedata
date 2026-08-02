# Phase G1.7 — binding-constraint 감사 + constraint-directed rescue

**결론: local rescue 는 accepted 품질을 완벽히 보존하지만 CASE_WALL_TIME_S 를 줄이지
못하고 늘린다. §4 micro-gate 실패로 locked77·G2d·G3 를 실행하지 않고 OFFLINE_CLOSURE 로
마감했다. commit 0 · push 0 · 실렌더 0.**

전체 결과 요약은 `overnight/final_morning_summary.md` 를 먼저 읽으면 된다.

## 1. 중심 질문과 답

> "실패 case 에서 실제로 막는 제약이 무엇이며, 그 제약에 맞춘 소규모 rescue 가
> accepted 품질을 보존하면서 end-to-end wall time 을 충분히 줄이는가?"

- **무엇이 막는가**: SIDE(28.7%) · G1(25.5%) · MULTI(16.5%) · G2(8.9%) 순.
  `HARD_PHYSICAL_ONLY` 는 0건이다.
- **품질을 보존하는가**: **예.** protection recall 11/11, paired explicit
  median 0.0573 불변, post-context regression 0.
- **wall time 을 줄이는가**: **아니오.** Config A −129.2 s · Config B −149.1 s
  (음수 = 증가). 필요량은 +211.5 s 였다.

## 2. 판정

```
게이트                                     기준           실측                판정
──────────────────────────────────────────────────────────────────────────────────
§11 rescue readiness A / B                >= 50%         54.2% / 70.6%       PASS
§12 품질 gate 1-3 (recall·품질·post-ctx)   회귀 0         회귀 0              PASS
§4  micro-gate SIDE/G1 추가 절감           >= +211.5 s    A -129.2 / B -149.1  FAIL
§13 locked77                               <= 4,279.0 s   미실행               N/A
──────────────────────────────────────────────────────────────────────────────────
G1P7_LOCKED_PASS                false (미실행)
G2D_MIXED100_PASS               false (미실행)
G3_REPRODUCIBILITY_PASS         false (미실행)
READY_FOR_NEW_500_PILOT         false
OFFLINE_CLOSURE_COMPLETE        true
```

## 3. 왜 실패했는가 — 구조적 이유

rescue 는 기존 탐색이 실패한 **뒤에** 붙는 단계다.

- 성공하지 못하면 그 비용이 **순증**한다 (실측 trig 12 / won 1).
- 성공해도 이득은 "남은 proposal 을 건너뛴 만큼"으로 제한된다
  (`EXPLICIT_PROPOSAL_SEARCH_LIMIT=3`, `v2_realize.py:2295-2308`).
- 그래서 예산을 키운 Config B 가 **더 나쁘다**.

이 결론은 실행 **전에** 계산한 절감 상한과 일치한다 — 엄격 near-miss 상한
263.8 s < 필요 475.4 s (`g1p7/rescue_readiness.md`).

## 4. 핵심 발견

1. **SIDE 는 국소 이동으로 고칠 수 없다.** `_occlusion_side_from_masks`
   (`v2_realize.py:3516`) 는 **가려진 픽셀 centroid** 의 화면 위치로 side 를 정하고
   **bottom 을 가장 먼저** 검사한다. occluder 는 support 제약으로 접지해야 해
   화면에서 세로로 자유롭게 못 움직인다.  SIDE actionable 11건 중 target side 를
   한 번도 달성하지 못한 case 가 **7건**.
2. **G2 는 고칠 여지가 가장 크지만 rescue 의 위치가 나쁘다.** G2 실패 1,152건 중
   **1,028건이 `ext_occ=0`** — 딱 1개만 더 가리면 되는 상태인데, rescue 가 탐색
   **끝**에 있어 예산을 다 쓴 뒤에야 시도한다.
3. **acceptance 도달 전 탈락이 25.1%** (support 463 · camera_clearance 157 ·
   collision 112). rescue 는 이 구간을 아예 건드리지 않는다.
4. **case 201·229 는 explicit 이 성공했는데 frame gate 에서 죽었다**
   (`gate_fail:G3` / `gate_fail:G5`). explicit rescue 의 분모가 아니다.

## 5. 방법론적으로 지킨 것

- acceptance 계약을 **기억이 아니라 코드에서** 확정 (`v2_realize.py:1838-1843`).
  `score` 에는 임계가 없고, G1/G2 는 정수 margin 이며, None 은 pass 가 아니다.
- **instrumentation replay 를 하지 않았다** — 기존 candidate log 로 충분함을 확인
  (§6 요구 23항목 중 20개 존재, `replay_wall_s` 합 4,754.3 s = baseline 4,754.4 s).
- **§13 wall-time 정의를 검증**했다. `replay_wall_s` 는 flush 를 제외하지만 실측
  오버헤드가 24건에 0.03 s 라 baseline 비교 가능성을 위해 **정의를 바꾸지 않고**
  차이만 `wall_time_definition.json` 에 기록했다.
- 같은 case 를 category 별로 **중복 합산하지 않았다** (SIDE∪G1 = 20 case,
  단순합 1,430.9 s 가 아니라 1,385.2 s).
- 실행 중 발견한 내 구현 결함(seed 부호 추측)을 **부분 결과를 보고 손보지 않고**
  전체 run 을 끝낸 뒤 수정했고, 수정 전/후를 각각 24건 replay 해 **결함이 결론을
  만들지 않았음을 분리 측정**했다.

## 6. 산출물

```
preflight/          baseline.{md,json} · locks · code hashes · 5k dryrun
g1p7/               acceptance_contract · candidate_schema_audit · candidate_dedup_audit
                    constraint_margins · binding_{cases,candidates,runtime,summary}
                    rescue_readiness · mechanism_subset · mechanism_{compare,gate}
                    mech_prefix/ (부호 수정 전 trial)
overnight/          overnight_state.json · overnight_log.txt · commands.jsonl
                    final_regression.json · final_morning_summary.md · 3개 replay 로그
offline_closure/    failure_atlas/ · rescue_upper_bound.md · next_design_options.md
                    experimental_rescue.patch (2,574줄)
rollback_plan.md
```

## 7. 다음 한 가지

`offline_closure/next_design_options.md` **후보 2 (ext_occ=0 조기 종료)** 의
**offline 판별 실험**. 렌더 0회로 가능하다 — locked77 accepted 34건의
`explicit_selected_stage` 를 집계해 승리 후보가 coarse 이후 stage 에서 나온 비율을 본다.
비율이 높으면 이 방향도 폐기해야 한다.

이것이 **절감이 순증하는 유일한 구조**다: rescue 는 실패 시 비용이 순증하지만,
조기 종료는 실패 시 비용이 **감소**한다.

## 8. 불변 확인 (2026-08-02)

```
unit 959 · integration 31 · golden 51        fail 0 · skip 0
registry ok=28 missing=0
5k FrameSpec 938f387d (4,313) / proposal 3cd365ee (4,439, 12/12)   불변
active scene 8cb4109adc6d…                                        불변
baseline dataset 3종 records.jsonl SHA256                          불변
locked77 G1.6 replay_records.jsonl                                 불변
public mask schema (m0/m4 → mask_amodal/mask_visible)              불변
blender process 0 · HEAD 불변 · commit 0 · push 0
500/2k/40k 렌더 0 · 모델 학습 0 · 추론 0 · ADD/ADD-S 0
```
