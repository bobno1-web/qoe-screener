"""[1] 초안 후보 -> 사람 O/X 검토표 (판단 없음, 변환만).

golden/drafts/ 의 초안 후보를 회사별로 묶어, 후보 적은 회사부터(SK하이닉스처럼 많은 회사는 맨 뒤)
표로 뽑는다. 사람은 '판정' 칸에 유지/제외/보류 를 적는다. 인용은 원문 그대로 싣되 너무 길면
문장 경계까지만 자른다(자르기만, 훼손·요약 금지). 원문 전체는 golden/drafts/ 에 그대로 남아 있고
cand_id 로 되찾으므로, 표의 잘린 인용이 정답 fidelity 를 해치지 않는다.

산출물은 harness/review/ 에 둔다(golden/ 아님 — 아직 정답 아니고 사람이 편집 중인 작업물).
  - review_candidates.csv        <- 사람이 '판정' 칸을 채워 돌려주는 정본(Excel 편집용, UTF-8 BOM)
  - review_candidates_preview.md <- 읽기용 미리보기(편집은 CSV 에)

사용: python harness/build_review_table.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.review_common import (  # noqa: E402
    DRAFTS_DIR, company_counts, conf_rank, load_draft_candidates, norm,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = PROJECT_ROOT / "harness" / "review"
CSV_PATH = REVIEW_DIR / "review_candidates.csv"
MD_PATH = REVIEW_DIR / "review_candidates_preview.md"

COLUMNS = ["id", "번호", "회사", "항목명", "인용", "왜_담았나", "확신", "인용검증", "판정"]
_ENDERS = ("습니다.", "입니다.", "였습니다.", "합니다.", "이다.", "다.", ".")


def clip_quote(q: str, limit: int = 180):
    """원문을 자르기만 한다(단어 변형 없음). 문장 경계 우선, 없으면 한계에서 하드컷. 반환 (표시문자열, 잘림?)."""
    q = q.strip()
    if len(q) <= limit:
        return q, False
    head = q[:limit]
    cut = -1
    for e in _ENDERS:
        idx = head.rfind(e)
        if idx != -1:
            cut = max(cut, idx + len(e))
    if cut < int(limit * 0.4):     # 쓸만한 경계 없음 -> 한계에서 자름
        cut = limit
    kept = q[:cut].rstrip()
    return kept, True


def _sorted_rows(cands):
    counts = company_counts(cands)
    # 회사: 후보 적은 순(SK하이닉스처럼 많은 회사는 맨 뒤). 동수는 회사명.
    comp_order = sorted(counts, key=lambda k: (counts[k], k[1]))
    rows = []
    n = 0
    for key in comp_order:
        stock, name = key
        group = [c for c in cands if (c["stock_code"], c["corp_name"]) == key]
        group.sort(key=lambda c: (conf_rank(c["확신"]),))   # 확신 높은 것부터
        for c in group:
            n += 1
            disp, clipped = clip_quote(c["인용"])
            rows.append({
                "id": c["cand_id"],
                "번호": n,
                "회사": name or stock,
                "항목명": c["항목명"],
                "인용": disp + (" […]" if clipped else ""),   # 잘림 마커(정본·미리보기 일관). 남긴 단어는 원문 그대로.
                "_인용_잘림": clipped,
                "왜_담았나": c["왜_담았나"],
                "확신": c["확신"],
                "인용검증": "verbatim확인" if c["citation_present"] else "⚠원문미확인",
                "판정": "",
            })
    return rows, counts, comp_order


def write_csv(rows):
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _md_cell(s: str) -> str:
    # 미리보기 렌더 전용: 줄바꿈->공백, 파이프 이스케이프(원문 CSV 는 훼손 없음).
    return norm(s).replace("|", r"\|")


def write_md(rows, counts, comp_order):
    lines = []
    lines.append("# 골든셋 후보 검토표 (읽기용 미리보기)\n")
    lines.append("- **편집은 이 파일이 아니라 `review_candidates.csv` 에서.** (여기 인용은 줄바꿈·파이프가 렌더용으로 손질됨)")
    lines.append("- '판정' 칸에 **유지 / 제외 / 보류** 중 하나. 비우면 통과 안 됨(=보류로 간주).")
    lines.append("- 인용 끝 ` […]` = 원문이 길어 문장 경계까지 자름(전체는 golden/drafts/ 에 보존). 자르기만 했고 단어는 원문 그대로.")
    lines.append("- `인용검증=⚠원문미확인` = 이 인용이 원문에서 verbatim 으로 확인되지 않음(대개 표 셀 `(전기:…)` 포맷). **유지 전 원문 직접 확인 권장.**")
    lines.append("- 회사 순서: 후보 적은 회사부터(빨리 끝나는 것부터 승인). 많은 회사는 뒤.\n")

    lines.append("## 회사별 후보 수 (적은 순)")
    for key in comp_order:
        lines.append(f"- {key[1] or key[0]} ({key[0]}): {counts[key]}건")
    lines.append("")

    lines.append("## 후보")
    lines.append("| 번호 | 회사 | 항목명 | 인용(원문, 자름만) | 왜_담았나 | 확신 | 인용검증 | 판정 |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for r in rows:
        q = _md_cell(r["인용"])   # 잘림 마커는 이미 인용 필드에 포함
        lines.append("| {번호} | {회사} | {항목} | {인용} | {왜} | {확신} | {검증} |  |".format(
            번호=r["번호"], 회사=_md_cell(r["회사"]), 항목=_md_cell(r["항목명"]),
            인용=q, 왜=_md_cell(r["왜_담았나"]), 확신=_md_cell(r["확신"]), 검증=r["인용검증"]))
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cands = load_draft_candidates(DRAFTS_DIR)
    rows, counts, comp_order = _sorted_rows(cands)
    write_csv(rows)
    write_md(rows, counts, comp_order)

    print(f"[written] {CSV_PATH.relative_to(PROJECT_ROOT)}  (사람이 '판정' 채우는 정본)")
    print(f"[written] {MD_PATH.relative_to(PROJECT_ROOT)}   (읽기용)")
    print(f"\n총 후보 {len(rows)}건, 잘린 인용 {sum(1 for r in rows if r['_인용_잘림'])}건, "
          f"원문미확인 {sum(1 for r in rows if r['인용검증']!='verbatim확인')}건")
    print("\n회사별 후보 수(적은 순 = 표에 실린 순서):")
    for key in comp_order:
        print(f"  {key[1] or key[0]} ({key[0]}): {counts[key]}건")
    # 0건 회사(판정 대상 없음)도 사실대로 보고
    zero = []
    for p in sorted(DRAFTS_DIR.glob("draft_*.json")):
        import json
        d = json.loads(p.read_text(encoding="utf-8"))
        if not d.get("draft_candidates"):
            zero.append((d.get("company", {}).get("corp_name", ""), p.name))
    if zero:
        print("\n0건(표에 행 없음):")
        for name, fn in zero:
            print(f"  {name}  [{fn}]")


if __name__ == "__main__":
    main()
