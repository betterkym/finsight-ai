import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: excel_builder input.json output.xlsx [previewDir]");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const wb = Workbook.create();

const C = {
  navy: "#0B1F33", navy2: "#173B57", blue: "#DCEAF5", pale: "#F5F7FA",
  line: "#D8DEE6", text: "#17202A", muted: "#667085", green: "#147D64",
  greenBg: "#EAF7F2", red: "#B42318", redBg: "#FDECEC", amber: "#9A6700",
  amberBg: "#FFF4D6", yellow: "#FFF2B2", white: "#FFFFFF", input: "#0000FF",
  link: "#008000",
};
const amountFmt = '#,##0.0;[Red](#,##0.0);-';
const countFmt = '#,##0;[Red](#,##0);-';
const pctFmt = '0.0%;[Red](0.0%);-';
const multipleFmt = '0.0x;[Red](0.0x);-';
const safe = v => v === null || v === undefined || Number.isNaN(v) ? null : v;
const pct = v => safe(v) === null ? null : Number(v) / 100;
const won100m = v => safe(v) === null ? null : Number(v) / 1e8;

function title(sheet, text, subtitle, endCol = "H") {
  sheet.showGridLines = false;
  sheet.mergeCells(`A1:${endCol}1`); sheet.getRange("A1").values = [[text]];
  sheet.getRange(`A1:${endCol}1`).format = { fill: C.navy, font: { color: C.white, bold: true, size: 16 }, rowHeight: 32, verticalAlignment: "center" };
  sheet.mergeCells(`A2:${endCol}2`); sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endCol}2`).format = { fill: C.pale, font: { color: C.muted, italic: true, size: 9 }, rowHeight: 23, wrapText: true };
}
function section(sheet, range, text) {
  sheet.mergeCells(range); const cell = range.split(":")[0]; sheet.getRange(cell).values = [[text]];
  sheet.getRange(range).format = { fill: C.navy2, font: { color: C.white, bold: true }, rowHeight: 22, verticalAlignment: "center" };
}
function header(sheet, range) {
  sheet.getRange(range).format = { fill: C.navy, font: { color: C.white, bold: true }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: C.line }, rowHeight: 28 };
}
function widths(sheet, mapping) { for (const [col, width] of Object.entries(mapping)) sheet.getRange(`${col}:${col}`).format.columnWidth = width; }
function tableBody(sheet, range) { sheet.getRange(range).format = { borders: { preset: "inside", style: "thin", color: C.line }, verticalAlignment: "top", wrapText: true }; }

const latest = data.quarterly[data.quarterly.length - 1] || {};
const thesis = data.thesis || {};
const market = data.marketContext?.market || {};
const valuationRange = data.valuationRange || {};
const assumptions = data.dcf?.assumptions || {};
const researchValuation = data.researchReference?.valuation || {};

// 00 Cover
const cover = wb.worksheets.add("00 Cover");
title(cover, `FinSight | ${data.company}`, `투자 검토 · ${data.asOf} · DART 실적 + 시장 정황 + 밸류에이션 교차검증`, "N");
section(cover, "A4:N4", "핵심 요약");
cover.mergeCells("A5:N5"); cover.getRange("A5").values = [[thesis.headline || "근거 검토"]];
cover.getRange("A5:N5").format = { font: { size: 15, bold: true, color: C.navy }, rowHeight: 28 };
cover.mergeCells("A6:N7"); cover.getRange("A6").values = [[thesis.summary || ""]];
cover.getRange("A6:N7").format = { wrapText: true, verticalAlignment: "top", fill: C.pale, font: { color: C.text, size: 10 } };
cover.getRange("A9:H11").values = [
  ["기준 분기", latest.period, "매출 YoY", pct(latest.revenue_yoy), "OPM", pct(latest.opm), "FCF 마진", pct(latest.fcf_margin)],
  ["현재 주가", safe(data.capital?.current_price), "3개월 수익률", pct(market.return_3m), "52주 고점 대비", pct(market.drawdown_52w_high), "우선 검토", data.scan.filter(x => x.status === "Abnormal").length],
  ["DCF 주당가치", safe(data.dcf?.implied_price), "교차가치 하단", safe(valuationRange.low), "교차가치 중앙", safe(valuationRange.mid), "교차가치 상단", safe(valuationRange.high)],
];
cover.getRange("A9:H11").format = { borders: { preset: "all", style: "thin", color: C.line }, rowHeight: 25 };
for (const col of ["A","C","E","G"]) cover.getRange(`${col}9:${col}11`).format = { font: { bold: true, color: C.muted }, fill: C.pale };
cover.getRange("D9:H9").format.numberFormat = pctFmt; cover.getRange("B10").format.numberFormat = countFmt; cover.getRange("D10:F10").format.numberFormat = pctFmt; cover.getRange("B11:H11").format.numberFormat = countFmt;

section(cover, "A13:G13", "확인된 사실관계");
cover.getRange("A14:D14").values = [["사실", "값", "해석", "출처 / 신뢰도"]]; header(cover, "A14:D14");
const factRows = (thesis.facts || []).map(x => [x.label, x.value, x.interpretation, `${x.source} / ${x.confidence}`]);
cover.getRange(`A15:D${14 + Math.max(factRows.length,1)}`).values = factRows.length ? factRows : [["사실 없음",null,null,null]]; tableBody(cover, `A15:D${14 + Math.max(factRows.length,1)}`);

section(cover, "A22:G22", "주가가 실적과 갈라지는 이유");
cover.getRange("A23:E23").values = [["우선순위", "논점", "해석", "근거", "반증 / 다음 확인"]]; header(cover, "A23:E23");
const hypothesisRows = (thesis.hypotheses || []).map((x,i) => [i+1, `${x.title} (${x.confidence})`, `${x.explanation || ""}${x.so_what ? "\n시사점: " + x.so_what : ""}`, (x.evidence||[]).join(" | "), x.falsifier]);
cover.getRange(`A24:E${23 + Math.max(hypothesisRows.length,1)}`).values = hypothesisRows.length ? hypothesisRows : [[null,"유의미한 비재무 논점 없음",null,null,null]]; tableBody(cover, `A24:E${23 + Math.max(hypothesisRows.length,1)}`);

cover.getRange("J9:L9").values = [["방법", "적정가", "현재가"]]; header(cover, "J9:L9");
const methodRows = (valuationRange.methods || []).map(x => [x.method, safe(x.value), safe(data.capital?.current_price)]);
cover.getRange(`J10:L${9 + Math.max(methodRows.length,1)}`).values = methodRows.length ? methodRows : [["N/A",null,null]];
cover.getRange(`K10:L${9 + Math.max(methodRows.length,1)}`).format.numberFormat = countFmt;
const valueChart = cover.charts.add("bar", cover.getRange(`J9:L${9 + Math.max(methodRows.length,1)}`)); valueChart.title = "방법별 적정가 vs 현재가 (원)"; valueChart.hasLegend = true; valueChart.yAxis = { numberFormatCode: "#,##0" }; valueChart.setPosition("H13", "N27");
widths(cover,{A:12,B:19,C:18,D:42,E:42,F:15,G:14,H:16,J:20,K:16,L:16,M:12,N:12}); cover.freezePanes.freezeRows(4);

// 01 Quarterly (전치: 분기를 열로, 항목을 행으로 — 애널리스트 표준 시계열 레이아웃)
const quarterly = wb.worksheets.add("01 Quarterly");
const qN = data.quarterly.length;
const qLast = String.fromCharCode(64 + 1 + qN); // A=항목, B.. = 분기 (분기 수 ≤ 24 → 최대 Y열)
title(quarterly, `${data.company} | 분기 실적`, "DART 연결재무제표 우선 · 단위 억원 · 결측 임의보정 없음", qLast);
section(quarterly, `A4:${qLast}4`, "과거 실적과 영업 동인");
const qMetrics = [
  ["매출", x=>won100m(x.revenue), amountFmt],
  ["QoQ", x=>pct(x.revenue_qoq), pctFmt],
  ["YoY", x=>pct(x.revenue_yoy), pctFmt],
  ["영업이익", x=>won100m(x.operating_profit), amountFmt],
  ["OPM", x=>pct(x.opm), pctFmt],
  ["순이익", x=>won100m(x.net_income), amountFmt],
  ["CFO", x=>won100m(x.cfo), amountFmt],
  ["CFO 마진", x=>pct(x.cfo_margin), pctFmt],
  ["D&A", x=>won100m(x.depreciation), amountFmt],
  ["CAPEX", x=>won100m(x.capex), amountFmt],
  ["FCF", x=>won100m(x.fcf), amountFmt],
  ["FCF 마진", x=>pct(x.fcf_margin), pctFmt],
  ["원가율", x=>pct(x.cogs_ratio), pctFmt],
  ["판관비율", x=>pct(x.sga_ratio), pctFmt],
  ["매출채권", x=>won100m(x.receivables), amountFmt],
  ["재고", x=>won100m(x.inventory), amountFmt],
  ["매입채무", x=>won100m(x.payables), amountFmt],
  ["운전자본", x=>won100m(x.working_capital), amountFmt],
  ["NWC/매출", x=>pct(x.working_capital_ratio), pctFmt],
  ["ΔNWC", x=>won100m(x.change_in_nwc), amountFmt],
  ["매출채권회전일", x=>safe(x.ar_days), "0.0"],
  ["재고회전일", x=>safe(x.inventory_days), "0.0"],
  ["매입채무회전일", x=>safe(x.payable_days), "0.0"],
  ["유동비율", x=>pct(x.current_ratio), pctFmt],
  ["부채비율", x=>pct(x.debt_ratio), pctFmt],
];
quarterly.getRange(`A5:${qLast}5`).values=[["항목", ...data.quarterly.map(x=>x.period)]]; header(quarterly,`A5:${qLast}5`);
const qBody = qMetrics.map(([label, fn]) => [label, ...data.quarterly.map(fn)]);
quarterly.getRange(`A6:${qLast}${5+qMetrics.length}`).values=qBody; tableBody(quarterly,`A6:${qLast}${5+qMetrics.length}`);
qMetrics.forEach(([label, fn, fmt], i) => { quarterly.getRange(`B${6+i}:${qLast}${6+i}`).format.numberFormat=fmt; });
quarterly.getRange(`A6:A${5+qMetrics.length}`).format.font={bold:true,color:C.navy};
quarterly.getRange(`A6:A${5+qMetrics.length}`).format.fill=C.pale;
quarterly.getRange(`B7:${qLast}8`).conditionalFormats.add("colorScale",{colors:[C.redBg,C.white,C.greenBg],thresholds:["min","50%","max"]});
quarterly.freezePanes.freezeRows(5); quarterly.freezePanes.freezeColumns(1);
quarterly.getRange("A:A").format.columnWidth=16;
for(let c=2;c<=1+qN;c++) quarterly.getRange(`${String.fromCharCode(64+c)}:${String.fromCharCode(64+c)}`).format.columnWidth=12;

// 02 Earnings Bridge
const earnings = wb.worksheets.add("02 Earnings Bridge");
title(earnings, `${data.company} | 실적·기대치 변동 분해`, "실적-과거 비교, 마진 변동분해, 증권사 기대치 참고", "L");
section(earnings,"A4:L4","분기별 마진 변동 분해");
earnings.getRange("A5:I5").values=[["분기","매출 QoQ","직전 OPM","원가율 기여","판관비율 기여","기타 기여","현재 OPM","패턴","해석"]]; header(earnings,"A5:I5");
const bridgeRows=(data.marginBridge||[]).map(x=>[x.period,pct(x.revenue_change_pct),pct(x.previous_opm),pct(x.cogs_contribution_pp),pct(x.sga_contribution_pp),pct(x.other_contribution_pp),pct(x.current_opm),x.pattern,x.comment]);
earnings.getRange(`A6:I${5+Math.max(bridgeRows.length,1)}`).values=bridgeRows.length?bridgeRows:[["데이터 없음",null,null,null,null,null,null,null,null]]; tableBody(earnings,`A6:I${5+Math.max(bridgeRows.length,1)}`);
earnings.getRange(`B6:G${5+Math.max(bridgeRows.length,1)}`).format.numberFormat=pctFmt;
section(earnings,"A18:L18","기대치 괴리 참고");
earnings.getRange("A19:G19").values=[["일자","지표","실제 서프라이즈","사실","출처","근거 등급","판단 활용"]]; header(earnings,"A19:G19");
const expectationRows=(data.researchReference?.expectations||[]).map(x=>[x.date,x.metric,pct(x.value),x.fact,x.source,x.evidence_level,"어닝 비트인데 주가 약세 = 지속성·수급 점검"]);
earnings.getRange(`A20:G${19+Math.max(expectationRows.length,1)}`).values=expectationRows.length?expectationRows:[[null,"컨센서스 참고 없음",null,null,null,null,"리서치 추정치 입력·정규화"]]; tableBody(earnings,`A20:G${19+Math.max(expectationRows.length,1)}`); earnings.getRange(`C20:C${19+Math.max(expectationRows.length,1)}`).format.numberFormat=pctFmt;
const commentaryStart=22+Math.max(expectationRows.length,1);
section(earnings,`A${commentaryStart}:L${commentaryStart}`,"최신 분기 해석 — 무엇이 바뀌었나가 아니라 그래서 무엇을");
earnings.getRange(`A${commentaryStart+1}:H${commentaryStart+1}`).values=[["관찰","판정","변화 내용","근거","시사점","투자자 행동","모델 연결","다음 확인 포인트"]]; header(earnings,`A${commentaryStart+1}:H${commentaryStart+1}`);
const trackerRows=(data.trackerCommentary||[]).map(x=>[
  x.title,
  `${x.verdict||"Review"} / ${x.confidence||"Medium"}`,
  x.read,
  (x.evidence||[]).join("\n"),
  x.so_what,
  x.action||x.so_what,
  x.model_link||"DCF",
  x.next
]);
earnings.getRange(`A${commentaryStart+2}:H${commentaryStart+1+Math.max(trackerRows.length,1)}`).values=trackerRows.length?trackerRows:[["최신 분기에 특이 조합 없음","중립","최신 분기는 대체로 예상 범위 내","유의미한 이상 변동 없음","더 뚜렷한 패턴이 나올 때까지 기준 가정 유지","기준 시나리오 유지; 민감도 점검","기준 시나리오","다음 DART 공시 점검"]];
tableBody(earnings,`A${commentaryStart+2}:H${commentaryStart+1+Math.max(trackerRows.length,1)}`);
earnings.freezePanes.freezeRows(5); widths(earnings,{A:24,B:16,C:44,D:42,E:42,F:42,G:24,H:42,I:18,J:15,K:15,L:15});

// 03 Thesis Evidence
const evidence = wb.worksheets.add("03 Thesis Evidence");
title(evidence, `${data.company} | 투자 논점·근거·반증`, "사실과 논점을 분리하며, 블로그는 1차 근거로 쓰지 않습니다", "K");
section(evidence,"A4:K4","투자 논점 트리");
evidence.getRange("A5:G5").values=[["우선순위","논점","신뢰도","해석","근거","반증","연결 URL"]]; header(evidence,"A5:G5");
const hRows=(thesis.hypotheses||[]).map((x,i)=>[i+1,x.title,x.confidence,`${x.explanation || ""}${x.so_what ? "\n시사점: " + x.so_what : ""}`,(x.evidence||[]).join(" | "),x.falsifier,x.url||null]);
evidence.getRange(`A6:G${5+Math.max(hRows.length,1)}`).values=hRows.length?hRows:[[null,"논점 없음",null,null,null,null,null]]; tableBody(evidence,`A6:G${5+Math.max(hRows.length,1)}`);
section(evidence,"A16:K16","다음 분기 체크포인트 — 판단 규칙");
evidence.getRange("A17:F17").values=[["우선순위","체크포인트","확인되면","확인 안 되면","모델 반영","연결 밸류 동인"]]; header(evidence,"A17:F17");
const checkpointRows=(thesis.checkpoints||[]).map((x,i)=>typeof x==="string"
  ? [i+1,x,"근거가 개선되면 예측 동인 갱신","확인 안 되면 보수 가정 유지","단일 약한 신호로 밸류 변경 금지","가정 점검"]
  : [i+1,x.checkpoint,x.if_confirmed,x.if_not_confirmed,x.action,x.valuation_link]);
evidence.getRange(`A18:F${17+Math.max(checkpointRows.length,1)}`).values=checkpointRows.length?checkpointRows:[[null,"체크포인트 없음",null,null,null,null]]; tableBody(evidence,`A18:F${17+Math.max(checkpointRows.length,1)}`);
section(evidence,"A28:K28","외부 정황 — 신뢰도순");
evidence.getRange("A29:H29").values=[["일자","제목","요약","출처","근거 등급","매칭 키워드","URL","활용"]]; header(evidence,"A29:H29");
const externalRows=(thesis.context||[]).map(x=>[x.date,x.title,x.summary||x.description,x.source,x.evidence_level,(x.matched_keywords||[]).join(", "),x.url,x.source==="Naver Blog"?"논점 탐색용":"정황 보강용"]);
evidence.getRange(`A30:H${29+Math.max(externalRows.length,1)}`).values=externalRows.length?externalRows:[[null,"매칭된 정황 없음",null,null,null,null,null,null]]; tableBody(evidence,`A30:H${29+Math.max(externalRows.length,1)}`);
evidence.freezePanes.freezeRows(5); widths(evidence,{A:10,B:30,C:55,D:18,E:24,F:28,G:46,H:26,I:12,J:12,K:12});

// 04 Peers & Multiples
const peers = wb.worksheets.add("04 Peers Multiples");
title(peers, `${data.company} | Peer·멀티플 교차검증`, `비교군: ${data.peerNames.join(", ") || "없음"} · 리서치 멀티플은 정답이 아니라 참고`, "J");
section(peers,"A4:J4","영업 벤치마크"); peers.getRange("A5:G5").values=[["지표","단위","분석기업","동종기업 중앙값","격차","비교기업 수","해석"]]; header(peers,"A5:G5");
const pRows=data.peerBenchmark.length?data.peerBenchmark.map(x=>[x["지표"],x["단위"],safe(x["분석기업"]),safe(x["동종기업 중앙값"]),safe(x["격차"]),safe(x["비교기업 수"]),safe(x["격차"])===null?"데이터 부족":(x["격차"]>0?"동종기업 상회":"동종기업 하회")]):[["동종기업 데이터 없음",null,null,null,null,0,"비교군 점검"]];
peers.getRange(`A6:G${5+pRows.length}`).values=pRows; tableBody(peers,`A6:G${5+pRows.length}`);
section(peers,"A18:J18","밸류에이션 방법"); peers.getRange("A19:G19").values=[["방법","케이스","배수","적정가","상승여력","근거","용도"]]; header(peers,"A19:G19");
const mRows=(data.multipleValuation||[]).map(x=>[x.method,x.case,safe(x.multiple),safe(x.implied_price),pct(x.upside),x.basis,"교차검증"]);
peers.getRange(`A20:G${19+Math.max(mRows.length,1)}`).values=mRows.length?mRows:[["멀티플 밸류에이션 없음",null,null,null,null,null,null]]; tableBody(peers,`A20:G${19+Math.max(mRows.length,1)}`);
peers.getRange(`C20:C${19+Math.max(mRows.length,1)}`).format.numberFormat=multipleFmt; peers.getRange(`D20:D${19+Math.max(mRows.length,1)}`).format.numberFormat=countFmt; peers.getRange(`E20:E${19+Math.max(mRows.length,1)}`).format.numberFormat=pctFmt;
peers.freezePanes.freezeRows(5); widths(peers,{A:24,B:30,C:12,D:16,E:12,F:48,G:18,H:12,I:12,J:12});

// 05 DCF
const dcf = wb.worksheets.add("05 DCF");
title(dcf, `${data.company} | 드라이버 기반 DCF`, "매출/OPM fade · NOPAT + D&A - CAPEX - ΔNWC · Gordon 성장 · 파란/노란 셀 편집 가능", "H");
section(dcf,"A4:D4","가정과 가드레일"); dcf.getRange("A5:D5").values=[["가정","입력값","근거 / 출처","구분"]]; header(dcf,"A5:D5");
const ev=Object.fromEntries((data.dcfEvidence||[]).map(x=>[x.assumption,x]));
const aRows=[
  ["1년차 매출성장률",pct(assumptions.revenue_growth),(ev["매출 성장률"]?.evidence||[]).join(" | ")||ev["매출 성장률"]?.source,"근거 반영"],
  ["5년차 매출성장률",pct(assumptions.revenue_growth_terminal),"지속가능 성장률로 수렴","Review"],
  ["1년차 EBIT 마진",pct(assumptions.opm),(ev["영업이익률"]?.evidence||[]).join(" | ")||ev["영업이익률"]?.source,"근거 반영"],
  ["5년차 EBIT 마진",pct(assumptions.opm_terminal),"최근 마진 중앙값 / 정상화","Review"],
  ["D&A / 매출",pct(assumptions.depreciation_ratio),"DART 과거 비율","Auto"],
  ["CAPEX / 매출",pct(assumptions.capex_ratio),"DART 과거 비율; 현재 이상치가 높으면 유지","Watch"],
  ["NWC / 매출",pct(assumptions.nwc_ratio),"매출채권+재고-매입채무 / 매출","Auto"],
  ["세율",pct(assumptions.tax_rate),"모델 가정","Review"],
  ["무위험수익률",pct(assumptions.risk_free_rate),"ECOS 국고채 10년","Auto"],
  ["ERP",pct(assumptions.erp),"KICPA 참고; 사용자 검토","Review"],
  ["조정 Beta",safe(assumptions.beta),data.recommendations?.beta?.basis||"FDR 원시 베타를 시장 쪽으로 조정; 0.50 하한","Guardrail"],
  ["부채 비중",pct(assumptions.debt_weight),data.capital?.debt_weight_source,"Auto"],
  ["세전 타인자본비용",pct(assumptions.cost_of_debt),"차입 주석과 대조","Review"],
  ["영구성장률",pct(assumptions.perpetual_growth),"GDP 기반 지속가능 범위","Review"],
  ["발행주식수",safe(data.capital?.shares_outstanding),data.capital?.share_source,"Auto"],
  ["순차입금 (억원)",won100m(data.capital?.net_debt),"이자부채 − 현금","Auto"],
  ["현재가",safe(data.capital?.current_price),"최근 종가","Market"],
];
dcf.getRange("A6:D22").values=aRows; tableBody(dcf,"A6:D22"); dcf.getRange("B6:B22").format={fill:C.yellow,font:{color:C.input}};
for(let r=6;r<=19;r++) if(r!==16&&r!==20&&r!==21&&r!==22) dcf.getRange(`B${r}`).format.numberFormat=pctFmt;
dcf.getRange("B16").format.numberFormat=multipleFmt; dcf.getRange("B20:B22").format.numberFormat=countFmt; dcf.getRange("B21").format.numberFormat=amountFmt;
section(dcf,"A24:H24","예측과 FCFF 빌드"); dcf.getRange("A25:H25").values=[["항목","LTM",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`,"수식 설명"]]; header(dcf,"A25:H25");
dcf.getRange("A26:A38").values=[["매출"],["성장률"],["EBIT 마진"],["EBIT"],["현금세금"],["NOPAT"],["D&A"],["CAPEX"],["NWC"],["NWC 증감"],["FCFF"],["할인계수"],["FCFF 현재가치"]];
dcf.getRange("B26").values=[[data.ltmRevenue]]; dcf.getRange("B28").values=[[pct(latest.opm)]]; dcf.getRange("B29").formulas=[["=B26*B28"]]; dcf.getRange("B31").formulas=[["=B29*(1-$B$13)"]]; dcf.getRange("B32").formulas=[["=B26*$B$10"]]; dcf.getRange("B33").formulas=[["=B26*$B$11"]]; dcf.getRange("B34").formulas=[["=B26*$B$12"]];
for(let col=3;col<=7;col++){
  const L=String.fromCharCode(64+col),P=String.fromCharCode(63+col),step=col-3;
  dcf.getRange(`${L}27`).formulas=[[`=$B$6+($B$7-$B$6)*${step}/4`]];
  dcf.getRange(`${L}26`).formulas=[[`=${P}26*(1+${L}27)`]];
  if (Array.isArray(assumptions.opm_path) && assumptions.opm_path.length >= 5 && assumptions.opm_path[step] !== null && assumptions.opm_path[step] !== undefined) {
    dcf.getRange(`${L}28`).values=[[pct(assumptions.opm_path[step])]];
  } else {
    dcf.getRange(`${L}28`).formulas=[[`=$B$8+($B$9-$B$8)*${step}/4`]];
  }
  dcf.getRange(`${L}29`).formulas=[[`=${L}26*${L}28`]]; dcf.getRange(`${L}30`).formulas=[[`=${L}29*$B$13`]]; dcf.getRange(`${L}31`).formulas=[[`=${L}29-${L}30`]];
  dcf.getRange(`${L}32`).formulas=[[`=${L}26*$B$10`]]; dcf.getRange(`${L}33`).formulas=[[`=${L}26*$B$11`]]; dcf.getRange(`${L}34`).formulas=[[`=${L}26*$B$12`]]; dcf.getRange(`${L}35`).formulas=[[`=${L}34-${P}34`]];
  dcf.getRange(`${L}36`).formulas=[[`=${L}31+${L}32-${L}33-${L}35`]]; dcf.getRange(`${L}37`).formulas=[[`=1/(1+$B$42)^${col-2}`]]; dcf.getRange(`${L}38`).formulas=[[`=${L}36*${L}37`]];
}
dcf.getRange("H26:H38").values=[["직전 매출 × (1+성장률)"],["선형 fade: 1년차→5년차"],["가능 시 bottom-up 판관비 OPM 경로; 아니면 선형 fade"],["매출 × EBIT 마진"],["EBIT × 세율"],["EBIT − 현금세금"],["매출 × D&A 비율"],["매출 × CAPEX 비율"],["매출 × NWC 비율"],["기말 NWC − 직전 NWC"],["NOPAT + D&A - CAPEX - ΔNWC"],["1/(1+WACC)^t"],["FCFF × 할인계수"]];
for(const row of [27,28,37]) dcf.getRange(`B${row}:G${row}`).format.numberFormat=pctFmt; for(const row of [26,29,30,31,32,33,34,35,36,38]) dcf.getRange(`B${row}:G${row}`).format.numberFormat=amountFmt;
section(dcf,"A40:D40","밸류에이션 산출과 점검"); dcf.getRange("A41:B52").values=[["자기자본비용",null],["WACC",null],["예측 FCFF 현재가치",null],["터미널가치",null],["터미널 현재가치",null],["기업가치(EV)",null],["주주가치",null],["주당 적정가",null],["TV / EV",null],["WACC-g 스프레드",null],["상승/(하락) 여력",null],["모델 상태",null]];
dcf.getRange("B41").formulas=[["=$B$14+$B$16*$B$15"]]; dcf.getRange("B42").formulas=[["=B41*(1-$B$17)+$B$18*(1-$B$13)*$B$17"]]; dcf.getRange("B43").formulas=[["=SUM(C38:G38)"]]; dcf.getRange("B44").formulas=[["=G36*(1+$B$19)/(B42-$B$19)"]]; dcf.getRange("B45").formulas=[["=B44*G37"]]; dcf.getRange("B46").formulas=[["=B43+B45"]]; dcf.getRange("B47").formulas=[["=B46-$B$21"]]; dcf.getRange("B48").formulas=[["=B47*100000000/$B$20"]]; dcf.getRange("B49").formulas=[["=B45/B46"]]; dcf.getRange("B50").formulas=[["=B42-$B$19"]]; dcf.getRange("B51").formulas=[["=B48/$B$22-1"]]; dcf.getRange("B52").formulas=[["=IF(AND(B50>=2%,B49<=75%,B20>0),\"PASS\",\"REVIEW\")"]];
dcf.getRange("B41:B42").format.numberFormat=pctFmt; dcf.getRange("B43:B47").format.numberFormat=amountFmt; dcf.getRange("B48").format.numberFormat=countFmt; dcf.getRange("B49:B51").format.numberFormat=pctFmt; dcf.getRange("A46:B52").format.borders={top:{style:"thin",color:C.navy}}; dcf.getRange("B52").conditionalFormats.add("containsText",{text:"PASS",format:{fill:C.greenBg,font:{color:C.green,bold:true}}}); dcf.getRange("B52").conditionalFormats.add("containsText",{text:"REVIEW",format:{fill:C.amberBg,font:{color:C.amber,bold:true}}});
dcf.freezePanes.freezeRows(5); widths(dcf,{A:28,B:18,C:48,D:18,E:14,F:14,G:14,H:34});

