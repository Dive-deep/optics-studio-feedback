# 합성 데모 사용

앱의 **Select model report… → Browse report**에서 `training-report.json`을 선택한 뒤 **Targets · Read only → Load target JSON**에서 `target.json`을 선택하세요. 상단 Open은 Save한 UI 세션용입니다.

이 폴더의 이름과 상대 위치를 유지합니다.

- `training-report.json`: 모델·DB·재료·목표 파일을 참조하는 리포트.
- `demo-model.pth`: 파일 연결 검사용 dummy. 학습된 모델이 아니며 역직렬화하지 않습니다.
- `demo-cases.sqlite`: 500개 합성 광학 사례. Zemax 실행 결과가 아닙니다.
- `materials/material_catalog.sqlite`: 로컬 광선 표시용 참조 카탈로그. 출처·proxy 경고를 유지합니다.
- `target.json`: 읽기 전용 데모 목표.

D057_2는 최초 참조 케이스이며 최선 또는 합격 설계가 아닙니다. 현재 148개 비교 가능 사례는 모두 NG입니다. Best candidates의 ‘미달 포함 탐색’으로 후보 간 절충을 확인하세요.

소스 저장소에 있는 `demo.optics.json`은 파일서비스 테스트 fixture로, 시작 세션으로 사용하지 않습니다. 사용자용 배포 ZIP에는 포함되지 않습니다. 실제 세션은 앱의 Save로 만드세요.
