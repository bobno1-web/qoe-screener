"""파이프라인 오케스트레이터 (web 껍데기). 검증된 CLI 진입점을 서브프로세스로 순서대로 부른다.

원칙: 재계산 공식·게이트·탐지 로직을 재구현하지 않는다. 회사 해석(이름/종목코드)만 기존
corp_codes 로 사전 수행하고, 나머지는 screen/surface/D&A/normalize CLI 를 그대로 실행한다.
API 키는 인자에 넣지 않고 서브프로세스 env 로만 전달한다(파일·로그 저장 금지, 명령줄 노출 금지).

surface 는 repeat=3 고정 — 사용자 선택 옵션 없음. 회차 비교가 표시위치 안정성 게이트·재현
배지·리콜 합집합의 전제라, 1회로 줄이면 방어가 죽는데 사용자는 그걸 모른 채 결과를 믿게 된다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "out"
PY = sys.executable
SURFACE_REPEAT = 3          # 고정 — 아래 이유로 사용자 옵션 없음
SURFACE_MODEL = "claude-opus-4-8"

STEP_DEFS = [
    ("financials", "재무제표 수집 (DART)"),
    ("surface", "주석 후보 발굴 (Claude · 3회 반복)"),
    ("da", "D&A 추출"),
    ("view", "화면 구성"),
]

# 서브프로세스별 타임아웃(초). surface 만 LLM 이라 넉넉히.
TIMEOUTS = {"financials": 300, "surface": 1200, "da": 300, "view": 300}


def new_job(job_id: str, query: str) -> dict:
    return {
        "id": job_id,
        "status": "resolving",          # resolving → running → done | error
        "input": query,
        "company": None,
        "steps": [
            {"key": k, "label": lb, "status": "pending", "started": None,
             "ended": None, "elapsed": None}
            for k, lb in STEP_DEFS
        ],
        "current": -1,
        "surface": {"done": 0, "total": SURFACE_REPEAT},
        "error": None,
        "result_url": None,
        "stock_code": None,
        "started": time.time(),
        "ended": None,
    }


def _scrub(text: str, secrets) -> str:
    """캡처한 출력에서 혹시라도 키가 섞이면 지운다(방어적). 정상 경로에선 키가 출력되지 않는다."""
    if not text:
        return text
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _child_env(dart_key: str, anthropic_key: str) -> dict:
    env = os.environ.copy()
    env["OPENDART_API_KEY"] = dart_key
    env["ANTHROPIC_API_KEY"] = anthropic_key
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def resolve_company(dart_key: str, query: str) -> dict:
    """회사명 또는 6자리 종목코드 → {corp_code, corp_name, stock_code}. 기존 corp_codes 재사용.

    추측하지 않는다: 0건/복수건이면 corp_codes 가 ResolveError 를 던진다(그대로 전달).
    """
    from src.extract import corp_codes as cc
    from src.extract.dart_client import DartClient

    cache = OUT_DIR / "_raw"
    client = DartClient(api_key=dart_key, raw_dir=cache, cache_dir=cache,
                        project_root=PROJECT_ROOT)
    records = cc.parse_corp_codes(client.get_corpcode_xml())
    q = (query or "").strip()
    if not q:
        raise ValueError("회사명 또는 6자리 종목코드를 입력하세요.")
    if q.isdigit() and len(q) == 6:
        target = cc.resolve_by_stock(records, q)
    else:
        target = cc.resolve_by_name(records, q)
    stock = (target.get("stock_code") or "").strip()
    if not stock:
        raise ValueError(f"'{target.get('corp_name','')}' 는 종목코드가 없어(비상장) 이 도구로 처리할 수 없습니다.")
    return {"corp_code": target["corp_code"], "corp_name": target.get("corp_name", ""),
            "stock_code": stock}


def _read_surface_meta(path: Path) -> dict:
    """저장된 surface JSON 에서 재사용 판정에 필요한 것만 읽는다: 공시 접수번호·주석 길이."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    src = d.get("source") or {}
    meta = src.get("meta") or {}
    return {"rcept_no": meta.get("rcept_no"), "base_year": meta.get("base_year"),
            "report_nm": meta.get("report_nm"), "notes_char_len": src.get("notes_char_len")}


