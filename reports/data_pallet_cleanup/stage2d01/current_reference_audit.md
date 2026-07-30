# Stage 2-D0.1 §2 — Canonical CURRENT reference 감사

## 결론

```
canonical broken CURRENT reference   before  44 행 (unique 39 · 파일 23)
                                     after    0 행
```

**과거 보고서의 2 / 8 / 10 중 어느 것도 쓰지 않았다.** 같은 검출기를 기준 커밋 트리와
현재 트리에 각각 돌려 얻은 값이다.

- before: `git grep <7패턴> 60e0860` → `current_reference_audit_base.csv`
- after : 현재 워킹트리 `rg <7패턴>` → `current_reference_audit.csv`

## 검출 형태 7종 (지시문 §2 요구 전부)

```
form           패턴                                              before 히트
──────────────────────────────────────────────────────────────────────────────
literal        "data/pallet/<x>"                                      1,959
literal_bs     data\pallet\<x>                                       10,200
os_path_join   os.path.join(..., "data", "pallet", "<x>")                25
pathlib        Path(..) / "data" / "pallet" / "<x>" · Path("data/pallet")  0
fstring        f"{root}/data/pallet/<x>"                                 19
shell_var      ${ROOT}/data/pallet/<x>                                   19
yaml_value     key: data/pallet/<x>        (따옴표 없는 plain scalar)      14
bare           따옴표 없는 일반 등장 (shell 대입·명령줄 예시·표)          16,158
```

### ★ 1차 시도가 놓친 것 — 기록해 둘 실패

1차 감사는 `literal` 패턴이 **`data/pallet/` 앞에 따옴표를 요구**했다. YAML plain
scalar 는 따옴표가 없다:

```yaml
train_dir: data/pallet/training_data/train      # <- 1차 감사가 못 봤다
```

그래서 `config/default.yaml`(2건) · `config/stage3_selftrain.yaml`(3건)의 **깨진 학습
입력 경로를 전부 놓쳤고**, 1차 canonical 을 19 로 과소보고했다. `yaml_value` +
`bare` 패턴을 추가해 다시 셌다.

두 번째로, rg 덤프를 `data/pallet/` · `data\pallet\` 두 패턴으로만 만들어서
**join-form 이 덤프에 아예 들어오지 않았다** (`"data", "pallet", "distractors"` 는
`data/pallet` 문자열을 포함하지 않는다). 덤프를 7패턴으로 합친 뒤
`compute_distractor_fill_ratio.py:49` · `debug_pallet_orientation.py:10` ·
`merge_and_validate.py:14,16,17,19` 가 정상 검출됐다.

## 분류 (before, 총 28,394 참조)

```
classification                건수     조치
────────────────────────────────────────────────────────────────────
REPORT_SNAPSHOT             27,428    수정 금지 (당시 결과)
TRANSACTION_MANIFEST           349    수정 금지 (이동 원장 + allowlist)
HISTORY                        186    수정 금지 (과거 기록)
CURRENT_RUNTIME                121    ★ fix 대상
CURRENT_DOC                     90    ★ fix 대상
FALSE_POSITIVE_TEST_FIXTURE     87    tmpdir fixture — 의도적으로 부재
LEGACY_RUNTIME_FROZEN           74    일회성 진단 스크립트(`_*.py`) — 동결
CURRENT_TEST                    39    ★ fix 대상 (실제 경로 단언)
FALSE_POSITIVE_COMMENT          12    주석 · registry 설명 키
LEGACY_DOC                       8    구 문서
```

`fix_required = CURRENT_{RUNTIME,TEST,DOC}` **AND** 대상 부재 **AND** io_role ≠ output
**AND** pre-existing-missing 아님.

CSV 에는 위 4개 bulk 분류(수정 금지 · 전체의 99.7%)를 제외한 행만 담았다
(before 431행 / after 422행). 전체 집계는 `current_reference_audit_summary.json` ·
`current_reference_audit_base_summary.json` 에 있다 — §14 의 "5MB 초과 raw dump 는
commit 대상 제외" 규칙에 따른 것이다(전량 CSV 는 56MB).

## io_role 을 나눠야 하는 이유

```
scripts/data_prep/blender/gen_topview_test.py:15
  "- N target = 24, outputs to data/pallet/_test_topview/"     -> output. 실행 시 생성.
config/default.yaml:53
  "train_dir: data/pallet/training_data/train"                  -> input. 없으면 학습 실패.
```

output 경로를 broken 으로 세면 "실행하면 만들어지는 폴더"를 전부 결함으로 계상한다.
반대로 output 이라고 무조건 넘기면 **옛 레이아웃을 다시 만들어내는 코드**를 놓친다 —
실제로 그런 게 하나 있었다:

```
scripts/data_prep/blender/gen_palletobj_v1.py:569
  bpy.ops.wm.save_as_mainfile(filepath="data/pallet/blender_scene/_sandbox_parking_lot_check.blend")
```

Stage 2-C2 로 `blender_scene/` 가 옮겨졌으므로 이 줄은 **없어진 폴더를 새로 만들어**
옛 배치를 되살린다. canonical(입력) 집계에는 넣지 않았지만 §11-G 의
`old active path resolution = 0` 게이트에 걸리므로 현재 폴더로 고쳤다.
(원래 semantics — 같은 파일을 덮어쓰는 백업 — 는 그대로다.)

## pre-existing missing — Stage 2 회귀가 아닌 것

이동 원장 3종(2-A / 2-B / 2-C2) 에 **0건**, Stage 1 grouped inventory 에 **0건** 인
경로는 Stage 2 이동으로 깨진 것이 아니라 이 저장소에 존재한 적이 없다 [확인].

```
data/pallet/pallet_scene            config/synthetic/isaac_sim.yaml:3,4   (다른 워크스테이션 자산)
data/pallet/real_unlabeled          config/stage3_selftrain.yaml:82 · self_train.py:18
data/pallet/test_render_v2          visualize_annotations.py:5
data/pallet/ndds3_pallet.pth        (1차에서 weights/ 로 정정)
```

`pallet_scene` 은 `isaac_sim.yaml` 에 `★ MISSING_ASSET` 주석만 달았다. 없는 자산을
가리키는 경로를 임의로 다른 경로로 바꾸면 **틀린 정보를 코드에 심는 것**이 된다.

`real_unlabeled` 는 registry `real_data_root`(= `reference/real_images/real_data`, 1,924장)
로 바꾸고 싶은 유혹이 있지만 그렇게 하지 않았다 — real_data 는 self-training 풀이고
`real_unlabeled` 가 그것과 같은 것이라는 근거가 없다. 확인되지 않은 동일시는 하지 않는다.

## 수정 결과

파일 25개 / 경로 관련 변경 줄 67 (`current_reference_fixes.csv`, git diff 에서 재구성).
방식:

- Python → `_pdp.get("<key>")` registry 조회, 또는 archive 실제 경로
- Shell → `$(python scripts/data_prep/blender/pallet_data_paths.py --key <key>)`
- Config → registry 로 유도 가능한 값은 중복 정본을 만들지 않고 실제 현재 경로로
- 문서 → 현재 자산 위치로

자산을 원위치로 되돌리거나 symlink/junction 을 만들지 않았다.

## 재검증

```
동일 검출기 · 현재 트리:  fix_required = 0
§11-G 도구 해석:          old active path 0 / registry key error 0 / missing input 0
```
