"""normalize 2단계: 화면용 단일 JSON(screenview) → 단일 HTML(프레임워크 없음, 자기완결).

- 데이터를 HTML 안에 인라인(<script>const DATA=...)한다. 로컬 파일 더블클릭으로 열린다(fetch 없음).
- 상태는 페이지 내 JS 변수/DOM 으로만 관리한다. localStorage/sessionStorage 를 쓰지 않는다.
- 구역 A(브릿지, 손익계산서식 세로 + 조원 병기) / B(조정 대상=상단·일회성, 토글) / C(참고 숫자=슬라이더,
  정성=별도묶음). 원문보기는 상·하단 공통이며 주석 원문 맥락을 넓게 띄우고 뽑은 값을 하이라이트한다.
- 재계산: 조정대상(B)만 EBITDA 를 움직인다. 참고(C)는 안 움직인다. 부호는 screenview 의 sign
  (이익=-1 차감, 비용=+1 가산)을 그대로 쓴다 — 화면은 판정하지 않는다. (재계산 로직 불변)
- 색으로 위험/안전을 딱지 붙이지 않는다. 하이라이트는 '뽑은 위치' 표시일 뿐 판정색이 아니다.
  슬라이더 기준선은 사용자가 정한다(도구가 선 긋지 않음).

사용:
  python src/normalize/render.py out/screenview_000660_XXplzZ.json --out out/screen_000660.html
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"

PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  /* 디자인 시스템(모노톤): 잉크 #1a1a1a · 보조 #5f6764 · 힌트 #9aa19e · 테두리 #e5e7eb ·
     패널 #f7f8f8 · 배경 #fff · 음수만 #b4462b. 강조색·왼쪽 강조선·그라데이션 없음. 폰트 Pretendard.
     * class/id·HTML 구조·JS 무변경 — 스타일 값만 교체(계산·토글·모달 로직 불변). */
  :root { --ink:#1a1a1a; --muted:#5f6764; --hint:#9aa19e; --line:#e5e7eb; --bg:#ffffff; --card:#fff;
          --panel:#f7f8f8; --accent:#1a1a1a; --pill:#eef0f0; --caution:#5f6764; --cautionbg:#f7f8f8;
          --hl:#fde68a; --neg:#b4462b; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.6 "Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;
         color:var(--ink); background:var(--bg); -webkit-font-smoothing:antialiased; }
  .wrap { max-width:980px; margin:0 auto; padding:22px 18px 80px; }
  h1 { font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }
  h2 { font-size:16px; margin:0 0 12px; letter-spacing:-.01em; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:18px; }
  /* 페이지 네비(표시용 링크 — 재계산·게이트와 무관) */
  .pagenav { display:flex; gap:8px; margin:0 0 16px; font-size:13px; flex-wrap:wrap; }
  .pagenav a, .pagenav span { border:1px solid var(--line); border-radius:999px; padding:5px 13px;
      text-decoration:none; color:var(--ink); background:var(--card); }
  .pagenav .cur { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin:0 0 18px;
          box-shadow:0 1px 2px rgba(20,20,20,.04),0 8px 24px -18px rgba(20,20,20,.18); }
  /* 주의 배너 — 왼쪽 강조선 제거, 패널 + 얇은 테두리 + 잉크 텍스트로 */
  .caution { background:var(--cautionbg); border:1px solid var(--line); color:var(--ink);
             padding:10px 14px; border-radius:10px; margin:0 0 10px; font-size:13.5px; }
  .num { font-variant-numeric:tabular-nums; }
  /* 헤드라인 */
  .headline { display:flex; flex-wrap:wrap; gap:10px 24px; align-items:baseline; margin:2px 0 16px; }
  .headline .big { font-size:26px; font-weight:700; font-variant-numeric:tabular-nums; }
  .headline .delta { font-size:13.5px; color:var(--muted); }
  /* 브릿지 — 손익계산서식 세로 */
  .stmt { width:100%; border-collapse:collapse; font-size:15px; }
  .stmt td { padding:8px 4px; vertical-align:baseline; }
  .stmt .op2 { color:var(--muted); display:inline-block; width:30px; }
  .stmt .val2 { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; white-space:nowrap; }
  .stmt .jo { color:var(--muted); font-weight:400; font-size:12.5px; margin-left:6px; }
  .stmt .q { color:var(--muted); font-size:12.5px; }
  .stmt .srccell { text-align:right; width:82px; }
  .stmt .ruleline { border-top:2px solid var(--ink); margin:1px 0; }
  .stmt .eqrow td { font-weight:700; padding-top:10px; }
  .stmt .eqrow .val2 { font-size:17px; }
  .detail { margin-top:14px; border-top:1px dashed var(--line); padding-top:10px; }
  .detail table { width:100%; border-collapse:collapse; font-size:13px; }
  .detail td { padding:5px 6px; border-bottom:1px solid var(--line); }
  .detail .val2 { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  /* 목록 */
  .row { display:flex; align-items:flex-start; gap:10px; padding:10px 4px; border-bottom:1px solid var(--line); }
  .row:last-child { border-bottom:none; }
  .row .amt { margin-left:auto; text-align:right; font-weight:600; white-space:nowrap; font-variant-numeric:tabular-nums; }
  .row .nm { font-weight:500; }
  .pills { margin-top:3px; }
  .pill { display:inline-block; font-size:11px; color:var(--muted); background:var(--pill);
          border:1px solid var(--line); border-radius:999px; padding:1px 8px; margin:2px 4px 0 0; }
  .pill.warn { color:var(--muted); background:var(--pill); border-color:var(--line); }
  .pill.ok { color:#2f3634; background:#e4e7e6; border-color:#d3d8d6; }
  .legend { font-size:12px; color:var(--muted); line-height:1.7; margin:-8px 0 16px; }
  .legend b { color:var(--ink); font-weight:600; }
  input[type=checkbox] { width:17px; height:17px; margin-top:2px; flex:0 0 auto; accent-color:var(--ink); }
  .src { background:none; border:1px solid var(--line); color:var(--ink); border-radius:8px;
         font-size:12px; padding:2px 9px; cursor:pointer; margin-top:2px; }
  .src:hover { background:var(--panel); }
  .disabled { color:var(--hint); }
  .row.child { margin-left:30px; }
  .row.child .nm { font-weight:400; }
  .tree { color:var(--muted); margin-right:4px; }
  .lockmsg { font-size:12px; color:var(--muted); margin-top:3px; }
  /* 수동 조정 스위치(불명 항목 — 사람이 원문 확인 후 직접 포함) */
  .manbox { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin-top:7px;
            padding:8px 10px; border:1px dashed var(--line); border-radius:10px; background:var(--panel); }
  .manlbl { display:inline-flex; align-items:center; gap:6px; font-size:12.5px; color:var(--ink);
            cursor:pointer; font-weight:500; }
  .manbox select { font:inherit; font-size:12.5px; padding:2px 6px; border:1px solid var(--line);
                   border-radius:8px; color:var(--ink); background:#fff; }
  .manbox select:disabled { color:var(--hint); }
  .manhint { font-size:12px; color:var(--muted); margin:2px 0 10px; }
  /* 1단계 확정 배지(✓ 산술로 증명) vs 2단계 추정 배지(⚠ 근접 추측) — 모노톤(글리프로 구분) */
  .confbox { font-size:12.5px; color:var(--ink); background:var(--panel); border:1px solid var(--line);
             border-radius:10px; padding:8px 11px; margin-top:6px; line-height:1.5; }
  .estbox { font-size:12.5px; color:var(--ink); background:var(--panel); border:1px solid var(--line);
            border-radius:10px; padding:8px 11px; margin-top:6px; line-height:1.5; }
  .estbox.off { color:var(--muted); background:var(--panel); border-color:var(--line); }
  .estbox .src { margin-left:6px; }
  .sliderbar { display:flex; align-items:center; gap:12px; margin:2px 0 14px; font-size:13px; color:var(--muted); }
  .sliderbar input[type=range] { flex:1; accent-color:var(--ink); }
  .grouphd { font-size:13px; color:var(--muted); margin:18px 0 4px; padding-top:12px; border-top:1px solid var(--line); }
  /* 모달 */
  .ov { position:fixed; inset:0; background:rgba(26,26,26,.45); display:none; align-items:center;
        justify-content:center; padding:20px; z-index:10; }
  .ov.on { display:flex; }
  .modal { background:#fff; border:1px solid var(--line); border-radius:14px; max-width:680px; width:100%; padding:20px; max-height:84vh; overflow:auto;
           box-shadow:0 10px 40px -12px rgba(20,20,20,.3); }
  .modal h3 { margin:0 0 4px; font-size:16px; padding-right:24px; }
  .modal .loc { color:var(--muted); font-size:13px; margin-bottom:10px; }
  .modal .cap { font-size:12px; color:var(--muted); margin:12px 0 4px; }
  /* JS 가 인라인으로 넣는 초록 캡션(#25603f)을 모노톤으로 덮어씀 — JS 무변경, CSS 로만 오버라이드 */
  .modal .cap[style*="25603f"] { color:var(--ink) !important; }
  .modal .excerpt { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 14px;
                    font-size:13.5px; line-height:1.7; max-height:48vh; overflow:auto; }
  .modal .excerpt .exrow { padding:1.5px 0; }
  .modal .excerpt .exrow.hlrow { background:#fff; border-radius:3px; margin:0 -6px; padding:1.5px 6px; }
  .modal .excerpt .gap { color:var(--hint); font-size:12px; text-align:center; padding:5px 0; user-select:none; }
  .modal mark { background:var(--hl); color:inherit; padding:0 1px; border-radius:2px; }
  .modal .exbtn { margin-top:9px; }
  /* 영업이익 원문보기 — 재구성 손익계산서 */
  .istbl { width:100%; border-collapse:collapse; font-size:14px; margin:8px 0 4px; }
  .istbl td { padding:7px 6px; border-bottom:1px solid var(--line); }
  .istbl .isop { color:var(--muted); width:34px; font-variant-numeric:tabular-nums; }
  .istbl .isval { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .istbl .isval .jo { color:var(--muted); font-weight:400; font-size:12px; margin-left:3px; }
  .istbl tr.sub td { font-weight:600; border-top:1px solid var(--ink); }
  .istbl tr.hl td { background:var(--hl); font-weight:700; }
  .modal .meta { color:var(--muted); font-size:12px; margin-top:10px; }
  .modal .x { float:right; border:none; background:none; font-size:22px; cursor:pointer; color:var(--muted); line-height:1; }
  .empty { color:var(--muted); font-size:13.5px; padding:6px 2px; }
  footer { color:var(--muted); font-size:12px; margin-top:26px; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="h-title"></h1>
  <div class="sub" id="h-sub"></div>
  <div class="pagenav">
    <a id="nav1" href="#">← ① 이익의 질 (재무제표로 이익 검증)</a>
    <span class="cur">② 조정 EBITDA</span>
  </div>
  <div id="cautions"></div>
  <div class="legend">태그 읽기 — <b>표시위치</b>: 상단(영업이익 안 · 조정 가능) / 하단·불명(참고). ·
    <b>손익계산서 확정</b>: XBRL 손익계산서 라인과 당기금액이 일치해 결정론으로 확정(계정명 매칭 아님). ·
    <b>근거 확인</b>: LLM 이 제시한 계상 위치 근거가 인용에 실제로 있음이 검증됨(없으면 상단→불명 강등 = 근거 게이트). ·
    <b>⚠ 표시위치 불안정</b>: 반복 실행에서 회차마다 달라 조정에서 제외(원문 확인). ·
    <b>근거강도</b>: 명시(금액이 인용에 그대로) / 추정(표 구조에서 유추 — 원문보기 발췌를 넓혀 근거를 함께 보임). ·
    <b>조정에 포함(수동)</b>: 불명 항목을 원문 확인 후 사용자가 직접 조정에 넣는 스위치(도구 판단 아님). ·
    <b>합계·구성 계층(1단계·산술)</b>: 주석 표의 산술(합계=구성 합)로 <b>증명</b>한 포함관계 → 잠금. 합계를 넣으면 구성 일괄 반영(구성 잠김), 구성만 개별 선택도 가능 — 이중가산 산술 불가. 이름 못 얻은 나머지는 <b>그 외(도구 계산값)</b>로 채워 합=구성을 맞춘다. ·
    <b>추정 묶음(2단계·근접)</b>: 서로 다른 주석이라 산술은 못 했으나 금액이 근접(≥99.5%)·동부호·동성격이라 포함관계로 <b>추정</b>해 잠근 것 — 추정임을 밝히고 [묶음 해제]로 사용자가 풀 수 있다(기본은 안전측 잠금). ·
    <b>⚠ 포함관계 가능성(3단계·경고)</b>: 근접 90~99.5% — 남남 가능성이 있어 잠그지 않고 경고만(원문 확인 요망). ·
    <b>D&A 이미 포함</b>: 후보 금액이 D&A(감가·무형 상각) 셀(XBRL 개념코드로 식별)과 일치하면 조정 자격을 박탈해 참고로 — 조정에 넣으면 EBITDA 에 이중 반영되기 때문. 손상차손 등은 D&A 개념이 아니라 안 걸린다(과제거 방지).</div>

  <div class="card">
    <h2>구역 A — EBITDA 브릿지</h2>
    <div class="headline">
      <div><div id="hl-label" style="font-size:12px;color:var(--muted)"></div>
        <div class="big" id="hl-norm"></div></div>
      <div class="delta" id="hl-delta"></div>
    </div>
    <table class="stmt" id="bridge"></table>
    <div class="detail" id="bridge-detail"></div>
  </div>

  <div class="card">
    <h2>구역 B — 조정 대상 (영업이익 위 · 일회성)</h2>
    <div class="sub" style="margin:-4px 0 10px">영업이익 안에 이미 반영된 일회성 항목입니다. 체크하면 EBITDA 에서
      제외합니다 — 이익 항목은 빼고, 비용 항목은 도로 더합니다. (매출원가·판관비에 묻힌 일회성을 캐내는 자리)</div>
    <div id="adjust"></div>
  </div>

  <div class="card">
    <h2>구역 C — 참고 항목 (영업이익 아래 · 표시위치 불명)</h2>
    <div class="sub" style="margin:-4px 0 8px">영업이익 아래(기타영업외 등)에 표시됐거나 표시위치가 불명한 항목입니다.
      애초에 EBITDA 에 없어 조정(도로 더하기) 대상이 아닙니다 — 손익계산서에 별도 줄로 보이니 원문으로 확인만.</div>
    <div class="sliderbar">
      <span>금액 기준(백만원 이상만 표시):</span>
      <input type="range" id="slider" min="0" value="0">
      <span class="num" id="slider-val" style="min-width:120px;text-align:right"></span>
    </div>
    <div id="reference"></div>
    <div id="refunknown-wrap" style="display:none">
      <div class="grouphd">표시위치 불명·불안정 — 영업이익 위/아래를 확정 못 했거나 회차마다 달라 도구는 조정하지 않음.</div>
      <div class="manhint">도구가 계상 위치를 확인하지 못한 항목입니다. 원문을 확인하고 <b>영업이익 안에 계상된 것이 맞으면</b>
        아래 “조정에 포함(수동)” 스위치로 직접 포함하십시오 — 손익방향(이익=제외 시 뺌 / 비용=제외 시 더함)을 정하면 EBITDA 에 반영됩니다.
        수동 포함은 <b>사용자 판단</b>이며 도구 판단과 구분됩니다.</div>
      <div id="refunknown"></div>
    </div>
    <div id="qual-wrap" style="display:none">
      <div class="grouphd">금액 없는 정성적 항목 — 우발부채·보고기간후사건 등. 금액이 없어 슬라이더 대상이 아닙니다.</div>
      <div id="qualitative"></div>
    </div>
  </div>

  <footer id="foot"></footer>
</div>

<div class="ov" id="ov"><div class="modal">
  <button class="x" onclick="closeSrc()">×</button>
  <h3 id="m-title"></h3>
  <div class="loc" id="m-loc"></div>
  <div id="m-info"></div>
  <div id="m-body"></div>
  <div class="meta" id="m-meta"></div>
</div></div>

<script>
const DATA = __DATA__;

// ---- state: 페이지 내 변수만. localStorage/sessionStorage 미사용. ----
const checked = {};            // adjustment id -> bool
const manual = {};             // reference_unknown id -> {on:bool, dir:"이익"|"비용"|null} (사용자 수동 포함)
const unlinked = new Set();    // 2단계 추정 묶음을 사용자가 해제한 합계 id (해제 시 두 항목 독립)
const sameAmtUnlinked = new Set();  // 동일금액 잠금을 사용자가 해제한 그룹 id (해제 시 중복분도 각자 Σ)
let sliderMin = 0;             // 사용자 조절 기준(도구가 정하지 않음)
const SRC = {};                // 브릿지 원문 레지스트리(key -> {src, ctx})
const BYID = {};               // 후보 레지스트리(id -> candidate). onclick 에 JSON 인라인 안 함(견고).
[...DATA.adjustments, ...DATA.reference, ...(DATA.reference_unknown||[]), ...(DATA.reference_qualitative||[])].forEach(x => BYID[x.id] = x);

const esc = s => (s==null?"":String(s)).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const fmtM = n => (n===null||n===undefined) ? "불명" : Math.round(n).toLocaleString("en-US");
const jo = m => (m===null||m===undefined) ? "" : "약 " + (m/1e6).toLocaleString("en-US",{minimumFractionDigits:1,maximumFractionDigits:1}) + "조원";
const fmtJo = m => `${fmtM(m)} 백만원 <span class="jo">(${jo(m)})</span>`;

function pills(o){
  let h="";
  if(o.표시위치){
    const xbrl = o.표시위치_source==="xbrl";
    const gateOk = !xbrl && o.표시위치_근거_확인;
    const cls = (xbrl||gateOk) ? "pill ok" : "pill";
    const suf = xbrl ? " · 손익계산서 확정" : (gateOk ? " · 근거 확인" : "");
    const tip = "이 회사가 손익계산서 어디에 표시했나. 상단=영업이익 안(조정 가능), 하단·불명=참고."
      + (xbrl?" 손익계산서 확정=XBRL 라인 금액과 정확히 일치해 결정론으로 확정됨(계정명 매칭 아님).":"")
      + (gateOk?(" 근거 확인=LLM 이 제시한 계상 위치 근거가 인용에 실제로 있음이 검증됨: “"+o.표시위치_근거_확인+"”."):"");
    h+=`<span class="${cls}" title="${esc(tip)}">표시위치: ${esc(o.표시위치)}${suf}</span>`;
  }
  if(o.표시위치_불안정) h+=`<span class="pill warn" title="반복 실행에서 표시위치가 회차마다 달랐습니다(${esc((o.표시위치_observed||[]).join('/'))}). 조정 대상에서 제외하고 참고로 돌렸습니다 — 원문으로 직접 확인하세요.">⚠ 표시위치 불안정</span>`;
  if(o.기간){
    const cur = o.기간==="당기", pri = o.기간==="전기";
    const bcls = cur ? "pill ok" : "pill warn";
    const bsuf = o.기간_근거==="xbrl" ? " · XBRL확정" : (o.기간_근거==="citation" ? " · 인용" : "");
    const btip = "이 금액이 당기(올해) 것인가. 당기만 EBITDA 조정 대상. 주석은 당기·전기를 나란히 적어 "
      + "surface 가 전기(작년) 금액을 집을 수 있어 검증한다: XBRL 기간 컨텍스트(CFY/PFY) 우선, 없으면 인용의 기간 표현.";
    if(cur||pri||o.period_gated) h+=`<span class="${bcls}" title="${esc(btip)}">기간: ${esc(o.기간)}${bsuf}</span>`;
  }
  if(o.조정성격) h+=`<span class="pill">조정성격: ${esc(o.조정성격)}</span>`;
  if(o.손익방향==="이익"||o.손익방향==="비용") h+=`<span class="pill">${o.손익방향}${o.손익방향==="이익"?" · 제외 시 이익에서 빠짐":" · 제외 시 도로 더함"}</span>`;
  (o.성격||[]).forEach(s=>h+=`<span class="pill">${esc(s)}</span>`);
  if(o.근거강도) h+=`<span class="pill" title="금액이 인용에서 얼마나 직접 확인되나. 명시=금액이 주석에 그대로 있고 인용만으로 확인. 추정=표 구조·문맥에서 유추(원문보기 발췌를 넓혀 유추 근거를 함께 보임). 일회성 여부의 근거 강도가 아님.">근거강도: ${esc(o.근거강도)}</span>`;
  if(o.appeared_in && o.of_runs) h+=`<span class="pill">재현 ${o.appeared_in}/${o.of_runs}</span>`;
  if(o.merged_count && o.merged_count>1) h+=`<span class="pill">중복 ${o.merged_count}건 통합</span>`;
  return `<div class="pills">${h}</div>`;
}

// ---- 재계산 (공식 불변: base + Σ sign×amount. 잠긴 항목만 Σ에서 게이팅) ----
// 포함관계는 '계층'이다 — 합계(부모)와 구성(자식). 표 산술로 합계=구성 합이 확정됐으므로:
//  · 합계 체크 → 구성 전부 자동 체크(합계 넣기 = 구성 전부 넣기). Σ 엔 합계가 한 번만 든다.
//  · 구성 개별 체크(합계 off) → 그 구성만 Σ(부분 조정). 구성 체크는 합계를 자동 체크 안 함.
//  · locked(구성)=부모 합계가 켜짐 → 구성은 Σ 에서 제외(합계로 이미 반영). 이래서 이중가산이 산술 불가.
// rawOn = 사용자가 켠 상태(체크 or 수동 on). locked 를 다시 참조 안 해 순환 없음.
const MANUAL_IDS = new Set((DATA.reference_unknown||[]).map(r=>r.id));
function rawOn(id){ if(checked[id]) return true; const m=manual[id]; return !!(m&&m.on); }
function linkActive(id){                    // 이 항목의 부모(합계) 링크가 유효한가 — 추정 묶음이 해제되면 무효(독립)
  const a = BYID[id]; if(!a || !a.parent_id) return false;
  const p = BYID[a.parent_id]; if(!p) return false;
  return !(p.containment_estimated && unlinked.has(p.id));
}
function locked(id){                        // 계층: 구성은 (유효 링크의) 부모(합계)가 켜지면 잠긴다. 합계는 안 잠김.
  const a = BYID[id]; if(!a || !a.parent_id) return false;
  return linkActive(id) && rawOn(a.parent_id);
}
// (1-b) 동일금액 안전망: 같은 금액·부호가 2건 이상이면 대표(primary)만 Σ 에 반영하고 중복(dup)은
// 게이팅한다(병합·tier-2 성공과 무관한 독립 잠금). 사용자가 그룹을 해제하면 중복도 각자 반영(재경고).
function sameAmtLocked(id){
  const a = BYID[id]; if(!a || a.same_amount_role!=="dup") return false;
  return !sameAmtUnlinked.has(a.same_amount_group);
}
function unlinkSameAmount(gid){              // 동일금액 잠금 해제/재잠금 토글.
  if(sameAmtUnlinked.has(gid)) sameAmtUnlinked.delete(gid); else sameAmtUnlinked.add(gid);
  renderAdjust(); renderReferenceUnknown(); renderHeadline();
}
// 수동 포함(불명 항목): 손익방향 태그가 있으면 그 부호, 없으면 사용자가 고른 방향의 부호.
function manualState(id){ return manual[id] || (manual[id] = {on:false, dir:null}); }
function setOn(id, val){                    // 자동/수동 어느 경로든 그 항목을 켜고/끈다(계층 전파용)
  if(MANUAL_IDS.has(id)){ manualState(id).on = val; } else { checked[id] = val; }
}
function propagateHierarchy(id, on){        // 합계 on/off → (유효 링크의) 구성 전부 따라감. 잠금이 Σ 중복을 막음.
  const a = BYID[id]; if(!a || !a.children_ids) return;
  a.children_ids.forEach(c=>{ if(linkActive(c)) setOn(c, on); });
}
function unlinkEstimated(id){               // 2단계 추정 묶음 해제/재연결 토글.
  const a = BYID[id];
  if(unlinked.has(id)){
    unlinked.delete(id);
    propagateHierarchy(id, rawOn(id));      // 재연결: 합계가 켜져 있으면 구성 다시 흡수(체크·잠김)
  } else {
    unlinked.add(id);                       // 해제: 두 항목 독립. 흡수돼 있던 구성 켜짐을 끈다(갑작스런 이중가산 방지)
    (a && a.children_ids || []).forEach(c=>setOn(c, false));
  }
  renderAdjust(); renderReferenceUnknown(); renderHeadline();
}
function effDir(r){ const st=manualState(r.id);
  return (r.손익방향==="이익"||r.손익방향==="비용") ? r.손익방향 : st.dir; }
function manualSign(dir){ return dir==="이익" ? -1 : (dir==="비용" ? 1 : null); }   // 부호 규약 불변
function manualActive(r){ const st=manualState(r.id);
  return st.on && r.amount_million!=null && manualSign(effDir(r))!=null; }
function manualIncluded(r){ return manualActive(r) && !locked(r.id) && !sameAmtLocked(r.id); }   // 실제 Σ 반영(계층·동일금액 게이팅)
function normalizedEBITDA(){
  let t = DATA.bridge.ebitda_base_million;
  for(const a of DATA.adjustments){                       // 구역 B 토글 — 계층·동일금액 잠금은 Σ 에서 제외
    if(checked[a.id] && a.toggleable && !locked(a.id) && !sameAmtLocked(a.id)) t += a.sign * a.amount_million;
  }
  for(const r of (DATA.reference_unknown||[])){          // 수동 포함 — 같은 공식, 같은 Σ 에 항 추가
    if(manualIncluded(r)) t += manualSign(effDir(r)) * r.amount_million;   // 잠긴(합계 흡수·동일금액 중복) 항목은 게이팅
  }
  return t;
}

function renderHeadline(){
  const base = DATA.bridge.ebitda_base_million, norm = normalizedEBITDA();
  const nAdj = DATA.adjustments.filter(a=>checked[a.id] && a.toggleable && !locked(a.id) && !sameAmtLocked(a.id)).length;
  const nMan = (DATA.reference_unknown||[]).filter(manualIncluded).length;
  const nTot = nAdj + nMan;
  document.getElementById("hl-label").textContent = nTot===0
    ? "현재 EBITDA (조정 0건)"
    : `조정 후 EBITDA (일회성 제외 · ${nTot}건 반영${nMan?` · 수동 ${nMan}건`:""})`;
  document.getElementById("hl-norm").innerHTML = fmtJo(norm);
  const d = norm - base;
  const sg = d>0?"+":(d<0?"−":"±");
  document.getElementById("hl-delta").innerHTML = nTot===0
    ? `기준선 그대로`
    : `기준선 ${fmtM(base)} 백만원 · 조정 ${sg}${fmtM(Math.abs(d))} 백만원`;
}

// ---- 구역 A 브릿지 (손익계산서식 세로) ----
function srcBtn(key, src, ctx){ if(!src) return ""; SRC[key]={src, ctx}; return `<button class="src" onclick="showSrcById('${key}')">원문보기</button>`; }

function renderBridge(){
  const b = DATA.bridge;
  const oiBtn = b.operating_income.income_statement
    ? `<button class="src" onclick="showStatement()">원문보기</button>`   // 손익계산서 재구성 표
    : srcBtn("oi", b.operating_income.source, null);
  let h = `<tr><td>영업이익 <span class="q">(재무제표)</span></td>
             <td class="val2">${fmtJo(b.operating_income.amount_million)}</td>
             <td class="srccell">${oiBtn}</td></tr>`;
  const added = b.da.lines.filter(l=>l.added);
  added.forEach((l,i)=>{
    h += `<tr><td><span class="op2">(+)</span>${esc(l.kind)}</td>
            <td class="val2">${fmtJo(l.value_million)}</td>
            <td class="srccell">${srcBtn("add"+i, l.source, l["원문맥락"])}</td></tr>`;
  });
  h += `<tr class="rule"><td colspan="3"><div class="ruleline"></div></td></tr>`;
  h += `<tr class="eqrow"><td>EBITDA 기준선</td><td class="val2">${fmtJo(b.ebitda_base_million)}</td><td></td></tr>`;
  document.getElementById("bridge").innerHTML = h;

  // 개별내역(성격별 합계에 이미 포함, 재가산 안 함) — 세로 표. 리스는 여기 한 번만 표시.
  const detail = b.da.lines.filter(l=>!l.added);
  const hasLeaseLine = b.da.lines.some(l=>(l.kind||"").includes("리스"));
  let dh = "";
  if(b.da.path) dh += `<div style="font-size:12.5px;color:var(--muted);margin-bottom:6px">D&A 경로: <b>${esc(b.da.path)}</b>${b.da.method?" ("+esc(b.da.method)+")":""}${b.da.note_title?" · "+esc(b.da.note_title):""}</div>`;
  if(detail.length){
    dh += `<div style="font-size:12.5px;color:var(--muted);margin-bottom:4px">개별내역(성격별 합계에 이미 포함 — 재가산 안 함):</div><table>`;
    detail.forEach((l,i)=>{
      dh += `<tr><td>${esc(l.kind)}</td><td class="val2">${fmtM(l.value_million)} 백만원</td>
             <td style="text-align:right;width:82px">${srcBtn("det"+i, l.source, l["원문맥락"])}</td></tr>`;
    });
    dh += `</table>`;
  }
  // 리스가 라인 어디에도 없을 때만(예: 유형자산 통합 회사) 별도줄로 한 번 표시.
  if(b.da.lease && b.da.lease.present && !hasLeaseLine){
    dh += `<div style="font-size:12.5px;color:var(--muted);margin-top:8px">리스 사용권자산 감가상각비: <b class="num">${fmtM((b.da.lease.value_won||0)/1e6)}</b> 백만원 (${esc(b.da.lease.mode)}) ${srcBtn("lease", b.da.lease.source, null)}</div>`;
  }
  document.getElementById("bridge-detail").innerHTML = dh;
}

// 경고 배지: 표 산술로 확정 못 했으나 금액이 근접한 포함관계 '가능성'. 잠그지 않고 알리기만 한다.
function warnBadge(o){
  if(!o.containment_warn || !o.containment_warn.length) return "";
  const w = o.containment_warn[0];
  const pct = Math.round((w.ratio||0)*100);
  return `<div class="lockmsg" style="color:var(--caution)">⚠ 포함관계 가능성 — 「${esc(w.partner_name)}」과(와) 금액이 근접(${pct}%)합니다. 표 산술로 확정하진 못했으나(다른 주석·나열식) 둘 다 반영 시 이중가산일 수 있습니다. 원문 확인 요망.</div>`;
}
function roleTag(o, isChild){
  const est = o.containment_estimated;
  if(o.is_total){
    if(est) return unlinked.has(o.id) ? `<span class="pill warn">추정 묶음 해제됨 · 독립</span>`
                                      : `<span class="pill warn">합계 · 추정 묶음(2단계)</span>`;
    return `<span class="pill">합계 · 구성 계층(산술)</span>`;
  }
  if(o.computed_residual) return `<span class="pill">그 외 · 도구 계산값</span>`;
  if(o.parent_id){
    if(est) return linkActive(o.id) ? `<span class="pill warn">구성 · 추정 묶음(2단계)</span>`
                                    : `<span class="pill warn">추정 묶음 해제됨 · 독립</span>`;
    return `<span class="pill">합계의 구성(산술)</span>`;
  }
  return "";
}
// 1단계 확정 배지(✓) — 산술로 증명된 종속 관계. 확신과 추측을 화면에서 구분한다.
function confBox(o){
  if(!(o.is_total && !o.containment_estimated)) return "";
  const ar = o.containment_arithmetic || {};
  const eq = ar.equation ? ` (${esc(ar.equation)})` : "";
  return `<div class="confbox">✓ 종속 관계 확인 — 주석 표에서 산술로 확인했습니다${eq}.</div>`;
}
// 2단계 추정 배지(⚠) + 해제/재연결 버튼 (합계 쪽에만). 도구는 확신(산술)과 추측(근접)을 구분해 말한다.
function estBox(o){
  if(!(o.containment_estimated && o.is_total)) return "";
  const m = o.containment_estimated_meta || {};
  const pct = (m.ratio!=null) ? (m.ratio*100).toFixed(2) : "";
  if(unlinked.has(o.id)){
    return `<div class="estbox off">묶음을 해제하면 두 항목을 각각 조정할 수 있습니다. 단, 실제로 포함 관계라면 같은 금액이 두 번 반영됩니다. 원문을 확인하셨는지 확인하십시오.
      <button class="src" onclick="unlinkEstimated('${o.id}')">다시 묶기</button></div>`;
  }
  return `<div class="estbox">⚠ 종속 관계 추정 — 두 항목의 금액이 거의 같아(${pct}%) 하나가 다른 하나에 포함된 것으로 추정해 묶었습니다. 다만 서로 다른 주석에 있어 확인하지 못했습니다. 원문을 확인하신 후, 별개 항목이면 묶음을 해제하십시오.
    <button class="src" onclick="unlinkEstimated('${o.id}')">묶음 해제</button></div>`;
}
// (1-b) 동일금액 잠금 배지/박스 — 금액·부호가 정확히 같은 항목이 둘 이상. 대표만 Σ 반영, 나머지는 잠금.
// 경고가 아니라 잠금이다(경고로는 사용자가 둘 다 켠다). 별개 항목이면 [묶음 해제]로 풀 수 있다.
function sameAmtBox(o){
  if(!o.same_amount_group) return "";
  const partners = (o.same_amount_partners||[]).map(p=>esc(p.항목명||"")).join(", ") || "다른 항목";
  const unl = sameAmtUnlinked.has(o.same_amount_group);
  if(o.same_amount_role==="dup"){
    return unl
      ? `<div class="estbox off">동일 금액 묶음 해제됨 · 독립 — 「${partners}」과 별개로 반영됩니다. 실제로 같은 항목이면 같은 금액이 두 번 반영되니 원문을 확인하십시오.
         <button class="src" onclick="unlinkSameAmount('${o.same_amount_group}')">다시 묶기</button></div>`
      : `<div class="estbox">⚠ 동일 금액 항목 — 「${partners}」과(와) 금액·부호가 정확히 같습니다(다른 주석에서 발굴). 같은 항목이 두 번 올라온 것일 수 있어 하나만(대표) 반영됩니다. 별개 항목이면 원문 확인 후 해제하십시오.
         <button class="src" onclick="unlinkSameAmount('${o.same_amount_group}')">묶음 해제</button></div>`;
  }
  // 대표(primary)
  return unl ? `<span class="pill warn">동일금액 묶음 해제됨 · 독립</span>`
             : `<span class="pill warn">동일금액 그룹 · 대표(반영)</span>`;
}
// (1-a) 여러 주석에서 병합된 항목 — 양쪽 주석위치를 함께 보인다(원문보기 투명성).
function mergedLocNote(o){
  if(!o._merged_locations || o._merged_locations.length<2) return "";
  const locs = o._merged_locations.map(l=>esc(l["주석위치"]||"")).filter(Boolean).join(" · ");
  return `<div class="lockmsg">여러 주석에서 같은 금액으로 발굴돼 병합됨: ${locs} (원문보기로 각 근거 확인)</div>`;
}
// ---- 구역 B (합계/구성 계층 들여쓰기 — 합계 체크 시 구성 일괄 반영) ----
function adjRow(a, isChild){
  const lock = locked(a.id);              // 계층: 부모(합계)가 켜지면 이 구성은 잠긴다(합계로 일괄 반영)
  const dupLock = sameAmtLocked(a.id);    // 동일금액 중복분: 대표만 반영, 이건 잠금(Σ 제외)
  const disabled = !a.toggleable || lock || dupLock;
  const amt = a.amount_million!==null ? fmtM(a.amount_million)+" 백만원" : "금액 불명";
  const cb = `<input type="checkbox" id="cb-${a.id}" ${checked[a.id]?"checked":""} ${disabled?"disabled":""} onchange="toggle('${a.id}')">`;
  const marker = isChild ? `<span class="tree">└</span>` : "";
  let msg = "";
  if(lock) msg = `<div class="lockmsg">합계에 포함됨 — 합계를 조정에 넣어 이 구성은 일괄 반영됩니다(개별 조정하려면 합계를 해제).</div>`;
  else if(!a.toggleable) msg = `<div class="lockmsg">토글 불가: ${esc(a.toggle_reason)}</div>`;
  return `<div class="row${disabled?' disabled':''}${isChild?' child':''}">${cb}
    <div><div class="nm">${marker}${esc(a.항목명)}</div>${pills(a)}${roleTag(a,isChild)}${warnBadge(a)}${confBox(a)}${estBox(a)}${sameAmtBox(a)}${mergedLocNote(a)}${msg}</div>
    <div class="amt">${a.sign===1?"+":(a.sign===-1?"−":"")} ${amt}
      <div><button class="src" onclick="showItemById('${a.id}')">원문보기</button></div></div></div>`;
}
function renderAdjust(){
  const box = document.getElementById("adjust");
  if(!DATA.adjustments.length){ box.innerHTML = `<div class="empty">조정대상 후보 없음 (surface 산출물이 없거나 조정대상 항목이 없음).</div>`; return; }
  const byId = {}; DATA.adjustments.forEach(a=>byId[a.id]=a);
  let h="";
  for(const a of DATA.adjustments){
    if(a.parent_id && byId[a.parent_id] && linkActive(a.id)) continue; // 유효 링크면 합계 밑에서(해제된 추정 자식은 최상위로)
    h += adjRow(a, false);
    (a.children_ids||[]).forEach(cid=>{ if(byId[cid] && linkActive(cid)) h += adjRow(byId[cid], true); });
  }
  box.innerHTML = h;
}

// ---- 구역 C: 숫자(슬라이더) + 정성(별도) ----
function renderReference(){
  const box = document.getElementById("reference");
  const items = DATA.reference;
  if(!items.length){ box.innerHTML = `<div class="empty">참고(숫자) 항목 없음.</div>`; }
  else {
    const maxA = Math.max(0, ...items.map(r=>r.amount_million||0));
    document.getElementById("slider").max = Math.ceil(maxA);
    let h="", shown=0;
    for(const r of items){
      if(r.amount_million < sliderMin) continue;   // 기준 미만 숨김
      shown++;
      // D&A 이중계상 차단 항목: 조정 자격 박탈됨을 명시(조정에 넣으면 이중 반영).
      let da = "";
      if(r.da_double_count){
        da = `<span class="pill warn">D&A 이미 포함 · 상각 확인(개념코드)</span>`
           + (r.not_adjustable_reason ? `<div class="lockmsg">${esc(r.not_adjustable_reason)}</div>` : "");
      }
      h += `<div class="row"><div><div class="nm">${esc(r.항목명)}</div>${pills(r)}${da}</div>
        <div class="amt">${fmtM(r.amount_million)} 백만원<div><button class="src" onclick="showItemById('${r.id}')">원문보기</button></div></div></div>`;
    }
    box.innerHTML = shown ? h : `<div class="empty">기준(${fmtM(sliderMin)} 백만원) 이상 항목 없음. 슬라이더를 낮추세요.</div>`;
  }
  document.getElementById("slider-val").textContent = fmtM(sliderMin)+" 백만원";
}

function manCtrl(r){
  const st = manualState(r.id);
  const lock = locked(r.id);              // 계층: 부모(합계)가 켜지면 이 구성은 합계로 일괄 반영됨
  if(sameAmtLocked(r.id)){                 // (1-b) 동일금액 중복분: 대표만 반영. 수동 포함도 잠근다(위 배지가 [묶음 해제] 제공).
    const cb = `<label class="manlbl"><input type="checkbox" disabled> 조정에 포함(수동)</label>`;
    return `<div class="manbox disabled">${cb} <span class="lockmsg" style="margin:0">동일 금액 대표 항목만 반영됩니다 — 별개 항목이면 위 [묶음 해제] 후 포함하십시오.</span></div>`;
  }
  if(r.computed_residual){                // '그 외' 잔여 — 도구 계산값(원문 인용 아님). 합계에 포함되며 개별로도 넣을 수 있음.
    const cb = `<label class="manlbl"><input type="checkbox" ${st.on?"checked":""} ${lock?"disabled":""} onchange="toggleManual('${r.id}')"> 조정에 포함(수동)</label>`;
    const note = lock ? "합계에 포함됨." : "성격 미확인 잔여(도구 계산값) — 합계를 넣으면 함께 반영됩니다. 개별 포함도 가능.";
    return `<div class="manbox disabled">${cb} <span class="lockmsg" style="margin:0">${note}</span></div>`;
  }
  if(r.amount_million==null){
    return `<div class="manbox">금액 불명이라 수동 조정 불가 — 원문보기로 확인만.</div>`;
  }
  const dirFixed = (r.손익방향==="이익"||r.손익방향==="비용");
  const cb = `<label class="manlbl"><input type="checkbox" ${st.on?"checked":""} ${lock?"disabled":""} onchange="toggleManual('${r.id}')"> 조정에 포함(수동)</label>`;
  if(lock){                              // 계층 잠금: 부모 합계가 켜져 이 구성은 합계로 일괄 반영됨
    return `<div class="manbox disabled">${cb}
      <span class="lockmsg" style="margin:0">합계에 포함됨 — 합계를 조정에 넣어 일괄 반영됩니다(개별 조정하려면 합계를 해제).</span></div>`;
  }
  let dirCtrl;
  if(dirFixed){
    dirCtrl = `<span class="pill">손익방향: ${r.손익방향}${r.손익방향==="이익"?" · 제외 시 뺌":" · 제외 시 더함"}</span>`;
  } else {
    dirCtrl = `<select onchange="setManualDir('${r.id}',this.value)" ${st.on?"":"disabled"}>
      <option value="">손익방향 선택…</option>
      <option value="이익" ${st.dir==="이익"?"selected":""}>이익 (제외 시 뺌)</option>
      <option value="비용" ${st.dir==="비용"?"selected":""}>비용 (제외 시 더함)</option></select>`;
  }
  let tail = "";
  if(manualIncluded(r)){
    const sg = manualSign(effDir(r))===1 ? "+" : "−";
    tail = `<span class="pill ok">수동 포함됨 · ${sg}${fmtM(r.amount_million)} 백만원 반영 (사용자 판단)</span>`;
  } else if(st.on && !dirFixed && !st.dir){
    tail = `<span class="lockmsg" style="margin:0">손익방향을 선택하면 EBITDA 에 반영됩니다.</span>`;
  }
  return `<div class="manbox">${cb} ${dirCtrl} ${tail}</div>`;
}
function refUnknownRow(r, isChild){
  const why = r.not_adjustable_reason ? `<div class="lockmsg">${esc(r.not_adjustable_reason)}</div>` : "";
  const marker = isChild ? `<span class="tree">└</span>` : "";
  const srcBtn = r.computed_residual ? "" : `<div><button class="src" onclick="showItemById('${r.id}')">원문보기</button></div>`;
  return `<div class="row${isChild?' child':''}"><div><div class="nm">${marker}${esc(r.항목명)}</div>${pills(r)}${roleTag(r,isChild)}${warnBadge(r)}${confBox(r)}${estBox(r)}${sameAmtBox(r)}${mergedLocNote(r)}${why}${manCtrl(r)}</div>
    <div class="amt">${r.amount_million!==null?fmtM(r.amount_million)+" 백만원":"금액 불명"}${srcBtn}</div></div>`;
}
function renderReferenceUnknown(){
  const items = DATA.reference_unknown || [];
  if(!items.length) return;
  document.getElementById("refunknown-wrap").style.display = "";
  const byId = {}; items.forEach(r=>byId[r.id]=r);
  let h="";
  for(const r of items){
    if(r.parent_id && byId[r.parent_id] && linkActive(r.id)) continue;   // 유효 링크면 합계 밑에서(해제된 추정 자식은 최상위로)
    h += refUnknownRow(r, false);
    (r.children_ids||[]).forEach(cid=>{ if(byId[cid] && linkActive(cid)) h += refUnknownRow(byId[cid], true); });
  }
  document.getElementById("refunknown").innerHTML = h;
}
function toggleManual(id){
  const st=manualState(id); st.on=!st.on;
  propagateHierarchy(id, st.on);          // 합계(수동)면 구성 전부 따라 on/off. 잠금이 Σ 중복 방지.
  renderReferenceUnknown(); renderAdjust(); renderHeadline();   // 교차구역 반영 위해 구역 B 도 재렌더
}
function setManualDir(id,v){ const st=manualState(id); st.dir=v||null; renderReferenceUnknown(); renderHeadline(); }

function renderQualitative(){
  const items = DATA.reference_qualitative || [];
  if(!items.length) return;
  document.getElementById("qual-wrap").style.display = "";
  let h="";
  for(const r of items){
    h += `<div class="row"><div><div class="nm">${esc(r.항목명)}</div>${pills(r)}</div>
      <div class="amt"><span style="color:var(--muted);font-weight:400">금액 없음</span>
        <div><button class="src" onclick="showItemById('${r.id}')">원문보기</button></div></div></div>`;
  }
  document.getElementById("qualitative").innerHTML = h;
}

function toggle(id){
  checked[id] = document.getElementById("cb-"+id).checked;
  propagateHierarchy(id, checked[id]);   // 합계면 구성 전부 따라 on/off(표시). 잠금이 Σ 중복 방지.
  renderAdjust(); renderReferenceUnknown(); renderHeadline();  // 교차구역 반영 위해 구역 C 도 재렌더
}
function onSlider(v){ sliderMin = +v; renderReference(); }

// ---- 원문보기 — 넓은 주석 발췌 + 하이라이트(상·하단 공통) ----
function highlightHTML(excerpt, offsets){
  if(!offsets || !offsets.length) return esc(excerpt);
  const seg = offsets.slice().sort((a,b)=>a[0]-b[0]);
  let h="", cur=0;
  for(const [s,e] of seg){ if(s<cur) continue;
    h += esc(excerpt.slice(cur,s)) + "<mark>" + esc(excerpt.slice(s,e)) + "</mark>"; cur=e; }
  return h + esc(excerpt.slice(cur));
}

// ---- 방식 B: 구조 신호로 줄바꿈 + 하이라이트 주변 행만 먼저(전체 펼치기). 내용 불변(공백만). ----
const AMT_RE = /\(?\d{1,3}(?:,\d{3})+\)?/g;         // 쉼표 있는 금액 = 표의 셀 값
const CTX_ROWS = 2;                                 // 하이라이트 주변 표시 행수(표시 문맥 — 판정 아님)
function splitRows(t){                               // 셀 끝(쉼표숫자+공백)마다 논리 행 경계
  const rows=[]; let last=0, m; AMT_RE.lastIndex=0;
  while((m=AMT_RE.exec(t))){
    const e=m.index+m[0].length;
    if(e<t.length && !/\s/.test(t[e])) continue;     // 숫자에 단위가 붙음(470,869백만원)=셀 끝 아님
    rows.push([last,e]); last=e;
  }
  if(last<t.length) rows.push([last,t.length]);
  return rows.length?rows:[[0,t.length]];
}
function renderExcerpt(excerpt, offsets, expanded){
  const rows = splitRows(excerpt); offsets = offsets||[];
  const hlRows = new Set();                          // 하이라이트가 속한 행
  for(const [s] of offsets) for(let i=0;i<rows.length;i++){ if(rows[i][0]<=s && s<rows[i][1]){ hlRows.add(i); break; } }
  const collapsible = rows.length > (CTX_ROWS*2+3) && hlRows.size>0;
  let visible=null;
  if(collapsible && !expanded){                      // 첫 행(표 머리) + 각 하이라이트 ±CTX
    visible=new Set([0]);
    for(const r of hlRows) for(let i=Math.max(0,r-CTX_ROWS);i<=Math.min(rows.length-1,r+CTX_ROWS);i++) visible.add(i);
  }
  let h="", hidden=0;
  for(let i=0;i<rows.length;i++){
    if(visible && !visible.has(i)){ hidden++; continue; }
    if(hidden>0){ h+=`<div class="gap">⋯ ${hidden}행 생략 — 전체 펼치기로 확인</div>`; hidden=0; }
    const [s,e]=rows[i], local=[];
    for(const [os,oe] of offsets){ const a=Math.max(os,s), b=Math.min(oe,e); if(a<b) local.push([a-s,b-s]); }
    h+=`<div class="exrow${hlRows.has(i)?' hlrow':''}">${highlightHTML(excerpt.slice(s,e), local)}</div>`;
  }
  if(hidden>0) h+=`<div class="gap">⋯ ${hidden}행 생략 — 전체 펼치기로 확인</div>`;
  return {html:h, total:rows.length, collapsible};
}
let _ex=null, _offs=null, _expanded=false;
function paintExcerpt(){
  const r = renderExcerpt(_ex, _offs, _expanded);
  const btn = r.collapsible
    ? `<button class="src exbtn" onclick="toggleExcerpt()">${_expanded?"접기":"전체 주석 펼치기 ("+r.total+"행)"}</button>` : "";
  document.getElementById("exwrap").innerHTML = `<div class="excerpt">${r.html}</div>${btn}`;
}
function toggleExcerpt(){ _expanded=!_expanded; paintExcerpt(); }

// ---- 영업이익 원문보기 — XBRL 손익계산서 계단 재구성(뽑은 줄 하이라이트) ----
function showStatement(){
  const is = DATA.bridge.operating_income.income_statement;
  document.getElementById("m-info").innerHTML = "";
  document.getElementById("m-title").textContent = "영업이익 — 손익계산서 (재구성)";
  document.getElementById("m-loc").textContent =
    `${is.statement_name||"포괄손익계산서"} · ${is.period_year||""} (재무제표 원본, XBRL 구조데이터)`;
  const op = {base:"", less:"(−)", subtotal:"(=)", result:"(=)"};
  let rows="";
  for(const l of is.lines){
    const cls = l.highlight ? "hl" : (l.role==="subtotal"||l.role==="result" ? "sub" : "");
    rows += `<tr${cls?` class="${cls}"`:""}><td class="isop">${op[l.role]||""}</td>`
          + `<td>${esc(l.label)}</td><td class="isval">${fmtM(l.amount_million)}<span class="jo">백만원</span></td></tr>`;
  }
  document.getElementById("m-body").innerHTML =
    `<div class="cap">재무제표 원본(XBRL)에서 재구성한 손익계산서입니다 — `
    + `<b style="background:var(--hl)">노란 줄</b>이 이 화면이 쓴 영업이익입니다.</div>`
    + `<table class="istbl">${rows}</table>`
    + `<div class="cap">매출액 − 매출원가 = 매출총이익, 매출총이익 − 판매비와관리비 = 영업이익. 값은 원본 그대로입니다.</div>`;
  const acc = (DATA.bridge.operating_income.source||{}).account_id;
  document.getElementById("m-meta").textContent = acc ? `개념코드: ${acc}` : "";
  document.getElementById("ov").classList.add("on");
}

function showSrcById(key){ const o=SRC[key]; if(!o) return; const s=o.src;
  openModal(s["항목"]||s["account_nm"]||"원문", s["주석위치"]||s["sj_nm"]||"", s["인용"]||"", s, o.ctx); }
function showItemById(id){ const c=BYID[id]; if(!c) return;
  openModal(c.항목명, c.주석위치||"", c.인용||"",
    {근거강도:c.근거강도, item_type:c.item_type, 표시위치_확정근거:c.표시위치_확정근거,
     표시위치_불안정:c.표시위치_불안정, 표시위치_observed:c.표시위치_observed,
     표시위치_근거_확인:c.표시위치_근거_확인, 표시위치_강등:c.표시위치_강등, 표시위치_llm:c.표시위치_llm},
    c["원문맥락"]); }
function infoBlocks(meta){
  let s="";
  const b = meta && meta.표시위치_확정근거;
  if(b) s += `<div class="cap" style="color:#25603f">✔ 표시위치 확정: 손익계산서 <b>${esc(b.account_nm)}</b> 당기금액과 정확히 일치 → <b>${esc(b.position)}</b>. XBRL 표준 개념코드(<span class="num">${esc(b.concept)}</span>)로 결정론 확정 — 계정명 매칭이 아닙니다.</div>`;
  if(meta && meta.표시위치_근거_확인) s += `<div class="cap" style="color:#25603f">✔ 계상 위치 근거 확인 — LLM 이 제시한 근거 “<b>${esc(meta.표시위치_근거_확인)}</b>” 가 인용에 실제로 있음이 검증됐습니다(헛근거 차단). 이 근거가 있어 상단(조정 가능)으로 남았습니다.</div>`;
  if(meta && meta.표시위치_강등) s += `<div class="caution">근거 게이트 강등 — LLM 은 <b>${esc(meta.표시위치_llm||"상단")}</b> 으로 봤으나, 인용에 계상 위치 근거가 없어 도구가 <b>불명</b> 으로 내렸습니다(근거 없는 상단이 EBITDA 를 움직이는 것을 막음). 원문을 확인하고 영업이익 안에 계상된 것이 맞으면 아래 “조정에 포함(수동)” 스위치로 직접 포함하세요.</div>`;
  if(meta && meta.표시위치_불안정) s += `<div class="caution">⚠ 표시위치 불안정 — 반복 실행에서 <b>${esc((meta.표시위치_observed||[]).join(" / "))}</b> 로 갈렸습니다. 조정 대상에서 제외하고 참고로 돌렸습니다. 원문으로 직접 확인하세요.</div>`;
  if(meta && meta.근거강도==="추정") s += `<div class="cap">근거강도 <b>추정</b> — 금액을 표 구조·문맥에서 유추했습니다. 아래 발췌를 넓혀 유추 근거(표 머리·주변 행)를 함께 보였습니다.</div>`;
  else if(meta && meta.근거강도==="명시") s += `<div class="cap">근거강도 <b>명시</b> — 금액이 인용에 그대로 있어 값이 직접 확인됩니다.</div>`;
  return s;
}
function openModal(title, loc, quote, meta, ctx){
  document.getElementById("m-title").textContent = title||"원문";
  document.getElementById("m-info").innerHTML = infoBlocks(meta);
  const body = document.getElementById("m-body");
  if(ctx && ctx.excerpt){
    document.getElementById("m-loc").textContent = ctx.note_title || loc || "";
    _ex=ctx.excerpt; _offs=ctx.offsets||[]; _expanded=false;
    body.innerHTML =
      `<div class="cap">주석 원문 발췌 — <b style="background:var(--hl)">노란 표시</b>가 이 화면이 뽑은 값입니다`
      + `${ctx.truncated?" (긴 주석이라 뽑은 부분 주변을 발췌).":"."}</div>`
      + `<div id="exwrap"></div>`
      + (quote?`<div class="cap">추출한 인용: “${esc(quote)}”</div>`:"");
    paintExcerpt();
  } else {
    document.getElementById("m-loc").textContent = loc||"";
    // 인용이 없으면 "(인용 없음)"으로 두지 않고 가진 원문 근거(인용/계정 메타)를 보여준다.
    const acc = meta && (meta["account_nm"] || meta["sj_nm"] || meta["account_id"]);
    body.innerHTML = quote
      ? `<div class="excerpt"><div class="exrow">${highlightHTML(quote, [])}</div></div>`
      : (acc ? `<div class="cap">이 값은 재무제표 계정에서 직접 추출됐습니다(주석 서술 없음).</div>`
             : `<div class="excerpt">(원문 근거 없음)</div>`);
  }
  let mh="";
  if(meta && meta["개념코드"]) mh += `개념코드: ${meta["개념코드"]}  `;
  if(meta && meta["account_id"]) mh += `개념코드: ${meta["account_id"]}  `;
  if(meta && meta["기간"]) mh += `기간: ${meta["기간"]}  `;
  if(meta && meta["원문값"]) mh += `원문값: ${meta["원문값"]}  `;
  if(meta && meta.근거강도) mh += `근거강도: ${meta.근거강도}  `;
  document.getElementById("m-meta").textContent = mh;
  document.getElementById("ov").classList.add("on");
}
function closeSrc(){ document.getElementById("ov").classList.remove("on"); }
document.getElementById("ov").addEventListener("click", e=>{ if(e.target.id==="ov") closeSrc(); });
document.addEventListener("keydown", e=>{ if(e.key==="Escape") closeSrc(); });

// ---- init ----
document.getElementById("h-title").textContent = `${DATA.company.corp_name||""} (${DATA.company.stock_code||""}) — 조정 EBITDA 화면 (일회성 제외)`;
document.getElementById("h-sub").textContent = `기준연도 ${DATA.base_year||""} · 원값·출처만, 판정·임계·색 없음 · 판정은 사람이 합니다`;
// 페이지 네비(표시용): 페이지1(이익의 질)로 가는 상대 링크. 재계산·게이트에 영향 없음.
(function(){ var n=document.getElementById("nav1"); if(n) n.setAttribute("href","quality_"+(DATA.company.stock_code||"")+".html"); })();
let ch="";
for(const w of DATA.warnings) ch += `<div class="caution">${esc(w.text)}</div>`;
if(DATA.meta && DATA.meta.surface_is_fixture) ch += `<div class="caution">이 화면의 구역 B/C 후보는 <b>모의(fixture)</b> 입력입니다. 인용은 실제 원문이며, 태그는 시연용입니다.</div>`;
document.getElementById("cautions").innerHTML = ch;
document.getElementById("slider").addEventListener("input", e=>onSlider(e.target.value));
let fh = "출처: " + Object.entries((DATA.meta&&DATA.meta.sources)||{}).filter(kv=>kv[1]).map(kv=>`${kv[0]}=${kv[1].split(/[\\\\/]/).pop()}`).join("  ");
if(DATA.screen_panel && DATA.screen_panel.cumulative_divergence_ratio!=null)
  fh += ` · 다년 괴리(참고): 누적 영업이익 ${fmtM(DATA.screen_panel.cumulative_operating_income/1e6)} vs 영업현금흐름 ${fmtM(DATA.screen_panel.cumulative_operating_cash_flow/1e6)} 백만`;
document.getElementById("foot").textContent = fh;

renderBridge(); renderHeadline(); renderAdjust(); renderReference(); renderReferenceUnknown(); renderQualitative();
</script>
</body>
</html>
"""


