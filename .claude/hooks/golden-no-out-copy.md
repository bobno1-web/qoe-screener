# hook: golden-no-out-copy — out/ → golden/ 유입 차단

golden-set-integrity 의 "향후 out/→golden/ 복사 차단은 훅으로 자동 강제"를 구현한 게이트.
정답지(golden/)에 도구 산출물(out/)이 섞이면 하네스가 자기 맹점을 못 보므로, 물리적으로 막는다.
**판단 로직 아님** — 파일 기원만 검사한다.

## 무엇을 하나
`harness/check_golden_no_out.py` 가 golden/ 하위를 훑어 out/ 기원 파일을 찾고, 있으면 STOP(exit 1).

세 신호(하나라도 걸리면 위반):
- **(A) 내용 해시**: golden/ 의 파일 sha256 == out/ 의 어떤 파일 → 그대로 복사됨.
- **(B) 파일명**: golden/ 에 `screen_*.json` / `surface_*.json`(도구 산출물 명명).
- **(C) 스키마**: golden/ 의 JSON 최상위 `schema_version` 이 `screen/`·`surface/` 로 시작.

정상 golden 산출물은 `_kind`가 `golden-draft`/`golden-ratified` 라 (B)(C)에 안 걸린다.
README.md 는 양쪽 제외.

## 언제 돌리나 (커밋 전 또는 파이프라인 시작 시)
```
python harness/check_golden_no_out.py    # exit 0 통과 / exit 1 위반(STOP)
```
- 골든셋을 만지는 작업 흐름(초안 생성·승인 변환) 전후에 실행.
- CI/파이프라인 진입점에서 exit code 로 게이트.

## git 초기화 시 자동화 (현재 qoe-normalizer 는 git 저장소 아님)
저장소가 생기면 pre-commit 으로 붙인다:
```
cp .claude/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```
`.claude/hooks/pre-commit` 은 이 검사를 호출하고, 위반 시 커밋을 막는다.

## 검증됨 (2026-07)
- 정상 상태 → OK(exit 0).
- out/screen_*.json 을 golden/ 에 복사 → STOP(exit 1), 내용해시 일치로 적발.
- 제거 후 재검 → OK. 세 신호 모두 동작.

## 경계
정답 승인은 `harness/ratify_from_review.py`(사람이 '유지' 표시한 것만) 로만 golden/ratified/ 에 들어간다.
이 게이트는 그 경로 밖에서 out/ 산출물이 새어드는 사고를 잡는 2차 방어선이다.
