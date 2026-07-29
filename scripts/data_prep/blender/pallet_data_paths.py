"""data/pallet 경로 registry resolver (bpy-free).

Stage 2-A 도입. `config/synthetic/pallet_paths.yaml` 한 곳에서 데이터 경로를 정의하고,
코드는 문자열 리터럴 대신 이 모듈의 키를 쓴다.

설계 원칙
  - registry 는 **지금 실제로 있는 경로**만 담는다. 옮기고 싶은 경로를 미리 적지 않는다.
  - 없는 경로에 대해 임의 fallback 을 만들지 않는다. 없으면 없다고 보고한다
    (조용히 다른 경로로 새는 것이 이 저장소에서 반복된 실패 방식이었다).
  - bpy 를 import 하지 않는다. Blender 밖에서도 그대로 단위 테스트된다
    (distractor_pool_v2.py / mask_profiles.py 와 같은 관례).
"""

import json
import os
import sys

try:  # blender_config.py 와 같은 처리 — Blender 내장 python 에 PyYAML 이 없을 수 있다.
    import yaml
except ImportError:
    yaml = None


DEFAULT_CONFIG_RELPATH = os.path.join("config", "synthetic", "pallet_paths.yaml")
ROOT_KEY = "pallet_data_root"
ROOT_ENV_VAR = "PALLET_DATA_ROOT"
CONFIG_ENV_VAR = "FOUNDATIONPOSE_PALLET_PATHS"

# registry 에 반드시 있어야 하는 키. 빠지면 로드 시점에 KeyError 로 알린다.
REQUIRED_KEYS = (
    "pallet_data_root",
    "production_scene",
    "background_root",
    "distractor_root",
    "distractor_manifest",
    "hdri_root",
    "floor_material_root",
    "pallet_material_root",
    "pallet_model_roots",
    "golden_overlay_reference",
    "real_data_root",
    "runs_root",
    "release_root",
    "archive_root",
)


