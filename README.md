# FinSight AI — Context-Aware Financial Signal Analyst

한국 상장사의 재무 신호·밸류에이션·거시 맥락을 통합 분석하는 B2B analyst workflow tool.  
IB/PE·컨설팅·금융기관 대상. "숫자"가 아닌 **"지표 간 관계 + 외부 맥락"** 해석에 집중.

---

## 차별점

- Rule-based Signal Engine + LLM Narrative 구조 (LLM이 직접 데이터 검색 안 함)
- OpenDART 재무제표 → KPI 자동 계산 → Financial Signal → Evidence Layer → LLM 리포트

---

## 주요 서비스 (11개)

| 서비스 | 설명 | 주차 |
|---|---|---|
| Financial Statement Interpreter | 매출·이익·현금흐름·재무비율 자동 계산 | 1주차 ✅ |
| Valuation Multiple Interpreter | PER/PBR/PSR/시가총액 계산 및 해석 | 1주차 ✅ |
| Financial Conflict Engine | 지표 간 충돌 탐지 (고성장 + 현금흐름 악화 등) | 2주차 |
| Company Archetype Classifier | 기업 유형 분류 (High Growth / Value Trap 등 6종) | 2주차 |
| Macro Exposure Mapper | 금리·환율·경기 민감도 분석 | 2주차 |
| News / Disclosure Event Tagger | 공시·뉴스 이벤트 태깅 | 3주차 |
| Narrative-Fundamental Gap | 시장 내러티브 vs 재무 데이터 괴리 탐지 | 3주차 |
| Consumer Attention Signal | 네이버 검색 트렌드 기반 소비자 관심도 | 3주차 |
| Evidence Level & Confidence Score | 근거 강도 자동 산정 (High/Medium/Low/Needs Review) | 3주차 |
| Consensus CSV Analyzer | Bloomberg/DataGuide forward expectation 분석 | 3주차 |
| Multi-section Analyst Report | Beginner / Analyst / Investment Screening 모드 PDF | 4주차 |

---

## KPI 계산 항목 (14개)

| 구분 | KPI |
|---|---|
| 수익성 | 영업이익률(OPM), 순이익률, ROE, ROA |
| 재무 안정성 | 부채비율 |
| 현금흐름 | CFO Margin, CAPEX Ratio, FCF Margin |
| 성장성 | 매출 성장률, 영업이익 성장률 |
| 밸류에이션 | PER, PBR, PSR, 시가총액(EPS 역산 추정) |

---

## 파일 구조

```
finsight-ai/
├── app.py                  # Streamlit UI (캐싱·현재 시장 동향·KPI 테이블)
├── data_collector.py       # OpenDART + FinanceDataReader + ECOS 데이터 수집
│                           #   get_financials / get_market_data / get_macro_data
│                           #   get_current_market_data (현재 주가 + 1M/3M/6M 등락)
│                           #   get_naver_search_trend (Week 3 플레이스홀더)
│                           #   parse_consensus_csv (Week 3 플레이스홀더)
├── kpi_engine.py           # 14개 KPI 계산 엔진
├── signal_engine.py        # Financial Signal + Conflict 탐지 (2주차)
├── report_generator.py     # LLM 리포트 + fpdf2 PDF 생성 (4주차)
├── consensus_template.csv  # Consensus CSV 업로드 템플릿
├── requirements.txt
└── .env                    # API 키 (절대 커밋 금지)
```

---

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env   # API 키 5개 입력 후 저장
streamlit run app.py
```

---

## API 키 발급 (5개)

| 키 | 발급처 | 용도 |
|---|---|---|
| `DART_API_KEY` | https://opendart.fss.or.kr | 재무제표 데이터 |
| `ECOS_API_KEY` | https://ecos.bok.or.kr | 기준금리·국고채 |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com | LLM 리포트 생성 |
| `NAVER_CLIENT_ID` | https://developers.naver.com | 네이버 검색 트렌드 (Week 3) |
| `NAVER_CLIENT_SECRET` | https://developers.naver.com | 네이버 검색 트렌드 (Week 3) |

---

## 4주 로드맵

| 주차 | 기간 | 마일스톤 |
|---|---|---|
| 1주차 | 2026-05-21 ~ 2026-05-27 | ✅ **완료** — Data Foundation & KPI Engine |
| 2주차 | 2026-05-28 ~ 2026-06-03 | Signal, Conflict & Archetype Engine |
| 3주차 | 2026-06-18 ~ 2026-06-24 | External Context & Evidence Layer (2주 휴식 후 재개) |
| 4주차 | 2026-06-25 ~ 2026-07-01 | Analyst Report Generator & Streamlit Cloud 배포 |

## PoC 기준 기업

삼성전자 / 농심 / 에이피알

---

## Company Archetype 분류 (6종)

`High Growth Premium` / `Stable Compounder` / `Cyclical Recovery` / `Turnaround Candidate` / `Value Trap Risk` / `Cash Conversion Risk`

## Evidence Level

- **High** — 재무제표 + 공시/뉴스 근거 모두 확인
- **Medium** — 재무제표 근거 있으나 외부 근거 제한
- **Low** — 텍스트 기반 추론 중심
- **Needs Review** — 데이터 충돌/누락
