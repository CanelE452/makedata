# Stage 2-D0 기준선 (비파괴 감사 · active 영역 보호)

일시: 2026-07-30 / branch `chore/data-pallet-stage2d0-archive-audit` (75a3f71 = main = origin/main 에서 분기)

## PRE-FLIGHT [확인, 실행함]

```
repo root              E:/CODING/GitHub/FoundationPose
branch (작업 전)         main
HEAD / origin/main     75a3f71c22a7eee4b689cb4ef59c38d1c3420e5d  (동일)
git status             clean
작업 branch             chore/data-pallet-stage2d0-archive-audit  (신규, 기존 동명 branch 없음)
디스크 E:               free 1,258.1 GB
data/pallet            2,560 dirs / 363,090 files / 192,468,045,942 bytes (179.25 GB)
실행 중 blender.exe     0개
```

### 실행 중 python process — 임의 종료하지 않음 [확인]

```
PID     명령                                              판정
────────────────────────────────────────────────────────────────────────────────────────
24916   python -m blender_mcp.server                      Blender MCP 브리지. 렌더 아님
29972   scripts\collector_watchdog.py --root E:\CODING\proj\Algorithmic-Trading   다른 프로젝트
580     Trading32\python.exe realtime.py --demo --collect  다른 프로젝트
27596   koapy.cli serve                                   다른 프로젝트
11112   koapy ... KiwoomOpenApiPlusServerApplication       다른 프로젝트
```

FoundationPose 학습·렌더 process 는 **0개**. 위 5개는 data/pallet 를 건드리지 않으므로
그대로 두었다(종료 금지 규칙 준수).

## 기준 측정값 [확인, 실행함]

```
항목                          값                          기대치        일치
──────────────────────────────────────────────────────────────────────────────
A registry audit              ok=24 missing=0 absent=0    missing=0     ✓
B default unit                646 passed, skip 0, fail 0  >=646         ✓
C local integration            31 passed, skip 0, fail 0  >=31          ✓
D golden overlay               51 passed, skip 0, fail 0  >=51          ✓
E Stage 2-A 원장               146 / 6,921 / failures 0    동일          ✓
  Stage 2-B B1/B2              4/3,220 · 3/68 / failures 0 동일          ✓
  Stage 2-C2 C2A/C2B           3/3 · 1/74 / failures 0     동일          ✓
  Stage 2-C2 C2C               2/1,336 / failures 3        failures 0    ✗ -> 아래
F active scene no-render       absolute 0 · missing 0 ·
                              textures 158 · distractor 356 · HDRI 1 ·
                              Dist_ 209 · HDRI 30/30 ·
                              floor 42/42 · wood 27/27 · node 누락 0     ✓
active scene sha256           8cb4109adc6d3213…                          ✓
```

5k dry-run 은 §1 지시대로 **수행하지 않았다** — active 코드·config 를 수정하지 않기 때문이다.
(`manage_pallet_data_layout.py` 의 verify 옵션 1개는 추가했으나 sampling/geometry 층과 무관하다.)

## ★ C2C verify failures 3 — 원인과 정정 [확인]

```
   S2C2002  RELPATH_SET extra=['synth_data_scene_portable_stage2c2.blend',
                               'synth_data_scene_portable_stage2c2_candidate.blend1']
   S2C2002  FILE_COUNT 175 != 173
   S2C2002  TOTAL_BYTES 4554353915 != 3836556170
```

- `missing=[]` — **없어진 파일 0**
- `sha256 checked 1334`, **SHA256 mismatch 0** — 옮긴 파일 전부 바이트 그대로
- extra 2개는 Stage 2-C2 에서 정상적으로 만든 파일(승격된 active scene + Blender 자동 백업)

**데이터 손상이 아니다.** 그러나 Stage 2-C2 최종 보고서에 적은 "C2C failures 0" 은
candidate 생성 **전** 측정값이었고, 승격 후에는 strict verify 가 필연적으로 실패한다.
그 보고는 부정확했다 — 여기서 정정한다.

### 조치: verify 의미를 명시적으로 분리

`--verify` 의 기본 동작(엄격 비교)은 **그대로 두고**, 새 플래그로만 완화한다.

```
python scripts/data_prep/manage_pallet_data_layout.py --verify --manifest <c2c>
  -> failures 3 (전부 destination 추가분). 기존 계약 불변.

python ... --verify --allow-destination-additions --manifest <c2c>
  -> dest additions : 1 move(s) — 이동 후 정상적으로 추가된 파일 (없어진 것 0)
       S2C2002  +2  ['...stage2c2.blend', '...stage2c2_candidate.blend1']
     failures       : 0
```

원장이 지켜야 하는 불변식은 **"옮긴 파일이 하나도 없어지지 않고 바이트가 그대로다"** 이지
"목적지 폴더가 얼어 있다" 가 아니다. 나머지 5개 원장은 strict 로도 여전히 failures 0 이고,
트랜잭션 unit 69개(39 + 30) 전부 통과했다.

## 감사 범위 [판정]

```
내용 재감사 제외 (Stage 2-C2 까지 정리 완료)  assets/ · reference/ · runs/ · release/
                                            (단 참조 그래프·registry 보호 검사에는 포함)
집중 감사                                    archive/ 166 entries · 최상위 잔여 85 entries ·
                                            production scene 폴더 blend 17개 ·
                                            isaac_assets · NoAI quarantine ·
                                            저장소 전체 weight 29개
감사 대상 bytes                              170.34 GB (data/pallet 179.25 GB 중)
```

기계 판독용 사본: `baseline_checksums.json`
