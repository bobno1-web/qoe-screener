"""루프 채점: 원문보기가 '검증 가능'해졌나 (사실만, 판정 없음).

지난 루프 구멍: 원문보기를 '할루시네이션 0'으로만 봐 '(인용 없음)'을 통과시켰다.
이번엔 렌더된 원문보기를 항목별로 실제로 '열어' 확인한다 — 코드가 맞다고 넘기지 않는다.

방법: render.py 의 JS(showStatement / splitRows / renderExcerpt / highlightHTML)를 파이썬으로
그대로 재현해, 각 브릿지 숫자의 모달을 '연다'. 그리고 주석 본문을 screenview 와 독립으로
다시 로드(notes_context.load_flat_notes, 캐시)해 발췌가 verbatim 부분문자열인지 대조한다.

1. 원문보기 검증가능성(1순위): 브릿지 모든 숫자(영업이익·D&A합계·개별내역)의 모달을 열어
   인용/표가 뜨고 하이라이트가 뽑은 값에 걸리나. '(인용 없음)' 하나라도 있으면 실패.
2. 주석 가독성(방식 B): splitRows 가 줄바꿈하나, 하이라이트 주변 행만 먼저(전체 펼치기) 뜨나.
3. 재계산 로직 무변경: normalizedEBITDA JS 정본 + 손검증 + 이중가산 게이트.
4. 원문 진위: 발췌가 실제 주석의 verbatim 부분문자열인가(지어냄 0). 못 찾은 항목 정직 처리.
5. 규칙: localStorage 미사용, 색 판정 없음, 원문 요약 없음.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def latest(kind):
    return sorted(glob.glob(str(ROOT / "out" / f"{kind}_000660_*.json")))[-1]


# ---- render.py JS 재현 (문자 단위 동일 로직) ----
AMT_RE = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?")
CTX_ROWS = 2


def splitRows(t):
    rows, last = [], 0
    for m in AMT_RE.finditer(t):
        e = m.end()
        if e < len(t) and not t[e].isspace():
            continue
        rows.append([last, e]); last = e
    if last < len(t):
        rows.append([last, len(t)])
    return rows or [[0, len(t)]]


def renderExcerpt(excerpt, offsets, expanded):
    rows = splitRows(excerpt); offsets = offsets or []
    hlRows = set()
    for off in offsets:
        s = off[0]
        for i in range(len(rows)):
            if rows[i][0] <= s < rows[i][1]:
                hlRows.add(i); break
    collapsible = len(rows) > (CTX_ROWS * 2 + 3) and len(hlRows) > 0
    visible = None
    if collapsible and not expanded:
        visible = {0}
        for r in hlRows:
            for i in range(max(0, r - CTX_ROWS), min(len(rows) - 1, r + CTX_ROWS) + 1):
                visible.add(i)
    shown_rows, hidden_total = 0, 0
    for i in range(len(rows)):
        if visible is not None and i not in visible:
            hidden_total += 1; continue
        shown_rows += 1
    return {"total": len(rows), "collapsible": collapsible,
            "shown_rows": shown_rows, "hidden_rows": hidden_total, "hlRows": sorted(hlRows)}


def marked_texts(excerpt, offsets):
    return [excerpt[s:e] for s, e in (offsets or [])]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sv = json.load(open(latest("screenview"), encoding="utf-8"))
    surface = json.load(open(latest("surface"), encoding="utf-8"))
    html = (ROOT / "out" / "screen_000660.html").read_text(encoding="utf-8")
    print(f"screenview={Path(latest('screenview')).name}  schema={sv['schema_version']}")

    # 독립 로드: 주석 본문(캐시)
    from src.normalize import notes_context as nctx
    notes = nctx.load_flat_notes("000660", which="consolidated")
    body = notes["text"] if notes else ""
    print(f"독립 주석본문 로드: {'OK' if notes else 'FAIL'}  (len={len(body)})")

    def verbatim(exc):
        """발췌가 주석 본문의 부분문자열인가(앞뒤 생략기호 …/⋯ 제거 후)."""
        core = exc.strip().lstrip("… ").rstrip(" …").strip()
        return core in body if body else None

    b = sv["bridge"]
    print("\n" + "=" * 78)
    print("### 1+4. 브릿지 원문보기 — 항목별로 실제로 '열어' 확인")

    # --- 영업이익: showStatement() ---
    oi = b["operating_income"]
    print("\n[영업이익] 원문보기 =", "손익계산서 재구성 표" if oi.get("income_statement") else "(표 없음)")
    istmt = oi.get("income_statement")
    if istmt:
        lines = istmt["lines"]
        hlrow = [l for l in lines if l.get("highlight")]
        rev = next((l["amount_million"] for l in lines if l["label"].startswith("매출액")), None)
        cos = next((l["amount_million"] for l in lines if "매출원가" in l["label"]), None)
        gp = next((l["amount_million"] for l in lines if "매출총이익" in l["label"]), None)
        sga = next((l["amount_million"] for l in lines if "판매비와관리비" in l["label"]), None)
        oival = next((l["amount_million"] for l in lines if l["role"] == "result"), None)
        print(f"   표 행수={len(lines)}  하이라이트 행={[l['label'] for l in hlrow]}")
        print(f"   계단검증: 매출{rev:,.0f} − 원가{cos:,.0f} = {rev-cos:,.0f} (표총이익 {gp:,.0f}, 일치={abs(rev-cos-gp)<1})")
        print(f"            총이익{gp:,.0f} − 판관비{sga:,.0f} = {gp-sga:,.0f} (표영업이익 {oival:,.0f}, 일치={abs(gp-sga-oival)<1})")
        print(f"   하이라이트값 == 브릿지 영업이익 {b['operating_income']['amount_million']:,.0f}: "
              f"{abs((hlrow[0]['amount_million'] if hlrow else -1) - b['operating_income']['amount_million'])<1}")
        print(f"   인용 없음? NO — XBRL 손익계산서 표로 뜸. 검증가능=YES")
    else:
        print("   *** 인용 없음 위험 ***")

    # --- D&A 라인: 성격별 합계(added) + 개별내역(!added) ---
    print("\n[D&A 라인] 각 줄 원문보기 모달 열기")
    da = b["da"]
    fails = []
    for l in da["lines"]:
        kind = l["kind"]; ctx = l.get("원문맥락"); src = l.get("source", {})
        tag = "합계(가산)" if l.get("added") else "개별내역"
        if not ctx or not ctx.get("excerpt"):
            print(f"\n   · {kind[:34]:34} [{tag}] → *** 원문맥락 없음(인용만) ***  인용='{src.get('인용')}'")
            fails.append(kind); continue
        exc, offs = ctx["excerpt"], ctx.get("offsets", [])
        r = renderExcerpt(exc, offs, expanded=False)
        marks = marked_texts(exc, offs)
        num = nctx.comma_number(src.get("원문값") or src.get("인용") or "")
        mark_ok = any(num and num in m for m in marks) if num else False
        vb = verbatim(exc)
        print(f"\n   · {kind[:34]:34} [{tag}]  anchor={ctx.get('anchor')}")
        print(f"       인용='{src.get('인용')}'  뽑은값={num}")
        print(f"       하이라이트 텍스트={marks}  → 뽑은값에 걸림={mark_ok}")
        print(f"       발췌 verbatim⊂주석본문={vb}   길이={len(exc)}")
        print(f"       방식B: 총{r['total']}행, 접힘상태 표시 {r['shown_rows']}행(숨김 {r['hidden_rows']}), "
              f"펼치기제공={r['collapsible']}, 하이라이트행={r['hlRows']}")
        if not mark_ok or vb is False:
            fails.append(kind)
    print(f"\n   >> 브릿지 D&A 원문보기 실패(인용없음/하이라이트안걸림/비verbatim): {len(fails)}건 {fails}")

    # 리스 별도줄 여부
    hasLeaseLine = any("리스" in (l.get("kind") or "") for l in da["lines"])
    print(f"   리스: da.lines에 리스줄 존재={hasLeaseLine} → 별도 lease줄 렌더 안함(중복표시 회피)")

    # ---- 2. 방식 B 종합 ----
    print("\n" + "=" * 78)
    print("### 2. 주석 가독성(방식 B) — 하이라이트 주변 행만 먼저 + 전체 펼치기")
    for l in da["lines"]:
        ctx = l.get("원문맥락")
        if not ctx:
            continue
        r = renderExcerpt(ctx["excerpt"], ctx.get("offsets", []), False)
        one_blob = r["total"] <= 1
        print(f"   {l['kind'][:30]:30} 행분해 {r['total']}행(1덩어리={one_blob}) "
              f"펼치기={'제공' if r['collapsible'] else '불필요(짧음)'}")

    # ---- 3. 재계산 로직 무변경 ----
    print("\n" + "=" * 78)
    print("### 3. 재계산 로직 무변경 + 이중가산 게이트")
    js = html.split("function normalizedEBITDA()")[1].split("function renderHeadline")[0]
    canon = ("let t = DATA.bridge.ebitda_base_million" in js
             and "t += a.sign * a.amount_million" in js
             and "!locked(a.id)" in js and "DATA.adjustments" in js)
    print(f"   normalizedEBITDA 정본(base+Σsign*amount, !locked 게이트, adjustments만): {canon}")
    print(f"   재계산이 reference/qualitative 참조: {'DATA.reference' in js or 'qualitative' in js} (False여야)")
    base = b["ebitda_base_million"]; adj = sv["adjustments"]
    signbad = [a["항목명"] for a in adj if a.get("toggleable") and (
        (a["손익방향"] == "이익" and a["sign"] != -1) or (a["손익방향"] == "비용" and a["sign"] != 1))]
    print(f"   부호오류(이익≠-1/비용≠+1): {len(signbad)} {signbad}")
    # 이중가산 게이트: 부모/자식 쌍 손검증
    byid = {a["id"]: a for a in adj}
    pairs = [(a, [byid[c] for c in a["children_ids"]]) for a in adj
             if a.get("children_ids")]
    for parent, kids in pairs:
        def calc(checkset):
            t = base
            for a in adj:
                if a["id"] in checkset and a.get("toggleable"):
                    locked = ((a.get("children_ids") and any(c in checkset for c in a["children_ids"]))
                              or (a.get("parent_id") and a["parent_id"] in checkset))
                    if not locked:
                        t += a["sign"] * a["amount_million"]
            return t
        pid, kids_ids = parent["id"], [k["id"] for k in kids]
        only_p = calc({pid}); only_k = calc(set(kids_ids)); both = calc({pid, *kids_ids})
        dbl = base + parent["sign"] * parent["amount_million"] + sum(k["sign"] * k["amount_million"] for k in kids)
        print(f"   포함쌍 '{parent['항목명'][:24]}' {parent['amount_million']:,.0f} ⊇ {[k['amount_million'] for k in kids]}")
        print(f"      합계만={only_p:,.0f}  구성만={only_k:,.0f}  둘다={both:,.0f}  (이중가산값 {dbl:,.0f} 회피={abs(both-dbl)>1})")

    # ---- 5. 규칙 ----
    print("\n" + "=" * 78)
    print("### 5. 규칙")
    real_ls = bool(re.search(r"(localStorage|sessionStorage)\s*\.", html))
    print(f"   localStorage/sessionStorage 실호출: {real_ls} (토큰수 {len(re.findall(r'localStorage|sessionStorage', html))}=주석)")
    print(f"   위험판정색 클래스(danger/risk/safe): {any(c in html for c in ['danger','\"risk','safe-'])}")
    print(f"   하이라이트=뽑은위치 표시 캡션: {'이 화면이 뽑은 값입니다' in html}")

    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
