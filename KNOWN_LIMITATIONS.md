# 현재 제한 — v1.1.0

이 버전은 화면과 파일·설정 작업을 검토하기 위한 사전 공개 앱입니다.

| 항목 | 현재 동작과 경계 |
| --- | --- |
| AI 예측·신뢰도 | 연결 전입니다. 파라미터 편집 후 저장된 MTF·Spot·스칼라를 새 예측으로 갱신하지 않습니다. |
| 모델 업데이트·Zemax·Auto design | 설정과 요청 초안을 준비합니다. 실제 학습·추가 데이터·반복 작업을 실행하지 않습니다. |
| DB tailoring | 섹션과 TBU 안내만 제공합니다. PCA·UMAP·필터 결과 DB 생성은 미구현입니다. |
| LLM panel | 표시·초안 저장만 제공합니다. 모델 응답·인증·코드 실행은 미연결입니다. |
| Sensitivity | 검증된 외부 Sobol JSON의 S1/ST·CI를 표시합니다. 표본 생성과 지수 계산은 TBU입니다. |
| 미제공 값 | A12와 Relative illumination은 공란입니다. 미계산 Sensitivity는 `—`이며 0이 아닙니다. |
| Explorer | 소스 파일을 읽기 전용으로 표시합니다. 편집·실행은 앱 내 기능이 아닙니다. |
| 광학 표시 | 렌즈 형상과 로컬 기하 광선은 Zemax의 성능 검증 결과가 아닙니다. |
| 데모 | DB는 합성 데이터이고 `.pth`는 dummy입니다. 광학·학습 정확도 평가에 사용하지 않습니다. |
| 저장·복원 | 설정과 화면 상태를 복원합니다. 실행 중인 backend 작업을 재개하지 않습니다. |
| Compute Test | GPU 인식 준비 상태만 진단합니다. ready도 학습·Zemax 성공을 뜻하지 않습니다. |

## Windows와 디스플레이

지원 정책은 Windows 11 x64, 표준 CPython 3.10–3.14, PySide6 6.11.2입니다. Python 3.12를 권장합니다. free-threaded/PyPy/32비트 Python/Windows ARM64는 이번 배포 대상이 아닙니다.

Windows Server CI 결과와 실제 Windows 11 PC 검증은 구분합니다. 실제 GPU, 고배율 DPI, OS 파일 선택·드래그, 접근성 검사는 추가 피드백이 필요합니다. 최신 실행 결과와 확인 범위는 [VALIDATION.md](VALIDATION.md)에 기록합니다.

WebGL2를 사용할 수 없으면 2D 단면을 유지하고 3D를 비활성화합니다. 작은 화면에서는 모든 분석을 동시에 볼 수 없으므로 분할 영역과 별도 분석창을 조절하세요.

## 데이터와 세션

목표 JSON은 읽기 전용입니다. 조건이나 출처가 맞지 않는 DB 케이스는 비교에서 제외하며, 허용 후보가 없으면 best를 만들어 표시하지 않습니다. NG 탐색과 합격 후보를 구분하세요.

외부 Sobol 보고서는 최대 2 MiB, 세션에 넣는 보고서는 1 MiB까지입니다. 현재 설정과 다른 context의 보고서는 Stale로 표시됩니다. 큰 보고서로 저장이 거절되면 Clear report로 화면에서 해제한 뒤 설정만 저장할 수 있으며 원본 보고서는 삭제하지 않습니다.

문제가 생기면 [실행 오류](https://github.com/Dive-deep/optics-studio-feedback/issues/new/choose) 양식에 버전과 재현 순서를 남겨주세요.
