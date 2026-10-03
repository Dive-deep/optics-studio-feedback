"""Pure validation for native workbench session state; never reads file paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath

from .sensitivity import SensitivityError, validate_panel_snapshot


WORKBENCH_KEYS = {"version", "page", "llm_visible", "analysis_visible", "workspace_split", "explorer", "sensitivity"}
LAYOUT_KEYS = {"window", "llm_width", "explorer_split", "charts"}
WINDOW_KEYS = {"x", "y", "width", "height", "maximized"}
EXPLORER_KEYS = {"workspace_root", "files", "current_file", "wrap_lines"}
PAGES = {"workspace", "explorer", "tailoring", "update", "sim", "auto"}
MAX_FILES = 64
MAX_PATH_LENGTH = 4096
MAX_QT_INT = 2**31 - 1
MIN_QT_INT = -(2**31)
MAX_WIDGET_SIZE = 2**24 - 1


class WorkbenchStateError(ValueError):
    """A native session field cannot be safely restored."""


def _require(condition, message):
    if not condition:
        raise WorkbenchStateError(message)


def _path_text(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_PATH_LENGTH and "\x00" not in value


def _relative_path(value):
    return (_path_text(value) and "\\" not in value and not PurePosixPath(value).is_absolute()
            and not PureWindowsPath(value).drive
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _validate_split(value, label):
    _require(isinstance(value, list) and len(value) == 2
             and all(type(size) is int and 0 <= size <= MAX_QT_INT for size in value)
             and sum(value) > 0,
             f"{label} needs two nonnegative Qt integers with a positive total.")


def _validate_window(value, label):
    if value is None:
        return
    _require(isinstance(value, dict) and set(value) == WINDOW_KEYS,
             f"{label} geometry has missing or unsupported fields.")
    for key in ("x", "y"):
        _require(type(value[key]) is int and MIN_QT_INT <= value[key] <= MAX_QT_INT,
                 f"{label} {key} must be a signed Qt integer.")
    for key in ("width", "height"):
        _require(type(value[key]) is int and 1 <= value[key] <= MAX_WIDGET_SIZE,
                 f"{label} {key} must be a positive Qt widget size.")
    _require(type(value["maximized"]) is bool, f"{label} maximized must be a boolean.")


def _validate_layout(value):
    _require(isinstance(value, dict) and set(value) == LAYOUT_KEYS,
             "Workbench layout has missing or unsupported fields.")
    _validate_window(value["window"], "Workbench window")
    width = value["llm_width"]
    _require(type(width) is int and 1 <= width <= MAX_WIDGET_SIZE,
             "LLM width must be a positive Qt widget size.")
    _validate_split(value["explorer_split"], "Explorer split")
    charts = value["charts"]
    _require(isinstance(charts, dict) and set(charts) == {"mtf", "spot"},
             "Chart layout requires exactly MTF and Spot window settings.")
    for name, chart in charts.items():
        _require(isinstance(chart, dict) and set(chart) == {"open", "window"},
                 f"{name} chart layout has missing or unsupported fields.")
        _require(type(chart["open"]) is bool, f"{name} chart open must be a boolean.")
        _validate_window(chart["window"], f"{name} chart window")


def validate_workbench_state(value) -> dict:
    """Return detached normalized settings before any UI or filesystem action.

    Absolute workspace roots from either OS are deliberately retained verbatim.
    Existence and root containment are checked by Explorer only during restore.
    Version 1 is returned as version 1 without inventing layout defaults.
    Version 2 adds native window geometry, panel widths and chart window state;
    screen fitting is the native restore layer's responsibility, never this validator's.
    Sensitivity snapshots delegate to the report service, including its 1 MiB
    embedded report limit. Credential rejection remains at the session boundary.
    """
    _require(isinstance(value, dict), "Workbench settings must be an object.")
    _require(type(value.get("version")) is int and value["version"] in (1, 2),
             "Workbench settings require version 1 or 2.")
    keys = WORKBENCH_KEYS if value["version"] == 1 else WORKBENCH_KEYS | {"layout"}
    _require(set(value) == keys,
             "Workbench settings have missing or unsupported fields.")
    _require(isinstance(value["page"], str) and value["page"] in PAGES,
             "Workbench page is not supported.")
    for key in ("llm_visible", "analysis_visible"):
        _require(type(value[key]) is bool, f"Workbench {key} must be a boolean.")
    _validate_split(value["workspace_split"], "Workbench workspace_split")
    if value["version"] == 2:
        _validate_layout(value["layout"])
    explorer = value["explorer"]
    _require(isinstance(explorer, dict) and set(explorer) == EXPLORER_KEYS,
             "Explorer settings have missing or unsupported fields.")
    root = explorer["workspace_root"]
    _require(_path_text(root) and (PurePosixPath(root).is_absolute() or PureWindowsPath(root).is_absolute()),
             "Explorer workspace_root must be an absolute POSIX or Windows path of at most 4096 characters.")
    files = explorer["files"]
    _require(isinstance(files, list) and len(files) <= MAX_FILES,
             "Explorer files must be a list of at most 64 source paths.")
    _require(all(_relative_path(path) for path in files),
             "Explorer files must be clean relative POSIX paths without '.', '..', drives, backslashes or NUL.")
    _require(len(set(files)) == len(files), "Explorer file paths must be unique.")
    current = explorer["current_file"]
    _require(current is None or isinstance(current, str) and current in files,
             "Explorer current_file must be null or one of its open files.")
    _require(type(explorer["wrap_lines"]) is bool, "Explorer wrap_lines must be a boolean.")
    sensitivity = value["sensitivity"]
    if sensitivity is not None:
        try:
            sensitivity = validate_panel_snapshot(sensitivity)
        except SensitivityError as error:
            raise WorkbenchStateError(f"Sensitivity settings: {error.message}") from error
    result = deepcopy(value)
    result["page"] = "workspace" if value["page"] == "sim" else value["page"]
    result["sensitivity"] = sensitivity
    return result
