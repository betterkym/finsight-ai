"""Downloadable retail-facing report for the report reliability validator."""
from __future__ import annotations

import datetime as dt
import html
import math
from pathlib import Path

import pandas as pd

from report_validator.evidence_audit import (
    build_scoring_rulebook,
    build_score_audit,
    build_source_audit,
    build_update_audit,
    score_formula,
)


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _f(value, suffix: str = "", digits: int = 1) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.{digits}f}{suffix}"


def _won(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.0f}원"


def _int_text(value, suffix: str = "") -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.0f}{suffix}"


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _cash_pressure_read(kpis: pd.DataFrame) -> str:
    if kpis is None or kpis.empty:
        return "원인 후보를 계산할 재무 데이터가 부족합니다."
    latest = kpis.iloc[-1]
    revenue_yoy = _num(latest.get("revenue_yoy")) or 0
    receivables_yoy = _num(latest.get("receivables_yoy"))
    inventory_yoy = _num(latest.get("inventory_yoy"))
    capex_ratio = _num(latest.get("capex_ratio"))
    capex_med = None
    if "capex_ratio" in kpis:
        hist = pd.to_numeric(kpis["capex_ratio"], errors="coerce").dropna().tail(8)
        capex_med = float(hist.median()) if not hist.empty else None

    drivers: list[str] = []
    if receivables_yoy is not None and receivables_yoy > revenue_yoy + 10:
        drivers.append(f"매출채권 증가율({_f(receivables_yoy, '%')})이 매출 성장률({_f(revenue_yoy, '%')})보다 높습니다")
    if inventory_yoy is not None and inventory_yoy > revenue_yoy + 10:
        drivers.append(f"재고 증가율({_f(inventory_yoy, '%')})이 매출 성장률({_f(revenue_yoy, '%')})보다 높습니다")
    if capex_ratio is not None and (capex_ratio > 8 or (capex_med is not None and capex_ratio > capex_med * 1.35)):
        text = f"CAPEX/매출이 {_f(capex_ratio, '%')}"
        if capex_med is not None:
            text += f"(최근 중앙값 {_f(capex_med, '%')})"
        drivers.append(text)
    if not drivers:
        return "운전자본·CAPEX 중 단일 원인이 강하게 잡히지는 않습니다."
    return " / ".join(drivers)


def _latest_read(kpis: pd.DataFrame) -> list[dict]:
    if kpis is None or kpis.empty:
        return []
    latest = kpis.iloc[-1]
    rows: list[dict] = []
    revenue_yoy = _num(latest.get("revenue_yoy"))
    opm = _num(latest.get("opm"))
    opm_yoy = _num(latest.get("opm_yoy_pp"))
    cfo_margin = _num(latest.get("cfo_margin"))
    fcf_margin = _num(latest.get("fcf_margin"))
    cogs_yoy = _num(latest.get("cogs_ratio_yoy_pp"))
    sga_yoy = _num(latest.get("sga_ratio_yoy_pp"))
    capex_ratio = _num(latest.get("capex_ratio"))
    receivables_yoy = _num(latest.get("receivables_yoy"))
    inventory_yoy = _num(latest.get("inventory_yoy"))

    if revenue_yoy is not None and opm_yoy is not None:
        if revenue_yoy > 0 and opm_yoy >= 0:
            rows.append({
                "title": "실적 방향",
                "verdict": "외형과 마진이 같은 방향",
                "read": "매출과 수익성이 함께 개선된 구간입니다. 다만 목표가를 정당화하려면 이 흐름이 다음 분기에도 이어져야 합니다.",
                "evidence": f"매출 YoY {_f(revenue_yoy, '%')}, OPM {_f(opm, '%')}, OPM YoY {_f(opm_yoy, '%p')}",
            })
        elif revenue_yoy > 0 and opm_yoy < 0:
            pressure = []
            if cogs_yoy is not None and cogs_yoy > 0:
                pressure.append(f"원가율 YoY {_f(cogs_yoy, '%p')}")
            if sga_yoy is not None and sga_yoy > 0:
                pressure.append(f"판관비율 YoY {_f(sga_yoy, '%p')}")
            rows.append({
                "title": "실적 방향",
                "verdict": "매출 증가가 이익으로 충분히 내려오지 않음",
                "read": "매출 성장만으로 목표가를 인정하면 과대평가될 수 있습니다. 원가율·판관비율 부담이 리포트 신뢰도 차감 근거입니다.",
                "evidence": " · ".join(pressure) or f"매출 YoY {_f(revenue_yoy, '%')}, OPM YoY {_f(opm_yoy, '%p')}",
            })
        else:
            rows.append({
                "title": "실적 방향",
                "verdict": "확인 구간",
                "read": "매출과 마진 신호가 뚜렷하게 한 방향으로 모이지 않습니다. 목표가보다 다음 실적 확인이 먼저입니다.",
                "evidence": f"매출 YoY {_f(revenue_yoy, '%')}, OPM YoY {_f(opm_yoy, '%p')}",
            })

    if cfo_margin is not None or fcf_margin is not None:
        if (fcf_margin or 0) < 0:
            read = "손익이 좋아 보여도 FCF(잉여현금흐름)가 남지 않는 구간입니다. 투자비나 운전자본 부담이 목표가 신뢰도를 낮출 수 있습니다."
            verdict = "현금 전환 확인 필요"
        else:
            read = "현금흐름이 크게 훼손된 신호는 제한적입니다. 목표가 검증에서는 성장률 가정의 현실성이 더 중요합니다."
            verdict = "현금흐름 큰 훼손 제한"
        rows.append({
            "title": "현금흐름",
            "verdict": verdict,
            "read": f"{read} 원인 후보는 {_cash_pressure_read(kpis)}.",
            "evidence": (
                f"CFO 마진 {_f(cfo_margin, '%')}, FCF(잉여현금흐름) 마진 {_f(fcf_margin, '%')}, "
                f"CAPEX/매출 {_f(capex_ratio, '%')}, 매출채권 YoY {_f(receivables_yoy, '%')}, 재고 YoY {_f(inventory_yoy, '%')}"
            ),
        })
    return rows[:3]


