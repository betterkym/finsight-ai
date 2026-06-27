"""FinSight — 이 리포트, 믿어도 되나?

증권사 리포트의 목표가를 3축으로 검증하는 개인투자자용 도구.
  ① 분포 위치: 다른 증권사와 비교해 목표가가 어디 위치하는가
  ② 발행 후 변화: 발행 후 기업 상황과 주가가 바뀌었는가
  ③ 가정 검증: 목표가를 위해 필요한 성장률이 현실적인가
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime
import pandas as pd
import streamlit as st

from core.kpi_engine import calculate_quarterly_kpis
from core.diagnostics import (
    calculate_multiple_valuation,
    build_valuation_range,
)
from finsight_modules import (
    reverse_engineer_target,
    aggregate_opinions,
    locate_in_distribution,
    locate_vs_consensus,
)
from core.mode_views import build_tracker_table, build_peer_benchmark
from core import data_collector as dc
from timeline_module import build_post_publish_timeline, fetch_foreign_net, fetch_price_at_date
from scoring_module import build_report_verdict
from lib.research_reference import get_research_reference, RESEARCH_LIBRARY
from consensus_crawler import search_company_and_consensus
import demo_data as D


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


st.set_page_config(page_title="FinSight — 리포트 검증", layout="wide")

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


# ──────────────────────────────────────────────
# 사이드바 — 자동 검색 / 직접 입력
# ──────────────────────────────────────────────
st.sidebar.markdown("### 📊 리포트 검증")
st.sidebar.divider()

# 모드 선택
# 분석 입력 (검색/입력 결과를 한 곳에 모음)
ready = False
selected_company = None
selected_target = None
sel_broker = ""
sel_opinion = "매수"
report_date = ""
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
    mean = consensus["price_target_mean"]
    st.sidebar.success(
        f"**{selected_company}**\n\n"
        f"시장 컨센서스 평균 **{mean:,.0f}원**\n\n"
        f"투자의견 {consensus['opinion_label']} · {consensus['create_date']}"
    )

    st.sidebar.markdown("**2️⃣ 검증할 리포트**")
    st.sidebar.caption("검증하려는 증권사 리포트의 목표가를 입력하세요.")
    selected_target = st.sidebar.number_input(
        "목표가 (원)", min_value=0, value=int(mean), step=1000,
        help="기본값은 컨센서스 평균입니다. 특정 리포트 목표가로 바꿔보세요.",
    )
    sel_broker = st.sidebar.text_input("증권사명 (선택)", placeholder="예: 한화투자증권")
    report_date = st.sidebar.date_input("발행일").strftime("%Y-%m-%d")
    sel_opinion = st.sidebar.selectbox("투자의견", ["매수", "중립", "매도"])

    ready = selected_target and selected_target > 0

elif search_result:
    st.sidebar.warning(search_result["message"])
    st.sidebar.caption("종목코드는 찾았으나 증권사 커버리지가 없을 수 있습니다.")

st.sidebar.divider()
st.sidebar.caption("💡 종목 검색 → 컨센서스 평균 확인 → 검증할 목표가 입력")


# ──────────────────────────────────────────────
# 데이터 분석
# ──────────────────────────────────────────────
@st.cache_data(show_spinner="🔬 3축 검증 중...")
def load_analysis(company_name: str, report_date: str, target_price: int,
                  consensus: dict = None, sel_broker: str = "",
                  sel_opinion: str = "매수"):
    """검증할 리포트 목표가 기반 3축 검증.

    실제 DART 재무 수집을 우선하고, 실패 시 농심 데모로 폴백한다.
    ①축은 네이버 컨센서스 평균 대비 위치로 판단한다.
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
        post_events = []  # 실데이터 이벤트는 다음 단계(공시 연동)에서
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

    # ① 분포 위치 (네이버 컨센서스 평균 대비 위치)
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

    # 종합 신뢰도
    verdict = build_report_verdict(
        distribution=distribution, timeline=timeline, reverse=reverse,
        report={"pub_date": report_date, "opinion": sel_opinion, "target_price": target_price},
    )

    return {
        "company": {"name": comp_name, "code": comp_code, "current_price": price,
                    "shares_outstanding": shares},
        "report": {
            "broker": sel_broker, "pub_date": report_date, "opinion": sel_opinion,
            "target_price": target_price, "price_at_pub": price_at_pub,
        },
        "kpis": kpis,
        "multiples": multiples,
        "valuation_range": valuation_range,
        "reverse": reverse,
        "distribution": distribution,
        "consensus": consensus,
        "timeline": timeline,
        "verdict": verdict,
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
    )
