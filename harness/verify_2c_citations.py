"""2-c 대역 후보의 인용을 올바른 입력 파일에 독립 대조(할루시네이션 + 교차오염 점검)."""
import glob
import json
import re
import sys
from pathlib import Path

SP = Path(r"C:\Users\gmg97\AppData\Local\Temp\claude\C--Users-gmg97-Desktop-25-26--QOE\7b754a0e-2eb0-489f-952d-f7b121e63343\scratchpad")


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def parse(t):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.S)
    i = t.find("[")
    if i < 0:
        return []
    try:
        return json.loads(t[i:t.rfind("]") + 1])
    except Exception:
        return []


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    tot = badtot = 0
    for stock in ["000660", "003490", "011170"]:
        src = norm((SP / f"input_{stock}.txt").read_text(encoding="utf-8"))
        for f in sorted(glob.glob(str(SP / f"agent_{stock}_r*.json"))):
            arr = parse(Path(f).read_text(encoding="utf-8"))
            bad = []
            for c in arr:
                if not isinstance(c, dict):
                    continue
                q = norm(c.get("인용"))
                if not q or q not in src:
                    bad.append((c.get("항목명"), q[:50]))
            tot += len([c for c in arr if isinstance(c, dict)])
            badtot += len(bad)
            print(f"{Path(f).name}: {len(arr)} cands, {len(bad)} NOT-verbatim")
            for nm, q in bad[:8]:
                print(f"     · {str(nm)[:42]} :: {q!r}")
    print(f"\nTOTAL cands={tot}  not-verbatim={badtot}")


if __name__ == "__main__":
    main()
