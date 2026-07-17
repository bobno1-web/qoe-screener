"""페이지 1 — 이익의 질(質) 지표. 재무제표 숫자로만 결정론 계산. LLM·추측 없음.

- 데이터 원천: screen 이 이미 연도별로 받아둔 fnlttSinglAcntAll(전체 재무제표) 캐시. 여기서
  매출·매출원가·매출채권·재고·자산총계를 표준 XBRL 개념코드로 뽑는다(financials.detect 재사용).
  개념코드(account_id) 우선, 없으면 지정 sj_div 안에서 표준 계정명 폴백 — "표준 라인 찾기"지
  "일회성 판정"이 아니다(no-keyword-heuristics 준수, financials.py 와 같은 원칙).
- 지표는 전부 산수(비율·차이·추이). **임계·색·등급으로 판정하지 않는다**(no-hardcoding). 산업마다
  정상 범위가 달라 도구가 선을 긋지 않는다 — 숫자와 추이만 내고 판정은 사람이 한다.
- 없는 값은 억지로 채우지 않는다: 금액 None → 지표 None + 사유("해당 없음"). 0 나눗셈도 None.
- 한 회사의 자기 시계열만 본다(동종업계 벤치마크 없음 — 데이터 없음).
"""
from __future__ import annotations

from decimal import Decimal

from src.extract import financials as F

# 표준 개념 스펙(financials.detect 형식). income 계열은 회사가 IS/CIS 어디에 두든 잡히게 둘 다.
# (삼성전자는 매출·매출원가·영업이익을 별도 손익계산서 IS 에 둔다 — docs/limitations §5.)
REVENUE = {
    "concept": "매출", "sj_div": ("IS", "CIS"),
    "ids": ("ifrs-full_Revenue",),
    "nm": ("매출액", "수익(매출액)", "영업수익", "매출"),
}
COST_OF_SALES = {
    "concept": "매출원가", "sj_div": ("IS", "CIS"),
    "ids": ("ifrs-full_CostOfSales",),
    "nm": ("매출원가",),
}
TOTAL_ASSETS = {
    "concept": "자산총계", "sj_div": ("BS",),
    "ids": ("ifrs-full_Assets",),
    "nm": ("자산총계",),
}
TRADE_RECEIVABLES = {
    "concept": "매출채권", "sj_div": ("BS",),
    # 순수 매출채권 우선, 없으면 '매출채권 및 기타채권' 합계행(대한항공·롯데). 어느 라인을 썼는지
    # 인용에 account_nm/개념코드로 그대로 드러내 사용자가 무엇을 본지 알게 한다(투명성).
    "ids": ("ifrs-full_CurrentTradeReceivables", "ifrs-full_TradeAndOtherCurrentReceivables"),
    "nm": ("매출채권", "매출채권및기타채권", "매출채권 및 기타채권", "매출채권및기타유동채권"),
}
INVENTORIES = {
    "concept": "재고자산", "sj_div": ("BS",),
    "ids": ("ifrs-full_Inventories",),
    "nm": ("재고자산",),
}

# 재사용: 영업이익·영업활동현금흐름은 screen 과 같은 스펙(financials.py).
LINE_SPECS = {
    "revenue": REVENUE,
    "cost_of_sales": COST_OF_SALES,
    "operating_income": F.OPERATING_INCOME,
    "operating_cash_flow": F.OPERATING_CASH_FLOW,
    "total_assets": TOTAL_ASSETS,
    "trade_receivables": TRADE_RECEIVABLES,
    "inventories": INVENTORIES,
}

DAYS_IN_YEAR = 365  # 회수기간·재고일수 환산용 상수(달력 상수 — 판정 임계가 아니다).


def extract_year(raw: dict) -> dict:
    """한 해의 전체 재무제표(raw fnlttSinglAcntAll)에서 라인들을 결정론 추출.

    반환 {line_key: detect_result}. detect_result 는 financials.detect 형식
    (amount:Decimal|None, account_id, account_nm, sj_div, sj_nm, match, ord).
    """
    return {key: F.detect(raw, spec) for key, spec in LINE_SPECS.items()}


def _won(item):
    """detect_result → 금액(Decimal) 또는 None."""
    if not item:
        return None
    a = item.get("amount")
    return a if isinstance(a, Decimal) else (Decimal(str(a)) if a is not None else None)


def _ratio(num, den):
    """num/den. 둘 다 있고 den!=0 이면 float, 아니면 None. 부호·음수 그대로(판정 없음)."""
    if num is None or den is None or den == 0:
        return None
    return float(num / den)


def _int(x):
    return int(x) if x is not None else None


