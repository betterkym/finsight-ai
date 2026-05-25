"""
app.py — FinSight AI Streamlit UI

현재 (1주차): 재무제표·KPI·현재 시장 동향·거시 지표 출력
예정 (2~4주차): Signal Engine, Conflict Engine, Analyst Report
"""

import streamlit as st
import pandas as pd
from data_collector import (
    get_financials, get_market_data, get_macro_data, get_current_market_data,
)
from kpi_engine import calculate_kpis

st.set_page_config(
    page_title="FinSight AI",
    page_icon="📊",
    layout="wide",
)

# ─── 캐싱 래퍼 ─────────────────────────────────────────────────────────────────
# st.cache_data는 직렬화 가능한(hashable) 인자만 받으므로 list → tuple 변환

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_financials(company: str, years: int) -> dict:
    return get_financials(company, years=years)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_market_data(company: str, years_tuple: tuple) -> dict:
    return get_market_data(company, years=list(years_tuple))


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_macro_data(years_tuple: tuple) -> dict:
    return get_macro_data(years=list(years_tuple))


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_current_market(company: str) -> dict:
    return get_current_market_data(company)


# ─── KPI 포매터 ────────────────────────────────────────────────────────────────

def _fmt_kpi(value, key: str, unit: str) -> str:
    if value is None:
        return "N/A"
    if key == "market_cap":
        # 백만원 → 조원 변환 표시 (1조 = 1_000_000 백만원)
        return f"{value / 1_000_000:.1f}"
    return f"{value:.2f}"


# ─── UI ────────────────────────────────────────────────────────────────────────

st.title("📊 FinSight AI")
st.caption("Context-Aware Financial Signal & Narrative Analyst")

# ─── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("분석 설정")
    company = st.text_input("기업명 (한국어)", value="삼성전자", placeholder="삼성전자")
    years   = st.slider("분석 기간 (년)", min_value=3, max_value=7, value=5)
    run_btn = st.button("🔍 분석 시작", type="primary", use_container_width=True)

    st.divider()
    st.subheader("PoC 기준 기업")
    for poc_name in ["삼성전자", "농심", "에이피알"]:
        if st.button(poc_name, use_container_width=True):
            company = poc_name
            run_btn = True

    st.divider()
    st.subheader("고급 기능 (Week 3 예정)")

    st.caption("📊 Consensus CSV 업로드")
    uploaded_csv = st.file_uploader(
        "Bloomberg/DataGuide CSV",
        type="csv",
        help="consensus_template.csv 형식으로 업로드하세요.",
    )
    if uploaded_csv is not None:
        st.info("Consensus 분석 기능은 Week 3에 구현됩니다.\n템플릿: consensus_template.csv")

    st.caption("🔍 네이버 검색 트렌드")
    st.text_input(
        "검색 키워드",
        placeholder="기업명 또는 브랜드명",
        disabled=True,
        help="Naver DataLab API 연동은 Week 3에 구현됩니다.",
    )

