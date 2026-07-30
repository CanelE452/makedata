# §18 memory · 문서 상태 갱신 계획

## 현재 memory 중 사실과 충돌하는 문장 [확인]

```
memory 파일                          오래된 문장                                    현재 사실
──────────────────────────────────────────────────────────────────────────────────────────────────────
stage2c1-portable-blend.md           "active production scene 은                     active = ...
                                      synth_data_scene_portable.blend"                 _stage2c2.blend
                                     "★ Stage 2-C2 에서 distractors/blender_scene    Stage 2-C2 완료 —
                                      을 옮기려면 356+158 을 rebase 해야 한다"          rebase 완료
                                     "미해결: portable_candidate_20260729.blend1       역할 확정됨
                                      정리 대상"                                        (ROLLBACK_CRITICAL,
                                                                                        원본과 byte-identical)
                                     "reports/.../stage2c1/ 17.5MB gitignore 대상      commit 완료
                                      아니라 commit 전 판단 필요"                        (26f2194)
                                     "commit/push 미실행, HEAD 여전히 e72a719"          75a3f71 까지 push 완료
──────────────────────────────────────────────────────────────────────────────────────────────────────
dryrun-5k-two-harnesses.md           (충돌 없음 — 두 하네스 값은 그대로 유효)
machine-role-synth-only.md           (충돌 없음)
v2-blend-integration.md              (충돌 없음)
```

`stage2c2-final-layout` 이라는 memory 는 **아직 없다** — Stage 2-C2 를 끝낸 뒤 사용자에게
갱신 여부를 물었고 답을 받지 않은 상태다.

## 갱신 계획

### 1. `stage2c1-portable-blend.md` → 갱신 (덮어쓰기 아님, 사실 정정)

```
- active scene 을 stage2c2.blend 로 정정
- rollback 사슬 3단(stage2c2 -> stage2c1 portable -> original)과 각 sha256 기록
- "Stage 2-C2 rebase 필요" 미해결 항목 -> 해소로 표시
- .blend1 역할 확정(ROLLBACK_CRITICAL, 원본과 byte-identical) 반영
- commit/push 상태 갱신 (26f2194 / 75a3f71)
```

### 2. `stage2d0-archive-audit.md` 신규 (project)

```
- archive/ semantic 하위폴더 7개가 비어 있고 dataset 156개가 depth1 에 평평하게 있다
- 최상위 ZIP 14개 + archive 내 6개 = 20 archives / 84.92 GB, 손상 1건(truncated)
- ★ ZIP 끼리 CRC 대조로 "이름·크기 같아도 내용이 다르다" 를 확정 — 중복 처리 불가
- weight 29개 전부 고유 SHA256, ACTIVE 1 / REPRO 24 / UNREFERENCED 4
- broken reference 2건: net_pallet_best.pth · ndds3_pallet.pth
- LEVEL 4 CRC 전수는 55.18GB 로 예산 초과 -> 승인 대기
```

### 3. 이번 단계에서 갱신 가능한 tracked 문서

```
_docs/data_pallet_layout.md              archive 실제 구조(빈 skeleton) 반영
reports/data_pallet_cleanup/README.md    stage2d0 산출물 목록 추가
```

과거 history(`_docs/history/2026-07-28.md`, `2026-07-29.md`)의 당시 내용은 **수정하지 않는다.**

## 주의 — memory 는 "그때 참이었던 것" 이다

Stage 2-C1 memory 가 지금 틀린 건 잘못 쓴 게 아니라 그 뒤에 상태가 바뀐 것이다.
갱신할 때 "왜 바뀌었나" 를 남겨 다음 세션이 되짚을 수 있게 한다.
