# FinSight

증권사 리포트와 DART 재무를 분석하는 도구. **두 개의 앱**으로 구성된다.

| 앱 | 대상 | 무엇을 하나 | 실행 |
|----|------|-------------|------|
| **app.py** | 첫 화면 | 애널리스트용과 개인투자자용을 버튼으로 선택 | `streamlit run app.py` |
| **report_validator/app_finsight.py** | 개인투자자 | 증권사 리포트를 DART·KRX·목표가 평균·공시·뉴스로 재검증, 신뢰도 100점 | `streamlit run report_validator/app_finsight.py` |
| **analyst_workbench/app.py** | 애널리스트 | DART 재무 전수 분석, 7탭 워크벤치 | `streamlit run analyst_workbench/app.py` |

두 앱은 **같은 엔진**(`kpi_engine`, `diagnostics`, `mode_views`)을 공유한다.
개인투자자용은 그 위에 리포트 신뢰도 검증 출력층을 얹은 것이다.

---

## 1️⃣ report_validator/app_finsight.py — 리포트 신뢰도 검증 (개인투자자용)

**증권사 리포트의 목표가와 투자의견을 DART 재무·공시, KRX 주가·수급, 증권사 목표가 평균, 발행 이후 공시·뉴스·지분 변동으로 다시 대조해 신뢰도 점수와 종합 해석 보고서를 제공한다.**

자세한 설명은 [report_validator/README.md](report_validator/README.md) 참고.

### 빠른 시작
```bash
streamlit run report_validator/app_finsight.py
```

### 핵심
- 분포 위치: 리포트 목표가가 시장 평균 대비 얼마나 공격적인지 확인
- 발행 후 변화: 발행 이후 주가·수급·공시·뉴스 변화가 전제를 바꿨는지 확인
- 가정 검증: 목표가에 필요한 EPS 성장률을 역산해 과거 실적과 대조

신뢰도 등급: **75+ A · 60+ B · 45+ C · 30+ D · 미만 E**

---

## 2️⃣ analyst_workbench/app.py — DART 분석 워크벤치 (애널리스트용)

**DART 분기 재무 → 이상 탐지 → 원인 추적 → DCF 검증 → HTML 리포트·Excel 생성.**

자세한 설명은 [analyst_workbench/README.md](analyst_workbench/README.md) 참고.

### 빠른 시작
```bash
pip install -r requirements.txt
streamlit run analyst_workbench/app.py
```

첫 화면에서 두 버전을 비교하려면 루트에서 실행합니다.

```bash
streamlit run app.py
```

애널리스트 워크벤치만 바로 열려면 다음 경로를 사용합니다.

```bash
streamlit run analyst_workbench/app.py
```

### 7개 탭
1. 리포트 — 발간형 투자 리포트
2. 투자판단 — 실적·기대·수급·촉매 + 확인 포인트
3. 실적 트래커 — 분기 KPI·추세
4. 이상 탐지 — 13개 지표 전수 판정 + 내부 원인
5. 동종기업 — peer 중앙값 비교
6. 가치평가 — DCF·PER·EV/EBITDA 교차검증
7. 근거·출처 — 데이터 커버리지·품질

---

## 📁 폴더 구조

```
finsight-ai/
├── app.py                   ← 첫 화면
│
├── report_validator/        ← 개인투자자용 (3축)
│   ├── app_finsight.py
│   ├── finsight_modules.py  (분포·역산)
│   ├── timeline_module.py   (발행 후 변화)
│   ├── scoring_module.py    (3축 점수 통합)
│   ├── demo_data.py
│   └── README.md            ← 자세한 설명
│
├── analyst_workbench/       ← 애널리스트용 (7탭)
│   ├── app.py
│   ├── signal_engine.py     (이상 탐지·원인)
│   ├── valuation_model.py   (Bottom-up 모델)
│   ├── report_templates.py  (HTML 리포트)
│   ├── report_generator.py  (Excel 생성)
│   └── README.md            ← 자세한 설명
│
├── core/                    ← 공유 엔진
│   ├── kpi_engine.py
│   ├── diagnostics.py
│   ├── data_collector.py
│   └── mode_views.py
│
└── lib/                     ← 유틸
    ├── research_reference.py
    └── validation_agenda.py
```

---

## 🔧 설치

```bash
pip install -r requirements.txt
```

### .env (선택)
```dotenv
DART_API_KEY=발급키          # 필수
ECOS_API_KEY=발급키          # 권장
NAVER_CLIENT_ID=값           # 권장
NAVER_CLIENT_SECRET=값
KRX_ID=계정 / KRX_PW=비번    # 수급
FRED_API_KEY=발급키          # 환율
```

DART 키만 필수. 나머지는 없으면 해당 기능을 건너뜁니다.

---

## 📖 더 알아보기

