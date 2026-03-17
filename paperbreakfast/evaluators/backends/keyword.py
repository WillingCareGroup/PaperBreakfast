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
    r"stem cell mobiliz", r"engraftment", r"self-renewal",
    # Cell therapy
    r"\bCAR.T\b", r"chimeric antigen receptor", r"\bCAR.NK\b",
    r"cell therapy", r"cellular therapy", r"adoptive cell",
    r"allogeneic", r"off.the.shelf", r"\biPSC\b", r"induced pluripotent",
    # Manufacturing / engineering
    r"gene editing", r"\bCRISPR\b", r"base editing", r"prime editing",
    r"lentiviral", r"retroviral", r"\bAAV\b", r"viral vector", r"gene therapy",
    r"gene correction", r"GMP", r"manufacturing",
    # Clinical / disease
    r"\bHSCT\b", r"bone marrow transplant", r"sickle cell", r"thalassemia",
    r"\bAML\b", r"\bALL\b", r"\bMDS\b", r"leukemia", r"lymphoma",
    # AI / protein design
    r"protein design", r"de novo protein", r"AlphaFold", r"RFdiffusion",
    r"ProteinMPNN", r"ESMFold", r"foundation model",
]

NEGATIVE_TERMS = [
    r"epidemiology", r"observational study", r"population.based",
    r"cardiovascular(?!.*stem)", r"cardiac(?!.*stem)",
]


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

        if positive_hits:
            display = list(dict.fromkeys(positive_hits))[:5]  # deduplicated, ordered
            reasoning = f"Matched {len(set(positive_hits))} relevant terms: {', '.join(display)}."
        else:
            reasoning = "No relevant keywords matched."

        return EvaluationResult(
            score=score,
            reasoning=reasoning,
            evaluator_name=self.name,
        )
