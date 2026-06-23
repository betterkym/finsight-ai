"""Evidence-ranked investment thesis and expectation-gap interpretation."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _fact(label: str, value: str, interpretation: str, source: str, confidence: str = "High") -> dict:
    return {"label": label, "value": value, "interpretation": interpretation, "source": source, "confidence": confidence}


def build_investment_thesis(
    kpis: pd.DataFrame,
    market: dict,
    ownership: list[dict],
    disclosures: list[dict],
    news: list[dict],
    blogs: list[dict],
    peer_kpis: dict[str, pd.DataFrame],
    research: dict,
) -> dict:
    """Separate operating facts, market expectations, flows and catalyst timing."""
    latest = kpis.iloc[-1]
    revenue_yoy = _num(latest.get("revenue_yoy"))
    op_yoy = _num(latest.get("operating_profit_yoy"))
    opm = _num(latest.get("opm"))
    opm_yoy = _num(latest.get("opm_yoy_pp"))
    cfo_margin = _num(latest.get("cfo_margin"))
    price_3m = _num(market.get("return_3m"))
    drawdown = _num(market.get("drawdown_52w_high"))

    operating_score = 0
    for value, positive in ((revenue_yoy, 0), (op_yoy, 0), (opm_yoy, 0), (cfo_margin, 0)):
        if value is not None:
            operating_score += 1 if value > positive else -1
    price_weak = (price_3m is not None and price_3m < -8) or (drawdown is not None and drawdown < -15)
    operating_ok = operating_score >= 2

    facts = [
        _fact("매출", f"{revenue_yoy:+.1f}% YoY" if revenue_yoy is not None else "N/A", "외형의 현재 방향", "DART 분기재무"),
        _fact("영업이익", f"{op_yoy:+.1f}% YoY" if op_yoy is not None else "N/A", "이익 모멘텀", "DART 분기재무"),
        _fact("영업이익률", f"{opm:.1f}% / YoY {opm_yoy:+.1f}%p" if opm is not None and opm_yoy is not None else "N/A", "원가·판관비를 반영한 수익성", "DART 분기재무"),
        _fact("주가", f"3개월 {price_3m:+.1f}% / 52주 고점 대비 {drawdown:.1f}%" if price_3m is not None and drawdown is not None else "N/A", "실적과 시장 기대의 차이", market.get("source", "Market data")),
    ]

    hypotheses = []
    if operating_ok and price_weak:
        headline = "실적 훼손보다 기대치·수급·성장 증명의 문제"
        summary = "최근 영업지표는 개선됐지만 주가는 이를 따라가지 못했습니다. 시장은 현재 숫자보다 해외 성장의 질, 투자 회수 시점과 수급을 할인하고 있을 가능성이 큽니다."
        hypotheses.append({
            "title": "Expectation de-rating",
            "explanation": "좋은 분기 실적이 이미 예상에 반영됐거나, 다음 분기 지속 가능성에 대한 신뢰가 낮아 멀티플이 확장되지 않은 구간입니다.",
            "confidence": "High", "evidence": ["DART 실적 개선", "주가 3개월/52주 고점 대비 약세"],
            "falsifier": "다음 분기 해외 매출·물량·이익률이 함께 개선되고도 멀티플이 회복되지 않는 경우",
        })
    elif not operating_ok and price_weak:
        headline = "실적과 주가가 함께 약한 펀더멘털 경계 구간"
        summary = "주가 약세를 수급만으로 설명하기 어렵습니다. 매출·마진·현금흐름 중 훼손된 축의 회복 확인이 먼저입니다."
    elif operating_ok:
        headline = "펀더멘털 개선이 주가에 반영되는 구간"
        summary = "실적과 시장 가격의 방향이 대체로 일치합니다. 다음 판단은 개선 속도의 지속성과 밸류에이션 부담입니다."
    else:
        headline = "방향성이 혼재된 확인 구간"
        summary = "실적과 가격 신호가 한 방향으로 모이지 않습니다. 단일 원인으로 결론내리지 않고 다음 공시를 확인해야 합니다."

    negative_ownership = [row for row in ownership if (_num(row.get("ratio_change")) or 0) < 0]
    if negative_ownership:
        row = negative_ownership[0]
        hypotheses.append({
            "title": "5% 주주 수급 부담",
            "explanation": f"{row.get('reporter') or '주요주주'}의 보유비율이 최근 보고에서 {row.get('ratio_change'):+.2f}%p 변동했습니다. 이는 사업 훼손과 별개로 단기 공급 부담이 될 수 있습니다.",
            "confidence": "High", "evidence": ["DART 대량보유 상황보고"],
            "falsifier": "후속 보고에서 매도가 멈추고 기관·외국인 수급이 정상화되는 경우", "url": row.get("url"),
        })

    facility = [item for item in disclosures if any(word in f"{item.get('title','')} {item.get('description','')}" for word in ("시설투자", "공장", "증설"))]
    if facility:
        hypotheses.append({
            "title": "성장 옵션과 실행 지연의 동시 반영",
            "explanation": "수출 설비 투자는 중장기 공급능력을 높이지만, 투자비 증가·준공 지연·초기 가동률은 단기 FCF와 멀티플에 부담이 될 수 있습니다.",
            "confidence": "Medium", "evidence": [facility[0].get("title", "DART 시설투자 공시")],
            "falsifier": "준공 일정 준수와 가동률 상승이 해외 매출·마진 개선으로 확인되는 경우", "url": facility[0].get("url"),
        })

    for driver in research.get("drivers", []):
        if driver.get("impact") in {"Risk", "Watch", "Flow Risk", "Catalyst/Risk"}:
            hypotheses.append({
                "title": f"{driver['theme']} 검증 포인트",
                "explanation": driver["fact"], "confidence": "Medium",
                "evidence": [driver["source"]], "falsifier": "다음 분기 세부 매출·물량·마진 자료로 반대 방향이 확인되는 경우",
            })

    expectation = research.get("expectations", [])
    if expectation:
        surprises = [row["value"] for row in expectation if row.get("metric") == "operating_profit_surprise"]
        if surprises:
            facts.append(_fact("컨센서스 괴리", f"영업이익 +{np.median(surprises):.1f}%", "실적은 기대를 상회했으나 주가 반응이 약하면 다음 분기 지속성 또는 수급 문제를 의심", "User-provided broker reports", "Medium"))

    related_context = []
    terms = ["수출", "공장", "점유율", "가격", "원가", "외국인", "국민연금", "경쟁", "유럽", "미국"]
    for item in news + blogs:
        haystack = f"{item.get('title','')} {item.get('description','')}"
        matched = [term for term in terms if term in haystack]
        if matched:
            related_context.append({**item, "matched_keywords": matched})
    related_context.sort(key=lambda item: 0 if item.get("source") == "Naver News" else 1)

    checkpoints = list(dict.fromkeys(research.get("checkpoints", []) + [hypothesis["falsifier"] for hypothesis in hypotheses]))[:7]
    return {
        "headline": headline, "summary": summary, "facts": facts,
        "hypotheses": hypotheses[:6], "checkpoints": checkpoints,
        "context": related_context[:6], "operating_score": operating_score,
        "expectation_gap": bool(operating_ok and price_weak),
    }
