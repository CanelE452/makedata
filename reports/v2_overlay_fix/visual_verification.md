# archive-style overlay — 시각 + 픽셀 검증 (Section 5 / Section 7)

날짜: 2026-07-28
대상: `data/pallet/archive/trunc_addon_v1_pilot/overlay` (정본 12장) vs
`data/pallet/_v2_smoke50_9d/overlay_archive_style` (Blender 없이 재생성한 50장 중 12장)

재현:
```
python scripts/data_prep/blender/overlay_v2_detailed.py \
    --dir data/pallet/_v2_smoke50_9d --out data/pallet/_v2_smoke50_9d \
    --overlay-dirname overlay_archive_style --sheet-dirname contact_sheets_archive_style \
    --style archive
python scripts/data_prep/blender/_verify_archive_style_pixels.py
python scripts/data_prep/blender/_make_archive_vs_new_sheet.py
```

---

## 1. 검증 방법

12개 항목 전부를 눈이 아니라 **픽셀 값 + 해당 프레임의 label**로 판정했다
(`scripts/data_prep/blender/_verify_archive_style_pixels.py`). 판정 기준은 완성된 오버레이를
`overlay_archive_trunc_style`의 **참조 레이어**(같은 keypoint로 그린 edge 레이어 / edge+dot 레이어)와
비교하는 것이다. 아카이브가 나중에 그리는 요소가 앞 요소를 덮는 것은 정상이므로 다음만 허용한다.

- dot(r=6)이 edge를 덮음 (먼 팔레트는 12개 edge가 전부 dot 안에 들어간다)
- pose axes / id label / panel / legend 가 dot·edge를 덮음
- 위 요소의 **안티에일리어싱 혼합색** (예: X축 글자가 X edge 위에 있으면 (255,64,64) 같은 중간색)
- 1 px 래스터화 편차 (아카이브 JSON의 projected_cuboid는 소수 2자리 반올림이라 대각선이 1 px 밀린다)

"단순히 없음" 또는 "다른 색"은 절대 통과하지 않는다. **판정 기준의 타당성은 아카이브 정본 12장이
같은 기준으로 12/12 통과한다는 것으로 확인**했다 (기준이 느슨해서 통과한 게 아니라, 기준이
아카이브의 실제 그리기 순서를 반영한다는 뜻).

## 2. archive reference 12장 — 12항목 PASS/FAIL

확인한 파일 (Read 도구로 12장 전부 직접 열어봄):
`data/pallet/archive/trunc_addon_v1_pilot/overlay/{000000,000001,000002,000003,000004,000005,000006,000007,000009,000011,000016,000061}.png`

```
항목                                 PASS/12   비고
────────────────────────────────────────────────────────────────────────────
X edge red      (255,80,80)          12/12
Y edge green    (80,220,80)          12/12
Z edge blue     (80,130,255)         12/12   000002/5/6/9/16은 dot에 완전히 가려짐(정상)
keypoint 0~8 distinct colors         12/12
centroid white  (255,255,255)        12/12
pose X/Y/Z axes visible              12/12
top-left in-image info panel         12/12   (6,6)~(181,246) 흑색, AA 흰 글자
bottom-right axis legend             12/12   swatch 3개 정확히 일치
no external panel                    12/12   캔버스 = RGB (640x480)
no full-width audit header           12/12
keypoints lie on cuboid projection   12/12   label의 projected_cuboid 좌표와 dot 중심 일치
output size equals RGB size          12/12
```

커버한 조건: 근접(0.82m) / 원거리(13.7m) / 저앙각(0.8°) / 고앙각(56.3°) / truncation(V=4~7) /
cargo(3개) / occluder / 실내(warehouse·hangar·autoshop) / 실외(parking_lot·construction_yard).
야간은 아카이브 파일럿 300장에 존재하지 않으므로(9종 HDRI 전부 주간) 커버 불가.

## 3. 신규 v2 archive-style 12장 — 12항목 PASS/FAIL

확인한 파일 (Read 도구로 12장 전부 직접 열어봄):
`data/pallet/_v2_smoke50_9d/overlay_archive_style/{f0000,f0002,f0007,f0008,f0010,f0012,f0014,f0022,f0024,f0031,f0040,f0049}.png`

