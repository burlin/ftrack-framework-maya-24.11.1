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
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> str:
    """Create a playblast from the given camera.

    Args:
        camera: Camera transform name to look through.
        width: Output width in pixels.
        height: Output height in pixels.
        start_frame: First frame to render. Defaults to scene playback start.
        end_frame: Last frame to render. Defaults to scene playback end.

    Returns:
        The file path of the created playblast movie.
    """
    temp_file = tempfile.NamedTemporaryFile(suffix=".mov", delete=False)
    temp_file_path = temp_file.name
    temp_file.close()

    cmds.lookThru(camera)

    cmds.setAttr("defaultRenderGlobals.imageFormat", 8)  # QuickTime (.mov)

    # Enable Maya's native camera-name HUD; restore previous state after blast.
    prev_cam_hud = cmds.headsUpDisplay("HUDCameraNames", query=True, visible=True)
    cmds.headsUpDisplay("HUDCameraNames", edit=True, visible=True)

    st = start_frame if start_frame is not None else cmds.playbackOptions(q=True, min=True)
    et = end_frame if end_frame is not None else cmds.playbackOptions(q=True, max=True)

    try:
        result_path = cmds.playblast(
            st=st,
            et=et,
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
    finally:
        cmds.headsUpDisplay("HUDCameraNames", edit=True, visible=prev_cam_hud)

    _log.info("Created playblast: %s (camera: %s)", result_path, camera)
    return result_path


def create_turnaround_playblast(
    objects: list[str],
    width: int = 1920,
    height: int = 1080,
    frames: int = 150,
) -> str:
    """Create a 360° turnaround playblast around the bounding box of *objects*.

    Builds a temporary pivot group at the bounding-box centre, parents a
    camera at *radius* distance, animates a full rotation over *frames* frames,
    blasts, then cleans everything up.

    Args:
        objects: Maya transforms whose combined bounding box defines the focus.
        width: Output width in pixels.
        height: Output height in pixels.
        frames: Number of frames for a full 360° orbit (default 50).

    Returns:
        File path of the created playblast movie.
    """
    if not objects:
        raise ValueError("No objects provided for turnaround playblast")

    # --- Bounding box ---
    bb = cmds.exactWorldBoundingBox(*objects, calculateExactly=True)
    xmin, ymin, zmin, xmax, ymax, zmax = bb
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    cz = (zmin + zmax) / 2.0

    max_extent = max(xmax - xmin, ymax - ymin, zmax - zmin)
    if max_extent < 0.001:
        max_extent = 1.0  # fallback for degenerate bbox

    radius = max_extent * 1.5
    # Place pivot slightly above centre so the camera looks down on the object
    elevation = (ymax - ymin) * 0.31
    tilt_angle = -2.0  # degrees — gentle downward look


    # --- Build temporary rig ---
    pivot = cmds.group(empty=True, name="mroya_turnaround_pivot_tmp")
    cmds.move(cx, cy + elevation, cz, pivot, absolute=True)

    cam_t, _cam_s = cmds.camera(name="mroya_turnaround_cam_tmp")
    cmds.parent(cam_t, pivot)
    for attr in ["tx", "ty", "tz", "rx", "ry", "rz"]:
        cmds.setAttr(f"{cam_t}.{attr}", 0)
    # Camera sits radius units along +Z from pivot; Maya cameras face -Z so
    # they naturally point back toward the pivot centre.
    cmds.setAttr(f"{cam_t}.translateZ", radius)
    cmds.setAttr(f"{cam_t}.rotateX", tilt_angle)

    # Animate pivot Y: 0 → 360 with linear tangents so speed is constant
    cmds.setKeyframe(pivot, attribute="rotateY", time=1, value=0)
    cmds.setKeyframe(pivot, attribute="rotateY", time=frames, value=360)
    cmds.keyTangent(
        pivot, attribute="rotateY",
        inTangentType="linear", outTangentType="linear",
    )

    # Deselect everything — keeps the viewport clean
    cmds.select(clear=True)

    # --- Playblast ---
    temp_file = tempfile.NamedTemporaryFile(suffix=".mov", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    try:
        cmds.lookThru(cam_t)
        result_path = cmds.playblast(
            st=1,
            et=frames,
            format="qt",
            filename=temp_path,
            width=width,
            height=height,
            showOrnaments=False,
            percent=100,
            compression="photo - JPEG",
            quality=100,
            viewer=False,
            offScreen=True,
            fo=True,
        )
    finally:
        # Always clean up — pivot deletion removes the camera child too
        try:
            cmds.delete(pivot)
        except Exception:
            pass

    _log.info("Created turnaround playblast: %s (%d frames)", result_path, frames)
    return result_path
