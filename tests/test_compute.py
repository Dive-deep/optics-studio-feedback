"""Readiness contracts, exercised without an NVIDIA GPU or remote connection."""

import ctypes
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from optics_ui.services.compute import (
    GpuReadinessService,
    _probe_cuda_driver,
    _run_isolated_probe,
)


class FakeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class FakeDriver:
    def __init__(self, names=("Test GPU 0",), init_code=0, count_code=0, name_code=0):
        self.names = names
        self.cuInit = FakeFunction(lambda flags: init_code)
        self.cuDeviceGetCount = FakeFunction(
            lambda ptr: self.write_int(ptr, len(names)) or count_code
        )
        self.cuDeviceGet = FakeFunction(
            lambda ptr, ordinal: self.write_int(ptr, ordinal + 10)
        )
        self.cuDeviceGetName = FakeFunction(
            lambda buffer, length, device: self.write_name(buffer, device, name_code)
        )

    @staticmethod
    def write_int(ptr, value):
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int))[0] = value
        return 0

    def write_name(self, buffer, device, code):
        buffer.value = self.names[device - 10].encode("utf-8")
        return code


class ReadinessServiceTests(unittest.TestCase):
    def test_mac_is_unsupported_and_does_not_probe(self):
        probe = Mock(side_effect=AssertionError("Must not probe on Mac"))
        result = GpuReadinessService(platform_name="Darwin", probe=probe).test()
        self.assertEqual(result["status"], "unsupported")
        self.assertFalse(result["ready"])
        self.assertIn("CUDA", result["message"])
        self.assertIn("Apple", result["message"])
        probe.assert_not_called()

    def test_other_platform_is_unsupported_without_probe(self):
        probe = Mock()
        result = GpuReadinessService(platform_name="FreeBSD", probe=probe).test()
        self.assertEqual(result["status"], "unsupported")
        probe.assert_not_called()

    def test_server_is_not_configured_without_local_or_network_probe(self):
        probe = Mock(side_effect=AssertionError("Must not probe a server"))
        result = GpuReadinessService(platform_name="Windows", probe=probe).test("server")
        self.assertEqual(result["target"], "server")
        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(result["message"], "서버 연결 정보가 없어 검사할 수 없습니다")
        self.assertFalse(result["ready"])
        probe.assert_not_called()

    def test_invalid_target_does_not_probe(self):
        probe = Mock()
        result = GpuReadinessService(probe=probe).test("other")
        self.assertEqual(result["status"], "invalid_target")
        self.assertFalse(result["ready"])
        probe.assert_not_called()

    def test_ready_only_means_driver_and_device_enumeration(self):
        devices = [{"index": 0, "name": "Test GPU"}]
        probe = Mock(return_value={"status": "ready", "devices": devices})
        service = GpuReadinessService(platform_name="Windows", probe=probe, timeout_seconds=3)
        result = service.test("local")
        self.assertTrue(result["ready"])
        self.assertEqual(result["devices"], devices)
        self.assertEqual(result["details"]["scope"], "cuda_driver_and_device_enumeration")
        self.assertFalse(result["details"]["framework_tested"])
        self.assertFalse(result["details"]["kernel_tested"])
        probe.assert_called_once_with("Windows", 3)
        json.dumps(result, ensure_ascii=False)

    def test_known_probe_failures_have_korean_messages_and_false_ready(self):
        for status in ("missing_driver", "no_device", "driver_error", "probe_error"):
            with self.subTest(status=status):
                probe = Mock(return_value={"status": status, "details": {"stage": "cuInit", "cuda_code": 803}})
                result = GpuReadinessService(platform_name="Linux", probe=probe).test()
                self.assertEqual(result["status"], status)
                self.assertFalse(result["ready"])
                self.assertTrue(any("가" <= char <= "힣" for char in result["message"]))
                self.assertEqual(result["details"]["cuda_code"], 803)

    def test_timeout_is_reported_without_claiming_readiness(self):
        probe = Mock(side_effect=subprocess.TimeoutExpired("probe", 2))
        result = GpuReadinessService(platform_name="Windows", probe=probe, timeout_seconds=2).test()
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["ready"])
        self.assertEqual(result["details"]["timeout_seconds"], 2)

    def test_probe_exception_is_a_serializable_error(self):
        probe = Mock(side_effect=OSError("cannot launch child"))
        result = GpuReadinessService(platform_name="Linux", probe=probe).test()
        self.assertEqual(result["status"], "probe_error")
        self.assertFalse(result["ready"])
        json.dumps(result)

    def test_malformed_probe_output_cannot_report_ready(self):
        for payload in (None, [], {"status": "unknown"}, {"status": "ready", "devices": []}, {"status": "ready", "devices": [{"name": "GPU"}]}):
            with self.subTest(payload=payload):
                result = GpuReadinessService(platform_name="Linux", probe=lambda *_: payload).test()
                self.assertEqual(result["status"], "probe_error")
                self.assertFalse(result["ready"])

    def test_invalid_timeout_is_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                GpuReadinessService(timeout_seconds=value)


