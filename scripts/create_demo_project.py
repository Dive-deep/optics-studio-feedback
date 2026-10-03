#!/usr/bin/env python3
"""Create a local UI demo from read-only SQLite snapshots.

The .pth is deliberately opaque demo text, never trained weights. Existing
generated files are reused unchanged. Edited/unknown output is not replaced
unless the user explicitly supplies --force.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optics_ui.services.files import FileDataService


DEFAULT_SOURCE = None  # Public developer tool requires an explicit source DB.
OUTPUT = ROOT / "examples/local-demo"
MANIFEST_NAME = "demo-manifest.json"
MODEL_BYTES = (
    b"OPTICS UI DEMO ARTIFACT\n"
    b"THIS FILE IS NOT TRAINED MODEL WEIGHTS.\n"
    b"It is opaque fixture data for file-selection and checksum tests only.\n"
    b"Do not load with torch.load, pickle, or an inference engine.\n"
)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + chr(10), encoding="utf-8")


def snapshot(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    writer = sqlite3.connect(destination)
    try:
        reader.execute("PRAGMA query_only=ON")
        reader.backup(writer)
        writer.execute("PRAGMA journal_mode=DELETE")
    finally:
        writer.close()
        reader.close()


def metadata(path):
    reader = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return dict(reader.execute("SELECT key,value FROM metadata"))
    finally:
        reader.close()


def default_targets():
    targets = []
    for field, threshold in ((0.0, 0.4), (0.8, 0.3)):
        for orientation in ("SAGITTAL", "TANGENTIAL"):
            targets.append({
                "id": f"mtf-{field:g}-{orientation.lower()}",
                "category": "mtf", "metric": "mtf", "frequency_lp_per_mm": 6,
                "field_norm": field, "orientation": orientation,
                "comparator": ">=", "value": threshold, "unit": "fraction", "required": True,
            })
    targets.extend([
        {"id": "spot-1f-rms-diameter", "category": "spot", "metric": "spot_rms_diameter",
         "field_norm": 1.0, "comparator": "close_to", "value": 1.6, "unit": "um", "required": True},
        {"id": "horizontal-full-fov", "category": "horizontal_fov", "metric": "horizontal_fov_full",
         "comparator": "close_to", "value": 24, "unit": "deg", "required": True},
    ])
    return {
        "profile_id": "local-ui-demo-targets-v1", "profile_version": 1,
        "read_only": True, "is_ui_example": True,
        "category_weights": {"mtf": 1, "spot": 1, "horizontal_fov": 1},
        "relative_tolerance": 0.05,
        "conditions_policy": {
            "prefer": "current_database_analysis_metadata",
            "display_defaults": {"temperature_c": 25, "wavelength_nm": 560},
            "fallback_does_not_recalculate_results": True,
        },
        "targets": targets,
        "notes": [
            "UI example JSON only; not a finalized backend target schema.",
            "MTF conditions share one category weight; four conditions do not make MTF four times heavier.",
            "Spot is RMS diameter near 1.6 um at normalized field 1.0.",
            "Horizontal FOV is the full 24 degree angle (plus/minus 12 degrees).",
            "Reference case D057_2 is not declared to pass these targets or be the current best candidate.",
        ],
    }


def verify(directory):
    service = FileDataService()
    report = service.load_report(directory / "training-report.json")
    case = service.load_case(report["database_path"], "D057_2")
    target = service.load_target(directory / "target.json")
    session = service.load_session(directory / "demo.optics.json")
    if report["training_summary"]["status"] != "unavailable":
        raise RuntimeError("The demo must not claim an actual training membership.")
    if report["model_deserialized"] or case["relative_illumination"] is not None:
        raise RuntimeError("The demo contract changed unexpectedly.")
    if not case["ui_compatible"] or not all(surface["a12"] is None for surface in case["surfaces"]):
        raise RuntimeError("The reference case is not compatible with the demo UI.")
    if session["resume_jobs"] or not target["read_only"]:
        raise RuntimeError("The demo must restore settings only and preserve read-only targets.")
    return {
        "report_path": report["report_path"], "target_path": target["path"],
        "session_path": str((directory / "demo.optics.json").resolve()),
        "bundle_path": str((directory / "demo-bundle.zip").resolve()),
        "database_path": report["database_path"], "model_path": report["model_path"],
        "case_id": case["id"], "source": case["origin"],
        "temperature_c": case["temperature_c"],
        "wavelengths_nm": case["analysis_conditions"]["wavelengths_nm"],
        "training_membership": "absent", "model_is_trained_weights": False,
    }


def existing_is_unchanged(directory, source_digest):
    manifest_path = directory / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("format") != "optics-ui-demo-manifest"
                or manifest.get("generator_version") != 1
                or manifest.get("source_database_sha256") != source_digest):
            return False
        expected = set()
        for entry in manifest["files"]:
            relative = Path(entry["path"])
            if relative.is_absolute() or ".." in relative.parts:
                return False
            path = directory / relative
            if not path.is_file() or digest(path) != entry["sha256"]:
                return False
            expected.add(relative.as_posix())
        actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
        return actual == expected | {MANIFEST_NAME}
    except (OSError, ValueError, KeyError, TypeError):
        return False


def generate(source=DEFAULT_SOURCE, destination=OUTPUT, *, force=False):
    if source is None:
        raise ValueError("Provide --source-db explicitly; the bundled demo is already ready to use.")
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise RuntimeError(f"Source database not found: {source}")
    if destination == ROOT or destination == source.parent or destination in source.parents:
        raise RuntimeError("The demo output must not replace the project or source directory.")
    source_before = digest(source)
    if destination.exists() and not force:
        if existing_is_unchanged(destination, source_before):
            return {"status": "unchanged", **verify(destination)}
        raise RuntimeError("Demo output already exists or was edited; nothing was overwritten. Use --force to regenerate this demo directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".local-demo-build-", dir=destination.parent))
    previous = None
    try:
        database = staging / "demo-cases.sqlite"
        snapshot(source, database)
        source_metadata = metadata(database)
        source_catalog = source_metadata.get("material_catalog_path")
        if not source_catalog:
            raise RuntimeError("The source DB does not declare its material catalog.")
        catalog = Path(source_catalog)
        if not catalog.is_absolute():
            catalog = source.parent / catalog
        catalog = catalog.resolve()
        if not catalog.is_file():
            raise RuntimeError(f"Material catalog is missing: {catalog}")
        catalog_before = digest(catalog)
        catalog_relative = Path("materials") / catalog.name
        catalog_copy = staging / catalog_relative
        if catalog.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
            snapshot(catalog, catalog_copy)
        else:
            catalog_copy.parent.mkdir(parents=True)
            shutil.copyfile(catalog, catalog_copy)
        logical_id = source_metadata.get("database_id", source_metadata.get("dataset_id", "local-ui-demo-optics-v1"))
        writer = sqlite3.connect(database)
        try:
            with writer:
                if not source_metadata.get("database_id") and not source_metadata.get("dataset_id"):
                    writer.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('database_id',?)", (logical_id,))
                writer.execute("UPDATE metadata SET value=? WHERE key='material_catalog_path'", (catalog_relative.as_posix(),))
        finally:
            writer.close()
        model = staging / "demo-model.pth"
        model.write_bytes(MODEL_BYTES)
        target = staging / "target.json"
        write_json(target, default_targets())
        database_report = {"filename": database.name, "id": logical_id}
        if source_metadata.get("schema_version"):
            database_report["schema_version"] = source_metadata["schema_version"]
        report = {
            "report_version": 1, "demo_only": True,
            "model": {"filename": model.name, "id": "UI-FIXTURE-NOT-TRAINED",
                      "sha256": digest(model), "artifact_kind": "opaque_ui_fixture", "trained_weights": False},
            "database": database_report,
            "material_catalog": {"filename": catalog_relative.as_posix()},
            "suggested_case_id": "D057_2",
            "target_profile": {"filename": target.name, "sha256": digest(target)},
            "provenance": {
                "data_origin": "SYNTHETIC_MATH_PROXY", "zemax_executed": False,
                "source_dataset_name": source_metadata.get("dataset_name"),
                "source_dataset_version": source_metadata.get("dataset_version"),
                "source_database_sha256": source_before,
            },
            "notes": [
                "UI FILE-LOADING DEMO ONLY. demo-model.pth is plain fixture bytes, not trained surrogate weights.",
                "The copied optical database contains synthetic mathematical proxies, not Zemax measurements.",
                "Training membership is deliberately absent. Do not infer trained counts from family_split.",
                "D057_2 is a reference case for UI loading, not a best or target-passing claim.",
            ],
        }
        report_path = staging / "training-report.json"
        write_json(report_path, report)
        service = FileDataService()
        loaded_report = service.load_report(report_path)
        loaded_case = service.load_case(database, "D057_2")
        references = {"report_path": str(report_path), "database_path": str(database), "target_path": str(target)}
        state = {"selected_case_id": "D057_2", "demo_only": True,
                 "analysis_conditions": loaded_case["analysis_conditions"],
                 "llm_draft": "", "view_mode": "3d"}
        service.save_session(staging / "demo.optics.json", state, references)
        exported = service.export_bundle(staging / "demo-bundle.zip", state, references)
        if loaded_report["training_summary"]["trained_count"] is not None or exported["executed"]:
            raise RuntimeError("Demo generation must not invent execution or training.")
        (staging / "README.md").write_text(
            "# Local UI demonstration files\n\n"
            "Open training-report.json in the app and target.json with the Targets file picker.\n"
            "Use the app Save/Open controls to create and restore a full UI session.\n"
            "`demo.optics.json` and `demo-bundle.zip` are minimal file-service fixtures,\n"
            "not complete UI sessions. Do not select `demo.optics.json` in the UI Open dialog.\n\n"
            "**demo-model.pth is NOT trained model weights.** It contains opaque demo text.\n"
            "The optical database is a SQLite snapshot of the synthetic sample DB. Zemax was not executed.\n"
            "No training membership is supplied and no trained-case count should be inferred.\n"
            "D057_2 is a reference case, not a claimed best or target-passing design.\n"
            "A12 and Relative illumination remain unavailable.\n\n"
            "Recreate with scripts/create_demo_project.py. Existing unchanged output is reused;\n"
            "edited or unrecognized output is preserved unless --force is explicitly supplied.\n"
            "Regeneration is reproducible in content/behavior; session/export timestamps can change.\n",
            encoding="utf-8",
        )
        if digest(source) != source_before or digest(catalog) != catalog_before:
            raise RuntimeError("Source files changed during generation; output was not published.")
        manifest = {
            "format": "optics-ui-demo-manifest", "schema_version": 1, "generator_version": 1,
            "source_database_sha256": source_before, "source_catalog_sha256": catalog_before,
            "model_is_trained_weights": False, "training_membership": "absent",
            "files": [{"path": path.relative_to(staging).as_posix(), "sha256": digest(path)}
                      for path in sorted(staging.rglob("*")) if path.is_file()],
        }
        write_json(staging / MANIFEST_NAME, manifest)
        verify(staging)
        if destination.exists():
            previous = Path(tempfile.mkdtemp(prefix=".local-demo-previous-", dir=destination.parent))
            previous.rmdir()
            os.replace(destination, previous)
        try:
            os.replace(staging, destination)
        except BaseException:
            if previous is not None:
                os.replace(previous, destination)
                previous = None
            raise
        if previous is not None:
            shutil.rmtree(previous)
            previous = None
        return {"status": "created", **verify(destination)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True, help="Explicit read-only source DB; normal users do not regenerate the bundled demo.")
    parser.add_argument("--force", action="store_true", help="Replace the generated local-demo directory even if edited.")
    arguments = parser.parse_args()
    try:
        result = generate(arguments.source_db, force=arguments.force)
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
