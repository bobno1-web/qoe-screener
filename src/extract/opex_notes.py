"""2차 스윕(상단 전용)용 — 영업비용을 구성하는 주석 섹션을 '표 산술 정합'으로 식별한다.

왜 이렇게 고르나(no-keyword-heuristics 준수):
- 영업이익 안(상단)에 파묻힌 일회성(재고평가손익·대손상각비·충당부채 전입·구조조정비 등)은 매출원가·
  판매비와관리비를 구성하는 주석에 있다. 전체 주석을 한 번에 훑는 1차 스윕은 이런 덜 두드러진 항목을
  지나치기 쉽다. 그래서 '영업비용을 구성하는 주석'만 따로 골라 2차 스윕에 넘긴다.
- 주석 선정은 **계정명 키워드('판관비'라는 글자 찾기)가 아니라 표 산술 정합**으로 한다: 영업비용 구성
  주석(비용의 성격별 분류·매출원가 명세·판매비와관리비 명세)은 그 총액(그 섹션의 당기 최댓값 셀)이
  손익계산서의 영업비용 라인 — 매출원가 / 판매비와관리비 / 둘의 합(=영업비용) — 과 산술로 맞는다.
  이 정합이 구조 신호다. containment(표 산술)·D&A(개념코드) 추출과 같은 계열이며, 회사마다 주석 번호·
  제목이 달라도 숫자가 맞으면 잡힌다.
- 하나도 식별 못 하면(정합 0) 그 회사는 2차 스윕을 **건너뛰고 정직하게 기록**한다(추측으로 아무 주석이나
  넣지 않는다). 어느 항목이 일회성인지는 판정하지 않는다 — LLM 발굴 + 사람 판정. 여기선 '어느 주석이
  영업비용을 구성하나'만 산술로 고른다.

이 모듈은 표준 재무 라인(매출원가·판관비 등)을 XBRL 개념코드로 찾고(financials.detect), 주석 섹션 총액과
산술로 대조할 뿐이다 — 회사맞춤 로직·계정명 목록 없음.
"""
from __future__ import annotations

import re

import re

from . import financials as F
from .da_notes import (
    _TE_RE, _TR_RE, _ATTR, _consolidated_notes_slice, _period_current,
    _text, _titles_pos, detect_unit,
)
from .notes_body import resolve_latest_business_report, select_business_report_body

# 판매비와관리비(표준 XBRL). 매출원가·매출·영업이익은 quality/financials 스펙 재사용.
SGA = {
    "concept": "판매비와관리비", "sj_div": ("IS", "CIS"),
    "ids": ("dart_TotalSellingGeneralAdministrativeExpenses",),
    "nm": ("판매비와관리비", "판매비와 관리비", "판매관리비"),
}

# Tier 2 구조 신호 — 영업비용에 파묻힌 일회성을 담는 '증감(movement)' 표준 XBRL 개념코드(계정명
# 키워드 아님, 개념코드 대조 = no-keyword-heuristics 예외, D&A 의 `Depreciat|Amorti` 와 같은 계열 판별).
# 요약 주석(성격별·판관비)은 이런 성분(재고평가·대손·충당부채 전입환입)을 '기타'로 뭉쳐 항목화하지
# 않으므로, 그 성분이 항목화된 상세 주석(재고자산·매출채권 손상·충당부채)을 개념코드로 잡는다.
# 실측 근거: SK 재고평가환입=ifrs-full_ReversalOfInventoryWritedown, 삼성 대손=dart_*CreditLoss*/
# *BadDebt*, 충당부채 전입=*AdditionalProvisions*/*ProvisionUsed*/*UnusedProvision*.
# 잔액·보증·자산처분 코드는 일부러 뺀다(Provision→ProvisionOfGuarantees[특수관계자], Retirement→
# DisposalsAndRetirement[자산처분] 오매칭 방지 — 그런 것까지 넣으면 스윕이 주석 절반으로 비대해져
# 집중이 무너진다). 상세 주석이 영업/영업외 어디로 갔는지는 여기서 판정하지 않는다 — 배치는 표시위치
# 게이트가 verbatim 근거로 정한다(거짓 상단 방어 유지). 여기선 '영업비용 성분 주석인가'만 구조로 고른다.
OPEX_COMPONENT_RE = re.compile(
    r"(InventoryWritedown|ReversalOfInventory|"                       # 재고평가손실·환입
    r"CreditLoss|BadDebt|"                                            # 대손상각(환입)
    r"AdditionalProvision|ProvisionUsed|UnusedProvision|ReversalOfProvision|"  # 충당부채 전입·사용·환입
    r"Severance)", re.I)                                              # 명예퇴직·구조조정


