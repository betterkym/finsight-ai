import os
import io
import re
import zipfile
import datetime
import requests
import pandas as pd
import xml.etree.ElementTree as ET
import FinanceDataReader as fdr
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY")
DART_BASE = "https://opendart.fss.or.kr/api"

ECOS_API_KEY = os.getenv("ECOS_API_KEY")
ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NAVER_TREND_BASE    = "https://openapi.naver.com/v1/datalab/search"
NAVER_FINANCE_BASE  = "https://finance.naver.com/item/coinfo.naver"

_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ECOS 통계코드 상수
_ECOS_BASE_RATE   = ("722Y001", "A", "0101000")   # 한국은행 기준금리 (연말 기준)
_ECOS_KTB10Y      = ("721Y001", "A", "5050000")   # 국고채 10년물 수익률 (연평균)

# IS 집계 계정 — MAX(abs) 전략 적용 대상
IS_ACCOUNTS = {"매출액", "영업이익", "당기순이익"}

# 계정명 표준화 매핑 (기업마다 계정명이 달라서 통일)
ACCOUNT_MAP = {
    # ── 매출액 ────────────────────────────────────────────────
    "매출액": "매출액",
    "수익(매출액)": "매출액",
    "영업수익": "매출액",
    "매출액(영업수익)": "매출액",
    "순매출액": "매출액",
    # "매출" 키는 "매출총이익" 오탐 위험이 있으나 MAX(abs) 전략으로 자기보정됨.
    # 단, 반드시 "매출액" 보다 뒤에 위치해야 함 (exact match 우선이므로 문제 없음).
    "매출": "매출액",

    # ── 영업이익 ──────────────────────────────────────────────
    "영업이익": "영업이익",
    "영업이익(손실)": "영업이익",
    "영업이익(영업손실)": "영업이익",
    "영업손익": "영업이익",

    # ── 당기순이익 ────────────────────────────────────────────
    "당기순이익": "당기순이익",
    "당기순이익(손실)": "당기순이익",
    "당기순손익": "당기순이익",
    "당기순이익(손실)(지배)": "당기순이익",
    "분기순이익": "당기순이익",

    # ── 자산 ──────────────────────────────────────────────────
    "자산총계": "자산총계",
    "자산합계": "자산총계",          # 일부 기업 대체 계정명

    # ── 부채 ──────────────────────────────────────────────────
    "부채총계": "부채총계",
    "부채합계": "부채총계",          # 일부 기업 대체 계정명

    # ── 자본 ──────────────────────────────────────────────────
    "자본총계": "자본총계",
    "자본합계": "자본총계",          # 일부 기업 대체 계정명

    # ── 영업활동현금흐름 ──────────────────────────────────────
    "영업활동으로 인한 현금흐름": "영업활동현금흐름",
    "영업활동현금흐름": "영업활동현금흐름",
    "영업활동으로인한현금흐름": "영업활동현금흐름",
    "영업활동으로 인한 순현금흐름": "영업활동현금흐름",
    "영업활동으로인한순현금흐름": "영업활동현금흐름",
    # "영업활동" 단독 키: startswith 체인에서 CF 섹션 합계를 포착.
    # sj_div="CF" 필터가 있어 IS/BS 오염 없음.
    "영업활동": "영업활동현금흐름",

    # ── CAPEX (유형자산 취득 — 현금유출 기준) ────────────────
    "유형자산의 취득": "CAPEX",
    "유형자산 취득": "CAPEX",
    "유형자산취득": "CAPEX",
    "유형자산의취득": "CAPEX",
    "유형자산의 증가": "CAPEX",
    "유형자산및무형자산의취득": "CAPEX",   # 합산 보고 기업
    "유형자산 및 무형자산 취득": "CAPEX",  # 공백 변형
    "유형자산 및 무형자산의 취득": "CAPEX",

    # ── EPS (원/주 단위 — 백만원 변환 없이 저장) ─────────────
    "기본주당이익": "EPS",
    "기본주당순이익": "EPS",
    "기본주당손익": "EPS",            # 손익 표현 기업
    "기본주당이익(손실)": "EPS",
    "기본주당손실": "EPS",
    "보통주 기본주당이익": "EPS",      # 에이피알 2024 등
    "보통주기본주당이익": "EPS",
    "보통주 기본주당순이익": "EPS",
    "보통주 기본주당손익": "EPS",      # 에이피알 2021·2022·2025
    "보통주기본주당손익": "EPS",
    "보통주 기본주당이익(손실)": "EPS",
}

