# Phase G1.5 — controlled solver 개선

렌더는 locked benchmark(77건 replay)까지만. mixed100b 는 Phase G2b 에서 만든다.

## 1. 판정

```
accepted recall              30 / 30   PASS
explicit visible px > 0      31 / 31   PASS
side match                   31 / 31   PASS
explicit_metrics_available   31 / 31   PASS   ← §2 목표
실패 프레임 context 낭비      1,151 s -> 32 s  (-97%)   PASS   ← §3 목표
total Blender time           4,949 s -> 5,020 s  (+1.4%)   목표(-50%) 미달
```

`G1P5_ACCEPTED_RECALL_PASS = true` · `G1P5_QUALITY_PASS = true` ·
`G1P5_RUNTIME_TARGET = missed (-50% 목표에 미달, 실측 +1.4%)`

§5 가 "미달이어도 accepted recall 우선"이라고 못박았으므로 recall 30/30 구성을 택했다.
아래 §5 에 그 트레이드오프의 실측 근거를 남긴다.

## 2. §2 explicit 저해상도 품질 지표

public 프로필은 M1~M3 를 저장하지 않아 마스크 분해로 `f_explicit` 을 못 얻는다.
직전 단계에서 controlled 품질 게이트가 그래서 BLOCKED 였고, `f_total` 대체는 금지였다.

탐색이 **이미 찍는** holdout 두 장(`explicit_before_mask`, `final_mask`)의 차집합에서
숫자만 뽑아 해결했다. 새 마스크를 렌더하지도, 파일을 저장하지도 않는다.

```
explicit_metrics_available · explicit_target_pixels · explicit_actual_pixels_lowres
f_explicit_target · f_explicit_actual_lowres · explicit_abs_error_lowres
explicit_target_centroid_u/v · explicit_actual_centroid_u/v_lowres
explicit_target_bbox_u0v0u1v1 · explicit_actual_bbox_u0v0u1v1_lowres
```

실측 (replay accepted 31건):

```
explicit_metrics_available   31 / 31
explicit_abs_error_lowres    min 0.002 · median 0.037
                             · p95 0.114 · max 0.116
```

순수 함수 `scene_placement_v2.explicit_lowres_metrics()` 로 분리해 bpy 없이 테스트한다.
`f_total` 은 입력에도 출력에도 없다는 것을 테스트로 고정했다.

## 3. §3 controlled 단계 순서 변경

```
before   cargo -> context -> explicit 탐색      (실패 시 context 비용 전액 낭비)
after    cargo -> explicit_prep -> explicit 탐색 -> (성공 시) context
```

explicit 이 요구조건을 못 맞추면 `explicit_blocked` 로 context 를 **아예 시도하지 않는다**.

```
실패 프레임의 context 단계 합계   1,151 s  ->  32 s
```

부수 정합성:
- `explicit_baseline` 에서 context 제거 (아직 배치 전이므로 explicit 기여분만 고립)
- context 예산 측정 시 배치된 occluder 를 `extra_hide` 로 가림 (의도된 가림을 예산에 넣지 않음)
- 후보 전체의 swept 예약 대신 **실제 배치된 occluder** 를 static 으로 전달
- `stage_runtime_s` 에 `explicit_prep` 분리

### ★ 이 재배열이 만든 회귀 1건 — 잡아서 고쳤다

`explicit_corner_reserve_pass` 는 **occluder 를 놓기 전** 코너 여유를 남겨두는 계약이라
`ext_occ_corners <= 1` 을 요구한다. 배치를 앞으로 옮기자 **가리는 것이 본업인 occluder**
때문에 그 조건이 거의 항상 깨져 모든 context 후보가 탈락했다.

```
1차 replay(20건) accepted 경로   context median 14.0 s -> 224.9 s (16배)
                                 저해상도 렌더 median 52 -> 351
```

배치 **후**에 맞는 기준 `context_corner_no_regression(metrics, post_explicit)` 으로 교체했다
— explicit 만 있던 상태 대비 `V_inframe`·`V_vis` 감소 없음 + `ext_occ` 증가 없음.
게이트를 없앤 것이 아니라 의미를 맞춘 것이고, explicit 이 없는 mode 는 기존 계약 그대로다.

## 4. §4 target-mask-conditioned seed

목표 마스크 통계(centroid·bbox·area)에 맞추는 해석적 정렬을 `target-seed` 라는 이름으로
**preprobe 바로 다음**으로 올렸다. 예전에는 같은 offset 이 `prealign` 이라는 이름으로
gate-overlap / corner-contact **뒤**에 있었다 (중복이라 구 stage 는 제거).

승리 stage 분포 — 같은 77 프레임에서:

```
                        구 smoke100(30)   신 replay(31)
target-seed / prealign        16              21
gate-overlap-refine            7              3
corner-contact-refine          3              2
preprobe                       3              3
primary                        1              2
```

계측: `search_init_strategy` · `search_seed_count` · `coarse_eval_count` ·
`fine_eval_count` · `best_seed_score` · `final_seed_score` · `search_winning_stage`.

## 5. ★ recall 과 runtime 의 트레이드오프 (실측 3회)

```
구성                                    recall    total time   context 낭비
──────────────────────────────────────────────────────────────────────────────
(1) target-seed 추가, 구 prealign 유지    28/30     -23.3%       1,151 -> 31 s
(2) 구 prealign 제거 (중복)               28/30     -22.1%       1,151 -> 32 s
(3) target-seed 를 예산에서 제외 ★채택     30/30     +1.4%        1,151 -> 32 s
```

(1)·(2) 에서 잃은 2건(proposal 113 · 166)은 둘 다 `candidate_budget_exhausted` 였다.
`target-seed` 를 앞으로 옮기면서 proposal 당 후보 예산을 먼저 먹어, 예전에
gate-overlap / corner-contact 로 살아나던 프레임이 예산 소진으로 죽은 것이다.
예전 파이프라인도 **같은 offset 을 같은 빈도로** 시도했으므로(위치만 뒤), 해석적 seed
단계를 예산 회계에서 빼는 것이 원상 복구다 — 게이트 완화가 아니다.

그 대가로 실패 프레임이 후보를 더 많이 평가하게 됐다
(`score_callback` reject 1,338 -> 2,026,
`candidate_budget_exhausted` 543 -> 434),
그래서 총시간이 +1.4% 다. **낭비의 성격이 바뀌었다** — "context 를 놓고 버리는"
1,151초가 사라지고, "후보를 더 보는" 시간이 들어왔으며 그 대가로 recall 2건 회복 +
expensive reject 1건이 accepted 로 살아났다.

### 다음에 시도할 것 (이번엔 하지 않았다)

target-seed 후보 수는 median 16 · max 24 인데, 보호가 필요했던 두 프레임은 **8개**만
썼다. 예산 면제를 무제한이 아니라 **상한 있는 허용치**로 바꾸면 recall 을 지키면서
총시간을 되찾을 여지가 있다. replay 1회가 약 66분이라 이번 범위에서는 시도하지 않았다.

## 6. 산출

```
locked_controlled_cases.{json,csv}   고정 입력 77건 (FrameSpec/Plan SHA · seed · 구 결과·비용)
replay_before_after.{csv,json,md}     before/after 전건 비교
prefilter_replay.{csv,md}            prefilter recall 49/49 재확인
logs/replay.log                       Blender 실행 로그
```
