# Stage 2-D1.2 §10 전체 회귀 검증

전부 **실제 실행**했다 [확인]. 아래 수치는 실행 출력에서 옮긴 것이다.

```
항목                                     기대치                실측                        판정
──────────────────────────────────────────────────────────────────────────────────────────────
A unit                                   745, skip 0           745 passed, fail 0          PASS
B integration                            >=31, skip 0          31 passed, skip 0           PASS
C golden                                 >=51, skip 0          51 passed, skip 0           PASS
D registry                               ok=28 missing=0       ok=28 missing=0             PASS
E exclusion                              problems 0            entries 16 / problems 0 /   PASS
                                         leaks 0 stale 0       leaks 0 / stale 0
F 기존 원장 9종                            failures 0            9원장 전부 0                PASS
   C2C (exact + chain x2)                failures 0            chain 11 file / 2 chain,    PASS
                                                               failures 0
G 신규 원장 D12B                           all / unhashed 0      4행 · all=4 · unhashed 0 ·  PASS
                                                               sha 92,429 · failures 0
   신규 원장 D12C                          all / unhashed 0      4행 · all=4 · unhashed 0 ·  PASS
                                                               sha 39,620 · failures 0
H 5k FrameSpec                           4,313 / 938f387d      4,313 / 938f387d            PASS
I 5k proposals                           4,439 / 3cd365ee      4,439 / 3cd365ee / 12-12    PASS
                                         12/12
J Blender no-render                      abs 0 missing 0       abs 0 · missing 0 ·         PASS
                                         Dist_ 209             node 누락 0 · Dist_ 209
K 파일 수 불변                             delta 0               363,090 -> 363,090          PASS
L 원장 멱등성                              재검증 후 dirty 0      git status: 원장 dirty 0     PASS
```

## A~C. 테스트

```
python -m pytest scripts/data_prep/blender/tests/ -q -rs
-> 745 passed in 86.20s     (skip 0)

PALLET_DATA_INTEGRATION=1 python -m pytest scripts/data_prep/blender/integration_tests/ -q -rs
-> 31 passed in 0.73s

python -m pytest scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py -q -rs
-> 51 passed in 0.28s
```

D1.1 대비 신규 테스트 0. D1.2 는 도구에 `stage2d12-final-moves` policy 와
`--successor-ledger-chain` 반복 지정을 추가했고, 둘 다 기존 31개 chain 테스트가 덮는
계약 위에서 동작한다(중복 prior key 거부는 실행 중 exit 2 로 확인).

## D. registry

```
python scripts/data_prep/blender/pallet_data_paths.py --audit
-> ok=28  missing=0  absent_optional=0
```

D1.2 가 값을 바꾼 키 4개 포함 전부 실재. `registry_transition.csv` 에서
`source_exists_now=False` / `destination_exists_now=True` 4/4.

## E. exclusion

```
python scripts/data_prep/verify_distribution_exclusions.py
-> entries 16 / problems 0 / release leaks 0
```

D12B 직후 1회, D12C 직후 1회 돌렸다. D12C 직후에는 **problems 4 (STALE_ENTRY)** 가
나왔다 — v4 파생 4종의 옛 경로가 남아 있었다. 새 경로로 갱신하고 다시 돌려 0 을 확인했다.
`exclusion_before.csv` / `exclusion_after_d12b.csv` / `exclusion_after_d12c.csv` /
`exclusion_final.csv`.

## F. 기존 원장 — 회귀 없음

```
원장                                    failures
──────────────────────────────────────────────────
stage2a/move_transaction                    0
stage2b/b1_reference_materials              0
stage2b/b2_lighting_models                  0
stage2b/b3_scene_assets                     0
stage2c2/c2a_background_packages            0
stage2c2/c2b_background_asset               0
stage2d1/d1b_corrupt                        0
stage2d1/d1a_packages                       0
stage2d11/d11a_blend_backups                0
──────────────────────────────────────────────────
stage2c2/c2c_distractor_scene (exact +      0    successor chain: 11 file(s)
  expected-additions + chain x2)                 from 2 chain(s) / 인정된 이관 11
```

★ chain 은 **두 개를 모두** 줘야 한다. D11A chain 만 주면 D1.2 가 옮긴 1개가 MISSING
(failures 2), D12 chain 만 주면 D1.1 이 옮긴 10개가 MISSING(failures 11).

## G. 신규 원장

