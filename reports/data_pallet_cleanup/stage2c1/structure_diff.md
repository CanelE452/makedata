# §7 구조 diff — 원본 vs portable

`post_audit/structure_diff.json` / `structure_diff.json` (동일 사본)

## 결과: **diffs = 0**

```
항목                    before(원본)   after(portable)   판정
──────────────────────────────────────────────────────────────
scenes                        1              1          동일
view_layers                   1              1          동일
collections                   2              2          동일
objects                   1,122          1,122          동일
meshes                      597            597          동일
materials                   350            350          동일
node_groups                   1              1          동일
worlds                        1              1          동일
cameras                       1              1          동일
lights                        1              1          동일
images                      603            603          동일
textures                      0              0          동일
```

이름 집합(정렬 비교) — 전부 동일:

```
objects (1,122) · collections (Collection, Distractors_v2) · materials (350)
worlds (World) · cameras (RenderCamera) · node_groups (1)
Pallet_* = [Pallet_0, Pallet_1, Pallet_2, Pallet_3]
Dist_ root = 209
```

렌더 / 카메라 / 컬러관리 — 전부 동일:

```
active_scene              Scene
render.engine             BLENDER_EEVEE
render.resolution         640 x 480 @ 100%
render.film_transparent   False
render.filepath           (변경 없음)
cycles.samples            (변경 없음)
eevee.taa_render_samples  (변경 없음)
view_transform            Filmic
look                      Medium Contrast
exposure / gamma          0.0 / 1.05
display_device            sRGB
sequencer_colorspace      sRGB
camera.matrix_world       4x4 전 성분 동일 (소수 9자리 비교)
camera.lens / sensor_width / sensor_fit / shift_x / shift_y   동일
```

## image datablock 수가 줄지 않은 이유

§7 은 "factory_yard unused datablock 을 제거했다면 image datablock 수만 정확히 1 감소 가능"
이라고 허용했다. 그러나 이 datablock 은 `users=1` 로 활성 world 의 Environment Texture 노드가
쓰고 있어 **미사용이 아니다**(`factory_yard_decision.md` §1). 따라서 제거가 아니라
REPOINT_EXACT 를 적용했고, image 수는 603 그대로다.

**허용되지 않은 차이 0건 → 승격 게이트 통과.**
