"""Shared settings for the financial-research capstone.

Chat calls use OpenAI when OPENAI_API_KEY is set, and otherwise OpenRouter.
The same key from Capstone 1–4 works here. A local .env wins. If this folder
has none, the earlier capstone env files are read so the demo can run.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

load_dotenv(ROOT / ".env")
for _sibling in ("Capstone 4", "Capstone 3", "Capstone 2", "Capstone 1"):
    load_dotenv(ROOT.parent / _sibling / ".env")


def has_chat_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"))


def chat_client_kwargs() -> dict:
    """Arguments for the OpenAI SDK. base_url is omitted for the official API."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return {
            "model": os.getenv("CHAT_MODEL", "gpt-4o-mini"),
            "api_key": openai_key,
            "temperature": 0,
        }

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        return {
            "model": os.getenv("CHAT_MODEL", "openai/gpt-4o-mini"),
            "api_key": openrouter_key,
            "base_url": OPENROUTER_BASE_URL,
            "temperature": 0,
        }

    raise RuntimeError("Set OPENAI_API_KEY or OPENROUTER_API_KEY in .env")
