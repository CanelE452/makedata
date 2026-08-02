# Phase G1 — generator mode semantics + controlled 배치 효율 수정

렌더는 하지 않았다. 이 단계는 코드 수정과 bpy-free 검증까지다.

## 1. 무엇이 틀렸었나 (baseline 실측)

```
mode                 결함                                              규모
──────────────────────────────────────────────────────────────────────────────
cargo-only           cargo 가 하나도 안 놓였는데 usable 통과           51 / 400
                     cargo 자체의 화면 가시성은 아예 측정하지 않음      400 / 400
context-rich         context 배치를 시도조차 안 함 (attempts=0)         39 / 600
controlled           f_target=0 plan 을 fallback 으로 렌더 가능         경로 존재
controlled           비싼 실패가 늦게 발견됨 (수율 17.6%)              94건 4,936초
```

### ★ 이전 보고 정정

"realize_occluder 는 렌더를 마친 뒤 판정한다"는 **틀렸다**. 비싼 reject 94건은
`rendered=False` 로, RGB 를 한 장도 렌더하지 않았다. 비용은 Blender 안의 저해상도
탐색(explicit 3,118초)과 그 앞에서 이미 끝난 context 배치(1,424초)에 있다.

## 2. 고친 것

### §3 usable mode 10장 주기 interleave

`usable_diagnostic_modes(n)` 이 네 블록 대신 10장 주기(2 clean / 2 cargo /
3 context / 3 controlled)로 배치한다. 총량은 기존 largest-remainder 그대로다.

```
n=10    2/2/3/3            n=100   20/20/30/30        n=2000  400/400/600/600
첫 10장 안에 네 mode 전부 · 10의 배수면 매 10장 2/2/3/3 · n=1..250 전수 count 일치
records mode(20/500) 배치는 무변경
```

이제 어디서 멈춰도 delivered set 이 대표성을 갖는다 — 1,449장에서 멈췄을 때
controlled 가 49장뿐이던 일이 구조적으로 사라진다.

### §4 cargo 자체 가시성 측정

`front/left/right_visibility_after_cargo` 는 "팔레트가 가려졌는가"이지 "cargo 가
보이는가"가 아니다. public mask 는 팔레트 전용이라 그것으로도 추론할 수 없다.
그래서 context 와 **같은 방식**의 저해상도 holdout 을 cargo 에도 적용했다.

```
n_cargo_visible            8px 이상 보이는 cargo 개수
cargo_visible_pixels       cargo union 의 저해상도 화면 픽셀 수   ← hard gate 는 >0
cargo_visible_pixel_ratio  화면 대비 비율
cargo_visibility_measured  True
```

임시 마스크는 `_lowres_holdout` 이 finally 에서 지운다 — **public output 에는
`mask_amodal` / `mask_visible` 두 장뿐이고 스키마는 그대로다.**

강제하지 않은 것: cargo 가 팔레트를 가려야 한다 / f_cargo 하한 / opening
visibility 감소. 1픽셀이 최종 기준이라는 뜻은 아니며, G2 100장의 분포를 보고
최소 임계 후보를 보고한다(이번 단계에서 확정하지 않는다).

### §5 context attempts=0 의 원인과 수정

`image_space_context_poses` 는 **이미지 좌우 띠의 픽셀 -> 지면 교점** 방향으로 푼다.
카메라가 지면에 가까우면(저앙각) 그 광선이 지평선 위로 가거나 교점이
`max_camera_distance=8m` 를 넘어 후보가 전멸한다.

```
absent 39프레임 · 후보 22,464개 기각 사유          비율
─────────────────────────────────────────────────────────
camera_distance_out_of_band              14,421   64.2%
ray_up (above horizon)                    5,049   22.5%
too_close_to_pallet                       2,992   13.3%
ok                                            2    0.0%
```

같은 물리 제약(카메라 거리 밴드 · 팔레트 최소 이격 · 화면 안)을 유지한 채 **순서만
뒤집은** ground-ring fallback 을 넣었다: 지면 위 점을 먼저 고르고 화면 좌우 띠에
맺히는지 확인한다. 1차 sampler 가 하나라도 성공하면 fallback 은 돌지 않으므로
기존 561장의 배치는 변하지 않는다.

```
              수정 전                수정 후
absent 39     poses 0: 38건          poses 18: 38건 · 1: 1건
present 561   poses>0: 559 / 0: 2    poses>0: 561
```

### §6 controlled invalid fallback 제거

`CONTROLLED_MODE_MAX_SKIPS(50)` 을 넘기면 `f_target=0` plan 을 그대로 렌더해
controlled 슬롯을 채우던 경로를 없앴다. 후보가 계속 없으면 슬롯을 잘못 채우는
대신 명시적 `stop_reason` 으로 멈춘다. (skip 확률 0.35 기준 50연속은 사실상 0.)

### §7 controlled feasibility prefilter (bpy-free)

`prepare_diagnostic_explicit_occluders` 가 nonce 0..640 으로 후보를 모은 **뒤,
6개를 고르기 전에** 걸러낸다. Blender 는 아예 열리지 않으므로 배제 비용이 0초다.

