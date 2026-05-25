"""
kpi_engine.py — 재무·밸류에이션 KPI 계산 엔진

입력:
  financials  : {year: {"매출액": int, "영업이익": int, ...}} — 단위 백만원 (data_collector.get_financials)
                financials[year]["EPS"] — 원/주 단위 (백만원 변환 없음)
  market_data : {year: {"price": float}} — 연말 종가, 원 (data_collector.get_market_data) [선택]

출력:
  {year: {"OPM": float, "net_income_margin": float, "ROE": float, "ROA": float,
          "PER": float, "PBR": float, "PSR": float, "market_cap": int, ...}}
"""


def _pct(numerator, denominator) -> float | None:
    """비율 계산 (%) — 분모 0·None 방어"""
    if not denominator or numerator is None:
        return None
    return round(numerator / denominator * 100, 2)


def _ratio(numerator, denominator) -> float | None:
    """배수 계산 (배) — 분모 0·None 방어"""
    if not denominator or numerator is None:
        return None
    return round(numerator / denominator, 2)


def calculate_kpis(financials: dict, market_data: dict | None = None) -> dict:
    """
    재무 데이터 → KPI 계산

    반환 형태:
    {
        2024: {
            "OPM": 12.5,               # 영업이익률 (%)
            "net_income_margin": 9.8,  # 순이익률 (%)
            "ROE": 18.3,               # 자기자본이익률 (%)
            "ROA": 6.1,                # 총자산이익률 (%)
            "debt_ratio": 42.1,        # 부채비율 = 부채총계 / 자본총계 (%)
            "CFO_margin": 15.2,        # 영업활동현금흐름 / 매출액 (%)
            "CAPEX_ratio": 8.1,        # CAPEX / 매출액 (%)
            "FCF_margin": 7.1,         # (CFO - CAPEX) / 매출액 (%)
            "revenue_growth": 5.3,     # 전년 대비 매출액 성장률 (%)
            "op_income_growth": 8.2,   # 전년 대비 영업이익 성장률 (%)
            "PER": 18.5,               # 주가 / EPS (배)
            "PBR": 2.1,                # 시가총액 / 자본총계 (배)
            "PSR": 1.8,                # 시가총액 / 매출액 (배)
            "market_cap": 350000000,   # 시가총액 (백만원, EPS 역산 추정)
        },
        2023: {...},
    }
    값이 계산 불가(분모 0, 데이터 누락)인 항목은 None으로 반환
    """
    sorted_years = sorted(financials.keys())
    result = {}

    for i, year in enumerate(sorted_years):
        d = financials[year]

        revenue    = d.get("매출액")
        op_income  = d.get("영업이익")
        net_income = d.get("당기순이익")
        assets     = d.get("자산총계")
        liab       = d.get("부채총계")
        equity     = d.get("자본총계")
        cfo        = d.get("영업활동현금흐름")
        capex      = d.get("CAPEX")
        eps        = d.get("EPS")  # 원/주 단위, 백만원 변환 없음

        kpis: dict = {}

        # ── 수익성 ──────────────────────────────────────────────
        kpis["OPM"]               = _pct(op_income, revenue)
        kpis["net_income_margin"] = _pct(net_income, revenue)

        # equity ≤ 0(자본잠식)이면 ROE·부채비율 의미 없음 → None
        equity_positive = equity is not None and equity > 0
        kpis["ROE"]        = _pct(net_income, equity) if equity_positive else None
        kpis["ROA"]        = _pct(net_income, assets)
        kpis["debt_ratio"] = _pct(liab, equity)       if equity_positive else None

        # ── 현금흐름 ─────────────────────────────────────────────
        kpis["CFO_margin"]  = _pct(cfo, revenue)
        kpis["CAPEX_ratio"] = _pct(capex, revenue)

        # FCF margin = (CFO - CAPEX) / 매출액
        if cfo is not None and capex is not None and revenue:
            kpis["FCF_margin"] = round((cfo - capex) / revenue * 100, 2)
        else:
            kpis["FCF_margin"] = None

        # ── 성장률 — 첫 연도는 비교 대상 없으므로 None ────────────
        if i > 0:
            prev     = financials[sorted_years[i - 1]]
            prev_rev = prev.get("매출액")
            prev_op  = prev.get("영업이익")
            kpis["revenue_growth"]   = _pct(revenue - prev_rev, abs(prev_rev)) if (prev_rev and revenue is not None) else None
            kpis["op_income_growth"] = _pct(op_income - prev_op, abs(prev_op)) if (prev_op and op_income is not None) else None
        else:
            kpis["revenue_growth"]   = None
            kpis["op_income_growth"] = None

        # ── 밸류에이션 ───────────────────────────────────────────
        # PER = 주가 / EPS
        # 시가총액 역산: shares ≈ 당기순이익(백만원) × 1_000_000 / EPS → mkt_cap = price × shares (백만원)
        # PBR = 시가총액 / 자본총계,  PSR = 시가총액 / 매출액
        price = market_data[year].get("price") if (market_data and year in market_data) else None

        kpis["PER"] = round(price / eps, 2) if (price and eps and eps > 0) else None

        market_cap: int | None = None
        if price and eps and eps > 0 and net_income and net_income > 0:
            shares_est = (net_income * 1_000_000) / eps        # 주식수 역산 (주)
            market_cap = int(price * shares_est) // 1_000_000  # 원 → 백만원

        kpis["market_cap"] = market_cap
        kpis["PBR"] = round(market_cap / equity, 2)   if (market_cap and equity_positive) else None
        kpis["PSR"] = round(market_cap / revenue, 2)  if (market_cap and revenue)         else None

        result[year] = kpis

    return result


if __name__ == "__main__":
    from data_collector import get_financials, get_market_data

    companies = ["삼성전자", "농심", "에이피알"]
    for company in companies:
        print(f"\n{'='*55}")
        print(f"[{company}] KPI 계산 중...")
        fin = get_financials(company)
        mkt = get_market_data(company, years=list(fin.keys()))
        if not fin:
            print("  재무 데이터 없음")
            continue
        kpis = calculate_kpis(fin, mkt)
        for year in sorted(kpis):
            print(f"\n  {year}년:")
            for k, v in kpis[year].items():
                if v is None:
                    print(f"    {k}: N/A")
                elif k == "market_cap":
                    print(f"    {k}: {v:,.0f} 백만원 ({v / 1_000_000:.1f} 조원)")
                elif k in ("PER", "PBR", "PSR"):
                    print(f"    {k}: {v:.2f}배")
                elif k == "debt_ratio":
                    print(f"    {k}: {v:.2f}%")
                else:
                    print(f"    {k}: {v:.2f}%")
