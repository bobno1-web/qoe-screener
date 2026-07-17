"""루프2-c-2 채점: 실 도구(대역 아님) 출력으로 (1) 리콜 재현, (2) 분리된 두 태그
(표시위치·정상화성격)의 정확성·독립성, (3) 재현 안정성·할루시네이션을 측정한다.

입력: out/_loop2c2/surface_{stock}_*.json  (실 discover.py --with-notes 출력, schema surface/1)
  - reproducibility.distinct_candidates : 리콜/안정성 (인용 dedup, appeared_in/of_runs)
  - runs[].candidates                    : 표시위치·정상화성격 태그 원본(distinct엔 태그 미보존)
  - hallucination.flagged                : 도구 자체 인용검증(원문에 verbatim 없는 후보)

매칭 규칙: 2-b/2-c와 동일(같은 경제적 사건; 고유숫자/주석/토큰 신호). 자동 판정 아님 — 제안 덤프.
태그 채점은 '기대값 자동산출 vs 도구태그' 불일치를 flag만 하고, 최종 확인은 사람이 인용을 보고 한다.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATIFIED = ROOT / "golden" / "ratified"
TOOLDIR = ROOT / "out" / "_loop2c2"
STOCKS = ["000660", "003490", "011170"]


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def salient_numbers(text):
    nums = set()
    for m in re.findall(r"\d[\d,]{3,}", str(text)):
        d = m.replace(",", "")
        if len(d) >= 4 and not (len(d) == 4 and 2015 <= int(d) <= 2027):
            nums.add(d)
    return nums


def load_golden(stock):
    d = json.loads((RATIFIED / f"ratified_{stock}.json").read_text(encoding="utf-8"))
    return d["company"]["corp_name"], d["items"]


def load_files(stock):
    return sorted(glob.glob(str(TOOLDIR / f"surface_{stock}_*.json")))


def tag_str(v):
    """표시위치/정상화성격 값을 단순 문자열로 정규화(배열/장식 허용)."""
    if isinstance(v, list):
        v = " ".join(str(x) for x in v)
    s = str(v or "")
    for key in ("상단", "하단", "조정대상", "참고", "불명"):
        if key in s:
            return key
    return "무태그" if not s.strip() else s.strip()


def load_tool(stock):
    """2c2 실 도구 출력 파일들을 읽어 (a) 리콜용 distinct 합집합, (b) 태그 레코드(인용별,
    회차별 태그 수집)를 만든다. 반환 (distinct_list, tag_by_quote, meta)."""
    files = load_files(stock)
    distinct = {}          # 인용 -> distinct record (리콜/안정성)
    tags = defaultdict(lambda: {"항목명": None, "주석위치": "", "성격": None,
                                "표시위치": [], "정상화성격": [], "인용": ""})
    total_runs = 0
    hallucinated = []
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        total_runs += d.get("repeat", len(d.get("runs", [])))
        for dc in d.get("reproducibility", {}).get("distinct_candidates", []):
            k = norm(dc.get("인용")) or norm(dc.get("항목명"))
            if not k:
                continue
            if k not in distinct:
                distinct[k] = {"항목명": dc.get("항목명"), "인용": dc.get("인용"),
                               "appeared": 0, "of_runs": 0,
                               "citation_verbatim_present": dc.get("citation_verbatim_present")}
            distinct[k]["appeared"] += dc.get("appeared_in", 0)
            distinct[k]["of_runs"] += dc.get("of_runs", 0)
        for r in d.get("runs", []):
            for c in r.get("candidates", []):
                if not isinstance(c, dict):
                    continue
                k = norm(c.get("인용")) or norm(c.get("항목명"))
                if not k:
                    continue
                t = tags[k]
                t["항목명"] = t["항목명"] or c.get("항목명")
                t["주석위치"] = t["주석위치"] or c.get("주석위치", "")
                t["성격"] = t["성격"] or c.get("성격")
                t["인용"] = t["인용"] or norm(c.get("인용"))
                t["표시위치"].append(tag_str(c.get("표시위치")))
                t["정상화성격"].append(tag_str(c.get("정상화성격")))
                cc = c.get("citation_check") or {}
                if cc.get("present") is False:
                    hallucinated.append({"항목명": c.get("항목명"),
                                         "인용": norm(c.get("인용"))[:80], "reason": cc.get("reason")})
    return list(distinct.values()), dict(tags), {"files": len(files), "total_runs": total_runs,
                                                 "hallucinated": hallucinated}


def best_match(g, cands):
    gq = f"{g.get('항목명','')} {g.get('인용','')}"
    gn = salient_numbers(gq)
    gt = set(re.findall(r"[A-Za-z]{3,}", gq)) | set(re.findall(r"[가-힣]{3,}", gq))
    best = (0, [], None)
    for c in cands:
        cq = f"{c.get('항목명','')} {c.get('인용','')}"
        cn = salient_numbers(cq)
        ct = set(re.findall(r"[A-Za-z]{3,}", cq)) | set(re.findall(r"[가-힣]{3,}", cq))
        shared = gn & cn
        score = 100 * len(shared) + 4 * len(gt & ct)
        if score > best[0]:
            best = (score, sorted(shared), c)
    return best


# ---- 태그 기대값(경제적 계층) 자동산출: flag 용, 최종은 사람 확인 ----
def expected_position(인용, 주석위치, 항목명):
    """표시위치 기대값을 '인용이 어느 계정을 인용했나'로 추정. 판단 근거는 인용 텍스트."""
    t = f"{항목명} {인용} {주석위치}"
    if re.search(r"기타영업외|영업외비용|영업외수익|금융수익|금융비용|금융원가|이자비용|이자수익|"
                 r"지분법|관계기업|공동기업|법인세|중단영업|매각예정|자본잉여|자기주식|기타포괄", t):
        return "하단"
    if re.search(r"매출원가|판매비와관리비|판매관리비|매출액|기타영업수익|기타영업비용|영업이익", t):
        return "상단"
    return "불명"


def expected_nature(항목명, 인용, 주석위치, 성격):
    """정상화성격 기대값: 일회성 경제사건=조정대상 / 시장가·자본거래·세금·경상이자=참고."""
    t = f"{항목명} {인용} {주석위치} {' '.join(성격 or [])}"
    # 참고 성격(정상화 대상 아님)
    if re.search(r"자기주식|자본잉여|주식발행|소각|자본거래", t):
        return "참고", "자본거래"
    if re.search(r"파생|평가손익|공정가치|당기손익-공정가치|매도가능|위험회피|환율변동|외화환산", t) \
            and not re.search(r"손상|처분|매각", t):
        return "참고", "시장가 평가손익"
    if re.search(r"이자비용|이자수익|배당금수익", t) and not re.search(r"손상|처분", t):
        return "참고", "경상 금융손익"
    # 조정대상(일회성 경제사건)
    if re.search(r"손상|처분손익|처분이익|처분손실|매각|사업결합|소송|배상|재해|구조조정|"
                 r"충당부채|우발|합의금|보상금|과징금", t):
        return "조정대상", "일회성 경제사건(손상·처분·소송·사업결합 등)"
    return "불명", "성격 애매"


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    report = {}
    for stock in STOCKS:
        name, golden = load_golden(stock)
        distinct, tags, meta = load_tool(stock)
        # ---- 리콜 ----
        rows = []
        for g in golden:
            score, shared, c = best_match(g, distinct)
            # 태그는 인용 기준으로 tags에서 끌어온다
            tg = tags.get(norm(c.get("인용")) if c else "", {})
            rows.append({
                "golden_항목명": g["항목명"],
                "golden_고유숫자": sorted(salient_numbers(g["항목명"] + " " + g["인용"]))[:4],
                "tool_항목명": c.get("항목명") if c else None,
                "tool_표시위치": Counter(tg.get("표시위치", [])).most_common(1)[0][0] if tg.get("표시위치") else None,
                "tool_정상화성격": Counter(tg.get("정상화성격", [])).most_common(1)[0][0] if tg.get("정상화성격") else None,
                "tool_인용": norm(c.get("인용"))[:90] if c else None,
                "shared_nums": shared, "score": score,
            })
        # ---- 태그 감사(전체 후보) + 교차표(독립성) ----
        crosstab = Counter()
        pos_flags, nat_flags, independent_cases = [], [], []
        tagrows = []
        for k, t in tags.items():
            pos = Counter(t["표시위치"]).most_common(1)[0][0] if t["표시위치"] else "무태그"
            nat = Counter(t["정상화성격"]).most_common(1)[0][0] if t["정상화성격"] else "무태그"
            exp_pos = expected_position(t["인용"], t["주석위치"], t["항목명"] or "")
            exp_nat, nat_why = expected_nature(t["항목명"] or "", t["인용"], t["주석위치"], t["성격"] or [])
            crosstab[(pos, nat)] += 1
            tagrows.append({"항목명": t["항목명"], "성격": t["성격"], "표시위치": pos, "정상화성격": nat,
                            "exp_표시위치": exp_pos, "exp_정상화성격": exp_nat,
                            "주석위치": t["주석위치"], "인용": t["인용"][:90],
                            "표시위치_회차": t["표시위치"], "정상화성격_회차": t["정상화성격"]})
            if exp_pos != "불명" and pos not in ("불명", "무태그") and pos != exp_pos:
                pos_flags.append({"항목명": t["항목명"], "도구": pos, "기대": exp_pos, "인용": t["인용"][:80]})
            if exp_nat != "불명" and nat not in ("불명", "무태그") and nat != exp_nat:
                nat_flags.append({"항목명": t["항목명"], "도구": nat, "기대": exp_nat, "사유": nat_why,
                                  "인용": t["인용"][:80]})
            # 독립성 핵심 케이스: 하단인데 조정대상 (표시≠성격)
            if pos == "하단" and nat == "조정대상":
                independent_cases.append({"항목명": t["항목명"], "성격": t["성격"], "인용": t["인용"][:80]})

        report[stock] = {
            "company": name, "golden_count": len(golden),
            "files": meta["files"], "total_runs": meta["total_runs"],
            "distinct_count": len(distinct), "tagged_count": len(tags),
            "recall_rows": rows,
            "crosstab": {f"{p}×{n}": v for (p, n), v in sorted(crosstab.items())},
            "pos_flags": pos_flags, "nat_flags": nat_flags,
            "independent_cases": independent_cases,
            "hallucinated": meta["hallucinated"],
            "tagrows": tagrows,
        }

    outp = ROOT / "harness" / "review" / "_loop2c2_match.json"
    outp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for stock in STOCKS:
        r = report[stock]
        print(f"\n[{r['company']} {stock}] golden={r['golden_count']} files={r['files']} "
              f"runs={r['total_runs']} distinct={r['distinct_count']} tagged={r['tagged_count']}")
        print(f"  교차표(표시위치×정상화성격): {r['crosstab']}")
        print(f"  독립케이스(하단×조정대상): {len(r['independent_cases'])}  "
              f"표시위치flag={len(r['pos_flags'])}  정상화성격flag={len(r['nat_flags'])}  "
              f"할루시네이션={len(r['hallucinated'])}")
    print(f"\n덤프: {outp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
