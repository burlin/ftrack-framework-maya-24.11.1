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

            # Read components dict
            comp_dict = {}
            if cmds.attributeQuery("components", node=node, exists=True):
                raw = cmds.getAttr(f"{node}.components") or ""
                if raw:
                    try:
                        comp_dict = json.loads(raw)
                    except Exception:
                        comp_dict = {c.strip(): False for c in raw.split(",") if c.strip()}

            self._results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(task_display))
            self._results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(asset_name))

            # Build a widget with a checkbox per component
            comp_widget = QtWidgets.QWidget()
            comp_layout = QtWidgets.QVBoxLayout(comp_widget)
            comp_layout.setContentsMargins(4, 2, 4, 2)
            comp_layout.setSpacing(2)
            for comp_name, to_publish in comp_dict.items():
                cb = QtWidgets.QCheckBox(comp_name)
                cb.setChecked(bool(to_publish))
                cb.stateChanged.connect(
                    lambda state, n=node, c=comp_name: self._on_comp_checkbox_changed(n, c, state)
                )
                comp_layout.addWidget(cb)
            self._results_table.setCellWidget(row, 2, comp_widget)

            # Adjust row height to fit checkboxes
            num_comps = max(1, len(comp_dict))
            row_height = max(30, 24 * num_comps + 8) if comp_dict else 30
            self._results_table.setRowHeight(row, row_height)

            setup_btn = QtWidgets.QPushButton("Setup Publisher")
            setup_btn.clicked.connect(
                lambda checked=False, n=node: self._on_setup_publisher(n)
            )
            self._results_table.setCellWidget(row, 3, setup_btn)

        self._status_label.setText(f"Found {len(publish_nodes)} publish node(s)")

    def _on_comp_checkbox_changed(self, node: str, comp_name: str, state: int):
        """Update the ToPublish flag in the components dict on the node."""
        if not MAYA_AVAILABLE:
            return
        if not cmds.attributeQuery("components", node=node, exists=True):
            return
        raw = cmds.getAttr(f"{node}.components") or ""
        try:
            comp_dict = json.loads(raw)
        except Exception:
            return
        comp_dict[comp_name] = bool(state)
        cmds.setAttr(f"{node}.components", json.dumps(comp_dict), type="string")

    def _on_setup_publisher(self, node: str):
        """Open the Publisher Setup window for a given node."""
        window = PublisherSetupWindow(node, parent=self)
        window.show()
        window.raise_()


def _load_asset_definitions() -> tuple[list[dict], list[str]]:
    """Load predefined asset definitions and extensions from asset_definitions.json."""
    json_path = Path(__file__).resolve().parents[3] / "resource" / "asset_definitions.json"
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        return data.get("assets", []), data.get("extensions", [])
    except Exception as exc:
        _log.error("Failed to load asset_definitions.json (%s): %s", json_path, exc)
        return [], []


