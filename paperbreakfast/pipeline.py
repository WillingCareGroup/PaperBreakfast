"""
Pipeline — orchestrates one full run of the system.

Each stage is independently callable so the scheduler can run them
at different cadences (poll every 2h, digest once daily).
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from paperbreakfast.config import AppConfig
from paperbreakfast.digest.builder import DigestBuilder
from paperbreakfast.digest.mailer import Mailer
from paperbreakfast.evaluators.base import BackendError
from paperbreakfast.evaluators.factory import build_evaluator
from paperbreakfast.feeds.poller import FeedPoller, PollResult
from paperbreakfast.models.db import (
    Paper,
    get_papers_for_digest,
    get_unevaluated_papers,
)

logger = logging.getLogger(__name__)

# Delay between LLM calls to avoid hammering the API
_EVAL_INTER_CALL_DELAY = 0.4  # seconds


@dataclass
class EvaluationSummary:
    evaluated: int = 0
    errors: int = 0


@dataclass
class DigestResult:
    paper_count: int = 0
    sent: bool = False
    error: str = ""


class Pipeline:

    def __init__(self, config: AppConfig):
        self.config = config
        self._poller = FeedPoller(config.feeds)
        self._evaluator = build_evaluator(config)
        self._builder = DigestBuilder(score_threshold=config.evaluator.score_threshold)
        self._mailer = Mailer(config.email, config.smtp_password or "")
        logger.info(f"Pipeline ready — evaluator: {self._evaluator.name}")

    # ── Public stages ────────────────────────────────────────────────────────

    def run_poll(self) -> PollResult:
        logger.info("Polling RSS feeds...")
        result = self._poller.poll_all()
        logger.info(
            f"Poll done: {result.total_new} new papers across {result.feeds_polled} feeds"
            + (f" ({len(result.errors)} errors)" if result.errors else "")
        )
        return result

    def run_evaluation(self) -> EvaluationSummary:
        papers = get_unevaluated_papers()
        if not papers:
            logger.info("No papers to evaluate.")
            return EvaluationSummary()

        logger.info(f"Evaluating {len(papers)} papers with {self._evaluator.name}...")
        summary = EvaluationSummary()

        for paper in papers:
            try:
                result = self._evaluator.evaluate(paper, self.config.interest_profile)
                (
                    Paper.update(
                        score=result.score,
                        reasoning=result.reasoning,
                        evaluator_name=result.evaluator_name,
                        evaluated_at=datetime.utcnow(),
                    )
                    .where(Paper.guid == paper.guid)
                    .execute()
                )
                summary.evaluated += 1
                if result.parse_error:
                    logger.warning(
                        f"Parse error evaluating '{paper.title[:60]}' — "
                        f"scored 0.0, raw: {result.raw_response[:80]!r}"
                    )
                else:
                    flag = "**" if result.score >= self.config.evaluator.score_threshold else "  "
                    logger.debug(f"{flag} [{result.score:.2f}] {paper.title[:80]}")

                if _EVAL_INTER_CALL_DELAY > 0:
                    time.sleep(_EVAL_INTER_CALL_DELAY)

            except BackendError as exc:
                logger.error(f"Backend error on '{paper.title[:60]}': {exc}")
                summary.errors += 1
            except Exception as exc:
                logger.error(f"Unexpected error on '{paper.title[:60]}': {exc}")
                summary.errors += 1

        logger.info(
            f"Evaluation done: {summary.evaluated} evaluated, {summary.errors} errors"
        )
        return summary

    def run_digest(self) -> DigestResult:
        since = datetime.utcnow() - timedelta(days=1)
        papers = get_papers_for_digest(since, self.config.evaluator.score_threshold)

        if not papers:
            logger.info("No new recommended papers for digest.")
            return DigestResult(paper_count=0, sent=False)

        logger.info(f"Building digest with {len(papers)} papers...")
        payload = self._builder.build(papers)
        sent = self._mailer.send(payload)

        if sent:
            (
                Paper.update(
                    included_in_digest=True,
                    digest_sent_at=datetime.utcnow(),
                )
                .where(Paper.guid.in_([p.guid for p in papers]))
                .execute()
            )

        return DigestResult(paper_count=len(papers), sent=sent)

    def run_full(self):
        """Convenience: poll + evaluate + digest in sequence."""
        poll = self.run_poll()
        ev = self.run_evaluation()
        digest = self.run_digest()
        return poll, ev, digest
