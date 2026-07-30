# Stage 2-D1.1 §8 — registry 전환 before / after

BLOCKED_REFERENCE 4건은 "현재 코드·config 가 실제로 참조하기 때문에" Stage 2-D1 이
이동을 막은 것이다. 옮기기 전에 참조를 registry 기반으로 바꿨다.

## 신규 registry key 4개 (§8.1)

이름은 `legacy_1` 같은 무의미한 것을 쓰지 않고 **자료의 역할**로 정했다.

```
key                                       현재 값 (이동 전)
────────────────────────────────────────────────────────────────────────────────────
legacy_training_data_root                 data/pallet/archive/training_data
legacy_train_palletobj_v3_root            data/pallet/archive/train_palletobj_v3
legacy_train_palletobj_v3_post_v1_root    data/pallet/archive/train_palletobj_v3_post_v1
legacy_sandbox_parking_lot_scene          data/pallet/assets/scenes/production/
                                            blender_scene/_sandbox_parking_lot_check.blend
```

`archive_root` + relpath 로 처리하지 않고 명시적 key 를 둔 이유: 이 4개는 **여러 current
runtime 이 서로 독립적으로 참조**한다(특히 `legacy_training_data_root` 는 10곳).
relpath 조립을 각 소비자가 반복하면 이동 시 10곳을 다시 고쳐야 한다.

```
registry audit  ok=24 -> ok=28   missing=0 (변화 없음)
```

## Two-step transition (§8.2) — 1단계 완료

### 이동 전 (지금 상태)

키를 **현재 source 경로**로 등록하고 소비자를 키 조회로 바꿨다. 이 상태에서 코드는
동작하고 데이터는 아직 이동 전이다.

전환한 소비자 16곳 (`registry_transition.csv`):

```
config/default.yaml:53,54                    registry:legacy_training_data_root/{train,val}
config/stage3_selftrain.yaml:81,85           registry:legacy_training_data_root/{train,val}
scripts/train_dope.sh                        resolve_path() 신설 — yq 값을 registry 해석
scripts/self_training/self_train.py:590      _pdp.resolve_config_value() 경유
scripts/self_training/self_train.py:17        docstring 사용예 -> --resolve
scripts/data_prep/postprocess_v3.py:198,202  argparse default -> _pdp.get()
scripts/data_prep/visualize_pretrain.py:193  glob 경로 -> _pdp.get()
scripts/data_prep/visualize_inference.py:9,187  docstring + argparse default
scripts/data_prep/evaluate_on_val.py:12      docstring 사용예 -> --resolve
scripts/data_prep/isaac_sim/generate_all.sh  TRAIN_BASE 기본값 -> --key 조회
scripts/data_prep/blender/gen_palletobj_v1.py:4,569  docstring + save_as_mainfile 출력
```

### ★ config YAML 도 registry 참조로 바꿨다

YAML 이 경로 리터럴을 복사해 갖고 있으면 자료가 움직일 때 registry 와 config **두 곳**을
고쳐야 하고, 한쪽만 고치면 조용히 어긋난다. §8.2 는 "이동 후 config 를 다시 수정하지
않아도 동작해야 한다"고 요구한다. 그래서 값 자체를 참조로 만들었다.

```
train_dir: registry:legacy_training_data_root/train
```

해석기: `pallet_data_paths.resolve_config_value()` + CLI `--resolve`.
`registry:` 로 시작하지 않는 값은 **그대로 반환**한다 — 기존 리터럴 설정이 계속 동작한다
(하위호환). 소비자 두 곳(`train_dope.sh` 의 `resolve_path()` · `self_train.py`)이 이
해석기를 통과시킨다.

```
$ python scripts/data_prep/blender/pallet_data_paths.py       --resolve registry:legacy_training_data_root/train
E:\CODING\GitHub\FoundationPose\data\palletrchive	raining_data	rain

$ ... --resolve data/pallet/plain/literal
data/pallet/plain/literal                    (리터럴은 그대로)

$ ... --resolve registry:nope_key
해석 실패: pallet_paths 에 없는 키: 'nope_key'   exit 1
```

### 이동 후 (미실행)

`pallet_paths.yaml` 의 **키 값 하나만** final destination 으로 바꾸면 된다.
code/config 재수정 불필요.

```
legacy_training_data_root
  data/pallet/archive/training_data
  -> data/pallet/archive/legacy_datasets/noai_baked/training_data
legacy_train_palletobj_v3_root
  -> data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v3
legacy_train_palletobj_v3_post_v1_root
  -> data/pallet/archive/legacy_datasets/redistributable/train_palletobj_v3_post_v1
legacy_sandbox_parking_lot_scene
  -> data/pallet/archive/legacy_scenes/snapshots/_sandbox_parking_lot_check.blend
```

이전 key 값은 이 문서와 history 에만 남긴다 — current config 에 중복 보존하지 않는다.

## 전환 검증 (§8.2) [확인]

```
registry audit                    ok=28 missing=0 absent_optional=0
신규 키 4개 실제 해석              4/4 존재하는 경로로 resolve
registry: 참조 해석                train/val 모두 정상, 리터럴 통과, 없는 키 exit 1
옛 경로 직접 참조 (실행 경로)       0
  data/pallet/archive/training_data        0  (pallet_paths.yaml 정본 + resolver docstring 제외)
  data/pallet/archive/train_palletobj_v3   0
  _sandbox_parking_lot_check               0
canonical CURRENT broken ref       0
unit / integration / golden        745 / 31 / 51  (skip 0 fail 0)
postprocess_v3.py --help          registry default 로 정상 기동
```

## ★ 이동은 미실행 — hash 예산

전환은 끝났지만 실이동은 하지 않았다. 4건 16.14 GiB × 2 = **32.29 GiB** 로 §6 전역 상한
20 GiB 를 넘는다 (§17 중단 기준).

또한 D1-003(`_sandbox_parking_lot_check.blend`)은 **C2C 원장 구성원**이라 D11A 와 같은
successor chain 처리가 추가로 필요하다.

지금 상태의 이점: 참조가 이미 registry 를 통하므로 **이동은 순수하게 데이터 이동 +
키 값 1줄 변경**이 됐다. 코드 변경 없이 언제든 실행할 수 있다.
