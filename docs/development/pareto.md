# DB Pareto: 비교 집합·목표·표시 계약

2026-09-22 · DB 기반 기능을 로컬 desktop 앱에 통합하고 검증했다. 구현 계약과 실제 검증 결과를 함께 기록한다. 이 문서의 과거 검증 기록과 현재 공개 버전의 검증은 구분하며 최신 실행 범위는 [검증 기록](../../VALIDATION.md)을 따른다.

## 1. 이번 범위

- 연결된 DB의 실제 케이스 풀에서 비교 가능한 결과를 추출한다.
- 기본 두 축에서 후보를 선택·강조하고, 선택한 2D 목적의 전선을 선택적으로 연결한다.
- **선택한 두 목적의 비지배 전선**과 **전체 세 목적의 비지배 후보를 두 축에 투영한 점**을 구별한다.
- 읽기 전용 목표 JSON의 가중치에 따른 현재 best candidate를 별표로 구분한다.
- DB의 실제 해석/측정 결과, DB 합성 데이터, 향후 모델 예측 결과를 구분한다. 예측 backend가 연결되기 전에는 predicted front를 placeholder로 유지한다.

DB에 포함된 비교 집합의 비지배 후보를 찾는 기능이다. 전체 물리 설계 공간의 진정한 전역 최적해를 찾았다는 뜻이 아니다. 전선을 연결한 선 위에 실제 렌즈가 존재하거나, 중간 좌표의 성능이 검증되었다는 뜻도 아니다.

## 2. 그래프가 참조할 하나의 케이스 풀

Python 계층에서 현재 선택한 리포트/DB를 읽어 case ID·결과·조건·출처를 제공하고, UI의 산점도·2D 전선·3목표 비지배 표시·가중 best가 **같은 풀**을 사용한다. 예전 embedded scatter나 다른 DB의 점을 섞어 새 DB의 Pareto 결과처럼 표시하지 않는다.

비교 집합의 식별자는 최소한 `source_kind + cohort_key`를 포함한다. cohort는 온도, 분석 파장 또는 spectrum과 그 가중, field 정의, S/T 방향, 분석 종류·설정·단위 등 실제로 비교에 필요한 조건을 구분한다. 재질이나 허용된 surface type은 설계 변수이므로 동일 분석 조건 아래의 대안 비교에서 반드시 같아야 한다고 가정하지 않는다.

| 정보 | 규칙 |
|---|---|
| 케이스 연결 | 모든 점은 현재 DB의 case ID와 선택 분석의 출처로 돌아갈 수 있어야 함 |
| 출처 | 실제 DB 결과와 합성 DB 결과를 구분; 예측이면 별도의 model/version 문맥 필요 |
| 조건 | 서로 다른 cohort를 한 전선 계산에 혼합하지 않음 |
| 결측 | 필수 MTF/Spot/FOV 또는 비교 조건이 없으면 `UNKNOWN`/제외 이유를 표시; 0이나 fallback 예측값으로 채우지 않음 |
| 지원 범위 | 편집 가능한 광학계와 호환되지 않는 케이스·유효하지 않은 분석은 이유와 함께 구분 |
| 수량 | 전체 조회 수·평가 가능 수·허용 후보 수·제외 사유를 구분. 일부만 조회했으면 그 범위를 명시 |
| 편집 상태 | DB에서 불러온 결과와 사용자가 변경한 미평가 처방을 구분. 편집값을 DB 점의 새 예측으로 기록하지 않음 |

단순 화면 표시용 25°C·560 nm fallback은 실제 분석 조건의 증거가 아니다. 명시된 DB 조건은 유지하고, 조건 정보가 없는 결과를 fallback 때문에 같은 cohort로 확정하지 않는다.

## 3. 목적과 score: `relative_target_margin_v1`

현재 임시 목표는 MTF 6 lp/mm의 0F S/T 각각 0.4 이상, 0.8F S/T 각각 0.3 이상, Spot 1.0F RMS **직경** 1.6 μm에 가까움, 전체 수평 FOV 24°에 가까움이다. 실제 값·가중치는 로드한 target JSON을 따른다. UI에서 이를 덮어쓰지 않는다.

각 MTF 조건 i의 실제값을 `m_i`, 양수 목표를 `t_i`라 하면:

```
MTF quality = min_i(m_i / t_i)
L_mtf      = 1 - MTF quality
L_spot     = abs(RMS_diameter - spot_target) / spot_target
L_fov      = abs(horizontal_full_fov - fov_target) / fov_target
```

