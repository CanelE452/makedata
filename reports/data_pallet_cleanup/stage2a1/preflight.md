# Stage 2-A.1 PRE-FLIGHT

- 일시: 2026-07-28
- 목표: Stage 2-A 산출물(registry / 트랜잭션 / 문서)의 안정화. **데이터 이동 0건.**

## 0. 기준 상태 [확인]

```
항목                       값
──────────────────────────────────────────────────────────────────────────
repo root                  E:/CODING/GitHub/FoundationPose
HEAD (작업 전)              d05e883dfc052e74b8b1be16cc7551c25e5eacab
origin/main                d05e883dfc052e74b8b1be16cc7551c25e5eacab  (동일)
git status                 clean (porcelain 무출력)
작업 branch                chore/data-pallet-stage2a1-stabilization  (신규 생성)
data/pallet 절대경로        E:\CODING\GitHub\FoundationPose\data\pallet  (gitignored)
pallet_paths.yaml          존재
move_transaction.jsonl     존재 — 146 rows,
                           sha256 fe1adc266bd91963c7be98779ed4c114b90b0b811fabdd60471a807aeb56d101
Stage 2-A destination      runs/smoke 30 · runs/diagnostics 13 · runs/failed 5
                           runs/pilot 0 · runs/production 0
production asset           10곳 전부 원위치 (blender_scene/hdri/models_usd/distractors/
                           background/pallets_v2_add/real_data/archive/textures_*/
                           archive/trunc_addon_v1_pilot)
```

working tree 가 clean 했으므로 §0 의 "관련 없는 변경 분류" 절차는 해당 없음.
`move_transaction.jsonl` 의 sha256 을 위에 고정해 두고, 작업 종료 시 동일한지 재확인한다.

---

## 1. 로컬 data/pallet 에 의존하는 registry 테스트 [확인]

현 `tests/test_pallet_data_paths.py` 22개 중 **파일시스템 실재를 단언하는 것 3개**:

```
테스트                                                            의존 대상
─────────────────────────────────────────────────────────────────────────────────
RealRegistry::test_audit_reports_no_missing_path                 registry 21경로 전부
SeparatorHandling::test_backslash_registry_values_are_accepted   isdir(hdri_root)
ConsumersUseTheRegistry::test_..._loads_the_full_209_pool        distractors_manifest.csv 실파일
```

registry **값만** 비교해서 clone 에서도 도는 것 19개(문자열 비교·임시 fixture·예외 검사).

## 2. 새 clone 에서 실패하거나 **잘못 통과**할 수 있는 테스트 [확인]

```
구분        테스트                                              새 clone 에서의 거동
──────────────────────────────────────────────────────────────────────────────────────
FAIL       test_audit_reports_no_missing_path                  missing 21 -> 단언 실패
FAIL       test_backslash_registry_values_are_accepted         isdir(hdri) False -> 실패
FAIL       test_..._loads_the_full_209_pool                    manifest 파일 없음 -> 실패
잘못 통과   test_project_root_detection_finds_the_repo          detect_project_root() 의 walk-up 은
                                                               `config/synthetic` + `data/pallet` 를
                                                               **둘 다** 요구한다. clone 에는 data/pallet 이
                                                               없어 walk-up 이 전부 실패하고
                                                               `__file__/../../..` fallback 으로 떨어지는데,
                                                               그 값이 우연히 repo 루트라 **통과한다.**
                                                               = 탐지 로직을 검증하지 못한 채 초록불
```

**[판정]** 3개는 실데이터 integration 으로 옮기고, `detect_project_root` 는 임시 디렉토리에
가짜 repo 구조를 만들어 **walk-up 경로 자체를 검증**하도록 unit 에서 다시 쓴다.

## 3. runtime 경로 정본이 두 군데로 표현된 위치 [확인]

```
파일                                라인   문구
────────────────────────────────────────────────────────────────────────────────
_docs/data_pallet_layout.md          60   "manifests/assets.csv 의 current_path 열이 정본"
_docs/data_pallet_layout.md         156   "current_path 가 정본, desired_path 는 예정지"
data/pallet/README.md                23   "manifests/assets.csv 의 current_path 열이 진실"
data/pallet/manifests/README.md      13   "정본 컬럼 = current_path"
```

같은 문서 안에서 "registry 로만 조회한다"와 공존해 **정본이 둘로 읽힌다.**
reports/data_pallet_cleanup/README.md 는 해당 문구 없음(§7 설명은 manifest 스키마 소개).

## 4. 트랜잭션 스크립트의 현재 hash 정책 [확인]

`manage_pallet_data_layout.py::snapshot()` — 아래 중 하나라도 만족하면 SHA256:

```
size <= 8MB (HASH_SIZE_LIMIT)
확장자 in {.json,.jsonl,.csv,.md,.txt,.yaml,.yml}
파일명에 "manifest" 포함
같은 폴더 안에서 동일 크기가 2개 이상 (duplicate_size_set)
```

