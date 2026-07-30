# Stage 2 이동 작업용 rollback 계획

- 작성일: 2026-07-28 (Stage 1 — 조사·계획 단계에서 미리 작성)
- 적용 대상: `reports/data_pallet_cleanup/proposed_moves.csv` 의 `status=SAFE_CANDIDATE` 항목
- **이 문서의 어떤 절차에도 삭제 명령(`rm`, `rmdir`, `del`, `Remove-Item`, `git rm`)은 포함하지 않는다.**
  rollback 은 언제나 "역방향 이동"으로만 수행한다.

---

## 0. 전제

- `data/pallet` 전체가 gitignored (`.gitignore:5 data/`) → **git 으로는 되돌릴 수 없다.**
  따라서 rollback 의 유일한 근거는 아래 **이동 원장(move ledger)** 이다.
- 원본과 목적지가 같은 볼륨(E:)이므로 이동은 rename 이며, 데이터 복사가 발생하지 않는다.
  → 중단 시 "절반만 복사된 파일"은 생기지 않지만, "절반만 옮겨진 디렉토리"는 생길 수 있다.
- 여유 공간: E: 1.3 TB free / 1.9 TB (33% 사용). 같은 볼륨 rename 이므로 추가 공간 요구는 0.

---

## 1. 이동 1건마다 기록할 원장 스키마

`reports/data_pallet_cleanup/move_ledger.csv` (Stage 2 에서 생성)

```
컬럼                     내용
────────────────────────────────────────────────────────────────────────
move_id                 proposed_moves.csv 의 move_id (M001…)
executed_at             ISO8601
source                  이동 전 경로 (data/pallet/…)
destination             이동 후 경로 (data/pallet/…)
pre_file_count          이동 전 재귀 파일 수
pre_total_bytes         이동 전 재귀 총 bytes
pre_manifest_sha256     이동 전 파일목록+크기 매니페스트의 SHA256 (아래 2절)
post_file_count         이동 후 재귀 파일 수
post_total_bytes        이동 후 재귀 총 bytes
post_manifest_sha256    이동 후 매니페스트 SHA256
sample_sha256_pre       표본 파일 N개의 개별 SHA256 (경로:해시 세미콜론 구분)
sample_sha256_post      동일 표본의 이동 후 SHA256
verdict                 OK / MISMATCH
rollback_command        역방향 이동 명령 (문자열로 그대로 보관)
code_changes_commit     이 이동에 동반한 코드/설정 커밋 SHA
```

## 2. 매니페스트 정의 (전 파일 해시 대신 사용)

data/pallet 전체 해시는 191 GB 재독이라 비현실적이다. 대신 **경로+크기+mtime 매니페스트**를 쓴다.

```
매니페스트 1줄 = "<디렉토리 기준 상대경로>\t<bytes>\t<mtime_ns>"
정렬 = 상대경로 오름차순 (locale 무관, 바이트 순)
manifest_sha256 = 위 텍스트(UTF-8, LF)의 SHA256
```

전체 SHA256 은 다음 경우에만 계산한다.
- 파일 크기 ≤ 8 MB 인 파일 전부
- 크기가 8 MB 를 넘어도 **표본 추출된 파일**(디렉토리당 최대 20개, 최소 3개)
- 이동 대상이 단일 파일인 경우(`*.blend`, `*.zip`)는 **크기 무관 전량 해시**

> Stage 1 인벤토리에서 이미 3,000개 파일의 SHA256 을 계산해 `grouped_inventory.csv` 에 넣어 두었다
> (`hash_status` = OK / SKIPPED_LARGE). Stage 2 의 pre-hash 는 이 값과 먼저 대조한다.

## 3. 이동 1건의 표준 순서

```
[1] pre 스냅샷      : file_count / total_bytes / manifest_sha256 / sample sha256 기록
[2] 목적지 확인     : 목적지가 이미 존재하면 중단(덮어쓰기 금지). 존재하지 않을 때만 생성.
[3] 이동           : 같은 볼륨 rename (복사 후 삭제 금지 — 삭제 단계를 만들지 않는다)
[4] post 스냅샷     : 동일 지표 재계산
[5] 판정           : pre == post 아니면 즉시 [R1] 실행
[6] 코드/문서 갱신  : required_code_changes / required_doc_changes / required_test_changes 적용
[7] 검증           : 아래 4절 게이트 전부 통과해야 다음 move 진행
```

