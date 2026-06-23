# FinSight — DART Filing Analysis Workbench

기업명 하나로 DART 분기 재무를 수집하고, 핵심 계정 전수 이상 탐지 → DART 내부 원인 추적 → 동종기업 검증 → 관련 공시·뉴스 맥락 → DCF 가정 연결까지 수행하는 Streamlit 분석 도구입니다.

> 원칙: 근거가 없으면 원인을 확정하지 않습니다. 웹은 판단 순서를 안내하고, Excel은 검증 가능한 수식과 출처를 남깁니다.

## 분석 순서

1. 최근 8개 또는 12개 분기 DART 재무 수집
2. 수익성·현금흐름·운전자본·투자·재무안정성 13개 지표 전수 스캔
3. 자체 과거 범위와 절대 기준을 벗어난 항목 선별
4. 원가율·판관비율·매출채권·재고·매입채무 등 DART 계정으로 내부 원인 추적
5. 자동 추천 동종기업 중앙값과 비교해 기업 고유 문제인지 업종 공통 현상인지 구분
6. 관련 키워드가 확인된 DART 공시와 외부 뉴스만 맥락으로 연결
7. 확인된 증거를 매출 성장률·영업이익률·FCFF 전환율 가정에 반영

## 화면 구성

| 탭 | 실무 목적 |
|---|---|
| `01 투자판단` | 실적·기대치·수급·촉매를 분리하고 다음 분기 확인 항목의 “확인되면/안 되면/모델 액션”까지 제시 |
| `02 실적 트래커` | 분기 원본, QoQ/YoY, 매출·OPM·CFO 추세, 최신 분기 변화 해석과 결측 확인 |
| `03 이상 탐지·원인` | 13개 지표 전수 판정과 DART 내부 원인·근거·검증 레시피 확인 |
| `04 동종기업 검증` | 자동 추천 peer set의 최신 중앙값과 상대 격차 확인 |
| `05 가치평가` | 바텀업 매출·판관비·WACC 빌드, DCF·PER·EV/EBITDA 교차검증, 베타 guardrail |
| `06 Excel·근거` | 재현 가능한 Analyst Workbook과 Markdown 요약 다운로드 |

## 자동 수집 범위

- 손익: 매출, 영업이익, 순이익, 매출원가, 판관비
- 현금흐름·투자: CFO, 유형자산 취득액, FCF
- 운전자본: 매출채권, 재고, 매입채무, 회전일수
- 재무상태: 유동자산·부채, 총자산·부채·자본, 부채비율
- 자본구조: DART 발행주식수, 이자부채, 현금, 순차입금
- 시장·거시: 최근 종가, 베타, 무위험수익률, KRX 수급, World Bank/FRED proxy 등
- 확장 API 준비: KOSIS(국내 산업·소비), KAMIS(원재료 가격), Trading Economics(국가별 매크로), UN Comtrade/KATI(수출입·해외 물량 proxy)

연결재무제표를 우선하며, 누적 flow는 개별 분기로 환산합니다. 계정 결측은 임의 보정하지 않고 `Needs Review`로 표시합니다.

## 동종기업 추천

농심 등 주요 테스트 기업은 검증된 업종 그룹에서 2개사를 자동 추천합니다. 자동 추천을 끄면 직접 선택할 수 있습니다. 추천 근거가 없는 기업은 임의로 비슷한 회사를 만들어내지 않습니다.

## Analyst Workbook

다운로드 Excel은 다음 12개 시트로 구성됩니다. 단일 OPM 추정이 아니라 매출·원가를
바텀업으로 재구성하는 농심 DCF 레퍼런스 로직을 그대로 옮겼습니다.

| 시트 | 내용 |
|---|---|
| `00 Cover` | 핵심 판단, 사실/가설 분리, 방법별 가치 차트 |
| `01 Quarterly` | 분기 원본·파생 KPI·QoQ/YoY |
| `02 Earnings Bridge` | 마진 변동 분해, 컨센서스 기대 괴리, 최신 분기 so-what 해석 |
| `03 Thesis Evidence` | 가설 트리, 확인되면/안 되면/모델 액션, 신뢰도순 외부 맥락 요약 |
| `04 Peers Multiples` | 동종기업 벤치마크와 멀티플 교차검증 |
| `05 DCF` | 수정 가능한 가정과 5개년 FCFF·WACC·영구가치 수식 |
| `06 Scenarios` | Bear/Base/Bull 수식 재계산 |
| `07 Checks Sources` | 데이터 품질, 모델 점검, 출처와 버전 |
| `08 Revenue Build` | 매출 = 산업성장률(동종 합산 proxy) + 점유율 변화 / CPI 교차검증 |
| `09 Cost Structure` | 판관비 = 인건비성(임금)+변동비(매출)+고정비(CPI)+대손 → 바텀업 OPM, 감가상각 배분 |
| `10 WACC & Beta` | 동종기업 베타 unlever→relever, CAPM·WACC 브릿지 |
| `11 Causal Read` | 주가 기여 분해와 이상신호별 원인 해석(근거 강도 표기) |

입력 셀(파란색·노란색)과 수식 셀을 구분하며, 값이 아니라 수식이 남도록 생성합니다.
`09 Cost Structure`의 바텀업 Implied OPM을 `05 DCF`의 OPM 가정과 대조해 마진의 현실성을 점검합니다.

## 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

`.env` 예시:

```dotenv
DART_API_KEY=발급키
ECOS_API_KEY=발급키
NAVER_CLIENT_ID=발급값
NAVER_CLIENT_SECRET=발급값
KRX_ID=KRX계정
KRX_PW=KRX비밀번호
KOSIS_API_KEY=발급키
KOSIS_FOOD_TABLE_ID=식품/소비 통계표ID
KAMIS_API_ID=발급ID
KAMIS_API_KEY=발급키
FRED_API_KEY=발급키
TRADING_ECONOMICS_KEY=발급키
UN_COMTRADE_KEY=발급키
```

DART 키는 필수입니다. ECOS·뉴스·외부 데이터 키가 없거나 연결되지 않으면 가능한 분석은 계속하고, 누락된 맥락은 화면과 Excel `07 Checks Sources`에 명시합니다. KOSIS/KAMIS/UN Comtrade는 키 외에도 통계표·품목·HS코드 매핑이 있어야 실무 가정 근거로 승격됩니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| `app.py` | 여섯 탭 분석 워크플로우 |
| `data_collector.py` | DART·시장·거시·뉴스 수집과 peer 추천 |
| `kpi_engine.py` | 분기 KPI와 증감률 계산 |
| `signal_engine.py` | 전수 이상 탐지, 내부 원인, peer·맥락 연결 |
| `business_focus.py` | 이상 신호를 DCF 가정으로 변환 |
| `diagnostics.py` | driver-based DCF, 멀티플 교차검증, 민감도 계산 |
| `excel_builder.mjs` | 수식 기반 12시트 Analyst Workbook 생성 |
| `report_generator.py` | Streamlit 다운로드용 Excel 브리지 |

## 한계

DART 표준계정으로 확인되지 않는 제품·지역별 매출, 세부 원재료 단가, 일회성 비용의 정확한 성격은 주석·IR 원문 검토가 필요합니다. 외부 뉴스는 관련 키워드가 있는 맥락 후보이며 인과관계의 증거로 단독 사용하지 않습니다.
