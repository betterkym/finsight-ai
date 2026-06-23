"""FinSight analyst workbench: filing-first diagnostics, peer evidence and DCF linkage."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from business_focus import build_assumption_recommendations, build_dcf_evidence_bridge
from data_collector import (
    enrich_disclosures_with_snippets, get_capital_structure, get_external_blog_context,
    get_external_news_context, get_macro_snapshot, get_major_shareholding_changes,
    get_market_beta, get_market_snapshot, get_peer_beta_inputs, get_peer_financials,
    get_quarterly_financials, get_recent_disclosures, get_sga_breakdown, recommend_peers,
)
from diagnostics import build_valuation_range, calculate_dcf, calculate_multiple_valuation, run_dcf_sensitivity
from interpretation import interpret_price_action, interpret_signal
from investment_thesis import build_investment_thesis
from kpi_engine import calculate_quarterly_kpis
from mode_views import build_peer_benchmark, build_peer_comparison, build_tracker_table
from report_generator import export_excel
from report_templates import generate_analysis_summary
from research_reference import get_research_reference
from signal_engine import attach_context, attach_peer_evidence, build_margin_bridge, scan_financial_health
from ui_components import (
    financial_trend_chart, inject_css, peer_benchmark_chart, price_path_chart,
    render_attribution, render_header, render_interpretation, render_quality, render_tab_intro,
)
from validation_agenda import build_data_quality_report, has_blocking_gaps
from valuation_model import build_opm_path, build_structured_model

st.set_page_config(page_title="FinSight | Filing Analysis Workbench", page_icon="▦", layout="wide")
inject_css()

QUICK_COMPANIES = ["농심", "삼양식품", "오뚜기", "아모레퍼시픽", "LG생활건강", "에이피알"]


@st.cache_data(ttl=3600, show_spinner=False)
def _load_company(company: str, quarters: int) -> pd.DataFrame:
    return calculate_quarterly_kpis(get_quarterly_financials(company, quarters))


@st.cache_data(ttl=3600, show_spinner=False)
def _load_peers(companies: tuple[str, ...], quarters: int) -> dict[str, pd.DataFrame]:
    raw = get_peer_financials(list(companies), quarters)
    return {name: calculate_quarterly_kpis(frame) for name, frame in raw.items()}


@st.cache_data(ttl=1800, show_spinner=False)
def _load_context(company: str, stock_code: str) -> dict:
    result = {"disclosures": [], "news": [], "blogs": [], "ownership": [], "market": {}, "errors": []}
    for key, loader in (
        ("disclosures", get_recent_disclosures), ("news", get_external_news_context),
        ("blogs", get_external_blog_context), ("ownership", get_major_shareholding_changes),
    ):
        try:
            result[key] = loader(company)
        except Exception as exc:
            result["errors"].append(f"{key}: {exc}")
    try:
        result["disclosures"] = enrich_disclosures_with_snippets(result["disclosures"])
    except Exception as exc:
        result["errors"].append(f"disclosure text: {exc}")
    try:
        result["market"] = get_market_snapshot(stock_code)
    except Exception as exc:
        result["errors"].append(f"market: {exc}")
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def _load_macro() -> dict:
    return get_macro_snapshot()


@st.cache_data(ttl=86400, show_spinner=False)
def _load_beta(stock_code: str) -> float | None:
    return get_market_beta(stock_code)


@st.cache_data(ttl=1800, show_spinner=False)
def _load_capital(company: str, year: int, quarter: int) -> dict:
    return get_capital_structure(company, year, quarter)


@st.cache_data(ttl=86400, show_spinner=False)
def _load_peer_betas(peer_names: tuple[str, ...]) -> list[dict]:
    try:
        return get_peer_beta_inputs(list(peer_names))
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def _load_sga_breakdown(company: str) -> dict | None:
    try:
        return get_sga_breakdown(company)
    except Exception:
        return None


def _fmt(value, suffix="", digits=1) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{value:,.{digits}f}{suffix}"


def _clear_analysis() -> None:
    for key in ("kpis", "peers", "company", "quarters", "peer_selection", "peer_method", "context", "dcf", "dcf_is_auto", "dcf_version"):
        st.session_state.pop(key, None)


def _tracker_style(frame: pd.DataFrame):
    delta_cols = [column for column in frame.columns if "QoQ" in column or "YoY" in column]
    def color(value):
        if not isinstance(value, (int, float)) or pd.isna(value):
            return ""
        return "color:#166534;background-color:#F0FDF4" if value > 0 else ("color:#991B1B;background-color:#FEF2F2" if value < 0 else "")
    return frame.style.format(precision=1, na_rep="Needs Review").map(color, subset=delta_cols)


with st.sidebar:
    st.markdown("## FinSight")
    st.caption("DART Filing Analysis Workbench")
    st.divider()
    company_input = st.text_input("기업명 또는 종목코드", value="농심")
    quarters_input = st.radio("조회 기간", [8, 12], horizontal=True, format_func=lambda x: f"{x}개 분기")
    peer_rec = recommend_peers(company_input, limit=2)
    auto_peers = st.checkbox("동종기업 자동 추천", value=True)
    if auto_peers:
        selected_peers = peer_rec["peers"]
        st.caption(f"{peer_rec['peer_group']} · {', '.join(selected_peers) if selected_peers else '추천 없음'}")
    else:
        selected_peers = st.multiselect("비교 기업 (최대 2개)", [name for name in QUICK_COMPANIES if name != company_input], max_selections=2)
    analyze = st.button("분석 실행", type="primary", width="stretch")
    st.divider()
    st.caption("판단 순서")
    st.markdown("1. 실제치와 과거·기대 비교\n2. DART 내부 원인\n3. 동종기업 검증\n4. 수급·공시·외부 맥락\n5. 반증 가능한 투자논점\n6. DCF·멀티플 교차검증")
    st.caption("근거가 없으면 원인을 확정하지 않습니다.")

render_header()

if analyze:
    if not company_input.strip():
        _clear_analysis()
        st.error("기업명을 입력해 주세요.")
    else:
        try:
            with st.spinner("분기 재무 수집 · 계정 검증 · 동종기업 비교 준비 중…"):
                loaded = _load_company(company_input.strip(), quarters_input)
                resolved = str(loaded.iloc[-1].get("company", company_input.strip()))
                resolved_peer_rec = recommend_peers(resolved, limit=2)
                peer_candidates = resolved_peer_rec["peers"] if auto_peers else selected_peers
                peers = tuple(name for name in peer_candidates if name != resolved)
                st.session_state.update({
                    "kpis": loaded, "peers": _load_peers(peers, quarters_input), "company": resolved,
                    "quarters": quarters_input, "peer_selection": list(peers),
                    "peer_method": resolved_peer_rec["method"] if auto_peers else "User selected",
                    "context": _load_context(resolved, str(loaded.iloc[-1].get("stock_code", ""))),
                })
                for key in ("dcf", "dcf_is_auto", "dcf_version"):
                    st.session_state.pop(key, None)
        except Exception as exc:
            _clear_analysis()
            st.error(f"분석을 시작하지 못했습니다: {exc}")

if "kpis" not in st.session_state:
    st.markdown("### 무엇을 확인하는 도구인가")
    st.write("분기 숫자를 나열하는 화면이 아닙니다. 모든 핵심 계정을 자체 과거와 비교해 이상 항목을 찾고, DART 내부 계정으로 원인을 좁힌 뒤 동종기업과 외부 맥락으로 검증하여 DCF 가정까지 연결합니다.")
    st.info("왼쪽에서 기업을 선택하고 분석 실행을 눌러주세요.")
    st.stop()

kpis = st.session_state["kpis"]
if "depreciation_ratio" not in kpis.columns:
    kpis = calculate_quarterly_kpis(kpis)
    st.session_state["kpis"] = kpis
peer_kpis = st.session_state.get("peers", {})
peer_kpis = {name: (calculate_quarterly_kpis(frame) if "depreciation_ratio" not in frame.columns else frame) for name, frame in peer_kpis.items()}
st.session_state["peers"] = peer_kpis
company = st.session_state["company"]
context = st.session_state.get("context", {"disclosures": [], "news": [], "blogs": [], "ownership": [], "market": {}, "errors": []})
latest = kpis.iloc[-1]
margin_bridge = build_margin_bridge(kpis)
quality = build_data_quality_report(kpis)
scan = attach_context(attach_peer_evidence(scan_financial_health(kpis), peer_kpis), context.get("disclosures", []), context.get("news", []))
abnormal = [item for item in scan if item["status"] == "Abnormal"]
review_items = [item for item in scan if item["status"] == "Needs Review"]
peer_benchmark = build_peer_benchmark(kpis, peer_kpis)
macro = _load_macro()
beta = _load_beta(str(latest.get("stock_code", "")))
capital = _load_capital(company, int(latest["year"]), int(latest["quarter"]))
recommendations = build_assumption_recommendations(kpis, macro, beta)
dcf_bridge = build_dcf_evidence_bridge(recommendations, scan)
dcf_map = {row["assumption"]: row for row in dcf_bridge}
research = get_research_reference(company)
thesis = build_investment_thesis(
    kpis, context.get("market", {}), context.get("ownership", []),
    context.get("disclosures", []), context.get("news", []), context.get("blogs", []),
    peer_kpis, research,
)
context_pool = context.get("disclosures", []) + context.get("news", []) + context.get("blogs", [])
interpreted = [interpret_signal(item, context_pool, research, context.get("market", {})) for item in abnormal]
price_action = interpret_price_action(
    kpis, context.get("market", {}), context.get("ownership", []),
    context.get("disclosures", []), research, context.get("news", []), context.get("blogs", []),
)
peer_betas = _load_peer_betas(tuple(st.session_state.get("peer_selection", [])))
sga_override = _load_sga_breakdown(company)
structured = build_structured_model(
    company, kpis, peer_kpis, macro, research, recommendations, capital, peer_betas, sga_override,
)

growth_default = dcf_map["매출 성장률"]["evidence_adjusted"]
opm_default = dcf_map["영업이익률"]["evidence_adjusted"]
conversion_default = dcf_map["FCFF 전환율"]["evidence_adjusted"]
perpetual_default = float(recommendations["perpetual_growth"]["default"])
growth_terminal_default = max(perpetual_default + 0.5, min(float(growth_default), 3.0))
ltm_revenue_eok = float(kpis.tail(4)["revenue"].sum(min_count=4) / 1e8)
opm_build = build_opm_path(structured["sga"], ltm_revenue_eok, float(growth_default), float(growth_terminal_default))
structured["opm_build"] = opm_build
opm_terminal_default = float(kpis["opm"].dropna().tail(4).median()) if not kpis["opm"].dropna().empty else float(opm_default)
depreciation_default = float(kpis["depreciation_ratio"].dropna().tail(4).median()) if not kpis["depreciation_ratio"].dropna().empty else 3.5
capex_history = kpis["capex_ratio"].dropna().tail(4)
capex_default = float(capex_history.median()) if not capex_history.empty else 3.0
if any(item["metric"] == "capex_ratio" and item["status"] == "Abnormal" for item in scan):
    capex_default = max(capex_default, float(latest.get("capex_ratio") or capex_default))
nwc_history = kpis["working_capital_ratio"].dropna().tail(4)
nwc_default = max(0.0, float(nwc_history.median()) if not nwc_history.empty else 10.0)
wacc_beta_default = float(structured["wacc"]["beta"])
auto_assumptions = {
    "revenue_growth": growth_default, "revenue_growth_terminal": growth_terminal_default,
    "opm": opm_default, "opm_terminal": opm_terminal_default,
    "opm_path": opm_build["opm_path"] if opm_build else None,
    "depreciation_ratio": depreciation_default, "capex_ratio": capex_default, "nwc_ratio": nwc_default,
    "fcf_conversion": conversion_default, "risk_free_rate": recommendations["risk_free_rate"]["default"],
    "erp": recommendations["erp"]["default"], "beta": wacc_beta_default,
    "perpetual_growth": perpetual_default, "tax_rate": 24.0,
    "debt_weight": float(capital.get("debt_weight") or 0), "cost_of_debt": 4.5,
}
needs_auto = "dcf" not in st.session_state or (st.session_state.get("dcf_is_auto") and st.session_state.get("dcf_version") != 6)
if needs_auto and float(capital.get("shares_outstanding") or 0) > 0:
    try:
        st.session_state["dcf"] = calculate_dcf(kpis, auto_assumptions, float(capital["shares_outstanding"]), float(capital.get("net_debt") or 0))
        st.session_state["dcf_is_auto"], st.session_state["dcf_version"] = True, 6
    except ValueError as exc:
        st.session_state["dcf_error"] = str(exc)
dcf = st.session_state.get("dcf")
multiple_valuation = calculate_multiple_valuation(
    kpis, float(capital.get("shares_outstanding") or 0), float(capital.get("net_debt") or 0),
    capital.get("current_price"), research.get("valuation", {}),
)
valuation_range = build_valuation_range(dcf, multiple_valuation, capital.get("current_price"))

st.markdown(f"## {company} | {latest['period']}")
st.caption(f"분석 범위 {len(kpis)}개 분기 · 비교기업 {', '.join(st.session_state.get('peer_selection', [])) or '없음'} · DART 계정 결측 {sum(item['missing_quarters'] for item in quality)}건")
h1, h2, h3, h4 = st.columns(4)
h1.metric("매출 YoY", _fmt(latest.get("revenue_yoy"), "%"))
h2.metric("영업이익률", _fmt(latest.get("opm"), "%"), _fmt(latest.get("opm_qoq_pp"), "%p"))
h3.metric("FCF 마진", _fmt(latest.get("fcf_margin"), "%"))
h4.metric("우선 검토", f"{len(abnormal)}건", f"결측 {len(review_items)}건")

brief_tab, tracker_tab, diagnostic_tab, peer_tab, dcf_tab, export_tab = st.tabs(["01 투자판단", "02 실적 트래커", "03 이상 탐지·원인", "04 동종기업 검증", "05 가치평가", "06 Excel·근거"])

with brief_tab:
    render_tab_intro("투자판단과 기대치 괴리", "실적이 좋아도 주가가 오르지 않는 이유를 펀더멘털·기대·수급·촉매 시점으로 분리합니다.", "핵심 결론 · 사실/해석 분리 · 기여 분해 · 반증 조건")
    st.markdown(f"### {price_action['verdict']}")
    st.write(price_action["thesis"])
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("현재 주가", _fmt(capital.get("current_price"), "원", 0), _fmt(context.get("market", {}).get("return_3m"), "% · 3M"))
    b2.metric("52주 고점 대비", _fmt(context.get("market", {}).get("drawdown_52w_high"), "%"))
    surprise_values = [row["value"] for row in research.get("expectations", []) if row.get("metric") == "operating_profit_surprise"]
    b3.metric("영업이익 기대 괴리", _fmt(pd.Series(surprise_values).median() if surprise_values else None, "%"))
    b4.metric("교차가치 중앙", _fmt(valuation_range.get("mid"), "원", 0))
    if any(price_action["price_frame"].get(k) is not None for k in ("ret_1m", "ret_3m", "ret_6m")):
        st.plotly_chart(price_path_chart(price_action["price_frame"]), width="stretch")
    st.markdown("#### 주가 움직임의 기여 분해 — 무엇이 실적이고 무엇이 아닌가")
    render_attribution(price_action["attribution"])
    st.markdown("#### 숫자로 확인된 사실")
    st.dataframe(pd.DataFrame(thesis["facts"]), width="stretch", hide_index=True)
    st.markdown("#### 다음 분기에 반드시 확인할 것")
    for checkpoint in thesis["checkpoints"]:
        st.markdown(f"- {checkpoint}")
    with st.expander("외부 맥락 후보 — 사실이 아닌 가설로만 사용"):
        for item in thesis["context"]:
            st.markdown(f"- [{item['title']}]({item['url']}) · {item['source']} · {item.get('evidence_level', 'Context')} · {', '.join(item['matched_keywords'])}")

with tracker_tab:
    render_tab_intro("분기 실적 트래커", "어닝 업데이트 숫자를 옮기고 방향이 바뀐 계정을 확인합니다.", "분기 원본 · QoQ/YoY · 매출/OPM/CFO 추세 · 결측")
    st.plotly_chart(financial_trend_chart(kpis), width="stretch")
    st.dataframe(_tracker_style(build_tracker_table(kpis)), width="stretch", height=460)
    with st.expander("DART 계정 연결 및 결측 점검"):
        render_quality(quality)

with diagnostic_tab:
    render_tab_intro("전 항목 이상 탐지와 원인 추적", "정상 항목까지 전수 스캔하고 자체 과거 범위를 벗어난 항목만 깊게 검증합니다.", "자체 과거 · DART 내부 답 · peer 판정 · 외부 맥락 · DCF 연결")
    scan_df = pd.DataFrame([{"영역": x["area"], "지표": x["label"], "현재": x["value"], "과거 중앙값": x["baseline"], "편차": x["deviation"], "판정": x["status"], "근거": x["reason"]} for x in scan])
    st.dataframe(scan_df.style.format({"현재": "{:.1f}", "과거 중앙값": "{:.1f}", "편차": "{:+.1f}"}, na_rep="N/A"), width="stretch", hide_index=True)
    st.markdown("#### 우선 검토 이슈 — 숫자 너머의 원인 해석")
    if not interpreted:
        st.success("설정된 절대 기준과 자체 과거 범위에서 우선 검토할 이상 항목이 없습니다.")
    for idx, item in enumerate(interpreted, 1):
        interp = item["interpretation"]
        with st.expander(f"{idx}. [{item['severity']}] {interp['headline']}", expanded=idx <= 2):
            render_interpretation(item, _fmt)
    if context.get("errors"):
        st.warning(" / ".join(context["errors"]))

with peer_tab:
    render_tab_intro("동종기업 검증", "이상 신호가 분석기업만의 문제인지 업종 공통 현상인지 구분합니다.", "자동 추천 peer set · 최신 중앙값 · 상대 격차")
    st.write(f"비교기업: **{', '.join(st.session_state.get('peer_selection', [])) or '없음'}**")
    st.caption(f"선정 방식: {st.session_state.get('peer_method')}")
    if peer_kpis:
        st.plotly_chart(peer_benchmark_chart(kpis, peer_kpis), width="stretch")
        st.dataframe(peer_benchmark.style.format({"분석기업": "{:.1f}", "동종기업 중앙값": "{:.1f}", "격차": "{:+.1f}"}, na_rep="N/A"), width="stretch", hide_index=True)
        st.dataframe(build_peer_comparison(kpis, peer_kpis).style.format(precision=1, na_rep="N/A"), width="stretch")
    else:
        st.warning("추천 가능한 동종기업이 없습니다. 자동 추천을 끄고 직접 선택해 주세요.")

with dcf_tab:
    render_tab_intro("가치평가 교차검증", "단일 DCF 숫자를 정답처럼 제시하지 않고 DCF·PER·EV/EBITDA·증권사 참고값의 차이를 드러냅니다.", "명시적 FCFF · 베타 guardrail · 터미널가치 점검 · 멀티플 밴드 · 방법별 괴리")
    evidence_df = pd.DataFrame([{"가정": row["assumption"], "과거 기반": row["base"], "증거 반영": row["evidence_adjusted"], "조정": row["action"], "신뢰도": row["confidence"], "연결 근거": " / ".join(row["evidence"]) or row["source"]} for row in dcf_bridge])
    st.dataframe(evidence_df, width="stretch", hide_index=True)

    st.markdown("#### 매출·원가 구조 빌드 — OPM을 단일 추정이 아닌 바텀업으로 재구성")
    rev_model, sga_model, wacc_model = structured["revenue"], structured["sga"], structured["wacc"]
    rb1, rb2 = st.columns([3, 2])
    with rb1:
        st.markdown("**매출 성장 분해** · " + rev_model["method"])
        rev_hist = pd.DataFrame([
            {"연도": r["year"], "기업 성장률(%)": r["company_growth"], "산업(동종합산, %)": r["industry_growth"],
             "점유율 기여(%p)": r["share_growth"], "실질(−CPI, %)": r["real_growth"]}
            for r in rev_model["history"] if r["company_growth"] is not None
        ])
        if not rev_hist.empty:
            st.dataframe(rev_hist.style.format("{:.1f}", subset=[c for c in rev_hist.columns if c != "연도"], na_rep="—"), width="stretch", hide_index=True)
        st.caption(f"최근 3개년 평균 기업 성장률 {_fmt(rev_model['recent_company_growth'],'%')} · 산업 proxy {_fmt(rev_model['industry_growth_avg'],'%')} · 점유율 기여 {_fmt(rev_model['share_growth_avg'],'%p')}")
    with rb2:
        st.markdown("**판관비 분해** · OPM = 매출총이익률 − 판관비율")
        sga_df = pd.DataFrame(sga_model["components"]).rename(columns={"component": "항목", "share": "비중(%)", "ltm_amount": "LTM(억원)", "driver": "추정 드라이버"})
        if not sga_df.empty:
            st.dataframe(sga_df[["항목", "비중(%)", "LTM(억원)", "추정 드라이버"]], width="stretch", hide_index=True)
        st.caption(f"매출총이익률 {_fmt(sga_model.get('gross_margin'),'%')} − 판관비율 {_fmt(sga_model.get('sga_ratio'),'%')} = 내재 OPM {_fmt(sga_model.get('implied_opm'),'%')} · {sga_model['seed_note']}")
    wb1, wb2 = st.columns([2, 3])
    with wb1:
        st.markdown("**WACC 브릿지**")
        st.dataframe(pd.DataFrame([
            {"항목": "무위험수익률 Rf", "값": f"{wacc_model['rf']:.2f}%"},
            {"항목": "시장위험프리미엄 ERP", "값": f"{wacc_model['erp']:.2f}%"},
            {"항목": "조정 베타 β", "값": f"{wacc_model['beta']:.3f}"},
            {"항목": "자기자본비용 Ke", "값": f"{wacc_model['cost_equity']:.2f}%"},
            {"항목": "세후 타인자본비용 Kd", "값": f"{wacc_model['after_tax_cost_debt']:.2f}%"},
            {"항목": "자본구조 (E/D)", "값": f"{wacc_model['equity_weight']:.0f}% / {wacc_model['debt_weight']:.0f}%"},
            {"항목": "WACC", "값": f"{wacc_model['wacc']:.2f}%"},
        ]), width="stretch", hide_index=True)
    with wb2:
        st.markdown("**동종기업 베타 unlever → relever**")
        if wacc_model["peer_table"]:
            st.dataframe(pd.DataFrame(wacc_model["peer_table"]).rename(columns={"peer": "기업", "levered_beta": "Levered β", "de_ratio": "D/E(%)", "unlevered_beta": "Unlevered β"}).style.format({"Levered β": "{:.3f}", "D/E(%)": "{:.1f}", "Unlevered β": "{:.3f}"}, na_rep="—"), width="stretch", hide_index=True)
        else:
            st.caption("동종기업 베타를 수집하지 못해 조정 베타(시장 회귀)로 대체했습니다.")
        st.caption(wacc_model["method"])

    st.markdown("#### 자동 수집된 자본구조")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("DCF 적용 주식수", _fmt(capital.get("shares_outstanding"), "주", 0))
    a2.metric("순차입금", _fmt(capital.get("net_debt"), "원", 0))
    a3.metric("WACC 부채비중", _fmt(capital.get("debt_weight"), "%", 2))
    a4.metric("최근 종가", _fmt(capital.get("current_price"), "원", 0))
    st.caption(f"주식수 {capital.get('share_source')} · 부채비중 {capital.get('debt_weight_source')}")

    prefix = f"dcfv5_{latest.get('stock_code', company)}_{latest['period']}"
    with st.form(f"dcf_form_{prefix}"):
        c1, c2, c3, c4 = st.columns(4)
        growth = c1.number_input("1년차 매출 성장률(%)", value=float(growth_default), step=0.1, key=f"{prefix}_growth")
        growth_terminal = c2.number_input("5년차 매출 성장률(%)", value=float(growth_terminal_default), step=0.1, key=f"{prefix}_growth_terminal")
        opm = c3.number_input("1년차 OPM(%)", value=float(opm_default), step=0.1, key=f"{prefix}_opm")
        opm_terminal = c4.number_input("5년차 OPM(%)", value=float(opm_terminal_default), step=0.1, key=f"{prefix}_opm_terminal")
        c5, c6, c7, c8 = st.columns(4)
        depreciation_ratio = c5.number_input("D&A/매출(%)", value=float(depreciation_default), step=0.1, key=f"{prefix}_da")
        capex_ratio = c6.number_input("CAPEX/매출(%)", value=float(capex_default), step=0.1, key=f"{prefix}_capex")
        nwc_ratio = c7.number_input("NWC/매출(%)", value=float(nwc_default), step=0.5, key=f"{prefix}_nwc")
        tax_rate = c8.number_input("세율(%)", min_value=0.0, max_value=60.0, value=24.0, step=0.5, key=f"{prefix}_tax")
        c9, c10, c11, c12 = st.columns(4)
        rf = c9.number_input("무위험수익률(%)", value=float(recommendations["risk_free_rate"]["default"]), step=0.1, key=f"{prefix}_rf")
        erp = c10.number_input("ERP(%)", value=float(recommendations["erp"]["default"]), step=0.1, key=f"{prefix}_erp")
        beta_input = c11.number_input("조정 베타", value=float(wacc_beta_default), step=0.05, key=f"{prefix}_beta")
        perpetual = c12.number_input("영구성장률(%)", value=float(perpetual_default), step=0.1, key=f"{prefix}_g")
        c13, c14, c15 = st.columns(3)
        shares = c13.number_input("DCF 적용 주식수", min_value=0.0, value=float(capital.get("shares_outstanding") or 0), step=1000.0, format="%.0f", key=f"{prefix}_shares")
        net_debt = c14.number_input("순차입금", value=float(capital.get("net_debt") or 0), step=1_000_000.0, format="%.0f", key=f"{prefix}_netdebt")
        debt_weight = c15.number_input("부채 비중(%)", min_value=0.0, max_value=100.0, value=float(capital.get("debt_weight") or 0), step=0.1, key=f"{prefix}_debtweight")
        recalculate = st.form_submit_button("수정 가정으로 재계산", type="primary", width="stretch")
    st.caption(f"베타 적용 근거: {structured['wacc']['beta_source']} (β={wacc_beta_default:.3f}) · 시장회귀 β={structured['wacc']['market_beta']:.3f}")
    if opm_build:
        st.caption("자동 DCF의 OPM은 단일 fade가 아니라 판관비 바텀업 빌드로 산출됩니다 — 연도별 " + " → ".join(f"{v:.1f}%" for v in opm_build["opm_path"] if v is not None))
    if recalculate:
        assumptions = {
            "revenue_growth": growth, "revenue_growth_terminal": growth_terminal,
            "opm": opm, "opm_terminal": opm_terminal,
            "depreciation_ratio": depreciation_ratio, "capex_ratio": capex_ratio, "nwc_ratio": nwc_ratio,
            "fcf_conversion": conversion_default, "risk_free_rate": rf, "erp": erp, "beta": beta_input,
            "perpetual_growth": perpetual, "tax_rate": tax_rate,
            "debt_weight": debt_weight, "cost_of_debt": 4.5,
        }
        try:
            st.session_state["dcf"] = calculate_dcf(kpis, assumptions, shares, net_debt)
            st.session_state["dcf_is_auto"], st.session_state["dcf_version"] = False, 6
        except ValueError as exc:
            st.error(str(exc))
    dcf = st.session_state.get("dcf")
    valuation_range = build_valuation_range(dcf, multiple_valuation, capital.get("current_price"))
    if dcf:
        if st.session_state.get("dcf_is_auto"):
            st.info("탐지 근거를 반영한 예비 DCF입니다. 확정 가치가 아니라 검토 시작점입니다.")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("WACC", _fmt(dcf["wacc"], "%", 2)); d2.metric("WACC-g", _fmt(dcf.get("wacc_growth_spread"), "%p", 2)); d3.metric("TV/EV", _fmt(dcf.get("terminal_value_share"), "%", 1)); d4.metric("DCF 주당가치", _fmt(dcf["implied_price"], "원", 0))
        if dcf.get("guardrails", {}).get("terminal_value_watch"):
            st.warning("기업가치의 75% 이상이 터미널가치에서 발생합니다. 성장률·WACC 민감도를 보수적으로 확인하세요.")
        st.dataframe(dcf["forecast"].style.format(precision=1), width="stretch", hide_index=True)
        sensitivity = run_dcf_sensitivity(kpis, dcf["assumptions"], dcf["shares_outstanding"], dcf["net_debt"])
        st.dataframe(sensitivity.pivot(index="성장률 변화(%p)", columns="OPM 변화(%p)", values="주당가치").style.format("{:,.0f}"), width="stretch")
    elif st.session_state.get("dcf_error"):
        st.error(st.session_state["dcf_error"])
    st.markdown("#### 멀티플·리서치 목표가 교차검증")
    if not multiple_valuation.empty:
        st.dataframe(multiple_valuation.style.format({"multiple": "{:.1f}", "implied_price": "{:,.0f}", "upside": "{:+.1f}%"}, na_rep="—"), width="stretch", hide_index=True)
        v1, v2, v3, v4 = st.columns(4)
        v1.metric("교차가치 하단", _fmt(valuation_range.get("low"), "원", 0)); v2.metric("중앙", _fmt(valuation_range.get("mid"), "원", 0)); v3.metric("상단", _fmt(valuation_range.get("high"), "원", 0)); v4.metric("방법론 분산", _fmt(valuation_range.get("dispersion"), "%", 1))
        st.caption(research.get("valuation", {}).get("note", "멀티플 밴드는 참고 범위이며 확정 목표가가 아닙니다."))

with export_tab:
    render_tab_intro("Excel과 근거 패키지", "웹에서 찾은 이슈와 가정을 모델 작업으로 넘기고 출처·결측·검증 상태를 보존합니다.", "Summary · Quarterly · Diagnostics · Peers · DCF · Checks/Sources")
    dcf = st.session_state.get("dcf")
    export_anomalies = [{"signal": x["label"], "severity": x["severity"], "comment": x["dart_answer"]} for x in abnormal]
    if has_blocking_gaps(quality):
        st.warning("매출액 또는 영업이익 결측이 있습니다. Excel Checks 시트를 먼저 확인하세요.")
    excel = export_excel(
        company, kpis, margin_bridge, dcf, recommendations, quality, export_anomalies, capital,
        scan=scan, peer_benchmark=peer_benchmark, dcf_evidence=dcf_bridge,
        peer_names=st.session_state.get("peer_selection", []),
        thesis=thesis, market_context=context, multiple_valuation=multiple_valuation,
        valuation_range=valuation_range, research_reference=research,
        structured=structured, price_action=price_action, interpreted=interpreted,
    )
    summary = generate_analysis_summary(
        company, kpis, margin_bridge, export_anomalies, dcf,
        price_action=price_action, interpreted=interpreted, structured=structured,
        valuation_range=valuation_range, capital=capital, research=research,
    )
    coverage = pd.DataFrame([
        {"근거 계층": "DART 재무", "상태": "Connected", "내용": f"{len(kpis)}개 분기"},
        {"근거 계층": "DART 공시", "상태": "Connected" if context.get("disclosures") else "Unavailable", "내용": f"{len(context.get('disclosures', []))}건"},
        {"근거 계층": "외부 뉴스", "상태": "Connected" if context.get("news") else "Unavailable", "내용": f"{len(context.get('news', []))}건"},
        {"근거 계층": "DART 지분공시", "상태": "Connected" if context.get("ownership") else "Unavailable", "내용": f"{len(context.get('ownership', []))}건"},
        {"근거 계층": "시장 가격", "상태": "Connected" if context.get("market") else "Unavailable", "내용": context.get("market", {}).get("as_of", "")},
        {"근거 계층": "리서치 참고", "상태": "Connected" if research.get("valuation") else "Unavailable", "내용": f"{len(research.get('expectations', []))}개 기대치 비교"},
        {"근거 계층": "동종기업", "상태": "Connected" if peer_kpis else "Unavailable", "내용": f"{len(peer_kpis)}개사"},
    ])
    st.dataframe(coverage, width="stretch", hide_index=True)
    c1, c2 = st.columns(2)
    c1.download_button("Analyst Workbook 다운로드", excel, file_name=f"FinSight_{company}_Analyst_Workbook.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", width="stretch")
    c2.download_button("분석 요약 Markdown", summary.encode("utf-8"), file_name=f"FinSight_{company}_summary.md", mime="text/markdown", width="stretch")