def render(view: dict) -> str:
    title = f"{view.get('company',{}).get('corp_name','')} 조정 EBITDA"
    data = json.dumps(view, ensure_ascii=False)
    return PAGE.replace("__TITLE__", title).replace("__DATA__", data)


def render_fragment(view: dict) -> str:
    """claude.ai Artifact 용 본문 프래그먼트: 스켈레톤이 <head>·<body>를 감싸므로 doctype/html/
    head/body 래퍼를 벗기고 <style>+본문+<script>만 남긴다."""
    full = render(view)
    frag = full[full.index("<style>"):full.index("</body>")]
    return frag.replace("</head>\n<body>", "")


def main(argv=None):
    p = argparse.ArgumentParser(description="normalize: screenview JSON → 단일 HTML")
    p.add_argument("view", help="screenview_*.json 경로")
    p.add_argument("--out", help="출력 HTML 경로(생략 시 out/ 동명)")
    p.add_argument("--fragment", action="store_true", help="Artifact용 본문 프래그먼트만 출력")
    args = p.parse_args(argv)

    view = json.loads(Path(args.view).read_text(encoding="utf-8"))
    html = render_fragment(view) if args.fragment else render(view)
    if args.out:
        out_path = Path(args.out)
    else:
        stock = view.get("company", {}).get("stock_code", "view")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = OUT_DIR / f"screen_{stock}_{stamp}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[written] {out_path}")
    return out_path


if __name__ == "__main__":
    main()
