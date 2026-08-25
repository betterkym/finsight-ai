"""Structured judgement-reprocessing layer for FinSight.

This module is not a copywriting layer. It converts the user's own claim and
the collected market data into closed-loop checks:
claim -> verification question -> observed result -> interpretation -> rule.
"""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime


def _plain(value) -> str:
    return str(value or "").strip()


def _num(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _fmt_pct(value) -> str:
    number = _num(value)
    if number is None:
        return "확인 제한"
    return f"{number:+.1f}%"


def _fmt_won(value) -> str:
    number = _num(value)
    if number is None:
        return "확인 제한"
    return f"{number:,.0f}원"


def _fmt_eok(value) -> str:
    number = _num(value)
    if number is None:
        return "확인 제한"
    return f"{number:+,.1f}억원"


def _clip(text: str, limit: int = 170) -> str:
    text = " ".join(_plain(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _matching_words(text: str, words: tuple[str, ...]) -> list[str]:
    return [word for word in words if word in text]


def _first_news(result: dict) -> dict | None:
    items = result.get("news_items") or []
    return items[0] if items else None


def _first_disclosure(result: dict) -> dict | None:
    items = result.get("disclosure_items") or []
    return items[0] if items else None


def _news_datetime(item: dict | None) -> dt.datetime | None:
    if not item:
        return None
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


def _news_time(item: dict | None) -> str:
    parsed = _news_datetime(item)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M")
    raw = _plain((item or {}).get("date"))
    return raw or "시각 확인 제한"


def _decision_time(result: dict) -> str:
    ymd = _plain(result.get("buy_ymd")) or "매수일 확인 제한"
    time = _plain(result.get("buy_time"))
    return f"{ymd} {time}" if time else ymd


def _decision_datetime_obj(result: dict) -> dt.datetime | None:
    ymd = _plain(result.get("buy_ymd"))
    if not ymd:
        return None
    time = _plain(result.get("buy_time")) or "15:30"
    try:
        return dt.datetime.strptime(f"{ymd} {time}", "%Y-%m-%d %H:%M")
    except Exception:
        try:
            return dt.datetime.strptime(ymd, "%Y-%m-%d")
        except Exception:
            return None


def _disclosure_date_obj(item: dict | None) -> dt.date | None:
    if not item:
        return None
    raw = _plain(item.get("date") or item.get("rcept_dt"))
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return dt.datetime.strptime(raw[:10], fmt).date()
        except Exception:
            pass
    return None


def _news_timing_read(news: dict | None, result: dict) -> tuple[str, str]:
    news_dt = _news_datetime(news)
    decision_dt = _decision_datetime_obj(result)
    if not news or not news_dt or not decision_dt:
        return "뉴스와 매수 시각의 선후관계는 확인 제한입니다.", "unknown"
    diff_hours = (news_dt - decision_dt).total_seconds() / 3600
    if diff_hours > 0:
        return (
            f"대표 뉴스 시각은 매수 판단보다 약 {diff_hours:.1f}시간 뒤입니다. 이 뉴스는 매수 당시 근거가 아니라 사후에 붙은 설명으로 봐야 합니다.",
            "after",
        )
    if abs(diff_hours) <= 6:
        return (
            f"대표 뉴스는 매수 전 약 {abs(diff_hours):.1f}시간 안에 나온 가까운 뉴스입니다. 다만 가까운 뉴스라도 가격이 먼저 움직였으면 새 근거가 아니라 확산된 재료일 수 있습니다.",
            "near_before",
        )
    return (
        f"대표 뉴스는 매수보다 약 {abs(diff_hours):.1f}시간 전에 나온 뉴스입니다. 매수 시점에는 이미 시장이 읽을 시간이 있었던 재료로 봐야 합니다.",
        "old_before",
    )


def _disclosure_timing_read(disclosure: dict | None, result: dict) -> tuple[str, str]:
    disclosure_date = _disclosure_date_obj(disclosure)
    decision_dt = _decision_datetime_obj(result)
    if not disclosure or not disclosure_date or not decision_dt:
        return "DART 공시와 매수일의 선후관계는 확인 제한입니다.", "unknown"
    buy_date = decision_dt.date()
    if disclosure_date < buy_date:
        days = (buy_date - disclosure_date).days
        return f"DART 공시는 매수일보다 {days}일 전에 이미 공개된 자료입니다. 매수 시점에는 새 정보보다 기존 재료 재해석에 가깝습니다.", "old"
    if disclosure_date == buy_date:
        return "DART 공시는 매수일과 같은 날 잡힙니다. 같은 날 공시라도 가격이 먼저 반응했는지 확인해야 합니다.", "same_day"
    return "DART 공시는 매수일 이후 자료로 잡힙니다. 이 공시는 매수 당시 판단 근거로 쓰면 안 됩니다.", "after"


def _market_reaction_snapshot(result: dict) -> tuple[list[str], bool, bool, bool]:
    metrics = result.get("metrics") or {}
    flow = result.get("flow_read") or {}
    prev_5d = _num(metrics.get("prev_5d_return"))
    day_pos = _num(metrics.get("day_position_pct"))
    volume_ratio = _num(metrics.get("volume_ratio"))
    smart_flow = _num(flow.get("smart"))
    reads: list[str] = []
    price_burden = False
    volume_burden = False
    flow_burden = False

    if prev_5d is not None:
        if prev_5d >= 8:
            reads.append(f"매수 전 5거래일에 이미 {_fmt_pct(prev_5d)} 올라 재료가 가격에 먼저 묻었을 가능성이 큽니다.")
            price_burden = True
        elif prev_5d <= -8:
            reads.append(f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}라, 뉴스보다 낙폭과대 반등 논리가 더 큰 축일 수 있습니다.")
        else:
            reads.append(f"매수 전 5거래일 흐름은 {_fmt_pct(prev_5d)}로 강한 선반영 신호는 제한적입니다.")
    if day_pos is not None:
        if day_pos >= 70:
            reads.append(f"매수가는 당일 가격 범위의 {day_pos:.0f}% 지점이라 낮은 자리에서 받은 거래는 아닙니다.")
            price_burden = True
        elif day_pos <= 30:
            reads.append(f"매수가는 당일 가격 범위의 {day_pos:.0f}% 지점이라 고점 추격 부담은 낮습니다.")
    if volume_ratio is not None:
        if volume_ratio >= 2:
            reads.append(f"거래량은 직전 평균의 {volume_ratio:.1f}배라 관심이 이미 몰린 상태였습니다.")
            volume_burden = True
        elif volume_ratio <= 0.8:
            reads.append(f"거래량은 직전 평균의 {volume_ratio:.1f}배라 뉴스 반응이 강하게 붙었다고 보기 어렵습니다.")
    if smart_flow is not None:
        if smart_flow < 0:
            reads.append(f"외국인·기관 합산 수급은 {flow.get('summary') or _fmt_eok(smart_flow)}으로, 뉴스 해석을 받쳐주는 쪽이 아닙니다.")
            flow_burden = True
        elif smart_flow > 0:
            reads.append(f"외국인·기관 합산 수급은 {flow.get('summary') or _fmt_eok(smart_flow)}으로, 최소한 수급은 반대로 가지 않았습니다.")
    if not reads:
        reads.append("가격·거래량·수급 반응은 충분히 복원되지 않았습니다.")
    return reads, price_burden, volume_burden, flow_burden


def _claim_profile(thesis: str, source_material: str) -> dict:
    text = f"{thesis}\n{source_material}"
    uncertainty_words = _matching_words(
        text,
        ("모르겠", "애매", "불확실", "이슈", "변동", "리스크", "불안", "단기", "복잡", "많아서", "흔들"),
    )
    conviction_words = _matching_words(
        text,
        ("확실", "무조건", "간다", "상한가", "급등", "목표가", "저평가", "호재", "반등", "수주", "실적"),
    )
    social_words = _matching_words(
        text,
        ("좋대", "추천", "종토방", "커뮤니티", "유튜브", "텔레그램", "단톡", "블로그", "인플루언서"),
    )
    if uncertainty_words and not conviction_words:
        return {
            "type": "불확실성 인식형",
            "keywords": uncertainty_words,
            "interpretation": (
                "사용자는 이미 단기 방향을 확신하지 못하고 있었습니다. 이 문장은 매수 근거가 아니라 "
                "비중, 보유기간, 무효화 기준을 더 보수적으로 잡으라는 경고 신호에 가깝습니다."
            ),
            "effect": "강한 진입 근거가 아니라 포지션 관리 근거로 재분류",
        }
    if uncertainty_words and conviction_words:
        return {
            "type": "기대와 불안 혼재형",
            "keywords": conviction_words + uncertainty_words,
            "interpretation": (
                "상승 기대와 불안이 같은 문장 안에 섞여 있습니다. 이때는 기대 문장보다 불안 문장을 "
                "상위 조건으로 올려야 판단이 덜 흔들립니다."
            ),
            "effect": "상승 가설은 조건부, 리스크 문장은 우선 검증 대상으로 분리",
        }
    if conviction_words:
        return {
            "type": "확신 주장형",
            "keywords": conviction_words,
            "interpretation": (
                "상승 기대가 비교적 강한 문장입니다. 이 경우 맞고 틀리고보다 먼저, 그 기대가 이미 가격과 "
                "거래량에 반영됐는지를 확인해야 합니다."
            ),
            "effect": "기대 자체가 아니라 선반영 여부를 핵심 검증 질문으로 전환",
        }
    if social_words:
        return {
            "type": "전달 정보 의존형",
            "keywords": social_words,
            "interpretation": (
                "원출처보다 전달된 분위기에 노출된 판단일 수 있습니다. 이 경우 글의 결론보다 최초 출처, "
                "공시 여부, 가격이 먼저 움직였는지를 확인해야 합니다."
            ),
            "effect": "자료의 주장보다 출처와 시간순서를 우선 검증",
        }
    return {
        "type": "근거 모호형",
        "keywords": [],
        "interpretation": (
            "명확한 가설이 잘 보이지 않습니다. 이 상태에서는 결과가 맞았는지보다, 당시 무엇을 믿고 "
            "들어갔는지와 무엇이 틀리면 나올지부터 복원해야 합니다."
        ),
        "effect": "결론보다 진입 기준 복원이 먼저",
    }


def _status_label(kind: str) -> str:
    return {
        "support": "유효",
        "caution": "조건부",
        "contradict": "반박",
        "missing": "공백",
    }.get(kind, "조건부")


def _check(
    kind: str,
    title: str,
    question: str,
    observed: str,
    interpretation: str,
    effect: str,
    next_rule: str,
    coach_note: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "status": _status_label(kind),
        "title": title,
        "question": question,
        "observed": observed,
        "interpretation": interpretation,
        "effect": effect,
        "next_rule": next_rule,
        "coach_note": coach_note or f"코치라면 여기서 '{effect}'라고 짚습니다. 그래서 다음에는 {next_rule}",
    }


def _claim_check(result: dict, profile: dict) -> dict:
    thesis = _plain(result.get("user_thesis"))
    source_material = _plain(result.get("source_material"))
    raw_claim = thesis or "사용자가 명시한 당시 주장은 없습니다."
    if source_material:
        observed = (
            f"입력 문장은 '{_clip(raw_claim, 130)}'이고, 붙여넣은 자료에서 먼저 걸린 문장은 "
            f"'{_clip(source_material, 150)}'입니다."
        )
    else:
        observed = f"입력 문장은 '{_clip(raw_claim, 150)}'입니다. 참고한 원문 자료는 아직 없습니다."
    return _check(
        "caution" if profile["type"] != "근거 모호형" else "missing",
        "사용자가 믿은 문장 재해석",
        "이 문장은 매수 근거였나, 아니면 리스크 경고였나?",
        observed,
        profile["interpretation"],
        profile["effect"],
        "다음 거래부터는 '내가 믿은 문장'과 '이 문장이 틀렸다는 신호'를 한 줄씩 같이 남깁니다.",
        (
            f"네가 적은 문장은 결론이 아니라 경고등입니다. '{profile['type']}'이면 그 문장을 믿고 더 세게 들어갈 게 아니라, "
            "비중을 줄이거나 확인 조건을 먼저 세웠어야 합니다."
        ),
    )


def _news_disclosure_check(result: dict) -> dict:
    reasons = result.get("buy_reasons") or []
    news = _first_news(result)
    disclosure = _first_disclosure(result)
    news_like = any(reason in reasons for reason in ("뉴스/기사", "공시/실적", "커뮤니티/지인 추천"))
    disclosure_like = any(reason in reasons for reason in ("공시/실적", "증권사 리포트"))
    market_reads, price_burden, volume_burden, flow_burden = _market_reaction_snapshot(result)
    if news or disclosure:
        news_timing, news_timing_kind = _news_timing_read(news, result)
        disclosure_timing, disclosure_timing_kind = _disclosure_timing_read(disclosure, result)
        news_part = (
            f"대표 뉴스 '{_clip(news.get('title'), 80)}'가 {_news_time(news)}에 잡혔습니다."
            if news else
            "대표 뉴스는 충분히 잡히지 않았습니다."
        )
        disclosure_title = _plain((disclosure or {}).get("title") or (disclosure or {}).get("report_nm"))
        disclosure_part = (
            f"DART 쪽에서는 '{_clip(disclosure_title, 80)}' 공시가 {disclosure.get('date') or '공시일 확인 제한'}에 잡혔습니다."
            if disclosure else
            "같이 대조할 DART 공시는 아직 충분하지 않습니다."
        )
        burden_count = sum([price_burden, volume_burden, flow_burden])
        if news_timing_kind == "after" or disclosure_timing_kind == "after":
            kind = "contradict"
            interpretation = (
                "이 자료는 매수 당시 사용자가 알 수 있었던 근거라기보다 사후 설명에 가깝습니다. "
                "따라서 이 뉴스·공시를 보고 '내 판단이 맞았다'고 보강하면 안 됩니다. 이번 판단에서는 이 자료를 매수 근거에서 제외하고, "
                "가격·거래량·수급으로 당시 상황을 다시 봐야 합니다."
            )
            effect = "뉴스·공시 근거는 매수 판단 근거에서 제외되고 사후 참고 자료로 강등"
            next_rule = "체결 이후에 나온 뉴스는 당시 판단 근거로 쓰지 않고, 사후 원인 후보로만 따로 표시합니다."
            coach_note = (
                "이건 네가 산 이유로 인정하면 안 됩니다. 매수 뒤에 나온 뉴스로 '역시 내 판단이 맞았네'라고 하면 사후 합리화가 됩니다. "
                "이번 판단은 뉴스가 아니라 매수 당시 가격·거래량·수급으로 다시 평가해야 합니다."
            )
        elif burden_count >= 2:
            kind = "contradict"
            interpretation = (
                "뉴스나 공시 내용이 좋아 보여도, 가격·거래량·수급이 이미 부담 쪽으로 기울어 있습니다. "
                "이 조합에서는 '좋은 재료를 발견했다'가 아니라 '재료가 알려진 뒤 늦게 따라붙었을 수 있다'로 읽어야 합니다. "
                "그래서 뉴스 근거는 진입을 강화하는 자료가 아니라 추격 위험을 확인시키는 자료로 바뀝니다."
            )
            effect = "뉴스·공시는 진입 강화 근거가 아니라 추격 위험 신호로 재분류"
            next_rule = "뉴스가 좋아도 최근 상승률, 당일 위치, 거래량 피크, 외국인·기관 수급 중 두 개 이상이 부담이면 추격 근거로 쓰지 않습니다."
            coach_note = (
                "여기서 배워야 할 건 '뉴스가 맞냐 틀리냐'가 아닙니다. 이미 가격이 움직였고 거래가 몰렸거나 수급이 받쳐주지 않으면, "
                "좋은 뉴스는 진입 신호가 아니라 늦게 본 신호입니다. 이 경우 네가 한 행동은 발견이 아니라 추격에 가까워집니다."
            )
        elif flow_burden:
            kind = "contradict"
            interpretation = (
                "뉴스는 보이지만 외국인·기관 수급이 받쳐주지 않습니다. 이 경우 시장 전체가 그 뉴스를 매수 근거로 받아들였다고 보기 어렵습니다. "
                "따라서 뉴스는 관심 배경으로만 남기고, 단기 판단은 수급 회복 여부가 먼저입니다."
            )
            effect = "뉴스 근거는 보조 배경으로 강등되고 수급 회복 확인이 우선"
            next_rule = "뉴스를 보고 들어가기 전에는 그날 또는 이후 외국인·기관이 실제로 같이 들어오는지 확인합니다."
            coach_note = (
                "뉴스는 좋은데 큰돈 흐름이 안 따라오면, 개인만 제목에 반응한 장면일 수 있습니다. "
                "이럴 땐 뉴스로 확신을 키우지 말고 수급이 돌아오는지 확인할 때까지 판단 강도를 낮춰야 합니다."
            )
        elif price_burden or volume_burden:
            kind = "caution"
            interpretation = (
                "뉴스·공시는 의미가 있을 수 있지만, 가격이나 거래량이 이미 먼저 반응한 흔적이 있습니다. "
                "따라서 이 자료는 '바로 진입' 근거가 아니라 '눌림이나 다음 거래량 유지 확인' 근거로만 써야 합니다."
            )
            effect = "뉴스·공시는 즉시 판단 근거에서 조건부 관찰 근거로 내려감"
            next_rule = "재료가 보이면 바로 판단하지 말고 첫 반응 이후 가격이 버티는지, 거래량이 이어지는지 확인합니다."
            coach_note = (
                "뉴스 자체는 버릴 필요가 없지만 바로 매수 버튼을 누를 근거는 아닙니다. "
                "이미 한 번 반응한 흔적이 있으니, 여기서는 '지금 들어간다'가 아니라 '다음 거래량이 이어지면 본다'로 바꿨어야 합니다."
            )
        else:
            kind = "support"
            interpretation = (
                "현재 연결된 데이터만 보면 뉴스·공시가 가격과 수급에 의해 강하게 반박되지는 않습니다. "
                "다만 이것도 단독 매수 근거가 아니라, 다음 가격 유지와 거래량 확인까지 통과할 때 판단을 보강하는 자료입니다."
            )
            effect = "뉴스·공시는 보조 유효 근거로 유지되지만 단독 결론은 아님"
            next_rule = "뉴스·공시가 반박되지 않을 때도 다음 봉의 가격 유지와 거래량 지속을 확인한 뒤 판단 강도를 올립니다."
            coach_note = (
                "이 경우 뉴스는 완전히 헛근거는 아닙니다. 다만 코치라면 '좋아, 관심 근거로는 인정. 대신 다음 가격 유지와 거래량까지 확인하고 강도를 올리자'고 말합니다."
            )
        return _check(
            kind,
            "뉴스·공시 시간순서 확인",
            "이 뉴스·공시를 지금 판단 근거로 올려도 되나?",
            f"{news_part} {disclosure_part} {news_timing} {disclosure_timing} {' '.join(market_reads)}",
            interpretation,
            effect,
            next_rule,
            coach_note,
        )
    if news_like or disclosure_like:
        return _check(
            "missing",
            "뉴스·공시 원문 공백",
            "근거로 삼은 자료의 원문과 최초 시각을 복원할 수 있나?",
            "사용자는 뉴스·공시성 근거를 선택했지만, 자동 매칭된 대표 원문은 충분하지 않습니다.",
            "이 상태에서 호재 선반영, 공시 효과, 실적 소멸을 단정하면 사후 끼워맞추기가 됩니다.",
            "정보성 근거는 아직 판단 강화가 아니라 자료 보강 필요로 분류",
            "다음에는 본 기사 링크나 공시 제목을 그대로 붙이고, 서비스는 그 시각을 기준으로 가격 반응을 다시 붙입니다.",
            (
                "네가 뉴스나 공시 때문에 움직였다고 했는데 원문이 없으면, 코치는 여기서 결론을 안 냅니다. "
                "원문이 없다는 건 네 기억이 틀렸다는 뜻이 아니라, 아직 판단 근거로 승격시킬 수 없다는 뜻입니다."
            ),
        )
    return _check(
        "caution",
        "뉴스·공시 영향 제한",
        "이번 판단에서 뉴스·공시가 메인 근거였나?",
        "입력 근거상 뉴스·공시가 핵심 축으로 선택되지는 않았습니다.",
        "따라서 DART를 억지로 결론에 끼우기보다, 가격·거래량·수급·포지션 조건을 먼저 봐야 합니다.",
        "DART는 필수 근거가 아니라 공시·실적형 거래에서 켜지는 검증 축",
        "근거가 차트나 수급이면 DART보다 체결 시점 가격과 거래량을 우선합니다.",
        "이번 거래가 뉴스·공시형이 아니라면 억지로 DART를 끌어올 필요가 없습니다. 코치라면 네가 실제로 보고 움직인 축부터 확인하라고 합니다.",
    )


def _price_check(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    prev_5d = _num(metrics.get("prev_5d_return"))
    day_pos = _num(metrics.get("day_position_pct"))
    if prev_5d is None and day_pos is None:
        return _check(
            "missing",
            "가격 위치 복원 공백",
            "내가 산 위치가 이미 반응한 뒤였나?",
            "매수 전 5거래일 흐름과 당일 고저점 내 위치가 충분히 복원되지 않았습니다.",
            "가격 위치가 없으면 추격 매수인지, 낙폭과대 접근인지, 단순 변동인지 강하게 말할 수 없습니다.",
            "가격 축은 낮은 확신도로만 반영",
            "체결 시간과 당일 고가·저가, 전일 종가를 붙여야 진입 위치 진단이 선명해집니다.",
            "코치라면 여기서 원인 추정을 멈춥니다. 네가 어디서 샀는지 복원되지 않으면 '당했다/안 당했다'보다 먼저 진입 위치부터 복구해야 합니다.",
        )

    parts = []
    kind = "caution"
    if prev_5d is not None:
        if prev_5d >= 8:
            parts.append(f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}로, 가격이 먼저 움직인 흔적이 있습니다.")
            kind = "contradict"
        elif prev_5d <= -8:
            parts.append(f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}라 낙폭과대 접근은 일부 설명됩니다.")
            kind = "support"
        else:
            parts.append(f"매수 전 5거래일 수익률은 {_fmt_pct(prev_5d)}로 강한 선반영 신호는 제한적입니다.")
    if day_pos is not None:
        if day_pos >= 70:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점이라 진입 위치 부담이 있습니다.")
            kind = "contradict"
        elif day_pos <= 30:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점이라 고점 추격으로 단정하기는 어렵습니다.")
        else:
            parts.append(f"매수가는 당일 범위의 {day_pos:.0f}% 지점으로 중간권입니다.")
    if kind == "contradict":
        coach_note = (
            "가격 쪽 코칭은 단순합니다. 네가 좋은 정보를 본 게 문제가 아니라, 그 정보를 보기 전에 이미 가격이 움직였는지 봤어야 합니다. "
            "이미 오른 뒤 위쪽에서 샀다면 이건 '정보를 선점한 매수'가 아니라 '반응 뒤 추격'으로 봐야 합니다."
        )
    elif kind == "support":
        coach_note = (
            "가격만 보면 네 판단이 완전히 이상한 자리는 아닙니다. 다만 싸 보인다는 느낌 하나로는 부족하고, "
            "거래량과 수급이 실제로 돌아오는지까지 확인해야 반등 근거로 올라갑니다."
        )
    else:
        coach_note = (
            "가격은 애매합니다. 이럴 때 코치는 방향을 맞히라고 하지 않고, 다른 축이 확실해질 때까지 판단 크기를 줄이라고 말합니다."
        )
    return _check(
        kind,
        "가격 선반영·진입 위치",
        "내가 본 이슈보다 가격이 먼저 움직였나?",
        " ".join(parts),
        "가격 축은 사용자의 근거가 실제로 늦었는지 확인하는 첫 번째 필터입니다. 가격이 이미 먼저 움직였으면 좋은 뉴스도 매수 근거가 아니라 추격 위험 신호가 됩니다.",
        "가격이 먼저 반응했다면 자료의 질보다 진입 위치 리스크가 더 커짐",
        "좋은 이슈를 봤다면 바로 누르기 전에 최근 3~5거래일 상승률과 당일 체결 위치부터 확인합니다.",
        coach_note,
    )


def _volume_flow_check(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    flow = result.get("flow_read") or {}
    volume_ratio = _num(metrics.get("volume_ratio"))
    smart_flow = _num(flow.get("smart"))
    observed_parts = []
    kind = "caution"
    if volume_ratio is None:
        observed_parts.append("매수일 거래량 배율은 충분히 복원되지 않았습니다.")
        kind = "missing"
    elif volume_ratio >= 2:
        observed_parts.append(f"매수일 거래량은 직전 평균의 {volume_ratio:.1f}배였습니다.")
    elif volume_ratio <= 0.8:
        observed_parts.append(f"매수일 거래량은 직전 평균의 {volume_ratio:.1f}배로 약했습니다.")
    else:
        observed_parts.append(f"매수일 거래량은 직전 평균의 {volume_ratio:.1f}배로 중간 수준입니다.")

    if smart_flow is None:
        observed_parts.append("KRX 외국인·기관 합산 수급은 확인 제한입니다.")
        if kind != "missing":
            kind = "caution"
    elif smart_flow < 0:
        observed_parts.append(f"KRX 외국인·기관 합산 수급은 {flow.get('summary') or _fmt_eok(smart_flow)}입니다.")
        kind = "contradict"
    elif smart_flow > 0:
        observed_parts.append(f"KRX 외국인·기관 합산 수급은 {flow.get('summary') or _fmt_eok(smart_flow)}입니다.")
        if kind != "contradict":
            kind = "support"
    else:
        observed_parts.append("KRX 외국인·기관 합산 수급은 중립에 가깝습니다.")

    if volume_ratio is not None and volume_ratio >= 2 and smart_flow is not None and smart_flow < 0:
        interpretation = (
            "거래량은 터졌지만 외국인·기관이 받쳐주지 않은 조합입니다. 이 경우 '관심이 몰렸다'보다 "
            "'고점권 물량 소화나 차익실현이 섞였나'를 먼저 의심해야 합니다."
        )
    elif smart_flow is not None and smart_flow > 0:
        interpretation = (
            "수급이 완전히 반대로 간 거래는 아닙니다. 다만 단기 판단에서는 수급 유입 하나만 보고 강하게 밀면 안 됩니다. "
            "가격이 버티고 거래량이 이어질 때만 판단 강도를 올릴 수 있습니다."
        )
    else:
        interpretation = (
            "거래량과 수급은 단기 판단의 핵심 축입니다. 한쪽이 비어 있거나 약하면 뉴스, 공시, 리포트의 힘도 낮춰 읽어야 합니다."
        )
    if kind == "contradict":
        coach_note = (
            "여기서 코치가 제일 세게 짚을 부분은 이겁니다. 거래는 많았는데 외국인·기관이 안 받쳐주면, "
            "그 거래량은 내 편의 매수세가 아니라 먼저 산 사람들의 출구일 수도 있습니다. 이 구간에서는 확신을 키우면 안 됩니다."
        )
    elif kind == "support":
        coach_note = (
            "수급은 네 판단을 어느 정도 받쳐줍니다. 하지만 이것만으로 끝이 아닙니다. 코치라면 '좋아, 그런데 가격이 버티는지까지 확인하고 비중을 올리자'고 말합니다."
        )
    elif kind == "missing":
        coach_note = (
            "수급이나 거래량이 비면 코칭도 조심스러워집니다. 이 경우 뉴스나 감정으로 빈칸을 메우지 말고, 데이터가 찰 때까지 판단 강도를 낮춰야 합니다."
        )
    else:
        coach_note = (
            "거래량과 수급은 아직 한쪽으로 확 기울지 않았습니다. 이럴 땐 맞히려 하지 말고, 다음 봉에서 거래량이 이어지는지 확인하는 관찰 모드가 맞습니다."
        )
    return _check(
        kind,
        "거래량·수급 동행 여부",
        "관심이 실제 매수세로 이어졌나, 아니면 물량이 빠진 구간이었나?",
        " ".join(observed_parts),
        interpretation,
        "거래량과 수급이 같은 방향일 때만 단기 근거가 강화됨",
        "거래량 급증 뒤 가격이 못 버티거나 외국인·기관이 비면, 이슈보다 물량 소화를 먼저 의심합니다.",
        coach_note,
    )


def _position_check(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    post_return = _num(metrics.get("post_return"))
    buy_price = _num(result.get("buy_price"))
    target = _num(result.get("expected_target_price"))
    stop = _num(result.get("stop_loss_price"))
    weight = _num(result.get("position_weight_pct"))
    max_loss = _num(result.get("max_loss_pct"))
    leverage = _plain(result.get("leverage"))
    capital = _plain(result.get("capital_pressure"))
    horizon = _plain(result.get("horizon"))
    target_return = (target / buy_price - 1) * 100 if target and buy_price else None
    stop_return = (stop / buy_price - 1) * 100 if stop and buy_price else None
    levered = leverage in ("미수 사용", "신용 사용", "미수/신용 둘 다")
    high_weight = weight is not None and weight >= 35
    urgent = capital == "곧 필요한 돈"
    within_loss_budget = post_return is not None and max_loss is not None and post_return < 0 and abs(post_return) <= max_loss

    parts = []
    if post_return is not None:
        parts.append(f"매수 후 수익률은 {_fmt_pct(post_return)}입니다.")
    if target_return is not None:
        parts.append(f"사용자가 생각한 목표가는 매수가 대비 {_fmt_pct(target_return)}입니다.")
    if stop_return is not None:
        parts.append(f"무효화 기준은 매수가 대비 {_fmt_pct(stop_return)}입니다.")
    if weight is not None:
        parts.append(f"계좌 내 비중은 {weight:.0f}%입니다.")
    if max_loss is not None:
        parts.append(f"감당 가능 손실률은 -{max_loss:.1f}%입니다.")
    if leverage:
        parts.append(f"레버리지 상태는 {leverage}입니다.")
    if capital:
        parts.append(f"자금 성격은 {capital}입니다.")
    if horizon:
        parts.append(f"투자기간은 {horizon}입니다.")

    if post_return is not None and post_return < 0 and within_loss_budget and not levered and not high_weight and not urgent:
        kind = "support"
        interpretation = (
            "현재 손실은 입력한 감당 가능 범위 안에 있습니다. 이 경우 '내가 당했다'로 바로 결론내기보다, "
            "처음 세운 근거가 실제로 훼손됐는지와 단기 변동을 구분해야 합니다."
        )
        effect = "손실 자체보다 근거 훼손 여부가 핵심"
        coach_note = (
            "이건 무조건 실패로 볼 장면이 아닙니다. 네가 감당하겠다고 정한 손실 범위 안이면, 코치는 '손실 났다'보다 "
            "'처음 믿은 근거가 깨졌나?'를 먼저 묻습니다. 기준이 안 깨졌다면 감정으로 복기하면 안 됩니다."
        )
    elif levered or high_weight or urgent:
        kind = "contradict"
        interpretation = (
            "종목 근거와 별개로 포지션 구조가 판단 시간을 짧게 만듭니다. 미수·신용, 높은 비중, 곧 필요한 돈은 "
            "같은 가격 변동도 훨씬 크게 느끼게 만들어서 좋은 근거를 들고 있어도 실행 품질을 낮춥니다."
        )
        effect = "좋은 근거보다 시간 압박과 손실 허용 범위가 우선"
        coach_note = (
            "여기서는 종목보다 네 포지션이 문제입니다. 좋은 근거가 있어도 미수·신용, 높은 비중, 곧 필요한 돈이면 "
            "작은 흔들림에도 버틸 시간이 없습니다. 코치라면 진입 전부터 손절 기준과 비중을 더 작게 잡으라고 했을 겁니다."
        )
    else:
        kind = "caution"
        interpretation = (
            "포지션 조건만으로 좋다/나쁘다를 단정하긴 어렵습니다. 다만 목표가, 무효화 기준, 감당 손실률이 "
            "서로 연결되어 있어야 같은 상황이 반복되지 않습니다."
        )
        effect = "가격 전망보다 목표가·손절가·비중의 일관성 확인 필요"
        coach_note = (
            "포지션 정보만으로는 강하게 혼낼 장면도, 칭찬할 장면도 아닙니다. 대신 목표가와 손절가가 같이 있어야 합니다. "
            "목표가만 있고 무효화 기준이 없으면 그건 계획이 아니라 기대입니다."
        )

    return _check(
        kind,
        "내 포지션 압박 반영",
        "이 하락은 근거 훼손인가, 아니면 내가 감당 가능한 단기 변동인가?",
        " ".join(parts) if parts else "포지션 비중, 자금 성격, 감당 손실률이 충분히 입력되지 않았습니다.",
        interpretation,
        effect,
        "다음 거래는 목표가보다 먼저 무효화 기준, 감당 손실률, 투입 비중을 같은 화면에서 맞춥니다.",
        coach_note,
    )


def _time_axis_check(result: dict) -> dict:
    reasons = result.get("buy_reasons") or []
    horizon = _plain(result.get("horizon"))
    short = horizon in ("당일", "내일~3일", "1주 이내")
    report_like = "증권사 리포트" in reasons
    disclosure_like = "공시/실적" in reasons
    if short and report_like:
        return _check(
            "contradict",
            "근거 시간축 불일치",
            "내 투자기간과 근거의 시간축이 맞았나?",
            f"입력한 투자기간은 {horizon}이고, 근거에는 증권사 리포트가 포함되어 있습니다.",
            "단기 판단에는 목표가보다 가격 위치, 장 초반 거래량, 수급 유지가 먼저입니다. 리포트는 중기 추적 논리이지 내일의 매도·보유를 직접 결정하는 자료가 아닙니다.",
            "리포트는 메인 근거에서 보조 근거로 내려야 함",
            "단기 매매에서는 리포트 목표가를 결론으로 쓰지 말고, '계속 추적할 이유'로만 둡니다.",
            (
                "이건 진짜 자주 당하는 실수입니다. 내일 팔지 말지를 고민하면서 6개월 목표가를 붙잡으면 판단이 흐려집니다. "
                "코치라면 리포트는 관심 근거로만 두고, 단기 판단은 평단·거래량·수급으로 다시 하라고 합니다."
            ),
        )
    if short and disclosure_like:
        return _check(
            "caution",
            "공시·실적의 단기 해석",
            "공시나 실적이 좋아도 단기 가격은 왜 반대로 갈 수 있나?",
            f"입력한 투자기간은 {horizon}이고, 근거에는 공시·실적이 포함되어 있습니다.",
            "공시나 실적은 숫자가 좋아도 기대가 먼저 반영돼 있으면 발표 직후 내려갈 수 있습니다. 단기에는 내용의 좋고 나쁨보다 발표 전 가격 반응과 거래량 피크가 더 중요합니다.",
            "공시 내용과 가격 반응을 분리해서 봐야 함",
            "실적·공시 직후에는 숫자만 보지 말고 컨센서스, 발표 전 상승률, 발표 직후 거래량을 같이 봅니다.",
            (
                "공시나 실적이 좋다는 말만 보고 들어가면 늦을 수 있습니다. 코치라면 '숫자가 좋다' 다음에 바로 "
                "'그 좋은 숫자를 시장이 이미 예상했나?'를 묻습니다. 발표 후 하락은 종종 악재가 아니라 기대 선반영의 결과일 수 있습니다."
            ),
        )
    return _check(
        "support" if horizon else "missing",
        "판단 시간축",
        "이번 판단은 단타, 스윙, 중기 중 어디에 속했나?",
        f"입력한 투자기간은 {horizon or '미입력'}입니다.",
        "시간축이 정해지면 어떤 데이터를 우선할지가 바뀝니다. 당일·내일은 가격과 수급, 1개월 이상은 실적·공시·리포트의 비중이 올라갑니다.",
        "데이터 우선순위를 정하는 기준",
        "판단 전 투자기간을 먼저 고정하고, 그 기간과 맞지 않는 근거는 보조 근거로 내립니다.",
        "코치라면 먼저 '이 거래를 몇 일짜리로 보는 거야?'부터 물을 겁니다. 기간이 정해져야 뉴스, 수급, 리포트 중 뭘 먼저 볼지 정해집니다.",
    )


def _data_gap_check(result: dict) -> dict | None:
    data_quality = result.get("data_quality") or {}
    critical = data_quality.get("critical_missing") or []
    missing = result.get("missing") or []
    if not critical and not missing:
        return None
    observed = " ".join((critical + missing)[:4])
    return _check(
        "missing",
        "확신도를 낮춘 데이터 공백",
        "이번 결론에서 아직 비어 있는 축은 무엇인가?",
        observed,
        "비어 있는 데이터는 결론을 약하게 만드는 요소입니다. 특히 체결 시간, 분봉, 시간외 거래량, 원문 링크가 없으면 단타 원인 분류는 보수적으로 읽어야 합니다.",
        "패턴명은 유지하되 원인 단정은 낮춤",
        "단기 거래는 체결 시각, 분봉 위치, 시간외 거래량을 보강해야 진단 밀도가 올라갑니다.",
        (
            "여기는 솔직히 말해 추측 금지 구간입니다. 코치라면 빈 데이터를 감으로 메우지 않습니다. "
            "체결 시각과 원문이 없으면 원인을 세게 찍지 말고, 다음 거래 기록 습관부터 고치라고 합니다."
        ),
    )


def _main_read(result: dict, profile: dict, checks: list[dict]) -> dict:
    company = result.get("company") or {}
    metrics = result.get("metrics") or {}
    top = result.get("top_label") or {}
    data_quality = result.get("data_quality") or {}
    thesis = _plain(result.get("user_thesis")) or "당시 생각 미입력"
    name = _plain(company.get("name")) or "이 종목"
    post_return = _num(metrics.get("post_return"))
    contradicts = [check for check in checks if check.get("kind") == "contradict"]
    missing = [check for check in checks if check.get("kind") == "missing"]
    supports = [check for check in checks if check.get("kind") == "support"]

    if profile["type"] in ("불확실성 인식형", "기대와 불안 혼재형"):
        core = (
            "사용자는 사실 확신을 말한 게 아니라 불확실성을 이미 감지하고 있었습니다. "
            "그래서 이번 진단의 핵심은 '맞았냐 틀렸냐'보다, 그 불확실성을 비중과 시간축에 제대로 반영했는지입니다."
        )
    elif profile["type"] == "확신 주장형":
        core = (
            "사용자의 문장은 상승 기대가 강했습니다. 그래서 핵심 검증은 그 기대가 사실인지보다, "
            "이미 가격과 거래량에 반영된 기대였는지입니다."
        )
    elif profile["type"] == "전달 정보 의존형":
        core = (
            "이번 판단은 원자료보다 전달된 분위기에 영향을 받았을 가능성이 있습니다. "
            "그래서 글의 결론보다 출처와 시간순서를 먼저 다시 붙였습니다."
        )
    else:
        core = (
            "당시 근거가 명확히 적히지 않았습니다. 그래서 이번에는 결과를 그럴듯하게 설명하기보다, 다음 거래에서 반드시 남겨야 할 판단 기준을 복원하는 쪽에 초점을 둡니다."
        )

    if contradicts:
        primary = contradicts[0]
        evidence_sentence = (
            f"코치가 제일 먼저 잡을 부분은 '{primary['title']}'입니다. "
            f"{primary.get('coach_note') or primary.get('interpretation')} "
            "즉, 이번 판단에서 문제는 정보가 없었던 게 아니라, 그 정보를 내 진입 위치와 수급 상태에 맞게 낮춰 읽지 못한 쪽에 가깝습니다."
        )
    elif missing:
        primary = missing[0]
        evidence_sentence = (
            f"이번에는 '{primary['title']}'이 비어 있어서 원인을 세게 단정하면 안 됩니다. "
            f"{primary.get('coach_note') or primary.get('interpretation')} "
            "여기서 배울 점은 더 많은 설명을 붙이는 게 아니라, 다음 거래부터 판단에 필요한 원자료를 남기는 습관입니다."
        )
    elif supports:
        primary = supports[0]
        evidence_sentence = (
            f"이번 판단에서 그래도 인정할 수 있는 부분은 '{primary['title']}'입니다. "
            f"{primary.get('coach_note') or primary.get('interpretation')} "
            "다만 유효한 근거가 하나 있다고 해서 바로 강한 결론으로 점프하면 안 됩니다. 다른 축이 같이 맞아야 합니다."
        )
    else:
        evidence_sentence = (
            "이번 데이터는 한쪽으로 강하게 기울지 않았습니다. 코치라면 여기서 맞히려 하지 않고, "
            "무엇이 확인되면 판단 강도를 올리고 무엇이 깨지면 내려올지 기준부터 세우라고 말합니다."
        )

    paragraphs = [
        {
            "title": "1. 네가 적은 말을 먼저 다시 읽었습니다",
            "body": (
                f"{_decision_time(result)}에 {name}을 {_fmt_won(result.get('buy_price'))} 근처에서 보며 사용자가 적은 문장은 "
                f"'{_clip(thesis, 160)}'입니다. 이 문장은 {profile['type']}입니다. {core}"
            ),
        },
        {"title": "2. 그래서 제일 먼저 고칠 판단은 이겁니다", "body": evidence_sentence},
        {
            "title": "3. 네 포지션까지 넣으면 의미가 달라집니다",
            "body": (
                f"매수 이후 손익은 {_fmt_pct(post_return)}입니다. 이 숫자만으로 성공이나 실패를 판정하지 않았습니다. "
                "미수·신용, 계좌 비중, 감당 가능 손실률, 자금 필요 시점이 있으면 같은 하락도 전혀 다르게 읽히기 때문입니다. "
                "그래서 이번 판단은 종목 전망보다 먼저 '이 변동을 감당할 구조였는가'로 재가공했습니다."
            ),
        },
        {
            "title": "4. 이번에 가져가야 할 한 문장",
            "body": (
                f"현재 가장 가까운 패턴은 '{_plain(top.get('name')) or '진단 제한'}'입니다. "
                f"다만 데이터 완성도는 {data_quality.get('score', '확인 제한')}/100입니다. "
                "이번에 배울 점은 '좋은 말이 보이면 바로 믿지 말자'가 아니라, 그 좋은 말이 내 매수 시점에서는 진짜 새 근거였는지, "
                "아니면 이미 가격과 거래량에 반영된 뒤 내가 뒤늦게 붙잡은 말이었는지 먼저 가르는 것입니다."
            ),
        },
    ]
    return {
        "lead": "FinSight는 네가 적은 생각을 그대로 받아쓰지 않고, 그 생각이 실제 데이터 앞에서 어떻게 바뀌어야 하는지 코치처럼 다시 짚습니다.",
        "one_sentence": (
            f"이번 판단의 핵심은 '{thesis}'라는 생각을 그대로 믿는 게 아니라, "
            f"{_plain(top.get('name')) or '진단 제한'} 가능성 때문에 판단 강도를 낮추거나 확인 순서를 바꿨어야 했다는 점입니다."
        ),
        "paragraphs": paragraphs,
        "next_rules": [
            "좋은 뉴스나 글을 보면 먼저 최초 공개 시각과 매수 전 주가 반응을 확인합니다.",
            "단기 판단에서는 리포트 목표가보다 체결 위치, 거래량 지속, 외국인·기관 수급을 먼저 봅니다.",
            "불안하다는 생각이 들면 그 문장을 무시하지 말고 비중, 손절 기준, 보유기간을 낮추는 신호로 씁니다.",
            "손실이 났을 때는 가격 하락과 근거 훼손을 분리해서 봅니다.",
        ],
    }


def build_insight_packet(result: dict) -> dict:
    """Build the main reprocessed judgement packet consumed by the UI."""
    thesis = _plain(result.get("user_thesis"))
    source_material = _plain(result.get("source_material"))
    profile = _claim_profile(thesis, source_material)
    checks = [
        _claim_check(result, profile),
        _news_disclosure_check(result),
        _price_check(result),
        _volume_flow_check(result),
        _position_check(result),
        _time_axis_check(result),
    ]
    gap = _data_gap_check(result)
    if gap:
        checks.append(gap)
    return {
        "claim": {
            "raw": thesis or "당시 생각 미입력",
            "source_material": source_material,
            "type": profile["type"],
            "keywords": profile.get("keywords") or [],
            "interpretation": profile["interpretation"],
            "effect": profile["effect"],
        },
        "checks": checks,
        "main_read": _main_read(result, profile, checks),
    }
