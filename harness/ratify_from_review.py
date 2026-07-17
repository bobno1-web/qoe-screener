"""[2] 사람이 채운 검토표 -> golden/ratified/ (사람 승인분만 정답으로 기록).

사람이 harness/review/review_candidates.csv 의 '판정' 칸을 채워 돌려주면, **'유지'로 표시한 것만**
golden/ratified/ 로 옮긴다. 제외=버림, 보류/빈칸=대기(통과 안 됨). 사람 표시 없이는 아무것도
ratified/ 로 못 들어간다(golden-set-integrity).

- 표의 인용은 잘렸을 수 있으므로, 정답에는 표가 아니라 **golden/drafts/ 의 원본 전체 인용**을 cand_id
  로 되찾아 기록한다(표 훼손이 정답 fidelity 를 못 건드림). id 가 초안에 없으면 STOP(표 위·변조 의심).
- out/ 는 절대 읽지 않는다. 입력은 사람 표 + golden/drafts/ 뿐.
- 안전장치: 기본은 dry-run(무엇이 통과할지 출력만). 실제 기록은 --commit 을 줘야 한다.

준비만 해 둔다. 사람이 표를 채워 오기 전에는 실행하지 않는다.

사용(사람이 표 채운 뒤):
  python harness/ratify_from_review.py            # dry-run: 통과 목록만
  python harness/ratify_from_review.py --commit    # golden/ratified/ 에 기록
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.review_common import DRAFTS_DIR, load_draft_candidates, norm  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_CSV = PROJECT_ROOT / "harness" / "review" / "review_candidates.csv"
RATIFIED_DIR = PROJECT_ROOT / "golden" / "ratified"

KEEP = {"유지", "유지(확정)"}          # 이것만 통과. 그 외(제외/보류/빈칸/오타)는 전부 미통과.
DROP = {"제외", "제외(버림)"}
HOLD = {"보류", "보류(대기)", ""}


def _read_table(path: Path):
    """사람이 편집한 CSV 읽기. Excel(한국 Windows) 인코딩 관용: utf-8-sig -> cp949."""
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            if rows and "id" in rows[0] and "판정" in rows[0]:
                return rows, enc
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit(f"검토표를 읽지 못했습니다(인코딩/컬럼 확인): {path} (STOP)")


def classify(verdict: str) -> str:
    v = norm(verdict)
    if v in KEEP:
        return "keep"
    if v in DROP:
        return "drop"
    if v in HOLD:
        return "hold"
    return "unknown"


def main(argv=None):
    p = argparse.ArgumentParser(description="검토표의 '유지'만 golden/ratified/ 로 기록(사람 승인분).")
    p.add_argument("--table", default=str(REVIEW_CSV))
    p.add_argument("--commit", action="store_true", help="실제 기록(없으면 dry-run)")
    args = p.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    table_path = Path(args.table)
    if not table_path.exists():
        raise SystemExit(f"검토표가 없습니다: {table_path} — 사람이 채운 표가 필요합니다. (STOP)")

    rows, enc = _read_table(table_path)
    by_id = {c["cand_id"]: c for c in load_draft_candidates(DRAFTS_DIR)}

    tally = {"keep": [], "drop": 0, "hold": 0, "unknown": []}
    kept = []
    for r in rows:
        cid = norm(r.get("id"))
        kind = classify(r.get("판정"))
        if kind == "keep":
            if cid not in by_id:
                raise SystemExit(
                    f"'유지'로 표시된 id={cid}(번호 {r.get('번호')})가 golden/drafts/ 에 없습니다 — "
                    f"표가 수정/손상되었을 수 있습니다. 기록 중단. (STOP)")
            tally["keep"].append(cid)
            kept.append(by_id[cid])
        elif kind == "drop":
            tally["drop"] += 1
        elif kind == "hold":
            tally["hold"] += 1
        else:
            tally["unknown"].append((r.get("번호"), r.get("판정")))

    # 회사별로 묶어 기록(정답은 회사별 파일). 원본 전체 인용을 담는다.
    by_company = {}
    for c in kept:
        by_company.setdefault((c["stock_code"], c["corp_name"], c["corp_code"]), []).append(c)

    stamp = datetime.now(timezone.utc).isoformat()
    planned = []
    for (stock, name, corp), items in sorted(by_company.items()):
        recs = [{
            "cand_id": c["cand_id"], "항목명": c["항목명"], "인용": c["인용"],  # 전체 원문
            "주석위치": c["주석위치"], "왜_담았나": c["왜_담았나"], "확신": c["확신"],
            "citation_verbatim_present": c["citation_present"], "source_draft": c["source_draft"],
            "human_verdict": "유지",
        } for c in items]
        out_path = RATIFIED_DIR / f"ratified_{stock}.json"
        planned.append((out_path, name, stock, recs))

    print(f"# ratify_from_review ({'COMMIT' if args.commit else 'DRY-RUN'})  표={table_path.name} enc={enc}")
    print(f"  유지 {len(tally['keep'])} | 제외 {tally['drop']} | 보류/빈칸 {tally['hold']} | "
          f"인식불가 {len(tally['unknown'])}")
    if tally["unknown"]:
        print("  ⚠ 인식 못한 판정값(통과 안 됨 — 오타 확인):")
        for no, v in tally["unknown"]:
            print(f"      번호 {no}: {v!r}")
    for out_path, name, stock, recs in planned:
        print(f"  -> {name}({stock}): 유지 {len(recs)}건 => {out_path.relative_to(PROJECT_ROOT)}")

    if not args.commit:
        print("\n[dry-run] 아무것도 쓰지 않았습니다. 실제 기록은 --commit 을 주세요.")
        return

    if not planned:
        print("\n유지 항목이 없어 기록할 것이 없습니다.")
        return

    RATIFIED_DIR.mkdir(parents=True, exist_ok=True)
    for out_path, name, stock, recs in planned:
        # 재실행 시 기존 정답과 cand_id 로 병합(중복 방지). ratified 안에서만 병합, out/ 무관.
        existing = {}
        if out_path.exists():
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for it in prev.get("items", []):
                existing[it["cand_id"]] = it
        for it in recs:
            existing[it["cand_id"]] = it
        doc = {
            "_kind": "golden-ratified",
            "_purpose": "사람이 '유지'로 승인한 정답. 채점 기준(golden-set-integrity). out/ 무관.",
            "ratified_at": stamp,
            "source": "human review: harness/review/review_candidates.csv (판정=유지)",
            "company": {"stock_code": stock, "corp_name": name},
            "count": len(existing),
            "items": list(existing.values()),
        }
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[written] {out_path.relative_to(PROJECT_ROOT)}  (누적 {len(existing)}건)")


if __name__ == "__main__":
    main()
