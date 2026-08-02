# G1.7 §9 — case-level binding signature

locked77 전 case 를 **unique geometry 후보** 기준으로 분류했다.

## primary_binding_signature

최소 violation 수로 정하고, 동수면 §9 대로 **deterministic constraint name
순서**로 tie-break 했다 (빈도순·runtime 영향순이 아니다).  이 규칙 때문에 G1-only
후보와 side-only 후보를 함께 가진 case 는 `ONE_MISS_G1` 으로 라벨링된다 —
해당 case 가 side 로 막혔다는 뜻이 아니다.  관측된 모든 유형은
`all_actionable_signatures` 열에 그대로 남겼다.

```
signature                     cases
──────────────────────────────────────
ACCEPTED                        36
MULTI_CONSTRAINT                11
ONE_MISS_G1                     10
ONE_MISS_SIDE                   10
ONE_MISS_G2                      3
TWO_MISS_G1_SIDE                 3
TWO_MISS_SIDE_TARGET             2
ONE_MISS_TARGET                  2
```

## case_class (§9 의 나머지 두 분류 — primary 와 직교하는 축)

```
ACCEPTED                                          34
BUDGET_EXHAUSTED_WITH_ACTIONABLE_CANDIDATE        32
NO_FEASIBLE_CANDIDATE_FOUND                       11
```

- `HARD_PHYSICAL_ONLY` **0건**.  모든 rejected case 는 acceptance 를 실제로
  평가받은 후보를 최소 1개 이상 가지고 있었다.
- `BUDGET_EXHAUSTED_WITH_ACTIONABLE_CANDIDATE` 가 rejected 43건 중 32건.
  후보 예산을 다 쓰고 끝났지만 4/5 또는 3/5 를 만족하는 후보가 있었다.

## rejected 가 아닌데 signature 가 ACCEPTED 인 2건

case 201·229 는 explicit solver 가 **성공**했고 `score_accept=True` 후보를
가졌지만, frame 단위 gate 에서 탈락했다 [확인]:

```
case 201  usable_reject_reasons = ['gate_fail:G3']
case 229  usable_reject_reasons = ['gate_fail:G5']
```

즉 explicit 제약이 막은 것이 아니다.  두 case 의 153.1 s 는 어떤 explicit rescue
로도 회수할 수 없으므로 rescue 대상 분모에서 제외해야 한다.

상세: `binding_cases.csv` (case 단위) · `binding_candidates.csv` (후보 단위)
