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
title(cover, `FinSight | ${data.company}`, `Investment review · ${data.asOf} · DART actuals + market context + valuation cross-check`, "N");
section(cover, "A4:N4", "Decision Snapshot");
cover.mergeCells("A5:N5"); cover.getRange("A5").values = [[thesis.headline || "Evidence review"]];
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

section(cover, "A13:G13", "What the Numbers Confirm");
cover.getRange("A14:D14").values = [["Fact", "Value", "Interpretation", "Source / Confidence"]]; header(cover, "A14:D14");
const factRows = (thesis.facts || []).map(x => [x.label, x.value, x.interpretation, `${x.source} / ${x.confidence}`]);
cover.getRange(`A15:D${14 + Math.max(factRows.length,1)}`).values = factRows.length ? factRows : [["No fact",null,null,null]]; tableBody(cover, `A15:D${14 + Math.max(factRows.length,1)}`);

section(cover, "A22:G22", "Why Price Can Diverge From Earnings");
cover.getRange("A23:E23").values = [["Priority", "Hypothesis", "Interpretation", "Evidence", "Falsifier / Next proof"]]; header(cover, "A23:E23");
const hypothesisRows = (thesis.hypotheses || []).map((x,i) => [i+1, `${x.title} (${x.confidence})`, x.explanation, (x.evidence||[]).join(" | "), x.falsifier]);
cover.getRange(`A24:E${23 + Math.max(hypothesisRows.length,1)}`).values = hypothesisRows.length ? hypothesisRows : [[null,"No material non-financial hypothesis",null,null,null]]; tableBody(cover, `A24:E${23 + Math.max(hypothesisRows.length,1)}`);

cover.getRange("J9:L9").values = [["Method", "Implied Price", "Current Price"]]; header(cover, "J9:L9");
const methodRows = (valuationRange.methods || []).map(x => [x.method, safe(x.value), safe(data.capital?.current_price)]);
cover.getRange(`J10:L${9 + Math.max(methodRows.length,1)}`).values = methodRows.length ? methodRows : [["N/A",null,null]];
cover.getRange(`K10:L${9 + Math.max(methodRows.length,1)}`).format.numberFormat = countFmt;
const valueChart = cover.charts.add("bar", cover.getRange(`J9:L${9 + Math.max(methodRows.length,1)}`)); valueChart.title = "Valuation methods vs current price (KRW)"; valueChart.hasLegend = true; valueChart.yAxis = { numberFormatCode: "#,##0" }; valueChart.setPosition("H13", "N27");
widths(cover,{A:12,B:19,C:18,D:42,E:42,F:15,G:14,H:16,J:20,K:16,L:16,M:12,N:12}); cover.freezePanes.freezeRows(4);

// 01 Quarterly
const quarterly = wb.worksheets.add("01 Quarterly");
title(quarterly, `${data.company} | Quarterly Actuals`, "DART consolidated statements preferred · amounts in KRW 100m · no silent gap filling", "Z");
section(quarterly, "A4:Z4", "Historical Actuals and Operating Drivers");
const qHeaders = ["Period","Revenue","QoQ","YoY","Operating Profit","OPM","Net Income","CFO","CFO Margin","D&A","CAPEX","FCF","FCF Margin","COGS %","SG&A %","Receivables","Inventory","Payables","Working Capital","NWC % Sales","ΔNWC","AR Days","Inventory Days","Payable Days","Current Ratio","Debt Ratio"];
quarterly.getRange("A5:Z5").values = [qHeaders]; header(quarterly,"A5:Z5");
const qRows = data.quarterly.map(x => [x.period,won100m(x.revenue),pct(x.revenue_qoq),pct(x.revenue_yoy),won100m(x.operating_profit),pct(x.opm),won100m(x.net_income),won100m(x.cfo),pct(x.cfo_margin),won100m(x.depreciation),won100m(x.capex),won100m(x.fcf),pct(x.fcf_margin),pct(x.cogs_ratio),pct(x.sga_ratio),won100m(x.receivables),won100m(x.inventory),won100m(x.payables),won100m(x.working_capital),pct(x.working_capital_ratio),won100m(x.change_in_nwc),safe(x.ar_days),safe(x.inventory_days),safe(x.payable_days),pct(x.current_ratio),pct(x.debt_ratio)]);
quarterly.getRange(`A6:Z${5+qRows.length}`).values=qRows; tableBody(quarterly,`A6:Z${5+qRows.length}`);
for(const col of ["B","E","G","H","J","K","L","P","Q","R","S","U"]) quarterly.getRange(`${col}6:${col}${5+qRows.length}`).format.numberFormat=amountFmt;
for(const col of ["C","D","F","I","M","N","O","T","Y","Z"]) quarterly.getRange(`${col}6:${col}${5+qRows.length}`).format.numberFormat=pctFmt;
quarterly.getRange(`V6:X${5+qRows.length}`).format.numberFormat="0.0";
quarterly.getRange(`C6:D${5+qRows.length}`).conditionalFormats.add("colorScale",{colors:[C.redBg,C.white,C.greenBg],thresholds:["min","50%","max"]});
quarterly.freezePanes.freezeRows(5); quarterly.freezePanes.freezeColumns(1); widths(quarterly,{A:13,B:14,C:9,D:9,E:16,F:9,G:14,H:14,I:11,J:12,K:12,L:13,M:11,N:10,O:10,P:14,Q:14,R:14,S:15,T:12,U:13,V:10,W:12,X:11,Y:11,Z:11});

