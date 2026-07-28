"""data/pallet 레이아웃 이동을 트랜잭션으로 수행한다 (Stage 2-A).

    --plan      이동 계획 + 사전검사 + 이동 전 snapshot 을 manifest 에 기록. 파일은 건드리지 않는다.
    --apply     manifest 순서대로 실제 이동. 같은 볼륨 rename 만 사용한다.
    --verify    destination 의 파일 수 / bytes / 상대경로 집합 / SHA256 을 snapshot 과 대조.
    --rollback  destination -> source 로 역이동.

설계 원칙 (rollback_plan.md 와 같은 근거)
  - **삭제 명령을 쓰지 않는다.** copytree 후 원본 삭제 방식도 쓰지 않는다.
    같은 볼륨 rename(os.replace) 이라 원본과 사본이 동시에 존재하는 순간이 없다.
  - destination 이 이미 있으면 덮어쓰지 않고 그 자리에서 중단한다.
  - 실패하면 다음 항목으로 넘어가지 않는다. 어디서 깨졌는지 특정할 수 있어야 한다.
  - data/pallet 은 gitignored 라 git 으로 되돌릴 수 없다. manifest 가 유일한 rollback 근거다.

사용 예
    python scripts/data_prep/manage_pallet_data_layout.py --plan \\
        --moves reports/data_pallet_cleanup/proposed_moves.csv \\
        --manifest reports/data_pallet_cleanup/stage2a/move_transaction.jsonl
    python scripts/data_prep/manage_pallet_data_layout.py --apply  --manifest <path>
    python scripts/data_prep/manage_pallet_data_layout.py --verify --manifest <path>
    python scripts/data_prep/manage_pallet_data_layout.py --rollback --manifest <path>
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS, "blender"))
import pallet_data_paths as PDP  # noqa: E402

# ---------------------------------------------------------------------------
# Stage 2-A 이동 정책 (§5). 여기서 완화하면 무엇이 왜 옮겨졌는지 추적할 수 없게 된다.
# ---------------------------------------------------------------------------
ALLOWED_DEST_PREFIXES = ("runs/smoke/", "runs/diagnostics/", "runs/failed/")
MAX_SINGLE_BYTES = 5 * 1024 ** 3
MAX_TOTAL_BYTES = 5 * 1024 ** 3
FORBIDDEN_EXT = {
    ".zip", ".7z", ".tar", ".gz",
    ".blend", ".blend1", ".obj", ".glb", ".gltf", ".fbx", ".ply", ".mtl",
    ".usd", ".usda", ".usdc", ".usdz",
    ".hdr", ".exr",
    ".pt", ".pth", ".ckpt", ".onnx", ".engine", ".safetensors",
}
LICENSE_HINTS = ("license", "licence", "sources.txt", "attribution", "copyright", "notice")
RESERVED_WIN = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} \
    | {"LPT%d" % i for i in range(1, 10)}
MAX_PATH_LEN = 240

HASH_ALWAYS_EXT = {".json", ".jsonl", ".csv", ".md", ".txt", ".yaml", ".yml"}
HASH_SIZE_LIMIT = 8 * 1024 * 1024

# Stage 1 의 문자열 스캐너가 os.path.join(root, "data", "pallet", X) 형태를 구체 경로로
# 환원하지 못해 "문서 참조뿐"으로 보였지만, 실제로는 현재 코드의 기본 출력 경로인 항목.
# 옮기면 다음 실행 때 스크립트가 옛 경로를 다시 만들어 이동이 조용히 무효가 된다.
EXPLICIT_EXCLUSIONS = {
    "data/pallet/v2_dryrun_audit":
        "audit_v2_dryrun.py:39 DEFAULT_OUT 이 이 경로를 기본 출력으로 재생성함",
}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _posix(path):
    return path.replace("\\", "/")


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
def snapshot(root, hash_all_sizes=None):
    """폴더의 (상대경로 -> 크기) 와 정책에 따른 SHA256 을 모은다.

    hash_all_sizes: 이 크기 집합에 속하면 크기 무관 해시 (동일 크기 중복 후보).
    """
    hash_all_sizes = hash_all_sizes or set()
    files = {}
    hashes = {}
    hashed_large = []
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = _posix(os.path.relpath(abs_path, root))
            size = os.path.getsize(abs_path)
            files[rel] = size
            total += size
            ext = os.path.splitext(name)[1].lower()
            want = (size <= HASH_SIZE_LIMIT
                    or ext in HASH_ALWAYS_EXT
                    or "manifest" in name.lower()
                    or size in hash_all_sizes)
            if want:
                hashes[rel] = _sha256(abs_path)
                if size > HASH_SIZE_LIMIT:
                    hashed_large.append(rel)
    return {
        "file_count": len(files),
        "total_bytes": total,
        "files": files,
        "sha256": hashes,
        "hashed_over_limit": hashed_large,
        "unhashed": sorted(set(files) - set(hashes)),
    }


def duplicate_size_set(root):
    """root 안에서 같은 크기가 2개 이상인 크기값 집합 (중복 후보 -> 크기 무관 해시)."""
    seen = {}
    dup = set()
    for dirpath, _d, filenames in os.walk(root):
        for name in filenames:
            try:
                size = os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
            if size in seen:
                dup.add(size)
            else:
                seen[size] = 1
    return dup


# ---------------------------------------------------------------------------
# 사전검사
# ---------------------------------------------------------------------------
def precheck(src_abs, dst_abs, referenced_by, data_root):
    problems = []
    if not os.path.isdir(src_abs):
        problems.append("SOURCE_NOT_A_DIRECTORY")
        return problems, {}
    if os.path.islink(src_abs):
        problems.append("SOURCE_IS_SYMLINK")
    if os.path.exists(dst_abs):
        problems.append("DEST_COLLISION")
    if referenced_by:
        problems.append("CODE_OR_TEST_REFERENCE=%s" % referenced_by)

    stats = {"file_count": 0, "total_bytes": 0, "inaccessible": 0,
             "path_over_limit": 0, "reserved_name": 0, "symlink": 0,
             "forbidden_ext": [], "license_files": []}
    for dirpath, dirnames, filenames in os.walk(src_abs):
        for d in dirnames:
            if os.path.islink(os.path.join(dirpath, d)):
                stats["symlink"] += 1
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, src_abs)
            stats["file_count"] += 1
            if os.path.islink(abs_path):
                stats["symlink"] += 1
            try:
                stats["total_bytes"] += os.path.getsize(abs_path)
                with open(abs_path, "rb") as fh:
                    fh.read(1)
            except OSError:
                stats["inaccessible"] += 1
            if len(os.path.join(dst_abs, rel)) > MAX_PATH_LEN:
                stats["path_over_limit"] += 1
            if os.path.splitext(name)[0].upper() in RESERVED_WIN:
                stats["reserved_name"] += 1
            ext = os.path.splitext(name)[1].lower()
            if ext in FORBIDDEN_EXT:
                stats["forbidden_ext"].append(_posix(rel))
            if any(h in name.lower() for h in LICENSE_HINTS):
                stats["license_files"].append(_posix(rel))

    if stats["file_count"] == 0:
        problems.append("EMPTY_DIRECTORY")
    if stats["total_bytes"] > MAX_SINGLE_BYTES:
        problems.append("OVER_SINGLE_SIZE_LIMIT")
    for key, label in (("inaccessible", "INACCESSIBLE_FILE"),
                       ("path_over_limit", "PATH_LENGTH_OVER_240"),
                       ("reserved_name", "RESERVED_WINDOWS_NAME"),
                       ("symlink", "SYMLINK_OR_REPARSE")):
        if stats[key]:
            problems.append("%s=%d" % (label, stats[key]))
    if stats["forbidden_ext"]:
        problems.append("FORBIDDEN_EXTENSION=%d" % len(stats["forbidden_ext"]))
    if stats["license_files"]:
        problems.append("LICENSE_FILE=%d" % len(stats["license_files"]))
    if not _posix(os.path.abspath(src_abs)).startswith(_posix(data_root)):
        problems.append("SOURCE_OUTSIDE_DATA_ROOT")
    if not _posix(os.path.abspath(dst_abs)).startswith(_posix(data_root)):
        problems.append("DEST_OUTSIDE_DATA_ROOT")
    return problems, stats


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------
def cmd_plan(args, paths):
    data_root = paths.get("pallet_data_root")
    rows = list(csv.DictReader(open(args.moves, encoding="utf-8-sig")))
    allow_empty = args.allow_empty_dirs

    planned, skipped = [], []
    running_total = 0
    for row in rows:
        if row.get("status") != "SAFE_CANDIDATE":
            continue
        dest = row["destination"]
        if not dest.startswith(ALLOWED_DEST_PREFIXES):
            continue
        src_rel = row["source"]
        if not src_rel.startswith("data/pallet/"):
            skipped.append((src_rel, "SOURCE_NOT_UNDER_DATA_PALLET"))
            continue
        if src_rel in EXPLICIT_EXCLUSIONS:
            skipped.append((src_rel, "EXPLICIT_EXCLUSION: " + EXPLICIT_EXCLUSIONS[src_rel]))
            continue
        leaf = src_rel.rstrip("/").split("/")[-1]
        dst_rel = "data/pallet/" + dest.rstrip("/") + "/" + leaf
        src_abs = os.path.join(paths.project_root, src_rel.replace("/", os.sep))
        dst_abs = os.path.join(paths.project_root, dst_rel.replace("/", os.sep))

        # 문서(md)만의 참조는 §5 의 "code/config/test direct reference" 가 아니다.
        code_refs = [r for r in (row.get("required_code_changes") or "").split(";") if r]
        test_refs = [r for r in (row.get("required_test_changes") or "").split(";")
                     if r and r != "none"]
        blocking = [r for r in code_refs if r != "none"] + test_refs

        problems, stats = precheck(src_abs, dst_abs, blocking, data_root)
        if allow_empty and problems == ["EMPTY_DIRECTORY"]:
            problems = []
        if problems:
            skipped.append((src_rel, ";".join(problems)))
            continue
        if running_total + stats["total_bytes"] > MAX_TOTAL_BYTES:
            skipped.append((src_rel, "OVER_TOTAL_SIZE_LIMIT"))
            continue
        running_total += stats["total_bytes"]

        dup_sizes = duplicate_size_set(src_abs)
        snap = snapshot(src_abs, dup_sizes)
        planned.append({
            "move_id": "S2A%03d" % (len(planned) + 1),
            "source": src_rel,
            "destination": dst_rel,
            "relative_files": sorted(snap["files"]),
            "file_count": snap["file_count"],
            "total_bytes": snap["total_bytes"],
            "pre_hash_manifest": {
                "sha256": snap["sha256"],
                "sizes": snap["files"],
                "hashed_over_limit": snap["hashed_over_limit"],
                "unhashed": snap["unhashed"],
            },
            "status": "PLANNED",
            "started_at": None,
            "completed_at": None,
            "error": None,
            "rollback_status": None,
        })

    os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        for row in planned:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    skip_path = os.path.splitext(args.manifest)[0] + "_skipped.csv"
    with open(skip_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "reason"])
        w.writerows(skipped)

    hashed = sum(len(p["pre_hash_manifest"]["sha256"]) for p in planned)
    unhashed = sum(len(p["pre_hash_manifest"]["unhashed"]) for p in planned)
    print("planned  : %d moves" % len(planned))
    print("files    : %d" % sum(p["file_count"] for p in planned))
    print("bytes    : %d (%.3f GB)" % (running_total, running_total / 1e9))
    print("hashed   : %d / unhashed(대형) : %d" % (hashed, unhashed))
    print("skipped  : %d  -> %s" % (len(skipped), skip_path))
    print("manifest : %s" % args.manifest)
    return 0


# ---------------------------------------------------------------------------
# manifest io
# ---------------------------------------------------------------------------
def _read_manifest(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_manifest(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _same_volume(a, b):
    return os.path.splitdrive(os.path.abspath(a))[0].lower() == \
        os.path.splitdrive(os.path.abspath(b))[0].lower()


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------
def cmd_apply(args, paths):
    rows = _read_manifest(args.manifest)
    done = 0
    for row in rows:
        if row["status"] == "MOVED":
            continue
        src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
        dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
        row["started_at"] = _now()
        try:
            if not os.path.isdir(src):
                raise RuntimeError("source가 사라졌습니다: %s" % row["source"])
            if os.path.exists(dst):
                raise RuntimeError("destination이 이미 존재합니다(덮어쓰지 않음): %s"
                                   % row["destination"])
            if not _same_volume(src, os.path.dirname(dst)):
                raise RuntimeError("다른 볼륨입니다. rename 이동을 쓸 수 없습니다.")
            parent = os.path.dirname(dst)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            os.rename(src, dst)          # 같은 볼륨 rename. 복사/삭제 없음.
            row["status"] = "MOVED"
            row["completed_at"] = _now()
            done += 1
        except Exception as exc:         # noqa: BLE001 - 중단하고 원인을 남긴다
            row["status"] = "FAILED"
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
            _write_manifest(args.manifest, rows)
            print("APPLY 중단: %s -> %s" % (row["source"], row["error"]))
            print("이동 완료 %d건. rollback 은 --rollback 으로." % done)
            return 1
    _write_manifest(args.manifest, rows)
    print("applied  : %d moves" % done)
    return 0


# ---------------------------------------------------------------------------
# --verify
# ---------------------------------------------------------------------------
def cmd_verify(args, paths):
    rows = _read_manifest(args.manifest)
    failures = []
    checked_files = checked_bytes = checked_hashes = 0
    for row in rows:
        if row["status"] != "MOVED":
            continue
        dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
        src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
        pre = row["pre_hash_manifest"]
        post = snapshot(dst, set())
        # 사후 해시는 사전에 해시한 것과 같은 집합만 비교한다.
        if post["file_count"] != row["file_count"]:
            failures.append((row["move_id"], "FILE_COUNT %d != %d"
                             % (post["file_count"], row["file_count"])))
        if post["total_bytes"] != row["total_bytes"]:
            failures.append((row["move_id"], "TOTAL_BYTES %d != %d"
                             % (post["total_bytes"], row["total_bytes"])))
        if sorted(post["files"]) != sorted(row["relative_files"]):
            missing = sorted(set(row["relative_files"]) - set(post["files"]))
            extra = sorted(set(post["files"]) - set(row["relative_files"]))
            failures.append((row["move_id"], "RELPATH_SET missing=%s extra=%s"
                             % (missing[:3], extra[:3])))
        for rel, want in pre["sha256"].items():
            abs_path = os.path.join(dst, rel.replace("/", os.sep))
            if not os.path.isfile(abs_path):
                failures.append((row["move_id"], "MISSING %s" % rel))
                continue
            got = _sha256(abs_path)
            checked_hashes += 1
            if got != want:
                failures.append((row["move_id"], "SHA256 %s" % rel))
        if os.path.exists(src):
            failures.append((row["move_id"], "SOURCE_STILL_EXISTS %s" % row["source"]))
        checked_files += post["file_count"]
        checked_bytes += post["total_bytes"]

    print("verified moves : %d" % sum(1 for r in rows if r["status"] == "MOVED"))
    print("files          : %d" % checked_files)
    print("bytes          : %d (%.3f GB)" % (checked_bytes, checked_bytes / 1e9))
    print("sha256 checked : %d" % checked_hashes)
    print("failures       : %d" % len(failures))
    for move_id, msg in failures[:40]:
        print("   %s  %s" % (move_id, msg))
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# --rollback
# ---------------------------------------------------------------------------
def cmd_rollback(args, paths):
    rows = _read_manifest(args.manifest)
    restored = 0
    for row in reversed(rows):           # 역순 (중첩 이동 충돌 방지)
        if row["status"] != "MOVED":
            continue
        src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
        dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
        try:
            if os.path.exists(src):
                raise RuntimeError("원래 자리에 이미 무언가 있습니다(덮어쓰지 않음): %s"
                                   % row["source"])
            if not os.path.isdir(dst):
                raise RuntimeError("되돌릴 destination이 없습니다: %s" % row["destination"])
            os.rename(dst, src)
            row["status"] = "ROLLED_BACK"
            row["rollback_status"] = "OK@" + _now()
            restored += 1
        except Exception as exc:          # noqa: BLE001
            row["rollback_status"] = "FAILED: %s: %s" % (type(exc).__name__, exc)
            _write_manifest(args.manifest, rows)
            print("ROLLBACK 중단: %s -> %s" % (row["move_id"], row["rollback_status"]))
            return 1
    _write_manifest(args.manifest, rows)
    print("rolled back : %d moves" % restored)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    ap.add_argument("--manifest",
                    default="reports/data_pallet_cleanup/stage2a/move_transaction.jsonl")
    ap.add_argument("--moves", default="reports/data_pallet_cleanup/proposed_moves.csv",
                    help="--plan 입력 (Stage 1 proposed_moves.csv)")
    ap.add_argument("--allow-empty-dirs", action="store_true",
                    help="파일이 0개인 run 폴더도 이동 대상에 포함")
    args = ap.parse_args(argv)

    paths = PDP.load()
    if args.plan:
        return cmd_plan(args, paths)
    if args.apply:
        return cmd_apply(args, paths)
    if args.verify:
        return cmd_verify(args, paths)
    return cmd_rollback(args, paths)


if __name__ == "__main__":
    raise SystemExit(main())
