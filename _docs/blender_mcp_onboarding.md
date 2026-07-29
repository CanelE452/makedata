# Blender 합성데이터 생성 — LLM 온보딩 (Pallet 6D Pose, v2 파이프라인)

> **이 문서의 독자 = 이 코드베이스를 처음 보는 LLM.** Blender MCP 또는 Blender CLI(standalone)로
> 팔레트 6D 포즈용 합성 데이터를 **처음 생성**할 때 이 문서 하나로 실전 재현 + 함정 회피 + 과거 실패
> 답습 방지를 목표로 한다. 모든 경로는 절대경로 기준(cwd = `E:\CODING\GitHub\FoundationPose`).
>
> 작성 2026-07-25. 이 문서는 **읽기 전용 온보딩**이며 기존 문서를 수정하지 않는다. 소스:
> `_docs/history/*`, `_docs/method/v2_domain_randomization.md`, `_docs/preprocessing/keypoint_definition.md`,
> `_docs/dataset_license_ledger.md`, 프로젝트/agent memory, `scripts/data_prep/blender/*`.
>
> **동작 단정 태그**: `[확인]` = 실행흐름 추적 또는 실제 실행으로 검증. `[추정]` = 주석·변수명·관례 추론(미검증).

---

## 0. 30초 요약 (TL;DR)

- **목표**: 팔레트를 감싸는 **9-point cuboid keypoint**(8 코너 + centroid)를 라벨로 하는 DOPE keypoint 학습셋을 Blender로 렌더한다. 추가로 **12kp E-단면**(앞면 개구부) 라벨과 **holdout mask**(full-audit 5-stage 또는 public 2-stage, §3.1.1)를 함께 생성한다.
- **아키텍처**: v2 파이프라인은 **3-layer**. `sample_frame`(순수, bpy-free) → `solve_placement`(순수 해석기하) → `realize/measure/render/label`(Blender측). 앞 2개는 Blender 없이 dry-run 감사가 가능하다.
- **프로덕션 씬**: `data/pallet/blender_scene/synth_data_scene_portable.blend` (342MB, NoAI 목재 제거 재-bake 완료, distractor 209 내장). **경로는 리터럴로 쓰지 말고 registry 키 `production_scene` 으로 조회한다.** 원본 `synth_data_scene.blend` 는 절대경로 228건이 박혀 있어 이 머신 전용이며, 이제 **보존용 rollback source** 로만 남는다(수정 금지, Stage 2-C1).
- **실행 2경로**: MCP 세션이 살아있으면 MCP로, 아니면 **Blender CLI standalone**(`blender -b <blend> --python <script>`)로. 대량/헤드리스 렌더는 항상 CLI.
- **환경 함정 3종**: 콘솔 cp949 → `PYTHONUTF8=1` 필수 / base conda에 **cv2 없음**(PIL+numpy만) / `conda run` libmamba 에러 → **직접 python.exe 경로** 사용.
- **★ 생성 후 "완료" 선언 전 반드시**: **전수 오버레이**를 눈으로 확인한다(샘플만 보면 magenta 배경 오염을 놓친다 — 이번 세션 실제 사고).

---

## 1. 개요 · 환경

### 1.1 목표
KS T-11형 팔레트(1100×1100×150mm)의 6D 포즈를 **keypoint 기반(DOPE)** 으로 추정한다. 팔레트는 비대칭 직육면체라 keypoint 방식이 적합. 라벨은:
- **9-point cuboid**: 8 코너 + centroid (Y=UP convention, camera-facing 동적 0123). → `_docs/preprocessing/keypoint_definition.md`.
- **12kp E-단면**: 앞면(FRONT) 개구부 기반 외곽 4 + 개구부 4×2. `efront_kp12.py`. FRONT가 닫힌-2홀 또는 bottom_open 면일 때만 `kp12_valid=True`.
- **holdout mask**: full-audit = M0~M4 5종 / public = M0·M4 2종 (아래 §3.1.1). 옛 `_unocc`/`_aftercargo`/`_visible` 접미사는 폐지됨.

### 1.2 conda / Python 환경
```
용도                         인터프리터                              비고
──────────────────────────────────────────────────────────────────────────────────────
학습·평가·PyTorch            conda env `pallet-pose`                 cv2 있음
Blender 스크립트(bpy측)      Blender 내장 Python (standalone)        bpy, mathutils
bpy-free 분석/오버레이/감사   C:\Users\User\anaconda3\python.exe      base env: PIL+numpy+matplotlib
                             (= base conda, ★cv2 없음)               만. cv2 필요하면 pallet-pose
```
- **★ `conda run -n base ...` 금지**: 이 머신에서 libmamba 플러그인 에러 발생 → **직접 절대경로** `C:\Users\User\anaconda3\python.exe`로 실행. [확인, 이번 세션]
- **★ base env엔 cv2 없음**: 이미지 저장은 `PIL.Image.fromarray`, 배열은 numpy. cv2를 쓰려면 `pallet-pose` env. [확인]
- matplotlib(base)는 **한글 글리프 깨짐**(DejaVu Sans) → 차트 주석은 **영문**으로.

### 1.3 Blender
- 버전 **Blender 5.1** [확인]. 실행파일(Windows): `/c/Program Files/Blender Foundation/Blender 5.1/blender.exe`.
- 렌더 엔진: 프로덕션 렌더는 **Cycles**(`v2_realize.render()` = `scene.cycles.samples=16`). floor/mask/일부 진단은 EEVEE-Next 사용 이력. **magenta(missing texture / GPU upload fail)가 나오면 Cycles로 전환**(과거 해법, §5C).
- **MCP 우선 vs CLI 대안**:
  - **MCP** (`mcp__blender__execute_blender_code`, `get_viewport_screenshot` 등): Blender GUI + MCP addon 세션이 **살아있을 때만**. 인터랙티브 씬 편집·즉석 검증에 유리.
  - **CLI standalone** (`blender -b <blend> --python <script.py> -- <args>`): MCP 세션이 없거나 대량/헤드리스 렌더일 때. **v2 본 파이프라인은 전부 CLI**로 돈다. `-b`=백그라운드(GUI 없음).
  - ⚠️ **잔류 GUI 세션 주의**: 사용자가 GUI로 blend를 열어둔 blender.exe(과거 PID34104)가 있을 수 있음 — **kill 금지**. 헤드리스 렌더는 별도 프로세스로 뜬다.

### 1.4 필수 환경변수
```
PYTHONUTF8=1            ★ cp949 콘솔이 em-dash(—)·한글 print에서 UnicodeEncodeError → 필수.
                          스크립트 안에서도 sys.stdout.reconfigure(encoding="utf-8", errors="replace") 방어.
PYTHONIOENCODING=utf-8  동일 목적(콘솔 인코딩).
CUDA_MODULE_LOADING=LAZY  (Isaac Sim 계열 DLL 충돌 회피 — 레거시. Blender 경로엔 필수 아님)
PYTHONUNBUFFERED=1      장시간 렌더 로그 실시간 flush.
```

