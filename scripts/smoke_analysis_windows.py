"""Opt-in actual Qt/D3 chart-window acceptance; never default test discovery.

Uses QtTest chart pointer/key/wheel events, actual main UI DOM button clicks,
real file services and explicit test path dialog stubs. Unsaved-close decisions
are injected and recorded as stubs. JS observes DOM/state, invokes actual
controls, scrolls a control into view, or installs passive input listeners.
No optical state, results, zoom transforms, or application data are
assigned by the test. No backend job or external request is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import PySide6
from PySide6.QtCore import QEventLoop, QObject, QPoint, QPointF, Qt, QTimer, qVersion
from PySide6.QtTest import QTest
from PySide6.QtGui import QGuiApplication
from optics_ui import desktop
from optics_ui.workbench.layout import fit_window_rect


class AnalysisWindowsRunner(QObject):
    def __init__(self, app, window, page, bridge, stats, output_dir, smoke_config):
        super().__init__(app)
        self.app, self.window, self.page, self.bridge = app, window, page, bridge
        self.stats, self.output, self.config = stats, output_dir, smoke_config
        self.output.mkdir(parents=True, exist_ok=True)
        self.started, self.exit_code, self.done = time.monotonic(), 1, False
        self.checks, self.actions = [], []
        self.evidence = {"mode": "actual-native-analysis-windows", "python": sys.version,
                         "platform": platform.platform(), "pyside": PySide6.__version__, "qt": qVersion(),
                         "qpa_platform": app.platformName(),
                         "pid": os.getpid(), "dialogs_stubbed": bool(smoke_config["dialog_stubs"]),
                         "unsaved_confirmation_stubbed": True, "backend_jobs_executed": False,
                         "js_application_state_assigned": False, "checks": self.checks,
                         "actions": self.actions, "captures": []}
        QTimer.singleShot(120, self.run)

    def evaluate(self, expression, page=None):
        loop, values = QEventLoop(), []
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(4000)
        def received(raw):
            values.append(raw)
            loop.quit()
        (page or self.page).runJavaScript("JSON.stringify(" + expression + ")", received)
        loop.exec()
        timer.stop()
        if not values or values[0] is None:
            raise RuntimeError("DOM observation timed out")
        return json.loads(values[0])

    def wait(self, predicate, description, timeout=15):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if predicate():
                return
            loop = QEventLoop()
            QTimer.singleShot(35, loop.quit)
            loop.exec()
        raise TimeoutError(description)

    def command(self, action, payload=None):
        loop, replies = QEventLoop(), []
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(15000)
        def received(ok, value):
            replies.append((ok, value))
            loop.quit()
        self.window.controller.command(action, payload or {}, received)
        if not replies:
            loop.exec()
        timer.stop()
        if not replies or not replies[0][0]:
            raise RuntimeError("Native UI command failed: " + action)
        return replies[0][1]

    def check(self, name, passed, details=None):
        self.checks.append({"name": name, "pass": bool(passed), "details": details or {}})
        if not passed:
            raise AssertionError(name)

    def dom(self, view, page, selector, *, scroll=False):
        script = """(() => {const el=document.querySelector(%s);if(!el)return null;
          %s
          const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,
          viewport:{width:innerWidth,height:innerHeight},text:el.textContent};})()""" % (
            json.dumps(selector), "el.scrollIntoView({block:'center'});" if scroll else "")
        result = self.evaluate(script, page)
        if not result or result["width"] <= 0 or result["height"] <= 0:
            raise RuntimeError("Control is not visible: " + selector)
        return result

    def coordinate(self, view, rect, *, dx=0, dy=0):
        x, y = rect["x"] + rect["width"] / 2 + dx, rect["y"] + rect["height"] / 2 + dy
        point = QPoint(round(x * view.width() / rect["viewport"]["width"]),
                       round(y * view.height() / rect["viewport"]["height"]))
        target = view.focusProxy() or view
        return target, target.mapFromGlobal(view.mapToGlobal(point)), point

    def click(self, view, page, selector, action):
        if page is self.page:
            self.dom(view, page, selector, scroll=True)
            self.evaluate("(() => {document.querySelector(" + json.dumps(selector) + ").click();return true;})()", page)
            self.actions.append({"action": action, "input": "DOM click on actual main UI control",
                                 "selector": selector})
            QTest.qWait(150)
            return
        owner = view.window()
        owner.raise_()
        owner.activateWindow()
        self.dom(view, page, selector, scroll=True)
        QTest.qWait(80)
        rect = self.dom(view, page, selector)
        target, local, point = self.coordinate(view, rect)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, local, 20)
        self.actions.append({"action": action, "input": "QtTest mouseClick", "selector": selector,
                             "qt_logical": [point.x(), point.y()], "dpr": view.devicePixelRatioF()})
        QTest.qWait(120)

    def chart_state(self, chart):
        return self.evaluate("window.opticsChartWindow?.getState()||null", chart.page)

    def chart_ready(self, kind):
        chart = self.window.chart_manager.window(kind)
        return bool(chart and chart.isVisible() and (self.chart_state(chart) or {}).get("rendered"))

    def capture(self, widget, name):
        saved = widget.grab().save(str(self.output / name))
        self.evidence["captures"].append({"file": name, "saved": saved,
                                           "size": [widget.width(), widget.height()],
                                           "kind": "native-widget-capture"})

    def instrument(self, chart):
        self.evaluate("""(() => {window.__ANALYSIS_QA_EVENTS__=[];
          for(const type of ['pointerdown','pointermove','pointerup','wheel','click'])
          document.addEventListener(type,e=>{if(window.__ANALYSIS_QA_EVENTS__.length<100)
          window.__ANALYSIS_QA_EVENTS__.push({type:e.type,trusted:e.isTrusted});},true);return true;})()""", chart.page)

    def hover(self, chart):
        chart.raise_()
        chart.activateWindow()
        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        rect = self.dom(chart.view, chart.page, "[data-chart-hit]")
        target, local, view_point = self.coordinate(chart.view, rect)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        window_point = chart.mapFromGlobal(chart.view.mapToGlobal(view_point))
        QTest.mouseMove(chart.windowHandle(), window_point + QPoint(-18, -10), 30)
        QTest.qWait(60)
        QTest.mouseMove(chart.windowHandle(), window_point, 30)
        QTest.qWait(100)
        self.actions.append({"action": chart.kind + "_hover", "input": "QtTest QWindow mouseMove",
                             "qt_window_logical": [window_point.x(), window_point.y()]})
        return self.evaluate("(() => {const t=document.querySelector('[data-chart-tooltip]');return {text:t?.textContent,visible:!!t&&getComputedStyle(t).display!=='none'};})()", chart.page)

    def wheel_and_pan(self, chart):
        rect = self.dom(chart.view, chart.page, "[data-chart-hit]")
        target, start, view_point = self.coordinate(chart.view, rect)
        chart.raise_()
        chart.activateWindow()
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        window_point = chart.mapFromGlobal(chart.view.mapToGlobal(view_point))
        before = self.chart_state(chart)["view"]
        QTest.wheelEvent(chart.windowHandle(), QPointF(window_point), QPoint(0, 120))
        QTest.qWait(250)
        wheel = self.chart_state(chart)["view"]
        self.check("spot_wheel_zooms", wheel["k"] > before["k"], {"before": before, "after": wheel})
        QTest.mouseMove(target, start, 20)
        QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start, 20)
        for step in range(1, 7):
            QTest.mouseMove(target, start + QPoint(step * 5, -step * 2), 15)
            QTest.qWait(20)
        end = start + QPoint(30, -12)
        QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end, 20)
        QTest.qWait(180)
        pan = self.chart_state(chart)["view"]
        self.check("spot_pointer_drag_pans", abs(pan["x"] - wheel["x"]) > 1 and abs(pan["y"] - wheel["y"]) > 1,
                   {"before": wheel, "after": pan})
        self.actions.append({"action": "spot_zoom_pan", "input": "QtTest QWindow wheel + QWidget pointer drag"})

    def run(self):
        try:
            w = self.window
            self.wait(lambda: w._ready and not w._initializing, "Native workbench did not initialize")
            self.check("explicit_file_dialog_stubs", self.config["dialog_stubs"])
            w.model_action.trigger()
            self.wait(lambda: self.evaluate("!!document.getElementById('o-report-browse')"), "Report button absent")
            self.click(w.renderer, self.page, "#o-report-browse", "browse_report_with_test_path")
            self.wait(lambda: "training-report.json" in w.model_label.text(), "Report/DB did not connect")
            w.targets_action.trigger()
            self.wait(lambda: self.evaluate("!!document.getElementById('o-target-browse')"), "Target button absent")
            self.click(w.renderer, self.page, "#o-target-browse", "browse_target_with_test_path")
            self.wait(lambda: bool(self.command("get_session_snapshot")["references"].get("target_path")), "Target did not connect")
            envelope = self.command("get_session_snapshot")
            database = Path(envelope["references"]["database_path"])
            database_hash = hashlib.sha256(database.read_bytes()).hexdigest()
            w.navigate("workspace")
            self.wait(lambda: self.command("get_state").get("view") == "workspace", "Workspace did not open")
            for kind in ("mtf", "spot"):
                self.click(w.renderer, self.page, '[data-action="' + kind + '"]', "workspace_" + kind + "_pop_up")
                self.wait(lambda k=kind: self.chart_ready(k), kind + " chart did not render")
            mtf, spot = (w.chart_manager.window(kind) for kind in ("mtf", "spot"))
            self.check("two_nonmodal_windows_keep_workspace", mtf.isVisible() and spot.isVisible() and
                       not mtf.isModal() and not spot.isModal() and w.isVisible() and w.current_page == "workspace"
                       and self.command("get_state")["view"] == "workspace"
                       and self.evaluate("(() => {const e=document.querySelector('.o-workspace');return !!e&&!e.hidden&&e.getClientRects().length>0;})()"))
            states = {"mtf": self.chart_state(mtf), "spot": self.chart_state(spot)}
            self.check("stored_reference_points_render", states["mtf"]["point_count"] == 48 and states["spot"]["point_count"] == 64
                       and states["mtf"]["reference_id"] == "D057_2" and states["spot"]["reference_id"] == "D057_2", states)
            for chart in (mtf, spot):
                self.check(chart.kind + "_private_channel_only", set(chart.channel.registeredObjects()) == {"chart"}
                           and self.evaluate("typeof window.opticsBridge==='undefined'&&typeof window.opticsWorkbench==='undefined'", chart.page))
                data = json.loads(chart.bridge.chartData())
                self.check(chart.kind + "_stored_source_and_units", "합성" in data["source_label"] and
                           data["units"] == ({"x": "lp/mm", "y": "fraction"} if chart.kind == "mtf" else {"x": "µm", "y": "µm"}),
                           {"source_label": data["source_label"], "conditions_label": data["conditions_label"], "units": data["units"]})
                self.instrument(chart)
            self.click(mtf.view, mtf.page, "#chart-zoom-in", "mtf_zoom_in")
            self.check("mtf_button_zooms", self.chart_state(mtf)["view"]["k"] > 1)
            self.wheel_and_pan(spot)
            for chart, unit in ((mtf, "lp/mm"), (spot, "µm")):
                hover = self.hover(chart)
                self.check(chart.kind + "_hover_values_and_units", hover["visible"] and unit in hover["text"], hover)
                events = self.evaluate("window.__ANALYSIS_QA_EVENTS__", chart.page)
                self.check(chart.kind + "_trusted_pointer_events", any(event["trusted"] and event["type"] == "pointermove" for event in events))
                if chart is spot:
                    self.check("spot_trusted_wheel_event", any(event["trusted"] and event["type"] == "wheel" for event in events))
                self.capture(chart, chart.kind + "-window.png")
            saved_zoom = {chart.kind: self.chart_state(chart)["view"] for chart in (mtf, spot)}
            self.wait(lambda: self.command("get_session_snapshot")["snapshot"].get("chart_views") == saved_zoom,
                      "Chart gestures did not reach authoritative session state")
            mtf.close()
            self.check("close_mtf_keeps_spot_and_workspace", not mtf.isVisible() and spot.isVisible() and w.isVisible())
            self.click(w.renderer, self.page, '[data-action="mtf"]', "reopen_mtf")
            self.wait(lambda: mtf.isVisible(), "MTF did not reopen")
            self.check("mtf_window_is_reused", w.chart_manager.window("mtf") is mtf)
            QTest.keyClick(spot, Qt.Key.Key_Escape)
            self.check("escape_spot_keeps_mtf_and_workspace", not spot.isVisible() and mtf.isVisible() and w.isVisible())
            self.click(w.renderer, self.page, '[data-action="spot"]', "reopen_spot")
            self.wait(lambda: spot.isVisible(), "Spot did not reopen")
            self.check("spot_window_is_reused", w.chart_manager.window("spot") is spot)
            w.llm_action.setChecked(True)
            w.resizeDocks([w.llm_dock], [330], Qt.Orientation.Horizontal)
            w.navigate("explorer")
            QTest.qWait(120)
            w.explorer.splitter.setSizes([270, 610])
            w.navigate("workspace")
            w.llm_editor.setPlainText("Analysis windows acceptance draft — no provider call")
            mtf.move(mtf.x() + 12, mtf.y() + 8)
            mtf.showMaximized()
            self.actions.append({"action": "maximize_mtf", "input": "native QWidget.showMaximized"})
            QTest.qWait(200)
            self.capture(w, "workspace-with-llm.png")
            before_save = w.collect_state()
            w.save_session()
            self.wait(lambda: not w._saving, "Native save did not finish")
            session_file = self.output / "ui-roundtrip.optics.json"
            self.check("native_save_created_session", session_file.is_file())
            session = json.loads(session_file.read_text(encoding="utf-8"))
            saved_native = session["state"]["workbench"]
            layout = saved_native["layout"]
            self.check("session_v2_contains_all_native_layouts", saved_native["version"] == 2 and
                       set(layout) == {"window", "llm_width", "explorer_split", "charts"} and
                       all(layout["charts"][kind]["open"] and "maximized" in layout["charts"][kind]["window"] for kind in ("mtf", "spot")), layout)
            self.check("session_keeps_chart_zoom", session["state"]["chart_views"] == saved_zoom)
            self.check("session_records_maximized_chart", layout["charts"]["mtf"]["window"]["maximized"])
            w.chart_manager.close_all()
            w.llm_action.setChecked(False)
            w.llm_editor.setPlainText("UNSAVED text replaced by explicit Open")
            w.explorer.splitter.setSizes([410, 470])
            w.open_session()
            self.wait(lambda: not w._opening and not w._layout_restore_pending, "Native session restore did not finish", timeout=25)
            self.wait(lambda: self.chart_ready("mtf") and self.chart_ready("spot"), "Restored chart pages did not render")
            self.check("session_reopens_both_charts_and_llm", w.chart_manager.window("mtf").isVisible() and
                       w.chart_manager.window("spot").isVisible() and w.llm_dock.isVisible())
            self.check("session_restores_zoom", all(self.chart_state(w.chart_manager.window(kind))["view"] == saved_zoom[kind] for kind in ("mtf", "spot")))
            restored_layout = w.collect_state()["layout"]
            screens = []
            for screen in QGuiApplication.screens():
                rect = screen.availableGeometry()
                screens.append({"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()})
            expected_window = fit_window_rect(before_save["layout"]["window"], screens,
                                               minimum=(w.minimumWidth(), w.minimumHeight()))
            # Charts, like the main window, must fit the current work area.
            # A normal chart moved near the bottom before maximization can
            # legitimately restore a few pixels higher on a 720px CI desktop.
            expected_charts = {
                kind: {"open": saved["open"],
                       "window": fit_window_rect(saved["window"], screens, minimum=(420, 300))}
                for kind, saved in before_save["layout"]["charts"].items()
            }
            self.check("session_restores_native_geometry", restored_layout["window"] == expected_window and
                       restored_layout["charts"] == expected_charts and
                       restored_layout["llm_width"] == before_save["layout"]["llm_width"] and
                       restored_layout["explorer_split"][0] == before_save["layout"]["explorer_split"][0],
                       {"before": before_save["layout"], "expected_main_window": expected_window,
                        "expected_chart_windows": expected_charts, "after": restored_layout,
                        "explorer_right_pane": "automatic remaining width, not a persisted fixed width"})
            self.check("session_restores_maximized_chart", w.chart_manager.window("mtf").isMaximized())
            restored_mtf = w.chart_manager.window("mtf")
            restored_mtf.showNormal()
            QTest.qWait(120)
            self.check("restored_maximized_chart_returns_to_saved_normal_size",
                       [restored_mtf.width(), restored_mtf.height()] ==
                       [expected_charts["mtf"]["window"]["width"], expected_charts["mtf"]["window"]["height"]])
            restored_mtf.showMaximized()
            QTest.qWait(120)
            current = self.command("get_session_snapshot")
            self.check("restored_native_baseline_is_clean", not w._saved_state.changed(current["session_fingerprint"], w.collect_state(), w.llm_editor.toPlainText()))
            decisions = []
            w._confirm_close = lambda **details: (decisions.append({"choice": "cancel", "can_save": details.get("can_save")}) or "cancel")
            w.llm_editor.setPlainText("Unsaved close-cancel acceptance draft")
            w.close()
            self.wait(lambda: bool(decisions) and not w._close_query, "Unsaved confirmation was not requested")
            self.check("unsaved_close_cancel_keeps_all_windows", w.isVisible() and not w._closed and
                       all(w.chart_manager.window(kind).isVisible() for kind in ("mtf", "spot")), {"decisions": decisions})
            before_quit = {"workspace": w.isVisible(), **{kind: w.chart_manager.window(kind).isVisible()
                                                         for kind in ("mtf", "spot")}}
            decisions_before_quit = len(decisions)
            self.app.quit()
            self.wait(lambda: len(decisions) > decisions_before_quit and not w._close_query,
                      "Application Quit did not request unsaved confirmation")
            after_quit = {"workspace": w.isVisible(), **{kind: w.chart_manager.window(kind).isVisible()
                                                        for kind in ("mtf", "spot")}}
            self.actions.append({"action": "application_quit_cancel", "input": "QApplication.quit; confirmation stub chooses cancel"})
            self.check("application_quit_cancel_keeps_all_windows", not w._closed and all(before_quit.values())
                       and all(after_quit.values()) and len(decisions) > decisions_before_quit,
                       {"before": before_quit, "after": after_quit, "new_decisions": decisions[decisions_before_quit:]})
            self.check("reference_database_unchanged", hashlib.sha256(database.read_bytes()).hexdigest() == database_hash)
            self.check("no_javascript_errors_or_external_requests", self.stats["javascript_errors"] == 0 and self.stats["blocked_external_requests"] == 0)
        except Exception as error:
            self.evidence["error"] = {"type": type(error).__name__, "message": str(error)}
            self.evidence["failure_context"] = {"native_status": self.window.statusBar().currentMessage(),
                                                "model_label": self.window.model_label.text(),
                                                "completed_operations": getattr(self.bridge, "completed_requests", None)}
            for kind in ("mtf", "spot"):
                chart = self.window.chart_manager.window(kind)
                if chart:
                    self.evidence["failure_context"][kind] = self.evaluate("({state:window.opticsChartWindow?.getState(),events:window.__ANALYSIS_QA_EVENTS__||[]})", chart.page)
        finally:
            self.finish()

    def finish(self):
        if self.done:
            return
        self.done = True
        try:
            self.capture(self.window, "workspace-final.png")
            self.evidence["seconds"] = time.monotonic() - self.started
            self.evidence["resource_policy"] = dict(self.stats)
            self.evidence["passed"] = bool(self.checks) and all(c["pass"] for c in self.checks) and "error" not in self.evidence
            self.exit_code = 0 if self.evidence["passed"] else 1
            (self.output / "results.json").write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Analysis-window acceptance:", "PASS" if self.exit_code == 0 else "FAIL", self.output / "results.json", flush=True)
        finally:
            self.window.close_for_shutdown()
            QTimer.singleShot(0, self.app.quit)


def main():
    parser = argparse.ArgumentParser(description="Opt-in actual analysis-window Qt acceptance")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/analysis-windows-smoke")
    parser.add_argument("--smoke-report", type=Path, default=ROOT / "examples/local-demo/training-report.json")
    parser.add_argument("--smoke-target", type=Path, default=ROOT / "examples/local-demo/target.json")
    args = parser.parse_args()
    desktop.SmokeRunner = AnalysisWindowsRunner
    return desktop.main(["--smoke", "--output-dir", str(args.output_dir.resolve()),
                         "--smoke-report", str(args.smoke_report.resolve()),
                         "--smoke-target", str(args.smoke_target.resolve())])


if __name__ == "__main__":
    raise SystemExit(main())
