# Stage 2-D1.1 최종 보고 — 잔여 정리

## 1. 목적과 판정

Stage 2-D1 이 남긴 3범위를 **검증 사슬을 유지한 채** 해소한다.

```
[판정]
  D11A_BLEND_BACKUPS       COMPLETE   10건 / 2.24 GiB — chained-ledger 로 C2C 사슬 유지
  D11B_REFERENCE_TRANSITION PARTIAL    registry 전환 완료 / 실이동 미실행 (hash 예산)
  D11C_LICENSE_RESOLUTION   PARTIAL    provenance 판정 완료 / 실이동 미실행 (hash 예산)

  D11_SCOPE_COMPLETE                    ✗  (이동이 2/3 cohort 미실행)
  FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE ✗  (BLOCKED 8건 이동 미완)
  FULL_PHYSICAL_MINIMAL_TREE            ✗  (top-level 잔여 65 + quarantine)

  commit 0 / push 0 — 사용자 승인 대기
```

**중단 사유**: §6 전역 hash read 상한 20 GiB 대비 D11B+D11C 필요량 **61.33 GiB** (3.1배).
§17 이 "hash read 20GiB 초과"를 중단 기준으로 명시하고 selective 강등도 금지한다.
예산을 지키는 쪽을 택하고, 예산과 무관한 작업(registry 전환 · provenance 판정)은
전부 완료했다.

## 2. branch / HEAD

```
branch  chore/data-pallet-stage2d11-residual-finalization
HEAD    1577e25d52a0c603b77729db7475934cc7cb6f1b  (= origin/main, 작업 전과 동일)
```

## 3. 기존 D1 상태 (작업 전 실측)

```
D1B/D1A/D1C   VERIFIED  30행 / 191,518 파일 / 130.14 GiB / mismatch 0
D1D           ROLLED_BACK 10행 · src 존재 10/10 · dst 잔존 0 · verified 10
C2C exact     failures 0
registry      ok=24 missing=0 · unit 714 · integration 31 · golden 51
5k            938f387d(4,313/687) · 3cd365ee(4,439, 12/12)
active scene  8cb4109adc6d3213…
data/pallet   dirs 2,567 · files 363,090
```

## 4. frozen residual scope

```
scope                     rows     files            bytes
D1D_ROLLBACK_SOURCE         10        10       2,400,984,463   (2.24 GiB)
BLOCKED_REFERENCE            4    92,429      17,334,010,020  (16.14 GiB)
BLOCKED_UNKNOWN              4    39,620      15,588,789,193  (14.52 GiB)
────────────────────────────────────────────────────────────────
합계                        18   132,059      35,323,783,676  (32.90 GiB)
```

Stage 2-D1 보고 숫자를 쓰지 않고 재계산했다. row 수는 같고 bytes 는 실측값이다.
동결: `frozen_scope.json` (scope_csv_sha256 로 `residual_scope.csv` 까지 이중 결속).

## 5. 실제 D1D file 수 · bytes

```
files 10 / bytes 2,400,984,463 (2.24 GiB)
exists 10/10 · COLD_ARCHIVE 10/10 · 현재 SHA256 == D0 기록 10/10
prior C2C 원장 구성원 10/10 · prior 원장 SHA256 == 현재 10/10
active/rollback registry ref 0 · current runtime/test ref 0 · dest collision 0
```

## 6. chained-ledger 설계

`--successor-ledger-chain <json>` 신규. immutable prior ledger 와 verified successor
ledger 를 **파일 단위 SHA256 identity** 로 잇는다. 기존 manifest 는 수정하지 않는다.

통과 조건 16개 (전부 강제):

```
① prior manifest SHA256 결속       ② prior 원장에 relative path 실재
③ prior 원장 size·SHA256 == mapping ④ successor source == prior destination
⑤ successor manifest SHA256 결속    ⑥ successor row VERIFIED
⑦ successor pre-hash == prior hash  ⑧ successor destination 존재
⑨ successor destination SHA256 일치 ⑩ successor destination size 일치
⑪ prior file 당 mapping 정확히 1개  ⑫ successor file 이 복수 prior 대표 금지
⑬ path escape 금지                 ⑭ ledger cycle 금지
⑮ unmapped missing 0               ⑯ prior destination 에 아직 있는 파일은 chain 불가
```