- [개인투자자용 3축 검증](report_validator/README.md)
- [애널리스트용 7탭 분석](analyst_workbench/README.md)

---

## 원칙

✅ **사실만** — 의견을 새로 만들지 않는다.

✅ **추천 금지** — "사세요/파세요"는 말하지 않는다.

✅ **판단은 사용자** — 도구는 맥락만 제공한다.

증권사 리포트의 목표가와 투자의견을 **DART 재무·공시, KRX 주가·수급, 증권사 목표가 평균, 발행 이후 공시·뉴스·지분 변동으로 재검증**하는 개인투자자용 도구입니다.
최종 결과는 리포트 신뢰도 100점과 종합 해석 보고서로 제공합니다.

### 빠른 시작

```bash
streamlit run report_validator/app_finsight.py
```

API 키 없이 농심 데모 데이터로 즉시 작동합니다. (DART_API_KEY가 있으면 실데이터 자동 연결)

### 3축 검증

| 축 | 질문 | 데이터 | 점수 |
|----|------|--------|------|
| **① 공간축** | 이 목표가, 다른 증권사보다 튀나? | 목표가 분포 (증권사 비교) | 30점 |
| **② 시간축** | 발행 후 상황 바뀌었나? | 실적·수급·주가 (시계열) | 30점 |
| **③ 논리축** ★ | 이 목표가 숫자가 성립하나? | 과거 EPS vs 필요 성장률 | 40점 |

**신뢰도 등급**: 75+ A · 60+ B · 45+ C · 30+ D · 미만 E

### 핵심 차별점

- **변동성 보정 (모듈3)**: 단순 평균 대신 중앙값 사용. 기저효과(한 해 +119%)로 오염된 평균을 걸러냅니다.
  예: 농심은 평균 성장 +36%지만, 실제 중앙값은 +5%. → "낙관" 판정
- **역산 계산**: 목표가를 "필요 EPS 성장률"로 역산해 과거 실적과 대조합니다.
- **수급 괴리**: "신호"가 아니라 "리포트 의견 vs 시장 행동의 괴리"만 제시합니다.

### 파일 구성

```
report_validator/
  app_finsight.py          # 3축 메인 UI + 신뢰도 카드
  scoring_module.py        # 신뢰도 점수 + 평가 의견 (모듈4)
  finsight_modules.py      # 분포·역산 함수 (모듈1·3)
  timeline_module.py       # 시점 정합성·수급 (모듈2)
  demo_data.py             # 농심 데모 (폴백용, 지우지 말 것)
```

**기존 엔진 (그대로 보존)**: kpi_engine, diagnostics, mode_views

### 사용자 입력

사이드바에서:
- **종목명/코드** (필수) → DART 자동 수집
- **리포트 정보** (필수) → 증권사, 발행일, 목표가, 의견

DART 실적·주가·수급은 자동 수집됩니다.

### 검증 기준 (농심)

```
신뢰도: 37/100 (D등급)
① 공간축: 14/30 — 8개 중 상위 12%
② 시간축: 17/30 — 발행 36일, 외국인 -180억 순매도
③ 논리축: 6/40 — 필요 +32% vs 보통 해 +5%

→ "한화투자증권 목표가 550,000원은 그대로 믿기 어렵습니다"
```

### 핵심 원칙

- **사실만**: 의견을 새로 만들지 않습니다.
- **추천금지**: "사세요/파세요"는 절대 말하지 않습니다. "신뢰도"만.
- **판단은 투자자**: FinSight는 맥락만 제공합니다.

📖 자세한 설계 논리는 [report_validator/README.md](report_validator/README.md)와 [files/problem_definition.md](files/problem_definition.md) 참고

---

## 분석 순서

1. 최근 8~24개 분기 DART 재무 수집(권장 12분기, 사이드바에서 선택)
2. 성장·수익성·현금흐름·운전자본·투자·재무안정성 13개 지표 전수 스캔
3. 자체 과거 범위와 절대 기준을 벗어난 항목 선별
4. 원가율·판관비율·매출채권·재고·매입채무 등 DART 계정으로 내부 원인 추적
5. 자동 추천 동종기업 중앙값과 비교해 기업 고유 문제인지 업종 공통 현상인지 구분
6. 관련 키워드가 확인된 DART 공시·지분공시·뉴스·블로그를 정황 후보로 연결
7. 확인된 증거를 매출 성장률·영업이익률·CAPEX·WACC·영구성장률 가정에 보수적으로 반영
8. DCF·PER·EV/EBITDA·리서치 참고값을 교차검증해 보수/기준/낙관 적정가 범위와 추정치 편차를 표시

## 화면 구성

