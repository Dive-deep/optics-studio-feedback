"""Small CUDA driver diagnostic, independent of ML/Zemax/LLM backends.

The synchronous public service should be called from the desktop job worker.
Native CUDA calls run in a separate, time-limited Python process, never in Qt.
No context, tensor, kernel, training task, or remote connection is created.
"""

from __future__ import annotations

import ctypes
from ctypes.util import find_library
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Callable


_SCOPE = "cuda_driver_and_device_enumeration"
_PROBE_STATUSES = {"ready", "missing_driver", "no_device", "driver_error", "probe_error"}
_MESSAGES = {
    "missing_driver": "NVIDIA CUDA 드라이버를 찾거나 불러올 수 없습니다.",
    "no_device": "CUDA에서 사용할 수 있는 NVIDIA GPU가 감지되지 않았습니다.",
    "driver_error": "CUDA 드라이버 초기화 또는 GPU 정보 조회에 실패했습니다.",
    "probe_error": "GPU 검사 결과를 가져오지 못했습니다.",
    "invalid_target": "검사 대상은 local 또는 server로 선택해 주세요.",
    "not_configured": "서버 연결 정보가 없어 검사할 수 없습니다",
}


class GpuReadinessService:
    """Report driver/device readiness; ``ready`` is not a training guarantee.

    ``platform_name`` and ``probe`` are injection points for GPU-free tests.
    The injected probe accepts (platform_name, timeout_seconds).
    """

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        probe: Callable[[str, float], dict[str, Any]] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self._platform = platform_name if platform_name is not None else platform.system()
        self._probe = probe if probe is not None else _run_isolated_probe
        self._timeout = timeout_seconds

    def test(self, target: str = "local") -> dict[str, Any]:
        """Return a JSON-ready result. Expected diagnostic failures are data."""
        if target not in ("local", "server"):
            return self._result(str(target), "invalid_target")
        if target == "server":
            # TODO(server-diagnostic-adapter): connect only when an explicit
            # endpoint/transport contract exists. Do not guess hosts or auth.
            return self._result(target, "not_configured")
        if self._platform == "Darwin":
            return self._result(
                target,
                "unsupported",
                message="현재 Mac 환경은 CUDA 검사 대상이 아닙니다. Apple GPU/MPS는 CUDA와 다릅니다.",
            )
        if self._platform not in ("Windows", "Linux"):
            return self._result(target, "unsupported", message="이 운영체제에서는 CUDA 검사를 지원하지 않습니다.")
        try:
            raw = self._probe(self._platform, self._timeout)
            if not isinstance(raw, dict) or raw.get("status") not in _PROBE_STATUSES:
                return self._result(target, "probe_error", details={"reason": "invalid_probe_result"})
            status = raw["status"]
            details = raw.get("details", {})
            if not isinstance(details, dict):
                return self._result(target, "probe_error", details={"reason": "invalid_probe_details"})
            devices = raw.get("devices", [])
            if status == "ready":
                if not self._valid_devices(devices):
                    return self._result(target, "probe_error", details={"reason": "missing_device_evidence"})
                # Copy only the contract fields, not arbitrary probe metadata.
                devices = [{"index": d["index"], "name": d["name"]} for d in devices]
            else:
                devices = []
            return self._result(target, status, devices=devices, details=details)
        except subprocess.TimeoutExpired:
            return self._result(
                target,
                "timeout",
                message=f"GPU 검사 제한 시간({self._timeout:g}초)을 초과하여 검사를 종료했습니다.",
                details={"timeout_seconds": self._timeout},
            )
        except (OSError, ValueError, TypeError) as exc:
            return self._result(target, "probe_error", details={"error_type": type(exc).__name__})

    @staticmethod
    def _valid_devices(devices: Any) -> bool:
        return isinstance(devices, list) and bool(devices) and all(
            isinstance(d, dict)
            and type(d.get("index")) is int
            and d["index"] >= 0
            and isinstance(d.get("name"), str)
            and bool(d["name"].strip())
            for d in devices
        )

    def _result(self, target, status, *, message=None, devices=None, details=None):
        devices = devices or []
        checked_scope = {
            **(details or {}),
            "platform": self._platform,
            "scope": _SCOPE,
            "context_tested": False,
            "kernel_tested": False,
            "framework_tested": False,
            "training_tested": False,
            "remote_contacted": False,
        }
        if status == "ready":
            message = f"CUDA 드라이버 초기화와 GPU {len(devices)}개 인식을 확인했습니다. 학습 환경은 별도 확인이 필요합니다."
        elif message is None:
            message = _MESSAGES[status]
            if status == "driver_error" and "cuda_code" in checked_scope:
                message += f" ({checked_scope.get('stage', 'CUDA')}, 오류 코드 {checked_scope['cuda_code']})"
        return {
            "target": target,
            "status": status,
            "ready": status == "ready",
            "message": message,
            "devices": devices,
            "details": checked_scope,
        }


