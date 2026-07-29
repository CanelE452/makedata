# Stage 2-C1 최종 보고 — production `.blend` portable 화 (원본 무손상)

## 1. 목적과 판정

production Blender scene 이 이 Windows 머신의 절대경로에 묶여 있는 문제를 **원본 `.blend` 를
한 바이트도 건드리지 않고** 해결한다.

**판정: 완료 · 승격함.** 중단 기준 해당 없음.

원본 `synth_data_scene.blend` 는 SHA256·크기·mtime 모두 작업 전과 동일하고, 같은 폴더에
새로 만든 `synth_data_scene_portable.blend` 가 active production scene 이 되었다.
`distractors` · `blender_scene` · `background` 디렉토리는 **이동하지 않았다**(Stage 2-C2 대상).

## 2. branch / HEAD

```
분기 기준     e72a719689d60e149563b3b5e558fa800254ff67  (= main = origin/main)
작업 branch   chore/data-pallet-stage2c1-portable-blend
작업 전 상태   clean, 실행 중 blender.exe 0개
commit / push  0 / 0
```

## 3. 원본 source hash

```
data/pallet/blender_scene/synth_data_scene.blend
  size    358,917,479 bytes
  mtime   2026-07-24 19:39:00.380291100 +0900
  sha256  46f436dc8d9302a6f857c62c1abcaf4e6fefdc10042ee646e9ef3dc3acbb7fb9
```

`_docs/history/2026-07-26.md:10` 이 기록한 값과 동일 — 2026-07-26 이후 원본이 한 번도
수정되지 않았다는 독립 증거다. 작업 종료 시점에도 동일하다.

## 4. 원본 외부경로 감사 (읽기 전용)

```
verdict                      건수   내용
────────────────────────────────────────────────────────────────────────────
BLOCKED_ABSOLUTE             228   data/pallet/distractors/... 드라이브 절대경로
SAFE_RELATIVE                286   //textures\ 158 + //..\distractors\ 128
SAFE_PACKED_OR_GENERATED      88   packed 86 + VIEWER 2
MISSING_CURRENT                1   factory_yard_2k.hdr -> 다른 워크스페이스 경로
────────────────────────────────────────────────────────────────────────────
합계                         603   libraries/movieclips/fonts/sounds/cache = 0
```

### ★ Stage 2-B 의 "356" 은 과다계상이었다 [확인, 추적함]

파일이 바뀐 게 아니다(SHA256 동일). Stage 2-B 가 커밋한 `blend_external_paths.csv` 의
`BLOCKED_ABSOLUTE` 356행을 raw 로 세면 **228 은 절대경로, 128 은 이미 `//` 상대경로**다.
Stage 2-B 는 `//textures` 158건 오탐은 고쳤지만 `//..\distractors` 128건은 남겼다
(두 보고서의 중간값 "514" 가 그 흔적: 158+356 = 286+228 = 514).
차이가 전부 설명되므로 진행했다. 상세: `pre_audit_summary.md`.

## 5. distractor mapping

```
계획 대상 (BLOCKED_ABSOLUTE)     228
PLANNED                          228
BLOCKED                            0
new_filepath 중복                   0   (228개 전부 서로 다른 경로)
basename 충돌로 인한 오결선          0
old_sha256 == new_sha256          228 / 228
```

변환 형태: `E:\...\data\pallet\distractors\X` → `//../distractors/X`
(Blender 가 저장 시 네이티브 구분자로 정규화해 `//..\distractors\X` 로 기록).
basename 재탐색을 하지 않고 **기존 절대경로가 가리키던 그 파일**만 기준으로 계산했다.
계획서: `distractor_path_plan.csv`.

## 6. factory_yard 판정: **REPOINT_EXACT**

