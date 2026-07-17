"""screen 실행기(경계 I/O): 대상 회사 하나의 다년 영업이익 vs 영업활동현금흐름 괴리를
계산해 out/에 구조화 JSON으로 저장.

흐름: extract(수집·파싱) -> screen.divergence.compute(순수 산수) -> JSON 직렬화.
계산 layer와 표시 layer를 섞지 않는다. LLM 없음. 위험/안전 판정 없음(사람이 본다).

사용:
  # 실데이터(OpenDART): 환경변수 OPENDART_API_KEY 필요
  python src/screen/run.py --stock-code 005930 --years-back 5
  python src/screen/run.py --corp-code 00126380 --end-year 2024 --years-back 5
  # 오프라인 재현(픽스처): API·네트워크 불필요, 결정론적
  python src/screen/run.py --fixture <path.json>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.screen import divergence  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"


def _dec(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def to_jsonable(obj):
    """Decimal 정수 -> int, 비정수 -> str(정밀 보존). dict/list 재귀, bool/None 유지."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else str(obj)
    return obj


def _load_fixture(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    company = raw.get("company", {})
    series = [{
        "year": int(year),
        "operating_income": _dec(vals["operating_income"]),
        "operating_cash_flow": _dec(vals["operating_cash_flow"]),
    } for year, vals in raw["series"].items()]
    meta = {
        "source": f"fixture:{path}",
        "years_requested": sorted(int(y) for y in raw["series"].keys()),
        "years_missing": raw.get("years_missing", []),
        "citations": raw.get("citations", {}),
        "provenance": {},
    }
    return company, series, meta


def _collect_live(args):
    from src.extract import corp_codes as cc
    from src.extract.dart_client import DartClient
    from src.extract.financials import REPRT_ANNUAL, collect_series

    api_key = os.environ.get("OPENDART_API_KEY")
    if not api_key:
        raise SystemExit("환경변수 OPENDART_API_KEY 가 필요합니다. (STOP)")

    cache_dir = OUT_DIR / "_raw"
    client = DartClient(api_key=api_key, raw_dir=cache_dir, cache_dir=cache_dir,
                        project_root=PROJECT_ROOT)

    records = cc.parse_corp_codes(client.get_corpcode_xml())
    if args.corp_code:
        hits = [r for r in records if r["corp_code"] == args.corp_code.strip()]
        if not hits:
            raise SystemExit(
                f"corp_code {args.corp_code} 를 corpCode 마스터에서 찾지 못했습니다. (STOP)")
        target = hits[0]
    elif args.stock_code:
        target = cc.resolve_by_stock(records, args.stock_code)
    else:
        target = cc.resolve_by_name(records, args.name)

    end_year = args.end_year or (datetime.now().year - 1)
    years = list(range(end_year - args.years_back + 1, end_year + 1))
    found, missing = collect_series(client, target["corp_code"], years, fs_div=args.fs_div)

    series = [{"year": r["year"],
               "operating_income": r["operating_income"],
               "operating_cash_flow": r["operating_cash_flow"]} for r in found]
    company = {"corp_code": target["corp_code"],
               "corp_name": target.get("corp_name", ""),
               "stock_code": target.get("stock_code", "")}
    meta = {
        "source": "opendart:fnlttSinglAcntAll",
        "reprt_code": REPRT_ANNUAL,
        "fs_div": args.fs_div,
        "years_requested": years,
        "years_missing": missing,
        "citations": {str(r["year"]): r["citations"] for r in found},
        "provenance": {str(r["year"]): {"request_hash": r["request_hash"],
                                        "raw_path": r["raw_path"]} for r in found},
    }
    return company, series, meta


def main(argv=None):
    p = argparse.ArgumentParser(
        description="screen: 다년 영업이익 vs 영업활동현금흐름 괴리 (원값, 판정 없음)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stock-code")
    g.add_argument("--corp-code")
    g.add_argument("--name")
    p.add_argument("--end-year", type=int, default=None,
                   help="수집 종료 사업연도(미지정 시 직전 연도)")
    p.add_argument("--years-back", type=int, default=5,
                   help="수집 창(년). 판정 임계가 아니라 수집 범위일 뿐")
    p.add_argument("--fs-div", default="CFS", choices=["CFS", "OFS"],
                   help="CFS=연결, OFS=별도")
    p.add_argument("--fixture", default=None, help="오프라인 재현용 시계열 JSON 경로")
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args(argv)

    # Windows 콘솔(cp949 등)에서도 UTF-8로 출력해 크래시 방지. 파일은 항상 UTF-8로 쓴다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if args.fixture:
        company, series, meta = _load_fixture(args.fixture)
    else:
        if not (args.stock_code or args.corp_code or args.name):
            raise SystemExit(
                "실데이터 모드는 --stock-code / --corp-code / --name 중 하나가 필요합니다. (STOP)")
        company, series, meta = _collect_live(args)

    result = divergence.compute(series)

    out = {
        "schema_version": "screen/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "원값 지표만 담는다. 위험/안전 판정 없음 — 판정은 사람이 한다.",
        "company": company,
        "years_covered_count": result["years_count"],
        "years_covered": [y["year"] for y in result["per_year"]],
        "screen": result,
        **meta,
    }
    out = to_jsonable(out)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ident = company.get("stock_code") or company.get("corp_code") or "fixture"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"screen_{ident}_{stamp}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {out_path}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out_path


if __name__ == "__main__":
    main()
