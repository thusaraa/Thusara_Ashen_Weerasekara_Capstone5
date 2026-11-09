"""Structured messages passed between the coordinator and the specialists."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    title: str
    url: str
    publisher: str = ""


class AgentMessage(BaseModel):
    sender: str
    recipient: str
    kind: Literal["task", "report", "critique", "revision"]
    ticker: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class ResearchBrief(BaseModel):
    goal: str
    ticker: str
    roles: list[str]
    messages: list[AgentMessage]
    critique_flags: list[str]
    refined: bool
    remaining_flags: list[str]
    note: str
    citations: list[Citation]
