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

## ⚠️ BLOCKERS — 공개 전 반드시 해결 (B1·B2·B3·B4 + ★재배선 해소, 잔여 = B5·B6 절차 2건)

> **갱신 2026-08-02 (★occlusion 선택 재배선 = 해소 확인)**: 아래 07-24 시점의 "★재배선 필요"는
> **v2 파이프라인 코드에서 이미 완료**됨을 코드 실물로 확인 [확인]. `v2_realize.py:61`·`v2_pipeline.py:53`이
> `distractor_pool_v2`(209 CC0/CC-BY manifest 기반)를 import 하고 occluder/context 선택을
> `dpool.select_distractor_object_names()`(v2_realize.py:2554)로 수행 — 209 풀에 `Sketchfab_model*`이
> 없으므로 **선택 자체가 불가능**(`distractor_pool_v2.py:19-21` 명시). 레거시 `DISTRACTOR_NAMES`
> (`config/synthetic/blender.yaml:35-41`)도 현재 **5종**(Barrel_01·Barrel_1·concrete_road_barrier·
> TrafficCone_1·TrafficCone_2)뿐이며 `Sketchfab_model` 없음. 추적 파일 전체 `git grep "Sketchfab_model"`
> → **주석 3곳뿐, 선택 목록 0건**. → **잔여 = B5(attribution)·B6(isaac_assets 제외) 절차 2건 + 구 데이터셋 v2 재생성.**
>
> **한정 [미검증]**: 확인 범위는 *선택 경로*(코드)다. blend 파일 내부에 `Sketchfab_model` 오브젝트가
> 물리적으로 남아 있는지는 Blender를 열어야 확인 가능 — 선택되지 않으므로 렌더 산출물 영향은 없다 `[추정]`.
> **새 미검증 항목 `?`**: 위 레거시 5종(Barrel_01 등)의 라이선스는 이 원장에 명시 기록이 없다(그룹 7 참조).

> **갱신 2026-07-24 (팔레트 교체·blend 재-bake 완료 + B2 오탐 정정)**: 목재 P2/P3(`scene_2/3.usd`) 격리 →
> 새 목재 2종(J-Toastie CC-BY3.0 + EUR-Pallet BlenderKit CC0) 투입, **프로덕션 blend 재-bake로 NoAI 목재
> 완전 제거 + 로더 repoint 완료 → B1 파이프라인 관문 해소**. **B2는 오탐으로 종료**(Isaac 지문 0, occluder=
> Poly Haven CC0). distractor 209는 blend에 import+tag 완료(에셋 가용), 선택 배선은 다음 phase.
> (당시 서술된 "★occlusion 선택 재배선 필요"는 위 2026-08-02 확인으로 **해소**.)

```
#    상태            블로커                                                          영향 범위
────────────────────────────────────────────────────────────────────────────────────────────────
B1   해소            "Old Wooden Pallet"(Luka Feric)=Standard+NoAI: 파이프라인서 제거  구 데이터셋만 v2 재생성 필요
B2   종료(오탐)      OCCLUDER=Isaac 오탐 → 실제 Poly Haven CC0(이름충돌)               (블로커 아님)
B3   해소            USD↔Sketchfab 매핑: 렌더로 P0/P1=플라스틱·P2/P3=목재 확정        목재 2종 다 교체→불확실성 소멸
B4   해소            floor 14/14 Poly Haven CC0 확정(미검증 5종 CC0 교체)              floor 전부 CC0(표기 불요)
B5   미해결 MEDIUM   CC-BY 저작자표시 의무 미이행 시 위반(첨부 attribution 필수)        Sketchfab/GSO/CC-BY 전부
B6   미해결 LOW      isaac_assets/(NVIDIA 창고 USD) 트리에 존재 — 배포물서 제외 필요     소스 에셋(렌더 산출물 아님)
B7   해소            NoAI dataset 압축본이 exclusion 에서 빠져 ZIP 경로로 누출 가능     train_4pallet_mask_v1.zip
B8   해소            v4 계열 파생 4종 = PROVEN_NOAI 확정 (라벨 전수) + noai_baked 격리   GREYBUG·bg1bak·emptywood·pilotA
★    해소(08-02)     occlusion 선택에 라이선스 불명 Sketchfab_model×3 → 209 풀 재배선    v2 선택 경로 코드 확인
?    미검증          레거시 DISTRACTOR_NAMES 5종(Barrel/TrafficCone/road_barrier) 라이선스 원장 기록 없음(그룹 7)
```

