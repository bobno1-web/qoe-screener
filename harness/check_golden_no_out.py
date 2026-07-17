"""[3] out -> golden 유입 차단 게이트 (golden-set-integrity 물리 강제).

golden/ 하위에 'out/ 기원' 파일이 들어왔는지 검사해, 발견되면 STOP(exit 1). 커밋 전 또는
파이프라인 시작 때 돌린다. 판단 없음 — 정답지에 도구 산출물이 섞이는 사고만 막는다.

세 가지 신호로 잡는다(하나라도 걸리면 위반):
  (A) 내용 해시 일치 : golden/ 의 파일이 out/ 의 어떤 파일과 sha256 동일(= 그대로 복사).
  (B) 파일명 시그니처: golden/ 에 screen_*.json / surface_*.json (도구 산출물 명명).
  (C) 스키마 시그니처: golden/ 의 JSON 최상위 schema_version 이 'screen/'·'surface/' 로 시작.

정상 golden 산출물은 _kind 가 'golden-'(draft/ratified) 이라 (B)(C)에 안 걸린다.
README.md 는 양쪽에서 제외(설명 문서). 문서화: .claude/hooks/golden-no-out-copy.md.

사용:
  python harness/check_golden_no_out.py          # 위반 있으면 exit 1
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "out"
GOLDEN_DIR = PROJECT_ROOT / "golden"

_NAME_SIG = re.compile(r"^(screen|surface)_.*\.json$", re.I)
_SCHEMA_SIG = re.compile(r"^(screen|surface)/", re.I)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _files(root: Path):
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file() and p.name != "README.md"]


def _schema_version(path: Path):
    if path.suffix.lower() != ".json":
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return d.get("schema_version") if isinstance(d, dict) else None


def scan():
    out_hashes = {}
    for p in _files(OUT_DIR):
        out_hashes.setdefault(_sha256(p), p)

    violations = []
    for g in _files(GOLDEN_DIR):
        h = _sha256(g)
        if h in out_hashes:
            violations.append((g, f"내용해시 일치 out/{out_hashes[h].relative_to(OUT_DIR)} (그대로 복사)"))
            continue
        if _NAME_SIG.match(g.name):
            violations.append((g, "파일명이 도구 산출물 형식(screen_*/surface_*)"))
            continue
        sv = _schema_version(g)
        if sv and _SCHEMA_SIG.match(str(sv)):
            violations.append((g, f"schema_version='{sv}' = 도구 산출물 스키마"))
    return violations, len(out_hashes)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    violations, n_out = scan()
    n_golden = len(_files(GOLDEN_DIR))
    print(f"# golden-no-out 게이트  (golden 파일 {n_golden}개 검사, out 지문 {n_out}개)")
    if not violations:
        print("OK: golden/ 에 out/ 기원 파일 없음. (통과)")
        return 0
    print(f"STOP: golden/ 에 out/ 기원으로 의심되는 파일 {len(violations)}개 — golden-set-integrity 위반.")
    for path, why in violations:
        print(f"  - {path.relative_to(PROJECT_ROOT)} : {why}")
    print("\n정답지에는 도구 산출물이 들어갈 수 없습니다. 해당 파일을 golden/ 에서 제거하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
