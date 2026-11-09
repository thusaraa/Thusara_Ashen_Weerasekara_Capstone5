"""JSON chat calls for the specialist write-ups and the refine step."""

from __future__ import annotations

import json
import re

from config import chat_client_kwargs


def parse_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, count=1).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Model output was not a JSON object.")
    return parsed


def complete_json(complete, system: str, user: str) -> dict:
    raw = complete(system, user)
    if isinstance(raw, dict):
        return raw
    return parse_json_object(str(raw))


def build_complete():
    """Return complete(system, user) -> str. The model is asked for JSON."""
    from openai import OpenAI

    kwargs = chat_client_kwargs()
    client = OpenAI(api_key=kwargs["api_key"], base_url=kwargs.get("base_url"))
    model = kwargs["model"]

    def complete(system: str, user: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
            )
        return response.choices[0].message.content or ""

    return complete
