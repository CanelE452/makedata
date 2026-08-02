# Phase G1.6 / G2c / G3 — 수정 전 기준선

`HEAD 0ebb41c` (= `origin/main`) · branch `main`

## 1. dirty worktree 분류

```
분류        항목
──────────────────────────────────────────────────────────────────────────
허용        _docs/history/.last-compact-resume.md
EXPECTED    _docs/history/{2026-08-01.md, changelog.md}
            scripts/data_prep/blender/{run_v2_scene_logic, scene_placement_v2,
              v2_pipeline, v2_realize}.py  (G1~G2b generator 변경)
            tests 3개 · 신규 도구 8 · 신규 테스트 3 + fixture
            reports/{v2_generator_fix_g1_g3, v2_generator_fix_g1p5_g2b}/
UNRELATED   0건
```

## 2. 기준선 (전부 실제 실행)

```
항목                    기대                     실측                     판정
──────────────────────────────────────────────────────────────────────────────
A registry             missing=0                ok=28 missing=0          PASS
B unit                 현재 이상 · skip 0       888 passed skip 0 fail 0  PASS
C local integration    skip 0 fail 0            31 passed skip 0       PASS
D golden overlay       skip 0 fail 0            51 passed skip 0       PASS
E1 5k FrameSpec        4,313/687 · 938f387d     동일                     PASS
E2 5k proposal         4,439 · 3cd365ee · 12/12 동일                     PASS
F active scene         SHA 불변 · abs 0 · miss 0 8cb4109a… · abs 0 · miss []  PASS
```

## 3. 읽기 전용 lock

```
데이터셋       rgb    labels  amodal  visible  overlay  records.jsonl sha256
──────────────────────────────────────────────────────────────────────────────
pilot_1449     1449   1449    1449    1449     0        d04283b279dca43d…
smoke100       100    100     100     100      0        269a48a9f3f00c8d…
smoke100b      100    100     100     100      100      bf682c0aab51f96d…

locked cases   77건 (accepted 30 · expensive reject 47)
               sha256 35478cbee718d791…
active scene   8cb4109a… · 358,898,838 bytes
```

## 4. process

```
blender.exe                        0개
FoundationPose 렌더/replay python  0개
python.exe 24916                   blender_mcp.server (MCP 서버) — 렌더 아님
```
