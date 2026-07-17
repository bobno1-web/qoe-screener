"""날조 판정의 결정적 기준: flagged 인용 속 '유의 숫자'가 모두 원문에 있나.
숫자가 하나라도 원문에 없으면 진짜 날조 의심. 전부 있으면 flag는 형식(합성·주석) 아티팩트."""
import json
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.surface import discover as D  # noqa: E402


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def salient_nums(text):
    out = []
    for m in re.findall(r"\d[\d,]{2,}", str(text)):
        d = m.replace(",", "")
        if len(d) >= 3 and not (len(d) == 4 and 2015 <= int(d) <= 2027):
            out.append(m)
    return out


def num_in_src(m, src, src_nocomma):
    # 원문에 콤마형(97,688) 또는 무콤마형(97688) 둘 중 하나로 있으면 존재.
    return (m in src) or (m.replace(",", "") in src_nocomma)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stock, f = sys.argv[1], sys.argv[2]
    args = types.SimpleNamespace(corp_code=None, stock_code=stock, name=None, with_notes=True)
    sections, company, meta, notes_text = D._collect_live(args)
    src = D._norm_ws(D.source_text(sections) + " " + (notes_text or ""))
    src_nocomma = src.replace(",", "")

    d = json.load(open(f, encoding="utf-8"))
    flagged, present_cnt = [], 0
    seen = set()
    for r in d["runs"]:
        for c in r["candidates"]:
            if c.get("citation_check", {}).get("present"):
                present_cnt += 1
                continue
            q = norm(c.get("인용"))
            if q in seen:
                continue
            seen.add(q)
            flagged.append(c)

    quotes_with_missing_num = []
    total_nums = missing_nums = 0
    for c in flagged:
        q = norm(c.get("인용"))
        nums = salient_nums(q)
        miss = [m for m in nums if not num_in_src(m, src, src_nocomma)]
        total_nums += len(nums)
        missing_nums += len(miss)
        if miss:
            quotes_with_missing_num.append((c.get("항목명"), miss, q[:100]))

    print(f"src_norm_len={len(src)}  present={present_cnt}  flagged_distinct={len(flagged)}")
    print(f"flagged 인용 속 유의숫자 총 {total_nums}개 중 원문에 없는 것 {missing_nums}개")
    print(f"숫자가 하나라도 없는 flagged 인용 수: {len(quotes_with_missing_num)} / {len(flagged)}")
    print("\n=== 원문에 없는 숫자를 가진 인용(진짜 날조 의심) ===")
    if not quotes_with_missing_num:
        print("  (없음) — 모든 flagged 인용의 숫자가 원문에 존재 → flag는 형식(합성·주석) 아티팩트")
    for nm, miss, q in quotes_with_missing_num:
        print(f"· [{nm}] 없는숫자={miss}\n    {q}")


if __name__ == "__main__":
    main()
