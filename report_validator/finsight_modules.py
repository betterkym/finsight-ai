"""모듈1(분포)·모듈3(역산) — 공간축과 논리축 검증.

기존 diagnostics.py를 건드리지 않고 별도로 구현.
diagnostics의 calculate_multiple_valuation/build_valuation_range는 그대로 쓰고,
여기에 '목표가 역산 + 변동성 보정'(모듈3)과 '분포 위치'(모듈1)만 더한다.
"""
from __future__ import annotations

import statistics
from collections import Counter
from statistics import NormalDist

import pandas as pd

from core.kpi_engine import annualize_quarters

# 증권사 목표가 분산을 컨센서스 평균의 12%로 가정한다(국내 커버리지 실증 근사).
# 네이버는 평균값만 제공하므로, '평균 대비 위치'를 z로 환산할 때 쓰는 표준편차 추정치.
_ASSUMED_TARGET_CV = 0.12


def locate_vs_consensus(target_price: float, consensus: dict) -> dict:
    """검증 목표가가 시장 컨센서스 평균 대비 어디인지 판단(모듈1, 평균 기반).

    네이버는 증권사별 목표가 리스트 대신 '컨센서스 평균'만 제공한다.
    개별 분포가 없으므로 평균 대비 괴리율을 표준편차 추정으로 z화한다.

    Args:
        target_price: 검증할 리포트의 목표가
        consensus: {"price_target_mean": float, ...}

    Returns:
        score_space가 읽는 형식(z, top_pct, insufficient 등)을 포함한 dict
    """
    mean = (consensus or {}).get("price_target_mean")
    if not mean or mean <= 0:
        return {
            "n": 0, "mean": target_price, "median": target_price, "std": 0.0,
            "this_target": round(target_price), "top_pct": 50, "z": 0.0,
            "vs_median_pct": 0.0, "position": "비교 불가", "insufficient": True,
        }

    gap_pct = (target_price - mean) / mean * 100
    assumed_std = mean * _ASSUMED_TARGET_CV
    z = (target_price - mean) / assumed_std if assumed_std else 0.0
    top_pct = round((1 - NormalDist().cdf(z)) * 100)
    top_pct = min(99, max(1, top_pct))

    if z > 0.5:
        position = "평균보다 공격적"
    elif z < -0.5:
        position = "평균보다 보수적"
    else:
        position = "컨센서스 평균권"

    return {
        "n": None,  # 증권사 개수는 알 수 없음(평균만 제공)
        "mean": float(mean),
        "median": float(mean),
        "std": float(assumed_std),
        "this_target": round(target_price),
        "top_pct": top_pct,
        "z": round(z, 2),
        "vs_median_pct": round(gap_pct, 1),
        "position": position,
        "insufficient": False,
        "assumed_std": True,
        "recomm_label": (consensus or {}).get("opinion_label", ""),
        "create_date": (consensus or {}).get("create_date", ""),
    }


