# §20 Blender no-render 최종 감사

```bash
SCENE="$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)"
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b "$SCENE" \
  --python scripts/data_prep/blender/audit_blend_assets.py -- \
  --report-dir reports/data_pallet_cleanup/stage2c2 --tag final
```

렌더 없음 · 저장 없음. 원자료: `final_no_render_audit.json`

## 결과 [확인, 실행함]

```
검사                                결과                    기대
──────────────────────────────────────────────────────────────────
scene open                          OK (stage2c2 stable)    OK
pallet_data_paths import            OK                      OK
blender_config import               OK                      OK
v2_realize import                   OK                      OK
registry missing                    0                       0
image datablock 총계                 603                    603
absolute external path              0                       0
missing image                       0                       0
missing library                     0                       0
textures resolve                    158                     158
distractor resolve                  356                     356
HDRI 외부 상대참조                    1                       1
material/world/nodegroup node 누락   0                       0   (마젠타 원인 경로 0)
Dist_ root                          209                     209
Pallet_0~3                          존재                    존재
Distractors_v2 컬렉션                존재                    존재
distractor manifest rows            209                     209
HDRI decode                         30 / 30                 30
  v2 constrained pool                28                     28  (factory_yard·mall_parking_lot 제외)
floor texture decode                42 / 42                 42
wood texture decode                 27 / 27                 27
background root                     assets/scenes/backgrounds/background  존재
background configured asset         parking_lot -> 파일 존재
                                    industrial  -> kind=existing (blend 내장, 파일 없음)
```

## 감사기 자체를 고친 점 [확인]

첫 실행에서 `//../distractors=0` 이 나왔다. 파일이 깨진 게 아니라 **카운터가 옛 상대경로
문자열(`//../distractors/`)을 하드코딩**하고 있었기 때문이다. 새 형태는
`//../../../distractors/library/` 라 문자열 매칭이 빗나갔다.

→ `audit_blend_assets.py` 의 카운터를 **resolve 된 절대경로가 registry root 안인지**로
바꿨다(위치 비의존). 이제 폴더가 또 옮겨져도 같은 수치를 낸다. 절대경로 판정에도
선행 슬래시(POSIX 절대경로) 케이스를 추가했다.

이 수정이 없었다면 "distractor 참조 0" 이라는 **틀린 안심**을 보고할 뻔했다.
