# §2 cargo-only 전수 감사 — usable_id 400..799 (400장)

## ★ 이전 감사 정정

이전 보고서는 "실제 가림 발생 326장(81.5%)"이라고 적었다. **그 수치는 틀렸다.**
public mask 는 **pallet 전용**이라 `visible_fraction < 1` 은 "무언가 가렸다"만 말하지
그것이 cargo 인지 알려주지 않는다. 지시가 명시적으로 금지한 추론이다.

이번에는 generator 가 직접 기록한 **cargo 전용 지표**를 썼다:

```
front_visibility_after_cargo · left_opening_visibility_after_cargo ·
right_opening_visibility_after_cargo      (< 1 이면 cargo 가 그 면을 가렸다)
```

## 결과

```
assigned cargo-only            400
diagnostic_mode 불일치           0
cargo_on = true                400 / 400   (100%)
cargo placed                   349         (87.2%)
★ cargo 가 실제로 팔레트를 가림   15         (3.8%)     ← 정정된 수치
no-cargo frame                  51         (12.8%)
no-cargo ids                   402·414·416·420·429·431·445·450 …

attempts       median 42   p95 106   max 117
실패 프레임만   median 50             max 114
runtime        median 6.5  p95 10.7  max 14.8 초

시도 563 = usable 400 + reject 163
수율 71.0%  (95% Wilson 67.2~74.6%)
reject 사유  G1 69 · d_occ_fail 27 · v_below_min 19 · C1 17 · G5 16
```

## 판독

1. **cargo 배치 실패 12.8%** — 50회 이상 시도하고도 못 놓는다.
2. **더 심각한 것: 배치에 성공한 349장 중에서도 팔레트를 실제로 가리는 것은 15장뿐**
   (전체의 3.8%). 즉 cargo 는 대개 팔레트 **위에** 놓이되 카메라 시선에서 팔레트를
   가리지 않는 위치에 놓인다.
3. 따라서 `cargo-only` 모드는 "적재물이 있는 팔레트"는 만들지만 **"적재물에 의한
   가림"은 거의 만들지 못한다.** f_cargo 를 측정하려는 설계 의도와 어긋난다.

실패 예시 RGB: `cargo_failure_examples/` (8장)
전수 데이터: `cargo_full_audit.csv`
