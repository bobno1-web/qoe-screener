"""주석에서 D&A(감가상각비·무형자산상각비) 결정론적 추출 — EBITDA 기준선용. LLM 없음.

원칙(no-keyword-heuristics / citations-mandatory 준수):
  - 라벨 문자열('감가상각비'가 들어가면 D&A) 매칭이 아니라, 표 셀 `<TE>` 의 **개념코드 ACODE**
    (IFRS/DART 표준 XBRL 코드)로 구조 추출한다. 이는 회계기준이 정한 구조상수 → no-hardcoding 예외
    이며 fnlttSinglAcntAll 의 account_id 추출과 같은 방식이다.
  - 당기/전기는 `ACONTEXT` 의 기간토큰(CFY{연도}dFY=당기 / PFY=전기)으로 구분한다.
  - 2단 경로. (a)우선: '비용의 성격별 분류' 주석(영업비용 성격별 분해 → D&A가 영업이익에 이미 차감 = A).
    (b)대체: 성격별 주석이 없으면 유형자산 감가상각비 + 무형자산상각비 + 리스 사용권자산 감가상각비를
    개별주석에서 각각 뽑아 합산(발생위치 미명시 → C, 안내문 첨부). 개별주석 총액은 그 개념코드 당기셀 중
    절대값 최대(합계행) 로 잡는다.
  - 이중계상 가드: 개별주석 코드는 성격별 집계코드와 겹치지 않게 자산별 코드만 쓰고, 리스(ROU)가
    유형자산 주석에 '사용권자산' 컬럼으로 내포된 회사는 리스를 다시 더하지 않는다.
  - 리스 사용권자산 감가상각비는 항상 별도 줄로 둔다(누락 방지). ROU 개념코드가 없으면 유형자산 통합/부재를
    명시(지어내지 않음).
  - 어느 주석·어느 셀(라벨·개념코드·기간·원문값)에서 뽑았는지 전부 출처로 남긴다. 교차검증(성격별 vs
    개별합 vs 현금흐름표)으로 영업 밖 상각비(운휴자산·투자부동산 등)와의 차이를 드러낸다.

추출과 A/B/C 위치판정(주석이 알려주는 계상위치)만 한다 — 어떤 항목이 비반복인지 '판정'하지 않는다.
"""
from __future__ import annotations

import re

from .financials import parse_amount            # 콤마·괄호·공백 처리 재사용
from .notes_body import (
    _ANCHORS, _TITLE_RE, _is_anchor, _sibling_prefix, _titles,
    fetch_notes_body, resolve_latest_business_report, select_business_report_body,
)

# D&A 개념코드(표준 XBRL). 성격별 주석 안에서 이 코드를 가진 금액셀만 D&A 로 본다.
DA_COMBINED = {"ifrs-full_DepreciationAndAmortisationExpense"}
DA_DEPRECIATION = {
    "ifrs-full_DepreciationExpense",
    "ifrs-full_DepreciationPropertyPlantAndEquipment",
    "dart_DepreciationExpense",
}
DA_AMORTISATION = {
    "ifrs-full_AmortisationExpense",
    "ifrs-full_AmortisationIntangibleAssetsOtherThanGoodwill",
    "dart_AmortisationExpense",
}
DA_LEASE = {"ifrs-full_DepreciationRightofuseAssets"}
_DA_CONCEPT_RE = re.compile(r"(Depreciat|Amorti)", re.I)   # 성격별 주석 내부 한정 보조판별

_TE_RE = re.compile(r"<TE\b([^>]*)>(.*?)</TE>", re.S | re.I)
_TR_RE = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.S | re.I)
_ATTR = lambda a, k: (re.search(rf'{k}="([^"]*)"', a, re.I) or _NONE).group(1)  # noqa: E731


class _N:
    def group(self, *_):
        return ""


_NONE = _N()

_UNIT_MULT = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000,
              "십억원": 1_000_000_000, "조원": 1_000_000_000_000}


