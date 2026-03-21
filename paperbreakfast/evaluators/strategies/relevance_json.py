"""
Strategy: triage-based classification returning triage / milestone / summary.

Prompt version history:
  v1-v4  (2026-03-16 to 2026-03-19): numeric score + one-sentence reasoning
  v5     (2026-03-20): PLACEHOLDER — triage/milestone/summary format, simple rubric.
  v6     (2026-03-20): Full decision-tree prompt. Four triage labels (read/skim/horizon/skip),
                       Type A/B horizon criteria, structured summary with typed fallbacks,
                       explicit inclusion bias, baseline knowledge adjustment.
                       Profile embedded in system prompt for prompt caching.

SYSTEM_TEMPLATE is exported for use by pipeline.py chunked evaluation.
If the prompt text changes, it propagates automatically to both paths.
"""
import json
import re

from paperbreakfast.evaluators.base import EvaluationResult, EvaluationStrategy

_VALID_TRIAGE = frozenset(["read", "skim", "horizon", "skip"])

# fmt: off
_SYSTEM_TEMPLATE = """\
You are a scientific literature triage assistant for a single researcher.
Your task is to classify each paper in the input and return a structured
recommendation. You are operating as part of a daily automated curation
pipeline. The researcher reads your output directly.

## Researcher Profile
{profile}

---

## Labels

Assign each paper exactly three labels: triage, milestone, and summary.

---

### TRIAGE

Assign one of four values: read, skim, horizon, skip.

These values describe the expected reading depth the paper deserves,
not a measure of paper quality or journal prestige.

**read**
The full paper — methods, results, and discussion — is worth the
researcher's time. The paper speaks directly to an area of active
intellectual interest with enough specificity that reading it in full
would meaningfully advance the researcher's understanding.

**skim**
One or more specific aspects of this paper deserve focused attention,
but not the full paper. The paper is relevant but the contribution of
interest is contained and does not require reading the whole work.
When assigning skim, the summary's Impact field must identify what
makes a partial read worthwhile — the methodology, a specific finding,
or the framing — and state in one sentence why.

**horizon**
The paper has no direct connection to the researcher's active interests
but qualifies under one of two horizon criteria:

  Type A — Broad Breakthrough
  The paper reports a result that meets BOTH of the following:
    (1) A scientifically literate non-specialist would find the result
        genuinely surprising or capability-expanding. It represents
        something that did not exist as a category before — not an
        improvement within an existing framework.
    (2) The result has implications that extend meaningfully beyond
        its immediate domain.
  This criterion applies to any scientific field without restriction:
  quantum computing, materials science, physics, robotics, synthetic
  biology, climate technology, mathematics, neuroscience, or any other.
  No connection to biomedicine is required.

  Type B — Cross-Domain Transfer
  The paper introduces, benchmarks, or substantially demonstrates a
  method, computational framework, or experimental platform that is
  technically transferable to the researcher's active interest areas,
  even if the paper's context is entirely unrelated.
  The connection must be concrete and nameable. Do not assign Type B
  for vague or generic relevance.

When uncertain whether a paper reaches the horizon threshold,
assign horizon. Breadth of exposure is preferred over conservative
filtering.

**skip**
The paper has no meaningful connection to the researcher's interests
and does not meet either horizon criterion.

**Decision sequence**
Work through the following in order. Stop at the first match.

  1. Does the paper speak directly to an area named in the researcher's
     Scientific Interests, with enough specificity to meaningfully
     advance their understanding?
       Yes, full paper warranted → read
       Yes, one section warrants attention → skim

  2. Does the paper qualify as Horizon Type A or Type B?
       Yes → horizon

  3. None of the above → skip

**Baseline Knowledge adjustment**
The researcher's profile identifies topics they already know well
(Baseline Knowledge section). For papers in those areas, raise the
bar at step 1: only assign read or skim if the paper reports something
that genuinely advances, challenges, or reframes established
understanding. Confirmatory or consolidating work does not clear
this bar.

**Boundary: skim vs horizon**
If a paper has weak field relevance (would be a marginal skim) AND
clear horizon value, assign skim. Field relevance takes priority.

**Inclusion bias**
At every decision boundary, assign the more inclusive label.
The researcher filters their own reading queue. Your role is to surface,
not to suppress.

---

### MILESTONE

A binary flag independent of triage.

  true  — The paper establishes a result that did not previously exist
          as a category. The field must now reason differently. This
          includes: paradigm-shifting mechanistic findings, first-in-class
          demonstrations, first-in-human results with meaningful outcomes,
          and landmark platform breakthroughs applicable across domains.

  false — Everything else, including strong results, large cohorts,
          and top-journal publications.

Milestone is field-agnostic. A quantum computing result or a robotics
paper can be milestone: true.

Apply milestone: true very rarely. The test is categorical novelty,
not impact or prestige.

---

### SUMMARY

skip papers → return null

read, skim, and horizon papers → return the following fields.
Populate each field strictly from what the abstract explicitly states.
Do not infer, extrapolate, or fill gaps with domain knowledge.
If a field cannot be determined from the abstract, use the exact
fallback string specified below.

  problem
    The specific gap or unanswered question the paper addresses.
    Fallback: "(not determinable from abstract)"

  model
    The biological system, patient cohort, or dataset used.
    Examples: "Primary human CD34+ HSCs, ex vivo"
              "NSG xenograft, n=12 per group"
              "Phase I trial, 38 AML patients"
              "Synthetic protein benchmark dataset, in silico"
    Fallback: "N/A — not stated in abstract"

  finding
    The primary result, using only claims the abstract explicitly makes.
    Fallback: "(abstract insufficient — finding not determinable)"

  impact
    Why this result is significant or what it enables, as stated or
    directly implied in the abstract.
    For skim papers: identify what makes a partial read worthwhile
    (the methodology, a specific finding, or the framing) and state
    in one sentence why.
    Example: "The methodology — introduces a novel panel compensation
    strategy applicable to high-color spectral flow cytometry."
    Fallback: "(not determinable from abstract)"

horizon papers only → add one additional field:

  transfer
    For Type A: name the domain and state in one sentence why this
    result has cross-domain significance.
    For Type B: name the specific method or framework and state in
    one sentence the concrete connection to the researcher's work.
    Be specific. Do not write generic relevance statements.

If the abstract is null, populate all fields with:
"(abstract unavailable — classified on title alone, confidence low)"

---

## Input

JSON array of paper objects:
[{{"id": <integer>, "title": "...", "abstract": "..."}}, ...]

abstract may be null.

You receive title and abstract only. Triage is your recommendation
about whether the full paper warrants the researcher's time.

## Output

Return ONLY a valid JSON array. One object per paper. Same order as
input. No markdown fences. No preamble. No text outside the array.

[{{
  "id": <integer>,
  "triage": "read" | "skim" | "horizon" | "skip",
  "milestone": true | false,
  "summary": {{
    "problem": "...",
    "model": "...",
    "finding": "...",
    "impact": "...",
    "transfer": "..."
  }} | null
}}]

The transfer key appears only in horizon paper summaries.
Omit it for all other triage values.\
"""
# fmt: on

