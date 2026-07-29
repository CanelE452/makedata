"""production `.blend` 의 외부경로를 감사하고, **원본은 건드리지 않은 채** portable
candidate 를 만드는 도구 (Stage 2-C1).

Blender 내장 Python 에서 돈다:

    blender -b <열 .blend> --python scripts/data_prep/blender/manage_blend_external_paths.py -- \
        --audit --source-blend <source> --report-dir <dir>

모드
  --audit             현재 열린 blend 의 path-bearing datablock 을 전수 덤프. 저장하지 않는다.
  --plan              audit + 절대경로 -> 상대경로 매핑 계획 + 누락 datablock 판정. 저장하지 않는다.
  --apply-candidate   **candidate 를 연 상태에서만** 계획을 적용하고 저장한다.
  --verify            현재 열린 blend 를 감사하고 기준 structure 와 비교한다. 저장하지 않는다.
  --emit-target-manifest
                      이동 **전에** 실행한다. 상대경로 문자열이 아니라 그것이 지금 가리키는
                      **실제 파일의 정체(절대경로 + SHA256)** 를 고정해 CSV 로 남긴다.
                      폴더가 옮겨지면 문자열은 의미를 잃지만 파일 정체는 남는다.
  --rebase-candidate  이동 **후에** candidate 를 연 상태에서 실행한다. target manifest 의
                      파일 정체를 --root-map 으로 새 위치에 재대응시키고, candidate 디렉토리
                      기준 상대경로를 다시 계산해 적용한다. 문자열을 하드코딩하지 않는다.

안전 규약 (코드로 강제)
  - source 와 candidate 가 같은 경로면 즉시 실패.
  - `--apply-candidate` 는 `bpy.data.filepath` 가 candidate 일 때만 동작한다.
    source 를 연 상태에서는 저장 계열 API 를 아예 호출하지 않는다.
  - pack / unpack / make_paths_relative / make_paths_absolute 전체 호출 없음.
    개별 datablock 의 `filepath` 만 명시적 계획에 따라 바꾼다.
  - 실행 전후로 source SHA256 을 재계산해 다르면 실패.
  - 계획에 없는 datablock 이 바뀌었으면 저장 전에 실패.
  - strict 모드에서 절대경로/사용자별 경로가 하나라도 남으면 저장하지 않는다.
"""

import argparse
import csv
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import bpy  # noqa: E402

import blend_path_utils as U  # noqa: E402


# `.blend` 안에서 외부 파일을 물고 있을 수 있는 datablock 컬렉션.
# 이름은 bpy.data 의 속성명이고, 없는 빌드에서도 죽지 않도록 getattr 로 접근한다.
PATH_BEARING_COLLECTIONS = (
    "images",
    "libraries",
    "movieclips",
    "fonts",
    "cache_files",
    "sounds",
    "volumes",
    "texts",
)

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


