"""검토표 생성기와 승인→ratified 변환기가 공유하는 로직 (판단 없음, 매핑만).

핵심: 각 초안 후보에 '내용에서 결정되는' 안정 id(cand_id)를 부여한다. 표에는 인용을 잘라 실어도
(자르기만, 훼손 금지), cand_id 로 golden/drafts/ 의 '원본 전체 인용'을 되찾을 수 있다 → 표의 잘린
인용이 ratified 정답을 훼손하지 않는다. 두 스크립트가 같은 cand_id 계산을 쓰도록 여기 모은다.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DRAFTS_DIR = PROJECT_ROOT / "golden" / "drafts"


def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def cand_id(stock: str, quote: str, item: str) -> str:
    """(회사, 정규화 인용, 항목명)에서 결정되는 10자리 id. 초안 내용이 같으면 항상 같은 id."""
    basis = f"{norm(stock)}|{norm(quote)}|{norm(item)}".encode("utf-8")
    return hashlib.sha1(basis).hexdigest()[:10]


def _draft_files(drafts_dir: Path):
    return sorted(p for p in drafts_dir.glob("draft_*.json") if p.is_file())


def load_draft_candidates(drafts_dir: Path = DRAFTS_DIR):
    """golden/drafts/*.json -> 후보 dict 리스트(cand_id 부여, 중복 제거).

    각 dict: cand_id, stock_code, corp_name, corp_code, 항목명, 인용(원문 전체), 왜_담았나,
    확신, 주석위치, citation_present, appeared_in, of_runs, source_draft.
    """
    out, seen = [], set()
    for path in _draft_files(drafts_dir):
        d = json.loads(path.read_text(encoding="utf-8"))
        comp = d.get("company", {})
        stock = comp.get("stock_code") or comp.get("corp_code") or ""
        for c in d.get("draft_candidates", []):
            item = c.get("항목명", "")
            quote = c.get("인용", "")
            cid = cand_id(stock, quote, item)
            if cid in seen:
                continue
            seen.add(cid)
            out.append({
                "cand_id": cid,
                "stock_code": stock,
                "corp_name": comp.get("corp_name", ""),
                "corp_code": comp.get("corp_code", ""),
                "항목명": item,
                "인용": quote,                       # 원문 전체(자르지 않음)
                "왜_담았나": c.get("왜_담았나", ""),
                "확신": c.get("확신", ""),
                "주석위치": c.get("주석위치", ""),
                "citation_present": bool(c.get("citation_check", {}).get("present")),
                "appeared_in": c.get("appeared_in"),
                "of_runs": c.get("of_runs"),
                "source_draft": path.name,
            })
    return out


def company_counts(cands):
    counts = {}
    for c in cands:
        key = (c["stock_code"], c["corp_name"])
        counts[key] = counts.get(key, 0) + 1
    return counts


# 확신 정렬 우선순위(높은 확신 먼저 보이게). 값 밖은 뒤로.
CONF_ORDER = {"높음": 0, "중간": 1, "낮음": 2}


def conf_rank(v) -> int:
    return CONF_ORDER.get(norm(v), 9)
