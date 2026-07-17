"""surface 서브프로세스 래퍼 — 진행 표시(3회 중 N회)만 얹고 계산은 discover.main 에 그대로 위임.

왜 래퍼가 필요한가: discover() 는 for i in range(repeat) 로 run_once 를 도는데 회차별
진행을 밖으로 내보내지 않는다. 화면에 "3회 중 N회"를 보여주려면 회차 완료를 관찰해야 한다.
그렇다고 discover.py(파이프라인) 를 고치면 안 된다(로직 불변 원칙). 그래서 web 계층인 여기서
모듈 전역 run_once 를 '관찰 전용'으로 감싼다 — 원본을 그대로 호출하고 그 반환값을 그대로 돌려주되,
회차가 끝날 때마다 진행 파일(QOE_PROGRESS_FILE)에 done 수만 적는다. 계산·출력·surface JSON 은
전부 discover.main 이 원래대로 만든다(byte 동일). 이 파일은 web 껍데기이지 파이프라인이 아니다.

호출: python -m src.web._surface_runner --stock-code XXXXXX --with-notes --repeat 3 --model claude-opus-4-8
      진행 파일 경로는 환경변수 QOE_PROGRESS_FILE 로 전달(없으면 진행 기록만 생략, 실행은 동일).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.surface import discover as D  # noqa: E402


def _install_progress_probe(progress_path: str, repeat: int) -> None:
    """discover.run_once 를 관찰 전용으로 감싼다. 원본 호출·반환값 불변, 진행 수만 기록."""
    orig = D.run_once

    def observed(idx, *args, **kwargs):
        result = orig(idx, *args, **kwargs)  # 계산은 원본이 그대로
        try:
            Path(progress_path).write_text(
                json.dumps({"done": idx + 1, "total": repeat}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass  # 진행 기록 실패가 파이프라인을 막지 않는다
        return result

    D.run_once = observed


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    progress_path = os.environ.get("QOE_PROGRESS_FILE")
    # --repeat 값 파싱(진행 total 표시용). 못 찾으면 discover 기본값 3.
    repeat = 3
    if "--repeat" in argv:
        try:
            repeat = int(argv[argv.index("--repeat") + 1])
        except (ValueError, IndexError):
            repeat = 3
    if progress_path:
        _install_progress_probe(progress_path, repeat)
    # 계산·직렬화·파일쓰기는 전부 파이프라인(discover.main)이 원래대로 수행한다.
    return D.main(argv)


if __name__ == "__main__":
    main()
