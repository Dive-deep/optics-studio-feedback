# Sensitivity matrix — Sobol 보고서와 네이티브 패널

2026-10-03 · 현재 범위는 **검증된 형식의 외부 결과를 읽고 표시하는 Python/Qt 프런트엔드**다. Sobol 표본 생성·평가·지수 계산, surrogate 추론·학습, Zemax 실행은 연결하지 않았다. 임의의 기존 DB 행에서 Sobol 지수를 추론하지 않는다.

구현: [서비스](../../optics_ui/services/sensitivity.py), [네이티브 위젯](../../optics_ui/workbench/sensitivity.py). 테스트는 저장소의 `tests/test_sensitivity.py`에 있다. 해석과 지원하는 보고서 계약은 아래에 설명한다.

## 표시 범위

`SensitivityPanel`은 `Sensitivity matrix`와 `Sobol indices`를 표시한다. **행=응답, 열=독립 입력**이며 콤보로 `S1 · First order`와 `ST · Total order`를 전환한다. 별도 상위 편집 탭을 생성하지 않는다. 선택한 응답은 같은 열 순서의 QPainter 막대로 표시하며 입력이 많으면 스크롤한다. 행렬 셀과 막대의 tooltip에는 원본 지수, CI, 상태, 입력 분포와 출력 조건이 있다.

보고서를 읽기 전에는 다음 9개 응답 행을 표시한다. 모든 결과는 `null`이며 화면에서는 `—`로 표시한다. 기본 행 이름이 존재한다는 사실은 해당 분석 조건의 계산 완료를 뜻하지 않는다.

| 출력 ID | 기본 의미 | 기본 단위 |
|---|---|---|
| `mtf_0_s` | MTF 6 lp/mm · 0F · Sagittal | fraction |
| `mtf_0_t` | MTF 6 lp/mm · 0F · Tangential | fraction |
| `mtf_08_s` | MTF 6 lp/mm · 0.8F · Sagittal | fraction |
| `mtf_08_t` | MTF 6 lp/mm · 0.8F · Tangential | fraction |
| `spot_rms_diameter_1f` | Spot RMS **직경** · 1F | µm |
| `horizontal_fov` | Horizontal FOV · **full angle** | deg |
| `vertical_fov` | Vertical FOV · **full angle** | deg |
| `na` | NA | dimensionless |
| `distortion` | Distortion | % |

출력별 `conditions`는 보고서에 따로 보존한다. NA의 object/image space, distortion의 signed/absolute 및 field 정의, MTF 방식, spot reference 등 과학적 의미는 생산자가 명시해야 한다. 현재 검증은 조건 object와 데이터 구조의 일관성을 검사하며, 모든 광학 정의의 올바름이나 평가기 정확성을 인증하지 않는다.

보고서에 없는 기본 응답은 미계산으로 남고 추가 출력은 뒤에 붙는다. 보고서를 읽은 뒤 열은 그 보고서의 독립 입력 목록을 사용한다. 미제공·고정 변수에 가짜 0을 넣지 않는다. 비활성 `Calculate · TBU` 버튼과 안내 문구가 평가기 미연결 상태를 알린다. 예시 숫자를 사용자의 기본 결과로 표시하거나 자동 연결하는 경로는 없다.

## 서비스 API

Qt 없이 사용할 수 있는 함수들이다. 예상 가능한 검증 오류는 `SensitivityError(ValueError)`의 `code`, `message`로 전달한다.

| 함수 | 계약 |
|---|---|
| `context_hash(context)` | 전체 JSON context의 숫자 의미를 정규화하고 정렬된 키·고정 구분자로 직렬화한 SHA-256 문자열 |
| `load_sensitivity_report(path)` | 선택된 파일 하나만 읽고 검증된 독립 dict 반환. 파일 변경·실행 없음 |
| `validate_report(payload)` | 파일을 읽지 않고 보고서 dict 검증. 원본 입력을 변경하지 않고 경고가 포함된 복사본 반환 |
| `validate_panel_snapshot(payload)` | 세션의 sensitivity 부분을 **워크스페이스 변경 전에** 검증. embedded 보고서도 검증 |

주요 오류 코드는 `INVALID_REPORT`, `REPORT_READ_ERROR`, `SESSION_REPORT_TOO_LARGE`다. 오류 메시지는 사용자에게 전달할 수 있다. 원본 보고서 경로를 실행 대상으로 취급하거나 보고서가 가리키는 모델·스크립트를 로드하지 않는다.

## 보고서 schema version 1