### 1.5 OS (Win / Ubuntu 양쪽)
`.claude` 설정은 두 OS 공유. **작업 시작 시 실제 OS 확인**. 이 워크스테이션은 Windows 11.
- bash 경로 함정: **`E:\...` 백슬래시는 quote 깨짐** → `/e/CODING/GitHub/FoundationPose/...` forward-slash 사용. [확인, 이번 세션]
- **Blender `--out` 등 경로는 절대경로 필수**: 상대경로면 Blender 렌더는 `C:\`(실행 cwd) 기준, PIL은 `E:\` 기준으로 갈려 FileNotFound. [확인, trunc_addon]

### 1.6 이 머신의 역할 = 합성 데이터 생성 **전용**
평가셋(outside/night/noapril, GT pose)·학습 코드·meas 하네스는 **별도 머신**. → 앙각(elevation) GT 분포 측정, belief→px SCALE, err_180 회전지표 등은 **여기서 조사하지 말고 "범위 밖"**으로 처리. `real_data/` 1924장은 평가셋 아님(self-training unlabeled 풀). 출처: `machine-role-synth-only` memory.

---

## 2. 파이프라인 구조 · 방법 (v2 규약)

### 2.1 3-layer 순수함수 분리 (order-4)
파일: `scripts/data_prep/blender/v2_pipeline.py`(순수 layer 1·2, **bpy import 0**) + `v2_realize.py`(layer 3, bpy측 전부). `v2_pipeline`의 realize/measure/render/label 4스텁이 **lazy import(`import v2_realize`)로 위임** → dry-run은 Blender 없이 순수하게 돈다.

```
sample_frame(rng, quota_state) -> (FrameSpec, Picks)   PURE, bpy-free. Layer-1(층화 샘플)
solve_placement(spec, assets)  -> Plan | Reject        PURE 해석기하. Layer-2(카메라·가림 역산)
realize(plan)   / measure(scene) / render(scene) / label(spec,plan,meas)   Blender. Layer-3
```
- Layer-1·2는 **bpy를 절대 import하면 안 된다**(dry-run 순수성). 결정성: 같은 seed → 같은 FrameSpec.
- **왜 이렇게?**: 렌더는 비싸다(~4.5s/frame, 40k = ~2일). dry-run이 렌더 0으로 처방-분포·통과율을 먼저 검증한다.

### 2.2 도메인 랜덤화(DR) 축 전체 목록
처방 상수 위치: `v2_pipeline.py` PRESCRIPTION 블록(L72~167). 스펙: `_docs/method/v2_domain_randomization.md`.
```
축                     처방                                                      quota?
────────────────────────────────────────────────────────────────────────────────────────
elevation (7-bin)      [0.5,3)0.08 [3,8)0.18 [8,15)0.20 [15,25)0.20 [25,40)0.16   ★JOINT
                       [40,60)0.10 [60,80)0.08   ← ★잠정(평가셋 GT로 재튜닝, 별도머신)  (elev×V)
V (in-frame 코너수)     4:0.15 5:0.25 6:0.30 7:0.20 8:0.10                          ★JOINT
scene_preset           indoor0.25 outdoor-day0.30 outdoor-night0.25 random-mix0.20  marginal
projected-size (폭비율) <10%/10-20%/20-40%/40-60%/>60% 각 uniform 0.20             marginal
azimuth                30° × 12bin uniform                                          marginal
f_target (가림)         0:0.40 [0.10,0.20)0.25 [0.20,0.35)0.20 [0.35,0.45)0.15      marginal
position_mode          near-pallet0.60 near-camera0.40 (f_target>0일 때만)           conditional
cargo on/off           50/50                                                        marginal
exposure_ev            U(-3.0, +0.2) EV  ← ★야간 커버리지 결정, 하한 상향 금지        (샘플입력)
aspect/resolution      4:3 640×480(0.50) 16:9 960×540(0.25) 3:2 720×480(0.15)       marginal
                       1:1 560×560(0.10)  [(선택)1280×960 ≤5%]
