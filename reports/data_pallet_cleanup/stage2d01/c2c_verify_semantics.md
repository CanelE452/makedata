# Stage 2-D0.1 §5 — C2C destination addition 검증 의미 고정

## 문제

Stage 2-C2 C2C 이동(`distractors` + `blender_scene`, 2 move / 1,336 파일)은 이동 직후
strict verify 를 통과했다. 그 뒤 destination 에 파일 2개가 새로 생겼다:

```
synth_data_scene_portable_stage2c2.blend            8cb4109a…  358,898,838 B  (active scene)
synth_data_scene_portable_stage2c2_candidate.blend1 5cad94e5…  358,898,907 B  (Blender 자동 백업)
```

그래서 strict verify 는 지금 반드시 실패한다:

```
S2C2002  RELPATH_SET extra=[…stage2c2.blend, …stage2c2_candidate.blend1]
S2C2002  FILE_COUNT   175 != 173
S2C2002  TOTAL_BYTES  4,554,353,915 != 3,836,556,170
```

**중요**: 원래 옮긴 파일 쪽은 전부 정상이다 — `missing 0`, `sha256_checked 1,334`,
`moved_file_sha_mismatch 0`. 실패 3건은 전부 "추가된 2개" 때문이다.

Stage 2-D0 에서 붙였던 `--allow-destination-additions` 는 **없어진 게 없으면 extra 를
무제한 허용**했다. 이러면 나중에 destination 이 오염되거나 다른 파일이 섞여 들어와도
통과한다 — 검증력이 없다.

## 바꾼 것

### 새 인터페이스

```
--expected-destination-additions <json>     (권장)
--allow-any-destination-additions           (구 broad mode, deprecated 경고 출력)
--allow-destination-additions               단독 사용 시 argparse 오류
```

`--allow-destination-additions` 를 즉시 삭제하지 않았다(하위호환). 단독으로 쓰면
"무엇을 허용할지 명시하라"는 오류로 막는다.

### JSON 명세

`c2c_expected_additions.json` — manifest 와 **결속**된다:

```
manifest_sha256      이 원장에 대한 명세임을 못박는다. 불일치 -> 명세 오류(exit 2)
destination_root     명세가 어느 destination 것인지
expected_additions[] relative_path / size / sha256 / role
```

**"예상 extra 가 2개"라는 보고를 그대로 믿지 않았다.** 현재 destination 을 manifest 의
relpath set 과 대조해 실제 extra set 을 계산했고(→ `c2c_verify_before.json`), 그 실측
결과가 2개였다. 각 extra 의 size · SHA256 · mtime · registry role · blend 관계를 전수
기록했다.

### 검증 규칙 (전부 실패 조건)

```
manifest 의 moved file 누락                  -> 실패
manifest 의 moved file hash mismatch          -> 실패
expected addition 누락                        -> EXPECTED_ADDITION_MISSING
expected addition size 불일치                 -> ADDITION_SIZE
expected addition sha256 불일치               -> ADDITION_SHA256
allowlist 에 없는 extra                       -> UNEXPECTED_ADDITION
relative_path 가 destination 밖으로 escape    -> 명세 오류
destination root 불일치                       -> 명세 오류
manifest_sha256 불일치                        -> 명세 오류
```

## 실측 결과

```
모드                                    failures   exit
──────────────────────────────────────────────────────
strict (allowlist 없음)                      3       1     ← 정상 추가 2개 때문
exact expected-additions                     0       0     ★ 정본 검증
```

exact 모드 출력:

```
verified moves : 2
files          : 1336
sha256 checked : 1334
dest additions : 1 move(s), exact allowlist
   S2C2002  +synth_data_scene_portable_stage2c2.blend             8cb4109adc6d3213  role=active_stage2c2_scene
   S2C2002  +synth_data_scene_portable_stage2c2_candidate.blend1  5cad94e59d678b01  role=blender_automatic_backup
failures       : 0
```

## 음성 검증 — "통과시키면 안 되는 것을 실제로 막는지"

```
사례                                        기대     실측                              exit  판정
──────────────────────────────────────────────────────────────────────────────────────────────────
allowlist 에서 extra 1개 제거                실패   UNEXPECTED_ADDITION …blend1         1    PASS
--allow-destination-additions 단독           오류   argparse error (명시 요구)          2    PASS
manifest_sha256 을 0*64 로 위조              오류   actual 241f5c56… 와 불일치          2    PASS
addition sha256 을 f*64 로 위조              실패   해시 불일치로 addition 불인정        1    PASS
relative_path = ../escape.txt                오류   destination 밖으로 나감              2    PASS
```

broad allow 로 C2C verify 를 통과시키지 않았다 — 정본 검증은 exact 모드다.

## Stage 2-A/2-B 동작 불변

allowlist 옵션 없이 그대로 통과한다 (§11-F):

```
Stage 2-A     146 / 6,921   failures 0
Stage 2-B B1    4 / 3,220   failures 0
Stage 2-B B2    3 /    68   failures 0
Stage 2-B B3    0 /     0   failures 0
Stage 2-C2 C2A  3 /     3   failures 0
Stage 2-C2 C2B  1 /    74   failures 0
```

원장 파일 SHA256 전부 불변 (`baseline_checksums.json`).

## 테스트

`scripts/data_prep/blender/tests/test_destination_additions.py` 18개 신규 (전부 tmpdir).
unit 646 → 664.

## `_candidate.blend1` 의 해시가 C1 portable 과 같은 이유

`5cad94e59d678b01…` 는 Stage 2-C1 portable blend 의 해시다. candidate 를 C1 portable
에서 복제해 만든 뒤 저장했으므로, Blender 가 남긴 `.blend1` 백업은 **저장 직전 내용
= C1 portable** 이다. 이상이 아니라 예상된 동일성이다 [확인].
