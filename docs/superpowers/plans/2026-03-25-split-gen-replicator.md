# gen_replicator_data.py 모듈 분리 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2800줄짜리 `gen_replicator_data.py`를 5개 모듈로 분리하여 유지보수성 향상

**Architecture:** Isaac Sim standalone 스크립트 특성상 `SimulationApp` 초기화와 `import` 순서가 중요. 메인 진입점(`gen_replicator_data.py`)에서 SimulationApp 생성 후, 나머지 모듈은 pure Python + USD/numpy 의존성만 가짐. 모듈 간 순환 의존 없도록 단방향 의존 구조 유지.

**Tech Stack:** Python, USD (pxr), numpy, PIL, Isaac Sim Replicator API

---

## 파일 구조

```
scripts/data_prep/
├── gen_replicator_data.py    # 메인 진입점 (SimulationApp, main, argparse)
├── sdg_config.py             # 모든 상수/설정값
├── sdg_math.py               # 수학 헬퍼 (euler, quat, bbox, camera matrix)
├── sdg_scene.py              # 씬 구성 (warehouse, props, 조명, 텍스처, 머티리얼)
├── sdg_distractors.py        # 디스트랙터/적재물 배치, 색상
├── sdg_usd_xform.py          # USD xformOp 직접 제어, prim path resolve
└── sdg_annotation.py         # NDDS JSON 작성, visibility 계산, keypoint
```

### 의존 관계 (단방향)
```
gen_replicator_data.py
  ├── sdg_config.py          (상수만, 의존 없음)
  ├── sdg_math.py            ← sdg_config
  ├── sdg_annotation.py      ← sdg_math, sdg_config
  ├── sdg_usd_xform.py       ← sdg_math (pxr 의존)
  ├── sdg_scene.py           ← sdg_config, sdg_usd_xform (pxr, rep 의존)
  └── sdg_distractors.py     ← sdg_config, sdg_usd_xform, sdg_math
```

### 각 모듈 내용

| 모듈 | 원본 라인 범위 | 함수/상수 | 예상 라인 |
|------|---------------|-----------|-----------|
| `sdg_config.py` | 137-366 | 모든 상수 (경로, 카메라, 색상, 에셋 목록 등) | ~230 |
| `sdg_math.py` | 528-635 | `euler_to_rotation_matrix`, `rotation_matrix_to_quat_xyzw`, `rotation_matrix_to_euler_deg`, `build_camera_matrix`, `build_view_matrix`, `_canonical_corners` | ~110 |
| `sdg_annotation.py` | 637-745, 670-745 | `_compute_visibility`, `write_ndds_json` | ~110 |
| `sdg_usd_xform.py` | 2113-2430 | `_resolve_rep_prim_path`, `_set_pose_usd`, `_set_pose_usd_rep`, `_set_camera_look_at_usd`, `_randomize_lights_usd`, `_set_light_attrs_usd`, `_set_distractor_visible`, `_apply_distractor_color` | ~320 |
| `sdg_scene.py` | 368-530, 745-1700 | 텍스처 생성/분류, `compute_model_info`, glTF변환, warehouse/props 로딩, `setup_scene`, `register_randomizers`, `_apply_color_to_all_materials`, floor/wall 텍스처 | ~900 |
| `sdg_distractors.py` | 1911-2110 | `_select_camera_mode`, `_sample_camera_pose`, `_jitter_look_at`, `_sample_floor_distractor_pos`, `_randomize_distractors` | ~200 |
| `gen_replicator_data.py` | 1-136, 2433-2910 | SimulationApp 초기화, `generate_data`, `generate_test_scenarios`, `main` | ~600 |

---

### Task 1: `sdg_config.py` — 상수/설정 분리

**Files:**
- Create: `scripts/data_prep/sdg_config.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_config.py` 생성**

원본 line 137-366의 모든 상수를 새 파일로 이동:
- 경로 상수 (`SCRIPT_DIR`, `PROJECT_ROOT`, `GLTF_DIR`, `USD_CACHE_DIR`, etc.)
- 이미지/카메라 설정 (`IMAGE_WIDTH`, `CAMERA_CONSTRAINTS`, etc.)
- 디스트랙터 설정 (`CARGO_OCCLUSION_TIERS`, `DISTRACTOR_CATEGORIES`, etc.)
- 팔레트 색상 (`PALLET_COLORS`)
- 배경 설정 (`WAREHOUSE_BG_PROBABILITY`, `HDRI_DIR_LOCAL`, etc.)
- 텍스처 설정 (`FLOOR_DIFFUSE_RANGE`, `PROCEDURAL_TEX_DIR`)