def _price_gap_read(analysis: dict) -> list[dict]:
    price_action = analysis.get("price_action") or {}
    rows: list[dict] = []
    verdict = price_action.get("verdict")
    thesis = price_action.get("thesis")
    if verdict or thesis:
        rows.append({
            "title": "주가 괴리",
            "verdict": verdict or "확인 구간",
            "read": thesis or "실적, 기대치, 수급 중 어느 축이 주가 차이를 만드는지 분해했습니다.",
            "evidence": "FinSight 주가·수급 해석",
        })
    for item in price_action.get("attribution", [])[:4]:
        rows.append({
            "title": item.get("driver", "요인"),
            "verdict": item.get("weight", ""),
            "read": item.get("reading", ""),
            "evidence": item.get("evidence", ""),
        })
    return rows[:5]


def _issue_read(analysis: dict) -> list[dict]:
    timeline = analysis.get("timeline", {})
    events = timeline.get("events", []) or []
    rows: list[dict] = []
    if events:
        for item in events[:4]:
            rows.append({
                "title": item.get("type", "발행 후 공시·뉴스"),
                "verdict": item.get("date", ""),
                "read": item.get("detail", ""),
                "evidence": "리포트 발행 이후 확인 항목",
            })
    if timeline.get("supply_gap"):
        rows.append({
            "title": "수급",
            "verdict": "리포트 의견과 반대 방향",
            "read": timeline.get("supply_read") or "매수 의견 이후 외국인 순매도가 누적됐습니다. 실적이 좋아도 주가 반영이 늦어질 수 있는 신호입니다.",
            "evidence": timeline.get("supply_basis") or f"외국인 {_int_text(timeline.get('foreign_net'), '억원')}",
        })
    return rows[:5]