학습 모델 report와 별개의 형식이다. `format='optics-sobol-report'`, 정수 `schema_version=1`을 요구한다. 실행 가능한 JSON fixture는 테스트 파일의 `context()`, `report()`, `cell()`에만 있으며, 명시적인 `synthetic_fixture`/`analytic_test` 출처를 가진 단위 테스트 데이터다. 사용자 demo DB·모델·세션에 자동 등록하지 않는다.

| 필드 | 필수 내용 |
|---|---|
| `study` | `id`, `context_hash` |
| `context` | 당시의 전체 `parameters`, `conditions`, `optics`, `model`, `reference_id`, `targets` |
| `origin` | `kind=external_analysis` 또는 `synthetic_fixture`, 비어 있지 않은 `source` |
| `evaluator` | `kind=simulator`/`surrogate`/`analytic_test`, `id`, `version` |
| `conditions` | 비어 있지 않은 분석 조건 object. `context.conditions`와 동일 |
| `distribution` | `dependence='independent'`, 입력마다 하나의 `marginals` 항목 |
| `sampling` | 아래 표본설계 메타데이터 |
| `inputs` | `{id,label,unit}` 배열, 중복 없는 1–128개 독립 입력 |
| `outputs` | `{id,label,unit,variance,conditions}` 배열, 중복 없는 1–32개 응답 |
| `first_order` | 출력 수 × 입력 수의 S1 cell 행렬 |
| `total_order` | 같은 차원의 ST cell 행렬 |

`context.parameters`는 `{id,label,unit,min,max,value,active,available}`를 기본 계약으로 사용한다. 독립 입력은 당시 context에서 `active=true`, `available=true`여야 하며 ID와 단위가 일치해야 한다. 고정값과 미제공 값도 전체 context에는 남긴다.

v1은 **독립·비그룹 입력의 Saltelli cross-design**만 받는다. 각 marginal은 `input_id`, `kind`를 가지며 다음 조건을 만족한다.

- `uniform`/`loguniform`: 유한하고 증가하는 `bounds=[min,max]`. context 범위와 동일해야 하며 loguniform은 양수다.
- `discrete`: 유한한 고유 값과 명시적인 양의 `probabilities`. 값은 context 범위 안에 있어야 한다.
- `categorical`: 고유 문자열 값과 명시적인 양의 `probabilities`. context에 `choices`가 있으면 같은 집합이어야 한다.
- discrete/categorical은 2–256개 값, 확률 합 1을 요구한다. 재질 선택을 one-hot 독립 입력으로 자동 변환하지 않는다.
- 종속 입력, 그룹 효과, 파생 변수를 독립 열로 선언한 결과는 이 버전에서 받지 않는다. 지원 범위를 넓힐 때 별도의 계약과 해석을 추가해야 한다.

`sampling`의 필수 키는 `method='saltelli_cross_design'`, `estimator`, `implementation`, `base_sample_count`, `evaluation_count`, `seed`, `scramble`, `second_order`, `design_hash`, `confidence_level`, `ci_method`다. seed는 정수 또는 null, scramble/second_order는 명시적 bool, design_hash는 64자리 SHA-256 문자열이다. confidence_level과 ci_method는 미제공이면 null로 기록한다.

독립 입력 D개와 base 표본 수 N에 대해 평가 행 수는 2차 효과를 구하지 않을 때 `N(D+2)`, 구할 때 `N(2D+2)`와 일치해야 한다. `second_order=true` 메타데이터를 받아도 현재 패널은 S1/ST만 표시한다. 검증기가 실제 표본 파일을 읽거나 해시·pairing을 재계산하는 것은 아니다. 따라서 생산자가 선언한 표본설계를 실제로 수행했는지는 별도 backend 검증 대상이다.

## Cell, 결측과 불확실성

cell 필수 키는 `estimate`, `ci_low`, `ci_high`, `status`다. 세 수치는 유한한 수 또는 명시적인 null이다. 출력 `variance`는 비음수 유한 값 또는 null이며, 숫자 지수에는 양수의 알려진 분산을 요구한다.

- 숫자 지수의 상태: `estimated_unvalidated`, `validated_for_scope`, `insufficient_precision`.
- null 지수의 상태: `not_computed`, `zero_output_variance`, `invalid_input_assumptions`, `sample_design_invalid`, `undefined_output`, `surrogate_validation_failed`, `unavailable`, `fixed`, `not_applicable`.
- CI는 양 끝점이 모두 존재하고 순서가 맞거나, 둘 다 null이어야 한다. null 지수에는 숫자 CI를 붙이지 않는다.
- CI가 있으면 confidence level과 방법도 있어야 한다. SALib `*_conf`의 **반폭**을 끝점처럼 읽지 않는다. 보고서 생산자가 `ci_low`/`ci_high`로 명시적으로 변환해야 한다.
- CI가 없으면 tooltip에 `CI: unavailable`을 표시한다. CI를 0으로 채우거나 모델 예측 정확도·광학 오차 보증으로 해석하지 않는다.
- 음수나 1 초과의 유한 추정치는 허용하고 `ESTIMATE_OUTSIDE_UNIT_INTERVAL` 경고와 다른 색으로 표시한다. 원본 수치를 0/1로 자르지 않는다. S1이 ST보다 크면 `FIRST_EXCEEDS_TOTAL` 경고를 추가한다.
- **ST 행 합계는 1로 정규화하지 않는다.** 상호작용이 여러 입력에서 중복 포함되므로 합계가 1보다 큰 것만으로 잘못된 결과는 아니다.