**B7 (해소 2026-07-30, Stage 2-D0.1)** — `archive/train_4pallet_mask_v1/`(NoAI baked)은
`_DISTRIBUTION_EXCLUDE.txt` 에 있었는데 **대응 압축본 `train_4pallet_mask_v1.zip`(9.0GB)이
빠져 있었다.** 추출본만 제외하면 같은 NoAI 산출물이 ZIP 경로로 릴리스에 들어갈 수 있다.
→ ZIP 을 exclusion 에 추가했다(entries 11→16, problems 0, leaks 0).
다른 NoAI 압축본(`training_data_v4_split.zip` 등)은 이미 제외된 디렉토리 **안**에 있어 덮인다.
`pallet.zip`(15.5GB)은 central directory 실측 결과 구성이 `train_palletobj_v1`+`v2` 뿐이고
둘 다 redistributable 이므로 **제외 대상이 아니다**(B5 attribution 만 필요). [확인]

**B8 (신규 2026-07-30 Stage 2-D0.1 → 해소 2026-07-30 Stage 2-D1.1/D1.2)**

*제기 (D0.1)* — `archive/` 아래 v4 계열 파생 4종(`training_data_v4_split_GREYBUG` ·
`_bg1bak` · `training_data_v4_emptywood` · `training_data_v4_pilotA`)은 이름상
`training_data_v4*` 파생이고 그 본체는 NoAI baked 로 제외돼 있다. 그러나 **파생본이 같은
blend 로 렌더됐는지는 라벨 metadata 로 확인하지 않았다** — 이름 유사성만으로 NoAI 를
단정하지 않는다. UNKNOWN_LICENSE 로 두고 보수적으로 exclusion 유지했다.

*확정 (D1.1 §provenance)* — 이름이 아니라 **라벨을 읽어** 판정했다. 라벨 JSON
**13,122개(= 프레임 13,120) 전수** 스캔, 표본 아님, 읽기 실패 0.

```
move_id  dataset                        프레임   NoAI 프레임      %    mtime       재-bake 이전
──────────────────────────────────────────────────────────────────────────────────────────────
D1-041   training_data_v4_split_GREYBUG  5,000      3,286      65.7%  2026-06-17   yes
D1-042   training_data_v4_split_bg1bak   5,000      3,272      65.4%  2026-06-16   yes
D1-043   training_data_v4_emptywood      3,000      3,000     100.0%  2026-06-18   yes
D1-049   training_data_v4_pilotA           120         76      63.3%  2026-06-16   yes
──────────────────────────────────────────────────────────────────────────────────────────────
합계                                     13,120      9,634      73.4%
```

근거 3단:
- **적극적 사용 증거** — 각 dataset 의 `objects[].name` 에 `Pallet_2`/`Pallet_3` 가 직접
  기록돼 있다. "NoAI 표식이 없다"는 소극적 근거가 아니다. `emptywood` 는 `Pallet_1` 이
  아예 없고 100% 가 NoAI 목재다.
- **자산 동일성** — `Pallet_2`/`Pallet_3` = `scene_2.usd`/`scene_3.usd` = "Old Wooden
  Pallet"(Luka Feric, Standard+NoAI, B1). 해당 USD 는 `archive/_noai_quarantine_usd/`
  에 실물로 남아 있다.
- **시점** — mtime 2026-06-16~18 로, NoAI 목재를 제거한 2026-07-24 blend 재-bake **이전**
  이다. 즉 NoAI 가 baked 된 blend 로 렌더됐다.

*조치 (D1.2 D12C)* — PROVEN_NOAI 4종(39,620 파일 / 15,588,789,193 B = 14.52 GiB)을
`archive/legacy_datasets/noai_baked/` 로 이동해 다른 7종 NoAI baked 산출물과 한곳에 모았다.
same-volume rename, hash-mode=all, pre/post SHA256 전수, failures 0.

