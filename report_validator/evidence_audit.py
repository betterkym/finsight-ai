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


def _signed_eok(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:+,.0f}억원"


def _shares(value) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    return f"{number:,.0f}주"


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
            "항목": "목표가 편차",
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
            "항목": "발행 이후 괴리",
            "배점": "30점",
            "점수": _score_label(axes["time"]),
            "차감": _deduction_label(axes["time"]),
            "정량 근거": (
                f"발행일 주가 {_won(timeline.get('price_at_pub'))}, "
                f"현재가 {_won(company.get('current_price'))}, "
                f"발행 후 {timeline.get('elapsed')}일, "
                f"발행 이후 수익률 {_pct(timeline.get('realized'))}, "
                f"목표가까지 남은 여력 {_pct(timeline.get('remaining'))}, "
                f"{timeline.get('supply_basis') or '외국인 누적 순매수 ' + _signed_eok(timeline.get('foreign_net'))}."
            ),
            "판정 로직": axes["time"].get("reason", ""),
        },
        {
            "항목": "필요 실적",
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


def build_scoring_rulebook(analysis: dict) -> list[dict]:
    """Explain the score weights and point deductions in user-facing language."""
    content = analysis.get("report_content_assessment") or {}
    return [
        {
            "구분": "목표가 편차",
            "배점": "30점",
            "비중 설명": "목표가가 시장 평균보다 크게 높으면 리포트 결론에 더 강한 근거가 필요합니다. 단, 평균보다 높다는 사실만으로 틀렸다고 볼 수는 없어 30점으로 둡니다.",
            "차감 기준": "평균권 z≤0.5는 30점, 0.5<z≤1.0은 22점, 1.0<z≤1.5는 14점, z>1.5는 7점입니다.",
            "현재 적용": _score_label((analysis["verdict"]["axes"]).get("space", {})),
        },
        {
            "구분": "발행 이후 괴리",
            "배점": "30점",
            "비중 설명": "리포트는 발행일의 판단입니다. 이후 주가·수급·공시가 다르게 움직이면 목표가가 맞아도 바로 신뢰하기 어렵습니다.",
            "차감 기준": "발행 30일 초과 -3점, 60일 초과 -6점, 90일 초과 -10점, 매수 의견과 반대 수급 -10점, 상승여력 70% 이상 소진 -5점입니다.",
            "현재 적용": _score_label((analysis["verdict"]["axes"]).get("time", {})),
        },
        {
            "구분": "필요 실적",
            "배점": "40점",
            "비중 설명": "목표가는 결국 앞으로 벌 이익의 함수라서 가장 큰 비중을 둡니다. 숫자로 달성 불가능하면 리포트 결론의 설득력이 크게 낮아집니다.",
            "차감 기준": "과거 범위 안이면 40점, 필요 성장이 보통 해의 2배 이하면 28점, 4배 이하면 18점, 4배 초과는 10점, 과거 최대치 초과는 4점입니다. 실적 변동성이 매우 크면 추가 -4점입니다.",
            "현재 적용": _score_label((analysis["verdict"]["axes"]).get("logic", {})),
        },
        {
            "구분": "본문 의견 검증",
            "배점": "객관분석 추가 차감",
            "비중 설명": "PDF 본문은 목표가 숫자의 배경을 담고 있습니다. 여러 리포트가 같은 이야기를 하더라도 실제 데이터로 덜 확인되면 최종 신뢰도에서 별도로 낮춰 봅니다.",
            "차감 기준": "리포트끼리 해석이 갈리는 논점은 논점당 -2점(최대 -4점), 본문에서 좋게 본 부분이 DART·주가·수급으로 덜 확인되는 논점은 논점당 -3점(최대 -8점), 전체 최대 -10점입니다.",
            "현재 적용": "본문 미반영" if content.get("score") is None else f"-{content.get('penalty', 0)}점",
        },
        {
            "구분": "FinSight 객관분석",
            "배점": "최종 추가 차감",
            "비중 설명": "기존 애널리스트 워크벤치의 재무 이상징후, 현금흐름, 수급 괴리 신호를 리포트 신뢰도 관점으로 바꿔 반영합니다.",
            "차감 기준": "High 이상징후 -6점, 일반 이상징후 -3점, FCF(잉여현금흐름) 마진 음수 -5점, CFO 마진 음수 -4점, 가격·수급 괴리 -3점 등입니다. 본문 의견 검증까지 합쳐 최대 -24점으로 제한합니다.",
            "현재 적용": f"-{(analysis['verdict'].get('alignment') or {}).get('penalty', 0)}점",
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
            "자료": "리포트 본문 의견",
            "출처": "업로드 PDF 텍스트",
            "확인값": (
                f"분석 논점 {len((analysis.get('report_content') or {}).get('theme_rows', []) or [])}개, "
                f"본문 검증 {(analysis.get('report_content_assessment') or {}).get('label', '미반영')}"
            ),
            "점수 연결": "본문 의견 검증 탭과 FinSight 객관분석 추가 차감에 사용합니다.",
        },
        {
            "자료": "증권사 목표가 평균",
            "출처": "네이버 금융 목표가 평균",
            "확인값": f"평균 목표가 {_won(dist.get('mean'))}, 투자의견 {consensus.get('opinion_label', '')}, 기준일 {consensus.get('create_date', '')}",
            "점수 연결": "목표가 편차 30점 산정에 사용합니다.",
        },
        {
            "자료": "DART 재무",
            "출처": "OpenDART 분기 재무제표",
            "확인값": f"최근 분기 {latest_period}, 발행주식수 {_shares(company.get('shares_outstanding'))}",
            "점수 연결": "EPS 역산, 재무 이상징후, 현금 전환 평가에 사용합니다.",
        },
        {
            "자료": "주가·수급",
            "출처": "KRX/pykrx 및 현재가 수집값",
            "확인값": f"발행일 주가 {_won(timeline.get('price_at_pub'))}, 현재가 {_won(company.get('current_price'))}, {timeline.get('supply_basis') or '외국인 ' + _signed_eok(timeline.get('foreign_net'))}",
            "점수 연결": "발행 이후 괴리 30점과 주가 괴리 해석에 사용합니다.",
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
            "점수 연결": "목표가 편차 외의 축은 데모 계산이므로 실제 평가 신뢰도가 낮습니다.",
        })
    return rows


def build_data_source_logic(analysis: dict) -> list[dict]:
    """Return the data flow behind the report-trust workflow."""
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
            "검증 단계": "리포트 기준값",
            "확인 항목": "증권사, 발행일, 투자의견, 목표가, 원문 링크 또는 업로드 PDF",
            "자료": "네이버 금융 리서치 목록 + 업로드 PDF + 사용자 입력",
            "분석 연결": "전체 검증의 시작점입니다. 목표가·발행일이 바뀌면 이후 괴리와 필요 실적 계산도 함께 달라집니다.",
            "반영 상태": f"업로드 PDF {len(report_batch)}개 반영" if report_batch else ("목록 연결" if report.get("pdf_url") else "직접 입력"),
        },
        {
            "검증 단계": "본문 의견",
            "확인 항목": "PDF 본문에서 반복되는 실적·마진·수급·현금흐름 관련 문장",
            "자료": "업로드 PDF 텍스트 추출",
            "분석 연결": "본문 의견을 리포트끼리 비교하고 DART·주가·수급과 대조해 객관분석 차감에 반영합니다.",
            "반영 상태": f"본문 논점 {len((analysis.get('report_content') or {}).get('theme_rows', []) or [])}개",
        },
        {
            "검증 단계": "목표가 편차",
            "확인 항목": "증권사 목표가 평균과 투자의견 평균",
            "자료": "네이버 금융 목표가 평균",
            "분석 연결": "단일 리포트 목표가가 시장 평균권인지, 평균보다 높게 튄 값인지 확인해 30점 축에 반영합니다.",
            "반영 상태": "연결" if analysis.get("consensus") else "미연결",
        },
        {
            "검증 단계": "필요 실적",
            "확인 항목": "분기 재무제표, EPS, 매출·이익·마진, CFO/FCF, 발행주식수",
            "자료": "OpenDART API",
            "분석 연결": "목표가를 EPS 성장률로 역산하고, 과거 실적 범위와 재무 이상징후를 함께 대조합니다.",
            "반영 상태": "데모 재무 사용" if analysis.get("is_demo_financials") else ("연결" if dc.DART_API_KEY else "DART_API_KEY 필요"),
        },
        {
            "검증 단계": "발행 이후 공시",
            "확인 항목": "발행 이후 공시, 지분공시, 주요주주 변동",
            "자료": "OpenDART 공시·대량보유 보고",
            "분석 연결": "리포트 발행일 이후 전제 변화와 수급 해석을 발행 이후 괴리 축에 반영합니다.",
            "반영 상태": f"공시 {len(context.get('disclosures', []) or [])}건 · 지분공시 {len(context.get('ownership', []) or [])}건",
        },
        {
            "검증 단계": "주가·수급",
            "확인 항목": "발행일 주가, 현재가, 기간 수익률, 외국인·기관 수급",
            "자료": "FinanceDataReader/KRX 가격 + pykrx/KRX 수급",
            "분석 연결": "실적 문제와 수급 문제를 분리해 발행 이후 괴리와 주가 괴리 해석에 반영합니다.",
            "반영 상태": status("KRX investor flow", "가격은 연결 · 상세 수급은 KRX_ID/KRX_PW 필요"),
        },
        {
            "검증 단계": "외부 이슈",
            "확인 항목": "발행 이후 관련 뉴스, 블로그·시장 해석, 이슈 키워드",
            "자료": "Naver Search API",
            "분석 연결": "확정 근거가 아니라 주가 괴리나 비용·수요 변화의 원인 후보로만 붙입니다.",
            "반영 상태": "연결" if (dc.NAVER_CLIENT_ID and dc.NAVER_CLIENT_SECRET) else "NAVER_CLIENT_ID/SECRET 필요",
        },
        {
            "검증 단계": "거시·원가 보조",
            "확인 항목": "환율, 원재료 proxy, 국내외 물가·성장률",
            "자료": "FRED, World Bank, ECOS",
            "분석 연결": "원가율·해외 매출·할인율 변화가 회사 숫자에 주는 압력을 보조 해석으로 붙입니다.",
            "반영 상태": f"FRED {status('FRED', 'FRED_API_KEY 필요')} / World Bank {status('World Bank', '무키 연결 시도')} / ECOS {'연결' if dc.ECOS_API_KEY else 'ECOS_API_KEY 필요'}",
        },
        {
            "검증 단계": "산업 세부 데이터",
            "확인 항목": "산업 소비통계, 원재료 가격, HS코드 수출입 물량",
            "자료": "KOSIS, KAMIS, Trading Economics, UN Comtrade/KATI",
            "분석 연결": "제품·지역별 매출이나 원가 원인을 DART보다 더 아래 단계에서 검증하는 확장 후보입니다.",
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
            "판단": event.get("impact") or "리포트 발행 이후 확인된 항목입니다. 목표가·의견이 여전히 유효한지 최신화해야 합니다.",
            "근거": event.get("detail", ""),
            "점수 영향": "발행 이후 괴리 근거",
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
