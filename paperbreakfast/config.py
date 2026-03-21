"""
Configuration loader.

Users edit config.yaml (copied from config.example.yaml).
Secrets (API keys, SMTP password) come exclusively from .env — never from YAML.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class FeedConfig:
    url: str
    name: str
    group: str = "general"
    enabled: bool = True


@dataclass
class BackendConfig:
    type: str                            # "claude" | "openai_compat" | "keyword"
    model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.1
    max_tokens: int = 512
    base_url: Optional[str] = None       # openai_compat only


@dataclass
class StrategyConfig:
    type: str                            # "relevance_json" | "chain_of_thought"


@dataclass
class EvaluatorConfig:
    backend: BackendConfig
    strategy: StrategyConfig
    score_threshold: float = 0.6
    use_batch: bool = False   # True = Anthropic Batch API (50% cost, async ~minutes)
    chunk_size: int = 25      # Papers per LLM call (1 = sequential, 25 = default efficient)


@dataclass
class EmailConfig:
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    from_addr: str = ""
    to_addrs: list = field(default_factory=list)
    send_hour: int = 8


@dataclass
class SchedulerConfig:
    poll_interval_hours: int = 2


@dataclass
class AppConfig:
    feeds: list
    evaluator: EvaluatorConfig
    email: EmailConfig
    scheduler: SchedulerConfig
    interest_profile: str
    db_path: str = "paperbreakfast.db"
    proxy_base_url: Optional[str] = None   # e.g. "libproxy2.usc.edu"
    # Secrets — loaded from env, never stored in YAML
    anthropic_api_key: Optional[str] = None
    smtp_password: Optional[str] = None
    openai_compat_api_key: str = "local"
    openai_compat_base_url: str = "http://localhost:1234/v1"


def load_config(
    config_path: str = "config.yaml",
    feeds_path: str = "feeds.yaml",
) -> AppConfig:
    load_dotenv()

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Copy config.example.yaml to config.yaml and fill in your settings."
        )

    with open(config_file) as f:
        raw = yaml.safe_load(f) or {}

    # Feeds
    feeds_file = Path(feeds_path)
    if not feeds_file.exists():
        raise FileNotFoundError(f"Feeds file not found: {feeds_path}")
    with open(feeds_file) as f:
        feeds_raw = yaml.safe_load(f) or {}
    feeds = [FeedConfig(**feed) for feed in feeds_raw.get("feeds", [])]

    # Evaluator
    ev = raw.get("evaluator", {})
    backend_raw = ev.get("backend", {"type": "keyword"})
    strategy_raw = ev.get("strategy", {"type": "relevance_json"})
    evaluator = EvaluatorConfig(
        backend=BackendConfig(**backend_raw),
        strategy=StrategyConfig(**strategy_raw),
        score_threshold=float(ev.get("score_threshold", 0.6)),
        use_batch=bool(ev.get("use_batch", False)),
        chunk_size=int(ev.get("chunk_size", 25)),
    )

    # Email
    em = raw.get("email", {})
    to_addrs = em.get("to_addrs", [])
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    email = EmailConfig(
        smtp_host=em.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(em.get("smtp_port", 587)),
        smtp_user=em.get("smtp_user", ""),
        from_addr=em.get("from_addr", ""),
        to_addrs=to_addrs,
        send_hour=int(em.get("send_hour", 8)),
    )

    # Scheduler
    sc = raw.get("scheduler", {})
    scheduler = SchedulerConfig(
        poll_interval_hours=int(sc.get("poll_interval_hours", 2)),
    )

    # Interest profile
    profile_path = raw.get("interest_profile_path", "profile.md")
    profile_file = Path(profile_path)
    if profile_file.exists():
        interest_profile = profile_file.read_text(encoding="utf-8")
    else:
        interest_profile = raw.get("interest_profile", "")

    if not interest_profile.strip():
        import warnings
        warnings.warn(
            f"Interest profile is empty. "
            f"Create '{profile_path}' or set 'interest_profile:' in config.yaml. "
            "LLM evaluators will perform poorly without it.",
            stacklevel=2,
        )

    return AppConfig(
        feeds=feeds,
        evaluator=evaluator,
        email=email,
        scheduler=scheduler,
        interest_profile=interest_profile,
        db_path=raw.get("db_path", "paperbreakfast.db"),
        proxy_base_url=raw.get("proxy_base_url") or None,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        smtp_password=os.environ.get("SMTP_PASSWORD"),
        openai_compat_api_key=os.environ.get("OPENAI_COMPAT_API_KEY", "local"),
        openai_compat_base_url=os.environ.get(
            "OPENAI_COMPAT_BASE_URL",
            evaluator.backend.base_url or "http://localhost:1234/v1",
        ),
    )