// 02 Earnings Bridge
const earnings = wb.worksheets.add("02 Earnings Bridge");
title(earnings, `${data.company} | Earnings and Expectation Bridge`, "Actual-vs-history, margin bridge and broker expectation references", "L");
section(earnings,"A4:L4","Quarter-on-Quarter Margin Bridge");
earnings.getRange("A5:I5").values=[["Period","Revenue QoQ","Prior OPM","COGS contribution","SG&A contribution","Other contribution","Current OPM","Pattern","Analyst implication"]]; header(earnings,"A5:I5");
const bridgeRows=(data.marginBridge||[]).map(x=>[x.period,pct(x.revenue_change_pct),pct(x.previous_opm),pct(x.cogs_contribution_pp),pct(x.sga_contribution_pp),pct(x.other_contribution_pp),pct(x.current_opm),x.pattern,x.comment]);
earnings.getRange(`A6:I${5+Math.max(bridgeRows.length,1)}`).values=bridgeRows.length?bridgeRows:[["No bridge",null,null,null,null,null,null,null,null]]; tableBody(earnings,`A6:I${5+Math.max(bridgeRows.length,1)}`);
earnings.getRange(`B6:G${5+Math.max(bridgeRows.length,1)}`).format.numberFormat=pctFmt;
section(earnings,"A18:L18","Expectation Gap References");
earnings.getRange("A19:G19").values=[["Date","Metric","Actual Surprise","Fact","Source","Evidence Level","Use in Decision"]]; header(earnings,"A19:G19");
const expectationRows=(data.researchReference?.expectations||[]).map(x=>[x.date,x.metric,pct(x.value),x.fact,x.source,x.evidence_level,"Beat + weak price = sustainability/flow review"]);
earnings.getRange(`A20:G${19+Math.max(expectationRows.length,1)}`).values=expectationRows.length?expectationRows:[[null,"No consensus reference",null,null,null,null,"Upload/normalize research estimate"]]; tableBody(earnings,`A20:G${19+Math.max(expectationRows.length,1)}`); earnings.getRange(`C20:C${19+Math.max(expectationRows.length,1)}`).format.numberFormat=pctFmt;
earnings.freezePanes.freezeRows(5); widths(earnings,{A:13,B:24,C:14,D:30,E:24,F:22,G:28,H:22,I:46,J:15,K:15,L:15});

// 03 Thesis Evidence
const evidence = wb.worksheets.add("03 Thesis Evidence");
title(evidence, `${data.company} | Thesis, Evidence and Falsifiers`, "Facts are separated from hypotheses; blogs are never treated as primary evidence", "K");
section(evidence,"A4:K4","Investment Thesis Tree");
evidence.getRange("A5:G5").values=[["Priority","Hypothesis","Confidence","Interpretation","Evidence","Falsifier","Linked URL"]]; header(evidence,"A5:G5");
const hRows=(thesis.hypotheses||[]).map((x,i)=>[i+1,x.title,x.confidence,x.explanation,(x.evidence||[]).join(" | "),x.falsifier,x.url||null]);
evidence.getRange(`A6:G${5+Math.max(hRows.length,1)}`).values=hRows.length?hRows:[[null,"No hypothesis",null,null,null,null,null]]; tableBody(evidence,`A6:G${5+Math.max(hRows.length,1)}`);
section(evidence,"A16:K16","Next-quarter Checkpoints"); evidence.getRange("A17:C17").values=[["Priority","Checkpoint","Decision if confirmed"]]; header(evidence,"A17:C17");
const checkpointRows=(thesis.checkpoints||[]).map((x,i)=>[i+1,x,"Update forecast driver or remove hypothesis"]);
evidence.getRange(`A18:C${17+Math.max(checkpointRows.length,1)}`).values=checkpointRows.length?checkpointRows:[[null,"No checkpoint",null]]; tableBody(evidence,`A18:C${17+Math.max(checkpointRows.length,1)}`);
section(evidence,"A28:K28","External Context - Ranked by Reliability"); evidence.getRange("A29:G29").values=[["Date","Title","Source","Evidence Level","Matched Keywords","URL","Analyst Use"]]; header(evidence,"A29:G29");
const externalRows=(thesis.context||[]).map(x=>[x.date,x.title,x.source,x.evidence_level,(x.matched_keywords||[]).join(", "),x.url,x.source==="Naver Blog"?"Hypothesis discovery only":"Context corroboration"]);
evidence.getRange(`A30:G${29+Math.max(externalRows.length,1)}`).values=externalRows.length?externalRows:[[null,"No matched context",null,null,null,null,null]]; tableBody(evidence,`A30:G${29+Math.max(externalRows.length,1)}`);
evidence.freezePanes.freezeRows(5); widths(evidence,{A:10,B:30,C:28,D:55,E:36,F:55,G:46,H:12,I:12,J:12,K:12});

