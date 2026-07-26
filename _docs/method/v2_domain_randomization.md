# v2 도메인 랜덤화 규약 (blueprint — 다음 phase 구현 대상)

**상태: 미구현.** 이 문서는 v2 재생성 전 "규약 구현" phase의 설계 스펙이다. 여기 적힌 것은 **구현 대상**이며, ★ v2 본 렌더는 구현·검증 완료 후 별도 승인으로만 한다. blend 통합(재-bake·distractor 209 가용화·로더)은 완료 상태([[v2-blend-integration]] / `_docs/history/2026-07-24.md`).

구현 대상 축: 해상도·종횡비 DR(아래 완전 스펙) · Visibility Gate(G3/G5) · Placement f_target 역산 · Intrinsics DR(lens_mm) · Illumination DR · 레이블 스키마. **해상도·종횡비 DR은 이들과 함께 규약 구현 phase에서 구현한다.**

---

## ★ 별도 머신(meas 하네스) 첫 확인 항목 — 우선순위 (2026-07-25)

그 머신 작업을 시작할 때 **다른 것보다 먼저** 확인한다(grep 몇 번이면 끝). 아래 **[높음] 두 개가 걸리면 슬라이드의 px·ADD·yaw 수치가 전부 영향**을 받는다.
```
[높음] meas 하네스에 640 하드코딩 SCALE(×12.8/9.6) 실재 여부
       → belief peak → 원본 px 환산이 해상도 바뀌면 에러 없이 조용히 틀림
[높음] meas 하네스 전처리 = 학습·평가와 동일한 정사각 squash 인지
       → live(run_dope_live:271)처럼 종횡비 보존이면 실도메인 평가 수치가 틀어진다
[낮음] 논문·슬라이드 정성 그림에 live 오버레이(run_dope_live, squash 버그)가 쓰였는지
```
- **이 워크스테이션 확인분(비오염)** [확인]: `evaluate_on_val.py` = per-frame·448² 정사각(학습과 동일) → 논문 정량표 비오염. `run_dope_live.py:450` = 정량 미저장(오버레이 이미지만). 위 3항목은 **이 머신 밖 = [[machine-role-synth-only]]** 소관이라 여기서 조사·수정하지 않음.

---

## 해상도·종횡비 DR (사용자 스펙 2026-07-24)

### 배경 [확인, 코드]
- 렌더 해상도가 하드코딩: `randomizers.py:523-524`(`scene.render.resolution_x/y = IMAGE_WIDTH/IMAGE_HEIGHT`), 카메라 렌즈도 `randomizers.py:545`(`cam.data.lens = FX * SENSOR_WIDTH / IMAGE_WIDTH`)로 IMAGE_WIDTH에 묶임 → **종횡비가 단일 고정, 랜덤화 안 됨**. (값 출처 `blender_config.py:78-79` ← `config/synthetic/blender.yaml`.)
- 4:3→1:1 squash가 렌더 종횡비에 하드코딩 → **16:9 입력은 4:3 대비 가로로 25% 더 눌린다**: 비등방(height/width) 4:3 = 0.750, 16:9 = 0.563.
- 여러 카메라(4:3 D435i 외) 대응이 목표인데 이 축이 랜덤화돼 있지 않음 → **종횡비 축 추가**.

### 렌더 해상도 DR (처방)
```
종횡비  해상도       비중   비고
────────────────────────────────────────────
4:3     640×480      50%    D435i 앵커
16:9    960×540      25%
3:2     720×480      15%
1:1     560×560      10%
(선택)  1280×960     ≤5%    고해상 디테일 통계 확인용
```
- 픽셀 수 억제 근거: **렌더 시간 ∝ 픽셀 수 + 40k 규모** → 1920은 과함. 위 해상도로 한정.
- 네트워크 입력 다중 스케일(400/320/512)은 **이번엔 안 함**. 이유: 학습 설정·배치 크기가 바뀌어 baseline 비교가 흐려짐. **종횡비 축만으로 충분.**

### ★ 같이 고쳐야 하는 것 5개 (없이 해상도만 흔들면 층화·DR·평가 붕괴) — 사용자 정교화 2026-07-24