# 재무제표 구분(sj_div)별 수집 대상 — 계정명 중복 방지
SJ_ACCOUNT_MAP = {
    "IS":  {"매출액", "영업이익", "당기순이익", "EPS"},
    "CIS": {"매출액", "영업이익", "당기순이익", "EPS"},
    "BS":  {"자산총계", "부채총계", "자본총계"},
    "CF":  {"영업활동현금흐름", "CAPEX"},
}

# EPS 등 원/주 단위 계정 — get_financials()에서 1,000,000 나누지 않음
PER_SHARE_ACCOUNTS = {"EPS"}

# 런타임 캐시 — 프로세스 내 최초 1회만 로드
_CORP_CODE_CACHE: dict[str, str] = {}   # {기업명: corp_code}
_TICKER_CACHE: dict[str, str] = {}      # {기업명: 주식코드(6자리)}


def _normalize_account(name: str) -> str | None:
    """계정명 표준화 — 정확한 매칭 우선, 이후 startswith 매칭"""
    name = name.strip()
    if name in ACCOUNT_MAP:
        return ACCOUNT_MAP[name]
    for key, val in ACCOUNT_MAP.items():
        if name.startswith(key):
            return val
    return None


def _validate_and_fix(data: dict) -> dict:
    """재무 데이터 기본 검증 및 보정"""
    # 부채총계 보정: 자산 = 부채 + 자본 (DART 원본 오류 대응)
    if "자산총계" in data and "자본총계" in data:
        expected_liab = data["자산총계"] - data["자본총계"]
        if "부채총계" not in data or data["부채총계"] == data["자산총계"]:
            # 계산 결과가 음수면 데이터 이상 → 그대로 두고 경고
            if expected_liab >= 0:
                data["부채총계"] = expected_liab

    # CAPEX는 현금흐름표에서 음수(유출)로 나오므로 절대값으로 저장
    if "CAPEX" in data:
        data["CAPEX"] = abs(data["CAPEX"])

    return data


