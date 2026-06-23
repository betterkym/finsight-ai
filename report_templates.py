"""Plain-text summary included alongside the Excel deliverable."""

from __future__ import annotations

import datetime as dt

import pandas as pd


def generate_analysis_summary(company: str, kpis: pd.DataFrame, bridge: pd.DataFrame, anomalies: list[dict], dcf: dict | None) -> str:
    latest = kpis.iloc[-1]
    pattern = bridge.iloc[-1] if not bridge.empty else {}
    lines = [
        f"# FinSight 분기 실적 분석 — {company}", "",
        f"기준 분기: {latest['period']} · 생성일: {dt.date.today().isoformat()}", "",
        "## 최신 분기",
        f"- 매출 YoY: {latest.get('revenue_yoy', float('nan')):.1f}%",
        f"- OPM: {latest.get('opm', float('nan')):.1f}% (QoQ {latest.get('opm_qoq_pp', float('nan')):+.1f}%p)",
        f"- CFO/매출: {latest.get('cfo_margin', float('nan')):.1f}%",
        "", "## 마진 변동 분해",
        f"- {pattern.get('pattern', '비교 데이터 부족')}: {pattern.get('comment', '')}",
        "", "## 재무 이상 신호",
    ]
    lines.extend([f"- [{item['severity']}] {item['signal']}: {item['comment']}" for item in anomalies] or ["- 특이 패턴 없음"])
    if dcf:
        lines.extend(["", "## DCF", f"- WACC: {dcf['wacc']:.2f}%", f"- 기업가치: {dcf['enterprise_value']:,.0f}", f"- 주당가치: {dcf['implied_price']:,.0f}" if dcf.get("implied_price") is not None else "- 주당가치: 주식수 입력 필요"])
    lines.extend(["", "> 모든 해석은 DART 재무 패턴에 기반한 가능한 설명이며 확정 원인이 아닙니다."])
    return "\n".join(lines)


generate_business_report = generate_analysis_summary
generate_analyst_report = generate_analysis_summary
generate_executive_brief = generate_analysis_summary
