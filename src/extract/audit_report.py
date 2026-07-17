"""감사보고서 4문단 추출용 OpenDART 배관 (audit-issue-tracker s1_fetch 재사용, 판단 없음).

재사용한 것:
  - corp_code -> 최신 사업연도 사업보고서(A001, list.json)
  - 원문 ZIP(document.xml) -> DOCUMENT-NAME 이 '연결'∧'감사보고서'∧¬'별도'인 엔트리 단일 식별
    (별도감사보고서·사업보고서 본문 배제). 연결감사보고서 없는 판본은 자동 건너뛰고,
    어느 판본에도 없으면 '대상 부적격'으로 멈춘다(연결전용 원칙, 임의 선택 안 함).
바꾼 것: requests -> loop 1 의 DartClient(urllib) 재사용(캐시·스냅샷·manifest 공유).
가져오지 않은 것: 뉴스 검색어(s3)·네이버 뉴스(s4)·연도필터(s5)·랭킹(s6).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta, timezone

from .dart_client import StopConditionError

REPRT_A001 = "A001"  # 사업보고서 (OpenDART 공시상세유형)


def _document_name(xml_bytes: bytes) -> str:
    """문서 상단의 <DOCUMENT-NAME> 값(연결/별도 구분 근거)."""
    head = xml_bytes[:4000].decode("utf-8", errors="replace")
    m = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", head, re.S)
    return m.group(1).strip() if m else ""


def select_consolidated_audit(zip_bytes: bytes):
    """ZIP 엔트리 중 '연결감사보고서' 하나를 고른다. 정확히 1개 아니면 실패(식별 불가).

    구분 근거(코드 명시): DOCUMENT-NAME 에 '감사보고서'∧'연결'∧¬'별도'.
    반환: (entry_filename, document_name, entry_bytes).
    """
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    hits, inventory = [], []
    for info in zf.infolist():
        data = zf.read(info)
        name = _document_name(data)
        inventory.append((info.filename, name))
        if ("감사보고서" in name) and ("연결" in name) and ("별도" not in name):
            hits.append((info.filename, name, data))
    if len(hits) != 1:
        raise StopConditionError(
            "연결감사보고서 단일 식별 실패. "
            f"hits={[(f, n) for f, n, _ in hits]} inventory={inventory} (STOP)")
    return hits[0]


def _fiscal_year(report_nm: str):
    """'사업보고서 (2025.12)' -> 2025. 실패 시 None."""
    m = re.search(r"\((\d{4})\.\d{2}\)", report_nm or "")
    return int(m.group(1)) if m else None


def list_business_reports(client, corp_code: str, days_back: int = 450):
    """corp_code -> 사업보고서(A001) 목록. 날짜범위는 오늘 기준 역산(특정 날짜 하드코딩 안 함)."""
    end = datetime.now(timezone.utc).date()
    bgn = end - timedelta(days=days_back)
    res = client.get_json(
        "list.json",
        {"corp_code": corp_code, "pblntf_detail_ty": REPRT_A001,
         "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
         "page_no": 1, "page_count": 100},
        "list",
    )
    data = res["data"]
    if data.get("status") not in ("000", "013"):
        raise StopConditionError(
            f"list.json 오류 status={data.get('status')} msg={data.get('message')} (STOP)")
    return data.get("list", [])


def resolve_latest_consolidated(client, corp_code: str, days_back: int = 450) -> dict:
    """corp_code -> '연결감사보고서를 포함한' 최신 회계연도 사업보고서로 해석.

    최신 회계연도 filing 을 최신순으로 시도하며, 연결감사보고서가 실재하는 첫 건을 채택.
    부분정정 등 첨부 없는 판본은 건너뛴다. 반환: {corp_code, rcept_no, base_year, report_nm,
    entry, document_name, skipped}.
    """
    filings = list_business_reports(client, corp_code, days_back)
    yrs = [(_fiscal_year(f.get("report_nm")), f) for f in filings]
    yrs = [(y, f) for y, f in yrs if y is not None]
    if not yrs:
        raise StopConditionError(f"corp_code {corp_code} 사업보고서(A001) 없음 — 대상 부적격. (STOP)")
    latest = max(y for y, _ in yrs)
    cands = [f for y, f in yrs if y == latest]
    cands.sort(key=lambda f: (f.get("rcept_dt", ""), f.get("rcept_no", "")), reverse=True)

    skipped = []
    for f in cands:
        rcept = f.get("rcept_no")
        zip_bytes, _, _ = client.get_document_zip(rcept)
        try:
            entry, doc_name, _ = select_consolidated_audit(zip_bytes)
        except StopConditionError:
            skipped.append({"rcept_no": rcept, "report_nm": f.get("report_nm")})
            continue
        return {"corp_code": corp_code, "rcept_no": rcept, "base_year": latest,
                "report_nm": f.get("report_nm"), "entry": entry,
                "document_name": doc_name, "skipped": skipped}
    raise StopConditionError(
        f"대상 부적격: corp_code {corp_code} {latest} 연결감사보고서 없음. "
        f"확인 판본={[s['rcept_no'] for s in skipped]} (STOP)")


def fetch_audit_html(client, corp_code: str, days_back: int = 450):
    """corp_code -> (meta, 연결감사보고서 HTML/XML 텍스트)."""
    meta = resolve_latest_consolidated(client, corp_code, days_back)
    zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
    _, _, data = select_consolidated_audit(zip_bytes)
    return meta, data.decode("utf-8")
