# §6 analyze / §7 determinism — public·full-audit 레이아웃 대응

`mask_profiles.py` 를 단일 정의로 삼고, 두 소비자의 `root/"mask"` 하드코딩을 걷어냈다.

```
public       mask_amodal/f{idx:04d}.png (M0)   mask_visible/f{idx:04d}.png (M4)
full-audit   mask/f{idx:04d}_m0.png … _m4.png
```

---

## §6 analyze_v2_scene_logic.py

### 수정 전 [확인]

```
471-474  mask_dir = root / "mask";  glob(f"f*_{suffix}.png")      (discover_indices)
968      mask_stats(root / "mask" / f"{frame}_{name}.png")        (build_frame_row)
```

public 셋에서는 `mask/` 가 아예 없으므로 **5 stage 전부를 결측으로 셌다.**
`--mask-names` 기본값이 5개라 `mask_area_after_*` 도 빈 채로 남았다.

### 수정 후

```
신규 --mask-profile auto|public|full-audit   (기본 auto)
     auto = mask_amodal + mask_visible 둘 다 있으면 public,
            mask/ 가 있으면 full-audit,
            둘 다 없으면 full-audit 으로 두되 detected_by 에 "unknown(...)" 를 남긴다
기존 --mask-names                            (하위호환 유지, 기본값 None)
     주면 profile 자동감지를 끄고 legacy <root>/mask/<frame>_<name>.png 규약을 그대로 쓴다
```

신설 헬퍼 — 직접 조립 대신 이것만 쓴다.

```python
resolve_mask_profile(root, requested, explicit_names)
    -> {profile, detected_by, stages, occlusion_decomposition_available}
mask_path_for(root, idx, stage, profile_info)   # MP.frame_mask_paths 위임
```

`discover_indices` 는 public 일 때 `mask_amodal/`·`mask_visible/` 의 `fNNNN.png`
(접미사 없음)에서 인덱스를 모으고, full-audit 일 때는 기존 접미사 glob 을 쓴다.

`write_self_test_fixture` 의 `root/"mask"` 조립은 **self-test 전용이라 유지**했다
(§6 지시: "self-test 외 실제 dataset 경로"). self-test 는 `--mask-names` 를 명시적으로
넘겨 legacy 경로를 타므로 기존 동작이 그대로다.

### summary 에 추가

```json
"mask_layout": {
  "mask_profile": "public",
  "detected_by": "dirs:mask_amodal+mask_visible",
  "mask_stages": ["m0", "m4"],
  "occlusion_decomposition_available": false
}
```

### 작업 중 추가로 발견해 고친 것 [확인]

`frame_columns()` 가 제거 대상을 **전역 `MASK_NAMES`** 로만 계산했다. `main()` 이
그 전역을 public 의 2개로 덮어쓴 뒤 호출하므로, 모듈 로드 시점에 5개로 만들어진
`FRAME_COLUMNS` 의 `mask_m1/m2/m3_*` 컬럼이 **살아남아 CSV 에 빈 칸으로 출력**됐다.
소비자에게는 "결측"으로 보인다. 알려진 전체 stage 집합을 먼저 제거하도록 고쳤고
회귀 테스트 2개로 고정했다.

### CLI end-to-end 결과 [확인, 실행함]

```
profile=public      exit=0
  mask_layout: {"mask_profile":"public","detected_by":"dirs:mask_amodal+mask_visible",
                "mask_stages":["m0","m4"],"occlusion_decomposition_available":false}
  frames: 3     source_files_missing: {''}     mask 컬럼: ['m0','m4']

profile=full-audit  exit=0
  mask_layout: {"mask_profile":"full-audit","detected_by":"dirs:mask",
                "mask_stages":["m0","m1","m2","m3","m4"],"occlusion_decomposition_available":true}
  frames: 3     source_files_missing: {''}     mask 컬럼: ['m0','m1','m2','m3','m4']
```

public 에서 **M1~M3 결측 오판 0건**, full-audit 결과는 5 stage 그대로(회귀 없음).
실제로 없는 stage(예: full-audit 에서 `f0000_m2.png` 삭제)는 **여전히 결측으로 보고**한다.

### None 과 0.0

`mask_profiles.decompose(..., PUBLIC)` 가 `f_static/f_cargo/f_context/f_explicit` 를
`None`(미측정)으로 두고 `f_total` 만 exact 로 계산한다는 것을 테스트로 고정했다.
가림이 없는 프레임의 `f_total` 은 `None` 이 아니라 `0.0` 이다.

---

## §7 compare_v2_determinism.py

### 수정 전 [확인]

```
217  root / "mask" / f"{frame}_{name}.png"   for name in MASK_NAMES   # 5개 고정
```

좌·우 모두 full-audit 이라고 가정. public 셋을 넣으면 5개 전부 decode 오류가 나거나,
`continue` 로 조용히 건너뛰어 mask 비교 0건인 채 "deterministic" 이 될 수 있었다.

### 수정 후

- 좌·우 profile 을 **각각 독립 감지**(`MP.detect_profile`).
- 경로는 `MP.frame_mask_paths(root, idx, profile)` 로 해석. 직접 조립은 legacy 분기 1곳만 남았다
  (테스트가 `src.count('"mask" / f"{frame}_') == 1` 로 고정).
- profile 이 다르면 **기본은 error** (`category: mask_profile_mismatch`, `deterministic=false`).
- `--allow-mask-profile-mismatch` 를 주면 공통 stage(m0, m4)만 비교하고
  `partial_mask_comparison=true` 를 남기며, **완전 결정성 통과로 표현하지 않는다**
  (mismatch 항목이 `mismatches` 에 남아 `deterministic` 은 false).
- `--mask-names` legacy override 유지.
- RGB / label / record 결정성 검사는 그대로.

### report 에 추가

```
left_mask_profile  right_mask_profile  compared_mask_stages
partial_mask_comparison  mask_profile_mismatch
```

### 조합별 결과 [확인, 실행함 — 임시 fixture]

```
좌 / 우                    compared_mask_stages   masks 비교수  deterministic
──────────────────────────────────────────────────────────────────────────────
public / public            [m0, m4]               2 frames x2   True
full-audit / full-audit    [m0..m4]               2 frames x5   True
public / full-audit        [m0, m4]               -             False (errors: mask_profile_mismatch)
public / full-audit
  + --allow-...-mismatch   [m0, m4]               2 frames x2   False (partial_mask_comparison=true)
public 한쪽 M4 픽셀 변조     [m0, m4]               -             False (mismatch: mask_pixels m4)
legacy --mask-names m0,m4  [m0, m4]               2 frames x2   True
```

---

## 테스트

`tests/test_mask_layout_compatibility.py` — **31개, 임시 fixture 전용(Blender·실데이터 없음)**

```
ProfileDefinitions          8   stage/dir 정의, detect_profile, public 분해가 None 인지,
                                0.0 과 None 구분, full-audit 전 source 계산, 불완전 areas 거부
AnalyzeProfileResolution    5   auto public / auto full-audit / 명시 override /
                                legacy --mask-names / mask 디렉토리 없음 -> unknown
AnalyzePublicLayout         6   인덱스 발견 / 경로가 public 디렉토리로 / **결측 오판 0** /
                                m1~m3 컬럼 부재 / 면적 측정 / CSV 컬럼에 빈 m1~m3 없음
AnalyzeFullAuditLayout      4   인덱스 / 5 stage 측정 / 진짜 결측은 보고 / 5 컬럼 유지
DeterminismAcrossProfiles   8   위 조합표 + RGB·label 검사 유지 + 직접 조립 1곳뿐
```
