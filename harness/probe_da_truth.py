"""회사별 D&A 손 정답 확립용 정밀 probe (원천=감사받은 연결주석).
출력(간결):
  - 영업이익(부문정보/성격별에서 확인용)
  - 유형자산 주석: 헤더행(자산분류) + 감가상각비 행 정렬 → 사용권자산 컬럼·ROU 감가상각비 확인
  - 무형자산 주석: 상각 관련 당기 행
  - 성격별 분류 주석: 전 행(당기 D&A)
  - 현금흐름표: 감가상각비·무형자산상각비 가산 행(교차검증)
  - 전 주석에서 ROU 개념코드(DepreciationRightofuseAssets) 당기 셀
  - 라벨에 '사용권'+'감가상각' 동시 등장 행
"""
import re
import sys
import os
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


def rows_of(seg, base_year):
    out = []
    for rm in TR.finditer(seg):
        cells = []
        for tm in TE.finditer(rm.group(1)):
            a = tm.group(1)
            acode = at(a, "ACODE")
            actx = at(a, "ACONTEXT")
            per = actx.split("_", 1)[0] if actx else ""
            cur = per.startswith(f"CFY{base_year}")
            cells.append({"v": txt(tm.group(2)), "acode": acode, "cur": cur, "per": per})
        if cells:
            out.append(cells)
    return out


def short(acode):
    return acode.split("_")[-1] if acode else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stock = sys.argv[1]
    api = os.environ["OPENDART_API_KEY"]
    cache = ROOT / "out" / "_raw"
    client = DartClient(api_key=api, raw_dir=cache, cache_dir=cache, project_root=ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    target = cc.resolve_by_stock(records, stock)
    meta = resolve_latest_business_report(client, target["corp_code"])
    by = meta["base_year"]
    zb, _, _ = client.get_document_zip(meta["rcept_no"])
    _, _, data = select_business_report_body(zb)
    notes = DN._consolidated_notes_slice(data.decode("utf-8", "replace"), "consolidated")
    titles = DN._titles_pos(notes)

    print(f"### {target['corp_name']} {stock} base_year={by}")

    def seg_of(kw_list, exclude=()):
        for i, (p, lab) in enumerate(titles):
            if lab and any(k in lab for k in kw_list) and not any(e in lab for e in exclude):
                nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes)
                return lab, notes[p:nxt]
        return None, None

    # 유형자산: 헤더(자산분류) + 감가상각비 행
    lab, seg = seg_of(["유형자산"])
    if seg:
        print(f"\n[유형자산] {lab}  단위={DN.detect_unit(seg)[0]}")
        for cells in rows_of(seg, by):
            label = cells[0]["v"]
            if label in ("", None):
                continue
            # 헤더행: 값이 대부분 비수치(자산분류명)
            nonnum = sum(1 for c in cells[1:] if c["v"] and not re.match(r"^\(?-?[\d,]+\)?$", c["v"]))
            if nonnum >= 3 and len(cells) > 3:
                print("  헤더> " + " | ".join(c["v"] for c in cells))
            if re.search(r"감가상각", label):
                vals = " | ".join(f"{c['v']}" for c in cells)
                print(f"  감가상각행> {vals}")
                print(f"     (개념코드들: {sorted({short(c['acode']) for c in cells if c['acode']})})")

    # 무형자산: 상각 당기행
    lab, seg = seg_of(["무형자산"])
    if seg:
        print(f"\n[무형자산] {lab}  단위={DN.detect_unit(seg)[0]}")
        for cells in rows_of(seg, by):
            label = cells[0]["v"]
            if re.search(r"상각", label):
                cur = [c["v"] for c in cells if c["cur"] and c["acode"]]
                print(f"  {label}> 당기셀:{cur}  전체:{[c['v'] for c in cells]}")

    # 성격별 분류: 전 당기행
    lab, seg = seg_of(["성격별"])
    if seg:
        print(f"\n[성격별] {lab}  단위={DN.detect_unit(seg)[0]}")
        for cells in rows_of(seg, by):
            label = cells[0]["v"]
            if not label:
                continue
            cur = [(c["v"], short(c["acode"])) for c in cells if c["cur"] and c["acode"]]
            if cur:
                print(f"  {label}> {cur}")
    else:
        print("\n[성격별] 주석 없음 (경로 b 대상)")

    # 현금흐름표: 감가/무형 가산행
    lab, seg = seg_of(["현금흐름"])
    if seg:
        print(f"\n[현금흐름표] {lab}")
        for cells in rows_of(seg, by):
            label = cells[0]["v"]
            if re.search(r"감가상각|상각", label):
                cur = [(c["v"], short(c["acode"])) for c in cells if c["cur"]]
                print(f"  {label}> {cur}")

    # 전 주석 ROU 개념코드 당기셀
    print("\n[ROU 개념코드(DepreciationRightofuseAssets) 당기셀 — 전 주석]")
    found = False
    for cells in rows_of(notes, by):
        for c in cells:
            if "RightofuseAssets" in c["acode"] and c["cur"]:
                print(f"  {cells[0]['v']} :: {c['v']}  [{short(c['acode'])}]")
                found = True
    if not found:
        print("  (없음 — ROU 별도 개념코드 미검출)")

    # 라벨에 사용권+감가상각 동시
    print("\n[라벨 '사용권' 포함 + 감가상각 관련 행]")
    seen = set()
    for cells in rows_of(notes, by):
        label = cells[0]["v"]
        if "사용권" in label and re.search(r"감가상각|상각", label):
            if label in seen:
                continue
            seen.add(label)
            cur = [(c["v"], short(c["acode"])) for c in cells if c["cur"] and c["acode"]]
            print(f"  {label}> {cur}")
    if not seen:
        print("  (없음)")


if __name__ == "__main__":
    main()
