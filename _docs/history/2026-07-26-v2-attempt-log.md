# 2026-07-26 Blender v2 constrained scene assembly 전체 시행착오

## 문서 목적

이 문서는 [2026-07-26.md](2026-07-26.md)의 결과 요약만으로는 다음 작업자가 실패 경로를 재현하기 어렵다는 문제를 보완한다. 2026-07-26 01:26의 첫 단일 프레임 probe부터 15:09의 exact 20-frame smoke, 이후 500-record 진단과 전수 감사까지 다음 내용을 시간순으로 기록한다.

- 무엇을 시험했는가.
- 실제 출력은 어디에 남았는가.
- 어떤 실패가 발생했는가.
- 당시 가설과 실제로 확인된 원인을 어떻게 구분하는가.
- 어떤 수정 후 어느 지표가 바뀌었는가.
- 아직 해결되지 않은 것은 무엇인가.

기록 표기는 다음과 같다.

- `[확인]`: `driver_summary.json`, `progress.json`, `records.jsonl`, Blender 로그, decoded 산출물 또는 comparator를 직접 읽어 확인했다.
- `[추정]`: 디렉터리 이름과 실행 종료 시점은 남아 있지만 로그에 명시적인 예외나 작업자 중단 사유가 없다.
- `[판정]`: 위 증거를 바탕으로 다음 구현 또는 운영 원칙으로 채택한 결론이다.

## 증거를 읽을 때의 주의점

- `[확인]` `driver_summary.json`은 정상적으로 session이 끝났을 때의 스냅샷이다. 중간 중단 후 재개한 출력에서는 이전 chunk의 summary가 남아 있을 수 있으므로 최신 `progress.json`과 `records.jsonl`을 함께 봐야 한다.
- `[확인]` `records.jsonl`은 append 로그다. 재시도한 index가 두 번 기록될 수 있다. 예를 들어 첫 500 중단 실행은 raw 62줄이지만 unique index는 61개이며, idx 32는 첫 `camera_clearance` 실패 뒤 재개 실행에서 렌더된 기록이 한 번 더 있다.
- `[확인]` Blender 로그가 traceback 없이 렌더 중간에서 끝난 경우는 프로세스 오류로 단정하지 않았다. 이 문서에서는 `중간 종료`로 적고, 디렉터리 이름으로 추론한 개발 단계는 `[추정]`으로 표시한다.
- 아래 `R/Rend/Fail/AP`는 각각 기록 수, 렌더 성공 수, realize 실패 수, G1~G5 all-pass 수다.

## 전체 흐름 요약

```text
초기 역할·mask 경로 부팅
  → anchor broad-phase가 모든 위치를 막음
  → anchor 실패 12/20에서 0/20으로 감소
  → 500 실행 중 stale HDRI 경로 발견
  → contact/explicit 계약을 넣기 위해 대형 실행 중단
  → fail-closed explicit solver에서 특정 frame 16/19 반복 실패
  → asset/scale/depth/yaw/ground/support 가설을 단일 프레임으로 분리
  → image-space 목표와 G2 corner 계약을 분리
  → reusable hierarchy의 hidden-child AABB 교차 프레임 누수 수정
  → GPU, CPU, no-denoise만으로는 exact RGB 재현 실패
  → CPU + adaptive off + denoise off + render thread 1에서 exact 재현
  → exact 20-frame 2회 통과
  → 500-record/435-render 진단 및 500-index 전수 감사
```

## 1. 01:26~01:44 — 단일 프레임 부팅과 support 경로 확인

첫 단계는 500장을 돌리는 것이 아니라 constrained 경로가 기존 production 경로와 분리된 상태에서 Blender 안에서 실제로 한 프레임을 완주하는지 확인하는 것이었다.

```text
시간      출력 suffix                       R/Rend/Fail/AP   결과
01:26     probe1_seed7500                    1/1/0/0          G5
01:27     probe1b_seed7500                   1/1/0/0          G5
01:28     probe_modes_seed7500               1/1/0/1          accepted
01:33     probe_modes2_seed7500              3/3/0/3          accepted 3
01:35     probe_modes2_repeat_seed7500       1/1/0/1          accepted
01:44     probe_supportfix_seed7500           3/3/0/3          accepted 3
```

