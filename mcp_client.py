"""Tool clients. LocalToolClient stays in-process. HttpMcpClient calls FastMCP."""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from market import MarketData
from tools import dispatch


class ToolClient(Protocol):
    def call(self, name: str, arguments: dict) -> dict: ...


class LocalToolClient:
    def __init__(self, market: MarketData):
        self.market = market

    def call(self, name: str, arguments: dict) -> dict:
        return dispatch(name, arguments, self.market)


class HttpMcpClient:
    """One HTTP call per tool. The server is the containerized MCP process."""

    def __init__(self, url: str):
        self.url = url

    def call(self, name: str, arguments: dict) -> dict:
        return asyncio.run(_call_http(self.url, name, arguments))


async def _call_http(url: str, name: str, arguments: dict) -> dict:
    from fastmcp import Client

    async with Client(url) as client:
        result = await client.call_tool(name, arguments)
    return unwrap_tool_result(result)


def unwrap_tool_result(result) -> dict:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    if isinstance(result, dict):
        return result
    raise RuntimeError("The MCP tool result was not a JSON object.")
