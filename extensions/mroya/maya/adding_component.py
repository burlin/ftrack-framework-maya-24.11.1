"""Adding component to Maya scene.

This module handles adding ftrack components to the Maya scene
via reference or import.

TO BE EXPANDED LATER.
"""
from __future__ import annotations
from . import reference_file
import maya.cmds as cmds
import logging

_log = logging.getLogger(__name__)


def add_component_to_scene(component_path: str, method: str) -> bool:
    """Main entry point for adding files to the scene."""
    print(f"[Adding Component] Path: {component_path} | Method: {method}")

    if method == "reference":
        return reference_file.reference_maya_file(component_path)

    elif method == "import":
        try:
            cmds.file(component_path, i=True)
            return True
        except Exception as e:
            _log.error("Import failed: %s", e)
            return False

    return False