def detect_project_root(start=None):
    """`config/synthetic/` 와 `data/pallet` 을 함께 가진 상위 디렉토리를 찾는다."""
    here = os.path.abspath(start or os.path.dirname(__file__))
    cur = here
    while True:
        if (os.path.isdir(os.path.join(cur, "config", "synthetic"))
                and os.path.isdir(os.path.join(cur, "data", "pallet"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 탐색 실패 시에만 이 파일 위치 기준 3단계 상위 (scripts/data_prep/blender -> repo)
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _normalize(path_value):
    """윈도우 backslash 와 posix slash 를 모두 받아 posix 상대표기로 통일."""
    return str(path_value).replace("\\", "/").strip()


def _strip_hash_comments(text):
    """줄 전체가 '#' 주석인 줄만 제거한다 (json fallback 용).

    Blender 내장 Python 에는 PyYAML 이 없어서 json.loads 로 떨어지는데, json 은 '#' 주석을
    파싱하지 못한다. 값 안의 '#'(색상 코드 등)을 건드리지 않도록 **줄 전체가 주석인 경우만**
    지운다. 줄 수를 유지해야 파싱 오류 줄 번호가 원본과 맞으므로 빈 줄로 대체한다.
    """
    out = []
    for line in text.splitlines():
        out.append("" if line.lstrip().startswith("#") else line)
    return "\n".join(out)


def _load_raw(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text)
    # PyYAML 이 없는 환경(Blender 내장 Python)에서도 같은 파일을 읽을 수 있어야 한다.
    return json.loads(_strip_hash_comments(text))


class PalletDataPaths(object):
    """registry 를 절대경로로 해석해 들고 있는 객체."""

    def __init__(self, config_path=None, project_root=None, data_root=None):
        self.project_root = os.path.abspath(project_root or detect_project_root())
        self.config_path = os.path.abspath(
            config_path
            or os.environ.get(CONFIG_ENV_VAR)
            or os.path.join(self.project_root, DEFAULT_CONFIG_RELPATH)
        )
        raw = _load_raw(self.config_path)
        # "// ..." 주석 키와 optional_keys 는 경로가 아니다.
        self._raw = {k: v for k, v in raw.items() if not k.startswith("//")}
        self.optional_keys = tuple(self._raw.pop("optional_keys", ()))

        missing_keys = [k for k in REQUIRED_KEYS if k not in self._raw]
        if missing_keys:
            raise KeyError(
                "pallet_paths registry 에 필수 키가 없습니다: %s (%s)"
                % (", ".join(missing_keys), self.config_path)
            )

        # data root override: 환경변수 > 인자 > registry 값. root 만 바뀌고 하위는 재조립된다.
        registry_root = _normalize(self._raw[ROOT_KEY])
        override = data_root or os.environ.get(ROOT_ENV_VAR)
        self.data_root_override = _normalize(override) if override else None
        self.registry_root = registry_root

        self._resolved = {}
        for key, value in self._raw.items():
            if isinstance(value, (list, tuple)):
                self._resolved[key] = [self._resolve(v) for v in value]
            else:
                self._resolved[key] = self._resolve(value)

    # ---------------------------------------------------------------- 해석
    def _resolve(self, value):
        rel = _normalize(value)
        if self.data_root_override is not None and (
            rel == self.registry_root or rel.startswith(self.registry_root + "/")
        ):
            rel = self.data_root_override + rel[len(self.registry_root):]
        if os.path.isabs(rel):
            return os.path.normpath(rel)
        return os.path.normpath(os.path.join(self.project_root, rel))

    # ---------------------------------------------------------------- 조회
    def __contains__(self, key):
        return key in self._resolved

    def keys(self):
        return tuple(self._resolved.keys())

    def get(self, key):
        """절대경로를 돌려준다. 없는 키는 KeyError (임의 fallback 없음)."""
        if key not in self._resolved:
            raise KeyError(
                "pallet_paths 에 없는 키: %r. 사용 가능: %s"
                % (key, ", ".join(sorted(self._resolved)))
            )
        return self._resolved[key]

    def get_existing(self, key):
        """존재까지 확인해서 돌려준다. 없으면 FileNotFoundError."""
        path = self.get(key)
        if isinstance(path, list):
            missing = [p for p in path if not os.path.exists(p)]
            if missing:
                raise FileNotFoundError(
                    "pallet_paths[%r] 의 경로가 없습니다: %s" % (key, ", ".join(missing))
                )
            return path
        if not os.path.exists(path):
            raise FileNotFoundError("pallet_paths[%r] 경로가 없습니다: %s" % (key, path))
        return path

    def relative(self, key):
        """프로젝트 루트 기준 posix 상대경로 (보고·매니페스트용)."""
        value = self.get(key)
        if isinstance(value, list):
            return [self._relative_one(v) for v in value]
        return self._relative_one(value)

    def _relative_one(self, abs_path):
        try:
            return os.path.relpath(abs_path, self.project_root).replace("\\", "/")
        except ValueError:  # 다른 드라이브
            return abs_path.replace("\\", "/")

    # ---------------------------------------------------------------- 감사
    def audit(self):
        """모든 키의 존재 여부를 조사한다.

        반환: {"ok": [...], "missing": [...], "absent_optional": [...]}
        missing 은 "있어야 하는데 없는 것", absent_optional 은 "없어도 되는 것".
        """
        ok, missing, absent_optional = [], [], []
        for key in sorted(self._resolved):
            value = self._resolved[key]
            paths = value if isinstance(value, list) else [value]
            for path in paths:
                entry = {"key": key, "path": path,
                         "relative": self._relative_one(path)}
                if os.path.exists(path):
                    ok.append(entry)
                elif key in self.optional_keys:
                    absent_optional.append(entry)
                else:
                    missing.append(entry)
        return {"ok": ok, "missing": missing, "absent_optional": absent_optional}


_CACHE = {}


def load(config_path=None, project_root=None, data_root=None, use_cache=True):
    """registry 로드. 같은 인자는 캐시된 인스턴스를 돌려준다."""
    key = (config_path, project_root, data_root,
           os.environ.get(ROOT_ENV_VAR), os.environ.get(CONFIG_ENV_VAR))
    if use_cache and key in _CACHE:
        return _CACHE[key]
    paths = PalletDataPaths(config_path=config_path, project_root=project_root,
                            data_root=data_root)
    if use_cache:
        _CACHE[key] = paths
    return paths


def clear_cache():
    _CACHE.clear()


def get(key, **kwargs):
    """모듈 레벨 단축 조회: pallet_data_paths.get("hdri_root")"""
    return load(**kwargs).get(key)


def _print_audit(paths, report, stream=None):
    out = stream or sys.stdout
    print("project_root : %s" % paths.project_root, file=out)
    print("config       : %s" % paths.config_path, file=out)
    print("data_root    : %s" % paths.get(ROOT_KEY), file=out)
    print(file=out)
    for entry in report["ok"]:
        print("  OK       %-26s %s" % (entry["key"], entry["relative"]), file=out)
    for entry in report["absent_optional"]:
        print("  ABSENT?  %-26s %s  (optional)" % (entry["key"], entry["relative"]), file=out)
    for entry in report["missing"]:
        print("  MISSING  %-26s %s" % (entry["key"], entry["relative"]), file=out)
    print(file=out)
    print("ok=%d missing=%d absent_optional=%d"
          % (len(report["ok"]), len(report["missing"]), len(report["absent_optional"])),
          file=out)


def main(argv=None):
    """CLI.

    --key KEY   해당 경로만 출력하고 종료 (audit 하지 않음)
    --audit     전체 audit 출력
    (인자 없음)  전체 audit 출력 = --audit 와 동일

    exit code:  0 = missing 없음 / 1 = missing 있음 또는 잘못된 key
    """
    import argparse

    ap = argparse.ArgumentParser(description="pallet 데이터 경로 registry 조회/감사")
    ap.add_argument("--config", default=None)
    ap.add_argument("--data-root", default=None, help="pallet_data_root 만 override")
    ap.add_argument("--audit", action="store_true",
                    help="모든 경로 존재 여부 검사 (인자를 아무것도 주지 않아도 동일)")
    ap.add_argument("--key", default=None, help="단일 키 조회 후 종료")
    args = ap.parse_args(argv)

    try:
        paths = load(config_path=args.config, data_root=args.data_root, use_cache=False)
    except (OSError, KeyError, ValueError) as exc:
        print("registry 로드 실패: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1

    if args.key is not None:
        # 단일 키 조회: audit 을 계산하지 않는다(불필요한 stat 방지).
        try:
            value = paths.get(args.key)
        except KeyError:
            print("알 수 없는 key: %r" % args.key, file=sys.stderr)
            print("사용 가능한 key: %s" % ", ".join(sorted(paths.keys())), file=sys.stderr)
            return 1
        for item in (value if isinstance(value, list) else [value]):
            print(item)
        return 0

    # --audit 이 있든 없든 audit 을 출력한다(인자 없음 = 전체 audit).
    report = paths.audit()
    _print_audit(paths, report)
    return 1 if report["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
