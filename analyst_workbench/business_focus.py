"""Evidence-based DCF assumption recommendations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.kpi_engine import annualize_quarters


def _range(center: float, spread: float, floor: float | None = None) -> tuple[float, float]:
    low, high = center - spread, center + spread
    if floor is not None:
        low = max(low, floor)
    return round(low, 1), round(high, 1)


def build_assumption_recommendations(kpis: pd.DataFrame, macro: dict, beta: float | None) -> dict:
    annual = annualize_quarters(kpis)
    growth = annual["revenue_growth"].dropna().tail(3)
    # Prefer a latest-twelve-month comparison when eight quarters are available.
    ltm_growth = None
    revenue = kpis["revenue"].dropna()
    if len(revenue) >= 8 and revenue.iloc[-8:-4].sum() != 0:
        ltm_growth = (revenue.iloc[-4:].sum() / revenue.iloc[-8:-4].sum() - 1) * 100
    recent_growth = float(growth.mean()) if not growth.empty else float(ltm_growth if ltm_growth is not None else 3.0)
    latest_growth = float(ltm_growth if ltm_growth is not None else (growth.iloc[-1] if not growth.empty else recent_growth))
    growth_center = min(recent_growth, latest_growth) if latest_growth < recent_growth else recent_growth

    opm = kpis["opm"].dropna().tail(4)
    opm_center = float(opm.mean()) if not opm.empty else 5.0
    conversion = kpis["cash_conversion"].replace([np.inf, -np.inf], np.nan).dropna().tail(4)
    conversion_center = float(conversion.median()) if not conversion.empty else 75.0
    conversion_center = min(max(conversion_center, 20.0), 120.0)

    growth_trend = "Watch" if len(growth) >= 2 and growth.iloc[-1] < growth.iloc[-2] else "Auto"
    margin_trend = "Risk" if len(opm) >= 3 and all(np.diff(opm) < 0) else "Auto"
    capex_burden = kpis["capex_ratio"].dropna().tail(4).mean()
    conversion_status = "Watch" if pd.notna(capex_burden) and capex_burden > 8 else "Auto"

    growth_range = _range(growth_center, max(1.0, abs(growth_center) * 0.25), -20.0)
    opm_range = _range(opm_center, max(0.5, float(opm.std() or 0.5)), -30.0)
    conversion_range = _range(conversion_center, 10.0, 0.0)
    perpetual_center = min(max(float(macro.get("gdp_growth") or 2.0), 1.0), 2.5)
    raw_beta = float(beta) if beta is not None and np.isfinite(beta) else None
    # Thin trading and short samples can push raw beta unrealistically close to zero.
    # Pull it toward the market beta (Blume-style) and keep a transparent POC floor.
    adjusted_beta = min(1.8, max(0.5, (raw_beta * 2 / 3 + 1 / 3) if raw_beta is not None else 1.0))
    beta_basis = (
        f"FDR 2년 주간 raw beta {raw_beta:.2f}; 시장 평균 회귀 조정 후 0.50~1.80 guardrail"
        if raw_beta is not None else "FDR 결측 fallback 1.00"
    )
    return {
        "revenue_growth": {"recommended": growth_range, "default": round(sum(growth_range) / 2, 1), "basis": "최근 완전연도 성장률과 최신 4분기(LTM) 성장률", "status": growth_trend},
        "opm": {"recommended": opm_range, "default": round(sum(opm_range) / 2, 1), "basis": "최근 4분기 OPM 평균과 변동성", "status": margin_trend},
        "fcf_conversion": {"recommended": conversion_range, "default": round(sum(conversion_range) / 2, 1), "basis": "최근 4분기 CFO/영업이익 중앙값 및 CAPEX", "status": conversion_status},
        "risk_free_rate": {"recommended": (macro.get("risk_free_rate"), macro.get("risk_free_rate")), "default": float(macro.get("risk_free_rate") or 3.2), "basis": "ECOS 국고채 10년물", "status": "Auto"},
        "erp": {"recommended": (macro.get("erp", 6.0), macro.get("erp", 6.0)), "default": float(macro.get("erp") or 6.0), "basis": "KICPA 공시 기준값 — 사용자 확인 필요", "status": "Review"},
        "beta": {"recommended": (round(adjusted_beta, 2), round(adjusted_beta, 2)), "default": round(adjusted_beta, 2), "basis": beta_basis, "status": "Adjusted" if raw_beta is not None else "Review"},
        "perpetual_growth": {"recommended": (1.5, 2.5), "default": round(perpetual_center, 1), "basis": "ECOS GDP 성장률 기반 권장 범위", "status": "Review"},
    }


def build_dcf_evidence_bridge(recommendations: dict, scan: list[dict]) -> list[dict]:
    """Translate detected evidence into explicit, conservative DCF assumption actions."""
    mapping = {
        "매출 성장률": "revenue_growth",
        "영업이익률": "opm",
        "FCFF 전환율": "fcf_conversion",
        "순차입금/WACC": "risk_free_rate",
    }
    results = []
    for label, key in mapping.items():
        rec = recommendations[key]
        linked = [item for item in scan if item.get("dcf") == label and item.get("status") == "Abnormal"]
        high = [item for item in linked if item.get("severity") == "High"]
        default = float(rec["default"])
        adjusted = default
        if label == "매출 성장률" and linked:
            adjusted = default - (2.0 if high else 1.0)
        elif label == "영업이익률" and linked:
            adjusted = default - (1.5 if high else 0.5)
        elif label == "FCFF 전환율" and linked:
            adjusted = default - (15.0 if high else 7.5)
        action = "기본값 유지" if not linked else f"보수 조정: {default:.1f} → {adjusted:.1f}"
        results.append({
            "assumption": label,
            "base": default,
            "evidence_adjusted": round(adjusted, 1),
            "action": action,
            "evidence": [f"{item['label']}: {item['reason']}" for item in linked],
            "confidence": "High" if high else ("Medium" if linked else "Historical only"),
            "source": rec["basis"],
        })
    return results