**broad removal allow 나 expected-removal 목록은 쓰지 않았다.** 없어진 파일을
통과시키는 유일한 근거는 "후속 원장이 같은 바이트로 이어받았다"는 증명이다.

### ★ 실행 중 발견해 고친 것 — verify 멱등성

chain 은 successor 원장 SHA256 에 결속되는데, verify 가 재실행마다 `verified_at` 을
갱신해 원장 SHA256 을 바꿨다. 실제로 chain 결속이 깨졌다:

```
successor chain 오류: successor manifest sha256 불일치
  spec   e2c1a19f29c59470…   actual 500da4140372ecd3…
```

원장은 "언제 **처음** 검증됐는가"를 기록하는 immutable 기록이어야 한다. 첫 검증에만
기록하도록 고쳤다. 멱등성 확인:

```
before=500da4140372ecd3  after1=500da4140372ecd3  after2=500da4140372ecd3  -> 멱등 YES
```

## 7. chained-ledger 음성 테스트

`tests/test_successor_ledger_chain.py` **31개, skip 0** (tmpdir 전용 30 + 실제 원장 읽기 1).
§4 요구 22항목 전부 커버. 음성 사례:

```
prior manifest SHA 위조                  -> exit 2
prior manifest path 불일치                -> SuccessorChainError
prior move_id 부재 / relpath 부재          -> SuccessorChainError
prior size / SHA mismatch                -> SuccessorChainError
prior destination path 불일치             -> SuccessorChainError
successor manifest SHA 위조               -> SuccessorChainError
successor source != prior destination     -> SuccessorChainError
successor row not VERIFIED / not MOVED    -> SuccessorChainError
successor destination 삭제 / 내용 위조     -> SuccessorChainError
successor pre-hash 위조                   -> SuccessorChainError
duplicate prior / successor mapping       -> SuccessorChainError
unmapped prior missing                   -> verify exit 1
path escape (../escaped)                 -> SuccessorChainError
ledger cycle (successor == prior)         -> SuccessorChainError
empty mappings / 필수 필드 누락            -> SuccessorChainError
prior destination 에 아직 있는 파일        -> SuccessorChainError
unrelated destination addition            -> verify exit 1
expected addition + chain 동시            -> exit 0 (공존 확인)
chain 없이 C2C missing                    -> exit 1 (기존 동작 유지)
```

실제 저장소 원장 확인(읽기 전용): D1D 10개가 C2C 원장 구성원이고 size·SHA256 이
기록돼 있음 — chain 을 만들 수 있는 전제.

## 8. D1.1-A plan / apply / verify

```
plan    10 moves / hashed 10 / unhashed 0 / pre read 2.24 GiB / 한도 20 GiB
        scope sha 323fb396f4fc931a…  결속 확인
apply   10 moves (same-volume rename)
verify  failures 0 / sha256 10 / post read 2.24 GiB / mismatch 0
        source 잔존 0 / destination 존재 10
예산     4.47 / 20 GiB (22.4%)
```

결과 위치:

```
archive/legacy_scenes/snapshots/        6  (POSTBAKE_CLEAN · PREBAKE_BACKUP · REBAKE_WIP ·
                                           scene12 · scene121 · scene_indoor)
archive/legacy_scenes/blender_backups/  4  (_sandbox_parking_lot_check.blend1 ·
                                           REBAKE_WIP.blend1 · scene.blend1 · scene12.blend1)
blender_scene/ 남은 blend               7  (active 2 + rollback 4 + D1-003 1)
보호 blend 6개 SHA256                   전부 불변
```

## 9. C2C successor-chain 결과

```
mapping 10 / 문제 0
prior manifest    c2c_distractor_scene.jsonl   sha256 241f5c569d2be924…
successor manifest d11a_blend_backups.jsonl    sha256 500da4140372ecd3…

chain 없이               failures 11  (RELPATH_SET_MISSING 1 + MISSING 10)
exact additions + chain  failures 0   ★
  files 1,326 / sha256 checked 1,324
  expected additions 2 (active stable blend + Blender 자동 백업)
  chain mappings applied 10 / unmapped prior missing 0
```

