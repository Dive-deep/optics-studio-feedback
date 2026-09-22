"""Qt desktop host for local UI assets and narrow Python services."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import platform
import sys
import time
import uuid

import PySide6
from PySide6.QtCore import QByteArray, QBuffer, QEvent, QFile, QIODevice, QObject, QTimer, QUrl, qVersion
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler
from PySide6.QtWebEngineWidgets import QWebEngineView

from .bridge import BridgeError, DesktopBridge, encode, failure

ASSETS = Path(__file__).resolve().parent / "assets"
ALLOWED_SUFFIXES = {".html", ".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2", ".ttf", ".ico", ".wasm", ".map"}


class AssetHandler(QWebEngineUrlSchemeHandler):
    def requestStarted(self, job):
        url = job.requestUrl()
        if url.host() != "ui" or job.requestMethod() != b"GET":
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        path = url.path()
        if path == "/qwebchannel.js":
            resource = QFile(":/qtwebchannel/qwebchannel.js")
            if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            content, mime = resource.readAll(), "text/javascript"
            resource.close()
        else:
            candidate = (ASSETS / (path.lstrip("/") or "index.html")).resolve()
            if not candidate.is_relative_to(ASSETS) or candidate.suffix.lower() not in ALLOWED_SUFFIXES:
                job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
                return
            try:
                content = QByteArray(candidate.read_bytes())
            except OSError:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            mime = "text/javascript" if candidate.suffix == ".js" else mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        buffer = QBuffer(job)
        buffer.setData(content)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode("ascii"), buffer)


class LocalRequestPolicy(QWebEngineUrlRequestInterceptor):
    def __init__(self, stats, parent=None):
        super().__init__(parent)
        self.stats = stats

    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = (url.scheme() == "optics-app" and url.host() == "ui") or url.scheme() in {"data", "blob", "about"}
        if allowed and url.scheme() == "optics-app":
            # Resource paths only. Never log arbitrary request bodies, queries or fragments.
            self.stats["local_asset_requests"] += 1
        elif not allowed:
            self.stats["blocked_external_requests"] += 1
        if not allowed:
            info.block(True)


class LocalPage(QWebEnginePage):
    def __init__(self, profile, stats, parent=None, *, capture_error_locations=False):
        super().__init__(profile, parent)
        self.stats = stats
        self.capture_error_locations = capture_error_locations

    def acceptNavigationRequest(self, url, navigation_type, is_main):
        return url.scheme() == "optics-app" and url.host() == "ui"

    def javaScriptConsoleMessage(self, level, message, line, source):
        # JS errors can contain user-entered secrets; only retain event counts.
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.stats["javascript_errors"] += 1
            if self.capture_error_locations:
                url = QUrl(source)
                location = url.path() if url.scheme() == "optics-app" and url.host() == "ui" else None
                category = next((kind for kind in ("SyntaxError", "ReferenceError", "TypeError", "RangeError") if kind in message), "JavaScriptError")
                locations = self.stats.setdefault("javascript_error_locations", [])
                if len(locations) < 10:
                    locations.append({"path": location, "line": line, "category": category})


class DesktopView(QWebEngineView):
    desktop_bridge: DesktopBridge | None = None

    def event(self, event):
        if self.desktop_bridge is not None and event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop) and event.mimeData().hasUrls():
            local_urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
            if event.type() == QEvent.Type.DragEnter:
                if local_urls:
                    event.acceptProposedAction()
                    return True
            else:
                request_id = "drop-" + uuid.uuid4().hex
                if len(local_urls) == 1 and len(event.mimeData().urls()) == 1:
                    self.desktop_bridge.load_dropped_report(local_urls[0].toLocalFile(), request_id)
                else:
                    self.desktop_bridge.reject_dropped_report(request_id, BridgeError("DROP_COUNT", "Choose one local training report JSON."))
                event.acceptProposedAction()
                return True
        return super().event(event)


class NativeDialogs:
    def __init__(self, window):
        self.window = window
        self.directory = str(Path.home())

    def _open(self, title, pattern):
        path, _ = QFileDialog.getOpenFileName(self.window, title, self.directory, pattern)
        if path:
            self.directory = str(Path(path).parent)
        return path

    def _save(self, title, name, pattern):
        path, _ = QFileDialog.getSaveFileName(self.window, title, str(Path(self.directory) / name), pattern)
        if path:
            self.directory = str(Path(path).parent)
        return path

    def callbacks(self):
        return {
            "choose_report": lambda: self._open("Choose training report", "Training report JSON (*.json)"),
            "choose_target": lambda: self._open("Choose target profile", "Target profile JSON (*.json)"),
            "choose_session_open": lambda: self._open("Open optics session", "Optics session (*.optics.json *.json)"),
            "choose_session_save": lambda: self._save("Save optics session", "design.optics.json", "Optics session (*.optics.json)"),
            "export_bundle": lambda: self._save("Export optics bundle", "design.optics.zip", "Optics bundle (*.zip)"),
        }


def smoke_dialog_configuration(output_dir: Path, report_path: Path | None, target_path: Path | None):
    """Explicit test-only dialog replacement; absent paths never open an unattended dialog."""
    output = output_dir.resolve()
    report = str(report_path.resolve()) if report_path else None
    target = str(target_path.resolve()) if target_path else None
    enabled = report is not None or target is not None
    config = {"report_path": report, "target_path": target, "output_dir": str(output), "dialog_stubs": enabled}
    if not enabled:
        return None, config
    session = str(output / "ui-roundtrip.optics.json")
    callbacks = {
        "choose_report": lambda: report or "",
        "choose_target": lambda: target or "",
        "choose_session_open": lambda: session,
        "choose_session_save": lambda: session,
        "export_bundle": lambda: str(output / "ui-roundtrip.zip"),
    }
    return callbacks, config


class SmokeRunner(QObject):
    """Opt-in acceptance evidence. Production execution never invokes this code."""
    SCRIPT = r"""
    (async () => {
      const checks = [];
      checks.push({name:'internal_origin',pass:location.origin==='optics-app://ui'});
      checks.push({name:'workspace_document',pass:document.readyState==='complete'&&document.body.innerText.length>20});
      const normalize = value => value && value.ok === true && 'data' in value ? value.data : value;
      const local = normalize(await window.opticsBridge.request('compute_test',{target:'local'}));
      const server = normalize(await window.opticsBridge.request('compute_test',{target:'server'}));
      checks.push({name:'local_compute_response',pass:local?.target==='local'&&typeof local?.ready==='boolean',status:local?.status});
      checks.push({name:'server_compute_response',pass:server?.target==='server'&&server?.status==='not_configured',status:server?.status});
      let rejected=false;
      try {const value=await window.opticsBridge.request('run_zemax',{});rejected=value?.ok===false;}
      catch {rejected=true;}
      checks.push({name:'no_job_execution_method',pass:rejected});
      const frontend = typeof window.__OPTICS_SMOKE__ === 'function' ? await window.__OPTICS_SMOKE__() : null;
      window.__DESKTOP_SMOKE_RESULT__={checks,frontend,canvasCount:document.querySelectorAll('canvas').length};
    })().catch(()=>{window.__DESKTOP_SMOKE_RESULT__={checks:[{name:'frontend_smoke_completed',pass:false}],error:'Smoke could not complete.'};});
    """

    def __init__(self, app, window, page, bridge, stats, output_dir, smoke_config):
        super().__init__(app)
        self.app, self.window, self.page, self.bridge = app, window, page, bridge
        self.stats, self.output_dir = stats, output_dir
        self.smoke_config = smoke_config
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.begun = False
        self.done = False
        self.exit_code = 1
        self.evidence = {"python": sys.version, "platform": platform.platform(), "pyside": PySide6.__version__, "qt": qVersion(),
                         "pid": os.getpid(), "mode": "actual-desktop-app-host", "captures": [], "backend_jobs_executed": False,
                         "dialogs_stubbed": bool(smoke_config["dialog_stubs"]), "smoke_config": smoke_config}
        QTimer.singleShot(100, self.poll_ready)

    def poll_ready(self):
        if self.done:
            return
        if time.monotonic() - self.started > 45:
            self.evidence["timeout"] = True
            self.finish()
            return
        def ready(value):
            if value and not self.begun:
                self.begun = True
                self.page.runJavaScript("window.__OPTICS_SMOKE_CONFIG__=" + json.dumps(self.smoke_config) + ";\n" + self.SCRIPT)
                QTimer.singleShot(100, self.poll_result)
            elif not self.begun:
                QTimer.singleShot(100, self.poll_ready)
        self.page.runJavaScript("document.readyState==='complete' && !!window.opticsBridge && typeof window.opticsBridge.request==='function'", ready)

    def poll_result(self):
        if time.monotonic() - self.started > 45:
            self.evidence["timeout"] = True
            self.finish()
            return
        def result(raw):
            if raw:
                self.evidence["browser"] = json.loads(raw)
                self.capture(0)
            else:
                QTimer.singleShot(100, self.poll_result)
        self.page.runJavaScript("JSON.stringify(window.__DESKTOP_SMOKE_RESULT__ || null)", lambda raw: result(None if raw == 'null' else raw))

    def capture(self, index):
        sizes = [(1280, 720), (1920, 1080)]
        if index >= len(sizes):
            self.capture_compute_panel()
            return
        width, height = sizes[index]
        # A fixed Qt content size proves layout rendering, not OS usable desktop area.
        self.window.centralWidget().setFixedSize(width, height)
        self.window.adjustSize()
        def shot():
            view = self.window.centralWidget()
            name = f"app-{width}x{height}.png"
            saved = view.grab().save(str(self.output_dir / name))
            def snapshot(raw):
                self.evidence["captures"].append({"requested_content_size": [width, height], "actual_content_size": [view.width(), view.height()],
                                                 "kind": "fixed-size-layout-capture", "file": name, "saved": saved,
                                                 "viewport": json.loads(raw) if raw else None})
                self.capture(index + 1)
            self.page.runJavaScript("JSON.stringify({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scrollWidth:document.documentElement.scrollWidth})", snapshot)
        QTimer.singleShot(700, shot)

    def capture_compute_panel(self):
        def available(value):
            if not value:
                self.evidence["compute_panel_capture"] = {"status": "hook_unavailable", "saved": False}
                self.finish()
                return
            self.window.centralWidget().setFixedSize(1440, 900)
            self.window.adjustSize()
            self.page.runJavaScript("""
              (async()=>{
                try {const data=await window.__OPTICS_CAPTURE_COMPUTE__();window.__DESKTOP_COMPUTE_CAPTURE_READY__={ok:true,data:data??null};}
                catch {window.__DESKTOP_COMPUTE_CAPTURE_READY__={ok:false};}
              })();
            """)
            QTimer.singleShot(100, self.poll_compute_panel)
        self.page.runJavaScript("typeof window.__OPTICS_CAPTURE_COMPUTE__==='function'", available)

    def poll_compute_panel(self):
        if time.monotonic() - self.started > 45:
            self.evidence["compute_panel_capture"] = {"status": "timeout", "saved": False}
            self.finish()
            return
        def ready(raw):
            if not raw or raw == "null":
                QTimer.singleShot(100, self.poll_compute_panel)
                return
            state = json.loads(raw)
            if not state["ok"]:
                self.evidence["compute_panel_capture"] = {"status": "hook_failed", "saved": False}
                self.finish()
                return
            def shot():
                view = self.window.centralWidget()
                name = "app-compute-panel.png"
                saved = view.grab().save(str(self.output_dir / name))
                self.evidence["compute_panel_capture"] = {"status": "captured", "saved": saved, "file": name,
                                                          "content_size": [view.width(), view.height()],
                                                          "kind": "fixed-size-layout-capture", "frontend_status": state.get("data")}
                self.finish()
            QTimer.singleShot(500, shot)
        self.page.runJavaScript("JSON.stringify(window.__DESKTOP_COMPUTE_CAPTURE_READY__||null)", ready)

    def finish(self):
        if self.done:
            return
        self.done = True
        self.evidence["seconds"] = time.monotonic() - self.started
        self.evidence["resource_policy"] = dict(self.stats)
        self.evidence["completed_deferred_operations"] = self.bridge.completed_requests
        checks = self.evidence.get("browser", {}).get("checks", [])
        passed = bool(checks) and all(item.get("pass") is True for item in checks) and not self.evidence.get("timeout")
        frontend = self.evidence.get("browser", {}).get("frontend")
        extra_checks = frontend if isinstance(frontend, list) else frontend.get("checks", []) if isinstance(frontend, dict) else []
        passed = passed and all(item.get("pass") is True for item in extra_checks)
        passed = passed and self.stats["blocked_external_requests"] == 0 and self.stats["javascript_errors"] == 0
        compute_capture = self.evidence.get("compute_panel_capture", {})
        if compute_capture.get("status") != "hook_unavailable":
            passed = passed and compute_capture.get("saved", False)
        self.evidence["passed"] = passed
        self.exit_code = 0 if passed else 1
        (self.output_dir / "desktop-app.json").write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Desktop smoke:", "PASS" if passed else "FAIL", str(self.output_dir / "desktop-app.json"), flush=True)
        QTimer.singleShot(0, self.app.quit)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local imaging optics desktop UI")
    parser.add_argument("--smoke", action="store_true", help="Run local UI acceptance checks, capture evidence and exit")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/desktop-smoke"))
    parser.add_argument("--smoke-report", type=Path, help="Test-only report path replacing the native chooser; requires --smoke")
    parser.add_argument("--smoke-target", type=Path, help="Test-only target path replacing the native chooser; requires --smoke")
    options = parser.parse_args(argv)
    if (options.smoke_report is not None or options.smoke_target is not None) and not options.smoke:
        parser.error("--smoke-report and --smoke-target require --smoke")
    if sys.version_info[:2] != (3, 12):
        print("This application currently requires Python 3.12.", file=sys.stderr)
        return 2
    if not (ASSETS / "index.html").is_file():
        print("Local UI assets are missing. Build or restore optics_ui/assets first.", file=sys.stderr)
        return 2
    from .services.files import FileDataService
    from .services.compute import GpuReadinessService

    scheme = QWebEngineUrlScheme(b"optics-app")
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled | QWebEngineUrlScheme.Flag.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AI Imaging Optics")
    app.setOrganizationName("Optics UI Research")
    window = QMainWindow()
    window.setWindowTitle("AI Imaging Optics — Local Workspace")
    view = DesktopView(window)
    view.setAcceptDrops(True)
    window.setCentralWidget(view)
    stats = {"local_asset_requests": 0, "blocked_external_requests": 0, "javascript_errors": 0}
    profile = QWebEngineProfile(app)  # Off-the-record; sessions persist through FileDataService.
    assets = AssetHandler(profile)
    profile.installUrlSchemeHandler(b"optics-app", assets)
    policy = LocalRequestPolicy(stats, profile)
    profile.setUrlRequestInterceptor(policy)
    page = LocalPage(profile, stats, view, capture_error_locations=options.smoke)
    view.setPage(page)
    native = NativeDialogs(window)
    stub_callbacks, smoke_config = smoke_dialog_configuration(options.output_dir, options.smoke_report, options.smoke_target)
    bridge = DesktopBridge(FileDataService(), GpuReadinessService(), dialogs=stub_callbacks or native.callbacks(), parent=window)
    view.desktop_bridge = bridge
    channel = QWebChannel(page)
    channel.registerObject("desktop", bridge)
    page.setWebChannel(channel)
    window.resize(1440, 900)
    view.load(QUrl("optics-app://ui/index.html"))
    window.show()
    smoke = SmokeRunner(app, window, page, bridge, stats, options.output_dir.resolve(), smoke_config) if options.smoke else None
    exit_code = app.exec()
    bridge.shutdown()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    profile.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return smoke.exit_code if smoke else exit_code