def _load_corp_codes() -> dict[str, str]:
    """DART 전체 기업 코드 다운로드 → {기업명: corp_code} 딕셔너리 (런타임 캐시)"""
    global _CORP_CODE_CACHE, _TICKER_CACHE
    if _CORP_CODE_CACHE:
        return _CORP_CODE_CACHE

    print("[DART] 기업 코드 목록 로딩 중...")
    try:
        resp = requests.get(
            f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": DART_API_KEY},
            timeout=60,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[DART] 기업 코드 로딩 실패: {e}")
        return {}

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            with zf.open("CORPCODE.xml") as f:
                tree = ET.parse(f)
    except Exception as e:
        print(f"[DART] ZIP 파싱 실패: {e}")
        return {}

    for item in tree.getroot().findall("list"):
        name = item.findtext("corp_name", "")
        stock = item.findtext("stock_code", "").strip()  # 공백 제거 — 비상장사 오인 방지
        code = item.findtext("corp_code", "")
        if name and stock and code:  # 상장사만 (stock_code가 실제로 있는 경우)
            _CORP_CODE_CACHE[name] = code
            _TICKER_CACHE[name] = stock

    print(f"[DART] 기업 코드 로딩 완료: {len(_CORP_CODE_CACHE)}개")
    return _CORP_CODE_CACHE


def get_corp_code(company_name: str) -> str | None:
    """기업명으로 DART corp_code 조회"""
    return _load_corp_codes().get(company_name)


def get_stock_ticker(company_name: str) -> str | None:
    """기업명으로 KRX 6자리 주식코드 조회"""
    _load_corp_codes()  # _TICKER_CACHE 동시 로드
    return _TICKER_CACHE.get(company_name)


def _get_year_end_price(ticker: str, year: int) -> float | None:
    """해당 연도 마지막 거래일 종가 (FinanceDataReader)"""
    try:
        df = fdr.DataReader(ticker, f"{year}-12-01", f"{year}-12-31")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        print(f"  [FDR 오류] {ticker} {year}년: {e}")
        return None


def _get_price_near_date(ticker: str, target_date: datetime.date) -> float | None:
    """지정 날짜 이전 가장 가까운 거래일의 종가 (최대 10거래일 소급)"""
    try:
        start = target_date - datetime.timedelta(days=14)
        df = fdr.DataReader(ticker, start.strftime("%Y-%m-%d"), target_date.strftime("%Y-%m-%d"))
        return float(df["Close"].iloc[-1]) if not df.empty else None
    except Exception as e:
        print(f"  [FDR 오류] {ticker} {target_date}: {e}")
        return None


def get_market_data(company_name: str, years: list[int] | None = None) -> dict:
    """
    기업명 → 연도별 연말 종가 반환 (FinanceDataReader)

    반환 형태:
    {
        2024: {"price": 53200.0},  # 원
        2023: {"price": 73400.0},
        ...
    }
    PER·PBR 계산은 kpi_engine에서 EPS와 결합하여 수행
    """
    ticker = get_stock_ticker(company_name)
    if not ticker:
        print(f"[FDR] '{company_name}' 티커를 찾을 수 없습니다.")
        return {}

    if years is None:
        now = datetime.date.today()
        latest_year = now.year - 1 if now.month >= 4 else now.year - 2
        years = list(range(latest_year, latest_year - 5, -1))

    result = {}
    for year in years:
        price = _get_year_end_price(ticker, year)
        if price is None:
            print(f"  [{company_name}] {year}년 주가 없음")
            continue
        result[year] = {"price": price}

    return result


def get_current_market_data(company_name: str) -> dict:
    """
    현재 주가 + 1개월/3개월/6개월 등락률 반환

    반환 형태:
    {
        "current_price": 53200.0,  # 원
        "change_1m": 3.5,          # 1개월 등락률 (%)
        "change_3m": -2.1,         # 3개월 등락률 (%)
        "change_6m": 8.7,          # 6개월 등락률 (%)
    }
    주가 데이터 없으면 빈 dict {} 반환
    """
    ticker = get_stock_ticker(company_name)
    if not ticker:
        return {}

    today = datetime.date.today()
    current_price = _get_price_near_date(ticker, today)
    if current_price is None:
        print(f"[FDR] '{company_name}' 현재 주가를 가져올 수 없습니다.")
        return {}

    result: dict = {"current_price": current_price}

    for months, key in [(1, "change_1m"), (3, "change_3m"), (6, "change_6m")]:
        past_date  = today - datetime.timedelta(days=months * 30)
        past_price = _get_price_near_date(ticker, past_date)
        if past_price and past_price > 0:
            result[key] = round((current_price - past_price) / past_price * 100, 2)
        else:
            result[key] = None

    return result


def _fetch_statements(corp_code: str, year: int, fs_div: str) -> pd.DataFrame:
    """DART fnlttSinglAcntAll API 호출 — 타임아웃·에러 시 빈 DataFrame 반환"""
    try:
        resp = requests.get(
            f"{DART_BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",  # 사업보고서
                "fs_div": fs_div,
            },
            timeout=30,
        )
        data = resp.json()
    except Exception as e:
        print(f"  [API 오류] {year}년 {fs_div}: {e}")
        return pd.DataFrame()

    if data.get("status") != "000" or not data.get("list"):
        return pd.DataFrame()
    return pd.DataFrame(data["list"])


