# KR Premarket Terminal — 장전 브리핑 터미널

한국 주식 장 시작 전, 전일 시장을 한 화면에 보여주는 금융 터미널입니다.
매일 아침 수집기가 `snapshot.json` 을 만들고, 정적 화면(`index.html`)이 그걸 읽어 표시합니다.
오늘 일정·야간선물은 화면에서 **Investing.com 위젯**으로 실시간 표시됩니다.

## 구성
```
collect.py        # 데이터 수집 → snapshot.json 생성 (approach a: 무료 라이브러리)
index.html        # 터미널 화면
requirements.txt  # 파이썬 의존성
config/
  earnings.json     # (선택) 실적/컨센서스 — 직접 큐레이션
  news_feeds.json   # (선택) 뉴스 RSS 목록
```

## 1) 설치
```bash
pip install -r requirements.txt
```

## 2) 수집 실행
```bash
python collect.py                   # 최근 거래일 기준 snapshot.json 생성
python collect.py --date 20260602   # 특정 거래일로 테스트
```
실행하면 항목별 `[OK]/[FAIL]` 가 출력됩니다. 실패한 항목은 화면에서 "데이터 없음" 으로 표시됩니다.

## 3) Investing.com 위젯 연결 (오늘 일정 · 야간선물)
`index.html` 상단의 두 줄만 수정하면 됩니다.
- `INVESTING_CALENDAR_URL` : 경제캘린더. 기본값으로 바로 동작하며,
  https://www.investing.com/webmaster-tools/economic-calendar 에서 국가(대한민국)·시간대(GMT+9)·언어를 골라 재생성하면 더 정확합니다.
- `INVESTING_NIGHT_URL` : 야간선물. https://www.investing.com/webmaster-tools/ → "Custom Real-Time Chart"
  에서 `KOSPI 200 Futures` 를 선택해 생성한 iframe 의 src 를 붙여넣으세요. (비워두면 안내문이 표시됩니다.)

## 4) 화면 확인
```bash
python -m http.server 8000   # index.html 과 snapshot.json 같은 폴더에서 실행
# 브라우저: http://localhost:8000
```
`snapshot.json` 이 없으면 화면은 **샘플 모드**(상단 노란 배너)로 뜹니다.

## 데이터 출처 (approach a — 무료)
| 항목 | 출처 | 상태 |
|---|---|---|
| 코스피·코스닥 지수/차트 | pykrx | 수집 |
| 수급(외인·기관·개인) | pykrx | 수집 |
| 전일 급등/급락/거래량 | pykrx | 수집 |
| 업종 히트맵 | pykrx (KRX 업종지수) | 수집 |
| 미국지수·SOX·금리·달러·WTI·환율·EWY | yfinance | 수집 |
| 뉴스 | RSS | 수집 |
| 오늘 일정 | Investing.com 위젯 | 화면 임베드(라이브) |
| 야간선물 | Investing.com 위젯 | 화면 임베드(라이브) |
| 실적/컨센서스 | config/earnings.json | 직접 입력(선택) |
| VKOSPI | — | 무료 불가 → 데이터 없음 |

> 못 가져오는 항목은 가짜로 채우지 않고 "데이터 없음" 으로 표시됩니다.

## 참고
- pykrx 함수 시그니처(예: `get_market_trading_value_by_investor`)는 버전에 따라 다를 수 있습니다.
  `[FAIL] 수급 ...` 가 뜨면 해당 함수만 버전에 맞게 수정하세요.
- 업종 코드 / 거래대금 하한선 / 뉴스 RSS 는 `collect.py` 상단 상수와 config 에서 조정 가능합니다.
- 인베스팅닷컴은 스크래핑(investpy 등)이 Cloudflare 로 막혀 있어, 데이터는 위젯 임베드로 가져옵니다.

## 다음 단계
매일 08:00 자동 실행 + 정적 배포(GitHub Actions + Pages) 설정을 `.github/workflows/update.yml` 로 추가합니다.
