# Stage 2-C1 기준선 (candidate 생성 전)

일시: 2026-07-29 / branch `chore/data-pallet-stage2c1-portable-blend` (e72a719 = main = origin/main 에서 분기)

## PRE-FLIGHT [확인, 실행함]

```
repo root              E:/CODING/GitHub/FoundationPose
branch (작업 전)         main
HEAD                   e72a719689d60e149563b3b5e558fa800254ff67
origin/main            e72a719689d60e149563b3b5e558fa800254ff67   (동일)
git status             clean
작업 branch             chore/data-pallet-stage2c1-portable-blend  (신규, 기존 동명 branch 없음)
data/pallet            E:\CODING\GitHub\FoundationPose\data\pallet   (gitignored)
디스크 E:               free 1,262.4 GB / used 600.6 GB   (candidate 342MB 복사에 충분)
실행 중 blender.exe     0개  (Get-CimInstance Win32_Process 조회 결과 없음)
```

## source blend [확인]

```
path        data/pallet/blender_scene/synth_data_scene.blend
size        358,917,479 bytes
mtime       2026-07-24 19:39:00
sha256      46f436dc8d9302a6f857c62c1abcaf4e6fefdc10042ee646e9ef3dc3acbb7fb9
```

이 값은 `_docs/history/2026-07-26.md:10` 이 기록한
`46F436DC8D9302A6F857C62C1ABCAF4E6FEFDC10042EE646E9EF3DC3ACBB7FB9` 와 **동일** —
2026-07-26 이후 원본이 한 번도 수정되지 않았다는 독립 증거.

```
companion textures  data/pallet/blender_scene/textures     158 files /  64,033,891 bytes
distractors         data/pallet/distractors              1,161 files / 1,958,754,064 bytes
```

## 기준 측정값 [확인, 실행함]

```
항목                          값                          기대치           일치
──────────────────────────────────────────────────────────────────────────────────
A registry audit              ok=21 missing=0 absent=0    missing=0        ✓
B default unit                568 passed, skip 0, fail 0  >=568            ✓
C local integration            23 passed, skip 0, fail 0  >=23             ✓
D golden overlay               51 passed, skip 0, fail 0  >=51             ✓
E Stage 2-A 원장               146 moves / 6,921 files     146 / 6,921      ✓
                              failures 0                  0                ✓
                              원장 sha256 fe1adc26…        불변             ✓
F Stage 2-B B1 manifest        4 moves / 3,220 files       hash all         ✓
                              sha256 checked 3,220, license 2, failures 0  ✓
F Stage 2-B B2 manifest        3 moves / 68 files          hash all         ✓
                              sha256 checked 68, license 4, failures 0     ✓
G 5k dry-run (FrameSpec)      accepted 4,313 / rejected 687                ✓
                              distractors 209                              ✓
                              FrameSpec sha256 938f387d…                   ✓
G 5k dry-run (proposals)      accepted 4,439, 12/12 checks PASS,
                              NaN/inf 0, digest 3cd365ee…                  ✓
```

### ★ G 항목 — 지시서 기대값과 도구가 어긋났던 건 [확인]

지시서는 `accepted=4,313 / rejected=687 / FrameSpec checksum 938f387d` 를 기대했다.
그런데 Stage 2-B `final_report.md` 가 "5k dry-run" 이라 부른 하네스는 **두 개**였고,
둘의 수치가 다르다. 처음 `dryrun_v2_proposals.py` 를 돌렸을 때 `accepted=4,439` /
`digest=3cd365ee…` 가 나와 기대값과 불일치했다. 그대로 "불일치"로 넘기지 않고 추적했다.

```
하네스                                              accepted  digest        의미
────────────────────────────────────────────────────────────────────────────────────────
v2_pipeline.py --n 5000 --seed 7000 --dump <p>       4,313    938f387d…   SAMPLE-ONLY 경로.
   (generate_specs: 매 sample 마다 quota 확정                              5,000 FrameSpec 을
    -> solve_specs 로 5,000건 전수 solve)                                  JSONL 덤프한 파일의
   rejected 687, 4,313+687 = 5,000                                        SHA256 = 지시서 값
dryrun_v2_proposals.py --proposals 5000 --seed 7000  4,439    3cd365ee…   ACCEPT-TIME quota
   (run_v2_scene_logic.iter_proposals = production                        (production 스트림).
    스트림, accept 시에만 quota 전진)                                       12/12 checks PASS
```

두 값 모두 이번 실행에서 **재현**했다.

- `938f387dd65258e0ee869d58b0f4f69046bddc5e8f56921fbb666ecf13d82a39` — 지시서 기대값과 일치
- `3cd365eec96d1009428879f6a2636569c8d5bdb5e8d6e1488a1cda76c5bd30cd` — 저장소에 이미 커밋돼
  있는 `reports/v2_revision/dryrun_5k_checks.json` 의 값과 **바이트 단위로 동일**
  (즉 이 하네스의 4,439 는 지금 깨진 게 아니라 원래부터 그 값이었다)

따라서 **기준선 불일치 없음**. 이후 §14 회귀 검증은 두 지표를 모두 대조한다.

> 이 dry-run 은 bpy 를 전혀 쓰지 않는다 — `.blend` 를 읽지도 않는다. 따라서 이 지표는
> "portable blend 작업이 sampling/geometry 층을 건드리지 않았다" 는 **불변식 확인**이지,
> 이미지 품질·수율에 대한 진술이 아니다.

## 재현 명령

```bash
python scripts/data_prep/blender/pallet_data_paths.py --audit
python -m pytest scripts/data_prep/blender/tests/ -q
PALLET_DATA_INTEGRATION=1 python -m pytest \
    scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py -q
python -m pytest scripts/data_prep/blender/tests/test_overlay_archive_trunc_style.py -q
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2a/move_transaction.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b1_reference_materials.jsonl
python scripts/data_prep/manage_pallet_data_layout.py --verify \
    --manifest reports/data_pallet_cleanup/stage2b/transactions/b2_lighting_models.jsonl
python scripts/data_prep/blender/v2_pipeline.py --n 5000 --seed 7000 \
    --dump reports/data_pallet_cleanup/stage2c1/dryrun/_raw_framespec_5k_baseline.jsonl
python scripts/data_prep/blender/dryrun_v2_proposals.py --proposals 5000 --seed 7000 --tag 5k \
    --out reports/data_pallet_cleanup/stage2c1/dryrun
```

`--out` 을 stage2c1 하위로 돌린 이유: 기본 출력 경로가
`reports/v2_revision/dryrun_5k_*` 라 **이미 커밋된 산출물을 덮어쓴다**. 기준선 측정이
tracked 파일을 건드리면 안 되므로 별도 디렉토리로 뺐다.

기계 판독용 사본: `baseline_checksums.json`
