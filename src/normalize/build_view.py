"""normalize 1단계: 앞 루프 산출물(screen·surface·D&A/ebitda)을 회사별 '화면용 단일 JSON'으로
합친다. 결정론적·LLM 없음. 판정/임계/색은 넣지 않는다 — 화면이 사람에게 원값을 보여줄 뿐이다.

무엇을 합치나 (모두 out/ 의 최신 파일, 없으면 생략 = graceful degradation):
- ebitda_{stock}_*.json  → 구역 A(EBITDA 브릿지): 영업이익 + D&A 가산내역(각 원문 출처).  [필수]
- surface_{stock}_*.json  → 구역 B/C 후보: 표시위치=상단·조정성격=조정대상 → B, 나머지 → C. (surface/2)
- screen_{stock}_*.json   → 다년 영업이익 vs 영업현금흐름 괴리 게이트(참고 패널).

무엇을 '안' 하나 (철칙):
- 후보의 조정성격/표시위치/손익방향/금액을 코드가 다시 판정하지 않는다. surface 산출물의 태그를
  그대로 읽는다(no-keyword-heuristics·no-hardcoding). 금액은 surface 가 인용에서 뽑은 '금액표시'를
  받아 '인용에 실제로 들어 있는 숫자인지'만 검증한다(citations-mandatory: 헛숫자 차단).
- 조정 대상 성격 판정을 코드가 하지 않는다. 배치(표시위치=상단·조정대상만 B)만 규칙으로 하고,
  실제 반영 여부는 화면에서 사람이 체크한다.

병합(#6, 표시·통합만): repeat 3 이 같은 경제사건을 회차마다 다른 문구로 2~3번 올린다. '같은 금액 +
같은 주석번호'(존재형은 '같은 주석 + 인용 앞부분')라는 구조 신호로만 병합한다 — 새 키워드 목록 없음.
대표=재현수 많은 것>인용 충실. 회차 집합 union 으로 재현배지 갱신. 금액/부호/조정성격 태그는 그대로.

부호 규약(재계산용, 불변): 손익방향=이익 → 제외 시 EBITDA 에서 뺀다(sign=-1). 손익방향=비용 →
도로 더한다(sign=+1). 방향/금액이 불명이면 토글 불가(재계산에서 제외).

원문보기(#5): notes_context 로 각 항목의 넓은 원문 발췌 + 하이라이트를 붙인다(캐시 우선, 없으면 생략).

운용리스 배너: D&A 를 개별주석 합산 경로(b)로 구한 회사(성격별 주석 없음)는 운용리스(리스아웃) 자산
감가가 별도 계상돼 빠졌을 수 있다(docs/limitations.md §1). '경로 b' 구조 신호로만 켠다(회사명 아님).

사용:
  set -a; source ../.env; set +a
  python src/normalize/build_view.py --stock-code 000660     # out/ 최신 3종 자동선택
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
OUT_DIR = PROJECT_ROOT / "out"

from src.normalize import notes_context as nctx  # noqa: E402
from src.extract import period_notes  # noqa: E402  — 기간(당기/전기) 게이트

WARN_GENERAL = ("EBITDA 계산 금액은 프로그램 산출값이므로 오류가 있을 수 있습니다. "
                "원문을 확인하십시오.")
WARN_OPLEASE = ("운용리스 자산 감가상각이 별도 계상되었을 수 있습니다. 원문 확인 요망. "
                "(성격별 주석이 없어 개별주석 합산 경로로 D&A 를 구한 회사입니다 — docs/limitations.md §1)")

UNIT_TO_WON = {"백만원": 1_000_000, "천원": 1_000, "원": 1}


# ---------------------------------------------------------------- 파일 선택
def _latest(kind: str, stock: str) -> Path | None:
    cands = sorted(OUT_DIR.glob(f"{kind}_{stock}_*.json"))
    return cands[-1] if cands else None


def _load(path: Path | None):
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 금액 파싱
def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def parse_amount(disp, unit, quote):
    """surface 의 금액표시→원. '인용'에 그 숫자가 실제로 있는지 검증(헛숫자 차단).
    반환 (won:int|None, million:float|None, reason:str|None)."""
    if not disp or str(disp).strip() in ("", "불명", "해당없음"):
        return None, None, "금액표시_없음"
    d = _digits(str(disp))
    if not d:
        return None, None, "숫자_없음"
    if d not in _digits(str(quote)):
        return None, None, "인용에_없는_숫자(검증실패)"
    mult = UNIT_TO_WON.get(str(unit).strip())
    if mult is None:
        return None, None, f"단위_불명({unit})"
    won = int(d) * mult
    return won, won / 1_000_000, None


# ---------------------------------------------------------------- dedup + 병합
def _cand_key(c) -> str:
    return _norm(str(c.get("인용", ""))) or _norm(str(c.get("항목명", "")))


def dedupe_candidates(surface):
    """runs[].candidates 를 회차교차 exact-key dedup. 각 distinct 키에 등장 회차 집합(_runs) 부착.
    표시위치 안정성([3])을 위해 그 키가 회차마다 받은 표시위치 값 집합(_disp_set)도 모은다 —
    같은 인용에 회차별로 다른 표시위치가 붙었는지 여기서 보존한다(대표 하나로 덮어쓰지 않는다)."""
    runs = surface.get("runs", []) if surface else []
    n = len(runs)
    groups, order = {}, []
    for r in runs:
        seen = set()
        for c in r.get("candidates", []):
            k = _cand_key(c)
            if not k or k in seen:
                continue
            seen.add(k)
            if k not in groups:
                groups[k] = {"cand": c, "runs": set(), "disp": set()}
                order.append(k)
            groups[k]["runs"].add(r.get("run_index"))
            d = c.get("표시위치")
            if d:
                groups[k]["disp"].add(d)
    out = []
    for k in order:
        g = groups[k]
        item = dict(g["cand"])
        item["_runs"] = g["runs"]
        item["_disp_set"] = set(g["disp"])
        out.append(item)
    return out, n


def _note_number(note_hint) -> str:
    """주석위치의 첫 주석 번호(구조 신호). 없으면 정규화 앞부분."""
    m = re.search(r"(\d+)", note_hint or "")
    return m.group(1) if m else (_norm(note_hint or "")[:8] or "?")


def _row_from_cand(c, two_tag):
    won, million, amt_reason = parse_amount(c.get("금액표시"), c.get("단위"), c.get("인용", ""))
    direction = c.get("손익방향")
    sign = {"이익": -1, "비용": +1}.get(str(direction).strip()) if two_tag else None
    nature = [s for s in (c.get("성격") or []) if s != "추정품질"]   # 추정품질 제거(범위 밖)
    # 조정성격: 신규 태그명. 구(舊) 산출물의 '정상화성격'도 읽는다(하위호환).
    adjust_char = (c.get("조정성격") or c.get("정상화성격")) if two_tag else "불명(surface/1)"
    return {
        "항목명": c.get("항목명"),
        "표시위치": c.get("표시위치") if two_tag else "불명",
        "표시위치_근거": c.get("표시위치_근거"),   # LLM 이 제시한 계상 위치 근거 구절([1] 게이트가 검증)
        "기간": c.get("기간"),                     # LLM 기간 태그(당기/전기/불명) — 기간 게이트가 XBRL·인용으로 재검증
        "조정성격": adjust_char,
        "성격": nature,
        "손익방향": direction if two_tag else None,
        "sign": sign,
        "amount_won": won,
        "amount_million": million,
        "amount_display": c.get("금액표시"),
        "unit": c.get("단위"),
        "주석위치": c.get("주석위치"),
        "인용": c.get("인용"),
        "근거강도": c.get("근거강도"),
        "item_type": c.get("item_type"),
        "_runs": set(c.get("_runs", [])),
        "_disp_set": set(c.get("_disp_set", [])),
        "_amt_reason": amt_reason,
    }


def _note_numbers(note_hint):
    """주석위치의 모든 주석 번호 집합(구조 신호). 여러 주석이 '/'로 나열돼도 순서 무관하게 잡는다."""
    return frozenset(re.findall(r"\d+", note_hint or ""))


def _merge_key(row):
    """같은 경제사건 병합키(구조 신호). 금액 있으면 (금액, 주석번호 집합) — 같은 금액·같은 주석이면
    이름이 달라도(회차별 표현 차이) 병합한다(주석 나열 순서 무관). 금액 없으면 (주석번호, 인용앞부분)."""
    if row["amount_won"] is not None:
        return ("AMT", row["amount_won"], _note_numbers(row.get("주석위치")))
    return ("QUAL", _note_number(row.get("주석위치")), _norm(row.get("인용", ""))[:24])


def _definite(r):
    """확정 태그 수(불명 아닌 조정성격·손익방향·표시위치). 병합 대표 선택에서 확정 > 불명."""
    return sum(1 for v in (r.get("조정성격"), r.get("손익방향"), r.get("표시위치"))
               if v and v != "불명")


def _merge_rows(rows, n_runs):
    groups, order = {}, []
    for r in rows:
        k = _merge_key(r)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    out = []
    for k in order:
        grp = groups[k]
        # 대표: 확정 태그 많은 것 > 재현수 많은 것 > 인용 충실
        rep = dict(max(grp, key=lambda r: (_definite(r), len(r["_runs"]), len(r.get("인용") or ""))))
        rep["_tag_priority_applied"] = len(grp) > 1 and any(
            _definite(x) != _definite(grp[0]) for x in grp)
        runs = set()
        disp_observed = set()
        for r in grp:
            runs |= r["_runs"]
            disp_observed |= r.get("_disp_set", set())   # 회차·문구변형 통틀어 관측된 표시위치([3])
        rep["_disp_observed"] = disp_observed
        rep["appeared_in"] = len(runs)
        rep["of_runs"] = n_runs
        rep["merged_count"] = len(grp)
        out.append(rep)
    return _consolidate_same_amount_name(out)


def _consolidate_same_amount_name(reps):
    """(1-a) 병합 보강 — 금액·부호·정규화 항목명이 같으면 주석번호가 달라도 병합한다. 1차 스윕(재고자산
    주석)과 2차 스윕(영업비용 주석)이 같은 항목을 다른 주석에서 인용해 병합키(금액,주석집합)가 안 맞는
    경우를 잡는다. 이름 일치를 요구해 금액만 우연히 같은 남남의 오병합을 막고, 인용·주석위치를 둘 다
    보존(_merged_locations)해 원문보기에서 양쪽을 볼 수 있게 한다. 병합이 실패해도 독립 안전망
    (detect_same_amount_locks)이 이중가산을 막으므로, 여기선 안전이 확실한 경우만 합친다."""
    groups, order = {}, []
    for r in reps:
        if (r.get("amount_won") is not None and r.get("sign") is not None
                and (r.get("항목명") or "").strip()):
            k = ("SAN", r["amount_won"], r["sign"], _norm(r.get("항목명")))
        else:
            k = ("SOLO", len(order))          # 금액·이름 없으면 병합 안 함(각자)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    out = []
    for k in order:
        grp = groups[k]
        if len(grp) == 1:
            out.append(grp[0])
            continue
        rep = dict(max(grp, key=lambda r: (_definite(r), r.get("appeared_in") or 0,
                                           len(r.get("인용") or ""))))
        rep["appeared_in"] = max((r.get("appeared_in") or 0) for r in grp)
        rep["merged_count"] = sum(r.get("merged_count", 1) for r in grp)
        disp = set()
        for r in grp:
            disp |= set(r.get("_disp_observed", set()))
        rep["_disp_observed"] = disp
        rep["_merged_locations"] = [{"주석위치": r.get("주석위치"), "인용": r.get("인용")} for r in grp]
        rep["_cross_sweep_merged"] = True
        out.append(rep)
    return out


# ---------------------------------------------------------------- 포함관계 — 표 산술(비율 폐기)
# [폐기] 비율/임계(구성합이 합계의 99.5%+) 기준은 "구성요소가 전부 후보로 올라온다"는 성립하지 않는
# 전제 위에 섰다. 작은 구성(예: 계약손실환입 1,048)이 후보로 안 오르면 비율이 미달해 못 잡고(충당부채
# 환입 총액 35,092 ⊃ 판매보증환입 34,044=97%를 놓침), 임계를 풀면 금액만 가까운 남남(무형처분 38,663 vs
# 무형손상 38,072)을 과묶는다. 비율은 포함관계의 증거가 아니다 — 주석 표의 '산술'이 증거다.
# 큰 값이 (작은 값들의 정확한 합)과 일치할 때만 합계로 확정한다. '합계'·'총액' 같은 글자는 찾지 않는다
# (키워드 금지) — 숫자가 실제로 더해지는지만 본다(D&A '성격별 합계=유형+무형+리스' 산술 대조와 같은 기법).
_COMMA_NUM = re.compile(r"\d[\d,]*")
_RUN_SEP = set(" \t\r\n()[]-−")   # 셀 구분자(런 유지). 한글·기타 문자는 런을 끊는다(행/항목 경계).


def _num_mag(display):
    """표시 문자열의 첫 쉼표형 숫자를 정수 크기로(부호·괄호·단위 무시). 없으면 None."""
    m = _COMMA_NUM.search(str(display or ""))
    return int(m.group(0).replace(",", "")) if m else None


def _numeric_runs(text):
    """주석 텍스트를 '숫자 런'으로 분해. 한 런 = 표의 한 행에서 이웃한 셀 값들 — 쉼표형 숫자들이
    공백·괄호·부호로만 이어진 최대 구간. 숫자 사이에 한글/기타 라벨이 오면 런이 끊긴다.
    ⇒ 매트릭스 표의 행(라벨은 행 앞에만, 셀 값은 서로 이웃)은 한 런으로 잡혀 산술 대조가 되고,
      나열식 목록('무형손상 38,072 무형처분 38,663 …')은 값마다 라벨이 껴 각 1개짜리 런이 되어
      합계 행으로 오인되지 않는다(과묶기 방지가 파서 구조에서 자연히 나온다). 반환 list[list[int]]."""
    runs, i, n = [], 0, len(text)
    while i < n:
        m = _COMMA_NUM.match(text, i)
        if not m:
            i += 1
            continue
        ints = [int(m.group(0).replace(",", ""))]
        j = m.end()
        while True:
            k = j
            while k < n and text[k] in _RUN_SEP:
                k += 1
            m2 = _COMMA_NUM.match(text, k) if k > j else None   # 구분자가 하나라도 있어야 이웃 셀
            if m2:
                ints.append(int(m2.group(0).replace(",", "")))
                j = m2.end()
            else:
                break
        runs.append(ints)
        i = j
    return runs


def _balanced_total(ints):
    """런이 '합계=구성 합'을 이루면 (total, others). 아니면 None. 최댓값이 나머지의 '정확한' 합과 같고,
    양수 구성이 2개 이상이어야 한다(total=A 같은 퇴화·단일 셀 열은 배제)."""
    if len(ints) < 3:
        return None
    mx = max(ints)
    others = list(ints)
    others.remove(mx)
    if mx > 0 and sum(others) == mx and sum(1 for o in others if o > 0) >= 2:
        return mx, others
    return None


def _section_for(cand, sections):
    """후보의 주석위치 번호로 섹션을 찾는다(notes_context._sec_num 규칙과 동일)."""
    for num in re.findall(r"\d+", cand.get("주석위치") or ""):
        for s in sections:
            m = re.match(r"\s*0*(\d+)\s*[.．]", s.get("label") or "")
            if m and m.group(1) == num:
                return s
    return None


def detect_containment(pool, notes):
    """표 산술로 합계/구성 포함관계를 확정(비율 폐기). 같은 주석 표에서 '합계=구성 합' 행을 찾아, 그 행의
    최댓값과 일치하는 후보를 합계로, 나머지 값과 일치하는 후보를 구성으로 확정한다. 합계 후보에
    is_total·children_ids, 구성 후보에 parent_id·child_index 를 달고, 표에서 이름을 얻지 못한 잔여
    (합계 − 확인된 구성 합)는 '그 외' 계산 노드로 만들어 돌려준다(합=구성 항상 성립 → 이중가산 산술
    불가). notes 없으면 산술 확인 불가 → (0, []). 반환 (confirmed_totals:int, residual_nodes:list)."""
    if not notes:
        return 0, []
    sections = notes.get("sections", [])
    items = [a for a in pool if a.get("amount_won") is not None and a.get("sign") is not None
             and _num_mag(a.get("amount_display")) is not None]
    by_sec = {}
    for a in items:
        sec = _section_for(a, sections)
        if sec is not None:
            by_sec.setdefault(id(sec), (sec, []))[1].append(a)
    assigned, totals, residuals = set(), 0, []
    for sec, cands in by_sec.values():
        if len(cands) < 2:
            continue
        balanced = [b for b in (_balanced_total(r) for r in _numeric_runs(sec["text"])) if b]
        for mx, others in sorted(balanced, key=lambda t: -t[0]):   # 큰 합계부터(중첩 시 바깥 우선)
            total_cand = next((c for c in cands if c["id"] not in assigned
                               and _num_mag(c["amount_display"]) == mx), None)
            if total_cand is None:
                continue
            avail = list(others)
            kids = []
            for c in cands:
                if c["id"] in assigned or c["id"] == total_cand["id"] or c["sign"] != total_cand["sign"]:
                    continue
                v = _num_mag(c["amount_display"])
                if v in avail:                       # 그 값이 실제로 표 행의 셀로 존재해야 구성 인정
                    avail.remove(v)
                    kids.append(c)
            if not kids:
                continue
            total_cand["is_total"] = True
            total_cand["children_ids"] = [k["id"] for k in kids]
            total_cand["containment_arithmetic"] = {
                "total": mx, "parts": others, "unit": total_cand.get("unit"),
                "equation": " + ".join(f"{o:,}" for o in others if o > 0) + f" = {mx:,}",
                "note": (sec.get("label") or "").strip()}
            for idx, k in enumerate(kids):
                k["parent_id"] = total_cand["id"]
                k["child_index"] = idx + 1
                assigned.add(k["id"])
            assigned.add(total_cand["id"])
            totals += 1
            named = sum(_num_mag(k["amount_display"]) for k in kids)
            resid = mx - named                       # 표엔 있으나 이름 못 얻은 셀들의 합 = 그 외
            if resid > 0:
                factor = total_cand["amount_won"] / mx    # 표시단위(백만원 등) → 원 배수
                rid = f"{total_cand['id']}-r"
                total_cand["children_ids"].append(rid)
                residuals.append({
                    "id": rid, "항목명": "그 외 (성격 미확인 잔여)",
                    "표시위치": total_cand.get("표시위치"), "조정성격": total_cand.get("조정성격"),
                    "성격": [], "손익방향": total_cand.get("손익방향"), "sign": total_cand["sign"],
                    "amount_won": int(round(resid * factor)),
                    "amount_million": resid * factor / 1_000_000,
                    "amount_display": f"{resid:,}", "unit": total_cand.get("unit"),
                    "주석위치": total_cand.get("주석위치"), "인용": None, "근거강도": None,
                    "item_type": None, "원문맥락": None,
                    "parent_id": total_cand["id"], "child_index": len(kids) + 1,
                    "computed_residual": True, "_residual_zone_of": total_cand["id"],
                    "not_adjustable_reason": (
                        f"도구 계산값 = 합계 {mx:,} − 확인된 구성 {named:,} = {resid:,}"
                        f"{(' ' + total_cand.get('unit')) if total_cand.get('unit') else ''}. "
                        "성격이 확인되지 않은 잔여입니다 — 원문 인용이 아니라 도구가 산술로 채운 값입니다. "
                        "합계 전체를 조정하려면 합계를 포함하고, 확인된 항목만 조정하려면 개별 선택하십시오."),
                })
    return totals, residuals


def _same_nature(a, b):
    """두 후보의 성격 계열이 같은가 — 기존 성격 태그(리스트) 교집합이 비지 않으면 같다고 본다.
    계정명 키워드 매칭 없음(no-keyword-heuristics) — LLM 이 단 성격 태그만으로 판정한다."""
    return bool(set(a.get("성격") or []) & set(b.get("성격") or []))


def detect_containment_proximity(pool):
    """표 산술(1단계)로 확정 못 한 근접 쌍을 2·3단계로 나눈다. 산술은 '같은 표 안'만 증명하므로, 서로
    다른 주석에 흩어진 포함관계(지분법 합계 vs Wuxi 손상)는 산술 불가 — 이때만 금액 근접을 보조로 쓴다.

    2단계(고근접 추정 잠금): 근접 ≥ 99.5% · 동부호 · 성격 계열 동일 → 큰 값=합계·작은 값=구성으로
      계층 잠금하되 '추정'(containment_estimated)임을 명시하고 사용자가 해제 가능. 잔여('그 외')는 만들지
      않는다(산술 근거가 없어 계산할 수 없다 — 1단계와 다른 점). 기본은 잠금(안전 기본값), 푸는 건 사용자.
    3단계(중근접 경고): 90% ≤ 근접 < 99.5%(또는 ≥99.5% 이나 성격 계열이 달라 2단계 미충족) · 동부호 →
      잠그지 않고 containment_warn 배지만. 이 구간·경우는 남남 가능성이 실질적이라 잠그지 않는다.
    1단계로 확정된(is_total/parent_id)·잔여(computed_residual)는 제외. 반환 (estimated:int, warns:int)."""
    items = [a for a in pool if a.get("amount_won") and a.get("sign") is not None
             and not a.get("is_total") and not a.get("parent_id") and not a.get("computed_residual")]
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["sign"] != b["sign"]:
                continue
            lo, hi = sorted((a["amount_won"], b["amount_won"]))
            if hi > 0 and lo / hi >= 0.90:
                big, small = (a, b) if a["amount_won"] >= b["amount_won"] else (b, a)
                pairs.append((lo / hi, big, small))
    pairs.sort(key=lambda t: -t[0])
    assigned, estimated, warns = set(), 0, 0
    # 2단계: 고근접 추정 잠금 (≥99.5% + 성격 계열 동일). 한 후보는 한 추정 묶음에만.
    # 금액이 정확히 같으면(ratio==1.0) 포함관계(합계⊃구성, 구성<합계)가 아니라 '중복'이다 — 병합
    # (`_merge_key`)이 처리한다. 여기선 tier-2 대상에서 빼(중복을 합계/구성으로 오분류하지 않게).
    for ratio, big, small in pairs:
        if ratio < 0.995 or big["id"] in assigned or small["id"] in assigned:
            continue
        if big["amount_won"] == small["amount_won"]:      # 같은 금액 = 중복, 포함관계 아님
            continue
        if not _same_nature(big, small):
            continue
        big["is_total"] = True
        big["containment_estimated"] = True
        big.setdefault("children_ids", []).append(small["id"])
        big["containment_estimated_meta"] = {
            "partner_id": small["id"], "partner_name": small["항목명"], "ratio": ratio,
            "nature": sorted(set(big.get("성격") or []) & set(small.get("성격") or []))}
        small["parent_id"] = big["id"]
        small["child_index"] = 1
        small["containment_estimated"] = True
        assigned.add(big["id"])
        assigned.add(small["id"])
        estimated += 1
    # 3단계: 중근접 경고 (2단계로 잠기지 않은 나머지 근접 쌍). 잠그지 않고 배지만.
    seen = set()
    for ratio, big, small in pairs:
        if big["id"] in assigned or small["id"] in assigned:
            continue
        key = (big["id"], small["id"])
        if key in seen:
            continue
        seen.add(key)
        for me, other in ((big, small), (small, big)):
            me.setdefault("containment_warn", []).append(
                {"partner_id": other["id"], "partner_name": other["항목명"], "ratio": ratio})
        warns += 1
    return estimated, warns


def bs_amounts_won(raw):
    """base-year 전체 재무제표(fnlttSinglAcntAll)의 재무상태표(sj_div=='BS') 라인 당기 금액(원, 절대값) 집합.

    후보 금액이 이 잔액과 정확히 일치하면 손익(P&L)이 아니라 재무상태표 잔액(자산·부채·자본)이다 →
    조정(EBITDA 가감) 대상이 될 수 없다. sj_div=='BS' 는 회계기준 표준 구분(구조 신호, 계정명 키워드 아님).
    한계: 주석에만 공시된 장부금액(예: 지분법투자 개별 장부금액)은 fnlttSinglAcntAll 의 BS '라인'이 아니라
    잡히지 않는다(그 값은 XBRL 개념코드도 없이 순수 HTML 표 셀에 있어 구조로 확정 불가 — docs §11)."""
    from src.extract import financials as _F
    out = set()
    for r in (raw or {}).get("list", []):
        if (r.get("sj_div") or "").strip() != "BS":
            continue
        a = _F.parse_amount(r.get("thstrm_amount"))
        if a is not None and a != 0:
            out.add(abs(int(a)))
    return out


def detect_same_amount_locks(pool):
    """(1-b) 동일금액 이중가산 안전망 — 병합·tier-2 의 성공을 가정하지 않는 독립 방어.

    왜 독립이어야 하나: 2차 스윕이 같은 항목(재고평가환입 661,733)을 다른 주석에서 발굴하면 병합키가
    안 맞아 구역 B 에 같은 금액이 2건 남는다. tier-2 는 ratio==1.0(정확히 같은 금액)을 '중복이니 병합이
    처리한다'며 제외하는데, 그 병합이 실패하면 아무도 안 막는 사각지대로 빠진다. 그래서 병합·tier-2 와
    무관하게 여기서 다시 막는다(경고가 아니라 잠금 — 경고로는 사용자가 둘 다 켤 수 있다).

    구역 B(및 수동 경로=구역 C 불명)에 금액·부호가 정확히 같은 항목이 둘 이상이면 상호배제로 잠근다:
    대표 하나만 Σ 에 반영하고 나머지는 게이팅한다. 사용자가 [묶음 해제]로 풀 수 있다(별개 항목이면).
    이미 계층(parent_id/is_total)으로 묶인 건 그 방어가 처리하므로 제외. 반환 잠금 그룹 수.
    (정확히 같은 금액은 구조 신호 — no-hardcoding 예외, 임계 상수 아님.)"""
    byid = {a.get("id"): a for a in pool}
    groups = {}
    for a in pool:
        amt = a.get("amount_won")
        if amt is None:
            continue
        # 계층 방어 대상은 동일금액 잠금에서 뺀다 — 단 '부모가 항상 켜져 자식이 확실히 잠기는' 1단계 산술
        # 확정(is_total·표 산술로 닫힘) 총계의 자식만. 2단계 추정(containment_estimated) 부모는 사용자가
        # 끌 수 있어(끄면 자식이 풀림) 계층 방어가 자식을 지킨다는 보장이 없다 → 그런 자식은 동일금액 그룹에
        # 편입해 부모 상태와 무관하게 독립적으로 상호배제한다(방어는 다른 방어의 성공을 가정하면 안 된다 —
        # 이마트 165,697: 추정 부모 끄면 자식이 풀려 별도 동일금액 그룹의 항목과 이중가산됐다). 총계(is_total)
        # 자체는 계층 앵커라 여전히 제외.
        if a.get("is_total"):
            continue
        pid = a.get("parent_id")
        if pid:
            parent = byid.get(pid)
            if parent and parent.get("is_total") and not parent.get("containment_estimated"):
                continue                                  # 1단계 확정 부모 — 자식은 계층으로 확실히 잠김
            # 2단계 추정 부모(또는 부모 소실)의 자식 → 계층 보호 불확실 → 아래로 내려가 동일금액 그룹에 편입
        groups.setdefault(abs(int(amt)), []).append(a)    # 부호 무관 금액 그룹(sign=None 도 포함)
    n = 0
    for amt, members in groups.items():
        if len(members) < 2:
            continue
        # 정(定)부호가 서로 다르면(이익 vs 비용) 반대 항목 — 중복 아님(둘 다면 상쇄지 이중 아님) → 안 잠금.
        # 같은 부호이거나 부호 불명(sign=None)이 섞인 경우만 잠근다: 사용자가 방향 지정 후 둘 다 켜는 경로 차단.
        signs = {m.get("sign") for m in members if m.get("sign") is not None}
        if len(signs) > 1:
            continue
        n += 1
        s = next(iter(signs)) if signs else None
        gid = f"samt_{'m' if s == -1 else ('p' if s == 1 else 'x')}_{amt}"
        # 대표: 상단(조정 가능)·계층 부모 없는 것(자립)·재현 많은 것 우선. 나머지는 중복(Σ 게이팅).
        # 계층 자식(추정 부모의)을 대표로 삼으면 그 항목이 총계 밑에 중첩 렌더돼 동일금액 UI 가 엉키므로
        # 자립 항목을 대표로 두고 계층 자식은 중복(dup)으로 게이팅한다.
        members.sort(key=lambda r: (0 if r.get("표시위치") == "상단" else 1,
                                    1 if r.get("parent_id") else 0,
                                    -(r.get("appeared_in") or 0), str(r.get("id"))))
        primary = members[0]
        primary["same_amount_group"] = gid
        primary["same_amount_role"] = "primary"
        primary["same_amount_partners"] = [{"id": m.get("id"), "항목명": m.get("항목명")}
                                           for m in members[1:]]
        for m in members[1:]:
            m["same_amount_group"] = gid
            m["same_amount_role"] = "dup"
            m["same_amount_partners"] = [{"id": primary.get("id"), "항목명": primary.get("항목명")}]
    return n


def placement_basis_ok(row):
    """[1] 근거 게이트: 표시위치=상단 확정에 필요한 '계상 위치 근거'가 실제로 있는지 확인만 한다.
    태그 내용을 재판정하지 않는다 — 헛숫자 차단(금액이 인용에 있나)과 같은 종류의 사후검증이다.
    근거로 인정: LLM 이 제시한 표시위치_근거(계상 위치를 드러낸 구절)가 인용·주석위치에 verbatim 으로
    존재해야 한다(지어낸 근거 차단). XBRL 결정론 확정은 별도(source=xbrl)로 이미 근거가 있으니 게이트 면제.
    계정명 목록 매칭 없음 — 오직 LLM 이 지목한 근거 텍스트의 '존재'만 구조적으로 확인한다(공백 무시).
    반환 (ok:bool, evidence:str|None)."""
    ev = row.get("표시위치_근거")
    if not ev or str(ev).strip() in ("", "불명", "해당없음", "없음"):
        return False, None
    ev_norm = _norm(str(ev))
    hay = _norm(str(row.get("인용", "")) + " " + str(row.get("주석위치", "")))
    if ev_norm and ev_norm in hay:
        return True, str(ev).strip()
    return False, None


def table_placement_ok(row, above_line_ev):
    """[1b-2] 표 구조 대체 근거 — verbatim 문자열 근거가 없을 때(중소형사는 주석 서술이 빈약해 LLM 이
    근거를 스티치하면 verbatim 매칭 실패), 후보 금액이 '상단(영업비용 구성) 표 발췌'에 있으면 상단으로 인정.

    문자열 이어붙이기가 아니라 '그 금액이 매출원가/판관비 구성 표(산술 정합) 또는 재고평가 개념코드 표(IAS
    2 상 매출원가 인식) 안에 계상됐나'를 표 구조로 확인한다(above_line_ev 는 opex_notes.above_line_evidence_text
    가 산술·표준 개념코드로 고른 섹션 발췌). 거짓 상단 0 유지: 그 발췌에 명백히 든 금액만 살린다. 반환 (ok, ev)."""
    if not above_line_ev:
        return False, None
    disp = str(row.get("amount_display") or "").strip()
    if len(re.sub(r"[^\d]", "", disp)) < 4:      # 너무 작은 수는 우연 일치 위험 → 제외
        return False, None
    if disp and disp in above_line_ev:
        return True, "매출원가·판관비/재고평가 등 영업비용 구성 표에 계상(표 구조 확인)"
    return False, None


# ---------------------------------------------------------------- D&A 이중계상 차단
# EBITDA = 영업이익 + D&A 다. D&A 로 가산한 금액에 이미 포함된 항목(예: 고객관계 상각 ⊂ 무형자산상각비)
# 이 조정 후보로 또 올라와 체크되면 같은 금액이 두 번 반영돼 EBITDA 가 틀어진다. 기존 이중가산 방어는
# '후보끼리'만 보므로 이 경로(후보 vs D&A)를 못 막는다 → 출처(주석)+산술로 결정론 차단. 계정명 키워드
# 없음, LLM 질의 없음, 회사맞춤 없음.
def da_cell_amounts(ebitda):
    """D&A 로 잡힌 개별 셀의 (주석번호, 표시금액 크기) 목록. `all_da_cells_by_note` 는 D&A 추출이 XBRL
    표준 개념코드(Depreciation*/Amortisation*)로 식별한 셀이라, 여기서 그 개념코드만 남기면 감가·무형·
    리스 상각 금액만 모인다 — 손상차손·이자 등 비-D&A 개념은 개념코드가 달라 자동 제외된다(개념코드
    비교는 계정명 한글 키워드가 아니라 회계기준 구조 = no-keyword 예외). 후보 금액이 이 중 하나와 같고
    같은 주석에서 오면 그 후보는 D&A 로 이미 EBITDA 에 반영된 상각 금액이다."""
    out = []
    cells = (((ebitda or {}).get("da", {}) or {}).get("cross_check", {}) or {}).get("all_da_cells_by_note", [])
    for c in cells:
        concept = c.get("개념코드") or ""
        if not re.search(r"Depreciat|Amorti", concept, re.I):        # D&A 개념코드만
            continue
        if re.search(r"InvestmentProperty|NotInUse", concept, re.I):  # 비영업 D&A(운휴자산·투자부동산)
            continue  # 영업이익 밖이라 EBITDA D&A 가산에 없음 → 이중계상 대상 아님(추출기의 영업/비영업 구분과 일치)
        nn = _note_number(c.get("주석"))
        mag = _num_mag(c.get("원문값"))
        if nn and mag:
            out.append((nn, mag))
    return out


def _da_double_count(row, da_cells, notes):
    """후보가 D&A 로 이미 반영된 상각 금액인가 — 후보 표시금액이 D&A 셀(개념코드로 식별)과 같고 같은
    주석에서 오면 True(확정). 손상차손 등은 D&A 개념이 아니라 셀에 없으니 안 걸린다(손상·처분 과제거
    방지 — 이들은 QoE 핵심 사냥감이므로 절대 지우면 안 됨). 광역 보수 제외는 하지 않는다.
    반환 (blocked, confirmed, reason)."""
    if row.get("amount_won") is None or not da_cells:
        return False, False, None
    cand_disp = _num_mag(row.get("amount_display"))
    if cand_disp is None:
        return False, False, None
    cand_notes = set(re.findall(r"\d+", row.get("주석위치") or ""))
    for nn, mag in da_cells:
        if mag == cand_disp and nn in cand_notes:
            reason = (f"감가·무형 상각(D&A)으로 이미 EBITDA 에 반영된 금액 — 주석 {nn} 의 상각비 셀"
                      f"(XBRL 개념코드로 식별)과 {cand_disp:,} 일치. 조정에 넣으면 이중 반영.")
            return True, True, reason
    return False, False, None


def build_sections(surface, notes=None, cis_lines=None, da_cells=None, period_map=None,
                   base_year=None, bs_amounts=None, above_line_ev=None):
    """배치 규칙(교정): EBITDA 조정(도로 더하기)은 영업이익에 이미 반영된 항목만 가능하다. 따라서
    구역 B(조정대상·토글)에는 표시위치=상단이면서 조정성격=조정대상인 것만 넣는다. 표시위치=하단은
    비반복이어도 EBITDA 에 없어 조정 불가 → 구역 C(참고). 표시위치=불명은 조정 불가 → C 불명 묶음.
    추정품질 단독 항목(성격이 추정품질뿐)은 범위 밖이라 화면에서 제외. 재계산 공식은 불변(게이팅만).

    표시위치 신뢰성 3겹:
    - [2] XBRL 결정론 확정: 후보 당기금액이 손익계산서 라인과 유일 일치하면 그 라인의 위치로 확정한다
      (LLM 태그보다 우선). 근거(개념코드·위치)를 표시위치_확정근거에 남긴다.
    - [3] 회차간 안정성 게이트: XBRL 로 확정 안 됐는데 표시위치가 회차마다 갈렸으면(예: 상단/불명)
      조정 대상에서 빼고 구역 C(불명 묶음)로 보낸다. 관측된 값 집합을 표시위치_observed 에 기록.
    - [1] 근거 게이트(코드 강제): 상단인데 XBRL 확정도 아니고 표시위치_근거가 인용에 verbatim 으로
      없으면(=계상 위치 근거 없음) 불명으로 강등해 구역 B 진입을 막는다(표시위치_강등 기록). 프롬프트
      보수 규칙([1] 지난 루프)을 코드로 못박는 마지막 겹 — LLM 이 규칙을 어겨도 근거 없는 상단은 못 든다."""
    cis_lines = cis_lines or []
    da_cells = da_cells or []
    period_map = period_map or {}
    bs_amounts = bs_amounts or set()
    above_line_ev = above_line_ev or ""
    period_gated_count = 0
    bs_gated_count = 0
    table_rescued_count = 0
    two_tag = str((surface or {}).get("schema_version", "")).startswith("surface/2")
    # [1] 근거 게이트: 프롬프트가 표시위치_근거를 요구한 산출물에서만 켠다(옛 산출물은 필드가 없어
    # 켜면 상단이 모두 근거없음으로 강등됨 → 하위호환 위해 능력 플래그로 게이팅).
    gate_enabled = bool((surface or {}).get("placement_evidence_field"))
    distinct, n_runs = dedupe_candidates(surface)
    rows = [_row_from_cand(c, two_tag) for c in distinct]
    merged = _merge_rows(rows, n_runs)
    tag_priority_count = sum(1 for r in merged if r.get("_tag_priority_applied"))

    adjustments, reference, reference_unknown, qualitative = [], [], [], []
    excluded_estimation = 0
    excluded_estimation_merged = 0        # 무손실 대사용(제외 rows 의 merged_count 합)
    xbrl_confirmed_count = 0
    unstable_count = 0
    gated_count = 0
    da_blocked_count = 0
    for i, row in enumerate(merged):
        row["id"] = f"cand{i}"
        amt_reason = row.pop("_amt_reason", None)
        row.pop("_runs", None)
        row.pop("_tag_priority_applied", None)
        disp_observed = {d for d in row.pop("_disp_observed", set()) if d}
        row.pop("_disp_set", None)
        # 추정품질 단독(추정품질 제거 후 성격이 비면) → 범위 밖, 화면에서 제외. 겸함은 남은 성격으로 유지.
        if two_tag and not row["성격"]:
            excluded_estimation += 1
            excluded_estimation_merged += row.get("merged_count", 1)
            continue
        nc = row["조정성격"]
        row["원문맥락"] = _context_for_cand(row, notes)

        # [D&A 이중계상 차단] — 후보가 D&A 가산액을 구성하면(출처+산술) 조정 자격 박탈 → 구역 C 참고.
        # 배치·조정성격보다 우선(상단·조정대상이라도 D&A 에 이미 있으면 조정 시 이중 반영). 재계산 공식
        # 불변 — 이 항목이 토글/수동 대상에서 빠지는 게이팅일 뿐. 참고에는 스위치·토글이 없어 Σ 에 못 든다.
        da_blocked, da_confirmed, da_reason = _da_double_count(row, da_cells, notes)
        if da_blocked:
            row["da_double_count"] = True
            row["da_confirmed"] = da_confirmed
            row["not_adjustable_reason"] = da_reason
            reference.append(row)                         # 구역 C 참고(조정 불가 — D&A 에 이미 포함)
            da_blocked_count += 1
            continue

        # [2] XBRL 결정론 확정 — 유일 금액정합일 때만. LLM 태그보다 우선.
        xbrl_pos, xbrl_basis = match_is_line(row["amount_won"], cis_lines)
        xbrl_confirmed = xbrl_pos is not None
        if xbrl_confirmed:
            if xbrl_pos != row["표시위치"]:
                row["표시위치_llm"] = row["표시위치"]   # 뒤집힌 원 LLM 태그 보존(감사추적)
            row["표시위치"] = xbrl_pos
            row["표시위치_source"] = "xbrl"
            row["표시위치_확정근거"] = xbrl_basis
            xbrl_confirmed_count += 1
        else:
            row["표시위치_source"] = "llm"
        disp = row["표시위치"]

        # [3] 회차간 표시위치 불안정 게이트 — XBRL 확정이면 면제(결정론 진실이 있으니).
        # [1c-우선] 표 구조 결정론이 계상 위치를 확정하면 회차 흔들림(안정성)보다 우선한다 — XBRL 결정론이
        # LLM 태그를 이기는 것과 같은 계열. LLM 이 회차마다 갈린 건 주석 서술이 빈약해서지 계상 위치 자체가
        # 불확실한 게 아니다(원문 표엔 매출원가/판관비에 명확히 있음 — 코미코 재고평가환입 666,343). 표 구조로
        # 확정 안 되는 항목(매출채권 대손처럼 판관비 명세에 라인 없어 표 산술 안 되는 것)은 여전히 불안정 → 불명.
        unstable = (not xbrl_confirmed) and len(disp_observed) > 1
        if unstable:
            tbl_ok, tbl_ev = table_placement_ok(row, above_line_ev)
            if gate_enabled and tbl_ok:
                row["표시위치_llm"] = "/".join(sorted(disp_observed))   # 회차 흔들림 보존(감사추적)
                row["표시위치"] = "상단"
                row["표시위치_근거_확인"] = tbl_ev
                row["표시위치_근거_표구조"] = True
                row["표시위치_표구조결정"] = True
                row["표시위치_불안정_표구조우선"] = True   # 표 구조가 안정성 게이트를 이김(감사추적)
                row["표시위치_observed"] = sorted(disp_observed)
                disp = "상단"
                unstable = False
                table_rescued_count += 1
            else:
                row["표시위치_불안정"] = True
                row["표시위치_observed"] = sorted(disp_observed)
                unstable_count += 1

        # [1] 근거 게이트 — 상단인데 XBRL 확정도 아니고 계상 위치 근거를 인용에서 검증 못 하면 불명 강등.
        # (불안정으로 이미 걸린 건 손대지 않는다. 하단은 EBITDA 조정과 무관하므로 게이트 대상 아님 —
        #  상단만이 구역 B 로 가 EBITDA 를 움직이니 상단 진입만 근거로 막는다.)
        if (gate_enabled and not unstable and not xbrl_confirmed and disp == "상단"
                and not row.get("표시위치_표구조결정")):   # 표 구조로 이미 확정된 건 재게이트 안 함
            ok, ev = placement_basis_ok(row)
            if ok:
                row["표시위치_근거_확인"] = ev          # 근거 통과 — 원문보기에 띄운다
            else:
                # [1b-2] verbatim 실패 시 표 구조 대체 근거 — 후보 금액이 매출원가/판관비/재고평가 구성
                # 표 발췌에 있으면 상단 인정(중소형사는 근거가 표에 흩어져 스티치되므로). 명백한 것만.
                tbl_ok, tbl_ev = table_placement_ok(row, above_line_ev)
                if tbl_ok:
                    row["표시위치_근거_확인"] = tbl_ev
                    row["표시위치_근거_표구조"] = True
                    table_rescued_count += 1
                else:
                    row["표시위치_llm"] = row["표시위치"]     # 원 LLM 태그 보존(감사추적)
                    row["표시위치"] = "불명"
                    row["표시위치_강등"] = True
                    disp = "불명"
                    gated_count += 1

        # [1b-3] 표 구조 결정(불명 → 상단): LLM 이 불명으로 둔 항목이라도, 그 금액이 매출원가/판관비 구성
        # 표(산술 정합) 또는 재고평가 개념코드(IAS 2 상 매출원가 인식) 표에 명백히 계상됐으면 상단으로 확정한다
        # (중소형사는 인용이 빈약해 LLM 이 불명으로 두지만 표에는 있다). XBRL 결정론([2])이 LLM 을 이기는 것과
        # 같은 계열 — 구조가 사실이면 우선. 게이트로 강등된 건 제외(이미 표 검증에 실패). 거짓 상단 0 유지:
        # 매출원가/판관비/재고평가 표라는 '명백한' 근거가 있을 때만. (CF 표는 근거에서 제외됨.)
        elif (gate_enabled and not unstable and not xbrl_confirmed and disp == "불명"
              and not row.get("표시위치_강등")):
            tbl_ok, tbl_ev = table_placement_ok(row, above_line_ev)
            if tbl_ok:
                row["표시위치_llm"] = "불명"
                row["표시위치"] = "상단"
                row["표시위치_근거_확인"] = tbl_ev
                row["표시위치_근거_표구조"] = True
                row["표시위치_표구조결정"] = True     # 불명→상단 결정(감사추적)
                disp = "상단"
                table_rescued_count += 1

        # 기간 게이트 — 구역 B(당기 EBITDA 조정)는 '당기 금액'만. surface 후보는 주석 텍스트라 기간 보장이
        # 없어 LLM 이 전기(작년) 금액을 집을 수 있다(네이버 스톡그랜트 80,180=전기인데 상단 B 로 올라옴).
        # 우선순위: XBRL 기간 컨텍스트(CFY/PFY) 결정론 > 인용 기간표현 > 불명. 당기 아니면(전기·불명) 조정
        # 자격만 박탈 → 구역 C(발굴은 유지, 수동 스위치는 열어둠). 표시위치와 같은 보수·비대칭.
        period, period_basis = period_notes.detect_period(row, period_map, base_year)
        row["기간"] = period
        row["기간_근거"] = period_basis

        # BS값 게이트 — 후보 금액이 재무상태표(BS) 라인 잔액과 정확히 일치하면 손익(P&L)이 아니라
        # 자산·부채·자본 잔액이다 → 조정(EBITDA 가감) 대상 아님. 자동·수동 어느 경로로도 못 들어가게
        # 구역 C 참고로 돌린다. sj_div=BS 는 표준 구조(계정명 키워드 아님). 최우선 게이트.
        if (row["amount_won"] is not None and abs(int(row["amount_won"])) in bs_amounts):
            row["bs_value"] = True
            row["not_adjustable_reason"] = ("재무상태표 잔액(자산·부채·자본)과 일치 — 손익(P&L)이 아니라 "
                                            "잔액이므로 EBITDA 조정 대상이 아닙니다(자동·수동 모두 불가).")
            bs_gated_count += 1
            reference.append(row)
            continue

        if unstable:
            row["not_adjustable_reason"] = ("표시위치 불안정 (회차별 상이: " + "/".join(sorted(disp_observed))
                                            + ") — 조정 불가, 원문으로 직접 확인")
            reference_unknown.append(row)                 # 구역 C 불명 묶음(불안정 → 조정 불가)
        elif disp == "상단" and nc == "조정대상":
            if row["amount_won"] is None:
                qualitative.append(row)                   # 금액 불명 — 정성(기간 게이트 무의미, EBITDA 못 움직임)
            elif period == "당기":
                toggleable = row["sign"] is not None
                row["toggleable"] = toggleable
                row["toggle_reason"] = None if toggleable else (amt_reason or "손익방향_불명")
                adjustments.append(row)                   # 구역 B(영업이익 위 · 조정대상 · 당기 · 토글)
            else:
                # 상단·조정대상·금액 있음이나 당기 아님(전기·기간불명) → 조정 자격 박탈 → 구역 C 불명.
                row["period_gated"] = True
                row["not_adjustable_reason"] = (
                    "전기(작년) 금액 — 당기 EBITDA 조정 대상 아님. 원문 확인 후 당기 항목이면 아래 스위치로 포함."
                    if period == "전기" else
                    "기간 미확인(당기/전기) — XBRL·인용으로 당기임을 확정 못 했습니다. 원문 확인 후 당기면 아래 스위치로 포함.")
                period_gated_count += 1
                reference_unknown.append(row)
        elif row["amount_won"] is None:
            qualitative.append(row)                       # 구역 C 정성(금액 불명 — 슬라이더 대상 아님)
        elif disp == "불명":
            if row.get("표시위치_강등"):
                row["not_adjustable_reason"] = (
                    "계상 위치 근거 없음 — LLM 은 상단으로 봤으나 인용에 계상 위치 근거가 없어 "
                    "불명으로 내렸습니다. 원문 확인 후 아래 스위치로 직접 조정에 포함할 수 있습니다.")
            else:
                row["not_adjustable_reason"] = "표시위치 불명 — EBITDA 에 있는지 몰라 조정 불가"
            reference_unknown.append(row)                 # 구역 C 불명 묶음(조정 불가)
        else:
            row["not_adjustable_reason"] = ("영업이익 아래(하단) 표시 — EBITDA 에 없어 조정 대상 아님"
                                            if disp == "하단" else "조정성격이 조정대상 아님(참고)")
            reference.append(row)                         # 구역 C 참고(하단 / 상단·참고)
    adjustments.sort(key=lambda r: (r["amount_won"] is None, -(r["amount_won"] or 0)))
    reference.sort(key=lambda r: -(r["amount_won"] or 0))
    reference_unknown.sort(key=lambda r: -(r["amount_won"] or 0))
    qualitative.sort(key=lambda r: (-(r.get("appeared_in") or 0), str(r["항목명"])))
    # 이중가산 방지는 EBITDA 를 움직이는 모든 경로에 건다 — 자동 토글(구역 B)뿐 아니라 수동 스위치
    # (구역 C 불명)도 같은 Σ 에 항을 더하므로, 표 산술 포함관계 탐지를 두 경로의 합집합에 적용한다.
    # (구역 C 참고=하단은 토글·수동 대상이 아니라 Σ 에 못 들어가므로 pool 에서 제외.)
    pool = adjustments + reference_unknown
    containment_totals, residual_nodes = detect_containment(pool, notes)
    # '그 외' 잔여 노드를 부모(합계)와 같은 구역에 넣는다 — 합=구성이 항상 성립하게(부모가 구역 B면 B,
    # 불명이면 C). 잔여는 계층 자식이라 render 가 합계 밑에 들여쓰기하고, 합계 체크 시 함께 잠긴다.
    adj_ids = {a["id"] for a in adjustments}
    for rn in residual_nodes:
        (adjustments if rn["_residual_zone_of"] in adj_ids else reference_unknown).append(rn)
    # 2·3단계: 표 산술(1단계)로 확정 못 한 근접 쌍. 산술은 같은 표만 잡으므로 다른 주석에 흩어진
    # 포함관계는 여기서 — 2단계(≥99.5%·동부호·동성격)=추정 잠금(해제 가능), 3단계(90~99.5%)=경고만.
    containment_estimated, containment_warn = detect_containment_proximity(adjustments + reference_unknown)
    # (1-b) 동일금액 이중가산 안전망 — 병합·tier-2 성공과 무관한 독립 잠금(같은 금액·부호 ≥2 → 상호배제).
    same_amount_locks = detect_same_amount_locks(adjustments + reference_unknown)
    stats = {"tag_priority_count": tag_priority_count, "containment_totals": containment_totals,
             "containment_estimated": containment_estimated,
             "containment_warn": containment_warn,
             "same_amount_locks": same_amount_locks,
             "period_gated": period_gated_count,
             "bs_gated": bs_gated_count,
             "table_rescued": table_rescued_count,
             "excluded_estimation": excluded_estimation,
             "excluded_estimation_merged": excluded_estimation_merged,
             "xbrl_confirmed_count": xbrl_confirmed_count,
             "unstable_display_count": unstable_count,
             "gated_display_count": gated_count,
             "da_blocked_count": da_blocked_count}
    return adjustments, reference, reference_unknown, qualitative, stats


# ---------------------------------------------------------------- 원문 맥락(#5)
def _context_for_cand(row, notes):
    if not notes:
        return None
    num = nctx.comma_number(row.get("amount_display")) if row.get("amount_won") is not None else None
    frag = nctx.longest_fragment(row.get("인용"))
    # [4] 근거강도=추정이면 유추 근거(표 머리·주변 행)를 함께 보이게 발췌 범위를 넓힌다.
    wide = 2 if str(row.get("근거강도")).strip() == "추정" else 1
    return nctx.excerpt_for(notes, row.get("주석위치"),
                            number_highlights=[num] if num else [],
                            text_anchors=[frag] if frag else [],
                            window_scale=wide)


def _context_for_src(src, notes):
    if not notes or not src:
        return None
    num = nctx.comma_number(src.get("원문값"))
    return nctx.excerpt_for(notes, src.get("주석위치"),
                            number_highlights=[num] if num else [],
                            text_anchors=[src.get("인용")] if src.get("인용") else [])


# ---------------------------------------------------------------- 손익계산서(영업이익 원문보기)
# 손익계산서 표준 계단 — XBRL 표준 개념코드로만 식별·정렬(회계기준 구조 = no-hardcoding 예외,
# 계정명 키워드 매칭 아님). 매출→매출원가→매출총이익→판관비→영업이익 까지. 라벨은 XBRL account_nm
# 그대로. 성격 판정이 아니라 '사실인 손익계산서'를 표로 재구성해 영업이익을 검증시키는 표시.
IS_WATERFALL = [
    ("ifrs-full_Revenue", "base"),
    ("ifrs-full_CostOfSales", "less"),
    ("ifrs-full_GrossProfit", "subtotal"),
    ("dart_TotalSellingGeneralAdministrativeExpenses", "less"),
    ("dart_OperatingIncomeLoss", "result"),
]


def _amount_to_won(s):
    """XBRL thstrm_amount → 정수(원). 음수(-, 괄호) 처리. 숫자 없으면 None."""
    t = str(s).strip()
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    d = _digits(t)
    if not d:
        return None
    return (-1 if neg else 1) * int(d)


def build_income_statement(ebitda):
    """영업이익 원문보기용: 캐시된 XBRL 재무제표(fnlttSinglAcntAll)의 포괄손익계산서(CIS)를 표준
    개념코드로 매출→영업이익 계단으로 재구성. 영업이익 행 하이라이트. 캐시·행 없으면 None."""
    oi = ebitda.get("operating_income", {})
    raw_rel = (oi.get("provenance") or {}).get("raw_path")
    if not raw_rel:
        return None
    raw_path = PROJECT_ROOT / raw_rel
    if not raw_path.exists():
        return None
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cis = {r.get("account_id"): r for r in raw.get("list", []) if r.get("sj_div") == "CIS"}
    hl_id = (oi.get("source") or {}).get("account_id")
    lines = []
    for concept, role in IS_WATERFALL:
        r = cis.get(concept)
        if not r:
            continue
        won = _amount_to_won(r.get("thstrm_amount"))
        if won is None:
            continue
        lines.append({
            "concept": concept,
            "label": r.get("account_nm") or concept,
            "amount_won": won,
            "amount_million": won / 1_000_000,
            "role": role,
            "highlight": concept == hl_id,
        })
    if not lines or not any(x["highlight"] for x in lines):
        return None
    return {
        "statement_name": (oi.get("source") or {}).get("sj_nm") or "포괄손익계산서",
        "period_year": ebitda.get("base_year"),
        "lines": lines,
    }


# ---------------------------------------------------------------- 표시위치 XBRL 결정론 대조([2])
# 손익계산서 표준 개념코드 → 영업이익 대비 위치. 회계기준이 정한 구조(no-hardcoding 예외 = 표준
# concept_id 로 식별). 계정명(한글 account_nm) 매칭이 아니다 — 오직 XBRL 표준 개념코드로만 가른다.
IS_ABOVE_OI = {                       # 영업이익 산정에 들어가는 라인(상단)
    "ifrs-full_Revenue",
    "ifrs-full_CostOfSales",
    "ifrs-full_GrossProfit",
    "dart_TotalSellingGeneralAdministrativeExpenses",
}
IS_BELOW_OI = {                       # 영업이익 아래 손익 라인(하단)
    "dart_OtherGains",
    "dart_OtherLosses",
    "ifrs-full_FinanceIncome",
    "ifrs-full_FinanceCosts",
    "ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    "ifrs-full_IncomeTaxExpenseContinuingOperations",
}


def load_cis_position_lines(ebitda):
    """ebitda 의 캐시된 XBRL(fnlttSinglAcntAll)에서 CIS 라인을 표준 개념코드로 영업이익 위/아래 분류.
    반환 [{concept, account_nm, amount_won, position:'상단'|'하단'}]. 캐시/경로 없으면 []."""
    oi = (ebitda or {}).get("operating_income", {})
    raw_rel = (oi.get("provenance") or {}).get("raw_path")
    if not raw_rel:
        return []
    raw_path = PROJECT_ROOT / raw_rel
    if not raw_path.exists():
        return []
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    lines = []
    for r in raw.get("list", []):
        if r.get("sj_div") != "CIS":
            continue
        concept = r.get("account_id")
        pos = "상단" if concept in IS_ABOVE_OI else ("하단" if concept in IS_BELOW_OI else None)
        if pos is None:
            continue
        won = _amount_to_won(r.get("thstrm_amount"))
        if won is None:
            continue
        lines.append({"concept": concept, "account_nm": r.get("account_nm") or concept,
                      "amount_won": won, "position": pos})
    return lines


def match_is_line(amount_won, cis_lines):
    """후보의 당기 금액이 손익계산서 라인의 당기 금액과 정확히 일치하면(구조·숫자 신호, 계정명 아님)
    그 라인의 영업이익 대비 위치를 결정론으로 반환한다. 우연 일치를 막으려 '유일 일치'일 때만.
    반환 (position:'상단'|'하단', basis:dict) 또는 (None, None)."""
    if amount_won is None or not cis_lines:
        return None, None
    hits = [ln for ln in cis_lines if abs(ln["amount_won"]) == abs(amount_won)]
    if len(hits) != 1:
        return None, None
    ln = hits[0]
    basis = {
        "concept": ln["concept"],
        "account_nm": ln["account_nm"],
        "line_amount_won": ln["amount_won"],
        "line_amount_million": ln["amount_won"] / 1_000_000,
        "position": ln["position"],
        "matched_on": "손익계산서 라인과 당기금액 정확히 일치(XBRL 개념코드로 위치 확정)",
    }
    return ln["position"], basis


# ---------------------------------------------------------------- 브릿지(A)
def build_bridge(ebitda, notes=None):
    oi = ebitda["operating_income"]
    oi_won = oi["amount_won"]
    da = ebitda.get("da", {})
    da_won = da.get("operating_da_won") or 0
    lines = []
    for ln in da.get("lines", []):
        lines.append({
            "kind": ln.get("kind"),
            "role": ln.get("role"),
            "value_won": ln.get("value_won"),
            "value_million": (ln.get("value_won") or 0) / 1_000_000,
            "added": ln.get("added"),
            "inclusion": ln.get("inclusion"),
            "notice": ln.get("notice"),
            "source": ln.get("source"),
            "원문맥락": _context_for_src(ln.get("source"), notes),
        })
    return {
        "operating_income": {
            "amount_won": oi_won,
            "amount_million": oi_won / 1_000_000,
            "source": oi.get("source"),   # 손익계산서 계정 — 주석 아님(원문맥락 없음)
            # 원문보기: 주석이 없는 재무제표 라인이라 XBRL 손익계산서 계단을 재구성해 검증시킨다.
            "income_statement": build_income_statement(ebitda),
        },
        "da": {
            "present": da.get("present"),
            "path": da.get("path"),
            "method": da.get("method"),
            "note_title": da.get("note_title"),
            "operating_da_won": da_won,
            "operating_da_million": da_won / 1_000_000,
            "lease": da.get("lease"),
            "lines": lines,
            "reason": da.get("reason"),
        },
        "ebitda_base_won": oi_won + da_won,
        "ebitda_base_million": (oi_won + da_won) / 1_000_000,
        "formula": "EBITDA(기준선) = 영업이익 + 가산 D&A(성격별 또는 개별주석 합산)",
    }


def build_screen_panel(screen):
    if not screen:
        return None
    s = screen.get("screen", {})
    return {
        "years_covered": screen.get("years_covered"),
        "cumulative_operating_income": s.get("cumulative_operating_income"),
        "cumulative_operating_cash_flow": s.get("cumulative_operating_cash_flow"),
        "cumulative_divergence_ratio": s.get("cumulative_divergence_ratio"),
        "per_year": s.get("per_year"),
        "note": "다년 영업이익 vs 영업현금흐름 괴리 게이트(별도 지표). EBITDA 재계산과 무관 — 참고.",
    }


# ---------------------------------------------------------------- 조립
def build_view(*, ebitda, surface=None, screen=None, sources=None, notes=None, period_map=None,
               bs_amounts=None, above_line_ev=None):
    bridge = build_bridge(ebitda, notes=notes)
    cis_lines = load_cis_position_lines(ebitda)   # [2] 표시위치 XBRL 결정론 대조용 손익계산서 라인
    da_cells = da_cell_amounts(ebitda)            # D&A 이중계상 차단용 — D&A 상각 셀(개념코드로 식별)
    base_year = ebitda.get("base_year")
    adjustments, reference, reference_unknown, qualitative, stats = build_sections(
        surface, notes=notes, cis_lines=cis_lines, da_cells=da_cells,
        period_map=period_map, base_year=base_year, bs_amounts=bs_amounts,
        above_line_ev=above_line_ev)
    warnings = [{"level": "always", "text": WARN_GENERAL}]
    if (ebitda.get("da", {}).get("path")) == "개별주석":
        warnings.append({"level": "operating_lease", "text": WARN_OPLEASE})
    return {
        "schema_version": "screen-view/2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ("조정 EBITDA 화면 입력. 원값·출처만. 표시위치=상단·조정대상만 토글로 EBITDA 를 "
                 "움직이고, 참고(하단·불명)는 움직이지 않는다. 판정·임계·색 없음 — 판정은 사람이 한다."),
        "company": ebitda.get("company", {}),
        "base_year": ebitda.get("base_year"),
        "warnings": warnings,
        "bridge": bridge,
        "adjustments": adjustments,            # 구역 B (표시위치=상단 · 조정성격=조정대상 · 토글)
        "reference": reference,                # 구역 C 숫자 참고(하단/상단·참고, 슬라이더)
        "reference_unknown": reference_unknown,  # 구역 C 불명 묶음(표시위치 불명 · 조정 불가)
        "reference_qualitative": qualitative,  # 구역 C 정성(금액 불명, 슬라이더 없음)
        "screen_panel": build_screen_panel(screen),
        "meta": {
            "surface_present": surface is not None,
            "surface_schema": (surface or {}).get("schema_version"),
            "surface_is_fixture": bool((surface or {}).get("source", {}).get("fixture")),
            "context_present": notes is not None,
            "adjust_count": len(adjustments),
            "reference_count": len(reference),
            "reference_unknown_count": len(reference_unknown),
            "qualitative_count": len(qualitative),
            "excluded_estimation": stats["excluded_estimation"],
            "excluded_estimation_merged": stats["excluded_estimation_merged"],
            "containment_totals": stats["containment_totals"],
            "containment_estimated": stats["containment_estimated"],
            "containment_warn": stats["containment_warn"],
            "same_amount_locks": stats["same_amount_locks"],
            "period_gated": stats["period_gated"],
            "bs_gated": stats["bs_gated"],
            "table_rescued": stats["table_rescued"],
            "tag_priority_count": stats["tag_priority_count"],
            "xbrl_confirmed_count": stats["xbrl_confirmed_count"],
            "unstable_display_count": stats["unstable_display_count"],
            "gated_display_count": stats["gated_display_count"],
            "da_blocked_count": stats["da_blocked_count"],
            "cis_lines_available": len(cis_lines),
            "sources": sources or {},
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="normalize: screen·surface·D&A → 화면용 단일 JSON")
    p.add_argument("--stock-code", required=True)
    p.add_argument("--ebitda", help="ebitda JSON 경로(생략 시 out/ 최신)")
    p.add_argument("--surface", help="surface JSON 경로(생략 시 out/ 최신). surface/2 권장")
    p.add_argument("--screen", help="screen JSON 경로(생략 시 out/ 최신)")
    p.add_argument("--no-context", action="store_true", help="원문 맥락(주석 본문) 부착 생략")
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args(argv)

    stock = args.stock_code.strip()
    ebitda_p = Path(args.ebitda) if args.ebitda else _latest("ebitda", stock)
    surface_p = Path(args.surface) if args.surface else _latest("surface", stock)
    screen_p = Path(args.screen) if args.screen else _latest("screen", stock)
    if ebitda_p is None or not Path(ebitda_p).exists():
        raise SystemExit(f"ebitda_{stock}_*.json 를 찾을 수 없습니다(브릿지 필수). (STOP)")

    ebitda = _load(ebitda_p)
    surface = _load(surface_p) if surface_p and Path(surface_p).exists() else None
    screen = _load(screen_p) if screen_p and Path(screen_p).exists() else None

    notes = None
    if not args.no_context:
        notes = nctx.load_flat_notes(ebitda.get("company", {}).get("corp_code"))

    # 기간 게이트용 XBRL 기간 컨텍스트 맵(당기/전기). zip 은 앞 단계에서 캐시됨(추가 네트워크 없음).
    # 키 없음·오프라인이면 {} → 게이트는 인용·LLM 태그로 차선 작동(정직한 열화).
    import os as _os
    period_map = period_notes.fetch_period_map(
        ebitda.get("company", {}).get("corp_code"), ebitda.get("base_year"),
        _os.environ.get("OPENDART_API_KEY", ""))

    # BS값 게이트용 재무상태표 라인 잔액 — screen 이 이미 받아둔 base-year 전체 재무제표에서(추가 호출 없음).
    bs_amounts = set()
    if screen:
        prov = (screen.get("provenance") or {})
        by = ebitda.get("base_year")
        rp = (prov.get(str(by)) or {}).get("raw_path")
        if not rp and prov:
            rp = prov[max(prov, key=lambda s: int(s))].get("raw_path")
        if rp:
            rpp = Path(rp) if Path(rp).exists() else (PROJECT_ROOT / rp)
            if rpp.exists():
                bs_amounts = bs_amounts_won(_load(rpp))

    # [1b-2] 표 구조 상단 근거 발췌 — 매출원가/판관비 산술 정합 + 재고평가 개념코드 섹션(캐시된 zip).
    above_line_ev = ""
    if screen and bs_amounts is not None:
        try:
            from src.extract import opex_notes as _OX
            prov = (screen.get("provenance") or {})
            by = ebitda.get("base_year")
            rp2 = (prov.get(str(by)) or {}).get("raw_path") or (
                prov[max(prov, key=lambda s: int(s))].get("raw_path") if prov else None)
            if rp2:
                rpp2 = Path(rp2) if Path(rp2).exists() else (PROJECT_ROOT / rp2)
                if rpp2.exists():
                    _tg = _OX.opex_targets_from_raw(_load(rpp2))
                    above_line_ev = _OX.fetch_above_line_evidence(
                        ebitda.get("company", {}).get("corp_code"), by, _tg,
                        _os.environ.get("OPENDART_API_KEY", "")).get("text", "")
        except Exception:  # noqa: BLE001 — 실패 시 verbatim 만으로 게이트(대체 근거 없음)
            above_line_ev = ""

    view = build_view(
        ebitda=ebitda, surface=surface, screen=screen, notes=notes, period_map=period_map,
        bs_amounts=bs_amounts, above_line_ev=above_line_ev,
        sources={
            "ebitda": str(ebitda_p),
            "surface": str(surface_p) if surface else None,
            "screen": str(screen_p) if screen else None,
        },
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"screenview_{stock}_{stamp}.json"
    out_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {out_path}")
    m = view["meta"]
    print(f"  B(상단·조정대상)={m['adjust_count']}  C참고={m['reference_count']}  "
          f"C불명={m['reference_unknown_count']}  C정성={m['qualitative_count']}  "
          f"추정품질제외={m['excluded_estimation']}  합계행(산술)={m['containment_totals']}  "
          f"추정잠금={m['containment_estimated']}  경고쌍={m['containment_warn']}  "
          f"동일금액잠금={m['same_amount_locks']}  기간강등={m['period_gated']}  BS차단={m['bs_gated']}  표구조살림={m['table_rescued']}  "
          f"태그우선({m['tag_priority_count']})  원문맥락={m['context_present']}  "
          f"XBRL확정={m['xbrl_confirmed_count']}  표시위치불안정={m['unstable_display_count']}  "
          f"근거강등={m['gated_display_count']}  D&A차단={m['da_blocked_count']}  CIS라인={m['cis_lines_available']}  "
          f"base_EBITDA(백만)={view['bridge']['ebitda_base_million']:,.0f}")
    return out_path


if __name__ == "__main__":
    main()
