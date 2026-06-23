"""Sell-side style investment note (pure Markdown) shipped with the Excel workbook."""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd


def _f(value, suffix="", digits=1):
    return "N/A" if value is None or (isinstance(value, float) and pd.isna(value)) else f"{value:,.{digits}f}{suffix}"


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def _row(*cells) -> str:
    return "| " + " | ".join(_clean(cell) for cell in cells) + " |"


def _gap_label(gap: float | None) -> str:
    if gap is None:
        return "판단 보류"
    if gap > 50:
        return "산정가치는 높지만 시장이 아직 반영하지 않은 구간"
    if gap > 15:
        return "상승여력은 열려 있으나 재평가 조건 확인이 선행되어야 하는 구간"
    if gap > -15:
        return "현재가가 산정가치에 근접한 구간"
    return "모델 가정이 시장보다 낙관적인 구간"


def rating_from_gap(gap: float | None) -> tuple[str, str]:
    """Quantitative stance derived from the cross-checked valuation gap. Not an official rating."""
    if gap is None:
        return ("의견 보류", "가격 또는 가치 입력이 부족해 정량 의견을 유보합니다.")
    if gap > 25:
        return ("비중확대", "교차검증 산정가치가 현재가를 뚜렷이 상회합니다.")
    if gap >= -10:
        return ("중립", "산정가치와 현재가의 괴리가 크지 않습니다.")
    return ("비중축소", "현재가가 교차검증 산정가치를 상회합니다.")


def build_report_model(
    company: str,
    kpis: pd.DataFrame,
    dcf: dict | None,
    *,
    price_action: dict | None = None,
    interpreted: list[dict] | None = None,
    structured: dict | None = None,
    valuation_range: dict | None = None,
    capital: dict | None = None,
    research: dict | None = None,
    thesis: dict | None = None,
    tracker_commentary: list[dict] | None = None,
) -> dict:
    """Normalize every report input into a single structure shared by the .md and the in-app view."""
    latest = kpis.iloc[-1]
    pa = price_action or {}
    capital = capital or {}
    vr = valuation_range or {}
    structured = structured or {}
    research = research or {}
    thesis = thesis or {}

    current = _num(capital.get("current_price"))
    dcf_price = _num((dcf or {}).get("implied_price"))
    cross_mid = _num(vr.get("mid"))
    dcf_gap = (dcf_price / current - 1) * 100 if dcf_price and current else None
    cross_gap = (cross_mid / current - 1) * 100 if cross_mid and current else None
    headline_gap = cross_gap if cross_gap is not None else dcf_gap
    rating, rating_note = rating_from_gap(headline_gap)

    frame = pa.get("price_frame", {})
    summary = _investment_summary(latest, pa, vr, current, headline_gap, thesis)
    snapshot = _earnings_snapshot(latest)
    valuation_rows = _valuation_rows(dcf, dcf_price, dcf_gap, cross_mid, cross_gap, research)
    gap_reasons = _gap_reasons(dcf, frame)
    decision_rows = _decision_rows(thesis, tracker_commentary)

    wacc = structured.get("wacc") or {}
    opm_path = (structured.get("opm_build") or {}).get("opm_path", [])

    return {
        "company": company,
        "code": str(latest.get("stock_code", "") or ""),
        "period": latest.get("period", ""),
        "gen_date": dt.date.today().isoformat(),
        "rating": rating,
        "rating_note": rating_note,
        "verdict": pa.get("verdict") or _gap_label(headline_gap),
        "thesis": pa.get("thesis") or thesis.get("summary", ""),
        "current_price": current,
        "target_mid": cross_mid,
        "target_low": _num(vr.get("low")),
        "target_high": _num(vr.get("high")),
        "upside": cross_gap,
        "dcf_price": dcf_price,
        "dcf_gap": dcf_gap,
        "terminal_share": _num((dcf or {}).get("terminal_value_share")),
        "wacc": wacc,
        "opm_path": [v for v in opm_path if v is not None],
        "summary_points": summary,
        "snapshot": snapshot,
        "valuation_rows": valuation_rows,
        "attribution": pa.get("attribution", []),
        "gap_reasons": gap_reasons,
        "decision_rows": decision_rows,
        "tracker_commentary": tracker_commentary or [],
        "interpreted": interpreted or [],
        "broker_targets": research.get("valuation", {}).get("broker_targets", []),
        "frame": frame,
    }


