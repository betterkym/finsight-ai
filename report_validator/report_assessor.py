"""Compare a broker report stance with FinSight's objective analysis layer."""
from __future__ import annotations

import math

import pandas as pd

from analyst_workbench.signal_engine import scan_financial_health


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _grade(total: int) -> tuple[str, str]:
    if total >= 75:
        return "A", "신뢰할 만함"
    if total >= 60:
        return "B", "대체로 무난"
    if total >= 45:
        return "C", "주의 필요"
    if total >= 30:
        return "D", "신뢰도 낮음"
    return "E", "낙관 편향 강함"


_AREA_LABELS = {
    "성장": "성장성",
    "수익성": "수익성",
    "현금흐름": "실적의 질",
    "운전자본": "실적의 질",
    "투자": "투자 부담",
    "재무안정성": "재무 안정성",
}

_METRIC_EXPLAINS = {
    "revenue_yoy": (
        "매출 성장률이 약합니다",
        "리포트가 높은 목표가나 긍정적 의견을 내려면 회사가 더 크게 성장한다는 전제가 필요합니다. 그런데 최근 매출 성장률이 과거보다 약하면 목표가의 성장 전제가 흔들립니다.",
    ),
    "opm": (
        "영업이익률이 약합니다",
        "회사가 매출을 올려도 이익으로 남기는 힘이 약해진 상태입니다. 목표가가 이익 개선을 전제로 한다면 이 부분은 신뢰도를 낮추는 근거가 됩니다.",
    ),
    "cogs_ratio": (
        "원가 부담이 커졌습니다",
        "제품을 만들고 파는 데 드는 원가 비중이 높아졌다는 뜻입니다. 매출이 늘어도 이익이 덜 남을 수 있어, 낙관적인 목표가에는 할인 요인입니다.",
    ),
    "sga_ratio": (
        "판매·관리 비용 부담이 커졌습니다",
        "광고, 인건비, 물류비 같은 비용 비중이 높아진 상태입니다. 리포트가 이익 개선을 말한다면 비용 부담이 실제로 줄어드는지가 중요합니다.",
    ),
    "cfo_margin": (
        "영업활동현금흐름(CFO) 마진이 약합니다",
        "손익계산서의 이익보다 실제 영업 현금 유입이 약한 상태입니다. 매출채권 회수 지연이나 재고 증가가 같이 보이면, 리포트의 이익 전망을 그대로 믿기 어렵습니다.",
    ),
    "fcf_margin": (
        "FCF(잉여현금흐름) 마진이 약합니다",
        "영업에서 들어온 현금보다 설비투자(CAPEX)나 운전자본 부담이 커서 회사에 남는 현금이 부족한 상태입니다. 목표가가 장기 현금흐름을 전제로 한다면 큰 차감 요인입니다.",
    ),
    "cash_conversion": (
        "CFO/영업이익 전환율이 약합니다",
        "영업이익이 실제 영업활동현금흐름(CFO)으로 충분히 바뀌지 않는 상태입니다. 매출채권·재고가 같이 늘었다면 실적의 질을 보수적으로 봐야 합니다.",
    ),
    "ar_days": (
        "대금 회수가 늦어지고 있습니다",
        "팔았다고 기록된 매출이 실제 현금으로 들어오는 속도가 느려진다는 뜻입니다. 매출 성장의 질을 낮게 보게 만드는 요인입니다.",
    ),
    "inventory_days": (
        "재고 부담이 커졌습니다",
        "제품이 팔려나가는 속도보다 재고가 쌓이는 신호일 수 있습니다. 수요가 생각보다 약하면 리포트의 성장 전제가 과할 수 있습니다.",
    ),
    "payable_days": (
        "운전자본 구조가 평소와 달라졌습니다",
        "매입채무 지급 기간이 크게 달라진 상태입니다. 일시적일 수 있지만 현금흐름 해석에는 보수적으로 반영합니다.",
    ),
    "capex_ratio": (
        "투자비 부담이 커졌습니다",
        "공장·설비 등에 쓰는 돈이 평소보다 커진 상태입니다. 미래 성장으로 이어질 수 있지만, 당장은 현금흐름과 목표가 신뢰도를 낮출 수 있습니다.",
    ),
    "current_ratio": (
        "단기 지급 여력이 약합니다",
        "단기 부채에 비해 바로 쓸 수 있는 자산이 부족하다는 뜻입니다. 재무 안정성 측면에서 리포트 신뢰도에 부담입니다.",
    ),
    "debt_ratio": (
        "부채 부담이 큽니다",
        "자본 대비 부채가 높은 상태입니다. 금리나 업황 변화에 취약해질 수 있어 낙관적 목표가에는 할인 요인입니다.",
    ),
}

