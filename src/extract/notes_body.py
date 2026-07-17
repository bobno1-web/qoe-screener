"""사업보고서 '재무제표 주석 본문'을 OpenDART에서 구조 앵커로 수집 (배관, 판단 없음).

[B] 참고 리포(특수관계자 모니터링)의 배관/판단 분리 결과:
  - 재사용(배관): 사업보고서 원문 ZIP 가져오기·엔트리 식별. qoe 는 이미 DartClient +
    audit_report 로 동등 배관을 보유 → 여기선 '본문 엔트리 선택 + 주석 섹션 슬라이싱'만 추가한다.
  - 재사용 안 함(판단): 그 리포의 주석 로케이터는 키워드('특수관계자' in part) 매칭뿐이고,
    특수관계자 판별(relation_type/taxonomy/컬럼롤)은 우리와 목적이 달라 가져오지 않는다.

구조 앵커(회사·업종 무관, 회계공시 표준 구조 → no-hardcoding 예외 '표준 주석 섹션 위치'):
  - 본문 엔트리: <DOCUMENT-NAME> 이 '사업보고서'(∧¬'감사보고서'). 감사보고서 사본은 audit_report 가 따로 뽑는다.
  - 주석 섹션 앵커: <TITLE ATOC="Y" ... ENG="... Notes to the consolidated financial statements">
    (= '연결재무제표 주석'). 별도는 'Notes to the separate financial statements'(= '재무제표 주석').
  - 섹션 경계: 같은 부모의 다음 형제 최상위 섹션 <TITLE ATOC="Y" AASSOCNOTE="{부모}-N-0">.
    AASSOCNOTE 숫자코드는 판본별로 바뀔 수 있어 ENG/한글 제목으로 앵커를 잡고, 경계는
    형제-섹션 구조로 잡는다(코드값 자체에 의존하지 않음).

이 모듈은 텍스트만 반환한다. 어느 항목이 비반복인지 '판정'하지 않는다(그건 surface/사람 몫).
"""
from __future__ import annotations

import io
import re
import zipfile

from .audit_report import _fiscal_year, list_business_reports  # 배관 재사용
from .dart_client import StopConditionError