else:
    A = None

# 초기 안내 화면
if A is None:
    st.markdown("## FinSight — 리포트 신뢰도 검증")
    st.markdown("### 👈 왼쪽에서 종목과 리포트를 선택하세요")
    st.info("📈 개인투자자를 위한 3축 검증으로 리포트의 신뢰도를 평가합니다.")
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
st.markdown(f"## FinSight — 리포트 신뢰도 검증")
st.markdown(
    f"**{co['name']}** · "
    f"{rep['broker']} · {rep['pub_date']} · "
    f"**{rep['opinion']}** · "
    f"목표가 {rep['target_price']:,}원"
)

if A.get("is_demo_financials"):
    st.warning(
        f"⚠️ **{co['name']}의 실제 재무를 DART에서 가져오지 못해 농심 데모 재무로 계산했습니다.** "
        f"(완전연도 EPS 부족 또는 종목 매칭 실패) "
        f"목표가 분포(①축)는 검색값을 반영하지만, 발행 후 변화(②축)·가정 검증(③축)은 데모입니다."
    )
else:
    st.caption(f"✅ 실제 DART 재무 연동 — 현재가 {co['current_price']:,.0f}원 · 발행주식수 {co['shares_outstanding']:,.0f}주")

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
    st.markdown(
        f"<div style='text-align:center;padding:20px 8px;border:2px solid {gc};"
        f"border-radius:12px;background:{COLOR['bg']}'>"
        f"<div style='font-size:12px;color:#666;font-weight:600'>신뢰도 점수</div>"
        f"<div style='font-size:48px;font-weight:900;color:{gc};line-height:1.0'>{V['total']}</div>"
        f"<div style='font-size:14px;color:#999;margin-bottom:8px'>/100</div>"
        f"<div style='font-size:18px;color:{gc};font-weight:700;margin-bottom:6px'>{V['grade']}등급</div>"
        f"<div style='font-size:14px;color:#666;margin-bottom:10px'>{V['label']}</div>"
        f"<div style='font-size:20px;letter-spacing:2px'>{'★'*V['stars']}{'☆'*(5-V['stars'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

with sc2:
    st.markdown("#### 평가 의견")
    st.markdown(f"**{V['headline']}**")
    st.markdown(V["guide"])

    # 축별 점수
    st.markdown("---")
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

dist = A["distribution"]
tl = A["timeline"]
rev = A["reverse"]

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("#### ① 분포 위치")
    st.markdown(f"### {signal_icon(dist['position'])} {dist['position']}")
    st.caption(
        f"컨센서스 평균 {dist['mean']:,.0f}원 대비 {dist['vs_median_pct']:+.1f}%"
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
tab1, tab2, tab3, tab4 = st.tabs([
    "① 분포 위치",
    "② 발행 후 변화",
    "③ 가정 검증",
    "근거·출처",
])

with tab1:
    st.subheader("시장 컨센서스 대비 위치")

    cons = A.get("consensus") or {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("검증 리포트 목표가", f"{rep['target_price']:,}원")
    with col2:
        st.metric("시장 컨센서스 평균", f"{dist['mean']:,.0f}원")
    with col3:
        st.metric("평균 대비", f"{dist['vs_median_pct']:+.1f}%",
                  delta=dist["position"], delta_color="off")

    st.markdown("---")
    st.markdown(
        f"**판정: {dist['position']}** "
        f"(z={dist['z']}, 표준편차는 컨센서스 평균의 {int(0.12*100)}%로 추정)"
    )
    if cons:
        st.caption(
            f"📊 네이버 금융 컨센서스 · 투자의견 {cons.get('opinion_label','')} "
            f"· 기준일 {cons.get('create_date','')}"
        )
    st.info(
        "ℹ️ 증권사별 개별 목표가는 리포트 PDF에만 있어 자동수집이 어렵습니다. "
        "대신 시장 컨센서스 **평균** 대비 이 리포트가 얼마나 공격적/보수적인지로 판단합니다."
    )

with tab2:
    st.subheader("발행 후 주가 및 수급 변화")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("발행일 주가", f"{tl['price_at_pub']:,}원")
        st.metric("현재 주가", f"{co['current_price']:,}원")
        st.metric("변화율", f"{(co['current_price']/tl['price_at_pub']-1)*100:.1f}%")

    with col2:
        st.metric("목표가까지 남은 여력", f"{(rep['target_price']/co['current_price']-1)*100:.1f}%")
        st.metric("발행 후 경과일", f"{tl['elapsed']}일")
        st.metric("여력 소진율", f"{tl['soak_pct']}%")

    if tl.get("supply_gap"):
        st.warning(f"⚠️ 외국인 순매도: {abs(D.DEMO_FOREIGN_NET_EOK):,}억원 (매수 의견과 괴리)")

with tab3:
    st.subheader("성장률 역산 검증")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("현재 주당이익", f"{rev['current_eps']:,.0f}원")
        st.metric("필요 주당이익", f"{rev['need_eps']:,.0f}원")
        st.metric("필요 성장률", f"{rev['need_growth']:+.1f}%")

    with col2:
        st.metric("과거 평균 성장", f"{rev['avg_growth']:+.1f}%")
        st.metric("과거 중앙값 성장", f"{rev['median_growth']:+.1f}%")
        st.metric("변동성 계수(CV)", f"{rev.get('cv', 0):.2f}")

    st.markdown("---")
    st.subheader("과거 성장률 추이")

    growth_df = pd.DataFrame({
        "연도": list(range(2019, 2025)),
        "성장률": rev["growth_history"][:6],
    })

    col1, col2 = st.columns([2, 1])
    with col1:
        st.line_chart(growth_df.set_index("연도"), height=250)
    with col2:
        avg_val = rev["avg_growth"]
        median_val = rev["median_growth"]
        st.metric("평균", f"{avg_val:+.1f}%")
        st.metric("중앙값", f"{median_val:+.1f}%")
        st.metric("필요값", f"{rev['need_growth']:+.1f}%")

with tab4:
    st.subheader("계산 근거")
    st.markdown("""
    **① 분포 위치**
    - 8개 증권사 목표가를 비교해 상대적 위치 판정
    - Z-score: (목표가 - 평균) / 표준편차

    **② 발행 후 변화**
    - 발행 이후 경과일, 주가 변화, 외국인 수급 괴리 평가
    - 공급 괴리(supply gap): 매수 의견인데 외국인 순매도인 경우

    **③ 가정 검증 (가장 중요)**
    - 목표가를 역산해 "필요 성장률" 계산
    - 과거 6년 성장률 중앙값과 비교
    - 변동성 높으면(CV > 0.8) 중앙값 사용, 낮으면 평균값 사용
    """)

    st.divider()
    st.subheader("신뢰도 점수 산정")
    st.markdown(f"""
    **배점 구성**
    - 분포 위치(공간축): 30점
    - 발행 후 변화(시간축): 30점
    - 가정 검증(논리축): 40점
    - **합계: 100점**

    **등급 기준**
    - A등급 (75점 이상): 신뢰할 만함
    - B등급 (60~74점): 대체로 무난
    - C등급 (45~59점): 주의 필요
    - D등급 (30~44점): 신뢰도 낮음
    - E등급 (미만 30점): 낙관 편향 강함

    **현재 결과: {V['total']}점 ({V['grade']}등급)**
    """)
