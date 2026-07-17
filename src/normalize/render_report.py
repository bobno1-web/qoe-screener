"""통합 리포트 — 페이지 1(이익의 질) + 페이지 2(조정 EBITDA)를 한 HTML 스크롤 문서로 묶는다.

왜 이렇게 묶나:
- 두 페이지는 하나의 이야기다 — 재무제표로 "이 영업이익을 믿을 수 있나"(1)를 먼저 보고, 그다음
  주석에서 일회성을 걷어낸다(2). 페이지를 끊으면 감사인이 위아래를 비교할 때 매번 로딩·스크롤
  위치를 잃는다. 한 페이지 스크롤 + 상단 고정 네비로 다스린다.

어떻게(배치·통합만, 페이지 2 로직 무변경):
- 두 페이지의 렌더 출력(quality_<code>.html, screen_<code>.html)을 **srcdoc iframe 으로 그대로 임베드**한다.
  → 페이지 2 의 HTML/JS 바이트가 한 글자도 안 바뀐다(재계산 공식·이중가산 3단계·D&A 게이트·표시위치
  3겹 방어 전부 무변경). 두 페이지의 전역 CSS(:root·body·.card·.ov)·전역 JS(const DATA·openSrc)·inline
  onclick 이 겹쳐 한 DOM 병합은 충돌하는데, iframe 은 그걸 원천 격리한다.
- srcdoc iframe 은 부모 origin 을 물려받아 **same-origin** — file:// 로 열어도 부모가 자식 높이를 재고
  표시 보정을 넣을 수 있다(개별 파일 src= 였다면 file:// cross-origin 으로 막힐 일).
- 전체높이 iframe(진짜 한 페이지 스크롤)의 부작용 두 개는 **표시용 보정**으로만 처리한다(분석 JS 무관):
  (a) 개별 페이지 자체 네비(.pagenav)는 통합 sticky 네비와 중복이라 숨긴다.
  (b) 원문보기 모달(.ov, position:fixed·vh)이 전체높이 iframe 에선 위치·크기가 어긋나므로, 열릴 때
      현재 보이는 화면 슬라이스로 옮기고 크기를 맞춘다(부모에서 same-origin 으로).

판정하지 않는다: 색·등급·임계 도입 없음. 두 축 사이의 인과를 단정하지 않는다 — 숫자를 나란히 둘 뿐.

사용:
  python src/normalize/render_report.py --stock-code 000660
  python src/normalize/render_report.py --quality out/quality_000660.html --screen out/screen_000660.html
"""
from __future__ import annotations

import argparse
import json
import re
from html import escape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"

