"""Portable window rectangles, bounded to currently available logical screens."""
from copy import deepcopy
import weakref

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication


def fit_window_rect(saved, screens, minimum=(400, 300)):
    """Preserve the best overlapping monitor; recover offscreen saved layouts.

    Callers validate saved state before invoking this placement helper. Logical
    pixels make the record independent of physical device pixel ratios.
    """
    result = deepcopy(saved)
    if not screens:
        return result
    def overlap(screen):
        width = max(0, min(saved['x'] + saved['width'], screen['x'] + screen['width']) - max(saved['x'], screen['x']))
        height = max(0, min(saved['y'] + saved['height'], screen['y'] + screen['height']) - max(saved['y'], screen['y']))
        return width * height
    screen = max(screens, key=overlap)
    # Reserve room above the client rectangle for platform window decoration.
    pad_x, pad_y = 12, 30
    available_width = max(1, screen['width'] - 2 * pad_x)
    available_height = max(1, screen['height'] - pad_y - 12)
    result['width'] = min(available_width, max(minimum[0], saved['width']))
    result['height'] = min(available_height, max(minimum[1], saved['height']))
    result['x'] = max(screen['x'] + pad_x, min(saved['x'], screen['x'] + screen['width'] - pad_x - result['width']))
    result['y'] = max(screen['y'] + pad_y, min(saved['y'], screen['y'] + screen['height'] - 12 - result['height']))
    return result


class _MaximizedLayoutRestore(QObject):
    """Finish a real maximize only after the native window is shown normally.

    Cocoa can deliver an old zoom/normal transition after a hidden window's
    synchronous state changes, losing either its saved normal rectangle or its
    maximized state. Two queued phases let that transition settle without a
    nested processEvents loop or showing a window the caller wants hidden.
    """
    def __init__(self, widget):
        super().__init__(widget)
        self._widget = weakref.ref(widget)
        self.pending = None
        self._phase = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        widget.installEventFilter(self)

    def cancel(self):
        self._timer.stop()
        self.pending = None
        self._phase = None

    def stage(self, geometry):
        self.cancel()
        self.pending = deepcopy(geometry)
        self._phase = 'normal'
        widget = self._widget()
        if widget is not None and widget.isVisible():
            self._timer.start(0)

    def eventFilter(self, watched, event):
        if self.pending is not None:
            if event.type() == QEvent.Type.Show:
                self._phase = 'normal'
                self._timer.start(0)
            elif event.type() == QEvent.Type.Hide:
                self._timer.stop()
        return False

    @Slot()
    def _advance(self):
        widget = self._widget()
        if widget is None or self.pending is None or not widget.isVisible():
            return
        if self._phase == 'normal':
            saved = self.pending
            widget.setWindowState(Qt.WindowState.WindowNoState)
            widget.setGeometry(saved['x'], saved['y'], saved['width'], saved['height'])
            self._phase = 'maximize'
            self._timer.start(0)
        else:
            widget.setWindowState(Qt.WindowState.WindowMaximized)
            self.pending = None
            self._phase = None


def capture_window_layout(widget):
    pending = getattr(widget, '_optics_maximized_restore', None)
    if pending is not None and pending.pending is not None:
        # Preserve the requested state while a hidden window is awaiting Show.
        # Once shown, normalGeometry is real and must survive showNormal().
        return deepcopy(pending.pending)
    rectangle = widget.normalGeometry() if widget.isMaximized() or widget.isFullScreen() else widget.geometry()
    if not rectangle.isValid():
        rectangle = widget.geometry()
    return {'x': rectangle.x(), 'y': rectangle.y(), 'width': rectangle.width(),
            'height': rectangle.height(), 'maximized': bool(widget.isMaximized() or widget.isFullScreen())}


def apply_window_layout(widget, saved, *, minimum_size=None):
    if saved is None:
        return
    restorer = getattr(widget, '_optics_maximized_restore', None)
    if restorer is not None:
        restorer.cancel()
    screens = []
    for screen in QGuiApplication.screens():
        rect = screen.availableGeometry()
        screens.append(dict(x=rect.x(), y=rect.y(), width=rect.width(), height=rect.height()))
    if minimum_size is None:
        preferred = widget.property('preferred_minimum')
        if not isinstance(preferred, QSize):
            preferred = QSize(max(1, widget.minimumWidth()), max(1, widget.minimumHeight()))
    elif hasattr(minimum_size, 'width'):
        preferred = QSize(max(1, minimum_size.width()), max(1, minimum_size.height()))
    else:
        preferred = QSize(max(1, minimum_size[0]), max(1, minimum_size[1]))
    widget.setProperty('preferred_minimum', preferred)
    fitted = fit_window_rect(saved, screens, minimum=(preferred.width(), preferred.height()))
    widget.setWindowState(Qt.WindowState.WindowNoState)
    # setGeometry alone cannot shrink below QWidget.minimumSize. Keep the
    # nominal minimum separate, then relax it only for a smaller known screen.
    # Explicit per-axis minimums also stop a child layout's sizeHint expanding
    # the top-level window back outside that screen when it is first shown.
    effective = QSize(min(preferred.width(), fitted['width']), min(preferred.height(), fitted['height'])) if screens else preferred
    widget.setMinimumSize(effective)
    widget.setGeometry(fitted['x'], fitted['y'], fitted['width'], fitted['height'])
    if fitted['maximized']:
        if restorer is None:
            restorer = _MaximizedLayoutRestore(widget)
            widget._optics_maximized_restore = restorer
        restorer.stage(fitted)
