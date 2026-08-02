# Phase G3 — 실행하지 않음

`G2_MIXED100_PASS = false` 이므로 §18("하나라도 실패하면 Phase G3 를 실행하지 않고
원인을 보고한다")에 따라 재현성 재검증을 시작하지 않았다.

미실행 항목: §19 post-fix reproducibility lock · §20 bpy-free 결정성 ·
§21~22 public exact20 A/B · §23 dataset-quality same-machine probe.

## 준비돼 있는 도구 (G2 통과 후 바로 실행 가능)

```
scripts/data_prep/blender/build_v2_repro_lock.py
    --out reports/v2_generator_fix_g1_g3/g3/reproducibility
        environment / code(SHA + diff) / scene / asset / command lock

scripts/data_prep/blender/audit_v2_bpyfree_determinism.py
    --seed 7000 --n 100 --proposals 400 --out <g3/reproducibility>
        mode schedule · proposal index · FrameSpec/Plan canonical SHA ·
        prefilter 결과와 사유 · frame seed · chunked resume == uninterrupted

scripts/data_prep/blender/audit_v2_exact_repro.py --a <run_a> --b <run_b> --out <g3>
        normalized record/label · decoded RGB/mask pixel 비교
        (file-byte 불일치는 참고값으로 따로 기록)

scripts/data_prep/blender/audit_v2_dataset_quality_probe.py --a <run> --b <probe> --out <g3>
        PLAN / LABEL / PUBLIC_MASK / DATASET_QUALITY_RGB 판정 분리
```

## §23 선택 규칙에 대한 사전 메모

usable slot 은 accept 시점에만 전진하므로 usable_id 42 를 재현하려면 0..41 을 먼저
렌더해야 한다. 즉 **임의 부분집합의 재현 비용 = 그 앞 전체의 재현 비용**이다.
interleave 이후 usable_id 0..9 는 정확히 clean 2 / cargo 2 / context 3 / controlled 3
이므로, "첫 완결 cycle"이 §23 이 요구한 구성(2/2/3/3)을 만족하는 유일하게 경제적인
결정적 선택이다. 실행할 때 이 근거를 보고서에 명시한다.
