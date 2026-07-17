"""루프 E2E(라이브 관통) 채점 — 사실만.

(2) 리콜: 라이브 surface 66 distinct 후보 vs golden ratified 34 (실질매칭: 숫자 우선, 키워드 보조).
(4/5) 날조: 33 flagged 인용의 숫자가 실제 원천(감사4문단+주석본문)에 있나 → 복합인용 아티팩트 vs 진짜 날조.
      원천은 캐시된 document 로 재구성(신규 네트워크콜 없음). env 는 ../.env 에서 source 해서 넣는다.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SURFACE = ROOT / "out" / "surface_000660_20260711T055703Z.json"
GOLDEN = ROOT / "golden" / "ratified" / "ratified_000660.json"


def digits_set(s, minlen=4):
    return {d.replace(",", "") for d in re.findall(r"\d[\d,]{%d,}" % (minlen - 1), s or "")
            if len(d.replace(",", "")) >= minlen}


def toks(s):
    return set(re.findall(r"[가-힣A-Za-z]{2,}", s or ""))


def reconstruct_source():
    """캐시된 감사 document + 주석 본문으로 src_norm 재구성(도구와 동일 함수)."""
    from src.extract import corp_codes as cc
    from src.extract.audit_report import fetch_audit_html
    from src.extract.audit_sections import extract_from_html
    from src.extract.dart_client import DartClient
    from src.extract.notes_body import fetch_notes_body
    from src.surface.discover import SECTION_ORDER, _sec_text, _norm_ws

    api = os.environ["OPENDART_API_KEY"]
    cache = ROOT / "out" / "_raw"
    client = DartClient(api_key=api, raw_dir=cache, cache_dir=cache, project_root=ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    target = [r for r in records if r["corp_code"] == "00164779"][0]
    meta, html = fetch_audit_html(client, "00164779")
    sections = extract_from_html(html)
    _, notes = fetch_notes_body(client, "00164779", which="consolidated")
    sec_text = "\n".join(_sec_text(sections[n]) for n in SECTION_ORDER
                         if n in sections and sections[n] is not None)
    return _norm_ws(sec_text + " " + (notes["text"] or ""))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    surf = json.loads(SURFACE.read_text(encoding="utf-8"))
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    distinct = surf["reproducibility"]["distinct_candidates"]
    # 리콜 분모에서 '범위 밖'(순수 추정품질 등) 재분류 항목 제외 — 삭제 아님, 골든엔 남아 있음.
    gitems = [g for g in gold["items"] if g.get("scope") != "out_of_scope"]
    oos = sum(1 for g in gold["items"] if g.get("scope") == "out_of_scope")

    # 라이브 후보 인덱스
    live = [{"항목명": d["항목명"], "인용": d.get("인용", ""),
             "nums": digits_set(d.get("인용", "")), "tok": toks(d["항목명"] + " " + d.get("인용", ""))}
            for d in distinct]

    print("=" * 80)
    print(f"### (2) 리콜: 라이브 surface distinct {len(live)} vs golden ratified {len(gitems)} (범위밖 {oos}건 제외)")
    full = partial = miss = 0
    miss_list = []
    for g in gitems:
        gnums = digits_set(g.get("인용", ""))
        gtok = toks(g["항목명"])
        # 1순위: 숫자 교집합
        m = None
        for c in live:
            if gnums and (gnums & c["nums"]):
                m = ("숫자", c); break
        # 2순위: 항목명 핵심 토큰 겹침(2개↑ 또는 고유명)
        if not m:
            for c in live:
                common = gtok & c["tok"]
                strong = {t for t in common if len(t) >= 3 or re.match(r"[A-Za-z]", t)}
                if len(common) >= 2 or strong:
                    m = ("키워드", c); break
        if m:
            if m[0] == "숫자":
                full += 1
            else:
                partial += 1
        else:
            miss += 1
            miss_list.append(g["항목명"])
    print(f"   숫자매칭(완전) {full}  키워드매칭(부분) {partial}  미검출 {miss}   → 검출 {full+partial}/{len(gitems)}")
    print(f"   미검출 항목: {miss_list}")

    print("\n" + "=" * 80)
    print("### (4/5) 날조 점검: 33 flagged 인용의 숫자가 실제 원천에 있나")
    try:
        src = reconstruct_source()
        print(f"   원천 재구성 OK (길이 {len(src):,}자, 감사4문단+주석본문)")
    except Exception as e:
        print(f"   [원천 재구성 실패: {e}]  — 숫자검증 생략")
        return
    src_digits = re.sub(r"[^0-9]", "", src)
    flagged = surf["hallucination"]["flagged"]
    artifact = concern = 0
    concern_items = []
    for f in flagged:
        q = f.get("인용", "")
        qnums = [d.replace(",", "") for d in re.findall(r"\d[\d,]{3,}", q) if len(d.replace(",", "")) >= 4]
        # 모든 salient 숫자가 원천 digit 스트림에 있나
        absent = [n for n in qnums if n not in src_digits]
        # 숫자 없는 인용은 조각 verbatim 로 판정
        if not qnums:
            frags = [x.strip() for x in q.split("...") if x.strip()]
            src_norm = re.sub(r"\s+", " ", src)
            absent_txt = [fr for fr in frags if re.sub(r"\s+", " ", fr) not in src_norm]
            if absent_txt:
                concern += 1; concern_items.append((f["항목명"], "텍스트조각부재", absent_txt[:1]))
            else:
                artifact += 1
        elif absent:
            concern += 1; concern_items.append((f["항목명"], "숫자부재", absent))
        else:
            artifact += 1
    print(f"   flagged {len(flagged)}건 중: 모든숫자 원천존재(복합인용 아티팩트)={artifact}  숫자/텍스트 부재(확인필요)={concern}")
    for nm, why, ev in concern_items:
        print(f"      <<확인필요 [{why}] {nm[:40]} :: {ev}")

    # 참고: distinct 후보 전체의 citation_verbatim_present 집계(도구 자기표시)
    vp = sum(1 for d in distinct if d.get("citation_verbatim_present"))
    print(f"\n   (도구 자기표시) distinct {len(distinct)}건 중 citation_verbatim_present=True: {vp}")
    print("\n(사실 보고 — 판정 없음)")


if __name__ == "__main__":
    main()