세 목적은 모두 loss를 **최소화**하는 형태다. MTF는 네 조건의 최악 정규화 비율을 사용해 하나의 범주로 취급한다. `L_mtf`는 clamp하지 않으므로 모든 조건의 MTF가 목표보다 높으면 음수가 될 수 있다. 목표를 넘은 뒤에도 높은 MTF를 선호한다는 원래 요구를 유지한다. 이 값은 확률·정확도·성공률이 아니다.

별표를 위한 score는 같은 세 범주 loss의 가중 평균이다.

```
score = (w_mtf*L_mtf + w_spot*L_spot + w_fov*L_fov)
        / (w_mtf + w_spot + w_fov)
```

현재 범주 가중치는 1:1:1이며 로드한 JSON의 범주 weight를 사용한다. 낮을수록 좋다. MTF 네 조건을 각각 별도 범주로 더하지 않는다. 음수 score도 허용하며 백분율처럼 표시하지 않는다. 목표·가중치가 평가 규약에 맞지 않으면 비교 불가 이유를 반환한다.

## 4. 후보 통과와 점수는 분리한다

- `PASS`: 모든 필수 조건을 본래 comparator로 충족.
- `NEAR_PASS`: 본래 조건을 전부 충족하지는 않지만 모든 필수 조건이 상대 5% 허용 범위 안에 있음.
- `NG`: 하나 이상의 필수 조건이 후보 허용 범위를 벗어남.
- `UNKNOWN`: 필요한 값·조건이 없거나 평가할 수 없음.

현재 close-to 목표에 별도 정식 허용오차가 정의되어 있지 않으므로, Spot/FOV의 strict PASS는 부동소수 비교 오차 수준에서 목표 일치를 뜻한다. 5% 범위를 strict PASS로 승격하지 않는다. 향후 별도 tolerance를 지원하려면 명시적인 target/schema 규약으로 다뤄야 한다.

MTF 40% 목표의 후보 하한은 38%, 30% 목표는 28.5%다. Spot의 후보 허용 구간은 1.52–1.68 μm, H-FOV는 22.8–25.2°다. **MTF의 높은 여유가 다른 필수 조건의 NG를 score에서 상쇄할 수 없다.** best 선정 전에 PASS/NEAR_PASS gate를 적용한다.

허용 후보 모드에서는 PASS와 NEAR_PASS만 전선 계산에 사용한다. NG 탐색 모드에서는 유효한 NG 결과까지 분포·trade-off를 살펴볼 수 있지만 합격 후보와 다른 상태로 표시한다. 별표 best는 동일 source/cohort의 허용 후보를 기준으로 유지한다. 허용 후보가 없으면 best 별표도 없으며, 탐색 가능한 NG가 있다는 이유로 best 합격 후보를 만들어내지 않는다.

## 5. 2D 전선, 3목표 비지배, 별표의 차이

### 기본 축

기본 X축은 `L_spot`, Y축은 `L_fov`다. 둘 다 **목표와의 정규화 거리**로, 낮을수록 가깝다. raw Spot을 작게 만들거나 raw FOV를 크게 만드는 축으로 바꾸어 해석하지 않는다. tooltip/선택 상세에는 원래 μm·degree 값, 목표, 상태를 함께 표시한다. 두 축으로 보더라도 모든 MTF 필수 조건을 후보 gate에서 평가한다.

선택 가능한 MTF 축은 `MTF quality × 100`을 **MTF 최악 충족률 (%) ↑**로 표시한다. 100%가 최악 조건까지 목표에 도달한 상태이며, 클수록 좋다. 이는 원래 MTF 값이나 예측 신뢰도가 아니다. Spot/FOV 축은 정규화 목표 거리에 100을 곱한 목표편차(%)이며 작을수록 좋다. 내부 dominance 계산은 세 loss의 최소화 규약을 유지한다.

### 계산과 표시

| 표시 | 계산 기준 | 의미 |
|---|---|---|
| 일반 점 | 현재 source/cohort와 탐색 필터의 케이스 | DB에서 제공된 결과 |
| 선택 강조 | 사용자가 선택한 case ID | 읽고 비교 중인 후보 |
| 2D 전선 | 현재 선택한 두 목적만으로 dominance 계산 | 그 두 목적에서 비지배인 관측 케이스 |
| 3목표 비지배 강조 | MTF·Spot·FOV의 세 loss로 dominance 계산 후 두 축에 투영 | 현재 집합의 전체 세 목적에서 비지배인 케이스 |
| best 별표 | 허용 후보의 3목표 비지배 집합에서 score 최소 | 현재 target weight에 따른 대표 후보 |

