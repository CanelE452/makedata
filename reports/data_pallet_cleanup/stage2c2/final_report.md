# Stage 2-C2 최종 보고 — 최종 레이아웃 이동 + blend rebase

## 1. 목적과 판정

루트에 남아 있던 세 자산군(`distractors/` · `blender_scene/` · `background/`)을 최종
`assets/` 구조로 옮기고, 옮긴 뒤 portable blend 의 상대경로를 새 위치 기준으로 rebase 한다.

**판정: 완료 · 승격함.** 중단 기준 해당 없음. `data/pallet` 루트에 남은 자산군은 없다.

## 2. branch / HEAD

```
분기 기준     26f21942b5ea38bf34af2659a6955a481a2c97b8  (= main = origin/main)
작업 branch   chore/data-pallet-stage2c2-final-layout
작업 전 상태   clean, 실행 중 blender.exe 0개, 전부 같은 볼륨 E:
commit / push  0 / 0
```

## 3. 이동 전 기준선

`baseline.md` / `baseline_checksums.json` — registry ok=22 missing=0 · unit 614 ·
integration 26 · golden 51 · Stage 2-A 146/6,921/0 (`fe1adc26…`) · Stage 2-B B1 4/3,220 ·
B2 3/68 (`43461e47…` / `0d0c06a8…`) · blend absolute 0 missing 0 textures 158 distractor 356 ·
5k FrameSpec 4,313 (`938f387d…`) · 5k proposals 4,439 (`3cd365ee…`) 12/12.

source 3곳: 1,411 파일 / 6,086,364,955 B (상한 10GB 이내) · symlink 0 · 접근불가 0.

## 4. background archive package 판정

```
파일                                        bytes        entries  open  SHA256          runtime refs
──────────────────────────────────────────────────────────────────────────────────────────────────
parking_lot.zip                          101,186,943      45     yes   b5d36f5f…            0
modular_buildings_industrial_area.zip     28,110,712      30     yes   3f233a6b…            0
modular_buildings_industrial_area..zip    28,110,712      30     yes   3f233a6b…            0
```

- 실측으로 정확히 3개. `.7z/.tar/.gz/.rar` 는 0개.
- 뒤 두 개는 **SHA256 동일**(중복 다운로드). 둘 다 보존 이동 — 삭제하지 않았다.
- gltf `buffers`/`images` URI 는 전부 `scene.bin` / `textures/*` 상대경로 → ZIP 의존 0.
- destination 은 **상대경로 보존**(basename 평탄화 금지).

## 5. blend 외부경로 target manifest

이동 **전에** 각 datablock 이 가리키는 파일의 절대경로 + SHA256 을 고정했다
(`blend_rebase_target_manifest.csv`, `--emit-target-manifest` 신규 모드).

```
603행   SKIP_PACKED_OR_GENERATED  88 · KEEP_RELATIVE 158 · REBASE 357 · BLOCKED 0
```

`action` 은 root 이동 여부가 아니라 **이동 후 디렉토리 기준으로 상대경로를 실제 계산해
기존 문자열과 비교**해서 정한다. 처음엔 root 기준으로 판정해 `REBASE 514 / KEEP 1` 이
나왔고(기대와 정반대), 계산 기준으로 고친 뒤 `158 / 357` 이 나왔다.

## 6. transaction policy

`transaction_policy.md` — `--policy stage2c2-final-layout` 신규. file entry ·
transaction_group + 그룹 원자성 · ZIP cohort 제한 · hash-mode all 강제.
신규 테스트 30개. **기존 테스트가 내 회귀를 잡은 건**(그룹 원자성이 Stage 2-A 계약을
깨뜨린 것)도 같은 문서에 기록.

## 7~9. 이동 결과

```
cohort  entry  source                  -> destination                             files    bytes        verify
────────────────────────────────────────────────────────────────────────────────────────────────────────────
C2A     file   background/*.zip 3      -> archive/packages/background_sources/        3   157,408,367  failures 0
C2B     dir    background/             -> assets/scenes/backgrounds/background/      74   133,646,354  failures 0
C2C     dir    distractors/            -> assets/distractors/library/             1,161 1,958,754,064  failures 0 ┐group
C2C     dir    blender_scene/          -> assets/scenes/production/blender_scene/   173 3,836,556,170  failures 0 ┘
────────────────────────────────────────────────────────────────────────────────────────────────────────────
                                                                                  1,411 6,086,364,955
hash-mode all · unhashed 0 · SHA256 mismatch 0 · license 12 보존 · overwrite 0 · 삭제 0
```

각 단계 직후 게이트:
- C2A → background 에 archive 잔존 **0** (아니면 C2B 시작 금지)
- C2B → gltf URI 결측 **0** (42 + 27), archive 0, source 소멸, destination 존재
- C2C → 두 source 소멸 · 두 destination 존재 · SHA256 전수 · 이 구간엔 Blender/테스트/생성기 미실행

## 10~13. candidate → stable

```
파일                                          bytes         sha256      역할
─────────────────────────────────────────────────────────────────────────────────────
synth_data_scene.blend                    358,917,479  46f436dc…  rollback 3 (원본, 불변)
synth_data_scene_portable.blend           358,898,907  5cad94e5…  rollback 2 (C1, 불변)
synth_data_scene_portable_stage2c2.blend  358,898,838  8cb4109a…  ★ active
```