- `[확인]` 첫 두 probe는 렌더와 레이블 생성까지는 성공했지만 저조도 G5에서 실패했다. 즉 pipeline 자체가 죽은 것은 아니었다.
- `[확인]` mode probe와 support 수정 probe에서는 단일/3개 프레임이 모두 accepted가 되어 anchor, support, M0~M4, final RGB/label의 최소 경로가 연결되었음을 확인했다.
- `[판정]` 이 결과만으로 scene logic 전체가 안정적이라고 보지 않고, 동일 seed의 20-frame smoke로 넘어갔다.

## 2. 01:50~02:44 — anchor broad-phase 과거부 수정

### 최초 20-frame smoke

출력: `data/pallet/_v2_scene_logic_smoke20_seed7500`

```text
records/rendered/realize_fail/all-pass  20/8/12/6
anchor_fail                              12
G1                                       1
G5                                       1
```

- `[확인]` 12개 realize 실패의 세부 원인은 11개가 마지막 사유 `inflated_static_aabb`, 1개가 `support`였다.
- `[확인]` `inflated_static_aabb` 실패 프레임은 대부분 24번의 anchor 후보를 모두 같은 이유로 거부했다.
- `[판정]` 이 결과는 “배경이 복잡해서 우연히 자리가 없었다”가 아니라 broad phase가 실제 배치 가능 영역까지 막는 구조 문제로 취급했다.

### 수정 뒤 반복

```text
출력 suffix                         R/Rend/Fail/AP   남은 실패
smoke20_seed7500_r2                 20/19/1/15       idx12 support 1, G1 2, G5 2
smoke20_seed7500_r3                 20/20/0/15       G1 3, G5 2
smoke20_seed7500_r3_repeat          20/20/0/15       G1 3, G5 2
smoke20_seed7500_r4                 20/20/0/15       G1 3, G5 2
```

- `[확인]` r2에서 broad-phase anchor 실패는 제거되고 idx 12의 support 실패만 남았다.
- `[확인]` r3부터 20개 모두 렌더되었다.
- `[확인]` r3와 r3_repeat는 record/label/mask가 같았지만 decoded RGB 20장 모두에서 픽셀 차이가 났다. 당시에는 분포 재현과 render exact 재현이 서로 다른 문제임을 확인하고 렌더 비결정성은 뒤 단계에서 별도로 분리했다.

## 3. 02:44~03:57 — 첫 500 실행 두 번을 끝까지 쓰지 않은 이유

### 첫 실행: stale HDRI 경로

보존 출력: `data/pallet/_v2_scene_logic_500_seed7500_failed_missing_hdri_20260726`

```text
progress unique records/rendered/all-pass  61/61/55
raw records.jsonl lines                    62
RGB/label/mask files                       61/61/305
complete                                   false
```

- `[확인]` 첫 로그는 30개 HDRI 중 `factory_yard_2k.hdr`를 `no pixels`로 skip했다고 출력했다.
- `[확인]` resume 로그에서는 Blender가 `C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\factory_yard_2k.hdr`를 찾지 못한다는 오류를 두 번 기록했다. 현재 workspace는 `E:\CODING\GitHub\FoundationPose`이므로 실행 중 선택된 image 경로가 과거 workspace의 절대경로를 가리켰다.
- `[확인]` 이 오류가 찍힌 뒤에도 idx 60까지 렌더가 계속되었다. 따라서 “HDRI 오류로 Blender가 즉시 crash했다”가 아니라, 누락 HDRI가 선택될 수 있는 데이터 무결성 문제가 확인되어 실행을 폐기한 것이다.
- `[확인]` idx 32는 첫 시도 `camera_clearance` 실패와 재개 후 렌더/G1 기록이 모두 append되어 raw 62줄, unique 61 index가 되었다.
- `[판정]` 일부 프레임이 이미 생성되었더라도 환경 asset pool이 깨진 실행은 500 진단 정본으로 이어 쓰지 않고 별도 실패 디렉터리로 보존했다.
- `[확인]` 다음 실행 로그의 constrained HDRI pool은 유효한 28개만 채택했다.

### 두 번째 실행: 100장을 본 뒤 계약을 다시 고치기 위해 중단

보존 출력: `data/pallet/_v2_scene_logic_500_seed7500_failed_prereview_p1_20260726`

```text
stale driver summary                      100/100/0/90
latest progress                           164 records, 163 rendered, 1 fail, 144 all-pass
mode                                      clean 100 + cargo 64
RGB/label/mask                            163/163/815
complete                                  false
```