**검증 사슬이 이어졌다** — C2C 원장은 수정하지 않았고, 없어진 10개는 후속 원장이
같은 SHA256 으로 이어받았음을 증명해 통과했다.

## 10. BLOCKED_REFERENCE canonical 수

```
4건 (기대값과 일치, 실측 정본)
D1-003  …/blender_scene/_sandbox_parking_lot_check.blend   0.13 GiB  ref 2  ★C2C 구성원
D1-033  archive/train_palletobj_v3                         9.95 GiB  ref 1
D1-038  archive/training_data                              5.99 GiB  ref 10
D1-053  archive/train_palletobj_v3_post_v1                 0.07 GiB  ref 1
```

## 11. 신규 registry key

```
legacy_training_data_root                 data/pallet/archive/training_data
legacy_train_palletobj_v3_root            data/pallet/archive/train_palletobj_v3
legacy_train_palletobj_v3_post_v1_root    data/pallet/archive/train_palletobj_v3_post_v1
legacy_sandbox_parking_lot_scene          …/blender_scene/_sandbox_parking_lot_check.blend

registry audit  ok=24 -> 28  missing=0
```

이름은 자료의 역할로 정했다 (`legacy_1` / `blocked_4` / `dataset_x` 금지).
`archive_root`+relpath 대신 명시적 key 를 둔 이유: 이 4개는 여러 current runtime 이
독립적으로 참조한다 (`legacy_training_data_root` 는 10곳).

## 12. current code / config 전환

16곳 (`registry_transition.csv`). 핵심은 **config YAML 값도 registry 참조로** 바꾼 것이다:

```
config/default.yaml:53,54        train_dir: registry:legacy_training_data_root/train
config/stage3_selftrain.yaml:81,85  synthetic_data: registry:legacy_training_data_root/train
```

해석기 신설: `pallet_data_paths.resolve_config_value()` + CLI `--resolve`.
`registry:` 로 시작하지 않는 값은 그대로 반환 → 기존 리터럴 설정 하위호환.
소비자 2곳(`train_dope.sh` 의 `resolve_path()` · `self_train.py`)이 이를 통과시킨다.

이렇게 해야 §8.2 요구("이동 후 code/config 를 다시 수정하지 않아도 동작")가 성립한다 —
이동 시 `pallet_paths.yaml` 의 **키 값 1줄**만 바꾸면 된다.

검증:

```
신규 키 4개 실제 해석        4/4
registry: 참조 해석          train/val 정상 · 리터럴 통과 · 없는 키 exit 1
옛 경로 직접 참조 (실행 경로) 0   (registry 정본과 resolver docstring 제외)
canonical CURRENT broken ref 0
unit / integration / golden  745 / 31 / 51  skip 0 fail 0
postprocess_v3.py --help    registry default 로 정상 기동
```

## 13. D1.1-B plan / apply / verify

```
plan / apply / verify   미실행
사유                    hash read 16.14 GiB × 2 = 32.29 GiB > 20 GiB 상한 (§6/§17)
준비 상태               registry 전환 완료 → 이동은 데이터 이동 + 키 1줄 변경만 남았다
추가 필요               D1-003 은 C2C 구성원 → successor chain 처리 필요 (D11A 와 동일 방식)
```

## 14. BLOCKED_UNKNOWN canonical 수

```
4건 (기대값과 일치, 실측 정본)
D1-041 training_data_v4_split_GREYBUG  4.93 GiB
D1-042 training_data_v4_split_bg1bak   4.93 GiB
D1-043 training_data_v4_emptywood      4.49 GiB
D1-049 training_data_v4_pilotA         0.18 GiB
current ref 0 · prior ledger 구성원 아님 → 기술적 장애 없음, 라이선스만 미확정이었다
```

## 15. dataset 별 provenance 증거

**라벨 13,122 프레임 전수 스캔** (표본 아님, 읽기 실패 0):

