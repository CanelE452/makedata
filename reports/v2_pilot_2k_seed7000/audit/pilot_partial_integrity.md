# §5 데이터 무결성 — 중단 시점 1,449장 전수

```
usable_id                0..1448   연속 True
missing                        0
duplicate                      0
파일 수      rgb 1449 · labels 1449 · mask_amodal 1449 · mask_visible 1449
             전부 N 과 일치         True
corrupt RGB / label / mask     0 / 0 / 0
empty amodal                   0
visible ⊆ amodal 위반           0
magenta frame                  0
camera distance > 10 m         0
record ↔ label path mismatch   0
annotation invalid             0
reprojection error   median 8.04e-14   p95 1.61e-13   max 1.46e-11 px
                     serialization gate 1e-4          통과 True
_incomplete_attempts 파일       0     (프레임 경계에서 멈춰 부분 산출물이 없다)
```

## 중단 절차 기록

```
1. wrapper(python PID 34216) 만 종료 → 다음 100-frame session 시작 차단
   Blender 는 건드리지 않음 (subprocess.run 은 job object 를 쓰지 않아 자식이 생존)
2. Blender(PID 31780) 에 cooperative interrupt (AttachConsole + CTRL_BREAK_EVENT)
   taskkill /F 미사용 · process tree 강제 종료 미사용
3. 종료 시각에 records.jsonl 과 progress.json 이 **같은 시각(00:10:24)에 flush** →
   프레임 경계에서 정지했음을 파일 mtime 으로 확인
4. accepted record 와 연결되지 않은 부분 산출물: 0 건 (격리 이동 대상 없음)
5. accepted frame 은 수정·재렌더·rename 하지 않음
```

**데이터는 완전하다.** 이 1,449장은 generator 수정 전 baseline 으로 그대로 쓸 수 있다.

기계 판독용: `pilot_partial_integrity.json`