**① projected-size 층화 = 이미지 폭 대비 비율 (확정 — 640 정규화 아님)**
- 근거 (정정 2026-07-25): 정사각 resize는 **폭과 높이를 서로 다른 배율로 누른다** — 폭에만 불변이고 **높이는 종횡비에 따라 달라진다**. **폭 비율만이 리사이즈 불변량**이라 층화는 폭 비율로 한다. 예(파렛트 폭 = 이미지폭 20%, 정사각 resize 후):
```
640×480(4:3)  폭 80px, 높이 ×0.750
960×540(16:9) 폭 80px, 높이 ×0.563   ← 같은 물체가 더 납작(폭 같아도 높이 눌림 다름)
```
→ **이 높이 비등방 변화가 바로 종횡비 DR이 필요한 이유.** (이전 문장 "정사각 resize라 640/320·960/480이 동일"은 폭에만 참·높이엔 거짓이라 종횡비 DR 필요성을 스스로 부정 → 정정.) 정사각 resize 코드: `evaluate_on_val.py:170` 448²·`self_train.py:101` image_size²·DOPE `common/utils.py:340` RandomCrop 400².
- 현재 위치: `gen_palletobj_scenarios.py:770` `[(40,64),(64,128),(128,256),(256,384),(384,560)]`(px), `gen_trunc_addon.py:996-1001`. → **폭 비율로 재정의**. **감사도 같은 기준.**
- 기존 bin 환산(문서 보존): `<64 / 64-128 / 128-256 / 256-384 / >384 px(@640)` = `<10% / 10-20% / 20-40% / 40-60% / >60%`(폭 대비).

**③ surf_dist = 해상도 소거 형태로 재작성 (①의 귀결)**
- 비율로 정의하면 배치 수식에서 해상도(W_img)가 소거된다:
```
fx = W_img · focal_mm / sensor_mm
f  = focal_mm · W_pallet / (sensor_mm · Z)     ← W_img 소거 (f = 폭 대비 투영비율)
Z  = focal_mm · W_pallet / (sensor_mm · f)
```
- 현재: `gen_palletobj_scenarios.py:771`·`gen_trunc_addon.py:1001` = `fx*1.3/target_px - 0.7`(fx·해상도 얽힘). → 위 `Z` 형태 **단일 소스로 통합** → **fx·해상도 상호작용이 사라져 Intrinsics DR(lens_mm 랜덤화)과 충돌 안 함.**

**② camera_effects = 효과별로 분리 (일괄 비례 스케일은 틀림)** — `camera_effects.py`
```
blur     → 해상도 비례 스케일  (같은 광학 흐림 = 더 많은 픽셀). blur_px ∝ width/640
noise    → 스케일 안 함        (픽셀당 읽기 노이즈. 리사이즈 때 평균돼 줄어드는 게 물리적으로 맞음)
vignette → 정규화 반경 기준이면 자동 (확인만)
JPEG     → 렌더 해상도 그대로   (8×8 블록이 캡처 해상도 기준)
```

**④ 평가 belief→px SCALE — 이 워크스테이션엔 하드코딩 없음(별도 머신 소관)** [확인, grep]
- 사용자 지적: 평가 코드 `SCALE ×12.8/×9.6`(=640/50, 480/50)이 640×480 하드코딩 → 해상도 바뀌면 belief peak→원본 px 환산이 **에러 없이 조용히 틀림**. 수정 = per-frame 해상도 기반.
- **이 repo 검사 결과 [확인]**: `evaluate_on_val.py:188-190`은 이미 **per-frame**(`h_orig,w_orig=img.shape` → `sx,sy=bw/w_orig,bh/h_orig`, L208 역환산 /sx·/sy) / `run_dope_live.py:271` `proc_scale=400/h`(per-frame·aspect 보존) / `self_train.py:254` `image_size/bw`(448) / `detector.py:558` `×scale_factor(8)`(stride). → **×12.8/×9.6 640-하드코딩은 이 repo에 없음.**
- → 그 하드코딩은 **meas 하네스(별도 머신, [[machine-role-synth-only]])** 소관 → **그쪽에서 per-frame 해상도 기반으로** 고칠 것(원칙만 기록). 이 머신에선 조사·수정 안 함.
- **열린 항목**: meas 하네스에 640 하드코딩 SCALE(×12.8/9.6)이 **실재하는지 미확인** → 그 머신 작업 시 **첫 확인 대상**.

