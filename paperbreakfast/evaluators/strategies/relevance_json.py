"""
Strategy: ask the LLM to return a strict JSON object with score + reasoning.

Fast, structured, easy to parse. Best for high-throughput evaluation.
"""
import json
import re

from paperbreakfast.evaluators.base import EvaluationResult, EvaluationStrategy

# Prompt version history — update when changing the prompt text, not the code
# v1 (2026-03-16): initial — structured JSON, 5-band scoring guide, strict 0.8+ threshold
SYSTEM_PROMPT = """\
You are a scientific literature curator. Evaluate whether a research paper is \
relevant to the researcher's interest profile.

Respond with ONLY a JSON object — no markdown, no explanation outside the JSON:
{"score": <float 0.0–1.0>, "reasoning": "<one concise sentence>"}

Scoring guide:
  0.0–0.2  Completely irrelevant
  0.2–0.4  Tangentially related, unlikely to be useful
  0.4–0.6  Somewhat relevant, worth knowing about
  0.6–0.8  Relevant and likely interesting
  0.8–1.0  Directly in the core research area — highly recommended

Be strict: reserve 0.8+ for papers that directly advance the researcher's \
specific focus areas.\
"""

USER_TEMPLATE = """\
## Researcher Interest Profile
{interest_profile}

## Paper
**Title:** {title}
**Journal:** {journal}
**Authors:** {authors}
**Abstract:**
{abstract}

Evaluate relevance and respond with only the JSON object.\
"""


class RelevanceJsonStrategy(EvaluationStrategy):

    @property
    def name(self) -> str:
        return "relevance_json"

    def build_prompts(self, paper, interest_profile: str) -> tuple[str, str]:
        user_prompt = USER_TEMPLATE.format(
            interest_profile=interest_profile,
            title=paper.title or "Unknown",
            journal=paper.journal or "Unknown",
            authors=(paper.authors or "Unknown")[:200],
            abstract=(paper.abstract or "No abstract available.")[:2500],
        )
        return SYSTEM_PROMPT, user_prompt

    def parse_response(self, raw_response: str) -> EvaluationResult:
        text = raw_response.strip()
        data = None

        # Try direct parse
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try finding a JSON block inside the text
        if data is None:
            match = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if data is None:
            return EvaluationResult(
                score=0.0,
                reasoning="Could not parse LLM response as JSON.",
                raw_response=raw_response,
                parse_error=True,
            )

        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reasoning = str(data.get("reasoning", "")).strip()

        return EvaluationResult(
            score=score,
            reasoning=reasoning,
            raw_response=raw_response,
        )
