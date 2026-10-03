"""Independent, reusable native MTF/Spot windows with a read-only data bridge.

The shared profile belongs to the desktop host. Call manager.shutdown() before
destroying that profile. Chart pages expose only their own data and zoom state,
never the desktop file/job bridge. Esc and Close hide one chart, not Workspace.
"""
from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..services.chart_data import (
    CHART_KINDS, MAX_PAYLOAD_BYTES, ChartDataError, finite_json,
    validate_chart_payload, validate_chart_view,
)


def _kind(kind):
    if not isinstance(kind, str) or kind not in CHART_KINDS:
        raise ChartDataError("Unsupported chart kind.")
    return kind


def _rect(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"x", "y", "width", "height", "maximized"}
            or type(value["maximized"]) is not bool
            or any(type(value[key]) is not int for key in ("x", "y", "width", "height"))
            or any(not -(2**31) <= value[key] <= 2**31 - 1 for key in ("x", "y"))
            or any(not 1 <= value[key] <= 16777215 for key in ("width", "height"))):
        raise ChartDataError("Chart window geometry is invalid.")
    return deepcopy(value)


class ChartBridge(QObject):
    dataChanged = Signal(str)
    viewStateChanged = Signal(dict)

    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self._payload = validate_chart_payload(payload)

    @Slot(result=str)
    def chartData(self):
        return json.dumps(self._payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    def set_data(self, payload):
        validated = validate_chart_payload(payload, kind=self._payload["kind"])
        self._payload = validated
        self.dataChanged.emit(self.chartData())

    @Slot(str)
    def viewChanged(self, raw):
        """Accept a local chart gesture only for the currently displayed data."""
        try:
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                return
            event = json.loads(raw)
            finite_json(event)
            if (not isinstance(event, dict) or set(event) != {"kind", "revision", "view"}
                    or event["kind"] != self._payload["kind"]
                    or event["revision"] != self._payload["revision"]):
                return
            event["view"] = validate_chart_view(event["view"])
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return
        self.viewStateChanged.emit(deepcopy(event))


class _ChartPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main):
        return url.scheme() == "optics-app" and url.host() == "ui"


class ChartWindow(QDialog):
    closed = Signal(str)
    viewChanged = Signal(dict)
    statusMessage = Signal(str)

    def __init__(self, kind, profile, payload, parent=None, *, page_factory=None, view_factory=None):
        self.kind = _kind(kind)
        validated = validate_chart_payload(payload, kind=kind)
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName(f"{kind}ChartWindow")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._disposed = False
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.error_label = QLabel()
        self.error_label.setObjectName("chartLoadError")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#963a28;background:#fff0e8;padding:12px;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.view = (view_factory or QWebEngineView)(self)
        layout.addWidget(self.view)
        self.page = page_factory(self.view) if page_factory else _ChartPage(profile, self.view)
        self.view.setPage(self.page)
        self.bridge = ChartBridge(validated, self.page)
        self.bridge.viewStateChanged.connect(self.viewChanged.emit)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("chart", self.bridge)
        self.page.setWebChannel(self.channel)
        self._title(validated)
        from .layout import apply_window_layout
        position = parent.geometry().topLeft() if parent is not None else self.geometry().topLeft()
        apply_window_layout(self, {"x": position.x() + 40, "y": position.y() + 40,
                                   "width": 900, "height": 650, "maximized": False}, minimum_size=(420, 300))
        self.view.loadFinished.connect(self._load_finished)
        self.view.load(QUrl("optics-app://ui/chart-window.html?kind=" + kind))

    def _load_finished(self, succeeded):
        if self._disposed:
            return
        self.error_label.setVisible(not succeeded)
        if not succeeded:
            message = "Chart could not load its local page. Check the bundled chart assets; Workspace remains available."
            self.error_label.setText(message)
            self.statusMessage.emit(message)

    def _title(self, payload):
        title = "MTF curve" if self.kind == "mtf" else "Spot diagram"
        self.setWindowTitle(f"{title} · {payload['reference_id']}")

    def set_data(self, payload):
        if self._disposed:
            return
        self.bridge.set_data(payload)
        self._title(self.bridge._payload)

    def closeEvent(self, event):
        event.accept()
        was_visible = self.isVisible()
        self.hide()
        if was_visible and not self._disposed:
            self.closed.emit(self.kind)

    def reject(self):
        self.close()

    def dispose(self):
        """Release page/view ownership before the host releases its profile."""
        if self._disposed:
            return
        self._disposed = True
        self.hide()
        self.view.stop()
        self.page.setWebChannel(None)
        self.deleteLater()
        # Flush only this dialog's deletion; do not drain unrelated app events.
        QCoreApplication.sendPostedEvents(self, QEvent.Type.DeferredDelete)


