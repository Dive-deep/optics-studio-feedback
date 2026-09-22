# Local UI demonstration files

Open training-report.json in the app and target.json with the Targets file picker.
Use the app Save/Open controls to create and restore a full UI session.
`demo.optics.json` and `demo-bundle.zip` are minimal file-service fixtures,
not complete UI sessions. Do not select `demo.optics.json` in the UI Open dialog.

**demo-model.pth is NOT trained model weights.** It contains opaque demo text.
The optical database is a SQLite snapshot of the synthetic sample DB. Zemax was not executed.
No training membership is supplied and no trained-case count should be inferred.
D057_2 is a reference case, not a claimed best or target-passing design.
A12 and Relative illumination remain unavailable.

Recreate with scripts/create_demo_project.py. Existing unchanged output is reused;
edited or unrecognized output is preserved unless --force is explicitly supplied.
Regeneration is reproducible in content/behavior; session/export timestamps can change.
