"""Analyst one-pager (Markdown) shipped alongside the Excel workbook."""

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
        return "싸 보이지만, 아직 시장이 전부 믿지는 않는 구간"
    if gap > 15:
        return "업사이드는 열려 있지만, 재평가 조건 확인이 먼저"
    if gap > -15:
        return "현재 주가가 산정가치와 크게 멀지 않은 구간"
    return "모델 가정이 시장보다 낙관적인 구간"


def _report_header(company: str, latest: pd.Series, verdict: str) -> list[str]:
    return [
        f"<div style='font-size:22px;font-weight:750;letter-spacing:-0.03em;margin:0 0 4px'>{company} 투자 메모</div>",
        f"<div style='font-size:12px;color:#667085;margin-bottom:14px'>{latest['period']} 기준 · 생성 {dt.date.today().isoformat()} · DART/시세/공시/리서치 참고자료 기반</div>",
        f"<div style='border-left:3px solid #1D4E89;background:#F8FAFC;padding:10px 13px;margin:10px 0 18px'><span style='font-size:12px;color:#667085'>핵심 판단</span><br><span style='font-size:15px;font-weight:700;color:#143257'>{_clean(verdict)}</span></div>",
    ]


def _section(title: str, subtitle: str | None = None) -> list[str]:
    block = [
        "",
        f"<div style='font-size:16px;font-weight:750;color:#143257;margin:22px 0 4px'>{title}</div>",
    ]
    if subtitle:
        block.append(f"<div style='font-size:12px;color:#667085;margin-bottom:8px'>{subtitle}</div>")
    block.append("")
    return block


def _valuation_gap_block(dcf: dict | None, valuation_range: dict, capital: dict, price_action: dict) -> list[str]:
    current = _num(capital.get("current_price"))
    dcf_price = _num((dcf or {}).get("implied_price"))
    cross_mid = _num(valuation_range.get("mid"))
    terminal_share = _num((dcf or {}).get("terminal_value_share"))
    dcf_gap = (dcf_price / current - 1) * 100 if dcf_price and current else None
    cross_gap = (cross_mid / current - 1) * 100 if cross_mid and current else None
    drawdown = _num((price_action or {}).get("price_frame", {}).get("drawdown"))
    ret_3m = _num((price_action or {}).get("price_frame", {}).get("ret_3m"))

    blockers = []
    if terminal_share is not None and terminal_share > 75:
        blockers.append("DCF 가치의 상당 부분이 터미널가치에 몰려 있어 WACC·영구성장률 작은 변화에도 목표가가 크게 흔들립니다.")
    if ret_3m is not None and ret_3m < -8:
        blockers.append("최근 주가가 약했다면 시장은 현재 실적보다 다음 분기 지속성·수급·촉매를 더 크게 할인하고 있습니다.")
    if drawdown is not None and drawdown < -20:
        blockers.append("52주 고점 대비 낙폭이 크면 ‘싸다’만으로 부족하고, 고점에서 붙었던 프리미엄이 왜 사라졌는지 따로 설명해야 합니다.")
    if not blockers:
        blockers.append("가치와 주가의 괴리는 단일 이유보다 실적 지속성, 수급, 섹터 선호, 할인율이 동시에 만든 결과로 보는 편이 안전합니다.")

    return [
        *_section("가치 괴리: 숫자가 맞아도 주가가 바로 따라오지 않는 이유"),
        _gap_label(cross_gap if cross_gap is not None else dcf_gap),
        "",
        "| 기준 | 주당가치 | 현재가 대비 | 해석 |",
        "|---|---:|---:|---|",
        _row("DCF", _f(dcf_price, "원", 0), _f(dcf_gap, "%"), "영업가정이 맞을 때의 이론값"),
        _row("현실 검산값", _f(cross_mid, "원", 0), _f(cross_gap, "%"), "DCF·멀티플·리서치 참고값을 함께 본 중간값"),
        _row("현재가", _f(current, "원", 0), "—", "시장이 지금 인정하는 가격"),
        "",
        "**읽는 법**",
        "",
        "DCF가 현재가보다 높게 나왔다고 해서 그 차이를 그대로 기대수익률로 보면 곤란합니다. 더 중요한 질문은 “왜 시장이 아직 그 가치를 가격에 다 반영하지 않았나”입니다. 보통 세 가지가 겹칩니다.",
        "",
        "1. **확인의 시간차** — 모델은 미래 현금흐름을 오늘 당겨오지만, 시장은 다음 분기 숫자와 수급을 보고 움직입니다.",
        "2. **가정의 온도차** — 매출·마진 가정을 조금만 높여도 DCF는 크게 뛰지만, 시장은 원가·환율·경쟁·CAPEX 회수 지연을 먼저 할인합니다.",
        "3. **투자자 심리와 수급** — 손실 구간의 매물, 기관·외국인 매도, 테마 선호 약화가 남아 있으면 좋은 실적도 바로 주가에 반영되지 않습니다.",
        "",
        "**지금 특히 봐야 할 할인 요인**",
        "",
        *[f"- {item}" for item in blockers],
        "",
    ]


