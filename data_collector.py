import os
import io
import zipfile
import datetime
import requests
import pandas as pd
import xml.etree.ElementTree as ET
import FinanceDataReader as fdr
from dotenv import load_dotenv

load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY")
DART_BASE = "https://opendart.fss.or.kr/api"

ECOS_API_KEY = os.getenv("ECOS_API_KEY")
ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

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
    print("[거시 데이터 테스트]")
    macro = get_macro_data()
    for year, d in sorted(macro.items()):
        print(f"  {year}년: 기준금리={d.get('base_rate')}% | "
              f"국고채10Y={d.get('ktb10y')}% | "
              f"USD/KRW={d.get('usd_krw')}원")
