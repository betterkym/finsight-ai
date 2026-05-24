# FinSight AI — Context-Aware Financial Signal Analyst

한국 상장사의 재무 신호·밸류에이션·거시 맥락을 통합 분석하는 B2B analyst workflow tool.

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env   # API 키 입력
streamlit run app.py
```

## 구조

```
finsight-ai/
├── data_collector.py  # OpenDART + FinanceDataReader + ECOS 데이터 수집
├── kpi_engine.py      # PER/PBR/ROE/OPM/CFO margin/CAPEX ratio 계산
├── signal_engine.py   # Financial Signal + Conflict 탐지 (2주차)
├── report_generator.py # LLM 리포트 생성 (4주차)
└── app.py             # Streamlit UI
```

## API 키 발급
- DART: https://opendart.fss.or.kr
- ECOS: https://ecos.bok.or.kr
- Anthropic: https://console.anthropic.com
