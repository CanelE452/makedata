# Stage 2-D2 preflight

base commit `d5e1ba181345fc7d84480606b26ba732ec3324e8` (Stage 2-D1.2 종료)
branch `chore/data-pallet-stage2d2-layout-completion` (신규 생성, 기존 동명 branch 없음)

## 1. 환경

```
repo root      E:/CODING/GitHub/FoundationPose
HEAD           d5e1ba181345fc7d84480606b26ba732ec3324e8
origin/main    d5e1ba181345fc7d84480606b26ba732ec3324e8   (일치)
data/pallet    E:\CODING\GitHub\FoundationPose\data\pallet
볼륨           source·destination 모두 E: (same-volume rename 가능)
디스크 여유     1.3T / 1.9T (33% 사용)
blender.exe    C:\Program Files\Blender Foundation\Blender 5.1\blender.exe (5.1.1)
```

## 2. working tree

허용된 dirty 는 `_docs/history/.last-compact-resume.md` 하나뿐이었고 실제로도 그것뿐이었다.
이 파일은 **수정하지 않음 / 복구하지 않음 / stage 하지 않음 / commit 대상에 넣지 않음**.

## 3. process 점검

```
blender.exe                      0개
python (FoundationPose 관련)      0개
python (다른 프로젝트)            4개 — Algorithmic-Trading (collector_watchdog · realtime ·
                                       koapy). 종료하지 않았다.
python -m blender_mcp.server     1개 (PID 24916, 2026-07-28 시작) — Blender 미실행이라
                                       중계 대상이 없다
```

배타 열기 probe (읽기전용·비파괴)로 잠금 0 확인:

```
FREE  synth_data_scene_portable_stage2c2.blend
FREE  data/pallet/manifests/archive.csv
FREE  data/pallet/_DISTRIBUTION_EXCLUDE.txt
```

## 4. 기준선

```
A registry      ok=28 missing=0 absent_optional=0
B unit          745 passed, skip 0, fail 0
C integration   31 passed, skip 0
D golden        51 passed, skip 0
E exclusion     entries 16 / problems 0 / leaks 0
F 기존 원장 12종  failures 0 전부
  C2C (exact additions + D11A chain + D12 chain)  failures 0 / 인정된 이관 11
G active scene  SHA256 8cb4109… / absolute 0 / missing 0 / Dist_ 209
H 5k FrameSpec  accepted 4,313 / rejected 687 / digest 938f387d
I 5k proposal   accepted 4,439 / digest 3cd365ee / 12-12 PASS
```

## 5. 먼저 읽은 것

stage2d12 산출물 일체(final_report · final_tree · filesystem_* · regression_results ·
rollback_plan · 원장 2종 · chain), stage2d11 chain, stage2d1/stage2c2 원장,
`data/pallet/manifests/{archive,path_map,assets}.csv`, `grouped_inventory.csv`,
registry(yaml + resolver), 이동 도구 3종, `_DISTRIBUTION_EXCLUDE.txt`,
`_docs/{data_pallet_layout,dataset_license_ledger}.md`, history, CLAUDE.md/AGENTS.md,
각 README, project-local memory.
