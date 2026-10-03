# 공개 배포 검증 기록

## v1.1.0 — 2026-10-04

이번 버전은 네이티브 작업 메뉴·Explorer·파라미터 편집창·Sensitivity·독립 MTF/Spot 창·세션 배치 복원·종료 안내를 포함합니다. 이전 0.x 테스트 수와 v1.1 결과를 혼합하지 않습니다.

| 환경/검사 | 현재 기록 |
| --- | --- |
| 원본 v1.1 개발 검증 | 2026-10-03 macOS / CPython 3.12.14 / PySide6·Qt 6.11.2. Python 311개, Node 195개 통과. 실제 workbench 통합 76개, 독립 분석창 33개 통과. |
| 이번 공개 저장소의 단위·자산·배포 검사 | 2026-10-04 macOS / Python 3.12 / PySide6 6.11.2에서 Python **325개**, Node **195개** 통과. 실제 작업대 **76개**, 독립 MTF/Spot 창 **33개** 통과. 배포 검사에는 한글·공백 경로로 실제 ZIP 압축 해제 후 native 모듈 import가 포함됩니다. JavaScript 오류·외부 WebEngine 요청 0건. |
| 이번 공개 커밋의 Windows CI | 실행 결과 확인 전. [Windows workflow](https://github.com/Dive-deep/optics-studio-feedback/actions/workflows/windows-check.yml)에서 커밋별 결과를 확인합니다. |
| 실제 Windows 11 PC | GPU·DPI·OS 파일 대화상자·드래그 검증은 TBU입니다. |

초기 Windows CI에서 테스트 fixture의 SQLite 연결 종료 누락, 플랫폼 줄바꿈 가정, 작은 화면에서 렌즈 선택 행이 창의 최소 너비를 강제하는 문제를 확인했습니다. 연결의 명시적 종료와 CRLF 보존 검사를 적용하고 렌즈 선택 행에 가로 스크롤을 추가했습니다. 테스트를 skip하거나 화면 크기 검사를 완화하지 않았습니다. 이어 실제 앱 검사에서 Git 자동 줄바꿈으로 opaque 데모 모델의 checksum이 바뀌는 문제를 재현하고, 공개 저장소의 binary/LF 속성과 실제 Windows식 Git checkout 회귀 검사를 복원했습니다.

표준 CPython 3.10–3.14 x64를 대상으로 하고 3.12를 권장합니다. 런처와 패키지 정책은 이 범위를 사용하지만 지원 정책 자체가 모든 기기의 실행 성공을 보증하지는 않습니다.

GUI 자동 검사는 파일 대화상자를 명시적인 테스트 경로로 대체합니다. offscreen 위젯 검사, 실제 Qt 앱 검사, Windows Server CI, 물리 Windows 11 기기 검사를 구분합니다. surrogate/Zemax/학습/자동 반복/LLM 실행과 광학 정확도는 이번 검증의 대상이 아닙니다.

재현 명령:

```powershell
python -m pip install -r requirements.txt
python scripts/build_ui.py
python -m unittest discover -s tests -v
node --test tests/*.cjs
python scripts/smoke_workbench.py
python scripts/smoke_analysis_windows.py
python scripts/build_feedback_release.py
```

GUI smoke에는 데스크톱 세션이 필요합니다. 일반 실행기에는 CI 전용 그래픽 설정을 강제로 넣지 않으며 Chromium sandbox를 끄지 않습니다.

---

# 이전 0.x 피드백 배포 검증 기록

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
