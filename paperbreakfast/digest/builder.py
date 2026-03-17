from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


@dataclass
class DigestPayload:
    html: str
    paper_count: int
    papers: list  # list[Paper]


class DigestBuilder:

    def __init__(self, score_threshold: float = 0.6):
        self.score_threshold = score_threshold
        template_dir = Path(__file__).parent.parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )

    def build(self, papers: list) -> DigestPayload:
        # Group by journal, sort each group by score desc
        by_journal: dict = defaultdict(list)
        for p in papers:
            by_journal[p.journal].append(p)

        # Sort journals so highest-average-scoring journal appears first
        sorted_journals = sorted(
            by_journal.items(),
            key=lambda kv: max(p.score or 0.0 for p in kv[1]),
            reverse=True,
        )

        template = self._env.get_template("digest.html.jinja2")
        html = template.render(
            date=datetime.utcnow().strftime("%B %d, %Y"),
            total_papers=len(papers),
            journals=sorted_journals,
            score_threshold=self.score_threshold,
        )

        return DigestPayload(html=html, paper_count=len(papers), papers=papers)