```
최종 경로 (릴리스 제외)
  archive/legacy_datasets/noai_baked/training_data_v4_split_GREYBUG    15,051 파일  4.93 GiB
  archive/legacy_datasets/noai_baked/training_data_v4_split_bg1bak     15,056 파일  4.93 GiB
  archive/legacy_datasets/noai_baked/training_data_v4_emptywood         9,031 파일  4.49 GiB
  archive/legacy_datasets/noai_baked/training_data_v4_pilotA              482 파일  0.18 GiB
```

`release_allowed = NO` (4/4). `_DISTRIBUTION_EXCLUDE.txt` 를 새 경로로 갱신했다
(entries 16 / problems 0 / leaks 0 / stale 0). ⚠️ 이 exclusion 파일은 **gitignored** 라
저장소에 커밋되지 않는다 — 릴리스 패키징을 다른 머신에서 하면 이 파일이 없다. 배포 스크립트를
쓸 때 이 원장(B8·B7·B6·B1)이 근거 정본이다.

**해소 판정**: UNKNOWN_LICENSE → PROVEN_NOAI 확정 + 물리 격리 + exclusion 반영 완료.
"확정되지 않아 보수적으로 제외"가 아니라 **확정돼서 제외**다. 재생성 필요 계열
(v4/v4_split/4pallet_mask)에 이 4종도 포함된다.

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
P0 scene.usd   data/pallet/assets/pallets/models/models_usd/scene.usd      Sketchfab    herisuwardi71  CC-BY 4.0    Y*    B5(표시)
P1 scene_1.usd data/pallet/assets/pallets/models/models_usd/scene_1.usd    Sketchfab    billy3D        CC-BY 4.0    Y*    B5(표시)
scene_noemit   data/pallet/assets/pallets/models/models_usd/scene_noemit   scene.usd파생 (P0 동일)       (P0 상속)    Y*    B5(표시)
blinn1_*.png   data/pallet/assets/pallets/models/models_usd/textures/blinn1_*  P1 참조   billy3D        (P1 상속)    Y*    B5(표시)
lambert16_*.png data/pallet/assets/pallets/models/models_usd/textures/lambert16_* P2 참조 미확정        미확정        ?     ★신규(아래)
```
- **★ P0/P1 원출처 확정 [강한 정황, 2026-08-02 Sketchfab API 역검색]** — 아래 §"source URL 상태" 참조.
- **★ `lambert16_*.png` 3개 = 격리된 P2 의 텍스처 [확인, 2026-08-02]**: USD 바이트 스캔 결과
  `lambert16` 토큰은 **`scene_2.usd`(격리본)에만** 있고 P0/P1/P3 엔 없다(`blinn1` 은 P1 에만).
  즉 이전 기록 "blinn1_*/lambert16_* 원자재는 P0/P1 상속"은 **lambert16 에 한해 오류** —
  P2 는 andree(CC-BY)/Luka Feric(NoAI) 중 어느 쪽인지 **미확정**이므로 이 3개 png 는
  **NoAI 텍스처일 가능성이 남아 있다**. 게다가 (a) `_DISTRIBUTION_EXCLUDE.txt` 에
  `models_usd/textures/` 가 없어 **배포 시 포함**되고, (b) `randomizers.py:121` 이 이름
  `lambert16` 머티리얼을 조회한다(없으면 fallback). → **P2/P3 판정 전까지 미해결**.
  판정법은 §"source URL 상태" 의 정점수 대조.
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
- **★ source URL 상태 — 2026-08-02 Sketchfab API 역검색으로 P0/P1 확정 [강한 정황]**:
  내부 조사 먼저 수행했으나 **history 는 2026-03-25 부터**라 USD 확보일(2026-03-04) 기록이 없고
  원본 ZIP 도 아카이브에 없음 [확인]. → 외부 Sketchfab API(`api.sketchfab.com/v3/models/<uid>`)로
  시드 4모델의 실측 폴리곤·라이선스를 받아 우리 USD 파일 크기와 대조.
  ```
  Sketchfab 모델                   faces     verts    라이선스        → 슬롯   USD 크기
  ─────────────────────────────────────────────────────────────────────────────────────
  "pallet 2606"  herisuwardi71    426,540  209,960   CC-BY          P0       20.9 MB
  "Plastic Pallet"  billy3D         4,392    1,958   CC-BY          P1        0.33 MB
  "Old Wooden Pallet"  Luka Feric   3,024    1,568   Free Standard  P2|P3     0.17 / 0.57 MB
  "Pallet"  andree(maestronoov)     2,160    1,120   CC-BY          P2|P3
  ```
  - **P0 = "pallet 2606" (herisuwardi71), CC-BY** —
    https://sketchfab.com/3d-models/pallet-2606-9fc3dca70fdb466e87602d3721d1075a
    근거: 4모델 중 **유일한 고폴리(426k faces, 나머지 전부 5k 미만)** ↔ 우리 P0 만 유일하게 20.9MB
    (나머지 3개는 ≤0.6MB) + 썸네일 형상(둥근 모서리 사각 플라스틱·격자 리브·막힌 상판)이 카탈로그
    `_pallet_catalog_0123/pallet_0123_row.png` 의 P0 와 일치. **[강한 정황] — 바이트/지오메트리
    동일성 확인은 아님**(Sketchfab 다운로드에 로그인 필요).
  - **P1 = "Plastic Pallet" (billy3D/billyNG), CC-BY** —
    https://sketchfab.com/3d-models/plastic-pallet-0699da1b0dd04c13b5c6731c8dda75d1
    기존 후보 URL 이 폴리곤 대조(4,392 faces ↔ 0.33MB)로 뒷받침됨.
  - **격리 P2/P3: 매핑 여전히 미확정** — 목재 2모델은 Luka Feric(3,024 f, **NoAI**) + andree(2,160 f, CC-BY).
    파일 크기로는 못 가른다(P3 가 P2 의 3.3배인데 faces 는 1.4배 차 = 텍스처 임베드 여부로 갈릴 수 있음).
    **확정법**: Blender 로 두 격리 USD 를 임포트해 **정점수를 세면 1,568 vs 1,120 으로 1:1 판명**된다.
    → 판정되면 (a) CC-BY 쪽은 격리 해제 가능, (b) `lambert16_*.png`(P2 텍스처) 귀속도 동시 종결.
  - Luka Feric 모델 라이선스 재확인 [확인]: API `license.label = "Free Standard"` — 시드 감사 기록과 일치.
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
modular_buildings_industrial_area assets/.../background/modular_buildings.../     Sketchfab  BazukaliKartal   CC-BY 4.0   Y*    *표시 필수(B5)
parking_lot                       assets/.../background/parking_lot/              Sketchfab  Veterock         CC-BY 4.0   Y*    *표시 필수(B5)
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
GSO ×128                  assets/distractors/library/{tier}/(gso__*)  Google Scanned Objects CC-BY 4.0   Y*    *표시 필수(B5); 32→128(D확장)
Poly Haven ×65            assets/distractors/library/{tier}/(ph__*)   Poly Haven             CC0 1.0     Y     -
Sketchfab ×16             assets/distractors/library/{tier}/(sf__*)   Sketchfab              CC-BY 4.0   Y*    *표시 필수(B5)
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
- **목재 9종 [확인, API 전수 검증 완료 2026-08-02]**: `textures_wood/{LICENSE.txt, SOURCES.txt}` 생성 =
  **9/9 CONFIRMED Poly Haven CC0, 0 UNVERIFIED**. floor 14종과 **동일 기준**(`https://api.polyhaven.com/
  info/<slug>` 200 + human-readable name 일치 + `type:1`)으로 9 slug 전수 조회. 저자: Rob Tuytel(4) ·
  Dimitrios Savva(2, 공동) · Jenelle van Heerden+Matterfield · Dario Barresi · Amal Kumar · Rico Cilliers.
  - **이전 근거 상태(해소 전)**: 폴더에 LICENSE/SOURCES **부재**, 근거는 (a) `_tmp_ph/*_files.json` 6개
    (`dl.polyhaven.org` 다운로드 매니페스트: brown_planks_04·dark_planks·plank_flooring_03·weathered_planks·
    wood_planks·wood_planks_grey) + (b) 나머지 3종(brown_planks_03·weathered_brown_planks·worn_planks)은
    history 2026-06-16 서술뿐(artifact 없음)이었다. **08-02 검증에서 그 3종도 200/name일치/type:1 통과** →
    provenance gap 종료. 파일 내용은 무수정(floor 처럼 교체한 것 아님).
  - **★ source URL (재발견용)**: URL 패턴 `https://polyhaven.com/a/<name>` (name = 파일명에서 `_diff/_nor_gl/
    _rough` 접미 제거). 예: https://polyhaven.com/a/wood_planks , https://polyhaven.com/a/plank_flooring_03 ,
    https://polyhaven.com/a/weathered_planks . (다운로드 CDN URL 원본은 `data/pallet/archive/superseded_runs/_tmp_ph/*_files.json`.)
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
- **★ 현 occlusion 선택 라이선스 갭 → 해소 [확인, 2026-08-02 코드 재검증]**: 07-24 시점 서술은
  "occlusion 선택 `DISTRACTOR_NAMES`(8)에 옛 `Sketchfab_model`×3(라이선스 불명) 포함 → 실 가림 렌더 오염,
  209 풀 재배선 필수"였다. **그 재배선은 이후 완료되었고 원장만 갱신이 밀려 있었다.** 확인 근거:
  ```
  근거                                                        파일:라인
  ────────────────────────────────────────────────────────────────────────────────────────
  v2 선택 소스 = distractor_pool_v2 (209 manifest)             v2_realize.py:61, v2_pipeline.py:53
  occluder/context 선택 호출                                   v2_realize.py:2554 select_distractor_object_names()
  209 풀에 Sketchfab_model 부재 → 선택 불가 (모듈 docstring)     distractor_pool_v2.py:19-21, :124
  레거시 DISTRACTOR_NAMES = 5종, Sketchfab_model 없음           config/synthetic/blender.yaml:35-41
  추적 파일 전체 grep → 주석 3곳뿐, 선택 목록 0건                git grep "Sketchfab_model" -- scripts/ config/
  구 생성기도 209 풀로 전환됨(주석 명시)                          gen_4pallet_mask.py:119, gen_dataset_v4.py:105
  ```
  **한정**: 위는 *선택 경로*(코드) 기준 [확인]. blend 내부에 해당 오브젝트가 물리적으로 잔존하는지는
  미검증 — 선택되지 않으므로 렌더 산출물에는 들어가지 않는다 `[추정]`. **distractor 209 통합 상태**:
  `synth_data_scene.blend`에 unpacked append + 태그 완료(`is_distractor_v2`=209, `size_class` 메타 209,
  GSO magenta 0, blend 342MB<1GB) = 에셋 가용화 완료 → **선택 배선까지 완료(본 항목 종료)**.
- **`?` 레거시 DISTRACTOR_NAMES 5종 — 라이선스 기록 없음 [미검증, 2026-08-02 신규]**:
  `config/synthetic/blender.yaml:35-41`의 `Barrel_01`·`Barrel_1`·`concrete_road_barrier`·`TrafficCone_1`·
  `TrafficCone_2`. v2 경로는 이 목록을 occluder 선택에 쓰지 않으나(위 참조) **레거시 생성기 경로에서는
  참조 가능**(`randomizers.py:954`). 이름상 Poly Haven CC0 계열로 보이지만 **원장·LICENSE 파일에 대응
  기록이 없다** → 추정으로 단정하지 않고 `?`로 남긴다. 구 데이터셋 v2 재생성 시 209 풀만 쓰면 무의미해짐.
- **isaac_assets/ (B6 유지)**: full_warehouse.usd + warehouse*.usd + Props(S_AisleSign/S_TrafficCone/
  S_WetFloorSign/SM_CratePlastic 등) + Materials(*.mdl). NVIDIA Isaac Sim 배포 에셋 → **배포물서 제외**.
  단 이 폴더는 **occluder 소스가 아님**(occluder는 Poly Haven) — Isaac 파이프라인(v4 USD) 잔재. 재취득 경로 =
  NVIDIA Isaac Sim 4.5 에셋 팩(Omniverse 설치본), https://docs.isaacsim.omniverse.nvidia.com (재배포 불가).
  배포 제외 처리 = `data/pallet/_DISTRIBUTION_EXCLUDE.txt`(isaac_assets/ + _noai_quarantine_usd/ 등재).

### 8. 렌더 산출 데이터셋 (라이선스 상속 대상)

```
dataset                          저장경로                                    상속 블로커
────────────────────────────────────────────────────────────────────────────────────────────
train_palletobj_v1/v2/v3         archive/legacy_datasets/redistributable/  ★v3는 미이동            팔레트=자작 OBJ, floor=CC0, occluder=CC0/CC-BY → B5만
train_palletobj_addon_v1         archive/legacy_datasets/redistributable/train_palletobj_addon_v1/       팔레트=자작 OBJ → B5(CC-BY occluder 표시)만
train_4pallet_mask_v1            archive/legacy_datasets/noai_baked/train_4pallet_mask_v1/          B1(NoAI 목재 P2/P3 baked) [+ B5]
trunc_addon_v1                   data/pallet/archive/trunc_addon_v1/                 팔레트=자작 OBJ → B5만
training_data_v4 / _v4_split     archive/legacy_datasets/noai_baked/training_data_v4*/              B1(NoAI 목재 P2/P3 baked) [+ B5]
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
- **baked Sketchfab_model — 정정(07-24) 후 해소(08-02)**: "Sketchfab_model"은 (a) CC-BY 배경
  (modular_buildings/parking_lot) 임포트 루트(정상, 표시 의무 B5)이면서, **동시에 (b) 옛 baked distractor
  오브젝트 ×3의 이름**이기도 함. 초기 토큰-grep은 (a)와 (b)를 구분 못 해 "증거 없음"이라 했으나 오판 —
  07-24 당시 **selection 레벨에선 3개 실재**했다. **→ 2026-08-02 확인: 선택 배선이 209 CC0/CC-BY 풀로
  교체되어 (b)는 더 이상 선택되지 않는다** [확인, 그룹 7 근거표]. (a)는 CC-BY 배경이라 B5 표시 대상으로 유지.
  modern_city_block 토큰은 여전히 0(비-CC 배경 baked 아님).