**⑤ live squash = BUG (재분류 2026-07-25 — "프로토콜로 정합" 아님)** [확인]
- train/eval은 **정사각 squash**로 학습·평가(`evaluate_on_val.py:170` 448²·`self_train.py:101` image_size²·DOPE `common/utils.py:340` RandomCrop 400²) = 임의 종횡비를 정사각으로(비정사각일수록 더 눌림, 16:9가 4:3보다 25%↑).
- ⚠️ **버그**: `run_dope_live.py:271` `proc_scale=400/h`(`new_w=w·proc_scale`)는 **종횡비 보존** → 모델이 **학습에서 본 적 없는 형태**를 입력받음 + **높이 기준(400/h)이라 폭이 400과 어긋남**. 프로토콜 문서로 덮을 게 아니라 **코드 버그**.
- **조치**: live를 학습·평가와 **동일한 정사각 squash로 맞출 것**(수정 자체는 규약 phase, 지금은 확인·문서화만).
- **★ live 결과 오염 확인 [확인, 이 repo]**: `run_dope_live.py:450` `cv2.imwrite`만 = **시각 오버레이 이미지만 저장, 정량 지표 미저장**. → 논문 정량표(ADD/PCK/Reproj/5cm5°, `_docs/experiments/experiments.md`)는 **live 산출 아님**(evaluate_on_val=448² 정사각=학습과 동일 squash라 비오염). **미확인 = 별도 머신 소관**: (a) 논문·슬라이드의 **정성 데모 그림**에 live 오버레이가 쓰였는지 (b) **meas 하네스가 정사각 vs 종횡비 보존** 어느 쪽인지 — 그 머신 작업 시 확인.

### 기록만 (조치 불필요)
- **1:1 560×560 = 실제 카메라 대응 없음**(정사각 센서 희귀). anisotropy 1.0 극단을 만드는 **합성 edge case**로 유지하되 **논문에 그 사실 명시**.
- **종횡비 차이는 fx와 달리 추론 때 레터박스 패딩으로 정확히 상쇄 가능** → DR로 가되, **논문 추론 프로토콜에 전처리(undistort → 4:3 정규화 → squash) 명시**(위 ⑤ train↔live 불일치도 이 프로토콜로 정합).

### 파일럿 감사에 추가할 항목
- **종횡비별 프레임 수** (처방 = 실측 대조).
- **projected-size 분포가 정규화 후 4개 종횡비에서 동일한지** (해상도 DR이 크기 분포를 왜곡 안 했는지).
- **anisotropy 계수 분포** (처방 = 실측).
- **anisotropy 분포 × f_target 실측 교차확인** — 종횡비마다 세로 압축률이 달라 **같은 f_target이 다르게 나타날 수 있음**.

---

## 앙각(elevation) 7-bin 처방 — ★잠정 (v2 규약 Phase C, 2026-07-25)

`v2_pipeline.py`의 elevation 층화를 기존 6-bin에서 **7-bin**으로 교체. 25-60° 광역 bin을
25-40 / 40-60 으로 쪼개고, 정보량이 큰 8-25° 작업 구간을 0.40으로 키웠다.
```
bin      [0.5,3) [3,8)  [8,15) [15,25) [25,40) [40,60) [60,80)   합
frac      0.08   0.18   0.20   0.20    0.16    0.10    0.08     1.00
```
- 코드 위치: `v2_pipeline.py` `ELEV_BIN_EDGES` / `ELEV_BIN_FRAC` (상수 옆 주석에도 "잠정" 명시).
  elev×V IPF joint(`build_elev_v_joint`)는 이 7-row marginal을 읽어 자동 재구성된다(감사 확인:
  joint fill = empirical/prescribed ≈ 1.00 전 셀, 통과율 84.9%).
- **★ 잠정 (PROVISIONAL)**: 위 per-bin 비중은 **작업용 추정치**다. **평가셋의 실제 앙각 분포
  (GT pose 기반)를 별도 머신([[machine-role-synth-only]], meas 하네스)에서 측정한 뒤 재조정**
  해야 한다. **이 워크스테이션(합성 전용)에서는 앙각을 측정하지 않는다** — 여기엔 GT pose가 없다.
  → meas 머신 작업 시 "평가셋 앙각 히스토그램 산출 → ELEV_BIN_FRAC 재튜닝"을 처리 항목에 포함.

