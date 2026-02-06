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
    """Scene Resource Window - temporary UI for scene resource management."""

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise RuntimeError("PySide6 or PySide2 is required")

        if parent is None:
            parent = _get_maya_main_window()

        super().__init__(parent)

        self.setWindowTitle("Scene Resource Window")
        self.setMinimumSize(500, 350)
        self.resize(550, 400)

        self._setup_ui()

        # Make window deletable on close
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

    def _setup_ui(self):
        """Set up the UI layout."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Top toolbar with Scan button
        toolbar_layout = QtWidgets.QHBoxLayout()

        self._scan_btn = QtWidgets.QPushButton("Scan")
        self._scan_btn.setMinimumWidth(80)
        self._scan_btn.setToolTip("Scan scene for ftrack reference nodes")
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        toolbar_layout.addWidget(self._scan_btn)

        toolbar_layout.addStretch(1)
        layout.addLayout(toolbar_layout)

        # Results table
        self._results_table = QtWidgets.QTableWidget()
        self._results_table.setColumnCount(2)
        self._results_table.setHorizontalHeaderLabels(["Asset", "Component"])
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._results_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._results_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._results_table.horizontalHeader().setStretchLastSection(True)
        self._results_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._results_table.verticalHeader().setVisible(False)
        layout.addWidget(self._results_table, 1)

        # Status label
        self._status_label = QtWidgets.QLabel("Click 'Scan' to find ftrack reference nodes")
        self._status_label.setStyleSheet("color: #888; font-size: 11px; padding: 5px;")
        layout.addWidget(self._status_label)

        # Bottom button row
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(10)

        button_layout.addStretch(1)

        # Ok button
        self._ok_btn = QtWidgets.QPushButton("Ok")
        self._ok_btn.setMinimumWidth(80)
        self._ok_btn.clicked.connect(self._on_ok_clicked)
        button_layout.addWidget(self._ok_btn)

        # Close button
        self._close_btn = QtWidgets.QPushButton("Close")
        self._close_btn.setMinimumWidth(80)
        self._close_btn.clicked.connect(self.close)
        button_layout.addWidget(self._close_btn)

        layout.addLayout(button_layout)

    def _on_scan_clicked(self):
        """Handle Scan button click - find ftrack reference nodes in the scene."""
        self._results_table.setRowCount(0)

        if not MAYA_AVAILABLE:
            self._status_label.setText("Maya not available")
            return

        # Find all network nodes that have ftrack attributes
        ftrack_nodes = []

        try:
            # Get all network nodes
            all_network_nodes = cmds.ls(type='network') or []

            for node in all_network_nodes:
                # Check if node has ftrack_asset_version_id attribute (our marker)
                if cmds.attributeQuery('ftrack_asset_version_id', node=node, exists=True):
                    ftrack_nodes.append(node)
        except Exception as exc:
            _log.error("Error scanning for ftrack nodes: %s", exc)
            self._status_label.setText(f"Error: {exc}")
            return

        if not ftrack_nodes:
            print("[Scene Resource Window] No ftrack reference nodes found in the scene")
            self._status_label.setText("No ftrack reference nodes found in the scene")
            return

        # Populate the table
        self._results_table.setRowCount(len(ftrack_nodes))

        for row, node in enumerate(ftrack_nodes):
            asset_name, component_name = self._get_node_display_data(node)

            # Asset column
            asset_item = QtWidgets.QTableWidgetItem(asset_name)
            asset_item.setData(QtCore.Qt.UserRole, node)  # Store node name
            self._results_table.setItem(row, 0, asset_item)

            # Component column
            component_item = QtWidgets.QTableWidgetItem(component_name)
            self._results_table.setItem(row, 1, component_item)

        count = len(ftrack_nodes)
        self._status_label.setText(f"Found {count} ftrack reference node(s)")
        print(f"[Scene Resource Window] Found {count} ftrack reference node(s): {ftrack_nodes}")

    def _get_node_display_data(self, node: str) -> tuple[str, str]:
        """Get display data for a ftrack reference node.

        Args:
            node: The Maya node name.

        Returns:
            Tuple of (asset_name, component_name_with_extension).
        """
        asset_name = ""
        component_name = ""
        component_path = ""

        try:
            if cmds.attributeQuery('ftrack_asset_name', node=node, exists=True):
                asset_name = cmds.getAttr(f'{node}.ftrack_asset_name') or ""
        except Exception:
            pass

        try:
            if cmds.attributeQuery('ftrack_component_name', node=node, exists=True):
                component_name = cmds.getAttr(f'{node}.ftrack_component_name') or ""
        except Exception:
            pass

        try:
            if cmds.attributeQuery('ftrack_component_path', node=node, exists=True):
                component_path = cmds.getAttr(f'{node}.ftrack_component_path') or ""
        except Exception:
            pass

        # Extract file extension from path and append to component name
        if component_path:
            _, ext = os.path.splitext(component_path)
            if ext and component_name:
                component_name = f"{component_name}{ext}"
            elif ext and not component_name:
                component_name = ext

        # Fallbacks
        if not asset_name:
            asset_name = node
        if not component_name:
            component_name = "-"

        return asset_name, component_name

    def _on_ok_clicked(self):
        """Handle Ok button click."""
        print("[Scene Resource Window] Ok button clicked!")
        _log.info("[Scene Resource Window] Ok button clicked!")


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
