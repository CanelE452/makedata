# G1.7 §7 — candidate geometry 중복 제거

## canonical geometry key

```
asset identity | occluder_side_target | center(x,y,z) | yaw_rad
              | u_offset | v_offset | depth_offset | yaw_offset
```

float 는 solver 가 실제로 다루는 분해능인 **1e-6** (m / rad) 로만 정규화했다.
임의의 소수점 자리로 서로 다른 geometry 를 합치지 않았다.

- `scale` 은 키에 넣지 않았다 — 현재 solver 에 explicit occluder scale 탐색축이
  없어 항상 동일하므로, 넣어도 구분력이 없고 안 넣어도 서로 다른 geometry 가
  합쳐지지 않는다.
- `center` 와 offset 을 **둘 다** 넣었다.  offset 은 seed 대비 상대값이라
  stage 가 다르면 같은 절대 위치가 다른 offset 으로 표현될 수 있다.

## 결과

```
지표                          값
──────────────────────────────────────
raw candidate                  2918
unique geometry                2790
duplicate                       128  (4.4%)
stage-crossing duplicate        128  (duplicate 의 100%)
```

중복 128 건은 **전부** stage-crossing 이다 — 즉 같은 geometry 를 stage 이름만
바꿔 다시 평가한 경우다.  같은 stage 안에서의 중복 평가는 0건이다.

constraint 통계(§8-§11)는 모두 **unique geometry 기준**으로 집계했다.

case 단위 상세는 `candidate_dedup_audit.csv` 에 있다.
