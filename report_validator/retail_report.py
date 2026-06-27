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
    if verdict["total"] >= 75:
        summary = f"{broker}의 목표가 {target_text}은 현재 FinSight 분석과 크게 충돌하지 않습니다. 신뢰도는 높게 볼 수 있습니다."
    elif verdict["total"] >= 60:
        summary = f"{broker}의 목표가 {target_text}은 참고할 만하지만, {lead_title} 때문에 그대로 확신하기는 어렵습니다."
    elif verdict["total"] >= 45:
        summary = f"{broker}의 목표가 {target_text}은 주의해서 봐야 합니다. FinSight 분석에서는 {lead_title}이 리포트 신뢰도를 낮췄습니다."
    else:
        summary = f"{broker}의 목표가 {target_text}은 그대로 믿기 어렵습니다. {lead_title}이 충분히 반영되지 않은 것으로 보입니다."

    content_assessment = analysis.get("report_content_assessment") or {}
    if content_assessment.get("penalty"):
        summary += f" PDF 본문 의견 검증에서는 {content_assessment.get('reason')} 때문에 신뢰도 {content_assessment.get('penalty')}점이 추가 차감됐습니다."

    return {
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


def generate_retail_html_report(analysis: dict) -> str:
    model = build_retail_report_model(analysis)
    company = model["company"]
    report = model["report"]
    verdict = model["verdict"]
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
        ("아직 보수적으로 볼 내용", "watch"),
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
  <title>FinSight 리포트 신뢰도 검증 - {_e(company['name'])}</title>
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
  <div class="kicker">FinSight 리포트 신뢰도 검증</div>
  <h1>{_e(company['name'])} 목표가 검증</h1>
  <div class="meta">{_e(report.get('broker') or '증권사 미입력')} · 발행일 {_e(report.get('pub_date'))} · 목표가 {_e(_won(report.get('target_price')))} · 생성일 {model['as_of']}</div>
  <div class="score"><b>{verdict['total']}</b><span>/100 · {verdict['grade']}등급</span></div>
  <div class="summary">{_e(model['summary'])}</div>

  <h2>1. 검증 결과</h2>
  <table><thead><tr><th>검증축</th><th>판정</th><th>해석</th><th>점수</th></tr></thead><tbody>{axis_rows}</tbody></table>

  <h2>2. 본문 의견 검증</h2>
  <p>{_e((model.get('report_content') or {}).get('summary') or (model.get('report_content_assessment') or {}).get('reason') or 'PDF 본문 의견 검증 결과가 없습니다.')}</p>
  {briefing_html}
  <table><thead><tr><th>논점</th><th>언급</th><th>리포트별 방향</th><th>실제 데이터 대조</th><th>판단</th></tr></thead><tbody>{content_rows}</tbody></table>

  <h2>3. 점수 산정 근거</h2>
  <p>{_e(model['score_formula']['text'])}</p>
  <table><thead><tr><th>구분</th><th>배점</th><th>비중 설명</th><th>차감 기준</th><th>현재 적용</th></tr></thead><tbody>{score_rulebook}</tbody></table>
  <table><thead><tr><th>항목</th><th>배점</th><th>점수</th><th>차감</th><th>정량 근거</th><th>판정 로직</th></tr></thead><tbody>{score_audit}</tbody></table>

  <h2>4. 최신 실적 읽기</h2>
  <ul>{latest}</ul>

  <h2>5. 주가 괴리 해석</h2>
  <ul>{price_reads}</ul>

  <h2>6. 객관분석·발행 후 업데이트</h2>
  <table><thead><tr><th>구분</th><th>항목</th><th>판단</th><th>근거</th><th>점수 영향</th></tr></thead><tbody>{update_audit}</tbody></table>

  <h2>7. 원자료 연결</h2>
  <table><thead><tr><th>자료</th><th>출처</th><th>확인값</th><th>점수 연결</th></tr></thead><tbody>{source_audit}</tbody></table>

  <h2>8. 발행 후 확인할 이슈</h2>
  <ul>{issues}</ul>

  <h2>9. 결론</h2>
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
    write("FinSight 리포트 신뢰도 검증", 11)
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
            ("아직 보수적으로 볼 내용", "watch"),
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

    write("9. 결론", 14, "B")
    write(verdict.get("headline", ""), 11, "B")
    write(verdict.get("guide", ""), 10)
    pdf.ln(2)
    write("본 자료는 종목 매수·매도 추천이 아니라 증권사 리포트 신뢰도 검증 자료입니다.", 9)

    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        return raw.encode("latin-1")
    return bytes(raw)
