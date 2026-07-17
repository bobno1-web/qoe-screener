"""연결재무제표(CFS)에서 연도별 영업이익·영업활동현금흐름 추출 (dartlens 파싱 배관 재사용).

- fnlttSinglAcntAll(전체 재무제표) 한 번 호출로 그 해의 모든 재무제표 행을 받는다.
  영업이익은 손익계산서(sj_div IS/CIS)에, 영업활동현금흐름은 현금흐름표(sj_div CF)에 있다.
- 표준 IFRS/DART 계정(account_id)으로 구조적 위치를 찾는다. 이는 회계기준이 정한 보편
  구조이므로 하드코딩이 아니다(no-hardcoding 예외). account_nm 매칭은 account_id가 없을
  때의 폴백이며, 지정된 sj_div 안에서만 찾는다(다른 표의 동명 계정 오검출 방지).
  주의: 여기서 하는 건 "표준 계정의 위치 찾기"지, "일회성 여부 판단"이 아니다.
- 금액은 dartlens parse_amount 그대로: 공란/'-'는 0이 아니라 None, 괄호는 음수, verbatim.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

REPRT_ANNUAL = "11011"  # 사업보고서 (OpenDART 표준 보고서 코드)

# 표준 개념 -> (재무제표 sj_div, 후보 account_id, 후보 account_nm). 산업 무관 IFRS/DART 개념.
OPERATING_INCOME = {
    "concept": "영업이익",
    "sj_div": ("IS", "CIS"),
    "ids": ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"),
    "nm": ("영업이익", "영업이익(손실)"),
}
OPERATING_CASH_FLOW = {
    "concept": "영업활동현금흐름",
    "sj_div": ("CF",),
    "ids": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
    "nm": ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로 인한 현금흐름"),
}


def parse_amount(raw):
    """OpenDART 금액 문자열 -> Decimal. 공란/'-'는 None(0 아님), 괄호는 음수."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def _rows(data):
    return data.get("list") or []


def detect(data: dict, spec: dict) -> dict:
    """구조적 위치로 한 개념의 금액을 찾고 인용 근거를 함께 반환.

    반환: {amount, account_id, account_nm, sj_div, sj_nm, match, rcept_no, ord}.
          없으면 match == 'MISSING' (숨기지 않고 노출).
    우선순위: (1) 표준 account_id (2) 정확 account_nm (3) account_nm 포함.
    모두 spec['sj_div'] 안에서만 탐색.
    """
    cand = [r for r in _rows(data) if (r.get("sj_div") or "").strip() in spec["sj_div"]]

    def build(it, how):
        return {
            "amount": parse_amount(it.get("thstrm_amount")),
            "account_id": (it.get("account_id") or "").strip(),
            "account_nm": (it.get("account_nm") or "").strip(),
            "sj_div": (it.get("sj_div") or "").strip(),
            "sj_nm": (it.get("sj_nm") or "").strip(),
            "match": how,
            "rcept_no": (it.get("rcept_no") or "").strip(),
            "ord": it.get("ord", ""),
        }

    for it in cand:
        if (it.get("account_id") or "").strip() in spec["ids"]:
            return build(it, "account_id")
    for it in cand:
        if (it.get("account_nm") or "").strip() in spec["nm"]:
            return build(it, "account_nm")
    for it in cand:
        nm = (it.get("account_nm") or "").strip()
        if any(k in nm for k in spec["nm"]):
            return build(it, "account_nm_contains")
    return {"amount": None, "account_id": "", "account_nm": "", "sj_div": "",
            "sj_nm": "", "match": "MISSING", "rcept_no": "", "ord": ""}


def fetch_year(client, corp_code: str, bsns_year, fs_div: str = "CFS"):
    """그 해의 전체 CFS 재무제표를 받아 (data, status, request_hash, raw_path) 반환."""
    res = client.get_json(
        "fnlttSinglAcntAll.json",
        {"corp_code": corp_code, "bsns_year": str(bsns_year),
         "reprt_code": REPRT_ANNUAL, "fs_div": fs_div},
        "fnlttSinglAcntAll",
    )
    return res["data"], res.get("status"), res["request_hash"], res["raw_path"]


def collect_series(client, corp_code: str, years, fs_div: str = "CFS"):
    """연도 리스트에 대해 영업이익·영업활동현금흐름 수집.

    반환: (found, missing)
      found   = [{year, operating_income, operating_cash_flow, citations, request_hash,
                  raw_path}] (오름차순, 두 값 모두 존재하는 해만)
      missing = [{year, reason}] (데이터 없음/계정 누락은 숨기지 않고 기록)
    """
    found, missing = [], []
    for y in years:
        data, status, req_hash, raw_path = fetch_year(client, corp_code, y, fs_div)
        if status != "000":
            missing.append({"year": int(y), "reason": f"status={status}"})
            continue
        oi = detect(data, OPERATING_INCOME)
        ocf = detect(data, OPERATING_CASH_FLOW)
        if oi["amount"] is None or ocf["amount"] is None:
            missing.append({"year": int(y),
                            "reason": f"oi_match={oi['match']}, ocf_match={ocf['match']}"})
            continue
        found.append({
            "year": int(y),
            "operating_income": oi["amount"],
            "operating_cash_flow": ocf["amount"],
            "citations": {"operating_income": oi, "operating_cash_flow": ocf},
            "request_hash": req_hash,
            "raw_path": raw_path,
        })
    found.sort(key=lambda r: r["year"])
    return found, missing
