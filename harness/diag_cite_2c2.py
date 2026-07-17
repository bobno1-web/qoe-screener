"""왜 실 도구가 인용 71건을 'not verbatim'으로 flag했나 진단.
각 flagged 인용에 대해: (1) 완전일치? (2) 최장 일치 접두 길이, (3) 원문에서 근처 텍스트."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC_ORDER = ["핵심감사사항", "강조사항", "기타사항", "계속기업 관련 중요한 불확실성"]


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def sec_text(v):
    return v["text"] if isinstance(v, dict) else v


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = sys.argv[1]
    d = json.load(open(f, encoding="utf-8"))
    # 도구가 verify에 쓴 src_norm 재구성: source_text(sections)+ " " + notes_text  (discover.discover 참조)
    # 파일엔 sections 원본이 없다 → runs의 인용을 present=True인 것과 False인 것으로 나눠 성격만 본다.
    flagged, present = [], []
    for r in d["runs"]:
        for c in r["candidates"]:
            cc = c.get("citation_check", {})
            (present if cc.get("present") else flagged).append(c)
    print(f"present={len(present)}  flagged={len(flagged)}")
    print(f"flagged reasons: {dict((lambda l: {x:l.count(x) for x in set(l)})([c['citation_check'].get('reason') for c in flagged]))}")
    print("\n=== flagged 인용 샘플 12 (길이·앞뒤) ===")
    for c in flagged[:12]:
        q = norm(c.get("인용"))
        print(f"\n· [{c.get('항목명')}] len={len(q)}")
        print(f"  인용: {q[:160]}")
    print("\n=== present(정상) 인용 샘플 4 ===")
    for c in present[:4]:
        q = norm(c.get("인용"))
        print(f"· [{c.get('항목명')}] {q[:120]}")


if __name__ == "__main__":
    main()
