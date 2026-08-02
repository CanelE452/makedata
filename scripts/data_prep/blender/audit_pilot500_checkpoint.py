"""pilot500 checkpoint 보완 감사 (읽기 전용, bpy-free).

`audit_v2_mode_semantics.py` 가 mode/semantics/무결성/controlled 효율을 덮으므로
여기서는 그 도구가 다루지 않는 항목만 본다.

  - constraint rescue trigger / mode 절대값 (A==B 가 아니라 전부 off·false)
  - context no-regression
  - public mask schema (M1~M3 · 임시 holdout · occlusion_decomposition_available)
  - reprojection median/p95/max
  - 해상도 · noise/blur tier 분포
  - mode 별 · stage 별 runtime
  - disk (RGB/label/mask/overlay 평균·p95 bytes) + 500장 예상
"""
import argparse
import collections
import csv
import io
import json
import os
import statistics as st
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
MODES = ("clean-static", "cargo-only", "context-rich", "controlled-occlusion")


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def q(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))] if v else None


def sizes(d):
    if not os.path.isdir(d):
        return []
    return [os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", type=int, required=True)
    ap.add_argument("--target-total", type=int, default=500)
    a = ap.parse_args(argv)
    root, out = _abs(a.dir), _abs(a.out)
    os.makedirs(out, exist_ok=True)

    recs = {}
    for line in io.open(os.path.join(root, "records.jsonl"), encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            recs[r["idx"]] = r
    ids = sorted(recs)
    rows = [recs[i] for i in ids]

    # ---- rescue 절대값 (§6) --------------------------------------------
    ctrl = [r for r in rows if r.get("diagnostic_mode") == "controlled-occlusion"]
    rescue_trig = [r["idx"] for r in rows if r.get("rescue_triggered")]
    rescue_modes = collections.Counter(str(r.get("constraint_rescue_mode"))
                                       for r in ctrl)
    rescue_ok = (not rescue_trig
                 and set(rescue_modes) <= {"off"})

    # ---- context no-regression (§6) ------------------------------------
    # context no-regression 은 record 에 boolean 으로 저장되지 않는다 (solver 내부
    # callback 이다).  대신 **context 배치 이후 최종 측정값**으로 정의한다 —
    # explicit occluder 가 최종 프레임에서 여전히 보이고 side 가 맞는가,
    # 그리고 explicit 실패로 context 를 건너뛰지 않았는가.
    noreg_fail, noreg_detail = 0, []
    for r in ctrl:
        vis = r.get("explicit_occluder_visible_pixels")
        side = r.get("occluder_side_match")
        skipped = bool(r.get("context_skipped_due_to_explicit_failure"))
        ok = bool(vis and int(vis) > 0) and bool(side) and not skipped
        if not ok:
            noreg_fail += 1
        noreg_detail.append({"idx": r["idx"], "visible_px": vis,
                             "side_match": side, "context_skipped": skipped,
                             "ok": ok})
    noreg_unknown = sum(1 for d in noreg_detail
                        if d["visible_px"] is None or d["side_match"] is None)

    # ---- public mask schema (§7) ---------------------------------------
    dirs = sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d)))
    forbidden = [d for d in dirs
                 if d not in ("rgb", "labels", "mask_amodal", "mask_visible",
                              "overlay", "logs")]
    session = json.load(io.open(os.path.join(root, "progress.json"),
                                encoding="utf-8"))
    occ_decomp = {bool(session.get("occlusion_decomposition_available"))}
    schema = {
        "directories": dirs,
        "forbidden_dirs": forbidden,
        "mask_amodal": len(sizes(os.path.join(root, "mask_amodal"))),
        "mask_visible": len(sizes(os.path.join(root, "mask_visible"))),
        "m1_m2_m3_dirs": [d for d in dirs if d.startswith("mask_")
                          and d not in ("mask_amodal", "mask_visible")],
        "temporary_holdout_files": [f for f in os.listdir(root)
                                    if "holdout" in f.lower()
                                    or "_tmp" in f.lower()],
        "occlusion_decomposition_available_values": sorted(occ_decomp),
        # mask_profile / occlusion_decomposition_available 은 **session 레벨**
        # 필드다 (record 아님) — progress.json 을 정본으로 읽는다.
        "mask_profile_values": [str(session.get("mask_profile"))],
        "render_profile": session.get("render_profile"),
    }
    schema["occlusion_decomposition_available_values"] = [
        bool(session.get("occlusion_decomposition_available"))]
    schema["schema_ok"] = bool(
        not forbidden and not schema["m1_m2_m3_dirs"]
        and not schema["temporary_holdout_files"]
        and occ_decomp == {False}
        and schema["mask_profile_values"] == ["public"])

    # ---- reprojection · 해상도 · tier (§7) -----------------------------
    # reprojection 은 record 에 없다 — audit_v2_mode_semantics 가 label 의
    # projected_cuboid 와 K·pose 재투영을 비교해 계산한 값을 정본으로 쓴다.
    reproj_src = os.path.join(out, "audit_summary.json")
    reproj_summary = (json.load(io.open(reproj_src, encoding="utf-8"))
                      .get("integrity", {}) if os.path.exists(reproj_src) else {})
    reproj = []
    # width/height 도 record 가 아니라 **label 의 camera_data** 에 있다.
    res = collections.Counter()
    for r in rows:
        lp = os.path.join(root, "labels", "f%04d_label.json" % r["idx"])
        if os.path.exists(lp):
            cam = json.load(io.open(lp, encoding="utf-8")).get("camera_data", {})
            res["%dx%d" % (cam.get("width", 0), cam.get("height", 0))] += 1
    tiers = collections.Counter(str(r.get("noise_tier")) for r in rows)
    blur = collections.Counter(str(r.get("gaussian_sigma")) for r in rows)

    # ---- runtime (§9) ---------------------------------------------------
    by_mode, stage_tot = collections.defaultdict(list), collections.defaultdict(float)
    for r in rows:
        if r.get("runtime_s") is not None:
            by_mode[r["diagnostic_mode"]].append(float(r["runtime_s"]))
        for k, v in (r.get("stage_runtime_s") or {}).items():
            stage_tot[k] += float(v or 0)
    runtime_rows = []
    for m in MODES:
        v = by_mode.get(m, [])
        if not v:
            continue
        runtime_rows.append({
            "mode": m, "n": len(v), "total_s": round(sum(v), 1),
            "mean_s": round(sum(v) / len(v), 1), "median_s": round(st.median(v), 1),
            "p90_s": round(q(v, .90), 1), "p95_s": round(q(v, .95), 1),
            "max_s": round(max(v), 1)})
    stage_rows = [{"stage": k, "total_s": round(v, 1)}
                  for k, v in sorted(stage_tot.items(), key=lambda kv: -kv[1])]

    # ---- disk (§9) ------------------------------------------------------
    disk = {}
    for sub in ("rgb", "labels", "mask_amodal", "mask_visible", "overlay"):
        s = sizes(os.path.join(root, sub))
        disk[sub] = {"files": len(s), "total_bytes": sum(s),
                     "mean_bytes": int(sum(s) / len(s)) if s else 0,
                     "p95_bytes": q(s, .95) or 0}
    per_frame = sum(d["mean_bytes"] for k, d in disk.items() if k != "overlay")
    disk["projection"] = {
        "per_frame_bytes_raw": per_frame,
        "per_frame_bytes_with_overlay": per_frame + disk["overlay"]["mean_bytes"],
        "target_total": a.target_total,
        "raw_total_mb": round(per_frame * a.target_total / 1e6, 1),
        "with_overlay_total_mb": round(
            (per_frame + disk["overlay"]["mean_bytes"]) * a.target_total / 1e6, 1)}

    for name, data, fields in (
            ("runtime_by_mode.csv", runtime_rows,
             ["mode", "n", "total_s", "mean_s", "median_s", "p90_s", "p95_s", "max_s"]),
            ("runtime_by_stage.csv", stage_rows, ["stage", "total_s"])):
        with io.open(os.path.join(out, name), "w", encoding="utf-8",
                     newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(data)

    for name, obj in (("mask_schema_audit.json", schema),
                      ("resolution_counts.json",
                       {"resolution": dict(res), "noise_tier": dict(tiers),
                        "gaussian_sigma": dict(blur)}),
                      ("disk_estimate.json", disk)):
        io.open(os.path.join(out, name), "w", encoding="utf-8",
                newline="\n").write(json.dumps(obj, indent=2,
                                               ensure_ascii=False) + "\n")

    with io.open(os.path.join(out, "context_no_regression_audit.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["idx", "mode", "explicit_visible_px", "side_match",
                    "context_skipped", "no_regression_ok"])
        for d in noreg_detail:
            w.writerow([d["idx"], "controlled-occlusion", d["visible_px"],
                        d["side_match"], d["context_skipped"], d["ok"]])

    gate = {
        "expected_usable": a.expect, "actual_usable": len(ids),
        "ids_contiguous": ids == list(range(len(ids))),
        "rescue_triggered_frames": rescue_trig,
        "rescue_mode_values_controlled": dict(rescue_modes),
        "rescue_off_confirmed": rescue_ok,
        "context_no_regression_fail": noreg_fail,
        "context_no_regression_unknown": noreg_unknown,
        "public_schema_ok": schema["schema_ok"],
        "reprojection_median_px": reproj_summary.get("reproj_median_px"),
        "reprojection_max_px": reproj_summary.get("reproj_max_px"),
        "reprojection_gate_px": reproj_summary.get("reproj_gate_px"),
        "reprojection_gate_pass": reproj_summary.get("reproj_gate_pass"),
        "reprojection_source": "audit_v2_mode_semantics (label 재투영 계산)",
        "resolution_counts": dict(res),
    }
    gate["SUPPLEMENTARY_PASS"] = bool(
        gate["actual_usable"] == a.expect and gate["ids_contiguous"]
        and rescue_ok and noreg_fail == 0 and schema["schema_ok"])
    io.open(os.path.join(out, "supplementary_gate.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(gate, indent=2,
                                           ensure_ascii=False) + "\n")

    print("usable %d/%d · IDs contiguous %s"
          % (len(ids), a.expect, gate["ids_contiguous"]))
    print("rescue triggered frames %s · controlled mode 값 %s -> off 확인 %s"
          % (rescue_trig or 0, dict(rescue_modes), rescue_ok))
    print("context no-regression: fail %d · unknown %d (controlled %d건)"
          % (noreg_fail, noreg_unknown, len(ctrl)))
    print("public schema ok %s · dirs %s" % (schema["schema_ok"], dirs))
    print("  M1~M3 dir %s · 임시 holdout %s · occ_decomp %s · mask_profile %s"
          % (schema["m1_m2_m3_dirs"] or 0, schema["temporary_holdout_files"] or 0,
             schema["occlusion_decomposition_available_values"],
             schema["mask_profile_values"]))
    print("reprojection (mode_semantics 감사 계산값) median %s · max %s px"
          % (reproj_summary.get("reproj_median_px"),
             reproj_summary.get("reproj_max_px")))
    print("해상도", dict(res), "· noise tier", dict(tiers))
    print()
    print("%-24s %4s %9s %9s %9s %9s" % ("mode", "n", "합계s", "중앙s", "p95s", "최대s"))
    for r in runtime_rows:
        print("%-24s %4d %9.1f %9.1f %9.1f %9.1f"
              % (r["mode"], r["n"], r["total_s"], r["median_s"], r["p95_s"],
                 r["max_s"]))
    print()
    print("stage 합계:", {r["stage"]: r["total_s"] for r in stage_rows})
    print("disk/frame raw %.2f MB · with overlay %.2f MB"
          % (per_frame / 1e6, disk["projection"]["per_frame_bytes_with_overlay"] / 1e6))
    print("  %d장 예상: raw %.1f MB · overlay 포함 %.1f MB"
          % (a.target_total, disk["projection"]["raw_total_mb"],
             disk["projection"]["with_overlay_total_mb"]))
    print()
    print("SUPPLEMENTARY_PASS =", gate["SUPPLEMENTARY_PASS"])
    return 0 if gate["SUPPLEMENTARY_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
