"""증권사 컨센서스 자동 수집 — 네이버 금융 모바일 API 기반.

현실 점검 결과:
  - 증권사별 개별 목표가 리스트는 리포트 PDF 안에만 있어 안정적 크롤링 불가
    (네이버·한경 목록 페이지 모두 목표가 컬럼 없음)
  - 네이버 컨센서스 '평균 목표주가/투자의견'은 공개 API로 안정적으로 수집 가능

따라서 ①축은 '검증 목표가 vs 시장 컨센서스 평균'으로 판단한다.
"""
from __future__ import annotations

import sys
import contextlib
import io
import re
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from bs4 import BeautifulSoup

from core import data_collector as dc

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    )
}
_NAVER_API = "https://m.stock.naver.com/api/stock/{code}/integration"
_NAVER_RESEARCH = "https://finance.naver.com/research/company_list.naver"

_COMMON_LISTED_COMPANIES = {
    "삼성전자": ("삼성전자", "005930"),
    "sk하이닉스": ("SK하이닉스", "000660"),
    "에스케이하이닉스": ("SK하이닉스", "000660"),
    "네이버": ("NAVER", "035420"),
    "naver": ("NAVER", "035420"),
    "카카오": ("카카오", "035720"),
    "kakao": ("카카오", "035720"),
    "카카오뱅크": ("카카오뱅크", "323410"),
    "카카오페이": ("카카오페이", "377300"),
    "농심": ("농심", "004370"),
    "에이피알": ("에이피알", "278470"),
    "apr": ("에이피알", "278470"),
    "현대차": ("현대자동차", "005380"),
    "현대자동차": ("현대자동차", "005380"),
    "기아": ("기아", "000270"),
    "lg전자": ("LG전자", "066570"),
    "엘지전자": ("LG전자", "066570"),
    "lg화학": ("LG화학", "051910"),
    "lg에너지솔루션": ("LG에너지솔루션", "373220"),
    "삼성sdi": ("삼성SDI", "006400"),
    "삼성바이오로직스": ("삼성바이오로직스", "207940"),
    "셀트리온": ("셀트리온", "068270"),
    "포스코홀딩스": ("POSCO홀딩스", "005490"),
    "posco홀딩스": ("POSCO홀딩스", "005490"),
    "kb금융": ("KB금융", "105560"),
    "신한지주": ("신한지주", "055550"),
    "현대모비스": ("현대모비스", "012330"),
}


def _normalize_company_query(value: str) -> str:
    raw = re.sub(r"\s+", "", str(value or "")).lower()
    raw = raw.replace("(주)", "").replace("주식회사", "")
    aliases = {
        "엘지": "lg",
        "에스케이": "sk",
        "케이비": "kb",
        "포스코": "posco",
    }
    for src, dst in aliases.items():
        raw = raw.replace(src, dst)
    return raw


def _resolve_company_for_search(company_name: str) -> tuple[str, str, str]:
    """Resolve listed company name for the search step without depending only on DART."""
    if company_name.isdigit() and len(company_name) == 6:
        return company_name, company_name, "사용자 입력 종목코드"

    try:
        info = dc.resolve_company(company_name)
        code = (info or {}).get("stock_code")
        resolved = (info or {}).get("company") or company_name
        if code:
            return resolved, code, "DART"
    except (ValueError, RuntimeError):
        pass

    normalized = _normalize_company_query(company_name)
    if normalized in _COMMON_LISTED_COMPANIES:
        resolved, code = _COMMON_LISTED_COMPANIES[normalized]
        return resolved, code, "기본 상장사 매핑"

    try:
        from pykrx import stock

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            tickers = stock.get_market_ticker_list(market="ALL")
        matches: list[tuple[int, str, str]] = []
        for ticker in tickers:
            try:
                name = stock.get_market_ticker_name(ticker)
            except Exception:
                continue
            name_norm = _normalize_company_query(name)
            if not name_norm:
                continue
            if normalized == name_norm:
                return name, ticker, "KRX"
            if normalized in name_norm or name_norm in normalized:
                matches.append((abs(len(name_norm) - len(normalized)), name, ticker))
        if matches:
            _gap, name, ticker = sorted(matches)[0]
            return name, ticker, "KRX"
    except Exception:
        pass

    raise ValueError(f"'{company_name}'의 상장 종목코드를 찾지 못했습니다.")


def _recomm_label(recomm_mean: float) -> str:
    """네이버 투자의견 평균(1=매도 ~ 5=매수)을 한글 라벨로."""
    if recomm_mean >= 4.0:
        return "매수"
    if recomm_mean >= 3.0:
        return "매수/중립"
    if recomm_mean >= 2.0:
        return "중립"
    if recomm_mean > 0:
        return "매도"
    return "의견 없음"


