"""재현 안정성(item5)을 의사결정 관점으로: 각 골든 항목이 N회 실행 중 몇 회에서 잡혔나
(같은 유의숫자를 가진 후보가 그 run에 있으면 1회 등장). 낮으면 그 항목의 리콜이 표본수에 취약.
회사별 N(=모든 파일의 run 합)과, 골든 커버리지 분포, 취약(1회만) 항목을 출력한다."""
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATIFIED = ROOT / "golden" / "ratified"
TOOLDIR = ROOT / "out" / "_loop2c2"
STOCKS = ["000660", "003490", "011170"]


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def snums(text):
    out = set()
    for m in re.findall(r"\d[\d,]{3,}", str(text)):
        d = m.replace(",", "")
        if len(d) >= 4 and not (len(d) == 4 and 2015 <= int(d) <= 2027):
            out.add(d)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for stock in STOCKS:
        gd = json.loads((RATIFIED / f"ratified_{stock}.json").read_text(encoding="utf-8"))
        golden = gd["items"]
        name = gd["company"]["corp_name"]
        # run 별 유의숫자 집합
        run_numsets = []
        qlevel_fully = qlevel_total = 0
        for f in sorted(glob.glob(str(TOOLDIR / f"surface_{stock}_*.json"))):
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            rep = d.get("reproducibility", {})
            qlevel_fully += rep.get("fully_stable_count", 0)
            qlevel_total += rep.get("distinct_candidate_count", 0)
            for r in d.get("runs", []):
                s = set()
                for c in r.get("candidates", []):
                    s |= snums(f"{c.get('항목명','')} {c.get('인용','')}")
                run_numsets.append(s)
        N = len(run_numsets)
        cov = Counter()
        fragile = []
        for g in golden:
            gn = snums(g["항목명"] + " " + g["인용"])
            if not gn:
                cov["무숫자골든"] += 1
                continue
            hits = sum(1 for s in run_numsets if gn & s)
            cov[hits] += 1
            if hits <= 1:
                fragile.append((hits, g["항목명"][:38]))
        print(f"\n[{name} {stock}] N={N}회  골든 {len(golden)}건")
        print(f"  골든 커버리지(몇/{N}회에서 잡힘): {dict(sorted(cov.items(), key=lambda x:str(x[0])))}")
        print(f"  인용-레벨 fully_stable(도구 자체): {qlevel_fully}/{qlevel_total}")
        if fragile:
            print(f"  취약(≤1회) 골든:")
            for h, nm in sorted(fragile):
                print(f"     {h}회 · {nm}")


if __name__ == "__main__":
    main()
