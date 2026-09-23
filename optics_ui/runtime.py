"""Interpreter policy shared by the Windows launcher and desktop module entry."""
from __future__ import annotations

import sys
import sysconfig


MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 15)
RECOMMENDED_PYTHON = "3.12"


def python_runtime_errors(version_info=None, *, free_threaded=None) -> list[str]:
    version = tuple((sys.version_info if version_info is None else version_info)[:2])
    errors = []
    if not MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE:
        errors.append("Python 3.10 through 3.14 is supported by this PySide6 release; Python 3.12 is recommended. "
                      + "This interpreter is " + ".".join(map(str, version)) + ".")
    if free_threaded is None:
        free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    if free_threaded:
        errors.append("This PySide6 release requires a standard Python build; free-threaded Python is not supported.")
    return errors


def runtime_info() -> dict:
    return {"version": list(sys.version_info[:3]), "executable": sys.executable,
            "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED"))}


def dependency_install_hint() -> str:
    # Use this interpreter, so installing a dependency never silently selects 3.12.
    command = '"' + sys.executable + '" -m pip install -r requirements.txt'
    return "Run in CMD: " + command + " ; or in PowerShell: & " + command
