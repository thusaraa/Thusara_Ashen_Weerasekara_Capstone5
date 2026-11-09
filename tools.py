"""The five research tools shared by the MCP server and the local client."""

from __future__ import annotations

from market import FixtureMarket, MarketData, MarketError, YFinanceMarket, compliance_screen

TOOL_NAMES = (
    "company_snapshot",
    "recent_news",
    "fundamentals",
    "price_history",
    "compliance_screen",
)


def dispatch(name: str, arguments: dict | None, market: MarketData | None = None) -> dict:
    """Run one tool. Validation failures come back as {"error": "..."}."""
    arguments = dict(arguments or {})
    feed = market if market is not None else YFinanceMarket()
    try:
        if name == "company_snapshot":
            return feed.snapshot(arguments["ticker"])
        if name == "recent_news":
            limit = arguments.get("limit", 5)
            return feed.news(arguments["ticker"], limit)
        if name == "fundamentals":
            return feed.fundamentals(arguments["ticker"])
        if name == "price_history":
            days = arguments.get("days", 30)
            return feed.history(arguments["ticker"], days)
        if name == "compliance_screen":
            return compliance_screen(arguments["text"])
        raise MarketError(f"Unknown tool {name}.")
    except KeyError as exc:
        return {"error": f"Missing argument {exc}."}
    except MarketError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"{name} failed: {exc}"}


def fixture_dispatch(name: str, arguments: dict | None) -> dict:
    return dispatch(name, arguments, FixtureMarket())
