# A2 — CC-BY Attribution 동봉 계획 (B5)

CC-BY 에셋은 배포물에 **저작자 표기 + 변경 사실**을 동봉해야 함. 이 문서가 그 위치·형식·변경목록을 정의한다.

## 1. 파일 위치 (배포 산출물)
- **`<dataset_root>/ATTRIBUTION.md`** — 릴리스 루트에 사람이 읽는 통합 표기(아래 형식). 필수.
- 정본 per-asset 목록 = `_docs/attribution_cc-by_appendix.md`(16 Sketchfab 인라인 + GSO/배경 포인터) → ATTRIBUTION.md가 이를 흡수.
- per-폴더 `SOURCES.txt`/`LICENSE.txt`(distractors/{tier}/·pallets_v2_add/·background/·hdri/)는 데이터와 함께 이동 → 그대로 동봉.
- (CC0 에셋 = 표기 의무 없음: HDRI 30·Poly Haven distractor 65·wood9·EUR-Pallet·pallet_full.obj. ATTRIBUTION에 "CC0, 표기 불요"로 참고 기재만.)

## 2. 형식 (per CC-BY 에셋)
```
"<title>" by <author>, licensed under CC BY <ver>, <source_url>.
  Modifications: <가한 변경>.
```

## 3. 변경 사실 (Modifications) — CC-BY 명시 의무, 에셋군별
```
에셋군                     라이선스        가한 변경(배포에 명시할 것)
──────────────────────────────────────────────────────────────────────────────────────
USD 팔레트 P0(scene.usd)    CC-BY 4.0       Blender 프로덕션 blend로 import·scale/orient 정규화,
  ·P1(scene_1.usd)          (herisuwardi71   씬 baking. **P0: emissive_strength 10000→0**
  (플라스틱, 유지)           /billy3D)        (scene_noemit.usd 세척본). 렌더 파이프라인 합성.
J-Toastie (신규 목재)       CC-BY 3.0        비-metric→실치수 uniform-scale, upright·접지 정규화,
                            (J-Toastie)      glb 재추출.
배경 glTF ×2               CC-BY 4.0        Blender import, scale/placement 조정, 배경으로 렌더 합성.
  industrial·parking_lot    (BazukaliKartal
                            /Veterock)
GSO distractor ×32(+확장)   CC-BY 4.0        upright·metric·접지 정규화, (일부) glb/obj 재익스포트.
  (Google Research)
Sketchfab distractor ×16    CC-BY 4.0        upright Z-up·실치수 uniform-scale·접지 정규화, glb 재추출.
```
- EUR-Pallet(CC0)·Scan탈락은 표기 불요.
- floor/wood 텍스처 변경(UV·tint 조정)은 A1(B4) 출처 확정 후 해당 라이선스가 CC-BY로 밝혀지면 여기 추가.

## 4. 미결
- A1(floor 14) 확정 후 CC-BY 텍스처 있으면 3절에 추가.
- 실제 `ATTRIBUTION.md` 생성은 **배포 패키징 시**(v2 빌드 후). 이 계획이 그 근거.
