"""FinSight — 리포트 신뢰도 검증.

증권사 리포트의 목표가와 투자의견을 DART 재무·공시, KRX 주가·수급,
증권사 목표가 평균, 발행 이후 공시·뉴스·지분 변동으로 다시 대조해
신뢰도 점수와 종합 해석 보고서를 제공한다.
  ① 분포 위치: 다른 증권사와 비교해 목표가가 어디 위치하는가
  ② 발행 후 변화: 발행 후 기업 상황과 주가가 바뀌었는가
  ③ 가정 검증: 목표가를 위해 필요한 성장률이 현실적인가
"""
from __future__ import annotations

import sys
import runpy
import re
from pathlib import Path
from io import BytesIO
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.kpi_engine import calculate_quarterly_kpis
from core.diagnostics import (
    calculate_multiple_valuation,
    build_valuation_range,
)
from report_validator.finsight_modules import (
    reverse_engineer_target,
    aggregate_opinions,
    locate_in_distribution,
    locate_vs_consensus,
)
from core.mode_views import build_tracker_table, build_peer_benchmark
from core import data_collector as dc
from analyst_workbench.interpretation import interpret_price_action
from report_validator.timeline_module import build_post_publish_timeline, fetch_foreign_net, fetch_price_at_date
from report_validator.scoring_module import build_report_verdict
from report_validator.report_assessor import build_alignment_assessment, apply_alignment_to_verdict
from report_validator.retail_report import generate_retail_html_report, generate_retail_pdf_report
from report_validator.evidence_audit import (
    build_data_source_logic,
    build_kpi_snapshot,
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

    ③축 역산까지 성공해야 실데이터로 인정한다 (완전연도 EPS 부족 등은 폴백).
    """
    try:
        info = dc.resolve_company(company_name)
        if not info or not info.get("stock_code"):
            return None
        fin = dc.get_quarterly_financials(company_name, quarters=24)
        if fin is None or len(fin) < 12 or "period" not in fin.columns:
            return None

        code = info["stock_code"]
        price = dc.get_current_price(code)
        last = fin["period"].iloc[-1]            # 예: '2026 1Q'
        yr = int(last.split()[0])
        q = int(last.split()[1].replace("Q", ""))
        shares = dc.get_share_snapshot(company_name, yr, q).get("shares_outstanding")
        if not price or not shares:
            return None

        # ③축 역산이 실제로 가능한지 검증 (완전연도 EPS 3개 이상)
        kpis = calculate_quarterly_kpis(fin)
        reverse_engineer_target(
            target_price=price * 1.2,  # 검증용 임의 목표가
            kpis=kpis,
            shares_outstanding=shares,
            current_price=price,
        )

        return {
            "company_name": info["company"],
            "stock_code": code,
            "financials": fin,
            "current_price": float(price),
            "shares_outstanding": float(shares),
        }
    except Exception:
        return None


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


def extract_report_pdf_text(file_bytes: bytes, max_pages: int = 6) -> tuple[str, str]:
    """Best-effort PDF text extraction for uploaded broker reports."""
    if not file_bytes:
        return "", "파일이 비어 있습니다."
    readers = []
    try:
        from pypdf import PdfReader
        readers.append(PdfReader)
    except Exception:
        pass
    try:
        from PyPDF2 import PdfReader
        readers.append(PdfReader)
    except Exception:
        pass
    if not readers:
        return "", "PDF 텍스트 추출 라이브러리가 없어 파일명만 반영합니다."
    try:
        reader = readers[0](BytesIO(file_bytes))
        texts = []
        for page in list(reader.pages)[:max_pages]:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(part.strip() for part in texts if part.strip())
        if not text:
            return "", "PDF에서 텍스트를 읽지 못했습니다. 스캔 PDF일 수 있습니다."
        return text[:12000], f"PDF 본문 {min(len(reader.pages), max_pages)}페이지 텍스트 일부를 읽었습니다."
    except Exception as exc:
        return "", f"PDF 텍스트 추출 실패: {str(exc)[:80]}"


BROKER_HINTS = [
    "삼성증권", "하나증권", "NH투자증권", "KB증권", "신한투자증권", "미래에셋증권",
    "한국투자증권", "대신증권", "키움증권", "메리츠증권", "유안타증권", "한화투자증권",
    "현대차증권", "유진투자증권", "교보증권", "신영증권", "DB금융투자", "SK증권",
    "IBK투자증권", "DS투자증권", "다올투자증권", "흥국증권", "LS증권",
]


def _clean_report_name(file_name: str) -> str:
    return Path(file_name or "업로드 리포트").stem.replace("_", " ").replace("-", " ").strip()


def report_identity(item: dict) -> str:
    broker = item.get("broker") or "증권사 추출 필요"
    date = item.get("pub_date") or "발행일 추출 필요"
    title = item.get("title") or _clean_report_name(item.get("file_name", "업로드 리포트"))
    return f"{broker} · {date} · {title}"


def reports_missing_target(reports: list[dict]) -> list[dict]:
    return [item for item in reports if not item.get("target_price")]


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
        value = float(str(raw).replace(",", "").strip())
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
    candidates: list[dict] = []
    patterns = [
        r"(목표\s*(?:주가|가|가격)|적정\s*주가|Target\s*Price|TP|Fair\s*Value)\s*(?:\([^)]*\))?\s*[:：]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,8}|[0-9]+(?:\.[0-9]+)?)\s*(원|만원|천원|KRW)?",
        r"(목표\s*(?:주가|가|가격)|적정\s*주가)\s*(?:\([^)]*\))?\s*[:：]?\s*\n?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,8}|[0-9]+(?:\.[0-9]+)?)\s*(원|만원|천원)?",
        r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,8}|[0-9]+(?:\.[0-9]+)?)\s*(원|만원|천원)?\s*(?:\([^)]*\))?\s*(목표\s*(?:주가|가|가격)|Target\s*Price|TP)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            groups = match.groups()
            if len(groups) >= 3 and re.search(r"목표|Target|TP|Fair", str(groups[0]), re.IGNORECASE):
                raw, unit = groups[1], groups[2] or ""
            else:
                raw, unit = groups[0], groups[1] or ""
            value = _money_to_won(raw, unit)
            if value is None or value < 1000 or value > 10000000:
                continue
            snippet = _target_evidence_snippet(text, match.start(), match.end())
            bad_context = re.search(r"(현재\s*주가|현재가|종가|시가총액|상승\s*여력|Upside)", snippet, re.IGNORECASE)
            old_context = re.search(r"(기존|종전|직전|이전)\s*(목표|TP|Target)", snippet, re.IGNORECASE)
            score = match.start()
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
    lowered = text.lower()
    if re.search(r"(투자의견|opinion|rating).{0,18}(매수|buy|outperform)", lowered, re.IGNORECASE):
        return "매수"
    if re.search(r"(투자의견|opinion|rating).{0,18}(중립|hold|neutral|보유)", lowered, re.IGNORECASE):
        return "중립"
    if re.search(r"(투자의견|opinion|rating).{0,18}(매도|sell|underperform)", lowered, re.IGNORECASE):
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
    for item in reports:
        target = item.get("target_price")
        gap = None
        upside = None
        if target and mean_target:
            gap = (target / mean_target - 1) * 100
        verdict = "목표가 추출 필요"
        if gap is not None:
            if gap >= 15:
                verdict = "평균보다 공격적"
            elif gap <= -15:
                verdict = "평균보다 보수적"
            else:
                verdict = "평균권"
        rows.append({
            "리포트": item.get("title") or item.get("file_name") or "업로드 리포트",
            "증권사": item.get("broker") or "추출 필요",
            "발행일": item.get("pub_date") or "추출 필요",
            "투자의견": item.get("opinion") or "추출 필요",
            "목표가": f"{target:,.0f}원" if target else "추출 필요",
            "평균 대비": f"{gap:+.1f}%" if gap is not None else "N/A",
            "판정": verdict,
            "목표가 근거": item.get("target_evidence") or "원문에서 목표가 문장을 찾지 못했습니다.",
        })
    return rows


def report_batch_stats(reports: list[dict]) -> dict:
    targets = sorted(int(item["target_price"]) for item in reports if item.get("target_price"))
    opinions: dict[str, int] = {}
    for item in reports:
        opinion = item.get("opinion") or "추출 필요"
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
        if majority_opinion == "추출 필요":
            majority_opinion = ""
    return {
        "count": len(reports),
        "target_count": len(targets),
        "min_target": targets[0] if targets else None,
        "max_target": targets[-1] if targets else None,
        "median_target": median,
        "mean_target": int(sum(targets) / len(targets)) if targets else None,
        "latest_date": max(dates).isoformat() if dates else "",
        "opinions": opinions,
        "majority_opinion": majority_opinion,
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
    missing = reports_missing_target(reports)
    if missing:
        parts.append(f"다만 목표가를 읽지 못한 {len(missing)}개 리포트는 목표가 기반 계산에서 제외했습니다.")
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
        st.metric("비교 리포트", f"{stats['count']}개")
    with d2:
        st.metric("목표가 중앙값", f"{stats['median_target']:,.0f}원" if stats.get("median_target") else "추출 필요")
    with d3:
        target_range = "추출 필요"
        if stats.get("min_target") and stats.get("max_target"):
            target_range = f"{stats['min_target']:,.0f}~{stats['max_target']:,.0f}원"
        st.metric("목표가 범위", target_range)
    with d4:
        opinion_text = " · ".join(f"{key} {value}" for key, value in stats.get("opinions", {}).items()) or "추출 필요"
        st.metric("투자의견 분포", opinion_text)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
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
        st.metric("업로드 리포트", f"{stats['count']}개")
    with c2:
        target_range = "N/A"
        if stats["min_target"] and stats["max_target"]:
            target_range = f"{stats['min_target']:,.0f}~{stats['max_target']:,.0f}원"
        st.metric("목표가 범위", target_range)
    with c3:
        st.metric("중앙 목표가", f"{stats['median_target']:,.0f}원" if stats["median_target"] else "추출 필요")
    with c4:
        opinion_text = " · ".join(f"{key} {value}" for key, value in stats["opinions"].items()) or "추출 필요"
        st.metric("투자의견 분포", opinion_text)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if stats["target_count"] < stats["count"]:
        missing = reports_missing_target(reports)
        missing_names = " / ".join(report_identity(item) for item in missing[:4])
        suffix = f" 외 {len(missing) - 4}개" if len(missing) > 4 else ""
        st.warning(
            f"목표가를 자동으로 읽지 못한 리포트: {missing_names}{suffix}. "
            "이 리포트는 중앙 목표가 계산과 현실 부합도 점수에서 제외했습니다. "
            "반영하려면 왼쪽 사이드바의 '목표가 직접 입력'에 원문 목표가를 입력하세요."
        )


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


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
        return None, "목표가 또는 발행일 주가 추출 필요"
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
    for item in reports:
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
            "증권사": item.get("broker") or "추출 필요",
            "발행일": pub_date or "추출 필요",
            "투자의견": item.get("opinion") or "추출 필요",
            "목표가": _fmt_won(target),
            "발행일 주가": _fmt_won(price_at_pub),
            "발행 후 주가 변화": _fmt_pct(realized),
            "발행 당시 상승여력": _fmt_pct(upside_at_pub),
            "현재 남은 여력": _fmt_pct(remaining),
            "목표가 평균 대비": _fmt_pct(dist_gap),
            "현실 부합도": f"{score:.0f}점" if score is not None else "추출 필요",
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


def build_post_report_events(context: dict, report_date: str) -> list[dict]:
    events: list[dict] = []
    for item in (context or {}).get("disclosures", [])[:12]:
        date = _normalize_event_date(item.get("date"))
        if report_date and date and date < report_date:
            continue
        events.append({
            "date": date,
            "type": "공시",
            "detail": item.get("title", ""),
            "summary": summarize_post_event(item),
            "url": item.get("url", ""),
        })
    for item in (context or {}).get("ownership", [])[:8]:
        date = _normalize_event_date(item.get("date"))
        if report_date and date and date < report_date:
            continue
        change = item.get("ratio_change")
        if change is None:
            continue
        events.append({
            "date": date,
            "type": "지분공시",
            "detail": f"{item.get('reporter', '주요주주')} 보유비율 {change:+.2f}%p 변동",
            "summary": summarize_post_event(item),
            "url": item.get("url", ""),
        })
    events.sort(key=lambda item: item.get("date") or "", reverse=True)
    return events[:6]


PRODUCT_TITLE = "FinSight — 리포트 신뢰도 검증"
PRODUCT_COPY = (
    "증권사 리포트를 그대로 받아들이기 전에 DART 재무·공시, KRX 주가·수급, "
    "증권사 목표가 평균, 발행 이후 뉴스·지분 변동을 대조합니다. "
    "목표가와 투자의견을 어느 정도 신뢰할 수 있는지 점수화하고, 현재 주가와의 차이를 해석합니다."
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
        grid-template-columns: 1fr 1fr 1fr;
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
              <div class="fs-logic-title">리포트 신뢰도를 세 단계로 확인합니다</div>
              <div class="fs-map">
                <div class="fs-map-step"><b>편차</b><span>목표가가 증권사 목표가 평균 대비 어느 구간에 있는지 확인합니다.</span></div>
                <div class="fs-map-step"><b>발행 후 변화</b><span>발행 이후 가격과 수급이 리포트 전제와 어긋났는지 봅니다.</span></div>
                <div class="fs-map-step"><b>가정</b><span>목표가에 필요한 EPS 성장률을 역산해 과거 실적과 대조합니다.</span></div>
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
          <div class="fs-logic-title">리포트 목표가를 입력하면 편차, 발행 후 변화, 가정을 순서대로 확인합니다</div>
          <div class="fs-logic-copy">
            목표가가 시장 평균보다 얼마나 높은지, 발행 뒤 전제가 바뀌었는지,
            그 가격을 만들려면 실적이 얼마나 좋아져야 하는지를 한 번에 봅니다.
          </div>
          <div class="fs-logic-grid">
            <div class="fs-logic-node"><strong>입력</strong><span>종목, 증권사, 발행일, 목표가, 투자의견을 기준점으로 둡니다.</span></div>
            <div class="fs-logic-node"><strong>편차</strong><span>증권사 목표가 평균 대비 높낮이를 계산해 목표가의 공격성을 봅니다.</span></div>
            <div class="fs-logic-node"><strong>발행 후 변화</strong><span>발행일 이후 주가 변화와 외국인 수급을 함께 확인합니다.</span></div>
            <div class="fs-logic-node"><strong>가정</strong><span>필요 EPS 성장률을 역산하고 과거 평균·중앙값 성장률과 비교합니다.</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_product_header() -> None:
    """Render the validator title with a direct entry to the old analyst app."""
    title_col, mode_col = st.columns([5.0, 1.15])
    with title_col:
        st.markdown(f"## {PRODUCT_TITLE}")
    with mode_col:
        st.markdown("<div style='height:3px'></div>", unsafe_allow_html=True)
        if st.button("Analyst Mode", key="open_analyst_mode", use_container_width=True):
            st.query_params["view"] = "analyst"
            st.rerun()
    st.caption(PRODUCT_COPY)


# ──────────────────────────────────────────────
# 사이드바 — 자동 검색 / 직접 입력
# ──────────────────────────────────────────────
st.sidebar.markdown("### 리포트 신뢰도 검증")
st.sidebar.caption(
    "증권사 리포트의 목표가와 투자의견을 DART 재무·공시, KRX 주가·수급, "
    "발행 이후 뉴스로 대조해 신뢰도를 점수화하고 현재 주가와의 차이를 해석하는 도구"
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
if st.sidebar.button("🔍 검색", use_container_width=True) and company_search:
    st.session_state["search_result"] = search_company_and_consensus(company_search)

search_result = st.session_state.get("search_result")

if search_result and search_result["success"]:
    selected_company = search_result["company_name"]
    consensus = search_result["consensus"]
    stock_code = search_result.get("stock_code")
    mean = consensus["price_target_mean"]
    st.sidebar.success(
        f"**{selected_company}**\n\n"
        f"증권사 목표가 평균 **{mean:,.0f}원**\n\n"
        f"투자의견 {consensus['opinion_label']} · {consensus['create_date']}"
    )

    st.sidebar.markdown("**2️⃣ 검증할 리포트**")
    reports = fetch_research_list(stock_code)
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
            f"{item['date']} · {item['broker']} · {item['title']}"
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
    target_default = int(mean)
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
        if st.sidebar.button("업로드 완료 · 분석에 반영", type="primary", use_container_width=True):
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
                use_container_width=True,
            )

    st.sidebar.markdown("**리포트를 찾지 못하셨나요?**")
    st.sidebar.caption("아래 링크에서 원문을 열어 PDF를 받은 뒤 위 업로드 칸에 넣을 수 있습니다.")
    search_query = quote(f"{selected_company} 증권사 리포트 PDF")
    naver_search_url = f"https://search.naver.com/search.naver?query={search_query}"
    google_search_url = f"https://www.google.com/search?q={search_query}"
    st.sidebar.markdown(
        f"""
        <div style="font-size:12px;line-height:1.65">
          <a href="{research_list_url}" target="_blank">네이버 리서치 목록</a><br>
          <a href="{naver_search_url}" target="_blank">네이버 검색</a> ·
          <a href="{google_search_url}" target="_blank">구글 검색</a>
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
    st.sidebar.warning(search_result["message"])
    st.sidebar.caption("종목코드는 찾았으나 증권사 커버리지가 없을 수 있습니다.")

st.sidebar.divider()
st.sidebar.caption("💡 종목 검색 → 증권사 목표가 평균 확인 → 검증할 목표가 입력")


# ──────────────────────────────────────────────
# 데이터 분석
# ──────────────────────────────────────────────
@st.cache_data(show_spinner="🔬 3축 검증 중...")
def load_analysis(company_name: str, report_date: str, target_price: int,
                  consensus: dict = None, sel_broker: str = "",
                  sel_opinion: str = "매수", report_title: str = "",
                  report_url: str = "", report_pdf_url: str = "",
                  report_file_name: str = "", report_text: str = "",
                  report_extract_status: str = "",
                  report_target_evidence: str = "",
                  report_batch: list[dict] | None = None,
                  cache_version: int = 2):
    """검증할 리포트 목표가 기반 3축 검증.

    실제 DART 재무 수집을 우선하고, 실패 시 농심 데모로 폴백한다.
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
        # 발행일 외국인 순매수(억) — pykrx, 실패 시 None
        foreign_net = fetch_foreign_net(stock_code, report_date)
        # 발행일 주가 — pykrx 자동 조회, 실패 시 현재가로 폴백
        price_at_pub = fetch_price_at_date(stock_code, report_date) or price
        context = fetch_report_context(comp_name, stock_code)
        post_events = build_post_report_events(context, report_date)
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
        foreign_net = D.DEMO_FOREIGN_NET_EOK
        post_events = D.DEMO_POST_EVENTS
        price_at_pub = 420000
        context = {"disclosures": [], "ownership": [], "news": [], "blogs": [], "market": {}, "external_drivers": {}, "errors": []}

    multiples = calculate_multiple_valuation(
        kpis=kpis, shares_outstanding=shares, net_debt=0, current_price=price,
    )
    valuation_range = build_valuation_range(
        dcf=None, multiples=multiples, current_price=price,
    )

    # ③ 가정 검증 (역산)
    reverse = reverse_engineer_target(
        target_price=target_price, kpis=kpis,
        shares_outstanding=shares, current_price=price,
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

    # ① 분포 위치 (네이버 증권사 목표가 평균 대비 위치)
    distribution = locate_vs_consensus(target_price, consensus)

    # ② 발행 후 변화
    timeline = build_post_publish_timeline(
        report={
            "pub_date": report_date,
            "opinion": sel_opinion,
            "target_price": target_price,
            "price_at_pub": price_at_pub,
        },
        current_price=price,
        post_events=post_events,
        foreign_net_fallback=foreign_net,
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
    st.markdown("### 왼쪽에서 종목과 리포트를 선택하세요")
    st.info(PRODUCT_COPY)
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### ① 분포 위치")
        st.markdown("목표가가 다른 증권사와 비교해 어디에 있는가")
    with col2:
        st.markdown("#### ② 발행 후 변화")
        st.markdown("리포트 발행 후 기업·주가 상황이 바뀌었는가")
    with col3:
        st.markdown("#### ③ 가정 검증")
        st.markdown("목표가 달성을 위한 성장률이 현실적인가")

    st.stop()

# 이후는 A가 있을 때만 실행
co, rep, V = A["company"], A["report"], A["verdict"]

# ──────────────────────────────────────────────
# 헤더
# ──────────────────────────────────────────────
render_product_header()
st.markdown(
    f"**{co['name']}** · "
    f"{rep['broker']} · {rep['pub_date']} · "
    f"**{rep['opinion']}** · "
    f"목표가 {rep['target_price']:,}원"
)
if rep.get("title"):
    st.caption(f"검증 리포트: {rep['title']}")
if rep.get("file_name"):
    status_text = f" · {rep.get('extract_status')}" if rep.get("extract_status") else ""
    st.caption(f"업로드 리포트: {rep['file_name']}{status_text}")
if rep.get("batch_count", 0) > 1:
    st.caption(f"업로드 리포트 {rep['batch_count']}개를 비교하고, 종합 점수는 추출된 목표가의 중앙값을 기준으로 계산했습니다.")
if rep.get("pdf_url"):
    st.markdown(f"[원문 PDF 열기]({rep['pdf_url']})")

html_report = generate_retail_html_report(A)
try:
    pdf_report = generate_retail_pdf_report(A)
except Exception:
    pdf_report = None

if A.get("is_demo_financials"):
    st.warning(
        f"⚠️ **{co['name']}의 실제 재무를 DART에서 가져오지 못해 농심 데모 재무로 계산했습니다.** "
        f"(완전연도 EPS 부족 또는 종목 매칭 실패) "
        f"목표가 분포(①축)는 검색값을 반영하지만, 발행 후 변화(②축)·가정 검증(③축)은 데모입니다."
    )
else:
    st.caption(f"✅ 실제 DART 재무 연동 — 현재가 {co['current_price']:,.0f}원 · 발행주식수 {co['shares_outstanding']:,.0f}주")

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
        f"<div style='text-align:center;padding:20px 8px;border:2px solid {gc};"
        f"border-radius:12px;background:{COLOR['bg']}'>"
        f"<div style='font-size:12px;color:#666;font-weight:600'>신뢰도 점수</div>"
        f"<div style='font-size:48px;font-weight:900;color:{gc};line-height:1.0'>{V['total']}</div>"
        f"<div style='font-size:14px;color:#999;margin-bottom:8px'>/100</div>"
        f"<div style='font-size:18px;color:{gc};font-weight:700;margin-bottom:6px'>{V['grade']}등급</div>"
        f"<div style='font-size:14px;color:#666;margin-bottom:10px'>{V['label']}</div>"
        f"<div style='font-size:20px;letter-spacing:2px'>{'★'*V['stars']}{'☆'*(5-V['stars'])}</div>"
        f"<div style='font-size:12px;color:#777;margin-top:10px'>기초 {base_total}점 · 객관분석 -{penalty}점</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

with sc2:
    st.markdown("<div style='height:42px'></div>", unsafe_allow_html=True)
    st.markdown("#### 세부 점수")
    for key, title in [("space", "분포 위치"), ("time", "발행 후 변화"), ("logic", "가정 검증")]:
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

st.markdown("#### 평가 의견")
st.markdown(f"**{V['headline']}**")
st.markdown(V["guide"])

alignment = V.get("alignment", {})
if alignment:
    st.markdown(f"#### FinSight 객관분석 대조 · {alignment.get('label', '')}")
    factor_bits = []
    for factor in alignment.get("factors", [])[:3]:
        points = factor.get("points", 0)
        point_text = f" -{points}점" if points else ""
        factor_bits.append(f"**{factor.get('title')}**{point_text} · {factor.get('evidence')}")
    st.markdown("  \n".join(factor_bits))

st.divider()

# ──────────────────────────────────────────────
# 3축 신호 카드
# ──────────────────────────────────────────────
def signal_icon(verdict: str) -> str:
    if verdict in ("낙관", "과도한 낙관", "확인 필요", "다소 높음"):
        return "🟠"
    if verdict in ("현실적", "양호", "평균권"):
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

dist = A["distribution"]
tl = A["timeline"]
rev = A["reverse"]
if "need_eps" not in rev and rev.get("current_eps") is not None:
    rev["need_eps"] = round(float(rev["current_eps"]) * (1 + float(rev.get("need_growth", 0)) / 100))

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("#### ① 분포 위치")
    st.markdown(f"### {signal_icon(dist['position'])} {dist['position']}")
    st.caption(
        f"목표가 평균 {dist['mean']:,.0f}원 대비 {dist['vs_median_pct']:+.1f}%"
    )

with c2:
    sig = "확인 필요" if tl["supply_gap"] else "양호"
    st.markdown("#### ② 발행 후 변화")
    st.markdown(f"### {signal_icon(sig)} {sig}")
    st.caption(f"발행 {tl['elapsed']}일 경과 · 여력 {tl['soak_pct']}% 소진")

with c3:
    st.markdown("#### ③ 가정 검증")
    st.markdown(f"### {signal_icon(rev['verdict'])} {rev['verdict']}")
    st.caption(
        f"필요 성장률 {rev['need_growth']:+.0f}% · "
        f"과거 중앙값 {rev['median_growth']:+.0f}%"
    )

st.divider()

# ──────────────────────────────────────────────
# 상세 탭
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "① 분포 위치",
    "② 발행 후 변화",
    "③ 가정 검증",
    "종합평가",
    "근거·출처",
])

with tab1:
    st.subheader("증권사 목표가 평균 대비 위치")

    cons = A.get("consensus") or {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("검증 리포트 목표가", f"{rep['target_price']:,}원")
    with col2:
        st.metric("증권사 목표가 평균", f"{dist['mean']:,.0f}원")
    with col3:
        st.metric("평균 대비", f"{dist['vs_median_pct']:+.1f}%",
                  delta=dist["position"], delta_color="off")

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
        "증권사별 개별 목표가는 리포트 PDF에 있어 원문 확인이 필요합니다. "
        "여기서는 증권사 목표가 평균 대비 위치를 먼저 봅니다."
    )
    render_report_batch_distribution(A)

with tab2:
    st.subheader("발행 후 주가 및 수급 변화")

    batch_tl = A.get("report_batch_timeline") or {}
    batch_rows = batch_tl.get("rows") or []
    batch_summary = batch_tl.get("summary") or {}
    if batch_rows:
        st.markdown("#### 업로드 리포트별 발행 후 변화")
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            st.metric("평균 발행일 주가", _fmt_won(batch_summary.get("avg_price_at_pub")))
        with b2:
            st.metric("현재 주가", _fmt_won(co["current_price"]))
        with b3:
            st.metric("평균 발행 후 변화", _fmt_pct(batch_summary.get("avg_realized")))
        with b4:
            best_label = batch_summary.get("best_broker") or "계산 필요"
            best_score = batch_summary.get("best_score")
            st.metric("가장 덜 어긋난 리포트", f"{best_label}", f"{best_score:.0f}점" if best_score is not None else None)
        if batch_summary.get("best_broker"):
            st.caption(
                f"{batch_summary['best_broker']} 리포트는 현재 데이터와의 괴리가 가장 작게 계산됐습니다. "
                f"근거: {batch_summary.get('best_reason', '')}"
            )
        st.dataframe(pd.DataFrame(batch_rows), use_container_width=True, hide_index=True)
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
        price_basis or f"발행 {tl['elapsed']}일 / 외국인 {tl.get('foreign_net', 0):+,}억원",
    )
    st.markdown("---")
    if tl.get("supply_gap"):
        st.warning(f"외국인 순매도: {abs(tl.get('foreign_net', 0)):,}억원 (매수 의견과 괴리)")
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
            url = item.get("url")
            title_html = f"<a href='{url}' target='_blank'>{detail}</a>" if url else detail
            st.markdown(
                f"""
                <div style="padding:8px 0;border-bottom:1px solid #E5EAF0">
                  <div style="font-size:14px;color:#17202A;font-weight:800">{date} 공시 · {title_html}</div>
                  <div style="font-size:12px;color:#667085;line-height:1.5;margin-top:3px">{summary}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if not tl.get("supply_gap") and not tl.get("events"):
        st.info("발행 이후 신뢰도를 크게 흔드는 수급·공시 변화는 제한적으로 보입니다.")

with tab3:
    st.subheader("성장률 역산 검증")

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
        st.metric("필요값", f"{rev['need_growth']:+.1f}%")

with tab4:
    st.subheader("종합평가")
    render_detail_block(
        "해석",
        "투자의견을 그대로 받아들이지 않고 DART 재무, 발행 후 변화, 목표가 평균, 목표가 가정을 함께 대조한 결과입니다.",
        f"최종 {V['total']}점 · {V['grade']}등급",
        f"기초 {V.get('base_total', V['total'])}점 / 객관분석 -{V.get('alignment', {}).get('penalty', 0)}점",
    )
    st.markdown(f"### {V['headline']}")
    st.markdown(V["guide"])
    batch_conclusion = report_batch_conclusion(A)
    if batch_conclusion:
        st.markdown("#### 리포트 간 비교 결론")
        st.info(batch_conclusion)
    batch_rows = build_report_comparison_rows(
        A.get("report_batch", []),
        (A.get("consensus") or {}).get("price_target_mean"),
    )
    if batch_rows:
        st.markdown("#### 업로드 리포트 비교")
        st.dataframe(pd.DataFrame(batch_rows), use_container_width=True, hide_index=True)
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
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "HTML 다운로드",
            html_report.encode("utf-8"),
            file_name=f"FinSight_{co['name']}_Report_Check.html",
            mime="text/html",
            use_container_width=True,
        )
    with dl2:
        if pdf_report:
            st.download_button(
                "PDF 다운로드",
                pdf_report,
                file_name=f"FinSight_{co['name']}_Report_Check.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

with tab5:
    st.subheader("점수 산정 근거")
    render_detail_block(
        "판단 기준",
        "이 탭은 결론을 뒷받침한 숫자와 출처를 그대로 남기는 감사표입니다. 목표가, 발행일, 현재가, 증권사 목표가 평균, DART 재무, 수급 변화가 각각 어떤 점수와 차감으로 연결됐는지 확인할 수 있습니다.",
        "주장이 아니라 확인된 팩트와 산식으로 신뢰도 점수를 만들었습니다.",
        "분포 위치 30점 / 발행 후 변화 30점 / 가정 검증 40점 / FinSight 객관분석 추가 차감",
    )
    formula = score_formula(A)
    st.markdown(f"**{formula['text']}**")
    st.dataframe(pd.DataFrame(build_score_audit(A)), use_container_width=True, hide_index=True)

    st.markdown("#### 객관분석·발행 후 업데이트")
    st.dataframe(pd.DataFrame(build_update_audit(A)), use_container_width=True, hide_index=True)

    st.markdown("#### 원자료 연결")
    st.dataframe(pd.DataFrame(build_source_audit(A)), use_container_width=True, hide_index=True)

    st.markdown("#### 데이터 소스 사용 이유")
    st.dataframe(pd.DataFrame(build_data_source_logic(A)), use_container_width=True, hide_index=True)

    kpi_snapshot = build_kpi_snapshot(A)
    if not kpi_snapshot.empty:
        st.markdown("#### DART 재무 스냅샷")
        st.dataframe(kpi_snapshot, use_container_width=True, hide_index=True)
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