def reverse_engineer_target(
    target_price: float,
    kpis: pd.DataFrame,
    shares_outstanding: float,
    current_price: float,
) -> dict:
    """목표가를 '필요 EPS 성장률'로 역산하고 과거 변동성으로 보정한다. (모듈3 코어)

    개인투자자는 목표가를 '결론'으로만 받는다. 이 함수는 그 목표가가
    성립하려면 회사가 얼마나 성장해야 하는지를 역산하고, 과거 실적과 대조한다.
    핵심은 '변동성 보정' — 단순 평균은 기저효과(한 해 +119% 등)로 오염되어
    낙관을 현실적으로 오판하게 만들기 때문에, 변동성이 크면 중앙값을 쓴다.
    """
    annual = annualize_quarters(kpis)
    if annual.empty or "net_income" not in annual:
        raise ValueError("역산에 필요한 연간 순이익 데이터가 없습니다.")
    eps_frame = annual[["year", "net_income"]].copy()
    eps_frame["eps"] = eps_frame["net_income"] / float(shares_outstanding)
    eps_frame = eps_frame.dropna(subset=["eps"])
    eps_series = eps_frame["eps"].tolist()
    if len(eps_series) < 3:
        raise ValueError("역산에는 최소 3개 완전연도 EPS가 필요합니다.")

    current_eps = eps_series[-1]
    if current_eps <= 0:
        raise ValueError("최근 EPS가 0 이하라 PER 역산이 불가능합니다.")
    current_per = current_price / current_eps
    need_eps = target_price / current_per
    need_growth = (need_eps / current_eps - 1) * 100

    growths = [
        (eps_series[i] / eps_series[i - 1] - 1) * 100
        for i in range(1, len(eps_series))
        if eps_series[i - 1] > 0
    ]
    years = eps_frame["year"].astype(int).tolist()
    growth_labels = [
        f"{years[i - 1]}→{years[i]}"
        for i in range(1, len(eps_series))
        if eps_series[i - 1] > 0
    ]
    avg = statistics.mean(growths)
    median = statistics.median(growths)
    std = statistics.pstdev(growths)
    cv = std / abs(avg) if avg else float("inf")

    if cv > 1.5:
        volatility, reference = "매우높음", median
    elif cv > 0.8:
        volatility, reference = "높음", median
    else:
        volatility, reference = "양호", avg

    if need_growth > max(growths):
        verdict = "과도한 낙관"
    elif need_growth > reference:
        verdict = "낙관"
    else:
        verdict = "현실적"

    return {
        "target_price": target_price,
        "current_price": current_price,
        "current_eps": round(current_eps),
        "need_eps": round(need_eps),
        "current_per": round(current_per, 1),
        "need_growth": round(need_growth, 1),
        "avg_growth": round(avg, 1),
        "median_growth": round(median, 1),
        "cv": round(cv, 1),
        "volatility": volatility,
        "reference_growth": round(reference, 1),
        "multiple": round(need_growth / reference, 1) if reference else None,
        "verdict": verdict,
        "growth_history": [round(g, 1) for g in growths],
        "growth_labels": growth_labels,
    }


def aggregate_opinions(broker_targets: list[dict]) -> dict:
    """증권사 투자의견(매수/중립/매도) 집계. (모듈1 보조)"""
    counter = Counter(str(t.get("opinion", "매수")) for t in broker_targets)
    buy = counter.get("매수", 0) + counter.get("적극매수", 0) + counter.get("Buy", 0)
    hold = counter.get("중립", 0) + counter.get("보유", 0) + counter.get("Hold", 0)
    sell = counter.get("매도", 0) + counter.get("Sell", 0)
    total = max(buy + hold + sell, 1)
    return {
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "total": total,
        "buy_ratio": round(buy / total * 100, 1),
        "has_sell": sell > 0,
    }


def locate_in_distribution(target_price: float, broker_targets: list[dict]) -> dict:
    """이 목표가가 전체 목표가 분포에서 어디인지 계산. (모듈1 핵심)

    비교 대상이 1개 이하여도 깨지지 않도록 안전한 기본값을 채운다.
    """
    prices = [float(t["target_price"]) for t in broker_targets if t.get("target_price")]
    if len(prices) < 2:
        # 비교 불가 — 자기 자신 정보만으로 중립 기본값
        only = round(target_price)
        return {
            "n": len(prices),
            "median": only,
            "mean": only,
            "min": only,
            "max": only,
            "this_target": only,
            "top_pct": 50,
            "z": 0.0,
            "vs_median_pct": 0.0,
            "position": "비교 불가",
            "insufficient": True,
        }
    median = statistics.median(prices)
    mean = statistics.mean(prices)
    std = statistics.pstdev(prices)
    below = sum(1 for p in prices if p < target_price)
    top_pct = round((1 - below / len(prices)) * 100)
    z = (target_price - mean) / std if std else 0.0
    if z > 0.5:
        position = "다소 높음"
    elif z < -0.5:
        position = "다소 낮음"
    else:
        position = "평균권"
    return {
        "n": len(prices),
        "median": round(median),
        "mean": round(mean),
        "min": round(min(prices)),
        "max": round(max(prices)),
        "this_target": round(target_price),
        "top_pct": top_pct,
        "z": round(z, 2),
        "vs_median_pct": round((target_price / median - 1) * 100, 1),
        "position": position,
        "insufficient": False,
    }