## projected-size = uniform (기하급수 bin) — 처방 확정 (Phase C)
`PROJ_SIZE_FRAC`는 **uniform 0.20 유지**(변경 없음). 근거: bin 경계가 폭-비율 상 (준)기하급수이고,
폭-비율이 유일한 리사이즈 불변 투영-크기 축(§①)이라 **기하급수 bin을 균등 샘플 = 카메라 거리
log-uniform = 스케일 불변 커버리지**. 즉 "기하 bin 위 균등"은 ASSUMED 자리표시가 아닌 **의도된 처방**.

## luma = exposure_ev 샘플 + luma_actual 감사 (Phase C)
`luma_bin` **쿼터 축 제거**(다운스트림 측정량에 쿼터를 강제하는 건 오류 — 샘플러가 렌더 전 luma를
모름). 대신 제어 입력 **`exposure_ev = U(-3.0, +0.2)` EV**를 샘플(어두운 창고/야간 편향, +0.2로
과노출 상한). `luma_actual`(0-255 평균)은 Layer-3 `measure()`(B3 스텁)에서 측정하고 **감사만**:
bin `<35 / 35-80 / 80-140 / >140`, 각 bin ≥10% 커버 통과(쿼터 강제 없음, `audit_luma_actual()`).
measure가 스텁이라 이번엔 exposure_ev 샘플 + 감사 bin 정의/틀만 마련.

## occluder 측면 오프셋 + accept-time quota (iter-B, 2026-07-25)

iter-A dry-run에서 **large occluder가 사실상 미사용**(사용률 0.3%)이고 near-pallet 강등 45%,
distractor-C1 지배 발견 → 아래 수정. dry-run 40k 재검증(accept 목표) 결과 함께 기록.

- **측면 오프셋(lateral overlap)** `v2_pipeline._occluder_lateral`: occluder는 팔레트 실루엣을
  **A_target 만큼만 겹치면** 됨(전체 실루엣=A_target 아님). `side∈{left,right,bottom,center}`를
  샘플해 그 방향 strip을 덮도록 **(깊이 d_occ, 측면 오프셋)을 함께** 풀어 배치. 큰 물체가 화면
  한쪽만 가리는 현실적 가림이 가능 → **large 사용률 0.3%→29.9% 회복**(성공 판정 기준).
  center=옛 contained(작은 물체). 레거시 solve는 `_occluder_legacy`로 보존(A-B 토글
  `LATERAL_OFFSET_ENABLED`). **★large 가중치는 낮추지 않음**(large가 안 쓰이는 게 문제였음).
- **카메라 클리어런스=배치 제약**(사후 게이트 아님): `d_occ ≥ 0.2m + occluder 시선방향 half-extent`를
  밴드 하한에 반영 → **distractor-C1 2927→18**로 소멸.
- **near-pallet 밴드 0.70→0.55**(상한 0.90 유지) + 깊이를 밴드 내에서 직접 샘플 → **강등률 45%→0%**.
- **accept-time quota**: `sample_frame`은 quota 읽기만(pure), `advance_quota`는 **accept 시에만**
  (`generate_accepted`). → **accept 분포가 처방과 정확히 일치**, 폐기 셀은 재타겟(attempted 분포만 왜곡).
- 검증(40k accept, seed 7000): 통과율 LEGACY 77.5% → LATERAL **81.6%**(≥70 충분, 인위적 상승 아님).
  잔여: C2(중심 가림) 1349→3382 상승 — lateral 큰 occluder의 **월드 AABB 보수성**(3D ray-AABB가
  실루엣보다 큼). 안전한 과폐기라 통과율 문제 없음. 필요 시 C2를 2D 실루엣-중심픽셀 검사로 정합(후속).

## 다른 축 (다음 phase, 상세 스펙 별도 — 여기선 이름만)
- Visibility Gate (G3/G5) · Placement f_target 역산 · Intrinsics DR(lens_mm) · Illumination DR
- 레이블 스키마: `pallet_type` · `material_variant` · `occlusion_fraction` · `edge_map` · `scene_preset`
- distractor 선택 배선: `DISTRACTOR_NAMES`(옛 8, `Sketchfab_model`×3 unknown-license 포함) → 가용화된 209 CC0/CC-BY 풀로 (Placement 소관, 릴리스 전 필수).