def opex_targets_from_raw(raw: dict) -> dict:
    """base-year 전체 재무제표(fnlttSinglAcntAll)에서 영업비용 정합 타깃(원)을 뽑는다.

    total_opex = 매출원가 + 판관비 (둘 다 있으면), 없으면 매출 − 영업이익(=영업비용) 폴백.
    전부 표준 개념코드 우선(financials.detect). 값 없으면 None(추정 안 함).
    """
    from src.screen import quality as Q

    def amt(spec):
        a = F.detect(raw, spec).get("amount")
        return int(a) if a is not None else None

    cos = amt(Q.COST_OF_SALES)
    sga = amt(SGA)
    rev = amt(Q.REVENUE)
    oi = amt(F.OPERATING_INCOME)
    if cos is not None and sga is not None:
        total = cos + sga
    elif rev is not None and oi is not None:
        total = rev - oi          # 매출원가 + 판관비 = 매출 − 영업이익
    else:
        total = None
    return {"cost_of_sales": cos, "sga": sga, "revenue": rev, "operating_income": oi,
            "total_opex": total}


def _section_max_current_won(segment: str, base_year: int):
    """섹션의 당기(ACONTEXT=CFY{base_year}) 숫자 셀 중 절대값 최대를 원으로. 단위 못 찾으면 None.

    섹션 총액행(성격별 합계·매출원가 합계 등)은 그 섹션에서 당기 절대값이 가장 큰 셀이다 — 이것을
    영업비용 IS 라인과 대조한다(작은 구성값이 우연히 타깃과 맞아 오인되는 것을 방지)."""
    ustr, umult = detect_unit(segment)
    if umult is None:
        return None, ustr, umult
    best = None
    for trm in _TR_RE.finditer(segment):
        for tm in _TE_RE.finditer(trm.group(1)):
            attrs = tm.group(1)
            ctx = _ATTR(attrs, "ACONTEXT")
            if not _period_current(ctx, base_year):
                continue
            v = F.parse_amount(_text(tm.group(2)))
            if v is None:
                continue
            av = abs(int(v))
            if best is None or av > best:
                best = av
    if best is None:
        return None, ustr, umult
    return best * umult, ustr, umult


def _section_component_codes(segment: str, base_year: int):
    """섹션 안 당기 셀들의 영업비용 성분 개념코드 계열(OPEX_COMPONENT_RE 일치)을 모은다."""
    hit = set()
    for trm in _TR_RE.finditer(segment):
        for tm in _TE_RE.finditer(trm.group(1)):
            attrs = tm.group(1)
            code = _ATTR(attrs, "ACODE")
            if not code or not OPEX_COMPONENT_RE.search(code):
                continue
            if _period_current(_ATTR(attrs, "ACONTEXT"), base_year):
                hit.add(code)
    return sorted(hit)


def _reconciles(value_won: int, target_won: int) -> bool:
    """섹션 총액이 타깃(영업비용 라인)과 맞나. 주석은 단위 반올림(백만원 등), IS 는 원 정밀 →
    상대오차 0.3% 또는 500만원 이내면 정합으로 본다(우연 일치 방지 위해 느슨하지 않게)."""
    if not value_won or not target_won:
        return False
    diff = abs(value_won - target_won)
    return diff <= max(5_000_000, 0.003 * abs(target_won))


