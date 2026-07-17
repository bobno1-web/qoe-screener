"""골든셋 범위 정합 후 리콜 재측정 (사실만, 판정 없음).

세 회사(SK 000660·대한항공 003490·롯데 011170)의 ratified 를 in-scope 만 분모로 삼아
라이브/최신 surface distinct 후보와 매칭(숫자 우선, 키워드 보조 — grade_loopE2E 와 동일 규칙).
out-of-scope(추정품질·세금·자본거래) 항목은 분모에서 빠지므로 도구가 안 잡아도 리콜 손실이 아니다
— 그 항목을 도구가 잡았는지도 참고로 같이 보고한다.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
COMPANIES = [("000660", "SK하이닉스"), ("003490", "대한항공"), ("011170", "롯데케미칼")]


def digits_set(s, minlen=4):
    return {d.replace(",", "") for d in re.findall(r"\d[\d,]{%d,}" % (minlen - 1), s or "")
            if len(d.replace(",", "")) >= minlen}


def toks(s):
    return set(re.findall(r"[가-힣A-Za-z]{2,}", s or ""))


def latest_surface(stock):
    c = sorted(OUT.glob(f"surface_{stock}_*.json"))
    return c[-1] if c else None


def match(g, live):
    """golden 항목 g 가 live 후보에 있나. 반환 ('숫자'|'키워드'|None)."""
    gnums = digits_set(g.get("인용", ""))
    gtok = toks(g["항목명"])
    for c in live:
        if gnums and (gnums & c["nums"]):
            return "숫자"
    for c in live:
        common = gtok & c["tok"]
        strong = {t for t in common if len(t) >= 3 or re.match(r"[A-Za-z]", t)}
        if len(common) >= 2 or strong:
            return "키워드"
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 82)
    print("### 골든셋 범위 정합 후 리콜 재측정 (in-scope 분모, 숫자 우선·키워드 보조)")
    tot_in = tot_hit = 0
    for stock, name in COMPANIES:
        gp = ROOT / "golden" / "ratified" / f"ratified_{stock}.json"
        sp = latest_surface(stock)
        if not gp.exists() or sp is None:
            print(f"\n[{stock} {name}] 골든/서피스 없음 — 스킵")
            continue
        gold = json.loads(gp.read_text(encoding="utf-8"))
        surf = json.loads(sp.read_text(encoding="utf-8"))
        distinct = surf.get("reproducibility", {}).get("distinct_candidates", [])
        live = [{"nums": digits_set(d.get("인용", "")),
                 "tok": toks((d.get("항목명") or "") + " " + (d.get("인용") or ""))} for d in distinct]

        in_scope = [g for g in gold["items"] if g.get("scope") != "out_of_scope"]
        out_scope = [g for g in gold["items"] if g.get("scope") == "out_of_scope"]

        hit = miss = 0
        miss_list = []
        for g in in_scope:
            if match(g, live):
                hit += 1
            else:
                miss += 1
                miss_list.append(g["항목명"][:34])
        tot_in += len(in_scope)
        tot_hit += hit
        print(f"\n[{stock} {name}]  surface distinct={len(distinct)} ({surf.get('schema_version')})")
        print(f"  in-scope 분모 {len(in_scope)} (out-of-scope {len(out_scope)}건 제외) · 검출 {hit}/{len(in_scope)} · 미검출 {miss}")
        if miss_list:
            print(f"    미검출(in-scope): {miss_list}")
        # out-of-scope 항목: 도구가 잡았는지 참고(안 잡아도 리콜 손실 아님)
        for g in out_scope:
            caught = match(g, live)
            cat = g.get("scope_category", "?")
            tag = "도구가 잡음(무관)" if caught else "도구 미검출(범위 밖이라 손실 아님)"
            print(f"    out[{cat}] {g['항목명'][:30]} → {tag}")

    print("\n" + "=" * 82)
    print(f"### 전체 in-scope 리콜: {tot_hit}/{tot_in}  ({100*tot_hit/tot_in:.0f}%)  (사실 — 판정 없음)")


if __name__ == "__main__":
    main()
