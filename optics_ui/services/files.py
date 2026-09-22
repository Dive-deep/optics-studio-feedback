"""Python 3.12 local file/data services with explicit, serializable contracts.

Model artifacts are opaque bytes. SQLite inputs are opened read-only. Session
state is JSON data, never executable instructions, and restoration never starts
jobs. UI/Qt, prediction, training, Zemax, and provider clients do not belong here.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile

from .materials import load_ray_indices


REFERENCE_KEYS = ("report_path", "database_path", "target_path")
SESSION_FORMAT = "optics-ui-session"
SESSION_VERSION = 1
DB_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
CREDENTIAL_KEYS = {
    "apikey", "accesstoken", "refreshtoken", "authtoken", "password", "secret",
    "clientsecret", "credentials", "authorization", "privatekey", "bearertoken",
    "token", "apitoken", "secretkey",
}
CREDENTIAL_SUFFIXES = ("apikey", "accesstoken", "refreshtoken", "apitoken",
                       "password", "clientsecret", "privatekey", "secretkey")


class FileDataError(ValueError):
    """An expected local operation failure for display by the desktop bridge."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _path(value):
    try:
        if not value:
            raise ValueError("A file path is required")
        return Path(value).expanduser().resolve()
    except (TypeError, ValueError, OSError) as error:
        raise FileDataError("FILE_PATH", "A valid local file path is required.") from error


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _read_json(path, prefix):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise FileDataError(f"{prefix}_READ", f"Cannot read {path.name}.") from error
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise FileDataError(f"{prefix}_JSON", f"{path.name} is not valid JSON.") from error


def _json_state(value, *, code="SESSION_STATE", reject_credentials=True):
    """Validate actual JSON types; never coerce sets, tuples, or NaN to data."""
    ancestors = set()

    def visit(item, location):
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise FileDataError(code, f"Non-finite number at {location}.")
            return
        if not isinstance(item, (dict, list)):
            raise FileDataError(code, f"Non-JSON value at {location}.")
        if id(item) in ancestors:
            raise FileDataError(code, f"Circular value at {location}.")
        ancestors.add(id(item))
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise FileDataError(code, "JSON object keys must be strings.")
                normalized = re.sub("[^a-z0-9]", "", key.lower())
                sensitive = normalized in CREDENTIAL_KEYS or normalized.endswith(CREDENTIAL_SUFFIXES)
                if reject_credentials and sensitive and child not in (None, "", {}):
                    raise FileDataError("SESSION_CREDENTIALS", f"Credentials cannot be stored in session field {location}.{key}.")
                visit(child, f"{location}.{key}")
        else:
            for index, child in enumerate(item):
                visit(child, f"{location}[{index}]")
        ancestors.remove(id(item))

    try:
        visit(value, "state")
    except RecursionError as error:
        raise FileDataError(code, "JSON nesting is too deep.") from error
    return deepcopy(value)


def _references(references, base=None):
    if references is None:
        references = {}
    if not isinstance(references, dict) or set(references) - set(REFERENCE_KEYS):
        raise FileDataError("REFERENCE_SCHEMA", "Expected report_path, database_path, and target_path references.")
    result = {}
    for key in REFERENCE_KEYS:
        value = references.get(key)
        if value in (None, ""):
            result[key] = None
        elif not isinstance(value, (str, os.PathLike)):
            raise FileDataError("REFERENCE_SCHEMA", f"{key} must be a local path or null.")
        else:
            candidate = Path(value).expanduser()
            if base is not None and not candidate.is_absolute():
                candidate = base / candidate
            result[key] = str(_path(candidate))
    return result


def _relative_references(references, base):
    result = {}
    for key, value in references.items():
        if value is None:
            result[key] = None
        else:
            try:
                result[key] = Path(os.path.relpath(value, base)).as_posix()
            except ValueError:
                # Windows references on another drive remain explicit and can
                # be relinked. A bundle relocates all included assets together.
                result[key] = value
    return result


def _atomic_json(path, document, code):
    temporary = None
    try:
        encoded = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + chr(10)).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError, TypeError) as error:
        raise FileDataError(code, f"Could not save {path.name}; the previous file was not replaced.") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _readonly_database(path):
    if not path.is_file():
        raise FileDataError("MISSING_DATABASE", f"Database file is missing: {path.name}.")
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    except sqlite3.Error as error:
        raise FileDataError("DATABASE_READ", f"Cannot read SQLite database {path.name}: {error}.") from error
    finally:
        if connection is not None:
            connection.close()


