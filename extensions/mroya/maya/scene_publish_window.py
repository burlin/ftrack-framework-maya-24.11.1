"""Scene Publish Inspector - UI for viewing ftrack publish nodes.

Usage from Maya:
    from mroya.maya import open_scene_publish_window
    open_scene_publish_window()
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from .ftrack_session import get_task_path, _get_ftrack_session
except ImportError:
    from ftrack_session import get_task_path, _get_ftrack_session

try:
    from ftrack_inout.publisher.core.selector import get_assets_list
    SELECTOR_AVAILABLE = True
except ImportError:
    get_assets_list = None  # type: ignore
    SELECTOR_AVAILABLE = False

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

            components_str = ""
            if cmds.attributeQuery("components", node=node, exists=True):
                components_str = cmds.getAttr(f"{node}.components") or ""

            self._results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(task_display))
            self._results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(asset_name))

            # Build a widget with a checkbox per component
            comp_widget = QtWidgets.QWidget()
            comp_layout = QtWidgets.QVBoxLayout(comp_widget)
            comp_layout.setContentsMargins(4, 2, 4, 2)
            comp_layout.setSpacing(2)
            if components_str:
                for comp_name in components_str.split(", "):
                    cb = QtWidgets.QCheckBox(comp_name.strip())
                    comp_layout.addWidget(cb)
            self._results_table.setCellWidget(row, 2, comp_widget)

            # Adjust row height to fit checkboxes
            row_height = max(30, 24 * max(1, len(components_str.split(", "))) + 8) if components_str else 30
            self._results_table.setRowHeight(row, row_height)

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


def _load_asset_definitions() -> list[dict]:
    """Load predefined asset definitions from asset_definitions.json."""
    json_path = Path(__file__).resolve().parents[3] / "resource" / "asset_definitions.json"
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        return data.get("assets", [])
    except Exception as exc:
        _log.error("Failed to load asset_definitions.json (%s): %s", json_path, exc)
        return []


class PublisherSetupWindow(QtWidgets.QDialog):
    """UI for setting up a publish node — pick a predefined asset or use an existing one."""

    def __init__(self, node: str, parent=None):
        super().__init__(parent)
        self._node = node
        self._existing_names: set[str] = set()
        self._existing_ids: dict[str, str] = {}
        self._asset_defs = _load_asset_definitions()

        # Read task_id from the node
        self._task_id = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("task_id", node=node, exists=True):
            self._task_id = cmds.getAttr(f"{node}.task_id") or ""

        asset_name = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("asset_name", node=node, exists=True):
            asset_name = cmds.getAttr(f"{node}.asset_name") or ""

        self.setWindowTitle(f"Publisher Setup - {node}")
        self.setMinimumSize(500, 220)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # --- Current asset label ---
        cur_layout = QtWidgets.QHBoxLayout()
        cur_layout.addWidget(QtWidgets.QLabel("Current Asset:"))
        self._current_label = QtWidgets.QLabel(asset_name or "Unnamed")
        self._current_label.setStyleSheet("font-weight: bold;")
        cur_layout.addWidget(self._current_label)
        cur_layout.addStretch(1)
        layout.addLayout(cur_layout)

        # --- New Asset (predefined) row ---
        new_layout = QtWidgets.QHBoxLayout()
        new_layout.addWidget(QtWidgets.QLabel("New Asset:"))
        self._new_asset_combo = QtWidgets.QComboBox()
        self._new_asset_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        for adef in self._asset_defs:
            comps = ", ".join(adef.get("components", []))
            self._new_asset_combo.addItem(
                f"{adef['name']}  (type: {adef.get('type', '')}, components: {comps})"
            )
        new_layout.addWidget(self._new_asset_combo)

        self._apply_new_btn = QtWidgets.QPushButton("Create")
        self._apply_new_btn.clicked.connect(self._on_apply_new)
        new_layout.addWidget(self._apply_new_btn)
        layout.addLayout(new_layout)

        # --- Existing Assets row ---
        ex_layout = QtWidgets.QHBoxLayout()
        ex_layout.addWidget(QtWidgets.QLabel("Existing Assets:"))
        self._existing_combo = QtWidgets.QComboBox()
        self._existing_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        ex_layout.addWidget(self._existing_combo)

        self._get_ex_btn = QtWidgets.QPushButton("Get Existing")
        self._get_ex_btn.clicked.connect(self._on_get_ex_clicked)
        ex_layout.addWidget(self._get_ex_btn)

        self._use_ex_btn = QtWidgets.QPushButton("Use Selected")
        self._use_ex_btn.clicked.connect(self._on_use_selected)
        self._use_ex_btn.setEnabled(False)
        ex_layout.addWidget(self._use_ex_btn)
        layout.addLayout(ex_layout)

        # --- Close ---
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    def _on_get_ex_clicked(self):
        """Fetch existing assets for the task (same logic as get_ex)."""
        session = _get_ftrack_session()
        if not session:
            QtWidgets.QMessageBox.warning(self, "Warning", "Ftrack session is not available.")
            return

        if not self._task_id:
            QtWidgets.QMessageBox.warning(self, "Warning", "Task ID is empty on this node.")
            return

        try:
            if SELECTOR_AVAILABLE:
                unique_version, unique_types = get_assets_list(session, self._task_id)
            else:
                task = session.get("Task", self._task_id)
                parent_id = task["parent_id"]
                assets = session.query(
                    f'Asset where parent.id is "{parent_id}"'
                ).all()
                unique_version = {}
                unique_types = {}
                seen: set[str] = set()
                for asset in sorted(assets, key=lambda a: a["name"].lower()):
                    try:
                        name = asset["name"]
                        if name not in seen:
                            unique_version[name] = asset["id"]
                            unique_types[name] = asset["type"]["name"]
                            seen.add(name)
                    except Exception:
                        continue

            self._existing_combo.clear()
            self._existing_names.clear()
            self._existing_ids.clear()

            for name, asset_id in unique_version.items():
                asset_type = unique_types.get(name, "")
                label = f"{name}    type: {asset_type}"
                self._existing_combo.addItem(label)
                self._existing_names.add(name)
                self._existing_ids[name] = asset_id

            self._use_ex_btn.setEnabled(self._existing_combo.count() > 0)
            _log.info("Loaded %d existing assets for task %s", len(unique_version), self._task_id)

        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load assets:\n{exc}")

    # ------------------------------------------------------------------
    def _on_use_selected(self):
        """Write the selected existing asset to the node."""
        idx = self._existing_combo.currentIndex()
        if idx < 0:
            return

        raw_label = self._existing_combo.currentText()
        asset_name = raw_label.split("    type:")[0].strip()
        asset_id = self._existing_ids.get(asset_name, "")

        self._write_asset_to_node(asset_name, asset_id)
        print(f"[Publisher Setup] Using existing asset '{asset_name}' (id: {asset_id})")

    # ------------------------------------------------------------------
    def _on_apply_new(self):
        """Apply the selected predefined asset, checking against existing assets."""
        idx = self._new_asset_combo.currentIndex()
        if idx < 0 or idx >= len(self._asset_defs):
            return

        # Fetch existing assets first if not already fetched
        if not self._existing_names:
            self._on_get_ex_clicked()

        adef = self._asset_defs[idx]
        asset_name = adef["name"]

        # Case-insensitive check against existing assets
        existing_lower = {n.lower() for n in self._existing_names}
        if asset_name.lower() in existing_lower:
            QtWidgets.QMessageBox.warning(
                self,
                "Asset Exists",
                f"Asset '{asset_name}' already exists in ftrack.\n\n"
                f"Use 'Get Existing' → 'Use Selected' to pick it instead.",
            )
            return

        comps = adef.get("components", [])
        self._write_asset_to_node(asset_name, "", components=comps)

        # Store asset_type on the node
        if MAYA_AVAILABLE:
            if not cmds.attributeQuery("asset_type", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="asset_type", dataType="string")
            cmds.setAttr(
                f"{self._node}.asset_type", adef.get("type", ""), type="string"
            )

        print(
            f"[Publisher Setup] Applied new asset '{asset_name}' "
            f"(type: {adef.get('type', '')}, components: {comps})"
        )

    # ------------------------------------------------------------------
    def _write_asset_to_node(
        self, asset_name: str, asset_id: str, components: list[str] | None = None
    ):
        """Write asset_name, asset_id, components to the Maya node and rename it."""
        if not MAYA_AVAILABLE:
            return
        if cmds.attributeQuery("asset_name", node=self._node, exists=True):
            cmds.setAttr(f"{self._node}.asset_name", asset_name, type="string")
        if not cmds.attributeQuery("asset_id", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="asset_id", dataType="string")
        cmds.setAttr(f"{self._node}.asset_id", asset_id, type="string")

        # Write components attribute
        if components is not None:
            comp_str = ", ".join(components)
            if not cmds.attributeQuery("components", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="components", dataType="string")
            cmds.setAttr(f"{self._node}.components", comp_str, type="string")

        # Rename node to ftrack_publish_{AssetName}
        new_name = f"ftrack_publish_{asset_name}"
        renamed = cmds.rename(self._node, new_name)
        self._node = renamed
        self.setWindowTitle(f"Publisher Setup - {renamed}")

        self._current_label.setText(asset_name)


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
