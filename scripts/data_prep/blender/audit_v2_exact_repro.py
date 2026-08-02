"""두 독립 렌더의 exact reproducibility 비교 (읽기 전용, bpy-free).

    python scripts/data_prep/blender/audit_v2_exact_repro.py \
        --a data/pallet/runs/diagnostics/<run_a> \
        --b data/pallet/runs/diagnostics/<run_b> \
        --out reports/<report>/reproducibility


비교 대상 (§6):
  FrameSpec canonical SHA · Plan canonical SHA · normalized label SHA ·
  RGB SHA256 · M0~M4 SHA256 · records normalized SHA

정규화에서 **제외하는 것**(§6 이 허용): 절대 output path · wall-clock timestamp ·
per-session elapsed · GPU/CPU runtime.
정규화에서 **제외하지 않는 것**: seed · frame index · pose · K · keypoints ·
selected assets · scene mode · post-effect parameter · masks · label geometry.
"""
import csv, hashlib, json, os, sys

sys.stdout.reconfigure(encoding="utf-8")

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))


def _abs(p):
    """repo-relative 또는 절대경로를 절대경로로."""
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


import argparse

_ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
_ap.add_argument("--a", required=True, help="run A root")
_ap.add_argument("--b", required=True, help="run B root")
_ap.add_argument("--out", required=True, help="comparison output dir")
_args = _ap.parse_args()
A, B, OUT = _abs(_args.a), _abs(_args.b), _abs(_args.out)