```
users=1, referenced_by = world:World/환경 텍스처  -> 미사용 아님 (제거 경로 성립 안 함)
후보 검색 (data/pallet 전체 + repo + registry hdri_root)  -> 정확히 1건
  data/pallet/assets/lighting/hdri/library/factory_yard_2k.hdr
  sha256 71d5b32c… == Stage1 인벤토리의 이동 전 data/pallet/hdri/factory_yard_2k.hdr
  라이선스 CC0 / SOURCES.txt: polyhaven.com/a/factory_yard, Sergej Majboroda
  Blender 5.1.1 decode OK (hdri_root 30/30)
렌더 동작 변화 없음 — v2 CONSTRAINED_HDRI_EXCLUDE / v4 _DROP 이 그대로 이름으로 제외 (pool 28)
```

상세·부수 관찰(`randomizers._collect_hdri_images` 의 already-loaded 재삽입 경로):
`factory_yard_decision.md`.

## 7. candidate 생성

```
1. stable/candidate 경로 부재 확인
2. shutil.copy2  source -> synth_data_scene_portable_candidate_20260729.blend
3. 복사 직후 SHA256 == source SHA256   (byte-identical 확인)
4. candidate 만 Blender 로 열기 (bpy.data.filepath == candidate 검증 후 진행)
5. 계획 228건 적용 + repoint 1건, 제거 0건
6. 저장 (compress=True — 원본 헤더가 zstd 28b52ffd 임을 확인하고 맞춤)
```

원본을 연 프로세스에서는 저장 계열 API 를 한 번도 호출하지 않았다.
pack/unpack/make_paths_relative/make_paths_absolute 전체 호출 **0**.

## 8. candidate 저장 전 게이트

```
열린 파일 == candidate            ✓
열린 파일 != source               ✓
source SHA256 (저장 직전)         46f436dc… 일치
계획 외 filepath 변경              0
절대경로 잔존                      0
사용자별 절대경로 잔존              0
missing path                     0
상대경로인데 resolve 실패           0
mapping SHA256 mismatch          0
-> 전부 통과했으므로 저장 실행
저장 후 source SHA256              46f436dc… 불변
```

## 9~12. 재개방 검증 (새 headless 프로세스)

```
항목                          원본     portable   기대
────────────────────────────────────────────────────────
image datablock                603       603     동일
절대 외부경로                   228         0        0
사용자별 절대경로                 1         0        0
missing path                    1         0        0
//textures resolve            158       158      158
//../distractors resolve      128       356   128+228
packed                         86        86     동일
mapping SHA256 대조             -    228/228  mismatch 0
경로 mismatch                   -         0        0
계획 외 변경                     -         0        0
구조 diff                       -         0        0
```

구조 diff 0 — scenes/view_layers/collections/objects/meshes/materials/node_groups/worlds/
cameras/lights/images/textures 개수, 이름 집합, active scene, render engine·해상도,
color management, 카메라 matrix_world(9자리)·lens·sensor 전부 동일.
상세: `post_audit_summary.md` · `structure_diff.md`.

## 13. no-render 감사

```
registry missing 0 · Pallet_0~3 · Distractors_v2 · Dist_ root 209 · manifest 209
image missing 0 · 절대경로 0 · node image 누락 0 (마젠타 원인 후보 0)
HDRI 30/30 decode (v2 constrained pool 28) · floor 42/42 · wood 27/27
```

원본 / candidate / 승격 후 stable 3회 모두 실행. `candidate_no_render_audit.md`.

## 14. 2-frame smoke

```
out    data/pallet/runs/smoke/_stage2c1_portable_blend_smoke2_seed7210/
seed 7210 · usable 2/2 · public mask · dataset-quality · noise clean · OPTIX · 181.45s
필수 87항목 검증 실패 0
f0000  Pallet_2 / parking_lot / dirt_ground / brown_dry / context-rich / 4.38m
f0001  Pallet_1 / parking_lot / gravel_concrete_02 / ind_blue / controlled-occlusion
       (Dist_utility_box_01) / 2.32m
magenta 0 (record + 픽셀 실측) · visible ⊆ amodal 위반 0px · overlay canvas == RGB
RGB 2장 + overlay 2장 직접 열어 확인
```