def _synthesis_block(latest: pd.Series, price_action: dict, tracker_commentary: list[dict] | None, thesis: dict | None) -> list[str]:
    cards = tracker_commentary or []
    thesis = thesis or {}
    first_card = cards[0] if cards else {}
    return [
        *_section("종합 해석", "실적, 주가, 가치평가를 따로 보지 않고 한 번에 읽은 결론입니다."),
        "| 질문 | 답 | 그래서 봐야 할 것 |",
        "|---|---|---|",
        _row(
            "실적은 좋은가?",
            f"매출 YoY {_f(latest.get('revenue_yoy'), '%')}, OPM {_f(latest.get('opm'), '%')}, FCF 마진 {_f(latest.get('fcf_margin'), '%')}",
            "성장률보다 마진과 현금 전환이 같이 개선되는지",
        ),
        _row(
            "주가는 왜 덜 따라오나?",
            (price_action or {}).get("verdict", "수급·기대치·지속성 확인 필요"),
            "좋은 분기 실적이 다음 분기에도 반복되는지, 매도 압력이 줄었는지",
        ),
        _row(
            "가정은 어떻게 둘까?",
            first_card.get("action", "기본 시나리오는 유지하고, 확인된 증거가 쌓일 때만 가정을 바꿉니다."),
            first_card.get("model_link", "매출 성장률 / OPM / FCFF / WACC"),
        ),
        "",
        (price_action or {}).get("thesis") or thesis.get("summary", ""),
        "",
    ]


