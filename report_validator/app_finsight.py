"""FinSight — 리포트 신뢰도 검증.

증권사 리포트의 목표가와 투자의견을 DART 재무·공시, KRX 주가·수급,
증권사 목표가 평균, 발행 이후 공시·뉴스·지분 변동으로 다시 대조해
신뢰도 점수와 종합 해석 보고서를 제공한다.
  ① 목표가 편차: 다른 증권사와 비교해 목표가가 얼마나 높은가
  ② 발행 이후 괴리: 발행 후 주가·수급·공시가 리포트와 어긋났는가
  ③ 필요 실적: 목표가를 위해 필요한 성장률이 현실적인가
  ④ 본문 의견 검증: 리포트 안의 핵심 의견이 서로/팩트와 맞는가
"""
from __future__ import annotations

import sys
import runpy
import re
import unicodedata
import html
from pathlib import Path
from io import BytesIO
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit Cloud Secrets를 환경변수로 연결한다.
# 배포 환경엔 .env가 없으므로, st.secrets에 넣은 DART_API_KEY 등을
# core.data_collector가 import 시점에 os.getenv로 읽을 수 있게 미리 주입한다.
# (반드시 core.* import보다 먼저 실행되어야 한다.)
try:
    for _secret_key, _secret_val in st.secrets.items():
        if isinstance(_secret_val, str) and _secret_val and not os.environ.get(_secret_key):
            os.environ[_secret_key] = _secret_val
except Exception:
    pass

from core.kpi_engine import calculate_quarterly_kpis
from core.diagnostics import (
    calculate_multiple_valuation,
    build_valuation_range,
)
from report_validator.finsight_modules import (
    reverse_engineer_target,
    reverse_engineer_target_lenient,
    aggregate_opinions,
    locate_in_distribution,
    locate_vs_consensus,
)
from core.mode_views import build_tracker_table, build_peer_benchmark
from core import data_collector as dc
from analyst_workbench.ui_components import financial_trend_chart
from analyst_workbench.interpretation import interpret_price_action
from report_validator.timeline_module import build_post_publish_timeline, fetch_foreign_flow, fetch_price_at_date
from report_validator.scoring_module import build_report_verdict
from report_validator.report_assessor import build_alignment_assessment, apply_alignment_to_verdict
from report_validator.retail_report import generate_retail_html_report, generate_retail_pdf_report
from report_validator.evidence_audit import (
    build_data_source_logic,
    build_dart_health_summary,
    build_kpi_snapshot,
    build_scoring_rulebook,
    build_score_audit,
    build_source_audit,
    build_update_audit,
    score_formula,
)
from lib.research_reference import get_research_reference, RESEARCH_LIBRARY
from report_validator.consensus_crawler import search_company_and_consensus, fetch_naver_research_reports
from report_validator import demo_data as D


def _launch_analyst_workbench() -> None:
    """Open the original analyst Streamlit implementation from this validator."""
    root = Path(__file__).resolve().parent.parent
    script = root / "analyst_workbench" / "app.py"
    for path in (script.parent, root):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    runpy.run_path(str(script), run_name="__main__")
    st.stop()


if st.query_params.get("view") == "analyst":
    _launch_analyst_workbench()


# ──────────────────────────────────────────────
# 실데이터 수집 (DART) — 실패 시 None 반환, 데모로 폴백
# ──────────────────────────────────────────────
@st.cache_data(show_spinner="📡 DART 재무 수집 중...")
def fetch_real_financials(company_name: str) -> dict | None:
    """종목명으로 실제 DART 재무·현재가·발행주식수를 수집한다.

    DART 재무가 수집되면 실데이터로 인정한다. 필요 실적 역산 가능 여부는
    load_analysis에서 별도 처리한다.
    """
    try:
        info = dc.resolve_company(company_name)
        if not info or not info.get("stock_code"):
            return None
        fin = dc.get_quarterly_financials(company_name, quarters=24)
        if fin is None or len(fin) < 4:
            return None

        code = info["stock_code"]
        price = dc.get_current_price(code)
        if not price:
            return None
        shares = None
        try:
            if {"year", "quarter"}.issubset(fin.columns):
                clean_periods = fin.dropna(subset=["year", "quarter"])
                latest = clean_periods.iloc[-1] if not clean_periods.empty else fin.iloc[-1]
                yr = int(latest.get("year"))
                q = int(latest.get("quarter"))
            else:
                period_text = str(fin.iloc[-1].get("period", ""))
                match = re.search(r"(20\d{2}).*?([1-4])", period_text)
                if not match:
                    raise ValueError(f"분기 식별 실패: {period_text}")
                yr, q = int(match.group(1)), int(match.group(2))
            shares = dc.get_share_snapshot(info["company"], yr, q).get("shares_outstanding")
        except Exception:
            shares = None

        return {
            "company_name": info["company"],
            "stock_code": code,
            "financials": fin,
            "current_price": float(price),
            "shares_outstanding": float(shares or 0),
            "financial_status": "실제 DART 재무",
            "share_status": "DART 발행주식수 연결" if shares else "발행주식수 미확인",
        }
    except Exception:
        return None


def diagnose_real_financials(company_name: str) -> list[dict]:
    """데모로 폴백된 경우, 어느 단계에서 막혔는지 단계별로 점검한다.

    배포 환경(.env 없음, 클라우드 IP)에서 DART/FDR이 막히는 지점을 그대로 노출해
    추측 없이 원인을 찾기 위한 진단표.
    """
    steps: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        steps.append({"단계": name, "상태": "✅ 정상" if ok else "❌ 실패", "내용": detail})

    # ① Secrets에 키가 들어왔는지(원천) ② 코드가 읽는지(최종) 분리 진단
    secret_keys = []
    secret_has_dart = False
    try:
        secret_keys = list(st.secrets.keys())
        secret_has_dart = bool(str(st.secrets.get("DART_API_KEY", "")).strip())
    except Exception:
        secret_keys = []
    add("Secrets에 DART_API_KEY 존재", secret_has_dart,
        f"st.secrets 키 목록: {', '.join(secret_keys) if secret_keys else '비어 있음'}"
        + ("" if secret_has_dart
           else " — Streamlit Cloud ▸ Manage app ▸ Settings ▸ Secrets에 DART_API_KEY를 저장하세요"))

    key_ok = bool(dc.DART_API_KEY)
    add("코드가 키를 읽음(os.getenv)", key_ok,
        f"키 끝 4자리 …{dc.DART_API_KEY[-4:]}" if key_ok
        else ("Secrets엔 있으나 코드가 못 읽음 — 앱 재부팅(Reboot) 필요"
              if secret_has_dart else "키 자체가 없어 못 읽음"))
    if not key_ok:
        return steps

    try:
        info = dc.resolve_company(company_name)
        ok = bool(info and info.get("stock_code"))
        add("종목 매칭(DART)", ok,
            f"{info.get('company')} / {info.get('stock_code')}" if ok else "매칭 실패")
        if not ok:
            return steps
        code = info["stock_code"]
    except Exception as e:
        add("종목 매칭(DART)", False, f"오류: {e}")
        return steps

    try:
        fin = dc.get_quarterly_financials(company_name, quarters=24)
        n = 0 if fin is None else len(fin)
        add("분기 재무(DART)", n >= 4, f"{n}분기 수집" if n else "재무가 비어 있음")
    except Exception as e:
        add("분기 재무(DART)", False, f"오류: {e}")

    try:
        price = dc.get_current_price(code)
        add("현재가(FinanceDataReader)", bool(price),
            f"{price:,.0f}원" if price
            else "가격 조회 실패 — 클라우드 IP에서 외부 시세 접근이 막혔을 수 있습니다")
    except Exception as e:
        add("현재가(FinanceDataReader)", False, f"오류: {e}")

    return steps


@st.cache_data(show_spinner="📰 네이버 리포트 목록 확인 중...")
def fetch_research_list(stock_code: str) -> list[dict]:
    return fetch_naver_research_reports(stock_code, pages=2, limit=20)


@st.cache_data(ttl=1800, show_spinner="🧾 발행 후 공시·시장 정황 확인 중...")
def fetch_report_context(company_name: str, stock_code: str) -> dict:
    context = {"disclosures": [], "ownership": [], "news": [], "blogs": [], "market": {}, "external_drivers": {}, "errors": []}
    for key, loader, args in (
        ("disclosures", dc.get_recent_disclosures, (company_name,)),
        ("ownership", dc.get_major_shareholding_changes, (company_name,)),
        ("news", dc.get_external_news_context, (company_name,)),
        ("blogs", dc.get_external_blog_context, (company_name,)),
    ):
        try:
            context[key] = loader(*args)
        except Exception as exc:
            context["errors"].append(f"{key}: {exc}")
    try:
        context["disclosures"] = dc.enrich_disclosures_with_snippets(context.get("disclosures", []), limit=4)
    except Exception as exc:
        context["errors"].append(f"disclosure snippets: {exc}")
    try:
        context["market"] = dc.get_market_snapshot(stock_code)
    except Exception as exc:
        context["errors"].append(f"market: {exc}")
    try:
        context["external_drivers"] = dc.get_external_driver_snapshot(company_name, stock_code)
    except Exception as exc:
        context["errors"].append(f"external drivers: {exc}")
    return context


@st.cache_data(ttl=3600, show_spinner=False)
def cached_price_at_date(stock_code: str, ymd: str) -> float | None:
    return fetch_price_at_date(stock_code, ymd)


def build_price_gap_read(price_action: dict) -> list[dict]:
    rows = []
    for item in (price_action or {}).get("attribution", []):
        rows.append({
            "driver": item.get("driver", ""),
            "weight": item.get("weight", ""),
            "reading": item.get("reading", ""),
            "evidence": item.get("evidence", ""),
            "url": item.get("url", ""),
        })
    return rows[:4]