def get_financials(company_name: str, years: int = 5) -> dict:
    """
    기업명 입력 → 최근 N개년 재무 데이터 반환

    반환 형태:
    {
        2024: {"매출액": int, "영업이익": int, ...},  # 단위: 백만원
        2023: {...},
        ...
    }
    기업명이 없거나 데이터 수집 실패 시 빈 dict {} 반환
    """
    corp_code = get_corp_code(company_name)
    if not corp_code:
        print(f"[DART] '{company_name}' corp_code를 찾을 수 없습니다.")
        return {}

    # 직전 연도 기준 — 사업보고서는 3~4월에 공시되므로 5월 이후면 전년도 이용 가능
    now = datetime.date.today()
    latest_year = now.year - 1 if now.month >= 4 else now.year - 2
    result = {}

    for year in range(latest_year, latest_year - years, -1):
        # 연결재무제표 우선, 없으면 개별재무제표
        df = _fetch_statements(corp_code, year, "CFS")
        if df.empty:
            df = _fetch_statements(corp_code, year, "OFS")
        if df.empty:
            print(f"  [{company_name}] {year}년 데이터 없음")
            continue

        # 후보값 수집: {account: [val1, val2, ...]}
        candidates: dict[str, list[int]] = {}
        for _, row in df.iterrows():
            sj_div = str(row.get("sj_div", ""))
            allowed = SJ_ACCOUNT_MAP.get(sj_div, set())
            if not allowed:
                continue
            account = _normalize_account(str(row.get("account_nm", "")))
            if not account or account not in allowed:
                continue
            raw = str(row.get("thstrm_amount", "")).replace(",", "").strip()
            if not raw or raw in ("-", ""):
                continue
            try:
                if account in PER_SHARE_ACCOUNTS:
                    value = int(raw)          # 원/주 — 단위 변환 없음
                else:
                    value = int(raw) // 1_000_000  # 원 → 백만원
                candidates.setdefault(account, []).append(value)
            except ValueError:
                continue

        # IS 계정은 MAX(abs) — 집계값의 절대값이 서브항목보다 항상 크므로 양/음수 모두 정확
        # BS·CF 계정은 첫 번째 값 사용 (집계항목이 먼저 등장)
        # EPS는 IS에 속하므로 MAX(abs) 적용 — 하위 EPS 항목 오인 방지
        year_data = {}
        for account, values in candidates.items():
            if account in IS_ACCOUNTS or account in PER_SHARE_ACCOUNTS:
                year_data[account] = max(values, key=abs)
            else:
                year_data[account] = values[0]

        if year_data:
            result[year] = _validate_and_fix(year_data)

    return result


def _ecos_annual(stat_code: str, item_code: str, start: int, end: int) -> dict[int, float]:
    """ECOS StatisticSearch 연간 데이터 → {year: value} 딕셔너리"""
    row_count = max(end - start + 1, 1)   # 요청 연도 수만큼 동적 산정
    try:
        url = (
            f"{ECOS_BASE}/{ECOS_API_KEY}/json/kr/1/{row_count}"
            f"/{stat_code}/A/{start}/{end}/{item_code}"
        )
        resp = requests.get(url, timeout=15)
        rows = resp.json().get("StatisticSearch", {}).get("row", [])
    except Exception as e:
        print(f"  [ECOS 오류] {stat_code}/{item_code}: {e}")
        return {}
    result = {}
    for row in rows:
        try:
            result[int(row["TIME"])] = float(row["DATA_VALUE"])
        except (KeyError, ValueError):
            continue
    return result