- `[확인]` 0~99 clean chunk는 끝났고, 100~163 cargo 구간까지 진행되었다.
- `[확인]` idx 103의 `anchor_fail/static_los` 1건 때문에 164 records와 163 RGB가 일치한다. 해당 frame은 `static_los`로 anchor 후보 24개를 모두 거부했다.
- `[확인]` 로그에는 Python traceback이나 Blender fatal error가 없다. resume 로그가 idx 163 렌더 뒤 끝난다.
- `[추정]` 디렉터리명 `failed_prereview_p1`과 이후 바로 이어진 `precontactmatrix` smoke를 보면, 500장을 끝까지 소비하기 전에 contact matrix 및 explicit 계약을 먼저 고치기 위해 작업자가 중단한 checkpoint다.
- `[판정]` 이 실행의 100-frame summary를 최종 500 결과로 재사용하지 않고 전체 디렉터리를 실패 보존본으로 분리했다.

## 4. 04:12~04:50 — contact matrix, explicit 계약, fail-closed 전환

```text
출력 suffix                                      상태
r8_failed_precontactmatrix_20260726               progress 13, RGB 14, record 13
r8                                                 빈 출력 디렉터리
r9                                                 20/20/0/14; G1 3, G5 3
r10_failed_preexplicitfix_20260726                13/13/0/8; G1 3, G5 2
r11_failed_prefailclosed_20260726                 record 0; RGB 1, M0~M3 4장
r12                                                20/18/2/13
```

- `[확인]` r8 로그는 idx 13의 RGB, label, M0~M4까지 저장한 뒤 record/progress append 전에 끝났다. 그래서 progress는 13인데 RGB/label은 각각 14장이다. traceback은 없다.
- `[확인]` r10은 13개 record에서 끝났고, 다음 idx 13의 임시 cargo/context mask를 만들던 중 로그가 끝났다. 최종 idx 13 RGB/label/M0~M4는 없으며 traceback도 없다.
- `[확인]` r11은 idx 0의 RGB와 M0~M3까지만 남고 M4, label, record가 없다. fail-closed 수정 전의 완결되지 않은 실행이므로 통계에서 제외했다.
- `[추정]` `precontactmatrix`, `preexplicitfix`, `prefailclosed`라는 이름과 traceback 없는 중간 EOF는 각각 다음 계약 변경을 위해 의도적으로 중단한 실행임을 나타낸다.
- `[확인]` r12에서 모든 프레임을 억지로 렌더하지 않고, 유효한 explicit placement를 찾지 못한 idx 16과 19를 `bounded_local_search_exhausted`로 실패시켰다.
- `[판정]` invalid occluder를 억지로 저장하는 것보다 명시적인 realize failure record를 남기는 fail-closed 정책을 유지했다.

## 5. 04:54~07:46 — frame 16/19 explicit solver 집중 분리

### 첫 반복: 실패가 context 때문인지 확인

- `[확인]` `f16_r1`부터 `f16_r20_support_hits`까지 대부분의 frame 16 probe는 `bounded_local_search_exhausted`였다.
- `[확인]` `f16_r18_no_context`도 같은 사유로 실패했다. 따라서 context clutter만 제거한다고 해결되지 않았다.
- `[확인]` `f16_r20_support_hits`까지 support 정보를 늘려도 실패했다.
- `[확인]` `f16_r21_mesh_contacts`, `f16_r17_current`, `f16_r22_best_seed`, `f16_r22_current`, `f16_r23_axis_feedback`은 각각 한 프레임 accepted를 만들었다.
- `[확인]` 그러나 fail-closed 조건을 다시 적용한 `f16_r24_failclosed`와 `f16_r24_side_seed_axis_feedback`은 다시 bounded failure였다.
- `[판정]` 한 번 화면에 보이게 만드는 것과 최종 collision/support/side/overlap 계약을 동시에 만족시키는 것은 다르므로, 일시적인 accepted probe 하나만으로 solver를 완료 처리하지 않았다.

### infeasible guard와 후보 다양화

```text
시도 이름의 핵심 가설                         실제 terminal 결과
infeasible_guard                              explicit_target_infeasible
side_candidate_feedback                       bounded_local_search_exhausted
pool640_mesh_support                          bounded_local_search_exhausted
pool640_six_fallback                          bounded_local_search_exhausted
shape_diverse                                 bounded_local_search_exhausted
bidirectional_depth                           bounded_local_search_exhausted
ground_compensated_depth                      bounded_local_search_exhausted
axis_fixed                                    bounded_local_search_exhausted
thin_upright                                  bounded_local_search_exhausted
manifest_normalized                           bounded_local_search_exhausted
uniform_scale                                 bounded_local_search_exhausted
reserved_corridor                             bounded_local_search_exhausted
reserved_world_pose                           bounded_local_search_exhausted
feedback_yaw90                                bounded_local_search_exhausted
tall_shallow                                  bounded_local_search_exhausted
ground_feasible_bottom                        bounded_local_search_exhausted
```

