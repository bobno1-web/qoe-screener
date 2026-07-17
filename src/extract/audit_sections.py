"""연결감사보고서에서 4개 섹션 추출 (audit-issue-tracker s2_extract 재사용, 판단 없음).

USERMARK="B" 가 붙은 <p>/<span> 를 '진짜 섹션 헤더'로 보고, 화이트리스트 헤더 사이를 슬라이싱한다.
이는 계정명 키워드 매칭이 아니라 문서 구조 마커다(no-keyword-heuristics 위반 아님). 화이트리스트 밖의
하위 소제목(핵심감사사항 하위 매터 등)은 섹션을 끊지 않는다 — 끊으면 본문이 잘린다(원 리포에서 확인된 버그).
주의: 이 규칙은 특정 감사법인·회사로만 검증됨 — 회사 확장 시 재검증 필요(원 리포 docs 명시).
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

FIXED_HEADERS = {
    "감사의견",
    "감사의견근거",
    "핵심감사사항",
    "강조사항",
    "기타사항",
    "계속기업 관련 중요한 불확실성",
    "연결재무제표에 대한 경영진과 지배기구의 책임",
    "연결재무제표감사에 대한 감사인의 책임",
}

INTEREST_SECTIONS = [
    "핵심감사사항",
    "강조사항",
    "기타사항",
    "계속기업 관련 중요한 불확실성",
]

_NUMBERED_HEADER = re.compile(r"^\d+\.\s")
_INTERNAL_CONTROL_MARK = "내부회계관리제도"


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _key(text):
    return re.sub(r"\s+", "", text or "")


_FIXED_HEADERS_KEY = {_key(h) for h in FIXED_HEADERS}
_INTEREST_KEY = {_key(s): s for s in INTEREST_SECTIONS}


def _usermark(tag):
    for key, val in tag.attrs.items():
        if key.lower() == "usermark":
            return val
    return None


def _is_anchor(node):
    return (
        isinstance(node, Tag)
        and node.name.lower() in ("p", "span")
        and _usermark(node) == "B"
    )


def _is_whitelist_header(text):
    k = _key(text)
    if not k:
        return False
    if k in _FIXED_HEADERS_KEY:
        return True
    if _NUMBERED_HEADER.match(_norm(text)):
        return True
    if _INTERNAL_CONTROL_MARK in k:
        return True
    return False


def _interest_name(text):
    return _INTEREST_KEY.get(_key(text))


def extract_from_html(html: str) -> dict:
    """감사보고서 HTML/XML 텍스트 -> {섹션명: {"text", "char_len"}} (관심 4섹션만)."""
    soup = BeautifulSoup(html, "html.parser")

    header_map = {}
    for tag in soup.find_all(True):
        if _is_anchor(tag):
            label = tag.get_text(strip=True)
            if _is_whitelist_header(label):
                header_map[id(tag)] = _interest_name(label)

    sections = {}
    current = None
    for node in soup.descendants:
        if isinstance(node, Tag):
            if id(node) in header_map:
                current = header_map[id(node)]
                if current is not None:
                    sections.setdefault(current, [])
        elif isinstance(node, NavigableString):
            if current is not None:
                sections[current].append(str(node))

    result = {}
    for name in INTEREST_SECTIONS:
        if name in sections:
            text = re.sub(r"\s+", " ", "".join(sections[name])).strip()
            result[name] = {"text": text, "char_len": len(text)}
    return result


def extract(html_path) -> dict:
    return extract_from_html(Path(html_path).read_text(encoding="utf-8"))
