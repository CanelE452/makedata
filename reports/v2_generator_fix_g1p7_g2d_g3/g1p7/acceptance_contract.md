# G1.7 §5 — candidate acceptance 계약 (코드에서 직접 확인)

정본은 **코드**다.  이전 보고 문장이나 기억을 쓰지 않았다.

`scripts/data_prep/blender/v2_realize.py:1838-1843` [확인]:

```python
target_error_ok = (
    error <= SP2.EXPLICIT_TARGET_ABS_TOLERANCE
)
candidate_accept = bool(
    side_match
    and int(object_visible_stats["visible_pixels"]) >= 8
    and target_error_ok
    and corner_metrics["joint_pass"]
)
```

`scene_placement_v2.py:69 external_corner_gate_metrics` [확인]:

```python
inframe_values = [v for inside, v in zip(in_frame, occlusion_fractions) if inside]
v_inframe = len(inframe_values)
ext_occ    = sum(v >= threshold for v in inframe_values)   # threshold = 0.5
v_vis      = v_inframe - ext_occ
g1_pass    = v_vis >= 4
g2_pass    = 1 <= ext_occ <= 4
joint_pass = g1_pass and g2_pass
```

## 분류

```
분류                 조건            실제 필드                     연산자        단위
──────────────────────────────────────────────────────────────────────────────────────────
HARD_PHYSICAL       support         reason == 'support'           탈락          -
                    collision       reason == 'collision'         탈락          -
                    camera clearance reason=='camera_clearance'   탈락          -
ACCEPTANCE          side            occluder_side_match           is True       범주형
                    visibility      object_visible_pixels         >= 8          저해상도 px
                    target          abs_error                     <= 0.12       가림분율(무차원)
                    G1              candidate_V_vis               >= 4          코너 개수
                    G2              candidate_ext_occ_corners     1 <= x <= 4   코너 개수
RANKING_ONLY        score           score                         비교 없음     음수 비용
```

## 명시 사항

- **score 는 acceptance threshold 가 아니다.**  ranking 전용이며 어떤 임계와도
  비교되지 않는다.  범위는 `(-inf, 0]`, 높을수록 좋다.  §13 의 Pareto 비교에서도
  constraint vector 가 동률일 때만 tie-break 로 쓴다.
- **visible_pixels 임계 8 은 이름 있는 상수가 아니라 코드의 리터럴** 이다
  (`v2_realize.py:1840`).  단위는 저해상도 holdout 렌더의 픽셀 수다.
- **target 오차는 길이가 아니라 가림 분율** 이다.  `abs_error = |f_explicit_actual
  − f_target|`, 허용오차 `EXPLICIT_TARGET_ABS_TOLERANCE = 0.12`.
- **G1/G2 는 boolean 이 아니라 정수 margin 을 가진다.**  둘 다 같은 코너
  가림분율 배열에서 나온다.  G1 은 "충분히 보이나", G2 는 "의도한 만큼
  가렸나"를 본다.  방향이 반대라서 한쪽을 개선하면 다른 쪽이 나빠질 수 있다.
- **None 은 미측정이며 pass 가 아니다.**  전체 후보 2918 중 732 건(25.1%)은
  hard physical 단계에서 탈락해 acceptance 조건을 하나도 평가받지 못했다.
- **0 의 의미는 조건마다 다르다.**  `visible_pixels=0` 은 전혀 안 보임(실패),
  `ext_occ=0` 은 전혀 안 가림(실패), `target margin=0` 은 정확히 경계(통과).
- hard physical 은 acceptance 의 **선행 관문** 이다.  탈락하면 score_callback
  자체가 호출되지 않으므로 acceptance 조건값이 전부 None 이 된다.