def _normalize_pdf_text(text: str) -> str:
    """Clean common PDF extraction artifacts without changing the meaning."""
    cleaned = unicodedata.normalize("NFKC", str(text or ""))
    cleaned = cleaned.replace("\x00", " ").replace("\u200b", "")
    cleaned = re.sub(r"([0-9])\s*,\s*([0-9]{3})", r"\1,\2", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _dedupe_text_blocks(blocks: list[str]) -> list[str]:
    seen = set()
    out = []
    for block in blocks:
        cleaned = _normalize_pdf_text(block)
        if len(cleaned) < 20:
            continue
        key = re.sub(r"\s+", "", cleaned[:700])
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _extract_with_pypdf(file_bytes: bytes, max_pages: int) -> tuple[list[str], int | None]:
    try:
        from pypdf import PdfReader
    except Exception:
        return [], None
    try:
        reader = PdfReader(BytesIO(file_bytes))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                return [], len(reader.pages)
        page_count = len(reader.pages)
        blocks = []
        for page in list(reader.pages)[:max_pages]:
            for mode in ("layout", "plain"):
                try:
                    text = page.extract_text(extraction_mode=mode) or ""
                except TypeError:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text:
                    blocks.append(text)
        return blocks, page_count
    except Exception:
        return [], None


def _extract_with_pdfplumber(file_bytes: bytes, max_pages: int) -> tuple[list[str], int | None]:
    try:
        import pdfplumber
    except Exception:
        return [], None
    try:
        blocks = []
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages[:max_pages]:
                for kwargs in ({"layout": True, "x_tolerance": 1, "y_tolerance": 3}, {}):
                    try:
                        text = page.extract_text(**kwargs) or ""
                    except Exception:
                        text = ""
                    if text:
                        blocks.append(text)
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []
                for table in tables[:4]:
                    rows = []
                    for row in table or []:
                        cells = [str(cell or "").strip() for cell in row or []]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        blocks.append("\n".join(rows))
        return blocks, page_count
    except Exception:
        return [], None


def extract_report_pdf_text(file_bytes: bytes, max_pages: int = 12) -> tuple[str, str]:
    """Best-effort PDF text extraction for uploaded broker reports."""
    if not file_bytes:
        return "", "파일이 비어 있습니다."
    blocks = []
    page_count = None
    engines = []

    pypdf_blocks, pypdf_pages = _extract_with_pypdf(file_bytes, max_pages)
    if pypdf_blocks:
        blocks.extend(pypdf_blocks)
        engines.append("pypdf")
    page_count = pypdf_pages or page_count

    plumber_blocks, plumber_pages = _extract_with_pdfplumber(file_bytes, max_pages)
    if plumber_blocks:
        blocks.extend(plumber_blocks)
        engines.append("pdfplumber")
    page_count = plumber_pages or page_count

    texts = _dedupe_text_blocks(blocks)
    text = "\n\n".join(texts)
    if not text:
        return "", "PDF에서 텍스트 레이어를 읽지 못했습니다. 이미지형/스캔 PDF일 수 있어 원문 확인이 필요합니다."

    pages_read = min(page_count or max_pages, max_pages)
    engine_text = " + ".join(dict.fromkeys(engines)) if engines else "PDF 리더"
    if len(text) < 500:
        status = f"PDF {pages_read}페이지에서 텍스트 일부만 읽었습니다. 표나 이미지형 페이지는 원문 확인이 필요합니다."
    else:
        status = f"PDF {pages_read}페이지 텍스트를 읽었습니다. ({engine_text})"
    return text[:30000], status


BROKER_HINTS = [
    "삼성증권", "하나증권", "NH투자증권", "KB증권", "신한투자증권", "미래에셋증권",
    "한국투자증권", "대신증권", "키움증권", "메리츠증권", "유안타증권", "한화투자증권",
    "현대차증권", "유진투자증권", "교보증권", "신영증권", "DB금융투자", "SK증권",
    "IBK투자증권", "DS투자증권", "다올투자증권", "흥국증권", "LS증권",
]


def _clean_report_name(file_name: str) -> str:
    return Path(file_name or "업로드 리포트").stem.replace("_", " ").replace("-", " ").strip()


def report_identity(item: dict) -> str:
    broker = item.get("broker") or "증권사 확인 필요"
    date = item.get("pub_date") or "발행일 확인 필요"
    title = item.get("title") or _clean_report_name(item.get("file_name", "업로드 리포트"))
    return f"{broker} · {date} · {title}"


def reports_missing_target(reports: list[dict]) -> list[dict]:
    return [item for item in reports if not item.get("target_price")]


def comparable_reports(reports: list[dict]) -> list[dict]:
    """Reports usable in the target-price/opinion comparison table."""
    return [item for item in reports if item.get("target_price") and item.get("opinion")]


def missing_comparison_notes(reports: list[dict]) -> list[str]:
    notes = []
    for item in reports:
        missing = []
        if not item.get("target_price"):
            missing.append("목표가 인식 불가")
        if not item.get("opinion"):
            missing.append("투자의견 인식 불가")
        if missing:
            notes.append(f"{report_identity(item)}: {', '.join(missing)}로 재확인 필요")
    return notes


def _parse_report_date(text: str) -> str:
    patterns = [
        r"(20\d{2})[.\-/년 ]\s*(\d{1,2})[.\-/월 ]\s*(\d{1,2})",
        r"(\d{2})[.]\s*(\d{1,2})[.]\s*(\d{1,2})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            year, month, day = match.groups()
            year_i = int(year) if len(year) == 4 else 2000 + int(year)
            try:
                return datetime.date(year_i, int(month), int(day)).isoformat()
            except ValueError:
                continue
    return ""


def _money_to_won(raw: str, unit: str = "") -> int | None:
    try:
        value = float(str(raw).replace(",", "").replace(" ", "").strip())
    except ValueError:
        return None
    if "만원" in unit:
        value *= 10000
    elif "천원" in unit:
        value *= 1000
    return int(value)


def _target_evidence_snippet(text: str, start: int, end: int) -> str:
    snippet = re.sub(r"\s+", " ", text[max(0, start - 35): min(len(text), end + 45)]).strip()
    return snippet[:140]


def _parse_target_price_with_evidence(text: str) -> tuple[int | None, str]:
    """Extract the report's own target price, never the market average fallback."""
    if not text:
        return None, ""
    text = _normalize_pdf_text(text)
    candidates: list[dict] = []
    target_label = (
        r"(?:목\s*표\s*(?:주\s*가|가|가\s*격)|적\s*정\s*주\s*가|"
        r"Target\s*Price|Fair\s*Value|TP)"
    )
    money = r"(?P<raw>[0-9]{1,3}(?:\s*,\s*[0-9]{3})+|[0-9]{4,8}|[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>원|만원|천원|KRW)?"
    patterns: list[tuple[str, int]] = [
        (rf"(?P<label>{target_label})\s*(?:\([^)]{{0,40}}\))?\s*(?:[:：|ㆍ·\-])?\s*(?:KRW\s*)?{money}", 0),
        (rf"(?P<label>{target_label}).{{0,45}}?(?:KRW\s*)?{money}", 200),
        (rf"{money}\s*(?:\([^)]{{0,40}}\))?\s*(?P<label>{target_label})", 500),
    ]
    for pattern, base_penalty in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.groupdict().get("raw") or ""
            unit = match.groupdict().get("unit") or ""
            if not unit:
                full_match = match.group(0)
                if "만원" in full_match:
                    unit = "만원"
                elif "천원" in full_match:
                    unit = "천원"
            value = _money_to_won(raw, unit)
            if value is None or value < 1000 or value > 10000000:
                continue
            snippet = _target_evidence_snippet(text, match.start(), match.end())
            bad_context = re.search(
                r"(현재\s*주가|현재가|종가|시가총액|상승\s*여력|Upside).{0,18}"
                + re.escape(str(raw)),
                snippet,
                re.IGNORECASE,
            )
            old_context = re.search(r"(기존|종전|직전|이전)\s*(목표|TP|Target)", snippet, re.IGNORECASE)
            score = match.start() + base_penalty
            if bad_context:
                score += 100000
            if old_context:
                score += 5000
            candidates.append({"value": value, "snippet": snippet, "score": score})
    if not candidates:
        return None, ""
    best = min(candidates, key=lambda item: item["score"])
    return best["value"], best["snippet"]


def _parse_target_price(text: str) -> int | None:
    target, _snippet = _parse_target_price_with_evidence(text)
    return target


def _parse_opinion(text: str) -> str:
    lowered = _normalize_pdf_text(text).lower()
    label = r"(투\s*자\s*의\s*견|opinion|rating|recommendation|investment\s*rating)"
    if re.search(rf"{label}.{{0,45}}(적극\s*매수|strong\s*buy)", lowered, re.IGNORECASE):
        return "적극매수"
    if re.search(rf"{label}.{{0,45}}(매수|buy|outperform|overweight|trading\s*buy)", lowered, re.IGNORECASE):
        return "매수"
    if re.search(rf"{label}.{{0,45}}(중립|hold|neutral|marketperform|보유)", lowered, re.IGNORECASE):
        return "중립"
    if re.search(rf"{label}.{{0,45}}(매도|sell|underperform|underweight)", lowered, re.IGNORECASE):
        return "매도"
    if re.search(r"(buy|매수)\s*(유지|상향|신규|의견)", lowered, re.IGNORECASE):
        return "매수"
    if re.search(r"(hold|neutral|중립|보유)\s*(유지|상향|하향|의견)", lowered, re.IGNORECASE):
        return "중립"
    if re.search(r"(sell|매도)\s*(유지|하향|의견)", lowered, re.IGNORECASE):
        return "매도"
    return ""


def _parse_broker(text: str) -> str:
    for broker in BROKER_HINTS:
        if broker in text:
            return broker
    match = re.search(r"([가-힣A-Za-z]{2,12}(?:증권|투자증권|금융투자))", text)
    return match.group(1) if match else ""


def extract_report_metadata(file_name: str, text: str) -> dict:
    source = f"{_clean_report_name(file_name)}\n{text or ''}"
    target_price, target_evidence = _parse_target_price_with_evidence(source)
    return {
        "file_name": file_name,
        "title": _clean_report_name(file_name),
        "broker": _parse_broker(source),
        "pub_date": _parse_report_date(source),
        "opinion": _parse_opinion(source),
        "target_price": target_price,
        "target_evidence": target_evidence,
        "text_excerpt": (text or "")[:12000],
    }


def build_report_comparison_rows(reports: list[dict], mean_target: float | None) -> list[dict]:
    rows = []
    for item in comparable_reports(reports):
        target = item.get("target_price")
        gap = None
        if target and mean_target:
            gap = (target / mean_target - 1) * 100
        verdict = "평균권"
        if gap is not None:
            if gap >= 15:
                verdict = "평균보다 공격적"
            elif gap <= -15:
                verdict = "평균보다 보수적"
        rows.append({
            "증권사": item.get("broker") or "확인 필요",
            "발행일": item.get("pub_date") or "확인 필요",
            "투자의견": item.get("opinion") or "",
            "목표가": f"{target:,.0f}원",
            "평균 대비": f"{gap:+.1f}%" if gap is not None else "N/A",
            "판정": verdict,
            "목표가 근거": item.get("target_evidence") or "원문에서 목표가 문장을 찾지 못했습니다.",
            "리포트": item.get("title") or item.get("file_name") or "업로드 리포트",
        })
    return rows


def report_batch_stats(reports: list[dict]) -> dict:
    targets = sorted(int(item["target_price"]) for item in reports if item.get("target_price"))
    opinions: dict[str, int] = {}
    for item in reports:
        opinion = item.get("opinion")
        if not opinion:
            continue
        opinions[opinion] = opinions.get(opinion, 0) + 1
    dates = []
    for item in reports:
        if item.get("pub_date"):
            try:
                dates.append(datetime.date.fromisoformat(item["pub_date"]))
            except ValueError:
                continue
    median = None
    if targets:
        mid = len(targets) // 2
        median = targets[mid] if len(targets) % 2 else int((targets[mid - 1] + targets[mid]) / 2)
    majority_opinion = ""
    if opinions:
        majority_opinion = max(opinions.items(), key=lambda pair: pair[1])[0]
    return {
        "count": len(reports),
        "target_count": len(targets),
        "comparison_count": len(comparable_reports(reports)),
        "opinion_count": sum(opinions.values()),
        "min_target": targets[0] if targets else None,
        "max_target": targets[-1] if targets else None,
        "median_target": median,
        "mean_target": int(sum(targets) / len(targets)) if targets else None,
        "latest_date": max(dates).isoformat() if dates else "",
        "opinions": opinions,
        "majority_opinion": majority_opinion,
    }


REPORT_THEME_RULES = [
    {
        "theme": "실적 성장",
        "keywords": ["매출", "성장", "실적", "외형", "판매", "수요"],
        "question": "리포트가 말한 성장 스토리가 최근 실적 숫자로 확인되는가",
    },
    {
        "theme": "수익성·마진",
        "keywords": ["영업이익", "수익성", "마진", "OPM", "원가율", "판관비", "이익률"],
        "question": "매출 성장뿐 아니라 이익률도 같이 좋아지고 있는가",
    },
    {
        "theme": "해외·수출",
        "keywords": ["해외", "수출", "미국", "중국", "일본", "글로벌", "법인", "수출액"],
        "question": "해외 성장 논리가 공시·뉴스·실적 흐름과 맞는가",
    },
    {
        "theme": "원가·비용",
        "keywords": ["원가", "비용", "판관비", "광고", "인건비", "운임", "환율", "원재료"],
        "question": "비용 부담이 목표가 가정을 훼손하지 않는가",
    },
    {
        "theme": "주가·수급",
        "keywords": ["주가", "수급", "외국인", "기관", "멀티플", "밸류에이션", "리레이팅", "디레이팅"],
        "question": "리포트 방향과 실제 가격·수급 반응이 맞는가",
    },
    {
        "theme": "현금흐름·투자",
        "keywords": ["현금흐름", "CFO", "FCF", "CAPEX", "투자", "재고", "운전자본"],
        "question": "회계상 이익이 실제 현금흐름으로 이어지는가",
    },
]

POSITIVE_WORDS = ["성장", "개선", "확대", "회복", "상향", "증가", "호조", "수혜", "기대", "견조", "긍정", "리레이팅"]
NEGATIVE_WORDS = ["부담", "둔화", "하락", "악화", "감소", "리스크", "우려", "비용", "적자", "부진", "압박", "불확실"]
OVERSEAS_SIGNAL_WORDS = [
    "해외", "수출", "글로벌", "미국", "중국", "일본", "유럽", "북미", "동남아",
    "아시아", "태국", "베트남", "인도네시아", "싱가포르", "대만", "홍콩",
    "면세", "현지", "법인", "FDA", "CE", "인허가", "품목허가", "허가", "승인",
]
OVERSEAS_CONCRETE_WORDS = [
    "계약", "공급", "수주", "MOU", "협약", "판매", "유통", "출시", "입점",
    "매장", "법인", "자회사", "공장", "투자", "인수", "취득", "승인", "허가",
    "인허가", "품목허가", "수출액", "해외매출", "매출", "실적", "선적",
]
EXPECTATION_ONLY_WORDS = [
    "전망", "기대", "목표가", "상향", "관심", "수혜", "모멘텀", "가능성",
    "주목", "리레이팅", "증권", "리포트", "분석", "추천",
]


def _plain_context_text(item: dict) -> str:
    parts = []
    for key in ("title", "detail", "summary", "description", "reason", "report_nm", "corp_name"):
        value = item.get(key)
        if value is not None:
            parts.append(str(value))
    text = re.sub(r"<[^>]+>", " ", " ".join(parts))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _context_title(item: dict, limit: int = 42) -> str:
    title = str(item.get("title") or item.get("detail") or item.get("report_nm") or "자료").strip()
    title = html.unescape(re.sub(r"<[^>]+>", " ", title))
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > limit:
        return title[: limit - 2].rstrip() + ".."
    return title


def _has_overseas_signal(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(word.lower() in lowered for word in OVERSEAS_SIGNAL_WORDS)


def _is_expectation_only_context(text: str) -> bool:
    lowered = str(text or "").lower()
    has_expectation = any(word.lower() in lowered for word in EXPECTATION_ONLY_WORDS)
    has_concrete = any(word.lower() in lowered for word in OVERSEAS_CONCRETE_WORDS)
    return has_expectation and not has_concrete


def _overseas_topic_label(text: str) -> str:
    lowered = str(text or "").lower()
    topics = []
    if any(word.lower() in lowered for word in ("계약", "공급", "수주", "MOU", "협약")):
        topics.append("공급·계약")
    if any(word.lower() in lowered for word in ("판매", "유통", "출시", "입점", "매장", "면세")):
        topics.append("해외 판매망")
    if any(word.lower() in lowered for word in ("허가", "승인", "FDA", "CE", "인허가", "품목허가")):
        topics.append("인허가")
    if any(word.lower() in lowered for word in ("법인", "자회사", "공장", "투자", "인수", "취득")):
        topics.append("해외 거점·투자")
    if any(word.lower() in lowered for word in ("수출액", "해외매출", "매출", "실적", "선적", "수출")):
        topics.append("수출·매출")
    return " · ".join(topics[:2]) if topics else "해외 성장 단서"


def _build_overseas_context_brief(context: dict) -> dict:
    disclosures = (context or {}).get("disclosures", []) or []
    news = (context or {}).get("news", []) or []
    total_count = len(disclosures) + len(news)
    candidates: list[dict] = []

    for source, rows in (("공시", disclosures), ("뉴스", news)):
        for item in rows:
            text = _plain_context_text(item)
            if not text or not _has_overseas_signal(text):
                continue
            candidates.append({
                "source": source,
                "title": _context_title(item),
                "topic": _overseas_topic_label(text),
                "expectation_only": _is_expectation_only_context(text),
            })

    concrete = [item for item in candidates if not item["expectation_only"]]
    expectation = [item for item in candidates if item["expectation_only"]]

    if not candidates:
        if total_count:
            return {
                "signal_count": 0,
                "concrete_count": 0,
                "brief": (
                    f"발행 이후 공시 {len(disclosures)}건·뉴스 {len(news)}건은 확인되지만, "
                    "제목과 요약 기준으로 해외 매출 증가를 직접 보강하는 단서는 뚜렷하지 않습니다. "
                    "따라서 이 자료들은 해외 성장의 숫자 근거라기보다 기대감이 얼마나 남아 있는지 보는 보조 자료로만 반영합니다."
                ),
            }
        return {
            "signal_count": 0,
            "concrete_count": 0,
            "brief": (
                "발행 이후 새 공시나 뉴스도 아직 잡히지 않아, "
                "리포트의 해외 성장 주장은 현재 숫자로는 확인이 부족합니다."
            ),
        }

    top_items = (concrete or candidates)[:3]
    topics = []
    for item in top_items:
        if item["topic"] not in topics:
            topics.append(item["topic"])
    examples = "; ".join(
        f"{item['source']} '{item['title']}'에서 {item['topic']} 단서"
        for item in top_items[:2]
    )

    brief = (
        f"발행 이후 자료 {total_count}건 중 해외 관련 단서는 {len(candidates)}건이고, "
        f"그중 실제 변화 단서로 볼 만한 것은 {len(concrete)}건입니다. "
        f"핵심은 {', '.join(topics[:3])} 쪽입니다"
    )
    if examples:
        brief += f" (예: {examples}). "
    else:
        brief += ". "
    if concrete:
        brief += "이런 내용은 리포트의 해외 성장 가정을 보강할 수 있지만, 매출 규모가 숫자로 확인되기 전까지는 목표가에 전부 반영하긴 어렵습니다."
    else:
        brief += "다만 대부분이 전망·관심성 기사에 가까워, 해외 매출이 실제로 늘었다는 근거로는 낮게 반영합니다."
    if expectation:
        brief += f" 전망성 표현이 중심인 {len(expectation)}건은 기대감 확인 자료로만 봅니다."
    return {
        "signal_count": len(candidates),
        "concrete_count": len(concrete),
        "brief": brief,
    }


def _split_report_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?。])\s+|(?<=[다요음임])\.\s+|[\n\r]+", cleaned)
    return [part.strip() for part in parts if 24 <= len(part.strip()) <= 260][:350]


def _stance_of(text: str) -> str:
    pos = sum(1 for word in POSITIVE_WORDS if word.lower() in text.lower())
    neg = sum(1 for word in NEGATIVE_WORDS if word.lower() in text.lower())
    if pos > neg:
        return "긍정"
    if neg > pos:
        return "부담"
    return "중립"


def _objective_theme_read(theme: str, analysis: dict) -> str:
    kpis = analysis.get("kpis")
    latest = kpis.iloc[-1] if kpis is not None and not kpis.empty else {}
    timeline = analysis.get("timeline") or {}
    price_action = analysis.get("price_action") or {}

    revenue_yoy = _num(latest.get("revenue_yoy"))
    op_yoy = _num(latest.get("operating_profit_yoy"))
    opm_yoy = _num(latest.get("opm_yoy_pp"))
    cfo_margin = _num(latest.get("cfo_margin"))
    fcf_margin = _num(latest.get("fcf_margin"))
    cogs_yoy = _num(latest.get("cogs_ratio_yoy_pp"))
    sga_yoy = _num(latest.get("sga_ratio_yoy_pp"))

    if theme == "실적 성장":
        if revenue_yoy is not None and op_yoy is not None:
            if revenue_yoy > 0 and op_yoy > 0:
                return f"DART 최근 분기 매출 {revenue_yoy:+.1f}%, 영업이익 {op_yoy:+.1f}%로 성장 논리는 숫자로 일부 확인됩니다."
            return f"DART 최근 분기 매출 {revenue_yoy:+.1f}%, 영업이익 {op_yoy:+.1f}%라 성장 논리는 선별적으로 봐야 합니다."
    if theme == "수익성·마진":
        if opm_yoy is not None:
            return f"OPM이 전년 동기 대비 {opm_yoy:+.1f}%p 변했습니다. 마진 개선 논리는 이 값과 함께 판단해야 합니다."
    if theme == "원가·비용":
        cost_bits = []
        if cogs_yoy is not None:
            cost_bits.append(f"원가율 {cogs_yoy:+.1f}%p")
        if sga_yoy is not None:
            cost_bits.append(f"판관비율 {sga_yoy:+.1f}%p")
        if cost_bits:
            return "최근 분기 " + ", ".join(cost_bits) + " 변동이 확인됩니다. 비용 부담을 낮게 본 리포트는 재확인이 필요합니다."
    if theme == "현금흐름·투자":
        if cfo_margin is not None or fcf_margin is not None:
            return f"CFO 마진 {_fmt_pct(cfo_margin)}, FCF(잉여현금흐름) 마진 {_fmt_pct(fcf_margin)}입니다. 이익이 현금으로 바뀌는지 확인해야 합니다."
    if theme == "주가·수급":
        return timeline.get("supply_read") or (
            f"발행 이후 수익률 {_fmt_pct(timeline.get('realized'))}입니다. "
            "리포트 방향과 가격·수급 반응을 분리해서 봐야 합니다."
        )
    if theme == "해외·수출":
        overseas_brief = _build_overseas_context_brief(analysis.get("context") or {})
        return (
            "DART 표준 재무제표의 손익계산서만으로는 지역별 매출이나 해외 매출 비중이 별도 항목으로 잡히지 않는 경우가 많습니다. "
            f"{overseas_brief['brief']}"
        )
    return price_action.get("thesis") or "객관 데이터와 함께 재확인이 필요한 논점입니다."


def analyze_report_content_batch(analysis: dict) -> dict:
    reports = [item for item in analysis.get("report_batch", []) if item.get("text_excerpt")]
    if not reports and (analysis.get("report") or {}).get("text_excerpt"):
        reports = [analysis["report"]]
    if not reports:
        return {"theme_rows": [], "claim_rows": [], "summary": "", "report_count": 0}
    theme_rows = []
    claim_rows = []
    for rule in REPORT_THEME_RULES:
        hits = []
        stances = []
        for item in reports:
            sentences = _split_report_sentences(item.get("text_excerpt", ""))
            matched = [
                sentence for sentence in sentences
                if any(keyword.lower() in sentence.lower() for keyword in rule["keywords"])
            ][:2]
            if not matched:
                continue
            combined = " / ".join(matched)
            stance = _stance_of(combined)
            stances.append(stance)
            label = item.get("broker") or item.get("title") or item.get("file_name") or "리포트"
            hits.append(f"{label}: {stance}")
            claim_rows.append({
                "논점": rule["theme"],
                "리포트": label,
                "방향": stance,
                "본문 근거": _short_summary(combined, 180),
            })
        if not hits:
            continue
        unique_stances = {stance for stance in stances}
        stance_counts = {stance: stances.count(stance) for stance in sorted(unique_stances)}
        if "긍정" in unique_stances and "부담" in unique_stances:
            read = "리포트 간 해석이 갈립니다."
            verdict = "의견 차이"
        elif "긍정" in unique_stances:
            read = "대부분 긍정적으로 해석합니다."
            verdict = "긍정 우세"
        elif "부담" in unique_stances:
            read = "대부분 부담 요인으로 봅니다."
            verdict = "부담 우세"
        else:
            read = "방향성은 중립적입니다."
            verdict = "중립"
        objective = _objective_theme_read(rule["theme"], analysis)
        theme_rows.append({
            "논점": rule["theme"],
            "판단 질문": rule["question"],
            "언급 리포트": f"{len(hits)}/{len(reports)}개",
            "리포트 간 차이": " · ".join(hits[:4]),
            "FinSight 대조": objective,
            "판정": verdict,
            "방향 분포": stance_counts,
            "해석": f"{read} {objective}",
        })
    common = [row["논점"] for row in theme_rows if row["언급 리포트"].startswith(str(len(reports)) + "/")]
    mixed = [row["논점"] for row in theme_rows if "갈립니다" in row["해석"]]
    confirmed = [
        row["논점"] for row in theme_rows
        if any(word in row.get("FinSight 대조", "") for word in ("확인됩니다", "확인", "성장 논리는 숫자로"))
        and not _objective_read_has_tension(row.get("FinSight 대조", ""))
    ]
    weak = [
        row["논점"] for row in theme_rows
        if _objective_read_has_tension(row.get("FinSight 대조", ""))
    ]
    summary_bits = []
    if common:
        summary_bits.append(
            f"여러 리포트가 공통으로 기대는 전제는 {', '.join(common[:3])}입니다. "
            "따라서 목표가 신뢰도는 이 전제들이 실제 숫자로 확인되는지에 달려 있습니다."
        )
    if confirmed:
        summary_bits.append(f"현재 데이터로 비교적 확인되는 부분은 {', '.join(confirmed[:2])}입니다.")
    if weak:
        summary_bits.append(
            f"반대로 {', '.join(weak[:2])}은 리포트 표현보다 보수적으로 봐야 합니다. "
            "이 항목은 최종 신뢰도 차감 근거가 됩니다."
        )
    if mixed:
        summary_bits.append(
            f"{', '.join(mixed[:2])}은 증권사별 해석이 갈립니다. "
            "목표가 차이는 이 전제를 얼마나 낙관적으로 보느냐에서 생긴 것으로 봅니다."
        )
    if not summary_bits and theme_rows:
        summary_bits.append(
            "리포트별 강조점이 분산되어 있습니다. 목표가 숫자만 비교하기보다 어떤 전제를 더 낙관적으로 잡았는지 확인해야 합니다."
        )
    return {
        "theme_rows": theme_rows,
        "claim_rows": claim_rows[:18],
        "summary": " ".join(summary_bits),
        "report_count": len(reports),
    }


def _objective_read_has_tension(text: str) -> bool:
    tension_words = [
        "선별", "재확인", "부담", "약", "제한", "낮", "눌", "훼손",
        "불확실", "보수", "덜", "지연", "부족",
    ]
    return any(word in str(text or "") for word in tension_words)


def assess_report_content_consistency(content: dict) -> dict:
    rows = content.get("theme_rows") or []
    if not rows:
        return {
            "label": "본문 미반영",
            "score": None,
            "max": 20,
            "penalty": 0,
            "reason": "PDF 본문을 읽지 못해 본문 의견 검증은 점수 차감에 반영하지 않았습니다.",
            "factors": [],
            "divergent_count": 0,
            "optimistic_gap_count": 0,
        }

    divergent = [row for row in rows if row.get("판정") == "의견 차이"]
    optimistic_gap = [
        row for row in rows
        if (row.get("방향 분포") or {}).get("긍정", 0) > 0
        and _objective_read_has_tension(row.get("FinSight 대조", ""))
    ]

    penalty = min(4, len(divergent) * 2) + min(8, len(optimistic_gap) * 3)
    penalty = min(10, penalty)
    score = max(0, 20 - penalty)

    factors = []
    if optimistic_gap:
        sample = optimistic_gap[0]
        factors.append({
            "title": "리포트가 좋게 본 전제가 아직 숫자로 충분히 확인되지 않음",
            "impact": "신뢰도 차감",
            "reason": f"{sample.get('논점')}을 좋게 본 리포트가 있지만, 지금 확인되는 자료만으로는 그 전제를 그대로 인정하기 어렵습니다.",
            "evidence": sample.get("FinSight 대조", ""),
            "points": min(8, len(optimistic_gap) * 3),
            "severity": "Content",
        })
    if divergent:
        sample = divergent[0]
        factors.append({
            "title": "리포트끼리 해석이 갈리는 부분",
            "impact": "신뢰도 차감",
            "reason": f"{sample.get('논점')}에 대해 증권사별 해석이 한 방향으로 모이지 않습니다.",
            "evidence": sample.get("리포트 간 차이", ""),
            "points": min(4, len(divergent) * 2),
            "severity": "Content",
        })

    if penalty >= 7:
        label = "낙관 해석 주의"
    elif penalty >= 3:
        label = "일부 재확인"
    else:
        label = "큰 충돌 제한"

    reason_bits = []
    if divergent:
        reason_bits.append(f"의견 차이 {len(divergent)}개")
    if optimistic_gap:
        reason_bits.append(f"데이터로 덜 확인된 긍정 해석 {len(optimistic_gap)}개")
    reason = " · ".join(reason_bits) if reason_bits else "본문 핵심 의견과 현재 데이터 사이의 큰 충돌은 제한적입니다."

    return {
        "label": label,
        "score": score,
        "max": 20,
        "penalty": penalty,
        "reason": reason,
        "factors": factors,
        "divergent_count": len(divergent),
        "optimistic_gap_count": len(optimistic_gap),
    }


def _theme_brief_text(row: dict, group: str) -> str:
    theme = row.get("논점", "핵심 논점")
    objective = row.get("FinSight 대조", "")
    if group == "trusted":
        if theme == "실적 성장":
            return (
                "리포트들이 말한 성장 방향은 일단 받아들여도 됩니다. "
                f"{objective} 다만 이 말이 곧 목표가 전체를 정당화한다는 뜻은 아니고, 다음 분기에도 같은 흐름이 이어지는지가 핵심입니다."
            )
        if theme == "수익성·마진":
            return (
                "마진이 좋아지고 있다는 주장 자체는 숫자로 대조할 수 있습니다. "
                f"{objective} 매출 성장과 이익률이 같이 움직이면 목표가의 기본 전제는 더 단단해집니다."
            )
        if theme == "현금흐름·투자":
            return (
                "이익이 실제 현금으로 남는지는 목표가 신뢰도에 중요합니다. "
                f"{objective} 현금흐름이 버티면 리포트의 이익 전망을 더 편하게 받아들일 수 있습니다."
            )
        return (
            f"{theme}은 리포트들이 비교적 같은 방향으로 보고 있고, 현재 데이터도 크게 반대하지 않습니다. "
            f"{objective}"
        )
    if group == "watch":
        if theme == "해외·수출":
            return (
                "해외 성장 스토리는 목표가를 설명하는 중요한 근거일 수 있지만, 확인 방식이 매출 전체 증가보다 까다롭습니다. "
                f"{objective} 그래서 해외 관련 단서가 있더라도 실제 매출 기여가 숫자로 확인되기 전까지는 목표가 신뢰도에 보수적으로 반영합니다."
            )
        if theme == "원가·비용":
            return (
                "비용 부담을 낮게 본 리포트라면 조심해서 봐야 합니다. "
                f"{objective} 매출이 늘어도 비용이 같이 올라가면 목표가에 필요한 이익이 덜 남습니다."
            )
        if theme == "주가·수급":
            return (
                "리포트 방향이 맞아도 가격과 수급이 따라오지 않으면 주가 반영은 늦어질 수 있습니다. "
                f"{objective}"
            )
        return (
            f"{theme}은 리포트 문장만으로 확정하기 어렵습니다. "
            f"{objective} 이 부분은 목표가를 믿기 전에 한 번 할인해서 봅니다."
        )
    if group == "contested":
        return (
            f"{theme}은 증권사마다 해석이 갈리는 부분입니다. "
            f"{row.get('리포트 간 차이', '')} 목표가 차이는 이 전제를 얼마나 좋게 보느냐에서 생긴 것으로 봅니다."
        )
    return objective


def _mention_counts(text: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", str(text or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _claim_brief(claims: list[dict]) -> str:
    bits = []
    for claim in claims[:2]:
        broker = claim.get("리포트") or "리포트"
        stance = claim.get("방향") or "확인"
        basis = claim.get("본문 근거") or ""
        bits.append(f"{broker} {stance}: {basis}")
    return " / ".join(bits)


def build_report_briefing(content: dict, assessment: dict | None = None) -> dict:
    rows = content.get("theme_rows") or []
    if not rows:
        return {"headline": "", "trusted": [], "watch": [], "contested": []}

    claims_by_theme: dict[str, list[dict]] = {}
    for claim in content.get("claim_rows") or []:
        claims_by_theme.setdefault(claim.get("논점", ""), []).append(claim)

    trusted: list[dict] = []
    watch: list[dict] = []
    contested: list[dict] = []
    for row in rows:
        objective = row.get("FinSight 대조", "")
        has_positive = (row.get("방향 분포") or {}).get("긍정", 0) > 0
        mentioned, total = _mention_counts(row.get("언급 리포트", ""))
        if not total:
            total = content.get("report_count") or 1
        common_threshold = 1 if total <= 1 else max(2, (total * 3 + 4) // 5)
        is_common = mentioned >= common_threshold
        is_tension = _objective_read_has_tension(objective) or "어렵" in objective or "부족" in objective
        theme = row.get("논점", "")
        claim_text = _claim_brief(claims_by_theme.get(theme, []))
        item = {
            "title": theme,
            "source": row.get("리포트 간 차이", ""),
            "evidence": objective,
            "claim": claim_text,
            "mention": row.get("언급 리포트", ""),
        }
        if row.get("판정") == "의견 차이":
            contested.append({**item, "read": _theme_brief_text(row, "contested")})
        elif is_common and has_positive and not is_tension:
            trusted.append({**item, "read": _theme_brief_text(row, "trusted")})
        elif is_common and row.get("판정") == "중립" and not is_tension:
            trusted.append({**item, "read": _theme_brief_text(row, "trusted")})
        elif has_positive or is_tension or row.get("판정") == "부담 우세":
            watch.append({**item, "read": _theme_brief_text(row, "watch")})
        elif is_common:
            trusted.append({**item, "read": _theme_brief_text(row, "trusted")})

    trusted = trusted[:3]
    watch = watch[:3]
    contested = contested[:2]

    if trusted:
        headline = (
            f"읽고 가져가도 되는 핵심은 {', '.join(item['title'] for item in trusted[:2])}입니다. "
            "이 부분은 리포트들이 반복해서 짚었고, 현재 확인되는 데이터와 큰 충돌이 없습니다."
        )
        if watch:
            headline += f" 다만 {', '.join(item['title'] for item in watch[:2])}은 아직 목표가 근거로 강하게 인정하기 어렵습니다."
    else:
        headline = "현재 업로드된 리포트들에서 그대로 가져갈 만한 공통 전제는 아직 약합니다."
        if watch:
            headline += f" 특히 {', '.join(item['title'] for item in watch[:2])}은 리포트 표현보다 보수적으로 봅니다."
    if contested:
        headline += f" {', '.join(item['title'] for item in contested[:2])}은 증권사별 해석 차이가 있습니다."

    return {
        "headline": headline,
        "trusted": trusted,
        "watch": watch,
        "contested": contested,
        "penalty": (assessment or {}).get("penalty", 0),
    }


def merge_content_assessment_into_alignment(alignment: dict, content_assessment: dict) -> dict:
    if not content_assessment:
        return alignment
    factors = list(alignment.get("factors", []))
    content_factors = content_assessment.get("factors") or []
    if content_factors:
        factors = content_factors + factors
    penalty = min(24, int(alignment.get("penalty", 0)) + int(content_assessment.get("penalty", 0)))
    if penalty >= 14:
        label = "중요 불일치"
    elif penalty >= 7:
        label = "부분 불일치"
    elif penalty > 0:
        label = "경미한 차감"
    else:
        label = alignment.get("label", "큰 충돌 제한")
    return {
        **alignment,
        "label": label,
        "penalty": penalty,
        "factors": factors[:7],
        "content_assessment": content_assessment,
    }


def report_batch_conclusion(analysis: dict) -> str:
    reports = analysis.get("report_batch") or []
    if not reports:
        return ""
    stats = report_batch_stats(reports)
    timeline = analysis.get("report_batch_timeline") or {}
    summary = timeline.get("summary") or {}
    parts = []
    if stats.get("target_count"):
        parts.append(
            f"추출된 목표가는 {stats['min_target']:,.0f}~{stats['max_target']:,.0f}원 범위이고 "
            f"중앙값은 {stats['median_target']:,.0f}원입니다."
        )
    opinion_text = " · ".join(f"{key} {value}개" for key, value in stats.get("opinions", {}).items())
    if opinion_text:
        parts.append(f"투자의견 분포는 {opinion_text}입니다.")
    if summary.get("best_broker"):
        score = summary.get("best_score")
        score_text = f"({score:.0f}점)" if score is not None else ""
        parts.append(
            f"현재 주가·발행일 이후 변화·목표가 편차를 함께 보면 {summary['best_broker']} 리포트가 "
            f"현재 데이터와 가장 덜 어긋납니다{score_text}. {summary.get('best_reason', '')}"
        )
    missing_notes = missing_comparison_notes(reports)
    if missing_notes:
        parts.append(f"다만 핵심 항목을 읽지 못한 {len(missing_notes)}개 리포트는 목표가·투자의견 비교표에서 제외했습니다.")
    return " ".join(parts)


def render_report_batch_distribution(analysis: dict) -> None:
    reports = analysis.get("report_batch") or []
    if not reports:
        return
    stats = report_batch_stats(reports)
    rows = build_report_comparison_rows(reports, (analysis.get("consensus") or {}).get("price_target_mean"))
    st.markdown("#### 증권사별 목표가·투자의견 비교")
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.metric("비교 리포트", f"{stats['comparison_count']}/{stats['count']}개")
    with d2:
        st.metric("목표가 중앙값", f"{stats['median_target']:,.0f}원" if stats.get("median_target") else "직접 입력 필요")
    with d3:
        target_range = "직접 입력 필요"
        if stats.get("min_target") and stats.get("max_target"):
            target_range = f"{stats['min_target']:,.0f}~{stats['max_target']:,.0f}원"
        st.metric("목표가 범위", target_range)
    with d4:
        opinion_text = " · ".join(f"{key} {value}" for key, value in stats.get("opinions", {}).items()) or "확인된 의견 없음"
        st.metric("투자의견 분포", opinion_text)
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("목표가와 투자의견이 모두 확인된 리포트가 아직 없습니다.")
    notes = missing_comparison_notes(reports)
    for note in notes[:5]:
        st.caption(f"* {note}")
    conclusion = report_batch_conclusion(analysis)
    if conclusion:
        st.info(conclusion)


def render_report_batch_overview(analysis: dict) -> None:
    reports = analysis.get("report_batch") or []
    if not reports:
        return
    stats = report_batch_stats(reports)
    consensus_mean = (analysis.get("consensus") or {}).get("price_target_mean")
    rows = build_report_comparison_rows(reports, consensus_mean)

    st.markdown("#### 업로드 리포트 비교")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("비교 리포트", f"{stats['comparison_count']}/{stats['count']}개")
    with c2:
        target_range = "N/A"
        if stats["min_target"] and stats["max_target"]:
            target_range = f"{stats['min_target']:,.0f}~{stats['max_target']:,.0f}원"
        st.metric("목표가 범위", target_range)
    with c3:
        st.metric("중앙 목표가", f"{stats['median_target']:,.0f}원" if stats["median_target"] else "직접 입력 필요")
    with c4:
        opinion_text = " · ".join(f"{key} {value}" for key, value in stats["opinions"].items()) or "확인된 의견 없음"
        st.metric("투자의견 분포", opinion_text)
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    notes = missing_comparison_notes(reports)
    for note in notes[:5]:
        st.caption(f"* {note}")
    if len(notes) > 5:
        st.caption(f"* 외 {len(notes) - 5}개 리포트도 재확인이 필요합니다.")
    if notes:
        st.caption("* 위 리포트는 목표가·투자의견 비교표와 중앙 목표가 계산에서 제외했습니다. 반영하려면 왼쪽 사이드바에서 원문 목표가를 직접 입력하세요.")


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


def tracker_style(frame: pd.DataFrame):
    delta_cols = [column for column in frame.columns if "QoQ" in column or "YoY" in column]

    def color(value):
        if not isinstance(value, (int, float)) or pd.isna(value):
            return ""
        if value > 0:
            return "color:#166534;background-color:#F0FDF4"
        if value < 0:
            return "color:#991B1B;background-color:#FEF2F2"
        return ""

    if not delta_cols:
        return frame.style.format(precision=1, na_rep="Needs Review")
    return frame.style.format(precision=1, na_rep="Needs Review").map(color, subset=delta_cols)


def _fmt_pct(value) -> str:
    number = _num(value)
    return "N/A" if number is None else f"{number:+.1f}%"


def _fmt_eok(value) -> str:
    number = _num(value)
    return "N/A" if number is None else f"{number / 1e8:,.0f}억원"


def _fmt_won(value) -> str:
    number = _num(value)
    return "N/A" if number is None else f"{number:,.0f}원"


def _batch_fit_score(
    *,
    target: float | None,
    price_at_pub: float | None,
    current_price: float,
    consensus_mean: float | None,
    opinion: str,
) -> tuple[float | None, str]:
    if target is None or price_at_pub is None or current_price <= 0:
        return None, "목표가 또는 발행일 주가 확인 필요"
    score = 78.0
    reasons = []
    realized = (current_price / price_at_pub - 1) * 100
    remaining = (target / current_price - 1) * 100
    if consensus_mean:
        gap = (target / consensus_mean - 1) * 100
        gap_penalty = min(28, abs(gap) * 0.65)
        score -= gap_penalty
        reasons.append(f"목표가 평균 대비 {gap:+.1f}%")
    if remaining > 35:
        score -= min(28, (remaining - 35) * 0.7)
        reasons.append(f"현재가 대비 남은 여력 {remaining:+.1f}%")
    elif remaining < -5:
        score -= min(20, abs(remaining + 5) * 1.1)
        reasons.append(f"현재가가 목표가를 {abs(remaining):.1f}% 상회")
    else:
        score += 5
        reasons.append(f"현재가 대비 남은 여력 {remaining:+.1f}%")
    if opinion in ("매수", "적극매수", "Buy") and realized < -15:
        score -= 14
        reasons.append(f"발행 후 주가 {realized:+.1f}%")
    elif opinion in ("매수", "적극매수", "Buy") and realized > 0:
        score += 4
        reasons.append(f"발행 후 주가 {realized:+.1f}%")
    return max(0, min(100, round(score, 1))), " · ".join(reasons[:3])


def build_batch_post_publish_analysis(
    reports: list[dict],
    *,
    stock_code: str,
    current_price: float,
    consensus: dict | None,
    fallback_price_at_pub: float | None,
) -> dict:
    if not reports:
        return {"rows": [], "summary": {}}
    consensus_mean = (consensus or {}).get("price_target_mean")
    rows = []
    raw_rows = []
    for item in comparable_reports(reports):
        pub_date = item.get("pub_date") or ""
        price_at_pub = None
        if pub_date and stock_code:
            price_at_pub = cached_price_at_date(stock_code, pub_date)
        if price_at_pub is None and len(reports) == 1:
            price_at_pub = fallback_price_at_pub
        target = _num(item.get("target_price"))
        realized = (current_price / price_at_pub - 1) * 100 if price_at_pub else None
        remaining = (target / current_price - 1) * 100 if target else None
        upside_at_pub = (target / price_at_pub - 1) * 100 if target and price_at_pub else None
        dist_gap = (target / consensus_mean - 1) * 100 if target and consensus_mean else None
        score, reason = _batch_fit_score(
            target=target,
            price_at_pub=price_at_pub,
            current_price=current_price,
            consensus_mean=consensus_mean,
            opinion=item.get("opinion") or "",
        )
        row = {
            "증권사": item.get("broker") or "확인 필요",
            "발행일": pub_date or "확인 필요",
            "투자의견": item.get("opinion") or "",
            "목표가": _fmt_won(target),
            "발행일 주가": _fmt_won(price_at_pub),
            "발행 후 주가 변화": _fmt_pct(realized),
            "발행 당시 상승여력": _fmt_pct(upside_at_pub),
            "현재 남은 여력": _fmt_pct(remaining),
            "목표가 평균 대비": _fmt_pct(dist_gap),
            "현실 부합도": f"{score:.0f}점" if score is not None else "계산 제외",
            "판단 근거": reason,
        }
        rows.append(row)
        raw_rows.append({**row, "_score": score, "_price_at_pub": price_at_pub, "_realized": realized})
    price_values = [row["_price_at_pub"] for row in raw_rows if row.get("_price_at_pub")]
    avg_price_at_pub = sum(price_values) / len(price_values) if price_values else None
    avg_realized = (current_price / avg_price_at_pub - 1) * 100 if avg_price_at_pub else None
    scored = [row for row in raw_rows if row.get("_score") is not None]
    best = max(scored, key=lambda row: row["_score"]) if scored else None
    return {
        "rows": rows,
        "summary": {
            "avg_price_at_pub": avg_price_at_pub,
            "avg_realized": avg_realized,
            "price_count": len(price_values),
            "best_broker": best.get("증권사") if best else "",
            "best_score": best.get("_score") if best else None,
            "best_reason": best.get("판단 근거") if best else "",
        },
    }


def _parse_context_date(value) -> datetime.date | None:
    if not value:
        return None
    raw = str(value)
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    try:
        parsed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _quarter_bounds(row) -> tuple[datetime.date | None, datetime.date | None]:
    year = _num(row.get("year"))
    quarter = _num(row.get("quarter"))
    if year is None or quarter is None:
        return None, None
    start_month = int(quarter) * 3 - 2
    start = datetime.date(int(year), start_month, 1)
    end_month = start_month + 2
    next_month = datetime.date(int(year) + (1 if end_month == 12 else 0), 1 if end_month == 12 else end_month + 1, 1)
    return start, next_month - datetime.timedelta(days=1)


def _quarter_context_titles(row, context: dict, limit: int = 2) -> list[str]:
    start, end = _quarter_bounds(row)
    if not start or not end:
        return []
    pool = []
    for key in ("disclosures", "ownership", "news", "blogs"):
        pool.extend((context or {}).get(key, []) or [])
    matches = []
    for item in pool:
        date = _parse_context_date(item.get("date"))
        if not date or not (start <= date <= end):
            continue
        title = item.get("title") or item.get("reporter") or item.get("detail")
        if title:
            matches.append(f"{date.isoformat()} {str(title)[:46]}")
        if len(matches) >= limit:
            break
    return matches


def _quarter_issue_note(row, context: dict) -> tuple[str, bool]:
    notes: list[str] = []
    severe = False
    revenue_yoy = _num(row.get("revenue_yoy"))
    revenue_qoq = _num(row.get("revenue_qoq"))
    op_yoy = _num(row.get("operating_profit_yoy"))
    opm = _num(row.get("opm"))
    opm_yoy = _num(row.get("opm_yoy_pp"))
    cfo_margin = _num(row.get("cfo_margin"))
    fcf_margin = _num(row.get("fcf_margin"))
    cogs_yoy = _num(row.get("cogs_ratio_yoy_pp"))
    sga_yoy = _num(row.get("sga_ratio_yoy_pp"))

    if revenue_yoy is not None and revenue_yoy <= -25:
        notes.append(f"매출이 전년 동기 대비 {_fmt_pct(revenue_yoy)} 급감")
        severe = True
    elif revenue_qoq is not None and revenue_qoq <= -20:
        notes.append(f"매출이 전분기 대비 {_fmt_pct(revenue_qoq)} 하락")
        severe = True
    elif revenue_yoy is not None and revenue_yoy >= 20:
        notes.append(f"매출이 전년 동기 대비 {_fmt_pct(revenue_yoy)} 성장")

    if opm is not None and opm < 0:
        notes.append(f"영업적자 구간(OPM {opm:.1f}%)")
        severe = True
    elif op_yoy is not None and op_yoy <= -40:
        notes.append(f"영업이익이 전년 동기 대비 {_fmt_pct(op_yoy)} 감소")
        severe = True
    elif opm_yoy is not None and opm_yoy <= -4:
        notes.append(f"OPM이 전년 동기 대비 {opm_yoy:+.1f}%p 하락")
        severe = True

    if fcf_margin is not None and fcf_margin < 0:
        notes.append(f"FCF(잉여현금흐름) 마진 {fcf_margin:.1f}%")
    elif cfo_margin is not None and cfo_margin < 0:
        notes.append(f"CFO 마진 {cfo_margin:.1f}%")
    if cogs_yoy is not None and cogs_yoy >= 3:
        notes.append(f"원가율 YoY {cogs_yoy:+.1f}%p")
    if sga_yoy is not None and sga_yoy >= 3:
        notes.append(f"판관비율 YoY {sga_yoy:+.1f}%p")

    context_titles = _quarter_context_titles(row, context)
    if context_titles:
        notes.append("같은 분기 자료: " + " / ".join(context_titles))

    if not notes:
        notes.append("숫자상 큰 급변은 제한적")
    return "<br>".join(notes[:4]), severe


def annotated_quarter_chart(kpis: pd.DataFrame, context: dict) -> go.Figure:
    frame = kpis.copy()
    notes, severe_flags, colors = [], [], []
    for _, row in frame.iterrows():
        note, severe = _quarter_issue_note(row, context)
        notes.append(note)
        severe_flags.append(severe)
        revenue_yoy = _num(row.get("revenue_yoy"))
        if severe:
            colors.append("#C0392B")
        elif revenue_yoy is not None and revenue_yoy >= 20:
            colors.append("#185FA5")
        else:
            colors.append("#B8C7D9")
    frame["_note"] = notes
    frame["_revenue_eok"] = frame["revenue"] / 1e8
    frame["_op_eok"] = frame["operating_profit"] / 1e8
    custom = pd.DataFrame({
        "revenue_yoy": frame.get("revenue_yoy").map(_fmt_pct),
        "revenue_qoq": frame.get("revenue_qoq").map(_fmt_pct),
        "op_eok": frame["_op_eok"].map(lambda value: "N/A" if pd.isna(value) else f"{value:,.0f}억원"),
        "opm": frame.get("opm").map(lambda value: "N/A" if pd.isna(value) else f"{value:.1f}%"),
        "cfo_margin": frame.get("cfo_margin").map(lambda value: "N/A" if pd.isna(value) else f"{value:.1f}%"),
        "fcf_margin": frame.get("fcf_margin").map(lambda value: "N/A" if pd.isna(value) else f"{value:.1f}%"),
        "note": frame["_note"],
    })
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=frame["period"],
        y=frame["_revenue_eok"],
        name="매출액",
        marker_color=colors,
        customdata=custom.values,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "매출액 %{y:,.0f}억원<br>"
            "매출 YoY %{customdata[0]} / QoQ %{customdata[1]}<br>"
            "영업이익 %{customdata[2]} / OPM %{customdata[3]}<br>"
            "CFO 마진 %{customdata[4]} / FCF 마진 %{customdata[5]}<br><br>"
            "<b>해석</b><br>%{customdata[6]}<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=frame["period"],
        y=frame["opm"],
        yaxis="y2",
        name="OPM",
        mode="lines+markers",
        line={"color": "#17365D", "width": 2},
        hovertemplate="<b>%{x}</b><br>OPM %{y:.1f}%<extra></extra>",
    ))
    severe_frame = frame[pd.Series(severe_flags, index=frame.index)]
    if not severe_frame.empty:
        fig.add_trace(go.Scatter(
            x=severe_frame["period"],
            y=severe_frame["_revenue_eok"],
            name="급변 분기",
            mode="markers",
            marker={"symbol": "triangle-up", "size": 11, "color": "#C0392B"},
            hoverinfo="skip",
        ))
    fig.update_layout(
        height=390,
        margin={"l": 20, "r": 20, "t": 34, "b": 25},
        legend={"orientation": "h", "y": 1.13},
        hovermode="x unified",
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        yaxis={"title": "매출액(억원)"},
        yaxis2={"title": "OPM(%)", "overlaying": "y", "side": "right"},
    )
    return fig


def _normalize_event_date(value: str) -> str:
    raw = str(value or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _short_summary(text: str, limit: int = 150) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return ""
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "..."


def summarize_post_event(item: dict) -> str:
    title = str(item.get("title") or item.get("detail") or "")
    description = item.get("description") or item.get("summary") or item.get("reason") or ""
    if description:
        return _short_summary(description)
    if "지속가능" in title or "ESG" in title.upper():
        return "지속가능경영·ESG 관련 보고서입니다. 목표가 계산 자체보다 비재무 리스크, 지배구조, 환경·사회 이슈 확인에 쓰는 보조 근거입니다."
    if "기업설명회" in title or "IR" in title.upper():
        return "기업설명회 관련 공시입니다. 리포트 발행 이후 회사가 시장에 설명한 실적·전략 방향을 확인하는 자료입니다."
    if "대량보유" in title or "지분" in title:
        return "주요주주 지분 변동 관련 공시입니다. 실적보다 수급과 지배구조 측면에서 주가 반응을 해석할 때 확인합니다."
    if "실적" in title or "잠정" in title:
        return "실적 관련 공시입니다. 리포트 발행 당시 가정과 실제 숫자가 달라졌는지 확인하는 핵심 자료입니다."
    if "투자" in title or "계약" in title:
        return "투자·계약 관련 공시입니다. 향후 매출 성장, 비용 부담, 현금흐름 변화 가능성을 확인하는 자료입니다."
    return "리포트 발행 이후 확인된 DART 공시입니다. 목표가와 투자의견의 전제가 바뀌었는지 확인하는 보조 근거입니다."


def explain_post_event_impact(item: dict) -> str:
    title = str(item.get("title") or item.get("detail") or "")
    event_type = str(item.get("type") or "")
    ratio_change = _num(item.get("ratio_change"))
    if event_type == "지분공시" or "대량보유" in title or "지분" in title:
        if ratio_change is not None and ratio_change < 0:
            return (
                f"신뢰도 영향: 주요주주 보유비율이 {ratio_change:+.2f}%p 줄어 단기 매도 압력으로 반영합니다. "
                "실적 가정 자체를 부정하진 않지만, 목표가까지 바로 회복된다고 보기 어렵게 만드는 요인입니다."
            )
        if ratio_change is not None and ratio_change > 0:
            return (
                f"신뢰도 영향: 주요주주 보유비율이 {ratio_change:+.2f}%p 늘어 수급 측면에서는 완충 요인입니다. "
                "다만 목표가 정당화는 실적과 현금흐름 확인이 함께 필요합니다."
            )
        return "신뢰도 영향: 지분 변동 성격을 확인해 수급 부담인지, 단순 보고인지 구분해야 합니다."
    if "실적" in title or "잠정" in title:
        return (
            "신뢰도 영향: 리포트 발행 당시의 매출·이익 가정을 최신 숫자로 다시 대체해야 하는 항목입니다. "
            "실적이 리포트 방향과 다르면 발행 이후 괴리 점수에 직접 영향을 줍니다."
        )
    if "기업설명회" in title or "IR" in title.upper():
        return (
            "신뢰도 영향: 회사가 발행 이후 새로 설명한 전략·실적 방향입니다. "
            "리포트의 성장 스토리가 이어지는지 확인하는 보조 근거로 반영합니다."
        )
    if "투자" in title or "계약" in title:
        return (
            "신뢰도 영향: 향후 매출 성장에는 긍정적일 수 있지만, 투자비·운전자본 부담이 같이 커질 수 있습니다. "
            "목표가를 인정하려면 성장 효과와 현금흐름 영향을 함께 봅니다."
        )
    if "지속가능" in title or "ESG" in title.upper():
        return (
            "신뢰도 영향: 목표가 계산을 바로 바꾸는 항목은 아니지만, 비재무 리스크와 지배구조 확인 자료로 둡니다. "
            "큰 이슈가 있으면 객관분석 차감 근거가 됩니다."
        )
    return (
        "신뢰도 영향: 리포트 이후 새로 공개된 정보라 목표가·투자의견의 전제가 아직 유효한지 확인하는 자료입니다. "
        "숫자 영향이 확인되면 발행 이후 괴리와 종합평가에 반영합니다."
    )


def explain_post_event_takeaway(item: dict, report: dict | None = None) -> dict:
    """Explain what the post-report event confirms and how it relates to the report."""
    title = str(item.get("title") or item.get("detail") or "")
    event_type = str(item.get("type") or "")
    ratio_change = _num(item.get("ratio_change"))
    opinion = str((report or {}).get("opinion") or "")
    positive_report = opinion in ("매수", "적극매수", "Buy")

    if event_type == "지분공시" or "대량보유" in title or "지분" in title:
        if ratio_change is not None and ratio_change < 0:
            return {
                "tone": "부정",
                "confirmed": (
                    f"발행 이후 주요주주 보유비율이 {ratio_change:+.2f}%p 낮아진 사실을 확인했습니다. "
                    "이익 전망을 직접 바꾸는 공시는 아니지만, 시장에 나올 수 있는 매도 물량이 늘어난 쪽으로 읽습니다."
                ),
                "relation": (
                    "매수 리포트의 목표가 방향과는 단기적으로 엇갈립니다. 실적 전제가 맞더라도 수급이 따라오지 않으면 목표가 반영 속도는 늦어질 수 있습니다."
                    if positive_report else
                    "보수적인 리포트라면 그 조심스러운 판단을 뒷받침하는 사후 수급 근거로 볼 수 있습니다."
                ),
            }
        if ratio_change is not None and ratio_change > 0:
            return {
                "tone": "긍정",
                "confirmed": (
                    f"발행 이후 주요주주 보유비율이 {ratio_change:+.2f}%p 높아진 사실을 확인했습니다. "
                    "최소한 수급 측면에서는 매도 압력보다 보유 확대가 관찰된 변화입니다."
                ),
                "relation": (
                    "매수 리포트라면 목표가 반영을 방해하는 수급 요인이 줄어든 쪽으로 해석할 수 있습니다. 다만 목표가 자체는 여전히 실적과 현금흐름으로 확인돼야 합니다."
                    if positive_report else
                    "보수적 리포트와는 다소 다른 방향의 사후 변화입니다. 수급은 우호적이지만 실적 근거를 함께 봐야 합니다."
                ),
            }
        return {
            "tone": "확인 필요",
            "confirmed": "발행 이후 지분 관련 공시가 확인됐지만, 보유 목적과 실제 매매 방향을 추가로 구분해야 합니다.",
            "relation": "리포트의 목표가 방향과 바로 연결하기보다 단기 수급 변화 가능성으로만 반영합니다.",
        }

    if "실적" in title or "잠정" in title:
        return {
            "tone": "핵심 확인",
            "confirmed": (
                "발행 이후 실제 실적 또는 잠정 실적이 새로 공개됐습니다. "
                "리포트가 예상했던 매출·영업이익·마진 전제가 숫자로 맞았는지 다시 대조해야 하는 자료입니다."
            ),
            "relation": (
                "실적이 리포트의 성장·마진 방향과 같으면 신뢰도는 올라가고, 다르면 목표가 근거를 낮춰 봅니다. "
                "따라서 이 공시는 발행 이후 변화 중 가장 직접적인 검증 자료입니다."
            ),
        }

    if "기업설명회" in title or "IR" in title.upper():
        return {
            "tone": "중립~확인",
            "confirmed": (
                "발행 이후 회사가 투자자에게 설명한 전략·실적 방향이 추가로 공개됐습니다. "
                "새 숫자라기보다는 경영진이 어떤 전제를 강조했는지 확인하는 자료입니다."
            ),
            "relation": (
                "리포트가 말한 성장 스토리와 회사 설명이 같은 방향이면 보조 근거가 됩니다. "
                "반대로 강조점이 달라졌다면 리포트의 전제가 일부 낡았을 수 있습니다."
            ),
        }

    if "투자" in title or "계약" in title:
        return {
            "tone": "양면",
            "confirmed": (
                "발행 이후 투자·계약 관련 변화가 확인됐습니다. "
                "매출 성장에는 긍정적일 수 있지만 투자비, 운전자본, 회수 시점까지 같이 봐야 합니다."
            ),
            "relation": (
                "리포트가 성장 확대를 핵심 근거로 삼았다면 방향성은 맞을 수 있습니다. "
                "다만 단기 이익과 현금흐름 부담이 커지면 목표가 반영은 지연될 수 있습니다."
            ),
        }

    if "지속가능" in title or "ESG" in title.upper():
        return {
            "tone": "중립",
            "confirmed": (
                "발행 이후 지속가능경영·ESG 관련 자료가 공개됐습니다. "
                "매출이나 이익 추정치를 바로 바꾸는 자료라기보다 비재무 리스크와 지배구조를 확인하는 자료입니다."
            ),
            "relation": (
                "리포트의 목표가 산식과 직접 연결되지는 않습니다. "
                "다만 리포트가 브랜드, 해외 확장, 지배구조 안정성을 강조했다면 보조 확인 자료로 둡니다."
            ),
        }

    return {
        "tone": "확인",
        "confirmed": (
            "리포트 발행 이후 새 공시가 확인됐습니다. "
            "아직 매출·이익 숫자를 바로 바꾸는 자료인지는 제한적이지만, 발행 당시 정보 이후 추가된 사실입니다."
        ),
        "relation": (
            "리포트의 핵심 전제와 같은 방향인지 확인해야 합니다. "
            "같은 방향이면 보조 근거, 다른 방향이면 발행 이후 괴리 근거로 반영합니다."
        ),
    }


def explain_growth_history(rev: dict) -> tuple[str, str]:
    if rev.get("verdict") == "확인 필요":
        return (
            "과거 성장률은 참고용입니다",
            rev.get("limited_reason") or "EPS 역산에 필요한 데이터가 부족해 목표가가 요구하는 성장률과 직접 비교하지 않았습니다.",
        )

    need = _num(rev.get("need_growth"))
    median = _num(rev.get("median_growth"))
    avg = _num(rev.get("avg_growth"))
    reference = _num(rev.get("reference_growth")) if rev.get("reference_growth") is not None else median
    history = [_num(value) for value in rev.get("growth_history", [])]
    history = [value for value in history if value is not None]
    volatility = rev.get("volatility", "")
    if need is None or median is None:
        return (
            "목표가에 필요한 성장을 과거와 비교합니다",
            "이 그래프는 목표가가 요구하는 이익 성장률이 회사의 과거 정상 범위 안에 있는지 보기 위한 기준선입니다.",
        )

    max_growth = max(history) if history else None
    min_growth = min(history) if history else None
    if max_growth is not None and need > max_growth:
        title = "목표가가 과거 최고 성장률보다 높은 성장을 요구합니다"
        body = (
            f"필요 성장률 {need:+.1f}%가 과거 관측 최고치 {max_growth:+.1f}%를 넘어섭니다. "
            "이 경우 리포트 목표가를 인정하려면 단순한 회복이 아니라 새 성장 동력이나 이익률 개선이 숫자로 확인돼야 합니다."
        )
    elif reference is not None and need > reference:
        title = "목표가가 보통 수준보다 높은 성장을 전제로 합니다"
        body = (
            f"필요 성장률 {need:+.1f}%가 과거 중앙값 {median:+.1f}%보다 높습니다. "
            "목표가가 틀렸다는 뜻은 아니지만, 다음 실적에서 매출 성장과 마진 개선이 같이 확인되지 않으면 신뢰도가 낮아집니다."
        )
    elif need < 0:
        title = "목표가가 큰 이익 성장을 요구하지는 않습니다"
        body = (
            f"필요 성장률이 {need:+.1f}%라 과거 중앙값 {median:+.1f}%보다 부담이 작습니다. "
            "이 경우 목표가 검증의 핵심은 실적보다 발행 이후 주가·수급 괴리와 본문 의견의 현실성입니다."
        )
    else:
        title = "목표가가 과거 보통 성장 범위 안에 있습니다"
        body = (
            f"필요 성장률 {need:+.1f}%가 과거 중앙값 {median:+.1f}%와 크게 벗어나지 않습니다. "
            "따라서 이 축에서는 목표가가 무리하다고 보기 어렵고, 다른 축의 수급·공시 변화를 함께 봅니다."
        )

    if volatility in ("높음", "매우높음"):
        body += " 과거 성장률 변동성이 커서 평균보다 중앙값을 기준으로 보는 편이 더 안전합니다."
    elif avg is not None:
        body += f" 참고로 단순 평균은 {avg:+.1f}%입니다."
    if min_growth is not None and max_growth is not None:
        body += f" 과거 관측 범위는 {min_growth:+.1f}%~{max_growth:+.1f}%입니다."
    return title, body


def build_post_report_events(context: dict, report_date: str, report: dict | None = None) -> list[dict]:
    events: list[dict] = []
    for item in (context or {}).get("disclosures", [])[:12]:
        date = _normalize_event_date(item.get("date"))
        if report_date and date and date < report_date:
            continue
        event = {
            "date": date,
            "type": "공시",
            "detail": item.get("title", ""),
            "summary": summarize_post_event(item),
            "url": item.get("url", ""),
        }
        event["impact"] = explain_post_event_impact(event)
        event["takeaway"] = explain_post_event_takeaway(event, report)
        events.append(event)
    for item in (context or {}).get("ownership", [])[:8]:
        date = _normalize_event_date(item.get("date"))
        if report_date and date and date < report_date:
            continue
        change = item.get("ratio_change")
        if change is None:
            continue
        event = {
            "date": date,
            "type": "지분공시",
            "detail": f"{item.get('reporter', '주요주주')} 보유비율 {change:+.2f}%p 변동",
            "summary": summarize_post_event(item),
            "url": item.get("url", ""),
            "ratio_change": change,
        }
        event["impact"] = explain_post_event_impact(event)
        event["takeaway"] = explain_post_event_takeaway(event, report)
        events.append(event)
    events.sort(key=lambda item: item.get("date") or "", reverse=True)
    return events[:6]


PRODUCT_TITLE = "FinSight — 리포트 신뢰도 검증"
PRODUCT_COPY = (
    "증권사 리포트를 그대로 받아들이기 전에 DART 재무·공시, KRX 주가·수급, "
    "증권사 목표가 평균, 발행 이후 뉴스·지분 변동, 업로드한 리포트 본문을 대조합니다. "
    "목표가와 투자의견을 어느 정도 신뢰할 수 있는지 점수화하고, 현재 주가와의 차이까지 해석합니다."
)


st.set_page_config(page_title=PRODUCT_TITLE, layout="wide")

# ──────────────────────────────────────────────
# 색상 팔레트
# ──────────────────────────────────────────────
COLOR = {
    "primary": "#1B2A4A",
    "space": "#185FA5",
    "time": "#0F6E56",
    "logic": "#C0392B",
    "grade_a": "#1B8A4A",
    "grade_b": "#5B8C2A",
    "grade_c": "#BA7517",
    "grade_d": "#C0392B",
    "grade_e": "#A32D2D",
    "bg": "#FAFAF7",
}


st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

    /* ── 전역 타이포그래피 ── */
    html, body, [class*="css"], .stApp, button, input, textarea, select {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .stApp { background: #F5F6F8; }

    /* ── Streamlit 기본 군더더기 정리 ── */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="stToolbar"] { right: 12px; }
    [data-testid="stHeader"] { background: transparent; height: 0; }
    .block-container { padding-top: 2.0rem; padding-bottom: 3rem; max-width: 1180px; }

    /* ── 본문 카드 컨테이너(중앙 영역) ── */
    [data-testid="stMainBlockContainer"] { }

    /* ── metric을 카드로 ── */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E6E9EE;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(16,24,40,0.04);
    }
    [data-testid="stMetricLabel"] p {
        font-size: 12.5px !important;
        font-weight: 700 !important;
        color: #64748B !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 25px !important;
        font-weight: 850 !important;
        color: #131A24 !important;
        letter-spacing: -0.02em;
    }

    /* ── 탭 바를 상용 사이트풍으로 ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        border-bottom: 1px solid #E2E6EC;
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        padding: 0 18px;
        background: transparent;
        border: none;
        border-radius: 8px 8px 0 0;
        color: #64748B;
        font-weight: 700;
        font-size: 14px;
    }
    .stTabs [data-baseweb="tab"]:hover { background: #EEF1F5; color: #334155; }
    .stTabs [aria-selected="true"] {
        color: #1B2A4A !important;
        background: #FFFFFF !important;
        border-bottom: 2.5px solid #1B2A4A !important;
    }
    .stTabs [data-baseweb="tab-highlight"] { display: none; }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 18px; }

    /* ── 버튼 ── */
    .stButton > button {
        border-radius: 9px;
        font-weight: 750;
        border: 1px solid #D5DAE1;
        transition: all .12s ease;
    }
    .stButton > button:hover { border-color: #1B2A4A; color: #1B2A4A; }
    .stButton > button[kind="primary"] {
        background: #1B2A4A;
        border: 1px solid #1B2A4A;
    }
    .stButton > button[kind="primary"]:hover { background: #25365C; color: #fff; }

    /* ── divider/캡션/사이드바 ── */
    hr { margin: 14px 0 !important; border-color: #E6E9EE !important; }
    [data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E6E9EE; }
    [data-testid="stSidebar"] .stButton > button { border-radius: 8px; }
    [data-testid="stCaptionContainer"] { color: #6B7684; }

    /* ── 데이터프레임 ── */
    [data-testid="stDataFrame"] { border: 1px solid #E6E9EE; border-radius: 10px; }

    .fs-logic-wrap {
        border: 1px solid #D8DEE6;
        border-radius: 8px;
        background: #FFFFFF;
        padding: 18px 20px;
        margin: 14px 0 22px;
    }
    .fs-logic-kicker {
        color: #5A6573;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0;
        margin-bottom: 8px;
    }
    .fs-logic-title {
        color: #17202A;
        font-size: 20px;
        font-weight: 850;
        letter-spacing: 0;
        margin-bottom: 8px;
    }
    .fs-logic-copy {
        color: #52606D;
        font-size: 14px;
        line-height: 1.55;
        margin-bottom: 16px;
    }
    .fs-logic-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
    }
    .fs-logic-node {
        border: 1px solid #E2E8F0;
        border-radius: 7px;
        padding: 12px 12px 13px;
        min-height: 128px;
        background: #FAFBFC;
    }
    .fs-logic-node strong {
        display: block;
        color: #173B57;
        font-size: 13px;
        margin-bottom: 7px;
    }
    .fs-logic-node span {
        display: block;
        color: #334155;
        font-size: 13px;
        line-height: 1.48;
    }
    .fs-map {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin-top: 10px;
    }
    .fs-map-step {
        border-left: 3px solid #173B57;
        background: #F8FAFC;
        padding: 10px 12px;
        border-radius: 0 7px 7px 0;
        min-height: 108px;
    }
    .fs-map-step b {
        display: block;
        color: #17202A;
        font-size: 13px;
        margin-bottom: 6px;
    }
    .fs-map-step span {
        color: #4B5563;
        font-size: 13px;
        line-height: 1.48;
    }
    @media (max-width: 900px) {
        .fs-logic-grid, .fs-map { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_validation_flow(compact: bool = False) -> None:
    """Show the report validation sequence without turning it into a tutorial."""
    if compact:
        st.markdown(
            """
            <div class="fs-logic-wrap">
              <div class="fs-logic-kicker">검증 순서</div>
              <div class="fs-logic-title">리포트 신뢰도를 네 단계로 확인합니다</div>
              <div class="fs-map">
                <div class="fs-map-step"><b>목표가 편차</b><span>각 리포트 목표가가 증권사 평균과 다른 리포트 대비 얼마나 높은지 봅니다.</span></div>
                <div class="fs-map-step"><b>발행 이후 괴리</b><span>리포트 발행 뒤 주가·수급·공시가 리포트 전제와 달라졌는지 봅니다.</span></div>
                <div class="fs-map-step"><b>필요 실적</b><span>목표가가 성립하려면 EPS가 얼마나 좋아져야 하는지 역산합니다.</span></div>
                <div class="fs-map-step"><b>본문 의견</b><span>리포트 안의 핵심 의견이 서로와 실제 데이터에 맞는지 대조합니다.</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        """
        <div class="fs-logic-wrap">
          <div class="fs-logic-kicker">검증 흐름</div>
          <div class="fs-logic-title">리포트 목표가와 본문 의견을 실제 데이터와 순서대로 대조합니다</div>
          <div class="fs-logic-copy">
            목표가가 시장 평균보다 얼마나 높은지, 발행 뒤 전제가 바뀌었는지,
            그 가격을 만들려면 실적이 얼마나 좋아져야 하는지, 본문 의견이 숫자로 확인되는지 봅니다.
          </div>
          <div class="fs-logic-grid">
            <div class="fs-logic-node"><strong>입력</strong><span>종목, 증권사, 발행일, 목표가, 투자의견을 기준점으로 둡니다.</span></div>
            <div class="fs-logic-node"><strong>목표가 편차</strong><span>증권사 목표가 평균과 업로드 리포트들 사이에서 얼마나 공격적인지 봅니다.</span></div>
            <div class="fs-logic-node"><strong>발행 이후 괴리</strong><span>발행일 이후 주가·수급·공시가 리포트 방향과 어긋났는지 확인합니다.</span></div>
            <div class="fs-logic-node"><strong>필요 실적</strong><span>목표가에 필요한 EPS 성장률을 과거 평균·중앙값 성장률과 비교합니다.</span></div>
            <div class="fs-logic-node"><strong>본문 의견</strong><span>PDF 본문에서 공통으로 말한 내용과 증권사별로 갈리는 해석을 DART·수급 데이터와 대조합니다.</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_product_header() -> None:
    """Render the validator title with a direct entry to the old analyst app."""
    title_col, mode_col = st.columns([5.0, 1.15])
    with title_col:
        st.markdown(
            "<div style='display:flex;align-items:center;gap:11px;margin:2px 0 2px'>"
            "<div style='width:36px;height:36px;border-radius:9px;"
            "background:linear-gradient(135deg,#1B2A4A 0%,#2E4A7A 100%);"
            "display:flex;align-items:center;justify-content:center;"
            "color:#fff;font-weight:900;font-size:18px;letter-spacing:-1px;"
            "box-shadow:0 2px 6px rgba(27,42,74,0.25)'>F</div>"
            "<div>"
            "<div style='font-size:23px;font-weight:850;color:#131A24;letter-spacing:-0.02em;line-height:1.1'>FinSight</div>"
            "<div style='font-size:12.5px;font-weight:650;color:#6B7684;margin-top:1px'>리포트 신뢰도 검증</div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
    with mode_col:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("Analyst Mode", key="open_analyst_mode", width="stretch"):
            st.query_params["view"] = "analyst"
            st.rerun()
    st.caption(PRODUCT_COPY)


# ──────────────────────────────────────────────
# 사이드바 — 자동 검색 / 직접 입력
# ──────────────────────────────────────────────
st.sidebar.markdown("### 리포트 신뢰도 검증")
st.sidebar.caption(
    "증권사 리포트의 목표가와 투자의견을 DART 재무·공시, KRX 주가·수급, "
    "발행 이후 뉴스, 리포트 본문 내용과 대조해 신뢰도를 점수화하고 현재 주가와의 차이를 해석하는 도구"
)
st.sidebar.divider()

# 모드 선택
# 분석 입력 (검색/입력 결과를 한 곳에 모음)
ready = False
selected_company = None
selected_target = None
sel_broker = ""
sel_opinion = "매수"
report_date = ""
sel_report_title = ""
sel_report_url = ""
sel_report_pdf_url = ""
sel_report_file_name = ""
sel_report_text = ""
sel_report_extract_status = ""
sel_report_target_evidence = ""
uploaded_report_summaries: list[dict] = []
consensus = None

st.sidebar.markdown("**1️⃣ 종목 검색**")
company_search = st.sidebar.text_input(
    "종목명", placeholder="예: 삼성전자, 농심, 카카오", label_visibility="collapsed",
)
if st.sidebar.button("🔍 검색", width="stretch") and company_search:
    st.session_state["search_result"] = search_company_and_consensus(company_search)

search_result = st.session_state.get("search_result") or {}

if search_result and search_result.get("success"):
    selected_company = search_result.get("company_name") or company_search
    consensus = search_result.get("consensus") or {}
    stock_code = search_result.get("stock_code")
    mean = consensus.get("price_target_mean") or 0
    if mean:
        # 현재가 + 당일 변동 추가
        current_price = dc.get_current_price(stock_code) if stock_code else None
        price_info = ""
        if current_price:
            market_snap = dc.get_market_snapshot(stock_code) if stock_code else {}
            change_pct = market_snap.get("return_1d")
            price_info = f" | 현재가 **{current_price:,.0f}원**"
            if change_pct is not None:
                arrow = "📈" if change_pct >= 0 else "📉"
                price_info += f" {arrow} {change_pct:+.1f}%"

        st.sidebar.success(
            f"**{selected_company}**\n\n"
            f"증권사 목표가 평균 **{mean:,.0f}원**{price_info}\n\n"
            f"투자의견 {consensus.get('opinion_label', '확인 필요')} · {consensus.get('create_date', '')}"
        )
    else:
        st.sidebar.success(f"**{selected_company}** 종목코드 {stock_code} 확인")
        st.sidebar.caption("증권사 목표가 평균은 확인하지 못했습니다. PDF 업로드 또는 목표가 직접 입력으로 검증을 진행하세요.")

    st.sidebar.markdown("**2️⃣ 검증할 리포트**")
    reports = fetch_research_list(stock_code) if stock_code else []
    selected_naver_report = None
    research_list_url = (
        "https://finance.naver.com/research/company_list.naver"
        f"?searchType=itemCode&itemCode={stock_code}"
    )
    if reports:
        broker_names = []
        for item in reports[:6]:
            broker = item.get("broker", "")
            if broker and broker not in broker_names:
                broker_names.append(broker)
        if broker_names:
            st.sidebar.caption(f"최근 리포트 발간: {', '.join(broker_names[:4])}")
        labels = ["직접 입력"] + [
            f"{item.get('date', '')} · {item.get('broker', '')} · {item.get('title', '')}"
            for item in reports
        ]
        chosen = st.sidebar.selectbox("네이버 리포트 선택", labels)
        if chosen != "직접 입력":
            selected_naver_report = reports[labels.index(chosen) - 1]
            sel_report_title = selected_naver_report.get("title", "")
            sel_report_url = selected_naver_report.get("read_url", "")
            sel_report_pdf_url = selected_naver_report.get("pdf_url", "")
            if sel_report_pdf_url:
                st.sidebar.markdown(f"[원문 PDF 열기]({sel_report_pdf_url})")
        with st.sidebar.expander("최근 리포트 링크 보기"):
            for item in reports[:6]:
                title = f"{item.get('date', '')} · {item.get('broker', '')} · {item.get('title', '')}"
                links = []
                if item.get("read_url"):
                    links.append(f"[요약]({item['read_url']})")
                if item.get("pdf_url"):
                    links.append(f"[PDF]({item['pdf_url']})")
                st.markdown(f"- **{title}** {' · '.join(links)}")
    else:
        st.sidebar.caption("네이버 종목분석 리포트 목록을 찾지 못했습니다. 직접 입력으로 검증합니다.")

    default_broker = (selected_naver_report or {}).get("broker", "")
    default_date = None
    if selected_naver_report and selected_naver_report.get("date"):
        try:
            default_date = datetime.date.fromisoformat(selected_naver_report["date"])
        except ValueError:
            default_date = None
    target_default = int(mean or 0)
    target_help = "기본값은 증권사 목표가 평균입니다. 특정 리포트 목표가로 바꿔보세요."
    opinion_default = "매수"

    st.sidebar.markdown("**PDF 파일 업로드**")
    uploaded_reports = st.sidebar.file_uploader(
        "증권사 리포트 PDF", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed",
        help="리포트 원문을 넣으면 이후 리포트 주장과 FinSight 데이터의 대조 분석으로 확장할 수 있습니다.",
    )
    if uploaded_reports:
        upload_fingerprint = tuple((item.name, getattr(item, "size", 0)) for item in uploaded_reports)
        applied_fingerprint = st.session_state.get("uploaded_report_fingerprint")
        if applied_fingerprint != upload_fingerprint:
            st.sidebar.caption(f"{len(uploaded_reports)}개 파일 선택됨. 아래 버튼을 눌러 분석에 반영하세요.")
        if st.sidebar.button("업로드 완료 · 분석에 반영", type="primary", width="stretch"):
            processed_reports = []
            for uploaded_report in uploaded_reports:
                text, status = extract_report_pdf_text(uploaded_report.getvalue())
                meta = extract_report_metadata(uploaded_report.name, text)
                meta["extract_status"] = status
                processed_reports.append(meta)
            st.session_state["uploaded_report_summaries"] = processed_reports
            st.session_state["uploaded_report_fingerprint"] = upload_fingerprint
            applied_fingerprint = upload_fingerprint
            st.sidebar.success(f"{len(processed_reports)}개 리포트를 분석에 반영했습니다.")
        if applied_fingerprint == upload_fingerprint:
            uploaded_report_summaries = st.session_state.get("uploaded_report_summaries", [])
    else:
        st.session_state.pop("uploaded_report_summaries", None)
        st.session_state.pop("uploaded_report_fingerprint", None)

    if uploaded_report_summaries:
        missing_before_manual = reports_missing_target(uploaded_report_summaries)
        if missing_before_manual:
            names = " / ".join(report_identity(item) for item in missing_before_manual[:3])
            suffix = f" 외 {len(missing_before_manual) - 3}개" if len(missing_before_manual) > 3 else ""
            st.sidebar.warning(
                f"목표가를 자동으로 읽지 못한 리포트: {names}{suffix}. "
                "입력하지 않으면 이 리포트는 중앙 목표가 계산과 현실 부합도 점수에서 제외됩니다."
            )
            with st.sidebar.expander("목표가 직접 입력"):
                st.caption("원문 목표가를 입력하면 해당 리포트 비교표와 중앙 목표가 계산에 반영합니다.")
                changed = False
                for idx, item in enumerate(uploaded_report_summaries):
                    if item.get("target_price"):
                        continue
                    key = f"manual_target_{idx}_{re.sub(r'[^0-9A-Za-z가-힣]+', '_', item.get('file_name', 'report'))[:28]}"
                    manual_target = st.number_input(
                        report_identity(item),
                        min_value=0,
                        value=0,
                        step=1000,
                        key=key,
                        help="이 입력값은 해당 리포트의 목표가로만 쓰입니다.",
                    )
                    if manual_target and manual_target > 0:
                        item["target_price"] = int(manual_target)
                        item["target_evidence"] = "사용자 직접 입력"
                        changed = True
                if changed:
                    st.session_state["uploaded_report_summaries"] = uploaded_report_summaries
                    st.success("직접 입력한 목표가를 반영했습니다.")

        stats = report_batch_stats(uploaded_report_summaries)
        sel_report_file_name = f"{len(uploaded_report_summaries)}개 PDF"
        sel_report_text = "\n\n".join(
            item.get("text_excerpt", "")[:2500]
            for item in uploaded_report_summaries
            if item.get("text_excerpt")
        )[:12000]
        sel_report_extract_status = (
            f"{len(uploaded_report_summaries)}개 PDF 반영 · "
            f"목표가 {stats['target_count']}/{stats['count']}개 추출"
        )
        evidence_items = [
            f"{item.get('broker') or item.get('title')}: {item.get('target_evidence')}"
            for item in uploaded_report_summaries
            if item.get("target_evidence")
        ]
        sel_report_target_evidence = " / ".join(evidence_items[:3])
        if not sel_report_title:
            sel_report_title = f"{selected_company} 업로드 리포트 {len(uploaded_report_summaries)}개 종합"
        default_broker = "복수 증권사" if len(uploaded_report_summaries) > 1 else (uploaded_report_summaries[0].get("broker") or default_broker)
        if stats.get("latest_date"):
            try:
                default_date = datetime.date.fromisoformat(stats["latest_date"])
            except ValueError:
                pass
        if stats.get("majority_opinion"):
            opinion_default = stats["majority_opinion"]
        if stats.get("median_target"):
            target_default = int(stats["median_target"])
            target_help = "업로드 PDF들의 중앙 목표가입니다. 개별 리포트별 목표가는 비교표에서 따로 확인하세요."
        else:
            target_default = 0
            target_help = "업로드 PDF에서 목표가를 확정적으로 읽지 못했습니다. 원문 목표가를 직접 입력하세요."
        st.sidebar.success(f"{len(uploaded_report_summaries)}개 업로드됨")
        st.sidebar.caption(sel_report_extract_status)
        if stats["target_count"] < stats["count"]:
            missing_after_manual = reports_missing_target(uploaded_report_summaries)
            missing_names = " / ".join(report_identity(item) for item in missing_after_manual[:3])
            st.sidebar.warning(
                f"아직 목표가가 없는 리포트는 계산에서 제외됩니다: {missing_names}"
            )
        with st.sidebar.expander("업로드 리포트 비교"):
            st.dataframe(
                pd.DataFrame(build_report_comparison_rows(uploaded_report_summaries, consensus.get("price_target_mean"))),
                hide_index=True,
                width="stretch",
            )

    search_query = quote(f"{selected_company} 증권사 리포트 PDF")
    naver_search_url = f"https://search.naver.com/search.naver?query={search_query}"
    google_search_url = f"https://www.google.com/search?q={search_query}"
    st.sidebar.markdown(
        f"""
        <div style="margin:12px 0 14px;padding:10px 11px;border:1px solid #D7E1EA;
                    border-radius:8px;background:#F8FAFC">
          <div style="font-size:13px;font-weight:800;color:#17202A;margin-bottom:7px">
            리포트 파일을 못 찾았다면
          </div>
          <div style="font-size:13px;line-height:1.9">
            <a href="{research_list_url}" target="_blank"
               style="font-weight:750;color:#185FA5;text-decoration:none">네이버 리서치 목록</a>
            <span style="color:#CBD5E1"> | </span>
            <a href="{naver_search_url}" target="_blank"
               style="font-weight:750;color:#185FA5;text-decoration:none">네이버 검색</a>
            <span style="color:#CBD5E1"> | </span>
            <a href="{google_search_url}" target="_blank"
               style="font-weight:750;color:#185FA5;text-decoration:none">구글 검색</a>
          </div>
          <div style="font-size:12px;color:#667085;margin-top:5px;line-height:1.45">
            원문 PDF를 받은 뒤 바로 위 업로드 칸에 넣으면 됩니다.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.caption("목표가는 리포트 원문에 적힌 숫자를 입력하세요.")
    selected_target = st.sidebar.number_input(
        "목표가 (원)", min_value=0, value=int(target_default), step=1000,
        help=target_help,
    )
    sel_broker = st.sidebar.text_input("증권사명 (선택)", value=default_broker, placeholder="예: 한화투자증권")
    date_obj = st.sidebar.date_input("발행일", value=default_date or "today")
    report_date = date_obj.strftime("%Y-%m-%d") if date_obj else ""
    opinion_options = ["매수", "중립", "매도"]
    sel_opinion = st.sidebar.selectbox(
        "투자의견",
        opinion_options,
        index=opinion_options.index(opinion_default) if opinion_default in opinion_options else 0,
    )

    ready = selected_target and selected_target > 0

elif search_result:
    st.sidebar.warning(search_result.get("message", "종목 검색 결과를 확인하지 못했습니다."))
    st.sidebar.caption("종목코드는 찾았으나 증권사 커버리지가 없을 수 있습니다.")

st.sidebar.divider()
st.sidebar.caption("💡 종목 검색 → 증권사 목표가 평균 확인 → 검증할 목표가 입력")


# ──────────────────────────────────────────────
# 데이터 분석
# ──────────────────────────────────────────────
@st.cache_data(show_spinner="🔬 리포트 검증 중...")
def load_analysis(company_name: str, report_date: str, target_price: int,
                  consensus: dict = None, sel_broker: str = "",
                  sel_opinion: str = "매수", report_title: str = "",
                  report_url: str = "", report_pdf_url: str = "",
                  report_file_name: str = "", report_text: str = "",
                  report_extract_status: str = "",
                  report_target_evidence: str = "",
                  report_batch: list[dict] | None = None,
                  cache_version: int = 2):
    """검증할 리포트 목표가 기반 검증.

    실제 DART 재무 수집을 우선하고, 실패 시 보조 재무 데이터로 앱 흐름을 유지한다.
    ①축은 네이버 증권사 목표가 평균 대비 위치로 판단한다.
    """
    real = fetch_real_financials(company_name)

    if real:
        # ── 실데이터 경로 ──
        financials = real["financials"]
        kpis = calculate_quarterly_kpis(financials)
        shares = real["shares_outstanding"]
        price = real["current_price"]
        stock_code = real["stock_code"]
        comp_name = real["company_name"]
        is_demo = False
        # 발행일 이후 외국인 수급 — 기간·일평균·최근 흐름까지 함께 보관
        foreign_flow = fetch_foreign_flow(stock_code, report_date)
        # 발행일 주가 — pykrx 자동 조회, 실패 시 현재가로 폴백
        price_at_pub = fetch_price_at_date(stock_code, report_date) or price
        context = fetch_report_context(comp_name, stock_code)
        post_events = build_post_report_events(context, report_date, {"opinion": sel_opinion, "target_price": target_price})
        comp_code = stock_code
    else:
        # ── 데모 폴백 ──
        financials = D.build_demo_financials()
        kpis = calculate_quarterly_kpis(financials)
        shares = D.DEMO_COMPANY["shares_outstanding"]
        price = D.DEMO_COMPANY["current_price"]
        comp_name = company_name or D.DEMO_COMPANY["name"]
        comp_code = D.DEMO_COMPANY["code"]
        is_demo = True
        foreign_flow = {
            "net_eok": D.DEMO_FOREIGN_NET_EOK,
            "start": report_date,
            "end": datetime.date.today().isoformat(),
            "trading_days": None,
            "avg_daily_eok": None,
            "recent_5d_eok": None,
            "buy_days": None,
            "sell_days": None,
            "source": "데모 보조 수급값",
            "available": True,
        }
        post_events = D.DEMO_POST_EVENTS
        price_at_pub = 420000
        context = {"disclosures": [], "ownership": [], "news": [], "blogs": [], "market": {}, "external_drivers": {}, "errors": []}

    multiples = calculate_multiple_valuation(
        kpis=kpis, shares_outstanding=shares, net_debt=0, current_price=price,
    )
    valuation_range = build_valuation_range(
        dcf=None, multiples=multiples, current_price=price,
    )

    # ③ 필요 실적 (목표가 역산)
    try:
        reverse = reverse_engineer_target(
            target_price=target_price, kpis=kpis,
            shares_outstanding=shares, current_price=price,
        )
    except Exception as exc:
        reverse = reverse_engineer_target_lenient(
            target_price=target_price,
            kpis=kpis,
            shares_outstanding=shares,
            current_price=price,
            reason=str(exc),
        )
    if "need_eps" not in reverse and reverse.get("current_eps") is not None:
        reverse["need_eps"] = round(float(reverse["current_eps"]) * (1 + float(reverse.get("need_growth", 0)) / 100))
    research = get_research_reference(comp_name)
    price_action = interpret_price_action(
        kpis,
        context.get("market", {}),
        context.get("ownership", []),
        context.get("disclosures", []),
        research,
        context.get("news", []),
        context.get("blogs", []),
    )

    # ① 목표가 편차 (네이버 증권사 목표가 평균 대비 위치)
    distribution = locate_vs_consensus(target_price, consensus)

    # ② 발행 이후 괴리
    timeline = build_post_publish_timeline(
        report={
            "pub_date": report_date,
            "opinion": sel_opinion,
            "target_price": target_price,
            "price_at_pub": price_at_pub,
        },
        current_price=price,
        post_events=post_events,
        foreign_flow_fallback=foreign_flow,
    )
    batch_timeline = build_batch_post_publish_analysis(
        report_batch or [],
        stock_code=comp_code,
        current_price=price,
        consensus=consensus,
        fallback_price_at_pub=price_at_pub,
    )

    report_payload = {
        "pub_date": report_date,
        "opinion": sel_opinion,
        "target_price": target_price,
        "broker": sel_broker,
        "title": report_title,
        "url": report_url,
        "pdf_url": report_pdf_url,
        "file_name": report_file_name,
        "text_excerpt": (report_text or "")[:12000],
        "extract_status": report_extract_status,
        "target_evidence": report_target_evidence,
        "has_uploaded_file": bool(report_file_name),
        "batch_count": len(report_batch or []),
    }
    content_analysis = analyze_report_content_batch({
        "report": report_payload,
        "report_batch": report_batch or [],
        "kpis": kpis,
        "timeline": timeline,
        "context": context,
        "price_action": price_action,
    })
    content_assessment = assess_report_content_consistency(content_analysis)
    content_analysis["briefing"] = build_report_briefing(content_analysis, content_assessment)

    # 종합 신뢰도
    verdict = build_report_verdict(
        distribution=distribution, timeline=timeline, reverse=reverse,
        report=report_payload,
    )
    alignment = build_alignment_assessment(
        kpis=kpis,
        report=report_payload,
        distribution=distribution,
        timeline=timeline,
        reverse=reverse,
        price_action=price_action,
    )
    alignment = merge_content_assessment_into_alignment(alignment, content_assessment)
    verdict = apply_alignment_to_verdict(verdict, alignment)

    return {
        "company": {"name": comp_name, "code": comp_code, "current_price": price,
                    "shares_outstanding": shares},
        "report": {**report_payload, "price_at_pub": price_at_pub},
        "kpis": kpis,
        "multiples": multiples,
        "valuation_range": valuation_range,
        "reverse": reverse,
        "distribution": distribution,
        "consensus": consensus,
        "timeline": timeline,
        "report_batch_timeline": batch_timeline,
        "verdict": verdict,
        "alignment": alignment,
        "report_content": content_analysis,
        "report_content_assessment": content_assessment,
        "context": context,
        "research": research,
        "price_action": price_action,
        "report_batch": report_batch or [],
        "is_demo_financials": is_demo,
    }

if ready:
    A = load_analysis(
        selected_company,
        report_date,
        int(selected_target),
        consensus=consensus,
        sel_broker=sel_broker,
        sel_opinion=sel_opinion,
        report_title=sel_report_title,
        report_url=sel_report_url,
        report_pdf_url=sel_report_pdf_url,
        report_file_name=sel_report_file_name,
        report_text=sel_report_text,
        report_extract_status=sel_report_extract_status,
        report_target_evidence=sel_report_target_evidence,
        report_batch=uploaded_report_summaries,
    )
else:
    A = None

# 초기 안내 화면
if A is None:
    render_product_header()

    # ── 히어로 ──
    st.markdown(
        "<div style='margin:18px 0 6px;padding:34px 36px;border-radius:16px;"
        "background:linear-gradient(135deg,#1B2A4A 0%,#2C4470 55%,#34548A 100%);"
        "box-shadow:0 8px 24px rgba(27,42,74,0.18)'>"
        "<div style='display:inline-block;font-size:12px;font-weight:800;color:#BBD0EE;"
        "background:rgba(255,255,255,0.10);padding:5px 12px;border-radius:20px;margin-bottom:14px'>"
        "증권사 리포트 신뢰도 검증</div>"
        "<div style='font-size:30px;font-weight:850;color:#FFFFFF;line-height:1.28;letter-spacing:-0.02em'>"
        "목표가를 그대로 믿기 전에,<br>데이터로 먼저 검증하세요</div>"
        "<div style='font-size:14.5px;color:#CDD8EA;line-height:1.65;margin-top:14px;max-width:680px'>"
        "DART 재무·공시, KRX 주가·수급, 증권사 목표가 평균, 발행 이후 뉴스·지분 변동, "
        "리포트 본문을 한 번에 대조해 목표가와 투자의견의 신뢰도를 점수화합니다.</div>"
        "<div style='font-size:13px;color:#9DB2D4;margin-top:16px;font-weight:600'>"
        "← 왼쪽에서 종목을 검색하고 검증할 리포트를 선택하면 분석이 시작됩니다</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── 4단계 검증 카드 ──
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    intro_steps = [
        ("01", "목표가 편차", COLOR["space"], "리포트 목표가가 증권사 평균과 다른 리포트 대비 얼마나 공격적인지 봅니다."),
        ("02", "발행 이후 괴리", COLOR["time"], "발행 뒤 주가·수급·공시가 리포트가 깔아둔 전제와 달라졌는지 확인합니다."),
        ("03", "필요 실적", COLOR["logic"], "그 목표가가 성립하려면 EPS가 얼마나 좋아져야 하는지 역산해 과거와 비교합니다."),
        ("04", "본문 의견", COLOR["primary"], "리포트 본문의 핵심 주장이 서로, 그리고 실제 데이터와 맞아떨어지는지 대조합니다."),
    ]
    intro_html = "".join(
        f"<div style='border:1px solid #E6E9EE;border-radius:12px;padding:18px 18px 20px;"
        f"background:#FFFFFF;box-shadow:0 1px 2px rgba(16,24,40,0.04)'>"
        f"<div style='font-size:13px;font-weight:900;color:{color};letter-spacing:1px'>{num}</div>"
        f"<div style='font-size:16px;font-weight:850;color:#131A24;margin:8px 0 8px'>{title}</div>"
        f"<div style='font-size:13px;color:#5A6573;line-height:1.55'>{desc}</div>"
        f"<div style='height:3px;width:32px;background:{color};border-radius:3px;margin-top:14px'></div>"
        f"</div>"
        for num, title, color, desc in intro_steps
    )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px'>{intro_html}</div>",
        unsafe_allow_html=True,
    )

    st.stop()

# 이후는 A가 있을 때만 실행
co, rep, V = A["company"], A["report"], A["verdict"]
content_view = A.get("report_content") or analyze_report_content_batch(A)
content_assessment = A.get("report_content_assessment") or assess_report_content_consistency(content_view)
content_briefing = content_view.get("briefing") or build_report_briefing(content_view, content_assessment)
content_view["briefing"] = content_briefing

# ──────────────────────────────────────────────
# 헤더
# ──────────────────────────────────────────────
render_product_header()
st.markdown(
    f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;"
    f"padding:13px 18px;border:1px solid #E2E8F0;border-radius:10px;background:#FFFFFF;margin:6px 0 4px'>"
    f"<span style='font-size:19px;font-weight:850;color:#17202A'>{co['name']}</span>"
    f"<span style='color:#CBD5E1'>|</span>"
    f"<span style='font-size:14px;color:#475569'>{rep['broker']} · {rep['pub_date']}</span>"
    f"<span style='font-size:13px;font-weight:800;color:#185FA5;background:#EAF2FB;"
    f"padding:2px 10px;border-radius:20px'>{rep['opinion']}</span>"
    f"<span style='font-size:14px;color:#475569'>목표가 "
    f"<b style='color:#17202A;font-size:15px'>{rep['target_price']:,}원</b></span>"
    f"</div>",
    unsafe_allow_html=True,
)
meta_lines = []
if rep.get("title"):
    meta_lines.append(f"<div><b>검증 리포트</b>: {html.escape(str(rep['title']))}</div>")
if rep.get("file_name"):
    status_text = f" · {rep.get('extract_status')}" if rep.get("extract_status") else ""
    meta_lines.append(f"<div><b>업로드 리포트</b>: {html.escape(str(rep['file_name'] + status_text))}</div>")
if rep.get("batch_count", 0) > 1:
    meta_lines.append(
        f"<div>업로드 리포트 {int(rep['batch_count'])}개를 비교하고, 종합 점수는 추출된 목표가의 중앙값을 기준으로 계산했습니다.</div>"
    )
if rep.get("pdf_url"):
    meta_lines.append(
        f"<div><a href='{html.escape(str(rep['pdf_url']))}' target='_blank' "
        f"style='color:#185FA5;text-decoration:none;font-weight:700'>원문 PDF 열기</a></div>"
    )

html_report = generate_retail_html_report(A)
try:
    pdf_report = generate_retail_pdf_report(A)
except Exception:
    pdf_report = None

if A.get("is_demo_financials"):
    meta_lines.append(
        "재무 항목은 현재 연결 가능한 보조값으로 계산했습니다. 실제 DART 반영 상태와 점수 영향은 '근거·출처' 탭에서 확인할 수 있습니다."
    )
    with st.expander("🔍 DART 재무가 연결 안 되는 이유 진단", expanded=True):
        diag_rows = diagnose_real_financials(selected_company or co.get("name", ""))
        st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)
        st.caption(
            "❌가 처음 뜨는 단계가 원인입니다. "
            "DART_API_KEY가 ❌면 Streamlit Cloud Secrets에 키를 넣으세요. "
            "현재가만 ❌면 클라우드에서 외부 시세 접근이 막힌 것이라 별도 처리가 필요합니다."
        )
else:
    share_text = f" · 발행주식수 {co['shares_outstanding']:,.0f}주" if co.get("shares_outstanding") else ""
    meta_lines.append(f"실제 DART 재무 연동 · 현재가 {co['current_price']:,.0f}원{share_text}")
    if (A.get("reverse") or {}).get("limited"):
        meta_lines.append(f"필요 실적은 보조 계산으로 표시합니다: {(A.get('reverse') or {}).get('limited_reason')}")

if meta_lines:
    st.markdown(
        "<div style='font-size:12.5px;color:#667085;line-height:1.34;margin:-1px 0 7px 2px'>"
        + "".join(f"<div style='margin:0 0 1px 0'>{line}</div>" for line in meta_lines)
        + "</div>",
        unsafe_allow_html=True,
    )

render_report_batch_overview(A)

# ──────────────────────────────────────────────
# 신뢰도 카드
# ──────────────────────────────────────────────
grade_color = {
    "A": COLOR["grade_a"],
    "B": COLOR["grade_b"],
    "C": COLOR["grade_c"],
    "D": COLOR["grade_d"],
    "E": COLOR["grade_e"],
}
gc = grade_color.get(V["grade"], COLOR["grade_d"])

sc1, sc2 = st.columns([1, 2.4])

with sc1:
    base_total = V.get("base_total", V["total"])
    penalty = V.get("alignment", {}).get("penalty", 0)
    st.markdown(
        f"<div style='text-align:center;padding:0 0 20px;border:1px solid #E6E9EE;"
        f"border-radius:14px;background:#FFFFFF;overflow:hidden;"
        f"box-shadow:0 2px 8px rgba(16,24,40,0.06)'>"
        f"<div style='height:5px;background:{gc}'></div>"
        f"<div style='padding:18px 8px 0'>"
        f"<div style='font-size:12px;color:#8A94A3;font-weight:700;letter-spacing:0.3px'>신뢰도 점수</div>"
        f"<div style='font-size:52px;font-weight:900;color:{gc};line-height:1.05;letter-spacing:-0.03em'>{V['total']}"
        f"<span style='font-size:17px;color:#B0B8C4;font-weight:700'> /100</span></div>"
        f"<div style='display:inline-block;font-size:14px;color:#fff;font-weight:800;background:{gc};"
        f"padding:3px 14px;border-radius:20px;margin:8px 0 8px'>{V['grade']}등급 · {V['label']}</div>"
        f"<div style='font-size:21px;letter-spacing:3px;color:{gc};margin-top:2px'>{'★'*V['stars']}<span style='color:#D8DEE6'>{'★'*(5-V['stars'])}</span></div>"
        f"<div style='font-size:12px;color:#8A94A3;margin-top:12px'>기초 {base_total}점 · 객관분석 −{penalty}점</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

with sc2:
    st.markdown("<div style='height:42px'></div>", unsafe_allow_html=True)
    st.markdown("#### 세부 점수")
    for key, title in [("space", "목표가 편차"), ("time", "발행 이후 괴리"), ("logic", "필요 실적")]:
        ax = V["axes"][key]
        if ax.get("uncounted"):
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin:6px 0'>"
                f"<span style='width:100px;font-size:13px;font-weight:600'>{title}</span>"
                f"<span style='flex:1;background:#E3E1D8;border-radius:3px;height:12px;'></span>"
                f"<span style='width:50px;text-align:right;font-size:12px;color:#999'>데이터 없음</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            pct = int(ax["score"] / ax["max"] * 100)
            bar_colors = {"space": COLOR["space"], "time": COLOR["time"], "logic": COLOR["logic"]}
            bar_color = bar_colors.get(key, COLOR["primary"])
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin:6px 0'>"
                f"<span style='width:100px;font-size:13px;font-weight:600'>{title}</span>"
                f"<span style='flex:1;background:#E3E1D8;border-radius:3px;height:12px;position:relative'>"
                f"<span style='position:absolute;left:0;top:0;height:12px;width:{pct}%;background:{bar_color};border-radius:3px'></span></span>"
                f"<span style='width:50px;text-align:right;font-size:13px;font-weight:700'>{ax['score']}/{ax['max']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    content_penalty = content_assessment.get("penalty", 0)
    content_label = content_assessment.get("label", "본문 미반영")
    penalty_text = "차감 없음" if not content_penalty else f"-{content_penalty}점"
    st.caption(f"본문 의견 검증: {content_label} · 객관분석 {penalty_text}")

# 핵심 결론은 한 줄 배너로만 고정 노출.
# 상세 평가의견·객관분석 대조는 '종합평가' 탭에서 전체를 봅니다.
st.markdown(
    f"<div style='margin:14px 0 4px;padding:12px 16px;border-left:4px solid {gc};"
    f"background:{COLOR['bg']};border-radius:0 8px 8px 0'>"
    f"<span style='font-size:15px;font-weight:800;color:#17202A'>{V['headline']}</span>"
    f"<span style='font-size:13px;color:#667085;margin-left:8px'>· 자세한 평가의견과 객관분석 대조는 ‘종합평가’ 탭에서 확인하세요</span>"
    f"</div>",
    unsafe_allow_html=True,
)

st.divider()

# ──────────────────────────────────────────────
# 핵심 신호 카드
# ──────────────────────────────────────────────
def signal_icon(verdict: str) -> str:
    if verdict in ("낙관", "과도한 낙관", "확인 필요", "다소 높음", "낙관 해석 주의", "일부 재확인"):
        return "🟠"
    if verdict in ("현실적", "양호", "평균권", "큰 충돌 제한"):
        return "🟢"
    return "⚪"


def render_detail_block(title: str, body: str, impact: str, basis: str | None = None) -> None:
    """Compact explanation line that does not push tab content downward."""
    basis_html = f"<span class='fs-detail-basis'>근거: {basis}</span>" if basis else ""
    st.markdown(
        f"""
        <div class="fs-detail-line">
          <span class="fs-detail-title">{title}</span>
          <span class="fs-detail-body">{body}</span>
          <div class="fs-detail-meta">
            <span class="fs-detail-impact">{impact}</span>
            {basis_html}
          </div>
        </div>
        <style>
        .fs-detail-line {{
            margin: 8px 0 12px;
            padding: 2px 0 8px;
            border-bottom: 1px solid #E5EAF0;
            color: #334155;
            font-size: 13px;
            line-height: 1.55;
        }}
        .fs-detail-title {{
            display: inline;
            color: #173B57;
            font-weight: 850;
            margin-right: 8px;
        }}
        .fs-detail-body {{ display: inline; }}
        .fs-detail-meta {{
            margin-top: 3px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px 12px;
            align-items: baseline;
        }}
        .fs-detail-impact {{
            display: inline-block;
            color: #17202A;
            font-weight: 800;
        }}
        .fs-detail-basis {{
            display: inline-block;
            color: #667085;
            font-size: 12px;
            line-height: 1.4;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_axis_brief(question: str, data: str, output: str) -> None:
    """Small top strip that makes the decision flow visible in each tab."""
    st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1.05fr 1.25fr 1fr;gap:10px;
                    margin:4px 0 14px;padding:10px 12px;border:1px solid #E2E8F0;
                    border-radius:7px;background:#FFFFFF">
          <div><span style="font-size:11px;color:#64748B;font-weight:800">판단 질문</span><br>
          <span style="font-size:13px;color:#17202A;line-height:1.45">{question}</span></div>
          <div><span style="font-size:11px;color:#64748B;font-weight:800">대조 데이터</span><br>
          <span style="font-size:13px;color:#17202A;line-height:1.45">{data}</span></div>
          <div><span style="font-size:11px;color:#64748B;font-weight:800">결론</span><br>
          <span style="font-size:13px;color:#17202A;line-height:1.45">{output}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _brief_item_html(item: dict) -> str:
    title = html.escape(str(item.get("title") or "핵심 내용"))
    read = html.escape(str(item.get("read") or ""))
    claim = html.escape(str(item.get("claim") or ""))
    evidence = html.escape(str(item.get("evidence") or ""))
    mention = html.escape(str(item.get("mention") or ""))
    claim_html = f"<div class='fs-brief-source'>리포트 본문: {claim}</div>" if claim else ""
    evidence_html = f"<div class='fs-brief-evidence'>데이터 대조: {evidence}</div>" if evidence else ""
    mention_html = f"<span>{mention}</span>" if mention else ""
    return f"""
      <li>
        <div class="fs-brief-item-title">{title} {mention_html}</div>
        <div class="fs-brief-read">{read}</div>
        {claim_html}
        {evidence_html}
      </li>
    """


def _brief_section_html(title: str, items: list[dict], empty: str) -> str:
    body = "".join(_brief_item_html(item) for item in items)
    if not body:
        body = f"<li><div class='fs-brief-read muted'>{html.escape(empty)}</div></li>"
    return f"""
      <section>
        <h4>{html.escape(title)}</h4>
        <ul>{body}</ul>
      </section>
    """


def render_report_briefing(briefing: dict) -> None:
    if not briefing or not briefing.get("headline"):
        return
    headline = html.escape(str(briefing.get("headline") or ""))
    st.markdown(
        f"""
        <div class="fs-brief-wrap">
          <div class="fs-brief-kicker">리포트에서 실제로 가져갈 내용</div>
          <div class="fs-brief-head">{headline}</div>
          <div class="fs-brief-grid">
            {_brief_section_html("믿고 가져갈 내용", briefing.get("trusted") or [], "아직 강하게 확인된 공통 내용은 없습니다.")}
            {_brief_section_html("아직 보수적으로 볼 내용", briefing.get("watch") or [], "큰 차감으로 볼 내용은 제한적입니다.")}
            {_brief_section_html("리포트끼리 갈리는 내용", briefing.get("contested") or [], "증권사별 해석 차이는 크게 잡히지 않았습니다.")}
          </div>
        </div>
        <style>
        .fs-brief-wrap {{
            margin: 10px 0 14px;
            padding: 13px 14px 12px;
            border: 1px solid #DCE6EF;
            border-radius: 8px;
            background: #FFFFFF;
        }}
        .fs-brief-kicker {{
            color: #185FA5;
            font-size: 12px;
            font-weight: 850;
            margin-bottom: 5px;
        }}
        .fs-brief-head {{
            color: #17202A;
            font-size: 14px;
            font-weight: 760;
            line-height: 1.55;
            margin-bottom: 10px;
        }}
        .fs-brief-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }}
        .fs-brief-grid section {{
            border-top: 2px solid #E5EAF0;
            padding-top: 8px;
        }}
        .fs-brief-grid h4 {{
            margin: 0 0 6px;
            color: #173B57;
            font-size: 13px;
        }}
        .fs-brief-grid ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .fs-brief-grid li {{
            margin: 0 0 10px;
        }}
        .fs-brief-item-title {{
            color: #17202A;
            font-size: 13px;
            font-weight: 850;
            line-height: 1.35;
        }}
        .fs-brief-item-title span {{
            color: #64748B;
            font-size: 11px;
            font-weight: 750;
        }}
        .fs-brief-read {{
            color: #334155;
            font-size: 12.5px;
            line-height: 1.55;
            margin-top: 3px;
        }}
        .fs-brief-source, .fs-brief-evidence {{
            color: #667085;
            font-size: 11.5px;
            line-height: 1.45;
            margin-top: 3px;
        }}
        .fs-brief-read.muted {{
            color: #94A3B8;
        }}
        @media (max-width: 900px) {{
            .fs-brief-grid {{ grid-template-columns: 1fr; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

dist = A["distribution"]
tl = A["timeline"]
rev = A["reverse"]
if "need_eps" not in rev and rev.get("current_eps") is not None:
    rev["need_eps"] = round(float(rev["current_eps"]) * (1 + float(rev.get("need_growth", 0)) / 100))

sig = "확인 필요" if tl["supply_gap"] else "양호"
content_label = content_assessment.get("label", "본문 미반영")
if content_assessment.get("score") is None:
    content_caption = "PDF 본문을 읽으면 리포트별 의견 차이를 반영합니다"
else:
    content_caption = (
        f"논점 {len(content_view.get('theme_rows', []))}개 · "
        f"객관분석 -{content_assessment.get('penalty', 0)}점"
    )

signal_cards = [
    ("① 목표가 편차", COLOR["space"], signal_icon(dist["position"]), dist["position"],
     f"목표가 평균 {dist['mean']:,.0f}원 대비 {dist['vs_median_pct']:+.1f}%"),
    ("② 발행 이후 괴리", COLOR["time"], signal_icon(sig), sig,
     f"발행 {tl['elapsed']}일 경과 · 여력 {tl['soak_pct']}% 소진"),
    ("③ 필요 실적", COLOR["logic"], signal_icon(rev["verdict"]), rev["verdict"],
     (rev.get("limited_reason") if rev.get("verdict") == "확인 필요"
      else f"필요 성장률 {rev['need_growth']:+.0f}% · 과거 중앙값 {rev['median_growth']:+.0f}%")),
    ("④ 본문 의견", COLOR["primary"], signal_icon(content_label), content_label,
     content_caption),
]

cards_html = "".join(
    f"<div style='border:1px solid #E2E8F0;border-top:3px solid {color};border-radius:9px;"
    f"padding:13px 15px;background:#FFFFFF;box-shadow:0 1px 2px rgba(16,24,40,0.04)'>"
    f"<div style='font-size:12px;color:#64748B;font-weight:800;letter-spacing:0.2px'>{name}</div>"
    f"<div style='font-size:18px;font-weight:850;color:#17202A;margin:5px 0 7px'>{icon} {verdict}</div>"
    f"<div style='font-size:12px;color:#667085;line-height:1.45'>{caption}</div>"
    f"</div>"
    for name, color, icon, verdict, caption in signal_cards
)
st.markdown(
    f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:6px 0 4px'>{cards_html}</div>",
    unsafe_allow_html=True,
)

st.divider()

# ──────────────────────────────────────────────
# 상세 탭
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "① 목표가 편차",
    "② 발행 이후 괴리",
    "③ 필요 실적",
    "④ 본문 의견 검증",
    "종합평가",
    "근거·출처",
])

with tab1:
    st.subheader("목표가가 얼마나 높은가")
    render_axis_brief(
        "이 리포트 목표가가 시장 평균이나 다른 증권사보다 유난히 높은가",
        "증권사 목표가 평균, 업로드 리포트별 목표가·투자의견, 목표가 평균 대비 편차",
        "목표가가 평균권인지, 공격적인지, 보수적인지 구분합니다.",
    )

    cons = A.get("consensus") or {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("검증 리포트 목표가", f"{rep['target_price']:,}원")
    with col2:
        st.metric("증권사 목표가 평균", f"{dist['mean']:,.0f}원")
    with col3:
        st.metric("평균 대비", f"{dist['vs_median_pct']:+.1f}%",
                  delta=dist["position"], delta_color="off")

    # 목표가가 평균 대비 어디 있는지 한눈에 보여주는 위치 막대 (-30%~+30% 범위로 정규화)
    dev = dist["vs_median_pct"]
    marker_pos = max(0.0, min(100.0, 50.0 + dev / 30.0 * 50.0))
    if dev > 12:
        marker_color, zone_text = COLOR["logic"], "평균보다 공격적"
    elif dev < -12:
        marker_color, zone_text = COLOR["space"], "평균보다 보수적"
    else:
        marker_color, zone_text = COLOR["grade_a"], "평균권"
    st.markdown(
        f"<div style='margin:10px 0 4px'>"
        f"<div style='position:relative;height:34px;border-radius:8px;"
        f"background:linear-gradient(90deg,#DCEBFB 0%,#EAF6EE 50%,#FBE4E1 100%);"
        f"border:1px solid #E2E8F0'>"
        f"<div style='position:absolute;left:50%;top:0;bottom:0;width:2px;background:#94A3B8'></div>"
        f"<div style='position:absolute;left:50%;top:-18px;transform:translateX(-50%);"
        f"font-size:11px;color:#64748B;font-weight:700'>평균</div>"
        f"<div style='position:absolute;left:{marker_pos}%;top:50%;transform:translate(-50%,-50%);"
        f"width:16px;height:16px;border-radius:50%;background:{marker_color};"
        f"border:2.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.25)'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;font-size:11px;color:#94A3B8;margin-top:3px'>"
        f"<span>보수적 −30%</span><span style='color:{marker_color};font-weight:800'>{zone_text} · {dev:+.1f}%</span><span>공격적 +30%</span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    render_detail_block(
        "해석",
        "목표가가 시장 평균보다 높다는 것만으로 틀렸다고 보지는 않습니다. 다만 평균에서 멀수록 그만큼 더 강한 근거가 필요합니다.",
        f"반영: {V['axes']['space']['reason']}",
        f"평균 대비 {dist['vs_median_pct']:+.1f}%",
    )
    st.markdown("---")
    st.markdown(
        f"**판정: {dist['position']}** "
        f"(z={dist['z']}, 표준편차는 목표가 평균의 {int(0.12*100)}%로 추정)"
    )
    if cons:
        st.caption(
            f"📊 네이버 금융 목표가 평균 · 투자의견 {cons.get('opinion_label','')} "
            f"· 기준일 {cons.get('create_date','')}"
        )
    st.info(
        "업로드한 PDF에서 목표가와 투자의견을 읽어 비교합니다. "
        "자동 인식이 안 된 리포트는 표 계산에서 제외하고, 왼쪽에서 직접 입력하면 다시 반영합니다."
    )
    render_report_batch_distribution(A)

with tab2:
    st.subheader("발행 이후 현실과 얼마나 달라졌나")
    render_axis_brief(
        "리포트 발행 뒤 주가·수급·공시가 리포트 방향과 어긋났는가",
        "리포트별 발행일 주가, 현재 주가, 발행 후 수익률, 지분공시, DART 공시",
        "시간이 지나 전제가 낡았는지, 어떤 리포트가 현재 흐름과 가장 덜 어긋나는지 봅니다.",
    )

    batch_tl = A.get("report_batch_timeline") or {}
    batch_rows = batch_tl.get("rows") or []
    batch_summary = batch_tl.get("summary") or {}
    if batch_rows:
        st.markdown("#### 업로드 리포트별 발행 이후 괴리")
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            st.metric("평균 발행일 주가", _fmt_won(batch_summary.get("avg_price_at_pub")))
        with b2:
            st.metric("현재 주가", _fmt_won(co["current_price"]))
        with b3:
            st.metric("평균 발행 후 수익률", _fmt_pct(batch_summary.get("avg_realized")))
        with b4:
            best_label = batch_summary.get("best_broker") or "계산 필요"
            best_score = batch_summary.get("best_score")
            st.metric("가장 덜 어긋난 리포트", f"{best_label}", f"{best_score:.0f}점" if best_score is not None else None)
        if batch_summary.get("best_broker"):
            st.caption(
                f"{batch_summary['best_broker']} 리포트는 현재 데이터와의 괴리가 가장 작게 계산됐습니다. "
                f"근거: {batch_summary.get('best_reason', '')}"
            )
        st.dataframe(pd.DataFrame(batch_rows), width="stretch", hide_index=True)
        st.caption(
            "발행일 주가를 찾지 못한 리포트는 발행 후 수익률 계산에서 제외됩니다. "
            "목표가를 읽지 못한 리포트는 남은 여력과 현실 부합도 계산에서 제외됩니다."
        )

    st.markdown("#### 종합 점수 기준")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("발행일 주가", f"{tl['price_at_pub']:,}원")
        st.metric("현재 주가", f"{co['current_price']:,}원")
        st.metric("변화율", f"{(co['current_price']/tl['price_at_pub']-1)*100:.1f}%")

    with col2:
        st.metric("목표가까지 남은 여력", f"{(rep['target_price']/co['current_price']-1)*100:.1f}%")
        st.metric("발행 후 경과일", f"{tl['elapsed']}일")
        st.metric("여력 소진율", f"{tl['soak_pct']}%")

    price_basis = ""
    if A.get("price_action", {}).get("price_frame"):
        pf = A["price_action"]["price_frame"]
        price_basis = (
            f"3개월 수익률 {pf.get('ret_3m'):+.1f}% / "
            f"52주 고점 대비 {pf.get('drawdown'):+.1f}%"
        ) if pf.get("ret_3m") is not None and pf.get("drawdown") is not None else ""
    render_detail_block(
        "해석",
        "리포트는 발행일 정보로 쓰인 문서입니다. 이후 가격 차이는 실적 훼손, 기대감 선반영, 수급 부담, 성장 이벤트 지연으로 나눠 신뢰도에 반영합니다.",
        f"반영: {V['axes']['time']['reason']}",
        price_basis or tl.get("supply_basis") or f"발행 {tl['elapsed']}일",
    )
    st.markdown("---")
    if tl.get("supply_gap"):
        st.warning(tl.get("supply_read") or "매수 의견 이후 수급이 반대로 움직였습니다.")
    price_action = A.get("price_action") or {}
    price_rows = build_price_gap_read(price_action)
    if price_action:
        st.markdown("#### 주가 괴리 해석")
        st.markdown(f"**{price_action.get('verdict', '확인 구간')}**")
        if price_action.get("thesis"):
            st.caption(price_action["thesis"])
        for row in price_rows[:3]:
            st.markdown(
                f"**{row.get('driver')} · {row.get('weight')}**  \n"
                f"{row.get('reading')}  \n"
                f"<span style='color:#667085;font-size:13px'>근거: {row.get('evidence')}</span>",
                unsafe_allow_html=True,
            )
    if tl.get("events"):
        st.markdown("#### 발행 이후 확인된 변화")
        for item in tl.get("events", [])[:5]:
            date = item.get("date", "")
            event_type = item.get("type", "")
            detail = item.get("detail", "")
            summary = item.get("summary") or summarize_post_event(item)
            impact = item.get("impact") or explain_post_event_impact(item)
            takeaway = item.get("takeaway") or explain_post_event_takeaway(item, rep)
            tone = takeaway.get("tone", "확인")
            url = item.get("url")
            link_html = (
                f"<div style='font-size:12px;margin-top:2px'>"
                f"<a href='{html.escape(url)}' target='_blank' style='color:#185FA5;text-decoration:none'>원문 공시 보기</a>"
                f"</div>"
                if url else ""
            )
            takeaway_html = (
                f"<div style='font-size:12px;color:#334155;line-height:1.55;margin-top:6px'>"
                f"<b>확인된 변화 · {html.escape(tone)}</b><br>{html.escape(takeaway.get('confirmed', ''))}"
                f"</div>"
                f"<div style='font-size:12px;color:#475569;line-height:1.55;margin-top:3px'>"
                f"<b>리포트와의 관계</b><br>{html.escape(takeaway.get('relation', ''))}"
                f"</div>"
            )
            st.markdown(
                f"""
                <div style="padding:8px 0;border-bottom:1px solid #E5EAF0">
                  <div style="font-size:14px;color:#17202A;font-weight:800">{html.escape(date)} {html.escape(event_type)} · {html.escape(detail)}</div>
                  {link_html}
                  <div style="font-size:12px;color:#667085;line-height:1.5;margin-top:4px">{html.escape(summary)}</div>
                  {takeaway_html}
                  <div style="font-size:12px;color:#3D4A5C;line-height:1.5;margin-top:4px;font-weight:650">{html.escape(impact)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if not tl.get("supply_gap") and not tl.get("events"):
        st.info("발행 이후 신뢰도를 크게 흔드는 수급·공시 변화는 제한적으로 보입니다.")

with tab3:
    st.subheader("목표가에 필요한 실적이 현실적인가")
    render_axis_brief(
        "목표가가 성립하려면 EPS가 얼마나 좋아져야 하는가",
        "DART 분기 재무, 현재 EPS, 목표가 역산 EPS, 과거 EPS 성장률 평균·중앙값",
        "목표가가 과거 실적 범위 안에서 설명되는지, 무리한 성장률을 요구하는지 판단합니다.",
    )

    if rev.get("verdict") == "확인 필요":
        st.info(rev.get("limited_reason") or "필요 실적 계산에 필요한 데이터가 부족해 이 항목은 점수에서 제외했습니다.")
        st.caption("DART 재무 자체는 유지하고, 목표가 편차·발행 이후 괴리·본문 의견 검증은 계속 계산합니다.")
    else:
        if rev.get("limited"):
            st.caption(f"보조 계산 기준: {rev.get('method', '최근 분기 기준')} · {rev.get('limited_reason', '')}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("현재 주당이익", f"{rev['current_eps']:,.0f}원")
            st.metric("필요 주당이익", f"{rev.get('need_eps', 0):,.0f}원")
            st.metric("필요 성장률", f"{rev['need_growth']:+.1f}%")

        with col2:
            st.metric("과거 평균 성장", f"{rev['avg_growth']:+.1f}%")
            st.metric("과거 중앙값 성장", f"{rev['median_growth']:+.1f}%")
            st.metric("변동성 계수(CV)", f"{rev.get('cv', 0):.2f}")

        render_detail_block(
            "해석",
            "목표가는 결국 앞으로 벌 이익에 대한 숫자입니다. 필요한 EPS 성장률이 과거 보통 수준보다 높으면 목표가 신뢰도는 낮아집니다.",
            f"반영: {V['axes']['logic']['reason']}",
            f"필요 {rev['need_growth']:+.1f}% / 중앙값 {rev['median_growth']:+.1f}%",
        )
    st.subheader("과거 성장률 추이")
    growth_title, growth_body = explain_growth_history(rev)
    st.markdown(f"**{growth_title}**")
    st.caption(growth_body)

    growth_history = rev.get("growth_history", [])
    growth_labels = rev.get("growth_labels") or [f"구간 {idx + 1}" for idx in range(len(growth_history))]
    growth_df = pd.DataFrame({
        "구간": growth_labels[:len(growth_history)],
        "성장률": growth_history,
    })

    col1, col2 = st.columns([2, 1])
    with col1:
        if growth_df.empty:
            st.info("과거 성장률 데이터가 부족합니다.")
        else:
            st.line_chart(growth_df.set_index("구간"), height=250)
    with col2:
        avg_val = rev["avg_growth"]
        median_val = rev["median_growth"]
        st.metric("평균", f"{avg_val:+.1f}%")
        st.metric("중앙값", f"{median_val:+.1f}%")
        if rev.get("verdict") == "확인 필요":
            st.metric("필요값", "계산 제외")
        else:
            st.metric("필요값", f"{rev['need_growth']:+.1f}%")

with tab4:
    st.subheader("리포트 본문 의견이 실제 데이터와 맞는가")
    render_axis_brief(
        "리포트 본문에서 좋게 본 부분이 실제 숫자로도 확인되는가",
        "PDF 본문 문장, 리포트별 강조 논점, DART 재무, 발행 후 주가·수급·공시",
        "공통으로 맞는 내용, 해석이 갈리는 부분, 낙관적으로 볼 수 있는 부분을 나눕니다.",
    )
    render_detail_block(
        "해석",
        "목표가 숫자만 맞춰보면 리포트 안의 핵심 의견을 놓칠 수 있습니다. 그래서 PDF 본문에서 반복되는 논점을 뽑고, 증권사별 해석 차이와 실제 데이터의 확인 정도를 따로 봅니다.",
        f"반영: {content_assessment.get('reason', '본문 의견 검증 미반영')}",
        f"객관분석 -{content_assessment.get('penalty', 0)}점",
    )
    render_report_briefing(content_briefing)

    theme_rows = content_view.get("theme_rows", [])
    claim_rows = content_view.get("claim_rows", [])
    if not theme_rows:
        st.info("업로드한 PDF 본문을 읽으면 리포트별 공통 의견과 차이가 이곳에 정리됩니다.")
    else:
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("분석 논점", f"{len(theme_rows)}개")
        with m2:
            st.metric("의견 차이", f"{content_assessment.get('divergent_count', 0)}개")
        with m3:
            penalty = content_assessment.get("penalty", 0)
            st.metric("신뢰도 반영", "차감 없음" if not penalty else f"-{penalty}점")
        if content_view.get("summary"):
            st.info(content_view["summary"])
        display_rows = []
        for row in theme_rows:
            display_rows.append({
                "논점": row.get("논점"),
                "언급": row.get("언급 리포트"),
                "리포트별 방향": row.get("리포트 간 차이"),
                "실제 데이터 대조": row.get("FinSight 대조"),
                "판단": row.get("판정"),
            })
        st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)
        if claim_rows:
            with st.expander("리포트별 본문 근거 보기"):
                st.dataframe(pd.DataFrame(claim_rows), width="stretch", hide_index=True)

with tab5:
    col_title, col_btn = st.columns([0.85, 0.15])
    with col_title:
        st.subheader("종합평가")
    with col_btn:
        st.download_button(
            "📥 HTML",
            html_report.encode("utf-8"),
            file_name=f"FinSight_{co['name']}_Report_Check.html",
            mime="text/html",
            width="stretch",
        )
    render_axis_brief(
        "목표가와 투자의견을 그대로 받아들여도 되는가",
        "목표가 편차, 발행 이후 괴리, 필요 실적, 본문 의견 검증, 객관분석 차감",
        "신뢰도 점수와 리포트별 현실 부합도를 함께 정리합니다.",
    )
    render_detail_block(
        "해석",
        "투자의견을 그대로 받아들이지 않고 DART 재무, 발행 이후 괴리, 목표가 평균, 필요 실적, 리포트 본문 의견을 함께 대조한 결과입니다.",
        f"최종 {V['total']}점 · {V['grade']}등급",
        f"기초 {V.get('base_total', V['total'])}점 / 객관분석 -{V.get('alignment', {}).get('penalty', 0)}점",
    )
    st.markdown(f"### {V['headline']}")
    st.markdown(V["guide"])
    batch_conclusion = report_batch_conclusion(A)
    if batch_conclusion:
        st.markdown("#### 리포트 간 비교 결론")
        st.info(batch_conclusion)
    if content_briefing.get("headline"):
        st.markdown("#### 리포트에서 가져갈 핵심")
        st.markdown(content_briefing["headline"])
    if content_view.get("summary"):
        st.markdown("#### 본문 의견 검증 결론")
        st.info(content_view["summary"])
    alignment = V.get("alignment", {})
    if alignment:
        st.markdown("#### 신뢰도에 반영한 객관분석")
        for idx, factor in enumerate(alignment.get("factors", []), start=1):
            points = factor.get("points", 0)
            point_text = f" · 신뢰도 -{points}점" if points else ""
            st.markdown(
                f"**{idx}. {factor.get('title')}**{point_text}  \n"
                f"{factor.get('reason')}  \n"
                f":gray[근거: {factor.get('evidence')}]"
            )

with tab6:
    st.subheader("점수 산정 근거")
    render_axis_brief(
        "점수와 결론이 어떤 숫자와 출처에서 나왔는가",
        "DART 재무·공시, KRX 주가·수급, 증권사 목표가 평균, 업로드 PDF, 뉴스·외부 정황",
        "주장이 아니라 어떤 데이터가 어떤 점수에 연결됐는지 확인합니다.",
    )
    render_detail_block(
        "판단 기준",
        "이 탭은 결론을 뒷받침한 숫자와 출처를 그대로 남기는 감사표입니다. 목표가, 발행일, 현재가, 증권사 목표가 평균, PDF 본문, DART 재무, 수급 변화가 각각 어떤 점수와 차감으로 연결됐는지 확인할 수 있습니다.",
        "주장이 아니라 확인된 팩트와 산식으로 신뢰도 점수를 만들었습니다.",
        "목표가 편차 30점 / 발행 이후 괴리 30점 / 필요 실적 40점 / 본문 의견·객관분석 추가 차감",
    )
    dart_health = build_dart_health_summary(A)
    health_color = "#0F6E56" if "연결" in dart_health.get("title", "") and not A.get("is_demo_financials") else "#BA7517"
    st.markdown(
        f"""
        <div style="margin:8px 0 14px;padding:12px 14px;border:1px solid #DCE2E8;
                    border-left:4px solid {health_color};border-radius:8px;background:#FFFFFF">
          <div style="font-size:14px;font-weight:850;color:#17202A">{html.escape(dart_health.get('title', 'DART 상태'))}</div>
          <div style="font-size:13px;color:#334155;line-height:1.55;margin-top:4px">
            {html.escape(dart_health.get('status', ''))}<br>
            재무: {html.escape(dart_health.get('financials', ''))}<br>
            공시: {html.escape(dart_health.get('disclosures', ''))}<br>
            핵심 누락: {html.escape(dart_health.get('missing', ''))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    formula = score_formula(A)
    st.markdown(f"**{formula['text']}**")

    st.markdown("#### 배점 기준")
    st.dataframe(pd.DataFrame(build_scoring_rulebook(A)), width="stretch", hide_index=True)

    st.markdown("#### 점수 계산")
    st.dataframe(pd.DataFrame(build_score_audit(A)), width="stretch", hide_index=True)

    st.markdown("#### 객관분석·발행 후 업데이트")
    st.dataframe(pd.DataFrame(build_update_audit(A)), width="stretch", hide_index=True)

    st.markdown("#### 원자료 연결")
    st.dataframe(pd.DataFrame(build_source_audit(A)), width="stretch", hide_index=True)

    # 발행 후 공시·외부 정황을 expander로 분류해서 보기 좋게 표시
    context = A.get("context") or {}
    disclosures = context.get("disclosures") or []
    news = context.get("news") or []
    blogs = context.get("blogs") or []

    def render_source_item(item: dict, item_type: str) -> None:
        """공시·뉴스·블로그 항목을 간결한 카드 형식으로 렌더링."""
        url = item.get("url") or ""
        title = item.get("title") or ""
        source = item.get("source") or ""
        description = item.get("description") or ""
        date_str = item.get("date") or ""

        badge_map = {"disclosure": "📋", "news": "📰", "blog": "📝"}
        badge = badge_map.get(item_type, "📌")

        cols = st.columns([0.03, 0.97])
        with cols[0]:
            st.write(badge)
        with cols[1]:
            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")

            caption_parts = []
            if source:
                caption_parts.append(source)
            if date_str:
                caption_parts.append(date_str[:10])
            if description:
                summary = description[:70].strip()
                if len(description) > 70:
                    summary += "..."
                caption_parts.append(summary)

            if caption_parts:
                st.caption(" · ".join(caption_parts))

    if disclosures:
        with st.expander(f"📋 발행 후 공시 ({len(disclosures)}건)", expanded=False):
            for item in disclosures:
                render_source_item(item, "disclosure")

    if news:
        with st.expander(f"📰 뉴스 ({len(news)}건)", expanded=False):
            for item in news:
                render_source_item(item, "news")

    if blogs:
        with st.expander(f"📝 블로그·해석 ({len(blogs)}건)", expanded=False):
            for item in blogs:
                render_source_item(item, "blog")

    st.markdown("#### 자료 흐름")
    st.dataframe(pd.DataFrame(build_data_source_logic(A)), width="stretch", hide_index=True)

    kpi_snapshot = build_kpi_snapshot(A)
    if not kpi_snapshot.empty:
        st.markdown("#### DART 재무 스냅샷")
        st.dataframe(kpi_snapshot, width="stretch", hide_index=True)
        with st.expander("더 자세히 보고 싶어요 — 매출·마진·현금흐름 흐름 보기"):
            kpis_detail = A.get("kpis")
            st.caption(
                "리포트 목표가가 설득력을 가지려면 매출 성장, 영업이익률, CFO/FCF 흐름이 같은 방향으로 받쳐줘야 합니다. "
                "급변한 분기는 색으로 표시했고, 마우스를 올리면 해당 분기의 숫자와 해석을 볼 수 있습니다."
            )
            if kpis_detail is not None and not kpis_detail.empty:
                st.plotly_chart(annotated_quarter_chart(kpis_detail, A.get("context", {})), width="stretch", key="validator_annotated_quarter_chart")

                chart_frame = kpis_detail.set_index("period")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("##### 전년 대비 성장")
                    growth_cols = [col for col in ["revenue_yoy", "operating_profit_yoy"] if col in chart_frame]
                    if growth_cols:
                        st.line_chart(
                            chart_frame[growth_cols].rename(columns={
                                "revenue_yoy": "매출 YoY",
                                "operating_profit_yoy": "영업이익 YoY",
                            }),
                            height=230,
                        )
                with col_b:
                    st.markdown("##### 마진 구조")
                    margin_cols = [col for col in ["opm", "cogs_ratio", "sga_ratio"] if col in chart_frame]
                    if margin_cols:
                        st.line_chart(
                            chart_frame[margin_cols].rename(columns={
                                "opm": "OPM",
                                "cogs_ratio": "원가율",
                                "sga_ratio": "판관비율",
                            }),
                            height=230,
                        )

                st.markdown("##### 현금흐름 전환")
                cash_cols = [col for col in ["cfo_margin", "fcf_margin"] if col in chart_frame]
                if cash_cols:
                    st.line_chart(
                        chart_frame[cash_cols].rename(columns={
                            "cfo_margin": "CFO 마진",
                            "fcf_margin": "FCF(잉여현금흐름) 마진",
                        }),
                        height=230,
                    )

                st.markdown("##### 분기별 원자료")
                st.dataframe(build_tracker_table(kpis_detail), width="stretch", height=360)
