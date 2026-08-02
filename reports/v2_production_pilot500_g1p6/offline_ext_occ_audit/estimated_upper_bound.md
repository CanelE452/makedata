# ext_occ=0 조기 종료 — offline 상한 추정

렌더 0회.  기존 record 의 candidate log 만 사용했다.

## 입력

```
locked77     data/pallet/runs/diagnostics/_locked77_g1p6/replay_records.jsonl (records 77 · candidate log 77)
smoke100b    data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public/records.jsonl (records 100 · candidate log 30)
```

## 관측

```
분석한 proposal                          231
  전 후보가 ext_occ=0                     53
  수락 후보를 가진 proposal                79
  ext_occ=0 이후 ext>0 으로 회복           36   <- 조기 종료의 false negative 후보
```

회복이 처음 일어난 stage 분포:

```
  target-seed              30
  primary                  3
  corner-contact-refine    3
```

## stage 별 "여기까지 전부 ext=0 이면 포기" 규칙의 손익

```
cutoff stage             발동    false_neg   safe_stop   절약 후보평가   안전
────────────────────────────────────────────────────────────────────────────────
preprobe                     89          33          56           1082   아니오
primary                      52           0          52             88   예
prealign-primary             41           0          41              0   예
target-seed                  47           3          44            490   아니오
gate-overlap-refine           0           0           0              0   예
fine                          0           0           0              0   예
rescue                        4           0           4              0   예
corner-contact-refine         9           0           9              9   예
```

## 판정

```
EXT_OCC_EARLY_TERMINATION_READY = True
가장 이른 안전 stage             = primary
```

**이번 500 pilot 에는 적용하지 않는다.**  generator 코드도 feature flag 도 바꾸지
않았다.  이 문서는 다음 설계 논의를 위한 자료다.
