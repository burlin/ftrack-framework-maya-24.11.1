"""Maya reference utility for mroya."""
from __future__ import annotations

import os
import logging
import maya.cmds as cmds

_log = logging.getLogger(__name__)


def reference_maya_file(file_path: str) -> bool:
    """References a file into the current Maya scene.

    Args:
        file_path: Absolute path to the .ma or .mb file.

    Returns:
        True if successful, False otherwise.
    """
    if not os.path.exists(file_path):
        _log.error("Reference failed: File does not exist -> %s", file_path)
        return False

    # Extract a clean namespace from the filename (e.g., 'char_rig' from 'char_rig_v001.ma')
    filename = os.path.basename(file_path)
    base_name = os.path.splitext(filename)[0]
    # Simple regex-free cleanup: replace dots/dashes with underscores
    namespace = base_name.replace(".", "_").replace("-", "_")

    try:
        _log.info("Referencing file: %s with namespace: %s", file_path, namespace)

        # Create the reference
        # - groupReference: Puts the content in a top-level group
        # - mergeNamespacesOnClash: Reuses namespace if already exists
        nodes = cmds.file(
            file_path,
            reference=True,
            namespace=namespace,
            groupReference=False,
            loadReferenceDepth="all",
            returnNewNodes=True
        )

        print(f"[Reference File] Successfully referenced: {namespace}")
        return True

    except Exception as exc:
        _log.error("Maya reference command failed: %s", exc)
        return False