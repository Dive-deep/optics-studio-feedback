# Optics Studio — Windows 사용자 피드백 버전

**v1.1.0 · 2026-10-04 · 사전 공개 버전**

결상광학계를 검토하는 **로컬 Python/PySide6 데스크톱 앱**입니다. 왼쪽 작업 메뉴, 실제 파일 Explorer, 넓은 파라미터 편집창, 독립 MTF/Spot 분석창을 제공하며 사용자의 화면 구성과 조작 흐름에 대한 피드백을 받습니다. 서버 호스팅은 필요하지 않습니다.

**현재 동작:** 로컬 report/DB/목표 파일 읽기, 렌즈 3D/2D와 로컬 기하 광선 표시, 파라미터 편집, 저장된 결과 검토, DB Pareto·후보 적용, 외부 Sobol 보고서 표시, 세션 저장·복원·ZIP 내보내기.

**연결 전(TBU):** 새 설계의 AI 예측·신뢰도, Zemax 실행, 모델 학습, 자동 설계 반복, DB tailoring 계산, LLM 서비스 연결. 파라미터를 바꿔도 MTF·Spot 등 저장된 결과가 새 예측으로 바뀌지는 않습니다.

## 다운로드와 설치

1. [v1.1.0 Release](https://github.com/Dive-deep/optics-studio-feedback/releases/tag/v1.1.0)에서 **`Optics-Studio-v1.1.0.zip`**을 내려받아 전체를 압축 해제합니다. 이전 배포도 [Releases](https://github.com/Dive-deep/optics-studio-feedback/releases)에 남아 있습니다. 개발 소스는 **Code → Download ZIP**으로 받을 수 있습니다.
2. **Windows 11 x64 + 표준 CPython 3.10–3.14 64비트**가 대상입니다. **Python 3.12는 권장이고 필수는 아닙니다. 3.13도 지원 정책에 포함됩니다.** PyPy와 free-threaded 빌드는 지원하지 않습니다.
3. 압축을 푼 폴더에서 PowerShell을 열고 설치합니다.

```powershell
py -3 -m pip install -r requirements.txt
py -3 launch.py --check
py -3 launch.py
```

설치 후에는 **`run_windows.cmd`를 더블클릭**해도 됩니다. Python을 여러 개 설치했다면 설치와 실행에 같은 인터프리터를 사용하세요. 예를 들어 3.13은 위 명령의 `py -3`을 모두 `py -3.13`으로 바꿉니다. `py` 명령이 없다면 해당 Python의 `python` 명령을 사용합니다.

Python·가상환경·PySide6는 ZIP에 묶지 않으며 실행기가 자동 설치하지 않습니다. 화면에 필요한 로컬 JavaScript·아이콘과 라이선스는 포함합니다. 사용자 실행에 Node.js, PyTorch, CUDA, Zemax는 필요하지 않습니다.

## 처음 실행하면

1. 모델 선택 영역의 **Browse report**에서 `examples/local-demo/training-report.json`을 선택합니다. `.pth` 자체를 선택하는 방식이 아닙니다.
2. **Targets · Read only → Load target JSON**에서 `examples/local-demo/target.json`을 선택합니다.
3. **Workspace → Configure parameters**에서 렌즈·면·System 변수를 함께 검토하고 **Apply**합니다.
4. MTF와 Spot의 **Pop up**을 눌러 각각 별도 창으로 열고 확대·이동·좌표를 확인합니다.
5. **Best candidates → 미달 포함 탐색**에서 저장된 DB 후보를 비교합니다.
6. **Save**로 현재 설계와 창 배치를 저장합니다. 상단 **Open**은 이 작업 세션을 여는 버튼입니다.

데모 DB는 **합성 데이터**, 모델 파일은 **연결 검사용 dummy**입니다. 실제 학습 모델이나 Zemax 결과가 아닙니다. 파일 이름과 상대 위치를 유지하세요. `demo.optics.json`은 내부 최소 fixture이므로 시작 세션으로 선택하지 마세요. 현재 예시 목표에는 허용 후보가 없을 수 있으며, 이를 오류나 실제 광학 성능의 결론으로 해석하지 않습니다.

상세 설명은 [사용자 안내](docs/user-guide.md), [온라인 웹 가이드](https://dive-deep.github.io/optics-studio-feedback/)에서 확인하세요. 오프라인 가이드는 `guide/dist/index.html`을 브라우저로 엽니다. 가이드는 설명 페이지이며 설계 작업을 실행하지 않습니다.

## v1.1 화면

- **왼쪽 메뉴:** Workspace, Explorer, Update model, Add Zemax Sim, Auto design, DB tailoring. 작업 페이지가 코드 탭으로 쌓이지 않습니다.
- **Explorer:** 실제 폴더를 열어 여러 코드 파일을 읽기 전용 탭에서 봅니다. 파일 탭을 이동·닫을 수 있고 설치된 VS Code로 열 수 있습니다.
- **Configure parameters:** 넓은 별도 창에서 검색·그룹 필터와 Min/Current/Max를 사용합니다. Apply/Cancel로 초안 반영을 결정합니다.
- **Sensitivity:** Workspace에서 외부 Sobol S1/ST 보고서를 읽습니다. 계산은 TBU이며 없는 값은 `—`로 표시합니다.
- **MTF/Spot:** 두 nonmodal 창을 함께 열고 Workspace를 계속 조작합니다.
- **오른쪽 LLM panel:** 버튼 또는 Ctrl+Alt+B로 열고 닫는 초안 영역입니다. 대화 응답·인증·작업 실행은 연결 전입니다.
- **저장·종료:** 창 배치·분석창·패널 상태를 세션에 저장하며 미저장 변경이 있으면 Save / Discard / Cancel을 제공합니다.

[변경 이력](CHANGELOG.md)과 [현재 제한](KNOWN_LIMITATIONS.md)도 함께 확인하세요.

## 실행 문제와 피드백

`py -3 launch.py --check`는 Python·Qt·필수 화면 파일을 검사하며 GUI나 backend 작업을 시작하지 않습니다. 설치와 실행 Python이 다르면 패키지를 찾지 못할 수 있습니다. CMD는 `OPTICS_PYTHON` → 활성 가상환경 → `py -3` → PATH의 `python` 순으로 선택합니다. 별도 경로를 지정하려면 CMD에서 `set "OPTICS_PYTHON=C:\path\to\python.exe"` 후 실행하세요.

WebGL2를 사용할 수 없는 환경에서는 설명과 함께 2D 단면으로 전환하고 3D 버튼을 비활성화합니다. 화면이 비어 있으면 전체 압축 해제 여부와 `--check` 결과를 먼저 확인하세요. CUDA GPU가 없어도 UI를 사용할 수 있습니다.

[Issues → New issue](https://github.com/Dive-deep/optics-studio-feedback/issues/new/choose)에서 **실행 오류** 또는 **사용성 피드백**을 선택해주세요. 버전, Windows/Python 버전, 화면 해상도·배율, 수행 순서와 기대/실제 결과를 적어주세요. 공개 게시물이므로 업무 데이터·토큰·개인정보는 제외합니다. GitHub 로그인이 어렵다면 웹 가이드의 양식을 복사해 담당자에게 전달하면 됩니다.

## 개발과 검증

이 저장소의 공개 작업 브랜치는 `feedback/windows-preview`입니다. `main`과 이전 Release는 과거 기준점으로 보존합니다. 배포는 실행 가능한 소스이며 `.exe` 설치 프로그램을 제공하지 않습니다.

```powershell
python -m pip install -r requirements.txt
python scripts/build_ui.py
python -m unittest discover -s tests -v
node --test tests/*.cjs
python scripts/smoke_workbench.py
python scripts/smoke_analysis_windows.py
python scripts/build_feedback_release.py
```

아래 개발 명령은 저장소 전체를 clone하거나 Code → Download ZIP으로 받은 개발 소스에서 실행합니다. Releases의 사용자용 ZIP에는 테스트·개발 빌더를 넣지 않습니다.

Node.js는 개발 검사용입니다. GUI smoke에는 데스크톱 세션이 필요하며 파일 선택은 명시적인 테스트 경로로 대체합니다. [검증 기록](VALIDATION.md)에서 버전과 실행 환경을 구분하고, [Windows CI](https://github.com/Dive-deep/optics-studio-feedback/actions/workflows/windows-check.yml)에서 해당 커밋의 결과를 확인하세요. 이번 v1.1 실행 코드는 [Windows Python 3.10–3.14 CI](https://github.com/Dive-deep/optics-studio-feedback/actions/runs/37134834927)를 모두 통과했습니다. 실행 코드 커밋과 상세 검사 수는 검증 기록에 있습니다. 실제 Windows 11의 DPI·GPU·OS 파일 대화상자 검증은 별도입니다.

배포 담당자는 [PUBLISHING.md](PUBLISHING.md)를 참고하세요. 별도의 프로젝트 오픈소스 라이선스를 선언하지 않았습니다. 외부 자산의 라이선스와 데이터 출처는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
