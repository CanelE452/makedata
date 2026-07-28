# Stage 2-A.1 최종 보고

## 1. 목적과 최종 판정

Stage 2-A 에서 도입한 경로 registry·트랜잭션 기반을 **새 clone / 로컬 workstation /
public·full-audit 레이아웃 어디서든 안전하게 쓸 수 있도록** 안정화. 6개 목표 전부 완료.
**판정: 완료.** 중단 기준(§10) 해당 없음.

## 2. 기준 branch / HEAD

```
작업 전 HEAD      d05e883dfc052e74b8b1be16cc7551c25e5eacab  (= origin/main)
작업 branch       chore/data-pallet-stage2a1-stabilization   (신규 생성)
git status        작업 전 clean
```

## 3. 변경 파일

```
수정 (8)
  scripts/data_prep/blender/pallet_data_paths.py          CLI `or True` 제거 + 오류 처리      +68/-
  scripts/data_prep/manage_pallet_data_layout.py          --hash-mode, is_within(commonpath)  +106
  scripts/data_prep/blender/analyze_v2_scene_logic.py     mask profile 자동 감지               +110
  scripts/data_prep/blender/compare_v2_determinism.py     좌/우 profile 독립 감지               +94
  _docs/blender_mcp_onboarding.md                         mask/overlay 규약 최신화 + registry  +137
  _docs/data_pallet_layout.md                             runtime 정본 단일화                   +22
  reports/data_pallet_cleanup/README.md                   정본 관계 주석                        +5
  data/pallet/README.md, manifests/README.md              (gitignored) 정본 단일화 동기화

삭제 (1)
  scripts/data_prep/blender/tests/test_pallet_data_paths.py   -> 아래 2파일로 분리 이관

신규 (4 + 보고서)
  scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py            41 tests
  scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py  20 tests
  scripts/data_prep/blender/tests/test_manage_pallet_data_layout.py         39 tests
  scripts/data_prep/blender/tests/test_mask_layout_compatibility.py         31 tests
  reports/data_pallet_cleanup/stage2a1/*.md                                 보고서 8종
```

## 4. registry unit / integration 분리 결과

```
                                        테스트   실데이터 의존
tests/test_pallet_data_paths_unit.py        41   없음
integration_tests/..._local.py              20   있음 (PALLET_DATA_INTEGRATION=1 필요)
────────────────────────────────────────────────────────────
합계                                        61   (기존 22 대비 +39)
```

assertion 약화 0. 실데이터 단언 3건은 삭제가 아니라 integration 으로 **이동**.
상세: `test_split.md`

## 5. 새 clone 에서 unit test 가 data/pallet 없이 동작하는가 → **예** [확인, 실행함]

`data/` 를 아예 만들지 않은 임시 트리에서 **41 passed, skip 0, network 0**.
전체 unit 파일을 넣은 시뮬레이션에서는 109 passed + 2 skip(= Stage 2-A 원장이 clone 에 없어서
건너뛰는 가드 테스트, `-rs` 로 사유 노출).

작업 중 **CLI 테스트가 fixture 가 아니라 실제 저장소 경로로 해석되어 통과**하던 것을 발견해
`--data-root` 고정으로 바로잡고 회귀 테스트를 넣었다. 고치려던 패턴이 새 테스트에서 재발한 사례다.

## 6. runtime source of truth 확정

> `config/synthetic/pallet_paths.yaml` = **runtime source of truth**
> `data/pallet/manifests/*.csv` = **local inventory snapshot**

실행 코드는 registry 만 읽는다. 문서 4곳의 "assets.csv 의 current_path 가 정본" 표현을 제거했다.
상세: `source_of_truth_audit.md`

## 7. assets.csv 의 새 역할

runtime config 아님. 조사 시점의 로컬 snapshot. **수정해도 실행 경로가 바뀌지 않는다.**
경로 변경은 `pallet_paths.yaml` 수정 + `--audit` 확인으로만.

