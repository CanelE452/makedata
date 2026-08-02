# Phase G1–G3 — 수정 전 기준선

`HEAD 0ebb41cb26feed567558ad9e94e06016c5d17430` (`origin/main` 과 일치) · branch `main`

> 지시서가 적은 base commit `7540428a` 는 Stage 2-D2 시점이다. 그 뒤 pilot 작업이
> `3599114` · `0ebb41c` 로 이미 commit·push 돼 있어 실제 HEAD 는 `0ebb41c` 다.
> 기존 작업을 지우지 않고 그 위에서 진행한다.

## 1. dirty worktree 분류

```
파일                                    분류               조치
──────────────────────────────────────────────────────────────────────────
_docs/history/.last-compact-resume.md   허용된 dirty       건드리지 않음
_docs/history/2026-08-01.md             EXPECTED (hook)    compact hook 이 append 한
                                                            마커. 이번 작업 history 와
                                                            같은 파일이라 유지
```

UNRELATED 변경 **0건** → 중단 사유 없음.

## 2. 기준선 (전부 실제 실행)

```
항목                       기대치                      실측                        판정
─────────────────────────────────────────────────────────────────────────────────────
A registry                ok=28 missing=0             ok=28 missing=0             PASS
B unit                    skip 0 fail 0               802 passed skip 0 fail 0  PASS
C local integration       skip 0 fail 0               31 passed skip 0        PASS
D golden overlay          skip 0 fail 0               51 passed skip 0       PASS
E1 5k FrameSpec           4,313/687 · 938f387d        4,313/687 · 938f387d     PASS
E2 5k proposal            4,439 · 3cd365ee · 12/12    4,439 · 3cd365ee · 12/12    PASS
F active scene no-render  abs 0 · missing 0 ·         abs 0 · missing [] ·   PASS
                          Dist_ 209                   Dist_ None
```

unit 은 preflight 당시 778 이었고 지금 802 이다 — pilot 세션에서 추가한
`test_v2_pilot_resume_reproducibility.py` 24개가 늘어난 것이다(회귀 아님).

active scene SHA256 `8cb4109a…` · 358,898,838 bytes — 이 값이 작업 내내 불변이어야 한다.

## 3. 읽기 전용으로 잠근 baseline pilot

```
root      data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_public
usable    1,449      rgb 1,449  labels 1,449  amodal 1,449  visible 1,449
records.jsonl sha256      d04283b279dca43d068451b6c9294210aacd8a510a6c737a1d3b361bc588a992
```

`preflight/baseline_pilot_lock.json` 에 records/rejected/manifest/progress SHA256 과
audit 산출물 13개 SHA256 을 고정했다. 이후 이 값이 바뀌면 즉시 중단한다.

## 4. process

```
blender.exe                       0개
FoundationPose 렌더 python        0개
python.exe 24916                  blender_mcp.server (MCP 서버) — 렌더 아님, 유지
```
