"""Ftrack publish node creation for Maya."""
from __future__ import annotations

import os
import logging

import maya.cmds as cmds

_log = logging.getLogger(__name__)

NODE_NAME = "ftrack_publish_unnamed"


def create_publish_node() -> str:
    """Create an empty Maya network node for ftrack publishing.

    The node is named ``ftrack_publish_unnamed`` and carries a single
    ``task_id`` attribute whose value is read from the ``FTRACK_CONTEXTID``
    environment variable (set by ftrack Connect when the scene is opened).

    Returns:
        The name of the created node.
    """
    task_id = os.environ.get("FTRACK_CONTEXTID", "")

    node = cmds.createNode("network", name=NODE_NAME)

    cmds.addAttr(node, longName="task_id", dataType="string")
    cmds.setAttr(f"{node}.task_id", task_id, type="string")

    cmds.addAttr(node, longName="asset_name", dataType="string")
    cmds.setAttr(f"{node}.asset_name", "Unnamed", type="string")

    cmds.addAttr(node, longName="playblast_camera", dataType="string")
    cmds.setAttr(f"{node}.playblast_camera", "", type="string")

    frame_start = int(cmds.playbackOptions(query=True, minTime=True))
    frame_end = int(cmds.playbackOptions(query=True, maxTime=True))
    cmds.addAttr(node, longName="frame_start", attributeType="long")
    cmds.setAttr(f"{node}.frame_start", frame_start)
    cmds.addAttr(node, longName="frame_end", attributeType="long")
    cmds.setAttr(f"{node}.frame_end", frame_end)

    cmds.addAttr(node, longName="bone_camera_export", attributeType="bool")
    cmds.setAttr(f"{node}.bone_camera_export", False)

    _log.info("Created publish node '%s' with task_id='%s'", node, task_id)
    return node