## 8. transaction hash-mode

```
--hash-mode selective  (기본)  Stage 2-A 정책 유지 (8MB 이하 / 텍스트·manifest / 동일크기 후보)
--hash-mode all               크기·확장자 무관 전량 SHA256 (active asset·blend·HDRI·3D·
                              golden reference·release package 이동 시 필수)
```

manifest row 에 `hash_mode / hashed_file_count / unhashed_file_count /
hash_started_at / hash_completed_at` 기록. `all` 인데 unhashed 가 남으면 **RuntimeError 로 중단**
(selective 를 all 로 보고하지 않는다). 기존 manifest 는 `hash_mode` 부재 시
`"selective-legacy"` 로 읽고 **자동 rewrite 하지 않는다** — verify/rollback 가능 상태 유지.

## 9. commonpath 경계 검사

`startswith` → `is_within()`(realpath + normcase + commonpath).
`data/pallet_backup` 이 `data/pallet` 안으로 잘못 판정되던 문제 해소.
source / destination / **destination 부모**를 검사(destination 은 아직 없어 realpath 가
부모까지만 접히므로). 다른 드라이브는 ValueError → False. 9개 테스트로 고정.

## 10. resolver CLI 수정

`if args.audit or True:` 제거. `--key`(단일 조회, audit 미계산, list 는 줄단위) /
`--audit` / 인자 없음(= --audit). 잘못된 key 는 traceback 대신 stderr 에 사용 가능 key 목록 +
exit 1. missing 있으면 exit 1, 없으면 0. CLI 테스트 9개.

## 11. onboarding mask 규약 수정

`§3.1.1` 신설 — public(mask_amodal/mask_visible, M1~M3 **렌더 안 함**) vs
full-audit(mask/f*_m0..m4) 대비표, M0~M4 의미, **None(미측정) 과 0.0(가림 없음) 구분**,
`mask_profiles.py` API. TL;DR·§1.1·G3 게이트·§3.1 레이아웃·§3.2 label 스키마도 함께 갱신.

## 12. onboarding overlay 규약 수정

canonical = `--style archive` → `<dataset>/overlay/`.
secondary debug = `--style frontrear-debug` → `<dataset>/overlay_frontrear_debug/`
(FRONT/REAR/connector + 외부 패널 + audit header + M0/M4 contour, **canonical 아님**).
archive 정본 reference `data/pallet/archive/trunc_addon_v1_pilot` 위치 불변 명시.
문서에 적은 옵션이 실제 존재하는지 소스로 확인했고, 미구현(`camera-postprocess none`)은 적지 않았다.

## 13. analyze public/full-audit 결과

```
profile=public      mask_stages [m0,m4]        결측 오판 0   CSV 컬럼 m0,m4 만
profile=full-audit  mask_stages [m0..m4]       회귀 없음     CSV 컬럼 5개 유지
```

summary 에 `mask_layout{mask_profile, detected_by, mask_stages,
occlusion_decomposition_available}` 추가. `--mask-names` legacy override 유지.

**추가 발견·수정**: `frame_columns()` 가 전역 `MASK_NAMES` 만으로 제거 대상을 계산해
public 에서 빈 `mask_m1/m2/m3_*` 컬럼이 CSV 에 남았다(소비자에겐 결측으로 보임). 수정 + 회귀 테스트.

## 14. determinism profile 별 결과

```
좌 / 우                          compared stages   deterministic   비고
────────────────────────────────────────────────────────────────────────────────
public / public                  [m0, m4]          True
full-audit / full-audit          [m0..m4]          True
public / full-audit (기본)        [m0, m4]          False           errors: mask_profile_mismatch
public / full-audit (--allow-)   [m0, m4]          False           partial_mask_comparison=true
```

report 에 `left_mask_profile / right_mask_profile / compared_mask_stages /
partial_mask_comparison / mask_profile_mismatch` 추가. 부분 비교를 완전 통과로 표시하지 않는다.

