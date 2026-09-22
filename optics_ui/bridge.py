"""Narrow desktop bridge. No generic filesystem, shell, model or job API."""
from __future__ import annotations

import json
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot

REFERENCE_KEYS = {"report_path", "database_path", "target_path"}
SENSITIVE_KEYS = {"apikey", "accesstoken", "refreshtoken", "authtoken", "authorization", "password", "secretkey", "credentials"}
METHODS = {"choose_report", "load_report", "choose_target", "choose_session_open", "choose_session_save",
           "export_bundle", "load_case", "list_cases", "candidate_data", "compute_test"}


class BridgeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def success(request_id: str | None, data: Any) -> dict:
    return {"id": request_id, "ok": True, "data": data}


def failure(request_id: str | None, error: Exception) -> dict:
    code, message = getattr(error, "code", None), getattr(error, "message", None)
    if not isinstance(code, str) or not isinstance(message, str):
        code, message = "INTERNAL_ERROR", "The desktop service could not complete the request."
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def encode(envelope: dict) -> str:
    try:
        return json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps(failure(envelope.get("id"), BridgeError("INVALID_RESPONSE", "The service returned an unsupported response.")))


def _contains_credentials(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("_", "").replace("-", "")
            if normalized in SENSITIVE_KEYS or _contains_credentials(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_credentials(item) for item in value)
    return False


class RequestRouter:
    """Pure routing contract, independent of Qt widgets and operating-system dialogs."""

    def __init__(self, files: Any, *, dialogs: dict[str, Callable[[], str]] | None = None,
                 defer_compute: Callable[[str, str], None] | None = None,
                 defer_files: Callable[[str, Callable[[], Any]], None] | None = None):
        self.files = files
        self.dialogs = dialogs or {}
        self.defer_compute = defer_compute
        self.defer_files = defer_files

    def dispatch(self, raw: str) -> dict:
        request_id = None
        try:
            if not isinstance(raw, str) or len(raw) > 2_000_000:
                raise BridgeError("INVALID_REQUEST", "Request must be a supported JSON envelope.")
            try:
                request = json.loads(raw)
            except (ValueError, RecursionError) as error:
                raise BridgeError("BAD_JSON", "Request is not valid JSON.") from error
            if not isinstance(request, dict):
                raise BridgeError("INVALID_REQUEST", "Request must be an object.")
            possible_id = request.get("id")
            if isinstance(possible_id, str) and 0 < len(possible_id) <= 128:
                request_id = possible_id
            if request_id is None or set(request) - {"id", "method", "params"}:
                raise BridgeError("INVALID_REQUEST", "A request ID and supported envelope fields are required.")
            method, params = request.get("method"), request.get("params", {})
            if not isinstance(method, str) or method not in METHODS:
                raise BridgeError("UNKNOWN_METHOD", "This desktop method is not available.")
            if not isinstance(params, dict):
                raise BridgeError("INVALID_PARAMS", "Parameters must be an object.")
            if _contains_credentials(params):
                raise BridgeError("CREDENTIALS_NOT_ALLOWED", "Credentials must not be sent to or stored by this desktop bridge.")
            self._validate_params(method, params)
            return success(request_id, self._invoke(request_id, method, params))
        except Exception as error:
            # Never log request bodies, service exceptions, credentials or filesystem contents.
            return failure(request_id, error)

    @staticmethod
    def _validate_params(method: str, params: dict) -> None:
        expected = {"load_report": {"path"}, "load_case": {"path", "case_id"}, "list_cases": {"path"}, "candidate_data": {"path"},
                    "compute_test": {"target"}, "choose_session_save": {"state", "references"},
                    "export_bundle": {"state", "references"}}.get(method, set())
        if set(params) != expected:
            raise BridgeError("INVALID_PARAMS", "Parameters do not match this desktop method.")
        for key in ("path", "case_id"):
            if key in params and (not isinstance(params[key], str) or not params[key].strip() or "\x00" in params[key]):
                raise BridgeError("INVALID_PARAMS", "A valid file path and case identifier are required.")
        if method == "compute_test" and params["target"] not in ("local", "server"):
            raise BridgeError("INVALID_PARAMS", "Compute target must be local or server.")
        if method in ("choose_session_save", "export_bundle"):
            refs = params["references"]
            if not isinstance(params["state"], dict) or not isinstance(refs, dict) or set(refs) - REFERENCE_KEYS:
                raise BridgeError("INVALID_PARAMS", "Session state and supported file references are required.")
            if any(value is not None and (not isinstance(value, str) or not value.strip() or "\x00" in value) for value in refs.values()):
                raise BridgeError("INVALID_PARAMS", "File references must be paths or null.")

    def _choose(self, method: str) -> str:
        callback = self.dialogs.get(method)
        if callback is None:
            raise BridgeError("SERVICE_UNAVAILABLE", "The native file dialog is unavailable.")
        return callback()

    def _invoke(self, request_id: str, method: str, params: dict) -> Any:
        if method == "compute_test":
            if self.defer_compute is None:
                raise BridgeError("SERVICE_UNAVAILABLE", "The compute readiness service is unavailable.")
            self.defer_compute(request_id, params["target"])
            return {"status": "started", "deferred": True, "request_id": request_id, "target": params["target"]}
        if method == "load_report":
            return self._file(request_id, "load_report", params["path"])
        if method == "load_case":
            return self._file(request_id, "load_case", params["path"], params["case_id"])
        if method == "list_cases":
            return self._file(request_id, "list_cases", params["path"])
        if method == "candidate_data":
            return self._file(request_id, "candidate_data", params["path"])
        path = self._choose(method)
        if not path:
            return {"status": "cancelled"}
        if method == "choose_report":
            return self._file(request_id, "load_report", path)
        if method == "choose_target":
            return self._file(request_id, "load_target", path)
        if method == "choose_session_open":
            return self._file(request_id, "load_session", path)
        if method == "choose_session_save":
            return self._file(request_id, "save_session", path, params["state"], params["references"])
        return self._file(request_id, "export_bundle", path, params["state"], params["references"])

    def _file(self, request_id: str, method: str, *args) -> Any:
        def operation():
            result = getattr(self.files, method)(*args)
            return {"cases": result} if method == "list_cases" else result
        if self.defer_files is not None:
            self.defer_files(request_id, operation)
            return {"status": "started", "deferred": True, "request_id": request_id}
        return operation()


class WorkerSignals(QObject):
    finished = Signal(str)


class ServiceWorker(QRunnable):
    def __init__(self, request_id: str, operation: Callable[[], Any]):
        super().__init__()
        self.request_id, self.operation = request_id, operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = success(self.request_id, self.operation())
        except Exception as error:
            result = failure(self.request_id, error)
        self.signals.finished.emit(encode(result))


class DesktopBridge(QObject):
    """Published as QWebChannel channel.objects.desktop."""
    responseReady = Signal(str)
    reportLoadStarted = Signal(str)
    reportLoaded = Signal(str)

    def __init__(self, files: Any, compute: Any, *, dialogs: dict[str, Callable[[], str]], parent=None):
        super().__init__(parent)
        self.files, self.compute = files, compute
        self.router = RequestRouter(files, dialogs=dialogs, defer_compute=self._defer_compute, defer_files=self._defer_files)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.pending: dict[str, ServiceWorker] = {}
        self.drop_requests: set[str] = set()
        self.completed_requests = 0

    @Slot(str, result=str)
    def dispatch(self, raw: str) -> str:
        if QThread.currentThread() != self.thread():
            return encode(failure(None, BridgeError("WRONG_THREAD", "Desktop requests must be dispatched on the UI thread.")))
        return encode(self.router.dispatch(raw))

    def _defer_compute(self, request_id: str, target: str) -> None:
        self._schedule(request_id, lambda: self.compute.test(target=target))

    def _defer_files(self, request_id: str, operation: Callable[[], Any]) -> None:
        self._schedule(request_id, operation)

    def _schedule(self, request_id: str, operation: Callable[[], Any]) -> None:
        if request_id in self.pending:
            raise BridgeError("DUPLICATE_REQUEST", "This request is already pending.")
        if len(self.pending) >= 8:
            raise BridgeError("BUSY", "Desktop file and readiness operations are busy. Please try again shortly.")
        worker = ServiceWorker(request_id, operation)
        worker.signals.finished.connect(self._complete_operation)
        self.pending[request_id] = worker
        self.pool.start(worker)

    @Slot(str)
    def _complete_operation(self, raw: str) -> None:
        request_id = json.loads(raw).get("id")
        self.pending.pop(request_id, None)
        self.completed_requests += 1
        self.responseReady.emit(raw)
        if request_id in self.drop_requests:
            self.drop_requests.remove(request_id)
            self.reportLoaded.emit(raw)

    def load_dropped_report(self, path: str, request_id: str) -> dict:
        self.reportLoadStarted.emit(json.dumps({"id": request_id, "path": path}, ensure_ascii=False))
        self.drop_requests.add(request_id)
        result = self.router.dispatch(json.dumps({"id": request_id, "method": "load_report", "params": {"path": path}}))
        if not result.get("data", {}).get("deferred"):
            self.drop_requests.discard(request_id)
            self.reportLoaded.emit(encode(result))
        return result

    def reject_dropped_report(self, request_id: str, error: BridgeError) -> None:
        self.reportLoadStarted.emit(json.dumps({"id": request_id}))
        self.reportLoaded.emit(encode(failure(request_id, error)))

    def shutdown(self) -> None:
        # The service owns its short timeout; never terminate another process or a GPU job.
        self.pool.waitForDone(6000)
