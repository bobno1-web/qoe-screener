"""페이지 1 — 이익의 질. screen(다년 재무제표)+ebitda 산출물 → 단일 HTML(자기완결, 프레임워크 없음).

- 지표는 전부 `src/screen/quality.py` 가 재무제표 숫자로 결정론 계산(LLM·추측 없음).
- **임계·색·등급으로 판정하지 않는다**(no-hardcoding): 숫자와 추이만 보이고 판정은 사람이. 추이
  스파크라인은 단색(판정색 아님) — 모양만 보여줄 뿐 좋고 나쁨을 색으로 딱지 붙이지 않는다.
- 각 지표에 원문보기: 그 숫자가 나온 재무제표 라인을 XBRL 로 재구성한 표에 해당 줄 하이라이트
  (페이지 2 영업이익 원문보기와 같은 방식). 개념코드로 식별·정렬(회계기준 구조, 계정명 매칭 아님).
- 페이지 2(조정 EBITDA)의 로직은 건드리지 않는다 — 이 파일은 별도 렌더러다.

사용:
  python src/normalize/render_quality.py --stock-code 000660
  python src/normalize/render_quality.py --screen out/screen_000660_*.json --ebitda out/ebitda_000660_*.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"

import sys  # noqa: E402
sys.path.insert(0, str(PROJECT_ROOT))
from src.screen import quality as Q  # noqa: E402

# ── 원문보기용 재구성: 표준 개념코드 순서(회계기준 구조 = no-hardcoding 예외, 계정명 매칭 아님) ──
IS_WATERFALL = [
    ("ifrs-full_Revenue", "매출"),
    ("ifrs-full_CostOfSales", "매출원가"),
    ("ifrs-full_GrossProfit", "매출총이익"),
    ("dart_TotalSellingGeneralAdministrativeExpenses", "판매비와관리비"),
    ("dart_OperatingIncomeLoss", "영업이익"),
    ("ifrs-full_ProfitLossFromOperatingActivities", "영업이익"),
]
CF_LINES = [
    ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름"),
    ("ifrs-full_CashFlowsFromUsedInInvestingActivities", "투자활동현금흐름"),
    ("ifrs-full_CashFlowsFromUsedInFinancingActivities", "재무활동현금흐름"),
]
BS_ASSET_LINES = [
    ("ifrs-full_CurrentAssets", "유동자산"),
    ("ifrs-full_CurrentTradeReceivables", "매출채권"),
    ("ifrs-full_TradeAndOtherCurrentReceivables", "매출채권및기타채권"),
    ("ifrs-full_Inventories", "재고자산"),
    ("ifrs-full_NoncurrentAssets", "비유동자산"),
    ("ifrs-full_Assets", "자산총계"),
]
STATEMENT_MAP = {          # line_key → (재구성 순서, sj_div 집합, 표 이름)
    "revenue": (IS_WATERFALL, ("IS", "CIS"), "손익계산서"),
    "cost_of_sales": (IS_WATERFALL, ("IS", "CIS"), "손익계산서"),
    "operating_income": (IS_WATERFALL, ("IS", "CIS"), "손익계산서"),
    "operating_cash_flow": (CF_LINES, ("CF",), "현금흐름표"),
    "total_assets": (BS_ASSET_LINES, ("BS",), "재무상태표(자산)"),
    "trade_receivables": (BS_ASSET_LINES, ("BS",), "재무상태표(자산)"),
    "inventories": (BS_ASSET_LINES, ("BS",), "재무상태표(자산)"),
}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _latest(kind, stock):
    c = sorted(OUT_DIR.glob(f"{kind}_{stock}_*.json"))
    return c[-1] if c else None


def _amount_won(raw_amount):
    a = Q.F.parse_amount(raw_amount)
    return int(a) if a is not None else None


def reconstruct_statement(raw, line_key, highlight_id):
    """raw(fnlttSinglAcntAll) 에서 line_key 의 재무제표를 표준 개념 순서로 재구성. 대상 줄 하이라이트."""
    order, sj_set, name = STATEMENT_MAP[line_key]
    byid = {}
    for r in raw.get("list", []):
        if (r.get("sj_div") or "").strip() in sj_set:
            aid = (r.get("account_id") or "").strip()
            if aid and aid not in byid:
                byid[aid] = r
    lines = []
    seen = set()
    for concept, label in order:
        if concept in seen or concept not in byid:
            continue
        seen.add(concept)
        r = byid[concept]
        won = _amount_won(r.get("thstrm_amount"))
        if won is None:
            continue
        lines.append({
            "concept": concept,
            "label": r.get("account_nm") or label,
            "amount_won": won,
            "amount_million": won / 1_000_000,
            "highlight": concept == highlight_id,
        })
    if not lines:
        return None
    return {"statement_name": name, "lines": lines}


def build_quality_view(screen, ebitda, *, base_raw_path=None):
    """페이지 1 뷰 JSON 조립. 연도별 raw 를 screen provenance 에서 로드 → 지표 + 원문보기 재구성."""
    prov = (screen or {}).get("provenance", {}) or {}
    company = (ebitda or {}).get("company") or (screen or {}).get("company") or {}
    years_data = []
    raw_by_year = {}
    for y in sorted(prov.keys(), key=lambda s: int(s)):
        rp = prov[y].get("raw_path")
        if not rp:
            continue
        p = PROJECT_ROOT / rp
        if not p.exists():
            p = Path(rp)
        if not p.exists():
            continue
        raw = _load(p)
        raw_by_year[int(y)] = raw
        years_data.append({"year": int(y), "items": Q.extract_year(raw)})

    metrics = Q.compute_metrics(years_data, ebitda)

    # 원문보기: 각 라인의 재구성 표(기준연도=가장 최근). 대상 개념은 그 해 실제 검출된 account_id.
    base_year = (ebitda or {}).get("base_year")
    try:
        base_year = int(base_year) if base_year is not None else None
    except (TypeError, ValueError):
        base_year = None
    if base_year not in raw_by_year and years_data:
        base_year = years_data[-1]["year"]
    base_raw = raw_by_year.get(base_year)
    base_items = next((yd["items"] for yd in years_data if yd["year"] == base_year), {})

    sources = {}
    line_used = {}
    if base_raw is not None:
        for key in STATEMENT_MAP:
            det = base_items.get(key) or {}
            hid = det.get("account_id") or ""
            stmt = reconstruct_statement(base_raw, key, hid)
            if stmt:
                stmt["period_year"] = base_year
                sources[key] = stmt
            line_used[key] = {
                "account_id": det.get("account_id"),
                "account_nm": det.get("account_nm"),
                "sj_div": det.get("sj_div"),
                "match": det.get("match"),
                "amount_won": (int(det["amount"]) if isinstance(det.get("amount"), Decimal) else None),
            }

    return {
        "schema_version": "quality-view/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ("이익의 질 — 재무제표 숫자로만 결정론 계산. 임계·색·등급 판정 없음(산업마다 정상 "
                 "범위가 달라 도구가 선을 긋지 않는다). 숫자·추이만 내고 판정은 사람이 한다."),
        "company": company,
        "base_year": base_year,
        "years": metrics["years"],
        "unit_note": "표의 금액 단위: 백만원. 비율·일수는 그대로. 원값(원)은 원문보기에서 확인.",
        "metrics": metrics,
        "sources": sources,          # 원문보기용 재구성 재무제표
        "line_used": line_used,      # 각 지표가 실제로 쓴 라인(개념코드·계정명·표) — 투명성
        "meta": {
            "years_count": len(metrics["years"]),
            "sources_present": sorted(sources.keys()),
            "screen_source": (screen or {}).get("company", {}).get("stock_code")
                             or company.get("stock_code"),
        },
    }


# ─────────────────────────────────────────────────────────────── 렌더 ───────
PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  /* 디자인 시스템(모노톤): 잉크 #1a1a1a · 보조 #5f6764 · 힌트 #9aa19e · 테두리 #e5e7eb · 패널 #f7f8f8 ·
     배경 #fff. 강조색·왼쪽 강조선·그라데이션 없음. 스파크라인은 단색(판정색 아님). 폰트 Pretendard.
     * class/id·HTML·JS 무변경 — 스타일 값만 교체. */
  :root { --ink:#1a1a1a; --muted:#5f6764; --hint:#9aa19e; --line:#e5e7eb; --bg:#ffffff; --card:#fff;
          --panel:#f7f8f8; --accent:#1a1a1a; --pill:#eef0f0; --hl:#fde68a; --spark:#1a1a1a; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.6 "Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;
         color:var(--ink); background:var(--bg); -webkit-font-smoothing:antialiased; }
  .wrap { max-width:980px; margin:0 auto; padding:22px 18px 80px; }
  h1 { font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }
  h2 { font-size:16px; margin:0 0 3px; letter-spacing:-.01em; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:16px; }
  .pagenav { display:flex; gap:8px; margin:0 0 16px; font-size:13px; flex-wrap:wrap; }
  .pagenav a, .pagenav span { border:1px solid var(--line); border-radius:999px; padding:5px 13px;
      text-decoration:none; color:var(--ink); background:var(--card); }
  .pagenav .cur { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
  .note { color:var(--muted); font-size:12.5px; line-height:1.7; margin:-6px 0 18px; }
  .note b { color:var(--ink); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin:0 0 16px;
          box-shadow:0 1px 2px rgba(20,20,20,.04),0 8px 24px -18px rgba(20,20,20,.18); }
  .card .desc { color:var(--muted); font-size:13px; margin:2px 0 12px; }
  .num { font-variant-numeric:tabular-nums; }
  table.q { width:100%; border-collapse:collapse; font-size:13.5px; }
  table.q th, table.q td { padding:7px 8px; border-bottom:1px solid var(--line); text-align:right;
      font-variant-numeric:tabular-nums; white-space:nowrap; }
  table.q th { color:var(--muted); font-weight:600; border-bottom:1px solid var(--line); }
  table.q th:first-child, table.q td:first-child { text-align:left; }
  table.q tr.cum td { font-weight:700; border-top:2px solid var(--ink); }
  table.q td.na { color:var(--hint); }
  .metahd { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .spark { margin:4px 0 2px; }
  .srcrow { margin-top:11px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .srcrow .lbl { font-size:12px; color:var(--muted); }
  .src { background:none; border:1px solid var(--line); color:var(--ink); border-radius:8px;
         font-size:12px; padding:2px 9px; cursor:pointer; }
  .src:hover { background:var(--panel); }
  .empty { color:var(--muted); font-size:13.5px; padding:6px 2px; }
  /* 모달 + 재구성 재무제표 표 */
  .ov { position:fixed; inset:0; background:rgba(26,26,26,.45); display:none; align-items:center;
        justify-content:center; padding:20px; z-index:10; }
  .ov.on { display:flex; }
  .modal { background:#fff; border:1px solid var(--line); border-radius:14px; max-width:640px; width:100%; padding:20px; max-height:84vh; overflow:auto;
           box-shadow:0 10px 40px -12px rgba(20,20,20,.3); }
  .modal h3 { margin:0 0 4px; font-size:16px; padding-right:24px; }
  .modal .loc { color:var(--muted); font-size:13px; margin-bottom:10px; }
  .modal .x { float:right; border:none; background:none; font-size:22px; cursor:pointer; color:var(--muted); line-height:1; }
  .istbl { width:100%; border-collapse:collapse; font-size:14px; margin:8px 0 4px; }
  .istbl td { padding:7px 6px; border-bottom:1px solid var(--line); }
  .istbl .isval { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .istbl .isval .jo { color:var(--muted); font-weight:400; font-size:12px; margin-left:3px; }
  .istbl tr.hl td { background:var(--hl); font-weight:700; }
  .modal .meta { color:var(--muted); font-size:12px; margin-top:10px; }
  footer { color:var(--muted); font-size:12px; margin-top:26px; }
</style></head><body><div class="wrap">
  <h1 id="h-title"></h1>
  <div class="sub" id="h-sub"></div>
  <div class="pagenav">
    <span class="cur">① 이익의 질</span>
    <a id="nav2" href="#">② 조정 EBITDA — 일회성 걷어내기 →</a>
  </div>
  <div class="note"><b>읽는 법.</b> 이 페이지는 재무제표 숫자로 "이 회사가 보고한 영업이익을 믿을 수 있나"를
    본다. <b>임계·색·등급으로 판정하지 않는다</b> — 산업마다 정상 범위가 다르기 때문이다(제조는 재고가 크고
    서비스는 없다). 숫자와 추이만 정직하게 내고, 판정은 감사인이 한다. 동종업계 비교는 하지 않고 한 회사의
    자기 추이만 본다. 모든 숫자에 <b>원문보기</b>(재무제표 라인)를 달았다.</div>
  <div id="cards"></div>
  <footer id="foot"></footer>
</div>
<div class="ov" id="ov"><div class="modal">
  <button class="x" onclick="closeSrc()">×</button>
  <h3 id="m-title"></h3>
  <div class="loc" id="m-loc"></div>
  <div id="m-body"></div>
  <div class="meta" id="m-meta"></div>
</div></div>
<script>const DATA = __DATA__;</script>
<script>__JS__</script>
</body></html>"""

