# §3 transaction script 강화 + §4 resolver CLI 수정

대상: `scripts/data_prep/manage_pallet_data_layout.py`, `scripts/data_prep/blender/pallet_data_paths.py`
**이번 단계에서 실제 이동은 하지 않았다.** 임시 fixture 기반 unit test 로만 검증했다.

---

## 3-A. hash mode

### 수정 전 [확인]

`snapshot()` 이 항상 selective 였고 모드 선택지가 없었다.

```
size <= 8MB  또는  확장자 in {.json,.jsonl,.csv,.md,.txt,.yaml,.yml}
             또는  파일명에 "manifest"  또는  같은 폴더 내 동일 크기 중복 후보
-> SHA256, 나머지는 unhashed 목록에 이름만 기록
```

### 수정 후

```
--hash-mode selective   (기본) 위 정책 그대로
--hash-mode all         크기·확장자 무관 전량 SHA256
                        active asset / production blend / HDRI / GLB·OBJ·USD /
                        golden reference / release package 이동 시 필수
```

manifest row 에 다음을 기록한다.

```
hash_mode  hashed_file_count  unhashed_file_count  hash_started_at  hash_completed_at
```

`all` 모드에서 해시되지 않은 파일이 하나라도 남으면 `snapshot()` 이 **RuntimeError 로 중단**한다
(정책이 깨진 채로 "전량 해시"라고 보고하지 않는다). `--verify` 도 `hash_mode=all` 인데
`pre_hash_manifest.unhashed` 가 비어 있지 않으면 실패로 센다.

### 하위호환 [확인, 실행함]

Stage 2-A 원장에는 `hash_mode` 필드가 없다. `manifest_hash_mode()` 가 이를
`"selective-legacy"` 로 읽고, **row 를 고쳐 쓰지 않는다.**

```
$ python scripts/data_prep/manage_pallet_data_layout.py --verify
verified moves : 146
files          : 6921
bytes          : 1197395529 (1.197 GB)
sha256 checked : 6921
hash modes     : selective-legacy=146
failures       : 0
```

원장 무결성(작업 전후 동일) [확인]:
`fe1adc266bd91963c7be98779ed4c114b90b0b811fabdd60471a807aeb56d101` (146 rows)

---

## 3-B. 경로 경계 검사

### 수정 전 [확인]

```python
if not _posix(os.path.abspath(src_abs)).startswith(_posix(data_root)):
```

문자열 prefix 비교라 **`data/pallet_backup` 이 `data/pallet` 안으로 잘못 판정**된다.
realpath 미사용(`..` 미접힘), normcase 미사용(Windows 대소문자).

### 수정 후

```python
def is_within(candidate, root):
    candidate_real = os.path.normcase(os.path.realpath(candidate))
    root_real = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([candidate_real, root_real]) == root_real
    except ValueError:      # 다른 드라이브
        return False
```

검사 대상: `source`, `destination`, **`destination` 의 부모**(destination 은 아직 없어서
realpath 가 부모까지만 접히므로 부모도 함께 본다).
manifest 경로는 `reports/` 에 있어 data root 밖이 정상이므로 이 검사를 적용하지 않는다.
symlink 는 기존 금지(`SYMLINK_OR_REPARSE`)를 그대로 둔다.

### 테스트 결과 [확인, 실행함]

```
data/pallet/runs            -> True
data/pallet (root 자신)      -> True
data/pallet_backup          -> False   ← 옛 startswith 로는 True 였다(테스트가 그 사실을 함께 단언)
data/pallet/../../outside   -> False
Z:\somewhere (다른 드라이브)  -> False
DATA/PALLET (대문자)         -> Windows 에서 True, POSIX 에서 False
```

---

## 3-C. transaction unit test (39개, temp dir 전용)

`tests/test_manage_pallet_data_layout.py`

```
그룹            수   내용
────────────────────────────────────────────────────────────────────────────
PathBoundary     9   위 경계 6종 + precheck 의 source/dest/prefix-collision 반영
Precheck         7   dest collision / forbidden ext / reserved name / license file /
                     empty dir / code reference / source 내부 symlink
HashMode         7   selective 는 대형 파일 unhashed / all 은 전량 해시 /
                     all 은 unhashed 0 / 타임스탬프·카운트 필드 /
                     알 수 없는 모드 거부 / legacy 판정 / legacy manifest 도 verify 통과
Transaction     15   plan 은 이동 없음 / apply 후 source 없음·dest 존재 /
                     verify 통과 / 변조·결측·추가 파일 탐지 /
                     dest 존재 시 덮어쓰지 않고 중단 /
                     부분 실패 후 상태 보존(MOVED,FAILED,PLANNED) /
                     rollback 원위치 복원 / rollback 충돌 시 중단 /
                     역순 rollback / 허용 목적지 밖 skip / move_id 접두 / same-volume
LedgerGuard      1   fixture 로 plan->apply->verify->rollback 전체를 돌려도
                     **실이동 원장 sha256 이 변하지 않음**을 단언
```

실제 Stage 2-A manifest 를 fixture 로 쓰거나 수정하지 않는다.

```
$ python -m pytest scripts/data_prep/blender/tests/test_manage_pallet_data_layout.py -q -rs
39 passed
```

새 clone(원장 없음)에서는 원장 관련 2건이 skip 되고 나머지 37건이 통과한다 —
`-rs` 로 사유가 출력되는 명시적 skip 이다.

---

## §4. resolver CLI 수정

### 수정 전 [확인]

```python
if args.audit or True:      # <- --audit 플래그가 아무 의미 없음
```

- `--audit` 무의미(항상 참)
- `--key` 경로에서도 audit 을 계산해 놓고 버림(불필요한 stat)
- 잘못된 key 는 `KeyError` traceback 그대로 노출
- `--key` 는 언제나 exit 0

### 수정 후

```
--key KEY   해당 경로만 출력하고 종료 (audit 계산 안 함). list 값은 한 줄에 하나씩.
--audit     전체 audit 출력
(인자 없음)  전체 audit 출력 (= --audit)
exit code   0 = missing 없음 / 1 = missing 있음, 잘못된 key, registry 로드 실패
잘못된 key   stderr 에 "알 수 없는 key" + 사용 가능한 key 목록, traceback 없음
```

`or True` 는 소스에서 완전히 사라졌고, 테스트가 문자열 `"or True"` 부재를 고정한다.

### 실행 확인 [확인, 실행함]

```
$ python scripts/data_prep/blender/pallet_data_paths.py            -> ok=21 missing=0, exit 0
$ python ... --audit                                               -> 위와 byte 동일 출력
$ python ... --key hdri_root                                       -> 경로 1줄, exit 0
$ python ... --key pallet_model_roots                              -> 경로 2줄, exit 0
$ python ... --key nope        -> stderr "알 수 없는 key: 'nope'" + 20개 key 목록, exit 1
```

CLI unit test 9개(인자 없음 / --audit 동일성 / --key / list key / 잘못된 key /
required missing 시 exit 1 / optional 부재 시 exit 0 / `or True` 부재 /
**fixture 안에서 해석되는지**)가 이를 고정한다.