| 탭 | 실무 목적 |
|---|---|
| `01 리포트` | 투자의견(정량)·산정가치·핵심 결론을 담은 발간형 리포트를 차트·표로 한 화면에 렌더 |
| `02 투자판단` | 실적·기대치·수급·촉매를 분리하고 다음 분기 확인 항목의 “확인되면/안 되면/모델 반영”까지 제시 |
| `03 실적 트래커` | 분기 원본, QoQ/YoY, 매출·OPM·CFO 추세, 최신 분기 변화 해석, 외부 검증 데이터 연결 상태와 결측 확인 |
| `04 이상 탐지·원인` | 13개 지표 전수 판정과 DART 내부 원인·근거·확인 절차 확인 |
| `05 동종기업 검증` | 자동 추천 peer set의 최신 중앙값, 상대 격차, 업종 대비 우위·열위 해석 확인 |
| `06 가치평가` | Bottom-up 매출·판관비·WACC Build, 외부 변수 DCF 조정, DCF·PER·EV/EBITDA 교차검증, 베타·터미널가치 guardrail |
| `07 근거·출처` | 데이터 커버리지, 외부 API 연결 상태, DART 공시·뉴스 원문, 결측·품질 점검 |

상단 고정 액션 영역에서 `📄 발간 리포트` HTML과 `📊 모델 워크북` Excel을 바로 내려받을 수 있습니다. HTML 리포트는 브라우저에서 열고 인쇄 기능으로 PDF 저장하는 흐름을 기준으로 합니다.

## 자동 수집 범위

- 손익: 매출, 영업이익, 순이익, 매출원가, 판관비
- 현금흐름·투자: CFO, 유형자산 취득액, FCF
- 운전자본: 매출채권, 재고, 매입채무, 회전일수
- 재무상태: 유동자산·부채, 총자산·부채·자본, 부채비율
- 자본구조: DART 발행주식수, 이자부채, 현금, 순차입금
- 시장·거시(기본 연결): 최근 종가, 베타, 무위험수익률(ECOS), World Bank 매크로
- 시장·거시(키 설정 시 연결): KRX 수급(`KRX_ID`/`KRX_PW`), FRED USD/KRW·원자재 proxy(`FRED_API_KEY`)
- 로드맵(미구현 — 현재는 연결 상태와 사용처만 표시): KOSIS(국내 산업·소비), KAMIS(원재료 가격), Trading Economics(국가별 매크로), UN Comtrade/KATI(수출입·해외 물량 proxy). 키를 넣어도 아직 데이터 fetch는 연결되지 않습니다.

연결재무제표를 우선하며, 누적 flow는 개별 분기로 환산합니다. 계정 결측은 임의 보정하지 않고 `Needs Review`로 표시합니다.

## 동종기업 추천

농심 등 주요 테스트 기업은 검증된 업종 그룹에서 2개사를 자동 추천합니다. 자동 추천을 끄면 직접 선택할 수 있습니다. 추천 근거가 없는 기업은 임의로 비슷한 회사를 만들어내지 않고 `직접 검토 필요`로 표시합니다.

## 발간형 HTML 리포트

상단 `📄 발간 리포트` 버튼은 `.html` 파일을 생성합니다. 리포트에는 다음 내용이 들어갑니다.

- 이번 실적 브리핑: 최신 분기 매출·마진·현금흐름 변화와 핵심 해석
- 외부 변수와 시장 맥락: 수급, 환율, 원재료, 뉴스·공시 정황의 의미와 한계
- 논점 지도: 확인된 사실, 해석, 근거를 분리한 투자 판단 구조
- 실적의 질: 마진 브릿지, CFO/FCF, 이상 신호 우선순위
- 가치평가: DCF·멀티플·리서치 참고값을 함께 본 적정가 범위
- 외부 변수 DCF 반영: 수급·원가·환율·테마를 WACC/OPM/CAPEX/성장률 가정에 어떻게 보수적으로 반영했는지
- 주가 괴리와 체크포인트: 다음 분기 확인되면/안 되면/모델에 어떻게 반영할지

## Analyst Workbook

다운로드 Excel은 다음 12개 시트로 구성됩니다. 단일 OPM 추정이 아니라 매출·원가를
Bottom-up으로 재구성하는 농심 DCF 레퍼런스 로직을 그대로 옮겼습니다.

