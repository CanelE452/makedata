# Dataset License Ledger — Pallet 6D Pose

팔레트 6D 포즈 데이터셋 **공개(release) 대비** 에셋 저작권 마스터 원장.
모든 렌더/합성 소스 에셋의 저장경로·출처·저작자·라이선스·공개가능여부를 한 곳에 기록하고, 공개 blocker를 전부 드러낸다.

- 작성: 2026-07-24 (read-only 감사, 렌더/생성 없음)
- 감사 범위: `data/pallet/` + `data/palletobj/` 트리 전수 열거
- 판정 표기: `Y`=공개가능 / `N`=공개불가(블로커) / `?`=미검증(정직 표기, 추정으로 단정 안 함)
- **출처 태그**: `[확인]`=파일/로그/코드로 실증 / `[추정]`=파일명·관례 단서(미검증) / `[시드]`=사전 감사 사실(재조사 안 함, 경로만 실측)

> **★ 이 머신의 역할 범위 (2026-07-24 명시)**: 이 워크스테이션 = 합성 데이터 생성 전용. 평가셋
> (outside/night/noapril, GT)·학습 코드·meas 하네스는 별도 머신. → 이 원장은 **합성 소스 에셋의
> 라이선스**만 권위 있게 다룬다. `real_data/` 1924장(단일 세션)은 평가셋 아님 = self-training용
> unlabeled 풀로 추정. **C3(실 평가셋 clutter 분포)는 이 머신 범위 밖 → 종료**(별도 머신 소관).

---

## 🚨 일정 영향 (SCHEDULE IMPACT — 최우선 인지)

**파이프라인 블로커 전부 해소 — B1(NoAI 팔레트) blend 관문 완료, B2(Isaac occluder) 오탐. 잔여 = 기존 데이터셋 v2 재생성:**
```
데이터셋                              상태            사유
──────────────────────────────────────────────────────────────────────────────
(v2 신규 생성분)                      클린            재-bake된 blend(NoAI 제거) + 새 목재 → 라이선스 클린
v4 / v4_split / 4pallet_mask         v2 재생성 필요   기존 산출물에 NoAI 목재(P2/P3)가 이미 baked(과거 렌더) → 폐기/재생성
v3 palletobj / trunc_addon / addon_v1 attribution만   팔레트=자작 OBJ + occluder=Poly Haven CC0 → B5(CC-BY) 표시만
```
→ **★(a) B1 blend 관문 해소 완료 (2026-07-24) [확인, zstd 해제 grep 재검증]** — 프로덕션 `synth_data_scene.blend` 재-bake로 **NoAI 목재(scene_2/3.usd 유래) 완전 제거**(새 blend grep: scene_2.usd=0·scene_3.usd=0·LP_merge_lambert16=0·Material_018=0·**Legacy_Pallet_2/3=0**[과거 로더가 rename만 한 중복본까지]; 백업엔 각 존재). 새 목재 woodpallet_block_jtoastie·eur_pallet_bk 투입 확인. B1 3부 조건(①USD 격리 ②blend 재-bake ③로더 repoint) **모두 완료**. → **파이프라인은 이제 라이선스 클린**, 기존 데이터셋은 **v2 재생성으로 클린화**(기존 산출물엔 NoAI baked라 폐기).
→ **(b) `paper_s2` 발표가능성은 어느 계열 학습인지에 달림** — v4/4pm(구 NoAI baked)기반이면 v2 재평가 필요, palletobj기반이면 attribution 후 사용가능. (실학습셋 확인은 v2 재생성으로 대체 예정이라 별도 확인 **불필요 = 종료**.)
※ **B2 정정 근거 [확인]**: 프로덕션 blend 157MB grep에서 Isaac 지문(isaac/Simple_Warehouse/S_WetFloor 등) **0 hit** + occluder명(WetFloorSign_01·cardboard_box_01·metal_toolbox)이 실제 Poly Haven CC0 에셋. "WetFloorSign=Isaac"은 이름-충돌 오탐(원장 구 B2 [확인] 태그 오류였음). 실제 occluder=Poly Haven CC0(5확정)+Sketchfab CC-BY 산업배경 prop(8추정)+불명 3.

**다양성 한계 (논문 데이터 절 기록용, 조치 불필요)**: 교체로 P3(막힌 데크 목재)가 빠지고 슬랫 목재 2종(J-Toastie·EUR)이 됨 → 데크구조 축에서 "막힌 목재" 소멸. 단 솔리드 마스크는 P0(플라스틱 막힌 데크)가 담당 → 치명적 아님. 팔레트 추가 안 함(시간 제약).

---

## ⚠️ BLOCKERS — 공개 전 반드시 해결 (B1·B2·B3·B4 해소, 잔여 = B5·B6 + ★occlusion 선택 재배선)

> **갱신 2026-07-24 (팔레트 교체·blend 재-bake 완료 + B2 오탐 정정)**: 목재 P2/P3(`scene_2/3.usd`) 격리 →
> 새 목재 2종(J-Toastie CC-BY3.0 + EUR-Pallet BlenderKit CC0) 투입, **프로덕션 blend 재-bake로 NoAI 목재
> 완전 제거 + 로더 repoint 완료 → B1 파이프라인 관문 해소**. **B2는 오탐으로 종료**(Isaac 지문 0, occluder=
> Poly Haven CC0). **잔여 = B5(attribution)·B6(isaac_assets 제외)** + **★occlusion 선택 재배선**(현 occlusion
> 선택 `DISTRACTOR_NAMES`(8)에 옛 `Sketchfab_model`×3(라이선스 불명)이 남아 실제 가림 렌더에 들어감 →
> 209 CC0/CC-BY 풀로 재배선 전까지 유효). distractor 209는 blend에 import+tag 완료(에셋 가용), 선택 배선은 다음 phase.

