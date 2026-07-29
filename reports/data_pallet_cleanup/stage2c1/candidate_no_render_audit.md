# §9 Blender no-render candidate 감사

`blender -b <blend> --python scripts/data_prep/blender/audit_blend_assets.py -- --report-dir … --tag …`

렌더·저장 없음. 원자료: `candidate_no_render_audit.json` (candidate) ·
`final_stable_no_render_audit.json` (승격 후 stable) · `pre_audit/source_no_render_audit.json` (원본)

> Stage 2-B 는 같은 감사를 **커밋되지 않은 임시 스크립트**로 돌렸다. 다음 단계에서 재현할 수
> 있어야 하므로 이번에 정식 스크립트(`audit_blend_assets.py`)로 만들었다.

## 결과 [확인, 실행함]

```
검사                                  원본 blend   portable(candidate)   portable(stable)   기대
────────────────────────────────────────────────────────────────────────────────────────────────
blender_config import                  OK            OK                   OK             OK
pallet_data_paths import               OK            OK                   OK             OK
v2_realize import                      OK            OK                   OK             OK
registry missing                        0             0                    0              0
Pallet_0~3                            존재          존재                 존재            존재
Distractors_v2 컬렉션                  존재          존재                 존재            존재
Dist_ root                            209           209                  209            209
distractor manifest rows              209           209                  209            209
background root                       존재          존재                 존재            존재
image datablock 총계                   603           603                  603           동일
image missing                           1             0                    0              0
image 절대경로                         229             0                    0              0
//textures 참조                        158           158                  158            158
//../distractors 참조                  128           356                  356          128+228
material/world/nodegroup image node 누락  1             0                    0              0
HDRI decode                          30/30         30/30                30/30          30/30
  v2 constrained pool                   28            28                   28             28
floor texture decode                 42/42         42/42                42/42          42/42
wood texture decode                  27/27         27/27                27/27          27/27
```

- **마젠타 원인이 될 missing texture 0** — `node_image_missing = 0`.
  원본에서 1건이던 것은 `factory_yard_2k.hdr` 이며 REPOINT_EXACT 로 해소됐다.
- **HDRI 30/30 decode** 는 `hdri_root` 의 실제 파일을 Blender 가 하나씩 로드해 `size[0] > 0` 을
  확인한 결과다. 여기에 `factory_yard_2k.hdr` 도 포함되며 이것이 §5 판정의 decode 근거다.
- `v2 constrained pool = 28` 은 `v2_realize.CONSTRAINED_HDRI_EXCLUDE`(factory_yard,
  mall_parking_lot) 를 뺀 수다. **이번 작업으로 바뀌지 않았다.**

## 재현

```bash
SCENE="$(python scripts/data_prep/blender/pallet_data_paths.py --key production_scene)"
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b "$SCENE" \
  --python scripts/data_prep/blender/audit_blend_assets.py -- \
  --report-dir reports/data_pallet_cleanup/stage2c1 --tag final_stable
```
