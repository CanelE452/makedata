# §3 context-rich 전수 감사 — usable_id 800..1399 (600장)

근거 지표(mask 추론 아님): `n_context_visible` · `context_visible_pixel_ratio` ·
`context_screen_area_ratio` · `context_reject_counts_by_reason`

## 결과

```
assigned context-rich          600
diagnostic_mode 불일치           0
context placed                 561         (93.5%)
★ context 실제로 보임            561         (93.5%)   ← 배치되면 항상 보인다
context absent                  39         (6.5%)
absent ids                     811·817·827·841·845·859·893·902 …
그중 cargo 가 대신 있는 프레임     13         (811·841·845·859·938·1004 …)

attempts       median 12   p95 188   max 215
실패 프레임만   median 0              max 0      ← 시도조차 하지 않았다
runtime        median 13.5 p95 32.2  max 71.0 초

시도 861 = usable 600 + reject 261
수율 69.7%  (95% Wilson 66.5~72.7%)
```

## context solver 내부 reject 사유 (누적 시도 횟수)

```
support             14,840      ← 지지면을 못 찾는 게 압도적
collision            3,145
occlusion_budget     1,977
camera_clearance       418
```

## 판독

1. **배치되면 100% 보인다** (561/561). cargo 와 대조적으로 context 는 화면에 잘 들어간다.
2. **absent 39장의 원인이 cargo 와 다르다** — `context_placement_attempts = 0` 이다.
   재시도 끝에 실패한 게 아니라 **애초에 시도하지 않았다**. 그중 13장은 cargo 가 대신
   놓여 있어, 모드 배정과 실제 장면 구성이 어긋난다.
3. 배치 비용의 주범은 **support 실패 14,840회** — 지지면 탐색이 runtime median 13.5초의
   대부분을 설명한다(p95 32.2초, max 71.0초).

실패 예시 RGB: `context_failure_examples/` (8장)
전수 데이터: `context_full_audit.csv`