// 06 Scenarios
const scenarios=wb.worksheets.add("06 Scenarios");
title(scenarios,`${data.company} | 시나리오 밸류에이션`,"Bear/Base/Bull이 성장률·마진·WACC를 재계산 — 결과는 붙여넣은 값이 아니라 수식","R");
section(scenarios,"A4:R4","시나리오 동인과 재계산 밸류에이션");
scenarios.getRange("A5:R5").values=[["시나리오","성장률 Δ","OPM Δ","WACC Δ","1년차 매출","2년차 매출","3년차 매출","4년차 매출","5년차 매출","1년차 FCFF","2년차 FCFF","3년차 FCFF","4년차 FCFF","5년차 FCFF","PV FCFF","PV 터미널","주주가치","주당가격"]]; header(scenarios,"A5:R5");
scenarios.getRange("A6:D8").values=[["Bear",-0.01,-0.01,0.01],["Base",0,0,0],["Bull",0.01,0.01,-0.005]]; scenarios.getRange("B6:D8").format={fill:C.yellow,font:{color:C.input},numberFormat:pctFmt};
for(let row=6;row<=8;row++){
  for(let col=5;col<=9;col++){
    const L=String.fromCharCode(64+col),P=String.fromCharCode(63+col),step=col-5;
    const prev=col===5?"'05 DCF'!$B$26":`${P}${row}`;
    scenarios.getRange(`${L}${row}`).formulas=[[`=${prev}*(1+('05 DCF'!$B$6+$B${row})+(('05 DCF'!$B$7-'05 DCF'!$B$6)*${step}/4))`]];
  }
  for(let col=10;col<=14;col++){
    const L=String.fromCharCode(64+col),revL=String.fromCharCode(59+col),step=col-10;
    const priorRev=step===0?"'05 DCF'!$B$26":`${String.fromCharCode(58+col)}${row}`;
    const margin=`('05 DCF'!$B$8+$C${row})+(('05 DCF'!$B$9-'05 DCF'!$B$8)*${step}/4)`;
    scenarios.getRange(`${L}${row}`).formulas=[[`=${revL}${row}*${margin}*(1-'05 DCF'!$B$13)+${revL}${row}*'05 DCF'!$B$10-${revL}${row}*'05 DCF'!$B$11-(${revL}${row}-${priorRev})*'05 DCF'!$B$12`]];
  }
  scenarios.getRange(`O${row}`).formulas=[[`=SUM(J${row}/(1+('05 DCF'!$B$42+$D${row}))^1,K${row}/(1+('05 DCF'!$B$42+$D${row}))^2,L${row}/(1+('05 DCF'!$B$42+$D${row}))^3,M${row}/(1+('05 DCF'!$B$42+$D${row}))^4,N${row}/(1+('05 DCF'!$B$42+$D${row}))^5)`]];
  scenarios.getRange(`P${row}`).formulas=[[`=(N${row}*(1+'05 DCF'!$B$19)/(('05 DCF'!$B$42+$D${row})-'05 DCF'!$B$19))/(1+('05 DCF'!$B$42+$D${row}))^5`]];
  scenarios.getRange(`Q${row}`).formulas=[[`=O${row}+P${row}-'05 DCF'!$B$21`]]; scenarios.getRange(`R${row}`).formulas=[[`=Q${row}*100000000/'05 DCF'!$B$20`]];
}
scenarios.getRange("E6:Q8").format.numberFormat=amountFmt; scenarios.getRange("R6:R8").format.numberFormat=countFmt; tableBody(scenarios,"A6:R8");
section(scenarios,"A11:H11","해석"); scenarios.getRange("A12:D15").values=[["구분","의미","행동","연결 점검"],["Bear","성장률/마진 하향 + WACC 상향","해외 물량·공장 가동 시점이 부진할 때 사용","05 DCF TV/EV"],["Base","근거 반영 기준 시나리오","기본 검토 출발점","05 DCF 모델 상태"],["Bull","물량 성장 + 영업 레버리지 + 위험프리미엄 하락","연속 2개 분기 확인 필요","03 Thesis Evidence"]]; header(scenarios,"A12:D12"); tableBody(scenarios,"A13:D15"); scenarios.freezePanes.freezeRows(5); widths(scenarios,{A:12,B:24,C:28,D:20,E:14,F:14,G:14,H:14,I:14,J:14,K:14,L:14,M:14,N:14,O:14,P:14,Q:15,R:16});