- `[확인]` `f16_r25_infeasible_guard`는 후보 탐색을 시작하기 전에 target을 달성 불가능하다고 판정하여 `explicit_target_infeasible`을 기록했다. 이 판정 자체가 너무 공격적인지를 확인하기 위해 이후에는 다시 bounded candidate search를 사용했다.
- `[확인]` 후보 pool 크기, fallback 수, shape 다양성, 양방향 depth, 바닥 보정, local axis, scale, corridor 예약, yaw 90도, tall/shallow 형태를 각각 바꿔도 frame 16은 안정적으로 해결되지 않았다.
- `[판정]` 실패 원인을 단일 상수 하나로 보지 않고 image-space 목표, ground support, BVH 충돌, side 계약을 분리하는 다음 단계로 넘어갔다.

### frame 18/19 관찰

- `[확인]` `f18_r19_log`는 렌더되었지만 G5로 실패했다.
- `[확인]` `f18_19_r27_targeted`는 두 record 중 하나가 렌더/G5, 하나가 bounded failure였다.
- `[확인]` `f18_19_r18_current`, `f19_r20_current`, `f18_19_r26_failclosed`, `f18_r01`은 완결된 record가 없는 중단/빈 probe다.

## 6. 07:57~10:10 — image-space 목표, G2, normalize 분리

### image-space 및 target utility

```text
probe                                         결과
idx10_context_image_space_r01                 accepted
f16_r38_aspect_lowres                         bounded failure
f16_r39_current_modes                         accepted
idx02_explicit_primary_only_r01               bounded failure
idx02_targeted_u_r01                          accepted
idx02_all_assets_initial_r01                  bounded failure
idx02_prealign_r02                            accepted
idx02_utility_first_r03                       accepted
idx02_swept_reservation_r04                   mesh_overlap
idx02_swept_reservation_r05                   accepted
idx02_bvhfallback_r05                         accepted
idx02_targetscore_r08                         accepted
```

- `[확인]` context object를 image-space 기준으로 평가한 idx 10은 accepted였다.
- `[확인]` explicit 후보를 primary asset 하나로 제한하거나 모든 asset 초기값만 늘리는 것은 idx 2에서 실패했다.
- `[확인]` target `u`, pre-alignment, utility-first score, swept reservation, BVH fallback, target score를 차례로 분리하면서 idx 2를 accepted로 만들 수 있었다.
- `[확인]` swept reservation r04는 `mesh_overlap`을 정확히 검출하고 fail-closed했으며 r05에서 accepted가 되었다. 충돌 검사를 완화해서 통과시킨 것이 아니다.

### “보인다”와 G2를 만족한다는 차이

```text
idx06 시도                         결과
r04                                bounded failure
r05, r06                           rendered, G2 fail
r08~r14                            bounded failure
r16                                accepted
```

- `[확인]` r05/r06은 explicit occluder가 렌더되었지만 외부 가림 corner 수 G2를 만족하지 못했다.
- `[판정]` `explicit_visible_pixels > 0`만으로 성공 처리하지 않고 실제 external-occluded corner 계약을 유지했다.

### asset normalization probe

```text
probe                         결과
idx07_norm_r01                bounded failure
idx09_norm_r01~r04            모두 bounded failure
idx14_norm_r01                bounded failure
idx14_norm_r02                accepted
idx10_norm_r02                accepted
idx02_norm_final_r01          accepted
```

- `[확인]` manifest/asset normalization은 idx 14, 10, 2에서는 accepted 결과와 연결됐지만 idx 7과 9를 보편적으로 해결하지 못했다.
- `[판정]` normalization을 만능 원인으로 기록하지 않고, 다음 smoke에서 교차 프레임 상태 누수를 별도로 확인했다.

## 7. 13:27~14:21 — 교차 프레임 transform/AABB 상태 누수

```text
출력 suffix       R/Rend/Fail/AP   bounded failure index
final_a            20/17/3/12       9, 10, 14
final_c            20/18/2/13       9, 14
final_d            20/18/2/13       9, 14
final_e            20/20/0/14       없음
final_f            20/20/0/14       없음
```