def _tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _metadata(connection):
    if "metadata" not in _tables(connection):
        return {}
    return dict(connection.execute("SELECT key,value FROM metadata"))


def _rows(connection, table, case_id=None, order=()):
    """Table names/order keys are module constants, values use placeholders."""
    if table not in _tables(connection):
        return []
    columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    if case_id is not None and "design_id" not in columns:
        raise FileDataError("DATABASE_SCHEMA", f"Table {table} has no design_id.")
    query = f'SELECT * FROM "{table}"'
    parameters = ()
    if case_id is not None:
        query += " WHERE design_id=?"
        parameters = (case_id,)
    ordering = [key for key in order if key in columns]
    if ordering:
        query += " ORDER BY " + ",".join(f'"{key}"' for key in ordering)
    return [dict(row) for row in connection.execute(query, parameters)]


def _normalize_report(raw):
    if not isinstance(raw, dict) or type(raw.get("report_version")) is not int or raw["report_version"] != 1:
        raise FileDataError("REPORT_SCHEMA", "Expected a JSON object with report_version 1.")
    report = deepcopy(raw)
    mappings = (
        ("model", {"model_file": "filename", "model_id": "id", "model_sha256": "sha256"}),
        ("database", {"database_file": "filename", "database_id": "id", "database_schema": "schema_version"}),
    )
    for section, aliases in mappings:
        value = report.get(section, {})
        if not isinstance(value, dict):
            raise FileDataError("REPORT_SCHEMA", f"{section} must be an object.")
        value = dict(value)
        for alias, field in aliases.items():
            if alias in report:
                if field in value and value[field] != report[alias]:
                    raise FileDataError("REPORT_SCHEMA", f"Conflicting canonical and legacy {section}.{field}.")
                value[field] = report.pop(alias)
        report[section] = value
    model = report["model"]
    if not isinstance(model.get("id"), str) or not model["id"].strip():
        raise FileDataError("REPORT_SCHEMA", "model.id is required.")
    if model.get("sha256") is not None:
        if not isinstance(model["sha256"], str) or re.fullmatch("[a-fA-F0-9]{64}", model["sha256"]) is None:
            raise FileDataError("REPORT_SCHEMA", "model.sha256 must be a SHA-256 hexadecimal digest.")
    for field in ("id", "schema_version"):
        value = report["database"].get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise FileDataError("REPORT_SCHEMA", f"database.{field} must be a non-empty string when provided.")
    return report


def _sibling(folder, filename, role, suffixes):
    if (not isinstance(filename, str) or not filename
            or any(char in filename for char in ("/", chr(92), ":"))
            or filename in (".", "..")):
        raise FileDataError("SIBLING_PATH", f"{role.lower()} must name a file in the report folder.")
    path = (folder / filename).resolve()
    if path.parent != folder or path.suffix.lower() not in suffixes:
        raise FileDataError("SIBLING_PATH", f"Unsupported or non-sibling {role.lower()} file: {filename}.")
    if not path.is_file():
        raise FileDataError(f"MISSING_{role}", f"Missing {role.lower()} file: {filename}.")
    return path


def _catalog_path(report, database, metadata):
    catalog = report.get("material_catalog")
    if catalog is not None:
        filename = catalog.get("filename") if isinstance(catalog, dict) else None
        if not isinstance(filename, str) or not filename:
            raise FileDataError("REPORT_SCHEMA", "material_catalog.filename must name a local catalog.")
    else:
        filename = metadata.get("material_catalog_path")
    if not filename:
        return None
    path = Path(filename).expanduser()
    return (database.parent / path).resolve() if not path.is_absolute() else path.resolve()