// 07 Checks Sources
const checks=wb.worksheets.add("07 Checks Sources");
title(checks,`${data.company} | 점검·출처·버전 로그`,"PASS는 계산·출처 완전성을 검증할 뿐, 투자 결론을 보증하지 않습니다","J");
section(checks,"A4:J4","모델 점검"); checks.getRange("A5:G5").values=[["점검","실제","기대","차이","허용","상태","조치 / 메모"]]; header(checks,"A5:G5");
checks.getRange("A6:G13").values=[["WACC-g 스프레드",null,0.02,null,0,null,"베타/WACC 상향 또는 터미널 성장 하향"],["TV/EV",null,0.75,null,0,null,"터미널 가정 점검"],["발행주식수 확보",null,1,null,0,null,"DART 주식수 fallback 확인"],["매출 완전성",data.quality.find(x=>x.field==="매출액")?.missing_quarters||0,0,null,0,null,"XBRL 매핑 확인"],["영업이익 완전성",data.quality.find(x=>x.field==="영업이익")?.missing_quarters||0,0,null,0,null,"XBRL 매핑 확인"],["FCFF 수식",null,null,null,0,null,"NOPAT + D&A - CAPEX - ΔNWC"],["주주가치 브릿지",null,null,null,0,null,"EV − 순차입금"],["종합 모델 상태",null,null,null,0,null,"필수 점검 전체"]];
checks.getRange("B6").formulas=[["='05 DCF'!B50"]]; checks.getRange("D6").formulas=[["=B6-C6"]]; checks.getRange("F6").formulas=[["=IF(B6>=C6,\"OK\",\"FAIL\")"]];
checks.getRange("B7").formulas=[["='05 DCF'!B49"]]; checks.getRange("D7").formulas=[["=C7-B7"]]; checks.getRange("F7").formulas=[["=IF(B7<=C7,\"OK\",\"FAIL\")"]];
checks.getRange("B8").formulas=[["='05 DCF'!B20"]]; checks.getRange("D8").formulas=[["=B8-C8"]]; checks.getRange("F8").formulas=[["=IF(B8>=C8,\"OK\",\"FAIL\")"]];
for(let r=9;r<=10;r++){checks.getRange(`D${r}`).formulas=[[`=B${r}-C${r}`]];checks.getRange(`F${r}`).formulas=[[`=IF(ABS(D${r})<=E${r},\"OK\",\"FAIL\")`]];}
checks.getRange("B11").formulas=[["='05 DCF'!G36"]]; checks.getRange("C11").formulas=[["='05 DCF'!G31+'05 DCF'!G32-'05 DCF'!G33-'05 DCF'!G35"]]; checks.getRange("D11").formulas=[["=B11-C11"]]; checks.getRange("F11").formulas=[["=IF(ABS(D11)<0.01,\"OK\",\"FAIL\")"]];
checks.getRange("B12").formulas=[["='05 DCF'!B47"]]; checks.getRange("C12").formulas=[["='05 DCF'!B46-'05 DCF'!B21"]]; checks.getRange("D12").formulas=[["=B12-C12"]]; checks.getRange("F12").formulas=[["=IF(ABS(D12)<0.01,\"OK\",\"FAIL\")"]]; checks.getRange("F13").formulas=[["=IF(COUNTIF(F6:F12,\"FAIL\")=0,\"PASS\",\"REVIEW\")"]];
checks.getRange("B6:E7").format.numberFormat=pctFmt; checks.getRange("B11:E12").format.numberFormat=amountFmt; checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"OK",format:{fill:C.greenBg,font:{color:C.green,bold:true}}}); checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"FAIL",format:{fill:C.redBg,font:{color:C.red,bold:true}}}); checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"REVIEW",format:{fill:C.amberBg,font:{color:C.amber,bold:true}}});
section(checks,"A16:J16","출처 로그"); checks.getRange("A17:I17").values=[["항목","값","단위","기준일","출처 유형","출처 / URL","근거 등급","상태","메모"]]; header(checks,"A17:I17");
const sourceRows=[
  ["분기 재무",data.quarterly.length,"quarters",data.asOf,"Primary filing","https://opendart.fss.or.kr","Primary","Connected","연결 우선"],
  ["5% 지분공시",(data.marketContext?.ownership||[]).length,"reports",data.asOf,"Primary filing","https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS004&apiId=2019021","Primary","Connected","DART 대량보유"],
  ["시장 가격",safe(data.capital?.current_price),"KRW",market.as_of,"Market","https://github.com/FinanceData/FinanceDataReader","Market","Connected","최근 종가"],
  ["Risk-free rate",safe(assumptions.risk_free_rate),"%",data.asOf,"Central bank","https://ecos.bok.or.kr","Primary","Connected","국고채 10년"],
  ["KRX 수급",data.marketContext?.external_drivers?.flows?.connected?1:0,"connection",data.marketContext?.external_drivers?.flows?.as_of||data.asOf,"Market microstructure","https://data.krx.co.kr","Market",data.marketContext?.external_drivers?.flows?.connected?"Connected":"Needs setup",data.marketContext?.external_drivers?.flows?.verdict||data.marketContext?.external_drivers?.flows?.reason||""],
  ["리서치 참고",(data.researchReference?.expectations||[]).length,"items",data.asOf,"User-provided PDF","Local reference files","Secondary","Info",researchValuation.note||""],
  ["뉴스 정황",(data.marketContext?.news||[]).length,"items",data.asOf,"News search","https://openapi.naver.com","Reported context","Info","키워드 매칭"],
  ["블로그 정황",(data.marketContext?.blogs||[]).length,"items",data.asOf,"Blog search","https://openapi.naver.com","Unverified","Hypothesis only","사실로 취급 안 함"],
  ...(data.marketContext?.external_drivers?.status_rows||[]).map(r=>[
    r.source,
    r.connected?1:0,
    "connection",
    data.asOf,
    r.evidence_level||"Context",
    r.source==="KOSIS"?"https://kosis.kr":(r.source==="KAMIS"?"https://www.kamis.or.kr":(String(r.source).startsWith("UN")?"https://comtradeplus.un.org":"External API")),
    r.evidence_level||"Context",
    r.status,
    `${r.detail||""}${r.action?` · ${r.action}`:""}`
  ]),
];
checks.getRange(`A18:I${17+sourceRows.length}`).values=sourceRows; tableBody(checks,`A18:I${17+sourceRows.length}`);
section(checks,"A28:J28","버전 로그"); checks.getRange("A29:D32").values=[["버전","일자","변경","작성"],["v3.0",new Date().toISOString().slice(0,10),"Bottom-up 판관비 빌드, 매출 산업/점유율 분해, peer-beta WACC, 인과 해석","FinSight"],["v2.0",data.asOf,"드라이버 DCF, 기대치 괴리, 지분, 다방법 밸류에이션","FinSight"],["v1.0",data.asOf,"DART 분기 트래커와 간이 DCF","FinSight"]]; header(checks,"A29:D29"); tableBody(checks,"A30:D32"); checks.freezePanes.freezeRows(5); widths(checks,{A:28,B:16,C:13,D:14,E:15,F:48,G:18,H:14,I:48,J:12});

