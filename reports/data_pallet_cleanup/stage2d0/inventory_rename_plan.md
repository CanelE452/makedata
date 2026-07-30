# §17 inventory.csv 명칭 정정 계획

## 현재 파일 [확인]

```
reports/data_pallet_cleanup/inventory.csv        220,480 bytes  (Stage 1, 2026-07-28)
reports/data_pallet_cleanup/_inventory_raw.csv                  (전 파일 raw dump)
```

`inventory.csv` 는 **전 파일 manifest 가 아니다** — 디렉토리·그룹 단위 집계다.
data/pallet 는 363,090 파일이고 220KB 로는 담을 수 없다. 전 파일 목록은
`_inventory_raw.csv` 쪽이다. 이름이 내용을 잘못 알려주고 있어
`grouped_inventory.csv` 로 바꾸는 것이 맞다 [판정].

## 현재 참조 [확인]

```
참조처                                     성격
──────────────────────────────────────────────────────────────────
reports/data_pallet_cleanup/README.md      문서 텍스트 (산출물 목록)
_docs/history/2026-07-28.md                HISTORY — 수정 금지
CURRENT_RUNTIME (.py/.sh/.yaml)            0건 — 코드가 읽지 않는다
CURRENT_TEST                               0건
```

코드·테스트 참조가 0이므로 rename 은 **문서 1곳만 고치면 된다.**

## rename 영향

```
required script changes   없음
required doc changes      reports/data_pallet_cleanup/README.md 의 산출물 목록 1줄
backward compatibility    불필요 (읽는 코드가 없다)
history 소급 수정          하지 않는다 — 2026-07-28 기록은 당시 이름이 정본이다
```

## 이번 단계 조치: **rename 하지 않음**

`git mv` 는 데이터 이동이 아니지만, Stage 2-D0 는 "이름 정정 계획만 출력" 을 지시했다.
다음 중 하나로 수행한다.

1. **Stage 2-D1 과 함께** (권장 — 같은 정리 맥락, 리뷰 단위가 하나)
2. 별도 tracked-only commit (`git mv` + README 1줄, history 미수정)

두 경우 모두 `_inventory_raw.csv` 는 이름을 바꾸지 않는다 — 그쪽은 실제 전 파일 raw 이므로
현재 이름이 내용과 맞다.
