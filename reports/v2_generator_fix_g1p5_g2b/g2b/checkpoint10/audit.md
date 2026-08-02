# G2b checkpoint10 — 첫 10장 게이트 (overlay 포함)

출력 `data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public`
(usable_id 0..9) · seed 7000 · dataset-quality · samples 64 · **mask public** ·
magenta 0.0 · Blender process 1개 · overwrite 없음(신규 디렉토리)

## 1. mode 배분 — PASS

```
mode                     기대   실측
────────────────────────────────────
clean-static                2      2
cargo-only                  2      2
context-rich                3      3
controlled-occlusion        3      3
```

10장 블록 2/2/3/3 위반 0건.

## 2. mode semantics — PASS (10/10)

```
mode                    n  semantics  세부
──────────────────────────────────────────────────────────────────────────────
clean-static            2    2/2      explicit 없음 · cargo 안 보임 · context 안 보임
cargo-only              2    2/2      placed 2/2 · visible px>0 2/2
context-rich            3    3/3      visible>=1 3/3 · ratio>0 3/3
controlled-occlusion    3    3/3      placed 3/3 · visible px>0 3/3
                                 side match 3/3 · **metrics_available 3/3**
```

`explicit_metrics_available` 이 controlled 전건에서 true — §2 가 실제로 동작한다.

## 3. 무결성 — PASS (위반 0)

```
rgb 10 · labels 10 · mask_amodal 10 · mask_visible 10 · overlay 10
usable_id 0..9 연속 True · missing 0 · duplicate 0
corrupt 0 · empty amodal 0 · visible 가 amodal 밖 0
magenta 0 · 거리>10m 0 · annotation invalid 0
gate(all_pass) 실패 0
reprojection max 1.27e-13 px  (gate 1e-04 — PASS)
```

## 4. overlay — PASS (10/10)

```
overlay 생성            10 / 10   실패 0
크기 == 해당 RGB        10 / 10
정보 패널(Pitch/Yaw/Roll) 10 / 10
우하단 축 범례           10 / 10
overlay_ok(셋 다)       10 / 10
해상도 분포             {'640x480': 4, '720x480': 3, '960x540': 2, '560x560': 1}
```

★ 지시서는 "640x480 원본 크기"라고 했지만 이 generator 는 **프레임마다 해상도가
다르다**(aspect 랜덤화). 640x480 으로 고정하면 나머지가 리사이즈되어 같은 문장의
"원본 크기"와 모순되므로, 각 프레임의 **native 해상도**로 만들고 감사 항목을
"overlay 크기 == 그 프레임 RGB 크기"로 바꿨다. 위 표의 `size_matches_rgb` 가 그것이다.

overlay 는 `overlay_archive_trunc_style.draw_archive_style_overlay()` +
`archive_metadata()` 정본 경로만 쓴다(직접 구현 없음). 프레임이 usable 로 확정된 뒤
label/record 로 **후처리** 생성하므로 generator semantics 에 영향이 없다.

출력 위치 2곳:
```
data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public/overlay/
reports/v2_generator_fix_g1p5_g2b/g2b/checkpoint10/overlays/all/
```

## 5. controlled 효율 (표본 3장 — 참고값)

```
                                    구 smoke100 ckpt10   신 smoke100b ckpt10
A usable / 전체 proposal                27.3%                27.3%
C 비싼 reject / attempt                 50.0%                37.5%
runtime reject/accepted                  1.98                 1.14
usable 1장당 실효 wall time            123.2 s              93.2 s
```

controlled 가 3장뿐이라 §12 효율 게이트는 여기서 판정하지 않는다 — 100장에서 한다.

## 6. 판정

§9 가 요구한 조건(mode 2/2/3/3 · semantics · 무결성 · overlay 10/10)을 전부 통과했다
→ 나머지 90장 진행.

산출: `audit.csv` · `audit.md` · `audit_summary.json` · `mode_semantics_audit.csv` ·
`controlled_efficiency.csv` · `controlled_quality.csv` · `runtime_by_stage.csv` ·
`overlays/`(all 10 · contact_*.png 4 · contact_extremes.png · overlay_audit.json ·
overlay_index.csv · extreme_cases.csv)
