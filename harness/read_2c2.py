"""_loop2c2_match.json 을 사람이 판정 가능한 형태로 편다: (1) 리콜 행 압축, (2) 정상화성격 flag
상세, (3) 손상/처분 후보의 두 태그, (4) 하단×조정대상 독립케이스 목록."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.load(open(ROOT / "harness" / "review" / "_loop2c2_match.json", encoding="utf-8"))
sys.stdout.reconfigure(encoding="utf-8")

for stock in ["000660", "003490", "011170"]:
    r = R[stock]
    print(f"\n{'='*70}\n[{r['company']} {stock}] golden={r['golden_count']} distinct={r['distinct_count']}")
    print("--- 리콜 행 (golden → best tool cand, score, 태그) ---")
    for row in r["recall_rows"]:
        sc = row["score"]; sh = row["shared_nums"]
        mark = "OK " if (sh or sc >= 40) else "??"
        print(f" {mark} sc={sc:>4} sh={sh} | {row['golden_항목명'][:34]:34} -> "
              f"[{row['tool_표시위치']}/{row['tool_정상화성격']}] {str(row['tool_항목명'])[:30]}")
    print("--- 정상화성격 flag(기대≠도구) ---")
    for fl in r["nat_flags"]:
        print(f"   도구={fl['도구']} 기대={fl['기대']} ({fl['사유']}) | {fl['항목명']}\n       {fl['인용']}")
    print("--- 표시위치 flag ---")
    for fl in r["pos_flags"]:
        print(f"   도구={fl['도구']} 기대={fl['기대']} | {fl['항목명']}\n       {fl['인용']}")

# 손상/처분 후보의 두 태그(전 회사)
print(f"\n{'='*70}\n[손상·처분 후보의 두 태그 — 표시위치≠정상화성격 확인]")
for stock in ["000660", "003490", "011170"]:
    r = R[stock]
    print(f"\n· {r['company']}")
    for t in r["tagrows"]:
        nm = (t["항목명"] or "") + " " + (t["인용"] or "")
        if re.search(r"손상|처분", nm):
            print(f"   [{t['표시위치']}/{t['정상화성격']}] {str(t['항목명'])[:40]}")

# 독립케이스 요약
print(f"\n{'='*70}\n[하단×조정대상 독립케이스 수]")
for stock in ["000660", "003490", "011170"]:
    r = R[stock]
    print(f" {r['company']}: {len(r['independent_cases'])}  "
          f"예: {[c['항목명'][:24] for c in r['independent_cases'][:6]]}")
