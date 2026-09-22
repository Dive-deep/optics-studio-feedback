# Optics Studio — Windows 사용자 피드백 버전

**0.1.0-feedback.1 · 2026-09-22**

결상광학계 설계 UI를 직접 써 보고 화면 구성과 사용 흐름에 대한 의견을 받기 위한 독립 스냅샷입니다. 메인 개발 프로젝트와 분리되어 있으며 `feedback/windows-preview` 브랜치에서 관리합니다.

**현재 동작:** 파일·DB 읽기, 파라미터 편집, 3D/2D·로컬 광선, 저장 결과 확대, DB Pareto, 후보 적용·되돌리기, 세션 저장·복원·ZIP 내보내기.

**TBU:** 편집한 설계의 AI 예측·신뢰도, Zemax 실행, 모델 학습, 자동 설계 반복, Claude 연결. 파라미터 편집 후 MTF·Spot·NA·FOV는 기존 참조 결과를 유지합니다.

## 다운로드와 시작

1. [GitHub Releases](https://github.com/Dive-deep/optics-studio-feedback/releases)에서 `Optics-Studio-Feedback-0.1.0-feedback.1.zip`을 내려받아 모두 압축 해제합니다. Releases가 아직 없다면 **Code → Download ZIP**으로 `feedback/windows-preview` 브랜치를 내려받습니다.
2. **Windows 11 x64 + Python 3.12 64비트**를 사용합니다. Python이 이미 설치되어 있다면 같은 환경을 그대로 사용합니다.
3. 압축을 푼 폴더에서 터미널을 열고 의존성을 설치합니다.

```powershell
py -3.12 -m pip install -r requirements.txt
```

4. **`run_windows.cmd`를 더블클릭**합니다. 또는 같은 터미널에서:

```powershell
py -3.12 launch.py
```

Python·가상환경·Qt/PySide 라이브러리는 배포 ZIP에 포함하지 않습니다. 자동 설치나 가상환경 생성도 하지 않습니다. 화면에 필요한 로컬 JavaScript·아이콘 자산과 라이선스는 앱 소스에 포함됩니다. 사용자 실행에 Node.js, PyTorch, CUDA, Zemax는 필요하지 않습니다.

## 첫 사용

1. **Select model report… → Browse report** → `examples/local-demo/training-report.json`을 선택합니다.
2. **Targets · Read only → Load target JSON** → `examples/local-demo/target.json`을 선택합니다.
3. **Workspace**로 돌아갑니다.
4. **Configure**에서 변수를 선택하고 슬라이더·숫자·재질을 조절합니다.
5. **Best candidates → 미달 포함 탐색**에서 DB 후보를 비교합니다.

상단 **Open**은 모델이 아닌 Save로 만든 작업 세션을 여는 버튼입니다. `.pth`는 직접 선택하지 않습니다. 데모 파일들의 상대 위치와 이름을 유지하세요.

웹 가이드: **[온라인 사용자 가이드](https://dive-deep.github.io/optics-studio-feedback/)**에서 바로 읽을 수 있습니다. 오프라인에서는 다운로드한 폴더의 **`guide/dist/index.html`**을 브라우저에서 여세요. 가이드는 설명 페이지이며 설계 작업을 실행하지 않습니다.

## 피드백

저장소 **Issues → New issue**에서 **사용성 피드백** 또는 **실행 오류** 양식을 선택해주세요. 작성에는 GitHub 로그인이 필요합니다. 화면·버튼, 수행 순서, 기대한 동작, 실제 결과와 캡처를 포함하면 도움이 됩니다. 로그인하기 어렵다면 가이드의 양식을 복사해 담당자에게 전달해주세요.

이번 검토는 조작 흐름·용어·읽기 쉬움·필요한 기능에 초점을 맞춥니다. 동봉된 DB는 **수학적 합성 데이터**, 모델은 **파일 연결 확인용 더미**입니다. Zemax 해석이나 학습 모델의 정확도를 검증하는 버전이 아닙니다.

현재 DB 500건 중 148건이 같은 조건에서 비교 가능하고 나머지 352건은 제외됩니다. 현재 목표에서는 148건 모두 NG이므로 기본 모드의 ‘허용 후보 없음’은 정상입니다. ‘미달 포함 탐색’에서 Pareto를 볼 수 있습니다.

## 실행 문제 확인

```powershell
py -3.12 launch.py --check
```

- Python/PySide 버전·x64·필수 화면 파일을 확인하며 창이나 백엔드 작업은 시작하지 않습니다.
- `py`가 없다면 같은 Python 3.12의 `python -m pip install -r requirements.txt`, `python launch.py`를 사용합니다.
- 별도 Python 경로를 쓰려면 CMD에서 `set "OPTICS_PYTHON=C:\path\to\python.exe"` 후 `run_windows.cmd`를 실행합니다. 이 값에는 실행 파일 경로만 넣습니다.
- 실패하면 터미널의 메시지, Windows/Python 버전, 화면 해상도와 배율을 Issues에 남겨주세요. CUDA GPU가 없어도 UI를 사용할 수 있습니다.
- WebGL2를 사용할 수 없는 그래픽 환경에서는 안내와 함께 2D 단면으로 전환하며 3D 버튼은 비활성화됩니다. 정상 드라이버 환경에서는 기존 3D 회전·이동·확대를 사용할 수 있습니다.
- 앱 전체가 비어 보이면 ZIP을 전부 압축 해제했는지와 `--check` 결과를 확인합니다. QtWebEngine 보안 설정을 끄지 마세요.

## 검증 범위와 개발자 메모

[Windows 자동 검증](https://github.com/Dive-deep/optics-studio-feedback/actions/runs/35732824991)을 통과했습니다. Windows Server 2025 x64 / Python 3.12 / PySide6 6.11.2에서 의존성 설치, UTF-8 재빌드, 한글·공백 경로의 CMD 실행, 단위 검사, 실제 3D·파일·세션 23개 및 Pareto 16개 검사를 확인했습니다. Python은 132개 통과·플랫폼 전용 1개 제외, JavaScript는 140개 통과했습니다. **물리 Windows 11 PC의 GPU·DPI·OS 파일 선택/드래그 검증은 TBU**입니다.

Mac 개발 환경에서 단위 검사와 실제 Qt 앱의 합성 데이터 로딩·가이드 캡처를 검증했습니다. 상세 결과는 [`VALIDATION.md`](VALIDATION.md)에 기록합니다. 자동 GUI 검사의 파일 대화상자는 명시적인 테스트 경로로 대체합니다.

- `main`: Windows 배포 작업 전의 소스 스냅샷 기준점.
- `feedback/windows-preview`: 이번 배포·가이드·런처 작업. 메인 프로젝트로 자동 동기화하지 않습니다.
- `snapshot-manifest.json`: 분리 시 원본 파일 SHA-256 기록. 이후 배포 수정의 기준점입니다.
- `scripts/build_feedback_release.py`: 사용자용 ZIP 생성. 런타임·venv·연구 문서·테스트·개인 산출물을 넣지 않습니다.
- `design/`과 `scripts/build_ui.py`: 개발자용 UI 재생성 소스. 사용자 실행 시 재빌드하지 않습니다.
- `.github/workflows/windows-check.yml`: Windows CI. `.github/workflows/guide-pages.yml`: 가이드만 Pages로 게시.

```powershell
python -m unittest discover -s tests -v
node --test tests/*.cjs
python scripts/build_feedback_release.py
```

저장소는 피드백 배포용이며 별도 오픈소스 라이선스를 선언하지 않았습니다. 동봉된 외부 자산의 라이선스와 데이터 출처는 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)를 참고하세요.