Dominance는 모든 고려 목적에서 나쁘지 않고 적어도 하나에서 더 좋은 관계다. 전부 같은 값의 케이스는 서로를 지배하지 않는다. 같은 좌표가 여러 케이스를 나타내면 case ID를 잃지 않는다. score 동률의 대표 표시는 결정적인 규칙으로 선택하되 유일한 물리적 최적해라고 부르지 않는다.

세 목적에서 비지배인 점도 두 축에 투영하면 다른 점보다 나빠 보일 수 있다. 보이지 않는 MTF가 더 좋을 수 있기 때문이다. **3목표 비지배 점들을 단순히 이어 2D 전선이라고 표시하지 않는다.** 축만 바뀌면 2D 전선은 바뀔 수 있지만 같은 비교 집합의 3목표 비지배 여부와 target-weight best는 바뀌지 않는다.

선택적인 2D 연결선은 2D 전선의 관측 점들을 잇는 안내선이다. smooth surrogate curve나 중간 설계의 interpolation 결과가 아니다. 실제 case가 없는 선 위를 새로운 후보로 선택·적용하지 않는다.

## 6. 선택·갱신·연결 전 상태

점 선택은 해당 case의 강조와 상세 정보에 연결한다. 후보 적용은 기존 case load/apply 계약을 사용하며, 선택된 점의 좌표만으로 처방을 재구성하지 않는다. NG는 ‘미달 참조 설계로 적용’으로 구분한다. 적용 직전의 수동 편집 상태로 한 단계 되돌릴 수 있으며, 적용 후 새 물리 파라미터 편집이나 참조 변경이 있으면 이전 되돌리기는 비활성화한다.

DB/report, source/cohort, target profile 또는 비교 필터가 바뀌면 계산 문맥을 갱신한다. 이전 비동기 조회가 최신 화면을 덮지 않아야 한다. 후보 적용 응답이 늦게 도착한 경우 그사이 사용자가 편집한 파라미터도 덮지 않는다. target JSON의 weight만 바뀌었으면 score/best를 다시 계산하고, target 자체가 바뀌면 목적·gate·전선도 다시 평가한다.

Design space의 **Explore**와 상단 **Best candidates**에서 상세 화면을 연다. 조건·출처·축·2D/3목표·안내선 설정은 접을 수 있다. **Pareto 주변 확대**는 그래프의 표시 범위만 바꾸며, dominance는 전체 선택 집합에서 계산한다. 표시 중인 점 수와 비교 집합 수를 함께 보여준다. 축·필터·선·확대·선택 등 보기 설정은 세션에 저장하지만 파생 case pool은 저장하지 않고 DB에서 다시 조회한다.

모델 예측 전선은 backend가 실제 예측과 조건·model/version을 제공할 때 연결한다. 현재에는 연결 전 placeholder로 둔다. DB 점에 예측 라벨을 붙이거나 모양을 채우려고 예측 점을 생성하지 않는다. 합성 DB의 비지배 결과도 합성 데이터 내의 비교이며 Zemax 검증을 대신하지 않는다.

## 7. 인수 기준과 증거 추적

아래 기준을 단위 검사와 실제 desktop 통합 검사로 확인했다. 실행 범위와 결과는 다음 절에 기록한다.

| 기준 | 확인할 증거 |
|---|---|
| PARETO-01: 실제 case pool 연결 | report/DB를 바꿨을 때 산점도·전선·별표의 case ID와 수량이 그 DB/cohort로 함께 바뀜 |
| PARETO-02: 조건·출처 분리 | 온도/spectrum/분석 조건 또는 origin이 다른 결과를 같은 전선에 섞지 않음; 결측 제외 이유 |
| PARETO-03: 전체 MTF gate | 표시 축이 Spot/FOV여도 MTF 한 조건의 허용 범위 초과로 후보 탈락 |
| PARETO-04: 축 방향·단위 | Spot/FOV 목표 거리의 양쪽 편차, RMS radius→diameter 및 full FOV 보존; 선택 MTF 충족률 축의 클수록 좋음 표시가 내부 loss 최소화와 같은 dominance를 만듦 |
| PARETO-05: 2D/3목표 구분 | 2D에서는 지배되지만 MTF 덕분에 3목표 비지배인 케이스를 두 표시가 구분 |
| PARETO-06: 안내선 | 선택한 2D 전선만 연결, 선택적으로 켜고 끄기, 선 위를 실재 후보로 만들지 않음 |
| PARETO-07: score/별표 | category-normalized score·음수 MTF 여유·JSON weight·hard gate·동률 규칙 확인 |
| PARETO-08: 상태/빈 후보 | PASS/NEAR_PASS/NG/UNKNOWN 및 허용 후보 없음 상태; NG 탐색이 별표 gate를 우회하지 않음 |
| PARETO-09: 선택 연결 | 점의 case ID, 원값·목표·조건·출처가 상세와 일치 |
| PARETO-10: 갱신 | 오래된 조회/target 결과 무효화, 축 변경만으로 3목표 membership/별표가 바뀌지 않음 |
| PARETO-11: 예측 미연결 | predicted front placeholder에 가짜 점·성공 표시가 없음 |

