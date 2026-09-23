"""Exercise the Windows CMD launcher without PowerShell rewriting its quotes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        print("This launcher check requires Windows.", file=sys.stderr)
        return 2
    command_processor = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    if not command_processor.is_file():
        print("Windows command processor was not found.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="Optics 사용자 preview ") as directory:
        preview = Path(directory)
        shutil.copytree(ROOT / "optics_ui", preview / "optics_ui",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("launch.py", "run_windows.cmd", "requirements.txt"):
            shutil.copyfile(ROOT / name, preview / name)
        environment = dict(os.environ)
        # Use the same setup-python interpreter that installed the dependencies.
        environment["OPTICS_PYTHON"] = sys.executable
        # Pass the complete command line to CreateProcess unchanged. An argv list
        # or PowerShell native invocation can escape the /c quote pair differently.
        # /s strips the first and last quotes, retaining the quoted script path.
        command = f'"{command_processor}" /d /s /c ""{preview / "run_windows.cmd"}" --check"'
        print("Checking CMD launcher in a Unicode/space path from its parent directory.", flush=True)
        try:
            completed = subprocess.run(
                command, executable=str(command_processor), shell=False,
                cwd=preview.parent, env=environment, stdin=subprocess.DEVNULL,
                timeout=30, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            print("CMD launcher preflight exceeded 30 seconds.", file=sys.stderr)
            return 124
        print(completed.stdout, end="")
        print(completed.stderr, end="", file=sys.stderr)
        if completed.returncode:
            print(f"CMD launcher preflight failed with exit code {completed.returncode}.", file=sys.stderr)
            return completed.returncode
        reports = [line.split("=", 1)[1] for line in completed.stdout.splitlines() if line.startswith("OPTICS_RUNTIME=")]
        if len(reports) != 1:
            print("CMD launcher did not report the resolved Python runtime exactly once.", file=sys.stderr)
            return 1
        try:
            reported = json.loads(reports[0])
            same_runtime = (reported["version"] == list(sys.version_info[:3])
                            and Path(reported["executable"]).resolve() == Path(sys.executable).resolve())
        except (ValueError, TypeError, KeyError):
            same_runtime = False
        if not same_runtime:
            print("CMD launcher used a different Python than the explicitly selected interpreter.", file=sys.stderr)
            return 1
    print("CMD launcher preflight PASS: selected interpreter version and executable match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
