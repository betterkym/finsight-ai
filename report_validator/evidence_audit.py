"""Evidence and score audit helpers for the report validator."""
from __future__ import annotations

import math

import pandas as pd

from core import data_collector as dc


def _num(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _won(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.0f}원"


def _eok(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number / 100000000:,.0f}억원"


def _pct(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:+.1f}%"


def _score_label(axis: dict) -> str:
    if axis.get("uncounted"):
        return "미집계"
    return f"{axis.get('score')}/{axis.get('max')}점"


def _deduction_label(axis: dict) -> str:
    if axis.get("uncounted"):
        return "감점 없음"
    score = _num(axis.get("score")) or 0
    max_score = _num(axis.get("max")) or 0
    return f"-{max_score - score:.0f}점"


def build_score_audit(analysis: dict) -> list[dict]:
    """Return the exact axis-level scoring evidence shown in the UI/report."""
    verdict = analysis["verdict"]
    report = analysis["report"]
    company = analysis["company"]
    dist = analysis["distribution"]
    timeline = analysis["timeline"]
    reverse = analysis["reverse"]
    axes = verdict["axes"]

    return [
        {
            "항목": "분포 위치",
            "배점": "30점",
            "점수": _score_label(axes["space"]),
            "차감": _deduction_label(axes["space"]),
            "정량 근거": (
                f"리포트 목표가 {_won(report.get('target_price'))}, "
                f"증권사 목표가 평균 {_won(dist.get('mean'))}, "
                f"평균 대비 {_pct(dist.get('vs_median_pct'))}, z={dist.get('z')}. "
                "네이버가 평균 목표가만 제공하므로 표준편차는 목표가 평균의 12%로 추정."
            ),
            "판정 로직": axes["space"].get("reason", ""),
        },
        {
            "항목": "발행 후 변화",
            "배점": "30점",
            "점수": _score_label(axes["time"]),
            "차감": _deduction_label(axes["time"]),
            "정량 근거": (
                f"발행일 주가 {_won(timeline.get('price_at_pub'))}, "
                f"현재가 {_won(company.get('current_price'))}, "
                f"발행 후 {timeline.get('elapsed')}일, "
                f"발행 이후 수익률 {_pct(timeline.get('realized'))}, "
                f"목표가까지 남은 여력 {_pct(timeline.get('remaining'))}, "
                f"외국인 누적 순매수 {timeline.get('foreign_net', 0):+,}억원."
            ),
            "판정 로직": axes["time"].get("reason", ""),
        },
        {
            "항목": "가정 검증",
            "배점": "40점",
            "점수": _score_label(axes["logic"]),
            "차감": _deduction_label(axes["logic"]),
            "정량 근거": (
                f"현재 EPS {_won(reverse.get('current_eps'))}, "
                f"목표가에 필요한 EPS {_won(reverse.get('need_eps'))}, "
                f"필요 성장률 {_pct(reverse.get('need_growth'))}, "
                f"과거 평균 {_pct(reverse.get('avg_growth'))}, "
                f"과거 중앙값 {_pct(reverse.get('median_growth'))}, "
                f"CV {reverse.get('cv')}."
            ),
            "판정 로직": axes["logic"].get("reason", ""),
        },
    ]


def score_formula(analysis: dict) -> dict:
    verdict = analysis["verdict"]
    axes = verdict["axes"]
    counted = [axis for axis in axes.values() if not axis.get("uncounted")]
    raw = sum((axis.get("score") or 0) for axis in counted)
    max_possible = sum((axis.get("max") or 0) for axis in counted)
    base_total = verdict.get("base_total", verdict.get("total", 0))
    penalty = (verdict.get("alignment") or {}).get("penalty", 0)
    final = verdict.get("total", 0)
    return {
        "raw": raw,
        "max_possible": max_possible,
        "base_total": base_total,
        "penalty": penalty,
        "final": final,
        "text": f"기초점수 = ({raw}/{max_possible}) x 100 = {base_total}점, 객관분석 차감 {penalty}점, 최종 {final}점",
    }


def build_source_audit(analysis: dict) -> list[dict]:
    report = analysis["report"]
    report_batch = analysis.get("report_batch") or []
    company = analysis["company"]
    dist = analysis["distribution"]
    consensus = analysis.get("consensus") or {}
    timeline = analysis["timeline"]
    context = analysis.get("context") or {}
    kpis = analysis.get("kpis")
    latest_period = ""
    if kpis is not None and not kpis.empty:
        latest_period = str(kpis.iloc[-1].get("period") or "")

    report_source = "사용자 입력"
    if report.get("file_name") and report.get("pdf_url"):
        report_source = "업로드 PDF + 네이버 금융 리서치 목록 + 사용자 입력"
    elif report.get("file_name"):
        report_source = "업로드 PDF + 사용자 입력"
    elif report.get("pdf_url"):
        report_source = "네이버 금융 리서치 목록 + 사용자가 입력한 목표가"
    report_value = (
        f"{report.get('broker') or '증권사 미입력'} / 발행일 {report.get('pub_date')} / "
        f"목표가 {_won(report.get('target_price'))} / 의견 {report.get('opinion')}"
    )
    if report.get("file_name"):
        report_value += f" / 업로드 {report.get('file_name')}"
    if len(report_batch) > 1:
        report_value += f" / 비교 리포트 {len(report_batch)}개"

    rows = [
        {
            "자료": "검증 리포트",
            "출처": report_source,
            "확인값": report_value,
            "점수 연결": "단일 PDF는 해당 리포트를 기준으로, 여러 PDF는 추출된 목표가의 중앙값을 기준으로 점수를 계산하고 개별 리포트는 비교표에 함께 표시합니다.",
        },
        {
            "자료": "증권사 목표가 평균",
            "출처": "네이버 금융 목표가 평균",
            "확인값": f"평균 목표가 {_won(dist.get('mean'))}, 투자의견 {consensus.get('opinion_label', '')}, 기준일 {consensus.get('create_date', '')}",
            "점수 연결": "분포 위치 30점 산정에 사용합니다.",
        },
        {
            "자료": "DART 재무",
            "출처": "OpenDART 분기 재무제표",
            "확인값": f"최근 분기 {latest_period}, 발행주식수 {company.get('shares_outstanding', 0):,.0f}주",
            "점수 연결": "EPS 역산, 재무 이상징후, 현금 전환 평가에 사용합니다.",
        },
        {
            "자료": "주가·수급",
            "출처": "KRX/pykrx 및 현재가 수집값",
            "확인값": f"발행일 주가 {_won(timeline.get('price_at_pub'))}, 현재가 {_won(company.get('current_price'))}, 외국인 {timeline.get('foreign_net', 0):+,}억원",
            "점수 연결": "발행 후 변화 30점과 주가 괴리 해석에 사용합니다.",
        },
        {
            "자료": "발행 후 공시",
            "출처": "DART 최근 공시·대량보유 보고",
            "확인값": f"공시 {len(context.get('disclosures', []) or [])}건, 지분공시 {len(context.get('ownership', []) or [])}건",
            "점수 연결": "리포트 발행 이후 새로 확인된 변화와 수급 해석에 사용합니다.",
        },
        {
            "자료": "외부 정황",
            "출처": "뉴스·블로그·리서치 참고 라이브러리",
            "확인값": f"뉴스 {len(context.get('news', []) or [])}건, 블로그 {len(context.get('blogs', []) or [])}건",
            "점수 연결": "원인 후보를 설명하는 보조 근거입니다. 점수 차감은 DART·주가·수급 근거를 우선합니다.",
        },
    ]
    if analysis.get("is_demo_financials"):
        rows.append({
            "자료": "데모 재무 폴백",
            "출처": "내장 데모 데이터",
            "확인값": "실제 DART 재무 수집 실패로 데모 재무를 사용했습니다.",
            "점수 연결": "분포 위치 외의 축은 데모 계산이므로 실제 평가 신뢰도가 낮습니다.",
        })
    return rows


def build_data_source_logic(analysis: dict) -> list[dict]:
    """Explain why each data source belongs in the report-trust workflow."""
    report = analysis.get("report", {})
    report_batch = analysis.get("report_batch") or []
    context = analysis.get("context") or {}
    external = context.get("external_drivers") or {}
    status_by_source = {
        str(row.get("source", "")).lower(): row
        for row in external.get("status_rows", []) or []
    }

    def status(source_key: str, default: str) -> str:
        row = next((value for key, value in status_by_source.items() if source_key.lower() in key), None)
        if not row:
            return default
        connected = "연결" if row.get("connected") else "미연결"
        detail = row.get("detail") or row.get("status") or ""
        return f"{connected} · {detail}"

    return [
        {
            "필수성": "필수",
            "판단 질문": "검증할 리포트의 기준점이 무엇인가",
            "필요한 사실": "증권사, 발행일, 투자의견, 목표가, 원문 링크 또는 업로드 PDF",
            "데이터·도구": "네이버 금융 리서치 목록 + 업로드 PDF + 사용자 입력",
            "쓰는 이유": "이 값들이 기준점이 되어 발행 이후 변화와 목표가 현실성을 계산합니다.",
            "점수·해석 연결": "전체 검증의 시작점. 목표가·발행일을 잘못 넣으면 모든 축의 결과가 달라집니다.",
            "반영 상태": f"업로드 PDF {len(report_batch)}개 반영" if report_batch else ("목록 연결" if report.get("pdf_url") else "직접 입력"),
        },
        {
            "필수성": "필수",
            "판단 질문": "목표가가 시장에서 얼마나 공격적인가",
            "필요한 사실": "증권사 목표가 평균과 투자의견 평균",
            "데이터·도구": "네이버 금융 목표가 평균",
            "쓰는 이유": "단일 리포트 목표가가 시장 평균권인지, 평균보다 높게 튄 값인지 먼저 확인합니다.",
            "점수·해석 연결": "분포 위치 30점. 평균에서 멀수록 목표가에 더 강한 근거가 필요합니다.",
            "반영 상태": "연결" if analysis.get("consensus") else "미연결",
        },
        {
            "필수성": "필수",
            "판단 질문": "목표가를 만드는 실적 가정이 실제 숫자로 가능한가",
            "필요한 사실": "분기 재무제표, EPS, 매출·이익·마진, CFO/FCF, 발행주식수",
            "데이터·도구": "OpenDART API",
            "쓰는 이유": "리포트가 말한 목표가를 EPS 성장률로 역산하고, 과거 실적 범위와 대조합니다.",
            "점수·해석 연결": "가정 검증 40점 + 객관분석 추가 차감. 재무 스캔의 1차 근거입니다.",
            "반영 상태": "데모 재무 사용" if analysis.get("is_demo_financials") else ("연결" if dc.DART_API_KEY else "DART_API_KEY 필요"),
        },
        {
            "필수성": "필수",
            "판단 질문": "리포트 발행 이후 새로 나온 회사 이벤트가 있었나",
            "필요한 사실": "발행 이후 공시, 지분공시, 주요주주 변동",
            "데이터·도구": "OpenDART 공시·대량보유 보고",
            "쓰는 이유": "리포트 발행일 이후 전제가 바뀌었는지 확인합니다.",
            "점수·해석 연결": "발행 후 변화 30점, 주가 괴리 해석, 객관분석 차감 근거.",
            "반영 상태": f"공시 {len(context.get('disclosures', []) or [])}건 · 지분공시 {len(context.get('ownership', []) or [])}건",
        },
        {
            "필수성": "핵심 보조",
            "판단 질문": "목표가와 현재 주가의 차이가 왜 바로 메워지지 않는가",
            "필요한 사실": "발행일 주가, 현재가, 기간 수익률, 외국인·기관 수급",
            "데이터·도구": "FinanceDataReader/KRX 가격 + pykrx/KRX 수급",
            "쓰는 이유": "실적이 맞아도 수급이 누르면 목표가가 곧바로 주가로 연결되지 않을 수 있습니다.",
            "점수·해석 연결": "발행 후 변화 30점, 주가 괴리 해석. 실적 문제와 수급 문제를 분리합니다.",
            "반영 상태": status("KRX investor flow", "가격은 연결 · 상세 수급은 KRX_ID/KRX_PW 필요"),
        },
        {
            "필수성": "보조",
            "판단 질문": "공시 밖에서 시장이 반응한 이슈가 있었나",
            "필요한 사실": "발행 이후 관련 뉴스, 블로그·시장 해석, 이슈 키워드",
            "데이터·도구": "Naver Search API",
            "쓰는 이유": "뉴스는 확정 근거가 아니라, 주가 괴리나 비용·수요 변화의 원인 후보를 찾기 위한 보조 자료입니다.",
            "점수·해석 연결": "보조 근거. 단독 차감에는 쓰지 않고 DART·주가·수급 근거와 맞을 때만 해석에 붙입니다.",
            "반영 상태": "연결" if (dc.NAVER_CLIENT_ID and dc.NAVER_CLIENT_SECRET) else "NAVER_CLIENT_ID/SECRET 필요",
        },
        {
            "필수성": "보조",
            "판단 질문": "원가·환율·경기 같은 외부 변수 때문에 실적 전제가 흔들렸나",
            "필요한 사실": "환율, 원재료 proxy, 국내외 물가·성장률",
            "데이터·도구": "FRED, World Bank, ECOS",
            "쓰는 이유": "원가율·해외 매출·할인율 변화가 회사 숫자에 어떤 압력을 줬는지 설명합니다.",
            "점수·해석 연결": "현재는 보조 해석. 애널리스트 워크벤치의 가치평가·민감도에서 더 크게 사용합니다.",
            "반영 상태": f"FRED {status('FRED', 'FRED_API_KEY 필요')} / World Bank {status('World Bank', '무키 연결 시도')} / ECOS {'연결' if dc.ECOS_API_KEY else 'ECOS_API_KEY 필요'}",
        },
        {
            "필수성": "확장 후보",
            "판단 질문": "산업 수요·원재료·수출 물량을 더 정밀하게 검증할 수 있나",
            "필요한 사실": "산업 소비통계, 원재료 가격, HS코드 수출입 물량",
            "데이터·도구": "KOSIS, KAMIS, Trading Economics, UN Comtrade/KATI",
            "쓰는 이유": "제품·지역별 매출이나 원가 원인을 DART보다 더 아래 단계에서 검증하기 위한 확장 데이터입니다.",
            "점수·해석 연결": "현재 점수에는 직접 반영하지 않습니다. 연결 상태와 사용처만 표시하는 확장 후보입니다.",
            "반영 상태": "로드맵 · 키가 있어도 품목/HS코드 매핑 후 반영",
        },
    ]


def build_update_audit(analysis: dict) -> list[dict]:
    verdict = analysis["verdict"]
    timeline = analysis["timeline"]
    rows: list[dict] = []
    for factor in (verdict.get("alignment") or {}).get("factors", []):
        rows.append({
            "평가 구분": "객관분석 차감",
            "항목": factor.get("title", ""),
            "판단": factor.get("reason", ""),
            "근거": factor.get("evidence", ""),
            "점수 영향": f"-{factor.get('points', 0)}점" if factor.get("points", 0) else "정성 반영",
        })
    for event in timeline.get("events", [])[:6]:
        rows.append({
            "평가 구분": "발행 후 업데이트",
            "항목": f"{event.get('date', '')} · {event.get('type', '')}",
            "판단": "리포트 발행 이후 확인된 항목입니다. 목표가·의견이 여전히 유효한지 최신화해야 합니다.",
            "근거": event.get("detail", ""),
            "점수 영향": "시간축 판단 근거",
        })
    price_action = analysis.get("price_action") or {}
    for item in price_action.get("attribution", [])[:4]:
        rows.append({
            "평가 구분": "주가 괴리 분해",
            "항목": f"{item.get('driver', '')} · {item.get('weight', '')}",
            "판단": item.get("reading", ""),
            "근거": item.get("evidence", ""),
            "점수 영향": "시장 해석·객관분석 차감 보조",
        })
    if not rows:
        rows.append({
            "평가 구분": "객관분석",
            "항목": "큰 충돌 제한",
            "판단": "현재 연결된 데이터에서는 리포트 결론을 크게 흔드는 항목이 제한적입니다.",
            "근거": "FinSight 스캔",
            "점수 영향": "차감 없음",
        })
    return rows


def build_kpi_snapshot(analysis: dict, rows: int = 8) -> pd.DataFrame:
    kpis = analysis.get("kpis")
    if kpis is None or kpis.empty:
        return pd.DataFrame()
    columns = [
        "period", "revenue", "operating_profit", "opm", "cfo", "fcf",
        "cfo_margin", "fcf_margin", "receivables", "inventory", "capex",
        "cogs_ratio", "sga_ratio",
    ]
    existing = [column for column in columns if column in kpis.columns]
    frame = kpis[existing].tail(rows).copy()
    rename = {
        "period": "분기",
        "revenue": "매출",
        "operating_profit": "영업이익",
        "opm": "OPM",
        "cfo": "CFO",
        "fcf": "FCF",
        "cfo_margin": "CFO 마진",
        "fcf_margin": "FCF 마진",
        "receivables": "매출채권",
        "inventory": "재고",
        "capex": "CAPEX",
        "cogs_ratio": "원가율",
        "sga_ratio": "판관비율",
    }
    amount_cols = {"revenue", "operating_profit", "cfo", "fcf", "receivables", "inventory", "capex"}
    pct_cols = {"opm", "cfo_margin", "fcf_margin", "cogs_ratio", "sga_ratio"}
    for column in amount_cols & set(frame.columns):
        frame[column] = frame[column].map(_eok)
    for column in pct_cols & set(frame.columns):
        frame[column] = frame[column].map(lambda value: (_pct(value)).replace("+", ""))
    return frame.rename(columns=rename)
