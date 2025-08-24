import dataclasses
import json
import itertools
import os
import re
from typing import List, Optional, Dict, Set, Tuple

from PyQt5.QtCore import Qt, QPointF, QTimer, QStandardPaths
from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox,
    QGraphicsScene, QStatusBar,
    QDialog, QFormLayout, QSpinBox, QPlainTextEdit, QLineEdit,
    QPushButton, QHBoxLayout, QDialogButtonBox, QLabel, QWidget, QApplication,
    QRadioButton, QInputDialog
)
from PyQt5.QtWidgets import QUndoStack, QUndoCommand

from graphview import GraphView, GraphNode, GraphEdge, OptionEdge
from model import DlgRow
import io_dlg
import json_conv
import layout


# ---------------- Диалоги ----------------

class SpacingDialog(QDialog):
    def __init__(self, h_gap: int, v_gap: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Format Spacing")
        self.setMinimumWidth(320)

        form = QFormLayout(self)

        self.h_spin = QSpinBox(); self.h_spin.setRange(10, 400); self.h_spin.setValue(h_gap)
        self.v_spin = QSpinBox(); self.v_spin.setRange(40, 400); self.v_spin.setValue(v_gap)

        form.addRow("H Gap (px):", self.h_spin)
        form.addRow("V Gap (px):", self.v_spin)

        preset_box = QHBoxLayout()
        for name, (h, v) in [
            ("Compact", (30, 70)),
            ("Normal", (layout.H_GAP_BASE, layout.V_GAP_BASE)),
            ("Spacious", (100, 160)),
        ]:
            btn = QPushButton(name); btn.clicked.connect(lambda _, H=h, V=v: (self.h_spin.setValue(H), self.v_spin.setValue(V)))
            preset_box.addWidget(btn)
        btn_auto = QPushButton("Auto"); btn_auto.clicked.connect(self._auto)
        preset_box.addWidget(btn_auto)
        form.addRow(preset_box)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        form.addRow(box)

    def _auto(self):
        mw = self.parent() if isinstance(self.parent(), MainWindow) else None
        n = len(mw.dlg_data) if mw else 0
        h, v = layout.auto_gaps(n)
        self.h_spin.setValue(h); self.v_spin.setValue(v)

    @property
    def values(self) -> Tuple[int, int]:
        return self.h_spin.value(), self.v_spin.value()


class EditNodeDialog(QDialog):
    def __init__(self, node_data: DlgRow, existing_indices: List[int], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Node")
        self.setMinimumWidth(500)

        self.original = dataclasses.replace(node_data)
        self.target_ref = node_data
        self.existing_indices = [i for i in existing_indices if i != node_data.index]

        form = QFormLayout(self)

        self.index_spin = QSpinBox(); self.index_spin.setRange(0, 999999); self.index_spin.setValue(node_data.index)
        self.next_edit = QLineEdit(str(node_data.next) if node_data.next is not None else "#")
        self.male_edit = QPlainTextEdit(node_data.male)
        self.female_edit = QPlainTextEdit(node_data.female)
        self.condition_edit = QLineEdit(node_data.condition)
        self.action_edit = QLineEdit(node_data.action)

        form.addRow("Index:", self.index_spin)
        form.addRow("Next Index ('#' for NPC):", self.next_edit)
        form.addRow("Male Text:", self.male_edit)
        form.addRow("Female Text:", self.female_edit)
        form.addRow("Condition:", self.condition_edit)
        form.addRow("Action:", self.action_edit)

        self.variant_edits: Dict[str, QLineEdit] = {}
        for key in self.target_ref.get_variants().keys():
            edit = QLineEdit(getattr(self.target_ref, key))
            self.variant_edits[key] = edit
            form.addRow(f"{key.capitalize()}:", edit)

        token_box = QHBoxLayout()
        for token in ["(Auto-Link)", "(Auto-End)", "(Starting Condition)", "...", ".."]:
            btn = QPushButton(token); btn.clicked.connect(lambda _, t=token: self.insert_token(t)); token_box.addWidget(btn)
        form.addRow(token_box)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._commit); box.rejected.connect(self.reject)
        form.addRow(box)

    def insert_token(self, token: str):
        w = self.focusWidget()
        if isinstance(w, QPlainTextEdit): w.insertPlainText(token)
        elif isinstance(w, QLineEdit): w.insert(token)

    def _commit(self):
        new_index = self.index_spin.value()
        if new_index in self.existing_indices:
            QMessageBox.warning(self, "Validation Error", f"Index {new_index} already exists."); return

        s = self.next_edit.text().strip()
        if s not in ('#', ''):
            try: next_val = int(s)
            except ValueError:
                QMessageBox.warning(self, "Validation Error", "'Next' must be an integer or '#'."); return
        else:
            next_val = None

        new_row = dataclasses.replace(
            self.target_ref,
            index=new_index, next=next_val,
            male=self.male_edit.toPlainText(),
            female=self.female_edit.toPlainText(),
            condition=self.condition_edit.text(),
            action=self.action_edit.text(),
        )
        for k, edit in self.variant_edits.items(): setattr(new_row, k, edit.text())
        for field in vars(new_row).values():
            if isinstance(field, str) and '}' in field:
                QMessageBox.warning(self, "Validation Error", "Character '}' is not allowed in text fields."); return

        mw = self.parent()
        if isinstance(mw, MainWindow): mw.push_edit_command(self.target_ref, self.original, new_row)
        self.accept()


class AddNodeTypeDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Add Node")
        self.rb_npc = QRadioButton("NPC"); self.rb_pc = QRadioButton("PC")
        self.rb_npc.setChecked(True)

        form = QFormLayout(self)
        row = QHBoxLayout()
        row.addWidget(self.rb_npc); row.addWidget(self.rb_pc)
        form.addRow(row)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        form.addRow(box)

    @property
    def is_pc(self) -> bool:
        return self.rb_pc.isChecked()


# -------------- Undo-команды --------------

class RelinkCommand(QUndoCommand):
    def __init__(self, mw: 'MainWindow', pc_index: int, old_next: Optional[int], new_next: Optional[int]):
        super().__init__(f"Relink PC #{pc_index} → {new_next}")
        self.mw = mw; self.pc_index = pc_index
        self.old_next = old_next; self.new_next = new_next
    def redo(self): self.mw._apply_relink(self.pc_index, self.new_next, preserve_view=True)
    def undo(self): self.mw._apply_relink(self.pc_index, self.old_next, preserve_view=True)


class MoveNodeCommand(QUndoCommand):
    def __init__(self, mw: 'MainWindow', index: int, old_pos: QPointF, new_pos: QPointF):
        super().__init__(f"Move node #{index}")
        self.mw = mw; self.index = index
        self.old_pos = QPointF(old_pos); self.new_pos = QPointF(new_pos)
    def redo(self): self.mw._set_node_pos(self.index, self.new_pos)
    def undo(self): self.mw._set_node_pos(self.index, self.old_pos)


class AddNodesCommand(QUndoCommand):
    def __init__(self, mw: 'MainWindow', rows: List[DlgRow], positions: Dict[int, Tuple[float, float]],
                 focus_index: Optional[int] = None):
        super().__init__(f"Add {len(rows)} node(s)")
        self.mw = mw
        self.rows = [dataclasses.replace(r) for r in rows]
        self.positions = {k: (float(v[0]), float(v[1])) for k, v in positions.items()}
        self.focus_index = focus_index
    def redo(self):
        self.mw._add_rows_and_items(self.rows, self.positions, preserve_view=True)
        if self.focus_index is not None:
            self.mw.focus_on_index(self.focus_index)
    def undo(self):
        self.mw._remove_rows_and_items([r.index for r in self.rows], preserve_view=True)


class DeleteNodesCommand(QUndoCommand):
    def __init__(self, mw: 'MainWindow', rows: List[DlgRow], positions: Dict[int, Tuple[float, float]]):
        super().__init__(f"Delete {len(rows)} node(s)")
        self.mw = mw
        self.rows = [dataclasses.replace(r) for r in rows]
        self.positions = {k: (float(v[0]), float(v[1])) for k, v in positions.items()}
    def redo(self): self.mw._remove_rows_and_items([r.index for r in self.rows], preserve_view=True)
    def undo(self): self.mw._add_rows_and_items(self.rows, self.positions, preserve_view=True)


class EditNodeCommand(QUndoCommand):
    def __init__(self, mw: 'MainWindow', target_ref: DlgRow, old_row: DlgRow, new_row: DlgRow):
        super().__init__(f"Edit node #{target_ref.index}")
        self.mw = mw; self.target_index = target_ref.index
        self.old_row = dataclasses.replace(old_row); self.new_row = dataclasses.replace(new_row)
    def redo(self): self.mw._apply_edit(self.target_index, self.new_row, preserve_view=True)
    def undo(self): self.mw._apply_edit(self.target_index, self.old_row, preserve_view=True)


# -------------- Главное окно --------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTMB DLG Editor 2.0")
        self.setGeometry(100, 100, 1200, 800)

        self.dlg_data: List[DlgRow] = []
        self.nodes: Dict[int, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.option_edges: List[OptionEdge] = []
        self.current_encoding: Optional[str] = None
        self.current_filepath: Optional[str] = None

        self.layout_mode: str = 'tree'
        self.tree_orientation: str = 'vertical'
        self.h_gap: int = layout.H_GAP_BASE
        self.v_gap: int = layout.V_GAP_BASE

        self.show_empty_nodes: bool = False
        self.show_option_edges: bool = True

        self.undo_stack = QUndoStack(self)
        self._paste_bump = 0

        # --- Автосохранение/восстановление ---
        self.modified = False
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(60_000)  # каждые 60 сек
        self.autosave_timer.timeout.connect(self._autosave_tick)
        self.autosave_timer.start()
        self.undo_stack.indexChanged.connect(lambda *_: self._mark_modified())

        self._setup_ui()
        self._create_actions()
        self._create_menus()

    # ---------- UI ----------
    def _setup_ui(self):
        self.scene = QGraphicsScene()
        self.view = GraphView(self.scene, self)
        self.setCentralWidget(self.view)

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.zoom_label = QLabel("100%"); self.status_bar.addPermanentWidget(self.zoom_label)
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{int(round(z*100))}%"))

        self.scene.selectionChanged.connect(self.update_edge_highlights)
        self.view.linkCreated.connect(self.on_link_created)

    def _create_actions(self):
        # File
        self.open_dlg_action = QAction("&Open DLG...", self, triggered=self.open_dlg)
        self.open_json_action = QAction("Open &JSON...", self, triggered=self.open_json)
        self.save_dlg_action = QAction("&Save DLG...", self, triggered=self.save_dlg)
        self.export_json_action = QAction("Export &JSON...", self, triggered=self.export_json)
        self.exit_action = QAction("E&xit", self, triggered=self.close)

        # View
        self.zoom_in_action = QAction("Zoom &In", self, triggered=lambda: self.view.zoom(1.15), shortcut="Ctrl+=")
        self.zoom_out_action = QAction("Zoom &Out", self, triggered=lambda: self.view.zoom(1 / 1.15), shortcut="Ctrl+-")
        self.zoom_reset_action = QAction("&Reset Zoom", self, triggered=self.view.reset_zoom, shortcut="Ctrl+0")
        self.fit_graph_action = QAction("&Fit to Graph", self, triggered=self.view.fit_to_graph, shortcut="F")
        self.fit_width_action = QAction("Fit &Width", self, triggered=self.view.fit_width)
        self.fit_height_action = QAction("Fit &Height", self, triggered=self.view.fit_height)

        # Layout
        self.layout_tree_vert_action = QAction("Layout: Tree &Vertical", self, triggered=lambda: self.set_layout('tree', 'vertical'))
        self.layout_tree_horiz_action = QAction("Layout: Tree &Horizontal", self, triggered=lambda: self.set_layout('tree', 'horizontal'))
        self.layout_sugiyama_action = QAction("Layout: &Sugiyama", self, triggered=lambda: self.set_layout('sugiyama', self.tree_orientation))
        self.format_spacing_action = QAction("&Format Spacing…", self, triggered=self.on_format_spacing)
        self.auto_compact_action = QAction("Auto &Compact", self, triggered=self.on_auto_compact, shortcut="Ctrl+Shift+F")
        self.spacing_shrink_action = QAction("Narrower Gaps", self, triggered=lambda: self.bump_spacing(0.85), shortcut="Ctrl+[")
        self.spacing_expand_action = QAction("Wider Gaps", self, triggered=lambda: self.bump_spacing(1.15), shortcut="Ctrl+]")

        # Toggle: show/hide
        self.toggle_empty_action = QAction("Show Empty Nodes", self, checkable=True, checked=self.show_empty_nodes)
        self.toggle_empty_action.triggered.connect(self.on_toggle_empty_nodes)
        self.toggle_option_edges_action = QAction("Show NPC → PC links", self, checkable=True,
                                                  checked=self.show_option_edges, triggered=self.on_toggle_option_edges)

        # Edit/Clipboard
        self.undo_action = self.undo_stack.createUndoAction(self, "&Undo"); self.undo_action.setShortcuts([Qt.CTRL + Qt.Key_Z])
        self.redo_action = self.undo_stack.createRedoAction(self, "&Redo"); self.redo_action.setShortcuts([Qt.CTRL + Qt.Key_Y, Qt.CTRL + Qt.SHIFT + Qt.Key_Z])
        self.copy_action = QAction("&Copy", self, triggered=self.copy_selection, shortcut="Ctrl+C")
        self.paste_action = QAction("&Paste", self, triggered=self.paste_from_clipboard, shortcut="Ctrl+V")
        self.cut_action = QAction("Cu&t", self, triggered=self.cut_selection, shortcut="Ctrl+X")
        self.delete_action = QAction("&Delete", self, triggered=self.delete_selection, shortcut=Qt.Key_Delete)

        # Add Node
        self.add_node_action = QAction("&Add Node…", self, triggered=self.add_node_dialog, shortcut="Ctrl+N")
        self.add_npc_action = QAction("Add &NPC Node", self, triggered=self.add_npc_node, shortcut="Ctrl+Shift+N")
        self.add_pc_action = QAction("Add &PC Node", self, triggered=self.add_pc_node, shortcut="Ctrl+Shift+P")

        # Trace
        self.trace_to_roots_action = QAction("Trace → Roots", self, triggered=self.trace_to_roots, shortcut="T")

        # Find
        self.find_action = QAction("&Find…", self, triggered=self.find_dialog, shortcut="Ctrl+F")

        self.addActions([
            self.zoom_in_action, self.zoom_out_action, self.zoom_reset_action, self.fit_graph_action,
            self.undo_action, self.redo_action, self.copy_action, self.paste_action, self.cut_action,
            self.delete_action, self.add_node_action, self.add_npc_action, self.add_pc_action,
            self.trace_to_roots_action, self.find_action
        ])

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.open_dlg_action); file_menu.addAction(self.open_json_action)
        file_menu.addSeparator(); file_menu.addAction(self.save_dlg_action); file_menu.addAction(self.export_json_action)
        file_menu.addSeparator(); file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("&View")
        for a in [self.zoom_in_action, self.zoom_out_action, self.zoom_reset_action, self.fit_graph_action,
                  self.fit_width_action, self.fit_height_action]:
            view_menu.addAction(a)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_empty_action)
        view_menu.addAction(self.toggle_option_edges_action)

        layout_menu = self.menuBar().addMenu("&Layout")
        for a in [self.layout_tree_vert_action, self.layout_tree_horiz_action, self.layout_sugiyama_action]:
            layout_menu.addAction(a)
        layout_menu.addSeparator()
        for a in [self.format_spacing_action, self.auto_compact_action, self.spacing_shrink_action, self.spacing_expand_action]:
            layout_menu.addAction(a)

        edit_menu = self.menuBar().addMenu("&Edit")
        for a in [self.undo_action, self.redo_action]:
            edit_menu.addAction(a)
        edit_menu.addSeparator()
        for a in [self.copy_action, self.paste_action, self.cut_action, self.delete_action]:
            edit_menu.addAction(a)
        edit_menu.addSeparator()
        for a in [self.add_node_action, self.add_npc_action, self.add_pc_action]:
            edit_menu.addAction(a)

        find_menu = self.menuBar().addMenu("&Find")
        find_menu.addAction(self.find_action)

        trace_menu = self.menuBar().addMenu("T&race")
        trace_menu.addAction(self.trace_to_roots_action)

    # ---------- Вспомогательное ----------
    def _mark_modified(self):
        self.modified = True

    def _autosave_dir(self) -> str:
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        path = os.path.join(base, "vtmb_dlg_editor2")
        os.makedirs(path, exist_ok=True)
        return path

    def _autosave_path(self) -> str:
        return os.path.join(self._autosave_dir(), "autosave.json")

    def _autosave_tick(self):
        if not self.dlg_data or not self.modified:
            return
        # пишем во временный файл и атомарно переименовываем
        tmp = self._autosave_path() + ".tmp"
        try:
            # используем уже готовый экспортёр в JSON
            if json_conv.export_json(tmp, self.dlg_data):
                os.replace(tmp, self._autosave_path())
                self.status_bar.showMessage("Autosaved (recovery file updated)", 2000)
        except Exception:
            # не душним — автосейв не должен падать приложение
            pass

    def _remove_autosave(self):
        try:
            if os.path.exists(self._autosave_path()):
                os.remove(self._autosave_path())
        except Exception:
            pass

    def check_recovery_on_start(self):
        """Зовётся из app.py сразу после создания окна."""
        p = self._autosave_path()
        if not os.path.exists(p):
            return
        try:
            size_ok = os.path.getsize(p) > 0
        except Exception:
            size_ok = False
        if not size_ok:
            return

        ret = QMessageBox.question(
            self, "Recover unsaved work?",
            "A recovery file from a previous session was found.\n\n"
            "Do you want to restore it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if ret == QMessageBox.Yes:
            rows = json_conv.import_json(p)
            if rows:
                self._clear_scene()
                self.dlg_data = rows
                self.current_encoding = "utf-8"
                self.current_filepath = None
                self.populate_scene()
                self.status_bar.showMessage("Recovered from autosave")
            # не удаляем файл — удалим только после явного сохранения
        else:
            # пользователь отказался — уберём файл, чтобы не спрашивать снова
            self._remove_autosave()

    def focus_on_index(self, idx: int):
        node = self.nodes.get(idx)
        if not node:
            return
        for it in self.scene.selectedItems():
            it.setSelected(False)
        node.setSelected(True)
        self.view.centerOn(node)
        self.update_edge_highlights()

    # ---------- Модель/сцена ----------
    def _ensure_parent_links(self):
        current_npc = None
        for r in self.dlg_data:
            if r.is_pc_reply():
                r.parent_npc = current_npc
            else:
                current_npc = r.index
                r.parent_npc = None

    def _visible_rows(self) -> List[DlgRow]:
        if self.show_empty_nodes: return list(self.dlg_data)
        return [r for r in self.dlg_data if not r.is_empty_separator()]

    def _calc_positions(self) -> Dict[int, Tuple[float, float]]:
        rows = self._visible_rows()
        if self.layout_mode == 'tree':
            return layout.calculate_tree_layout(rows, orientation=self.tree_orientation, h_gap=self.h_gap, v_gap=self.v_gap)
        else:
            return layout.calculate_layout(rows, h_gap=self.h_gap, v_gap=self.v_gap)

    def _update_scene_rect(self):
        r = self.view._nodes_bounding_rect()
        if r is not None:
            self.scene.setSceneRect(r)

    def populate_scene(self):
        # Rebuild the scene atomically to avoid transient selectionChanged crashes
        self.scene.blockSignals(True)
        try:
            self.scene.clear();
            self.nodes = {};
            self.edges = [];
            self.option_edges = []
            if not self.dlg_data:
                return

            self._ensure_parent_links()
            rows = self._visible_rows()
            if not rows:
                return

            positions = self._calc_positions()

            # --- Nodes ---
            for row in rows:
                node = GraphNode(row)
                self.nodes[row.index] = node
                self.scene.addItem(node)
                x, y = positions.get(row.index, (0, 0))
                node.setPos(x, y)

            # --- Main edges (PC → NPC) ---
            for row in rows:
                if row.is_pc_reply() and row.next in self.nodes:
                    s = self.nodes[row.index]
                    d = self.nodes[row.next]
                    e = GraphEdge(s, d)
                    s.out_edges.append(e)
                    d.in_edges.append(e)
                    self.edges.append(e)
                    self.scene.addItem(e)

            # --- Option edges (NPC → PC) ---
            if self.show_option_edges:
                for row in rows:
                    if row.is_pc_reply() and row.parent_npc in self.nodes and row.index in self.nodes:
                        s = self.nodes[row.parent_npc]
                        d = self.nodes[row.index]
                        oe = OptionEdge(s, d)
                        s.opt_out_edges.append(oe)
                        d.opt_in_edges.append(oe)
                        self.option_edges.append(oe)
                        self.scene.addItem(oe)

            self._update_scene_rect()
            self.status_bar.showMessage(
                f"Loaded {len(self.dlg_data)} nodes ({len(rows)} visible). "
                f"Encoding: {self.current_encoding or 'n/a'}"
            )
            self.view.fit_to_graph()
            self.undo_stack.setClean()
            self.modified = False
        finally:
            self.scene.blockSignals(False)

        # One-shot recompute after rebuild
        self.update_edge_highlights()

    def relayout(self, *, preserve_view: bool = True):
        rows = self._visible_rows()
        if not rows: return
        center = self.view.current_view_center_scene() if preserve_view else None

        positions = self._calc_positions()
        for idx, node in self.nodes.items():
            if idx in positions:
                x, y = positions[idx]; node.setPos(x, y)
        for e in self.edges: e.update_path()
        for oe in self.option_edges: oe.update_path()

        self._update_scene_rect()
        if preserve_view and center is not None: self.view.restore_view_center(center)
        else: self.view.fit_to_graph()

    # --- локальные операции, без scene.clear() ---

    def _remove_items_only(self, index: int):
        for e in list(self.edges):
            if e.source.data.index == index or e.dest.data.index == index:
                e.source.out_edges[:] = [x for x in e.source.out_edges if x is not e]
                e.dest.in_edges[:] = [x for x in e.dest.in_edges if x is not e]
                if e in self.edges: self.edges.remove(e)
                self.scene.removeItem(e)
        for oe in list(self.option_edges):
            if oe.source.data.index == index or oe.dest.data.index == index:
                oe.source.opt_out_edges[:] = [x for x in oe.source.opt_out_edges if x is not oe]
                oe.dest.opt_in_edges[:] = [x for x in oe.dest.opt_in_edges if x is not oe]
                if oe in self.option_edges: self.option_edges.remove(oe)
                self.scene.removeItem(oe)
        if index in self.nodes:
            self.scene.removeItem(self.nodes[index])
            del self.nodes[index]

    def _add_one_node_item(self, row: DlgRow, pos: Tuple[float, float]):
        if not row or row.index in self.nodes:
            return
        node = GraphNode(row)
        self.nodes[row.index] = node
        self.scene.addItem(node)
        node.setPos(pos[0], pos[1])

        if row.is_pc_reply() and row.next in self.nodes:
            e = GraphEdge(self.nodes[row.index], self.nodes[row.next])
            self.nodes[row.index].out_edges.append(e)
            self.nodes[row.next].in_edges.append(e)   # фикс опечатки
            self.edges.append(e); self.scene.addItem(e)

        if row.is_pc_reply() and self.show_option_edges and row.parent_npc in self.nodes:
            oe = OptionEdge(self.nodes[row.parent_npc], self.nodes[row.index])
            self.nodes[row.parent_npc].opt_out_edges.append(oe)
            self.nodes[row.index].opt_in_edges.append(oe)
            self.option_edges.append(oe); self.scene.addItem(oe)

    def _set_node_pos(self, index: int, pos: QPointF):
        if index in self.nodes: self.nodes[index].setPos(pos)

    def _apply_relink(self, pc_index: int, new_next: Optional[int], preserve_view: bool = True):
        pc_row = next((r for r in self.dlg_data if r.index == pc_index), None)
        if pc_row is None: return
        pc_row.next = new_next
        # Обновляем шапку PC-ноды, чтобы "PC → next" видно сразу
        if pc_index in self.nodes:
            self.nodes[pc_index].update()
        self._mark_modified()

        # Удаляем старое ребро от PC
        old = None
        for e in list(self.edges):
            if e.source.data.index == pc_index:
                old = e;
                break
        if old:
            old.source.out_edges.remove(old);
            old.dest.in_edges.remove(old)
            if old in self.edges: self.edges.remove(old)
            self.scene.removeItem(old)

        # Создаём новое ребро, если обе ноды на сцене
        if pc_index in self.nodes and new_next in self.nodes:
            e = GraphEdge(self.nodes[pc_index], self.nodes[new_next])
            self.nodes[pc_index].out_edges.append(e)
            self.nodes[new_next].in_edges.append(e)
            self.edges.append(e)
            self.scene.addItem(e)
            e.update_path()
            self.scene.update()

        # ВАЖНО: подсветка и стиль рёбер
        self.update_edge_highlights()

        # Обновляем пути всех рёбер/опций
        for oe in self.option_edges: oe.update_path()
        if preserve_view:
            for e in self.edges: e.update_path()

    def _add_rows_and_items(self, rows: List[DlgRow], positions: Dict[int, Tuple[float, float]], preserve_view: bool = True):
        for r in rows:
            if any(x.index == r.index for x in self.dlg_data):
                raise ValueError(f"Duplicate index on add: {r.index}")
            self.dlg_data.append(r)
        self._mark_modified()

        center = self.view.current_view_center_scene() if preserve_view else None
        visible_ids = set(x.index for x in self._visible_rows())

        for r in rows:
            if r.index not in visible_ids: continue
            self._add_one_node_item(r, positions.get(r.index, (0.0, 0.0)))

        self._update_scene_rect()
        if preserve_view and center is not None: self.view.restore_view_center(center)

    def _remove_rows_and_items(self, indices: List[int], preserve_view: bool = True):
        center = self.view.current_view_center_scene() if preserve_view else None
        for idx in indices:
            self._remove_items_only(idx)
        self.dlg_data[:] = [r for r in self.dlg_data if r.index not in indices]
        self._mark_modified()
        self._update_scene_rect()
        if preserve_view and center is not None: self.view.restore_view_center(center)

    def _row_dict(self, r: DlgRow) -> Dict[str, object]:
        return dataclasses.asdict(r)
    def _row_from_dict(self, d: Dict[str, object]) -> DlgRow:
        return DlgRow(**d)

    # ---------- Подсветка / цепочки ----------
    def update_edge_highlights(self):
        selected_nodes = [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]
        selected_edges = [it for it in self.scene.selectedItems() if isinstance(it, GraphEdge)]
        selected_opt_edges = [it for it in self.scene.selectedItems() if isinstance(it, OptionEdge)]

        # сброс стилей
        for n in self.nodes.values():
            n.setOpacity(1.0)
        for e in self.edges:
            e.set_style('normal')
        for oe in self.option_edges:
            oe.set_state('normal')

        if not selected_nodes and not selected_edges and not selected_opt_edges:
            return

        focus_nodes: Set[int] = set()
        focus_edges: Set[GraphEdge] = set()
        focus_opt_edges: Set[OptionEdge] = set()

        if selected_edges:
            # как и раньше: для выбранного основного ребра показываем цепочку
            edge: GraphEdge = selected_edges[0]
            focus_nodes, focus_edges = self._compute_chain(edge)

        elif selected_opt_edges:
            # для выбранного опционного ребра подсвечиваем его и обе конечные ноды
            oe: OptionEdge = selected_opt_edges[0]
            focus_opt_edges.add(oe)
            focus_nodes.update([oe.source.data.index, oe.dest.data.index])

        else:
            # НОВОЕ: для выбранной ноды подсвечиваем ВСЕ инцидентные ей ребра
            for node in selected_nodes:
                focus_nodes.add(node.data.index)

                # все обычные PC→NPC ребра вокруг ноды
                for e in node.in_edges + node.out_edges:
                    focus_edges.add(e)
                    focus_nodes.add(e.source.data.index)
                    focus_nodes.add(e.dest.data.index)

                # все опционные NPC→PC ребра вокруг ноды
                if node.data.is_pc_reply():
                    # выбран PC: подсвечиваем все входящие зелёные (от NPC к этому PC)
                    for oe in node.opt_in_edges:
                        focus_opt_edges.add(oe)
                        focus_nodes.add(oe.source.data.index)
                        focus_nodes.add(oe.dest.data.index)
                else:
                    # выбран NPC: подсвечиваем все исходящие зелёные (от NPC к его вариантам PC)
                    for oe in node.opt_out_edges:
                        focus_opt_edges.add(oe)
                        focus_nodes.add(oe.source.data.index)
                        focus_nodes.add(oe.dest.data.index)

        # применяем стили
        for e in self.edges:
            e.set_style('highlight' if e in focus_edges else 'dim')

        for oe in self.option_edges:
            oe.set_state('highlight' if oe in focus_opt_edges else 'dim')

        for idx, n in self.nodes.items():
            n.setOpacity(1.0 if idx in focus_nodes else 0.2)

    def _compute_chain(self, edge: GraphEdge) -> Tuple[Set[int], Set[GraphEdge]]:
        by_index: Dict[int, DlgRow] = {r.index: r for r in self.dlg_data}
        pc_children_of_npc: Dict[int, List[int]] = {}
        for r in self.dlg_data:
            if r.is_pc_reply() and r.parent_npc is not None:
                pc_children_of_npc.setdefault(r.parent_npc, []).append(r.index)

        def neighbors(idx: int) -> List[int]:
            r = by_index.get(idx)
            if r is None: return []
            if r.is_pc_reply():
                res = []
                if r.parent_npc is not None: res.append(r.parent_npc)
                if r.next is not None: res.append(r.next)
                return res
            else:
                return pc_children_of_npc.get(idx, [])

        start = {edge.source.data.index, edge.dest.data.index}
        seen: Set[int] = set(start); q: List[int] = list(start)
        while q:
            cur = q.pop(0)
            for nb in neighbors(cur):
                if nb not in seen:
                    seen.add(nb); q.append(nb)

        focus_edges: Set[GraphEdge] = set()
        for e in self.edges:
            if e.source.data.index in seen and e.dest.data.index in seen:
                focus_edges.add(e)
        return seen, focus_edges

    # ---------- Трассировка ----------
    def _upstream_paths(self, to_pc_index: int, max_depth: int = 20, max_paths: int = 200):
        self._ensure_parent_links()
        by_index = {r.index: r for r in self.dlg_data}
        pc_to_target = {r.index: r.next for r in self.dlg_data if r.is_pc_reply() and r.next is not None}

        start_npc = by_index[to_pc_index].parent_npc
        if start_npc is None:
            return [[to_pc_index]]

        initial = [start_npc, to_pc_index]
        paths, stack = [], [(initial, start_npc, 0)]
        while stack and len(paths) < max_paths:
            path, npc, depth = stack.pop()
            incoming_pcs = [pc for pc, dest in pc_to_target.items() if dest == npc]
            if not incoming_pcs or depth >= max_depth:
                paths.append(path)
                continue
            for pc in incoming_pcs:
                parent = by_index[pc].parent_npc
                if parent is None:
                    paths.append([pc] + path)
                else:
                    if parent in path:
                        paths.append(path)
                    else:
                        stack.append(([parent, pc] + path, parent, depth + 1))
        return paths

    def trace_to_roots(self):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]
        if not sel:
            QMessageBox.information(self, "Trace", "Select a PC node to trace.")
            return

        node = sel[0].data
        target_pc = node.index if node.is_pc_reply() else None
        if target_pc is None and node.parent_npc is not None:
            kids = [r.index for r in self.dlg_data if r.parent_npc == node.index and r.is_pc_reply()]
            if not kids:
                QMessageBox.information(self, "Trace", "This NPC has no PC replies to trace.")
                return
            target_pc = kids[0]

        if target_pc is None:
            QMessageBox.information(self, "Trace", "Pick a PC node to trace to roots.")
            return

        paths = self._upstream_paths(target_pc)

        focus_nodes = set(itertools.chain.from_iterable(paths))
        focus_edges = {e for e in self.edges
                       if e.source.data.index in focus_nodes and e.dest.data.index in focus_nodes}
        for e in self.edges:
            e.set_style('highlight' if e in focus_edges else 'dim')
        for idx, gn in self.nodes.items():
            gn.setOpacity(1.0 if idx in focus_nodes else 0.2)
        for oe in self.option_edges:
            s = oe.source.data.index; d = oe.dest.data.index
            oe.set_state('highlight' if (s in focus_nodes and d in focus_nodes) else 'dim')

        def label(idx: int) -> str:
            r = next(x for x in self.dlg_data if x.index == idx)
            typ = 'PC → {}'.format(r.next) if r.is_pc_reply() else 'NPC'
            text = (r.male or r.female).strip()
            text = re.sub(r'\s+', ' ', text)
            return f"#{r.index} {typ}: {text[:70] + ('...' if len(text) > 70 else '')}"

        lines = []
        for i, path in enumerate(paths, 1):
            lines.append(f"Path {i}:")
            lines.extend("  " + label(p) for p in path)
        QMessageBox.information(self, "Trace to roots", "\n".join(lines))

    # ---------- Обработчики/команды ----------
    def open_editor_for(self, node_item: GraphNode):
        existing_indices = [row.index for row in self.dlg_data]
        dialog = EditNodeDialog(node_item.data, existing_indices, self)
        dialog.exec_()

    def on_link_created(self, pc_index: int, npc_index: int):
        pc_row = next((r for r in self.dlg_data if r.index == pc_index), None)
        if pc_row is None or pc_row.next == npc_index: return
        self.undo_stack.push(RelinkCommand(self, pc_index, pc_row.next, npc_index))
        self.status_bar.showMessage(f"Relinked PC #{pc_index} → NPC #{npc_index}")

    def set_layout(self, mode: str, orientation: str):
        self.layout_mode = mode
        if orientation in ('vertical', 'horizontal'): self.tree_orientation = orientation
        self.populate_scene()

    def on_format_spacing(self):
        dlg = SpacingDialog(self.h_gap, self.v_gap, self)
        if dlg.exec_() == QDialog.Accepted:
            self.h_gap, self.v_gap = dlg.values; self.relayout(preserve_view=True)

    def on_auto_compact(self):
        self.h_gap, self.v_gap = layout.auto_gaps(len(self.dlg_data)); self.relayout(preserve_view=True)

    def bump_spacing(self, factor: float):
        self.h_gap = max(10, int(self.h_gap * factor))
        self.v_gap = max(40, int(self.v_gap * factor))
        self.relayout(preserve_view=True)

    def on_toggle_empty_nodes(self, checked: bool):
        center = self.view.current_view_center_scene()
        self.show_empty_nodes = checked
        self.populate_scene()
        if center is not None: self.view.restore_view_center(center)

    def on_toggle_option_edges(self, checked: bool):
        center = self.view.current_view_center_scene()
        self.show_option_edges = checked
        self.populate_scene()
        if center is not None: self.view.restore_view_center(center)

    # ---------- Поиск ----------
    def find_dialog(self):
        text, ok = QInputDialog.getText(self, "Find", "ID (число) или текст (часть фразы):")
        if not ok or not text.strip():
            return
        q = text.strip()
        match_row: Optional[DlgRow] = None

        if q.isdigit():
            idx = int(q)
            match_row = next((r for r in self.dlg_data if r.index == idx), None)
        else:
            ql = q.lower()
            for r in self.dlg_data:
                txt = (r.male or r.female or "").lower()
                if ql in txt:
                    match_row = r
                    break

        if not match_row:
            QMessageBox.information(self, "Find", "Nothing found.")
            return

        if match_row.index not in self.nodes:
            if not self.show_empty_nodes:
                self.show_empty_nodes = True
                self.toggle_empty_action.setChecked(True)
                self.populate_scene()
        node = self.nodes.get(match_row.index)
        if node:
            for it in self.scene.selectedItems():
                it.setSelected(False)
            node.setSelected(True)
            self.view.centerOn(node)
            self.update_edge_highlights()

    # ---------- Вставка PC под NPC ----------
    def add_pc_under_npc(self, npc_index: int):
        if not self.dlg_data:
            return

        parent_item = self.nodes.get(npc_index)
        parent_pos = parent_item.pos() if parent_item else QPointF(0, 0)
        new_pos = (parent_pos.x(), parent_pos.y() + max(60, self.v_gap * 0.8))

        pos = next((i for i, r in enumerate(self.dlg_data) if r.index == npc_index), None)
        if pos is None:
            return
        end = len(self.dlg_data)
        for i in range(pos + 1, len(self.dlg_data)):
            if not self.dlg_data[i].is_pc_reply():
                end = i
                break

        for i in range(pos + 1, end):
            if self.dlg_data[i].is_empty_separator():
                row = self.dlg_data[i]
                row.male = "New PC"; row.female = ""
                row.condition = ""; row.action = ""
                row.parent_npc = npc_index
                row.next = npc_index
                self._remove_items_only(row.index)
                self._add_one_node_item(row, new_pos)
                self._update_scene_rect()
                node = self.nodes.get(row.index)
                if node:
                    self.focus_on_index(node.data.index)
                    self.open_editor_for(node)
                return

        used_ids = {r.index for r in self.dlg_data}
        next_npc_id = self.dlg_data[end].index if end < len(self.dlg_data) else max(used_ids) + 100000
        candidate = next((val for val in range(npc_index + 1, next_npc_id) if val not in used_ids), None)

        insert_at = end
        if candidate is not None:
            new_id = candidate
            new_row = DlgRow(
                index=new_id, male="New PC", female="", next=npc_index,
                condition="", action="",
                unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
                parent_npc=npc_index
            )
            self.dlg_data.insert(insert_at, new_row)
            self._add_one_node_item(new_row, new_pos)
            self._update_scene_rect()
            self.focus_on_index(new_id)
            self.open_editor_for(self.nodes[new_id])
            return

        start_shift_id = self.dlg_data[end].index if end < len(self.dlg_data) else max(used_ids) + 1
        self._shift_indices_from(start_shift_id, +1)

        new_id = start_shift_id
        new_row = DlgRow(
            index=new_id, male="New PC", female="", next=npc_index,
            condition="", action="",
            unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
            parent_npc=npc_index
        )
        self.dlg_data.insert(insert_at, new_row)
        self._add_one_node_item(new_row, new_pos)
        self._update_scene_rect()
        self.focus_on_index(new_id)
        self.open_editor_for(self.nodes[new_id])

    def _shift_indices_from(self, start_id: int, delta: int):
        for r in self.dlg_data:
            if r.index >= start_id:
                r.index += delta
            if r.is_pc_reply() and r.next is not None and r.next >= start_id:
                r.next += delta
            if r.parent_npc is not None and r.parent_npc >= start_id:
                r.parent_npc += delta

        new_nodes: Dict[int, GraphNode] = {}
        for idx, node in list(self.nodes.items()):
            new_idx = idx + delta if idx >= start_id else idx
            if new_idx != idx:
                node.data.index = new_idx
                node.update()
            new_nodes[new_idx] = node
        self.nodes = new_nodes

        for e in self.edges: e.update_path()
        for oe in self.option_edges: oe.update_path()

    # ---------- Новое: NPC-ответ для PC рядом с PC + Add NPC here ----------
    def add_npc_answer_for_pc(self, pc_index: int, scene_pos: QPointF):
        pc_row = next((r for r in self.dlg_data if r.index == pc_index), None)
        if pc_row is None:
            return
        new_id = self._new_index()
        new_row = DlgRow(
            index=new_id,
            male="New NPC", female="",
            next=None, condition="", action="",
            unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
            parent_npc=None
        )

        pc_item = self.nodes.get(pc_index)
        if pc_item:
            if self.tree_orientation == 'vertical':
                p = pc_item.pos() + QPointF(0, self.v_gap * 1.2)
            else:
                p = pc_item.pos() + QPointF(self.h_gap * 1.2, 0)
            target_pos = (p.x(), p.y())
        else:
            target_pos = (scene_pos.x(), scene_pos.y())

        self.undo_stack.beginMacro("Add NPC answer")
        self.undo_stack.push(AddNodesCommand(self, [new_row], {new_id: target_pos}, focus_index=new_id))
        self.undo_stack.push(RelinkCommand(self, pc_index, pc_row.next, new_id))
        self.undo_stack.endMacro()

        # Ensure the node object exists and the edge is present (belt-and-suspenders)
        QApplication.processEvents()
        # Unconditionally re-apply relink after node creation to guarantee edge exists
        self._apply_relink(pc_index, new_id, preserve_view=True)
        self.scene.update()
        self.view.viewport().update()
        node = self.nodes.get(new_id)
        if node:
            # Открываем редактор на следующий тик — стрела уже отрисована
            QTimer.singleShot(0, lambda: self.open_editor_for(node))

    def add_npc_at(self, scene_pos: QPointF):
        idx = self._new_index()
        row = DlgRow(
            index=idx, male="New NPC", female="", next=None, condition="", action="",
            unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
            parent_npc=None
        )
        self.undo_stack.push(AddNodesCommand(self, [row], {idx: (scene_pos.x(), scene_pos.y())}, focus_index=idx))

    # ---------- Clipboard ----------
    def copy_selection(self):
        selected_nodes = [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]
        if not selected_nodes: return
        ids = [n.data.index for n in selected_nodes]
        rows = [next(r for r in self.dlg_data if r.index == idx) for idx in ids]
        pos = {idx: (self.nodes[idx].pos().x(), self.nodes[idx].pos().y()) for idx in ids if idx in self.nodes}
        payload = {"format": "vtmb_dlg_clipboard_v1", "nodes": [dataclasses.asdict(r) for r in rows], "positions": pos}
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False))

    def cut_selection(self):
        if not [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]: return
        self.copy_selection(); self.delete_selection()

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or data.get("format") != "vtmb_dlg_clipboard_v1": return
        except Exception:
            return
        nodes_data = data.get("nodes", []); positions = data.get("positions", {})
        existing = set(r.index for r in self.dlg_data)
        next_idx = (max(existing) + 1) if existing else 1

        mapping: Dict[int, int] = {}
        new_rows: List[DlgRow] = []; new_positions: Dict[int, Tuple[float, float]] = {}
        bump = 40 * (self._paste_bump % 5); self._paste_bump += 1

        for raw in nodes_data:
            old = DlgRow(**raw)
            new_index = next_idx
            while new_index in existing or new_index in mapping.values(): new_index += 1
            mapping[old.index] = new_index

        for raw in nodes_data:
            old = DlgRow(**raw)
            new = dataclasses.replace(old); new.index = mapping[old.index]
            if new.next is not None and new.next in mapping: new.next = mapping[new.next]
            if new.parent_npc is not None and new.parent_npc in mapping: new.parent_npc = mapping[new.parent_npc]
            new_rows.append(new)
            p = positions.get(str(old.index)) or positions.get(old.index)
            if p is None:
                cx = self.view.current_view_center_scene(); p = (cx.x(), cx.y())
            new_positions[new.index] = (float(p[0]) + bump, float(p[1]) + bump)

        focus_idx = new_rows[0].index if new_rows else None
        self.undo_stack.push(AddNodesCommand(self, new_rows, new_positions, focus_index=focus_idx))

    def delete_selection(self):
        selected_nodes = [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]
        if not selected_nodes: return
        ids = [n.data.index for n in selected_nodes]
        rows = [next(r for r in self.dlg_data if r.index == idx) for idx in ids]
        pos = {idx: (self.nodes[idx].pos().x(), self.nodes[idx].pos().y()) for idx in ids if idx in self.nodes}
        self.undo_stack.push(DeleteNodesCommand(self, rows, pos))

    def push_move_command(self, node: GraphNode, old_pos: QPointF, new_pos: QPointF):
        self.undo_stack.push(MoveNodeCommand(self, node.data.index, old_pos, new_pos))

    def push_edit_command(self, target_ref: DlgRow, old_row: DlgRow, new_row: DlgRow):
        self.undo_stack.push(EditNodeCommand(self, target_ref, old_row, new_row))

    def _apply_edit(self, target_index: int, src: DlgRow, preserve_view: bool = True):
        dst = next((r for r in self.dlg_data if r.index == target_index), None)
        if dst is None: return
        new_index = src.index
        if new_index != target_index and any(r.index == new_index for r in self.dlg_data):
            QMessageBox.warning(self, "Validation Error", f"Index {new_index} already exists."); return

        center = self.view.current_view_center_scene() if preserve_view else None
        old_index = dst.index
        for field in vars(dst).keys(): setattr(dst, field, getattr(src, field))
        self._mark_modified()

        if old_index != dst.index:
            if old_index in self.nodes:
                node_item = self.nodes.pop(old_index); node_item.data.index = dst.index; self.nodes[dst.index] = node_item
            for r in self.dlg_data:
                if r.is_pc_reply() and r.next == old_index: r.next = dst.index
                if r.parent_npc == old_index: r.parent_npc = dst.index
            for e in self.edges: e.update_path()
            for oe in self.option_edges: oe.update_path()

        self._remove_items_only(dst.index)
        self._add_one_node_item(dst, (self.view.current_view_center_scene().x(), self.view.current_view_center_scene().y()))
        self._update_scene_rect()
        if preserve_view and center is not None: self.view.restore_view_center(center)
        if dst.index in self.nodes:
            # Восстановить PC → этот NPC
            for r in self.dlg_data:
                if r.is_pc_reply() and r.next == dst.index and r.index in self.nodes:
                    e = GraphEdge(self.nodes[r.index], self.nodes[dst.index])
                    self.nodes[r.index].out_edges.append(e)
                    self.nodes[dst.index].in_edges.append(e)
                    self.edges.append(e);
                    self.scene.addItem(e)
                    e.update_path()
            # Восстановить опциональные рёбра NPC → PC
            if self.show_option_edges:
                for r in self.dlg_data:
                    if r.is_pc_reply() and r.parent_npc == dst.index and r.index in self.nodes:
                        oe = OptionEdge(self.nodes[dst.index], self.nodes[r.index])
                        self.nodes[dst.index].opt_out_edges.append(oe)
                        self.nodes[r.index].opt_in_edges.append(oe)
                        self.option_edges.append(oe);
                        self.scene.addItem(oe)

        self.update_edge_highlights()

    # ---------- Создание узлов ----------
    def _new_index(self) -> int:
        taken = {r.index for r in self.dlg_data}
        i = (max(taken) + 1) if taken else 1
        while i in taken: i += 1
        return i

    def add_node_dialog(self):
        dlg = AddNodeTypeDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            if dlg.is_pc: self.add_pc_node()
            else: self.add_npc_node()

    def add_npc_node(self):
        idx = self._new_index()
        row = DlgRow(
            index=idx, male="New NPC", female="", next=None, condition="", action="",
            unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
            parent_npc=None
        )
        center = self.view.current_view_center_scene()
        self.undo_stack.push(AddNodesCommand(self, [row], {idx: (center.x(), center.y())}, focus_index=idx))
        self.status_bar.showMessage(f"NPC node #{idx} added")

    def add_pc_node(self):
        idx = self._new_index()
        selected_npc = None
        for it in self.scene.selectedItems():
            if isinstance(it, GraphNode) and (not it.data.is_pc_reply()):
                selected_npc = it.data.index; break
        if selected_npc is None:
            npc_candidates = [r.index for r in self.dlg_data if not r.is_pc_reply()]
            selected_npc = npc_candidates[0] if npc_candidates else None

        row = DlgRow(
            index=idx, male="New PC", female="", next=selected_npc,
            condition="", action="",
            unknown01="", unknown02="", unknown03="", unknown04="", unknown05="", unknown06="", malkavian="",
            parent_npc=selected_npc
        )
        center = self.view.current_view_center_scene()
        self.undo_stack.push(AddNodesCommand(self, [row], {idx: (center.x(), center.y())}, focus_index=idx))
        self.status_bar.showMessage(f"PC node #{idx} added (next→{selected_npc})")

    # ---------- File I/O ----------
    def _clear_scene(self):
        # Safely clear scene without firing selectionChanged mid-reset
        self.scene.blockSignals(True)
        try:
            self.scene.clear()
            self.dlg_data = []
            self.nodes = {}
            self.edges = []
            self.option_edges = []
            self.current_encoding = None
            self.current_filepath = None
            self.view.reset_zoom()
        finally:
            self.scene.blockSignals(False)
        # Ensure visual state consistent
        self.update_edge_highlights()

    def open_dlg(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open DLG File", "", "DLG Files (*.dlg);;All Files (*)")
        if not filepath: return
        self._clear_scene()
        rows, encoding = io_dlg.read_dlg(filepath)
        if rows is not None and encoding:
            self.dlg_data = rows; self.current_encoding = encoding; self.current_filepath = filepath
            self.on_auto_compact(); self.populate_scene()
            self._remove_autosave()
        else:
            QMessageBox.critical(self, "Error", "Failed to open or parse the DLG file.")

    def open_json(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open JSON File", "", "JSON Files (*.json);;All Files (*)")
        if not filepath: return
        self._clear_scene()
        rows = json_conv.import_json(filepath)
        if rows:
            self.dlg_data = rows; self.current_encoding = 'utf-8'; self.current_filepath = filepath
            self.on_auto_compact(); self.populate_scene()
            self._remove_autosave()
        else:
            QMessageBox.critical(self, "Error", "Failed to open or parse the JSON file.")

    def save_dlg(self):
        if not self.dlg_data or not self.current_encoding:
            QMessageBox.warning(self, "Warning", "No data to save."); return
        filepath, _ = QFileDialog.getSaveFileName(self, "Save DLG File", self.current_filepath or "", "DLG Files (*.dlg);;All Files (*)")
        if not filepath: return

        tmp = filepath + ".tmp"
        ok = io_dlg.write_dlg(tmp, self.dlg_data, self.current_encoding)
        if ok:
            try:
                os.replace(tmp, filepath)  # атомарная замена
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to finalize save: {e}")
                return
            self.current_filepath = filepath
            self.status_bar.showMessage(f"File saved to {filepath}")
            self.undo_stack.setClean()
            self.modified = False
            self._remove_autosave()
        else:
            QMessageBox.critical(self, "Error", "Failed to save DLG file.")

    def export_json(self):
        if not self.dlg_data:
            QMessageBox.warning(self, "Warning", "No data to export."); return
        filepath, _ = QFileDialog.getSaveFileName(self, "Export JSON File", "", "JSON Files (*.json);;All Files (*)")
        if not filepath: return
        tmp = filepath + ".tmp"
        if json_conv.export_json(tmp, self.dlg_data):
            try:
                os.replace(tmp, filepath)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to finalize export: {e}")
                return
            self.status_bar.showMessage(f"File exported to {filepath}")
            # экспорт — это не «сохранение проекта», но сбрасывать modified логично, если это основной формат
        else:
            QMessageBox.critical(self, "Error", "Failed to export JSON file.")

    # ---------- Закрытие ----------
    def closeEvent(self, event):
        # тихий автосейв на выходе; если пользователь не сохранит — можно восстановить
        self._autosave_tick()
        if self.modified:
            ret = QMessageBox.question(
                self, "Unsaved changes",
                "There are unsaved changes. Save before exit?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes
            )
            if ret == QMessageBox.Yes:
                self.save_dlg()
                if self.modified:  # если всё ещё есть изменения — значит, сохранение отменили/не удалось
                    event.ignore()
                    return
            elif ret == QMessageBox.Cancel:
                event.ignore()
                return
        super().closeEvent(event)

    # ---------- Навигация стрелками ----------
    # ---------- Навигация стрелками ----------
    def navigate_selection(self, direction: str):
        """Перейти к соседней ноде по рёбрам от текущей выделенной.
        direction ∈ {'up','down','left','right'}.
        'vertical': up=входящие, down=выходящие; left/right — перемещение среди детей/сиблингов.
        'horizontal': left=входящие, right=выходящие.
        """
        node_items = [it for it in self.scene.selectedItems() if isinstance(it, GraphNode)]
        if not node_items:
            return
        cur: GraphNode = node_items[0]

        # --- Особая логика для вертикальной ориентации: left/right ходим по детям/сиблингам
        if self.tree_orientation == 'vertical' and direction in ('left', 'right'):
            going_right = (direction == 'right')

            # 1) Стоим на NPC: ходим по его дочерним PC (вариантам)
            if not cur.data.is_pc_reply() and cur.opt_out_edges:
                children = [oe.dest for oe in cur.opt_out_edges]
                # уникализируем по индексу
                children = list({n.data.index: n for n in children}.values())
                children.sort(key=lambda it: (it.pos().x(), it.pos().y()))
                target = children[0] if going_right else children[-1]
                for it in self.scene.selectedItems():
                    it.setSelected(False)
                target.setSelected(True)
                self.view.centerOn(target)
                self.update_edge_highlights()
                return

            # 2) Стоим на PC: ходим по сиблингам (другим PC под тем же NPC)
            if cur.data.is_pc_reply():
                parent = cur.opt_in_edges[0].source if cur.opt_in_edges else None
                if parent is not None:
                    siblings = [oe.dest for oe in parent.opt_out_edges]
                    seen = set();
                    sibs = []
                    for n in siblings:
                        if n.data.index not in seen:
                            seen.add(n.data.index);
                            sibs.append(n)
                    sibs.sort(key=lambda it: (it.pos().x(), it.pos().y()))
                    try:
                        i = next(i for i, n in enumerate(sibs) if n.data.index == cur.data.index)
                    except StopIteration:
                        i = 0
                    j = i + (1 if going_right else -1)
                    j = max(0, min(len(sibs) - 1, j))
                    if j != i:
                        for it in self.scene.selectedItems():
                            it.setSelected(False)
                        sibs[j].setSelected(True)
                        self.view.centerOn(sibs[j])
                        self.update_edge_highlights()
                        return
        # --- Обычная логика: движение по входящим/исходящим
        if self.tree_orientation == 'vertical':
            go_incoming = (direction == 'up')
            go_outgoing = (direction == 'down')
        else:
            go_incoming = (direction == 'left')
            go_outgoing = (direction == 'right')

        candidates = []
        if go_incoming:
            candidates.extend([e.source for e in cur.in_edges])  # PC→NPC (входящие)
            candidates.extend([oe.source for oe in cur.opt_in_edges])  # NPC→PC (входящие опции)
        elif go_outgoing:
            candidates.extend([e.dest for e in cur.out_edges])  # PC→NPC (исходящие)
            candidates.extend([oe.dest for oe in cur.opt_out_edges])  # NPC→PC (исходящие опции)
        else:
            return

        # уникализируем по индексу
        seen = set();
        uniq = []
        for n in candidates:
            idx = n.data.index
            if idx not in seen:
                seen.add(idx);
                uniq.append(n)
        if not uniq:
            return

        # стабильный порядок по геометрии
        if self.tree_orientation == 'vertical':
            uniq.sort(key=lambda it: (it.pos().x(), it.pos().y()))
        else:
            uniq.sort(key=lambda it: (it.pos().y(), it.pos().x()))

        nxt = uniq[0]
        for it in self.scene.selectedItems():
            it.setSelected(False)
        nxt.setSelected(True)
        self.view.centerOn(nxt)
        self.update_edge_highlights()
