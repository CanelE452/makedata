"""Fail-closed same-seed comparator for Blender v2 scene outputs.

The comparison is semantic for JSON and exact for decoded pixels.  Paths,
runtime measurements, and process-session bookkeeping are deliberately
excluded by exact field name; every other JSON field participates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import os

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mask_profiles as MP  # noqa: E402


# full-audit 5-stage. public 셋은 MP.mask_stages(PUBLIC) = (m0, m4) 로 축소된다.
MASK_NAMES = ("m0", "m1", "m2", "m3", "m4")

# Exact names only.  Do not replace this with suffix/pattern matching: an
# unlisted field must remain part of the deterministic contract.
EXCLUDED_JSON_FIELDS = frozenset(
    {
        "runtime_s",
        "stage_runtime_s",
        "rgb_path",
        "label_path",
        "mask_paths",
        "output_path",
        "output_root",
        "session_id",
        "session_start",
        "session_count",
        "session_completed",
        "session_pending",
        "session_elapsed_s",
        "processed_this_session",
        "rendered_this_session",
    }
)


class InvalidJson(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise InvalidJson(f"non-finite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJson(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"missing file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(
                handle,
                parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, InvalidJson) as exc:
        raise InvalidJson(f"{path}: {exc}") from exc


def _load_records(root: Path) -> dict[int, dict[str, Any]]:
    payload = _read_json(root / "records.json")
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        raise InvalidJson("records.json must be a list or an object with a records list")

    records: dict[int, dict[str, Any]] = {}
    for position, record in enumerate(payload):
        if not isinstance(record, dict):
            raise InvalidJson(f"record at position {position} is not an object")
        idx = record.get("idx")
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise InvalidJson(f"record at position {position} has invalid idx: {idx!r}")
        if idx in records:
            raise InvalidJson(f"duplicate record idx: {idx}")
        records[idx] = record
    return records


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical_value(item)
            for key, item in value.items()
            if key not in EXCLUDED_JSON_FIELDS
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _short_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= 500 else text[:497] + "..."


def _first_difference(left: Any, right: Any, path: str = "$") -> dict[str, Any]:
    if type(left) is not type(right):
        return {
            "path": path,
            "left": _short_value(left),
            "right": _short_value(right),
        }
    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            return {
                "path": path,
                "left_only_keys": sorted(left_keys - right_keys),
                "right_only_keys": sorted(right_keys - left_keys),
            }
        for key in sorted(left_keys):
            if left[key] != right[key]:
                return _first_difference(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        if len(left) != len(right):
            return {
                "path": path,
                "left_length": len(left),
                "right_length": len(right),
            }
        for position, (left_item, right_item) in enumerate(zip(left, right)):
            if left_item != right_item:
                return _first_difference(
                    left_item,
                    right_item,
                    f"{path}[{position}]",
                )
    elif left != right:
        return {
            "path": path,
            "left": _short_value(left),
            "right": _short_value(right),
        }
    return {"path": path, "left": _short_value(left), "right": _short_value(right)}


def _decode_pixels(path: Path, mode: str) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"missing file: {path}")
    try:
        with Image.open(path) as image:
            image.load()
            return np.asarray(image.convert(mode)).copy()
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _pixel_difference(
    category: str,
    idx: int,
    left: np.ndarray,
    right: np.ndarray,
    *,
    mask: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "category": category,
        "idx": idx,
        "left_shape": list(left.shape),
        "right_shape": list(right.shape),
    }
    if mask is not None:
        item["mask"] = mask
    if left.shape != right.shape or left.dtype != right.dtype:
        item["left_dtype"] = str(left.dtype)
        item["right_dtype"] = str(right.dtype)
        return item

    differing = left != right
    item["differing_values"] = int(np.count_nonzero(differing))
    first = np.argwhere(differing)[0]
    coordinate = tuple(int(value) for value in first)
    item["first_coordinate"] = list(coordinate)
    item["left_value"] = int(left[coordinate])
    item["right_value"] = int(right[coordinate])
    return item


def _artifact_paths(root: Path, idx: int, mask_stages=None,
                    profile: str | None = None) -> dict[str, Path]:
    """프레임 idx 의 비교 대상 경로.

    mask 경로는 직접 조립하지 않고 mask_profiles 로 해석한다. profile 이 주어지면
    그 레이아웃을, 아니면 legacy full-audit `<root>/mask/<frame>_<stage>.png` 를 쓴다.
    """
    frame = MP.frame_stem(idx)
    result = {
        "label": root / "labels" / f"{frame}_label.json",
        "rgb": root / "rgb" / f"{frame}_rgb.png",
    }
    stages = tuple(mask_stages) if mask_stages is not None else MASK_NAMES
    if profile is None:
        result.update({f"mask:{name}": root / "mask" / f"{frame}_{name}.png"
                       for name in stages})
    else:
        resolved = MP.frame_mask_paths(root, idx, profile)
        result.update({f"mask:{name}": Path(resolved[name]) for name in stages})
    return result


def compare_output_roots(left_root: str | Path, right_root: str | Path,
                         allow_mask_profile_mismatch: bool = False,
                         mask_names: tuple[str, ...] | None = None) -> dict[str, Any]:
    left_root = Path(left_root).resolve()
    right_root = Path(right_root).resolve()
    errors: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    compared = {"records": 0, "labels": 0, "rgb": 0, "masks": 0}

    # ---- mask 레이아웃: 좌/우를 각각 독립 감지한다. 한쪽 profile 로 다른 쪽을 읽지 않는다.
    if mask_names is not None:                       # legacy 명시 override (하위호환)
        left_profile = right_profile = None
        compared_stages = tuple(mask_names)
        partial_mask_comparison = False
        left_profile_name = right_profile_name = "legacy-explicit"
    else:
        left_profile = MP.detect_profile(left_root)
        right_profile = MP.detect_profile(right_root)
        left_profile_name, right_profile_name = left_profile, right_profile
        left_stages = MP.mask_stages(left_profile)
        right_stages = MP.mask_stages(right_profile)
        if left_profile == right_profile:
            compared_stages = tuple(left_stages)
            partial_mask_comparison = False
        else:
            # 서로 다른 레이아웃을 조용히 섞지 않는다.
            compared_stages = tuple(s for s in left_stages if s in right_stages)
            partial_mask_comparison = True
            entry = {
                "category": "mask_profile_mismatch",
                "left_mask_profile": left_profile,
                "right_mask_profile": right_profile,
                "compared_mask_stages": list(compared_stages),
            }
            if allow_mask_profile_mismatch:
                # 공통 stage 만 비교하고, 완전 결정성으로 표현하지 않는다.
                mismatches.append({**entry, "allowed": True})
            else:
                errors.append(entry)

    loaded: dict[str, dict[int, dict[str, Any]] | None] = {}
    for side, root in (("left", left_root), ("right", right_root)):
        try:
            if not root.is_dir():
                raise FileNotFoundError(f"missing output root: {root}")
            loaded[side] = _load_records(root)
        except (OSError, ValueError) as exc:
            loaded[side] = None
            errors.append(
                {
                    "category": "records_load",
                    "side": side,
                    "path": str(root / "records.json"),
                    "error": str(exc),
                }
            )

    left_records = loaded["left"] or {}
    right_records = loaded["right"] or {}
    left_indices = sorted(left_records)
    right_indices = sorted(right_records)
    left_only = sorted(set(left_indices) - set(right_indices))
    right_only = sorted(set(right_indices) - set(left_indices))
    if left_only or right_only:
        mismatches.append(
            {
                "category": "record_indices",
                "left_only": left_only,
                "right_only": right_only,
            }
        )

    common_indices = sorted(set(left_indices) & set(right_indices))
    for idx in common_indices:
        left_record = _canonical_value(left_records[idx])
        right_record = _canonical_value(right_records[idx])
        compared["records"] += 1
        if _canonical_json(left_record) != _canonical_json(right_record):
            mismatches.append(
                {
                    "category": "record_semantics",
                    "idx": idx,
                    **_first_difference(left_record, right_record),
                }
            )

        left_paths = _artifact_paths(left_root, idx, compared_stages, left_profile)
        right_paths = _artifact_paths(right_root, idx, compared_stages, right_profile)

        try:
            left_label = _canonical_value(_read_json(left_paths["label"]))
        except (OSError, ValueError) as exc:
            left_label = None
            errors.append(
                {
                    "category": "label_load",
                    "side": "left",
                    "idx": idx,
                    "path": str(left_paths["label"]),
                    "error": str(exc),
                }
            )
        try:
            right_label = _canonical_value(_read_json(right_paths["label"]))
        except (OSError, ValueError) as exc:
            right_label = None
            errors.append(
                {
                    "category": "label_load",
                    "side": "right",
                    "idx": idx,
                    "path": str(right_paths["label"]),
                    "error": str(exc),
                }
            )
        if left_label is not None and right_label is not None:
            compared["labels"] += 1
            if _canonical_json(left_label) != _canonical_json(right_label):
                mismatches.append(
                    {
                        "category": "label_semantics",
                        "idx": idx,
                        **_first_difference(left_label, right_label),
                    }
                )

        decoded: dict[tuple[str, str], np.ndarray] = {}
        for side, paths in (("left", left_paths), ("right", right_paths)):
            for artifact, mode in (("rgb", "RGB"),) + tuple(
                (f"mask:{name}", "L") for name in compared_stages
            ):
                try:
                    decoded[(side, artifact)] = _decode_pixels(
                        paths[artifact],
                        mode,
                    )
                except (OSError, ValueError) as exc:
                    errors.append(
                        {
                            "category": "artifact_decode",
                            "side": side,
                            "idx": idx,
                            "artifact": artifact,
                            "path": str(paths[artifact]),
                            "error": str(exc),
                        }
                    )

        if ("left", "rgb") in decoded and ("right", "rgb") in decoded:
            compared["rgb"] += 1
            left_rgb = decoded[("left", "rgb")]
            right_rgb = decoded[("right", "rgb")]
            if not np.array_equal(left_rgb, right_rgb):
                mismatches.append(
                    _pixel_difference("rgb_pixels", idx, left_rgb, right_rgb)
                )

        for name in compared_stages:
            artifact = f"mask:{name}"
            if ("left", artifact) not in decoded or ("right", artifact) not in decoded:
                continue
            compared["masks"] += 1
            left_mask = decoded[("left", artifact)]
            right_mask = decoded[("right", artifact)]
            if not np.array_equal(left_mask, right_mask):
                mismatches.append(
                    _pixel_difference(
                        "mask_pixels",
                        idx,
                        left_mask,
                        right_mask,
                        mask=name,
                    )
                )

    report = {
        "schema_version": 1,
        "left_root": str(left_root),
        "right_root": str(right_root),
        "deterministic": not errors and not mismatches,
        "left_mask_profile": left_profile_name,
        "right_mask_profile": right_profile_name,
        "compared_mask_stages": list(compared_stages),
        "partial_mask_comparison": partial_mask_comparison,
        "mask_profile_mismatch": left_profile_name != right_profile_name,
        "excluded_json_fields": sorted(EXCLUDED_JSON_FIELDS),
        "indices": {
            "left": left_indices,
            "right": right_indices,
            "common": common_indices,
            "match": left_indices == right_indices,
        },
        "compared": compared,
        "mismatches": mismatches,
        "errors": errors,
    }
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two same-seed Blender v2 output roots exactly.",
    )
    parser.add_argument("left_root")
    parser.add_argument("right_root")
    parser.add_argument(
        "--allow-mask-profile-mismatch", action="store_true",
        help="좌/우 mask 레이아웃이 다를 때 공통 stage(m0,m4)만 비교한다. "
             "결과는 partial_mask_comparison=true 로 표시되며 완전 결정성 통과가 아니다.",
    )
    parser.add_argument(
        "--mask-names", default=None,
        help="Legacy override: <root>/mask/<frame>_<name>.png 접미사를 직접 지정한다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mask_names = (tuple(x.strip() for x in args.mask_names.split(",") if x.strip())
                  if args.mask_names else None)
    report = compare_output_roots(
        args.left_root, args.right_root,
        allow_mask_profile_mismatch=args.allow_mask_profile_mismatch,
        mask_names=mask_names,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["deterministic"] else 1


if __name__ == "__main__":
    sys.exit(main())
