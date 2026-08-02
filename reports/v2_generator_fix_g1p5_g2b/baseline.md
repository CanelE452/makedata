# Phase G1.5 / G2b — 수정 전 기준선

`HEAD 0ebb41c` (`origin/main` 과 일치) · branch `main`

## 1. dirty worktree 분류

```
분류                    항목
──────────────────────────────────────────────────────────────────────────
허용된 dirty            _docs/history/.last-compact-resume.md
EXPECTED (직전 단계)     _docs/history/{2026-08-01.md, changelog.md}
                        scripts/data_prep/blender/{run_v2_scene_logic,
                          scene_placement_v2, v2_pipeline, v2_realize}.py
                        scripts/data_prep/blender/tests/{3개}
                        신규 도구 5 · 신규 테스트 2 + fixture · reports/…g1_g3/
UNRELATED               0건
```

Phase G1–G3 작업물이 그대로 있는 상태에서 이어서 진행한다 (commit 0 · push 0).

## 2. 기준선 (전부 실제 실행)

```
항목                       기대치                      실측                        판정
─────────────────────────────────────────────────────────────────────────────────────
A registry                ok=28 missing=0             ok=28 missing=0             PASS
B unit                    skip 0 fail 0               865 passed skip 0 fail 0  PASS
C local integration       skip 0 fail 0               31 passed skip 0        PASS
D golden overlay          skip 0 fail 0               51 passed skip 0        PASS
E1 5k FrameSpec           4,313/687 · 938f387d        4,313/687 · 938f387d        PASS
E2 5k proposal            4,439 · 3cd365ee · 12/12    4,439 · 3cd365ee · 12/12  PASS
F active scene no-render  abs 0 · missing 0           abs 0 · missing [] ·   PASS
                                                      Dist_ None
```

active scene SHA256 `8cb4109a…` · 358,898,838 bytes.

## 3. 읽기 전용으로 잠근 두 baseline

```
pilot 1,449장   rgb 1,449 · labels 1,449 · amodal 1,449 · visible 1,449
                records.jsonl d04283b279dca43d…
smoke100        rgb 100 · labels 100 · amodal 100 · visible 100
                dataset 안 overlay 0 (없음) · report 쪽 overlay 100
                records.jsonl 269a48a9f3f00c8d…
                g2/final_report.md cbf30b4a8fc489b3…
```

두 데이터셋 모두 이번 작업에서 **읽기 전용**이다. 새 출력은
`v2_mode_semantics_smoke100b_seed7000_public` 로 따로 만든다.

## 4. ★ 지시서 §8/§13 의 전제 정정 — overlay 해상도

지시서는 overlay 를 "640x480 원본 크기"로 적었지만, 이 generator 는 **프레임마다
해상도가 다르다** (aspect 랜덤화).

```
smoke100 RGB 해상도 분포   640x480 48 · 720x480 18 · 960x540 26 · 560x560 8
직전 단계 overlay 분포      동일 (이미 native 해상도로 생성돼 있다)
```

640x480 으로 고정하면 52장이 **리사이즈**되어 같은 문장의 "원본 크기"와 모순된다.
따라서 overlay 는 **각 프레임의 native 해상도**로 만들고, 감사 항목도
"overlay 크기 == 해당 RGB 크기"로 검사한다.

## 5. process

```
blender.exe                       0개
FoundationPose 렌더 python        0개
python.exe 24916                  blender_mcp.server (MCP 서버) — 렌더 아님
```