```
항목                                 PASS/12   비고
────────────────────────────────────────────────────────────────────────────
X edge red      (255,80,80)          12/12
Y edge green    (80,220,80)          12/12
Z edge blue     (80,130,255)         12/12   f0008/12/24/31은 dot에 완전히 가려짐(정상)
keypoint 0~8 distinct colors         12/12
centroid white  (255,255,255)        12/12   f0022는 centroid가 panel 밑 → panel이 덮음(정상)
pose X/Y/Z axes visible              12/12
top-left in-image info panel         12/12
bottom-right axis legend             12/12
no external panel                    12/12
no full-width audit header           12/12
keypoints lie on cuboid projection   12/12
output size equals RGB size          12/12
```

커버한 조건: 근접(0.82m) / 원거리(8.75m) / 저앙각(1.9°) / 고앙각(60.3°) / truncation(V=4~7) /
cargo(1~2개) / explicit occluder(f0040·f0049) / context distractor(f0024·f0031) /
indoor·outdoor-day·outdoor-night·random-mix 전부 포함.

## 4. 픽셀 샘플링으로 확인한 상수 일치

24장(정본 12 + 신규 12) 전부에서 아래가 **정확히** 일치한다.

```
대상                       기대값                          결과
──────────────────────────────────────────────────────────────────────
panel 좌상단 (6,6)         (0,0,0)                         24/24 일치
panel 우하단 (181,246)     (0,0,0)                         24/24 일치
legend X swatch            (255,60,60)  @ (W-91, H-59)     24/24 일치
legend Y swatch            (60,220,60)  @ (W-91, H-44)     24/24 일치
legend Z swatch            (80,130,255) @ (W-91, H-29)     24/24 일치
canvas                     == RGB 크기                     24/24 일치
```

추가로 legend 박스(91x61) 전체를 정본과 **픽셀 단위 diff**한 결과 **차이 0 px**
(신규 코드로 다시 그린 legend를 `archive/.../overlay/000000.png`와 비교).
이 골든 비교는 회귀 테스트로 고정했다:
`tests/test_overlay_archive_trunc_style.py::TestLegend::test_legend_is_pixel_identical_to_the_archive`.

## 5. FAIL이었던 것 — 폰트 (원인·조치)

첫 실행에서 **정본 12장 전부가 "top-left in-image info panel"에서 FAIL**했다. 조사 결과 판정
스크립트가 아니라 복원 코드 쪽 버그였다.

- 증상: 정본 panel에는 순백(255,255,255) 픽셀이 **0개**, 글자 코어가 240 근처(안티에일리어싱).
  재생성본은 순백 5630 px (비트맵 폰트, AA 없음).
- 원인: `overlay_archive_trunc_style._archive_bitmap_font()`가 PIL 고전 6x11 비트맵 폰트를
  강제하고 있었다. 실제 아카이브는 `drw.text(font=None)`으로 그려졌고, 그 시점 Pillow(>=10.1)에서
  그것은 **AA TrueType 페이스**였다.
- 증거: 고정 내용인 legend 박스를 다시 그려 정본과 diff — `load_default()`는 **0 px 차이**,
  비트맵 폰트는 **482 px 차이**. panel 첫 줄만 비교해도 비트맵은 442 px 차이.
- 조치: `_archive_bitmap_font()` → `_archive_font()`(`ImageFont.load_default()`)로 교체하고
  전 오버레이 재생성. 잘못된 가정을 고정하고 있던 테스트 3개를 수정하고
  (`test_uses_the_classic_bitmap_font` → `test_uses_the_font_the_archive_was_drawn_with`,
  순백 매칭 → AA ink 임계값), 정본과의 골든 diff 테스트를 새로 추가했다.
- 결과: `pytest scripts/data_prep/blender/tests/ -q` → **443 passed**.

그 외 FAIL은 모두 판정 스크립트 쪽 과잉 엄격함이었고(위 1절의 허용 규칙 부재), 아카이브 정본도
동일하게 FAIL시키는 것으로 확인 후 기준을 고쳤다. 최종 상태에서 정본·신규 모두 12/12.

## 6. 비교 시트

`reports/v2_overlay_fix/archive_reference_vs_new.png` (1310x3098, 6쌍, 양쪽 모두 **원본 크기로**
붙임 — 리사이즈하면 panel/legend 크기 비교가 무의미해지므로).

```
조건              왼쪽(정본)          오른쪽(신규)
──────────────────────────────────────────────────
near / truncated  archive 000004      new f0002
far               archive 000005      new f0008
low elevation     archive 000001      new f0000
high elevation    archive 000061      new f0007
cargo             archive 000009      new f0010
occluder          archive 000011      new f0040
```
