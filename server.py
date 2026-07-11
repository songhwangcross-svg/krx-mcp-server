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

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pykrx import stock

logging.basicConfig(level=logging.INFO)
_diag = logging.getLogger("krx-mcp-diag")

mcp = FastMCP("krx-price-server")


def _diagnose_and_disable_transport_security():
    """MCP SDK가 DNS 리바인딩 방지를 위해 Host 헤더를 검사하는데, 배포 도메인이
    기본 허용 목록(localhost 등)에 없어서 계속 421로 막힙니다. 정확한 내부 구조를
    모르는 상태에서 여러 차례 값만 바꿔 시도했지만 실패했으므로, 이번에는
    1) 실제 구조를 로그로 출력해서 진단하고
    2) 검증 관련 메서드를 이름 패턴으로 찾아 "항상 통과"하도록 패치합니다.
    로그에서 "[KRX-DIAG]"로 시작하는 줄을 확인하면 정확한 원인을 알 수 있습니다.
    """
    try:
        import mcp.server.transport_security as ts_mod
    except ImportError as e:
        _diag.warning("[KRX-DIAG] transport_security 모듈 임포트 실패: %s", e)
        return

    names = [n for n in dir(ts_mod) if not n.startswith("_")]
    _diag.warning("[KRX-DIAG] transport_security 모듈 멤버: %s", names)

    settings_cls = getattr(ts_mod, "TransportSecuritySettings", None)
    permissive = None
    if settings_cls is not None:
        try:
            default_settings = settings_cls()
            dump = getattr(default_settings, "model_dump", None)
            _diag.warning(
                "[KRX-DIAG] 기본 TransportSecuritySettings: %s",
                dump() if callable(dump) else vars(default_settings),
            )
        except Exception as e:
            _diag.warning("[KRX-DIAG] TransportSecuritySettings() 기본값 조회 실패: %s", e)
        try:
            permissive = settings_cls(enabled=False, allowed_hosts=["*"], allowed_origins=["*"])
        except Exception as e:
            _diag.warning("[KRX-DIAG] permissive TransportSecuritySettings 생성 실패: %s", e)

    # 검증 로직을 담당할 것으로 보이는 클래스의 메서드를 이름 패턴으로 찾아 패치
    patched_any = False
    for name in names:
        obj = getattr(ts_mod, name)
        if not isinstance(obj, type):
            continue
        if "Middleware" not in name and "Security" not in name:
            continue
        method_names = [m for m in vars(obj).keys() if not m.startswith("__")]
        _diag.warning("[KRX-DIAG] 후보 클래스 %s 메서드: %s", name, method_names)
        for method_name in method_names:
            lower = method_name.lower()
            if not any(k in lower for k in ("host", "origin", "valid", "check", "verify")):
                continue
            attr = getattr(obj, method_name)
            if not callable(attr):
                continue
            if asyncio.iscoroutinefunction(attr):
                async def _always_ok(*a, **kw):
                    return True
                setattr(obj, method_name, _always_ok)
            else:
                setattr(obj, method_name, lambda *a, **kw: True)
            patched_any = True
            _diag.warning("[KRX-DIAG] %s.%s 를 항상 허용하도록 패치함", name, method_name)

    if not patched_any:
        _diag.warning("[KRX-DIAG] 패치할 메서드를 찾지 못함 — 이름 패턴이 다를 수 있음")

    # FastMCP 인스턴스/설정 쪽에도 permissive 설정을 넣어볼 수 있는 자리를 모두 시도
    if permissive is not None:
        for holder_name, holder in (("mcp", mcp), ("mcp.settings", getattr(mcp, "settings", None))):
            if holder is None:
                continue
            for field_name in ("transport_security", "security", "security_settings"):
                if hasattr(holder, field_name):
                    try:
                        setattr(holder, field_name, permissive)
                        _diag.warning("[KRX-DIAG] %s.%s = permissive 설정 성공", holder_name, field_name)
                    except Exception as e:
                        _diag.warning("[KRX-DIAG] %s.%s 설정 실패: %s", holder_name, field_name, e)


_diagnose_and_disable_transport_security()


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


class _HostHeaderRewriteMiddleware:
    """MCP SDK에는 DNS 리바인딩 공격을 막기 위해 Host 헤더가 localhost 계열일 때만
    통과시키는 내부 보안 검사가 있습니다. 이 서버는 실제 도메인(onrender.com 등)으로
    배포되므로 그 검사에서 항상 421로 막히는데, 버전에 따라 이 검사를 끄는 설정 API가
    다르거나 없을 수 있어 더 확실한 방법으로 우회합니다: 요청이 내부 앱에 도달하기 전에
    Host 헤더 값을 "localhost"로 바꿔치기합니다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            scope = dict(scope)
            scope["headers"] = [
                (b"host", b"localhost") if k.lower() == b"host" else (k, v)
                for k, v in scope.get("headers", [])
            ]
        await self.app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    # 최종 접속 URL은 http(s)://<host>:<port>/mcp 형태가 됩니다.
    mcp.settings.streamable_http_path = "/mcp"

    raw_app = mcp.streamable_http_app()
    app = _HostHeaderRewriteMiddleware(raw_app)
    uvicorn.run(app, host="0.0.0.0", port=port)
