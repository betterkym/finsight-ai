"""모듈2 — 시점 정합성. 리포트 발행 후 무슨 일이 있었나.

발행일을 기준점(t=0)으로 잡고, 그 후 나온 실적·공시·수급·주가를
한 타임라인에 모은다. 수급은 '신호'가 아니라 '리포트 의견 vs 시장
행동의 괴리'로만 제시한다 (리딩방식 단발 신호 금지).
"""
from __future__ import annotations

import contextlib
import io
from datetime import datetime


def _iso_date(value) -> str:
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return str(value)[:10]


def _fmt_eok(value) -> str:
    if value is None:
        return "N/A"
    number = float(value)
    direction = "순매수" if number >= 0 else "순매도"
    return f"{direction} {abs(number):,.0f}억원"


def _days_between(start_ymd: str, end_ymd: str | None = None) -> int:
    """두 날짜(YYYY-MM-DD) 사이 일수."""
    start = datetime.strptime(start_ymd, "%Y-%m-%d")
    end = datetime.strptime(end_ymd, "%Y-%m-%d") if end_ymd else datetime.now()
    return (end - start).days


def fetch_price_at_date(stock_code: str, ymd: str) -> float | None:
    """지정된 날짜의 종가. pykrx 사용, 실패 시 None."""
    try:
        from pykrx import stock

        yyyymmdd = ymd.replace("-", "")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = stock.get_market_ohlcv(yyyymmdd, yyyymmdd, stock_code)
        if not df.empty:
            return float(df.iloc[0]["종가"])
    except Exception:
        pass
    return None


