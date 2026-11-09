"""Checks that do not call a model or the public market APIs."""

from __future__ import annotations

import asyncio
import json
import unittest

from coordinator import route, run
from market import (
    FixtureMarket,
    MarketError,
    _about_ticker,
    compliance_screen,
    extract_ticker,
    parse_limit,
    parse_ticker,
)
from mcp_client import LocalToolClient, unwrap_tool_result
from messages import AgentMessage
from specialists import refine_note


class TickerTests(unittest.TestCase):
    def test_symbol_from_the_course_question(self):
        self.assertEqual(extract_ticker("Brief me on NVDA earnings risk"), "NVDA")

    def test_company_name_and_dollar_prefix(self):
        self.assertEqual(extract_ticker("How does nvidia look into earnings?"), "NVDA")
        self.assertEqual(parse_ticker("$aapl"), "AAPL")

    def test_stopword_and_missing_ticker(self):
        with self.assertRaises(MarketError):
            parse_ticker("RISK")
        with self.assertRaises(MarketError):
            extract_ticker("What should I watch this week?")

    def test_headline_filter_keeps_the_company_name(self):
        self.assertTrue(_about_ticker("NVDA", {"title": "Older Nvidia chips just cost Oracle a deal"}))
        self.assertFalse(_about_ticker("NVDA", {"title": "Eli Lilly raised its revenue forecast"}))

    def test_limit_range(self):
        self.assertEqual(parse_limit(5), 5)
        with self.assertRaises(MarketError):
            parse_limit(0)
        with self.assertRaises(MarketError):
            parse_limit(12)


class ComplianceTests(unittest.TestCase):
    def test_flags_trade_language_and_a_missing_disclaimer(self):
        screen = compliance_screen("You should buy NVDA. Returns are guaranteed.")
        self.assertFalse(screen["passed"])
        self.assertIn("trade_instruction", screen["flags"])
        self.assertIn("guarantee", screen["flags"])
        self.assertIn("missing_disclaimer", screen["flags"])

    def test_clear_text_passes(self):
        screen = compliance_screen(
            "Export rules are a watch item. This note is research context, not investment advice."
        )
        self.assertTrue(screen["passed"])
        self.assertEqual(screen["flags"], [])


class RouteTests(unittest.TestCase):
    def test_full_brief(self):
        self.assertEqual(
            route("Brief me on NVDA earnings risk"),
            ["news", "analyst", "risk", "compliance"],
        )

    def test_headlines_skip_the_analyst(self):
        self.assertEqual(route("Latest headlines on AAPL"), ["news", "compliance"])

    def test_margins_go_to_the_analyst(self):
        self.assertEqual(route("What are MSFT margins"), ["analyst", "compliance"])

    def test_screen_only(self):
        self.assertEqual(
            route("Check this copy: you should buy NVDA"),
            ["compliance"],
        )


class CoordinatorTests(unittest.TestCase):
    def test_offline_brief_critiques_then_adds_the_disclaimer(self):
        client = RecordingClient()
        brief = run("Brief me on NVDA earnings risk", client)
        self.assertEqual(brief.ticker, "NVDA")
        self.assertEqual(brief.critique_flags, ["missing_disclaimer"])
        self.assertTrue(brief.refined)
        self.assertEqual(brief.remaining_flags, [])
        self.assertIn("not investment advice", brief.note.lower())
        self.assertTrue(any(item.url.startswith("https://example.com/") for item in brief.citations))
        self.assertIn("recent_news", client.calls)
        self.assertIn("fundamentals", client.calls)
        self.assertEqual(client.calls.count("compliance_screen"), 2)
        senders = [message.sender for message in brief.messages]
        self.assertLess(senders.index("news"), senders.index("risk"))
        self.assertLess(senders.index("analyst"), senders.index("risk"))

    def test_rewrite_removes_a_planted_trade_instruction(self):
        brief = run("Brief me on NVDA earnings risk", LocalToolClient(FixtureMarket()), _planted_complete)
        self.assertIn("trade_instruction", brief.critique_flags)
        self.assertIn("guarantee", brief.critique_flags)
        self.assertTrue(brief.refined)
        self.assertEqual(brief.remaining_flags, [])
        self.assertNotIn("guaranteed", brief.note.lower())
        self.assertNotIn("you should buy", brief.note.lower())

    def test_local_refine_strips_phrases_without_a_model(self):
        cleaned, changes = refine_note(
            "You should buy NVDA. Returns are guaranteed.",
            ["trade_instruction", "guarantee", "missing_disclaimer"],
        )
        screen = compliance_screen(cleaned)
        self.assertTrue(screen["passed"])
        self.assertTrue(changes)


class McpToolTests(unittest.TestCase):
    def test_in_memory_client_calls_the_snapshot_tool(self):
        import mcp_server
        from fastmcp import Client

        mcp_server.set_market(FixtureMarket())
        try:
            result = asyncio.run(_snapshot(Client))
        finally:
            from market import YFinanceMarket

            mcp_server.set_market(YFinanceMarket())
        data = unwrap_tool_result(result)
        self.assertEqual(data["ticker"], "NVDA")
        self.assertEqual(data["price"], 131.25)
        self.assertNotIn("error", data)

    def test_bad_ticker_is_an_error_payload(self):
        payload = LocalToolClient(FixtureMarket()).call("company_snapshot", {"ticker": "RISK"})
        self.assertIn("error", payload)


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.inner = LocalToolClient(FixtureMarket())

    def call(self, name: str, arguments: dict) -> dict:
        self.calls.append(name)
        return self.inner.call(name, arguments)


def _planted_complete(system: str, user: str) -> str:
    if "rewrite" in system.lower():
        return json.dumps(
            {
                "brief": (
                    "NVDA coverage centers on data-center demand and export rules. "
                    "This note is research context, not investment advice."
                ),
                "changes": ["Removed the trade instruction.", "Removed the guarantee."],
            }
        )
    if "News Researcher" in system:
        return json.dumps(
            {
                "summary": "You should buy NVDA, returns are guaranteed.",
                "findings": ["You should buy NVDA, returns are guaranteed."],
            }
        )
    return json.dumps(
        {
            "summary": "The tool payload is the only basis for this section.",
            "findings": ["Used the tool payload."],
        }
    )


async def _snapshot(client_cls):
    import mcp_server

    async with client_cls(mcp_server.mcp) as client:
        return await client.call_tool("company_snapshot", {"ticker": "NVDA"})


class MessageShapeTests(unittest.TestCase):
    def test_report_round_trip(self):
        message = AgentMessage(
            sender="news",
            recipient="coordinator",
            kind="report",
            ticker="NVDA",
            summary="Headlines are in.",
        )
        self.assertEqual(message.model_dump()["kind"], "report")


if __name__ == "__main__":
    unittest.main()