_TITLE_RE = re.compile(r"<TITLE\b([^>]*)>(.*?)</TITLE>", re.S | re.I)
_ATOC_RE = re.compile(r'ATOC\s*=\s*"([^"]*)"', re.I)
_ASSOC_RE = re.compile(r'AASSOCNOTE\s*=\s*"([^"]*)"', re.I)
_ENG_RE = re.compile(r'ENG\s*=\s*"([^"]*)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# 섹션 종류별 안정 앵커(ENG 우선, 한글 보조). 회계공시 표준 문구.
_ANCHORS = {
    "consolidated": {
        "eng": "notes to the consolidated financial statements",
        "ko_all": ("연결", "주석"),
    },
    "separate": {
        "eng": "notes to the separate financial statements",
        "ko_all": ("주석",),
        "ko_none": ("연결",),
    },
}


def _document_name(xml_bytes: bytes) -> str:
    head = xml_bytes[:4000].decode("utf-8", errors="replace")
    m = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", head, re.S)
    return m.group(1).strip() if m else ""


def select_business_report_body(zip_bytes: bytes):
    """ZIP 엔트리 중 '사업보고서 본문' 하나를 고른다. 정확히 1개 아니면 실패.

    구분 근거: DOCUMENT-NAME 에 '사업보고서'∧¬'감사보고서'(연결/별도 감사보고서 사본 배제).
    반환: (entry_filename, document_name, entry_bytes).
    """
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    hits, inventory = [], []
    for info in zf.infolist():
        data = zf.read(info)
        name = _document_name(data)
        inventory.append((info.filename, name))
        if ("사업보고서" in name) and ("감사보고서" not in name):
            hits.append((info.filename, name, data))
    if len(hits) != 1:
        raise StopConditionError(
            "사업보고서 본문 단일 식별 실패. "
            f"hits={[(f, n) for f, n, _ in hits]} inventory={inventory} (STOP)")
    return hits[0]


def _label(inner: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", inner)).strip()


def _titles(text: str):
    """문서 순서대로 모든 <TITLE> 을 (start, atoc, assoc, eng, label) 로."""
    out = []
    for m in _TITLE_RE.finditer(text):
        attrs, inner = m.group(1), m.group(2)
        atoc = _ATOC_RE.search(attrs)
        assoc = _ASSOC_RE.search(attrs)
        eng = _ENG_RE.search(attrs)
        out.append({
            "start": m.start(),
            "atoc": (atoc.group(1) if atoc else "").upper(),
            "assoc": assoc.group(1) if assoc else "",
            "eng": (eng.group(1) if eng else ""),
            "label": _label(inner),
        })
    return out


def _is_anchor(t, spec) -> bool:
    eng = t["eng"].lower()
    if spec["eng"] in eng:
        return True
    lab = t["label"]
    if all(k in lab for k in spec.get("ko_all", ())) and "주석" in lab:
        if any(k in lab for k in spec.get("ko_none", ())):
            return False
        return True
    return False


def _sibling_prefix(assoc: str):
    """'D-0-3-3-0' -> 부모 'D-0-3'. 최상위 섹션 형제 판별용. 실패 시 None."""
    m = re.match(r"^(.*)-\d+-0$", assoc)
    return m.group(1) if m else None


def extract_notes_body(body_text: str, which: str = "consolidated") -> dict:
    """사업보고서 본문 텍스트 -> 지정 주석 섹션(연결/별도)의 본문 텍스트.

    반환: {"which","header","eng","assoc","text","char_len","note_titles",
           "boundary","present"}. 앵커를 못 찾으면 present=False.
    """
    spec = _ANCHORS[which]
    titles = _titles(body_text)
    atoc_titles = [t for t in titles if t["atoc"] == "Y"]

    anchor = next((t for t in atoc_titles if _is_anchor(t, spec)), None)
    if anchor is None:
        return {"which": which, "present": False, "header": None, "eng": None,
                "assoc": None, "text": "", "char_len": 0, "note_titles": [],
                "boundary": "not_found"}

    # 경계: 같은 부모의 '다음 형제 최상위 섹션'. 없으면 다음 ATOC=Y 섹션. 없으면 문서 끝.
    parent = _sibling_prefix(anchor["assoc"])
    boundary_start, boundary_kind = len(body_text), "eof"
    if parent:
        sib_re = re.compile(r"^" + re.escape(parent) + r"-\d+-0$")
        for t in atoc_titles:
            if t["start"] > anchor["start"] and sib_re.match(t["assoc"]):
                boundary_start, boundary_kind = t["start"], "sibling_section"
                break
    if boundary_kind == "eof":
        for t in atoc_titles:
            if t["start"] > anchor["start"]:
                boundary_start, boundary_kind = t["start"], "next_atoc_title"
                break

    raw_slice = body_text[anchor["start"]:boundary_start]
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw_slice)).strip()
    # 하위 주석 제목(예: '30. 특수관계자와의 거래') — '몇 번 주석' 인용 근거용. 앵커 자신은 제외.
    child = [_label(m.group(2)) for m in _TITLE_RE.finditer(raw_slice)]
    note_titles = [c for c in child[1:] if c]

    return {"which": which, "present": True, "header": anchor["label"],
            "eng": anchor["eng"], "assoc": anchor["assoc"], "text": text,
            "char_len": len(text), "note_titles": note_titles,
            "boundary": boundary_kind}


def resolve_latest_business_report(client, corp_code: str, days_back: int = 450) -> dict:
    """corp_code -> 최신 회계연도 사업보고서 filing 해석. 반환 {corp_code, rcept_no, base_year, report_nm}."""
    filings = list_business_reports(client, corp_code, days_back)
    yrs = [(_fiscal_year(f.get("report_nm")), f) for f in filings]
    yrs = [(y, f) for y, f in yrs if y is not None]
    if not yrs:
        raise StopConditionError(f"corp_code {corp_code} 사업보고서(A001) 없음 — 대상 부적격. (STOP)")
    latest = max(y for y, _ in yrs)
    cands = [f for y, f in yrs if y == latest]
    cands.sort(key=lambda f: (f.get("rcept_dt", ""), f.get("rcept_no", "")), reverse=True)
    f = cands[0]
    return {"corp_code": corp_code, "rcept_no": f.get("rcept_no"), "base_year": latest,
            "report_nm": f.get("report_nm")}


def fetch_notes_body(client, corp_code: str, which: str = "consolidated", days_back: int = 450):
    """corp_code -> (meta, 주석 섹션 dict). 최신 사업보고서 본문에서 연결(기본)/별도 주석 슬라이싱."""
    meta = resolve_latest_business_report(client, corp_code, days_back)
    zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
    entry, doc_name, data = select_business_report_body(zip_bytes)
    notes = extract_notes_body(data.decode("utf-8", errors="replace"), which=which)
    meta = {**meta, "entry": entry, "document_name": doc_name}
    return meta, notes