class CudaProbeTests(unittest.TestCase):
    def probe(self, driver):
        return _probe_cuda_driver("Windows", finder=lambda _: None, loader=lambda _: driver)

    def test_missing_driver(self):
        loader = Mock(side_effect=OSError("missing"))
        result = _probe_cuda_driver("Windows", finder=lambda _: None, loader=loader)
        self.assertEqual(result["status"], "missing_driver")
        loader.assert_called_once_with("nvcuda.dll")

    def test_driver_initialization_error(self):
        result = self.probe(FakeDriver(init_code=803))
        self.assertEqual(result["status"], "driver_error")
        self.assertEqual(result["details"]["stage"], "cuInit")
        self.assertEqual(result["details"]["cuda_code"], 803)

    def test_cuda_no_device_code(self):
        self.assertEqual(self.probe(FakeDriver(init_code=100))["status"], "no_device")

    def test_zero_devices(self):
        self.assertEqual(self.probe(FakeDriver(names=()))["status"], "no_device")

    def test_device_enumeration_error(self):
        result = self.probe(FakeDriver(count_code=999))
        self.assertEqual(result["status"], "driver_error")
        self.assertEqual(result["details"]["stage"], "cuDeviceGetCount")

    def test_device_name_error_does_not_report_ready(self):
        result = self.probe(FakeDriver(name_code=1))
        self.assertEqual(result["status"], "driver_error")
        self.assertEqual(result["details"]["stage"], "cuDeviceGetName")

    def test_missing_driver_symbol_is_driver_error(self):
        result = self.probe(object())
        self.assertEqual(result["status"], "driver_error")

    def test_resolves_device_handles_and_names(self):
        result = self.probe(FakeDriver(names=("GPU A", "GPU B")))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["devices"], [{"index": 0, "name": "GPU A"}, {"index": 1, "name": "GPU B"}])

    def test_linux_driver_search_uses_discovered_library(self):
        loader = Mock(return_value=FakeDriver())
        result = _probe_cuda_driver("Linux", finder=lambda _: "libcuda.so.1", loader=loader)
        self.assertEqual(result["status"], "ready")
        loader.assert_called_once_with("libcuda.so.1")


class IsolatedProbeTests(unittest.TestCase):
    @patch("optics_ui.services.compute.subprocess.run")
    def test_child_process_has_timeout_and_no_shell(self, run):
        payload = {"status": "no_device"}
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        self.assertEqual(_run_isolated_probe("Windows", 2.5), payload)
        args, kwargs = run.call_args
        self.assertIn("--probe", args[0])
        self.assertEqual(args[0][-1], "Windows")
        self.assertEqual(kwargs["timeout"], 2.5)
        self.assertFalse(kwargs["shell"])

    @patch("optics_ui.services.compute.subprocess.run")
    def test_timeout_propagates_to_service(self, run):
        run.side_effect = subprocess.TimeoutExpired("probe", 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_isolated_probe("Linux", 1)

    @patch("optics_ui.services.compute.subprocess.run")
    def test_child_crash_returns_probe_error(self, run):
        run.return_value = subprocess.CompletedProcess([], -11, "", "driver crash")
        result = _run_isolated_probe("Linux", 1)
        self.assertEqual(result["status"], "probe_error")
        self.assertEqual(result["details"]["returncode"], -11)

    @patch("optics_ui.services.compute.subprocess.run")
    def test_invalid_json_returns_probe_error(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "not json", "")
        self.assertEqual(_run_isolated_probe("Linux", 1)["status"], "probe_error")


if __name__ == "__main__":
    unittest.main()