- **occluder [B2 오탐 종료]**: 프로덕션 blend 157MB 해제 grep Isaac 지문 0 → occluder=Poly Haven CC0
  (이름충돌 오탐) → 그룹 7. **isaac_assets/ NVIDIA(B6, occluder 소스 아님·v4 잔재)** → 그룹 7.
- **★ blend baked 팔레트 [task5→재-bake 완료, B1 해소]**: `synth_data_scene.blend`(zstd)에 Pallet_0~3
  형상이 baked였고, 격리 전에는 Pallet_2/3(NoAI 목재)가 mesh로 잔존했음. **2026-07-24 재-bake로 제거 완료**
  (새 blend grep: scene_2/3.usd·LP_merge_lambert16·Material_018·Legacy_Pallet_2/3 전부 0; 새 목재 J-Toastie/
  EUR 투입). 백업 `synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend`에 원본 보존. → 렌더 시 NoAI 미출력.

---

## 공개가능 종합판정 (갱신 2026-08-02)

**현재 상태: 에셋 블로커 전부 해소(B1/B2/B3/B4 + ★재배선). 잔여 = B5·B6 절차 2건 + 구 데이터셋 v2 재생성.**

**B1 해소**(blend 재-bake로 NoAI 원천 제거, 3부 조건 완료 + legacy-purge 강건화). **B2 오탐 종료**(occluder=
Poly Haven CC0). **B3 해소**(재질 확정). **B4 해소**(floor 14/14 CC0 확정). **★occlusion 선택 재배선 해소**
(2026-08-02 코드 확인 — v2 선택 소스가 `distractor_pool_v2` 209 CC0/CC-BY 풀이며 `Sketchfab_model*`은
선택 불가; 근거표는 그룹 7). **잔여 = B5(CC-BY 표시)·B6(isaac_assets 제외)** — 둘 다 **배포 시점 절차**이지
현재 생성 파이프라인의 오염 요인이 아니다.

