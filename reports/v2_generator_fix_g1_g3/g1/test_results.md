# Phase G1 — 테스트 결과

전부 실제 실행. 수치는 명령 출력 그대로다.

## 1. 회귀

```
항목                        수정 전            수정 후            판정
────────────────────────────────────────────────────────────────────────
registry audit             ok=28 missing=0    ok=28 missing=0    PASS
unit (tests/)              802 passed         865 passed         PASS  skip 0 fail 0
local integration          31 passed          31 passed          PASS  skip 0
golden overlay             51 passed          51 passed          PASS  skip 0
5k FrameSpec digest        938f387d           938f387d           불변
5k proposal digest         3cd365ee (4,439)   3cd365ee (4,439)   불변  12/12 checks
```

unit 이 802 -> 865 로 늘어난 것은 아래 신규 테스트 63개 때문이다(회귀 아님).

## 2. 신규·수정 테스트

```
파일                                          내용                              개수
──────────────────────────────────────────────────────────────────────────────────
tests/test_mode_semantics.py (신규)           §3 schedule 8 · cargo 5 ·          33
                                              context 5 · controlled 6 ·
                                              null 3 · gate 통합 4 · public 2
tests/test_controlled_prefilter.py (신규)     recall 2 · determinism 4 ·         21
                                              synthetic 11 · schema 4
tests/test_scene_placement_v2.py (추가)       저앙각 context pose fallback        6
tests/test_v2_pilot_resume_reproducibility    interleave resume                   3
tests/test_usable_completion_mode.py (수정)   픽스처에 mode semantics 필드 추가,
                                              controlled skip 시나리오를 새
                                              schedule 에 맞춤, 고정 record
                                              스키마에 신규 16키 반영
```

## 3. §11 필수 항목 대응

```
#   항목                                      테스트
──────────────────────────────────────────────────────────────────────────────
1   n=10 count 2/2/3/3                        ModeSchedule.test_n10_is_2_2_3_3
2   n=100 count 20/20/30/30                   ModeSchedule.test_n100_counts
3   n=2000 count 400/400/600/600              ModeSchedule.test_n2000_counts
4   first 10 에 네 mode 전부                  test_first_ten_slots_cover_every_mode
5   same n schedule exact                     test_same_n_gives_the_same_schedule
6   records mode 20/500 회귀 없음             test_records_mode_allocation_is_untouched
7   cargo placed 0 -> reject                  CargoSemantics.test_cargo_not_placed_is_rejected
8   placed>0 visible 0 -> reject              test_placed_but_invisible_is_rejected
9   visible>0 -> pass                         test_visible_pixels_gt_zero_passes
10  보이지만 팔레트 안 가림 -> pass           test_visible_cargo_that_does_not_occlude...
11  public pallet mask 로 계산하지 않음       test_pallet_mask_fields_are_not_used_...
12  context requested 0 -> reject             ContextSemantics.test_requested_zero_is_rejected
13  context placed 0 -> reject                test_placed_zero_is_rejected
14  placed>0 visible 0 -> reject              test_placed_but_invisible_is_rejected
15  n_context_visible>=1 -> pass              test_visible_context_passes
16  cargo 만 있고 context 없음 -> reject      test_cargo_cannot_substitute_for_context
17  f_target=0 -> reject                      ControlledSemantics.test_zero_target_is_rejected
18  explicit occluder 없음 -> reject          test_missing_occluder_is_rejected
19  visible pixels 0 -> reject                test_invisible_occluder_is_rejected
20  side mismatch -> reject                   test_side_mismatch_is_rejected
21  정상 controlled -> pass                   test_valid_controlled_passes
22  skip limit 뒤 invalid fallback 금지       test_runner_never_renders_a_zero_target_plan...
23  None 은 unknown/fail                      NullSemantics.test_none_is_unknown_and_never_a_pass
24  0 은 실제 zero                            test_zero_is_a_real_zero_not_unknown
25  False 는 실제 fail                        test_false_is_a_real_failure
26  prefilter deterministic                   Determinism.test_same_candidate_gives_the_same_answer
27  frame/seed blacklist 없음                 test_no_frame_or_seed_blacklist_exists_in_the_rule
28  accepted fixture false negative 0         BaselineRecall.test_no_winner_is_removed (49건)
29  infeasible synthetic reject               SyntheticCandidates 6종
30  feasible synthetic retain                 test_feasible_candidate_is_retained
                                              test_grounded_candidate_at_the_margin_is_retained
31  prefilter reason 안정적                   test_reasons_are_from_the_declared_set
32  solver output schema 회귀 없음            SolverSchemaUnchanged 4종
33  public 은 amodal+visible 만               PublicMaskUnchanged.test_public_profile_writes_only...
34  임시 마스크가 output 에 저장되지 않음      test_cargo_visibility_masks_are_temporary_only
35  visible subset amodal 회귀 없음           기존 test_audit_v2_mask_integrity (무변경 통과)
36  interleave schedule resume 동일           test_interleaved_schedule_survives_a_resume
37  delivered ID 중복 0                       test_delivered_ids_have_no_duplicates
38  proposal replay exact                     기존 ProposalStreamIsReplayable 6종 (무변경 통과)
```

## 4. prefilter baseline recall (실측)

```bash
python scripts/data_prep/blender/audit_v2_controlled_prefilter.py \
    --dir data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_public \
    --seed 7000 --out reports/v2_generator_fix_g1_g3/g1
```

```
accepted frame                49
  winner 보존                 49 / 49      PASS
  prefilter 로 프레임 탈락    0            PASS
expensive reject frame        94
  Blender 진입 전 조기 탈락   12  (12.8%)
후보 pool                     29,725 -> 20,013  (32.7% 제거)
```
