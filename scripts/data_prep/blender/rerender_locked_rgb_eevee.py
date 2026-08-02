"""locked source Plan 을 그대로 재현하고 **최종 RGB 만** EEVEE 로 다시 렌더한다.

    blender -b <scene> --python scripts/data_prep/blender/rerender_locked_rgb_eevee.py -- \
        --source data/pallet/runs/diagnostics/v2_mode_semantics_smoke100b_seed7000_public \
        --out    data/pallet/runs/diagnostics/v2_eevee_renderonly100_from_smoke100b \
        --limit 8

핵심 계약
  - 배치는 **재추첨하지 않는다**.  `stage_seeds = derive_stage_seeds(frame_seed)` 이므로
    같은 (seed, proposal_index) 로 realize 하면 배치가 bitwise 동일하다 (exact20 로 입증).
  - solver 의 저해상도 holdout 렌더는 **배치 판정에 쓰이므로 엔진을 바꾸지 않는다**.
    엔진 교체는 오직 최종 RGB 1회에만 적용한다.
  - label / public mask 는 다시 계산하지 않고 source 에서 copy2 후 SHA256 대조한다.
  - production default (RENDER_PROFILES, run_v2_scene_logic) 는 건드리지 않는다.
"""
import argparse
import hashlib
import io
import json
import os
import random
import shutil
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import run_v2_scene_logic as R  # noqa: E402
import v2_pipeline as vp  # noqa: E402
import v2_realize as vr  # noqa: E402

