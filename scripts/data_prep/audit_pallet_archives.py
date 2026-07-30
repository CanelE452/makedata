"""data/pallet 잔여 대용량 자료 비파괴 감사 (Stage 2-D0).

**읽기만 한다.** 이동·삭제·rename·압축해제·ZIP 수정을 하지 않는다.

    --inventory          depth 1/2 구조 + 확장자/레이아웃 지문
    --package-signature  archive 를 central directory 만 읽어 서명 추출 (해제 없음)
    --tree-signature     추출 디렉토리의 (상대경로 -> size, CRC32) 서명
    --weight-inventory   저장소 전체 weight/checkpoint 색인
    --classify           위 산출물을 근거 우선순위로 분류
    --plan               Stage 2-D1 이동 계획만 작성 (apply 하지 않음)

hash-mode
    metadata   경로·크기·mtime 만. 내용 읽기 0.
    selective  8MB 이하 + 텍스트/manifest/license + 동일 크기 후보만 해시 (기본)
    full       승인된 후보만 전량 SHA256. Stage 2-D0 기본 사용 금지.

read budget
    전체 hash read 를 --max-full-hash-bytes 로 제한한다. 넘으면 실행하지 않고
    "필요한 후보 + 예상 read bytes" 를 보고한다. 실제 읽은 bytes 를 항상 기록한다.

설계 원칙
  - 파일 수와 총 bytes 가 같다고 exact duplicate 라고 부르지 않는다.
    증거 레벨(LEVEL 0~5)을 분리해 표기한다.
  - 이름·폴더명은 **최하위 근거**다. runtime > config > test > current doc >
    run manifest > history > 이름 순으로 판단한다.
  - `.blend1` 을 이름만 보고 불필요로 판정하지 않는다.
"""

import argparse
import csv
import fnmatch
import json
import hashlib
import os
import sys
import tarfile
import time
import zipfile
import zlib

_THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS, "blender"))
import pallet_data_paths as PDP  # noqa: E402


HASH_METADATA = "metadata"
HASH_SELECTIVE = "selective"
HASH_FULL = "full"
HASH_MODES = (HASH_METADATA, HASH_SELECTIVE, HASH_FULL)

SELECTIVE_SIZE_LIMIT = 8 * 1024 * 1024
SELECTIVE_EXT = {".json", ".jsonl", ".csv", ".md", ".txt", ".yaml", ".yml", ".cfg", ".ini"}
SELECTIVE_NAME_HINTS = ("manifest", "license", "licence", "sources", "readme", "attribution",
                        "summary", "progress", "records", "driver")

ARCHIVE_EXT = {".zip", ".7z", ".tar", ".gz", ".tgz", ".rar", ".bz2", ".xz"}
WEIGHT_EXT = {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".safetensors",
              ".weights", ".pb", ".tflite", ".trt"}
BLEND_EXT = {".blend", ".blend1", ".blend2"}

# 데이터셋 레이아웃 지문 (폴더명이 아니라 내부 구성으로 판단한다)
DATASET_DIR_HINTS = ("rgb", "labels", "mask", "mask_amodal", "mask_visible", "overlay",
                     "eda_phase6", "logs")
DATASET_FILE_HINTS = ("records.jsonl", "records.json", "driver_summary.json",
                      "progress.json", "usable_manifest.csv", "usable_manifest.json")

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", "node_modules",
                  ".venv", "venv", "env", ".mypy_cache", ".idea", ".vscode"}


class ReadBudget(object):
    """실제로 읽은 bytes 를 세고 상한을 강제한다."""

    def __init__(self, limit_bytes):
        self.limit = limit_bytes
        self.read = 0
        self.refused = []

    def can(self, nbytes):
        return self.read + nbytes <= self.limit

    def spend(self, nbytes):
        self.read += nbytes

    def refuse(self, path, nbytes, reason="budget"):
        self.refused.append({"path": path, "bytes": nbytes, "reason": reason})


def sha256_file(path, budget):
    size = os.path.getsize(path)
    if not budget.can(size):
        budget.refuse(path, size)
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    budget.spend(size)
    return h.hexdigest()


def crc32_file(path, budget):
    size = os.path.getsize(path)
    if not budget.can(size):
        budget.refuse(path, size)
        return None
    crc = 0
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            crc = zlib.crc32(b, crc)
    budget.spend(size)
    return crc & 0xFFFFFFFF


