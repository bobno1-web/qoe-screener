"""루프2-a 채점기: surface (1) 재현안정성 (2) 인용진위(할루시네이션) (3) 스키마 (4) 규칙.

이 단계는 리콜을 재지 않는다(골든셋 전). "맞는 후보인가"는 채점하지 않는다.
정답 없이 잴 수 있는 것만 잰다.

독립성: 도구가 out/ 에 낸 reproducibility/hallucination 블록을 그대로 믿지 않고,
여기서 원문 대조·겹침·스키마를 다시 계산한 뒤 도구 블록과 교차대조한다.

입력:
  - harness/surface_inputs/aekyung_161000_sections.json  (원문=모델입력)
  - harness/surface_inputs/_runs/run{0,1,2}.json           (모델 원문 응답 3회; opus 서브에이전트 대역)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS_FILE = ROOT / "harness" / "surface_inputs" / "aekyung_161000_sections.json"
RUNS_DIR = ROOT / "harness" / "surface_inputs" / "_runs"
DISCOVER = ROOT / "src" / "surface" / "discover.py"

REQUIRED = ["항목명", "인용", "주석위치", "비반복성_근거", "근거강도", "조정대상_소계", "item_type"]
ALLOWED = {
    "근거강도": {"명시", "추정", "해당없음"},
    "조정대상_소계": {"영업이익", "영업외손익", "세전이익", "중단영업", "불명", "해당없음"},
    "item_type": {"존재형", "발굴형"},
}
# 판정성(단정) 라벨 스캔 — 프롬프트는 '판정 아님/후보만'을 요구. 이런 단정 표현이 섞이면 위반.
JUDGMENT_MARKERS = ["확실히", "확실한", "확정적", "틀림없", "명백히 일회성", "일회성임", "일회성이다",
                    "반드시 일회성", "확실히 일회성", "단정", "definitely", "certainly one-off"]


def norm_ws(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def load_source_norm():
    raw = json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))
    order = ["핵심감사사항", "강조사항", "기타사항", "계속기업 관련 중요한 불확실성"]
    sec = raw["sections"]
    return norm_ws("\n".join(sec[n] for n in order if n in sec)), raw


def parse_array(text):
    """모델 원문에서 JSON 배열을 독립 파싱(도구 코드 미사용)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    i = t.find("[")
    if i == -1:
        return None
    depth = 0
    instr = esc = False
    for j in range(i, len(t)):
        c = t[j]
        if instr:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                instr = False
        elif c == '"':
            instr = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(t[i:j + 1])
    return None


def load_runs():
    runs = []
    for f in sorted(RUNS_DIR.glob("run*.json")):
        txt = f.read_text(encoding="utf-8")
        runs.append((f.name, parse_array(txt) or []))
    return runs


