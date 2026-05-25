"""
signal_engine.py — Financial Signal & Conflict 탐지 엔진 (Week 2 구현)

입력:
  kpis      : {year: {"OPM": float, "ROE": float, ...}}  — kpi_engine.calculate_kpis() 결과
  macro     : {year: {"base_rate": float, ...}}           — data_collector.get_macro_data() 결과 [선택]
  consensus : {year: {"forward_eps": float, ...}}         — data_collector.parse_consensus_csv() 결과 [선택]

출력 구조:
  signals   : list[SignalDict]
  conflicts : list[ConflictDict]
  archetype : str
  evidence  : EvidenceDict

─────────────────────────────────────────────────────────────────────────────
SignalDict 형태:
{
    "category":      "profitability",          # profitability | growth | cashflow | stability | valuation
    "name":          "opm_contraction",        # snake_case 식별자
    "label":         "영업이익률 지속 위축",   # 한국어 표시명
    "direction":     "negative",               # positive | negative | neutral | warning
    "strength":      "High",                   # High | Medium | Low
    "evidence":      "OPM 3년 연속 하락 (12.5% → 9.8% → 7.2%)",
    "kpis_involved": ["OPM"],
}

ConflictDict 형태:
{
    "name":          "earnings_cash_divergence",
    "label":         "이익-현금흐름 괴리",
    "description":   "순이익은 증가했으나 CFO Margin이 하락. 이익의 질(quality) 저하 가능성.",
    "severity":      "High",                   # High | Medium | Low
    "kpis_involved": ["net_income_margin", "CFO_margin"],
}

EvidenceDict 형태:
{
    "level": "Medium",   # High | Medium | Low | Needs Review
    "score": 0.68,       # 0.0~1.0 Analyst Confidence Score
    "basis": "재무제표 데이터 기반. 공시·뉴스 근거 미수집 (Week 3 추가 예정).",
}

Company Archetype (6종):
    "High Growth Premium"  — 고성장 + 고밸류에이션 정당화
    "Stable Compounder"    — 안정적 복리 성장, 견조한 FCF
    "Cyclical Recovery"    — 실적 회복세, 경기 민감 업종
    "Turnaround Candidate" — 적자→흑자 전환 진행 중
    "Value Trap Risk"      — 저밸류이나 펀더멘털 악화
    "Cash Conversion Risk" — 이익은 나지만 현금화 안 됨
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

# ── 타입 별칭 ─────────────────────────────────────────────────────────────────
SignalDict   = dict
ConflictDict = dict
EvidenceDict = dict

# ── Signal 카테고리 상수 ──────────────────────────────────────────────────────
CAT_PROFITABILITY = "profitability"
CAT_GROWTH        = "growth"
CAT_CASHFLOW      = "cashflow"
CAT_STABILITY     = "stability"
CAT_VALUATION     = "valuation"

# ── Archetype 상수 ────────────────────────────────────────────────────────────
ARCHETYPE_HIGH_GROWTH    = "High Growth Premium"
ARCHETYPE_COMPOUNDER     = "Stable Compounder"
ARCHETYPE_CYCLICAL       = "Cyclical Recovery"
ARCHETYPE_TURNAROUND     = "Turnaround Candidate"
ARCHETYPE_VALUE_TRAP     = "Value Trap Risk"
ARCHETYPE_CASH_RISK      = "Cash Conversion Risk"

ALL_ARCHETYPES = [
    ARCHETYPE_HIGH_GROWTH, ARCHETYPE_COMPOUNDER, ARCHETYPE_CYCLICAL,
    ARCHETYPE_TURNAROUND, ARCHETYPE_VALUE_TRAP, ARCHETYPE_CASH_RISK,
]


# ── 공개 API ──────────────────────────────────────────────────────────────────

def generate_financial_signals(kpis: dict) -> list[SignalDict]:
    """
    KPI 딕셔너리 → Financial Signal 리스트 (8개 이상)

    탐지 대상 신호 (Week 2 구현):
    [수익성]
      - OPM 지속 개선 / 위축 (3년 추세)
      - 순이익률 vs OPM 괴리 (세금·이자 효과)
      - ROE 레버리지 분해 (듀퐁 분해 — 수익성 vs 회전율 vs 레버리지)
    [성장성]
      - 매출 가속/감속 성장 (성장률 기울기)
      - 영업이익 성장률 > 매출 성장률 (운영 레버리지)
    [현금흐름]
      - FCF Margin 개선/악화 추세
      - CAPEX Heavy (투자 집중 국면)
    [재무 안정성]
      - 부채비율 급등 경고
      - ROA 하락 (자산 효율성 저하)

    반환: list[SignalDict]  (방향·강도·근거 포함)
    """
    raise NotImplementedError("generate_financial_signals: Week 2 구현 예정")


def detect_conflicts(kpis: dict) -> list[ConflictDict]:
    """
    KPI 딕셔너리 → 지표 간 충돌 신호 리스트 (3개 이상)

    탐지 대상 충돌 (Week 2 구현):
      1. 이익-현금흐름 괴리  — 순이익 ↑ but CFO Margin ↓  (이익의 질 저하)
      2. 성장-수익성 역행    — 매출 ↑ but OPM ↓           (규모의 불경제)
      3. 밸류에이션-펀더멘털 — PER 고평가 but ROE·성장률 ↓ (밸류에이션 버블)
      4. 레버리지-수익성     — 부채비율 ↑ but ROE ↓       (부채 효율 저하)
      5. CAPEX-FCF 역행     — CAPEX Heavy but FCF 음수     (과투자 위험)

    반환: list[ConflictDict]  (심각도·연관 KPI 포함)
    """
    raise NotImplementedError("detect_conflicts: Week 2 구현 예정")


def classify_archetype(kpis: dict) -> str:
    """
    KPI 딕셔너리 → Company Archetype 분류

    분류 로직 (Week 2 구현):
      High Growth Premium  : revenue_growth > 20% AND PER > 25배
      Stable Compounder    : revenue_growth 5~15% AND FCF_margin > 8% AND debt_ratio < 100%
      Cyclical Recovery    : op_income_growth > 50% (저점 회복) AND OPM 상승 추세
      Turnaround Candidate : 최근 연도 OPM > 0 AND 이전 2개년 OPM < 0
      Value Trap Risk      : PBR < 0.8 AND revenue_growth < 0
      Cash Conversion Risk : net_income_margin > 5% AND FCF_margin < 1%

    반환: str — ALL_ARCHETYPES 중 하나
    """
    raise NotImplementedError("classify_archetype: Week 2 구현 예정")


def calculate_market_expectation_gap(
    kpis: dict,
    consensus: dict,
) -> dict:
    """
    현재 KPI vs Consensus(애널리스트 예상) → 시장 기대 괴리 분석 (Week 3 선택)

    Args:
        kpis      : kpi_engine.calculate_kpis() 결과
        consensus : data_collector.parse_consensus_csv() 결과

    반환 형태:
    {
        "forward_per_gap":        3.2,   # 실제 PER - Consensus PER (배)
        "target_price_upside":    12.5,  # (목표주가 - 현재주가) / 현재주가 (%)
        "eps_revision_direction": "up",  # "up" | "down" | "neutral"
        "summary": "컨센서스 대비 PER 3.2배 고평가, 목표주가 상승여력 12.5%",
    }
    """
    raise NotImplementedError("calculate_market_expectation_gap: Week 3 구현 예정")


def map_macro_exposure(kpis: dict, macro: dict) -> dict:
    """
    KPI + 거시 지표 → 매크로 민감도 분석 (Week 2 구현)

    분석 항목:
      - 금리 민감도 (부채비율 높을수록 금리 상승 리스크 ↑)
      - 환율 민감도 (수출 비중, 달러 부채 추정)
      - KOSPI 상관성 (베타 추정)

    반환 형태:
    {
        "rate_sensitivity":   "High",    # High | Medium | Low
        "fx_sensitivity":     "Medium",
        "kospi_correlation":  "High",
        "summary": "고부채 구조로 금리 상승 시 이자비용 증가 리스크 높음",
    }
    """
    raise NotImplementedError("map_macro_exposure: Week 2 구현 예정")


def calculate_evidence_level(
    signals: list[SignalDict],
    conflicts: list[ConflictDict],
    has_news: bool = False,
    has_consensus: bool = False,
) -> EvidenceDict:
    """
    Signal + Conflict 목록 → Evidence Level & Analyst Confidence Score

    산정 기준 (Week 2 구현):
      High        : 재무제표 근거 ≥ 3개 AND (공시/뉴스 OR Consensus 있음)
      Medium      : 재무제표 근거 ≥ 2개 BUT 외부 근거 없음
      Low         : 재무제표 근거 1개 이하 OR 텍스트 추론 중심
      Needs Review: 데이터 충돌(Conflict 수 ≥ 3) 또는 누락 계정 다수

    Confidence Score:
      0.8~1.0 : High evidence, conflict 없음
      0.6~0.79: Medium evidence
      0.4~0.59: Low evidence 또는 conflict 존재
      < 0.4   : Needs Review

    반환: EvidenceDict
    """
    raise NotImplementedError("calculate_evidence_level: Week 2 구현 예정")


def run_full_analysis(
    kpis: dict,
    macro: dict | None = None,
    consensus: dict | None = None,
    has_news: bool = False,
) -> dict:
    """
    전체 Signal 분석 파이프라인 — app.py·report_generator.py에서 호출

    반환 형태:
    {
        "signals":   list[SignalDict],
        "conflicts": list[ConflictDict],
        "archetype": str,
        "macro_exposure": dict,          # macro가 None이면 {}
        "market_gap": dict,              # consensus가 None이면 {}
        "evidence":  EvidenceDict,
    }
    """
    raise NotImplementedError("run_full_analysis: Week 2 구현 예정")


if __name__ == "__main__":
    # Week 2 구현 후 테스트
    # from data_collector import get_financials, get_market_data, get_macro_data
    # from kpi_engine import calculate_kpis
    #
    # fin = get_financials("삼성전자")
    # mkt = get_market_data("삼성전자", years=list(fin.keys()))
    # macro = get_macro_data(years=list(fin.keys()))
    # kpis = calculate_kpis(fin, mkt)
    # result = run_full_analysis(kpis, macro)
    # print(result)
    print("signal_engine.py — Week 2 구현 예정")
    print(f"Archetype 분류 6종: {ALL_ARCHETYPES}")