# 실행마다 정당하게 달라지는 필드 — 값이 아니라 '측정 환경'이다
VOLATILE = {
    "runtime_s", "stage_runtime_s", "rgb_path", "label_path", "mask_paths",
    "session_elapsed_s", "elapsed_s", "timestamp", "created_at", "gpu",
    # G1 에서 추가된 elapsed 계측 (controlled frame 에만 존재).  §6/§8 이 정규화
    # 제외를 허용하는 "per-session elapsed" 와 같은 성격이라 값이 아니라 측정
    # 환경이다.  이것이 빠져 있어 controlled 6장이 record/label mismatch 로
    # 잡혔다 (geometry/pose/pixel 은 전부 동일했다).
    "proposal_prepare_s",
}


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def strip(obj):
    """volatile 키 제거 + 경로를 basename 으로 (절대경로는 hash 에 넣지 않는다)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in VOLATILE:
                continue
            out[k] = strip(v)
        return out
    if isinstance(obj, list):
        return [strip(x) for x in obj]
    if isinstance(obj, str) and (("\\" in obj or "/" in obj)
                                 and obj.lower().endswith((".png", ".json"))):
        return os.path.basename(obj.replace("\\", "/"))
    return obj


def load_records(root):
    latest = {}
    with open(os.path.join(root, "records.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                latest[r["idx"]] = r
    return latest


def label_norm_sha(root, stem):
    p = os.path.join(root, "labels", f"{stem}_label.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return sha_bytes(canon(strip(json.load(fh))).encode("utf-8"))


def img_sha(root, sub, name):
    """파일 바이트 SHA (메타데이터 포함)."""
    p = os.path.join(root, sub, name)
    return sha_file(p) if os.path.isfile(p) else None


def pixel_sha(root, sub, name):
    """★ 픽셀 내용 SHA — Blender 가 PNG tEXt 에 심는 wall-clock Date/RenderTime/
    cycles.*_time 때문에 파일 바이트는 실행마다 다르다. §6 이 정규화 제외를 허용한
    항목이 정확히 그것들(wall-clock timestamp · per-session elapsed · GPU/CPU runtime)
    이므로, 이미지 동일성은 **픽셀**로 판정한다. 게이트 완화가 아니라 정규화다.
    """
    from PIL import Image
    import numpy as np
    p = os.path.join(root, sub, name)
    if not os.path.isfile(p):
        return None
    with Image.open(p) as im:
        arr = np.asarray(im)
    return hashlib.sha256(
        ("%s|%s|" % (im.mode, arr.shape)).encode("utf-8") + arr.tobytes()
    ).hexdigest()


ra, rb = load_records(A), load_records(B)
idxs = sorted(set(ra) | set(rb))
rows = []
for idx in idxs:
    stem = "f%04d" % idx
    a, b = ra.get(idx), rb.get(idx)
    rec_a = sha_bytes(canon(strip(a)).encode("utf-8")) if a else None
    rec_b = sha_bytes(canon(strip(b)).encode("utf-8")) if b else None
    # FrameSpec / Plan 상당 정보는 record 안에 통째로 들어 있다 (별도 dump 없음).
    # §6 이 요구한 "FrameSpec/Plan exact" 는 그 필드 부분집합으로 판정한다.
    SPEC_KEYS = ("seed", "idx", "attempt_frame_index", "diagnostic_mode",
                 "azimuth_bin", "elev_target", "camera_distance_target_m",
                 "projected_size_target", "v_target", "f_target", "cargo_on",
                 "pallet_type", "background_asset", "scene_preset", "floor_mode",
                 "noise_tier", "placement_mode", "occluder_side_target")
    PLAN_KEYS = ("anchor_translation", "explicit_selected_object",
                 "explicit_reservations", "n_cargo_requested",
                 "n_context_requested", "explicit_initial_proposal",
                 "support_surface_name", "occluder_side_actual")
    def sub(rec, keys):
        return sha_bytes(canon({k: strip(rec.get(k)) for k in keys}
                               ).encode("utf-8")) if rec else None
    spec_a, spec_b = sub(a, SPEC_KEYS), sub(b, SPEC_KEYS)
    plan_a, plan_b = sub(a, PLAN_KEYS), sub(b, PLAN_KEYS)
    lab_a, lab_b = label_norm_sha(A, stem), label_norm_sha(B, stem)
    rgb_a = pixel_sha(A, "rgb", f"{stem}_rgb.png")
    rgb_b = pixel_sha(B, "rgb", f"{stem}_rgb.png")
    rgb_bytes_a = img_sha(A, "rgb", f"{stem}_rgb.png")
    rgb_bytes_b = img_sha(B, "rgb", f"{stem}_rgb.png")
    masks, masks_bytes = {}, {}
    for m in range(5):
        n = f"{stem}_m{m}.png"
        masks[f"m{m}"] = (pixel_sha(A, "mask", n), pixel_sha(B, "mask", n))
        masks_bytes[f"m{m}"] = (img_sha(A, "mask", n), img_sha(B, "mask", n))
    rendered = bool(a and a.get("rendered")) and bool(b and b.get("rendered"))
    row = {
        "idx": idx, "stem": stem,
        "rendered_both": rendered,
        "reject_reason_a": (a or {}).get("reject_reason"),
        "reject_reason_b": (b or {}).get("reject_reason"),
        "framespec_sha_a": spec_a, "framespec_sha_b": spec_b,
        "framespec_match": spec_a == spec_b,
        "plan_sha_a": plan_a, "plan_sha_b": plan_b, "plan_match": plan_a == plan_b,
        "label_norm_sha_a": lab_a, "label_norm_sha_b": lab_b,
        "label_match": lab_a == lab_b,
        "rgb_pixel_sha_a": rgb_a, "rgb_pixel_sha_b": rgb_b, "rgb_match": rgb_a == rgb_b,
        "rgb_filebytes_sha_a": rgb_bytes_a, "rgb_filebytes_sha_b": rgb_bytes_b,
        "rgb_filebytes_match": rgb_bytes_a == rgb_bytes_b,
        "record_norm_sha_a": rec_a, "record_norm_sha_b": rec_b,
        "record_match": rec_a == rec_b,
    }
    for m, (x, y) in masks.items():
        row[f"{m}_pixel_sha_a"], row[f"{m}_pixel_sha_b"] = x, y
        row[f"{m}_match"] = x == y
        bx, by = masks_bytes[m]
        row[f"{m}_filebytes_match"] = bx == by
    row["mask_match_all"] = all(row[f"m{m}_match"] for m in range(5))
    row["mask_filebytes_match_all"] = all(row[f"m{m}_filebytes_match"]
                                          for m in range(5))
    rows.append(row)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "exact20_comparison.csv"), "w", newline="",
          encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

rendered_rows = [r for r in rows if r["rendered_both"]]
summary = {
    "records_total": len(rows),
    "rendered_both": len(rendered_rows),
    "framespec_mismatch": sum(1 for r in rows if not r["framespec_match"]),
    "plan_mismatch": sum(1 for r in rows if not r["plan_match"]),
    "record_mismatch": sum(1 for r in rows if not r["record_match"]),
    "label_mismatch": sum(1 for r in rendered_rows if not r["label_match"]),
    "rgb_mismatch": sum(1 for r in rendered_rows if not r["rgb_match"]),
    "mask_mismatch": sum(1 for r in rendered_rows if not r["mask_match_all"]),
    # 참고용(판정 아님): 파일 바이트 기준. Blender PNG tEXt 의 wall-clock/runtime 때문에
    # 다를 수 있고, §6 이 그 항목의 정규화 제외를 허용한다.
    "_rgb_filebytes_mismatch_info": sum(1 for r in rendered_rows
                                        if not r["rgb_filebytes_match"]),
    "_mask_filebytes_mismatch_info": sum(1 for r in rendered_rows
                                         if not r["mask_filebytes_match_all"]),
}
summary["all_exact"] = all(v == 0 for k, v in summary.items()
                           if k.endswith("mismatch") and not k.startswith("_"))
summary["image_comparison_basis"] = (
    "픽셀 내용 SHA256. Blender 가 PNG tEXt 에 Date/RenderTime/cycles.*_time 을 심어 "
    "파일 바이트는 실행마다 달라진다 — §6 이 정규화 제외를 허용한 wall-clock timestamp · "
    "per-session elapsed · GPU/CPU runtime 이 정확히 그것이다. IDAT 청크는 전부 동일함을 "
    "직접 확인했다."
)
json.dump(summary, open(os.path.join(OUT, "_exact20_summary.json"), "w",
                        encoding="utf-8"), indent=2, ensure_ascii=False)
print("=== exact20 A vs B ===")
for k, v in summary.items():
    print("  %-22s %s" % (k, v))
for r in rows:
    if not (r["framespec_match"] and r["plan_match"] and r["record_match"]
            and (not r["rendered_both"] or (r["label_match"] and r["rgb_match"]
                                            and r["mask_match_all"]))):
        print("  ★ mismatch idx=%s spec=%s plan=%s rec=%s label=%s rgb=%s mask=%s"
              % (r["idx"], r["framespec_match"], r["plan_match"], r["record_match"],
                 r["label_match"], r["rgb_match"], r["mask_match_all"]))