def _protected_artifacts(references):
    """Protect direct references plus model/catalog dependencies during saves.

    A broken reference must not prevent saving unrelated UI settings. Parse
    available dependency declarations without requiring successful model/DB
    verification and without ever deserializing the model.
    """
    protected = {value for value in references.values() if value}
    report, database = {}, None
    if references.get("database_path"):
        database = Path(references["database_path"])
    if references.get("report_path"):
        report_path = Path(references["report_path"])
        try:
            report = _normalize_report(_read_json(report_path, "REPORT"))
            for section in ("model", "database"):
                name = report[section].get("filename")
                if (isinstance(name, str) and name and name not in (".", "..")
                        and not any(char in name for char in ("/", chr(92), ":"))):
                    artifact = (report_path.parent / name).resolve()
                    protected.add(str(artifact))
                    if section == "database" and database is None:
                        database = artifact
        except FileDataError:
            report = {}
    if database is not None:
        metadata = {}
        try:
            with _readonly_database(database) as connection:
                metadata = _metadata(connection)
        except FileDataError:
            pass
        try:
            catalog = _catalog_path(report, database, metadata)
            if catalog is not None:
                protected.add(str(catalog))
        except FileDataError:
            pass
    return protected


def _membership(report):
    training = report.get("training")
    if training is not None and not isinstance(training, dict):
        raise FileDataError("REPORT_SCHEMA", "training must be an object.")
    training = training or {}
    entries = training.get("cases", training.get("case_ids", report.get("trained_cases")))
    if entries is None:
        return None
    if not isinstance(entries, list):
        raise FileDataError("REPORT_SCHEMA", "Training membership must be an explicit list.")
    result = {}
    for entry in entries:
        item = {"case_id": entry} if isinstance(entry, str) else entry
        if not isinstance(item, dict):
            raise FileDataError("REPORT_SCHEMA", "Each training member requires a case_id.")
        case_id = item.get("case_id", item.get("design_id"))
        if not isinstance(case_id, str) or not case_id:
            raise FileDataError("REPORT_SCHEMA", "Each training member requires a non-empty case_id.")
        normalized = dict(item, case_id=case_id)
        if case_id in result and result[case_id] != normalized:
            raise FileDataError("REPORT_SCHEMA", f"Conflicting training entries for {case_id}.")
        result[case_id] = normalized
    return result


def _training_summary(report, connection):
    members = _membership(report)
    result = {"status": "unavailable", "trained_count": None, "new_case_count": None,
              "changed_case_count": None, "discovery_only": True, "change_detection_scope": "unavailable"}
    if members is None:
        return result
    result["trained_count"] = len(members)
    if "designs" not in _tables(connection):
        result["status"] = "database_cases_unavailable"
        return result
    rows = _rows(connection, "designs")
    current = {row["design_id"]: row for row in rows}
    result.update(status="available", new_case_count=len(set(current) - set(members)))
    common = set(current) & set(members)
    if members and all(members[key].get("prescription_hash") for key in members) and all(
            current[key].get("prescription_hash") for key in common):
        result["changed_case_count"] = sum(
            members[key]["prescription_hash"] != current[key]["prescription_hash"] for key in common)
        result["change_detection_scope"] = "prescription_hash_only"
    return result


def _finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _conditions(analyses, wavelengths, metrics, mtf, spot):
    settings = {}
    ordered = sorted(analyses, key=lambda row: row.get("analysis_type") != "FFT_MTF")
    for row in ordered:
        raw = row.get("settings_json")
        if raw:
            try:
                candidate = json.loads(raw, parse_constant=_reject_constant)
            except (ValueError, TypeError):
                continue
            if isinstance(candidate, dict):
                for key, value in candidate.items():
                    settings.setdefault(key, value)
    temperature = settings.get("temperature_c")
    source_temperature = "analysis_metadata"
    if not _finite_number(temperature):
        available = sorted({row["temperature_c"] for row in metrics + mtf + spot
                            if _finite_number(row.get("temperature_c"))})
        temperature = 20 if 20 in available else (available[0] if available else None)
        source_temperature = "database_results"
    assumed = []
    if temperature is None:
        temperature, source_temperature = 25, "display_default"
        assumed.append("temperature_c")
    spectrum = settings.get("wavelengths_nm")
    spectrum_source = "analysis_metadata"
    if not isinstance(spectrum, list) or not spectrum or not all(_finite_number(value) and value > 0 for value in spectrum):
        spectrum = [row["wavelength_nm"] for row in wavelengths
                    if _finite_number(row.get("wavelength_nm")) and row["wavelength_nm"] > 0]
        spectrum_source = "database_wavelengths"
    if not spectrum:
        spectrum, spectrum_source = [560], "display_default"
        assumed.append("wavelengths_nm")
    primary = next((row["wavelength_nm"] for row in wavelengths if row.get("is_primary")
                    and _finite_number(row.get("wavelength_nm"))), None)
    if primary is None and len(spectrum) == 1:
        primary = spectrum[0]
    # TODO(backend-metadata): Keep per-analysis weighting/mode and selected
    # conditions explicit when the live backend contract becomes available.
    result = {"temperature_c": temperature, "wavelengths_nm": list(spectrum),
              "primary_wavelength_nm": primary, "wavelength_mode": "multiple" if len(spectrum) > 1 else "single",
              "temperature_source": source_temperature, "wavelength_source": spectrum_source,
              "assumed_fields": assumed, "recalculation_performed": False,
              "spot_field_norm": 1.0}
    if isinstance(settings.get("wavelength_weights"), list):
        result["wavelength_weights"] = list(settings["wavelength_weights"])
    return result


