"""모듈4 — 리포트 신뢰도 점수화 + 평가 의견 생성.

핵심 검증 결과를 100점 만점으로 종합하고, '종목'이 아니라 '리포트'에 대한
평가 의견을 문장으로 만든다. 종목 추천(사세요/파세요)은 하지 않는다.
오직 '이 리포트를 얼마나 믿어도 되는가'만 판정한다.

가중치 설계 근거:
  필요 실적 40 — 목표가가 요구하는 실적 현실성이 가장 본질적.
  목표가 편차 30 — 평균에서 크게 벗어난 목표가인지 확인.
  발행 이후 괴리 30 — 발행 후 전제가 낡았거나 수급과 어긋났는지 확인.
"""
from __future__ import annotations


def score_space(distribution: dict) -> dict:
    """목표가 편차 점수 (30점).

    비교할 목표가 분포가 없으면(insufficient) 0점이 아니라 '미집계'로 처리한다.
    분포 데이터가 없다는 것이 리포트의 흠은 아니므로 점수를 깎지 않는다.
    """
    if not distribution or distribution.get("insufficient"):
        return {
            "score": None,
            "max": 30,
            "reason": "비교할 다른 증권사 목표가 없음 — 미집계",
            "uncounted": True,
        }
    z = abs(distribution["z"])
    top = distribution["top_pct"]
    if z <= 0.5:
        base, note = 30, "증권사 목표가 평균권 — 혼자 튀지 않음"
    elif z <= 1.0:
        base, note = 22, "평균에서 다소 벗어남"
    elif z <= 1.5:
        base, note = 14, f"상위 {top}% — 다소 높은 축"
    else:
        base, note = 7, f"상위 {top}% — 극단적으로 높음(낙관 편향 신호)"
    return {"score": base, "max": 30, "reason": note, "z": round(distribution["z"], 2)}


def score_time(timeline: dict) -> dict:
    """발행 이후 괴리 점수 (30점)."""
    base = 30
    deductions = []
    if timeline["elapsed"] > 90:
        base -= 10
        deductions.append(f"발행 {timeline['elapsed']}일 경과(많이 낡음)")
    elif timeline["elapsed"] > 60:
        base -= 6
        deductions.append(f"발행 {timeline['elapsed']}일 경과")
    elif timeline["elapsed"] > 30:
        base -= 3
        deductions.append(f"발행 {timeline['elapsed']}일 경과")
    if timeline["supply_gap"]:
        base -= 10
        deductions.append(timeline.get("supply_basis") or f"외국인 {timeline['foreign_net']:+}억원 순매도")
    if timeline["soak_pct"] > 70:
        base -= 5
        deductions.append(f"상승여력 {timeline['soak_pct']}% 이미 소진")
    base = max(base, 0)
    note = "발행 시점 정합성 양호" if not deductions else " · ".join(deductions)
    return {"score": base, "max": 30, "reason": note}


def score_logic(reverse: dict) -> dict:
    """필요 실적 점수 (40점)."""
    if reverse.get("verdict") == "확인 필요":
        return {
            "score": None,
            "max": 40,
            "reason": reverse.get("limited_reason") or "필요 실적 계산에 필요한 데이터가 부족해 미집계",
            "uncounted": True,
        }
    mult = reverse["multiple"] if reverse["multiple"] else 1
    verdict = reverse["verdict"]
    if verdict == "현실적":
        base, note = 40, "목표가 가정이 과거 실적으로 충분히 달성 가능"
    elif verdict == "낙관":
        if mult <= 2:
            base, note = 28, f"필요 성장이 보통 해의 {mult}배 — 다소 낙관"
        elif mult <= 4:
            base, note = 18, f"필요 성장이 보통 해의 {mult}배 — 낙관적"
        else:
            base, note = 10, f"필요 성장이 보통 해의 {mult}배 — 상당히 낙관적"
    else:  # 과도한 낙관
        base, note = 4, f"필요 성장이 과거 최대치마저 초과 — 비현실적"
    if reverse["volatility"] == "매우높음" and verdict in ("낙관", "과도한 낙관"):
        base = max(base - 4, 0)
        note += " (실적 변동성 커 불확실성 가중)"
    return {"score": base, "max": 40, "reason": note}


