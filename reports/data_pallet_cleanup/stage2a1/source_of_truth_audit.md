# §2 runtime 경로 정본 확정

## 확정된 관계

> **`config/synthetic/pallet_paths.yaml` 은 runtime source of truth 이고,
> `data/pallet/manifests/*.csv` 는 local inventory snapshot 이다.**

```
역할                        위치                                              성격
──────────────────────────────────────────────────────────────────────────────────────
runtime source of truth     config/synthetic/pallet_paths.yaml                 tracked, 유일 정본
resolver                    scripts/data_prep/blender/pallet_data_paths.py     tracked
local inventory snapshot    data/pallet/manifests/*.csv                        gitignored, 조사 기록
tracked 조사·이동 기록        reports/data_pallet_cleanup/                       tracked
```

## 원칙

- 실행 코드는 `pallet_paths.yaml` 만 읽는다. **`assets.csv` 를 읽는 실행 경로는 없다** [확인].
- `assets.csv` 는 runtime config 가 아니라 조사 시점의 snapshot 이다.
- `assets.csv` 를 수정해도 실행 경로는 바뀌지 않는다.
- runtime 경로 변경은 `pallet_paths.yaml` 수정으로만 수행한다.
- 경로 이동과 registry 변경은 **같은 transaction 단계에서 함께 검증**한다.
  (옮기고 registry 를 안 고치면 `--audit` 의 `missing` 으로, 반대면 실행 시 파일 없음으로 드러난다.)

## 수정 전 상태 [확인]

같은 문서 안에서 "registry 로만 조회한다"와 "assets.csv 의 current_path 가 정본"이 공존해
정본이 둘로 읽혔다.

```
파일                                라인   문구
────────────────────────────────────────────────────────────────────────────────
_docs/data_pallet_layout.md          60   "manifests/assets.csv 의 current_path 열이 정본"
_docs/data_pallet_layout.md         156   "current_path 가 정본, desired_path 는 예정지"
data/pallet/README.md                23   "manifests/assets.csv 의 current_path 열이 진실"
data/pallet/manifests/README.md      13   "정본 컬럼 = current_path"
```

## 수정 내역

```
파일                                     변경
──────────────────────────────────────────────────────────────────────────────────────
_docs/data_pallet_layout.md              §1 에 "정본은 하나다" 표 신설(4행 관계 + 5원칙).
                                         §2 CURRENT 도입부를 registry 기준으로 교체.
                                         §5 manifests 표의 assets.csv 설명을 snapshot 으로 교체.
data/pallet/README.md                    CURRENT 절 도입부를 registry 기준으로 교체.
data/pallet/manifests/README.md          맨 앞에 "이 폴더는 runtime config 가 아니다" 절 신설.
                                         "정본 컬럼" -> "주요 컬럼".
                                         "코드가 읽어야 하는 값은 current_path" ->
                                         "코드는 어떤 컬럼도 직접 읽지 않는다".
reports/data_pallet_cleanup/README.md    §7 앞에 Stage 2-A.1 갱신 주석 추가.
```

`AGENTS.md` / `CLAUDE.md` 에는 registry 안내 1행만 있고 정본 충돌 문구가 없어 그대로 뒀다 [확인].
`_docs/history/*` 는 **수정하지 않았다**(과거 기록 소급 수정 금지).

## 검증 [확인, 실행함]

```
$ grep -rn "current_path.*정본\|current_path 열이 진실" _docs/ data/pallet/*.md data/pallet/manifests/
(무출력)

$ grep -rn "runtime source of truth" _docs/data_pallet_layout.md data/pallet/README.md \
      data/pallet/manifests/README.md reports/data_pallet_cleanup/README.md
4개 파일 전부에 존재
```

registry 가 실제로 유일한 해석 경로인지도 코드로 확인했다 —
`blender_config` / `v2_realize` / `v2_pipeline` / `distractor_pool_v2` 4개 소비자 모두
`pallet_data_paths` 를 통하고, integration test 가 `blender_config.WOOD_TEXTURE_DIR ==
registry["pallet_material_root"]` 를 단언한다.
