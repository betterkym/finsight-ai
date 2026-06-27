"""Data quality checks: never silently force missing DART values."""

from __future__ import annotations

import pandas as pd

CORE_FIELDS = {
    "revenue": "매출액", "operating_profit": "영업이익", "net_income": "순이익",
    "cogs": "매출원가", "sga": "판매비와관리비", "cfo": "영업활동현금흐름",
    "capex": "CAPEX", "receivables": "매출채권", "inventory": "재고자산",
    "payables": "매입채무", "total_assets": "자산총계", "total_liabilities": "부채총계",
    "total_equity": "자본총계", "current_assets": "유동자산", "current_liabilities": "유동부채",
}


def build_data_quality_report(kpis: pd.DataFrame) -> list[dict]:
    checks = []
    for field, label in CORE_FIELDS.items():
        missing = int(kpis[field].isna().sum()) if field in kpis else len(kpis)
        checks.append({
            "field": label, "status": "Needs Review" if missing else "DART",
            "missing_quarters": missing,
            "note": "계정 매핑을 확인하세요." if missing else "DART 원본 계정 연결 완료",
        })
    return checks


def has_blocking_gaps(checks: list[dict]) -> bool:
    blocking = {"매출액", "영업이익"}
    return any(item["field"] in blocking and item["missing_quarters"] > 0 for item in checks)


# Compatibility entry point for older imports.
def build_validation_agenda(ar, view=None):
    frame = ar if isinstance(ar, pd.DataFrame) else ar.get("kpis", pd.DataFrame())
    return build_data_quality_report(frame)