class PublisherSetupWindow(QtWidgets.QDialog):
    """UI for setting up a publish node — pick a predefined asset or use an existing one."""

    def __init__(self, node: str, parent=None):
        super().__init__(parent)
        self._node = node
        self._existing_names: set[str] = set()
        self._existing_ids: dict[str, str] = {}
        self._existing_types: dict[str, str] = {}
        self._asset_defs, self._extensions = _load_asset_definitions()

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

        # --- Components list ---
        comp_header = QtWidgets.QHBoxLayout()
        comp_header.addWidget(QtWidgets.QLabel("Components:"))
        comp_header.addStretch(1)
        layout.addLayout(comp_header)

        self._comp_list_widget = QtWidgets.QWidget()
        self._comp_list_layout = QtWidgets.QVBoxLayout(self._comp_list_widget)
        self._comp_list_layout.setContentsMargins(0, 0, 0, 0)
        self._comp_list_layout.setSpacing(4)
        layout.addWidget(self._comp_list_widget)

        self._refresh_components_list()

        # --- Add component row ---
        add_comp_layout = QtWidgets.QHBoxLayout()
        self._comp_name_edit = QtWidgets.QLineEdit()
        self._comp_name_edit.setPlaceholderText("component name")
        self._comp_name_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        # Pre-fill default component name based on current asset type
        self._comp_name_edit.setText(self._get_default_component_name())
        add_comp_layout.addWidget(self._comp_name_edit)

        self._ext_combo = QtWidgets.QComboBox()
        for ext in self._extensions:
            self._ext_combo.addItem(f".{ext}")
        add_comp_layout.addWidget(self._ext_combo)

        add_comp_btn = QtWidgets.QPushButton("Add Component")
        add_comp_btn.clicked.connect(self._on_add_component)
        add_comp_layout.addWidget(add_comp_btn)
        layout.addLayout(add_comp_layout)

        # --- Close ---
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    def _read_components_dict(self) -> dict:
        """Read the components attribute from the node as a dict."""
        if not MAYA_AVAILABLE:
            return {}
        if not cmds.attributeQuery("components", node=self._node, exists=True):
            return {}
        raw = cmds.getAttr(f"{self._node}.components") or ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            # Legacy comma-separated format fallback
            return {c.strip(): False for c in raw.split(",") if c.strip()}

    def _save_components_dict(self, comp_dict: dict):
        """Write the components dict to the node attribute as JSON."""
        if not MAYA_AVAILABLE:
            return
        if not cmds.attributeQuery("components", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="components", dataType="string")
        cmds.setAttr(
            f"{self._node}.components", json.dumps(comp_dict), type="string"
        )

    def _refresh_components_list(self):
        """Rebuild the components list from the node's components attribute."""
        # Clear existing rows
        while self._comp_list_layout.count():
            item = self._comp_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not MAYA_AVAILABLE:
            return

        comp_dict = self._read_components_dict()

        if not comp_dict:
            label = QtWidgets.QLabel("No components")
            label.setStyleSheet("color: #888; font-style: italic;")
            self._comp_list_layout.addWidget(label)
            return

        for comp_name in comp_dict:
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(20, 0, 0, 0)
            row_layout.setSpacing(8)

            row_layout.addWidget(QtWidgets.QLabel(comp_name))
            row_layout.addStretch(1)

            sel_btn = QtWidgets.QPushButton("Select Objects")
            sel_btn.clicked.connect(
                lambda checked=False, c=comp_name: self._on_select_objects(c)
            )
            row_layout.addWidget(sel_btn)

            del_btn = QtWidgets.QPushButton("Delete")
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(
                lambda checked=False, c=comp_name: self._on_delete_component(c)
            )
            row_layout.addWidget(del_btn)

            self._comp_list_layout.addWidget(row_widget)

    # ------------------------------------------------------------------
    def _on_delete_component(self, comp_name: str):
        """Remove a component from the node's components attribute."""
        if not MAYA_AVAILABLE:
            return

        comp_dict = self._read_components_dict()
        comp_dict.pop(comp_name, None)
        self._save_components_dict(comp_dict)

        print(f"[Publisher Setup] Deleted component '{comp_name}' from {self._node}")
        self._refresh_components_list()

    # ------------------------------------------------------------------
    def _on_select_objects(self, comp_name: str):
        """Open the Component Objects window for a given component."""
        window = ComponentObjectsWindow(self._node, comp_name, parent=self)
        window.show()
        window.raise_()

    # ------------------------------------------------------------------
    def _get_default_component_name(self) -> str:
        """Return the default component name based on the node's asset type."""
        if not MAYA_AVAILABLE:
            return ""
        asset_type = ""
        if cmds.attributeQuery("asset_type", node=self._node, exists=True):
            asset_type = cmds.getAttr(f"{self._node}.asset_type") or ""
        asset_name = ""
        if cmds.attributeQuery("asset_name", node=self._node, exists=True):
            asset_name = cmds.getAttr(f"{self._node}.asset_name") or ""
        for adef in self._asset_defs:
            if asset_type and adef.get("type", "").lower() == asset_type.lower():
                return adef.get("component_name", "")
            if asset_name and adef.get("name", "").lower() == asset_name.lower():
                return adef.get("component_name", "")
        return ""

    # ------------------------------------------------------------------
    def _on_add_component(self):
        """Add a new component to the node's components attribute."""
        name = self._comp_name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Warning", "Component name cannot be empty.")
            return

        ext = self._ext_combo.currentText()  # e.g. ".fbx"
        comp_full = f"{name}{ext}"

        if not MAYA_AVAILABLE:
            return

        comp_dict = self._read_components_dict()

        # Check for duplicate
        if comp_full in comp_dict:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate", f"Component '{comp_full}' already exists."
            )
            return

        comp_dict[comp_full] = False
        self._save_components_dict(comp_dict)

        print(f"[Publisher Setup] Added component '{comp_full}' to {self._node}")
        self._refresh_components_list()

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
            self._existing_types.clear()

            for name, asset_id in unique_version.items():
                asset_type = unique_types.get(name, "")
                label = f"{name}    type: {asset_type}"
                self._existing_combo.addItem(label)
                self._existing_names.add(name)
                self._existing_ids[name] = asset_id
                self._existing_types[name] = asset_type

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
        asset_type = self._existing_types.get(asset_name, "")

        # Look up components from predefined asset definitions by name/type
        comps = self._get_components_for_asset(asset_name, asset_type)

        self._write_asset_to_node(asset_name, asset_id, components=comps)

        # Store asset_type on the node
        if MAYA_AVAILABLE and asset_type:
            if not cmds.attributeQuery("asset_type", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="asset_type", dataType="string")
            cmds.setAttr(f"{self._node}.asset_type", asset_type, type="string")

        print(f"[Publisher Setup] Using existing asset '{asset_name}' (id: {asset_id}, components: {comps})")

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
    def _get_components_for_asset(self, asset_name: str, asset_type: str) -> list[str]:
        """Look up components from predefined asset definitions by type or name."""
        # Match by type first (case-insensitive)
        for adef in self._asset_defs:
            if adef.get("type", "").lower() == asset_type.lower():
                return adef.get("components", [])
        # Fall back to matching by name (case-insensitive)
        for adef in self._asset_defs:
            if adef.get("name", "").lower() == asset_name.lower():
                return adef.get("components", [])
        return []

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

        # Write components attribute as JSON dict {name: ToPublish}
        if components is not None:
            comp_dict = {c: False for c in components}
            if not cmds.attributeQuery("components", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="components", dataType="string")
            cmds.setAttr(
                f"{self._node}.components", json.dumps(comp_dict), type="string"
            )

        # Rename node to ftrack_publish_{AssetName}
        new_name = f"ftrack_publish_{asset_name}"
        renamed = cmds.rename(self._node, new_name)
        self._node = renamed
        self.setWindowTitle(f"Publisher Setup - {renamed}")

        self._current_label.setText(asset_name)
        self._refresh_components_list()


