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

    # Evaluation
    score = FloatField(null=True)         # 0.0–1.0, null = not yet evaluated
    reasoning = TextField(null=True)
    evaluator_name = CharField(max_length=128, null=True)
    evaluated_at = DateTimeField(null=True)

    # Digest tracking
    included_in_digest = BooleanField(default=False)
    digest_sent_at = DateTimeField(null=True)

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
    logger.info(f"Database ready: {db_path}")
    return db


def get_unevaluated_papers() -> list:
    return list(Paper.select().where(Paper.score.is_null()))


def get_papers_for_digest(since: datetime, score_threshold: float) -> list:
    return list(
        Paper.select()
        .where(
            (Paper.score >= score_threshold)
            & (Paper.included_in_digest == False)  # noqa: E712
            & (Paper.fetched_at >= since)
        )
        .order_by(Paper.score.desc())
    )
