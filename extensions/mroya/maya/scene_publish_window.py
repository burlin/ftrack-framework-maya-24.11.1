"""Scene Publish Inspector - UI for viewing ftrack publish nodes.

Usage from Maya:
    from mroya.maya import open_scene_publish_window
    open_scene_publish_window()
"""
from __future__ import annotations

import logging

try:
    from .ftrack_session import get_task_path
except ImportError:
    from ftrack_session import get_task_path

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


class ScenePublishWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise RuntimeError("PySide6 or PySide2 is required")
        if parent is None:
            parent = _get_maya_main_window()
        super().__init__(parent)

        self.setWindowTitle("Scene Publish Inspector")
        self.setMinimumSize(650, 350)
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
        self._results_table.setHorizontalHeaderLabels(["Task", "Asset", "Components", ""])
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._results_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self._results_table.setColumnWidth(3, 120)

        layout.addWidget(self._results_table)

        self._status_label = QtWidgets.QLabel("Click 'Scan' to find ftrack publish nodes")
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
        if not MAYA_AVAILABLE:
            return

        publish_nodes = []
        all_network_nodes = cmds.ls(type="network") or []
        for node in all_network_nodes:
            if cmds.attributeQuery("task_id", node=node, exists=True):
                publish_nodes.append(node)

        self._results_table.setRowCount(len(publish_nodes))

        for row, node in enumerate(publish_nodes):
            task_id = cmds.getAttr(f"{node}.task_id") or ""
            asset_name = ""
            if cmds.attributeQuery("asset_name", node=node, exists=True):
                asset_name = cmds.getAttr(f"{node}.asset_name") or ""
            asset_name = asset_name or "Unnamed"

            task_display = get_task_path(task_id) if task_id else ""

            self._results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(task_display))
            self._results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(asset_name))
            self._results_table.setItem(row, 2, QtWidgets.QTableWidgetItem(""))

            setup_btn = QtWidgets.QPushButton("Setup Publisher")
            setup_btn.clicked.connect(
                lambda checked=False, n=node: self._on_setup_publisher(n)
            )
            self._results_table.setCellWidget(row, 3, setup_btn)

        self._status_label.setText(f"Found {len(publish_nodes)} publish node(s)")

    def _on_setup_publisher(self, node: str):
        """Open the Publisher Setup window for a given node."""
        window = PublisherSetupWindow(node, parent=self)
        window.show()
        window.raise_()


class PublisherSetupWindow(QtWidgets.QDialog):
    """Placeholder UI for setting up a publish node's asset name and components."""

    def __init__(self, node: str, parent=None):
        super().__init__(parent)
        self._node = node

        asset_name = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("asset_name", node=node, exists=True):
            asset_name = cmds.getAttr(f"{node}.asset_name") or ""

        self.setWindowTitle(f"Publisher Setup - {node}")
        self.setMinimumSize(400, 250)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Asset name row
        name_layout = QtWidgets.QHBoxLayout()
        name_layout.addWidget(QtWidgets.QLabel("Asset Name:"))
        self._name_edit = QtWidgets.QLineEdit(asset_name)
        name_layout.addWidget(self._name_edit)
        self._set_name_btn = QtWidgets.QPushButton("Set Asset Name")
        self._set_name_btn.clicked.connect(self._on_set_asset_name)
        name_layout.addWidget(self._set_name_btn)
        layout.addLayout(name_layout)

        # Components placeholder
        layout.addWidget(QtWidgets.QLabel("Components:"))
        self._components_list = QtWidgets.QListWidget()
        layout.addWidget(self._components_list)

        self._add_component_btn = QtWidgets.QPushButton("Add Component")
        self._add_component_btn.clicked.connect(self._on_add_component)
        layout.addWidget(self._add_component_btn)

        # Close
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _on_set_asset_name(self):
        name = self._name_edit.text().strip()
        if not name:
            return
        if MAYA_AVAILABLE and cmds.attributeQuery("asset_name", node=self._node, exists=True):
            cmds.setAttr(f"{self._node}.asset_name", name, type="string")
            print(f"[Publisher Setup] Set asset_name to '{name}' on {self._node}")

    def _on_add_component(self):
        print(f"[Publisher Setup] Add Component clicked for {self._node}")


def open_scene_publish_window():
    """Open the Scene Publish Inspector window.

    Returns:
        The window instance, or None if failed.
    """
    global _window_instance

    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        print("[Scene Publish Inspector] Maya is not available")
        return None

    if not PYSIDE_AVAILABLE:
        _log.error("PySide6/PySide2 is not available")
        print("[Scene Publish Inspector] PySide is not available")
        return None

    if _window_instance is not None:
        try:
            if _window_instance.isVisible():
                _window_instance.raise_()
                _window_instance.activateWindow()
                return _window_instance
        except Exception:
            pass
        _window_instance = None

    try:
        _window_instance = ScenePublishWindow()
        _window_instance.show()
        _window_instance.raise_()
        _window_instance.activateWindow()

        def _on_close():
            global _window_instance
            _window_instance = None

        _window_instance.finished.connect(_on_close)

        print("[Scene Publish Inspector] Window opened")
        return _window_instance

    except Exception as exc:
        _log.error("Failed to open Scene Publish Inspector: %s", exc)
        print(f"[Scene Publish Inspector] Failed to open: {exc}")
        return None