_DATA_RE = re.compile(r"const DATA\s*=\s*(\{.*?\});</script>", re.DOTALL)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def extract_meta(quality_html: str) -> dict:
    """페이지 1 HTML 의 인라인 DATA 에서 회사명·종목코드·기준연도·연도범위를 뽑는다(네비 헤더용)."""
    m = _DATA_RE.search(quality_html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    comp = data.get("company") or {}
    years = data.get("years") or []
    return {
        "corp_name": comp.get("corp_name") or "",
        "stock_code": comp.get("stock_code") or "",
        "base_year": data.get("base_year"),
        "years": years,
    }


# ───────────────────────────────────────────────────────── 통합 셸(배치만) ───
REPORT = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --ink:#1c2530; --muted:#5b6b7b; --line:#d7dee6; --bg:#eef1f5; --card:#fff;
          --accent:#2f4a63; --band:#22364a; }
  * { box-sizing:border-box; }
  html, body { margin:0; }
  body { font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;
         color:var(--ink); background:var(--bg); }
  .topnav { position:sticky; top:0; z-index:50; background:rgba(255,255,255,.94);
            -webkit-backdrop-filter:blur(6px); backdrop-filter:blur(6px); border-bottom:1px solid var(--line); }
  .topnav .inner { max-width:1040px; margin:0 auto; padding:9px 18px; display:flex;
                   align-items:center; gap:14px; flex-wrap:wrap; }
  .ident { display:flex; align-items:baseline; gap:9px; min-width:0; }
  .ident b { font-size:15px; font-weight:700; letter-spacing:-.01em; }
  .ident .code { font:12px ui-monospace,Consolas,monospace; color:var(--muted); font-weight:600; }
  .ident .yr { font-size:12px; color:var(--muted); font-weight:500; white-space:nowrap; }
  .jump { margin-left:auto; display:flex; gap:6px; }
  .jump a { text-decoration:none; font-size:13px; color:var(--accent); border:1px solid var(--line);
            background:#fff; border-radius:20px; padding:5px 13px; white-space:nowrap; }
  .jump a:hover { border-color:var(--accent); }
  .jump a.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  main { max-width:1040px; margin:0 auto; padding:0 14px 40px; }
  .sec { scroll-margin-top:56px; }
  .sechd { display:flex; align-items:center; gap:11px; margin:22px 4px 9px; }
  .secno { width:26px; height:26px; border-radius:7px; background:var(--band); color:#fff;
           font-weight:700; font-size:14px; display:grid; place-items:center; flex:none; }
  .sechd .t { font-size:17px; font-weight:700; }
  .sechd .s { font-size:12.5px; color:var(--muted); }
  .frame { width:100%; border:1px solid var(--line); border-radius:12px; background:var(--card);
           display:block; min-height:600px; }
  .divider { display:flex; align-items:center; gap:14px; margin:30px 8px 6px; color:var(--muted);
             font-size:12.5px; }
  .divider::before, .divider::after { content:""; height:1px; background:var(--line); flex:1; }
  .divider span { max-width:660px; text-align:center; line-height:1.65; }
  footer { max-width:1040px; margin:0 auto; padding:22px 20px 40px; color:var(--muted); font-size:12px;
           line-height:1.7; }
  noscript { display:block; max-width:1040px; margin:14px auto; padding:12px 18px; background:#fff;
             border:1px solid var(--line); border-radius:10px; color:var(--muted); font-size:13px; }
</style></head><body>
<nav class="topnav"><div class="inner">
  <div class="ident">__IDENT__</div>
  <div class="jump">
    <a href="#sec1" data-i="0" class="active">① 이익의 질</a>
    <a href="#sec2" data-i="1">② 조정 EBITDA</a>
  </div>
</div></nav>
<main>
  <noscript>이 리포트는 두 화면을 한 페이지에 담기 위해 JavaScript 로 높이를 맞춥니다. 스크립트가 꺼져
    있으면 각 섹션이 잘려 보일 수 있습니다 — 개별 페이지(quality_·screen_)를 직접 여세요.</noscript>
  <section id="sec1" class="sec">
    <div class="sechd"><span class="secno">1</span>
      <span class="t">이익의 질</span>
      <span class="s">재무제표로 "이 영업이익이 현금을 벌어오나"</span></div>
    <iframe id="f1" class="frame" title="이익의 질" srcdoc="__SRC1__"></iframe>
  </section>
  <div class="divider"><span>__CONNECT__</span></div>
  <section id="sec2" class="sec">
    <div class="sechd"><span class="secno">2</span>
      <span class="t">조정 EBITDA</span>
      <span class="s">주석에서 일회성 발굴·조정(토글) — 판정은 감사인이</span></div>
    <iframe id="f2" class="frame" title="조정 EBITDA" srcdoc="__SRC2__"></iframe>
  </section>
</main>
<footer>__FOOT__</footer>
<script>__JS__</script>
</body></html>"""

# 부모 스크립트: (1) 자식 높이 자동 맞춤(전체높이 → 한 페이지 스크롤), (2) 자체 네비 숨김·모달 위치
# 보정(표시용), (3) 스크롤에 따른 네비 active. 전부 same-origin 으로 자식 DOM 을 읽되 분석 JS 는 안 건드린다.
REPORT_JS = r"""
(function(){
  var NAVH = 52;
  var frames = [document.getElementById('f1'), document.getElementById('f2')];
  var secs   = [document.getElementById('sec1'), document.getElementById('sec2')];
  var links  = document.querySelectorAll('.jump a');
  var openOvs = [];

  function docOf(f){ try { return f.contentDocument || (f.contentWindow && f.contentWindow.document); }
                     catch(e){ return null; } }

  // (1) 전체높이 = 내부 스크롤 없이 부모 스크롤 하나로 — 자식 문서 높이를 iframe 에 그대로.
  function fit(f){ var d = docOf(f); if(!d || !d.documentElement) return;
    var h = d.documentElement.scrollHeight; if(h > 0) f.style.height = h + 'px'; }

  // (2a) 개별 페이지 자체 네비(.pagenav)는 통합 네비와 중복 → 숨김. 모달 내부 vh 캡 해제(전체높이라 과대).
  function injectShim(d){ if(!d || !d.head) return;
    try { var st = d.createElement('style');
      st.textContent = '.pagenav{display:none!important}' +
                       '.ov .excerpt{max-height:none!important}' +
                       '.ov .istbl{max-height:none!important}';
      d.head.appendChild(st); } catch(e){} }

  // (2b) 원문보기 모달: 전체높이 iframe 에선 position:fixed/vh 가 어긋난다 → 열릴 때 현재 보이는
  // 화면 슬라이스(top=화면상단이 자식문서에서 가리키는 위치, height=부모 뷰포트)로 옮기고 크기 보정.
  function isOpen(ov){ var w = ov.ownerDocument.defaultView;
    return ov.classList.contains('on') || (w && w.getComputedStyle(ov).display !== 'none'); }
  function placeOv(f, ov){
    var m = ov.querySelector('.modal');
    if(!isOpen(ov)){ ov.style.position=''; ov.style.top=''; ov.style.height=''; ov.style.bottom='';
      if(m) m.style.maxHeight=''; var k=openOvs.indexOf(ov); if(k>=0) openOvs.splice(k,1); return; }
    var rect = f.getBoundingClientRect();
    var vh = window.innerHeight;
    var visTop = Math.min(Math.max(0, -rect.top), Math.max(0, f.offsetHeight - 40));
    ov.style.position = 'absolute';
    ov.style.top = visTop + 'px';
    ov.style.height = vh + 'px';
    ov.style.bottom = 'auto';
    if(m) m.style.maxHeight = Math.round(vh * 0.86) + 'px';
    if(openOvs.indexOf(ov) < 0) openOvs.push(ov);
  }
  function watchOvs(f){ var d = docOf(f); if(!d) return;
    var ovs = d.querySelectorAll('.ov');
    for(var i=0;i<ovs.length;i++){ (function(ov){
      try { var mo = new MutationObserver(function(){ placeOv(f, ov); });
        mo.observe(ov, {attributes:true, attributeFilter:['class','style']}); } catch(e){}
    })(ovs[i]); }
  }
  function reposOpen(){ openOvs.slice().forEach(function(ov){
    for(var k=0;k<frames.length;k++){ if(docOf(frames[k]) === ov.ownerDocument){ placeOv(frames[k], ov); break; } }
  }); }

  function onLoad(f){ var d = docOf(f); injectShim(d); fit(f); watchOvs(f);
    if(d){ try { var ro = new ResizeObserver(function(){ fit(f); reposOpen(); });
      ro.observe(d.documentElement); if(d.body) ro.observe(d.body); } catch(e){} } }

  frames.forEach(function(f){
    f.addEventListener('load', function(){ onLoad(f); });
    setTimeout(function(){ if(!f.style.height || f.style.height === '600px') onLoad(f); }, 80); // srcdoc 즉시로드 대비
  });
  // 폴백: ResizeObserver 없거나 지연 로드면 몇 차례 더 재측정.
  var ticks = 0;
  var iv = setInterval(function(){ frames.forEach(fit); if(++ticks > 8) clearInterval(iv); }, 250);

  // (3) 스크롤에 따라 네비 active 갱신.
  function onScroll(){ var y = window.scrollY + NAVH + 40;
    var active = (secs[1] && secs[1].offsetTop <= y) ? 1 : 0;
    for(var i=0;i<links.length;i++){ links[i].classList.toggle('active', +links[i].getAttribute('data-i') === active); }
    reposOpen();
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  window.addEventListener('resize', function(){ frames.forEach(fit); reposOpen(); onScroll(); });
  onScroll();
})();
"""

CONNECT = ("위(1)는 재무제표로 이익이 현금을 벌어오는지 검증하고, 아래(2)는 주석에서 일회성을 걷어낸다. "
           "QoE 사고 순서는 1 → 2 — 이익을 못 믿으면 일회성을 걷어내도 의미가 없다. "
           "두 축의 숫자를 나란히 보되, 무엇이 무엇의 원인인지는 도구가 단정하지 않는다. 판정은 감사인이 한다.")


def _ident(meta: dict) -> str:
    name = escape(meta.get("corp_name") or "회사")
    code = escape(meta.get("stock_code") or "")
    years = meta.get("years") or []
    by = meta.get("base_year")
    yr = ""
    if by:
        yr = f"기준연도 {escape(str(by))}"
        if years:
            yr += f" · {escape(str(years[0]))}~{escape(str(years[-1]))}"
    parts = [f"<b>{name}</b>"]
    if code:
        parts.append(f'<span class="code">{code}</span>')
    if yr:
        parts.append(f'<span class="yr">{yr}</span>')
    return " ".join(parts)


def _foot(meta: dict) -> str:
    return ("QoE 노멀라이저 · 한 페이지에 두 축을 담았습니다 — ① 재무제표로 이익 검증 → ② 주석에서 일회성 조정. "
            "① 이익의 질은 임계·색·등급으로 판정하지 않는다(산업마다 정상 범위가 다르다). ② 조정 EBITDA 의 "
            "재계산·이중가산 방어·표시위치 게이트는 개별 페이지 그대로다(이 리포트는 두 화면을 배치만 통합). "
            "모든 숫자에 원문보기(재무제표·주석)를 달았고, 최종 판정은 사람이 한다.")


def build_report(quality_html: str, screen_html: str, meta: dict) -> str:
    title = f"{meta.get('corp_name','') or '회사'} — 이익의 질 · 조정 EBITDA (통합)"
    return (REPORT
            .replace("__TITLE__", escape(title))
            .replace("__IDENT__", _ident(meta))
            .replace("__CONNECT__", escape(CONNECT))
            .replace("__FOOT__", escape(_foot(meta)))
            .replace("__SRC1__", escape(quality_html, quote=True))
            .replace("__SRC2__", escape(screen_html, quote=True))
            .replace("__JS__", REPORT_JS))


def main(argv=None):
    import sys
    p = argparse.ArgumentParser(description="통합 리포트: 페이지1(이익의 질)+페이지2(조정 EBITDA) → 한 HTML")
    p.add_argument("--stock-code")
    p.add_argument("--quality", help="페이지1 HTML(생략 시 out/quality_<stock>.html)")
    p.add_argument("--screen", help="페이지2 HTML(생략 시 out/screen_<stock>.html)")
    p.add_argument("--out", help="출력 HTML(생략 시 out/report_<stock>.html)")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    stock = (args.stock_code or "").strip()
    q_path = Path(args.quality) if args.quality else (OUT_DIR / f"quality_{stock}.html")
    s_path = Path(args.screen) if args.screen else (OUT_DIR / f"screen_{stock}.html")
    if not q_path.exists():
        raise SystemExit(f"페이지1 HTML 을 찾을 수 없습니다: {q_path} (render_quality 먼저 실행) (STOP)")
    if not s_path.exists():
        raise SystemExit(f"페이지2 HTML 을 찾을 수 없습니다: {s_path} (render 먼저 실행) (STOP)")

    quality_html = _read(q_path)
    screen_html = _read(s_path)
    meta = extract_meta(quality_html)
    if not stock:
        stock = meta.get("stock_code") or "unknown"

    html = build_report(quality_html, screen_html, meta)
    out_path = Path(args.out) if args.out else OUT_DIR / f"report_{stock}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[written] {out_path}")
    print(f"  회사 {meta.get('corp_name','?')} ({meta.get('stock_code','?')})  기준연도 {meta.get('base_year')}  "
          f"연도 {meta.get('years')}")
    print(f"  임베드: {q_path.name} ({len(quality_html):,}자) + {s_path.name} ({len(screen_html):,}자)")
    return out_path


if __name__ == "__main__":
    main()
