"""루프1 채점기: screen 모듈 산수 정합 + 결정론 검증.

정답 출처: harness/fixtures/*.json 의 'expected' 블록(사람이 감사받은 연결재무제표를 손으로 읽고
손으로 누적 계산한 값). out/ 도구출력은 채점 대상이지 정답이 아니다(golden-set-integrity).

검증 항목:
  item1 숫자정합 : 도구 out/ 의 연도별·누적 값 == fixture 'expected'(손 정답).
  item2 계산정합 : divergence.py 를 쓰지 않는 독립 산수 재계산 == 도구 out/.
  item4 결정론   : 같은 fixture 두 번 실행 → generated_at 제외 완전 동일.

판정하지 않고 사실만 보고한다(통과/실패 + 실패 위치).
"""
from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # qoe-normalizer/
RUN = ROOT / "src" / "screen" / "run.py"
FIX_DIR = ROOT / "harness" / "fixtures"


def _dec(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def run_tool(fixture: Path, out_dir: Path) -> dict:
    """도구를 subprocess 로 돌려 out_dir 에 쓴 JSON 을 로드해 반환(도구 코드 직접 import 안 함)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    before = set(out_dir.glob("screen_*.json"))
    r = subprocess.run(
        [sys.executable, str(RUN), "--fixture", str(fixture), "--out-dir", str(out_dir)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise SystemExit(f"도구 실행 실패({fixture.name}):\nSTDOUT{r.stdout}\nSTDERR{r.stderr}")
    after = set(out_dir.glob("screen_*.json"))
    new = sorted(after - before)
    path = new[-1] if new else sorted(after)[-1]
    return json.loads(path.read_text(encoding="utf-8"))


def indep_compute(series: dict) -> dict:
    """divergence.py 를 쓰지 않는 독립 재계산. 순수 Decimal 산수."""
    rows = sorted(series.items(), key=lambda kv: int(kv[0]))
    per = {}
    cum_oi = Decimal(0)
    cum_ocf = Decimal(0)
    ordered = []
    for y, v in rows:
        oi = _dec(v["operating_income"])
        ocf = _dec(v["operating_cash_flow"])
        below = ocf < oi
        per[str(int(y))] = {"accruals": oi - ocf, "ocf_below_oi": below}
        cum_oi += oi
        cum_ocf += ocf
        ordered.append((int(y), below))
    cum_accr = cum_oi - cum_ocf
    ratio = None if cum_oi == 0 else cum_ocf / cum_oi
    dur = 0
    for _, below in reversed(ordered):
        if below:
            dur += 1
        else:
            break
    return {
        "years_count": len(ordered),
        "first_year": ordered[0][0],
        "last_year": ordered[-1][0],
        "per_year": per,
        "cumulative_operating_income": cum_oi,
        "cumulative_operating_cash_flow": cum_ocf,
        "cumulative_accruals": cum_accr,
        "cumulative_divergence_ratio": ratio,
        "consecutive_recent_years_ocf_below_oi": dur,
    }


def _num(x):
    """도구 JSON 값(int 또는 str 소수) -> Decimal. None 유지."""
    if x is None:
        return None
    return _dec(x)


def cmp_item1(tool: dict, fx: dict) -> list[str]:
    """도구 out/ 연도별·누적 == fixture expected(손 정답). 불일치 위치 리스트 반환."""
    fails = []
    scr = tool["screen"]
    exp = fx["expected"]
    series = fx["series"]

    # 스칼라(연도수/최초/최종/누적/지속연수)
    scalar = {
        "years_count": exp["years_count"],
        "first_year": exp["first_year"],
        "last_year": exp["last_year"],
        "cumulative_operating_income": exp["cumulative_operating_income"],
        "cumulative_operating_cash_flow": exp["cumulative_operating_cash_flow"],
        "cumulative_accruals": exp["cumulative_accruals"],
        "consecutive_recent_years_ocf_below_oi": exp["consecutive_recent_years_ocf_below_oi"],
    }
    for k, want in scalar.items():
        got = scr.get(k)
        if _num(got) != _dec(want):
            fails.append(f"[누적/스칼라] {k}: 도구={got} != 손정답={want}")

    # 비율 note (0분모 여부)
    if scr.get("cumulative_divergence_ratio_note") != exp.get("cumulative_divergence_ratio_note"):
        fails.append(f"[비율note] 도구={scr.get('cumulative_divergence_ratio_note')!r} "
                     f"!= 손정답={exp.get('cumulative_divergence_ratio_note')!r}")

    # 비율 값: 손정답 approx 와 근사 일치(6자리) — 산술 exact 는 item2 가 검증
    tool_ratio = scr.get("cumulative_divergence_ratio")
    approx = exp.get("cumulative_divergence_ratio_approx")
    if approx is not None and tool_ratio is not None:
        if abs(_dec(tool_ratio) - _dec(approx)) > Decimal("0.001"):
            fails.append(f"[비율] 도구={tool_ratio} vs 손정답근사={approx} (차이>0.001)")
    elif (approx is None) != (tool_ratio is None):
        fails.append(f"[비율] 도구={tool_ratio!r} vs 손정답근사={approx!r} (None 불일치)")

    # 연도별: 도구가 echo한 OI/OCF == fixture 입력, accruals/ocf_below_oi == 손정답
    tool_py = {str(r["year"]): r for r in scr["per_year"]}
    for y, want in exp["per_year"].items():
        t = tool_py.get(y)
        if t is None:
            fails.append(f"[연도 {y}] 도구 출력에 연도 없음")
            continue
        if _num(t["operating_income"]) != _dec(series[y]["operating_income"]):
            fails.append(f"[연도 {y}] operating_income: 도구={t['operating_income']} "
                         f"!= 입력={series[y]['operating_income']}")
        if _num(t["operating_cash_flow"]) != _dec(series[y]["operating_cash_flow"]):
            fails.append(f"[연도 {y}] operating_cash_flow: 도구={t['operating_cash_flow']} "
                         f"!= 입력={series[y]['operating_cash_flow']}")
        if _num(t["accruals"]) != _dec(want["accruals"]):
            fails.append(f"[연도 {y}] accruals: 도구={t['accruals']} != 손정답={want['accruals']}")
        if bool(t["ocf_below_oi"]) != bool(want["ocf_below_oi"]):
            fails.append(f"[연도 {y}] ocf_below_oi: 도구={t['ocf_below_oi']} "
                         f"!= 손정답={want['ocf_below_oi']}")
    return fails


def cmp_item2(tool: dict, indep: dict) -> list[str]:
    """도구 out/ == 독립 재계산. 공식 정합."""
    fails = []
    scr = tool["screen"]
    for k in ("years_count", "first_year", "last_year",
              "cumulative_operating_income", "cumulative_operating_cash_flow",
              "cumulative_accruals", "consecutive_recent_years_ocf_below_oi"):
        if _num(scr.get(k)) != _dec(indep[k]):
            fails.append(f"[{k}] 도구={scr.get(k)} != 독립재계산={indep[k]}")
    # 비율 exact(도구 문자열 == 독립 Decimal 문자열), None 포함
    tr = scr.get("cumulative_divergence_ratio")
    ir = indep["cumulative_divergence_ratio"]
    if ir is None:
        if tr is not None:
            fails.append(f"[비율] 도구={tr!r} != 독립재계산=None")
    else:
        if tr is None or _dec(tr) != ir:
            fails.append(f"[비율] 도구={tr!r} != 독립재계산={ir}")
    # 연도별 accruals/ocf_below_oi
    tool_py = {str(r["year"]): r for r in scr["per_year"]}
    for y, want in indep["per_year"].items():
        t = tool_py.get(y)
        if t is None:
            fails.append(f"[연도 {y}] 도구 출력에 연도 없음")
            continue
        if _num(t["accruals"]) != want["accruals"]:
            fails.append(f"[연도 {y}] accruals: 도구={t['accruals']} != 독립={want['accruals']}")
        if bool(t["ocf_below_oi"]) != want["ocf_below_oi"]:
            fails.append(f"[연도 {y}] ocf_below_oi: 도구={t['ocf_below_oi']} != 독립={want['ocf_below_oi']}")
    return fails


def _strip_volatile(out: dict) -> dict:
    d = dict(out)
    d.pop("generated_at", None)
    return d


def cmp_item4(a: dict, b: dict) -> list[str]:
    """결정론: generated_at 제외 완전 동일해야."""
    sa = json.dumps(_strip_volatile(a), ensure_ascii=False, sort_keys=True)
    sb = json.dumps(_strip_volatile(b), ensure_ascii=False, sort_keys=True)
    if sa == sb:
        return []
    # 어디가 다른지 대략 위치
    diffs = []
    for k in set(a) | set(b):
        if k == "generated_at":
            continue
        if a.get(k) != b.get(k):
            diffs.append(f"[{k}] run1 != run2")
    return diffs or ["(generated_at 외 직렬화 불일치)"]


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    tmp = ROOT / "harness" / "_grade_tmp"
    fixtures = sorted(FIX_DIR.glob("*.json"))
    print(f"# 루프1 채점  (fixtures={len(fixtures)}개, 정답출처=harness/fixtures/*.json 'expected')\n")

    overall = {1: True, 2: True, 4: True}
    for fx_path in fixtures:
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        name = fx["company"]["corp_name"]
        stock = fx["company"]["stock_code"]
        print(f"## {name} ({stock})  [{fx_path.name}]")

        run1 = run_tool(fx_path, tmp / f"{stock}_a")
        run2 = run_tool(fx_path, tmp / f"{stock}_b")
        indep = indep_compute(fx["series"])

        f1 = cmp_item1(run1, fx)
        f2 = cmp_item2(run1, indep)
        f4 = cmp_item4(run1, run2)

        for item, fails in ((1, f1), (2, f2), (4, f4)):
            if fails:
                overall[item] = False
        print(f"  item1 숫자정합(도구==손정답)  : {'PASS' if not f1 else 'FAIL'}")
        for m in f1:
            print(f"      - {m}")
        print(f"  item2 계산정합(도구==독립재계산): {'PASS' if not f2 else 'FAIL'}")
        for m in f2:
            print(f"      - {m}")
        print(f"  item4 결정론(2회 동일)         : {'PASS' if not f4 else 'FAIL'}")
        for m in f4:
            print(f"      - {m}")
        # 참고: 도구 실제 산출 요약
        scr = run1["screen"]
        print(f"      · 도구 누적OI={scr['cumulative_operating_income']} "
              f"누적OCF={scr['cumulative_operating_cash_flow']} "
              f"누적발생액={scr['cumulative_accruals']} "
              f"비율={scr['cumulative_divergence_ratio']} "
              f"지속연수={scr['consecutive_recent_years_ocf_below_oi']}")
        print()

    print("# 종합 (사실만)")
    print(f"  item1 숫자정합 : {'전부 PASS' if overall[1] else '실패 있음(위 참조)'}")
    print(f"  item2 계산정합 : {'전부 PASS' if overall[2] else '실패 있음(위 참조)'}")
    print(f"  item4 결정론   : {'전부 PASS' if overall[4] else '실패 있음(위 참조)'}")


if __name__ == "__main__":
    main()
