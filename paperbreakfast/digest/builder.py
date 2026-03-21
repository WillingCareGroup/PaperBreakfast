import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from jinja2 import Environment, FileSystemLoader

# Topic tag definitions — matched against title + abstract (case-insensitive)
_TAG_PATTERNS: dict[str, list[str]] = {
    "HSC/HSPC": [
        r"\bHSC\b", r"\bHSPC\b", r"hematopoietic stem", r"hematopoietic progenitor",
        r"stem cell expansion", r"ex vivo expansion", r"cord blood",
        r"self-renewal", r"engraftment", r"stem cell mobiliz",
    ],
    "CAR-T": [
        r"\bCAR[-\s]T\b", r"chimeric antigen receptor.*T.cell",
        r"T.cell.*chimeric antigen",
    ],
    "CAR-NK": [
        r"\bCAR[-\s]NK\b", r"chimeric antigen receptor.*NK",
        r"NK.*chimeric antigen",
    ],
    "Gene Editing": [
        r"\bCRISPR\b", r"\bCas9\b", r"base edit", r"prime edit",
    ],
    "Gene Therapy": [
        r"lentiviral", r"retroviral", r"\bAAV\b", r"viral vector",
        r"gene therapy", r"gene correction", r"gene transfer",
    ],
    "iPSC": [
        r"\biPSC\b", r"induced pluripotent",
    ],
    "Allogeneic": [
        r"allogeneic", r"off.the.shelf",
    ],
    "HSCT": [
        r"\bHSCT\b", r"hematopoietic stem cell transplant",
        r"bone marrow transplant", r"stem cell transplant",
    ],
    "Manufacturing": [
        r"\bGMP\b", r"good manufacturing", r"bioreactor",
        r"scale.up", r"scalable.*manufactur", r"manufactur.*cell",
    ],
    "AI/Protein Design": [
        r"protein design", r"de novo protein", r"\bAlphaFold\b",
        r"\bRFdiffusion\b", r"\bProteinMPNN\b", r"\bESMFold\b",
        r"foundation model", r"machine learning.*protein",
    ],
}

_TRIAGE_ORDER = {"read": 0, "horizon": 1, "skim": 2}


def _get_tags(paper) -> list[str]:
    text = f"{paper.title or ''} {paper.abstract or ''}"
    tags = [
        tag
        for tag, patterns in _TAG_PATTERNS.items()
        if any(re.search(p, text, re.IGNORECASE) for p in patterns)
    ]
    if paper.milestone:
        if "Milestone" not in tags:
            tags.append("Milestone")
    return tags


def _parse_summary(paper) -> dict | None:
    if not paper.summary:
        return None
    try:
        return json.loads(paper.summary)
    except (json.JSONDecodeError, TypeError):
        return None


def _make_proxy_filter(proxy_base: str | None):
    """Return a Jinja2 filter that rewrites URLs through an EZproxy host."""
    def proxy_url(url: str) -> str:
        if not proxy_base or not url:
            return url
        try:
            parsed = urlparse(url)
            proxy_host = parsed.netloc.replace(".", "-") + "." + proxy_base
            return urlunparse(parsed._replace(netloc=proxy_host))
        except Exception:
            return url
    return proxy_url


@dataclass
class DigestPayload:
    html: str
    paper_count: int
    papers: list  # list[Paper]


class DigestBuilder:

    def __init__(self, proxy_base_url: str | None = None):
        template_dir = Path(__file__).parent.parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )
        self._env.filters["proxy_url"] = _make_proxy_filter(proxy_base_url)

    def build(
        self,
        papers: list,
        poll_result=None,
        eval_summary=None,
        total_papers_today: int = 0,
        feeds_configured: int = 0,
    ) -> DigestPayload:
        read_papers    = [p for p in papers if p.triage == "read"]
        horizon_papers = [p for p in papers if p.triage == "horizon"]
        skim_papers    = [p for p in papers if p.triage == "skim"]

        paper_tags = {p.guid: _get_tags(p) for p in papers}
        paper_summaries = {p.guid: _parse_summary(p) for p in papers}

        journal_count = len({p.journal for p in papers})

        feed_errors = list(poll_result.errors) if poll_result else []
        eval_errors = getattr(eval_summary, "error_messages", []) if eval_summary else []

        template = self._env.get_template("digest.html.jinja2")
        html = template.render(
            date=datetime.utcnow().strftime("%B %d, %Y"),
            recommended_count=len(papers),
            total_papers_today=total_papers_today,
            journal_count=journal_count,
            read_count=len(read_papers),
            horizon_count=len(horizon_papers),
            skim_count=len(skim_papers),
            read_papers=read_papers,
            horizon_papers=horizon_papers,
            skim_papers=skim_papers,
            paper_tags=paper_tags,
            paper_summaries=paper_summaries,
            feeds_ok=poll_result.feeds_ok if poll_result else None,
            feeds_total=poll_result.feeds_total if poll_result else (feeds_configured or None),
            feed_errors=feed_errors,
            eval_errors=eval_errors,
            eval_errors_count=eval_summary.errors if eval_summary else 0,
        )

        return DigestPayload(html=html, paper_count=len(papers), papers=papers)