class ComponentObjectsWindow(QtWidgets.QDialog):
    """Window for selecting Maya scene objects to associate with a component."""

    def __init__(self, node: str, comp_name: str, parent=None):
        super().__init__(parent)
        self._node = node
        self._comp_name = comp_name

        self.setWindowTitle(f"Select Objects - {comp_name}")
        self.setMinimumSize(400, 300)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # --- Header ---
        header = QtWidgets.QLabel(f"Objects for: {comp_name}")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        # --- Object list ---
        self._obj_list = QtWidgets.QListWidget()
        layout.addWidget(self._obj_list)

        # --- Buttons ---
        btn_layout = QtWidgets.QHBoxLayout()

        add_sel_btn = QtWidgets.QPushButton("Add Selected")
        add_sel_btn.clicked.connect(self._on_add_selected)
        btn_layout.addWidget(add_sel_btn)

        remove_btn = QtWidgets.QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._on_remove_selected)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch(1)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Load existing objects
        self._refresh_list()

    # ------------------------------------------------------------------
    def _get_object_lists(self) -> dict:
        """Read the components_object_lists attribute from the node as a dict."""
        if not MAYA_AVAILABLE:
            return {}
        if not cmds.attributeQuery("components_object_lists", node=self._node, exists=True):
            return {}
        raw = cmds.getAttr(f"{self._node}.components_object_lists") or ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    def _save_object_lists(self, data: dict):
        """Write the components_object_lists attribute to the node as JSON."""
        if not MAYA_AVAILABLE:
            return
        if not cmds.attributeQuery("components_object_lists", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="components_object_lists", dataType="string")
        cmds.setAttr(
            f"{self._node}.components_object_lists", json.dumps(data), type="string"
        )

    # ------------------------------------------------------------------
    def _refresh_list(self):
        """Reload the object list from the node attribute."""
        self._obj_list.clear()
        data = self._get_object_lists()
        objects = data.get(self._comp_name, [])
        for obj in objects:
            self._obj_list.addItem(obj)

    # ------------------------------------------------------------------
    def _on_add_selected(self):
        """Add currently selected Maya scene objects to this component's list."""
        if not MAYA_AVAILABLE:
            return
        selection = cmds.ls(selection=True, long=False) or []
        if not selection:
            QtWidgets.QMessageBox.warning(self, "Warning", "Nothing selected in the scene.")
            return

        data = self._get_object_lists()
        existing = data.get(self._comp_name, [])

        added = []
        for obj in selection:
            if obj not in existing:
                existing.append(obj)
                added.append(obj)

        data[self._comp_name] = existing
        self._save_object_lists(data)
        self._refresh_list()

        if added:
            print(f"[Select Objects] Added {added} to '{self._comp_name}'")

    # ------------------------------------------------------------------
    def _on_remove_selected(self):
        """Remove the selected items from the list."""
        selected_items = self._obj_list.selectedItems()
        if not selected_items:
            return

        data = self._get_object_lists()
        existing = data.get(self._comp_name, [])

        for item in selected_items:
            obj_name = item.text()
            if obj_name in existing:
                existing.remove(obj_name)

        data[self._comp_name] = existing
        self._save_object_lists(data)
        self._refresh_list()


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


