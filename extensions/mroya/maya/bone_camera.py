"""Bone camera rig utilities for Maya.

Creates a minimal joint hierarchy (root + camera joint) with a 1×1×1 cm
proxy-box mesh skin-bound to the root joint.  The camera joint is then
constrained to a source camera, baked across the frame range, and the
whole rig is exported as FBX for game-engine import.

Typical workflow
----------------
1.  root_jnt, cam_jnt, box = create_bone_camera_rig(camera_transform)
2.  bake_bone_camera_rig(cam_jnt, camera_transform, start_frame, end_frame)
3.  export_bone_camera(root_jnt, box, file_path)
4.  cleanup_bone_camera_rig(root_jnt, box)

Hierarchy produced
------------------
  {prefix}_root_jnt            ← stays at world origin
      └── {prefix}_cam_jnt     ← receives baked camera animation
  {prefix}_proxy_box           ← 1×1×1 cm mesh, skin-bound to root_jnt
"""
from __future__ import annotations

import logging

import maya.cmds as cmds

_log = logging.getLogger(__name__)

_TRANSFORM_ATTRS = [
    "translateX", "translateY", "translateZ",
    "rotateX",    "rotateY",    "rotateZ",
]


# ---------------------------------------------------------------------------
# Rig creation
# ---------------------------------------------------------------------------

def create_bone_camera_rig(camera_transform: str) -> tuple[str, str, str]:
    """Build the bone camera rig in the current scene.

    The root joint is placed at the world origin and stays there.
    The camera joint (child of root) is also at the origin in the bind
    pose — it receives the baked camera animation in a later step.
    A 1×1×1 cm proxy box mesh is created and skin-bound to the root joint
    so the hierarchy is valid for engine import.

    Args:
        camera_transform: Short or long name of the source camera transform.
            Used only to derive a node-name prefix.

    Returns:
        Tuple of (root_joint, camera_joint, box_transform).
    """
    # Sanitise camera name to produce a clean node-name prefix
    short = camera_transform.rsplit("|", 1)[-1]
    prefix = short.replace(":", "_")

    # ------------------------------------------------------------------ joints
    cmds.select(clear=True)
    root_joint = cmds.joint(name=f"{prefix}_root_jnt", position=(0, 0, 0))
    # With root_joint selected, the next joint() becomes its child
    camera_joint = cmds.joint(name=f"{prefix}_cam_jnt", position=(0, 0, 0))

    # ----------------------------------------------------------- proxy box mesh
    box_transform = cmds.polyCube(
        width=1, height=1, depth=1,
        name=f"{prefix}_proxy_box",
    )[0]

    # --------------------------------------------------------- skin cluster
    # Bind the box to the root joint only (not camera_joint).
    # toSelectedBones=True ensures only the explicitly listed joint is used.
    cmds.skinCluster(
        root_joint, box_transform,
        name=f"{prefix}_skin",
        toSelectedBones=True,
    )

    _log.info(
        "Bone camera rig created: root=%s  cam=%s  box=%s",
        root_joint, camera_joint, box_transform,
    )
    return root_joint, camera_joint, box_transform


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------

def bake_bone_camera_rig(
    camera_joint: str,
    camera_transform: str,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> None:
    """Constrain *camera_joint* to *camera_transform*, bake, then delete the constraint.

    Args:
        camera_joint: The joint whose animation will be baked.
        camera_transform: Source camera transform to follow.
        start_frame: First frame to bake. Defaults to scene playback start.
        end_frame: Last frame to bake. Defaults to scene playback end.
    """
    start = (
        start_frame if start_frame is not None
        else int(cmds.playbackOptions(query=True, minTime=True))
    )
    end = (
        end_frame if end_frame is not None
        else int(cmds.playbackOptions(query=True, maxTime=True))
    )

    parent_con = cmds.parentConstraint(
        camera_transform, camera_joint, maintainOffset=False,
    )[0]

    bake_attrs = [f"{camera_joint}.{attr}" for attr in _TRANSFORM_ATTRS]
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

    cmds.delete(parent_con)
    _log.info(
        "Baked bone camera joint '%s' ← '%s' (%s–%s)",
        camera_joint, camera_transform, start, end,
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_bone_camera(
    root_joint: str,
    box_transform: str,
    file_path: str,
    ascii: bool = True,
) -> str:
    """Export the bone camera rig as FBX.

    Selects root_joint and box_transform with hierarchy=True so FBX picks up
    child joints, mesh shapes, and the skin cluster automatically.
    Triangulation is handled by the FBX exporter flag (no mesh modification).

    Args:
        root_joint: Root joint of the rig (camera_joint is its child).
        box_transform: Proxy box mesh transform.
        file_path: Destination .fbx path (extension must be .fbx).
        ascii: Write ASCII FBX when True (default), binary otherwise.

    Returns:
        The exported file path.
    """
    # Select everything related to the rig — hierarchy=True picks up child
    # joints and mesh shapes so FBX sees the full skeletal mesh.
    cmds.select(clear=True)
    cmds.select([root_joint, box_transform], replace=True, hierarchy=True)

    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")

    import maya.mel as mel
    mel.eval(f'FBXExportInAscii -v {"true" if ascii else "false"}')
    mel.eval('FBXExportTriangulate -v true')

    from pathlib import Path
    base = str(Path(file_path).parent / Path(file_path).stem)
    cmds.file(base, force=True, type="FBX export", exportSelected=True)

    _log.info("Exported bone camera FBX (ascii=%s): %s", ascii, file_path)
    return file_path


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_bone_camera_rig(root_joint: str, box_transform: str) -> None:
    """Delete the temporary rig nodes from the scene.

    Deletes *root_joint* (which also removes its child camera_joint) and
    *box_transform* (the proxy mesh, including its shape and skin cluster).
    """
    for node in (root_joint, box_transform):
        if cmds.objExists(node):
            cmds.delete(node)
            _log.info("Deleted temp bone-camera node: %s", node)