def _first_nonempty(*values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _short(text: str, limit: int = 190) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _score_stance(total: int | float) -> tuple[str, str]:
    if total >= 75:
        return "긍정 유지", "리포트 방향은 현재 데이터와 큰 충돌이 없습니다. 목표가 근거가 숫자로도 어느 정도 받쳐지는 구간입니다."
    if total >= 60:
        return "조건부 참고", "리포트 방향은 참고할 수 있지만 목표가 전체를 그대로 받아들이기에는 확인할 전제가 남아 있습니다."
    if total >= 45:
        return "보수적 검토", "리포트의 핵심 전제 중 일부가 현재 데이터와 어긋납니다. 목표가보다 전제의 회복 여부를 먼저 봐야 합니다."
    return "신뢰도 낮음", "현재 확인되는 숫자와 발행 이후 흐름만 보면 리포트 결론을 그대로 쓰기 어렵습니다."


def _opinion_distribution(reports: list[dict]) -> str:
    counts: dict[str, int] = {}
    for item in reports:
        opinion = item.get("opinion")
        if opinion:
            counts[opinion] = counts.get(opinion, 0) + 1
    return " · ".join(f"{key} {value}개" for key, value in counts.items()) or "확인된 투자의견 없음"


def _broker_rows(analysis: dict) -> list[dict]:
    reports = analysis.get("report_batch") or []
    consensus_mean = (analysis.get("consensus") or {}).get("price_target_mean")
    current_price = (analysis.get("company") or {}).get("current_price")
    rows = []
    for item in reports:
        target = _num(item.get("target_price"))
        if target is None:
            continue
        gap = (target / consensus_mean - 1) * 100 if consensus_mean else None
        upside = (target / current_price - 1) * 100 if current_price else None
        rows.append({
            "증권사": item.get("broker") or "확인 필요",
            "발행일": item.get("pub_date") or "확인 필요",
            "투자의견": item.get("opinion") or "확인 필요",
            "목표가": _won(target),
            "현재가 대비": _f(upside, "%"),
            "평균 대비": _f(gap, "%"),
            "읽는 법": (
                "평균보다 공격적" if gap is not None and gap >= 15
                else "평균보다 보수적" if gap is not None and gap <= -15
                else "평균권"
            ),
        })
    return rows[:8]


def _broker_summary(analysis: dict) -> str:
    reports = analysis.get("report_batch") or []
    targets = sorted(_num(item.get("target_price")) for item in reports if _num(item.get("target_price")) is not None)
    if not reports:
        return "업로드된 리포트가 없거나 본문을 읽지 못해 증권사별 비교는 제한됩니다."
    if not targets:
        return f"업로드 리포트 {len(reports)}개 중 목표가를 안정적으로 읽은 리포트가 없어 목표가 분포 비교는 제한됩니다."
    median = targets[len(targets) // 2] if len(targets) % 2 else (targets[len(targets) // 2 - 1] + targets[len(targets) // 2]) / 2
    summary = (
        f"업로드 리포트 {len(reports)}개 중 목표가 {len(targets)}개를 읽었습니다. "
        f"목표가 범위는 {_won(targets[0])}~{_won(targets[-1])}, 중앙값은 {_won(median)}입니다. "
        f"투자의견 분포는 {_opinion_distribution(reports)}입니다."
    )
    batch = (analysis.get("report_batch_timeline") or {}).get("summary") or {}
    if batch.get("best_broker"):
        score = batch.get("best_score")
        score_text = f"({score:.0f}점)" if score is not None else ""
        summary += f" 발행 이후 흐름까지 보면 {batch['best_broker']} 리포트가 현재 데이터와 가장 덜 어긋납니다{score_text}."
    return summary


def _trusted_titles(briefing: dict, key: str) -> str:
    items = briefing.get(key) or []
    return ", ".join(item.get("title", "") for item in items[:3] if item.get("title")) or "해당 없음"


def _watchpoint_rows(model: dict) -> list[dict]:
    report_content = model.get("report_content") or {}
    briefing = report_content.get("briefing") or {}
    rows = []
    for item in briefing.get("watch") or []:
        rows.append({
            "항목": item.get("title") or "보수적 확인",
            "왜 중요한가": item.get("read") or item.get("evidence") or "",
            "확인할 변화": "이 전제가 숫자나 공시로 확인되기 전까지 목표가 신뢰도에는 할인 적용",
        })
    for item in model.get("issue_reads") or []:
        title = item.get("title") or "발행 후 이슈"
        if "수급" in title:
            check = "외국인 매도 중단 또는 순매수 전환, 최근 5거래일 매도 강도 둔화, 발행일 이후 주가 하락분 일부 회복"
        else:
            check = item.get("evidence") or "발행 이후 새 공시·뉴스·수급 변화"
        rows.append({
            "항목": title,
            "왜 중요한가": item.get("read") or "",
            "확인할 변화": check,
        })
    for item in (model.get("verdict") or {}).get("alignment", {}).get("factors", [])[:3]:
        rows.append({
            "항목": item.get("title") or "객관분석 차감",
            "왜 중요한가": item.get("reason") or "",
            "확인할 변화": item.get("evidence") or "",
        })
    return rows[:6]


def _build_analyst_pack(analysis: dict, model: dict) -> dict:
    company = model["company"]
    report = model["report"]
    verdict = model["verdict"]
    dist = analysis.get("distribution") or {}
    timeline = analysis.get("timeline") or {}
    reverse = analysis.get("reverse") or {}
    briefing = (model.get("report_content") or {}).get("briefing") or {}
    total = int(verdict.get("total", 0))
    stance, stance_read = _score_stance(total)

    current_price = _num(company.get("current_price"))
    target = _num(report.get("target_price"))
    upside = (target / current_price - 1) * 100 if target and current_price else None
    dist_gap = dist.get("vs_median_pct")
    target_mean = dist.get("mean")

    key_numbers = [
        {"label": "신뢰도", "value": f"{total}/100", "read": f"{verdict.get('grade')}등급 · {stance}"},
        {"label": "현재가 대비 목표가", "value": _f(upside, "%"), "read": f"현재가 {_won(current_price)} / 목표가 {_won(target)}"},
        {"label": "증권사 평균 대비", "value": _f(dist_gap, "%"), "read": f"평균 목표가 {_won(target_mean)}"},
        {"label": "발행 후 주가", "value": _f(timeline.get("realized"), "%"), "read": f"발행 후 {timeline.get('elapsed')}일 · 남은 여력 {_f(timeline.get('remaining'), '%')}"},
        {"label": "필요 성장률", "value": _f(reverse.get("need_growth"), "%"), "read": f"과거 중앙값 {_f(reverse.get('median_growth'), '%')}와 비교"},
        {"label": "본문 검증", "value": _first_nonempty((model.get("report_content_assessment") or {}).get("label"), "확인"), "read": _trusted_titles(briefing, "trusted")},
    ]

    decision_points = [
        {
            "title": "목표가를 그대로 받아들여도 되는가",
            "read": (
                f"목표가는 현재가 대비 {_f(upside, '%')} 여력이 있고 증권사 평균 대비 {_f(dist_gap, '%')}입니다. "
                "평균에서 멀수록 리포트가 제시한 성장 전제가 실제 숫자로 더 강하게 확인돼야 합니다."
            ),
            "evidence": f"목표가 {_won(target)} / 평균 {_won(target_mean)} / 현재가 {_won(current_price)}",
        },
        {
            "title": "발행 이후 시장은 같은 방향으로 움직였는가",
            "read": timeline.get("supply_read") or (
                f"발행 후 주가는 {_f(timeline.get('realized'), '%')} 움직였습니다. "
                "수급·공시 변화가 제한적이면 목표가 검증은 실적 가정 중심으로 봅니다."
            ),
            "evidence": timeline.get("supply_basis") or f"발행 후 {timeline.get('elapsed')}일",
        },
        {
            "title": "목표가에 필요한 실적이 무리하지 않은가",
            "read": (
                f"목표가가 성립하려면 EPS 성장률이 {_f(reverse.get('need_growth'), '%')} 필요합니다. "
                f"과거 중앙값 {_f(reverse.get('median_growth'), '%')}와의 차이가 크면 목표가에는 할인율을 적용합니다."
            ),
            "evidence": f"필요 EPS {_won(reverse.get('need_eps'))} / 현재 EPS {_won(reverse.get('current_eps'))}",
        },
        {
            "title": "리포트 본문에서 실제로 가져갈 내용은 무엇인가",
            "read": briefing.get("headline") or (model.get("report_content") or {}).get("summary") or "PDF 본문 검증 결과가 제한적입니다.",
            "evidence": f"믿을 내용: {_trusted_titles(briefing, 'trusted')} / 보수적 내용: {_trusted_titles(briefing, 'watch')}",
        },
    ]

    return {
        "stance": stance,
        "stance_read": stance_read,
        "subtitle": (
            f"{company.get('name')} 리포트는 '{stance}' 관점입니다. "
            "목표가 숫자보다 그 목표가를 만드는 전제가 지금도 살아 있는지에 초점을 둡니다."
        ),
        "key_numbers": key_numbers,
        "decision_points": decision_points,
        "broker_summary": _broker_summary(analysis),
        "broker_rows": _broker_rows(analysis),
        "watchpoints": _watchpoint_rows(model),
    }


def build_retail_report_model(analysis: dict) -> dict:
    company = analysis["company"]
    report = analysis["report"]
    verdict = analysis["verdict"]
    dist = analysis["distribution"]
    timeline = analysis["timeline"]
    reverse = analysis["reverse"]

    weak = verdict.get("weakest", "")
    broker = report.get("broker") or "이 리포트"
    target = report.get("target_price", 0)
    target_text = _won(target)
    alignment = verdict.get("alignment") or {}
    lead = (alignment.get("factors") or [{}])[0]
    lead_title = lead.get("title") or weak or "추가 부담"
    if verdict.get("headline") and verdict.get("guide"):
        summary = f"{verdict.get('headline')} {verdict.get('guide')}"
    elif verdict["total"] >= 75:
        summary = f"{broker}의 목표가 {target_text}은 현재 데이터와 크게 충돌하지 않습니다. 다만 현재가 기준 가격 반영 정도는 함께 봐야 합니다."
    elif verdict["total"] >= 60:
        summary = f"{broker}의 목표가 {target_text}은 참고할 만하지만, {lead_title} 때문에 그대로 확신하기는 어렵습니다."
    elif verdict["total"] >= 45:
        summary = f"{broker}의 목표가 {target_text}은 결론보다 가정을 할인해서 봐야 합니다. FinSight 분석에서는 {lead_title}이 리포트 신뢰도를 낮췄습니다."
    else:
        summary = f"{broker}의 목표가 {target_text}은 지금 판단 근거로 그대로 쓰기 어렵습니다. {lead_title}이 충분히 반영되지 않은 것으로 보입니다."

    content_assessment = analysis.get("report_content_assessment") or {}
    if content_assessment.get("penalty") and "본문 의견" not in summary:
        summary += f" PDF 본문 의견 검증에서는 {content_assessment.get('reason')} 때문에 신뢰도 {content_assessment.get('penalty')}점이 추가 차감됐습니다."

    model = {
        "company": company,
        "report": report,
        "verdict": verdict,
        "summary": summary,
        "as_of": dt.date.today().isoformat(),
        "score_formula": score_formula(analysis),
        "score_rulebook": build_scoring_rulebook(analysis),
        "score_audit": build_score_audit(analysis),
        "source_audit": build_source_audit(analysis),
        "update_audit": build_update_audit(analysis),
        "axis_rows": [
            {
                "axis": "목표가 편차",
                "result": dist.get("position"),
                "read": f"증권사 목표가 평균 {_won(dist.get('mean'))} 대비 {_f(dist.get('vs_median_pct'), '%')}입니다.",
                "score": verdict["axes"]["space"],
            },
            {
                "axis": "발행 이후 괴리",
                "result": "수급 괴리" if timeline.get("supply_gap") else "큰 괴리 제한",
                "read": timeline.get("supply_read") or f"발행 {_int_text(timeline.get('elapsed'), '일')} 경과, 여력 {_f(timeline.get('soak_pct'), '%')} 소진입니다.",
                "score": verdict["axes"]["time"],
            },
            {
                "axis": "필요 실적",
                "result": reverse.get("verdict"),
                "read": f"필요 성장률 {_f(reverse.get('need_growth'), '%')} vs 과거 중앙값 {_f(reverse.get('median_growth'), '%')}입니다.",
                "score": verdict["axes"]["logic"],
            },
        ],
        "latest_reads": _latest_read(analysis.get("kpis")),
        "issue_reads": _issue_read(analysis),
        "price_reads": _price_gap_read(analysis),
        "report_content": analysis.get("report_content") or {},
        "report_content_assessment": content_assessment,
    }
    model["analyst_pack"] = _build_analyst_pack(analysis, model)
    return model


def generate_retail_html_report(analysis: dict) -> str:
    model = build_retail_report_model(analysis)
    company = model["company"]
    report = model["report"]
    verdict = model["verdict"]
    analyst = model.get("analyst_pack") or {}
    key_cards = "".join(
        f"<div class='key-card'><span>{_e(item.get('label'))}</span><b>{_e(item.get('value'))}</b><em>{_e(item.get('read'))}</em></div>"
        for item in analyst.get("key_numbers", [])
    )
    decision_items = "".join(
        f"<li><b>{_e(item.get('title'))}</b><p>{_e(item.get('read'))}</p><span>{_e(item.get('evidence'))}</span></li>"
        for item in analyst.get("decision_points", [])
    )
    broker_rows = "".join(
        "<tr>"
        f"<td>{_e(row.get('증권사'))}</td>"
        f"<td>{_e(row.get('발행일'))}</td>"
        f"<td>{_e(row.get('투자의견'))}</td>"
        f"<td>{_e(row.get('목표가'))}</td>"
        f"<td>{_e(row.get('현재가 대비'))}</td>"
        f"<td>{_e(row.get('평균 대비'))}</td>"
        f"<td>{_e(row.get('읽는 법'))}</td>"
        "</tr>"
        for row in analyst.get("broker_rows", [])
    )
    if not broker_rows:
        broker_rows = "<tr><td colspan='7'>비교 가능한 목표가·투자의견을 읽은 리포트가 아직 없습니다.</td></tr>"
    watchpoint_rows = "".join(
        "<tr>"
        f"<td>{_e(row.get('항목'))}</td>"
        f"<td>{_e(row.get('왜 중요한가'))}</td>"
        f"<td>{_e(row.get('확인할 변화'))}</td>"
        "</tr>"
        for row in analyst.get("watchpoints", [])
    )
    if not watchpoint_rows:
        watchpoint_rows = "<tr><td colspan='3'>현재 리포트 신뢰도를 크게 흔드는 추가 확인 항목은 제한적입니다.</td></tr>"
    axis_rows = "".join(
        "<tr>"
        f"<td>{_e(row['axis'])}</td>"
        f"<td>{_e(row['result'])}</td>"
        f"<td>{_e(row['read'])}</td>"
        f"<td>{_e('데이터 없음' if row['score'].get('uncounted') else str(row['score'].get('score')) + '/' + str(row['score'].get('max')))}</td>"
        "</tr>"
        for row in model["axis_rows"]
    )
    latest = "".join(
        f"<li><b>{_e(row['title'])} · {_e(row['verdict'])}</b><p>{_e(row['read'])}</p><span>{_e(row['evidence'])}</span></li>"
        for row in model["latest_reads"]
    ) or "<li><b>실적 해석</b><p>재무 데이터가 부족해 최신 분기 해석을 제한합니다.</p></li>"
    issues = "".join(
        f"<li><b>{_e(row['title'])} · {_e(row['verdict'])}</b><p>{_e(row['read'])}</p><span>{_e(row['evidence'])}</span></li>"
        for row in model["issue_reads"]
    ) or "<li><b>발행 후 공시·뉴스</b><p>현재 연결된 발행 후 공시·뉴스·지분 변동은 제한적입니다.</p></li>"
    price_reads = "".join(
        f"<li><b>{_e(row['title'])} · {_e(row['verdict'])}</b><p>{_e(row['read'])}</p><span>{_e(row['evidence'])}</span></li>"
        for row in model["price_reads"]
    ) or "<li><b>주가 괴리</b><p>현재 연결된 주가·수급 데이터에서는 별도 괴리 원인이 강하게 잡히지 않습니다.</p></li>"
    score_audit = "".join(
        "<tr>"
        f"<td>{_e(row['항목'])}</td>"
        f"<td>{_e(row['배점'])}</td>"
        f"<td>{_e(row['점수'])}</td>"
        f"<td>{_e(row['차감'])}</td>"
        f"<td>{_e(row['정량 근거'])}</td>"
        f"<td>{_e(row['판정 로직'])}</td>"
        "</tr>"
        for row in model["score_audit"]
    )
    score_rulebook = "".join(
        "<tr>"
        f"<td>{_e(row['구분'])}</td>"
        f"<td>{_e(row['배점'])}</td>"
        f"<td>{_e(row['비중 설명'])}</td>"
        f"<td>{_e(row['차감 기준'])}</td>"
        f"<td>{_e(row['현재 적용'])}</td>"
        "</tr>"
        for row in model["score_rulebook"]
    )
    content_rows = "".join(
        "<tr>"
        f"<td>{_e(row.get('논점'))}</td>"
        f"<td>{_e(row.get('언급 리포트'))}</td>"
        f"<td>{_e(row.get('리포트 간 차이'))}</td>"
        f"<td>{_e(row.get('FinSight 대조'))}</td>"
        f"<td>{_e(row.get('판정'))}</td>"
        "</tr>"
        for row in (model.get("report_content") or {}).get("theme_rows", [])
    )
    if not content_rows:
        content_rows = "<tr><td colspan='5'>PDF 본문을 읽지 못해 본문 의견 검증은 제외했습니다.</td></tr>"
    briefing = (model.get("report_content") or {}).get("briefing") or {}
    briefing_sections = []
    for title, key in (
        ("믿고 가져갈 내용", "trusted"),
        ("그대로 믿기 어려운 내용", "watch"),
        ("리포트끼리 갈리는 내용", "contested"),
    ):
        items = briefing.get(key) or []
        if not items:
            continue
        lis = "".join(
            f"<li><b>{_e(item.get('title'))}</b><p>{_e(item.get('read'))}</p><span>{_e(item.get('evidence'))}</span></li>"
            for item in items[:3]
        )
        briefing_sections.append(f"<h3>{_e(title)}</h3><ul>{lis}</ul>")
    briefing_html = ""
    if briefing.get("headline"):
        briefing_html = f"<div class='briefing'><p>{_e(briefing.get('headline'))}</p>{''.join(briefing_sections)}</div>"
    update_audit = "".join(
        "<tr>"
        f"<td>{_e(row['평가 구분'])}</td>"
        f"<td>{_e(row['항목'])}</td>"
        f"<td>{_e(row['판단'])}</td>"
        f"<td>{_e(row['근거'])}</td>"
        f"<td>{_e(row['점수 영향'])}</td>"
        "</tr>"
        for row in model["update_audit"]
    )
    source_audit = "".join(
        "<tr>"
        f"<td>{_e(row['자료'])}</td>"
        f"<td>{_e(row['출처'])}</td>"
        f"<td>{_e(row['확인값'])}</td>"
        f"<td>{_e(row['점수 연결'])}</td>"
        "</tr>"
        for row in model["source_audit"]
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>FinSight 리포트 점검 결과 - {_e(company['name'])}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; color:#17202A; margin:0; background:#F7F8FA; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 42px 34px 64px; background:#fff; min-height:100vh; }}
    .kicker {{ color:#5B6775; font-size:13px; font-weight:700; }}
    h1 {{ font-size:32px; margin:8px 0 4px; }}
    h2 {{ font-size:20px; margin-top:34px; border-top:1px solid #DCE2E8; padding-top:22px; }}
    .meta {{ color:#667085; margin-bottom:24px; }}
    .score {{ display:flex; align-items:end; gap:12px; margin:22px 0; }}
    .score b {{ font-size:54px; color:#173B57; line-height:1; }}
    .score span {{ font-size:20px; font-weight:800; }}
    .summary {{ background:#F3F6F9; border-left:4px solid #173B57; padding:16px 18px; line-height:1.7; }}
    .view-box {{ border:1px solid #D7E0EA; background:#FBFCFD; padding:18px 20px; margin:20px 0 18px; }}
    .view-box h2 {{ border:0; padding:0; margin:0 0 8px; font-size:22px; }}
    .view-box p {{ margin:6px 0; line-height:1.7; }}
    .key-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:16px 0 20px; }}
    .key-card {{ border:1px solid #E2E8F0; background:#fff; padding:12px 13px; min-height:88px; }}
    .key-card span {{ display:block; color:#667085; font-size:12px; font-weight:800; }}
    .key-card b {{ display:block; color:#173B57; font-size:23px; margin-top:4px; }}
    .key-card em {{ display:block; color:#52606D; font-size:12px; font-style:normal; line-height:1.45; margin-top:4px; }}
    .decision-list {{ padding-left:18px; margin-top:8px; }}
    .decision-list li {{ margin:14px 0; }}
    .decision-list b {{ color:#17202A; }}
    .broker-note {{ color:#334155; background:#F8FAFC; border-left:3px solid #173B57; padding:12px 14px; line-height:1.65; margin:10px 0; }}
    .briefing {{ background:#FAFBFC; border:1px solid #DCE2E8; padding:14px 16px; margin:12px 0 14px; }}
    .briefing h3 {{ font-size:15px; margin:14px 0 4px; }}
    .briefing p {{ line-height:1.65; margin:0 0 8px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    th, td {{ border-bottom:1px solid #E5EAF0; padding:11px 9px; text-align:left; vertical-align:top; font-size:14px; }}
    th {{ background:#F8FAFC; color:#364152; }}
    ul {{ padding-left:18px; }}
    li {{ margin:13px 0; }}
    li p {{ margin:5px 0; line-height:1.65; }}
    li span {{ color:#667085; font-size:13px; }}
    footer {{ margin-top:42px; color:#667085; font-size:12px; line-height:1.6; }}
  </style>
</head>
<body>
<main>
  <div class="kicker">FinSight 리포트 점검 결과</div>
  <h1>{_e(company['name'])} 목표가 검증</h1>
  <div class="meta">{_e(report.get('broker') or '증권사 미입력')} · 발행일 {_e(report.get('pub_date'))} · 목표가 {_e(_won(report.get('target_price')))} · 생성일 {model['as_of']}</div>
  <div class="score"><b>{verdict['total']}</b><span>/100 · {verdict['grade']}등급</span></div>
  <div class="summary">{_e(model['summary'])}</div>

  <section class="view-box">
    <h2>한눈에 보는 점검 결과</h2>
    <p><b>{_e(analyst.get('stance'))}</b> — {_e(analyst.get('stance_read'))}</p>
    <p>{_e(analyst.get('subtitle'))}</p>
  </section>

  <div class="key-grid">{key_cards}</div>

  <h2>1. 이 리포트를 지금 어떻게 볼까</h2>
  <ul class="decision-list">{decision_items}</ul>

  <h2>2. 증권사 리포트 간 차이</h2>
  <div class="broker-note">{_e(analyst.get('broker_summary'))}</div>
  <table><thead><tr><th>증권사</th><th>발행일</th><th>의견</th><th>목표가</th><th>현재가 대비</th><th>평균 대비</th><th>읽는 법</th></tr></thead><tbody>{broker_rows}</tbody></table>

  <h2>3. 검증 결과</h2>
  <table><thead><tr><th>검증축</th><th>판정</th><th>해석</th><th>점수</th></tr></thead><tbody>{axis_rows}</tbody></table>

  <h2>4. 본문 의견 검증</h2>
  <p>{_e((model.get('report_content') or {}).get('summary') or (model.get('report_content_assessment') or {}).get('reason') or 'PDF 본문 의견 검증 결과가 없습니다.')}</p>
  {briefing_html}
  <table><thead><tr><th>논점</th><th>언급</th><th>리포트별 방향</th><th>실제 데이터 대조</th><th>판단</th></tr></thead><tbody>{content_rows}</tbody></table>

  <h2>5. 그대로 믿기 어려운 내용</h2>
  <table><thead><tr><th>항목</th><th>왜 중요한가</th><th>확인할 변화</th></tr></thead><tbody>{watchpoint_rows}</tbody></table>

  <h2>6. 점수 산정 근거</h2>
  <p>{_e(model['score_formula']['text'])}</p>
  <table><thead><tr><th>구분</th><th>배점</th><th>비중 설명</th><th>차감 기준</th><th>현재 적용</th></tr></thead><tbody>{score_rulebook}</tbody></table>
  <table><thead><tr><th>항목</th><th>배점</th><th>점수</th><th>차감</th><th>정량 근거</th><th>판정 로직</th></tr></thead><tbody>{score_audit}</tbody></table>

  <h2>7. 최신 실적 읽기</h2>
  <ul>{latest}</ul>

  <h2>8. 주가 괴리 해석</h2>
  <ul>{price_reads}</ul>

  <h2>9. 객관분석·발행 후 업데이트</h2>
  <table><thead><tr><th>구분</th><th>항목</th><th>판단</th><th>근거</th><th>점수 영향</th></tr></thead><tbody>{update_audit}</tbody></table>

  <h2>10. 원자료 연결</h2>
  <table><thead><tr><th>자료</th><th>출처</th><th>확인값</th><th>점수 연결</th></tr></thead><tbody>{source_audit}</tbody></table>

  <h2>11. 발행 후 확인할 이슈</h2>
  <ul>{issues}</ul>

  <h2>12. 최종 판정</h2>
  <p>{_e(verdict.get('headline'))}</p>
  <p>{_e(verdict.get('guide'))}</p>

  <footer>이 문서는 종목 매수·매도 추천이 아니라 증권사 리포트 신뢰도 검증 자료입니다. 자동 수집 데이터에는 결측 또는 지연 가능성이 있어, 원문 공시와 최신 시세 기준으로 해석됩니다.</footer>
</main>
</body>
</html>"""


def _pdf_font_path() -> str | None:
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/AppleGothic.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def generate_retail_pdf_report(analysis: dict) -> bytes:
    """Generate a compact PDF. Raises RuntimeError if Korean PDF support is unavailable."""
    try:
        from fpdf import FPDF
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PDF 생성 라이브러리 fpdf가 필요합니다.") from exc

    font_path = _pdf_font_path()
    if not font_path:
        raise RuntimeError("한글 PDF 폰트를 찾지 못했습니다.")

    model = build_retail_report_model(analysis)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.add_font("KR", "", font_path)
    pdf.add_font("KR", "B", font_path)
    pdf.set_font("KR", size=12)

    def write(text: str, size: int = 11, style: str = "", h: float = 7) -> None:
        pdf.set_font("KR", style=style, size=size)
        pdf.multi_cell(0, h, str(text))

    company = model["company"]
    report = model["report"]
    verdict = model["verdict"]
    write("FinSight 리포트 점검 결과", 11)
    write(f"{company['name']} 목표가 검증", 20, "B", 9)
    write(f"{report.get('broker') or '증권사 미입력'} · 발행일 {report.get('pub_date')} · 목표가 {_won(report.get('target_price'))} · 생성일 {model['as_of']}", 10)
    pdf.ln(2)
    write(f"신뢰도 {verdict['total']}/100 · {verdict['grade']}등급", 16, "B", 8)
    write(model["summary"], 11)
    pdf.ln(2)

    write("1. 검증 결과", 14, "B")
    for row in model["axis_rows"]:
        score = row["score"]
        score_text = "데이터 없음" if score.get("uncounted") else f"{score.get('score')}/{score.get('max')}"
        write(f"- {row['axis']} · {row['result']} · {score_text}", 11, "B")
        write(row["read"], 10)
    pdf.ln(1)

    write("2. 본문 의견 검증", 14, "B")
    content_assessment = model.get("report_content_assessment") or {}
    content_summary = (model.get("report_content") or {}).get("summary") or content_assessment.get("reason") or "PDF 본문 의견 검증 결과가 없습니다."
    write(content_summary, 10)
    briefing = (model.get("report_content") or {}).get("briefing") or {}
    if briefing.get("headline"):
        write(f"브리핑: {briefing.get('headline')}", 10, "B")
        for title, key in (
            ("믿고 가져갈 내용", "trusted"),
            ("그대로 믿기 어려운 내용", "watch"),
            ("리포트끼리 갈리는 내용", "contested"),
        ):
            items = briefing.get(key) or []
            if not items:
                continue
            write(title, 10, "B")
            for item in items[:3]:
                write(f"- {item.get('title')}: {item.get('read')}", 9)
    for row in (model.get("report_content") or {}).get("theme_rows", [])[:8]:
        write(f"- {row.get('논점')} · {row.get('판정')} · {row.get('언급 리포트')}", 10, "B")
        write(f"리포트별 방향: {row.get('리포트 간 차이')}", 9)
        write(f"실제 데이터 대조: {row.get('FinSight 대조')}", 9)
    pdf.ln(1)

    write("3. 점수 산정 근거", 14, "B")
    write(model["score_formula"]["text"], 10)
    for row in model["score_rulebook"]:
        write(f"- {row['구분']} · {row['배점']} · {row['현재 적용']}", 10, "B")
        write(f"차감 기준: {row['차감 기준']}", 9)
    for row in model["score_audit"]:
        write(f"- {row['항목']} · {row['점수']} · {row['차감']}", 10, "B")
        write(f"근거: {row['정량 근거']}", 9)
        write(f"로직: {row['판정 로직']}", 9)
    pdf.ln(1)

    write("4. 최신 실적 읽기", 14, "B")
    for row in model["latest_reads"] or [{"title": "실적 해석", "verdict": "", "read": "재무 데이터가 부족해 최신 분기 해석을 제한합니다.", "evidence": ""}]:
        write(f"- {row['title']} · {row['verdict']}", 11, "B")
        write(row["read"], 10)
        if row.get("evidence"):
            write(f"근거: {row['evidence']}", 9)
    pdf.ln(1)

    write("5. 주가 괴리 해석", 14, "B")
    for row in model["price_reads"] or [{"title": "주가 괴리", "verdict": "", "read": "현재 연결된 주가·수급 데이터에서는 별도 괴리 원인이 강하게 잡히지 않습니다.", "evidence": ""}]:
        write(f"- {row['title']} · {row['verdict']}", 11, "B")
        write(row["read"], 10)
        if row.get("evidence"):
            write(f"근거: {row['evidence']}", 9)
    pdf.ln(1)

    write("6. 객관분석·발행 후 업데이트", 14, "B")
    for row in model["update_audit"][:8]:
        write(f"- {row['평가 구분']} · {row['항목']} · {row['점수 영향']}", 10, "B")
        write(row["판단"], 9)
        if row.get("근거"):
            write(f"근거: {row['근거']}", 9)
    pdf.ln(1)

    write("7. 원자료 연결", 14, "B")
    for row in model["source_audit"]:
        write(f"- {row['자료']} · {row['출처']}", 10, "B")
        write(f"{row['확인값']} / {row['점수 연결']}", 9)
    pdf.ln(1)

    write("8. 발행 후 확인할 이슈", 14, "B")
    for row in model["issue_reads"] or [{"title": "발행 후 공시·뉴스", "verdict": "", "read": "현재 연결된 발행 후 공시·뉴스·지분 변동은 제한적입니다.", "evidence": ""}]:
        write(f"- {row['title']} · {row['verdict']}", 11, "B")
        write(row["read"], 10)
        if row.get("evidence"):
            write(f"근거: {row['evidence']}", 9)
    pdf.ln(1)

    write("9. 최종 판정", 14, "B")
    write(verdict.get("headline", ""), 11, "B")
    write(verdict.get("guide", ""), 10)
    pdf.ln(2)
    write("본 자료는 종목 매수·매도 추천이 아니라 증권사 리포트 신뢰도 검증 자료입니다.", 9)

    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        return raw.encode("latin-1")
    return bytes(raw)
