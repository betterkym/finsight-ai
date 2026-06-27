"""FinSight — 이 리포트, 믿어도 되나?

증권사 리포트의 목표가를 3축으로 검증하는 개인투자자용 도구.
  ① 공간축: 다른 증권사보다 튀나?  (분포 위치)
  ② 시간축: 발행 후 상황 바뀌었나?  (시점 정합성)
  ③ 논리축: 이 목표가 숫자가 성립하나?  (가정 역산) ★

엔진은 기존 모듈을 그대로 호출한다:
  kpi_engine.calculate_quarterly_kpis
  diagnostics.calculate_multiple_valuation / build_valuation_range
  finsight_modules.reverse_engineer_target / locate_in_distribution / aggregate_opinions
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

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
)
from core.mode_views import build_tracker_table, build_peer_benchmark
from timeline_module import build_post_publish_timeline
from scoring_module import build_report_verdict
import demo_data as D


st.set_page_config(page_title="FinSight — 리포트 검증", layout="wide")

NAVY = "#1B2A4A"
RED = "#C0392B"


# ──────────────────────────────────────────────
# 데이터 준비 (데모 또는 실데이터)
# ──────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_analysis():
    financials = D.build_demo_financials()
    kpis = calculate_quarterly_kpis(financials)
    company = D.DEMO_COMPANY
    report = D.DEMO_REPORT
    valuation_ref = D.get_demo_valuation_reference()
    current_price = company["current_price"]
    shares = company["shares_outstanding"]
    net_debt = 0.0

    multiple_valuation = calculate_multiple_valuation(
        kpis, shares, net_debt, current_price, valuation_ref
    )
    valuation_range = build_valuation_range(None, multiple_valuation, current_price)

    # [05 동종기업 검증 재사용] 공간축 — 농심 vs 동종기업 펀더멘털
    peers_raw = D.build_demo_peers()
    peers = {name: calculate_quarterly_kpis(df) for name, df in peers_raw.items()}
    peer_benchmark = build_peer_benchmark(kpis, peers)

    reverse = reverse_engineer_target(
        report["target_price"], kpis, shares, current_price
    )
    opinions = aggregate_opinions(valuation_ref["broker_targets"])
    distribution = locate_in_distribution(
        report["target_price"], valuation_ref["broker_targets"]
    )
    timeline = build_post_publish_timeline(
        report,
        current_price,
        post_events=D.DEMO_POST_EVENTS,
        foreign_net_fallback=D.DEMO_FOREIGN_NET_EOK,
        as_of="2026-06-20",
    )
    # [모듈4] 3축 종합 → 리포트 신뢰도 점수 + 평가 의견
    verdict = build_report_verdict(distribution, timeline, reverse, report)

    return {
        "company": company,
        "report": report,
        "kpis": kpis,
        "multiple_valuation": multiple_valuation,
        "valuation_range": valuation_range,
        "reverse": reverse,
        "opinions": opinions,
        "distribution": distribution,
        "timeline": timeline,
        "broker_targets": valuation_ref["broker_targets"],
        "peer_benchmark": peer_benchmark,
        "peers": list(peers.keys()),
        "verdict": verdict,
    }


A = load_analysis()
co, rep = A["company"], A["report"]


# ──────────────────────────────────────────────
# 헤더
# ──────────────────────────────────────────────
st.markdown(f"## FinSight — 이 리포트, 믿어도 되나?")
st.markdown(
    f"**{co['name']}** ({co['code']}) · {rep['broker']} · {rep['pub_date']} · "
    f"**{rep['opinion']}** · 목표가 {rep['target_price']:,}원 · 현재가 {co['current_price']:,}원"
)


# ──────────────────────────────────────────────
# 통합 검증 카드 (3축 신호등)
# ──────────────────────────────────────────────
def signal_color(verdict: str) -> str:
    if verdict in ("낙관", "과도한 낙관", "확인 필요", "다소 높음"):
        return "🟠"
    if verdict in ("현실적", "양호", "평균권"):
        return "🟢"
    return "⚪"


dist = A["distribution"]
tl = A["timeline"]
rev = A["reverse"]
op = A["opinions"]
V = A["verdict"]

# ── 리포트 신뢰도 점수 + 평가 의견 (최상단) ──
grade_color = {
    "A": "#1B8A4A",
    "B": "#5B8C2A",
    "C": "#BA7517",
    "D": "#C0392B",
    "E": "#A32D2D",
}
gc = grade_color.get(V["grade"], "#C0392B")
sc1, sc2 = st.columns([1, 2.4])
with sc1:
    st.markdown(
        f"<div style='text-align:center;padding:18px 8px;border:2px solid {gc};"
        f"border-radius:14px;background:#FAFAF7'>"
        f"<div style='font-size:13px;color:#5F5E5A'>리포트 신뢰도</div>"
        f"<div style='font-size:46px;font-weight:800;color:{gc};line-height:1.1'>{V['total']}<span style='font-size:20px;color:#9a9a92'>/100</span></div>"
        f"<div style='font-size:20px;color:{gc};font-weight:700'>{V['grade']}등급 · {V['label']}</div>"
        f"<div style='font-size:22px;letter-spacing:3px'>{'★'*V['stars']}{'☆'*(5-V['stars'])}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
with sc2:
    st.markdown(f"#### 📋 리포트 평가 의견")
    st.markdown(f"**{V['headline']}**")
    st.markdown(V["guide"])
    # 축별 점수 막대
    for key in ("space", "time", "logic"):
        ax = V["axes"][key]
        if ax.get("uncounted"):
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0'>"
                f"<span style='width:160px;font-size:13px'>{ax['title']}</span>"
                f"<span style='flex:1;background:#E3E1D8;border-radius:4px;height:14px;'></span>"
                f"<span style='width:54px;text-align:right;font-size:13px;color:#999'>미집계</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            pct = int(ax["score"] / ax["max"] * 100)
            bar_color = "#185FA5" if key == "space" else ("#0F6E56" if key == "time" else "#C0392B")
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0'>"
                f"<span style='width:160px;font-size:13px'>{ax['title']}</span>"
                f"<span style='flex:1;background:#E3E1D8;border-radius:4px;height:14px;position:relative'>"
                f"<span style='position:absolute;left:0;top:0;height:14px;width:{pct}%;background:{bar_color};border-radius:4px'></span></span>"
                f"<span style='width:54px;text-align:right;font-size:13px;font-weight:700'>{ax['score']}/{ax['max']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    st.caption(f"⚖️ {V['disclaimer']}")

st.divider()

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("##### ① 혼자 튀나?")
    st.markdown(f"### {signal_color(dist['position'])} {dist['position']}")
    st.caption(
        f"{dist['n']}개 증권사 중 상위 {dist['top_pct']}% · 평균 대비 {dist['vs_median_pct']:+.1f}%"
    )
with c2:
    st.markdown("##### ② 지금도 유효?")
    sig = "확인 필요" if tl["supply_gap"] else "양호"
    st.markdown(f"### {signal_color(sig)} {sig}")
    st.caption(f"발행 {tl['elapsed']}일 경과 · 여력 {tl['soak_pct']}% 소진")
with c3:
    st.markdown("##### ③ 숫자가 성립?")
    st.markdown(f"### {signal_color(rev['verdict'])} {rev['verdict']}")
    st.caption(f"필요 성장 {rev['need_growth']:+.0f}% · 보통 해엔 {rev['median_growth']:+.0f}%")

st.caption("⚖️ 판단은 투자자 몫 · FinSight는 사실을 모아 보여줄 뿐 추천하지 않습니다")
st.divider()


# ──────────────────────────────────────────────
# 3축 탭
# ──────────────────────────────────────────────
ax1, ax2, ax3, ev = st.tabs(["① 혼자 튀나?", "② 지금도 유효?", "③ 숫자가 성립?", "근거·출처"])


# ① 공간축
with ax1:
    st.markdown("### 다른 증권사들과 비교하면")
    st.caption("🔗 기존 기능 연결: 05 동종기업 검증 + 06 가치평가(분포) + 의견 집계(신규)")
    st.info(
        f"이 목표가 {dist['this_target']:,}원은 **{dist['n']}개 증권사 중 상위 {dist['top_pct']}%** "
        f"입니다. 평균 목표가({dist['median']:,}원)보다 {dist['vs_median_pct']:+.1f}% 높습니다."
    )

    targets_df = pd.DataFrame(A["broker_targets"]).sort_values(
        "target_price", ascending=False
    )
    targets_df = targets_df.rename(
        columns={"source": "증권사", "target_price": "목표가", "opinion": "의견"}
    )
    targets_df["목표가"] = targets_df["목표가"].map(lambda x: f"{x:,}원")
    st.dataframe(targets_df, hide_index=True, width="stretch")

    st.markdown("#### 의견 분포")
    oc1, oc2, oc3 = st.columns(3)
    oc1.metric("매수", op["buy"])
    oc2.metric("중립", op["hold"])
    oc3.metric("매도", op["sell"])
    if op["has_sell"]:
        st.warning(
            f"⚠️ 매도 의견이 {op['sell']}개 있습니다. 증권사 리포트에서 매도는 "
            f"전체의 0.1%로 매우 드문 신호입니다 — 그만큼 주목할 가치가 있습니다."
        )

    st.divider()
    st.markdown("#### 적정가 범위 — 여러 방법으로 교차검증")
    st.caption("기존 06 가치평가의 DCF·PER·EV/EBITDA 교차검증 결과")
    vr = A["valuation_range"]
    if vr.get("low") is not None:
        vrc1, vrc2, vrc3 = st.columns(3)
        vrc1.metric("보수 (하위 25%)", f"{vr['low']:,.0f}원")
        vrc2.metric("중앙값", f"{vr['mid']:,.0f}원")
        vrc3.metric("낙관 (상위 75%)", f"{vr['high']:,.0f}원")
        if vr.get("dispersion"):
            st.caption(
                f"방법 간 편차 {vr['dispersion']:.0f}% — "
                f"{'방법별 결론이 크게 갈림' if vr['dispersion'] > 30 else '방법별 결론이 대체로 수렴'}. "
                f"이 리포트 목표가 {dist['this_target']:,}원과 비교해 보세요."
            )

    st.divider()
    st.markdown("#### 동종기업과 비교 — 펀더멘털 우열")
    st.caption(f"기존 05 동종기업 검증: {', '.join(A['peers'])} 대비")
    pb = A["peer_benchmark"]
    if not pb.empty:
        show_pb = pb[["지표", "분석기업", "동종기업 중앙값", "격차", "단위"]].copy()
        for col in ("분석기업", "동종기업 중앙값", "격차"):
            show_pb[col] = show_pb[col].map(
                lambda x: f"{x:.1f}" if pd.notna(x) else "—"
            )
        st.dataframe(show_pb, hide_index=True, width="stretch")


# ② 시간축
with ax2:
    st.markdown("### 리포트 발행 후 무슨 일이 있었나")
    st.caption("🔗 기존 기능 연결: 03 실적 트래커 + 07 근거·출처 + 수급 타임라인(신규)")
    st.info(
        f"이 리포트는 **{tl['elapsed']}일 전({tl['months']}개월 전)** 정보로 작성됐습니다. "
        f"발행 시점 상승여력 {tl['orig_upside']:+.0f}% 중 **{tl['soak_pct']}%가 이미 소진**됐고, "
        f"남은 여력은 {tl['remaining']:+.1f}%입니다."
    )

    if tl["supply_gap"]:
        st.warning(
            f"⚠️ 리포트는 **{tl['opinion']}** 의견인데, 발행 후 외국인은 "
            f"누적 **{tl['foreign_net']:+,}억원 순매도**했습니다. "
            f"스마트머니는 리포트와 반대 방향으로 움직이는 중입니다. "
            f"(매수/매도 신호가 아니라 판단 재료입니다)"
        )

    st.markdown("#### 발행 후 타임라인")
    if tl["events"]:
        ev_df = pd.DataFrame(tl["events"]).rename(
            columns={"date": "날짜", "type": "구분", "detail": "내용"}
        )
        st.dataframe(ev_df, hide_index=True, width="stretch")

    st.markdown("#### 발행 후 나온 실적")
    tracker = build_tracker_table(A["kpis"])
    st.dataframe(tracker.tail(3), width="stretch")


# ③ 논리축 ★
with ax3:
    st.markdown("### 이 목표가, 숫자가 말이 되나")
    st.caption("🔗 기존 기능 연결: 06 가치평가(DCF·역산) + kpi_engine(과거 EPS) + 변동성 보정(신규·핵심)")
    st.info(
        f"목표가 {rev['target_price']:,}원이 되려면 회사 순이익(EPS)이 "
        f"**{rev['need_growth']:+.1f}% 늘어야** 합니다. "
        f"그런데 이 회사가 보통 해에 성장한 폭(중앙값)은 **{rev['median_growth']:+.1f}%**입니다."
    )

    if rev["volatility"] == "매우높음":
        st.warning(
            f"⚠️ 이 회사는 실적이 **들쭉날쭉 심합니다** (변동성 매우 높음). "
            f"단순 평균 성장률({rev['avg_growth']:+.1f}%)은 특정 해의 큰 변동에 "
            f"왜곡됐기 때문에, **중앙값({rev['median_growth']:+.1f}%)**으로 봐야 정확합니다. "
            f"필요 성장률이 보통 해의 **{rev['multiple']}배**입니다."
        )
    elif rev["verdict"] in ("낙관", "과도한 낙관"):
        st.warning(
            f"필요 성장률 {rev['need_growth']:+.1f}%가 과거 대표 성장률 "
            f"{rev['reference_growth']:+.1f}%를 웃돕니다 → **{rev['verdict']}**"
        )

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("현재 EPS", f"{rev['current_eps']:,}원")
    mc2.metric("현재 PER", f"{rev['current_per']}배")
    mc3.metric("필요 성장률", f"{rev['need_growth']:+.1f}%")
    mc4.metric("변동성(CV)", f"{rev['cv']}", rev["volatility"])

    st.markdown("#### 과거 EPS 성장률")
    gh = rev["growth_history"]
    st.caption(
        f"연도별: {' / '.join(f'{g:+.0f}%' for g in gh)} → "
        f"평균 {rev['avg_growth']:+.1f}% · 중앙값 {rev['median_growth']:+.1f}%"
    )

    st.markdown("#### 시나리오별 적정가 (PER 역산)")
    mv = A["multiple_valuation"]
    if not mv.empty:
        show = mv.copy()
        show["implied_price"] = show["implied_price"].map(
            lambda x: f"{x:,.0f}원" if pd.notna(x) else "—"
        )
        show["upside"] = show["upside"].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
        show = show.rename(
            columns={
                "method": "방법",
                "case": "케이스",
                "implied_price": "적정가",
                "upside": "상승여력",
                "basis": "근거",
            }
        )
        st.dataframe(
            show[["방법", "케이스", "적정가", "상승여력", "근거"]],
            hide_index=True,
            width="stretch",
        )


# 근거·출처
with ev:
    st.markdown("### 근거와 출처")
    st.markdown(
        "- **목표가·의견 분포**: 증권사 공개 리포트 (목표가·투자의견 숫자만 수집)\n"
        "- **과거 실적·EPS**: DART 사업보고서\n"
        "- **수급**: KRX (pykrx)\n"
        "- **역산 계산**: 기존 FinSight diagnostics 엔진"
    )
    st.caption(
        "FinSight는 리포트 본문을 재배포하지 않습니다. 사실(숫자)만 가공해 "
        "한 화면에 모으며, 어떤 종목도 추천하지 않습니다."
    )

    with st.expander("역산 계산식 상세"):
        st.code(
            f"현재 PER = 현재가 {rev['current_price']:,} / 현재 EPS {rev['current_eps']:,} "
            f"= {rev['current_per']}배\n"
            f"필요 EPS = 목표가 {rev['target_price']:,} / PER {rev['current_per']} "
            f"= {round(rev['target_price']/rev['current_per']):,}원\n"
            f"필요 성장률 = (필요 EPS / 현재 EPS - 1) = {rev['need_growth']:+.1f}%\n"
            f"변동계수 CV = 성장률 표준편차 / |평균| = {rev['cv']} → {rev['volatility']}\n"
            f"대표값 = {'중앙값' if rev['cv'] > 0.8 else '평균'} {rev['reference_growth']:+.1f}%\n"
            f"판정: 필요 {rev['need_growth']:+.1f}% vs 대표 {rev['reference_growth']:+.1f}% "
            f"→ {rev['verdict']}"
        )