```
move_id  dataset                          frames  NoAI 프레임      %   mtime       pre-rebake
────────────────────────────────────────────────────────────────────────────────────────────
D1-041   training_data_v4_split_GREYBUG    5,000     3,286      65.7%  2026-06-17     yes
D1-042   training_data_v4_split_bg1bak     5,000     3,272      65.4%  2026-06-16     yes
D1-043   training_data_v4_emptywood        3,000     3,000     100.0%  2026-06-18     yes
D1-049   training_data_v4_pilotA             120        76      63.3%  2026-06-16     yes
```

팔레트 이름 분포 (라벨 `objects[].name`):

```
D1-041  Pallet_1=1,714 · Pallet_2=1,679 · Pallet_3=1,607
D1-042  Pallet_1=1,728 · Pallet_2=1,669 · Pallet_3=1,603
D1-043  Pallet_2=1,488 · Pallet_3=1,512          ← Pallet_1 없음 = 전부 NoAI
D1-049  Pallet_1=44 · Pallet_2=41 · Pallet_3=35
```

`Pallet_2`/`Pallet_3` = `scene_2.usd`/`scene_3.usd` = NoAI "Old Wooden Pallet"
(Luka Feric, Standard+NoAI) — ledger B1 명시, 해당 USD 가
`archive/_noai_quarantine_usd/` 에 실존.

반대 증거도 검토했다: 부모와 바이트 동일 프레임 **0/200** → 복사본이 아니라 별도 렌더.
그러나 NoAI 판정 근거는 복사 여부가 아니라 자기 라벨의 팔레트 자산이므로 판정은
바뀌지 않는다(오히려 독립 렌더인데 NoAI 를 썼다는 더 직접적인 증거다).

`README_CONTAMINATION.md` 는 부모 2종에만 있고 파생 4종엔 없다 — 표식 부재가 무죄
근거가 아님을 이 스캔이 보여준다.

## 16. license 판정

```
PROVEN_NOAI               4  (D1-041 · D1-042 · D1-043 · D1-049)
PROVEN_REDISTRIBUTABLE    0
UNRESOLVED_LICENSE        0
```

**미확정을 redistributable 로 추정하지 않았다.** 4종 모두 적극적 사용 증거로 확정됐다.
목적지: `archive/legacy_datasets/noai_baked/<name>` — 부모 2종이 이미 그곳에 있다.
`nonredistributable/unknown_license/` 는 UNRESOLVED 0건이라 쓰지 않는다.
release_allowed = **NO** (4종 전부).

## 17. D1.1-C plan / apply / verify

```
plan / apply / verify   미실행
사유                    hash read 14.52 GiB × 2 = 29.04 GiB > 20 GiB 상한 (§6/§17)
준비 상태               provenance 판정 완료 → 목적지 확정. 이동 + exclusion 4경로 정정만 남았다
```

## 18. exclusion 결과

```
entries 16 / problems 0 / release leaks 0 / stale 0   (D1.1 에서 변경 없음)
```

D11A 는 blend 이동이라 배포 제외 대상이 아니고, D11B/D11C 가 미실행이므로 경로 변경도
없다. `_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** — 새 clone 에서 자동 복원되지 않는
로컬 정책 파일이다. tracked 정본 기록은 `_docs/dataset_license_ledger.md` 이고, 수동
복구 절차는 `rollback_plan.md` 에 있다.

## 19. local manifests

```
archive.csv    D11A 10행 신규 (executed=yes · moved_stage=Stage2-D1.1) + 열 5개 추가
               (pre_stage2d11_path · successor_ledger · prior_ledger ·
                license_decision · provenance_evidence)  총 245행
path_map.csv   D11A 10행 신규 (205 -> 215). original_path 유지
assets.csv     stage2d11_status 열 — 현역 자산 17개 SHA256 재확인, 변경 0
```

## 20. grouped inventory

```
266 -> 276 행 (removed 0 / added 10)
depth 분포 {1: 74, 2: 151, 3: 8, 4: 43}   entry_type {dir 193, file 83}
MOVED_STAGE2D1X 40행 (D1 30 + D1.1 10)
```

**그룹 단위 유지** — 276행 vs data/pallet 파일 363,090개. 전 파일 manifest 로 바꾸지
않았다.

## 21. final tree

`final_tree.csv` (233 entry) / `final_tree.md`

```
data/pallet top-level 74   권장 8 + isaac_assets(quarantine) + 잔여 65 (4.27 GiB)
archive depth-1      151   semantic 컨테이너 9개 중 legacy_scenes/ 가 처음 채워짐
UNKNOWN / 미분류        0
분류되지 않은 top-level ZIP  0
빈 폴더                  7   삭제하지 않았다
```

## 22. 남은 KEEP

```
production_scene · experimental_scene            registry active (2)
rollback blend 4                                 rollback 사슬
UNREFERENCED_WEIGHT 4                            weights/ · data/pallet 밖 · gitignored ·
                                                 목적지 미정 · 삭제 후보 아님
