후보를 토글해 정상화 EBITDA 를 재계산하는 화면 단계. 파싱·발굴·판정 로직을 넣지 않는다 —
앞 루프(ebitda·surface·screen) 산출물을 읽어 화면에 원값·출처로 보여줄 뿐이다. LLM 없음.
(세금 정합을 포함한 순이익 레벨 정상화는 EBITDA 기준선 범위 밖 — 별도 과제.)

`build_view.py` — 회사별 최신 ebitda·surface·screen out/ JSON → 화면용 단일 JSON(screenview/1).
결정론적. surface 의 두 태그(표시위치·정상화성격)·손익방향·금액을 **그대로 읽고 코드가 재판정하지
않는다**(no-keyword-heuristics·no-hardcoding). 금액은 surface 의 '금액표시'가 인용에 실제로 있는
숫자인지만 검증(citations-mandatory). 정상화성격=조정대상 → 구역 B(토글), 참고·불명 → 구역 C.
D&A 를 개별주석 합산 경로(b)로 구한 회사면 운용리스 배너(구조 신호로만, 회사명 아님 —
docs/limitations.md §1).

`render.py` — screenview JSON → 단일 HTML(프레임워크 없음, 데이터 인라인, 더블클릭 실행).
구역 A(EBITDA 브릿지+원문보기), B(조정대상 체크박스 토글→재계산: 이익 차감·비용 가산, 부호는
screenview 의 sign 그대로), C(참고, 토글 없음 + 사용자 조절 금액 슬라이더). 원문보기는 상·하단
공통(인용+주석위치, D&A 는 개념코드·기간까지). 상태는 페이지 내 변수만 — localStorage/
sessionStorage 미사용. 임계·색으로 위험/안전 딱지 붙이지 않는다.