def grade_of(total: int) -> tuple[str, str]:
    """점수를 등급으로 변환."""
    if total >= 75:
        return "A", "신뢰할 만함"
    if total >= 60:
        return "B", "대체로 무난"
    if total >= 45:
        return "C", "주의 필요"
    if total >= 30:
        return "D", "신뢰도 낮음"
    return "E", "낙관 편향 강함"


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:+.1f}%"


def _eok_flow(value) -> str:
    number = _num(value)
    if number is None:
        return "외국인 수급 N/A"
    direction = "순매수" if number >= 0 else "순매도"
    return f"외국인 {direction} {abs(number):,.0f}억원"


def _judgment_label(total: int, distribution: dict, timeline: dict, reverse: dict) -> str:
    """Translate the score into investor-facing reading guidance, not a buy/sell call."""
    soak = _num(timeline.get("soak_pct"))
    supply_gap = bool(timeline.get("supply_gap"))
    reverse_verdict = reverse.get("verdict")
    z = abs(_num(distribution.get("z")) or 0)

    if total < 45:
        return "리포트 결론을 그대로 믿기 어려움"
    if supply_gap and soak is not None and soak >= 70:
        return "매수 의견은 있지만 지금 따라가기 부담"
    if soak is not None and soak >= 70:
        return "목표가 여력보다 가격 반영을 먼저 봐야 함"
    if supply_gap:
        return "실적보다 시장 반응 확인이 먼저"
    if reverse_verdict in {"낙관", "과도한 낙관"}:
        return "목표가보다 다음 실적 확인이 중요"
    if z >= 1.0:
        return "공격적인 목표가라 근거 확인 필요"
    if total >= 75:
        return "리포트 근거를 비교적 편하게 참고 가능"
    return "참고 가능하지만 핵심 전제는 재확인"


def _evidence_sentences(distribution: dict, timeline: dict, reverse: dict, weakest: str) -> list[str]:
    """Build compact, concrete reasons for the comprehensive verdict."""
    sentences: list[str] = []

    realized = _num(timeline.get("realized"))
    remaining = _num(timeline.get("remaining"))
    soak = _num(timeline.get("soak_pct"))
    elapsed = timeline.get("elapsed")
    if realized is not None and remaining is not None:
        prefix = f"리포트 발행 후 {elapsed}일 기준, " if elapsed is not None else ""
        sentence = f"{prefix}발행 이후 주가는 {_pct(realized)} 움직였고, 목표가까지 남은 여력은 {_pct(remaining)}입니다"
        if soak is not None:
            sentence += f". 발행 당시 기대 상승여력의 {soak:.0f}%가 가격에 반영된 상태입니다"
        sentences.append(sentence + ".")

    if timeline.get("foreign_net") is not None:
        flow = _eok_flow(timeline.get("foreign_net"))
        recent = _num(timeline.get("foreign_recent_5d"))
        if recent is not None:
            sentences.append(f"같은 기간 {flow}이고 최근 5거래일은 {_eok_flow(recent)}이라, 시장 반응이 리포트 방향과 맞는지 따로 봐야 합니다.")
        else:
            sentences.append(f"같은 기간 {flow}라, 리포트 의견과 실제 수급 방향이 같은지 확인해야 합니다.")

    vs_mean = _num(distribution.get("vs_median_pct"))
    if vs_mean is not None:
        sentences.append(f"목표가는 증권사 평균 대비 {_pct(vs_mean)} 위치라, 평균에서 멀수록 더 강한 실적 근거가 필요합니다.")

    if reverse.get("verdict") and reverse.get("verdict") != "확인 필요":
        need = _num(reverse.get("need_growth"))
        median = _num(reverse.get("median_growth"))
        if need is not None and median is not None:
            sentences.append(f"목표가가 성립하려면 EPS가 {_pct(need)} 성장해야 하고, 과거 중앙값은 {_pct(median)}입니다.")
        else:
            sentences.append(f"필요 실적 판정은 '{reverse.get('verdict')}'입니다.")

    if not sentences:
        sentences.append(f"현재 가장 약한 축은 {weakest}입니다.")
    return sentences[:4]


