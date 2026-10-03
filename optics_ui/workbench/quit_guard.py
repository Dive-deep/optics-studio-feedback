"""Route OS/application Quit through the workspace's asynchronous close guard."""
import weakref

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class ApplicationQuitGuard(QObject):
    def __init__(self, application, window):
        super().__init__(application)
        self._window = weakref.ref(window)

    def eventFilter(self, watched, event):
        # Application filters also see events addressed to other QObjects.
        # WebEngine's internal event loops may quit during initialization; only
        # a Quit addressed to QApplication is an application-close request.
        if watched is not self.parent() or event.type() != QEvent.Type.Quit:
            return False
        window = self._window()
        if window is None or not isValid(window) or window._allow_close:
            return False
        # QApplication normally closes all top-level windows first. Asking the
        # workspace before that preserves both charts when the user cancels.
        window.close()
        return True


class WorkbenchApplication(QApplication):
    """Intercept only events sent to the application, not all GUI QObjects.

    A global Python application event filter also wraps transient WebEngine
    internals and can crash native initialization. Overriding this receiver's
    event method keeps those internal events entirely within Qt.
    """
    def bind_workspace(self, window):
        self._quit_guard = ApplicationQuitGuard(self, window)

    def event(self, event):
        if event.type() == QEvent.Type.Quit:
            guard = getattr(self, '_quit_guard', None)
            if guard is not None and guard.eventFilter(self, event):
                return True
        return super().event(event)
