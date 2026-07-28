# §1 registry 테스트 분리 (clone-safe unit / local integration)

## 문제 [확인]

Stage 2-A 의 `tests/test_pallet_data_paths.py`(22개)는 로컬 workstation 의 실제
`data/pallet` 파일을 단언했다. 그런데 `data/pallet` 은 gitignored 라 새 clone 에는 없다.

```
거동        테스트                                              새 clone 에서
──────────────────────────────────────────────────────────────────────────────────
FAIL       test_audit_reports_no_missing_path                  registry 21경로 전부 없음
FAIL       test_backslash_registry_values_are_accepted         isdir(hdri_root) False
FAIL       test_..._loads_the_full_209_pool                    manifest 파일 없음
잘못 통과   test_project_root_detection_finds_the_repo          walk-up 이 전부 실패하고
                                                               `__file__/../../..` fallback 으로
                                                               떨어지는데 그 값이 우연히 repo 라
                                                               초록불. 탐지 로직 미검증.
```

## 분리 결과

```
파일                                                             테스트   실데이터
─────────────────────────────────────────────────────────────────────────────────
tests/test_pallet_data_paths_unit.py                                41   사용 안 함
integration_tests/test_pallet_data_paths_local.py                   20   사용
─────────────────────────────────────────────────────────────────────────────────
합계                                                                61
기존                                                                22
증감                                                               +39
```

**기존 assertion 은 하나도 약화하지 않았다.** 실데이터 단언 3건은 integration 으로 **이동**했고,
`detect_project_root` 는 임시 fixture 에 가짜 repo 를 만들어 **walk-up 경로 자체를 검증**하도록
다시 썼다(두 marker 를 모두 요구하는지, 하나만 있으면 탐지 실패하는지).

## unit test 가 검사하는 것 (41)

```
그룹                          수   내용
────────────────────────────────────────────────────────────────────────────────
ModuleIsBpyFree                3   소스에 import bpy 없음 / sys.modules 오염 없음 /
                                   별도 인터프리터에서 bpy 없이 import 성공
ConfigParsing                  4   명시 config 경로 / "//" 주석 키 무시 /
                                   FOUNDATIONPOSE_PALLET_PATHS env / list 값 원소별 해석
ProjectRootDetection           4   두 marker 를 모두 가진 상위로 walk-up /
                                   config 만 있으면 root 아님 / data/pallet 을 만들면 찾음 /
                                   명시 project_root 우선
RootOverride                   4   PALLET_DATA_ROOT env / 인자 override / 절대 root /
                                   data root 밖 경로는 건드리지 않음
SeparatorHandling              3   backslash 값 수용 / relative() 는 항상 posix /
                                   해석 결과는 절대경로이며 project_root 하위
MissingAndOptional             8   required key 누락 시 KeyError(전 키 대상) /
                                   없는 경로는 missing 으로 보고(대체 경로 없음) /
                                   optional 은 absent_optional / unknown key KeyError /
                                   get_existing 은 list 원소까지 검사
Caching                        2   동일 인자 캐시 / clear_cache 재로드
RegistryContentRules           4   배포된 registry 의 *내용* 규칙 (파일시스템 미접근):
                                   필수 키 존재 / 빈 assets/ 를 가리키지 않음 /
                                   material root 가 archive 위치를 명시 / 전부 상대경로
CommandLineInterface           9   §4 참조 (or True 회귀 방지 포함)
```

## clone-safety 실증 [확인, 실행함]

`config/synthetic` + `scripts/` 만 복사하고 **`data/` 를 아예 만들지 않은** 임시 트리에서 실행:

```
$ ls <clone_sim>
config
scripts

$ python -m pytest scripts/data_prep/blender/tests/test_pallet_data_paths_unit.py -q -rs
41 passed in 1.05s          # skip 0, network 0
```

### CLI 테스트의 함정을 한 번 더 잡았다 [확인]

처음 작성한 CLI 테스트는 `--config` 만 fixture 로 주었는데, `project_root` 는 **모듈 파일 위치**
에서 탐지되므로 상대경로가 **실제 저장소**를 향했다. 즉 fixture 가 아니라 이 workstation 의
`data/pallet` 존재 여부를 검사하며 통과하고 있었다 — 애초에 고치려던 바로 그 패턴이다.
`_run()` 이 항상 `--data-root <fixture>` 를 붙이도록 바꾸고,
`test_cli_paths_resolve_inside_the_fixture_not_the_real_repo` 로 이를 고정했다.

## integration test (20)

```
실행:
  PALLET_DATA_INTEGRATION=1 python -m pytest \
      scripts/data_prep/blender/integration_tests/test_pallet_data_paths_local.py -q
  # PowerShell:  $env:PALLET_DATA_INTEGRATION="1"

환경변수 없이 실행하면 -> 수집 시점에 RuntimeError 로 중단 (조용한 skip 아님)
```

검사 항목: registry audit missing 0 / production_scene · textures(같은 폴더) / background_root /
distractor_root · manifest · **pool 정확히 209** / manifest 경로가 registry 와 일치(pool·pipeline) /
hdri_root(.hdr 존재) / floor·pallet material root / **blender_config 가 해석한 값과 일치** /
pallet model roots 전부 / golden overlay reference + `overlay/000000.png` 실재 /
real_data_root / runs_root / registry 가 빈 assets/ 를 가리키지 않음 /
assets/ 에 README 외 파일이 없음(자산 미이동 상태 확인).

```
$ PALLET_DATA_INTEGRATION=1 python -m pytest scripts/data_prep/blender/integration_tests -q -rs
20 passed in 0.19s          # skip 0
```

## 기본 collection 에 섞이지 않음 [확인]

```
$ python -m pytest scripts/data_prep/blender/tests -q --collect-only
566 tests collected          # integration_tests/ 는 포함되지 않음
```

디렉토리 자체를 분리했으므로 "숨기기 위한 collection 제외"나 조건부 skip 마커가 없다.
