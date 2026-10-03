"""Finite, bounded chart interchange. Stored reference data only; no prediction.

MTF is retained as a fraction; the renderer formats percent. Spot x/y have
already been converted to micrometres by the existing reference-data loader.
This module must not convert those coordinates a second time or compute RMS.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math


CHART_KINDS = frozenset({"mtf", "spot"})
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_MTF_ROWS = 8192
MAX_SPOT_POINTS = 50000


class ChartDataError(ValueError):
    def __init__(self, message, code="CHART_DATA_INVALID"):
        self.code, self.message = code, message
        super().__init__(message)


def _require(condition, message):
    if not condition:
        raise ChartDataError(message)


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value, name):
    _require(isinstance(value, str) and 0 < len(value) <= 4096, f"{name} must be a nonempty bounded string.")


def finite_json(value):
    """Reject malformed/nonfinite JSON before copying or exposing it to Qt."""
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        _require(depth <= 32 and count <= 200000, "Chart data exceeds the structure limit.")
        if isinstance(item, dict):
            _require(all(isinstance(key, str) for key in item), "Chart object keys must be strings.")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif item is None or type(item) in (str, bool):
            return
        else:
            _require(_finite(item), "Chart values must be finite JSON data.")

    visit(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ChartDataError("Chart data could not be encoded as finite JSON.") from exc
    _require(len(encoded) <= MAX_PAYLOAD_BYTES, "Chart data exceeds the 2 MiB limit.")


def validate_chart_view(value):
    _require(isinstance(value, dict) and set(value) == {"k", "x", "y"}, "Chart view requires k, x and y.")
    _require(all(_finite(v) for v in value.values()) and 1 <= value["k"] <= 12,
             "Chart view needs a zoom in [1, 12] and finite offsets.")
    return deepcopy(value)


def validate_chart_payload(payload, *, kind=None):
    """Return a detached payload, sorting MTF samples without mixing S/T."""
    finite_json(payload)
    _require(isinstance(payload, dict), "Chart payload must be an object.")
    actual_kind = payload.get("kind")
    _require(isinstance(actual_kind, str) and actual_kind in CHART_KINDS, "Unsupported chart kind.")
    _require(kind is None or kind == actual_kind, "Chart kind does not match its window.")
    _require(type(payload.get("schema_version")) is int and payload["schema_version"] == 1,
             "Unsupported chart schema version.")
    for key in ("revision", "reference_id", "source_label", "conditions_label"):
        _text(payload.get(key), key)
    _require(isinstance(payload.get("condition_metadata"), dict), "Chart condition metadata must be an object.")
    units = {"x": "lp/mm", "y": "fraction"} if actual_kind == "mtf" else {"x": "µm", "y": "µm"}
    _require(payload.get("units") == units, "Chart units do not match the declared data contract.")
    _require("rms_diameter_um" in payload and (payload["rms_diameter_um"] is None or
             _finite(payload["rms_diameter_um"]) and payload["rms_diameter_um"] >= 0),
             "RMS diameter must be a nonnegative finite value or null.")
    _require("view" in payload, "Chart view must be explicit (object or null).")
    if payload["view"] is not None:
        validate_chart_view(payload["view"])
    rows = payload.get(actual_kind)
    limit = MAX_MTF_ROWS if actual_kind == "mtf" else MAX_SPOT_POINTS
    _require(isinstance(rows, list) and len(rows) <= limit, f"Chart rows must be a list of at most {limit} entries.")
    seen = set()
    for row in rows:
        _require(isinstance(row, dict), "Chart sample must be an object.")
        if actual_kind == "mtf":
            _require(_finite(row.get("field_norm")) and 0 <= row["field_norm"] <= 1,
                     "MTF normalized field must be finite and in [0, 1].")
            _require(row.get("orientation") in ("SAGITTAL", "TANGENTIAL"), "MTF direction must remain explicit S/T.")
            _require(_finite(row.get("frequency_lp_per_mm")) and row["frequency_lp_per_mm"] >= 0,
                     "MTF frequency must be finite and nonnegative.")
            _require(_finite(row.get("mtf")) and 0 <= row["mtf"] <= 1, "MTF must be a finite fraction in [0, 1].")
            key = (row["field_norm"], row["orientation"], row["frequency_lp_per_mm"])
            _require(key not in seen, "Duplicate MTF field/direction/frequency sample.")
            seen.add(key)
        else:
            _require(_finite(row.get("x")) and _finite(row.get("y")), "Spot coordinates must be finite micrometres.")
            if row.get("wavelength_nm") is not None:
                _require(_finite(row["wavelength_nm"]) and row["wavelength_nm"] > 0,
                         "Spot wavelength must be positive and finite when provided.")
    result = deepcopy(payload)
    if actual_kind == "mtf":
        result["mtf"].sort(key=lambda row: (row["field_norm"], row["orientation"], row["frequency_lp_per_mm"]))
    return result
