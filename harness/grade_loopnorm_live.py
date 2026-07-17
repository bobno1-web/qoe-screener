"""루프 normalize 라이브 채점 (사실만, 판정 없음). 최신 out/ 라이브 산출물 자동 선택.

[B] 재확인 핵심: 이전 fixture 검증에서 '무손실=False, 날조 3건'이 떴는데, 그것이 fixture(실제
surface 후보의 손큐레이션 부분집합 + 인용 재작성)의 아티팩트였는지, 진짜 라이브에서는 해소되는지.
 - 무손실: build_view 는 surface 후보를 회차교차 dedup 후 전원 adjustments∪reference 로 보낸다.
   → dedup 후보수 == len(adj)+len(ref) 여야 하고, 모든 화면후보 키가 surface dedup 키집합에 있어야.
 - 날조: build_view 는 인용을 그대로 복사 → 화면후보 인용이 surface 산출물에 verbatim 존재해야(0건).
또한 discover.py 자체의 hallucination(인용 vs 원문 주석) 카운트도 참고로 같이 본다(별개 지표).
"""
import json
import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"


def latest(kind, stock):
    c = sorted(OUT.glob(f"{kind}_{stock}_*.json"))
    return c[-1] if c else None


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def norm(s):
    return re.sub(r"\s+", "", str(s) if s is not None else "")


def digits(s):
    return re.sub(r"[^0-9]", "", str(s) if s is not None else "")


def cand_key(c):
    return norm(c.get("인용", "")) or norm(c.get("항목명", ""))


