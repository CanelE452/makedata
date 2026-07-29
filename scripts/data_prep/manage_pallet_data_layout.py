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

HASH_MODE_SELECTIVE = "selective"
HASH_MODE_ALL = "all"
HASH_MODES = (HASH_MODE_SELECTIVE, HASH_MODE_ALL)
# Stage 2-A 이전 manifest 에는 hash_mode 필드가 없다. 자동 rewrite 하지 않고 이 이름으로 읽는다.
HASH_MODE_LEGACY = "selective-legacy"

# Stage 1 의 문자열 스캐너가 os.path.join(root, "data", "pallet", X) 형태를 구체 경로로
# 환원하지 못해 "문서 참조뿐"으로 보였지만, 실제로는 현재 코드의 기본 출력 경로인 항목.
# 옮기면 다음 실행 때 스크립트가 옛 경로를 다시 만들어 이동이 조용히 무효가 된다.
EXPLICIT_EXCLUSIONS = {
    "data/pallet/v2_dryrun_audit":
        "audit_v2_dryrun.py:39 DEFAULT_OUT 이 이 경로를 기본 출력으로 재생성함",
}

# ---------------------------------------------------------------------------
# 이동 정책 (Stage 2-B 에서 도입). 정책은 "무엇을 어디로 옮겨도 되는가"의 전부를 담는다.
#
#   stage2a-runs         (기본, 하위호환) 코드 참조 없는 저위험 run 만 runs/ 아래로.
#   stage2b-active-assets 현역 자산·golden reference 를 assets//reference/ 아래로.
#                         source -> destination 이 exact allowlist 이고 hash-mode=all 강제.
# ---------------------------------------------------------------------------
POLICY_STAGE2A = "stage2a-runs"
POLICY_STAGE2B = "stage2b-active-assets"
POLICY_STAGE2C2 = "stage2c2-final-layout"

# entry_kind: Stage 2-A/2-B 는 directory 만 옮겼다. Stage 2-C2 는 background 안의
# 원본 다운로드 ZIP 을 **파일 단위**로 먼저 떼어내야 하므로 file entry 가 필요하다.
ENTRY_DIRECTORY = "directory"
ENTRY_FILE = "file"
ENTRY_KINDS = (ENTRY_DIRECTORY, ENTRY_FILE)

# Stage 2-C2 archive package 규칙: background 안의 archive 파일만, 상대경로를 보존해
# archive/packages/background_sources 아래로. basename 평탄화 금지.
C2A_ARCHIVE_SOURCE_ROOT = "data/pallet/background"
C2A_ARCHIVE_DEST_ROOT = "data/pallet/archive/packages/background_sources"
ARCHIVE_EXT = {".zip", ".7z", ".tar", ".gz", ".tgz", ".rar"}

# Stage 2-B exact allowlist. 여기 없는 source/destination 은 전부 거부한다.
STAGE2B_ALLOWLIST = (
    # (source, destination, cohort)
    ("data/pallet/archive/textures_wood",
     "data/pallet/assets/materials/pallet/textures_wood", "B1_REFERENCE_MATERIALS"),
    ("data/pallet/archive/textures_floor",
     "data/pallet/assets/materials/floor/textures_floor", "B1_REFERENCE_MATERIALS"),
    ("data/pallet/archive/trunc_addon_v1_pilot",
     "data/pallet/reference/golden_overlay/trunc_addon_v1_pilot", "B1_REFERENCE_MATERIALS"),
    ("data/pallet/real_data",
     "data/pallet/reference/real_images/real_data", "B1_REFERENCE_MATERIALS"),
    ("data/pallet/hdri",
     "data/pallet/assets/lighting/hdri/library", "B2_LIGHTING_MODELS"),
    ("data/pallet/models_usd",
     "data/pallet/assets/pallets/models/models_usd", "B2_LIGHTING_MODELS"),
    ("data/pallet/pallets_v2_add",
     "data/pallet/assets/pallets/source/pallets_v2_add", "B2_LIGHTING_MODELS"),
    ("data/pallet/background",
     "data/pallet/assets/scenes/backgrounds/background", "B3_SCENE_ASSETS"),
    ("data/pallet/distractors",
     "data/pallet/assets/distractors/library", "B3_SCENE_ASSETS"),
    ("data/pallet/blender_scene",
     "data/pallet/assets/scenes/production/blender_scene", "B4_PRODUCTION_SCENE"),
)

