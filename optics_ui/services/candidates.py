"""Read-only candidate projection and strict per-output comparison cohorts.

This module does not rank candidates, evaluate targets, calculate Pareto fronts,
or run models. Instance IDs are returned separately from cohort conditions.
"""
from collections import Counter, defaultdict
import hashlib
import itertools
import json

from .files import FileDataError, _conditions, _finite_number as _base_finite_number, _ui_compatible, _unique_object, _reject_constant


TABLES = ("designs", "lens_elements", "surfaces", "analyses", "wavelengths",
          "first_order_metrics", "mtf_samples", "spot_summary")
OUTPUT_TYPES = {"first_order": {"FIRST_ORDER", "THERMAL_MTF"},
                "mtf": {"FFT_MTF", "THERMAL_MTF"}, "spot": {"SPOT_DIAGRAM"}}
INSTANCE_FIELDS = {"analysis_id", "design_id", "case_id", "request_id", "candidate_id", "run_id", "created_at_utc"}
UNKNOWN_METADATA = {"UNKNOWN", "UNAVAILABLE", "UNSPECIFIED", "MISSING", "NONE", "NULL", "N/A"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value):
    try:
        return _base_finite_number(value)
    except (OverflowError, TypeError):
        return False


def _flag(value):
    return True if value == 1 else False if value == 0 else None


