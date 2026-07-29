"""렌더 없이 `.blend` 를 production 파이프라인 관점에서 감사한다 (Stage 2-C1).

Stage 2-B 는 같은 감사를 커밋되지 않은 임시 스크립트로 돌렸다. 같은 검사를 다음 단계에서도
재현할 수 있어야 하므로 정식 스크립트로 만든다.

    blender -b <blend> --python scripts/data_prep/blender/audit_blend_assets.py -- \
        --report-dir reports/data_pallet_cleanup/stage2c1 --tag candidate

검사 (전부 읽기 전용 — render / save 없음)
  - blender_config · pallet_data_paths import
  - registry audit missing
  - Pallet_0~3 / Distractors_v2 / Dist_ root 수
  - background root · distractor manifest
  - hdri_root 의 모든 HDRI decode  (v2 의 CONSTRAINED_HDRI_EXCLUDE 도 같이 표시)
  - floor / wood 텍스처 decode
  - `.blend` 내부 image datablock 의 missing 수 (마젠타 원인 후보)
  - material / world image node 의 경로 누락 수
"""

import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import bpy  # noqa: E402


def _decode(path):
    """이미지 하나를 실제로 디코드해 (ok, w, h, error) 를 돌려준다."""
    image = None
    try:
        image = bpy.data.images.load(path, check_existing=False)
        w, h = image.size[0], image.size[1]
        return (w > 0 and h > 0), w, h, ""
    except Exception as exc:                      # noqa: BLE001 - 사유를 그대로 남긴다
        return False, 0, 0, str(exc)
    finally:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass


def _decode_dir(root, exts):
    rows = []
    if not os.path.isdir(root):
        return rows
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith(exts):
            continue
        path = os.path.join(root, name)
        ok, w, h, err = _decode(path)
        rows.append({"name": name, "ok": ok, "size": [w, h], "error": err})
    return rows


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--tag", default="candidate")
    args = ap.parse_args(argv)
    os.makedirs(args.report_dir, exist_ok=True)

    result = {"blend": bpy.data.filepath, "tag": args.tag,
              "blender_version": bpy.app.version_string}

    # --- import 경로 ---
    import pallet_data_paths as PDP
    import blender_config as cfg
    import v2_realize as VR

    paths = PDP.load(use_cache=False)
    audit = paths.audit()
    result["registry"] = {
        "ok": len(audit["ok"]),
        "missing": [e["relative"] for e in audit["missing"]],
        "absent_optional": len(audit["absent_optional"]),
    }
    result["imports"] = {"blender_config": True, "pallet_data_paths": True,
                         "v2_realize": True}

    # --- 씬 오브젝트 ---
    objects = bpy.data.objects
    result["scene"] = {
        "pallets": sorted(o.name for o in objects if o.name.startswith("Pallet_")),
        "distractors_v2_collection": "Distractors_v2" in bpy.data.collections,
        "dist_roots": sum(1 for o in objects
                          if o.name.startswith("Dist_") and o.parent is None),
        "dist_all": sum(1 for o in objects if o.name.startswith("Dist_")),
        "cameras": sorted(o.name for o in objects if o.type == "CAMERA"),
        "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    }

    # --- blend 내부 image datablock ---
    missing_images, packed, generated = [], 0, 0
    for img in bpy.data.images:
        if getattr(img, "packed_file", None) is not None:
            packed += 1
            continue
        if str(getattr(img, "source", "")) in ("GENERATED", "VIEWER"):
            generated += 1
            continue
        raw = img.filepath_raw
        if not raw:
            continue
        abs_path = os.path.abspath(bpy.path.abspath(raw))
        if not os.path.isfile(abs_path):
            missing_images.append({"name": img.name, "filepath_raw": raw,
                                   "users": img.users})
    # Stage 2-C2: 참조 수를 상대경로 **문자열 형태**로 세면 폴더가 옮겨질 때마다 0 이 된다.
    # 대신 resolve 된 절대경로가 registry root 안인지로 센다 (위치 비의존).
    def _under(root):
        root_n = os.path.normcase(os.path.abspath(root))
        n = 0
        for img in bpy.data.images:
            raw = img.filepath_raw
            if not raw or getattr(img, "packed_file", None) is not None:
                continue
            p = os.path.normcase(os.path.abspath(bpy.path.abspath(raw)))
            if p == root_n or p.startswith(root_n + os.sep):
                n += 1
        return n

    scene_dir = os.path.dirname(os.path.abspath(bpy.data.filepath))
    result["images"] = {
        "total": len(bpy.data.images),
        "packed": packed,
        "generated": generated,
        "missing": missing_images,
        "missing_count": len(missing_images),
        "relative_textures": _under(os.path.join(scene_dir, "textures")),
        "relative_distractors": _under(paths.get("distractor_root")),
        "relative_hdri": _under(paths.get("hdri_root")),
        "absolute": sum(1 for i in bpy.data.images
                        if i.filepath_raw and not i.filepath_raw.startswith("//")
                        and (os.path.isabs(i.filepath_raw)
                             or (len(i.filepath_raw) > 1 and i.filepath_raw[1] == ":")
                             or i.filepath_raw[0] in ("/", "\\"))),
    }

    # --- material / world node 의 이미지 경로 누락 ---
    node_missing = []
    def _scan(tree, owner):
        if tree is None:
            return
        for node in tree.nodes:
            img = getattr(node, "image", None)
            if img is None:
                continue
            if getattr(img, "packed_file", None) is not None:
                continue
            if str(getattr(img, "source", "")) in ("GENERATED", "VIEWER"):
                continue
            raw = img.filepath_raw
            if not raw:
                node_missing.append({"owner": owner, "node": node.name,
                                     "image": img.name, "reason": "empty_filepath"})
                continue
            if not os.path.isfile(os.path.abspath(bpy.path.abspath(raw))):
                node_missing.append({"owner": owner, "node": node.name,
                                     "image": img.name, "reason": "file_missing",
                                     "filepath_raw": raw})
    for mat in bpy.data.materials:
        _scan(getattr(mat, "node_tree", None), "material:%s" % mat.name)
    for world in bpy.data.worlds:
        _scan(getattr(world, "node_tree", None), "world:%s" % world.name)
    for group in bpy.data.node_groups:
        _scan(group, "nodegroup:%s" % group.name)
    result["node_image_missing"] = {"count": len(node_missing), "entries": node_missing}

    # --- 외부 자산 decode ---
    hdri_rows = _decode_dir(paths.get("hdri_root"), (".hdr", ".exr"))
    result["hdri"] = {
        "root": paths.relative("hdri_root"),
        "total": len(hdri_rows),
        "ok": sum(1 for r in hdri_rows if r["ok"]),
        "failed": [r for r in hdri_rows if not r["ok"]],
        "v2_constrained_exclude": sorted(VR.CONSTRAINED_HDRI_EXCLUDE),
        "v2_constrained_pool_size": len([
            r for r in hdri_rows
            if r["ok"] and r["name"] not in VR.CONSTRAINED_HDRI_EXCLUDE]),
    }

    floor_rows = _decode_dir(paths.get("floor_material_root"), (".png", ".jpg", ".jpeg"))
    wood_rows = _decode_dir(paths.get("pallet_material_root"), (".png", ".jpg", ".jpeg"))
    result["floor_textures"] = {"total": len(floor_rows),
                                "ok": sum(1 for r in floor_rows if r["ok"]),
                                "failed": [r for r in floor_rows if not r["ok"]]}
    result["wood_textures"] = {"total": len(wood_rows),
                               "ok": sum(1 for r in wood_rows if r["ok"]),
                               "failed": [r for r in wood_rows if not r["ok"]]}

    # --- 매니페스트 / 배경 ---
    import distractor_pool_v2 as dpool
    result["distractor_manifest"] = {
        "path": paths.relative("distractor_manifest"),
        "rows": len(dpool.load_pool()),
    }
    bg_root = paths.get("background_root")
    result["background_root"] = {
        "path": paths.relative("background_root"),
        "exists": os.path.isdir(bg_root),
        "configured_assets": sorted(cfg.BACKGROUND_KEYS),
        "configured_files_present": {
            k: bool(v.get("filepath")) and os.path.isfile(v["filepath"])
            for k, v in cfg.BACKGROUND_ASSETS.items() if v.get("filepath")
        },
    }

    out = os.path.join(args.report_dir, "%s_no_render_audit.json" % args.tag)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, sort_keys=True)

    print("[audit] registry missing=%d" % len(result["registry"]["missing"]))
    print("[audit] pallets=%s Distractors_v2=%s Dist_roots=%d"
          % (result["scene"]["pallets"], result["scene"]["distractors_v2_collection"],
             result["scene"]["dist_roots"]))
    print("[audit] images total=%d missing=%d absolute=%d "
          "textures=%d distractors=%d hdri=%d  (resolve 기준, 문자열 형태 무관)"
          % (result["images"]["total"], result["images"]["missing_count"],
             result["images"]["absolute"], result["images"]["relative_textures"],
             result["images"]["relative_distractors"], result["images"]["relative_hdri"]))
    print("[audit] node image missing=%d" % result["node_image_missing"]["count"])
    print("[audit] HDRI %d/%d decode ok (v2 constrained pool=%d)"
          % (result["hdri"]["ok"], result["hdri"]["total"],
             result["hdri"]["v2_constrained_pool_size"]))
    print("[audit] floor %d/%d  wood %d/%d decode ok"
          % (result["floor_textures"]["ok"], result["floor_textures"]["total"],
             result["wood_textures"]["ok"], result["wood_textures"]["total"]))
    print("[audit] distractor manifest rows=%d" % result["distractor_manifest"]["rows"])
    print("[audit] -> %s" % out)


if __name__ == "__main__":
    main()