# ─── 분석 실행 ─────────────────────────────────────────────────────────────────
if run_btn and company:

    with st.spinner(f"'{company}' 재무 데이터 수집 중... (최초 실행 시 기업코드 로딩 ~30초)"):
        financials = _cached_financials(company, years)

    if not financials:
        st.error(f"'{company}'의 재무 데이터를 찾을 수 없습니다. 정확한 한국어 기업명을 입력하세요.")
        st.stop()

    with st.spinner("주가·거시 데이터 수집 중..."):
        year_list   = tuple(sorted(financials.keys()))
        market_data = _cached_market_data(company, year_list)
        macro_data  = _cached_macro_data(year_list)

    kpis = calculate_kpis(financials, market_data)

    # ── 현재 시장 동향 패널 ────────────────────────────────────────────────────
    with st.spinner("현재 주가 수집 중..."):
        curr_mkt = _cached_current_market(company)

    if curr_mkt:
        st.subheader(f"{company} 현재 시장 동향")
        cols = st.columns(4)
        cols[0].metric("현재 주가", f"{curr_mkt['current_price']:,.0f}원")
        for col, (key, label) in zip(
            cols[1:],
            [("change_1m", "1개월"), ("change_3m", "3개월"), ("change_6m", "6개월")],
        ):
            val = curr_mkt.get(key)
            if val is not None:
                col.metric(f"{label} 등락률", f"{val:+.1f}%", delta=f"{val:.2f}%")
            else:
                col.metric(f"{label} 등락률", "N/A")
        st.divider()

    # ── 탭 구성 ────────────────────────────────────────────────────────────────
    tab_fin, tab_kpi, tab_macro = st.tabs(["📋 재무제표", "📈 KPI", "🌍 거시 지표"])

    # ── 탭1: 재무제표 ──────────────────────────────────────────────────────────
    with tab_fin:
        st.subheader(f"{company} 재무 데이터 (단위: 백만원)")

        ACCOUNT_LABELS = {
            "매출액":         "매출액",
            "영업이익":        "영업이익",
            "당기순이익":      "당기순이익",
            "자산총계":        "자산총계",
            "부채총계":        "부채총계",
            "자본총계":        "자본총계",
            "영업활동현금흐름": "영업활동CFO",
            "CAPEX":          "CAPEX",
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

    # ── 탭2: KPI ───────────────────────────────────────────────────────────────
    with tab_kpi:
        st.subheader(f"{company} KPI 지표")

        KPI_LABELS: dict[str, tuple[str, str]] = {
            # 수익성
            "OPM":               ("영업이익률",      "%"),
            "net_income_margin": ("순이익률",        "%"),
            "ROE":               ("ROE",            "%"),
            "ROA":               ("ROA",            "%"),
            # 재무 안정성
            "debt_ratio":        ("부채비율",        "%"),
            # 현금흐름
            "CFO_margin":        ("CFO Margin",     "%"),
            "CAPEX_ratio":       ("CAPEX Ratio",    "%"),
            "FCF_margin":        ("FCF Margin",     "%"),
            # 성장성
            "revenue_growth":    ("매출 성장률",     "%"),
            "op_income_growth":  ("영업이익 성장률", "%"),
            # 밸류에이션
            "PER":               ("PER",            "배"),
            "PBR":               ("PBR",            "배"),
            "PSR":               ("PSR",            "배"),
            "market_cap":        ("시가총액",        "조원"),
        }

        kpi_rows = {}
        for yr in sorted(kpis.keys()):
            k = kpis[yr]
            kpi_rows[yr] = {
                f"{label}({unit})": _fmt_kpi(k.get(key), key, unit)
                for key, (label, unit) in KPI_LABELS.items()
            }

        df_kpi = pd.DataFrame(kpi_rows).T
        df_kpi.index.name = "연도"
        st.dataframe(df_kpi, use_container_width=True)

        captions = []
        if any(kpis[yr].get("PER") is None for yr in kpis):
            captions.append("PER·PBR·PSR·시가총액은 상장사만 표시. EPS 음수 또는 주가 없는 연도는 N/A.")
        captions.append("시가총액은 EPS 역산 추정값 (조원). 실제 발행주식수와 차이가 있을 수 있습니다.")
        for cap in captions:
            st.caption(cap)

    # ── 탭3: 거시 지표 ─────────────────────────────────────────────────────────
    with tab_macro:
        st.subheader("한국·글로벌 거시 지표")

        macro_rows = {}
        for yr in sorted(macro_data.keys()):
            m = macro_data[yr]
            macro_rows[yr] = {
                "기준금리(%)":      m.get("base_rate"),
                "국고채 10년물(%)": m.get("ktb10y"),
                "USD/KRW(원)":     m.get("usd_krw"),
                "KOSPI":           m.get("kospi"),
                "NASDAQ":          m.get("nasdaq"),
            }

        if macro_rows:
            df_macro = pd.DataFrame(macro_rows).T
            df_macro.index.name = "연도"
            st.dataframe(
                df_macro.style.format("{:,.2f}", na_rep="N/A"),
                use_container_width=True,
            )
        else:
            st.info("거시 데이터를 불러올 수 없습니다.")
