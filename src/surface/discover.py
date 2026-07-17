"""surface 1단계(2-a): 감사보고서 4문단을 LLM으로 읽어 비반복 의심 후보를 인용과 함께 뽑는다.

- prompts/surface_candidates.md 도구 프롬프트(고정 사고순서)를 system 으로, 4문단을 user 로
  Claude(Opus 4.8)에 보낸다. Opus 4.8은 temperature 미지원 → 결과가 아니라 '사고과정'을 지정해
  안정화한다(audit-issue-tracker 패턴 계승).
- 재현 점검: 같은 입력을 --repeat N 회 돌려 후보 안정성(몇/N 회 등장)을 집계한다.
- 할루시네이션 점검: 각 후보의 '인용'이 원문 4문단에 실제로 있는지(공백 정규화 후 부분문자열)
  검증해 flag 한다. 이는 후보 선별이 아니라 모델 출력에 대한 사후 검증이다(citations-mandatory 의
  역추적/디버깅 목적). 인용이 없거나 원문에 없으면 flag.
- 이 단계는 리콜을 재지 않는다(골든셋 전). "확실히 일회성" 판정 라벨은 붙이지 않는다.
- schema surface/2.1: 후보마다 두 독립 태그(표시위치·조정성격) + 재계산용 금액표시·단위·손익방향
  (모두 프롬프트가 인용에서만 뽑게 함). 표시위치=상단/하단이면 계상 위치 근거 구절(표시위치_근거)을
  인용에서 그대로 뽑게 하고(normalize 의 근거 게이트가 verbatim 검증), 태그·금액은 프롬프트가 정한다.

사용:
  # 실데이터: 환경변수 OPENDART_API_KEY, ANTHROPIC_API_KEY 필요
  python src/surface/discover.py --corp-code 00126380 --repeat 3
  # 오프라인 재현(섹션 픽스처 + 목 응답): API·네트워크 불필요, 결정론적
  python src/surface/discover.py --sections-file sections.json --mock mock.json --repeat 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 스크립트로 직접 실행(python src/surface/discover.py) 시 프로젝트 루트를 import 경로에 넣어
# 'from src.extract ...' 가 되게 한다(run.py 와 동일 패턴). 목/오프라인은 src.* 를 안 쓰지만
# 실데이터 경로(_collect_live)가 이를 필요로 한다.
sys.path.insert(0, str(PROJECT_ROOT))
OUT_DIR = PROJECT_ROOT / "out"
DEFAULT_PROMPT = PROJECT_ROOT / "prompts" / "surface_candidates.md"
DEFAULT_UPPER_PROMPT = PROJECT_ROOT / "prompts" / "surface_upper_sweep.md"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 16000

# 감사보고서 4섹션 고정 순서 (audit_sections.INTEREST_SECTIONS 와 동일)
SECTION_ORDER = ["핵심감사사항", "강조사항", "기타사항", "계속기업 관련 중요한 불확실성"]


def _norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _sec_text(val):
    return val["text"] if isinstance(val, dict) else val


def load_prompt(path):
    return Path(path).read_text(encoding="utf-8")


def build_user_message(sections: dict) -> str:
    parts = []
    for name in SECTION_ORDER:
        if name in sections and sections[name] is not None:
            parts.append(f"[{name}]\n{_sec_text(sections[name])}")
    return "\n\n".join(parts)


def source_text(sections: dict) -> str:
    return "\n".join(_sec_text(sections[n]) for n in SECTION_ORDER
                     if n in sections and sections[n] is not None)


def _section_char_len(sections: dict) -> dict:
    return {n: len(_norm_ws(_sec_text(sections[n])))
            for n in SECTION_ORDER if n in sections and sections[n] is not None}


def call_model(system, user, model, thinking, max_tokens, cache=True):
    """anthropic SDK 로 Claude 호출(지연 임포트). temperature 등 샘플링 파라미터는 보내지 않는다
    (Opus 4.8에서 400). 안정화는 프롬프트의 고정 사고순서가 담당.

    prompt caching(cache=True): system(고정 지시)+user(주석 본문)는 같은 스윕의 모든 회차에서 동일하므로
    `cache_control: ephemeral` 로 캐시 프리픽스로 지정한다 — 회차1은 캐시 쓰기(1.25×), 회차2·3은 캐시
    읽기(0.1×)로 결제된다. 보내는 내용·모델·파라미터는 그대로라 산출물 품질에 영향 없다(입력 불변).
    반환 (text, usage). usage 는 토큰·캐시 계측용(input/output/cache_creation/cache_read)."""
    import anthropic  # lazy: 목/오프라인 실행은 SDK 없이도 돈다

    client = anthropic.Anthropic()
    if cache:
        # 두 캐시 브레이크포인트: system, 그리고 system+user. 큰 안정 프리픽스(주석 본문)를 캐시한다.
        system_arg = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        user_content = [{"type": "text", "text": user, "cache_control": {"type": "ephemeral"}}]
    else:
        system_arg, user_content = system, user
    kwargs = dict(model=model, max_tokens=max_tokens, system=system_arg,
                  messages=[{"role": "user", "content": user_content}])
    kwargs["thinking"] = {"type": "adaptive"} if thinking == "adaptive" else {"type": "disabled"}
    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    u = resp.usage
    usage = {
        "input_tokens": getattr(u, "input_tokens", None),
        "output_tokens": getattr(u, "output_tokens", None),
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None),
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
    }
    return text, usage


def parse_candidates(raw):
    """모델 응답에서 첫 JSON 배열을 관대하게 추출. 반환 (list|None, ok, error)."""
    if raw is None:
        return None, False, "no_text"
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    i = t.find("[")
    if i == -1:
        return None, False, "no_array"
    depth, end, instr, esc = 0, -1, False, False
    for j in range(i, len(t)):
        c = t[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end == -1:
        return None, False, "unterminated_array"
    try:
        arr = json.loads(t[i:end])
    except Exception as e:  # noqa: BLE001
        return None, False, f"json_error:{e}"
    if not isinstance(arr, list):
        return None, False, "not_a_list"
    return arr, True, None


def verify_citation(cand, src_norm):
    """후보의 '인용'이 원문에 verbatim(공백 정규화)으로 있는지. 없으면 할루시네이션 후보."""
    quote = cand.get("인용")
    if not quote or not str(quote).strip():
        return {"present": False, "reason": "no_quote"}
    present = _norm_ws(str(quote)) in src_norm
    return {"present": present, "reason": None if present else "quote_not_in_source"}


def _cand_key(cand):
    return _norm_ws(str(cand.get("인용", ""))) or _norm_ws(str(cand.get("항목명", "")))


def run_once(idx, system, user, model, thinking, max_tokens, src_norm, mock_text=None, cache=True):
    call_error = None
    usage = None
    if mock_text is not None:
        raw = mock_text
    else:
        try:
            raw, usage = call_model(system, user, model, thinking, max_tokens, cache=cache)
        except Exception as e:  # noqa: BLE001
            raw, call_error = None, f"{type(e).__name__}:{e}"

    cands, ok, perr = parse_candidates(raw)
    annotated = []
    for c in (cands or []):
        cc = dict(c)
        cc["citation_check"] = verify_citation(c, src_norm)
        annotated.append(cc)
    return {
        "run_index": idx,
        "raw_char_len": len(raw) if raw else 0,
        "parse_ok": ok,
        "parse_error": perr,
        "call_error": call_error,
        "candidate_count": len(annotated),
        "candidates": annotated,
        "usage": usage,
    }


def _merge_candidates(gen_cands, up_cands):
    """한 회차의 1차(general)+2차(upper) 후보를 합친다. 2차 후보는 _sweep='upper' 로 표시하고,
    같은 회차에서 1차와 exact-key 중복이면 1차 것을 남긴다(회차 내 중복 카운트 방지 — 회차간 dedup 은
    downstream 이 그대로 한다). 반환 (merged, upper_new_count)."""
    keys = {_cand_key(c) for c in gen_cands}
    merged = list(gen_cands)
    new = 0
    for c in up_cands:
        cc = dict(c)
        cc["_sweep"] = "upper"
        k = _cand_key(cc)
        if k and k in keys:
            continue
        if k:
            keys.add(k)
        merged.append(cc)
        new += 1
    return merged, new


def aggregate(runs):
    n = len(runs)
    groups = OrderedDict()
    for r in runs:
        seen = set()
        for c in r["candidates"]:
            k = _cand_key(c)
            if not k or k in seen:  # 한 회차 안에서 중복 후보는 1번만 센다
                continue
            seen.add(k)
            g = groups.setdefault(k, {"항목명": c.get("항목명"), "인용": c.get("인용"),
                                      "runs": [], "citation_present": c["citation_check"]["present"]})
            g["runs"].append(r["run_index"])

    distinct = []
    for g in groups.values():
        cnt = len(g["runs"])
        distinct.append({
            "항목명": g["항목명"], "인용": g["인용"], "runs": g["runs"],
            "appeared_in": cnt, "of_runs": n, "stability": round(cnt / n, 4) if n else 0,
            "citation_verbatim_present": g["citation_present"],
        })
    distinct.sort(key=lambda d: (-d["appeared_in"], str(d["항목명"])))

    flagged = []
    for r in runs:
        for c in r["candidates"]:
            if not c["citation_check"]["present"]:
                flagged.append({"run_index": r["run_index"], "항목명": c.get("항목명"),
                                "인용": c.get("인용"), "reason": c["citation_check"]["reason"]})

    reproducibility = {
        "total_runs": n,
        "distinct_candidate_count": len(distinct),
        "fully_stable_count": sum(1 for d in distinct if d["appeared_in"] == n),
        "distinct_candidates": distinct,
    }
    hallucination = {
        "flagged_count": len(flagged),
        "note": "인용이 원문 4문단에 verbatim 으로 없는 후보. 후보 자체를 지우지 않고 표시만 한다.",
        "flagged": flagged,
    }
    return reproducibility, hallucination


def _aggregate_usage(runs, cache):
    """모든 LLM 호출(일반+2차)의 토큰·캐시 사용을 합산. 입력 결제단위(입력가 기준)로 캐시 절감률을
    계산한다: 캐시 write=1.25×·read=0.10×·미캐시=1.0×. 캐시 없으면 그 입력 전부를 1.0× 로 결제."""
    tot = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    for r in runs:
        for key in ("usage", "upper_usage"):
            u = r.get(key)
            if not u:
                continue
            tot["calls"] += 1
            for k in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
                tot[k] += (u.get(k) or 0)
    cw, cr, inp = (tot["cache_creation_input_tokens"], tot["cache_read_input_tokens"],
                   tot["input_tokens"])
    cached_units = inp * 1.0 + cw * 1.25 + cr * 0.10          # 입력가 기준 결제단위(캐시 적용)
    uncached_units = inp + cw + cr                            # 캐시 없으면 전부 1.0×
    tot["cache_enabled"] = cache
    tot["input_cost_units_cached"] = round(cached_units)
    tot["input_cost_units_uncached_equiv"] = round(uncached_units)
    tot["input_saving_pct"] = (round(100 * (1 - cached_units / uncached_units), 1)
                               if uncached_units else 0.0)
    return tot


def discover(sections, *, repeat, model, thinking, max_tokens, prompt_path,
             mock_texts=None, company=None, source_meta=None, notes_text=None,
             upper=None, upper_prompt_path=None, upper_mock_texts=None, cache=True):
    system = load_prompt(prompt_path)
    user = build_user_message(sections)
    src_norm = _norm_ws(source_text(sections))
    # 입력 공정성: 감사 4문단은 요약 — 골든셋 항목 다수는 주석 본문을 읽어야 나온다. 주석을 함께
    # 넣고, 인용검증 소스도 확장한다(프롬프트는 그대로. 골든셋은 참조하지 않는다 = 부정 아님).
    notes_norm = _norm_ws(notes_text) if notes_text else ""
    if notes_norm:
        user = f"{user}\n\n[연결재무제표 주석]\n{notes_text}"
        src_norm = _norm_ws(source_text(sections) + " " + notes_text)

    # 2차 스윕(상단 전용): 영업비용 구성 주석만 집중 발굴. 구조로 선정된 발췌가 있을 때만 켠다.
    up_on = bool(upper and upper.get("applied") and upper.get("text"))
    up_system = load_prompt(upper_prompt_path or DEFAULT_UPPER_PROMPT) if up_on else None
    up_user = upper.get("text") if up_on else None
    if up_on:
        # 2차 스윕 발췌도 인용검증 소스에 포함(모델이 그 텍스트에서 인용하므로 verbatim 검증이 맞아야 함).
        src_norm = _norm_ws(src_norm + " " + upper["text"])

    runs = []
    for i in range(repeat):
        mt = mock_texts[i % len(mock_texts)] if mock_texts else None
        gen = run_once(i, system, user, model, thinking, max_tokens, src_norm, mock_text=mt, cache=cache)
        for c in gen["candidates"]:
            c["_sweep"] = "general"
        gen["general_candidate_count"] = len(gen["candidates"])
        if up_on:
            umt = upper_mock_texts[i % len(upper_mock_texts)] if upper_mock_texts else None
            up = run_once(i, up_system, up_user, model, thinking, max_tokens, src_norm, mock_text=umt, cache=cache)
            merged, up_new = _merge_candidates(gen["candidates"], up["candidates"])
            gen["candidates"] = merged
            gen["candidate_count"] = len(merged)
            gen["upper_candidate_count"] = len(up["candidates"])
            gen["upper_new_count"] = up_new
            gen["upper_parse_ok"] = up["parse_ok"]
            gen["upper_call_error"] = up["call_error"]
            gen["upper_usage"] = up["usage"]
        runs.append(gen)
    usage_summary = _aggregate_usage(runs, cache)

    reproducibility, hallucination = aggregate(runs)
    return {
        "schema_version": "surface/2.1",
        # 표시위치_근거 필드를 프롬프트가 요구함 → normalize 의 근거 게이트를 켜도 된다는 능력 플래그.
        # 옛 산출물(이 키 없음)은 게이트를 끄고 그대로 처리(하위호환).
        "placement_evidence_field": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "비반복 의심 '후보'만 올린다. 일회성 확정 판정 아님 — 판정은 감사인이 한다.",
        "stage": "surface (감사보고서 4문단" + (" + 재무제표 주석 본문)" if notes_norm else ")")
                 + (" + 상단 2차 스윕" if up_on else ""),
        "company": company or {},
        "model": model,
        "thinking": thinking,
        "repeat": repeat,
        "cache": cache,
        "usage_summary": usage_summary,
        "source": {
            "sections_present": [n for n in SECTION_ORDER if n in sections],
            "section_char_len": _section_char_len(sections),
            "notes_included": bool(notes_norm),
            "notes_char_len": len(notes_norm),
            "meta": source_meta or {},
            "mock": bool(mock_texts),
        },
        # 2차 스윕(상단 전용) 투명성: 어느 주석을 구조로 골랐나·건너뛰었으면 사유.
        "upper_sweep": {
            "applied": up_on,
            "reason": (upper or {}).get("reason") if upper is not None else "upper 미요청(--upper-sweep 없음)",
            "selection_method": (upper or {}).get("selection_method"),
            "tier1_count": (upper or {}).get("tier1_count"),
            "tier2_count": (upper or {}).get("tier2_count"),
            "targets": (upper or {}).get("targets"),
            "sections": (upper or {}).get("sections"),
            "text_char_len": len(upper["text"]) if up_on else 0,
            "prompt": str(upper_prompt_path or DEFAULT_UPPER_PROMPT) if up_on else None,
        },
        "runs": runs,
        "reproducibility": reproducibility,
        "hallucination": hallucination,
    }


def _load_mock(path):
    """목 파일: 각 원소가 문자열(모델 원문) 또는 리스트(파싱된 후보 배열)인 JSON 배열."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("--mock 파일은 응답들의 JSON 배열이어야 합니다. (STOP)")
    return [e if isinstance(e, str) else json.dumps(e, ensure_ascii=False) for e in data]


