"""Run the actual local desktop app's opt-in acceptance mode and check evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/desktop-smoke")
parser.add_argument("--smoke-report", type=Path, help="Replace native report dialog with this explicit test path")
parser.add_argument("--smoke-target", type=Path, help="Replace native target dialog with this explicit test path")
args = parser.parse_args()
output = args.output_dir.resolve()
output.mkdir(parents=True, exist_ok=True)
# Windows CI exercises the distribution launcher as well as the actual desktop.
# Mac remains a development-only native host, not Windows validation.
entry = [str(ROOT / "launch.py")] if sys.platform == "win32" else ["-m", "optics_ui"]
command = [sys.executable, *entry, "--smoke", "--output-dir", str(output)]
if args.smoke_report:
    command.extend(["--smoke-report", str(args.smoke_report.resolve())])
if args.smoke_target:
    command.extend(["--smoke-target", str(args.smoke_target.resolve())])
with (output / "runtime.log").open("w", encoding="utf-8") as log:
    completed = subprocess.run(command, cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, timeout=70)
report_path = output / "desktop-app.json"
if not report_path.is_file():
    print("Desktop evidence was not generated. See", output / "runtime.log")
    raise SystemExit(completed.returncode or 1)
report = json.loads(report_path.read_text(encoding="utf-8"))
assert completed.returncode == 0 and report["passed"], "Desktop acceptance checks failed"
assert report["dialogs_stubbed"] == bool(args.smoke_report or args.smoke_target), "Dialog test mode was not recorded accurately"
assert len(report["captures"]) == 2 and all(item["saved"] for item in report["captures"]), "Missing desktop captures"
assert all(item["actual_content_size"] == item["requested_content_size"] for item in report["captures"]), "Unexpected content dimensions"
print("Desktop app smoke PASS:", report_path)