_METRIC_LABELS = {
    "revenue_yoy": "매출 YoY",
    "opm": "OPM",
    "cogs_ratio": "매출원가율",
    "sga_ratio": "판관비율",
    "cfo_margin": "CFO 마진",
    "fcf_margin": "FCF 마진",
    "cash_conversion": "CFO/영업이익",
    "ar_days": "매출채권 회수일수",
    "inventory_days": "재고 회전일수",
    "payable_days": "매입채무 지급일수",
    "capex_ratio": "CAPEX/매출",
    "current_ratio": "유동비율",
    "debt_ratio": "부채비율",
}


def _fmt(value, unit: str = "") -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.1f}{unit}"


def _period(row) -> str:
    try:
        return str(row.get("period") or "")
    except AttributeError:
        return ""


def _metric_snapshot(kpis: pd.DataFrame, metric: str, unit: str = "") -> str:
    if kpis is None or kpis.empty or metric not in kpis:
        return ""
    latest = kpis.iloc[-1]
    parts = [f"최근 {_period(latest)} {_METRIC_LABELS.get(metric, metric)} {_fmt(latest.get(metric), unit)}"]
    if len(kpis) >= 2:
        prev = kpis.iloc[-2]
        prev_val = _num(prev.get(metric))
        latest_val = _num(latest.get(metric))
        if prev_val is not None and latest_val is not None:
            parts.append(f"직전 분기 대비 {latest_val - prev_val:+.1f}{unit}")
    if len(kpis) >= 5:
        yoy = kpis.iloc[-5]
        yoy_val = _num(yoy.get(metric))
        latest_val = _num(latest.get(metric))
        if yoy_val is not None and latest_val is not None:
            parts.append(f"전년 동기 대비 {latest_val - yoy_val:+.1f}{unit}")
    return " / ".join(parts)


def _cash_pressure_read(kpis: pd.DataFrame) -> str:
    if kpis is None or kpis.empty:
        return ""
    latest = kpis.iloc[-1]
    revenue_yoy = _num(latest.get("revenue_yoy")) or 0
    receivables_yoy = _num(latest.get("receivables_yoy"))
    inventory_yoy = _num(latest.get("inventory_yoy"))
    capex_ratio = _num(latest.get("capex_ratio"))
    capex_med = None
    if "capex_ratio" in kpis:
        capex_hist = pd.to_numeric(kpis["capex_ratio"], errors="coerce").dropna().tail(8)
        capex_med = float(capex_hist.median()) if not capex_hist.empty else None

    drivers: list[str] = []
    if receivables_yoy is not None and receivables_yoy > revenue_yoy + 10:
        drivers.append(f"매출채권 증가율({receivables_yoy:+.1f}%)이 매출 성장률({revenue_yoy:+.1f}%)보다 높아 회수 지연 가능성이 있습니다")
    if inventory_yoy is not None and inventory_yoy > revenue_yoy + 10:
        drivers.append(f"재고 증가율({inventory_yoy:+.1f}%)이 매출 성장률({revenue_yoy:+.1f}%)보다 높아 재고 부담 가능성이 있습니다")
    if capex_ratio is not None and (capex_ratio > 8 or (capex_med is not None and capex_ratio > capex_med * 1.35)):
        base = f"CAPEX/매출이 {capex_ratio:.1f}%"
        if capex_med is not None:
            base += f"(최근 중앙값 {capex_med:.1f}%)"
        drivers.append(f"{base}로 높아 FCF(잉여현금흐름)를 누르고 있습니다")
    if not drivers:
        return "DART 본표상 운전자본·CAPEX 중 단일 원인이 강하게 잡히지는 않습니다. 그래서 현금 전환 약화는 신뢰도 차감에는 반영하되, 원인은 추가 근거가 붙을 때까지 단정하지 않습니다."
    return " / ".join(drivers)


