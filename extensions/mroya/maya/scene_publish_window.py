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
        self._create_node_btn = QtWidgets.QPushButton("Create Publisher Node")
        self._create_node_btn.clicked.connect(self._on_create_node_clicked)
        toolbar_layout.addWidget(self._create_node_btn)
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
        self._results_table.setColumnWidth(3, 190)

        layout.addWidget(self._results_table)

        self._status_label = QtWidgets.QLabel("Click 'Scan' to find ftrack publish nodes")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_label)

        button_layout = QtWidgets.QHBoxLayout()
        self._publish_action_btn = QtWidgets.QPushButton("Publish")
        self._publish_action_btn.clicked.connect(self._on_publish_clicked)
        button_layout.addWidget(self._publish_action_btn)
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

            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            setup_btn = QtWidgets.QPushButton("Setup Publisher")
            setup_btn.clicked.connect(
                lambda checked=False, n=node: self._on_setup_publisher(n)
            )
            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.clicked.connect(
                lambda checked=False, n=node: self._on_delete_node(n)
            )
            actions_layout.addWidget(setup_btn)
            actions_layout.addWidget(delete_btn)
            self._results_table.setCellWidget(row, 3, actions_widget)

        self._status_label.setText(f"Found {len(publish_nodes)} publish node(s)")

    def _on_create_node_clicked(self):
        """Create a new ftrack publish node and refresh the scan."""
        try:
            try:
                from .publish_node import create_publish_node
            except ImportError:
                from publish_node import create_publish_node
            node = create_publish_node()
            print(f"[Scene Publish Inspector] Created publish node: {node}")
            self._on_scan_clicked()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Error", f"Failed to create publisher node:\n{exc}"
            )

    def _on_publish_clicked(self):
        """Open the Publish window."""
        window = PublishWindow(parent=self)
        window.show()
        window.raise_()

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

    def _on_delete_node(self, node: str):
        """Ask for confirmation then delete the publish node from the Maya scene."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Publisher Node",
            f"Are you sure you want to delete '{node}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            cmds.delete(node)
            print(f"[Scene Publish Inspector] Deleted node: {node}")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to delete '{node}':\n{exc}")
        self._on_scan_clicked()


_FORMAT_DEFAULTS: dict = {
    "fbx": {
        "ascii": True,
        "input_connections": False,
        "blend_shapes": True,
        "bake_animation": True,
        "strip_namespaces": True,
    },
}


def _get_component_defaults(asset_type: str, ext: str) -> dict:
    """Return merged export defaults for asset_type + ext from export_defaults.json.

    Priority: _FORMAT_DEFAULTS base < JSON asset-type entry.
    No imports from exporters — reads the JSON directly.
    """
    ext = ext.lower()
    base = dict(_FORMAT_DEFAULTS.get(ext, {}))
    json_path = Path(__file__).resolve().parents[3] / "resource" / "export_defaults.json"
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        for key, val in data.items():
            if key.startswith("_"):
                continue
            if key.lower() == asset_type.lower():
                base.update(val.get(ext, {}))
                break
    except Exception as exc:
        _log.warning("Could not load export_defaults.json (%s): %s", json_path, exc)
    return base


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

        # --- Asset mode status label ---
        self._asset_mode_label = QtWidgets.QLabel("")
        self._asset_mode_label.setStyleSheet("color: #5aabff; font-size: 11px; padding-left: 4px;")
        layout.addWidget(self._asset_mode_label)

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

        # --- Frame Range ---
        fr_row = QtWidgets.QHBoxLayout()
        fr_row.addWidget(QtWidgets.QLabel("Frame Range:"))
        self._frame_start_spin = QtWidgets.QSpinBox()
        self._frame_start_spin.setRange(-99999, 99999)
        self._frame_start_spin.setFixedWidth(70)
        self._frame_end_spin = QtWidgets.QSpinBox()
        self._frame_end_spin.setRange(-99999, 99999)
        self._frame_end_spin.setFixedWidth(70)
        # Restore from node, or default to scene playback range
        if MAYA_AVAILABLE:
            scene_start = int(cmds.playbackOptions(query=True, minTime=True))
            scene_end = int(cmds.playbackOptions(query=True, maxTime=True))
            fs = scene_start
            fe = scene_end
            if cmds.attributeQuery("frame_start", node=node, exists=True):
                try:
                    fs = int(cmds.getAttr(f"{node}.frame_start"))
                except Exception:
                    pass
            if cmds.attributeQuery("frame_end", node=node, exists=True):
                try:
                    fe = int(cmds.getAttr(f"{node}.frame_end"))
                except Exception:
                    pass
            self._frame_start_spin.setValue(fs)
            self._frame_end_spin.setValue(fe)
        self._frame_start_spin.valueChanged.connect(self._on_frame_range_changed)
        self._frame_end_spin.valueChanged.connect(self._on_frame_range_changed)
        fr_row.addWidget(self._frame_start_spin)
        fr_row.addWidget(QtWidgets.QLabel("—"))
        fr_row.addWidget(self._frame_end_spin)
        from_scene_btn = QtWidgets.QPushButton("From Scene")
        from_scene_btn.clicked.connect(self._on_frame_range_from_scene)
        fr_row.addWidget(from_scene_btn)
        fr_row.addStretch(1)
        layout.addLayout(fr_row)

        # --- Playblast Camera ---
        cam_row = QtWidgets.QHBoxLayout()
        cam_row.addWidget(QtWidgets.QLabel("Playblast Camera:"))
        self._camera_combo = QtWidgets.QComboBox()
        self._camera_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self._camera_combo.addItem("No Playblast")
        self._camera_combo.addItem("Turnaround Camera")
        if MAYA_AVAILABLE:
            for shape in cmds.ls(type="camera") or []:
                transforms = cmds.listRelatives(shape, parent=True, fullPath=False) or []
                if transforms:
                    self._camera_combo.addItem(transforms[0])
        # Restore saved value or auto-select Turnaround for rig/geo assets
        current_cam = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("playblast_camera", node=node, exists=True):
            current_cam = cmds.getAttr(f"{node}.playblast_camera") or ""
        _asset_type_for_cam = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("asset_type", node=node, exists=True):
            _asset_type_for_cam = (cmds.getAttr(f"{node}.asset_type") or "").lower()
        if current_cam:
            # __turnaround__ sentinel maps to the display item "Turnaround Camera"
            lookup = "Turnaround Camera" if current_cam == "__turnaround__" else current_cam
            idx = self._camera_combo.findText(lookup)
            if idx >= 0:
                self._camera_combo.setCurrentIndex(idx)
        elif _asset_type_for_cam in ("rig", "geo", "geometry"):
            self._camera_combo.setCurrentIndex(self._camera_combo.findText("Turnaround Camera"))
            # Signal not connected yet — persist directly so publish picks it up
            if MAYA_AVAILABLE:
                if not cmds.attributeQuery("playblast_camera", node=node, exists=True):
                    cmds.addAttr(node, longName="playblast_camera", dataType="string")
                cmds.setAttr(f"{node}.playblast_camera", "__turnaround__", type="string")
        self._camera_combo.currentTextChanged.connect(self._on_camera_changed)
        cam_row.addWidget(self._camera_combo)
        layout.addLayout(cam_row)

        # --- Bone Camera Export ---
        bone_row = QtWidgets.QHBoxLayout()
        self._bone_camera_cb = QtWidgets.QCheckBox("Export bone camera system")
        self._bone_camera_cb.setToolTip(
            "Creates a root + camera joint hierarchy with a 1×1×1 cm proxy mesh,\n"
            "bakes the camera animation onto the joint, and exports as\n"
            "[camera]_baked_to_bone.fbx alongside the other components."
        )
        bone_export = False
        if MAYA_AVAILABLE and cmds.attributeQuery("bone_camera_export", node=node, exists=True):
            try:
                bone_export = bool(cmds.getAttr(f"{node}.bone_camera_export"))
            except Exception:
                pass
        self._bone_camera_cb.setChecked(bone_export)
        # Only meaningful when a camera is selected
        self._bone_camera_cb.setEnabled(bool(current_cam))
        self._bone_camera_cb.stateChanged.connect(self._on_bone_camera_changed)
        bone_row.addWidget(self._bone_camera_cb)
        bone_row.addStretch(1)
        layout.addLayout(bone_row)

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

            opts_btn = QtWidgets.QPushButton("Options")
            opts_btn.setFixedWidth(60)
            opts_btn.clicked.connect(
                lambda checked=False, c=comp_name: self._on_component_options(c)
            )
            row_layout.addWidget(opts_btn)

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

    def _on_component_options(self, comp_name: str):
        """Open the options window for a component."""
        window = ComponentOptionsWindow(self._node, comp_name, parent=self)
        window.show()
        window.raise_()

    def _on_frame_range_changed(self):
        """Save the current frame range spinbox values to the node."""
        if not MAYA_AVAILABLE:
            return
        for attr, spin in (
            ("frame_start", self._frame_start_spin),
            ("frame_end", self._frame_end_spin),
        ):
            if not cmds.attributeQuery(attr, node=self._node, exists=True):
                cmds.addAttr(self._node, longName=attr, attributeType="long")
            cmds.setAttr(f"{self._node}.{attr}", spin.value())

    def _on_frame_range_from_scene(self):
        """Reset frame range spinboxes to the current scene playback range."""
        if not MAYA_AVAILABLE:
            return
        self._frame_start_spin.setValue(int(cmds.playbackOptions(query=True, minTime=True)))
        self._frame_end_spin.setValue(int(cmds.playbackOptions(query=True, maxTime=True)))

    def _on_camera_changed(self, text: str):
        """Save the selected playblast camera to the node attribute."""
        if not MAYA_AVAILABLE:
            return
        if not cmds.attributeQuery("playblast_camera", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="playblast_camera", dataType="string")
        if text == "No Playblast":
            value = ""
        elif text == "Turnaround Camera":
            value = "__turnaround__"
        else:
            value = text
        cmds.setAttr(f"{self._node}.playblast_camera", value, type="string")
        # Bone camera export only makes sense with a real scene camera
        self._bone_camera_cb.setEnabled(bool(value) and value != "__turnaround__")

    def _on_bone_camera_changed(self, state: int):
        """Save the bone camera export flag to the node attribute."""
        if not MAYA_AVAILABLE:
            return
        if not cmds.attributeQuery("bone_camera_export", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="bone_camera_export", attributeType="bool")
        cmds.setAttr(f"{self._node}.bone_camera_export", bool(state))

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
            adef_type = adef.get("type", "").lower()
            adef_name = adef.get("name", "").lower()
            at = asset_type.lower() if asset_type else ""
            an = asset_name.lower() if asset_name else ""
            if at and (at == adef_type or at == adef_name):
                return adef.get("component_name", "")
            if an and (an == adef_type or an == adef_name):
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

        # Only write default components if the node has none configured yet
        comps = None
        if not self._node_has_components():
            comps = self._get_components_for_asset(asset_name, asset_type)

        self._write_asset_to_node(asset_name, asset_id, components=comps)

        # Store asset_type on the node
        if MAYA_AVAILABLE and asset_type:
            if not cmds.attributeQuery("asset_type", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="asset_type", dataType="string")
            cmds.setAttr(f"{self._node}.asset_type", asset_type, type="string")
        self._update_camera_combo()

        self._asset_mode_label.setText(f"Using existing asset: {asset_name}")
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

        # Only write default components if the node has none configured yet
        comps = None if self._node_has_components() else adef.get("components", [])
        self._write_asset_to_node(asset_name, "", components=comps)

        # Store asset_type on the node — use the full name (e.g. "Geometry", "Rig")
        # so the publisher can look it up as an ftrack AssetType by name.
        if MAYA_AVAILABLE:
            if not cmds.attributeQuery("asset_type", node=self._node, exists=True):
                cmds.addAttr(self._node, longName="asset_type", dataType="string")
            cmds.setAttr(
                f"{self._node}.asset_type", adef.get("name", ""), type="string"
            )
        self._update_camera_combo()

        self._asset_mode_label.setText(f"Creating new asset: {asset_name}")
        print(
            f"[Publisher Setup] Applied new asset '{asset_name}' "
            f"(type: {adef.get('name', '')}, components: {comps})"
        )

    # ------------------------------------------------------------------
    def _update_camera_combo(self):
        """Auto-select Turnaround Camera when a rig/geo asset type is applied."""
        if not MAYA_AVAILABLE:
            return
        asset_type = ""
        if cmds.attributeQuery("asset_type", node=self._node, exists=True):
            asset_type = (cmds.getAttr(f"{self._node}.asset_type") or "").lower()

        if asset_type in ("rig", "geo", "geometry") and self._camera_combo.currentText() == "No Playblast":
            idx = self._camera_combo.findText("Turnaround Camera")
            if idx >= 0:
                self._camera_combo.setCurrentIndex(idx)
                # setCurrentIndex triggers currentTextChanged which calls _on_camera_changed,
                # saving "__turnaround__" to the node automatically

    # ------------------------------------------------------------------
    def _node_has_components(self) -> bool:
        """Return True if the node already has at least one component configured."""
        if not MAYA_AVAILABLE:
            return False
        if not cmds.attributeQuery("components", node=self._node, exists=True):
            return False
        raw = cmds.getAttr(f"{self._node}.components") or ""
        if not raw:
            return False
        try:
            return bool(json.loads(raw))
        except Exception:
            return bool(raw.strip())

    def _get_components_for_asset(self, asset_name: str, asset_type: str) -> list[str]:
        """Look up components from predefined asset definitions by type or name."""
        at = asset_type.lower() if asset_type else ""
        an = asset_name.lower() if asset_name else ""
        for adef in self._asset_defs:
            adef_type = adef.get("type", "").lower()
            adef_name = adef.get("name", "").lower()
            if at and (at == adef_type or at == adef_name):
                return adef.get("components", [])
            if an and (an == adef_type or an == adef_name):
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
        self._obj_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
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
        selection = cmds.ls(selection=True, long=True) or []
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


class ComponentOptionsWindow(QtWidgets.QDialog):
    """Small options dialog for a single component, keyed on its file extension."""

    def __init__(self, node: str, comp_name: str, parent=None):
        super().__init__(parent)
        self._node = node
        self._comp_name = comp_name
        self._ext = Path(comp_name).suffix.lstrip(".").lower()

        self.setWindowTitle(f"Options — {comp_name}")
        self.setMinimumWidth(280)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        opts = self._read_options()
        self._widgets: dict = {}

        if self._ext == "fbx":
            cb_ascii = QtWidgets.QCheckBox("ASCII export")
            cb_ascii.setChecked(bool(opts.get("ascii")))
            layout.addWidget(cb_ascii)
            self._widgets["ascii"] = cb_ascii

            cb_ic = QtWidgets.QCheckBox("Input connections")
            cb_ic.setChecked(bool(opts.get("input_connections")))
            layout.addWidget(cb_ic)
            self._widgets["input_connections"] = cb_ic

            cb_bs = QtWidgets.QCheckBox("Blend shapes")
            cb_bs.setChecked(bool(opts.get("blend_shapes")))
            layout.addWidget(cb_bs)
            self._widgets["blend_shapes"] = cb_bs

            cb_bake = QtWidgets.QCheckBox("Bake animation")
            cb_bake.setChecked(bool(opts.get("bake_animation")))
            layout.addWidget(cb_bake)
            self._widgets["bake_animation"] = cb_bake

            cb_strip_ns = QtWidgets.QCheckBox("Strip namespaces")
            cb_strip_ns.setChecked(bool(opts.get("strip_namespaces")))
            layout.addWidget(cb_strip_ns)
            self._widgets["strip_namespaces"] = cb_strip_ns
        else:
            layout.addWidget(QtWidgets.QLabel("No options available for this format."))

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _read_all_options(self) -> dict:
        if not MAYA_AVAILABLE:
            return {}
        if not cmds.attributeQuery("component_options", node=self._node, exists=True):
            return {}
        raw = cmds.getAttr(f"{self._node}.component_options") or ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _read_options(self) -> dict:
        """Return merged options: format base < JSON config < stored node options."""
        asset_type = ""
        if MAYA_AVAILABLE and cmds.attributeQuery("asset_type", node=self._node, exists=True):
            asset_type = cmds.getAttr(f"{self._node}.asset_type") or ""
        base = _get_component_defaults(asset_type, self._ext)
        stored = self._read_all_options().get(self._comp_name, {})
        return {**base, **stored}

    def _on_save(self):
        if not MAYA_AVAILABLE:
            self.close()
            return
        all_opts = self._read_all_options()
        comp_opts = {
            key: widget.isChecked()
            for key, widget in self._widgets.items()
            if isinstance(widget, QtWidgets.QCheckBox)
        }
        all_opts[self._comp_name] = comp_opts
        if not cmds.attributeQuery("component_options", node=self._node, exists=True):
            cmds.addAttr(self._node, longName="component_options", dataType="string")
        cmds.setAttr(
            f"{self._node}.component_options", json.dumps(all_opts), type="string"
        )
        self.close()


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

        # --- Snapshot row ---
        snap_layout = QtWidgets.QHBoxLayout()
        snap_layout.addWidget(QtWidgets.QLabel("Snapshot format:"))
        self._snapshot_combo = QtWidgets.QComboBox()
        self._snapshot_combo.addItems([".ma", ".mb"])
        snap_layout.addWidget(self._snapshot_combo)
        snap_layout.addStretch(1)
        layout.addLayout(snap_layout)

        # --- Assets / components tree ---
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Asset / Component", "Objects"])
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self._tree)

        # --- Transfer to additional locations ---
        loc_group = QtWidgets.QGroupBox("Transfer to additional locations")
        loc_group_layout = QtWidgets.QVBoxLayout(loc_group)
        loc_group_layout.setContentsMargins(8, 6, 8, 6)
        loc_group_layout.setSpacing(4)
        self._loc_status_label = QtWidgets.QLabel("Loading locations...")
        self._loc_status_label.setStyleSheet("color: #888; font-size: 11px;")
        loc_group_layout.addWidget(self._loc_status_label)
        self._loc_checkboxes_widget = QtWidgets.QWidget()
        self._loc_checkboxes_layout = QtWidgets.QVBoxLayout(self._loc_checkboxes_widget)
        self._loc_checkboxes_layout.setContentsMargins(0, 0, 0, 0)
        self._loc_checkboxes_layout.setSpacing(3)
        loc_group_layout.addWidget(self._loc_checkboxes_widget)
        layout.addWidget(loc_group)

        # {location_id: QCheckBox}
        self._location_checkboxes: dict = {}

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
        self._load_locations()

    def _load_locations(self):
        """Populate the additional locations checkboxes from the ftrack session.

        Shows only locations relevant to the current user:
        - Locations whose name contains the user surname (e.g. k.nalobin → nalobin)
        - x.local and s3.studio.storage are always included
        """
        session = _get_ftrack_session()
        if session is None:
            self._loc_status_label.setText("No ftrack session — locations unavailable")
            return
        try:
            # Derive surname from api_user: "k.nalobin" → "nalobin"
            api_user = session.api_user or ""
            parts = api_user.split(".")
            surname = parts[-1].lower() if len(parts) >= 2 else api_user.lower()

            _ALWAYS_INCLUDE = {"x.local", "s3.studio.storage"}

            locations = session.query("Location").all()

            def _is_relevant(loc):
                name = loc.get("name", "")
                # Always-include these locations
                if name in _ALWAYS_INCLUDE:
                    return True
                # Match only locations whose name starts with "surname."
                # (e.g. nalobin.home.local, nalobin.local) — NOT k.nalobin.Local
                if surname and name.lower().startswith(surname + "."):
                    return True
                return False

            extra_locs = [l for l in locations if _is_relevant(l)]
            extra_locs.sort(key=lambda l: l.get("name", ""))

            self._loc_status_label.hide()

            if not extra_locs:
                self._loc_status_label.setText("No additional locations available")
                self._loc_status_label.show()
                return

            for loc in extra_locs:
                cb = QtWidgets.QCheckBox(loc["name"])
                cb.setChecked(True)
                self._loc_checkboxes_layout.addWidget(cb)
                self._location_checkboxes[loc["id"]] = cb

        except Exception as exc:
            self._loc_status_label.setText(f"Failed to load locations: {exc}")
            self._loc_status_label.show()

    def _queue_transfers(self, session, component_ids: list, target_location_ids: list) -> None:
        """Create a ftrack Job and fire a mroya.transfer.request event for each target location."""
        if not component_ids or not target_location_ids:
            return

        try:
            from ftrack_api.event.base import Event  # type: ignore
        except ImportError:
            print("[Publish] ftrack_api not available — cannot queue transfers")
            return

        # Determine the actual source location by querying where the components landed.
        # Using ComponentLocation is more reliable than pick_location() because
        # create_component(location='auto') may pick a different location than
        # pick_location() returns (e.g. if the highest-priority location is inaccessible).
        from_location_id = None
        try:
            cl = session.query(
                f"ComponentLocation where component_id is \"{component_ids[0]}\""
            ).first()
            if cl:
                from_location_id = cl["location_id"]
                print(f"[Publish] Source location resolved from ComponentLocation: {from_location_id}")
        except Exception as exc:
            print(f"[Publish] ComponentLocation query failed, falling back to pick_location: {exc}")

        if not from_location_id:
            try:
                default_loc = session.pick_location()
                from_location_id = default_loc["id"] if default_loc else None
            except Exception as exc:
                print(f"[Publish] Could not determine source location: {exc}")
                return

        if not from_location_id:
            print("[Publish] No source location found — skipping transfers")
            return

        try:
            import socket
            current_hostname = socket.gethostname().lower()
            api_user = session.api_user
            user_entity = session.query(f"User where username is \"{api_user}\"").one()
            user_id = user_entity["id"]
        except Exception as exc:
            print(f"[Publish] Could not resolve user: {exc}")
            return

        for loc_id in target_location_ids:
            try:
                loc_entity = session.get("Location", loc_id)
                loc_name = loc_entity["name"] if loc_entity else loc_id

                job = session.create("Job", {
                    "user_id": user_id,
                    "status": "running",
                    "data": json.dumps({
                        "tag": "mroya_transfer",
                        "description": (
                            f"Transfer components to {loc_name} "
                            "(initiated from Scene Publish Inspector)"
                        ),
                        "from_location_id": from_location_id,
                        "to_location_id": loc_id,
                        "to_location_name": loc_name,
                    }),
                })
                session.commit()
                job_id = job["id"]

                payload = {
                    "job_id": job_id,
                    "user_id": user_id,
                    "from_location_id": from_location_id,
                    "to_location_id": loc_id,
                    "selection": [
                        {"entityType": "Component", "entityId": cid}
                        for cid in component_ids
                    ],
                    "ignore_component_not_in_location": False,
                    "ignore_location_errors": False,
                }

                try:
                    session.event_hub.connect()
                except Exception:
                    pass

                event = Event(
                    topic="mroya.transfer.request",
                    data=payload,
                    source={
                        "hostname": current_hostname,
                        "user": {"username": api_user},
                    },
                )
                session.event_hub.publish(event, on_error="ignore")
                print(f"[Publish] Transfer job queued → '{loc_name}' (job {job_id})")

            except Exception as exc:
                print(f"[Publish] Failed to queue transfer to {loc_id}: {exc}")

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

            # Read node attributes
            task_id = cmds.getAttr(f"{node}.task_id") or ""

            asset_name = ""
            if cmds.attributeQuery("asset_name", node=node, exists=True):
                asset_name = cmds.getAttr(f"{node}.asset_name") or ""
            asset_name = asset_name or "Unnamed"

            asset_id = ""
            if cmds.attributeQuery("asset_id", node=node, exists=True):
                asset_id = cmds.getAttr(f"{node}.asset_id") or ""

            asset_type = ""
            if cmds.attributeQuery("asset_type", node=node, exists=True):
                asset_type = cmds.getAttr(f"{node}.asset_type") or ""

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

            playblast_camera = ""
            if cmds.attributeQuery("playblast_camera", node=node, exists=True):
                playblast_camera = cmds.getAttr(f"{node}.playblast_camera") or ""

            scene_start = int(cmds.playbackOptions(query=True, minTime=True))
            scene_end = int(cmds.playbackOptions(query=True, maxTime=True))
            frame_start = scene_start
            frame_end = scene_end
            if cmds.attributeQuery("frame_start", node=node, exists=True):
                try:
                    frame_start = int(cmds.getAttr(f"{node}.frame_start"))
                except Exception:
                    pass
            if cmds.attributeQuery("frame_end", node=node, exists=True):
                try:
                    frame_end = int(cmds.getAttr(f"{node}.frame_end"))
                except Exception:
                    pass

            # Build tree
            asset_item = QtWidgets.QTreeWidgetItem([asset_name, f"{frame_start} – {frame_end}"])
            asset_item.setExpanded(True)

            bone_camera_export = False
            if cmds.attributeQuery("bone_camera_export", node=node, exists=True):
                try:
                    bone_camera_export = bool(cmds.getAttr(f"{node}.bone_camera_export"))
                except Exception:
                    pass

            asset_data = {
                "node": node,
                "task_id": task_id,
                "asset_name": asset_name,
                "asset_id": asset_id,
                "asset_type": asset_type,
                "playblast_camera": playblast_camera,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "bone_camera_export": bone_camera_export,
                "components": [],
            }

            for comp_name in to_publish:
                objects = obj_lists.get(comp_name, [])
                objects_str = ", ".join(objects) if objects else "(no objects)"
                comp_item = QtWidgets.QTreeWidgetItem([comp_name, objects_str])
                asset_item.addChild(comp_item)
                asset_data["components"].append({
                    "component": comp_name,
                    "objects": objects,
                })

            # Show bone camera component in tree when enabled
            if bone_camera_export and playblast_camera:
                cam_short = playblast_camera.rsplit("|", 1)[-1]
                bone_item = QtWidgets.QTreeWidgetItem(
                    [f"{cam_short}_baked_to_bone.fbx", "(bone camera — auto-generated)"]
                )
                asset_item.addChild(bone_item)

            self._tree.addTopLevelItem(asset_item)
            self._publish_data.append(asset_data)

        if not self._publish_data:
            empty_item = QtWidgets.QTreeWidgetItem(
                ["No components marked for publish", ""]
            )
            self._tree.addTopLevelItem(empty_item)
            self._publish_btn.setEnabled(False)

    def _on_publish(self):
        """Save temp component files and publish via ftrack_inout Publisher."""
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
        scene_stem = scene_file.stem

        # Create tmp folder
        tmp_dir = scene_dir / f"tmp_{scene_stem}"
        tmp_dir.mkdir(exist_ok=True)

        try:
            from .metadata import collect_component_metadata
        except ImportError:
            from metadata import collect_component_metadata
        component_metadata = collect_component_metadata()

        try:
            from ftrack_inout.publisher.core import JobBuilder, Publisher, PublishResult
        except ImportError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Import Error",
                f"ftrack_inout.publisher.core is not available:\n{exc}"
            )
            return

        session = _get_ftrack_session()

        # Record publish time once (before the loop) so all tasks in the
        # batch share the same delta.  Publisher auto_timelog is disabled;
        # Maya creates/edits timelogs via the result dialog instead.
        _timelog_total_secs = 0.0
        _timelog_per_task = 0.0
        try:
            from ftrack_inout.common.timelog import record_publish
            task_count = len(self._publish_data) or 1
            _timelog_per_task, _total_str = record_publish(task_count=task_count)
            _timelog_total_secs = _timelog_per_task * task_count
        except Exception as exc:
            _log.warning("Time calculation failed: %s", exc)

        results = []
        for asset_data in self._publish_data:
            asset_name = asset_data["asset_name"]
            task_id = asset_data["task_id"]
            asset_id = asset_data["asset_id"]
            asset_type = asset_data["asset_type"]

            # Create playblast for this asset (camera and frame range stored per node)
            playblast_path = None
            camera = asset_data.get("playblast_camera", "")
            frame_start = asset_data.get("frame_start")
            frame_end = asset_data.get("frame_end")
            if camera == "__turnaround__":
                try:
                    try:
                        from .create_playblast import create_turnaround_playblast
                    except ImportError:
                        from create_playblast import create_turnaround_playblast
                    # Collect all objects across all components for this asset
                    all_objects = [
                        obj
                        for cd in asset_data.get("components", [])
                        for obj in cd.get("objects", [])
                        if obj and cmds.objExists(obj)
                    ]
                    # Fall back to all visible mesh transforms when no objects are assigned
                    if not all_objects:
                        mesh_shapes = cmds.ls(type="mesh", visible=True, long=False) or []
                        seen: set[str] = set()
                        for shape in mesh_shapes:
                            parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
                            if parents and parents[0] not in seen:
                                seen.add(parents[0])
                                all_objects.append(parents[0])
                    playblast_path = create_turnaround_playblast(all_objects)
                    print(f"[Publish] Turnaround playblast created for '{asset_name}': {playblast_path}")
                except Exception as exc:
                    _log.error("Turnaround playblast failed for %s: %s", asset_name, exc)
                    print(f"[Publish] Turnaround playblast FAILED for '{asset_name}': {exc}")
            elif camera:
                try:
                    try:
                        from .create_playblast import create_playblast
                    except ImportError:
                        from create_playblast import create_playblast
                    playblast_path = create_playblast(
                        camera,
                        start_frame=frame_start,
                        end_frame=frame_end,
                    )
                    print(f"[Publish] Playblast created for '{asset_name}': {playblast_path}")
                except Exception as exc:
                    _log.error("Playblast creation failed for %s: %s", asset_name, exc)
                    print(f"[Publish] Playblast FAILED for '{asset_name}': {exc}")

            # Read per-component export options stored on the node
            comp_options: dict = {}
            node = asset_data["node"]
            if cmds.attributeQuery("component_options", node=node, exists=True):
                raw_opts = cmds.getAttr(f"{node}.component_options") or ""
                if raw_opts:
                    try:
                        comp_options = json.loads(raw_opts)
                    except Exception:
                        pass

            # Export component files and build component list
            comp_list = []
            export_failed = False
            temp_cameras = []  # track baked cameras for cleanup

            try:
                from .exporters import export_component
            except ImportError:
                from exporters import export_component

            try:
                from .camera_export import is_camera, prepare_camera, cleanup_temp_camera
            except ImportError:
                from camera_export import is_camera, prepare_camera, cleanup_temp_camera

            for comp_data in asset_data["components"]:
                comp_name = comp_data["component"]
                objects = comp_data["objects"]
                file_path = str(tmp_dir / comp_name)

                # If any object is a camera, bake it first and export the baked copy
                export_objects = list(objects)
                for obj in objects:
                    try:
                        obj_is_cam = is_camera(obj)
                    except Exception:
                        obj_is_cam = False
                    if obj_is_cam:
                        try:
                            baked = prepare_camera(obj, start_frame=frame_start, end_frame=frame_end)
                            temp_cameras.append(baked)
                            # Replace the original camera with the baked one
                            export_objects = [
                                baked if o == obj else o for o in export_objects
                            ]
                            print(f"[Publish] Baked camera '{obj}' → '{baked}'")
                        except Exception as exc:
                            _log.error("Camera bake failed for %s: %s", obj, exc)
                            print(f"[Publish] Camera bake FAILED for '{obj}': {exc}")

                try:
                    # Merge asset frame range into options so FBX bake
                    # animation can use it without storing it on the node.
                    comp_opts = {
                        **comp_options.get(comp_name, {}),
                        "frame_start": frame_start,
                        "frame_end": frame_end,
                    }
                    export_component(
                        export_objects, file_path,
                        options=comp_opts,
                        asset_type=asset_type,
                    )
                except Exception as exc:
                    _log.error("Export failed for %s: %s", comp_name, exc)
                    print(f"[Publish] Export FAILED for '{comp_name}': {exc}")
                    export_failed = True
                    continue

                # Strip extension from name — ftrack adds it from the file
                comp_name_no_ext = Path(comp_name).stem
                comp_list.append({
                    "name": comp_name_no_ext,
                    "file_path": file_path,
                    "component_type": "file",
                    "metadata": component_metadata,
                })

            # Clean up temp baked cameras
            for tc in temp_cameras:
                try:
                    cleanup_temp_camera(tc)
                    print(f"[Publish] Cleaned up temp camera: {tc}")
                except Exception as exc:
                    _log.warning("Failed to delete temp camera %s: %s", tc, exc)

            if export_failed and not comp_list:
                results.append((asset_name, PublishResult(
                    success=False, error_message="All exports failed"
                )))
                continue

            # Bone camera export (optional, enabled per asset in Setup window)
            bone_camera_export = asset_data.get("bone_camera_export", False)
            if camera and bone_camera_export:
                try:
                    try:
                        from .bone_camera import (
                            create_bone_camera_rig, bake_bone_camera_rig,
                            export_bone_camera, cleanup_bone_camera_rig,
                        )
                    except ImportError:
                        from bone_camera import (
                            create_bone_camera_rig, bake_bone_camera_rig,
                            export_bone_camera, cleanup_bone_camera_rig,
                        )
                    cam_short = camera.rsplit("|", 1)[-1]
                    bone_cam_file = str(tmp_dir / f"{cam_short}_baked_to_bone.fbx")
                    root_jnt = None
                    box_mesh = None
                    try:
                        root_jnt, cam_jnt, box_mesh = create_bone_camera_rig(camera)
                        bake_bone_camera_rig(
                            cam_jnt, camera,
                            start_frame=frame_start, end_frame=frame_end,
                        )
                        export_bone_camera(root_jnt, box_mesh, bone_cam_file, ascii=False)
                        comp_list.append({
                            "name": f"{cam_short}_baked_to_bone",
                            "file_path": bone_cam_file,
                            "component_type": "file",
                            "metadata": component_metadata,
                        })
                        print(f"[Publish] Bone camera exported: {bone_cam_file}")
                    except Exception as exc:
                        _log.error("Bone camera export failed: %s", exc)
                        print(f"[Publish] Bone camera FAILED: {exc}")
                    finally:
                        if root_jnt and box_mesh:
                            try:
                                cleanup_bone_camera_rig(root_jnt, box_mesh)
                            except Exception as exc:
                                _log.warning("Bone camera cleanup failed: %s", exc)
                except ImportError as exc:
                    print(f"[Publish] bone_camera module not available: {exc}")

            # Add playblast component
            if playblast_path:
                comp_list.append({
                    "name": "playblast",
                    "file_path": playblast_path,
                    "component_type": "playblast",
                    "metadata": component_metadata,
                })

            # Add mandatory snapshot component
            snap_ext = self._snapshot_combo.currentText()  # ".ma" or ".mb"
            snap_file = str(tmp_dir / f"snapshot{snap_ext}")
            try:
                try:
                    from .exporters import save_snapshot
                except ImportError:
                    from exporters import save_snapshot
                save_snapshot(snap_file)
                comp_list.append({
                    "name": "snapshot",
                    "file_path": snap_file,
                    "component_type": "file",
                    "metadata": component_metadata,
                })
                print(f"[Publish] Snapshot saved: {snap_file}")
            except Exception as exc:
                _log.error("Snapshot save failed: %s", exc)
                print(f"[Publish] Snapshot FAILED: {exc}")

            # Build PublishJob via JobBuilder.from_dict
            job_data = {
                "task_id": task_id,
                "asset_name": asset_name,
                "asset_type": asset_type,
                "components": comp_list,
                "source_dcc": "maya",
                "source_scene": scene_path,
            }
            if asset_id:
                job_data["asset_id"] = asset_id

            job = JobBuilder.from_dict(job_data)

            # Execute publish
            publisher = Publisher(session=session, dry_run=(session is None), auto_timelog=False)
            result = publisher.execute(job)
            results.append((asset_name, result))

        # Queue transfers to additional checked locations
        checked_loc_ids = [
            loc_id for loc_id, cb in self._location_checkboxes.items()
            if cb.isChecked()
        ]
        if checked_loc_ids:
            all_component_ids = []
            for _, result in results:
                if result.success:
                    all_component_ids.extend(result.component_ids)
            if all_component_ids:
                self._queue_transfers(session, all_component_ids, checked_loc_ids)

        # Show results
        success_count = sum(1 for _, r in results if r.success)
        fail_count = len(results) - success_count

        msg_lines = []
        for asset_name, result in results:
            if result.success:
                ver = result.asset_version_number or "?"
                msg_lines.append(f"{asset_name}: v{ver} published OK")
            else:
                msg_lines.append(f"{asset_name}: FAILED - {result.error_message}")

        summary = "\n".join(msg_lines)
        print(f"\n[Publish] {success_count} succeeded, {fail_count} failed")
        print(summary)

        # --- Time logging (Maya handles timelogs via editable dialog) ---
        successful_task_ids = [
            ad["task_id"]
            for ad, (_, r) in zip(self._publish_data, results)
            if r.success and ad.get("task_id")
        ]

        if fail_count > 0:
            # Partial failure — create timelogs for successful tasks, show warning
            time_note = ""
            if _timelog_total_secs > 0 and successful_task_ids:
                try:
                    from ftrack_inout.common.timelog import (
                        create_ftrack_timelog, format_duration,
                    )
                    per_task = _timelog_total_secs / len(successful_task_ids)
                    for tid in successful_task_ids:
                        create_ftrack_timelog(session, tid, per_task,
                                             comment="Auto-logged on publish")
                    time_note = f"\n\nTime logged: {format_duration(_timelog_total_secs)}"
                except Exception as exc:
                    _log.warning("Time logging failed: %s", exc)
            QtWidgets.QMessageBox.warning(
                self, "Publish Results",
                f"{success_count} succeeded, {fail_count} failed:\n\n{summary}{time_note}"
            )
        else:
            # Full success — show dialog with editable time field
            if _timelog_total_secs > 0 and successful_task_ids:
                edited_secs = _show_publish_result_dialog(
                    self, summary, _timelog_total_secs, len(successful_task_ids),
                )
                # Create timelogs with the (possibly edited) duration
                final_secs = edited_secs if (edited_secs and edited_secs > 0) else _timelog_total_secs
                try:
                    from ftrack_inout.common.timelog import (
                        create_ftrack_timelog, format_duration,
                    )
                    per_task = final_secs / len(successful_task_ids)
                    for tid in successful_task_ids:
                        create_ftrack_timelog(session, tid, per_task,
                                             comment="Auto-logged on publish")
                    print(f"[Publish] Time logged: {format_duration(final_secs)}")
                except Exception as exc:
                    _log.warning("Time logging failed: %s", exc)
            else:
                QtWidgets.QMessageBox.information(
                    self, "Publish Complete",
                    f"All {success_count} asset(s) published successfully.\n\n{summary}"
                )


def _show_publish_result_dialog(
    parent, summary: str, total_secs: float, task_count: int,
) -> float | None:
    """Show publish-success dialog with an editable time field.

    Args:
        parent: Parent widget.
        summary: Multi-line publish summary text.
        total_secs: Calculated total seconds to pre-fill.
        task_count: Number of tasks (for the "split across" note).

    Returns:
        The (possibly edited) total seconds, or None if the user cancelled.
    """
    from ftrack_inout.common.timelog import format_duration, parse_duration

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Publish Complete")
    dlg.setMinimumWidth(380)

    layout = QtWidgets.QVBoxLayout(dlg)

    # Summary label
    summary_label = QtWidgets.QLabel(
        f"All assets published successfully.\n\n{summary}"
    )
    summary_label.setWordWrap(True)
    layout.addWidget(summary_label)

    # Separator
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    layout.addWidget(line)

    # Time row
    time_layout = QtWidgets.QHBoxLayout()
    time_label = QtWidgets.QLabel("Time spent:")
    time_edit = QtWidgets.QLineEdit(format_duration(total_secs))
    time_edit.setToolTip(
        "Edit the time to log. Examples: 1h 30m, 45m, 2h"
    )
    time_edit.setMaximumWidth(120)
    time_layout.addWidget(time_label)
    time_layout.addWidget(time_edit)
    time_layout.addStretch()
    layout.addLayout(time_layout)

    if task_count > 1:
        split_label = QtWidgets.QLabel(
            f"(will be split equally across {task_count} tasks)"
        )
        split_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(split_label)

    layout.addSpacing(8)

    # Buttons
    btn_layout = QtWidgets.QHBoxLayout()
    btn_layout.addStretch()
    ok_btn = QtWidgets.QPushButton("OK")
    ok_btn.setDefault(True)
    ok_btn.clicked.connect(dlg.accept)
    btn_layout.addWidget(ok_btn)
    layout.addLayout(btn_layout)

    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        text = time_edit.text().strip()
        edited = parse_duration(text)
        if edited is not None and edited > 0:
            return edited
        # If parsing failed, fall back to original
        return total_secs

    # Dialog closed / cancelled — still log the original time
    return total_secs


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
