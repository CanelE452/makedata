# Stage 2-D0.1 최종 보고 — data/pallet 안정화

## 1. 목적과 최종 판정

Stage 2-D0 비파괴 감사가 찾은 결함 4종을 고치고, Stage 2-D1 archive 이동 계획을 실행
가능한 상태로 고정한다. **데이터 이동 0 · 삭제 0.**

```
[판정]  READY_FOR_STAGE_2_D1
        readiness gate 15항목 전부 PASS / FAIL 0.
        범위: status=READY/CORRUPT_MOVE_READY 인 40건 (132.37 GiB).
        나머지 20건은 이동 대상이 아니며 각각 이유가 확정돼 있다.
        Stage 2-D1 은 실행하지 않았다. commit·push 하지 않았다.
```

## 2. branch / HEAD

```
branch       chore/data-pallet-stage2d01-stabilization
HEAD         60e0860840fbacf4da8233e4adb33bcaed1c2b75  (= origin/main, 작업 전과 동일)
commit       0
push         0
```

## 3. 수정 전 기준선

```
data/pallet   dirs 2,560 · files 363,090 · bytes 192,468,045,942 (179.25 GiB)
registry      ok=24 missing=0
unit 646 · integration 31 · golden 51 (skip 0 / fail 0)
Stage 2-A/B/C2 원장 SHA256 4종 · active scene 8cb4109a…
C2C strict verify failures 3 (예상된 실패 — 원인 규명 완료)
exclusion entries 11 / release leak 5
blender.exe 0개 · data/pallet 관련 Python process 0개
```

## 4. canonical broken reference 수

```
before  44 행 (unique 39 · 파일 23)
after    0 행
```

**과거 보고서의 2 / 8 / 10 중 어느 것도 고르지 않았다.** 같은 검출기를 기준 커밋 트리
(`git grep 60e0860`)와 현재 트리에 각각 적용해 얻은 값이다.

★ 내 1차 감사는 19 로 **과소보고**였다. 두 가지를 틀렸다:

1. `literal` 패턴이 `data/pallet/` 앞에 따옴표를 요구해서 **YAML plain scalar 를 전부
   놓쳤다** — `train_dir: data/pallet/training_data/train`. 이 때문에
   `config/default.yaml`·`config/stage3_selftrain.yaml` 의 **깨진 학습 입력 경로 5건**을
   못 봤다.
