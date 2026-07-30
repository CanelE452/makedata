# D1D_BLEND_BACKUPS — ★ 실행했으나 rollback (앞선 원장 충돌)

```
[판정]  ROLLED_BACK / BLOCKED
        10건 apply·verify 까지 성공했지만 Stage 2-C2 C2C 원장의 verify 를 깨뜨려
        §18 중단 기준에 걸렸다. D1D 만 역순 rollback 했다.
        이 10건은 이번 단계에서 이동하지 않는다.
```

## 대상 (계획 10건 / 2,400,984,463 B = 2.24 GiB)

```
move_id  파일                                                   destination
──────────────────────────────────────────────────────────────────────────────────
D1-004   _sandbox_parking_lot_check.blend1                      legacy_scenes/blender_backups/
D1-005   synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend   legacy_scenes/snapshots/
D1-006   synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend   legacy_scenes/snapshots/
D1-007   synth_data_scene.REBAKE_WIP.blend                       legacy_scenes/snapshots/
D1-008   synth_data_scene.REBAKE_WIP.blend1                      legacy_scenes/blender_backups/
D1-010   synth_data_scene.blend1                                 legacy_scenes/blender_backups/
D1-011   synth_data_scene12.blend                                legacy_scenes/snapshots/
D1-012   synth_data_scene12.blend1                               legacy_scenes/blender_backups/
D1-013   synth_data_scene121.blend                               legacy_scenes/snapshots/
D1-014   synth_data_scene_indoor.blend                           legacy_scenes/snapshots/
```

## 이동 전 보호 조건 전수 확인 [확인]

`.blend1` 이라는 이유로 옮기지 않았다. 계획과 **SHA256 identity** 로 판단했다.

```
move_id  D0 분류        registry 참조  runtime/test 참조  SHA256 identity
────────────────────────────────────────────────────────────────────────
10건 전부 COLD_ARCHIVE      0              0              전부 일치
```

active(2) · rollback-critical(4) blend 6개는 계획에서 KEEP 이므로 애초에 선택되지 않았다.

## 실행 결과

```
plan     10 moves / hashed 10 / unhashed 0 / pre read 2.24 GiB / 1.8s
apply    10 moves / 0.1s
verify   failures 0 / sha256 checked 10 / post read 2.24 GiB / 1.8s
예산      4.47 / 6 GiB (74.5%)
```

여기까지는 **성공**이었다. 문제는 그 다음 cohort 회귀 검증에서 나왔다.

## ★ 실패 — Stage 2-C2 C2C exact verify 가 11건 실패

```
S2C2002  RELPATH_SET_MISSING ['_sandbox_parking_lot_check.blend1',
                              'synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend',
                              'synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend',
                              'synth_data_scene.REBAKE_WIP.blend',
                              'synth_data_scene.REBAKE_WIP.blend1']
S2C2002  MISSING synth_data_scene.blend1
S2C2002  MISSING synth_data_scene.POSTBAKE_CLEAN_20260724_191902.blend
S2C2002  MISSING synth_data_scene.PREBAKE_BACKUP_20260724_181050.blend
S2C2002  MISSING synth_data_scene.REBAKE_WIP.blend
S2C2002  MISSING synth_data_scene.REBAKE_WIP.blend1
S2C2002  MISSING synth_data_scene12.blend
S2C2002  MISSING synth_data_scene12.blend1
S2C2002  MISSING synth_data_scene121.blend
S2C2002  MISSING synth_data_scene_indoor.blend
S2C2002  MISSING _sandbox_parking_lot_check.blend1
```

### 원인 [확인]

이 10개 blend 는 **Stage 2-C2 C2C 이동(S2C2002)의 구성원**이다. C2C 는
`data/pallet/blender_scene` → `data/pallet/assets/scenes/production/blender_scene`
로 173개 파일을 옮겼고, 그 안에 이 10개가 들어 있다.

