# §5 `factory_yard_2k.hdr` 누락 datablock 판정

## 판정: **REPOINT_EXACT**

원자료: `factory_yard_candidates.csv` · `factory_yard_usage.json` ·
`pre_audit/missing_usage.json` · `pre_audit/source_no_render_audit.json`

## 1. 현재 상태 [확인]

```
datablock            images / "factory_yard_2k.hdr"
저장된 filepath_raw   C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\factory_yard_2k.hdr
resolve 결과          파일 없음 (현재 workspace 는 E:\CODING\GitHub\FoundationPose)
users                1
fake_user            false
referenced_by        world:World/환경 텍스처   (Environment Texture 노드)
```

world 는 **1개**(`World`)이고 scene 도 **1개**(`Scene`)이므로, 이 노드는 활성 scene 의
world 다 [확인 — `pre_audit/source_structure.json` 의 `counts.worlds=1`, `names.worlds=['World']`,
`active_scene='Scene'`].

→ **users>0 이므로 "미사용 datablock 제거"(REMOVE_UNUSED_CANDIDATE_ONLY) 경로는 성립하지 않는다.**

## 2. 후보 검색 [확인, 실행함]

```
검색 범위                                결과
────────────────────────────────────────────────────────────────────────────────────
data/pallet 전체 (find -iname)          1건  assets/lighting/hdri/library/factory_yard_2k.hdr
repository (data/ 제외)                 0건
registry hdri_root                      포함 (30개 HDRI 라이브러리 안)
Stage 2-B 이동 전 path_map / 인벤토리     data/pallet/hdri/factory_yard_2k.hdr  (같은 파일)
────────────────────────────────────────────────────────────────────────────────────
후보 총계                                1  -> BLOCKED_AMBIGUOUS 아님
```

## 3. 후보 검증 [확인]

```
항목              값
──────────────────────────────────────────────────────────────────────────────────
경로              data/pallet/assets/lighting/hdri/library/factory_yard_2k.hdr
크기              6,393,026 bytes
SHA256            71d5b32c0e179f5b59f652c59cc4eac18b390e0639e3de2e6049de6bae95caf4
라이선스           CC0 1.0 (LICENSE.txt — Poly Haven 전량 CC0)
출처 기록          SOURCES.txt: asset_id=factory_yard |
                  https://polyhaven.com/a/factory_yard | author: Sergej Majboroda
active manifest   hdri_root 30개 중 1개로 포함
Blender decode    OK — hdri_root 30/30 decode 성공 (Blender 5.1.1, audit_blend_assets.py)
용도 일치          world environment texture 용 HDRI (원 datablock 과 동일 역할)
```

### 결정적 증거 — 이동 전 원본과 동일 파일 [확인]

깨진 경로가 가리키던 위치는 `<other-workspace>/data/pallet/hdri/factory_yard_2k.hdr` 이고,
`data/pallet/hdri` 는 Stage 2-B 에서 `assets/lighting/hdri/library` 로 이동한 폴더다.
Stage 1 인벤토리(`reports/data_pallet_cleanup/_inventory_raw.csv:2614`)가 기록한
이동 전 `data/pallet/hdri/factory_yard_2k.hdr` 의 SHA256 은
`71d5b32c0e179f5b59f652c59cc4eac18b390e0639e3de2e6049de6bae95caf4` —
**현재 후보와 바이트 단위로 같은 파일이다.** basename 우연 일치가 아니다.

## 4. REPOINT_EXACT 조건 대조

```
조건                                       결과
──────────────────────────────────────────────────────
동일 basename 의 유일한 정상 파일 존재         ✓ 1건
출처·라이선스 일치                           ✓ SOURCES.txt + CC0
decode 성공                                ✓ Blender 5.1.1, 30/30
실제 용도 일치                              ✓ world environment HDRI
```

## 5. 렌더 동작에 미치는 영향: **없음** [확인]

repoint 는 datablock 이 실재 파일을 가리키게 할 뿐, HDRI 선택 pool 을 바꾸지 않는다.
factory_yard 는 **양쪽 파이프라인 모두에서 이름으로 제외**되어 있다:

```
현행 v2 constrained (run_v2_scene_logic -> v2_realize._prepare_constrained_hdri_pool)
    v2_realize.py:73  CONSTRAINED_HDRI_EXCLUDE = {"factory_yard_2k.hdr", "mall_parking_lot_2k.hdr"}
    -> pool = 28  (감사 출력에서 확인: "HDRI 30/30 decode ok (v2 constrained pool=28)")

legacy v4 계열 (gen_dataset_v4:547 / gen_4pallet_mask:720 / gen_topview_test:387 / gen_preview10:404)
    _DROP = ("mall_parking_lot", "factory_yard")
```

즉 이 작업은 factory_yard 를 **un-drop 하지 않는다**. `_docs/blender_mcp_onboarding.md:598`
의 "factory_yard HDRI un-drop 미검증(Blender magenta 테스트 필요)" 항목은 그대로 남는다.

### 부수 관찰 — 제네릭 경로에 남아 있는 함정 [확인, 이번 단계 범위 밖]

`randomizers._collect_hdri_images()` 는 disk 로드 시 decode 실패분을 `continue` 로 거르지만
(L1252-1259), 바로 뒤 L1262-1266 "Also include any already-loaded HDRIs" 에서
`filepath` 에 `.hdr` 이 들어간 datablock 을 **다시 pool 에 넣는다.**
현행 v2 는 `_prepare_constrained_hdri_pool()` 이 `randomizers._hdri_cache` 를 미리 채워
이 경로를 타지 않으므로 실害는 없다. 이번 repoint 로 해당 datablock 이 정상 decode 되므로
설령 그 경로를 타더라도 magenta world 는 나지 않는다.
(`_docs/history/2026-07-26-v2-attempt-log.md:107-108` 이 기록한 "no pixels skip" +
"C:\Users\...\factory_yard_2k.hdr 못 찾음" 오류의 근원이 이 datablock 이었다.)

## 6. 적용 결과 [확인]

```
before  C:\Users\User\Documents\GitHub\FoundationPose\data\pallet\hdri\factory_yard_2k.hdr   (missing)
after   //..\assets\lighting\hdri\library\factory_yard_2k.hdr                                 (exists)
resolve 후 SHA256   71d5b32c0e179f5b…  = 기대값과 일치
users               1  (변화 없음)
image datablock 수   603 -> 603  (제거 0건)
```

candidate 에서만 수행했고 원본 `.blend` 는 수정하지 않았다.
