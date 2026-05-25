"""
report_generator.py — LLM 기반 Analyst Report 생성 + fpdf2 PDF 출력 (Week 4 구현)

입력:
  company   : str                        — 기업명
  financials: dict                       — data_collector.get_financials() 결과
  kpis      : dict                       — kpi_engine.calculate_kpis() 결과
  analysis  : dict                       — signal_engine.run_full_analysis() 결과
  mode      : str                        — "beginner" | "analyst" | "screening"

출력:
  report_text: str    — 마크다운 형식 리포트
  pdf_path   : str    — 저장된 PDF 경로 (export_pdf 호출 시)

─────────────────────────────────────────────────────────────────────────────
리포트 모드:
  beginner   — 비전문가 대상. 비유·쉬운 설명 위주. 용어 해설 포함.
  analyst    — IB/PE 애널리스트 대상. 지표 근거 + 판단 + What to Watch Next.
  screening  — 투자 스크리닝 대상. Bull/Bear case + 핵심 리스크 + 액션 아이템.

리포트 섹션 구조 (analyst 모드 기준):
  1. Executive Summary          — 기업 개요 + 핵심 메시지 3줄
  2. Financial Performance      — 수익성·성장성·현금흐름 해석
  3. Valuation Analysis         — PER/PBR/PSR + 업종 비교 맥락
  4. Financial Signal Summary   — Signal Engine 결과 해석
  5. Conflict & Risk Flags      — Conflict Engine 결과
  6. Company Archetype          — 분류 근거 설명
  7. Macro Exposure             — 금리·환율 민감도
  8. Evidence Level             — High/Medium/Low/Needs Review + Confidence Score
  9. What to Watch Next         — 다음 분기 모니터링 포인트

LLM 모델: claude-haiku-4-5 (비용 정책)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_MODEL = "claude-haiku-4-5"  # 절대 변경 금지

REPORT_MODES = ("beginner", "analyst", "screening")


# ── LLM 클라이언트 (Week 4 활성화) ────────────────────────────────────────────

def _get_client():
    """Anthropic 클라이언트 반환 — API 키 없으면 RuntimeError"""
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError("anthropic 패키지가 설치되지 않았습니다: pip install anthropic") from e
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다.")
    return Anthropic(api_key=ANTHROPIC_API_KEY)


# ── 공개 API ──────────────────────────────────────────────────────────────────

def generate_report(
    company: str,
    financials: dict,
    kpis: dict,
    analysis: dict,
    mode: str = "analyst",
) -> str:
    """
    구조화된 재무 데이터 → LLM Analyst Report (마크다운)

    Args:
        company   : 기업명 (한국어)
        financials: {year: {"매출액": int, ...}} — 단위 백만원
        kpis      : {year: {"OPM": float, ...}}
        analysis  : signal_engine.run_full_analysis() 반환값
                    {"signals": [...], "conflicts": [...], "archetype": str,
                     "macro_exposure": dict, "evidence": dict}
        mode      : "beginner" | "analyst" | "screening"

    반환: 마크다운 형식 리포트 문자열

    구현 시 주의 (Week 4):
      - LLM에게 숫자 계산을 시키지 말 것 — 이미 계산된 kpis·analysis를 JSON으로 전달
      - 프롬프트에 mode별 tone 지침 포함
      - max_tokens: 2000 (beginner) / 3000 (analyst) / 1500 (screening)
      - JSON output 강제: {"sections": {"executive_summary": "...", ...}}
    """
    if mode not in REPORT_MODES:
        raise ValueError(f"mode는 {REPORT_MODES} 중 하나여야 합니다.")
    raise NotImplementedError("generate_report: Week 4 구현 예정")


def _build_prompt(
    company: str,
    financials: dict,
    kpis: dict,
    analysis: dict,
    mode: str,
) -> str:
    """
    LLM 프롬프트 생성 — structured data → JSON prompt (Week 4 구현)

    프롬프트 전략:
      - System: 역할 정의 (IB analyst / 초보자 가이드 / 스크리닝 전문가)
      - User: 기업명 + JSON 형태 kpis + signals + conflicts + archetype
      - Output format 지정: JSON with section keys

    Rule: LLM은 해석·서술만, 수치 계산은 하지 않음
    """
    raise NotImplementedError("_build_prompt: Week 4 구현 예정")


def export_pdf(
    report_text: str,
    company: str,
    output_dir: str = ".",
) -> str:
    """
    마크다운 리포트 → fpdf2 PDF 파일 생성

    Args:
        report_text: generate_report() 결과 마크다운 문자열
        company    : 기업명 (파일명에 사용)
        output_dir : PDF 저장 디렉토리

    반환: 생성된 PDF 파일 경로

    구현 시 주의 (Week 4):
      - 한국어 폰트 임베딩 필수 (NanumGothic 또는 Malgun Gothic)
      - 섹션별 스타일: 제목 16pt Bold, 본문 10pt Regular
      - 표지: 기업명 + FinSight AI 로고 + 생성일
      - 꼬리말: Evidence Level + Confidence Score
    """
    raise NotImplementedError("export_pdf: Week 4 구현 예정")


def generate_what_to_watch(kpis: dict, signals: list, conflicts: list) -> list[str]:
    """
    다음 분기 모니터링 포인트 생성 (3~5개)

    반환: ["OPM 반등 여부 확인 (다음 분기 실적 발표)", "FCF 전환 가능성 모니터링", ...]
    """
    raise NotImplementedError("generate_what_to_watch: Week 4 구현 예정")


if __name__ == "__main__":
    # Week 4 구현 후 테스트
    # from data_collector import get_financials, get_market_data
    # from kpi_engine import calculate_kpis
    # from signal_engine import run_full_analysis
    #
    # fin   = get_financials("에이피알")
    # mkt   = get_market_data("에이피알", years=list(fin.keys()))
    # kpis  = calculate_kpis(fin, mkt)
    # analysis = run_full_analysis(kpis)
    #
    # report = generate_report("에이피알", fin, kpis, analysis, mode="analyst")
    # pdf_path = export_pdf(report, "에이피알")
    # print(f"PDF 저장: {pdf_path}")
    print("report_generator.py — Week 4 구현 예정")
    print(f"지원 모드: {REPORT_MODES}")
    print(f"LLM 모델: {_MODEL}")