D1D 가 그것들을 C2C destination **밖으로** 빼내자 C2C 의 불변식
"우리가 옮긴 파일이 하나도 없어지지 않았다"가 깨졌다.

**데이터는 안전했다** — D1D 원장이 새 위치와 SHA256 을 기록하고 있었고 verify 도
통과했다. 깨진 것은 데이터가 아니라 **검증 사슬**이다: C2C 원장 하나만으로는
그 파일들이 어디 있는지 증명할 수 없게 된다.

### 왜 완화하지 않았는가

`--expected-destination-additions` 처럼 "예상된 제거"를 허용하는 옵션을 만들면 통과할
수 있다. 그러나

- §18 이 "C2C exact verify 실패"를 중단 기준으로 명시한다
- 원장 연쇄(chained ledger — "이 파일은 다른 원장이 이어받았다")는 검증 의미를 바꾸는
  설계 변경이고 이 단계의 범위가 아니다
- 임계값 완화·실패 은닉 금지

그래서 **rollback** 을 택했다.

## rollback 결과 [확인]

```
rolled back                      10 moves
blend 17개 원위치                 assets/scenes/production/blender_scene/ 에 17개
legacy_scenes/{snapshots,blender_backups}  비어 있음 (폴더는 삭제하지 않았다)
C2C exact verify                 failures 0  (복구 확인)
보호 blend 6개 SHA256            전부 불변
```

## 재발 방지 — 계획 단계 guard 를 코드에 넣었다

`manage_pallet_data_layout.py`:

```python
PRIOR_LEDGERS = (stage2a, stage2b b1/b2/b3, c2a, c2b, c2c)
prior_ledger_members()        # 앞선 원장이 "여기 있어야 한다"고 주장하는 (dest, relpath)
find_prior_ledger_conflict()  # source 가 그 구성원이면 충돌
```

D1 계획 단계에서 충돌이 있으면 **exit 2 로 거부**한다. 실제로 D1D 를 다시 계획하면:

```
계획 거부: 앞선 트랜잭션 원장의 구성원을 그 destination 밖으로 옮기려 합니다:
  D1-004 (…/blender_scene/_sandbox_parking_lot_check.blend1)
  원장 …/c2c_distractor_scene.jsonl / S2C2002 — 그 원장이 옮긴 파일: _sandbox_parking_lot_check.blend1
  옮기면 그 원장의 verify 가 MISSING 으로 실패합니다(검증 사슬 끊김).
  원장 연쇄(chained ledger) 없이는 이동하지 않습니다.
```

신규 테스트 4개(`PriorLedgerConflict`) — 그중 하나는 **실제 저장소 원장**으로
"C2C destination 안의 blend 는 이동 금지, `pallet.zip` 은 아님"을 고정한다.

## 전수 재검사 결과 — 충돌은 D1D 에만 있다 [확인]

계획 40건 전부를 앞선 원장 7개와 대조했다.

```
cohort                충돌
────────────────────────────
D1B_CORRUPT            0
D1D_BLEND_BACKUPS     10   ← 전부
D1A_PACKAGES           0
D1C_LEGACY_DATASETS    0
```

그래서 D1A·D1C 는 그대로 진행할 수 있었다.

## 이 10건을 옮기려면 (다음 단계 제안)

선택지 두 가지. **둘 다 이 단계의 범위 밖이고 승인이 필요하다.**

1. **원장 연쇄(chained ledger)** — verify 에 "이 파일은 원장 X 가 이어받았다"를
   증명 가능한 형태로 도입한다. C2C verify 가 D1D 원장을 따라가 SHA256 까지 확인하면
   사슬이 유지된다. 가장 정합적이지만 verify 의미를 확장하는 설계 변경이다.
2. **C2C 원장 재작성 금지 원칙을 유지한 채 그대로 둔다** — cold blend 10개가
   `assets/scenes/production/blender_scene/` 에 남는다. 기능상 문제는 없고
   "현역 폴더에 cold 파일이 섞여 있다"는 정리 미완만 남는다.
