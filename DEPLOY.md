# KRX 종가 MCP 서버 배포 가이드

이 폴더는 국내(코스피/코스닥) 종목의 일별 종가를 제공하는 MCP 서버입니다.
`pykrx` 라이브러리로 한국거래소 데이터를 조회하고, `mcp[cli]` 패키지로
원격에서 접속 가능한 MCP 엔드포인트(`/mcp`)를 엽니다.

**중요:** 저(Claude)는 이 서버를 대신 배포하거나, Cowork에 커스텀 커넥터를
자동으로 등록할 수 없습니다. 배포와 커넥터 등록은 아래 순서대로 직접
진행해주셔야 합니다. 코드에 문제가 있으면 오류 메시지를 알려주세요 — 함께
디버깅하겠습니다. (이 코드는 샌드박스 네트워크 제약으로 이 환경에서 직접
실행 테스트는 못 했습니다.)

## 1. 배포하기 (Render.com 기준, 무료 플랜 가능)

Render는 GitHub 저장소만 연결하면 Dockerfile을 자동 인식해 배포해주는
가장 간단한 방법입니다. (Railway, Fly.io 등 다른 PaaS도 비슷한 방식으로
가능합니다.)

1. 이 `krx-mcp-server` 폴더를 GitHub 저장소로 올립니다. **git 명령어 없이,
   웹 화면에서 파일을 끌어다 놓는 방식**으로 할 수 있습니다.
   1. [github.com](https://github.com) 접속 → 계정이 없으면 우측 상단
      **Sign up**으로 무료 가입 (이메일만 있으면 됩니다).
   2. 로그인 후 우측 상단 **+** 버튼 → **New repository** 클릭.
   3. Repository name에 `krx-mcp-server` 입력. Public/Private 아무거나
      선택해도 됩니다. "Add a README file" 등 다른 옵션은 전부 체크 해제한
      채 **Create repository** 클릭.
   4. 저장소가 만들어지면 빈 화면에 "uploading an existing file"이라는
      파란 링크가 보입니다 — 클릭.
   5. 컴퓨터에서 이 `krx-mcp-server` 폴더 안의 4개 파일
      (`server.py`, `requirements.txt`, `Dockerfile`, `DEPLOY.md`)을
      모두 선택해서 업로드 영역으로 끌어다 놓습니다.
      (제가 전달해드린 파일들이 저장된 폴더에서 찾으실 수 있습니다.)
   6. 페이지 하단의 **Commit changes** 버튼 클릭하면 업로드 완료입니다.
2. [render.com](https://render.com) 가입 후 대시보드에서 **New > Web Service**
   선택.
3. 방금 만든 GitHub 저장소를 연결합니다.
4. Render가 `Dockerfile`을 자동으로 인식합니다. Region은 아무 곳이나
   선택해도 되지만, 한국과 가까운 리전(Singapore 등)을 고르면 응답이
   조금 더 빠릅니다.
5. **Instance Type**은 Free로 시작해도 됩니다 (단, 무료 플랜은 일정 시간
   미사용 시 서버가 슬립 상태가 되어 첫 요청이 느릴 수 있습니다).
6. Create Web Service를 누르면 빌드 후 아래 형태의 공개 URL이 생성됩니다:
   ```
   https://krx-mcp-server.onrender.com
   ```
7. 실제 MCP 접속 URL은 여기에 `/mcp`를 붙인 주소입니다:
   ```
   https://krx-mcp-server.onrender.com/mcp
   ```

## 2. 정상 동작 확인

배포가 끝나면 터미널에서 다음처럼 확인해보세요 (200 또는 MCP 초기화
응답이 나오면 정상):

```bash
curl -i https://krx-mcp-server.onrender.com/mcp
```

만약 500 에러나 모듈 관련 오류가 나오면, Render 대시보드의 **Logs** 탭에
찍히는 오류 메시지를 저에게 붙여넣어 주세요.

## 3. Cowork에 커스텀 커넥터로 등록하기 (직접 진행 필요)

1. Claude/Cowork 설정으로 이동합니다.
   - 조직 관리자라면: **Admin 설정 > Connectors**
   - 개인 사용자라면: 설정 내 "도구 연결/커넥터" 메뉴 (Claude가 안내하는
     "커스텀 커넥터 추가" 버튼)
2. 하단의 **"Add custom connector" (커스텀 커넥터 추가)** 클릭.
3. URL란에 배포된 주소를 입력:
   ```
   https://krx-mcp-server.onrender.com/mcp
   ```
4. 이름은 자유롭게 (예: "KRX 종가 서버").
5. **Add / 연결** 클릭.
6. 연결이 완료되면 다시 저에게 알려주세요 — 그때 실제 도구 스키마를
   확인하고, investment-dashboard에 매일 종가를 반영하는 로직을
   이어서 구현하겠습니다.

## 제공되는 도구 (Tools)

| 도구 | 설명 |
|---|---|
| `get_closing_price(ticker, date="")` | 종목 1개의 종가/OHLCV 조회 |
| `get_closing_prices_bulk(tickers, date="")` | 여러 종목을 한 번에 조회 (포트폴리오용) |
| `get_market_cap(ticker, date="")` | 시가총액·상장주식수 조회 |
| `get_latest_business_day()` | 가장 최근 거래일 조회 |

`ticker`는 6자리 종목코드입니다 (예: 삼성전자 `005930`, SK `034730`).
`date`를 비워두면 자동으로 가장 최근 거래일 기준 데이터를 반환합니다.
