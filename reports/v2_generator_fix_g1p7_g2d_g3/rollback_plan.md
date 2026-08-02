# G1.7 rollback plan

## 현재 상태 — 되돌릴 것이 사실상 없다

constraint-directed rescue 는 **feature flag 아래 기본 OFF** 로 들어갔다.
production 경로(`run_v2_scene_logic.py` 기본 인자)로 실행하면 G1.6 과 동일하게 동작한다.

```
SP2.CONSTRAINT_RESCUE_DEFAULT_MODE = "off"
v2_realize.SEARCH_TUNING["constraint_rescue_mode"] = "off"
v2_realize.py:2319   and SEARCH_TUNING["constraint_rescue_mode"] != "off"
```

`constraint_rescue_plan(...)` 를 기본 인자로 부르면 `evaluations=[]`, `beam=[]` 을
반환한다 (테스트 `test_feature_defaults_to_off` 로 고정).

## 즉시 무력화 (코드 수정 없이)

CLI 인자를 **빼기만** 하면 된다.

```
--constraint-rescue-mode side_g1     <- 이 인자를 주지 않으면 off
--constraint-rescue-beam N
--constraint-rescue-eval-max N
--constraint-rescue-category-max N
```

## 코드까지 되돌려야 할 때

변경 전체가 `offline_closure/experimental_rescue.patch` (2,574줄) 에 보존돼 있다.

```
git apply -R reports/v2_generator_fix_g1p7_g2d_g3/offline_closure/experimental_rescue.patch
```

되돌리면 함께 사라지는 것 (되돌리기 전에 확인):

- `scene_placement_v2.py` — constraint vector · Pareto · rescue seed 순수 함수
- `v2_realize.py` — `constraint-rescue` stage · record 17필드 · `set_search_tuning` 확장
- `run_v2_scene_logic.py` — CLI 4개 · record 전파 · manifest 5컬럼
- `replay_controlled_cases.py` — CLI 4개 · `wall_time_definition.json` 계측

**금지**: `git reset` · `git checkout` 으로 변경 폐기 · `git stash`.
(이번 단계에서 한 번도 사용하지 않았다.)

## 되돌리지 말아야 할 것

아래는 rescue 와 무관하게 **그 자체로 가치가 있는 산출물**이다.

| 항목 | 이유 |
|---|---|
| `g1p7/acceptance_contract.*` | 코드에서 직접 읽은 수락 계약 정본 |
| `g1p7/binding_*` · `constraint_margins.md` | 실패 원인의 정량 지도 |
| `offline_closure/failure_atlas/` | 다음 설계의 입력 |
| `tests/test_constraint_rescue.py` | 계약·게이트 불변을 지키는 회귀 테스트 40개 |
| `replay_controlled_cases.py` 의 wall-time 계측 | §13 정의 검증에 필요 |

특히 `test_rescue_does_not_change_acceptance_thresholds` 와
`test_public_mask_profile_unchanged` 는 rescue 를 되돌려도 남겨야 한다 —
acceptance 임계와 public mask schema 가 조용히 바뀌는 것을 막는다.

## 검증된 불변 (2026-08-02)

```
5k FrameSpec digest      938f387d (4,313)      불변
5k proposal digest       3cd365ee (4,439,12/12) 불변
active scene SHA         8cb4109adc6d…          불변
baseline dataset 3종     records.jsonl SHA256   불변
locked77 G1.6 replay     replay_records.jsonl   불변
public mask schema       m0/m4 → amodal/visible 불변
unit / integration / golden   959 / 31 / 51     fail 0 · skip 0
commit / push                                    0 / 0
```
