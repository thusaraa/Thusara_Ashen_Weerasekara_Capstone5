"""The four specialists. Each one calls a research tool, then writes a scoped report.

Citations are taken from the tool payload. The model can phrase the summary,
and it cannot invent a URL.
"""

from __future__ import annotations

import json

from llm import complete_json
from market import compliance_screen, disclaimer_present, ensure_disclaimer, strip_blocked_phrases
from mcp_client import ToolClient
from messages import AgentMessage, Citation

NEWS_SYSTEM = (
    "You are the News Researcher on a financial research desk. "
    "Use only the headline JSON in the user message. Do not invent prices, dates, or sources. "
    "Do not recommend buying, selling, or holding. Do not say returns are guaranteed. "
    'Return a JSON object with keys "summary" (string) and "findings" (array of short strings).'
)
ANALYST_SYSTEM = (
    "You are the Financial Analyst on a financial research desk. "
    "Use only the snapshot, fundamentals, and price-history JSON. "
    "Describe the figures. Do not recommend a trade and do not invent a price target. "
    'Return a JSON object with keys "summary" (string) and "findings" (array of short strings).'
)
RISK_SYSTEM = (
    "You are the Risk Assessor on a financial research desk. "
    "Use only the specialist reports and the price-history JSON. "
    "Name downside risks that the payload supports. "
    "Do not compare a figure with a historical average, and do not invent a cause, unless that comparison or cause is in the JSON. "
    "Do not recommend a trade. "
    'Return a JSON object with keys "summary" (string) and "findings" (array of short strings).'
)
REFINE_SYSTEM = (
    "You rewrite a research note so it can pass a compliance screen. "
    "Remove trade instructions, guarantees, risk-free claims, and unsupported price targets. "
    "Keep the facts and the source lines. "
    "Add this sentence if it is missing: This note is research context, not investment advice. "
    'Return a JSON object with keys "brief" (string) and "changes" (array of short strings).'
)


def news_researcher(ticker: str, tools: ToolClient, complete=None) -> AgentMessage:
    payload = tools.call("recent_news", {"ticker": ticker, "limit": 5})
    citations = _news_citations(payload)
    fallback, findings = _news_fallback(payload)
    summary, findings = _ask(complete, NEWS_SYSTEM, payload, fallback, findings)
    return AgentMessage(
        sender="news",
        recipient="coordinator",
        kind="report",
        ticker=ticker,
        summary=summary,
        findings=findings,
        citations=citations,
        payload=payload,
    )


def financial_analyst(ticker: str, tools: ToolClient, complete=None) -> AgentMessage:
    snapshot = tools.call("company_snapshot", {"ticker": ticker})
    fundamentals = tools.call("fundamentals", {"ticker": ticker})
    history = tools.call("price_history", {"ticker": ticker, "days": 30})
    payload = {"snapshot": snapshot, "fundamentals": fundamentals, "history": history}
    fallback, findings = _analyst_fallback(payload)
    summary, findings = _ask(complete, ANALYST_SYSTEM, payload, fallback, findings)
    return AgentMessage(
        sender="analyst",
        recipient="coordinator",
        kind="report",
        ticker=ticker,
        summary=summary,
        findings=findings,
        citations=[_source_citation(ticker, snapshot.get("source"), "market data")],
        payload=payload,
    )


def risk_assessor(
    ticker: str,
    tools: ToolClient,
    complete=None,
    news: AgentMessage | None = None,
    analyst: AgentMessage | None = None,
) -> AgentMessage:
    history = tools.call("price_history", {"ticker": ticker, "days": 30})
    payload = {
        "history": history,
        "news": _public_report(news),
        "analyst": _public_report(analyst),
    }
    fallback, findings = _risk_fallback(payload)
    summary, findings = _ask(complete, RISK_SYSTEM, payload, fallback, findings)
    return AgentMessage(
        sender="risk",
        recipient="coordinator",
        kind="report",
        ticker=ticker,
        summary=summary,
        findings=findings,
        citations=[_source_citation(ticker, history.get("source"), "price history")],
        payload=payload,
    )


def compliance_checker(ticker: str, tools: ToolClient, text: str) -> AgentMessage:
    screen = tools.call("compliance_screen", {"text": text})
    flags = list(screen.get("flags") or [])
    if screen.get("error"):
        summary = f"Compliance screen failed: {screen['error']}"
        flags = ["screen_error"]
    elif screen.get("passed"):
        summary = "The draft passed the compliance screen."
    else:
        summary = "The draft failed the compliance screen: " + ", ".join(flags) + "."
    return AgentMessage(
        sender="compliance",
        recipient="coordinator",
        kind="critique",
        ticker=ticker,
        summary=summary,
        flags=flags,
        payload=screen if isinstance(screen, dict) else {},
    )


