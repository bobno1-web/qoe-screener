# 예시 결과 (데모) · Example results (demo)

키 없이도 볼 수 있게 미리 돌려둔 **실제 출력**입니다. 전부 공개 공시 데이터(OpenDART)에서
산출했습니다(fixture 아님). 브라우저로 바로 열거나, 서버 실행 중에는 `/demo/report_<종목코드>.html` 으로 볼 수 있습니다.

각 회사는 **한 페이지(통합 리포트)** 로 봅니다 — 위에서 **① 이익의 질**(재무제표로 이익 검증),
아래로 스크롤하면 **② 조정 EBITDA**(주석에서 일회성 걷어내기). 상단 고정 네비로 두 축을 오갑니다.

Each company opens as **one integrated report** — **① Earnings quality** (verify the profit from
financials) at the top, scroll down to **② Adjusted EBITDA** (strip one-offs from the notes).

**업종 커버리지(8사): 반도체 · 전자 · 화학 · 항공 · 플랫폼 · 유통 · 의료기기 · 반도체부품.
대기업 6 + 중소형 2 — 규모가 작아 주석 서술이 빈약해도 표 구조 근거로 상단(일회성)을 살린다.**

| 회사 / Company | 업종 | 규모 | 통합 리포트 / Report | (개별) ① 이익의 질 | (개별) ② 조정 EBITDA |
|---|---|---|---|---|---|
| SK하이닉스 / SK Hynix (000660) | 반도체 | 대 | **[report](report_000660.html)** | [quality](quality_000660.html) | [screen](screen_000660.html) |
| 삼성전자 / Samsung (005930) | 전자 | 대 | **[report](report_005930.html)** | [quality](quality_005930.html) | [screen](screen_005930.html) |
| 롯데케미칼 / Lotte Chem. (011170) | 화학 | 대 | **[report](report_011170.html)** | [quality](quality_011170.html) | [screen](screen_011170.html) |
| 대한항공 / Korean Air (003490) | 항공 | 대 | **[report](report_003490.html)** | [quality](quality_003490.html) | [screen](screen_003490.html) |
| 네이버 / NAVER (035420) | 플랫폼 | 대 | **[report](report_035420.html)** | [quality](quality_035420.html) | [screen](screen_035420.html) |
| 이마트 / Emart (139480) | 유통 | 대 | **[report](report_139480.html)** | [quality](quality_139480.html) | [screen](screen_139480.html) |
| 아이센스 / i-SENS (099190) | 의료기기 | 중소 | **[report](report_099190.html)** | [quality](quality_099190.html) | [screen](screen_099190.html) |
| 코미코 / KoMiCo (183300) | 반도체부품 | 중소 | **[report](report_183300.html)** | [quality](quality_183300.html) | [screen](screen_183300.html) |

## 8사 한눈에 — 이익의 질 (기준연도 2025) · Eight companies at a glance

재무제표 숫자로만 결정론 계산. **판정하지 않는다**(임계·색·등급 없음) — 산업마다 정상 범위가 다르다.
숫자·추이만 보고 판정은 사람이. 발생액·EBITDA−OCF 는 규모차가 커 대기업은 **조(兆)**, 중소형은 **억**으로 표기.

| 회사 | 업종 | 규모 | 영업이익률 | 매출채권 회수기간 | 재고일수 | 발생액(영업이익−영업현금) | EBITDA−영업현금 |
|---|---|--|--:|--:|--:|--:|--:|
| SK하이닉스 | 반도체 | 대 | 48.6% | 68.4일 | 135.6일 | −6.2조 | +7.7조 |
| 삼성전자 | 전자 | 대 | 13.1% | 55.9일 | 95.0일 | −41.7조 | +5.2조 |
| 롯데케미칼 | 화학 | 대 | **−5.1%** | 36.8일 | 58.3일 | −1.4조 | −0.2조 |
| 대한항공 | 항공 | 대 | 4.4% | 21.2일 | 24.5일 | −3.0조 | −0.1조 |
| 네이버 | 플랫폼 | 대 | 18.3% | 51.2일 | **해당없음** | −0.9조 | −0.1조 |
| 이마트 | 유통 | 대 | 1.1% | 18.6일 | 38.4일 | −1.0조 | +0.5조 |
| 아이센스 | 의료기기 | 중소 | 2.5% | 77.9일 | 142.9일 | −39억 | +50억 |
| 코미코 | 반도체부품 | 중소 | 18.4% | 50.8일 | 62.3일 | +77억 | **+1,241억** |

*(도구는 숫자를 나란히 둘 뿐, 회사 간 우열이나 인과를 단정하지 않는다. 롯데는 기준연도 영업손실이라
음수 영업이익률, 네이버는 서비스업이라 **매출원가(재고일수 분모)가 없어 "해당없음"** — 억지로 채우지
않는다. Emart 는 유통이라 재고회전이 빠르다. 코미코는 EBITDA(1,623억)가 영업현금(382억)을 크게
웃돌아 **EBITDA−OCF +1,241억** — 이런 괴리가 섹션①이 먼저 보여주는 이익질 일차 신호다.)*

Deterministic from financials, with **no thresholds/colors/grades**. NAVER (a platform) has **no cost
of sales**, so inventory days show "해당없음" (N/A) — the tool leaves it blank rather than fabricating.
Large caps in trillions (조), small/mid caps in hundred-millions (억) due to the size gap.

### 중소형 2사 — 조정 EBITDA (구역 B) · Small/mid caps: adjusted items
표 구조 근거로 살린 상단(일회성). 주석 서술이 빈약해 verbatim 근거가 없어도, 매출원가/판관비 표에
산술 정합하거나 재고평가 개념코드에 실재하면 상단으로 인정한다(계정명 키워드 아님).

- **아이센스**: 재고자산 평가손실(감액) 878,525천 · 대손상각비(환입) 2,383,869천 — 판관비/매출원가 표 근거.
- **코미코**: 재고자산 평가손실환입 666,343천 — 회차마다 표시위치가 흔들렸으나 표 구조가 매출원가 계상을
  확정(안정성 게이트보다 표 구조 우선). 매출채권 대손은 표 산술이 안 돼 **불명 유지**(과함 없음).

각 지표에는 **원문보기**(재무제표 라인 — XBRL 재구성 + 하이라이트)를 답니다. 통합 리포트를 열어
지표·조정 항목을 클릭하면 근거 재무제표·주석 줄을 바로 확인할 수 있습니다.