```

전부 최종 위치와 유지 이유를 `final_tree.md` 에 문서화했다.

## 23. 남은 quarantine

```
data/pallet/isaac_assets/                      4.05 GiB  NVIDIA EULA (ledger B6)
data/pallet/archive/_noai_quarantine_usd/      0.70 MiB  NoAI USD (ledger B1)
archive/legacy_datasets/noai_baked/ 3종                   NoAI baked 렌더 산출물
```

전부 `_DISTRIBUTION_EXCLUDE.txt` 등록 · 배포 금지 문서화 완료.

## 24. UNKNOWN remaining

```
0
```

BLOCKED_UNKNOWN 4건이 PROVEN_NOAI 로 확정돼 UNKNOWN 등급이 사라졌다.
(위치는 아직 옛 경로 — 이동만 미실행)

## 25. canonical current refs

```
fix_required = 0
```

전환 후 다형식 검출기(literal · backslash · os.path.join · pathlib · f-string ·
shell var · YAML plain scalar) 재스캔 결과 0.

```
이동한 BLOCKED_REFERENCE 의 old source path   0 (이동 미실행이므로 현재 경로가 유효)
신규 registry key 가 실제 current code 에서 사용됨   16곳
old output path 가 실행 시 재생성                   0 (gen_palletobj_v1.py:569 도 registry)
archive destination 리터럴 중복 정본                0 (registry 1곳)
```

## 26. registry

```
ok=28  missing=0  absent_optional=0    (24 + 신규 4)
```

## 27~29. unit / integration / golden

```
unit         714 -> 745 passed (+31), skip 0, fail 0
integration   31 passed, skip 0, fail 0
golden        51 passed, skip 0, fail 0
```

## 30. 기존 원장 verify

```
stage2a · stage2b b1/b2 · stage2c2 c2a/c2b · stage2d1 d1b/d1a    failures 0
stage2c2 c2c (exact + successor chain)                            failures 0
stage2d1 d1d (ROLLED_BACK 증거)                                   수정하지 않음
원장 SHA256                                                       전부 불변
```

## 31. 신규 원장 verify

```
d11a_blend_backups.jsonl   10행 · all · unhashed 0 · mismatch 0 · failures 0
d11b_blocked_reference.jsonl    미생성 (이동 미실행)
d11c_license_resolution.jsonl   미생성 (이동 미실행)
```

## 32. 5k FrameSpec

```
accepted 4,313 / rejected 687
sha256 938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39   동일
```

## 33. 5k proposal

```
accepted 4,439 / digest 3cd365eec96d1009… / 12/12 checks passed   동일
```

## 34. Blender no-render

```
images 603 · absolute 0 · missing 0 · textures 158 · distractors 356 · hdri 1
Dist_ 209 · node image missing 0 · active scene 8cb4109adc6d3213… 불변
렌더 0
```

## 35. rollback 가능 여부

가능하다. D11A 원장이 `rollback_source`/`rollback_destination`/`source_sha256` 를 갖고
있고, registry 전환은 tracked 파일이라 git 으로 완전 복원된다. 절차는 `rollback_plan.md`.

## 36. D11_SCOPE_COMPLETE

**false.** D1D 10건은 완료했으나 BLOCKED_REFERENCE·BLOCKED_UNKNOWN 의 실이동이 hash
예산으로 미실행이다.

## 37. FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE

**false.** UNKNOWN 0 · unclassified 0 · broken ref 0 · exclusion leak 0 · chain 검증 완료 ·
KEEP/quarantine 문서화 완료는 모두 충족했지만 BLOCKED 8건 처리가 미완이다.

## 38. FULL_PHYSICAL_MINIMAL_TREE

**false.** top-level 74 = 권장 8 + quarantine 1 + 잔여 65.

## 38.5 작업 중 규율 위반 1건 (발견·복구)

§1-F 기준선 verify 가 Stage 2-D1 원장 2개의 `verified_at` 타임스탬프를 갱신했다(멱등 수정 **전**이었다). 데이터·해시·경로는 전 행 동일했고 타임스탬프만 바뀌었다.
`git checkout 1577e25 --` 로 복구했고, 복구 후 verify 재실행에서 원장이 다시
바뀌지 않음을 확인했다(멱등). 상세: `regression_results.md`.

```
d1b_corrupt.jsonl   1행 · d1a_packages.jsonl 14행 -> 복구 완료 · dirty 0
기존 원장 수정        최종 0
```

## 39. git diff

```
tracked 변경
  scripts/data_prep/manage_pallet_data_layout.py        chained-ledger + D11 policy
  scripts/data_prep/blender/pallet_data_paths.py        resolve_config_value + --resolve
  scripts/data_prep/blender/tests/test_successor_ledger_chain.py   신규 31 테스트
  config/synthetic/pallet_paths.yaml                   신규 key 4
  config/default.yaml · config/stage3_selftrain.yaml   registry 참조
  scripts/train_dope.sh · self_training/self_train.py  resolve 경유
  scripts/data_prep/{postprocess_v3,visualize_pretrain,visualize_inference,
                     evaluate_on_val}.py               registry 조회
  scripts/data_prep/isaac_sim/generate_all.sh          registry 조회
  scripts/data_prep/blender/gen_palletobj_v1.py        registry 조회
  reports/data_pallet_cleanup/grouped_inventory.csv    266 -> 276
  reports/data_pallet_cleanup/stage2d11/               신규 (보고서 + 원장 1)