def _text(inner: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()


def detect_unit(segment: str):
    """'(단위 : 백만원)' -> (표시문자열, 곱수). 못 찾으면 (None, None)."""
    m = re.search(r"\(단위\s*[:：]?\s*([가-힣]+)\s*\)", segment)
    if not m:
        return None, None
    raw = m.group(1).strip()
    return raw, _UNIT_MULT.get(raw)


def _consolidated_notes_slice(body: str, which: str = "consolidated") -> str:
    spec = _ANCHORS[which]
    titles = _titles(body)
    atoc = [t for t in titles if t["atoc"] == "Y"]
    anchor = next((t for t in atoc if _is_anchor(t, spec)), None)
    if anchor is None:
        return ""
    parent = _sibling_prefix(anchor["assoc"])
    bnd = len(body)
    if parent:
        sib = re.compile(r"^" + re.escape(parent) + r"-\d+-0$")
        for t in atoc:
            if t["start"] > anchor["start"] and sib.match(t["assoc"]):
                bnd = t["start"]
                break
    return body[anchor["start"]:bnd]


def find_nature_note(notes_raw: str):
    """'비용의 성격별 분류' 주석 조각을 (제목, segment) 로. 없으면 (None, None).

    표준 주석 제목으로 위치를 잡는다(표준 주석 위치 = 구조상수). 실제 D&A 판별은 조각 안에서
    개념코드로만 한다.
    """
    child = [(m.start(), _text(m.group(2))) for m in _TITLE_RE.finditer(notes_raw)]
    for i, (pos, lab) in enumerate(child):
        if "성격별" in lab:                      # '비용의 성격별 분류'
            nxt = child[i + 1][0] if i + 1 < len(child) else len(notes_raw)
            return lab, notes_raw[pos:nxt]
    return None, None


def _period_current(acontext: str, base_year: int) -> bool:
    tok = acontext.split("_", 1)[0] if acontext else ""
    return tok.startswith(f"CFY{base_year}")


def _rows_with_da(segment: str, base_year: int):
    """성격별 주석 조각에서 (라벨, 개념코드, 당기 원문값, acontext) 행들. D&A 개념만."""
    out = []
    for rm in _TR_RE.finditer(segment):
        cells = []
        for tm in _TE_RE.finditer(rm.group(1)):
            attrs = tm.group(1)
            cells.append({
                "acode": _ATTR(attrs, "ACODE"),
                "acontext": _ATTR(attrs, "ACONTEXT"),
                "eng": _ATTR(attrs, "ENG"),
                "text": _text(tm.group(2)),
            })
        if not cells:
            continue
        label = cells[0]["text"] or cells[0]["eng"]
        for c in cells[1:]:
            if c["acode"] and _DA_CONCEPT_RE.search(c["acode"]) and _period_current(c["acontext"], base_year):
                out.append({"label": label, "eng": cells[0]["eng"], "acode": c["acode"],
                            "acontext": c["acontext"], "value_text": c["text"]})
    return out


def _classify(acode: str) -> str:
    if acode in DA_COMBINED:
        return "combined"
    if acode in DA_DEPRECIATION or acode in DA_LEASE:
        return "depreciation"
    if acode in DA_AMORTISATION:
        return "amortisation"
    # 코드 목록 밖이지만 개념상 D&A인 경우: 이름으로 대분류(성격별 주석 내부 한정)
    if re.search(r"Amorti", acode, re.I):
        return "amortisation"
    return "depreciation"


# A/B/C 중 (C) 안내문 — 발생위치 미명시분을 영업 가정으로 가산할 때 원문보기에 첨부.
NOTICE_C = ("상각비의 발생 위치에 대한 구체적 언급이 없으므로, 영업에서 발생한 것으로 "
            "가정하여 가산한 수치입니다.")

# 개별 자산주석 총액용 개념코드 — 성격별 집계코드(DA_COMBINED / DepreciationExpense·
# AmortisationExpense)와 겹치지 않게 자산별 코드만 쓴다(같은 값을 두 경로에서 잡아 이중계상하는 것을 방지).
CODE_PPE = ("ifrs-full_DepreciationPropertyPlantAndEquipment",)
CODE_INTANGIBLE = ("ifrs-full_AmortisationIntangibleAssetsOtherThanGoodwill",)
CODE_ROU = ("ifrs-full_DepreciationRightofuseAssets",)
CODE_INVPROP = ("ifrs-full_DepreciationInvestmentProperty",)
CODE_CF_DEP = ("ifrs-full_AdjustmentsForDepreciationExpense",)      # 현금흐름표 가산 감가상각비(교차검증)
CODE_CF_AMORT = ("ifrs-full_AdjustmentsForAmortisationExpense",)    # 현금흐름표 가산 무형자산상각비(교차검증)


def _titles_pos(notes_raw: str):
    return [(m.start(), _text(m.group(2))) for m in _TITLE_RE.finditer(notes_raw)]


def _note_of(titles, pos: int) -> str:
    """문서 위치 pos 를 감싸는 최근 상위 주석 제목."""
    cur = ""
    for s, lab in titles:
        if s <= pos and lab:
            cur = lab
        elif s > pos:
            break
    return cur


def _note_segment(notes_raw: str, titles, note_label: str) -> str:
    for i, (s, lab) in enumerate(titles):
        if lab == note_label:
            nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes_raw)
            return notes_raw[s:nxt]
    return ""


