# Stage 2-D1.2 최종 보고 — D11B / D11C 실제 이동

## 1. 목적과 최종 판정

**목적** — Stage 2-D1.1 이 예산 충돌로 남긴 잔여 2 cohort(`BLOCKED_REFERENCE` 4건,
`BLOCKED_UNKNOWN` 4건)를 실제로 옮겨 D11 범위를 닫는다.

```
판정                                        결과
──────────────────────────────────────────────────────────────
D12B_COMPLETE                               ✅ COMPLETE
D12C_COMPLETE                               ✅ COMPLETE
D11_SCOPE_COMPLETE                          ✅ COMPLETE
FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE     ❌ NOT COMPLETE
FULL_PHYSICAL_MINIMAL_TREE                  ❌ NOT COMPLETE
```

세 판정은 **서로 다른 질문**이다. D11 범위는 닫혔지만 `data/pallet` 전체 레이아웃 정책은
닫히지 않았다 — 근거는 §41~43.

## 2. branch / HEAD

```
branch  chore/data-pallet-stage2d12-final-moves
HEAD    3a6ade5313d89ccb976cd35fc154d1e7388daa13   (Stage 2-D1.1 종료 커밋)
commit  없음 — 사용자 승인 대기
```

## 3. baseline

`baseline_checksums.json` — 원장·chain·registry·도구 18개 파일의 SHA256.
`ledger_status_before.json` — 원장 13종의 row/moved/verified/files/bytes.
`filesystem_before.json` — D1.1 의 `filesystem_after.json` 을 그대로 사용
(**after + 이동 8건 역산 == D1.1 after** 로 검증, mismatch 0).

## 4. frozen scope

`frozen_scope.json` / `.csv`, `recomputed_from_filesystem = true`.
계획서 숫자를 재사용하지 않고 이동 직전 파일시스템을 다시 쟀다.

```
cohort                  row  files     bytes
────────────────────────────────────────────────────
D12B_REFERENCE_MOVE      4   92,429   17,334,010,020
D12C_PROVEN_NOAI_MOVE    4   39,620   15,588,789,193
────────────────────────────────────────────────────
합계                     8  132,049   32,922,799,213
```

scope CSV 는 SHA256 으로 JSON 에 결속돼 있고, 도구가 실행 시 재대조한다.

## 5. hash budget

```
cohort                  추정 읽기    실사용      한도     소진율
──────────────────────────────────────────────────────────────
D12B_REFERENCE_MOVE     32.287 GiB  32.29 GiB   36 GiB   89.7%
D12C_PROVEN_NOAI_MOVE   29.036 GiB  29.04 GiB   34 GiB   85.4%
──────────────────────────────────────────────────────────────
합계                    61.323 GiB  61.32 GiB   70 GiB   87.6%
```

`hash-mode=all` · `workers=1` · selective 강등 0 · 초과 0.

## 6. D12B row / files / bytes

```
move_id  source                                     -> destination                          files    bytes
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
D1-003   assets/scenes/production/blender_scene/    archive/legacy_scenes/snapshots/            1  137,789,005
         _sandbox_parking_lot_check.blend           _sandbox_parking_lot_check.blend
D1-033   archive/train_palletobj_v3                 archive/legacy_datasets/redistributable/ 40,002 10,682,796,255
                                                    train_palletobj_v3
D1-038   archive/training_data                      archive/legacy_datasets/noai_baked/      34,704  6,435,540,124
                                                    training_data
D1-053   archive/train_palletobj_v3_post_v1         archive/legacy_datasets/redistributable/ 17,722     77,884,636
                                                    train_palletobj_v3_post_v1
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
                                                                                            92,429 17,334,010,020
```

## 7. D12B registry before

```
registry key                            value_before
────────────────────────────────────────────────────────────────────────────────
legacy_sandbox_parking_lot_scene        assets/scenes/production/blender_scene/
                                        _sandbox_parking_lot_check.blend
legacy_train_palletobj_v3_root          archive/train_palletobj_v3
legacy_training_data_root               archive/training_data
legacy_train_palletobj_v3_post_v1_root  archive/train_palletobj_v3_post_v1
```