```
규칙                                    임계        물리적 근거
──────────────────────────────────────────────────────────────────────────────
prefilter_side_geometry_infeasible      side=center 실루엣 전체가 팔레트 안에 들어가야
                                                    해 접지 occluder 로는 깊이 여유가
                                                    없다 (baseline 30회 시도 0회 성공)
prefilter_floor_support_infeasible      bottom/높이 접지 스냅 변위가 bounded search 의
                                        ∉[-0.60,   u/v/depth 범위를 넘는다
                                          1.90]     (winner 범위 -0.535 ~ 1.751)
prefilter_fill_ratio_too_low            <0.45      성긴 실루엣은 조밀한 겹침을 못 만든다
                                                    (winner 최소 0.480)
prefilter_insufficient_projected_area   실루엣/     여유가 없으면 어떤 섭동도 목표를
                                        A_target    놓친다 (winner 최소 1.192)
                                        <1.15
                                        실루엣/     팔레트를 통째로 덮으면 부분 가림
                                        A_pallet    목표를 맞출 수 없다 (winner 최대 19.92)
                                        >22.0
prefilter_position_band_infeasible      band 밖     기존 solver 제약의 명시적 재확인
```

**분포는 건드리지 않았다** — FrameSpec · f_target · side · elevation · projected
size 모두 그대로다. 걸러지는 것은 "이 프레임에 쓸 occluder 후보"뿐이고, 후보가
전멸한 프레임은 baseline 에서도 어차피 실패하던 프레임이다(비용만 앞당겼다).

실측 recall:

```
accepted 49건의 승리 후보 보존   49 / 49       ← 하나도 버리지 않았다
accepted 프레임 탈락             0
비싼 실패 프레임 조기 탈락       12 / 94  (12.8%, 0초)
후보 pool                        29,725 -> 20,013  (32.7% 제거)
```

후보 pool 이 32.7% 줄었다는 것은, 남은 6개 proposal 이 **전부 접지 가능한 후보**로
채워진다는 뜻이다. 실제 수율 개선은 G2 100장에서 측정한다(여기서 추정하지 않는다).

### §8 runtime·count 계측

기존 `stage_runtime_s` 를 재사용하고 중복 필드를 만들지 않았다. 새로 남기는 값:

```
proposal_prepare_s              bpy-free 후보 준비(prefilter 포함) 시간
candidates_before_prefilter     / candidates_after_prefilter / prefilter_reject_count
prefilter_reject_counts_by_reason
realization_attempt_count       Blender 안에서 실제로 돈 explicit 탐색 횟수
lowres_render_count             프레임당 저해상도 holdout 렌더 횟수
```

### §9 mode-specific usable gate

`scene_placement_v2.mode_semantics_verdict()` (bpy-free) 가 mode 별 조건을 tri-state
로 평가하고, **두 곳에서** 강제한다.

```
1) realize 안 — 최종 RGB 를 렌더하기 전에 realize_ok=False 로 되돌린다 (비용 절감)
2) usable_conditions — 최종 record 로 독립 재판정 (fail-closed)
```

```
mode                  조건
──────────────────────────────────────────────────────────────────────────────
clean-static          explicit 없음 · 보이는 cargo 없음 · 보이는 context 없음
cargo-only            n_cargo_placed>=1 · cargo_visible_pixels>0
context-rich          requested>=1 · placed>=1 · visible>=1 & ratio>0
controlled-occlusion  f_target>0 · occluder placed · visible px>0 · side match
```

None 은 통과가 아니다 / 0 은 실제 0 / False 는 실제 실패. short-circuit 없이 전부
평가하므로 실패 사유가 모두 남는다.

### §10 record · manifest

records / records_rejected / manifest 에 다음이 추가됐다(없으면 null, 0 과 구분).

```
mode_semantics_pass · mode_semantics_conditions · _failed_conditions ·
_unknown_conditions · mode_semantics_reason
n_cargo_visible · cargo_visible_pixels · cargo_visible_pixel_ratio ·
cargo_visibility_measured
proposal_prepare_s · candidates_before/after_prefilter · prefilter_reject_count ·
prefilter_reject_counts_by_reason · realization_attempt_count · lowres_render_count
```

public mask 스키마는 무변경.

## 3. 회귀

```
registry ok=28 missing=0 · unit 865 passed(skip 0 fail 0) · integration 31 ·
golden 51 · 5k FrameSpec 938f387d(불변) · 5k proposal 3cd365ee 4,439 12/12(불변)
```

상세는 `test_results.md`.

## 4. 변경 파일

```
scripts/data_prep/blender/run_v2_scene_logic.py     +145 -13
scripts/data_prep/blender/scene_placement_v2.py     +241
scripts/data_prep/blender/v2_pipeline.py             +50
scripts/data_prep/blender/v2_realize.py              +62
scripts/data_prep/blender/audit_v2_controlled_prefilter.py   (신규)
scripts/data_prep/blender/tests/test_mode_semantics.py       (신규 33)
scripts/data_prep/blender/tests/test_controlled_prefilter.py (신규 21)
scripts/data_prep/blender/tests/fixtures/controlled_prefilter_winners.json (신규)
scripts/data_prep/blender/tests/test_scene_placement_v2.py           +56
scripts/data_prep/blender/tests/test_usable_completion_mode.py       +44 -0
scripts/data_prep/blender/tests/test_v2_pilot_resume_reproducibility.py +20
```

commit / push 없음. baseline pilot 1,449장 무변경.

## 5. 하지 않은 것

sampler 분포 · ELEV_BIN_FRAC · V_FRAC · PROJ_SIZE_FRAC · F_TARGET_FRAC ·
MAX_CAMERA_DISTANCE_M · scene preset 분포 · noise tier 분포 · gate 완화 ·
cargo 가 팔레트를 가리도록 강제 · accepted controlled 의 f_target 허용 범위 완화
— **전부 무변경**.
