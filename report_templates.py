"""Sell-side style investment notes shipped with the Excel workbook and HTML export."""

from __future__ import annotations

import datetime as dt
import html
import math
import re

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


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _inline(value) -> str:
    """Escape text and preserve simple **bold** emphasis for the HTML report."""
    text = _e(value)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _source_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    body = ""
    for item in rows:
        title = item.get("title") or item.get("source") or "외부 자료"
        body += (
            "<tr>"
            f"<td>{_e(item.get('date') or item.get('published') or '')}</td>"
            f"<td>{_e(item.get('source') or '')}</td>"
            f"<td>{_html_link(title, item.get('url'))}</td>"
            f"<td>{_e(item.get('summary') or item.get('description') or '제목 기준 매칭. 원문 확인 전에는 참고 정황으로만 사용.')}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>일자</th><th>출처</th><th>자료</th><th>리포트 내 사용 방식</th></tr></thead><tbody>" + body + "</tbody></table>"


def _html_link(label: str, url: str | None) -> str:
    safe_label = _e(label or "원문")
    if not url:
        return safe_label
    safe_url = _e(url)
    return f"<a href='{safe_url}' target='_blank' rel='noreferrer'>{safe_label}</a>"


def _theme_for_company(company: str) -> dict:
    name = company or ""
    if any(key in name for key in ("농심", "삼양", "오뚜기", "CJ제일제당", "대상")):
        return {
            "sector": "Food & Consumer",
            "primary": "#D35400",
            "secondary": "#F4A261",
            "soft": "#FFF3E8",
            "ink": "#2D1B12",
            "pattern": "radial-gradient(circle at 82% 18%, rgba(244,162,97,.30), transparent 26%), linear-gradient(135deg,#fffaf5,#fff 48%,#fcefe3)",
        }
    if any(key in name for key in ("아모레", "LG생활건강", "에이피알", "코스맥스", "한국콜마")):
        return {
            "sector": "Beauty & Personal Care",
            "primary": "#9D4EDD",
            "secondary": "#F15BB5",
            "soft": "#F8EEFF",
            "ink": "#24112F",
            "pattern": "radial-gradient(circle at 82% 18%, rgba(241,91,181,.24), transparent 28%), linear-gradient(135deg,#fff7fb,#fff 48%,#f3e8ff)",
        }
    if any(key in name for key in ("제너셈", "한미반도체", "리노공업", "이오테크닉스", "삼성전자", "SK하이닉스")):
        return {
            "sector": "Semiconductor Equipment",
            "primary": "#C40000",
            "secondary": "#F97316",
            "soft": "#FFF1F1",
            "ink": "#250A0A",
            "pattern": "radial-gradient(circle at 82% 18%, rgba(196,0,0,.18), transparent 27%), linear-gradient(135deg,#fff,#fff 48%,#fff1f1)",
        }
    return {
        "sector": "Equity Research",
        "primary": "#1D4E89",
        "secondary": "#2A9D8F",
        "soft": "#EEF6FF",
        "ink": "#0F2238",
        "pattern": "radial-gradient(circle at 82% 18%, rgba(42,157,143,.22), transparent 27%), linear-gradient(135deg,#f8fbff,#fff 48%,#eef6ff)",
    }


def _toc(items: list[tuple[str, str]]) -> str:
    return "".join(f"<a href='#{_e(anchor)}'>{_e(label)}</a>" for anchor, label in items)


def _mini_card(label: str, value: str, note: str) -> str:
    return f"<div class='mini'><span>{_e(label)}</span><b>{_e(value)}</b><p>{_e(note)}</p></div>"


def _earnings_briefing(latest, tracker_commentary: list[dict] | None, thesis: dict) -> dict:
    revenue_yoy = _num(latest.get("revenue_yoy"))
    opm = _num(latest.get("opm"))
    opm_yoy = _num(latest.get("opm_yoy_pp"))
    fcf_margin = _num(latest.get("fcf_margin"))
    cfo_margin = _num(latest.get("cfo_margin"))
    bullets = [
        f"매출은 YoY {_f(revenue_yoy, '%')}로 외형 방향을 확인했습니다.",
        f"영업이익률은 {_f(opm, '%')}이며 YoY {_f(opm_yoy, '%p')}입니다. 매출 증가가 이익으로 얼마나 내려왔는지가 이번 분기의 1차 질문입니다.",
        f"현금흐름은 CFO 마진 {_f(cfo_margin, '%')}, FCF 마진 {_f(fcf_margin, '%')}입니다. 이익의 질은 손익계산서보다 현금 전환에서 다시 확인해야 합니다.",
    ]
    for card in (tracker_commentary or [])[:2]:
        read = card.get("read")
        action = card.get("action") or card.get("so_what")
        if read:
            bullets.append(f"{card.get('title','핵심 변화')}: {read}")
        if action:
            bullets.append(f"모델 반영: {action}")
    summary = thesis.get("summary") or ""
    if not summary:
        if revenue_yoy is not None and opm_yoy is not None and revenue_yoy > 0 and opm_yoy >= 0:
            summary = "이번 분기는 외형과 수익성이 같은 방향으로 움직였습니다. 숫자 자체는 긍정적이지만, 주가가 따라오지 않았다면 원인은 실적보다 기대치 선반영·수급·외부 변수에서 찾아야 합니다."
        elif revenue_yoy is not None and opm_yoy is not None and revenue_yoy > 0 and opm_yoy < 0:
            summary = "외형은 성장했지만 수익성이 약해진 분기입니다. 매출 성장률을 DCF에 곧장 반영하기보다 원가율·판관비율·현금 전환율이 정상화되는지를 먼저 확인해야 합니다."
        else:
            summary = "이번 분기는 단일 숫자만으로 방향을 확정하기 어렵습니다. 매출, 마진, 현금흐름, 수급이 같은 방향으로 모이는지 확인하는 구간입니다."
    return {"bullets": bullets[:6], "summary": summary}


def _external_market_brief(company: str, market_context: dict | None, thesis: dict) -> dict:
    context = market_context or {}
    market = context.get("market") or {}
    drivers = context.get("external_drivers") or {}
    flows = drivers.get("flows") or {}
    macro = drivers.get("macro") or {}
    rows: list[list[str]] = []

    if market:
        signal = []
        for key, label in (("return_1m", "1개월"), ("return_3m", "3개월"), ("drawdown_52w_high", "52주 고점 대비")):
            value = _num(market.get(key))
            if value is not None:
                signal.append(f"{label} {_f(value, '%')}")
        rows.append([
            "시장 가격",
            " / ".join(signal) or "가격 데이터 연결",
            "실적과 주가 반응이 갈라졌는지 확인하는 1차 신호입니다.",
            "멀티플 할인 / 리레이팅 시점",
        ])
    if flows:
        if flows.get("connected"):
            signal = f"20일 누적 외국인 {_f(_num(flows.get('foreign_20d_eok')), '억', 0)}, 기관 {_f(_num(flows.get('institution_20d_eok')), '억', 0)}"
        else:
            signal = flows.get("reason") or "KRX 수급 연결 대기"
        rows.append([
            "수급",
            signal,
            "실적이 좋아도 매도 압력이 남아 있으면 주가는 늦게 반응할 수 있습니다.",
            "목표 멀티플 / 진입 타이밍",
        ])
    fred_fx = macro.get("fred_usd_krw") or {}
    fred_wheat = macro.get("fred_wheat") or {}
    def _fred_signal(label, series, unit_digits):
        value = _f(_num(series.get("value")), "", unit_digits)
        chg = _num(series.get("change_3m_pct"))
        trend = f" (3M {chg:+.1f}%)" if chg is not None else ""
        return f"{label} {series.get('date','')}: {value}{trend}"

    if fred_fx:
        rows.append([
            "환율",
            _fred_signal("USD/KRW", fred_fx, 1),
            "해외 매출 환산과 원재료 수입비용을 동시에 흔드는 변수입니다. 상승 구간이면 원가율 압박으로 우선 읽습니다.",
            "매출 성장률 / 원가율",
        ])
    if fred_wheat:
        rows.append([
            "원재료 proxy",
            _fred_signal("Wheat", fred_wheat, 1),
            "식품·소비재 기업은 원가율 변동의 배경 후보로 우선 점검합니다. 3M 상승이면 마진 보수화 신호입니다.",
            "원가율 / OPM",
        ])
    for item in (thesis.get("context") or [])[:3]:
        matched = ", ".join(item.get("matched_keywords", [])[:3])
        context_read = item.get("summary") or (f"관련 키워드: {matched}" if matched else "제목 기준 참고 정황입니다.")
        rows.append([
            item.get("source", "외부 자료"),
            item.get("title", "")[:80],
            context_read,
            "가설 후보 / 원문 확인",
        ])

    if not rows:
        rows.append([
            "외부 변수",
            "연결된 실시간 정황 부족",
            "현재 리포트는 DART 숫자 중심으로 해석합니다. 뉴스·수급·원자재 API가 연결되면 이 구간이 자동 보강됩니다.",
            "근거 보강 대기",
        ])

    themes = []
    text_pool = " ".join(
        f"{item.get('title','')} {item.get('summary','')} {item.get('description','')}"
        for item in (thesis.get("context") or [])
    )
    for keyword, label in [
        ("환율", "환율"),
        ("원가", "원가"),
        ("수출", "해외 성장"),
        ("공장", "증설/가동률"),
        ("외국인", "외국인 수급"),
        ("국민연금", "대형 주주 수급"),
        ("반도체", "섹터 쏠림"),
        ("전쟁", "지정학/원자재"),
        ("유가", "유가"),
        ("대통령", "정책 테마"),
        ("스페이스X", "테마성 이벤트"),
    ]:
        if keyword in text_pool:
            themes.append(label)
    if flows.get("connected") and ((_num(flows.get("foreign_20d_eok")) or 0) < 0 or (_num(flows.get("institution_20d_eok")) or 0) < 0):
        themes.append("수급 부담")
    unique_themes = []
    for theme in themes:
        if theme not in unique_themes:
            unique_themes.append(theme)
    theme_text = ", ".join(unique_themes[:4])
    if theme_text:
        synthesis = f"현재 외부 변수는 {theme_text} 쪽을 우선 확인해야 합니다. 이 변수들은 실적의 방향을 바꾸기보다 시장이 적용하는 할인율·멀티플·진입 시점을 흔드는 요인으로 해석하는 편이 안전합니다."
    else:
        synthesis = f"{company}의 외부 변수는 아직 하나의 강한 테마로 수렴하지 않습니다. 따라서 이번 리포트에서는 DART 실적과 현금흐름을 1차 근거로 두고, 외부 자료는 원인 후보로만 사용합니다."
    return {"rows": rows[:7], "synthesis": synthesis}


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
        return ("비중확대", "여러 방식으로 추정한 적정가가 현재가를 뚜렷이 상회합니다.")
    if gap >= -10:
        return ("중립", "추정 적정가와 현재가의 괴리가 크지 않습니다.")
    return ("비중축소", "현재가가 추정 적정가를 상회합니다.")


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
    terminal_guidance: dict | None = None,
    market_context: dict | None = None,
    external_dcf_adjustments: list[dict] | None = None,
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
    earnings_brief = _earnings_briefing(latest, tracker_commentary, thesis)
    external_brief = _external_market_brief(company, market_context, thesis)

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
        "earnings_brief": earnings_brief,
        "external_brief": external_brief,
        "snapshot": snapshot,
        "valuation_rows": valuation_rows,
        "attribution": pa.get("attribution", []),
        "gap_reasons": gap_reasons,
        "decision_rows": decision_rows,
        "tracker_commentary": tracker_commentary or [],
        "interpreted": interpreted or [],
        "terminal_guidance": terminal_guidance or {},
        "external_dcf_adjustments": external_dcf_adjustments or [],
        "facts": thesis.get("facts", []),
        "hypotheses": thesis.get("hypotheses", []),
        "context_items": thesis.get("context", []),
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
            f"**기준 적정가는 현재가를 상회한다.** 여러 방식으로 본 기준 적정가 {_f(vr.get('mid'), '원', 0)}"
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
        ["기준 적정가", _f(cross_mid, "원", 0), _f(cross_gap, "%"), "DCF·PER·EV/EBITDA·리서치 참고값을 함께 본 중간값"],
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
    terminal_guidance: dict | None = None,
    market_context: dict | None = None,
    external_dcf_adjustments: list[dict] | None = None,
) -> str:
    m = build_report_model(
        company, kpis, dcf, price_action=price_action, interpreted=interpreted,
        structured=structured, valuation_range=valuation_range, capital=capital,
        research=research, thesis=thesis, tracker_commentary=tracker_commentary,
        terminal_guidance=terminal_guidance,
        market_context=market_context,
        external_dcf_adjustments=external_dcf_adjustments,
    )
    code = f" ({m['code']})" if m["code"] else ""
    lines: list[str] = [
        f"# {company}{code} — 투자 노트",
        "",
        f"**정량 투자의견: {m['rating']}**  ·  기준 적정가 {_f(m['target_mid'], '원', 0)}  ·  "
        f"현재가 {_f(m['current_price'], '원', 0)}  ·  상승여력 {_f(m['upside'], '%')}",
        "",
        "| 항목 | 내용 |",
        "|---|---|",
        _row("기준 분기", m["period"]),
        _row("생성일", m["gen_date"]),
        _row("DCF 주당가치", f"{_f(m['dcf_price'], '원', 0)} (현재가 대비 {_f(m['dcf_gap'], '%')})"),
        _row("적정가 범위", f"{_f(m['target_low'], '원', 0)} ~ {_f(m['target_high'], '원', 0)}"),
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
        lines.append(f"- 터미널가치 비중 {_f(m['terminal_share'], '%')} — 아래 보수 조합으로 DCF 상단을 눌러 본 뒤 사용")
    tv = m.get("terminal_guidance") or {}
    if tv.get("rows"):
        lines += [
            "",
            "**터미널가치 보수 점검 조합**",
            "",
            f"- {tv.get('diagnosis','')}",
            "",
            "| 시나리오 | WACC | 영구성장률 | WACC-g | 5년차 성장률 | 5년차 OPM | 주당가치 | 현재가 대비 | 사용법 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for row in tv["rows"]:
            lines.append(_row(
                row.get("case", ""),
                _f(row.get("wacc"), "%", 2),
                _f(row.get("perpetual_growth"), "%"),
                _f(row.get("spread"), "%p", 2),
                _f(row.get("terminal_revenue_growth"), "%"),
                _f(row.get("terminal_opm"), "%"),
                _f(row.get("implied_price"), "원", 0),
                _f(row.get("upside"), "%"),
                row.get("action", ""),
            ))
        lines += ["", f"- 판단 기준: {tv.get('decision_rule','')}", ""]
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
        lines.append("**적정가와 현재가가 벌어진 이유**")
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
        "‘정량 투자의견’은 추정 적정가와 현재가의 괴리에서 기계적으로 도출한 참고치로 공식 투자의견이 아닙니다. "
        "투자 판단은 다음 분기 확인되는 실적과 수급을 함께 보아야 합니다._",
    ]
    return "\n".join(lines)


def generate_analysis_html_report(
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
    terminal_guidance: dict | None = None,
    market_context: dict | None = None,
    external_dcf_adjustments: list[dict] | None = None,
) -> str:
    """A browser-friendly investment note. This is the user-facing downloadable report."""
    m = build_report_model(
        company, kpis, dcf, price_action=price_action, interpreted=interpreted,
        structured=structured, valuation_range=valuation_range, capital=capital,
        research=research, thesis=thesis, tracker_commentary=tracker_commentary,
        terminal_guidance=terminal_guidance,
        market_context=market_context,
        external_dcf_adjustments=external_dcf_adjustments,
    )
    code = f" · {m['code']}" if m.get("code") else ""
    summary = "".join(f"<li>{_inline(p)}</li>" for p in m["summary_points"])
    earnings_brief = m.get("earnings_brief") or {}
    earnings_brief_html = (
        f"<div class='brief-box'><p>{_e(earnings_brief.get('summary',''))}</p>"
        + "<ul>"
        + "".join(f"<li>{_e(item)}</li>" for item in earnings_brief.get("bullets", [])[:6])
        + "</ul></div>"
    )
    external_brief = m.get("external_brief") or {}
    external_brief_table = _html_table(
        ["외부 변수", "현재 신호", "해석", "모델 연결"],
        external_brief.get("rows", []),
    ) if external_brief.get("rows") else ""
    external_dcf_table = ""
    if m.get("external_dcf_adjustments"):
        external_dcf_table = _html_table(
            ["외부 변수", "현재 신호", "DCF 반영", "조정 전", "조정 후", "해석", "신뢰도"],
            [
                [
                    row.get("외부 변수", ""),
                    row.get("현재 신호", ""),
                    row.get("DCF 반영", ""),
                    _f(row.get("조정 전"), ""),
                    _f(row.get("조정 후"), ""),
                    row.get("해석", ""),
                    row.get("신뢰도", ""),
                ]
                for row in m["external_dcf_adjustments"]
            ],
        )
    tracker = "".join(
        f"<li><strong>{_e(card.get('title'))}</strong><span>{_e(card.get('read'))}</span></li>"
        for card in m.get("tracker_commentary", [])[:3]
    )
    valuation_table = _html_table(["방법", "주당가치", "현재가 대비", "비고"], m["valuation_rows"])
    snapshot_table = _html_table(["지표", "값", "변화", "코멘트"], m["snapshot"])
    decision_table = _html_table(["확인할 것", "확인되면", "확인 안 되면", "가정 조정"], m["decision_rows"]) if m["decision_rows"] else ""
    facts_table = ""
    if m.get("facts"):
        facts_table = _html_table(
            ["확인된 사실", "현재 값", "해석", "근거"],
            [
                [
                    f.get("label", ""),
                    f.get("value", ""),
                    f.get("interpretation", ""),
                    f"{f.get('source','')} · {f.get('confidence','')}",
                ]
                for f in m["facts"][:6]
            ],
        )
    hypothesis_cards = ""
    if m.get("hypotheses"):
        hypothesis_cards = "".join(
            "<div class='hypo'>"
            f"<div><b>{_e(h.get('title',''))}</b><span>{_e(h.get('confidence',''))}</span></div>"
            f"<p>{_e(h.get('explanation',''))}</p>"
            f"<em>So what · {_e(h.get('so_what','확인 전까지는 보조 가설로만 사용합니다.'))}</em>"
            "</div>"
            for h in m["hypotheses"][:4]
        )
    source_table = _source_table(m.get("context_items", [])[:6])
    attribution_table = ""
    if m["attribution"]:
        attribution_table = _html_table(
            ["변동요인", "강도", "해석", "근거"],
            [
                [
                    a.get("driver", ""),
                    a.get("weight", ""),
                    str(a.get("reading", "")).replace("\n", " "),
                    f"{a.get('evidence','')} ({a.get('evidence_level','')})",
                ]
                for a in m["attribution"]
            ],
        )
    gap_reasons = "".join(f"<li>{_inline(reason)}</li>" for reason in m["gap_reasons"])
    interpreted_items = ""
    if m["interpreted"]:
        rows = []
        for item in m["interpreted"]:
            I = item.get("interpretation", {})
            top = (I.get("cause_candidates") or [{}])[0]
            cause = f"[{top.get('evidence_level','')}] {top.get('cause','')}" if top.get("cause") else "근거 대기"
            rows.append([I.get("headline", item.get("label", "")), I.get("confidence", ""), cause])
        interpreted_items = _html_table(["이상신호", "신뢰도", "원인 후보"], rows)
    w = m.get("wacc") or {}
    wacc_line = ""
    if w:
        wacc_line = (
            f"WACC {_f(w.get('wacc'), '%', 2)} = Rf {_f(w.get('rf'), '%')} + "
            f"β {_f(w.get('beta'), '', 3)} × ERP {_f(w.get('erp'), '%')} → "
            f"Ke {_f(w.get('cost_equity'), '%')}"
        )
    opm_line = " → ".join(_f(v, "%") for v in m["opm_path"]) if m["opm_path"] else ""
    tv = m.get("terminal_guidance") or {}
    terminal_table = ""
    if tv.get("rows"):
        terminal_table = _html_table(
            ["시나리오", "WACC", "영구성장률", "WACC-g", "5년차 성장률", "5년차 OPM", "주당가치", "현재가 대비", "사용법"],
            [
                [
                    row.get("case", ""),
                    _f(row.get("wacc"), "%", 2),
                    _f(row.get("perpetual_growth"), "%"),
                    _f(row.get("spread"), "%p", 2),
                    _f(row.get("terminal_revenue_growth"), "%"),
                    _f(row.get("terminal_opm"), "%"),
                    _f(row.get("implied_price"), "원", 0),
                    _f(row.get("upside"), "%"),
                    row.get("action", ""),
                ]
                for row in tv["rows"]
            ],
        )
    theme = _theme_for_company(company)
    toc = _toc([
        ("summary", "요약"),
        ("briefing", "실적 브리핑"),
        ("external", "외부 변수"),
        ("logic", "논점 지도"),
        ("quality", "실적의 질"),
        ("valuation", "가치평가"),
        ("gap", "주가 괴리"),
        ("check", "체크포인트"),
    ])
    mini_cards = "".join([
        _mini_card("주가 위치", _f(m["current_price"], "원", 0), f"기준 적정가 대비 {_f(m['upside'], '%')}"),
        _mini_card("현금흐름", _f(kpis.iloc[-1].get("fcf_margin"), "%"), "이익이 실제 현금으로 남는지 확인"),
        _mini_card("가치 민감도", _f(m["terminal_share"], "%"), "터미널가치 비중이 높으면 할인율 변화에 민감"),
    ])
    html_doc = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(company)} 투자 메모</title>
  <style>
    :root {{--primary:{theme['primary']};--secondary:{theme['secondary']};--soft:{theme['soft']};--ink:{theme['ink']};}}
    body {{ margin:0; background:#f3f6fa; color:#17202a; font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Segoe UI",sans-serif; }}
    .page {{ max-width:980px; margin:34px auto; background:#fff; border:1px solid #dfe6ee; box-shadow:0 10px 28px rgba(15,34,56,.08); }}
    .cover {{ position:relative; overflow:hidden; padding:32px 34px 28px; background:{theme['pattern']}; border-bottom:3px solid var(--primary); }}
    .cover:after {{ content:""; position:absolute; right:-110px; bottom:-145px; width:420px; height:280px; background:linear-gradient(135deg,transparent 20%,rgba(0,0,0,.06),rgba(0,0,0,.18)); transform:rotate(-18deg); border-radius:36px; }}
    .topline {{ display:flex; justify-content:space-between; gap:20px; position:relative; z-index:1; }}
    .eyebrow {{ font-size:11px; letter-spacing:.16em; color:var(--primary); font-weight:800; text-transform:uppercase; }}
    h1 {{ margin:9px 0 6px; font-size:32px; letter-spacing:-.055em; line-height:1.08; color:var(--ink); }}
    .sector {{ color:var(--primary); font-weight:800; font-size:13px; margin-bottom:8px; }}
    .headline {{ max-width:710px; font-size:22px; font-weight:850; letter-spacing:-.045em; line-height:1.25; margin:16px 0 18px; color:#111827; }}
    .meta {{ color:#667085; font-size:12px; line-height:1.5; }}
    .rating {{ min-width:190px; text-align:right; }}
    .rating b {{ display:inline-block; color:var(--primary); background:#fff; border:1px solid #e6edf5; padding:7px 10px; border-radius:999px; font-size:13px; }}
    .rating p {{ margin:7px 0 0; font-size:11px; color:#667085; line-height:1.45; }}
    .toc {{ display:flex; flex-wrap:wrap; gap:8px; position:relative; z-index:2; margin-top:18px; }}
    .toc a {{ text-decoration:none; color:var(--primary); background:#fff; border:1px solid #e6edf5; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:750; }}
    .checkbox {{ position:relative; z-index:1; background:#fff; border:1px solid #dfe6ee; border-radius:10px; padding:15px 18px; max-width:830px; box-shadow:0 8px 20px rgba(16,24,40,.06); }}
    .check-title {{ display:inline-block; background:var(--secondary); color:#fff; font-weight:850; border-radius:999px; padding:5px 22px; margin-bottom:9px; }}
    .check-list {{ margin:0; padding-left:20px; }}
    .check-list li::marker {{ color:var(--secondary); }}
    .mini-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; position:relative; z-index:1; margin-top:14px; }}
    .mini {{ background:rgba(255,255,255,.92); border:1px solid #dfe6ee; border-radius:10px; padding:12px 13px; min-height:84px; }}
    .mini span {{ display:block; color:#667085; font-size:11px; margin-bottom:5px; }}
    .mini b {{ color:var(--primary); font-size:18px; letter-spacing:-.03em; }}
    .mini p {{ margin:6px 0 0; color:#475467; font-size:12px; line-height:1.4; }}
    .body {{ padding:26px 34px 34px; }}
    .two-col {{ display:grid; grid-template-columns:1.05fr .95fr; gap:14px; align-items:start; }}
    .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:22px; }}
    .kpi {{ border:1px solid #e2e8f0; border-top:3px solid var(--primary); padding:11px 12px; border-radius:7px; background:#fbfcfe; }}
    .kpi span {{ display:block; color:#667085; font-size:11px; margin-bottom:4px; }}
    .kpi b {{ font-size:17px; letter-spacing:-.02em; }}
    .verdict {{ border-left:4px solid var(--primary); background:var(--soft); padding:13px 15px; margin:0 0 24px; }}
    .verdict span {{ display:block; color:#667085; font-size:11px; margin-bottom:4px; }}
    .verdict b {{ color:var(--ink); font-size:15px; }}
    .brief-box {{ border:1px solid #dfe6ee; border-radius:10px; padding:14px 16px; background:#fbfcfe; margin:10px 0 16px; }}
    .brief-box p {{ margin:0 0 10px; line-height:1.72; color:#243447; }}
    .brief-box ul {{ margin:0; }}
    h2 {{ font-size:16px; color:var(--primary); letter-spacing:-.02em; margin:26px 0 8px; padding-top:2px; }}
    .sub {{ color:#667085; font-size:12px; margin:-3px 0 10px; }}
    ul {{ padding-left:19px; margin-top:8px; }}
    li {{ margin:7px 0; line-height:1.65; }}
    li span {{ display:block; margin-top:2px; color:#344054; }}
    table {{ width:100%; border-collapse:collapse; margin:10px 0 16px; font-size:13px; }}
    th {{ background:var(--ink); color:#fff; text-align:left; padding:9px 10px; font-size:12px; }}
    td {{ border-bottom:1px solid #e8eef5; padding:9px 10px; vertical-align:top; line-height:1.45; }}
    tr:nth-child(even) td {{ background:#fbfcfe; }}
    .hypo {{ border:1px solid #e2e8f0; border-left:3px solid var(--primary); border-radius:8px; padding:11px 12px; margin:0 0 9px; background:#fff; }}
    .hypo div {{ display:flex; justify-content:space-between; gap:10px; align-items:center; }}
    .hypo b {{ color:#111827; font-size:13px; }}
    .hypo span {{ color:var(--primary); background:var(--soft); border-radius:999px; padding:3px 8px; font-size:11px; font-weight:800; }}
    .hypo p {{ margin:7px 0; color:#344054; line-height:1.55; font-size:12px; }}
    .hypo em {{ display:block; color:#475467; font-style:normal; font-size:12px; line-height:1.5; }}
    a {{ color:var(--primary); text-decoration:none; font-weight:750; }}
    .note {{ color:#344054; line-height:1.7; margin:9px 0 15px; }}
    .small {{ font-size:12px; color:#667085; line-height:1.6; }}
    .foot {{ margin-top:28px; padding-top:14px; border-top:1px solid #e2e8f0; font-size:11px; color:#667085; line-height:1.6; }}
    @media (max-width:760px) {{ .page{{margin:0;border:none}} .topline{{display:block}} .rating{{text-align:left;margin-top:12px}} .mini-grid,.kpis,.two-col{{grid-template-columns:1fr}} h1{{font-size:27px}} }}
    @media print {{ body {{ background:#fff; }} .page {{ margin:0; box-shadow:none; border:none; }} .toc{{display:none}} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="cover">
      <div class="topline">
        <div>
        <div class="eyebrow">FINSIGHT INVESTMENT NOTE</div>
        <div class="sector">{_e(theme['sector'])}</div>
        <h1>{_e(company)} 투자 메모</h1>
        <div class="meta">{_e(m['period'])} 기준{_e(code)} · 생성 {_e(m['gen_date'])}<br>DART 재무·공시 / 시세 / 리서치 참고자료 기반</div>
        </div>
        <div class="rating">
          <b>정량 의견 · {_e(m['rating'])}</b>
          <p>{_e(m['rating_note'])}</p>
        </div>
      </div>
      <div class="headline">{_e(m['verdict'])}</div>
      <div class="checkbox">
        <div class="check-title">체크포인트</div>
        <ul class="check-list">{summary}</ul>
      </div>
      <div class="mini-grid">{mini_cards}</div>
      <nav class="toc">{toc}</nav>
    </header>
    <section class="body">
      <div class="kpis">
        <div class="kpi"><span>현재가</span><b>{_f(m['current_price'], '원', 0)}</b></div>
        <div class="kpi"><span>기준 적정가</span><b>{_f(m['target_mid'], '원', 0)}</b></div>
        <div class="kpi"><span>상승여력</span><b>{_f(m['upside'], '%')}</b></div>
        <div class="kpi"><span>DCF 주당가치</span><b>{_f(m['dcf_price'], '원', 0)}</b></div>
      </div>
      <div class="verdict"><span>해석 요약</span><b>{_e(m['verdict'])}</b></div>
      <h2 id="summary">1. 요약</h2>
      <ul>{summary}</ul>
      <h2 id="briefing">2. 이번 실적 브리핑</h2>
      <div class="sub">숫자 변화의 핵심과 이번 분기의 투자 해석을 먼저 정리합니다.</div>
      {earnings_brief_html}
      <h2 id="external">3. 외부 변수와 시장 맥락</h2>
      <div class="sub">뉴스·수급·매크로는 확정 사실이 아니라 DART 숫자를 설명하는 보조 가설로 사용합니다.</div>
      <p class="note">{_e(external_brief.get('synthesis',''))}</p>
      {external_brief_table}
      <h2 id="logic">4. 논점 지도</h2>
      <div class="sub">확인된 사실과 아직 검증 중인 가설을 분리합니다.</div>
      <div class="two-col">
        <div>{facts_table}</div>
        <div>{hypothesis_cards}</div>
      </div>
      <h2 id="quality">5. 실적의 질</h2>
      <div class="sub">좋은 숫자인지, 좋아 보이는 숫자인지를 구분합니다.</div>
      {snapshot_table}
      <p class="note">{_e(m['thesis'])}</p>
      {f"<ul>{tracker}</ul>" if tracker else ""}
      <h2 id="valuation">6. 가치평가</h2>
      <div class="sub">하나의 목표가보다 여러 방식으로 계산한 범위를 보는 쪽이 안전합니다.</div>
      {valuation_table}
      <p class="small">{_e(wacc_line)}</p>
      {f"<p class='small'>OPM 경로: {_e(opm_line)}</p>" if opm_line else ""}
      {f"<h2>6-1. 외부 변수 DCF 반영</h2><div class='sub'>외부 변수는 확정 실적이 아니므로 보수적인 조정 레이어로만 반영했습니다.</div>{external_dcf_table}" if external_dcf_table else ""}
      {f"<p class='small'>터미널가치 비중 {_f(m['terminal_share'], '%')} — 기준값을 그대로 믿기보다 아래 보수 조합으로 한 번 눌러 본 뒤 사용</p>" if m['terminal_share'] is not None else ""}
      {f"<div class='verdict'><span>터미널가치 점검</span><b>{_e(tv.get('headline',''))}</b><p class='small'>{_e(tv.get('diagnosis',''))}</p></div>{terminal_table}<p class='small'>{_e(tv.get('decision_rule',''))}</p>" if terminal_table else ""}
      <h2 id="gap">7. 주가 괴리</h2>
      <div class="sub">왜 적정가와 현재가가 다르게 움직이는지에 대한 해석입니다.</div>
      {attribution_table}
      <ul>{gap_reasons}</ul>
      {f"<h2>8. 외부 자료 후보</h2><div class='sub'>원문 확인 전에는 확정 사실이 아니라 원인 후보로만 사용합니다.</div>{source_table}" if source_table else ""}
      <h2 id="check">9. 체크포인트</h2>
      <div class="sub">다음 분기에 확인되면 무엇을 바꾸고, 아니면 무엇을 보수적으로 둘지 정리했습니다.</div>
      {decision_table}
      {f"<h2>10. 우선 검토 이상신호</h2>{interpreted_items}" if interpreted_items else ""}
      <div class="foot">
        본 자료는 FinSight가 DART 재무 패턴과 공시·뉴스·리서치 참고자료를 함께 검토해 만든 참고용 리포트입니다.
        정량 의견은 추정 적정가와 현재가의 괴리에서 기계적으로 도출한 참고치이며 공식 투자의견이 아닙니다.
      </div>
    </section>
  </main>
</body>
</html>"""
    return html_doc


generate_business_report = generate_analysis_summary
generate_analyst_report = generate_analysis_summary
generate_executive_brief = generate_analysis_summary