- `[확인]` 같은 seed의 final_c와 final_d가 똑같이 idx 9와 14에서 실패해 단순 확률적 운으로 보기는 어려웠다.
- `[확인]` `idx09_10_state_r01`에서 idx 9는 bounded failure, 바로 다음 idx 10은 accepted였다.
- `[확인]` reusable object hierarchy를 숨긴 상태에서 root transform을 되돌려도 child의 evaluated transform/AABB가 이전 프레임 값을 보유할 수 있는 경로가 있었다.
- `[확인]` `scene_visibility_v2.fresh_world_aabb()`는 hierarchy visibility와 dependency graph를 갱신한 뒤 AABB를 다시 계산한다.
- `[확인]` `blender_probe_v2_transform_reset.py`는 base transform 복구, hidden child AABB, 재배치 center, deterministic render setting의 복구를 검사하며 `transform-reset-regression PASS`를 반환했다.
- `[확인]` 수정 뒤 final_e와 final_f는 둘 다 20/20 렌더, realize failure 0이었다.
- `[판정]` “특정 asset이 나쁘다”가 아니라 reusable Blender object의 교차 프레임 상태를 매 frame 명시적으로 초기화하고 fresh evaluated AABB를 쓰는 문제로 봉합했다.

## 8. 14:25~15:09 — exact render determinism 분리 실험

동일 seed의 geometry/label/mask가 같아도 RGB가 bit-exact하지 않았기 때문에 렌더 설정을 한 항목씩 분리했다.

```text
비교 pair                    records labels RGB masks   deterministic   mismatch
r3 vs r3_repeat              20      20     20  100     false           RGB 20
final_g_cpu vs final_h_cpu   20      20     20  100     false           RGB 12
nodenoise i vs j              1       1      1    5     false           RGB 1
singlethread k vs l           1       1      1    5     true            0
final_m_exact vs n_exact     20      20     20  100     true            0
```

- `[확인]` GPU 반복은 RGB 20/20이 달랐다.
- `[확인]` CPU로만 바꾼 full smoke도 RGB 12/20이 달랐다.
- `[확인]` CPU에서 denoise를 끈 1-frame pair도 RGB가 달랐다.
- `[확인]` render thread를 1개로 고정한 1-frame pair가 처음 exact match했다.
- `[확인]` 최종 설정은 CPU, adaptive sampling off, denoise off, `threads_mode=FIXED`, `threads=1`이다.
- `[확인]` 이 설정으로 final_m_exact와 final_n_exact는 record 20, label 20, decoded RGB 20, decoded mask 100이 모두 exact match했다.
- `[판정]` production의 기본 렌더 설정은 바꾸지 않고 진단 runner의 exact smoke에서만 deterministic setting을 opt-in했다.

## 9. 최종 500-record 진단과 남은 실패

정본 출력: `data/pallet/_v2_scene_logic_500_seed7500`

```text
records/rendered/realize_fail/all-pass  500/435/65/364
rendered 기준 all-pass                  83.68%
proposal 기준 all-pass                  72.80%
fatal defect                            0
exact collision max                     0
```

realize failure는 다음과 같다.

```text
controlled / bounded_local_search_exhausted  62
controlled / anchor_fail                      1
context / anchor_fail                         2
```

- `[확인]` 500장은 “완성 이미지 500장”이 아니라 proposal record 500개와 RGB/label 435개의 진단 실행이다.
- `[확인]` controlled target 150개 중 87개만 렌더되어 proposal-to-render delivery는 58%다.
- `[확인]` 렌더된 controlled 87개는 explicit occluder가 모두 보였고 `|actual-target|` 중앙값은 0.03823이지만 center actual은 3개뿐이다.
- `[확인]` 자동 audit fatal defect는 0이지만, accepted 중 M0 area 100 px 미만 extreme-small 12개와 visible noise/dark warning이 남는다.
- `[판정]` constrained 경로는 진단 opt-in 상태로 유지하고 production default와 40k 본렌더는 승인하지 않았다.

## 실패 분류와 현재 해석

