"""Restrained analyst-workbench components. No decorative dashboard chrome."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


def inject_css() -> None:
    st.markdown("""
    <style>
      :root {--ink:#0F172A;--muted:#64748B;--line:#E2E8F0;--navy:#143257;--accent:#1D4E89;--paper:#FFFFFF;}
      .stApp {background:#F1F4F8;color:var(--ink);font-feature-settings:"tnum";}
      .block-container {max-width:1480px;padding-top:1.2rem;padding-bottom:4rem;}
      [data-testid="stSidebar"] {background:#0F2238;border-right:1px solid #0B1A2C;}
      [data-testid="stSidebar"] * {color:#D6E1ED;}
      [data-testid="stSidebar"] h2 {color:#FFFFFF;letter-spacing:-.02em;}
      [data-testid="stSidebar"] .stButton button {border-radius:4px;font-weight:700;min-height:2.8rem;background:#2563EB;color:#fff;border:none;}
      [data-testid="stSidebar"] .stButton button:hover {background:#1D4ED8;}
      [data-testid="stMetric"] {background:#FFFFFF;border:1px solid #E2E8F0;border-top:3px solid var(--accent);border-radius:6px;padding:14px 16px;box-shadow:0 1px 2px rgba(16,24,40,.05);}
      [data-testid="stMetricLabel"] {color:#475467;font-size:.76rem;letter-spacing:.02em;}
      [data-testid="stMetricValue"] {font-size:1.5rem;letter-spacing:-.02em;}
      [data-baseweb="tab-list"] {gap:2px;border-bottom:1px solid #D0D5DD;}
      [data-baseweb="tab"] {border-radius:6px 6px 0 0;padding:11px 18px;color:#475467;font-weight:500;}
      [aria-selected="true"][data-baseweb="tab"] {color:#143257;font-weight:700;border-bottom:2px solid #1D4E89;background:#FFFFFF;}
      .fs-kicker {font-size:.66rem;letter-spacing:.16em;color:#1D4E89;font-weight:800;text-transform:uppercase;}
      .fs-masthead {display:flex;align-items:flex-end;justify-content:space-between;border-bottom:2px solid #143257;padding:8px 0 16px;margin-bottom:18px;gap:24px;}
      .fs-brand {font-size:2.3rem;line-height:1;font-weight:800;letter-spacing:-.05em;color:#0B1F33;}
      .fs-brand span {color:#1D4E89;}
      .fs-subtitle {margin-top:9px;font-size:.92rem;color:#475467;max-width:820px;line-height:1.55;}
      .fs-product-tag {font-size:.66rem;letter-spacing:.1em;font-weight:800;color:#FFFFFF;border-radius:4px;padding:8px 12px;background:#143257;white-space:nowrap;}
      .fs-tab-intro {background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #1D4E89;border-radius:0 6px 6px 0;padding:13px 18px;margin:4px 0 18px 0;}
      .fs-tab-title {font-weight:800;color:#143257;margin-bottom:4px;font-size:1.02rem;}
      .fs-tab-purpose {font-size:.9rem;color:#344054;margin-bottom:5px;}
      .fs-tab-output {font-size:.74rem;color:#667085;letter-spacing:.01em;}
      .fs-note {background:#FFFFFF;border-left:3px solid #1D4E89;padding:12px 14px;color:#344054;}
      .fs-risk {background:#FFFAEB;border-left:3px solid #B54708;padding:12px 14px;}
      .fs-stable {background:#F6FEF9;border-left:3px solid #027A48;padding:12px 14px;}
      /* Causal interpretation cards */
      .fs-card {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;padding:16px 18px;margin-bottom:12px;box-shadow:0 1px 3px rgba(16,24,40,.04);}
      .fs-card-lead {font-size:1.0rem;color:#0F172A;line-height:1.6;margin-bottom:10px;}
      .fs-card-lead b {color:#143257;}
      .fs-meta {display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px;}
      .fs-badge {font-size:.68rem;font-weight:700;letter-spacing:.02em;padding:3px 9px;border-radius:999px;border:1px solid transparent;}
      .fs-b-high {background:#FEF2F2;color:#B42318;border-color:#FCA5A5;}
      .fs-b-med {background:#FFF7ED;color:#9A3412;border-color:#FDBA74;}
      .fs-b-low {background:#F0FDF4;color:#15803D;border-color:#86EFAC;}
      .fs-b-pending {background:#F1F5F9;color:#475569;border-color:#CBD5E1;}
      .fs-b-tier0 {background:#EFF6FF;color:#1D4ED8;border-color:#93C5FD;}
      .fs-b-tier1 {background:#F5F3FF;color:#6D28D9;border-color:#C4B5FD;}
      .fs-b-tier2 {background:#FFFBEB;color:#B45309;border-color:#FCD34D;}
      .fs-b-tier3 {background:#F8FAFC;color:#64748B;border-color:#E2E8F0;}
      .fs-cause {border-left:3px solid #CBD5E1;padding:7px 12px;margin:6px 0;background:#FAFBFC;border-radius:0 5px 5px 0;}
      .fs-cause-t0 {border-left-color:#2563EB;} .fs-cause-t1 {border-left-color:#7C3AED;}
      .fs-cause-t2 {border-left-color:#D97706;} .fs-cause-t3 {border-left-color:#94A3B8;}
      .fs-cause a {color:#1D4ED8;text-decoration:none;font-weight:600;}
      .fs-snippet {color:#64748B;font-size:.82rem;margin-top:3px;}
      .fs-rail {color:#475467;font-size:.84rem;}
      .fs-attr {display:grid;grid-template-columns:170px 78px 1fr;gap:0;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;background:#fff;}
      .fs-attr-row {display:contents;}
      .fs-attr-cell {padding:11px 14px;border-bottom:1px solid #EEF2F6;}
      .fs-attr-driver {font-weight:700;color:#143257;background:#F8FAFC;}
      .fs-attr-read {color:#344054;font-size:.9rem;line-height:1.5;}
      .fs-attr-ev {font-size:.74rem;color:#64748B;margin-top:4px;}
      .fs-recipe {border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;background:#fff;}
      .fs-recipe-row {display:flex;gap:0;border-bottom:1px solid #EEF2F6;}
      .fs-recipe-row:last-child {border-bottom:none;}
      .fs-recipe-n {width:34px;flex:none;display:flex;align-items:flex-start;justify-content:center;padding-top:11px;font-weight:800;color:#1D4E89;background:#F8FAFC;}
      .fs-recipe-body {padding:9px 14px;font-size:.86rem;color:#344054;line-height:1.5;display:flex;flex-direction:column;gap:3px;}
      .fs-recipe-tag {display:inline-block;min-width:46px;font-size:.66rem;font-weight:800;color:#475569;background:#EEF2F6;border-radius:3px;padding:1px 6px;margin-right:8px;text-align:center;letter-spacing:.02em;}
      .fs-recipe-rule {color:#9A3412;background:#FFF7ED;}
      h1,h2,h3,h4 {letter-spacing:-.02em;}
      .stDataFrame {border:1px solid #E2E8F0;border-radius:6px;}
      footer {visibility:hidden;} #MainMenu {visibility:hidden;}
      @media (max-width:760px) {.fs-masthead{display:block}.fs-product-tag{display:inline-block;margin-top:12px}.block-container{padding-top:.9rem}.fs-brand{font-size:1.9rem}.fs-attr{grid-template-columns:1fr}}
    </style>
    """, unsafe_allow_html=True)


_WEIGHT_BADGE = {"High": "fs-b-high", "Medium": "fs-b-med", "Low": "fs-b-low", "Aligned": "fs-b-low", "Evidence pending": "fs-b-pending"}
_TIER_BADGE = {0: "fs-b-tier0", 1: "fs-b-tier1", 2: "fs-b-tier2", 3: "fs-b-tier3", 4: "fs-b-tier3"}


def _esc(text) -> str:
    import html
    return html.escape(str(text if text is not None else ""))


def render_attribution(attribution: list[dict]) -> None:
    """Render the price-action driver decomposition as an analyst attribution grid."""
    if not attribution:
        st.info("기여 분해에 사용할 실적·수급·기대치 데이터가 부족합니다.")
        return
    cells = ['<div class="fs-attr">']
    for row in attribution:
        badge = _WEIGHT_BADGE.get(row.get("weight"), "fs-b-pending")
        ev = _esc(row.get("evidence", ""))
        lvl = _esc(row.get("evidence_level", ""))
        link = f' · <a href="{_esc(row["url"])}" target="_blank">공시</a>' if row.get("url") else ""
        cells.append(
            f'<div class="fs-attr-row"><div class="fs-attr-cell fs-attr-driver">{_esc(row.get("driver"))}</div>'
            f'<div class="fs-attr-cell"><span class="fs-badge {badge}">{_esc(row.get("weight"))}</span></div>'
            f'<div class="fs-attr-cell fs-attr-read">{_esc(row.get("reading"))}'
            f'<div class="fs-attr-ev">근거: {ev} · {lvl}{link}</div></div></div>'
        )
    cells.append("</div>")
    st.markdown("".join(cells), unsafe_allow_html=True)


def render_interpretation(item: dict, fmt) -> None:
    """Render one abnormal signal's full causal reading (mechanism → sourced cause → falsifier)."""
    interp = item["interpretation"]
    conf = interp.get("confidence", "")
    conf_cls = {"High": "fs-b-high", "Medium": "fs-b-med", "Low": "fs-b-low"}.get(conf, "fs-b-pending")
    obs = f"현재 {fmt(item['value'], item['unit'])} · 자체 과거 중앙값 {fmt(item['baseline'], item['unit'])}"
    peer = ""
    if item.get("peer_value") is not None:
        peer = f' · 동종기업 중앙값 {fmt(item["peer_value"], item["unit"])} ({item.get("peer_verdict","")})'
    meta = (
        f'<div class="fs-meta"><span class="fs-badge {conf_cls}">해석 신뢰도 {_esc(conf)}</span>'
        f'<span class="fs-rail">{_esc(obs)}{_esc(peer)}</span></div>'
    )
    lead = f'<div class="fs-card-lead">{_esc(interp["narrative"])}</div>'
    blocks = [f'<div class="fs-card">{meta}{lead}']
    if interp.get("cause_candidates"):
        blocks.append('<div class="fs-rail" style="font-weight:700;margin:6px 0 2px;">원인 후보 · 근거 강도순</div>')
        for cause in interp["cause_candidates"]:
            tier = cause.get("tier", 3)
            badge = _TIER_BADGE.get(tier, "fs-b-tier3")
            link = f' <a href="{_esc(cause["url"])}" target="_blank">↗</a>' if cause.get("url") else ""
            snippet = f'<div class="fs-snippet">{_esc(cause["snippet"])}</div>' if cause.get("snippet") else ""
            blocks.append(
                f'<div class="fs-cause fs-cause-t{tier}"><span class="fs-badge {badge}">{_esc(cause["evidence_level"])}</span> '
                f'{_esc(cause["cause"])}{link} <span class="fs-snippet">· {_esc(cause.get("source",""))}</span>{snippet}</div>'
            )
    else:
        blocks.append('<div class="fs-rail" style="color:#B45309;">키워드가 매칭된 공시·뉴스·리서치 근거가 없어 사업 원인을 확정하지 않습니다.</div>')
    blocks.append('</div>')
    st.markdown("".join(blocks), unsafe_allow_html=True)
    st.markdown('<div class="fs-rail" style="font-weight:700;margin:10px 0 4px;">검증 레시피 · 어디서 → 무엇을 → 판정</div>', unsafe_allow_html=True)
    recipe_html = ['<div class="fs-recipe">']
    for i, r in enumerate(interp.get("verification", []), 1):
        recipe_html.append(
            f'<div class="fs-recipe-row"><div class="fs-recipe-n">{i}</div>'
            f'<div class="fs-recipe-body">'
            f'<div><span class="fs-recipe-tag">어디서</span>{_esc(r.get("where"))}</div>'
            f'<div><span class="fs-recipe-tag">무엇을</span>{_esc(r.get("what"))}</div>'
            f'<div><span class="fs-recipe-tag fs-recipe-rule">판정</span>{_esc(r.get("rule"))}</div>'
            f'</div></div>'
        )
    recipe_html.append("</div>")
    st.markdown("".join(recipe_html), unsafe_allow_html=True)
    cols = st.columns([3, 2])
    with cols[0]:
        st.markdown("**DART 본표가 답한 부분 (메커니즘)**")
        st.caption(interp.get("dart_answer") or "—")
        for ev in item.get("dart_evidence", []):
            st.caption(f"• {ev}")
    with cols[1]:
        st.markdown("**반증 조건**")
        st.caption(f"⛔ {interp.get('falsifier','')}")


def render_header() -> None:
    st.markdown(
        '<div class="fs-masthead"><div><div class="fs-kicker">FILING-LED EQUITY RESEARCH</div>'
        '<div class="fs-brand">Fin<span>Sight</span></div><div class="fs-subtitle">공시 숫자를 끝점으로 보지 않습니다. '
        '기대치 괴리·수급·경쟁·투자 시점을 검증하고, 그 판단을 바텀업 가치평가 수식으로 연결합니다.</div>'
        '</div><div class="fs-product-tag">ANALYST WORKBENCH</div></div>',
        unsafe_allow_html=True,
    )


def price_path_chart(frame: dict) -> go.Figure:
    """Return-by-horizon bar mirroring the reference report's price-path panel."""
    labels = [("ret_1m", "1개월"), ("ret_3m", "3개월"), ("ret_6m", "6개월"), ("ret_12m", "12개월")]
    pairs = [(name, frame.get(key)) for key, name in labels if frame.get(key) is not None]
    names = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    colors = ["#DC2626" if (v or 0) < 0 else "#16A34A" for v in values]
    fig = go.Figure(go.Bar(x=names, y=values, marker_color=colors, text=[f"{v:+.1f}%" for v in values], textposition="outside"))
    sub = []
    if frame.get("drawdown") is not None:
        sub.append(f"52주 고점 대비 {frame['drawdown']:+.1f}%")
    if frame.get("position_52w") is not None:
        sub.append(f"52주 밴드 내 위치 {frame['position_52w']:.0f}%")
    fig.update_layout(
        height=230, margin={"l": 10, "r": 10, "t": 36, "b": 10},
        title={"text": "기간별 수익률 · " + " · ".join(sub), "font": {"size": 12, "color": "#475467"}},
        yaxis_title="%", plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", showlegend=False,
    )
    return fig


def render_tab_intro(title: str, purpose: str, output: str) -> None:
    st.markdown(
        f'<div class="fs-tab-intro"><div class="fs-tab-title">{title}</div>'
        f'<div class="fs-tab-purpose">{purpose}</div>'
        f'<div class="fs-tab-output">이 탭의 산출물 · {output}</div></div>',
        unsafe_allow_html=True,
    )


def render_pattern(pattern: dict) -> None:
    cls = "fs-risk" if pattern.get("severity") in ("High", "Watch") else "fs-stable"
    st.markdown(f'<div class="{cls}"><b>{pattern.get("pattern", "비교 데이터 부족")}</b><br>{pattern.get("comment", "")}</div>', unsafe_allow_html=True)


def render_status(status: str) -> str:
    return {"Auto":"🟢 자동 반영", "Stable":"🟢 안정", "Watch":"🟡 확인", "Review":"🟡 사용자 확인", "Risk":"🔴 하락 추세"}.get(status, status)


def financial_trend_chart(kpis: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=kpis["period"], y=kpis["revenue"] / 1e8, name="매출액", marker_color="#B8C7D9"), secondary_y=False)
    fig.add_trace(go.Scatter(x=kpis["period"], y=kpis["opm"], name="OPM", mode="lines+markers", line={"color":"#17365D","width":2}), secondary_y=True)
    fig.add_trace(go.Scatter(x=kpis["period"], y=kpis["cfo_margin"], name="CFO/매출", mode="lines+markers", line={"color":"#667085","width":2,"dash":"dot"}), secondary_y=True)
    fig.update_yaxes(title_text="매출액(억원)", secondary_y=False)
    fig.update_yaxes(title_text="비율(%)", secondary_y=True)
    fig.update_layout(height=420, margin={"l":20,"r":20,"t":35,"b":20}, legend={"orientation":"h","y":1.12}, hovermode="x unified", plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
    return fig


def peer_benchmark_chart(primary: pd.DataFrame, peers: dict[str, pd.DataFrame]) -> go.Figure:
    names, growth, opm = [], [], []
    all_frames = {str(primary.iloc[-1].get("company", "분석기업")): primary, **peers}
    for name, frame in all_frames.items():
        if frame.empty:
            continue
        names.append(name)
        growth.append(frame.iloc[-1].get("revenue_yoy"))
        opm.append(frame.iloc[-1].get("opm"))
    colors = ["#17365D"] + ["#98A2B3"] * max(0, len(names) - 1)
    fig = make_subplots(rows=1, cols=2, subplot_titles=("매출 성장률 YoY(%)", "영업이익률(%)"))
    fig.add_trace(go.Bar(x=names, y=growth, marker_color=colors, name="매출 성장"), row=1, col=1)
    fig.add_trace(go.Bar(x=names, y=opm, marker_color=colors, name="OPM"), row=1, col=2)
    fig.update_layout(height=360, showlegend=False, margin={"l":20,"r":20,"t":55,"b":30}, plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
    return fig


def margin_waterfall_chart(latest: pd.Series) -> go.Figure:
    previous = latest.get("previous_opm") or 0
    values = [previous, latest.get("cogs_contribution_pp") or 0, latest.get("sga_contribution_pp") or 0, latest.get("other_contribution_pp") or 0, latest.get("current_opm") or 0]
    fig = go.Figure(go.Waterfall(
        x=["이전 OPM", "원가율 기여", "판관비율 기여", "기타", "현재 OPM"],
        measure=["absolute", "relative", "relative", "relative", "total"], y=values,
        connector={"line":{"color":"#94a3b8"}}, increasing={"marker":{"color":"#22c55e"}}, decreasing={"marker":{"color":"#ef4444"}}, totals={"marker":{"color":"#2563eb"}},
        text=[f"{value:+.1f}%p" for value in values], textposition="outside",
    ))
    fig.update_layout(height=420, yaxis_title="OPM / 기여도 (%p)", margin={"l":20,"r":20,"t":30,"b":20})
    return fig


def render_quality(checks: list[dict]) -> None:
    frame = pd.DataFrame(checks).rename(columns={"field":"항목","status":"출처/상태","missing_quarters":"결측 분기","note":"메모"})
    st.dataframe(frame, width="stretch", hide_index=True)


# Compatibility names for imports in old notebooks; the UI no longer uses mode cards or briefs.
section_label = lambda text: st.markdown(f"#### {text}")
render_landing_header = render_header
