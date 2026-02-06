"""Scene Resource Window - Temporary UI module.

This module provides a simple Qt window for managing scene resources.
TO BE REMOVED OR EXPANDED LATER.

Usage from Maya:
    from mroya.maya import open_scene_resource_window
    open_scene_resource_window()
"""
from __future__ import annotations

import logging
import os

try:
    from . import adding_component
except ImportError:
    # Fallback for testing if not in a package
    import adding_component

try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    MAYA_AVAILABLE: bool = True
except ImportError:
    cmds = None  # type: ignore
    omui = None  # type: ignore
    MAYA_AVAILABLE = False

try:
    from PySide6 import QtWidgets, QtCore
    from shiboken6 import wrapInstance
    PYSIDE_AVAILABLE: bool = True
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore
        from shiboken2 import wrapInstance
        PYSIDE_AVAILABLE = True
    except ImportError:
        QtWidgets = None  # type: ignore
        QtCore = None  # type: ignore
        wrapInstance = None  # type: ignore
        PYSIDE_AVAILABLE = False

_log = logging.getLogger(__name__)

# Singleton window reference
_window_instance = None


def _get_maya_main_window():
    """Get Maya main window as QWidget."""
    if not MAYA_AVAILABLE or not PYSIDE_AVAILABLE or wrapInstance is None:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception as exc:
        _log.error("Failed to get Maya main window: %s", exc)
        return None


class SceneResourceWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise RuntimeError("PySide6 or PySide2 is required")
        if parent is None:
            parent = _get_maya_main_window()
        super().__init__(parent)

        self.setWindowTitle("Scene Resource Window")
        self.setMinimumSize(600, 400)  # Made slightly wider for the new column
        self._setup_ui()
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        toolbar_layout = QtWidgets.QHBoxLayout()
        self._scan_btn = QtWidgets.QPushButton("Scan Scene")
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        toolbar_layout.addWidget(self._scan_btn)
        toolbar_layout.addStretch(1)
        layout.addLayout(toolbar_layout)

        # Results table - Added 3rd column
        self._results_table = QtWidgets.QTableWidget()
        self._results_table.setColumnCount(3)
        self._results_table.setHorizontalHeaderLabels(["Asset", "Component", "Actions"])
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._results_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self._results_table.setColumnWidth(2, 180)

        layout.addWidget(self._results_table)

        self._status_label = QtWidgets.QLabel("Click 'Scan' to find ftrack reference nodes")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_label)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        self._close_btn = QtWidgets.QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        button_layout.addWidget(self._close_btn)
        layout.addLayout(button_layout)

    def _on_scan_clicked(self):
        self._results_table.setRowCount(0)
        if not MAYA_AVAILABLE: return

        ftrack_nodes = []
        all_network_nodes = cmds.ls(type='network') or []
        for node in all_network_nodes:
            if cmds.attributeQuery('ftrack_asset_version_id', node=node, exists=True):
                ftrack_nodes.append(node)

        self._results_table.setRowCount(len(ftrack_nodes))

        for row, node in enumerate(ftrack_nodes):
            asset_name, component_name = self._get_node_display_data(node)
            path = cmds.getAttr(f"{node}.ftrack_component_path") if cmds.attributeQuery('ftrack_component_path',
                                                                                        node=node, exists=True) else ""

            # Asset and Component Items
            self._results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(asset_name))
            self._results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(component_name))

            # Create Action Widget (Dropdown + Button)
            action_widget = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)

            combo = QtWidgets.QComboBox()
            combo.addItems(["reference", "import"])

            btn = QtWidgets.QPushButton("Add")
            btn.setFixedWidth(50)
            # Connect using a lambda to pass the specific row's data
            btn.clicked.connect(lambda checked=False, p=path, c=combo: self._on_add_clicked(p, c))

            action_layout.addWidget(combo)
            action_layout.addWidget(btn)
            self._results_table.setCellWidget(row, 2, action_widget)

        self._status_label.setText(f"Found {len(ftrack_nodes)} node(s)")

    def _on_add_clicked(self, component_path: str, combo_box: QtWidgets.QComboBox):
        """Called when the 'Add' button in a row is clicked."""
        method = combo_box.currentText()

        if not component_path:
            _log.warning("No component path found for this node.")
            return

        # Call the logic from adding_component.py
        success = adding_component.add_component_to_scene(component_path, method)

        if success:
            self._status_label.setText(f"Successfully added via {method}")
        else:
            self._status_label.setText("Failed to add component.")

    def _get_node_display_data(self, node: str) -> tuple[str, str]:
        """Get display data for a node, including file extension."""
        asset_name = ""
        component_name = ""
        component_path = ""

        # Fetch attributes safely from the Maya node
        if cmds.attributeQuery('ftrack_asset_name', node=node, exists=True):
            asset_name = cmds.getAttr(f'{node}.ftrack_asset_name') or ""

        if cmds.attributeQuery('ftrack_component_name', node=node, exists=True):
            component_name = cmds.getAttr(f'{node}.ftrack_component_name') or ""

        if cmds.attributeQuery('ftrack_component_path', node=node, exists=True):
            component_path = cmds.getAttr(f'{node}.ftrack_component_path') or ""

        # Logic to append the extension (e.g., .fbx, .ma, .abc)
        if component_path:
            _, ext = os.path.splitext(component_path)
            if ext:
                # If we have a name like 'main' and ext '.fbx', result is 'main.fbx'
                if component_name:
                    component_name = f"{component_name}{ext}"
                else:
                    component_name = ext

        # Fallbacks for empty attributes
        asset_name = asset_name or node
        component_name = component_name or "-"

        return asset_name, component_name

def open_scene_resource_window():
    """Open the Scene Resource Window.

    Usage from Maya shelf button:
        from mroya.maya import open_scene_resource_window
        open_scene_resource_window()

    Returns:
        The window instance, or None if failed.
    """
    global _window_instance

    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        print("[Scene Resource Window] Maya is not available")
        return None

    if not PYSIDE_AVAILABLE:
        _log.error("PySide6/PySide2 is not available")
        print("[Scene Resource Window] PySide is not available")
        return None

    # If window exists and is visible, just raise it
    if _window_instance is not None:
        try:
            if _window_instance.isVisible():
                _window_instance.raise_()
                _window_instance.activateWindow()
                return _window_instance
        except Exception:
            pass
        _window_instance = None

    # Create new window
    try:
        _window_instance = SceneResourceWindow()
        _window_instance.show()
        _window_instance.raise_()
        _window_instance.activateWindow()

        # Clear reference when window closes
        def _on_close():
            global _window_instance
            _window_instance = None

        _window_instance.finished.connect(_on_close)

        print("[Scene Resource Window] Window opened")
        return _window_instance

    except Exception as exc:
        _log.error("Failed to open Scene Resource Window: %s", exc)
        print(f"[Scene Resource Window] Failed to open: {exc}")
        return None