def get_macro_data(years: list[int] | None = None) -> dict:
    """
    한국 거시 지표 수집 — ECOS(기준금리·국고채10년물) + FDR(USD/KRW 연말 종가)

    반환 형태:
    {
        2024: {"base_rate": 3.0, "ktb10y": 3.218, "usd_krw": 1472.8},
        2023: {...},
        ...
    }
    base_rate: 연말 기준금리 (%), ktb10y: 국고채 10년물 연평균 수익률 (%), usd_krw: 연말 환율 (원)
    """
    if years is None:
        now = datetime.date.today()
        latest_year = now.year - 1 if now.month >= 4 else now.year - 2
        years = list(range(latest_year, latest_year - 5, -1))

    start, end = min(years), max(years)

    stat_code_br, _, item_code_br = _ECOS_BASE_RATE
    stat_code_kb, _, item_code_kb = _ECOS_KTB10Y

    base_rates = _ecos_annual(stat_code_br, item_code_br, start, end)
    ktb10y     = _ecos_annual(stat_code_kb, item_code_kb, start, end)

    result = {}
    for year in years:
        # USD/KRW: FDR 연말 마지막 거래일 종가
        try:
            df_fx = fdr.DataReader("USD/KRW", f"{year}-12-01", f"{year}-12-31")
            usd_krw = float(df_fx["Close"].iloc[-1]) if not df_fx.empty else None
        except Exception as e:
            print(f"  [FDR 환율 오류] {year}년: {e}")
            usd_krw = None

        entry: dict = {}
        if year in base_rates:
            entry["base_rate"] = base_rates[year]
        if year in ktb10y:
            entry["ktb10y"] = ktb10y[year]
        if usd_krw is not None:
            entry["usd_krw"] = round(usd_krw, 2)

        # KOSPI(KS11), NASDAQ(IXIC) 연말 종가
        for idx_ticker, idx_key in [("KS11", "kospi"), ("IXIC", "nasdaq")]:
            try:
                df_idx = fdr.DataReader(idx_ticker, f"{year}-12-01", f"{year}-12-31")
                val = float(df_idx["Close"].iloc[-1]) if not df_idx.empty else None
            except Exception as e:
                print(f"  [FDR 지수 오류] {idx_ticker} {year}년: {e}")
                val = None
            if val is not None:
                entry[idx_key] = round(val, 2)

        if entry:
            result[year] = entry

    return result


def get_naver_search_trend(keyword: str, start_date: str, end_date: str) -> dict:
    """
    네이버 데이터랩 검색 트렌드 API (Week 3 구현 예정)

    Args:
        keyword: 검색 키워드 (기업명 또는 브랜드명)
        start_date: "YYYY-MM-DD" 형식
        end_date:   "YYYY-MM-DD" 형식

    반환 형태:
    {
        "YYYY-MM": 검색량_지수,  # 0~100 (상대 지수)
        ...
    }

    API 호출 예시 (Week 3):
        POST https://openapi.naver.com/v1/datalab/search
        Headers: X-Naver-Client-Id, X-Naver-Client-Secret
        Body: {
            "startDate": start_date, "endDate": end_date, "timeUnit": "month",
            "keywords": [{"name": keyword, "param": [keyword]}]
        }
    """
    raise NotImplementedError("get_naver_search_trend: Week 3 구현 예정")


# ── 네이버금융 컨센서스 스크래퍼 ──────────────────────────────────────────────

def _parse_rating_kr(text: str) -> str:
    """한국어 투자의견 → BUY / HOLD / SELL"""
    if any(w in text for w in ["강력매수", "적극매수", "비중확대", "매수"]):
        return "BUY"
    if any(w in text for w in ["매도", "비중축소"]):
        return "SELL"
    return "HOLD"