def dedupe(surface):
    """build_view.dedupe_candidates 와 동일 규칙: 회차교차 첫 등장 유지."""
    keys, seen_all = [], {}
    for r in surface.get("runs", []):
        seen = set()
        for c in r.get("candidates", []):
            k = cand_key(c)
            if not k or k in seen:
                continue
            seen.add(k)
            if k not in seen_all:
                seen_all[k] = c
                keys.append(k)
    return keys, seen_all


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stock = sys.argv[1] if len(sys.argv) > 1 else "000660"
    sv_p = latest("screenview", stock)
    sv = load(sv_p)
    srcs = sv["meta"]["sources"]
    surface = load(srcs["surface"]) if srcs.get("surface") else None
    eb = load(srcs["ebitda"])
    scr = load(srcs["screen"]) if srcs.get("screen") else None
    html_p = OUT / f"screen_{stock}.html"
    html = html_p.read_text(encoding="utf-8") if html_p.exists() else ""

    base = sv["bridge"]["ebitda_base_million"]
    adj, ref = sv["adjustments"], sv["reference"]
    refunk = sv.get("reference_unknown", [])
    qual = sv.get("reference_qualitative", [])

    def adjchar(x):                     # 조정성격(신규) — 구 산출물 정상화성격도 읽음
        return x.get("조정성격") or x.get("정상화성격")

    print("=" * 78)
    print(f"채점 대상(라이브 자동선택): screenview={sv_p.name}")
    print(f"  sources: surface={Path(srcs['surface']).name if srcs.get('surface') else None}")
    print(f"           ebitda ={Path(srcs['ebitda']).name}")
    print(f"           screen ={Path(srcs['screen']).name if srcs.get('screen') else None}")
    print(f"  surface fixture 여부: {sv['meta'].get('surface_is_fixture')}  (False 여야 라이브)")
    print(f"  surface schema: {sv['meta'].get('surface_schema')}")

    print("\n" + "=" * 78)
    print("### 1. 토글 재계산 정확성 (공식 불변 + 이중가산 방지)")
    print(f"base EBITDA = {base:,.0f} 백만 = 영업이익 {sv['bridge']['operating_income']['amount_million']:,.0f}"
          f" + D&A {sv['bridge']['da']['operating_da_million']:,.0f}")
    byid = {a["id"]: a for a in adj}

    def locked_m(id_, chk):                 # render.py locked() 미러
        a = byid.get(id_)
        if not a:
            return False
        if a.get("children_ids") and any(chk.get(c) for c in a["children_ids"]):
            return True
        if a.get("parent_id") and chk.get(a["parent_id"]):
            return True
        return False

    def norm_m(chk):                        # render.py normalizedEBITDA() 미러(잠금 게이팅 포함)
        t = base
        for a in adj:
            if chk.get(a["id"]) and a.get("toggleable") and not locked_m(a["id"], chk):
                t += a["sign"] * a["amount_million"]
        return t

    sign_err = sum(1 for a in adj if (("-" if a["손익방향"] == "이익" else "+" if a["손익방향"] == "비용" else "?")
                                      != ("-" if a["sign"] * a["amount_million"] < 0 else "+")))
    print(f"  단일토글 부호오류: {sign_err}건")
    # 비-포함관계 항목: 잠금 무관 → tool(잠금미러) == 공식합 이어야
    plain = [a for a in adj if not a.get("parent_id") and not a.get("children_ids")]
    fails = 0
    for r in (2, 3):
        for combo in combinations(plain, r):
            chk = {c["id"]: True for c in combo}
            hand = base + sum(c["sign"] * c["amount_million"] for c in combo if c.get("toggleable"))
            if abs(norm_m(chk) - hand) > 1e-6:
                fails += 1
    print(f"  비포함관계 {len(plain)}건 2·3조합 tool==공식합: 불일치 {fails}건")
    # 합계/구성 이중가산 방지 시연
    totals = [a for a in adj if a.get("is_total")]
    print(f"  합계행 {len(totals)}건 — 이중가산 방지 시연:")
    for P in totals:
        kids = [byid[c] for c in P["children_ids"] if c in byid]
        ksum = sum(k["amount_million"] for k in kids)
        naive = base + P["sign"] * P["amount_million"] + sum(k["sign"] * k["amount_million"] for k in kids)
        only_total = norm_m({P["id"]: True})
        only_kids = norm_m({k["id"]: True for k in kids})
        both = norm_m({**{P["id"]: True}, **{k["id"]: True for k in kids}})
        cap = base + max(P["amount_million"], ksum)
        print(f"    합계 {P['항목명'][:22]} {P['amount_million']:,.0f} ⊃ 구성합 {ksum:,.0f}")
        print(f"      합계만={only_total:,.0f} · 구성만={only_kids:,.0f} · 둘다(잠금)={both:,.0f} · 순진이중가산={naive:,.0f}")
        print(f"      >> 이중가산 방지: 둘다 != 순진 → {abs(both-naive)>1:>1} · 결과 ≤ base+max → {both<=cap+1}")

    print("\n" + "=" * 78)
    print("### 2. 구역 분류 (배치 규칙 교정: B = 표시위치=상단 ∩ 조정대상)")
    # B: 전원 표시위치=상단 && 조정대상
    b_wrong = [a["항목명"] for a in adj if not (a["표시위치"] == "상단" and adjchar(a) == "조정대상")]
    print(f"  B 전원 (상단 ∩ 조정대상): {not b_wrong}  위반={b_wrong}")
    # C 어디에도 상단·조정대상(=B 몫)이 새지 않아야
    leaked = [r["항목명"] for r in ref + refunk + qual
              if r["표시위치"] == "상단" and adjchar(r) == "조정대상"]
    print(f"  C 로 샌 상단·조정대상(있으면 오배치): {leaked or '없음'}")
    # 추정품질 완전 제거
    est_left = [x["항목명"] for x in adj + ref + refunk + qual if "추정품질" in (x.get("성격") or [])]
    print(f"  추정품질 잔존(전 구역): {est_left or '없음'}  · 추정품질제외 카운트={sv['meta'].get('excluded_estimation')}")
    # 손상/처분 항목 배치 — 하단은 전부 C 여야
    for x in adj + ref + refunk:
        if any(k in (x["항목명"] or "") for k in ("손상", "처분")):
            zone = "B" if x in adj else ("C불명" if x in refunk else "C참고")
            print(f"    [{zone}] 표시위치={x['표시위치']} 조정성격={adjchar(x)} · {x['항목명'][:36]}")

    print("\n" + "=" * 78)
    print("### 3. [B] 무손실 + 날조 재확인 (병합 인지)")
    allrows = adj + ref + refunk + qual
    if surface is None:
        print("  surface 없음 — 스킵")
    else:
        keys, seen_all = dedupe(surface)
        n_runs = len(surface.get("runs", []))
        raw_counts = [len(r.get("candidates", [])) for r in surface.get("runs", [])]
        print(f"  surface runs={n_runs} 각 후보수={raw_counts} · dedup 후 distinct={len(keys)}")
        print(f"  병합 후 행수: B {len(adj)} + C참고 {len(ref)} + C불명 {len(refunk)} + C정성 {len(qual)} = {len(allrows)}")
        # 병합 무손실(교정): 화면행 + 추정품질 의도적 제외 = dedup distinct (제외분은 merged_count 로 대사)
        tot_merged = sum(r.get("merged_count", 1) for r in allrows)
        excl_merged = sv["meta"].get("excluded_estimation_merged", 0)
        lossless = (tot_merged + excl_merged) == len(keys)
        print(f"  >> 무손실(화면 Σ {tot_merged} + 추정품질제외 {excl_merged} == dedup {len(keys)}): {lossless}  (True 여야)")
        print(f"     병합으로 {len(keys)-excl_merged} → {len(allrows)} 행(중복 통합), 추정품질 {excl_merged}건 범위밖 제외")
        # 날조: 대표행 인용이 surface 산출물 인용에 verbatim
        surface_quotes = {norm(c.get("인용", "")) for r in surface["runs"] for c in r["candidates"]}
        fab = [x["항목명"] for x in allrows if norm(x.get("인용", "")) not in surface_quotes]
        print(f"  >> 날조(대표행 인용 ∉ surface인용): {len(fab)}건  {fab}  (0 여야 함)")
        # 참고: discover.py 자체 hallucination(인용 vs 원문 주석)
        h = surface.get("hallucination", {})
        print(f"  참고) discover.py hallucination.flagged_count={h.get('flagged_count')} "
              f"(인용 vs 원문 주석 검증 — /·… 합성인용 형식 아티팩트 포함, 숫자단위 아님)")

    print("\n" + "=" * 78)
    print("### 4. 데이터 통합 무결성 (통합 vs 원본 out/)")
    def chk(nm, a, b):
        print(f"  {nm:14} view={a:>18,}  src={b:>18,}  일치={a==b}")
    chk("영업이익", sv["bridge"]["operating_income"]["amount_won"], eb["operating_income"]["amount_won"])
    chk("D&A 가산", sv["bridge"]["da"]["operating_da_won"], eb["da"]["operating_da_won"])
    chk("EBITDA base", sv["bridge"]["ebitda_base_won"], eb["ebitda"]["amount_won"])
    if scr:
        sp, ss = sv["screen_panel"], scr["screen"]
        print(f"  screen_panel 누적영업이익 일치={sp['cumulative_operating_income']==ss['cumulative_operating_income']}"
              f" · 누적영업현금 일치={sp['cumulative_operating_cash_flow']==ss['cumulative_operating_cash_flow']}")
    # D&A 라인 원문값⊂인용 자기정합
    da_bad = 0
    for ln in sv["bridge"]["da"]["lines"]:
        s = ln.get("source") or {}
        if s.get("원문값") and s.get("인용") and digits(s["원문값"]) not in digits(s["인용"]):
            da_bad += 1
    print(f"  D&A 라인 원문값⊂인용 자기정합: 불일치 {da_bad}건")
    if html:
        i = html.find("const DATA = ")
        j = html.find("\n// ---- state", i)
        dtxt = html[i + len("const DATA = "):j].rstrip().rstrip(";")
        same = json.dumps(json.loads(dtxt), sort_keys=True, ensure_ascii=False) == json.dumps(sv, sort_keys=True, ensure_ascii=False)
        print(f"  HTML 인라인 DATA == screenview JSON(무손실): {same}")

    print("\n" + "=" * 78)
    print("### 5. 원문보기 + 규칙")
    missing = [x["항목명"] for x in allrows if not (x.get("인용") or "").strip()]
    print(f"  후보 전원 인용 존재(B+C숫자+C정성): {not missing}  누락={missing}")
    # 원문맥락(#5) 부착률
    withctx = sum(1 for x in allrows if x.get("원문맥락"))
    print(f"  원문맥락 부착: {withctx}/{len(allrows)}개 후보 · 브릿지 D&A라인 "
          f"{sum(1 for l in sv['bridge']['da']['lines'] if l.get('원문맥락'))}/{len(sv['bridge']['da']['lines'])}")
    bridge_srcs = [sv["bridge"]["operating_income"].get("source")] + \
                  [ln.get("source") for ln in sv["bridge"]["da"]["lines"]]
    nosrc = sum(1 for s in bridge_srcs if not s)
    print(f"  브릿지 원문소스 없음: {nosrc}개")
    if html:
        real_call = bool(re.search(r"(localStorage|sessionStorage)\s*\.", html))
        print(f"  실제 스토리지 API 호출: {real_call}  (False 여야)")
        print(f"  slider min/value 0 (데이터파생 max): {'min=\"0\" value=\"0\"' in html}")

    print("\n" + "=" * 78)
    print("### 6. 원문보기 검증가능성 (갈래1 손익계산서 · 갈래2 방식B 줄바꿈)")
    # 갈래1: 영업이익 원문보기 = 손익계산서 계단, 뽑은 줄 하이라이트, 자기검산
    isv = sv["bridge"]["operating_income"].get("income_statement")
    print(f"  [갈래1] income_statement 존재: {isv is not None}  (True 여야 — '(인용 없음)' 대체)")
    if isv:
        by = {l["concept"]: l["amount_won"] for l in isv["lines"]}
        hl = [l for l in isv["lines"] if l["highlight"]]
        oi_match = len(hl) == 1 and hl[0]["amount_won"] == sv["bridge"]["operating_income"]["amount_won"]
        print(f"    라인 {len(isv['lines'])}개 · 하이라이트 1개 && ==영업이익: {oi_match}")
        gp = by.get("ifrs-full_Revenue", 0) - by.get("ifrs-full_CostOfSales", 0)
        oi = by.get("ifrs-full_GrossProfit", 0) - by.get("dart_TotalSellingGeneralAdministrativeExpenses", 0)
        a1 = gp == by.get("ifrs-full_GrossProfit")
        a2 = oi == by.get("dart_OperatingIncomeLoss")
        print(f"    자기검산: 매출-매출원가=매출총이익 {a1} · 매출총이익-판관비=영업이익 {a2}")
    if html:
        print(f"    HTML: showStatement 함수 {'showStatement()' in html} · 영업이익 버튼 연결 "
              f"{'onclick=\"showStatement()\"' in html}")

    # 갈래2: 방식B 줄바꿈 미러 — 내용 불변(join==원문) + 하이라이트가 행 안에 · 다행 분해
    amt_re = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?")

    def split_rows(t):
        rows, last = [], 0
        for m in amt_re.finditer(t):
            e = m.end()
            if e < len(t) and not t[e].isspace():
                continue
            rows.append([last, e]); last = e
        if last < len(t):
            rows.append([last, len(t)])
        return rows or [[0, len(t)]]

    excerpts = []
    for x in allrows:
        c = x.get("원문맥락")
        if c and c.get("excerpt"):
            excerpts.append((x["항목명"], c))
    for ln in sv["bridge"]["da"]["lines"]:
        c = ln.get("원문맥락")
        if c and c.get("excerpt"):
            excerpts.append((ln.get("kind"), c))
    verbatim_ok = hl_in_row = multi = 0
    for _, c in excerpts:
        ex = c["excerpt"]; rows = split_rows(ex)
        if "".join(ex[s:e] for s, e in rows) == ex:
            verbatim_ok += 1
        if len(rows) >= 2:
            multi += 1
        ok = all(any(s <= o[0] < e for s, e in rows) for o in (c.get("offsets") or []))
        if ok:
            hl_in_row += 1
    n = len(excerpts)
    print(f"  [갈래2] 발췌 {n}개 — 내용 불변(join==원문) {verbatim_ok}/{n} · "
          f"하이라이트 행 매핑 {hl_in_row}/{n} · 다행 분해 {multi}/{n}")
    if html:
        print(f"    HTML: splitRows {'function splitRows' in html} · "
              f"전체펼치기 버튼 {'전체 주석 펼치기' in html} · 발췌 pre-wrap 제거 "
              f"{'.excerpt .exrow' in html}")

    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
