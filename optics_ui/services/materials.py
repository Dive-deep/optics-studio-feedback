"""Exact, read-only catalog samples for local ray visualization.

No interpolation, dispersion evaluation, nd substitution, or guessed indices.
Unavailable catalog data is diagnostic metadata and must not prevent case
loading. Each call owns its SQLite connection so desktop workers can use it.
"""

import math
from pathlib import Path
import sqlite3


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _positive(value):
    return _finite(value) and value > 0


def _condition_selection(conditions):
    conditions = conditions if isinstance(conditions, dict) else {}
    assumed = conditions.get("assumed_fields", [])
    if not isinstance(assumed, (list, tuple)):
        assumed = []
    temperature = conditions.get("temperature_c")
    if _finite(temperature):
        temperature_source = conditions.get("temperature_source") or "analysis_metadata"
    elif temperature is None:
        temperature, temperature_source = 25, "display_default"
    else:
        temperature, temperature_source = None, "invalid_metadata"
    if "temperature_c" in assumed or temperature_source in ("display_default", "display-default"):
        temperature_source = "display_default"

    primary = conditions.get("primary_wavelength_nm")
    spectrum = conditions.get("wavelengths_nm")
    if _positive(primary):
        wavelength, wavelength_source = primary, "primary_wavelength_nm"
    elif isinstance(spectrum, (list, tuple)) and any(_positive(value) for value in spectrum):
        wavelength = next(value for value in spectrum if _positive(value))
        wavelength_source = "first_available_wavelength"
    elif _positive(conditions.get("wavelength_nm")):
        wavelength, wavelength_source = conditions["wavelength_nm"], "wavelength_nm"
    else:
        supplied = any(conditions.get(key) not in (None, [], "")
                       for key in ("primary_wavelength_nm", "wavelengths_nm", "wavelength_nm"))
        wavelength, wavelength_source = (None, "invalid_metadata") if supplied else (560, "display_default")
    if (conditions.get("wavelength_source") in ("display_default", "display-default")
            or any(key in assumed for key in ("wavelengths_nm", "wavelength_nm", "primary_wavelength_nm"))):
        wavelength_source = "display_default"
    return wavelength, temperature, {"wavelength": wavelength_source, "temperature": temperature_source}


def load_ray_indices(*, database_path, database_metadata, material_ids, analysis_conditions):
    """Return exact samples for every requested selectable material ID.

    status is available when all requested IDs have exact valid rows, partial
    when some have them, and unavailable when none do. Missing keys must never
    be replaced with a guessed n by the caller.
    """
    requested = list(dict.fromkeys(value for value in material_ids if isinstance(value, str) and value))
    wavelength, temperature, sources = _condition_selection(analysis_conditions)
    metadata = database_metadata if isinstance(database_metadata, dict) else {}
    reference = metadata.get("material_catalog_path")
    result = {
        "status": "unavailable", "wavelength_nm": wavelength, "temperature_c": temperature,
        "indices": {}, "missing_material_ids": requested.copy(),
        "provenance": {"lookup": "exact_sample", "catalog_reference": reference,
                       "catalog_path": None, "condition_sources": sources,
                       "catalog_metadata": {}, "materials": {}},
        "warnings": [],
    }

    def warning(code, message, material_id=None):
        item = {"code": code, "message": message}
        if material_id is not None:
            item["material_id"] = material_id
        result["warnings"].append(item)

    if not _positive(wavelength) or not _finite(temperature):
        warning("MATERIAL_INDEX_CONDITIONS", "Valid wavelength and temperature metadata are required for an exact index lookup.")
        return result
    if not requested:
        warning("MATERIAL_INDEX_NO_MATERIALS", "No selectable material IDs were supplied.")
        return result
    if not isinstance(reference, str) or not reference.strip():
        warning("MATERIAL_CATALOG_REFERENCE_MISSING", "The database does not reference a material catalog.")
        return result
    connection = None
    try:
        catalog = Path(reference).expanduser()
        if not catalog.is_absolute():
            catalog = Path(database_path).resolve().parent / catalog
        catalog = catalog.resolve()
        result["provenance"]["catalog_path"] = str(catalog)
        if not catalog.is_file():
            warning("MATERIAL_CATALOG_MISSING", f"Material catalog is missing: {catalog.name}.")
            return result
        connection = sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(refractive_index_samples)")}
        required = {"material_id", "wavelength_nm", "temperature_c", "refractive_index"}
        if not required.issubset(columns):
            warning("MATERIAL_CATALOG_SCHEMA", "The catalog has no compatible refractive_index_samples table.")
            return result
        metadata_columns = {row[1] for row in connection.execute("PRAGMA table_info(metadata)")}
        if {"key", "value"}.issubset(metadata_columns):
            result["provenance"]["catalog_metadata"] = dict(connection.execute("SELECT key,value FROM metadata"))
        placeholders = ",".join("?" for _ in requested)
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM refractive_index_samples WHERE wavelength_nm=? AND temperature_c=? "
            f"AND material_id IN ({placeholders})",
            [wavelength, temperature, *requested],
        )]
        for material_id in requested:
            matches = [row for row in rows if row["material_id"] == material_id]
            if not matches:
                warning("MATERIAL_INDEX_MISSING",
                        f"No exact index sample for {material_id} at {wavelength:g} nm / {temperature:g} C.",
                        material_id)
                continue
            if len(matches) != 1:
                warning("MATERIAL_INDEX_AMBIGUOUS", f"Multiple exact index rows exist for {material_id}.", material_id)
                continue
            row = matches[0]
            if not _positive(row["refractive_index"]):
                warning("MATERIAL_INDEX_INVALID", f"The exact refractive-index value is invalid for {material_id}.", material_id)
                continue
            result["indices"][material_id] = row["refractive_index"]
            result["provenance"]["materials"][material_id] = {
                "n_model_id": row.get("n_model_id"), "n_is_proxy": row.get("n_is_proxy"),
                "is_extrapolated": row.get("is_extrapolated"), "source_quality": row.get("source_quality"),
            }
            if row.get("is_extrapolated"):
                warning("MATERIAL_INDEX_EXTRAPOLATED", f"The stored exact-condition sample is marked extrapolated for {material_id}.", material_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        result["indices"] = {}
        result["provenance"]["materials"] = {}
        warning("MATERIAL_CATALOG_READ", f"Material index lookup is unavailable: {type(error).__name__}.")
    finally:
        if connection is not None:
            connection.close()
    result["missing_material_ids"] = [value for value in requested if value not in result["indices"]]
    if result["indices"]:
        result["status"] = "partial" if result["missing_material_ids"] else "available"
    return result
