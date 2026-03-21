"""
Core interfaces for the evaluation system.

The design separates two independent axes of variation:

  LLMBackend        — WHERE / HOW the LLM is called (Claude, LM Studio, Ollama, keyword)
  EvaluationStrategy — WHAT is asked and how the response is parsed

These are composed into an Evaluator by factory.py.
Adding a new backend never requires changing any strategy, and vice versa.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paperbreakfast.models.db import Paper


@dataclass
class EvaluationResult:
    triage: str            # "read" | "skim" | "horizon" | "skip"
    milestone: bool = False          # True = paradigm-shifting advance
    summary: dict | None = None      # {problem, model, finding, impact} or None for skip
    raw_response: str = ""           # raw LLM output, preserved for debugging
    evaluator_name: str = ""
    parse_error: bool = False        # True when triage defaulted to "skip" due to parse failure


class BackendError(Exception):
    """Raised by LLMBackend on unrecoverable failure (auth, connection, etc.)."""


class LLMBackend(ABC):
    """
    Knows how to send a (system, user) prompt to an LLM and return raw text.
    Has no knowledge of papers, scoring, or prompt construction.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'claude:claude-haiku-4-5-20251001'"""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send prompt pair to the LLM, return the raw text response.
        Raises BackendError on unrecoverable failure.
        """


class EvaluationStrategy(ABC):
    """
    Knows how to build prompts for paper relevance evaluation
    and parse raw LLM responses into an EvaluationResult.
    Has no knowledge of which backend is being used.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'relevance_json'"""

    @abstractmethod
    def build_prompts(self, paper: Paper, interest_profile: str) -> tuple[str, str]:
        """Return (system_prompt, user_prompt)."""

    @abstractmethod
    def parse_response(self, raw_response: str) -> EvaluationResult:
        """
        Parse raw LLM output into a structured EvaluationResult.
        MUST NOT raise — return EvaluationResult(triage='skip', parse_error=True) on failure.
        """


class Evaluator(ABC):
    """
    The interface the pipeline calls.
    Implementations compose a backend with a strategy (or stand alone, like keyword).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate(self, paper: Paper, interest_profile: str) -> EvaluationResult:
        """
        Score a paper against the interest profile.
        Does NOT persist anything — the pipeline owns DB writes.
        """
