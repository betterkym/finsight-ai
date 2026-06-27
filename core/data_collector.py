"""FinSight data layer: DART quarterly statements, ECOS macro data and market beta."""

from __future__ import annotations

import datetime as dt
import html
import io
import os
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

# core/data_collector.py 기준으로 프로젝트 루트의 .env를 로드
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DART_API_KEY = os.getenv("DART_API_KEY", "")
ECOS_API_KEY = os.getenv("ECOS_API_KEY", "")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
KOSIS_API_KEY = os.getenv("KOSIS_API_KEY", "")
KOSIS_FOOD_TABLE_ID = os.getenv("KOSIS_FOOD_TABLE_ID", "")
KAMIS_API_ID = os.getenv("KAMIS_API_ID", "")
KAMIS_API_KEY = os.getenv("KAMIS_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
TRADING_ECONOMICS_KEY = os.getenv("TRADING_ECONOMICS_KEY", "")
UN_COMTRADE_KEY = os.getenv("UN_COMTRADE_KEY", "")
KRX_ID = os.getenv("KRX_ID", "")
KRX_PW = os.getenv("KRX_PW", "")
DART_BASE = "https://opendart.fss.or.kr/api"
ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
NAVER_NEWS_BASE = "https://openapi.naver.com/v1/search/news.json"
NAVER_BLOG_BASE = "https://openapi.naver.com/v1/search/blog.json"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

REPORTS = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
REPORT_LABELS = {1: "1Q", 2: "2Q", 3: "3Q", 4: "4Q"}

# Standard XBRL IDs are preferred; Korean labels are fallbacks for issuer-specific accounts.
ACCOUNT_ALIASES = {
    "revenue": ("ifrs-full_Revenue", "매출액", "영업수익", "수익(매출액)"),
    "operating_profit": ("dart_OperatingIncomeLoss", "영업이익", "영업이익(손실)"),
    "net_income": ("ifrs-full_ProfitLoss", "당기순이익", "분기순이익", "반기순이익"),
    "cogs": ("ifrs-full_CostOfSales", "매출원가"),
    "sga": ("dart_TotalSellingGeneralAdministrativeExpenses", "판매비와관리비", "판매비와관리비용"),
    "cfo": ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름"),
    "depreciation": (
        "ifrs-full_AdjustmentsForDepreciationExpense",
        "ifrs-full_DepreciationExpense",
        "감가상각비", "유형자산감가상각비",
    ),
    "capex": (
        "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "유형자산의 취득", "유형자산 취득",
    ),
    "receivables": ("ifrs-full_TradeAndOtherCurrentReceivables", "매출채권", "매출채권 및 기타채권"),
    "inventory": ("ifrs-full_Inventories", "재고자산"),
    "payables": ("ifrs-full_TradeAndOtherCurrentPayables", "ifrs-full_TradePayables", "매입채무", "매입채무 및 기타채무"),
    "cash": ("ifrs-full_CashAndCashEquivalents", "현금및현금성자산"),
    "debt": ("ifrs-full_Borrowings", "차입금"),
    "total_assets": ("ifrs-full_Assets", "자산총계"),
    "total_liabilities": ("ifrs-full_Liabilities", "부채총계"),
    "total_equity": ("ifrs-full_Equity", "자본총계"),
    "current_assets": ("ifrs-full_CurrentAssets", "유동자산"),
    "current_liabilities": ("ifrs-full_CurrentLiabilities", "유동부채"),
}
FLOW_ACCOUNTS = {"revenue", "operating_profit", "net_income", "cogs", "sga", "cfo", "depreciation", "capex"}


def _number(value) -> float | None:
    if value is None or value == "" or pd.isna(value):
        return None
    try:
        number = float(str(value).replace(",", "").replace("−", "-").strip())
        return None if pd.isna(number) else number
    except (TypeError, ValueError):
        return None


def _dart_get(endpoint: str, **params) -> dict:
    if not DART_API_KEY:
        raise RuntimeError("DART_API_KEY가 없습니다. .env에 발급 키를 입력해 주세요.")
    try:
        response = requests.get(
            f"{DART_BASE}/{endpoint}", params={"crtfc_key": DART_API_KEY, **params}, timeout=30
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError("DART 네트워크 요청에 실패했습니다. 연결 상태를 확인해 주세요.") from exc
    payload = response.json()
    if payload.get("status") not in ("000", None):
        raise RuntimeError(payload.get("message", "DART 요청에 실패했습니다."))
    return payload


@lru_cache(maxsize=1)
def _corp_codes() -> dict[str, dict[str, str]]:
    if not DART_API_KEY:
        return {}
    try:
        response = requests.get(
            f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=30
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError("DART 기업코드 목록을 불러오지 못했습니다.") from exc
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        root = ET.fromstring(archive.read("CORPCODE.xml"))
    result = {}
    for item in root.findall("list"):
        name = (item.findtext("corp_name") or "").strip()
        if name:
            result[name] = {
                "corp_code": item.findtext("corp_code") or "",
                "stock_code": (item.findtext("stock_code") or "").strip(),
            }
    return result


def resolve_company(company: str) -> dict[str, str]:
    """Resolve an exact or close company name to DART and KRX identifiers.

    1) Exact match if exists
    2) Partial substring match
    3) Fuzzy (similarity) match — excludes financial institutions (증권·은행·보험 등)
    4) Ranks by: similarity score (descending), then shortest name
    """
    import difflib

    company = company.strip()
    codes = _corp_codes()

    # 1) 종목 코드로 검색
    if company.isdigit() and len(company) == 6:
        for name, value in codes.items():
            if value.get("stock_code") == company:
                return {"company": name, **value}
        raise ValueError(f"DART에서 종목코드 '{company}'을(를) 찾지 못했습니다.")

    # 2) 정확한 매칭
    if company in codes:
        return {"company": company, **codes[company]}

    # 금융기관 제외 필터
    def is_not_finance(name: str) -> bool:
        return not any(x in name for x in ["증권", "은행", "보험", "캐피탈", "금융", "펀드", "카드"])

    # 3) 모든 상장 종목 수집
    all_listed = [
        (name, value) for name, value in codes.items()
        if value.get("stock_code")
    ]

    # 4) 부분 매칭 (substring) — 부분 매칭이 있으면 보너스 점수
    def fuzzy_score(name: str) -> tuple:
        sim = difflib.SequenceMatcher(None, company, name).ratio()
        is_partial = company in name
        # 부분 매칭이면 유사도에 보너스, 금융기관은 페널티
        bonus = 0.2 if is_partial else 0
        penalty = -0.3 if not is_not_finance(name) else 0
        return (-sim - bonus + penalty, len(name))  # 높은 점수가 낮은 순으로 정렬되게 음수화

    # 금융기관 제외 후보
    non_finance = [c for c in all_listed if is_not_finance(c[0])]
    candidates = non_finance if non_finance else all_listed

    if not candidates:
        raise ValueError(f"DART에서 '{company}'을(를) 찾지 못했습니다.")

    # 점수로 정렬해서 최고 후보 선택
    name, value = min(candidates, key=lambda item: fuzzy_score(item[0]))
    return {"company": name, **value}


def suggest_companies(query: str, limit: int = 6) -> list[dict]:
    """Return close company-name candidates for a query that didn't resolve exactly.

    Handles substring, normalized (space/case-insensitive) and fuzzy (typo) matches so the
    UI can ask '혹시 이걸 찾으셨나요?' instead of a hard 'not found'. Listed names are preferred.
    """
    import difflib

    query = (query or "").strip()
    if not query:
        return []
    try:
        codes = _corp_codes()
    except Exception:
        return []
    if not codes:
        return []

    # Common Hangul↔Latin brand spellings so 엘지전자 surfaces LG전자, 에스케이 → SK 등.
    aliases = {"엘지": "lg", "에스케이": "sk", "케이티": "kt", "지에스": "gs", "씨제이": "cj",
               "케이비": "kb", "에이치디": "hd", "현대차": "현대자동차", "기아차": "기아"}

    def norm(value: str) -> str:
        v = value.replace(" ", "").replace("(주)", "").replace("주식회사", "").lower()
        for hangul, latin in aliases.items():
            v = v.replace(hangul, latin)
        return v

    q = norm(query)
    if not q:
        return []
    grams = {q[i:i + 2] for i in range(len(q) - 1)} or {q}
    scored: list[tuple[float, str, str]] = []
    for name, value in codes.items():
        stock_code = value.get("stock_code", "")
        if not stock_code:  # 분석에는 상장 종목코드가 필요 — 상장사만 후보로 제시
            continue
        n = norm(name)
        if len(n) < 2:
            continue
        if q in n or n in q:
            score = 0.95 if q in n else 0.78
        elif n[0] == q[0] or any(gram in n for gram in grams):
            score = difflib.SequenceMatcher(None, q, n).ratio()
        else:
            continue
        if score >= 0.5:
            scored.append((score, name, stock_code))

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    out, seen = [], set()
    for _score, name, stock_code in scored:
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "stock_code": stock_code, "listed": True})
        if len(out) >= limit:
            break
    return out


def _matches(row: pd.Series, aliases: tuple[str, ...]) -> bool:
    account_id = str(row.get("account_id", ""))
    account_nm = str(row.get("account_nm", "")).replace(" ", "")
    return any(alias == account_id or alias.replace(" ", "") == account_nm for alias in aliases)


def _extract_account(rows: pd.DataFrame, key: str, flow: bool) -> tuple[float | None, str]:
    candidates = rows[rows.apply(lambda row: _matches(row, ACCOUNT_ALIASES[key]), axis=1)]
    if candidates.empty:
        return None, "Needs Review"
    # Consolidated statement rows come first; duplicate subtotal rows come last in many filings.
    row = candidates.iloc[0]
    if flow:
        value = _number(row.get("thstrm_add_amount"))
        if value is None:
            value = _number(row.get("thstrm_amount"))
    else:
        value = _number(row.get("thstrm_amount"))
    return value, "DART"


def _fetch_report(corp_code: str, year: int, quarter: int) -> dict:
    rows = _fetch_statement_rows(corp_code, year, quarter)
    values, quality = {}, {}
    for key in ACCOUNT_ALIASES:
        values[key], quality[key] = _extract_account(rows, key, key in FLOW_ACCOUNTS)
    return {"values": values, "quality": quality}


def _fetch_statement_rows(corp_code: str, year: int, quarter: int) -> pd.DataFrame:
    """Fetch consolidated rows, falling back to separate statements."""
    rows = pd.DataFrame()
    try:
        payload = _dart_get(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=REPORTS[quarter],
            fs_div="CFS",
        )
        rows = pd.DataFrame(payload.get("list", []))
    except RuntimeError as exc:
        # DART status 013 means there is no consolidated statement for this filing.
        if "조회된" not in str(exc):
            raise
    if rows.empty:
        # Some issuers only publish separate statements.
        payload = _dart_get(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code,
            bsns_year=str(year),
            reprt_code=REPORTS[quarter],
            fs_div="OFS",
        )
        rows = pd.DataFrame(payload.get("list", []))
    return rows


def get_quarterly_financials(company: str, quarters: int = 12) -> pd.DataFrame:
    """Return standalone quarterly values for the latest 8–12 quarters.

    DART interim cash-flow values are cumulative. Flow accounts are therefore converted
    to standalone quarters by subtracting the prior cumulative filing in the same year.
    Balance-sheet accounts remain point-in-time values.
    """
    info = resolve_company(company)
    today = dt.date.today()
    start_year = today.year - (quarters // 4 + 2)
    records = []
    for year in range(start_year, today.year + 1):
        previous_cumulative: dict[str, float | None] = {key: None for key in FLOW_ACCOUNTS}
        for quarter in range(1, 5):
            # Do not request clearly future filings.
            if year == today.year and quarter > (today.month - 1) // 3:
                continue
            try:
                report = _fetch_report(info["corp_code"], year, quarter)
            except RuntimeError as exc:
                if "조회된 데이타가 없습니다" in str(exc) or "조회된 데이터가 없습니다" in str(exc):
                    continue
                raise
            values = report["values"].copy()
            for key in FLOW_ACCOUNTS:
                cumulative = values.get(key)
                if cumulative is not None and quarter > 1 and previous_cumulative.get(key) is not None:
                    values[key] = cumulative - previous_cumulative[key]
                previous_cumulative[key] = cumulative
            values.update({
                "company": info["company"], "stock_code": info["stock_code"],
                "year": year, "quarter": quarter, "period": f"{year} {REPORT_LABELS[quarter]}",
                "source": "DART", "needs_review": any(v == "Needs Review" for v in report["quality"].values()),
            })
            records.append(values)
    if not records:
        raise RuntimeError("선택한 기간의 분기 재무데이터가 없습니다.")
    return pd.DataFrame(records).sort_values(["year", "quarter"]).tail(quarters).reset_index(drop=True)


def get_peer_financials(companies: list[str], quarters: int = 12) -> dict[str, pd.DataFrame]:
    return {company: get_quarterly_financials(company, quarters) for company in companies if company.strip()}


def get_market_beta(stock_code: str, years: int = 2) -> float | None:
    """Calculate weekly beta against KOSPI from two years of prices."""
    if not stock_code:
        return None
    try:
        import FinanceDataReader as fdr

        end = dt.date.today()
        start = end - dt.timedelta(days=365 * years + 30)
        stock_prices = fdr.DataReader(stock_code, start, end)
        market_prices = fdr.DataReader("KS11", start, end)
        # Some FDR/KRX combinations no longer return KS11. KODEX 200 is a liquid proxy.
        if market_prices.empty or "Close" not in market_prices:
            market_prices = fdr.DataReader("069500", start, end)
        stock = stock_prices["Close"].resample("W-FRI").last().pct_change()
        market = market_prices["Close"].resample("W-FRI").last().pct_change()
        joined = pd.concat([stock, market], axis=1).dropna()
        if len(joined) < 30 or joined.iloc[:, 1].var() == 0:
            return None
        return float(np.cov(joined.iloc[:, 0], joined.iloc[:, 1], ddof=1)[0, 1] / joined.iloc[:, 1].var())
    except Exception:
        return None


def get_current_price(stock_code: str) -> float | None:
    """Return the latest available closing price from FinanceDataReader."""
    if not stock_code:
        return None
    try:
        import FinanceDataReader as fdr

        end = dt.date.today()
        start = end - dt.timedelta(days=30)
        prices = fdr.DataReader(stock_code, start, end)
        if prices.empty:
            return None
        return float(prices["Close"].dropna().iloc[-1])
    except Exception:
        return None


def _prior_report_periods(year: int, quarter: int, limit: int = 8) -> list[tuple[int, int]]:
    periods = []
    current_year, current_quarter = year, quarter
    for _ in range(limit):
        periods.append((current_year, current_quarter))
        current_quarter -= 1
        if current_quarter == 0:
            current_year -= 1
            current_quarter = 4
    return periods


def get_share_snapshot(company: str, year: int, quarter: int) -> dict:
    """Get total distributed shares, falling back to the latest report with numeric data."""
    info = resolve_company(company)
    for report_year, report_quarter in _prior_report_periods(year, quarter):
        try:
            payload = _dart_get(
                "stockTotqySttus.json",
                corp_code=info["corp_code"],
                bsns_year=str(report_year),
                reprt_code=REPORTS[report_quarter],
            )
        except RuntimeError as exc:
            if "조회된" in str(exc):
                continue
            raise
        rows = payload.get("list", [])
        total = next((row for row in rows if row.get("se") == "합계"), None)
        if total:
            distributed = _number(total.get("distb_stock_co"))
            issued = _number(total.get("istc_totqy"))
            treasury = _number(total.get("tesstk_co")) or 0.0
            if distributed is not None and distributed > 0:
                return {
                    "shares_outstanding": distributed,
                    "issued_shares": issued,
                    "treasury_shares": treasury,
                    "as_of": total.get("stlm_dt"),
                    "source": "DART 주식의 총수 현황 — 유통주식수(합계)",
                    "report_year": report_year,
                    "report_quarter": report_quarter,
                }
    return {
        "shares_outstanding": None, "issued_shares": None, "treasury_shares": None,
        "as_of": None, "source": "DART 주식수 Needs Review",
    }


_DEBT_ACCOUNT_IDS = {
    "ifrs-full_ShorttermBorrowings", "dart_ShortTermBorrowings",
    "ifrs-full_LongtermBorrowings", "dart_LongTermBorrowingsGross",
    "ifrs-full_CurrentLeaseLiabilities", "ifrs-full_NoncurrentLeaseLiabilities",
    "ifrs-full_CurrentPortionOfNoncurrentBorrowings",
    "dart_CurrentPortionOfLongTermBorrowings", "dart_CurrentPortionOfBonds",
    "dart_CurrentPortionOfConvertibleBonds", "dart_CurrentPortionOfExchangeableBond",
    "ifrs-full_BondsIssued", "dart_BondsIssued",
}
_DEBT_ACCOUNT_NAMES = {
    "단기차입금", "장기차입금", "유동성장기차입금", "유동성장기부채",
    "사채", "유동성사채", "전환사채", "유동성전환사채", "교환사채",
    "유동성교환사채", "신주인수권부사채", "리스부채", "유동성리스부채", "비유동리스부채",
}


def get_capital_structure(company: str, year: int, quarter: int) -> dict:
    """Calculate gross debt, net debt, market debt weight and accounting debt ratio."""
    info = resolve_company(company)
    rows = _fetch_statement_rows(info["corp_code"], year, quarter)
    bs = rows[rows.get("sj_div", pd.Series(dtype=str)).eq("BS")].copy()
    if bs.empty:
        return {"gross_debt": None, "net_debt": None, "debt_weight": None, "source": "DART Needs Review"}

    bs["_amount"] = bs["thstrm_amount"].map(_number)
    normalized_name = bs["account_nm"].astype(str).str.replace(" ", "", regex=False)
    debt_mask = bs["account_id"].isin(_DEBT_ACCOUNT_IDS) | normalized_name.isin(_DEBT_ACCOUNT_NAMES)
    debt_rows = bs[debt_mask & bs["_amount"].notna()].drop_duplicates(subset=["account_id", "account_nm"])
    gross_debt = float(debt_rows["_amount"].abs().sum())

    def exact_value(account_id: str) -> float | None:
        matched = bs[bs["account_id"].eq(account_id)]["_amount"].dropna()
        return float(matched.iloc[0]) if not matched.empty else None

    cash = exact_value("ifrs-full_CashAndCashEquivalents")
    liabilities = exact_value("ifrs-full_Liabilities")
    equity = exact_value("ifrs-full_Equity")
    net_debt = gross_debt - cash if cash is not None else None
    accounting_debt_ratio = (
        liabilities / equity * 100 if liabilities is not None and equity not in (None, 0) else None
    )

    share_data = get_share_snapshot(info["company"], year, quarter)
    current_price = get_current_price(info["stock_code"])
    shares = share_data.get("shares_outstanding")
    market_cap = current_price * shares if current_price is not None and shares is not None else None
    if market_cap is not None and gross_debt + market_cap > 0:
        debt_weight = gross_debt / (gross_debt + market_cap) * 100
        weight_source = "DART 이자부채 + FDR 최근 종가 시가총액"
    elif equity is not None and gross_debt + equity > 0:
        debt_weight = gross_debt / (gross_debt + equity) * 100
        weight_source = "DART 장부자본 fallback"
    else:
        debt_weight, weight_source = None, "Needs Review"

    return {
        **share_data,
        "company": info["company"], "stock_code": info["stock_code"],
        "cash": cash, "gross_debt": gross_debt, "net_debt": net_debt,
        "total_liabilities": liabilities, "total_equity": equity,
        "accounting_debt_ratio": accounting_debt_ratio,
        "current_price": current_price, "market_cap": market_cap,
        "debt_weight": debt_weight, "debt_weight_source": weight_source,
        "share_source": share_data.get("source"),
        "debt_components": [
            {"account": row["account_nm"], "amount": float(row["_amount"])}
            for _, row in debt_rows.iterrows()
        ],
        "source": "DART 최신 재무상태표 + 주식총수 + FinanceDataReader",
    }


def get_macro_snapshot() -> dict[str, float | None]:
    """Fetch current DCF macro inputs from ECOS, with explicit fallbacks."""
    fallback = {"risk_free_rate": 3.2, "usd_krw": None, "gdp_growth": 2.0, "erp": 6.0}
    if not ECOS_API_KEY:
        return {**fallback, "source": "Fallback — ECOS key missing"}

    def latest(stat: str, cycle: str, item: str, unit: str = "?") -> float | None:
        end = dt.date.today()
        start = end - dt.timedelta(days=550)
        if cycle == "D":
            s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        elif cycle == "M":
            s, e = start.strftime("%Y%m"), end.strftime("%Y%m")
        else:
            s, e = str(end.year - 3), str(end.year)
        url = f"{ECOS_BASE}/{ECOS_API_KEY}/json/kr/1/100/{stat}/{cycle}/{s}/{e}/{item}/{unit}"
        try:
            rows = requests.get(url, timeout=20).json()["StatisticSearch"]["row"]
            return _number(rows[-1]["DATA_VALUE"])
        except Exception:
            return None

    def cpi_yoy() -> float | None:
        end = dt.date.today()
        start = end - dt.timedelta(days=500)
        url = f"{ECOS_BASE}/{ECOS_API_KEY}/json/kr/1/100/901Y009/M/{start.strftime('%Y%m')}/{end.strftime('%Y%m')}/0"
        try:
            rows = requests.get(url, timeout=20).json()["StatisticSearch"]["row"]
            series = [(_number(r["DATA_VALUE"])) for r in rows if _number(r.get("DATA_VALUE")) is not None]
            if len(series) >= 13 and series[-13]:
                return round((series[-1] / series[-13] - 1) * 100, 2)
        except Exception:
            return None
        return None

    rf = latest("817Y002", "D", "010210000")
    fx = latest("731Y001", "D", "0000001")
    gdp = latest("200Y104", "A", "1400", "?")
    cpi = cpi_yoy()
    return {
        "risk_free_rate": rf if rf is not None else fallback["risk_free_rate"],
        "usd_krw": fx, "gdp_growth": gdp if gdp is not None else fallback["gdp_growth"],
        "cpi_growth": cpi if cpi is not None else 2.5,
        "erp": fallback["erp"], "source": "ECOS + KICPA reference/fallback",
    }


def get_peer_beta_inputs(peer_names: list[str]) -> list[dict]:
    """Resolve peer levered betas and a debt/equity proxy for WACC unlever/relever."""
    results = []
    for name in peer_names:
        try:
            info = resolve_company(name)
        except Exception:
            continue
        beta = get_market_beta(info.get("stock_code", ""))
        if beta is None:
            continue
        de = None
        try:
            today = dt.date.today()
            quarter = max(1, (today.month - 1) // 3)
            for ry, rq in _prior_report_periods(today.year, quarter, limit=4):
                rows = _fetch_statement_rows(info["corp_code"], ry, rq)
                bs = rows[rows.get("sj_div", pd.Series(dtype=str)).eq("BS")]
                if bs.empty:
                    continue
                liabilities = bs[bs["account_id"].eq("ifrs-full_Liabilities")]["thstrm_amount"].map(_number).dropna()
                equity = bs[bs["account_id"].eq("ifrs-full_Equity")]["thstrm_amount"].map(_number).dropna()
                if not liabilities.empty and not equity.empty and equity.iloc[0]:
                    de = float(liabilities.iloc[0] / equity.iloc[0] * 100)
                    break
        except Exception:
            de = None
        results.append({"name": info["company"], "levered_beta": float(beta), "de_ratio": de})
    return results


PEER_GROUPS = {
    "Food & Beverage": ["농심", "삼양식품", "오뚜기", "CJ제일제당", "대상"],
    "Beauty & Personal Care": ["아모레퍼시픽", "LG생활건강", "에이피알", "코스맥스", "한국콜마"],
    "Retail": ["신세계", "현대백화점", "롯데쇼핑", "BGF리테일", "GS리테일"],
}


def recommend_peers(company: str, limit: int = 2) -> dict:
    """Return transparent, curated sector peers for the POC universe."""
    resolved = company.strip()
    known_names = {member for members in PEER_GROUPS.values() for member in members}
    if resolved not in known_names:
        try:
            resolved = resolve_company(company)["company"]
        except Exception:
            pass
    for group, members in PEER_GROUPS.items():
        if resolved in members:
            return {
                "company": resolved,
                "peer_group": group,
                "peers": [member for member in members if member != resolved][:limit],
                "method": "검증된 상장 동종기업 세트 · 사업모델·전방시장 유사성 기준",
            }
    return {"company": resolved, "peer_group": "미분류", "peers": [], "method": "직접 검토 필요"}


def get_recent_disclosures(company: str, days: int = 365, limit: int = 30) -> list[dict]:
    """Fetch recent DART filing titles for internal root-cause evidence."""
    info = resolve_company(company)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    payload = _dart_get(
        "list.json",
        corp_code=info["corp_code"],
        bgn_de=start.strftime("%Y%m%d"),
        end_de=end.strftime("%Y%m%d"),
        page_no=1,
        page_count=min(limit, 100),
        sort="date",
        sort_mth="desc",
    )
    return [
        {
            "rcept_no": row.get("rcept_no"),
            "date": row.get("rcept_dt"),
            "title": row.get("report_nm"),
            "filer": row.get("flr_nm"),
            "report_type": row.get("pblntf_ty"),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no')}",
            "source": "DART 공시",
        }
        for row in payload.get("list", [])[:limit]
    ]


DISCLOSURE_EVIDENCE_KEYWORDS = [
    "신규시설투자", "시설투자", "공급계약", "영업정지", "대량보유", "지분", "기업설명회",
    "원재료", "가격", "수출", "해외", "공장", "증설", "생산능력", "환율", "재고",
]


def _dart_document_text(rcept_no: str) -> str:
    """Return plain text from a DART filing package, bounded for causal evidence search."""
    try:
        response = requests.get(
            f"{DART_BASE}/document.xml",
            params={"crtfc_key": DART_API_KEY, "rcept_no": rcept_no},
            timeout=30,
        )
        response.raise_for_status()
        chunks = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist()[:20]:
                if not name.lower().endswith((".xml", ".html", ".htm", ".txt")):
                    continue
                raw = archive.read(name)
                decoded = raw.decode("utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", decoded)
                text = html.unescape(re.sub(r"\s+", " ", text)).strip()
                if text:
                    chunks.append(text)
        return " ".join(chunks)[:500_000]
    except Exception:
        return ""


def enrich_disclosures_with_snippets(disclosures: list[dict], limit: int = 4) -> list[dict]:
    """Attach short primary-source snippets to the most decision-relevant filings."""
    enriched = [dict(item) for item in disclosures]
    candidates = [
        item for item in enriched
        if any(keyword in str(item.get("title", "")) for keyword in DISCLOSURE_EVIDENCE_KEYWORDS)
    ][:limit]
    for item in candidates:
        text = _dart_document_text(str(item.get("rcept_no") or ""))
        if not text:
            continue
        positions = [text.find(keyword) for keyword in DISCLOSURE_EVIDENCE_KEYWORDS if text.find(keyword) >= 0]
        if positions:
            start = max(0, min(positions) - 120)
            item["description"] = text[start:start + 700]
            item["evidence_level"] = "Primary filing text"
    return enriched


# SG&A footnote line items → fixed/variable/labour/bad-debt buckets, matching the
# decomposition the reference DCF builds. Depreciation lines are excluded (handled in D&A).
_SGA_BUCKETS = {
    "labor": ["급여", "임금", "퇴직급여", "복리후생비"],
    "variable": ["지급수수료", "여비교통비", "수도광열비", "임차료", "소모품비", "수출비용", "용역비", "판매수수료"],
    "fixed": ["제세공과금", "세금과공과", "운반비", "운송보관료", "광고선전비", "판매촉진비", "경상개발비", "연구비", "기타판매비와관리비", "기타"],
    "baddebt": ["대손상각비"],
}
_SGA_SKIP = ["감가상각비", "무형자산상각비", "상각비"]


def get_sga_breakdown(company: str, year: int | None = None) -> dict | None:
    """Parse the 판매비와관리비 footnote and bucket it into labour/variable/fixed/bad-debt.

    Returns ``None`` on any doubt (few matches, implausible shares, parse error) so the
    caller falls back to curated/default weights — this can only improve coverage, never
    inject a wrong split.
    """
    try:
        info = resolve_company(company)
        disclosures = get_recent_disclosures(company, days=500, limit=40)
        # The itemised 판관비 table lives in the annual 사업보고서; quarterly/half reports
        # usually omit it. Try annual first, then fall back to others.
        ordered = (
            [d for d in disclosures if "사업보고서" in str(d.get("title", ""))]
            + [d for d in disclosures if "반기보고서" in str(d.get("title", ""))]
            + [d for d in disclosures if "분기보고서" in str(d.get("title", ""))]
        )
        # '광고선전비'/'운송보관료' appear only in the SG&A note, never on the balance
        # sheet, so they anchor a clean window and keep '급여자산' etc. out.
        label_re = {
            label: re.compile(
                (r"급여(?!자산|채무|부채|충당)" if label == "급여" else re.escape(label))
                + r"[^0-9\-]{0,14}([0-9]{1,3}(?:,[0-9]{3}){1,3})"
            )
            for labels in _SGA_BUCKETS.values() for label in labels if label not in _SGA_SKIP
        }
        amounts: dict[str, float] = {}
        report = None
        for candidate in ordered[:4]:
            text = _dart_document_text(str(candidate.get("rcept_no") or ""))
            if not text or "광고선전비" not in text:
                continue
            anchor = text.find("광고선전비")
            window = text[max(0, anchor - 2800): anchor + 2800]
            found: dict[str, float] = {}
            for label, rx in label_re.items():
                if label in found:
                    continue
                m = rx.search(window)
                if m:
                    found[label] = float(m.group(1).replace(",", ""))
            if len(found) >= 6:
                amounts, report = found, candidate
                break
        if not amounts or report is None:
            return None
        buckets = {b: 0.0 for b in _SGA_BUCKETS}
        for bucket, labels in _SGA_BUCKETS.items():
            for label in labels:
                buckets[bucket] += amounts.get(label, 0.0)
        total = sum(buckets.values())
        # A real listed staple's SG&A note is hundreds of 억 (천원 units); a far smaller
        # sum signals a partial parse or wrong unit column — reject rather than mislead.
        if total < 1e7:  # 100억 in 천원
            return None
        shares = {b: buckets[b] / total for b in buckets}
        # Sanity gate: a clean SG&A note has labour and fixed each in a believable band.
        if not (0.10 <= shares["labor"] <= 0.55 and 0.10 <= shares["fixed"] <= 0.65 and shares["variable"] <= 0.60):
            return None
        return {
            "labor": round(shares["labor"], 4), "variable": round(shares["variable"], 4),
            "fixed": round(shares["fixed"], 4), "baddebt": round(shares["baddebt"], 4),
            "matched_items": len(amounts), "total_eok": round(total / 1e5, 1),
            "source": f"DART 판관비 주석 자동 추출 ({report.get('title', '')[:24]}, {len(amounts)}개 항목)",
        }
    except Exception:
        return None


def _plain_html(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(text).strip()


def _naver_search(endpoint: str, query: str, limit: int) -> list[dict]:
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    response = requests.get(
        endpoint,
        params={"query": query, "display": min(limit, 100), "sort": "date"},
        headers={
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        },
        timeout=20,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    source = "Naver News" if endpoint == NAVER_NEWS_BASE else "Naver Blog"
    return [
        {
            "date": item.get("pubDate"),
            "title": _plain_html(item.get("title")),
            "description": _plain_html(item.get("description")),
            "url": item.get("originallink") or item.get("link"),
            "source": source,
            "query": query,
            "evidence_level": "Reported context" if source == "Naver News" else "Unverified interpretation",
        }
        for item in items[:limit]
    ]


def _dedupe_context(items: list[dict], limit: int) -> list[dict]:
    seen, result = set(), []
    for item in items:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def get_external_news_context(company: str, limit: int = 24) -> list[dict]:
    """Search decision themes instead of returning a generic company-news feed."""
    queries = [
        f"{company} 실적 전망", f"{company} 수출 해외 공장",
        f"{company} 원가 가격 경쟁", f"{company} 수급 국민연금 외국인",
    ]
    items = []
    for query in queries:
        items.extend(_naver_search(NAVER_NEWS_BASE, query, max(4, limit // len(queries))))
    return _dedupe_context(items, limit)


def get_external_blog_context(company: str, limit: int = 10) -> list[dict]:
    """Fetch explicitly labeled, unverified interpretations for expectation-gap discovery."""
    queries = [f"{company} 주가 이유", f"{company} 실적 주가 괴리"]
    items = []
    for query in queries:
        items.extend(_naver_search(NAVER_BLOG_BASE, query, max(4, limit // len(queries))))
    return _dedupe_context(items, limit)


def get_major_shareholding_changes(company: str, limit: int = 12) -> list[dict]:
    """Return DART 5% ownership reports with explicit share and ratio changes."""
    info = resolve_company(company)
    try:
        payload = _dart_get("majorstock.json", corp_code=info["corp_code"])
    except RuntimeError as exc:
        if "조회된" in str(exc):
            return []
        raise
    rows = []
    for item in payload.get("list", [])[:limit]:
        rows.append({
            "date": item.get("rcept_dt"), "reporter": item.get("repror"),
            "report_type": item.get("report_tp"), "shares": _number(item.get("stkqy")),
            "share_change": _number(item.get("stkqy_irds")), "ratio": _number(item.get("stkrt")),
            "ratio_change": _number(item.get("stkrt_irds")), "reason": item.get("report_resn"),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
            "source": "DART 대량보유 상황보고", "evidence_level": "Primary filing data",
        })
    return rows


def get_market_snapshot(stock_code: str) -> dict:
    """Return price drawdown, momentum and volume regime used for expectation-gap analysis."""
    if not stock_code:
        return {}
    try:
        import FinanceDataReader as fdr

        end = dt.date.today()
        prices = fdr.DataReader(stock_code, end - dt.timedelta(days=430), end)
        close = prices["Close"].dropna()
        if close.empty:
            return {}
        current = float(close.iloc[-1])
        window_52 = close.tail(252)
        result = {
            "current_price": current, "high_52w": float(window_52.max()), "low_52w": float(window_52.min()),
            "drawdown_52w_high": (current / float(window_52.max()) - 1) * 100,
            "position_52w": (current - float(window_52.min())) / (float(window_52.max()) - float(window_52.min())) * 100 if window_52.max() != window_52.min() else None,
            "source": "FinanceDataReader/KRX", "as_of": str(close.index[-1].date()),
        }
        for days, label in ((21, "return_1m"), (63, "return_3m"), (126, "return_6m"), (252, "return_12m")):
            result[label] = (current / float(close.iloc[-min(days + 1, len(close))]) - 1) * 100 if len(close) > 1 else None
        if "Volume" in prices and len(prices["Volume"].dropna()) >= 60:
            volume = prices["Volume"].dropna()
            result["volume_20d_vs_60d"] = float(volume.tail(20).mean() / volume.tail(60).mean() * 100)
        return result
    except Exception:
        return {}


def _status(source: str, connected: bool, detail: str, *, action: str = "", evidence_level: str = "Context") -> dict:
    return {
        "source": source,
        "connected": connected,
        "status": "Connected" if connected else "Needs setup",
        "detail": detail,
        "action": action,
        "evidence_level": evidence_level,
    }


def get_krx_flow_snapshot(stock_code: str, days: int = 90) -> dict:
    """Optional KRX investor-flow snapshot via pykrx.

    Investor flow is intentionally kept separate from DART fundamentals: it explains
    multiple/price reaction risk, not operating performance.
    """
    if not stock_code:
        return {"connected": False, "source": "KRX", "reason": "종목코드 없음", "status_rows": []}
    if not KRX_ID or not KRX_PW:
        return {
            "connected": False,
            "source": "KRX/pykrx",
            "reason": "KRX_ID 또는 KRX_PW 환경변수 필요",
            "action": "KRX 계정 정보를 .env에 추가하면 기관·외국인 수급을 자동 연결",
            "status_rows": [],
        }
    try:
        from pykrx import stock

        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        frame = stock.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), stock_code, detail=True
        )
        if frame is None or frame.empty:
            return {"connected": False, "source": "KRX/pykrx", "reason": "수급 데이터 없음", "status_rows": []}
        numeric = frame.apply(pd.to_numeric, errors="coerce")
        # KRX detail 컬럼은 기관을 7개 세부항목으로 쪼개 제공한다(기관합계 컬럼 없음).
        # 외국인도 본토/기타로 나뉘므로 각각 합산해 투자자 그룹별 순매수를 만든다.
        INSTITUTION_COLS = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
        FOREIGN_COLS = ["외국인합계", "외국인", "기타외국인"]
        RETAIL_COLS = ["개인"]

        def group_tail_sum(candidate_cols: list[str], window: int) -> float | None:
            present = [c for c in candidate_cols if c in numeric]
            # 합계 컬럼(예: 외국인합계)이 있으면 세부 항목과의 이중 계산을 피한다.
            aggregate = next((c for c in present if c.endswith("합계")), None)
            present = [aggregate] if aggregate else present
            if not present:
                return None
            per_day = numeric[present].sum(axis=1, min_count=1).dropna()
            if per_day.empty:
                return None
            return float(per_day.tail(min(window, len(per_day))).sum() / 1e8)

        foreign_20d = group_tail_sum(FOREIGN_COLS, 20)
        institution_20d = group_tail_sum(INSTITUTION_COLS, 20)
        retail_20d = group_tail_sum(RETAIL_COLS, 20)
        foreign_60d = group_tail_sum(FOREIGN_COLS, 60)
        institution_60d = group_tail_sum(INSTITUTION_COLS, 60)
        smart_20d = sum(x for x in [foreign_20d, institution_20d] if x is not None)
        if foreign_20d is None and institution_20d is None:
            verdict = "수급 열 매핑 확인 필요"
        elif smart_20d < 0:
            verdict = "기관·외국인 순매도 우위 — 실적 개선에도 멀티플 회복이 지연될 수 있음"
        elif smart_20d > 0:
            verdict = "기관·외국인 순매수 우위 — 실적 개선이 가격에 반영될 가능성 확인"
        else:
            verdict = "수급 중립"
        return {
            "connected": True,
            "source": "KRX investor flow via pykrx",
            "as_of": str(numeric.index[-1].date()) if hasattr(numeric.index[-1], "date") else str(numeric.index[-1]),
            "foreign_20d_eok": foreign_20d,
            "institution_20d_eok": institution_20d,
            "retail_20d_eok": retail_20d,
            "foreign_60d_eok": foreign_60d,
            "institution_60d_eok": institution_60d,
            "verdict": verdict,
            "columns": list(frame.columns),
        }
    except ImportError:
        return {
            "connected": False,
            "source": "KRX Data",
            "reason": "pykrx 미설치",
            "action": "requirements 설치 후 KRX 수급 자동 연결",
            "status_rows": [],
        }
    except Exception as exc:
        message = str(exc)[:160]
        if "KRX_ID" in message or "KRX_PW" in message or "로그인" in message:
            message = "KRX_ID 또는 KRX_PW 환경변수 필요"
        return {"connected": False, "source": "KRX/pykrx", "reason": message, "status_rows": []}


def _fred_latest(series_id: str) -> dict | None:
    """Latest FRED observation plus 3M/12M trailing change so callers can react to direction, not just presence."""
    if not FRED_API_KEY:
        return None
    try:
        response = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 400,
            },
            timeout=20,
        )
        response.raise_for_status()
        obs = []
        for row in response.json().get("observations", []):
            value = _number(row.get("value"))
            date = row.get("date")
            if value is not None and date:
                obs.append((date, value))
        if not obs:
            return None
        latest_date, latest_value = obs[0]  # desc order: newest first
        anchor = dt.date.fromisoformat(latest_date)

        def value_on_or_before(days_back: int) -> float | None:
            target = anchor - dt.timedelta(days=days_back)
            for date, value in obs:
                if dt.date.fromisoformat(date) <= target:
                    return value
            return None

        prior_3m = value_on_or_before(90)
        prior_12m = value_on_or_before(365)
        change_3m = (latest_value / prior_3m - 1) * 100 if prior_3m else None
        change_12m = (latest_value / prior_12m - 1) * 100 if prior_12m else None
        return {
            "date": latest_date,
            "value": latest_value,
            "series_id": series_id,
            "change_3m_pct": round(change_3m, 1) if change_3m is not None else None,
            "change_12m_pct": round(change_12m, 1) if change_12m is not None else None,
        }
    except Exception:
        return None


def get_worldbank_macro_snapshot() -> dict:
    """No-key country macro fallback for inflation/GDP context."""
    indicators = {
        "korea_inflation_yoy": ("KOR", "FP.CPI.TOTL.ZG"),
        "korea_gdp_growth": ("KOR", "NY.GDP.MKTP.KD.ZG"),
        "us_inflation_yoy": ("USA", "FP.CPI.TOTL.ZG"),
    }
    result = {"connected": False, "source": "World Bank API", "items": []}
    for label, (country, indicator) in indicators.items():
        try:
            response = requests.get(
                f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
                params={"format": "json", "per_page": 6},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            row = next((x for x in rows if x.get("value") is not None), None)
            if row:
                result["items"].append({
                    "label": label,
                    "date": row.get("date"),
                    "value": float(row.get("value")),
                    "source": "World Bank",
                })
        except Exception:
            continue
    result["connected"] = bool(result["items"])
    return result


def get_external_driver_snapshot(company: str, stock_code: str) -> dict:
    """Aggregate non-DART drivers used as second-level hypotheses, never as hard facts."""
    flows = get_krx_flow_snapshot(stock_code)
    worldbank = get_worldbank_macro_snapshot()
    fred_fx = _fred_latest("DEXKOUS")
    fred_wheat = _fred_latest("PWHEAMTUSDM")

    status_rows = [
        _status(
            "KRX investor flow",
            bool(flows.get("connected")),
            flows.get("verdict") or flows.get("reason") or "기관·외국인·개인 수급",
            action=flows.get("action", "실적과 주가 반응 괴리 설명에 사용"),
            evidence_level="Market microstructure",
        ),
        _status(
            "KOSIS",
            bool(KOSIS_API_KEY and KOSIS_FOOD_TABLE_ID),
            "식품산업·소비·물가 세부통계 연결" if KOSIS_API_KEY and KOSIS_FOOD_TABLE_ID else "KOSIS_API_KEY와 KOSIS_FOOD_TABLE_ID 필요",
            action="국내 산업 성장률·수요 흐름을 매출 전망과 대조",
            evidence_level="Official statistics",
        ),
        _status(
            "KAMIS",
            bool(KAMIS_API_ID and KAMIS_API_KEY),
            "농산물·가공식품 원재료 가격 연결 준비" if KAMIS_API_ID and KAMIS_API_KEY else "KAMIS_API_ID와 KAMIS_API_KEY 필요",
            action="원가율 변동 원인 후보로 사용",
            evidence_level="Official price data",
        ),
        _status(
            "World Bank",
            bool(worldbank.get("connected")),
            f"{len(worldbank.get('items', []))}개 국가 매크로 항목",
            action="해외/국내 수요·물가 배경 확인",
            evidence_level="Official statistics",
        ),
        _status(
            "FRED",
            bool(FRED_API_KEY and (fred_fx or fred_wheat)),
            "USD/KRW·원재료 proxy 연결" if FRED_API_KEY else "FRED_API_KEY 필요",
            action="환율·원재료 가격이 원가율/해외 실적에 미친 압력 확인",
            evidence_level="Macro/commodity proxy",
        ),
        _status(
            "Trading Economics",
            bool(TRADING_ECONOMICS_KEY),
            "국가별 고빈도 매크로/원자재 확장 준비" if TRADING_ECONOMICS_KEY else "TRADING_ECONOMICS_KEY 필요",
            action="해외 국가별 매출 가정과 환율/금리 민감도 보강",
            evidence_level="Macro context",
        ),
        _status(
            "UN Comtrade / KATI",
            bool(UN_COMTRADE_KEY),
            "HS코드 기반 수출입 proxy 확장 준비" if UN_COMTRADE_KEY else "UN_COMTRADE_KEY 및 HS 코드 매핑 필요",
            action=f"{company} 해외 매출이 공시보다 늦게 보일 때 수출 물량 proxy로 검증",
            evidence_level="Trade proxy",
        ),
    ]
    return {
        "flows": flows,
        "macro": {
            "worldbank": worldbank,
            "fred_usd_krw": fred_fx,
            "fred_wheat": fred_wheat,
        },
        "cost_inputs": {
            "kamis_configured": bool(KAMIS_API_ID and KAMIS_API_KEY),
            "fred_wheat": fred_wheat,
            "note": "KAMIS 품목코드 매핑 후 소맥/팜유/농산물 원가 proxy를 원가율 해석에 연결",
        },
        "trade_proxy": {
            "configured": bool(UN_COMTRADE_KEY),
            "note": "UN Comtrade/KATI는 HS코드 또는 KATI 품목 매핑 후 해외 물량 검증에 사용",
        },
        "status_rows": status_rows,
    }


# Compatibility aliases kept small so existing notebooks do not break abruptly.
get_financials = get_quarterly_financials
get_macro_data = get_macro_snapshot