def refine_note(draft: str, flags: list[str], complete=None) -> tuple[str, list[str]]:
    """Rewrite once. Source lines stay, and a disclaimer is appended when needed."""
    changes: list[str] = []
    text = draft
    content_flags = [flag for flag in flags if flag != "missing_disclaimer"]
    if content_flags and complete is not None:
        try:
            data = complete_json(
                complete,
                REFINE_SYSTEM,
                json.dumps({"draft": draft, "flags": flags}),
            )
            text = str(data.get("brief") or draft)
            changes.extend(str(item) for item in (data.get("changes") or []))
        except Exception:
            text = strip_blocked_phrases(draft)
            changes.append("Rewrote blocked phrases locally.")
    elif content_flags:
        text = strip_blocked_phrases(draft)
        changes.append("Rewrote blocked phrases locally.")
    restored = _restore_sources(draft, text)
    if restored != text:
        text = restored
        changes.append("Kept the source lines from the draft.")
    still_blocked = [
        flag for flag in compliance_screen(text)["flags"] if flag != "missing_disclaimer"
    ]
    if still_blocked:
        text = strip_blocked_phrases(text)
        changes.append("Cleared remaining blocked phrases.")
    if "missing_disclaimer" in flags or not disclaimer_present(text):
        text = ensure_disclaimer(text)
        changes.append("Appended the research disclaimer.")
    return text, changes


def _restore_sources(original: str, rewritten: str) -> str:
    source_lines = [line for line in original.splitlines() if line.startswith("- [")]
    missing = [line for line in source_lines if line not in rewritten]
    if not missing:
        return rewritten
    block = "\n".join(missing)
    if "## Sources" in rewritten:
        return rewritten.rstrip() + "\n" + block + "\n"
    return rewritten.rstrip() + "\n\n## Sources\n\n" + block + "\n"


def _ask(complete, system: str, payload: dict, fallback: str, findings: list[str]) -> tuple[str, list[str]]:
    if complete is None:
        return fallback, findings
    try:
        data = complete_json(complete, system, json.dumps(payload))
    except Exception:
        return fallback, findings
    summary = str(data.get("summary") or "").strip() or fallback
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        return summary, findings
    cleaned = [str(item).strip() for item in raw_findings if str(item).strip()]
    return summary, cleaned or findings


def _news_fallback(payload: dict) -> tuple[str, list[str]]:
    if payload.get("error"):
        return f"News lookup failed: {payload['error']}", []
    titles = [item.get("title", "") for item in payload.get("items") or [] if item.get("title")]
    if not titles:
        return "No recent headlines were returned for this ticker.", []
    return "Recent headlines: " + "; ".join(titles) + ".", titles


def _news_citations(payload: dict) -> list[Citation]:
    citations = []
    for item in payload.get("items") or []:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if url and title:
            citations.append(Citation(title=title, url=url, publisher=item.get("publisher") or ""))
    return citations


def _analyst_fallback(payload: dict) -> tuple[str, list[str]]:
    snapshot = payload.get("snapshot") or {}
    fundamentals = payload.get("fundamentals") or {}
    history = payload.get("history") or {}
    if snapshot.get("error") and fundamentals.get("error"):
        return f"Market data was unavailable: {snapshot['error']}", []
    parts = []
    if snapshot.get("price") is not None:
        parts.append(f"last price {snapshot['price']} {snapshot.get('currency') or ''}".strip())
    if fundamentals.get("trailing_pe") is not None:
        parts.append(f"trailing P/E {fundamentals['trailing_pe']}")
    if fundamentals.get("profit_margin") is not None:
        parts.append(f"profit margin {fundamentals['profit_margin']}")
    if history.get("return_pct") is not None:
        parts.append(f"{history.get('days')} bar return {history['return_pct']}%")
    if not parts:
        return "The market tools returned no figures.", []
    sentence = "Figures from the market tools: " + ", ".join(parts) + "."
    return sentence, parts


def _risk_fallback(payload: dict) -> tuple[str, list[str]]:
    history = payload.get("history") or {}
    findings = []
    volatility = history.get("annualized_volatility_pct")
    if volatility is not None:
        findings.append(f"Annualized volatility over the window is {volatility}%.")
    return_pct = history.get("return_pct")
    if return_pct is not None:
        findings.append(f"The window return is {return_pct}%.")
    news = payload.get("news") or {}
    for finding in (news.get("findings") or [])[:2]:
        findings.append(f"Headline theme: {finding}")
    if history.get("error"):
        return f"Risk inputs were incomplete: {history['error']}", findings
    if not findings:
        return "The risk tools did not return a window to assess.", []
    return " ".join(findings), findings


def _source_citation(ticker: str, source: str | None, label: str) -> Citation:
    if source == "fixture":
        url = f"https://example.com/fixture/{ticker}/{label.replace(' ', '-')}"
    else:
        url = f"https://finance.yahoo.com/quote/{ticker}"
    return Citation(title=f"{ticker} {label}", url=url, publisher=source or "market data")


def _public_report(message: AgentMessage | None) -> dict:
    if message is None:
        return {}
    return {"summary": message.summary, "findings": message.findings}
