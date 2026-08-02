# 합성 데이터 에셋 저작권 요약 (검토용)

Pallet 6D Pose — Geometry-aware Self-Training / 합성 데이터 생성 파이프라인
작성 2026-08-02 · 근거 정본: [`_docs/dataset_license_ledger.md`](dataset_license_ledger.md)

---

## 결론

**현재 생성 파이프라인이 사용하는 에셋은 전부 CC0 / CC-BY / 자체 제작이다.**
비-CC(NoAI, Standard) 에셋은 파이프라인에서 제거·격리되었고, NVIDIA EULA 에셋은 미사용이다.

- **CC0** (표기 의무 없음): HDRI 30, distractor 65, floor 텍스처 14, wood 텍스처 9, 팔레트 2종
- **CC-BY** (저작자 표시 필수): distractor 144, 배경 2, 팔레트 3종 — **데이터셋 공개 시 `ATTRIBUTION.md` 동봉 필요**
- **자체 제작**: 팔레트 photogrammetry 모델 1, 실촬영 이미지 1,924장
- **미사용·격리**: NoAI 팔레트 2종, 비-CC 배경 1종, NVIDIA Isaac Sim 에셋

---

## 0. 전체 요약 (한 장)

| 구분 | 에셋 | 종수 | 저작자 / 출처 | 라이선스 | 표기의무 | 출처 URL |
|---|---|---|---|---|---|---|
| **팔레트** | pallet_full.obj | 1 | 본인 (photogrammetry) | 자체 IP | — | — |
| | pallet 2606 (P0) | 1 | herisuwardi71 / Sketchfab | CC-BY 4.0 | 필수 | [링크](https://sketchfab.com/3d-models/pallet-2606-9fc3dca70fdb466e87602d3721d1075a) |
| | Plastic Pallet (P1) | 1 | billy3D / Sketchfab | CC-BY 4.0 | 필수 | [링크](https://sketchfab.com/3d-models/plastic-pallet-0699da1b0dd04c13b5c6731c8dda75d1) |
| | Pallet (stringer) | 1 | Quaternius / Poly Pizza | **CC0 1.0** | 불요 | [링크](https://poly.pizza/m/cUAsYHDqfD) |
| | Wooden Pallet | 1 | J-Toastie / Poly Pizza | CC-BY 3.0 | 필수 | [링크](https://poly.pizza/m/XSKlcrzyi6) |
| | EUR-Pallet | 1 | LensError / BlenderKit | **CC0 1.0** | 불요 | [링크](https://www.blenderkit.com/asset-gallery-detail/751202c6-5da7-4085-9da0-0550cce6dc9c/) |
| **Distractor** | Google Scanned Objects | 128 | Google Research / Gazebo Fuel | CC-BY 4.0 | 필수 | `app.gazebosim.org/GoogleResearch/fuel/models/<name>` |
| | Poly Haven props | 65 | (개별) / Poly Haven | **CC0 1.0** | 불요 | `polyhaven.com/a/<name>` |
| | Sketchfab props | 16 | (개별, 부록 참조) | CC-BY 4.0 | 필수 | `sketchfab.com/3d-models/<slug>` |
| **배경** | Modular Buildings (Industrial Area) | 1 | BazukaliKartal / Sketchfab | CC-BY 4.0 | 필수 | [링크](https://sketchfab.com/3d-models/modular-buildings-industrial-area-ef3bbb072d81405fae3e954ed3522d49) |
| | Parking lot | 1 | Veterock / Sketchfab | CC-BY 4.0 | 필수 | [링크](https://sketchfab.com/3d-models/parking-lot-80e54d8326ea4646949961e8ada35518) |
| **조명** | HDRI (주간 21 + 야간 9) | 30 | (개별) / Poly Haven | **CC0 1.0** | 불요 | `polyhaven.com/a/<asset_id>` |
| **텍스처** | 바닥 floor | 14 | (개별) / Poly Haven | **CC0 1.0** | 불요 | `polyhaven.com/a/<slug>` |
| | 목재 wood | 9 | (개별) / Poly Haven | **CC0 1.0** | 불요 | `polyhaven.com/a/<slug>` |
| **실촬영** | RealSense D435i | 1,924장 | 본인 | 자체 IP | — | — |
| **코드** | FoundationPose / DOPE | — | NVIDIA | NVIDIA Source Code License | 라이선스 동봉 | 비상업 한정 |
| **렌더러** | Blender | — | Blender Foundation | GNU GPL | — | 산출물에 전파 없음 |

**라이선스 집계** (3D 모델 + HDRI + 텍스처)

| 라이선스 | 종수 | 내역 |
|---|---|---|
| **CC0 1.0** (표기 불요) | **120** | Poly Haven distractor 65 + HDRI 30 + floor 14 + wood 9 + 팔레트 2 |
| **CC-BY** (표기 필수) | **149** | GSO 128 + Sketchfab distractor 16 + 배경 2 + 팔레트 3 |
| 자체 IP | 1 + 1,924장 | pallet_full.obj + 실촬영 |
| 비-CC | **0** | (NoAI·Standard·EULA 에셋은 전부 미사용·격리 — §8) |

---

## 1. 3D 모델 — 팔레트

| 에셋 | 제목 | 저작자 | 출처 | 라이선스 | URL |
|---|---|---|---|---|---|
| `pallet_full.obj` | — | 본인 | 자체 photogrammetry | 자체 IP | — |
| P0 `scene.usd` (빨강 플라스틱) | pallet 2606 | herisuwardi71 | Sketchfab | CC-BY 4.0 | https://sketchfab.com/3d-models/pallet-2606-9fc3dca70fdb466e87602d3721d1075a |
| P1 `scene_1.usd` (초록 플라스틱) | Plastic Pallet | billy3D | Sketchfab | CC-BY 4.0 | https://sketchfab.com/3d-models/plastic-pallet-0699da1b0dd04c13b5c6731c8dda75d1 |
| `stringer_2way` | Pallet | Quaternius | Poly Pizza | **CC0 1.0** | https://poly.pizza/m/cUAsYHDqfD |
| `woodpallet_block` | Wooden Pallet | J-Toastie | Poly Pizza | **CC-BY 3.0** | https://poly.pizza/m/XSKlcrzyi6 |
| `eur_pallet` | EUR-Pallet | LensError | BlenderKit | **CC0 1.0** | https://www.blenderkit.com/asset-gallery-detail/751202c6-5da7-4085-9da0-0550cce6dc9c/ |

근거: `data/pallet/assets/pallets/source/pallets_v2_add/LICENSE.txt` (게이트 명시 — *"only CC0 / CC-BY accepted. NC / ND / SA / Standard / NoAI excluded"*) · P0/P1은 아래 역검색 결과

**P0/P1 원출처 확정 방법** (2026-08-02, Sketchfab API 역검색)

내부 기록에 다운로드 이력이 없어(history는 USD 확보 3주 후부터 시작), 사전 감사에서 확인된 4개 후보 모델의 **실측 폴리곤 수**를 API로 조회해 우리 USD 파일 크기와 대조했습니다.

| Sketchfab 모델 | 저작자 | faces | 라이선스 | 대응 슬롯 | USD 크기 |
|---|---|---|---|---|---|
| pallet 2606 | herisuwardi71 | **426,540** | CC-BY | **P0** | **20.9 MB** |
| Plastic Pallet | billy3D | 4,392 | CC-BY | **P1** | 0.33 MB |
| Old Wooden Pallet | Luka Feric | 3,024 | Free Standard (NoAI) | 미사용·격리 | 0.17 / 0.57 MB |
| Pallet | andree (maestronoov) | 2,160 | CC-BY | 미사용·격리 | (동상) |

P0는 4모델 중 **유일한 고폴리(426k faces, 나머지는 전부 5k 미만)**이고, 우리 USD 중에서도 **P0만 유일하게 20.9MB**(나머지는 0.6MB 이하)입니다. 썸네일 형상도 카탈로그 렌더의 P0와 일치합니다.

> 근거 강도: **강한 정황**입니다. Sketchfab 모델 다운로드에는 로그인이 필요해 바이트/지오메트리 동일성까지는 확인하지 않았습니다.

## 2. 3D 모델 — Distractor / 방해물 (209종)

| 출처 | 종수 | 저작자 | 라이선스 | URL 형식 |
|---|---|---|---|---|
| Google Scanned Objects | **128** | Google Research | CC-BY 4.0 | `https://app.gazebosim.org/GoogleResearch/fuel/models/<name>` |
| Poly Haven | **65** | (개별) | **CC0 1.0** | `https://polyhaven.com/a/<name>` |
| Sketchfab | **16** | (개별, 부록 참조) | CC-BY 4.0 | `https://sketchfab.com/3d-models/<slug>` |

전체 목록(개별 URL·저작자 209행): `data/pallet/assets/distractors/library/distractors_manifest.csv`
GSO 인용: Laursen et al., *Google Scanned Objects: A High-Quality Dataset of 3D Scanned Household Items*, ICRA 2022

## 3. 배경 씬 (2종)

| 에셋 | 저작자 | 라이선스 | URL |
|---|---|---|---|
| Modular Buildings (Industrial Area) | BazukaliKartal | CC-BY 4.0 | https://sketchfab.com/3d-models/modular-buildings-industrial-area-ef3bbb072d81405fae3e954ed3522d49 |
| Parking lot | Veterock | CC-BY 4.0 | https://sketchfab.com/3d-models/parking-lot-80e54d8326ea4646949961e8ada35518 |

라이선스 원문: 각 폴더의 `license.txt` — *"Author must be credited. Commercial use is allowed."*

## 4. 조명 (HDRI 30종)

| 항목 | 내용 |
|---|---|
| 출처 | Poly Haven — https://polyhaven.com |
| 라이선스 | **CC0 1.0 Universal** — https://polyhaven.com/license |
| 권리 | *"copy, modify, distribute and use the work, even for commercial purposes… No attribution is required."* |
| 구성 | 주간 21 + 야간/저조도 9 (2k, Radiance RGBE) |
| 전체 목록 | `data/pallet/assets/lighting/hdri/library/SOURCES.txt` (30종 asset_id·URL·저작자) |

예: `https://polyhaven.com/a/dresden_station_night` (Greg Zaal) · `https://polyhaven.com/a/unfinished_office_night` (Sergej Majboroda)

## 5. 텍스처

| 그룹 | 종수 | 출처 | 라이선스 | 검증 |
|---|---|---|---|---|
| 바닥(floor) | 14 | Poly Haven | **CC0 1.0** | ✅ 14/14 CONFIRMED — Poly Haven API `info/<slug>` 조회로 전수 확인 |
| 목재(wood) | 9 | Poly Haven | **CC0 1.0** | ✅ 9/9 CONFIRMED — 동일 방법으로 전수 확인 (2026-08-02) |

근거: 각 폴더의 `{LICENSE.txt, SOURCES.txt}` — `assets/materials/floor/textures_floor/` · `assets/materials/pallet/textures_wood/`
검증 기준: `https://api.polyhaven.com/info/<slug>` 가 HTTP 200 + human-readable name 일치 + `type:1`(texture) → CONFIRMED CC0 (Poly Haven은 사이트 전체가 CC0)

**wood 9종 개별 출처** (파일명 = Poly Haven slug)

| 텍스처 | 저작자 | URL |
|---|---|---|
| brown_planks_03 | Rob Tuytel | https://polyhaven.com/a/brown_planks_03 |
| brown_planks_04 | Rob Tuytel | https://polyhaven.com/a/brown_planks_04 |
| dark_planks | Rob Tuytel | https://polyhaven.com/a/dark_planks |
| plank_flooring_03 | Jenelle van Heerden, Matterfield | https://polyhaven.com/a/plank_flooring_03 |
| weathered_brown_planks | Dimitrios Savva, Rico Cilliers | https://polyhaven.com/a/weathered_brown_planks |
| weathered_planks | Dario Barresi, Dimitrios Savva | https://polyhaven.com/a/weathered_planks |
| wood_planks | Amal Kumar | https://polyhaven.com/a/wood_planks |
| wood_planks_grey | Rob Tuytel | https://polyhaven.com/a/wood_planks_grey |
| worn_planks | Dimitrios Savva | https://polyhaven.com/a/worn_planks |

## 6. 실촬영 데이터

| 항목 | 내용 |
|---|---|
| 구성 | RealSense D435i 촬영 1,924장 (`data/pallet/reference/real_images/real_data/`) |
| 권리 | 자체 촬영 = 자체 IP |
| 용도 | self-training unlabeled 풀 |

## 7. 소프트웨어 / 코드

| 대상 | 라이선스 | 제약 |
|---|---|---|
| FoundationPose (리포 루트) | NVIDIA Source Code License | **§3.3 비상업(연구·평가) 한정** |
| Deep_Object_Pose (DOPE) | NVIDIA Source Code License | 동일 |
| Blender (렌더러) | GNU GPL | 렌더 산출물에는 라이선스 전파 없음 |

---

## 8. 미사용 · 격리 항목 (배포·학습에서 제외)

| 대상 | 사유 | 조치 |
|---|---|---|
| 목재 팔레트 2종 "Old Wooden Pallet" (Luka Feric) | Sketchfab **Free Standard + NoAI** — AI 학습 데이터셋 사용 금지 | 파이프라인에서 제거, `archive/_noai_quarantine_usd/`로 격리(보관만) |
| 배경 `modern_city_block` | Sketchfab **Standard**(비-CC) | 제거 |
| `isaac_assets/` (NVIDIA Isaac Sim 창고 USD) | **NVIDIA EULA** — 재배포 불가 | 미사용, 배포 트리에서 제외 |
| 구 데이터셋 8종 (v4 / v4_split / 4pallet_mask 계열) | 위 NoAI 팔레트가 이미 렌더에 포함됨 | 격리 + 배포 제외, **v2 재생성 예정** |

구 데이터셋 판정 근거: 라벨 JSON **13,122 프레임 전수 스캔**(표본 아님) — 4개 파생 데이터셋에서 NoAI 팔레트 사용 프레임 63.3~100%
배포 차단 검증: `scripts/data_prep/verify_distribution_exclusions.py` (현재 leaks 0)

---

## 9. 공개 시 필요한 조치

| # | 항목 | 상태 |
|---|---|---|
| 1 | CC-BY 에셋 통합 `ATTRIBUTION.md` 동봉 (distractor 144 + 배경 2 + 팔레트 3) | 미생성 — 배포 패키징 시 작성 |
| 2 | `isaac_assets/` 배포 트리 제외 | 제외 목록 등재 완료, 패키징 시 적용 |
| 3 | 구 데이터셋 v2 재생성 | 예정 |
| 4 | 격리된 목재 USD 2종의 원본 판별 (Blender 정점수 대조: 1,568 vs 1,120) | 미실시 — 판별 시 CC-BY 쪽은 격리 해제 가능 |
| ~~5~~ | ~~wood 텍스처 LICENSE 파일 생성~~ | ✅ 완료 (2026-08-02, 9/9 CONFIRMED CC0) |
| ~~6~~ | ~~P0/P1 원출처 URL 확정~~ | ✅ 완료 (2026-08-02, Sketchfab API 역검색) |

> **현 단계(생성·학습)에서는 위반 사항 없음.** CC-BY 표시 의무는 배포 시점에 발생한다.

---

### 부록: CC-BY Sketchfab distractor 16종 개별 출처

| 에셋 | 제목 | 저작자 | URL |
|---|---|---|---|
| forklift_01 | Forklift | fdgasd7 | https://sketchfab.com/3d-models/forklift-bdb03db7036e436286f4e2fd34c02a89 |
| forklift_02 | Forklift | mansta9 | https://sketchfab.com/3d-models/forklift-d40cae50e04145dd997cdca415cd72ad |
| cargo_truck_01 | Isuzu Cargo Base Truck | VuckyZ123 | https://sketchfab.com/3d-models/isuzu-cargo-base-truck-6f5765ef13294287b5d14df4ba64d5bf |
| delivery_truck_01 | DELIVERY TRUCK | jasmin.daniel | https://sketchfab.com/3d-models/delivery-truck-1d53f7fa474849db812102dfa5d070d0 |
| delivery_van_01 | European Delivery Van | evan.hiltz | https://sketchfab.com/3d-models/european-delivery-van-0b2f1ad95a79419f9a092420024d329c |
| hand_truck_01 | Industrial hand truck | ittoKubashi7 | https://sketchfab.com/3d-models/industrial-hand-truck-a7b424b174ba456f9d84624c1835a2f5 |
| hand_truck_scan_02 | Quixel Megascans Metal Hand Truck | Guay0 | https://sketchfab.com/3d-models/3d-scan-quixel-megascans-metal-hand-truck-df28fe2186a3417090b912d63daca2b4 |
| storage_rack_01 | Storage Rack | andersta | https://sketchfab.com/3d-models/storage-rack-f990c9d601bd480798d12fd5a60dcb5a |
| no_parking_sign_01 | No Parking Sign | polygroun | https://sketchfab.com/3d-models/no-parking-sign-3e6e0c4e68794d0d852a28be2f30c766 |
| construction_sign_01 | construction sign | SweetLemons | https://sketchfab.com/3d-models/construction-sign-7f84fa84c2064de496a68e2cab2acf51 |
| water_dispenser_01 | Brio Water Dispenser | dana.digital | https://sketchfab.com/3d-models/brio-water-dispenser-818b5e12dd3c47c4939e5b4c9c45b6a5 |
| hard_hat_01 | Safety Helmet | muradyanhovo1117 | https://sketchfab.com/3d-models/safety-helmet-f9c17905f17a45d885442ebace25a66f |
| hard_hat_02 | Hard Hat3 | kristiyan | https://sketchfab.com/3d-models/hard-hat3-cc19391032eb4ff7872b274df375801e |
| bollard_01 | Bollard | MaX3Dd | https://sketchfab.com/3d-models/bollard-aa382530c7624927a782547def4c85cb |
| construction_barrier_01 | construction site barrier | lwse | https://sketchfab.com/3d-models/construction-site-barrier-3917d39740eb4c008924a08c273412d1 |
| traffic_barricade_01 | Traffic Barrier | chamindu918 | https://sketchfab.com/3d-models/traffic-barrier-53fb77ce2c9248319d8913f3526cd047 |

표기 형식: `"<title>" by <author>, licensed under CC BY 4.0, via Sketchfab (<url>).`

**CC-BY §3(b) 변경 고지**: 접지 정규화(min-z→0) · XY 중심 정규화 · 일부 glb/obj 재익스포트 · MTL 텍스처 경로 재bind. 원본 지오메트리/텍스처 콘텐츠는 불변.
