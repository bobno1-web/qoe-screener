"""골든셋 초안 생성기 (harness 지원 도구 — 채점기 아님, 골든셋을 '만드는' 쪽).

golden/draft-prompt/draft_golden_candidates.md (일부러 과잉포함하는 초안 프롬프트)를 system 으로,
실 OpenDART로 수집한 연결감사보고서 4문단을 user 로 Claude(Opus 4.8)에 보낸다.
이 초안 프롬프트는 도구 프롬프트(prompts/surface_candidates.md)와 절대 병합·혼용하지 않는다
(golden-set-integrity: 초안은 도구가 놓칠 것까지 사람 앞에 올려야 하므로 일부러 다르다).

- 초안은 도구보다 넓게 던진다: --repeat N 회 돌려 후보를 '합집합(union)'으로 모은다(빠짐없음 우선).
- 각 후보 '인용'을 원문 4문단에 대조(citation_check) — 초안도 인용을 지어내면 안 됨(citations-mandatory).
- 산출물은 golden/drafts/ 에만 쓴다. 정답 아님(사람 승인 전). 사람이 golden/ratified/ 로 옮기기 전엔
  채점에 쓰지 않는다. out/ 도구출력은 여기 절대 안 들어온다(물리 분리).
- LLM 이 '확실히 일회성' 을 판정하지 않는다 — 넓게 담고, 사람이 뒤에서 쳐낸다.

사용:
  set -a; source ../.env; set +a   # OPENDART_API_KEY, ANTHROPIC_API_KEY
  python harness/build_golden_draft.py --stock-code 005930 --stock-code 000660 --repeat 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.extract import corp_codes as cc                       # noqa: E402
from src.extract.audit_report import fetch_audit_html          # noqa: E402
from src.extract.audit_sections import extract_from_html       # noqa: E402
from src.extract.dart_client import DartClient, StopConditionError  # noqa: E402
from src.extract.notes_body import fetch_notes_body            # noqa: E402
from src.surface.discover import (                             # noqa: E402
    SECTION_ORDER, build_user_message, call_model, load_prompt,
    parse_candidates, source_text, verify_citation, _norm_ws,
)

DRAFT_PROMPT = PROJECT_ROOT / "golden" / "draft-prompt" / "draft_golden_candidates.md"
TOOL_PROMPT = PROJECT_ROOT / "prompts" / "surface_candidates.md"
DRAFTS_DIR = PROJECT_ROOT / "golden" / "drafts"
RAW_DIR = PROJECT_ROOT / "out" / "_raw"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 16000


def _assert_prompts_separate():
    """초안 프롬프트와 도구 프롬프트가 물리적으로 다른 파일이고 내용도 다름을 실행 시 재확인."""
    if DRAFT_PROMPT.resolve() == TOOL_PROMPT.resolve():
        raise SystemExit("초안 프롬프트와 도구 프롬프트가 같은 파일을 가리킴 — golden-set-integrity 위반. (STOP)")
    if TOOL_PROMPT.exists() and load_prompt(DRAFT_PROMPT).strip() == load_prompt(TOOL_PROMPT).strip():
        raise SystemExit("초안 프롬프트 내용이 도구 프롬프트와 동일 — 초안은 일부러 더 넓어야 함. (STOP)")


def _client():
    key = os.environ.get("OPENDART_API_KEY")
    if not key:
        raise SystemExit("환경변수 OPENDART_API_KEY 가 필요합니다. (STOP)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("환경변수 ANTHROPIC_API_KEY 가 필요합니다. (STOP)")
    return DartClient(api_key=key, raw_dir=RAW_DIR, cache_dir=RAW_DIR, project_root=PROJECT_ROOT)


def _resolve(client, records, args_stock, args_corp):
    if args_corp:
        hit = [r for r in records if r["corp_code"] == args_corp.strip()]
        if not hit:
            raise StopConditionError(f"corp_code {args_corp} 없음")
        return hit[0]
    return cc.resolve_by_stock(records, args_stock)


def union_candidates(runs):
    """여러 회차 후보를 '합집합'으로 (초안은 넓게). 인용 정규화 키로 dedup, 전체 필드 보존."""
    groups = OrderedDict()
    n = len(runs)
    for r in runs:
        seen = set()
        for c in r["candidates"]:
            k = _norm_ws(str(c.get("인용", ""))) or _norm_ws(str(c.get("항목명", "")))
            if not k:
                continue
            if k in groups:
                if r["run_index"] not in groups[k]["_runs"]:
                    groups[k]["_runs"].append(r["run_index"])
                continue
            if k in seen:
                continue
            seen.add(k)
            g = dict(c)
            g["_runs"] = [r["run_index"]]
            groups[k] = g
    out = []
    for g in groups.values():
        g["appeared_in"] = len(g["_runs"])
        g["of_runs"] = n
        g.pop("_runs", None)
        out.append(g)
    # 확신 낮음도 담되, 사람이 먼저 볼 수 있게 appeared_in 내림차순
    out.sort(key=lambda d: (-d.get("appeared_in", 0), str(d.get("항목명", ""))))
    return out


def run_company(client, target, *, system, repeat, model, max_tokens, with_notes=False):
    corp_code = target["corp_code"]
    meta, html = fetch_audit_html(client, corp_code)
    sections = extract_from_html(html)
    user = build_user_message(sections)
    src_norm = _norm_ws(source_text(sections))

    # (+가능하면 주석): 감사보고서 4문단은 요약 — 실제 일회성 항목은 재무제표 주석에 있다.
    # 주석 본문을 user 에 덧붙이고, 인용검증 소스도 함께 확장한다(안 그러면 주석 인용이 전부 flag).
    notes_meta = None
    if with_notes:
        try:
            nmeta, notes = fetch_notes_body(client, corp_code, which="consolidated")
            if notes["present"] and notes["text"]:
                user = f"{user}\n\n[연결재무제표 주석]\n{notes['text']}"
                src_norm = _norm_ws(source_text(sections) + " " + notes["text"])
            notes_meta = {"rcept_no": nmeta["rcept_no"], "base_year": nmeta["base_year"],
                          "present": notes["present"], "char_len": notes["char_len"],
                          "note_titles_count": len(notes["note_titles"]),
                          "boundary": notes["boundary"]}
        except (StopConditionError, Exception) as e:  # noqa: BLE001
            notes_meta = {"present": False, "error": f"{type(e).__name__}:{e}"}

    runs = []
    for i in range(repeat):
        try:
            raw = call_model(system, user, model, "disabled", max_tokens)
            call_error = None
        except Exception as e:  # noqa: BLE001
            raw, call_error = None, f"{type(e).__name__}:{e}"
        cands, ok, perr = parse_candidates(raw)
        annotated = []
        for c in (cands or []):
            cc_ = dict(c)
            cc_["citation_check"] = verify_citation(c, src_norm)
            annotated.append(cc_)
        runs.append({"run_index": i, "parse_ok": ok, "parse_error": perr,
                     "call_error": call_error, "candidate_count": len(annotated),
                     "candidates": annotated})

    union = union_candidates(runs)
    flagged = [{"항목명": c.get("항목명"), "인용": c.get("인용")}
               for c in union if not c.get("citation_check", {}).get("present")]
    return {
        "_kind": "golden-draft",
        "_purpose": "AI 초안(과잉포함). 정답 아님 — 사람이 golden/ratified/ 로 승인하기 전엔 채점에 쓰지 않는다.",
        "_prompt_source": "golden/draft-prompt/draft_golden_candidates.md (도구 프롬프트와 분리)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": {"corp_code": corp_code,
                    "corp_name": target.get("corp_name", ""),
                    "stock_code": target.get("stock_code", "")},
        "source": {
            "source": "opendart:document.xml",
            "rcept_no": meta["rcept_no"], "base_year": meta["base_year"],
            "report_nm": meta["report_nm"], "document_name": meta["document_name"],
            "sections_present": [n for n in SECTION_ORDER if n in sections],
            "section_char_len": {n: sections[n]["char_len"] for n in SECTION_ORDER if n in sections},
            "notes": notes_meta,
        },
        "model": model, "repeat": repeat,
        "draft_candidate_count": len(union),
        "citation_flagged_count": len(flagged),
        "citation_flagged": flagged,
        "draft_candidates": union,
        "runs_raw": runs,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="골든셋 초안 생성(과잉포함 프롬프트, 실 OpenDART+Claude)")
    p.add_argument("--stock-code", action="append", default=[], help="반복 지정 가능")
    p.add_argument("--corp-code", action="append", default=[], help="반복 지정 가능")
    p.add_argument("--repeat", type=int, default=2, help="회차(합집합으로 넓게 모음)")
    p.add_argument("--with-notes", action="store_true",
                   help="연결재무제표 주석 본문도 함께 읽힌다(+주석 경로, 토큰 큼)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--out-dir", default=str(DRAFTS_DIR))
    args = p.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    _assert_prompts_separate()
    system = load_prompt(DRAFT_PROMPT)

    client = _client()
    records = cc.parse_corp_codes(client.get_corpcode_xml())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    targets = [("stock", s) for s in args.stock_code] + [("corp", c) for c in args.corp_code]
    if not targets:
        raise SystemExit("--stock-code 또는 --corp-code 를 하나 이상 지정하세요. (STOP)")

    summary = []
    for kind, ident in targets:
        try:
            target = _resolve(client, records, ident if kind == "stock" else None,
                              ident if kind == "corp" else None)
            result = run_company(client, target, system=system, repeat=args.repeat,
                                 model=args.model, max_tokens=args.max_tokens,
                                 with_notes=args.with_notes)
        except (StopConditionError, Exception) as e:  # noqa: BLE001
            summary.append({"target": ident, "status": "SKIP", "reason": f"{type(e).__name__}:{e}"})
            print(f"[skip] {ident}: {type(e).__name__}: {e}")
            continue

        name = result["company"]["corp_name"] or result["company"]["corp_code"]
        sid = result["company"]["stock_code"] or result["company"]["corp_code"]
        path = out_dir / f"draft_{sid}_{stamp}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({"target": ident, "status": "OK", "corp_name": name,
                        "sections": result["source"]["sections_present"],
                        "draft_candidates": result["draft_candidate_count"],
                        "citation_flagged": result["citation_flagged_count"],
                        "path": str(path.relative_to(PROJECT_ROOT))})
        print(f"[written] {path.relative_to(PROJECT_ROOT)}  "
              f"({name}: 섹션 {result['source']['sections_present']}, "
              f"초안후보 {result['draft_candidate_count']}개, 인용flag {result['citation_flagged_count']})")

    print("\n=== 초안 생성 요약 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
