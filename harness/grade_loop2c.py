"""루프2-c 채점 보조: 개선 프롬프트 리콜 재측정 + 신규 태그(성격·EBITDA구분) 추출.

- 도구 후보는 out/_loop2c/surface_{stock}_*.json (신 프롬프트, --with-notes)에서 읽는다.
- distinct_candidates 는 태그를 안 보존하므로 runs[].candidates 원본을 합집합(인용 dedup)해
  성격·EBITDA구분·회색지대_근거 태그까지 보존한다.
- 매칭 규칙은 2-b와 동일(같은 경제적 사건; 고유숫자/주석/고유명 신호). 자동 판정 아님 — 제안 덤프.
- 이전(2-b) 놓친 10건이 이번에 잡히는지 개별 추적.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATIFIED = ROOT / "golden" / "ratified"
# 대역(서브에이전트)로 개선 프롬프트를 실행한 출력 디렉토리 (실 API 크레딧 소진으로 도구 직접실행 불가).
TOOLDIR = Path(r"C:\Users\gmg97\AppData\Local\Temp\claude\C--Users-gmg97-Desktop-25-26--QOE\7b754a0e-2eb0-489f-952d-f7b121e63343\scratchpad")
CORP = {"000660": "00164779", "003490": "00113526", "011170": "00165413"}

# 2-b에서 놓친 항목(회복 추적용): (stock, 식별 고유숫자 or 키워드)
PREV_MISSED = [
    ("000660", "자기주식처분이익", "4,313,106"),
    ("000660", "자기주식 소각(보고기간후사건)", "15,300,000"),
    ("000660", "금융자산처분이익", "187,868"),
    ("000660", "기부금", "84,884"),
    ("000660", "세액공제 발생액", "5,262,773"),
    ("000660", "소송·특허 클레임 우발부채(포괄)", "지적재산권"),
    ("000660", "Wuxi 지배력 상실·공동기업투자 인식(전기)", "지배력을 상실"),
    ("000660", "SkyHigh 콜옵션 행사(부분)", "콜옵션"),
    ("003490", "이연수익(마일리지) 추정 변경", "마일리지"),
    ("011170", "롯데에너지머티리얼즈 지분53.3% 취득(사업결합)", "2,537,698"),
]


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def salient_numbers(text):
    nums = set()
    for m in re.findall(r"\d[\d,]{3,}", str(text)):
        d = m.replace(",", "")
        if len(d) >= 4 and not (4 == len(d) and 2015 <= int(d) <= 2027):
            nums.add(d)
    return nums


def load_golden(stock):
    d = json.loads((RATIFIED / f"ratified_{stock}.json").read_text(encoding="utf-8"))
    return d["company"]["corp_name"], d["items"]


def _parse_array(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    i = t.find("[")
    if i == -1:
        return []
    depth = instr = esc = 0
    for j in range(i, len(t)):
        ch = t[j]
        if instr:
            if esc: esc = 0
            elif ch == "\\": esc = 1
            elif ch == '"': instr = 0
        elif ch == '"': instr = 1
        elif ch == "[": depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[i:j + 1])
                except Exception:
                    return []
    return []


def load_tool(stock):
    """개선 프롬프트를 대역 실행한 회차별 파일(agent_{stock}_r*.json)을 합집합(인용 dedup), 태그 보존."""
    files = sorted(glob.glob(str(TOOLDIR / f"agent_{stock}_r*.json")))
    if not files:
        return None, [], 0
    union = {}
    for f in files:
        arr = _parse_array(Path(f).read_text(encoding="utf-8"))
        for c in arr:
            if not isinstance(c, dict):
                continue
            k = norm(c.get("인용")) or norm(c.get("항목명"))
            if k and k not in union:
                union[k] = c
    return f"{len(files)} agent-runs (union)", list(union.values()), len(files)


def best_matches(g, cands, topk=3):
    gq = f"{g.get('항목명','')} {g.get('인용','')}"
    gn = salient_numbers(gq)
    scored = []
    for c in cands:
        cq = f"{c.get('항목명','')} {c.get('인용','')}"
        cn = salient_numbers(cq)
        shared = gn & cn
        # 토큰(영문/고유단어)
        gt = set(re.findall(r"[A-Za-z]{3,}", gq)) | set(re.findall(r"[가-힣]{3,}", gq))
        ct = set(re.findall(r"[A-Za-z]{3,}", cq)) | set(re.findall(r"[가-힣]{3,}", cq))
        st = gt & ct
        score = 100 * len(shared) + 4 * len(st)
        scored.append((score, sorted(shared), c))
    scored.sort(key=lambda x: -x[0])
    return scored[:topk]


def expected_ebitda(항목명, 인용, 주석위치):
    """태그 1차 자동판정(경제적 계층). 반환 (기대구분, 사유). 최종은 사람 판정."""
    t = f"{항목명} {인용} {주석위치}"
    # 하단(EBITDA 밖): 금융·투자·세금·자본·중단영업
    if re.search(r"관계기업|공동기업|종속기업투자|지분법", t) and re.search(r"손상|처분", t):
        return "하단", "투자자산(지분법/종속기업) 손상·처분 = 영업외"
    if re.search(r"금융수익|금융비용|금융원가|이자|파생상품|금융상품평가|배당금수익|금융자산처분", t):
        return "하단", "금융손익 = 영업이익 아래"
    if re.search(r"법인세|세액공제|최저한세|이연법인세", t):
        return "하단", "세금 = 영업이익 아래"
    if re.search(r"자기주식|자본잉여|주식발행|소각", t):
        return "하단", "자본거래 = 영업이익 아래"
    if re.search(r"중단영업|매각예정", t):
        return "하단", "중단영업/매각예정 = 영업이익 아래"
    # 상단(EBITDA 영향): 영업자산 손상·상각, 매출원가/재고, 인건비
    if re.search(r"유형자산손상|무형자산손상|사용권자산손상|영업권 ?손상|현금창출단위", t) and "투자" not in t:
        return "상단", "영업자산(유형·무형·영업권·CGU) 손상 = EBITDA 계층"
    if re.search(r"재고자산|평가손실환입|운휴자산상각|과거근무원가", t):
        return "상단", "매출원가·영업비용 계층"
    return "불명", "자동판정 보류(사람 확인)"


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    report = {}
    for stock in ["000660", "003490", "011170"]:
        name, golden = load_golden(stock)
        tool_name, cands, n_runs = load_tool(stock)
        rows = []
        for g in golden:
            bm = best_matches(g, cands)
            top = bm[0] if bm else (0, [], None)
            score, shared, c = top
            rows.append({
                "golden_항목명": g["항목명"],
                "golden_고유숫자": sorted(salient_numbers(g["항목명"] + " " + g["인용"]))[:4],
                "best_tool_항목명": (c.get("항목명") if c else None),
                "best_tool_성격": (c.get("성격") if c else None),
                "best_tool_EBITDA구분": (c.get("EBITDA구분") if c else None),
                "best_tool_인용": (norm(c.get("인용"))[:80] if c else None),
                "shared_nums": shared, "score": score,
            })
        report[stock] = {"company": name, "golden_count": len(golden),
                         "tool_file": tool_name, "n_runs": n_runs,
                         "tool_cand_count": len(cands), "rows": rows,
                         "all_tool": [{"항목명": c.get("항목명"), "성격": c.get("성격"),
                                       "EBITDA구분": c.get("EBITDA구분"),
                                       "주석위치": c.get("주석위치", ""),
                                       "인용": norm(c.get("인용"))[:80]} for c in cands]}

    # ---- 태그 1차 자동감사: EBITDA구분 오분류 후보 ----
    tag_flags = {}
    for stock, r in report.items():
        flags = []
        for c in r["all_tool"]:
            exp, why = expected_ebitda(c.get("항목명", ""), c.get("인용", ""), c.get("주석위치", ""))
            got = str(c.get("EBITDA구분") or "").strip()
            got_simple = "상단" if "상단" in got else ("하단" if "하단" in got else ("불명" if got else "무태그"))
            if exp != "불명" and got_simple not in ("불명", "무태그") and got_simple != exp:
                flags.append({"항목명": c.get("항목명"), "성격": c.get("성격"),
                              "도구태그": got_simple, "기대": exp, "사유": why})
        tag_flags[stock] = flags
    report["_tag_audit"] = tag_flags

    p = ROOT / "harness" / "review" / "_loop2c_match.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for stock, r in report.items():
        if stock.startswith("_"):
            continue
        print(f"[{r['company']} {stock}] 골든 {r['golden_count']}  "
              f"도구후보 {r['tool_cand_count']} (runs={r['n_runs']})  파일={r['tool_file']}  "
              f"태그오분류(자동) {len(tag_flags.get(stock, []))}")
    print(f"덤프: {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