// 04 Peers & Multiples
const peers = wb.worksheets.add("04 Peers Multiples");
title(peers, `${data.company} | Peer and Multiple Cross-check`, `Peer set: ${data.peerNames.join(", ") || "None"} · research multiples are references, not answers`, "J");
section(peers,"A4:J4","Operating Benchmark"); peers.getRange("A5:G5").values=[["Metric","Unit","Target","Peer Median","Gap","Peer Count","Interpretation"]]; header(peers,"A5:G5");
const pRows=data.peerBenchmark.length?data.peerBenchmark.map(x=>[x["지표"],x["단위"],safe(x["분석기업"]),safe(x["동종기업 중앙값"]),safe(x["격차"]),safe(x["비교기업 수"]),safe(x["격차"])===null?"Insufficient data":(x["격차"]>0?"Above peer median":"Below peer median")]):[["No peer data",null,null,null,null,0,"Review peer set"]];
peers.getRange(`A6:G${5+pRows.length}`).values=pRows; tableBody(peers,`A6:G${5+pRows.length}`);
section(peers,"A18:J18","Valuation Methods"); peers.getRange("A19:G19").values=[["Method","Case","Multiple","Implied Price","Upside","Basis","Use"]]; header(peers,"A19:G19");
const mRows=(data.multipleValuation||[]).map(x=>[x.method,x.case,safe(x.multiple),safe(x.implied_price),pct(x.upside),x.basis,"Cross-check"]);
peers.getRange(`A20:G${19+Math.max(mRows.length,1)}`).values=mRows.length?mRows:[["No multiple valuation",null,null,null,null,null,null]]; tableBody(peers,`A20:G${19+Math.max(mRows.length,1)}`);
peers.getRange(`C20:C${19+Math.max(mRows.length,1)}`).format.numberFormat=multipleFmt; peers.getRange(`D20:D${19+Math.max(mRows.length,1)}`).format.numberFormat=countFmt; peers.getRange(`E20:E${19+Math.max(mRows.length,1)}`).format.numberFormat=pctFmt;
peers.freezePanes.freezeRows(5); widths(peers,{A:24,B:30,C:12,D:16,E:12,F:48,G:18,H:12,I:12,J:12});

