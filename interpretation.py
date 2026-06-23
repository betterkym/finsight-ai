"""Second-level causal interpretation.

Where ``signal_engine`` answers *what* moved and *which DART account* explains the
mechanics, this module answers *why* — it chains the number to a concrete, sourced
business cause instead of stopping at "please re-check this account". Every cause
candidate carries an explicit evidence level so a reader can tell a primary filing
fact from a reported-news inference from an unverified blog interpretation.

Nothing here invents a cause. When no evidence pool supports a reading, the module
says so plainly and falls back to the mechanical DART answer.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


# Evidence tiers, ranked. Lower rank = harder evidence.
_TIER_RANK = {
    "Primary filing": 0, "Primary filing data": 0, "Primary filing text": 0,
    "Broker estimate comparison": 1, "User-provided broker reports": 1,
    "Reported context": 2, "Reported context (news)": 2,
    "Context": 3, "Unverified interpretation": 4,
}
_TIER_LABEL = {
    0: "1차 공시", 1: "리서치 추정", 2: "보도 정황", 3: "참고 맥락", 4: "미검증 해석",
}


def _tier(level: str | None) -> int:
    return _TIER_RANK.get(str(level or "Context"), 3)


# Per-metric causal scaffolding. ``themes`` are research-driver themes that plausibly
# move the metric; ``keywords`` rank free-text context; ``frame`` turns a matched
# cause into a full sentence rather than a checklist line.
_METRIC_CAUSE = {
    "cogs_ratio": {
        "themes": {"원가", "원재료", "환율", "관세", "물량"},
        "keywords": ["원재료", "곡물", "원맥", "팜유", "환율", "관세", "에누리", "가격 인상", "판가", "가동률", "물량"],
        "mechanism": "원가율 상승은 보통 ① 원재료·환율 등 투입가, ② 판가/에누리, ③ 가동률(고정비 분산) 셋 중 하나가 움직인 결과입니다.",
    },
    "sga_ratio": {
        "themes": {"마케팅", "수급", "유럽", "미주", "채널"},
        "keywords": ["마케팅", "광고", "판촉", "프로모션", "물류", "운송", "인건비", "수수료", "신규 채널", "입점", "법인"],
        "mechanism": "판관비율 변화는 광고·판촉, 물류, 인건비, 신규 진출 비용 중 어디가 늘었는지로 갈립니다.",
    },
    "opm": {
        "themes": {"원가", "마케팅", "미주", "국내", "유럽", "점유율"},
        "keywords": ["원가", "판가", "가격", "경쟁", "점유율", "프로모션", "마케팅", "물량", "믹스"],
        "mechanism": "영업이익률은 원가율과 판관비율의 합성 결과이므로, 둘 중 무엇이 주도했는지부터 분리해야 합니다.",
    },
    "revenue_yoy": {
        "themes": {"국내", "미주", "유럽", "중국", "수출", "점유율", "채널"},
        "keywords": ["수출", "해외", "미국", "유럽", "중국", "점유율", "신제품", "물량", "판가", "경쟁", "채널", "입점"],
        "mechanism": "매출 성장은 가격(판가)과 물량으로 분해되고, 지역별로는 국내 점유율과 해외 신규 시장 기여가 다릅니다.",
    },
    "fcf_margin": {
        "themes": {"설비", "투자", "공장", "증설"},
        "keywords": ["투자", "공장", "증설", "설비", "CAPEX", "준공", "가동", "재고", "채권"],
        "mechanism": "FCF 약화는 운전자본(재고·채권) 증가 또는 설비 투자 확대에서 나옵니다.",
    },
    "cfo_margin": {
        "themes": {"재고", "채권"},
        "keywords": ["재고", "채권", "회수", "현금", "운전자본"],
        "mechanism": "CFO가 이익을 따라오지 못하면 운전자본에 현금이 묶였을 가능성이 큽니다.",
    },
    "cash_conversion": {
        "themes": {"재고", "채권"},
        "keywords": ["재고", "채권", "회수", "선수금", "현금"],
        "mechanism": "현금 전환율 하락은 이익의 질 문제로, 매출채권·재고 증가가 전형적 원인입니다.",
    },
    "ar_days": {
        "themes": {"채널", "수출"},
        "keywords": ["채권", "회수", "직거래", "수출", "채널", "결제"],
        "mechanism": "회수일수 증가는 결제조건 완화나 신규(해외·직거래) 채널 비중 확대와 자주 동행합니다.",
    },
    "inventory_days": {
        "themes": {"수출", "공장", "수요"},
        "keywords": ["재고", "수요", "출하", "물량", "수출", "선적", "생산"],
        "mechanism": "재고일수 증가는 수요 둔화 또는 수출 선적 대기·선제 생산 중 하나입니다.",
    },
    "capex_ratio": {
        "themes": {"설비", "공장", "증설"},
        "keywords": ["공장", "증설", "설비", "투자", "준공", "생산능력", "수출전용"],
        "mechanism": "CAPEX 급증은 보통 증설 사이클 진입 신호이며, 회수 시점과 가동률이 관건입니다.",
    },
}

_DIRECTION = {
    "cogs_ratio": "상승", "sga_ratio": "상승", "ar_days": "장기화",
    "inventory_days": "장기화", "payable_days": "변화", "capex_ratio": "확대",
    "debt_ratio": "상승", "opm": "하락", "revenue_yoy": "둔화",
    "fcf_margin": "약화", "cfo_margin": "약화", "cash_conversion": "하락",
    "current_ratio": "하락",
}


def _score_context(item: dict, keywords: set[str]) -> tuple[int, list[str]]:
    haystack = f"{item.get('title','')} {item.get('description','')}"
    matched = [k for k in keywords if k in haystack]
    return len(matched), matched


def _rank_evidence(pool: list[dict], keywords: set[str], limit: int = 3) -> list[dict]:
    scored = []
    for item in pool:
        hits, matched = _score_context(item, keywords)
        if hits == 0:
            continue
        scored.append((
            _tier(item.get("evidence_level") or item.get("source")),  # harder evidence first
            -hits,                                                     # more keyword overlap first
            {**item, "matched_keywords": matched},
        ))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in scored[:limit]]


def _driver_for_metric(metric: str, research: dict) -> list[dict]:
    spec = _METRIC_CAUSE.get(metric, {})
    themes = spec.get("themes", set())
    keywords = set(spec.get("keywords", []))
    hits = []
    for driver in research.get("drivers", []):
        text = f"{driver.get('theme','')} {driver.get('fact','')}"
        if driver.get("theme") in themes or any(k in text for k in keywords):
            hits.append(driver)
    return hits


def interpret_signal(item: dict, context_pool: list[dict], research: dict, market: dict | None = None) -> dict:
    """Turn one abnormal scan row into a sourced causal reading.

    Returns the original row plus an ``interpretation`` block: a narrative paragraph,
    ranked cause candidates with evidence tiers, a confidence grade and a falsifier.
    """
    metric = item.get("metric")
    spec = _METRIC_CAUSE.get(metric, {})
    keywords = set(spec.get("keywords", []))
    value = _num(item.get("value"))
    baseline = _num(item.get("baseline"))
    unit = item.get("unit", "")
    direction = _DIRECTION.get(metric, "이탈")

    # Cause candidates, hardest evidence first: research drivers, then primary
    # filings, then reported news, then unverified blogs already attached upstream.
    candidates: list[dict] = []
    for driver in _driver_for_metric(metric, research):
        candidates.append({
            "cause": f"{driver['theme']}: {driver['fact']}",
            "evidence_level": "리서치 추정", "tier": 1,
            "source": driver.get("source", "리서치 참고"), "url": None,
        })
    for ctx in _rank_evidence(context_pool, keywords, limit=3):
        candidates.append({
            "cause": ctx.get("title", ""),
            "evidence_level": _TIER_LABEL[_tier(ctx.get("evidence_level") or ctx.get("source"))],
            "tier": _tier(ctx.get("evidence_level") or ctx.get("source")),
            "source": ctx.get("source", ""), "url": ctx.get("url"),
            "snippet": (ctx.get("description") or "")[:180],
            "matched_keywords": ctx.get("matched_keywords", []),
        })
    candidates.sort(key=lambda c: c.get("tier", 3))

    # Narrative: state the move, the mechanism, the best sourced reading, the residual.
    move = ""
    if value is not None and baseline is not None and unit:
        gap = value - baseline
        move = f"{item['label']}이 {value:.1f}{unit}로 자체 과거 중앙값({baseline:.1f}{unit}) 대비 {gap:+.1f}{unit} {direction}했습니다. "
    mechanism = spec.get("mechanism", "")
    mech_answer = item.get("dart_answer", "")
    if candidates:
        top = candidates[0]
        bridge = (
            f"숫자만으로는 여기서 멈추지만, {top['source']}({top['evidence_level']})는 "
            f"이 움직임을 「{top['cause']}」와 연결합니다. "
        )
        residual = "다만 보도·리서치 정황이므로 다음 분기 세부 자료로 교차확인이 필요합니다."
        confidence = "High" if top.get("tier", 3) <= 1 else ("Medium" if top.get("tier", 3) == 2 else "Low")
    else:
        bridge = "현재 키워드가 매칭된 공시·뉴스·리서치 근거가 없어 사업적 원인을 특정하지 않습니다. "
        residual = "원인을 억지로 만들지 않고, 아래 확인 포인트를 다음 분기 자료로 점검하세요."
        confidence = "Evidence pending"

    narrative = (move + mechanism + " " + bridge + residual).strip()

    watch = _watch_points(metric, item, research)
    return {
        **item,
        "interpretation": {
            "headline": _headline(metric, item, candidates),
            "narrative": narrative,
            "mechanism": mechanism,
            "dart_answer": mech_answer,
            "cause_candidates": candidates,
            "confidence": confidence,
            "watch_points": watch,
            "falsifier": _falsifier(metric),
        },
    }


def _headline(metric: str, item: dict, candidates: list[dict]) -> str:
    if candidates:
        return f"{item['label']} {_DIRECTION.get(metric,'이탈')} — {candidates[0]['cause'][:46]}"
    return f"{item['label']} {_DIRECTION.get(metric,'이탈')} — 근거 대기"


def _watch_points(metric: str, item: dict, research: dict) -> list[str]:
    base = {
        "cogs_ratio": ["판가 인상이 원가 상승을 따라잡는지(스프레드)", "주력 원재료 단가·환율 방향"],
        "sga_ratio": ["광고·판촉비가 매출 성장으로 회수되는지", "신규 진출(법인/채널) 초기비용의 일회성 여부"],
        "opm": ["원가율과 판관비율 중 어느 축이 회복되는지", "해외 이익률이 가격 효과가 아닌 물량으로 개선되는지"],
        "revenue_yoy": ["국내 점유율 하락이 멈추는지", "해외 성장이 판가가 아닌 물량으로 전환되는지"],
        "fcf_margin": ["CAPEX 사이클의 준공·가동 일정 준수 여부", "운전자본 증가가 일시적인지 구조적인지"],
        "cfo_margin": ["매출채권·재고 증가가 다음 분기 되돌려지는지"],
        "cash_conversion": ["이익 대비 현금 전환율의 추세 반전 여부"],
        "ar_days": ["신규 채널 비중 확대에 따른 구조적 장기화인지"],
        "inventory_days": ["재고 증가가 수요 둔화인지 수출 선적 대기인지"],
        "capex_ratio": ["투자 회수기간과 목표 가동률", "투자비·준공일정 추가 변경 여부"],
    }.get(metric, ["다음 분기 동일 계정의 방향 지속 여부"])
    return base + research.get("checkpoints", [])[:1]


def _falsifier(metric: str) -> str:
    return {
        "cogs_ratio": "판가 인상에도 원가율이 추가 상승하면 구조적 원가 압력으로 재분류",
        "sga_ratio": "매출이 늘어도 판관비율이 동반 상승하면 비용 통제 실패로 재분류",
        "opm": "매출·물량이 늘어도 OPM이 회복되지 않으면 구조적 수익성 훼손",
        "revenue_yoy": "해외가 성장해도 국내 점유율 하락이 이를 상쇄하면 성장 가정 하향",
        "fcf_margin": "준공·가동 이후에도 FCF가 음전이면 투자 회수 가정 재검토",
    }.get(metric, "다음 분기 동일 방향이 반복되면 일회성 가정을 구조적 요인으로 재분류")


# ---------------------------------------------------------------------------
# Market-level: the "실적 때문만은 아니다" decomposition.
# ---------------------------------------------------------------------------

def interpret_price_action(
    kpis: pd.DataFrame,
    market: dict,
    ownership: list[dict],
    disclosures: list[dict],
    research: dict,
    news: list[dict],
    blogs: list[dict],
) -> dict:
    """Decompose price weakness into earnings, expectations, flows and catalyst timing.

    Produces an attribution table (each driver weighted by evidence strength) plus a
    plain-language verdict that separates "the business broke" from "the multiple and
    flows re-rated" — the distinction the reference reports make explicitly.
    """
    latest = kpis.iloc[-1]
    rev_yoy = _num(latest.get("revenue_yoy"))
    op_yoy = _num(latest.get("operating_profit_yoy"))
    opm_yoy = _num(latest.get("opm_yoy_pp"))
    ret_3m = _num(market.get("return_3m"))
    ret_1m = _num(market.get("return_1m"))
    drawdown = _num(market.get("drawdown_52w_high"))
    pos_52w = _num(market.get("position_52w"))

    operating_axes = [v for v in (rev_yoy, op_yoy, opm_yoy) if v is not None]
    operating_up = sum(1 for v in operating_axes if v > 0)
    operating_down = sum(1 for v in operating_axes if v < 0)
    price_weak = (ret_3m is not None and ret_3m < -5) or (drawdown is not None and drawdown < -12)

    attribution = []

    # 1) Earnings axis
    if operating_axes:
        if operating_up >= operating_down:
            earn_read = "최근 분기 실적은 훼손보다 개선에 가깝습니다"
            earn_weight = "Low" if price_weak else "Aligned"
        else:
            earn_read = "매출·이익·마진 중 일부가 실제로 약해졌습니다"
            earn_weight = "High"
        bits = []
        if rev_yoy is not None: bits.append(f"매출 {rev_yoy:+.1f}%")
        if op_yoy is not None: bits.append(f"영업이익 {op_yoy:+.1f}%")
        if opm_yoy is not None: bits.append(f"OPM {opm_yoy:+.1f}%p")
        attribution.append({
            "driver": "실적(펀더멘털)", "weight": earn_weight,
            "reading": earn_read, "evidence": " · ".join(bits) or "데이터 부족",
            "evidence_level": "1차 공시",
        })

    # 2) Expectation / consensus axis
    surprises = [r["value"] for r in research.get("expectations", []) if r.get("metric") == "operating_profit_surprise"]
    if surprises:
        med = float(np.median(surprises))
        if price_weak and med > 0:
            exp_read = f"컨센서스를 {med:+.1f}% 상회하고도 주가가 약하면, 호실적이 이미 가격에 반영됐거나 다음 분기 지속성에 대한 신뢰가 낮은 기대치 조정 구간입니다"
            exp_weight = "High"
        else:
            exp_read = f"실적이 컨센서스 대비 {med:+.1f}% 수준으로 기대 괴리는 제한적입니다"
            exp_weight = "Medium"
        attribution.append({
            "driver": "기대치(멀티플 디레이팅)", "weight": exp_weight,
            "reading": exp_read, "evidence": f"브로커 컨센서스 대비 영업이익 {med:+.1f}%",
            "evidence_level": "리서치 추정",
        })

    # 3) Flow axis — ownership reductions are the clearest "not earnings" cause.
    sellers = [r for r in ownership if (_num(r.get("ratio_change")) or 0) < 0]
    if sellers:
        row = sellers[0]
        rc = _num(row.get("ratio_change"))
        shr = _num(row.get("share_change"))
        flow_read = (
            f"{row.get('reporter') or '주요주주'}가 보유비율을 {rc:+.2f}%p"
            f"{f' ({shr:+,.0f}주)' if shr is not None else ''} 줄였습니다. "
            f"보유목적이 단순투자라면 지배구조가 아닌 단기 수급 부담으로 읽는 것이 맞습니다."
        )
        attribution.append({
            "driver": "수급(기관/대주주)", "weight": "High",
            "reading": flow_read, "evidence": f"DART 대량보유: {row.get('report_type','')} {rc:+.2f}%p",
            "evidence_level": "1차 공시", "url": row.get("url"),
        })
    foreign = _num(market.get("foreign_ownership_change"))
    if foreign is not None:
        attribution.append({
            "driver": "수급(외국인)", "weight": "Medium",
            "reading": f"외국인 보유율이 {foreign:+.2f}%p 변동했습니다. 매도 후 재유입이면 저점 신호로, 추세 이탈이면 부담으로 읽습니다.",
            "evidence": f"외국인 보유율 {foreign:+.2f}%p", "evidence_level": "보도 정황",
        })

    # 4) Catalyst-timing axis — capex/plant disclosures defer the payoff.
    facility = [
        d for d in disclosures
        if any(w in f"{d.get('title','')} {d.get('description','')}" for w in ("시설투자", "공장", "증설", "수출전용"))
    ]
    facility_driver = next((d for d in research.get("drivers", []) if d.get("theme") == "설비"), None)
    if facility or facility_driver:
        ref = facility[0].get("title") if facility else facility_driver.get("fact")
        attribution.append({
            "driver": "성장 옵션·실행 지연", "weight": "Medium",
            "reading": (
                "증설은 중장기 공급능력을 키우지만, 투자비 증가·준공 지연·초기 가동률은 단기 FCF와 멀티플에 부담입니다. "
                "기대가 숫자(해외 매출·가동률)로 확인되기까지 시장은 프리미엄을 유보합니다."
            ),
            "evidence": ref or "DART 시설투자 공시",
            "evidence_level": "1차 공시" if facility else "리서치 추정",
            "url": facility[0].get("url") if facility else None,
        })

    # Verdict — the headline distinction the request asks for.
    high_nonfundamental = [a for a in attribution if a["driver"] != "실적(펀더멘털)" and a["weight"] == "High"]
    if price_weak and operating_up >= operating_down and high_nonfundamental:
        verdict = "실적 때문만은 아닙니다 — 수급·기대치 조정이 더 크게 작용한 구간"
        thesis = (
            "최근 분기 실적은 무너지지 않았는데 주가가 약합니다. 원인은 펀더멘털 훼손보다 "
            f"{', '.join(a['driver'] for a in high_nonfundamental)}에 가깝습니다. "
            "주가가 다시 힘을 받으려면 실적 자체보다 ‘기대를 숫자로 증명’하는 다음 분기 해외 성장과 수급 회복이 필요합니다."
        )
    elif price_weak and operating_down > operating_up:
        verdict = "주가 약세를 수급만으로 설명하기 어려운 펀더멘털 경계 구간"
        thesis = "실적·마진·현금흐름 중 훼손된 축이 먼저 회복돼야 합니다. 수급은 부차적입니다."
    elif not price_weak and operating_up >= operating_down:
        verdict = "실적과 주가 방향이 대체로 일치하는 구간"
        thesis = "다음 판단은 개선 속도의 지속성과 밸류에이션 부담입니다."
    else:
        verdict = "신호가 혼재된 확인 구간"
        thesis = "단일 원인으로 결론내리지 않고 다음 공시를 기다리는 것이 합리적입니다."

    # Numeric framing for the price path (mirrors the blog's "442,500 → 37만원" panel).
    price_frame = {
        "current": _num(market.get("current_price")),
        "high_52w": _num(market.get("high_52w")),
        "low_52w": _num(market.get("low_52w")),
        "drawdown": drawdown, "position_52w": pos_52w,
        "ret_1m": ret_1m, "ret_3m": ret_3m,
        "ret_6m": _num(market.get("return_6m")), "ret_12m": _num(market.get("return_12m")),
    }
    return {
        "verdict": verdict, "thesis": thesis,
        "attribution": attribution, "price_frame": price_frame,
        "price_weak": price_weak, "operating_up": operating_up, "operating_down": operating_down,
    }
