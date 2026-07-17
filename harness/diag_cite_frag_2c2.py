"""flagged 인용이 '조각 합성(composite)'인지 '진짜 날조(fabrication)'인지 가른다.
도구와 동일 경로로 원문(sections+notes)을 재구성(결정론적, LLM 없음)하고, flagged 인용을
' / ' 와 ' ... ' 로 쪼갠 조각들이 원문에 개별적으로 verbatim 존재하는지 검사한다."""
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


def build_src(stock):
    args = types.SimpleNamespace(corp_code=None, stock_code=stock, name=None, with_notes=True)
    sections, company, meta, notes_text = D._collect_live(args)
    src = D._norm_ws(D.source_text(sections) + " " + (notes_text or ""))
    return src


def frags(q):
    # 모델이 조각을 잇는 구분자: ' / ', ' ... ', '...', '  '
    parts = re.split(r"\s*/\s*|\s*\.\.\.\s*|\s*…\s*", q)
    out = []
    for p in parts:
        p = norm(re.sub(r"\(전기[:：].*?\)", "", p))  # 모델 주석 '(전기: ...)' 제거 후 검사
        p = norm(re.sub(r"\(수익\)|\(비용\)", "", p))
        if len(p) >= 4:
            out.append(p)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stock = sys.argv[1]
    f = sys.argv[2]
    src = build_src(stock)
    print(f"src_len(norm)={len(src)}")
    d = json.load(open(f, encoding="utf-8"))
    flagged = []
    seen = set()
    for r in d["runs"]:
        for c in r["candidates"]:
            if c.get("citation_check", {}).get("present"):
                continue
            q = norm(c.get("인용"))
            if q in seen:
                continue
            seen.add(q)
            flagged.append(c)

    composite_ok = whole_ok = genuine = 0
    genuine_list = []
    for c in flagged:
        q = norm(c.get("인용"))
        if q in src:
            whole_ok += 1
            continue
        fr = frags(q)
        missing = [p for p in fr if p not in src]
        if fr and not missing:
            composite_ok += 1
        else:
            genuine += 1
            genuine_list.append((c.get("항목명"), missing[:2], q[:90]))
    print(f"flagged distinct={len(flagged)}")
    print(f"  whole_present_after_our_norm={whole_ok}")
    print(f"  composite(all fragments present)={composite_ok}")
    print(f"  GENUINE missing fragments={genuine}")
    print("\n=== 진짜 원문에 없는 조각을 가진 후보 ===")
    for nm, miss, q in genuine_list:
        print(f"· [{nm}] missing={miss}\n    인용:{q}")


if __name__ == "__main__":
    main()
