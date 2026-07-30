# Stage 2-D1.2 — registry before / after

## 핵심

D1.1 이 registry 전환을 끝내 둔 덕분에, D1.2 의 이동은 **키 값 4줄 변경**으로 끝났다.
실행 표면(config·스크립트)은 **한 줄도 고치지 않았다** — 전부 `registry:` 참조이거나
`pallet_data_paths.py --key/--resolve` 호출이기 때문이다.

## 바뀐 키 4개 (`config/synthetic/pallet_paths.yaml`)

```
registry key                            before                              after
──────────────────────────────────────────────────────────────────────────────────────────
legacy_sandbox_parking_lot_scene        assets/scenes/production/           archive/legacy_scenes/
                                        blender_scene/                      snapshots/
                                        _sandbox_parking_lot_check.blend    _sandbox_parking_lot_check.blend
legacy_train_palletobj_v3_root          archive/train_palletobj_v3          archive/legacy_datasets/
                                                                            redistributable/train_palletobj_v3
legacy_training_data_root               archive/training_data               archive/legacy_datasets/
                                                                            noai_baked/training_data
legacy_train_palletobj_v3_post_v1_root  archive/train_palletobj_v3_post_v1  archive/legacy_datasets/
                                                                            redistributable/train_palletobj_v3_post_v1
```

(경로는 전부 `data/pallet/` 기준. 기계 판독용은 `registry_transition.csv`.)

## 이 키들을 쓰는 곳 — 전부 그대로 동작

```
파일                                          형태
────────────────────────────────────────────────────────────────────────────────────
config/default.yaml:55-56                     registry:legacy_training_data_root/train
                                              registry:legacy_training_data_root/val
config/stage3_selftrain.yaml:82,86            registry:legacy_training_data_root/train
                                              registry:legacy_training_data_root/val
scripts/self_training/self_train.py:17        --resolve registry:legacy_training_data_root/train
scripts/data_prep/isaac_sim/generate_all.sh:46  --key legacy_training_data_root
scripts/train_dope.sh                         resolve_path() -> --resolve
```

`registry:<key>[/sub]` 는 `resolve_config_value()` 가 푼다. registry 값이 아닌 문자열은
그대로 통과시켜 하위 호환을 유지한다.

## 검증

```
python scripts/data_prep/blender/pallet_data_paths.py --audit
-> ok=28  missing=0  absent_optional=0
```

28개 키 전부 실재하는 경로를 가리킨다. `registry_transition.csv` 의
`source_exists_now = False` / `destination_exists_now = True` 로 옛 경로가 남아 있지
않음도 확인했다(4/4).

## ★ 이동 전 재측정에서 잡은 것

처음에는 D1.1 CSV 의 `current_runtime_test_refs` 를 그대로 가져다 썼다. 그 값은
**registry 전환 이전**에 잰 것이라 4건 전부 LIVE_REF 문제로 잡혔다 — 오탐이다.
지금 실행 표면을 다시 재서 고쳤다.

```
재측정 방식: 실행 표면에서 source 경로를 리터럴로 가리키는 곳을 센다.
             registry 정본(config/synthetic/pallet_paths.yaml)과
             resolver docstring(pallet_data_paths.py)은 제외 — 그 둘이 경로를 소유한다.

결과: 3건 -> 0
      1건 -> 진짜였다: generate_all.sh:42 의 낡은 주석이 옛 경로를 적고 있었다 -> 갱신
```

"이전 단계 CSV 에 있으니까 맞겠지"로 넘겼으면 이동 자체를 못 했거나(오탐 4건),
진짜 stale 주석 1건을 놓쳤다.