def _da_cells(notes_raw: str, titles, base_year: int):
    """전체 주석에서 당기 D&A 개념코드(<TE ACODE=...>) 셀을 그 셀이 속한 주석과 함께 수집."""
    cells = []
    for trm in _TR_RE.finditer(notes_raw):
        row = []
        for tm in _TE_RE.finditer(trm.group(1)):
            a = tm.group(1)
            row.append({"acode": _ATTR(a, "ACODE"), "acontext": _ATTR(a, "ACONTEXT"),
                        "text": _text(tm.group(2))})
        if not row:
            continue
        label = row[0]["text"]
        for c in row:
            if (c["acode"] and _DA_CONCEPT_RE.search(c["acode"])
                    and _period_current(c["acontext"], base_year)):
                cells.append({"note": _note_of(titles, trm.start()), "label": label,
                              "acode": c["acode"], "acontext": c["acontext"],
                              "value_text": c["text"], "value": parse_amount(c["text"])})
    return cells


def _src_cell(cell: dict, unit_str) -> dict:
    return {"주석위치": cell["note"], "항목": cell["label"],
            "인용": f'{cell["label"]} {cell["value_text"]}'.strip(),
            "개념코드": cell["acode"],
            "기간": cell["acontext"].split("_", 1)[0] if cell["acontext"] else "",
            "단위": unit_str, "원문값": cell["value_text"]}


def _component(notes_raw, titles, cells, codes):
    """개별주석 총액 = 해당 개념코드의 당기 셀 중 절대값 최대(=합계행). 부호는 표시방식(증감표는 음수)
    차이일 뿐이라 절대값을 쓴다. 없으면 None. 총액이 어느 주석·어느 셀에서 나왔는지 출처를 남긴다."""
    grp = [c for c in cells if c["acode"] in codes and c["value"] is not None]
    if not grp:
        return None
    best = max(grp, key=lambda c: abs(c["value"]))
    seg = _note_segment(notes_raw, titles, best["note"])
    ustr, umult = detect_unit(seg)
    val = abs(best["value"])
    return {"note": best["note"], "value_display": val, "unit": ustr, "unit_multiplier": umult,
            "value_won": (val * umult) if umult is not None else None,
            "n_cells": len(grp),
            "distinct_abs": [str(x) for x in sorted({abs(c["value"]) for c in grp}, reverse=True)[:8]],
            "source": _src_cell(best, ustr)}


def _won(display, mult):
    return (display * mult) if (display is not None and mult is not None) else None


