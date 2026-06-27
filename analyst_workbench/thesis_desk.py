"""Thesis Desk — 사용자의 투자 가설을 '검증 가능한 명제'로 분해하고
지지/반박/부족 근거로 구조화하는 근거-인용 강제형 레이어.

설계 원칙(=FinSight 원칙의 LLM 확장):
1) 사실은 결정론 레이어(룰 엔진)가 만든다. 각 근거에는 출처·신뢰도가 붙는다.
2) LLM은 '오라클'이 아니라 Evidence Ledger 위의 '제한된 작업자'다.
   - 어떤 sub-claim을 '지지/반박'으로 표시하려면 반드시 Ledger 행 id를 인용해야 한다.
   - 인용할 근거가 없으면 '미검증(Missing)'으로 라우팅된다.
3) 코드가 인용된 id를 후검증한다. Ledger에 없는 id(환각 인용)는 출력 전에 제거하고,
   유효 인용이 0이 된 지지/반박 명제는 '미검증'으로 강등한다.

→ 지지 근거는 출처 인용이 강제되고, 환각은 코드가 거른다.
   판단을 대신 내리지 않으면서 '부족한 근거'와 '판단이 바뀌는 조건'을 짚어준다.
"""
from __future__ import annotations

import json
import math
import os

MODEL_DEFAULT = "claude-opus-4-8"
VALID_VERDICTS = {"Supported", "Contradicted", "Mixed", "Unverifiable"}


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _short(text, limit: int = 200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _row(rows: list[dict], prefix: str, kind: str, claim: str, *, value: str = "",
         source: str = "", confidence: str = "Medium") -> None:
    claim = _short(claim)
    if not claim:
        return
    rows.append({
        "id": f"{prefix}{sum(1 for r in rows if r['id'].startswith(prefix)) + 1}",
        "type": kind,
        "claim": claim,
        "value": _short(value, 60),
        "source": _short(source, 60) or "FinSight 분석",
        "confidence": confidence or "Medium",
    })


def build_evidence_ledger(
    thesis: dict | None,
    interpreted: list[dict] | None,
    valuation_range: dict | None,
    context: dict | None,
    latest=None,
) -> list[dict]:
    """룰 엔진들의 출력을 출처·신뢰도가 붙은 평탄한 근거 원장으로 재조립한다."""
    thesis = thesis or {}
    context = context or {}
    rows: list[dict] = []

    # F: 운영 사실 (DART 분기재무 기반)
    for fact in thesis.get("facts", []):
        _row(rows, "F", "fact",
             f"{fact.get('label', '')}: {fact.get('value', '')} — {fact.get('interpretation', '')}",
             value=str(fact.get("value", "")),
             source=fact.get("source", "DART"),
             confidence=fact.get("confidence", "High"))

    # H: 룰 엔진이 세운 투자 가설 (반증조건 포함)
    for hyp in thesis.get("hypotheses", []):
        evidence = ", ".join(hyp.get("evidence", []) or [])
        claim = f"[{hyp.get('title', '가설')}] {hyp.get('explanation', '')}"
        if hyp.get("falsifier"):
            claim += f" (반증조건: {hyp['falsifier']})"
        _row(rows, "H", "hypothesis", claim,
             source=evidence or "투자가설(룰 엔진)",
             confidence=hyp.get("confidence", "Medium"))

    # S: 이상신호별 원인 해석 (근거강도 표기)
    for item in (interpreted or [])[:6]:
        interp = item.get("interpretation", {}) or {}
        causes = interp.get("cause_candidates", []) or []
        top = causes[0] if causes else {}
        _row(rows, "S", "signal",
             f"[{item.get('label', '신호')}] {interp.get('headline', '') or interp.get('narrative', '')}",
             value=str(item.get("value", "")),
             source=top.get("source", "이상탐지"),
             confidence=interp.get("confidence", "Low"))

    # V: 밸류에이션 교차검증 (방법별 + 괴리)
    vr = valuation_range or {}
    price = _num(vr.get("current_price"))
    for method in vr.get("methods", []) or []:
        val = _num(method.get("value"))
        if val is None:
            continue
        gap = f" / 현재가 대비 {(val / price - 1) * 100:+.0f}%" if price and price > 0 else ""
        _row(rows, "V", "valuation",
             f"{method.get('method', '')} 적정가 ≈ {val:,.0f}원{gap}",
             value=f"{val:,.0f}원", source="가치평가 교차검증", confidence="Medium")
    if vr.get("dispersion") is not None:
        _row(rows, "V", "valuation",
             f"밸류에이션 방법 간 편차 {vr['dispersion']:.0f}% — 방법별 결론이 {'크게' if vr['dispersion'] > 30 else '다소'} 갈림",
             source="가치평가 교차검증", confidence="Medium")

    # M: 시장/주가
    market = context.get("market", {}) or {}
    r3 = _num(market.get("return_3m"))
    dd = _num(market.get("drawdown_52w_high"))
    if r3 is not None or dd is not None:
        parts = []
        if r3 is not None:
            parts.append(f"3개월 {r3:+.1f}%")
        if dd is not None:
            parts.append(f"52주 고점 대비 {dd:.1f}%")
        _row(rows, "M", "market", "주가: " + " / ".join(parts),
             source=market.get("source", "Market data"), confidence="High")

    # O: 5% 주주 수급
    for own in (context.get("ownership", []) or []):
        change = _num(own.get("ratio_change"))
        if change is None or abs(change) < 0.3:
            continue
        _row(rows, "O", "ownership",
             f"{own.get('reporter', '주요주주')} 보유비율 {change:+.2f}%p 변동 (수급 {'부담' if change < 0 else '우호'} 후보)",
             source="DART 대량보유 보고", confidence="High")

    # X: 외부 정황 (확정 아님 — 신뢰도 낮음으로 명시)
    for ctx in (thesis.get("context", []) or [])[:6]:
        _row(rows, "X", "external",
             f"[정황] {ctx.get('title', '')}: {ctx.get('summary', ctx.get('description', ''))}",
             source=ctx.get("source", "External"), confidence="Low")

    # C: 다음 분기 확인점 (forward — '판단이 바뀌는 조건' 재료)
    for chk in (thesis.get("checkpoints", []) or [])[:7]:
        _row(rows, "C", "check",
             f"확인점: {chk.get('checkpoint', '')} | 확인되면: {chk.get('if_confirmed', '')} | 안 되면: {chk.get('if_not_confirmed', '')}",
             source="투자판단 체크포인트", confidence="—")

    return rows


def _ledger_text(ledger: list[dict]) -> str:
    lines = []
    for r in ledger:
        conf = f" · 신뢰도 {r['confidence']}" if r["confidence"] not in ("", "—") else ""
        val = f" · {r['value']}" if r["value"] else ""
        lines.append(f"[{r['id']}] ({r['type']}) {r['claim']}{val} · 출처 {r['source']}{conf}")
    return "\n".join(lines)


_SYSTEM = """당신은 FinSight의 리서치 보조자다. 사용자(애널리스트)가 던진 '투자 가설'을 검증 가능한 명제로 분해하고, 아래 Evidence Ledger에 있는 근거만으로 판단을 구조화한다.

절대 규칙:
1. Ledger에 없는 사실을 새로 지어내지 마라. 외부 지식·추측으로 숫자나 사실을 만들지 마라.
2. 어떤 sub-claim을 'Supported(지지)' 또는 'Contradicted(반박)'로 표시하려면 반드시 그 근거의 Ledger id(예: F1, H2, V3)를 citations에 넣어라. 인용할 Ledger 근거가 없으면 verdict는 'Unverifiable'로 하고 citations는 비워라.
3. 매도/매수 같은 최종 투자 판단을 단정하지 마라. 당신의 역할은 '대신 판단'이 아니라 '가설의 강도와 빈틈을 보여주는 것'이다. 확률·설명력 수준의 조심스러운 표현을 쓴다.
4. 지지 근거만 모으지 마라. 같은 비중으로 반박 근거와 '부족한 근거(missing_evidence)'를 반드시 찾아라. missing_evidence는 이 가설을 보고서에 쓰려면 더 확보해야 할 자료 유형을 구체적으로 적는다(예: '해외 매출의 가격효과/물량효과 분해', '기관·외국인 수급 정상화 여부').
5. confidence는 지지·반박·부족 근거의 균형으로 정한다. 부족 근거가 많으면 Medium 이하로 낮춰라.

출력은 아래 JSON 스키마만, 한국어로. 마크다운·설명문 없이 JSON 객체 하나만 출력한다.
{
  "restated_thesis": "사용자 가설을 검증 가능한 한 문장으로 재진술",
  "sub_claims": [
    {"claim": "분해된 세부 명제", "verdict": "Supported|Contradicted|Mixed|Unverifiable", "citations": ["F1","V2"], "reasoning": "근거에 비춘 한두 문장 해석"}
  ],
  "missing_evidence": ["보고서에 쓰려면 더 필요한 자료 유형", "..."],
  "confidence": "High|Medium|Low",
  "what_would_change": "어떤 자료가 어느 방향으로 확인되면 이 판단이 바뀌는지",
  "memo_sentence": "보고서에 그대로 붙일 수 있는 1~2문장 (조심스러운 어투, 근거 기반)"
}"""


def answer_thesis(question: str, ledger: list[dict], company: str,
                  model: str = MODEL_DEFAULT) -> dict:
    """가설 + Ledger → Opus 호출 → 인용 검증을 거친 구조화 결과."""
    question = (question or "").strip()
    if not question:
        return {"error": "empty", "message": "가설이나 질문을 입력해 주세요."}

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("your_"):
        return {
            "error": "no_api_key",
            "message": "ANTHROPIC_API_KEY가 설정되지 않았습니다. .env에 키를 넣으면 Thesis Desk가 활성화됩니다.",
        }

    try:
        import anthropic
    except ImportError:
        return {"error": "no_sdk", "message": "anthropic 패키지가 필요합니다: pip install anthropic"}

    user_msg = (
        f"분석 대상: {company}\n\n"
        f"=== Evidence Ledger (이 안의 근거만 인용 가능) ===\n{_ledger_text(ledger)}\n\n"
        f"=== 사용자 투자 가설 ===\n{question}\n\n"
        "위 규칙대로 JSON만 출력하라."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text
    except Exception as exc:  # noqa: BLE001 — surface any API/parse failure to UI
        return {"error": "api", "message": f"모델 호출 실패: {exc}"}

    try:
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start:end + 1])
    except (ValueError, KeyError) as exc:
        return {"error": "parse", "message": f"응답 파싱 실패: {exc}", "raw": raw[:500]}

    return _validate_citations(parsed, ledger)


