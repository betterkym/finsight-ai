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
        move = f"{item['label']}이 {value:.1f}{unit}로 과거 중앙값({baseline:.1f}{unit})보다 {gap:+.1f}{unit} {direction}했습니다. "
    mechanism = spec.get("mechanism", "")
    mech_answer = item.get("dart_answer", "")
    if candidates:
        top = candidates[0]
        bridge = f"{top['source']}({top['evidence_level']})는 이 움직임을 「{top['cause']}」와 연결합니다. "
        residual = "보도·리서치 단계의 정황이므로, 아래 절차대로 다음 분기 세부 자료에서 직접 확인하면 확정됩니다."
        confidence = "High" if top.get("tier", 3) <= 1 else ("Medium" if top.get("tier", 3) == 2 else "Low")
    else:
        bridge = "매칭된 공시·뉴스·리서치 근거가 아직 없어 원인을 단정하지 않습니다. "
        residual = "대신 아래 확인 절차로 어디를 어떻게 봐야 하는지 짚었습니다."
        confidence = "Evidence pending"

    narrative = (move + mechanism + " " + bridge + residual).strip()

    return {
        **item,
        "interpretation": {
            "headline": _headline(metric, item, candidates),
            "narrative": narrative,
            "mechanism": mechanism,
            "dart_answer": mech_answer,
            "cause_candidates": candidates,
            "confidence": confidence,
            "verification": _verification_recipes(metric, research),
            "falsifier": _falsifier(metric),
        },
    }


def _headline(metric: str, item: dict, candidates: list[dict]) -> str:
    if candidates:
        return f"{item['label']} {_DIRECTION.get(metric,'이탈')} — {candidates[0]['cause'][:46]}"
    return f"{item['label']} {_DIRECTION.get(metric,'이탈')} — 근거 대기"


# Concrete verification recipes: for each metric, *where* to look (a named DART note,
# disclosure, or IR table — not "the filing"), *what* to compute or compare, and the
# *decision rule* that turns the result into a conclusion. This replaces "please check".
_VERIFY = {
    "cogs_ratio": [
        {"where": "DART 분기보고서 주석 「비용의 성격별 분류」 또는 「매출원가」 명세",
         "what": "원재료비/매출 비율의 QoQ 변화를, 같은 분기 주력 원재료(곡물·원맥·팜유 등) 선물가와 USD/KRW 평균환율 변화와 나란히 비교",
         "rule": "원재료가·환율이 함께 올랐는데 원가율이 그만큼 올랐으면 → 투입가 압력(일시적일 수 있음). 원재료가 안정인데 원가율↑이면 → 제품 믹스 악화·가동률 저하(더 구조적)"},
        {"where": "IR 실적발표 자료·콜의 원가 코멘트, 「매출에누리」 추이",
         "what": "총매출 대비 매출에누리(판촉성 할인) 비율의 변화 확인 — 에누리가 늘면 순매출이 줄어 원가율이 자동 상승",
         "rule": "에누리 확대가 원가율 상승의 상당 부분을 설명하면 → 원가가 아니라 가격·판촉 전략 이슈로 재분류"},
    ],
    "sga_ratio": [
        {"where": "DART 「판매비와관리비」 주석(본 워크북 09 Cost Structure 자동추출표)",
         "what": "항목별 금액의 QoQ·YoY를 뽑아 광고선전비·판촉비·물류비 중 증가 주도 항목을 특정하고, 매출 성장률과 증가율을 비교",
         "rule": "광고·판촉비 증가율이 매출 성장률 안쪽이면 → 회수 가능한 투자. 매출은 정체인데 판관비만 늘면 → 비용 통제 실패"},
        {"where": "최근 1년 시설투자·해외 판매법인 설립 공시(DART), IR 신규 진출 계획",
         "what": "신규 법인/채널 진출 시점과 판관비 증가 시점이 겹치는지 대조",
         "rule": "진출 초기비용과 시점이 일치하면 → 일회성(2~3분기 후 정상화 가정). 진출 없이 증가면 → 구조적 비용"},
    ],
    "opm": [
        {"where": "본 워크북 02 Earnings Bridge(원가율·판관비율 기여 분해)",
         "what": "OPM 변화를 원가율 기여와 판관비율 기여로 분해해 어느 축이 주도했는지 확인",
         "rule": "원가율 주도면 cogs_ratio 절차로, 판관비 주도면 sga_ratio 절차로 한 단계 더 내려가 원인 추적"},
        {"where": "IR 지역별 영업이익률(국내/미주/중국/일본/유럽)",
         "what": "해외 이익률 개선이 판가 인상 효과인지 물량 증가에 따른 고정비 분산인지 구분",
         "rule": "물량 동반 없이 판가만으로 개선됐으면 → 다음 분기 지속성 의심"},
    ],
    "revenue_yoy": [
        {"where": "DART 사업보고서 「매출 실적」(지역별·제품별), IR 지역별 매출표",
         "what": "지역별 매출 YoY를 분해하고, 국내는 3사(농심·삼양·오뚜기) 합산 성장률 대비 점유율 변화로, 해외는 물량 vs 판가로 분해",
         "rule": "성장이 판가·환율 효과면 → 지속성 의문(보수). 물량·신규 지역 기여면 → 견조"},
        {"where": "본 워크북 08 Revenue Build의 점유율 기여 행",
         "what": "점유율 기여(%p)가 (+)인지 (−)인지 확인",
         "rule": "점유율 기여가 음수면 산업 성장에 무임승차 중 → 경쟁 심화 신호"},
    ],
    "fcf_margin": [
        {"where": "DART 현금흐름표 투자활동 + 「유형자산」 주석 + 신규 시설투자 공시",
         "what": "CAPEX/매출을 과거 3년 평균과 비교하고, 증설 공시의 투자금액·완공예정일·자기자본 대비 비율을 확인",
         "rule": "증설 사이클 진입이면 → 준공·가동 전까지 FCF 압박은 정상(회수 시점이 관건). 증설 없이 FCF 악화면 → 운전자본 문제(cfo_margin 절차로)"},
    ],
    "cfo_margin": [
        {"where": "DART 현금흐름표 「영업활동」 운전자본 증감 + 매출채권·재고 주석",
         "what": "매출채권·재고 증가액을 매출 증가액과 비교(증가율 격차)",
         "rule": "매출채권 증가율이 매출 증가율을 +10%p 이상 초과면 → 회수 지연으로 현금이 묶임. 재고가 초과면 → 과잉생산·수요둔화"},
    ],
    "cash_conversion": [
        {"where": "DART 현금흐름표 + 운전자본 증감 주석",
         "what": "CFO/영업이익 비율의 추세와, 그 하락이 매출채권·재고 증가로 설명되는지 확인",
         "rule": "운전자본 증가로 설명되면 → 다음 분기 되돌림 여부 추적. 설명 안 되면 → 이익의 질(일회성 이익·회계추정) 의심"},
    ],
    "ar_days": [
        {"where": "DART 「매출채권」 주석(연령분석·대손충당금 설정률), IR 채널 구성",
         "what": "회수일수 추세와 대손충당금 설정률을 함께 보고, 해외·직거래·대형유통 비중 확대 여부와 대조",
         "rule": "신규 채널 비중 확대로 결제조건이 길어진 구조면 → 추세 용인. 설정률까지 오르면 → 부실 위험 경고"},
    ],
    "inventory_days": [
        {"where": "DART 「재고자산」 주석(재고자산평가손실), IR 출하·수출 물량",
         "what": "재고 증가를 ① 수요 둔화(출하 감소)와 ② 수출 선적 대기·선제 생산으로 구분하고, 평가손실 인식 여부 확인",
         "rule": "평가손실이 잡히면 → 수요 둔화(경고). 선적 대기면 → 다음 분기 매출로 전환(일시적)"},
    ],
    "capex_ratio": [
        {"where": "신규 시설투자 공시(투자금액·완공일·목적), DART 「유형자산」 주석",
         "what": "투자 목적(수출 대응·증설), 회수기간, 목표 가동률을 공시 원문에서 확인하고 투자비·일정의 정정 이력을 점검",
         "rule": "투자비 증액·완공 지연 정정이 반복되면 → 회수 가정 하향. 일정 준수+가동률 상승이면 → 성장 옵션 유효"},
    ],
    "debt_ratio": [
        {"where": "DART 재무상태표 + 「차입금」 주석(만기·금리 구조)",
         "what": "단기차입금 비중과 1년 내 만기 도래액을 현금성자산으로 커버 가능한지 계산",
         "rule": "단기차입·만기도래액이 현금을 초과하면 → 차환 리스크. 장기·고정금리 위주면 → 부담 제한적"},
    ],
    "current_ratio": [
        {"where": "DART 재무상태표 유동자산·유동부채 구성",
         "what": "유동비율 하락이 현금 감소 때문인지 단기차입·매입채무 증가 때문인지 분해",
         "rule": "재고·매출채권은 늘었는데 현금이 줄었으면 → 운전자본에 현금이 묶인 것(cfo_margin 절차로)"},
    ],
}


