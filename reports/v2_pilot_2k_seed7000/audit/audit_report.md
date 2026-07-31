# v2 pilot (public, seed 7000) — 중단 후 전수 감사

중단 시점 usable **1,449** (id 0..1448 연속). cooperative interrupt 로 정지,
`taskkill /F` 미사용, 부분 파일 0건.

```
mode 구성 (실측)
  clean-static           400 / 400   완료
  cargo-only             400 / 400   완료
  context-rich           600 / 600   완료
  controlled-occlusion    49 / 600   중단 (표본)
```

## A. cargo-only — 400장 전수

```
물체 배치 성공        349 / 400   (87.2%)
배치 실패              51         (12.8%)   ids 402·414·416·420·429·431·445·450 …
실제 가림 발생        326         (81.5%)
runtime               median 6.5  p95 10.7  max 14.8 초   합계 2,756 초
실패 프레임 배치 시도  median 50   max 114
시도 563 = usable 400 + reject 163    수율 71.0%  (95% Wilson 67.2~74.6%)
reject runtime        합계 656 초 (median 5.7, max 12.7)
reject 사유           G1 69 · d_occ_fail 27 · v_below_min 19 · C1 17 · G5 16
```

**cargo-only 라벨인데 cargo 가 없는 프레임이 51장(12.8%)** 이다. 50회 이상 시도하고도
배치에 실패했는데 usable gate 에는 "그 모드의 물체가 실제로 놓였는가" 조건이 없어 통과했다.

## B. context-rich — 600장 전수

```
물체 배치 성공        561 / 600   (93.5%)
배치 실패              39         (6.5%)    ids 811·817·827·841·845·859·893·902 …
실제 가림 발생        324         (54.0%)   ← 배치돼도 절반은 팔레트를 가리지 않는다
runtime               median 13.5  p95 32.2  max 71.0 초   합계 9,680 초
실패 프레임 배치 시도  median 0   max 0      ← 시도조차 하지 않았다
시도 861 = usable 600 + reject 261    수율 69.7%  (95% Wilson 66.5~72.7%)
reject runtime        합계 2,996 초 (median 14.4, max 102.5)
reject 사유           G1 94 · G5 39 · d_occ_fail 34 · C1 34 · v_below_min 31
```

실패 39장은 `context_placement_attempts = 0` — 재시도 끝에 실패한 게 아니라 **애초에
배치를 시도하지 않았다**. cargo-only 의 실패(50회 시도 후 실패)와 원인이 다르다.

## C. controlled-occlusion — 49장 전수 (표본)

```
물체 배치 성공         49 / 49    (100.0%)   ← 기능 자체는 정상 동작
실제 가림 발생         49 / 49    (100.0%)
visible_fraction      median 0.770   p05 0.549   p95 0.959
f_target median 0.183  vs  f_total(actual) median 0.230
occluder side         right 18 · left 16 · bottom 15   (균등)
occluder asset        utility_box 15 · water_dispenser 13 · chinese_screen 8 ·
                      Shelf 5 · construction_sign 2 …

★ 시도 276 = usable 49 + reject 227     수율 17.8%  (95% Wilson 13.7~22.7%)
runtime (usable)      median 44.0  p95 85.5  max 111.6 초   합계 2,445 초
runtime (reject)      median 48.4              max 127.7 초   합계 5,147 초
reject 사유
  proposal_skip:mode_requires_explicit_occluder    96   (solve 단계 — 싸다)
  usable_reject:...realize_occluder...             94   ★ 렌더까지 하고 버림 — 비싸다
  solve_reject:C1 15 · d_occ_fail 11 · v_below_min 7
```

**usable 49장을 얻는 데 reject 로만 5,147초(1.43시간)를 썼다** — usable 자체(2,445초)의
2.1배다. 비싼 쪽(렌더 후 reject) 94건이 병목이다.

## D. 데이터 무결성 — 1,449장 전수

```
usable id 0..1448 연속     True     missing 0     duplicate 0
파일 수                    rgb 1449 · labels 1449 · mask_amodal 1449 · mask_visible 1449
                           전부 N 과 일치        True
visible ⊆ amodal 위반      0
corrupt file               0
annotation invalid         0
reprojection               median 8.04e-14   p95 1.61e-13   max 1.46e-11 px
                           serialization gate 1e-4 통과      True
incomplete attempts 격리   0 건 (프레임 경계에서 멈춰 부분 파일이 생기지 않았다)
```

**데이터 자체는 완전하다.** record · label · mask · RGB 가 서로 일치하고 손상이 없다.

## 판정

```
PILOT_SUFFICIENT_FIX_GENERATOR = true
```

근거:

1. **controlled-occlusion 기능은 동작한다** — 배치 100%, 가림 100%, side·asset 분포 균등.
2. **그러나 수율이 17.8%(95% CI 13.7~22.7%)** 이고, reject 의 41%(94/227)가 렌더까지
   마친 뒤 버려진다. 남은 551장에 약 44시간이 필요하다 — 실측 기반.
3. **cargo/context 의 mode-content 불일치가 확정됐다** — cargo-only 12.8%, context-rich
   6.5% 가 해당 물체 없이 그 모드 라벨을 달고 있다. gate 에 조건이 없다.
4. 데이터 무결성은 문제없으므로, 지금까지의 1,449장은 **generator 수정 후 비교 기준**으로
   쓸 수 있다.

현재 설정으로 2,000장을 마저 채워도 위 세 결론은 바뀌지 않는다.

## 이번 단계에서 하지 않은 것

generator 수정 0 · 재렌더 0 · sampler/gate 변경 0 · commit 0 · push 0.

산출: `audit_summary.json` · `audit_frames.csv`(A·B·C 1,049행 — clean-static 400장은
지시된 감사 대상이 아니라 제외. D 무결성은 1,449장 전수)
