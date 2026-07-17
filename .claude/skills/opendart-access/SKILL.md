---
name: opendart-access
description: OpenDART(한국 전자공시)에서 재무제표·감사보고서·주석 본문을 가져오는 재사용 배관 패턴. corp_code 조회 → 문서/재무제표/주석 수집 → 구조 앵커로 파싱. 이 프로젝트에서 OpenDART를 건드릴 때(screen 수집, surface 감사보고서, 주석 수집 등) 참조한다. 코드는 src/extract/ 에 있고 이 문서는 지도·불변식·함정만 담는다.
---

# opendart-access — OpenDART 접근 배관 (재사용 지도)

세 번째 재사용이라 스킬로 승격. **배관만 재사용하고 판단 로직은 절대 가져오지 않는다**(외부 리포
dartlens/audit-issue-tracker/특수관계자 공통 교훈). 배관 = 수집·파싱·캐시. 판단 = 무엇이 이상/일회성/
특수관계자인지 결정 — 판단은 screen(산수)·surface(LLM)·사람이 하지 이 배관이 하지 않는다.

## 코드 위치 (여기 사본 두지 말 것 — 가리키기만)
- `src/extract/dart_client.py` — urllib 클라이언트. `request_hash`, `DartClient.get_json`,
  `get_corpcode_xml`, `get_document_zip`. 캐시·스냅샷·manifest·하드스톱의 핵심.
- `src/extract/corp_codes.py` — corpCode 마스터 파싱, `resolve_by_stock/name`, `listed_companies`.
- `src/extract/financials.py` — `fnlttSinglAcntAll` 수집, `parse_amount`, 구조적 계정 detect, `collect_series`.
- `src/extract/audit_report.py` — 사업보고서→ZIP→연결감사보고서 엔트리 단일 식별.
- `src/extract/audit_sections.py` — 감사보고서 4문단(USERMARK=B 구조 헤더 슬라이싱).
- `src/extract/notes_body.py` — 사업보고서 본문→재무제표 주석 섹션(TITLE ATOC=Y 앵커 슬라이싱).

## 엔드포인트 (params 는 API 키 제외)
- `corpCode.xml` — 상장사 마스터(ZIP 안 CORPCODE.xml). stock_code(6자리)↔corp_code(8자리) 매핑. induty_code 없음.
- `fnlttSinglAcntAll.json` — 재무제표. `reprt_code=11011`(사업보고서), `fs_div=CFS`(연결)/`OFS`(별도), `bsns_year`.
- `list.json` — 공시목록. `pblntf_detail_ty=A001`(사업보고서). 날짜창은 오늘 기준 역산(특정날짜 하드코딩 금지).
- `document.xml` — 원문 ZIP(`PK` 매직). 엔트리마다 `<DOCUMENT-NAME>` 로 종류 구분.

## 불변식 (깨지면 배관 실패)
- **API 키는 request_hash·캐시키·로그에서 제외.** 스냅샷은 out/_raw/ 에 request_hash 파일명으로, manifest.jsonl 에 기록. 캐시 우선.
- **하드스톱**: status 010/011(인증), 800(점검), 020(레이트리밋) 및 ZIP 이 `PK` 아니면 즉시 StopConditionError. 조용히 넘어가지 않는다.
- **금액은 Decimal 정확산술.** `parse_amount`: 공백·'-'→None(0 아님), 괄호=음수, 콤마 제거. 원값만, 임계·색·라벨 금지.
- **단위 함정**: `fnlttSinglAcntAll` 원시응답은 **원(won)** 단위. 감사받은 표시가 백만원이면 누적/발생액은 ×1,000,000. 비율·지속연수는 단위 불변.
- **계정은 구조로 잡는다**(account_id 우선 → sj_div 내 정확 nm → nm 포함). 계정명 키워드 목록 매칭 아님. sj_div: 영업이익=IS/CIS, 영업활동현금흐름=CF.

## 구조 앵커 (no-hardcoding 예외 = 회계공시 표준 구조; 키워드 매칭 아님)
- **문서 엔트리 선택**: `<DOCUMENT-NAME>` 에 '연결'∧'감사보고서'∧¬'별도'(연결감사보고서) / '사업보고서'∧¬'감사보고서'(본문). 정확히 1개 아니면 STOP.
- **감사보고서 섹션**: `USERMARK="B"` 인 `<p>/<span>` = 진짜 섹션 헤더. 화이트리스트 헤더 사이 슬라이싱. 화이트리스트 밖 하위 소제목은 섹션을 끊지 않는다(안 그러면 본문 잘림).
- **주석 섹션**: `<TITLE ATOC="Y" ENG="Notes to the consolidated/separate financial statements">`(= 연결/별도 재무제표 주석). 경계 = 같은 부모의 다음 형제 최상위 섹션(`AASSOCNOTE="{부모}-N-0"`). **AASSOCNOTE 숫자코드는 판본별로 변함 → ENG/한글 제목으로 앵커, 경계는 형제구조로.**

## 함정
- USERMARK/화이트리스트 규칙은 특정 감사법인·회사로만 검증됨 — 회사 확장 시 재검증(원 리포 명시). 청정 감사의견 회사는 4문단 중 핵심감사사항만 존재하는 게 정상(강조/기타/계속기업 부재는 버그 아님).
- 감사 4문단은 요약 — 실제 일회성 손익은 대개 **재무제표 주석 본문**(notes_body)에 있다. 리콜 필요하면 주석까지 읽힌다(토큰 큼).
- Windows 콘솔(cp949)은 `sys.stdout.reconfigure(encoding="utf-8")` 로 크래시 방지. 파일은 항상 UTF-8.
- 무거운 의존성은 지연 임포트(offline/mock 는 anthropic·bs4 없이도 돈다). opendartreader 는 도입하지 않는다 — urllib DartClient 로 자족.

## 전체 관통 실행 순서 (E2E — 2026-07-11 SK하이닉스 라이브 검증)
한 회사를 screen→surface→D&A→normalize 로 끝까지 돌리는 재사용 절차. 실행 전 키 주입:
`set -a; source ../.env; set +a`(커맨드라인 키 하드코딩은 분류기가 거부 — .env source 만).
1. screen: `python src/screen/run.py --stock-code <6자리> --years-back 5 --fs-div CFS` → 다년 괴리.
2. surface: `python src/surface/discover.py --stock-code <6자리> --with-notes --repeat 3` → 후보(surface/2 두 태그+금액+손익방향), 확률적이라 repeat 로 재현 확인.
3. D&A: `python src/screen/ebitda_run.py --stock-code <6자리>` → EBITDA(경로·출처).
4. normalize: `python src/normalize/build_view.py --stock-code <6자리>`(out/ 최신 3종 자동선택) → screenview JSON, 이어서 `python src/normalize/render.py <screenview> --out out/screen_<6자리>.html`.
검증: `python harness/grade_loopnorm_live.py <6자리>`(토글 재계산·무손실·날조·통합 무결성). Artifact 는 `render.py --fragment`.
캐시된 회사는 재실행이 대부분 캐시 히트(surface 의 LLM 호출만 유료). base_year 는 D&A 가 확정.

## 판단 로직 재사용 금지 (배관과 섞지 말 것)
15개 재무비율·peer median/IQR·Tukey fence(dartlens); 뉴스검색어·네이버뉴스 s3~s6(audit-tracker);
relation_type authority·taxonomy·SUB_CMPN 컬럼롤(특수관계자). 전부 '판단'이라 이 배관 밖.
