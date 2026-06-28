"""FinSight entry point.

This wrapper keeps the analyst workbench and the retail report validator separate
while giving evaluators a clear first choice.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
APPS = {
    "analyst": ROOT / "analyst_workbench" / "app.py",
    "retail": ROOT / "report_validator" / "app_finsight.py",
}


def _launch(app_key: str) -> None:
    """Run a child Streamlit app without changing the original app files."""
    script = APPS[app_key]
    for path in (script.parent, ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    runpy.run_path(str(script), run_name="__main__")


view = st.query_params.get("view") or "retail"
if view in APPS:
    _launch(view)
    st.stop()


st.set_page_config(page_title="FinSight", page_icon="▦", layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #F7F8FA; color: #17202A; }
    [data-testid="stSidebar"] { display: none; }
    .block-container { max-width: 1180px; padding-top: 48px; }
    .fs-shell { border-top: 4px solid #173B57; padding-top: 28px; }
    .fs-kicker { color: #5C6670; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    .fs-title { font-size: 48px; line-height: 1.08; font-weight: 850; color: #17202A; margin: 8px 0 12px; letter-spacing: 0; }
    .fs-lead { color: #4B5563; font-size: 18px; max-width: 820px; line-height: 1.65; margin-bottom: 28px; }
    .fs-card { background: #FFFFFF; border: 1px solid #DCE2E8; border-radius: 8px; padding: 24px; min-height: 255px; box-shadow: 0 12px 32px rgba(23,32,42,.06); }
    .fs-card h3 { margin: 0 0 8px; font-size: 24px; color: #17202A; letter-spacing: 0; }
    .fs-card p { color: #52606D; line-height: 1.58; margin: 0 0 16px; }
    .fs-tag { display: inline-block; padding: 5px 9px; border-radius: 6px; background: #EEF3F7; color: #173B57; font-size: 12px; font-weight: 750; margin-bottom: 14px; }
    .fs-list { color: #334155; font-size: 14px; line-height: 1.85; margin-top: 12px; }
    div.stButton > button { border-radius: 7px; min-height: 46px; font-weight: 800; border: 1px solid #173B57; }
    div.stButton > button[kind="primary"] { background: #173B57; color: white; }
    .fs-flow { margin-top: 28px; padding: 18px 20px; border: 1px solid #DCE2E8; border-radius: 8px; background: #FFFFFF; color: #405060; line-height: 1.7; }
    .fs-nav button { margin-top: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div class='fs-shell'>", unsafe_allow_html=True)
st.markdown("<div class='fs-kicker'>FinSight</div>", unsafe_allow_html=True)
title_col, nav_col = st.columns([4.8, 1.2])
with title_col:
    st.markdown("<div class='fs-title'>증권사 리포트, 지금도 믿어도 될까?</div>", unsafe_allow_html=True)
with nav_col:
    st.markdown("<div class='fs-nav'>", unsafe_allow_html=True)
    if st.button("Analyst Mode", width="stretch"):
        st.query_params["view"] = "analyst"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='fs-lead'>FinSight는 증권사 리포트를 그대로 믿기 전에, DART 재무·공시와 KRX 주가·수급, "
    "증권사 목표가 평균, 업로드 PDF 본문, 발행 이후 공시·뉴스·지분 변동을 한 번 더 대조합니다. "
    "목표가와 투자의견을 어느 정도 신뢰할 수 있는지 점수화하고 현재 주가와의 차이를 해석합니다.</div>",
    unsafe_allow_html=True,
)

col1, col2 = st.columns(2, gap="large")
with col1:
    st.markdown(
        """
        <div class="fs-card">
          <span class="fs-tag">Analyst Mode</span>
          <h3>애널리스트 워크벤치</h3>
          <p>DART 분기 재무를 전수 스캔하고, 이상 탐지부터 원인 추적, 동종기업 비교, 가치평가 모델까지 이어서 봅니다.</p>
          <div class="fs-list">
          재무 수집 → 이상 탐지 → 원인·정황 연결<br>
          동종기업 검증 → DCF·멀티플 교차검증 → 리포트·워크북
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Analyst Mode로 입장", type="primary", width="stretch"):
        st.query_params["view"] = "analyst"
        st.rerun()

with col2:
    st.markdown(
        """
        <div class="fs-card">
          <span class="fs-tag">Report Check</span>
          <h3>리포트 신뢰도 검증</h3>
          <p>증권사 리포트의 목표가, 투자의견, 본문 의견을 DART 재무·공시, KRX 주가·수급, 목표가 평균, 발행 이후 이슈로 다시 대조합니다.</p>
          <div class="fs-list">
          리포트 입력 → 목표가 평균 비교 → 발행 후 주가·수급 확인<br>
          필요 EPS 성장률 역산 → 본문 의견 검증 → 종합 해석 보고서
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("개인투자자용으로 입장", width="stretch"):
        st.query_params["view"] = "retail"
        st.rerun()

st.markdown(
    """
    <div class="fs-flow">
    두 화면은 같은 데이터 엔진을 사용합니다. 워크벤치는 원인 분석과 모델링까지 열고,
    리포트 신뢰도 검증은 개인투자자가 리포트를 읽을 때 필요한 팩트 대조, 점수화, 종합 해석을 먼저 보여줍니다.
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("</div>", unsafe_allow_html=True)
