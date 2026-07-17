"""루프3 채점기: 골든셋 '초안'이 정답지 재료로 건전한지 + 순환방지 준수 사실 확인.

이 단계는 "초안 후보가 맞느냐"를 판정하지 않는다(사람 승인 몫). 사실만 잰다:
  item1 순환방지 : 초안/도구 프롬프트 파일 분리·내용 상이·초안이 더 넓게 설계됐는지.
                   초안 산출물이 도구 out/ 재활용이 아니라 초안 스키마로 생성됐는지.
  item2 과잉포함 : (별도로 도구를 실행해) 초안 후보수 ≥ 도구 후보수인지.
  item3 인용진위 : 초안 후보 '인용'을 원문에 '내 코드로 다시' 대조. 지어낸 인용 개수.
                   도구가 저장한 citation_check 를 믿지 않고 재계산 후 교차대조.

독립성: 원문은 캐시된 실 DART 문서(out/_raw)에서 재구성. 초안이 저장한 present 필드가 아니라
        여기서 substring 을 다시 계산한다. 미검출 인용은 원문 XML 전체 텍스트에서 조각까지 확인해
        '지어냄 / 생략부호 결합 / 추출섹션 밖' 으로 분류한다.
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.extract.audit_report import fetch_audit_html          # noqa: E402
from src.extract.audit_sections import extract_from_html       # noqa: E402
from src.extract.dart_client import DartClient                 # noqa: E402
from src.extract.notes_body import fetch_notes_body            # noqa: E402
from src.surface.discover import (                             # noqa: E402
    SECTION_ORDER, source_text, _norm_ws,
)

DRAFTS_DIR = PROJECT_ROOT / "golden" / "drafts"
RAW_DIR = PROJECT_ROOT / "out" / "_raw"
DRAFT_PROMPT = PROJECT_ROOT / "golden" / "draft-prompt" / "draft_golden_candidates.md"
TOOL_PROMPT = PROJECT_ROOT / "prompts" / "surface_candidates.md"

DRAFT_SCHEMA_FIELDS = {"항목명", "인용", "주석위치", "왜_담았나", "확신"}
TOOL_SCHEMA_FIELDS = {"비반복성_근거", "근거강도", "조정대상_소계", "item_type"}


def norm(s):
    return _norm_ws(str(s or ""))


def raw_doc_text(corp_code, rcept_no):
    """캐시된 실 DART 문서 zip 전체 XML 엔트리의 태그제거 텍스트(정규화). 원문 존재여부 판정용."""
    texts = []
    for zpath in glob.glob(str(RAW_DIR / "document" / "*.zip")):
        try:
            z = zipfile.ZipFile(zpath)
        except Exception:
            continue
        names = z.namelist()
        if not any(rcept_no in n for n in names):
            continue
        for n in names:
            try:
                data = z.read(n)
            except Exception:
                continue
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    s = data.decode(enc)
                    break
                except Exception:
                    s = None
            if s is None:
                continue
            s = re.sub(r"<[^>]+>", " ", s)
            texts.append(s)
    return norm(" ".join(texts))


def reconstruct_src_norm(client, corp_code, want_notes):
    """모델이 실제로 본 원문(src_norm)을 재구성. 초안이 --with-notes 였다면 주석 본문까지 포함.
    build_golden_draft.run_company 의 src_norm 계산과 동일하게 맞춘다."""
    meta, html = fetch_audit_html(client, corp_code)
    sections = extract_from_html(html)
    base = source_text(sections)
    notes_used = False
    if want_notes:
        try:
            _nm, notes = fetch_notes_body(client, corp_code, which="consolidated")
            if notes["present"] and notes["text"]:
                base = source_text(sections) + " " + notes["text"]
                notes_used = True
        except Exception:  # noqa: BLE001
            pass
    return meta, sections, norm(base), notes_used


def fragments(quote):
    """초안 인용을 생략부호(…, ...) + 괄호주석((전기:..),(당기:..),(주석 .. 참조))로 분해.
    괄호주석·생략부호는 모델이 덧댄 서식일 수 있으므로 조각별로 원문 대조한다."""
    q = re.sub(r"\((?:전기|당기)\s*:[^)]*\)", " ... ", quote)
    q = re.sub(r"\(주석[^)]*\)", " ... ", q)
    parts = re.split(r"\s*(?:\.\.\.|…|⋯)\s*", q)
    return [p for p in (norm(p) for p in parts) if len(p) >= 8]


def classify_flag(q, src_norm, docall):
    """미검출 인용을 사유별 분류. 반환 (category, detail)."""
    frs = fragments(q)
    in_doc = [fr for fr in frs if fr in docall]
    in_src = [fr for fr in frs if fr in src_norm]
    if q and q in docall:
        return "추출섹션밖", "원문XML엔 통째로 존재(모델입력·정규화 밖)"
    if frs and len(in_doc) == len(frs):
        return "비정형인용_내용원문존재", f"조각 {len(frs)}개 전부 원문존재(섹션내 {len(in_src)}/{len(frs)})"
    if in_doc:
        return "부분근거", f"조각 {len(in_doc)}/{len(frs)}만 원문존재"
    return "지어냄", "원문·조각 어디에도 없음"


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    key = os.environ.get("OPENDART_API_KEY")
    if not key:
        raise SystemExit("OPENDART_API_KEY 필요(캐시 재구성에도 클라이언트 생성 필요). source ../.env")
    client = DartClient(api_key=key, raw_dir=RAW_DIR, cache_dir=RAW_DIR, project_root=PROJECT_ROOT)

    # ---- item1: 프롬프트 분리/상이 ----
    print("## item1 순환방지(프롬프트/산출물)")
    dp = DRAFT_PROMPT.read_text(encoding="utf-8")
    tp = TOOL_PROMPT.read_text(encoding="utf-8")
    print(f"  초안 프롬프트 경로: {DRAFT_PROMPT.relative_to(PROJECT_ROOT)}")
    print(f"  도구 프롬프트 경로: {TOOL_PROMPT.relative_to(PROJECT_ROOT)}")
    print(f"  다른 파일인가: {DRAFT_PROMPT.resolve() != TOOL_PROMPT.resolve()}")
    print(f"  내용 상이한가: {dp.strip() != tp.strip()}  (초안 {len(dp)}자 / 도구 {len(tp)}자)")

    drafts = sorted(glob.glob(str(DRAFTS_DIR / "draft_*.json")))
    print(f"\n  초안 산출물 {len(drafts)}개 스키마 검사(도구 out/ 재활용 아닌지):")
    for f in drafts:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        cands = d.get("draft_candidates", []) + [c for r in d.get("runs_raw", []) for c in r.get("candidates", [])]
        keys = set()
        for c in cands:
            keys |= set(c.keys())
        keys -= {"citation_check", "appeared_in", "of_runs", "_runs"}
        has_draft = bool(keys & DRAFT_SCHEMA_FIELDS)
        has_tool = bool(keys & TOOL_SCHEMA_FIELDS)
        kind = d.get("_kind")
        psrc = d.get("_prompt_source", "")
        tag = "초안스키마" if (has_draft and not has_tool) else ("도구스키마혼입!" if has_tool else "후보없음")
        print(f"    - {Path(f).name}: _kind={kind}  후보필드={sorted(keys)}  → {tag}"
              + (f"  prompt_source={psrc[:38]}" if psrc else ""))

    # ---- item3: 인용 진위 (독립 재계산; 주석 포함 원문으로) ----
    print("\n## item3 인용 진위(독립 재계산 + 원문 XML 조각 분류; --with-notes 반영)")
    tot_cand = tot_flag_mine = tot_flag_tool = 0
    cls_tot = {"추출섹션밖": 0, "비정형인용_내용원문존재": 0, "부분근거": 0, "지어냄": 0}
    disagree = 0
    fabricated_items = []
    for f in drafts:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        corp = d["company"]["corp_code"]
        name = d["company"]["corp_name"]
        rcept = d["source"]["rcept_no"]
        want_notes = bool((d["source"].get("notes") or {}).get("present"))
        try:
            meta, sections, src_norm, notes_used = reconstruct_src_norm(client, corp, want_notes)
        except Exception as e:  # noqa: BLE001
            print(f"  [{name}] 원문 재구성 실패: {type(e).__name__}:{e}")
            continue
        docall = raw_doc_text(corp, rcept)
        cands = d.get("draft_candidates", [])
        n_cand = len(cands)
        mine_flag = []
        for c in cands:
            q = norm(c.get("인용"))
            present_mine = bool(q) and (q in src_norm)
            present_tool = bool(c.get("citation_check", {}).get("present"))
            if present_mine != present_tool:
                disagree += 1
            if not present_mine:
                cat, detail = classify_flag(q, src_norm, docall)
                cls_tot[cat] += 1
                if cat == "지어냄":
                    fabricated_items.append((name, c.get("항목명"), q))
                mine_flag.append((c.get("항목명"), cat, detail, q[:58]))
        tool_flag = d.get("citation_flagged_count", 0)
        tot_cand += n_cand
        tot_flag_mine += len(mine_flag)
        tot_flag_tool += tool_flag
        print(f"  [{name} {d['company']['stock_code']}] 초안후보 {n_cand}  "
              f"내독립flag {len(mine_flag)}  도구저장flag {tool_flag}  "
              f"src_norm {len(src_norm)}자(notes={notes_used})  원문XML {len(docall)}자")
        for item, cat, detail, qhead in mine_flag:
            print(f"        · {str(item)[:40]} :: {cat} — {detail}")

    print(f"\n  [합계] 초안후보 {tot_cand}개 중 인용 verbatim 미검출(내 독립계산) {tot_flag_mine}개 "
          f"/ 도구저장 {tot_flag_tool}개 / 불일치 {disagree}건")
    print(f"         사유분류: {cls_tot}")
    print(f"         → 원문 어디에도 근거없는 '지어냄' 개수: {cls_tot['지어냄']}")
    for nm, item, q in fabricated_items:
        print(f"            [{nm}] {item}\n               = {q[:110]!r}")


if __name__ == "__main__":
    main()
