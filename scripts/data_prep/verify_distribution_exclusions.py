"""릴리스 제외 목록(`data/pallet/_DISTRIBUTION_EXCLUDE.txt`) 검증기.

이 파일은 "공개 릴리스 패키지에 넣으면 안 되는 경로"의 정본이다. 경로가 stale 하면
게이트가 조용히 아무것도 걸러내지 못한다 — Stage 1 조사에서 실제로 5/5 가 stale 이었다.
그래서 검증을 코드로 고정한다.

검사
  - 빈 줄 / "#" 주석 처리
  - 각 entry 가 data/pallet 내부인지 (commonpath 기반, 문자열 prefix 아님)
  - ".." escape 가 없는지
  - entry 가 실제로 존재하는지 (stale 탐지)
  - 중복 entry
  - release/ 트리가 exclude 대상을 포함하지 않는지

exit code: 0 = 이상 없음 / 1 = missing·stale·duplicate·escape 등 문제 있음
"""

import argparse
import csv
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS, "blender"))
import pallet_data_paths as PDP  # noqa: E402

EXCLUDE_FILENAME = "_DISTRIBUTION_EXCLUDE.txt"


def is_within(candidate, root):
    try:
        c = os.path.normcase(os.path.realpath(candidate))
        r = os.path.normcase(os.path.realpath(root))
    except OSError:
        return False
    try:
        return os.path.commonpath([c, r]) == r
    except ValueError:
        return False


def parse(path):
    """[(lineno, raw, entry)] — 주석·빈 줄 제거."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            out.append((lineno, raw.rstrip("\n"), line))
    return out


def audit(data_root, exclude_path, release_root=None):
    rows = []
    seen = {}
    for lineno, raw, entry in parse(exclude_path):
        rel = entry.rstrip("/").replace("\\", "/")
        target = os.path.join(data_root, rel.replace("/", os.sep))
        problems = []
        if ".." in rel.split("/"):
            problems.append("PATH_ESCAPE")
        if os.path.isabs(rel):
            problems.append("ABSOLUTE_PATH")
        if not problems and not is_within(target, data_root):
            problems.append("OUTSIDE_DATA_ROOT")
        exists = os.path.exists(target)
        if not exists:
            problems.append("STALE_ENTRY")
        if rel in seen:
            problems.append("DUPLICATE_OF_LINE_%d" % seen[rel])
        else:
            seen[rel] = lineno
        rows.append(dict(line=lineno, entry=entry, resolved_relative=rel,
                         resolved_path=target, exists=exists,
                         is_dir=os.path.isdir(target),
                         problems=";".join(problems), ok=not problems))

    # release/ 트리가 exclude 대상을 품고 있지 않은지
    leaks = []
    if release_root and os.path.isdir(release_root):
        for r in rows:
            if not r["exists"]:
                continue
            leaked = os.path.join(release_root, r["resolved_relative"].replace("/", os.sep))
            if os.path.exists(leaked):
                leaks.append(leaked)
            base = os.path.basename(r["resolved_relative"])
            for dirpath, dirnames, _f in os.walk(release_root):
                if base in dirnames:
                    leaks.append(os.path.join(dirpath, base))
    return rows, leaks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # 기본 출력은 stage 중립 경로다. Stage 2-B 스냅샷 폴더를 기본값으로 두면 이 검증기를
    # 돌릴 때마다 **과거 스냅샷이 덮어써진다**(Stage 2-C2 에서 실제로 발생, git diff 로 발견).
    # 스냅샷은 그 단계의 증거이므로 재작성 대상이 아니다.
    ap.add_argument("--csv",
                    default="reports/data_pallet_cleanup/distribution_exclusion_audit.csv",
                    help="현재 상태 audit CSV 출력 경로. 단계별 보고서에 남기려면 "
                         "그 단계 폴더를 명시적으로 지정한다.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    paths = PDP.load()
    data_root = paths.get("pallet_data_root")
    exclude_path = os.path.join(data_root, EXCLUDE_FILENAME)
    if not os.path.isfile(exclude_path):
        print("제외 목록 파일이 없습니다: %s" % exclude_path, file=sys.stderr)
        return 1

    rows, leaks = audit(data_root, exclude_path, paths.get("release_root"))

    if args.csv:
        os.makedirs(os.path.dirname(args.csv), exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    bad = [r for r in rows if not r["ok"]]
    if not args.quiet:
        print("exclude file : %s" % exclude_path)
        print("entries      : %d" % len(rows))
        for r in rows:
            print("  %-4s %-46s %s" % ("OK" if r["ok"] else "BAD",
                                       r["resolved_relative"], r["problems"] or ""))
        print("problems     : %d" % len(bad))
        print("release leaks: %d" % len(leaks))
        for p in leaks[:10]:
            print("   LEAK", p)
    return 1 if (bad or leaks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