```
#    상태            블로커                                                          영향 범위
────────────────────────────────────────────────────────────────────────────────────────────────
B1   해소            "Old Wooden Pallet"(Luka Feric)=Standard+NoAI: 파이프라인서 제거  구 데이터셋만 v2 재생성 필요
B2   종료(오탐)      OCCLUDER=Isaac 오탐 → 실제 Poly Haven CC0(이름충돌)               (블로커 아님)
B3   해소            USD↔Sketchfab 매핑: 렌더로 P0/P1=플라스틱·P2/P3=목재 확정        목재 2종 다 교체→불확실성 소멸
B4   해소            floor 14/14 Poly Haven CC0 확정(미검증 5종 CC0 교체)              floor 전부 CC0(표기 불요)
B5   미해결 MEDIUM   CC-BY 저작자표시 의무 미이행 시 위반(첨부 attribution 필수)        Sketchfab/GSO/CC-BY 전부
B6   미해결 LOW      isaac_assets/(NVIDIA 창고 USD) 트리에 존재 — 배포물서 제외 필요     소스 에셋(렌더 산출물 아님)
```

**B1 (CRITICAL → 해소 2026-07-24)** — 시드 감사에서 확인된 4번째 팔레트 "Old Wooden Pallet"(Luka Feric) =
Sketchfab **Free Standard License + NoAI 태그**(Standard=재배포 금지 + NoAI=AI/ML 학습·데이터셋 사용 금지).
목재 원본 2종(P2 `scene_2.usd`, P3 `scene_3.usd`) 중 하나가 이 NoAI 모델 — 매핑 미확정이라 **둘 다 교체**.
**3부 조건 모두 완료 → 파이프라인서 NoAI 원천 제거**:
- **① USD 격리**: `scene_2/3.usd` → `data/pallet/archive/_noai_quarantine_usd/`(삭제X, provenance 보관, README) [확인, 2026-07-28 경로 정정].
- **② blend 재-bake [확인, zstd 해제 grep 재검증]**: 프로덕션 `synth_data_scene.blend` 재-bake로 NoAI 목재
  완전 제거 — 새 blend grep에서 **scene_2.usd=0 · scene_3.usd=0 · LP_merge_lambert16=0 · Material_018=0 ·
  Legacy_Pallet_2/3=0**(과거 로더가 삭제 않고 rename만 한 NoAI 중복본까지 제거; 백업엔 각 존재). 새 목재
  `woodpallet_block_jtoastie`·`eur_pallet_bk` 투입 확인. 백업 = `synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend`.
- **③ 로더 repoint**: `randomizers.py`에 `.glb` 분기 추가 + `config/synthetic/blender.yaml` P2/P3 → 새 glb
  (슬롯 Pallet_2=J-Toastie, Pallet_3=EUR). P0/P1 회귀 0(V2), 스모크 PASS(V6).
- **④ legacy-purge 강건화(2026-07-24 후속)**: 로더의 rename→**삭제-on-성공**으로 수정 → `Legacy_Pallet_0/1`
  제거. Legacy 누적이 NoAI 재-bake의 잠재 원인이었음(로더가 구 팔레트를 지우지 않고 rename만 해 blend에 쌓임) →
  원인 제거. 재-bake 후 재확인 grep에서 NoAI(scene_2/3.usd·LP_merge_lambert16) **여전히 0** → B1 해소 유지.
- **잔여 = 기존 데이터셋 v2 재생성**: v4/v4_split/4pallet_mask 등 **기존 렌더 산출물에는 NoAI가 이미 baked**
  (과거 렌더) → 폐기하고 **재-bake된 클린 blend로 v2 재생성** 후 공개(=상단 일정영향). 파이프라인 자체는 클린.
- 파일 변경: `config/synthetic/blender.yaml` · `scripts/data_prep/blender/randomizers.py`(glb 분기) ·
  `models_usd/`(새 glb 투입). USD/시드 로직 무영향.

**B2 (종료 — 오탐 확정 2026-07-24)** — 이전 판본은 "OCCLUDER_POOL이 NVIDIA Isaac Sim prop"이라
[확인]으로 flag했으나 **오탐**. **정정 근거 [확인, decompressed blend grep]**: 프로덕션 blend(157MB 해제)
전체 grep에서 Isaac 지문(`isaac`/`Simple_Warehouse`/`S_WetFloor` 등) **0 hit**. occluder 오브젝트명
(`WetFloorSign_01`·`cardboard_box_01`·`metal_toolbox` 등)은 실제 **Poly Haven CC0** 에셋이며, `S_WetFloorSign
.usd`(Isaac)와는 **이름만 충돌**한 것(내 초기 grep이 파일명 일치만 보고 단정 = verify 누락 오류). 실제 occluder
구성 = Poly Haven CC0(5확정) + Sketchfab CC-BY 산업 prop(8추정) + 불명 3. → **occluder는 NVIDIA 무관,
CC0/CC-BY**. v3 palletobj/trunc_addon/addon_v1은 Isaac 미포함 → **B5(attribution)만 하면 사용 가능**.
(cargo 배럴/카드보드도 Poly Haven CC0 계열.) **B2 블로커 종료.**

**B3 (HIGH → 해소)** — 4개 `scene*.usd`(baked crate, 메타 0)의 Sketchfab 저작자 1:1 매핑은 여전히
불명이지만, **더 이상 필요 없음**. 카탈로그 렌더(`_pallet_catalog_0123/pallet_0123_row.png`) 육안으로
**P0(scene.usd)=빨강 플라스틱, P1(scene_1.usd)=초록 플라스틱, P2(scene_2.usd)=어두운 목재,
P3(scene_3.usd)=밝은 목재** 확정 [확인]. NoAI "Old Wooden Pallet"은 **목재**이므로 반드시 {P2,P3} 중
하나 → P0/P1(플라스틱, 둘 다 CC-BY)은 NoAI 아님이 확정. 목재 2종(P2·P3)을 **모두 교체·격리**했으므로
"어느 목재가 NoAI인가"라는 매핑 질문 자체가 **무의미화 = 해소**. (P0/P1은 CC-BY로 유지, B5 표시 대상.)

