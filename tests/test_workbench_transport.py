"""The native shell can route UI actions, never arbitrary backend methods."""
import json
import unittest
import gc
import weakref

from tests.qt_support import QT_APP
from optics_ui.workbench.transport import WorkbenchBridge, RendererController
from PySide6.QtCore import QCoreApplication, QEvent


class FakePage:
    def __init__(self):
        self.scripts = []

    def runJavaScript(self, script):
        self.scripts.append(script)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.page = FakePage()
        self.bridge = WorkbenchBridge()
        self.controller = RendererController(self.page, self.bridge)
        self.addCleanup(self.controller.shutdown)

    def notify(self, kind, payload=None):
        self.bridge.notify(json.dumps({'type': kind, 'payload': payload or {}}))

    def test_readiness_and_state_events_are_detached(self):
        events = []
        self.controller.stateChanged.connect(events.append)
        self.notify('ready')
        self.assertTrue(self.controller.ready)
        self.notify('state', {'view': 'workspace', 'llm_draft': 'hello'})
        self.assertEqual(self.controller.last_state['view'], 'workspace')
        events[-1]['view'] = 'modified'
        self.assertEqual(self.controller.last_state['view'], 'workspace')

    def test_only_explicit_ui_actions_are_routed(self):
        responses = []
        self.notify('ready')
        self.controller.command('run_python', {'code': 'anything'}, lambda *r: responses.append(r))
        self.assertFalse(responses[-1][0])
        self.assertEqual(self.page.scripts, [])

    def test_not_ready_does_not_drop_command_silently(self):
        responses = []
        self.controller.command('save', callback=lambda *r: responses.append(r))
        self.assertFalse(responses[-1][0])
        self.assertEqual(self.page.scripts, [])

    def test_command_completion_matches_id_once(self):
        responses = []
        self.notify('ready')
        request_id = self.controller.command('navigate', {'page': 'workspace'}, lambda *r: responses.append(r))
        self.assertIn('window.opticsWorkbench.command', self.page.scripts[-1])
        self.bridge.commandResult(json.dumps({'id': 'unknown', 'ok': True, 'data': None}))
        self.assertEqual(responses, [])
        result = {'id': request_id, 'ok': True, 'data': {'view': 'workspace'}}
        self.bridge.commandResult(json.dumps(result))
        self.bridge.commandResult(json.dumps(result))
        self.assertEqual(responses, [(True, {'view': 'workspace'})])

    def test_json_payload_cannot_become_executable_script(self):
        self.notify('ready')
        text = "');alert('unsafe'); // \u2028\n</script>"
        self.controller.command('set_llm_draft', {'draft': text})
        self.assertIn(json.dumps({'draft': text}, ensure_ascii=True), self.page.scripts[-1])

    def test_malformed_and_nonfinite_messages_are_ignored(self):
        states = []
        self.controller.stateChanged.connect(states.append)
        for raw in ('not-json', '[]', '{"type":"ready","payload":NaN}', '{"type":"unknown","payload":{}}'):
            self.bridge.notify(raw)
        self.assertEqual(states, [])
        self.assertFalse(self.controller.ready)

    def test_oversized_messages_rejected_and_shutdown_rejects_pending(self):
        self.bridge.notify('{"type":"ready","payload":{"data":"' + 'a' * (3 * 1024 * 1024) + '"}}')
        self.assertFalse(self.controller.ready)
        self.notify('ready')
        responses = []
        self.controller.command('save', callback=lambda *r: responses.append(r))
        self.controller.shutdown()
        self.assertFalse(responses[-1][0])
        self.assertFalse(self.controller.ready)

    def test_frontend_errors_and_native_requests(self):
        requested, toggles, sessions, responses = [], [], [], []
        self.controller.parametersRequested.connect(lambda: requested.append(True))
        self.controller.llmToggleRequested.connect(lambda: toggles.append(True))
        self.controller.sessionRestored.connect(sessions.append)
        self.notify('ready')
        self.notify('parameters_requested')
        self.notify('llm_toggle')
        self.notify('session_restored', {'workbench': None})
        request_id = self.controller.command('save', callback=lambda *r: responses.append(r))
        self.bridge.commandResult(json.dumps({'id': request_id, 'ok': False, 'error': {'message': 'Invalid range'}}))
        self.assertEqual(requested, [True])
        self.assertEqual(toggles, [True])
        self.assertEqual(sessions, [{'workbench': None}])
        self.assertEqual(responses, [(False, {'message': 'Invalid range'})])


    def test_timeout_settles_once_and_completed_controller_has_no_timer_cycle(self):
        bridge = WorkbenchBridge()
        controller = RendererController(FakePage(), bridge)
        controller.ready = True
        responses = []
        request_id = controller.command('get_state', callback=lambda *result: responses.append(result))
        timer = controller._pending[request_id][1]
        timer.timeout.emit()
        timer.timeout.emit()
        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0][0])
        self.assertIn('timed out', responses[0][1]['message'])
        reference = weakref.ref(controller)
        del controller
        gc.collect()
        self.assertIsNone(reference(), 'Timer callbacks must not retain their parent controller')
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