fx                     70% U[300,700]px random / 30% D435i anchor(605.9065)         marginal
material_variant       config weight (pallet_type 종속, 비균일)                     free-random
distractor size_class  large/road 3.0 · medium 2.0 · indoor 1.0 · small 0.6(가중)   가중선택
occluder side          left/right/bottom/center (측면 오프셋)                        (배치)
luma_actual            측정만 — 쿼터 없음. bin <35/35-80/80-140/>140 각 ≥10% 커버 감사   audit-only
```
- **elevation × V만 2-D JOINT**(저앙각→저V=truncation 물리결합, IPF/Sinkhorn로 두 marginal 동시 강제). 나머지는 marginal greedy deficit-fill.
- **luma는 quota 축이 아님**: 렌더 후에야 아는 measured 량 → 쿼터 강제 불가. `exposure_ev`(제어입력)만 샘플, luma는 감사만.
- **★ setting override 금지**: `exposure_ev` 하한 −3.0, `ELEV_BIN_FRAC` 7-bin, `F_TARGET_FRAC`, `G5_LUMA_MIN=12.0`는 **사용자 누적 결정**. 통과율이 낮아도 임의 조정 금지(§5A ③④).

### 2.3 accept-time quota (★중요 설계)
- `sample_frame`은 quota를 **읽기만**(pure). 커밋(`advance_quota`)은 **호출부가 accept 시에만** 한다(`generate_accepted`).
- 효과: **accepted set 분포가 처방과 정확 일치**, reject된 셀은 자기교정(재타겟). sample-time에 커밋하면 폐기된 셀이 처방을 왜곡. (이번 세션 iter-A→iter-B 수정, §5A ⑥)

### 2.4 실측배정 (target ≠ actual → actual bin, 안전게이트만 폐기)
- solve의 target(예 V_target=4)과 렌더 실측(V_actual=6)이 다르면 **폐기하지 않고 actual bin으로 배정**한다. 이게 v4 시절 통과율 28% 붕괴(v_gate_reject 14405)를 해소한 핵심.
- **오직 안전게이트(G1~G5)만 하드 폐기**한다:
```
G1  V_vis >= 4              (in_frame & occlusion<0.5인 코너 4개 이상)  ★yield 지배 인자
G2  occluder 있으면 ext_occ_corners ∈ [1,4]   (없으면 통과)
G3  area_visible(M4) >= 0.5 * area_amodal(M0)  (팔레트 절반 이상 보임)
G4  centroid in-frame
G5  luma_pallet(VISIBLE 마스크 영역) >= 12.0   ← ★프레임 전체 luma 아님(§5A ③)
```
- net yield ≈ solve_pass(0.80) × gate_pass(0.40) ≈ **31~40%** → N장 뽑으려면 ~2.5~3.2N 렌더. 40k 스루풋 경고.
- ★ **binding constraint = G1(저앙각 grazing)**, G5 아님. 야간 손실 주범도 저앙각(elevation 7-bin 재튜닝은 별도머신 소관).

### 2.5 데이터 경로 registry (★ 문자열 조립 금지)

```
config/synthetic/pallet_paths.yaml               runtime source of truth (경로 정의)
scripts/data_prep/blender/pallet_data_paths.py   resolver (bpy import 없음)
```

```python
import pallet_data_paths as pdp
scene = pdp.get("production_scene")      # data/pallet/blender_scene/synth_data_scene_portable.blend
hdri  = pdp.get("hdri_root")             # data/pallet/assets/lighting/hdri/library
```

```bash
python scripts/data_prep/blender/pallet_data_paths.py            # 전 경로 감사 (exit 1 = missing 있음)
python scripts/data_prep/blender/pallet_data_paths.py --key hdri_root
PALLET_DATA_ROOT=/mnt/data/pallet python ...                     # root 만 override
```

`data/pallet/manifests/*.csv` 는 조사 시점 snapshot 이지 runtime config 가 아니다.
경로를 바꾸려면 `pallet_paths.yaml` 을 고치고 `--audit` 으로 확인한다.
현행 registry 값 표는 `_docs/data_pallet_layout.md` 참조.
**★ 2026-07-29 Stage 2-B**: 이름은 `archive/` 인데 현역이던 자산 3종
(`archive/textures_wood` · `archive/textures_floor` · `archive/trunc_addon_v1_pilot`)을
`assets/materials/{pallet,floor}/` 와 `reference/golden_overlay/` 로 **이동 완료**했다.
아직 원위치인 것: `distractors/` · `background/`(원본 ZIP 포함) · `blender_scene/`. 상세는
`reports/data_pallet_cleanup/stage2b/final_report.md`.
**★ 2026-07-29 Stage 2-C1**: production `.blend` 의 절대경로 228건을 `//../distractors/...`
상대경로로 바꾼 **portable 사본**을 만들고 registry `production_scene` 을 그쪽으로 옮겼다.
원본 `synth_data_scene.blend` 는 한 바이트도 바뀌지 않았고 rollback source 로 보존된다.
`factory_yard_2k.hdr` 의 깨진 다른-워크스페이스 경로 1건도 정확한 파일로 repoint 했다
(sha256 대조 확인, 렌더 pool 은 여전히 이름으로 제외되어 28 로 불변).
`distractors/` 이동은 여전히 남아 있다 — 이제 사유가 "절대참조"가 아니라
"상대참조 356건 rebase 필요"다. 상세: `reports/data_pallet_cleanup/stage2c1/final_report.md`.

### 2.5 재현 커맨드 (파이프라인 단계별)
```bash
# (a) dry-run 층화 검증 (Blender 없음, ~45s, 통과율 84.9%)
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/v2_pipeline.py --n 40000 --seed 7000
# (b) dry-run 감사 리포트 (a~f 차트 + report) -> data/pallet/v2_dryrun_audit/
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/audit_v2_dryrun.py

# (c) B3 자산체크 (첫 실렌더 5프레임 + magenta 서브테스트) -> data/pallet/_v2_b3_check/
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b \
  "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
  --python scripts/data_prep/blender/_b3_asset_check.py -- \
  --out data/pallet/_v2_b3_check --seed 7000 --n 5

# (d) 200장 캘리브 (target vs actual 6종 분석) -> data/pallet/_v2_calib_200/
"/c/.../blender.exe" -b "$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)" \
  --python scripts/data_prep/blender/_v2_calib_200.py -- --seed 7000 --n 200
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/_v2_calib_200_analyze.py  # matplotlib(base)

# (e) 파일럿 2k (chunk launcher: 200장/fresh Blender, OOM 방지, resume) -> data/pallet/_v2_pilot_2k/
#     mask 레이아웃 선택: 진단용은 --mask-profile full-audit (기본), 공개용은 --mask-profile public
bash scripts/data_prep/blender/run_pilot_2k.sh 2000 200 7000    # TOTAL CHUNK SEED

# (f) 파일럿 감사 (★overlay 폴더 선-clear 후) -> _v2_pilot_2k/audit/
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/_v2_pilot_audit.py \
  --dir data/pallet/_v2_pilot_2k --n_overlay 30

# (g) ★전수 오버레이 (canonical) -> <dataset>/overlay/
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/overlay_v2_detailed.py \
  --dir data/pallet/_v2_pilot_2k --style archive
# (g-2) 진단용 FRONT/REAR overlay -> <dataset>/overlay_frontrear_debug/
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/overlay_v2_detailed.py \
  --dir data/pallet/_v2_pilot_2k --style frontrear-debug
# (구) 파일럿 당시 전수 오버레이 스크립트 (재현용, canonical 아님)
C:/Users/User/anaconda3/python.exe scripts/data_prep/blender/_v2_pilot_overlay_all.py \
  --dir data/pallet/_v2_pilot_2k
```
- **★ 본 렌더(40k)는 반드시 사용자 승인 후**. 파일럿·캘리브까지가 무-승인 상한. commit도 명시 요청 전 금지.

---

## 3. 파일 구조 (★ rgb / overlay / mask / labels 분리)

### 3.1 v2 파일럿 출력 레이아웃 (`data/pallet/_v2_pilot_2k/`)
```
_v2_pilot_2k/
├── rgb/            f{idx:04d}_rgb.png          최종 post-process된 RGB (Cycles 16spp + camera_effects)
├── labels/         f{idx:04d}_label.json       DOPE camera_data + objects (아래 스키마)
├── mask/           f{idx:04d}_m0.png ~ _m4.png  ★full-audit 전용 5-stage holdout (아래 3.1.1)
├── mask_amodal/    f{idx:04d}.png              ★public 전용 M0 (target-only amodal)
├── mask_visible/   f{idx:04d}.png              ★public 전용 M4 (final visible)
├── overlay/        f{idx:04d}.png              ★canonical overlay (--style archive)
├── overlay_frontrear_debug/  f{idx:04d}.png    보조 진단 overlay (--style frontrear-debug)
├── audit/          overlay_perm_azimuth/ night/ kp12/ + pilot_audit_report.json
├── pilot_records.json(.jsonl)  처방+실측 메타(프레임당 즉시 flush, resume용)
├── driver_summary.json         accepted/rendered_ok/solve_pass
└── logs/           chunk_NNN.log
```
#### 3.1.1 ★ mask 규약 (2026-07-28 현행 — `mask_profiles.py` 가 단일 정의)

`--mask-profile` 로 **두 레이아웃 중 하나**를 고른다. 목적이 다르므로 서로를 대체하지 않는다.

```
public (공개 배포용)                     full-audit (진단용, 기본값)
──────────────────────────────────────────────────────────────────────────────────
mask_amodal/f{idx:04d}.png  = M0        mask/f{idx:04d}_m0.png  = M0
mask_visible/f{idx:04d}.png = M4        mask/f{idx:04d}_m1.png  = M1
                                        mask/f{idx:04d}_m2.png  = M2
M1~M3 는 **렌더 자체를 하지 않는다**       mask/f{idx:04d}_m3.png  = M3
(렌더 후 삭제가 아님 → 프레임당 3패스 절약)  mask/f{idx:04d}_m4.png  = M4

f_total  = exact (1 − M4/M0)             f_total  = 1 − M4/M0
f_static  = None  ← 미측정                f_static  = 1 − M1/M0
f_cargo   = None  ← 미측정                f_cargo   = (M1−M2)/M0
f_context = None  ← 미측정                f_context = (M2−M3)/M0
f_explicit= None  ← 미측정                f_explicit= (M3−M4)/M0
occlusion_decomposition_available=false  occlusion_decomposition_available=true
```

**M0~M4 의미** (각 stage = holdout 렌더, 팔레트=white emission·나머지=black·world=black BW):

```
M0  target-only amodal        비팔레트 전부 hide → 팔레트 완전 실루엣
M1  static scene 반영          정적 배경만 남김 (cargo/context/explicit hide)
M2  static + cargo            (context/explicit hide)
M3  static + cargo + context  (explicit hide)
M4  final visible             아무것도 hide 안 함 = 실제 카메라가 보는 것
```

**★ None 과 0.0 을 혼동하지 말 것**

```
None  = 미측정 (public 에서 source 별 분해를 애초에 렌더하지 않았다)
0.0   = 측정했고 그 source 의 가림이 없었다
```

public 셋에서 `f_static` 등을 0 으로 채우면 "가림이 없었다"는 **거짓 정보**가 된다.
같은 이유로 public 셋에서 M1~M3 파일이 없는 것은 **결측이 아니라 정상**이다 —
분석기(`analyze_v2_scene_logic.py`)는 레이아웃을 자동 감지해 이를 결측으로 세지 않는다.

경로를 직접 조립하지 말고 `mask_profiles.py` 를 쓴다:

```python
import mask_profiles as MP
MP.detect_profile(root)                       # 'public' | 'full-audit'
MP.mask_stages(profile)                       # ('m0','m4') | ('m0'..'m4')
MP.frame_mask_paths(root, idx, profile)       # {stage: path}
MP.resolve_frame_mask_path(root, idx, 'm0')   # 레이아웃 몰라도 찾아주는 호환 조회
MP.decompose(areas, profile)                  # (분해값, invariant)
```

### 3.2 label JSON 스키마 (`v2_realize.label()`, L719~)
```
{
  "camera_data": {
    "width","height","resolution":[W,H],"aspect_ratio","aspect_label",
    "intrinsics": {fx,fy,cx,cy},          # per-frame K (cx=W/2, cy=H/2)
    "lens_mm",                            # = fx * SENSOR_WIDTH / W  (Intrinsics DR)
    "fx_mode": "random"|"anchor",
    "location_worldframe","look_worldframe",
    "scene_preset","exposure_ev",
    "background_asset","floor_mode","floor": {floor_texture,uv_scale,tint,...}|null
  },
  "objects": [{
    "class":"pallet","name":"Pallet_0..3","source_asset",
    "keypoint_convention":"camera_dynamic_0123_v4",
    "location","quaternion_xyzw","euler_angles":{pitch,yaw,roll},"pose_transform"(4x4),
    "projected_cuboid":[[u,v]×8], "projected_cuboid_centroid":[u,v],
    "cuboid":[[x,y,z]×8],                  # world 3D, perm_v4 재정렬 순서
    "perm_v4":[8], "front_visibility_cos","facing_margin","dimensions_m":{width,height,depth},
    "v2_labels": {
      "pallet_type","material_variant_target","material_variant_actual",
      "position_mode",
      "elev_bin_target","elevation_deg_target","elevation_deg_actual",   # actual = atan2 재측정
      "azimuth_deg_target","proj_size_bin_target","proj_size_ratio_target",
      "v_target","V_actual","V_vis_actual","ext_occ_corners_actual",
      "f_target","f_target_bin","f_cargo","f_occ","f_total","f_actual_bin",  # ★실측배정 bin
      "occlusion_fraction":[9],           # per-corner 연속 가림 0..1 (9-ray 양자화, binary 아님)
      "cargo_on","n_cargo_actual",
      "exposure_ev","luma_actual","luma_pallet_actual",
      "occluder_asset","occluder_placed",
      "mask_area_amodal","mask_area_visible","mask_profile",
      "occlusion_decomposition_available",
      # full-audit 만: "mask_area_after_static","mask_area_after_cargo","mask_area_after_context"
    },
    "safety_gates": {G1..G5, "all_pass"}
  }]
}
```
- **12kp E-단면**은 `efront_kp12.py`가 `compute_annotation_v4`에 배선되어 `kp12_valid`/`front_face_type`/`kp12_in_frame`/`kp12_visible` 필드를 추가한다(additive). 9kp cuboid 라벨은 불변.
- ⚠️ `material_family` 필드는 (이번 파일럿에서) **전 프레임 None**(미채움, §5A ⑫) — 재질 축 집계는 `material_variant_target`(17종, pallet_type 종속)으로 조인해야 함.
- ⚠️ `camera_data.floor`가 **None인 프레임 있음**(HDRI-floor 모드) → `.get()` / dict 체크 필수.

### 3.3 legacy 레이아웃 참고 (`data/pallet/reference/golden_overlay/trunc_addon_v1_pilot/`)
과거 생성기는 **rgb+json을 루트에 colocate**(`000000.png` + `000000.json`) + `mask/`·`overlay/`·`audit_eye/` 하위폴더. 파일명 = `{i:06d}` 6자리. v2는 `f{idx:04d}_rgb.png` 4자리 접두형으로 바뀜. 오버레이 파일명 형식은 두 방식 모두 **`{번호}.png`**(zero-pad).

---

## 4. Overlay 생성법 (★ archive 방식 준수)

### 4.1 스타일 규약 (2026-07-28 현행 — canonical = `--style archive`)
9kp cuboid를 2D projected_cuboid에 그린다:
```
canonical (--style archive)  ->  <dataset>/overlay/            ★정본
  edge          world X/Y/Z 축별 색 (255,80,80)/(80,220,80)/(80,130,255)
  keypoint      ID별 0~8 색, centroid 는 흰색, off-screen 은 (130,130,130)
  pose axis     pose_transform 회전 + K 투영, z>0 일 때만
  panel         좌상단 in-image 정보 패널 (외부 패널 없음)
  legend        우하단 축 범례
  canvas        입력 RGB 와 동일 크기 (full-width header 없음, mask contour 없음)

secondary debug (--style frontrear-debug)  ->  <dataset>/overlay_frontrear_debug/
  FRONT face (0-1-2-3)  두꺼운 빨강 (255,30,30) / REAR (4-5-6-7) 얇은 파랑 / connector 노랑
  외부 진단 패널 + audit header + M0/M4 contour
  → convention·gate 진단 전용. **canonical 이 아니다.**

canonical 정본 reference: `data/pallet/reference/golden_overlay/trunc_addon_v1_pilot/`
  (2026-07-29 Stage 2-B 에서 archive/ 밑에서 여기로 이동. registry key `golden_overlay_reference`)
  tests/test_overlay_archive_trunc_style.py 가 이 폴더의 overlay/000000.png 를 픽셀 비교한다.
코너 점                     0~3 빨강 · 4~7 파랑, 흰 테두리, 옆에 번호 0..7
centroid                    초록 점 (0,255,0)
헤더(상단 검은 띠)           f{idx} {pallet} elev(actual) az(target) front_is_camera_near
                            all_pass front_visibility_cos facing_margin
```
- `front_is_camera_near` = FRONT centroid(코너0-3 평균)가 REAR(4-7 평균)보다 카메라에 가까운가. 정상이면 True.

### 4.2 ★ 전수 생성 필수 (샘플만으론 못 잡는다)
- **이번 세션 실제 사고**: 파일럿 2000장 중 magenta 배경 74장이 샘플 30장에 안 걸림. **전수 오버레이 육안**으로만 발견(kp/luma 감사는 놓침, §5A ①). → **"완료" 선언 전 canonical `overlay/` 전수를 눈으로 훑는다**.
- 재생성은 **bpy-free**(PIL+numpy만) → 렌더 없이 disk의 labels+rgb만으로 그린다. 재렌더/Blender 불필요.
- **함정: audit 스크립트는 overlay 폴더를 안 비운다**(makedirs exist_ok) → 옛 run 잔재와 혼재. 재실행 전 `rm overlay_*/*.png`.
- **함정: stock audit의 perm 오버레이는 azimuth bin 0~2만 뽑는다**(`sorted(...,(azimuth_bin,idx))[:30]`) → azimuth 다양성 0. perm 규칙 검증(FRONT가 방위 추적)엔 az 0~11 round-robin 재생성 필요.

### 4.3 손상/저장 관련 방어
- **truncated PNG 방어**: `ImageFile.LOAD_TRUNCATED_IMAGES = True`(디스크 손상 프레임도 부분 오버레이). 렌더/디스크 결함으로 실제 손상 발생(§5A ⑩).
- **손상 검출**: 전수 스캔 시 `Image.open`만으론 truncated 못 잡음 → `.convert("RGB")` + `np.asarray`(=디코드 강제)해야 검출.
- **Claude Read API가 오버레이 PNG를 거부**할 수 있음(PIL 저장 메타 이슈) → `PIL.Image.fromarray`로 재저장하면 육안 로드 가능(§5A ⑪).

---

## 5. ★ 과거 실패 사례 전부 (증상 → 원인 → 수정 → 교훈)

> 같은 실수를 반복하지 않기 위한 핵심 섹션. **총 40+ 사례.** 5A = 이번 세션(2026-07-25), 5B~5E = history/agent-memory 누적.

### 5A. 이번 세션 (2026-07-25) — 소스 미기록분 포함

**① magenta 배경 오염 (전수 오버레이로만 발견)**
- 증상: 파일럿 2000장 중 배경이 magenta(R>180&G<90&B>180)인 프레임 74장(3.7%), 그중 **45장이 all_pass 통과**(학습셋 5.6% 오염).
- 원인: 누락 텍스처 = Blender missing-texture magenta. 안전게이트(G1~G5)가 기하/밝기만 봐서 못 잡음. B3의 "바닥×glTF magenta 기하검출"은 이 케이스(배경 에셋 텍스처 누락)를 미포착.
- 수정(권고): magenta 픽셀비 게이트 추가 + **전수 오버레이 육안 필수**. kp/luma 감사만으론 놓침.
- 교훈: **샘플 감사는 배경 오염을 못 본다. 생성 후 전수 오버레이를 눈으로.** 게이트는 "보이는 팔레트"만 보고 배경 품질은 안 본다.

**② launcher 무한루프 중복 launch**
- 증상: resume 오판으로 두 chained job이 각각 `while :` 무한루프 → 7루프 누적 + 동시 Blender OOM.
- 원인: `run_pilot_2k.sh`가 `while :`로 done_cnt<TOTAL이면 계속 재launch. 두 잡을 동시에 걸면 서로의 진행을 못 보고 각자 돎.
- 수정: **★ TaskStop이 detached bash-loop + Blender children를 안 죽인다 → process-tree 명시 kill 필요**. (데이터 자체는 무결 = 연속·double-render 낭비만.)
- 교훈: 무한루프 launcher는 **단일 인스턴스**만. 중단은 부모 bash가 아니라 **자식 트리(blender.exe 포함)까지** 명시 kill.

**③ G5 dark 폐기 버그**
- 증상: 야간(어두운 배경) 프레임에서 팔레트가 보이는데도 폐기.
- 원인: G5가 `luma_frame`(프레임 전체 평균)으로 판정 → 까만 야간 배경 때문에 평균이 낮아 폐기. "노출 −3.0으로 어둡게 만든 걸 G5가 어둡다고 스스로 버리는" 모순.
- 수정: `luma_pallet` 마스크를 **unocc → visible**로 교체 + `g5 = (lp is None or lp>=12)`(luma_frame 조건 제거, 임계 12 불변). `v2_realize.measure()` L642~647 / `safety_gates()` L695.
- 교훈: 게이트 통과율이 낮으면 **판정 "대상"(전체 프레임 vs 영역 마스크)을 먼저 의심**. 단 실효과는 +2장(+1%p)뿐 — 진짜 binding은 G1(저앙각). 게이트 낭비를 setting 조정으로 덮지 말 것.

**④ 노출 override 실수 (setting override 금지)**
- 증상: G5 dark 폐기 24% 회수하려 노출 하한 −3.0→−2.0 제안 → 사용자 기각.
- 원인: 노출 −3.0은 **야간 HDRI 5종 커버리지 결정**(이번 세션 명시 결정). 상향하면 야간 도메인이 사라짐.
- 수정: 제안 철회, 노출 불변. G5는 판정 로직(대상)만 수정.
- 교훈: **setting(노출·elevation·f_target·게이트 임계) override 금지** — 사용자 누적 결정. CLI/agent가 "가중치·하한 조정"을 제안하면 방향(만든 걸 버리는 모순)부터 확인.

**⑤ centroid ≠ origin → 앙각 Δ13° 오염**
- 증상: solve의 elevation target 52.9° vs 실렌더 actual 39.3°(Δ13°).
- 원인: `solve_placement`는 카메라를 팔레트 **centroid=[0,0,H/2] 기준**으로 배치하는데, realize가 팔레트 **object origin**을 world원점에 두면 USD 팔레트의 origin↔centroid 오프셋만큼 어긋남. 방치 시 elev·V·f 층화 전부 오염.
- 수정: realize에서 실측 centroid0 구해 `delta = centroid0 − [0,0,H/2]`, cam_pos·cam_look·occluder_center에 delta 적용. → 200장 전부 Δ=+0.00.
- 교훈: 순수 solve의 좌표 가정(centroid 기준)과 Blender realize의 배치(origin 기준)가 다를 수 있다. **정렬버그는 실렌더 target-vs-actual로만 드러난다.**

**⑥ quota sample-time → accept-time**
- 증상: dry-run에서 폐기된 셀이 처방 분포를 왜곡(attempted만 봄).
- 원인: `sample_frame`이 quota를 sample 시점에 커밋 → reject 프레임도 카운트.
- 수정: `sample_frame`을 pure-read로, `advance_quota`는 `generate_accepted`가 **accept 시에만** 호출. → accepted 분포가 처방과 정확 일치.
- 교훈: 층화 쿼터는 **accept 시점에 전진**해야 accepted set이 처방과 맞는다.

**⑦ occluder delivery median 0 (C2 2D 실루엣 정합 필요, 보류)**
- 증상: occluder-only 가림(f_occ)이 target의 median 0.00, 82%가 0.5x 미만(mean −0.176).
- 원인: lateral offset 배치가 A_target 근사(bbox·fill_ratio·orientation)라 실루엣 밖으로 빗나감. bbox ≠ 실메시 실루엣.
- 수정: scalar 보정으론 median-0 못 고침 → 근본은 occluder 2D 실루엣 중심픽셀 정합(C2). **사용자 지시로 보류**. f_actual은 cargo가 지배(+27.6pp), occluder 기여 미미라 치명적 아님.
- 교훈: under-deliver를 f_actual quota-feedback으로 덮으면 렌더 낭비 trap(high-f를 계속 요구). measured 량은 audit-only.

**⑧ 환경 함정 (재확인)**
- cp949 콘솔 → `PYTHONUTF8=1` + `sys.stdout.reconfigure(...)`. cv2가 base env에 없음 → `PIL.Image.fromarray`. `conda run -n base` libmamba 에러 → 직접 `anaconda3\python.exe`. (§1.2)

**⑨ transcript 정리로 오래된 agent SendMessage 재개 불가**
- 증상: compact/정리 후 기존 3d-expert 스레드에 SendMessage 재개 실패.
- 수정: 새 위임(새 스레드)으로 진행.
- 교훈: 장기 agent 스레드는 compact 후 끊길 수 있음 — 재개 대신 새 위임 + memory 인계.

**⑩ f1661 원본 손상 (truncated PNG)**
- 증상: `f1661_rgb.png`가 헤더는 OK(720x480)인데 픽셀 디코드 실패("unrecognized data stream").
- 원인: 렌더/디스크 defect.
- 수정: `ImageFile.LOAD_TRUNCATED_IMAGES = True`로 부분 로드. 검출은 `.convert("RGB")`+`np.asarray`.
- 교훈: 전수 스캔은 디코드 강제해야 손상 잡힌다. (§4.3)

**⑪ 오버레이 PNG를 Claude Read API가 거부**
- 증상: PIL이 저장한 오버레이 PNG를 Read(이미지)로 못 엶.
- 원인: PIL 저장 메타 이슈 [추정].
- 수정: `PIL.Image.fromarray(np.asarray(im))`로 재저장 → 육안 로드 가능.
- 교훈: 육안 검증용 이미지는 fromarray 재저장으로 정규화.

**⑫ material_family 라벨 전 프레임 None**
- 증상: `objects[0].v2_labels`의 재질 family 필드가 전부 None(미채움).
- 수정: 재질 축 집계는 `material_variant_target`(17종)으로 조인. (family 채우기는 미해결 TODO.)
- 교훈: 라벨 필드가 None-채움일 수 있음 — 집계 전 실제 값 존재 확인(선언 ≠ 실제).

**⑬ mask 분리 시 mv 6000개 loop timeout + 접미사 폴더 혼동**
- 증상: 마스크를 하위폴더로 옮기는 `mv` 6000개 loop가 2분 timeout. 접미사 제거로 폴더 혼동.
- 수정: **일괄 처리**(shutil 배치). 접미사 **유지**. (당시 규약 기준 — 현행 mask 레이아웃은 §3.1.1)
- 교훈: 대량 파일 이동은 loop 금지, 일괄. resume이 파일명 접미사에 의존하므로 접미사 제거 금지. (§3.1)

### 5B. 기하 · convention 실패 (누적)

**compute_perm_v4 FRONT(0123) 축-고정 버그** (2026-07-03, `blender_math.py:195~`)
- 증상: 평평 직사각 팔레트에서 FRONT(코너0-3)가 카메라 방위와 무관하게 한 축쌍(±Y)에 고정. trunc_addon 300프레임 전부 FRONT=월드 ±Y. az 90/270에선 FRONT가 카메라를 등짐(front_cos 음수).
- 원인: step3이 top4를 "평행 opposite-edge 쌍 1개"로 split 후 그 2면만 비교. 직사각 top face는 평행쌍이 2개(±W, ±D, 둘 다 |cos|=1 동률)라 `parallel[0]` 채택이 부동소수/입력순서로 결정. facing_margin(맞은편 차이) 게이트가 못 잡음.
- 수정: 평행 split 제거 → top4를 centroid 방위각 정렬해 4옆면 생성, **모든 옆면 normal-facing 비교 argmax=FRONT, +2=REAR**. facing_margin 정의를 맞은편→**인접(최상−차상)** 면 차이로 변경.
- ★ 공유 함수라 trunc_addon/addon_v1/v4/topview/preview10 **전부 영향**. 게이트 있는 v4도 45° 코너혼동 통과(2860 중 548=19.2% 오배정) → fix 후 grazing-gate만으로 0%. **baked JSON은 재생성 전엔 옛 라벨**(함수 수정으로 안 바뀜).
- 교훈: **grazing(front_cos↓)과 corner-ambiguity(facing_margin↓)는 다른 축.** 임계는 섭동실험으로 정할 것(추측 금지).

**FACING_MARGIN_MIN 재튜닝 0.60 → 0.15** (2026-07-03)
- 위 margin 정의 변경(맞은편→인접, 스케일 작아짐)으로 옛 0.60 과도(passRate 32.9%, 2/3 버림). ±3° 섭동 sweep 77760뷰로 unstable margin max=0.080 측정 → **0.15 채택**(leak 0 + 2x buffer, passRate 83.5%). `gen_dataset_v4.py:95`·`gen_topview_test.py:76`·`gen_preview10.py:78`. ⚠️ 이후 2026-07-24 다시 `0.15→6.0°`로 재해석(방위각 규칙 교체) — **v2 파일럿에서 재검증 필요**(≤60°만 검증됨).

**preview10 FRONT-near 오판 (평평 팔레트 far면을 FRONT로)** (2026-06-15, `blender_math.py:189`)
- 증상: 평평 팔레트는 far면이 2D 면적이 더 크게 투영(frame01 far 5113 > near 3987px) → far를 FRONT로 오판.
- 수정: `cam_pos`가 있으면 2D 면적이 아니라 **항상 3D 거리로 near=FRONT** 판정.
- 교훈: 투영 2D 면적은 원근 때문에 near/far와 역전될 수 있다. near/far는 3D로.

**preview10 connector X-cross** (2026-06-15)
- 증상: connector(0-4 등) 4쌍이 X 교차(frame06/07).
- 원인: step7이 rear-top을 image-x로 정렬 → far face라 front-LEFT의 depth짝이 RIGHT짝에 연결.
- 수정: rear를 front id0과의 **3D 거리**로 짝지음(id4=C[id0] 최근접). oracle은 connector-connector cross만 신호(평평 팔레트는 total 12-edge cross가 정상에서도 2 나옴).

**odd V(5,7) 저앙각 도달불가 → trunc_addon rear collapse** (2026-07-03, `gen_trunc_addon.py`)
- 증상: 저앙각 lateral clip으론 홀수 V 도달불가(수직쌍 제거=even만).
- 수정: vertical/diag 모드 + `generate_frame` 내 adaptive alpha search(`count_in_frame_only`로 렌더 없이 target_v 적중). **elevation-PRIMARY planner**(elev bin deficit 먼저 → 그 bin에서 target_v를 deficit×feasibility). 비싼 렌더 전 geometry-only `_probe_dist.py`로 두 marginal 예측검증.
- 교훈: 두 축(elev, V)이 물리결합이면 marginal 독립 샘플이 충돌. JOINT 또는 PRIMARY-conditional로.

**DOPE keypoint convention = object-frame canonical (NOT camera-facing)** (2026-06-03)
- 학습/GT 코너순서는 **object-frame canonical**(659 GT 중 657에서 HEIGHT edge가 최단 = 고정좌표계). `make_pallet_keypoints_3d`(OpenCV)는 X부호 반대 0↔1 swap 버그. 새 필터는 카메라앞면0123 가정 금지.
- ⚠️ v2 라벨은 `camera_dynamic_0123_v4`(카메라-facing) — 학습 로더 convention과 **분리 주의**. 평가는 order-free Hungarian(cube automorphism 48, 반사 포함)으로 흡수.

**evaluate_on_val: flat 팔레트 EPnP 발산 → ITERATIVE 필수** (2026-06-03)
- 평평 팔레트는 EPnP가 발산(43px) → `cv2.solvePnP ITERATIVE`(4.9px). convention 삼중 불일치로 reproj 130px+ 버그 → order-free `annotate_pnp.solve_pose`. dims 1.1/1.3/0.11.

**squash 제거는 회귀** (2026-06-08)
- 사용자 가설(squash가 indoor 코너 망침)을 데이터로 반증: no-squash가 indoor cuboid를 collapse(13→35px). **squash 유지**.

### 5C. 재질 · magenta · 렌더링 실패 (누적)

**팔레트 머티리얼 검정/청록** (2026-06-16)
- 원인: `config/synthetic/blender.yaml` `appearance.pallet_color_variants` base_color가 거의 검정(0.02~0.10) → dark base가 HDRI cast에 지배돼 청록. USD 머티리얼 아님.
- 수정: config 교체(단색칠 → Polyhaven 실사 plank albedo+normal+rough 텍스처, MULTIPLY tint). USD/코드 무수정(geometry 기반이라 라벨 무영향).
- ⚠️ 함정: group명이 "plastic"인데 Pallet_1이 매핑 → plastic 배열에 목재값을 채워야 함(이름에 속지 말 것). scene_3 청록은 faded_gray 변종+cool HDRI 착시(→aged_brown).

**GSO OBJ가 Blender에서 magenta** (2026-07-24)
- 원인: GSO의 MTL `map_Kd texture.png`가 `meshes/` 옆을 가리키나 실제 png는 `../materials/textures/`(경로 불일치).
- 수정: 텍스처 직접 load + `node_tree.clear()` 후 Principled+ImageTexture 새 배선 + **EEVEE_NEXT**(Workbench TEXTURE는 깨진 노드 집어 계속 magenta). GSO=Z-up·metric·정립(재정규화 불필요, 접지만).
- 교훈: magenta = missing texture. MTL 경로를 실제 png 위치로 repoint.

**바닥 항상 회색 = BG_industrial 아스팔트가 FloorRandPlane 가림** (2026-06-16)
- 원인: `randomize_background`가 매프레임 BG_industrial 재노출 → 자체 `Floor*_Asphalt_0`(z≈0)이 fresh plane(z=−6mm)을 가림.
- 수정: `FLOOR_BG_GROUND_HIDE`+`_hide_bg_ground()`(캐시 없이 **매프레임** hide, `randomize_floor`에서 호출). `floor_and_mask.py`.
- 교훈: 매프레임 재노출되는 배경 지오메트리는 **매프레임** hide(캐시 no-op 주의).

**base_m 그레이팅 함정** (2026-06-16)
- `synth_data_scene.blend`의 `Base_base_m_0`은 평면이 아니라 도랑 그레이팅 → 실사 텍스처가 슬랫에 쪼개져 회색 줄무늬. "단색은 바뀌는데 텍스처는 안 바뀜" = 메시 UV 문제. 해법 = fresh plane drop.

**FloorPlane z=−6mm** (2026-06-16)
- fresh 평면을 z=0 아닌 **−6mm**로 내려야 on-ground silhouette raycast 점이 오occlusion 판정 안 함 → 게이트 보존(pass 3.6→13.2%). distractor는 각자 z=0 접지(상대높이 보존).

**HDRI magenta / mall_parking_lot 보라 / factory_yard decode 실패** (2026-06-15)
- 배경 magenta 원인: parking_lot 얇은 patch void 노출(→industrial만+안쪽 배치), HDRI `mall_parking_lot`(보라 cast)·`factory_yard`(decode 실패 magenta)는 **`_DROP` 목록으로 제외**. factory_yard는 파일 복구됐어도 파이프라인 `_DROP`에 여전히 포함(un-drop하려면 Blender magenta 테스트 필요).

**EEVEE GPU upload 실패 magenta → Cycles** (2026-06-15)
- EEVEE에서 GPU 텍스처 upload 실패 magenta는 reload로 못 고침(+per-frame I/O hang) → **Cycles로 전환**.

**바닥 UV scale 비현실** (2026-06-17)
- 바닥 패턴이 팔레트(1.1m)보다 크면 비현실 → `FLOOR_UV_SCALE_RANGE=(1.5,3.0)`(metres_per_tile 중심 2~2.5).

### 5D. Blender CLI · 환경 · 검증 실패 (누적)

**Blender `cmd &` 백그라운드 신뢰 불가** (2026-06-15)
- 증상: `blender ... &`가 echo만 exit0, 자식은 계속 돎 → stale JSON 오판.
- 수정: **foreground 동기 실행**. 실종료는 tasklist/PID로 확인. (재현 위해 드라이버에서 `random.seed` 필수 — `randomize_background/hdri/floor`는 전역 unseeded random.)

**Blender 씬 undo 실패** (2025-03-25)
- MCP undo 불안정으로 씬 손실. **작업 전 .blend 저장이 유일한 안전장치.** 삭제 전 사용자 확인.

**RNA 무효화** (2026-05-19)
- Blender 5.1 standalone에서 오브젝트 참조가 무효화 → **매번 이름으로 재조회**(`bpy.data.objects.get(name)`). Collection hide vs occluder duplicate 분리(`scene.collection`으로 unlink/link).

**CleanVisiiDopeLoader path = [list] 필요** (2026-06-04)
- `path_dataset`에 str 넣으면 글자 iterate → `/` 탐색 PermissionError. **[list]로**.

**Distractors_v2 컬렉션 exclude → 조용히 0 distractor** (2026-07-25, B3)
- 증상: view-layer excluded collection은 per-object visibility가 켜져도 **에러 없이 0 distractor 렌더**(silent, fallback 안 걸림).
- 수정: `force_distractors_v2_enabled()`(realize 첫줄) = layer-collection un-exclude + `coll.hide_render/hide_viewport=False`. 209 roots 확인.
- 교훈: silent-0 리스크. 첫 실렌더 전 반드시 render-enable 확인.

**magenta 기하검출은 top-down + Standard view transform 필요** (2026-07-25, B3)
- 증상: magenta 검증 카메라를 accepted plan에서 뽑으면 배경 벽을 봐 magenta 0(Filmic 톤맵이 어둡게).
- 수정: **top-down 명시 카메라 (0.6,0.6,5)→(0,0,0.05) + `view_transform='Standard'`**(바닥만 프레임, emission magenta crisp). 이름 안 걸리는 새 지면도 **기하검출**(`_hide_ground_geometric`: XY>10m & Zthick<0.3m & |cz|<0.15)로 hide.

**image-quadrant 사인검사 false-violation** (2026-06-16)
- 평평 팔레트에서 "image-quadrant 사인검사"가 54/120 false-violation → **simple-quad + 0top/0left**가 올바른 판정. flat 팔레트는 비스듬 정상이므로 rect_ok/aspect를 PASS 게이트로 쓰지 말 것.

### 5E. 라이선스 · 검증(verify 누락) 실패 (누적)

**B1 NoAI 목재 — USD 격리만으론 미해소, blend 재-bake 필수** (2026-07-24)
- 증상: NoAI 목재 P2/P3(`scene_2/3.usd`)를 USD 격리했는데도 렌더에 계속 출력.
- 원인: 프로덕션 blend에 **Pallet_2/3 형상이 baked** + 과거 로더가 불일치 팔레트를 삭제 않고 `Legacy_*`로 rename만 한 **중복본**까지 잔존.
- 수정: 3부 = ①USD 격리 ②**blend 재-bake**(NoAI 완전 제거) ③로더 repoint(`usd_import`→.glb 분기). + legacy-purge(로더를 rename→**삭제-on-성공**으로). 새 목재 J-Toastie(CC-BY3.0)·EUR(CC0).
- 교훈: **격리 ≠ 해소.** baked blend는 재-bake해야. "삭제 안 하고 rename"이 누적 오염 원인.

**B2 Isaac occluder 오탐 (이름매칭 단정 금지)** (2026-07-24)
- 증상: "OCCLUDER=NVIDIA Isaac"이라 [확인] 태그로 블로커 등재.
- 원인: `WetFloorSign_01`이 Isaac `S_WetFloorSign.usd`와 **파일명만 충돌**. 프로덕션 blend 157MB grep 결과 Isaac 지문 0, 실제 occluder = Poly Haven CC0.
- 수정: B2 종료(오탐). occluder = CC0(5) + Sketchfab CC-BY(8) + 불명(3).
- 교훈: **이름 일치를 증거로 단정 금지(verify 누락).** 실행흐름/grep으로 실증해야 [확인].

**GSO manifest finalize 재실행 금지** (2026-07-24)
- 옛 finalize가 `sf__`를 gso로 오분류 → manifest는 **utf-8-sig append-only**로만.

**floor 미검증 5종** (2026-07-24)
- 미검증 5종(tile_white 등)을 동등 Poly Haven CC0로 **내용 교체**(파일명 유지 = `floor_and_mask.py:34` 참조만이라 코드 무변경). 원본 백업 `textures_floor/_replaced_originals/`.

---

## 6. 저작권 · 라이선스

> 정본: `_docs/dataset_license_ledger.md`(URL 36개+), `_docs/attribution_cc-by_appendix.md`(CC-BY 부록),
> `_docs/attribution_bundling_plan.md`(B5 동봉 계획) + per-폴더 `SOURCES.txt`/`LICENSE.txt`.
> **종합판정: 현재 공개불가(N)** — 잔여 = B5(attribution 동봉)·B6(isaac 제외) + occlusion 선택 재배선.

### 6.1 에셋군별 출처 · 라이선스
```
에셋군                 개수   출처                라이선스        표기의무   공개  URL/원장
──────────────────────────────────────────────────────────────────────────────────────────────
HDRI 환경광            30     Poly Haven          CC0 1.0         불요       Y     hdri/SOURCES.txt
                                                                                  polyhaven.com/a/<id>