def _metric_evidence(item: dict, kpis: pd.DataFrame) -> str:
    metric = item.get("metric")
    unit = item.get("unit", "")
    evidence = item.get("label", "")
    snapshot = _metric_snapshot(kpis, metric, unit)
    if snapshot:
        evidence = snapshot
    value = _num(item.get("value"))
    baseline = _num(item.get("baseline"))
    if value is not None and baseline is not None:
        evidence += f" / 과거 중앙값 {baseline:.1f}{unit}"
    dart_evidence = item.get("dart_evidence") or []
    if dart_evidence:
        evidence += " / " + " · ".join(str(x) for x in dart_evidence[:3])
    if metric in {"cfo_margin", "fcf_margin", "cash_conversion"}:
        cash_read = _cash_pressure_read(kpis)
        if cash_read:
            evidence += " / 원인 후보: " + cash_read
    return evidence.strip()


def _price_action_factor(price_action: dict) -> dict | None:
    if not price_action:
        return None
    high_nonfundamental = [
        item for item in price_action.get("attribution", [])
        if item.get("driver") != "실적(펀더멘털)" and item.get("weight") == "High"
    ]
    if not price_action.get("price_weak") or not high_nonfundamental:
        return None
    top = high_nonfundamental[0]
    driver = top.get("driver", "")
    if "기대치" in driver:
        title = "호재 선반영 가능성"
        reason = "실적이 나쁘지 않은데 주가가 약하면, 리포트의 긍정 논리가 이미 가격에 반영됐거나 다음 분기 지속성을 시장이 낮게 보는 구간일 수 있습니다."
    elif "수급" in driver:
        title = "외국인 매도와 목표가 반영 지연"
        reason = "리포트의 매수 논리가 맞더라도, 외국인·주요주주 매도가 강하면 목표가까지의 회복이 늦어질 수 있습니다."
    else:
        title = "성장 기대가 아직 숫자로 확인되지 않음"
        reason = "증설·해외 성장 같은 기대는 장기적으로 긍정적일 수 있지만, 매출·마진·가동률로 확인되기 전까지 목표가 신뢰도를 온전히 인정하기 어렵습니다."
    return {
        "title": title,
        "impact": "신뢰도 차감",
        "reason": reason,
        "evidence": f"{top.get('driver')}: {top.get('evidence') or top.get('reading')}",
        "points": 3,
        "severity": "Market",
    }


def _report_is_positive(report: dict) -> bool:
    text = f"{report.get('title', '')} {report.get('opinion', '')}"
    return any(word in text for word in ("매수", "상향", "성장", "회복", "견조", "개선", "긍정", "기대"))