// 08 Revenue Build — industry vs share decomposition (reference: 산업성장률 + 점유율 변화율)
const sm = data.structured || {};
const revModel = sm.revenue || {}; const sgaModel = sm.sga || {}; const depModel = sm.depreciation || {}; const waccModel = sm.wacc || {};
const revBuild = wb.worksheets.add("08 Revenue Build");
title(revBuild, `${data.company} | 매출 빌드`, revModel.method || "기업성장률 ≈ 산업성장률(동종 합산 proxy) + 점유율 변화 / 인플레이션 교차검증", "I");
section(revBuild,"A4:I4","과거 성장률 분해");
revBuild.getRange("A5:E5").values=[["연도","기업 성장률","산업(동종 합산 proxy)","점유율 기여","실질(ex-CPI)"]]; header(revBuild,"A5:E5");
const rh=(revModel.history||[]).filter(r=>r.company_growth!==null).map(r=>[r.year,pct(r.company_growth),pct(r.industry_growth),pct(r.share_growth),pct(r.real_growth)]);
revBuild.getRange(`A6:E${5+Math.max(rh.length,1)}`).values=rh.length?rh:[["과거 데이터 없음",null,null,null,null]]; tableBody(revBuild,`A6:E${5+Math.max(rh.length,1)}`);
revBuild.getRange(`B6:E${5+Math.max(rh.length,1)}`).format.numberFormat=pctFmt;
const rEnd=5+Math.max(rh.length,1);
section(revBuild,`A${rEnd+2}:I${rEnd+2}`,"전망 빌드 — 파란 셀(산업/점유율 가정) 편집");
const fr=rEnd+3;
revBuild.getRange(`A${fr}:G${fr}`).values=[["동인","가정",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`]]; header(revBuild,`A${fr}:G${fr}`);
revBuild.getRange(`A${fr+1}:B${fr+4}`).values=[["산업 성장률(산업)",pct(revModel.industry_growth_avg)],["점유율 기여(점유율)",pct(revModel.share_growth_avg)],["기업 성장률 = 합",null],["매출(억원)",null]];
revBuild.getRange(`B${fr+1}:B${fr+2}`).format={fill:C.yellow,font:{color:C.input},numberFormat:pctFmt};
for(let col=3;col<=7;col++){const L=String.fromCharCode(64+col),P=String.fromCharCode(63+col);
  revBuild.getRange(`${L}${fr+3}`).formulas=[[`=$B${fr+1}+$B${fr+2}`]];
  const prev=col===3?`'05 DCF'!$B$26`:`${P}${fr+4}`;
  revBuild.getRange(`${L}${fr+4}`).formulas=[[`=${prev}*(1+${L}${fr+3})`]];
}
revBuild.getRange(`C${fr+3}:G${fr+3}`).format.numberFormat=pctFmt; revBuild.getRange(`C${fr+4}:G${fr+4}`).format.numberFormat=amountFmt;
tableBody(revBuild,`A${fr+1}:G${fr+4}`);
revBuild.getRange(`A${fr+6}`).values=[["해석: 국내는 산업성장률+점유율, 해외는 국가별 CPI 조정 성장률로 분해. 점유율이 횡보(≈0)면 성장은 사실상 산업·물가에 수렴."]];
revBuild.getRange(`A${fr+6}:I${fr+6}`).format={font:{italic:true,color:C.muted},wrapText:true};
const drvRows=(revModel.drivers||[]).map(d=>[d.theme,d.fact,d.source]);
if(drvRows.length){section(revBuild,`A${fr+8}:I${fr+8}`,"지역 / 동인 메모"); revBuild.getRange(`A${fr+9}:C${fr+9}`).values=[["테마","사실","출처"]]; header(revBuild,`A${fr+9}:C${fr+9}`); revBuild.getRange(`A${fr+10}:C${fr+9+drvRows.length}`).values=drvRows; tableBody(revBuild,`A${fr+10}:C${fr+9+drvRows.length}`);}
widths(revBuild,{A:26,B:18,C:14,D:14,E:14,F:14,G:14,H:12,I:12}); revBuild.freezePanes.freezeRows(5);

// 09 Cost Structure — SG&A 4-way build feeding OPM bottom-up
const cost = wb.worksheets.add("09 Cost Structure");
title(cost, `${data.company} | 원가구조 & 판관비 빌드`, sgaModel.method || "판관비 = 인건비성(임금) + 변동비(매출연동) + 고정비(CPI) + 대손(매출연동) → OPM = 매출총이익률 − 판관비율", "I");
section(cost,"A4:I4","판관비 분해 (LTM)");
cost.getRange("A5:E5").values=[["항목","판관비 비중","LTM (억원)","매출 대비","추정 동인"]]; header(cost,"A5:E5");
const comp=sgaModel.components||[];
const compRows=comp.map(c=>[c.component,pct(c.share),safe(c.ltm_amount),pct(c.pct_of_sales),c.driver]);
cost.getRange(`A6:E${5+Math.max(compRows.length,1)}`).values=compRows.length?compRows:[["판관비 분해 없음",null,null,null,null]]; tableBody(cost,`A6:E${5+Math.max(compRows.length,1)}`);
cost.getRange(`B6:B${5+Math.max(compRows.length,1)}`).format.numberFormat=pctFmt; cost.getRange(`C6:C${5+Math.max(compRows.length,1)}`).format.numberFormat=amountFmt; cost.getRange(`D6:D${5+Math.max(compRows.length,1)}`).format.numberFormat=pctFmt;
const cEnd=5+Math.max(compRows.length,1);
// Editable drivers
const dr=cEnd+2;
section(cost,`A${dr}:I${dr}`,"동인 (파란 셀 = 편집)");
cost.getRange(`A${dr+1}:B${dr+4}`).values=[["임금상승률/년",pct(sgaModel.wage_growth)],["CPI/년",pct(sgaModel.cpi)],["대손율(매출 대비)",pct(sgaModel.baddebt_ratio)],["원가율(매출 대비)",pct(sgaModel.cogs_ratio)]];
cost.getRange(`B${dr+1}:B${dr+4}`).format={fill:C.yellow,font:{color:C.input},numberFormat:pctFmt};
tableBody(cost,`A${dr+1}:B${dr+4}`);
// Forward build, pulling forecast revenue from 05 DCF
const fb=dr+6; const labor=comp.find(c=>c.component.startsWith("인건비"))?.ltm_amount||0; const variable=comp.find(c=>c.component.startsWith("변동비"))?.ltm_amount||0; const fixed=comp.find(c=>c.component.startsWith("고정비"))?.ltm_amount||0;
const ltmRev=data.ltmRevenue||1;
section(cost,`A${fb}:H${fb}`,"전망 판관비 → Implied OPM");
cost.getRange(`A${fb+1}:G${fb+1}`).values=[["항목","LTM",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`]]; header(cost,`A${fb+1}:G${fb+1}`);
cost.getRange(`A${fb+2}:A${fb+9}`).values=[["매출(억원)"],["인건비(임금연동)"],["변동비(매출 대비)"],["고정비(CPI연동)"],["대손(매출 대비)"],["판관비 합계"],["판관비율"],["Implied OPM = 매출총이익률 − 판관비율"]];
cost.getRange(`B${fb+2}`).values=[[ltmRev]]; cost.getRange(`B${fb+3}`).values=[[labor]]; cost.getRange(`B${fb+4}`).values=[[variable]]; cost.getRange(`B${fb+5}`).values=[[fixed]];
cost.getRange(`B${fb+6}`).formulas=[[`=$B${fb+2}*$B${dr+3}`]]; cost.getRange(`B${fb+7}`).formulas=[[`=SUM(B${fb+3}:B${fb+6})`]]; cost.getRange(`B${fb+8}`).formulas=[[`=B${fb+7}/B${fb+2}`]]; cost.getRange(`B${fb+9}`).formulas=[[`=(1-$B${dr+4})-B${fb+8}`]];
for(let col=3;col<=7;col++){const L=String.fromCharCode(64+col),P=String.fromCharCode(63+col);
  cost.getRange(`${L}${fb+2}`).formulas=[[`='05 DCF'!${L}26`]];
  cost.getRange(`${L}${fb+3}`).formulas=[[`=${P}${fb+3}*(1+$B${dr+1})`]];
  cost.getRange(`${L}${fb+4}`).formulas=[[`=${L}${fb+2}*($B${fb+4}/$B${fb+2})`]];
  cost.getRange(`${L}${fb+5}`).formulas=[[`=${P}${fb+5}*(1+$B${dr+2})`]];
  cost.getRange(`${L}${fb+6}`).formulas=[[`=${L}${fb+2}*$B${dr+3}`]];
  cost.getRange(`${L}${fb+7}`).formulas=[[`=SUM(${L}${fb+3}:${L}${fb+6})`]];
  cost.getRange(`${L}${fb+8}`).formulas=[[`=${L}${fb+7}/${L}${fb+2}`]];
  cost.getRange(`${L}${fb+9}`).formulas=[[`=(1-$B${dr+4})-${L}${fb+8}`]];
}
for(const r of [fb+2,fb+3,fb+4,fb+5,fb+6,fb+7]) cost.getRange(`B${r}:G${r}`).format.numberFormat=amountFmt;
for(const r of [fb+8,fb+9]) cost.getRange(`B${r}:G${r}`).format.numberFormat=pctFmt;
tableBody(cost,`A${fb+2}:G${fb+9}`);
cost.getRange(`A${fb+11}`).values=[[`해석: 변동비는 매출에 비례, 인건비·고정비는 임금/물가로 escalate. 이 빌드의 Implied OPM(${fb+9}행)을 '05 DCF'의 OPM fade 가정과 대조해 마진 가정의 현실성을 점검.`]];
cost.getRange(`A${fb+11}:I${fb+11}`).format={font:{italic:true,color:C.muted},wrapText:true};
// Depreciation split
const ds=fb+13;
section(cost,`A${ds}:I${ds}`,"감가상각 배분 (기존 상각 + 신규 CapEx)");
cost.getRange(`A${ds+1}:C${ds+1}`).values=[["항목","값","설명"]]; header(cost,`A${ds+1}:C${ds+1}`);
cost.getRange(`A${ds+2}:C${ds+5}`).values=[["D&A / 매출",pct(depModel.da_ratio),depModel.method||""],["CAPEX / 매출",pct(depModel.capex_ratio),"무성장 시 DEP만큼 재투자 가정 가능"],["원가 배분",pct(depModel.cogs_share),"제조원가 배분 비율"],["판관비 배분",pct(depModel.sga_share),"판관비 배분 비율"]];
cost.getRange(`B${ds+2}:B${ds+5}`).format.numberFormat=pctFmt; tableBody(cost,`A${ds+2}:C${ds+5}`);
widths(cost,{A:26,B:16,C:40,D:14,E:30,F:14,G:14,H:12,I:12}); cost.freezePanes.freezeRows(5);