def _run_isolated_probe(platform_name: str, timeout_seconds: float) -> dict[str, Any]:
    if getattr(sys, "frozen", False):
        # A frozen GUI executable is not a Python interpreter. A packaged probe
        # entry point must be added during packaging, not recursively launch UI.
        return {"status": "probe_error", "details": {"reason": "packaged_probe_not_configured"}}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe", platform_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        shell=False,
        **options,
    )
    # subprocess.run kills and waits for its child when the timeout expires.
    if process.returncode != 0:
        return {"status": "probe_error", "details": {"returncode": process.returncode}}
    try:
        payload = json.loads(process.stdout)
    except (ValueError, TypeError):
        return {"status": "probe_error", "details": {"reason": "invalid_probe_json"}}
    return payload


def _probe_cuda_driver(
    platform_name: str,
    *,
    finder: Callable[[str], str | None] | None = None,
    loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Worker-only CUDA calls; finder/loader permit ctypes-level fake tests."""
    finder = finder if finder is not None else find_library
    if platform_name not in ("Windows", "Linux"):
        return {"status": "probe_error", "details": {"reason": "unsupported_probe_platform"}}
    if loader is None:
        if platform_name == "Windows":
            # CUDA driver DLL belongs to the Windows system directory.
            loader = lambda name: ctypes.WinDLL(name, winmode=0x00000800)
        else:
            loader = ctypes.CDLL
    fallback = ["nvcuda.dll"] if platform_name == "Windows" else ["libcuda.so.1", "libcuda.so"]
    discovered = finder("nvcuda" if platform_name == "Windows" else "cuda")
    names = list(dict.fromkeys(([discovered] if discovered else []) + fallback))
    driver = None
    loaded_name = ""
    for name in names:
        try:
            driver = loader(name)
            loaded_name = name
            break
        except OSError:
            continue
    if driver is None:
        return {"status": "missing_driver", "details": {"searched_libraries": names}}
    details = {"driver_library": loaded_name}

    def error(stage, code):
        return {"status": "no_device" if code == 100 else "driver_error", "details": {**details, "stage": stage, "cuda_code": code}}

    signatures = {
        "cuInit": [ctypes.c_uint],
        "cuDeviceGetCount": [ctypes.POINTER(ctypes.c_int)],
        "cuDeviceGet": [ctypes.POINTER(ctypes.c_int), ctypes.c_int],
        "cuDeviceGetName": [ctypes.POINTER(ctypes.c_char), ctypes.c_int, ctypes.c_int],
    }
    try:
        for name, arguments in signatures.items():
            function = getattr(driver, name)
            function.argtypes = arguments
            function.restype = ctypes.c_int
    except AttributeError:
        return {"status": "driver_error", "details": {**details, "stage": "driver_api_symbols"}}
    code = driver.cuInit(0)
    if code != 0:
        return error("cuInit", code)
    count = ctypes.c_int()
    code = driver.cuDeviceGetCount(ctypes.byref(count))
    if code != 0:
        return error("cuDeviceGetCount", code)
    if count.value == 0:
        return {"status": "no_device", "details": details}
    if count.value < 0:
        return {"status": "driver_error", "details": {**details, "stage": "invalid_device_count"}}
    devices = []
    for ordinal in range(count.value):
        device = ctypes.c_int()
        code = driver.cuDeviceGet(ctypes.byref(device), ordinal)
        if code != 0:
            return error("cuDeviceGet", code)
        name_buffer = ctypes.create_string_buffer(256)
        code = driver.cuDeviceGetName(name_buffer, len(name_buffer), device.value)
        if code != 0:
            return error("cuDeviceGetName", code)
        devices.append({"index": ordinal, "name": name_buffer.value.decode("utf-8", errors="replace")})
    return {"status": "ready", "devices": devices, "details": details}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--probe":
        raise SystemExit(2)
    # This process imports no application backends and cannot start a GUI.
    print(json.dumps(_probe_cuda_driver(sys.argv[2]), ensure_ascii=True))
