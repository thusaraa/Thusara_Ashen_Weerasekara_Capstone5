"""Market data, ticker checks, and the compliance screen.

The MCP server and the in-process tool client both call these methods.
FixtureMarket keeps the tests and the offline demo off the network.
YFinanceMarket reads delayed public prices and headlines.
"""

from __future__ import annotations

import copy
import re
from typing import Protocol

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
STOPWORDS = frozenset(
    {
        "A",
        "I",
        "ME",
        "ON",
        "OR",
        "AN",
        "THE",
        "AND",
        "FOR",
        "TO",
        "OF",
        "IN",
        "RISK",
        "NEWS",
        "ETF",
        "IPO",
        "CEO",
        "CFO",
        "EPS",
        "PE",
        "AI",
        "US",
        "UK",
        "EU",
        "BRIEF",
        "CHECK",
        "COPY",
        "NOT",
        "BUY",
        "SELL",
        "HOLD",
        "USD",
        "GDP",
    }
)
ALIASES = {
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "meta": "META",
    "amd": "AMD",
    "intel": "INTC",
    "netflix": "NFLX",
    "broadcom": "AVGO",
}

_RULES = (
    (re.compile(r"\byou should (buy|sell|hold)\b", re.I), "trade_instruction"),
    (re.compile(r"\bguaranteed\b", re.I), "guarantee"),
    (re.compile(r"\brisk[-\s]?free\b", re.I), "risk_free"),
    (re.compile(r"\bwill (definitely|certainly)\b", re.I), "certainty"),
    (re.compile(r"\bprice target of \$\d", re.I), "price_target"),
)
_DISCLAIMER_RE = re.compile(r"not investment advice", re.I)
DISCLAIMER = (
    "This note is research context, not investment advice. "
    "It does not recommend buying, selling, or holding any security."
)

_FIXTURE = {
    "snapshot": {
        "ticker": "NVDA",
        "name": "NVIDIA Corporation",
        "price": 131.25,
        "currency": "USD",
        "market_cap": 3_200_000_000_000,
        "year_high": 153.13,
        "year_low": 86.62,
        "source": "fixture",
    },
    "news": [
        {
            "title": "NVIDIA data-center revenue stays in focus ahead of earnings",
            "publisher": "Example Wire",
            "url": "https://example.com/nvda-earnings",
            "published": "2026-11-01",
        },
        {
            "title": "Export rules remain a watch item for NVIDIA accelerators",
            "publisher": "Example Policy",
            "url": "https://example.com/nvda-export",
            "published": "2026-10-28",
        },
    ],
    "fundamentals": {
        "ticker": "NVDA",
        "trailing_pe": 48.2,
        "forward_pe": 32.4,
        "profit_margin": 0.55,
        "revenue": 130_500_000_000,
        "earnings_date": "2026-11-19",
        "source": "fixture",
    },
    "history": {
        "ticker": "NVDA",
        "days": 21,
        "start_price": 118.0,
        "end_price": 131.25,
        "return_pct": 11.23,
        "annualized_volatility_pct": 42.0,
        "high": 136.0,
        "low": 116.4,
        "source": "fixture",
    },
}


class MarketError(ValueError):
    """A ticker, a limit, or a tool argument failed validation."""


class MarketData(Protocol):
    def snapshot(self, ticker: str) -> dict: ...

    def news(self, ticker: str, limit: int = 5) -> dict: ...

    def fundamentals(self, ticker: str) -> dict: ...

    def history(self, ticker: str, days: int = 30) -> dict: ...


def parse_ticker(raw: str) -> str:
    ticker = (raw or "").strip().upper().lstrip("$")
    if not TICKER_RE.match(ticker) or ticker in STOPWORDS:
        raise MarketError("Ticker must be 1 to 5 letters, such as NVDA.")
    return ticker


def extract_ticker(text: str) -> str:
    """Pull a symbol from a research question.

    A $NVDA form wins, then an all-caps token, then a company name.
    """
    dollar = re.search(r"\$([A-Za-z]{1,5})\b", text or "")
    if dollar:
        return parse_ticker(dollar.group(1))
    for token in re.findall(r"\b[A-Z]{1,5}\b", text or ""):
        if token not in STOPWORDS and len(token) >= 2:
            return token
    lowered = (text or "").lower()
    for name, ticker in ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return ticker
    raise MarketError("No ticker found. Use a symbol like NVDA or a name like Nvidia.")


