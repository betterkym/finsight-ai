"""증권사 컨센서스 자동 수집 — 네이버 금융 모바일 API 기반.

현실 점검 결과:
  - 증권사별 개별 목표가 리스트는 리포트 PDF 안에만 있어 안정적 크롤링 불가
    (네이버·한경 목록 페이지 모두 목표가 컬럼 없음)
  - 네이버 컨센서스 '평균 목표주가/투자의견'은 공개 API로 안정적으로 수집 가능

따라서 ①축은 '검증 목표가 vs 시장 컨센서스 평균'으로 판단한다.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from core import data_collector as dc

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    )
}
_NAVER_API = "https://m.stock.naver.com/api/stock/{code}/integration"


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

    info = dc.resolve_company(company_name)
    code = info.get("stock_code") if info else None
    resolved_name = info.get("company") if info else company_name

    if not code:
        return {"success": False, "company_name": company_name, "stock_code": None,
                "consensus": None,
                "message": f"'{company_name}'의 종목코드를 찾지 못했습니다."}

    consensus = fetch_naver_consensus(code)
    if not consensus:
        return {"success": False, "company_name": resolved_name, "stock_code": code,
                "consensus": None,
                "message": f"{resolved_name}의 컨센서스 목표가가 없습니다 (커버리지 부족)."}

    return {
        "success": True,
        "company_name": resolved_name,
        "stock_code": code,
        "consensus": consensus,
        "message": (
            f"✅ {resolved_name} 컨센서스 평균 "
            f"{consensus['price_target_mean']:,.0f}원 · {consensus['opinion_label']}"
        ),
    }
