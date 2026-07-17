# harness/review — 사람 검토 작업물 (정답 아님)

골든셋 승인 '전' 단계. 초안 후보를 사람이 O/X 하기 위한 편집용 표가 여기 있다.
**golden/ 아니다** — 아직 정답이 아니고 사람이 편집 중인 작업물이므로 harness/ 에 둔다.

## 파일
- `review_candidates.csv` — **정본(편집 대상)**. '판정' 칸에 회사별로 **유지 / 제외 / 보류** 를 적는다.
  Excel(한국 Windows)에서 열려 UTF-8 BOM. 인용은 원문 그대로(길면 문장 경계까지 자름, ` […]` 표시).
  `id` 열은 건드리지 말 것 — 승인 변환 때 원본 전체 인용을 되찾는 열쇠다.
  `인용검증=⚠원문미확인` 은 그 인용이 원문에서 verbatim 확인 안 됨(표 셀 포맷 등) → 유지 전 원문 확인 권장.
- `review_candidates_preview.md` — 읽기용 미리보기. 편집은 CSV 에서.

## 흐름
1. 표 생성:   `python harness/build_review_table.py`  (golden/drafts/ → 이 표)
2. 사람이 CSV '판정' 칸을 채운다(후보 적은 회사부터 = 표 위에서부터).
3. 정답 기록: `python harness/ratify_from_review.py --commit`  ('유지'만 golden/ratified/ 로)
   - --commit 없이는 dry-run(무엇이 통과할지만 출력, 미기록).
   - '유지'로 정확히 적은 것만 통과. 빈칸·보류·오타·제외는 통과 안 됨.

채점 기준은 오직 golden/ratified/(사람 승인분). 이 폴더의 표는 절대 정답으로 쓰지 않는다.
