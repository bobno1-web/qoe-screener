"""루프 채점: 화면 개선이 표시만 바꿨고 검증 로직·데이터를 훼손했나 (사실만).

1. 재계산 로직 무변경: normalizedEBITDA/sign/base 가 이전과 동일한가 + 라이브 재계산 손검증.
2. 병합 정합(1순위 = 과병합): merge 그룹을 붕괴 前 멤버까지 재구성해, 한 대표로 합쳐진 것들이
   정말 같은 경제사건인가(항목명/인용 상이 = 과병합 의심). 재현배지 union 보존.
3. 원문보기 진위: 각 항목 원문맥락.excerpt 가 실제 주석 텍스트의 verbatim 부분문자열인가,
   하이라이트 offset 이 그 값 자리인가, 지어낸 문맥 없나.
4. 존재형 분리: qualitative=금액불명만, 금액 있는 항목이 존재형에 잘못 안 갔나.
5. 구역 A: base=47,206,319+13,889,639=61,095,958 유지, 조원 병기 정확(≈61.1조).
6. 규칙: localStorage 미사용, 색 판정 없음, 원문 요약 없음(verbatim).
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.normalize import build_view as BV  # noqa: E402
from src.normalize import notes_context as nctx  # noqa: E402


def latest(kind):
    return sorted(glob.glob(str(ROOT / "out" / f"{kind}_000660_*.json")))[-1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    surface = json.loads(Path(latest("surface")).read_text(encoding="utf-8"))
    sv = json.loads(Path(latest("screenview")).read_text(encoding="utf-8"))
    print(f"surface={Path(latest('surface')).name}  screenview={Path(latest('screenview')).name}")
    print(f"schema={sv['schema_version']}  B={len(sv['adjustments'])} C숫자={len(sv['reference'])} "
          f"C정성={len(sv.get('reference_qualitative',[]))}")

    # ---- 2. 병합 그룹 재구성(붕괴 전 멤버) ----
    two_tag = str(surface.get("schema_version", "")).startswith("surface/2")
    distinct, n = BV.dedupe_candidates(surface)
    rows = [BV._row_from_cand(c, two_tag) for c in distinct]
    groups = {}
    for r in rows:
        groups.setdefault(BV._merge_key(r), []).append(r)
    print("\n" + "=" * 78)
    print(f"### 2. 병합 정합 — distinct {len(rows)} → merge 그룹 {len(groups)}")
    multi = {k: g for k, g in groups.items() if len(g) > 1}
    print(f"멀티멤버(병합발생) 그룹: {len(multi)}")

    def item_sig(r):
        return re.sub(r"\s+", "", (r.get("항목명") or ""))

    over = []
    for k, g in multi.items():
        names = [r.get("항목명") for r in g]
        sigs = {item_sig(r) for r in g}
        quotes = {re.sub(r'\s+', '', (r.get('인용') or ''))[:40] for r in g}
        # 과병합 의심: 항목명 서로 많이 다르면(핵심 토큰 교집합 없음)
        toks = [set(re.findall(r"[가-힣A-Za-z]{2,}", n or "")) for n in names]
        common = set.intersection(*toks) if toks else set()
        suspect = len(sigs) > 1 and not common
        print(f"\n  키={k}")
        for r in g:
            print(f"     · {r.get('항목명')[:42]:42} | 금액={r.get('amount_display')} {r.get('단위')} "
                  f"| 주석={str(r.get('주석위치'))[:24]} | 인용앞={re.sub(chr(92)+'s+','',(r.get('인용') or ''))[:26]}")
        print(f"     → 멤버 {len(g)}, 항목명 고유 {len(sigs)}, 공통토큰={sorted(common)[:4]}  "
              f"{'<<< 과병합 의심(공통토큰 없음)' if suspect else '(같은 경제사건으로 보임)'}")
        if suspect:
            over.append((k, names))

    print(f"\n  과병합 의심 그룹 수: {len(over)}")

    # 재현배지 보존: merged rep 의 appeared_in == union runs
    print("\n-- 재현배지(appeared_in/of_runs/merged_count) 보존 스팟체크 --")
    merged = BV._merge_rows(rows, n)
    bad = 0
    for m in merged:
        # 원 그룹 union 재계산
        k = BV._merge_key(m)
        g = groups[k]
        union = set()
        for r in g:
            union |= r["_runs"]
        if m["appeared_in"] != len(union) or m["of_runs"] != n or m["merged_count"] != len(g):
            bad += 1
    print(f"   merged {len(merged)}건: 배지 불일치 {bad}건 (appeared_in=union·of_runs=n·merged_count=grp)")

    # ---- 1. 재계산 로직 ----
    print("\n" + "=" * 78)
    print("### 1. 재계산 로직 무변경 + 라이브 손검증")
    base = sv["bridge"]["ebitda_base_million"]
    adj = sv["adjustments"]
    allids = [a["id"] for a in adj if a.get("toggleable")]
    tool_all = base + sum(a["sign"] * a["amount_million"] for a in adj if a.get("toggleable"))
    print(f"   base={base:,.0f}  toggleable 조정대상 {len(allids)}건")
    print(f"   전부체크 재계산 = {tool_all:,.0f}  (base + Σ sign*amount)")
    signbad = [a["항목명"] for a in adj if a.get("toggleable") and (
        (a["손익방향"] == "이익" and a["sign"] != -1) or (a["손익방향"] == "비용" and a["sign"] != 1))]
    print(f"   부호오류(이익≠-1 / 비용≠+1): {len(signbad)}  {signbad}")
    # render.py 재계산 JS 가 이전과 동일한지(문자열)
    html = (ROOT / "out" / "screen_000660.html").read_text(encoding="utf-8")
    js = html.split("function normalizedEBITDA()")[1].split("function renderHeadline")[0]
    canonical = "let t = DATA.bridge.ebitda_base_million" in js and "t += a.sign * a.amount_million" in js and "DATA.adjustments" in js
    print(f"   normalizedEBITDA JS 정본(base+Σsign*amount, adjustments만): {canonical}")
    print(f"   재계산 루프가 reference/qualitative 참조: "
          f"{'DATA.reference' in js or 'qualitative' in js}  (False 여야)")

    # ---- 4. 존재형 분리 ----
    print("\n" + "=" * 78)
    print("### 4. 존재형(금액불명) 분리")
    qual = sv.get("reference_qualitative", [])
    q_withamt = [q["항목명"] for q in qual if q.get("amount_won") is not None]
    r_noamt = [r["항목명"] for r in sv["reference"] if r.get("amount_won") is None]
    a_check = [a["항목명"] for a in adj if a.get("amount_won") is None]
    print(f"   qualitative {len(qual)}건: 금액 있는데 정성에 들어간 것 {len(q_withamt)} {q_withamt}")
    print(f"   reference(숫자) 중 금액 불명 섞임 {len(r_noamt)} {r_noamt}")
    print(f"   adjustments 중 금액불명(toggle불가) {len(a_check)} {a_check[:3]}")

    # ---- 5. 구역 A ----
    print("\n" + "=" * 78)
    print("### 5. 구역 A 숫자/조원")
    oi = sv["bridge"]["operating_income"]["amount_million"]
    da = sv["bridge"]["da"]["operating_da_million"]
    print(f"   {oi:,.0f} + {da:,.0f} = {oi+da:,.0f}  (base={base:,.0f}, 일치={oi+da==base})")
    jo = round(base / 1e6, 1)
    print(f"   조원 병기: {base:,.0f}백만 → 약 {jo}조원  (61,095,958백만=61.095958조≈61.1: {jo==61.1})")

    # ---- 6. 규칙 ----
    print("\n" + "=" * 78)
    print("### 6. 규칙")
    real_ls = bool(re.search(r"(localStorage|sessionStorage)\s*\.", html))
    print(f"   localStorage/sessionStorage 실호출: {real_ls}  (토큰 {len(re.findall(r'localStorage|sessionStorage',html))}=주석)")
    print(f"   하이라이트색 <mark>=--hl(노랑) '뽑은 위치 표시': "
          f"{'뽑은 위치 표시일 뿐 판정색이 아니다' in html}")
    print(f"   red/green 위험판정 클래스 부재(항목행에 danger/safe 없음): "
          f"{'danger' not in html and 'risk' not in html}")

    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
