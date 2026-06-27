"""Evidence-ranked investment thesis and expectation-gap interpretation."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _short(text: str | None, limit: int = 155) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _fact(label: str, value: str, interpretation: str, source: str, confidence: str = "High") -> dict:
    return {"label": label, "value": value, "interpretation": interpretation, "source": source, "confidence": confidence}


def _context_summary(item: dict, matched: list[str]) -> str:
    """Make external links decision-useful while keeping them below filing evidence."""
    source = item.get("source", "External")
    desc = _short(item.get("description"), 145)
    keyword_note = f"관련 키워드: {', '.join(matched[:4])}" if matched else "관련 키워드 미확인"
    if not desc:
        desc = "제목 기준으로만 매칭됐습니다. 원문 확인 전에는 투자 근거로 쓰지 않습니다."
    if source == "Naver Blog":
        return f"참고 정황: {desc} ({keyword_note}). 사실 확정이 아니라 가능한 원인을 넓혀 보는 참고용입니다."
    return f"참고 정황: {desc} ({keyword_note}). DART 숫자와 맞을 때만 해석 근거로 사용합니다."


def _checkpoint_from_text(text: str, hypothesis: dict | None = None) -> dict:
    """Turn a proof point into a so-what decision rule."""
    label = text.strip()
    low = label.lower()
    if "해외" in label and ("멀티플" in label or "회복" in label):
        return {
            "checkpoint": label,
            "why": "실적 개선이 이미 가격에 반영됐는지, 아니면 시장이 성장 지속성을 아직 믿지 않는지 가르는 확인점입니다.",
            "if_confirmed": "해외 매출·물량·마진이 좋아졌는데도 멀티플이 회복되지 않으면 실적 가정보다 할인율/WACC·목표 멀티플·촉매 부재가 문제입니다.",
            "if_not_confirmed": "해외 지표 중 하나라도 둔화되면 주가 부진은 기대치 문제가 아니라 성장/마진 가정 자체의 하향 신호입니다.",
            "action": "DCF에서는 매출 성장률을 쉽게 올리지 말고, Base는 보수 유지·Bull은 2개 분기 연속 확인 뒤 적용합니다.",
            "valuation_link": "매출 성장률 / Target PER",
        }
    if any(word in label for word in ("매도", "수급", "외국인", "기관", "국민연금")):
        return {
            "checkpoint": label,
            "why": "펀더멘털과 별개로 주가 상단을 누르는 공급 압력이 남아 있는지 확인합니다.",
            "if_confirmed": "매도 압력이 멈추고 외국인·기관 수급이 정상화되면 수급 할인은 일부 제거되어 멀티플 회복 여지가 생깁니다.",
            "if_not_confirmed": "수급 정상화가 없으면 실적이 좋아도 리레이팅이 지연될 수 있어 목표가보다 진입 타이밍을 더 보수적으로 봅니다.",
            "action": "DCF 현금흐름은 유지하되 교차검증 멀티플은 하단/중앙값 위주로 사용합니다.",
            "valuation_link": "Target PER / 진입 시점",
        }
    if any(word in label for word in ("준공", "가동률", "공장", "시설투자")):
        return {
            "checkpoint": label,
            "why": "증설은 성장 옵션이지만 지연·초기 가동률 부진은 FCF와 마진을 동시에 압박할 수 있습니다.",
            "if_confirmed": "준공과 가동률이 계획대로 확인되면 해외 매출 성장률과 중장기 OPM 상향 근거가 됩니다.",
            "if_not_confirmed": "지연 또는 낮은 가동률이면 CAPEX 부담은 남고 매출 전환이 늦어져 FCF/TV 가정을 낮춰야 합니다.",
            "action": "CAPEX/매출과 D&A를 높게 유지하고, Bull case 적용을 보류합니다.",
            "valuation_link": "CAPEX / D&A / Terminal growth",
        }
    if any(word in label for word in ("물량", "마진", "세부 매출", "원가")):
        return {
            "checkpoint": label,
            "why": "매출 증가가 가격/환율 효과인지, 실제 물량과 마진 개선인지 분리합니다.",
            "if_confirmed": "물량과 마진이 함께 개선되면 성장의 질이 좋아져 매출 성장률과 OPM을 동시에 올릴 수 있습니다.",
            "if_not_confirmed": "매출만 늘고 물량·마진이 약하면 가격/환율 착시 가능성이 있어 OPM과 FCF 전환율을 보수화합니다.",
            "action": "분기 트래커에서 매출 YoY와 OPM YoY, CFO 마진을 묶어 확인합니다.",
            "valuation_link": "OPM / FCFF conversion",
        }
    if hypothesis:
        return {
            "checkpoint": label,
            "why": hypothesis.get("explanation", "이 해석을 유지할지 판단하는 반증 조건입니다."),
            "if_confirmed": "해석이 반증되면 해당 리스크 프리미엄을 낮추거나 성장/마진 가정을 정상화할 수 있습니다.",
            "if_not_confirmed": "반증되지 않으면 현재 보수 가정을 유지하고 다음 공시까지 확정 판단을 미룹니다.",
            "action": "근거가 2개 이상 쌓일 때만 DCF 입력값을 변경합니다.",
            "valuation_link": "DCF assumption review",
        }
    return {
        "checkpoint": label,
        "why": "현재 투자 논점이 다음 분기에도 유효한지 확인하는 항목입니다.",
        "if_confirmed": "확인되면 해당 해석의 신뢰도를 높이고 연결된 DCF 가정을 조정합니다.",
        "if_not_confirmed": "확인되지 않으면 해석의 신뢰도를 낮추고 다른 원인을 우선 검토합니다.",
        "action": "확인 전에는 단일 지표만으로 목표가를 바꾸지 않습니다.",
        "valuation_link": "Assumption linkage",
    }


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
            "so_what": "실적 숫자가 맞았다는 것만으로는 부족합니다. 시장이 원하는 증거는 해외 성장의 질과 멀티플 회복의 동행입니다.",
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

    negative_ownership = sorted(
        (row for row in ownership if (_num(row.get("ratio_change")) or 0) < -0.3),
        key=lambda row: _num(row.get("ratio_change")) or 0,
    )
    if negative_ownership:
        row = negative_ownership[0]
        hypotheses.append({
            "title": "5% 주주 수급 부담",
            "explanation": f"{row.get('reporter') or '주요주주'}의 보유비율이 최근 보고에서 {row.get('ratio_change'):+.2f}%p 줄었습니다. 사업 훼손과 별개로 단기 공급 부담이 됩니다.",
            "confidence": "High", "evidence": ["DART 대량보유 상황보고"],
            "falsifier": "후속 보고에서 매도가 멈추고 기관·외국인 수급이 정상화되는 경우", "url": row.get("url"),
            "so_what": "수급 부담이면 손익계산서가 좋아져도 주가가 늦게 반응합니다. 주가 판단은 실적보다 수급 정상화 시점을 같이 봐야 합니다.",
        })

    facility = [item for item in disclosures if any(word in f"{item.get('title','')} {item.get('description','')}" for word in ("시설투자", "공장", "증설"))]
    if facility:
        hypotheses.append({
            "title": "성장 옵션과 실행 지연의 동시 반영",
            "explanation": "수출 설비 투자는 중장기 공급능력을 높이지만, 투자비 증가·준공 지연·초기 가동률은 단기 FCF와 멀티플에 부담이 될 수 있습니다.",
            "confidence": "Medium", "evidence": [facility[0].get("title", "DART 시설투자 공시")],
            "falsifier": "준공 일정 준수와 가동률 상승이 해외 매출·마진 개선으로 확인되는 경우", "url": facility[0].get("url"),
            "so_what": "증설은 장기 성장 옵션이지만 단기에는 CAPEX·감가상각·초기 효율 부담입니다. 그래서 매출 성장과 FCF를 같이 봐야 합니다.",
        })

    for driver in research.get("drivers", []):
        if driver.get("impact") in {"Risk", "Watch", "Flow Risk", "Catalyst/Risk"}:
            hypotheses.append({
                "title": f"{driver['theme']} 검증 포인트",
                "explanation": driver["fact"], "confidence": "Medium",
                "evidence": [driver["source"]], "falsifier": "다음 분기 세부 매출·물량·마진 자료로 반대 방향이 확인되는 경우",
                "so_what": "리서치 참고 논점은 DART 숫자로 재확인되기 전까지는 미검증 정황입니다. 확인되면 연결 가정을 조정하고, 아니면 제외합니다.",
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
            related_context.append({**item, "matched_keywords": matched, "summary": _context_summary(item, matched)})
    related_context.sort(key=lambda item: 0 if item.get("source") == "Naver News" else 1)

    checkpoint_texts = list(dict.fromkeys(research.get("checkpoints", []) + [hypothesis["falsifier"] for hypothesis in hypotheses]))[:7]
    checkpoints = []
    for text in checkpoint_texts:
        linked = next((h for h in hypotheses if h.get("falsifier") == text), None)
        checkpoints.append(_checkpoint_from_text(text, linked))
    return {
        "headline": headline, "summary": summary, "facts": facts,
        "hypotheses": hypotheses[:6], "checkpoints": checkpoints,
        "context": related_context[:6], "operating_score": operating_score,
        "expectation_gap": bool(operating_ok and price_weak),
    }
