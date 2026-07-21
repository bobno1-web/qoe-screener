"""로컬 Flask 웹앱 (127.0.0.1:5000). 회사명 입력 → 기존 파이프라인 실행 → EBITDA 조정 화면.

- 호스팅하지 않는다. 로컬 전용 — 실사 데이터가 PC 를 떠나지 않는 게 이 도구의 전제.
- API 키(OPENDART·ANTHROPIC)는 화면에서 입력받아 이 프로세스 메모리에만 둔다. 파일·로그·
  산출물에 저장하지 않고, 서버를 끄면 사라진다. 서브프로세스에는 env 로만 전달한다.
- surface 는 3회 반복 고정 — 사용자 선택 옵션 없음(회차 비교가 방어의 전제).

실행: python -m src.web.app   (보통은 start_qoe.bat / start_qoe.sh 가 대신 부른다)
"""
from __future__ import annotations

import re
import sys
import threading
import time
import uuid
import webbrowser
from html import escape
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.web import pipeline  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"

app = Flask(__name__)

# ── 메모리 전용 상태 (디스크 저장 금지) ─────────────────────────────
# 서버 프로세스가 살아있는 동안만 존재. 종료 시 소멸. 어떤 파일에도 안 쓴다.
_KEYS: dict = {}            # {"opendart":..., "anthropic":...}
_JOBS: dict = {}           # {job_id: job dict}
_LOCK = threading.Lock()

ISSUER_DART = "https://opendart.fss.or.kr/"
ISSUER_ANTHROPIC = "https://console.anthropic.com/"

EXAMPLES = [
    ("SK하이닉스", "000660"),
    ("대한항공", "003490"),
    ("롯데케미칼", "011170"),
    ("삼성전자", "005930"),
]


# ── 디자인 시스템(모노톤) — 공용 상수 ────────────────────────────────
# 랜딩·키입력·진행·회사입력이 공유하는 브랜드 요소. 결과 페이지(render*.py)는 별도로 자기 디자인 유지.
REPO_URL = "https://github.com/bobno1-web/qoe-screener"

# 돋보기 심볼(렌즈 원 + 가운데 채운 점 + 손잡이) — 블랙 단색. 브랜드바 인라인 SVG.
BRAND_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="#1a1a1a" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="10.5" cy="10.5" r="6"></circle>'
    '<line x1="15.4" y1="15.4" x2="20" y2="20"></line>'
    '<circle cx="10.5" cy="10.5" r="1.7" fill="#1a1a1a" stroke="none"></circle>'
    "</svg>"
)
# 같은 돋보기 심볼(흰 둥근 타일 + 블랙 글래스) — favicon data URI SVG.
FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
    "<rect width='24' height='24' rx='6' fill='%23ffffff'/>"
    "<g fill='none' stroke='%231a1a1a' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<circle cx='10.5' cy='10.5' r='6'/><line x1='15.4' y1='15.4' x2='20' y2='20'/></g>"
    "<circle cx='10.5' cy='10.5' r='1.7' fill='%231a1a1a'/></svg>"
)


