"""Transparent five-year DCF calculator for user-confirmed assumptions."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from kpi_engine import annualize_quarters


def calculate_dcf(
    kpis: pd.DataFrame,
    assumptions: dict,
    shares_outstanding: float,
    net_debt: float = 0.0,
    forecast_years: int = 5,
) -> dict:
    if forecast_years < 1:
        raise ValueError("예측 기간은 1년 이상이어야 합니다.")
    annual = annualize_quarters(kpis)
    if annual.empty or annual["revenue"].dropna().empty:
        raise ValueError("DCF 계산에 필요한 매출 데이터가 없습니다.")
    base_year = int(kpis.iloc[-1]["year"])
    recent_four = kpis.tail(4)
    if len(recent_four) < 4:
        raise ValueError("DCF 계산에는 최소 4개 분기 데이터가 필요합니다.")
    base_revenue = float(recent_four["revenue"].sum(min_count=4))
    if math.isnan(base_revenue):
        raise ValueError("최근 4개 분기 매출에 결측이 있어 DCF를 계산할 수 없습니다.")
    growth = float(assumptions["revenue_growth"]) / 100
    opm = float(assumptions["opm"]) / 100
    conversion = float(assumptions["fcf_conversion"]) / 100
    tax_rate = float(assumptions.get("tax_rate", 24.0)) / 100
    rf = float(assumptions["risk_free_rate"]) / 100
    erp = float(assumptions["erp"]) / 100
    beta = float(assumptions["beta"])
    debt_weight = float(assumptions.get("debt_weight", 20.0)) / 100
    cost_debt = float(assumptions.get("cost_of_debt", 4.5)) / 100
    cost_equity = rf + beta * erp
    wacc = cost_equity * (1 - debt_weight) + cost_debt * (1 - tax_rate) * debt_weight
    perpetual = float(assumptions["perpetual_growth"]) / 100
    numeric_inputs = [growth, opm, conversion, tax_rate, rf, erp, beta, debt_weight, cost_debt, perpetual]
    if not all(math.isfinite(value) for value in numeric_inputs):
        raise ValueError("DCF 가정에 유효하지 않은 숫자가 포함되어 있습니다.")
    if growth <= -1:
        raise ValueError("매출 성장률은 -100%보다 커야 합니다.")
    if conversion < 0:
        raise ValueError("FCFF 전환율은 0% 이상이어야 합니다.")
    if not 0 <= tax_rate <= 1 or not 0 <= debt_weight <= 1:
        raise ValueError("법인세율과 부채 비중은 0~100% 범위여야 합니다.")
    if beta < 0 or rf < 0 or erp < 0 or cost_debt < 0:
        raise ValueError("할인율 구성 가정은 음수일 수 없습니다.")
    if wacc <= perpetual:
        raise ValueError("WACC는 영구성장률보다 커야 합니다.")
    if wacc - perpetual < 0.02:
        raise ValueError("터미널가치 과대평가 방지를 위해 WACC-영구성장률 스프레드는 2.0%p 이상이어야 합니다.")

    forecasts, revenue, pv_sum = [], base_revenue, 0.0
    use_driver_model = all(key in assumptions for key in ("revenue_growth_terminal", "opm_terminal", "depreciation_ratio", "capex_ratio", "nwc_ratio"))
    terminal_growth_rate = float(assumptions.get("revenue_growth_terminal", assumptions["revenue_growth"])) / 100
    terminal_opm = float(assumptions.get("opm_terminal", assumptions["opm"])) / 100
    depreciation_ratio = float(assumptions.get("depreciation_ratio", 0.0)) / 100
    capex_ratio = float(assumptions.get("capex_ratio", 0.0)) / 100
    nwc_ratio = float(assumptions.get("nwc_ratio", 0.0)) / 100
    # An explicit bottom-up OPM path (built from the SG&A decomposition) takes precedence
    # over the linear fade; the linear fade remains the fallback.
    opm_path = assumptions.get("opm_path")
    opm_path = list(opm_path) if isinstance(opm_path, (list, tuple)) and len(opm_path) >= forecast_years else None
    previous_revenue = revenue
    for year in range(1, forecast_years + 1):
        progress = (year - 1) / max(forecast_years - 1, 1)
        year_growth = growth + (terminal_growth_rate - growth) * progress if use_driver_model else growth
        if opm_path is not None and opm_path[year - 1] is not None and math.isfinite(float(opm_path[year - 1])):
            year_opm = float(opm_path[year - 1]) / 100
        else:
            year_opm = opm + (terminal_opm - opm) * progress if use_driver_model else opm
        revenue *= 1 + year_growth
        ebit = revenue * year_opm
        nopat = ebit * (1 - tax_rate)
        if use_driver_model:
            depreciation = revenue * depreciation_ratio
            capex = revenue * capex_ratio
            change_in_nwc = (revenue - previous_revenue) * nwc_ratio
            fcff = nopat + depreciation - capex - change_in_nwc
        else:
            depreciation, capex, change_in_nwc = None, None, None
            fcff = nopat * conversion
        discount_factor = 1 / ((1 + wacc) ** year)
        pv = fcff * discount_factor
        pv_sum += pv
        forecasts.append({
            "year": base_year + year, "revenue": revenue, "revenue_growth": year_growth * 100,
            "opm": year_opm * 100, "ebit": ebit, "tax": ebit * tax_rate,
            "nopat": nopat, "depreciation": depreciation, "capex": capex,
            "change_in_nwc": change_in_nwc, "fcff": fcff,
            "discount_factor": discount_factor, "pv_fcff": pv,
        })
        previous_revenue = revenue
    terminal_fcff = forecasts[-1]["fcff"] * (1 + perpetual)
    terminal_value = terminal_fcff / (wacc - perpetual)
    pv_terminal = terminal_value / ((1 + wacc) ** forecast_years)
    enterprise_value = pv_sum + pv_terminal
    equity_value = enterprise_value - float(net_debt)
    implied_price = equity_value / float(shares_outstanding) if shares_outstanding > 0 else None
    terminal_share = pv_terminal / enterprise_value * 100 if enterprise_value else None
    return {
        "historical": annual, "forecast": pd.DataFrame(forecasts),
        "cost_of_equity": cost_equity * 100, "wacc": wacc * 100,
        "terminal_value": terminal_value, "pv_terminal": pv_terminal,
        "enterprise_value": enterprise_value, "equity_value": equity_value,
        "shares_outstanding": shares_outstanding, "net_debt": float(net_debt),
        "implied_price": implied_price,
        "terminal_value_share": terminal_share, "wacc_growth_spread": (wacc - perpetual) * 100,
        "driver_model": use_driver_model, "opm_path_used": opm_path is not None,
        "guardrails": {
            "beta_floor_applied": beta <= 0.5,
            "terminal_value_watch": terminal_share is not None and terminal_share > 75,
            "wacc_growth_spread_ok": (wacc - perpetual) >= 0.02,
        },
        "assumptions": assumptions,
    }


def calculate_multiple_valuation(
    kpis: pd.DataFrame,
    shares_outstanding: float,
    net_debt: float,
    current_price: float | None,
    valuation_reference: dict | None = None,
) -> pd.DataFrame:
    """Cross-check DCF using forward-style PER and EV/EBITDA bands."""
    valuation_reference = valuation_reference or {}
    recent = kpis.tail(4)
    if len(recent) < 4 or shares_outstanding <= 0:
        return pd.DataFrame()
    ltm_net_income = float(recent["net_income"].sum(min_count=4))
    ltm_ebit = float(recent["operating_profit"].sum(min_count=4))
    ltm_da = float(recent.get("depreciation", pd.Series([0] * len(recent))).fillna(0).abs().sum())
    eps = ltm_net_income / shares_outstanding
    ebitda = ltm_ebit + ltm_da
    rows = []
    per_band = valuation_reference.get("per_band") or [10.0, 12.0, 14.0]
    for multiple in per_band:
        price = eps * float(multiple)
        rows.append({"method": "PER", "case": f"{multiple:.1f}x", "multiple": float(multiple), "implied_price": price, "upside": (price / current_price - 1) * 100 if current_price else None, "basis": "LTM EPS × 목표 PER"})
    ev_band = valuation_reference.get("ev_ebitda_band") or [4.0, 5.0, 6.0]
    for multiple in ev_band:
        enterprise_value = ebitda * float(multiple)
        equity_value = enterprise_value - net_debt
        price = equity_value / shares_outstanding
        rows.append({"method": "EV/EBITDA", "case": f"{multiple:.1f}x", "multiple": float(multiple), "implied_price": price, "upside": (price / current_price - 1) * 100 if current_price else None, "basis": "LTM EBITDA × 목표배수 − 순차입금"})
    for target in valuation_reference.get("broker_targets", []):
        price = float(target["target_price"])
        rows.append({"method": "Broker reference", "case": target["source"], "multiple": None, "implied_price": price, "upside": (price / current_price - 1) * 100 if current_price else None, "basis": "리서치 참고값 · 교차검증용"})
    return pd.DataFrame(rows)


def build_valuation_range(dcf: dict | None, multiples: pd.DataFrame, current_price: float | None) -> dict:
    """Triangulate methods without hiding disagreement behind a single average."""
    values = []
    if dcf and dcf.get("implied_price") is not None:
        values.append({"method": "DCF", "value": float(dcf["implied_price"])})
    if not multiples.empty:
        for method, group in multiples.groupby("method"):
            clean = pd.to_numeric(group["implied_price"], errors="coerce").dropna()
            if not clean.empty:
                values.append({"method": method, "value": float(clean.median())})
    numbers = [row["value"] for row in values if np.isfinite(row["value"]) and row["value"] > 0]
    return {
        "methods": values,
        "low": float(np.percentile(numbers, 25)) if numbers else None,
        "mid": float(np.median(numbers)) if numbers else None,
        "high": float(np.percentile(numbers, 75)) if numbers else None,
        "current_price": current_price,
        "dispersion": (max(numbers) / min(numbers) - 1) * 100 if len(numbers) >= 2 else None,
    }


def run_dcf_sensitivity(kpis: pd.DataFrame, assumptions: dict, shares: float, net_debt: float) -> pd.DataFrame:
    rows = []
    for growth_delta in (-1.0, 0.0, 1.0):
        for opm_delta in (-1.0, 0.0, 1.0):
            scenario = assumptions.copy()
            scenario["revenue_growth"] += growth_delta
            scenario["opm"] += opm_delta
            try:
                result = calculate_dcf(kpis, scenario, shares, net_debt)
                price = result["implied_price"]
            except ValueError:
                price = None
            rows.append({"성장률 변화(%p)": growth_delta, "OPM 변화(%p)": opm_delta, "주당가치": price})
    return pd.DataFrame(rows)
