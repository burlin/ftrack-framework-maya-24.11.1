"""Camera bake-and-export utilities for Maya.

Workflow:
1. Duplicate the source camera to a temp ``{name}_PIPE`` camera.
2. Parent-constrain + aim-constrain the duplicate to the original.
3. Bake all transform and camera-specific attributes.
4. Delete constraints, export the baked camera to FBX.
5. Delete the temp camera from the scene.
"""
from __future__ import annotations

import logging

import maya.cmds as cmds

_log = logging.getLogger(__name__)

# Attributes baked onto the temp camera
_TRANSFORM_ATTRS = [
    "translateX", "translateY", "translateZ",
    "rotateX", "rotateY", "rotateZ",
]

_CAMERA_ATTRS = [
    "focalLength",
    "horizontalFilmAperture",
    "verticalFilmAperture",
    "nearClipPlane",
    "farClipPlane",
    "lensSqueezeRatio",
    "fStop",
    "focusDistance",
    "shutterAngle",
    "centerOfInterest",
]


def is_camera(obj_name: str) -> bool:
    """Return True if *obj_name* is (or has) a camera shape node."""
    if not cmds.objExists(obj_name):
        return False
    if cmds.objectType(obj_name) == "camera":
        return True
    shapes = cmds.listRelatives(obj_name, shapes=True, fullPath=True) or []
    return any(cmds.objectType(s) == "camera" for s in shapes)


def _get_camera_shape(transform: str) -> str | None:
    """Return the first camera shape under *transform*, or None."""
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    for s in shapes:
        if cmds.objectType(s) == "camera":
            return s
    return None


def prepare_camera(camera_transform: str) -> str:
    """Duplicate *camera_transform*, bake animation, return the temp camera name.

    The duplicate is named ``{camera_transform}_PIPE`` and lives at world
    level.  All transform and camera-specific channels are baked across the
    timeline range so the result is a clean, standalone camera ready for
    export.

    Args:
        camera_transform: Name of the source camera transform node.

    Returns:
        The name of the baked temp camera transform.

    Raises:
        RuntimeError: If duplication or baking fails.
    """
    if not cmds.objExists(camera_transform):
        raise RuntimeError(f"Camera '{camera_transform}' does not exist")

    src_shape = _get_camera_shape(camera_transform)
    if src_shape is None:
        raise RuntimeError(f"'{camera_transform}' has no camera shape")

    temp_name = f"{camera_transform}_PIPE"

    # Duplicate camera (without children/input connections)
    dup = cmds.duplicate(camera_transform, name=temp_name, returnRootsOnly=True)[0]

    # Ensure it lives at world level
    parent = cmds.listRelatives(dup, parent=True, fullPath=True)
    if parent:
        dup = cmds.parent(dup, world=True)[0]

    dup_shape = _get_camera_shape(dup)

    # ------------------------------------------------------------------
    # Constrain the duplicate to follow the original
    # ------------------------------------------------------------------
    parent_con = cmds.parentConstraint(camera_transform, dup, maintainOffset=False)[0]

    # Connect camera-specific attrs so they follow the source during bake
    cam_connections = []
    for attr in _CAMERA_ATTRS:
        src_plug = f"{src_shape}.{attr}"
        dst_plug = f"{dup_shape}.{attr}"
        if cmds.objExists(src_plug) and cmds.objExists(dst_plug):
            try:
                cmds.connectAttr(src_plug, dst_plug, force=True)
                cam_connections.append((src_plug, dst_plug))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Bake
    # ------------------------------------------------------------------
    start = cmds.playbackOptions(query=True, minTime=True)
    end = cmds.playbackOptions(query=True, maxTime=True)

    # Build list of attrs to bake
    bake_attrs = [f"{dup}.{a}" for a in _TRANSFORM_ATTRS]
    if dup_shape:
        bake_attrs += [f"{dup_shape}.{a}" for a in _CAMERA_ATTRS
                       if cmds.objExists(f"{dup_shape}.{a}")]

    cmds.bakeResults(
        bake_attrs,
        time=(start, end),
        sampleBy=1,
        oversamplingRate=1,
        disableImplicitControl=True,
        preserveOutsideKeys=True,
        sparseAnimCurveBake=False,
        simulation=False,
    )

    # ------------------------------------------------------------------
    # Clean up constraints and connections
    # ------------------------------------------------------------------
    cmds.delete(parent_con)

    for src_plug, dst_plug in cam_connections:
        try:
            cmds.disconnectAttr(src_plug, dst_plug)
        except Exception:
            pass

    # Visual indicator — colour the temp camera red in the outliner
    try:
        cmds.setAttr(f"{dup}.useOutlinerColor", True)
        cmds.setAttr(f"{dup}.outlinerColor", 1, 0, 0)
    except Exception:
        pass

    _log.info(
        "Prepared baked camera '%s' from '%s' (frames %s-%s)",
        dup, camera_transform, int(start), int(end),
    )
    return dup


def cleanup_temp_camera(temp_camera: str):
    """Delete the temporary baked camera from the scene."""
    if cmds.objExists(temp_camera):
        cmds.delete(temp_camera)
        _log.info("Deleted temp camera: %s", temp_camera)
