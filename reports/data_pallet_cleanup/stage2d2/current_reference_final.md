# Stage 2-D2 §17 — current reference 최종 감사

## A. Canonical scope (gitignore 준수 = 실행 표면)

```
fix_required        0
총 참조             (current_reference_final_summary.json)
```

이전 단계(D1/D1.1/D1.2)와 **같은 범위**다. 재현:

```bash
rg -n --no-heading \
   -g '*.py' -g '*.sh' -g '*.ps1' -g '*.bat' -g '*.yaml' -g '*.yml' \
   -g '*.json' -g '*.md' -g '*.jsonl' \
   -e 'data/pallet/' -e 'data\+pallet\+' \
   -e '["'"'"']data["'"'"']\s*,\s*["'"'"']pallet["'"'"']' \
   -e '["'"'"']data["'"'"']\s*/\s*["'"'"']pallet["'"'"']' . > refscan.txt
REFOUTDIR=stage2d2 REFSCAN=refscan.txt python d2_refaudit.py
```

검출 형태 8종: `literal` · `literal_bs` · `os_path_join` · `pathlib` · `fstring` ·
`shell_var` · `yaml_value` · `bare`.

### 이동 직후에는 0 이 아니었다

이동 후 1차 감사에서 **16건**이 걸렸다 — 전부 현재 문서(`_docs/`)가 옛 경로를 CURRENT 로
서술하고 있었다.

```
_docs/blender_mcp_onboarding.md            8   v2 진단 실행 명령 (출력·입력 경로)
_docs/experiments/v2_smoke50_continuous_eda_results.md  6   산출물 위치 서술
_docs/dataset_license_ledger.md            1   _tmp_ph 다운로드 provenance
_docs/blender_mcp_onboarding.md            1   출력 레이아웃 절 제목
```

§17 이 요구한 대로 **현재 문서가 old path 를 CURRENT 로 표현하면 수정**했다(40 치환).
수정 원칙은 참조의 역할을 따랐다:

```
출력(-> 여기 나온다)  ->  data/pallet/runs/{diagnostics,eval}/
입력(--dir 로 읽는다) ->  data/pallet/archive/superseded_runs/
```

과거 보고서·원장·history 의 old path 는 **정상 기록**이라 수정하지 않았다.

## B. Extended local scope (`--no-ignore`, data/pallet 내부 포함)

```
actionable fix_required   0
비-actionable             7
```

7건은 전부 고치면 안 되는 것이다:

```
파일                                                       분류                왜 수정 금지
──────────────────────────────────────────────────────────────────────────────────────────
archive/_noai_quarantine_usd/README.md:5                   PROVENANCE_RECORD   NoAI USD 가 원래
                                                                               어디 있었는지가
                                                                               기록의 내용이다
archive/superseded_runs/_v2_pilot_2k/diagnosis/code/       CODE_SNAPSHOT       진단 시점 코드 사본.
  v2_pipeline.py:62 · distractor_pool_v2.py:33                                 현역 정본은
                                                                               scripts/data_prep/
                                                                               blender/ 쪽
archive/superseded_runs/_efront_12kp_check/                ONE_OFF_ARCHIVE_TOOL 아카이브된 일회성 검사
  check_kp12_realdata.py:16
archive/superseded_runs/_pallet_catalog_0123/              ONE_OFF_ARCHIVE_TOOL 아카이브된 일회성 렌더
  render_pallet_catalog{,_side}.py:18  (2건)
assets/README.md:40                                        LOCAL_CURRENT_DOC   Stage 2-D1.2 가 남긴
                                                           (의도적 각주)        "구 경로가 이랬다" 각주
```

분류기(`d01_refaudit.py` 계열)가 이들을 `CURRENT_RUNTIME` 으로 매기는 이유는 `_` 접두
동결 판정을 basename 으로만 하고 `data/pallet/archive/` 를 아카이브로 인식하는 규칙이
없어서다. canonical 범위에서는 스캔되지 않아 canonical 숫자(0)에는 영향이 없다.
