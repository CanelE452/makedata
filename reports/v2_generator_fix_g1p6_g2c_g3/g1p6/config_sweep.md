# §6 mechanism config sweep + 설정 선택

subset 22건 · baseline = 현재 채택 G1.5 · Blender 는 항상 1개만 실행

## 1. 1차 sweep (6 config)

```
config        acc  prot   qual  ctx   runtime  sc_rej evals budget fine(t/e/w) ts_free/paid
----------------------------------------------------------------------------------------------
baseline_g1p5   7  7/7    OK    OK      1339.0    616   904    143   0/0  /0      0/0
k12_p25         7  7/7    OK    OK      1322.9    616   904    155   4/0  /0    311/0
k12_p50         7  7/7    OK    OK      1310.0    616   904    159   5/0  /0    311/0
k4_p25          6  6/7    OK    OK      1115.5    515   782    182   5/0  /0    156/155
k4_p50          6  6/7    OK    OK      1089.1    515   782    186   6/0  /0    156/155
k8_p25          7  7/7    OK    OK      1333.0    616   904    155   4/0  /0    311/0
k8_p50          7  7/7    OK    OK      1310.6    616   904    159   5/0  /0    311/0
```

## 2. ★ 1차 sweep 이 실제로 측정하지 못한 것 두 가지

### (a) target-seed 상한은 proposal 단위이고 실제 개수는 8이다

```
proposal 당 unique target-seed 후보 수   8 (38 proposal) · 7 (1 proposal)
```

§2 보고서의 'free eval median 16 · max 24' 는 **프레임당 합계**(proposal 최대 3개 x 8)였다.  상한은 proposal 단위로 걸리므로 **K=8·K=12 는
무제한과 동일**(paid 0)하고 물리는 것은 K=4 뿐인데, K=4 는 protection 6/7 로
탈락한다 (proposal 113 손실).

### (b) fine refinement 이 한 번도 평가하지 못했다

```
1차 sweep 전 config   fine_triggered 4~6 · fine_eval_count 0 · fine_won 0
```

구현 결함이었다 — fine 단계도 일반 예산 검사(`bounded_candidate_offsets`)를
통과하게 돼 있어, **예산이 소진돼 실패한 프레임(=fine 이 필요한 바로 그
프레임)에서 항상 0개**를 평가했다.  fine 은 자체 상한(FINE_MAX_EVALS=8)만
적용하도록 고치고 테스트로 고정했다.  따라서 1차 sweep 의 p25/p50 비교는 무효다.

## 3. 수정 후 확인 run (1회 추가, 총 7 config)

p50 은 p25 의 **상위집합**이라 한 번만 돌리면 두 threshold 의 답이 모두 나온다.

```
run                acc  protection  runtime   sc_rej  budget  fine t/e/w
--------------------------------------------------------------------------
baseline_g1p5        7  7/7          1339.0     616     143   0/0/0
k8_p50 (버그)        7  7/7          1310.6     616     159   5/0/0
k8_p50 (수정)        9  7/7          1372.9     633     137   5/34/3
```

```
fine 발동 case      evals  margin before -> after      won   p25 대상
--------------------------------------------------------------------------
pi 18               6   -0.0134 -> +0.0201   True  True
pi 29               6   -0.0564 -> +0.0981   True  True
pi 136              6   -0.0388 -> +0.0055   True  True
pi 184              8   -0.1106 -> -0.1582   False False
pi 237              8   -0.0488 -> -0.1217   False True
```

**회복 2건** [29, 136] · 손실 없음

## 4. 선택

```
target_seed_free_cap        8      (per-proposal 최대가 8이라 물리는 최소 상한)
near_miss_gap_threshold     0.0607 (p25)
fine_max_evals              8
fine candidates per case    1
```

p25 는 p50 과 **같은 3건을 회복**하면서 trigger 1건(pi 184, margin -0.1106)과 그 8 eval 을 아낀다.

선택 순서(§6): protection recall -> explicit quality -> post-context ->
total runtime -> score_callback -> eval 수.  protection/quality/post-context 는
K>=8 의 모든 config 가 통과했고, 그 뒤 순서에서 p25 가 p50 을 이긴다.