def _safe(value):
    """Only JSON-finite metadata can become comparison evidence."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if _finite_number(value):
        return float(value)
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key not in INSTANCE_FIELDS}
    raise ValueError("Unsupported metadata value")


def _settings(analysis):
    raw = analysis.get("settings_json")
    if not _text(raw):
        raise ValueError("Missing settings")
    settings = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not isinstance(settings, dict) or not settings:
        raise ValueError("Missing settings")
    return _safe(settings)


def _batch(connection):
    available = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "designs" not in available:
        raise FileDataError("DATABASE_SCHEMA", "The database has no designs table.")
    tables = {}
    for name in TABLES:
        rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{name}" ORDER BY design_id')] if name in available else []
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["design_id"]].append(row)
        tables[name] = grouped
    return tables


def _spectrum(settings, wavelengths, output):
    """Use declared per-analysis wavelengths; only medium comes from matching actual metadata."""
    def medium(wavelength):
        declared = settings.get("wavelength_reference_medium")
        if _text(declared):
            return declared
        values = {row.get("wavelength_reference_medium") for row in wavelengths
                  if row.get("wavelength_nm") == wavelength and _text(row.get("wavelength_reference_medium"))}
        if len(values) != 1:
            raise ValueError("Wavelength reference medium is unknown")
        return next(iter(values))

    reference = settings.get("reference_wavelength_nm")
    wave = settings.get("wavelengths_nm")
    weights = settings.get("wavelength_weights")
    if _finite_number(reference) and reference > 0 and (output == "first_order" or not wave):
        return {"mode": "reference", "reference_wavelength_nm": float(reference),
                "reference_medium": medium(reference)}
    if (not isinstance(wave, list) or not wave or not all(_finite_number(w) and w > 0 for w in wave)
            or len(set(wave)) != len(wave) or not isinstance(weights, list) or len(weights) != len(wave)
            or not all(_finite_number(w) and w >= 0 for w in weights) or sum(weights) <= 0):
        raise ValueError("Declared wavelengths and weights are required")
    components = sorted([{"wavelength_nm": float(w), "weight": float(weight), "reference_medium": medium(w)}
                         for w, weight in zip(wave, weights)], key=lambda row: row["wavelength_nm"])
    return {"mode": "weighted", "components": components}


def _analysis_proof(output, rows, by_analysis, wavelengths, temperature, reasons):
    prefix = output.upper()
    if not rows:
        reasons.append(prefix + "_RESULT_MISSING")
        return None, None
    identifiers = {row.get("analysis_id") for row in rows}
    if len(identifiers) != 1 or not all(_text(value) for value in identifiers):
        reasons.append(prefix + "_ANALYSIS_LINK_MISSING_OR_AMBIGUOUS")
        return None, None
    identifier = next(iter(identifiers))
    linked = by_analysis.get(identifier, [])
    if len(linked) != 1:
        reasons.append(prefix + "_ANALYSIS_LINK_INVALID")
        return None, identifier
    analysis = linked[0]
    if analysis.get("analysis_type") not in OUTPUT_TYPES[output]:
        reasons.append(prefix + "_ANALYSIS_TYPE_UNSUPPORTED")
        return None, identifier
    if (analysis.get("execution_status") != "SUCCEEDED"
            or any(analysis.get(key) != 1 for key in ("analysis_requested", "analysis_succeeded", "result_complete", "result_valid"))):
        reasons.append(prefix + "_ANALYSIS_NOT_VALID_COMPLETE_SUCCESS")
        return None, identifier
    required = ("analysis_type", "design_mode", "fidelity", "engine_name", "result_source")
    if not all(_text(analysis.get(key)) and analysis[key].strip().upper() not in UNKNOWN_METADATA for key in required):
        reasons.append(prefix + "_ANALYSIS_METADATA_MISSING")
        return None, identifier
    try:
        settings = _settings(analysis)
        if "temperature_c" in settings and settings["temperature_c"] != temperature:
            raise ValueError("Analysis temperature disagrees with selected result")
        if "temperatures_c" in settings and (not isinstance(settings["temperatures_c"], list) or temperature not in settings["temperatures_c"]):
            raise ValueError("Selected temperature is not in analysis settings")
        spectrum = _spectrum(settings, wavelengths, output)
    except (ValueError, TypeError, RecursionError):
        reasons.append(prefix + "_CONDITIONS_UNPROVEN")
        return None, identifier
    return {**{key: analysis[key] for key in required}, "temperature_c": temperature,
            "spectrum": spectrum, "settings": settings}, identifier


def _first_order(rows, proof, reasons):
    if proof is None:
        return None
    if len(rows) != 1:
        reasons.append("FIRST_ORDER_RESULT_AMBIGUOUS")
        return None
    row = rows[0]
    value = row.get("horizontal_fov_deg")
    if not _finite_number(value) or value < 0:
        reasons.append("FIRST_ORDER_FOV_MISSING_OR_INVALID")
        return None
    if "focus_valid" in row and row["focus_valid"] != 1:
        reasons.append("FIRST_ORDER_FOCUS_INVALID")
        return None
    if not _text(proof["settings"].get("method")):
        reasons.append("FIRST_ORDER_METHOD_MISSING")
        return None
    proof.update(method=proof["settings"]["method"], value_unit="degree", quantity="horizontal_fov")
    return float(value)


def _spot(rows, proof, reasons):
    if proof is None:
        return None
    if len(rows) != 1:
        reasons.append("SPOT_RESULT_AMBIGUOUS")
        return None
    row = rows[0]
    radius = row.get("rms_radius_mm_proxy", row.get("rms_radius_mm"))
    if not _finite_number(radius) or radius < 0:
        reasons.append("SPOT_RMS_MISSING_OR_INVALID")
        return None
    reference = row.get("reference")
    settings = proof["settings"]
    method = settings.get("method", settings.get("ray_pattern"))
    if not _text(reference) or not _text(method) or not _finite_number(row.get("ray_count")) or row["ray_count"] <= 0:
        reasons.append("SPOT_REFERENCE_OR_SAMPLING_MISSING")
        return None
    if "reference" in settings and settings["reference"] != reference:
        reasons.append("SPOT_REFERENCE_MISMATCH")
        return None
    fields = settings.get("fields_norm")
    if fields is not None and (not isinstance(fields, list) or not all(_finite_number(value) for value in fields) or 1.0 not in fields):
        reasons.append("SPOT_FIELD_METADATA_MISMATCH")
        return None
    diameter = float(radius) * 2000
    if not _finite_number(diameter):
        reasons.append("SPOT_RMS_MISSING_OR_INVALID")
        return None
    proof.update(field_norm=1.0, reference=reference, method=method, ray_count=row["ray_count"], value_unit="um", quantity="rms_diameter")
    return diameter


def _mtf(rows, proof, reasons):
    if proof is None:
        return []
    samples, keys = [], []
    for row in rows:
        field, orientation, frequency, value = (row.get(key) for key in ("field_norm", "orientation", "frequency_lp_per_mm", "mtf"))
        if (not all(_finite_number(number) for number in (field, frequency, value)) or field < 0 or frequency < 0
                or not 0 <= value <= 1 or orientation not in {"SAGITTAL", "TANGENTIAL"} or not _text(row.get("method"))):
            reasons.append("MTF_SAMPLE_INVALID")
            return []
        keys.append((float(field), orientation, float(frequency)))
        samples.append({"field_norm": float(field), "orientation": orientation, "frequency_lp_per_mm": float(frequency), "mtf": float(value)})
    settings = proof["settings"]
    axes = [settings.get(key) for key in ("fields_norm", "orientations", "frequencies_lp_per_mm")]
    if (not all(isinstance(axis, list) and axis for axis in axes) or not _text(settings.get("method"))
            or not all(_finite_number(x) and x >= 0 for x in axes[0] + axes[2])
            or not all(isinstance(x, str) and x in {"SAGITTAL", "TANGENTIAL"} for x in axes[1])):
        reasons.append("MTF_GRID_METADATA_MISSING")
        return []
    expected = set(itertools.product(*axes))
    if len(set(keys)) != len(keys) or set(keys) != expected:
        reasons.append("MTF_GRID_INCOMPLETE_OR_DUPLICATE")
        return []
    proof.update(method=settings["method"], sample_grid={"fields_norm": sorted(set(axes[0])), "orientations": sorted(set(axes[1])),
                  "frequencies_lp_per_mm": sorted(set(axes[2]))}, value_unit="fraction", frequency_unit="lp/mm")
    methods = {row["method"] for row in rows}
    if len(methods) == 1:
        proof["result_method"] = next(iter(methods))
    else:
        proof["result_method_by_sample"] = sorted([
            {"field_norm": float(row["field_norm"]), "orientation": row["orientation"],
             "frequency_lp_per_mm": float(row["frequency_lp_per_mm"]), "method": row["method"]}
            for row in rows], key=lambda row: (row["field_norm"], row["orientation"], row["frequency_lp_per_mm"]))
    return sorted(samples, key=lambda row: (row["field_norm"], row["orientation"], row["frequency_lp_per_mm"]))


def _source(design, analyses, reasons):
    origin = design.get("data_origin") if _text(design.get("data_origin")) else None
    values = [origin or ""] + [str(row.get(key) or "") for row in analyses for key in ("result_source", "engine_name")]
    for analysis in analyses:
        try:
            settings = _settings(analysis)
            if _text(settings.get("synthetic_engine")):
                values.append("SYNTHETIC_ENGINE:" + settings["synthetic_engine"])
            for key in ("result_source", "data_origin"):
                if _text(settings.get(key)):
                    values.append(settings[key])
        except (ValueError, TypeError, RecursionError):
            pass
    def family(row):
        source = str(row.get("result_source") or "").upper()
        engine = str(row.get("engine_name") or "").upper()
        if any(marker in source + engine for marker in ("PREDICT", "SURROGATE", "NEURAL")) or source == "MODEL" or source.startswith("MODEL_"):
            return "predicted"
        if any(marker in source + engine for marker in ("SYNTHETIC", "PROXY")):
            return "synthetic"
        if "ZEMAX" in source:
            return "zemax"
        return "db"
    families = {family(row) for row in analyses}
    if "predicted" in families or any(any(marker in value.upper() for marker in ("PREDICT", "SURROGATE", "NEURAL"))
                                      or value.upper() == "MODEL" or value.upper().startswith("MODEL_") for value in values):
        reasons.append("PREDICTED_SOURCE_UNSUPPORTED")
    if len(families) > 1:
        reasons.append("PROVENANCE_MIXED_SOURCES")
    synthetic = any("SYNTHETIC" in value.upper() or "PROXY" in value.upper() for value in values)
    declared_zemax = "ZEMAX" in (origin or "").upper()
    results = [row.get("result_source") for row in analyses]
    if synthetic:
        if design.get("zemax_executed") == 1 or declared_zemax:
            reasons.append("PROVENANCE_CONFLICT")
        return "synthetic", origin
    if results and all(_text(value) and "ZEMAX" in value.upper() for value in results) and design.get("zemax_executed") == 1:
        return "zemax", origin
    if declared_zemax and design.get("zemax_executed") == 0:
        reasons.append("PROVENANCE_CONFLICT")
    return "db", origin


def candidate_data_from_connection(connection):
    tables = _batch(connection)
    cases, cohorts, excluded = [], {}, Counter()
    for case_id in sorted(tables["designs"]):
        designs = tables["designs"][case_id]
        if len(designs) != 1 or not _text(case_id):
            raise FileDataError("DATABASE_SCHEMA", "Candidate cases require unique non-empty design IDs.")
        design = designs[0]
        analyses = tables["analyses"][case_id]
        wavelengths = sorted(tables["wavelengths"][case_id], key=lambda row: row.get("wavelength_no", 0))
        metrics, mtf, spots = (tables[name][case_id] for name in ("first_order_metrics", "mtf_samples", "spot_summary"))
        reasons = []
        try:
            selected = _conditions(analyses, wavelengths, metrics, mtf, spots)
        except (ValueError, TypeError, OverflowError, RecursionError):
            selected = {"temperature_c": None, "temperature_source": "display_default"}
            reasons.append("CASE_CONDITIONS_INVALID")
        temperature = float(selected["temperature_c"]) if selected["temperature_source"] != "display_default" else None
        selected_rows = {"first_order": [r for r in metrics if temperature is not None and r.get("temperature_c") == temperature],
                         "mtf": [r for r in mtf if temperature is not None and r.get("temperature_c") == temperature],
                         "spot": [r for r in spots if temperature is not None and r.get("temperature_c") == temperature and r.get("field_norm") == 1.0]}
        by_analysis = defaultdict(list)
        for analysis in analyses:
            by_analysis[analysis.get("analysis_id")].append(analysis)
        if temperature is None:
            reasons.append("TEMPERATURE_UNPROVEN")
        compatible = _ui_compatible(tables["lens_elements"][case_id], tables["surfaces"][case_id])
        if not compatible:
            reasons.append("UI_TOPOLOGY_OR_SURFACE_UNSUPPORTED")
        if design.get("geometry_valid") != 1:
            reasons.append("GEOMETRY_NOT_VALID")
        if design.get("trace_success") != 1:
            reasons.append("TRACE_NOT_SUCCESSFUL")
        outputs, identifiers = {}, {}
        for output, rows in selected_rows.items():
            outputs[output], identifiers[output] = _analysis_proof(output, rows, by_analysis, wavelengths, temperature, reasons)
        fov = _first_order(selected_rows["first_order"], outputs["first_order"], reasons)
        spot = _spot(selected_rows["spot"], outputs["spot"], reasons)
        curve = _mtf(selected_rows["mtf"], outputs["mtf"], reasons)
        linked = [by_analysis[key][0] for key in identifiers.values() if len(by_analysis.get(key, [])) == 1]
        source_kind, origin = _source(design, linked, reasons)
        conditions = {"temperature_c": temperature,
                      "temperature_source": selected["temperature_source"] if temperature is not None else None,
                      "outputs": outputs}
        reasons = sorted(set(reasons))
        ready = not reasons and fov is not None and spot is not None and bool(curve)
        key = None
        if ready:
            signature = {"comparison_policy": "strict-analysis-v1", "source_kind": source_kind,
                         "origin": origin, "conditions": conditions}
            key = "cohort-v1:" + hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        case = {"id": case_id, "source_kind": source_kind, "origin": origin,
                "status": design.get("overall_status") if _text(design.get("overall_status")) else None,
                "ui_compatible": compatible, "geometry_valid": _flag(design.get("geometry_valid")), "trace_success": _flag(design.get("trace_success")),
                "temperature_c": temperature, "conditions": conditions, "cohort_key": key,
                "comparison_ready": ready, "exclusion_reasons": reasons,
                "metrics": {"spot_rms_diameter_um": spot, "horizontal_fov_deg": fov}, "mtf": curve,
                "analysis_ids": identifiers, "zemax_executed": _flag(design.get("zemax_executed")),
                "units": {"spot_rms_diameter_um": "um", "horizontal_fov_deg": "degree", "mtf": "fraction"}}
        cases.append(case)
        excluded.update(reasons)
        if key is not None:
            group = cohorts.setdefault(key, {"key": key, "source_kind": source_kind, "conditions": conditions, "case_ids": []})
            group["case_ids"].append(case_id)
    groups = [{**group, "case_count": len(group["case_ids"])} for group in cohorts.values()]
    ready_count = sum(case["comparison_ready"] for case in cases)
    return {"schema_version": 1, "cases": cases, "cohorts": groups,
            "summary": {"total_cases": len(cases), "comparison_ready_cases": ready_count,
                        "excluded_cases": len(cases)-ready_count, "cohort_count": len(groups),
                        "source_counts": dict(Counter(case["source_kind"] for case in cases)), "exclusion_counts": dict(excluded)},
            "read_only": True, "comparison_policy": "strict-analysis-v1", "target_evaluation_performed": False}
