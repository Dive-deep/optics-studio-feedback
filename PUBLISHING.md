# 공개 배포 담당자 안내

저장소: [Dive-deep/optics-studio-feedback](https://github.com/Dive-deep/optics-studio-feedback)

기본 브랜치는 `feedback/windows-preview`입니다. 이전 `main` 기준점과 Release를 보존하며 개발 원본으로 자동 역동기화하지 않습니다. 이번 공개 범위는 **Optics Studio 앱과 사용자 문서**입니다.

## v1.1.0 배포물

- Git tag: `v1.1.0`
- Release 상태: prerelease — ML/Zemax/자동 설계 실행은 연결 전
- 사용자 ZIP: `Optics-Studio-v1.1.0.zip`
- ZIP과 함께 SHA-256 checksum을 제공합니다.
- Python/Qt 런타임, 가상환경, 개인 설정, 연구 자료, 실험 기록은 ZIP에 포함하지 않습니다.
- 저장소의 개발 소스와 테스트는 공개하지만 사용자 ZIP의 실행에 재빌드나 Node.js가 필요하지 않습니다.

## 배포 절차

1. 제품 버전·README·CHANGELOG·사용자 가이드·Issues 기본 버전을 맞춥니다.
2. `python scripts/build_ui.py`로 로컬 자산을 만들고 Python/Node 테스트를 실행합니다.
3. GUI 세션에서 `scripts/smoke_workbench.py`, `scripts/smoke_analysis_windows.py`를 실행합니다. 파일 대화상자 대역과 실제 OS 검증을 구분합니다.
4. `python scripts/build_feedback_release.py`로 사용자 ZIP을 생성합니다. 새 폴더에 압축 해제해 필수 파일, 실행 진입점, 상대 링크와 checksum을 확인합니다.
5. 공개 브랜치에 커밋을 올리고 [Windows CI](https://github.com/Dive-deep/optics-studio-feedback/actions/workflows/windows-check.yml)에서 **해당 커밋**의 결과를 확인합니다. 실패·미실행을 통과로 기록하지 않습니다.
6. 검증한 실행 코드를 tag/Release 대상으로 사용하고 ZIP·checksum을 첨부합니다. 검증 결과를 기록하는 문서 전용 후속 커밋을 tag로 사용할 때는 실행 코드·테스트가 CI 커밋과 동일한지 Git diff로 확인하고 두 커밋의 역할을 구분합니다. [VALIDATION.md](VALIDATION.md)에 실행 URL과 환경·한계를 기록합니다.
7. [Guide Pages workflow](https://github.com/Dive-deep/optics-studio-feedback/actions/workflows/guide-pages.yml)의 게시 결과를 확인하고 공개 가이드 링크·자산을 검사합니다.

실제 Windows 11 기기 검사가 남아 있으면 그 사실을 Release와 검증 문서에 유지합니다. 기존 0.x 자동 검사 결과로 v1.1의 성공을 대신하지 않습니다.

## 가이드와 피드백

온라인 가이드는 [GitHub Pages](https://dive-deep.github.io/optics-studio-feedback/)이며 `guide/dist`만 게시합니다. 오프라인 `guide/dist/index.html`을 ZIP에 포함합니다. 가이드의 설명과 스크린샷이 앱 버전과 다르면 변경하거나 이전 자료임을 명시합니다.

피드백은 Issues의 사용성/실행 오류 양식으로 수집합니다. 백그라운드 telemetry는 추가하지 않습니다. 사용자 캡처·로그를 공개할 때 토큰·개인정보·업무 데이터가 없는지 확인합니다.

기존 외부 자산의 라이선스는 유지하며 프로젝트 라이선스를 임의로 새로 선언하지 않습니다. 자세한 내용은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.

## 소스 갱신 시 유지할 배포 설정

개발 원본에서 파일을 가져올 때 공개 저장소의 `.gitattributes`, Windows CI, 배포 빌더와 Windows 전용 fixture 정리 코드를 통째로 덮어쓰지 않습니다. 모델 `.pth`·SQLite·이미지의 binary 속성은 체크아웃 중 바이트 변경을 막습니다. Git `core.autocrlf=true` 체크아웃 후 모델·목표 파일의 checksum도 배포 회귀 검사에 포함됩니다.