def _verification_recipes(metric: str, research: dict) -> list[dict]:
    recipes = _VERIFY.get(metric, [{
        "where": "DART 해당 계정 주석과 직전 분기 동일 항목",
        "what": "다음 분기 동일 계정의 방향이 지속되는지 추적",
        "rule": "같은 방향이 2분기 이상 반복되면 → 일회성이 아니라 구조적 요인으로 재분류",
    }])
    return [dict(r) for r in recipes]


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
            earn_read = "최근 분기 실적은 훼손이 아니라 개선 쪽입니다"
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

    # 3) Flow axis — the *largest* ownership reduction is the clearest "not earnings"
    #    cause; a trivial -0.04%p change is noise, not a story.
    sellers = sorted(
        (r for r in ownership if (_num(r.get("ratio_change")) or 0) < -0.3),
        key=lambda r: _num(r.get("ratio_change")) or 0,
    )
    if sellers:
        row = sellers[0]
        rc = _num(row.get("ratio_change"))
        shr = _num(row.get("share_change"))
        flow_read = (
            f"{row.get('reporter') or '주요주주'}의 보유비율이 {rc:+.2f}%p"
            f"{f' ({shr:+,.0f}주)' if shr is not None else ''} 줄었습니다. "
            f"보유목적이 단순투자라면 지배구조 이슈가 아니라 단기 수급 부담으로 읽어야 합니다."
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
        ref = (facility[0].get("title", "").strip() if facility else facility_driver.get("fact"))
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
            "최근 분기 실적은 무너지지 않았는데 주가가 약합니다. 약세를 끌어내린 축은 펀더멘털이 아니라 "
            f"{', '.join(a['driver'] for a in high_nonfundamental)}입니다. "
            "주가가 다시 오르려면 실적 자체보다 다음 분기 해외 성장과 수급 회복이 숫자로 확인돼야 합니다."
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