D1.1 이 이 키들을 신설하고 config·스크립트를 `registry:` 참조로 바꿔 뒀다.
그래서 D1.2 는 **실행 표면을 한 줄도 고치지 않고** 키 값만 바꿨다.

★ live reference 는 D1.1 CSV 값을 복사하지 않고 **다시 쟀다**. 복사했으면 registry 전환
이전 값이라 4건 전부 LIVE_REF 오탐이 됐다. 재측정 결과 3건은 0, 1건
(`generate_all.sh:42` 낡은 주석)은 진짜여서 갱신했다.

## 8. D12B pre-hash

`hash-mode=all`, 92,429 파일 / 17,334,010,020 B (16.14 GiB) 전수 SHA256.
unhashed 0.

## 9. D12B apply

same-volume `os.rename` 4회. overwrite 0, 삭제 0, cross-volume 0, symlink 0.
`transaction_group = D12B_REFERENCE_MOVE` (atomic — 일부 row 선행 이동 없음).

## 10. D12B registry after

```
registry key                            value_after
────────────────────────────────────────────────────────────────────────────────
legacy_sandbox_parking_lot_scene        archive/legacy_scenes/snapshots/
                                        _sandbox_parking_lot_check.blend
legacy_train_palletobj_v3_root          archive/legacy_datasets/redistributable/train_palletobj_v3
legacy_training_data_root               archive/legacy_datasets/noai_baked/training_data
legacy_train_palletobj_v3_post_v1_root  archive/legacy_datasets/redistributable/train_palletobj_v3_post_v1
```

```
python scripts/data_prep/blender/pallet_data_paths.py --audit
-> ok=28  missing=0  absent_optional=0
```

`registry_transition.csv`: source_exists_now=False 4/4, destination_exists_now=True 4/4.

## 11. D12B post-hash

sha256 checked **92,429** / post hash read 16.14 GiB / mismatch 0 / **failures 0**.

## 12. D12B successor chain

8건 전부 prior ledger 소속을 직접 조회했다.

```
D1-003  -> c2c_distractor_scene.jsonl / S2C2002    ★ chain 필요
나머지 3건 -> 소속 없음                              chain 불필요
```

`chains/c2c_distractor_scene_to_d12.json` (mapping 1). D1.1 의
`stage2d11/c2c_successor_chain.json` 은 **수정하지 않았다**.

C2C 검증은 **두 chain 을 모두** 줘야 통과한다:

```
D11A chain 만 -> failures 2  (D1.2 가 옮긴 1개 MISSING)
D12  chain 만 -> failures 11 (D1.1 이 옮긴 10개 MISSING)
둘 다         -> successor chain: 11 file(s) from 2 chain(s) / 인정된 이관 11 / failures 0
```

그래서 `--successor-ledger-chain` 을 반복 지정 가능하게 만들고, 중복 prior key 주장은
exit 2 로 거부하게 했다.

## 13. D12B rollback 가능 여부

가능. `d12b_reference_move.jsonl` 4행 전부 `rollback_source`/`rollback_destination` 보유.
`--rollback --manifest <원장>` 으로 역순 복구. 단 **D12C 를 먼저 되돌려야 한다**
(D12B 가 만든 `noai_baked/` 안에 D12C 가 들어갔다). 상세는 `rollback_plan.md`.

## 14. D12C row / files / bytes

```
move_id  dataset                        files    bytes
─────────────────────────────────────────────────────────────
D1-041   training_data_v4_split_GREYBUG 15,051  5,291,018,327
D1-042   training_data_v4_split_bg1bak  15,056  5,288,678,749
D1-043   training_data_v4_emptywood      9,031  4,820,265,222
D1-049   training_data_v4_pilotA           482    188,826,895
─────────────────────────────────────────────────────────────
                                        39,620 15,588,789,193
```

전부 `archive/legacy_datasets/noai_baked/<같은 이름>` 으로.

## 15. D12C provenance 재확인

D1.1 의 `PROVEN_NOAI` 판정을 **다시 믿지 않고** file_count/bytes 로 동일성을 재확인했다
(`provenance_verification.csv`, `identity_unchanged = True` 4/4).

