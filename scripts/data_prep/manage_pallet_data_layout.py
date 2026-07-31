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
# Stage 2-D2: 이 함정 자체를 해소했다 — audit_v2_dryrun.py 의 DEFAULT_OUT 을
# runs/diagnostics/ 로 옮겨서 재실행이 옛 경로를 되살리지 않는다. 가드는 지우지 않고
# 해소 사실을 남긴다(다시 archive 를 기본 출력으로 만들면 같은 문제가 재발한다).
EXPLICIT_EXCLUSIONS = {}
RESOLVED_EXCLUSIONS = {
    "data/pallet/v2_dryrun_audit":
        "Stage 2-D2 해소: audit_v2_dryrun.py DEFAULT_OUT -> "
        "data/pallet/runs/diagnostics/v2_dryrun_audit (재생성 함정 제거)",
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
#   stage2d1-archive-finalization
#     archive/ **안**의 평면 배치를 의미별 하위폴더로 정리한다. 앞선 정책들과 달리
#     allowlist 가 코드 상수가 아니라 **동결된 계획 CSV** 다 — Stage 2-D0.1 이
#     40행을 확정했고 그 파일의 SHA256 으로 결속한다. 계획이 한 바이트라도 바뀌면
#     plan/apply 가 거부된다.
POLICY_STAGE2D1 = "stage2d1-archive-finalization"

# Stage 2-D1 계획에서 이동 대상으로 허용하는 status. 그 외는 전부 거부한다.
D1_MOVE_STATUS = ("READY", "CORRUPT_MOVE_READY")
# 계획에 들어오면 안 되는 status (들어오면 계획 자체를 거부한다).
D1_FORBIDDEN_STATUS = (
    "BLOCKED_REFERENCE", "BLOCKED_ACTIVE", "BLOCKED_ROLLBACK", "BLOCKED_LICENSE",
    "BLOCKED_UNKNOWN", "KEEP_ACTIVE", "KEEP_ROLLBACK", "KEEP_QUARANTINE",
    "KEEP_CURRENT", "NEEDS_CRC",
)
# ZIP 을 옮길 수 있는 cohort. corrupt package 는 D1B 만.
D1_ARCHIVE_COHORTS = ("D1A_PACKAGES", "D1B_CORRUPT")
D1_CORRUPT_COHORT = "D1B_CORRUPT"
D1_SCHEMA_VERSION = "stage2d1.1"

#   stage2d11-residual-finalization
#     Stage 2-D1 이 남긴 잔여 3범위를 처리한다. D1 policy 와 다른 점 두 가지:
#       (a) allowlist 가 frozen_scope.json (계획 CSV 가 아니라 재계산된 범위)
#       (b) prior ledger 구성원이어도 **successor chain 계획이 있으면** 이동을 허용한다
#           (D1 은 무조건 거부였다 — 그게 D1D 를 막은 guard 다)
POLICY_STAGE2D11 = "stage2d11-residual-finalization"
D11_SCHEMA_VERSION = "stage2d11.1"
D11_COHORTS = ("D11A_BLEND_BACKUPS", "D11B_REFERENCE_TRANSITION",
               "D11C_LICENSE_RESOLUTION")

#   stage2d12-final-moves
#     Stage 2-D1.1 이 준비만 해 둔 두 cohort 의 실이동. D11 policy 와 다른 점:
#       (a) scope CSV 스키마가 다르다 — 목적지·registry key 전환·provenance 판정이
#           이미 CSV 에 확정돼 있다 (D11 은 scope 열로 분류만 했다)
#       (b) PROVEN_NOAI row 는 noai_baked/ 목적지만 허용하고 redistributable·packages·
#           unidentified·release 로는 절대 보내지 않는다
#     기존 policy 4개 동작은 바꾸지 않는다.
POLICY_STAGE2D12 = "stage2d12-final-moves"
D12_SCHEMA_VERSION = "stage2d12.1"
D12_COHORTS = ("D12B_REFERENCE_MOVE", "D12C_PROVEN_NOAI_MOVE")
D12_NOAI_DEST_ROOT = "data/pallet/archive/legacy_datasets/noai_baked"
# PROVEN_NOAI 자료가 절대 가면 안 되는 목적지 조각
D12_FORBIDDEN_NOAI_DEST = ("/redistributable/", "/packages/", "/unidentified/",
                           "/release/", "/partial/")

#   stage2d2-layout-completion
#     Stage 2-A archive 계획에 destination 이 있으나 executed=no 로 남아 있던 물리적
#     잔여를 최종 destination 으로 옮겨 레이아웃 정책을 닫는 단계.
#     앞선 policy 와 다른 점:
#       (a) allowlist 가 frozen_final_plan.csv 다 (SHA256 결속)
#       (b) cohort 를 destination 의 semantic root 에서 유도한다 — 임의 숫자 분할 금지
#       (c) 빈 디렉토리를 **보존 이동**할 수 있다 (삭제 금지 정책 유지)
#       (d) 제한 라이선스(HIGH/NoAI/EULA)는 redistributable·release 로 못 간다
#     기존 policy 6개 동작은 바꾸지 않는다.
POLICY_STAGE2D2 = "stage2d2-layout-completion"
D2_SCHEMA_VERSION = "stage2d2.1"
D2_COHORTS = ("D2_SUPERSEDED_RUNS", "D2_LEGACY_DATASETS", "D2_LEGACY_SCENES",
              "D2_LEGACY_ASSETS", "D2_PACKAGES", "D2_NONREDISTRIBUTABLE",
              "D2_LEGACY_LAYOUT")
# §3 이 승인한 final root. 이번 단계에서 catch-all 폴더를 새로 만들지 않는다.
D2_ALLOWED_DEST_ROOTS = (
    "data/pallet/archive/legacy_datasets/",
    "data/pallet/archive/legacy_scenes/",
    "data/pallet/archive/legacy_assets/",
    "data/pallet/archive/packages/",
    "data/pallet/archive/superseded_runs/",
    "data/pallet/archive/nonredistributable/",
    "data/pallet/archive/legacy_layout/",
)
# 제한 라이선스 자료가 절대 가면 안 되는 목적지 조각
D2_FORBIDDEN_RESTRICTED_DEST = ("/redistributable/", "/release/")
# 비어 있어도 유지해야 하는 최종 semantic container (stale empty 로 오분류 금지)
D2_POLICY_CONTAINERS = (
    "data/pallet/archive/legacy_datasets", "data/pallet/archive/legacy_scenes",
    "data/pallet/archive/legacy_assets", "data/pallet/archive/packages",
    "data/pallet/archive/superseded_runs", "data/pallet/archive/nonredistributable",
    "data/pallet/archive/legacy_layout", "data/pallet/archive/unidentified",
    "data/pallet/archive/duplicates", "data/pallet/archive/corrupt",
    "data/pallet/release", "data/pallet/reference", "data/pallet/runs",
    "data/pallet/manifests", "data/pallet/assets",
)

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
    POLICY_STAGE2D1: {
        # archive/ 안으로만 옮긴다. assets/ · reference/ · runs/ · release/ 는 목적지가 아니다.
        "allowed_dest_prefixes": ("archive/",),
        "allowlist": None,                      # 동결된 계획 CSV 가 allowlist 다
        # weight 만 절대 금지. ZIP 은 D1A/D1B cohort 에서만 허용(cohort 검사로 따로 막는다).
        "forbidden_ext": {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt",
                          ".safetensors"},
        # ZIP 규칙은 두 층으로 나눈다.
        #   (a) **entry** 로서의 ZIP  -> D1A/D1B cohort 만 (generator 의 row 단위 검사)
        #   (b) dataset 안에 들어 있어 **딸려 가는** ZIP -> 허용하되, 그 ZIP 이 같은 계획에
        #       별도 row 로도 잡혀 있으면 거부 (한 파일을 두 경로로 옮기려는 모순)
        # C2C 때의 blanket 금지는 "background 의 ZIP 을 C2A 가 먼저 분리한다" 는 별개
        # 요구였다. D1C 의 archive/training_data_v4_split/training_data_v4_split.zip 은
        # 별도 계획 row 가 없는 dataset 내용물이라 함께 가는 것이 맞다.
        "archive_allowed_cohorts": ("D1A_PACKAGES", "D1B_CORRUPT",
                                    "D1C_LEGACY_DATASETS", "D1D_BLEND_BACKUPS"),
        "license_is_blocker": False,            # 라이선스 파일은 dataset 과 함께 보존한다
        # D1A 의 pallet.zip 은 15.5 GiB, D1C 의 dataset 은 최대 10 GiB 수준이다.
        "max_single_bytes": 32 * 1024 ** 3,
        "max_total_bytes": 140 * 1024 ** 3,     # 계획 합계 132.37 GiB
        "require_hash_mode": HASH_MODE_ALL,     # 전수 SHA256 강제 (selective 강등 금지)
        "move_id_prefix": "S2D1",
    },
    POLICY_STAGE2D11: {
        # archive/ 안으로만. D11A 는 legacy_scenes/, D11B/D11C 는 계획이 정한 곳.
        "allowed_dest_prefixes": ("archive/",),
        "allowlist": None,                      # frozen_scope.json 이 allowlist 다
        "forbidden_ext": {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt",
                          ".safetensors"},
        # ZIP 을 entry 로 옮기지 않는다 — 이번 범위에 package row 가 없다.
        # dataset 안에 딸려 가는 ZIP 은 D1 과 같은 규칙으로 허용한다.
        "archive_allowed_cohorts": D11_COHORTS,
        "license_is_blocker": False,
        "max_single_bytes": 32 * 1024 ** 3,
        "max_total_bytes": 40 * 1024 ** 3,      # 범위 합계 32.90 GiB
        "require_hash_mode": HASH_MODE_ALL,
        "move_id_prefix": "S2D11",
    },
    POLICY_STAGE2D12: {
        "allowed_dest_prefixes": ("archive/",),
        "allowlist": None,                      # frozen_scope.csv 가 allowlist 다
        "forbidden_ext": {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt",
                          ".safetensors"},
        # dataset 안에 딸려 가는 ZIP 은 D1/D1.1 과 같은 규칙으로 허용한다.
        "archive_allowed_cohorts": D12_COHORTS,
        "license_is_blocker": False,
        "max_single_bytes": 32 * 1024 ** 3,
        "max_total_bytes": 40 * 1024 ** 3,      # cohort 최대 16.14 GiB
        "require_hash_mode": HASH_MODE_ALL,
        "move_id_prefix": "S2D12",
    },
    POLICY_STAGE2D2: {
        "allowed_dest_prefixes": ("archive/",),
        "allowlist": None,                      # frozen_final_plan.csv 가 allowlist 다
        "forbidden_ext": {".pt", ".pth", ".ckpt", ".onnx", ".engine", ".trt",
                          ".safetensors"},
        "archive_allowed_cohorts": D2_COHORTS,
        "license_is_blocker": False,
        "max_single_bytes": 32 * 1024 ** 3,
        "max_total_bytes": 40 * 1024 ** 3,      # 전체 계획 5.47 GiB
        "require_hash_mode": HASH_MODE_ALL,
        "move_id_prefix": "S2D2",
    },
}


