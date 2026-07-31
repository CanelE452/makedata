# 배포 제외 목록 재구축 명세 (tracked 정본)

## 왜 이 문서가 필요한가

실제 제외 목록 `data/pallet/_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** 다
(`.gitignore` 가 `data/` 전체를 제외). 저장소를 clone 한 다른 머신에는 그 파일이 없다.
릴리스 패키징을 다른 머신에서 하면 제외 규칙이 통째로 사라진다.

이 문서는 tracked 파일이며, 아래 표만으로 그 파일을 정확히 재생성할 수 있다.
라이선스 근거 정본은 `_docs/dataset_license_ledger.md` 다.

## 최종 제외 목록 (16 entry, 2026-07-31 Stage 2-D2 기준)

경로는 전부 `data/pallet/` 기준 상대경로. 디렉토리는 끝에 `/`.

```
# 그대로 파일에 넣을 entry                                    사유              라이선스 클래스   근거
─────────────────────────────────────────────────────────────────────────────────────────────────────────
isaac_assets/                                                NVIDIA Isaac 소스   EULA/재배포금지   ledger B6
archive/_noai_quarantine_usd/                                NoAI 원본 USD 보관  NoAI             ledger B1
archive/superseded_runs/_pallet_catalog_0123/                작업 산출물         n/a (데이터셋 아님) Stage 2-D2 이동
archive/superseded_runs/_efront_12kp_check/                  작업 산출물         n/a              Stage 2-D2 이동
archive/superseded_runs/_floor_applied14/                    작업 산출물         n/a              Stage 2-D2 이동
archive/superseded_runs/_floor_compare/                      작업 산출물         n/a              Stage 2-D2 이동
archive/legacy_datasets/noai_baked/training_data/            NoAI baked 렌더     NoAI             ledger B1/25,70
archive/legacy_datasets/noai_baked/training_data_v4/         NoAI baked 렌더     NoAI             ledger B1
archive/legacy_datasets/noai_baked/training_data_v4_split/   NoAI baked 렌더     NoAI             ledger B1
archive/legacy_datasets/noai_baked/train_4pallet_mask_v1/    NoAI baked 렌더     NoAI             ledger B1
archive/packages/dataset_bundles/train_4pallet_mask_v1.zip   위 추출본의 ZIP     NoAI             ledger B7
archive/legacy_datasets/noai_baked/training_data_v4_split_GREYBUG/  PROVEN_NOAI  NoAI             ledger B8
archive/legacy_datasets/noai_baked/training_data_v4_split_bg1bak/   PROVEN_NOAI  NoAI             ledger B8
archive/legacy_datasets/noai_baked/training_data_v4_emptywood/      PROVEN_NOAI  NoAI             ledger B8
archive/legacy_datasets/noai_baked/training_data_v4_pilotA/         PROVEN_NOAI  NoAI             ledger B8
archive/packages/background_sources/                         원본 다운로드 ZIP   중복배포 방지     Stage 2-C2 C2A
```

`exists=True` 16/16 · problems 0 · leaks 0 · stale 0 · duplicates 0 · path escape 0
(`exclusion_final.csv` 가 기계 판독용 실측 결과).

## 파일 형식

```
# 주석은 '#' 이후. 빈 줄 무시.
# 경로는 data/pallet 기준 상대경로, 디렉토리는 뒤에 '/'.
```

## 검증

```bash
python scripts/data_prep/verify_distribution_exclusions.py
# 기대: entries 16 / problems 0 / release leaks 0
```

## 원칙

- **NoAI · EULA · UNKNOWN_LICENSE 는 절대 `redistributable/` 이나 `release/` 로 보내지
  않는다.** 이동 도구(`stage2d2-layout-completion`)가 목적지 수준에서 막는다.
- 추출본을 제외했으면 **대응 ZIP 도** 제외한다(ledger B7 이 잡은 누출 경로).
- 이미 제외된 디렉토리 **안**에 있는 압축본은 상위 규칙에 덮인다.
- 경로가 바뀌면 이 문서와 실제 파일을 **같이** 갱신한다. 검증기가 stale 을 잡는다
  (Stage 2-D2 에서 실제로 4건 잡았다).
