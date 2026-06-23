"""Rule-based margin decomposition and continuous financial anomaly detection."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _v(row: pd.Series, key: str) -> float | None:
    value = row.get(key)
    return None if value is None or pd.isna(value) else float(value)


def _up(value: float | None, threshold: float = 0.5) -> bool:
    return value is not None and value > threshold


def _down(value: float | None, threshold: float = 0.5) -> bool:
    return value is not None and value < -threshold


def classify_margin_pattern(current: pd.Series, previous: pd.Series) -> dict:
    """Apply one of the 15 proposal rules to a quarter-on-quarter comparison."""
    revenue_change = _v(current, "revenue_qoq")
    opm_change = _v(current, "opm_qoq_pp")
    cogs_change = _v(current, "cogs_ratio_qoq_pp")
    sga_change = _v(current, "sga_ratio_qoq_pp")
    cfo_change = _v(current, "cfo_qoq")
    fcf_change = _v(current, "fcf_qoq")
    net_change = _v(current, "net_income_qoq")
    inv_change = _v(current, "inventory_qoq")
    rec_change = _v(current, "receivables_qoq")
    capex_change = None
    if _v(previous, "capex") not in (None, 0) and _v(current, "capex") is not None:
        capex_change = (abs(_v(current, "capex")) / abs(_v(previous, "capex")) - 1) * 100

    title, comment, severity = "안정적 수익 구조", "매출·OPM·CFO가 모두 안정 범위에 있습니다.", "Stable"
    if _up(revenue_change) and _down(opm_change) and _up(cogs_change) and _up(sga_change):
        title, comment, severity = "복합 비용 부담", "원가율과 판관비율이 함께 상승해 매출 성장을 상쇄했습니다.", "High"
    elif _up(revenue_change) and _down(opm_change) and _up(cogs_change):
        title, comment, severity = "원가 부담", f"원가율 {cogs_change:+.1f}%p가 OPM 하락의 주요 기여 요인입니다.", "High"
    elif _up(revenue_change) and _down(opm_change) and _up(sga_change):
        title, comment, severity = "판관비 부담", f"판관비율 {sga_change:+.1f}%p가 OPM 하락의 주요 기여 요인입니다.", "High"
    elif _up(revenue_change) and _up(opm_change):
        title, comment = "레버리지 효과", "외형 성장과 수익성이 동반 개선됐습니다. 고정비 레버리지 또는 비용 통제 여부를 확인하세요."
    elif _down(revenue_change) and abs(opm_change or 0) <= 0.5:
        title, comment, severity = "마진 방어", "매출 감소에도 수익성을 유지했습니다. 원가 절감의 지속 가능성을 확인하세요.", "Watch"
    elif _down(revenue_change) and _down(opm_change):
        title, comment, severity = "디레버리지", "매출 감소와 OPM 하락이 동시에 나타나 고정비 부담 가능성이 있습니다.", "High"
    elif abs(revenue_change or 0) <= 0.5 and _down(opm_change):
        title, comment, severity = "비용 구조 악화", "매출 정체 구간에서 원가 또는 판관비 부담이 확대됐습니다.", "High"
    elif _up(net_change) and _down(cfo_change):
        title, comment, severity = "이익의 질 저하", "순이익은 증가했지만 CFO가 감소했습니다. 운전자본 변화를 확인하세요.", "High"
    elif (_v(current, "cfo") or 0) > 0 and _up(capex_change, 30):
        title, comment, severity = "투자 부담", "영업현금은 양호하지만 CAPEX 증가로 FCF 부담이 커졌습니다.", "Watch"
    elif _up(revenue_change) and inv_change is not None and inv_change > (revenue_change or 0) + 10:
        title, comment, severity = "재고 과잉 가능성", "재고 증가율이 매출 증가율을 크게 웃돕니다. 수요 둔화 여부를 확인하세요.", "High"
    elif _up(revenue_change) and rec_change is not None and rec_change > (revenue_change or 0) + 10:
        title, comment, severity = "현금 회수 지연", "매출채권 증가율이 매출 증가율을 크게 웃돕니다.", "High"
    elif _up(opm_change) and _down(cfo_change):
        title, comment, severity = "낮은 현금 전환", "OPM은 개선됐지만 CFO가 감소했습니다. 재고·매출채권을 함께 확인하세요.", "High"
    elif _up(revenue_change) and _down(fcf_change):
        title, comment, severity = "외형 성장·현금 소진", "매출 성장에도 FCF가 감소했습니다. CAPEX와 운전자본 부담을 분리해 보세요.", "Watch"
    return {"pattern": title, "comment": comment, "severity": severity}


def build_margin_bridge(kpis: pd.DataFrame) -> pd.DataFrame:
    """Decompose OPM change into gross-margin and SG&A contributions."""
    rows = []
    for index in range(1, len(kpis)):
        current, previous = kpis.iloc[index], kpis.iloc[index - 1]
        opm_delta = _v(current, "opm_qoq_pp")
        cogs_delta = _v(current, "cogs_ratio_qoq_pp")
        sga_delta = _v(current, "sga_ratio_qoq_pp")
        pattern = classify_margin_pattern(current, previous)
        recent_opm = kpis.iloc[max(0, index - 3):index + 1]["opm"].dropna()
        if (
            pattern["pattern"] == "안정적 수익 구조"
            and len(recent_opm) == 4
            and recent_opm.std() > 3.0
        ):
            pattern = {
                "pattern": "계절성·비경상 변동",
                "comment": "최근 4분기 OPM 편차가 큽니다. 계절성 또는 일회성 비용 여부를 확인하세요.",
                "severity": "Watch",
            }
        rows.append({
            "period": current["period"],
            "revenue_change_pct": _v(current, "revenue_qoq"),
            "previous_opm": _v(previous, "opm"),
            "cogs_contribution_pp": None if cogs_delta is None else -cogs_delta,
            "sga_contribution_pp": None if sga_delta is None else -sga_delta,
            "other_contribution_pp": None if opm_delta is None or cogs_delta is None or sga_delta is None else opm_delta + cogs_delta + sga_delta,
            "current_opm": _v(current, "opm"),
            "opm_change_pp": opm_delta,
            **pattern,
        })
    return pd.DataFrame(rows)


def _consecutive(values: pd.Series, count: int, predicate) -> bool:
    clean = values.dropna().tail(count)
    return len(clean) == count and all(predicate(value) for value in clean)


def detect_anomalies(kpis: pd.DataFrame) -> list[dict]:
    signals = []
    if len(kpis) < 2:
        return signals
    revenue_growth = kpis["revenue_qoq"]
    if _consecutive(kpis["receivables_qoq"] - revenue_growth, 3, lambda x: x > 0):
        signals.append({"signal": "매출채권 연속 증가", "severity": "High", "comment": "3분기 연속 매출채권 증가율이 매출 증가율을 웃돌았습니다. CFO 약화 가능성을 확인하세요."})
    if _consecutive(kpis["inventory_qoq"] - revenue_growth, 2, lambda x: x > 0):
        signals.append({"signal": "재고 연속 누적", "severity": "High", "comment": "2분기 연속 재고 증가율이 매출 증가율을 웃돌았습니다. 수요 둔화 또는 과잉 생산 가능성이 있습니다."})
    conversion = kpis["cash_conversion"].replace([np.inf, -np.inf], np.nan)
    if len(conversion.dropna().tail(4)) == 4 and all(np.diff(conversion.dropna().tail(4)) < 0):
        signals.append({"signal": "CFO/영업이익 연속 하락", "severity": "High", "comment": "현금 전환율이 3개 구간 연속 하락했습니다. 이익의 질을 재검토하세요."})
    opm = kpis["opm"].dropna().tail(5)
    if len(opm) == 5 and all(np.diff(opm) < 0):
        signals.append({"signal": "OPM 4분기 연속 하락", "severity": "High", "comment": "구조적 수익성 악화 가능성이 있어 DCF 마진 가정 재검토가 필요합니다."})
    if _consecutive(kpis["fcf"], 3, lambda x: x < 0):
        signals.append({"signal": "FCF 3분기 연속 마이너스", "severity": "High", "comment": "현금 소진이 이어지고 있습니다. 투자 일정과 자금 조달 리스크를 확인하세요."})
    return signals


def run_full_analysis(kpis: pd.DataFrame, macro=None) -> dict:
    bridge = build_margin_bridge(kpis)
    return {"margin_bridge": bridge, "anomalies": detect_anomalies(kpis)}


SCAN_SPECS = [
    {"metric": "revenue_yoy", "label": "매출 성장률 YoY", "area": "성장", "unit": "%", "bad": "low", "warn_gap": 10.0, "hard": -5.0, "dcf": "매출 성장률"},
    {"metric": "opm", "label": "영업이익률", "area": "수익성", "unit": "%", "bad": "low", "warn_gap": 2.0, "hard": None, "dcf": "영업이익률"},
    {"metric": "cogs_ratio", "label": "매출원가율", "area": "수익성", "unit": "%", "bad": "high", "warn_gap": 1.5, "hard": None, "dcf": "영업이익률"},
    {"metric": "sga_ratio", "label": "판관비율", "area": "수익성", "unit": "%", "bad": "high", "warn_gap": 1.5, "hard": None, "dcf": "영업이익률"},
    {"metric": "cfo_margin", "label": "CFO 마진", "area": "현금흐름", "unit": "%", "bad": "low", "warn_gap": 3.0, "hard": 0.0, "dcf": "FCFF 전환율"},
    {"metric": "fcf_margin", "label": "FCF 마진", "area": "현금흐름", "unit": "%", "bad": "low", "warn_gap": 3.0, "hard": 0.0, "dcf": "FCFF 전환율"},
    {"metric": "cash_conversion", "label": "CFO/영업이익", "area": "현금흐름", "unit": "%", "bad": "low", "warn_gap": 25.0, "hard": 60.0, "dcf": "FCFF 전환율"},
    {"metric": "ar_days", "label": "매출채권 회수일수", "area": "운전자본", "unit": "일", "bad": "high", "warn_gap": 15.0, "hard": None, "dcf": "FCFF 전환율"},
    {"metric": "inventory_days", "label": "재고 회전일수", "area": "운전자본", "unit": "일", "bad": "high", "warn_gap": 15.0, "hard": None, "dcf": "FCFF 전환율"},
    {"metric": "payable_days", "label": "매입채무 지급일수", "area": "운전자본", "unit": "일", "bad": "high", "warn_gap": 20.0, "hard": None, "dcf": "FCFF 전환율"},
    {"metric": "capex_ratio", "label": "CAPEX/매출", "area": "투자", "unit": "%", "bad": "high", "warn_gap": 3.0, "hard": None, "dcf": "FCFF 전환율"},
    {"metric": "current_ratio", "label": "유동비율", "area": "재무안정성", "unit": "%", "bad": "low", "warn_gap": 25.0, "hard": 100.0, "dcf": "순차입금/WACC"},
    {"metric": "debt_ratio", "label": "부채비율", "area": "재무안정성", "unit": "%", "bad": "high", "warn_gap": 30.0, "hard": 150.0, "dcf": "순차입금/WACC"},
]


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) or not np.isfinite(value) else float(value)


def _root_cause(metric: str, kpis: pd.DataFrame) -> tuple[str, list[str], bool]:
    latest = kpis.iloc[-1]
    evidence: list[str] = []
    external_needed = False
    if metric in {"opm", "cogs_ratio", "sga_ratio"}:
        cogs = _num(latest.get("cogs_ratio_qoq_pp"))
        sga = _num(latest.get("sga_ratio_qoq_pp"))
        if cogs is not None:
            evidence.append(f"원가율 QoQ {cogs:+.1f}%p")
        if sga is not None:
            evidence.append(f"판관비율 QoQ {sga:+.1f}%p")
        if cogs is None and sga is None:
            return "DART 내 원가율·판관비율 분해 계정이 부족합니다.", evidence, True
        if (cogs or 0) <= 0 and (sga or 0) <= 0:
            return "원가율·판관비율 악화가 확인되지 않아 DART 본표만으로 OPM 하락 원인을 설명할 수 없습니다.", evidence, True
        main = "원가율" if max(cogs or 0, 0) >= max(sga or 0, 0) else "판관비율"
        return f"DART 분해상 {main} 변화의 기여가 더 큽니다. 실제 사업 원인은 공시 주석 또는 외부 맥락 확인이 필요합니다.", evidence, True
    if metric in {"cfo_margin", "fcf_margin", "cash_conversion"}:
        ar = _num(latest.get("receivables_yoy"))
        inv = _num(latest.get("inventory_yoy"))
        pay = _num(latest.get("payables_yoy"))
        capex = _num(latest.get("capex_ratio"))
        for label, value in [("매출채권 YoY", ar), ("재고 YoY", inv), ("매입채무 YoY", pay), ("CAPEX/매출", capex)]:
            if value is not None:
                evidence.append(f"{label} {value:+.1f}%" if "YoY" in label else f"{label} {value:.1f}%")
        drivers = []
        revenue_yoy = _num(latest.get("revenue_yoy")) or 0
        if ar is not None and ar > revenue_yoy + 10:
            drivers.append("매출채권 증가")
        if inv is not None and inv > revenue_yoy + 10:
            drivers.append("재고 증가")
        if metric == "fcf_margin" and capex is not None and capex > 8:
            drivers.append("CAPEX 부담")
        answer = ", ".join(drivers) if drivers else "DART 운전자본·CAPEX만으로 단일 원인을 특정하지 못했습니다"
        return answer, evidence, not bool(drivers)
    if metric in {"ar_days", "inventory_days", "payable_days"}:
        revenue_yoy = _num(latest.get("revenue_yoy"))
        related = {
            "ar_days": _num(latest.get("receivables_yoy")),
            "inventory_days": _num(latest.get("inventory_yoy")),
            "payable_days": _num(latest.get("payables_yoy")),
        }[metric]
        if revenue_yoy is not None:
            evidence.append(f"매출 YoY {revenue_yoy:+.1f}%")
        if related is not None:
            evidence.append(f"관련 계정 YoY {related:+.1f}%")
        return "관련 운전자본 계정의 증가 속도를 매출 성장과 비교했습니다. 수요·회수조건·조달조건은 외부 확인이 필요합니다.", evidence, True
    if metric == "capex_ratio":
        evidence.append(f"최근 CAPEX/매출 {_num(latest.get('capex_ratio')) or 0:.1f}%")
        return "DART에서 투자 현금유출 규모는 확인되나 투자 목적·회수기간은 공시 원문 확인이 필요합니다.", evidence, True
    if metric in {"current_ratio", "debt_ratio"}:
        return "재무상태표의 유동자산·유동부채·총부채·자본으로 산출했습니다.", evidence, False
    return "DART 손익계정만으로 매출 변화의 사업 원인을 특정할 수 없습니다.", evidence, True


def scan_financial_health(kpis: pd.DataFrame) -> list[dict]:
    """Scan every core metric against company history; return normal and abnormal rows."""
    if kpis.empty:
        return []
    latest = kpis.iloc[-1]
    rows = []
    for spec in SCAN_SPECS:
        value = _num(latest.get(spec["metric"]))
        history = pd.to_numeric(kpis.iloc[:-1].get(spec["metric"], pd.Series(dtype=float)), errors="coerce").dropna().tail(7)
        baseline = float(history.median()) if not history.empty else None
        status, severity, reason = "Normal", "Normal", "자체 과거 정상 범위 내"
        if value is None:
            status, severity, reason = "Needs Review", "Review", "DART 계정 결측"
        else:
            gap = value - baseline if baseline is not None else None
            adverse_gap = (
                gap is not None and ((spec["bad"] == "high" and gap > spec["warn_gap"]) or (spec["bad"] == "low" and gap < -spec["warn_gap"]))
            )
            hard_breach = spec["hard"] is not None and (
                (spec["bad"] == "high" and value > spec["hard"]) or (spec["bad"] == "low" and value < spec["hard"])
            )
            if hard_breach:
                status, severity, reason = "Abnormal", "High", "절대 위험 기준 이탈"
            elif adverse_gap:
                status, severity = "Abnormal", "Watch"
                reason = "자체 과거 범위 이탈(방향 해석 필요)" if spec["metric"] == "payable_days" else "자체 과거 중앙값 대비 유의한 악화"
        answer, evidence, external_needed = _root_cause(spec["metric"], kpis) if status == "Abnormal" else ("—", [], False)
        rows.append({
            **spec,
            "period": latest.get("period"), "value": value, "baseline": baseline,
            "deviation": None if value is None or baseline is None else value - baseline,
            "status": status, "severity": severity, "reason": reason,
            "question": f"{spec['label']}이 왜 자체 과거 범위를 벗어났는가?" if status == "Abnormal" else "—",
            "dart_answer": answer, "dart_evidence": evidence,
            "external_needed": external_needed,
            "peer_value": None, "peer_gap": None, "peer_verdict": "비교 전",
            "context": [],
        })
    return rows


def attach_peer_evidence(scan: list[dict], peer_kpis: dict[str, pd.DataFrame]) -> list[dict]:
    enriched = []
    spec_map = {item["metric"]: item for item in SCAN_SPECS}
    for item in scan:
        peer_values = []
        for frame in peer_kpis.values():
            if not frame.empty and item["metric"] in frame:
                value = _num(frame.iloc[-1].get(item["metric"]))
                if value is not None:
                    peer_values.append(value)
        row = dict(item)
        if peer_values and item["value"] is not None:
            peer_median = float(np.median(peer_values))
            gap = item["value"] - peer_median
            bad = spec_map[item["metric"]]["bad"]
            company_specific = (bad == "high" and gap > 0) or (bad == "low" and gap < 0)
            row.update({
                "peer_value": peer_median, "peer_gap": gap,
                "peer_verdict": "기업 고유 이슈 가능성" if company_specific else "업종 공통/상대 우위",
            })
        enriched.append(row)
    return enriched


CONTEXT_KEYWORDS = {
    "성장": ["수출", "매출", "판매", "신제품", "해외", "중국", "미국", "수요"],
    "수익성": ["원가", "가격", "원재료", "마케팅", "광고", "물류", "환율", "판관비"],
    "현금흐름": ["재고", "채권", "현금", "투자", "공장", "증설", "공급망"],
    "운전자본": ["재고", "채권", "회수", "공급망", "유통", "채널"],
    "투자": ["투자", "공장", "증설", "설비", "생산능력"],
    "재무안정성": ["차입", "사채", "신용", "유동성", "자금조달"],
}


def attach_context(scan: list[dict], disclosures: list[dict], news: list[dict]) -> list[dict]:
    enriched = []
    for item in scan:
        row = dict(item)
        if item["status"] != "Abnormal" or not item["external_needed"]:
            enriched.append(row)
            continue
        keywords = CONTEXT_KEYWORDS.get(item["area"], [])
        matches = []
        for context_item in disclosures + news:
            haystack = f"{context_item.get('title','')} {context_item.get('description','')}"
            matched = [keyword for keyword in keywords if keyword in haystack]
            if matched:
                matches.append({**context_item, "matched_keywords": matched})
        row["context"] = matches[:3]
        enriched.append(row)
    return enriched