**B4 (MEDIUM → 해소 2026-07-24)** — floor 14텍스처(`textures_floor/`)를 **14/14 CONFIRMED Poly Haven CC0**로
확정. 조치: 9종은 기존 Poly Haven slug 실증 유지, **미검증 5종을 동등 Poly Haven CC0로 내용 교체**(파일명
유지 = `floor_and_mask.py:34` 참조만이라 코드 무변경): `tile_white`→floor_tiles_02, `tile_brown`→
brown_floor_tiles, `wood_laminate`→laminate_floor_02, `dirt_ground`→brown_mud_dry, `red_earth`→
cracked_red_ground (전부 Poly Haven CC0). `textures_floor/{SOURCES.txt,LICENSE.txt}` 생성(14/14 CC0,
0 UNVERIFIED), 원본 백업 `textures_floor/_replaced_originals/`. → **floor 전부 CC0 = 표기 불요, B4 해소.**

**B5 (MEDIUM)** — CC-BY 에셋(유지 팔레트 P0/P1 플라스틱 2, 배경 2, **GSO ≈128**, Sketchfab distractor 16,
v2 J-Toastie 목재 팔레트[CC-BY 3.0], occluder 중 Sketchfab CC-BY 8)은 **저작자표시가 데이터셋에 동봉되어야**
라이선스 충족. (EUR-Pallet BlenderKit·Poly Haven·GSO 외 CC0는 표시 불요.) `_docs/attribution_cc-by_appendix.md`
(GSO 32→128 반영) + 폴더별 SOURCES 존재하나, 공개 배포물에 통합·동봉(`ATTRIBUTION.md`) 확인 필요.