```text
실패 계열                    처음 관찰                 확인된 해석/현재 상태
anchor inflated AABB         smoke20 최초 12건         broad phase 과거부; r3에서 0건
support                      r2 idx12                  단독 support 실패; 후속 smoke에서 제거
stale HDRI absolute path     첫 500 resume            과거 C: 경로 datablock; 유효 pool 28개로 제한
중간 실행 종료              r8/r10/r11, 일부 probe   traceback 없음; 통계 제외, 산출물만 보존
explicit bounded exhaustion r12 idx16/19             fail-closed의 실제 미전달; 최종 500에도 62건
explicit infeasible guard    f16 r25                  조기 판정 1건; 보편 원인으로 채택하지 않음
mesh overlap                 idx02 swept r04          exact collision이 정상적으로 거부; r05에서 수정
G2                           idx06 r05/r06            occluder visible과 external corner 가림은 별개
hidden-child stale AABB      final a/c/d              fresh evaluated AABB + transform reset으로 수정
GPU RGB nondeterminism       r3 pair                  record/label/mask 동일, RGB 20건 불일치
CPU RGB nondeterminism       final g/h                CPU만으로 부족, RGB 12건 불일치
no-denoise nondeterminism    probe i/j                 denoise off만으로 부족
exact RGB                    probe k/l, final m/n      single render thread 포함 시 exact
tiny accepted target         final 500 audit          아직 architecture-derived size gate 없음
center under-delivery        final 500                3/87; 아직 미해결
```

## 다음 세션이 먼저 볼 파일

```text
요약 결과
  _docs/history/2026-07-26.md

전체 시행착오
  _docs/history/2026-07-26-v2-attempt-log.md

최종 smoke
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_m_exact/
  data/pallet/_v2_scene_logic_smoke20_seed7500_final_n_exact/

최종 500 진단
  data/pallet/_v2_scene_logic_500_seed7500/
  data/pallet/_v2_scene_logic_500_seed7500/eda/

대표 중단 실행
  data/pallet/_v2_scene_logic_500_seed7500_failed_missing_hdri_20260726/
  data/pallet/_v2_scene_logic_500_seed7500_failed_prereview_p1_20260726/
  data/pallet/_v2_scene_logic_smoke20_seed7500_r8_failed_precontactmatrix_20260726/
  data/pallet/_v2_scene_logic_smoke20_seed7500_r10_failed_preexplicitfix_20260726/
  data/pallet/_v2_scene_logic_smoke20_seed7500_r11_failed_prefailclosed_20260726/

회귀 검증
  scripts/data_prep/blender/tests/blender_probe_v2_collision_support.py
  scripts/data_prep/blender/tests/blender_probe_v2_transform_reset.py
  scripts/data_prep/blender/tests/blender_probe_v2_holdout_shared_material.py
  scripts/data_prep/blender/compare_v2_determinism.py
```

## 시행착오가 현재 코드에 남은 위치

```text
역할/contact 정책 및 mask 불변식
  scripts/data_prep/blender/scene_placement_v2.py
  - contact matrix                         around line 1301
  - M0~M4 decomposition order             line 1467
  - mask monotonicity validation          around line 1561
  - corner-contact refinement offsets     line 889

재사용 오브젝트 상태 초기화
  scripts/data_prep/blender/scene_visibility_v2.py
  - ensure_base_transform                 line 486
  - restore_base_transform                line 504
  - fresh_world_aabb                      line 519

support/contact 및 explicit 배치
  scripts/data_prep/blender/scene_visibility_v2.py
  - place_initial_explicit_occluder       line 2116
  - explicit feedback/support checks      around line 2230
  - collision/camera clearance audit      line 2486

Blender realize/fail-closed
  scripts/data_prep/blender/v2_realize.py
  - _realize_constrained                  line 676
  - corner-contact refine 연결           around line 2212
  - bounded_local_search_exhausted        around line 2428
  - deterministic_rgb_render_settings     line 3202

exact comparator
  scripts/data_prep/blender/compare_v2_determinism.py
  - compare_output_roots                  line 224
  - CLI main                              line 394
```

## 보존 출력 전체 인덱스

아래 인덱스는 2026-07-26 종료 시점 `data/pallet/_v2_scene_logic*` 디렉터리 133개를 시간순으로 분류한 것이다. 이름이 길어 공통 접두사 `data/pallet/_v2_scene_logic_`는 생략했다. `empty`는 디렉터리는 있지만 완결된 `records.jsonl` record가 없는 실행이다.

### A. 부팅, smoke, 첫 500