def select_opex_note_sections(notes_raw: str, base_year: int, targets: dict) -> dict:
    """주석(raw HTML slice)에서 영업비용 구성 섹션을 표 산술 정합으로 고른다.

    반환 {applied, reason, selection_method, targets, sections:[{title, matched, value_won, char_len}], text}.
    applied=False 면 sections=[] · text="" (2차 스윕 건너뜀).
    """
    tset = [("total_opex", targets.get("total_opex")),
            ("cost_of_sales", targets.get("cost_of_sales")),
            ("sga", targets.get("sga"))]
    tset = [(k, v) for k, v in tset if v]
    if not notes_raw or not tset:
        return {"applied": False, "reason": "영업비용 IS 라인(매출원가·판관비·영업비용) 정합 타깃 없음 — "
                "주석 선정 불가(건너뜀).", "selection_method": "표산술정합", "targets": targets,
                "sections": [], "text": ""}

    titles = _titles_pos(notes_raw)
    sections = []
    seen_titles = set()
    for i, (pos, lab) in enumerate(titles):
        if not lab or lab in seen_titles:
            continue
        nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes_raw)
        seg = notes_raw[pos:nxt]
        # Tier 1 — 섹션 총액이 영업비용 IS 라인과 산술 정합(요약 주석: 성격별·매출원가·판관비).
        val_won, ustr, umult = _section_max_current_won(seg, base_year)
        matched = next((k for k, tv in tset if val_won is not None and _reconciles(val_won, tv)), None)
        # Tier 2 — 섹션에 영업비용 성분 개념코드가 있음(상세 주석: 재고자산·매출채권 손상·충당부채·종업원급여).
        codes = _section_component_codes(seg, base_year)
        if not matched and not codes:
            continue
        seen_titles.add(lab)
        body = _text(seg)
        sections.append({"title": lab, "tier": (1 if matched else 2),
                         "matched_target": matched, "value_won": val_won,
                         "component_codes": codes, "unit": ustr,
                         "char_len": len(body), "_text": body})

    if not sections:
        return {"applied": False, "reason": "영업비용 구성 주석을 구조(표 산술 정합·성분 개념코드)로 "
                "식별하지 못함 — 2차 스윕 건너뜀.",
                "selection_method": "표산술정합+성분개념코드", "targets": targets,
                "sections": [], "text": ""}

    text = "\n\n".join(f"[{s['title']}]\n{s['_text']}" for s in sections)
    public = [{k: v for k, v in s.items() if k != "_text"} for s in sections]
    n1 = sum(1 for s in sections if s["tier"] == 1)
    return {"applied": True, "reason": None,
            "selection_method": "표산술정합+성분개념코드", "targets": targets,
            "tier1_count": n1, "tier2_count": len(sections) - n1,
            "sections": public, "text": text}


# 재고평가손실/환입 개념코드 — IAS 2.34: 재고자산 평가손실(환입)은 매출원가로 인식된다(=영업이익 안·상단).
# 표준 XBRL 개념코드(계정명 키워드 아님, D&A 의 개념코드 계열과 같은 방식). ACODE 속성 안에서만 찾는다.
_INV_WRITEDOWN_ACODE = re.compile(
    r'ACODE="[^"]*(?:Writedown\w*Inventor|Inventor\w*Writedown|Reversal\w*Inventor|Inventor\w*Reversal)[^"]*"',
    re.I)
# 현금흐름표 섹션은 근거에서 제외 — 재고평가 개념코드가 비현금 조정으로 들어 있으나, 대손·충당부채 등
# 다른 조정 금액도 함께 담아 상단 근거로 쓰면 하단성 항목까지 오인정될 위험. 구조로 식별(CF 개념코드).
_CF_STATEMENT_ACODE = re.compile(r'ACODE="[^"]*CashFlowsFromUsedIn[^"]*"', re.I)


