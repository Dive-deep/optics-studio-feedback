"""Narrow native workbench ↔ local renderer UI transport.

No network, file access, shell evaluation, model loading or optical job execution
is exposed here. File workflows remain in the existing DesktopBridge service.
"""
from __future__ import annotations

from copy import deepcopy
import json
import uuid

from PySide6.QtCore import QObject, QTimer, Signal, Slot

MAX_MESSAGE_BYTES = 2 * 1024 * 1024
UI_ACTIONS = frozenset({
    'navigate', 'get_state', 'apply_parameters', 'set_shell_state',
    'set_llm_draft', 'model', 'open', 'save', 'export', 'targets',
    'candidates', 'configure', 'get_chart_data', 'set_chart_view', 'get_session_snapshot',
})
EVENT_TYPES = frozenset({'ready', 'state', 'parameters_requested', 'llm_toggle', 'session_restored', 'chart_requested', 'session_opened'})


def _decode(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_MESSAGE_BYTES:
        raise ValueError('Message is too large.')
    def reject(_):
        raise ValueError('Nonfinite JSON value.')
    value = json.loads(raw, parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object.')
    return value


class WorkbenchBridge(QObject):
    """WebChannel sink. Events are bounded; unknown messages are ignored."""
    eventReceived = Signal(dict)
    resultReceived = Signal(dict)

    @Slot(str)
    def notify(self, raw):
        try:
            message = _decode(raw)
            if message.get('type') not in EVENT_TYPES or not isinstance(message.get('payload'), dict):
                return
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return
        self.eventReceived.emit(message)

    @Slot(str)
    def commandResult(self, raw):
        try:
            message = _decode(raw)
            if not isinstance(message.get('id'), str) or type(message.get('ok')) is not bool:
                return
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return
        self.resultReceived.emit(message)


class RendererController(QObject):
    stateChanged = Signal(dict)
    sessionRestored = Signal(dict)
    sessionOpened = Signal(dict)
    chartRequested = Signal(dict)
    parametersRequested = Signal()
    llmToggleRequested = Signal()
    readyChanged = Signal(bool)
    statusMessage = Signal(str)

    def __init__(self, page, bridge, parent=None):
        super().__init__(parent)
        self.page = page
        self.bridge = bridge
        self.ready = False
        self.last_state = {}
        self._pending = {}
        bridge.eventReceived.connect(self._event)
        bridge.resultReceived.connect(self._result)

    @Slot(dict)
    def _event(self, event):
        kind, payload = event['type'], event['payload']
        if kind == 'ready':
            self.ready = True
            self.readyChanged.emit(True)
        elif kind == 'state':
            self.last_state = deepcopy(payload)
            self.stateChanged.emit(deepcopy(payload))
        elif kind == 'session_restored':
            self.sessionRestored.emit(deepcopy(payload))
        elif kind == 'session_opened':
            self.sessionOpened.emit(deepcopy(payload))
        elif kind == 'chart_requested':
            self.chartRequested.emit(deepcopy(payload))
        elif kind == 'parameters_requested':
            self.parametersRequested.emit()
        elif kind == 'llm_toggle':
            self.llmToggleRequested.emit()

    def command(self, action, payload=None, callback=None):
        """Run one allowlisted UI command and deliver its Promise result once."""
        if action not in UI_ACTIONS:
            self._fail(callback, 'Unsupported workbench action.')
            return None
        if not self.ready:
            self._fail(callback, '화면이 준비될 때까지 잠시 기다려 주세요.')
            return None
        try:
            arguments = json.dumps(payload if payload is not None else {}, ensure_ascii=True, allow_nan=False)
            if len(arguments) > MAX_MESSAGE_BYTES:
                raise ValueError('Payload too large.')
        except (TypeError, ValueError, RecursionError):
            self._fail(callback, 'UI settings could not be encoded safely.')
            return None
        request_id = uuid.uuid4().hex
        timer = QTimer(self)
        timer.setSingleShot(True)
        # File selection may keep a native dialog open for several minutes.
        timer.setProperty('request_id', request_id)
        # A QObject receiver slot avoids a child timer lambda retaining its
        # parent controller during deferred deletion.
        timer.timeout.connect(self._timeout)
        timer.start(310000 if action in {'open', 'save', 'export', 'model', 'targets'} else 20000)
        self._pending[request_id] = (callback, timer)
        # JSON is embedded as a JS expression, never interpolated into quoted code.
        script = """(() => {
          const id = %s;
          const settle = (ok, data) => window.opticsBridge?.workbench?.commandResult(
            JSON.stringify(ok ? {id, ok, data: data ?? null} : {id, ok, error: {message: String(data)}}));
          Promise.resolve().then(() => window.opticsWorkbench.command(%s, %s))
            .then(data => settle(true, data), error => settle(false, error?.message || 'UI request failed.'));
        })();""" % (json.dumps(request_id), json.dumps(action), arguments)
        self.page.runJavaScript(script)
        return request_id

    @Slot()
    def _timeout(self):
        timer = self.sender()
        if isinstance(timer, QTimer):
            request_id = timer.property('request_id')
            if isinstance(request_id, str):
                self._settle(request_id, False, {'message': 'UI request timed out.'})

    def _fail(self, callback, message):
        self.statusMessage.emit(message)
        if callback is not None:
            callback(False, {'message': message})

    @Slot(dict)
    def _result(self, envelope):
        result = envelope.get('data') if envelope['ok'] else envelope.get('error', {'message': 'UI request failed.'})
        self._settle(envelope['id'], envelope['ok'], result)

    def _settle(self, request_id, ok, result):
        item = self._pending.pop(request_id, None)
        if item is None:
            return
        callback, timer = item
        timer.stop()
        timer.deleteLater()
        if not ok:
            self.statusMessage.emit(str(result.get('message', 'UI request failed.')) if isinstance(result, dict) else 'UI request failed.')
        if callback is not None:
            callback(ok, result)

    def shutdown(self):
        self.unavailable('Workbench has closed.')

    def unavailable(self, message):
        """Fail outstanding UI requests after a renderer/process lifecycle error."""
        self.ready = False
        self.readyChanged.emit(False)
        for request_id in list(self._pending):
            self._settle(request_id, False, {'message': message})
        self.statusMessage.emit(message)
