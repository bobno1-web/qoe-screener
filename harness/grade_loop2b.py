"""루프2-b 채점 보조: 리콜(골든셋 42건 중 도구가 몇 건을 실질 매칭했나).

매칭은 '글자 일치'가 아니라 '같은 경제적 사건'. 이 스크립트는 자동 '판정'을 하지 않는다 —
각 골든 항목에 대해 도구 후보들과의 매칭 신호(공유 고유숫자 / 주석번호 / 계정·고유명 토큰 겹침)를
계산해 '후보 매칭'을 제안하고 근거를 덤프한다. 최종 일치/부분/놓침 판정은 사람(채점자)이 한다.

입력:
  golden/ratified/ratified_{stock}.json           (정답 = 사람 승인분)
  out/surface_{corp}_*.json (최신, --with-notes)   (도구 후보; reproducibility.distinct_candidates)
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATIFIED = ROOT / "golden" / "ratified"
OUT = ROOT / "out"

# stock_code -> corp_code (surface 파일명은 corp_code)
CORP = {"000660": "00164779", "003490": "00113526", "011170": "00165413"}


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def salient_numbers(text):
    """콤마 제거한 4자리 이상 숫자열(고유 식별력 있는 금액). 연도(2018~2027)는 제외."""
    nums = set()
    for m in re.findall(r"\d[\d,]{3,}", str(text)):
        d = m.replace(",", "")
        if len(d) >= 4 and not (4 == len(d) and 2015 <= int(d) <= 2027):
            nums.add(d)
    return nums


def note_nums(text):
    return set(re.findall(r"주석\s*(\d+)", str(text)))


_STOP = set("및 관련 손상 차손 이익 손실 인식 하였습니다 대한 등 그 수 및 의 를 을 이 가 은 는 에 로 와 과 당기 전기 연결 회사 실체 기타 영업 비용 수익 평가".split())


def tokens(text):
    """계정·고유명 토큰: 한글 2+음절 덩어리, 영문/숫자 낱말. 흔한 회계 접미어는 약하게."""
    t = str(text)
    toks = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", t):
        if len(w) >= 3:
            toks.add(w.lower())
    for w in re.findall(r"[가-힣]{2,}", t):
        if w not in _STOP and len(w) >= 2:
            toks.add(w)
    return toks


def load_golden(stock):
    d = json.loads((RATIFIED / f"ratified_{stock}.json").read_text(encoding="utf-8"))
    return d["company"]["corp_name"], d["items"]


def load_tool(stock):
    """가용한 모든 도구 실행(--with-notes repeat3)의 distinct 후보를 합집합(인용 정규화 dedup).
    도구가 확률적이므로 리콜은 '도구가 올린 후보 전량' 대비로 잰다(가장 관대)."""
    corp = CORP[stock]
    files = sorted(glob.glob(str(OUT / f"surface_{stock}_*.json")))
    if not files:
        files = sorted(glob.glob(str(OUT / f"surface_{corp}_*.json")))
    if not files:
        return None, [], 0
    union = {}
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for c in d["reproducibility"]["distinct_candidates"]:
            k = norm(c.get("인용")) or norm(c.get("항목명"))
            if k and k not in union:
                union[k] = c
    return f"{len(files)} runs (union)", list(union.values()), len(files)


def match_signals(g, c):
    gq = f"{g.get('항목명','')} {g.get('인용','')}"
    cq = f"{c.get('항목명','')} {c.get('인용','')}"
    gn, cn = salient_numbers(gq), salient_numbers(cq)
    shared_nums = gn & cn
    gnote = note_nums(f"{g.get('주석위치','')} {g.get('인용','')}")
    cnote = note_nums(f"{c.get('주석위치','')} {c.get('인용','')}")
    shared_note = gnote & cnote
    gt, ct = tokens(gq), tokens(cq)
    shared_tok = gt & ct
    # 점수: 고유숫자 공유가 최강, 그다음 고유명 토큰(영문/고유단어), 주석번호는 보조
    score = 0
    score += 100 * len(shared_nums)
    strong_tok = {w for w in shared_tok if re.search(r"[A-Za-z]", w) or len(w) >= 3}
    score += 5 * len(strong_tok)
    score += 2 * len(shared_note)
    return score, {
        "shared_nums": sorted(shared_nums),
        "shared_note": sorted(shared_note),
        "shared_tokens": sorted(shared_tok)[:12],
    }


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    report = {}
    for stock in ["000660", "003490", "011170"]:
        name, golden = load_golden(stock)
        tool_name, cands, nfiles = load_tool(stock)
        rows = []
        for g in golden:
            scored = sorted(((match_signals(g, c)[0], match_signals(g, c)[1], ci)
                             for ci, c in enumerate(cands)), key=lambda x: -x[0])
            best = scored[0] if scored else (0, {}, None)
            bscore, bsig, bci = best
            auto = ("STRONG(number)" if bsig.get("shared_nums")
                    else "TOKENS" if bscore >= 10
                    else "WEAK/none")
            rows.append({
                "golden_항목명": g["항목명"],
                "golden_인용": g["인용"][:70],
                "golden_주석": g.get("주석위치", ""),
                "best_tool_항목명": cands[bci]["항목명"] if bci is not None else None,
                "best_tool_인용": (cands[bci]["인용"][:70]) if bci is not None else None,
                "score": bscore, "auto": auto, "signals": bsig,
            })
        report[stock] = {"company": name, "golden_count": len(golden),
                         "tool_file": tool_name, "tool_cand_count": len(cands), "rows": rows}

    p = ROOT / "harness" / "review" / "_loop2b_match_proposals.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 콘솔 요약(간단)
    for stock, r in report.items():
        strong = sum(1 for x in r["rows"] if x["auto"].startswith("STRONG"))
        toks = sum(1 for x in r["rows"] if x["auto"] == "TOKENS")
        none = sum(1 for x in r["rows"] if x["auto"] == "WEAK/none")
        print(f"[{r['company']} {stock}] 골든 {r['golden_count']}  도구후보 {r['tool_cand_count']}  "
              f"자동:STRONG {strong} / TOKENS {toks} / WEAK {none}   도구파일={r['tool_file']}")
    print(f"\n제안 덤프: {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
