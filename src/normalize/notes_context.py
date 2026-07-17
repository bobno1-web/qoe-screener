"""normalize 보조: 원문보기 상세화(#5)용. 캐시된 주석 본문에서 항목별 '넓은 발췌 + 하이라이트'를
만든다. 결정론적·verbatim — 요약·변형·생성 없음(citations-mandatory). 라이브 LLM 없음.

- fetch_notes_body 로 연결 주석 섹션의 플랫 텍스트(태그 제거·공백정규화)를 얻는다. 이는 surface 가
  LLM 에 넣은 바로 그 텍스트(같은 회차 캐시) → 후보 인용·D&A 원문값이 이 텍스트의 부분문자열.
- 주석 제목으로 섹션을 나눠 항목의 '주석위치' 번호에 맞는 섹션을 통째로 띄운다(성격별표 전체 등).
  섹션이 길면 하이라이트(뽑은 금액) 주변 창으로. 섹션에 그 숫자가 없으면 전체 텍스트에서 숫자로 재앵커.
- OpenDART 배관은 캐시 우선(document.xml 캐시면 무네트워크). 키·캐시 없으면 None(원문보기는 인용만).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
OUT_DIR = PROJECT_ROOT / "out"

SECTION_CAP = 4200     # 섹션 통째 표시 상한(넘으면 창으로 좁힌다)
WINDOW = 1100          # 하이라이트 주변 창 반경(문자)


# ---------------------------------------------------------------- 로드
def load_flat_notes(corp_code, which="consolidated"):
    """캐시된 사업보고서 → {text, sections}. 키/캐시/앵커 없으면 None(원문보기 degradation)."""
    if not os.environ.get("OPENDART_API_KEY"):
        return None
    try:
        from src.extract.dart_client import DartClient
        from src.extract.notes_body import fetch_notes_body
        cache = OUT_DIR / "_raw"
        client = DartClient(api_key=os.environ["OPENDART_API_KEY"], raw_dir=cache,
                            cache_dir=cache, project_root=PROJECT_ROOT)
        _, notes = fetch_notes_body(client, corp_code, which=which)
        if not notes.get("present") or not notes.get("text"):
            return None
        text = notes["text"]
        return {"text": text, "sections": _sections(text, notes.get("note_titles", []))}
    except Exception:
        return None


def _sections(text, note_titles):
    """플랫 텍스트를 하위 주석 제목 경계로 분할. 문서 순서로 첫 등장 위치를 잡는다."""
    positions, cursor = [], 0
    for lab in note_titles:
        if not lab:
            continue
        idx = text.find(lab, cursor)
        if idx == -1:
            idx = text.find(lab)
        if idx == -1:
            continue
        positions.append((idx, lab))
        cursor = idx + len(lab)
    positions.sort()
    secs = []
    for i, (pos, lab) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        secs.append({"label": lab, "start": pos, "text": text[pos:end]})
    return secs


# ---------------------------------------------------------------- 발췌
def _sec_num(label):
    m = re.match(r"\s*0*(\d+)\s*[.．]", label or "")
    return m.group(1) if m else None


def _match_section(sections, note_hint):
    nums = re.findall(r"\d+", note_hint or "")
    for n in nums:                         # 주석 번호 우선
        for s in sections:
            if _sec_num(s["label"]) == n:
                return s
    h = re.sub(r"\s+", "", note_hint or "")   # 번호 없으면 제목 텍스트로
    for s in sections:
        core = re.sub(r"^\s*0*\d+\s*[.．]\s*", "", s["label"]).strip()
        if len(re.sub(r"\s+", "", core)) >= 4 and re.sub(r"\s+", "", core) in h:
            return s
    return None


def _note_of_pos(sections, i):
    cur = None
    for s in sections:
        if s["start"] <= i:
            cur = s["label"]
        else:
            break
    return cur


def _window(s, i, alen, scale=1):
    """섹션/텍스트 s 에서 위치 i 주변 발췌. 짧으면 통째, 길면 창. (excerpt, truncated).
    scale>1 이면(근거강도=추정 항목) 통째 표시 상한·창 반경을 넓혀 유추 근거(표 머리·주변 행)를 더 보인다."""
    cap = SECTION_CAP * scale
    win = WINDOW * scale
    if len(s) <= cap:
        return s, False
    start = max(0, i - win)
    end = min(len(s), i + alen + win)
    pre = "… " if start > 0 else ""
    suf = " …" if end < len(s) else ""
    return pre + s[start:end] + suf, True


def _offsets(excerpt, needles):
    """발췌 안 needle 들의 [start,end]. 숫자/쉼표 경계로 부분숫자 오탐 방지, 중복 병합."""
    offs = []
    for nd in needles:
        if not nd:
            continue
        start = 0
        while True:
            i = excerpt.find(nd, start)
            if i == -1:
                break
            before = excerpt[i - 1] if i > 0 else ""
            after = excerpt[i + len(nd)] if i + len(nd) < len(excerpt) else ""
            if not (before.isdigit() or before == ",") and not after.isdigit():
                offs.append([i, i + len(nd)])
            start = i + len(nd)
    offs.sort()
    merged = []
    for s, e in offs:
        if merged and s < merged[-1][1]:
            continue
        merged.append([s, e])
    return merged


def _lcs_in_text(needle, text, minlen=12):
    """needle(인용)에서 text(주석)에 실제로 있는 최장 연속 부분문자열. 문구가 달라도 겹치는 구간을
    찾는다. 없으면 None. seed(minlen) 부재 위치는 빠르게 건너뛴다."""
    q = re.sub(r"\s+", " ", needle or "").strip()
    n, best, i = len(q), "", 0
    while i <= n - minlen:
        if q[i:i + minlen] in text:
            lo = i + minlen
            while lo <= n and q[i:lo] in text:
                lo += 1
            cand = q[i:lo - 1]
            if len(cand) > len(best):
                best = cand
            i += max(1, len(cand) - minlen + 1)
        else:
            i += 1
    return best if len(best) >= minlen else None


def excerpt_for(notes, note_hint, number_highlights=(), text_anchors=(), window_scale=1):
    """항목의 넓은 원문 발췌 + 하이라이트. 반환 {note_title, excerpt, offsets, truncated, anchor} | None.

    number_highlights: 마크할 금액 문자열(쉼표형). text_anchors: 앵커용 인용 조각(금액 없는 항목).
    window_scale: 발췌 범위 배율(근거강도=추정 항목은 2 로 넓혀 유추 근거를 더 보인다)."""
    if not notes:
        return None
    text, sections = notes["text"], notes["sections"]
    number_highlights = [n for n in number_highlights if n]
    text_anchors = [a for a in text_anchors if a and len(a) >= 10]
    anchors = number_highlights + text_anchors

    sec = _match_section(sections, note_hint)
    # 1) 매칭 섹션 안에서 앵커
    if sec:
        for a in anchors:
            j = sec["text"].find(a)
            if j != -1:
                exc, trunc = _window(sec["text"], j, len(a), window_scale)
                return {"note_title": sec["label"], "excerpt": exc,
                        "offsets": _offsets(exc, number_highlights + text_anchors),
                        "truncated": trunc, "anchor": "section"}
    # 2) 전체 텍스트에서 숫자/조각으로 재앵커(주석위치가 어긋난 경우 자기교정)
    for a in anchors:
        j = text.find(a)
        if j != -1:
            exc, trunc = _window(text, j, len(a), window_scale)
            title = _note_of_pos(sections, j) or (sec["label"] if sec else note_hint)
            return {"note_title": title, "excerpt": exc,
                    "offsets": _offsets(exc, number_highlights + text_anchors),
                    "truncated": trunc, "anchor": "window"}
    # 3) 인용과 주석 본문의 최장 공통 부분문자열로 재앵커(문구가 조금 달라도 매칭 — 숫자가
    #    감사보고서에만 있고 정책 서술만 주석에 있는 KAM 항목 등).
    for a in text_anchors:
        lcs = _lcs_in_text(a, text)
        if lcs:
            j = text.find(lcs)
            exc, trunc = _window(text, j, len(lcs), window_scale)
            title = _note_of_pos(sections, j) or (sec["label"] if sec else note_hint)
            return {"note_title": title, "excerpt": exc,
                    "offsets": _offsets(exc, number_highlights + [lcs]),
                    "truncated": trunc, "anchor": "lcs"}
    # 4) 못 찾음 → None. 화면이 인용 자체를 보여준다(어긋난 주석을 억지로 띄우지 않음).
    return None


# ---------------------------------------------------------------- 항목 헬퍼
def comma_number(display):
    """금액표시('(661,733)' 등)에서 쉼표형 숫자만. 없으면 None."""
    if not display:
        return None
    m = re.search(r"\d[\d,]*", str(display))
    return m.group(0) if m else None


def longest_fragment(quote):
    """인용에서 '...'·'/'·'…' 로 끊은 가장 긴 조각(금액 없는 존재형 앵커용)."""
    if not quote:
        return None
    parts = re.split(r"\.{3}|…|\s/\s|/", str(quote))
    parts = [p.strip() for p in parts if p and p.strip()]
    return max(parts, key=len) if parts else None
