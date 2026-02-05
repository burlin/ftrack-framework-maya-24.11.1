"""
Mroya Task Hub launcher integration for Maya.

Runs inside Maya (via ftrack-framework-maya userSetup.py) and:
- adds menu item that opens embedded Qt browser Task Hub;
- creates/shows Qt browser widget in the same Maya process, using
  PySide6 Maya 2026+ and shared browser code from ftrack_inout.browser.

This approach:
- doesn't require separate process/window;
- uses environment prepared by ftrack Connect (FTRACK_* etc.);
- keeps all DCC-specific code in one place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

import maya.cmds as cmds
import maya.OpenMayaUI as omui
import maya.mel as mel

try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
    from shiboken6 import wrapInstance  # type: ignore
    PYSIDE6_AVAILABLE = True
except Exception:  # pragma: no cover - old Maya without PySide6
    QtWidgets = None  # type: ignore
    QtCore = None  # type: ignore
    wrapInstance = None  # type: ignore
    PYSIDE6_AVAILABLE = False


_browser_widget = None  # type: ignore[var-annotated]
_user_tasks_window = None  # type: ignore[var-annotated]
_publisher_window = None  # type: ignore[var-annotated]
_selection_script_job = None  # type: ignore[var-annotated]


def _find_project_root() -> Path:
    """Determine Mroya project root.

    Priority:
    1) MROOT environment variable, if run_browser.py exists there.
    2) Search upward from this file to directory containing run_browser.py.
    3) Fallback: two levels up from plugin root (usually G:/mroya).
    """
    env_root = os.environ.get("MROOT")
    if env_root:
        env_path = Path(env_root)
        if (env_path / "run_browser.py").is_file():
            return env_path

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "run_browser.py").is_file():
            return parent

    # Usually structure: G:/mroya/ftrack_plugins/ftrack-framework-maya-24.11.1/resource/bootstrap/...
    # Go up three levels to G:/mroya.
    return here.parents[3]


def _bootstrap_python_paths() -> Path:
    """Add MROOT and ftrack_plugins to sys.path for importing mroya_task_hub etc.

    Returns project root.
    """
    project_root = _find_project_root()
    plugins_root = project_root / "ftrack_plugins"

    for path in (project_root, plugins_root):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    # Add ftrack_inout dependencies (fileseq, boto3, ftrack_api, etc.)
    ftrack_inout_deps = plugins_root / "ftrack_inout" / "dependencies"
    if ftrack_inout_deps.is_dir():
        deps_str = str(ftrack_inout_deps)
        if deps_str not in sys.path:
            sys.path.insert(0, deps_str)
            print(f"[mroya_maya_taskhub] Added ftrack_inout dependencies to sys.path: {deps_str}")

    # Also add maya plugin's own dependencies (for ftrack_api, etc.)
    here = Path(__file__).resolve()
    plugin_root = here.parents[2]  # .../ftrack-framework-maya-24.11.1
    plugin_deps = plugin_root / "dependencies"
    if plugin_deps.is_dir():
        deps_str = str(plugin_deps)
        if deps_str not in sys.path:
            sys.path.insert(0, deps_str)
            print(f"[mroya_maya_taskhub] Added maya plugin dependencies to sys.path: {deps_str}")

    return project_root


def _get_maya_main_window():
    """Get QWidget of Maya main window for attaching our window."""
    if not PYSIDE6_AVAILABLE or QtWidgets is None or wrapInstance is None:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception as exc:  # pragma: no cover
        print("[mroya_maya_taskhub] Failed to get Maya main window:", exc)
        return None


def launch_task_browser(*_args, **_kwargs) -> None:
    """Maya menu callback: open embedded Task Hub browser."""
    global _browser_widget

    if not PYSIDE6_AVAILABLE:
        print(
            "[mroya_maya_taskhub] PySide6 is not available in this Maya. "
            "Embedded browser is supported on Maya 2026+."
        )
        return

    project_root = _bootstrap_python_paths()

    # Detailed import logging
    print(f"[mroya_maya_taskhub] Project root: {project_root}")
    print(f"[mroya_maya_taskhub] sys.path entries: {len(sys.path)}")
    
    try:
        print("[mroya_maya_taskhub] Importing ftrack_inout.browser...")
        from ftrack_inout.browser import FtrackBrowser  # type: ignore
        print("[mroya_maya_taskhub] ✅ Successfully imported FtrackBrowser from ftrack_inout.browser")
    except Exception as exc:
        import traceback
        print(
            f"[mroya_maya_taskhub] ❌ Failed to import FtrackBrowser from ftrack_inout.browser "
            f"(project_root={project_root}): {exc}"
        )
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")
        return

    # Create widget if it's not yet created or was closed.
    try:
        if _browser_widget is None or not _browser_widget.isVisible():
            print("[mroya_maya_taskhub] Creating FtrackBrowser widget...")
            _browser_widget = FtrackBrowser()
            main_window = _get_maya_main_window()
            if main_window is not None:
                _browser_widget.setParent(main_window)
                _browser_widget.setWindowFlags(QtCore.Qt.Window)  # type: ignore[union-attr]
            print("[mroya_maya_taskhub] ✅ FtrackBrowser widget created")

        _browser_widget.show()
        _browser_widget.raise_()
        _browser_widget.activateWindow()
        print("[mroya_maya_taskhub] ✅ Embedded Task Hub browser shown in Maya.")
    except Exception as exc:
        import traceback
        print(f"[mroya_maya_taskhub] ❌ Failed to show embedded browser: {exc}")
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")


def launch_user_tasks(*_args, **_kwargs) -> None:
    """Open User Tasks window (UserTasksWidget) inside Maya.

    Behavior similar to Houdini launcher: separate dialog on top of Maya.
    """
    global _user_tasks_window

    if not PYSIDE6_AVAILABLE:
        print(
            "[mroya_maya_taskhub] PySide6 is not available in this Maya. "
            "Embedded User Tasks require Maya 2026+."
        )
        return

    project_root = _bootstrap_python_paths()

    # Detailed import logging
    print(f"[mroya_maya_taskhub] Project root: {project_root}")
    print(f"[mroya_maya_taskhub] sys.path entries: {len(sys.path)}")
    
    try:
        print("[mroya_maya_taskhub] Importing ftrack_inout.browser...")
        from ftrack_inout import browser as fbrowser  # type: ignore
        print("[mroya_maya_taskhub] ✅ Successfully imported ftrack_inout.browser")
    except Exception as exc:
        import traceback
        print(
            f"[mroya_maya_taskhub] ❌ Failed to import ftrack_inout.browser "
            f"(project_root={project_root}): {exc}"
        )
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")
        return

    try:
        print("[mroya_maya_taskhub] Importing ftrack_inout.browser.dcc.maya...")
        from ftrack_inout.browser.dcc.maya import MayaUserTasksHandlers  # type: ignore
        print("[mroya_maya_taskhub] ✅ Successfully imported MayaUserTasksHandlers")
    except Exception as exc:
        import traceback
        print(
            f"[mroya_maya_taskhub] ❌ Failed to import MayaUserTasksHandlers: {exc}"
        )
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")
        return

    widget_cls = getattr(fbrowser, "UserTasksWidget", None)
    if widget_cls is None:
        print("[mroya_maya_taskhub] ❌ UserTasksWidget is not available in ftrack_inout.browser")
        print(f"[mroya_maya_taskhub] Available attributes: {[attr for attr in dir(fbrowser) if not attr.startswith('_')]}")
        return
    
    print(f"[mroya_maya_taskhub] ✅ UserTasksWidget found: {widget_cls}")

    # If window is already open and alive — just raise it.
    try:
        if _user_tasks_window is not None and _user_tasks_window.isVisible():
            _user_tasks_window.raise_()
            _user_tasks_window.activateWindow()
            return
    except Exception:
        _user_tasks_window = None

    main_window = _get_maya_main_window()

    window = QtWidgets.QDialog(main_window)
    window.setWindowTitle("User Tasks - Mroya")
    layout = QtWidgets.QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)

    try:
        tasks_widget = widget_cls(dcc_handlers=MayaUserTasksHandlers())  # type: ignore[call-arg]
    except Exception as exc:
        print(f"[mroya_maya_taskhub] Failed to create UserTasksWidget: {exc}")
        return

    layout.addWidget(tasks_widget)
    window.resize(900, 600)
    window.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

    _user_tasks_window = window
    window.show()


def create_publisher_node(*_args, **_kwargs) -> None:
    """Create publisher node in Maya scene and open Publisher UI."""
    _bootstrap_python_paths()
    
    try:
        from ftrack_inout.publisher.dcc.maya import create_publisher_node as _create_node
        node_name = _create_node()
        cmds.select(node_name)
        print(f"[mroya_maya_taskhub] ✅ Created publisher node: {node_name}")
        
        # Open Publisher window
        _open_publisher_window(node_name)
    except Exception as exc:
        import traceback
        print(f"[mroya_maya_taskhub] ❌ Failed to create publisher node: {exc}")
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")


def open_ftrack_input_window_callback(*_args, **_kwargs) -> None:
    """Open Ftrack Input window (finput-like loader) from menu."""
    _bootstrap_python_paths()

    try:
        from ftrack_inout.browser.dcc.maya import open_ftrack_input_window
        if open_ftrack_input_window:
            open_ftrack_input_window()
            print("[mroya_maya_taskhub] ✅ Opened Ftrack Input window")
        else:
            print("[mroya_maya_taskhub] ❌ Ftrack Input not available (PySide/Maya)")
    except Exception as exc:
        import traceback
        print(f"[mroya_maya_taskhub] ❌ Failed to open Ftrack Input: {exc}")
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")


# ============================================================================
# Publisher Window (full UI like Houdini HDA)
# ============================================================================

def _is_publisher_node(node_name: str) -> bool:
    """Check if node is a Mroya publisher node."""
    if not node_name or not cmds.objExists(node_name):
        return False
    return cmds.attributeQuery("isMroyaPublisher", node=node_name, exists=True)


def _open_publisher_window(node_name: str = None):
    """Open full Publisher window for given node."""
    global _publisher_window
    
    if not PYSIDE6_AVAILABLE:
        print("[mroya_maya_taskhub] PySide6 is not available")
        return
    
    _bootstrap_python_paths()
    
    # Get node from selection if not provided
    if node_name is None:
        selection = cmds.ls(selection=True)
        if selection:
            node_name = selection[0]
        else:
            cmds.warning("Please select a publisher node first")
            return
    
    # Check if it's a publisher node
    if not _is_publisher_node(node_name):
        cmds.warning(f"Node '{node_name}' is not a Mroya publisher node")
        return
    
    try:
        from ftrack_inout.publisher.dcc.maya.maya_publisher_window import show_publisher_window
        _publisher_window = show_publisher_window(node_name)
        print(f"[mroya_maya_taskhub] ✅ Opened Publisher window for: {node_name}")
    except Exception as exc:
        import traceback
        print(f"[mroya_maya_taskhub] ❌ Failed to open Publisher window: {exc}")
        print(f"[mroya_maya_taskhub] Traceback:\n{traceback.format_exc()}")


def _on_selection_changed():
    """Called when selection changes - show/hide publisher toolbar (not the full window)."""
    sel = cmds.ls(selection=True)
    if sel and _is_publisher_node(sel[0]):
        # Show toolbar only, not the full window
        _show_publisher_toolbar(sel[0])
    else:
        _hide_publisher_toolbar()


# ============================================================================
# Compact Publisher Toolbar (docked buttons)
# ============================================================================

_publisher_toolbar = None


def _show_publisher_toolbar(node_name: str):
    """Show compact toolbar with publisher buttons."""
    global _publisher_toolbar
    
    if not PYSIDE6_AVAILABLE:
        return
    
    # Create toolbar if needed
    if _publisher_toolbar is None:
        _publisher_toolbar = _create_publisher_toolbar()
        print(f"[mroya_maya_taskhub] Publisher toolbar created")
    
    # Update node reference
    _publisher_toolbar.node_name = node_name
    _publisher_toolbar.node_label.setText(f"📦 {node_name}")
    
    # Position near top of Maya window
    main_window = _get_maya_main_window()
    if main_window:
        main_geo = main_window.geometry()
        _publisher_toolbar.move(main_geo.x() + 100, main_geo.y() + 80)
    
    _publisher_toolbar.show()
    _publisher_toolbar.raise_()
    _publisher_toolbar.activateWindow()
    print(f"[mroya_maya_taskhub] Toolbar shown for: {node_name}")


def _hide_publisher_toolbar():
    """Hide publisher toolbar."""
    global _publisher_toolbar
    if _publisher_toolbar is not None and _publisher_toolbar.isVisible():
        _publisher_toolbar.hide()
        print("[mroya_maya_taskhub] Toolbar hidden")


def _create_publisher_toolbar():
    """Create compact floating toolbar with publisher buttons."""
    main_window = _get_maya_main_window()
    
    toolbar = QtWidgets.QWidget(main_window, QtCore.Qt.Window | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
    toolbar.setWindowTitle("Mroya Publisher")
    toolbar.setFixedHeight(55)
    toolbar.setMinimumWidth(450)
    toolbar.node_name = None
    
    # Style - more visible
    toolbar.setStyleSheet("""
        QWidget { 
            background-color: #2d4a3d; 
            border: 2px solid #4a8a6a;
            border-radius: 5px;
        }
        QLabel {
            border: none;
            color: #ccc;
            font-size: 13px;
        }
        QPushButton { 
            padding: 8px 15px; 
            border-radius: 4px;
            font-weight: bold;
            font-size: 12px;
            border: 1px solid #555;
        }
        QPushButton:hover { background-color: #555; }
    """)
    
    layout = QtWidgets.QHBoxLayout(toolbar)
    layout.setContentsMargins(10, 5, 10, 5)
    layout.setSpacing(10)
    
    # Node label
    toolbar.node_label = QtWidgets.QLabel("📦 --")
    toolbar.node_label.setStyleSheet("color: #aaa; font-size: 12px;")
    layout.addWidget(toolbar.node_label)
    
    layout.addStretch()
    
    # Open UI button
    ui_btn = QtWidgets.QPushButton("📝 Open UI")
    ui_btn.setStyleSheet("background-color: #4a6a8a;")
    ui_btn.setToolTip("Open full Publisher interface")
    ui_btn.clicked.connect(lambda: _toolbar_open_ui(toolbar))
    layout.addWidget(ui_btn)
    
    # Test button
    test_btn = QtWidgets.QPushButton("🧪 Test")
    test_btn.setStyleSheet("background-color: #555566;")
    test_btn.setToolTip("Dry-run test")
    test_btn.clicked.connect(lambda: _toolbar_test(toolbar))
    layout.addWidget(test_btn)
    
    # Publish button
    publish_btn = QtWidgets.QPushButton("🚀 Publish")
    publish_btn.setStyleSheet("background-color: #336633;")
    publish_btn.setToolTip("Publish to Ftrack")
    publish_btn.clicked.connect(lambda: _toolbar_publish(toolbar))
    layout.addWidget(publish_btn)
    
    return toolbar


def _toolbar_open_ui(toolbar):
    """Open UI button clicked."""
    if toolbar.node_name:
        _open_publisher_window(toolbar.node_name)


def _toolbar_test(toolbar):
    """Test button clicked."""
    if toolbar.node_name:
        _bootstrap_python_paths()
        try:
            from ftrack_inout.publisher.dcc.maya import publish_dry_run_callback
            publish_dry_run_callback(toolbar.node_name)
        except Exception as e:
            cmds.warning(f"Test failed: {e}")


def _toolbar_publish(toolbar):
    """Publish button clicked."""
    if toolbar.node_name:
        _bootstrap_python_paths()
        try:
            from ftrack_inout.publisher.dcc.maya import publish_callback
            publish_callback(toolbar.node_name)
        except Exception as e:
            cmds.warning(f"Publish failed: {e}")


def _on_node_double_clicked():
    """Called on double-click - open publisher window."""
    sel = cmds.ls(selection=True)
    if sel and _is_publisher_node(sel[0]):
        _open_publisher_window(sel[0])


def _install_selection_callback():
    """Install scriptJob to track selection changes and open publisher window."""
    global _selection_script_job
    
    # Kill old job if exists
    if _selection_script_job is not None:
        try:
            cmds.scriptJob(kill=_selection_script_job, force=True)
        except Exception:
            pass
    
    # Create job for selection changes
    _selection_script_job = cmds.scriptJob(
        event=["SelectionChanged", _on_selection_changed],
        protected=True
    )
    
    print(f"[mroya_maya_taskhub] Publisher selection callback installed (job: {_selection_script_job})")


def _ensure_menu() -> str:
    """Create (or find) 'Mroya' menu in Maya main window and return its name."""
    # Maya 2026 doesn't have cmds.mel; use maya.mel module directly.
    main_window = mel.eval("$tmpVar=$gMainWindow")  # type: ignore[attr-defined]

    # Search for existing menu.
    for menu in cmds.window(main_window, q=True, menuArray=True) or []:
        label = cmds.menu(menu, q=True, label=True)
        if label == "Mroya":
            return menu

    # Create new menu on the right in main menu bar.
    menu_name = cmds.menu("MroyaMenu", label="Mroya", parent=main_window, tearOff=True)
    return menu_name


def install_menu() -> None:
    """Install menu items for Task Hub browser, User Tasks, and Publisher in Maya."""
    try:
        menu = _ensure_menu()

        # Remove old items if they already existed.
        existing_items = cmds.menu(menu, q=True, itemArray=True) or []
        old_labels = {
            "Open Task Browser", "Open User Tasks", "Ftrack Input",
            "Create Publisher Node", "Publisher UI", "Publisher Test", "Publish"
        }
        for item in list(existing_items):
            label = cmds.menuItem(item, q=True, label=True)
            if label in old_labels:
                cmds.deleteUI(item)

        # Item for main browser.
        cmds.menuItem(
            "MroyaTaskHubBrowser",
            label="Open Task Browser",
            parent=menu,
            command=lambda *_a, **_k: launch_task_browser(),
        )

        # Item for User Tasks window.
        cmds.menuItem(
            "MroyaUserTasks",
            label="Open User Tasks",
            parent=menu,
            command=lambda *_a, **_k: launch_user_tasks(),
        )

        # Item for Ftrack Input (finput-like loader).
        cmds.menuItem(
            "MroyaFtrackInput",
            label="Ftrack Input",
            parent=menu,
            command=lambda *_a, **_k: open_ftrack_input_window_callback(),
        )

        # Separator before Publisher section
        cmds.menuItem(divider=True, parent=menu)

        # Create Publisher Node only - buttons are on the node via AETemplate
        cmds.menuItem(
            "MroyaPublisherCreate",
            label="Create Publisher Node",
            parent=menu,
            command=lambda *_a, **_k: create_publisher_node(),
        )

        # Install selection callback for publisher panel
        _install_selection_callback()

        print(
            "[mroya_maya_taskhub] Menu installed under 'Mroya' -> "
            "'Open Task Browser', 'Open User Tasks', 'Ftrack Input', 'Create Publisher Node'"
        )
    except Exception as exc:
        print("[mroya_maya_taskhub] Failed to install menu:", exc)


