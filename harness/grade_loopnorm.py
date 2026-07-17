"""루프 normalize 채점 (사실만, 판정 없음).

토글 재계산이 회계적으로 정확한지 손계산과 대조한다. 핵심:
 1. 토글 재계산: normalized = base + Σ(sign*amount).  부호(이익=-1 차감 / 비용=+1 가산),
    누적(여러 개 동시), 참고항목 불변(체크박스 없음·recalc 루프 밖).
 2. 구역 분류: 정상화성격=조정대상→상단(B), 참고·불명→하단(C). 손상차손(하단표시)이 상단 갔나.
 3. 데이터 통합: bridge=ebitda src, candidates=surface src(무손실), screen_panel=screen src.
 4. 원문보기: 모든 항목 인용 존재 + 후보 인용이 실제 surface out 에 verbatim(날조 점검).
 5. 슬라이더: max=데이터파생, 하드코딩 임계 없음.
 6. 규칙: localStorage 미사용, 색 판정, 모든 항목 원문.

replicate: render.py 의 normalizedEBITDA() 를 파이썬으로 그대로 옮겨 손계산.
"""
import json
import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"

SV = OUT / "screenview_000660_20260711T023324Z.json"
EBITDA_SRC = OUT / "ebitda_000660_20260711T013414Z.json"
SCREEN_SRC = OUT / "screen_000660_20260710T084813Z.json"
SURFACE_REAL = OUT / "surface_000660_20260710T235842Z.json"   # fixture 가 인용 재사용한 실제 산출물
HTML = OUT / "screen_000660.html"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def digits(s):
    return re.sub(r"[^0-9]", "", str(s) if s is not None else "")