JS = r"""
var Y = DATA.years || [];
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
function fmtM(won){ // 원 → 백만원, 콤마. null 은 '—'
  if(won==null) return '<span class="na">—</span>';
  var m = Math.round(won/1e6);
  return (m<0?'('+Math.abs(m).toLocaleString()+')':m.toLocaleString());
}
function fmtRatio(r,dp){ if(r==null) return '<span class="na">—</span>'; return r.toFixed(dp==null?3:dp); }
function fmtPct(r){ if(r==null) return '<span class="na">—</span>'; return (r*100).toFixed(2)+'%'; }
function fmtDays(d){ if(d==null) return '<span class="na">—</span>'; return d.toFixed(1)+'일'; }

// 단색 스파크라인(판정색 아님 — 추이 모양만). 값 배열에서 SVG polyline.
function spark(vals, w, h){
  w=w||220; h=h||34; var pad=3;
  var xs=[], present=vals.map(function(v){return v==null?null:v;});
  var nums=present.filter(function(v){return v!=null;});
  if(nums.length<2) return '';
  var mn=Math.min.apply(null,nums), mx=Math.max.apply(null,nums);
  var rng=(mx-mn)||1, n=vals.length;
  var pts=[];
  for(var i=0;i<n;i++){ if(present[i]==null) continue;
    var x=pad+(n===1?0:(w-2*pad)*i/(n-1));
    var y=h-pad-(h-2*pad)*(present[i]-mn)/rng;
    pts.push(x.toFixed(1)+','+y.toFixed(1));
  }
  // 0 기준선(값에 음수·양수가 섞이면 표시 — 판정색 아닌 옅은 회선)
  var zero='';
  if(mn<0 && mx>0){ var zy=h-pad-(h-2*pad)*(0-mn)/rng; zero='<line x1="'+pad+'" y1="'+zy.toFixed(1)+'" x2="'+(w-pad)+'" y2="'+zy.toFixed(1)+'" stroke="#c9d2db" stroke-width="1" stroke-dasharray="3 3"/>'; }
  return '<svg class="spark" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'">'+zero+
    '<polyline fill="none" stroke="var(--spark)" stroke-width="1.6" points="'+pts.join(' ')+'"/></svg>';
}

function srcBtn(key,label){ if(!DATA.sources[key]) return '';
  return '<button class="src" onclick="openSrc(\''+key+'\')">원문보기 · '+esc(label)+'</button>'; }

function yearCols(){ return Y.map(function(y){return '<th>'+y+'</th>';}).join(''); }
function rowByYear(vals, fmt){ return Y.map(function(y,i){
  var v=vals[i]; var isna=(v==null||(v.na===true));
  return '<td'+(isna?' class="na"':'')+'>'+fmt(v)+'</td>'; }).join(''); }

function card(title, desc, inner){
  return '<div class="card"><div class="metahd"><h2>'+esc(title)+'</h2></div>'+
    '<div class="desc">'+desc+'</div>'+inner+'</div>';
}

function build(){
  document.getElementById('h-title').textContent = (DATA.company.corp_name||'')+' — 이익의 질';
  document.getElementById('h-sub').textContent = '재무제표 기준 · '+(Y.length?(Y[0]+'~'+Y[Y.length-1]):'')+' · 페이지 1 / 2';
  var s=DATA.company.stock_code||'';
  document.getElementById('nav2').setAttribute('href','screen_'+s+'.html');
  var C=[];
  var M=DATA.metrics;

  // 1) 영업이익 vs 영업현금흐름
  (function(){ var p=M.oi_vs_ocf.per_year, cu=M.oi_vs_ocf.cumulative;
    var t='<table class="q"><tr><th>연도(백만원)</th>'+yearCols()+'<th>누적</th></tr>';
    t+='<tr><td>영업이익</td>'+p.map(function(r){return '<td>'+fmtM(r.operating_income)+'</td>';}).join('')+'<td>'+fmtM(cu.operating_income)+'</td></tr>';
    t+='<tr><td>영업현금흐름</td>'+p.map(function(r){return '<td>'+fmtM(r.operating_cash_flow)+'</td>';}).join('')+'<td>'+fmtM(cu.operating_cash_flow)+'</td></tr>';
    t+='<tr class="cum"><td>발생액 (영업이익 − 영업현금흐름)</td>'+p.map(function(r){return '<td>'+fmtM(r.accrual)+'</td>';}).join('')+'<td>'+fmtM(cu.accrual)+'</td></tr>';
    t+='</table>';
    t+=spark(p.map(function(r){return r.accrual==null?null:r.accrual/1e6;}));
    t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('operating_income','영업이익')+srcBtn('operating_cash_flow','영업현금흐름')+'</div>';
    C.push(card('1. 영업이익 vs 영업현금흐름 (핵심)',
      '이익이 현금으로 뒷받침되는지. 발생액 = 영업이익 − 영업현금흐름. 발생액이 계속 크게 (+)면 이익이 현금보다 앞서 잡힌 것 — 왜인지는 원문·주석으로 확인. 판정은 하지 않는다.', t)); })();

  // 2) 발생액 비율
  (function(){ var p=M.accrual_ratio.per_year;
    var t='<table class="q"><tr><th>연도</th>'+yearCols()+'</tr>';
    t+='<tr><td>발생액 ÷ 총자산</td>'+rowByYear(p,function(r){return fmtPct(r.over_assets);})+'</tr>';
    t+='<tr><td>발생액 ÷ 매출</td>'+rowByYear(p,function(r){return fmtPct(r.over_revenue);})+'</tr>';
    t+='</table>';
    t+=spark(p.map(function(r){return r.over_assets==null?null:r.over_assets;}));
    t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('total_assets','자산총계')+srcBtn('revenue','매출')+'</div>';
    C.push(card('2. 발생액 비율',
      '발생액을 규모(총자산·매출)로 나눠 회사 크기와 무관하게 본다. 절대액이 커도 규모 대비 작을 수 있다.', t)); })();

  // 3) 매출채권 회전
  (function(){ var p=M.receivables_turnover.per_year;
    var t='<table class="q"><tr><th>연도(백만원)</th>'+yearCols()+'</tr>';
    t+='<tr><td>매출채권</td>'+p.map(function(r){return '<td>'+fmtM(r.trade_receivables)+'</td>';}).join('')+'</tr>';
    t+='<tr><td>매출</td>'+p.map(function(r){return '<td>'+fmtM(r.revenue)+'</td>';}).join('')+'</tr>';
    t+='<tr><td>매출채권 ÷ 매출</td>'+rowByYear(p,function(r){return fmtRatio(r.over_revenue);})+'</tr>';
    t+='<tr class="cum"><td>회수기간(일)</td>'+rowByYear(p,function(r){return fmtDays(r.days);})+'</tr>';
    t+='</table>';
    t+=spark(p.map(function(r){return r.days==null?null:r.days;}));
    t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('trade_receivables','매출채권')+srcBtn('revenue','매출')+'</div>';
    C.push(card('3. 매출채권 회전',
      '매출보다 채권이 빨리 늘면(회수기간이 길어지면) 아직 안 받은 돈으로 매출을 인식했을 가능성. 산업별 정상 범위가 다르니 추이로 본다.', t)); })();

  // 4) 재고 회전
  (function(){ var p=M.inventory_turnover.per_year;
    var t='<table class="q"><tr><th>연도(백만원)</th>'+yearCols()+'</tr>';
    t+='<tr><td>재고자산</td>'+p.map(function(r){return '<td>'+fmtM(r.inventories)+'</td>';}).join('')+'</tr>';
    t+='<tr><td>매출원가</td>'+p.map(function(r){return '<td>'+fmtM(r.cost_of_sales)+'</td>';}).join('')+'</tr>';
    t+='<tr><td>재고 ÷ 매출원가</td>'+rowByYear(p,function(r){return fmtRatio(r.over_cogs);})+'</tr>';
    t+='<tr class="cum"><td>재고일수(일)</td>'+rowByYear(p,function(r){return fmtDays(r.days);})+'</tr>';
    t+='</table>';
    t+=spark(p.map(function(r){return r.days==null?null:r.days;}));
    t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('inventories','재고자산')+srcBtn('cost_of_sales','매출원가')+'</div>';
    C.push(card('4. 재고 회전',
      '재고가 매출원가보다 빨리 쌓이면(재고일수가 늘면) 나중에 평가손실로 터질 수 있다. 재고가 없는 회사는 해당 없음.', t)); })();

  // 5) EBITDA vs 영업현금흐름
  (function(){ var e=M.ebitda_vs_ocf; var t;
    if(!e.available){ t='<div class="empty">'+esc(e.na_reason||'EBITDA 산출물 없음')+'</div>'; }
    else{
      t='<table class="q"><tr><th>'+e.base_year+'년(백만원)</th><th>금액</th></tr>';
      t+='<tr><td>EBITDA (영업이익 + 가산 D&amp;A)</td><td>'+fmtM(e.ebitda)+'</td></tr>';
      t+='<tr><td>영업현금흐름</td><td>'+fmtM(e.operating_cash_flow)+'</td></tr>';
      t+='<tr class="cum"><td>차이 (EBITDA − 영업현금흐름)</td><td>'+fmtM(e.difference)+'</td></tr>';
      t+='</table>';
      t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('operating_cash_flow','영업현금흐름')+
         '<span class="lbl">· EBITDA 구성은 페이지 2 브릿지에서</span></div>';
    }
    C.push(card('5. EBITDA vs 영업현금흐름',
      'EBITDA(우리가 계산한 것)와 실제 영업현금흐름의 차이. 차이가 크면 운전자본(재고·채권 증가 등)이 이익을 현금에서 갉아먹고 있는 것. D&amp;A 는 기준연도만 뽑으므로 기준연도 1개를 비교한다.', t)); })();

  // 6) 영업이익률
  (function(){ var p=M.operating_margin.per_year;
    var t='<table class="q"><tr><th>연도(백만원)</th>'+yearCols()+'</tr>';
    t+='<tr><td>영업이익</td>'+p.map(function(r){return '<td>'+fmtM(r.operating_income)+'</td>';}).join('')+'</tr>';
    t+='<tr><td>매출</td>'+p.map(function(r){return '<td>'+fmtM(r.revenue)+'</td>';}).join('')+'</tr>';
    t+='<tr class="cum"><td>영업이익률</td>'+rowByYear(p,function(r){return fmtPct(r.margin);})+'</tr>';
    t+='</table>';
    t+=spark(p.map(function(r){return r.margin==null?null:r.margin;}));
    t+='<div class="srcrow"><span class="lbl">원문:</span>'+srcBtn('operating_income','영업이익')+srcBtn('revenue','매출')+'</div>';
    C.push(card('6. 영업이익률 추이',
      '영업이익 ÷ 매출. 갑자기 좋아졌거나 나빠졌으면 왜인지 확인 대상 — 일회성인지(페이지 2)·추정 변화인지.', t)); })();

  document.getElementById('cards').innerHTML = C.join('');
  var lu = DATA.line_used||{};
  var used = Object.keys(lu).filter(function(k){return lu[k] && lu[k].account_id;}).length;
  document.getElementById('foot').innerHTML =
    '결정론 계산(LLM 없음) · 개념코드 기반 추출 · 기준연도 '+esc(DATA.base_year)+' · 라인 '+used+'개 확인 · '+
    '생성 '+esc((DATA.generated_at||'').slice(0,10))+'. 임계·색·등급 판정 없음 — 판정은 사람이.';
}

// ── 원문보기 모달: 재구성 재무제표 표에 해당 줄 하이라이트 ──
function openSrc(key){
  var st=DATA.sources[key]; if(!st) return;
  var lu=(DATA.line_used||{})[key]||{};
  document.getElementById('m-title').textContent = st.statement_name+' — 원문 재구성';
  document.getElementById('m-loc').textContent =
    (st.period_year? st.period_year+'년 · ':'')+'XBRL 재무제표에서 표준 개념코드로 재구성(계정명 매칭 아님). 노란 줄이 지표에 쓴 값.';
  var h='<table class="istbl">';
  st.lines.forEach(function(ln){
    h+='<tr'+(ln.highlight?' class="hl"':'')+'><td>'+esc(ln.label)+'</td>'+
       '<td class="isval">'+ln.amount_won.toLocaleString()+'<span class="jo"> ('+Math.round(ln.amount_million).toLocaleString()+' 백만)</span></td></tr>';
  });
  h+='</table>';
  document.getElementById('m-body').innerHTML=h;
  document.getElementById('m-meta').innerHTML = lu.account_id?
    ('쓴 라인: <b>'+esc(lu.account_nm||'')+'</b> · 개념코드 '+esc(lu.account_id)+' · 표 '+esc(lu.sj_div||'')+
     ' · 매칭 '+esc(lu.match||'')) : '';
  document.getElementById('ov').classList.add('on');
}
function closeSrc(){ document.getElementById('ov').classList.remove('on'); }
document.addEventListener('keydown',function(e){ if(e.key==='Escape') closeSrc(); });
document.getElementById('ov').addEventListener('click',function(e){ if(e.target===this) closeSrc(); });
build();
"""


