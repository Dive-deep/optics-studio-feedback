"""Native workbench chrome around the existing local optics renderer.

Pages are independent of Explorer code tabs. All optical/file actions cross the
controller's allowlisted UI contract; this shell never executes an optical job.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QDockWidget, QFrame, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QToolBar, QVBoxLayout, QWidget,
)

from ..services.source_files import DEFAULT_WORKSPACE_ROOT
from .. import __version__
from ..services.workbench_state import WorkbenchStateError, validate_workbench_state
from .explorer import ExplorerPage
from .parameters import ParameterDialog
from .sensitivity import SensitivityPanel
from .layout import apply_window_layout, capture_window_layout
from .unsaved import UnsavedState


PAGE_LABELS = {
    "explorer": "Explorer", "workspace": "Workspace", "tailoring": "DB tailoring",
    "update": "Update model", "sim": "Add Zemax Sim", "auto": "Auto design",
}
RENDERER_PAGES = {"workspace", "update", "sim", "auto"}
FRONTEND_AUXILIARY_PAGES = {"model", "targets", "conditions", "candidates", "mtf", "spot", "project"}


def _label(text="", *, wrap=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    return label


class WorkbenchWindow(QMainWindow):
    def __init__(self, renderer: QWidget, controller, parent=None, *, confirm_close=None):
        super().__init__(parent)
        self.renderer, self.controller = renderer, controller
        self.current_page = "workspace"
        self._frontend_view = "workspace"
        self._last_state = {}
        self._ready = False
        self._closed = False
        self._saving = False
        self._llm_dirty = False
        self._parameters_pending = False
        self._navigation_revision = 0
        self._pending_navigation = None
        self._state_event_revision = 0
        self._session_generation = 0
        self._save_token = None
        self.chart_manager = None
        self._chart_revision = None
        self._chart_tickets = {kind: 0 for kind in ('mtf', 'spot')}
        self._layout_restore_pending = 0
        self._restored_fingerprint = None
        self._restore_had_errors = False
        self._llm_width = 310
        self._restoring_layout = False
        self._saved_state = UnsavedState()
        self._initializing = False
        self._opening = False
        self._open_command_done = True
        self._finishing_restore = False
        self._close_query = False
        self._close_after_save = False
        self._allow_close = False
        self._confirm_close = confirm_close or self._confirm_unsaved_close
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.close)
        self.parameter_dialog = None
        self._last_split_sizes = [550, 250]
        self.setObjectName("opticsWorkbench")
        self.setWindowTitle(f"Optics Studio {__version__} — Local Workbench")
        self.resize(1280, 780)
        self.setMinimumSize(960, 620)
        self._build_pages()
        self._build_llm_dock()
        self._build_actions()
        self._apply_style()
        self.statusBar().showMessage("Preparing local workspace…")
        self.explorer.statusMessage.connect(self._status)
        self.sensitivity.statusMessage.connect(self._status)
        controller.stateChanged.connect(self._on_state_event)
        controller.sessionRestored.connect(self.restore_state)
        controller.parametersRequested.connect(self.open_parameters)
        controller.llmToggleRequested.connect(self.toggle_llm)
        controller.readyChanged.connect(self._on_ready)
        controller.statusMessage.connect(self._status)
        if hasattr(controller, 'chartRequested'):
            controller.chartRequested.connect(self._chart_requested)
        if hasattr(controller, 'sessionOpened'):
            controller.sessionOpened.connect(self._on_session_opened)
        self._on_state_changed(getattr(controller, "last_state", {}) or {})
        self._on_ready(bool(getattr(controller, "ready", False)))

    def _build_pages(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("workbenchSidebar")
        sidebar.setFixedWidth(54)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(5, 12, 5, 10)
        brand = _label("OS")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setToolTip("Optics Studio")
        brand.setObjectName("workbenchBrand")
        side.addWidget(brand)
        side.addSpacing(14)
        icons = Path(__file__).with_name("icons")
        self.nav_buttons = {}
        for page, title in PAGE_LABELS.items():
            button = QPushButton()
            button.setProperty("navigation", True)
            button.setObjectName(f"navigate-{page}")
            button.setAccessibleName(f"Open {title} page")
            button.setToolTip(title)
            button.setFixedSize(44, 42)
            button.setCheckable(True)
            button.setIcon(QIcon(str(icons / (page + ".svg"))))
            button.setIconSize(QSize(22, 22))
            button.clicked.connect(lambda _, p=page: self.navigate(p))
            side.addWidget(button)
            self.nav_buttons[page] = button
        side.addStretch()
        footnote = _label("Local")
        footnote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footnote.setToolTip("Local workspace · Backend not connected")
        footnote.setObjectName("workbenchFootnote")
        side.addWidget(footnote)
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        self.pages.setObjectName("workbenchPages")
        self.workspace_page = QWidget()
        workspace_layout = QVBoxLayout(self.workspace_page)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setAccessibleName("Optical workspace and sensitivity analysis")
        self.renderer.setMinimumHeight(180)
        self.workspace_splitter.addWidget(self.renderer)
        self.sensitivity = SensitivityPanel()
        self.workspace_splitter.addWidget(self.sensitivity)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.splitterMoved.connect(self._remember_split)
        self.sensitivity.hide()
        workspace_layout.addWidget(self.workspace_splitter)
        self.explorer = ExplorerPage(workspace_root=DEFAULT_WORKSPACE_ROOT)
        self.tailoring_page = self._tailoring_page()
        self.pages.addWidget(self.workspace_page)
        self.pages.addWidget(self.explorer)
        self.pages.addWidget(self.tailoring_page)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        heading = QFrame()
        heading.setObjectName("workbenchPageHeader")
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(15, 7, 15, 7)
        self.page_heading = _label("Workspace")
        self.page_heading.setAccessibleName("Current workbench page")
        self.page_heading.setStyleSheet("font-weight:600;font-size:13px;")
        heading_layout.addWidget(self.page_heading)
        heading_layout.addStretch()
        content_layout.addWidget(heading)
        content_layout.addWidget(self.pages, 1)
        layout.addWidget(content, 1)
        self.setCentralWidget(central)

    def _tailoring_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 24)
        title = _label("DB tailoring")
        title.setStyleSheet("font-size:22px;font-weight:600;")
        layout.addWidget(title)
        layout.addWidget(_label("학습에 사용할 DB 사례를 검토하고 선택하는 작업 화면입니다. 데이터 선택 로직과 분석 연결은 TBU입니다.", wrap=True))
        for heading, detail in (
            ("PCA", "주성분 분석 결과를 연결할 예정입니다. 현재 계산하거나 좌표를 추정하지 않습니다."),
            ("UMAP", "차원 축소 결과와 분석 설정을 연결할 예정입니다."),
            ("User select", "사용자가 DB 사례를 직접 검토하고 선택하는 흐름을 구현할 예정입니다."),
        ):
            box = QGroupBox(heading + " · TBU")
            box_layout = QVBoxLayout(box)
            box_layout.addWidget(_label(detail, wrap=True))
            layout.addWidget(box)
        layout.addStretch()
        scroll.setWidget(body)
        return scroll

    def _build_llm_dock(self):
        self.llm_dock = QDockWidget("LLM extension", self)
        self.llm_dock.setObjectName("llmDock")
        self.llm_dock.setAccessibleName("Independent LLM extension panel")
        self.llm_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.llm_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = _label("Claude · TBU")
        heading.setStyleSheet("font-weight:600;")
        layout.addWidget(heading)
        layout.addWidget(_label("설계 목표나 수행할 작업을 자연어로 작성하세요. 현재는 초안만 저장하며 명령을 실행하지 않습니다.", wrap=True))
        self.llm_editor = QPlainTextEdit()
        self.llm_editor.setObjectName("llmDraft")
        self.llm_editor.setAccessibleName("LLM instruction draft")
        self.llm_editor.setPlaceholderText("예: 목표 MTF를 만족하는 후보를 검토해줘…")
        self.llm_editor.textChanged.connect(self._draft_changed)
        layout.addWidget(self.llm_editor, 1)
        self.llm_send_button = QPushButton("Send · TBU")
        self.llm_send_button.setAccessibleName("Send is unavailable until the LLM backend is connected")
        self.llm_send_button.setEnabled(False)
        layout.addWidget(self.llm_send_button)
        layout.addWidget(_label("연결 정보와 인증은 아직 제공하지 않습니다.", wrap=True))
        self.llm_dock.setWidget(body)
        self.llm_dock.setMinimumWidth(270)
        self.llm_dock.setMaximumWidth(460)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.llm_dock)
        self.resizeDocks([self.llm_dock], [310], Qt.Orientation.Horizontal)
        self.llm_dock.hide()
        self.llm_dock.installEventFilter(self)

    def _action(self, title, handler, shortcut=None):
        action = QAction(title, self)
        action.triggered.connect(handler)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _build_actions(self):
        self.open_action = self._action("Open…", self.open_session, QKeySequence.StandardKey.Open)
        self.save_action = self._action("Save…", self.save_session, QKeySequence.StandardKey.Save)
        self.export_action = self._action("Export…", self.export_session)
        self.model_action = self._action("Model report…", lambda: self._open_renderer_tool("model"))
        self.parameters_action = self._action("Parameters…", self.open_parameters, QKeySequence("Ctrl+Alt+P"))
        self.targets_action = self._action("Target profile…", lambda: self._open_renderer_tool("targets"))
        self.candidates_action = self._action("Best candidates", lambda: self._open_renderer_tool("candidates"))
        self.analysis_action = self._action("Sensitivity", self._toggle_analysis)
        self.analysis_action.setCheckable(True)
        self.analysis_action.toggled.connect(self._update_analysis)
        self.llm_action = self._action("LLM panel", lambda: None)
        self.llm_action.setCheckable(True)
        keys = [QKeySequence("Ctrl+Alt+B")]
        if sys.platform == "darwin":
            keys.append(QKeySequence("Meta+Alt+B"))
        self.llm_action.setShortcuts(list({key.toString(): key for key in keys}.values()))
        self.llm_action.toggled.connect(self.llm_dock.setVisible)
        self.llm_dock.visibilityChanged.connect(self._sync_llm_action)
        self._renderer_actions = [self.open_action, self.save_action, self.export_action, self.model_action,
                                  self.parameters_action, self.targets_action, self.candidates_action, self.llm_action]
        file_menu = self.menuBar().addMenu("File")
        for action in (self.open_action, self.save_action, self.export_action):
            file_menu.addAction(action)
        view_menu = self.menuBar().addMenu("View")
        self.nav_actions = {}
        for page, title in PAGE_LABELS.items():
            action = self._action(title, lambda _, p=page: self.navigate(p))
            view_menu.addAction(action)
            self.nav_actions[page] = action
        view_menu.addSeparator()
        view_menu.addAction(self.analysis_action)
        view_menu.addAction(self.llm_action)
        tools_menu = self.menuBar().addMenu("Tools")
        for action in (self.model_action, self.parameters_action, self.targets_action, self.candidates_action):
            tools_menu.addAction(action)
        toolbar = QToolBar("Workspace controls", self)
        toolbar.setObjectName("workbenchToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        for action in (self.open_action, self.save_action, self.export_action):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.model_action)
        toolbar.addAction(self.parameters_action)
        toolbar.addSeparator()
        toolbar.addAction(self.analysis_action)
        toolbar.addAction(self.llm_action)
        spacer = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.model_label = _label("No model report selected")
        self.model_label.setMaximumWidth(235)
        self.model_label.setAccessibleName("Current model report")
        toolbar.addWidget(self.model_label)
        self._show_page("workspace")

    def _apply_style(self):
        palette = self.palette()
        for role, color in ((QPalette.ColorRole.Window, "#f7f8fa"), (QPalette.ColorRole.Base, "#ffffff"),
                            (QPalette.ColorRole.Text, "#202733"), (QPalette.ColorRole.WindowText, "#202733"),
                            (QPalette.ColorRole.Button, "#f7f8fa"), (QPalette.ColorRole.ButtonText, "#202733"),
                            (QPalette.ColorRole.AlternateBase, "#f7f8fa"), (QPalette.ColorRole.Highlight, "#d8e9fc"),
                            (QPalette.ColorRole.HighlightedText, "#202733"), (QPalette.ColorRole.ToolTipBase, "#ffffff"),
                            (QPalette.ColorRole.ToolTipText, "#202733"), (QPalette.ColorRole.PlaceholderText, "#788595")):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet("""
            QMainWindow#opticsWorkbench {background:#ffffff; color:#202733;}
            QWidget {color:#202733;}
            QFrame#workbenchSidebar {background:#f3f4f6;border-right:1px solid #dfe3e8;}
            QFrame#workbenchPageHeader {background:#fafbfc;border-bottom:1px solid #e1e5eb;}
            QLabel#workbenchBrand {color:#4c596b;font-size:11px;font-weight:600;}
            QLabel#workbenchFootnote {color:#778393;font-size:9px;}
            QPushButton {color:#253142;}
            QPushButton:disabled {color:#929cab;}
            QPushButton[navigation="true"] {border:0;border-radius:5px;padding:9px;background:transparent;color:#334155;}
            QPushButton[navigation="true"]:hover {background:#e8ebef;}
            QPushButton[navigation="true"]:checked {background:#e0ecfa;color:#205c99;font-weight:600;}
            QPushButton[navigation="true"]:disabled {color:#98a1ae;}
            QToolBar#workbenchToolbar {background:#ffffff;border-bottom:1px solid #dfe3e8;padding:5px;spacing:3px;}
            QToolBar QToolButton {border:0;border-radius:4px;padding:6px 9px;color:#253142;}
            QToolBar QToolButton:disabled {color:#929cab;}
            QToolBar QToolButton:hover {background:#edf1f6;}
            QToolBar QToolButton:checked {background:#e0ecfa;color:#205c99;}
            QDockWidget {background:#f8f9fb;color:#202733;border-left:1px solid #dfe3e8;}
            QDockWidget::title {padding:10px;background:#f1f3f6;font-weight:600;}
            QPlainTextEdit {background:white;color:#253142;border:1px solid #dbe1e9;selection-background-color:#d8e9fc;}
            QLineEdit, QComboBox, QTableWidget, QTreeView {background:white;color:#253142;selection-background-color:#d8e9fc;selection-color:#202733;}
            QHeaderView::section {background:#f1f3f6;color:#435169;padding:5px;border:0;border-bottom:1px solid #dce2ea;}
            QStatusBar {background:#f1f3f6;color:#526070;border-top:1px solid #e0e4e9;}
            QSplitter::handle {background:#e5e9ef;height:5px;width:5px;}
            QGroupBox {border:1px solid #dce2ea;border-radius:6px;margin-top:16px;padding:17px;}
            QGroupBox::title {subcontrol-origin:margin;left:13px;padding:0 4px;}
        """)

    def _status(self, message):
        if not self._closed:
            self.statusBar().showMessage(str(message))

    def _on_ready(self, ready):
        if self._closed:
            return
        self._ready = bool(ready)
        self._enable_controls()
        if self._ready:
            self._status("Local workspace ready · Optical backend and LLM execution remain TBU")
            self._refresh_renderer_state()
            self._initialize_saved_state()

    def _refresh_renderer_state(self):
        captured = (self._state_event_revision, self._navigation_revision, self._session_generation)
        def received(ok, value):
            current = (self._state_event_revision, self._navigation_revision, self._session_generation)
            if ok and current == captured:
                self._on_state_changed(value)
        self._send("get_state", callback=received)

    def _on_state_event(self, value):
        self._state_event_revision += 1
        self._on_state_changed(value)

    def _enable_controls(self):
        locked = self._initializing or self._opening or self._close_query or self._close_after_save
        for action in self._renderer_actions:
            action.setEnabled(self._ready and not locked and not (self._saving and action in {self.save_action, self.export_action}))
        for page in PAGE_LABELS:
            enabled = (self._ready or page == "explorer") and not locked
            self.nav_buttons[page].setEnabled(enabled)
            self.nav_actions[page].setEnabled(enabled)
        self.llm_editor.setEnabled(self._ready and not locked)
        self.sensitivity.setEnabled(self._ready and not locked)
        self.renderer.setEnabled(not locked)
        self.explorer.setEnabled(not locked)
        self.analysis_action.setEnabled(self._ready and not locked and self.current_page == "workspace" and self._frontend_view == "workspace")
        if self.chart_manager:
            for kind in ('mtf', 'spot'):
                chart = self.chart_manager.window(kind)
                if chart is not None:
                    chart.setEnabled(not locked)

    def _send(self, action, payload=None, callback=None):
        if self._closed:
            return None
        if not self._ready:
            message = "화면이 준비될 때까지 잠시 기다려 주세요."
            self._status(message)
            if callback is not None:
                callback(False, {'message': message})
            return None
        def completed(ok, data):
            if self._closed:
                return
            if not ok:
                self._status(data.get("message", "UI request failed.") if isinstance(data, dict) else "UI request failed.")
            if callback is not None:
                callback(ok, data)
        return self.controller.command(action, payload, completed)

    def _show_page(self, page):
        self.current_page = page
        self.page_heading.setText(PAGE_LABELS[page])
        self.setWindowTitle(f"Optics Studio {__version__} — Local Workbench")
        self.pages.setCurrentWidget(self.explorer if page == "explorer" else self.tailoring_page if page == "tailoring" else self.workspace_page)
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page)
        self._update_analysis()

    def navigate(self, page):
        if self._closed or page not in PAGE_LABELS or not self._ready and page != "explorer":
            return
        self._navigation_revision += 1
        self._pending_navigation = None
        if page in RENDERER_PAGES:
            self._frontend_view = page
            self._pending_navigation = (self._navigation_revision, page)
        self._show_page(page)
        self._enable_controls()
        if page in RENDERER_PAGES:
            self._send("navigate", {"page": page})

    def _open_renderer_tool(self, action):
        if not self._ready:
            return
        self._navigation_revision += 1
        self._pending_navigation = (self._navigation_revision, action)
        self._frontend_view = action
        self._show_page("workspace")
        self._enable_controls()
        self._send(action)

    def _on_state_changed(self, value, *, accept_view=True):
        if self._closed or not isinstance(value, dict):
            return
        self._last_state = deepcopy(value)
        if isinstance(value.get("analysis_context"), dict):
            self.sensitivity.set_context(value["analysis_context"])
        if isinstance(value.get("model_label"), str):
            self.model_label.setText(value["model_label"])
            self.model_label.setToolTip(value["model_label"])
        if isinstance(value.get("llm_draft"), str) and not self._llm_dirty:
            self._set_draft(value["llm_draft"])
        revision = value.get('chart_revision')
        if revision is not None and revision != self._chart_revision:
            self._chart_revision = revision
            self._refresh_charts()
        view = value.get("view")
        expected = self._pending_navigation[1] if self._pending_navigation is not None else None
        if (accept_view and isinstance(view, str) and (view in RENDERER_PAGES or view in FRONTEND_AUXILIARY_PAGES)
                and (expected is None or view == expected)):
            self._pending_navigation = None
            self._frontend_view = view
            if self.current_page not in {"explorer", "tailoring"}:
                self._show_page(view if view in RENDERER_PAGES else "workspace")
        self._enable_controls()

    def _draft_changed(self):
        self._llm_dirty = True

    def _set_draft(self, text):
        self.llm_editor.blockSignals(True)
        self.llm_editor.setPlainText(text)
        self.llm_editor.blockSignals(False)
        self._llm_dirty = False

    def toggle_llm(self):
        if self._ready and not self._closed:
            self.llm_action.setChecked(not self.llm_action.isChecked())

    def _sync_llm_action(self, _visible):
        self.llm_action.blockSignals(True)
        self.llm_action.setChecked(not self.llm_dock.isHidden())
        self.llm_action.blockSignals(False)

    def _remember_split(self, *_args):
        sizes = self.workspace_splitter.sizes()
        if len(sizes) == 2 and all(size > 0 for size in sizes):
            self._last_split_sizes = sizes

    def _toggle_analysis(self, *_args):
        self._update_analysis()

    def _update_analysis(self, *_args):
        expanded = (hasattr(self, "analysis_action") and self.analysis_action.isChecked()
                    and self.current_page == "workspace" and self._frontend_view == "workspace")
        self.sensitivity.setVisible(bool(expanded))
        if expanded:
            self.workspace_splitter.setSizes(self._last_split_sizes)

    def open_parameters(self):
        if self._closed or not self._ready or self._parameters_pending:
            return
        if self.parameter_dialog is not None:
            self.parameter_dialog.raise_()
            self.parameter_dialog.activateWindow()
            return
        self._parameters_pending = True
        def received(ok, data):
            self._parameters_pending = False
            if not ok or not isinstance(data, dict):
                return
            payload = data.get("parameter_payload")
            if not isinstance(payload, dict):
                self._status("파라미터 정보를 가져올 수 없습니다. 참조 설계를 먼저 선택하세요.")
                return
            def commit(payload, completed):
                if self._closed or not self._ready:
                    completed(False, {"message": "화면 연결이 준비되지 않아 적용할 수 없습니다. 입력값은 유지됩니다."})
                    return
                self._send("apply_parameters", payload, completed)
            try:
                dialog = ParameterDialog(payload, self, commit=commit)
            except (ValueError, TypeError) as error:
                self._status(f"Parameter dialog could not open: {error}")
                return
            self.parameter_dialog = dialog
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            def finished(_):
                if self.parameter_dialog is dialog:
                    self.parameter_dialog = None
            dialog.finished.connect(finished)
            dialog.open()
        self._send("get_state", callback=received)

    def collect_state(self):
        sizes = self.workspace_splitter.sizes() if not self.sensitivity.isHidden() else self._last_split_sizes
        if len(sizes) != 2 or sum(sizes) <= 0:
            sizes = [550, 250]
        explorer_split = self.explorer.splitter.sizes()
        if len(explorer_split) != 2 or sum(explorer_split) <= 0:
            explorer_split = [240, 800]
        return validate_workbench_state({
            "version": 2, "page": self.current_page,
            "llm_visible": not self.llm_dock.isHidden(), "analysis_visible": self.analysis_action.isChecked(),
            "workspace_split": list(sizes), "explorer": self.explorer.snapshot(),
            "sensitivity": self.sensitivity.snapshot(),
            "layout": {'window': capture_window_layout(self), 'llm_width': self._llm_width,
                       'explorer_split': explorer_split, 'charts': self.chart_manager.snapshot() if self.chart_manager else
                       {kind: {'open': False, 'window': None} for kind in ('mtf', 'spot')}},
        })

    def restore_state(self, state):
        if self._closed or not isinstance(state, dict):
            return False
        workbench = state.get("workbench")
        if workbench is not None:
            try:
                native = validate_workbench_state(workbench)
            except WorkbenchStateError as error:
                self._status(f"Workbench restore rejected: {error}")
                return False
            self._begin_restored_session()
            self._navigation_revision += 1
            self._pending_navigation = None
            self._restore_had_errors = not self.explorer.restore(native["explorer"])
            sensitivity = native["sensitivity"] or {"format": "optics-sensitivity-panel", "schema_version": 1,
                                                    "metric": "S1", "report": None, "report_path": None, "output_id": None, "stale": False}
            if not self.sensitivity.restore(sensitivity):
                self._restore_had_errors = True
            self._last_split_sizes = native["workspace_split"]
            self.analysis_action.setChecked(native["analysis_visible"])
            self.llm_action.setChecked(native["llm_visible"])
            self._frontend_view = native["page"] if native["page"] in RENDERER_PAGES else self._frontend_view
            self._show_page(native["page"])
            self.workspace_splitter.setSizes(self._last_split_sizes)
            if native['version'] == 2:
                self._restore_layout(native['layout'])
            else:
                self._refresh_charts()
        else:
            self._begin_restored_session()
            self._navigation_revision += 1
            self._pending_navigation = None
            view = state.get("view", self._last_state.get("view", "workspace"))
            self._frontend_view = view if isinstance(view, str) else "workspace"
            self._show_page(view if isinstance(view, str) and view in RENDERER_PAGES else "workspace")
            self._refresh_charts()
        if isinstance(state.get("llm_draft"), str):
            self._set_draft(state["llm_draft"])
        else:
            # An explicit Open replaces the prior draft. The restore event may
            # contain only native state; fetch the restored renderer draft.
            self._llm_dirty = False
            self._refresh_renderer_state()
        self._enable_controls()
        return True

    def _begin_restored_session(self):
        self._session_generation += 1
        self._restored_fingerprint = None
        self._restore_had_errors = False
        self._finishing_restore = False
        if self._save_token is not None:
            self._save_token = None
            self._saving = False
            self._status("A new session was opened; the previous save preparation was cancelled.")

    def _save_or_export(self, action, on_complete=None):
        if not self._ready or self._closed or self._saving:
            if on_complete:
                on_complete(False)
            return
        try:
            snapshot = self.collect_state()
        except ValueError as error:
            self._status(f"Session could not be prepared: {error}")
            if on_complete:
                on_complete(False)
            return
        draft = self.llm_editor.toPlainText()
        generation = self._session_generation
        token = object()
        self._save_token = token
        self._saving = True
        self._enable_controls()
        def owns_request():
            return self._save_token is token and self._session_generation == generation
        def finished(ok, data):
            if not owns_request():
                return
            self._save_token = None
            self._saving = False
            self._enable_controls()
            successful = ok and isinstance(data, dict) and data.get('status') == ('saved' if action == 'save' else 'exported')
            if successful:
                self._status("Session saved." if data["status"] == "saved" else "Session bundle exported.")
                if action == 'save' and isinstance(data.get('session_fingerprint'), str):
                    self._saved_state.mark_saved(data['session_fingerprint'], snapshot, draft)
            if on_complete:
                on_complete(bool(successful))
            elif self._close_after_save:
                self._close_after_save = False
                if successful:
                    self._request_close_check()
                else:
                    self._enable_controls()
        def draft_set(ok, data):
            if not owns_request():
                return
            if not ok:
                finished(False, data)
                return
            if self.llm_editor.toPlainText() == draft:
                self._llm_dirty = False
            self._send(action, callback=finished)
        def shell_set(ok, data):
            if not owns_request():
                return
            if not ok:
                finished(False, data)
                return
            self._send("set_llm_draft", {"draft": draft}, draft_set)
        self._send("set_shell_state", snapshot, shell_set)

    def save_session(self):
        self._save_or_export("save")

    def export_session(self):
        self._save_or_export("export")

    def eventFilter(self, watched, event):
        if (watched is getattr(self, 'llm_dock', None) and event.type() == QEvent.Type.Resize
                and not self._restoring_layout and not self.llm_dock.isHidden()):
            self._llm_width = max(1, self.llm_dock.width())
        return super().eventFilter(watched, event)

    def _restore_layout(self, layout):
        self._restoring_layout = True
        try:
            apply_window_layout(self, layout['window'])
            self._llm_width = min(self.llm_dock.maximumWidth(), max(self.llm_dock.minimumWidth(), layout['llm_width']))
            self.resizeDocks([self.llm_dock], [self._llm_width], Qt.Orientation.Horizontal)
            # Hidden stacked pages can still have their initial 640px size.
            # Lay out Explorer against the real page before restoring its fixed
            # tree width; the code pane receives the remaining space.
            self.explorer.resize(self.pages.contentsRect().size())
            self.explorer.layout().activate()
            left = layout['explorer_split'][0]
            remainder = max(1, self.explorer.splitter.width() - self.explorer.splitter.handleWidth() - left)
            self.explorer.splitter.setSizes([left, remainder])
        finally:
            self._restoring_layout = False
        self._layout_restore_pending = 0
        if self.chart_manager:
            self.chart_manager.close_all()
            for kind, saved in layout['charts'].items():
                self.chart_manager.set_saved_layout(kind, saved['window'])
                if saved['open']:
                    self._layout_restore_pending += 1
                    self._request_chart(kind, open_window=True, restoring=True)

    def attach_chart_manager(self, manager):
        self.chart_manager = manager
        manager.statusMessage.connect(self._status)
        manager.viewChanged.connect(lambda event: self._send('set_chart_view', event))

    def _chart_requested(self, event):
        if not self._closed and self.chart_manager:
            self.chart_manager.open_chart(event.get('kind'), event.get('data'))
            self._enable_controls()

    def _refresh_charts(self):
        if self.chart_manager and self._ready and not self._layout_restore_pending:
            for kind in ('mtf', 'spot'):
                if self.chart_manager.window(kind) is not None:
                    self._request_chart(kind)

    def _request_chart(self, kind, *, open_window=False, restoring=False):
        self._chart_tickets[kind] += 1
        ticket, generation = self._chart_tickets[kind], self._session_generation
        def received(ok, data):
            if generation != self._session_generation:
                return
            if ok and ticket == self._chart_tickets[kind] and self.chart_manager:
                if open_window:
                    applied = self.chart_manager.open_chart(kind, data) is not None
                else:
                    applied = self.chart_manager.set_data(kind, data)
                if restoring and not applied:
                    self._restore_had_errors = True
                self._enable_controls()
            elif restoring:
                self._restore_had_errors = True
            if restoring:
                self._layout_restore_pending = max(0, self._layout_restore_pending - 1)
                if self._layout_restore_pending == 0:
                    self._refresh_charts()
                self._finish_restored_baseline()
        self._send('get_chart_data', {'kind': kind}, received)

    def _initialize_saved_state(self):
        if self._saved_state.initialized or self._initializing or self._opening:
            return
        generation = self._session_generation
        self._initializing = True
        self._enable_controls()
        def received(ok, value):
            self._initializing = False
            if generation == self._session_generation and ok and isinstance(value, dict) and isinstance(value.get('session_fingerprint'), str):
                try:
                    self._saved_state.mark_saved(value['session_fingerprint'], self.collect_state(), self.llm_editor.toPlainText())
                except ValueError as error:
                    self._status(str(error))
            self._enable_controls()
        self._send('get_session_snapshot', callback=received)

    def open_session(self):
        if self._opening or not self._ready or self._closed:
            return
        self._opening = True
        self._open_command_done = False
        self._restored_fingerprint = None
        self._enable_controls()
        def received(ok, value):
            self._open_command_done = True
            if ok and isinstance(value, dict) and value.get('status') == 'loaded':
                self._finish_restored_baseline()
            else:
                self._opening = False
                self._enable_controls()
        self._send('open', callback=received)

    def _on_session_opened(self, event):
        if isinstance(event.get('session_fingerprint'), str):
            self._restored_fingerprint = event['session_fingerprint']
            self._finish_restored_baseline()

    def _finish_restored_baseline(self):
        if (self._layout_restore_pending or self._finishing_restore or not self._open_command_done
                or not isinstance(self._restored_fingerprint, str)):
            return
        self._finishing_restore = True
        generation = self._session_generation
        fingerprint = self._restored_fingerprint
        def received(ok, value):
            if generation != self._session_generation:
                return
            self._finishing_restore = False
            if ok and isinstance(value, dict):
                self._on_state_changed(value)
                try:
                    if self._restore_had_errors:
                        self._saved_state = UnsavedState()
                        self._status('일부 화면 설정을 복원하지 못했습니다. 현재 상태를 확인한 뒤 다시 저장하세요.')
                    else:
                        self._saved_state.mark_saved(fingerprint, self.collect_state(), self.llm_editor.toPlainText())
                except ValueError as error:
                    self._status(str(error))
            self._restored_fingerprint = None
            self._opening = False
            self._enable_controls()
        self._send('get_state', callback=received)

    def _confirm_unsaved_close(self, *, can_save=True, message=None):
        box = QMessageBox(self)
        box.setWindowTitle('변경 사항 저장')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(message or '저장하지 않은 설계 또는 화면 설정이 있습니다.')
        box.setInformativeText('저장 후 종료하거나, 저장하지 않고 종료할 수 있습니다.')
        buttons = QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        if can_save:
            buttons |= QMessageBox.StandardButton.Save
        box.setStandardButtons(buttons)
        box.button(QMessageBox.StandardButton.Discard).setText('저장하지 않고 종료')
        box.button(QMessageBox.StandardButton.Cancel).setText('취소')
        if can_save:
            box.button(QMessageBox.StandardButton.Save).setText('저장 후 종료')
        box.setDefaultButton(QMessageBox.StandardButton.Save if can_save else QMessageBox.StandardButton.Cancel)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        choice = box.exec()
        box.deleteLater()
        return {QMessageBox.StandardButton.Save: 'save', QMessageBox.StandardButton.Discard: 'discard'}.get(choice, 'cancel')

    def _request_close_check(self):
        if self._close_query or self._closed:
            return
        self._close_query = True
        self._enable_controls()
        generation = self._session_generation
        def received(ok, value):
            if generation != self._session_generation:
                self._close_query = False
                self._enable_controls()
                return
            message = None
            try:
                fingerprint = value.get('session_fingerprint') if ok and isinstance(value, dict) else None
                if not isinstance(fingerprint, str):
                    raise ValueError('현재 저장 상태를 확인하지 못했습니다. 변경 내용이 있을 수 있습니다.')
                dirty = self._saved_state.changed(fingerprint, self.collect_state(), self.llm_editor.toPlainText())
            except ValueError as error:
                message, dirty = str(error), True
            if not dirty:
                self.close_for_shutdown()
                return
            decision = self._confirm_close(can_save=self._ready, message=message)
            self._close_query = False
            if decision == 'discard':
                self.close_for_shutdown()
            elif decision == 'save' and self._ready:
                self._close_after_save = True
                self._enable_controls()
                def saved(success):
                    self._close_after_save = False
                    self._enable_controls()
                    if success:
                        self._request_close_check()
                self._save_or_export('save', saved)
            else:
                self._enable_controls()
        if self._ready:
            self._send('get_session_snapshot', callback=received)
        else:
            received(False, None)

    def close_for_shutdown(self):
        """Close after an explicit decision, or opt-in test/application shutdown."""
        self._allow_close = True
        self._closed = True
        self._parameters_pending = False
        if self.parameter_dialog is not None:
            self.parameter_dialog.close_for_shutdown()
        if self.chart_manager:
            self.chart_manager.close_all()
        self._close_timer.start(0)

    def closeEvent(self, event):
        if self._allow_close:
            super().closeEvent(event)
            return
        event.ignore()
        if self.parameter_dialog is not None:
            self.parameter_dialog.raise_()
            self.parameter_dialog.activateWindow()
            self._status('파라미터 창에서 적용 또는 취소를 완료한 뒤 종료하세요.')
            return
        if self._opening or self._initializing:
            self._status('설정을 불러오는 중입니다. 완료 후 다시 종료해 주세요.')
            return
        if self._saving:
            self._close_after_save = True
            self._enable_controls()
            return
        if not self._ready and not self._saved_state.initialized:
            self.close_for_shutdown()
            return
        self._request_close_check()
