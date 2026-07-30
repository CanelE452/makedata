# Stage 2-D0.1 §11 — 전체 검증 결과

전부 **실제 실행**했다 [확인].

```
항목                                     기대치            실측                          판정
──────────────────────────────────────────────────────────────────────────────────────────────
A unit                                   >=646, skip 0     664 passed, skip 0, fail 0     PASS
B local integration                      >=31,  skip 0      31 passed, skip 0, fail 0     PASS
C golden overlay                         >=51,  skip 0      51 passed, skip 0, fail 0     PASS
D registry                               ok=24 missing=0   ok=24 missing=0 absent=0       PASS
E exclusion                              problems 0        entries 16 / problems 0 /      PASS
                                         leaks 0 stale 0   leaks 0 / stale 0 / dup 0
F transaction                            failures 0        아래 표                        PASS
G 수정된 경로 도구                        전부 0            old-active 0 / key-error 0 /   PASS
                                                           missing-input 0
H 5k FrameSpec                           938f387d          938f387d… 동일                 PASS
                                         4,313 / 687       4,313 / 687
  5k proposals                           3cd365ee, 12/12   3cd365ee… 4,439, 12/12 PASS    PASS
I Blender no-render                      abs 0 missing 0   abs 0 missing 0 Dist_ 209      PASS
                                         Dist_ 209
```

## A. Unit

```
python -m pytest scripts/data_prep/blender/tests/ -q
-> 664 passed in 147.50s
```

646 → 664 (+18). 신규 전부 `tests/test_destination_additions.py` — C2C exact allowlist
검증(tmpdir 전용, 실제 자산 미접촉). skip 0 / fail 0.

## B. Local integration

```
PALLET_DATA_INTEGRATION=1 python -m pytest scripts/data_prep/blender/integration_tests/ -q
-> 31 passed in 0.70s
```

환경변수 없이 실행하면 collection error 로 멈춘다(의도된 가드). 처음 그렇게 돌려
error 를 봤고, 환경변수를 주고 다시 돌려 31 passed 를 얻었다 — 이 실패는 회귀가 아니다.

## C. Golden overlay

```
python -m pytest scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py -q
-> 51 passed in 0.29s
```

golden reference 는 `reference/golden_overlay/trunc_addon_v1_pilot`(registry
`golden_overlay_reference`). skip 0 — Stage 2-B 이동 후에도 registry 조회로 붙는다.

## D. Registry

```
python scripts/data_prep/blender/pallet_data_paths.py --audit
-> ok=24 missing=0 absent_optional=0
```

키 23개 / 경로 24개(`pallet_model_roots` 가 2개). 이번 단계에서 registry 키를 추가하지
않았다 — 추가하면 이 기대치(24)가 흔들리고, dataset 키 등록은 Stage 2-D1 선행 작업으로
분리하는 것이 맞다.

## E. Exclusion

```
python scripts/data_prep/verify_distribution_exclusions.py \
  --csv reports/data_pallet_cleanup/stage2d01/exclusion_after.csv
-> entries 16 / problems 0 / release leaks 0 / exit 0
```

`--csv` 를 stage2d01 로 명시했다. Stage 2-B/C 보고서를 출력 대상으로 쓰지 않았다
(Stage 2-C2 에서 기본값이 `stage2b/distribution_exclusion_audit.csv` 를 덮어쓴 사고가
있었고, 그때 기본값을 stage-neutral 로 바꿨다).

before 11 entries → after 16. 추가분: `train_4pallet_mask_v1.zip` +
v4 파생 4종(GREYBUG · bg1bak · emptywood · pilotA).

## F. Transaction 원장

```
원장                          moves  files   sha256 checked  failures  hash mode
────────────────────────────────────────────────────────────────────────────────────
stage2a/move_transaction       146   6,921       6,921           0     selective-legacy=146
stage2b/b1_reference_materials   4   3,220       3,220           0     all=4
stage2b/b2_lighting_models       3      68          68           0     all=3
stage2b/b3_scene_assets          0       0           0           0     (none)
stage2c2/c2a_background_pkgs     3       3           3           0     all=3
stage2c2/c2b_background_asset    1      74          74           0     all=1
stage2c2/c2c_distractor_scene    2   1,336       1,334           0 ★   all=2
────────────────────────────────────────────────────────────────────────────────────
합계                           159  11,622      11,620           0
```

