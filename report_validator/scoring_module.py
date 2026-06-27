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
        deductions.append(f"외국인 {timeline['foreign_net']:+}억 순매도(리포트와 반대)")
    if timeline["soak_pct"] > 70:
        base -= 5
        deductions.append(f"상승여력 {timeline['soak_pct']}% 이미 소진")
    base = max(base, 0)
    note = "발행 시점 정합성 양호" if not deductions else " · ".join(deductions)
    return {"score": base, "max": 30, "reason": note}


def score_logic(reverse: dict) -> dict:
    """필요 실적 점수 (40점)."""
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
    weak_candidates.append(("리포트 발행 이후 현실과 벌어진 점", tm["score"] / tm["max"]))
    weak_candidates.append(("목표가에 필요한 실적이 부담스러운 점", lg["score"] / lg["max"]))
    weakest = min(weak_candidates, key=lambda x: x[1])[0] if weak_candidates else "불명확한 점"

    broker = report.get("broker", "이 증권사")
    target = report.get("target_price", 0)

    if total >= 60:
        headline = f"{broker}의 목표가 {target:,}원은 현재 데이터와 크게 충돌하지 않습니다."
        guide = "목표가 편차·발행 이후 괴리·필요 실적에서 큰 차감 요인은 제한적입니다. 목표가를 참고할 수는 있지만, 리포트 결론이 확정됐다는 뜻은 아닙니다."
    elif total >= 45:
        headline = f"{broker}의 목표가 {target:,}원은 주의해서 봐야 합니다."
        guide = f"특히 '{weakest}'이 신뢰도를 낮춥니다. 리포트의 결론보다 근거와 가정이 맞는지 보는 쪽이 안전합니다."
    else:
        headline = f"{broker}의 목표가 {target:,}원은 그대로 믿기 어렵습니다."
        guide = (
            f"핵심 검증에서 약점이 여러 개 드러났고, 특히 '{weakest}'이 두드러집니다. "
            f"리포트의 목표가가 현재 확인된 데이터보다 낙관적일 가능성이 큽니다."
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
        "weakest": weakest,
        "disclaimer": "이 점수는 '리포트의 신뢰도'에 대한 평가이며, 종목 매수·매도 추천이 아닙니다.",
    }
