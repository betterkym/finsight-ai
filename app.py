"""FinSight analyst workbench: filing-first diagnostics, peer evidence and DCF linkage."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from business_focus import build_assumption_recommendations, build_dcf_evidence_bridge
from data_collector import (
    enrich_disclosures_with_snippets, get_capital_structure, get_external_blog_context,
    get_external_driver_snapshot, get_external_news_context, get_macro_snapshot, get_major_shareholding_changes,
    get_market_beta, get_market_snapshot, get_peer_beta_inputs, get_peer_financials,
    get_quarterly_financials, get_recent_disclosures, get_sga_breakdown, recommend_peers,
)
from diagnostics import (
    build_terminal_value_guidance, build_valuation_range, calculate_dcf,
    calculate_multiple_valuation, run_dcf_sensitivity,
)
from interpretation import interpret_price_action, interpret_signal
from investment_thesis import build_investment_thesis
from kpi_engine import calculate_quarterly_kpis
from mode_views import build_peer_benchmark, build_peer_comparison, build_tracker_table
from report_generator import export_excel
from report_templates import generate_analysis_html_report
from research_reference import get_research_reference
from signal_engine import attach_context, attach_peer_evidence, build_margin_bridge, scan_financial_health
from ui_components import (
    financial_trend_chart, inject_css, peer_benchmark_chart, price_path_chart,
    render_attribution, render_checkpoints, render_context_items, render_header, render_interpretation,
    render_landing, render_process_steps, render_quality, render_tab_intro, valuation_range_band,
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
    result = {
        "disclosures": [], "news": [], "blogs": [], "ownership": [],
        "market": {}, "external_drivers": {}, "errors": [],
    }
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
    try:
        result["external_drivers"] = get_external_driver_snapshot(company, stock_code)
    except Exception as exc:
        result["errors"].append(f"external drivers: {exc}")
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


def _safe_num(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_delta(value, unit="%", digits=1) -> str:
    number = _safe_num(value)
    return "N/A" if number is None else f"{number:+,.{digits}f}{unit}"


def _peer_latest_median(peer_kpis: dict[str, pd.DataFrame], column: str) -> float | None:
    values = []
    for frame in (peer_kpis or {}).values():
        if frame is None or frame.empty or column not in frame:
            continue
        number = _safe_num(frame.iloc[-1].get(column))
        if number is not None:
            values.append(number)
    return float(pd.Series(values).median()) if values else None


def _external_driver_note(context: dict) -> tuple[str, list[str]]:
    drivers = (context or {}).get("external_drivers", {})
    flows = drivers.get("flows", {})
    notes = []
    if flows.get("connected"):
        notes.append(
            f"KRX 20일 수급: 외국인 {_fmt_delta(flows.get('foreign_20d_eok'), '억', 0)}, "
            f"기관 {_fmt_delta(flows.get('institution_20d_eok'), '억', 0)}"
        )
    elif flows:
        notes.append(f"KRX 수급: {flows.get('reason', '연결 대기')}")
    macro = drivers.get("macro", {})
    fred_fx = macro.get("fred_usd_krw") or {}
    fred_wheat = macro.get("fred_wheat") or {}
    if fred_fx:
        notes.append(f"FRED USD/KRW {fred_fx.get('date')}: {fred_fx.get('value'):,.1f}")
    if fred_wheat:
        notes.append(f"FRED wheat proxy {fred_wheat.get('date')}: {fred_wheat.get('value'):,.1f}")
    status = [
        f"{row['source']}: {row['status']}"
        for row in drivers.get("status_rows", [])
        if row.get("source") in {"KOSIS", "KAMIS", "UN Comtrade / KATI"}
    ]
    return " · ".join(notes[:3]) if notes else "외부 수급·원가·무역 proxy는 연결 상태를 별도 표에서 확인", status


def _make_card(title: str, verdict: str, read: str, evidence: list[str], so_what: str, action: str, next_: str, model_link: str, confidence: str = "Medium") -> dict:
    return {
        "title": title,
        "verdict": verdict,
        "read": read,
        "evidence": [line for line in evidence if line],
        "so_what": so_what,
        "action": action,
        "next": next_,
        "model_link": model_link,
        "confidence": confidence,
    }


def _build_tracker_commentary(
    kpis: pd.DataFrame,
    peer_kpis: dict[str, pd.DataFrame] | None = None,
    context: dict | None = None,
    macro: dict | None = None,
) -> list[dict]:
    """Explain the latest quarter as an analyst decision bridge."""
    if kpis.empty:
        return []
    latest = kpis.iloc[-1]
    cards: list[dict] = []

    def val(key):
        return latest.get(key)

    revenue_yoy = _safe_num(val("revenue_yoy"))
    revenue_qoq = _safe_num(val("revenue_qoq"))
    opm = _safe_num(val("opm"))
    opm_yoy = _safe_num(val("opm_yoy_pp"))
    cogs_yoy = _safe_num(val("cogs_ratio_yoy_pp"))
    sga_yoy = _safe_num(val("sga_ratio_yoy_pp"))
    cfo_margin = _safe_num(val("cfo_margin"))
    fcf_margin = _safe_num(val("fcf_margin"))
    capex_ratio = _safe_num(val("capex_ratio"))
    ar_days = _safe_num(val("ar_days"))
    inv_days = _safe_num(val("inventory_days"))
    peer_revenue = _peer_latest_median(peer_kpis or {}, "revenue_yoy")
    peer_opm = _peer_latest_median(peer_kpis or {}, "opm")
    external_note, setup_notes = _external_driver_note(context or {})

    if revenue_yoy is not None and opm_yoy is not None:
        if revenue_yoy > 0 and opm_yoy < 0:
            pressure = []
            if cogs_yoy is not None and cogs_yoy > 0:
                pressure.append(f"원가율이 YoY {cogs_yoy:+.1f}%p 올라 매출 증가분을 흡수")
            if sga_yoy is not None and sga_yoy > 0:
                pressure.append(f"판관비율이 YoY {sga_yoy:+.1f}%p 올라 영업 레버리지 훼손")
            cards.append(_make_card(
                "성장 품질: 매출 증가가 이익으로 충분히 못 내려옴",
                "주의",
                "외형은 커졌지만 이익률이 같이 따라오지 못했습니다. 이 조합은 ‘수요가 좋아졌다’보다 ‘가격·믹스·원가·판관비 중 하나가 훼손됐다’는 질문을 먼저 던져야 합니다.",
                [
                    f"매출 YoY {revenue_yoy:+.1f}%, QoQ {_fmt_delta(revenue_qoq)}",
                    f"OPM {opm:.1f}%, YoY {opm_yoy:+.1f}%p",
                    " / ".join(pressure) if pressure else "원가율/판관비율 중 압박 축은 추가 계정 확인 필요",
                    f"동종기업 중앙값 매출 YoY {_fmt_delta(peer_revenue)}" if peer_revenue is not None else "",
                ],
                "DCF에서 매출 성장률만 올리면 과대평가됩니다. 다음 모델 업데이트는 매출보다 OPM·FCFF 전환율을 먼저 보수화하는 쪽이 안전합니다.",
                "1년차 OPM 또는 FCFF 전환율을 낮추고, 원가율/판관비율이 정상화되는 분기부터 성장률 상향을 허용합니다.",
                "다음 분기에 매출 증가와 원가율·판관비율 하락이 동시에 나오지 않으면 ‘성장 프리미엄’보다 ‘마진 정상화 지연’으로 해석합니다.",
                "OPM / FCFF conversion / terminal margin",
                "High",
            ))
        elif revenue_yoy > 0 and opm_yoy >= 0:
            price_lag = (context or {}).get("market", {}).get("return_3m")
            cards.append(_make_card(
                "성장 품질: 외형과 수익성이 같은 방향",
                "긍정",
                "매출과 OPM이 동시에 개선된 구간입니다. 숫자만 보면 DCF의 1년차 매출·마진 가정을 동시에 지지하지만, 주가가 반응하지 않았다면 원인은 숫자 밖에서 찾아야 합니다.",
                [
                    f"매출 YoY {revenue_yoy:+.1f}%",
                    f"OPM YoY {opm_yoy:+.1f}%p",
                    f"최근 3개월 주가수익률 {_fmt_delta(price_lag)}" if price_lag is not None else "",
                    external_note,
                ],
                "실적 개선에도 멀티플이 회복되지 않으면 ‘실적 문제’가 아니라 기대치 선반영, 수급 매도, 지속가능성 의심 중 하나일 가능성이 큽니다.",
                "기본 시나리오는 유지하거나 소폭 올릴 수 있습니다. 다만 KRX 수급과 동종기업 대비 프리미엄 회복이 확인되기 전까지 멀티플 상단은 열어두지 않습니다.",
                "다음 분기에도 해외 매출·물량·이익률이 함께 개선되고도 주가가 무반응이면 수급/밸류에이션 할인 요인을 별도 투자논점으로 분리합니다.",
                "Revenue growth / OPM / exit multiple",
                "High",
            ))
        elif revenue_yoy < 0 and opm_yoy >= 0:
            cards.append(_make_card(
                "방어 품질: 매출 둔화 속 마진 방어",
                "혼재",
                "외형은 약하지만 비용 통제나 믹스 개선으로 마진을 지킨 패턴입니다. 단, 비용 절감만으로는 장기 성장률을 설명하기 어렵습니다.",
                [
                    f"매출 YoY {revenue_yoy:+.1f}%",
                    f"OPM YoY {opm_yoy:+.1f}%p",
                    f"동종기업 중앙값 OPM {_fmt(peer_opm, '%')}" if peer_opm is not None else "",
                ],
                "단기 이익은 방어돼도 매출 회복이 없으면 터미널 성장률과 멀티플 상단은 제한됩니다.",
                "마진 가정은 유지하되 매출 성장률과 터미널 성장률은 보수적으로 둡니다.",
                "다음 분기 매출 회복 없이 마진만 유지되면 ‘구조적 체질 개선’이 아니라 비용 절감 효과로 낮게 평가합니다.",
                "Terminal growth / sales CAGR / OPM sustainability",
            ))

    if cfo_margin is not None and fcf_margin is not None:
        if cfo_margin > 0 and fcf_margin < 0:
            cards.append(_make_card(
                "현금 전환: 영업현금은 있으나 FCF가 새고 있음",
                "확인필요",
                "손익은 현금으로 일부 전환되지만 CAPEX 또는 운전자본이 FCF를 흡수합니다. 증설 투자라면 미래 매출로 회수돼야 하고, 운전자본이면 다음 분기 정상화가 필요합니다.",
                [
                    f"CFO 마진 {cfo_margin:.1f}%",
                    f"FCF 마진 {fcf_margin:.1f}%",
                    f"CAPEX/매출 {_fmt(capex_ratio, '%')}",
                ],
                "DCF의 핵심은 이익이 아니라 FCFF입니다. 이 상태가 지속되면 영업이익 개선을 전부 가치로 인정하면 안 됩니다.",
                "향후 1~2년 FCFF를 보수적으로 두고, CAPEX가 매출로 전환되는 시점 전까지 터미널가치 의존도를 낮춥니다.",
                "다음 분기에 CFO와 FCF가 같이 개선되지 않으면 ‘투자 회수 지연’ 또는 ‘운전자본 누수’로 분류합니다.",
                "FCFF / CAPEX / NWC",
                "High",
            ))
        elif cfo_margin < 0:
            cards.append(_make_card(
                "현금 전환: 회계 이익보다 현금이 약함",
                "주의",
                "손익계산서보다 현금흐름표가 더 나쁜 구간입니다. 매출채권·재고 증가, 채널 재고, 판촉성 매출 가능성을 먼저 확인해야 합니다.",
                [f"CFO 마진 {cfo_margin:.1f}%", f"FCF 마진 {fcf_margin:.1f}%"],
                "이익률이 좋아 보여도 현금 전환이 안 되면 DCF는 즉시 과대평가됩니다.",
                "FCFF 전환율과 NWC/매출 가정을 낮추고, 다음 분기 회수 전까지 성장률 상향은 보류합니다.",
                "다음 분기 매출채권·재고가 줄지 않으면 실적 품질 할인 요인으로 유지합니다.",
                "NWC / FCFF conversion",
                "High",
            ))

    wc_flags = []
    if ar_days is not None and "ar_days" in kpis:
        ar_med = kpis["ar_days"].dropna().tail(8).median()
        if pd.notna(ar_med) and ar_days > ar_med * 1.15:
            wc_flags.append(f"채권회수일 {ar_days:.0f}일 vs 최근 중앙값 {ar_med:.0f}일")
    if inv_days is not None and "inventory_days" in kpis:
        inv_med = kpis["inventory_days"].dropna().tail(8).median()
        if pd.notna(inv_med) and inv_days > inv_med * 1.15:
            wc_flags.append(f"재고일수 {inv_days:.0f}일 vs 최근 중앙값 {inv_med:.0f}일")
    if wc_flags:
        cards.append(_make_card(
            "운전자본: 매출의 질을 다시 봐야 하는 구간",
            "주의",
            "매출이 늘어도 채권·재고가 같이 늘면 실제 최종수요보다 채널 재고나 회수 지연일 수 있습니다.",
            wc_flags,
            "운전자본 부담은 DCF에서 바로 ΔNWC 증가와 FCFF 감소로 연결됩니다. 성장률보다 현금 회수 속도가 더 중요합니다.",
            "NWC/매출 가정을 상향하고, 다음 분기 정상화 전까지 매출 성장률 신뢰도를 낮춥니다.",
            "다음 분기 재고·채권 회전일이 과거 중앙값 근처로 내려오지 않으면 ‘좋은 성장’으로 인정하지 않습니다.",
            "NWC / revenue quality / FCFF",
        ))

    if capex_ratio is not None and "capex_ratio" in kpis:
        capex_med = kpis["capex_ratio"].dropna().tail(8).median()
        if pd.notna(capex_med) and capex_ratio > capex_med * 1.4:
            cards.append(_make_card(
                "투자 부담: 지금은 비용, 나중엔 매출이어야 함",
                "확인필요",
                "평소보다 큰 CAPEX는 당장 FCF를 누르지만, 증설·해외 생산능력이라면 이후 매출과 마진으로 회수돼야 합니다.",
                [f"CAPEX/매출 {capex_ratio:.1f}% vs 최근 중앙값 {capex_med:.1f}%", external_note],
                "CAPEX를 성장투자로 인정하려면 매출 전환 시점이 필요합니다. 전환 근거가 없으면 단기 FCFF만 낮아지고 가치 기여는 제한됩니다.",
                "투자 회수 전까지 CAPEX/매출은 높게 유지하고, 신규 설비 매출이 확인되는 분기부터 성장률을 반영합니다.",
                "준공·가동률·해외 매출 전환이 다음 보고서/IR에서 확인되지 않으면 증설 프리미엄을 모델에 넣지 않습니다.",
                "CAPEX / sales ramp / terminal value share",
            ))

    if setup_notes and len(cards) < 4:
        cards.append(_make_card(
            "외부 검증 레이어: 아직 숫자로 확정하지 말아야 할 것",
            "데이터확장",
            "DART로 원인은 좁힐 수 있지만 원재료·해외 수요·수급은 별도 데이터가 있어야 ‘왜’까지 설명됩니다.",
            setup_notes[:3],
            "키/품목코드가 연결되면 원가율 변화는 KAMIS/FRED, 해외 매출은 UN Comtrade/KATI, 국내 수요는 KOSIS로 교차검증됩니다.",
            "현재는 해당 항목을 가설로만 사용하고, 연결 후에는 DCF 매출·마진 가정의 보정 근거로 승격합니다.",
            "다음 버전에서는 원가율 급등 시 품목 가격, 해외 매출 괴리 시 HS 수출량, 주가 무반응 시 KRX 수급을 자동 첨부합니다.",
            "Evidence quality / assumption confidence",
            "Pending",
        ))

    if not cards:
        cards.append(_make_card(
            "최신 분기: 큰 이상 조합은 제한적",
            "중립",
            "핵심 계정이 자체 과거 범위를 크게 벗어나지 않았습니다. 이럴 때 억지로 원인을 만들기보다 주가 괴리가 기대치·수급·멀티플에서 왔는지 분리하는 편이 실무적으로 안전합니다.",
            [f"매출 YoY {_fmt_delta(revenue_yoy)}", f"OPM {_fmt(opm, '%')}", f"FCF 마진 {_fmt(fcf_margin, '%')}", external_note],
            "DCF 가정은 유지하되, 주가가 실적보다 약하면 수급/기대치/밸류에이션 할인 쪽을 별도 논점으로 봅니다.",
            "기본 시나리오를 유지하고 민감도에서 OPM·WACC·멀티플 할인 폭을 먼저 점검합니다.",
            "다음 분기에 매출, OPM, CFO/FCF가 같은 방향으로 움직이는지 확인합니다.",
            "Base-case hold / sensitivity",
        ))
    return cards[:4]


def _apply_external_dcf_adjustments(assumptions: dict, context: dict, thesis: dict, latest: pd.Series) -> tuple[dict, list[dict]]:
    """Apply a conservative, evidence-labeled external-variable layer to auto DCF assumptions."""
    adjusted = dict(assumptions)
    rows: list[dict] = []

    def add(driver: str, signal: str, target: str, before: float | None, after: float | None, reason: str, confidence: str = "Medium"):
        rows.append({
            "외부 변수": driver,
            "현재 신호": signal,
            "DCF 반영": target,
            "조정 전": before,
            "조정 후": after,
            "해석": reason,
            "신뢰도": confidence,
        })

    drivers = (context or {}).get("external_drivers", {})
    flows = drivers.get("flows", {})
    if flows.get("connected"):
        foreign = _safe_num(flows.get("foreign_20d_eok")) or 0
        institution = _safe_num(flows.get("institution_20d_eok")) or 0
        net_flow = foreign + institution
        if net_flow < -100:
            before = float(adjusted.get("erp", 6.0))
            after = round(before + 0.4, 2)
            adjusted["erp"] = after
            add(
                "수급 부담",
                f"20일 외국인+기관 {net_flow:+,.0f}억원",
                "ERP +0.4%p → WACC 보수화",
                before,
                after,
                "실적과 별개로 매도 압력이 남아 있으면 멀티플 회복이 지연될 수 있어 할인율 레이어에 반영합니다.",
                "Market",
            )
        elif net_flow > 100:
            before = float(adjusted.get("erp", 6.0))
            after = round(max(before - 0.2, before - 0.2), 2)
            adjusted["erp"] = after
            add(
                "수급 개선",
                f"20일 외국인+기관 {net_flow:+,.0f}억원",
                "ERP -0.2%p → 할인 완화",
                before,
                after,
                "수급이 회복되면 펀더멘털 개선이 가격에 반영될 가능성이 커져 할인율을 소폭 완화합니다.",
                "Market",
            )

    market = (context or {}).get("market", {})
    ret_3m = _safe_num(market.get("return_3m"))
    drawdown = _safe_num(market.get("drawdown_52w_high"))
    opm_yoy = _safe_num(latest.get("opm_yoy_pp"))
    if ret_3m is not None and ret_3m < -10 and (opm_yoy is None or opm_yoy >= -1):
        before = float(adjusted.get("erp", 6.0))
        after = round(max(float(adjusted.get("erp", before)), before) + 0.2, 2)
        adjusted["erp"] = after
        add(
            "주가·실적 괴리",
            f"3개월 수익률 {ret_3m:+.1f}%, 52주 고점 대비 {_fmt_delta(drawdown)}",
            "ERP +0.2%p → 리레이팅 지연 반영",
            before,
            after,
            "실적 훼손이 크지 않은데 주가가 약하면 시장은 지속성·수급·테마 부재를 할인하고 있을 가능성이 큽니다.",
            "Market",
        )

    text_pool = " ".join(
        f"{item.get('title','')} {item.get('summary','')} {item.get('description','')}"
        for item in (thesis or {}).get("context", [])
    )
    macro = drivers.get("macro", {})
    fx = macro.get("fred_usd_krw") or {}
    wheat = macro.get("fred_wheat") or {}
    fx_chg = _safe_num(fx.get("change_3m_pct"))
    wheat_chg = _safe_num(wheat.get("change_3m_pct"))
    has_cost_signal = any(keyword in text_pool for keyword in ("원가", "유가", "곡물", "소맥", "팜유", "환율", "전쟁"))
    fx_up = fx_chg is not None and fx_chg > 1.5
    wheat_up = wheat_chg is not None and wheat_chg > 3.0
    # 연결만으로 발동하지 않고, 환율·원재료가 실제로 오른 구간이거나 뉴스 원가 신호가 있을 때만 마진을 보수화한다.
    if has_cost_signal or fx_up or wheat_up:
        before = float(adjusted.get("opm", 0.0))
        haircut = 0.3
        cogs_yoy = _safe_num(latest.get("cogs_ratio_yoy_pp"))
        if cogs_yoy is not None and cogs_yoy > 0:
            haircut = min(0.8, max(0.3, cogs_yoy * 0.35))
        if fx_up or wheat_up:
            macro_push = max((fx_chg or 0) * 0.03, (wheat_chg or 0) * 0.02)
            haircut = min(0.8, max(haircut, round(macro_push, 1)))
        after = round(before - haircut, 1)
        adjusted["opm"] = after
        if "opm_path" in adjusted and adjusted["opm_path"]:
            adjusted["opm_path"] = [round(float(v) - haircut, 1) if v is not None else None for v in adjusted["opm_path"]]
        macro_bits = []
        if fx_up:
            macro_bits.append(f"USD/KRW 3M {fx_chg:+.1f}%")
        if wheat_up:
            macro_bits.append(f"소맥 3M {wheat_chg:+.1f}%")
        if has_cost_signal:
            macro_bits.append("뉴스 원가 신호")
        add(
            "환율·원재료 압박",
            " · ".join(macro_bits) or "원가 변수 감지",
            f"1년차 OPM {haircut:.1f}%p 하향",
            before,
            after,
            "원가·환율 변수는 매출보다 마진에 먼저 반영합니다. 실제 원가율 안정이 확인되기 전까지 OPM을 보수화합니다.",
            "Context",
        )

    has_growth_signal = any(keyword in text_pool for keyword in ("수출", "해외", "공장", "증설", "가동률"))
    if has_growth_signal:
        capex_ratio = _safe_num(latest.get("capex_ratio"))
        if capex_ratio is not None and capex_ratio > float(adjusted.get("capex_ratio", capex_ratio)) * 1.15:
            before = float(adjusted.get("capex_ratio", capex_ratio))
            after = round(max(before, capex_ratio), 1)
            adjusted["capex_ratio"] = after
            add(
                "증설·해외 성장 옵션",
                f"CAPEX/매출 {_fmt_delta(capex_ratio)} 및 관련 키워드 감지",
                "CAPEX/매출 상향 유지",
                before,
                after,
                "증설은 성장 옵션이지만 매출 전환 전까지는 FCFF를 누르는 요인입니다. 가동률·해외 매출 확인 전에는 CAPEX 부담을 먼저 반영합니다.",
                "Filing/Context",
            )
        else:
            before = float(adjusted.get("revenue_growth_terminal", adjusted.get("revenue_growth", 0)))
            after = round(min(before + 0.3, float(adjusted.get("revenue_growth", before))), 1)
            adjusted["revenue_growth_terminal"] = after
            add(
                "해외·증설 성장 후보",
                "수출/공장/증설 관련 키워드 감지",
                "5년차 성장률 +0.3%p 한도",
                before,
                after,
                "외부 자료만으로 장기 성장률을 크게 올리지는 않고, 확인 전에는 제한적인 옵션 가치만 반영합니다.",
                "Context",
            )

    if any(keyword in text_pool for keyword in ("정책", "대통령", "수혜주", "스페이스X", "테마")):
        before = float(adjusted.get("erp", 6.0))
        after = round(before + 0.3, 2)
        adjusted["erp"] = after
        add(
            "테마성 가격 변동",
            "정책/테마 키워드 감지",
            "ERP +0.3%p → 테마 프리미엄 할인",
            before,
            after,
            "테마는 가격 변동을 만들 수 있지만 지속 현금흐름 근거가 약하면 DCF에는 할인율 보수화로 반영합니다.",
            "Context",
        )

    return adjusted, rows


with st.sidebar:
    st.markdown(
        '<div class="fs-side-cap">DART Filing Analysis Workbench</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    company_input = st.text_input("기업명 또는 종목코드", value="농심")
    quarters_input = st.select_slider(
        "조회 기간", options=[8, 12, 16, 20, 24], value=12,
        format_func=lambda x: f"{x}개 분기 · {x // 4}년" + (" (권장)" if x == 12 else ""),
    )
    st.markdown(
        "<div style='font-size:.72rem;color:#8AA3BE;line-height:1.4;margin:-2px 0 6px'>"
        "권장 12분기(3년) · 길수록 추세는 안정적이나 옛 분기 결측↑</div>",
        unsafe_allow_html=True,
    )
    peer_rec = recommend_peers(company_input, limit=2)
    peer_mode = st.radio("동종기업 선정", ["자동 추천", "직접 입력"], horizontal=True)
    auto_peers = peer_mode == "자동 추천"
    if auto_peers:
        selected_peers = peer_rec["peers"]
        st.caption(f"{peer_rec['peer_group']} · {', '.join(selected_peers) if selected_peers else '추천 없음'}")
    else:
        selected_peers = st.multiselect("비교 기업 (최대 2개)", [name for name in QUICK_COMPANIES if name != company_input], max_selections=2)
    analyze = st.button("분석 실행", type="primary", width="stretch")
    st.divider()
    render_process_steps()

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

render_header(slim=True)

if "kpis" not in st.session_state:
    render_landing(QUICK_COMPANIES)
    st.stop()

kpis = st.session_state["kpis"]
if "depreciation_ratio" not in kpis.columns:
    kpis = calculate_quarterly_kpis(kpis)
    st.session_state["kpis"] = kpis
peer_kpis = st.session_state.get("peers", {})
peer_kpis = {name: (calculate_quarterly_kpis(frame) if "depreciation_ratio" not in frame.columns else frame) for name, frame in peer_kpis.items()}
st.session_state["peers"] = peer_kpis
company = st.session_state["company"]
context = st.session_state.get("context", {"disclosures": [], "news": [], "blogs": [], "ownership": [], "market": {}, "external_drivers": {}, "errors": []})
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
tracker_commentary = _build_tracker_commentary(kpis, peer_kpis, context, macro)
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
auto_assumptions, external_dcf_adjustments = _apply_external_dcf_adjustments(auto_assumptions, context, thesis, latest)
growth_default = float(auto_assumptions["revenue_growth"])
growth_terminal_default = float(auto_assumptions["revenue_growth_terminal"])
opm_default = float(auto_assumptions["opm"])
opm_terminal_default = float(auto_assumptions["opm_terminal"])
capex_default = float(auto_assumptions["capex_ratio"])
perpetual_default = float(auto_assumptions["perpetual_growth"])
if opm_build and auto_assumptions.get("opm_path"):
    opm_build["opm_path"] = auto_assumptions["opm_path"]
    structured["opm_build"] = opm_build
needs_auto = "dcf" not in st.session_state or (st.session_state.get("dcf_is_auto") and st.session_state.get("dcf_version") != 7)
if needs_auto and float(capital.get("shares_outstanding") or 0) > 0:
    try:
        st.session_state["dcf"] = calculate_dcf(kpis, auto_assumptions, float(capital["shares_outstanding"]), float(capital.get("net_debt") or 0))
        st.session_state["dcf_is_auto"], st.session_state["dcf_version"] = True, 7
    except ValueError as exc:
        st.session_state["dcf_error"] = str(exc)
dcf = st.session_state.get("dcf")
multiple_valuation = calculate_multiple_valuation(
    kpis, float(capital.get("shares_outstanding") or 0), float(capital.get("net_debt") or 0),
    capital.get("current_price"), research.get("valuation", {}),
)
valuation_range = build_valuation_range(dcf, multiple_valuation, capital.get("current_price"))

export_anomalies = [{"signal": x["label"], "severity": x["severity"], "comment": x["dart_answer"]} for x in abnormal]
html_report = generate_analysis_html_report(
    company, kpis, margin_bridge, export_anomalies, dcf,
    price_action=price_action, interpreted=interpreted, structured=structured,
    valuation_range=valuation_range, capital=capital, research=research,
    thesis=thesis, tracker_commentary=tracker_commentary,
    terminal_guidance=build_terminal_value_guidance(kpis, dcf, capital.get("current_price")),
    market_context=context,
    external_dcf_adjustments=external_dcf_adjustments,
)
excel = export_excel(
    company, kpis, margin_bridge, dcf, recommendations, quality, export_anomalies, capital,
    scan=scan, peer_benchmark=peer_benchmark, dcf_evidence=dcf_bridge,
    peer_names=st.session_state.get("peer_selection", []),
    thesis=thesis, market_context=context, multiple_valuation=multiple_valuation,
    valuation_range=valuation_range, research_reference=research,
    structured=structured, price_action=price_action, interpreted=interpreted,
    tracker_commentary=tracker_commentary,
)

head_l, head_r = st.columns([2.55, 1.45])
with head_l:
    st.markdown(f"## {company} | {latest['period']}")
    st.caption(f"분석 {len(kpis)}개 분기 · 비교기업 {', '.join(st.session_state.get('peer_selection', [])) or '없음'} · 우선 검토 {len(abnormal)}건 · DART 결측 {sum(item['missing_quarters'] for item in quality)}건")
with head_r:
    dl1, dl2 = st.columns(2)
    dl1.download_button("📄 발간 리포트", html_report.encode("utf-8"), file_name=f"FinSight_{company}_Investment_Note.html", mime="text/html", type="primary", width="stretch", help="브라우저용 HTML · 인쇄하면 발간용 PDF")
    dl2.download_button("📊 모델 워크북", excel, file_name=f"FinSight_{company}_Analyst_Workbook.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", help="수식 편집 가능한 12시트 Excel 모델")

market_snap = context.get("market", {})
h1, h2, h3, h4 = st.columns(4)
h1.metric("현재 주가", _fmt(capital.get("current_price"), "원", 0), _fmt(market_snap.get("return_3m"), "% · 3M"))
h2.metric("매출 YoY", _fmt(latest.get("revenue_yoy"), "%"))
h3.metric("영업이익률", _fmt(latest.get("opm"), "%"), _fmt(latest.get("opm_qoq_pp"), "%p"))
h4.metric("FCF 마진", _fmt(latest.get("fcf_margin"), "%"))
st.divider()

report_tab, brief_tab, tracker_tab, diagnostic_tab, peer_tab, dcf_tab, export_tab = st.tabs(
    ["01 리포트", "02 투자판단", "03 실적 트래커", "04 이상 탐지·원인", "05 동종기업 검증", "06 가치평가", "07 근거·출처"]
)

with report_tab:
    render_tab_intro("발간 투자 리포트", "실적·밸류에이션·수급·리스크를 한 장의 발간형 리포트로 정리합니다.", "투자의견 · 산정가치 · 차트 · 체크포인트")
    st.caption("상단 📄 버튼으로 HTML을 받아 브라우저에서 인쇄(⌘P) → PDF로 저장하면 발간용 PDF가 됩니다.")
    components.html(html_report, height=2200, scrolling=True)

with brief_tab:
    render_tab_intro("투자판단과 기대치 괴리", "실적이 좋아도 주가가 오르지 않는 이유를 펀더멘털·기대·수급·촉매 시점으로 분리합니다.", "핵심 판단 · 사실과 해석 구분 · 변동요인 분해 · 확인 포인트")
    st.markdown(f"### {price_action['verdict']}")
    st.write(price_action["thesis"])
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("현재 주가", _fmt(capital.get("current_price"), "원", 0), _fmt(context.get("market", {}).get("return_3m"), "% · 3M"))
    b2.metric("52주 고점 대비", _fmt(context.get("market", {}).get("drawdown_52w_high"), "%"))
    surprise_values = [row["value"] for row in research.get("expectations", []) if row.get("metric") == "operating_profit_surprise"]
    b3.metric("영업이익 기대 괴리", _fmt(pd.Series(surprise_values).median() if surprise_values else None, "%"))
    b4.metric("기준 적정가", _fmt(valuation_range.get("mid"), "원", 0))
    if any(price_action["price_frame"].get(k) is not None for k in ("ret_1m", "ret_3m", "ret_6m")):
        st.plotly_chart(price_path_chart(price_action["price_frame"]), width="stretch", key="brief_price_path_chart")
    st.markdown("#### 주가 변동요인 분해")
    st.caption("주가 등락을 펀더멘털·기대치·수급·촉매로 나눠 각 요인의 기여도를 추정합니다.")
    render_attribution(price_action["attribution"])
    st.markdown("#### 확인된 사실관계")
    st.dataframe(pd.DataFrame(thesis["facts"]), width="stretch", hide_index=True)
    st.markdown("#### 다음 분기에 반드시 확인할 것")
    render_checkpoints(thesis["checkpoints"])
    with st.expander("외부 정황 자료 (미검증 · 참고용)"):
        render_context_items(thesis["context"])

with tracker_tab:
    render_tab_intro("분기 실적 트래커", "어닝 업데이트 숫자를 옮기고 방향이 바뀐 계정을 확인합니다.", "분기 원본 · QoQ/YoY · 매출/OPM/CFO 추세 · 결측")
    st.plotly_chart(financial_trend_chart(kpis), width="stretch", key="tracker_financial_trend_chart")
    if tracker_commentary:
        st.markdown("#### 이번 분기 변화 해석")
        st.caption("숫자 변화 → 가능한 원인 → 투자자 액션 → DCF 가정 연결 순서로 읽도록 구성했습니다.")
        cols = st.columns(min(2, len(tracker_commentary)))
        for idx, card in enumerate(tracker_commentary):
            with cols[idx % len(cols)]:
                with st.container(border=True):
                    st.markdown(f"**{card['title']}**")
                    st.caption(f"판정: {card.get('verdict', '검토')} · 신뢰도: {card.get('confidence', 'Medium')} · 연결: {card.get('model_link', 'DCF')}")
                    st.write(card["read"])
                    evidence = card.get("evidence") or []
                    if evidence:
                        st.markdown("근거")
                        for line in evidence[:4]:
                            st.markdown(f"- {line}")
                    st.markdown("**그래서 사용자는 무엇을 해야 하나**")
                    st.write(card.get("action") or card["so_what"])
                    st.caption(card["so_what"])
                    st.markdown(f"다음 확인: {card['next']}")
    st.dataframe(_tracker_style(build_tracker_table(kpis)), width="stretch", height=460)
    driver_rows = (context.get("external_drivers") or {}).get("status_rows", [])
    if driver_rows:
        with st.expander("외부 검증 데이터 연결 상태 — 수급·원가·무역·매크로"):
            st.dataframe(
                pd.DataFrame(driver_rows).rename(columns={
                    "source": "데이터", "status": "상태", "detail": "현재 의미",
                    "action": "서비스 내 사용처", "evidence_level": "근거 등급",
                    "connected": "연결됨",
                })[["데이터", "상태", "현재 의미", "서비스 내 사용처", "근거 등급"]],
                width="stretch",
                hide_index=True,
            )
    with st.expander("DART 계정 연결 및 결측 점검"):
        render_quality(quality)

with diagnostic_tab:
    render_tab_intro("전 항목 이상 탐지와 원인 추적", "정상 항목까지 전수 스캔하고 자체 과거 범위를 벗어난 항목만 깊게 검증합니다.", "자체 과거 · DART 내부 답 · peer 판정 · 외부 정황 · DCF 연결")
    scan_df = pd.DataFrame([{"영역": x["area"], "지표": x["label"], "현재": x["value"], "과거 중앙값": x["baseline"], "편차": x["deviation"], "판정": x["status"], "근거": x["reason"]} for x in scan])
    st.dataframe(scan_df.style.format({"현재": "{:.1f}", "과거 중앙값": "{:.1f}", "편차": "{:+.1f}"}, na_rep="N/A"), width="stretch", hide_index=True)
    st.markdown("#### 우선 검토 이슈 · 원인 해석")
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
        st.plotly_chart(peer_benchmark_chart(kpis, peer_kpis), width="stretch", key="peer_benchmark_chart")
        st.dataframe(peer_benchmark.style.format({"분석기업": "{:.1f}", "동종기업 중앙값": "{:.1f}", "격차": "{:+.1f}"}, na_rep="N/A"), width="stretch", hide_index=True)
        st.dataframe(build_peer_comparison(kpis, peer_kpis).style.format(precision=1, na_rep="N/A"), width="stretch")
    else:
        st.warning("추천 가능한 동종기업이 없습니다. 자동 추천을 끄고 직접 선택해 주세요.")

with dcf_tab:
    render_tab_intro("가치평가 점검", "단일 DCF 숫자를 정답처럼 제시하지 않고 DCF·PER·EV/EBITDA·증권사 참고값의 차이를 드러냅니다.", "명시적 FCFF · 베타 guardrail · 터미널가치 점검 · 적정가 범위 · 추정치 편차")
    evidence_df = pd.DataFrame([{"가정": row["assumption"], "과거 기반": row["base"], "증거 반영": row["evidence_adjusted"], "조정": row["action"], "신뢰도": row["confidence"], "연결 근거": " / ".join(row["evidence"]) or row["source"]} for row in dcf_bridge])
    st.dataframe(
        evidence_df, width="stretch", hide_index=True,
        column_config={
            "가정": st.column_config.TextColumn("가정", width="small"),
            "조정": st.column_config.TextColumn("조정", width="medium"),
            "연결 근거": st.column_config.TextColumn("연결 근거", width="large"),
        },
    )
    if external_dcf_adjustments:
        st.markdown("#### 외부 변수 DCF 반영")
        st.caption("뉴스·수급·환율·원재료·테마는 확정 실적이 아니므로 보수적인 조정 레이어로만 반영합니다.")
        external_df = pd.DataFrame(external_dcf_adjustments)
        st.dataframe(
            external_df.style.format({"조정 전": "{:.2f}", "조정 후": "{:.2f}"}, na_rep="—"),
            width="stretch", hide_index=True,
            column_config={
                "현재 신호": st.column_config.TextColumn("현재 신호", width="medium"),
                "해석": st.column_config.TextColumn("해석", width="large"),
            },
        )

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
        st.caption(f"최근연도 가중 기업 성장률 {_fmt(rev_model['recent_company_growth'],'%')} · 산업 proxy {_fmt(rev_model['industry_growth_avg'],'%')} · 점유율 기여 {_fmt(rev_model['share_growth_avg'],'%p')}")
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
        st.caption("자동 DCF의 OPM은 단순 추세선이 아니라 판관비 바텀업 빌드로 산출됩니다 — 연도별 " + " → ".join(f"{v:.1f}%" for v in opm_build["opm_path"] if v is not None))
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
            st.session_state["dcf_is_auto"], st.session_state["dcf_version"] = False, 7
        except ValueError as exc:
            st.error(str(exc))
    dcf = st.session_state.get("dcf")
    valuation_range = build_valuation_range(dcf, multiple_valuation, capital.get("current_price"))
    st.markdown("#### 현재가와 적정가 범위")
    st.caption("DCF, PER, EV/EBITDA, 리서치 참고값을 함께 본 참고 범위입니다. 확정 목표가는 아닙니다.")
    if not multiple_valuation.empty:
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("현재가", _fmt(capital.get("current_price"), "원", 0))
        p2.metric("보수적 적정가", _fmt(valuation_range.get("low"), "원", 0))
        p3.metric("기준 적정가", _fmt(valuation_range.get("mid"), "원", 0))
        p4.metric("낙관적 적정가", _fmt(valuation_range.get("high"), "원", 0))
        p5.metric("추정치 편차", _fmt(valuation_range.get("dispersion"), "%", 1))
        st.plotly_chart(
            valuation_range_band(capital.get("current_price"), valuation_range),
            width="stretch",
            key="valuation_range_band_chart",
        )
        with st.expander("계산에 사용한 방법별 값 보기", expanded=False):
            mv = multiple_valuation.rename(columns={
                "method": "방법", "case": "케이스", "multiple": "배수",
                "implied_price": "적정주가", "upside": "상승여력", "basis": "근거",
            })
            st.dataframe(
                mv.style.format({"배수": "{:.1f}", "적정주가": "{:,.0f}", "상승여력": "{:+.1f}%"}, na_rep="—"),
                width="stretch", hide_index=True,
                column_config={"근거": st.column_config.TextColumn("근거", width="medium")},
            )
            note = research.get("valuation", {}).get("note")
            if note:
                st.caption(note)
    else:
        st.info("적정가 범위를 만들 수 있는 비교값이 아직 부족합니다. DCF 계산값과 리서치 참고값을 먼저 확인하세요.")

    if dcf:
        if st.session_state.get("dcf_is_auto"):
            st.info("탐지 근거를 반영한 예비 DCF입니다. 확정 가치가 아니라 검토 시작점입니다.")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("WACC", _fmt(dcf["wacc"], "%", 2)); d2.metric("WACC-g", _fmt(dcf.get("wacc_growth_spread"), "%p", 2)); d3.metric("TV/EV", _fmt(dcf.get("terminal_value_share"), "%", 1)); d4.metric("DCF 주당가치", _fmt(dcf["implied_price"], "원", 0))
        if dcf.get("guardrails", {}).get("terminal_value_watch"):
            tv_guidance = build_terminal_value_guidance(kpis, dcf, capital.get("current_price"))
            st.warning(tv_guidance.get("headline") or "터미널가치 비중이 높습니다.")
            with st.expander("상세 조정안 보기 — 권장 Base·하방 스트레스", expanded=False):
                st.write(tv_guidance.get("diagnosis", ""))
                tv_rows = pd.DataFrame(tv_guidance.get("rows", []))
                if not tv_rows.empty:
                    tv_display = tv_rows.rename(columns={
                        "case": "시나리오", "wacc": "WACC(%)", "perpetual_growth": "영구성장률(%)",
                        "terminal_revenue_growth": "5년차 성장률(%)", "terminal_opm": "5년차 OPM(%)",
                        "spread": "WACC-g(%p)", "implied_price": "주당가치", "upside": "현재가 대비",
                        "action": "해석/사용법",
                    })
                    st.dataframe(
                        tv_display[["시나리오", "WACC(%)", "영구성장률(%)", "WACC-g(%p)", "5년차 성장률(%)", "5년차 OPM(%)", "주당가치", "현재가 대비", "해석/사용법"]].style.format({
                            "WACC(%)": "{:.2f}", "영구성장률(%)": "{:.1f}", "WACC-g(%p)": "{:.2f}",
                            "5년차 성장률(%)": "{:.1f}", "5년차 OPM(%)": "{:.1f}",
                            "주당가치": "{:,.0f}", "현재가 대비": "{:+.1f}%",
                        }, na_rep="—"),
                        width="stretch", hide_index=True,
                        column_config={"해석/사용법": st.column_config.TextColumn("해석/사용법", width="large")},
                    )
                st.caption(tv_guidance.get("decision_rule", ""))
        st.markdown("**5개년 FCFF 추정** · 금액 단위 억원")
        fc = dcf["forecast"]
        _eok = lambda col: pd.to_numeric(fc.get(col), errors="coerce") / 1e8
        fc_display = pd.DataFrame({
            "연도": pd.to_numeric(fc["year"], errors="coerce").astype("Int64").astype(str),
            "매출(억)": _eok("revenue"), "성장률(%)": pd.to_numeric(fc["revenue_growth"], errors="coerce"),
            "OPM(%)": pd.to_numeric(fc["opm"], errors="coerce"), "EBIT(억)": _eok("ebit"),
            "NOPAT(억)": _eok("nopat"), "D&A(억)": _eok("depreciation"), "CAPEX(억)": _eok("capex"),
            "ΔNWC(억)": _eok("change_in_nwc"), "FCFF(억)": _eok("fcff"),
            "할인계수": pd.to_numeric(fc["discount_factor"], errors="coerce"), "PV(억)": _eok("pv_fcff"),
        })
        amount_cols = ["매출(억)", "EBIT(억)", "NOPAT(억)", "D&A(억)", "CAPEX(억)", "ΔNWC(억)", "FCFF(억)", "PV(억)"]
        st.dataframe(
            fc_display.style.format(
                {**{c: "{:,.0f}" for c in amount_cols}, "성장률(%)": "{:.1f}", "OPM(%)": "{:.1f}", "할인계수": "{:.3f}"},
                na_rep="—",
            ),
            width="stretch", hide_index=True,
        )
        sensitivity = run_dcf_sensitivity(kpis, dcf["assumptions"], dcf["shares_outstanding"], dcf["net_debt"])
        st.markdown("**민감도 — 주당가치(원)** · 행: 성장률 ±%p, 열: OPM ±%p")
        st.dataframe(sensitivity.pivot(index="성장률 변화(%p)", columns="OPM 변화(%p)", values="주당가치").style.format("{:,.0f}"), width="stretch")
    elif st.session_state.get("dcf_error"):
        st.error(st.session_state["dcf_error"])

with export_tab:
    render_tab_intro("근거·출처 전수", "이 분석이 어떤 데이터·공시·뉴스·검증을 거쳤는지 모두 펼쳐 신뢰도를 점검합니다.", "데이터 커버리지 · 외부연결 상태 · 공시·뉴스 원문 · 결측 점검")
    if has_blocking_gaps(quality):
        st.warning("매출액 또는 영업이익 결측이 있습니다. 상단 Excel의 Checks 시트를 먼저 확인하세요.")
    st.markdown("#### 데이터 커버리지")
    coverage = pd.DataFrame([
        {"근거 계층": "DART 재무", "상태": "Connected", "내용": f"{len(kpis)}개 분기"},
        {"근거 계층": "DART 공시", "상태": "Connected" if context.get("disclosures") else "Unavailable", "내용": f"{len(context.get('disclosures', []))}건"},
        {"근거 계층": "외부 뉴스", "상태": "Connected" if context.get("news") else "Unavailable", "내용": f"{len(context.get('news', []))}건"},
        {"근거 계층": "DART 지분공시", "상태": "Connected" if context.get("ownership") else "Unavailable", "내용": f"{len(context.get('ownership', []))}건"},
        {"근거 계층": "시장 가격", "상태": "Connected" if context.get("market") else "Unavailable", "내용": context.get("market", {}).get("as_of", "")},
        {"근거 계층": "KRX 수급", "상태": "Connected" if (context.get("external_drivers", {}).get("flows", {}).get("connected")) else "Needs setup", "내용": context.get("external_drivers", {}).get("flows", {}).get("verdict") or context.get("external_drivers", {}).get("flows", {}).get("reason", "")},
        {"근거 계층": "원가·무역·매크로 API", "상태": "Mixed", "내용": f"{sum(1 for r in context.get('external_drivers', {}).get('status_rows', []) if r.get('connected'))}/{len(context.get('external_drivers', {}).get('status_rows', []))}개 연결"},
        {"근거 계층": "리서치 참고", "상태": "Connected" if research.get("valuation") else "Unavailable", "내용": f"{len(research.get('expectations', []))}개 기대치 비교"},
        {"근거 계층": "동종기업", "상태": "Connected" if peer_kpis else "Unavailable", "내용": f"{len(peer_kpis)}개사"},
    ])
    st.dataframe(coverage, width="stretch", hide_index=True)

    driver_rows = (context.get("external_drivers") or {}).get("status_rows", [])
    if driver_rows:
        st.markdown("#### 외부 연결 상태 — 수급·원가·무역·매크로")
        st.dataframe(
            pd.DataFrame(driver_rows).rename(columns={
                "source": "데이터", "status": "상태", "detail": "현재 의미",
                "action": "서비스 내 사용처", "evidence_level": "근거 등급",
            })[["데이터", "상태", "현재 의미", "서비스 내 사용처", "근거 등급"]],
            width="stretch", hide_index=True,
            column_config={
                "현재 의미": st.column_config.TextColumn("현재 의미", width="medium"),
                "서비스 내 사용처": st.column_config.TextColumn("서비스 내 사용처", width="medium"),
            },
        )

    src_items = (
        [{"유형": "DART 공시", **d} for d in context.get("disclosures", [])]
        + [{"유형": "뉴스", **n} for n in context.get("news", [])]
        + [{"유형": "블로그", **b} for b in context.get("blogs", [])]
    )
    if src_items:
        with st.expander(f"공시·뉴스 원문 ({len(src_items)}건) — 클릭해 출처 확인", expanded=False):
            render_context_items(src_items)

    st.markdown("#### 데이터 품질·결측 점검")
    render_quality(quality)
