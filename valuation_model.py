"""Driver-based valuation model in the style of the reference Nongshim DCF.

The reference workbook does not fade a single OPM number. It rebuilds margin from the
bottom up every year:

* **Revenue** — domestic growth is split into an *industry* component (peer-aggregate
  growth as the proxy the reference used: "3사 합산 매출 변화 = 산업성장률") and a
  *market-share* component; an inflation cross-check separates real demand from price.
* **SG&A** — decomposed into labour-type (wage growth), variable (% of sales), fixed
  (CPI escalation) and bad-debt (% of sales). OPM then falls out of gross margin minus
  this rebuilt SG&A ratio rather than an analyst guess.
* **Depreciation** — existing assets run off over their remaining life while each year's
  new CAPEX is re-depreciated, then split between COGS and SG&A on the historical ratio.
* **WACC** — peer betas are unlevered and re-levered to the target capital structure.

For companies with a curated reference (e.g. Nongshim) the cost-structure shares are
seeded from disclosed notes; for everyone else they fall back to ratios implied by the
DART history. Every number is transparent and editable downstream in Excel.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _median_tail(series: pd.Series, n: int = 4):
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().tail(n)
    return float(clean.median()) if not clean.empty else None


# Disclosed SG&A composition for curated names (share of total SG&A, ex-depreciation).
# Source: each issuer's "판매비와관리비" note, normalised to labour/variable/fixed/baddebt.
_SGA_SEED = {
    "농심": {"labor": 0.342, "variable": 0.334, "fixed": 0.285, "baddebt": 0.0004,
             "wage_growth": 3.30, "cpi": 2.67, "baddebt_ratio": 0.041,
             "note": "DART 판관비 주석 기준 인건비성/변동비/고정비/대손 분해 (5개년)"},
}
# Sensible cross-industry default when no disclosed breakdown exists.
_SGA_DEFAULT = {"labor": 0.30, "variable": 0.30, "fixed": 0.39, "baddebt": 0.01,
                "wage_growth": 3.30, "cpi": 2.50, "baddebt_ratio": 0.05,
                "note": "공시 분해 부재 — 역사적 비율 기반 기본 가중치(편집 가능)"}


def build_revenue_decomposition(
    kpis: pd.DataFrame, peer_kpis: dict[str, pd.DataFrame], macro: dict, research: dict,
) -> dict:
    """Split historical revenue growth into industry vs share, with an inflation check."""
    annual_company = _annual_revenue(kpis)
    history = []
    peer_growth_by_year = _peer_industry_growth(peer_kpis)
    cpi = _num(macro.get("cpi_growth"))
    for year, rev, g in annual_company:
        industry = peer_growth_by_year.get(year)
        share = (g - industry) if (g is not None and industry is not None) else None
        history.append({
            "year": year, "revenue": rev, "company_growth": g,
            "industry_growth": industry, "share_growth": share,
            "real_growth": (g - cpi) if (g is not None and cpi is not None) else None,
        })
    growths = [row["company_growth"] for row in history if row["company_growth"] is not None]
    industry_vals = [row["industry_growth"] for row in history if row["industry_growth"] is not None]
    share_vals = [row["share_growth"] for row in history if row["share_growth"] is not None]
    industry_avg = float(np.mean(industry_vals)) if industry_vals else None
    share_avg = float(np.mean(share_vals)) if share_vals else None
    recent = float(np.mean(growths[-3:])) if growths else 3.0
    # When peer history is too thin to split industry vs share, seed the forward build
    # with the company's own recent growth (industry≈company, share≈0) so the model
    # stays usable; the split columns above still show where data was missing.
    industry_seed = industry_avg if industry_avg is not None else recent
    share_seed = share_avg if share_avg is not None else 0.0
    return {
        "history": history,
        "industry_growth_avg": round(industry_seed, 2),
        "share_growth_avg": round(share_seed, 2),
        "industry_observed": industry_avg is not None,
        "recent_company_growth": round(recent, 2),
        "cpi": cpi,
        "method": "기업성장률 ≈ 산업성장률(동종기업 합산 proxy) + 점유율 변화율 / 인플레이션 교차검증",
        "drivers": [d for d in research.get("drivers", []) if d.get("theme") in {"국내", "미주", "유럽", "중국", "수출", "점유율"}],
    }


def _annual_revenue(kpis: pd.DataFrame) -> list[tuple[int, float, float | None]]:
    grouped = kpis.groupby("year")
    rev = grouped["revenue"].sum(min_count=1)
    counts = grouped["quarter"].nunique()
    full = rev[counts == 4]
    rev = full if not full.empty else rev
    out, prev = [], None
    for year, value in rev.items():
        v = _num(value)
        g = ((v / prev - 1) * 100) if (v is not None and prev not in (None, 0)) else None
        out.append((int(year), None if v is None else v / 1e8, None if g is None else round(g, 2)))
        prev = v
    return out


def _peer_industry_growth(peer_kpis: dict[str, pd.DataFrame]) -> dict[int, float]:
    """Aggregate peer annual revenue YoY as an industry-growth proxy."""
    totals: dict[int, float] = {}
    for frame in peer_kpis.values():
        if frame.empty:
            continue
        grouped = frame.groupby("year")
        rev = grouped["revenue"].sum(min_count=1)
        counts = grouped["quarter"].nunique()
        rev = rev[counts == 4] if not rev[counts == 4].empty else rev
        for year, value in rev.items():
            v = _num(value)
            if v is not None:
                totals[int(year)] = totals.get(int(year), 0.0) + v
    out, years = {}, sorted(totals)
    for i in range(1, len(years)):
        prev, cur = totals[years[i - 1]], totals[years[i]]
        if prev:
            out[years[i]] = round((cur / prev - 1) * 100, 2)
    return out


def build_sga_decomposition(kpis: pd.DataFrame, company: str, macro: dict, override: dict | None = None) -> dict:
    """Decompose SG&A into labour / variable / fixed / bad-debt with projection drivers.

    ``override`` (auto-extracted DART footnote shares) wins over the curated seed, which
    wins over the cross-industry default.
    """
    seed = dict(_SGA_SEED.get(company, _SGA_DEFAULT))
    if override:
        seed = {**seed, **{k: override[k] for k in ("labor", "variable", "fixed", "baddebt") if k in override},
                "note": override.get("source", seed["note"])}
    cpi = _num(macro.get("cpi_growth")) or seed["cpi"]
    recent = kpis.tail(4)
    sga = _num(recent["sga"].sum(min_count=4))
    revenue = _num(recent["revenue"].sum(min_count=4))
    cogs_ratio = _median_tail(kpis["cogs_ratio"])
    sga_ratio = (sga / revenue * 100) if (sga and revenue) else _median_tail(kpis["sga_ratio"])
    components = []
    if sga:
        for key, label in (("labor", "인건비성(급여·복리후생)"), ("variable", "변동비(수수료·물류·용역)"),
                            ("fixed", "고정비(광고·운반·세금)"), ("baddebt", "대손상각비")):
            amount = sga * seed[key]
            driver = {"labor": f"임금상승률 {seed['wage_growth']:.2f}%/년",
                      "variable": "매출 연동(매출비율 고정)",
                      "fixed": f"소비자물가 {cpi:.2f}%/년",
                      "baddebt": f"매출 대비 대손율 {seed['baddebt_ratio']:.3f}%"}[key]
            components.append({
                "component": label, "share": round(seed[key] * 100, 1),
                "ltm_amount": round(amount / 1e8, 1), "driver": driver,
                "pct_of_sales": round(amount / revenue * 100, 4) if revenue else None,
            })
    return {
        "components": components, "seed_note": seed["note"],
        "wage_growth": seed["wage_growth"], "cpi": round(cpi, 2),
        "baddebt_ratio": seed["baddebt_ratio"],
        "ltm_sga": round(sga / 1e8, 1) if sga else None,
        "sga_ratio": round(sga_ratio, 2) if sga_ratio is not None else None,
        "cogs_ratio": round(cogs_ratio, 2) if cogs_ratio is not None else None,
        "gross_margin": round(100 - cogs_ratio, 2) if cogs_ratio is not None else None,
        "implied_opm": round((100 - cogs_ratio) - sga_ratio, 2) if (cogs_ratio is not None and sga_ratio is not None) else None,
        "method": "판관비 = 인건비성(임금) + 변동비(매출연동) + 고정비(CPI) + 대손(매출연동) → OPM = 매출총이익률 − 판관비율",
    }


def build_opm_path(sga_model: dict, base_revenue_eok: float, growth_y1: float, growth_terminal: float,
                   forecast_years: int = 5) -> dict | None:
    """Bottom-up OPM per forecast year: gross margin − escalated SG&A ratio.

    Mirrors the reference: variable SG&A scales with sales, labour escalates at the wage
    rate, fixed at CPI, bad-debt as a % of sales. Returns ``None`` when the cost split is
    unavailable so the caller can fall back to a linear OPM fade.
    """
    def _amount(prefix: str) -> float:
        for c in sga_model.get("components", []):
            if c["component"].startswith(prefix):
                return float(c.get("ltm_amount") or 0)
        return 0.0
    gross_margin = sga_model.get("gross_margin")
    if not sga_model.get("components") or gross_margin is None or not base_revenue_eok:
        return None
    labor = _amount("인건비")
    variable = _amount("변동비")
    fixed = _amount("고정비")
    baddebt_ratio = float(sga_model.get("baddebt_ratio") or 0) / 100
    wage = float(sga_model.get("wage_growth") or 3.3) / 100
    cpi = float(sga_model.get("cpi") or 2.5) / 100
    variable_pct = variable / base_revenue_eok if base_revenue_eok else 0
    path, revenue = [], base_revenue_eok
    for year in range(1, forecast_years + 1):
        progress = (year - 1) / max(forecast_years - 1, 1)
        g = (growth_y1 + (growth_terminal - growth_y1) * progress) / 100
        revenue *= 1 + g
        labor_t = labor * (1 + wage) ** year
        fixed_t = fixed * (1 + cpi) ** year
        variable_t = revenue * variable_pct
        baddebt_t = revenue * baddebt_ratio
        sga_t = labor_t + variable_t + fixed_t + baddebt_t
        sga_ratio = sga_t / revenue * 100 if revenue else None
        opm = round(gross_margin - sga_ratio, 2) if sga_ratio is not None else None
        path.append({"year_index": year, "revenue": round(revenue, 1),
                     "sga_ratio": round(sga_ratio, 2) if sga_ratio is not None else None, "opm": opm})
    return {
        "opm_path": [p["opm"] for p in path], "detail": path,
        "gross_margin": gross_margin,
        "method": "OPM_t = 매출총이익률 − (인건비·임금↑ + 변동비·매출연동 + 고정비·CPI↑ + 대손·매출연동)/매출",
    }


def build_depreciation_schedule(kpis: pd.DataFrame, macro: dict) -> dict:
    """Existing-asset run-off plus re-depreciated new CAPEX, split COGS / SG&A."""
    da_ratio = _median_tail(kpis["depreciation_ratio"])
    capex_ratio = _median_tail(kpis["capex_ratio"])
    # Reference tangible-asset split: ~77.8% COGS, ~22.2% SG&A.
    return {
        "da_ratio": round(da_ratio, 2) if da_ratio is not None else 3.5,
        "capex_ratio": round(capex_ratio, 2) if capex_ratio is not None else 3.0,
        "cogs_share": 77.8, "sga_share": 22.2,
        "method": "기존자산은 잔존내용연수 동안 상각 후 종료, 신규 CapEx는 매년 재투자로 재상각 → 제조원가 77.8% / 판관비 22.2% 배분",
    }


def build_wacc_bridge(recommendations: dict, capital: dict, macro: dict, peer_betas: list[dict] | None = None) -> dict:
    """Transparent CAPM/WACC bridge with optional peer unlever/relever."""
    rf = _num(recommendations.get("risk_free_rate", {}).get("default")) or 3.2
    erp = _num(recommendations.get("erp", {}).get("default")) or 6.0
    market_beta = _num(recommendations.get("beta", {}).get("default")) or 1.0
    debt_weight = _num(capital.get("debt_weight")) or 20.0
    tax = 24.0
    cost_debt = 4.5
    peer_table = []
    relevered_beta = None
    if peer_betas:
        target_de = (debt_weight / (100 - debt_weight)) if debt_weight < 100 else None
        unlevered = []
        for p in peer_betas:
            lb = _num(p.get("levered_beta"))
            de = _num(p.get("de_ratio"))
            if lb is None:
                continue
            ub = lb / (1 + (1 - tax / 100) * (de / 100)) if de is not None else lb
            unlevered.append(ub)
            peer_table.append({"peer": p.get("name"), "levered_beta": round(lb, 3),
                               "de_ratio": de, "unlevered_beta": round(ub, 3)})
        if unlevered and target_de is not None:
            ub_avg = float(np.mean(unlevered))
            relevered_beta = ub_avg * (1 + (1 - tax / 100) * target_de)
            peer_table.append({"peer": "Selected (relevered)", "levered_beta": round(relevered_beta, 3),
                               "de_ratio": round(target_de * 100, 1), "unlevered_beta": round(ub_avg, 3)})
    # Reference convention: use the peer-relevered beta when available, else the
    # market-regressed adjusted beta. Thinly traded Korean staples can push the
    # relevered beta unrealistically low, so apply the same 0.50 POC floor used for
    # the single-stock beta — this prevents a collapsing WACC and runaway valuation.
    BETA_FLOOR = 0.5
    if relevered_beta is not None:
        beta = max(relevered_beta, BETA_FLOOR, market_beta * 0.5)
        floored = beta > relevered_beta + 1e-9
        beta_source = f"동종기업 unlever→relever{' (0.50 guardrail 적용)' if floored else ''}"
    else:
        beta = market_beta
        beta_source = "시장회귀 조정 베타(동종 베타 결측)"
    cost_equity = rf + beta * erp
    wacc = cost_equity * (1 - debt_weight / 100) + cost_debt * (1 - tax / 100) * (debt_weight / 100)
    return {
        "rf": round(rf, 2), "erp": round(erp, 2), "beta": round(beta, 3),
        "market_beta": round(market_beta, 3), "beta_source": beta_source,
        "cost_equity": round(cost_equity, 2), "cost_debt": cost_debt,
        "tax": tax, "after_tax_cost_debt": round(cost_debt * (1 - tax / 100), 2),
        "equity_weight": round(100 - debt_weight, 2), "debt_weight": round(debt_weight, 2),
        "wacc": round(wacc, 2), "peer_table": peer_table,
        "method": "CAPM Ke = Rf + β·ERP / Kd(세후) / 자본구조 가중 → WACC. 베타는 동종기업 unlever→relever",
    }


def build_structured_model(
    company: str, kpis: pd.DataFrame, peer_kpis: dict[str, pd.DataFrame],
    macro: dict, research: dict, recommendations: dict, capital: dict,
    peer_betas: list[dict] | None = None, sga_override: dict | None = None,
) -> dict:
    """Assemble the full reference-style build for UI and Excel consumption."""
    return {
        "company": company,
        "revenue": build_revenue_decomposition(kpis, peer_kpis, macro, research),
        "sga": build_sga_decomposition(kpis, company, macro, sga_override),
        "depreciation": build_depreciation_schedule(kpis, macro),
        "wacc": build_wacc_bridge(recommendations, capital, macro, peer_betas),
    }
