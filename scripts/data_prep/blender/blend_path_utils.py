"""`.blend` 외부경로 재작성에 쓰는 순수 helper (bpy-free).

Stage 2-C1 도입. Blender 안에서만 도는 코드는 단위 테스트가 어렵기 때문에, 판단이
들어가는 부분(경로 포함 관계 / 상대경로 계산 / plan 검증 / 해시 대조)을 전부 여기로
빼고 `manage_blend_external_paths.py` 는 bpy 왕복만 담당한다.

설계 원칙
  - Windows 경로가 1급 시민이다. `os.path.commonpath()` 는 백슬래시를 돌려주므로
    forward-slash 로 정규화한 문자열과 직접 비교하면 **항상 False** 가 된다.
    이 버그는 Stage 2-B 감사에서 실제로 발생해 356건을 514건으로 부풀렸다.
    그래서 비교는 `os.path.normcase(os.path.abspath(...))` 로만 한다.
  - drive 가 다르면 상대경로가 성립하지 않는다. 예외를 삼키지 않고 None 을 돌려준다.
  - plan 에 없는 변경은 거부한다. "그 김에 같이 고쳤다" 를 구조적으로 막는다.
"""

import hashlib
import os


BLEND_RELATIVE_PREFIX = "//"

# 사용자·머신에 못박히는 접두 패턴. strict 모드에서 잔존하면 실패시킨다.
USER_SPECIFIC_MARKERS = (
    "/users/",
    "/home/",
    "/documents/",
    "/desktop/",
    "/appdata/",
    "c:/users",
)


# --------------------------------------------------------------------- 경로
def norm(path):
    """비교용 정규화: 절대화 + normcase. 슬래시 방향 혼용을 여기서 흡수한다."""
    if path is None:
        return None
    return os.path.normcase(os.path.abspath(str(path)))


def is_within(path, root):
    """`path` 가 `root` 아래(또는 root 자신)인지.

    `commonpath` 결과를 forward-slash 문자열과 비교하지 않는다 — normcase 된 절대경로
    끼리만 비교한다. prefix collision(`/a/bc` 가 `/a/b` 안이라고 오판) 을 막으려고
    구분자를 붙여 비교한다.
    """
    p, r = norm(path), norm(root)
    if p is None or r is None:
        return False
    if p == r:
        return True
    return p.startswith(r.rstrip(os.sep) + os.sep)


def same_drive(a, b):
    return os.path.splitdrive(norm(a))[0] == os.path.splitdrive(norm(b))[0]


def to_blend_relative(target_abs, blend_dir):
    """`target_abs` 를 `blend_dir` 기준 Blender 상대표기(`//...`)로.

    Blender 의 `//` 는 "이 .blend 가 있는 디렉토리" 를 뜻한다. 구분자는 항상
    forward-slash 로 쓴다(Blender 가 두 방향 다 받지만 Windows 백슬래시를 넣으면
    linux 에서 열 때 깨진다).

    다른 drive 면 상대경로가 성립하지 않으므로 None.
    """
    if not same_drive(target_abs, blend_dir):
        return None
    rel = os.path.relpath(os.path.abspath(str(target_abs)),
                          os.path.abspath(str(blend_dir)))
    return BLEND_RELATIVE_PREFIX + rel.replace("\\", "/")


def resolve_blend_relative(rel_path, blend_dir):
    """`//...` 표기를 절대경로로. `bpy.path.abspath` 없이 같은 의미를 계산한다."""
    text = str(rel_path)
    if not text.startswith(BLEND_RELATIVE_PREFIX):
        return os.path.abspath(text)
    return os.path.abspath(os.path.join(str(blend_dir),
                                        text[len(BLEND_RELATIVE_PREFIX):]))


def is_absolute_filepath(raw):
    """datablock 의 filepath_raw 가 절대경로 표기인지.

    `//` 로 시작하면 Blender 상대표기다. 빈 문자열(packed/generated)은 경로가 아니다.
    """
    text = str(raw or "")
    if not text or text.startswith(BLEND_RELATIVE_PREFIX):
        return False
    if len(text) > 1 and text[1] == ":":       # 드라이브 표기 (E:\..., C:/...)
        return True
    if text[0] in ("/", "\\"):                 # POSIX 절대경로 / UNC
        # Python 3.13 의 ntpath.isabs 는 선행 슬래시 하나짜리를 더 이상 절대경로로 보지
        # 않는다(드라이브 상대경로 취급). Linux 에서 저장된 .blend 를 Windows 에서 감사할
        # 때 `/home/...` 를 상대경로로 오분류하면 안 되므로 직접 판정한다.
        return True
    return os.path.isabs(text)


def has_user_specific_prefix(raw):
    """user profile / drive 에 못박힌 흔적이 남았는지 (strict 게이트용)."""
    text = str(raw or "").replace("\\", "/").lower()
    if not text or text.startswith(BLEND_RELATIVE_PREFIX):
        return False
    return any(marker in text for marker in USER_SPECIFIC_MARKERS)


