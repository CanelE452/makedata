# stage2c2/dryrun — 5k dry-run 원자료 (이동 전/후)

`--out` 을 여기로 돌린 이유: `dryrun_v2_proposals.py` 의 기본 출력 경로가
`reports/v2_revision/dryrun_5k_*` 라 **이미 커밋된 산출물을 덮어쓴다**.

## 두 하네스, 두 지표 — before / after 동일 [확인]

```
파일                                       하네스                        지표
────────────────────────────────────────────────────────────────────────────────────────────
_raw_framespec_5k_{before,after}.jsonl     v2_pipeline.py --dump         5,000 FrameSpec JSONL
                                           (SAMPLE-ONLY)                 sha256 938f387d…
                                                                         accepted 4,313 / rejected 687
                                                                         두 파일 **byte 동일** (cmp)
dryrun_5k_{before,after}_checks.json       dryrun_v2_proposals.py        digest 3cd365ee… (동일)
_raw_dryrun_5k_{before,after}_proposals.csv (ACCEPT-TIME quota)          accepted 4,439, 12/12 PASS
dryrun_5k_{before,after}_summary.md
dryrun_5k_{before,after}_joint_eda.{png,pdf}
dryrun_5k_{before,after}_axis_marginals.csv
```

`before` = C2A 이동 전, `after` = stable 승격 후.

> 이 dry-run 은 bpy 를 쓰지 않는다 — `.blend` 를 읽지도 않는다. 폴더 이동이 sampling/geometry
> 층을 건드리지 않았다는 **불변식 확인**이지, 이미지 품질·수율에 대한 진술이 아니다.

## `_raw_*` 접두어 · commit 대상 [확인]

```
_raw_framespec_5k_before.jsonl        3,116,379 B
_raw_framespec_5k_after.jsonl         3,116,379 B   (before 와 byte 동일)
_raw_dryrun_5k_before_proposals.csv   1,278,061 B
_raw_dryrun_5k_after_proposals.csv    1,278,061 B
────────────────────────────────────────────────
_raw_ 합계                            8.4 MB
```

- **5MB 초과 파일은 0개** → 이번 단계에서 새로 `.gitignore` 에 추가한 항목은 없다.
- `*_joint_eda.png` 2장(4.6MB)은 기존 `.gitignore:25 *.png` 로 이미 제외된다.
- `stage2c2/` 전체는 17.6MB, 그중 **실제 commit 대상은 59파일 / 12.30MB**.

판단에 쓰는 요약은 `../baseline.md` · `dryrun_5k_*_summary.md` · `dryrun_5k_*_checks.json` 이다.
원자료를 지우지 않은 이유는 5k 결정성 주장의 근거를 숨기지 않기 위해서다.

## 재현

```bash
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 \
    --dump reports/data_pallet_cleanup/stage2c2/dryrun/_raw_framespec_5k_after.jsonl
python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 \
    --tag 5k_after --out reports/data_pallet_cleanup/stage2c2/dryrun
```
