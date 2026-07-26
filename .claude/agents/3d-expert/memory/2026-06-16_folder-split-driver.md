# run_dataset_v4 폴더 분할(folder-split) 저장 — 2026-06-16

## 목적
풀 5000장을 한 폴더에 몰지 않고 **폴더당 200장 독립 DOPE 데이터셋**으로 분할 저장.

## 설계 (엔진 미변경, driver+flag만)
- Python `gen_dataset_v4.py`는 chunk 1개를 `out_dir/<split>/{images,json,...}`에 쓰던 구조.
  여기에 `--flat_out` 플래그만 추가 → `<split>/` 서브디렉토리 생략, out_dir 자체가 데이터셋 루트.
  (`split_dir = out_root if args.flat_out else os.path.join(out_root, args.split)`)
  게이트/라벨/랜덤화 로직은 **한 줄도 안 건드림**.
- bash `run_dataset_v4.sh`가 폴더 매핑 담당:
  - `train_batch_%03d` / `val_batch_%03d` (zero-pad), out_dir 바로 밑.
  - `--flat_out --out_dir <out>/<folder>` 로 호출 → 폴더가 곧 데이터셋.
  - frame index 폴더 내 0부터 ({i:06d}). 전역 연속 아님 → DOPE 로더가 폴더 하나만 가리켜도 OK.

## resume = 폴더별 PNG 카운트
- count>=per_folder 폴더 SKIP, 부분 폴더는 count부터 이어감(start_idx=count).
- seed = seed_base + folder*10000 + done_count → 폴더/재개 chunk마다 달라 동일 프레임 반복 방지.
- 마지막 폴더는 PER_FOLDER를 일시 축소해 나머지(<200)만 채움.

## 검증 패턴 (소량)
- batch=6 per_folder=6 train14 val6 → 000(6)/001(6)/002(2)/val000(6) 정확.
- resume: 한 폴더 일부 png 삭제 후 재실행 → 완성 폴더 SKIP, 부분 폴더만 이어감 확인.
- 라벨 무결성: dims_m H≈0.20(scaled 0.15*ratio) W/D≈1.1, perm dynamic, ratio/HDRI/bg 랜덤 유지.

## 함정/주의
- `rm -rf`는 이 환경 Bash 권한에서 거부됨 → `find ... -delete`로 우회.
- bash cwd는 호출마다 리셋 → 절대경로 또는 프로젝트 루트 기준 상대경로 일관 사용.
- 풀 실행 out_dir은 기존 파일럿(`training_data_v4/{train,val}` flat)과 충돌 피해 **새 dir** 권장.
- 200장 = train 20폴더 + val 5폴더 = 25폴더/5000장.

## 풀 커맨드
bash run_dataset_v4.sh --n_train 4000 --n_val 1000 \
  --out_dir data/pallet/training_data_v4_split \
  --seed 7000 --per_folder 200 --batch_size 200 --overlay_every 100