2. rg 덤프를 `data/pallet/`·`data\pallet\` 두 패턴으로만 만들어서 **join-form 이 덤프에
   들어오지 않았다** — `os.path.join(root,"data","pallet","distractors")` 에는
   `data/pallet` 문자열이 없다.

패턴 7종(literal · literal_bs · os_path_join · pathlib · fstring · shell_var ·
yaml_value · bare)으로 덤프와 파서를 모두 고쳐 다시 셌다.

## 5. 수정한 runtime / config / test 목록

파일 25개 / 경로 관련 변경 줄 67 (`current_reference_fixes.csv`, git diff 에서 재구성).

```
config/default.yaml                              2  training_data -> archive/training_data (train/val)
config/stage3_selftrain.yaml                     3  같은 것 + pretrained weight 부재 정정
config/synthetic/isaac_sim.yaml                  5  procedural texture archive · 출력 dir · MISSING_ASSET 주석
config/synthetic/blender_train_4000.yaml         1  출력 base_dir
scripts/data_prep/compute_distractor_fill_ratio  4  distractors -> _pdp.get("distractor_root")
scripts/data_prep/isaac_sim/debug_pallet_orient  5  models_usd -> registry + ★PROJECT_ROOT 한 단계 부족 수정
scripts/data_prep/isaac_sim/generate_all.sh      3  training_data -> archive · hdri -> --key
scripts/data_prep/merge_and_validate.py          8  같은 리터럴 5회 -> BASE_DIR + env override
scripts/data_prep/postprocess_v3.py              3  dataset 입력 -> archive
scripts/data_prep/verify_keypoints.py            2  dataset 입력 -> archive
scripts/data_prep/visualize_inference.py         3  dataset 입력 -> archive (docstring + default)
scripts/data_prep/visualize_pretrain.py          2  dataset 입력 -> archive
scripts/data_prep/evaluate_on_val.py             1  사용 예시 -> archive
scripts/self_training/self_train.py              2  사용 예시 + 부재 weight
scripts/dope/run_dope_live.py                    2  부재 weight -> final_net_epoch_0060.pth
scripts/data_prep/blender/run_addon_v1.sh        2  씬 -> --key experimental_scene
scripts/data_prep/blender/gen_palletobj_v1.py    2  ★save_as_mainfile 이 없어진 옛 폴더를 재생성했다
scripts/data_prep/blender/gen_preview10.py       1  docstring 씬 -> --key production_scene
scripts/data_prep/blender/gen_topview_test.py    1  같은 것
scripts/data_prep/blender/run_trunc_addon.py     1  sandbox 씬 -> --key experimental_scene
_docs/attribution_cc-by_appendix.md              3  distractor · background 자산 위치
_docs/dataset_license_ledger.md                  6  저장경로 열 + B7/B8
_docs/method/step1_synthetic_data.md             1  USD 모델 경로
_docs/preprocessing/data_pipeline.md             3  배경 자산 · 학습 데이터 경로
scripts/data_prep/efront_calibration/README.md   1  측정 산출물 -> archive
```

고치지 않은 부재 자산 4종 (이동 원장 0 + Stage 1 인벤토리 0 = **Stage 2 회귀 아님**):
`pallet_scene` · `real_unlabeled` · `test_render_v2` · `ndds3_pallet.pth`.
`real_unlabeled` 를 `real_data_root` 로 바꾸지 않았다 — 같은 것이라는 근거가 없다.

## 6. 실제 실행 검증 결과

```
A unit 664 (646+18, skip 0 fail 0)      B integration 31      C golden 51
D registry ok=24 missing=0              E exclusion 16/0/0/0
F 원장 159 move / 11,622 files / failures 0
G 도구 해석 old-active 0 · key-error 0 · missing-input 0
H 5k 938f387d(4,313/687) · 3cd365ee(4,439, 12/12)
I Blender no-render abs 0 · missing 0 · Dist_ 209
```

★ G 게이트가 결함 3건을 추가로 잡았다: `gen_palletobj_v1.py:569` 의 옛 폴더 재생성
저장 경로 + 부재 weight 2건. 상세는 `regression_results.md`.

## 7. exclusion 누락 canonical 수

```
canonical 항목 19 / restricted 13 / release leak (before) 5
```

**Stage 2-D0 의 "누락 5건"을 그대로 복사하지 않았다.** 개수는 우연히 같지만 **멤버가
다르다**:

```
D0 가 leak 이라 한 pallet.zip  -> leak 아님.
   central directory 실측 결과 구성이 train_palletobj_v1 + v2 뿐이고 둘 다
   redistributable (B5 attribution 만 필요). 과잉 제외하지 않는다.
D0 가 놓친 training_data_v4_pilotA -> leak.
```

## 8. `train_4pallet_mask_v1.zip` 처리

```
추출본  archive/train_4pallet_mask_v1/   NoAI baked -> 이미 제외돼 있었다
ZIP     train_4pallet_mask_v1.zip 9.01 GiB -> 제외 목록에 **없었다** = 누출 경로
조치    exclusion 에 추가. verify 결과 OK.
```

같은 NoAI 산출물이 ZIP 경로로 릴리스에 새어 나갈 수 있는 상태였다. 다른 NoAI 압축본
(`training_data_v4_split.zip` 등)은 이미 제외된 디렉토리 **안**에 있어 덮인다 [확인].

## 9. license ledger 변경

```
B7  해소       NoAI dataset 압축본이 exclusion 에서 빠져 ZIP 경로로 누출 가능
B8  신규 MEDIUM v4 계열 파생 4종의 NoAI 상속 미확정 — 보수적 제외 유지
```

B8 판정 근거: 이름상 `training_data_v4*` 파생이고 본체는 NoAI baked 다. 그러나 파생본이
같은 blend 로 렌더됐는지 **라벨 metadata 로 확인하지 않았다**. 이름 유사성만으로 NoAI 를
단정하지도, 일반 archive 로 분류하지도 않는다 → `UNKNOWN_LICENSE` 로 두고 제외 유지.
잘못 배포하는 쪽은 되돌릴 수 없다.

## 10. release leak 검증

```
entries        11 -> 16
problems        0
release leaks   5 -> 0
stale           0
duplicate       0
exit code       0
```

## 11. C2C strict verify 실패 원인

```
S2C2002  RELPATH_SET extra=[…stage2c2.blend, …stage2c2_candidate.blend1]
S2C2002  FILE_COUNT   175 != 173
S2C2002  TOTAL_BYTES  4,554,353,915 != 3,836,556,170
```

manifest 생성 이후 destination 에 Stage 2-C2 가 정상 생성한 2개 파일이 추가돼 파일 수 ·
bytes · relpath set 이 어긋난다. **원래 옮긴 쪽은 전부 정상**: missing 0 /
sha256_checked 1,334 / moved_file_sha_mismatch 0.

## 12. 실제 destination extra 목록

"예상 extra 가 2개"라는 보고를 믿지 않고 현재 destination 을 manifest 와 대조해 실측했다.
결과가 2개였다:

```
relative_path                                        size          sha256      role
──────────────────────────────────────────────────────────────────────────────────────────
synth_data_scene_portable_stage2c2.blend             358,898,838   8cb4109a…   active_stage2c2_scene
                                                     mtime 2026-07-29 18:29:24
                                                     registry_keys=[production_scene]
