"""Artifact-tool Excel bridge for the FinSight analyst workbook."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

NODE_BIN = Path("/Users/betterkim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
MODULES = Path("/Users/betterkim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules")
BUILDER = Path(__file__).with_name("excel_builder.mjs")
RUNTIME_ROOT = Path("/tmp/finsight-excel-runtime")


def _clean(value):
    if isinstance(value, pd.DataFrame):
        return [_clean(row) for row in value.replace({np.nan: None}).to_dict("records")]
    if isinstance(value, pd.Series):
        return _clean(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    return value


def _node_command() -> str | None:
    if NODE_BIN.exists():
        return str(NODE_BIN)
    return shutil.which("node")


def _ensure_runtime() -> str:
    node = _node_command()
    if not node or not MODULES.joinpath("@oai", "artifact-tool").exists():
        raise RuntimeError("Excel artifact runtime을 찾을 수 없습니다.")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    link = RUNTIME_ROOT / "node_modules"
    if link.is_symlink() and link.resolve() != MODULES.resolve():
        link.unlink()
    if not link.exists():
        link.symlink_to(MODULES, target_is_directory=True)
    return node


def _sheet_frame(value) -> pd.DataFrame:
    cleaned = _clean(value)
    if isinstance(cleaned, list):
        return pd.DataFrame(cleaned)
    if isinstance(cleaned, dict):
        return pd.DataFrame([cleaned])
    return pd.DataFrame([{"value": cleaned}])


def _fallback_excel(payload: dict) -> bytes:
    """Build a compact workbook when the local artifact runtime is unavailable."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_rows = [
            {"항목": "회사", "값": payload.get("company")},
            {"항목": "기준 기간", "값": payload.get("asOf")},
            {"항목": "모델 상태", "값": payload.get("modelStatus")},
            {"항목": "예상 시작연도", "값": payload.get("forecastStart")},
            {"항목": "LTM 매출(억원)", "값": payload.get("ltmRevenue")},
        ]
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        _sheet_frame(payload.get("quarterly", [])).to_excel(writer, sheet_name="Quarterly", index=False)
        _sheet_frame(payload.get("scan", [])).to_excel(writer, sheet_name="Signals", index=False)
        _sheet_frame(payload.get("quality", [])).to_excel(writer, sheet_name="Quality", index=False)
        _sheet_frame(payload.get("recommendations", {})).to_excel(writer, sheet_name="Assumptions", index=False)
        _sheet_frame(payload.get("multipleValuation", [])).to_excel(writer, sheet_name="Multiples", index=False)
        _sheet_frame(payload.get("peerBenchmark", [])).to_excel(writer, sheet_name="Peers", index=False)
        _sheet_frame(payload.get("dcfEvidence", [])).to_excel(writer, sheet_name="DCF Evidence", index=False)
        _sheet_frame(payload.get("trackerCommentary", [])).to_excel(writer, sheet_name="Tracker Notes", index=False)
    return output.getvalue()


def export_excel(
    company: str,
    kpis: pd.DataFrame,
    bridge: pd.DataFrame,
    dcf: dict | None,
    recommendations: dict,
    quality_checks: list[dict],
    anomalies: list[dict],
    capital_inputs: dict | None = None,
    *,
    scan: list[dict] | None = None,
    peer_benchmark: pd.DataFrame | None = None,
    dcf_evidence: list[dict] | None = None,
    peer_names: list[str] | None = None,
    thesis: dict | None = None,
    market_context: dict | None = None,
    multiple_valuation: pd.DataFrame | None = None,
    valuation_range: dict | None = None,
    research_reference: dict | None = None,
    structured: dict | None = None,
    price_action: dict | None = None,
    interpreted: list[dict] | None = None,
    tracker_commentary: list[dict] | None = None,
) -> bytes:
    """Build an eight-sheet, source-backed analyst workbook and return XLSX bytes."""
    latest = kpis.iloc[-1]
    core_quality = [item for item in quality_checks if item["field"] in {"매출액", "영업이익", "영업활동현금흐름"}]
    model_status = "PASS" if all(item["missing_quarters"] == 0 for item in core_quality) else "REVIEW"
    dcf_payload = None
    if dcf:
        dcf_payload = {key: value for key, value in dcf.items() if not isinstance(value, pd.DataFrame)}
    payload = {
        "company": company,
        "asOf": str(latest.get("period")),
        "forecastStart": int(latest.get("year")) + 1,
        "ltmRevenue": float(kpis.tail(4)["revenue"].sum(min_count=4) / 1e8),
        "quarterly": kpis,
        "marginBridge": bridge,
        "dcf": dcf_payload,
        "recommendations": recommendations,
        "quality": quality_checks,
        "anomalies": anomalies,
        "capital": capital_inputs or {},
        "scan": scan or [],
        "peerBenchmark": peer_benchmark if peer_benchmark is not None else pd.DataFrame(),
        "dcfEvidence": dcf_evidence or [],
        "peerNames": peer_names or [],
        "thesis": thesis or {},
        "marketContext": market_context or {},
        "multipleValuation": multiple_valuation if multiple_valuation is not None else pd.DataFrame(),
        "valuationRange": valuation_range or {},
        "researchReference": research_reference or {},
        "structured": structured or {},
        "priceAction": price_action or {},
        "trackerCommentary": tracker_commentary or [],
        "interpreted": [
            {**{k: v for k, v in item.items() if k not in ("interpretation",)}, "interpretation": item.get("interpretation", {})}
            for item in (interpreted or [])
        ],
        "contextCount": sum(len(item.get("context", [])) for item in (scan or [])),
        "modelStatus": model_status,
    }

    try:
        node = _ensure_runtime()
    except RuntimeError:
        return _fallback_excel(payload)

    with tempfile.TemporaryDirectory(dir=RUNTIME_ROOT) as tmp:
        work = Path(tmp)
        shutil.copy2(BUILDER, work / "build_workbook.mjs")
        input_path, output_path = work / "input.json", work / "workbook.xlsx"
        input_path.write_text(json.dumps(_clean(payload), ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [node, str(work / "build_workbook.mjs"), str(input_path), str(output_path)],
            cwd=work, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Excel 생성 실패: {(result.stderr or result.stdout)[-500:]}")
        return output_path.read_bytes()


def generate_report(*args, **kwargs):
    raise RuntimeError("FinSight는 Analyst Workbook Excel 산출물을 사용합니다.")