def _decision_rules_block(thesis: dict | None, tracker_commentary: list[dict] | None) -> list[str]:
    lines = [
        *_section("다음 분기 판단 기준", "확인되면 무엇을 바꾸고, 확인되지 않으면 무엇을 보수적으로 둘지 정리했습니다."),
        "| 확인할 것 | 확인되면 | 확인 안 되면 | 가정 조정 |",
        "|---|---|---|---|",
    ]
    checkpoints = (thesis or {}).get("checkpoints", [])[:5]
    if checkpoints:
        for c in checkpoints:
            if isinstance(c, str):
                lines.append(_row(c, "해당 논점 신뢰도 상승", "보수 가정 유지", "한 분기 신호만으로 목표가를 바꾸지 않음"))
            else:
                lines.append(_row(c.get("checkpoint"), c.get("if_confirmed"), c.get("if_not_confirmed"), c.get("action")))
    else:
        for card in (tracker_commentary or [])[:4]:
            lines.append(_row(card.get("next"), "연결 가정 상향 검토", "기본/보수 시나리오 유지", card.get("action")))
    lines.append("")
    return lines


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
    latest = kpis.iloc[-1]
    pa = price_action or {}
    capital = capital or {}
    vr = valuation_range or {}
    current = _num(capital.get("current_price"))
    mid = _num(vr.get("mid"))
    upside = (mid / current - 1) * 100 if mid and current else None
    lines = _report_header(company, latest, pa.get("verdict") or _gap_label(upside))

    lines += _synthesis_block(latest, pa, tracker_commentary, thesis)
    lines += _valuation_gap_block(dcf, vr, capital, pa)

    if pa.get("attribution"):
        lines += [*_section("주가 괴리 요인", "주가가 실적을 바로 따라가지 못한 이유를 네 가지로 나눠 봅니다."), "| 변동요인 | 강도 | 해석 | 근거 |", "|---|---|---|---|"]
        for a in pa["attribution"]:
            reading = str(a.get("reading", "")).replace("\n", " ")
            lines.append(_row(a.get("driver", ""), a.get("weight", ""), reading, f"{a.get('evidence','')} ({a.get('evidence_level','')})"))
        lines.append("")

    lines += [
        *_section("실적의 질", "좋은 숫자인지, 좋아 보이는 숫자인지를 구분합니다."),
        "| 축 | 최신 신호 | 해석 | 모델 연결 |",
        "|---|---:|---|---|",
        _row("외형", _f(latest.get("revenue_yoy"), "%"), "매출은 늘었는지. 다만 가격·환율·물량 중 무엇이 만든 성장인지는 따로 봐야 함", "매출 성장률"),
        _row("수익성", _f(latest.get("opm"), "%"), f"QoQ {_f(latest.get('opm_qoq_pp'), '%p')}. 원가율과 판관비율 중 어느 쪽이 움직였는지 확인", "OPM"),
        _row("현금", _f(latest.get("fcf_margin"), "%"), "이익이 현금으로 남는지 보는 지표. 가치평가에서는 이 숫자가 특히 중요", "잉여현금흐름"),
        _row("원가/판관비", f"원가율 {_f(latest.get('cogs_ratio'), '%')} / 판관비율 {_f(latest.get('sga_ratio'), '%')}", "마진 변화의 출발점", "매출총이익률 / 판관비율"),
        "",
    ]
    if tracker_commentary:
        lines += ["**이번 분기 핵심 읽기**", ""]
        for card in tracker_commentary[:3]:
            lines.append(f"- **{card.get('title')}** — {card.get('read')}  ")
            lines.append(f"  - 해석: {card.get('action') or card.get('so_what')} / 연결 가정: {card.get('model_link', 'DCF')}")
        lines.append("")

    interp = interpreted or []
    lines += _section("숫자 뒤의 원인", "이상신호가 있다면 원인 후보와 확인 방법을 붙였습니다.")
    if not interp:
        lines.append("- 자체 과거 범위와 절대 기준에서 우선 검토할 이상 항목 없음")
    for idx, item in enumerate(interp, 1):
        I = item.get("interpretation", {})
        lines.append(f"\n**{idx}. {I.get('headline', item.get('label',''))}**  \n_해석 신뢰도: {I.get('confidence','')}_")
        lines.append(I.get("narrative", ""))
        causes = I.get("cause_candidates", [])
        if causes:
            lines.append("\n**원인 후보 (근거 강도순)**")
            for c in causes:
                src = c.get("source", "")
                lines.append(f"- [{c.get('evidence_level','')}] {c.get('cause','')} — {src}")
        if I.get("verification"):
            lines.append("\n**확인 절차**")
            for j, r in enumerate(I["verification"], 1):
                lines.append(f"{j}. **어디서** {r.get('where','')}")
                lines.append(f"   - **무엇을** {r.get('what','')}")
                lines.append(f"   - **판정** {r.get('rule','')}")
        if I.get("falsifier"):
            lines.append(f"\n> 반증: {I['falsifier']}")
    lines.append("")

    lines += _section("가치평가를 읽는 법", "목표가 하나보다, 어떤 가정이 가격을 움직이는지가 중요합니다.")
    if dcf:
        lines += [
            f"- WACC {_f(dcf.get('wacc'),'%',2)} · 터미널/EV {_f(dcf.get('terminal_value_share'),'%')} · DCF 주당가치 {_f(dcf.get('implied_price'),'원',0)}",
        ]
        if dcf.get("opm_path_used"):
            lines.append("- OPM은 단순 추세선이 아니라 판관비를 인건비·변동비·고정비·대손으로 나눠 계산")
    if structured and structured.get("opm_build"):
        path = structured["opm_build"].get("opm_path", [])
        if path:
            lines.append("- 판관비 기반 OPM 경로: " + " → ".join(_f(v, "%") for v in path if v is not None))
    if structured and structured.get("wacc"):
        w = structured["wacc"]
        lines.append(f"- WACC 구성: Rf {_f(w.get('rf'),'%')} + β {_f(w.get('beta'),'',3)} × ERP {_f(w.get('erp'),'%')} → Ke {_f(w.get('cost_equity'),'%')}; β 산출 {w.get('beta_source','')}")
    if vr.get("mid") is not None:
        upside = (vr["mid"] / capital["current_price"] - 1) * 100 if capital.get("current_price") else None
        lines.append(f"- 현실 검산값(DCF·PER·EV/EBITDA·리서치 참고) {_f(vr.get('mid'),'원',0)} (하단 {_f(vr.get('low'),'원',0)} / 상단 {_f(vr.get('high'),'원',0)}) · 현재가 대비 {_f(upside,'%')}")
    if research and research.get("valuation", {}).get("broker_targets"):
        tgts = ", ".join(f"{t['source']} {t['target_price']:,}원" for t in research["valuation"]["broker_targets"])
        lines.append(f"- 참고 브로커 목표가: {tgts}")
    lines.append("")
    lines.append("**이 숫자를 대하는 태도**")
    lines.append("")
    lines.append("- DCF가 현재가보다 높아도 그 차이를 전부 상승여력으로 보지 않습니다. 터미널가치 비중, 수급, 아직 확인되지 않은 성장 옵션은 할인해야 합니다.")
    lines.append("- 현재가가 낮다고 해서 시장이 무조건 틀린 것도 아닙니다. 시장은 경쟁, 원가, 정책, 섹터 선호, 투자자 심리를 모델보다 먼저 가격에 반영할 때가 많습니다.")
    lines.append("- 그래서 이 리포트는 ‘정답 목표가’를 찍기보다, 어떤 증거가 나오면 어떤 가정을 바꿀지 정하는 데 초점을 둡니다.")
    lines.append("")

    lines += _decision_rules_block(thesis, tracker_commentary)

    lines += [
        "---",
        "_본 자료는 DART 재무 패턴과 공시·뉴스·리서치 참고자료를 함께 본 검토용 리포트입니다. 원인 후보는 근거 강도를 구분했으며, 투자 판단은 다음 분기 확인되는 숫자와 수급을 함께 봐야 합니다._",
    ]
    return "\n".join(lines)


generate_business_report = generate_analysis_summary
generate_analyst_report = generate_analysis_summary
generate_executive_brief = generate_analysis_summary
