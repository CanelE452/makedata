# G1.7 §4 — 코드 변경 전 기준선 회귀

모두 **코드 변경 전** 상태에서 실행했다.  locked77 replay 기록·baseline dataset·
기존 report 는 읽기만 했다.

```
항목                          결과                                   판정
────────────────────────────────────────────────────────────────────────
A registry --audit            ok=28  missing=0                       PASS
B unit                        919 passed · 0 failed · 0 skipped      PASS
C local integration           31 passed · 0 failed · 0 skipped       PASS
D golden overlay              51 passed · 0 failed · 0 skipped       PASS
E1 5k FrameSpec               accepted 4,313 / rejected 687          PASS
                              digest 938f387d (기대 938f387d)
E2 5k proposal                accepted 4439 · checks 12/12             PASS
                              digest 3cd365ee (기대 3cd365ee)
F active scene (no-render)    SHA 8cb4109a                                 PASS
                              images missing 0 · absolute 0
                              node image missing 0 · Dist_ rows 209
```

## 잠금 대상 (읽기 전용, 이번 단계에서 수정 금지)

```
dataset                                          RGB    overlay  records.jsonl sha256
──────────────────────────────────────────────────────────────────────────────────────
v2_pilot_2k_seed7000_public                      1449        0    d04283b279dca43d…
v2_mode_semantics_smoke100_seed7000_public        100        0    269a48a9f3f00c8d…
v2_mode_semantics_smoke100b_seed7000_public       100      100    bf682c0aab51f96d…
```

locked77 benchmark:

```
manifest      35478cbee718d791
  cases 77 (accepted 30 · expensive reject 47) · seed 7000
G1.6 replay   f682bf6430d5ff7d
  records 77
```

**판정: BASELINE_REGRESSION_PASS = true**