def wants_selective(path, size, dup_sizes):
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    if size <= SELECTIVE_SIZE_LIMIT:
        return True
    if ext in SELECTIVE_EXT:
        return True
    if any(h in name for h in SELECTIVE_NAME_HINTS):
        return True
    return size in dup_sizes


def posix(p):
    return p.replace("\\", "/")


def walk_files(root, exclude_globs=()):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        rel_dir = posix(os.path.relpath(dirpath, root))
        if any(fnmatch.fnmatch(rel_dir, g) for g in exclude_globs):
            dirnames[:] = []
            continue
        for name in filenames:
            yield dirpath, name


# --------------------------------------------------------------------- 인벤토리
def dir_signature(abs_dir, budget, hash_mode):
    """디렉토리 하나의 지문. 내용 해시는 hash_mode 에 따른다."""
    sig = {
        "file_count": 0, "total_bytes": 0,
        "mtime_min": None, "mtime_max": None,
        "ext_counts": {}, "top_dirs": set(),
        "has_rgb": False, "has_labels": False, "has_masks": False,
        "has_records": False, "has_overlay": False,
        "has_blend": False, "has_archive": False, "has_weight": False,
        "has_license": False,
        "sizes": {},
    }
    for dirpath, name in walk_files(abs_dir):
        ap = os.path.join(dirpath, name)
        try:
            st = os.stat(ap)
        except OSError:
            continue
        rel = posix(os.path.relpath(ap, abs_dir))
        sig["file_count"] += 1
        sig["total_bytes"] += st.st_size
        sig["sizes"][rel] = st.st_size
        mt = st.st_mtime
        sig["mtime_min"] = mt if sig["mtime_min"] is None else min(sig["mtime_min"], mt)
        sig["mtime_max"] = mt if sig["mtime_max"] is None else max(sig["mtime_max"], mt)
        ext = os.path.splitext(name)[1].lower()
        sig["ext_counts"][ext] = sig["ext_counts"].get(ext, 0) + 1
        head = rel.split("/")[0] if "/" in rel else ""
        if head:
            sig["top_dirs"].add(head)
        low = name.lower()
        if ext in BLEND_EXT:
            sig["has_blend"] = True
        if ext in ARCHIVE_EXT:
            sig["has_archive"] = True
        if ext in WEIGHT_EXT:
            sig["has_weight"] = True
        if any(h in low for h in ("license", "licence", "sources.txt", "attribution")):
            sig["has_license"] = True
        if low in DATASET_FILE_HINTS:
            sig["has_records"] = True
    tops = {d.lower() for d in sig["top_dirs"]}
    sig["has_rgb"] = "rgb" in tops
    sig["has_labels"] = "labels" in tops
    sig["has_masks"] = bool(tops & {"mask", "mask_amodal", "mask_visible"})
    sig["has_overlay"] = bool(tops & {"overlay", "eda_phase6"})
    sig["top_dirs"] = sorted(sig["top_dirs"])
    return sig


def fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