def _investment_summary(latest, pa, vr, current, gap, thesis) -> list[str]:
    points = []
    rev, opm, qoq = latest.get("revenue_yoy"), latest.get("opm"), latest.get("opm_qoq_pp")
    points.append(
        f"**실적은 무너지지 않았다.** 매출 YoY {_f(rev, '%')}, 영업이익률 {_f(opm, '%')}"
        f"(QoQ {_f(qoq, '%p')})로 외형·수익성이 추세를 유지했다."
    )
    if vr.get("mid") is not None and current:
        points.append(
            f"**산정가치는 현재가를 상회한다.** 교차검증 중앙값 {_f(vr.get('mid'), '원', 0)}"
            f"(현재가 대비 {_f(gap, '%')}), 단 상승 실현에는 재평가 조건 확인이 선행된다."
        )
    if pa.get("verdict"):
        points.append(f"**주가 약세의 축은 펀더멘털이 아니다.** {_clean(pa.get('verdict'))}.")
    checkpoints = thesis.get("checkpoints", []) if isinstance(thesis, dict) else []
    if checkpoints:
        first = checkpoints[0]
        label = first if isinstance(first, str) else first.get("checkpoint", "")
        if label:
            points.append(f"**다음 분기 관전 포인트.** {_clean(label)}가 숫자로 확인되는지가 재평가의 1차 트리거다.")
    return points


def _earnings_snapshot(latest) -> list[list[str]]:
    return [
        ["매출 성장", _f(latest.get("revenue_yoy"), "%"), f"QoQ {_f(latest.get('revenue_qoq'), '%')}", "외형 방향. 가격·물량·환율 분해 전까지 질은 미확정"],
        ["영업이익률", _f(latest.get("opm"), "%"), f"QoQ {_f(latest.get('opm_qoq_pp'), '%p')}", "원가율·판관비율 중 어느 축이 움직였는지 확인"],
        ["원가율 / 판관비율", f"{_f(latest.get('cogs_ratio'), '%')} / {_f(latest.get('sga_ratio'), '%')}", "—", "마진 변화의 1차 원인"],
        ["현금흐름 (CFO / FCF)", f"{_f(latest.get('cfo_margin'), '%')} / {_f(latest.get('fcf_margin'), '%')}", "—", "이익의 현금 전환. 밸류에이션 신뢰도의 핵심"],
    ]


def _valuation_rows(dcf, dcf_price, dcf_gap, cross_mid, cross_gap, research) -> list[list[str]]:
    rows = [
        ["DCF", _f(dcf_price, "원", 0), _f(dcf_gap, "%"), "영업가정·할인율이 맞을 때의 이론값"],
        ["교차검증 중앙", _f(cross_mid, "원", 0), _f(cross_gap, "%"), "DCF·PER·EV/EBITDA·리서치 참고값의 중간"],
    ]
    for t in research.get("valuation", {}).get("broker_targets", [])[:3]:
        rows.append([f"참고 · {t.get('source','')}", _f(_num(t.get('target_price')), "원", 0), "—", "외부 리서치 목표가(검증용)"])
    return rows


def _gap_reasons(dcf, frame) -> list[str]:
    terminal = _num((dcf or {}).get("terminal_value_share"))
    drawdown = _num((frame or {}).get("drawdown"))
    reasons = [
        "**확인의 시간차** — 모델은 미래 현금흐름을 현재로 당겨오지만, 시장은 다음 분기 실적과 수급이 확인될 때까지 할인한다.",
        "**가정의 민감도** — 매출·마진 가정을 소폭만 높여도 DCF는 크게 변하지만, 시장은 원가·환율·경쟁·CAPEX 회수 지연을 먼저 반영한다.",
        "**수급·심리** — 손실 구간 매물과 기관·외국인 순매도가 남아 있으면 양호한 실적도 즉시 멀티플 확장으로 이어지지 않는다.",
    ]
    if terminal is not None and terminal > 75:
        reasons.append(f"**터미널 의존도** — DCF 가치의 {_f(terminal, '%')}가 잔존가치에서 발생해 WACC·영구성장률 변화에 민감하다.")
    if drawdown is not None and drawdown < -20:
        reasons.append(f"**고점 대비 낙폭** — 52주 고점 대비 {_f(drawdown, '%')}로, 사라진 프리미엄의 원인을 별도로 설명해야 한다.")
    return reasons


