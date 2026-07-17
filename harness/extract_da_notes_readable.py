"""독립 검증용: 감사받은 연결주석 원문에서 D&A 관련 주석 표를 '사람이 읽는' 형태로 뽑는다.
도구 출력(out/)을 안 본다 — 원천(사업보고서 주석 본문)에서 직접 렌더한다.

출력(회사별 .txt):
  - base_year, 주석 제목 목록
  - 관심 주석(성격별 분류/유형자산/무형자산/리스·사용권/투자부동산/현금흐름표/부문정보/일반관리비 등)
    표를 행 단위로: [단위] 라벨 | 셀값 {ACODE·기간} | ...
  - 라벨에 '감가상각' 또는 '상각'이 든 모든 행(개념코드 없어도) — 은행 등 업종특수 D&A 누락 점검용.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import os

from src.extract import corp_codes as cc  # noqa: E402
from src.extract.dart_client import DartClient  # noqa: E402
from src.extract import da_notes as DN  # noqa: E402
from src.extract.notes_body import (  # noqa: E402
    resolve_latest_business_report, select_business_report_body,
)

OUT = Path(r"C:\Users\gmg97\AppData\Local\Temp\claude\C--Users-gmg97-Desktop-25-26--QOE\7b754a0e-2eb0-489f-952d-f7b121e63343\scratchpad")

TE = re.compile(r"<TE\b([^>]*)>(.*?)</TE>", re.S | re.I)
TR = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.S | re.I)
ATTR = lambda a, k: (re.search(rf'{k}="([^"]*)"', a, re.I) or None)  # noqa: E731

# 관심 주석 제목 키워드
KEYS = ["성격별", "유형자산", "무형자산", "리스", "사용권", "투자부동산",
        "현금흐름", "부문", "판매비와 관리비", "일반관리비", "영업비용", "감가상각"]


def txt(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def render_rows(segment, base_year):
    lines = []
    for rm in TR.finditer(segment):
        cells = []
        for tm in TE.finditer(rm.group(1)):
            a = tm.group(1)
            val = txt(tm.group(2))
            acode_m = ATTR(a, "ACODE")
            actx_m = ATTR(a, "ACONTEXT")
            acode = acode_m.group(1) if acode_m else ""
            actx = actx_m.group(1) if actx_m else ""
            per = actx.split("_", 1)[0] if actx else ""
            tag = ""
            if acode:
                cur = "★당기" if per.startswith(f"CFY{base_year}") else ("전기" if "PFY" in per else per)
                tag = f" {{{acode.split('_')[-1]}·{cur}}}"
            cells.append(val + tag)
        if cells and any(c.strip() for c in cells):
            lines.append(" | ".join(cells))
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stock = sys.argv[1]
    api = os.environ["OPENDART_API_KEY"]
    cache = ROOT / "out" / "_raw"
    client = DartClient(api_key=api, raw_dir=cache, cache_dir=cache, project_root=ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    target = cc.resolve_by_stock(records, stock)
    corp = target["corp_code"]
    meta = resolve_latest_business_report(client, corp)
    base_year = meta["base_year"]
    zip_bytes, _, _ = client.get_document_zip(meta["rcept_no"])
    entry, doc_name, data = select_business_report_body(zip_bytes)
    body = data.decode("utf-8", errors="replace")
    notes = DN._consolidated_notes_slice(body, "consolidated")

    titles = DN._titles_pos(notes)
    out = [f"# {target['corp_name']} {stock}  base_year={base_year}  rcept={meta['rcept_no']}",
           f"# notes_len={len(notes)}  doc={doc_name}",
           "\n## 주석 제목 목록"]
    for pos, lab in titles:
        if lab:
            out.append(f"  @{pos} {lab}")

    # 관심 주석 세그먼트
    for i, (pos, lab) in enumerate(titles):
        if not lab or not any(k in lab for k in KEYS):
            continue
        nxt = titles[i + 1][0] if i + 1 < len(titles) else len(notes)
        seg = notes[pos:nxt]
        ustr, _ = DN.detect_unit(seg)
        rows = render_rows(seg, base_year)
        if not rows:
            continue
        out.append(f"\n{'='*80}\n## [{lab}]  단위={ustr}  (@{pos}, {len(seg)}자)")
        for r in rows[:120]:
            out.append("  " + r)

    # 라벨에 감가상각/상각 든 모든 행(개념코드 유무 무관) — 누락 점검
    out.append(f"\n{'='*80}\n## [라벨 스캔] '감가상각' 또는 '상각' 포함 행 (당기 개념코드 태그 표시)")
    seen = set()
    for rm in TR.finditer(notes):
        cells = []
        has_da_label = False
        for tm in TE.finditer(rm.group(1)):
            a = tm.group(1)
            val = txt(tm.group(2))
            if re.search(r"감가상각|상각비|상각", val):
                has_da_label = True
            acode_m = ATTR(a, "ACODE")
            actx_m = ATTR(a, "ACONTEXT")
            acode = acode_m.group(1) if acode_m else ""
            actx = actx_m.group(1) if actx_m else ""
            per = actx.split("_", 1)[0] if actx else ""
            tag = ""
            if acode:
                cur = "★당기" if per.startswith(f"CFY{base_year}") else ("전기" if "PFY" in per else per)
                tag = f" {{{acode.split('_')[-1]}·{cur}}}"
            cells.append(val + tag)
        if has_da_label and cells:
            note = DN._note_of(titles, rm.start())
            key = (note, tuple(cells))
            if key in seen:
                continue
            seen.add(key)
            out.append(f"  [{note}] " + " | ".join(cells))

    p = OUT / f"danotes_{stock}.txt"
    p.write_text("\n".join(out), encoding="utf-8")
    print(f"[written] {p}  ({len(out)} lines)")


if __name__ == "__main__":
    main()