class ChartWindowManager(QObject):
    statusMessage = Signal(str)
    viewChanged = Signal(dict)
    windowsChanged = Signal()

    def __init__(self, profile, parent=None, *, page_factory=None, view_factory=None):
        super().__init__(parent)
        self.profile = profile
        self._parent_window = parent
        self._page_factory, self._view_factory = page_factory, view_factory
        self._windows, self._payloads, self._layouts = {}, {}, {}
        self._closed = False

    def window(self, kind):
        return self._windows.get(kind) if isinstance(kind, str) else None

    def set_data(self, kind, payload):
        if self._closed:
            return False
        try:
            _kind(kind)
            validated = validate_chart_payload(payload, kind=kind)
            if kind in self._windows:
                self._windows[kind].set_data(validated)
            self._payloads[kind] = validated
        except ChartDataError as error:
            self.statusMessage.emit(error.message)
            return False
        return True

    def open_chart(self, kind, payload=None):
        if self._closed:
            return None
        try:
            _kind(kind)
        except ChartDataError as error:
            self.statusMessage.emit(error.message)
            return None
        if not self.set_data(kind, self._payloads.get(kind) if payload is None else payload):
            return None
        if kind not in self._windows:
            window = ChartWindow(kind, self.profile, self._payloads[kind], self._parent_window,
                                 page_factory=self._page_factory, view_factory=self._view_factory)
            window.closed.connect(self._on_closed)
            window.viewChanged.connect(self.viewChanged.emit)
            window.statusMessage.connect(self.statusMessage.emit)
            self._windows[kind] = window
            if self._layouts.get(kind) is not None:
                self.apply_layout(kind, self._layouts[kind])
        window = self._windows[kind]
        if window.isMinimized():
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        self.windowsChanged.emit()
        return window

    def _on_closed(self, kind):
        if not self._closed:
            from .layout import capture_window_layout
            self._layouts[kind] = capture_window_layout(self._windows[kind])
            self.windowsChanged.emit()

    def set_saved_layout(self, kind, rect):
        return self.apply_layout(kind, rect)

    def apply_layout(self, kind, rect):
        if self._closed:
            return False
        try:
            _kind(kind)
            validated = _rect(rect)
        except ChartDataError as error:
            self.statusMessage.emit(error.message)
            return False
        self._layouts[kind] = validated
        if validated is not None and kind in self._windows:
            from .layout import apply_window_layout
            apply_window_layout(self._windows[kind], validated, minimum_size=(420, 300))
        return True

    def snapshot(self):
        from .layout import capture_window_layout
        return {kind: {"open": self._windows[kind].isVisible() if kind in self._windows else False,
                       "window": capture_window_layout(self._windows[kind]) if kind in self._windows
                       else deepcopy(self._layouts.get(kind))} for kind in ("mtf", "spot")}

    def close_all(self):
        for window in tuple(self._windows.values()):
            window.close()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        windows, self._windows = tuple(self._windows.values()), {}
        for window in windows:
            window.dispose()
        self._payloads.clear()