`smoke2_verification.md` — 마스크 전경 판정은 파이프라인 정본
`strict_decode_mask`(>127) 를 import 해서 썼고, 처음 `>0` 으로 셌던 오류를 바로잡은 경위도
그대로 적었다. HDRI 파일명 필드는 v2 스키마에 없어 `scene_preset`+`exposure_ev` 로 확인했다.

## 15. stable 승격 · registry 변경

```
data/pallet/blender_scene/synth_data_scene_portable.blend   sha256 5cad94e5…  358,898,907 B
rename 전후 SHA256 동일 · overwrite 0 · 원본 그대로 유지 · 원본 이름/위치 불변
```

```
registry key                      before                          after
──────────────────────────────────────────────────────────────────────────────────────
production_scene                  …/synth_data_scene.blend        …/synth_data_scene_portable.blend
production_scene_rollback_source  (없음)                           …/synth_data_scene.blend   ← 신규
production_scene_textures         변경 없음
experimental_scene                변경 없음 (지시대로)
audit                             ok=21 missing=0                 ok=22 missing=0
```

`promotion_report.md`.

## 16. current runtime 경로 수정

```
분류                파일                                          조치
──────────────────────────────────────────────────────────────────────────────────────
CURRENT_RUNTIME    run_dataset_v4.sh:58                          resolver CLI 조회로 교체
                   run_4pallet_mask.sh:41                        resolver CLI 조회로 교체
                   run_pilot_2k.sh:11 (머신 절대경로였음)           ROOT 변수 + resolver CLI
CURRENT_RUNTIME    run_v2_scene_logic.py:13,25 (docstring 예시)    resolver 조회 예시로 교체
                   gen_dataset_v4.py:29 / gen_4pallet_mask.py:29  동일
CURRENT_TEST       test_pallet_data_paths_unit.py                신규 불변식 3건
                   integration_tests/…_local.py                  신규 불변식 3건
CURRENT_DOC        _docs/data_pallet_layout.md                   registry 표 + 이동보류 사유 갱신
                   _docs/blender_mcp_onboarding.md               프로덕션 씬 정의 + 예시 4곳
                   scripts/data_prep/efront_calibration/README.md 예시 교체
수정하지 않음        _docs/history/* · reports/ snapshot ·
                   Stage 2-A/2-B transaction manifest ·
                   path_map original_path · 과거 명령·결과
LEGACY(미수정)      _b3_asset_check · _g5_reverify · _v2_calib_200 · _v2_pilot_2k ·
                   _render_* 9종 · _diag_* · _gen_wood_random_samples ·
                   gen_preview10 · gen_topview_test · render_blender_data
                   (전부 일회성 진단 스크립트의 docstring 예시. 실행 시 씬은 CLI 인자로
                    받으므로 런타임 동작에 영향 없음)
```

새 portable 경로 리터럴을 여러 곳에 다시 박지 않았다 — 전부 registry 키 조회다.

## 17~22. 승격 후 회귀 검증

```
검사                         기준선          승격 후          판정
────────────────────────────────────────────────────────────────────
registry audit              ok=21/miss 0    ok=22/miss 0     ✓
default unit                568 passed      614 passed       ✓ (+43 helper, +3 registry)
local integration            23 passed       26 passed       ✓ (+3)
golden overlay               51 passed       51 passed       ✓ skip 0
Stage 2-A 원장               146 / 6,921     146 / 6,921      ✓ failures 0
Stage 2-A 원장 sha256        fe1adc26…       fe1adc26…        ✓ 불변
Stage 2-B B1                 4 / 3,220       4 / 3,220        ✓ hash all, failures 0
Stage 2-B B2                 3 / 68          3 / 68           ✓ hash all, failures 0
5k FrameSpec sha256          938f387d…       938f387d…        ✓ 덤프 byte 동일
5k accepted / rejected       4,313 / 687     4,313 / 687      ✓
5k distractors               209             209              ✓
5k proposals digest          3cd365ee…       3cd365ee…        ✓ 12/12 PASS
NaN / inf                    0               0                ✓
final no-render (stable)     -               전 항목 통과       ✓
```

## 23. 원본 보존 확인