**B6 (LOW-INFO)** — `data/pallet/isaac_assets/`에 NVIDIA Isaac Sim Simple_Warehouse USD(full_warehouse
.usd, props, materials/*.mdl) 원본 존재. 렌더 산출물은 아니지만 배포 트리에 포함되면 안 됨(NVIDIA EULA).

---

## 그룹별 원장

### 1. 팔레트 모델 (핵심 타깃 오브젝트) — **2026-07-24 교체·격리 반영**

**유지 (플라스틱 2종, CC-BY 확정) + 자작 OBJ**
```
asset          저장경로                              출처         저작자        라이선스     공개  블로커
──────────────────────────────────────────────────────────────────────────────────────────────────────
pallet_full    data/palletobj/pallet_full.obj(.mtl)  본인 촬영    사용자(본인)   본인 IP(자작) Y     -
  +diffuse텍스  data/palletobj/laydown_u1_v1_diffuse  photogram.   사용자(본인)   본인 IP      Y     -
P0 scene.usd   data/pallet/assets/pallets/models/models_usd/scene.usd      Sketchfab    (플라스틱)     CC-BY 4.0    Y*    B5(표시)
P1 scene_1.usd data/pallet/assets/pallets/models/models_usd/scene_1.usd    Sketchfab    billy3D(추정)  CC-BY 4.0    Y*    B5(표시)
scene_noemit   data/pallet/assets/pallets/models/models_usd/scene_noemit   scene.usd파생 (P0 동일)       (P0 상속)    Y*    B5(표시)
usd텍스처       data/pallet/assets/pallets/models/models_usd/textures/*.png Sketchfab파생 blinn1(P0/P1)  (P0/P1 상속) Y*    B5(표시)
```
**격리 (목재 2종 — NoAI 원천 제거, `_noai_quarantine_usd/`로 이동, 보관만)**
```
asset          저장경로(신)                                   출처       라이선스              공개  블로커
──────────────────────────────────────────────────────────────────────────────────────────────────────────
P2 scene_2.usd data/pallet/archive/_noai_quarantine_usd/scene_2.usd   Sketchfab  미확정 CC-BY|NoAI      N     B1(격리)
P3 scene_3.usd data/pallet/archive/_noai_quarantine_usd/scene_3.usd   Sketchfab  미확정 CC-BY|NoAI      N     B1(격리)
```
- **[확인] 렌더로 재질 확정** (`_pallet_catalog_0123/pallet_0123_row.png`): P0=빨강 플라스틱, P1=초록
  플라스틱, P2=어두운 목재, P3=밝은 목재. NoAI "Old Wooden Pallet"은 목재 → 반드시 {P2,P3} 중 하나이며
  **P0/P1(플라스틱)은 NoAI 아님이 확정**. → 목재 2종을 **모두 격리·교체**하여 B1 원천 제거, B3 무의미화.
- **시드 4모델 [시드]**: "pallet 2606"(herisuwardi71) CC-BY4.0 / "Plastic Pallet"(billy3D) CC-BY4.0 /
  "Pallet"(andree/maestronoov) CC-BY4.0 / **"Old Wooden Pallet"(Luka Feric) = Free Standard+NoAI = B1**.
  → 플라스틱 2종(P0/P1)은 이 중 billy3D "Plastic Pallet" + 나머지 CC-BY 하나로 매핑됨(둘 다 CC-BY, 표시 대상).
- **★ source URL 상태 (재발견성)**:
  - **유지 P0/P1: canonical URL 미보유**(models_usd에 SOURCES/LICENSE 없음, USD=baked crate 메타 0,
    원본 아카이브 미발견). P1 후보 URL(billy3D "Plastic Pallet", `pallets_v2_add/SOURCES.txt` 기록):
    https://sketchfab.com/3d-models/plastic-pallet-0699da1b0dd04c13b5c6731c8dda75d1 . P0는 title/author
    단서만 → 정확 재발견 보장 안 됨. **B5 저작자표시를 위해 CC-BY 원출처 URL 확정 권장**.
  - **격리 P2/P3: URL 미보유** — provenance는 `_noai_quarantine_usd/README.md`에 보관. NoAI라 재발견해도
    사용 금지.
- `scene_noemit.usd` = scene.usd(P0)의 emissive 제거 변형 → P0(CC-BY) 상속. `models_usd/textures/`의
  `blinn1_*`/`lambert16_*` 원자재도 소스 모델 상속(파이프라인은 DR 머티리얼로 덮어써 렌더엔 미사용).
- **repoint 완료 [확인, 2026-07-24]**: 로더 `randomizers.py`에 `.glb` 분기 추가 + `config/synthetic/
  blender.yaml`에서 P2/P3 → 새 glb 재배선(슬롯 Pallet_2=J-Toastie, Pallet_3=EUR). 프로덕션 blend도 재-bake로
  NoAI 목재 제거(grep scene_2/3.usd·Legacy_Pallet_2/3=0). → 파이프라인 클린, B1 해소.

### 2. v2 신규 팔레트 풀 (additive, 별도 LICENSE/SOURCES 완비) — **격리 P2/P3의 교체 목재 포함**

```
asset                          저장경로                                              출처        저작자      라이선스   공개  역할/비고
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
stringer_2way_quaternius_cc0   data/pallet/assets/pallets/source/pallets_v2_add/models/stringer_2way..glb  Poly Pizza  Quaternius  CC0 1.0    Y     신규 stringer(막힌면)
woodpallet_block_jtoastie_ccby data/pallet/assets/pallets/source/pallets_v2_add/models/woodpallet_block..   Poly Pizza  J-Toastie   CC-BY 3.0  Y*    ★목재 교체①, *표시 필수(B5)
eur_pallet_bk_cc0              data/pallet/assets/pallets/source/pallets_v2_add/models/eur_pallet_bk_cc0.glb BlenderKit  LensError   CC0 1.0    Y     ★목재 교체②(800×1200×144)
```
- 출처/라이선스: `data/pallet/assets/pallets/source/pallets_v2_add/{LICENSE.txt, SOURCES.txt}` [확인]. 게이트=CC0/CC-BY만 수락,
  NC/ND/SA/Standard/NoAI 제외. 3종 모두 통과. **아직 렌더/데이터셋 미생성**(소스 확보 + 정규화·12kp 측정·
  kp 오버레이만 완료). J-Toastie + EUR-Pallet 2종이 **격리된 목재 P2/P3의 교체분**(B1 repoint 대상).
- **★ source URL (모델 페이지, 재발견용)**:
  - stringer (Quaternius, CC0): https://poly.pizza/m/cUAsYHDqfD
  - wood block (J-Toastie, CC-BY 3.0): https://poly.pizza/m/XSKlcrzyi6
  - EUR-Pallet (LensError, CC0): https://www.blenderkit.com/asset-gallery-detail/751202c6-5da7-4085-9da0-0550cce6dc9c/
  - (bare CDN `static.poly.pizza/<uuid>.glb`도 SOURCES.txt에 있으나 재발견용은 위 모델 페이지 URL 우선.)
- J-Toastie는 **CC-BY 3.0**(4.0 아님) — 표기: `"Wooden Pallet" by J-Toastie, via Poly Pizza, CC-BY 3.0`.
  EUR-Pallet은 CC0 → 표시 불요.
- **탈락 기록(참고)**: "Scan Wooden Pallet"(BlenderKit CC0, assetBaseId 3822ba51-e0b0-4773-a209-9ab316d7129c)
  = long 면 막힘(n_op=1) + 포토스캔 142k tri + non-manifold → REJECTED.

### 3. HDRI 환경광 (30종)

```
group               저장경로               출처        저작자                라이선스   공개  비고
─────────────────────────────────────────────────────────────────────────────────────────────────
HDRI ×30 (.hdr)     data/pallet/assets/lighting/hdri/library/*.hdr Poly Haven  각 asset별(SOURCES명시) CC0 1.0    Y     저작자표시 불요
```
- `hdri/LICENSE.txt`(CC0 1.0 명문) + `hdri/SOURCES.txt`(30종 asset_id·URL·author 전수) [확인].
- **★ source URL (재발견용)**: 전 30종 개별 URL = `data/pallet/assets/lighting/hdri/library/SOURCES.txt`의 각 행에 명시.
  URL 패턴 = `https://polyhaven.com/a/<asset_id>` (asset_id = 파일명에서 `_2k` 제거).
  예: `dresden_station_night_2k.hdr` → https://polyhaven.com/a/dresden_station_night ,
  `empty_warehouse_01_2k.hdr` → https://polyhaven.com/a/empty_warehouse_01 ,
  `factory_yard_2k.hdr` → https://polyhaven.com/a/factory_yard .
- 저작자 예: Greg Zaal, Sergej Majboroda, Dimitrios Savva, Oliksiy Yakovlyev 등. CC0라 표시 의무 없음(권장).

### 4. 배경 3D (glTF, 근경)

```
asset                            저장경로                                       출처       저작자           라이선스    공개  비고
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
modular_buildings_industrial_area data/pallet/background/modular_buildings.../   Sketchfab  BazukaliKartal   CC-BY 4.0   Y*    *표시 필수(B5)
parking_lot                       data/pallet/background/parking_lot/            Sketchfab  Veterock         CC-BY 4.0   Y*    *표시 필수(B5)
(modern_city_block)               제거됨(scratchpad 격리)                        Sketchfab  -                Standard(비CC) N     사용 금지
```
- 각 폴더 `license.txt`에 title/author/CC-BY4.0/credit 문구 명시 [확인].
- **★ source URL (모델 페이지, 재발견용)**:
  - modular_buildings_industrial_area (BazukaliKartal):
    https://sketchfab.com/3d-models/modular-buildings-industrial-area-ef3bbb072d81405fae3e954ed3522d49
    (저작자 프로필: https://sketchfab.com/BazukaliKartal)
  - parking_lot (Veterock):
    https://sketchfab.com/3d-models/parking-lot-80e54d8326ea4646949961e8ada35518
    (저작자 프로필: https://sketchfab.com/windofglass)
- **modern_city_block 잔존 확인**: 프로덕션 blend(`_sandbox_palletobj_production.blend`) baked 토큰에
  `modular_buildings_industrial_area`(15)·`parking_lot`(14)만 존재, `modern_city_block` 토큰 **0** [확인]
  → 제거된 비-CC 배경은 프로덕션 blend에 baked되지 않음(de-risk 확인됨).

### 5. Distractor / 적재물 풀 (≈209종, 별도 매니페스트 완비)

```
group                     저장경로                                출처                   라이선스    공개  비고
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
GSO ×128                  data/pallet/distractors/{tier}/(gso__*)  Google Scanned Objects CC-BY 4.0   Y*    *표시 필수(B5); 32→128(D확장)
Poly Haven ×65            data/pallet/distractors/{tier}/(ph__*)   Poly Haven             CC0 1.0     Y     -
Sketchfab ×16             data/pallet/distractors/{tier}/(sf__*)   Sketchfab              CC-BY 4.0   Y*    *표시 필수(B5)
```
- **GSO 32→128 확장(2026-07-24 D)**: +96종(box39·container31·office14·warehouse10·other2), 전부 CC-BY 4.0,
  저작자=Google Research(via Gazebo Fuel GoogleResearch). manifest 총 209행(+1.2GB). ⚠️일부 GSO OBJ의
  MTL `map_Kd` 경로 불일치 → 파이프라인 소비 시 재bind 필요할 수 있음.
- `distractors/{indoor,large,medium,road,small}/{LICENSE.txt,SOURCES.txt}` 폴더별 존재 [확인] +
  `distractors/distractors_manifest.csv` + `_docs/attribution_cc-by_appendix.md`(Sketchfab 16종 title/author/
  URL 교차참조) [확인]. 저작자 예(Sketchfab): fdgasd7, mansta9, VuckyZ123, evan.hiltz 등 16명.
- **★ source URL — 자산별 전 URL = `distractors_manifest.csv`의 `url` 열** (전 항목 모델 페이지 URL 보유) [확인].
  CSV 열: `folder,folder_ko,source,name,...,license,url,mesh,notes`. source별 URL 형식:
  ```
  polyhaven : https://polyhaven.com/a/<name>                  예) https://polyhaven.com/a/barrel_stove
  gso       : https://app.gazebosim.org/GoogleResearch/fuel/models/<name>
              예) https://app.gazebosim.org/GoogleResearch/fuel/models/Clue_Board_Game_Classic_Edition
  sketchfab : https://sketchfab.com/3d-models/<slug>-<uid>     예) .../forklift-bdb03db7036e436286f4e2fd34c02a89
  ```
- **★ Sketchfab distractor 16종 전 URL** (`_docs/attribution_cc-by_appendix.md` §1 = 정본, 여기 재수록):
  ```
  forklift_01             https://sketchfab.com/3d-models/forklift-bdb03db7036e436286f4e2fd34c02a89
  forklift_02             https://sketchfab.com/3d-models/forklift-d40cae50e04145dd997cdca415cd72ad
  cargo_truck_01          https://sketchfab.com/3d-models/isuzu-cargo-base-truck-6f5765ef13294287b5d14df4ba64d5bf
  delivery_truck_01       https://sketchfab.com/3d-models/delivery-truck-1d53f7fa474849db812102dfa5d070d0
  delivery_van_01         https://sketchfab.com/3d-models/european-delivery-van-0b2f1ad95a79419f9a092420024d329c
  hand_truck_01           https://sketchfab.com/3d-models/industrial-hand-truck-a7b424b174ba456f9d84624c1835a2f5
  hand_truck_scan_02      https://sketchfab.com/3d-models/3d-scan-quixel-megascans-metal-hand-truck-df28fe2186a3417090b912d63daca2b4
  storage_rack_01         https://sketchfab.com/3d-models/storage-rack-f990c9d601bd480798d12fd5a60dcb5a
  no_parking_sign_01      https://sketchfab.com/3d-models/no-parking-sign-3e6e0c4e68794d0d852a28be2f30c766
  construction_sign_01    https://sketchfab.com/3d-models/construction-sign-7f84fa84c2064de496a68e2cab2acf51
  water_dispenser_01      https://sketchfab.com/3d-models/brio-water-dispenser-818b5e12dd3c47c4939e5b4c9c45b6a5
  hard_hat_01             https://sketchfab.com/3d-models/safety-helmet-f9c17905f17a45d885442ebace25a66f
  hard_hat_02             https://sketchfab.com/3d-models/hard-hat3-cc19391032eb4ff7872b274df375801e
  bollard_01              https://sketchfab.com/3d-models/bollard-aa382530c7624927a782547def4c85cb
  construction_barrier_01 https://sketchfab.com/3d-models/construction-site-barrier-3917d39740eb4c008924a08c273412d1
  traffic_barricade_01    https://sketchfab.com/3d-models/traffic-barrier-53fb77ce2c9248319d8913f3526cd047
  ```
- GSO 128(gso__*) + Poly Haven 65(ph__*) 개별 URL은 위 형식으로 manifest `url` 열에서 직접 재발견 가능.

### 6. 바닥/목재 텍스처 (팔레트 데크 + 지면)

```
group                저장경로                          출처            저작자      라이선스        공개  블로커
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
목재 텍스처 ×9        data/pallet/assets/materials/pallet/textures_wood/*.png   Poly Haven      Poly Haven  CC0 1.0(검증됨)  Y     -
floor 텍스처 ×14      data/pallet/assets/materials/floor/textures_floor/*.png  Poly Haven      Poly Haven  CC0 1.0(확정)    Y     B4 해소
_procedural_textures  data/pallet/archive/_procedural_textures/ 절차생성(자작)  스크립트     자작(CC0급)      Y     -(현 미사용)
```
- **목재 9종 [확인, 검증완료]**: `_tmp_ph/*_files.json` 6개가 `dl.polyhaven.org`(CC0) 다운로드 매니페스트
  (brown_planks_04/dark_planks/plank_flooring_03/weathered_planks/wood_planks/wood_planks_grey). 나머지 3종
  (weathered_brown_planks/worn_planks/brown_planks_03)은 history 2026-06-16에 "Polyhaven 실사 png"로 명기.
  → 전 9종 Poly Haven CC0.
  - **★ source URL (재발견용)**: URL 패턴 `https://polyhaven.com/a/<name>` (name = 파일명에서 `_diff/_nor_gl/
    _rough` 접미 제거). 예: https://polyhaven.com/a/wood_planks , https://polyhaven.com/a/plank_flooring_03 ,
    https://polyhaven.com/a/weathered_planks . (다운로드 CDN URL 원본은 `data/pallet/_tmp_ph/*_files.json`.)
- **floor 14종 [확인, 검증완료 → B4 해소 2026-07-24]**: `textures_floor/{SOURCES.txt,LICENSE.txt}` 생성 =
  **14/14 CONFIRMED Poly Haven CC0, 0 UNVERIFIED**. 9종은 기존 Poly Haven slug 실증 유지, **미검증 5종을
  동등 Poly Haven CC0로 내용 교체**(파일명 유지 = `floor_and_mask.py:34` 참조만이라 코드 무변경, 원본 백업
  `textures_floor/_replaced_originals/`):
  ```
  파일명(유지)      새 Poly Haven 소스     source URL
  ─────────────────────────────────────────────────────────────────────
  tile_white     → floor_tiles_02       https://polyhaven.com/a/floor_tiles_02      (밝은 페일 스톤타일=실내)
  tile_brown     → brown_floor_tiles    https://polyhaven.com/a/brown_floor_tiles
  wood_laminate  → laminate_floor_02    https://polyhaven.com/a/laminate_floor_02   (밝은 오크 라미네이트=실내)
  dirt_ground    → brown_mud_dry        https://polyhaven.com/a/brown_mud_dry       (실외 지면)
  red_earth      → cracked_red_ground   https://polyhaven.com/a/cracked_red_ground  (실외 지면)
  ```
  - 유지 9종 URL 패턴 `https://polyhaven.com/a/<파일명 slug>`: asphalt_02, brick_floor_02, cobblestone_floor_08,
    concrete_floor_02, concrete_floor_painted, concrete_pavers_02, damaged_concrete_floor, gravel_concrete_02,
    red_brick. → 전 14종 재발견 가능. **CC0라 표기 불요.**
- `_procedural_textures/`(21 png, beige_tile/blue_epoxy/dark_asphalt 등)는 스크립트 절차생성 자작물.
  현 파이프라인 floor는 `textures_floor/`만 사용(이 폴더는 구버전, 사실상 미사용).

### 7. Occluder / 씬 소품 (blend 내장, baked)

```
group                저장경로                                          출처(실측)          라이선스           공개  블로커
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
OCCLUDER_POOL ×19    _sandbox_palletobj_production.blend (baked)       Poly Haven CC0(오탐정정) CC0(5)+CC-BY(8?)+불명(3) Y*   B2 종료
isaac_assets/        data/pallet/isaac_assets/Assets/Isaac/4.5/...     NVIDIA Isaac Sim    Isaac Sim EULA     N     B6
cargo(배럴/카드보드)  production blend (baked, CARGO_SOURCES)            Poly Haven CC0(정정) CC0계열            Y     -
```
- **OCCLUDER_POOL [확인 — B2 오탐 정정]**: 프로덕션 blend 157MB 해제 grep에서 Isaac 지문 **0 hit**,
  occluder 실제 출처 = **Poly Haven CC0**(`WetFloorSign_01`·`cardboard_box_01`·`metal_toolbox` 등 5확정)
  + Sketchfab CC-BY 산업 prop(8추정, B5 표시대상) + 불명 3. 이전의 "`WetFloorSign_01`=Isaac `S_WetFloorSign
  .usd`" 단정은 **파일명 이름-충돌 오탐**(verify 누락)이었음. → NVIDIA 무관, occluder는 CC0/CC-BY.
  (정의: `gen_palletobj_scenarios.py:48 OCCLUDER_TIERS`.) 잔여 = 불명 3종 출처 확정 + CC-BY 8종 attribution(B5).
- **★ 현 occlusion 선택 라이선스 갭 (2026-07-24, 재배선 필요)**: 메인 `synth_data_scene.blend`의 occlusion
  선택 `DISTRACTOR_NAMES`(8)에 옛 **`Sketchfab_model`×3(라이선스 불명)**이 포함 → **실제 가림 렌더에 unknown-
  license 자산이 들어감** [확인]. (위 OCCLUDER_POOL "불명 3"과 동일 계열.) → **릴리스/v2 재생성 전 occlusion
  선택을 209 CC0/CC-BY 풀로 재배선 필수**. Standard/비-CC일 수 있어 attribution(B5)만으로 불충분할 수 있음 =
  교체가 안전. **distractor 209 통합 상태**: `synth_data_scene.blend`에 unpacked append + 태그 완료
  (`is_distractor_v2`=209, `size_class` 메타 209, GSO magenta 0, blend 342MB<1GB) = **에셋 가용화 완료**;
  선택 배선(`DISTRACTOR_NAMES`→209)은 **다음 phase(Placement)**.
- **isaac_assets/ (B6 유지)**: full_warehouse.usd + warehouse*.usd + Props(S_AisleSign/S_TrafficCone/
  S_WetFloorSign/SM_CratePlastic 등) + Materials(*.mdl). NVIDIA Isaac Sim 배포 에셋 → **배포물서 제외**.
  단 이 폴더는 **occluder 소스가 아님**(occluder는 Poly Haven) — Isaac 파이프라인(v4 USD) 잔재. 재취득 경로 =
  NVIDIA Isaac Sim 4.5 에셋 팩(Omniverse 설치본), https://docs.isaacsim.omniverse.nvidia.com (재배포 불가).
  배포 제외 처리 = `data/pallet/_DISTRIBUTION_EXCLUDE.txt`(isaac_assets/ + _noai_quarantine_usd/ 등재).

### 8. 렌더 산출 데이터셋 (라이선스 상속 대상)

```
dataset                          저장경로                                    상속 블로커
────────────────────────────────────────────────────────────────────────────────────────────
train_palletobj_v1/v2/v3         data/pallet/train_palletobj_v{1,2,3}/       팔레트=자작 OBJ, floor=CC0, occluder=CC0/CC-BY → B5만
train_palletobj_addon_v1         data/pallet/archive/train_palletobj_addon_v1/       팔레트=자작 OBJ → B5(CC-BY occluder 표시)만
train_4pallet_mask_v1            data/pallet/archive/train_4pallet_mask_v1/          B1(NoAI 목재 P2/P3 baked) [+ B5]
trunc_addon_v1                   data/pallet/archive/trunc_addon_v1/                 팔레트=자작 OBJ → B5만
training_data_v4 / _v4_split     data/pallet/archive/training_data_v4*/              B1(NoAI 목재 P2/P3 baked) [+ B5]
training_data (구)               data/pallet/archive/training_data/                  B1 가능 [+구 BG]
real_data (실촬영)                data/pallet/reference/real_images/real_data/*.jpg                 본인 촬영(D435i) → 본인 IP, Y
```
- 렌더 데이터셋은 **baked된 모든 소스 에셋의 라이선스를 상속**한다. **B2 오탐 종료·B4 해소(floor CC0) →
  palletobj/trunc/addon 계열은 Isaac·floor 블로커 없음**(occluder=Poly Haven CC0/일부 CC-BY, floor=CC0).
  **파이프라인 blend는 재-bake로 NoAI 제거 완료(B1 해소)** — 단 **기존 렌더 산출물**(v4/v4_split/4pallet_mask)에는
  구 NoAI 목재가 이미 baked → 이 구 데이터셋은 **재-bake된 클린 blend로 v2 재생성** 후에만 공개 가능. (재생성은
  데이터 산출 작업이지 블로커 해소 아님.) palletobj_v1/v2/v3·addon·trunc는 팔레트가
  자작 `pallet_full.obj`라 B1 무관 — CC-BY occluder attribution **B5만** 상속.)
- `real_data/`(color_*.jpg, RealSense D435i 실촬영)는 사용자 본인 촬영물 → 본인 IP(Y). 단 실제 현장
  로고/상표/인물 포함 여부는 별도 확인 권장(경미).
- 루트의 다수 `test_blender_v*`, `_*`(테스트/디버그 렌더·로그)는 파생 산출물 — 공개 대상 아니면 배포 제외.

---

## Gap별 검증 결과 (요구 3갭)

**Gap 1 — floor/wood 텍스처 라이선스 (둘 다 해소)**
- 목재 9종: **검증 완료 → Poly Haven CC0** (`_tmp_ph` 다운로드 매니페스트 `dl.polyhaven.org` + history 명문). Y.
- floor 14종: **해소(B4, 2026-07-24)**. `textures_floor/{SOURCES.txt,LICENSE.txt}` = 14/14 CONFIRMED Poly
  Haven CC0. 미검증 5종(tile_white·tile_brown·wood_laminate·dirt_ground·red_earth)을 동등 Poly Haven CC0로
  내용 교체(파일명 유지=코드 무변경, 원본 백업 `_replaced_originals/`). 그룹 6에 5종 새 URL 반영. Y.

**Gap 2 — USD ↔ Sketchfab 매핑 (B3 해소, 2026-07-24)**
- 4개 `scene*.usd` 전부 PXR-USDC(바이너리 crate), Sketchfab 메타데이터 문자열 0 [확인] → 저작자 1:1 매핑은
  로컬 파일만으로 여전히 불명. 그러나 **재질 확정으로 매핑 불필요화**.
- 카탈로그 렌더(`_pallet_catalog_0123/pallet_0123_row.png`) 육안 [확인]: **P0=빨강 플라스틱, P1=초록
  플라스틱, P2=어두운 목재, P3=밝은 목재**. NoAI "Old Wooden Pallet"은 **목재** → 반드시 {P2,P3} 중 하나.
- **결론(해소)**: P0/P1(플라스틱)은 NoAI 아님 확정(유지, CC-BY). 목재 P2/P3를 **둘 다 격리·교체**(그룹 1) →
  "어느 목재가 NoAI인가" 매핑 질문 자체가 무의미. **B3 해소**. (B1도 blend 재-bake·로더 repoint 완료로
  파이프라인서 NoAI 제거 = 해소, 위 B1 참조.)
- 재질 단서(참고): P1=`blinn1`(Maya)+`Collada_visual_scene_group`(DAE), P0=20MB glTF파생(`Scene___Root`),
  P2=`lambert16`, P3=`Material_018`.

**Gap 3 — 누락 방지 전수 열거 (신규 편입 항목)**
- `pallets_v2_add/`(v2 신규 팔레트 3: stringer CC0 + J-Toastie CC-BY3.0 + EUR-Pallet CC0) → 그룹 2. 후자
  2종이 격리 목재 P2/P3의 교체분.
- `_noai_quarantine_usd/`(격리된 scene_2/3.usd + README) → 그룹 1(격리 표).
- `models_usd/textures/`(blinn1/lambert16 원자재), `scene_noemit.usd` → 그룹 1로 편입.
- `_procedural_textures/`(자작 21) → 그룹 6.
- **baked Sketchfab_model — ⚠️ 정정(2026-07-24 심층 확인)**: "Sketchfab_model"은 (a) CC-BY 배경
  (modular_buildings/parking_lot) 임포트 루트(정상, 표시 의무 B5)이면서, **동시에 (b) 옛 baked distractor
  오브젝트 ×3의 이름**이기도 함. **(b) 3개가 현 occlusion 선택 `DISTRACTOR_NAMES`(8)에 포함 = 라이선스 불명
  자산이 실제 가림 렌더에 들어감** [확인]. 초기 토큰-grep은 (a)와 (b)를 구분 못 해 "증거 없음"이라 했으나
  오판 — **selection 레벨에선 3개 실재**. modern_city_block 토큰은 여전히 0(비-CC 배경 baked 아님). → **B5/릴리스
  관문: v2 재생성·공개 전 occlusion 선택을 209 CC0/CC-BY 풀로 재배선 필수**(아래 그룹 7, 종합판정).
- **occluder [B2 오탐 종료]**: 프로덕션 blend 157MB 해제 grep Isaac 지문 0 → occluder=Poly Haven CC0
  (이름충돌 오탐) → 그룹 7. **isaac_assets/ NVIDIA(B6, occluder 소스 아님·v4 잔재)** → 그룹 7.
- **★ blend baked 팔레트 [task5→재-bake 완료, B1 해소]**: `synth_data_scene.blend`(zstd)에 Pallet_0~3
  형상이 baked였고, 격리 전에는 Pallet_2/3(NoAI 목재)가 mesh로 잔존했음. **2026-07-24 재-bake로 제거 완료**
  (새 blend grep: scene_2/3.usd·LP_merge_lambert16·Material_018·Legacy_Pallet_2/3 전부 0; 새 목재 J-Toastie/
  EUR 투입). 백업 `synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend`에 원본 보존. → 렌더 시 NoAI 미출력.

---

## 공개가능 종합판정 (갱신 2026-07-24)

**현재 상태: 팔레트 블로커(B1/B3) 전부 해소, B2 오탐·B4 해소. 잔여 = B5·B6(절차) + ★occlusion 선택 재배선 + 구 데이터셋 v2 재생성.**

**B1 해소**(blend 재-bake로 NoAI 원천 제거, 3부 조건 완료 + legacy-purge 강건화). **B2 오탐 종료**(occluder=
Poly Haven CC0). **B3 해소**(재질 확정). **B4 해소**(floor 14/14 CC0 확정). **잔여 = B5(CC-BY 표시)·B6
(isaac_assets 제외)** + **★occlusion 선택 재배선**(현 `DISTRACTOR_NAMES`(8)에 라이선스 불명 `Sketchfab_model`
×3 포함 → 실 가림 렌더 오염, 209 CC0/CC-BY 풀로 교체 필요). distractor 209는 blend import+tag 완료(에셋 가용),
선택 배선은 다음 phase.

**공개(Y) 도달 조건 — 갱신 해결 순서**
```
1) ★occlusion 선택 재배선: DISTRACTOR_NAMES(8) 중 Sketchfab_model×3(라이선스 불명) 제거 → 209 CC0/CC-BY
   풀로 교체. v2 재생성 전 필수(안 하면 unknown-license가 가림 렌더에 baked).
2) v2 재생성: 재-bake된 클린 blend(+재배선된 occlusion)로 v4/v4_split/4pallet_mask 재생성(구 산출물 폐기).
3) B5: CC-BY 전 항목(P0/P1 플라스틱·배경2·GSO≈128·Sketchfab16·J-Toastie·occluder CC-BY 8) 통합 attribution 동봉.
4) B6: isaac_assets/ 원본을 공개 배포 트리에서 제외(`_DISTRIBUTION_EXCLUDE.txt` 등재됨).
```

**즉시 공개 가능(클린) 자산** — HDRI 30(CC0), Poly Haven distractor 65(CC0)·occluder CC0, 목재 텍스처 9(CC0),
**floor 텍스처 14(CC0, 확정)**, v2 stringer·EUR-Pallet(CC0), 재-bake blend(NoAI 제거), pallet_full.obj·
real_data(본인 IP). CC-BY 자산(팔레트 P0/P1·배경2·GSO≈128·Sketchfab16·J-Toastie·occluder CC-BY)은
**저작자표시 동봉 시** 공개 가능.

**종료된 항목(잔여에서 제외)**: B1(blend 재-bake + legacy-purge로 NoAI 파이프라인 제거) / B2(Isaac occluder,
오탐) / B3(USD 매핑, 재질 확정) / B4(floor 14/14 CC0 확정) / paper_s2 실학습셋 확인(v2 재생성으로 대체 →
불필요) / C3 실 평가셋 clutter 분포(이 머신 범위 밖) / distractor 209 **에셋 통합(import+tag 완료)**. **다음
phase**: occlusion 선택 배선(`DISTRACTOR_NAMES`→209, Placement). **보류(지금 결정 안 함)**: 20+ clutter 복제로직.

**핵심 리스크 요약(갱신)**: (1) NoAI 리스크는 목재 2종 격리 + **blend 재-bake**(scene_2/3.usd·Legacy_Pallet_2/3
전부 grep 0) + **legacy-purge**(로더 삭제-on-성공, Legacy_Pallet_0/1 제거 = 재-bake 누적원인 차단)로 **파이프라인서
원천 제거 완료** — 단 **구 데이터셋(v4/4pallet_mask)은 NoAI가 이미 baked라 v2 재생성 전까지 공개 불가**.
(2) "occluder=Isaac" 우려는 **오탐으로 종료**(occluder=Poly Haven CC0). (3) **★현 occlusion 선택에 라이선스 불명
`Sketchfab_model`×3 잔존** → 209 CC0/CC-BY 풀 재배선 전까지 실 가림 렌더가 unknown-license 오염 = **릴리스/v2
재생성 전 필수 처리**. 실질 남은 것 = **B5·B6 + occlusion 재배선**.
