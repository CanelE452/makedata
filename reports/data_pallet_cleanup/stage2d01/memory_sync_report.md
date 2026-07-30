# Stage 2-D0.1 §8 — current 문서 · project-local memory 동기화

## project-local memory 위치 [확인]

```
C:\Users\User\.claude\projects\E--CODING-GitHub-FoundationPose\memory\
```

Claude Code 의 프로젝트별 memory 디렉토리다. `MEMORY.md`(인덱스) + 파일당 사실 1개.
저장소 안에도 `.claude/agents/` 가 있지만 그것은 agent 정의·agent 경험 로그이고
프로젝트 상태 memory 가 아니다 — 이번에 건드리지 않았다.

**전역 사용자 memory(`~/.claude/CLAUDE.md` 등)와 다른 프로젝트 memory 는 수정하지 않았다.**

## 갱신한 memory 파일 2개

### `stage2c1-portable-blend.md`

```
갱신 전                                     갱신 후
────────────────────────────────────────────────────────────────────────────
"Stage 2-D1(48건 163GB) 미실행"             "READY 40건 132.37 GiB" + 정본 출처 링크
```

이 파일은 이미 이전 세션에서 Stage 2-C2 완료 상태로 고쳐져 있었다 (active =
stage2c2 scene, background/distractors/blender_scene 이동 완료, semantic 하위폴더
비어 있음, dataset 은 archive depth-1 평면 배치). 지시문이 지적한 outdated 문장
(`Stage 2-C2 에서 rebase 필요` · `distractors/blender_scene/background 이동 미완료` ·
`Stage 2-C1 portable 이 active` · `Stage 2-D0 미실행`)은 **이번 감사 시점에 이미
남아 있지 않았다** — 잔존 항목은 D1 규모 숫자 하나였다.

### `stage2d01-stabilization.md`

```
갱신 전                                     갱신 후
────────────────────────────────────────────────────────────────────────────
canonical = 19건(12파일)                    canonical = 44행(unique 39 · 파일 23) -> 0
(패턴 버그로 과소계상)                       + 왜 틀렸는지(따옴표 요구 · 덤프 패턴 누락)
고친 것 12파일                               고친 것 25파일 / 경로 변경 줄 67
(D1 규모 없음)                              READY 40 / 132.37 GiB / BLOCKED 8 / KEEP 12
                                            + D1 선행조건(registry 키 등록 후 이동)
```

`MEMORY.md` 인덱스의 두 줄도 새 요약으로 맞췄다.

## 갱신한 current 문서

```
_docs/data_pallet_layout.md          §6 "다음 단계(Stage 2-B 후보)" 6항목 처리상태 표기
                                     §7 신규 — archive 내부 정리 상태(D0/D0.1) + D1 계획 표
reports/data_pallet_cleanup/README.md  grouped_inventory.csv 이름 반영 (2곳)
reports/data_pallet_cleanup/rollback_plan.md  같은 이름 반영 (5곳)
_docs/dataset_license_ledger.md      저장경로 열 갱신 + B7(해소) · B8(신규 MEDIUM)
_docs/attribution_cc-by_appendix.md  distractor·background 자산 위치
_docs/method/step1_synthetic_data.md USD 모델 경로
_docs/preprocessing/data_pipeline.md 배경 자산·학습 데이터 경로
_docs/history/2026-07-30.md          **새 Section 추가만** (과거 Section 무수정)
_docs/history/changelog.md           한 줄 요약 추가
```

`AGENTS.md` 는 이 저장소에 없다. `CLAUDE.md` 의 current path 설명은 이미
`data/pallet/assets/pallets/models/models_usd/` · `archive/_noai_quarantine_usd/` ·
registry 안내로 맞춰져 있어 수정할 것이 없었다 [확인].

## 반영한 현재 사실

```
사실                                              반영 위치
────────────────────────────────────────────────────────────────────────
active scene = Stage 2-C2 scene (8cb4109a)         layout §2 · memory
background/distractors/blender_scene 이동 완료      layout §2·§3 · memory
Stage 2-C2 rebase 완료                             layout §3 · memory
Stage 2-D0 감사 완료 / Stage 2-D1 미실행            layout §6·§7 · memory
semantic archive 하위폴더 7개는 현재 비어 있음      layout §7 · memory
dataset 은 archive depth-1 에 평평하게 존재         layout §7 · memory
D1 계획 = READY 40 / 132.37 GiB (D0 의 48/163 아님) layout §7 · memory
package structural match ≠ exact duplicate         layout §7
isaac_assets · NoAI quarantine 이동 금지            layout §7 · exclude 파일
weights exact duplicate 0                          layout §7
```

## 수정하지 않은 것

- 과거 history Section 의 당시 표현 (2026-07-24/26/28/29 및 30일 이전 Section)
- report snapshot (`stage2a/` · `stage2b/` · `stage2c1/` · `stage2c2/` · `stage2d0/`)
- transaction manifest (`*.jsonl`)
- `data/pallet/manifests/*.csv` — **current metadata 동기화가 실제로 필요하지 않았다.**
  이번 단계는 자산을 옮기지 않았으므로 assets/runs/path_map/archive 스냅샷의 내용이
  달라질 이유가 없다. 지시문의 "필요할 때만 수정한다"에 따라 손대지 않았다.