// 10 WACC & Beta — peer unlever/relever
const wsheet = wb.worksheets.add("10 WACC & Beta");
title(wsheet, `${data.company} | WACC & 동종기업 Beta`, waccModel.method || "CAPM Ke = Rf + β·ERP / 세후 Kd / 자본구조 가중 → WACC. 베타는 동종기업 unlever→relever", "G");
section(wsheet,"A4:G4","동종기업 Beta Unlever → Relever");
wsheet.getRange("A5:D5").values=[["동종기업","Levered β","D/E (%)","Unlevered β"]]; header(wsheet,"A5:D5");
const pt=(waccModel.peer_table||[]).map(p=>[p.peer,safe(p.levered_beta),safe(p.de_ratio),safe(p.unlevered_beta)]);
wsheet.getRange(`A6:D${5+Math.max(pt.length,1)}`).values=pt.length?pt:[["동종기업 베타 없음 — 조정 시장베타 사용",null,null,null]]; tableBody(wsheet,`A6:D${5+Math.max(pt.length,1)}`);
for(const col of ["B","D"]) wsheet.getRange(`${col}6:${col}${5+Math.max(pt.length,1)}`).format.numberFormat="0.000";
wsheet.getRange(`C6:C${5+Math.max(pt.length,1)}`).format.numberFormat="0.0";
const wEnd=5+Math.max(pt.length,1);
section(wsheet,`A${wEnd+2}:G${wEnd+2}`,"CAPM / WACC 브릿지");
wsheet.getRange(`A${wEnd+3}:B${wEnd+12}`).values=[["무위험수익률 (Rf)",pct(waccModel.rf)],["주식위험프리미엄 (ERP)",pct(waccModel.erp)],["조정 베타 (β)",safe(waccModel.beta)],["자기자본비용 (Ke)",pct(waccModel.cost_equity)],["세전 타인자본비용 (Kd)",pct(waccModel.cost_debt)],["세율",pct(waccModel.tax)],["세후 Kd",pct(waccModel.after_tax_cost_debt)],["자기자본 비중",pct(waccModel.equity_weight)],["부채 비중",pct(waccModel.debt_weight)],["WACC",pct(waccModel.wacc)]];
for(const r of [wEnd+3,wEnd+4,wEnd+6,wEnd+7,wEnd+8,wEnd+9,wEnd+10,wEnd+11,wEnd+12]) wsheet.getRange(`B${r}`).format.numberFormat=pctFmt;
wsheet.getRange(`B${wEnd+5}`).format.numberFormat="0.000";
wsheet.getRange(`A${wEnd+12}:B${wEnd+12}`).format={font:{bold:true},fill:C.blue};
tableBody(wsheet,`A${wEnd+3}:B${wEnd+12}`);
widths(wsheet,{A:28,B:16,C:14,D:14,E:12,F:12,G:12}); wsheet.freezePanes.freezeRows(5);

