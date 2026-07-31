# v2 pilot 2k (seed 7000, full-audit) — PRE-FLIGHT

base commit `7540428a90953bbe23119321086c7dfc4320fd01` (Stage 2-D2 종료)
branch `feat/v2-pilot-2k-paper-figures` (신규, 동명 branch 없음)

## 1. 저장소 상태

```
repo root    E:/CODING/GitHub/FoundationPose
HEAD         7540428a90953bbe23119321086c7dfc4320fd01
origin/main  7540428a90953bbe23119321086c7dfc4320fd01   (일치)
dirty        _docs/history/.last-compact-resume.md  하나뿐 (허용된 것)
```

이 파일은 **수정하지 않음 / 복구하지 않음 / stage 하지 않음 / commit 대상에 넣지 않음**.

## 2. Production scene — registry 로 해석

```bash
python scripts/data_prep/blender/pallet_data_paths.py --key production_scene
```

```
E:\CODING\GitHub\FoundationPose\data\pallet\assets\scenes\production\
  blender_scene\synth_data_scene_portable_stage2c2.blend
SHA256   8cb4109adc6d321…   (기대 prefix 8cb4109a ✓)
bytes    358,898,838
```

경로를 코드·명령에 하드코딩하지 않는다. 이후 모든 실행은 registry 조회 결과를 쓴다.

## 3. Process 점검

```
blender.exe                       0개
FoundationPose/data/pallet python 0개
그 외 python 4개                   Algorithmic-Trading (다른 프로젝트) — 종료하지 않았다
```

## 4. 환경

```
OS               Windows-11-10.0.26200-SP0
Blender          5.1.1  build hash b70da489d7f4  build date 2026-04-14
Blender Python   3.13.9
Host Python      3.13.9   (conda: pallet-pose)
NumPy            2.3.5
Pillow           12.0.0
Matplotlib       3.10.6
SciPy            1.16.3
GPU              NVIDIA GeForce RTX 4070
GPU driver       32.0.15.9579
Cycles device    dataset-quality 프로필이 GPU 활성화 (vr.enable_gpu())
locale           ('Korean_Korea', '949')  preferred cp949
timezone         KST (UTC+9)
디스크 여유       1.3T / 1.9T
data/pallet      363,090 파일
```

⚠️ locale 이 `cp949` 다 — figure/CSV/JSON 출력은 전부 UTF-8 로 명시 인코딩한다.

## 5. 기준선 (전부 실제 실행)

```
항목                       기대치                    실측                          판정
──────────────────────────────────────────────────────────────────────────────────────
A registry                ok=28 missing=0           ok=28 missing=0               PASS
B unit                    >=778 skip 0              778 passed, skip 0, fail 0    PASS
C local integration       >=31 skip 0               31 passed, skip 0             PASS
D golden overlay          >=51 skip 0               51 passed, skip 0             PASS
E1 5k FrameSpec           4,313 / 687 / 938f387d    동일                          PASS
E2 5k proposal            4,439 / 3cd365ee / 12-12  동일                          PASS
F active scene no-render  8cb4109a · abs 0 ·        8cb4109a · abs 0 · missing 0  PASS
                          missing 0 · Dist_ 209     · node 누락 0 · Dist_ 209
                                                    images 603 · HDRI 30/30 ·
                                                    floor 42/42 · wood 27/27
```

렌더·저장은 하지 않았다 (`-b` 백그라운드 감사만).

## 6. 실행기 조사 — 지시의 옵션명을 그대로 믿지 않았다

§2 가 지정한 `run_v2_scene_logic.py` 의 실제 argparse 를 읽었다.

```
--out --seed --n --completion-mode {records,usable} --max-attempts
--magenta-max-fraction --start --count --samples
--render-profile {diagnostic-exact,dataset-quality} --noise-tier
--mask-profile {full-audit,public} --rerun-failures
```

지시가 요구한 `--session-usable-cap` 은 **아직 없다** → §3 에서 추가한다.

### resume 은 이미 구현돼 있다 [확인]

```python
def _resume_state(records_path, rejected_path):
    """Resume: (accepted records by usable id, next proposal index to actually run)."""
    # records.jsonl + records_rejected.jsonl 의 최대 proposal_index + 1
...
        if proposal_index < resume_from:
            continue          # replaying a previous session's stream; do not re-log
```

`iter_proposals()` 가 seed 로부터 stream 을 결정적으로 재생하고, `resume_from` 이전
proposal 은 렌더도 기록도 하지 않는다. quota 는 accept 시점에만 advance 한다
(`vp.advance_quota(quota, picks)`), 즉 replay 해도 quota 진행이 동일하다.

따라서 §3 의 `--session-usable-cap` 은 **"이번 세션에서 새로 전달한 usable 수"를 세어
루프를 조기 종료**하는 최소 변경으로 충분하다. sampling·quota·proposal 순서는 건드리지
않는다.

단, 현재 코드는 `not complete` 이면 `UsableCompletionError` 를 **raise** 한다
(비정상 종료). 세션 cap 으로 멈춘 경우는 정상 종료(exit 0)여야 하므로 그 분기를
구분해야 한다.

## 7. 이번 단계에서 바꾸지 않는 것

sampler 분포 · elevation bin · projected-size bin · 거리 상한 · f_target 분포 ·
scene mode 분포 · acceptance gate — **전부 무변경**. 기준선 5k 두 하네스의 digest
(938f387d / 3cd365ee)가 렌더 전후로 동일해야 한다.
