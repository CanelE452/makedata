# D1B_CORRUPT — 손상 package 보존 이동

```
[판정]  VERIFIED  (1건 / 4,529,431,174 B = 4.22 GiB / file 1)
```

## 대상

```
move_id  D1-001
source   data/pallet/train_palletobj_v1.zip
dest     data/pallet/archive/packages/corrupt/train_palletobj_v1.zip
entry    file
분류      CORRUPT_PACKAGE
근거      n/a (central directory 부재)
```

## 이동 전 corrupt 상태 대조 [확인]

Stage 2-D0 판정과 지금 상태가 같은지 먼저 확인했다 — "손상"이라는 전제를 그대로
믿지 않았다.

```
D0 packages.csv   open_status=NO  open_error=BadZipFile: File is not a zip file
                  size_bytes=4,529,431,174
현재               존재=True  size=4,529,431,174  (동일)
                  zipfile.ZipFile() -> BadZipFile: File is not a zip file  (동일)
```

## 절차와 결과

```
단계                          결과
────────────────────────────────────────────────────────────────────
plan (hash-mode all)          1 move / hashed 1 / unhashed 0 / 3.2s
  pre SHA256 read             4,529,431,174 B (4.22 GiB) / 한도 10 GiB
  destination collision       0
  same volume (E:)            yes
apply (rename)                1 move / 0.1s
  source 존재                 False   (없어야 정상)
  destination 존재            True
  size                        4,529,431,174  (동일)
verify                        failures 0 / sha256 checked 1 / 3.5s
  post SHA256 read            4,529,431,174 B (4.22 GiB)
  pre == post SHA256          일치
예산 사용                      8.44 / 10 GiB (84.4%)
checkpoint                    VERIFIED
```

## corrupt 상태 보존 확인 [확인]

이동 **후에도** 열리지 않는다:

```
zipfile.ZipFile(dest) -> BadZipFile: File is not a zip file
```

복구·압축해제·재작성을 시도하지 않았다. `testzip()` 도 호출하지 않았다.
이동 후 ZIP open 을 성공시키려 하지 않는다는 규칙 그대로다.

**삭제하지 않았다.** 이 파일은 유일본이 아니지만(`train_palletobj_v1 (2).zip` 가
D1A 로 정상 이동) 그것이 삭제 근거가 되지 않는다 — 손상본 자체가 provenance 다.

## cohort 회귀 (§11)

```
registry                ok=24 missing=0
exclusion               entries 16 / problems 0 / leaks 0
C2C exact verify        failures 0
active scene SHA256     8cb4109adc6d3213…  (불변)
canonical CURRENT ref   fix_required 0
unit                    707 passed, skip 0, fail 0
integration              31 passed, skip 0, fail 0
```

## rollback

```
python scripts/data_prep/manage_pallet_data_layout.py --rollback \
  --manifest reports/data_pallet_cleanup/stage2d1/transactions/d1b_corrupt.jsonl
```

원장이 유일한 rollback 근거다. `rollback_source` / `rollback_destination` 필드에
원위치가 기록돼 있다.
