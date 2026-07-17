"""루프 채점: 이중가산 방지가 실제로 막는가 + 검증 재계산 무변경 (사실만).

포함관계 탐지는 '표 산술'로 교체됐다(비율/임계 폐기). 방어는 계층(합계·구성) 모델이다:
합계 체크 → 구성 자동 체크·잠김(합계로 일괄 반영), 구성 개별 체크 → 합계 안 됨(부분 조정).
합계=구성 합이 산술로 확정돼 합계와 구성이 함께 Σ 에 드는 이중가산은 산술적으로 불가능하다.

1. 이중가산 방지(1순위): render.js 의 locked()+normalizedEBITDA()+propagate() 를 파이썬으로 이식,
   자동(구역 B)+수동(구역 C 불명) 모든 체크상태를 전수 시뮬 → '합계+구성 동시 반영' 경로 0 인지.
2. 포함관계 판정: 합계=구성 합 산술이 정확히 성립하나(잔여='그 외'로 닫힘) / 억지묶기 없나 /
   산술 확정 못 한 근접쌍은 잠금 대신 경고 배지인가(놓친 이중가산 없나).
3. 재계산 공식 무변경: 잠기지 않은 항목 재계산이 base+Σsign*amount 그대로인가(게이팅이 공식 불변).
4. 태그 우선순위 / 5. 하이라이트 / 6. 규칙.
"""
import glob
import itertools
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


# ---- render.js 재계산 로직 파이썬 이식(계층 모델) ----
def rawon(aid, checked, manual):
    return bool(checked.get(aid) or (manual.get(aid) or {}).get("on"))


def locked(aid, checked, manual, byid):
    a = byid.get(aid)                          # 계층: 구성은 부모(합계)가 켜지면 잠긴다. 합계는 계층으로 안 잠김.
    return bool(a and a.get("parent_id") and rawon(a["parent_id"], checked, manual))


def eff_dir(r, manual):
    if r.get("손익방향") in ("이익", "비용"):
        return r["손익방향"]
    return (manual.get(r["id"]) or {}).get("dir")


def man_sign(dr):
    return -1 if dr == "이익" else (1 if dr == "비용" else None)


def normalized(base, adj, refu, checked, manual, byid):
    t = base
    for a in adj:
        if checked.get(a["id"]) and a.get("toggleable") and not locked(a["id"], checked, manual, byid):
            t += a["sign"] * a["amount_million"]
    for r in refu:
        st = manual.get(r["id"]) or {}
        s = man_sign(eff_dir(r, manual))
        if st.get("on") and r.get("amount_million") is not None and s is not None \
                and not locked(r["id"], checked, manual, byid):
            t += s * r["amount_million"]
    return t


def set_on(aid, val, checked, manual, manual_ids):
    if aid in manual_ids:
        manual.setdefault(aid, {"on": False, "dir": None})["on"] = val
    else:
        checked[aid] = val