**★ 현재 "생성/학습" 단계 판정**: 신규 v2 생성분은 **라이선스 클린** — NoAI 미사용, unknown-license
occluder 미선택, isaac_assets 미참조(occluder 소스 아님·v4 잔재). **B5는 배포 시점에 발생하는 의무**이므로
사내 생성·학습만 하는 현 단계에서는 위반이 아니다. 단 **구 데이터셋(noai_baked 8종)을 학습에 재사용하면
그 시점에 오염**되므로 격리 유지가 전제.

**공개(Y) 도달 조건 — 갱신 해결 순서**
```
1) [해소 08-02] occlusion 선택 재배선 → 209 CC0/CC-BY 풀 (v2_realize.py:2554 / distractor_pool_v2)
2) v2 재생성: 재-bake된 클린 blend(+209 풀 occlusion)로 v4/v4_split/4pallet_mask 재생성(구 산출물 폐기).
3) B5: CC-BY 전 항목(P0/P1 플라스틱·배경2·GSO≈128·Sketchfab16·J-Toastie·occluder CC-BY 8) 통합 attribution 동봉.
4) B6: isaac_assets/ 원본을 공개 배포 트리에서 제외(`_DISTRIBUTION_EXCLUDE.txt` 등재됨).
```

**근거가 약한 잔여 (공개 전 보강 권장, 블로커 아님)**
```
항목                      현 근거                                      필요 조치
──────────────────────────────────────────────────────────────────────────────────────
[해소 08-02] wood 9종     API 9/9 CONFIRMED + LICENSE/SOURCES.txt 생성  없음 (종료)
레거시 DISTRACTOR 5종     기록 없음 (`?`)                              v2 재생성으로 무의미화되면 종료
P0 canonical URL          title/author 단서만                          B5 표기용 원출처 URL 확정 권장
```

