"""Read-only Sobol report contract. No sampling, DB inference, or evaluation.

Version 1 is an independent, ungrouped Saltelli cross-design interchange:
  format='optics-sobol-report', schema_version=1
  study={id, context_hash}; context=<complete workspace analysis context>
  origin={kind: external_analysis|synthetic_fixture, source}
  evaluator={kind: simulator|surrogate|analytic_test, id, version}
  conditions=<nonempty analysis conditions, identical to context.conditions>
  distribution={dependence:'independent', marginals:[{input_id, kind,
      bounds:[min,max]} | {input_id,kind:'categorical'|'discrete',
      values:[...],probabilities:[...]}]}
  sampling={method:'saltelli_cross_design', estimator, implementation,
      base_sample_count, evaluation_count, seed:int|null, scramble:bool,
      second_order:bool, design_hash:sha256, confidence_level:number|null,
      ci_method:string|null}
  inputs=[{id,label,unit}]; outputs=[{id,label,unit,variance:number|null,
      conditions:<nonempty output definition>}]
  first_order, total_order: output-by-input matrices of
      {estimate:number|null, ci_low:number|null, ci_high:number|null, status}

Confidence endpoints are explicit; SALib *_conf half-widths must be converted
by the producer, never interpreted as endpoints here. Additional JSON metadata
is preserved. Structural validation does not certify the evaluator, statistical
precision, independence assertion, or optical accuracy. The context hash covers
the complete supplied settings, including fixed values, types/materials/Stop,
model identity, targets and provenance; no DB rows are used to compute indices.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re


MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_EMBEDDED_REPORT_BYTES = 1024 * 1024
MAX_INPUTS = 128
MAX_OUTPUTS = 32
MAX_SAFE_CONTEXT_INTEGER = 2**53 - 1
FORMAT = "optics-sobol-report"
DEFAULT_OUTPUTS = (
    {"id": "mtf_0_s", "label": "MTF 6 lp/mm · 0F · S", "unit": "fraction"},
    {"id": "mtf_0_t", "label": "MTF 6 lp/mm · 0F · T", "unit": "fraction"},
    {"id": "mtf_08_s", "label": "MTF 6 lp/mm · 0.8F · S", "unit": "fraction"},
    {"id": "mtf_08_t", "label": "MTF 6 lp/mm · 0.8F · T", "unit": "fraction"},
    {"id": "spot_rms_diameter_1f", "label": "Spot RMS diameter · 1F", "unit": "µm"},
    {"id": "horizontal_fov", "label": "Horizontal FOV · full", "unit": "deg"},
    {"id": "vertical_fov", "label": "Vertical FOV · full", "unit": "deg"},
    {"id": "na", "label": "NA", "unit": "dimensionless"},
    {"id": "distortion", "label": "Distortion", "unit": "%"},
)
NUMERIC_STATUSES = {"estimated_unvalidated", "validated_for_scope", "insufficient_precision"}
NULL_STATUSES = {"not_computed", "zero_output_variance", "invalid_input_assumptions",
                 "sample_design_invalid", "undefined_output", "surrogate_validation_failed",
                 "unavailable", "fixed", "not_applicable"}


class SensitivityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _require(ok, message):
    if not ok:
        raise SensitivityError("INVALID_REPORT", message)


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value, name, *, empty=False):
    _require(isinstance(value, str) and len(value) <= 4096 and (empty or bool(value.strip())),
             f"{name} must be a {'possibly empty ' if empty else 'nonempty '}string.")


def _object(value, name, *, nonempty=True):
    _require(isinstance(value, dict) and (bool(value) or not nonempty), f"{name} must be an object.")


def _json_bytes(value):
    """Bound structure, reject Python/JSON nonfinite and non-JSON values."""
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        _require(depth <= 40 and count <= 100_000, "JSON nesting or element limit exceeded.")
        if isinstance(item, dict):
            for key, val in item.items():
                _require(isinstance(key, str), "JSON object keys must be strings.")
                visit(val, depth + 1)
        elif isinstance(item, list):
            for val in item:
                visit(val, depth + 1)
        elif item is None or isinstance(item, (str, bool, int)):
            pass
        elif isinstance(item, float):
            _require(math.isfinite(item), "Nonfinite numbers are not allowed.")
        else:
            raise SensitivityError("INVALID_REPORT", "Only JSON values are allowed.")

    visit(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise SensitivityError("INVALID_REPORT", "Report is not valid finite JSON.") from exc
    _require(len(encoded) <= MAX_REPORT_BYTES, "Report exceeds the 2 MiB limit.")
    return encoded


def context_hash(context: dict) -> str:
    """Stable context identity across Python → JSON/JavaScript → Python.

    JSON has a single number type. Hash-only normalization makes 1/1.0 and
    0/-0.0 identical without rewriting producer data. Integral values outside
    the interoperable ±(2**53-1) range are rejected conservatively, including
    integral floats, instead of accepting a hash that JS can silently change.
    Nonintegral finite binary64 values retain Python's round-trip representation.
    This is the v1 application convention, not a claim of full RFC 8785 JCS.
    """
    _object(context, "context", nonempty=False)
    _json_bytes(context)  # Validate bounds/types before traversing for hashing.

    def normalized(value):
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        if type(value) is int or type(value) is float and value.is_integer():
            _require(abs(value) <= MAX_SAFE_CONTEXT_INTEGER,
                     "Integral context values must be within JavaScript's safe integer range "
                     "±(2**53−1); encode larger identifiers as strings.")
            return int(value)
        return value

    return hashlib.sha256(_json_bytes(normalized(context))).hexdigest()


def _named_rows(rows, name, limit):
    _require(isinstance(rows, list) and 1 <= len(rows) <= limit,
             f"{name} must contain 1–{limit} entries.")
    seen = set()
    for row in rows:
        _object(row, name)
        for key in ("id", "label", "unit"):
            _text(row.get(key), f"{name}.{key}", empty=key == "unit")
        _require(row["id"] not in seen, f"Duplicate {name} id.")
        seen.add(row["id"])
    return seen


def _validate_distribution(report, context_parameters):
    distribution = report.get("distribution")
    _object(distribution, "distribution")
    _require(distribution.get("dependence") == "independent",
             "Version 1 requires explicitly independent, ungrouped inputs.")
    _require(not distribution.get("groups"), "Group effects need a separate report contract.")
    marginals = distribution.get("marginals")
    _require(isinstance(marginals, list) and len(marginals) == len(report["inputs"]),
             "One declared marginal is required per input.")
    seen = set()
    for marginal in marginals:
        _object(marginal, "marginal")
        input_id = marginal.get("input_id")
        _require(isinstance(input_id, str) and input_id in context_parameters and input_id not in seen,
                 "Marginal input id must match one unique context parameter.")
        seen.add(input_id)
        parameter = context_parameters[input_id]
        _require(parameter.get("active") is True and parameter.get("available") is True,
                 "An independent input must be active and available in the report context.")
        kind = marginal.get("kind")
        _require(isinstance(kind, str), "Marginal kind must be a string.")
        if kind in {"uniform", "loguniform"}:
            bounds = marginal.get("bounds")
            _require(isinstance(bounds, list) and len(bounds) == 2 and all(_number(v) for v in bounds)
                     and bounds[0] < bounds[1], "Numeric marginal bounds must increase and be finite.")
            _require(_number(parameter.get("min")) and _number(parameter.get("max")) and
                     bounds == [parameter.get("min"), parameter.get("max")],
                     "Marginal bounds do not match the recorded context range.")
            _require(kind != "loguniform" or bounds[0] > 0, "Log-uniform bounds must be positive.")
        elif kind in {"categorical", "discrete"}:
            values, probabilities = marginal.get("values"), marginal.get("probabilities")
            _require(isinstance(values, list) and 2 <= len(values) <= 256,
                     "A discrete marginal requires 2–256 values.")
            _require(all(isinstance(v, str) and bool(v) for v in values) if kind == "categorical"
                     else all(_number(v) for v in values), "Invalid discrete/categorical values.")
            _require(len(set(values)) == len(values), "Discrete values must be unique.")
            _require(isinstance(probabilities, list) and len(probabilities) == len(values)
                     and all(_number(p) and p > 0 for p in probabilities)
                     and math.isclose(sum(probabilities), 1., abs_tol=1e-9, rel_tol=0),
                     "Explicit positive probabilities must sum to 1.")
            if kind == "discrete":
                _require(_number(parameter.get("min")) and _number(parameter.get("max"))
                         and all(parameter["min"] <= v <= parameter["max"] for v in values),
                         "Discrete values must lie inside the context range.")
            elif "choices" in parameter:
                choices = parameter["choices"]
                _require(isinstance(choices, list) and all(isinstance(v, str) for v in choices)
                         and set(values) == set(choices),
                         "Categorical marginal differs from the context choices.")
        else:
            raise SensitivityError("INVALID_REPORT", "Unsupported marginal distribution in version 1.")
    _require(seen == {i["id"] for i in report["inputs"]}, "Marginals must match all report inputs.")


def validate_report(payload: dict) -> dict:
    """Return detached, validated data and diagnostics without changing estimates."""
    _json_bytes(payload)
    _object(payload, "report")
    _require(payload.get("format") == FORMAT and type(payload.get("schema_version")) is int
             and payload["schema_version"] == 1, "Unsupported Sobol report format or schema version.")
    report = copy.deepcopy(payload)
    _named_rows(report.get("inputs"), "inputs", MAX_INPUTS)
    _named_rows(report.get("outputs"), "outputs", MAX_OUTPUTS)
    context = report.get("context")
    _object(context, "context")
    _require(all(key in context for key in ("parameters", "conditions", "optics", "model",
                                           "reference_id", "targets")), "Incomplete study context.")
    parameters = context["parameters"]
    _require(isinstance(parameters, list) and len(parameters) <= 256, "Invalid context parameters.")
    by_id = {}
    for parameter in parameters:
        _object(parameter, "context parameter")
        _text(parameter.get("id"), "context parameter id")
        _require(parameter["id"] not in by_id, "Duplicate context parameter id.")
        by_id[parameter["id"]] = parameter
    study = report.get("study")
    _object(study, "study")
    _text(study.get("id"), "study.id")
    _require(study.get("context_hash") == context_hash(context), "Study context hash does not match its settings.")
    _object(report.get("conditions"), "conditions")
    _require(report["conditions"] == context["conditions"], "Report conditions conflict with recorded context.")
    for key in ("optics", "model", "targets"):
        _object(context[key], f"context.{key}", nonempty=False)
    origin = report.get("origin")
    _object(origin, "origin")
    _require(isinstance(origin.get("kind"), str) and origin["kind"] in {"external_analysis", "synthetic_fixture"}, "Explicit report origin is required.")
    _text(origin.get("source"), "origin.source")
    evaluator = report.get("evaluator")
    _object(evaluator, "evaluator")
    _require(isinstance(evaluator.get("kind"), str) and evaluator["kind"] in {"simulator", "surrogate", "analytic_test"}, "Unsupported evaluator kind.")
    for key in ("id", "version"):
        _text(evaluator.get(key), f"evaluator.{key}")
    for item in report["inputs"]:
        _require(item["id"] in by_id and item["unit"] == by_id[item["id"]].get("unit"),
                 "Report input must match the context id and unit.")
        _require(not item.get("group") and not item.get("derived"),
                 "Version 1 columns describe independent controls, not derived/group effects.")
    _validate_distribution(report, by_id)
    sampling = report.get("sampling")
    _object(sampling, "sampling")
    _require(sampling.get("method") == "saltelli_cross_design",
             "A Sobol sensitivity cross-design is required; arbitrary DB rows are not a design.")
    for key in ("estimator", "implementation"):
        _text(sampling.get(key), f"sampling.{key}")
    for key in ("base_sample_count", "evaluation_count"):
        _require(type(sampling.get(key)) is int and 1 <= sampling[key] <= 10**12,
                 f"sampling.{key} must be a positive integer.")
    for key in ("scramble", "second_order"):
        _require(type(sampling.get(key)) is bool, f"sampling.{key} must be explicit.")
    _require("seed" in sampling and (sampling["seed"] is None or
             type(sampling["seed"]) is int and sampling["seed"] >= 0), "sampling.seed is required (integer or null).")
    _require(isinstance(sampling.get("design_hash"), str) and
             re.fullmatch(r"[a-fA-F0-9]{64}", sampling["design_hash"]) is not None,
             "sampling.design_hash must be a SHA-256 identity.")
    d = len(report["inputs"])
    _require(sampling["evaluation_count"] == sampling["base_sample_count"] *
             (2 * d + 2 if sampling["second_order"] else d + 2), "Cross-design sample count does not match its dimensions.")
    _require("confidence_level" in sampling and (sampling["confidence_level"] is None or
             _number(sampling["confidence_level"]) and 0 < sampling["confidence_level"] < 1),
             "confidence_level must be explicit (probability or null).")
    _require("ci_method" in sampling, "CI method must be explicit (string or null).")
    if sampling["ci_method"] is not None:
        _text(sampling["ci_method"], "ci_method")
    warnings = []
    for output in report["outputs"]:
        _require("variance" in output and (output["variance"] is None or
                 _number(output["variance"]) and output["variance"] >= 0), "Output variance must be nonnegative or null.")
        _object(output.get("conditions"), "output conditions")
    for name in ("first_order", "total_order"):
        matrix = report.get(name)
        _require(isinstance(matrix, list) and len(matrix) == len(report["outputs"]), "Matrix output dimension mismatch.")
        for row_index, row in enumerate(matrix):
            _require(isinstance(row, list) and len(row) == d, "Matrix input dimension mismatch.")
            output = report["outputs"][row_index]
            for column, cell in enumerate(row):
                _object(cell, "matrix cell")
                _require(all(k in cell for k in ("estimate", "ci_low", "ci_high", "status")), "Incomplete matrix cell.")
                value, low, high, status = (cell[k] for k in ("estimate", "ci_low", "ci_high", "status"))
                _require(isinstance(status, str) and status in NUMERIC_STATUSES | NULL_STATUSES, "Unknown cell status.")
                _require(value is None and status in NULL_STATUSES or _number(value) and status in NUMERIC_STATUSES,
                         "Estimate and cell status disagree.")
                _require(low is None and high is None or _number(low) and _number(high) and low <= high,
                         "CI endpoints must both be finite and ordered, or both null.")
                _require(value is not None or low is None and high is None, "An undefined estimate cannot have a CI.")
                if value is not None:
                    _require(output["variance"] is not None and output["variance"] > 0,
                             "Numeric indices require a positive known output variance.")
                if low is not None:
                    _require(sampling["confidence_level"] is not None and sampling["ci_method"] is not None,
                             "CI endpoints require confidence level and method provenance.")
                if value is not None and not 0 <= value <= 1:
                    warnings.append({"code": "ESTIMATE_OUTSIDE_UNIT_INTERVAL", "matrix": name,
                                     "output_id": output["id"], "input_id": report["inputs"][column]["id"],
                                     "message": "Raw estimate outside [0, 1]; retained without clipping."})
    for row, output in enumerate(report["outputs"]):
        for column, item in enumerate(report["inputs"]):
            s1 = report["first_order"][row][column]["estimate"]
            st = report["total_order"][row][column]["estimate"]
            if s1 is not None and st is not None and s1 > st:
                warnings.append({"code": "FIRST_EXCEEDS_TOTAL", "output_id": output["id"],
                                 "input_id": item["id"], "message": "S1 exceeds ST; inspect estimator precision."})
    report["warnings"] = warnings
    return report


def validate_panel_snapshot(payload: dict) -> dict:
    """Validate before changing any workspace state during session restore.

    Embedded reports have a smaller budget so a surrounding 2 MiB session can
    carry optics and UI state too. No silent replacement by a fragile file path.
    The caller must still enforce its complete session/transport byte limit.
    """
    _object(payload, "sensitivity snapshot")
    _require(payload.get("format") == "optics-sensitivity-panel"
             and type(payload.get("schema_version")) is int and payload["schema_version"] == 1,
             "Unsupported sensitivity snapshot format.")
    _require(isinstance(payload.get("metric"), str) and payload["metric"] in {"S1", "ST"},
             "Unknown sensitivity metric.")
    _require("report" in payload, "Missing sensitivity report field.")
    for key in ("report_path", "output_id"):
        _require(payload.get(key) is None or isinstance(payload[key], str), f"Invalid {key}.")
    report = payload["report"]
    if report is not None:
        if len(_json_bytes(report)) > MAX_EMBEDDED_REPORT_BYTES:
            raise SensitivityError("SESSION_REPORT_TOO_LARGE",
                                   "Sensitivity report exceeds the 1 MiB session embedding limit. "
                                   "Import a smaller report before saving; the current result is retained.")
        report = validate_report(report)
    result = copy.deepcopy(payload)
    result["report"] = report
    _json_bytes(result)
    return result


def load_sensitivity_report(path: str | Path) -> dict:
    """Read at most 2 MiB from one chosen JSON file; never execute report content."""
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON object key.")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise SensitivityError("INVALID_REPORT", "Nonfinite JSON constants are not allowed.")

    try:
        with Path(path).open("rb") as stream:
            content = stream.read(MAX_REPORT_BYTES + 1)
        _require(len(content) <= MAX_REPORT_BYTES, "Report exceeds the 2 MiB limit.")
        payload = json.loads(content.decode("utf-8-sig"), object_pairs_hook=pairs,
                             parse_constant=invalid_constant)
    except SensitivityError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise SensitivityError("REPORT_READ_ERROR", "Cannot read a valid Sobol JSON report.") from exc
    return validate_report(payload)