- [ ] **Step 2: `gen_replicator_data.py`에서 상수 제거, import 추가**

```python
from sdg_config import *
```

- [ ] **Step 3: Isaac Sim에서 실행 테스트**

`--num_frames 1`로 1프레임 생성하여 import 에러 없는지 확인.

- [ ] **Step 4: Commit**

```bash
git add scripts/data_prep/sdg_config.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract constants to sdg_config.py"
```

---

### Task 2: `sdg_math.py` — 수학 헬퍼 분리

**Files:**
- Create: `scripts/data_prep/sdg_math.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_math.py` 생성**

원본 line 528-635 이동:
- `euler_to_rotation_matrix`
- `rotation_matrix_to_quat_xyzw`
- `rotation_matrix_to_euler_deg`
- `build_camera_matrix` (sdg_config에서 기본값 import)
- `build_view_matrix`
- `_canonical_corners`

의존: `numpy` only.

- [ ] **Step 2: `gen_replicator_data.py`에서 제거, import 추가**

```python
from sdg_math import (euler_to_rotation_matrix, rotation_matrix_to_quat_xyzw,
                       rotation_matrix_to_euler_deg, build_camera_matrix,
                       build_view_matrix, _canonical_corners)
```

- [ ] **Step 3: 기존 호출 코드가 정상 동작하는지 확인**

- [ ] **Step 4: Commit**

```bash
git add scripts/data_prep/sdg_math.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract math helpers to sdg_math.py"
```

---

### Task 3: `sdg_annotation.py` — annotation/visibility 분리

**Files:**
- Create: `scripts/data_prep/sdg_annotation.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_annotation.py` 생성**

원본에서 이동:
- `_compute_visibility` (line 637-667)
- `write_ndds_json` (line 670-743)

의존: `sdg_math` (`euler_to_rotation_matrix`, `_canonical_corners`, `build_view_matrix`), `sdg_config`, `numpy`.

- [ ] **Step 2: `gen_replicator_data.py`에서 제거, import 추가**

- [ ] **Step 3: Commit**

```bash
git add scripts/data_prep/sdg_annotation.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract annotation/visibility to sdg_annotation.py"
```

---

### Task 4: `sdg_usd_xform.py` — USD xformOp 제어 분리

**Files:**
- Create: `scripts/data_prep/sdg_usd_xform.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_usd_xform.py` 생성**

원본에서 이동:
- `_rep_prim_path_cache`, `_distractor_prim_path_cache`, `_xformable_cache` (모듈 레벨 캐시)
- `_resolve_rep_prim_path` (line 2116-2135)
- `_resolve_distractor_prim_path` (line 2137-2144)
- `_set_pose_usd` (line 2150-2209)
- `_set_pose_usd_rep` (line 2212-2215)
- `_set_camera_look_at_usd` (line 2218-2291)
- `_randomize_lights_usd` (line 2293-2356)
- `_set_light_attrs_usd` (line 2358-2394)
- `_set_distractor_visible` (line 2396-2411)
- `_apply_distractor_color` (line 2413-2430)

의존: `sdg_math` (`euler_to_rotation_matrix`, `rotation_matrix_to_quat_xyzw`), `pxr` (Gf, UsdGeom, UsdShade, UsdLux).

- [ ] **Step 2: `gen_replicator_data.py`에서 제거, import 추가**

- [ ] **Step 3: Commit**

```bash
git add scripts/data_prep/sdg_usd_xform.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract USD xform ops to sdg_usd_xform.py"
```

---

### Task 5: `sdg_distractors.py` — 디스트랙터/적재물/카메라 배치 분리

**Files:**
- Create: `scripts/data_prep/sdg_distractors.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_distractors.py` 생성**

원본에서 이동:
- `_select_camera_mode` (line 1911-1920)
- `_sample_camera_pose` (line 1922-1954)
- `_jitter_look_at` (line 1956-1962)
- `_sample_floor_distractor_pos` (line 1964-2003)
- `_randomize_distractors` (line 2005-2110)

의존: `sdg_config` (상수), `sdg_usd_xform` (`_set_pose_usd_rep`, `_apply_distractor_color`), `numpy`.

- [ ] **Step 2: `gen_replicator_data.py`에서 제거, import 추가**

- [ ] **Step 3: Commit**

```bash
git add scripts/data_prep/sdg_distractors.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract distractor/camera placement to sdg_distractors.py"
```

---

### Task 6: `sdg_scene.py` — 씬 구성 분리

**Files:**
- Create: `scripts/data_prep/sdg_scene.py`
- Modify: `scripts/data_prep/gen_replicator_data.py`

- [ ] **Step 1: `sdg_scene.py` 생성**

