# Stage 2-D1.1 §9 — BLOCKED_UNKNOWN provenance 판정

```
[판정]  4종 전부 PROVEN_NOAI
        PROVEN_REDISTRIBUTABLE 0 · UNRESOLVED_LICENSE 0
```

Stage 2-D0.1 이 "NoAI 상속을 라벨 metadata 로 확인하지 않았다"며 UNKNOWN_LICENSE 로
보류한 4종이다. 이번에 **확인했다.**

## 조사 방법 — 이름이 아니라 라벨을 읽었다

```
1  label JSON 전수 스캔 (13,122 프레임, 표본 아님, 읽기 실패 0)
     objects[].name 의 팔레트 식별자를 센다
2  NoAI 자산 식별
     Pallet_2 / Pallet_3 = scene_2.usd / scene_3.usd 유래
     = "Old Wooden Pallet"(Luka Feric, Standard+NoAI) — ledger B1
     해당 USD 가 archive/_noai_quarantine_usd/ 에 실존 (scene_2.usd · scene_3.usd)
3  생성 시점
     2026-07-24 blend 재-bake 가 NoAI 목재를 제거했다 (ledger B1: 새 blend grep
     scene_2.usd=0 · scene_3.usd=0 · Legacy_Pallet_2/3=0)
     -> mtime 이 그 이전이면 NoAI 목재가 baked 된 blend 로 렌더된 것
4  부모와의 frame identity
     부모 dataset 에 바이트 동일한 프레임이 있는지 (복사본 여부)
5  생성 로그 · 배경 자산 기록
```

## 결과 (전수)

```
move_id  dataset                          label   frames  NoAI 프레임      %   mtime        pre-rebake
──────────────────────────────────────────────────────────────────────────────────────────────────────
D1-041   training_data_v4_split_GREYBUG    5,000   5,000     3,286      65.7%  2026-06-17      yes
D1-042   training_data_v4_split_bg1bak     5,000   5,000     3,272      65.4%  2026-06-16      yes
D1-043   training_data_v4_emptywood        3,000   3,000     3,000     100.0%  2026-06-18      yes
D1-049   training_data_v4_pilotA             122     120        76      63.3%  2026-06-16      yes
```

팔레트 이름 분포:

```
D1-041   Pallet_1=1,714 · Pallet_2=1,679 · Pallet_3=1,607
D1-042   Pallet_1=1,728 · Pallet_2=1,669 · Pallet_3=1,603
D1-043   Pallet_2=1,488 · Pallet_3=1,512          ← Pallet_1 없음, 전부 NoAI
D1-049   Pallet_1=44 · Pallet_2=41 · Pallet_3=35
```

실제 라벨 한 프레임 (`training_data_v4_emptywood/train_batch_000/000000.json`):

```
objects[0].class = pallet
objects[0].name  = Pallet_2        ← NoAI 자산
camera_data.background_asset = industrial
```

## 판정 — PROVEN_NOAI (4/4)

각 dataset 의 **자기 라벨에 NoAI 팔레트 사용이 기록돼 있다.** "NoAI 표식이 없다"는
소극적 근거가 아니라 **적극적 사용 증거**다.

```
근거 4중
  ① 라벨 전수 스캔 — 63.3~100% 프레임이 objects[].name 에 Pallet_2/Pallet_3
  ② Pallet_2/3 = scene_2/3.usd = NoAI "Old Wooden Pallet" (ledger B1 명시)
     + 해당 USD 가 격리 폴더에 실존
  ③ mtime 2026-06-16~18 = 2026-07-24 재-bake(NoAI 제거) 이전
  ④ 읽기 실패 라벨 0 (표본이 아니라 전수)
```

### 반대 증거도 검토했다

```
부모와 바이트 동일 프레임 : 0/200 (4종 전부)
```

즉 부모(`training_data_v4` / `_v4_split`)의 **복사본이 아니라 별도 렌더**다. 그러나
NoAI 판정 근거는 복사 여부가 아니라 **자기 라벨에 기록된 팔레트 자산**이므로 판정은
바뀌지 않는다. 오히려 "독립 렌더인데도 NoAI 팔레트를 썼다"는 것이 더 직접적인 증거다.

`README_CONTAMINATION.md` 는 부모 2종에만 있고 파생 4종에는 없다 — 그래서 D0.1 이
"확인하지 않았다"고 한 것이다. 표식 부재가 무죄 근거가 아님을 이번 스캔이 보여준다.

### UNRESOLVED_LICENSE 로 남긴 것 없음

4종 모두 부모가 명확하고(이름 접두 + 같은 생성 파이프라인 라벨 스키마) NoAI 사용이
직접 증명됐다. 증거 충돌이나 metadata 부족은 없었다.

## 목적지

```
PROVEN_NOAI -> data/pallet/archive/legacy_datasets/noai_baked/<name>
```

`nonredistributable/unknown_license/` 는 **쓰지 않는다** — UNRESOLVED 가 0건이다.

```
D1-041  -> archive/legacy_datasets/noai_baked/training_data_v4_split_GREYBUG
D1-042  -> archive/legacy_datasets/noai_baked/training_data_v4_split_bg1bak
D1-043  -> archive/legacy_datasets/noai_baked/training_data_v4_emptywood
D1-049  -> archive/legacy_datasets/noai_baked/training_data_v4_pilotA
```

부모 2종(`training_data_v4` · `_v4_split`)이 Stage 2-D1 D1C 에서 이미 그 위치로 갔으므로
파생도 같은 곳에 모인다 — 라이선스 등급이 같은 것끼리 모이는 배치다.

## 릴리스

```
release_allowed  NO — 공개 릴리스 불가 (4종 전부)
exclusion        현재 옛 경로로 등록돼 있다 (EXCLUDED)
                 이동 시 새 경로로 정정해야 한다
```

**redistributable 로 표현하지 않는다. 삭제하지 않는다.**

## ★ 이동은 미실행 — hash 예산

판정은 끝났지만 실이동은 하지 않았다. 4종 14.52 GiB × 2 = **29.04 GiB** 로 §6 전역 상한
20 GiB 를 넘는다 (§17 중단 기준). 예산 결정 후 아래 명령으로 실행할 수 있다.

```
python scripts/data_prep/manage_pallet_data_layout.py --plan \
  --policy stage2d11-residual-finalization \
  --d11-scope reports/data_pallet_cleanup/stage2d11/frozen_scope.json \
  --d11-scope-sha256 <hex> \
  --cohort D11C_LICENSE_RESOLUTION --hash-mode all \
  --d11-license-decision PROVEN_NOAI \
  --d11-provenance-evidence "라벨 전수 스캔 NoAI 63.3~100% + ledger B1 + pre-rebake mtime" \
  --manifest reports/data_pallet_cleanup/stage2d11/transactions/d11c_license_resolution.jsonl \
  --max-hash-read-gib 30            # ← 예산 상향 승인 필요
```

이동 후 `_DISTRIBUTION_EXCLUDE.txt` 의 4개 경로를
`archive/legacy_datasets/noai_baked/<name>/` 로 정정하고 verifier 를 다시 돌려야 한다.