**한 번에 1건씩.** 배치 이동 금지 — 실패 시 어느 지점에서 깨졌는지 특정할 수 없다.

## 4. 이동 후 검증 게이트 (전부 통과해야 다음 단계)

```
게이트                          명령 / 확인 방법                                       실패 시
──────────────────────────────────────────────────────────────────────────────────────────────
G1 파일 수·바이트 일치          post == pre                                            R1
G2 매니페스트 해시 일치         post_manifest_sha256 == pre_manifest_sha256            R1
G3 단위 테스트                  cd scripts/data_prep/blender && python -m pytest tests -q   R2
G4 golden fixture 미-skip       pytest tests/test_overlay_archive_trunc_style.py -q -rs
                                → "skipped" 0 이어야 함 (★ skipUnless 라 조용히 skip 됨)   R2
G5 config 로드                  python -c "import sys;sys.path.insert(0,'scripts/data_prep/blender');
                                import blender_config as c;print(c.HDRI_DIR,c.PALLET_SOURCE_DIR)"
                                → 출력 경로가 실제로 존재해야 함                          R2
G6 manifest 로드                python -c "...; import distractor_pool_v2 as d;
                                print(len(d.load_pool()))" → 209                        R2
G7 blend 텍스처 무결            blender -b <blend> --python-expr
                                "import bpy;print([i.filepath for i in bpy.data.images if not i.has_data])"
                                → 빈 리스트                                             R2
```

## 5. rollback 절차

### R1 — 이동 직후 지표 불일치 (코드 수정 전)

```
1) 즉시 후속 이동 중단
2) rollback_command 실행 = destination → source 로 역방향 rename
3) 역방향 이동 후 file_count / total_bytes / manifest_sha256 를 pre 값과 재대조
4) 일치하면 원장에 verdict=MISMATCH, rolled_back=yes 기록하고 해당 move_id 를 BLOCKED 로 강등
5) 불일치가 남으면 그 시점에서 **모든 작업을 중단하고 사용자에게 보고** (자동 복구 시도 금지)
```

### R2 — 코드 수정까지 반영한 뒤 테스트 실패

```
1) 코드/설정 변경 revert:
     git revert <code_changes_commit>        (커밋이 push 되지 않았다면 git reset --soft HEAD~1 후 재작업)
   → 파괴적 옵션(reset --hard) 금지. 사용자 승인 없이는 어떤 revert 도 push 하지 않는다.
2) rollback_command 로 파일 역방향 이동
3) G3~G7 재실행하여 원복 상태가 이동 전과 동일한지 확인
4) 원장에 실패 원인 기록 후 해당 move_id 를 BLOCKED_BY_CODE_REFERENCE 로 강등
```

### R3 — 여러 move 를 진행한 뒤 뒤늦게 문제 발견 (전체 rollback)

```
1) move_ledger.csv 를 executed_at 역순으로 정렬
2) 마지막 이동부터 **역순으로 1건씩** R1/R2 절차 적용
   (역순이 아니면 중첩 이동에서 목적지 충돌 발생)
3) 각 건마다 G1/G2 통과를 확인한 뒤 다음 건으로 진행
4) 전부 되돌린 뒤 Stage 1 스냅샷과 최종 대조:
     - 디렉토리 2,489 / 파일 363,015 / 191,023,311,090 bytes
     - reports/data_pallet_cleanup/grouped_inventory.csv 의 sha256(hash_status=OK) 전량 재검증
```

## 6. Stage 1 기준선 (rollback 최종 대조값)

```
항목                    값                     근거
──────────────────────────────────────────────────────────────────────────
디렉토리 수             2,489                  directories.csv 행 수
파일 수                 363,015                grouped_inventory.csv / os.walk 집계
총 bytes                191,023,311,090        os.walk 집계 (191.02 GB)
SHA256 계산 완료 파일    3,005                  grouped_inventory.csv hash_status=OK
빈 디렉토리             400                    grouped_inventory.csv is_empty=true
git 상태                clean (HEAD ff972c2)   git status --porcelain 무출력
```

## 7. 절대 하지 않는 것

- 원본을 지우고 목적지에 복사본을 남기는 방식(복사→삭제)의 이동
- 목적지가 이미 존재할 때 덮어쓰기
- 중복이라고 판단한 파일 삭제 (duplicate_groups.csv 는 전부 `deletion_recommended=false`)
- symlink / junction 으로 구 경로를 살려두기 (조용한 이중 진실 생성)
- 한 커밋에 여러 move + 코드 수정 묶기
