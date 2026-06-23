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
      [data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {color:#D6E1ED;}
      [data-testid="stSidebar"] h2 {color:#FFFFFF;letter-spacing:-.02em;}
      /* Input/select fields: white box needs dark text so typing is legible */
      [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {color:#0F172A !important;background:#FFFFFF;}
      [data-testid="stSidebar"] [data-baseweb="input"], [data-testid="stSidebar"] [data-baseweb="select"] > div {background:#FFFFFF;border:1px solid #CBD5E1;border-radius:6px;}
      [data-testid="stSidebar"] [data-baseweb="input"] *, [data-testid="stSidebar"] [data-baseweb="select"] * {color:#0F172A;}
      [data-testid="stSidebar"] input::placeholder {color:#94A3B8 !important;}
      [data-testid="stSidebar"] [role="radiogroup"] label {color:#D6E1ED;}
      [data-testid="stSidebar"] .stButton button {border-radius:4px;font-weight:700;min-height:2.8rem;background:#2563EB;color:#fff !important;border:none;}
      [data-testid="stSidebar"] .stButton button * {color:#fff !important;}
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
      .fs-tab-intro {background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #1D4E89;border-radius:0 6px 6px 0;padding:13px 18px;margin:4px 0 18px 0;min-height:96px;display:flex;flex-direction:column;justify-content:center;}
      .fs-tab-title {font-weight:800;color:#143257;margin-bottom:4px;font-size:1.02rem;}
      .fs-tab-purpose {font-size:.9rem;color:#344054;margin-bottom:5px;word-break:keep-all;}
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
      .finsight-context-item {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;padding:11px 14px;margin:8px 0;}
      .finsight-context-item a {font-weight:700;color:#143257;text-decoration:none;}
      .finsight-context-item span {display:block;color:#64748B;font-size:.76rem;margin-top:2px;}
      .finsight-context-item p {color:#111827;font-size:.9rem;line-height:1.5;margin:7px 0 0 0;}
      /* '혹시 이걸 찾으셨나요?' modal content */
      .fs-nf {text-align:center;margin:2px 0 16px;}
      .fs-nf-ico {font-size:1.9rem;line-height:1;margin-bottom:8px;}
      .fs-nf-title {font-size:1.18rem;font-weight:800;color:#0B1F33;letter-spacing:-.02em;line-height:1.35;}
      .fs-nf-sub {font-size:.92rem;color:#667085;margin-top:8px;line-height:1.5;}
      div[data-testid="stDialog"] div[role="dialog"] {border-radius:16px;box-shadow:0 24px 60px rgba(11,31,51,.28);}
      /* Full-screen loading overlay (centered, dimmed backdrop) */
      .fs-overlay {position:fixed;inset:0;z-index:99990;background:rgba(11,31,51,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;}
      .fs-ov-card {background:#FFFFFF;border-radius:16px;padding:30px 38px 26px;box-shadow:0 24px 60px rgba(11,31,51,.32);text-align:center;max-width:410px;width:86%;}
      .fs-spin {width:42px;height:42px;margin:0 auto 16px;border:4px solid #E6ECF3;border-top-color:#1D4E89;border-radius:50%;animation:fs-rot .8s linear infinite;}
      @keyframes fs-rot {to {transform:rotate(360deg);}}
      .fs-ov-title {font-size:1.18rem;font-weight:800;color:#0B1F33;letter-spacing:-.02em;}
      .fs-ov-sub {font-size:.92rem;color:#475467;margin-top:9px;line-height:1.6;word-break:keep-all;}
      @property --fs-sec {syntax:'<integer>';initial-value:0;inherits:false;}
      .fs-ov-eta {display:inline-block;margin-top:15px;font-size:.78rem;font-weight:700;color:#1D4E89;background:#EFF4FB;border:1px solid #DCE7F5;border-radius:999px;padding:4px 13px;counter-reset:fssec var(--fs-sec);animation:fs-sec-tick 60s steps(60,end) forwards;}
      .fs-ov-eta::after {content:"경과 " counter(fssec) "초 · 보통 10~20초";}
      @keyframes fs-sec-tick {from {--fs-sec:0;} to {--fs-sec:60;}}
      /* Slim top bar (analysis pages + landing option A) */
      .fs-bar {display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #D7DEE7;padding:2px 0 12px;margin-bottom:20px;gap:20px;}
      .fs-bar-brand {font-size:1.5rem;font-weight:800;letter-spacing:-.045em;color:#0B1F33;line-height:1;}
      .fs-bar-brand span {color:#1D4E89;}
      /* Landing hero */
      .fs-hero {margin:10px 0 4px;}
      .fs-hero-lead {font-size:1.92rem;line-height:1.26;font-weight:800;letter-spacing:-.035em;color:#0B1F33;max-width:900px;}
      .fs-hero-lead em {font-style:normal;color:#1D4E89;}
      .fs-hero-sub {margin-top:14px;font-size:1.0rem;line-height:1.62;color:#475467;max-width:780px;}
      .fs-cap {font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;color:#94A3B8;font-weight:800;margin:30px 0 10px;}
      .fs-feature-grid {display:grid;grid-template-columns:repeat(4,1fr);gap:14px;}
      .fs-feature {background:#FFFFFF;border:1px solid #E2E8F0;border-top:3px solid #1D4E89;border-radius:9px;padding:18px 18px 20px;box-shadow:0 1px 3px rgba(16,24,40,.05);transition:transform .16s ease,box-shadow .16s ease;}
      .fs-feature:hover {transform:translateY(-3px);box-shadow:0 10px 24px rgba(16,24,40,.10);}
      .fs-feature-k {font-size:.68rem;font-weight:800;letter-spacing:.14em;color:#1D4E89;}
      .fs-feature-t {font-size:1.12rem;font-weight:800;color:#143257;margin:9px 0 7px;letter-spacing:-.01em;}
      .fs-feature-d {font-size:.91rem;line-height:1.56;color:#475467;}
      .fs-usecases {display:grid;grid-template-columns:repeat(3,1fr);border:1px solid #E2E8F0;border-radius:9px;overflow:hidden;background:#FFFFFF;}
      .fs-usecase {padding:16px 18px;border-right:1px solid #EEF2F6;}
      .fs-usecase:last-child {border-right:none;}
      .fs-usecase-h {font-size:.9rem;font-weight:800;color:#1D4E89;letter-spacing:-.01em;}
      .fs-usecase-d {font-size:.91rem;color:#475467;line-height:1.52;margin-top:5px;}
      .fs-cta {display:flex;align-items:center;gap:14px;margin-top:22px;padding:16px 20px;background:linear-gradient(90deg,#0F2238,#173B57);border-radius:9px;color:#DCEAF7;font-size:.96rem;line-height:1.5;}
      .fs-cta b {color:#FFFFFF;}
      .fs-cta-arrow {font-size:1.35rem;color:#7FB0E6;flex:none;}
      .fs-cta-ex {color:#9DBBDB;font-size:.84rem;}
      @media (max-width:1100px){.fs-feature-grid{grid-template-columns:repeat(2,1fr)}.fs-usecases{grid-template-columns:1fr}.fs-usecase{border-right:none;border-bottom:1px solid #EEF2F6}.fs-hero-lead{font-size:1.6rem}}
      /* Publication report view */
      .fs-rpt-head {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:18px 22px;box-shadow:0 1px 3px rgba(16,24,40,.05);display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap;}
      .fs-rpt-co {font-size:1.55rem;font-weight:800;letter-spacing:-.035em;color:#0B1F33;line-height:1.1;}
      .fs-rpt-co span {color:#64748B;font-size:.98rem;font-weight:600;margin-left:6px;letter-spacing:0;}
      .fs-rpt-meta {font-size:.78rem;color:#667085;margin-top:5px;}
      .fs-rating-wrap {text-align:right;}
      .fs-rating {display:inline-block;font-size:.86rem;font-weight:800;padding:6px 16px;border-radius:999px;}
      .fs-rating-buy {background:#ECFDF3;color:#067647;border:1px solid #ABEFC6;}
      .fs-rating-hold {background:#F1F5F9;color:#475569;border:1px solid #CBD5E1;}
      .fs-rating-sell {background:#FEF3F2;color:#B42318;border:1px solid #FECDCA;}
      .fs-rating-note {font-size:.72rem;color:#94A3B8;margin-top:5px;max-width:230px;}
      .fs-rpt-verdict {border-left:4px solid #1D4E89;background:#F8FAFC;padding:12px 16px;margin:16px 0 2px;border-radius:0 8px 8px 0;}
      .fs-rpt-verdict-k {font-size:.68rem;font-weight:800;letter-spacing:.1em;color:#1D4E89;text-transform:uppercase;}
      .fs-rpt-verdict-t {font-size:1.05rem;font-weight:700;color:#143257;margin-top:4px;line-height:1.45;}
      .fs-rpt-sec {font-size:1.16rem;font-weight:800;color:#143257;letter-spacing:-.02em;border-bottom:2px solid #143257;padding-bottom:7px;margin:30px 0 2px;}
      .fs-rpt-sub {font-size:.8rem;color:#667085;margin:4px 0 2px;}
      .fs-rpt-li {font-size:.94rem;color:#1F2937;line-height:1.55;margin:8px 0;padding:8px 0 8px 14px;border-left:2px solid #E2E8F0;}
      .fs-rpt-li b {color:#143257;}
      .fs-rpt-reason {font-size:.9rem;color:#344054;line-height:1.55;margin:7px 0;}
      .fs-rpt-reason b {color:#143257;}
      .fs-rpt-disc {font-size:.74rem;color:#94A3B8;line-height:1.5;border-top:1px solid #E2E8F0;margin-top:26px;padding-top:12px;}
      /* Compact checkpoint cards */
      .fs-chk {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:9px;padding:12px 14px;margin-bottom:9px;box-shadow:0 1px 2px rgba(16,24,40,.04);}
      .fs-chk-top {display:flex;justify-content:space-between;align-items:baseline;gap:12px;}
      .fs-chk-t {font-size:.95rem;font-weight:700;color:#143257;line-height:1.4;}
      .fs-chk-t b {color:#1D4E89;margin-right:6px;}
      .fs-chk-link {font-size:.68rem;font-weight:700;color:#475569;background:#F1F5F9;border:1px solid #E2E8F0;border-radius:5px;padding:2px 8px;white-space:nowrap;}
      .fs-chk-why {font-size:.8rem;color:#667085;margin:4px 0 10px;line-height:1.45;}
      .fs-chk-grid {display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;}
      .fs-chk-cell {border-radius:6px;padding:8px 10px;font-size:.82rem;line-height:1.45;}
      .fs-chk-cell .tx {color:#344054;}
      .fs-chk-h {font-size:.66rem;font-weight:800;letter-spacing:.02em;display:block;margin-bottom:3px;}
      .fs-chk-ok {background:#F0FDF4;border:1px solid #BBF7D0;} .fs-chk-ok .fs-chk-h {color:#15803D;}
      .fs-chk-ng {background:#FEF2F2;border:1px solid #FECACA;} .fs-chk-ng .fs-chk-h {color:#B91C1C;}
      .fs-chk-act {background:#EFF4FB;border:1px solid #C9DBF0;} .fs-chk-act .fs-chk-h {color:#1D4E89;}
      @media (max-width:900px){.fs-chk-grid{grid-template-columns:1fr;}}
      /* External context cards */
      .fs-ctx {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:9px;padding:13px 16px;margin:9px 0;}
      .fs-ctx-title {font-weight:700;color:#143257;text-decoration:none;font-size:.94rem;line-height:1.4;}
      .fs-ctx-title:hover {text-decoration:underline;}
      .fs-ctx-meta {font-size:.72rem;color:#94A3B8;margin:4px 0 9px;}
      .fs-ctx-body {font-size:.9rem;color:#1F2937;line-height:1.62;}
      .fs-ctx-tag {display:inline-block;font-size:.66rem;font-weight:800;color:#1D4E89;background:#EFF4FB;border:1px solid #DCE7F5;border-radius:5px;padding:1px 7px;margin-right:7px;vertical-align:middle;}
      .fs-ctx-foot {font-size:.76rem;color:#667085;margin-top:9px;padding-top:8px;border-top:1px dashed #E2E8F0;line-height:1.5;}
      .fs-ctx-foot b {color:#475569;font-weight:700;}
      /* Sidebar rail label (brand lives in the top bar, not repeated here) */
      [data-testid="stSidebar"] .fs-side-cap {font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;color:#7E9ABA;font-weight:800;padding:2px 0 2px;}
      /* Sidebar analysis stepper */
      [data-testid="stSidebar"] .fs-steps-cap {font-size:.64rem;letter-spacing:.14em;text-transform:uppercase;color:#7E9ABA;font-weight:800;margin:2px 0 12px;}
      [data-testid="stSidebar"] .fs-step {display:flex;gap:11px;align-items:flex-start;padding:0 0 13px;position:relative;}
      [data-testid="stSidebar"] .fs-step:last-child {padding-bottom:0;}
      [data-testid="stSidebar"] .fs-step::before {content:"";position:absolute;left:9.5px;top:21px;bottom:-1px;width:1px;background:#244668;}
      [data-testid="stSidebar"] .fs-step:last-child::before {display:none;}
      [data-testid="stSidebar"] .fs-step-n {flex:none;width:20px;height:20px;border-radius:50%;background:#13335A;border:1px solid #2C5688;color:#9FC4ED;font-size:.7rem;font-weight:800;display:flex;align-items:center;justify-content:center;z-index:1;}
      [data-testid="stSidebar"] .fs-step-t {font-size:.82rem;color:#CAD8E8;line-height:1.4;padding-top:1px;}
      [data-testid="stSidebar"] .fs-principle {margin-top:14px;font-size:.73rem;color:#8AA3BE;line-height:1.5;border-left:2px solid #2C5688;padding-left:10px;}
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


def render_checkpoints(checkpoints: list) -> None:
    """Compact next-quarter checkpoint cards (confirm / not-confirm / model action)."""
    if not checkpoints:
        st.caption("다음 분기에 추적할 확정 포인트가 아직 없습니다.")
        return
    for idx, c in enumerate(checkpoints, 1):
        if isinstance(c, str):
            st.markdown(f'<div class="fs-chk"><div class="fs-chk-t"><b>{idx}.</b>{_esc(c)}</div></div>',
                        unsafe_allow_html=True)
            continue
        link = c.get("valuation_link", "DCF")
        why = _esc(c.get("why", ""))
        st.markdown(
            '<div class="fs-chk">'
            f'<div class="fs-chk-top"><div class="fs-chk-t"><b>{idx}.</b>{_esc(c.get("checkpoint",""))}</div>'
            f'<span class="fs-chk-link">연결 · {_esc(link)}</span></div>'
            + (f'<div class="fs-chk-why">{why}</div>' if why else '<div style="height:6px"></div>')
            + '<div class="fs-chk-grid">'
            f'<div class="fs-chk-cell fs-chk-ok"><span class="fs-chk-h">확인되면</span>'
            f'<span class="tx">{_esc(c.get("if_confirmed", "해당 해석의 신뢰도를 높입니다."))}</span></div>'
            f'<div class="fs-chk-cell fs-chk-ng"><span class="fs-chk-h">확인 안 되면</span>'
            f'<span class="tx">{_esc(c.get("if_not_confirmed", "해당 해석의 신뢰도를 낮춥니다."))}</span></div>'
            f'<div class="fs-chk-cell fs-chk-act"><span class="fs-chk-h">모델 반영</span>'
            f'<span class="tx">{_esc(c.get("action", "연결 가정을 재검토합니다."))}</span></div>'
            '</div></div>',
            unsafe_allow_html=True,
        )


def render_context_items(items: list[dict]) -> None:
    """External context cards: readable lead → snippet → keyword/caveat footnote."""
    if not items:
        st.caption("키워드가 매칭된 외부 정황 자료가 없습니다.")
        return
    for it in items:
        desc = " ".join(str(it.get("description") or "").split())
        if len(desc) > 240:
            desc = desc[:240].rstrip() + "…"
        if not desc:
            desc = "제목 기준으로만 매칭된 자료입니다. 원문 확인 전에는 투자 근거로 쓰지 않습니다."
        kws = ", ".join(it.get("matched_keywords", [])[:4]) or "키워드 미확인"
        caveat = ("사실 확정이 아니라 가능한 원인을 넓혀 보는 참고용입니다."
                  if it.get("source") == "Naver Blog" else "DART 숫자와 맞을 때만 해석 근거로 사용합니다.")
        meta = " · ".join(str(x) for x in [it.get("date"), it.get("source"), it.get("evidence_level", "Context")] if x)
        url = _esc(str(it.get("url") or "#"))
        st.markdown(
            '<div class="fs-ctx">'
            f'<a class="fs-ctx-title" href="{url}" target="_blank">{_esc(it.get("title") or "외부 자료")}</a>'
            f'<div class="fs-ctx-meta">{_esc(meta)}</div>'
            f'<div class="fs-ctx-body"><span class="fs-ctx-tag">참고 정황</span>{_esc(desc)}</div>'
            f'<div class="fs-ctx-foot"><b>관련 키워드:</b> {_esc(kws)} · {caveat}</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def render_attribution(attribution: list[dict]) -> None:
    """Render the price-action driver decomposition as an analyst attribution grid."""
    if not attribution:
        st.info("변동요인 분해에 사용할 실적·수급·기대치 데이터가 부족합니다.")
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
    st.markdown('<div class="fs-rail" style="font-weight:700;margin:10px 0 4px;">확인 절차 · 어디서 → 무엇을 → 판정</div>', unsafe_allow_html=True)
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
        st.markdown("**DART 본표가 답한 부분 (작동 원리)**")
        st.caption(interp.get("dart_answer") or "—")
        for ev in item.get("dart_evidence", []):
            st.caption(f"• {ev}")
    with cols[1]:
        st.markdown("**반증 조건**")
        st.caption(f"⛔ {interp.get('falsifier','')}")


def render_header(slim: bool = False) -> None:
    if slim:
        st.markdown(
            '<div class="fs-bar"><div class="fs-bar-brand">Fin<span>Sight</span></div>'
            '<div class="fs-product-tag">ANALYST WORKBENCH</div></div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        '<div class="fs-masthead"><div><div class="fs-kicker">FILING-LED EQUITY RESEARCH</div>'
        '<div class="fs-brand">Fin<span>Sight</span></div><div class="fs-subtitle">'
        '실적 변화의 원인을 추적하고 밸류에이션까지 잇는 공시 기반 리서치 워크벤치.</div>'
        '</div><div class="fs-product-tag">ANALYST WORKBENCH</div></div>',
        unsafe_allow_html=True,
    )


_LANDING_FEATURES = [
    ("이상 탐지", "전 계정을 자체 과거 범위와 비교해, 통계적으로 벗어난 항목만 가려냅니다."),
    ("원인 추적", "DART 주석·공시·뉴스에서 변화의 원인을 근거 강도순으로, 확인 절차까지 함께 제시합니다."),
    ("동종기업 검증", "같은 신호가 회사만의 문제인지 업종 공통 현상인지 자동 추천된 비교군으로 가립니다."),
    ("가치평가 연결", "판관비 bottom-up OPM·동종기업 베타로 DCF·PER·EV/EBITDA를 교차검증합니다."),
]

_LANDING_USECASES = [
    ("어닝 쇼크 직후", "꺾인 마진이 원가율 탓인지 판관비 탓인지 한 번에 분해합니다."),
    ("주가가 실적과 따로 놀 때", "수익률을 펀더멘털·기대치·수급·촉매 기여로 나눠 읽습니다."),
    ("목표가 점검", "단일 숫자 대신 DCF·멀티플 방법별 밴드로 교차검증합니다."),
]


_PROCESS_STEPS = [
    "과거·기대치 대비 실적 점검",
    "DART 공시 계정으로 원인 분해",
    "동종기업과 교차 검증",
    "수급·공시·시장 정황 확인",
    "검증 가능한 투자 논점 도출",
    "DCF·멀티플로 가치 교차검증",
]


def render_process_steps() -> None:
    """Sidebar analysis pipeline shown as a connected stepper, not a bare list."""
    steps = "".join(
        f'<div class="fs-step"><div class="fs-step-n">{i}</div>'
        f'<div class="fs-step-t">{_esc(text)}</div></div>'
        for i, text in enumerate(_PROCESS_STEPS, 1)
    )
    st.markdown(
        '<div class="fs-steps-cap">분석 프로세스</div>'
        f'<div class="fs-steps">{steps}</div>'
        '<div class="fs-principle">근거가 부족하면 원인을 단정하지 않고, '
        '무엇을 어떻게 확인할지 절차로 안내합니다.</div>',
        unsafe_allow_html=True,
    )


_HERO_LEAD = '숫자의 변화에서 <em>Why</em>를 찾고, <em>Valuation</em>까지 잇습니다.'
_HERO_SUB = ('DART 재무·공시, 시세·수급, 동종기업을 한자리에서 교차검증합니다. '
             '이상 신호를 자동으로 짚어 원인을 근거 강도순으로 제시하고, bottom-up DCF 가정으로 연결합니다.')


def render_landing(examples: list[str] | None = None) -> None:
    """Pre-analysis cover: value proposition, capability grid, use-cases, start cue."""
    features = "".join(
        f'<div class="fs-feature"><div class="fs-feature-k">{i:02d}</div>'
        f'<div class="fs-feature-t">{_esc(title)}</div>'
        f'<div class="fs-feature-d">{_esc(desc)}</div></div>'
        for i, (title, desc) in enumerate(_LANDING_FEATURES, 1)
    )
    usecases = "".join(
        f'<div class="fs-usecase"><div class="fs-usecase-h">{_esc(head)}</div>'
        f'<div class="fs-usecase-d">{_esc(desc)}</div></div>'
        for head, desc in _LANDING_USECASES
    )
    example_text = ""
    if examples:
        example_text = f'<div class="fs-cta-ex">예: {_esc(" · ".join(examples[:3]))}</div>'
    hero = f'<div class="fs-hero"><div class="fs-hero-lead">{_HERO_LEAD}</div><div class="fs-hero-sub">{_HERO_SUB}</div></div>'
    st.markdown(
        hero
        + '<div class="fs-cap">핵심 기능</div>'
        + f'<div class="fs-feature-grid">{features}</div>'
        + '<div class="fs-cap">이럴 때 써보세요</div>'
        + f'<div class="fs-usecases">{usecases}</div>'
        + '<div class="fs-cta"><span class="fs-cta-arrow">←</span>'
        + f'<div>왼쪽 사이드바에서 기업명을 입력하고 <b>분석 실행</b>을 누르면 시작됩니다.{example_text}</div>'
        + '</div>',
        unsafe_allow_html=True,
    )


def valuation_range_band(current_price: float | None, valuation_range: dict) -> go.Figure:
    """Compact price-band view for the top of the valuation tab."""
    low = valuation_range.get("low")
    mid = valuation_range.get("mid")
    high = valuation_range.get("high")
    points = [
        ("보수적", low, "#64748B"),
        ("기준", mid, "#1D4E89"),
        ("낙관적", high, "#94A3B8"),
    ]
    valid_values = [float(v) for _, v, _ in points if v is not None]
    if current_price is not None:
        valid_values.append(float(current_price))
    fig = go.Figure()
    if low is not None and high is not None:
        fig.add_trace(go.Scatter(
            x=[float(low), float(high)], y=[0, 0], mode="lines",
            line={"color": "#CBD5E1", "width": 14}, hoverinfo="skip", showlegend=False,
        ))
    for label, value, color in points:
        if value is None:
            continue
        fig.add_trace(go.Scatter(
            x=[float(value)], y=[0], mode="markers+text",
            marker={"size": 15, "color": color, "line": {"color": "#FFFFFF", "width": 2}},
            text=[f"{label}<br>{float(value):,.0f}원"], textposition="top center",
            hovertemplate=f"{label} 적정가<br>%{{x:,.0f}}원<extra></extra>",
            showlegend=False,
        ))
    if current_price is not None:
        fig.add_trace(go.Scatter(
            x=[float(current_price)], y=[0], mode="markers+text",
            marker={"symbol": "diamond", "size": 14, "color": "#B42318"},
            text=[f"현재가<br>{float(current_price):,.0f}원"], textposition="bottom center",
            hovertemplate="현재가<br>%{x:,.0f}원<extra></extra>",
            showlegend=False,
        ))
    if valid_values:
        lo, hi = min(valid_values), max(valid_values)
        pad = max((hi - lo) * 0.16, hi * 0.03 if hi else 1)
        x_range = [lo - pad, hi + pad]
    else:
        x_range = None
    fig.update_layout(
        height=190, margin={"l": 14, "r": 14, "t": 36, "b": 22},
        title={"text": "현재 주가가 적정가 범위 안에서 어디에 있는지", "font": {"size": 13, "color": "#475467"}},
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        xaxis={"range": x_range, "tickformat": ",.0f", "showgrid": True, "gridcolor": "#EEF2F6", "title": None},
        yaxis={"visible": False, "range": [-0.7, 0.7]},
    )
    return fig


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
