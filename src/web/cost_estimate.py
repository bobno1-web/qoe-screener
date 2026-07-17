"""surface(LLM) 실행 비용·시간 추정 — 표시 전용. 분석을 지배하지 않는다.

이 값들은 실측 앵커(SK하이닉스, 2026-07-15)를 주석 길이로 선형 스케일한 '추정'이다.
판정선(임계)이 아니라 사용자에게 알고 시작하게 하는 안내라, no-hardcoding 이 금하는
'판단을 지배하는 마법 상수'가 아니다(비용은 분석 결과·게이트에 영향 0). 실제 청구는
Anthropic usage 가 정하며, 여기 숫자는 시작 전 눈금일 뿐이다.

실측 앵커(6콜=1차 3 + 2차 3, Opus, 프롬프트 캐싱 on):
  주석 106,179자 → 캐시 적용 $5.04 (입력 $2.37 + 출력 $2.70), 소요 6.4~8.2분.
출력 비용은 후보 수에 달려 주석 길이와 거의 무관(≈상수), 입력 비용은 주석 길이에 비례.
그래서 cost ≈ 출력상수 + 입력앵커 × (주석자수 / 앵커자수).
"""
from __future__ import annotations

# ── 실측 앵커 (SK, 2026-07-15) — 바꾸려면 새 측정으로 교체 ──────────────
_ANCHOR_NOTES_CHARS = 106_179     # SK 연결주석 정규화 길이(자)
_OUTPUT_USD_FIXED = 2.70          # 출력 토큰 비용(캐시 무관·후보 수에 달림 ≈ 상수)
_INPUT_USD_AT_ANCHOR = 2.37       # 앵커 주석 길이에서의 캐시 적용 입력 비용(길이에 비례)
_MIN_LOW, _MIN_HIGH = 6, 9        # 소요 시간 범위(분) — 출력/추론 바운드, 주석 길이와 무관(실측)
_MARGIN_LOW, _MARGIN_HIGH = 0.8, 1.25   # 표시 범위 여유(추정 불확실성)


def estimate(notes_chars: int | None) -> dict:
    """주석 길이(자) → 비용·시간 추정. notes_chars 모르면(None) 앵커로 대략 안내.

    반환: {usd, usd_low, usd_high, minutes_low, minutes_high, notes_chars, basis}
    비용은 새 전체 분석(6콜, Opus, 캐싱 on) 기준. 재사용(저장분)은 $0·즉시 — 호출측이 처리.
    """
    chars = int(notes_chars) if notes_chars else _ANCHOR_NOTES_CHARS
    ratio = chars / _ANCHOR_NOTES_CHARS
    usd = _OUTPUT_USD_FIXED + _INPUT_USD_AT_ANCHOR * ratio
    return {
        "usd": round(usd, 1),
        "usd_low": round(usd * _MARGIN_LOW, 1),
        "usd_high": round(usd * _MARGIN_HIGH, 1),
        "minutes_low": _MIN_LOW,
        "minutes_high": _MIN_HIGH,
        "notes_chars": chars,
        "approx": notes_chars is None,     # 주석 길이 미상 → 앵커 근사임을 표시
        "basis": "실측(SK, 6콜·Opus·캐싱) 기준 추정 — 실제 청구는 Anthropic usage",
    }
