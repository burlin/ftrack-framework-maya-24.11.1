"""Component metadata collection for Maya publishes."""
from __future__ import annotations

import maya.cmds as cmds


def collect_component_metadata() -> dict:
    """Collect metadata from the current Maya session.

    Returns a dict suitable for ComponentData.metadata.
    Extend this function to add more metadata in the future.
    """
    meta = {}

    # DCC identifier
    meta['dcc'] = 'maya'

    # Maya version (e.g. "2024", "2025")
    try:
        meta['dcc_version'] = cmds.about(version=True)
    except Exception:
        pass

    return meta