# 어떤 정책에서도 옮기지 않는 확장자 (패키지·학습 가중치).
ALWAYS_FORBIDDEN_EXT = {
    ".zip", ".7z", ".tar", ".gz", ".rar",
    ".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt", ".safetensors",
}
# Stage 2-A 에서만 금지하던 3D/HDR. Stage 2-B 는 allowlist 안에서만 허용한다.
ASSET_EXT = {
    ".blend", ".blend1", ".obj", ".glb", ".gltf", ".fbx", ".ply", ".mtl",
    ".usd", ".usda", ".usdc", ".usdz", ".hdr", ".exr",
}

# Stage 2-C2 exact allowlist. (source, destination, cohort, entry_kind, transaction_group)
# C2A 는 파일 목록이 실측으로 정해지므로 여기엔 규칙만 두고 plan 시점에 확장한다.
STAGE2C2_ALLOWLIST = (
    ("data/pallet/background",
     "data/pallet/assets/scenes/backgrounds/background",
     "C2B_BACKGROUND_ASSET", ENTRY_DIRECTORY, "C2B_BACKGROUND_ASSET"),
    ("data/pallet/distractors",
     "data/pallet/assets/distractors/library",
     "C2C_DISTRACTOR_SCENE", ENTRY_DIRECTORY, "C2C_DISTRACTOR_SCENE"),
    ("data/pallet/blender_scene",
     "data/pallet/assets/scenes/production/blender_scene",
     "C2C_DISTRACTOR_SCENE", ENTRY_DIRECTORY, "C2C_DISTRACTOR_SCENE"),
)

# C2C 는 두 directory 가 함께 가야 의미가 있다 (blend 의 상대참조가 distractors 를 가리킨다).
# 한쪽만 계획되거나 한쪽만 적용되면 그룹 전체를 되돌린다.
REQUIRED_GROUP_SOURCES = {
    "C2C_DISTRACTOR_SCENE": ("data/pallet/distractors", "data/pallet/blender_scene"),
}

