"""EBITDA 조립 실행기(경계 I/O): 영업이익(재무제표) + D&A(주석) = EBITDA. 결정론적, LLM 없음.

흐름: 대상 회사 최신 사업보고서 기준연도로
  1) 주석에서 D&A 추출(da_notes, 개념코드 구조 추출) — 그 해 기준연도를 여기서 확정.
  2) 같은 해 fnlttSinglAcntAll 에서 영업이익 추출(financials, account_id 구조 추출).
  3) EBITDA = 영업이익 + D&A (원 단위로 정합). 임계·색·라벨 없음.
모든 숫자에 출처(주석 인용/재무제표 계정) 를 단다. D&A 를 못 뽑으면 추정 없이 '추출 불가+사유'로.

사용:
  set -a; source ../.env; set +a
  python src/screen/ebitda_run.py --stock-code 000660
  python src/screen/ebitda_run.py --corp-code 00126380 --fs-div CFS
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
OUT_DIR = PROJECT_ROOT / "out"


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else str(obj)
    return obj


def _collect(args):
    from src.extract import corp_codes as cc
    from src.extract.da_notes import fetch_da
    from src.extract.dart_client import DartClient
    from src.extract.financials import OPERATING_INCOME, detect, fetch_year

    api_key = os.environ.get("OPENDART_API_KEY")
    if not api_key:
        raise SystemExit("환경변수 OPENDART_API_KEY 가 필요합니다. (STOP)")

    cache = OUT_DIR / "_raw"
    client = DartClient(api_key=api_key, raw_dir=cache, cache_dir=cache, project_root=PROJECT_ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    if args.corp_code:
        hits = [r for r in records if r["corp_code"] == args.corp_code.strip()]
        if not hits:
            raise SystemExit(f"corp_code {args.corp_code} 없음. (STOP)")
        target = hits[0]
    elif args.stock_code:
        target = cc.resolve_by_stock(records, args.stock_code)
    else:
        target = cc.resolve_by_name(records, args.name)
    corp_code = target["corp_code"]

    # 1) D&A (주석) — 기준연도 확정
    da_meta, da = fetch_da(client, corp_code, which=args.notes_scope)
    base_year = da_meta["base_year"]

    # 2) 영업이익 (같은 해 재무제표)
    data, status, req_hash, raw_path = fetch_year(client, corp_code, base_year, args.fs_div)
    oi = detect(data, OPERATING_INCOME) if status == "000" else {"amount": None, "match": f"status={status}"}
    oi_won = oi.get("amount")

    company = {"corp_code": corp_code, "corp_name": target.get("corp_name", ""),
               "stock_code": target.get("stock_code", "")}
    return company, base_year, oi, oi_won, req_hash if status == "000" else None, raw_path if status == "000" else None, da_meta, da, args


def _build(company, base_year, oi, oi_won, req_hash, raw_path, da_meta, da, args):
    da_won = da.get("operating_da_won") if da.get("present") else None
    ebitda_won = None
    unresolved = []
    if oi_won is None:
        unresolved.append(f"영업이익 추출 실패(match={oi.get('match')})")
    if not da.get("present"):
        unresolved.append(f"D&A 추출 불가({da.get('reason')})")
    elif da_won is None:
        unresolved.append(f"D&A 단위 미검출(unit={da.get('unit')!r}) → 원 단위 정합 불가")
    elif da.get("reason"):
        unresolved.append(da.get("reason"))
    if oi_won is not None and da_won is not None:
        ebitda_won = oi_won + da_won

    return {
        "schema_version": "ebitda/2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ("정상화 기준선 EBITDA = 영업이익 + (감가상각비 + 무형자산상각비 + 리스 사용권자산 감가상각비). "
                 "영업이익에 이미 차감된 상각비만 가산. 원값·출처만, 판정/임계 없음."),
        "company": company,
        "base_year": base_year,
        "fs_div": args.fs_div,
        "operating_income": {
            "amount_won": oi_won,
            "source": {"account_id": oi.get("account_id"), "account_nm": oi.get("account_nm"),
                       "sj_nm": oi.get("sj_nm"), "match": oi.get("match"),
                       "rcept_no": oi.get("rcept_no"), "reprt": "11011(사업보고서)"},
            "provenance": {"request_hash": req_hash, "raw_path": raw_path},
        },
        "da": {
            "present": da.get("present"),
            "path": da.get("path"),                 # 성격별 | 개별주석
            "method": da.get("method"),             # 성격별-combined | 성격별-sum | 개별주석-sum
            "note_title": da.get("note_title"),
            "unit": da.get("unit"),
            "operating_da_won": da_won,             # EBITDA 가산액(원)
            "lines": da.get("lines"),               # 감가/무형/리스 각 줄: A/B/C·가산여부·출처
            "lease": da.get("lease"),               # 리스 별도줄 요약(통합/미검출 포함)
            "cross_check": da.get("cross_check"),   # 성격별 vs 개별합 vs 현금흐름표
            "reason": da.get("reason"),
            "provenance": {"rcept_no": da_meta.get("rcept_no"), "entry": da_meta.get("entry"),
                           "document_name": da_meta.get("document_name"),
                           "notes_scope": da_meta.get("notes_scope")},
        },
        "ebitda": {
            "amount_won": ebitda_won,
            "amount_million": (ebitda_won / Decimal(1_000_000)) if ebitda_won is not None else None,
            "formula": "operating_income + operating_da (원 단위)",
            "computable": ebitda_won is not None,
            "unresolved": unresolved,
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="EBITDA = 영업이익 + D&A(주석). 원값·출처, 판정 없음.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stock-code")
    g.add_argument("--corp-code")
    g.add_argument("--name")
    p.add_argument("--fs-div", default="CFS", choices=["CFS", "OFS"])
    p.add_argument("--notes-scope", default="consolidated", choices=["consolidated", "separate"])
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not (args.stock_code or args.corp_code or args.name):
        raise SystemExit("--stock-code / --corp-code / --name 중 하나가 필요합니다. (STOP)")

    out = to_jsonable(_build(*_collect(args)))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ident = out["company"].get("stock_code") or out["company"].get("corp_code")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"ebitda_{ident}_{stamp}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {path}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return path


if __name__ == "__main__":
    main()
