# §6 — 20-frame exact reproducibility smoke (A vs B)

두 번 **독립 실행**했다. profile `diagnostic-exact`(CPU byte-reproducible path),
seed 7000, n 20, mask `full-audit`, records mode.

```
data/pallet/runs/diagnostics/v2_repro_exact20_a
data/pallet/runs/diagnostics/v2_repro_exact20_b
```

## 결과 — PASS

```
항목                    A vs B    비고
────────────────────────────────────────────────────────────────────
records_total              20     양쪽 동일
rendered_both              18     idx 15 · 18 은 **양쪽 모두** solver 배치 실패
                                  (bounded_local_search_exhausted) — 렌더 실패가
                                  아니라 records mode 의 정상적인 realize_fail
framespec_mismatch          0
plan_mismatch               0
record_mismatch             0     normalized (volatile 필드 제외)
label_mismatch              0     normalized
rgb_mismatch                0     픽셀 내용
mask_mismatch               0     M0~M4 = 90장, 픽셀 내용
────────────────────────────────────────────────────────────────────
all_exact                True
```

## ★ 이미지 동일성은 파일 바이트가 아니라 픽셀로 판정한다

1차 비교에서 mask 가 18/18 불일치로 나왔다. **FAIL 로 보고하지 않고 원인을 규명했다.**

```
PNG IDAT 청크        A·B 전부 동일 (10개 청크 SHA 일치)
numpy array_equal    True
차이는 tEXt 청크뿐
  Date                                  2026/07/31 14:42:38  vs  14:55:46
  RenderTime                            00:00.30             vs  00:00.21
  cycles.ViewLayer.total_time           00:00.26             vs  00:00.18
  cycles.ViewLayer.synchronization_time 00:00.26             vs  00:00.17
```

Blender 가 PNG 에 심는 **wall-clock timestamp 와 렌더 소요시간**이다. §6 이 정규화
제외를 허용한 항목(절대 output path · wall-clock timestamp · per-session elapsed ·
GPU/CPU runtime)과 정확히 일치한다.

따라서 이미지 비교 기준을 **픽셀 내용 SHA256** 으로 정정했다. 이것은 게이트 완화가
아니라 지시가 명시한 정규화다. 파일 바이트 기준 결과도 참고값으로 함께 기록한다:

```
_rgb_filebytes_mismatch_info    0     RGB 는 후처리 후 PIL 재저장이라 Blender
                                      메타데이터가 없어 바이트까지 일치 [추정]
_mask_filebytes_mismatch_info  18     mask 는 Blender 가 직접 쓴 PNG 그대로 [확인]
```

정규화에서 **제외하지 않은 것**: seed · frame index · pose · K · keypoints ·
selected assets · scene mode · post-effect parameter · mask 픽셀 · label geometry.

## 판정

`exact20` 게이트 통과 → §7 의 2,000 usable-frame 렌더를 시작할 수 있다.

산출: `exact20_comparison.csv` (프레임별 전 항목 SHA), `_exact20_summary.json`