# --------------------------------------------------------------------- 유틸
def _blend_is_compressed(path):
    """저장 시 원본과 같은 압축 방식을 쓰기 위해 헤더로 판별한다."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == ZSTD_MAGIC
    except OSError:
        return False


def _blend_dir():
    return os.path.dirname(os.path.abspath(bpy.data.filepath))


def _abspath(raw):
    """`bpy.path.abspath` 를 쓰되 실패하면 순수 계산으로 대체한다."""
    text = str(raw or "")
    if not text:
        return ""
    try:
        return os.path.abspath(bpy.path.abspath(text))
    except Exception:
        return U.resolve_blend_relative(text, _blend_dir())


def _is_packed(datablock):
    packed = getattr(datablock, "packed_file", None)
    if packed is not None:
        return True
    files = getattr(datablock, "packed_files", None)
    return bool(files) if files is not None else False


def _source_kind(datablock):
    """image 의 source(FILE/GENERATED/...) 처럼 종류가 있으면 그대로 남긴다."""
    return str(getattr(datablock, "source", "") or "")


# ------------------------------------------------------------------ 참조 추적
def _image_referrers():
    """image datablock -> 그것을 참조하는 node/owner 목록."""
    refs = {}

    def add(image, owner):
        if image is None:
            return
        refs.setdefault(image.name, []).append(owner)

    def walk_tree(tree, owner):
        if tree is None:
            return
        for node in tree.nodes:
            img = getattr(node, "image", None)
            if img is not None:
                add(img, "%s/%s" % (owner, node.name))

    for mat in bpy.data.materials:
        walk_tree(getattr(mat, "node_tree", None), "material:%s" % mat.name)
    for world in bpy.data.worlds:
        walk_tree(getattr(world, "node_tree", None), "world:%s" % world.name)
    for group in bpy.data.node_groups:
        walk_tree(group, "nodegroup:%s" % group.name)
    for scene in bpy.data.scenes:
        if getattr(scene, "use_nodes", False):
            walk_tree(getattr(scene, "node_tree", None), "compositor:%s" % scene.name)
    for tex in bpy.data.textures:
        img = getattr(tex, "image", None)
        if img is not None:
            add(img, "texture:%s" % tex.name)
    for brush in bpy.data.brushes:
        for attr in ("texture", "mask_texture"):
            tex = getattr(brush, attr, None)
            img = getattr(tex, "image", None) if tex is not None else None
            if img is not None:
                add(img, "brush:%s.%s" % (brush.name, attr))
    return refs


def _modifier_cache_paths():
    """modifier / simulation cache 가 들고 있는 외부 경로."""
    rows = []
    for obj in bpy.data.objects:
        for mod in getattr(obj, "modifiers", []) or []:
            for attr in ("filepath", "cache_file"):
                value = getattr(mod, attr, None)
                if value is None:
                    continue
                raw = value if isinstance(value, str) else getattr(value, "filepath", None)
                if not raw:
                    continue
                rows.append({
                    "type": "modifier",
                    "name": "%s/%s.%s" % (obj.name, mod.name, attr),
                    "users": 1,
                    "filepath_raw": str(raw),
                })
            settings = getattr(mod, "point_cache", None) or getattr(
                getattr(mod, "domain_settings", None), "point_cache", None)
            if settings is not None and getattr(settings, "use_external", False):
                raw = getattr(settings, "filepath", "")
                if raw:
                    rows.append({
                        "type": "point_cache",
                        "name": "%s/%s" % (obj.name, mod.name),
                        "users": 1,
                        "filepath_raw": str(raw),
                    })
    return rows


# --------------------------------------------------------------------- 감사
def collect_external_paths():
    """path-bearing datablock 전수 수집."""
    referrers = _image_referrers()
    entries = []

    for coll_name in PATH_BEARING_COLLECTIONS:
        collection = getattr(bpy.data, coll_name, None)
        if collection is None:
            continue
        for db in collection:
            raw = getattr(db, "filepath_raw", None)
            if raw is None:
                raw = getattr(db, "filepath", None)
            if raw is None:
                continue
            if coll_name == "texts" and not str(raw):
                continue  # 내부 텍스트 블록은 외부 의존이 아니다
            raw = str(raw)
            packed = _is_packed(db)
            abs_path = _abspath(raw) if raw else ""
            entries.append({
                "type": coll_name,
                "name": db.name,
                "users": int(getattr(db, "users", 0)),
                "fake_user": bool(getattr(db, "use_fake_user", False)),
                "filepath_raw": raw,
                "filepath_absolute": abs_path,
                "exists": bool(abs_path) and os.path.isfile(abs_path),
                "is_absolute": U.is_absolute_filepath(raw),
                "is_relative": raw.startswith(U.BLEND_RELATIVE_PREFIX),
                "is_packed": packed,
                "source_kind": _source_kind(db),
                "referenced_by": ";".join(referrers.get(db.name, [])),
            })

    for row in _modifier_cache_paths():
        raw = row["filepath_raw"]
        abs_path = _abspath(raw)
        entries.append({
            "type": row["type"],
            "name": row["name"],
            "users": row["users"],
            "fake_user": False,
            "filepath_raw": raw,
            "filepath_absolute": abs_path,
            "exists": bool(abs_path) and os.path.exists(abs_path),
            "is_absolute": U.is_absolute_filepath(raw),
            "is_relative": raw.startswith(U.BLEND_RELATIVE_PREFIX),
            "is_packed": False,
            "source_kind": "",
            "referenced_by": "",
        })

    entries.sort(key=lambda e: (e["type"], e["name"]))
    return entries


def classify(entry, allowed_root):
    """감사 판정. Stage 2-B 와 같은 어휘를 쓴다(비교 가능해야 한다)."""
    if entry["is_packed"] or entry["source_kind"] in ("GENERATED", "VIEWER"):
        return "SAFE_PACKED_OR_GENERATED"
    if not entry["filepath_raw"]:
        return "SAFE_PACKED_OR_GENERATED"
    if entry["is_absolute"]:
        if not entry["exists"]:
            return "MISSING_CURRENT"
        return ("BLOCKED_ABSOLUTE" if U.is_within(entry["filepath_absolute"], allowed_root)
                else "ABSOLUTE_OUTSIDE_ROOT")
    if not entry["exists"]:
        return "MISSING_CURRENT"
    return "SAFE_RELATIVE"


def summarize(entries, allowed_root):
    counts = {}
    for e in entries:
        verdict = classify(e, allowed_root)
        e["verdict"] = verdict
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


# ------------------------------------------------------------------ 구조 스냅샷
def _names(collection):
    return sorted(db.name for db in collection)


def collect_structure():
    """승격 게이트가 비교할 구조 스냅샷. 렌더/카메라/컬러관리까지 포함한다."""
    scene = bpy.context.scene
    cam = scene.camera
    struct = {
        "counts": {
            "scenes": len(bpy.data.scenes),
            "view_layers": sum(len(s.view_layers) for s in bpy.data.scenes),
            "collections": len(bpy.data.collections),
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "node_groups": len(bpy.data.node_groups),
            "worlds": len(bpy.data.worlds),
            "cameras": len(bpy.data.cameras),
            "lights": len(bpy.data.lights),
            "images": len(bpy.data.images),
            "textures": len(bpy.data.textures),
        },
        "names": {
            "objects": _names(bpy.data.objects),
            "collections": _names(bpy.data.collections),
            "materials": _names(bpy.data.materials),
            "worlds": _names(bpy.data.worlds),
            "cameras": _names(bpy.data.cameras),
            "node_groups": _names(bpy.data.node_groups),
        },
        "active_scene": scene.name,
        "render": {
            "engine": scene.render.engine,
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
            "film_transparent": bool(scene.render.film_transparent),
            "filepath": scene.render.filepath,
        },
        "cycles_samples": int(getattr(getattr(scene, "cycles", None), "samples", 0) or 0),
        "eevee_taa_render_samples": int(
            getattr(getattr(scene, "eevee", None), "taa_render_samples", 0) or 0),
        "color_management": {
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "exposure": round(float(scene.view_settings.exposure), 6),
            "gamma": round(float(scene.view_settings.gamma), 6),
            "display_device": scene.display_settings.display_device,
            "sequencer_colorspace": scene.sequencer_colorspace_settings.name,
        },
        "camera": None,
        "pallets": sorted(o.name for o in bpy.data.objects
                          if o.name.startswith("Pallet_")),
        "dist_roots": sorted(o.name for o in bpy.data.objects
                             if o.name.startswith("Dist_") and o.parent is None),
        "dist_all": sum(1 for o in bpy.data.objects if o.name.startswith("Dist_")),
    }
    if cam is not None:
        struct["camera"] = {
            "name": cam.name,
            "matrix_world": [[round(float(v), 9) for v in row] for row in cam.matrix_world],
            "lens": round(float(cam.data.lens), 9),
            "sensor_width": round(float(cam.data.sensor_width), 9),
            "sensor_fit": cam.data.sensor_fit,
            "shift_x": round(float(cam.data.shift_x), 9),
            "shift_y": round(float(cam.data.shift_y), 9),
        }
    return struct


def diff_structure(before, after):
    """허용되지 않은 구조 변화를 찾아 목록으로 돌려준다."""
    diffs = []

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), path + [str(key)])
        elif isinstance(a, list) and isinstance(b, list):
            if a != b:
                only_a = [x for x in a if x not in b]
                only_b = [x for x in b if x not in a]
                diffs.append({"path": "/".join(path), "before_only": only_a[:20],
                              "after_only": only_b[:20],
                              "before_len": len(a), "after_len": len(b)})
        elif a != b:
            diffs.append({"path": "/".join(path), "before": a, "after": b})

    walk(before, after, [])
    return diffs


# --------------------------------------------------------------------- 출력
CSV_FIELDS = ("type", "name", "users", "fake_user", "filepath_raw", "filepath_absolute",
              "exists", "is_absolute", "is_relative", "is_packed", "source_kind",
              "referenced_by", "verdict")


def write_paths_csv(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for e in entries:
            w.writerow(e)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def write_plan_csv(path, plans):
    fields = ("datablock_name", "old_filepath", "old_absolute", "old_sha256",
              "new_filepath", "new_absolute", "new_sha256", "same_file",
              "users", "owner_nodes", "status", "blocker")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in plans:
            w.writerow(p)


# --------------------------------------------------------------------- 모드
def do_audit(args, tag):
    entries = collect_external_paths()
    counts = summarize(entries, args.allowed_root)
    struct = collect_structure()

    write_paths_csv(os.path.join(args.report_dir, "external_paths.csv"), entries)
    write_json(os.path.join(args.report_dir, "external_paths.json"),
               {"blend": bpy.data.filepath, "counts": counts, "entries": entries})
    write_json(os.path.join(args.report_dir, args.structure_name), struct)

    summary = {
        "mode": tag,
        "opened_blend": bpy.data.filepath,
        "opened_blend_sha256": U.sha256_file(bpy.data.filepath),
        "blender_version": bpy.app.version_string,
        "allowed_root": args.allowed_root,
        "total_entries": len(entries),
        "counts": counts,
        "structure_counts": struct["counts"],
        "pallets": struct["pallets"],
        "dist_roots": len(struct["dist_roots"]),
        "dist_all": struct["dist_all"],
        # 저장된 raw 는 Windows 백슬래시(`//textures\...`)라 슬래시를 정규화해서 센다.
        "relative_textures": sum(
            1 for e in entries
            if e["filepath_raw"].replace("\\", "/").startswith("//textures/")),
        "relative_distractors": sum(
            1 for e in entries
            if e["filepath_raw"].replace("\\", "/").startswith("//../distractors/")),
        "raw_relative_total": sum(1 for e in entries if e["is_relative"]),
        "raw_absolute_total": sum(1 for e in entries if e["is_absolute"]),
        "raw_empty_total": sum(1 for e in entries if not e["filepath_raw"]),
        "packed_total": sum(1 for e in entries if e["is_packed"]),
    }
    write_json(os.path.join(args.report_dir, "summary.json"), summary)
    print("[%s] %s" % (tag, json.dumps(summary["counts"], ensure_ascii=False)))
    print("[%s] entries=%d dist_roots=%d pallets=%s //textures=%d"
          % (tag, len(entries), summary["dist_roots"], summary["pallets"],
             summary["relative_textures"]))
    return entries, struct, summary


def build_plans(entries, args):
    blend_dir = _blend_dir()
    plans = []
    for e in entries:
        if e.get("verdict") != "BLOCKED_ABSOLUTE":
            continue
        plan = U.build_mapping(e, blend_dir, args.rewrite_root or args.allowed_root)
        plan["users"] = e["users"]
        plan["owner_nodes"] = e["referenced_by"]
        plans.append(plan)
    return plans


def collect_missing(entries):
    return [e for e in entries if e.get("verdict") == "MISSING_CURRENT"]


def do_plan(args):
    entries, struct, _ = do_audit(args, "plan")
    plans = build_plans(entries, args)
    write_plan_csv(os.path.join(args.report_dir, "distractor_path_plan.csv"), plans)

    missing = collect_missing(entries)
    write_json(os.path.join(args.report_dir, "missing_usage.json"), missing)

    planned = sum(1 for p in plans if p["status"] == "PLANNED")
    blocked = [p for p in plans if p["status"] != "PLANNED"]
    print("[plan] mappings planned=%d blocked=%d missing_datablocks=%d"
          % (planned, len(blocked), len(missing)))
    for p in blocked[:20]:
        print("   BLOCKED %s : %s" % (p["datablock_name"], p["blocker"]))
    for m in missing:
        print("   MISSING %s/%s users=%d fake_user=%s raw=%s refs=%s"
              % (m["type"], m["name"], m["users"], m["fake_user"],
                 m["filepath_raw"], m["referenced_by"] or "-"))
    return plans, missing


def do_apply_candidate(args):
    opened = os.path.abspath(bpy.data.filepath)
    candidate = os.path.abspath(args.candidate_blend)
    source = os.path.abspath(args.source_blend)

    U.assert_distinct_files(source, candidate)
    if U.norm(opened) != U.norm(candidate):
        raise U.PlanError(
            "열린 파일이 candidate 가 아닙니다. 저장을 거부합니다.\n"
            "  opened    %s\n  candidate %s" % (opened, candidate))
    if U.norm(opened) == U.norm(source):
        raise U.PlanError("열린 파일이 source 입니다. 저장을 거부합니다: %s" % opened)

    source_sha_before = U.assert_source_unchanged(source, args.expect_source_sha256)

    entries, struct_before, _ = do_audit(args, "apply-pre")
    plans = build_plans(entries, args)
    blocked = [p for p in plans if p["status"] != "PLANNED"]
    if blocked:
        raise U.PlanError("계획 단계에서 BLOCKED 가 %d 건 있습니다. 저장하지 않습니다." % len(blocked))

    # --- 누락 datablock 처리 (계획서에 명시된 것만) ---
    removed_images = []
    if args.remove_unused_missing:
        for name in args.remove_unused_missing:
            img = bpy.data.images.get(name)
            if img is None:
                raise U.PlanError("제거 대상 image datablock 이 없습니다: %s" % name)
            if img.users or img.use_fake_user:
                raise U.PlanError(
                    "users=%d fake_user=%s 인 datablock 은 제거하지 않습니다: %s"
                    % (img.users, img.use_fake_user, name))
            bpy.data.images.remove(img)
            removed_images.append(name)

    # --- 누락 datablock repoint (REPOINT_EXACT 판정을 받은 것만) ---
    repointed = []
    for spec in (args.repoint or []):
        if "=" not in spec:
            raise U.PlanError("--repoint 형식은 NAME=PATH 입니다: %s" % spec)
        name, target = spec.split("=", 1)
        img = bpy.data.images.get(name)
        if img is None:
            raise U.PlanError("repoint 대상 image datablock 이 없습니다: %s" % name)
        target_abs = os.path.abspath(target)
        if not os.path.isfile(target_abs):
            raise U.PlanError("repoint 대상 파일이 없습니다: %s" % target_abs)
        if not U.is_within(target_abs, args.allowed_root):
            raise U.PlanError("repoint 대상이 허용 루트 밖입니다: %s" % target_abs)
        new_rel = U.to_blend_relative(target_abs, _blend_dir())
        if new_rel is None:
            raise U.PlanError("repoint 대상이 다른 드라이브에 있습니다: %s" % target_abs)
        before = img.filepath_raw
        img.filepath = new_rel
        if img.filepath_raw != new_rel:
            raise U.PlanError("repoint 결과가 계획과 다릅니다: %s -> %s" % (name, img.filepath_raw))
        repointed.append({"name": name, "before": before, "after": new_rel,
                          "target_sha256": U.sha256_file(target_abs)})

    # --- 개별 filepath 재작성 (pack/make_paths_* 미사용) ---
    applied = []
    for p in plans:
        db = bpy.data.images.get(p["datablock_name"])
        if db is None:
            raise U.PlanError("계획된 image datablock 이 없습니다: %s" % p["datablock_name"])
        before = db.filepath_raw
        db.filepath = p["new_filepath"]          # Blender 가 filepath_raw 를 갱신한다
        after = db.filepath_raw
        if after != p["new_filepath"]:
            raise U.PlanError(
                "filepath 설정 결과가 계획과 다릅니다: %s -> %s (기대 %s)"
                % (p["datablock_name"], after, p["new_filepath"]))
        applied.append({"name": p["datablock_name"], "before": before, "after": after})

    # --- 저장 전 게이트 ---
    entries_after = collect_external_paths()
    counts_after = summarize(entries_after, args.allowed_root)
    planned_names = [p["datablock_name"] for p in plans] + [r["name"] for r in repointed]
    changed = [e["name"] for e in entries_after
               if e["type"] == "images" and e["name"] in set(planned_names)]
    U.assert_only_planned_changes(planned_names, changed)

    residual_abs = [e for e in entries_after if e["is_absolute"] and not e["is_packed"]]
    residual_user = [e for e in entries_after if U.has_user_specific_prefix(e["filepath_raw"])]
    residual_missing = [e for e in entries_after if e.get("verdict") == "MISSING_CURRENT"]
    unresolved = [e for e in entries_after
                  if e["is_relative"] and not e["is_packed"] and not e["exists"]]

    gate = {
        "opened_is_candidate": True,
        "unplanned_changes": 0,
        "absolute_remaining": len(residual_abs),
        "user_specific_remaining": len(residual_user),
        "missing_remaining": len(residual_missing),
        "unresolved_relative": len(unresolved),
        "mapping_sha256_mismatch": sum(1 for p in plans if not p["same_file"]),
        "removed_images": removed_images,
        "repointed": [r["name"] for r in repointed],
    }
    fail = [k for k in ("absolute_remaining", "user_specific_remaining", "missing_remaining",
                        "unresolved_relative", "mapping_sha256_mismatch") if gate[k]]
    if fail and args.strict:
        write_json(os.path.join(args.report_dir, "candidate_apply_log.json"),
                   {"gate": gate, "applied": applied,
                    "residual_absolute": residual_abs[:50],
                    "residual_missing": residual_missing[:50],
                    "counts_after": counts_after})
        raise U.PlanError("저장 전 게이트 실패: %s" % ", ".join(fail))

    # --- 저장 (candidate 만) ---
    compress = _blend_is_compressed(source)
    bpy.ops.wm.save_as_mainfile(filepath=candidate, compress=compress,
                                relative_remap=False, copy=False)
    saved_sha = U.sha256_file(candidate)

    source_sha_after = U.sha256_file(source)
    if source_sha_after != source_sha_before:
        raise U.PlanError("저장 후 source SHA256 이 변했습니다: %s -> %s"
                          % (source_sha_before, source_sha_after))

    log = {
        "source": source,
        "source_sha256_before": source_sha_before,
        "source_sha256_after": source_sha_after,
        "candidate": candidate,
        "candidate_sha256_after_save": saved_sha,
        "compress": compress,
        "applied_count": len(applied),
        "applied": applied,
        "repointed": repointed,
        "removed_images": removed_images,
        "gate": gate,
        "counts_after": counts_after,
        "blender_version": bpy.app.version_string,
    }
    write_json(os.path.join(args.report_dir, "candidate_apply_log.json"), log)
    print("[apply] rewritten=%d repointed=%d removed_images=%d compress=%s" %
          (len(applied), len(repointed), len(removed_images), compress))
    print("[apply] source sha256 unchanged: %s" % (source_sha_after == source_sha_before))
    print("[apply] candidate sha256 %s" % saved_sha)
    return log


TARGET_FIELDS = ("datablock_type", "datablock_name", "users", "filepath_raw",
                 "current_blend_dir", "current_resolved_absolute", "current_size",
                 "current_sha256", "is_packed", "is_generated", "current_allowed_root",
                 "target_allowed_root", "target_absolute", "target_relative_filepath",
                 "action", "blocker")


def _parse_root_map(specs):
    """--root-map OLD=NEW 를 (old_abs, new_abs) 리스트로. 긴 root 를 먼저 매칭한다."""
    pairs = []
    for spec in specs or []:
        if "=" not in spec:
            raise U.PlanError("--root-map 형식은 OLD=NEW 입니다: %s" % spec)
        old, new = spec.split("=", 1)
        pairs.append((os.path.abspath(old), os.path.abspath(new)))
    # 긴 경로 우선: blender_scene/textures 가 blender_scene 보다 먼저 매칭돼야 한다.
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _remap(abs_path, root_pairs):
    """abs_path 가 속한 current root 를 찾아 target root 로 옮긴 절대경로를 돌려준다."""
    for old, new in root_pairs:
        if U.is_within(abs_path, old):
            rel = os.path.relpath(abs_path, old)
            return old, new, os.path.abspath(os.path.join(new, rel))
    return None, None, None


def do_emit_target_manifest(args):
    """이동 전: 각 datablock 이 지금 가리키는 파일의 정체를 고정한다."""
    entries = collect_external_paths()
    summarize(entries, args.allowed_root)
    blend_dir = _blend_dir()
    root_pairs = _parse_root_map(args.root_map)

    rows = []
    for e in entries:
        generated = e["source_kind"] in ("GENERATED", "VIEWER")
        row = {
            "datablock_type": e["type"],
            "datablock_name": e["name"],
            "users": e["users"],
            "filepath_raw": e["filepath_raw"],
            "current_blend_dir": blend_dir,
            "current_resolved_absolute": e["filepath_absolute"],
            "current_size": "",
            "current_sha256": "",
            "is_packed": e["is_packed"],
            "is_generated": generated,
            "current_allowed_root": "",
            "target_allowed_root": "",
            "target_absolute": "",
            "target_relative_filepath": "",
            "action": "",
            "blocker": "",
        }
        if e["is_packed"] or generated or not e["filepath_raw"]:
            row["action"] = "SKIP_PACKED_OR_GENERATED"
            rows.append(row)
            continue
        abs_path = e["filepath_absolute"]
        if not abs_path or not os.path.isfile(abs_path):
            row["action"] = "BLOCKED"
            row["blocker"] = "current_target_missing"
            rows.append(row)
            continue
        row["current_size"] = os.path.getsize(abs_path)
        row["current_sha256"] = U.sha256_file(abs_path)
        old_root, new_root, target_abs = _remap(abs_path, root_pairs)
        if old_root is None:
            row["action"] = "BLOCKED"
            row["blocker"] = "unknown_current_root"
            rows.append(row)
            continue
        row["current_allowed_root"] = old_root
        row["target_allowed_root"] = new_root
        row["target_absolute"] = target_abs

        # action 은 root 가 움직였는지가 아니라 **상대경로 문자열이 그대로 유효한지**로 정한다.
        # textures 는 blend 와 함께 옮겨지므로 root 는 바뀌어도 `//textures/...` 는 그대로 맞고,
        # HDRI 는 root 가 그대로여도 blend 디렉토리가 옮겨져 문자열이 달라진다.
        target_dir = args.target_blend_dir or blend_dir
        new_rel = U.to_blend_relative(target_abs, target_dir)
        if new_rel is None:
            row["action"] = "BLOCKED"
            row["blocker"] = "different_drive"
            rows.append(row)
            continue
        row["target_relative_filepath"] = new_rel
        same = e["filepath_raw"].replace("\\", "/") == new_rel
        row["action"] = "KEEP_RELATIVE" if same else "REBASE"
        rows.append(row)

    path = args.target_manifest or os.path.join(args.report_dir,
                                                "blend_rebase_target_manifest.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TARGET_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    counts = {}
    for r in rows:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    blocked = [r for r in rows if r["action"] == "BLOCKED"]
    print("[target-manifest] %s" % json.dumps(counts, ensure_ascii=False))
    print("[target-manifest] blocked=%d -> %s" % (len(blocked), path))
    for r in blocked[:10]:
        print("   BLOCKED %s : %s (%s)" % (r["datablock_name"], r["blocker"],
                                           r["filepath_raw"][:80]))
    return rows


def do_rebase_candidate(args):
    """이동 후: candidate 안에서 target manifest 기준으로 상대경로를 다시 계산·적용."""
    opened = os.path.abspath(bpy.data.filepath)
    candidate = os.path.abspath(args.candidate_blend)
    source = os.path.abspath(args.source_blend)

    U.assert_distinct_files(source, candidate)
    if U.norm(opened) != U.norm(candidate):
        raise U.PlanError("열린 파일이 candidate 가 아닙니다. 저장을 거부합니다.\n"
                          "  opened    %s\n  candidate %s" % (opened, candidate))
    source_sha_before = U.assert_source_unchanged(source, args.expect_source_sha256)

    with open(args.target_manifest, "r", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))
    blocked_in_manifest = [r for r in manifest if r["action"] == "BLOCKED"]
    if blocked_in_manifest:
        raise U.PlanError("target manifest 에 BLOCKED 가 %d 건 있습니다."
                          % len(blocked_in_manifest))

    root_pairs = _parse_root_map(args.root_map)
    blend_dir = _blend_dir()
    applied, kept, mismatches = [], [], []

    for row in manifest:
        if row["action"] == "SKIP_PACKED_OR_GENERATED":
            continue
        name = row["datablock_name"]
        db = bpy.data.images.get(name)
        if db is None:
            raise U.PlanError("manifest 의 image datablock 이 없습니다: %s" % name)

        # target manifest 가 기록해 둔 "옛 절대경로" 를 root-map 으로 새 위치에 대응시킨다.
        old_abs = row["current_resolved_absolute"]
        _o, _n, target_abs = _remap(old_abs, root_pairs)
        if target_abs is None:
            raise U.PlanError("root-map 으로 해석할 수 없는 경로: %s" % old_abs)
        if not os.path.isfile(target_abs):
            mismatches.append((name, "target_missing", target_abs))
            continue
        got = U.sha256_file(target_abs)
        if got != row["current_sha256"]:
            mismatches.append((name, "sha256_mismatch", target_abs))
            continue

        new_rel = U.to_blend_relative(target_abs, blend_dir)
        if new_rel is None:
            mismatches.append((name, "different_drive", target_abs))
            continue
        if U.escapes_root(new_rel, blend_dir, args.allowed_root):
            mismatches.append((name, "escapes_allowed_root", new_rel))
            continue
        if U.has_user_specific_prefix(new_rel):
            mismatches.append((name, "user_specific_prefix", new_rel))
            continue

        before = db.filepath_raw
        db.filepath = new_rel
        after = db.filepath_raw
        if after.replace("\\", "/") != new_rel:
            raise U.PlanError("filepath 설정 결과가 계획과 다릅니다: %s -> %s (기대 %s)"
                              % (name, after, new_rel))
        record = {"name": name, "before": before, "after": after,
                  "target_absolute": target_abs, "sha256": got}
        (kept if before.replace("\\", "/") == new_rel else applied).append(record)

    if mismatches:
        write_json(os.path.join(args.report_dir, "rebase_mismatches.json"), mismatches)
        raise U.PlanError("rebase 검증 실패 %d 건 (rebase_mismatches.json 참조)" % len(mismatches))

    # --- 저장 전 게이트 ---
    entries_after = collect_external_paths()
    counts_after = summarize(entries_after, args.allowed_root)
    residual_abs = [e for e in entries_after if e["is_absolute"] and not e["is_packed"]]
    residual_user = [e for e in entries_after if U.has_user_specific_prefix(e["filepath_raw"])]
    residual_missing = [e for e in entries_after if e.get("verdict") == "MISSING_CURRENT"]
    unresolved = [e for e in entries_after
                  if e["is_relative"] and not e["is_packed"] and not e["exists"]]
    gate = {
        "absolute_remaining": len(residual_abs),
        "user_specific_remaining": len(residual_user),
        "missing_remaining": len(residual_missing),
        "unresolved_relative": len(unresolved),
        "mapping_mismatch": len(mismatches),
        "rebased": len(applied),
        "kept_relative": len(kept),
    }
    fail = [k for k in ("absolute_remaining", "user_specific_remaining", "missing_remaining",
                        "unresolved_relative", "mapping_mismatch") if gate[k]]
    if fail and args.strict:
        write_json(os.path.join(args.report_dir, "candidate_apply_log.json"),
                   {"gate": gate, "counts_after": counts_after,
                    "residual_missing": residual_missing[:50]})
        raise U.PlanError("저장 전 게이트 실패: %s" % ", ".join(fail))

    compress = _blend_is_compressed(source)
    bpy.ops.wm.save_as_mainfile(filepath=candidate, compress=compress,
                                relative_remap=False, copy=False)
    saved_sha = U.sha256_file(candidate)
    source_sha_after = U.sha256_file(source)
    if source_sha_after != source_sha_before:
        raise U.PlanError("저장 후 source SHA256 이 변했습니다.")

    log = {
        "mode": "rebase-candidate",
        "source": source, "source_sha256_before": source_sha_before,
        "source_sha256_after": source_sha_after,
        "candidate": candidate, "candidate_sha256_after_save": saved_sha,
        "compress": compress, "blend_dir": blend_dir,
        "root_map": ["%s=%s" % (o, n) for o, n in root_pairs],
        "rebased_count": len(applied), "kept_relative_count": len(kept),
        "rebased": applied, "kept_relative": kept[:20],
        "gate": gate, "counts_after": counts_after,
        "blender_version": bpy.app.version_string,
    }
    write_json(os.path.join(args.report_dir, "candidate_apply_log.json"), log)
    print("[rebase] rebased=%d kept_relative=%d compress=%s"
          % (len(applied), len(kept), compress))
    print("[rebase] gate %s" % json.dumps(gate, ensure_ascii=False))
    print("[rebase] source sha256 unchanged: %s" % (source_sha_after == source_sha_before))
    print("[rebase] candidate sha256 %s" % saved_sha)
    return log


def do_verify(args):
    entries, struct, summary = do_audit(args, "verify")
    result = {"summary": summary}

    if args.baseline_structure and os.path.isfile(args.baseline_structure):
        with open(args.baseline_structure, "r", encoding="utf-8") as f:
            before = json.load(f)
        diffs = diff_structure(before, struct)
        write_json(os.path.join(args.report_dir, "structure_diff.json"),
                   {"diffs": diffs, "before_counts": before.get("counts"),
                    "after_counts": struct["counts"]})
        result["structure_diff_count"] = len(diffs)
        print("[verify] structure diffs=%d" % len(diffs))
        for d in diffs[:30]:
            print("   DIFF %s" % json.dumps(d, ensure_ascii=False)[:300])

    # 참조 파일 해시 대조 (상대경로가 원래 파일을 정확히 가리키는지)
    rows = []
    for e in entries:
        if e["is_packed"] or not e["filepath_raw"] or not e["is_relative"]:
            continue
        rows.append({
            "name": e["name"],
            "filepath_raw": e["filepath_raw"],
            "resolved": e["filepath_absolute"],
            "exists": e["exists"],
            "sha256": U.sha256_file(e["filepath_absolute"]) if e["exists"] else "",
        })
    path = os.path.join(args.report_dir, "referenced_file_hashes.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=("name", "filepath_raw", "resolved", "exists", "sha256"))
        w.writeheader()
        w.writerows(rows)
    result["referenced_files"] = len(rows)
    write_json(os.path.join(args.report_dir, "verify_result.json"), result)
    print("[verify] referenced relative files hashed=%d" % len(rows))
    return result


# --------------------------------------------------------------------- CLI
def parse_args(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description="production .blend 외부경로 감사/portable 변환")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply-candidate", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--emit-target-manifest", action="store_true")
    mode.add_argument("--rebase-candidate", action="store_true")

    ap.add_argument("--source-blend", required=True)
    ap.add_argument("--candidate-blend", default=None)
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--allowed-root", default=None,
                    help="이 루트 밖 절대경로는 재작성 대상이 아니다 (기본: data/pallet)")
    ap.add_argument("--rewrite-root", default=None,
                    help="재작성 허용 루트 (기본: --allowed-root)")
    ap.add_argument("--remove-unused-missing", nargs="*", default=None,
                    help="candidate 에서만 제거할 미사용 image datablock 이름")
    ap.add_argument("--repoint", nargs="*", default=None, metavar="NAME=PATH",
                    help="REPOINT_EXACT 판정을 받은 누락 datablock 을 정확한 파일로 다시 연결")
    ap.add_argument("--target-manifest", default=None,
                    help="--emit-target-manifest 출력 / --rebase-candidate 입력 CSV")
    ap.add_argument("--root-map", nargs="*", default=None, metavar="OLD=NEW",
                    help="current asset root -> target asset root (긴 root 우선 매칭)")
    ap.add_argument("--target-blend-dir", default=None,
                    help="--emit-target-manifest 전용: 이동 후 blend 가 있을 디렉토리. "
                         "상대경로 문자열이 그대로 유효한지 여기서 미리 계산한다.")
    ap.add_argument("--expect-source-sha256", default=None)
    ap.add_argument("--baseline-structure", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--role", choices=("source", "candidate", "opened"), default="opened",
                    help="산출물 파일명 규약: source_structure.json / candidate_structure.json")
    args = ap.parse_args(argv)

    args.structure_name = {
        "source": "source_structure.json",
        "candidate": "candidate_structure.json",
        "opened": "structure.json",
    }[args.role]
    args.sha_name = {
        "source": "source_blend_sha256.txt",
        "candidate": "candidate_sha256.txt",
        "opened": "opened_blend_sha256.txt",
    }[args.role]

    args.source_blend = os.path.abspath(args.source_blend)
    if args.candidate_blend:
        args.candidate_blend = os.path.abspath(args.candidate_blend)
        U.assert_distinct_files(args.source_blend, args.candidate_blend)
    args.report_dir = os.path.abspath(args.report_dir)
    if args.allowed_root is None:
        project_root = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
        args.allowed_root = os.path.join(project_root, "data", "pallet")
    args.allowed_root = os.path.abspath(args.allowed_root)
    if args.rewrite_root:
        args.rewrite_root = os.path.abspath(args.rewrite_root)
    return args


def main():
    args = parse_args()
    os.makedirs(args.report_dir, exist_ok=True)

    if args.expect_source_sha256:
        U.assert_source_unchanged(args.source_blend, args.expect_source_sha256)

    if args.apply_candidate:
        if not args.candidate_blend:
            raise U.PlanError("--apply-candidate 에는 --candidate-blend 가 필요합니다")
        if not args.expect_source_sha256:
            raise U.PlanError("--apply-candidate 에는 --expect-source-sha256 이 필요합니다")
        do_apply_candidate(args)
        return

    if args.rebase_candidate:
        for need, why in (("candidate_blend", "--candidate-blend"),
                          ("expect_source_sha256", "--expect-source-sha256"),
                          ("target_manifest", "--target-manifest")):
            if not getattr(args, need):
                raise U.PlanError("--rebase-candidate 에는 %s 가 필요합니다" % why)
        if not args.root_map:
            raise U.PlanError("--rebase-candidate 에는 --root-map 이 필요합니다")
        do_rebase_candidate(args)
        return

    # audit / plan / verify 는 저장하지 않는다. 열린 파일이 source 여도 안전하다.
    with open(os.path.join(args.report_dir, args.sha_name), "w",
              encoding="utf-8") as f:
        f.write("%s  %s\n" % (U.sha256_file(bpy.data.filepath), bpy.data.filepath))

    if args.audit:
        do_audit(args, "audit")
    elif args.plan:
        do_plan(args)
    elif args.verify:
        do_verify(args)
    elif args.emit_target_manifest:
        if not args.root_map:
            raise U.PlanError("--emit-target-manifest 에는 --root-map 이 필요합니다")
        do_emit_target_manifest(args)


if __name__ == "__main__":
    try:
        main()
    except U.PlanError as exc:
        print("[FAIL] %s" % exc, file=sys.stderr)
        sys.exit(2)