Python 추출 계약, JavaScript 목적/비지배 계산, 화면 선택·연결선·상태 검증을 각각 기록한다. 과거 단위/desktop 테스트를 이번 Pareto 완료 증거로 재사용하지 않는다. 실제 surrogate/Zemax/학습/LLM 연결은 TBU다. Windows 공개 배포의 검증 범위는 [검증 기록](../../VALIDATION.md)을 따른다.

## 8. 구현과 검증 결과 · 2026-09-22

| 계층 | 소스 | 역할 |
|---|---|---|
| DB 추출 | `optics_ui/services/candidates.py` | 읽기 전용 일괄 조회, 실제 분석 조건·출처·cohort·제외 사유 |
| 목적·Pareto | `design/pareto.js` | 목표 검사, gate, 세 목적 loss, 비지배 집합과 가중 best |
| 화면 | `design/pareto-view.js` | mini/상세 그래프, 조건·축·선, 선택·적용·되돌리기 |
| 파일 연결 | `design/file-controller.js` | `candidate_data` 요청, DB 문맥과 늦은 응답 보호 |
| 세션 | `design/session-validation.js` | 선택적 `pareto_view` 검증·복원, 기존 세션 호환 |

테스트를 먼저 작성해 실패를 확인한 뒤 추출·목적 계산·요청 연결을 구현했다. 전체 Python **114개**, JavaScript **133개**가 통과했다. 이 중 신규 Pareto 추출은 22개, 목적 계산은 33개, 요청 연결은 6개이며 세션 검사는 2개를 추가했다.

2026-09-22 당시 Mac Python 3.12.14 / PySide6·Qt 6.11.2 앱에서 Pareto 화면·연결 15개와 내부 origin 검사, 기존 파일·세션·광선·Compute 회귀 22개가 통과했다. 두 실행 모두 JS 오류·외부 요청은 0건이었다. 1280×720과 1920×1080 고정 콘텐츠 크기로 그래프 배치를 확인했다. 이 기록은 당시 구현 검증이며 현재 공개 커밋의 재실행 결과는 [검증 기록](../../VALIDATION.md)에서 확인한다.

현재 합성 데모 DB의 500건 중 비교 가능한 같은 조건의 결과는 **148건**, 결측·비호환 등 제외는 **352건**이다. 현재 target JSON에서는 148건 모두 NG이며 PASS/NEAR_PASS는 0건이다. 허용 후보 기본 화면은 빈 상태를 정확히 표시하고, ‘미달 포함 탐색’에서 저장 결과의 trade-off를 볼 수 있다. 기본 Spot/FOV의 2D 비지배 점은 5개, 세 목적 비지배 점은 12개이며 합격 best 별표는 없다.

합격 후보 적용·2D/3목표 차이·NG gate는 **격리된 DB 복사본의 명시적 테스트 지표**로 검증했다. 이는 광학 성능 검증 자료가 아니다. 원본 데모 DB는 변경하지 않았다. 최종 화면 캡처는 원본 합성 DB의 NG 탐색으로 되돌린 상태다. 자동 파일 흐름은 OS 대화상자를 명시적 경로로 대체했으므로 실제 OS 파일 선택·drop, Windows 실기기 검증을 대신하지 않는다.

재현 명령(설치한 Python 사용, GUI 세션 필요):

```sh
python -m unittest discover -s tests -q
node --test tests/*.cjs
python scripts/smoke_pareto.py
python scripts/smoke_app.py --output-dir artifacts/pareto-regression --smoke-report examples/local-demo/training-report.json --smoke-target examples/local-demo/target.json
```
