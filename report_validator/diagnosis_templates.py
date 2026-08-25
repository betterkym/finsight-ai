"""Narrative templates for FinSight judgement coaching.

The app should not only label a trade pattern. It should reconstruct the
practical order of checks a user should have followed at the decision moment.
"""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime


def _plain(value) -> str:
    return str(value or "").strip()


def _fmt_pct(value) -> str:
    try:
        if value is None:
            return "확인 제한"
        number = float(value)
        return f"{number:+.1f}%"
    except Exception:
        return "확인 제한"


def _fmt_won(value) -> str:
    try:
        if value is None:
            return "확인 제한"
        return f"{float(value):,.0f}원"
    except Exception:
        return "확인 제한"


def _num(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _clip(text: str, limit: int = 220) -> str:
    text = " ".join(_plain(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _count_keywords(text: str, words: list[str]) -> list[str]:
    source = _plain(text)
    return [word for word in words if word in source]


def _claim_profile(thesis: str, source_material: str) -> dict:
    text = f"{thesis}\n{source_material}"
    uncertainty = _count_keywords(text, ["모르겠", "애매", "불확실", "이슈", "변동", "리스크", "불안", "단기", "복잡", "많아서"])
    conviction = _count_keywords(text, ["확실", "무조건", "간다", "상한가", "급등", "목표가", "저평가", "호재", "반등"])
    downside = _count_keywords(text, ["위험", "악재", "하락", "빠질", "손절", "매도", "불안"])
    if uncertainty and not conviction:
        return {
            "type": "불확실성 인식형",
            "read": (
                "이 문장은 강한 매수 근거가 아니라, 사용자가 이미 단기 방향을 확신하지 못하고 있었다는 신호입니다. "
                "따라서 이 주장은 '사야 한다'의 근거가 아니라, 비중·보유기간·손절 기준을 보수적으로 잡아야 한다는 리스크 신호로 해석해야 합니다."
            ),
            "keywords": uncertainty,
        }
    if conviction and uncertainty:
        return {
            "type": "혼합 주장형",
            "read": (
                "입력 문장 안에 기대와 불확실성이 같이 있습니다. 이런 경우 기대 문장만 골라 믿으면 안 되고, "
                "불확실성 문장을 더 높은 우선순위로 올려서 조건부 판단으로 바꿔야 합니다."
            ),
            "keywords": conviction + uncertainty,
        }
    if conviction:
        return {
            "type": "확신 주장형",
            "read": (
                "입력 문장은 상승 기대를 비교적 강하게 담고 있습니다. 이 경우 서비스는 그 기대가 사실인지보다, "
                "그 기대가 이미 가격·거래량·수급에 반영됐는지를 먼저 검증해야 합니다."
            ),
            "keywords": conviction,
        }
    if downside:
        return {
            "type": "방어 판단형",
            "read": (
                "입력 문장은 상승 기대보다 위험 회피 쪽에 가깝습니다. 이 경우 가격 하락 자체보다 "
                "실제로 근거가 훼손됐는지, 아니면 단기 변동을 손실로 과대해석했는지 나눠야 합니다."
            ),
            "keywords": downside,
        }
    return {
        "type": "근거 모호형",
        "read": (
            "입력 문장만으로는 명확한 투자 가설이 보이지 않습니다. 이 경우 결과 해석보다 먼저 "
            "내가 무엇을 믿고 들어갔는지, 무엇이 틀리면 빠져나올지부터 복원해야 합니다."
        ),
        "keywords": [],
    }


def _price_result(prev_5d, day_pos) -> str:
    if prev_5d is None and day_pos is None:
        return "확인 결과, 매수 전 가격 선반영과 당일 체결 위치는 충분히 복원되지 않았습니다. 그래서 가격 축은 낮은 확신도로만 반영했습니다."
    parts = []
    if prev_5d is not None:
        if prev_5d >= 8:
            parts.append(f"매수 전 5거래일 수익률이 {_fmt_pct(prev_5d)}라 가격이 이미 먼저 움직인 쪽입니다")
        elif prev_5d <= -8:
            parts.append(f"매수 전 5거래일 수익률이 {_fmt_pct(prev_5d)}라 낙폭과대 논리는 일부 성립합니다")
        else:
            parts.append(f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}로 강한 선반영 신호는 제한적입니다")
    if day_pos is not None:
        if day_pos >= 70:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점이라 위치 부담이 있습니다")
        elif day_pos <= 30:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점이라 고점 추격 부담은 상대적으로 낮습니다")
        else:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점으로 중간권입니다")
    return "확인 결과, " + " / ".join(parts) + "."


def _volume_result(volume_ratio) -> str:
    if volume_ratio is None:
        return "확인 결과, 매수일 거래량 배율은 충분히 복원되지 않았습니다. 그래서 거래량으로 추격 여부를 단정하지 않았습니다."
    if volume_ratio >= 2:
        return f"확인 결과, 매수일 거래량은 직전 평균의 {volume_ratio:.1f}배였습니다. 이건 관심이 몰린 신호이지만, 고점권에서는 차익실현 물량이 섞였을 가능성도 같이 봐야 합니다."
    if volume_ratio <= 0.8:
        return f"확인 결과, 매수일 거래량은 직전 평균의 {volume_ratio:.1f}배로 약했습니다. 반등이나 시간외 기대를 확정 신호로 쓰기엔 부족합니다."
    return f"확인 결과, 매수일 거래량은 직전 평균의 {volume_ratio:.1f}배로 과열도 침묵도 아닌 중간 수준입니다."


def _flow_result(flow: dict, smart_flow) -> str:
    summary = flow.get("summary") or "확인 제한"
    if smart_flow is None:
        return f"확인 결과, KRX 외국인·기관 수급은 {summary}입니다. 수급이 비어 있으므로 수급을 근거로 한 확신은 낮춰야 합니다."
    if smart_flow < 0:
        return f"확인 결과, KRX 외국인·기관 합산은 {summary}입니다. 가격이나 뉴스가 좋아 보여도 수급은 부담 쪽이라, 사용자의 판단을 그대로 강화해주지 않습니다."
    if smart_flow > 0:
        return f"확인 결과, KRX 외국인·기관 합산은 {summary}입니다. 수급은 판단을 일부 받쳐주지만, 다음 가격이 버티지 못하면 '좋은 수급'은 바로 약해집니다."
    return f"확인 결과, KRX 외국인·기관 합산은 {summary}으로 중립에 가깝습니다."


def _news_result(news: dict | None, disclosure: dict | None) -> str:
    if not news and not disclosure:
        return "확인 결과, 자동 수집된 대표 뉴스와 DART 공시가 충분하지 않습니다. 그래서 뉴스·공시 축은 결론을 강하게 밀어주는 근거로 쓰지 않았습니다."
    parts = []
    if news:
        parts.append(f"대표 뉴스는 '{_plain(news.get('title'))}'이고 시각은 {_news_time_text(news)}입니다")
    else:
        parts.append("대표 뉴스는 확인 제한입니다")
    if disclosure:
        title = _plain(disclosure.get("title") or disclosure.get("report_nm")) or "공시명 확인 제한"
        date = _plain(disclosure.get("date")) or "공시일 확인 제한"
        parts.append(f"같이 대조한 DART 공시는 '{title}', 공시일 {date}입니다")
    else:
        parts.append("같이 대조할 DART 공시는 충분히 잡히지 않았습니다")
    return "확인 결과, " + " / ".join(parts) + ". 그래서 이 자료는 바로 매수 근거가 아니라, 가격·거래량·수급이 같이 받쳐주는지 확인해야 하는 재료입니다."


def _news_datetime(item: dict) -> dt.datetime | None:
    raw = _plain(item.get("date"))
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def _news_time_text(item: dict) -> str:
    parsed = _news_datetime(item)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M")
    raw = _plain(item.get("date"))
    return raw or "시각 확인 제한"


def _decision_datetime(result: dict) -> str:
    date = _plain(result.get("buy_ymd")) or "매수일 확인 제한"
    time = _plain(result.get("buy_time"))
    return f"{date} {time}" if time else date


def _first_news(result: dict) -> dict | None:
    items = result.get("news_items") or []
    return items[0] if items else None


def _first_disclosure(result: dict) -> dict | None:
    items = result.get("disclosure_items") or []
    return items[0] if items else None


def _flow_intro(result: dict) -> str:
    company = result.get("company") or {}
    reasons = result.get("buy_reasons") or []
    reason_text = ", ".join(reasons) if reasons else "근거 미입력"
    return (
        f"입력된 판단 시점은 {_decision_datetime(result)}입니다. "
        f"이때 {_plain(company.get('name')) or '이 종목'}을 {_fmt_won(result.get('buy_price'))} 근처에서 보면서 "
        f"붙잡은 근거는 {reason_text}였습니다. 여기서 바로 결론을 내리면 안 되고, "
        "그 근거가 새 정보인지, 이미 가격에 반영된 정보인지, 내 투자기간에 맞는 근거인지부터 분리했어야 합니다."
    )


def build_integrated_coaching_report(result: dict) -> dict:
    """Turn separate evidence axes into one judgement-coaching storyline."""
    company = result.get("company") or {}
    metrics = result.get("metrics") or {}
    flow = result.get("flow_read") or {}
    top = result.get("top_label") or {}
    data_quality = result.get("data_quality") or {}
    reasons = result.get("buy_reasons") or []
    news = _first_news(result)
    disclosure = _first_disclosure(result)

    thesis = _plain(result.get("user_thesis"))
    source_material = _plain(result.get("source_material"))
    target_price = _num(result.get("expected_target_price"))
    stop_loss = _num(result.get("stop_loss_price"))
    position_weight = _num(result.get("position_weight_pct"))
    max_loss_pct = _num(result.get("max_loss_pct"))
    capital_pressure = _plain(result.get("capital_pressure"))
    buy_price = _num(result.get("buy_price"))
    leverage = _plain(result.get("leverage"))
    horizon = _plain(result.get("horizon"))
    prev_5d = _num(metrics.get("prev_5d_return"))
    volume_ratio = _num(metrics.get("volume_ratio"))
    day_pos = _num(metrics.get("day_position_pct"))
    smart_flow = _num(flow.get("smart"))
    post_return = _num(metrics.get("post_return"))
    medium_horizon = horizon in ("1개월 이내", "중장기")
    low_capital_pressure = capital_pressure in ("", "여유자금")
    low_weight = position_weight is None or position_weight <= 20
    levered = leverage in ("미수 사용", "신용 사용", "미수/신용 둘 다")
    within_loss_budget = (
        post_return is not None and max_loss_pct is not None and post_return < 0 and abs(post_return) <= max_loss_pct
    )

    hype_words = _count_keywords(
        f"{thesis}\n{source_material}",
        ["무조건", "상한가", "대박", "세력", "가즈아", "폭등", "쩜상", "인생", "몰빵", "역대급", "확정", "간다"],
    )
    source_words = _count_keywords(
        f"{thesis}\n{source_material}",
        ["공시", "실적", "수주", "계약", "리포트", "목표가", "시간외", "외국인", "기관", "뉴스", "유튜브", "텔레그램", "종토방"],
    )
    target_return = (target_price / buy_price - 1) * 100 if target_price and buy_price else None
    stop_risk = (stop_loss / buy_price - 1) * 100 if stop_loss and buy_price else None
    claim_profile = _claim_profile(thesis, source_material)
    price_result = _price_result(prev_5d, day_pos)
    volume_result = _volume_result(volume_ratio)
    flow_result = _flow_result(flow, smart_flow)
    news_result = _news_result(news, disclosure)

    assumed_claim = thesis or (
        "사용자가 명시한 주장은 없습니다. 따라서 이번 결과는 입력한 근거 유형과 시장 데이터로 추정한 판단 구조입니다."
    )
    if source_material:
        material_read = (
            f"붙여넣은 자료에서 먼저 읽어야 할 문장은 '{_clip(source_material, 180)}'입니다. "
            "이 문장은 사실 자체라기보다 사용자가 노출된 내러티브로 취급해야 합니다."
        )
    else:
        material_read = (
            "참고 자료 원문이 없어서 사용자가 실제로 어떤 문장을 믿었는지까지는 복원하지 못했습니다. "
            "다음에는 뉴스 링크, 리포트 문장, 커뮤니티 글을 그대로 붙여야 진단 밀도가 올라갑니다."
        )

    trace = []
    trace.append({
        "title": "사용자가 믿은 문장 해석",
        "body": (
            f"이번 판단의 출발점은 '{assumed_claim}'입니다. 이 문장은 {claim_profile['type']}으로 읽었습니다. "
            f"{claim_profile['read']} "
            f"{material_read} "
            + (
                f"특히 자료 안에 {', '.join(hype_words)} 같은 강한 확신 표현이 있어, 정보보다 분위기에 끌렸을 가능성을 별도로 경계해야 합니다. "
                if hype_words else
                "자료 안에서 과도한 확신 표현은 강하게 잡히지 않았지만, 그래도 주장과 사실을 분리해야 합니다. "
            )
            + (
                f"자료가 건드린 키워드는 {', '.join(source_words)}입니다. "
                if source_words else
                "자료 안에서 명확히 분류되는 투자 근거 키워드는 제한적입니다. "
            )
            + "따라서 이 문장은 그대로 결론이 아니라, 아래 데이터 확인을 거쳐 조건부 판단으로 바꿔야 합니다."
        ),
    })

    if news or disclosure:
        trace.append({
            "title": "뉴스와 공시를 실제로 대조한 결과",
            "body": (
                f"{news_result} "
                + (
                    f"뉴스 요약에는 '{_clip(news.get('description'), 150)}'가 보였습니다. "
                    if news and news.get("description") else ""
                )
                + "이 자료는 그 자체로 판단을 밀어주는 근거가 아닙니다. "
                "가격이 이미 먼저 올랐거나 수급이 빠져 있으면 뉴스는 진입 근거가 아니라 늦게 본 설명으로 내려가고, 가격 유지와 수급이 같이 확인될 때만 보조 근거로 올릴 수 있습니다."
            ),
        })
    elif "뉴스/기사" in reasons or "커뮤니티/지인 추천" in reasons:
        trace.append({
            "title": "뉴스/커뮤니티 근거 확인 결과",
            "body": (
                f"{news_result} "
                "따라서 사용자가 본 뉴스나 커뮤니티 글은 사실로 확정하지 않고, 내러티브 노출로만 반영했습니다. "
                "이 경우 결론은 '뉴스가 틀렸다'가 아니라 '뉴스 근거만으로는 포지션을 키울 수 없다'입니다."
            ),
        })

    trace.append({
        "title": "가격 반응을 확인한 결과",
        "body": (
            f"{price_result} "
            + (
                "그래서 입력한 문장이 불확실성 인식형이었다면, 이 가격 결과는 '확신을 낮춰야 한다'는 사용자의 느낌을 일부 뒷받침합니다."
                if claim_profile["type"] == "불확실성 인식형" and ((prev_5d is not None and abs(prev_5d) >= 5) or (day_pos is not None and day_pos >= 70)) else
                "그래서 가격 축만 놓고는 사용자의 문장을 강하게 반박하거나 확정해주지 않습니다. 다음 축인 거래량과 수급까지 같이 봐야 합니다."
            )
        ),
    })

    trace.append({
        "title": "거래량과 수급까지 확인한 결과",
        "body": (
            f"{volume_result} {flow_result} "
            + (
                "따라서 사용자가 '이슈가 너무 많아 단기 방향은 모르겠다'고 쓴 경우, 이 말은 회피성 문장이 아니라 꽤 중요한 리스크 인식입니다. "
                "이 상태에서는 강한 방향 예측보다 포지션 크기와 확인 조건을 먼저 세우는 쪽이 맞습니다."
                if claim_profile["type"] == "불확실성 인식형" else
                "따라서 사용자의 주장은 거래량과 수급이 같이 확인될 때만 강화됩니다. 한 축만 좋으면 결론은 조건부로 남겨야 합니다."
            )
        ),
    })

    risk_parts = []
    if target_return is not None:
        risk_parts.append(f"사용자가 생각한 목표가는 매수가 대비 {_fmt_pct(target_return)}입니다")
    if stop_risk is not None:
        risk_parts.append(f"손절 기준은 매수가 대비 {_fmt_pct(stop_risk)}입니다")
    if max_loss_pct:
        risk_parts.append(f"감당 가능 손실률은 -{max_loss_pct:.1f}%입니다")
    if position_weight:
        risk_parts.append(f"입력 비중은 {position_weight:.0f}%입니다")
    if capital_pressure:
        risk_parts.append(f"자금 성격은 {capital_pressure}입니다")
    if leverage and leverage != "없음":
        risk_parts.append(f"{leverage} 상태입니다")
    if horizon:
        risk_parts.append(f"투자기간은 {horizon}입니다")
    trace.append({
        "title": "목표가·손절가·비중으로 판단 강도 조정",
        "body": (
            " / ".join(risk_parts) if risk_parts else
            "목표가, 손절가, 비중이 충분히 입력되지 않아 리스크 보상 구조는 제한적으로만 봅니다."
        ) + (
            " 목표가가 멀고 손절 기준이 없으면, 좋은 자료를 봤더라도 판단은 희망회로 쪽으로 기울기 쉽습니다. "
            "특히 미수/신용이나 높은 비중이면 목표가보다 먼저 무효화 조건을 세워야 합니다."
        ),
    })

    if post_return is not None and post_return < 0:
        if medium_horizon and low_capital_pressure and low_weight and not levered and within_loss_budget:
            volatility_read = (
                f"현재 손익 {_fmt_pct(post_return)}는 입력한 감당 가능 손실률 -{max_loss_pct:.1f}% 안에 있습니다. "
                "투자기간도 단타가 아니라면, 이 하락을 곧바로 '내가 당했다'로 해석하면 안 됩니다. "
                "이 경우 핵심 질문은 손실 자체가 아니라, 처음 세운 투자 근거가 훼손됐는지입니다. "
                "수급이 유지되고 공시·실적 전제가 깨지지 않았다면 단기 변동은 관리 대상이지 즉시 실패 판정은 아닙니다."
            )
        elif levered or capital_pressure == "곧 필요한 돈" or not low_weight:
            volatility_read = (
                f"현재 손익 {_fmt_pct(post_return)} 자체보다 더 큰 문제는 시간 압박입니다. "
                f"{leverage if levered else capital_pressure or '높은 비중'} 상태에서는 같은 하락도 버틸 수 있는 시간이 짧습니다. "
                "이 경우 수급이 좋아 보여도 단기 변동을 감당할 구조가 아니면 판단 품질은 낮아집니다."
            )
        else:
            volatility_read = (
                f"현재 손익은 {_fmt_pct(post_return)}입니다. 이 하락이 단순 변동인지 근거 훼손인지는 "
                "가격만으로 판단하면 안 됩니다. 투자기간, 비중, 자금 필요 시점, 수급 유지 여부를 같이 봐야 합니다."
            )
        trace.append({
            "title": "손실을 단기 변동과 근거 훼손으로 분리",
            "body": volatility_read,
        })

    final_read = (
        f"따라서 이번 판단은 '{_plain(top.get('name')) or '판단 패턴 확인 제한'}'으로 재가공됩니다. "
        "중요한 건 각 데이터가 따로 좋다/나쁘다가 아니라, 사용자가 믿은 주장과 데이터의 시간순서가 맞았는지, "
        "그리고 그 변동을 감당할 자금 구조였는지입니다. "
        f"현재 데이터 완성도는 {data_quality.get('score', '확인 제한')}/100이고, "
        f"매수 이후 성과는 {_fmt_pct(post_return)}입니다."
    )

    corrected_thought = (
        "이 상황에서의 정석 사고는 '좋은 말이 보였다'에서 출발하지 않습니다. "
        "먼저 그 말이 언제 처음 공개됐는지, 가격이 이미 반응했는지, 거래량과 수급이 따라왔는지, "
        "내 목표가·손절 기준·자금 성격이 시간축에 맞는지 순서대로 확인해야 합니다. "
        "그 순서를 통과하지 못한 근거는 매수·보유의 메인 근거가 아니라 관찰 후보로 내려야 합니다."
    )

    return {
        "assumed_claim": assumed_claim,
        "material_read": material_read,
        "trace": trace,
        "final_read": final_read,
        "corrected_thought": corrected_thought,
    }


def build_detailed_judgement_flow(result: dict) -> dict:
    """Build a detailed coaching flow based on the data actually present."""
    metrics = result.get("metrics") or {}
    flow = result.get("flow_read") or {}
    top = result.get("top_label") or {}
    reasons = result.get("buy_reasons") or []
    data_quality = result.get("data_quality") or {}
    news = _first_news(result)
    disclosure = _first_disclosure(result)

    prev_5d = metrics.get("prev_5d_return")
    volume_ratio = metrics.get("volume_ratio")
    day_pos = metrics.get("day_position_pct")
    post_return = metrics.get("post_return")
    smart_flow = flow.get("smart")
    after_hours = "시간외 상승" in reasons
    news_like = any(reason in reasons for reason in ("뉴스/기사", "공시/실적", "커뮤니티/지인 추천"))
    report_like = "증권사 리포트" in reasons

    steps: list[dict] = []

    if news_like or news:
        if news:
            title = _plain(news.get("title")) or "제목 확인 제한"
            description = _plain(news.get("description"))
            query = _plain(news.get("query"))
            steps.append({
                "title": "1. 먼저 뉴스가 정말 새 정보인지 의심했어야 합니다.",
                "body": (
                    f"그 시점에 네이버 뉴스에서 먼저 확인했어야 할 항목은 '{title}'입니다. "
                    f"검색어는 '{query or '종목 뉴스'}', 기사 시각은 {_news_time_text(news)}로 잡힙니다. "
                    "여기서 바로 '호재니까 사야겠다'로 가면 늦습니다. 기사 제목은 방금 뜬 것처럼 보여도, "
                    "내용 자체는 이미 장중 가격이나 이전 공시로 먼저 반영됐을 수 있습니다. "
                    + (f"기사 요약에 보이는 핵심 문장은 '{description[:160]}'입니다. " if description else "")
                    + "따라서 이 뉴스는 매수 버튼을 누르는 근거가 아니라, 원출처와 가격 선반영 여부를 확인하라는 신호로 봤어야 합니다."
                ),
                "check": "확인 순서: 기사 시각 -> 원출처 공시 여부 -> 뉴스 전 주가 움직임 -> 뉴스 직후 거래량.",
            })
        else:
            steps.append({
                "title": "1. 뉴스 근거를 선택했다면, 먼저 원문과 보도 시각을 찾아야 합니다.",
                "body": (
                    "뉴스를 보고 판단한 거래인데 현재 자동 수집된 뉴스가 충분하지 않습니다. "
                    "이 상태에서 '호재 선반영'이라고 단정하면 안 됩니다. 먼저 네이버 뉴스에서 종목명, 주가, 공시, 시간외 키워드로 "
                    "체결 전후 기사를 다시 확인하고, 가장 먼저 나온 보도가 언제였는지 잡아야 합니다."
                ),
                "check": "뉴스 시각이 없으면 선반영 단정 금지.",
            })

    if disclosure or "공시/실적" in reasons or report_like:
        if disclosure:
            title = _plain(disclosure.get("title")) or _plain(disclosure.get("report_nm")) or "공시명 확인 제한"
            date = _plain(disclosure.get("date")) or "공시일 확인 제한"
            steps.append({
                "title": "2. 그 다음 DART에서 뉴스의 원재료가 이미 공개됐는지 봤어야 합니다.",
                "body": (
                    f"DART에서 먼저 대조할 공시는 '{title}'이고 공시일은 {date}입니다. "
                    "만약 뉴스 내용이 이 공시를 다시 기사화한 것이라면, 사용자는 새 정보를 선점한 게 아니라 이미 공개된 재료를 뒤늦게 본 겁니다. "
                    "반대로 공시가 실제로 체결 직전에 처음 나온 것이라면, 그때는 공시 내용의 숫자 영향과 시장 반응을 나눠 봐야 합니다. "
                    "그래서 코치라면 공시 내용을 바로 믿기 전에 이렇게 묻습니다. 이 공시가 매수 시점의 새 근거였나, 아니면 이미 알려진 재료를 내가 뒤늦게 붙잡은 건가. "
                    "전자가 아니면 공시는 진입 근거가 아니라 사후 설명으로 내려야 합니다."
                ),
                "check": "확인 순서: DART 공시일 -> 기사 보도 시각 -> 주가가 먼저 움직였는지.",
            })
        else:
            steps.append({
                "title": "2. 공시·실적 근거라면 DART 원문 확인 전에는 판단을 확정하면 안 됩니다.",
                "body": (
                    "현재 결과에는 DART 원문 매칭이 충분하지 않습니다. 공시나 실적이 근거라면 기사 제목보다 DART 원문이 먼저입니다. "
                    "실적 발표 직후에는 숫자가 좋아도 주가가 빠질 수 있습니다. 기대가 이미 선반영됐거나, 컨센서스 대비 세부 항목이 실망스러웠을 수 있기 때문입니다."
                ),
                "check": "DART 원문이 없으면 재료소멸/실적실망 단정 금지.",
            })

    steps.append({
        "title": "3. 그 다음 가격이 뉴스보다 먼저 움직였는지 확인했어야 합니다.",
        "body": (
            f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}입니다. "
            + (
                "이 수치가 이미 크게 올라 있었다면, 내가 본 뉴스는 상승의 출발점이 아니라 뒤늦게 붙은 설명일 수 있습니다. "
                if prev_5d is not None and prev_5d >= 8 else
                "이 수치만 보면 강한 선반영이라고 단정하긴 어렵지만, 그래도 뉴스 전 가격 반응을 확인하는 순서는 필요합니다. "
                if prev_5d is not None else
                "현재 매수 전 가격 흐름이 충분히 복원되지 않아 선반영 여부는 낮은 확신도로만 봐야 합니다. "
            )
            + (
                f"매수가의 당일 고저점 내 위치는 {float(day_pos):.0f}% 지점입니다. 상단에 가까울수록 '좋은 뉴스'보다 '이미 오른 뒤 따라 산 것'인지 먼저 의심해야 합니다."
                if day_pos is not None else
                "당일 고저점 대비 매수가 위치는 확인이 제한됩니다. 이 값이 없으면 고점 추격 여부를 강하게 말할 수 없습니다."
            )
        ),
        "check": "확인 순서: 5거래일 상승률 -> 당일 고점 대비 위치 -> 전일 고점/저점 돌파 여부.",
    })

    steps.append({
        "title": "4. 거래량이 '매수세'인지 '차익실현 물량'인지 구분했어야 합니다.",
        "body": (
            f"매수일 거래량은 직전 평균 대비 {float(volume_ratio):.1f}배입니다. "
            + (
                "거래량이 이미 크게 터진 상태라면 그 자체는 좋은 신호이면서 동시에 위험 신호입니다. 가격이 고점을 못 넘기는데 거래량만 터졌다면, 신규 매수세보다 먼저 산 쪽의 차익실현 물량이 강했을 수 있습니다."
                if volume_ratio is not None and volume_ratio >= 2 else
                "거래량이 약하면 반등이나 시간외 상승을 확정 신호로 보기 어렵습니다. 다음 정규장 초반에 거래량이 붙는지 확인했어야 합니다."
                if volume_ratio is not None and volume_ratio <= 0.8 else
                "거래량 과열은 제한적이지만, 단기 판단에서는 분봉 기준으로 어느 시간대에 거래가 몰렸는지까지 봐야 합니다."
                if volume_ratio is not None else
                "현재는 거래량 배율을 충분히 계산하지 못했습니다. 이 경우 뉴스나 시간외 근거를 강하게 믿으면 안 됩니다."
            )
        ),
        "check": "확인 순서: 거래량 급증 -> 가격 고점 돌파 여부 -> 거래량 이후 가격 유지력.",
    })

    steps.append({
        "title": "5. 외국인·기관이 같이 따라왔는지 확인했어야 합니다.",
        "body": (
            f"매수 이후 KRX 기준 외국인·기관 합산 흐름은 {flow.get('summary') or '확인 제한'}입니다. "
            + (
                "합산 수급이 매도 쪽이면, 가격 반등이나 뉴스보다 수급 이탈을 먼저 봐야 합니다. 이 경우 '나만 늦게 들어간 건가?'라는 질문이 맞습니다."
                if smart_flow is not None and smart_flow < 0 else
                "합산 수급이 매수 쪽이면 최소한 수급만 놓고 보면 완전히 역행한 거래는 아닙니다. 다만 이것만으로 단기 상승을 확정할 수는 없습니다."
                if smart_flow is not None and smart_flow > 0 else
                "수급이 확인되지 않으면 '기관·외인이 받쳐준다'는 식의 해석은 쓰면 안 됩니다."
            )
        ),
        "check": "확인 순서: 외국인 -> 기관 -> 금융투자/투신/연기금 세부 주체 -> 가격 반응.",
    })

    if after_hours:
        steps.append({
            "title": "6. 시간외 상승은 결론이 아니라 다음날 확인할 숙제입니다.",
            "body": (
                "시간외 상승을 보고 판단한 경우, 가장 먼저 봐야 할 것은 상승률이 아니라 거래량과 호가 두께입니다. "
                "오후 6시 이후에 뉴스가 보였고 시간외가 움직였다면, '내일 오르겠다'가 아니라 '왜 정규장에는 반응하지 않았지?'를 먼저 물어야 합니다. "
                "정규장에서 이미 약했는데 시간외만 오른 경우라면 다음날 9시 15분~30분 사이에 거래량이 붙으면서 가격을 유지하는지 확인해야 합니다. "
                "현재 KIS 시간외 거래량과 분봉이 없으므로 이 축은 확신도를 낮춰야 합니다."
            ),
            "check": "확인 순서: 시간외 거래량 -> 호가 두께 -> 다음 정규장 9:15~9:30 유지력.",
        })

    if report_like:
        steps.append({
            "title": "7. 리포트는 목표가가 아니라 시간축부터 맞춰야 합니다.",
            "body": (
                "증권사 리포트를 근거로 봤다면, 먼저 그 리포트의 시간축을 내 판단과 맞춰야 합니다. "
                "내일 팔지 말지, 시간외에서 들어갈지 같은 판단에는 리포트 목표가보다 가격·거래량·수급이 먼저입니다. "
                "리포트는 이 종목을 중기적으로 계속 추적할 논리가 남았는지 확인하는 보조 근거로 내려와야 합니다."
            ),
            "check": "확인 순서: 내 투자기간 -> 리포트 발행일 -> 목표가 반영률 -> 발행 이후 공시/수급 변화.",
        })

    closing = (
        f"그래서 이번 판단은 '{_plain(top.get('name')) or '패턴 확인 제한'}' 가능성이 높게 나온 겁니다. "
        "다만 이 결론은 맞히기 놀이가 아니라, 다음에 같은 상황이 왔을 때 멈춰서 확인할 순서를 만드는 용도입니다. "
        f"현재 데이터 완성도는 {data_quality.get('score', '확인 제한')}/100이고, "
        f"매수 이후 수익률은 {_fmt_pct(post_return)}입니다."
    )

    return {
        "intro": _flow_intro(result),
        "steps": steps,
        "closing": closing,
    }
