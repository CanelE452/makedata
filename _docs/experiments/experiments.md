# 11. 실험 설계

## 11.1 Table 1: 핵심 비교 — Self-Training 전략 (Real Test, Seen Pallet)

| Method                               | ADD (%) ↑ | Reproj (px) ↓ | 5cm5° (%) ↑ |
| ------------------------------------ | --------- | -------------- | ----------- |
| Synthetic-only (하한선)              | ?         | ?              | ?           |
| + Finetuning (필터 없음)             | ?         | ?              | ?           |
| + Finetuning (confidence 필터)       | ?         | ?              | ?           |
| + Finetuning (필터 A)                | ?         | ?              | ?           |
| + Finetuning (필터 A+B)              | ?         | ?              | ?           |
| + Finetuning (필터 A+B+C) **(Ours)** | ?         | ?              | ?           |
| Fully supervised (상한선)            | ?         | ?              | ?           |

## 11.2 Table 2: 일반화 성능 (Seen vs Unseen)

| Method             | Seen ADD (%) ↑ | Unseen ADD (%) ↑ | Δ Unseen |
| ------------------ | -------------- | ---------------- | -------- |
| Synthetic-only     | ?              | ?                | baseline |
| Ours (A+B+C)       | ?              | ?                | ?        |

## 11.3 Table 3: Geometric Filter Ablation

| Filter 구성              | PL 채택률 | PL 정확도 | 최종 ADD ↑ |
| ------------------------ | --------- | --------- | ---------- |
| No filter                | ?         | ?         | ?          |
| 필터 A만                 | ?         | ?         | ?          |
| 필터 A+B                 | ?         | ?         | ?          |
| 필터 A+B+C (Ours)        | ?         | ?         | ?          |

## 11.4 추가 실험 (선택)

| Method                               | ADD (%) ↑ | 비고 |
| ------------------------------------ | --------- | ---- |
| Ours (Self-Training only)            | ?         | 메인 방법 |
| + Adversarial DA 추가               | ?         | DA 결합 시 추가 효과? |

## 11.5 Sigma Sensitivity (Optional)

| sigma | Belief Peak (px) | Val PCK@3px (%) | 비고 |
| ----- | ---------------- | --------------- | ---- |
| 0.5   | ~1               | ?               | gradient vanishing 예상 |
| 2.0   | ~13×13           | ?               | 중간 |
| 4.0   | ~25×25           | ?               | DOPE 공식 기본값 |

## 11.6 Figure: Self-Training 수렴

```
그래프 1: Round별 pseudo-label 채택률 변화
그래프 2: Round별 Real Test ADD 변화
→ 라운드가 진행될수록 채택률 증가 + 성능 향상 → 수렴
```