def _dart_client(dart_key: str):
    from src.extract.dart_client import DartClient
    cache = OUT_DIR / "_raw"
    return DartClient(api_key=dart_key, raw_dir=cache, cache_dir=cache,
                      project_root=PROJECT_ROOT)


def latest_filing(dart_key: str, corp_code: str):
    """최신 사업보고서 filing 메타 {rcept_no, base_year, report_nm}. 실패 시 None(가벼운 메타 호출)."""
    try:
        from src.extract.notes_body import resolve_latest_business_report
        return resolve_latest_business_report(_dart_client(dart_key), corp_code)
    except Exception:  # noqa: BLE001  — 신선도 확인 실패는 치명적 아님(재사용 보수 처리)
        return None


def notes_char_len(dart_key: str, corp_code: str) -> int | None:
    """최신 사업보고서 연결주석 길이(자). 비용 추정용. 실패 시 None. 문서 zip 은 캐시된다."""
    try:
        from src.extract.notes_body import (resolve_latest_business_report,
                                            select_business_report_body)
        from src.extract.da_notes import _consolidated_notes_slice
        cl = _dart_client(dart_key)
        meta = resolve_latest_business_report(cl, corp_code)
        zb, _, _ = cl.get_document_zip(meta["rcept_no"])
        _, _, data = select_business_report_body(zb)
        nr = _consolidated_notes_slice(data.decode("utf-8", errors="replace"))
        return len(nr)
    except Exception:  # noqa: BLE001
        return None


def _surface_freshness(existing: Path | None, dart_key: str, corp_code: str) -> dict:
    """저장된 surface 가 최신 공시(rcept_no) 기준인가. 재사용 판정의 근거.

    반환: {has_saved, saved_rcept, latest_rcept, fresh, report_nm, notes_char_len}
    fresh=True  → 같은 공시라 재사용 안전. fresh=False → 새 공시 감지, 다시 분석해야 함.
    최신 rcept 확인 실패(오프라인 등)면 fresh=None → 보수적으로 재사용 허용(사용자가 재사용 택했으니).
    """
    if not existing:
        return {"has_saved": False, "fresh": None}
    sm = _read_surface_meta(existing)
    saved_rcept = sm.get("rcept_no")
    latest = latest_filing(dart_key, corp_code)
    latest_rcept = latest.get("rcept_no") if latest else None
    if latest_rcept is None or saved_rcept is None:
        fresh = None                       # 확인 불가 → 재사용 허용(보수)
    else:
        fresh = (saved_rcept == latest_rcept)
    return {"has_saved": True, "saved_rcept": saved_rcept, "latest_rcept": latest_rcept,
            "fresh": fresh, "report_nm": (latest or {}).get("report_nm") or sm.get("report_nm"),
            "notes_char_len": sm.get("notes_char_len")}


def preview(dart_key: str, query: str) -> dict:
    """실행 전 안내: 회사 해석 + 저장분 재사용 가능 여부 + 예상 비용·시간.

    새 분석도 저장분 재사용도 강제하지 않는다 — 사용자가 알고 고르게 표시만 한다. DART 메타
    호출만 쓰고 LLM 은 안 부른다(공짜). 회사 해석 실패는 그대로 올려 폼에서 오류로 보인다.
    """
    from src.web import cost_estimate
    company = resolve_company(dart_key, query)          # 실패 시 예외 → 호출측이 폼 오류로
    stock = company["stock_code"]
    existing = _latest("surface", stock)
    fr = _surface_freshness(existing, dart_key, company["corp_code"])
    # 주석 길이: 저장분이 있으면 그 길이(공시 간 거의 불변), 없으면 새로 재서 추정(문서 캐시 데움).
    chars = fr.get("notes_char_len")
    if chars is None:
        chars = notes_char_len(dart_key, company["corp_code"])
    est = cost_estimate.estimate(chars)
    reuse_free = bool(fr.get("has_saved") and fr.get("fresh") in (True, None))
    return {"company": company, "freshness": fr, "estimate": est, "reuse_free": reuse_free}


def _run_plain(cmd, env, timeout, secrets):
    """서브프로세스 1개 실행. (ok, tail) 반환. 키는 스크럽."""
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, timeout=timeout,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired:
        return False, f"시간 초과({timeout}s)"
    if proc.returncode != 0:
        tail = _scrub((proc.stderr or proc.stdout or "").strip(), secrets)
        return False, tail[-800:]
    return True, ""


