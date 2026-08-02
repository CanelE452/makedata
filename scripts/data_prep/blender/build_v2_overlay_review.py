"""canonical overlay 전수 생성 + mode 별 contact sheet + 극단 사례 선정 (읽기 전용).

overlay 는 직접 그리지 않는다 — `overlay_archive_trunc_style.draw_archive_style_overlay()`
가 golden reference 로 고정된 정본이고 cuboid · 9 keypoint · pose 축 · Pitch/Yaw/Roll
패널을 함께 그린다.

    python scripts/data_prep/blender/build_v2_overlay_review.py \
        --dir data/pallet/runs/diagnostics/<run> \
        --out reports/<report>/overlay_review

극단 사례는 손으로 고르지 않는다 — 고정된 quantile 규칙(min/median/max)으로 뽑고
선정 규칙과 frame id 를 CSV 로 남긴다.
"""
import argparse
import collections
import csv
import io
import json
import os
import sys

import numpy as np
from PIL import Image

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import overlay_v2_detailed as OV            # noqa: E402
import overlay_archive_trunc_style as ARCH  # noqa: E402

MODES = ("clean-static", "cargo-only", "context-rich", "controlled-occlusion")
MODE_SLUG = {"clean-static": "clean", "cargo-only": "cargo",
             "context-rich": "context", "controlled-occlusion": "controlled"}


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def canonical_overlay(root, usable_id, record):
    """정본 overlay 를 PIL Image 로 반환 (원본 해상도 그대로)."""
    stem = "f%04d" % usable_id
    rgb = os.path.join(root, "rgb", stem + "_rgb.png")
    label_path = os.path.join(root, "labels", stem + "_label.json")
    if not (os.path.isfile(rgb) and os.path.isfile(label_path)):
        return None
    label = json.load(io.open(label_path, encoding="utf-8"))
    obj = (label.get("objects") or [None])[0]
    geom = OV.frame_geometry(label, obj)
    if not geom:
        return None
    uv8 = geom.get("uv8")
    centroid = geom.get("uv_centroid")
    kps9 = None
    if uv8 is not None and centroid is not None:
        kps9 = ([list(map(float, uv8[i])) for i in range(len(uv8))]
                + [list(map(float, centroid))])
    axes = OV.pose_axis_endpoints(geom)
    ctx = OV.build_context(root, usable_id, label, obj, None, record or {},
                           None, None, None, geom=geom)
    meta = OV.archive_metadata(ctx)
    with Image.open(rgb) as image:
        return ARCH.draw_archive_style_overlay(image.convert("RGB"), kps9,
                                               axes, meta)


def overlay_audit(root, usable_id, overlay):
    """overlay 품질을 픽셀로 검사한다 — "그렸다"는 선언 대신 실제 차이를 본다.

    canonical overlay 는 좌상단에 정보 패널(Pitch/Yaw/Roll 포함), 우하단에 축 범례를
    그린다.  두 영역이 원본 RGB 와 실제로 달라졌는지 확인한다.
    """
    rgb_path = os.path.join(root, "rgb", "f%04d_rgb.png" % usable_id)
    result = {"overlay_w": overlay.width, "overlay_h": overlay.height,
              "rgb_w": None, "rgb_h": None, "size_matches_rgb": None,
              "panel_drawn": None, "legend_drawn": None,
              "differs_from_rgb": None, "overlay_ok": False}
    if not os.path.isfile(rgb_path):
        return result
    with Image.open(rgb_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    over = np.asarray(overlay.convert("RGB"))
    result["rgb_w"], result["rgb_h"] = int(rgb.shape[1]), int(rgb.shape[0])
    result["size_matches_rgb"] = bool(over.shape == rgb.shape)
    if not result["size_matches_rgb"]:
        return result
    diff = (over != rgb).any(axis=-1)
    height, width = diff.shape
    panel = diff[:min(140, height), :min(230, width)]
    legend = diff[max(0, height - 70):, max(0, width - 130):]
    result["differs_from_rgb"] = bool(diff.any())
    result["panel_drawn"] = bool(panel.mean() > 0.05)
    result["legend_drawn"] = bool(legend.mean() > 0.02)
    result["overlay_ok"] = bool(result["size_matches_rgb"]
                                and result["panel_drawn"]
                                and result["legend_drawn"])
    return result


def contact_sheet(images, columns=4, thumb_w=480, pad=6, bg=(24, 24, 28)):
    if not images:
        return None
    thumbs = []
    for image in images:
        ratio = thumb_w / float(image.width)
        thumbs.append(image.resize((thumb_w, max(1, int(image.height * ratio))),
                                   Image.LANCZOS))
    rows = (len(thumbs) + columns - 1) // columns
    cell_h = max(t.height for t in thumbs)
    sheet = Image.new("RGB",
                      (columns * thumb_w + (columns + 1) * pad,
                       rows * cell_h + (rows + 1) * pad), bg)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, columns)
        sheet.paste(thumb, (pad + col * (thumb_w + pad),
                            pad + row * (cell_h + pad)))
    return sheet


