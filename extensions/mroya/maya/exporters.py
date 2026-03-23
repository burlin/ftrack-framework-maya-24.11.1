"""Maya export functions for different file formats.

Each exporter selects the given objects and exports them to the specified path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import maya.cmds as cmds
import maya.mel as mel

_log = logging.getLogger(__name__)

# Base defaults per format — used when no asset_type-specific entry exists in the JSON.
# These are the lowest-priority fallback; export_defaults.json overrides them.
_FORMAT_DEFAULTS: dict[str, dict] = {
    "fbx": {
        "ascii": True,
        "input_connections": False,
        "blend_shapes": True,
        "bake_animation": True,
        "strip_namespaces": True,
    },
}

_DEFAULTS_CACHE: dict | None = None


def _load_export_defaults() -> dict:
    """Load export_defaults.json, caching after first read."""
    global _DEFAULTS_CACHE
    if _DEFAULTS_CACHE is not None:
        return _DEFAULTS_CACHE
    json_path = Path(__file__).resolve().parents[3] / "resource" / "export_defaults.json"
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            _DEFAULTS_CACHE = json.load(f)
        _log.info("Loaded export_defaults.json from %s", json_path)
    except Exception as exc:
        _log.warning("Could not load export_defaults.json (%s): %s", json_path, exc)
        _DEFAULTS_CACHE = {}
    return _DEFAULTS_CACHE


def get_export_defaults(asset_type: str, ext: str) -> dict:
    """Return fully merged export defaults for a given asset type and extension.

    Priority (lowest → highest):
      1. _FORMAT_DEFAULTS  — format-level base (e.g. FBX generic defaults)
      2. export_defaults.json entry for asset_type + ext

    Lookup is case-insensitive on asset_type.
    Always returns a complete dict for known formats so callers don't need
    their own per-key fallbacks.
    """
    ext = ext.lower()
    base = dict(_FORMAT_DEFAULTS.get(ext, {}))

    json_defaults = _load_export_defaults()
    for key, val in json_defaults.items():
        if key.startswith("_"):
            continue
        if key.lower() == asset_type.lower():
            base.update(val.get(ext, {}))
            break

    return base


def _select_objects(objects: list[str]):
    """Select the given objects in Maya, raising if any are missing."""
    if not objects:
        raise ValueError("No objects to export")
    cmds.select(clear=True)
    cmds.select(objects, replace=True)


def _strip_ext(file_path: str) -> str:
    """Strip the file extension — cmds.file() auto-appends it."""
    p = Path(file_path)
    return str(p.parent / p.stem)


def _apply_fbx_flags(
    ascii: bool,
    input_connections: bool,
    blend_shapes: bool,
    bake_animation: bool,
    bake_start: int,
    bake_end: int,
) -> None:
    """Set FBX MEL export flags. Assumes FBX plugin is already loaded."""
    mel.eval(f'FBXExportInAscii -v {"true" if ascii else "false"}')
    mel.eval(f'FBXExportInputConnections -v {"true" if input_connections else "false"}')
    mel.eval(f'FBXExportShapes -v {"true" if blend_shapes else "false"}')
    mel.eval(f'FBXExportBakeComplexAnimation -v {"true" if bake_animation else "false"}')
    if bake_animation:
        mel.eval(f'FBXExportBakeComplexStart -v {bake_start}')
        mel.eval(f'FBXExportBakeComplexEnd -v {bake_end}')
        mel.eval('FBXExportBakeComplexStep -v 1')


def _export_fbx_strip_namespaces(
    objects: list[str],
    file_path: str,
    ascii: bool,
    input_connections: bool,
    blend_shapes: bool,
    bake_animation: bool,
    bake_start: int,
    bake_end: int,
) -> None:
    """Direct port of the proven standalone strip-namespace export script.

    For each root: duplicate → strip namespaces → constrain to original →
    bake → delete constraints → export → delete duplicate.
    """
    # Find the topmost object in the hierarchy — the one with the shortest
    # full path. This handles the case where the user selects both a parent
    # and a child joint; we want to export from the root downward so the
    # entire hierarchy is captured, not just a subtree.
    def _full_path(obj):
        try:
            fp = cmds.ls(obj, long=True)
            return fp[0] if fp else obj
        except Exception:
            return obj

    root = min(objects, key=lambda o: len(_full_path(o).split("|")))
    new_root_name = None
    constraints = []

    try:
        tmp_root = cmds.duplicate(
            root,
            returnRootsOnly=True,
            upstreamNodes=False,
            inputConnections=False,
            renameChildren=True,
        )[0]

        all_tmp_nodes = cmds.listRelatives(tmp_root, allDescendents=True, fullPath=True) or []
        all_tmp_nodes.append(tmp_root)
        all_tmp_nodes.sort(key=len, reverse=True)

        new_root_name = tmp_root
        for node in all_tmp_nodes:
            for attr in ['t', 'r', 's', 'v']:
                for axis in ['x', 'y', 'z']:
                    at = f"{node}.{attr}{axis}" if attr != 'v' else f"{node}.{attr}"
                    if cmds.objExists(at):
                        try:
                            cmds.setAttr(at, lock=False)
                        except Exception:
                            pass

            if ":" in node:
                clean_name = node.split("|")[-1].split(":")[-1]
                actual_name = cmds.rename(node, clean_name)
            else:
                actual_name = node.split("|")[-1]

            new_root_name = actual_name  # last iteration = root (shortest path)

        # Resolve the duplicate root's full DAG path after all renames.
        dup_root_long = cmds.ls(new_root_name, long=True)
        dup_root_long = dup_root_long[0] if dup_root_long else new_root_name

        # Build a mapping: clean short name -> full DAG path in the duplicate.
        # Using full paths avoids resolving to the wrong node when the scene
        # has other nodes sharing the same short name as the cleaned duplicates.
        all_dup_nodes = cmds.listRelatives(dup_root_long, allDescendents=True, fullPath=True) or []
        all_dup_nodes.append(dup_root_long)
        dup_by_short = {n.split("|")[-1]: n for n in all_dup_nodes}

        original_hierarchy = cmds.listRelatives(root, allDescendents=True, fullPath=True) or []
        original_hierarchy.append(root)

        for orig in original_hierarchy:
            clean_short = orig.split("|")[-1].split(":")[-1]
            dup_full = dup_by_short.get(clean_short)
            if dup_full and cmds.objExists(dup_full):
                try:
                    con = cmds.parentConstraint(orig, dup_full, mo=False)
                    scl = cmds.scaleConstraint(orig, dup_full, mo=False)
                    constraints.extend([con[0], scl[0]])
                except RuntimeError:
                    pass

        cmds.select(dup_root_long, hierarchy=True)
        cmds.bakeResults(
            cmds.ls(selection=True),
            time=(bake_start, bake_end),
            simulation=True,
            hierarchy="both",
            sampleBy=1,
            disableImplicitControl=True,
            preserveOutsideKeys=True,
            minimizeRotation=True,
        )

        if constraints:
            cmds.delete(constraints)
            constraints = []

        if cmds.listRelatives(new_root_name, parent=True):
            cmds.parent(new_root_name, world=True)

        cmds.select(new_root_name)
        mel.eval('FBXResetExport()')
        _apply_fbx_flags(ascii, input_connections, blend_shapes, bake_animation,
                         bake_start, bake_end)
        cmds.file(_strip_ext(file_path), force=True, type="FBX export",
                  preserveReferences=True, exportSelected=True)

    finally:
        if constraints:
            try:
                cmds.delete(constraints)
            except Exception:
                pass
        if new_root_name and cmds.objExists(new_root_name):
            try:
                cmds.delete(new_root_name)
            except Exception:
                pass


def export_fbx(
    objects: list[str],
    file_path: str,
    ascii: bool = True,
    input_connections: bool = False,
    blend_shapes: bool = True,
    bake_animation: bool = True,
    bake_start: int | None = None,
    bake_end: int | None = None,
    strip_namespaces: bool = True,
) -> str:
    """Export selected objects as FBX.

    Args:
        objects: Maya objects to export.
        file_path: Destination path.
        ascii: Write ASCII FBX when True (default), binary otherwise.
        input_connections: Export input connections. Off by default.
        blend_shapes: Export blend shapes. On by default.
        bake_animation: Bake complex animation. On by default.
        bake_start: First frame for bake. Uses scene start if None.
        bake_end: Last frame for bake. Uses scene end if None.
        strip_namespaces: When True (default), duplicate the hierarchy, strip
            all namespaces from node names, bake the animation on the clean
            duplicate, export it, then delete the duplicate.  When False,
            export the original selection as-is.
    """
    # Ensure FBX plugin is loaded
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")

    start = int(bake_start) if bake_start is not None else int(cmds.playbackOptions(q=True, min=True))
    end = int(bake_end) if bake_end is not None else int(cmds.playbackOptions(q=True, max=True))

    if strip_namespaces:
        _export_fbx_strip_namespaces(
            objects, file_path,
            ascii=ascii,
            input_connections=input_connections,
            blend_shapes=blend_shapes,
            bake_animation=bake_animation,
            bake_start=start,
            bake_end=end,
        )
        _log.info(
            "Exported FBX with namespace stripping (ascii=%s, bake=%s): %s",
            ascii, bake_animation, file_path,
        )
        return file_path

    _select_objects(objects)
    _apply_fbx_flags(ascii, input_connections, blend_shapes, bake_animation, start, end)
    cmds.file(
        _strip_ext(file_path),
        force=True,
        type="FBX export",
        exportSelected=True,
    )
    _log.info(
        "Exported FBX (ascii=%s, input_connections=%s, blend_shapes=%s, bake=%s): %s",
        ascii, input_connections, blend_shapes, bake_animation, file_path,
    )
    return file_path


def export_ma(objects: list[str], file_path: str) -> str:
    """Export selected objects as Maya ASCII."""
    _select_objects(objects)

    cmds.file(
        _strip_ext(file_path),
        force=True,
        type="mayaAscii",
        exportSelected=True,
    )
    _log.info("Exported Maya ASCII: %s", file_path)
    return file_path


def export_obj(objects: list[str], file_path: str) -> str:
    """Export selected objects as OBJ."""
    _select_objects(objects)

    # Ensure OBJ plugin is loaded
    if not cmds.pluginInfo("objExport", query=True, loaded=True):
        cmds.loadPlugin("objExport")

    cmds.file(
        _strip_ext(file_path),
        force=True,
        type="OBJexport",
        exportSelected=True,
    )
    _log.info("Exported OBJ: %s", file_path)
    return file_path


def export_abc(
    objects: list[str],
    file_path: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> str:
    """Export selected objects as Alembic (.abc).

    Args:
        objects: Maya objects to export.
        file_path: Destination path (with or without .abc extension).
        frame_start: First frame to export. Uses scene start if None.
        frame_end: Last frame to export. Uses scene end if None.
    """
    if not cmds.pluginInfo("AbcExport", query=True, loaded=True):
        cmds.loadPlugin("AbcExport")

    start = int(frame_start) if frame_start is not None else int(cmds.playbackOptions(q=True, min=True))
    end = int(frame_end) if frame_end is not None else int(cmds.playbackOptions(q=True, max=True))

    # Ensure the path ends with .abc
    out_path = str(file_path) if str(file_path).lower().endswith(".abc") else str(file_path) + ".abc"

    roots = " ".join(f"-root {obj}" for obj in objects)
    job_str = (
        f"-frameRange {start} {end} "
        f"-uvWrite -worldSpace -writeVisibility "
        f"{roots} "
        f"-file {out_path}"
    )
    cmds.AbcExport(j=job_str)
    _log.info("Exported Alembic (frames %s–%s): %s", start, end, out_path)
    return out_path


def export_usd(objects: list[str], file_path: str) -> str:
    """Export selected objects as USD (binary)."""
    _select_objects(objects)

    # Ensure USD plugin is loaded
    if not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaUsdPlugin")

    cmds.mayaUSDExport(
        file=file_path,
        selection=True,
    )
    _log.info("Exported USD: %s", file_path)
    return file_path


def export_usda(objects: list[str], file_path: str) -> str:
    """Export selected objects as USDA (ASCII)."""
    _select_objects(objects)

    if not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaUsdPlugin")

    cmds.mayaUSDExport(
        file=file_path,
        selection=True,
    )
    _log.info("Exported USDA: %s", file_path)
    return file_path


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_EXPORTERS = {
    "abc": export_abc,
    "fbx": export_fbx,
    "ma": export_ma,
    "obj": export_obj,
    "usd": export_usd,
    "usda": export_usda,
}


def save_snapshot(file_path: str) -> str:
    """Save the current Maya scene as a snapshot (ma or mb).

    Args:
        file_path: Destination path. Extension determines format
                   (``.ma`` → mayaAscii, ``.mb`` → mayaBinary).

    Returns:
        The file path of the saved snapshot.
    """
    ext = Path(file_path).suffix.lstrip(".").lower()
    file_type = "mayaBinary" if ext == "mb" else "mayaAscii"

    cmds.file(
        _strip_ext(file_path),
        force=True,
        type=file_type,
        exportAll=True,
    )
    _log.info("Saved snapshot (%s): %s", file_type, file_path)
    return file_path


def export_component(
    objects: list[str],
    file_path: str,
    options: dict | None = None,
    asset_type: str = "",
) -> str:
    """Export objects using the appropriate exporter based on file extension.

    Options are resolved in priority order (lowest → highest):
      1. Built-in fallback defaults (hardcoded)
      2. export_defaults.json values for this asset_type + extension
      3. Per-component options stored on the Maya publish node

    Args:
        objects: List of Maya object names to export.
        file_path: Destination file path (extension determines format).
        options: Format-specific export options already stored on the node.
        asset_type: Asset type name (e.g. "Rig", "Animation") used to look up
                    defaults from export_defaults.json.

    Returns:
        The file path of the exported file.

    Raises:
        ValueError: If no objects given or extension is unsupported.
    """
    ext = Path(file_path).suffix.lstrip(".").lower()
    exporter = _EXPORTERS.get(ext)
    if exporter is None:
        raise ValueError(
            f"Unsupported export format: '.{ext}'. "
            f"Supported: {', '.join(sorted(_EXPORTERS))}"
        )

    # Build merged options: format base < JSON asset-type config < node-stored options
    # get_export_defaults always returns a complete dict for known formats, so no
    # per-key Python fallbacks are needed below.
    opts = {**get_export_defaults(asset_type, ext), **(options or {})}

    if ext == "fbx":
        return exporter(
            objects, file_path,
            ascii=opts["ascii"],
            input_connections=opts["input_connections"],
            blend_shapes=opts["blend_shapes"],
            bake_animation=opts["bake_animation"],
            bake_start=opts.get("frame_start"),
            bake_end=opts.get("frame_end"),
            strip_namespaces=opts["strip_namespaces"],
        )
    if ext == "abc":
        return exporter(
            objects, file_path,
            frame_start=opts.get("frame_start"),
            frame_end=opts.get("frame_end"),
        )
    return exporter(objects, file_path)
