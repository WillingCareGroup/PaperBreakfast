"""
Keyword-based evaluator — no LLM required.

Useful for:
  - Testing the pipeline without API keys
  - Fast pre-filtering before a more expensive LLM pass
  - Baseline comparison against LLM evaluators

This is a standalone Evaluator (not a LLMBackend) because it bypasses
the strategy layer entirely.
"""
import re

from paperbreakfast.evaluators.base import EvaluationResult, Evaluator

# Terms scored in title (weight 2.0) and abstract (weight 1.0)
POSITIVE_TERMS = [
    # HSC / HSPC
    r"\bHSC\b", r"\bHSPC\b", r"hematopoietic stem", r"hematopoietic progenitor",
    r"stem cell expansion", r"ex vivo expansion", r"cord blood",
    r"stem cell mobiliz", r"engraftment", r"\bself-renewal\b",
    # Cell therapy
    r"\bCAR[-\s]T\b", r"chimeric antigen receptor", r"\bCAR[-\s]NK\b",
    r"cell therapy", r"cellular therapy", r"adoptive cell",
    r"allogeneic", r"off.the.shelf", r"\biPSC\b", r"induced pluripotent",
    # Manufacturing / engineering
    r"\bgene editing\b", r"\bCRISPR\b", r"base editing", r"prime editing",
    r"lentiviral", r"retroviral", r"\bAAV\b", r"viral vector", r"gene therapy",
    r"gene correction", r"\bGMP\b", r"manufacturing",
    # Clinical / disease
    r"\bHSCT\b", r"bone marrow transplant", r"sickle cell", r"thalassemia",
    r"\bAML\b", r"\bALL\b", r"\bMDS\b", r"leukemia", r"lymphoma",
    # AI / protein design
    r"protein design", r"de novo protein", r"\bAlphaFold\b", r"\bRFdiffusion\b",
    r"\bProteinMPNN\b", r"\bESMFold\b", r"foundation model",
]

NEGATIVE_TERMS = [
    r"epidemiology", r"observational study", r"population.based",
    r"cardiovascular(?!.*stem)", r"cardiac(?!.*stem)",
]

# Score thresholds for triage mapping
_READ_THRESHOLD = 0.8
_SKIM_THRESHOLD = 0.6


class KeywordEvaluator(Evaluator):

    @property
    def name(self) -> str:
        return "keyword"

    def evaluate(self, paper, interest_profile: str) -> EvaluationResult:
        title = paper.title.lower() if paper.title else ""
        abstract = paper.abstract.lower() if paper.abstract else ""

        positive_hits: list[str] = []
        for pattern in POSITIVE_TERMS:
            if re.search(pattern, title, re.IGNORECASE):
                positive_hits.append(pattern.replace(r"\b", "").replace("\\b", ""))
            elif re.search(pattern, abstract, re.IGNORECASE):
                positive_hits.append(pattern.replace(r"\b", "").replace("\\b", ""))

        negative_hits = [
            p for p in NEGATIVE_TERMS
            if re.search(p, title + " " + abstract, re.IGNORECASE)
        ]

        raw_score = len(set(positive_hits)) * 0.12
        raw_score -= len(set(negative_hits)) * 0.2
        score = max(0.0, min(1.0, raw_score))

        if score >= _READ_THRESHOLD:
            triage = "read"
        elif score >= _SKIM_THRESHOLD:
            triage = "skim"
        else:
            triage = "skip"

        summary = None
        if triage != "skip" and positive_hits:
            display = list(dict.fromkeys(positive_hits))[:5]
            summary = {
                "problem": "(keyword evaluation — no semantic analysis)",
                "model": "N/A — not stated in abstract",
                "finding": f"Matched {len(set(positive_hits))} relevant terms: {', '.join(display)}.",
                "impact": "(keyword evaluation — verify with LLM evaluator)",
            }

        return EvaluationResult(
            triage=triage,
            milestone=False,
            summary=summary,
            evaluator_name=self.name,
        )
