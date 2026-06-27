"""모듈2 — 시점 정합성. 리포트 발행 후 무슨 일이 있었나.

발행일을 기준점(t=0)으로 잡고, 그 후 나온 실적·공시·수급·주가를
한 타임라인에 모은다. 수급은 '신호'가 아니라 '리포트 의견 vs 시장
행동의 괴리'로만 제시한다 (리딩방식 단발 신호 금지).
"""
from __future__ import annotations

from datetime import datetime


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
        df = stock.get_market_ohlcv(yyyymmdd, yyyymmdd, stock_code)
        if not df.empty:
            return float(df.iloc[0]["종가"])
    except Exception:
        pass
    return None


def fetch_foreign_net(stock_code: str, pub_date: str) -> int | None:
    """발행 후 외국인 누적 순매수(억). pykrx 사용, 실패 시 None."""
    try:
        from pykrx import stock

        start = pub_date.replace("-", "")
        end = datetime.now().strftime("%Y%m%d")
        df = stock.get_market_trading_value_by_date(start, end, stock_code)
        for col in ("외국인", "외국인합계"):
            if col in df.columns:
                return int(df[col].sum() / 1e8)
    except Exception:
        return None
    return None


def build_post_publish_timeline(
    report: dict,
    current_price: float,
    *,
    stock_code: str | None = None,
    post_events: list[dict] | None = None,
    foreign_net_fallback: int | None = None,
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
    foreign_net = None
    if stock_code:
        foreign_net = fetch_foreign_net(stock_code, pub_date)
    if foreign_net is None:
        foreign_net = (
            foreign_net_fallback if foreign_net_fallback is not None else 0
        )

    opinion = report.get("opinion", "매수")
    supply_gap = (opinion in ("매수", "적극매수")) and foreign_net < 0

    return {
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
        "supply_gap": supply_gap,
        "opinion": opinion,
        "events": post_events or [],
    }