def _decision_rows(thesis, tracker_commentary) -> list[list[str]]:
    rows = []
    for c in (thesis or {}).get("checkpoints", [])[:5]:
        if isinstance(c, str):
            rows.append([c, "해당 논점 신뢰도 상승", "보수 가정 유지", "단일 분기 신호로 목표가 불변"])
        else:
            rows.append([c.get("checkpoint", ""), c.get("if_confirmed", ""), c.get("if_not_confirmed", ""), c.get("action", "")])
    if not rows:
        for card in (tracker_commentary or [])[:4]:
            rows.append([card.get("next", ""), "연결 가정 상향 검토", "기본/보수 시나리오 유지", card.get("action", "")])
    return rows


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
    thesis: dict | None = None,
    tracker_commentary: list[dict] | None = None,
) -> str:
    m = build_report_model(
        company, kpis, dcf, price_action=price_action, interpreted=interpreted,
        structured=structured, valuation_range=valuation_range, capital=capital,
        research=research, thesis=thesis, tracker_commentary=tracker_commentary,
    )
    code = f" ({m['code']})" if m["code"] else ""
    lines: list[str] = [
        f"# {company}{code} — 투자 노트",
        "",
        f"**정량 투자의견: {m['rating']}**  ·  산정가치 {_f(m['target_mid'], '원', 0)}  ·  "
        f"현재가 {_f(m['current_price'], '원', 0)}  ·  상승여력 {_f(m['upside'], '%')}",
        "",
        "| 항목 | 내용 |",
        "|---|---|",
        _row("기준 분기", m["period"]),
        _row("생성일", m["gen_date"]),
        _row("DCF 주당가치", f"{_f(m['dcf_price'], '원', 0)} (현재가 대비 {_f(m['dcf_gap'], '%')})"),
        _row("산정가치 범위", f"{_f(m['target_low'], '원', 0)} ~ {_f(m['target_high'], '원', 0)}"),
        _row("출처", "DART 재무·공시 / 시세 / 리서치 참고자료"),
        "",
        f"> **핵심 결론** — {_clean(m['verdict'])}",
        "",
        "---",
        "",
        "## I. Investment Summary",
        "",
        *[f"- {p}" for p in m["summary_points"]],
        "",
        "## II. 실적 리뷰",
        "",
        f"_{m['period']} 기준_",
        "",
        "| 지표 | 값 | 변화 | 코멘트 |",
        "|---|---:|---:|---|",
        *[_row(*r) for r in m["snapshot"]],
        "",
    ]
    if m["thesis"]:
        lines += [_clean(m["thesis"]), ""]
    if m["tracker_commentary"]:
        lines.append("**이번 분기 핵심 변화**")
        lines.append("")
        for card in m["tracker_commentary"][:3]:
            lines.append(f"- **{_clean(card.get('title'))}** — {_clean(card.get('read'))}")
        lines.append("")

    lines += [
        "## III. 밸류에이션",
        "",
        "| 방법 | 주당가치 | 현재가 대비 | 비고 |",
        "|---|---:|---:|---|",
        *[_row(*r) for r in m["valuation_rows"]],
        "",
    ]
    w = m["wacc"]
    if w:
        lines.append(
            f"- **WACC {_f(w.get('wacc'), '%', 2)}** = Rf {_f(w.get('rf'), '%')} + β {_f(w.get('beta'), '', 3)} "
            f"× ERP {_f(w.get('erp'), '%')} → Ke {_f(w.get('cost_equity'), '%')} (β 산출: {_clean(w.get('beta_source'))})"
        )
    if m["opm_path"]:
        lines.append("- **OPM 경로(판관비 bottom-up)**: " + " → ".join(_f(v, "%") for v in m["opm_path"]))
    if m["terminal_share"] is not None:
        lines.append(f"- 터미널가치 비중 {_f(m['terminal_share'], '%')} — 잔존가치 의존도와 할인율 민감도를 함께 확인")
    lines.append("")

    if m["attribution"]:
        lines += [
            "## IV. 주가 괴리 분석",
            "",
            f"{_clean(m['verdict'])}. 주가 등락을 네 가지 축으로 분해하면 다음과 같다.",
            "",
            "| 변동요인 | 강도 | 해석 | 근거 |",
            "|---|---|---|---|",
        ]
        for a in m["attribution"]:
            lines.append(_row(a.get("driver", ""), a.get("weight", ""), str(a.get("reading", "")).replace("\n", " "),
                              f"{a.get('evidence','')} ({a.get('evidence_level','')})"))
        lines.append("")
        lines.append("**산정가치와 현재가가 벌어진 이유**")
        lines.append("")
        for i, reason in enumerate(m["gap_reasons"], 1):
            lines.append(f"{i}. {reason}")
        lines.append("")

    lines += ["## V. 리스크 및 체크포인트", ""]
    if m["decision_rows"]:
        lines += [
            "| 확인할 것 | 확인되면 | 확인 안 되면 | 가정 조정 |",
            "|---|---|---|---|",
            *[_row(*r) for r in m["decision_rows"]],
            "",
        ]
    if m["interpreted"]:
        lines.append("**우선 검토 이상신호**")
        lines.append("")
        for idx, item in enumerate(m["interpreted"], 1):
            I = item.get("interpretation", {})
            top = (I.get("cause_candidates") or [{}])[0]
            cause = f" — 원인 후보: [{top.get('evidence_level','')}] {top.get('cause','')}" if top.get("cause") else ""
            lines.append(f"{idx}. **{_clean(I.get('headline', item.get('label','')))}** (해석 신뢰도 {I.get('confidence','')}){cause}")
        lines.append("")

    lines += [
        "---",
        f"_{company} 투자 노트 · {m['gen_date']} 생성. 본 자료는 DART 재무 패턴과 공시·뉴스·리서치 참고자료를 함께 검토한 자료이며, "
        "‘정량 투자의견’은 교차검증 산정가치와 현재가의 괴리에서 기계적으로 도출한 참고치로 공식 투자의견이 아닙니다. "
        "투자 판단은 다음 분기 확인되는 실적과 수급을 함께 보아야 합니다._",
    ]
    return "\n".join(lines)


generate_business_report = generate_analysis_summary
generate_analyst_report = generate_analysis_summary
generate_executive_brief = generate_analysis_summary