POLICIES = {
    POLICY_STAGE2A: {
        "allowed_dest_prefixes": ALLOWED_DEST_PREFIXES,
        "allowlist": None,                      # 목적지 prefix 방식
        "forbidden_ext": ALWAYS_FORBIDDEN_EXT | ASSET_EXT,
        "license_is_blocker": True,             # run 에 라이선스 파일이 있으면 이상 신호
        "max_single_bytes": 5 * 1024 ** 3,
        "max_total_bytes": 5 * 1024 ** 3,
        "require_hash_mode": None,              # selective/all 모두 허용
        "move_id_prefix": "S2A",
    },
    POLICY_STAGE2B: {
        "allowed_dest_prefixes": ("assets/", "reference/"),
        "allowlist": STAGE2B_ALLOWLIST,         # exact source->dest
        "forbidden_ext": ALWAYS_FORBIDDEN_EXT,  # 3D/HDR 은 허용 (자산이니까)
        "license_is_blocker": False,            # 라이선스는 자산과 함께 보존해야 한다
        "max_single_bytes": 10 * 1024 ** 3,
        "max_total_bytes": 10 * 1024 ** 3,
        "require_hash_mode": HASH_MODE_ALL,     # 전량 SHA256 강제
        "move_id_prefix": "S2B",
    },
    POLICY_STAGE2C2: {
        "allowed_dest_prefixes": ("assets/", "archive/packages/background_sources/"),
        "allowlist": STAGE2C2_ALLOWLIST,
        # ZIP 은 C2A(file entry)에서만 허용한다. directory cohort 에 ZIP 이 남아 있으면 거부.
        "forbidden_ext": {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt", ".safetensors"},
        "archive_allowed_cohorts": ("C2A_BACKGROUND_PACKAGES",),
        "license_is_blocker": False,
        "max_single_bytes": 10 * 1024 ** 3,
        "max_total_bytes": 10 * 1024 ** 3,
        "require_hash_mode": HASH_MODE_ALL,
        "move_id_prefix": "S2C2",
    },
}


def get_policy(name):
    if name not in POLICIES:
        raise ValueError("unknown policy %r (expected %s)" % (name, list(POLICIES)))
    return POLICIES[name]


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


def is_within(candidate, root):
    """``candidate`` 가 ``root`` 안(또는 root 자신)인가.

    문자열 startswith 를 쓰면 ``data/pallet_backup`` 이 ``data/pallet`` 안으로 잘못
    판정된다. realpath 로 ``..`` 와 symlink 를 접고, normcase 로 Windows 대소문자를
    정규화한 뒤 commonpath 로 비교한다. 다른 드라이브면 commonpath 가 ValueError 라
    False 다.
    """
    try:
        candidate_real = os.path.normcase(os.path.realpath(candidate))
        root_real = os.path.normcase(os.path.realpath(root))
    except OSError:
        return False
    try:
        return os.path.commonpath([candidate_real, root_real]) == root_real
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
def snapshot(root, hash_all_sizes=None, hash_mode=HASH_MODE_SELECTIVE):
    """폴더의 (상대경로 -> 크기) 와 정책에 따른 SHA256 을 모은다.

    hash_all_sizes: 이 크기 집합에 속하면 크기 무관 해시 (동일 크기 중복 후보).
    hash_mode:
        "selective" - 8MB 이하 / 텍스트·manifest 확장자 / 동일 크기 중복 후보만 해시.
                      나머지는 unhashed 로 남긴다 (Stage 2-A 정책 그대로).
        "all"       - 크기·확장자 무관 전량 해시. active asset·production blend·HDRI·
                      GLB/OBJ/USD·golden reference·release package 를 옮길 때 필수.
    """
    if hash_mode not in HASH_MODES:
        raise ValueError("unknown hash mode %r (expected %s)" % (hash_mode, list(HASH_MODES)))
    hash_all_sizes = hash_all_sizes or set()
    files = {}
    hashes = {}
    hashed_large = []
    total = 0
    started = _now()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = _posix(os.path.relpath(abs_path, root))
            size = os.path.getsize(abs_path)
            files[rel] = size
            total += size
            ext = os.path.splitext(name)[1].lower()
            want = hash_mode == HASH_MODE_ALL or (
                size <= HASH_SIZE_LIMIT
                or ext in HASH_ALWAYS_EXT
                or "manifest" in name.lower()
                or size in hash_all_sizes)
            if want:
                hashes[rel] = _sha256(abs_path)
                if size > HASH_SIZE_LIMIT:
                    hashed_large.append(rel)
    unhashed = sorted(set(files) - set(hashes))
    if hash_mode == HASH_MODE_ALL and unhashed:
        # 여기 걸리면 정책이 깨진 것이다. 조용히 넘기지 않는다.
        raise RuntimeError(
            "hash-mode=all 인데 해시되지 않은 파일이 %d개 있습니다: %s"
            % (len(unhashed), unhashed[:5]))
    return {
        "file_count": len(files),
        "total_bytes": total,
        "files": files,
        "sha256": hashes,
        "hashed_over_limit": hashed_large,
        "unhashed": unhashed,
        "hash_mode": hash_mode,
        "hashed_file_count": len(hashes),
        "unhashed_file_count": len(unhashed),
        "hash_started_at": started,
        "hash_completed_at": _now(),
    }


def snapshot_file(path, hash_mode=HASH_MODE_ALL):
    """단일 파일 entry 의 snapshot. directory snapshot 과 같은 스키마를 돌려준다.

    상대경로 키는 basename 하나뿐이다. 이렇게 두면 verify/rollback 이 directory 와
    같은 코드 경로를 쓸 수 있고, manifest 스키마도 갈라지지 않는다.
    """
    if hash_mode != HASH_MODE_ALL:
        raise ValueError("file entry 는 hash-mode=all 만 허용한다 (받은 값: %r)" % hash_mode)
    name = os.path.basename(path)
    size = os.path.getsize(path)
    started = _now()
    digest = _sha256(path)
    return {
        "file_count": 1,
        "total_bytes": size,
        "files": {name: size},
        "sha256": {name: digest},
        "hashed_over_limit": [name] if size > HASH_SIZE_LIMIT else [],
        "unhashed": [],
        "hash_mode": hash_mode,
        "hashed_file_count": 1,
        "unhashed_file_count": 0,
        "hash_started_at": started,
        "hash_completed_at": _now(),
    }


def precheck_file(src_abs, dst_abs, data_root, policy):
    """파일 entry 사전검사. directory 판정을 그대로 쓰면 SOURCE_NOT_A_DIRECTORY 로 막힌다."""
    problems = []
    stats = {"file_count": 0, "total_bytes": 0, "inaccessible": 0,
             "path_over_limit": 0, "reserved_name": 0, "symlink": 0,
             "forbidden_ext": [], "license_files": []}
    if not os.path.isfile(src_abs):
        problems.append("SOURCE_NOT_A_FILE")
        return problems, stats
    if os.path.islink(src_abs):
        problems.append("SOURCE_IS_SYMLINK")
        stats["symlink"] = 1
    if os.path.exists(dst_abs):
        problems.append("DEST_COLLISION")

    name = os.path.basename(src_abs)
    stats["file_count"] = 1
    try:
        stats["total_bytes"] = os.path.getsize(src_abs)
        with open(src_abs, "rb") as fh:
            fh.read(1)
    except OSError:
        stats["inaccessible"] = 1
        problems.append("INACCESSIBLE_FILE=1")
    if len(dst_abs) > MAX_PATH_LEN:
        stats["path_over_limit"] = 1
        problems.append("PATH_LENGTH_OVER_240")
    if os.path.splitext(name)[0].upper() in RESERVED_WIN:
        stats["reserved_name"] = 1
        problems.append("RESERVED_WINDOWS_NAME")
    ext = os.path.splitext(name)[1].lower()
    if ext in policy["forbidden_ext"]:
        stats["forbidden_ext"].append(name)
        problems.append("FORBIDDEN_EXTENSION=1")
    if any(h in name.lower() for h in LICENSE_HINTS):
        stats["license_files"].append(name)
    if stats["total_bytes"] > policy["max_single_bytes"]:
        problems.append("OVER_SINGLE_SIZE_LIMIT")
    if not is_within(src_abs, data_root):
        problems.append("SOURCE_OUTSIDE_DATA_ROOT")
    if not is_within(os.path.dirname(dst_abs), data_root):
        problems.append("DEST_OUTSIDE_DATA_ROOT")
    return problems, stats


def archive_files_under(root_abs):
    """root 아래의 archive 확장자 파일 상대경로 목록 (정렬)."""
    found = []
    for dirpath, _d, filenames in os.walk(root_abs):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in ARCHIVE_EXT:
                found.append(_posix(os.path.relpath(os.path.join(dirpath, name), root_abs)))
    return sorted(found)


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
def precheck(src_abs, dst_abs, referenced_by, data_root, policy=None):
    """이동 사전검사. policy 를 주지 않으면 Stage 2-A 정책으로 검사한다(하위호환)."""
    policy = policy or POLICIES[POLICY_STAGE2A]
    forbidden_ext = policy["forbidden_ext"]
    license_is_blocker = policy["license_is_blocker"]
    max_single = policy["max_single_bytes"]
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
            if ext in forbidden_ext:
                stats["forbidden_ext"].append(_posix(rel))
            if any(h in name.lower() for h in LICENSE_HINTS):
                stats["license_files"].append(_posix(rel))

    if stats["file_count"] == 0:
        problems.append("EMPTY_DIRECTORY")
    if stats["total_bytes"] > max_single:
        problems.append("OVER_SINGLE_SIZE_LIMIT")
    for key, label in (("inaccessible", "INACCESSIBLE_FILE"),
                       ("path_over_limit", "PATH_LENGTH_OVER_240"),
                       ("reserved_name", "RESERVED_WINDOWS_NAME"),
                       ("symlink", "SYMLINK_OR_REPARSE")):
        if stats[key]:
            problems.append("%s=%d" % (label, stats[key]))
    if stats["forbidden_ext"]:
        problems.append("FORBIDDEN_EXTENSION=%d" % len(stats["forbidden_ext"]))
    if stats["license_files"] and license_is_blocker:
        # Stage 2-A: run 폴더에 라이선스 파일이 있는 것은 이상 신호였다.
        # Stage 2-B: 자산과 함께 보존해야 하므로 blocker 가 아니다(개수·해시만 기록·검증).
        problems.append("LICENSE_FILE=%d" % len(stats["license_files"]))
    if not is_within(src_abs, data_root):
        problems.append("SOURCE_OUTSIDE_DATA_ROOT")
    # destination 자체는 아직 없으므로 realpath 가 부모까지만 접힌다. 부모도 함께 본다.
    if not is_within(dst_abs, data_root) or not is_within(os.path.dirname(dst_abs), data_root):
        problems.append("DEST_OUTSIDE_DATA_ROOT")
    return problems, stats


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------
def _stage2a_candidates(args, policy):
    """Stage 2-A: proposed_moves.csv 의 SAFE_CANDIDATE 중 허용 목적지 prefix 만."""
    rows = list(csv.DictReader(open(args.moves, encoding="utf-8-sig")))
    for row in rows:
        if row.get("status") != "SAFE_CANDIDATE":
            continue
        dest = row["destination"]
        if not dest.startswith(policy["allowed_dest_prefixes"]):
            continue
        src_rel = row["source"]
        leaf = src_rel.rstrip("/").split("/")[-1]
        dst_rel = "data/pallet/" + dest.rstrip("/") + "/" + leaf
        # 문서(md)만의 참조는 "code/config/test direct reference" 가 아니다.
        code_refs = [r for r in (row.get("required_code_changes") or "").split(";") if r]
        test_refs = [r for r in (row.get("required_test_changes") or "").split(";")
                     if r and r != "none"]
        blocking = [r for r in code_refs if r != "none"] + test_refs
        yield src_rel, dst_rel, blocking, ""


def _stage2b_candidates(args, policy):
    """Stage 2-B: exact allowlist. --cohort 로 걸러 cohort 별 manifest 를 만든다."""
    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    only = set(x.strip() for x in (args.only_source or "").split(",") if x.strip())
    for src_rel, dst_rel, cohort in policy["allowlist"]:
        if wanted and cohort not in wanted:
            continue
        if only and src_rel not in only:
            continue
        yield src_rel, dst_rel, [], cohort


def _stage2c2_candidates(args, policy, paths):
    """Stage 2-C2: C2A 는 실측 archive 파일, C2B/C2C 는 exact directory allowlist."""
    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    only = set(x.strip() for x in (args.only_source or "").split(",") if x.strip())

    if not wanted or "C2A_BACKGROUND_PACKAGES" in wanted:
        src_root = os.path.join(paths.project_root,
                                C2A_ARCHIVE_SOURCE_ROOT.replace("/", os.sep))
        for rel in archive_files_under(src_root):
            src_rel = "%s/%s" % (C2A_ARCHIVE_SOURCE_ROOT, rel)
            dst_rel = "%s/%s" % (C2A_ARCHIVE_DEST_ROOT, rel)   # 상대경로 보존 (평탄화 금지)
            if only and src_rel not in only:
                continue
            yield src_rel, dst_rel, [], "C2A_BACKGROUND_PACKAGES", ENTRY_FILE, \
                "C2A_BACKGROUND_PACKAGES"

    for src_rel, dst_rel, cohort, kind, group in policy["allowlist"]:
        if wanted and cohort not in wanted:
            continue
        if only and src_rel not in only:
            continue
        yield src_rel, dst_rel, [], cohort, kind, group


def cmd_plan(args, paths):
    policy_name = getattr(args, "policy", POLICY_STAGE2A)
    policy = get_policy(policy_name)
    required_hash = policy["require_hash_mode"]
    if required_hash and args.hash_mode != required_hash:
        print("정책 %s 는 --hash-mode %s 를 요구합니다 (현재 %s)."
              % (policy_name, required_hash, args.hash_mode), file=sys.stderr)
        return 2

    data_root = paths.get("pallet_data_root")
    allow_empty = args.allow_empty_dirs
    if policy_name == POLICY_STAGE2C2:
        gen = lambda a, p: _stage2c2_candidates(a, p, paths)   # noqa: E731
    elif policy["allowlist"]:
        gen = lambda a, p: ((s, d, b, c, ENTRY_DIRECTORY, c)   # noqa: E731
                            for s, d, b, c in _stage2b_candidates(a, p))
    else:
        gen = lambda a, p: ((s, d, b, c, ENTRY_DIRECTORY, c)   # noqa: E731
                            for s, d, b, c in _stage2a_candidates(a, p))

    planned, skipped = [], []
    running_total = 0
    for src_rel, dst_rel, blocking, cohort, entry_kind, group in gen(args, policy):
        if not src_rel.startswith("data/pallet/"):
            skipped.append((src_rel, "SOURCE_NOT_UNDER_DATA_PALLET"))
            continue
        if src_rel in EXPLICIT_EXCLUSIONS:
            skipped.append((src_rel, "EXPLICIT_EXCLUSION: " + EXPLICIT_EXCLUSIONS[src_rel]))
            continue
        src_abs = os.path.join(paths.project_root, src_rel.replace("/", os.sep))
        dst_abs = os.path.join(paths.project_root, dst_rel.replace("/", os.sep))

        if entry_kind == ENTRY_FILE:
            problems, stats = precheck_file(src_abs, dst_abs, data_root, policy)
        else:
            problems, stats = precheck(src_abs, dst_abs, blocking, data_root, policy=policy)
            # directory cohort 에 archive 가 남아 있으면 거부한다. ZIP 은 C2A 에서만 옮긴다.
            allowed_archive = policy.get("archive_allowed_cohorts", ())
            if cohort not in allowed_archive:
                leftover = archive_files_under(src_abs) if os.path.isdir(src_abs) else []
                if leftover:
                    problems.append("ARCHIVE_IN_NON_PACKAGE_COHORT=%d" % len(leftover))
        if allow_empty and problems == ["EMPTY_DIRECTORY"]:
            problems = []
        if problems:
            skipped.append((src_rel, ";".join(problems)))
            continue
        if running_total + stats["total_bytes"] > policy["max_total_bytes"]:
            skipped.append((src_rel, "OVER_TOTAL_SIZE_LIMIT"))
            continue
        running_total += stats["total_bytes"]

        if entry_kind == ENTRY_FILE:
            snap = snapshot_file(src_abs, hash_mode=args.hash_mode)
        else:
            dup_sizes = (duplicate_size_set(src_abs)
                         if args.hash_mode == HASH_MODE_SELECTIVE else set())
            snap = snapshot(src_abs, dup_sizes, hash_mode=args.hash_mode)
        planned.append({
            "move_id": "%s%03d" % (args.move_id_prefix or policy["move_id_prefix"],
                                   len(planned) + 1),
            "policy": policy_name,
            "cohort": cohort,
            "entry_kind": entry_kind,
            "transaction_group": group,
            "license_files": sorted(stats["license_files"]),
            "source": src_rel,
            "destination": dst_rel,
            "relative_files": sorted(snap["files"]),
            "file_count": snap["file_count"],
            "total_bytes": snap["total_bytes"],
            "hash_mode": snap["hash_mode"],
            "hashed_file_count": snap["hashed_file_count"],
            "unhashed_file_count": snap["unhashed_file_count"],
            "hash_started_at": snap["hash_started_at"],
            "hash_completed_at": snap["hash_completed_at"],
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

    # 그룹 완전성: C2C 처럼 함께 가야 하는 source 가 한쪽만 계획되면 계획 자체를 거부한다.
    planned_sources = {p["source"] for p in planned}
    planned_groups = {p.get("transaction_group") for p in planned}
    for group, required in REQUIRED_GROUP_SOURCES.items():
        if group not in planned_groups:
            continue
        missing = [s for s in required if s not in planned_sources]
        if missing:
            print("그룹 %s 가 불완전합니다. 계획하지 않습니다: 누락 %s"
                  % (group, ", ".join(missing)), file=sys.stderr)
            for s in missing:
                reason = dict(skipped).get(s, "NOT_PLANNED")
                print("   %s -> %s" % (s, reason), file=sys.stderr)
            return 2

    os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        for row in planned:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    skip_path = os.path.splitext(args.manifest)[0] + "_skipped.csv"
    with open(skip_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "reason"])
        w.writerows(skipped)

    hashed = sum(p["hashed_file_count"] for p in planned)
    unhashed = sum(p["unhashed_file_count"] for p in planned)
    print("policy   : %s" % policy_name)
    print("planned  : %d moves" % len(planned))
    print("files    : %d" % sum(p["file_count"] for p in planned))
    print("bytes    : %d (%.3f GB)" % (running_total, running_total / 1e9))
    print("hash-mode: %s" % args.hash_mode)
    print("hashed   : %d / unhashed : %d" % (hashed, unhashed))
    print("license  : %d files preserved"
          % sum(len(p.get("license_files", [])) for p in planned))
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
def _entry_kind(row):
    """manifest row 의 entry_kind. Stage 2-A/2-B row 에는 필드가 없다(전부 directory)."""
    kind = row.get("entry_kind")
    return kind if kind in ENTRY_KINDS else ENTRY_DIRECTORY


def _undo_move(row, paths):
    """한 row 를 원위치로 되돌린다 (그룹 실패 시 부분 rollback 용)."""
    src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
    dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
    if os.path.exists(src):
        raise RuntimeError("원래 자리에 이미 무언가 있습니다(덮어쓰지 않음): %s" % row["source"])
    if not os.path.exists(dst):
        raise RuntimeError("되돌릴 destination이 없습니다: %s" % row["destination"])
    parent = os.path.dirname(src)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    os.rename(dst, src)


def cmd_apply(args, paths):
    rows = _read_manifest(args.manifest)
    done = 0
    applied_in_group = {}
    for row in rows:
        if row["status"] == "MOVED":
            continue
        src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
        dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
        kind = _entry_kind(row)
        # 그룹 원자성은 **명시적 transaction_group 이 있는 row 에만** 적용한다.
        # Stage 2-A/2-B row 에는 이 필드가 없고, 그쪽 계약은 "실패하면 그 자리에서 멈추고
        # 이미 옮긴 것은 그대로 둔다" 이다. 여기서 그걸 바꾸면 기존 원장 의미가 달라진다.
        group = row.get("transaction_group") or None
        row["started_at"] = _now()
        try:
            exists = os.path.isfile(src) if kind == ENTRY_FILE else os.path.isdir(src)
            if not exists:
                raise RuntimeError("source가 사라졌습니다(%s): %s" % (kind, row["source"]))
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
            if group:
                applied_in_group.setdefault(group, []).append(row)
            done += 1
        except Exception as exc:         # noqa: BLE001 - 중단하고 원인을 남긴다
            row["status"] = "FAILED"
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
            print("APPLY 중단: %s -> %s" % (row["source"], row["error"]))
            # 같은 transaction_group 에서 이미 옮긴 것은 되돌린다 (원자성).
            partial = applied_in_group.get(group, []) if group else []
            for prev in reversed(partial):
                try:
                    _undo_move(prev, paths)
                    prev["status"] = "ROLLED_BACK"
                    prev["rollback_status"] = "GROUP_FAILURE@" + _now()
                    done -= 1
                    print("  group rollback: %s 되돌림" % prev["source"])
                except Exception as undo_exc:   # noqa: BLE001
                    prev["rollback_status"] = "FAILED: %s: %s" % (
                        type(undo_exc).__name__, undo_exc)
                    print("  group rollback 실패: %s -> %s"
                          % (prev["source"], prev["rollback_status"]))
            _write_manifest(args.manifest, rows)
            print("이동 완료 %d건. 나머지 rollback 은 --rollback 으로." % done)
            return 1

    # 그룹 완전성: 그룹 안의 모든 row 가 MOVED 여야 한다 (명시적 그룹만).
    by_group = {}
    for row in rows:
        g = row.get("transaction_group")
        if g:
            by_group.setdefault(g, []).append(row)
    for group, grp in by_group.items():
        moved = [r for r in grp if r["status"] == "MOVED"]
        if moved and len(moved) != len(grp):
            print("그룹 %s 가 불완전하게 적용되었습니다 (%d/%d). 역순 rollback 합니다."
                  % (group, len(moved), len(grp)), file=sys.stderr)
            for prev in reversed(moved):
                _undo_move(prev, paths)
                prev["status"] = "ROLLED_BACK"
                prev["rollback_status"] = "GROUP_INCOMPLETE@" + _now()
            _write_manifest(args.manifest, rows)
            return 1

    _write_manifest(args.manifest, rows)
    print("applied  : %d moves" % done)
    return 0


# ---------------------------------------------------------------------------
# --verify
# ---------------------------------------------------------------------------
def manifest_hash_mode(row):
    """manifest row 의 hash_mode. Stage 2-A 이전 row 에는 필드가 없다.

    없으면 "selective-legacy" 로 해석한다. **row 를 고쳐 쓰지 않는다** —
    move_transaction.jsonl 은 실이동의 유일한 rollback 원장이라 재작성 대상이 아니다.
    """
    mode = row.get("hash_mode")
    if mode in HASH_MODES:
        return mode
    return HASH_MODE_LEGACY


def cmd_verify(args, paths):
    rows = _read_manifest(args.manifest)
    failures = []
    checked_files = checked_bytes = checked_hashes = checked_licenses = 0
    modes = {}
    for row in rows:
        if row["status"] != "MOVED":
            continue
        mode = manifest_hash_mode(row)
        modes[mode] = modes.get(mode, 0) + 1
        pre_unhashed = row.get("pre_hash_manifest", {}).get("unhashed", [])
        if mode == HASH_MODE_ALL and pre_unhashed:
            failures.append((row["move_id"],
                             "HASH_MODE_ALL_WITH_UNHASHED=%d" % len(pre_unhashed)))
        dst = os.path.join(paths.project_root, row["destination"].replace("/", os.sep))
        src = os.path.join(paths.project_root, row["source"].replace("/", os.sep))
        pre = row["pre_hash_manifest"]
        kind = _entry_kind(row)
        if kind == ENTRY_FILE:
            if not os.path.isfile(dst):
                failures.append((row["move_id"], "DEST_FILE_MISSING %s" % row["destination"]))
                continue
            post = snapshot_file(dst, hash_mode=HASH_MODE_ALL)
            # 파일 entry 는 destination 자체가 파일이므로 해시 대조 기준 디렉토리를 바꾼다.
            dst_dir = os.path.dirname(dst)
        else:
            post = snapshot(dst, set())
            dst_dir = dst
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
            abs_path = os.path.join(dst_dir, rel.replace("/", os.sep))
            if not os.path.isfile(abs_path):
                failures.append((row["move_id"], "MISSING %s" % rel))
                continue
            got = _sha256(abs_path)
            checked_hashes += 1
            if got != want:
                failures.append((row["move_id"], "SHA256 %s" % rel))
        # 라이선스 파일은 자산과 함께 살아 있어야 한다. 하나라도 빠지면 실패.
        for rel in row.get("license_files", []):
            if not os.path.isfile(os.path.join(dst_dir, rel.replace("/", os.sep))):
                failures.append((row["move_id"], "LICENSE_FILE_LOST %s" % rel))
            else:
                checked_licenses += 1
        if os.path.exists(src):
            failures.append((row["move_id"], "SOURCE_STILL_EXISTS %s" % row["source"]))
        checked_files += post["file_count"]
        checked_bytes += post["total_bytes"]

    print("verified moves : %d" % sum(1 for r in rows if r["status"] == "MOVED"))
    print("files          : %d" % checked_files)
    print("bytes          : %d (%.3f GB)" % (checked_bytes, checked_bytes / 1e9))
    print("sha256 checked : %d" % checked_hashes)
    print("hash modes     : %s" % (", ".join("%s=%d" % kv for kv in sorted(modes.items()))
                                   or "(none)"))
    print("license files  : %d verified" % checked_licenses)
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
        try:
            _undo_move(row, paths)
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
    ap.add_argument("--hash-mode", choices=list(HASH_MODES), default=HASH_MODE_SELECTIVE,
                    help="selective(기본, Stage 2-A 정책) 또는 all(전량 SHA256 — "
                         "active asset/production blend/HDRI/3D/golden reference 이동 시 필수)")
    ap.add_argument("--move-id-prefix", default=None,
                    help="--plan 이 붙일 move_id 접두 (기본: 정책별 S2A/S2B)")
    ap.add_argument("--policy", choices=list(POLICIES), default=POLICY_STAGE2A,
                    help="이동 정책. 생략하면 stage2a-runs (하위호환)")
    ap.add_argument("--cohort", default=None,
                    help="stage2b 전용: 이 cohort 만 계획 (예: B1_REFERENCE_MATERIALS)")
    ap.add_argument("--only-source", default=None,
                    help="stage2b 전용: 이 source 만 계획 (쉼표 구분, allowlist 안이어야 함)")
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