# ------------------------------------------------------------- package signature
def zip_signature(path):
    """ZIP central directory 만 읽는다. 압축 해제하지 않는다."""
    out = {"archive_type": "zip", "open_status": "yes", "open_error": "",
            "entry_count": 0, "compressed_bytes": 0, "uncompressed_bytes": 0,
            "duplicate_entry_paths": 0, "encrypted_entries": 0,
            "crc_available": True, "compress_types": {}, "entries": [],
            "license_entries": [], "manifest_entries": []}
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            seen = set()
            for i in infos:
                if i.is_dir():
                    continue
                out["entry_count"] += 1
                out["compressed_bytes"] += i.compress_size
                out["uncompressed_bytes"] += i.file_size
                p = posix(i.filename)
                if p in seen:
                    out["duplicate_entry_paths"] += 1
                seen.add(p)
                if i.flag_bits & 0x1:
                    out["encrypted_entries"] += 1
                ct = str(i.compress_type)
                out["compress_types"][ct] = out["compress_types"].get(ct, 0) + 1
                out["entries"].append({"path": p, "size": i.file_size,
                                       "crc": i.CRC, "compress_size": i.compress_size})
                low = p.lower()
                if any(h in low for h in ("license", "licence", "sources.txt", "attribution")):
                    out["license_entries"].append(p)
                if "manifest" in low or low.endswith("records.jsonl"):
                    out["manifest_entries"].append(p)
    except Exception as exc:                     # noqa: BLE001 - 손상도 사실로 기록
        out["open_status"] = "NO"
        out["open_error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def tar_signature(path):
    out = {"archive_type": "tar", "open_status": "yes", "open_error": "",
            "entry_count": 0, "compressed_bytes": os.path.getsize(path),
            "uncompressed_bytes": 0, "duplicate_entry_paths": 0,
            "encrypted_entries": 0, "crc_available": False, "compress_types": {},
            "entries": [], "license_entries": [], "manifest_entries": []}
    try:
        with tarfile.open(path) as t:
            seen = set()
            for m in t:
                if not m.isfile():
                    continue
                out["entry_count"] += 1
                out["uncompressed_bytes"] += m.size
                p = posix(m.name)
                if p in seen:
                    out["duplicate_entry_paths"] += 1
                seen.add(p)
                out["entries"].append({"path": p, "size": m.size, "crc": None,
                                       "compress_size": None})
    except Exception as exc:                     # noqa: BLE001
        out["open_status"] = "NO"
        out["open_error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def archive_signature(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        return zip_signature(path)
    if ext in (".tar", ".tgz", ".gz", ".bz2", ".xz"):
        return tar_signature(path)
    return {"archive_type": ext.lstrip("."), "open_status": "UNSUPPORTED", "open_error":
            "이 도구는 zip/tar 계열만 서명을 읽는다 (해제 없이 읽을 수 없는 형식)",
            "entry_count": 0, "compressed_bytes": os.path.getsize(path),
            "uncompressed_bytes": 0, "duplicate_entry_paths": 0, "encrypted_entries": 0,
            "crc_available": False, "compress_types": {}, "entries": [],
            "license_entries": [], "manifest_entries": []}


# ------------------------------------------------------------ package <-> tree
def normalize_entry_paths(entries):
    """ZIP 안의 공통 접두 디렉토리를 벗겨 추출 트리와 비교 가능하게 만든다."""
    paths = [e["path"] for e in entries]
    if not paths:
        return {}, ""
    parts = [p.split("/") for p in paths]
    prefix = []
    while True:
        heads = {p[0] for p in parts if len(p) > 1}
        if len(heads) != 1:
            break
        head = heads.pop()
        if any(len(p) == 1 or p[0] != head for p in parts):
            break
        prefix.append(head)
        parts = [p[1:] for p in parts]
    stripped = {"/".join(p): e for p, e in zip(parts, entries)}
    return stripped, "/".join(prefix)


def match_levels(pkg_entries, tree_sizes, tree_crcs=None):
    """증거 레벨 판정. 파일 수+bytes 만으로 exact duplicate 라고 부르지 않는다."""
    stripped, prefix = normalize_entry_paths(pkg_entries)
    pkg_sizes = {p: e["size"] for p, e in stripped.items()}
    pkg_crcs = {p: e["crc"] for p, e in stripped.items()}
    level = 0
    detail = {"stripped_prefix": prefix,
              "pkg_entries": len(pkg_sizes), "tree_files": len(tree_sizes),
              "pkg_bytes": sum(pkg_sizes.values()), "tree_bytes": sum(tree_sizes.values())}
    if detail["pkg_entries"] == detail["tree_files"]:
        level = 1
    if level >= 1 and detail["pkg_bytes"] == detail["tree_bytes"]:
        level = 2
    path_match = set(pkg_sizes) == set(tree_sizes)
    size_match = path_match and all(pkg_sizes[k] == tree_sizes[k] for k in pkg_sizes)
    if size_match:
        level = 3
    crc_match = None
    if level >= 3 and tree_crcs:
        crc_match = all(pkg_crcs.get(k) is not None and tree_crcs.get(k) == pkg_crcs[k]
                        for k in pkg_sizes)
        if crc_match:
            level = 4
    detail.update({"path_match": path_match, "size_match": size_match,
                   "crc_match": crc_match})
    return level, detail


LEVEL_NAME = {0: "POSSIBLE_MATCH", 1: "POSSIBLE_MATCH", 2: "POSSIBLE_MATCH",
              3: "STRUCTURAL_MATCH", 4: "CONTENT_VERIFIED_BY_CRC",
              5: "CONTENT_VERIFIED_BY_SHA256"}


# ---------------------------------------------------------------------- weights
def weight_inventory(repo_root, budget, hash_mode):
    rows = []
    for dirpath, name in walk_files(repo_root):
        ext = os.path.splitext(name)[1].lower()
        if ext not in WEIGHT_EXT:
            continue
        ap = os.path.join(dirpath, name)
        try:
            st = os.stat(ap)
        except OSError:
            continue
        rel = posix(os.path.relpath(ap, repo_root))
        digest = None
        if hash_mode == HASH_FULL or st.st_size <= SELECTIVE_SIZE_LIMIT:
            digest = sha256_file(ap, budget)
        rows.append({"path": rel, "bytes": st.st_size, "sha256": digest or "",
                     "mtime": fmt_time(st.st_mtime), "extension": ext})
    rows.sort(key=lambda r: -r["bytes"])
    return rows


# ------------------------------------------------------------------------- CLI
def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--package-signature", action="store_true")
    ap.add_argument("--weight-inventory", action="store_true")
    ap.add_argument("--root", default=None, help="기본: registry pallet_data_root")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--hash-mode", choices=list(HASH_MODES), default=HASH_SELECTIVE)
    ap.add_argument("--max-full-hash-bytes", type=int, default=20 * 1024 ** 3,
                    help="hash read 상한 (기본 20GB). 넘으면 읽지 않고 후보로만 보고")
    ap.add_argument("--include", nargs="*", default=None)
    ap.add_argument("--exclude", nargs="*", default=None,
                    help="root 기준 상대 glob (예: assets/* reference/*)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    paths = PDP.load()
    root = os.path.abspath(args.root or paths.get("pallet_data_root"))
    repo_root = os.path.abspath(args.repo_root or paths.project_root)
    out_dir = os.path.abspath(args.output_dir)
    budget = ReadBudget(args.max_full_hash_bytes)
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    summary = {"root": root, "repo_root": repo_root, "hash_mode": args.hash_mode,
               "budget_limit_bytes": budget.limit, "modes": []}

    if args.inventory:
        summary["modes"].append("inventory")
        exclude = args.exclude or []
        rows = []
        for name in sorted(os.listdir(root)):
            ap = os.path.join(root, name)
            if os.path.isdir(ap):
                if any(fnmatch.fnmatch(name, g) for g in exclude):
                    rows.append({"relative_path": name, "type": "dir",
                                 "note": "EXCLUDED_FROM_CONTENT_AUDIT"})
                    continue
                sig = dir_signature(ap, budget, args.hash_mode)
                rows.append({
                    "relative_path": name, "type": "dir",
                    "file_count_recursive": sig["file_count"],
                    "total_bytes_recursive": sig["total_bytes"],
                    "modified_min": fmt_time(sig["mtime_min"]),
                    "modified_max": fmt_time(sig["mtime_max"]),
                    "extension_counts": json.dumps(
                        dict(sorted(sig["ext_counts"].items(), key=lambda kv: -kv[1])[:8]),
                        ensure_ascii=False),
                    "top_dirs": ";".join(sig["top_dirs"][:12]),
                    "contains_rgb": sig["has_rgb"], "contains_labels": sig["has_labels"],
                    "contains_masks": sig["has_masks"], "contains_records": sig["has_records"],
                    "contains_overlay": sig["has_overlay"],
                    "contains_dataset_layout": sig["has_rgb"] and sig["has_labels"],
                    "contains_blend": sig["has_blend"],
                    "contains_archive": sig["has_archive"],
                    "contains_weight": sig["has_weight"],
                    "contains_license": sig["has_license"], "note": "",
                })
            else:
                st = os.stat(ap)
                ext = os.path.splitext(name)[1].lower()
                rows.append({
                    "relative_path": name, "type": "file",
                    "file_count_recursive": 1, "total_bytes_recursive": st.st_size,
                    "modified_min": fmt_time(st.st_mtime),
                    "modified_max": fmt_time(st.st_mtime),
                    "extension_counts": json.dumps({ext: 1}),
                    "contains_archive": ext in ARCHIVE_EXT,
                    "contains_weight": ext in WEIGHT_EXT,
                    "contains_blend": ext in BLEND_EXT, "note": "",
                })
        fields = ["relative_path", "type", "file_count_recursive", "total_bytes_recursive",
                  "modified_min", "modified_max", "extension_counts", "top_dirs",
                  "contains_dataset_layout", "contains_rgb", "contains_labels",
                  "contains_masks", "contains_records", "contains_overlay",
                  "contains_blend", "contains_archive", "contains_weight",
                  "contains_license", "note"]
        write_csv(os.path.join(out_dir, "_raw_top_level_inventory.csv"), rows, fields)
        print("[inventory] entries=%d -> _raw_top_level_inventory.csv" % len(rows))

    if args.package_signature:
        summary["modes"].append("package-signature")
        pkgs, entries_summary = [], []
        for dirpath, name in walk_files(root):
            if os.path.splitext(name)[1].lower() not in ARCHIVE_EXT:
                continue
            ap = os.path.join(dirpath, name)
            rel = posix(os.path.relpath(ap, root))
            sig = archive_signature(ap)
            pkgs.append({
                "path": rel, "size_bytes": os.path.getsize(ap),
                "archive_type": sig["archive_type"],
                "open_status": sig["open_status"], "open_error": sig["open_error"],
                "entry_count": sig["entry_count"],
                "compressed_bytes": sig["compressed_bytes"],
                "uncompressed_bytes": sig["uncompressed_bytes"],
                "duplicate_entry_paths": sig["duplicate_entry_paths"],
                "encrypted_entries": sig["encrypted_entries"],
                "crc_available": sig["crc_available"],
                "compress_types": json.dumps(sig["compress_types"]),
                "license_entries": ";".join(sig["license_entries"][:5]),
                "manifest_entries": ";".join(sig["manifest_entries"][:5]),
            })
            stripped, prefix = normalize_entry_paths(sig["entries"])
            tops = {}
            for p in stripped:
                tops[p.split("/")[0]] = tops.get(p.split("/")[0], 0) + 1
            entries_summary.append({
                "package": rel, "stripped_prefix": prefix,
                "entry_count": len(stripped),
                "top_level_entries": json.dumps(
                    dict(sorted(tops.items(), key=lambda kv: -kv[1])[:10]), ensure_ascii=False),
            })
            write_json(os.path.join(out_dir, "_raw_pkg_%s.json"
                                   % rel.replace("/", "__").replace(".", "_")),
                       {"package": rel, "signature": {k: v for k, v in sig.items()
                                                      if k != "entries"},
                        "entries": sig["entries"]})
        write_csv(os.path.join(out_dir, "packages.csv"), pkgs,
                  ["path", "size_bytes", "archive_type", "open_status", "open_error",
                   "entry_count", "compressed_bytes", "uncompressed_bytes",
                   "duplicate_entry_paths", "encrypted_entries", "crc_available",
                   "compress_types", "license_entries", "manifest_entries"])
        write_csv(os.path.join(out_dir, "package_entries_summary.csv"), entries_summary,
                  ["package", "stripped_prefix", "entry_count", "top_level_entries"])
        bad = [p for p in pkgs if p["open_status"] != "yes"]
        write_csv(os.path.join(out_dir, "corrupt_packages.csv"), bad,
                  ["path", "size_bytes", "archive_type", "open_status", "open_error",
                   "entry_count"])
        print("[package] archives=%d open_fail=%d -> packages.csv" % (len(pkgs), len(bad)))

    if args.weight_inventory:
        summary["modes"].append("weight-inventory")
        rows = weight_inventory(repo_root, budget, args.hash_mode)
        write_csv(os.path.join(out_dir, "_raw_weights.csv"), rows,
                  ["path", "bytes", "sha256", "mtime", "extension"])
        print("[weights] found=%d -> _raw_weights.csv" % len(rows))

    summary["read_bytes"] = budget.read
    summary["refused"] = budget.refused
    summary["elapsed_s"] = round(time.time() - started, 2)
    write_json(os.path.join(out_dir, "audit_run_summary.json"), summary)
    print("[budget] read=%d bytes (%.3f GB) / limit %.1f GB / refused=%d"
          % (budget.read, budget.read / 1024 ** 3, budget.limit / 1024 ** 3,
             len(budget.refused)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
