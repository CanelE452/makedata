# Stage 2-B 이동 전 기준선

일시: 2026-07-29 / branch `chore/data-pallet-stage2b-active-assets` (0264ae4 에서 분기)

## PRE-FLIGHT [확인]

```
repo root            E:/CODING/GitHub/FoundationPose
HEAD (작업 전)         0264ae48c28e4cc6068f3e8d140ed2a3b58444c8  (= origin/main)
git status            clean
data/pallet           E:\CODING\GitHub\FoundationPose\data\pallet  (gitignored)
디스크                 E: 1.3T free / 1.9T
source↔dest 볼륨       둘 다 E:  (같은 볼륨 → rename 이동 가능)
실행 중 blender.exe    0개 (headless 생성 없음, GUI 없음)
Stage 2-A 원장 sha256  fe1adc266bd91963c7be98779ed4c114b90b0b811fabdd60471a807aeb56d101
```

## 기준 측정값 [확인, 실행함]

```
항목                        값                       기대치            일치
──────────────────────────────────────────────────────────────────────────────
registry audit              ok=21 missing=0          missing=0         ✓
default unit tests          566 passed, skip 0       ≥566, fail 0      ✓
local integration           20 passed, skip 0        ≥20, fail 0       ✓
Stage 2-A verify            146 moves / 6,921 files  146 / 6,921       ✓
                            failures 0               0                 ✓
5k dry-run accepted         4,313                    4,313             ✓
5k dry-run rejected         687                      687               ✓
distractor pool             209                      209               ✓
FrameSpec checksum          938f387dd65258e0…        938f387d…         ✓
NaN / inf                   0                        0                 ✓
data/pallet dirs            2,532
data/pallet files           363,026
data/pallet bytes           191,023,461,932
```

기계 판독용 사본: `baseline_checksums.json`
