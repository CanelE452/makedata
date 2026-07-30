# Stage 2-D1 최종 구조 감사

## data/pallet top-level (74개)

```
권장 구조                     상태
────────────────────────────────────────────────────────────────
assets/                      ✓  현역 자산 (D1 미접촉)
reference/                   ✓  golden reference · 실사 (D1 미접촉)
runs/                        ✓  run 산출물 (D1 미접촉)
manifests/                   ✓  로컬 metadata (D1 에서 갱신)
release/                     ✓  (비어 있음)
archive/                     ✓  ★ D1 이 정리한 대상
README.md                    ✓
_DISTRIBUTION_EXCLUDE.txt    ✓  (D1A/D1C 이동 반영해 갱신)
isaac_assets/                —  KEEP_QUARANTINE (NVIDIA EULA, 이동 금지)
────────────────────────────────────────────────────────────────
그 외                        65개  ← 아래 분류
```

`data/pallet/*.zip` = **0개**. 루트에 남은 package 는 없다 (before 15개).

## 권장 구조 밖 65개 — 분류

```
분류                  개수   bytes(MiB)   성격
──────────────────────────────────────────────────────────────────────────────
LOG                    40         8.30   생성·렌더 로그 (*.log · *_log.txt)
ONE_OFF_SCRIPT         11         0.03   일회성 repack/zip/stress 스크립트 (*.py)
DIAGNOSTIC_RUN_DIR     10     4,349.29   _v2_* · _tmp_ph · _trunc_*_example 진단 산출물
OUTPUT_DIR              3        12.14   eval_results · logs · v2_dryrun_audit
DIAGNOSTIC_IMAGE        1         0.95   _floor_catalog.png
──────────────────────────────────────────────────────────────────────────────
합계                   65     4,370.71
```

**이 65개는 Stage 2-D1 계획(40행)에 애초에 포함되지 않았다.** 48개는 Stage 2-A 의
`manifests/archive.csv` 에 이동 계획이 이미 있으나 `executed=no` 다(그 파일의
executed=no row 는 202개). Stage 2-A 는 "코드 참조 없는 저위험 run 만" 옮기는 정책이었고
이들은 그 범위 밖이었다.

판정 분류:

```
BLOCKED        0   (D1 계획의 BLOCKED 8건은 archive/ 안에 있고 top-level 아님)
KEEP           1   isaac_assets (quarantine)
UNKNOWN        0   65개 전부 성격이 확정돼 있다 (log / script / 진단 산출물 / 출력)
stale empty    0
management     2   README.md · _DISTRIBUTION_EXCLUDE.txt
미정리 잔여     65   위 표 — 이동 계획은 있으나 미실행
```

## archive/ depth-1 (151개, before 166)

```
D1 이 만든 semantic 컨테이너와 내용
────────────────────────────────────────────────────────────────────
archive/packages/
├── background_sources/          3   (Stage 2-C2 C2A 이동분)
├── dataset_bundles/            14   ★ D1A
└── corrupt/                     1   ★ D1B (train_palletobj_v1.zip, 손상 보존)
archive/legacy_datasets/
├── redistributable/            11   ★ D1C
├── noai_baked/                  3   ★ D1C (릴리스 제외 유지)
└── partial/                     1   ★ D1C
archive/legacy_scenes/
├── snapshots/                   0   (D1D rollback — 폴더는 삭제하지 않았다)
└── blender_backups/             0   (같음)
```

`failed/` 는 해당 row 가 없어 만들지 않았다. **빈 폴더를 삭제하지 않았다.**

archive depth-1 이 166 → 151 인 것은 dataset 15개가 `legacy_datasets/` 아래로 한 단계
내려갔기 때문이다 (packages 는 이미 depth-1 컨테이너였다).

archive/ 에 남은 나머지 136개는 D1 계획 밖의 진단·중간 산출물이다 (`_addon_pilot*` ·
`_cam_test*` · `_floor_*` 등) — Stage 2-A 가 semantic 하위폴더로 계획했지만 미실행.

## 최종 판정 — 둘 다 쓰지 않는다

### D1_READY_SCOPE_COMPLETE → **미달**

조건: READY 40건 전부 VERIFIED / mismatch 0 / rollback 가능

```
READY 40건 전부 VERIFIED   ✗  30/40 VERIFIED, 10건(D1D)은 rollback
mismatch 0                 ✓  SHA256 mismatch 0 / file count·bytes·relpath 전부 일치
rollback 가능               ✓  원장 3종 + rollback_source/destination 기록
```

10건이 VERIFIED 가 아니므로 이 라벨을 쓰지 않는다. 대신 사실을 그대로 쓴다:

```
D1_PARTIAL — 30/40 VERIFIED (130.14 GiB), 10/40 BLOCKED_BY_PRIOR_LEDGER (rollback 완료)
```

### FULL_DATA_PALLET_LAYOUT_COMPLETE → **미달**

```
top-level unexpected legacy entry = 0   ✗  65개 남아 있다
UNKNOWN = 0                             ✓  65개 전부 성격 확정
남은 BLOCKED/KEEP 위치가 정책상 허용     △  BLOCKED 8 · KEEP 12 는 허용되지만
                                           D1D 10건은 "현역 폴더에 cold 파일" 상태로 남음
active runtime old-path reference = 0   ✓  canonical fix_required 0
exclusion leak = 0                      ✓
```

BLOCKED 8 / KEEP 12 / D1D 10 / top-level 잔여 65 때문에 전체 정리는 끝나지 않았다.
**FULL 완료라고 쓰지 않는다.**

## 남은 일 (다음 단계 후보)

```
1  D1D 10건       원장 연쇄(chained ledger) 도입 후 이동, 또는 현 위치 유지 결정
2  BLOCKED_REFERENCE 4건  registry 키 등록 + 참조 전환 후 이동
3  BLOCKED_UNKNOWN 4건    v4 파생의 NoAI 상속 확정 (라벨 metadata 판독)
4  top-level 잔여 65개    log/script/진단 산출물 정리 — Stage 2-A archive.csv 계획 재활성화
5  archive/ 잔여 136개    같은 성격
6  UNREFERENCED_WEIGHT 4  목적지 결정 + 별도 승인
```
