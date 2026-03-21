"""
RSS feed poller.

Responsibilities:
  - Fetch all configured feeds via feedparser
  - Extract paper metadata (title, abstract, authors, date, URL)
  - Deduplicate against the database using Paper.get_or_create(guid=...)
  - Return a PollResult summary; never raise on per-feed errors
"""
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import feedparser

from paperbreakfast.config import FeedConfig
from paperbreakfast.models.db import Paper

logger = logging.getLogger(__name__)


@dataclass
class PollResult:
    feeds_total: int = 0    # total enabled feeds attempted
    feeds_ok: int = 0       # feeds that returned without error
    total_fetched: int = 0
    total_new: int = 0
    errors: list = field(default_factory=list)

    @property
    def feeds_polled(self) -> int:
        """Back-compat alias."""
        return self.feeds_ok


class FeedPoller:

    def __init__(self, feeds: list):
        self._feeds = [f for f in feeds if f.enabled]

    def poll_all(self) -> PollResult:
        result = PollResult(feeds_total=len(self._feeds))
        for feed in self._feeds:
            try:
                fetched, new = self._poll_one(feed)
                result.feeds_ok += 1
                result.total_fetched += fetched
                result.total_new += new
                if new:
                    logger.info(f"  [{feed.name}] {new} new / {fetched} total")
                else:
                    logger.debug(f"  [{feed.name}] {fetched} fetched, none new")
            except Exception as exc:
                msg = f"[{feed.name}] {exc}"
                logger.error(f"Error polling '{feed.name}' ({feed.url}): {exc}")
                result.errors.append(msg)
        return result

    def _poll_one(self, feed: FeedConfig) -> tuple[int, int]:
        parsed = feedparser.parse(feed.url)

        if parsed.get("bozo") and parsed.get("bozo_exception"):
            logger.warning(
                f"[{feed.name}] Possibly malformed feed: {parsed.bozo_exception}"
            )

        fetched = 0
        new = 0

        for entry in parsed.entries:
            fetched += 1
            guid = self._extract_guid(entry)

            _, created = Paper.get_or_create(
                guid=guid,
                defaults={
                    "title": self._extract_title(entry),
                    "abstract": self._extract_abstract(entry),
                    "url": entry.get("link", ""),
                    "journal": feed.name,
                    "authors": self._extract_authors(entry),
                    "published_date": self._extract_date(entry),
                    "fetched_at": datetime.utcnow(),
                    "doi": self._extract_doi(entry),
                },
            )
            if created:
                new += 1

        return fetched, new

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _extract_guid(self, entry) -> str:
        guid = entry.get("id") or entry.get("link")
        if guid:
            return guid
        # Stable fallback: sha256 of title (Python's hash() is NOT stable across runs)
        title = entry.get("title", "")
        return "sha256:" + hashlib.sha256(title.encode()).hexdigest()[:24]

    def _extract_title(self, entry) -> str:
        return self._strip_html(entry.get("title", "Untitled")).strip()

    def _extract_abstract(self, entry) -> str:
        raw = ""
        # feedparser normalizes most content into entry.summary
        if entry.get("summary"):
            raw = entry.summary
        elif hasattr(entry, "content") and entry.content:
            raw = entry.content[0].get("value", "")
        elif entry.get("description"):
            raw = entry.description
        return self._strip_html(raw).strip()

    def _extract_doi(self, entry) -> str | None:
        for field in ("dc_identifier", "prism_doi"):
            val = entry.get(field, "")
            if val:
                val = val.replace("doi:", "").strip().rstrip(".,;)")
                if val.startswith("10."):
                    return val
        return None

    def _extract_authors(self, entry) -> str:
        if entry.get("authors"):
            names = [a.get("name", "") for a in entry.authors if a.get("name")]
            return ", ".join(names)
        if entry.get("author"):
            return entry.author
        return ""

    def _extract_date(self, entry) -> datetime:
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            val = entry.get(attr)
            if val:
                try:
                    return datetime.fromtimestamp(time.mktime(val))
                except (OverflowError, OSError, ValueError):
                    pass
        return datetime.utcnow()

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