synth_data_scene_portable_stage2c2_candidate.blend1  358,898,907   5cad94e5…   blender_automatic_backup
                                                     mtime 2026-07-29 16:56:38
                                                     registry_keys=[]
```

`.blend1` 의 해시가 Stage 2-C1 portable 과 같은 것은 정상이다 — candidate 를 C1 portable
에서 복제해 저장했으므로 Blender 백업 내용이 곧 C1 portable 이다 [확인].

## 13. exact expected-addition 정책

```
--expected-destination-additions <json>     신규 · 정본 (manifest_sha256 결속)
--allow-any-destination-additions           구 broad mode, deprecated 경고
--allow-destination-additions               단독 사용 시 argparse 오류
```

실패 조건: moved file 누락 / moved file hash mismatch / expected addition 누락 /
addition size·sha256 불일치 / allowlist 없는 extra / relative_path escape /
destination root 불일치 / manifest_sha256 불일치.

음성 검증 5종 전부 PASS (부분 allowlist → UNEXPECTED_ADDITION · broad flag 단독 → 오류 ·
manifest sha 위조 → 오류 · addition sha 위조 → 실패 · `../escape.txt` → 오류).
**broad allow 로 통과시키지 않았다.** Stage 2-A/B verify 동작은 바꾸지 않았다.
신규 테스트 18개(`tests/test_destination_additions.py`, tmpdir 전용).

## 14. C2C verify 최종 결과

```
모드                        failures  exit
strict                          3       1     ← 정상 추가 2개 때문
exact expected-additions        0       0     ★ 정본
```

## 15. inventory.csv grouped 판정

```
entry_type 열 존재 (dir/file)                                 ✓
file_count_recursive · total_bytes_recursive 집계 필드 존재      ✓
416 row vs data/pallet 파일 363,090개 — 전수 manifest 아님      ✓
Stage 1 "디렉토리 단위 인벤토리" 설명과 일치                    ✓
```

## 16. rename 결과

```
git mv reports/data_pallet_cleanup/inventory.csv \
       reports/data_pallet_cleanup/grouped_inventory.csv     416행 · 내용 변경 0
```

코드 참조 0건이라 migration warning / 자동 탐지 fallback 은 넣지 않았다.

## 17. current reference 갱신

```
수정   reports/data_pallet_cleanup/README.md        2곳
       reports/data_pallet_cleanup/rollback_plan.md 5곳
보존   history · report snapshot · transaction manifest 의 당시 파일명 (소급 수정 안 함)
```

## 18. memory sync 결과

project-local memory = `C:\Users\User\.claude\projects\E--CODING-GitHub-FoundationPose\memory\`
[확인]. 전역 사용자 memory · 다른 프로젝트 memory 는 수정하지 않았다.

```
stage2c1-portable-blend.md    D1 규모 "48건 163GB" -> "READY 40건 132.37 GiB"
stage2d01-stabilization.md    canonical 19 -> 44/0, 고친 파일 12 -> 25, D1 정본 + 선행조건,
                              스캔 패턴을 두 번 틀린 이유 기록
MEMORY.md                     인덱스 한 줄 갱신
```

지시문이 지적한 outdated 문장(`Stage 2-C2 에서 rebase 필요` · 이동 미완료 3건 ·
`Stage 2-C1 portable 이 active` · `Stage 2-D0 미실행`)은 이번 감사 시점에 **이미 남아
있지 않았다**. 상세는 `memory_sync_report.md`.

current 문서: `_docs/data_pallet_layout.md` §6 처리상태 + §7 신규(archive 내부 정리 상태 ·
D1 계획) · ledger B7/B8 · attribution · step1 · data_pipeline · README · rollback_plan.

## 19. D1 계획 재계산 결과

```
정본  reports/data_pallet_cleanup/stage2d01/proposed_stage2d1_moves_final.csv   60행
```

수정된 current reference graph · exclusion list · license ledger · grouped inventory
경로를 반영해 재계산했다. D0 의 `proposed_stage2d1_moves.csv`(48건 163.03GB)를 그대로
쓰지 않았다.

★ 계산 중 잡은 자체 버그 3개 (기록해 둔다):

```
under_registry() 가 양방향 prefix 검사를 해서 archive_root 하위 전부를 차단 -> READY 0.
  container root(archive_root · assets_root · pallet_data_root …)는 그 자식을 차단하지
  않는다. archive/foo -> archive/legacy_datasets/foo 로 옮겨도 archive_root 는 유효하다.
