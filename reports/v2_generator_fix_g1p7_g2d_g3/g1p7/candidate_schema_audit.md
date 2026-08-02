# G1.7 §6 — candidate log schema 감사

**결론: 기존 G1.6 candidate log 만으로 §7-§11 감사가 가능하다.
instrumentation-only patch 와 그에 따른 subset replay 는 실행하지 않는다.**

## 필드 대응

```
요구 항목                실제 위치                                        상태
─────────────────────────────────────────────────────────────────────────────────
case_id                  record.proposal_index                            있음  — locked case 식별자
proposal_index           candidate.proposal_index                         있음
candidate_id             (파생) case_id:order                               파생  — 로그 순서로 결정적 생성
asset identity           candidate.proposal_object                        있음
stage                    candidate.stage                                  있음
geometry key             (파생) asset|center|yaw|u/v/depth/yaw offset       파생  — §7 canonical key
side_match               candidate.occluder_side_match                    있음  — actual 은 occluder_side_actual
visible_pixels           candidate.object_visible_pixels                  있음
target_abs_error         candidate.abs_error                              있음
target_error_ok          candidate.target_error_ok                        있음
G1                       candidate.candidate_G1_pass + candidate_V_vis    있음  — boolean + 연속 margin 둘 다
G2                       candidate.candidate_G2_pass + candidate_ext_occ_corners 있음  — boolean + 연속 margin 둘 다
support pass             candidate.support_reason / support_error         있음
collision pass           candidate.collision_object                       있음
camera-clearance pass    candidate.camera_clearance_ok                    있음  — camera_clearance_min/object 도 있음
scalar score             candidate.score                                  있음
rejection reason         candidate.reason                                 있음
runtime                  (후보 단위 없음) record.replay_wall_s = CASE_WALL_TIME_S case 단위만  — §10 primary clock 은 case 단위라 충분
lowres render count      record.lowres_render_count                       case 단위만  — 후보 단위 분해 없음
u/v offset               candidate.u_offset / v_offset                    있음
depth                    candidate.depth_offset                           있음
scale                    (없음)                                             없음  — 현재 solver 는 explicit occluder scale 을 탐색축으로 쓰지 않는다
orientation              candidate.yaw_rad / yaw_offset                   있음
final selected 여부        candidate.score_accept + record.explicit_selected_stage 있음
```

## 부족한 3개와 그 처리

1. **candidate_id** — 원본에 없지만 candidate log 의 **순서**가 결정적이므로
   `case_id:order` 로 파생한다.  새 필드를 렌더로 만들 필요가 없다.
2. **candidate 단위 runtime / lowres render count** — 없다.  그러나 §10 이
   지정한 primary clock 은 **CASE_WALL_TIME_S** 이고, 이는 replay record 의
   `replay_wall_s` 로 이미 존재한다.  전 77건 합이 **4754.3 s** 로 지시문이 명시한
   G1.6 baseline 4,754.4 s 와 일치한다 [확인].  따라서 후보 단위 시간이 없어도
   §10·§11 판정에 필요한 시계는 완비돼 있다.
3. **scale** — 현재 solver 에 explicit occluder scale 탐색축 자체가 없다.
   없는 축을 계측하려고 만들지 않는다 (§16 "현재 solver 에서 실제로 존재하는
   축만 사용한다").

## instrumentation replay 를 하지 않는 근거

§6 은 "필드가 충분하면 기존 record 만 사용한다" 고 정한다.  acceptance 5개 조건의
값·연산자·threshold 가 모두 후보 단위로 남아 있고(위 표), primary clock 도
case 단위로 존재한다.  없는 3개는 (1) 파생 가능 (2) 판정에 불필요 (3) 축 자체가
부재 — 어느 것도 새 replay 를 정당화하지 않는다.

따라서 `instrumentation_equivalence.csv` 는 **전후 비교 대상이 없음(N/A)** 으로
기록한다.  임의 baseline 을 만들지 않는다.