def compute_metrics(years: list, ebitda: dict | None = None) -> dict:
    """years = [{"year":int, "items":{line_key:detect_result}}] 오름차순. 지표를 결정론 계산.

    각 지표: per_year 행 + (해당 시)누적. 값이 없으면 None + na_reason. 임계·색·등급 없음.
    """
    ys = sorted(years, key=lambda r: r["year"])

    def series(key):
        return [(_won(r["items"].get(key))) for r in ys]

    yr = [r["year"] for r in ys]
    rev = series("revenue")
    cogs = series("cost_of_sales")
    oi = series("operating_income")
    ocf = series("operating_cash_flow")
    assets = series("total_assets")
    recv = series("trade_receivables")
    inv = series("inventories")

    # 1) 영업이익 vs 영업현금흐름 + 발생액(=영업이익−영업현금흐름)
    accrual = [(_o - _c if (_o is not None and _c is not None) else None)
               for _o, _c in zip(oi, ocf)]
    m_oi_ocf = {
        "per_year": [{
            "year": y,
            "operating_income": _int(o), "operating_cash_flow": _int(c),
            "accrual": _int(a),
        } for y, o, c, a in zip(yr, oi, ocf, accrual)],
        "cumulative": {
            "operating_income": _int(_sum(oi)),
            "operating_cash_flow": _int(_sum(ocf)),
            "accrual": _int(_sum(accrual)),
        },
    }

    # 2) 발생액 비율 = 발생액 ÷ 총자산, 발생액 ÷ 매출
    m_accrual_ratio = {"per_year": [{
        "year": y,
        "accrual": _int(a),
        "over_assets": _ratio(a, ta),
        "over_revenue": _ratio(a, rv),
    } for y, a, ta, rv in zip(yr, accrual, assets, rev)]}

    # 3) 매출채권 회전 = 매출채권 ÷ 매출, 회수기간(일) = 365 × 매출채권 ÷ 매출
    m_recv = {"per_year": [{
        "year": y, "trade_receivables": _int(rc), "revenue": _int(rv),
        "over_revenue": _ratio(rc, rv),
        "days": (_ratio(rc, rv) * DAYS_IN_YEAR if _ratio(rc, rv) is not None else None),
    } for y, rc, rv in zip(yr, recv, rev)]}

    # 4) 재고 회전 = 재고 ÷ 매출원가, 재고일수 = 365 × 재고 ÷ 매출원가
    m_inv = {"per_year": [{
        "year": y, "inventories": _int(iv), "cost_of_sales": _int(cg),
        "over_cogs": _ratio(iv, cg),
        "days": (_ratio(iv, cg) * DAYS_IN_YEAR if _ratio(iv, cg) is not None else None),
    } for y, iv, cg in zip(yr, inv, cogs)]}

    # 5) EBITDA(우리가 계산) vs 영업현금흐름 — D&A 는 기준연도만 뽑으므로 기준연도 1개 비교.
    m_ebitda_ocf = _ebitda_vs_ocf(ebitda, yr, ocf)

    # 6) 영업이익률 = 영업이익 ÷ 매출
    m_margin = {"per_year": [{
        "year": y, "operating_income": _int(o), "revenue": _int(rv),
        "margin": _ratio(o, rv),
    } for y, o, rv in zip(yr, oi, rev)]}

    return {
        "years": yr,
        "oi_vs_ocf": m_oi_ocf,
        "accrual_ratio": m_accrual_ratio,
        "receivables_turnover": m_recv,
        "inventory_turnover": m_inv,
        "ebitda_vs_ocf": m_ebitda_ocf,
        "operating_margin": m_margin,
    }


def _sum(vals):
    present = [v for v in vals if v is not None]
    return sum(present) if present else None


def _ebitda_vs_ocf(ebitda, yr, ocf):
    """기준연도 EBITDA(=영업이익+가산 D&A) vs 그 해 영업현금흐름. 차이=EBITDA−OCF."""
    if not ebitda:
        return {"available": False, "na_reason": "EBITDA(D&A) 산출물 없음"}
    oi = (ebitda.get("operating_income") or {})
    oi_won = oi.get("amount_won")
    da_won = ((ebitda.get("da") or {}).get("operating_da_won")) or 0
    base_year = ebitda.get("base_year")
    if oi_won is None or base_year is None:
        return {"available": False, "na_reason": "EBITDA 기준연도/영업이익 없음"}
    ebitda_won = oi_won + da_won
    ocf_by_year = {y: c for y, c in zip(yr, ocf)}
    try:
        by = int(base_year)
    except (TypeError, ValueError):
        by = base_year
    base_ocf = ocf_by_year.get(by)
    diff = (ebitda_won - base_ocf) if base_ocf is not None else None
    return {
        "available": True,
        "base_year": by,
        "ebitda": int(ebitda_won),
        "operating_cash_flow": (int(base_ocf) if base_ocf is not None else None),
        "difference": (int(diff) if diff is not None else None),
        "na_reason": (None if base_ocf is not None else f"{by}년 영업현금흐름 없음"),
    }
