"""FastMCP server for the financial research tools.

Run it with `python mcp_server.py`, then point MCP Inspector at
http://localhost:8000/mcp. The coordinator can use this process with
`--mcp http://localhost:8000/mcp`. The default coordinator path calls the
same functions in-process.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from market import MarketData, YFinanceMarket
from tools import dispatch

mcp = FastMCP("Financial Research MCP")

_market: MarketData = YFinanceMarket()


def set_market(market: MarketData) -> None:
    """Swap the data source. Tests point this at FixtureMarket."""
    global _market
    _market = market


def get_market() -> MarketData:
    return _market


@mcp.tool()
def company_snapshot(ticker: str) -> dict:
    """Latest price, market cap, and 52-week range for a stock ticker."""
    return dispatch("company_snapshot", {"ticker": ticker}, get_market())


@mcp.tool()
def recent_news(ticker: str, limit: int = 5) -> dict:
    """Recent headlines for a ticker. limit is an integer from 1 to 8."""
    return dispatch("recent_news", {"ticker": ticker, "limit": limit}, get_market())


@mcp.tool()
def fundamentals(ticker: str) -> dict:
    """Trailing and forward P/E, margin, revenue, and the next earnings date."""
    return dispatch("fundamentals", {"ticker": ticker}, get_market())


@mcp.tool()
def price_history(ticker: str, days: int = 30) -> dict:
    """Window return, high, low, and annualized volatility. days is 5 to 90."""
    return dispatch("price_history", {"ticker": ticker, "days": days}, get_market())


@mcp.tool()
def compliance_screen(text: str) -> dict:
    """Flag trade instructions, guarantees, and a missing research disclaimer."""
    return dispatch("compliance_screen", {"text": text}, get_market())


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")


if __name__ == "__main__":
    main()
