# §10 `_DISTRIBUTION_EXCLUDE.txt` 복구

## 수정 전 상태 [확인]

Stage 1 이 "5/5 stale" 로 보고한 그대로였다. 릴리스 게이트가 **아무것도 걸러내지 못하는** 상태.

```
파일에 적힌 경로              실제 위치                              판정
──────────────────────────────────────────────────────────────────────────────────
isaac_assets/                data/pallet/isaac_assets               OK
_noai_quarantine_usd/        archive/_noai_quarantine_usd           STALE
_pallet_catalog_0123/        archive/_pallet_catalog_0123           STALE
_efront_12kp_check/          archive/_efront_12kp_check             STALE
_floor_applied14/            archive/_floor_applied14               STALE
_floor_compare/              archive/_floor_compare                 STALE
_removed_noCC_background/    (이 트리에 없음)                         STALE(존재하지 않음)
```

## 수정 내용

- stale 5건을 `archive/` 아래 실제 위치로 정정.
- 존재하지 않는 `_removed_noCC_background/` 는 **삭제하지 않고 주석으로 강등**했다
  (과거 격리 사실은 기록으로 남기되, 검증기가 stale 로 잡지 않게).
- ledger:25/70 이 명시한 **NoAI baked legacy 렌더 산출물 4종을 신규 추가**했다 —
  이전에는 목록에 아예 없어서 릴리스 시 그대로 들어갈 수 있었다.
  `archive/training_data/`, `archive/training_data_v4/`,
  `archive/training_data_v4_split/`, `archive/train_4pallet_mask_v1/`
- 파일 상단에 형식 규약(상대경로, `#` 주석, 디렉토리는 `/`)과 검증 명령을 명시.

## 신규 검증기

`scripts/data_prep/verify_distribution_exclusions.py`

```
검사 항목
  - 빈 줄 / '#' 주석 처리
  - 각 entry 가 data/pallet 내부인지 (commonpath 기반, 문자열 prefix 아님)
  - '..' escape 없음 / 절대경로 아님
  - entry 가 실제로 존재하는지 (stale 탐지)
  - 중복 entry
  - release/ 트리가 exclude 대상을 포함하지 않는지 (leak 탐지)
exit code  0 = 이상 없음 / 1 = 하나라도 문제
```

## 검증 결과 [확인, 실행함]

```
$ python scripts/data_prep/verify_distribution_exclusions.py
entries      : 10
  OK isaac_assets
  OK archive/_noai_quarantine_usd
  OK archive/_pallet_catalog_0123
  OK archive/_efront_12kp_check
  OK archive/_floor_applied14
  OK archive/_floor_compare
  OK archive/training_data
  OK archive/training_data_v4
  OK archive/training_data_v4_split
  OK archive/train_4pallet_mask_v1
problems     : 0
release leaks: 0
exit=0
```

CSV: `distribution_exclusion_audit.csv`

## 계속 이동 금지로 유지한 것 [확인]

```
경로                                  이유
────────────────────────────────────────────────────────────────────────
data/pallet/archive/_noai_quarantine_usd   NoAI 격리 — 격리 위치 자체가 라이선스 근거 (ledger:60)
data/pallet/isaac_assets                   NVIDIA Isaac Sim EULA (ledger:103, B6)
archive/ NoAI baked legacy datasets        ledger:25,70 — 로컬 보관만, 공개 불가
```

Stage 2-B 에서 이 3군은 **한 파일도 옮기지 않았다.**