def above_line_evidence_text(notes_raw: str, base_year: int, targets: dict) -> tuple:
    """상단(영업이익 안) 표 구조 근거용 발췌. 후보 금액이 여기 있으면 매출원가/판관비 구성 표(또는 IAS 2 상
    매출원가로 인식되는 재고평가) 안에 계상된 것이라 상단 근거로 인정한다(문자열 스티치 대신 표 구조).

    포함 기준(둘 다 구조 신호 — 계정명 키워드 아님):
      ① 섹션 당기 최댓값 셀이 IS 매출원가/판관비/영업비용과 산술 정합 → 그 섹션은 영업비용 구성 표.
      ② 섹션에 재고평가손실/환입 표준 개념코드(IAS 2.34 매출원가 인식) 존재.
    ②는 재고평가에 한정한다 — 재고평가는 회계기준상 매출원가로 인식돼 상단이 확정적이기 때문. 충당부채·
    대손 등은 상단/하단이 갈릴 수 있어 포함하지 않는다(명백한 것만 살림 — 거짓 상단 0 유지).
    반환 (text, section_titles)."""
    titles = _titles_pos(notes_raw)
    tset = [(k, v) for k, v in [("total_opex", targets.get("total_opex")),
                                ("cost_of_sales", targets.get("cost_of_sales")),
                                ("sga", targets.get("sga"))] if v]
    incl = []
    seen = set()
    for i, (pos, lab) in enumerate(titles):
        if not lab or lab in seen:
            continue
        nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes_raw)
        seg = notes_raw[pos:nxt]
        if _CF_STATEMENT_ACODE.search(seg):      # 현금흐름표 섹션 제외(다른 조정 금액 오인정 방지)
            continue
        val, _u, _m = _section_max_current_won(seg, base_year)
        reconciles = val is not None and any(_reconciles(val, tv) for _k, tv in tset)
        has_inv_writedown = bool(_INV_WRITEDOWN_ACODE.search(seg))
        if reconciles or has_inv_writedown:
            seen.add(lab)
            incl.append((lab, _text(seg), "산술정합" if reconciles else "재고평가개념코드"))
    text = "\n\n".join(f"[{t}]\n{b}" for t, b, _r in incl)
    return text, [{"title": t, "basis": r} for t, _b, r in incl]


def fetch_above_line_evidence(corp_code: str, base_year: int, targets: dict, api_key: str,
                              which: str = "consolidated", days_back: int = 450) -> dict:
    """corp_code → 상단 표 구조 근거 발췌(캐시된 zip). 실패 시 빈 결과(게이트는 verbatim 만으로 작동)."""
    try:
        from pathlib import Path

        from .dart_client import DartClient
        project_root = Path(__file__).resolve().parents[2]
        cache = project_root / "out" / "_raw"
        client = DartClient(api_key=api_key or "", raw_dir=cache, cache_dir=cache, project_root=project_root)
        meta = resolve_latest_business_report(client, corp_code, days_back)
        zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
        _, _, data = select_business_report_body(zip_bytes)
        notes_raw = _consolidated_notes_slice(data.decode("utf-8", errors="replace"), which=which)
        text, sections = above_line_evidence_text(notes_raw, base_year, targets)
        return {"text": text, "sections": sections}
    except Exception:      # noqa: BLE001
        return {"text": "", "sections": []}


def fetch_opex_context(client, corp_code: str, base_year: int, targets: dict,
                       which: str = "consolidated", days_back: int = 450) -> dict:
    """corp_code -> 영업비용 구성 주석 섹션 선정 결과. 최신 사업보고서 본문 raw 주석에서 슬라이싱.

    zip 은 audit/notes 수집에서 이미 캐시됨(추가 네트워크 없음). targets 는 opex_targets_from_raw 결과.
    """
    meta = resolve_latest_business_report(client, corp_code, days_back)
    zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
    _, _, data = select_business_report_body(zip_bytes)
    notes_raw = _consolidated_notes_slice(data.decode("utf-8", errors="replace"), which=which)
    sel = select_opex_note_sections(notes_raw, base_year, targets)
    sel["base_year"] = base_year
    sel["rcept_no"] = meta["rcept_no"]
    return sel
