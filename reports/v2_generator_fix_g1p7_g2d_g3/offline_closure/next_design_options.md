# G1.7 §24.3 — 다음 설계 후보 (설계안만, 구현 금지)

근거 없는 새 heuristic 을 구현하지 않는다.  아래는 **설계안**이며, 각 후보는 먼저
소형 판별 실험으로 전제를 확인한 뒤에만 본 구현을 검토한다.

공통 전제 (G1.7-A/B 실측):

```
필요 절감           475.4 s   (4,754.4 -> 4,279.0)
엄격 near-miss 상한  263.8 s   -> 단독으로는 도달 불가
SIDE 축              연속 margin 없음 · rejected 43건 중 target side 미달성 21건
G2 실패 1,152건 중   1,028건이 ext_occ=0 (딱 1개만 더 가리면 되는 상태)
hard physical        acceptance 도달 전 탈락 732/2,918 (25.1%)
```

핵심 관찰: **rescue 는 실패한 뒤에 도는 단계라 성공하지 못하면 비용이 순증한다.**
따라서 다음 축은 "실패 후보를 더 잘 고치기"가 아니라 **"실패 후보를 애초에 만들지 않기"**
이거나 **"실패를 더 일찍 확정하기"** 다.

---

## 후보 1 — side-feasibility prefilter (배치 前 차단)

- **binding category**: ONE_MISS_SIDE (734.0 s · rejected wall 의 28.7%)
- **현재 rescue 로 안 되는 이유**: `_occlusion_side_from_masks` 는 가려진 픽셀
  centroid 의 화면 위치로 side 를 정하고 **bottom 을 가장 먼저** 검사한다.
  occluder 는 support 제약으로 접지해야 해 화면에서 세로 이동이 자유롭지 않다.
  국소 u/v/depth offset 으로 side **범주**를 바꾸기 어렵다 (실측: rescue 성공률 낮음).
- **변경 범위**: `controlled_prefilter_reason` 에 조건 1개 추가 — proposal 의 화면
  투영 bbox 와 팔레트 amodal bbox 의 삼등분 경계를 비교해, target side 삼등분과
  교집합이 0 인 (asset, side) 조합을 **탐색 시작 전에** 버린다.  solver·gate·budget
  불변, prefilter 만 수정.
- **expected benefit**: side 로 막힌 case 의 탐색 자체를 건너뛴다.  상한은
  해당 case 들의 explicit 탐색 시간 (locked77 기준 최대 734.0 s 중 탐색분).
- **expected risk**: 지금 accepted 인 프레임을 잘못 버리면 recall 손실.
  prefilter 는 이미 winner 49/49 재현 baseline 이 있으므로 같은 방식으로 검증 가능.
- **필요 렌더**: 0 (offline). 판별 실험은 기존 candidate log 로 가능.
- **먼저 할 소형 판별 실험**: locked77 의 accepted 34건 전체에 대해 이 조건을
  적용했을 때 **한 건도 버려지지 않는지** 확인 (offline, 렌더 0).
- **숫자 중단 기준**: accepted 34건 중 1건이라도 버려지면 폐기.
  버려지지 않으면, rejected side case 중 몇 %가 조기 차단되는지 측정해
  50% 미만이면 폐기.

---

## 후보 2 — ext_occ=0 조기 종료 (실패를 더 일찍 확정)

- **binding category**: ONE_MISS_G2 (227.5 s) + G2 를 포함한 조합
- **현재 rescue 로 안 되는 이유**: G2 는 국소 이동으로 고칠 여지가 가장 큰 축인데
  (1,028/1,152 이 ext_occ=0, margin −1), rescue 가 **탐색 끝**에 붙어 있어
  이미 예산을 다 쓴 뒤에야 시도한다.  이득이 "남은 proposal 건너뛰기"뿐이다.
- **변경 범위**: proposal 단위 조기 포기 규칙 — 한 proposal 의 coarse 단계에서
  평가된 후보가 모두 `ext_occ == 0` 이고 `corner_threshold_gap` 이 크면
  (= occluder 가 팔레트 코너 근처에 전혀 못 감) 남은 stage 를 건너뛰고 다음
  proposal 로 넘어간다.  acceptance gate 불변, 후보 예산 상한 불변.
- **expected benefit**: 가망 없는 proposal 의 refine/feedback/rescue 단계를 생략.
  실패 case 의 탐색 꼬리를 자르므로 **절감이 순증**이다 (rescue 와 반대).
- **expected risk**: 늦게 성공하던 proposal 을 조기 포기하면 recall 손실.
- **필요 렌더**: 0 for 판별, locked77 1회 for 확인.
- **먼저 할 소형 판별 실험**: locked77 accepted 34건의 **승리 후보가 몇 번째
  stage 에서 나왔는지** 집계 (`explicit_selected_stage` 이미 존재).  승리
  후보가 coarse 이후 stage 에서 나온 비율이 높으면 이 규칙은 위험하다.
- **숫자 중단 기준**: accepted 34건 중 조기 포기 규칙에 걸리는 게 1건이라도
  있으면 임계를 좁히고, 좁혀서 0건이 안 되면 폐기.

---

## 후보 3 — hard-physical 후보를 만들지 않는 배치 샘플러

- **binding category**: 전 category 공통 (acceptance 도달 전 탈락 732/2,918 = 25.1%,
  support 463 · camera_clearance 157 · collision 112)
- **현재 rescue 로 안 되는 이유**: rescue 는 hard physical fail 후보를 beam 에서
  제외하므로 이 25.1% 를 전혀 건드리지 않는다.  이 후보들은 만들어지고 버려진다.
- **변경 범위**: 후보 offset 을 적용하기 전에 support/clearance 를 **해석적으로**
  선검사한다 (바닥 높이·카메라 거리는 이미 알고 있는 값).  통과 못 할 offset 은
  평가 자체를 건너뛴다.  gate·예산·분포 불변.
- **expected benefit**: 후보 평가 수를 최대 25% 줄인다.  단, 이들은 저해상도
  렌더 전에 탈락하는 값싼 후보일 수 있으므로 **시간 절감은 개수 절감보다 작다**.
- **expected risk**: 낮음 (gate 를 바꾸지 않고 확실히 실패할 후보만 제외).
  다만 해석적 선검사가 실제 검사와 불일치하면 후보를 잘못 버릴 수 있다.
- **필요 렌더**: 0 for 판별.
- **먼저 할 소형 판별 실험**: hard physical 로 탈락한 732건이 **전체 explicit
  시간의 몇 %** 를 썼는지 먼저 측정한다.  후보 단위 runtime 이 없으므로
  instrumentation-only patch 가 필요하다 (§6 에서 미실행으로 남겨둔 항목).
- **숫자 중단 기준**: 그 비중이 explicit 시간의 15% 미만이면 폐기
  (필요 절감 475.4 s 에 기여할 수 없다).

---

## 권장 순서

1. **후보 2** (조기 종료) — 유일하게 절감이 순증하는 구조. 판별 실험이 offline 이고 즉시 가능.
2. **후보 1** (side prefilter) — 가장 큰 category 를 겨냥. 판별 실험도 offline.
3. **후보 3** — 판별에 instrumentation 이 필요해 비용이 가장 크다.

세 후보 모두 **이번 단계에서 구현하지 않았다.**
