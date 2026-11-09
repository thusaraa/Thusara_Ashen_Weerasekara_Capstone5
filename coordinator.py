"""Coordinator-dispatcher for a financial research brief.

News and the financial analyst run together. Risk reads both reports.
Compliance critiques the draft, and one refine pass follows when the screen
raises a flag. A second screen is the last step.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from config import has_chat_key
from llm import build_complete
from market import FixtureMarket, YFinanceMarket, extract_ticker, parse_ticker
from mcp_client import HttpMcpClient, LocalToolClient, ToolClient
from messages import AgentMessage, Citation, ResearchBrief
from specialists import (
    compliance_checker,
    financial_analyst,
    news_researcher,
    refine_note,
    risk_assessor,
)

_NEWS_CUES = ("news", "headline", "headlines", "brief", "earnings", "research")
_ANALYST_CUES = (
    "earnings",
    "margin",
    "margins",
    "valuation",
    "financial",
    "revenue",
    "brief",
    "risk",
    "research",
)
_RISK_CUES = ("risk", "risks", "brief", "downside", "exposure", "research")
_COMPLIANCE_CUES = ("compliant", "compliance", "check this", "screen this")


def route(goal: str) -> list[str]:
    """Pick specialists from the wording of the research goal.

    Compliance always closes a research route. A request that only asks
    for a screen stays with the compliance checker.
    """
    text = (goal or "").lower()
    wants_news = any(cue in text for cue in _NEWS_CUES)
    wants_analyst = any(cue in text for cue in _ANALYST_CUES)
    wants_risk = any(cue in text for cue in _RISK_CUES)
    screen_only = any(cue in text for cue in _COMPLIANCE_CUES)
    if screen_only and not (wants_news or wants_analyst or wants_risk):
        return ["compliance"]
    roles = []
    if wants_news:
        roles.append("news")
    if wants_analyst:
        roles.append("analyst")
    if wants_risk:
        roles.append("risk")
    if not roles:
        roles = ["news", "analyst", "risk"]
    roles.append("compliance")
    return roles


def run(goal: str, tools: ToolClient, complete=None, ticker: str | None = None) -> ResearchBrief:
    symbol = parse_ticker(ticker) if ticker else extract_ticker(goal)
    roles = route(goal)
    messages: list[AgentMessage] = []
    reports: dict[str, AgentMessage] = {}

    parallel = [role for role in ("news", "analyst") if role in roles]
    for role in parallel:
        messages.append(_task(role, symbol, goal))
    finished = _run_parallel(symbol, tools, complete, parallel)
    for role in parallel:
        messages.append(finished[role])
        reports[role] = finished[role]

    if "risk" in roles:
        messages.append(_task("risk", symbol, goal))
        report = risk_assessor(symbol, tools, complete, reports.get("news"), reports.get("analyst"))
        messages.append(report)
        reports["risk"] = report

    draft = goal if roles == ["compliance"] else assemble_note(symbol, goal, reports)
    if roles != ["compliance"]:
        messages.append(
            AgentMessage(
                sender="coordinator",
                recipient="compliance",
                kind="report",
                ticker=symbol,
                summary="Draft assembled from the specialist reports.",
                payload={"draft": draft},
            )
        )

    critique = compliance_checker(symbol, tools, draft)
    messages.append(critique)
    note = draft
    refined = False
    if critique.flags:
        note, changes = refine_note(draft, critique.flags, complete)
        refined = True
        messages.append(
            AgentMessage(
                sender="coordinator",
                recipient="user",
                kind="revision",
                ticker=symbol,
                summary="Revised the draft after the compliance critique.",
                findings=changes,
                flags=list(critique.flags),
            )
        )
        second = compliance_checker(symbol, tools, note)
        messages.append(second)
        remaining = list(second.flags)
    else:
        remaining = []

    return ResearchBrief(
        goal=goal,
        ticker=symbol,
        roles=roles,
        messages=messages,
        critique_flags=list(critique.flags),
        refined=refined,
        remaining_flags=remaining,
        note=note,
        citations=_collect_citations(reports),
    )


def assemble_note(ticker: str, goal: str, reports: dict[str, AgentMessage]) -> str:
    lines = [f"# {ticker} research note", "", f"Question: {goal}", ""]
    sections = (
        ("news", "News"),
        ("analyst", "Financials"),
        ("risk", "Risks"),
    )
    for role, title in sections:
        report = reports.get(role)
        if report is None:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append(report.summary)
        for finding in report.findings:
            lines.append(f"- {finding}")
        lines.append("")
    citations = _collect_citations(reports)
    if citations:
        lines.append("## Sources")
        lines.append("")
        for citation in citations:
            publisher = f", {citation.publisher}" if citation.publisher else ""
            lines.append(f"- [{citation.title}]({citation.url}){publisher}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render(brief: ResearchBrief) -> str:
    """Markdown transcript of one coordinator run."""
    lines = [
        f"# Capstone 5 demo — {brief.ticker}",
        "",
        brief.goal,
        "",
        "Route: " + ", ".join(brief.roles),
        "Critique flags: " + (", ".join(brief.critique_flags) or "none"),
        f"Refined: {brief.refined}",
        "Remaining flags: " + (", ".join(brief.remaining_flags) or "none"),
        "",
        "## Handoff",
        "",
    ]
    for message in brief.messages:
        lines.append(f"### {message.sender} -> {message.recipient} ({message.kind})")
        lines.append("")
        lines.append(message.summary)
        if message.findings:
            lines.append("")
            for finding in message.findings:
                lines.append(f"- {finding}")
        lines.append("")
    lines.extend(["## Final note", "", brief.note])
    return "\n".join(lines).rstrip() + "\n"


def _run_parallel(ticker: str, tools: ToolClient, complete, roles: list[str]) -> dict[str, AgentMessage]:
    if not roles:
        return {}

    def run_one(role: str) -> AgentMessage:
        if role == "news":
            return news_researcher(ticker, tools, complete)
        if role == "analyst":
            return financial_analyst(ticker, tools, complete)
        raise RuntimeError(f"No parallel runner for {role}.")

    if len(roles) == 1:
        return {roles[0]: run_one(roles[0])}
    finished: dict[str, AgentMessage] = {}
    with ThreadPoolExecutor(max_workers=len(roles)) as pool:
        futures = {pool.submit(run_one, role): role for role in roles}
        for future, role in futures.items():
            finished[role] = future.result()
    return finished


def _task(role: str, ticker: str, goal: str) -> AgentMessage:
    instructions = {
        "news": f"Collect recent headlines for {ticker}.",
        "analyst": f"Read price, fundamentals, and the recent window for {ticker}.",
        "risk": f"Assess downside risk for {ticker} from the other reports.",
    }
    return AgentMessage(
        sender="coordinator",
        recipient=role,
        kind="task",
        ticker=ticker,
        summary=f"{instructions[role]} Goal: {goal}",
    )


def _collect_citations(reports: dict[str, AgentMessage]) -> list[Citation]:
    seen = set()
    citations = []
    for role in ("news", "analyst", "risk"):
        report = reports.get(role)
        if report is None:
            continue
        for citation in report.citations:
            if citation.url in seen:
                continue
            seen.add(citation.url)
            citations.append(citation)
    return citations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Financial news research coordinator")
    parser.add_argument("goal", nargs="?", default="Brief me on NVDA earnings risk")
    parser.add_argument("--ticker", help="Override the ticker parsed from the goal")
    parser.add_argument("--mcp", help="FastMCP URL, for example http://localhost:8000/mcp")
    parser.add_argument("--offline", action="store_true", help="Use fixture data and skip the model")
    args = parser.parse_args(argv)

    if args.offline:
        tools: ToolClient = LocalToolClient(FixtureMarket())
        complete = None
    elif args.mcp:
        if not has_chat_key():
            raise SystemExit("Set OPENAI_API_KEY or OPENROUTER_API_KEY before using --mcp.")
        tools = HttpMcpClient(args.mcp)
        complete = build_complete()
    else:
        if not has_chat_key():
            raise SystemExit("Set OPENAI_API_KEY or OPENROUTER_API_KEY, or pass --offline.")
        tools = LocalToolClient(YFinanceMarket())
        complete = build_complete()

    brief = run(args.goal, tools, complete, ticker=args.ticker)
    print(brief.note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