배경 3D glTF (근경)     2     Sketchfab           CC-BY 4.0       ★필수(B5)  Y*    industrial(BazukaliKartal)
                              modular_industrial                                  parking_lot(Veterock)
                              /parking_lot                                        ledger 그룹4에 URL
distractor Poly Haven  65     Poly Haven          CC0 1.0         불요       Y     manifest url 열
distractor GSO         128    Google Scanned Obj  CC-BY 4.0       ★필수(B5)  Y*    Gazebo Fuel GoogleResearch
                              (Gazebo Fuel)                                        app.gazebosim.org/...
distractor Sketchfab   16     Sketchfab           CC-BY 4.0       ★필수(B5)  Y*    appendix §1(16 URL 인라인)
팔레트 P0/P1(플라스틱)  2     Sketchfab           CC-BY 4.0       ★필수(B5)  Y*    P1=billy3D(URL有) P0=단서만
팔레트 J-Toastie(목재)  1     Poly Pizza          CC-BY 3.0       ★필수(B5)  Y*    poly.pizza/m/XSKlcrzyi6
팔레트 EUR(목재)        1     BlenderKit(LensError) CC0 1.0        불요       Y     blenderkit .../751202c6
팔레트 stringer         1     Poly Pizza(Quaternius) CC0 1.0      불요       Y     poly.pizza/m/cUAsYHDqfD
바닥 텍스처             14     Poly Haven          CC0 1.0(확정)   불요       Y     textures_floor/SOURCES.txt
목재 텍스처              9     Poly Haven          CC0 1.0         불요       Y     polyhaven.com/a/<name>
occluder(blend baked)  19     Poly Haven CC0(5)   CC0+CC-BY+불명   일부★     Y*    B2 오탐정정
                              +Sketchfab CC-BY(8)                                 불명3=재배선 대상
                              +불명(3)