★ C2C 는 **exact expected-addition 모드**에서 failures 0 이다. strict 모드는 3 (원인:
manifest 생성 이후 정상 추가된 2개 파일). 상세·음성검증 5종은
`c2c_verify_semantics.md` / `c2c_verify_after.json`.

```
moved source missing        0
moved source hash mismatch  0
unexpected addition         0
expected addition missing   0
```

원장 파일 SHA256 전부 불변 — `fe1adc26…` · `43461e47…` · `0d0c06a8…` · `241f5c56…`.

## G. 수정된 경로 도구 실제 해석

수정 파일 20개(1차 12 + 2차 8)에 대해 registry 키 9건 + 경로 리터럴 58건 = 67항목 해석.

```
old active path resolution   0     (Stage 2-B/C2 이전 위치를 가리키는 실행 경로 없음)
registry key error           0
missing input path           0
출력 경로(실행 시 생성)       8     정상 — 결함 아님
원래 없던 자산                4     pallet_scene ×2 · real_unlabeled ×2 (Stage 2 회귀 아님)
```

★ 이 게이트가 실제로 결함 3건을 잡았다:

```
gen_palletobj_v1.py:569   save_as_mainfile 이 없어진 data/pallet/blender_scene/ 에 저장
                          -> 실행하면 옛 레이아웃을 다시 만들어냈다. 현재 폴더로 정정.
stage3_selftrain.yaml:83  pretrained_weights = weights/…/net_pallet_best.pth (부재)
self_train.py:16          같은 부재 weight  -> 둘 다 final_net_epoch_0060.pth 로 정정
```

`--help` / registry 조회로 확인했고, 비파괴 모드가 없는 대상은 경로 해석까지만 검사했다.

미해결로 남긴 것(범위 밖 · 이번 이동과 무관한 선존재 결함):

```
render_indoor_data.py:29  --output_dir default 가 다른 머신 절대경로
                          "C:/Users/User/Documents/GitHub/FoundationPose/data/pallet/test_indoor_v1"
                          출력 경로이고 Stage 2 이동으로 깨진 것이 아니다. 기본값을 바꾸면
                          동작이 바뀌므로 손대지 않고 보고만 한다.
```

## H. 5k 두 하네스

CURRENT runtime/config 코드를 수정했으므로 둘 다 재실행했다.

```
FrameSpec (sample-only)
  python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 --dump <path>
  accepted 4,313 / rejected 687
  reject 분해: v_below_min 111 · d_occ_fail 138 · penetration 1 · C1 130 · C2 307
  dump sha256 938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39  (동일)

proposal (accept-time quota)
  python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 \
    --out reports/data_pallet_cleanup/stage2d01/dryrun
  accepted 4,439 / 5,000 (88.78%)
  determinism replay sha256 3cd365eec96d1009…  run1 == run2
  12/12 checks PASS
```

두 값이 다른 것은 불일치가 아니다 — 하네스가 다르다(샘플링 단계 vs accept-time quota
단계). `--out` 을 반드시 명시한다: 기본값이 커밋된 `reports/v2_revision/` 산출물을 덮는다.

## I. Blender no-render

```
blender -b "$(… --key production_scene)" --python scripts/data_prep/blender/audit_blend_assets.py \
  -- --report-dir reports/data_pallet_cleanup/stage2d01/no_render --tag stage2d01_active

registry missing        0
images total          603   missing 0   absolute 0
  textures            158   distractors 356   hdri 1
node image missing      0
Dist_ roots           209   (distractor manifest rows 209)
HDRI decode         30/30   (v2 constrained pool 28)
floor decode        42/42   wood decode 27/27
active scene sha256   8cb4109adc6d3213…  (불변)
```

**렌더는 하지 않았다.** Blender 프로세스는 감사 스크립트만 실행하고 종료했다
(`Blender quit`). 사용자 GUI Blender 는 실행 중이 아니었으므로 종료한 것도 없다.