current_runtime_refs 열을 세지 않고 기본값 0 으로 두었다 -> READY 판정의 근거가 없었다.
  실측으로 채웠다.
leaf 이름 매칭에 후행 경계가 없어 trunc_addon_v1 이 trunc_addon_v1_pilot 을,
  training_data 가 training_data_v4 를 먹었다. 또 bare stem "pallet"(pallet.zip)이
  전역 오탐 395건을 만들었다. 경로 형태 + 양쪽 경계로 고쳤다.
```

참조 판정은 **라인 단위 근거**로 4분류했다 (`plan_reference_hits.csv`):

```
path_current    data/pallet/archive/<leaf>   -> 옮기면 깨진다 = READY 차단 (19건)
path_stale_old  data/pallet/<leaf> (부재)     -> 이미 깨져 있다. 차단 근거 아님 (19건)
leaf_only       구분자 없는 이름 단독          -> 경로 참조 아님
path_other      옛 폴더 · 절대경로 등
```

## 20. cohort 별 READY 수 · bytes

```
cohort                READY   bytes         files      목적지
────────────────────────────────────────────────────────────────────────────────────────
D1B_CORRUPT              1      4.22 GiB        1      archive/packages/corrupt/
D1D_BLEND_BACKUPS       10      2.24 GiB       10      archive/legacy_scenes/{snapshots,blender_backups}/
D1A_PACKAGES            14     75.21 GiB       14      archive/packages/dataset_bundles/
D1C_LEGACY_DATASETS     15     50.70 GiB  191,503      archive/legacy_datasets/{redistributable,partial}/
D1E_WEIGHTS              0          —            —     (별도 승인 — 목적지 미정)
D1F_QUARANTINE           0          —            —     (이동 금지)
────────────────────────────────────────────────────────────────────────────────────────
합계                    40    132.37 GiB  191,528      (142,134,662,870 B)
```

권장 실행 순서 D1B → D1D → D1A → D1C.

## 21. BLOCKED / KEEP 수

```
BLOCKED  8  (30.66 GiB)
  BLOCKED_UNKNOWN    4   v4 파생 — NoAI 상속 미확정 (ledger B8)          14.53 GiB
  BLOCKED_REFERENCE  4   CURRENT 경로 참조 살아있음                      16.13 GiB
      archive/training_data              runtime ref 10  (config 4 + script 6)
      archive/train_palletobj_v3         runtime ref  1  postprocess_v3.py:199
      archive/train_palletobj_v3_post_v1 runtime ref  1  postprocess_v3.py:202
      …/blender_scene/_sandbox_parking_lot_check.blend  ref 2  gen_palletobj_v1.py:4,569

KEEP    12
  KEEP_ACTIVE      2  registry active blend
  KEEP_ROLLBACK    4  rollback-critical blend
  KEEP_ACTIVE      4  UNREFERENCED_WEIGHT (data/pallet 밖 · 삭제 후보 아님)
  KEEP_QUARANTINE  2  isaac_assets(EULA) · NoAI USD