원본에서 이동:
- `_generate_procedural_textures` (line 368-500)
- `_classify_textures` (line 503-517)
- `_pick_weighted_texture` (line 520-525)
- `compute_model_info` (line 745-851)
- glTF 변환 (`convert_gltf_to_usd`, `_verify_textures`, `convert_all_gltf`) (line 857-961)
- `_pick_pallet_color` (line 967-979)
- warehouse/props 로딩 (`_try_load_warehouse`, `_list_nucleus_dir`, `_try_load_props`) (line 981-1113)
- `setup_scene` (line 1115-1698)
- `register_randomizers` (line 1701-1767)
- `_apply_color_to_all_materials` (line 1775-1816)
- `_to_omni_uri` (line 1825-1834)
- `_change_floor_wall_textures` (line 1836-1909)

의존: `sdg_config`, `sdg_math`, `sdg_usd_xform`, `pxr`, `rep`, `numpy`, `PIL`.

**주의:** `setup_scene`이 가장 큰 함수(~580줄). 이 안에서 distractor bbox 측정, 머티리얼 풀 생성 등 다양한 작업이 있으나, 일단 통째로 이동하고 추후 필요시 추가 분리.

- [ ] **Step 2: `gen_replicator_data.py`에서 제거, import 추가**

남은 `gen_replicator_data.py`에는:
- SimulationApp 초기화 (line 1-136) — **이동 불가** (import 순서 의존)
- `generate_data` (line 2433-2693)
- `generate_test_scenarios` (line 2695-2805)
- `main` (line 2807-2910)

- [ ] **Step 3: 1프레임 생성 테스트**

```bash
python scripts/data_prep/gen_replicator_data.py --num_frames 1 --output_dir /tmp/test_split
```

- [ ] **Step 4: Commit**

```bash
git add scripts/data_prep/sdg_scene.py scripts/data_prep/gen_replicator_data.py
git commit -m "refactor: extract scene setup to sdg_scene.py"
```

---

### Task 7: 최종 정리 및 `__init__.py`

**Files:**
- Modify: `scripts/data_prep/gen_replicator_data.py` (최종 정리)
- Modify: `scripts/data_prep/CLAUDE.md` (문서 업데이트)

- [ ] **Step 1: `gen_replicator_data.py` 정리**

- 불필요한 빈 줄, 주석 정리
- import 순서 정리
- 최종 라인 수 확인 (~600줄 목표)

- [ ] **Step 2: `scripts/data_prep/CLAUDE.md` 업데이트**

모듈 분리 구조 반영:

```markdown
## 모듈 구조 (gen_replicator_data)

| 모듈 | 역할 |
|------|------|
| `sdg_config.py` | 모든 상수/설정값 (경로, 카메라, 색상, 에셋) |
| `sdg_math.py` | 수학 헬퍼 (euler, quat, bbox, camera matrix) |
| `sdg_annotation.py` | NDDS JSON 작성, visibility 계산 |
| `sdg_usd_xform.py` | USD xformOp 제어, prim path resolve |
| `sdg_scene.py` | 씬 구성 (warehouse, props, 조명, 텍스처) |
| `sdg_distractors.py` | 디스트랙터/적재물 배치, 카메라 포즈 |
| `gen_replicator_data.py` | 메인 진입점 (SimulationApp, generate_data, main) |
```

- [ ] **Step 3: Commit**

```bash
git add scripts/data_prep/
git commit -m "refactor: finalize module split, update docs"
```

---

## 주의사항

1. **Isaac Sim import 순서**: `SimulationApp` 생성 전에 `pxr`, `rep` 등을 import하면 crash. 따라서 `sdg_scene.py` 등은 `gen_replicator_data.py`의 SimulationApp 생성 이후에 import해야 함. 메인 파일 상단에서 lazy import 패턴 사용:
   ```python
   # SimulationApp 생성 후
   from sdg_config import *
   from sdg_math import ...
   # pxr 의존 모듈은 SimulationApp 이후
   from sdg_usd_xform import ...
   from sdg_scene import ...
   from sdg_distractors import ...
   from sdg_annotation import ...
   ```

2. **모듈 레벨 캐시**: `_xformable_cache`, `_cached_pallet_shaders` 등은 모듈 전역 변수. 이동 시 해당 모듈에서 관리하고, 필요하면 reset 함수 제공.

3. **`ORIENTATION_OVERRIDES` 절대 수정 금지** — `compute_model_info` 내부의 값은 검증 완료.

4. **테스트**: Isaac Sim 환경에서만 실행 가능하므로, 각 Task 완료 후 `--num_frames 1`로 smoke test.