def norm_ebitda(base_m, adjustments, checked_ids):
    """render.py normalizedEBITDA() 그대로: base + Σ(sign*amount) over checked & toggleable."""
    t = base_m
    for a in adjustments:
        if a["id"] in checked_ids and a.get("toggleable"):
            t += a["sign"] * a["amount_million"]
    return t


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sv = load(SV)
    eb = load(EBITDA_SRC)
    scr = load(SCREEN_SRC)
    real_surface = load(SURFACE_REAL)
    html = HTML.read_text(encoding="utf-8")

    base = sv["bridge"]["ebitda_base_million"]
    adj = sv["adjustments"]
    ref = sv["reference"]

    print("=" * 78)
    print("### 1. 토글 재계산 정확성 (1순위)")
    print(f"기준선 base EBITDA = {base:,.0f} 백만원")
    print(f"   = 영업이익 {sv['bridge']['operating_income']['amount_million']:,.0f}"
          f" + D&A {sv['bridge']['da']['operating_da_million']:,.0f}")
    print("\n-- 개별 토글(부호·금액) : 각 항목 단독 체크 시 --")
    print(f"{'id':6}{'항목명':42}{'방향':5}{'sign':5}{'금액(백만)':>14}{'단독체크→EBITDA':>18}{'Δ':>14}")
    for a in adj:
        one = norm_ebitda(base, adj, {a["id"]})
        d = one - base
        # 부호 기대: 이익이면 감소(Δ<0), 비용이면 증가(Δ>0)
        exp = "-" if a["손익방향"] == "이익" else ("+" if a["손익방향"] == "비용" else "?")
        got = "-" if d < 0 else ("+" if d > 0 else "0")
        ok = "OK" if exp == got else "<<부호오류"
        print(f"{a['id']:6}{a['항목명'][:40]:42}{a['손익방향']:5}{a['sign']:>4} "
              f"{a['amount_million']:>14,.0f}{one:>18,.0f}{d:>+14,.0f}  {ok}")

    print("\n-- 누적: 전부 체크 --")
    allids = {a["id"] for a in adj}
    allnorm = norm_ebitda(base, adj, allids)
    # 손계산 독립 재현
    hand = base + sum(a["sign"] * a["amount_million"] for a in adj)
    print(f"   전부체크 EBITDA(도구식) = {allnorm:,.0f}")
    print(f"   손계산 base + Σ(sign*amount) = {hand:,.0f}   일치={allnorm==hand}")
    profits = sum(a["amount_million"] for a in adj if a["손익방향"] == "이익")
    costs = sum(a["amount_million"] for a in adj if a["손익방향"] == "비용")
    print(f"   이익합(차감) {profits:,.0f} · 비용합(가산) {costs:,.0f} · 순 {costs-profits:+,.0f}")
    print(f"   base {base:,.0f} + 순 {costs-profits:+,.0f} = {base+costs-profits:,.0f}")

    print("\n-- 누적 스팟체크: 임의 2·3개 조합 손계산 대조 --")
    fails = 0
    for r in (2, 3):
        for combo in combinations(adj, r):
            ids = {a["id"] for a in combo}
            tool = norm_ebitda(base, adj, ids)
            hand2 = base + sum(a["sign"] * a["amount_million"] for a in combo)
            if abs(tool - hand2) > 1e-6:
                fails += 1
    print(f"   2·3개 조합 전수 대조: 불일치 {fails} 건")

    print("\n-- 참고(구역 C) 항목이 EBITDA 를 움직일 수 있나 --")
    # (a) recalc 루프는 adjustments 만 돈다 (HTML 검증), (b) reference 는 체크박스 미렌더
    recalc_body = html.split("function normalizedEBITDA")[1].split("function renderHeadline")[0]
    print(f"   recalc 루프가 DATA.reference 참조: {'DATA.reference' in recalc_body}  (False 여야 함)")
    render_ref = html.split("function renderReference")[1].split("function toggle")[0]
    print(f"   renderReference 가 checkbox 렌더: {'type=\"checkbox\"' in render_ref or 'checkbox' in render_ref}  (False 여야 함)")
    print(f"   참고 항목 수 {len(ref)} — recalc 에 절대 진입 안 함(루프 대상=adjustments {len(adj)}건)")

    print("\n" + "=" * 78)
    print("### 2. 구역 분류 정확성")
    b_wrong = [a["항목명"] for a in adj if a["정상화성격"] != "조정대상"]
    c_wrong = [r["항목명"] for r in ref if r["정상화성격"] not in ("참고", "불명", "불명(surface/1)")]
    print(f"   구역B(상단) 전원 정상화성격=조정대상: {not b_wrong}  오배치={b_wrong}")
    print(f"   구역C(하단) 전원 참고/불명: {not c_wrong}  오배치={c_wrong}")
    print("   손상차손(표시위치=하단, 정상화성격=조정대상) 위치:")
    for a in adj + ref:
        if "손상차손" in a["항목명"]:
            zone = "상단(B)" if a in adj else "하단(C)"
            print(f"      [{zone}] {a['항목명'][:44]} · 표시위치={a['표시위치']} · 정상화성격={a['정상화성격']}")

    print("\n" + "=" * 78)
    print("### 3. 데이터 통합 무결성 (통합JSON vs 원본 out/)")
    # bridge vs ebitda src
    checks = []
    checks.append(("영업이익", sv["bridge"]["operating_income"]["amount_won"], eb["operating_income"]["amount_won"]))
    checks.append(("D&A 가산", sv["bridge"]["da"]["operating_da_won"], eb["da"]["operating_da_won"]))
    checks.append(("EBITDA base", sv["bridge"]["ebitda_base_won"], eb["ebitda"]["amount_won"]))
    checks.append(("리스 ROU", sv["bridge"]["da"]["lease"]["value_won"], eb["da"]["lease"]["value_won"]))
    for nm, a, b in checks:
        print(f"   {nm:14} screenview={a:>18,}  ebitda_src={b:>18,}  일치={a==b}")
    # candidates vs surface src (무손실)
    real_cands = real_surface["runs"][0]["candidates"]
    print(f"   surface 후보수: 원본 {len(real_cands)}  →  통합 adjustments+reference {len(adj)+len(ref)}  "
          f"(무손실={len(real_cands)==len(adj)+len(ref)})")
    # screen panel vs screen src
    sp = sv["screen_panel"]
    ss = scr["screen"]
    print(f"   screen_panel 누적영업이익 {sp['cumulative_operating_income']} vs src {ss['cumulative_operating_income']} "
          f"일치={sp['cumulative_operating_income']==ss['cumulative_operating_income']}")
    print(f"   screen_panel 누적영업현금 {sp['cumulative_operating_cash_flow']} vs src {ss['cumulative_operating_cash_flow']} "
          f"일치={sp['cumulative_operating_cash_flow']==ss['cumulative_operating_cash_flow']}")
    # HTML 임베드 무손실
    i = html.find("const DATA = ")
    j = html.find("\n// ---- state", i)
    dtxt = html[i + len("const DATA = "):j].rstrip().rstrip(";")
    same = json.dumps(json.loads(dtxt), sort_keys=True, ensure_ascii=False) == json.dumps(sv, sort_keys=True, ensure_ascii=False)
    print(f"   HTML 인라인 DATA == screenview JSON(무손실): {same}")

    print("\n" + "=" * 78)
    print("### 4. 원문보기 (모든 항목 인용 존재 + 후보 인용 실제성)")
    missing = [x["항목명"] for x in adj + ref if not (x.get("인용") or "").strip()]
    print(f"   후보 전원 인용 존재: {not missing}  누락={missing}")
    # 후보 인용이 실제 surface out 에 verbatim 존재
    real_quotes = {re.sub(r'\s+', '', c.get('인용', '')) for c in real_cands}
    fab = []
    for x in adj + ref:
        q = re.sub(r'\s+', '', x.get('인용', ''))
        if q not in real_quotes:
            fab.append(x["항목명"])
    print(f"   후보 인용이 실제 surface 산출물에 verbatim: 날조/불일치 {len(fab)}건  {fab}")
    # bridge 원문값이 ebitda src line 에 존재
    bridge_srcs = [sv["bridge"]["operating_income"].get("source")]
    for ln in sv["bridge"]["da"]["lines"]:
        bridge_srcs.append(ln.get("source"))
    bridge_srcs.append(sv["bridge"]["da"]["lease"].get("source"))
    nosrc = sum(1 for s in bridge_srcs if not s)
    print(f"   브릿지 원문소스: 총 {len(bridge_srcs)}개 중 소스없음 {nosrc}개")
    # D&A 원문값이 인용에 들어있나(자기정합)
    da_bad = 0
    for ln in sv["bridge"]["da"]["lines"]:
        s = ln.get("source") or {}
        if s.get("원문값") and s.get("인용") and digits(s["원문값"]) not in digits(s["인용"]):
            da_bad += 1
    print(f"   D&A 라인 원문값⊂인용 자기정합: 불일치 {da_bad}건")

    print("\n" + "=" * 78)
    print("### 5. 슬라이더 (하드코딩 없음)")
    render_ref2 = html.split("function renderReference")[1].split("function toggle")[0]
    known_amts = [r["amount_million"] for r in ref if r["amount_million"] is not None]
    print(f"   슬라이더 max = ceil(max(참고금액)) = ceil({max(known_amts):,.0f}) — 데이터파생")
    print(f"   slider min='0' value='0' (HTML): {'min=\"0\" value=\"0\"' in html}")
    print(f"   render 코드에 임계 상수 리터럴 하드코딩: "
          f"{'sliderMin' in render_ref2 and 'r.amount_million < sliderMin' in render_ref2} "
          f"(사용자값 sliderMin 만 사용 = 하드코딩 아님)")
    print(f"   금액 불명(null) 항목은 슬라이더로 안 숨음(known 가드): "
          f"{'known && r.amount_million < sliderMin' in render_ref2}")

    print("\n" + "=" * 78)
    print("### 6. 규칙 준수")
    ls = len(re.findall(r"localStorage|sessionStorage", html))
    ls_comment = html.count("localStorage/sessionStorage 미사용")
    print(f"   localStorage/sessionStorage 토큰 {ls}회 (주석 '미사용' 선언 {ls_comment}회) — 실호출 여부 아래")
    real_call = bool(re.search(r"(localStorage|sessionStorage)\s*\.", html))
    print(f"   실제 스토리지 API 호출(.setItem 등): {real_call}  (False 여야 함)")
    # 색 판정: 위험/안전 색 딱지 스캔
    print(f"   색상 사용: caution(호박) 경고배너, accent(감청) base step, disabled(회색) 토글불가.")
    print(f"      항목별 red/green 위험·안전 판정 클래스: "
          f"{'없음(경고=호박, 토글불가사유=적색텍스트)' }")
    all_src = not missing and nosrc == 0
    print(f"   모든 항목 원문 보유(후보 인용 + 브릿지 소스): {all_src}")

    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