def escapes_root(rel_path, blend_dir, allowed_root):
    """`//..` 상대경로가 허용 루트 밖으로 나가는지."""
    return not is_within(resolve_blend_relative(rel_path, blend_dir), allowed_root)


# --------------------------------------------------------------------- 해시
def sha256_file(path, chunk=1 << 20):
    """파일 SHA256. 없으면 None (예외로 흐름을 끊지 않고 판정에 남긴다)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


# --------------------------------------------------------------------- plan
class PlanError(Exception):
    """계획 자체가 성립하지 않는 경우 (진행 금지)."""


def assert_distinct_files(source, candidate):
    """source 와 candidate 가 같은 파일을 가리키면 즉시 중단."""
    if norm(source) == norm(candidate):
        raise PlanError(
            "source 와 candidate 가 같은 경로입니다. 원본을 덮어쓸 수 있습니다: %s" % source)


def assert_candidate_not_present(candidate):
    if os.path.exists(candidate):
        raise PlanError("candidate 가 이미 존재합니다(overwrite 금지): %s" % candidate)


def assert_source_unchanged(source, expected_sha256):
    actual = sha256_file(source)
    if actual != expected_sha256:
        raise PlanError(
            "source blend 의 SHA256 이 바뀌었습니다.\n  expected %s\n  actual   %s"
            % (expected_sha256, actual))
    return actual


def build_mapping(entry, blend_dir, allowed_root):
    """절대경로 datablock 하나를 상대경로로 바꾸는 계획 1건을 만든다.

    entry: {"name","filepath_raw","filepath_absolute"} 를 가진 dict.
    반환: 계획 dict. `status` 가 "PLANNED" 가 아니면 적용하지 않는다.
    """
    old_abs = entry.get("filepath_absolute")
    plan = {
        "datablock_name": entry.get("name"),
        "old_filepath": entry.get("filepath_raw"),
        "old_absolute": old_abs,
        "old_sha256": None,
        "new_filepath": None,
        "new_absolute": None,
        "new_sha256": None,
        "same_file": False,
        "status": "BLOCKED",
        "blocker": "",
    }
    if not old_abs or not os.path.isfile(old_abs):
        plan["blocker"] = "source_file_missing"
        return plan
    if not is_within(old_abs, allowed_root):
        plan["blocker"] = "outside_allowed_root"
        return plan

    new_rel = to_blend_relative(old_abs, blend_dir)
    if new_rel is None:
        plan["blocker"] = "different_drive"
        return plan
    new_abs = resolve_blend_relative(new_rel, blend_dir)
    if not os.path.isfile(new_abs):
        plan["blocker"] = "resolved_target_missing"
        return plan
    if escapes_root(new_rel, blend_dir, allowed_root):
        plan["blocker"] = "escapes_allowed_root"
        return plan
    if has_user_specific_prefix(new_rel):
        plan["blocker"] = "user_specific_prefix_remains"
        return plan

    old_hash = sha256_file(old_abs)
    new_hash = sha256_file(new_abs)
    plan.update({
        "old_sha256": old_hash,
        "new_filepath": new_rel,
        "new_absolute": new_abs,
        "new_sha256": new_hash,
        "same_file": bool(old_hash) and old_hash == new_hash,
    })
    if not plan["same_file"]:
        plan["blocker"] = "sha256_mismatch"
        return plan
    plan["status"] = "PLANNED"
    return plan


def assert_only_planned_changes(planned_names, changed_names):
    """실제로 바꾼 datablock 집합이 계획 집합과 정확히 같은지."""
    extra = sorted(set(changed_names) - set(planned_names))
    if extra:
        raise PlanError("계획에 없는 datablock 이 수정되었습니다: %s" % ", ".join(extra))
    missed = sorted(set(planned_names) - set(changed_names))
    if missed:
        raise PlanError("계획된 datablock 이 수정되지 않았습니다: %s" % ", ".join(missed))


# ------------------------------------------------------- missing datablock 판정
DECISION_REPOINT_EXACT = "REPOINT_EXACT"
DECISION_REMOVE_UNUSED = "REMOVE_UNUSED_CANDIDATE_ONLY"
DECISION_BLOCKED_USED = "BLOCKED_USED_MISSING"
DECISION_BLOCKED_AMBIGUOUS = "BLOCKED_AMBIGUOUS"


def decide_missing_datablock(candidates, users, fake_user, referenced_by):
    """누락된 외부파일 datablock 을 어떻게 할지 판정한다.

    candidates: 같은 basename 을 가진 실제 파일 경로 리스트 (라이선스·용도 확인을 마친 것만
                넘긴다 — 이 함수는 개수만 본다).
    users / fake_user / referenced_by: Blender 쪽에서 읽어온 사용 흔적.

    임의 대체를 못 하도록, "후보 1개 + 사용처 있음" 이 아니면 전부 BLOCKED 로 떨어진다.
    """
    used = bool(users) or bool(fake_user) or bool(referenced_by)
    if len(candidates) > 1:
        return DECISION_BLOCKED_AMBIGUOUS
    if len(candidates) == 1:
        return DECISION_REPOINT_EXACT
    return DECISION_BLOCKED_USED if used else DECISION_REMOVE_UNUSED