def _at_temperature(rows, temperature):
    return [row for row in rows if "temperature_c" not in row or row["temperature_c"] == temperature]


def _ui_compatible(lenses, surfaces):
    if (len(lenses) != 3 or len(surfaces) != 6
            or {row.get("lens_index") for row in lenses} != {1, 2, 3}
            or {row.get("surface_index") for row in surfaces} != set(range(1, 7))):
        return False
    by_surface = {row["surface_index"]: row for row in surfaces}
    for lens in lenses:
        front = by_surface.get(lens.get("front_surface_index"), {})
        back = by_surface.get(lens.get("back_surface_index"), {})
        if (front.get("lens_index") != lens["lens_index"] or back.get("lens_index") != lens["lens_index"]
                or front.get("surface_type") not in {"STANDARD", "EVEN_ASPHERE"}
                or front.get("surface_type") != back.get("surface_type")):
            return False
    return True


def _sqlite_snapshot(source, destination):
    deadline = time.monotonic() + 30

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise FileDataError("DATABASE_BUSY", "Database snapshot timed out; retry after the current write finishes.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with _readonly_database(source) as connection:
        target = sqlite3.connect(destination)
        try:
            connection.backup(target, pages=256, progress=progress, sleep=0.02)
            # A backup contains committed WAL pages in its main database. Give
            # the portable copy DELETE journaling so reopening it does not
            # require or create a copied WAL/SHM sidecar.
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()


class FileDataService:
    def load_report(self, report_path):
        path = _path(report_path)
        if path.suffix.lower() != ".json":
            raise FileDataError("REPORT_TYPE", "Select a training report JSON, not a model artifact.")
        report = _normalize_report(_read_json(path, "REPORT"))
        model = _sibling(path.parent, report["model"].get("filename"), "MODEL", {".pth"})
        database = _sibling(path.parent, report["database"].get("filename"), "DATABASE", DB_SUFFIXES)
        try:
            if report["model"].get("sha256") and _sha256(model).lower() != report["model"]["sha256"].lower():
                raise FileDataError("MODEL_HASH_MISMATCH", f"Model checksum does not match the report: {model.name}.")
        except OSError as error:
            raise FileDataError("MODEL_READ", f"Cannot read model file {model.name}.") from error
        with _readonly_database(database) as connection:
            metadata = _metadata(connection)
            logical_id = metadata.get("database_id", metadata.get("dataset_id"))
            if report["database"].get("id") is not None and report["database"]["id"] != logical_id:
                raise FileDataError("DATABASE_ID_MISMATCH", f"Database logical ID does not match the report: {database.name}.")
            if report["database"].get("schema_version") is not None and report["database"]["schema_version"] != metadata.get("schema_version"):
                raise FileDataError("DATABASE_SCHEMA_MISMATCH", f"Database schema version does not match the report: {database.name}.")
            training = _training_summary(report, connection)
        warnings = []
        if report["database"].get("sha256"):
            warnings.append({"code": "DATABASE_SNAPSHOT_HASH_INFORMATIONAL",
                             "message": "The recorded database hash identifies a training snapshot; a live database may contain appended cases."})
        catalog = _catalog_path(report, database, metadata)
        if catalog is not None and not catalog.is_file():
            warnings.append({"code": "MISSING_MATERIAL_CATALOG", "message": f"Material catalog is missing: {catalog.name}."})
        best = report.get("best_candidate")
        suggestion = report.get("suggested_case_id")
        if suggestion is None and isinstance(best, dict):
            suggestion = best.get("case_id", best.get("design_id", best.get("id")))
        if suggestion is not None and not isinstance(suggestion, str):
            raise FileDataError("REPORT_SCHEMA", "The suggested case ID must be a string.")
        return {"status": "valid", "report": report, "report_path": str(path), "model_path": str(model),
                "database_path": str(database), "model_id": report["model"]["id"], "database_id": logical_id,
                "database_metadata": metadata, "material_catalog_path": str(catalog) if catalog else None,
                "training_summary": training, "suggested_case_id": suggestion, "warnings": warnings,
                "model_deserialized": False}

    def load_case(self, database_path, case_id):
        database = _path(database_path)
        if not isinstance(case_id, str) or not case_id:
            raise FileDataError("CASE_ID", "A case ID is required.")
        with _readonly_database(database) as connection:
            if "designs" not in _tables(connection):
                raise FileDataError("DATABASE_SCHEMA", "The database has no designs table.")
            design = _rows(connection, "designs", case_id)
            if not design:
                raise FileDataError("CASE_NOT_FOUND", f"Case {case_id} is not present in {database.name}.")
            lenses = _rows(connection, "lens_elements", case_id, ("lens_index",))
            surfaces = _rows(connection, "surfaces", case_id, ("surface_index",))
            analyses = _rows(connection, "analyses", case_id)
            wavelengths = _rows(connection, "wavelengths", case_id, ("wavelength_no",))
            metrics = _rows(connection, "first_order_metrics", case_id, ("temperature_c",))
            mtf = _rows(connection, "mtf_samples", case_id, ("temperature_c", "field_norm", "orientation", "frequency_lp_per_mm"))
            summaries = _rows(connection, "spot_summary", case_id, ("temperature_c", "field_norm"))
            spot = _rows(connection, "spot_points", case_id, ("temperature_c", "field_norm", "ray_index"))
            gaps = _rows(connection, "air_gaps", case_id, ("gap_index",))
            parameters = _rows(connection, "surface_parameters", case_id, ("surface_index", "parameter_name"))
            metadata = _metadata(connection)
            materials = sorted({row["material_id"] for row in _rows(connection, "lens_elements")
                                if isinstance(row.get("material_id"), str) and row["material_id"]})
        conditions = _conditions(analyses, wavelengths, metrics, mtf, summaries)
        ray_indices = load_ray_indices(database_path=database, database_metadata=metadata,
                                       material_ids=materials, analysis_conditions=conditions)
        temperature = conditions["temperature_c"]
        for surface in surfaces:
            surface["a12"] = None
        source = next((row.get("result_source") for row in analyses if row.get("result_source")), design[0].get("data_origin", "UNKNOWN"))
        return {"id": case_id, "origin": source, "database_path": str(database),
                "temperature_c": temperature, "primary_wavelength_nm": conditions["primary_wavelength_nm"],
                "analysis_conditions": conditions, "design": design, "lenses": lenses, "surfaces": surfaces,
                "mtf": _at_temperature(mtf, temperature),
                "spot": [row for row in _at_temperature(spot, temperature) if row.get("field_norm") == 1.0],
                "spot_summary": [row for row in _at_temperature(summaries, temperature) if row.get("field_norm") == 1.0],
                "metrics": _at_temperature(metrics, temperature), "air_gaps": gaps,
                "surface_parameters": parameters, "wavelengths": wavelengths, "analyses": analyses,
                "materials": materials, "ui_compatible": _ui_compatible(lenses, surfaces),
                "ray_indices": ray_indices,
                "database_metadata": metadata, "relative_illumination": None,
                "unavailable": {"a12": None, "relative_illumination": None}}

    def list_cases(self, database_path):
        database = _path(database_path)
        with _readonly_database(database) as connection:
            if "designs" not in _tables(connection):
                raise FileDataError("DATABASE_SCHEMA", "The database has no designs table.")
            designs = _rows(connection, "designs", order=("design_id",))
            metrics = _rows(connection, "first_order_metrics", order=("temperature_c",))
            spots = _rows(connection, "spot_summary", order=("temperature_c", "field_norm"))
            lenses = _rows(connection, "lens_elements")
            surfaces = _rows(connection, "surfaces")
        result = []
        for design in designs:
            case_id = design["design_id"]
            candidates = [row for row in metrics if row["design_id"] == case_id]
            metric = next((row for row in candidates if row.get("temperature_c") == 20), candidates[0] if candidates else {})
            temperature = metric.get("temperature_c")
            summary = next((row for row in spots if row["design_id"] == case_id
                            and row.get("field_norm") == 1.0 and row.get("temperature_c") == temperature), {})
            radius = summary.get("rms_radius_mm_proxy")
            result.append({"id": case_id, "status": design.get("overall_status"), "origin": design.get("data_origin", "UNKNOWN"),
                           "geometry_valid": design.get("geometry_valid"), "trace_success": design.get("trace_success"),
                           "temperature_c": temperature, "horizontal_fov_deg": metric.get("horizontal_fov_deg"),
                           "spot_rms_diameter_um": radius * 2000 if _finite_number(radius) else None,
                           "ui_compatible": _ui_compatible([row for row in lenses if row["design_id"] == case_id],
                                                           [row for row in surfaces if row["design_id"] == case_id])})
        return result

    def candidate_data(self, database_path):
        """Project observed results into strict comparison cohorts, without ranking."""
        from .candidates import candidate_data_from_connection
        database = _path(database_path)
        with _readonly_database(database) as connection:
            return candidate_data_from_connection(connection)

    def load_target(self, path):
        path = _path(path)
        profile = _read_json(path, "TARGET")
        if not isinstance(profile, dict):
            raise FileDataError("TARGET_SCHEMA", "The target profile must be a JSON object.")
        return {"status": "loaded", "path": str(path), "profile": profile, "read_only": True,
                "sha256": _sha256(path), "schema_validation": "json_object_only"}

    def save_session(self, path, state, references):
        path = _path(path)
        state = _json_state(state)
        references = _references(references)
        if str(path) in _protected_artifacts(references):
            raise FileDataError("SESSION_REFERENCE_OVERWRITE", "A session cannot overwrite one of its referenced files.")
        if path.suffix.lower() in DB_SUFFIXES | {".pth", ".pt", ".zip"}:
            raise FileDataError("SESSION_TYPE", "A session must not use a model, database, or bundle file extension.")
        document = {"format": SESSION_FORMAT, "schema_version": SESSION_VERSION,
                    "saved_at_utc": datetime.now(timezone.utc).isoformat(), "state": state,
                    "references": _relative_references(references, path.parent), "resume_jobs": False}
        _atomic_json(path, document, "SESSION_WRITE")
        return {"status": "saved", "path": str(path), "format": SESSION_FORMAT, "schema_version": SESSION_VERSION}

    def load_session(self, path):
        path = _path(path)
        document = _read_json(path, "SESSION")
        if (not isinstance(document, dict) or document.get("format") != SESSION_FORMAT
                or type(document.get("schema_version")) is not int or document["schema_version"] != SESSION_VERSION
                or "state" not in document or not isinstance(document.get("references"), dict)):
            raise FileDataError("SESSION_SCHEMA", "Expected optics-ui-session schema_version 1.")
        state = _json_state(document["state"])
        references = _references(document["references"], path.parent)
        warnings = [{"code": "MISSING_REFERENCE", "message": f"{key} needs to be relinked: {Path(value).name}."}
                    for key, value in references.items() if value and not Path(value).is_file()]
        return {"status": "loaded", "path": str(path), "format": SESSION_FORMAT, "schema_version": SESSION_VERSION,
                "state": state, "references": references, "stored_references": dict(document["references"]),
                "resume_jobs": False, "restored_state_is_settings_only": True, "warnings": warnings}

    def export_bundle(self, path, state, references):
        path = _path(path)
        state = _json_state(state)
        references = _references(references)
        if path.suffix.lower() != ".zip":
            raise FileDataError("BUNDLE_TYPE", "A portable bundle uses the .zip extension.")
        if str(path) in _protected_artifacts(references):
            raise FileDataError("REFERENCE_MISMATCH", "A bundle cannot overwrite a referenced file.")
        report_result = self.load_report(references["report_path"]) if references["report_path"] else None
        database = _path(references["database_path"]) if references["database_path"] else None
        if report_result:
            report_database = Path(report_result["database_path"])
            if database is not None and database != report_database:
                raise FileDataError("REFERENCE_MISMATCH", "The selected database differs from the database named by the report.")
            database = report_database
        temporary_zip = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".optics-bundle-", dir=path.parent) as staging_name:
                staging = Path(staging_name)
                project = staging / "project"
                project.mkdir()
                portable = dict.fromkeys(REFERENCE_KEYS)
                report = deepcopy(report_result["report"]) if report_result else None
                catalog = Path(report_result["material_catalog_path"]) if report_result and report_result["material_catalog_path"] else None
                database_copy = None
                if database is not None:
                    database_copy = project / database.name
                    _sqlite_snapshot(database, database_copy)
                    portable["database_path"] = str(database_copy)
                    if catalog is None:
                        with _readonly_database(database_copy) as connection:
                            catalog = _catalog_path({}, database, _metadata(connection))
                if catalog is not None:
                    if not catalog.is_file():
                        raise FileDataError("MISSING_MATERIAL_CATALOG", f"Material catalog is missing: {catalog.name}.")
                    catalog_copy = project / "materials" / catalog.name
                    catalog_copy.parent.mkdir(parents=True, exist_ok=True)
                    if catalog.suffix.lower() in DB_SUFFIXES:
                        _sqlite_snapshot(catalog, catalog_copy)
                    else:
                        shutil.copyfile(catalog, catalog_copy)
                    catalog_relative = catalog_copy.relative_to(project).as_posix()
                    if report is not None:
                        report["material_catalog"] = {"filename": catalog_relative}
                    if database_copy is not None:
                        copied = sqlite3.connect(database_copy)
                        try:
                            with copied:
                                if "metadata" in _tables(copied):
                                    copied.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('material_catalog_path',?)",
                                                   (catalog_relative,))
                        finally:
                            copied.close()
                if report_result:
                    model = Path(report_result["model_path"])
                    model_copy = project / model.name
                    shutil.copyfile(model, model_copy)
                    expected_hash = report["model"].get("sha256")
                    if expected_hash and _sha256(model_copy).lower() != expected_hash.lower():
                        raise FileDataError("MODEL_HASH_MISMATCH", "The model changed while the bundle was being prepared.")
                    report_copy = project / Path(report_result["report_path"]).name
                    _atomic_json(report_copy, report, "BUNDLE_WRITE")
                    portable["report_path"] = str(report_copy)
                    # Recheck the actual exported artifacts, not only the live
                    # originals inspected before snapshot/copy.
                    self.load_report(report_copy)
                if references["target_path"]:
                    target = Path(references["target_path"])
                    self.load_target(target)
                    target_copy = staging / "targets" / target.name
                    target_copy.parent.mkdir()
                    shutil.copyfile(target, target_copy)
                    portable["target_path"] = str(target_copy)
                session_name = "session.optics.json"
                self.save_session(staging / session_name, state, portable)
                members = sorted(item for item in staging.rglob("*") if item.is_file())
                manifest = {"format": "optics-ui-bundle", "schema_version": 1, "sqlite_snapshot": True,
                            "executed": False, "files": [{"path": item.relative_to(staging).as_posix(),
                            "sha256": _sha256(item), "size_bytes": item.stat().st_size} for item in members]}
                _atomic_json(staging / "bundle-manifest.json", manifest, "BUNDLE_WRITE")
                descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
                os.close(descriptor)
                temporary_zip = Path(name)
                files = sorted(item for item in staging.rglob("*") if item.is_file())
                with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for item in files:
                        archive.write(item, item.relative_to(staging).as_posix())
                with temporary_zip.open("rb+") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary_zip, path)
                temporary_zip = None
                names = [item.relative_to(staging).as_posix() for item in files]
            return {"status": "exported", "path": str(path), "files": names,
                    "session_path": session_name, "executed": False}
        except FileDataError:
            raise
        except (OSError, sqlite3.Error, zipfile.BadZipFile) as error:
            raise FileDataError("BUNDLE_WRITE", f"Could not export {path.name}; the previous bundle was not replaced.") from error
        finally:
            if temporary_zip is not None:
                temporary_zip.unlink(missing_ok=True)