| 시트 | 내용 |
|---|---|
| `00 Cover` | 핵심 판단, 사실/해석 분리, 방법별 가치 차트 |
| `01 Quarterly` | 분기 원본·파생 KPI·QoQ/YoY |
| `02 Earnings Bridge` | 마진 변동 분해, 컨센서스 기대 괴리, 최신 분기 so-what 해석 |
| `03 Thesis Evidence` | 논점 트리, 확인되면/안 되면/모델 반영, 신뢰도순 외부 정황 요약 |
| `04 Peers Multiples` | 동종기업 벤치마크와 멀티플 교차검증 |
| `05 DCF` | 수정 가능한 가정과 5개년 FCFF·WACC·영구가치 수식 |
| `06 Scenarios` | Bear/Base/Bull 수식 재계산 |
| `07 Checks Sources` | 데이터 품질, 모델 점검, 출처와 버전 |
| `08 Revenue Build` | 매출 = 산업성장률(동종 합산 proxy) + 점유율 변화 / CPI 교차검증 |
| `09 Cost Structure` | 판관비 = 인건비성(임금)+변동비(매출)+고정비(CPI)+대손 → Bottom-up OPM, 감가상각 배분 |
| `10 WACC & Beta` | 동종기업 베타 unlever→relever, CAPM·WACC 브릿지 |
| `11 Causal Read` | 주가 기여 분해와 이상신호별 원인 해석(근거 강도 표기) |

입력 셀(파란색·노란색)과 수식 셀을 구분하며, 값이 아니라 수식이 남도록 생성합니다.
`09 Cost Structure`의 Bottom-up Implied OPM을 `05 DCF`의 OPM 가정과 대조해 마진의 현실성을 점검합니다. `11 Causal Read`는 “이상 신호 발견”에서 멈추지 않고, 내부 원인·외부 정황·다음 확인 액션을 함께 남깁니다.

## 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run analyst_workbench/app.py
```

`.env` 예시:

```dotenv
# 필수
DART_API_KEY=발급키
# 권장(있으면 거시·기대치·정황 보강)
ECOS_API_KEY=발급키
NAVER_CLIENT_ID=발급값
NAVER_CLIENT_SECRET=발급값
# 키 설정 시 실제 연결되는 외부 데이터
KRX_ID=KRX계정
KRX_PW=KRX비밀번호
FRED_API_KEY=발급키
# 로드맵(키를 넣어도 아직 데이터 fetch 미구현 — 상태 표시만)
KOSIS_API_KEY=발급키
KOSIS_FOOD_TABLE_ID=식품/소비 통계표ID
KAMIS_API_ID=발급ID
KAMIS_API_KEY=발급키
TRADING_ECONOMICS_KEY=발급키
UN_COMTRADE_KEY=발급키
```

DART 키는 필수입니다. ECOS·뉴스 키가 없으면 가능한 분석은 계속하고, 누락된 정황은 화면과 Excel `07 Checks Sources`에 명시합니다. KRX 수급(`KRX_ID`/`KRX_PW`)과 FRED(`FRED_API_KEY`)는 키와 패키지가 준비되면 자동 연결을 시도합니다. KOSIS/KAMIS/Trading Economics/UN Comtrade는 fetch 구현이 아직 없어, 현재는 `07 근거·출처`와 Excel `07 Checks Sources`에 연결 상태·사용처만 표시되고 분석에는 반영되지 않습니다(로드맵).

## 주요 파일

| 파일 | 역할 |
|---|---|
| `app.py` | 첫 화면 |
| `analyst_workbench/app.py` | 일곱 탭 분석 워크플로우 |
| `core/data_collector.py` | DART·시장·거시·뉴스 수집과 peer 추천 |
| `core/kpi_engine.py` | 분기 KPI와 증감률 계산 |
| `analyst_workbench/signal_engine.py` | 전수 이상 탐지, 내부 원인, peer·맥락 연결 |
| `analyst_workbench/business_focus.py` | 이상 신호를 DCF 가정으로 변환 |
| `core/diagnostics.py` | driver-based DCF, 멀티플 교차검증, 민감도 계산 |
| `analyst_workbench/excel_builder.mjs` | 수식 기반 12시트 Analyst Workbook 생성 |
| `analyst_workbench/report_generator.py` | Streamlit 다운로드용 Excel 브리지 |
| `analyst_workbench/report_templates.py` | 발간형 투자 리포트 HTML과 in-app 리포트 모델 생성 |
| `analyst_workbench/valuation_model.py` | 매출·판관비·WACC Bottom-up Build |
| `analyst_workbench/interpretation.py` | 이상신호·주가 괴리의 인과 해석과 확인 절차 |
| `analyst_workbench/ui_components.py` | CSS·차트·발간 리포트·랜딩 등 화면 컴포넌트 |

## 한계

DART 표준계정으로 확인되지 않는 제품·지역별 매출, 세부 원재료 단가, 일회성 비용의 정확한 성격은 주석·IR 원문 검토가 필요합니다. 외부 뉴스·블로그는 관련 키워드가 있는 정황 후보이며 인과관계의 증거로 단독 사용하지 않습니다. 외부 변수는 확정 실적이 아니므로 DCF에는 보수적인 조정 레이어로만 반영합니다. ‘01 리포트’의 정량 투자의견은 교차검증 산정가치와 현재가의 괴리에서 기계적으로 도출한 참고치로, 공식 투자의견이 아닙니다.