S1/ST는 선언한 분포에서의 분산 기여이며 파라미터를 올릴지 내릴지 알려주지 않는다. 낮은 S1만으로 변수를 고정하거나, `ST−S1`을 특정 두 변수의 상호작용으로 읽지 않는다. `validated_for_scope`도 외부 생산자의 주장이다. 패널은 이를 독립적으로 확인했다고 표시하지 않는다.

## Context와 stale

보고서의 `study.context_hash`는 함께 들어 있는 `context`의 재계산 해시와 일치해야 한다. 현재 패널 context와 그 해시가 다르면 `Stale`을 표시하면서 기존 보고서를 참고용으로 보존한다. 해시에는 범위뿐 아니라 값·활성 상태·조건·재질·면 종류·Stop·모델·목표·reference가 포함된다. key 순서 변화는 같은 해시지만 다른 JSON 값이나 배열 순서는 다른 context다.

v1 해시 규칙은 Python→JavaScript JSON→Python 왕복의 숫자 의미를 보존한다. **해시 계산용 복사본에서만** `1`과 `1.0`, `0`과 `-0.0`을 동일하게 처리하며, 불리언은 숫자와 구별한다. 생산자의 보고서나 원래 context dict를 바꾸지 않는다. 유한한 비정수 float는 같은 binary64 값의 Python round-trip 표현을 사용한다. 이 규칙은 앱의 schema v1 계약이며 RFC 8785 전체 구현이라는 의미는 아니다.

context의 정수값은 정수형 float도 포함해 **±(2⁵³−1)** 안으로 제한한다. 그 밖의 값은 JavaScript에서 정밀도가 달라질 수 있으므로 조용히 반올림하지 않고 거절한다. 큰 식별번호는 문자열로 제공한다. `1e20`처럼 유한하지만 이 한계를 넘는 정수형 값도 보수적으로 거절한다. 출시 전 v1 규칙을 보완한 것이므로 외부 생산자는 이 `context_hash()` 규칙으로 해시를 생성해야 한다. 잘못된 해시를 import 시 자동 재작성하지 않는다.

호출자는 조건/형상/모델 설정이 바뀔 때 `set_context()`를 다시 호출한다. 같은 해시가 반복 전달되면 위젯을 재구축하지 않는다. 보고서의 입력/출력 값을 현재 설계에 자동 적용하지 않으며, stale 상태를 해소하려고 결과를 재계산하지 않는다. 저장된 `stale` 플래그는 복원 시 신뢰하지 않고 현재 context와 다시 비교한다.

새 live context 자체가 검증에 실패해도 이전 보고서를 삭제하지 않는다. 대신 `Stale · current context cannot be validated`로 표시해 이전 정상 해시 때문에 fresh로 남는 일을 막는다. 정상 context를 다시 전달하면 거절 상태를 해제하고 해시를 비교한다.

## 네이티브 통합과 세션

```python
from optics_ui.workbench.sensitivity import SensitivityPanel
from optics_ui.services.sensitivity import validate_panel_snapshot

panel = SensitivityPanel(parent)
panel.statusMessage.connect(show_status)
panel.set_context(current_analysis_context)
```

| 메서드·신호 | 동작 |
|---|---|
| `set_context(dict) -> bool` | 유한 JSON context 보존, stale 갱신. 거절 시 기존 보고서는 유지하고 현재 context 사용 불가·stale 표시 |
| `load_report(path) -> bool` | 정상 보고서만 교체. 잘못된 파일은 이전 보고서·선택·표시 유지 |
| `snapshot() -> dict` | 보고서와 표시 선택을 복사. 용량 제한 실패는 typed 예외 |
| `restore(snapshot) -> bool` | 먼저 전체 sensitivity snapshot 검증 후 교체. 실패 시 기존 표시 유지 |
| `statusMessage(str)` | import/restore/context 실패와 import 완료 상태 전달 |
| `request_preview() -> dict` | 실행하지 않는 typed 요청 초안 |

