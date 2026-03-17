"""
Strategy: step-by-step reasoning before scoring.

Produces richer, more auditable reasoning. Slightly more tokens / slower.
Good for: diagnosing why certain papers are (or aren't) being recommended,
tuning the interest profile, or when using a smaller local model that
benefits from explicit reasoning steps.
"""
import re

from paperbreakfast.evaluators.base import EvaluationResult, EvaluationStrategy

# Prompt version history — update when changing the prompt text, not the code
# v1 (2026-03-16): initial — step-by-step reasoning, ends with SCORE: float
SYSTEM_PROMPT = """\
You are a scientific literature curator. Evaluate whether a research paper is \
relevant to the researcher's interest profile.

Think through the evaluation step-by-step, then end your response with exactly:
SCORE: <float between 0.0 and 1.0>

Scoring guide:
  0.0–0.2  Completely irrelevant
  0.2–0.4  Tangentially related
  0.4–0.6  Somewhat relevant
  0.6–0.8  Relevant and interesting
  0.8–1.0  Directly in core research area — highly recommended\
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

Evaluate step-by-step, then end with SCORE: <0.0–1.0>\
"""


class ChainOfThoughtStrategy(EvaluationStrategy):

    @property
    def name(self) -> str:
        return "chain_of_thought"

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
        match = re.search(r'SCORE:\s*([0-9]*\.?[0-9]+)', raw_response, re.IGNORECASE)
        if not match:
            return EvaluationResult(
                score=0.0,
                reasoning="No SCORE line found in LLM response.",
                raw_response=raw_response,
                parse_error=True,
            )

        score = float(match.group(1))
        score = max(0.0, min(1.0, score))

        # Everything before SCORE: is the reasoning
        reasoning = raw_response[: match.start()].strip()
        if not reasoning:
            reasoning = "No reasoning provided."

        return EvaluationResult(
            score=score,
            reasoning=reasoning,
            raw_response=raw_response,
        )