def get_policy(name):
    if name not in POLICIES:
        raise ValueError("unknown policy %r (expected %s)" % (name, list(POLICIES)))
    return POLICIES[name]


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class HashBudgetExceeded(RuntimeError):
    """해시 read 예산 초과. selective 로 강등하지 않고 중단한다."""


class HashBudget:
    """SHA256 read 예산. 실제 읽은 바이트를 세고, 넘으면 즉시 예외.

    Stage 2-D1 은 파일을 이동 전·후로 두 번 읽는다(132 GiB × 2 ≈ 265 GiB). 예산 없이
    돌리면 어디까지 읽었는지 모르는 상태로 디스크를 몇 시간 점유한다. 그래서
      - 해시를 **시작하기 전에** stat 으로 예상 read 를 계산해 초과면 거부하고
      - 읽는 중에도 누적치를 검사한다.
    limit_bytes=None 이면 무제한(기존 정책 동작과 동일 — 옵션을 생략하면 영향 없음).
    """

    def __init__(self, limit_bytes=None, label=""):
        self.limit = limit_bytes
        self.label = label
        self.read_bytes = 0

    def precheck(self, expected_bytes):
        if self.limit is None:
            return
        if self.read_bytes + expected_bytes > self.limit:
            raise HashBudgetExceeded(
                "%s 해시 예산 초과 예상: 이미 %d + 예상 %d > 한도 %d "
                "(%.2f GiB > %.2f GiB). 해시를 시작하지 않습니다."
                % (self.label, self.read_bytes, expected_bytes, self.limit,
                   (self.read_bytes + expected_bytes) / 1024 ** 3,
                   self.limit / 1024 ** 3))

    def add(self, n):
        self.read_bytes += n
        if self.limit is not None and self.read_bytes > self.limit:
            raise HashBudgetExceeded(
                "%s 해시 예산 초과: %d > %d (%.2f GiB > %.2f GiB)"
                % (self.label, self.read_bytes, self.limit,
                   self.read_bytes / 1024 ** 3, self.limit / 1024 ** 3))


def _sha256(path, budget=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
            if budget is not None:
                budget.add(len(block))
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
def snapshot(root, hash_all_sizes=None, hash_mode=HASH_MODE_SELECTIVE, budget=None):
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
    # 1단계: stat 만으로 전체 크기를 먼저 잰다. hash-mode=all 이면 그게 곧 예상 read 량
    # 이므로 **한 바이트도 읽기 전에** 예산을 검사할 수 있다.
    entries = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = _posix(os.path.relpath(abs_path, root))
            size = os.path.getsize(abs_path)
            entries.append((abs_path, rel, name, size))
            files[rel] = size
            total += size
    if budget is not None and hash_mode == HASH_MODE_ALL:
        budget.precheck(total)
    started = _now()
    # 2단계: 실제 해시. worker=1 (순차) — 여러 cohort 를 동시에 읽지 않는다는 규율과
    # 디스크 thrashing 방지가 목적이다.
    for abs_path, rel, name, size in entries:
        ext = os.path.splitext(name)[1].lower()
        want = hash_mode == HASH_MODE_ALL or (
            size <= HASH_SIZE_LIMIT
            or ext in HASH_ALWAYS_EXT
            or "manifest" in name.lower()
            or size in hash_all_sizes)
        if want:
            hashes[rel] = _sha256(abs_path, budget=budget)
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
        "hash_read_bytes": (sum(files[r] for r in hashes) if hashes else 0),
    }


def stat_only_snapshot(root):
    """해시 없이 (상대경로 -> 크기) 만. verify 의 count/bytes/relpath 대조 전용.

    Stage 2-D1 이 필요해서 넣었다. 기존 verify 는 post snapshot 을 selective 로 떠서
    8MB 이하 파일을 **다시** 읽는데, 그 뒤 pre["sha256"] 루프가 같은 파일을 또 읽는다.
    D1C 처럼 191,503개가 대부분 작은 파일이면 post read 가 두 배가 되어 예산을 날린다.
    해시는 pre["sha256"] 루프가 전담하므로 여기서는 stat 만 한다.
    """
    files = {}
    total = 0
    for dirpath, _d, filenames in os.walk(root):
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = _posix(os.path.relpath(abs_path, root))
            size = os.path.getsize(abs_path)
            files[rel] = size
            total += size
    return {"file_count": len(files), "total_bytes": total, "files": files,
            "sha256": {}, "hash_mode": "stat-only", "hashed_file_count": 0,
            "unhashed_file_count": len(files), "hash_read_bytes": 0}


def snapshot_file(path, hash_mode=HASH_MODE_ALL, budget=None):
    """단일 파일 entry 의 snapshot. directory snapshot 과 같은 스키마를 돌려준다.

    상대경로 키는 basename 하나뿐이다. 이렇게 두면 verify/rollback 이 directory 와
    같은 코드 경로를 쓸 수 있고, manifest 스키마도 갈라지지 않는다.
    """
    if hash_mode != HASH_MODE_ALL:
        raise ValueError("file entry 는 hash-mode=all 만 허용한다 (받은 값: %r)" % hash_mode)
    name = os.path.basename(path)
    size = os.path.getsize(path)
    if budget is not None:
        budget.precheck(size)
    started = _now()
    digest = _sha256(path, budget=budget)
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
        "hash_read_bytes": size,
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


class PlanBindingError(Exception):
    """동결 계획 CSV 가 기대한 SHA256 과 다르거나 금지된 row 를 담고 있다."""


# 앞선 트랜잭션 원장. 여기서 옮긴 파일을 그 destination 밖으로 다시 빼면 **그 원장의
# verify 가 MISSING 으로 실패한다.** Stage 2-D1 실행 중 실제로 발생했다:
# D1D 가 blend backup 10개를 assets/scenes/production/blender_scene 밖으로 옮겼고
# 그건 Stage 2-C2 C2C 이동(S2C2002)의 구성원이라 C2C exact verify 가 11건 실패했다.
# 데이터는 안전했지만(새 원장이 위치를 기록) 검증 사슬이 끊겼다. 그래서 계획 단계에서 막는다.
PRIOR_LEDGERS = (
    "reports/data_pallet_cleanup/stage2a/move_transaction.jsonl",
    "reports/data_pallet_cleanup/stage2b/transactions/b1_reference_materials.jsonl",
    "reports/data_pallet_cleanup/stage2b/transactions/b2_lighting_models.jsonl",
    "reports/data_pallet_cleanup/stage2b/transactions/b3_scene_assets.jsonl",
    "reports/data_pallet_cleanup/stage2c2/transactions/c2a_background_packages.jsonl",
    "reports/data_pallet_cleanup/stage2c2/transactions/c2b_background_asset.jsonl",
    "reports/data_pallet_cleanup/stage2c2/transactions/c2c_distractor_scene.jsonl",
)


