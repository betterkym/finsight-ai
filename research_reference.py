"""Structured facts extracted from user-supplied research PDFs for POC validation.

The service consumes facts, valuation conventions and falsifiable checkpoints rather
than reproducing report prose. Future uploaded reports can be normalized to this schema.
"""
from __future__ import annotations


RESEARCH_LIBRARY = {
    "농심": {
        "expectations": [
            {
                "date": "2026-05-15", "source": "한화투자증권 기업분석 (user-provided PDF)",
                "fact": "1Q26 영업이익 674억원으로 컨센서스 610억원을 상회",
                "metric": "operating_profit_surprise", "value": 10.5, "unit": "%",
                "evidence_level": "Broker estimate comparison",
            },
            {
                "date": "2026-05-18", "source": "하나증권 Earnings Review (user-provided PDF)",
                "fact": "1Q26 영업이익 컨센서스 대비 11.9% 상회",
                "metric": "operating_profit_surprise", "value": 11.9, "unit": "%",
                "evidence_level": "Broker estimate comparison",
            },
        ],
        "drivers": [
            {"theme": "국내", "fact": "국내 라면 점유율 55.9%, 전년 대비 하락", "impact": "Risk", "source": "한화·하나증권 1Q26 리뷰"},
            {"theme": "미주", "fact": "미국 매출은 증가했으나 물량은 감소해 가격·에누리 효과 비중이 큼", "impact": "Watch", "source": "하나증권 1Q26 리뷰"},
            {"theme": "유럽", "fact": "유럽 판매법인 매출 약 370억원, 유통사 직거래와 신제품 확장", "impact": "Catalyst", "source": "한화·하나증권 1Q26 리뷰"},
            {"theme": "설비", "fact": "녹산 수출전용공장 투자 2,043억원, 완료 예정 2026년 10월", "impact": "Catalyst/Risk", "source": "DART 시설투자 공시·user-provided PDF"},
            {"theme": "수급", "fact": "국민연금 보유비율 7.91%에서 5.90%로 하락", "impact": "Flow Risk", "source": "DART 대량보유 공시·user-provided PDF"},
        ],
        "valuation": {
            "per_band": [12.0, 14.0, 16.0, 18.0],
            "ev_ebitda_band": [4.0, 5.0, 6.0],
            "broker_targets": [
                {"source": "하나증권 2026-05-18", "target_price": 540000},
                {"source": "한화투자증권 2026-05-15", "target_price": 550000},
            ],
            "note": "리포트는 12M forward PER 밴드와 이익 추정치로 목표가를 교차검증",
        },
        "checkpoints": [
            "해외 매출 성장과 해외 이익률이 동시에 개선되는가",
            "미주 성장이 가격 효과가 아닌 물량 회복으로 전환되는가",
            "녹산 공장 투자비·준공 일정이 추가로 악화되지 않는가",
            "국내 라면 점유율 하락이 멈추는가",
            "기관 매도 이후 외국인·기관 수급이 실적 개선과 함께 회복되는가",
        ],
    },
    "에이피알": {
        "expectations": [],
        "drivers": [
            {"theme": "채널", "fact": "미국 대형 오프라인 리테일러 입점 확대", "impact": "Catalyst", "source": "DS투자증권 2026-05-28"},
            {"theme": "지역", "fact": "유럽 주요 5개국 온·오프라인 확장 초기", "impact": "Catalyst", "source": "DS투자증권 2026-05-28"},
        ],
        "valuation": {
            "per_band": [22.0, 25.0, 28.6, 32.0],
            "ev_ebitda_band": [16.0, 19.0, 22.0],
            "broker_targets": [{"source": "DS투자증권 2026-05-28", "target_price": 610000}],
            "note": "27F EPS 21,020원에 Target PER 28.6배를 적용한 사례",
        },
        "checkpoints": ["미국 오프라인 입점이 sell-in 이후 sell-through로 이어지는가", "유럽 신규 국가 매출이 판관비 증가를 상쇄하는가"],
    },
}


def get_research_reference(company: str) -> dict:
    return RESEARCH_LIBRARY.get(company, {"expectations": [], "drivers": [], "valuation": {}, "checkpoints": []})
