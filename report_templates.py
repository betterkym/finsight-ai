"""Analyst one-pager (Markdown) shipped alongside the Excel workbook."""

from __future__ import annotations

import datetime as dt

import pandas as pd


def _f(value, suffix="", digits=1):
    return "N/A" if value is None or (isinstance(value, float) and pd.isna(value)) else f"{value:,.{digits}f}{suffix}"


def generate_analysis_summary(
    company: str,
    kpis: pd.DataFrame,
    bridge: pd.DataFrame,
    anomalies: list[dict],
    dcf: dict | None,
    *,
    price_action: dict | None = None,
    interpreted: list[dict] | None = None,
    structured: dict | None = None,
    valuation_range: dict | None = None,
    capital: dict | None = None,
    research: dict | None = None,
) -> str:
    latest = kpis.iloc[-1]
    pa = price_action or {}
    capital = capital or {}
    vr = valuation_range or {}
    lines = [
        f"# {company} — 분석 노트",
        f"_{latest['period']} 기준 · 생성 {dt.date.today().isoformat()} · 출처: DART 재무·공시, 시세, (참고) 리서치·뉴스_",
        "",
    ]

    if pa.get("verdict"):
        lines += [f"## 판정 — {pa['verdict']}", pa.get("thesis", ""), ""]

    # Price-action attribution
    if pa.get("attribution"):
        lines += ["## 주가 움직임의 기여 분해", "", "| 드라이버 | 비중 | 해석 | 근거 |", "|---|---|---|---|"]
        for a in pa["attribution"]:
            reading = str(a.get("reading", "")).replace("\n", " ")
            lines.append(f"| {a.get('driver','')} | {a.get('weight','')} | {reading} | {a.get('evidence','')} ({a.get('evidence_level','')}) |")
        lines.append("")

    # Operating snapshot
    lines += [
        "## 실적 스냅샷",
        f"- 매출 YoY {_f(latest.get('revenue_yoy'),'%')} · 영업이익률 {_f(latest.get('opm'),'%')} (QoQ {_f(latest.get('opm_qoq_pp'),'%p')})",
        f"- CFO/매출 {_f(latest.get('cfo_margin'),'%')} · FCF 마진 {_f(latest.get('fcf_margin'),'%')} · 원가율 {_f(latest.get('cogs_ratio'),'%')} · 판관비율 {_f(latest.get('sga_ratio'),'%')}",
    ]
    if capital.get("current_price") is not None:
        m = (price_action or {}).get("price_frame", {})
        lines.append(f"- 현재가 {_f(capital.get('current_price'),'원',0)} · 3개월 {_f(m.get('ret_3m'),'%')} · 52주 고점 대비 {_f(m.get('drawdown'),'%')}")
    lines.append("")

    # Abnormal signals → cause → recipe
    interp = interpreted or []
    lines.append("## 이상신호 · 원인 해석 · 검증 레시피")
    if not interp:
        lines.append("- 자체 과거 범위와 절대 기준에서 우선 검토할 이상 항목 없음")
    for idx, item in enumerate(interp, 1):
        I = item.get("interpretation", {})
        lines.append(f"\n### {idx}. {I.get('headline', item.get('label',''))}  ·  해석 신뢰도 {I.get('confidence','')}")
        lines.append(I.get("narrative", ""))
        causes = I.get("cause_candidates", [])
        if causes:
            lines.append("\n**원인 후보 (근거 강도순)**")
            for c in causes:
                src = c.get("source", "")
                lines.append(f"- [{c.get('evidence_level','')}] {c.get('cause','')} — {src}")
        if I.get("verification"):
            lines.append("\n**검증 레시피**")
            for j, r in enumerate(I["verification"], 1):
                lines.append(f"{j}. **어디서** {r.get('where','')}")
                lines.append(f"   - **무엇을** {r.get('what','')}")
                lines.append(f"   - **판정** {r.get('rule','')}")
        if I.get("falsifier"):
            lines.append(f"\n> 반증: {I['falsifier']}")
    lines.append("")

    # Valuation
    lines.append("## 밸류에이션")
    if dcf:
        lines += [
            f"- WACC {_f(dcf.get('wacc'),'%',2)} · 터미널/EV {_f(dcf.get('terminal_value_share'),'%')} · DCF 주당가치 {_f(dcf.get('implied_price'),'원',0)}",
        ]
        if dcf.get("opm_path_used"):
            lines.append("- OPM은 단일 fade가 아니라 판관비 바텀업 빌드(인건비·변동비·고정비·대손)로 연도별 산출")
    if structured and structured.get("opm_build"):
        path = structured["opm_build"].get("opm_path", [])
        if path:
            lines.append("- 바텀업 OPM 경로: " + " → ".join(_f(v, "%") for v in path if v is not None))
    if structured and structured.get("wacc"):
        w = structured["wacc"]
        lines.append(f"- WACC 구성: Rf {_f(w.get('rf'),'%')} + β {_f(w.get('beta'),'',3)} × ERP {_f(w.get('erp'),'%')} → Ke {_f(w.get('cost_equity'),'%')}; β 산출 {w.get('beta_source','')}")
    if vr.get("mid") is not None:
        upside = (vr["mid"] / capital["current_price"] - 1) * 100 if capital.get("current_price") else None
        lines.append(f"- 교차검증(DCF·PER·EV/EBITDA·리서치) 중앙 {_f(vr.get('mid'),'원',0)} (하단 {_f(vr.get('low'),'원',0)} / 상단 {_f(vr.get('high'),'원',0)}) · 현재가 대비 {_f(upside,'%')}")
    if research and research.get("valuation", {}).get("broker_targets"):
        tgts = ", ".join(f"{t['source']} {t['target_price']:,}원" for t in research["valuation"]["broker_targets"])
        lines.append(f"- 참고 브로커 목표가: {tgts}")
    lines.append("")

    # Checkpoints
    checkpoints = (research or {}).get("checkpoints", []) if research else []
    if checkpoints:
        lines.append("## 다음 분기 체크포인트")
        lines += [f"- {c}" for c in checkpoints]
        lines.append("")

    lines += [
        "---",
        "_이 노트는 DART 재무 패턴과 매칭된 공시·뉴스에 근거한 검토용 해석입니다. 원인 후보는 근거 강도(1차 공시 > 리서치 추정 > 보도 정황 > 미검증)를 명시했으며, 확정 결론이 아니라 검증 레시피로 직접 확인할 출발점입니다._",
    ]
    return "\n".join(lines)


generate_business_report = generate_analysis_summary
generate_analyst_report = generate_analysis_summary
generate_executive_brief = generate_analysis_summary