나머지는 `unhashed` 리스트에 이름만 기록. **모드 선택 불가 — 항상 selective.**
Stage 2-A 실이동에서는 대상이 전부 8MB 이하라 결과적으로 unhashed 0 이었다(6,921/6,921 해시).

## 5. 트랜잭션 스크립트의 경로 경계 검사 방식 [확인]

```python
# manage_pallet_data_layout.py:196,198
if not _posix(os.path.abspath(src_abs)).startswith(_posix(data_root)):
```

**문자열 prefix 비교**다. `data/pallet_backup` 은 `data/pallet` 로 시작하므로
"data root 안"으로 잘못 판정된다. realpath·commonpath 미사용, 대소문자 정규화 없음.

## 6. `pallet_data_paths.py` CLI 의 `or True` [확인]

```python
# line 228
if args.audit or True:
```

- `--audit` 플래그가 **아무 의미가 없다**(항상 참).
- `--key` 는 그 앞에서 `return 0` 하므로 정상 동작하지만, `--key` 경로에서는
  audit 결과를 계산해 놓고 버린다(불필요한 stat).
- 잘못된 key 는 `paths.get()` 의 KeyError 가 **traceback 째로** 노출된다.
- exit code 는 missing 유무로 갈리지만, `--key` 경로는 항상 0.

## 7. analyze / compare 의 mask 경로 하드코딩 [확인]

```
파일                          라인        코드
────────────────────────────────────────────────────────────────────────────────
analyze_v2_scene_logic.py     471-474    mask_dir = root / "mask";  glob(f"f*_{suffix}.png")
analyze_v2_scene_logic.py     968        mask_stats(root / "mask" / f"{frame}_{name}.png")
analyze_v2_scene_logic.py     2019-2024  write_self_test_fixture (self-test 전용 — 유지 대상)
compare_v2_determinism.py     217        root / "mask" / f"{frame}_{name}.png"  (MASK_NAMES 5개 고정)
```

`mask_profiles.py` 는 이미 필요한 API 를 전부 갖고 있다 [확인]:
`detect_profile(root)` / `mask_stages(profile)` / `frame_mask_paths(root, idx, profile)` /
`resolve_frame_mask_path(root, idx, stage)` / `mask_dirnames(profile)` /
`occlusion_decomposition_available(profile)` / `decompose(areas, profile)`.

public 레이아웃은 `mask_amodal/fNNNN.png` · `mask_visible/fNNNN.png` 라
현재 코드는 **5개 전부를 결측으로 세고**, `mask_names[1..3]` 인덱싱이 public(2 stage)에서
IndexError 대신 조용히 건너뛰어 `mask_area_after_*` 가 비게 된다.

## 8. onboarding 의 오래된 mask · overlay 설명 위치 [확인]

```
라인        내용
────────────────────────────────────────────────────────────────────────────
17          "visible mask 3종"
32          "visible mask 3종: unoccluded / after-cargo / visible"
124         G3 게이트가 area_unocc 기준
156-157     overlay_all/ 을 전수 오버레이 정본으로 서술
171-174     레이아웃: mask/f*_unocc.png, _aftercargo.png, overlay_all/
180-191     "마스크 3종 의미" + f_cargo/f_total 정의 + 접미사 정본 규칙
223         label 스키마의 mask_area_unocc / after_cargo / visible
240-251     overlay 정본 = FRONT 빨강 / REAR 파랑 / connector 노랑
253-257     overlay_all 전수 육안 절차
341         접미사 유지 규칙
542         체크리스트의 overlay_all
```

현 규약(2026-07-28 커밋 ff972c2)은 **M0~M4 5-stage(full-audit) / M0·M4 2-stage(public)** 이고
overlay canonical 은 `--style archive` → `<dataset>/overlay/` 다. 문서가 두 세대 뒤처져 있다.

## 9. 변경할 파일과 목적

```
파일                                                          목적
──────────────────────────────────────────────────────────────────────────────────────
tests/test_pallet_data_paths_unit.py                    신규  clone-safe unit (fixture 전용)
integration_tests/test_pallet_data_paths_local.py       신규  실데이터 integration (명시 실행)
tests/test_pallet_data_paths.py                         삭제→분리  두 파일로 이관 (assertion 유지)
tests/test_manage_pallet_data_layout.py                 신규  트랜잭션 unit (temp dir 전용)
tests/test_mask_layout_compatibility.py                 신규  public/full-audit fixture 검사
pallet_data_paths.py                                    수정  CLI `or True` 제거 + 오류 처리
manage_pallet_data_layout.py                            수정  --hash-mode, is_within(commonpath)
analyze_v2_scene_logic.py                               수정  mask profile 자동 감지
compare_v2_determinism.py                               수정  좌/우 profile 독립 감지
_docs/blender_mcp_onboarding.md                         수정  mask/overlay 규약 최신화
_docs/data_pallet_layout.md                             수정  runtime 정본 단일화
data/pallet/README.md, manifests/README.md              수정  동일
reports/data_pallet_cleanup/stage2a1/*.md               신규  보고서 8종
```

**[판정]** 위 9항목을 확인했고 예상 밖의 코드 변경은 없다. 작업을 진행한다.