**즉시 공개 가능(클린) 자산** — HDRI 30(CC0), Poly Haven distractor 65(CC0)·occluder CC0, 목재 텍스처 9(CC0),
**floor 텍스처 14(CC0, 확정)**, v2 stringer·EUR-Pallet(CC0), 재-bake blend(NoAI 제거), pallet_full.obj·
real_data(본인 IP). CC-BY 자산(팔레트 P0/P1·배경2·GSO≈128·Sketchfab16·J-Toastie·occluder CC-BY)은
**저작자표시 동봉 시** 공개 가능.

**종료된 항목(잔여에서 제외)**: B1(blend 재-bake + legacy-purge로 NoAI 파이프라인 제거) / B2(Isaac occluder,
오탐) / B3(USD 매핑, 재질 확정) / B4(floor 14/14 CC0 확정) / paper_s2 실학습셋 확인(v2 재생성으로 대체 →
불필요) / C3 실 평가셋 clutter 분포(이 머신 범위 밖) / distractor 209 **에셋 통합(import+tag 완료)** /
**★occlusion 선택 배선(→209 풀, 2026-08-02 코드 확인으로 종료)**. **보류(지금 결정 안 함)**: 20+ clutter 복제로직.

**핵심 리스크 요약(갱신 2026-08-02)**: (1) NoAI 리스크는 목재 2종 격리 + **blend 재-bake**(scene_2/3.usd·
Legacy_Pallet_2/3 전부 grep 0) + **legacy-purge**(로더 삭제-on-성공, Legacy_Pallet_0/1 제거 = 재-bake 누적원인
차단)로 **파이프라인서 원천 제거 완료** — 단 **구 데이터셋(v4/4pallet_mask)은 NoAI가 이미 baked라 v2 재생성
전까지 공개 불가·재학습 금지**. (2) "occluder=Isaac" 우려는 **오탐으로 종료**(occluder=Poly Haven CC0).
(3) **★occlusion 선택의 unknown-license 오염은 해소** — v2 선택 소스가 209 CC0/CC-BY 풀로 교체되어
`Sketchfab_model*`은 선택 불가 [확인, 그룹 7 근거표]. 실질 남은 것 = **B5·B6(배포 시점 절차) + 구 데이터셋
v2 재생성**. 생성 파이프라인 자체에는 라이선스 오염 요인이 남아 있지 않다.

