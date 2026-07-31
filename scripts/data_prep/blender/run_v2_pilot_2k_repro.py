"""v2 pilot 2k — session 단위 재개 wrapper (병렬 렌더 없음).

2,000 usable frame 을 **한 Blender process 로 끝까지** 돌리지 않는다.
`run_v2_scene_logic.py --completion-mode usable --session-usable-cap K` 를 반복 호출해
K 장씩 전달하고, 매 session 마다 progress.json 을 확인한다.

이 wrapper 가 하는 일은 **호출과 감시**뿐이다 — sampling·quota·proposal 순서·gate 는
건드리지 않는다. production scene 은 registry 로만 해석한다(경로 하드코딩 금지).

    python scripts/data_prep/blender/run_v2_pilot_2k_repro.py \
        --out data/pallet/runs/diagnostics/v2_pilot_2k_seed7000_fullaudit \
        --seed 7000 --n 2000 --session-usable-cap 100 \
        --log-dir reports/v2_pilot_2k_seed7000/logs
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

import pallet_data_paths as PDP  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
RUNNER = os.path.join(_THIS, "run_v2_scene_logic.py")

BLENDER_CANDIDATES = (
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "/usr/bin/blender",
)


def find_blender(explicit=None):
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit(f"blender 실행 파일이 없습니다: {explicit}")
        return explicit
    env = os.environ.get("BLENDER_EXE")
    if env and os.path.isfile(env):
        return env
    for cand in BLENDER_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    found = shutil.which("blender")
    if found:
        return found
    raise SystemExit("blender 실행 파일을 찾지 못했습니다 (--blender 또는 BLENDER_EXE)")


def read_progress(out_abs):
    """progress.json -> dict (없으면 빈 dict). driver_summary 를 fallback 으로 쓴다."""
    for name in ("progress.json", "driver_summary.json"):
        path = os.path.join(out_abs, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            continue
    return {}


def build_command(blender, scene, args):
    """실제로 실행할 Blender 명령 (로그·command lock 에 그대로 기록된다)."""
    return [
        blender, "-b", scene,
        "--python", RUNNER, "--",
        "--out", args.out,
        "--seed", str(args.seed),
        "--n", str(args.n),
        "--completion-mode", "usable",
        "--render-profile", args.render_profile,
        "--samples", str(args.samples),
        "--noise-tier", args.noise_tier,
        "--mask-profile", args.mask_profile,
        "--magenta-max-fraction", str(args.magenta_max_fraction),
        "--session-usable-cap", str(args.session_usable_cap),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True,
                    help="pilot output root (repo-relative or absolute)")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--n", type=int, default=2000, help="target usable frames")
    ap.add_argument("--session-usable-cap", type=int, default=100)
    ap.add_argument("--render-profile", default="dataset-quality")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--noise-tier", default="auto")
    ap.add_argument("--mask-profile", default="full-audit")
    ap.add_argument("--magenta-max-fraction", type=float, default=0.0)
    ap.add_argument("--blender", default=None)
    ap.add_argument("--log-dir", default="reports/v2_pilot_2k_seed7000/logs")
    ap.add_argument("--max-sessions", type=int, default=200,
                    help="안전 상한 — 무한 재시도를 막는다")
    ap.add_argument("--dry-run", action="store_true",
                    help="명령만 출력하고 Blender 를 실행하지 않는다")
    args = ap.parse_args(argv)

    if args.session_usable_cap < 1:
        raise SystemExit("--session-usable-cap 은 1 이상이어야 합니다")

    scene = PDP.load().get("production_scene")      # ★ registry 로만 해석
    if not os.path.isfile(scene):
        raise SystemExit(f"production scene 이 없습니다: {scene}")
    blender = find_blender(args.blender)

    out_abs = args.out if os.path.isabs(args.out) else os.path.join(PROJECT_ROOT,
                                                                    args.out)
    log_dir = (args.log_dir if os.path.isabs(args.log_dir)
               else os.path.join(PROJECT_ROOT, args.log_dir))
    os.makedirs(log_dir, exist_ok=True)

    cmd = build_command(blender, scene, args)
    print("[WRAPPER] scene   :", scene, flush=True)
    print("[WRAPPER] blender :", blender, flush=True)
    print("[WRAPPER] command :", " ".join(f'"{c}"' if " " in c else c for c in cmd),
          flush=True)
    if args.dry_run:
        return 0

    sessions = []
    started = time.time()
    previous_delivered = int(read_progress(out_abs).get("usable_delivered") or 0)
    print(f"[WRAPPER] resume from usable_delivered={previous_delivered}", flush=True)

    for session in range(args.max_sessions):
        progress = read_progress(out_abs)
        delivered = int(progress.get("usable_delivered") or 0)
        if progress.get("complete") and delivered >= args.n:
            print(f"[WRAPPER] already complete ({delivered}/{args.n})", flush=True)
            break

        log_path = os.path.join(log_dir, "session_%03d.log" % session)
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            log.write("# session %d\n# %s\n\n" % (session, " ".join(cmd)))
            log.flush()
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  cwd=PROJECT_ROOT)
        elapsed = time.time() - t0

        after = read_progress(out_abs)
        now = int(after.get("usable_delivered") or 0)
        gained = now - delivered
        sessions.append({
            "session": session, "exit_code": proc.returncode,
            "delivered_before": delivered, "delivered_after": now,
            "gained": gained, "elapsed_s": round(elapsed, 2),
            "session_paused": bool(after.get("session_paused")),
            "complete": bool(after.get("complete")),
            "log": os.path.relpath(log_path, PROJECT_ROOT).replace(os.sep, "/"),
        })
        print(f"[WRAPPER] session {session:03d} exit={proc.returncode} "
              f"delivered {delivered}->{now} (+{gained}) in {elapsed:.1f}s "
              f"paused={bool(after.get('session_paused'))}", flush=True)

        if proc.returncode != 0:
            print(f"[WRAPPER] ★ 비정상 종료 (exit {proc.returncode}) — 중단. "
                  f"로그: {log_path}", flush=True)
            break
        if after.get("complete") and now >= args.n:
            print(f"[WRAPPER] COMPLETE {now}/{args.n}", flush=True)
            break
        if gained <= 0:
            print("[WRAPPER] ★ usable_delivered 가 증가하지 않았다 — 중단 "
                  "(무한 루프 방지)", flush=True)
            break

    summary = {
        "out": args.out, "seed": args.seed, "target": args.n,
        "session_usable_cap": args.session_usable_cap,
        "blender": blender, "scene": scene,
        "command": cmd,
        "sessions": sessions,
        "total_elapsed_s": round(time.time() - started, 2),
        "final": read_progress(out_abs),
    }
    summary_path = os.path.join(log_dir, "wrapper_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    final = summary["final"]
    print(f"[WRAPPER] sessions={len(sessions)} "
          f"delivered={final.get('usable_delivered')}/{args.n} "
          f"complete={final.get('complete')} -> {summary_path}", flush=True)
    ok = bool(final.get("complete")) and \
        int(final.get("usable_delivered") or 0) >= args.n
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
