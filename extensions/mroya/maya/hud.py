"""Maya HUD showing ftrack context: user, project, shot/task, camera and focal length."""
from __future__ import annotations

import logging
import os

import maya.cmds as cmds

_log = logging.getLogger(__name__)

_HUD_NAMES = [
    'MroyaHUD_Project',
    'MroyaHUD_Shot',
    'MroyaHUD_User',
    'MroyaHUD_Camera',
    'MroyaHUD_FocalLen',
]

# ── camera helpers ────────────────────────────────────────────────────────────

def _active_camera_transform() -> str:
    """Return the transform name of the camera in the focused model panel."""
    try:
        panel = cmds.getPanel(withFocus=True)
        if panel and cmds.getPanel(typeOf=panel) == 'modelPanel':
            cam = cmds.modelEditor(panel, q=True, camera=True)
            if cam:
                return cam
    except Exception:
        pass
    # Fallback: first model panel found
    try:
        for p in cmds.getPanel(type='modelPanel') or []:
            cam = cmds.modelEditor(p, q=True, camera=True)
            if cam:
                return cam
    except Exception:
        pass
    return ''


def _hud_camera_name() -> str:
    """HUD callback: short name of the active camera."""
    try:
        cam = _active_camera_transform()
        return cam.split('|')[-1] if cam else '—'
    except Exception:
        return '—'


def _hud_focal_length() -> str:
    """HUD callback: focal length of the active camera."""
    try:
        cam = _active_camera_transform()
        if not cam:
            return '—'
        shapes = cmds.listRelatives(cam, shapes=True, type='camera') or []
        cam_shape = shapes[0] if shapes else cam
        fl = cmds.getAttr(f'{cam_shape}.focalLength')
        return f'{fl:.1f} mm'
    except Exception:
        return '—'


# ── ftrack helpers ────────────────────────────────────────────────────────────

def _fetch_ftrack_context() -> tuple[str, str, str]:
    """Return (project_name, parent_name, task_name) from the current context.

    Queries as Task (the typical FTRACK_CONTEXTID entity type).
    Falls back to empty strings on any error.
    """
    task_id = os.environ.get('FTRACK_CONTEXTID', '')
    if not task_id:
        return '', '', ''

    try:
        from mroya.maya.ftrack_session import _get_ftrack_session
        session = _get_ftrack_session()
        if not session:
            return '', '', ''

        task = session.query(
            f'select name, parent.name, project.name '
            f'from Task where id is "{task_id}"'
        ).first()

        if task:
            project_name = (task.get('project') or {}).get('name', '')
            parent_name  = (task.get('parent')  or {}).get('name', '')
            task_name    = task.get('name', '')
            return project_name, parent_name, task_name

        # Fallback: might be a Shot/Sequence context, not a Task
        ctx = session.query(
            f'select name, parent.name '
            f'from Context where id is "{task_id}"'
        ).first()
        if ctx:
            parent_name = (ctx.get('parent') or {}).get('name', '')
            return '', parent_name, ctx.get('name', '')

        return '', '', ''

    except Exception as exc:
        _log.warning('HUD: could not fetch ftrack context: %s', exc)
        return '', '', ''


# ── public API ────────────────────────────────────────────────────────────────

def remove_hud() -> None:
    """Remove all Mroya HUD elements."""
    for name in _HUD_NAMES:
        try:
            if cmds.headsUpDisplay(name, exists=True):
                cmds.headsUpDisplay(name, remove=True)
        except Exception:
            pass


def install_hud() -> None:
    """Create Mroya HUD elements in Maya's viewport (top-right corner)."""
    remove_hud()

    user         = os.environ.get('FTRACK_API_USER', '')
    project_name, shot_name, task_name = _fetch_ftrack_context()

    task_label = f'{shot_name} / {task_name}' if (shot_name and task_name) else (shot_name or task_name)

    # Section 5 = top-right.  Use nextFreeBlock so we never clash with
    # Maya's built-in HUDs that may already occupy fixed block numbers.
    section = 5

    _static = [
        ('MroyaHUD_Project',  f'Project:  {project_name}',  None,              None),
        ('MroyaHUD_Shot',     f'Task:     {task_label}',    None,              None),
        ('MroyaHUD_User',     f'User:     {user}',          None,              None),
    ]
    _dynamic = [
        ('MroyaHUD_Camera',   'Camera:    ', _hud_camera_name,  'SelectionChanged'),
        ('MroyaHUD_FocalLen', 'Focal:     ', _hud_focal_length, 'timeChanged'),
    ]

    for hud_name, label, cmd, event in _static + _dynamic:
        block = cmds.headsUpDisplay(nextFreeBlock=section)
        kwargs = dict(section=section, block=block, blockSize='small', labelFontSize='large')
        if cmd:
            kwargs.update(label=label, dataFontSize='large', command=cmd, event=event)
        else:
            kwargs['label'] = label
        cmds.headsUpDisplay(hud_name, **kwargs)

    _log.info(
        'Mroya HUD installed — project=%r  parent=%r  task=%r  user=%r',
        project_name, shot_name, task_name, user,
    )
    print(f'[mroya_hud] HUD installed — {project_name} / {task_label} / {user}')
