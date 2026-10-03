"""Exercise the real native v1 window and local renderer together.

Opt-in acceptance only. Saves isolated evidence under artifacts/, uses explicit
file-dialog stubs, never starts a backend job or modifies a source/model/DB file.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLineEdit, QTabWidget
from optics_ui import desktop
from optics_ui.services.sensitivity import context_hash, DEFAULT_OUTPUTS


def synthetic_report(context):
    """Declared test fixture for UI transport; these are NOT optical results."""
    context = deepcopy(context)
    # External Python analysis commonly emits 1.0 where the JS renderer emits
    # 1. Exercise that real cross-language session round trip, not only native
    # importer → native exporter where the representation would stay identical.
    for parameter in context['parameters']:
        for key in ('min', 'max', 'value'):
            if parameter.get(key) is not None:
                parameter[key] = float(parameter[key])
    parameters = [p for p in context['parameters'] if p['active'] and p['available']][:2]
    def cell(estimate):
        return {'estimate': estimate, 'ci_low': None, 'ci_high': None,
                'status': 'not_computed' if estimate is None else 'estimated_unvalidated'}
    return {
        'format': 'optics-sobol-report', 'schema_version': 1,
        'study': {'id': 'native-acceptance-fixture', 'context_hash': context_hash(context)},
        'context': context,
        'origin': {'kind': 'synthetic_fixture', 'source': 'Native UI acceptance ONLY; no optical evaluation'},
        'evaluator': {'kind': 'analytic_test', 'id': 'UI-fixture', 'version': '1'},
        'conditions': deepcopy(context['conditions']),
        'distribution': {'dependence': 'independent', 'marginals': [
            {'input_id': p['id'], 'kind': 'uniform', 'bounds': [p['min'], p['max']]} for p in parameters]},
        'sampling': {'method': 'saltelli_cross_design', 'estimator': 'test-fixture', 'implementation': 'test-fixture-1',
                     'base_sample_count': 8, 'evaluation_count': 8 * (len(parameters) + 2), 'seed': 3,
                     'scramble': True, 'second_order': False, 'design_hash': 'a' * 64,
                     'confidence_level': None, 'ci_method': None},
        'inputs': [{'id': p['id'], 'label': p['group'] + ' · ' + p['label'], 'unit': p['unit']} for p in parameters],
        'outputs': [{**deepcopy(DEFAULT_OUTPUTS[0]), 'variance': .1,
                     'conditions': {'field_norm': 0, 'orientation': 'S', 'frequency_lp_per_mm': 6}}],
        'first_order': [[cell(.2), cell(None)]], 'total_order': [[cell(.8), cell(.7)]],
    }


class NativeAcceptance:
    def __init__(self, runner):
        self.runner = runner
        self.window = runner.window
        self.controller = self.window.controller
        self.checks = []
        self.steps = self.scenarios()

    def check(self, name, condition):
        self.checks.append({'name': name, 'pass': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def start(self):
        self.advance()

    def advance(self, response=None):
        try:
            action, payload = self.steps.send(response)
            if action == '__wait__':
                QTimer.singleShot(payload, lambda: self.advance(None))
            else:
                self.controller.command(action, payload, lambda ok, data: QTimer.singleShot(0, lambda: self.advance((ok, data))))
        except StopIteration:
            self.runner.native_finished(self.checks)
        except Exception as error:
            self.checks.append({'name': 'native_acceptance_completed', 'pass': False, 'message': str(error)})
            self.runner.native_finished(self.checks)

    def scenarios(self):
        w = self.window
        ok, baseline = yield 'get_state', {}
        self.check('real_workbench_api_ready', ok and bool(baseline.get('parameter_payload')))
        self.check('only_explorer_has_code_tabs', w.findChildren(QTabWidget) == [w.explorer.tabs])
        self.check('code_tabs_have_close_buttons', w.explorer.tabs.tabsClosable())

        w.navigate('explorer')
        self.check('real_python_file_opened', w.explorer.open_file(ROOT / 'optics_ui/desktop.py'))
        self.check('real_second_file_opened', w.explorer.open_file(ROOT / 'optics_ui/services/files.py'))
        self.check('two_code_tabs_only', w.explorer.tabs.count() == 2)
        w.explorer.tabs.tabCloseRequested.emit(0)
        self.check('code_tab_can_be_closed', w.explorer.tabs.count() == 1)
        w.llm_action.trigger()
        w.llm_editor.setPlainText('현재 목표와 설계 제약을 검토해 줘. (native UI acceptance draft)')
        yield '__wait__', 250
        self.check('llm_is_independent_right_dock', w.llm_dock.isVisible())
        self.check('explorer_stays_open_beside_llm', w.current_page == 'explorer' and w.explorer.tabs.count() == 1)
        w.grab().save(str(self.runner.output_dir / 'native-explorer-llm.png'))
        w.navigate('tailoring')
        yield '__wait__', 100
        self.check('tailoring_does_not_create_code_tab', w.current_page == 'tailoring' and w.explorer.tabs.count() == 1)
        self.check('tailoring_keeps_llm_visible', w.llm_dock.isVisible())
        w.grab().save(str(self.runner.output_dir / 'native-db-tailoring.png'))
        w.llm_action.trigger()

        w.navigate('workspace')
        ok, original = yield 'get_state', {}
        self.check('workspace_returns_to_same_optics', ok and original['parameter_payload'] == baseline['parameter_payload'])
        w.open_parameters()
        yield '__wait__', 180
        dialog = w.parameter_dialog
        self.check('native_large_parameter_dialog_opens', dialog is not None and dialog.isVisible() and dialog.width() >= 800)
        original_parameters = deepcopy(original['parameter_payload'])
        row = next(p for p in original_parameters['parameters'] if p['active'] and p['available'] and p['value'] > p['min'])
        maximum = (row['value'] + row['min']) / 2
        edit = dialog.findChild(QLineEdit, 'parameter-max-' + row['id'])
        edit.setText(format(maximum, '.17g'))
        edit.editingFinished.emit()
        dialog.reject()
        ok, cancelled = yield 'get_state', {}
        self.check('native_cancel_preserves_entire_optical_draft', ok and cancelled['parameter_payload'] == original_parameters)

        w.open_parameters()
        yield '__wait__', 150
        dialog = w.parameter_dialog
        self.check('parameter_dialog_all_rows_available', dialog.table.rowCount() == len(original_parameters['parameters']))
        dialog.grab().save(str(self.runner.output_dir / 'native-parameters.png'))
        edit = dialog.findChild(QLineEdit, 'parameter-max-' + row['id'])
        edit.setText(format(maximum, '.17g'))
        edit.editingFinished.emit()
        dialog.apply_button.click()
        yield '__wait__', 120
        ok, applied = yield 'get_state', {}
        edited = next(p for p in applied['parameter_payload']['parameters'] if p['id'] == row['id'])
        self.check('native_apply_clamps_edited_current', ok and edited['max'] == maximum and edited['value'] == maximum)
        other_original = [p for p in original_parameters['parameters'] if p['id'] != row['id']]
        self.check('native_apply_does_not_change_other_parameters', [p for p in applied['parameter_payload']['parameters'] if p['id'] != row['id']] == other_original)
        ok, error = yield 'apply_parameters', original_parameters
        self.check('stale_parameter_revision_rejected', not ok)
        restore = deepcopy(original_parameters)
        restore['revision'] = applied['parameter_payload']['revision']
        ok, _ = yield 'apply_parameters', restore
        self.check('original_parameter_values_restored', ok)

        # No fabricated indices appear in a fresh Workspace.
        w.analysis_action.setChecked(True)
        yield '__wait__', 100
        self.check('sensitivity_and_sobol_inside_workspace', w.sensitivity.isVisible())
        self.check('no_evaluator_does_not_fabricate_indices', w.sensitivity.snapshot()['report'] is None and
                   all(value is None for value in w.sensitivity.chart.values))
        w.grab().save(str(self.runner.output_dir / 'native-sensitivity.png'))
        report_path = self.runner.output_dir / 'synthetic-sobol-ui-fixture.json'
        report_path.write_text(json.dumps(synthetic_report(w.sensitivity.request_preview()['context']), ensure_ascii=False), encoding='utf-8')
        self.check('real_sobol_report_import', w.sensitivity.load_report(report_path))
        self.check('imported_report_context_matches', w.sensitivity.snapshot()['stale'] is False)
        self.check('sobol_null_does_not_become_zero', w.sensitivity.chart.values == [.2, None])
        w.sensitivity.index_combo.setCurrentIndex(1)
        self.check('sobol_total_order_not_normalized', w.sensitivity.chart.values == [.8, .7])
        ok, current = yield 'get_state', {}
        changed = deepcopy(current['parameter_payload'])
        changed_row = next(p for p in changed['parameters'] if p['id'] == row['id'])
        changed_row['value'] = maximum
        ok, _ = yield 'apply_parameters', changed
        yield '__wait__', 60
        self.check('optical_edit_marks_sobol_report_stale', ok and w.sensitivity.snapshot()['stale'] is True)
        ok, current = yield 'get_state', {}
        restore = deepcopy(original_parameters)
        restore['revision'] = current['parameter_payload']['revision']
        ok, _ = yield 'apply_parameters', restore
        yield '__wait__', 60
        self.check('restoring_optics_restores_report_context_match', ok and not w.sensitivity.snapshot()['stale'])
        w.grab().save(str(self.runner.output_dir / 'native-sensitivity-imported-fixture.png'))
        saved_shell = w.collect_state()
        self.check('native_session_has_code_paths_not_contents', saved_shell['explorer']['files'] == ['optics_ui/services/files.py'])
        ok, _ = yield 'set_shell_state', saved_shell
        self.check('native_shell_state_validated_by_renderer', ok)
        draft = w.llm_editor.toPlainText()
        ok, _ = yield 'set_llm_draft', {'draft': draft}
        ok, _ = yield 'save', {}
        self.check('real_file_session_save', ok)
        session_path = self.runner.output_dir / 'ui-roundtrip.optics.json'
        session = json.loads(session_path.read_text(encoding='utf-8'))
        self.check('session_file_contains_v2_shell', session['state']['workbench']['version'] == 2)
        w.explorer.close_current_tab()
        w.llm_editor.setPlainText('UNSAVED draft that Open must replace')
        w.navigate('tailoring')
        ok, _ = yield 'open', {}
        yield '__wait__', 150
        self.check('native_session_reopens_successfully', ok)
        self.check('session_restores_code_tabs', w.explorer.snapshot()['files'] == saved_shell['explorer']['files'])
        self.check('session_restores_native_page', w.current_page == 'workspace')
        self.check('session_restores_analysis_visibility', w.analysis_action.isChecked())
        self.check('session_restores_llm_draft', w.llm_editor.toPlainText() == draft)
        self.check('session_restores_embedded_sobol_report', w.sensitivity.chart.values == [.8, .7] and not w.sensitivity.snapshot()['stale'])
        w.analysis_action.setChecked(False)


class WorkbenchRunner(desktop.SmokeRunner):
    def capture(self, index):
        if index == 0 and not getattr(self, 'native_done', False):
            self.native = NativeAcceptance(self)
            self.native.start()
            return
        super().capture(index)

    def native_finished(self, checks):
        self.native_done = True
        self.evidence['native_workbench'] = {'checks': checks}
        self.evidence['browser']['checks'].extend(checks)
        if all(check['pass'] for check in checks):
            super().capture(0)
        else:
            self.finish()


def main():
    desktop.SmokeRunner = WorkbenchRunner
    return desktop.main([
        '--smoke', '--output-dir', str(ROOT / 'artifacts/workbench-smoke'),
        '--smoke-report', str(ROOT / 'examples/local-demo/training-report.json'),
        '--smoke-target', str(ROOT / 'examples/local-demo/target.json'),
    ])


if __name__ == '__main__':
    raise SystemExit(main())
