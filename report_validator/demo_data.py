"""데모 데이터 공급 — DART/리서치 API 키 없이도 전체 플로우가 돌도록.

실제 운영에서는 data_collector(DART)와 research_reference(리포트)가
이 자리를 대신한다. MVP/데모에서는 농심 실제 근사값으로 채운다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


DEMO_COMPANY = {
    "name": "농심",
    "code": "004370",
    "shares_outstanding": 6_082_642,
    "current_price": 415_000,
}

# 연간 EPS 목표(원) — 사업보고서 근사. 분기로 분해해 KPI 엔진에 투입.
_EPS_BY_YEAR = {
    2019: 13_900,
    2020: 25_500,
    2021: 26_240,
    2022: 17_847,
    2023: 39_113,
    2024: 41_000,
}

# 검증 대상 리포트 (research_reference.py의 실제 농심 리포트 기반)
DEMO_REPORT = {
    "broker": "한화투자증권",
    "analyst": "(user-provided PDF)",
    "pub_date": "2026-05-15",
    "opinion": "매수",
    "target_price": 550_000,
    "price_at_pub": 420_000,
    "annual_op_assumption_eok": 2_700,  # 연 영업이익 가정(억)
}

# 같은 종목 다른 증권사 목표가 분포 (모듈1 입력)
# research_reference의 실제 2개(한화 550k·하나 540k) + 분포 맥락용 추가
DEMO_BROKER_TARGETS = [
    {"source": "하나증권 2026-05-18", "target_price": 540_000, "opinion": "매수"},
    {"source": "한화투자증권 2026-05-15", "target_price": 550_000, "opinion": "매수"},
    {"source": "A증권", "target_price": 480_000, "opinion": "중립"},
    {"source": "B증권", "target_price": 500_000, "opinion": "매수"},
    {"source": "C증권", "target_price": 460_000, "opinion": "중립"},
    {"source": "D증권", "target_price": 520_000, "opinion": "매수"},
    {"source": "E증권", "target_price": 445_000, "opinion": "매도"},
    {"source": "F증권", "target_price": 510_000, "opinion": "매수"},
]

# 발행 후 수급·이벤트 (모듈2 입력) — research_reference 드라이버 기반
DEMO_POST_EVENTS = [
    {
        "date": "2026-05-18",
        "type": "실적",
        "detail": "1Q26 영업이익 674억 (컨센 610억 상회 +10.5%)",
    },
    {
        "date": "2026-05-20",
        "type": "수급",
        "detail": "국민연금 보유 7.91%→5.90% 하락",
    },
    {
        "date": "2026-05-22",
        "type": "공시",
        "detail": "녹산 수출공장 투자 2,043억 (26년 10월 완료예정)",
    },
    {"date": "2026-06-01", "type": "정황", "detail": "국내 라면 점유율 55.9% 전년比 하락"},
]
DEMO_FOREIGN_NET_EOK = -180  # 발행 후 외국인 누적 순매수(억)
DEMO_CURRENT_PRICE_NOW = 415_000


def build_demo_financials() -> pd.DataFrame:
    """농심 EPS 궤적을 24분기 재무제표로 분해. calculate_quarterly_kpis 입력용."""
    rows = []
    shares = DEMO_COMPANY["shares_outstanding"]
    for year, eps in _EPS_BY_YEAR.items():
        ni_year = eps * shares
        base_rev = 8_000e8 * (1 + (year - 2019) * 0.03)
        for q in range(1, 5):
            rows.append(
                {
                    "year": year,
                    "quarter": q,
                    "company": DEMO_COMPANY["name"],
                    "period": f"{year}Q{q}",
                    "revenue": base_rev / 4,
                    "operating_profit": base_rev * 0.075 / 4,
                    "net_income": ni_year / 4,
                    "cogs": base_rev * 0.62 / 4,
                    "sga": base_rev * 0.25 / 4,
                    "cfo": base_rev * 0.06 / 4,
                    "depreciation": base_rev * 0.025 / 4,
                    "capex": base_rev * 0.031 / 4,
                    "receivables": base_rev * 0.12,
                    "inventory": base_rev * 0.10,
                    "payables": base_rev * 0.075,
                    "cash": 2_000e8,
                    "debt": 1_000e8,
                    "total_assets": 15_000e8,
                    "total_liabilities": 5_000e8,
                    "total_equity": 10_000e8,
                    "current_assets": 6_000e8,
                    "current_liabilities": 3_000e8,
                }
            )
    return pd.DataFrame(rows)


def get_demo_valuation_reference() -> dict:
    """diagnostics.calculate_multiple_valuation이 받는 형식."""
    return {
        "per_band": [10.0, 12.0, 14.0],
        "ev_ebitda_band": [5.0, 6.0, 7.0],
        "broker_targets": DEMO_BROKER_TARGETS,
    }


def build_demo_peers() -> dict[str, pd.DataFrame]:
    """동종기업(삼양식품·오뚜기) 데모 분기 데이터. build_peer_benchmark 입력용."""
    peers = {}
    # (회사명, 매출배수, OPM수준, 성장률) — 농심 대비 상대 특성
    specs = {
        "삼양식품": {"rev_mult": 0.45, "opm": 0.16, "growth": 0.25},
        "오뚜기": {"rev_mult": 0.85, "opm": 0.065, "growth": 0.04},
    }
    for name, s in specs.items():
        rows = []
        for year in range(2022, 2025):
            base_rev = 8_000e8 * s["rev_mult"] * (1 + (year - 2022) * s["growth"])
            for q in range(1, 5):
                rows.append(
                    {
                        "year": year,
                        "quarter": q,
                        "company": name,
                        "period": f"{year}Q{q}",
                        "revenue": base_rev / 4,
                        "operating_profit": base_rev * s["opm"] / 4,
                        "net_income": base_rev * s["opm"] * 0.75 / 4,
                        "cogs": base_rev * 0.62 / 4,
                        "sga": base_rev * 0.25 / 4,
                        "cfo": base_rev * 0.06 / 4,
                        "depreciation": base_rev * 0.025 / 4,
                        "capex": base_rev * 0.03 / 4,
                        "receivables": base_rev * 0.12,
                        "inventory": base_rev * 0.10,
                        "payables": base_rev * 0.075,
                        "cash": 1_000e8,
                        "debt": 500e8,
                        "total_assets": 8_000e8,
                        "total_liabilities": 3_000e8,
                        "total_equity": 5_000e8,
                        "current_assets": 3_500e8,
                        "current_liabilities": 1_800e8,
                    }
                )
        peers[name] = pd.DataFrame(rows)
    return peers