# ── 공용 셸(디자인) ────────────────────────────────────────────────
# 모노톤: 잉크 #1a1a1a · 보조 #5f6764 · 힌트 #9aa19e · 테두리 #e5e7eb · 패널 #f7f8f8 · 배경 #fff.
# 강조색 없음(버튼은 블랙). 왼쪽 강조선·그라데이션 금지. 음수 금액만 #b4462b. 폰트 Pretendard.
_SHELL = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · QoE Screener</title>
<link rel="icon" href="{favicon}">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  :root{{
    --ink:#1a1a1a; --ink-soft:#5f6764; --line:#e5e7eb; --line-2:#f0f1f1;
    --bg:#ffffff; --card:#ffffff; --panel:#f7f8f8; --accent:#1a1a1a; --accent-soft:#f2f3f3;
    --good:#1a1a1a; --warn:#9aa19e; --bad:#b4462b; --mute:#9aa19e;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font-family:"Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",system-ui,sans-serif;
    line-height:1.6;-webkit-font-smoothing:antialiased}}
  /* 상단 브랜드바 — 전 진입 화면 공유(돋보기 로고 + 브랜드명) */
  .topbar{{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;
    padding:12px 20px;background:rgba(255,255,255,.9);backdrop-filter:saturate(1.2) blur(8px);
    border-bottom:1px solid var(--line)}}
  .brand{{display:inline-flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}}
  .brand-mark{{width:30px;height:30px;border-radius:9px;background:#fff;border:1px solid var(--line);
    display:grid;place-items:center;box-shadow:0 1px 2px rgba(20,20,20,.05)}}
  .brand-mark svg{{width:18px;height:18px;display:block}}
  .brand-name{{font-size:16px;font-weight:700;letter-spacing:-.01em}}
  .brand-tag{{margin-left:auto;font-size:12.5px;color:var(--mute)}}
  .wrap{{max-width:660px;margin:0 auto;padding:36px 20px 72px}}
  h1{{font-size:22px;letter-spacing:-.01em;margin:6px 0 6px;text-wrap:balance}}
  p.sub{{color:var(--ink-soft);margin:0 0 22px;font-size:14.5px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:24px;box-shadow:0 1px 2px rgba(20,20,20,.04),0 8px 24px -18px rgba(20,20,20,.18)}}
  .card + .card{{margin-top:16px}}
  label{{display:block;font-weight:600;font-size:13.5px;margin:16px 0 6px}}
  label:first-child{{margin-top:0}}
  .hint{{font-size:12.5px;color:var(--mute);font-weight:400;margin-left:6px}}
  input[type=text],input[type=password]{{width:100%;padding:11px 13px;font-size:14.5px;
    border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);
    font-family:inherit}}
  input:focus{{outline:none;border-color:var(--ink);box-shadow:0 0 0 3px var(--accent-soft)}}
  button,.btn{{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:0;
    border-radius:10px;background:var(--accent);color:#fff;font-size:14.5px;font-weight:600;
    padding:11px 20px;cursor:pointer;font-family:inherit;text-decoration:none;margin-top:20px}}
  button:hover,.btn:hover{{background:#000}}
  .btn.ghost{{background:transparent;color:var(--ink);padding:6px 0;margin-top:0;
    font-size:13px}}
  a{{color:var(--ink)}}
  .row{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
  .chip{{border:1px solid var(--line);background:#fff;border-radius:999px;
    padding:6px 13px;font-size:13px;color:var(--ink-soft);cursor:pointer;
    font-family:inherit}}
  .chip:hover{{border-color:var(--ink);color:var(--ink)}}
  .chip b{{font-family:"Consolas",ui-monospace,monospace;color:var(--ink)}}
  .keystate{{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-soft);
    background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 13px;margin-bottom:4px}}
  .dot{{width:8px;height:8px;border-radius:50%;background:var(--good);flex:none}}
  .err{{background:#fbf1ee;border:1px solid #eccdc5;color:var(--bad);border-radius:10px;
    padding:12px 14px;font-size:13.5px;margin-bottom:16px}}
  .note{{font-size:12.5px;color:var(--mute);margin-top:14px}}
  ol.steps{{list-style:none;padding:0;margin:8px 0 0;counter-reset:s}}
  ol.steps li{{display:flex;align-items:center;gap:12px;padding:13px 4px;
    border-top:1px solid var(--line-2)}}
  ol.steps li:first-child{{border-top:0}}
  .mark{{width:26px;height:26px;border-radius:50%;flex:none;display:grid;place-items:center;
    font-size:13px;font-weight:700;background:var(--line-2);color:var(--mute)}}
  li.running .mark{{background:var(--ink);color:#fff;
    animation:pulse 1.3s ease-in-out infinite}}
  li.done .mark{{background:var(--ink);color:#fff}}
  li.error .mark{{background:var(--bad);color:#fff}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
  .stepmain{{flex:1;min-width:0}}
  .steplabel{{font-size:14px;font-weight:600}}
  li.pending .steplabel{{color:var(--mute);font-weight:500}}
  .stepmeta{{font-size:12px;color:var(--mute);font-variant-numeric:tabular-nums}}
  @media (prefers-reduced-motion:reduce){{li.running .mark{{animation:none}}}}
</style></head><body>
  <header class="topbar">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true">{brand}</span>
      <span class="brand-name">QoE Screener</span>
    </a>
    <span class="brand-tag">영업이익 질 스크리닝 · 로컬</span>
  </header>
  <div class="wrap">
  {body}
  </div>
{script}</body></html>"""


def page(title, body, script=""):
    return _SHELL.format(title=escape(title), body=body, script=script,
                         favicon=FAVICON, brand=BRAND_SVG)


# ── 랜딩(진입 라우트) ──────────────────────────────────────────────
# 확정된 모노톤 디자인. "시작하기"는 기존 진입 흐름(/start → 키 없으면 키입력)으로 잇는다.
# 히어로 카드 안의 숫자는 데모 예시(정적) — 실제 계산과 무관한 시각 요소.
_LANDING = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QoE Screener · 영업이익의 질 스크리닝</title>
<link rel="icon" href="__FAVICON__">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  :root{
    --ink:#1a1a1a; --ink-soft:#5f6764; --mute:#9aa19e;
    --line:#e5e7eb; --panel:#f7f8f8; --bg:#ffffff; --neg:#b4462b;
    --shadow:0 1px 2px rgba(20,20,20,.04),0 10px 30px -20px rgba(20,20,20,.22);
    --shadow-lg:0 1px 2px rgba(20,20,20,.05),0 20px 46px -24px rgba(20,20,20,.26);
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:"Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",system-ui,sans-serif;
    background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;line-height:1.6}
  a{color:inherit;text-decoration:none}
  .wrap{max-width:1080px;margin:0 auto;padding:0 24px}

  /* 상단 브랜드바 */
  nav{display:flex;align-items:center;justify-content:space-between;height:66px;
    border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;
    background:rgba(255,255,255,.9);backdrop-filter:saturate(1.2) blur(8px)}
  .logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;letter-spacing:-.01em}
  .logo-mark{width:30px;height:30px;border-radius:9px;background:#fff;border:1px solid var(--line);
    display:grid;place-items:center;box-shadow:0 1px 2px rgba(20,20,20,.05)}
  .logo-mark svg{width:18px;height:18px;display:block}
  .nav-links{display:flex;align-items:center;gap:26px}
  .nav-links a{color:var(--ink-soft);font-size:14.5px;font-weight:500}
  .nav-links a:hover{color:var(--ink)}
  .nav-cta{background:var(--ink);color:#fff !important;padding:9px 17px;border-radius:9px;font-size:14px;font-weight:600}
  .nav-cta:hover{background:#000}

  /* 히어로 */
  .hero{padding:82px 0 60px;text-align:center}
  .eyebrow{display:inline-block;background:#fff;border:1px solid var(--line);color:var(--ink-soft);
    font-size:12.5px;font-weight:600;padding:6px 14px;border-radius:999px;margin-bottom:24px;box-shadow:var(--shadow)}
  h1{font-size:clamp(2rem,5vw,3.35rem);font-weight:800;letter-spacing:-.035em;line-height:1.18;margin-bottom:20px}
  .sub{font-size:clamp(1rem,2.2vw,1.18rem);color:var(--ink-soft);max-width:600px;margin:0 auto 34px;line-height:1.7}
  .hero-btns{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
  .btn{padding:13px 26px;border-radius:11px;font-size:15.5px;font-weight:600;
    display:inline-flex;align-items:center;gap:8px;transition:background .15s,transform .06s,box-shadow .15s;letter-spacing:-.01em}
  .btn-primary{background:var(--ink);color:#fff;box-shadow:var(--shadow)}
  .btn-primary:hover{background:#000;transform:translateY(-1px);box-shadow:var(--shadow-lg)}
  .btn-ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
  .btn-ghost:hover{background:var(--panel)}

  /* 히어로 미니 UI(데모 — 정적) */
  .hero-visual{max-width:900px;margin:56px auto 0;border-radius:16px;border:1px solid var(--line);
    box-shadow:var(--shadow-lg);overflow:hidden;background:#fff}
  .hv-bar{height:38px;background:var(--panel);border-bottom:1px solid var(--line);
    display:flex;align-items:center;gap:7px;padding:0 15px}
  .hv-dot{width:10px;height:10px;border-radius:50%;background:#dfe3e3}
  .hv-tag{margin-left:auto;font-size:11.5px;color:var(--mute)}
  .hv-body{padding:28px 30px;display:grid;grid-template-columns:1.05fr 1fr;gap:20px;text-align:left}
  .hv-card{border:1px solid var(--line);border-radius:12px;padding:18px 20px;background:#fff}
  .hv-label{font-size:12px;color:var(--mute);font-weight:600;margin-bottom:12px}
  .hv-big{font-size:29px;font-weight:800;letter-spacing:-.03em;font-variant-numeric:tabular-nums}
  .hv-big small{font-size:13px;color:var(--mute);font-weight:600;margin-left:6px}
  .spark{height:42px;display:flex;align-items:flex-end;gap:5px;margin:12px 0 4px}
  .spark i{flex:1;background:var(--ink);border-radius:3px 3px 0 0;opacity:.16}
  .spark i.on{opacity:.82}
  .hv-row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;
    border-top:1px solid var(--panel);font-size:13px}
  .hv-row:first-of-type{border-top:none}
  .hv-row .v{font-weight:700;font-variant-numeric:tabular-nums}
  .hv-row .neg{color:var(--neg)}
  .pill{font-size:11px;padding:3px 9px;border-radius:999px;font-weight:600;
    background:var(--panel);color:var(--ink-soft);border:1px solid var(--line)}

  /* 섹션 공통 */
  .section{padding:78px 0}
  .sec-head{text-align:center;max-width:600px;margin:0 auto 46px}
  .sec-head h2{font-size:clamp(1.6rem,3.5vw,2.2rem);font-weight:800;letter-spacing:-.03em;margin-bottom:12px}
  .sec-head p{font-size:16px;color:var(--ink-soft)}

  /* 기능 카드 3 */
  .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
  .card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:30px 26px;
    box-shadow:var(--shadow);transition:transform .18s,box-shadow .18s}
  .card:hover{transform:translateY(-3px);box-shadow:var(--shadow-lg)}
  .card-ico{width:46px;height:46px;border-radius:12px;background:var(--panel);border:1px solid var(--line);
    display:grid;place-items:center;margin-bottom:18px}
  .card-ico svg{width:22px;height:22px;stroke:var(--ink);fill:none;stroke-width:1.7}
  .card h3{font-size:18.5px;font-weight:700;letter-spacing:-.02em;margin-bottom:10px}
  .card p{font-size:14.5px;color:var(--ink-soft);line-height:1.72}

  /* 작동 방식 3단계 */
  .steps-sec{background:var(--panel);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  .steps{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
  .step{padding-top:6px}
  .step-n{font-size:13.5px;font-weight:700;color:var(--ink-soft);margin-bottom:13px;
    display:flex;align-items:center;gap:9px}
  .step-n b{width:29px;height:29px;border-radius:9px;background:#fff;border:1px solid var(--line);
    display:grid;place-items:center;font-size:13.5px;color:var(--ink)}
  .step h4{font-size:17px;font-weight:700;letter-spacing:-.02em;margin-bottom:8px}
  .step p{font-size:14.5px;color:var(--ink-soft);line-height:1.7}

  /* CTA */
  .cta-sec{text-align:center;padding:84px 0}
  .cta-sec h2{font-size:clamp(1.7rem,3.6vw,2.3rem);font-weight:800;letter-spacing:-.03em;margin-bottom:14px}
  .cta-sec p{font-size:16px;color:var(--ink-soft);margin-bottom:30px}

  /* 푸터 */
  footer{border-top:1px solid var(--line);padding:34px 0;display:flex;
    align-items:center;justify-content:space-between;font-size:13.5px;color:var(--mute);gap:16px;flex-wrap:wrap}
  footer .f-links a{color:var(--ink-soft);margin-left:20px}
  footer .f-links a:hover{color:var(--ink)}

  @media(max-width:820px){
    .cards,.steps,.hv-body{grid-template-columns:1fr}
    .nav-links a:not(.nav-cta){display:none}
    .hero{padding:58px 0 44px}
    footer{justify-content:center;text-align:center}
    footer .f-links a{margin:0 10px}
  }
</style>
</head>
<body>

<nav class="wrap">
  <a class="logo" href="/">
    <span class="logo-mark" aria-hidden="true">__BRAND__</span>QoE Screener
  </a>
  <div class="nav-links">
    <a href="#features">기능</a>
    <a href="#how">작동 방식</a>
    <a href="__REPO__" target="_blank" rel="noopener">GitHub</a>
    <a href="/start" class="nav-cta">시작하기</a>
  </div>
</nav>

<header class="hero wrap">
  <span class="eyebrow">M&amp;A 실사용 · 로컬 실행</span>
  <h1>회사명 하나로<br>영업이익의 질을 읽습니다</h1>
  <p class="sub">재무제표에서 이익의 질을 진단하고, 주석에 파묻힌 일회성 항목을
    원문 근거와 함께 찾아 조정 EBITDA 후보를 제시합니다. 판정은 사람이 합니다.</p>
  <div class="hero-btns">
    <a href="/start" class="btn btn-primary">시작하기</a>
    <a href="__REPO__" target="_blank" rel="noopener" class="btn btn-ghost">GitHub에서 보기</a>
  </div>

  <div class="hero-visual" aria-hidden="true">
    <div class="hv-bar">
      <i class="hv-dot"></i><i class="hv-dot"></i><i class="hv-dot"></i>
      <span class="hv-tag">예시 화면 · 데모</span>
    </div>
    <div class="hv-body">
      <div class="hv-card">
        <div class="hv-label">조정 후 EBITDA</div>
        <div class="hv-big">60,434,225<small>백만원</small></div>
        <div class="spark">
          <i style="height:52%"></i><i style="height:38%"></i><i style="height:22%"></i>
          <i style="height:70%"></i><i class="on" style="height:100%"></i>
        </div>
        <div class="hv-row"><span>재고평가손실환입</span><span class="v neg">−661,733</span></div>
        <div class="hv-row"><span>base EBITDA</span><span class="v">61,095,958</span></div>
      </div>
      <div class="hv-card">
        <div class="hv-label">이익의 질</div>
        <div class="hv-row"><span>영업이익 vs 영업현금흐름</span><span class="pill">현금 1.49×</span></div>
        <div class="hv-row"><span>발생액</span><span class="v">−6.2조</span></div>
        <div class="hv-row"><span>매출채권 회수기간</span><span class="v">68.4일</span></div>
        <div class="hv-row"><span>재고일수</span><span class="v">135.6일</span></div>
        <div class="hv-row"><span>표시위치 근거</span><span class="pill">원문 확인</span></div>
      </div>
    </div>
  </div>
</header>

<section class="section wrap" id="features">
  <div class="sec-head">
    <h2>실사의 첫 두 질문에 답합니다</h2>
    <p>이 이익이 진짜 현금을 벌어오는가, 그 안에 일회성은 무엇인가.</p>
  </div>
  <div class="cards">
    <div class="card">
      <div class="card-ico"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg></div>
      <h3>어떤 도구인가</h3>
      <p>한국 상장사의 영업이익 질과 조정 EBITDA를 재무제표·주석에서 스크리닝합니다. 회사명 하나면 됩니다.</p>
    </div>
    <div class="card">
      <div class="card-ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg></div>
      <h3>누가 쓰는가</h3>
      <p>M&amp;A 인수 실사 실무자와 감사인. 대상 회사의 이익 질을 빠르게 훑고, 조정 후보를 원문과 함께 확인합니다.</p>
    </div>
    <div class="card">
      <div class="card-ico"><svg viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg></div>
      <h3>왜 이 도구인가</h3>
      <p>주석 깊이 파묻힌 일회성을 빠짐없이 올립니다. 도구는 판정하지 않고, 모든 숫자에 원문 근거를 답니다.</p>
    </div>
  </div>
</section>

<section class="steps-sec section" id="how">
  <div class="wrap">
    <div class="sec-head">
      <h2>작동 방식</h2>
      <p>세 단계로 끝납니다. 평균 6분.</p>
    </div>
    <div class="steps">
      <div class="step">
        <div class="step-n"><b>1</b>입력</div>
        <h4>회사명을 넣습니다</h4>
        <p>OpenDART에서 재무제표와 주석을 자동으로 받아옵니다. 별도 자료 준비가 필요 없습니다.</p>
      </div>
      <div class="step">
        <div class="step-n"><b>2</b>분석</div>
        <h4>두 축으로 읽습니다</h4>
        <p>재무제표로 이익의 질을, 주석에서 일회성 항목을 발굴해 조정 EBITDA 후보를 만듭니다.</p>
      </div>
      <div class="step">
        <div class="step-n"><b>3</b>확인</div>
        <h4>원문으로 판단합니다</h4>
        <p>모든 후보에 원문보기가 붙습니다. 조정 여부는 화면에서 직접 토글해 판단합니다.</p>
      </div>
    </div>
  </div>
</section>

<section class="cta-sec wrap">
  <h2>지금 바로 돌려보세요</h2>
  <p>로컬에서 실행됩니다. 실사 데이터가 PC를 떠나지 않습니다.</p>
  <a href="/start" class="btn btn-primary">시작하기</a>
</section>

<footer class="wrap">
  <div>© 2026 QoE Screener · 로컬 실행 도구</div>
  <div class="f-links">
    <a href="__REPO__" target="_blank" rel="noopener">GitHub</a>
    <a href="__REPO__#readme" target="_blank" rel="noopener">문서</a>
    <a href="__REPO__/blob/main/docs/limitations.md" target="_blank" rel="noopener">한계</a>
  </div>
</footer>

</body>
</html>"""


def landing_page():
    return (_LANDING.replace("__FAVICON__", FAVICON)
                    .replace("__BRAND__", BRAND_SVG)
                    .replace("__REPO__", REPO_URL))


def _has_keys():
    return bool(_KEYS.get("opendart") and _KEYS.get("anthropic"))


# ── 라우트 ────────────────────────────────────────────────────────
@app.route("/")
def index():
    # 진입 = 랜딩 페이지. "시작하기"는 /start 로 이어져 기존 키 게이팅을 탄다.
    return landing_page()


@app.route("/start")
def start():
    # 기존 진입 로직(키 없으면 키입력, 있으면 회사입력). 로직 무변경 — 라우트만 분리했다.
    if not _has_keys():
        return redirect(url_for("keys_form"))
    return company_form()


@app.route("/keys", methods=["GET"])
def keys_form(err=None):
    e = f'<div class="err">{escape(err)}</div>' if err else ""
    body = f"""
  <h1>API 키 입력</h1>
  <p class="sub">키는 이 PC 메모리에만 잠시 머물다 서버를 끄면 사라집니다.
     파일·로그에 저장하지 않고, 로컬 실행이라 PC 밖으로 나가지 않습니다.</p>
  <div class="card">{e}
    <form method="post" action="/keys">
      <label>OpenDART API 키
        <span class="hint">무료 · 발급: <a href="{ISSUER_DART}" target="_blank" rel="noopener">opendart.fss.or.kr</a></span></label>
      <input type="password" name="opendart" autocomplete="off" spellcheck="false"
             placeholder="40자리 영숫자" required>
      <label>Anthropic API 키
        <span class="hint">유료·소액 · 발급: <a href="{ISSUER_ANTHROPIC}" target="_blank" rel="noopener">console.anthropic.com</a></span></label>
      <input type="password" name="anthropic" autocomplete="off" spellcheck="false"
             placeholder="sk-ant-..." required>
      <button type="submit">저장하고 시작</button>
    </form>
    <p class="note">저장 = 이 서버 프로세스의 메모리에만 보관. 디스크에 쓰지 않습니다.</p>
  </div>"""
    return page("API 키", body)


@app.route("/keys", methods=["POST"])
def keys_save():
    dart = (request.form.get("opendart") or "").strip()
    anth = (request.form.get("anthropic") or "").strip()
    if not dart or not anth:
        return keys_form(err="두 키를 모두 입력하세요.")
    with _LOCK:
        _KEYS["opendart"] = dart
        _KEYS["anthropic"] = anth
    return redirect(url_for("start"))


@app.route("/keys/clear", methods=["POST"])
def keys_clear():
    with _LOCK:
        _KEYS.clear()
    return redirect(url_for("keys_form"))


def company_form(err=None):
    e = f'<div class="err">{escape(err)}</div>' if err else ""
    chips = "".join(
        f'<span class="chip" data-q="{escape(code)}">{escape(name)} '
        f'<b>{escape(code)}</b></span>' for name, code in EXAMPLES)
    body = f"""
  <div class="keystate"><span class="dot"></span> API 키 설정됨 (메모리)
     <form method="post" action="/keys/clear" style="margin:0 0 0 auto">
       <button class="btn ghost" type="submit">키 변경</button></form></div>
  <h1>회사 입력</h1>
  <p class="sub">회사명 또는 6자리 종목코드를 넣으면, 영업이익 안에 파묻힌 일회성 조정 후보를
     EBITDA 브릿지와 함께 화면으로 올립니다. 조정은 토글로, 판정은 사람이.</p>
  <div class="card">{e}
    <form method="post" action="/preview" id="runform">
      <label>회사명 또는 종목코드</label>
      <input type="text" name="query" id="query" autocomplete="off" spellcheck="false"
             placeholder="예: 삼성전자  또는  005930" required autofocus>
      <div class="row">{chips}</div>
      <button type="submit">다음 — 예상 비용 확인</button>
    </form>
    <p class="note">회사를 넣으면 <b>실행 전에</b> 예상 비용·소요시간을 먼저 보여줍니다. 같은 공시를
       이미 분석한 적이 있으면 <b>저장된 결과를 무료로 재사용</b>할 수 있고, 새 공시가 올라왔으면 다시
       분석합니다. 분석은 재무제표 수집 → 주석 후보 발굴(Claude 3회) → D&A 추출 → 화면 구성 순으로
       돕니다. 금융업(은행·보험·증권)은 범위 밖입니다.</p>
  </div>
  <script>
    document.querySelectorAll('.chip').forEach(function(c){{
      c.addEventListener('click', function(){{
        document.getElementById('query').value = c.getAttribute('data-q');
      }});
    }});
  </script>"""
    return page("회사 입력", body)


@app.route("/preview", methods=["POST"])
def preview():
    """실행 전 안내 — 회사 해석 + 저장분 재사용 가능 여부 + 예상 비용·시간. LLM 안 부름(공짜)."""
    if not _has_keys():
        return redirect(url_for("keys_form"))
    query = (request.form.get("query") or "").strip()
    if not query:
        return company_form(err="회사명 또는 종목코드를 입력하세요.")
    try:
        pv = pipeline.preview(_KEYS["opendart"], query)
    except Exception as e:  # noqa: BLE001  — 회사 해석 실패(0건/복수/비상장)만 여기 온다
        return company_form(err=str(e))

    c = pv["company"]
    est = pv["estimate"]
    fr = pv["freshness"]
    qesc = escape(query)
    name = escape(f'{c["corp_name"]} ({c["stock_code"]})')
    report = escape(fr.get("report_nm") or "최신 사업보고서")
    chars = est["notes_chars"]
    chars_txt = f"약 {chars:,}자" + ("(추정)" if est["approx"] else "")
    cost_txt = f"${est['usd_low']:.1f}~${est['usd_high']:.1f}"
    time_txt = f"{est['minutes_low']}~{est['minutes_high']}분"
    basis = escape(est["basis"])

    # 재사용 가능 여부에 따라 카드 문구·버튼을 바꾼다. 새 분석은 항상 가능, 재사용은 같은 공시가 있을 때만.
    fresh = fr.get("fresh")
    if fr.get("has_saved") and fresh is True:
        head = ('<div class="keystate">'
                '<span class="dot"></span> 저장된 분석 있음 (같은 공시) — 재사용하면 무료·즉시</div>')
        note = "이미 같은 공시로 분석한 결과가 있습니다. 재사용하면 Claude 를 다시 부르지 않습니다(무료)."
    elif fr.get("has_saved") and fresh is None:
        head = ('<div class="keystate"><span class="dot" style="background:var(--warn)"></span> '
                '저장된 분석 있음 — 최신 공시 확인 불가(오프라인?), 재사용 가능</div>')
        note = "저장된 분석이 있으나 최신 공시 여부를 확인하지 못했습니다. 재사용하거나 새로 분석하세요."
    elif fr.get("has_saved") and fresh is False:
        head = ('<div class="keystate">'
                '<span class="dot" style="background:var(--warn)"></span> 새 공시 감지 — 저장된 분석은 이전 '
                f'공시({escape(str(fr.get("saved_rcept")))}) 기준, 다시 분석해야 합니다</div>')
        note = ("새 사업보고서가 올라와 저장된 분석이 낡았습니다. 새로 분석하면 최신 공시로 다시 발굴합니다."
                "(재사용을 눌러도 새 공시가 감지되면 자동으로 다시 분석합니다.)")
    else:
        head = ('<div class="keystate"><span class="dot" style="background:var(--mute)"></span> '
                '저장된 분석 없음 — 이 회사는 처음입니다</div>')
        note = "처음 분석하는 회사입니다. 아래 예상 비용·시간을 확인하고 시작하세요."

    reuse_btn = ""
    if pv["reuse_free"]:
        reuse_btn = (f'<form method="post" action="/run" style="margin:0">'
                     f'<input type="hidden" name="query" value="{qesc}">'
                     f'<input type="hidden" name="reuse_surface" value="1">'
                     f'<button type="submit">저장된 분석 재사용 (무료·즉시)</button></form>')
    # 재사용 버튼이 있으면 '새로 분석'은 보조(ghost) 스타일로, 없으면 기본(강조) 스타일로.
    fresh_label = "새로 분석" if fr.get("has_saved") else "분석 시작"
    fresh_attr = (' class="btn ghost" style="background:transparent;color:var(--accent);'
                  'border:1px solid var(--line);padding:11px 20px"') if pv["reuse_free"] else ""
    fresh_btn = (f'<form method="post" action="/run" style="margin:0">'
                 f'<input type="hidden" name="query" value="{qesc}">'
                 f'<input type="hidden" name="reuse_surface" value="">'
                 f'<button type="submit"{fresh_attr}>{fresh_label} (예상 {cost_txt})</button></form>')

    body = f"""
  <div class="keystate"><span class="dot"></span> API 키 설정됨 (메모리)
     <form method="post" action="/keys/clear" style="margin:0 0 0 auto">
       <button class="btn ghost" type="submit">키 변경</button></form></div>
  <h1>실행 전 확인</h1>
  <p class="sub">{name} · {report}</p>
  <div class="card">
    {head}
    <table style="width:100%;border-collapse:collapse;margin:14px 0 6px;font-size:14px">
      <tr><td style="padding:7px 0;color:var(--ink-soft);width:38%">주석 분량</td>
          <td style="padding:7px 0;font-variant-numeric:tabular-nums">{chars_txt}</td></tr>
      <tr><td style="padding:7px 0;color:var(--ink-soft);border-top:1px solid var(--line-2)">예상 비용 (새 분석)</td>
          <td style="padding:7px 0;border-top:1px solid var(--line-2);font-variant-numeric:tabular-nums"><b>{cost_txt}</b></td></tr>
      <tr><td style="padding:7px 0;color:var(--ink-soft);border-top:1px solid var(--line-2)">예상 소요시간</td>
          <td style="padding:7px 0;border-top:1px solid var(--line-2);font-variant-numeric:tabular-nums">{time_txt}</td></tr>
    </table>
    <p class="note" style="margin-top:6px">{escape(note)}</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:18px;align-items:center">
      {reuse_btn}{fresh_btn}
    </div>
    <p class="note" style="margin-top:16px">{basis}. 주석 발굴은 Claude(Opus) 3회 반복이 방어의
       전제라 줄이지 않습니다. 재사용은 저장된 분석(같은 공시)을 그대로 쓰는 것이라 정확도 영향이 없습니다.</p>
    <a class="btn ghost" href="/start" style="margin-top:8px">← 다른 회사</a>
  </div>"""
    return page("실행 전 확인", body)


@app.route("/run", methods=["POST"])
def run():
    if not _has_keys():
        return redirect(url_for("keys_form"))
    query = (request.form.get("query") or "").strip()
    if not query:
        return company_form(err="회사명 또는 종목코드를 입력하세요.")
    reuse_surface = bool(request.form.get("reuse_surface"))
    job_id = uuid.uuid4().hex[:12]
    job = pipeline.new_job(job_id, query)
    job["reuse_surface"] = reuse_surface
    with _LOCK:
        _JOBS[job_id] = job
    dart, anth = _KEYS["opendart"], _KEYS["anthropic"]
    t = threading.Thread(target=pipeline.run, args=(job, dart, anth),
                         kwargs={"reuse_surface": reuse_surface}, daemon=True)
    t.start()
    return redirect(url_for("progress_page", job_id=job_id))


@app.route("/progress/<job_id>")
def progress_page(job_id):
    if job_id not in _JOBS:
        return redirect(url_for("index"))
    body = """
  <h1>실행 중</h1>
  <p class="sub" id="sub">파이프라인을 시작합니다…</p>
  <div class="card">
    <ol class="steps" id="steps"></ol>
    <div id="err"></div>
  </div>
  <p class="note">이 창을 열어두세요. 완료되면 EBITDA 조정 화면으로 넘어갑니다.</p>"""
    script = """<script>
  var JOB = "%s";
  var LABELS = ["재무제표 수집 (DART)","주석 후보 발굴 (Claude · 3회 반복)","D&A 추출","화면 구성"];
  function fmt(s){ if(s==null) return ""; return s.toFixed(0)+"s"; }
  function mark(st,i){ if(st==="done") return "\\u2713"; if(st==="error") return "\\u2715"; return String(i+1); }
  function draw(j){
    var ol = document.getElementById("steps"); ol.innerHTML="";
    j.steps.forEach(function(s,i){
      var li=document.createElement("li"); li.className=s.status;
      var meta="";
      if(s.status==="done") meta = (s.key==="surface" && s.reused) ? "기존 결과 재사용 (Claude 생략)" : fmt(s.elapsed);
      else if(s.status==="running"){
        meta = fmt(s.elapsed_live);
        if(s.key==="surface") meta = "3회 중 "+j.surface.done+"회"+(s.elapsed_live!=null?" · "+fmt(s.elapsed_live):"");
      }
      li.innerHTML = '<span class="mark">'+mark(s.status,i)+'</span>'+
        '<span class="stepmain"><span class="steplabel">'+LABELS[i]+'</span>'+
        (meta?'<div class="stepmeta">'+meta+'</div>':'')+'</span>';
      ol.appendChild(li);
    });
    var sub=document.getElementById("sub");
    if(j.company) sub.textContent = j.company.corp_name+" ("+j.company.stock_code+")";
    else if(j.status==="resolving") sub.textContent = "회사 확인 중: "+j.input;
    if(j.status==="error"){
      document.getElementById("err").innerHTML =
        '<div class="err" style="margin:14px 0 0">'+ (j.error||"오류") +'</div>'+
        '<a class="btn" href="/start">다시 시도</a>';
    }
    if(j.status==="done" && j.result_url){
      sub.textContent = (j.company? j.company.corp_name+" ("+j.company.stock_code+") · " : "")+"완료 — 화면으로 이동합니다";
      window.location = j.result_url;
    }
  }
  function poll(){
    fetch("/status/"+JOB).then(function(r){return r.json();}).then(function(j){
      draw(j);
      if(j.status!=="done" && j.status!=="error") setTimeout(poll, 1500);
    }).catch(function(){ setTimeout(poll, 2000); });
  }
  poll();
</script>""" % escape(job_id)
    return page("실행 중", body, script)


@app.route("/status/<job_id>")
def status(job_id):
    job = _JOBS.get(job_id)
    if not job:
        abort(404)
    # 키는 job 에 들어있지 않다. 그대로 직렬화해도 안전. 실행 중 단계의 live 경과만 덧붙인다.
    view = {
        "status": job["status"],
        "input": job["input"],
        "company": job["company"],
        "surface": job["surface"],
        "error": job["error"],
        "result_url": job["result_url"],
        "steps": [],
    }
    now = time.time()
    for s in job["steps"]:
        d = {"key": s["key"], "status": s["status"], "elapsed": s["elapsed"],
             "elapsed_live": None, "reused": s.get("reused", False)}
        if s["status"] == "running" and s["started"]:
            d["elapsed_live"] = round(now - s["started"], 1)
        view["steps"].append(d)
    return jsonify(view)


# 페이지 파일명만 허용(report_/quality_/screen_ + 6자리). report 는 통합 리포트(랜딩), quality/screen
# 은 개별 페이지(직접 열람용). 통합 리포트는 두 페이지를 srcdoc 로 인라인 임베드해 자기완결이라 런타임에
# 다른 파일을 불러오지 않는다(file:// 데모에서도 안전).
_PAGE_NAME = re.compile(r"^(?:report|quality|screen)_\d{6}\.html$")


@app.route("/v/<name>")
def view_page(name):
    if not _PAGE_NAME.match(name):
        abort(404)
    path = OUT_DIR / name
    if not path.exists():
        abort(404)
    return Response(path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route("/result/<stock>")
def result(stock):
    # 하위호환: 종목코드로 들어오면 통합 리포트(① 이익의 질 → ② 조정 EBITDA)로 보낸다.
    if not (stock.isdigit() and len(stock) == 6):
        abort(404)
    return redirect(f"/v/report_{stock}.html")


@app.route("/demo/<name>")
def demo(name):
    if not _PAGE_NAME.match(name):
        abort(404)
    path = OUT_DIR / "results" / name
    if not path.exists():
        abort(404)
    return Response(path.read_text(encoding="utf-8"), mimetype="text/html")


def _open_browser():
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass


def main():
    # 로컬 전용: 127.0.0.1 만 바인딩(외부 노출 금지). 리로더 끔(백그라운드 스레드·서브프로세스 보호).
    print("QoE Normalizer  ->  http://127.0.0.1:5000  (Ctrl+C to stop)")
    threading.Timer(1.2, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