def parse_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
        raise MarketError("limit must be an integer from 1 to 8.")
    return limit


def parse_days(days: int) -> int:
    if isinstance(days, bool) or not isinstance(days, int) or not 5 <= days <= 90:
        raise MarketError("days must be an integer from 5 to 90.")
    return days


def compliance_screen(text: str) -> dict:
    """Flag trade instructions, guarantees, and a missing disclaimer."""
    if not isinstance(text, str):
        raise MarketError("text must be a string.")
    sample = text[:20_000]
    flags = [code for pattern, code in _RULES if pattern.search(sample)]
    disclaimer = bool(_DISCLAIMER_RE.search(sample))
    if not disclaimer:
        flags.append("missing_disclaimer")
    return {
        "passed": not flags,
        "flags": flags,
        "disclaimer_present": disclaimer,
    }


def disclaimer_present(text: str) -> bool:
    return bool(_DISCLAIMER_RE.search(text or ""))


def ensure_disclaimer(text: str) -> str:
    body = (text or "").rstrip()
    if disclaimer_present(body):
        return body
    if not body:
        return DISCLAIMER
    return f"{body}\n\n{DISCLAIMER}"


def strip_blocked_phrases(text: str) -> str:
    """Local rewrite used when the model rewrite is unavailable."""
    cleaned = text or ""
    cleaned = re.sub(r"\byou should (buy|sell|hold)\b", "the sources discuss", cleaned, flags=re.I)
    cleaned = re.sub(r"\bguaranteed\b", "uncertain", cleaned, flags=re.I)
    cleaned = re.sub(r"\brisk[-\s]?free\b", "risky", cleaned, flags=re.I)
    cleaned = re.sub(r"\bwill (definitely|certainly)\b", "may", cleaned, flags=re.I)
    cleaned = re.sub(r"\bprice target of \$\d[\d,]*", "an unsupported target", cleaned, flags=re.I)
    return cleaned


class FixtureMarket:
    """Fixed NVDA-shaped data. The requested ticker is stamped onto each payload."""

    def snapshot(self, ticker: str) -> dict:
        symbol = parse_ticker(ticker)
        data = copy.deepcopy(_FIXTURE["snapshot"])
        data["ticker"] = symbol
        if symbol != "NVDA":
            data["name"] = f"{symbol} sample"
        return data

    def news(self, ticker: str, limit: int = 5) -> dict:
        symbol = parse_ticker(ticker)
        count = parse_limit(limit)
        items = []
        for item in _FIXTURE["news"][:count]:
            row = copy.deepcopy(item)
            if symbol != "NVDA":
                row["title"] = row["title"].replace("NVIDIA", symbol)
                row["url"] = f"https://example.com/{symbol.lower()}-{len(items) + 1}"
            items.append(row)
        return {"ticker": symbol, "items": items, "source": "fixture"}

    def fundamentals(self, ticker: str) -> dict:
        symbol = parse_ticker(ticker)
        data = copy.deepcopy(_FIXTURE["fundamentals"])
        data["ticker"] = symbol
        return data

    def history(self, ticker: str, days: int = 30) -> dict:
        symbol = parse_ticker(ticker)
        parse_days(days)
        data = copy.deepcopy(_FIXTURE["history"])
        data["ticker"] = symbol
        return data