def build_report_verdict(
    distribution: dict, timeline: dict, reverse: dict, report: dict
) -> dict:
    """핵심 검증축을 종합해 리포트 신뢰도 점수 + 평가 의견을 생성한다.

    핵심: '종목'에 대한 의견이 아니라 '리포트'에 대한 평가다.
    """
    sp = score_space(distribution)
    tm = score_time(timeline)
    lg = score_logic(reverse)

    # 미집계 항목(비교 데이터 없음)은 제외하고, 집계된 항목만으로 100점 환산.
    counted = [ax for ax in (sp, tm, lg) if not ax.get("uncounted")]
    raw = sum(ax["score"] for ax in counted if ax["score"] is not None)
    max_possible = sum(ax["max"] for ax in counted if not ax.get("uncounted"))
    total = round(raw / max_possible * 100) if max_possible else 0
    partial = len(counted) < 3  # 일부 축만 집계됨
    grade, label = grade_of(total)
    stars = round(total / 20)

    # ── 평가 의견 문장 (리포트에 대한 평가, 종목 추천 아님) ──
    weak_candidates = []
    if not sp.get("uncounted"):
        weak_candidates.append(("분포에서 혼자 튀는 점", sp["score"] / sp["max"]))
    if not tm.get("uncounted"):
        weak_candidates.append(("리포트 발행 이후 현실과 벌어진 점", tm["score"] / tm["max"]))
    if not lg.get("uncounted"):
        weak_candidates.append(("목표가에 필요한 실적이 부담스러운 점", lg["score"] / lg["max"]))
    weakest = min(weak_candidates, key=lambda x: x[1])[0] if weak_candidates else "불명확한 점"

    broker = report.get("broker", "이 증권사")
    target = report.get("target_price", 0)
    judgment = _judgment_label(total, distribution, timeline, reverse)
    evidence = _evidence_sentences(distribution, timeline, reverse, weakest)

    headline = f"{broker} 목표가 {target:,}원: {judgment}"
    if total >= 75:
        guide = (
            f"신뢰도는 높지만 매수·매도 타이밍을 찍는 결과는 아닙니다. "
            f"{' '.join(evidence)} 따라서 이 리포트는 주요 근거를 참고하되, 현재가 기준 가격 반영 정도는 함께 봐야 합니다."
        )
    elif total >= 60:
        guide = (
            f"리포트 방향은 참고할 수 있지만 그대로 확신하기보다는 핵심 전제를 다시 보는 쪽이 낫습니다. "
            f"{' '.join(evidence)} 그래서 매수 의견 자체보다 현재 가격에서 남은 여력과 다음 실적 확인이 더 중요합니다."
        )
    elif total >= 45:
        guide = (
            f"이 리포트는 결론보다 가정을 할인해서 봐야 합니다. "
            f"{' '.join(evidence)} 특히 {weakest} 때문에 목표가를 현재 시점에서 그대로 받아들이기에는 부담이 있습니다."
        )
    else:
        guide = (
            f"현재 확인되는 데이터만 놓고 보면 이 리포트의 목표가와 투자의견은 보수적으로 봐야 합니다. "
            f"{' '.join(evidence)} 리포트의 긍정 논리가 틀렸다고 단정하는 것은 아니지만, 지금 판단 근거로 그대로 쓰기에는 신뢰도가 낮습니다."
        )

    return {
        "total": total,
        "grade": grade,
        "label": label,
        "stars": stars,
        "partial": partial,
        "axes": {
            "space": {**sp, "title": "① 목표가 편차"},
            "time": {**tm, "title": "② 발행 이후 괴리"},
            "logic": {**lg, "title": "③ 필요 실적"},
        },
        "headline": headline,
        "guide": guide,
        "judgment": judgment,
        "evidence_sentences": evidence,
        "weakest": weakest,
        "disclaimer": "이 점수는 '리포트의 신뢰도'에 대한 평가이며, 종목 매수·매도 추천이 아닙니다.",
    }
