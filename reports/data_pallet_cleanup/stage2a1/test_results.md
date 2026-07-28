# §8 테스트 결과

Blender 렌더 0건, 데이터 생성 0건, 데이터 이동 0건.

## 8-A. Clone-safe registry unit [확인, 실행함]

`config/synthetic` + `scripts/` 만 복사하고 **`data/` 를 아예 만들지 않은** 임시 트리에서 실행.

```
$ ls <clone_sim>
config
scripts

$ python -m pytest scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py -q -rs
41 passed in 1.05s        # skip 0, network 0
```

트랜잭션·mask 테스트까지 함께 넣은 clone 시뮬레이션:

```
$ python -m pytest scripts/data_prep/blender/tests -q -rs      # clone_sim2
109 passed, 2 skipped in 2.32s
  SKIPPED test_manage_pallet_data_layout.py:459  Stage 2-A 원장이 없는 환경 (새 clone)
  SKIPPED test_manage_pallet_data_layout.py:476  Stage 2-A 원장이 없는 환경 (새 clone)
```

두 skip 은 **Stage 2-A 실이동 원장(clone 에 없는 gitignored 산출물)을 읽는 가드 테스트**다.
`-rs` 로 사유가 드러나는 명시적 skip 이고, 이 workstation 에서는 둘 다 실행된다(아래 8-E skip 0).

## 8-B. Local registry integration [확인, 실행함]

```
$ PALLET_DATA_INTEGRATION=1 python -m pytest scripts/data_prep/blender/integration_tests -q -rs
20 passed in 0.19s        # skip 0
```

- registry audit missing 0
- distractor pool **정확히 209**
- production scene + 동반 textures(같은 폴더) 실재
- golden reference `overlay/000000.png` 실재
- `blender_config.WOOD/FLOOR_TEXTURE_DIR` == registry 값
- registry 가 빈 `assets/` 를 가리키지 않음 / `assets/` 에 README 외 파일 없음

환경변수 없이 실행하면 수집 시점 RuntimeError 로 중단(조용한 skip 아님) [확인]:

```
$ python -m pytest scripts/data_prep/blender/integration_tests/... -q
ERROR ... PALLET_DATA_INTEGRATION=1 을 설정하고 실행하세요.
1 error in 0.10s
```

## 8-C. Transaction unit [확인, 실행함]

```
$ python -m pytest scripts/data_prep/blender/tests/test_manage_pallet_data_layout.py -q -rs
39 passed        # skip 0 (이 workstation)
```

temp directory 전용. selective/all hash, path escape(prefix collision 포함), collision,
verify(변조·결측·추가 탐지), rollback(복원·충돌 중단·역순), legacy manifest 호환,
부분 실패 후 상태 보존까지 포함. 실제 Stage 2-A manifest 는 읽기만 하고 수정하지 않는다
(전체 사이클을 돌린 뒤 원장 sha256 불변을 단언하는 가드 테스트 포함).

## 8-D. Mask layout fixtures [확인, 실행함]

```
$ python -m pytest scripts/data_prep/blender/tests/test_mask_layout_compatibility.py -q
31 passed        # skip 0
```

```
검사                                        결과
────────────────────────────────────────────────────────────────────────────
analyze public                              profile=public, stages=[m0,m4], 결측 오판 0
analyze full-audit                          profile=full-audit, stages=[m0..m4], 회귀 없음
determinism public/public                   compared=[m0,m4], deterministic=True
determinism full/full                       compared=[m0..m4], deterministic=True
determinism public/full (기본)               errors=[mask_profile_mismatch], deterministic=False
determinism public/full (--allow-...)       compared=[m0,m4], partial=True, deterministic=False
public 에서 M1~M3 결측 오판                   0건 (source_files_missing 비어 있음)
0.0 과 None 구분                             f_total=0.0 유지 / f_static 등은 None
```

CLI end-to-end 로도 확인했다(임시 fixture, Blender 없음):

```
profile=public      exit=0  mask 컬럼 ['m0','m4']         source_files_missing {''}
profile=full-audit  exit=0  mask 컬럼 ['m0'..'m4']        source_files_missing {''}
```

## 8-E. 기존 로컬 전체 suite [확인, 실행함]

```
$ python -m pytest scripts/data_prep/blender/tests -q -rs
566 passed in 82.76s        # skip 0, fail 0
```

### 개수 변동 회계

```
항목                                              수
────────────────────────────────────────────────────────
Stage 2-A 기준                                   477
  - 제거: tests/test_pallet_data_paths.py         -22   (분리·이관, assertion 약화 없음)
  + 추가: test_pallet_data_paths_unit.py          +41
  + 추가: test_manage_pallet_data_layout.py       +39
  + 추가: test_mask_layout_compatibility.py       +31
────────────────────────────────────────────────────────
default unit pass                                566
local integration pass (별도 실행)                 +20
────────────────────────────────────────────────────────
합계                                             586
skip                                               0
fail                                               0
```

registry 검사 수: 기존 22 → unit 41 + integration 20 = **61** (기준 22 이상 충족).
**의미적 커버리지 감소 없음** — 실데이터 단언은 삭제가 아니라 integration 으로 이동했고,
`detect_project_root` 는 오히려 "틀린 이유로 통과"하던 것을 실검증으로 바꿨다.
archive overlay golden test 는 여전히 skip 0 으로 통과한다(fixture 위치 불변).

## 8-F. 기존 Stage 2-A 데이터 검증 (읽기 전용) [확인, 실행함]

`--apply` / `--rollback` / manifest 덮어쓰는 `--plan` 은 실행하지 않았다.

```
$ python scripts/data_prep/manage_pallet_data_layout.py --verify
verified moves : 146
files          : 6921
bytes          : 1197395529 (1.197 GB)
sha256 checked : 6921
hash modes     : selective-legacy=146
failures       : 0
```

원장 sha256 `fe1adc266bd91963c7be98779ed4c114b90b0b811fabdd60471a807aeb56d101` —
PRE-FLIGHT 값과 동일(재작성 없음).
Stage 2-A destination 존재: runs/smoke 30 · runs/diagnostics 13 · runs/failed 5 (불변).

## 8-G. 5k bpy-free dry-run [확인, 실행함]

```
$ python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 --dump <tmp>

FrameSpec dump sha256   938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39
Stage 2-A 값과            동일
accepted                4313 (86.3%)          동일
rejected                687                   동일
distractors             209                   동일
determinism             same seed identical=True / different seed differs=True
solve_placement         determinism(same spec => same Plan)=True
FrameSpec lines         5000
NaN / inf               0
missing asset·config    0 (Traceback / No such file 문자열 0)
registry missing        0
```

알고리즘·처방을 바꾸지 않았으므로 동일 seed 에서 checksum 과 통계가 같아야 하고, 실제로 같다.

## 데이터 무변화 확인 [확인, 실행함]

```
                Stage 2-A 종료      Stage 2-A.1 종료      delta
dirs            2,532               2,532                 +0
files           363,026             363,026               +0
bytes           191,023,461,284     191,023,461,932       +648
```

`+648` bytes 는 §2 정본 단일화로 갱신한 **문서 2개**뿐이다 —
`data/pallet/README.md`, `data/pallet/manifests/README.md` (mtime 으로 확인).
데이터 파일 이동·삭제·생성 0건.