// 11 Causal Read — second-level interpretation in the workbook
const pa = data.priceAction || {};
const causal = wb.worksheets.add("11 Causal Read");
title(causal, `${data.company} | 인과 해석`, "원인 해석 — 주가 변동요인 분해와 이상신호별 사유(근거 강도 표기)", "H");
section(causal,"A4:H4",pa.verdict||"주가 변동요인 분해");
causal.mergeCells("A5:H6"); causal.getRange("A5").values=[[pa.thesis||""]]; causal.getRange("A5:H6").format={wrapText:true,verticalAlignment:"top",fill:C.pale,font:{color:C.text,size:10}};
causal.getRange("A8:D8").values=[["변동요인","강도","해석","근거 / 등급"]]; header(causal,"A8:D8");
const attrRows=(pa.attribution||[]).map(a=>[a.driver,a.weight,a.reading,`${a.evidence||""} · ${a.evidence_level||""}`]);
causal.getRange(`A9:D${8+Math.max(attrRows.length,1)}`).values=attrRows.length?attrRows:[["분해 데이터 없음",null,null,null]]; tableBody(causal,`A9:D${8+Math.max(attrRows.length,1)}`);
const aEnd=8+Math.max(attrRows.length,1);
section(causal,`A${aEnd+2}:H${aEnd+2}`,"이상신호 — 원인 출처와 확인 절차");
causal.getRange(`A${aEnd+3}:G${aEnd+3}`).values=[["이상신호","해석(무엇이 아니라 왜)","핵심 원인","근거","신뢰도","확인 — 어디서 → 무엇을 → 판정","반증"]]; header(causal,`A${aEnd+3}:G${aEnd+3}`);
const recipeText=I=>(I.verification||[]).map((r,i)=>`${i+1}. [어디서] ${r.where}\n   [무엇을] ${r.what}\n   [판정] ${r.rule}`).join("\n\n");
const ir=(data.interpreted||[]).map(it=>{const I=it.interpretation||{};const top=(I.cause_candidates||[])[0]||{};return [it.label,I.narrative,top.cause||"근거 대기",top.evidence_level||"—",I.confidence||"",recipeText(I),I.falsifier||""];});
causal.getRange(`A${aEnd+4}:G${aEnd+3+Math.max(ir.length,1)}`).values=ir.length?ir:[["이상신호 없음","자체 과거 범위 내 정상","—","—","—","—","—"]]; tableBody(causal,`A${aEnd+4}:G${aEnd+3+Math.max(ir.length,1)}`);
causal.getRange(`F${aEnd+4}:F${aEnd+3+Math.max(ir.length,1)}`).format={wrapText:true,verticalAlignment:"top",font:{size:9}};
widths(causal,{A:22,B:52,C:30,D:13,E:12,F:64,G:38,H:12}); causal.freezePanes.freezeRows(4);

if(previewDir){
  await fs.mkdir(previewDir,{recursive:true});
  for(const name of ["00 Cover","01 Quarterly","02 Earnings Bridge","03 Thesis Evidence","04 Peers Multiples","05 DCF","06 Scenarios","07 Checks Sources","08 Revenue Build","09 Cost Structure","10 WACC & Beta","11 Causal Read"]){
    const preview=await wb.render({sheetName:name,autoCrop:"all",scale:1,format:"png"});
    await fs.writeFile(`${previewDir}/${name.replaceAll(" ","_")}.png`,new Uint8Array(await preview.arrayBuffer()));
  }
}
await fs.mkdir(outputPath.substring(0,outputPath.lastIndexOf("/")),{recursive:true});
const out=await SpreadsheetFile.exportXlsx(wb); await out.save(outputPath);