```
D12B_REFERENCE_MOVE     4 row · 92,429 파일 · 17,334,010,020 B (16.14 GiB)
  hash modes  all=4      unhashed 0
  pre  16.14 GiB / post 16.14 GiB
  sha256 checked 92,429   failures 0

D12C_PROVEN_NOAI_MOVE   4 row · 39,620 파일 · 15,588,789,193 B (14.52 GiB)
  hash modes  all=4      unhashed 0
  pre  14.52 GiB / post 14.52 GiB
  sha256 checked 39,620   failures 0
```

## H. 5k FrameSpec

```
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 --dump <tmp>.jsonl
-> accepted 4,313 / rejects 687
-> dump sha256 938f387d…      (D1.1 기준값과 동일)
```

## I. 5k proposals

```
python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 \
       --out reports/data_pallet_cleanup/stage2d12/dryrun_after
-> accepted 4,439 / 5,000 (88.78%)
-> determinism sha256 run1 = run2 = 3cd365eec96d1009…
-> [verdict] 12/12 checks passed
```

`dryrun_5k_proposals.csv` 의 SHA256 이 before(3a6e7c32)와 after(3a6e7c32) **동일**.
⚠️ `--out` 을 생략하면 기본값이 커밋본을 덮어쓴다 — 항상 명시했다.

## J. Blender no-render 감사

```
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b <production_scene> \
  --python scripts/data_prep/blender/audit_blend_assets.py -- \
  --report-dir reports/data_pallet_cleanup/stage2d12/no_render --tag d12_after

[audit] registry missing=0
[audit] pallets=['Pallet_0','Pallet_1','Pallet_2','Pallet_3'] Distractors_v2=True Dist_roots=209
[audit] images total=603 missing=0 absolute=0 textures=158 distractors=356 hdri=1
[audit] node image missing=0
[audit] HDRI 30/30 decode ok (v2 constrained pool=28)
[audit] floor 42/42  wood 27/27 decode ok
[audit] distractor manifest rows=209
```

**렌더는 하지 않았다** — 감사만. `-b`(백그라운드) 로 돌렸고 사용자 GUI 세션은 건드리지 않았다.

주의: blend 안의 오브젝트 이름 `Pallet_2`/`Pallet_3` 가 여전히 보이지만, 이것은 **이름**
이고 2026-07-24 재-bake 로 NoAI 목재 메시(`scene_2/3.usd` 유래)는 제거됐다(ledger B1,
zstd 해제 grep 으로 `scene_2.usd=0 · scene_3.usd=0 · Legacy_Pallet_2/3=0` 확인).

## K. 파일 수 불변

```
data/pallet   before  dirs 2,567  files 363,090  bytes 192,468,097,791
              after   dirs 2,567  files 363,090  bytes 192,468,109,581
              delta   dirs 0      files 0        bytes +11,790
```

bytes +11,790 의 출처를 전부 특정했다 — **자산·데이터셋은 1바이트도 안 바뀌었다**.

```
data/pallet/assets/README.md          +621     구 경로 열 -> registry key 열 (§7)
data/pallet/manifests/*.csv        +10,754     archive/path_map/assets 갱신 (§8)
data/pallet/_DISTRIBUTION_EXCLUDE.txt +415     D12C 경로 갱신 + 근거 주석 (§6.8)
────────────────────────────────────────────
                                   +11,790
```

셋 다 지시가 허용한 수정 대상이다. 별도로 보호 영역을 SHA256 으로 재확인했다:

```
blend_diffs 0 · weight_diffs 0 · package_diffs 0 · dataset_diffs 0
hash read 9.48 GiB   총 문제 0
```

`archive` +137,789,005 / `assets` −137,788,384 은 sandbox blend 1개 이동분이며
차이 621 이 README 수정분이다.

## L. 원장 멱등성

모든 원장을 재검증한 뒤:

```
git status --porcelain | rg 'transactions|\.jsonl'   ->  (없음)
```

원장 dirty 0. verify 가 최초 검증만 기록하기 때문이다 — 이게 없으면 재검증 때마다
`verified_at` 이 바뀌어 chain 의 prior SHA 결속이 깨진다(D1.1 에서 실제 발생).

## 실행하지 않은 것

```
모델 학습            0
데이터 생성          0
Blender 렌더         0   (no-render 감사만)
파일 삭제            0
ZIP 삭제/수정/해제    0
D11A 재이동          0
기존 원장 rewrite     0
isaac_assets 이동    0
NoAI USD quarantine 이동  0
active/rollback scene 이동  0
weight 이동          0
commit / push        0   (사용자 승인 대기)
```
