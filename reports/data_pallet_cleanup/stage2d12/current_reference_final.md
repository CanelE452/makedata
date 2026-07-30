# Stage 2-D1.2 §7 — canonical CURRENT reference 최종 감사

생성: 2026-07-30 (D12B·D12C 이동 + registry 갱신 완료 후)
원본 CSV: `current_reference_final.csv` / 집계: `current_reference_final_summary.json`

## 0. 결론

```
canonical fix_required                      0 건
canonical 총 참조                       94,027
CSV 기록 행 (수정금지 대량분류 제외)         530
```

D1 · D1.1 과 **행 수(530) · fix_required(0) 가 동일**하다. D1.2 의 8건 이동(92,429 + 39,620 파일)
이 실행 표면의 참조를 하나도 깨뜨리지 않았다는 뜻이다 [확인 — 아래 재현 명령으로 재계산].

## 1. 범위 (이전 단계와 동일해야 비교가 성립한다)

D0.1 에서 정한 canonical scope = **git 추적 실행 표면**. `rg` 기본 동작이 `.gitignore` 를
따르므로 `data/` 는 스캔에서 빠진다. D1 · D1.1 도 같은 범위였다(둘 다 `data/pallet/` 내부
파일 행 0 — 교차 확인함).

재현:

```bash
rg -n --no-heading \
   -g '*.py' -g '*.sh' -g '*.ps1' -g '*.bat' -g '*.yaml' -g '*.yml' -g '*.json' -g '*.md' -g '*.jsonl' \
   -e 'data/pallet/' -e 'data\\+pallet\\+' \
   -e '["'"'"']data["'"'"']\s*,\s*["'"'"']pallet["'"'"']' \
   -e '["'"'"']data["'"'"']\s*/\s*["'"'"']pallet["'"'"']' \
   . > refscan_d12_canon.txt
REFOUTDIR=stage2d12 REFSCAN=refscan_d12_canon.txt \
REFOUT=current_reference_final.csv REFSUM=current_reference_final_summary.json \
python d12_refaudit.py
```

검출 형태 7종(D0.1 확정본 그대로): `literal` `literal_bs` `os_path_join` `pathlib`
`fstring` `shell_var` `yaml_value` `bare`.

## 2. 분류 분포

```
분류                          건수     CSV     성격
────────────────────────────────────────────────────────────────────────
REPORT_SNAPSHOT             92,864      -     당시 결과 스냅샷 — 수정 금지
TRANSACTION_MANIFEST           441      -     이동 원장 — 수정 금지
HISTORY                        192      -     과거 기록 — 수정 금지
CURRENT_TEST                   144    144     실제 경로를 단언하는 테스트
FALSE_POSITIVE_TEST_FIXTURE    113    113     tmpdir fixture (의도적 부재)
CURRENT_RUNTIME                 95     95     현행 실행 경로
CURRENT_DOC                     83     83     현재 문서
LEGACY_RUNTIME_FROZEN           74     74     일회성 진단 스크립트 (동결)
FALSE_POSITIVE_COMMENT          15     15     주석 — 실행 경로 아님
LEGACY_DOC                       6      6     구 문서
────────────────────────────────────────────────────────────────────────
총                          94,027    530
```

대량 4분류(93,497건, 전체의 99.4%)는 전부 "수정 금지" 성격이라 CSV 에서 빼고 집계만 남겼다
(넣으면 CSV 가 56MB 가 된다 — D0.1 §14 결정 그대로).

## 3. fix_required = 0 의 근거

`executable_path=True` 239건 중 대상이 **지금 존재하지 않는** 것은 25건이다. 25건 전부가
다음 둘 중 하나로 설명된다 — 그래서 깨진 참조가 아니다.

```
사유                                       건수   설명
──────────────────────────────────────────────────────────────────────────────
io_role = output                            20   스크립트가 실행 시 makedirs 하는 산출물 경로
pre_existing_missing                         6   Stage 1 inventory 0 + 이동 원장 0
                                                 = 애초에 이 저장소에 없던 자산 (겹침 1건)
──────────────────────────────────────────────────────────────────────────────
남는 것                                       0
```

pre-existing missing 4종 (Stage 2 이동으로 깨진 것이 **아님**, D0.1 에서 확정):

```
data/pallet/pallet_scene        Stage 1 inventory 부재 + 이동 원장 부재 (다른 워크스테이션 자산)
data/pallet/real_unlabeled      이동 원장 0 + Stage 1 inventory 0 (실사 풀 정본은 real_data_root)
data/pallet/test_render_v2      이동 원장 0 + Stage 1 inventory 0 (과거 임시 렌더 산출물 이름)
data/pallet/ndds3_pallet.pth    이동 원장 0 + 저장소 부재 (weights/ 로 대체됨)
```