```text
probe1_seed7500                                      1/1/0/0   G5
probe1b_seed7500                                     1/1/0/0   G5
probe_modes_seed7500                                 1/1/0/1   accepted
probe_modes2_seed7500                                3/3/0/3   accepted
probe_modes2_repeat_seed7500                         1/1/0/1   accepted
probe_supportfix_seed7500                            3/3/0/3   accepted
smoke20_seed7500                                    20/8/12/6  anchor 12, G1 1, G5 1
smoke20_seed7500_r2                                20/19/1/15  anchor 1, G1 2, G5 2
smoke20_seed7500_r3                                20/20/0/15  G1 3, G5 2
smoke20_seed7500_r3_repeat                         20/20/0/15  G1 3, G5 2
smoke20_seed7500_r4                                20/20/0/15  G1 3, G5 2
500_seed7500_failed_missing_hdri_20260726           61 unique   interrupted, 61 rendered
smoke20_seed7500_r5                                20/20/0/14  G1 3, G5 3
smoke20_seed7500_r6                                20/20/0/14  G1 3, G5 3
smoke20_seed7500_r7_probe_idx7                      1/1/0/0     G1
smoke20_seed7500_r7                                20/20/0/14  G1 3, G5 3
500_seed7500_failed_prereview_p1_20260726          164 records  163 rendered, anchor 1
smoke20_seed7500_r8_failed_precontactmatrix_20260726 13 records  interrupted
smoke20_seed7500_r8                                  empty
smoke20_seed7500_r9                                20/20/0/14  G1 3, G5 3
smoke20_seed7500_r10_failed_preexplicitfix_20260726 13/13/0/8   interrupted
smoke20_seed7500_r11_failed_prefailclosed_20260726   empty      partial RGB/M0~M3
smoke20_seed7500_r12                               20/18/2/13  bounded 2, G1 3, G5 2
```

### B. frame 16/18/19 explicit solver

```text
probe_seed7500_f16_r1                               bounded
probe_seed7500_f19_r1                               bounded
probe_seed7500_f16_r2                               bounded
probe_seed7500_f16_r3                               bounded
probe_seed7500_f16_r4                               bounded
probe_seed7500_f16_r5                               bounded
probe_seed7500_f16_r6                               bounded
probe_seed7500_f16_r7                               bounded
probe_seed7500_f16_r8                               bounded
probe_seed7500_f16_r9                               bounded
probe_seed7500_f16_r10                              bounded
probe_seed7500_f16_r11                              bounded
probe_seed7500_f16_r13                              bounded
probe_seed7500_f16_r14                              bounded
probe_seed7500_f16_r15                              bounded
probe_seed7500_f16_r17                              bounded
probe_seed7500_f16_r18_no_context                   bounded
probe_seed7500_f16_r19                              bounded
probe_seed7500_f16_r20_support_hits                 bounded
probe_seed7500_f16_r16                              bounded
probe_seed7500_f16_r21_mesh_contacts                accepted
probe_seed7500_f16_r17_current                      accepted
probe_seed7500_f18_19_r18_current                   empty
probe_seed7500_f16_r22_best_seed                    accepted
probe_seed7500_f16_r22_current                      accepted
probe_seed7500_f18_r19_log                          rendered, G5
probe_seed7500_f19_r20_current                      empty
probe_seed7500_f16_r23_axis_feedback                accepted
probe_seed7500_f16_r24_failclosed                   bounded
probe_seed7500_f16_r24_side_seed_axis_feedback      bounded
probe_seed7500_f16_r25_infeasible_guard             explicit_target_infeasible
probe_seed7500_f18_19_r26_failclosed                empty
probe_seed7500_f16_r25_side_candidate_feedback      bounded
probe_seed7500_f16_r26_pool640_mesh_support         bounded
probe_seed7500_f16_r27_pool640_six_fallback         bounded
probe_seed7500_f18_19_r27_targeted                  2/1/1/0; bounded 1, G5 1
probe_seed7500_f16_r28_shape_diverse                bounded
probe_seed7500_f16_r29_bidirectional_depth          bounded
probe_seed7500_f16_r30_ground_compensated_depth     bounded
probe_seed7500_f16_r31_axis_fixed                   bounded
probe_seed7500_f16_r32_thin_upright                 bounded
probe_seed7500_f16_r33_thin_upright                 bounded
probe_seed7500_f16_r33_manifest_normalized          bounded
probe_seed7500_f16_r34_uniform_scale                bounded
probe_seed7500_f16_r34_reserved_corridor            bounded
probe_seed7500_f16_r35_reserved_world_pose          bounded
probe_seed7500_f16_r35_feedback_yaw90               bounded
probe_seed7500_f16_r36_tall_shallow                 bounded
probe_seed7500_f16_r37_ground_feasible_bottom       bounded
probe_seed7500_f18_r01                              empty
```

### C. image-space, target utility, G2, normalization

