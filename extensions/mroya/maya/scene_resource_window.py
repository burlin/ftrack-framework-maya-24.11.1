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
    from .reference_file import replace_reference
except ImportError:
    # Fallback for testing if not in a package
    import adding_component
    from reference_file import replace_reference

from ftrack_inout.input.dcc.maya import get_session_for_maya
from ftrack_inout.input.core import (
    load_asset_version_component_data,
    resolve_component_to_select,
    resolve_component_path,
)

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

        self._session = get_session_for_maya()

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

        self._results_table = QtWidgets.QTableWidget()
        self._results_table.setColumnCount(4)
        self._results_table.setHorizontalHeaderLabels(["Asset", "Version", "Component", "Actions"])
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._results_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self._results_table.setColumnWidth(1, 80)
        self._results_table.setColumnWidth(3, 250)

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
            asset_name, component_display = self._get_node_display_data(node)
            path = cmds.getAttr(f"{node}.ftrack_component_path") if cmds.attributeQuery('ftrack_component_path',
                                                                                        node=node, exists=True) else ""

            # Read ftrack IDs needed for the version query
            asset_id = ""
            raw_component_name = ""
            current_version_id = ""
            if cmds.attributeQuery('ftrack_asset_id', node=node, exists=True):
                asset_id = cmds.getAttr(f"{node}.ftrack_asset_id") or ""
            if cmds.attributeQuery('ftrack_component_name', node=node, exists=True):
                raw_component_name = cmds.getAttr(f"{node}.ftrack_component_name") or ""
            if cmds.attributeQuery('ftrack_asset_version_id', node=node, exists=True):
                current_version_id = cmds.getAttr(f"{node}.ftrack_asset_version_id") or ""

            # --- Column 0: Asset ---
            self._results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(asset_name))

            # --- Column 1: Version dropdown ---
            version_combo = QtWidgets.QComboBox()
            cached = None
            if asset_id and self._session:
                cached = load_asset_version_component_data(
                    self._session, asset_id, force_refresh=True
                )
            current_index = 0
            if cached:
                idx = 0
                for v in cached["version_info"]:
                    version_id = v["id"]
                    comp_id = resolve_component_to_select(
                        cached, version_id,
                        component_to_select_name=raw_component_name,
                    ) if raw_component_name else None
                    if not comp_id:
                        continue
                    version_combo.addItem(v["name"], {
                        "version": v["version"],
                        "version_id": version_id,
                        "component_id": comp_id,
                    })
                    if version_id == current_version_id:
                        current_index = idx
                    idx += 1
            if version_combo.count() == 0:
                version_combo.addItem("—")
                version_combo.setEnabled(False)
            else:
                version_combo.setCurrentIndex(current_index)
            self._results_table.setCellWidget(row, 1, version_combo)

            # --- Column 2: Component ---
            self._results_table.setItem(row, 2, QtWidgets.QTableWidgetItem(component_display))

            # Read added_to_scene flag
            added = False
            if cmds.attributeQuery('added_to_scene', node=node, exists=True):
                added = bool(cmds.getAttr(f"{node}.added_to_scene"))

            # --- Column 3: Actions ---
            action_widget = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)

            combo = QtWidgets.QComboBox()
            combo.addItems(["reference", "import"])
            if added and cmds.attributeQuery('ftrack_add_method', node=node, exists=True):
                stored_method = cmds.getAttr(f"{node}.ftrack_add_method") or ""
                idx = combo.findText(stored_method)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            if added:
                combo.setEnabled(False)

            reimport_btn = QtWidgets.QPushButton("Reimport")
            reimport_btn.setFixedWidth(65)
            reimport_btn.setEnabled(added)

            btn = QtWidgets.QPushButton("Add")
            btn.setFixedWidth(50)
            btn.setEnabled(not added)

            reimport_btn.clicked.connect(lambda checked=False, n=node, vc=version_combo, rb=reimport_btn, ab=btn, mc=combo: self._on_reimport_clicked(n, vc, rb, ab, mc))
            btn.clicked.connect(lambda checked=False, n=node, vc=version_combo, c=combo, ab=btn, rb=reimport_btn: self._on_add_clicked(n, vc, c, ab, rb))

            action_layout.addWidget(combo)
            action_layout.addWidget(reimport_btn)
            action_layout.addWidget(btn)
            self._results_table.setCellWidget(row, 3, action_widget)

        self._status_label.setText(f"Found {len(ftrack_nodes)} node(s)")

    def _on_reimport_clicked(
        self,
        node: str,
        version_combo: QtWidgets.QComboBox,
        reimport_btn: QtWidgets.QPushButton,
        add_btn: QtWidgets.QPushButton,
        method_combo: QtWidgets.QComboBox,
    ):
        """Replace the existing reference with the version selected in the dropdown."""
        version_data = version_combo.currentData()
        if not version_data or not version_data.get("component_id"):
            self._status_label.setText("No version selected.")
            return

        component_id = version_data["component_id"]
        version_id = version_data["version_id"]

        new_path = self._resolve_any_disk_path(component_id)
        if not new_path:
            self._status_label.setText("Transfer component first.")
            print("[Reimport] Transfer component first")
            return

        # Read the current path from the reference node
        current_path = ""
        if cmds.attributeQuery("ftrack_component_path", node=node, exists=True):
            current_path = cmds.getAttr(f"{node}.ftrack_component_path") or ""

        if not current_path:
            self._status_label.setText("No current path on reference node.")
            return

        success = replace_reference(current_path, new_path)
        if not success:
            self._status_label.setText("Failed to replace reference.")
            return

        # Update the ftrack reference node attributes
        try:
            cmds.setAttr(f"{node}.ftrack_component_path", new_path, type="string")
            if cmds.attributeQuery("ftrack_component_id", node=node, exists=True):
                cmds.setAttr(f"{node}.ftrack_component_id", component_id, type="string")
            if cmds.attributeQuery("ftrack_asset_version_id", node=node, exists=True):
                cmds.setAttr(f"{node}.ftrack_asset_version_id", version_id, type="string")
        except Exception as exc:
            _log.error("Failed to update reference node '%s': %s", node, exc)

        self._status_label.setText(f"Reimported v{version_data['version']}")

    def _on_add_clicked(
        self,
        node: str,
        version_combo: QtWidgets.QComboBox,
        method_combo: QtWidgets.QComboBox,
        add_btn: QtWidgets.QPushButton,
        reimport_btn: QtWidgets.QPushButton,
    ):
        """Add the component for the selected version and update the reference node."""
        version_data = version_combo.currentData()
        if not version_data or not version_data.get("component_id"):
            self._status_label.setText("No version selected.")
            return

        component_id = version_data["component_id"]
        version_id = version_data["version_id"]

        path = self._resolve_any_disk_path(component_id)

        if not path:
            self._status_label.setText("Transfer component first.")
            return

        method = method_combo.currentText()
        success = adding_component.add_component_to_scene(path, method)

        if not success:
            self._status_label.setText("Failed to add component.")
            return

        # Update the ftrack reference node with the new version data
        try:
            if cmds.attributeQuery("ftrack_component_path", node=node, exists=True):
                cmds.setAttr(f"{node}.ftrack_component_path", path, type="string")
            if cmds.attributeQuery("ftrack_component_id", node=node, exists=True):
                cmds.setAttr(f"{node}.ftrack_component_id", component_id, type="string")
            if cmds.attributeQuery("ftrack_asset_version_id", node=node, exists=True):
                cmds.setAttr(f"{node}.ftrack_asset_version_id", version_id, type="string")
        except Exception as exc:
            _log.error("Failed to update reference node '%s': %s", node, exc)

        # Store the method used and lock the combo
        self._set_node_string_attr(node, 'ftrack_add_method', method)
        method_combo.setEnabled(False)

        # Mark as added and flip button states
        self._set_added_to_scene(node, True)
        add_btn.setEnabled(False)
        reimport_btn.setEnabled(True)

        self._status_label.setText(
            f"Added v{version_data['version']} via {method}"
        )

    def _set_added_to_scene(self, node: str, value: bool):
        """Set the added_to_scene flag on the ftrack node, creating the attr if needed."""
        if not cmds.attributeQuery('added_to_scene', node=node, exists=True):
            cmds.addAttr(node, longName='added_to_scene', attributeType='bool')
        cmds.setAttr(f"{node}.added_to_scene", value)

    def _set_node_string_attr(self, node: str, attr: str, value: str):
        """Set a string attribute on a node, creating it if needed."""
        if not cmds.attributeQuery(attr, node=node, exists=True):
            cmds.addAttr(node, longName=attr, dataType='string')
        cmds.setAttr(f"{node}.{attr}", value, type='string')

    def _resolve_any_disk_path(self, component_id: str) -> str | None:
        """Resolve filesystem path for a component from any available disk location."""
        if not self._session or not component_id:
            return None
        try:
            component = self._session.get("Component", component_id)
            if not component:
                return None
            for comp_loc in component["component_locations"]:
                location = comp_loc["location"]
                try:
                    path = resolve_component_path(self._session, component, location=location)
                    if path:
                        return path
                except (ValueError, Exception):
                    continue
        except Exception as exc:
            _log.error("Failed to resolve path for component %s: %s", component_id, exc)
        return None

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