## 4. ★ 범위를 넓혀 본 추가 발견 (canonical 밖 — 이번에 처음 스캔했다)

canonical scope 는 `.gitignore` 때문에 `data/pallet/` **안에 있는** 스크립트·문서를 한 번도
보지 않았다. D1.2 에서 `--no-ignore --hidden` 으로 한 번 넓혀 봤다(`_wide_scope_refs.csv`).

발견 11건 → 그중 **실제 문제 5건을 고쳤고**, 남은 6건은 고치면 안 되는 것이다.

### 4.1 고친 것 — `data/pallet/assets/README.md` (5건)

표의 오른쪽 열 제목이 `CURRENT 위치(2026-07-28 기준)` 이고 값이 구 경로였다:

```
before →  pallets/source/    원본 USD/GLB   data/pallet/models_usd/, pallets_v2_add/models/
          distractors/manifest/            data/pallet/distractors/
          scenes/experimental/             data/pallet/blender_scene/_sandbox_*.blend
          ...
after  →  열을 registry key 로 교체 (pallet_model_roots[0] / distractor_manifest / ...)
          + 빈 하위폴더는 "(비어 있음) — 실제 위치" 로 명시
          + 왜 바꿨는지 각주
```

이 열이 가리키던 `models_usd/` `distractors/` `textures_wood/` `textures_floor/`
`blender_scene/` 은 2-B/2-C2 에서 전부 이동해 **지금 하나도 존재하지 않는다**
(존재 여부 개별 확인함). 리터럴을 다시 적으면 같은 일이 반복되므로 registry key 로 바꿨다.
경로 정본은 `pallet_data_paths.py --audit` (ok=28 missing=0).

수정 근거: 이 파일은 D0.1 이 허용한 수정 대상(`data/pallet 의 README 류`)에 든다.

### 4.2 고치지 않은 것 (6건) — 동결·아카이브 스냅샷

```
파일                                                          왜 수정 금지
──────────────────────────────────────────────────────────────────────────────────────
_v2_pilot_2k/diagnosis/code/v2_pipeline.py:62                 진단 시점 코드 스냅샷.
_v2_pilot_2k/diagnosis/code/distractor_pool_v2.py:33          현역 정본은 scripts/data_prep/
                                                              blender/v2_pipeline.py 이고
                                                              그쪽은 canonical 감사 통과.
                                                              스냅샷을 고치면 "그때 뭘 돌렸나"
                                                              증거가 훼손된다.
archive/_efront_12kp_check/check_kp12_realdata.py:16          archive/ = 아카이브. 일회성 검사.
archive/_pallet_catalog_0123/render_pallet_catalog.py:18      archive/ = 아카이브. 일회성 렌더.
archive/_pallet_catalog_0123/render_pallet_catalog_side.py:18 동상.
archive/_noai_quarantine_usd/README.md:5                      NoAI USD 가 **원래 어디 있었는지**
                                                              를 남긴 provenance 기록.
                                                              구 경로가 기록의 내용이다.
```

이들이 현역 실행 표면이 아님을 확인한 근거: `v2_pipeline.py` 는 저장소에 2벌 존재하고
(`scripts/data_prep/blender/` = 현역, `data/pallet/_v2_pilot_2k/diagnosis/code/` = 스냅샷),
후자를 import·실행하는 코드는 저장소에 없다 [확인 — 전역 grep 0건]. `archive/` 아래는
정의상 "현재 파이프라인이 읽지 않는 과거 자산"이다.

분류기(`d01_refaudit.py`)가 이들을 `CURRENT_RUNTIME` 으로 잘못 매긴 이유: `_` 접두 동결
판정을 **basename 으로만** 하고, `data/pallet/archive/` 를 아카이브로 인식하는 규칙이 없다.
canonical scope 에서는 이 경로들이 애초에 스캔되지 않아 드러나지 않던 빈틈이다.
canonical 숫자(0)에는 영향이 없다 — 범위가 다르다.

### 4.3 남은 1건은 이 문서가 만든 것

`data/pallet/assets/README.md:40` 은 4.1 에서 내가 추가한 각주다 — "구 경로가 이러이러했다"
를 **일부러** 적은 줄이라 stale 이 아니다. registry 설명 주석과 같은 성격이며
(`FALSE_POSITIVE_COMMENT` 규칙이 줄 첫머리 `#` 만 보기 때문에 자동 분류되지 않는다),
수정 대상이 아니다.