snapshot은 `format='optics-sensitivity-panel'`, `schema_version=1`, `report`, `report_path`, `metric='S1'|'ST'`, `output_id`, `stale`를 가진다. `report`는 검증된 내용을 embed하거나 null이다. `report_path`는 출처 기록이며 복원 시 그 경로의 파일을 자동으로 다시 읽지 않는다. 패널 restore가 광학 workspace context까지 복원하지 않으므로 호출자가 전체 세션을 검증하고 context를 설정해야 한다.

전체 세션 적용 전에 `validate_panel_snapshot(saved_state['sensitivity'])`를 호출한다. 광학 상태를 먼저 바꾼 뒤 불량 보고서를 발견하는 부분 복원을 피하기 위한 순서다. 이는 sensitivity 부분 검증이며 세션의 나머지 상태와 전체 용량은 상위 로더가 검사해야 한다.

선택 파일 import 한도는 **2 MiB**다. 중복 JSON 키, 비유한 수, 잘못된 UTF-8/JSON, 과도한 차원·중첩은 거절한다. 세션 embed는 canonical JSON 기준 **1 MiB**로 더 작게 제한해 나머지 광학·UI 설정 공간을 남긴다. 이를 넘으면 `SESSION_REPORT_TOO_LARGE`를 반환하고 현재 열람 결과를 유지한다. 큰 보고서를 조용히 경로 참조로 바꾸지 않으며, 작은 보고서로 교체한 뒤 저장하도록 안내한다. 상위 세션/전송의 전체 2 MiB 한도 충족은 별도 검증이 필요하다.

## Typed 요청 초안 내보내기

`request_preview()`는 `schema_version=1`, `method='sobol_sensitivity'`, `status='unavailable'`, `reason='evaluator_not_connected'`, `executed=false`, `context_hash`, `context`, 기본 `outputs`, `distribution=null`, `sampling=null`을 반환한다.

현재 context가 거절된 상태라면 `reason='invalid_context'`, 설명 `message`, `context=null`, `context_hash=null`을 반환한다. 예외를 내거나 이전 context를 현재 유효한 요청으로 제시하지 않는다. `executed=false`와 미설정 분포·표본설계는 유지한다.

이는 상위 UI나 향후 어댑터가 표시·직렬화할 수 있는 데이터다. 이 메서드 자체는 파일을 저장하거나 endpoint를 호출하지 않는다. GUI의 min/max만 보고 균일분포를 가정하거나 예산·seed를 만들어 넣지 않는다. 실제 평가기, 분포, 표본설계, 실패 처리와 검증 계약이 정해질 때까지 실행 요청으로 승격하지 않는다.

## 테스트 우선 개발과 확인 결과

테스트를 먼저 작성해 미구현 모듈 import 실패를 확인했고, 구현 및 보완 후 **26개 테스트가 Python 3.12.14에서 통과**했다. Qt 위젯 검사는 공용 `tests.qt_support.QT_APP`의 offscreen 환경을 사용한다.

검증 범위는 provenance/분포/표본 수/차원/중복/비유한 값 거절, categorical 확률, null·CI·범위 밖 추정치 보존, ST 비정규화, context 해시와 stale, 잘못된 교체·복원 시 기존 상태 유지, 세션 왕복과 embed 제한, 같은 context의 재렌더링 생략, 실행 없는 요청 초안, S1/ST 전환 및 실제 QPainter offscreen 렌더링이다.

추가 회귀는 반복되는 Radius 열·막대·tooltip의 렌즈/면/ID 구분, `1.0→1`과 signed zero의 동일 해시, unsafe 정수 거절, 잘못된 live context의 stale/복구를 검사한다. 실제 Node의 `JSON.parse`/`JSON.stringify`를 통과한 float context 보고서를 다시 검증하고 `FileDataService.save_session`/`load_session`으로 왕복했다. 변경 전에는 같은 검사에서 context hash mismatch가 발생했다. Node가 없는 테스트 환경에서는 이 한 가지 실제 JS 왕복 검사를 명시적으로 skip하며, 이번 로컬 26개 통과 실행에는 skip이 없었다.

재현:

```sh
python -m unittest tests.test_sensitivity
```

이 결과는 외부 Sobol 평가의 통계적 정확성, 실제 surrogate/Zemax 연결, Windows 화면 동작 또는 최종 앱 전체 통합 검증을 뜻하지 않는다. 서비스·패널 테스트의 수치 fixture는 실제 광학 성능이 아니며 사용자 초기 화면에 연결하지 않는다.

`Clear report`는 가져온 보고서를 화면에서 해제하며 현재 설계/context와 원본 파일을 보존한다. 큰 embedded 보고서 때문에 세션 저장이 거절된 경우 설정만 저장하는 데 사용할 수 있다. 보고서 해제 회귀도 위 테스트 수에 포함한다.
