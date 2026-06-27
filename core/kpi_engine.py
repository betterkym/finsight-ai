"""Quarterly KPI calculations used by the tracker, margin bridge and DCF."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _divide(a: pd.Series, b: pd.Series) -> pd.Series:
    return np.where((b.notna()) & (b != 0), a / b * 100, np.nan)


def calculate_quarterly_kpis(financials: pd.DataFrame) -> pd.DataFrame:
    df = financials.copy().sort_values(["year", "quarter"]).reset_index(drop=True)
    numeric = [
        "revenue", "operating_profit", "net_income", "cogs", "sga", "cfo", "depreciation", "capex",
        "receivables", "inventory", "payables", "cash", "debt", "total_assets",
        "total_liabilities", "total_equity", "current_assets", "current_liabilities",
    ]
    for column in numeric:
        if column not in df:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["opm"] = _divide(df["operating_profit"], df["revenue"])
    df["net_margin"] = _divide(df["net_income"], df["revenue"])
    df["cfo_margin"] = _divide(df["cfo"], df["revenue"])
    df["cogs_ratio"] = _divide(df["cogs"], df["revenue"])
    df["sga_ratio"] = _divide(df["sga"], df["revenue"])
    df["capex_ratio"] = _divide(df["capex"].abs(), df["revenue"])
    df["depreciation_ratio"] = _divide(df["depreciation"].abs(), df["revenue"])
    df["fcf"] = df["cfo"] - df["capex"].abs()
    df["fcf_margin"] = _divide(df["fcf"], df["revenue"])
    df["cash_conversion"] = _divide(df["cfo"], df["operating_profit"])
    df["working_capital"] = df["receivables"] + df["inventory"] - df["payables"]
    df["working_capital_ratio"] = _divide(df["working_capital"], df["revenue"])
    df["change_in_nwc"] = df["working_capital"].diff()
    df["unlevered_fcf"] = df["operating_profit"] * 0.76 + df["depreciation"].abs() - df["capex"].abs() - df["change_in_nwc"]
    df["ar_days"] = _divide(df["receivables"], df["revenue"]) * 0.9
    df["inventory_days"] = _divide(df["inventory"], df["cogs"]) * 0.9
    df["payable_days"] = _divide(df["payables"], df["cogs"]) * 0.9
    df["current_ratio"] = _divide(df["current_assets"], df["current_liabilities"])
    df["debt_ratio"] = _divide(df["total_liabilities"], df["total_equity"])

    for metric in ["revenue", "operating_profit", "net_income", "cfo", "fcf", "receivables", "inventory", "payables", "working_capital"]:
        df[f"{metric}_qoq"] = df[metric].pct_change(fill_method=None) * 100
        df[f"{metric}_yoy"] = df[metric].pct_change(4, fill_method=None) * 100
    for metric in ["opm", "net_margin", "cfo_margin", "cogs_ratio", "sga_ratio"]:
        df[f"{metric}_qoq_pp"] = df[metric].diff()
        df[f"{metric}_yoy_pp"] = df[metric].diff(4)
    return df.replace([np.inf, -np.inf], np.nan)


def latest_snapshot(kpis: pd.DataFrame) -> dict:
    if kpis.empty:
        return {}
    row = kpis.iloc[-1]
    return {column: (None if pd.isna(value) else value) for column, value in row.items()}


def annualize_quarters(kpis: pd.DataFrame) -> pd.DataFrame:
    """Aggregate complete four-quarter fiscal years for DCF history.

    A partially reported current year must not be mistaken for a full historical year.
    The DCF base itself uses the latest four quarters (LTM) in ``diagnostics.py``.
    """
    flows = ["revenue", "operating_profit", "net_income", "cfo", "depreciation", "capex", "fcf", "unlevered_fcf"]
    available = [column for column in flows if column in kpis]
    grouped = kpis.groupby("year")
    annual = grouped[available].sum(min_count=1)
    annual["quarter_count"] = grouped["quarter"].nunique()
    complete = annual[annual["quarter_count"] == 4]
    if not complete.empty:
        annual = complete
    annual = annual.reset_index()
    annual["opm"] = _divide(annual["operating_profit"], annual["revenue"])
    annual["revenue_growth"] = annual["revenue"].pct_change(fill_method=None) * 100
    return annual


# Old call sites can pass market_data; it is intentionally ignored in the narrowed MVP.
def calculate_kpis(financials, market_data=None):
    if isinstance(financials, pd.DataFrame):
        return calculate_quarterly_kpis(financials)
    raise TypeError("calculate_kpis는 새 기획에서 분기 DataFrame을 입력받습니다.")
