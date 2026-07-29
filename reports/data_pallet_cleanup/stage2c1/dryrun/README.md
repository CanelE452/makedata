# stage2c1/dryrun — 5k dry-run 원자료

`--out` 을 여기로 돌린 이유: `dryrun_v2_proposals.py` 의 기본 출력 경로가
`reports/v2_revision/dryrun_5k_*` 이라 **이미 커밋된 산출물을 덮어쓴다.**
기준선 측정이 tracked 파일을 건드리면 안 되므로 별도 디렉토리로 뺐다.

## 두 하네스, 두 지표 [확인]

```
파일                                      하네스                       지표
──────────────────────────────────────────────────────────────────────────────────────
_raw_framespec_5k_{baseline,after}.jsonl  v2_pipeline.py --dump        5,000 FrameSpec JSONL
                                          (SAMPLE-ONLY, generate_specs) sha256 938f387d…
                                                                       accepted 4,313 / rejected 687
dryrun_5k{,_after}_checks.json            dryrun_v2_proposals.py       proposal 스트림 digest
_raw_dryrun_5k{,_after}_proposals.csv     (ACCEPT-TIME quota,          3cd365ee…
dryrun_5k{,_after}_summary.md              production 스트림)           accepted 4,439, 12/12 PASS
dryrun_5k{,_after}_joint_eda.{png,pdf}
dryrun_5k{,_after}_axis_marginals.csv
```

`baseline` = candidate 생성 전, `after` = stable 승격 후.
**FrameSpec 덤프 두 개는 byte 단위로 동일**(`cmp` 확인), proposals digest 도 동일.

## `_raw_*` 접두어

앞에 `_raw_` 가 붙은 4개가 대용량 원자료다(합 8.8MB). 판단에 쓰는 요약은
`../baseline.md` · `dryrun_5k_summary.md` · `dryrun_5k_checks.json` 이다.

```
_raw_framespec_5k_baseline.jsonl      3,116,379 B
_raw_framespec_5k_after.jsonl         3,116,379 B   (baseline 과 동일 바이트)
_raw_dryrun_5k_proposals.csv          1,278,061 B
_raw_dryrun_5k_after_proposals.csv    1,278,061 B
```

## gitignore 여부 [확인]

`git check-ignore` 결과 **ignore 대상이 아니다** — 지금 commit 하면 그대로 들어간다.
`reports/data_pallet_cleanup/stage2c1/` 전체는 **17.5 MB**이고 그중 이 폴더가 12.9 MB
(위 4개 8.8MB + joint_eda PNG 2장 4.7MB)다.

commit 전에 결정이 필요하다. 근거를 숨기지 않기 위해 지금은 지우지 않았다:

- 그대로 커밋 — 5k 결정성의 완전한 원자료가 저장소에 남는다 (+17.5MB)
- `_raw_*` 와 `*_joint_eda.png` 만 제외 — 요약·checksum·체크리스트는 유지되고 약 4.6MB
- 두 실행 중 `after` 쪽만 유지 — baseline 과 byte 동일하므로 정보 손실 없음 (약 -4.4MB)

## 재현

```bash
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 \
    --dump reports/data_pallet_cleanup/stage2c1/dryrun/_raw_framespec_5k_after.jsonl
python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 \
    --tag 5k_after --out reports/data_pallet_cleanup/stage2c1/dryrun
```