# ======================================================================
# Publish Window
# ======================================================================

_publish_window_instance = None


class PublishWindow(QtWidgets.QDialog):
    """Window showing assets and components marked for publish."""

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise RuntimeError("PySide6 or PySide2 is required")
        if parent is None:
            parent = _get_maya_main_window()
        super().__init__(parent)

        self.setWindowTitle("Publish")
        self.setMinimumSize(600, 400)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # --- Assets / components tree ---
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Asset / Component", "Objects"])
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self._tree)

        # --- Buttons ---
        btn_layout = QtWidgets.QHBoxLayout()
        self._publish_btn = QtWidgets.QPushButton("Publish")
        self._publish_btn.clicked.connect(self._on_publish)
        btn_layout.addWidget(self._publish_btn)
        btn_layout.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._publish_data: list[dict] = []
        self._scan()

    def _scan(self):
        """Scan scene for publish nodes with components marked for publish."""
        self._tree.clear()
        self._publish_data.clear()

        if not MAYA_AVAILABLE:
            return

        all_network_nodes = cmds.ls(type="network") or []
        for node in all_network_nodes:
            if not cmds.attributeQuery("task_id", node=node, exists=True):
                continue

            # Read asset name
            asset_name = ""
            if cmds.attributeQuery("asset_name", node=node, exists=True):
                asset_name = cmds.getAttr(f"{node}.asset_name") or ""
            asset_name = asset_name or "Unnamed"

            # Read components dict
            comp_dict = {}
            if cmds.attributeQuery("components", node=node, exists=True):
                raw = cmds.getAttr(f"{node}.components") or ""
                if raw:
                    try:
                        comp_dict = json.loads(raw)
                    except Exception:
                        pass

            # Filter to only components marked for publish
            to_publish = {k: v for k, v in comp_dict.items() if v}
            if not to_publish:
                continue

            # Read object lists
            obj_lists = {}
            if cmds.attributeQuery("components_object_lists", node=node, exists=True):
                raw_obj = cmds.getAttr(f"{node}.components_object_lists") or ""
                if raw_obj:
                    try:
                        obj_lists = json.loads(raw_obj)
                    except Exception:
                        pass

            # Build tree
            asset_item = QtWidgets.QTreeWidgetItem([asset_name, ""])
            asset_item.setExpanded(True)

            asset_data = {"node": node, "asset_name": asset_name, "components": []}

            for comp_name in to_publish:
                objects = obj_lists.get(comp_name, [])
                objects_str = ", ".join(objects) if objects else "(no objects)"
                comp_item = QtWidgets.QTreeWidgetItem([comp_name, objects_str])
                asset_item.addChild(comp_item)
                asset_data["components"].append({
                    "component": comp_name,
                    "objects": objects,
                })

            self._tree.addTopLevelItem(asset_item)
            self._publish_data.append(asset_data)

        if not self._publish_data:
            empty_item = QtWidgets.QTreeWidgetItem(
                ["No components marked for publish", ""]
            )
            self._tree.addTopLevelItem(empty_item)
            self._publish_btn.setEnabled(False)

    def _on_publish(self):
        """Save component files to a temp folder next to the scene file."""
        if not MAYA_AVAILABLE:
            return

        # Check if scene is saved
        scene_path = cmds.file(query=True, sceneName=True)
        if not scene_path:
            QtWidgets.QMessageBox.warning(
                self, "Scene Not Saved",
                "Please save the scene before publishing."
            )
            return

        scene_file = Path(scene_path)
        scene_dir = scene_file.parent
        scene_stem = scene_file.stem  # filename without extension

        # Create tmp folder
        tmp_dir = scene_dir / f"tmp_{scene_stem}"
        tmp_dir.mkdir(exist_ok=True)

        print("=" * 60)
        print("PUBLISH")
        print("=" * 60)

        for asset_data in self._publish_data:
            asset_name = asset_data["asset_name"]
            print(f"\nAsset: {asset_name}  (node: {asset_data['node']})")

            for comp_data in asset_data["components"]:
                comp_name = comp_data["component"]
                objects = comp_data["objects"]

                # Write file with component name (e.g. camera.fbx)
                file_path = tmp_dir / comp_name
                with open(file_path, "w") as f:
                    for obj in objects:
                        f.write(f"{obj}\n")

                print(f"  Component: {comp_name} -> {file_path}")
                if objects:
                    for obj in objects:
                        print(f"    - {obj}")
                else:
                    print("    (no objects)")

        print(f"\nFiles saved to: {tmp_dir}")
        print("=" * 60)

        QtWidgets.QMessageBox.information(
            self, "Publish Complete",
            f"Files saved to:\n{tmp_dir}"
        )


def open_publish_window():
    """Open the Publish window.

    Returns:
        The window instance, or None if failed.
    """
    global _publish_window_instance

    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        print("[Publish] Maya is not available")
        return None

    if not PYSIDE_AVAILABLE:
        _log.error("PySide6/PySide2 is not available")
        print("[Publish] PySide is not available")
        return None

    if _publish_window_instance is not None:
        try:
            if _publish_window_instance.isVisible():
                _publish_window_instance.raise_()
                _publish_window_instance.activateWindow()
                return _publish_window_instance
        except Exception:
            pass
        _publish_window_instance = None

    try:
        _publish_window_instance = PublishWindow()
        _publish_window_instance.show()
        _publish_window_instance.raise_()
        _publish_window_instance.activateWindow()

        def _on_close():
            global _publish_window_instance
            _publish_window_instance = None

        _publish_window_instance.finished.connect(_on_close)

        print("[Publish] Window opened")
        return _publish_window_instance

    except Exception as exc:
        _log.error("Failed to open Publish window: %s", exc)
        print(f"[Publish] Failed to open: {exc}")
        return None
