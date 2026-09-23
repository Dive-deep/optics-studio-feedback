# Feedback snapshot validation

## Python compatibility update — 0.1.0-feedback.2 / 2026-09-23

Python 3.12 is recommended, not mandatory. Runtime guards and packaging metadata use one supported range: standard CPython 3.10–3.14 x64. The upper/lower limits follow [PySide6 6.11.2 metadata](https://pypi.org/project/PySide6/6.11.2/), not an arbitrary preference for 3.12. Free-threaded builds cannot use the pinned stable-ABI wheels.

The Windows workflow runs separate jobs for 3.10, 3.11, 3.12, 3.13 and 3.14, each including dependency installation, launcher selection, all unit tests, actual Qt 3D/file/session smoke and Pareto smoke. [Current matrix results](https://github.com/Dive-deep/optics-studio-feedback/actions/workflows/windows-check.yml). [Run 35804703019](https://github.com/Dive-deep/optics-studio-feedback/actions/runs/35804703019) passed all five versions on release commit `40c3fff2c8e86fc314f72d27af7aeb6f9bb98e23`: 139 Python unit tests plus one platform-only skip, 140 JavaScript tests, 23 actual desktop checks and 16 Pareto checks per version. JavaScript errors and external requests were zero. The public ZIP was built by the Python 3.13 Windows job.

Dependency errors print an install command for the currently executing Python. The CMD no longer forces `py -3.12`; an explicitly selected interpreter and an existing activated virtual environment take priority. No environment is created or installed automatically.

## Original feedback.1 validation record

2026-09-22 · isolated Windows source preview and static user guide.

## Windows CI passed

[Verified run 35732824991](https://github.com/Dive-deep/optics-studio-feedback/actions/runs/35732824991), runtime commit `55bf20b254dceb279559b932d49a80d81752b515`.

Host: Windows Server 2025 x64, Python 3.12.10, PySide6 / Qt 6.11.2.

- Dependency install, UTF-8 asset rebuild, launcher preflight: passed.
- Actual CMD launcher from a different working directory, with Korean characters and spaces in the source path: passed.
- Python: 133 collected, **132 passed / 1 skipped**. The skip is a POSIX-only literal-backslash filename test; backslash already denotes a directory separator on Windows.
- JavaScript: **140 passed**, including seven WebGL-unavailable state checks.
- Actual Qt desktop: **23 checks passed**, including successful 3D initialization, native Python file services, Save/Open/Export, ray and Stop state restoration.
- Pareto desktop: **16 checks passed**, including actual DB loading, 2D/3-objective distinction, apply/undo, stale response protection and session settings.
- Both desktop runs recorded **0 JavaScript errors and 0 external requests**. 1280×720 and 1920×1080 content captures were saved. A rendered three-lens Windows screenshot was inspected.

The CI host has a software graphics adapter. Its workflow requests `--use-gl=angle --use-angle=swiftshader`; the actual browser reports `ANGLE (Microsoft, Microsoft Basic Render Driver ... Direct3D11 ...)`. We record the observed renderer rather than infer a physical GPU from the request. Chromium sandbox protections remain enabled. Qt documents backend selection through `QTWEBENGINE_CHROMIUM_FLAGS`: [Qt WebEngine graphics configuration](https://doc.qt.io/qt-6/qtwebengine-features.html#changing-the-graphics-api-backend-in-chromium).

The ordinary user launcher does not force these CI graphics flags. On unsupported WebGL2 systems the application keeps the 2D section visible, displays a persistent explanation and disables the unavailable 3D toggle, including after case or session restoration. It does not conceal unexpected renderer errors or turn a failed 3D test into a pass.

## Local Mac checks

- Python 3.12 / PySide6 6.11.2: **133 unit checks passed** (existing 114, launcher 11, release builder 8).
- JavaScript: **140 passed**. Launcher, archive and graphics fallback tests were written before their implementations.
- Actual Qt application: **23 checks passed** after the graphics fallback change; normal 3D remained visible, JavaScript errors and external requests were zero.
- A source-only ZIP extracted into a new Korean-and-space path passed the earlier 22 file/scene/Compute checks. The final archive builder checks required files, exclusions, symlink/path boundaries, CRC, SHA-256 and identical CMD CRLF bytes from LF/CRLF source input.
- Guide: local links and anchors resolve; five actual application screenshots are present; JavaScript syntax passes. No external runtime, telemetry or form submission code is used.

## Scope and remaining checks

Automatic desktop tests replace OS file choosers with explicit test paths. Windows Server CI is **not** a physical Windows 11 workstation test. Native chooser/drop, display scaling, hardware GPU variants and accessibility review remain TBU. User-facing `py` discovery is separate from the CI's explicit Python path check.

Surrogate prediction, Zemax, training, automated design, Claude execution and optical-performance validation remain outside this release. The included DB is synthetic and the model is an opaque fixture.

The primary development directory was not edited. Baseline hashes confirmed all 72 copied source files remained unchanged at separation. All Windows fixes, packaging and guide work stay in this independent repository on `feedback/windows-preview`.
