# §5 Stage 2-C2 transaction policy

`scripts/data_prep/manage_pallet_data_layout.py --policy stage2c2-final-layout`

기존 정책(`stage2a-runs`, `stage2b-active-assets`)은 그대로 두고 신규 정책만 추가했다.
Stage 2-A/2-B 원장은 읽기만 하고 재작성하지 않는다.

## 도구가 새로 갖게 된 능력

```
능력                    이유
────────────────────────────────────────────────────────────────────────────────────────
file entry             Stage 2-A/2-B 는 directory 만 옮겼다. background 안의 원본 ZIP 은
(entry_kind=file)      폴더째가 아니라 **파일 단위**로 떼어내야 해서 필요했다.
                       snapshot_file / precheck_file / apply / verify / rollback 전부 대응.
transaction_group      distractors 와 blender_scene 은 함께 가야 의미가 있다(blend 의 상대참조가
+ group rollback       distractors 를 가리킨다). 한쪽만 옮겨진 상태로 끝나면 안 되므로,
                       그룹 안에서 실패하면 이미 옮긴 것을 역순으로 되돌린다.
archive cohort 제한     ZIP 은 C2A 에서만 허용. directory cohort 계획 시 source 안에 archive 가
                       하나라도 있으면 ARCHIVE_IN_NON_PACKAGE_COHORT 로 거부한다.
```

### 기존 계약을 깨지 않기 위해 한 일 [확인]

group rollback 을 처음 넣었을 때 `transaction_group` 이 없는 Stage 2-A row 를 `cohort` 로
묶어버려, **"실패하면 그 자리에서 멈추고 이미 옮긴 것은 둔다"** 라는 Stage 2-A 계약이 깨졌다
(`test_apply_stops_at_the_first_failure_and_keeps_manifest_state` 가 잡았다).
→ 그룹 원자성은 **명시적 `transaction_group` 이 있는 row 에만** 적용하도록 고쳤다.

## cohort / 이동 규칙

```
cohort                      entry   source                        destination
─────────────────────────────────────────────────────────────────────────────────────────────────
C2A_BACKGROUND_PACKAGES     file    background 아래 archive 파일     archive/packages/background_sources/
                                    (실측으로 결정, 하드코딩 없음)     + **같은 상대경로 보존** (평탄화 금지)
C2B_BACKGROUND_ASSET        dir     data/pallet/background          assets/scenes/backgrounds/background
C2C_DISTRACTOR_SCENE        dir     data/pallet/distractors         assets/distractors/library
C2C_DISTRACTOR_SCENE        dir     data/pallet/blender_scene       assets/scenes/production/blender_scene
```

```
정책 값
  allowed_dest_prefixes    assets/ · archive/packages/background_sources/
  forbidden_ext            .pt .pth .ckpt .onnx .engine .trt .safetensors  (weight/checkpoint)
  archive_allowed_cohorts  C2A_BACKGROUND_PACKAGES 만
  require_hash_mode        all  (selective 로 계획하면 exit 2)
  max_single / max_total   10 GB
  license_is_blocker       False (자산과 함께 보존해야 하므로 blocker 아님 — 대신 verify 대상)
  move_id_prefix           S2C2
  같은 볼륨 rename만        copy 후 삭제 / copytree 미사용
  destination overwrite    금지 (있으면 DEST_COLLISION 으로 중단)
  symlink/reparse          거부
  path escape              is_within(realpath+normcase+commonpath) 로 차단
```

## 신규 테스트 (`tests/test_stage2c2_layout_policy.py`, 30개)

실제 `data/pallet` 을 쓰지 않고 tmpdir fixture 위에서만 돈다.

```
그룹                        고정한 것
──────────────────────────────────────────────────────────────────────────────────
PolicyShape (6)            정책 등록 · hash all 강제 · weight 금지 · destination exact ·
                           distractors/blender_scene 이 같은 group · 그룹 필수 source 2개
FileEntry (6)              snapshot_file / precheck_file (파일 수용, 디렉토리 거부,
                           destination 충돌 거부) / archive 스캔(중첩 포함, 없으면 빈 목록)
C2APackages (5)            상대경로 보존(평탄화 아님) · file entry + hash all ·
                           apply/verify · rollback 이 원래 상대경로로 복원 · 변조 시 verify 실패
ArchiveOnlyInPackage (2)   ZIP 남아 있으면 background directory 계획 거부,
                           C2A 적용 후에는 통과
C2CGroupAtomicity (6)      한쪽만 있으면 계획 거부 · 둘 다 있으면 계획 · 두 번째 실패 시
                           첫 번째까지 롤백 · 함께 apply/verify · 역순 rollback · license 보존
HashModeIsForced (2)       selective 거부 · 모든 row unhashed 0
LegacyContractUnchanged(3) entry_kind 기본값 directory · cohort 를 그룹으로 쓰지 않음
                           (Stage 2-A 부분 이동 계약 보존)
```

기존 `test_manage_pallet_data_layout.py` 39개 전부 통과(회귀 0), 전체 unit 646.
