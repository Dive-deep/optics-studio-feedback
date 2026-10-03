"""Native, read-only source Explorer with movable, independently closable tabs."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

from PySide6.QtCore import QDir, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFontDatabase, QKeySequence, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFileSystemModel, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeView, QVBoxLayout, QWidget,
)

from ..services.source_files import DEFAULT_WORKSPACE_ROOT, HIDDEN_COMPONENTS, SourceFileError, SourceFilesService
from ..services.workbench_state import MAX_FILES as MAX_SOURCE_TABS


class _SourceFilter(QSortFilterProxyModel):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        path = Path(model.filePath(index))
        if path.name.casefold() in HIDDEN_COMPONENTS:
            return False
        # QFileSystemModel retains ancestor indexes to reach its root. Do not
        # enumerate them; the QTreeView is explicitly rooted at the workspace.
        if path in self.service.root_path.parents:
            return True
        try:
            self.service.resolve_path(path)
            return True
        except SourceFileError:
            return False


class _CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language):
        super().__init__(document)
        self.rules = []
        def add(pattern, color):
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            self.rules.append((re.compile(pattern), style))
        add(r'\b\d+(?:\.\d+)?\b', '#8b62b8')
        add(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", '#508662')
        if language == "python":
            add(r'\b(?:def|class|return|if|elif|else|for|while|try|except|finally|with|as|from|import|pass|raise|yield|async|await|True|False|None|and|or|not|in|is|lambda)\b', '#9564b2')
            add(r'#[^\n]*', '#7b8794')
        elif language == "json":
            add(r'\b(?:true|false|null)\b', '#9564b2')
            add(r'"(?:\\.|[^"\\])*"(?=\s*:)', '#398397')

    def highlightBlock(self, text):
        # A minified multi-megabyte line remains readable without expensive
        # per-token formatting; this never truncates the underlying document.
        if len(text) > 20_000:
            return
        for pattern, style in self.rules:
            previous, offset = 0, 0
            for match in pattern.finditer(text):
                offset += len(text[previous:match.start()].encode("utf-16-le")) // 2
                length = len(match.group().encode("utf-16-le")) // 2
                self.setFormat(offset, length, style)
                previous, offset = match.end(), offset + length


class ExplorerPage(QWidget):
    statusMessage = Signal(str)

    def __init__(self, parent=None, *, workspace_root=DEFAULT_WORKSPACE_ROOT):
        super().__init__(parent)
        self.service = SourceFilesService(workspace_root)
        self.root_path = self.service.root_path
        self._external_processes = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        toolbar = QHBoxLayout()
        self.folder_button = QPushButton("Open folder…")
        self.folder_button.clicked.connect(self._choose_folder)
        self.path_label = QLineEdit(str(self.root_path))
        self.path_label.setReadOnly(True)
        self.path_label.setAccessibleName("Source workspace folder")
        self.wrap_checkbox = QCheckBox("Wrap lines")
        self.wrap_checkbox.toggled.connect(self._set_wrap)
        self.vscode_button = QPushButton("Open in VS Code")
        self.vscode_button.setEnabled(False)
        self.vscode_button.clicked.connect(self._open_vscode)
        toolbar.addWidget(self.folder_button)
        toolbar.addWidget(self.path_label, 1)
        toolbar.addWidget(self.wrap_checkbox)
        toolbar.addWidget(self.vscode_button)
        layout.addLayout(toolbar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeView()
        self.tree.setAccessibleName("Workspace source files")
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.activated.connect(self._activate)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(lambda _: self.vscode_button.setEnabled(self.tabs.currentWidget() is not None))
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 800])
        layout.addWidget(self.splitter, 1)
        self.message_label = QLabel("파일을 선택하면 실제 소스를 읽기 전용으로 표시합니다.")
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.close_action = QAction("Close code tab", self)
        shortcuts = [QKeySequence(QKeySequence.StandardKey.Close), QKeySequence("Ctrl+W")]
        self.close_action.setShortcuts(list({key.toString(): key for key in shortcuts}.values()))
        self.close_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.close_action.triggered.connect(self.close_current_tab)
        self.addAction(self.close_action)
        self.fs_model = None
        self.proxy = None
        self._set_tree_root()

    def _notify(self, message):
        self.message_label.setText(message)
        self.statusMessage.emit(message)

    def _set_tree_root(self):
        old_model, old_proxy = self.fs_model, self.proxy
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setReadOnly(True)
        self.fs_model.setResolveSymlinks(False)
        self.fs_model.setOption(QFileSystemModel.Option.DontUseCustomDirectoryIcons, True)
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.proxy = _SourceFilter(self.service, self)
        self.proxy.setSourceModel(self.fs_model)
        self.tree.setModel(self.proxy)
        source_index = self.fs_model.setRootPath(str(self.root_path))
        self.tree.setRootIndex(self.proxy.mapFromSource(source_index))
        for column in range(1, self.fs_model.columnCount()):
            self.tree.hideColumn(column)
        if old_proxy is not None:
            old_proxy.deleteLater()
        if old_model is not None:
            old_model.deleteLater()

    def _choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose source workspace", str(self.root_path))
        if selected:
            self.open_folder(selected)

    def open_folder(self, path):
        try:
            service = SourceFilesService(path)
        except SourceFileError as error:
            self._notify(error.message)
            return False
        if service.root_path != self.root_path:
            while self.tabs.count():
                self._close_tab(0)
            self.service = service
            self.root_path = service.root_path
            self.path_label.setText(str(self.root_path))
            self._set_tree_root()
        self._notify(f"Source workspace: {self.root_path}")
        return True

    def _activate(self, index):
        source_index = self.proxy.mapToSource(index)
        if not self.fs_model.isDir(source_index):
            self.open_file(self.fs_model.filePath(source_index))

    def open_file(self, path):
        try:
            canonical = self.service.resolve_path(path)
            for index in range(self.tabs.count()):
                if Path(self.tabs.widget(index).property("source_path")) == canonical:
                    self.tabs.setCurrentIndex(index)
                    return True
            if self.tabs.count() >= MAX_SOURCE_TABS:
                self._notify(f"최대 {MAX_SOURCE_TABS}개 코드 탭을 열 수 있습니다. 기존 탭을 닫고 다시 열어 주세요.")
                return False
            document = self.service.read_file(canonical)
        except SourceFileError as error:
            self._notify(error.message)
            return False
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        editor.setPlainText(document.text)
        editor.setProperty("source_path", str(document.path))
        editor.setProperty("language", document.language)
        editor.setAccessibleName(f"Read-only source: {document.path.name}")
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap_checkbox.isChecked() else QPlainTextEdit.LineWrapMode.NoWrap)
        if document.language in {"python", "json"}:
            editor._source_highlighter = _CodeHighlighter(editor.document(), document.language)
        index = self.tabs.addTab(editor, document.path.name)
        self.tabs.setTabToolTip(index, str(document.path))
        self.tabs.setCurrentIndex(index)
        self._notify(f"Read only · {document.path.relative_to(self.root_path)} · {document.size_bytes:,} bytes")
        return True

    def _close_tab(self, index):
        editor = self.tabs.widget(index)
        if editor is not None:
            self.tabs.removeTab(index)
            editor.deleteLater()

    def close_current_tab(self):
        self._close_tab(self.tabs.currentIndex())

    def _set_wrap(self, enabled):
        for index in range(self.tabs.count()):
            self.tabs.widget(index).setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap)

    def snapshot(self):
        files = [Path(self.tabs.widget(index).property("source_path")).relative_to(self.root_path).as_posix() for index in range(self.tabs.count())]
        current = self.tabs.currentIndex()
        return {"workspace_root": str(self.root_path), "files": files,
                "current_file": files[current] if current >= 0 else None, "wrap_lines": self.wrap_checkbox.isChecked()}

    def restore(self, saved):
        if (not isinstance(saved, dict) or not isinstance(saved.get("files", []), list)
                or any(not isinstance(path, str) for path in saved.get("files", []))
                or not isinstance(saved.get("wrap_lines", False), bool)):
            self._notify("Source workspace settings are invalid; current tabs were preserved.")
            return False
        root = saved.get("workspace_root", str(self.root_path))
        if not isinstance(root, str) or not Path(root).is_absolute():
            self._notify("Source workspace settings need an absolute workspace folder.")
            return False
        if not self.open_folder(root):
            return False
        while self.tabs.count():
            self._close_tab(0)
        self.wrap_checkbox.setChecked(saved.get("wrap_lines", False))
        errors = []
        for path in saved.get("files", []):
            if not self.open_file(path):
                errors.append(self.message_label.text())
        selected = saved.get("current_file")
        if isinstance(selected, str):
            for index in range(self.tabs.count()):
                relative = Path(self.tabs.widget(index).property("source_path")).relative_to(self.root_path).as_posix()
                if relative == selected:
                    self.tabs.setCurrentIndex(index)
                    break
        if errors:
            self._notify(f"Restored {self.tabs.count()} code tabs; skipped {len(errors)} files. " + " ".join(errors[:3]))
        return not errors

    def _open_vscode(self):
        editor = self.tabs.currentWidget()
        if editor is None:
            return
        try:
            path = self.service.resolve_path(editor.property("source_path"))
            executable = shutil.which("code")
            if executable is None:
                self._notify("VS Code CLI 'code' was not found. Install its PATH command to use this button.")
                return
            if sys.platform == "win32" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
                # Avoid cmd.exe interpretation of file names containing shell symbols.
                native = Path(executable).parent.parent / "Code.exe"
                if not native.is_file():
                    self._notify("The native VS Code executable was not found beside its CLI wrapper.")
                    return
                executable = str(native)
            line = editor.textCursor().blockNumber() + 1
            process = subprocess.Popen([executable, "--goto", f"{path}:{line}"], cwd=self.root_path,
                                       shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            self._external_processes = [item for item in self._external_processes if item.poll() is None]
            self._external_processes.append(process)
            self._notify(f"Requested VS Code: {path.name}:{line}")
        except (SourceFileError, OSError) as error:
            self._notify(f"Could not open VS Code: {error}")
