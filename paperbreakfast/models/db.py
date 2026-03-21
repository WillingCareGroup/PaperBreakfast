"""
Database models (peewee + SQLite).

The DatabaseProxy pattern lets us call init_db() once at startup with the
configured path, and all models will use that connection automatically.
"""
import logging
from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DatabaseProxy,
    DateTimeField,
    FloatField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

logger = logging.getLogger(__name__)

database_proxy = DatabaseProxy()


class BaseModel(Model):
    class Meta:
        database = database_proxy


class Paper(BaseModel):
    # Primary key: DOI or URL — used for deduplication across feed polls
    guid = CharField(primary_key=True, max_length=512)

    title = TextField()
    abstract = TextField(default="")
    url = TextField(default="")
    journal = CharField(max_length=256, default="")
    authors = TextField(default="")       # comma-separated string
    published_date = DateTimeField(null=True)
    fetched_at = DateTimeField(default=datetime.utcnow)

    # Evaluation — triage-based (replaces legacy score/reasoning)
    triage = CharField(max_length=16, null=True)   # "read" | "skim" | "horizon" | "skip" | null = not evaluated
    milestone = BooleanField(null=True)             # True = paradigm-shifting advance
    summary = TextField(null=True)                  # JSON: {problem, model, finding, impact}
    evaluator_name = CharField(max_length=128, null=True)
    evaluator_model = CharField(max_length=128, null=True)  # e.g. "claude-sonnet-4-6"
    evaluated_at = DateTimeField(null=True)

    # Legacy columns — kept for backward compat with pre-v2 data, not written by new code
    score = FloatField(null=True)
    reasoning = TextField(null=True)

    # Digest tracking
    included_in_digest = BooleanField(default=False)
    digest_sent_at = DateTimeField(null=True)

    # DOI — populated during fetch from dc_identifier; used for API enrichment
    doi = CharField(max_length=256, null=True)

    # Extracted by LLM during evaluation — null if not recognised
    institution = CharField(max_length=256, null=True)
    pi_name = CharField(max_length=256, null=True)

    # User relevance feedback — populated via `python main.py feedback`
    # Values: "good" (relevant, correctly surfaced) | "noise" (irrelevant, false positive)
    #         "missed" (relevant but scored below threshold) | null (not yet reviewed)
    user_feedback = CharField(max_length=16, null=True)

    class Meta:
        table_name = "papers"


class DigestRun(BaseModel):
    id = AutoField()
    sent_at = DateTimeField(default=datetime.utcnow)
    paper_count = IntegerField(default=0)
    success = BooleanField(default=False)
    error_message = TextField(null=True)

    class Meta:
        table_name = "digest_runs"



def init_db(db_path: str):
    """Create the SQLite database, bind it to the proxy, create tables."""
    db = SqliteDatabase(
        db_path,
        pragmas={"journal_mode": "wal", "foreign_keys": 1},
    )
    database_proxy.initialize(db)
    db.connect(reuse_if_open=True)
    db.create_tables([Paper, DigestRun], safe=True)
    # Lightweight migrations — add columns introduced after initial schema.
    # SQLite ignores "duplicate column" errors so we catch and continue.
    migrations = [
        "ALTER TABLE papers ADD COLUMN doi VARCHAR(256)",
        "ALTER TABLE papers ADD COLUMN triage VARCHAR(16)",
        "ALTER TABLE papers ADD COLUMN milestone BOOLEAN",
        "ALTER TABLE papers ADD COLUMN summary TEXT",
        "ALTER TABLE papers ADD COLUMN evaluator_model VARCHAR(128)",
    ]
    for stmt in migrations:
        try:
            db.execute_sql(stmt)
        except Exception:
            pass  # column already exists
    logger.info(f"Database ready: {db_path}")
    return db


def get_unevaluated_papers() -> list:
    return list(Paper.select().where(Paper.triage.is_null()))


def get_papers_for_digest(since: datetime) -> list:
    return list(
        Paper.select()
        .where(
            (Paper.triage.in_(["read", "skim", "horizon"]))
            & (Paper.included_in_digest == False)  # noqa: E712
            & (Paper.fetched_at >= since)
        )
    )


def get_papers_fetched_today() -> int:
    from datetime import date, time
    start = datetime.combine(date.today(), time.min)
    return Paper.select().where(Paper.fetched_at >= start).count()