```
dataset                        프레임   NoAI 프레임      %     mtime       재-bake 이전
────────────────────────────────────────────────────────────────────────────────────
training_data_v4_split_GREYBUG  5,000      3,286      65.7%   2026-06-17   yes
training_data_v4_split_bg1bak   5,000      3,272      65.4%   2026-06-16   yes
training_data_v4_emptywood      3,000      3,000     100.0%   2026-06-18   yes
training_data_v4_pilotA           120         76      63.3%   2026-06-16   yes
────────────────────────────────────────────────────────────────────────────────────
합계                            13,120      9,634      73.4%
```

라벨 JSON 13,122개 전수 스캔(표본 아님, 읽기 실패 0). `objects[].name` 에
`Pallet_2`/`Pallet_3` = `scene_2.usd`/`scene_3.usd` = "Old Wooden Pallet"(NoAI, B1).
**적극적 사용 증거**이지 "표식이 없다"는 소극적 근거가 아니다.

도구가 `PROVEN_NOAI` 는 `noai_baked/` 외 목적지로 못 가게 막는다
(`/redistributable/` `/packages/` `/unidentified/` `/release/` `/partial/` 거부).

## 16. D12C pre-hash

`hash-mode=all`, 39,620 파일 / 15,588,789,193 B (14.52 GiB) 전수. unhashed 0.

## 17. D12C apply

same-volume rename 4회. `transaction_group = D12C_PROVEN_NOAI_MOVE` (atomic).

## 18. D12C post-hash

sha256 checked **39,620** / post hash read 14.52 GiB / mismatch 0 / **failures 0**.

## 19. D12C successor chain

