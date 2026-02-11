"""Playblast creation for Maya."""
from __future__ import annotations

import logging
import tempfile
import os

import maya.cmds as cmds

_log = logging.getLogger(__name__)

DEFAULT_CAMERAS = {"persp", "top", "front", "side"}


def get_scene_cameras() -> list[str]:
    """Return non-default cameras in the scene.

    If no user cameras exist, returns ``["persp"]`` as fallback.
    """
    all_cameras = cmds.ls(type="camera", long=True) or []
    user_cameras = []
    for cam_shape in all_cameras:
        transform = cmds.listRelatives(cam_shape, parent=True, fullPath=True)
        if not transform:
            continue
        short_name = transform[0].rsplit("|", 1)[-1]
        if short_name not in DEFAULT_CAMERAS:
            user_cameras.append(short_name)

    return user_cameras if user_cameras else ["persp"]


def create_playblast(
    camera: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Create a playblast from the given camera.

    Args:
        camera: Camera transform name to look through.
        width: Output width in pixels.
        height: Output height in pixels.

    Returns:
        The file path of the created playblast movie.
    """
    temp_file = tempfile.NamedTemporaryFile(suffix=".mov", delete=False)
    temp_file_path = temp_file.name
    temp_file.close()

    cmds.lookThru(camera)

    cmds.setAttr("defaultRenderGlobals.imageFormat", 8)  # QuickTime (.mov)

    cmds.headsUpDisplay(
        "CameraHUD",
        section=5,
        block=9,
        blockSize="small",
        label="Current Frame:",
        labelFontSize="large",
        pre="currentFrame",
    )

    result_path = cmds.playblast(
        st=cmds.playbackOptions(q=True, min=True),
        et=cmds.playbackOptions(q=True, max=True),
        format="qt",
        filename=temp_file_path,
        width=width,
        height=height,
        showOrnaments=True,
        percent=100,
        compression="photo - JPEG",
        quality=100,
        viewer=False,
        offScreen=True,
        fo=True,
    )

    cmds.headsUpDisplay("CameraHUD", remove=True)

    _log.info("Created playblast: %s (camera: %s)", result_path, camera)
    return result_path