def jaccard_sets(sets):
    inter = set.intersection(*sets) if sets else set()
    union = set.union(*sets) if sets else set()
    return len(inter), len(union), (len(inter) / len(union) if union else 0.0)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    src_norm, raw_fx = load_source_norm()
    runs = load_runs()
    n = len(runs)
    print(f"# 루프2-a 채점  회사={raw_fx['company']['corp_name']}({raw_fx['company']['stock_code']}), 회차={n}")
    print(f"  원문(정규화) 길이: {len(src_norm)}자   섹션: {list(raw_fx['sections'].keys())}\n")

    # ---- item 2: 인용 진위 (독립 대조) ----
    print("## item2 할루시네이션(인용 진위, 독립 대조)")
    halluc = []
    per_run_counts = []
    for name, cands in runs:
        cnt = 0
        for c in cands:
            q = norm_ws(c.get("인용"))
            present = bool(q) and (q in src_norm)
            if not present:
                halluc.append((name, c.get("항목명"), c.get("인용"),
                               "no_quote" if not q else "quote_not_in_source"))
            cnt += 1
        per_run_counts.append(cnt)
    print(f"  회차별 후보수: {per_run_counts}")
    print(f"  원문에 없는 인용(할루시네이션) 개수: {len(halluc)}")
    for name, item, quote, why in halluc:
        print(f"    - [{name}] {item} :: {why} :: {quote!r}")
    print()

    # ---- item 1: 재현 안정성 (독립 겹침) ----
    print("## item1 재현 안정성(겹침, 독립 계산)")
    quote_sets = [set(norm_ws(c.get("인용")) for c in cands if norm_ws(c.get("인용"))) for _, cands in runs]
    name_sets = [set(norm_ws(c.get("항목명")) for c in cands if norm_ws(c.get("항목명"))) for _, cands in runs]
    for label, sets in (("인용키", quote_sets), ("항목명키", name_sets)):
        inter, union, jac = jaccard_sets(sets)
        pair = []
        for a, b in combinations(range(n), 2):
            pu = len(sets[a] | sets[b])
            pair.append(len(sets[a] & sets[b]) / pu if pu else 0.0)
        mean_pair = sum(pair) / len(pair) if pair else 0.0
        print(f"  [{label}] 3회 전체교집합={inter} 합집합={union} "
              f"Jaccard(∩3/∪)={jac:.4f}  평균쌍별Jaccard={mean_pair:.4f}")
        # 각 distinct 후보가 몇/3 회 등장
        allkeys = set().union(*sets) if sets else set()
        appear = {k: sum(1 for st in sets if k in st) for k in allkeys}
        dist = sorted(appear.values(), reverse=True)
        print(f"      distinct={len(allkeys)}  등장분포(회/3)={dist}")
    print()

    # ---- item 3: 스키마 준수 (독립) ----
    print("## item3 스키마 준수(독립 검사)")
    schema_fail = []
    for name, cands in runs:
        for idx, c in enumerate(cands):
            miss = [f for f in REQUIRED if f not in c]
            if miss:
                schema_fail.append((name, idx, c.get("항목명"), f"필드누락:{miss}"))
            for field, allowed in ALLOWED.items():
                if field in c and str(c[field]) not in allowed:
                    schema_fail.append((name, idx, c.get("항목명"),
                                        f"{field} 허용밖 값='{c[field]}'"))
            blob = " ".join(str(v) for v in c.values())
            hits = [m for m in JUDGMENT_MARKERS if m in blob]
            if hits:
                schema_fail.append((name, idx, c.get("항목명"), f"판정성 표현: {hits}"))
    print(f"  스키마/판정성 위반 개수: {len(schema_fail)}")
    for name, idx, item, why in schema_fail:
        print(f"    - [{name}] #{idx} {item} :: {why}")
    print()

    # ---- 도구 파이프라인 교차대조 (도구를 --mock 로 실행, 자기보고 블록 vs 독립계산) ----
    print("## 도구 파이프라인 교차대조 (discover.py --mock, 자기보고 vs 독립)")
    mock = RUNS_DIR / "_mock3.json"
    mock.write_text(json.dumps([f.read_text(encoding="utf-8") for f in sorted(RUNS_DIR.glob("run*.json"))],
                               ensure_ascii=False), encoding="utf-8")
    tmp_out = RUNS_DIR / "_toolout"
    tmp_out.mkdir(exist_ok=True)
    before = set(tmp_out.glob("surface_*.json"))
    r = subprocess.run([sys.executable, str(DISCOVER), "--sections-file", str(SECTIONS_FILE),
                        "--mock", str(mock), "--repeat", "3", "--out-dir", str(tmp_out)],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("  도구 실행 실패:\n", r.stderr[-1500:])
        return
    newf = sorted(set(tmp_out.glob("surface_*.json")) - before)
    tool = json.loads((newf[-1] if newf else sorted(tmp_out.glob('surface_*.json'))[-1]).read_text(encoding="utf-8"))
    trep = tool["reproducibility"]
    thal = tool["hallucination"]
    print(f"  도구 자기보고: distinct={trep['distinct_candidate_count']} "
          f"fully_stable={trep['fully_stable_count']}/{trep['total_runs']} "
          f"할루시네이션flagged={thal['flagged_count']}")
    # 독립 대조: 도구 flagged_count == 나의 halluc 개수?
    print(f"  독립 계산   : 할루시네이션={len(halluc)}  "
          f"(도구와 {'일치' if thal['flagged_count'] == len(halluc) else '불일치'})")
    # 도구 fully_stable == 인용키 전체교집합?
    inter_q, union_q, _ = jaccard_sets(quote_sets)
    print(f"  도구 fully_stable_count={trep['fully_stable_count']} vs 독립 인용키 전체교집합={inter_q} "
          f"({'일치' if trep['fully_stable_count'] == inter_q else '주의: 키 기준 상이 가능'})")


if __name__ == "__main__":
    main()