def render(view: dict) -> str:
    title = f"{view.get('company',{}).get('corp_name','')} 이익의 질"
    data = json.dumps(view, ensure_ascii=False)
    return (PAGE.replace("__TITLE__", title)
            .replace("__DATA__", data)
            .replace("__JS__", JS))


def main(argv=None):
    p = argparse.ArgumentParser(description="normalize 페이지1: screen·ebitda → 이익의 질 HTML")
    p.add_argument("--stock-code")
    p.add_argument("--screen", help="screen JSON(생략 시 out/ 최신)")
    p.add_argument("--ebitda", help="ebitda JSON(생략 시 out/ 최신)")
    p.add_argument("--out", help="출력 HTML(생략 시 out/quality_<stock>.html)")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    stock = (args.stock_code or "").strip()
    screen_p = Path(args.screen) if args.screen else (_latest("screen", stock) if stock else None)
    ebitda_p = Path(args.ebitda) if args.ebitda else (_latest("ebitda", stock) if stock else None)
    if not screen_p or not Path(screen_p).exists():
        raise SystemExit(f"screen_{stock}_*.json 를 찾을 수 없습니다(다년 재무제표 필수). (STOP)")
    screen = _load(screen_p)
    ebitda = _load(ebitda_p) if ebitda_p and Path(ebitda_p).exists() else None
    if not stock:
        stock = (screen.get("company", {}) or {}).get("stock_code") or "unknown"

    view = build_quality_view(screen, ebitda)
    html = render(view)
    out_path = Path(args.out) if args.out else OUT_DIR / f"quality_{stock}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    m = view["meta"]
    print(f"[written] {out_path}")
    print(f"  연도 {view['years']}  라인원문 {len(m['sources_present'])}개  기준연도 {view['base_year']}")
    return out_path


if __name__ == "__main__":
    main()