// 05 DCF
const dcf = wb.worksheets.add("05 DCF");
title(dcf, `${data.company} | Driver-based DCF`, "Revenue/OPM fade · NOPAT + D&A - CAPEX - ΔNWC · Gordon growth · blue/yellow cells are editable", "H");
section(dcf,"A4:D4","Assumptions and Guardrails"); dcf.getRange("A5:D5").values=[["Assumption","Input","Evidence / Source","Control"]]; header(dcf,"A5:D5");
const ev=Object.fromEntries((data.dcfEvidence||[]).map(x=>[x.assumption,x]));
const aRows=[
  ["Year 1 Revenue Growth",pct(assumptions.revenue_growth),(ev["매출 성장률"]?.evidence||[]).join(" | ")||ev["매출 성장률"]?.source,"Evidence adjusted"],
  ["Year 5 Revenue Growth",pct(assumptions.revenue_growth_terminal),"Fade toward sustainable growth","Review"],
  ["Year 1 EBIT Margin",pct(assumptions.opm),(ev["영업이익률"]?.evidence||[]).join(" | ")||ev["영업이익률"]?.source,"Evidence adjusted"],
  ["Year 5 EBIT Margin",pct(assumptions.opm_terminal),"Recent margin median / normalization","Review"],
  ["D&A / Revenue",pct(assumptions.depreciation_ratio),"DART historical ratio","Auto"],
  ["CAPEX / Revenue",pct(assumptions.capex_ratio),"DART historical ratio; current anomaly retained when higher","Watch"],
  ["NWC / Revenue",pct(assumptions.nwc_ratio),"AR + Inventory - AP / Revenue","Auto"],
  ["Tax Rate",pct(assumptions.tax_rate),"Model assumption","Review"],
  ["Risk-free Rate",pct(assumptions.risk_free_rate),"ECOS 10Y Korean Treasury","Auto"],
  ["ERP",pct(assumptions.erp),"KICPA reference; user review","Review"],
  ["Adjusted Beta",safe(assumptions.beta),data.recommendations?.beta?.basis||"FDR raw beta adjusted toward market; 0.50 floor","Guardrail"],
  ["Debt Weight",pct(assumptions.debt_weight),data.capital?.debt_weight_source,"Auto"],
  ["Pre-tax Cost of Debt",pct(assumptions.cost_of_debt),"Review against borrowing notes","Review"],
  ["Perpetual Growth",pct(assumptions.perpetual_growth),"GDP-based sustainable range","Review"],
  ["Shares Outstanding",safe(data.capital?.shares_outstanding),data.capital?.share_source,"Auto"],
  ["Net Debt (억원)",won100m(data.capital?.net_debt),"Interest debt less cash","Auto"],
  ["Current Price",safe(data.capital?.current_price),"Latest available close","Market"],
];
dcf.getRange("A6:D22").values=aRows; tableBody(dcf,"A6:D22"); dcf.getRange("B6:B22").format={fill:C.yellow,font:{color:C.input}};
for(let r=6;r<=19;r++) if(r!==16&&r!==20&&r!==21&&r!==22) dcf.getRange(`B${r}`).format.numberFormat=pctFmt;
dcf.getRange("B16").format.numberFormat=multipleFmt; dcf.getRange("B20:B22").format.numberFormat=countFmt; dcf.getRange("B21").format.numberFormat=amountFmt;
section(dcf,"A24:H24","Forecast and FCFF Build"); dcf.getRange("A25:H25").values=[["Metric","LTM",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`,"Formula logic"]]; header(dcf,"A25:H25");
dcf.getRange("A26:A38").values=[["Revenue"],["Growth"],["EBIT Margin"],["EBIT"],["Cash Tax"],["NOPAT"],["D&A"],["CAPEX"],["NWC"],["Change in NWC"],["FCFF"],["Discount Factor"],["PV of FCFF"]];
dcf.getRange("B26").values=[[data.ltmRevenue]]; dcf.getRange("B28").values=[[pct(latest.opm)]]; dcf.getRange("B29").formulas=[["=B26*B28"]]; dcf.getRange("B31").formulas=[["=B29*(1-$B$13)"]]; dcf.getRange("B32").formulas=[["=B26*$B$10"]]; dcf.getRange("B33").formulas=[["=B26*$B$11"]]; dcf.getRange("B34").formulas=[["=B26*$B$12"]];
for(let col=3;col<=7;col++){
  const L=String.fromCharCode(64+col),P=String.fromCharCode(63+col),step=col-3;
  dcf.getRange(`${L}27`).formulas=[[`=$B$6+($B$7-$B$6)*${step}/4`]];
  dcf.getRange(`${L}26`).formulas=[[`=${P}26*(1+${L}27)`]];
  dcf.getRange(`${L}28`).formulas=[[`=$B$8+($B$9-$B$8)*${step}/4`]];
  dcf.getRange(`${L}29`).formulas=[[`=${L}26*${L}28`]]; dcf.getRange(`${L}30`).formulas=[[`=${L}29*$B$13`]]; dcf.getRange(`${L}31`).formulas=[[`=${L}29-${L}30`]];
  dcf.getRange(`${L}32`).formulas=[[`=${L}26*$B$10`]]; dcf.getRange(`${L}33`).formulas=[[`=${L}26*$B$11`]]; dcf.getRange(`${L}34`).formulas=[[`=${L}26*$B$12`]]; dcf.getRange(`${L}35`).formulas=[[`=${L}34-${P}34`]];
  dcf.getRange(`${L}36`).formulas=[[`=${L}31+${L}32-${L}33-${L}35`]]; dcf.getRange(`${L}37`).formulas=[[`=1/(1+$B$42)^${col-2}`]]; dcf.getRange(`${L}38`).formulas=[[`=${L}36*${L}37`]];
}
dcf.getRange("H26:H38").values=[["Prior revenue × (1+growth)"],["Linear fade: Year 1 to Year 5"],["Linear fade: Year 1 to Year 5"],["Revenue × EBIT margin"],["EBIT × tax"],["EBIT - cash tax"],["Revenue × D&A ratio"],["Revenue × CAPEX ratio"],["Revenue × NWC ratio"],["Ending NWC - prior NWC"],["NOPAT + D&A - CAPEX - ΔNWC"],["1/(1+WACC)^t"],["FCFF × discount factor"]];
for(const row of [27,28,37]) dcf.getRange(`B${row}:G${row}`).format.numberFormat=pctFmt; for(const row of [26,29,30,31,32,33,34,35,36,38]) dcf.getRange(`B${row}:G${row}`).format.numberFormat=amountFmt;
section(dcf,"A40:D40","Valuation Output and Safety Checks"); dcf.getRange("A41:B52").values=[["Cost of Equity",null],["WACC",null],["PV Forecast FCFF",null],["Terminal Value",null],["PV Terminal Value",null],["Enterprise Value",null],["Equity Value",null],["Implied Price / Share",null],["TV / Enterprise Value",null],["WACC - g Spread",null],["Upside / (Downside)",null],["Model Status",null]];
dcf.getRange("B41").formulas=[["=$B$14+$B$16*$B$15"]]; dcf.getRange("B42").formulas=[["=B41*(1-$B$17)+$B$18*(1-$B$13)*$B$17"]]; dcf.getRange("B43").formulas=[["=SUM(C38:G38)"]]; dcf.getRange("B44").formulas=[["=G36*(1+$B$19)/(B42-$B$19)"]]; dcf.getRange("B45").formulas=[["=B44*G37"]]; dcf.getRange("B46").formulas=[["=B43+B45"]]; dcf.getRange("B47").formulas=[["=B46-$B$21"]]; dcf.getRange("B48").formulas=[["=B47*100000000/$B$20"]]; dcf.getRange("B49").formulas=[["=B45/B46"]]; dcf.getRange("B50").formulas=[["=B42-$B$19"]]; dcf.getRange("B51").formulas=[["=B48/$B$22-1"]]; dcf.getRange("B52").formulas=[["=IF(AND(B50>=2%,B49<=80%,B20>0),\"PASS\",\"REVIEW\")"]];
dcf.getRange("B41:B42").format.numberFormat=pctFmt; dcf.getRange("B43:B47").format.numberFormat=amountFmt; dcf.getRange("B48").format.numberFormat=countFmt; dcf.getRange("B49:B51").format.numberFormat=pctFmt; dcf.getRange("A46:B52").format.borders={top:{style:"thin",color:C.navy}}; dcf.getRange("B52").conditionalFormats.add("containsText",{text:"PASS",format:{fill:C.greenBg,font:{color:C.green,bold:true}}}); dcf.getRange("B52").conditionalFormats.add("containsText",{text:"REVIEW",format:{fill:C.amberBg,font:{color:C.amber,bold:true}}});
dcf.freezePanes.freezeRows(5); widths(dcf,{A:28,B:18,C:48,D:18,E:14,F:14,G:14,H:34});

// 06 Scenarios
const scenarios=wb.worksheets.add("06 Scenarios");
title(scenarios,`${data.company} | Scenario Valuation`,"Bear/Base/Bull mechanics recalculate growth, margin and WACC - outputs are formulas, not pasted values","R");
section(scenarios,"A4:R4","Scenario Drivers and Recalculated Valuation");
scenarios.getRange("A5:R5").values=[["Scenario","Growth Δ","OPM Δ","WACC Δ","Y1 Revenue","Y2 Revenue","Y3 Revenue","Y4 Revenue","Y5 Revenue","Y1 FCFF","Y2 FCFF","Y3 FCFF","Y4 FCFF","Y5 FCFF","PV FCFF","PV Terminal","Equity Value","Price / Share"]]; header(scenarios,"A5:R5");
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
section(scenarios,"A11:H11","Interpretation"); scenarios.getRange("A12:D15").values=[["Rule","Why it matters","Action","Linked check"],["Bear","Lower growth/margin + higher WACC","Use when overseas volume or plant timing disappoints","05 DCF TV/EV"],["Base","Evidence-adjusted operating case","Default review starting point","05 DCF Model Status"],["Bull","Volume growth + operating leverage + lower risk premium","Require two consecutive proof points","03 Thesis Evidence"]]; header(scenarios,"A12:D12"); tableBody(scenarios,"A13:D15"); scenarios.freezePanes.freezeRows(5); widths(scenarios,{A:12,B:24,C:28,D:20,E:14,F:14,G:14,H:14,I:14,J:14,K:14,L:14,M:14,N:14,O:14,P:14,Q:15,R:16});

// 07 Checks Sources
const checks=wb.worksheets.add("07 Checks Sources");
title(checks,`${data.company} | Checks, Sources and Version Log`,"PASS validates mechanics and source completeness - it does not certify an investment conclusion","J");
section(checks,"A4:J4","Model Checks"); checks.getRange("A5:G5").values=[["Check","Actual","Expected","Difference","Tolerance","Status","Fix / Note"]]; header(checks,"A5:G5");
checks.getRange("A6:G13").values=[["WACC-g spread",null,0.02,null,0,null,"Raise beta/WACC or lower terminal growth"],["TV/EV",null,0.80,null,0,null,"Review terminal assumptions"],["Shares populated",null,1,null,0,null,"Check DART share fallback"],["Revenue complete",data.quality.find(x=>x.field==="매출액")?.missing_quarters||0,0,null,0,null,"Check XBRL mapping"],["Operating profit complete",data.quality.find(x=>x.field==="영업이익")?.missing_quarters||0,0,null,0,null,"Check XBRL mapping"],["FCFF formula",null,null,null,0,null,"NOPAT + D&A - CAPEX - ΔNWC"],["Equity bridge",null,null,null,0,null,"EV - net debt"],["Overall model status",null,null,null,0,null,"All required checks"]];
checks.getRange("B6").formulas=[["='05 DCF'!B50"]]; checks.getRange("D6").formulas=[["=B6-C6"]]; checks.getRange("F6").formulas=[["=IF(B6>=C6,\"OK\",\"FAIL\")"]];
checks.getRange("B7").formulas=[["='05 DCF'!B49"]]; checks.getRange("D7").formulas=[["=C7-B7"]]; checks.getRange("F7").formulas=[["=IF(B7<=C7,\"OK\",\"FAIL\")"]];
checks.getRange("B8").formulas=[["='05 DCF'!B20"]]; checks.getRange("D8").formulas=[["=B8-C8"]]; checks.getRange("F8").formulas=[["=IF(B8>=C8,\"OK\",\"FAIL\")"]];
for(let r=9;r<=10;r++){checks.getRange(`D${r}`).formulas=[[`=B${r}-C${r}`]];checks.getRange(`F${r}`).formulas=[[`=IF(ABS(D${r})<=E${r},\"OK\",\"FAIL\")`]];}
checks.getRange("B11").formulas=[["='05 DCF'!G36"]]; checks.getRange("C11").formulas=[["='05 DCF'!G31+'05 DCF'!G32-'05 DCF'!G33-'05 DCF'!G35"]]; checks.getRange("D11").formulas=[["=B11-C11"]]; checks.getRange("F11").formulas=[["=IF(ABS(D11)<0.01,\"OK\",\"FAIL\")"]];
checks.getRange("B12").formulas=[["='05 DCF'!B47"]]; checks.getRange("C12").formulas=[["='05 DCF'!B46-'05 DCF'!B21"]]; checks.getRange("D12").formulas=[["=B12-C12"]]; checks.getRange("F12").formulas=[["=IF(ABS(D12)<0.01,\"OK\",\"FAIL\")"]]; checks.getRange("F13").formulas=[["=IF(COUNTIF(F6:F12,\"FAIL\")=0,\"PASS\",\"REVIEW\")"]];
checks.getRange("B6:E7").format.numberFormat=pctFmt; checks.getRange("B11:E12").format.numberFormat=amountFmt; checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"OK",format:{fill:C.greenBg,font:{color:C.green,bold:true}}}); checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"FAIL",format:{fill:C.redBg,font:{color:C.red,bold:true}}}); checks.getRange("F6:F13").conditionalFormats.add("containsText",{text:"REVIEW",format:{fill:C.amberBg,font:{color:C.amber,bold:true}}});
section(checks,"A16:J16","Source Log"); checks.getRange("A17:I17").values=[["Item","Value","Units","As-of","Source Type","Source / URL","Evidence Level","Status","Notes"]]; header(checks,"A17:I17");
const sourceRows=[
  ["Quarterly financials",data.quarterly.length,"quarters",data.asOf,"Primary filing","https://opendart.fss.or.kr","Primary","Connected","Consolidated preferred"],
  ["5% ownership reports",(data.marketContext?.ownership||[]).length,"reports",data.asOf,"Primary filing","https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS004&apiId=2019021","Primary","Connected","DART majorstock"],
  ["Market price",safe(data.capital?.current_price),"KRW",market.as_of,"Market","https://github.com/FinanceData/FinanceDataReader","Market","Connected","Latest available close"],
  ["Risk-free rate",safe(assumptions.risk_free_rate),"%",data.asOf,"Central bank","https://ecos.bok.or.kr","Primary","Connected","10Y Korean Treasury"],
  ["Research references",(data.researchReference?.expectations||[]).length,"items",data.asOf,"User-provided PDF","Local reference files","Secondary","Info",researchValuation.note||""],
  ["News context",(data.marketContext?.news||[]).length,"items",data.asOf,"News search","https://openapi.naver.com","Reported context","Info","Keyword matched"],
  ["Blog context",(data.marketContext?.blogs||[]).length,"items",data.asOf,"Blog search","https://openapi.naver.com","Unverified","Hypothesis only","Never treated as fact"],
];
checks.getRange(`A18:I${17+sourceRows.length}`).values=sourceRows; tableBody(checks,`A18:I${17+sourceRows.length}`);
section(checks,"A28:J28","Version Log"); checks.getRange("A29:D32").values=[["Version","Date","Change","Owner"],["v3.0",new Date().toISOString().slice(0,10),"Bottom-up SG&A build, revenue industry/share split, peer-beta WACC, causal interpretation","FinSight"],["v2.0",data.asOf,"Driver DCF, expectation gap, ownership, multi-method valuation","FinSight"],["v1.0",data.asOf,"DART quarterly tracker and simplified DCF","FinSight"]]; header(checks,"A29:D29"); tableBody(checks,"A30:D32"); checks.freezePanes.freezeRows(5); widths(checks,{A:28,B:16,C:13,D:14,E:15,F:48,G:18,H:14,I:48,J:12});