def prior_ledger_members(project_root, ledger_rels=PRIOR_LEDGERS):
    """앞선 원장이 "지금 여기 있어야 한다"고 주장하는 (destination, 상대경로) 목록."""
    owned = []
    for rel in ledger_rels:
        p = os.path.join(project_root, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != "MOVED":
                continue
            owned.append((rel, row["move_id"], row["destination"],
                          set(row.get("relative_files") or ())))
    return owned


def find_prior_ledger_conflict(source_rel, owned):
    """source 가 앞선 원장 destination 의 구성원이면 (원장, move_id, 설명) 을 돌려준다."""
    for rel, move_id, dest, members in owned:
        if source_rel == dest:
            return rel, move_id, "source 가 그 원장의 destination 자체"
        if source_rel.startswith(dest + "/"):
            inner = source_rel[len(dest) + 1:]
            if inner in members or any(m.startswith(inner + "/") for m in members):
                return rel, move_id, "그 원장이 옮긴 파일: %s" % inner
    return None


def load_frozen_plan(plan_path, expected_sha256):
    """Stage 2-D1 동결 계획을 읽고 SHA256 으로 결속한다.

    계획 파일이 바뀌면(한 바이트라도) 여기서 멈춘다. Stage 2-B/2-C2 는 allowlist 가
    코드 상수여서 이런 결속이 필요 없었지만, D1 은 40행이 외부 CSV 라 결속이 유일한
    "계획대로 옮긴다" 보장이다.
    """
    if not os.path.isfile(plan_path):
        raise PlanBindingError("계획 CSV 가 없습니다: %s" % plan_path)
    actual = _sha256(plan_path)
    if expected_sha256 and actual != expected_sha256:
        raise PlanBindingError(
            "계획 CSV SHA256 불일치 — 계획이 변경되었습니다.\n  expected %s\n  actual   %s"
            % (expected_sha256, actual))
    with open(plan_path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return rows, actual


def _stage2d1_candidates(args, policy, paths):
    """Stage 2-D1: 동결 계획 CSV 의 READY/CORRUPT_MOVE_READY row 만.

    금지 status 가 하나라도 선택되면 계획을 만들지 않고 예외를 던진다.
    """
    rows, actual = load_frozen_plan(args.d1_plan, args.d1_plan_sha256)
    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    only = set(x.strip() for x in (args.only_source or "").split(",") if x.strip())
    ids = set(x.strip() for x in (args.move_ids or "").split(",") if x.strip())
    owned = prior_ledger_members(paths.project_root)
    # 계획 전체의 source 집합 — dataset 안에 딸려 가는 ZIP 이 별도 row 로도 잡혀 있는지
    # 보는 데 쓴다 (한 파일을 두 경로로 옮기려는 모순 차단).
    all_plan_sources = {r["source"] for r in rows
                        if r["status"] in D1_MOVE_STATUS}

    for row in rows:
        status = row["status"]
        cohort = row["cohort"]
        if wanted and cohort not in wanted:
            continue
        if ids and row["move_id"] not in ids:
            continue
        if only and row["source"] not in only:
            continue
        if status not in D1_MOVE_STATUS:
            # cohort 는 원래 섞여 있다 — 예를 들어 D1D_BLEND_BACKUPS 17행 중 READY 는
            # 10행이고 나머지 7행은 active/rollback blend 라 KEEP 이다. 같은 cohort 에
            # 있다는 것 자체는 오류가 아니고, **선택되지 않으면** 된다.
            # 다만 호출자가 --move-ids / --only-source 로 금지 row 를 콕 집어 요구했다면
            # 조용히 건너뛰지 않고 거부한다.
            if (ids or only) and status in D1_FORBIDDEN_STATUS:
                raise PlanBindingError(
                    "이동 금지 status 를 명시적으로 요청했습니다: %s %s (%s)"
                    % (row["move_id"], status, row["source"]))
            continue
        # 계획 CSV 를 그대로 믿지 않고 여기서 다시 확인한다.
        if row["rollback_role"]:
            raise PlanBindingError("rollback/active role row: %s (%s)"
                                   % (row["move_id"], row["rollback_role"]))
        if "UNKNOWN" in row["license_status"]:
            raise PlanBindingError("UNKNOWN license row: %s" % row["move_id"])
        if row["classification"] == "LICENSE_QUARANTINE":
            raise PlanBindingError("quarantine row: %s" % row["move_id"])
        if row["source"].startswith("weights/"):
            raise PlanBindingError("weight source row: %s" % row["move_id"])
        if int(row["current_runtime_refs"] or 0) or int(row["current_test_refs"] or 0):
            raise PlanBindingError(
                "CURRENT 참조가 살아있는 row: %s (runtime %s / test %s)"
                % (row["move_id"], row["current_runtime_refs"], row["current_test_refs"]))
        dest = row["destination"]
        if not dest.startswith("data/pallet/archive/"):
            raise PlanBindingError("목적지가 archive/ 밖입니다: %s -> %s"
                                   % (row["move_id"], dest))
        # prefix 검사만으로는 escape 를 막을 수 없다:
        # "data/pallet/archive/../../../escaped" 도 prefix 를 통과한다.
        # 정규화 후 archive/ 안에 남는지 본다. escape 는 skip 이 아니라 **계획 거부**다 —
        # 동결된 계획에 escape 가 있다는 것은 계획 자체가 신뢰할 수 없다는 뜻이다.
        arch_root = os.path.normpath("data/pallet/archive")
        if os.path.commonpath([os.path.normpath(dest), arch_root]) != arch_root:
            raise PlanBindingError("목적지가 archive/ 밖으로 나갑니다(escape): %s -> %s"
                                   % (row["move_id"], dest))
        if ".." in dest.split("/") or ".." in row["source"].split("/"):
            raise PlanBindingError("경로에 .. 가 있습니다: %s" % row["move_id"])
        kind = row["entry_kind"] if row["entry_kind"] in ENTRY_KINDS else ENTRY_DIRECTORY
        # ZIP 은 D1A/D1B 만. corrupt package 는 D1B 만.
        if os.path.splitext(row["source"])[1].lower() in ARCHIVE_EXT:
            if cohort not in D1_ARCHIVE_COHORTS:
                raise PlanBindingError("ZIP 은 %s cohort 에서만 허용: %s (%s)"
                                       % (", ".join(D1_ARCHIVE_COHORTS),
                                          row["move_id"], cohort))
        if row["classification"] == "CORRUPT_PACKAGE" and cohort != D1_CORRUPT_COHORT:
            raise PlanBindingError("corrupt package 는 %s 에서만 허용: %s (%s)"
                                   % (D1_CORRUPT_COHORT, row["move_id"], cohort))
        if kind == ENTRY_DIRECTORY:
            src_abs = os.path.join(paths.project_root,
                                   row["source"].replace("/", os.sep))
            for inner in (archive_files_under(src_abs)
                          if os.path.isdir(src_abs) else []):
                inner_rel = "%s/%s" % (row["source"], inner)
                if inner_rel in all_plan_sources:
                    raise PlanBindingError(
                        "dataset 안의 package 가 별도 row 로도 계획돼 있습니다 — 한 파일을 "
                        "두 경로로 옮길 수 없습니다: %s 안의 %s"
                        % (row["move_id"], inner_rel))
        conflict = find_prior_ledger_conflict(row["source"], owned)
        if conflict:
            raise PlanBindingError(
                "앞선 트랜잭션 원장의 구성원을 그 destination 밖으로 옮기려 합니다: "
                "%s (%s)\n  원장 %s / %s — %s\n"
                "  옮기면 그 원장의 verify 가 MISSING 으로 실패합니다(검증 사슬 끊김). "
                "원장 연쇄(chained ledger) 없이는 이동하지 않습니다."
                % (row["move_id"], row["source"], conflict[0], conflict[1], conflict[2]))
        # cohort 를 transaction_group 으로 쓴다 -> 한 건 실패 시 cohort 전체 역순 rollback.
        yield row["source"], dest, [], cohort, kind, cohort, row


def load_frozen_scope(path, expected_sha256):
    """Stage 2-D1.1 frozen scope 를 읽고 SHA256 으로 결속한다."""
    if not os.path.isfile(path):
        raise PlanBindingError("frozen scope 가 없습니다: %s" % path)
    actual = _sha256(path)
    if expected_sha256 and actual != expected_sha256:
        raise PlanBindingError(
            "frozen scope SHA256 불일치 — 범위가 변경되었습니다.\n"
            "  expected %s\n  actual   %s" % (expected_sha256, actual))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh), actual


def _stage2d11_candidates(args, policy, paths):
    """Stage 2-D1.1: residual_scope.csv 의 지정 cohort row 만.

    D1 policy 와 다른 점: prior ledger 구성원이어도 **successor chain 을 만들 계획이
    있으면**(--d11-allow-prior-ledger-with-chain) 이동을 허용한다. 그 플래그가 없으면
    D1 과 똑같이 거부한다.
    """
    scope, scope_sha = load_frozen_scope(args.d11_scope, args.d11_scope_sha256)
    csv_rel = scope.get("scope_csv")
    csv_abs = os.path.join(paths.project_root, csv_rel.replace("/", os.sep))
    if scope.get("scope_csv_sha256") and _sha256(csv_abs) != scope["scope_csv_sha256"]:
        raise PlanBindingError("residual_scope.csv 가 frozen scope 이후 변경되었습니다")
    with open(csv_abs, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    ids = set(x.strip() for x in (args.move_ids or "").split(",") if x.strip())
    owned = prior_ledger_members(paths.project_root)
    allow_chain = bool(getattr(args, "d11_allow_prior_ledger_with_chain", False))
    # scope 의 cohort 는 scope 열이 아니라 인자로 지정한다 (scope 열은 진단용 분류다).
    SCOPE_TO_COHORT = {"D1D_ROLLBACK_SOURCE": "D11A_BLEND_BACKUPS",
                       "BLOCKED_REFERENCE": "D11B_REFERENCE_TRANSITION",
                       "BLOCKED_UNKNOWN": "D11C_LICENSE_RESOLUTION"}
    for row in rows:
        cohort = SCOPE_TO_COHORT.get(row["scope"])
        if cohort is None:
            continue
        if wanted and cohort not in wanted:
            continue
        if ids and row["move_id"] not in ids:
            continue
        src = row["source"]
        dst = args.d11_destination_map.get(row["move_id"]) if getattr(
            args, "d11_destination_map", None) else row["intended_destination"]
        if not dst or not dst.startswith("data/pallet/archive/"):
            raise PlanBindingError("목적지가 archive/ 밖이거나 비어 있습니다: %s -> %r"
                                   % (row["move_id"], dst))
        arch_root = os.path.normpath("data/pallet/archive")
        if os.path.commonpath([os.path.normpath(dst), arch_root]) != arch_root:
            raise PlanBindingError("목적지가 archive/ 를 벗어납니다: %s" % dst)
        if ".." in dst.split("/") or ".." in src.split("/"):
            raise PlanBindingError("경로에 .. 가 있습니다: %s" % row["move_id"])
        if int(row["current_runtime_test_refs"] or 0):
            raise PlanBindingError(
                "CURRENT 참조가 살아있습니다 — registry 전환이 선행돼야 합니다: %s (%s)"
                % (row["move_id"], row["reference_locations"]))
        if int(row["registry_ref_count"] or 0):
            raise PlanBindingError("registry 가 직접 가리키는 경로입니다: %s (%s)"
                                   % (row["move_id"], row["registry_keys"]))
        if "UNKNOWN" in (row.get("license_status") or "") and cohort != \
                "D11C_LICENSE_RESOLUTION":
            raise PlanBindingError("UNKNOWN license row: %s" % row["move_id"])
        conflict = find_prior_ledger_conflict(src, owned)
        if conflict and not allow_chain:
            raise PlanBindingError(
                "앞선 원장 구성원입니다 — successor chain 계획 없이 옮기지 않습니다: "
                "%s (%s / %s)" % (row["move_id"], conflict[0], conflict[1]))
        kind = row["entry_kind"] if row["entry_kind"] in ENTRY_KINDS else ENTRY_DIRECTORY
        yield src, dst, [], cohort, kind, cohort, dict(
            row, _scope_sha=scope_sha,
            _prior_ledger=conflict[0] if conflict else "",
            _prior_move_id=conflict[1] if conflict else "")


def _stage2d12_candidates(args, policy, paths):
    """Stage 2-D1.2: frozen_scope.csv 의 지정 cohort row.

    목적지·registry key 전환·provenance 판정이 이미 CSV 에 확정돼 있다.
    CSV 를 그대로 믿지 않고 여기서 다시 검사한다.
    """
    scope, scope_sha = load_frozen_scope(args.d12_scope, args.d12_scope_sha256)
    csv_rel = scope.get("scope_csv")
    csv_abs = os.path.join(paths.project_root, csv_rel.replace("/", os.sep))
    if scope.get("scope_csv_sha256") and _sha256(csv_abs) != scope["scope_csv_sha256"]:
        raise PlanBindingError("frozen_scope.csv 가 동결 이후 변경되었습니다")
    if scope.get("problems"):
        raise PlanBindingError("frozen scope 에 미해결 문제가 %d 건 있습니다: %s"
                               % (len(scope["problems"]), scope["problems"][:3]))
    if not scope.get("within_all_limits"):
        raise PlanBindingError("frozen scope 가 hash 예산 한도를 넘습니다")
    with open(csv_abs, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    ids = set(x.strip() for x in (args.move_ids or "").split(",") if x.strip())
    owned = prior_ledger_members(paths.project_root)
    allow_chain = bool(getattr(args, "d12_allow_prior_ledger_with_chain", False))
    all_sources = {r["source"] for r in rows}

    selected = []
    for row in rows:
        cohort = row["cohort"]
        if cohort not in D12_COHORTS:
            raise PlanBindingError("알 수 없는 cohort: %s" % cohort)
        if wanted and cohort not in wanted:
            continue
        if ids and row["move_id"] not in ids:
            continue
        selected.append(row)

    # cohort 임의 분할 금지 — 선택한 cohort 의 row 를 전부 가져와야 한다.
    for c in (wanted or set(r["cohort"] for r in selected)):
        want_n = sum(1 for r in rows if r["cohort"] == c)
        got_n = sum(1 for r in selected if r["cohort"] == c)
        if want_n != got_n and not ids:
            raise PlanBindingError(
                "cohort 를 임의 분할할 수 없습니다: %s (%d/%d)" % (c, got_n, want_n))

    for row in selected:
        cohort = row["cohort"]
        src = row["source"]
        dst = row["destination"]
        if not dst.startswith("data/pallet/archive/"):
            raise PlanBindingError("목적지가 archive/ 밖입니다: %s" % row["move_id"])
        arch_root = os.path.normpath("data/pallet/archive")
        if os.path.commonpath([os.path.normpath(dst), arch_root]) != arch_root:
            raise PlanBindingError("목적지가 archive/ 를 벗어납니다: %s" % dst)
        if ".." in dst.split("/") or ".." in src.split("/"):
            raise PlanBindingError("경로에 .. 가 있습니다: %s" % row["move_id"])
        if int(row["current_runtime_test_refs"] or 0):
            raise PlanBindingError(
                "CURRENT 참조가 살아있습니다: %s (%s)"
                % (row["move_id"], row["reference_locations"]))
        decision = (row.get("provenance_decision") or "").strip()
        if cohort == "D12C_PROVEN_NOAI_MOVE":
            if decision != "PROVEN_NOAI":
                raise PlanBindingError(
                    "D12C 는 PROVEN_NOAI 만 허용합니다: %s (%r)"
                    % (row["move_id"], decision))
            if not dst.startswith(D12_NOAI_DEST_ROOT + "/"):
                raise PlanBindingError(
                    "PROVEN_NOAI 목적지가 noai_baked 아래가 아닙니다: %s" % dst)
            for bad in D12_FORBIDDEN_NOAI_DEST:
                if bad in dst:
                    raise PlanBindingError(
                        "NoAI 자료를 금지 목적지로 보낼 수 없습니다: %s (%s)" % (dst, bad))
        if cohort == "D12B_REFERENCE_MOVE":
            key = (row.get("registry_key") or "").strip()
            if not key:
                raise PlanBindingError("registry key 없이 이동할 수 없습니다: %s"
                                       % row["move_id"])
            try:
                cur = _posix(os.path.relpath(paths.get(key), paths.project_root))
            except KeyError:
                raise PlanBindingError("registry key 가 없습니다: %s" % key)
            if cur != src:
                raise PlanBindingError(
                    "registry key 가 아직 source 를 가리켜야 합니다: %s (%s != %s)"
                    % (key, cur, src))
            if _posix(row.get("registry_final_value") or "") != dst:
                raise PlanBindingError("registry_final_value 가 목적지와 다릅니다: %s"
                                       % row["move_id"])
        kind = row["entry_kind"] if row["entry_kind"] in ENTRY_KINDS else ENTRY_DIRECTORY
        if kind == ENTRY_DIRECTORY:
            src_abs = os.path.join(paths.project_root, src.replace("/", os.sep))
            for inner in (archive_files_under(src_abs)
                          if os.path.isdir(src_abs) else []):
                if "%s/%s" % (src, inner) in all_sources:
                    raise PlanBindingError(
                        "dataset 안의 package 가 별도 row 로도 계획돼 있습니다: %s/%s"
                        % (src, inner))
        conflict = find_prior_ledger_conflict(src, owned)
        if conflict and not allow_chain:
            raise PlanBindingError(
                "앞선 원장 구성원입니다 — successor chain 계획 없이 옮기지 않습니다: "
                "%s (%s / %s)" % (row["move_id"], conflict[0], conflict[1]))
        yield src, dst, [], cohort, kind, cohort, dict(
            row, _scope_sha=scope_sha,
            _prior_ledger=conflict[0] if conflict else "",
            _prior_move_id=conflict[1] if conflict else "")


def is_policy_container(rel_path):
    """비어 있어도 유지해야 하는 최종 semantic container 인가.

    stale empty source 로 오분류해 옮기면 정책 구조 자체가 사라진다.
    """
    p = _posix(rel_path).rstrip("/")
    return p in D2_POLICY_CONTAINERS


def _stage2d2_candidates(args, policy, paths):
    """Stage 2-D2: frozen_final_plan.csv 의 지정 cohort row.

    CSV 를 그대로 믿지 않고 여기서 다시 검사한다 — 특히
    (a) 선택 집합이 계획과 정확히 같은지, (b) live reference 가 0 인지,
    (c) destination 이 승인된 final root 아래인지, (d) 라이선스 규칙.
    """
    scope, scope_sha = load_frozen_scope(args.d2_plan, args.d2_plan_sha256)
    csv_rel = scope.get("plan_csv")
    csv_abs = os.path.join(paths.project_root, csv_rel.replace("/", os.sep))
    if scope.get("plan_csv_sha256") and _sha256(csv_abs) != scope["plan_csv_sha256"]:
        raise PlanBindingError("frozen_final_plan.csv 가 동결 이후 변경되었습니다")
    for key in ("destination_policy_problems", "nested_source_conflicts",
                "duplicate_destinations"):
        if scope.get(key):
            raise PlanBindingError("frozen plan 에 %s 가 %d 건 있습니다: %s"
                                   % (key, len(scope[key]), scope[key][:3]))
    if not (scope.get("hash_budget") or {}).get("within"):
        raise PlanBindingError("frozen plan 이 hash 예산 한도를 넘습니다")
    with open(csv_abs, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != scope.get("selected_count"):
        raise PlanBindingError("plan row 수가 동결값과 다릅니다: %d != %s"
                               % (len(rows), scope.get("selected_count")))

    wanted = set(x.strip() for x in (args.cohort or "").split(",") if x.strip())
    ids = set(x.strip() for x in (args.move_ids or "").split(",") if x.strip())
    owned = prior_ledger_members(paths.project_root)
    all_sources = {r["source"] for r in rows}
    all_dests = [r["destination"] for r in rows]
    if len(set(all_dests)) != len(all_dests):
        raise PlanBindingError("plan 안에 중복 destination 이 있습니다")

    selected = []
    for row in rows:
        cohort = row["transaction_group"]
        if cohort not in D2_COHORTS:
            raise PlanBindingError("알 수 없는 cohort: %s" % cohort)
        if wanted and cohort not in wanted:
            continue
        if ids and row["d2_move_id"] not in ids:
            continue
        selected.append(row)

    # cohort 임의 분할 금지
    for c in (wanted or set(r["transaction_group"] for r in selected)):
        want_n = sum(1 for r in rows if r["transaction_group"] == c)
        got_n = sum(1 for r in selected if r["transaction_group"] == c)
        if want_n != got_n and not ids:
            raise PlanBindingError(
                "cohort 를 임의 분할할 수 없습니다: %s (%d/%d)" % (c, got_n, want_n))

    for row in selected:
        mid = row["d2_move_id"]
        src = row["source"]
        dst = row["destination"]
        if ".." in dst.split("/") or ".." in src.split("/"):
            raise PlanBindingError("경로에 .. 가 있습니다: %s" % mid)
        if not any(dst.startswith(r) for r in D2_ALLOWED_DEST_ROOTS):
            raise PlanBindingError("목적지가 승인된 final root 밖입니다: %s (%s)"
                                   % (mid, dst))
        arch_root = os.path.normpath("data/pallet/archive")
        if os.path.commonpath([os.path.normpath(dst), arch_root]) != arch_root:
            raise PlanBindingError("목적지가 archive/ 를 벗어납니다: %s" % dst)
        if int(row.get("current_runtime_refs") or 0) or \
                int(row.get("current_test_refs") or 0):
            raise PlanBindingError(
                "CURRENT runtime/test 참조가 살아있습니다: %s (%s/%s)"
                % (mid, row.get("current_runtime_refs"), row.get("current_test_refs")))
        if int(row.get("registry_refs") or 0):
            raise PlanBindingError("registry key 가 가리키는 항목입니다: %s" % mid)
        lic = (row.get("license_status") or "")
        if lic.startswith("HIGH") or "NoAI" in lic or "EULA" in lic:
            for bad in D2_FORBIDDEN_RESTRICTED_DEST:
                if bad in dst:
                    raise PlanBindingError(
                        "제한 라이선스 자료를 금지 목적지로 보낼 수 없습니다: %s (%s)"
                        % (dst, bad))
        if dst.endswith(".zip") and "/packages/" not in dst:
            raise PlanBindingError("package 는 packages/ 계열만 허용합니다: %s" % dst)
        if is_policy_container(src):
            raise PlanBindingError("최종 policy container 는 옮길 수 없습니다: %s" % src)
        # 중첩 source 금지 — 부모 row 와 그 내부 row 를 동시에 옮기지 않는다
        for other in all_sources:
            if other != src and other.startswith(src + "/"):
                raise PlanBindingError("중첩 source 충돌: %s ⊃ %s" % (src, other))
        kind = row["entry_kind"] if row["entry_kind"] in ENTRY_KINDS else ENTRY_DIRECTORY
        conflict = find_prior_ledger_conflict(src, owned)
        chain_ok = (row.get("successor_chain_required") or "").strip().lower() == "true"
        if conflict and not chain_ok:
            raise PlanBindingError(
                "앞선 원장 구성원입니다 — successor chain 계획 없이 옮기지 않습니다: "
                "%s (%s / %s)" % (mid, conflict[0], conflict[1]))
        yield src, dst, [], row["transaction_group"], kind, row["transaction_group"], \
            dict(row, _scope_sha=scope_sha,
                 _prior_ledger=conflict[0] if conflict else "",
                 _prior_move_id=conflict[1] if conflict else "")


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
    plan_sha_actual = None
    if policy_name == POLICY_STAGE2D1:
        if not args.d1_plan:
            print("정책 %s 는 --d1-plan <csv> 를 요구합니다." % policy_name,
                  file=sys.stderr)
            return 2
        try:
            _, plan_sha_actual = load_frozen_plan(args.d1_plan, args.d1_plan_sha256)
        except PlanBindingError as exc:
            print("계획 결속 실패: %s" % exc, file=sys.stderr)
            return 2
        gen = lambda a, p: _stage2d1_candidates(a, p, paths)   # noqa: E731
    elif policy_name == POLICY_STAGE2D11:
        if not args.d11_scope:
            print("정책 %s 는 --d11-scope <json> 을 요구합니다." % policy_name,
                  file=sys.stderr)
            return 2
        try:
            _, plan_sha_actual = load_frozen_scope(args.d11_scope, args.d11_scope_sha256)
        except PlanBindingError as exc:
            print("범위 결속 실패: %s" % exc, file=sys.stderr)
            return 2
        gen = lambda a, p: _stage2d11_candidates(a, p, paths)   # noqa: E731
    elif policy_name == POLICY_STAGE2D12:
        if not args.d12_scope:
            print("정책 %s 는 --d12-scope <json> 을 요구합니다." % policy_name,
                  file=sys.stderr)
            return 2
        try:
            _, plan_sha_actual = load_frozen_scope(args.d12_scope, args.d12_scope_sha256)
        except PlanBindingError as exc:
            print("범위 결속 실패: %s" % exc, file=sys.stderr)
            return 2
        gen = lambda a, p: _stage2d12_candidates(a, p, paths)   # noqa: E731
    elif policy_name == POLICY_STAGE2D2:
        if not args.d2_plan:
            print("정책 %s 는 --d2-plan <json> 을 요구합니다." % policy_name,
                  file=sys.stderr)
            return 2
        try:
            _, plan_sha_actual = load_frozen_scope(args.d2_plan, args.d2_plan_sha256)
        except PlanBindingError as exc:
            print("계획 결속 실패: %s" % exc, file=sys.stderr)
            return 2
        gen = lambda a, p: _stage2d2_candidates(a, p, paths)    # noqa: E731
    elif policy_name == POLICY_STAGE2C2:
        gen = lambda a, p: ((s, d, b, c, k, g, None)           # noqa: E731
                            for s, d, b, c, k, g in _stage2c2_candidates(a, p, paths))
    elif policy["allowlist"]:
        gen = lambda a, p: ((s, d, b, c, ENTRY_DIRECTORY, c, None)   # noqa: E731
                            for s, d, b, c in _stage2b_candidates(a, p))
    else:
        gen = lambda a, p: ((s, d, b, c, ENTRY_DIRECTORY, c, None)   # noqa: E731
                            for s, d, b, c in _stage2a_candidates(a, p))

    budget = None
    if policy_name in (POLICY_STAGE2D1, POLICY_STAGE2D11) \
            and args.max_hash_read_bytes is not None:
        budget = HashBudget(args.max_hash_read_bytes,
                            label="plan/%s" % (args.cohort or "all"))

    planned, skipped = [], []
    running_total = 0
    try:
        candidates = list(gen(args, policy))
    except PlanBindingError as exc:
        print("계획 거부: %s" % exc, file=sys.stderr)
        return 2
    for src_rel, dst_rel, blocking, cohort, entry_kind, group, plan_row in candidates:
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

        try:
            if entry_kind == ENTRY_FILE:
                snap = snapshot_file(src_abs, hash_mode=args.hash_mode, budget=budget)
            else:
                dup_sizes = (duplicate_size_set(src_abs)
                             if args.hash_mode == HASH_MODE_SELECTIVE else set())
                snap = snapshot(src_abs, dup_sizes, hash_mode=args.hash_mode,
                                budget=budget)
        except HashBudgetExceeded as exc:
            print("해시 예산 초과로 계획을 중단합니다: %s" % exc, file=sys.stderr)
            print("  selective 로 강등하지 않습니다. --max-hash-read-gib 를 조정하거나 "
                  "cohort 를 나누십시오.", file=sys.stderr)
            return 2
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
        if policy_name == POLICY_STAGE2D1:
            # §3 이 요구하는 Stage 2-D1 전용 필드. 기존 스키마 필드는 건드리지 않고 덧붙인다.
            planned[-1].update({
                "schema_version": D1_SCHEMA_VERSION,
                "plan_path": _posix(os.path.relpath(args.d1_plan, paths.project_root)),
                "plan_sha256": plan_sha_actual,
                "move_id": plan_row["move_id"],          # 계획의 move_id 를 그대로 쓴다
                "classification": plan_row["classification"],
                "evidence_level": plan_row["evidence_level"],
                "license_status": plan_row["license_status"],
                "exclusion_status": plan_row["exclusion_status"],
                "source_file_count": snap["file_count"],
                "source_total_bytes": snap["total_bytes"],
                "source_sha256": snap["sha256"],
                "hash_read_bytes_pre": snap.get("hash_read_bytes", 0),
                "hash_read_bytes_post": None,            # verify 에서 채운다
                "applied_at": None,
                "verified_at": None,
                "rollback_source": src_rel,              # 되돌릴 때의 목적지
                "rollback_destination": dst_rel,         # 되돌릴 때의 출발지
                "plan_row_status": plan_row["status"],
            })
        if policy_name == POLICY_STAGE2D12:
            # §4 가 요구한 Stage 2-D1.2 결속 필드
            planned[-1].update({
                "schema_version": D12_SCHEMA_VERSION,
                "frozen_scope_path": _posix(os.path.relpath(args.d12_scope,
                                                            paths.project_root)),
                "frozen_scope_sha256": plan_row["_scope_sha"],
                "move_id": plan_row["move_id"],
                "classification": plan_row.get("license_status", ""),
                "registry_key": plan_row.get("registry_key", ""),
                "registry_value_before": plan_row.get("registry_current_value", ""),
                "registry_value_after": plan_row.get("registry_final_value", ""),
                "registry_transition_applied": False,
                "provenance_decision": plan_row.get("provenance_decision", ""),
                "provenance_evidence": plan_row.get("noai_evidence", ""),
                "license_status": plan_row.get("license_status", ""),
                "exclusion_before": plan_row.get("exclusion_before", ""),
                "exclusion_after": "",
                "source_file_count": snap["file_count"],
                "source_total_bytes": snap["total_bytes"],
                "source_sha256": snap["sha256"],
                "hash_read_bytes_pre": snap.get("hash_read_bytes", 0),
                "hash_read_bytes_post": None,
                "applied_at": None, "verified_at": None,
                "rollback_source": src_rel, "rollback_destination": dst_rel,
                "prior_ledger_members": plan_row.get("_prior_ledger", ""),
                "prior_manifest_path": plan_row.get("_prior_ledger", ""),
                "prior_manifest_sha256": (
                    _sha256(os.path.join(paths.project_root,
                                         plan_row["_prior_ledger"].replace("/", os.sep)))
                    if plan_row.get("_prior_ledger") else ""),
                "prior_move_id": plan_row.get("_prior_move_id", ""),
                "successor_chain_required": bool(plan_row.get("_prior_ledger")),
                "hash_budget_gib": getattr(args, "max_hash_read_gib", None),
            })
        elif policy_name == POLICY_STAGE2D2:
            # §7 이 요구한 Stage 2-D2 결속 필드
            planned[-1].update({
                "schema_version": D2_SCHEMA_VERSION,
                "frozen_plan_path": _posix(os.path.relpath(args.d2_plan,
                                                           paths.project_root)),
                "frozen_plan_sha256": plan_row["_scope_sha"],
                "d2_move_id": plan_row["d2_move_id"],
                "move_id": plan_row["d2_move_id"],
                "classification": plan_row.get("classification", ""),
                "license_status": plan_row.get("license_status", ""),
                "exclusion_before": plan_row.get("exclusion_required", ""),
                "exclusion_after": "",
                "plan_origin": plan_row.get("plan_origin", ""),
                "destination_policy_root": plan_row.get("destination_policy_root", ""),
                "empty_before": snap["file_count"] == 0,
                "empty_after": None,                     # verify 에서 채운다
                "source_file_count": snap["file_count"],
                "source_total_bytes": snap["total_bytes"],
                "source_sha256": snap["sha256"],
                "hash_read_bytes_pre": snap.get("hash_read_bytes", 0),
                "hash_read_bytes_post": None,
                "applied_at": None, "verified_at": None,
                "rollback_source": src_rel, "rollback_destination": dst_rel,
                "prior_ledger_members": plan_row.get("_prior_ledger", ""),
                "prior_move_id": plan_row.get("_prior_move_id", ""),
                "successor_chain_required": bool(plan_row.get("_prior_ledger")),
                "hash_budget_gib": getattr(args, "max_hash_read_gib", None),
            })
        elif policy_name == POLICY_STAGE2D11:
            # §5 가 요구한 Stage 2-D1.1 전용 필드
            planned[-1].update({
                "schema_version": D11_SCHEMA_VERSION,
                "scope_path": _posix(os.path.relpath(args.d11_scope,
                                                     paths.project_root)),
                "scope_sha256": plan_row["_scope_sha"],
                "move_id": plan_row["move_id"],
                "classification": plan_row.get("d0_classification", ""),
                "evidence_level": plan_row.get("prior_ledger_sha256", "") and
                                  "prior ledger SHA256 identity" or "n/a",
                "license_status": plan_row.get("license_status", ""),
                "license_decision": getattr(args, "d11_license_decision", "") or "",
                "provenance_evidence": getattr(args, "d11_provenance_evidence", "") or "",
                "source_file_count": snap["file_count"],
                "source_total_bytes": snap["total_bytes"],
                "source_sha256": snap["sha256"],
                "hash_read_bytes_pre": snap.get("hash_read_bytes", 0),
                "hash_read_bytes_post": None,
                "applied_at": None, "verified_at": None,
                "rollback_source": src_rel, "rollback_destination": dst_rel,
                "prior_ledger_members": plan_row.get("_prior_ledger", ""),
                "prior_manifest_path": plan_row.get("_prior_ledger", ""),
                "prior_manifest_sha256": (
                    _sha256(os.path.join(paths.project_root,
                                         plan_row["_prior_ledger"].replace("/", os.sep)))
                    if plan_row.get("_prior_ledger") else ""),
                "prior_move_id": plan_row.get("_prior_move_id", ""),
                "prior_relative_path": plan_row.get("prior_relative_path", ""),
                "prior_ledger_sha256": plan_row.get("prior_ledger_sha256", ""),
                "successor_chain_required": bool(plan_row.get("_prior_ledger")),
                "registry_keys_before": plan_row.get("registry_keys", ""),
                "registry_keys_after": getattr(args, "d11_registry_keys_after", "") or "",
                "exclusion_before": plan_row.get("exclusion_status", ""),
                "exclusion_after": getattr(args, "d11_exclusion_after", "") or "",
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
    if budget is not None:
        print("hash read: %d bytes (%.2f GiB) / 한도 %.2f GiB"
              % (budget.read_bytes, budget.read_bytes / 1024 ** 3,
                 budget.limit / 1024 ** 3))
    if plan_sha_actual:
        print("plan sha : %s" % plan_sha_actual)
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
# ---------------------------------------------------------------------------
# destination additions (Stage 2-D0.1)
#
# 이동 후 destination 폴더에서 작업이 계속되면(예: Stage 2-C2 가 그 안에 새 씬을 만듦)
# count/bytes/relpath 는 당연히 달라진다. 원장이 지켜야 하는 불변식은
#   "옮긴 파일이 하나도 없어지지 않고 바이트가 그대로다"
# 이지 "폴더가 얼어 있다" 가 아니다.
#
# 그러나 "없어진 게 없으면 추가는 아무거나 허용" 은 검증력이 없다 — 나중에 오염된 파일이
# 섞여도 통과한다. 그래서 **예상한 파일만 exact 로 허용**한다(경로+크기+SHA256+역할).
# ---------------------------------------------------------------------------
class ExpectedAdditionsError(Exception):
    """expected-additions 명세 자체가 성립하지 않는 경우 (verify 를 진행하지 않는다)."""


def load_expected_additions(path, manifest_path, rows):
    """expected-additions JSON 을 읽고 manifest 와 결속되는지 검사한다.

    반환: {destination(str) -> {relative_path -> {"size","sha256","role"}}}
    """
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)

    want_manifest_sha = spec.get("manifest_sha256")
    actual_manifest_sha = _sha256(manifest_path)
    if not want_manifest_sha:
        raise ExpectedAdditionsError("manifest_sha256 가 없습니다 — 어느 트랜잭션의 명세인지 "
                                     "결속되지 않으면 다른 원장에 잘못 적용될 수 있습니다")
    if want_manifest_sha != actual_manifest_sha:
        raise ExpectedAdditionsError(
            "manifest_sha256 불일치 — 이 명세는 다른 transaction 을 가리킵니다.\n"
            "  spec   %s\n  actual %s" % (want_manifest_sha, actual_manifest_sha))

    moved_dests = {row["destination"] for row in rows}
    default_dest = spec.get("destination_root")
    out = {}
    entries = spec.get("expected_additions") or []
    if not isinstance(entries, list):
        raise ExpectedAdditionsError("expected_additions 는 리스트여야 합니다")
    for e in entries:
        dest = e.get("destination") or default_dest
        if not dest:
            raise ExpectedAdditionsError("destination_root 또는 entry.destination 이 필요합니다")
        dest = _posix(dest)
        if dest not in moved_dests:
            raise ExpectedAdditionsError(
                "destination 이 이 manifest 의 이동 대상이 아닙니다: %s\n  허용: %s"
                % (dest, sorted(moved_dests)))
        rel = _posix(str(e.get("relative_path") or ""))
        if not rel:
            raise ExpectedAdditionsError("relative_path 가 비어 있습니다")
        if os.path.isabs(rel) or rel.startswith("/") or ".." in rel.split("/"):
            raise ExpectedAdditionsError("relative_path 가 destination 밖으로 나갑니다: %s" % rel)
        if e.get("size") is None or not e.get("sha256"):
            raise ExpectedAdditionsError("expected addition 에 size/sha256 이 필요합니다: %s" % rel)
        bucket = out.setdefault(dest, {})
        if rel in bucket:
            raise ExpectedAdditionsError("expected addition 이 중복됩니다: %s" % rel)
        bucket[rel] = {"size": int(e["size"]), "sha256": str(e["sha256"]),
                       "role": e.get("role", "")}
    return out


# ---------------------------------------------------------------------------
# successor ledger chain (Stage 2-D1.1)
#
# Stage 2-D1 이 드러낸 문제: 앞선 원장(C2C)이 옮긴 파일을 그 destination 밖으로 다시
# 옮기면 앞선 원장의 verify 가 MISSING 으로 실패한다. 데이터는 후속 원장이 기록하고
# 있으므로 안전한데도 검증 사슬이 끊긴다.
#
# "없어진 건 그냥 허용" 이나 "expected removal 목록" 으로는 통과시키지 않는다 —
# 그러면 진짜 유실도 통과한다. 대신 **파일 단위 SHA256 identity 로 두 원장을 잇는다**:
#   prior ledger 가 기록한 (relative_path, size, sha256)
#     == successor ledger 의 source identity
#     == successor destination 의 현재 실측 identity
# 세 값이 모두 같을 때만 "없어진 게 아니라 이어받았다" 고 인정한다.
#
# 기존 manifest 는 한 바이트도 고치지 않는다 (immutable).
# ---------------------------------------------------------------------------
class SuccessorChainError(Exception):
    """chain 명세 자체가 성립하지 않는 경우 (verify 를 진행하지 않는다)."""


CHAIN_REQUIRED_MAPPING_FIELDS = (
    "prior_move_id", "prior_relative_path", "prior_destination_path", "size", "sha256",
    "successor_manifest", "successor_move_id", "successor_source_path",
    "successor_destination_path",
)


def load_successor_chain(path, manifest_path, rows, project_root):
    """successor chain JSON 을 읽고 15개 조건을 검사한다.

    반환: {(prior_destination_path, prior_relative_path) -> mapping dict}
    이 키가 "prior ledger 에서 없어졌지만 이어받은 것으로 인정되는 파일" 이다.
    """
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)

    prior = spec.get("prior_manifest") or {}
    # (1) prior manifest SHA256 결속
    want = prior.get("sha256")
    actual = _sha256(manifest_path)
    if not want:
        raise SuccessorChainError("prior_manifest.sha256 가 없습니다 — 어느 원장의 "
                                  "chain 인지 결속되지 않습니다")
    if want != actual:
        raise SuccessorChainError(
            "prior_manifest.sha256 불일치 — 이 chain 은 다른 원장을 가리킵니다.\n"
            "  spec   %s\n  actual %s" % (want, actual))
    if prior.get("path"):
        spec_prior = _posix(prior["path"])
        given = _posix(os.path.relpath(manifest_path, project_root))
        if os.path.normcase(spec_prior) != os.path.normcase(given):
            raise SuccessorChainError("prior_manifest.path 가 검증 대상과 다릅니다:\n"
                                      "  spec %s\n  given %s" % (spec_prior, given))

    # (5) successor manifest SHA256 결속 + (14) cycle 없음
    succ_specs = spec.get("successor_manifests") or []
    if not succ_specs:
        raise SuccessorChainError("successor_manifests 가 비어 있습니다")
    succ_rows = {}
    prior_real = os.path.normcase(os.path.realpath(manifest_path))
    for s in succ_specs:
        rel = _posix(str(s.get("path") or ""))
        if not rel:
            raise SuccessorChainError("successor_manifests[].path 가 필요합니다")
        ap = os.path.join(project_root, rel.replace("/", os.sep))
        if not os.path.isfile(ap):
            raise SuccessorChainError("successor manifest 가 없습니다: %s" % rel)
        if os.path.normcase(os.path.realpath(ap)) == prior_real:
            raise SuccessorChainError(
                "ledger cycle — successor 가 prior 와 같은 원장입니다: %s" % rel)
        got = _sha256(ap)
        if s.get("sha256") and s["sha256"] != got:
            raise SuccessorChainError(
                "successor manifest sha256 불일치: %s\n  spec   %s\n  actual %s"
                % (rel, s["sha256"], got))
        succ_rows[rel] = {r["move_id"]: r for r in _read_manifest(ap)}

    prior_rows = {r["move_id"]: r for r in rows}
    out = {}
    seen_successor = {}
    for m in spec.get("mappings") or []:
        for f in CHAIN_REQUIRED_MAPPING_FIELDS:
            if m.get(f) in (None, ""):
                raise SuccessorChainError("mapping 에 %s 가 필요합니다: %r" % (f, m))
        prel = _posix(str(m["prior_relative_path"]))
        pdest = _posix(str(m["prior_destination_path"]))
        # (13) path escape 없음
        for label, val in (("prior_relative_path", prel),
                           ("successor_source_path", _posix(m["successor_source_path"])),
                           ("successor_destination_path",
                            _posix(m["successor_destination_path"]))):
            if os.path.isabs(val) or val.startswith("/") or ".." in val.split("/"):
                raise SuccessorChainError("%s 가 경로를 탈출합니다: %s" % (label, val))

        # (2) prior manifest 에 그 relative path 가 실제 존재 + (3) size/sha 일치
        prow = prior_rows.get(m["prior_move_id"])
        if prow is None:
            raise SuccessorChainError("prior manifest 에 move_id 가 없습니다: %s"
                                      % m["prior_move_id"])
        if _posix(prow["destination"]) != pdest:
            raise SuccessorChainError(
                "prior_destination_path 가 원장과 다릅니다: %s != %s"
                % (pdest, prow["destination"]))
        if prel not in (prow.get("relative_files") or []):
            raise SuccessorChainError(
                "prior 원장이 그 파일을 옮긴 기록이 없습니다: %s / %s"
                % (m["prior_move_id"], prel))
        pre = prow.get("pre_hash_manifest") or {}
        want_sha = (pre.get("sha256") or {}).get(prel)
        want_size = (pre.get("sizes") or {}).get(prel)
        if want_sha is None or want_size is None:
            raise SuccessorChainError(
                "prior 원장에 그 파일의 size/sha256 이 없습니다: %s" % prel)
        if str(want_size) != str(m["size"]):
            raise SuccessorChainError("prior size 불일치: %s (원장 %s != chain %s)"
                                      % (prel, want_size, m["size"]))
        if want_sha != m["sha256"]:
            raise SuccessorChainError("prior sha256 불일치: %s" % prel)

        # (4) successor source == prior destination 안의 그 파일
        expect_src = "%s/%s" % (pdest, prel)
        if _posix(m["successor_source_path"]) != expect_src:
            raise SuccessorChainError(
                "successor_source_path 가 prior destination 과 다릅니다:\n"
                "  expect %s\n  got    %s" % (expect_src, m["successor_source_path"]))

        # (6)(7) successor row 가 VERIFIED 이고 pre-hash 가 prior hash 와 일치
        srel = _posix(str(m["successor_manifest"]))
        if srel not in succ_rows:
            raise SuccessorChainError(
                "mapping 이 chain 에 없는 successor manifest 를 가리킵니다: %s" % srel)
        srow = succ_rows[srel].get(m["successor_move_id"])
        if srow is None:
            raise SuccessorChainError("successor manifest 에 move_id 가 없습니다: %s"
                                      % m["successor_move_id"])
        if srow.get("status") != "MOVED" or not srow.get("verified_at"):
            raise SuccessorChainError(
                "successor row 가 VERIFIED 가 아닙니다: %s (status=%s verified_at=%s)"
                % (m["successor_move_id"], srow.get("status"), srow.get("verified_at")))
        if _posix(srow["source"]) != _posix(m["successor_source_path"]):
            raise SuccessorChainError(
                "successor 원장의 source 가 mapping 과 다릅니다: %s != %s"
                % (srow["source"], m["successor_source_path"]))
        if _posix(srow["destination"]) != _posix(m["successor_destination_path"]):
            raise SuccessorChainError(
                "successor 원장의 destination 이 mapping 과 다릅니다: %s != %s"
                % (srow["destination"], m["successor_destination_path"]))
        s_pre = (srow.get("pre_hash_manifest") or {}).get("sha256") or {}
        # file entry 의 상대키는 basename 하나다
        s_leaf = _posix(srow["destination"]).rsplit("/", 1)[-1]
        s_sha = s_pre.get(s_leaf)
        if s_sha is None and len(s_pre) == 1:
            s_sha = next(iter(s_pre.values()))
        if s_sha != m["sha256"]:
            raise SuccessorChainError(
                "successor pre-hash 가 prior hash 와 다릅니다: %s" % prel)

        # (8)(9)(10) successor destination 실측
        dabs = os.path.join(project_root,
                            _posix(m["successor_destination_path"]).replace("/", os.sep))
        if not os.path.isfile(dabs):
            raise SuccessorChainError("successor destination 이 없습니다: %s"
                                      % m["successor_destination_path"])
        if os.path.getsize(dabs) != int(m["size"]):
            raise SuccessorChainError("successor destination size 불일치: %s"
                                      % m["successor_destination_path"])
        if _sha256(dabs) != m["sha256"]:
            raise SuccessorChainError("successor destination sha256 불일치: %s"
                                      % m["successor_destination_path"])

        # (11) 같은 prior file 에 mapping 정확히 1개
        key = (pdest, prel)
        if key in out:
            raise SuccessorChainError("같은 prior file 에 mapping 이 2개 이상입니다: %s"
                                      % prel)
        # (12) 같은 successor file 이 여러 prior file 을 대표하지 않음
        skey = _posix(m["successor_destination_path"])
        if skey in seen_successor:
            raise SuccessorChainError(
                "같은 successor file 이 여러 prior file 을 대표합니다: %s (%s, %s)"
                % (skey, seen_successor[skey], prel))
        seen_successor[skey] = prel

        # 현재 prior destination 에 아직 있는 파일은 chain 에 넣을 수 없다
        still = os.path.join(project_root, ("%s/%s" % (pdest, prel)).replace("/", os.sep))
        if os.path.exists(still):
            raise SuccessorChainError(
                "prior destination 에 아직 존재하는 파일을 chain 으로 우회시킬 수 없습니다: %s"
                % expect_src)

        out[key] = dict(m)
    if not out:
        raise SuccessorChainError("mappings 가 비어 있습니다 — chain 이 아무것도 잇지 않습니다")
    return out


def check_expected_additions(dest_rel, dest_abs, extra, allow_map):
    """extra 파일 집합을 allowlist 와 exact 대조. (failures, accepted) 를 돌려준다."""
    expected = allow_map.get(dest_rel, {})
    failures, accepted = [], []
    for rel in extra:
        want = expected.get(rel)
        if want is None:
            failures.append("UNEXPECTED_ADDITION %s" % rel)
            continue
        ap = os.path.join(dest_abs, rel.replace("/", os.sep))
        size = os.path.getsize(ap)
        if size != want["size"]:
            failures.append("ADDITION_SIZE %s (%d != %d)" % (rel, size, want["size"]))
            continue
        got = _sha256(ap)
        if got != want["sha256"]:
            failures.append("ADDITION_SHA256 %s" % rel)
            continue
        accepted.append({"relative_path": rel, "size": size, "sha256": got,
                         "role": want["role"]})
    for rel in expected:
        if rel not in set(extra):
            failures.append("EXPECTED_ADDITION_MISSING %s" % rel)
    return failures, accepted


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
            if row.get("schema_version") in (D1_SCHEMA_VERSION, D11_SCHEMA_VERSION,
                                            D12_SCHEMA_VERSION):
                row["applied_at"] = row["completed_at"]
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


def _finish_d1_rows(manifest_path, rows, touched):
    """D1 row 에 채운 verified_at / hash_read_bytes_post 를 원장에 반영한다.

    D1 이 아닌 원장은 건드리지 않는다 (Stage 2-A/B/C2 원장 rewrite 금지).
    """
    if touched:
        _write_manifest(manifest_path, rows)


def cmd_verify(args, paths):
    rows = _read_manifest(args.manifest)
    failures = []
    added_notes = []
    touched = False
    post_budget = None
    if getattr(args, "max_hash_read_bytes", None) is not None and any(
            r.get("schema_version") in (D1_SCHEMA_VERSION, D11_SCHEMA_VERSION,
                                        D12_SCHEMA_VERSION)
            for r in rows):
        post_budget = HashBudget(args.max_hash_read_bytes, label="verify")
    # destination additions 정책. 기본은 엄격(둘 다 없음 -> extra 는 곧 실패).
    expected_map = None
    allow_any = bool(getattr(args, "allow_any_destination_additions", False))
    spec_path = getattr(args, "expected_destination_additions", None)
    if spec_path:
        try:
            expected_map = load_expected_additions(spec_path, args.manifest, rows)
        except ExpectedAdditionsError as exc:
            print("expected-additions 명세 오류: %s" % exc, file=sys.stderr)
            return 2
    if allow_any:
        print("경고: --allow-any-destination-additions 는 destination 의 모든 추가 파일을 "
              "검증 없이 통과시킵니다. 실원장 검증에는 "
              "--expected-destination-additions 를 쓰십시오.", file=sys.stderr)
    # successor ledger chain: prior 에서 없어진 파일을 후속 원장이 SHA256 identity 로
    # 이어받았음을 증명할 때만 missing 에서 제외한다.
    chain_map = None
    chain_paths = getattr(args, "successor_ledger_chain", None) or []
    if isinstance(chain_paths, str):          # 하위호환 (단일 값)
        chain_paths = [chain_paths]
    chain_used = []
    if chain_paths:
        # 여러 chain 을 병합한다. 이관이 여러 단계·여러 후속 원장으로 갈라지면 chain 도
        # 여러 개가 되고, prior 원장 하나를 검증하려면 그것들을 **모두** 봐야 한다.
        # 같은 prior file 을 두 chain 이 각각 주장하면 모순이므로 실패시킨다.
        chain_map = {}
        for cp in chain_paths:
            try:
                part = load_successor_chain(cp, args.manifest, rows,
                                            paths.project_root)
            except SuccessorChainError as exc:
                print("successor chain 오류 (%s): %s" % (cp, exc), file=sys.stderr)
                return 2
            dup = set(part) & set(chain_map)
            if dup:
                print("successor chain 충돌 — 같은 prior file 을 여러 chain 이 주장합니다: "
                      "%s" % sorted(dup)[:3], file=sys.stderr)
                return 2
            chain_map.update(part)
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
        # D1 계열 스키마(= 전수 hash · stat_only post · verified_at 1회 기록).
        # ★ 새 stage 를 추가할 때 여기 넣는 것을 잊으면 verify 가 통과했다고 보고하면서
        #   원장에 verified_at 을 남기지 않는다 (Stage 2-D2 에서 실제로 겪음).
        is_d1 = row.get("schema_version") in (D1_SCHEMA_VERSION, D11_SCHEMA_VERSION,
                                              D12_SCHEMA_VERSION, D2_SCHEMA_VERSION)
        if kind == ENTRY_FILE:
            if not os.path.isfile(dst):
                failures.append((row["move_id"], "DEST_FILE_MISSING %s" % row["destination"]))
                continue
            # D1 은 아래 pre["sha256"] 루프가 같은 파일을 다시 해시한다 -> 여기서는 stat 만.
            post = ({"file_count": 1, "total_bytes": os.path.getsize(dst),
                     "files": {os.path.basename(dst): os.path.getsize(dst)}}
                    if is_d1 else snapshot_file(dst, hash_mode=HASH_MODE_ALL))
            # 파일 entry 는 destination 자체가 파일이므로 해시 대조 기준 디렉토리를 바꾼다.
            dst_dir = os.path.dirname(dst)
        else:
            post = stat_only_snapshot(dst) if is_d1 else snapshot(dst, set())
            dst_dir = dst
        # 옮긴 파일이 하나도 없어지지 않았는지(missing)와, destination 에 나중에 추가된
        # 파일(extra)을 분리한다. extra 는 **exact allowlist 로만** 허용한다 — 경로·크기·
        # SHA256 이 명세와 같아야 하고, 명세에 없는 extra 는 실패다.
        missing = sorted(set(row["relative_files"]) - set(post["files"]))
        extra = sorted(set(post["files"]) - set(row["relative_files"]))
        chained = []
        if missing and chain_map is not None:
            still_missing = []
            for rel in missing:
                key = (_posix(row["destination"]), rel)
                if key in chain_map:
                    chained.append(rel)
                    chain_used.append((row["move_id"], rel, chain_map[key]))
                else:
                    still_missing.append(rel)
            missing = still_missing
        if missing:
            failures.append((row["move_id"], "RELPATH_SET_MISSING %s" % missing[:5]))

        addition_ok = False
        if extra:
            if expected_map is not None:
                fails, accepted = check_expected_additions(row["destination"], dst_dir, extra,
                                                           expected_map)
                for msg in fails:
                    failures.append((row["move_id"], msg))
                if not fails:
                    addition_ok = True
                    added_notes.append((row["move_id"], accepted))
            elif allow_any:
                addition_ok = True
                added_notes.append((row["move_id"],
                                    [{"relative_path": r, "size": None, "sha256": None,
                                      "role": "(unverified — broad mode)"} for r in extra]))
            else:
                failures.append((row["move_id"], "RELPATH_SET extra=%s" % extra[:5]))
        elif expected_map is not None and expected_map.get(row["destination"]):
            for rel in expected_map[row["destination"]]:
                failures.append((row["move_id"], "EXPECTED_ADDITION_MISSING %s" % rel))

        # chain 으로 이어받은 파일은 count/bytes 기대치에서 빼고 비교한다.
        exp_count = row["file_count"] - len(chained)
        exp_bytes = row["total_bytes"] - sum(
            int(row["pre_hash_manifest"]["sizes"][r]) for r in chained)
        if post["file_count"] != exp_count and not addition_ok:
            failures.append((row["move_id"], "FILE_COUNT %d != %d"
                             % (post["file_count"], exp_count)))
        if post["total_bytes"] != exp_bytes and not addition_ok:
            failures.append((row["move_id"], "TOTAL_BYTES %d != %d"
                             % (post["total_bytes"], exp_bytes)))
        if is_d1 and post_budget is not None:
            post_budget.precheck(row.get("source_total_bytes") or row["total_bytes"])
        row_post_read = 0
        chained_set = set(chained)
        for rel, want in pre["sha256"].items():
            if rel in chained_set:
                continue          # 후속 원장이 이어받았고 identity 를 이미 검증했다
            abs_path = os.path.join(dst_dir, rel.replace("/", os.sep))
            if not os.path.isfile(abs_path):
                failures.append((row["move_id"], "MISSING %s" % rel))
                continue
            try:
                got = _sha256(abs_path, budget=post_budget if is_d1 else None)
            except HashBudgetExceeded as exc:
                print("post-hash 예산 초과로 verify 를 중단합니다: %s" % exc,
                      file=sys.stderr)
                failures.append((row["move_id"], "HASH_BUDGET_EXCEEDED"))
                _finish_d1_rows(args.manifest, rows, touched)
                print("failures       : %d" % len(failures))
                return 1
            row_post_read += os.path.getsize(abs_path)
            checked_hashes += 1
            if got != want:
                failures.append((row["move_id"], "SHA256 %s" % rel))
        if is_d1 and not row.get("verified_at"):
            # **첫 검증에만** 기록한다. 재검증이 원장을 다시 쓰면 원장 SHA256 이 바뀌고,
            # 그 SHA 에 결속된 successor chain 이 깨진다 (Stage 2-D1.1 에서 실제 발생).
            # 원장은 "언제 처음 검증됐는가"를 기록하는 immutable 기록이다.
            row["hash_read_bytes_post"] = row_post_read
            row["verified_at"] = _now()
            touched = True
        # 라이선스 파일은 자산과 함께 살아 있어야 한다. 하나라도 빠지면 실패.
        for rel in row.get("license_files", []):
            if rel in chained_set:
                continue
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
    if added_notes:
        mode = "exact allowlist" if expected_map is not None else "BROAD (unverified)"
        print("dest additions : %d move(s), %s"
              % (len(added_notes), mode))
        for move_id, accepted in added_notes:
            for a in accepted:
                print("   %s  +%-52s %s  role=%s"
                      % (move_id, a["relative_path"],
                         (a["sha256"] or "")[:16] or "(미검증)", a["role"]))
    if chain_map is not None:
        print("successor chain: %d file(s) from %d chain(s) / 인정된 이관 %d"
              % (len(chain_map), len(chain_paths), len(chain_used)))
        for move_id, rel, m in chain_used:
            print("   %s  ~>%-52s %s  role=%s"
                  % (move_id, rel, m["sha256"][:16], m.get("role", "")))
        unused = set(chain_map) - {(_posix(r["destination"]), rel)
                                   for r in rows if r["status"] == "MOVED"
                                   for rel in (r.get("relative_files") or [])}
        if unused:
            failures.append(("(chain)", "MAPPING_NOT_APPLICABLE %s"
                             % sorted(unused)[:3]))
    if post_budget is not None:
        print("post hash read : %d bytes (%.2f GiB) / 한도 %.2f GiB"
              % (post_budget.read_bytes, post_budget.read_bytes / 1024 ** 3,
                 post_budget.limit / 1024 ** 3))
    _finish_d1_rows(args.manifest, rows, touched)
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
    ap.add_argument("--d1-plan", default=None, metavar="CSV",
                    help="stage2d1 전용: 동결된 이동계획 CSV "
                         "(reports/data_pallet_cleanup/stage2d01/"
                         "proposed_stage2d1_moves_final.csv). READY/CORRUPT_MOVE_READY "
                         "row 만 선택하고 금지 status 가 선택 범위에 있으면 거부한다.")
    ap.add_argument("--d1-plan-sha256", default=None, metavar="HEX",
                    help="stage2d1 전용: 계획 CSV 의 기대 SHA256. 불일치하면 계획·적용을 "
                         "거부한다(계획 변조·갱신 방지).")
    ap.add_argument("--move-ids", default=None, metavar="ID,ID",
                    help="stage2d1 전용: 이 move_id 만 계획 (cohort 안에서 일부만 다룰 때)")
    ap.add_argument("--max-hash-read-gib", type=float, default=None, metavar="GIB",
                    help="SHA256 read 예산(GiB). 예상 read 가 한도를 넘으면 해시를 "
                         "시작하기 전에 거부하고, 읽는 중 넘으면 중단한다. selective 로 "
                         "자동 강등하지 않는다. 생략하면 무제한(기존 동작과 동일).")
    ap.add_argument("--max-hash-read-bytes", type=int, default=None, metavar="BYTES",
                    help="--max-hash-read-gib 의 바이트 단위 형태. 둘 다 주면 이 값이 이긴다.")
    ap.add_argument("--expected-destination-additions", default=None, metavar="JSON",
                    help="--verify: 이동 후 destination 에 추가된 파일을 **exact allowlist** 로만 "
                         "허용한다. JSON 은 manifest_sha256 으로 이 원장에 결속되고, 각 항목의 "
                         "relative_path/size/sha256 이 정확히 일치해야 한다. 명세에 없는 extra, "
                         "명세에 있는데 없는 파일, 크기·해시 불일치는 전부 실패. "
                         "옮긴 파일의 누락·해시 불일치는 이 옵션과 무관하게 항상 실패한다.")
    ap.add_argument("--allow-any-destination-additions", action="store_true",
                    help="[DEPRECATED · 실원장 검증에 쓰지 말 것] destination 의 모든 추가 파일을 "
                         "검증 없이 통과시킨다. 오염된 파일이 섞여도 통과하므로 조사용으로만 쓴다.")
    ap.add_argument("--allow-destination-additions", action="store_true",
                    help="[DEPRECATED] 단독 사용은 오류다. 무엇을 허용할지 명시해야 한다 — "
                         "--expected-destination-additions(권장) 또는 "
                         "--allow-any-destination-additions 를 쓰라.")
    ap.add_argument("--d11-scope", default=None, metavar="JSON",
                    help="stage2d11 전용: frozen_scope.json (재계산된 잔여 범위)")
    ap.add_argument("--d11-scope-sha256", default=None, metavar="HEX",
                    help="stage2d11 전용: frozen scope 의 기대 SHA256")
    ap.add_argument("--d11-allow-prior-ledger-with-chain", action="store_true",
                    help="stage2d11 전용: prior ledger 구성원 이동을 허용한다. "
                         "**successor chain 을 만들 계획이 있을 때만** 쓴다 — 이동 후 "
                         "--successor-ledger-chain 으로 prior 원장 검증을 반드시 통과시켜야 "
                         "한다. 그러지 않으면 검증 사슬이 끊긴 상태로 남는다.")
    ap.add_argument("--d11-license-decision", default=None,
                    help="stage2d11 전용: 원장에 남길 license 판정 "
                         "(PROVEN_REDISTRIBUTABLE / PROVEN_NOAI / UNRESOLVED_LICENSE)")
    ap.add_argument("--d11-provenance-evidence", default=None,
                    help="stage2d11 전용: 판정 근거 요약 (원장에 기록)")
    ap.add_argument("--d11-registry-keys-after", default=None,
                    help="stage2d11 전용: 이동 후 이 자료를 가리키는 registry key")
    ap.add_argument("--d11-exclusion-after", default=None,
                    help="stage2d11 전용: 이동 후 exclusion 경로")
    ap.add_argument("--d12-scope", default=None, metavar="JSON",
                    help="stage2d12 전용: frozen_scope.json (목적지·registry 전환·"
                         "provenance 판정이 확정된 범위)")
    ap.add_argument("--d12-scope-sha256", default=None, metavar="HEX",
                    help="stage2d12 전용: frozen scope 의 기대 SHA256")
    ap.add_argument("--d12-allow-prior-ledger-with-chain", action="store_true",
                    help="stage2d12 전용: prior ledger 구성원 이동 허용. successor chain 을 "
                         "만들 계획이 있을 때만 쓴다 — 이동 후 --successor-ledger-chain 으로 "
                         "prior 원장 검증을 반드시 통과시켜야 한다.")
    ap.add_argument("--d2-plan", default=None, metavar="JSON",
                    help="stage2d2 전용: frozen_final_plan.json "
                         "(최종 destination·cohort·참조 실측이 확정된 계획)")
    ap.add_argument("--d2-plan-sha256", default=None, metavar="HEX",
                    help="stage2d2 전용: frozen plan 의 기대 SHA256")
    ap.add_argument("--successor-ledger-chain", default=None, metavar="JSON",
                    action="append",
                    help="--verify: (반복 가능) prior 원장에서 없어진 파일을 후속 원장이 이어받았음을 "
                         "**파일 단위 SHA256 identity** 로 증명하는 chain 명세. "
                         "prior/successor manifest SHA256 결속 + prior 원장의 size·sha256 · "
                         "successor source==prior destination · successor VERIFIED · "
                         "successor destination 실측 해시가 모두 일치할 때만 missing 에서 "
                         "제외한다. 아직 prior destination 에 있는 파일은 chain 에 넣을 수 없다. "
                         "expected-destination-additions 와 함께 쓸 수 있다.")
    ap.add_argument("--only-source", default=None,
                    help="stage2b 전용: 이 source 만 계획 (쉼표 구분, allowlist 안이어야 함)")
    args = ap.parse_args(argv)

    if getattr(args, "allow_destination_additions", False) and not (
            args.expected_destination_additions or args.allow_any_destination_additions):
        ap.error("--allow-destination-additions 는 단독으로 쓸 수 없습니다. "
                 "무엇을 허용할지 명시하십시오: --expected-destination-additions <json> (권장) "
                 "또는 --allow-any-destination-additions")

    # GiB 편의 옵션을 바이트로 접는다. 둘 다 없으면 None(무제한) 그대로 둔다.
    if args.max_hash_read_bytes is None and args.max_hash_read_gib is not None:
        args.max_hash_read_bytes = int(args.max_hash_read_gib * 1024 ** 3)

    if args.policy == POLICY_STAGE2D1 and args.plan and not args.d1_plan:
        ap.error("정책 %s 는 --d1-plan <csv> 가 필요합니다." % POLICY_STAGE2D1)
    if args.policy == POLICY_STAGE2D11 and args.plan and not args.d11_scope:
        ap.error("정책 %s 는 --d11-scope <json> 이 필요합니다." % POLICY_STAGE2D11)
    if args.policy == POLICY_STAGE2D12 and args.plan and not args.d12_scope:
        ap.error("정책 %s 는 --d12-scope <json> 이 필요합니다." % POLICY_STAGE2D12)
    if args.policy == POLICY_STAGE2D2 and args.plan and not args.d2_plan:
        ap.error("정책 %s 는 --d2-plan <json> 이 필요합니다." % POLICY_STAGE2D2)

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
