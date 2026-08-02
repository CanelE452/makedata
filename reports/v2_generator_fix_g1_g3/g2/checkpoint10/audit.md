# G2 checkpoint10 — 첫 10장 게이트

출력 `data/pallet/runs/diagnostics/v2_mode_semantics_smoke100_seed7000_public`
(usable_id 0..9) · seed 7000 · dataset-quality · samples 64 · mask **public** ·
magenta 0.0 · Blender process 1개

## 1. mode 배분

```
mode                     기대   실측   판정
──────────────────────────────────────────
clean-static                2      2   PASS
cargo-only                  2      2   PASS
context-rich                3      3   PASS
controlled-occlusion        3      3   PASS
```

10장 블록 2/2/3/3 위반 0건

## 2. mode semantics 전수

```
mode                    n  semantics  세부
──────────────────────────────────────────────────────────────────────────
clean-static            2    2/2      explicit 없음 · cargo 안 보임 · context 안 보임
cargo-only              2    2/2      placed 2/2 · visible px>0 2/2
context-rich            3    3/3      visible>=1 3/3 · ratio>0 3/3
controlled-occlusion    3    3/3      placed 3/3 · visible px>0 3/3 · side match 3/3
```

record 의 `mode_semantics_pass` 와 재계산 결과 불일치 0건.

cargo 가시성은 저해상도 object holdout 으로 직접 측정한 값이다 — public mask 는
팔레트 전용이라 그것으로 추론하지 않았다.

## 3. 무결성

```
rgb 10 · labels 10 · mask_amodal 10 · mask_visible 10      (각 10 기대)
usable_id 0..9 연속 True · missing 0 · duplicate 0
corrupt 0 · empty amodal 0 · visible 가 amodal 밖 0
magenta 0 · 카메라거리>10m 0 · annotation invalid 0
gate(all_pass) 실패 0
reprojection max 1.27e-13 px  (gate 1e-04 — PASS)
```

## 4. controlled 효율 (표본 3장 — 참고값)

```
A usable / 전체 proposal               3/11 = 27.3%
B usable / attempt(mode filter 제외)   3/8 = 37.5%
C 비싼 reject / attempt                4/8 = 50.0%
0초 reject   mode_filter 3 · solve 1 · prefilter 소진 1
runtime      reject 245.6s / accepted 123.9s = 1.98
```

controlled 가 3장뿐이라 §16 효율 게이트는 **여기서 판정하지 않는다** — 100장에서 한다.
prefilter 소진 1건은 Blender 를 열지 않고 0초에 버려진 것으로, 설계대로 동작했다.

## 5. 판정

§13 이 요구한 조건을 전부 통과했다 → 나머지 90장 진행.

산출: `audit_summary.json` · `mode_semantics_audit.csv` · `records_audit.csv` ·
`controlled_efficiency.csv` · `controlled_quality.csv` · `runtime_by_stage.csv` ·
`overlays/all/`(원본 해상도 10장) · `overlays/contact_*.png` ·
`overlays/extreme_cases.csv`
