"""Maya export functions for different file formats.

Each exporter selects the given objects and exports them to the specified path.
"""
from __future__ import annotations

import logging
from pathlib import Path

import maya.cmds as cmds
import maya.mel as mel

_log = logging.getLogger(__name__)


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
    # objects[0] is the root — same as selection[0] in the standalone script.
    # Never iterate: if the component list contains the root plus descendants,
    # each iteration would trigger a full bake of the entire timeline.
    root = objects[0]
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

        original_hierarchy = cmds.listRelatives(root, allDescendents=True, fullPath=True) or []
        original_hierarchy.append(root)

        for orig in original_hierarchy:
            clean_target = orig.split("|")[-1].split(":")[-1]
            if cmds.objExists(clean_target) and clean_target != orig:
                try:
                    con = cmds.parentConstraint(orig, clean_target, mo=False)
                    scl = cmds.scaleConstraint(orig, clean_target, mo=False)
                    constraints.extend([con[0], scl[0]])
                except RuntimeError:
                    pass

        cmds.select(new_root_name, hierarchy=True)
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
) -> str:
    """Export objects using the appropriate exporter based on file extension.

    Args:
        objects: List of Maya object names to export.
        file_path: Destination file path (extension determines format).
        options: Format-specific export options dict (e.g. ``{"ascii": True}``
                 for FBX).

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
    opts = options or {}
    if ext == "fbx":
        return exporter(
            objects, file_path,
            ascii=opts.get("ascii", True),
            input_connections=opts.get("input_connections", False),
            blend_shapes=opts.get("blend_shapes", True),
            bake_animation=opts.get("bake_animation", True),
            bake_start=opts.get("frame_start"),
            bake_end=opts.get("frame_end"),
            strip_namespaces=opts.get("strip_namespaces", True),
        )
    return exporter(objects, file_path)