def _validate_citations(parsed: dict, ledger: list[dict]) -> dict:
    """환각 인용 제거 + 근거 잃은 지지/반박 명제를 '미검증'으로 강등."""
    valid_ids = {r["id"] for r in ledger}
    ledger_by_id = {r["id"]: r for r in ledger}
    hallucinated: list[str] = []

    claims = parsed.get("sub_claims") or []
    cleaned = []
    for claim in claims:
        cites = claim.get("citations") or []
        kept = [c for c in cites if c in valid_ids]
        hallucinated.extend(c for c in cites if c not in valid_ids)
        verdict = claim.get("verdict", "Unverifiable")
        if verdict not in VALID_VERDICTS:
            verdict = "Unverifiable"
        # 지지/반박/혼재인데 유효 인용이 0 → 미검증 강등
        if verdict in {"Supported", "Contradicted", "Mixed"} and not kept:
            verdict = "Unverifiable"
            claim["downgraded"] = True
        claim["citations"] = kept
        claim["cited_rows"] = [ledger_by_id[c] for c in kept]
        claim["verdict"] = verdict
        cleaned.append(claim)

    parsed["sub_claims"] = cleaned
    parsed["_audit"] = {
        "ledger_size": len(ledger),
        "hallucinated_citations": sorted(set(hallucinated)),
        "supported": sum(1 for c in cleaned if c["verdict"] == "Supported"),
        "contradicted": sum(1 for c in cleaned if c["verdict"] == "Contradicted"),
        "unverifiable": sum(1 for c in cleaned if c["verdict"] == "Unverifiable"),
    }
    return parsed