```

BLOCKED_REFERENCE 4건은 **§3 에서 방금 고친 참조들**이다. 지금 한 단계 더 내리면 같은
참조가 다시 깨진다 → Stage 2-D1 선행 단계로 **registry 키 등록 + 참조 전환**이 필요하다.

## 22. D1 readiness 판정

```
15 항목 PASS / 0 FAIL   ->   READY_FOR_STAGE_2_D1
```

항목별 실측은 `stage2d1_readiness.md`. READY 조건 11개를 코드로 강제했고
(`ready_or_block`), 사후 실측으로도 blocker 0 · source missing 0 · dest collision 0 ·
UNKNOWN 0 · quarantine 0 · rollback-critical 0 · runtime ref 0 · test ref 0 ·
cross-volume 0 을 확인했다.

## 23~25. unit / integration / golden

```
unit         664 passed, skip 0, fail 0   (기존 646 + 신규 18)
integration   31 passed, skip 0, fail 0   (PALLET_DATA_INTEGRATION=1)
golden        51 passed, skip 0, fail 0
```

## 26. registry

```
ok=24  missing=0  absent_optional=0     (키 23개 / 경로 24개)
```

이번 단계에서 registry 키를 추가하지 않았다 — dataset 키 등록은 D1 선행 작업으로 분리.

## 27. Stage 2-A/B/C2 원장

```
stage2a              146 / 6,921  failures 0   fe1adc266bd91963…  불변
stage2b b1             4 / 3,220  failures 0   43461e4749898529…  불변
stage2b b2             3 /    68  failures 0   0d0c06a849fcf201…  불변
stage2b b3             0 /     0  failures 0
stage2c2 c2a           3 /     3  failures 0
stage2c2 c2b           1 /    74  failures 0
stage2c2 c2c           2 / 1,336  failures 0 (exact) / 3 (strict)  241f5c569d2be924…  불변
```

## 28. 5k FrameSpec

```
accepted 4,313 / rejected 687
sha256   938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39   동일
reject   v_below_min 111 · d_occ_fail 138 · penetration 1 · C1 130 · C2 307
```

## 29. 5k proposals

```
accepted 4,439 / 5,000 (88.78%)
digest   3cd365eec96d1009…  run1 == run2 (determinism replay)
checks   12/12 PASS
```

두 하네스의 값이 다른 것은 불일치가 아니다 — sampling 단계 vs accept-time quota 단계다.

## 30. filesystem 불변

```
영역                     대조 대상        불일치
─────────────────────────────────────────────────
archive depth-1 entry        166             0
package (ZIP)                 20             0     path/size
blend                         17             0     path/size/SHA256
weight                        29             0     path/size/SHA256
legacy dataset               120             0     path/file_count/total_bytes
─────────────────────────────────────────────────
                                             0

data/pallet  before  dirs 2,560 · files 363,090 · bytes 192,468,045,942
             after   dirs 2,560 · files 363,090 · bytes 192,468,047,026
             delta   dirs 0 · files 0 · bytes +1,084
                     = data/pallet/_DISTRIBUTION_EXCLUDE.txt 2,502 -> 3,586 단독 (허용 변경)

hash read   9.48 GB (blend 4.18 + weight 5.30) — 예산 20 GB 내
```

## 31. git diff

```
31 files changed, 282 insertions(+), 77 deletions(-)
   수정 30 + rename 1 (inventory.csv -> grouped_inventory.csv)
   신규 untracked: scripts/data_prep/blender/tests/test_destination_additions.py
                   reports/data_pallet_cleanup/stage2d01/
git add -A · git add . 사용 0
```

`reports/data_pallet_cleanup/stage2d01/` 총 4.3 MB, **5 MB 초과 파일 없음**.
전량 참조 감사 CSV(56 MB)는 수정 금지 4분류(전체의 99.7%)를 제외해 109 KB 로 줄이고
집계는 `current_reference_audit_summary.json` 에 남겼다.

## 32. rollback 가능 여부

가능하다. 데이터를 옮기지 않았으므로 되돌릴 대상은 tracked 변경 30 + rename 1 +
`_DISTRIBUTION_EXCLUDE.txt` 1개뿐이다. 절차는 `rollback_plan.md`.
`_DISTRIBUTION_EXCLUDE.txt` 를 되돌리면 릴리스 게이트가 다시 뚫린다는 점을 명시했다.

## 33. commit / push 여부

```
commit  0
push    0
```

사용자 승인 없이 commit·push 하지 않는다. Stage 2-D1 도 자동으로 시작하지 않는다.

---

## 최종 수치

```
canonical broken CURRENT refs        before 44 (unique 39 · 파일 23)  ->  after 0
exclusion missing                    before 5   ->  after 0
release leaks                        before 5   ->  after 0
C2C unexpected additions             0
C2C expected-addition mismatch       0
grouped inventory rename             완료 (git mv · 416행 · 내용 변경 0)
D1 READY move count                  40
D1 READY bytes                       142,134,662,870 (132.37 GiB · 191,528 파일)
D1 BLOCKED count                     8
D1 KEEP count                        12
data 이동                            0
data 삭제                            0
ZIP 이동                             0
blend 이동                           0
weight 이동                          0
Stage 2-D1 실행                      0
Blender 렌더                         0
commit                               0
push                                 0
```