```
파일 존재                                    ✓
SHA256 = 46f436dc… (작업 전과 동일)           ✓
크기 358,917,479 (동일)                       ✓
mtime 2026-07-24 19:39:00.380291100 (동일)   ✓  -> 저장 이력 없음
내부 filepath 수정                            없음 (source 를 연 프로세스는 read-only)
registry 에서 active 아님, rollback source 로 보존  ✓
삭제·이동·개명                                 없음
portable 과 별개 파일 (os.path.samefile=False) ✓
```

### 새로 생긴 파일 1개 (정직한 기록)

`data/pallet/blender_scene/synth_data_scene_portable_candidate_20260729.blend1`
— `save_as_mainfile` 이 만든 자동 백업. 358,917,479 bytes, SHA256 `46f436dc…`
(= 원본과 동일 바이트). 삭제하지 않았다. 이름이 이미 없는 candidate 를 가리키므로
Stage 2-C2 정리 대상.

## 24. Stage 2-C2 선행조건

```
해소됨    production .blend 의 절대경로 (228 -> 0)
해소됨    factory_yard_2k.hdr 깨진 datablock (1 -> 0)
남음      distractors/ 이동 시 //..\distractors\ **356건** rebase 필요
          (사유가 "절대참조"에서 "상대참조 rebase"로 바뀐 것이지 없어진 게 아니다)
남음      blender_scene/ 이동 시 //textures\ 158 + //..\distractors\ 356 둘 다 rebase
남음      background/ 의 원본 ZIP 3개(157MB)를 archive/packages/ 로 먼저 분리
남음      packed 17건의 AppData/Temp 경로 문자열 (inert, packed 라 수정 대상 아님)
정리대상   synth_data_scene_portable_candidate_20260729.blend1
도구       manage_blend_external_paths.py 가 rebase 에도 그대로 쓰인다
          (--rewrite-root / --allowed-root 로 새 위치를 지정)
```

## 25. git diff

```
12 files changed, 101 insertions(+), 24 deletions(-)
  config/synthetic/pallet_paths.yaml
  scripts/data_prep/blender/{run_dataset_v4.sh, run_4pallet_mask.sh, run_pilot_2k.sh}
  scripts/data_prep/blender/{run_v2_scene_logic.py, gen_dataset_v4.py, gen_4pallet_mask.py}
  scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py
  scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py
  scripts/data_prep/efront_calibration/README.md
  _docs/data_pallet_layout.md, _docs/blender_mcp_onboarding.md

신규(untracked)
  scripts/data_prep/blender/blend_path_utils.py            (bpy-free 순수 helper)
  scripts/data_prep/blender/manage_blend_external_paths.py (audit/plan/apply/verify)
  scripts/data_prep/blender/audit_blend_assets.py          (no-render 자산 감사)
  scripts/data_prep/blender/tests/test_blend_external_paths.py  (43 tests)
  reports/data_pallet_cleanup/stage2c1/
```

## 26. rollback 가능 여부

**가능.** 원본이 무손상이므로 registry 를 되돌리고 portable 파일을 `archive/legacy_scenes/`
아래로 rename 하면 끝이다. 데이터 삭제 없음. 절차: `rollback_plan.md`.
원본이 남아 있으므로 portable 은 언제든 결정적으로 재생성할 수도 있다.

---

```
원본 blend 수정 건수            0
원본 blend 삭제 건수            0
candidate 생성 수              1
상대경로 변환 수                228
정확 파일 SHA256 대조 수         228   (+ factory_yard 1 = 229)
SHA256 mismatch               0
missing path before / after   1 / 0
absolute path before / after  229 / 0
factory_yard 처리 방식          REPOINT_EXACT (제거 아님)
구조 불변 위반 수                0
smoke frame 수                 2
magenta frame 수               0
distractors 이동 수             0
background 이동 수              0
blender_scene 디렉토리 이동 수    0
ZIP 이동 수                    0
legacy dataset 이동 수          0
isaac_assets 이동 수            0
NoAI quarantine 이동 수         0
500 렌더 수                    0
40k 렌더 수                    0
commit                        0
push                          0
```