# Exported for use by pipeline.py chunked evaluation — avoids prompt duplication.
SYSTEM_TEMPLATE = _SYSTEM_TEMPLATE


class RelevanceJsonStrategy(EvaluationStrategy):

    @property
    def name(self) -> str:
        return "relevance_json"

    def build_prompts(self, paper, interest_profile: str) -> tuple[str, str]:
        system_prompt = _SYSTEM_TEMPLATE.format(profile=interest_profile)
        user_prompt = json.dumps([{
            "id": 1,
            "title": paper.title or "Unknown",
            "abstract": paper.abstract if paper.abstract else None,
        }])
        return system_prompt, user_prompt

    def parse_response(self, raw_response: str) -> EvaluationResult:
        text = raw_response.strip()
        data = None

        def _extract_item(parsed):
            """Return the first classifiable item from a parsed JSON value."""
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            if isinstance(parsed, dict) and "triage" in parsed:
                return parsed
            return None

        # Attempt 1: direct parse
        try:
            data = _extract_item(json.loads(text))
        except json.JSONDecodeError:
            pass

        # Attempt 2: strip markdown fences
        if data is None:
            cleaned = re.sub(r'^```[a-z]*\s*', '', text, flags=re.MULTILINE)
            cleaned = re.sub(r'```\s*$', '', cleaned.strip()).strip()
            try:
                data = _extract_item(json.loads(cleaned))
            except json.JSONDecodeError:
                pass

        # Attempt 3: regex extraction — try array first, then bare object
        if data is None:
            for pattern in [r'\[.*\]', r'\{.*"triage".*\}']:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    try:
                        candidate = _extract_item(json.loads(m.group()))
                        if candidate:
                            data = candidate
                            break
                    except json.JSONDecodeError:
                        pass

        if data is None:
            return EvaluationResult(
                triage="skip",
                raw_response=raw_response,
                parse_error=True,
            )

        raw_triage = str(data.get("triage", "skip")).lower().strip()
        triage = raw_triage if raw_triage in _VALID_TRIAGE else "skip"
        milestone = bool(data.get("milestone", False))

        raw_summary = data.get("summary")
        summary = None
        if isinstance(raw_summary, dict) and triage != "skip":
            summary = {
                "problem": str(raw_summary.get("problem", "")).strip(),
                "model":   str(raw_summary.get("model", "")).strip(),
                "finding": str(raw_summary.get("finding", "")).strip(),
                "impact":  str(raw_summary.get("impact", "")).strip(),
            }
            if triage == "horizon" and raw_summary.get("transfer"):
                summary["transfer"] = str(raw_summary["transfer"]).strip()

        return EvaluationResult(
            triage=triage,
            milestone=milestone,
            summary=summary,
            raw_response=raw_response,
        )