def pick_extremes(rows, key, label):
    """min / median / max 를 고정 규칙으로 뽑는다 (손으로 고르지 않는다)."""
    usable = [r for r in rows if r.get(key) is not None]
    if not usable:
        return []
    usable.sort(key=lambda r: float(r[key]))
    picks = [("min", usable[0]), ("median", usable[len(usable) // 2]),
             ("max", usable[-1])]
    return [{"selection": label, "quantile": q, "usable_id": r["usable_id"],
             "diagnostic_mode": r["diagnostic_mode"], "metric": key,
             "value": r[key], "rule": f"sort by {key} asc; take {q}"}
            for q, r in picks]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--columns", type=int, default=4)
    ap.add_argument("--max-id", type=int, default=None,
                    help="이 usable_id 까지만 (진행 중인 run 의 앞부분만 볼 때)")
    ap.add_argument("--dataset-overlay-dir", default=None,
                    help="데이터셋 쪽에도 같은 overlay 를 남긴다 (예: <run>/overlay)")
    ap.add_argument("--audit", action="store_true",
                    help="overlay 품질 감사(크기·패널·범례)를 함께 수행한다")
    args = ap.parse_args(argv)

    root, out = _abs(args.dir), _abs(args.out)
    all_dir = os.path.join(out, "all")
    os.makedirs(all_dir, exist_ok=True)

    latest = {}
    for line in io.open(os.path.join(root, "records.jsonl"), encoding="utf-8"):
        if not line.strip():
            continue
        record = json.loads(line)
        key = record.get("usable_id", record.get("idx"))
        if isinstance(key, int):
            latest[key] = record
    ids = sorted(latest)
    if args.max_id is not None:
        ids = [i for i in ids if i <= args.max_id]

    dataset_dir = (_abs(args.dataset_overlay_dir)
                   if args.dataset_overlay_dir else None)
    if dataset_dir:
        os.makedirs(dataset_dir, exist_ok=True)

    rows, images, failures = [], {}, []
    for usable_id in ids:
        record = latest[usable_id]
        overlay = canonical_overlay(root, usable_id, record)
        if overlay is None:
            print("  ! overlay 실패 f%04d" % usable_id)
            failures.append(usable_id)
            continue
        path = os.path.join(all_dir, "f%04d_overlay.png" % usable_id)
        overlay.save(path)
        if dataset_dir:
            overlay.save(os.path.join(dataset_dir, "f%04d_overlay.png" % usable_id))
        images[usable_id] = overlay
        audit = overlay_audit(root, usable_id, overlay) if args.audit else {}
        rows.append({
            "usable_id": usable_id,
            "diagnostic_mode": record.get("diagnostic_mode"),
            "overlay_rel": os.path.relpath(path, out).replace(os.sep, "/"),
            **audit,
            "cargo_visible_pixels": record.get("cargo_visible_pixels"),
            "context_visible_pixel_ratio": record.get("context_visible_pixel_ratio"),
            "explicit_occluder_visible_pixels": record.get(
                "explicit_occluder_visible_pixels"),
            "f_explicit_target": record.get("f_explicit_target"),
            "f_explicit_actual_lowres": record.get("f_explicit_actual_lowres"),
            # public 프로필은 마스크 분해가 없으므로 저해상도 오차가 유일한 값이다.
            "abs_target_error": record.get("explicit_abs_error_lowres"),
            "runtime_s": record.get("runtime_s"),
        })

    with io.open(os.path.join(out, "overlay_index.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    for mode in MODES:
        picked = [r["usable_id"] for r in rows if r["diagnostic_mode"] == mode]
        sheet = contact_sheet([images[i] for i in picked], columns=args.columns)
        if sheet is not None:
            sheet.save(os.path.join(out, f"contact_{MODE_SLUG[mode]}.png"))
            sheet.save(os.path.join(out, f"sheet_{MODE_SLUG[mode]}.png"))
        print("  sheet_%s.png  %d장" % (MODE_SLUG[mode], len(picked)))

    extremes = []
    extremes += pick_extremes([r for r in rows
                               if r["diagnostic_mode"] == "cargo-only"],
                              "cargo_visible_pixels", "cargo_visible_pixels")
    extremes += pick_extremes([r for r in rows
                               if r["diagnostic_mode"] == "context-rich"],
                              "context_visible_pixel_ratio",
                              "context_visible_ratio")
    controlled = [r for r in rows
                  if r["diagnostic_mode"] == "controlled-occlusion"]
    extremes += pick_extremes(controlled, "abs_target_error",
                              "controlled_f_target_error")
    extremes += pick_extremes(controlled, "runtime_s", "controlled_runtime")
    with io.open(os.path.join(out, "extreme_cases.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["selection", "quantile",
                                                "usable_id", "diagnostic_mode",
                                                "metric", "value", "rule"])
        writer.writeheader()
        writer.writerows(extremes)
    sheet = contact_sheet([images[e["usable_id"]] for e in extremes
                           if e["usable_id"] in images], columns=args.columns)
    if sheet is not None:
        sheet.save(os.path.join(out, "contact_extremes.png"))
    # §13 이 요구한 축별 극단 sheet — 선정 규칙은 위 quantile rule 그대로다.
    for name, selections in (
            ("runtime", ("controlled_runtime",)),
            ("visibility", ("cargo_visible_pixels", "context_visible_ratio")),
            ("error", ("controlled_f_target_error",))):
        picked = [e["usable_id"] for e in extremes
                  if e["selection"] in selections and e["usable_id"] in images]
        axis_sheet = contact_sheet([images[i] for i in picked],
                                   columns=args.columns)
        if axis_sheet is not None:
            axis_sheet.save(os.path.join(out, f"sheet_extreme_{name}.png"))
        print("  sheet_extreme_%s.png  %d장" % (name, len(picked)))

    print("overlay %d장 -> %s" % (len(rows), all_dir))
    if dataset_dir:
        print("dataset overlay -> %s" % dataset_dir)
    print("extreme cases %d행 -> extreme_cases.csv" % len(extremes))
    if args.audit:
        ok = sum(1 for r in rows if r.get("overlay_ok"))
        size_ok = sum(1 for r in rows if r.get("size_matches_rgb"))
        panel = sum(1 for r in rows if r.get("panel_drawn"))
        legend = sum(1 for r in rows if r.get("legend_drawn"))
        audit = {"frames": len(ids), "overlays": len(rows),
                 "failed": failures, "overlay_ok": ok,
                 "size_matches_rgb": size_ok, "panel_drawn": panel,
                 "legend_drawn": legend,
                 "resolutions": dict(collections.Counter(
                     "%dx%d" % (r["overlay_w"], r["overlay_h"]) for r in rows))}
        io.open(os.path.join(out, "overlay_audit.json"), "w", encoding="utf-8",
                newline="\n").write(json.dumps(audit, indent=2,
                                               ensure_ascii=False) + "\n")
        print("audit  overlay_ok %d/%d · size %d · panel %d · legend %d · 실패 %d"
              % (ok, len(rows), size_ok, panel, legend, len(failures)))
        print("       해상도 분포 %s" % audit["resolutions"])
        if ok != len(ids) or failures:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
