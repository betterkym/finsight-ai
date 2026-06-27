# FinSight

FinSight는 증권사 리포트를 그대로 받아들이기 전에, 리포트의 목표가·투자의견·본문 의견을 실제 데이터와 다시 맞춰보는 도구입니다. 기존 애널리스트 워크벤치의 재무 스캔, 공시 확인, 수급·주가 해석 로직을 개인투자자용 리포트 검증 흐름으로 재구성했습니다.

## 앱 구조

| 앱 | 대상 | 역할 | 실행 |
|----|------|------|------|
| `app.py` | 데모 진입점 | 기본은 리포트 신뢰도 검증, `Analyst Mode` 버튼으로 기존 워크벤치 진입 | `streamlit run app.py` |
| `report_validator/app_finsight.py` | 개인투자자 | 여러 증권사 리포트를 업로드해 목표가·본문 의견·발행 이후 변화를 비교 검증 | `streamlit run report_validator/app_finsight.py` |
| `analyst_workbench/app.py` | 애널리스트 | DART 재무 전수 분석, 이상 탐지, 가치평가, HTML·Excel 리포트 생성 | `streamlit run analyst_workbench/app.py` |

두 앱은 `core/kpi_engine.py`, `core/diagnostics.py`, `core/mode_views.py`를 공유합니다. 개인투자자용 화면은 기존 분석 엔진을 버린 것이 아니라, 증권사 리포트를 검증하는 출력층을 새로 얹은 구조입니다.

## 리포트 신뢰도 검증 흐름

1. **리포트 기준값 확정**
   업로드 PDF 또는 사용자가 입력한 증권사, 발행일, 투자의견, 목표가를 기준점으로 둡니다. 여러 PDF가 들어오면 목표가·투자의견을 리포트별로 분리해 비교합니다.

2. **목표가 편차**
   리포트 목표가가 증권사 목표가 평균과 업로드 리포트 묶음 안에서 어느 위치인지 확인합니다. 평균에서 멀수록 더 강한 근거가 필요합니다.

3. **발행 이후 괴리**
   발행일 이후 현재 주가, 외국인·기관 수급, 공시·지분 변동을 붙여 리포트가 나온 뒤 전제가 달라졌는지 봅니다.

4. **필요 실적**
   목표가가 성립하려면 EPS가 얼마나 좋아져야 하는지 역산하고, 과거 평균·중앙값 성장률과 비교합니다.

5. **본문 의견 검증**
   PDF 본문에서 반복되는 실적·마진·수급·현금흐름 관련 의견을 뽑아 리포트끼리 비교하고, DART 재무·주가·수급과 대조합니다.

6. **종합평가와 보고서**
   목표가 편차, 발행 이후 괴리, 필요 실적을 100점 기준으로 환산하고, 본문 의견과 기존 애널리스트 엔진의 객관분석 차감을 더해 최종 신뢰도와 HTML/PDF 보고서를 만듭니다.

## 연결 데이터

| 데이터 | 쓰임 |
|--------|------|
| 업로드 PDF | 목표가·투자의견·본문 의견 추출, 리포트별 비교 |
| 네이버 금융 리서치/목표가 평균 | 증권사 평균 목표가와 리포트 목록 확인 |
| OpenDART | 분기 재무, 발행주식수, 공시, 지분 변동 확인 |
| KRX/pykrx | 발행일 주가, 현재가, 외국인·기관 수급 확인 |
| Naver Search | 발행 이후 뉴스와 시장 이슈 보조 확인 |
| FRED/ECOS/World Bank 등 | 환율·거시·원가 변수 보조 해석 |

API 키가 없거나 외부 데이터 호출이 실패한 항목은 해당 축만 보조값으로 계산하며, 실제 반영 상태는 앱의 `출처 및 근거` 탭에서 확인합니다.

## 빠른 시작

```bash
pip install -r requirements.txt
streamlit run app.py
```

개인투자자용 화면만 바로 열려면:

```bash
streamlit run report_validator/app_finsight.py
```

기존 애널리스트 워크벤치만 바로 열려면:

```bash
streamlit run analyst_workbench/app.py
```

## 폴더 구조

```text
finsight-ai/
├── app.py
├── report_validator/
│   ├── app_finsight.py
│   ├── finsight_modules.py
│   ├── timeline_module.py
│   ├── scoring_module.py
│   ├── report_assessor.py
│   ├── evidence_audit.py
│   ├── retail_report.py
│   └── demo_data.py
├── analyst_workbench/
│   ├── app.py
│   ├── signal_engine.py
│   ├── valuation_model.py
│   ├── report_templates.py
│   └── report_generator.py
├── core/
│   ├── kpi_engine.py
│   ├── diagnostics.py
│   ├── data_collector.py
│   └── mode_views.py
└── lib/
    ├── research_reference.py
    └── validation_agenda.py
```

## 원칙

- **리포트 검증이지 종목 추천이 아닙니다.** 결과는 매수·매도 의견이 아니라 리포트 신뢰도입니다.
- **숫자와 원문 근거를 남깁니다.** 목표가, 발행일, 주가, DART 재무, 수급, PDF 본문이 어느 판단에 쓰였는지 추적할 수 있어야 합니다.
- **기존 분석 엔진을 유지합니다.** 개인투자자용 화면은 애널리스트 워크벤치의 재무·공시·수급 분석 로직을 리포트 검증 관점으로 바꾼 것입니다.