rebase 357 · kept_relative 158 · 저장 전 게이트 전부 0 · rename 전후 sha256 동일.

```
재개방 검증(새 프로세스)     C1 portable   C2 stable   기대
─────────────────────────────────────────────────────────
image datablock                 603          603     동일
절대 외부경로 / 사용자별            0/0          0/0      0/0
missing path                      0            0        0
packed                           86           86     동일
textures / distractor / HDRI  158/356/1    158/356/1  동일
target path·SHA256 mismatch       -          0 / 0   (515건)
변경 datablock / 계획 외 변경        -        357 / 0
구조 diff                         -            0        0
```

## 14~16. registry · 코드 · exclusion

`registry_before_after.md` — ok=22 → 24 (신규 키 2개), missing 0.
배경 자산 경로는 새 리터럴을 박지 않고 **`relpath` + registry 조인**으로 전환했다.
옛 경로 스캔(`old_path_scan.csv`): CURRENT_RUNTIME / TEST / DOC 참조 **0**.
`distribution_exclusion_audit.md` — entries 11 / problems 0 / leaks 0.

## 17~19. manifest · old path · 테스트

`assets.csv` 17행(신규/갱신 8) · `path_map.csv` 175행(+5) · `archive.csv` 235행(+3).
original_path 는 보존하고 current_path 만 갱신했다.

```
default unit          646 passed (614 -> +30 정책 +2 registry 규칙), skip 0, fail 0
local integration      31 passed (26 -> +5), skip 0, fail 0
golden overlay         51 passed, skip 0
Stage 2-A 원장         146 / 6,921 / failures 0 · sha256 fe1adc26… 불변
Stage 2-B 원장         B1 4/3,220 · B2 3/68 · hash all · unhashed 0 · failures 0 · 원장 sha 불변
Stage 2-C2 트랜잭션     C2A 3/3 · C2B 1/74 · C2C 2/1,334 · hash all · unhashed 0 · failures 0
5k FrameSpec          4,313 / 687 · 938f387d… · 덤프 byte 동일
5k proposals          4,439 · 3cd365ee… · 12/12 PASS
```

## 20. Blender no-render

`final_no_render_audit.md` — absolute 0 · missing 0 · textures 158 · distractor 356 ·
HDRI 1 · node 누락 0 · Dist_ 209 · HDRI 30/30 · floor 42/42 · wood 27/27 · manifest 209 ·
background 2 asset 설정 정상.

★ 감사기 카운터가 옛 상대경로 문자열을 하드코딩해 `distractor=0` 이라는 **틀린 안심**을
낼 뻔했다. resolve 기준(위치 비의존)으로 고쳤다.

## 21. smoke

`smoke2_verification.md` — seed 7220, usable 2/2, 필수 93항목 실패 0, magenta 0,
RGB 2 + overlay 2 직접 확인. **두 프레임 모두 외부 distractor 가 실제 렌더**됐다
(f0000 CAUTION WET FLOOR + 캔, f0001 `Dist_utility_box_01` + 선반 + 탄약통) —
새 상대경로가 렌더 시점에도 해석된다는 직접 증거. 전체 렌더 2 frames (상한 3).

## 28. 남은 Stage 2-D

archive 대량 이동(legacy_datasets 87.7GB + packages 80.8GB) · 최상위 ZIP 약 80GB ·
isaac_assets · NoAI quarantine · `blender_scene` 안 `.blend1` 4개 + legacy snapshot 6개 정리
(SHA256 로 역할 확정해 둠) · packed 17건의 옛 temp 경로 문자열(inert) ·
`inventory.csv` → `grouped_inventory.csv` 개명 · GSO MTL 2건 결측(기존 상태).

## 29. git diff

```
수정   config/synthetic/{pallet_paths,blender,blender_train_4000}.yaml
       scripts/data_prep/manage_pallet_data_layout.py
       scripts/data_prep/blender/{blender_config,manage_blend_external_paths,audit_blend_assets}.py
       scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py
       scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py
       _docs/{data_pallet_layout,blender_mcp_onboarding}.md
       _docs/history/{2026-07-29,changelog}.md
신규   scripts/data_prep/blender/tests/test_stage2c2_layout_policy.py
       reports/data_pallet_cleanup/stage2c2/
gitignored(로컬)  data/pallet/manifests/*.csv · data/pallet/_DISTRIBUTION_EXCLUDE.txt ·
                  data/pallet/{README,assets/README}.md
```

## 30. rollback 가능 여부

**가능.** `rollback_plan.md` — C2C → C2B → C2A 역순, 전부 manifest 기반 rename 역이동.
삭제 없음. 그룹 실패는 도구가 자동으로 역순 롤백한다.

---

```
background package 이동 파일 수      3
background asset 이동 파일 수       74
distractor 이동 파일 수          1,161
blender_scene 이동 파일 수         173
전체 이동 bytes            6,086,364,955
SHA256 검사 수                   1,411   (+ blend rebase 대조 515)
mismatch 수                          0
blend rebase 수                    357   (KEEP_RELATIVE 158 별도)
absolute path before / after       0 / 0
missing path before / after        0 / 0
structure diff 수                    0
smoke frame 수                       2
magenta frame 수                     0
데이터 삭제                           0
legacy dataset 이동                  0
isaac_assets 이동                    0
NoAI quarantine 이동                 0
weight/checkpoint 이동               0
500 렌더                            0
40k 렌더                            0
commit                             0
push                               0
```