def fetch_naver_consensus(stock_code: str) -> dict | None:
    """네이버 금융에서 컨센서스 평균 목표가·투자의견을 수집.

    Returns:
        {"price_target_mean": float, "recomm_mean": float,
         "opinion_label": str, "create_date": str} 또는 None
    """
    if not stock_code:
        return None
    try:
        url = _NAVER_API.format(code=stock_code)
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        if resp.status_code != 200:
            return None
        ci = resp.json().get("consensusInfo") or {}
        raw_mean = ci.get("priceTargetMean")
        if not raw_mean:
            return None
        mean = float(str(raw_mean).replace(",", ""))
        recomm = float(ci.get("recommMean") or 0)
        return {
            "price_target_mean": mean,
            "recomm_mean": recomm,
            "opinion_label": _recomm_label(recomm),
            "create_date": ci.get("createDate", ""),
        }
    except Exception:
        return None


def search_company_and_consensus(company_name: str) -> dict:
    """종목명 → DART 코드 + 네이버 컨센서스 평균을 한 번에 수집.

    Returns:
        {
            "success": bool,
            "company_name": str,
            "stock_code": str | None,
            "consensus": dict | None,   # fetch_naver_consensus 결과
            "message": str,
        }
    """
    if not company_name or not company_name.strip():
        return {"success": False, "company_name": company_name, "stock_code": None,
                "consensus": None, "message": "종목명을 입력하세요."}

    company_name = company_name.strip()

    try:
        resolved_name, code, source = _resolve_company_for_search(company_name)
    except ValueError:
        return {"success": False, "company_name": company_name, "stock_code": None,
                "consensus": None,
                "message": f"'{company_name}'의 상장 종목코드를 찾지 못했습니다. 종목명이나 6자리 종목코드로 다시 검색하세요."}

    if not code:
        return {"success": False, "company_name": company_name, "stock_code": None,
                "consensus": None,
                "message": f"'{company_name}'의 종목코드를 찾지 못했습니다."}

    consensus = fetch_naver_consensus(code)
    if not consensus:
        return {
            "success": True,
            "company_name": resolved_name,
            "stock_code": code,
            "consensus": {},
            "source": source,
            "message": (
                f"{resolved_name} 종목코드 {code}는 확인했습니다. "
                "증권사 목표가 평균은 확인하지 못했으니 PDF 업로드 또는 목표가 직접 입력으로 진행하세요."
            ),
        }

    return {
        "success": True,
        "company_name": resolved_name,
        "stock_code": code,
        "consensus": consensus,
        "source": source,
        "message": (
            f"✅ {resolved_name} 컨센서스 평균 "
            f"{(consensus.get('price_target_mean') or 0):,.0f}원 · {consensus.get('opinion_label', '확인 필요')}"
        ),
    }


def _normalize_naver_date(value: str) -> str:
    """Convert Naver research dates like 26.05.18 to YYYY-MM-DD."""
    raw = (value or "").strip()
    parts = raw.split(".")
    if len(parts) != 3:
        return raw
    yy, mm, dd = parts
    try:
        return f"20{int(yy):02d}-{int(mm):02d}-{int(dd):02d}"
    except ValueError:
        return raw


def fetch_naver_research_reports(stock_code: str, *, pages: int = 2, limit: int = 20) -> list[dict]:
    """Fetch latest Naver Finance company research rows for a stock code.

    Naver exposes report lists as HTML, not as a stable documented API. We use this
    only for metadata and PDF links; target prices still require report parsing or
    manual confirmation.
    """
    if not stock_code:
        return []
    reports: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                _NAVER_RESEARCH,
                params={"searchType": "itemCode", "itemCode": stock_code, "page": page},
                headers=_HEADERS,
                timeout=8,
            )
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            continue

        for tr in soup.select("table.type_1 tr"):
            cols = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cols) < 6:
                continue
            company, title, broker, _attach, date, views = cols[:6]
            if not company or not title or title == "제목":
                continue
            links = tr.find_all("a")
            read_url = None
            pdf_url = None
            for link in links:
                href = link.get("href") or ""
                if "company_read.naver" in href:
                    read_url = urljoin("https://finance.naver.com/research/", href)
                if href.lower().endswith(".pdf"):
                    pdf_url = href
            key = read_url or f"{stock_code}:{title}:{broker}:{date}"
            if key in seen:
                continue
            seen.add(key)
            reports.append({
                "company": company,
                "title": title,
                "broker": broker,
                "date": _normalize_naver_date(date),
                "views": views,
                "read_url": read_url,
                "pdf_url": pdf_url,
                "source": "Naver Finance Research",
            })
            if len(reports) >= limit:
                return reports
    return reports