## 15. Stage 2-A transaction verify (읽기 전용)

```
verified moves 146 / files 6,921 / bytes 1,197,395,529 / sha256 6,921 / failures 0
hash modes: selective-legacy=146
원장 sha256 fe1adc26…  (PRE-FLIGHT 값과 동일 = 재작성 없음)
```

## 16. 5k dry-run 전후 비교

```
FrameSpec sha256   938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39  (Stage 2-A 와 동일)
accepted 4,313 (86.3%) / rejected 687 / distractors 209 / NaN·inf 0 / missing 0
determinism same-seed identical=True, different-seed differs=True
```

## 17. 전체 테스트 결과

```
default unit         566 passed   (477 - 22 + 41 + 39 + 31)
local integration     20 passed   (PALLET_DATA_INTEGRATION=1)
─────────────────────────────────
합계                 586 passed   skip 0   fail 0
```

변경 이유: 기존 22개 registry 테스트를 41(unit) + 20(integration) 으로 분리·강화했고,
트랜잭션 39 + mask 레이아웃 31 을 신설했다. 커버리지 감소 없음, 임계값 완화 없음,
테스트 숨김(collection 제외) 없음.

## 18. 남은 Stage 2-B blocker

1. `.blend` 내부 이미지 경로 덤프 미실행 → `assets/scenes/production/` 이동은 그 확인 후
2. `archive/textures_{wood,floor}` → `assets/materials/` (이제 **registry 값만 바꾸면 됨**)
3. `archive/trunc_addon_v1_pilot` → `reference/golden_overlay/` + 테스트 수정 + `pytest -rs` skip 0
4. `hdri`/`models_usd`/`background`/`distractors` → `assets/` (registry + blender.yaml 동기화)
5. **`_DISTRIBUTION_EXCLUDE.txt` 경로 5/5 stale — 릴리스 라이선스 게이트 미작동 (미해결)**
6. archive 이동(legacy_datasets 87.7GB + packages 80.8GB)
7. `inventory.csv` → `grouped_inventory.csv` 개명 (계획만)
8. `analyze_v2_continuous.py` 는 mask 경로를 만들지 않아 이번 수정 대상이 아니었다 [확인]

## 19. git diff

```
 _docs/blender_mcp_onboarding.md                    | 137 +++++++++---
 _docs/data_pallet_layout.md                        |  22 +-
 reports/data_pallet_cleanup/README.md              |   5 +
 scripts/data_prep/blender/analyze_v2_scene_logic.py| 110 ++++++++--
 scripts/data_prep/blender/compare_v2_determinism.py|  94 +++++++--
 scripts/data_prep/blender/pallet_data_paths.py     |  68 ++++--
 scripts/data_prep/blender/tests/test_pallet_data_paths.py | 234 --------------
 scripts/data_prep/manage_pallet_data_layout.py     | 106 ++++++++--
 8 files changed, 453 insertions(+), 323 deletions(-)

신규(untracked): reports/data_pallet_cleanup/stage2a1/
                scripts/data_prep/blender/integration_tests/
                scripts/data_prep/blender/tests/test_{manage_pallet_data_layout,
                    mask_layout_compatibility,pallet_data_paths_unit}.py
```

## 20. rollback 필요 여부 → **불필요**

데이터 이동이 0건이라 되돌릴 파일 상태가 없다. 코드 변경은 커밋되지 않은 작업 branch 에만
있으므로 `git checkout main` 으로 즉시 원복 가능하다. Stage 2-A 원장은 무손상이라
필요 시 Stage 2-A 의 146건 이동도 여전히 `--rollback` 으로 되돌릴 수 있다.

---

```
데이터 이동 건수        0
데이터 삭제 건수        0
asset 이동 건수         0
ZIP 이동 건수           0
Blender 렌더 건수       0
Stage 2-B 실행 건수     0
commit                 0
push                   0
```
