# §10 isaac_assets 감사

```
경로            data/pallet/isaac_assets
파일 수          4,543
bytes           4,350,676,768 (4.052 GB)
확장자          .png 2375 · .usd 1857 · .jpg 200 · .hdr 73 · .mdl 30 · .last_generated 5 · .exr 2 · .txt 1
license 문서    Assets/Isaac/4.5/Isaac/Materials/Textures/Skies/PolyHaven/license.txt (1건, 하위 자산용)
                NVIDIA EULA 문서 자체는 트리 안에 없음
```

## 참조 [확인]

```
registry key                        0건 — registry 어느 키도 isaac_assets 를 가리키지 않는다
CURRENT_RUNTIME (Blender v2 경로)    0건 — v2 파이프라인은 blender_config/registry 만 읽는다
legacy runtime (Isaac Sim 계열)      config/synthetic/isaac_sim.yaml 이 data/pallet/pallet_scene ·
                                    training_data · _procedural_textures 를 가리키지만
                                    **isaac_assets 자체를 직접 참조하지는 않는다**
                                    (그 3경로도 현재 전부 부재 — stale_reference_actionable.csv)
test                                0건
```

Isaac Sim 파이프라인(`scripts/data_prep/isaac_sim/`)은 Isaac Sim 내장 Python 으로만 돌고
현재 생성기(Blender v2)와 별개다. 이 트리를 읽는 현행 runtime 경로는 확인되지 않았다.

## 라이선스·배포

```
ledger _docs/dataset_license_ledger.md:53  B6 미해결 LOW —
    "isaac_assets/(NVIDIA 창고 USD) 트리에 존재 — 배포물서 제외 필요, 소스 에셋(렌더 산출물 아님)"
ledger :30  B2 는 오탐으로 종료 — 프로덕션 blend 에 Isaac 지문 0 hit.
            즉 **렌더 산출물에는 Isaac 자산이 baked 되어 있지 않다.**
_DISTRIBUTION_EXCLUDE.txt:14  isaac_assets/   -> 등록됨, 검증기 OK
```

## 판정: **LICENSE_QUARANTINE**

근거: NVIDIA Isaac Sim EULA 재배포 제한 + ledger B6 + exclusion 등록.
현재 runtime 미사용이므로 `REPRO_REFERENCE` 성격도 함께 갖는다(Isaac 계열 재현 시 필요).
근거 충돌은 없으므로 UNKNOWN 아님.

## 이번 단계 조치: **없음 (이동 0)**

Stage 2-D1 제안(`proposed_stage2d1_moves.csv`, status=`KEEP_QUARANTINE`):
`archive/nonredistributable/nvidia/isaac_assets` 로 이동하면 격리 의도가 구조로 드러난다.
단 **이동 시 `_DISTRIBUTION_EXCLUDE.txt:14` 경로를 동시에 갱신**해야 하며, 그러지 않으면
릴리스 게이트가 조용히 무력화된다(Stage 1 에서 실제로 5/5 stale 이었던 실패 방식).
대체 CC0/CC-BY 자산: HDRI 30종·distractor 209종이 이미 확보돼 있어 파이프라인은 Isaac 자산
없이 동작한다 [확인, v2 constrained pool 28 · Dist_ 209].