```text
probe_seed7500_idx10_context_image_space_r01        accepted
probe_seed7500_idx02_controlled_image_space_r01     empty
probe_seed7500_f16_r38_aspect_lowres                bounded
probe_seed7500_idx02_explicit_primary_only_r01      bounded
probe_seed7500_f16_r39_current_modes                accepted
smoke20_seed7500_r40                                partial 2; accepted 1, G5 1
probe_seed7500_idx02_targeted_u_r01                 accepted
probe_seed7500_idx02_all_assets_initial_r01         bounded
probe_seed7500_idx02_prealign_r01                   empty
probe_seed7500_idx02_prealign_r02                   accepted
probe_seed7500_idx02_utility_first_r03              accepted
probe_seed7500_idx02_swept_reservation_r04          mesh_overlap
probe_seed7500_idx02_swept_reservation_r05          accepted
probe_seed7500_idx06_r01                            empty
probe_seed7500_idx02_bvhfallback_r05                accepted
probe_seed7500_idx02_scorestage_r06                 empty
probe_seed7500_idx06_r02                            empty
probe_seed7500_idx02_targetscore_r07                empty
probe_seed7500_idx02_targetscore_r08                accepted
probe_seed7500_idx06_r03                            empty
probe_seed7500_idx06_targetscore_r03                empty
probe_seed7500_idx06_r04                            bounded
probe_seed7500_idx06_r05                            rendered, G2
probe_seed7500_idx06_r06                            rendered, G2
probe_seed7500_idx06_r07                            empty
probe_seed7500_idx06_r08                            bounded
probe_seed7500_idx06_r09                            bounded
probe_seed7500_idx06_r10                            bounded
probe_seed7500_idx06_r11                            bounded
probe_seed7500_idx06_r12                            bounded
probe_seed7500_idx06_r13                            bounded
probe_seed7500_idx06_r14                            bounded
probe_seed7500_idx06_r15                            empty
probe_seed7500_idx06_r16                            accepted
probe_seed7500_idx07_norm_r01                       bounded
probe_seed7500_idx09_norm_r01                       bounded
probe_seed7500_idx14_norm_r01                       bounded
probe_seed7500_idx14_norm_r02                       accepted
probe_seed7500_idx09_norm_r02                       bounded
probe_seed7500_idx09_norm_r03                       bounded
probe_seed7500_idx09_norm_r04                       bounded
probe_seed7500_idx10_norm_r02                       accepted
probe_seed7500_idx02_norm_final_r01                 accepted
```

### D. state leak, determinism, final 진단

```text
smoke20_seed7500_final_a                            20/17/3/12; bounded 3
probe_seed7500_idx09_10_state_r01                    2/1/1/1; idx9 bounded, idx10 accepted
smoke20_seed7500_final_c                            20/18/2/13; bounded 2
smoke20_seed7500_final_d                            20/18/2/13; bounded 2
smoke20_seed7500_final_e                            20/20/0/14
smoke20_seed7500_final_f                            20/20/0/14
smoke20_seed7500_cpu_probe_g                         1/1/0/0; G5
smoke20_seed7500_cpu_probe_h                         1/1/0/0; G5
smoke20_seed7500_final_g_cpu                        20/20/0/14; exact RGB false
smoke20_seed7500_final_h_cpu                        20/20/0/14; exact RGB false
smoke20_seed7500_nodenoise_probe_i                   1/1/0/1
smoke20_seed7500_nodenoise_probe_j                   1/1/0/1; pair exact false
smoke20_seed7500_singlethread_probe_k                1/1/0/1
smoke20_seed7500_singlethread_probe_l                1/1/0/1; pair exact true
smoke20_seed7500_final_m_exact                      20/20/0/14
smoke20_seed7500_final_n_exact                      20/20/0/14; pair exact true
500_seed7500                                       500/435/65/364; final diagnostic
```

## 기록에서 제외하거나 과장하지 않은 것

- 빈 probe 디렉터리는 성공이나 실패로 보간하지 않았다.
- traceback 없는 중간 EOF는 Blender crash라고 단정하지 않았다.
- 디렉터리명에 적힌 가설은 그 가설을 시험했다는 기록이지 원인이 입증됐다는 뜻이 아니다.
- 한 프레임 accepted는 전체 solver 안정성 증거로 취급하지 않았다.
- 500-record의 435 rendered를 500-image 데이터셋이라고 부르지 않았다.
- BVH `exact_collision_count=0`을 근거로 충돌 없음은 말할 수 있지만, thumbnail 육안만으로 관통 없음이라고 판정하지 않았다.
- final 500의 높은 rendered-frame all-pass를 distribution 설계의 causal improvement라고 주장하지 않았다.
