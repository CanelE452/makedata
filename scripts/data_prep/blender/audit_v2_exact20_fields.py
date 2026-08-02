"""exact20 A/B 항목별 비교 (§8) — 읽기 전용, bpy-free.

`audit_v2_exact_repro.py` 가 canonical SHA·decoded pixel 을 비교하고,
이 도구는 §8 이 이름으로 지정한 항목을 **하나씩** 대조한다.
추가로 `constraint rescue trigger` 는 A==B 가 아니라 **양쪽 모두 false** 여야 한다
(frozen config 가 실제 run 에 반영됐는지 확인).
"""
import argparse
import collections
import csv
import io
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

# §8 "정규화 제외 가능" — 값이 아니라 측정 환경이다
VOLATILE = {
    "runtime_s", "stage_runtime_s", "session_elapsed_s", "elapsed_s",
    "timestamp", "created_at", "gpu", "rgb_path", "label_path", "mask_paths",
    "proposal_prepare_s", "fine_runtime_s", "rescue_runtime_s",
    "lowres_render_count", "replay_wall_s", "frame_s",
}

# §8 "제외 금지" — 반드시 일치해야 하는 항목
REQUIRED_FIELDS = [
    ("mode schedule", "diagnostic_mode"),
    ("proposal index sequence", "proposal_index"),
    ("accepted/rejected outcome", "usable"),
    ("normalized rejection reason", "usable_reject_reasons"),
    ("attempt seed", "attempt_seed"),
    ("target side", "occluder_side_target"),
    ("explicit target metric", "f_explicit_target"),
    ("explicit actual metric", "f_explicit_actual_lowres"),
    ("explicit error", "explicit_abs_error_lowres"),
    ("explicit metrics available", "explicit_metrics_available"),
    ("side match", "occluder_side_match"),
    ("target-seed unique", "target_seed_unique_count"),
    ("target-seed free used", "target_seed_free_used"),
    ("target-seed paid used", "target_seed_paid_used"),
    ("fine triggered", "fine_triggered"),
    ("fine eval count", "fine_eval_count"),
    ("fine won", "fine_won"),
    ("mode semantics pass", "mode_semantics_pass"),
    ("V_vis", "V_vis"),
    ("projected size", "projected_size_actual"),
    ("camera distance", "camera_distance_actual_m"),
    ("elevation", "elev_actual"),
    ("realization attempts", "realization_attempt_count"),
    ("prefilter rejects", "prefilter_reject_count"),
    ("mask m0 area", "mask_m0_area_px"),
    ("visible keypoints", "visible_kp_count"),
]


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def load(root):
    latest = {}
    for line in io.open(os.path.join(_abs(root), "records.jsonl"),
                        encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            latest[r["idx"]] = r
    return latest


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = _abs(a.out)
    os.makedirs(out, exist_ok=True)

    ra, rb = load(a.a), load(a.b)
    idxs = sorted(set(ra) | set(rb))

    rows, field_mismatch = [], collections.Counter()
    for idx in idxs:
        x, y = ra.get(idx), rb.get(idx)
        row = {"idx": idx, "in_a": x is not None, "in_b": y is not None,
               "mode": (x or y or {}).get("diagnostic_mode")}
        if x is None or y is None:
            row["mismatch_fields"] = "MISSING_RECORD"
            field_mismatch["MISSING_RECORD"] += 1
            rows.append(row)
            continue
        bad = []
        for _label, key in REQUIRED_FIELDS:
            if canon(x.get(key)) != canon(y.get(key)):
                bad.append(key)
                field_mismatch[key] += 1
        nx = {k: v for k, v in x.items() if k not in VOLATILE}
        ny = {k: v for k, v in y.items() if k not in VOLATILE}
        extra = sorted(k for k in set(nx) | set(ny)
                       if canon(nx.get(k)) != canon(ny.get(k)))
        for k in extra:
            if k not in bad:
                field_mismatch[k] += 1
        row["mismatch_fields"] = "|".join(sorted(set(bad) | set(extra)))
        row["rescue_triggered_a"] = bool(x.get("rescue_triggered"))
        row["rescue_triggered_b"] = bool(y.get("rescue_triggered"))
        row["constraint_rescue_mode_a"] = x.get("constraint_rescue_mode")
        row["constraint_rescue_mode_b"] = y.get("constraint_rescue_mode")
        rows.append(row)

    with io.open(os.path.join(out, "exact20_comparison.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    rescue_on = [r for r in rows
                 if r.get("rescue_triggered_a") or r.get("rescue_triggered_b")]
    modes_a = collections.Counter(ra[i].get("diagnostic_mode") for i in ra)
    modes_b = collections.Counter(rb[i].get("diagnostic_mode") for i in rb)
    expected_modes = {"clean-static": 4, "cargo-only": 4, "context-rich": 6,
                      "controlled-occlusion": 6}
    summary = {
        "records_a": len(ra), "records_b": len(rb), "compared": len(idxs),
        "field_mismatch_total": sum(field_mismatch.values()),
        "field_mismatch_by_key": dict(field_mismatch),
        "frames_with_mismatch": sum(1 for r in rows if r["mismatch_fields"]),
        "mode_counts_a": dict(modes_a), "mode_counts_b": dict(modes_b),
        "mode_counts_expected": expected_modes,
        "mode_schedule_ok": (dict(modes_a) == expected_modes
                             and dict(modes_b) == expected_modes),
        "constraint_rescue_triggered_frames": len(rescue_on),
        "constraint_rescue_off_confirmed": len(rescue_on) == 0,
        "constraint_rescue_mode_values": sorted(
            str(v) for v in ({r.get("constraint_rescue_mode_a") for r in rows}
                             | {r.get("constraint_rescue_mode_b") for r in rows})),
    }
    summary["FIELD_COMPARISON_PASS"] = bool(
        summary["field_mismatch_total"] == 0
        and summary["records_a"] == summary["records_b"] == 20
        and summary["mode_schedule_ok"]
        and summary["constraint_rescue_off_confirmed"])
    io.open(os.path.join(out, "exact20_fields_summary.json"), "w",
            encoding="utf-8", newline="\n").write(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    print("records A %d · B %d · compared %d" % (len(ra), len(rb), len(idxs)))
    print("field mismatch total %d · frames with mismatch %d"
          % (summary["field_mismatch_total"], summary["frames_with_mismatch"]))
    for k, v in field_mismatch.most_common(15):
        print("    %-42s %d" % (k, v))
    print("mode counts A %s" % dict(modes_a))
    print("mode counts B %s" % dict(modes_b))
    print("mode schedule ok:", summary["mode_schedule_ok"])
    print("constraint rescue mode values:",
          summary["constraint_rescue_mode_values"])
    print("constraint rescue triggered frames: %d (0 이어야 함)"
          % summary["constraint_rescue_triggered_frames"])
    print("FIELD_COMPARISON_PASS =", summary["FIELD_COMPARISON_PASS"])
    return 0 if summary["FIELD_COMPARISON_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