def _collect_live(args):
    from src.extract import corp_codes as cc
    from src.extract.audit_report import fetch_audit_html
    from src.extract.audit_sections import extract_from_html
    from src.extract.dart_client import DartClient

    api_key = os.environ.get("OPENDART_API_KEY")
    if not api_key:
        raise SystemExit("환경변수 OPENDART_API_KEY 가 필요합니다. (STOP)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("환경변수 ANTHROPIC_API_KEY 가 필요합니다(목 모드가 아니라면). (STOP)")

    cache_dir = OUT_DIR / "_raw"
    client = DartClient(api_key=api_key, raw_dir=cache_dir, cache_dir=cache_dir,
                        project_root=PROJECT_ROOT)

    records = cc.parse_corp_codes(client.get_corpcode_xml())
    if args.corp_code:
        hits = [r for r in records if r["corp_code"] == args.corp_code.strip()]
        if not hits:
            raise SystemExit(f"corp_code {args.corp_code} 없음. (STOP)")
        target = hits[0]
    elif args.stock_code:
        target = cc.resolve_by_stock(records, args.stock_code)
    else:
        target = cc.resolve_by_name(records, args.name)
    corp_code = target["corp_code"]

    meta, html = fetch_audit_html(client, corp_code)
    sections = extract_from_html(html)
    company = {"corp_code": corp_code, "corp_name": target.get("corp_name", ""),
               "stock_code": target.get("stock_code", "")}
    source_meta = {"source": "opendart:document.xml", "rcept_no": meta["rcept_no"],
                   "base_year": meta["base_year"], "report_nm": meta["report_nm"],
                   "entry": meta["entry"], "document_name": meta["document_name"]}

    notes_text = None
    if getattr(args, "with_notes", False):
        from src.extract.notes_body import fetch_notes_body
        nmeta, notes = fetch_notes_body(client, corp_code, which="consolidated")
        if notes["present"] and notes["text"]:
            notes_text = notes["text"]
            source_meta["notes"] = {"rcept_no": nmeta["rcept_no"], "base_year": nmeta["base_year"],
                                    "char_len": notes["char_len"],
                                    "note_titles_count": len(notes["note_titles"]),
                                    "boundary": notes["boundary"]}
        else:
            source_meta["notes"] = {"present": False, "reason": notes.get("reason") or notes.get("boundary")}

    # 2차 스윕(상단 전용) 컨텍스트: 영업비용 구성 주석을 구조(표 산술+성분 개념코드)로 선정.
    # base-year 전체 재무제표(캐시)로 영업비용 IS 라인 타깃을 잡는다. 추가 네트워크 없음(zip·재무제표 캐시).
    upper = None
    if getattr(args, "upper_sweep", False):
        from src.extract import financials as _F
        from src.extract import opex_notes as _OX
        base_year = meta["base_year"]
        try:
            data, _st, _rh, _rp = _F.fetch_year(client, corp_code, base_year, "CFS")
            targets = _OX.opex_targets_from_raw(data)
            upper = _OX.fetch_opex_context(client, corp_code, base_year, targets)
        except Exception as e:  # noqa: BLE001 — 실패 시 정직하게 건너뛴다(추측으로 주석 안 넣음)
            upper = {"applied": False, "reason": f"2차 스윕 컨텍스트 수집 실패: {type(e).__name__}: {e}",
                     "selection_method": "표산술정합+성분개념코드", "sections": [], "text": ""}
    return sections, company, source_meta, notes_text, upper


def main(argv=None):
    p = argparse.ArgumentParser(
        description="surface 2-a: 감사보고서 4문단 -> 비반복 후보(인용 포함), 재현·할루시네이션 점검")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--corp-code", help="실데이터: OpenDART corp_code")
    src.add_argument("--stock-code", help="실데이터: 종목코드(6자리)")
    src.add_argument("--name", help="실데이터: 정확한 회사명")
    src.add_argument("--sections-file", help="오프라인: {company?, sections:{섹션명:text}} JSON")
    p.add_argument("--with-notes", action="store_true",
                   help="감사 4문단 + 연결재무제표 주석 본문을 함께 입력(입력 공정성). 프롬프트는 불변.")
    p.add_argument("--upper-sweep", action="store_true",
                   help="상단 전용 2차 스윕 추가: 영업비용 구성 주석만 구조로 골라 집중 발굴(1차와 합집합). "
                        "구조 식별 못 하면 정직하게 건너뛴다.")
    p.add_argument("--upper-prompt", default=str(DEFAULT_UPPER_PROMPT), help="2차 스윕 프롬프트 경로")
    p.add_argument("--no-cache", action="store_true",
                   help="프롬프트 캐싱 끔(기본: 켬). 캐싱은 같은 스윕 회차의 주석 본문을 캐시해 비용을 줄인다.")
    p.add_argument("--mock", default=None, help="오프라인 목 응답 JSON(응답 배열)")
    p.add_argument("--repeat", type=int, default=3, help="같은 입력 반복 횟수(재현 점검)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--thinking", default="disabled", choices=["disabled", "adaptive"])
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    mock_texts = _load_mock(args.mock) if args.mock else None

    notes_text = None
    upper = None
    if args.sections_file:
        raw = json.loads(Path(args.sections_file).read_text(encoding="utf-8"))
        sections = raw["sections"]
        company = raw.get("company", {})
        source_meta = {"source": f"sections-file:{args.sections_file}"}
        notes_text = raw.get("notes_text")
        # 오프라인 스키마 테스트용: sections-file 에 upper 발췌를 직접 넣을 수 있다(선택).
        if raw.get("upper_text"):
            upper = {"applied": True, "reason": None, "selection_method": "offline",
                     "text": raw["upper_text"], "sections": raw.get("upper_sections", [])}
    else:
        if not mock_texts and not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("실데이터 모드는 ANTHROPIC_API_KEY 가 필요합니다(또는 --mock). (STOP)")
        sections, company, source_meta, notes_text, upper = _collect_live(args)

    result = discover(sections, repeat=args.repeat, model=args.model, thinking=args.thinking,
                      cache=not args.no_cache,
                      max_tokens=args.max_tokens, prompt_path=args.prompt,
                      mock_texts=mock_texts, company=company, source_meta=source_meta,
                      notes_text=notes_text, upper=upper, upper_prompt_path=args.upper_prompt)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ident = (company.get("stock_code") or company.get("corp_code") or "fixture")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"surface_{ident}_{stamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {out_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return out_path


if __name__ == "__main__":
    main()