gitignored (커밋 대상 아님)
  data/pallet/manifests/{archive,path_map,assets}.csv
git add -A / git add . 사용 0
```

## 40. commit / push

```
commit  0
push    0
```

사용자 승인 없이 commit·push 하지 않는다. 데이터 생성·pilot·모델 학습을 자동 시작하지
않는다.

---

## 최종 수치

```
D1.1-A selected / verified / rolled_back    10 / 10 / 0
D1.1-B selected / verified / rolled_back     4 /  0 / 0   (registry 전환만 완료, 이동 미실행)
D1.1-C selected / verified / rolled_back     4 /  0 / 0   (판정만 완료, 이동 미실행)
전체 이동 row                                10
전체 이동 files                               10
전체 이동 bytes                    2,400,984,463  (2.24 GiB)
pre-hash read bytes               2,400,984,463
post-hash read bytes              2,400,984,463
SHA256 mismatch                              0
unhashed                                     0
prior ledger mapped missing                 10
prior ledger unmapped missing                0
registry key before / after              24 / 28
current broken refs                          0
exclusion leaks                              0
UNKNOWN remaining                            0
KEEP remaining                              10  (blend 6 + weight 4)
quarantine remaining                         3  (isaac_assets · NoAI USD · noai_baked 3종)
top-level unexpected remaining              65  (4.27 GiB)
archive depth-1 unexpected remaining       136
data 삭제                                    0
ZIP 삭제                                     0
package 수정                                 0
압축해제                                     0
weight 이동                                  0
isaac_assets 이동                            0
NoAI USD 이동                                0
Blender 렌더                                 0
모델 학습                                    0
기존 원장 수정                                0  (위반 1건 발견 후 복구)
commit                                       0
push                                         0
```

## 다음 단계에 필요한 결정

```
1  hash 예산      D11B 32.29 GiB + D11C 29.04 GiB = 61.33 GiB 승인 여부
                 (승인 시 두 cohort 를 순차 실행하면 이동이 끝난다)
2  D1-003        C2C 구성원이라 successor chain 추가 필요 — D11A 와 동일 방식, 검증됨
3  잔여 65 + 136  Stage 2-A archive.csv 계획(executed=no 202행) 재활성화 검토
4  weight 4      목적지 결정 + 별도 승인
```