**불필요.** 4건 모두 prior ledger 소속 0 (직접 조회로 확인, "chain 이 안 만들어졌으니
없을 것"으로 넘기지 않았다).

## 20. exclusion 결과

```
python scripts/data_prep/verify_distribution_exclusions.py
-> entries 16 / problems 0 / release leaks 0 / stale 0
```

D12C 직후 1차 검사에서 **problems 4 (STALE_ENTRY)** 가 나왔다 — v4 파생 4종의 옛 경로가
남아 있었다. 새 경로로 갱신하고 재검사해 0 을 얻었다. NoAI baked 8종 전부 등재.

`exclusion_before.csv` / `after_d12b` / `after_d12c` / `exclusion_final.csv`.

⚠️ `_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** 다 — 저장소에 커밋되지 않는다.
다른 머신에서 릴리스를 만들면 이 파일이 없다. 근거 정본은 `_docs/dataset_license_ledger.md`.

## 21. license ledger

`_docs/dataset_license_ledger.md` 의 **B8 을 "미해결 MEDIUM" → "해소"** 로 바꿨다.

```
before  B8  미해결 MEDIUM  v4 계열 파생 4종의 NoAI 상속 미확정 — 보수적 제외 유지중
after   B8  해소           v4 계열 파생 4종 = PROVEN_NOAI 확정 (라벨 전수) + noai_baked 격리
```

본문에 dataset 이름 · PROVEN_NOAI 판정 · 근거 3단(적극적 사용 증거 / 자산 동일성 / 시점) ·
프레임·라벨 분모(13,120 / 13,122) · 최종 경로 4개 · `release_allowed=NO` ·
NoAI USD 원본 위치(`archive/_noai_quarantine_usd/`) · exclusion 이 gitignored 라는 주의를
모두 적었다.

"확정되지 않아 보수적으로 제외" → **"확정돼서 제외"** 로 성격이 바뀌었다.

## 22. local manifests

```
data/pallet/manifests/archive.csv    기존 row 갱신 7 / 신규 1 / 총 246   (d12_* 11열 추가)
data/pallet/manifests/path_map.csv   신규 8 / 총 223                    (pre_d12_path 등 4열 추가)
data/pallet/manifests/assets.csv     17 row / SHA256 변경 0 / 경로부재 0  (stage2d12_status 열)
```

`original_path` / `pre_d1_path` 는 지우지 않았다 — 이력이다.

`_sandbox_parking_lot_check` 의 `.blend`(D1.2 → `snapshots/`)와 `.blend1`(D1.1 →
`blender_backups/`)이 서로 다른 폴더인 것은 **확장자 규칙**이지 모순이 아니다 [확인].

## 23. grouped inventory

```
reports/data_pallet_cleanup/grouped_inventory.csv   276 -> 277 rows (removed 7 / added 8)
depth 분포 {1: 74, 2: 144, 3: 8, 4: 51}   entry_type {file 84, dir 193}
MOVED_STAGE2D1X row 48
data/pallet 실측 파일수 363,090 — 그룹 인벤토리이지 전수 manifest 가 아니다
```

`grouped_inventory_diff.md` 에 removed/added 전체 목록.

## 24. final tree

`final_tree.csv` **277 entry** (`final_tree.md` 에 해설).

D1.1 은 depth 1~3(233)까지만 봤다. D1.2 의 목적지는 semantic 컨테이너의 **손자**라
depth 3 까지면 이번에 옮긴 게 하나도 안 보인다 → **depth 4 추가**(+51).

```
★ UNKNOWN / 미분류               0
분류되지 않은 top-level ZIP       0
역할 불명 dataset                 0
current path / old path 중복      0
이동 완료 source 잔존             0
```

NoAI baked 8종이 `archive/legacy_datasets/noai_baked/` 한곳에 모였다.

## 25. 남은 KEEP

```
KEEP_QUARANTINE            1   isaac_assets/            4,543 파일 / 4.05 GiB
PLAN_ROW_KEEP_QUARANTINE   1   archive/_noai_quarantine_usd/   3 파일
```

둘 다 **이동 금지** 대상이다 (NVIDIA EULA / NoAI provenance 보관).

## 26. 남은 quarantine

위 2건이 전부. D1.2 는 quarantine 을 하나도 건드리지 않았다.

## 27. BLOCKED remaining

**0.** D1.1 이 남긴 `BLOCKED_REFERENCE` 4 · `BLOCKED_UNKNOWN` 4 를 이번에 전부 해소했다.

## 28. UNKNOWN remaining

**0.** `UNKNOWN_LICENSE` 4건은 `PROVEN_NOAI` 로 확정됐고, 구조 감사의 미분류도 0 이다.

## 29. current references

```
canonical fix_required   0
canonical 총 참조        94,027
CSV 기록 행               530     (D1 · D1.1 과 동일)
```

★ 이번에 **범위를 넓혀** `data/pallet` 내부까지 스캔했다(canonical scope 는 `.gitignore`
때문에 한 번도 본 적이 없다). 발견 11건 중 **5건을 고쳤다** —
`data/pallet/assets/README.md` 의 오른쪽 열이 2026-07-28 시점 구 경로
(`models_usd/` `distractors/` `textures_wood/` `blender_scene/` — 지금 하나도 없음)를
가리키고 있었다. 열 자체를 **registry key 로 교체**했다.

남은 6건은 고치면 안 되는 것이다 — `_v2_pilot_2k/diagnosis/code/` 진단 스냅샷(현역 정본은
`scripts/data_prep/blender/`), `archive/` 아래 일회성 스크립트, NoAI USD provenance README.
상세·근거는 `current_reference_final.md` §4.

## 30. registry

```
ok=28  missing=0  absent_optional=0
바뀐 키 4개 / source_exists_now=False 4 / destination_exists_now=True 4
```

## 31. unit

`745 passed` (skip 0, fail 0).

## 32. integration

`31 passed` (skip 0). `PALLET_DATA_INTEGRATION=1`.

## 33. golden

`51 passed` (skip 0).

## 34. prior ledger verify

기존 원장 9종 + C2C = **전부 failures 0**. C2C 는 exact allowlist +
expected-destination-additions + chain 2개로 통과, `인정된 이관 11`.

## 35. 신규 ledger verify

```
D12B  4행 · hash all=4 · unhashed 0 · sha256 92,429 · failures 0
D12C  4행 · hash all=4 · unhashed 0 · sha256 39,620 · failures 0
```

재검증 후 `git status` 로 **원장 dirty 0** 확인 — verify 멱등성 유지.

## 36. 5k FrameSpec

`accepted 4,313 / rejects 687`, dump sha256 `938f387d…` — D1.1 기준값과 동일.

## 37. 5k proposal

`accepted 4,439 / 5,000 (88.78%)`, determinism `3cd365ee…`, **12/12 checks passed**.
`dryrun_5k_proposals.csv` SHA256 before=after=`3a6e7c32`.

## 38. Blender no-render

```
registry missing=0 · images 603 missing=0 absolute=0 · node image missing=0
HDRI 30/30 · floor 42/42 · wood 27/27 · distractor manifest 209 · Dist_roots 209
```

**렌더는 하지 않았다** — 감사만(`-b` 백그라운드).

## 39. D12B_COMPLETE — ✅

selected 4 / moved 4 / verified 4 / failed 0 / rolled_back 0.
registry 4키 전환 완료, chain 1개 생성, C2C 통과, 옛 경로 잔존 0.

## 40. D12C_COMPLETE — ✅

selected 4 / moved 4 / verified 4 / failed 0 / rolled_back 0.
PROVEN_NOAI 4종이 `noai_baked/` 로, exclusion 갱신 완료, license ledger B8 해소.

## 41. D11_SCOPE_COMPLETE — ✅

D1.1 의 `residual_scope.csv` 는 **18행**이었다.

```
scope                   n   해소 단계
──────────────────────────────────────────────
D1D_ROLLBACK_SOURCE    10   Stage 2-D1.1 D11A (이동 완료)
BLOCKED_REFERENCE       4   ★ Stage 2-D1.2 D12B (이번)
BLOCKED_UNKNOWN         4   ★ Stage 2-D1.2 D12C (이번)
──────────────────────────────────────────────
                       18   전부 해소
```

BLOCKED remaining 0 · UNKNOWN remaining 0. **D11 범위는 닫혔다.**

## 42. FULL_DATA_PALLET_LAYOUT_POLICY_COMPLETE — ❌ NOT COMPLETE

권장 구조 밖에 **200개**가 남아 있다. 전부 Stage 2-A `archive.csv` 에 이동 계획이
있으나 `executed = no` 다.

```
위치                        n     크기        내용
────────────────────────────────────────────────────────────────────────
data/pallet/ depth 1       65    4.27 GiB   _v2_* 진단 run 10 · 로그 40 ·
                                            일회성 스크립트 11 · 출력 dir 3 · 이미지 1
archive/ depth 2          135    1.20 GiB   test_blender_v* 등 과거 렌더 산출물 100 ·
                                            _efront_12kp_check 등 일회성 검사 34 · 파일 1
────────────────────────────────────────────────────────────────────────
                          200    5.47 GiB
```

성격은 전부 확정됐다(UNKNOWN 0) — "뭔지 모르는 것"은 없다. 하지만 **권장 구조 안으로
들어가지는 않았다.** 이건 D1.2 의 범위가 아니었고, 범위를 넘어 손대지 않았다.

## 43. FULL_PHYSICAL_MINIMAL_TREE — ❌ NOT COMPLETE

```
빈 폴더                     7    삭제하지 않았다 (지시가 삭제 금지)
권장 구조 밖 entry        200    §42
삭제한 파일                 0
```

빈 뼈대 7개(`archive/{corrupt,legacy_assets,nonredistributable,superseded_runs,
unidentified}` + `test_blender_v35/v49`)는 다음 단계 분류의 목적지로 남겨 뒀다.

물리적 최소 트리는 **삭제 또는 추가 이동**을 요구하는데 둘 다 이번 범위 밖이다.

## 44. git diff

```
scripts/data_prep/manage_pallet_data_layout.py    | 241 ++++++++  stage2d12 policy + chain 반복
reports/data_pallet_cleanup/grouped_inventory.csv | 113 +++-----  재생성 (276 -> 277)
_docs/data_pallet_layout.md                       |  99 +++++++  §10 Stage 2-D1.2 절 추가
_docs/dataset_license_ledger.md                   |  61 +++++-   B8 미해결 -> 해소
reports/data_pallet_cleanup/                      |  15 +-       검증기 기본 출력 갱신
  distribution_exclusion_audit.csv                              (최종 상태 반영)
config/synthetic/pallet_paths.yaml                |   8 +-       키 4개 값 전환
scripts/data_prep/isaac_sim/generate_all.sh       |   4 +-       낡은 주석 갱신
CLAUDE.md                                         |   2 +-       archive 구조 설명 갱신
AGENTS.md                                         |   2 +-       동상 (CLAUDE.md 와 동일 문장)
_docs/history/changelog.md                        |   1 +        한 줄 요약
_docs/history/2026-07-30.md                       |  11 +        compact 마커 (hook 생성)

?? _docs/history/2026-07-31.md                                   작업 기록 (신규)
?? reports/data_pallet_cleanup/stage2d12/                        산출물 일체 (신규)

_docs/history/.last-compact-resume.md             |   4 +-  ← 지시가 허용한 유일한 dirty.
                                                              수정·복구·stage·commit 안 함.
                                                              (compact hook 이 쓴 것)
```

gitignored 라 diff 에 안 나오는 변경(로컬 파일):

```
data/pallet/_DISTRIBUTION_EXCLUDE.txt    +415 B   D12C 경로 갱신 + 근거
data/pallet/assets/README.md             +621 B   구 경로 열 -> registry key 열
data/pallet/manifests/{archive,path_map,assets}.csv  +10,754 B
```

### 5MB 초과 산출물 — commit 제외하지 않는다

```
22.98 MB  transactions/d12b_reference_move.jsonl
10.36 MB  transactions/d12c_noai_move.jsonl
```

둘 다 **재생성 불가능**하다 — 이동 전 pre-hash manifest(파일별 relpath/size/SHA256)는
이동이 끝난 뒤 다시 만들 수 없고, 이것이 **유일한 rollback·provenance 근거**다.
크기를 이유로 제외하지 않는다. 선례도 있다 — Stage 2-D1 의
`d1c_legacy_datasets.jsonl`(40 MB)이 이미 커밋돼 있다.

반대로 재생성 가능한 대용량은 제외한다: 참조 감사의 raw dump(88 MB)는 CSV 에 넣지 않고
집계만 남겼다(대량 4분류 93,497행 = 전체의 99.4%, 전부 "수정 금지" 성격).

## 45. commit / push 여부

**commit 0 / push 0.** 사용자 승인 대기.

branch `chore/data-pallet-stage2d12-final-moves` 는 base `3a6ade5` 에서 아직 움직이지
않았다. 새 데이터 pilot·모델 실험도 시작하지 않았다.

---

# 마감 수치

```
D12B  selected 4 / verified 4 / failed 0 / rolled_back 0
D12C  selected 4 / verified 4 / failed 0 / rolled_back 0

전체 이동 rows                    8
전체 이동 files             132,049
전체 이동 bytes      32,922,799,213   (30.66 GiB)

D12B pre / post hash read    17,334,010,020 / 17,334,010,020   (16.14 / 16.14 GiB)
D12C pre / post hash read    15,588,789,193 / 15,588,789,193   (14.52 / 14.52 GiB)
total hash read              65,845,598,426                    (61.32 GiB, 한도 70)

SHA256 mismatch                   0
unhashed                          0
prior ledger mapped missing      11   (chain 2개로 전부 증명 — 인정된 이관 11)
prior ledger unmapped missing     0

registry keys before / after      4 / 4   (전부 실재, ok=28 missing=0)
current broken refs               0
exclusion leaks                   0

BLOCKED_REFERENCE remaining       0
BLOCKED_UNKNOWN remaining         0
UNKNOWN remaining                 0
KEEP remaining                    2   (isaac_assets · _noai_quarantine_usd)
quarantine remaining              2   (동일 2건)
top-level unexpected remaining    0

data file count before / after    363,090 / 363,090
data 삭제                          0
ZIP 삭제                           0
package 수정                       0
압축해제                           0
weight 이동                        0
isaac_assets 이동                  0
NoAI USD 이동                      0
Blender 렌더                       0
데이터 생성                        0
모델 학습                          0
commit                            0
push                              0
```
