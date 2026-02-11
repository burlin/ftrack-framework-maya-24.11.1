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


def export_fbx(objects: list[str], file_path: str) -> str:
    """Export selected objects as FBX."""
    _select_objects(objects)

    # Ensure FBX plugin is loaded
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")

    cmds.file(
        _strip_ext(file_path),
        force=True,
        type="FBX export",
        exportSelected=True,
    )
    _log.info("Exported FBX: %s", file_path)
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


def export_component(objects: list[str], file_path: str) -> str:
    """Export objects using the appropriate exporter based on file extension.

    Args:
        objects: List of Maya object names to export.
        file_path: Destination file path (extension determines format).

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
    return exporter(objects, file_path)