EEVEE_PROFILE = {
    "name": "EEVEE_RENDERONLY_32",
    "samples": 32,
}


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def eevee_engine():
    items = [i.identifier for i in
             bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    for want in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        if want in items:
            return want, items
    raise RuntimeError("EEVEE engine enum 없음: %s" % items)


def eevee_capabilities(scene, engine):
    """실제 API 를 읽어 지원 property 만 기록한다 (이름 추측 금지)."""
    cap, ee = {}, getattr(scene, "eevee", None)
    for name in ("taa_render_samples", "taa_samples", "use_gtao", "gtao_distance",
                 "use_soft_shadows", "use_ssr", "use_ssr_refraction",
                 "use_shadow_high_bitdepth", "shadow_cube_size",
                 "shadow_cascade_size", "use_overscan", "overscan_size",
                 "use_bloom", "use_motion_blur", "use_raytracing",
                 "ray_tracing_method", "fast_gi_method"):
        cap[name] = (getattr(ee, name) if ee is not None and hasattr(ee, name)
                     else "N/A")
    cap["engine"] = engine
    cap["film_transparent"] = scene.render.film_transparent
    cap["use_motion_blur_render"] = scene.render.use_motion_blur
    cap["view_transform"] = scene.view_settings.view_transform
    cap["look"] = scene.view_settings.look
    cap["exposure"] = scene.view_settings.exposure
    cap["gamma"] = scene.view_settings.gamma
    return cap


def render_eevee(rs, rgb_path, engine, samples):
    """최종 RGB 1회만 EEVEE 로. 렌더 후 엔진을 원복한다."""
    scene = rs["scene"]
    prev_engine = scene.render.engine
    prev_path = scene.render.filepath
    scene.render.engine = engine
    ee = getattr(scene, "eevee", None)
    restored = {}
    if ee is not None:
        for attr in ("taa_render_samples",):
            if hasattr(ee, attr):
                restored[attr] = getattr(ee, attr)
                setattr(ee, attr, int(samples))
        for attr, val in (("use_gtao", True), ("use_soft_shadows", True),
                          ("use_ssr", True)):
            if hasattr(ee, attr):
                restored[attr] = getattr(ee, attr)
                setattr(ee, attr, val)
    scene.render.filepath = rgb_path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    t0 = time.perf_counter()
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        elapsed = time.perf_counter() - t0
        if ee is not None:
            for attr, val in restored.items():
                setattr(ee, attr, val)
        scene.render.engine = prev_engine
        scene.render.filepath = prev_path
    return elapsed


def transform_digest(rs):
    """현재 씬의 배치를 요약 — source 와 동일한지 검증할 지문."""
    parts = []
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if not obj.visible_get() and obj.hide_render:
            continue
        m = obj.matrix_world
        parts.append("%s|%s" % (obj.name, "|".join(
            "%.6f" % m[r][c] for r in range(4) for c in range(4))))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-ids", default=None,
                    help="쉼표로 구분한 usable id (smoke 용)")
    ap.add_argument("--samples", type=int, default=EEVEE_PROFILE["samples"])
    a = ap.parse_args(argv)
    src, out = _abs(a.source), _abs(a.out)
    for sub in ("rgb", "labels", "mask_amodal", "mask_visible"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    engine, all_engines = eevee_engine()
    scene = bpy.context.scene
    caps = eevee_capabilities(scene, engine)
    print("[EEVEE] engine=%s (available=%s)" % (engine, all_engines), flush=True)

    records = {}
    for line in io.open(os.path.join(src, "records.jsonl"), encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            records[r["idx"]] = r
    ids = sorted(records)
    if a.only_ids:
        want = {int(x) for x in a.only_ids.split(",")}
        ids = [i for i in ids if i in want]
    elif a.limit:
        ids = ids[:a.limit]

    # 데이터셋 seed 는 progress.json 이 정본이다 (record 의 seed 는 **프레임 seed**).
    session = json.load(io.open(os.path.join(src, "progress.json"), encoding="utf-8"))
    seed = int(session["seed"])
    need = {int(records[i]["proposal_index"]) for i in ids}
    print("[EEVEE] frames=%d seed=%d max_proposal=%d"
          % (len(ids), seed, max(need)), flush=True)

    vr.enable_gpu()
    assets = vp.load_assets()
    plans = {}
    for pidx, plan, _rej in R.iter_proposals(
            seed, assets, vp, placement_mode="constrained",
            max_proposals=max(need) + 1):
        if pidx in need and plan is not None:
            plans[pidx] = plan
        if len(plans) == len(need):
            break
    print("[EEVEE] plans restored %d/%d" % (len(plans), len(need)), flush=True)

    manifest_path = os.path.join(out, "render_manifest.json")
    done = {}
    if os.path.exists(manifest_path):
        done = {int(k): v for k, v in
                json.load(io.open(manifest_path, encoding="utf-8")).items()}

    rec_out = io.open(os.path.join(out, "records.jsonl"), "a", encoding="utf-8",
                      newline="\n")
    for n, idx in enumerate(ids):
        if idx in done:
            print("[EEVEE] skip %d (already rendered)" % idx, flush=True)
            continue
        src_rec = records[idx]
        pidx = int(src_rec["proposal_index"])
        plan = plans.get(pidx)
        if plan is None:
            print("[EEVEE] ! plan 없음 idx=%d proposal=%d" % (idx, pidx), flush=True)
            continue
        frame_seed = int(src_rec["frame_seed"]) if src_rec.get("frame_seed") \
            else int(src_rec["attempt_seed"])
        # ★ production 은 realize **직전에** 전역 RNG 를 프레임 seed 로 고정한다
        # (run_v2_scene_logic.py:1443-1445).  이 두 줄이 없으면 배치가 달라진다 —
        # 실측으로 0.596 m 어긋나는 것을 확인했다.
        random.seed(frame_seed)
        np.random.seed(frame_seed & 0xFFFFFFFF)
        t_setup = time.perf_counter()
        rs = vr.realize(plan, floor_mode=None, placement_mode="constrained",
                        diagnostic_mode=src_rec.get("diagnostic_mode"),
                        frame_seed=frame_seed)
        setup_s = time.perf_counter() - t_setup
        if rs is not None and rs.get("realize_ok") is False:
            rs = None
        if rs is None or "scene" not in rs:
            print("[EEVEE] ! realize 실패 idx=%d — 배치 재현 불가, 건너뜀"
                  % idx, flush=True)
            failed.append({"idx": idx, "mode": src_rec.get("diagnostic_mode"),
                           "reason": "realize_not_reproducible"})
            continue
        digest = transform_digest(rs)
        # ★ 배치가 source 와 실제로 같은지 **검증**한다 (가정 금지).
        src_lab = json.load(io.open(os.path.join(src, "labels",
                                                 "f%04d_label.json" % idx),
                                    encoding="utf-8"))
        src_cub = src_lab["objects"][0]["cuboid"]
        pal = bpy.data.objects.get(rs.get("pallet_name") or "")
        placement_err = None
        if pal is not None:
            import mathutils
            pts = [pal.matrix_world @ mathutils.Vector(c[:]) for c in pal.bound_box]
            mn = [min(p[i] for p in pts) for i in range(3)]
            mx = [max(p[i] for p in pts) for i in range(3)]
            s_mn = [min(c[i] for c in src_cub) for i in range(3)]
            s_mx = [max(c[i] for c in src_cub) for i in range(3)]
            placement_err = max(max(abs(mn[i] - s_mn[i]) for i in range(3)),
                                max(abs(mx[i] - s_mx[i]) for i in range(3)))
        if placement_err is None or placement_err > 1e-4:
            print("[EEVEE] ! 배치 불일치 idx=%d err=%s — 건너뜀"
                  % (idx, placement_err), flush=True)
            failed.append({"idx": idx, "mode": src_rec.get("diagnostic_mode"),
                           "reason": "placement_mismatch",
                           "placement_err_m": placement_err})
            continue
        rgb_path = os.path.join(out, "rgb", "f%04d_rgb.png" % idx)
        render_s = render_eevee(rs, rgb_path, engine, a.samples)
        t_w = time.perf_counter()
        copies = {}
        for sub, name in (("labels", "f%04d_label.json" % idx),
                          ("mask_amodal", "f%04d.png" % idx),
                          ("mask_visible", "f%04d.png" % idx)):
            s_p = os.path.join(src, sub, name)
            d_p = os.path.join(out, sub, name)
            shutil.copy2(s_p, d_p)
            copies[sub] = {"sha_src": sha256(s_p), "sha_dst": sha256(d_p)}
            copies[sub]["match"] = copies[sub]["sha_src"] == copies[sub]["sha_dst"]
        write_s = time.perf_counter() - t_w
        row = {"idx": idx, "mode": src_rec.get("diagnostic_mode"),
               "proposal_index": pidx, "frame_seed": frame_seed,
               "engine": engine, "samples": a.samples,
               "setup_s": round(setup_s, 4), "render_s": round(render_s, 4),
               "write_s": round(write_s, 4),
               "transform_digest": digest,
               "placement_max_err_m": placement_err,
               "source_rgb": os.path.join(src, "rgb", "f%04d_rgb.png" % idx),
               "eevee_rgb": rgb_path,
               "label_sha_match": copies["labels"]["match"],
               "amodal_sha_match": copies["mask_amodal"]["match"],
               "visible_sha_match": copies["mask_visible"]["match"]}
        done[idx] = row
        rec_out.write(json.dumps(row, ensure_ascii=False) + "\n")
        rec_out.flush()
        io.open(manifest_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps({str(k): v for k, v in done.items()}, indent=1,
                       ensure_ascii=False) + "\n")
        print("[EEVEE] %3d/%d idx=%d mode=%-22s setup %5.1fs render %5.2fs "
              "write %4.2fs sha %s"
              % (n + 1, len(ids), idx, row["mode"], setup_s, render_s, write_s,
                 all(copies[k]["match"] for k in copies)), flush=True)
    rec_out.close()
    io.open(os.path.join(out, "source_manifest.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(
                {"source": src, "seed": seed, "frames": ids,
                 "engine_capabilities": caps,
                 "profile": EEVEE_PROFILE}, indent=2, ensure_ascii=False) + "\n")
    io.open(os.path.join(out, "failed_frames.json"), "w", encoding="utf-8",
            newline="\n").write(
                json.dumps(failed, indent=2, ensure_ascii=False) + "\n")
    print("[EEVEE] DONE rendered=%d failed=%d -> %s"
          % (len(done), len(failed), out), flush=True)
    for f in failed:
        print("   FAILED idx=%(idx)s mode=%(mode)s reason=%(reason)s" % f, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
