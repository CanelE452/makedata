"""dataset-quality same-machine replay probe — 같은 seed 로 다시 렌더한 프레임을 비교한다.

판정을 분리해서 낸다 (§23)
    PLAN_REPRODUCIBLE_EXACT · LABEL_REPRODUCIBLE_EXACT ·
    PUBLIC_MASK_REPRODUCIBLE_EXACT · DATASET_QUALITY_RGB_BITWISE_REPRODUCIBLE_SAME_MACHINE

RGB 가 다르면 숨기지 않고 max/mean 채널 차 · PSNR · 불일치 픽셀 비율을 적는다.

    python scripts/data_prep/blender/audit_v2_dataset_quality_probe.py \
        --a data/pallet/runs/diagnostics/<run> \
        --b data/pallet/runs/diagnostics/<run>_probe \
        --out reports/<report>/g3
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys

import numpy as np
from PIL import Image

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

# 경로·시각·소요시간은 비교에서 제외한다.  그 밖의 필드는 전부 계약에 포함된다.
EXCLUDED = frozenset({
    "rgb_path", "label_path", "mask_paths", "out", "runtime_s",
    "stage_runtime_s", "proposal_prepare_s", "elapsed_s", "attempt_seed",
    "lowres_render_count",
})


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def load_records(root):
    latest = {}
    for line in io.open(os.path.join(root, "records.jsonl"), encoding="utf-8"):
        if not line.strip():
            continue
        record = json.loads(line)
        key = record.get("usable_id", record.get("idx"))
        if isinstance(key, int):
            latest[key] = record
    return latest


def normalize(obj):
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items())
                if k not in EXCLUDED}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 9)
    return obj


def canon(obj):
    return json.dumps(normalize(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pixels(path):
    if not os.path.isfile(path):
        return None
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB") if image.mode != "L"
                          else image.convert("L"))


def compare_images(pa, pb):
    a, b = pixels(pa), pixels(pb)
    if a is None or b is None:
        return {"status": "missing"}
    if a.shape != b.shape:
        return {"status": "shape_mismatch", "a": list(a.shape), "b": list(b.shape)}
    equal = bool(np.array_equal(a, b))
    out = {"status": "ok", "identical": equal,
           "content_sha_a": hashlib.sha256(a.tobytes()).hexdigest(),
           "content_sha_b": hashlib.sha256(b.tobytes()).hexdigest()}
    if not equal:
        diff = np.abs(a.astype(np.int32) - b.astype(np.int32))
        mse = float((diff.astype(np.float64) ** 2).mean())
        out.update({
            "max_abs_channel_diff": int(diff.max()),
            "mean_abs_channel_diff": float(diff.mean()),
            "mismatch_pixel_fraction": float((diff.any(axis=-1) if diff.ndim == 3
                                              else diff > 0).mean()),
            "psnr_db": (float("inf") if mse == 0
                        else 10.0 * math.log10(255.0 * 255.0 / mse)),
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    a_root, b_root, out = _abs(args.a), _abs(args.b), _abs(args.out)
    os.makedirs(out, exist_ok=True)

    a_rec, b_rec = load_records(a_root), load_records(b_root)
    ids = sorted(set(a_rec) & set(b_rec))
    if not ids:
        raise SystemExit("공통 usable_id 가 없습니다")

    rows = []
    for usable_id in ids:
        stem = "f%04d" % usable_id
        ra, rb = a_rec[usable_id], b_rec[usable_id]
        label_a = os.path.join(a_root, "labels", stem + "_label.json")
        label_b = os.path.join(b_root, "labels", stem + "_label.json")
        la = json.load(io.open(label_a, encoding="utf-8"))
        lb = json.load(io.open(label_b, encoding="utf-8"))
        rgb = compare_images(os.path.join(a_root, "rgb", stem + "_rgb.png"),
                             os.path.join(b_root, "rgb", stem + "_rgb.png"))
        amodal = compare_images(
            os.path.join(a_root, "mask_amodal", stem + ".png"),
            os.path.join(b_root, "mask_amodal", stem + ".png"))
        visible = compare_images(
            os.path.join(a_root, "mask_visible", stem + ".png"),
            os.path.join(b_root, "mask_visible", stem + ".png"))
        rows.append({
            "usable_id": usable_id,
            "diagnostic_mode": ra.get("diagnostic_mode"),
            "proposal_index_a": ra.get("proposal_index"),
            "proposal_index_b": rb.get("proposal_index"),
            "frame_seed_a": ra.get("seed"), "frame_seed_b": rb.get("seed"),
            "record_match": sha(canon(ra)) == sha(canon(rb)),
            "label_match": sha(canon(la)) == sha(canon(lb)),
            "rgb_identical": rgb.get("identical"),
            "rgb_max_abs_diff": rgb.get("max_abs_channel_diff"),
            "rgb_mean_abs_diff": rgb.get("mean_abs_channel_diff"),
            "rgb_mismatch_fraction": rgb.get("mismatch_pixel_fraction"),
            "rgb_psnr_db": rgb.get("psnr_db"),
            "amodal_identical": amodal.get("identical"),
            "visible_identical": visible.get("identical"),
        })

    with io.open(os.path.join(out, "dataset_quality_probe10.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    verdict = {
        "n": len(rows),
        "PLAN_REPRODUCIBLE_EXACT": all(
            r["proposal_index_a"] == r["proposal_index_b"]
            and r["frame_seed_a"] == r["frame_seed_b"] for r in rows),
        "RECORD_REPRODUCIBLE_EXACT": all(r["record_match"] for r in rows),
        "LABEL_REPRODUCIBLE_EXACT": all(r["label_match"] for r in rows),
        "PUBLIC_MASK_REPRODUCIBLE_EXACT": all(
            r["amodal_identical"] and r["visible_identical"] for r in rows),
        "DATASET_QUALITY_RGB_BITWISE_REPRODUCIBLE_SAME_MACHINE": all(
            r["rgb_identical"] for r in rows),
        "CROSS_MACHINE": "UNTESTED",
    }
    io.open(os.path.join(out, "dataset_quality_probe10.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps({"verdict": verdict, "rows": rows}, indent=2,
                   ensure_ascii=False, default=str) + "\n")
    for key, value in verdict.items():
        print("  %-52s %s" % (key, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