def propagate(aid, on, checked, manual, byid, manual_ids):
    a = byid.get(aid)                          # 합계 on/off → 구성 전부 따라감. 잠금이 Σ 중복 방지.
    if a and a.get("children_ids"):
        for c in a["children_ids"]:
            set_on(c, on, checked, manual, manual_ids)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sv = json.loads(Path(latest("screenview")).read_text(encoding="utf-8"))
    print(f"screenview={Path(latest('screenview')).name}  schema={sv['schema_version']}")
    adj = sv["adjustments"]
    refu = sv.get("reference_unknown", [])
    base = sv["bridge"]["ebitda_base_million"]
    pool = adj + refu
    byid = {a["id"]: a for a in pool}
    manual_ids = {r["id"] for r in refu}
    print(f"base EBITDA={base:,.0f}  구역B {len(adj)}건 · 구역C불명 {len(refu)}건  "
          f"합계행={sv['meta'].get('containment_totals')}  경고쌍={sv['meta'].get('containment_warn')}  "
          f"태그우선={sv['meta'].get('tag_priority_count')}")

    totals = [a for a in pool if a.get("is_total")]
    t1 = [a for a in totals if not a.get("containment_estimated")]   # 1단계 표 산술 확정
    t2 = [a for a in totals if a.get("containment_estimated")]       # 2단계 고근접 추정
    print("\n" + "=" * 80)
    print(f"### 1. 이중가산 방지 — 1단계(산술) {len(t1)} · 2단계(추정) {len(t2)} · 3단계(경고) {sv['meta'].get('containment_warn')} (계층 모델)")
    for P in t1:
        ar = P.get("containment_arithmetic", {})
        print(f"\n  [1·산술] 합계 {P['항목명'][:28]} id={P['id']} 금액={P['amount_million']:,.0f} [산술 {ar.get('equation')} · {ar.get('note')}]")
        for k in (byid[c] for c in P["children_ids"] if c in byid):
            tag = "그 외(계산값)" if k.get("computed_residual") else "구성"
            print(f"    └ {tag} {k['항목명'][:24]} id={k['id']} 금액={k['amount_million']:,.0f}")
    for P in t2:
        m = P.get("containment_estimated_meta", {})
        print(f"\n  [2·추정] 합계 {P['항목명'][:26]} id={P['id']} 금액={P['amount_million']:,.0f} "
              f"[근접 {m.get('ratio', 0) * 100:.2f}% · 성격 {m.get('nature')} · 해제 가능]")
        for k in (byid[c] for c in P["children_ids"] if c in byid):
            print(f"    └ 구성 {k['항목명'][:24]} id={k['id']} 금액={k['amount_million']:,.0f} 잔여없음={not k.get('computed_residual')}")

    # (A) raw 상태 전수: 자동 B(on/off) × 수동 C(off/on×방향) 강제 — 잠금 게이팅만으로 이중가산 0 인지
    Bitems = [a for a in adj if a.get("toggleable")]
    Uitems = [r for r in refu if r.get("amount_million") is not None]

    def dopts(r):
        return [r["손익방향"]] if r.get("손익방향") in ("이익", "비용") else ["이익", "비용"]

    ustate = [[("off", None)] + [("on", dv) for dv in dopts(r)] for r in Uitems]
    dbl, combos = 0, 0
    for Bs in itertools.product([False, True], repeat=len(Bitems)):
        for Us in itertools.product(*ustate):
            checked, manual = {}, {}
            for a, on in zip(Bitems, Bs):
                checked[a["id"]] = on
            for r, (mode, dv) in zip(Uitems, Us):
                manual[r["id"]] = {"on": mode == "on", "dir": dv}
            combos += 1
            contrib = set()
            for a in adj:
                if checked.get(a["id"]) and a.get("toggleable") and not locked(a["id"], checked, manual, byid):
                    contrib.add(a["id"])
            for r in refu:
                st = manual.get(r["id"]) or {}
                if st.get("on") and r.get("amount_million") is not None \
                        and man_sign(eff_dir(r, manual)) is not None and not locked(r["id"], checked, manual, byid):
                    contrib.add(r["id"])
            for P in totals:
                if P["id"] in contrib and any(c in contrib for c in P.get("children_ids", [])):
                    dbl += 1
    print(f"\n  raw 전수 {combos:,}조합 · '합계+구성 동시 Σ 반영' 경로: {dbl}  (0이어야 함)")

    # (B) 계층 규칙: 합계 체크→구성 잠김·Σ 1회, 구성 전부 개별=합계값(이중 아님)
    for P in totals:
        kids = P["children_ids"]
        ck, mn = {}, {}
        set_on(P["id"], True, ck, mn, manual_ids)
        propagate(P["id"], True, ck, mn, byid, manual_ids)
        e_total = normalized(base, adj, refu, ck, mn, byid)
        allkids_locked = all(locked(c, ck, mn, byid) for c in kids)
        ck2, mn2 = {}, {}
        for c in kids:
            set_on(c, True, ck2, mn2, manual_ids)
        e_kids = normalized(base, adj, refu, ck2, mn2, byid)
        auto = rawon(P["id"], ck2, mn2)
        print(f"  합계 {P['id']}: 합계만 EBITDA={e_total:,.0f} · 구성전부 EBITDA={e_kids:,.0f} "
              f"→ 동일={abs(e_total - e_kids) < 1e-6}  구성전부잠김(합계시)={allkids_locked}  구성→합계자동체크={auto}(F여야)")

    # ---- 2. 포함관계 판정(산술 정확성 / 억지묶기 / 놓침) ----
    print("\n" + "=" * 80)
    print("### 2. 포함관계 판정 — 표 산술 정확성(1단계) / 추정 근거(2단계)")
    for P in t1:
        ar = P.get("containment_arithmetic", {})
        named = [byid[c] for c in P["children_ids"] if c in byid and not byid[c].get("computed_residual")]
        resid = [byid[c] for c in P["children_ids"] if c in byid and byid[c].get("computed_residual")]
        s = sum(BV._num_mag(k["amount_display"]) for k in named) + sum(BV._num_mag(r["amount_display"]) for r in resid)
        print(f"  [1] 합계 {ar.get('total'):,} = 확인구성 {sum(BV._num_mag(k['amount_display']) for k in named):,} "
              f"+ 그외 {sum(BV._num_mag(r['amount_display']) for r in resid):,} → 산술 닫힘={s == ar.get('total')}")
    for P in t2:
        m = P.get("containment_estimated_meta", {})
        no_resid = not any(byid[c].get("computed_residual") for c in P["children_ids"] if c in byid)
        print(f"  [2] 추정 {P['amount_million']:,.0f} — 근접 {m.get('ratio', 0) * 100:.2f}% · 성격계열 동일 {bool(m.get('nature'))} · "
              f"잔여('그 외') 안 만듦={no_resid} · 사용자 해제 가능")
    # 놓친 포함/억지묶기 독립 재확인: 같은 부호 근접쌍(≥90%) 중 확정도 경고도 아닌 게 있나(=조용한 위험)
    print("  -- 산술 미확정 근접쌍(잠금X): 경고 배지가 붙었나(놓친 이중가산 0) --")
    warned_ids = {c["id"] for c in pool if c.get("containment_warn")}
    confirmed = {c["id"] for c in pool if c.get("is_total") or c.get("parent_id")}
    silent = 0
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = pool[i], pool[j]
            if not (a.get("amount_won") and b.get("amount_won")) or a.get("sign") != b.get("sign"):
                continue
            lo, hi = sorted((a["amount_won"], b["amount_won"]))
            if hi and lo / hi >= 0.90:
                covered = (a["id"] in confirmed and b["id"] in confirmed) or \
                          (a["id"] in warned_ids and b["id"] in warned_ids)
                if not covered:
                    silent += 1
                    print(f"     <<조용한 근접쌍(잠금·경고 다 없음): {a['항목명'][:20]}({a['amount_won']:,}) "
                          f"~ {b['항목명'][:20]}({b['amount_won']:,})")
    print(f"  조용한 근접쌍(잠금·경고 모두 없는 이중가산 위험): {silent}  (0이어야 함)")

    # ---- 3. 재계산 공식 무변경 ----
    print("\n" + "=" * 80)
    print("### 3. 재계산 공식 무변경(잠금은 게이트일 뿐)")
    html = (ROOT / "out" / "screen_000660.html").read_text(encoding="utf-8")
    js = html.split("function normalizedEBITDA()")[1].split("function renderHeadline")[0]
    print(f"   공식 base+Σsign*amount 유지: {'ebitda_base_million' in js and 't += a.sign * a.amount_million' in js}")
    print(f"   추가 게이트 !locked(a.id) 만: {'!locked(a.id)' in js}")
    free = [a for a in adj if a.get("toggleable") and not a.get("is_total") and not a.get("parent_id")]
    ck = {a["id"]: True for a in free}
    e_free = normalized(base, adj, [], ck, {}, byid)
    pure = base + sum(a["sign"] * a["amount_million"] for a in free)
    print(f"   비포함 {len(free)}건 전부체크: 도구={e_free:,.0f} 순수공식={pure:,.0f} 일치={abs(e_free - pure) < 1e-6}")
    signbad = [a["항목명"] for a in pool if a.get("toggleable") and a.get("손익방향") and (
        (a["손익방향"] == "이익" and a["sign"] != -1) or (a["손익방향"] == "비용" and a["sign"] != 1))]
    print(f"   부호오류: {len(signbad)} {signbad}")

    # ---- 4. 태그 우선순위 ----
    print("\n" + "=" * 80)
    print("### 4. 태그 우선순위(확정>불명)")
    surface = json.loads(Path(latest("surface")).read_text(encoding="utf-8"))
    two = str(surface.get("schema_version", "")).startswith("surface/2")
    distinct, n = BV.dedupe_candidates(surface)
    rows = [BV._row_from_cand(c, two) for c in distinct]
    groups = {}
    for r in rows:
        groups.setdefault(BV._merge_key(r), []).append(r)
    applied = overwrite = 0
    for k, g in groups.items():
        if len(g) < 2:
            continue
        defs = [BV._definite(r) for r in g]
        if len(set(defs)) > 1:
            applied += 1
            rep = max(g, key=lambda r: (BV._definite(r), len(r["_runs"]), len(r.get("인용") or "")))
            if BV._definite(rep) != max(defs):
                overwrite += 1
    print(f"   태그우선 적용(확정≠불명 그룹): {applied}  meta보고={sv['meta'].get('tag_priority_count')}")
    print(f"   확정을 불명으로 덮은 오류: {overwrite}  (0이어야 함)")

    # ---- 5. 하이라이트 ----
    print("\n" + "=" * 80)
    print("### 5. 하이라이트")
    notes = nctx.load_flat_notes(sv["company"]["corp_code"]) if os.environ.get("OPENDART_API_KEY") else None
    allitems = adj + sv["reference"] + refu + sv.get("reference_qualitative", [])
    if notes:
        amt_hl = amt_no = 0
        for x in allitems:
            ctx = x.get("원문맥락")
            if not ctx or not ctx.get("excerpt") or x.get("amount_won") is None or x.get("computed_residual"):
                continue
            disp = nctx.comma_number(x.get("amount_display"))
            marked = " || ".join(ctx["excerpt"][s:e] for s, e in (ctx.get("offsets") or []))
            hit = disp and disp in marked
            amt_hl += 1 if hit else 0
            amt_no += 0 if hit else 1
        print(f"   금액항목 하이라이트: 성공 {amt_hl}, 실패 {amt_no}")
    else:
        print("   (OPENDART 키 없음 — 하이라이트 재현 생략)")

    # ---- 6. 규칙 ----
    print("\n" + "=" * 80)
    print("### 6. 규칙")
    print(f"   localStorage 실호출: {bool(re.search(r'(localStorage|sessionStorage)[.]', html))}")
    print(f"   위험색 클래스(danger/safe/risk): {('danger' in html or 'safe' in html or 'risk' in html)}")
    print(f"   비율/임계 탐지 잔존(build_view): {'_best_subset' in (ROOT / 'src/normalize/build_view.py').read_text(encoding='utf-8')}")
    print(f"   그 외(도구 계산값) 원문 인용 구분: {'computed_residual' in html}")
    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