def _clean_num(text: str) -> float | None:
    """숫자 문자열 정제 → float (쉼표·단위·공백 제거)"""
    if not text:
        return None
    text = text.strip()
    if text in ("-", "N/A", "NA", "n/a", "—", ""):
        return None
    cleaned = re.sub(r"[,\s원배%]", "", text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _naver_soup(ticker: str, target: str | None = None) -> BeautifulSoup | None:
    """네이버금융 coinfo 페이지 요청 → BeautifulSoup"""
    params: dict = {"code": ticker}
    if target:
        params["target"] = target
    try:
        resp = requests.get(NAVER_FINANCE_BASE, params=params,
                            headers=_NAVER_HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or "euc-kr"
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [Naver] 요청 실패 (target={target}): {e}")
        return None


_WISEREPORT_BASE = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"


def _wisereport_text(ticker: str) -> str:
    """WiseReport 기업개요 페이지 텍스트 반환"""
    try:
        resp = requests.get(
            _WISEREPORT_BASE, params={"cmp_cd": ticker},
            headers=_NAVER_HEADERS, timeout=15,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"  [WiseReport] 요청 실패: {e}")
        return ""


def _parse_opinion(ticker: str) -> dict:
    """
    WiseReport → 투자의견·목표주가·EPS·PER·애널리스트 수 파싱

    페이지 내 컨센서스 블록 형태:
      "추정기관수  {score}  {target_price}  {eps}  {per}  {count}"
    예: "추정기관수 4.04 390,417 42,966 6.81 24"
    """
    result: dict = {}
    text = _wisereport_text(ticker)
    if not text:
        return result

    # 컨센서스 요약 블록 — 목표주가·EPS·PER·기관수 한 번에 파싱
    m = re.search(
        r"추정기관수\s+([\d.]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)\s+(\d+)",
        text,
    )
    if m:
        score        = float(m.group(1))
        target_price = _clean_num(m.group(2))
        forward_eps  = _clean_num(m.group(3))
        forward_per  = float(m.group(4))
        analyst_cnt  = int(m.group(5))

        if target_price:
            result["target_price"]  = target_price
        if forward_eps:
            result["forward_eps"]   = forward_eps
        result["forward_per"]       = forward_per
        result["analyst_count"]     = analyst_cnt
        # 투자의견: 1(강력매도)~5(강력매수) 스케일 → BUY/HOLD/SELL
        result["rating"] = "BUY" if score >= 3.5 else "HOLD" if score >= 2.5 else "SELL"

    return result


def get_naver_consensus(
    company_name: str,
    year: int | None = None,
    prev_revenue_mil: int | None = None,
) -> dict:
    """
    네이버금융 컨센서스 자동 수집 — 기업명만 넣으면 자동으로 가져옴

    Args:
        company_name    : 기업명 (한국어)
        year            : 예상 연도 (None이면 올해+1 자동 설정)
        prev_revenue_mil: 전년도 실제 매출액 (백만원) — expected_revenue_growth 계산용
                          get_financials() 결과의 최근 연도 "매출액" 값을 넘기면 됨

    반환 형태:
    {
        "company": "삼성전자",
        "year": 2025,
        "target_price": 82000.0,          # 원
        "rating": "BUY",
        "analyst_count": 32,
        "forward_eps": 4850.0,            # 원/주
        "forward_per": 11.2,              # 배
        "expected_revenue_growth": 8.5,   # % (prev_revenue_mil 제공 시)
        "expected_op_margin": 15.2,       # %
        "expected_net_income": 26800000,  # 백만원
    }
    스크래핑 실패 항목은 키 자체가 없음 (None 아닌 absent)
    """
    ticker = get_stock_ticker(company_name)
    if not ticker:
        print(f"[Consensus] '{company_name}' 티커 없음")
        return {}

    if year is None:
        today = datetime.date.today()
        # 4월 이후면 전년도 실적 공시 완료 → 당해 연도가 forward
        latest_actual = today.year - 1 if today.month >= 4 else today.year - 2
        year = latest_actual + 1

    print(f"[Consensus] {company_name} ({ticker}) {year}E 수집 중...")

    result: dict = {"company": company_name, "year": year}
    result.update(_parse_opinion(ticker))

    found = [k for k, v in result.items() if k not in ("company", "year")]
    print(f"  수집 항목: {found if found else '없음 — 페이지 구조 확인 필요'}")
    return result


def parse_consensus_csv(filepath: str, company_name: str | None = None) -> dict:
    """
    consensus_template.csv 파싱 → {year: {field: value}} 딕셔너리

    Args:
        filepath    : CSV 파일 경로
        company_name: 기업명 필터 (None이면 첫 번째 기업 데이터 반환)
                      CSV에 여러 기업이 있으면 반드시 지정 필요

    CSV 컬럼:
      company, year, forward_eps, forward_per, target_price,
      expected_revenue_growth, expected_op_margin, expected_net_income,
      rating, analyst_count

    반환 형태:
    {
        2026: {
            "forward_eps": 42966.0,
            "target_price": 390417.0,
            "rating": "BUY",
            "analyst_count": 24,
            ...
        }
    }
    빈 셀은 해당 키를 포함하지 않음
    """
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"[Consensus] CSV 파싱 실패: {e}")
        return {}

    # company_name 필터 적용
    if company_name:
        df = df[df["company"] == company_name]
    elif "company" in df.columns and df["company"].nunique() > 1:
        first = df["company"].iloc[0]
        print(f"[Consensus] company_name 미지정 — '{first}' 데이터 사용 (총 {df['company'].nunique()}개 기업)")
        df = df[df["company"] == first]

    numeric_cols = [
        "forward_eps", "forward_per", "target_price",
        "expected_revenue_growth", "expected_op_margin", "expected_net_income",
    ]
    result: dict = {}
    for _, row in df.iterrows():
        year_raw = row.get("year")
        if pd.isna(year_raw):
            continue
        year = int(year_raw)
        entry: dict = {}
        for col in numeric_cols:
            val = row.get(col)
            if pd.notna(val):
                entry[col] = float(val)
        rating = row.get("rating")
        if pd.notna(rating):
            entry["rating"] = str(rating).strip().upper()
        count = row.get("analyst_count")
        if pd.notna(count):
            entry["analyst_count"] = int(count)
        if entry:
            result[year] = entry

    return result


if __name__ == "__main__":
    companies = ["삼성전자", "농심", "에이피알"]
    for company in companies:
        print(f"\n{'='*50}")
        print(f"[{company}] 재무 데이터 수집 중...")
        data = get_financials(company)
        if not data:
            print("  데이터 없음")
            continue
        for year, metrics in sorted(data.items()):
            print(f"  {year}년:")
            for k, v in metrics.items():
                print(f"    {k}: {v:,} 백만원")

    print("\n" + "="*50)
    print("[시장 데이터 테스트]")
    for company in companies:
        print(f"\n[{company}] 주가 수집 중...")
        mkt = get_market_data(company)
        if not mkt:
            print("  데이터 없음")
            continue
        for year, d in sorted(mkt.items()):
            print(f"  {year}년: 연말 종가 {d['price']:,.0f}원")

    print("\n" + "="*50)
    print("[현재 시장 데이터 테스트]")
    for company in companies:
        print(f"\n[{company}] 현재 주가 수집 중...")
        curr = get_current_market_data(company)
        if not curr:
            print("  데이터 없음")
            continue
        print(f"  현재 주가: {curr['current_price']:,.0f}원")
        for key, label in [("change_1m", "1M"), ("change_3m", "3M"), ("change_6m", "6M")]:
            val = curr.get(key)
            if val is None:
                print(f"  {label}: N/A")
            else:
                sign = "+" if val > 0 else ""
                print(f"  {label}: {sign}{val:.2f}%")

    print("\n" + "="*50)
    print("[거시 데이터 테스트]")
    macro = get_macro_data()
    for year, d in sorted(macro.items()):
        print(f"  {year}년: 기준금리={d.get('base_rate')}% | "
              f"국고채10Y={d.get('ktb10y')}% | "
              f"USD/KRW={d.get('usd_krw')}원 | "
              f"KOSPI={d.get('kospi')} | NASDAQ={d.get('nasdaq')}")

    print("\n" + "="*50)
    print("[컨센서스 스크래핑 테스트]")
    for company in companies:
        fin = get_financials(company, years=1)
        prev_rev = None
        if fin:
            latest_year = max(fin.keys())
            prev_rev = fin[latest_year].get("매출액")
        print(f"\n[{company}]")
        result = get_naver_consensus(company, prev_revenue_mil=prev_rev)
        for k, v in result.items():
            if k in ("company", "year"):
                continue
            print(f"  {k}: {v}")
