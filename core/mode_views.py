"""Presentation-ready tables for the narrowed FinSight workflow."""

from __future__ import annotations

import pandas as pd


TRACKER_COLUMNS = {
    "period": "분기", "revenue": "매출액(억원)", "revenue_qoq": "매출 QoQ(%)", "revenue_yoy": "매출 YoY(%)",
    "operating_profit": "영업이익(억원)", "opm": "OPM(%)", "opm_qoq_pp": "OPM QoQ(%p)",
    "net_income": "순이익(억원)", "net_margin": "순이익률(%)", "cfo": "CFO(억원)", "cfo_margin": "CFO/매출(%)",
    "capex": "CAPEX(억원)", "fcf": "FCF(억원)", "cogs_ratio": "원가율(%)", "sga_ratio": "판관비율(%)",
    "receivables": "매출채권(억원)", "inventory": "재고자산(억원)", "payables": "매입채무(억원)",
    "ar_days": "채권회수일", "inventory_days": "재고일수", "payable_days": "지급일수",
}


def build_tracker_table(kpis: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in TRACKER_COLUMNS if column in kpis]
    frame = kpis[columns].copy()
    amount_columns = ["revenue", "operating_profit", "net_income", "cfo", "capex", "fcf", "receivables", "inventory", "payables"]
    for column in amount_columns:
        if column in frame:
            frame[column] = frame[column] / 1e8
    return frame.rename(columns=TRACKER_COLUMNS).set_index("분기")


def build_peer_comparison(primary: pd.DataFrame, peers: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    company_frames = {str(primary.iloc[-1].get("company", "분석 기업")): primary, **peers}
    for company, frame in company_frames.items():
        if frame.empty:
            continue
        latest = frame.iloc[-1]
        frames.append({
            "기업": company, "기준 분기": latest.get("period"), "매출 성장률 YoY(%)": latest.get("revenue_yoy"),
            "OPM(%)": latest.get("opm"), "OPM QoQ(%p)": latest.get("opm_qoq_pp"), "FCF 마진(%)": latest.get("fcf_margin"),
        })
    return pd.DataFrame(frames).set_index("기업") if frames else pd.DataFrame()


BENCHMARK_METRICS = {
    "revenue_yoy": ("매출 성장률 YoY", "%"),
    "opm": ("영업이익률", "%"),
    "cfo_margin": ("CFO 마진", "%"),
    "fcf_margin": ("FCF 마진", "%"),
    "ar_days": ("매출채권 회수일수", "일"),
    "inventory_days": ("재고 회전일수", "일"),
    "capex_ratio": ("CAPEX/매출", "%"),
    "debt_ratio": ("부채비율", "%"),
}


def build_peer_benchmark(primary: pd.DataFrame, peers: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    if primary.empty:
        return pd.DataFrame()
    target = primary.iloc[-1]
    for metric, (label, unit) in BENCHMARK_METRICS.items():
        target_value = target.get(metric)
        values = []
        for name, frame in peers.items():
            if not frame.empty and metric in frame and pd.notna(frame.iloc[-1].get(metric)):
                values.append(float(frame.iloc[-1][metric]))
        peer_median = pd.Series(values).median() if values else None
        rows.append({
            "metric_key": metric, "지표": label, "단위": unit,
            "분석기업": None if pd.isna(target_value) else target_value,
            "동종기업 중앙값": peer_median,
            "격차": None if peer_median is None or pd.isna(target_value) else float(target_value) - peer_median,
            "비교기업 수": len(values),
        })
    return pd.DataFrame(rows)


def format_recommendation(item: dict) -> str:
    low, high = item["recommended"]
    if low is None or high is None:
        return "데이터 확인 필요"
    return f"{low:.1f}–{high:.1f}"


# Small compatibility wrapper: the old three-mode data model is intentionally gone.
def build_analysis_result(company, financials, kpis, market=None, macro=None, analysis=None, current=None):
    return {"company": company, "financials": financials, "kpis": kpis, "macro": macro or {}, "analysis": analysis or {}}