---

### 2026-07-30 Stage 2-D1 — 경로 이동 반영

`archive/` 내부 정리로 restricted 자산의 경로가 바뀌었다. 위 표의 저장경로 열은
갱신했고, `data/pallet/_DISTRIBUTION_EXCLUDE.txt` 도 같이 정정했다
(entries 16 / problems 0 / leaks 0 / stale 0 [확인]).

```
restricted 자산                   현재 경로
──────────────────────────────────────────────────────────────────────────────────
train_4pallet_mask_v1.zip        archive/packages/dataset_bundles/train_4pallet_mask_v1.zip
train_4pallet_mask_v1/           archive/legacy_datasets/noai_baked/train_4pallet_mask_v1/
training_data_v4/                archive/legacy_datasets/noai_baked/training_data_v4/
training_data_v4_split/          archive/legacy_datasets/noai_baked/training_data_v4_split/
training_data/                   archive/training_data/          ← 미이동 (runtime 참조 살아있음)
train_palletobj_v1.zip (손상본)   archive/packages/corrupt/train_palletobj_v1.zip
isaac_assets/ · _noai_quarantine_usd/   변경 없음 (이동 금지)
```

**B8 은 2026-07-30 Stage 2-D1.1 에서 해소됐다** (아래 D1.1 섹션 참조). 원문:
~~B8(v4 파생 4종 NoAI 상속 미확정)은 여전히 미해결이다~~ — 그 4종은 Stage 2-D1 에서
`BLOCKED_UNKNOWN` 으로 이동하지 않았고 `archive/` depth-1 에 옛 경로 그대로 있다.
배포 제외도 옛 경로로 유지된다.