// 08 Revenue Build — industry vs share decomposition (reference: 산업성장률 + 점유율 변화율)
const sm = data.structured || {};
const revModel = sm.revenue || {}; const sgaModel = sm.sga || {}; const depModel = sm.depreciation || {}; const waccModel = sm.wacc || {};
const revBuild = wb.worksheets.add("08 Revenue Build");
title(revBuild, `${data.company} | Revenue Build`, revModel.method || "기업성장률 ≈ 산업성장률(동종 합산 proxy) + 점유율 변화 / 인플레이션 교차검증", "I");
section(revBuild,"A4:I4","Historical Growth Decomposition");
revBuild.getRange("A5:E5").values=[["Year","Company Growth","Industry (peer-sum proxy)","Share Contribution","Real (ex-CPI)"]]; header(revBuild,"A5:E5");
const rh=(revModel.history||[]).filter(r=>r.company_growth!==null).map(r=>[r.year,pct(r.company_growth),pct(r.industry_growth),pct(r.share_growth),pct(r.real_growth)]);
revBuild.getRange(`A6:E${5+Math.max(rh.length,1)}`).values=rh.length?rh:[["No history",null,null,null,null]]; tableBody(revBuild,`A6:E${5+Math.max(rh.length,1)}`);
revBuild.getRange(`B6:E${5+Math.max(rh.length,1)}`).format.numberFormat=pctFmt;
const rEnd=5+Math.max(rh.length,1);
section(revBuild,`A${rEnd+2}:I${rEnd+2}`,"Forward Build — edit blue industry / share assumptions");
const fr=rEnd+3;
revBuild.getRange(`A${fr}:G${fr}`).values=[["Driver","Assumption",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`]]; header(revBuild,`A${fr}:G${fr}`);
revBuild.getRange(`A${fr+1}:B${fr+4}`).values=[["Industry growth (산업)",pct(revModel.industry_growth_avg)],["Share contribution (점유율)",pct(revModel.share_growth_avg)],["Company growth = sum",null],["Revenue (억원)",null]];
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
if(drvRows.length){section(revBuild,`A${fr+8}:I${fr+8}`,"Region / Driver Notes"); revBuild.getRange(`A${fr+9}:C${fr+9}`).values=[["Theme","Fact","Source"]]; header(revBuild,`A${fr+9}:C${fr+9}`); revBuild.getRange(`A${fr+10}:C${fr+9+drvRows.length}`).values=drvRows; tableBody(revBuild,`A${fr+10}:C${fr+9+drvRows.length}`);}
widths(revBuild,{A:26,B:18,C:14,D:14,E:14,F:14,G:14,H:12,I:12}); revBuild.freezePanes.freezeRows(5);

// 09 Cost Structure — SG&A 4-way build feeding OPM bottom-up
const cost = wb.worksheets.add("09 Cost Structure");
title(cost, `${data.company} | Cost Structure & SG&A Build`, sgaModel.method || "판관비 = 인건비성(임금) + 변동비(매출연동) + 고정비(CPI) + 대손(매출연동) → OPM = 매출총이익률 − 판관비율", "I");
section(cost,"A4:I4","SG&A Decomposition (LTM)");
cost.getRange("A5:E5").values=[["Component","Share of SG&A","LTM (억원)","% of Sales","Projection Driver"]]; header(cost,"A5:E5");
const comp=sgaModel.components||[];
const compRows=comp.map(c=>[c.component,pct(c.share),safe(c.ltm_amount),pct(c.pct_of_sales),c.driver]);
cost.getRange(`A6:E${5+Math.max(compRows.length,1)}`).values=compRows.length?compRows:[["No SG&A breakdown",null,null,null,null]]; tableBody(cost,`A6:E${5+Math.max(compRows.length,1)}`);
cost.getRange(`B6:B${5+Math.max(compRows.length,1)}`).format.numberFormat=pctFmt; cost.getRange(`C6:C${5+Math.max(compRows.length,1)}`).format.numberFormat=amountFmt; cost.getRange(`D6:D${5+Math.max(compRows.length,1)}`).format.numberFormat=pctFmt;
const cEnd=5+Math.max(compRows.length,1);
// Editable drivers
const dr=cEnd+2;
section(cost,`A${dr}:I${dr}`,"Drivers (blue = editable)");
cost.getRange(`A${dr+1}:B${dr+4}`).values=[["Wage growth /yr",pct(sgaModel.wage_growth)],["CPI /yr",pct(sgaModel.cpi)],["Bad-debt % of sales",pct(sgaModel.baddebt_ratio)],["COGS % of sales (gross)",pct(sgaModel.cogs_ratio)]];
cost.getRange(`B${dr+1}:B${dr+4}`).format={fill:C.yellow,font:{color:C.input},numberFormat:pctFmt};
tableBody(cost,`A${dr+1}:B${dr+4}`);
// Forward build, pulling forecast revenue from 05 DCF
const fb=dr+6; const labor=comp.find(c=>c.component.startsWith("인건비"))?.ltm_amount||0; const variable=comp.find(c=>c.component.startsWith("변동비"))?.ltm_amount||0; const fixed=comp.find(c=>c.component.startsWith("고정비"))?.ltm_amount||0;
const ltmRev=data.ltmRevenue||1;
section(cost,`A${fb}:H${fb}`,"Forward SG&A → Implied OPM");
cost.getRange(`A${fb+1}:G${fb+1}`).values=[["Line","LTM",`${data.forecastStart}E`,`${data.forecastStart+1}E`,`${data.forecastStart+2}E`,`${data.forecastStart+3}E`,`${data.forecastStart+4}E`]]; header(cost,`A${fb+1}:G${fb+1}`);
cost.getRange(`A${fb+2}:A${fb+9}`).values=[["Revenue (억원)"],["Labour (wage-indexed)"],["Variable (% sales)"],["Fixed (CPI-indexed)"],["Bad debt (% sales)"],["Total SG&A"],["SG&A % of Sales"],["Implied OPM = GM − SG&A%"]];
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
section(cost,`A${ds}:I${ds}`,"Depreciation Split (existing run-off + new CapEx)");
cost.getRange(`A${ds+1}:C${ds+1}`).values=[["Item","Value","Logic"]]; header(cost,`A${ds+1}:C${ds+1}`);
cost.getRange(`A${ds+2}:C${ds+5}`).values=[["D&A / Revenue",pct(depModel.da_ratio),depModel.method||""],["CAPEX / Revenue",pct(depModel.capex_ratio),"무성장 시 DEP만큼 재투자 가정 가능"],["COGS share",pct(depModel.cogs_share),"제조원가 배분 비율"],["SG&A share",pct(depModel.sga_share),"판관비 배분 비율"]];
cost.getRange(`B${ds+2}:B${ds+5}`).format.numberFormat=pctFmt; tableBody(cost,`A${ds+2}:C${ds+5}`);
widths(cost,{A:26,B:16,C:40,D:14,E:30,F:14,G:14,H:12,I:12}); cost.freezePanes.freezeRows(5);

// 10 WACC & Beta — peer unlever/relever
const wsheet = wb.worksheets.add("10 WACC & Beta");
title(wsheet, `${data.company} | WACC & Peer Beta`, waccModel.method || "CAPM Ke = Rf + β·ERP / 세후 Kd / 자본구조 가중 → WACC. 베타는 동종기업 unlever→relever", "G");
section(wsheet,"A4:G4","Peer Beta Unlever → Relever");
wsheet.getRange("A5:D5").values=[["Peer","Levered β","D/E (%)","Unlevered β"]]; header(wsheet,"A5:D5");
const pt=(waccModel.peer_table||[]).map(p=>[p.peer,safe(p.levered_beta),safe(p.de_ratio),safe(p.unlevered_beta)]);
wsheet.getRange(`A6:D${5+Math.max(pt.length,1)}`).values=pt.length?pt:[["Peer beta unavailable — adjusted market beta used",null,null,null]]; tableBody(wsheet,`A6:D${5+Math.max(pt.length,1)}`);
for(const col of ["B","D"]) wsheet.getRange(`${col}6:${col}${5+Math.max(pt.length,1)}`).format.numberFormat="0.000";
wsheet.getRange(`C6:C${5+Math.max(pt.length,1)}`).format.numberFormat="0.0";
const wEnd=5+Math.max(pt.length,1);
section(wsheet,`A${wEnd+2}:G${wEnd+2}`,"CAPM / WACC Bridge");
wsheet.getRange(`A${wEnd+3}:B${wEnd+12}`).values=[["Risk-free rate (Rf)",pct(waccModel.rf)],["Equity risk premium (ERP)",pct(waccModel.erp)],["Adjusted beta (β)",safe(waccModel.beta)],["Cost of equity (Ke)",pct(waccModel.cost_equity)],["Pre-tax cost of debt (Kd)",pct(waccModel.cost_debt)],["Tax rate",pct(waccModel.tax)],["After-tax Kd",pct(waccModel.after_tax_cost_debt)],["Equity weight",pct(waccModel.equity_weight)],["Debt weight",pct(waccModel.debt_weight)],["WACC",pct(waccModel.wacc)]];
for(const r of [wEnd+3,wEnd+4,wEnd+6,wEnd+7,wEnd+8,wEnd+9,wEnd+10,wEnd+11,wEnd+12]) wsheet.getRange(`B${r}`).format.numberFormat=pctFmt;
wsheet.getRange(`B${wEnd+5}`).format.numberFormat="0.000";
wsheet.getRange(`A${wEnd+12}:B${wEnd+12}`).format={font:{bold:true},fill:C.blue};
tableBody(wsheet,`A${wEnd+3}:B${wEnd+12}`);
widths(wsheet,{A:28,B:16,C:14,D:14,E:12,F:12,G:12}); wsheet.freezePanes.freezeRows(5);

// 11 Causal Read — second-level interpretation in the workbook
const pa = data.priceAction || {};
const causal = wb.worksheets.add("11 Causal Read");
title(causal, `${data.company} | Causal Read`, "숫자 너머의 원인 해석 — 기여 분해와 이상신호별 사유(근거 강도 표기)", "H");
section(causal,"A4:H4",pa.verdict||"Price-action attribution");
causal.mergeCells("A5:H6"); causal.getRange("A5").values=[[pa.thesis||""]]; causal.getRange("A5:H6").format={wrapText:true,verticalAlignment:"top",fill:C.pale,font:{color:C.text,size:10}};
causal.getRange("A8:D8").values=[["Driver","Weight","Reading","Evidence / Level"]]; header(causal,"A8:D8");
const attrRows=(pa.attribution||[]).map(a=>[a.driver,a.weight,a.reading,`${a.evidence||""} · ${a.evidence_level||""}`]);
causal.getRange(`A9:D${8+Math.max(attrRows.length,1)}`).values=attrRows.length?attrRows:[["No attribution",null,null,null]]; tableBody(causal,`A9:D${8+Math.max(attrRows.length,1)}`);
const aEnd=8+Math.max(attrRows.length,1);
section(causal,`A${aEnd+2}:H${aEnd+2}`,"Abnormal Signal — Sourced Cause & Verification Recipe");
causal.getRange(`A${aEnd+3}:G${aEnd+3}`).values=[["Signal","Reading (why, not just what)","Top Cause","Evidence","Confidence","Verify — 어디서 → 무엇을 → 판정","Falsifier"]]; header(causal,`A${aEnd+3}:G${aEnd+3}`);
const recipeText=I=>(I.verification||[]).map((r,i)=>`${i+1}. [어디서] ${r.where}\n   [무엇을] ${r.what}\n   [판정] ${r.rule}`).join("\n\n");
const ir=(data.interpreted||[]).map(it=>{const I=it.interpretation||{};const top=(I.cause_candidates||[])[0]||{};return [it.label,I.narrative,top.cause||"근거 대기",top.evidence_level||"—",I.confidence||"",recipeText(I),I.falsifier||""];});
causal.getRange(`A${aEnd+4}:G${aEnd+3+Math.max(ir.length,1)}`).values=ir.length?ir:[["No abnormal signal","자체 과거 범위 내 정상","—","—","—","—","—"]]; tableBody(causal,`A${aEnd+4}:G${aEnd+3+Math.max(ir.length,1)}`);
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