def build_alignment_assessment(
    *,
    kpis: pd.DataFrame,
    report: dict,
    distribution: dict,
    timeline: dict,
    reverse: dict,
    price_action: dict | None = None,
) -> dict:
    """Return score impact from the existing analyst engine, in retail language.

    This does not ask users to inspect accounting details. It turns those details
    into report-trust impacts.
    """
    factors: list[dict] = []
    penalty = 0

    def add(title: str, impact: str, reason: str, evidence: str, points: int, severity: str = "Medium") -> None:
        nonlocal penalty
        penalty += max(points, 0)
        factors.append({
            "title": title,
            "impact": impact,
            "reason": reason,
            "evidence": evidence,
            "points": max(points, 0),
            "severity": severity,
        })

    scan = []
    try:
        scan = scan_financial_health(kpis)
    except Exception:
        scan = []
    abnormal = [item for item in scan if item.get("status") == "Abnormal"]
    abnormal.sort(key=lambda item: 0 if item.get("severity") == "High" else 1)

    for item in abnormal[:3]:
        area = _AREA_LABELS.get(item.get("area"), item.get("area", "재무 지표"))
        value = _num(item.get("value"))
        baseline = _num(item.get("baseline"))
        severity = item.get("severity", "Watch")
        points = 6 if severity == "High" else 3
        metric_title, metric_reason = _METRIC_EXPLAINS.get(
            item.get("metric"),
            (
                f"{area} 지표가 평소 범위를 벗어났습니다",
                "회사의 최근 숫자가 과거 정상 범위에서 벗어나 리포트의 목표가 전제를 더 엄격하게 봐야 합니다.",
            ),
        )
        evidence = _metric_evidence(item, kpis)
        add(
            metric_title,
            "신뢰도 차감",
            metric_reason,
            evidence,
            points,
            severity,
        )

    latest = kpis.iloc[-1] if kpis is not None and not kpis.empty else {}
    cfo_margin = _num(latest.get("cfo_margin")) if hasattr(latest, "get") else None
    fcf_margin = _num(latest.get("fcf_margin")) if hasattr(latest, "get") else None
    if fcf_margin is not None and fcf_margin < 0:
        add(
            "현금흐름 불일치",
            "신뢰도 차감",
            "손익 숫자보다 FCF(잉여현금흐름)가 약합니다. 목표가가 높은 리포트일수록 회사에 남는 현금이 부족한 점을 신뢰도에 보수적으로 반영합니다.",
            f"FCF 마진 {fcf_margin:.1f}% / {_cash_pressure_read(kpis)}",
            5,
            "High",
        )
    elif cfo_margin is not None and cfo_margin < 0:
        add(
            "현금흐름 불일치",
            "신뢰도 차감",
            "영업활동에서 현금이 빠져나가는 구간이라, 낙관적인 목표가에는 보수적 할인이 필요합니다.",
            f"CFO 마진 {cfo_margin:.1f}% / {_cash_pressure_read(kpis)}",
            4,
            "High",
        )

    market_factor = _price_action_factor(price_action or {})
    if market_factor:
        add(
            market_factor["title"],
            market_factor["impact"],
            market_factor["reason"],
            market_factor["evidence"],
            market_factor["points"],
            market_factor["severity"],
        )

    if timeline.get("supply_gap"):
        add(
            "발행 후 수급 괴리",
            "신뢰도 차감",
            timeline.get("supply_read") or "리포트는 매수 의견인데 발행 이후 외국인 순매도가 누적됐습니다. 리포트 결론이 시장 행동과 엇갈린 부분입니다.",
            timeline.get("supply_basis") or f"외국인 {timeline.get('foreign_net', 0):+,}억원",
            0,
            "Market",
        )

    if reverse.get("verdict") in {"낙관", "과도한 낙관"}:
        add(
            "목표가 가정 부담",
            "핵심 차감 근거",
            "목표가를 만들기 위해 필요한 이익 성장이 과거 보통 수준보다 높습니다.",
            f"필요 성장률 {reverse.get('need_growth')}% / 과거 중앙값 {reverse.get('median_growth')}%",
            0,
            "High",
        )

    if distribution.get("z", 0) and abs(float(distribution.get("z", 0))) > 0.5:
        add(
            "시장 평균과 거리",
            "보조 차감 근거",
            "목표가가 시장 평균권에서 벗어나 있습니다. 공격적인 리포트라면 더 강한 근거가 필요합니다.",
            f"증권사 목표가 평균 대비 {distribution.get('vs_median_pct', 0):+.1f}%",
            0,
            "Market",
        )

    if _report_is_positive(report) and abnormal:
        add(
            "긍정 의견을 낮춰 봐야 하는 이유",
            "신뢰도 차감",
            "리포트는 긍정적으로 쓰였지만, DART 재무에서는 목표가를 그대로 인정하기 어려운 항목이 같이 확인됐습니다.",
            report.get("title") or report.get("opinion", ""),
            3,
            "Medium",
        )

    penalty = min(penalty, 18)
    if not factors:
        factors.append({
            "title": "객관 분석과 큰 충돌 제한",
            "impact": "차감 없음",
            "reason": "현재 연결된 DART·시장 데이터에서는 리포트 결론을 크게 흔드는 항목이 제한적입니다.",
            "evidence": "FinSight 스캔",
            "points": 0,
            "severity": "Low",
        })

    if penalty >= 12:
        label = "중요 불일치"
    elif penalty >= 6:
        label = "부분 불일치"
    elif penalty > 0:
        label = "경미한 차감"
    else:
        label = "큰 충돌 제한"

    return {
        "label": label,
        "penalty": penalty,
        "factors": factors[:6],
        "scan_count": len(scan),
        "abnormal_count": len(abnormal),
    }


def apply_alignment_to_verdict(verdict: dict, alignment: dict) -> dict:
    """Apply analyst-engine penalties to the existing 3-axis report score."""
    out = dict(verdict)
    base_total = int(out.get("total", 0))
    penalty = int(alignment.get("penalty", 0))
    adjusted = max(0, base_total - penalty)
    grade, label = _grade(adjusted)
    out.update({
        "base_total": base_total,
        "total": adjusted,
        "grade": grade,
        "label": label,
        "stars": round(adjusted / 20),
        "alignment": alignment,
    })
    if penalty:
        lead = alignment.get("factors", [{}])[0]
        out["guide"] = (
            f"{out.get('guide', '')} FinSight 객관 분석 기준으로는 '{lead.get('title', '추가 부담')}' 때문에 "
            f"신뢰도 {penalty}점을 추가 차감했습니다."
        )
    return out
