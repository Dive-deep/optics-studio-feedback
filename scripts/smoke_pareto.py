"""Actual Qt UI acceptance for DB Pareto. Uses an isolated synthetic test DB.

The original local demo is opened read-only and never modified. Fixture metric
values are fabricated solely to test PASS/NEAR/NG and 2D/3D UI behavior, not optics.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optics_ui import desktop
from optics_ui.services.files import FileDataService


def make_fixture(output):
    folder = Path(tempfile.mkdtemp(prefix="pareto-fixture-", dir=output))
    source = ROOT / "examples/local-demo"
    shutil.copyfile(source / "demo-model.pth", folder / "demo-model.pth")
    shutil.copyfile(source / "target.json", folder / "target.json")
    shutil.copytree(source / "materials", folder / "materials")
    database = folder / "demo-cases.sqlite"
    with closing(sqlite3.connect((source / database.name).resolve().as_uri() + "?mode=ro", uri=True)) as reader, reader:
        with closing(sqlite3.connect(database)) as writer, writer:
            reader.backup(writer)
    cases = FileDataService().candidate_data(database)["cases"]
    ready = {row["id"]: row for row in cases if row["comparison_ready"]}
    ids = ["D057_2", "D057_3", "D050_3", "D004_0"]
    assert all(name in ready for name in ids)
    assert len({ready[name]["cohort_key"] for name in ids}) == 1
    values = [(1.616, 24.96, 1.1), (1.648, 24.24, 1.3),
              (1.664, 24.72, 1.8), (1.7, 24, 2.4)]
    with closing(sqlite3.connect(database)) as connection, connection:
        for case_id, (diameter, fov, ratio) in zip(ids, values):
            connection.execute("UPDATE spot_summary SET rms_radius_mm_proxy=? WHERE design_id=? AND temperature_c=20 AND field_norm=1",
                               (diameter / 2000, case_id))
            connection.execute("UPDATE first_order_metrics SET horizontal_fov_deg=? WHERE design_id=? AND temperature_c=20",
                               (fov, case_id))
            for field, threshold in [(0, .4), (.8, .3)]:
                connection.execute("UPDATE mtf_samples SET mtf=? WHERE design_id=? AND temperature_c=20 AND field_norm=? AND frequency_lp_per_mm=6",
                                   (ratio * threshold, case_id, field))
    report = json.loads((source / "training-report.json").read_text(encoding="utf-8"))
    report["notes"].insert(0, "PARETO UI TEST FIXTURE: modified synthetic metrics, NOT optical performance validation.")
    (folder / "training-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"first": ids[0], "second": ids[1], "best": ids[2], "ng": ids[3],
            "report_path": str(folder / "training-report.json"),
            "target_path": str(folder / "target.json"),
            "source_report_path": str(source / "training-report.json")}


def main():
    output = ROOT / "artifacts/pareto-smoke"
    output.mkdir(parents=True, exist_ok=True)
    original = ROOT / "examples/local-demo/demo-cases.sqlite"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    fixture = make_fixture(output)
    (output / "fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    class ParetoRunner(desktop.SmokeRunner):
        SCRIPT = "window.__PARETO_FIXTURE__=" + json.dumps(fixture) + r""";
        (async()=>{
          const frontend=await window.__OPTICS_PARETO_SMOKE__(window.__PARETO_FIXTURE__);
          window.__DESKTOP_SMOKE_RESULT__={checks:[{name:'internal_origin',pass:location.origin==='optics-app://ui'}],frontend};
        })().catch(error=>{
          window.__DESKTOP_SMOKE_RESULT__={checks:[{name:'pareto_smoke_completed',pass:false}],
            error:String(error.message)};
        });"""

        def capture_compute_panel(self):
            self.evidence["compute_panel_capture"] = {"status": "hook_unavailable"}
            self.evidence["capture_scenario"] = "original_synthetic_db_exploratory_front_not_target_passing"
            self.finish()

    desktop.SmokeRunner = ParetoRunner
    code = desktop.main(["--smoke", "--output-dir", str(output),
                         "--smoke-report", fixture["report_path"], "--smoke-target", fixture["target_path"]])
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before, "Original demo DB changed"
    return code


if __name__ == "__main__":
    raise SystemExit(main())