pallet_full.obj / real_data   본인 촬영           본인 IP         불요       Y     -
```
- `*` = CC-BY라 **저작자표시 동봉 시** 공개 가능(B5). CC0는 표기 불요(권장).
- **표기 형식**(B5): `"<title>" by <author>, licensed under CC BY <ver>, <url>. Modifications: <변경>.`
- **가한 변경(CC-BY 명시 의무)**: USD 팔레트 = import·scale/orient 정규화·씬 baking(P0 emissive 10000→0) / GSO·Sketchfab = upright·metric·접지 정규화·재익스포트 / 배경 = import·placement 조정 / J-Toastie = 비-metric→실치수 uniform-scale·glb 재추출.

### 6.2 ★ 아직 확인 못한(불명) 항목
```
항목                          상태        조치
──────────────────────────────────────────────────────────────────────────────
occluder 불명 3종             출처 미확정  209 CC0/CC-BY 풀로 재배선하면 자동 해소
P0 canonical source URL       단서만       정확 재발견 보장 안 됨(B5 표시 위해 확정 권장)
현 DISTRACTOR_NAMES(8) 중     ★라이선스   실 가림 렌더에 unknown-license가 baked →
  Sketchfab_model ×3          불명         209 풀로 재배선 필수(릴리스/v2 재생성 전)