def extract_da(notes_raw: str, base_year: int) -> dict:
    """당기 D&A 를 EBITDA 가산용으로 추출한다. 2단 경로 + A/B/C 판정 + 리스 별도줄 + 교차검증.

    경로(a) 우선: '비용의 성격별 분류' 주석의 D&A(영업비용 성격별 분해 → 영업이익에 이미 차감 = A).
    경로(b) 대체: 성격별 주석이 없으면 유형자산 감가상각비 + 무형자산상각비 + 리스 사용권자산
                  감가상각비를 개별주석에서 각각 뽑아 합산(발생위치 미명시 → C, 안내문 첨부).
    개별 자산주석 총액(유형/무형/리스/투자부동산)은 두 경로 모두에서 뽑아 리스 별도줄·내역·교차검증에 쓴다.
    추정하지 않는다. 못 뽑으면 present=False + 사유.
    """
    titles = _titles_pos(notes_raw)
    cells = _da_cells(notes_raw, titles, base_year)

    ppe = _component(notes_raw, titles, cells, CODE_PPE)
    intan = _component(notes_raw, titles, cells, CODE_INTANGIBLE)
    rou = _component(notes_raw, titles, cells, CODE_ROU)
    invp = _component(notes_raw, titles, cells, CODE_INVPROP)
    cf_dep = _component(notes_raw, titles, cells, CODE_CF_DEP)
    cf_amort = _component(notes_raw, titles, cells, CODE_CF_AMORT)

    # 리스 별도줄: ROU 개념코드가 있으면 별도 추출, 없으면 유형자산 주석 통합(사용권자산 컬럼) 여부로 안내.
    if rou is not None:
        lease = {"present": True, "mode": "별도개념코드", "value_won": rou["value_won"],
                 "value_display": rou["value_display"], "unit": rou["unit"],
                 "source": rou["source"],
                 "note": "리스(사용권자산) 주석에서 DepreciationRightofuseAssets 로 별도 추출."}
    else:
        ppe_seg = _note_segment(notes_raw, titles, ppe["note"]) if ppe else ""
        integrated = "사용권" in ppe_seg
        lease = {"present": False,
                 "mode": "유형자산통합" if integrated else "미검출",
                 "value_won": None, "value_display": None, "unit": None, "source": None,
                 "note": ("리스 사용권자산 감가상각비: 별도 개념코드(DepreciationRightofuseAssets) 미검출. "
                          + ("유형자산 주석에 '사용권자산' 컬럼으로 통합 표시(예: 항공기 리스) → 유형자산 "
                             "합계·성격별 합계에 이미 포함. 별도 분리 불가."
                             if integrated else
                             "유형자산 주석에도 사용권자산 표기 없음 → 리스 상각이 없거나 단기·소액리스만일 수 있음. "
                             "성격별 합계엔 있으면 포함됨. 지어내지 않음."))}

    # 전체 D&A 셀(투명성/인용): 주석별로 나열
    all_by_note = [{"주석": c["note"], "항목": c["label"], "개념코드": c["acode"],
                    "기간": c["acontext"].split("_", 1)[0] if c["acontext"] else "",
                    "원문값": c["value_text"]} for c in cells]

    # 리스 ROU 가 유형자산 주석 총액에 내포됐나? (일부 회사는 사용권자산을 유형자산 주석에 품어 표시.
    # 그러면 유형자산 총액에 ROU 가 이미 포함 → 리스를 또 더하면 이중계상.) 구조 신호: 유형자산
    # 주석 조각에 '사용권' 컬럼이 있고, 그 안에 ROU 총액과 정확히 일치하는 당기 셀이 있으면 내포로 본다.
    rou_nested = False
    if ppe is not None and rou is not None:
        ppe_seg = _note_segment(notes_raw, titles, ppe["note"])
        if "사용권" in ppe_seg:
            ppe_note_vals = {abs(c["value"]) for c in cells
                             if c["note"] == ppe["note"] and c["value"] is not None}
            rou_nested = ppe["value_display"] in ppe_note_vals and rou["value_display"] in ppe_note_vals

    lines = []
    reason = None
    nat_title, seg = find_nature_note(notes_raw)

    if seg is not None:
        # ---------- 경로 (a): 성격별 주석 ----------
        path, nat_unit, nat_mult = "성격별", *detect_unit(seg)
        rows = _rows_with_da(seg, base_year)
        combined = [r for r in rows if r["acode"] in DA_COMBINED]
        op_display = None
        if not rows:
            path, reason = None, "성격별 주석은 있으나 당기 D&A 개념코드 셀 없음. 추정 안 함."
            method = None
        elif combined:
            method = "성격별-combined"
            r = combined[0]
            op_display = parse_amount(r["value_text"])
            lines.append({"kind": "감가상각비 및 무형자산상각비(성격별 합계)", "role": "성격별-집계",
                          "value_display": op_display, "value_won": _won(op_display, nat_mult),
                          "unit": nat_unit, "inclusion": "A",
                          "inclusion_basis": "비용의 성격별 분류 = 영업비용의 성격별 분해 → 상각비가 영업이익에 이미 차감됨.",
                          "added": True, "notice": None, "source": _src(nat_title, r, nat_unit)})
        else:
            method = "성격별-sum"
            op_display = sum((parse_amount(r["value_text"]) or 0) for r in rows)
            for r in rows:
                v = parse_amount(r["value_text"])
                lines.append({"kind": r["label"], "role": "성격별-집계",
                              "value_display": v, "value_won": _won(v, nat_mult),
                              "unit": nat_unit, "inclusion": "A",
                              "inclusion_basis": "비용의 성격별 분류 = 영업비용의 성격별 분해 → 영업이익에 이미 차감됨.",
                              "added": True, "notice": None, "source": _src(nat_title, r, nat_unit)})
        operating_won = _won(op_display, nat_mult)
        unit = nat_unit

        # 개별주석 내역줄(감가/무형/리스): 성격별 합계에 이미 포함 → 표시·검증용, 재가산 안 함(이중계상 방지).
        # 성격별 총액이 실제로 잡혔을 때만(=path 유지) 붙인다.
        for comp, kind in (((ppe, "감가상각비(유형자산 주석)"), (intan, "무형자산상각비(무형자산 주석)"))
                           if path == "성격별" else ()):
            if comp:
                lines.append({"kind": kind, "role": "개별내역", "value_display": comp["value_display"],
                              "value_won": comp["value_won"], "unit": comp["unit"], "inclusion": "A",
                              "inclusion_basis": "개별주석 총액(내역). 성격별 영업 D&A 합계에 포함되어 이미 가산됨.",
                              "added": False, "notice": "성격별 합계에 포함 — 개별 재가산 시 이중계상(미가산).",
                              "source": comp["source"]})
        if path == "성격별" and lease["present"]:
            lines.append({"kind": "리스 사용권자산 감가상각비", "role": "개별내역",
                          "value_display": lease["value_display"], "value_won": lease["value_won"],
                          "unit": lease["unit"], "inclusion": "A",
                          "inclusion_basis": "사용권자산 감가상각비(내역). 성격별 영업 D&A 합계에 포함됨.",
                          "added": False, "notice": "성격별 합계에 포함 — 개별 재가산 시 이중계상(미가산).",
                          "source": lease["source"]})

    elif ppe or intan or rou:
        # ---------- 경로 (b): 성격별 주석 부재 → 개별주석 합산 ----------
        path, method = "개별주석", "개별주석-sum"
        op_won = 0
        any_missing_unit = False
        for comp, kind in ((ppe, "감가상각비(유형자산)"), (intan, "무형자산상각비"),
                           (rou, "리스 사용권자산 감가상각비")):
            if not comp:
                continue
            # 리스 ROU 가 유형자산 총액에 내포된 회사면 리스를 또 더하지 않는다(이중계상 방지).
            nested = (comp is rou) and rou_nested
            if comp["value_won"] is None:
                any_missing_unit = True
            elif not nested:
                op_won += comp["value_won"]
            lines.append({"kind": kind, "role": "개별합산", "value_display": comp["value_display"],
                          "value_won": comp["value_won"], "unit": comp["unit"], "inclusion": "C",
                          "inclusion_basis": ("유형자산 주석에 사용권자산으로 통합 표시 → 유형자산 총액에 이미 포함(중복 방지). "
                                              "이 줄은 표시용이며 재가산하지 않음."
                                              if nested else
                                              "개별주석은 상각비 발생 위치(영업/영업외)를 명시하지 않음 → 영업 가정하여 가산(C)."),
                          "added": not nested,
                          "notice": None if nested else NOTICE_C, "source": comp["source"]})
        if not lease["present"] and rou is None:
            # 리스 별도줄 부재를 명시적으로 남긴다(누락 아님을 증명).
            lines.append({"kind": "리스 사용권자산 감가상각비", "role": "개별합산",
                          "value_display": None, "value_won": None, "unit": None, "inclusion": "C",
                          "inclusion_basis": lease["note"], "added": False, "notice": None, "source": None})
        operating_won = op_won if op_won else None
        op_display = None
        unit = (ppe or intan or rou)["unit"]
        if any_missing_unit:
            reason = "개별주석 일부 단위 미검출 → 원 단위 정합 불가분 존재(가산 제외)."
    else:
        path, method, operating_won, op_display, unit = None, None, None, None, None
        reason = "성격별 주석·개별 자산주석 모두에서 당기 D&A 개념코드 미검출. 추정 안 함 → 추출 불가."

    # 투자부동산 감가상각비: 통상 영업 밖(임대) → (B) 참고, 미가산.
    if invp:
        lines.append({"kind": "감가상각비(투자부동산)", "role": "참고", "value_display": invp["value_display"],
                      "value_won": invp["value_won"], "unit": invp["unit"], "inclusion": "B",
                      "inclusion_basis": "투자부동산 감가상각비는 통상 임대(영업 밖) → 영업이익에 없어 가산 대상 아님(B).",
                      "added": False, "notice": None, "source": invp["source"]})

    # ---------- 교차검증: 성격별(영업) vs 개별합(유형+무형+리스) vs 현금흐름표(감가+무형) ----------
    # 리스가 유형자산에 내포된 회사는 리스를 개별합에서 빼야 이중계상이 안 된다(유형 총액에 이미 포함).
    indiv_comps = (ppe, intan) if rou_nested else (ppe, intan, rou)
    parts = [c["value_won"] for c in indiv_comps if c and c["value_won"] is not None]
    indiv_sum = sum(parts) if parts else None
    cf_sum = None
    cfp = [c["value_won"] for c in (cf_dep, cf_amort) if c and c["value_won"] is not None]
    if cfp:
        cf_sum = sum(cfp)
    delta = (operating_won - indiv_sum) if (operating_won is not None and indiv_sum is not None) else None
    cross = {
        "성격별_영업D&A_won": operating_won if path == "성격별" else None,
        "개별합_유형무형리스_won": indiv_sum,
        "현금흐름표_감가무형_won": cf_sum,
        "델타_성격별_minus_개별합_won": delta,
        "델타_해석": ("개별합이 성격별(영업)보다 크면 그 차이는 영업 밖에서 난 상각비(예: 운휴자산상각비·"
                     "투자부동산)와 자본화분 — 영업이익에 없어 가산 안 함. 부호·크기는 원값으로 확인."),
        "리스_유형자산에_내포": rou_nested,
        "components_won": {"유형자산": ppe["value_won"] if ppe else None,
                           "무형자산": intan["value_won"] if intan else None,
                           "리스사용권": rou["value_won"] if rou else None,
                           "투자부동산": invp["value_won"] if invp else None},
        "all_da_cells_by_note": all_by_note,
    }

    return {
        "present": operating_won is not None,
        "path": path,
        "method": method,
        "note_title": nat_title,
        "unit": unit,
        "operating_da_display": op_display,
        "operating_da_won": operating_won,      # EBITDA 가산액(원)
        "total_da_won": operating_won,          # 하위호환 별칭
        "lines": lines,                          # 감가/무형/리스 각 줄: A/B/C·가산여부·출처
        "lease": lease,                          # 리스 별도줄 요약(통합/미검출 포함)
        "cross_check": cross,
        "reason": reason,
    }


def _src(note_title, row, unit_str):
    return {
        "주석위치": note_title,
        "항목": row["label"],
        "인용": f'{row["label"]} {row["value_text"]}'.strip(),
        "개념코드": row["acode"],
        "기간": row["acontext"].split("_", 1)[0] if row["acontext"] else "",
        "단위": unit_str,
        "원문값": row["value_text"],
    }


def fetch_da(client, corp_code: str, which: str = "consolidated", days_back: int = 450):
    """corp_code -> (meta, D&A dict). 최신 사업보고서 본문의 (연결)주석에서 성격별 D&A 추출."""
    meta = resolve_latest_business_report(client, corp_code, days_back)
    zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
    entry, doc_name, data = select_business_report_body(zip_bytes)
    body = data.decode("utf-8", errors="replace")
    notes_raw = _consolidated_notes_slice(body, which=which)
    da = extract_da(notes_raw, meta["base_year"])
    meta = {**meta, "entry": entry, "document_name": doc_name, "notes_scope": which}
    return meta, da
