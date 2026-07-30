# hash / read budget 보고

상한: **20 GB** (`--max-full-hash-bytes` 기본값). 넘기면 읽지 않고 후보로만 보고한다.

## 실제 읽은 bytes [확인]

```
단계                                     mode              read bytes        GB
────────────────────────────────────────────────────────────────────────────────
--inventory (depth1/2 구조)              metadata                   0      0.000
--package-signature (archive 20개)       package-signature          0      0.000
   ZIP central directory 만 읽음. 압축 해제 0. testzip() 미실행.
weight SHA256 (29개 × 191.8MB)           full(승인 범위 내)  5,686,135,448      5.298
blend SHA256 (17개) + NoAI (3개)         full(승인 범위 내)  ~4,491,000,000      4.183
package CRC divergence (PNG 8개)         full(표적)             3,489,000      0.003
────────────────────────────────────────────────────────────────────────────────
합계                                                       ~10,180,000,000      9.48
```

**9.48 GB / 20 GB (47%)** — 상한 내에서 끝냈다. 거부(refused) 0건.

## 읽지 않고 남긴 것 — 비용과 이유

### LEVEL 4 (CRC 전수) package↔dataset 검증: **55.18 GB 필요 → 실행하지 않음**

`package_dataset_matches.csv` 의 LEVEL 3(STRUCTURAL_MATCH) 12건을
CONTENT_VERIFIED_BY_CRC 로 올리려면 추출 트리를 전부 읽어야 한다.

```
package                              대응 dataset                    CRC 비용
──────────────────────────────────────────────────────────────────────────────
train_palletobj_v3.zip               archive/train_palletobj_v3        9.95 GB
train_4pallet_mask_v1.zip            archive/train_4pallet_mask_v1     9.17 GB
train_palletobj_v2 (2).zip           archive/train_palletobj_v2        7.77 GB
train_palletobj_v2.zip               archive/train_palletobj_v2        7.77 GB
train_palletobj_v1 (2).zip           archive/train_palletobj_v1        7.76 GB
train_palletobj_addon_v1.zip         archive/train_palletobj_addon_v1  5.36 GB
test_blender_v69/64/70/68/v65/indoor 각 대응 dataset                   7.40 GB
──────────────────────────────────────────────────────────────────────────────
합계                                                                  55.18 GB  (> 20 GB)
```

→ **사용자 승인 대기.** 승인 시 `--max-full-hash-bytes 60000000000` 로 실행 가능.

### 대신 read 0 bytes 로 얻은 것 — package↔package CRC 대조

ZIP central directory 에는 **entry 별 CRC32 가 이미 들어 있다.** 추출 없이 ZIP 끼리
비교하면 내용 동등성을 0바이트로 판정할 수 있다. 이 경로로 다음을 확정했다.

```
쌍                                                        entries  path size CRC  LEVEL
────────────────────────────────────────────────────────────────────────────────────────
modular_buildings_industrial_area(.)zip ×2                    29   ✓    ✓    ✓      4  CONTENT_VERIFIED_BY_CRC
train_palletobj_v2.zip  <->  train_palletobj_v2 (2).zip    30,010   ✓    ✓    ✗      3  CRC 3건 불일치
test_blender_v68 <-> v70 <-> test_indoor_v1                 3,000   ✓    ✗    ✗      1  크기부터 다름
```

이어서 **불일치 파일만** 표적 CRC 검증(3.3 MB read)으로 어느 사본이 추출본과 맞는지 확정했다
(`package_crc_divergence.csv`). 55 GB 를 쓰지 않고 핵심 결론을 얻은 경로다.

### `zipfile.testzip()` 미실행

전체 데이터를 읽으므로 5 GB 이하 또는 명시 승인된 package 만 대상이라는 규칙에 따라
**한 건도 실행하지 않았다.** 손상 판정은 central directory 부재(EOCD 미검출)로 충분했다.

## Stage 2-D1 실행 시 예상 read

이동 트랜잭션은 `hash-mode all` 이라 source·destination 양쪽을 읽는다.

```
이동 후보 48건 / 163.03 GB  ->  예상 hash read 326.07 GB
```

D1 은 이 비용을 전제로 별도 승인이 필요하다. cohort 를 쪼개 단계별로 실행하면
한 번에 읽는 양을 줄일 수 있다(D1B corrupt 4.2GB → D1D blend 3.0GB → D1A packages
84.9GB → D1C datasets 82.3GB 순).