def _run_surface(job, stock, env, secrets):
    """surface 만 Popen + 진행 파일 폴링으로 '3회 중 N회' 갱신. 계산은 discover.main 이 그대로."""
    prog_fd, prog_path = tempfile.mkstemp(prefix="qoe_surface_", suffix=".json")
    os.close(prog_fd)
    err_fd, err_path = tempfile.mkstemp(prefix="qoe_surface_err_", suffix=".txt")
    env = dict(env)
    env["QOE_PROGRESS_FILE"] = prog_path
    cmd = [PY, "-m", "src.web._surface_runner", "--stock-code", stock,
           "--with-notes", "--upper-sweep", "--repeat", str(SURFACE_REPEAT),
           "--model", SURFACE_MODEL]
    # stdout 은 버린다: surface JSON 은 discover.main 이 out/ 에 직접 쓴다(우리가 glob 로 찾음).
    # PIPE 로 받아 안 비우면 큰 최종 JSON 출력에서 파이프 버퍼가 차 자식이 write 에서 교착한다.
    # stderr 는 파일로 흘려 버퍼 한계 없이 받아, 실패 시 꼬리만 읽는다.
    try:
        with os.fdopen(err_fd, "w", encoding="utf-8") as errf:
            proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env,
                                    stdout=subprocess.DEVNULL, stderr=errf)
            deadline = time.time() + TIMEOUTS["surface"]
            while proc.poll() is None:
                time.sleep(1.0)
                try:
                    data = json.loads(Path(prog_path).read_text(encoding="utf-8"))
                    job["surface"]["done"] = int(data.get("done", 0))
                except Exception:
                    pass
                if time.time() > deadline:
                    proc.kill()
                    return False, f"시간 초과({TIMEOUTS['surface']}s)"
        if proc.returncode != 0:
            tail = ""
            try:
                tail = Path(err_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
            return False, _scrub(tail.strip(), secrets)[-800:]
        job["surface"]["done"] = SURFACE_REPEAT
        return True, ""
    finally:
        for p in (prog_path, err_path):
            try:
                os.remove(p)
            except OSError:
                pass


def _latest(kind: str, stock: str):
    cands = sorted(OUT_DIR.glob(f"{kind}_{stock}_*.json"))
    return cands[-1] if cands else None


def _start_step(job, idx):
    job["current"] = idx
    st = job["steps"][idx]
    st["status"] = "running"
    st["started"] = time.time()


def _end_step(job, idx):
    st = job["steps"][idx]
    st["status"] = "done"
    st["ended"] = time.time()
    st["elapsed"] = round(st["ended"] - st["started"], 1)


def _fail(job, idx, msg):
    st = job["steps"][idx]
    st["status"] = "error"
    st["ended"] = time.time()
    if st["started"]:
        st["elapsed"] = round(st["ended"] - st["started"], 1)
    job["status"] = "error"
    job["error"] = msg
    job["ended"] = time.time()


def run(job: dict, dart_key: str, anthropic_key: str, reuse_surface: bool = True) -> None:
    """백그라운드 스레드에서 실행. job 을 제자리 갱신한다. 키는 env 로만 흘러간다.

    reuse_surface: 기존 surface 산출물이 있으면 주석 발굴(LLM 6콜)을 생략하고 재사용한다(기본 True).
    surface 는 회사·주석에만 의존하고 게이팅·화면 변경과 무관하므로, 같은 회사를 다시 볼 때 매번
    LLM 을 재결제할 이유가 없다(비용 절감). 새 발굴이 필요하면 사용자가 재사용을 끈다.
    """
    secrets = [dart_key, anthropic_key]
    try:
        job["status"] = "resolving"
        company = resolve_company(dart_key, job["input"])
        job["company"] = company
        stock = company["stock_code"]
        job["stock_code"] = stock
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = _scrub(str(e), secrets)
        job["ended"] = time.time()
        return

    env = _child_env(dart_key, anthropic_key)
    job["status"] = "running"

    # [1/4] 재무제표 수집 (screen) — 콜드 캐시면 corpCode 마스터 다운로드가 여기서 흡수된다.
    _start_step(job, 0)
    ok, msg = _run_plain([PY, "src/screen/run.py", "--stock-code", stock],
                         env, TIMEOUTS["financials"], secrets)
    if not ok:
        return _fail(job, 0, f"재무제표 수집 실패: {msg}")
    _end_step(job, 0)

    # [2/4] 주석 후보 발굴 (surface, repeat=3 고정) — 기존 산출물이 '같은 공시(rcept_no)' 기준이고
    # 재사용 선택이면 LLM 재실행 생략. 공시가 갱신되면(새 rcept_no) 재사용을 켰어도 자동으로 다시 분석한다
    # (낡은 분석을 무료라고 재활용하지 않는다). rcept 확인 불가(오프라인 등)면 보수적으로 재사용 허용.
    _start_step(job, 1)
    existing = _latest("surface", stock)
    reuse_ok = False
    if reuse_surface and existing:
        fr = _surface_freshness(existing, dart_key, company["corp_code"])
        if fr.get("fresh") in (True, None):
            reuse_ok = True
            job["steps"][1]["reused_rcept"] = fr.get("saved_rcept")
            job["steps"][1]["reused_fresh"] = fr.get("fresh")
        else:
            # 새 공시 감지 → 재분석. 사용자에게 사유를 남긴다(무료 재사용이 아니라 재과금됨).
            job["steps"][1]["restale"] = {"saved": fr.get("saved_rcept"),
                                          "latest": fr.get("latest_rcept")}
    if reuse_ok:
        job["surface"]["done"] = SURFACE_REPEAT
        job["steps"][1]["reused"] = True
        job["steps"][1]["reused_from"] = existing.name
        _end_step(job, 1)
    else:
        ok, msg = _run_surface(job, stock, env, secrets)
        if not ok:
            return _fail(job, 1, f"주석 후보 발굴 실패: {msg}")
        _end_step(job, 1)

    # [3/4] D&A 추출 (ebitda)
    _start_step(job, 2)
    ok, msg = _run_plain([PY, "src/screen/ebitda_run.py", "--stock-code", stock],
                         env, TIMEOUTS["da"], secrets)
    if not ok:
        return _fail(job, 2, f"D&A 추출 실패: {msg}")
    _end_step(job, 2)

    # [4/4] 화면 구성 (build_view → render)
    _start_step(job, 3)
    ok, msg = _run_plain([PY, "src/normalize/build_view.py", "--stock-code", stock],
                         env, TIMEOUTS["view"], secrets)
    if not ok:
        return _fail(job, 3, f"화면 구성(뷰) 실패: {msg}")
    view_path = _latest("screenview", stock)
    if not view_path:
        return _fail(job, 3, "screenview JSON 을 찾지 못했습니다.")
    out_html = OUT_DIR / f"screen_{stock}.html"
    ok, msg = _run_plain([PY, "src/normalize/render.py", str(view_path),
                          "--out", str(out_html)], env, TIMEOUTS["view"], secrets)
    if not ok:
        return _fail(job, 3, f"화면 구성(페이지2 렌더) 실패: {msg}")
    # 페이지 1 — 이익의 질(재무제표 결정론 지표). screen·ebitda 재사용, 페이지 2 로직 무관.
    q_html = OUT_DIR / f"quality_{stock}.html"
    ok, msg = _run_plain([PY, "src/normalize/render_quality.py", "--stock-code", stock,
                          "--out", str(q_html)], env, TIMEOUTS["view"], secrets)
    if not ok:
        return _fail(job, 3, f"화면 구성(페이지1 렌더) 실패: {msg}")
    # 통합 리포트 — 두 페이지를 한 스크롤 문서로(배치만). 페이지 2 HTML/JS 는 srcdoc 로 바이트 그대로 임베드.
    r_html = OUT_DIR / f"report_{stock}.html"
    ok, msg = _run_plain([PY, "src/normalize/render_report.py", "--stock-code", stock,
                          "--quality", str(q_html), "--screen", str(out_html),
                          "--out", str(r_html)], env, TIMEOUTS["view"], secrets)
    if not ok:
        return _fail(job, 3, f"화면 구성(통합 리포트) 실패: {msg}")
    _end_step(job, 3)

    # 랜딩은 통합 리포트 — 한 페이지에서 ① 이익 검증 → ② 조정 EBITDA 를 스크롤·네비로 오간다.
    job["result_url"] = f"/v/report_{stock}.html"
    job["status"] = "done"
    job["ended"] = time.time()
