"""
app.py — FinSight AI Streamlit UI (Week 1 기반)

현재: 재무 데이터 + KPI 테이블 출력 (최소 UI)
예정: 2~4주차에 시각화·신호·리포트 패널 추가
"""

import streamlit as st
import pandas as pd
from data_collector import get_financials, get_market_data, get_macro_data
from kpi_engine import calculate_kpis

st.set_page_config(
    page_title="FinSight AI",
    page_icon="📊",
    layout="wide",
)

st.title("📊 FinSight AI")
st.caption("Context-Aware Financial Signal & Narrative Analyst")

# ─── 입력 영역 ───────────────────────────────────────────────
with st.sidebar:
    st.header("분석 설정")
    company = st.text_input("기업명 (한국어)", value="삼성전자", placeholder="삼성전자")
    years   = st.slider("분석 기간 (년)", min_value=3, max_value=7, value=5)
    run_btn = st.button("🔍 분석 시작", type="primary", use_container_width=True)

    st.divider()
    st.subheader("PoC 기준 기업")
    for name in ["삼성전자", "농심", "에이피알"]:
        if st.button(name, use_container_width=True):
            company = name
            run_btn = True

# ─── 분석 실행 ────────────────────────────────────────────────
if run_btn and company:
    with st.spinner(f"'{company}' 데이터 수집 중... (최초 실행 시 기업코드 로딩 ~30초)"):
        financials = get_financials(company, years=years)

    if not financials:
        st.error(f"'{company}'의 재무 데이터를 찾을 수 없습니다. 정확한 한국어 기업명을 입력하세요.")
        st.stop()

    with st.spinner("주가 및 거시 데이터 수집 중..."):
        year_list  = list(financials.keys())
        market_data = get_market_data(company, years=year_list)
        macro_data  = get_macro_data(years=year_list)

    kpis = calculate_kpis(financials, market_data)

    # ─── 탭 구성 ─────────────────────────────────────────────
    tab_fin, tab_kpi, tab_macro = st.tabs(["📋 재무제표", "📈 KPI", "🌍 거시 지표"])

    # ── 탭1: 재무제표 ────────────────────────────────────────
    with tab_fin:
        st.subheader(f"{company} 재무 데이터 (단위: 백만원)")

        ACCOUNT_LABELS = {
            "매출액": "매출액",
            "영업이익": "영업이익",
            "당기순이익": "당기순이익",
            "자산총계": "자산총계",
            "부채총계": "부채총계",
            "자본총계": "자본총계",
            "영업활동현금흐름": "영업활동CFO",
            "CAPEX": "CAPEX",
        }
        rows = {}
        for yr in sorted(financials.keys()):
            d = financials[yr]
            rows[yr] = {label: d.get(key) for key, label in ACCOUNT_LABELS.items()}

        df_fin = pd.DataFrame(rows).T
        df_fin.index.name = "연도"
        st.dataframe(
            df_fin.style.format("{:,.0f}", na_rep="N/A"),
            use_container_width=True,
        )

    # ── 탭2: KPI ─────────────────────────────────────────────
    with tab_kpi:
        st.subheader(f"{company} KPI 지표")

        KPI_LABELS = {
            "OPM":            ("영업이익률", "%"),
            "ROE":            ("ROE", "%"),
            "debt_ratio":     ("부채비율", "%"),
            "CFO_margin":     ("CFO Margin", "%"),
            "CAPEX_ratio":    ("CAPEX Ratio", "%"),
            "FCF_margin":     ("FCF Margin", "%"),
            "revenue_growth": ("매출 성장률", "%"),
            "op_income_growth": ("영업이익 성장률", "%"),
            "PER":            ("PER", "배"),
            "PBR":            ("PBR", "배"),
        }

        kpi_rows = {}
        for yr in sorted(kpis.keys()):
            k = kpis[yr]
            kpi_rows[yr] = {
                f"{label}({unit})": (f"{k[key]:.2f}" if k.get(key) is not None else "N/A")
                for key, (label, unit) in KPI_LABELS.items()
            }

        df_kpi = pd.DataFrame(kpi_rows).T
        df_kpi.index.name = "연도"
        st.dataframe(df_kpi, use_container_width=True)

        # 주석
        if any(kpis[yr].get("PER") is None for yr in kpis):
            st.caption(
                "PER·PBR은 상장사만 표시. EPS가 음수이거나 주가 데이터가 없는 연도는 N/A."
            )

    # ── 탭3: 거시 지표 ───────────────────────────────────────
    with tab_macro:
        st.subheader("한국 거시 지표")

        macro_rows = {}
        for yr in sorted(macro_data.keys()):
            m = macro_data[yr]
            macro_rows[yr] = {
                "기준금리(%)":    m.get("base_rate"),
                "국고채 10년물(%)": m.get("ktb10y"),
                "USD/KRW(원)":  m.get("usd_krw"),
            }

        if macro_rows:
            df_macro = pd.DataFrame(macro_rows).T
            df_macro.index.name = "연도"
            st.dataframe(
                df_macro.style.format("{:.2f}", na_rep="N/A"),
                use_container_width=True,
            )
        else:
            st.info("거시 데이터를 불러올 수 없습니다.")
