"""모듈2 — 시점 정합성. 리포트 발행 후 무슨 일이 있었나.

발행일을 기준점(t=0)으로 잡고, 그 후 나온 실적·공시·수급·주가를
한 타임라인에 모은다. 수급은 '신호'가 아니라 '리포트 의견 vs 시장
행동의 괴리'로만 제시한다 (리딩방식 단발 신호 금지).
"""
from __future__ import annotations

import contextlib
import io
import time
from datetime import datetime, timedelta

import pandas as pd


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


def _parse_ymd(ymd: str) -> datetime:
    return datetime.strptime(str(ymd)[:10], "%Y-%m-%d")


def fetch_price_at_date_info(stock_code: str, ymd: str, lookback_days: int = 21) -> dict | None:
    """리포트 발행일 기준 종가.

    발행일이 휴장일이면 직전 거래일 종가를 사용한다. 실패 시 현재가로
    대체하지 않는다. 현재가 폴백은 발행 이후 수익률을 0%처럼 왜곡하기 때문이다.
    """
    if not stock_code or not ymd:
        return None
    try:
        from pykrx import stock

        target = _parse_ymd(ymd)
        start = (target - timedelta(days=lookback_days)).strftime("%Y%m%d")
        end = target.strftime("%Y%m%d")
        df = None
        for attempt in range(2):
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    df = stock.get_market_ohlcv(start, end, stock_code)
                break
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
                else:
                    raise
        if df is not None and not df.empty:
            row = df.sort_index().iloc[-1]
            trade_date = _iso_date(df.sort_index().index[-1])
            return {
                "price": float(row["종가"]),
                "date": trade_date,
                "requested_date": target.strftime("%Y-%m-%d"),
                "source": "KRX 일별 종가",
                "is_exact_date": trade_date == target.strftime("%Y-%m-%d"),
            }
    except Exception:
        pass
    try:
        import FinanceDataReader as fdr

        target = _parse_ymd(ymd)
        start = (target - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = (target + timedelta(days=1)).strftime("%Y-%m-%d")
        prices = None
        for attempt in range(2):
            try:
                prices = fdr.DataReader(stock_code, start, end)
                break
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
                else:
                    raise
        if prices is not None and not prices.empty and "Close" in prices:
            row = prices.sort_index().iloc[-1]
            trade_date = _iso_date(prices.sort_index().index[-1])
            return {
                "price": float(row["Close"]),
                "date": trade_date,
                "requested_date": target.strftime("%Y-%m-%d"),
                "source": "FinanceDataReader 종가",
                "is_exact_date": trade_date == target.strftime("%Y-%m-%d"),
            }
    except Exception:
        pass
    return None


def fetch_price_at_date(stock_code: str, ymd: str) -> float | None:
    """지정된 날짜 또는 직전 거래일의 종가. 실패 시 None."""
    info = fetch_price_at_date_info(stock_code, ymd)
    return info.get("price") if info else None


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
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


def fetch_investor_flow_since(stock_code: str, start_date: str, as_of: str | None = None) -> dict | None:
    """특정 이벤트 이후 투자자별 누적 순매수(억원).

    외국인만으로는 해석이 너무 얕아질 수 있어 기관 세부 주체까지 같이
    가져온다. KRX가 컬럼을 다르게 제공하면 확인 가능한 그룹만 반환한다.
    """
    if not stock_code or not start_date:
        return None
    try:
        from pykrx import stock

        start = start_date.replace("-", "")
        end = (as_of or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = stock.get_market_trading_value_by_date(start, end, stock_code, detail=True)
        if df is None or df.empty:
            return None
        numeric = df.apply(lambda col: pd.to_numeric(col, errors="coerce"))

        def series_for(cols: list[str]):
            present = [col for col in cols if col in numeric.columns]
            aggregate = next((col for col in present if col.endswith("합계")), None)
            present = [aggregate] if aggregate else present
            if not present:
                return None
            series = numeric[present].sum(axis=1, min_count=1).dropna()
            return series if not series.empty else None

        groups = {
            "foreign": series_for(["외국인합계", "외국인", "기타외국인"]),
            "institution": series_for(["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]),
            "retail": series_for(["개인"]),
            "financial_investment": series_for(["금융투자"]),
            "investment_trust": series_for(["투신"]),
            "private_fund": series_for(["사모"]),
            "pension": series_for(["연기금"]),
        }

        def eok(series):
            if series is None:
                return None
            return round(float(series.sum()) / 1e8, 1)

        detail = {key: eok(series) for key, series in groups.items()}
        available = any(value is not None for value in detail.values())
        if not available:
            return None
        return {
            **detail,
            "start": _iso_date(df.index[0]),
            "end": _iso_date(df.index[-1]),
            "trading_days": int(len(df)),
            "source": "KRX 투자자별 거래대금",
            "available": True,
        }
    except Exception:
        return None


def _fallback_foreign_flow(value: int | None, pub_date: str, as_of: str | None) -> dict:
    return {
        "net_eok": int(value) if value is not None else None,
        "start": pub_date,
        "end": as_of or datetime.now().strftime("%Y-%m-%d"),
        "trading_days": None,
        "avg_daily_eok": None,
        "recent_5d_eok": None,
        "buy_days": None,
        "sell_days": None,
        "source": "수급 미확인" if value is None else "보조 수급값",
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
    current_price: float | None,
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

    price_at_pub = _safe_float(report.get("price_at_pub"))
    current = _safe_float(current_price)
    target = float(report["target_price"])
    orig_upside = None
    realized = None
    soak_pct = None
    if price_at_pub and price_at_pub > 0:
        orig_upside = (target / price_at_pub - 1) * 100
        realized = (current / price_at_pub - 1) * 100 if current and current > 0 else None
        # 발행 시점 상승여력이 양(+)일 때만 '소진율'이 의미가 있다.
        # 목표가가 발행가보다 낮은(하향) 리포트면 소진 개념이 성립하지 않는다.
        if orig_upside > 0 and realized is not None:
            soak_pct = round(realized / orig_upside * 100)
        elif orig_upside <= 0:
            soak_pct = 0
    else:
        price_at_pub = None
    remaining = (target / current - 1) * 100 if current and current > 0 else None

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
    supply_gap = (opinion in ("매수", "적극매수")) and foreign_net is not None and foreign_net < 0
    timeline = {
        "pub_date": pub_date,
        "price_at_pub": round(price_at_pub) if price_at_pub else None,
        "price_at_pub_date": (report.get("price_at_pub_date") or pub_date) if price_at_pub else None,
        "price_at_pub_requested_date": report.get("price_at_pub_requested_date") or pub_date,
        "price_at_pub_source": report.get("price_at_pub_source") or ("KRX 일별 종가" if price_at_pub else "확인 불가"),
        "price_at_pub_available": bool(price_at_pub),
        "target_price": round(target),
        "elapsed": elapsed,
        "months": round(elapsed / 30, 1),
        "orig_upside": round(orig_upside, 1) if orig_upside is not None else None,
        "realized": round(realized, 1) if realized is not None else None,
        "remaining": round(remaining, 1) if remaining is not None else None,
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
