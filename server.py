"""
KRX 종가 MCP 서버
------------------
pykrx 라이브러리를 이용해 국내(코스피/코스닥) 종목의 일별 종가·시가총액 정보를
MCP(Model Context Protocol) 도구로 제공하는 원격 서버입니다.

배포 후 이 서버의 공개 URL(예: https://your-app.onrender.com/mcp)을
Claude/Cowork의 "커스텀 커넥터"로 등록하면, 매일 종가 기반으로
investment-dashboard 같은 아티팩트를 자동 갱신하는 데 사용할 수 있습니다.

로컬 실행:
    pip install -r requirements.txt
    python server.py
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pykrx import stock

logging.basicConfig(level=logging.INFO)

# MCP SDK는 DNS 리바인딩 공격을 막기 위해 기본적으로 Host 헤더를 검사하며,
# 기본 허용 목록(allowed_hosts / allowed_origins)이 비어 있어 배포 도메인
# (onrender.com 등)이 전부 421로 막힙니다. 실제 필드명은
# enable_dns_rebinding_protection이며, 이를 False로 두면 해당 검사 자체를
# 건너뜁니다. 이것이 SDK가 제공하는 정식 비활성화 경로입니다.
# (이전에 시도했던 검증 메서드 몽키패치는 반환값 규약을 잘못 파악해
# "'bool' object is not callable" 500 에러를 유발했으므로 제거했습니다.)
mcp = FastMCP("krx-price-server")
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)


def _latest_business_day(base: Optional[str] = None) -> str:
    """기준일(base, YYYYMMDD) 또는 오늘 기준으로 가장 최근 거래일(YYYYMMDD)을 찾는다.
    삼성전자(005930) 종가 데이터가 존재하는 가장 가까운 과거일을 거래일로 판단한다."""
    d = datetime.strptime(base, "%Y%m%d") if base else datetime.now()
    for _ in range(10):
        ymd = d.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(ymd, ymd, "005930")
            if df is not None and not df.empty:
                return ymd
        except Exception:
            pass
        d -= timedelta(days=1)
    raise RuntimeError("최근 거래일을 찾지 못했습니다.")


@mcp.tool()
def get_closing_price(ticker: str, date: str = "") -> dict:
    """지정한 종목코드의 일별 종가 정보를 반환합니다.

    Args:
        ticker: 6자리 종목코드 (예: "005930" 삼성전자, "034730" SK)
        date: 조회일 YYYYMMDD 형식. 비워두면 가장 최근 거래일 기준으로 조회합니다.

    Returns:
        종목명, 조회일, 시가/고가/저가/종가/거래량/등락률(%)을 담은 dict.
        해당일에 거래 데이터가 없으면 error 필드가 채워집니다(휴장일 등).
    """
    target = date or _latest_business_day()
    try:
        df = stock.get_market_ohlcv(target, target, ticker)
    except Exception as e:
        return {"ticker": ticker, "date": target, "error": f"조회 실패: {e}"}

    if df is None or df.empty:
        return {"ticker": ticker, "date": target, "error": "해당일 데이터 없음(휴장일이거나 상장 전일 수 있음)"}

    row = df.iloc[0]
    try:
        name = stock.get_market_ticker_name(ticker)
    except Exception:
        name = ""

    return {
        "ticker": ticker,
        "name": name,
        "date": target,
        "open": int(row["시가"]),
        "high": int(row["고가"]),
        "low": int(row["저가"]),
        "close": int(row["종가"]),
        "volume": int(row["거래량"]),
        "change_pct": float(row["등락률"]),
    }


@mcp.tool()
def get_closing_prices_bulk(tickers: List[str], date: str = "") -> List[dict]:
    """여러 종목코드의 일별 종가 정보를 한 번에 반환합니다.
    포트폴리오 전체(예: 보유 국내 종목 13개)의 종가를 한 번의 호출로 가져올 때 사용하세요.

    Args:
        tickers: 6자리 종목코드 리스트 (예: ["005930", "034730", "263860"])
        date: 조회일 YYYYMMDD 형식. 비워두면 가장 최근 거래일 기준으로 조회합니다.

    Returns:
        get_closing_price와 동일한 형식의 dict 리스트 (요청한 순서 유지).
    """
    target = date or _latest_business_day()
    return [get_closing_price(t, target) for t in tickers]


@mcp.tool()
def get_market_cap(ticker: str, date: str = "") -> dict:
    """지정한 종목코드의 시가총액·상장주식수 정보를 반환합니다.

    Args:
        ticker: 6자리 종목코드
        date: 조회일 YYYYMMDD 형식. 비워두면 가장 최근 거래일 기준으로 조회합니다.
    """
    target = date or _latest_business_day()
    try:
        df = stock.get_market_cap(target, target, ticker)
    except Exception as e:
        return {"ticker": ticker, "date": target, "error": f"조회 실패: {e}"}

    if df is None or df.empty:
        return {"ticker": ticker, "date": target, "error": "해당일 데이터 없음"}

    row = df.iloc[0]
    return {
        "ticker": ticker,
        "date": target,
        "market_cap": int(row["시가총액"]),
        "shares_outstanding": int(row["상장주식수"]),
    }


@mcp.tool()
def get_latest_business_day() -> dict:
    """가장 최근 거래일(YYYYMMDD)을 반환합니다. 오늘이 휴장일이면 직전 거래일을 반환합니다."""
    return {"date": _latest_business_day()}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    # 최종 접속 URL은 http(s)://<host>:<port>/mcp 형태가 됩니다.
    mcp.settings.streamable_http_path = "/mcp"

    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
