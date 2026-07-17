"""D&A 채점 최종 검증:
 (1) 출처 진위: 각 도구 line 의 원문값이 인용 주석 세그먼트에 verbatim 존재하나(날조 점검).
 (2) 신한 완전성: 유형/무형/ROU/투자부동산 밖에 당기 D&A 개념코드 셀 또는 '상각/운용리스' 라벨 행이
     있는데 도구가 빠뜨렸나(은행 업종특수 D&A 누락 점검).
 (3) A/B/C notice: 개별주석(C) 줄에 안내문이 붙었나.
 (4) KA 유형자산 헤더: 사용권자산 컬럼 확인.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.extract import corp_codes as cc  # noqa: E402
from src.extract.dart_client import DartClient  # noqa: E402
from src.extract import da_notes as DN  # noqa: E402
from src.extract.notes_body import resolve_latest_business_report, select_business_report_body  # noqa: E402

TE = re.compile(r"<TE\b([^>]*)>(.*?)</TE>", re.S | re.I)
TR = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.S | re.I)


def at(a, k):
    m = re.search(rf'{k}="([^"]*)"', a, re.I)
    return m.group(1) if m else ""


def txt(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def notes_for(stock):
    api = os.environ["OPENDART_API_KEY"]
    cache = ROOT / "out" / "_raw"
    client = DartClient(api_key=api, raw_dir=cache, cache_dir=cache, project_root=ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    t = cc.resolve_by_stock(records, stock)
    meta = resolve_latest_business_report(client, t["corp_code"])
    zb, _, _ = client.get_document_zip(meta["rcept_no"])
    _, _, data = select_business_report_body(zb)
    notes = DN._consolidated_notes_slice(data.decode("utf-8", "replace"), "consolidated")
    return notes, DN._titles_pos(notes), meta["base_year"], t["corp_name"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for stock in ["003490", "011170", "000660", "055550"]:
        notes, titles, by, name = notes_for(stock)
        f = sorted(glob.glob(str(ROOT / "out" / "_loopda" / f"ebitda_{stock}_*.json")))[-1]
        d = json.load(open(f, encoding="utf-8"))
        print(f"\n{'='*72}\n### {name} {stock}")

        # (1)+(3) 출처 진위 + notice
        print("-- 출처 진위(원문값 verbatim in 인용주석) + notice --")
        for ln in d["da"]["lines"]:
            src = ln.get("source")
            if not src:
                print(f"   [{ln['kind'][:30]}] source=None (present={ln['value_won']})")
                continue
            note = src["주석위치"]
            raw = src["원문값"]
            seg = DN._note_segment(notes, titles, note)
            note_exists = bool(seg)
            val_in = raw in seg if seg else False
            noticed = "notice✓" if ln.get("notice") else "notice—"
            flag = "" if (note_exists and val_in) else "  <<< 확인필요"
            print(f"   [{ln['inclusion']}/{'added' if ln['added'] else 'noadd'}/{noticed}] "
                  f"{ln['kind'][:26]:26} 원문값={raw:>16} @{note[:20]:20} note존재={note_exists} 값존재={val_in}{flag}")

        # (2) 완전성: 전 주석 당기 D&A 개념코드 셀을 주석·개념코드별로 집계
        cells = DN._da_cells(notes, titles, by)
        from collections import defaultdict
        agg = defaultdict(list)
        for c in cells:
            agg[(c["note"], c["acode"].split("_")[-1])].append(abs(c["value"]) if c["value"] is not None else 0)
        print("-- 전 주석 당기 D&A 개념코드 셀(주석·코드별 최대=합계행 후보) --")
        for (note, code), vals in sorted(agg.items(), key=lambda x: -max(x[1])):
            print(f"   {max(vals):>16,}  [{code}]  @{note[:34]}")

        # 라벨 스캔: '상각' 또는 '운용리스' 든 행 중 개념코드 없는(태그 안 된) 것 — 누락 위험
        print("-- 라벨 '상각/운용리스' 인데 D&A 개념코드 태그 없는 당기 관련 행(누락위험) --")
        seen = set()
        for rm in TR.finditer(notes):
            cellz = []
            has_lbl = False
            has_da_code = False
            for tm in TE.finditer(rm.group(1)):
                a = tm.group(1)
                v = txt(tm.group(2))
                if re.search(r"상각|운용리스", v):
                    has_lbl = True
                if DN._DA_CONCEPT_RE.search(at(a, "ACODE") or ""):
                    has_da_code = True
                cellz.append(v)
            if has_lbl and not has_da_code and cellz:
                note = DN._note_of(titles, rm.start())
                key = (note, cellz[0])
                if key in seen or not cellz[0]:
                    continue
                seen.add(key)
                if re.search(r"운용리스|리스자산|감가상각비|무형자산상각|상각비", cellz[0]):
                    print(f"     [{note[:24]}] {cellz[0][:40]} :: {[c for c in cellz[1:] if c][:5]}")

        # (4) KA 유형자산 헤더행
        if stock == "003490":
            seg = DN._note_segment(notes, titles, "15. 유형자산 (연결)")
            print("-- KA 유형자산 헤더행(사용권자산 컬럼 확인) --")
            for rm in TR.finditer(seg):
                cs = [txt(tm.group(2)) for tm in TE.finditer(rm.group(1))]
                if any("사용권" in c for c in cs) and any("항공기" in c or "토지" in c or "건물" in c for c in cs):
                    print("     헤더> " + " | ".join(cs))
                    break


if __name__ == "__main__":
    main()