class YFinanceMarket:
    """Delayed quotes, headlines, fundamentals, and a short return window."""

    def snapshot(self, ticker: str) -> dict:
        symbol = parse_ticker(ticker)
        instrument = self._instrument(symbol)
        info = _fast_info(instrument)
        price = _first(info, "last_price", "lastPrice")
        if price is None:
            closes = self._closes(instrument)
            price = float(closes.iloc[-1])
        name = symbol
        try:
            short_name = (instrument.info or {}).get("shortName")
            if short_name:
                name = str(short_name)
        except Exception:
            name = symbol
        return {
            "ticker": symbol,
            "name": name,
            "price": _round(price),
            "currency": _first(info, "currency") or "USD",
            "market_cap": _round(_first(info, "market_cap", "marketCap"), 0),
            "year_high": _round(_first(info, "year_high", "yearHigh")),
            "year_low": _round(_first(info, "year_low", "yearLow")),
            "source": "yfinance",
        }

    def news(self, ticker: str, limit: int = 5) -> dict:
        symbol = parse_ticker(ticker)
        count = parse_limit(limit)
        instrument = self._instrument(symbol)
        try:
            raw_items = list(instrument.news or [])
        except Exception as exc:
            raise MarketError(f"News lookup failed for {symbol}: {exc}") from exc
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = _news_item(raw)
            if item and _about_ticker(symbol, item):
                items.append(item)
            if len(items) >= count:
                break
        return {"ticker": symbol, "items": items, "source": "yfinance"}

    def fundamentals(self, ticker: str) -> dict:
        symbol = parse_ticker(ticker)
        instrument = self._instrument(symbol)
        try:
            info = instrument.info or {}
        except Exception as exc:
            raise MarketError(f"Fundamentals lookup failed for {symbol}: {exc}") from exc
        if not isinstance(info, dict):
            info = {}
        return {
            "ticker": symbol,
            "trailing_pe": _round(info.get("trailingPE")),
            "forward_pe": _round(info.get("forwardPE")),
            "profit_margin": _round(info.get("profitMargins"), 4),
            "revenue": _round(info.get("totalRevenue"), 0),
            "earnings_date": _earnings_date(instrument),
            "source": "yfinance",
        }

    def history(self, ticker: str, days: int = 30) -> dict:
        symbol = parse_ticker(ticker)
        window = parse_days(days)
        closes = self._closes(self._instrument(symbol)).tail(window)
        if len(closes) < 2:
            raise MarketError(f"Not enough prices for {symbol}.")
        start = float(closes.iloc[0])
        end = float(closes.iloc[-1])
        daily = closes.pct_change().dropna()
        volatility = float(daily.std() * (252 ** 0.5) * 100) if len(daily) else 0.0
        return {
            "ticker": symbol,
            "days": int(len(closes)),
            "start_price": _round(start),
            "end_price": _round(end),
            "return_pct": _round((end / start - 1) * 100),
            "annualized_volatility_pct": _round(volatility),
            "high": _round(float(closes.max())),
            "low": _round(float(closes.min())),
            "source": "yfinance",
        }

    @staticmethod
    def _instrument(ticker: str):
        import yfinance as yf

        return yf.Ticker(ticker)

    @staticmethod
    def _closes(instrument):
        try:
            hist = instrument.history(period="3mo")
        except Exception as exc:
            raise MarketError(f"Price lookup failed: {exc}") from exc
        if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
            raise MarketError("No prices were returned.")
        closes = hist["Close"].dropna()
        if closes.empty:
            raise MarketError("No prices were returned.")
        return closes


def _fast_info(instrument) -> dict:
    try:
        info = instrument.fast_info
    except Exception:
        return {}
    if isinstance(info, dict):
        return info
    return info


def _first(info, *keys):
    for key in keys:
        if isinstance(info, dict) and info.get(key) is not None:
            return info.get(key)
        if hasattr(info, key):
            value = getattr(info, key)
            if value is not None:
                return value
    return None


def _round(value, digits: int = 2):
    number = _as_float(value)
    if number is None:
        return None
    if digits == 0:
        return int(round(number))
    return round(number, digits)


def _as_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _news_item(raw: dict) -> dict | None:
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    title = content.get("title") or raw.get("title")
    if not title:
        return None
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    publisher = provider.get("displayName") or content.get("publisher") or raw.get("publisher") or ""
    canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
    url = ""
    if isinstance(canonical, dict):
        url = canonical.get("url") or ""
    url = url or content.get("link") or raw.get("link") or ""
    published = content.get("pubDate") or ""
    if not published and raw.get("providerPublishTime"):
        published = str(raw["providerPublishTime"])
    summary = content.get("summary") or content.get("description") or ""
    return {
        "title": str(title),
        "publisher": str(publisher),
        "url": str(url),
        "published": str(published),
        "summary": str(summary)[:400],
    }


def _about_ticker(ticker: str, item: dict) -> bool:
    """Keep a headline when the title names the company. Yahoo also tags unrelated stories."""
    names = [ticker]
    for name, symbol in ALIASES.items():
        if symbol == ticker:
            names.append(name)
    title = item.get("title") or ""
    return any(re.search(rf"\b{re.escape(name)}\b", title, re.I) for name in names)


def _earnings_date(instrument) -> str | None:
    try:
        calendar = instrument.calendar
    except Exception:
        return None
    if isinstance(calendar, dict):
        value = calendar.get("Earnings Date") or calendar.get("EarningsDate")
        if isinstance(value, (list, tuple)) and value:
            return str(value[0])[:10]
        if value:
            return str(value)[:10]
    return None