def fetch_foreign_flow(stock_code: str, pub_date: str, as_of: str | None = None) -> dict | None:
    """발행 후 외국인 누적 순매수 상세. pykrx 사용, 실패 시 None."""
    try:
        from pykrx import stock

        start = pub_date.replace("-", "")
        end = (as_of or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = stock.get_market_trading_value_by_date(start, end, stock_code)
        if df.empty:
            return None
        for col in ("외국인", "외국인합계"):
            if col in df.columns:
                daily = df[col].dropna() / 1e8
                if daily.empty:
                    return None
                net_eok = int(round(float(daily.sum())))
                return {
                    "net_eok": net_eok,
                    "start": _iso_date(df.index[0]),
                    "end": _iso_date(df.index[-1]),
                    "trading_days": int(len(daily)),
                    "avg_daily_eok": round(float(daily.mean()), 1),
                    "recent_5d_eok": round(float(daily.tail(min(5, len(daily))).sum()), 1),
                    "buy_days": int((daily > 0).sum()),
                    "sell_days": int((daily < 0).sum()),
                    "source": "KRX 투자자별 거래대금",
                    "available": True,
                }
    except Exception:
        return None
    return None


def fetch_foreign_net(stock_code: str, pub_date: str) -> int | None:
    """발행 후 외국인 누적 순매수(억). pykrx 사용, 실패 시 None."""
    flow = fetch_foreign_flow(stock_code, pub_date)
    return flow.get("net_eok") if flow else None


def _fallback_foreign_flow(value: int | None, pub_date: str, as_of: str | None) -> dict:
    return {
        "net_eok": int(value or 0),
        "start": pub_date,
        "end": as_of or datetime.now().strftime("%Y-%m-%d"),
        "trading_days": None,
        "avg_daily_eok": None,
        "recent_5d_eok": None,
        "buy_days": None,
        "sell_days": None,
        "source": "보조 수급값",
        "available": value is not None,
    }


def build_supply_basis(timeline: dict) -> str:
    net = timeline.get("foreign_net")
    if net is None:
        return "외국인 수급 데이터를 확인하지 못했습니다."
    start = timeline.get("foreign_start") or timeline.get("pub_date") or "발행일"
    end = timeline.get("foreign_end") or "현재"
    days = timeline.get("foreign_trading_days")
    avg = timeline.get("foreign_avg_daily")
    recent = timeline.get("foreign_recent_5d")
    source = timeline.get("foreign_source") or "KRX"
    parts = [f"{start}~{end} 외국인 누적 {_fmt_eok(net)}"]
    if days:
        parts.append(f"{days}거래일")
    if avg is not None:
        parts.append(f"일평균 {_fmt_eok(avg)}")
    if recent is not None:
        parts.append(f"최근 5거래일 {_fmt_eok(recent)}")
    parts.append(source)
    return " · ".join(parts)


def build_supply_read(timeline: dict) -> str:
    """Explain what the flow means instead of showing a standalone number."""
    net = timeline.get("foreign_net")
    basis = build_supply_basis(timeline)
    opinion = str(timeline.get("opinion") or "")
    realized = timeline.get("realized")
    remaining = timeline.get("remaining")
    price_text = ""
    if realized is not None:
        price_text = f" 같은 기간 주가는 {realized:+.1f}% 움직였고"
        if remaining is not None:
            price_text += f", 목표가까지 남은 여력은 {remaining:+.1f}%입니다."
        else:
            price_text += "."

    if net is None:
        return "수급 데이터가 없어 발행 이후 괴리는 주가와 공시 변화 중심으로 봅니다."
    if net < 0 and opinion in ("매수", "적극매수", "Buy"):
        return (
            f"{basis}. 매수 리포트가 나온 뒤 외국인은 반대로 팔았습니다.{price_text} "
            "이 숫자는 회사가 나빠졌다는 단정이 아니라, 발행 이후 시장 참여자가 아직 리포트의 목표가 시나리오를 따라가지 않았다는 뜻입니다. "
            "여기서 흐름이 바뀌었다고 보려면 외국인 매도가 멈추거나 순매수로 돌아서고, 최근 5거래일 매도 강도가 줄어들며, "
            "주가가 발행일 이후 하락분을 일부 되돌리는 모습이 같이 나와야 합니다. 그 전까지는 목표가가 논리적으로 가능해도 주가 반영 시점을 보수적으로 봅니다."
        )
    if net > 0 and opinion in ("매수", "적극매수", "Buy"):
        return (
            f"{basis}. 리포트 방향과 수급 방향은 같은 편입니다.{price_text} "
            "다만 순매수만으로 목표가를 정당화할 수는 없고, 실적과 공시가 같은 방향으로 받쳐주는지까지 같이 봅니다."
        )
    if net < 0:
        return (
            f"{basis}. 발행 이후 외국인 매도가 누적됐습니다.{price_text} "
            "주가 약세가 실적만의 문제가 아니라 수급 할인과 함께 나타난 구간인지 확인해야 합니다."
        )
    if net > 0:
        return (
            f"{basis}. 발행 이후 외국인 매수는 주가 하방을 일부 완충하는 요인입니다.{price_text} "
            "다만 목표가 신뢰도는 수급보다 실적·공시로 확인되는 전제가 우선입니다."
        )
    return (
        f"{basis}. 외국인 수급은 방향성이 크지 않습니다.{price_text} "
        "이 경우 발행 이후 괴리는 수급보다 주가 변화와 새 공시·뉴스를 더 크게 봅니다."
    )


def build_post_publish_timeline(
    report: dict,
    current_price: float,
    *,
    stock_code: str | None = None,
    post_events: list[dict] | None = None,
    foreign_net_fallback: int | None = None,
    foreign_flow_fallback: dict | None = None,
    as_of: str | None = None,
) -> dict:
    """발행 후 타임라인 + 선반영 소진율 + 수급 괴리.

    report: {pub_date, opinion, target_price, price_at_pub, annual_op_assumption_eok}
    """
    pub_date = report["pub_date"]
    elapsed = _days_between(pub_date, as_of)

    price_at_pub = float(report["price_at_pub"])
    target = float(report["target_price"])
    orig_upside = (target / price_at_pub - 1) * 100
    realized = (current_price / price_at_pub - 1) * 100
    remaining = (target / current_price - 1) * 100
    # 발행 시점 상승여력이 양(+)일 때만 '소진율'이 의미가 있다.
    # 목표가가 발행가보다 낮은(하향) 리포트면 소진 개념이 성립하지 않는다.
    if orig_upside > 0:
        soak_pct = round(realized / orig_upside * 100)
    else:
        soak_pct = 0

    # 수급: pykrx 우선, 실패 시 폴백
    foreign_flow = None
    if stock_code:
        foreign_flow = fetch_foreign_flow(stock_code, pub_date, as_of=as_of)
    if foreign_flow is None and foreign_flow_fallback:
        foreign_flow = foreign_flow_fallback
    if foreign_flow is None:
        foreign_flow = _fallback_foreign_flow(foreign_net_fallback, pub_date, as_of)
    foreign_net = foreign_flow.get("net_eok")

    opinion = report.get("opinion", "매수")
    supply_gap = (opinion in ("매수", "적극매수")) and foreign_net < 0
    timeline = {
        "pub_date": pub_date,
        "price_at_pub": round(price_at_pub),
        "target_price": round(target),
        "elapsed": elapsed,
        "months": round(elapsed / 30, 1),
        "orig_upside": round(orig_upside, 1),
        "realized": round(realized, 1),
        "remaining": round(remaining, 1),
        "soak_pct": soak_pct,
        "foreign_net": foreign_net,
        "foreign_start": foreign_flow.get("start"),
        "foreign_end": foreign_flow.get("end"),
        "foreign_source": foreign_flow.get("source"),
        "foreign_available": foreign_flow.get("available", False),
        "foreign_trading_days": foreign_flow.get("trading_days"),
        "foreign_avg_daily": foreign_flow.get("avg_daily_eok"),
        "foreign_recent_5d": foreign_flow.get("recent_5d_eok"),
        "foreign_buy_days": foreign_flow.get("buy_days"),
        "foreign_sell_days": foreign_flow.get("sell_days"),
        "supply_gap": supply_gap,
        "opinion": opinion,
        "events": post_events or [],
    }
    timeline["supply_basis"] = build_supply_basis(timeline)
    timeline["supply_read"] = build_supply_read(timeline)
    return timeline
