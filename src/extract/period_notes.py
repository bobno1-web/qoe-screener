"""기간(당기/전기) 판정 — surface 후보 금액이 '당기 것'인지 확인해 조정 자격을 게이팅한다.

왜 필요한가: D&A·영업이익은 XBRL 개념코드로 뽑아 기간이 확실(CFY{연도}dFY)하지만, surface 후보는
주석 텍스트에서 LLM 이 읽은 것이라 기간 보장이 없다. 주석은 당기·전기를 나란히 적으므로 LLM 이 전기
금액을 집을 수 있다(네이버 스톡그랜트 80,180 은 전기 금액인데 당기 구역 B 로 올라왔다). 토글하면
작년 숫자가 올해 EBITDA 에 반영된다 — 기존 게이트 중 '이 금액이 당기 것인가'를 보는 건 하나도 없었다.

판정 우선순위(결정론 우선, 언어표현 차선):
  1. **XBRL 기간 컨텍스트**(`<TE ACONTEXT>` 의 CFY{base_year}=당기 / PFY=전기): 후보 금액이 주석의
     기간태그 셀과 일치하면 그 셀의 기간으로 결정론 판정. 당기 셀에만 있으면 당기, 전기 셀에만 있으면
     전기, 둘 다면 양기(모호)→차선으로. XBRL 표준 구조라 계정명 키워드 아님(no-keyword 예외).
  2. **인용의 기간 표현**(XBRL 대조 불가한 서술형 금액): 금액 앞의 가장 가까운 기간 표현(당기/전기).
     계정명 키워드가 아니라 '인용이 어느 기간을 말하는지'를 본다. '전기차·전기요금·전기전자' 같은 합성어의
     '전기'는 lookahead 로 제외(기간어 '전기'는 뒤에 공백·중·말·:·( 등이 온다).
  3. 그마저 없으면 **불명** → 조정 불가(구역 C). 추측 금지.
"""
from __future__ import annotations

import re

from . import financials as F
from .da_notes import (_TE_RE, _TR_RE, _ATTR, _consolidated_notes_slice,
                       _titles_pos, detect_unit, _text)
from .notes_body import resolve_latest_business_report, select_business_report_body

# 기간어 판별 — 뒤에 기간 문맥 토큰이 오는 '당기/전기'만(합성어 전기차·전기요금 제외).
_CUR_RE = re.compile(r"당기(?=[\s중말초에:,()]|$)")
_PRI_RE = re.compile(r"전기(?=[\s중말초에:,()]|$)|직전\s*(?:연도|사업연도|기)")


def build_period_map(notes_raw: str, base_year: int) -> dict:
    """raw 주석 → {amount_won: set(기간토큰)}. 기간토큰: 'CFY{by}...'=당기 / 'PFY...'=전기.

    각 주석 섹션의 단위(백만원 등)로 셀 값을 원으로 환산해, 그 금액이 어느 기간 컨텍스트에 나타나는지 모은다.
    """
    titles = _titles_pos(notes_raw)
    m: dict = {}
    for i, (pos, _lab) in enumerate(titles):
        nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes_raw)
        seg = notes_raw[pos:nxt]
        _ustr, umult = detect_unit(seg)
        if umult is None:
            continue
        for trm in _TR_RE.finditer(seg):
            for tm in _TE_RE.finditer(trm.group(1)):
                ctx = _ATTR(tm.group(1), "ACONTEXT")
                if not ctx:
                    continue
                v = F.parse_amount(_text(tm.group(2)))
                if v is None:
                    continue
                won = abs(int(v)) * umult
                if won:
                    m.setdefault(won, set()).add(ctx.split("_", 1)[0])
    return m


def classify_xbrl(amount_won, period_map: dict, base_year) -> str | None:
    """XBRL 기간 컨텍스트로 결정론 판정. 당기/전기/양기(둘 다)/None(대조 불가)."""
    if amount_won is None or not period_map:
        return None
    toks = period_map.get(abs(int(amount_won)))
    if not toks:
        return None
    cfy = any(t.startswith(f"CFY{base_year}") for t in toks)
    pfy = any(t.startswith("PFY") for t in toks)
    if cfy and not pfy:
        return "당기"
    if pfy and not cfy:
        return "전기"
    return "양기"          # 당기·전기 둘 다(같은 값)면 모호 → 차선(인용)으로


def citation_period(citation: str, amount_display) -> str | None:
    """인용에서 금액 앞의 가장 가까운 기간 표현. 당기/전기/None. 계정명 아니라 기간어만 본다."""
    if not citation:
        return None
    cit = str(citation)
    idx = cit.find(str(amount_display).strip()) if amount_display else -1
    scope = cit if idx < 0 else cit[:idx]      # 금액 앞 텍스트(못 찾으면 전체)
    cur = [mm.start() for mm in _CUR_RE.finditer(scope)]
    pri = [mm.start() for mm in _PRI_RE.finditer(scope)]
    lc = max(cur) if cur else -1
    lp = max(pri) if pri else -1
    if lc < 0 and lp < 0:
        return None
    return "당기" if lc > lp else "전기"


def detect_period(row: dict, period_map: dict, base_year) -> tuple:
    """후보의 기간을 판정. 반환 (period, basis): period∈{당기,전기,불명}, basis∈{xbrl,citation,llm,None}.

    우선순위: XBRL 결정론 > 인용 기간표현 > LLM 태그(전기만 신뢰해 강등) > 불명. 당기로 인정(구역 B 허용)
    하려면 XBRL·인용의 '적극적 당기 근거'가 필요하다 — 근거 없으면 불명(표시위치와 같은 보수·비대칭).
    """
    x = classify_xbrl(row.get("amount_won"), period_map, base_year)
    if x in ("당기", "전기"):
        return x, "xbrl"
    # 양기(모호) 또는 XBRL 대조 불가 → 인용
    c = citation_period(row.get("인용"), row.get("amount_display"))
    if c in ("당기", "전기"):
        return c, "citation"
    # LLM 기간 태그: 강등(전기)만 신뢰. 당기 주장은 근거 없으면 안 받는다(보수).
    llm = str(row.get("기간") or "").strip()
    if llm == "전기":
        return "전기", "llm"
    return "불명", None


def fetch_period_map(corp_code: str, base_year: int, api_key: str,
                     which: str = "consolidated", days_back: int = 450) -> dict:
    """corp_code → 기간 맵. 최신 사업보고서 본문 raw 주석에서 파싱(zip 은 앞 단계에서 캐시됨).

    실패(키 없음·오프라인·파싱 오류)하면 {} 반환 — 게이트는 인용·LLM 태그로 차선 작동한다(정직한 열화).
    """
    try:
        from pathlib import Path

        from .dart_client import DartClient
        project_root = Path(__file__).resolve().parents[2]
        cache = project_root / "out" / "_raw"
        client = DartClient(api_key=api_key or "", raw_dir=cache, cache_dir=cache,
                            project_root=project_root)
        meta = resolve_latest_business_report(client, corp_code, days_back)
        zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
        _, _, data = select_business_report_body(zip_bytes)
        notes_raw = _consolidated_notes_slice(data.decode("utf-8", errors="replace"), which=which)
        return build_period_map(notes_raw, base_year)
    except Exception:      # noqa: BLE001 — 실패는 조용히 {} (차선 경로가 받는다)
        return {}