Isaac Sim 창고 에셋           라이선스     License FAQ vs Additional License 상충 →
  (대체 CC0 탐색만)           상충          다운로드 보류(사용자 결정)
factory_yard HDRI un-drop     미검증        Blender magenta 테스트 필요(현재 _DROP)
```

### 6.3 공개 블로커(B1~B6) 상태
```
B1  NoAI 팔레트         해소   blend 재-bake + 로더 repoint + legacy-purge (파이프라인 클린)
                              단 구 데이터셋(v4/v4_split/4pallet_mask)은 NoAI baked → v2 재생성 필요
B2  Isaac occluder      종료   오탐(이름충돌). occluder=Poly Haven CC0
B3  USD↔Sketchfab 매핑   해소   렌더로 P0/P1=플라스틱·P2/P3=목재 확정, 목재 2종 교체로 무의미화
B4  floor 14종          해소   14/14 Poly Haven CC0 확정
B5  CC-BY attribution   ★미해결 배포물에 ATTRIBUTION.md 통합 동봉 필요(패키징 시)
B6  isaac_assets 제외   ★미해결 data/pallet/isaac_assets/(NVIDIA EULA) 배포 트리서 제외
                              (_DISTRIBUTION_EXCLUDE.txt 등재됨)
+   occlusion 선택 재배선 ★미해결 DISTRACTOR_NAMES(8)→209 CC0/CC-BY 풀 (v2 재생성 전 필수)
```
- **즉시 공개 가능(클린)**: HDRI 30·PH distractor 65·목재 9·floor 14·EUR/stringer·재-bake blend·pallet_full.obj·real_data.

---

## 7. 함정 · 팁 체크리스트

### 7.1 자원(process / device) lifecycle
- [ ] 무한루프 launcher(`run_pilot_2k.sh`)는 **단일 인스턴스만**. 두 잡 동시 = 중복 launch + OOM(§5A ②).
- [ ] 중단은 **process-tree 명시 kill**(detached bash-loop + blender.exe children). TaskStop만으론 자식 안 죽음.
- [ ] 대량 렌더는 **chunk(200장/fresh Blender)** — mid-run 재시작 없으므로 단일세션 2k+는 OOM 리스크.
- [ ] 사용자 GUI blender.exe(잔류 PID)는 **kill 금지**. 헤드리스 렌더는 별도 프로세스.
- [ ] `blender ... &` 백그라운드 신뢰 불가 → foreground 동기 + PID 확인(§5D).

### 7.2 환경 / 실행
- [ ] `PYTHONUTF8=1` + stdout reconfigure(cp949 em-dash/한글).
- [ ] bpy-free 분석은 `C:\Users\User\anaconda3\python.exe` 직접(`conda run` 금지, cv2 없음→PIL).
- [ ] bash 경로는 forward-slash `/e/CODING/...`(백슬래시 quote 깨짐).
- [ ] Blender `--out` 등 **절대경로**(상대면 Blender=C:\ / PIL=E:\ 갈림).
- [ ] `random.seed` 명시(randomize_background/hdri/floor는 전역 unseeded → 재현 안 됨).

### 7.3 검증 (★ verify 빼먹지 말 것)
- [ ] **★ 생성 후 전수 오버레이 육안**(샘플만으론 magenta 배경 오염 놓침, §5A ①). canonical `overlay/` 전수 (`--style archive`).
- [ ] 오버레이 폴더 재실행 전 `rm overlay_*/*.png`(옛 run 잔재 혼재).
- [ ] 손상 PNG 검출은 `.convert("RGB")+np.asarray`(디코드 강제). `LOAD_TRUNCATED_IMAGES=True` 방어.
- [ ] 겹침(관통) 판정은 눈이 아니라 **BVH mesh intersection / ray casting 코드**로(썸네일로 "겹침 없음" 단정 금지 — CLAUDE.md 규칙).
- [ ] "완료" 선언 전 실제 이미지 로드: 물체 부유/관통/겹침, overlay keypoint가 팔레트에 정확 대응, 배경 오염 없음. **로그 vis 수치만으로 판단 금지.**
- [ ] target vs actual 편향은 **실렌더 캘리브(200장)**로만 드러남(centroid 정렬버그 등, §5A ⑤). dry-run은 못 봄.
- [ ] 실측배정 감사: `f_target_bin`(target)과 `f_actual_bin`(measured)을 **둘 다** 집계 — target만 보면 왜곡 숨김(bin3 target15%→actual43%).

### 7.4 절대 건드리지 말 것 / 확인 후에만
- [ ] setting override 금지: `EXPOSURE_EV_RANGE(-3.0,0.2)`·`ELEV_BIN_EDGES` 7-bin·`F_TARGET_FRAC`·`G5_LUMA_MIN=12.0`(사용자 결정, §5A ④).
- [ ] `ORIENTATION_OVERRIDES` 수정 금지(검증 완료값, keypoint_definition.md §4).
- [ ] Isaac Sim 스크립트의 `ORIENTATION_OVERRIDES`도 동일(scripts/data_prep/CLAUDE.md).
- [ ] commit / push는 명시 요청 전 금지. `git add -A/.` 금지(변경 파일만 개별 스테이징).
- [ ] blend 편집 전 **저장 먼저**(MCP undo 불안정, §5D).
- [ ] 3D/렌더링 비자명 문제는 **3d-expert agent에 먼저 상담**(좌표변환·projection·cuboid 라벨링·camera convention).

### 7.5 관련 문서 · agent 인계
- 파이프라인 DR 스펙: `_docs/method/v2_domain_randomization.md`
- keypoint: `_docs/preprocessing/keypoint_definition.md` / kp12: `pallet-efront-12kp-scheme` memory
- 라이선스: `_docs/dataset_license_ledger.md` + attribution 2종
- 히스토리: `_docs/history/2026-07-24.md`, `2026-07-25.md`(v2 규약 구현 전 과정)
- agent 경험: `agents/3d-expert/memory/MEMORY.md`(인덱스, 40+ 로그) + `agents/data-engineer/memory/`
- ★ 3D/CV 작업(좌표계·projection·cuboid·convention)은 **3d-expert**, 데이터 수집·EDA·정제·검증은 **data-engineer**에 위임.
