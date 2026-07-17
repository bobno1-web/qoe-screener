"""screen 계산 layer: 다년 영업이익 vs 영업활동현금흐름 괴리 (순수 산수).

이 모듈은 I/O·네트워크·LLM 없이 (연도, 영업이익, 영업활동현금흐름) 시계열만 받아
원값 지표를 계산한다. 임계·색·라벨을 붙이지 않는다 — 판정선은 사람이 본다(no-hardcoding).
표시 layer와 섞지 않는다: 여기서는 숫자만 낸다. Decimal로 정확 계산, 재스케일 없음.
"""
from __future__ import annotations

from decimal import Decimal


def _dec(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def compute(series: list[dict]) -> dict:
    """series: [{'year': int, 'operating_income', 'operating_cash_flow'}] (Decimal 권장).

    원값 지표 dict 반환. 라벨/색/임계 없음.
      - 연도별: 영업이익, 영업활동현금흐름, 발생액(=이익-현금), ocf_below_oi(사실 비교)
      - 누적 영업이익, 누적 영업활동현금흐름, 누적 발생액(=누적이익-누적현금)
      - 누적 괴리 비율 = 누적 영업활동현금흐름 ÷ 누적 영업이익 (분모 0이면 None+사유)
      - 지속연수 = 가장 최근 해부터 영업현금흐름이 영업이익에 미달한 해가 몇 년 연속인지
    """
    rows = sorted(series, key=lambda r: r["year"])
    per_year = []
    for r in rows:
        oi = _dec(r["operating_income"])
        ocf = _dec(r["operating_cash_flow"])
        per_year.append({
            "year": int(r["year"]),
            "operating_income": oi,
            "operating_cash_flow": ocf,
            "accruals": oi - ocf,          # 발생액(연도) = 영업이익 - 영업활동현금흐름
            "ocf_below_oi": ocf < oi,      # 사실 비교(라벨 아님): 현금흐름 < 이익
        })

    cum_oi = sum((y["operating_income"] for y in per_year), Decimal(0))
    cum_ocf = sum((y["operating_cash_flow"] for y in per_year), Decimal(0))
    cum_accruals = cum_oi - cum_ocf

    if cum_oi == 0:
        cum_ratio = None
        ratio_note = ("누적 영업이익이 0이라 비율(누적 영업활동현금흐름 ÷ 누적 영업이익)이 "
                      "정의되지 않음. 원값(누적 발생액 등)으로 판단할 것.")
    else:
        cum_ratio = cum_ocf / cum_oi
        ratio_note = None

    # 지속연수: 최근 해부터 거꾸로, 영업현금흐름이 영업이익에 미달(strict <)한 연속 연수
    duration = 0
    for y in reversed(per_year):
        if y["ocf_below_oi"]:
            duration += 1
        else:
            break

    return {
        "years_count": len(per_year),
        "first_year": per_year[0]["year"] if per_year else None,
        "last_year": per_year[-1]["year"] if per_year else None,
        "per_year": per_year,
        "cumulative_operating_income": cum_oi,
        "cumulative_operating_cash_flow": cum_ocf,
        "cumulative_accruals": cum_accruals,
        "cumulative_divergence_ratio": cum_ratio,
        "cumulative_divergence_ratio_note": ratio_note,
        "consecutive_recent_years_ocf_below_oi": duration,
    }