`data/pallet/_DISTRIBUTION_EXCLUDE.txt` 는 **gitignored** 다 — 이 tracked ledger 가
경로 기록의 정본이다.

---

### 2026-07-30 Stage 2-D1.1 — B8 해소: v4 파생 4종 = PROVEN_NOAI [확인]

Stage 2-D0.1 이 "NoAI 상속을 라벨 metadata 로 확인하지 않았다"며 UNKNOWN_LICENSE 로
보류한 4종을 **라벨 전수 스캔으로 확정**했다.

```
dataset                          frames  NoAI 프레임      %   판정
─────────────────────────────────────────────────────────────────────────
training_data_v4_split_GREYBUG    5,000     3,286      65.7%  PROVEN_NOAI
training_data_v4_split_bg1bak     5,000     3,272      65.4%  PROVEN_NOAI
training_data_v4_emptywood        3,000     3,000     100.0%  PROVEN_NOAI
training_data_v4_pilotA             120        76      63.3%  PROVEN_NOAI
```

근거 4중:
1. 라벨 `objects[].name` 에 `Pallet_2`/`Pallet_3` 기록 — 13,122 프레임 전수 스캔, 읽기 실패 0
2. `Pallet_2/3` = `scene_2.usd`/`scene_3.usd` = "Old Wooden Pallet"(Luka Feric, NoAI) — B1
   명시 + 해당 USD 가 `archive/_noai_quarantine_usd/` 에 실존
3. mtime 2026-06-16~18 = 2026-07-24 blend 재-bake(NoAI 제거) **이전**
4. 부모와 바이트 동일 프레임 0/200 → 복사본이 아닌 독립 렌더인데도 NoAI 를 썼다

`README_CONTAMINATION.md` 는 부모 2종에만 있고 파생 4종엔 없다 — **표식 부재는 무죄
근거가 아니다.**

```
판정 분포   PROVEN_NOAI 4 / PROVEN_REDISTRIBUTABLE 0 / UNRESOLVED_LICENSE 0
공개 릴리스  NO (4종 전부)
목적지      archive/legacy_datasets/noai_baked/<name>   ← 부모 2종이 이미 그곳
이동        미실행 (hash 예산 20 GiB 초과 — 29.04 GiB 필요)
            현재 경로는 archive/<name> 이고 exclusion 도 그 경로로 등록돼 있다
```

상세: `reports/data_pallet_cleanup/stage2d11/provenance_report.md` ·
`provenance_decisions.csv`
