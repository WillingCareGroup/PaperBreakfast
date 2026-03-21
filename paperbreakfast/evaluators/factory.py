"""
Evaluator factory.

This is the only file that knows the full backend × strategy matrix.
Adding a new backend or strategy means:
  1. Write the new class in backends/ or strategies/
  2. Register it in BACKENDS or STRATEGIES below
  3. Done — no other file needs to change
"""
from paperbreakfast.evaluators.base import (
    EvaluationStrategy,
    Evaluator,
    EvaluationResult,
    LLMBackend,
)
from paperbreakfast.evaluators.backends.keyword import KeywordEvaluator


class CompositeEvaluator(Evaluator):
    """Combines any LLMBackend with any EvaluationStrategy."""

    def __init__(self, backend: LLMBackend, strategy: EvaluationStrategy):
        self._backend = backend
        self._strategy = strategy

    @property
    def name(self) -> str:
        return f"{self._backend.name}/{self._strategy.name}"

    @property
    def strategy(self):
        return self._strategy

    @property
    def backend(self):
        return self._backend

    def evaluate(self, paper, interest_profile: str) -> EvaluationResult:
        system_prompt, user_prompt = self._strategy.build_prompts(paper, interest_profile)
        raw = self._backend.complete(system_prompt, user_prompt)
        result = self._strategy.parse_response(raw)
        result.evaluator_name = self.name
        return result


# Registry lambdas receive (EvaluatorConfig, AppConfig) → instance
# Using lambdas keeps imports lazy (so missing optional deps don't fail at startup)

def _make_claude(ev_cfg, app_cfg):
    from paperbreakfast.evaluators.backends.claude import ClaudeBackend
    return ClaudeBackend(
        api_key=app_cfg.anthropic_api_key or "",
        model=ev_cfg.backend.model,
        temperature=ev_cfg.backend.temperature,
        max_tokens=ev_cfg.backend.max_tokens,
    )


def _make_openai_compat(ev_cfg, app_cfg):
    from paperbreakfast.evaluators.backends.openai_compat import OpenAICompatBackend
    return OpenAICompatBackend(
        base_url=app_cfg.openai_compat_base_url,
        api_key=app_cfg.openai_compat_api_key,
        model=ev_cfg.backend.model,
        temperature=ev_cfg.backend.temperature,
        max_tokens=ev_cfg.backend.max_tokens,
    )


BACKENDS = {
    "claude": _make_claude,
    "openai_compat": _make_openai_compat,
}

STRATEGIES = {
    "relevance_json": lambda: __import__(
        "paperbreakfast.evaluators.strategies.relevance_json",
        fromlist=["RelevanceJsonStrategy"],
    ).RelevanceJsonStrategy(),
    "chain_of_thought": lambda: __import__(
        "paperbreakfast.evaluators.strategies.chain_of_thought",
        fromlist=["ChainOfThoughtStrategy"],
    ).ChainOfThoughtStrategy(),
}


def build_evaluator(app_cfg) -> Evaluator:
    """
    Build the configured evaluator from AppConfig.

    Called once at pipeline startup. Validates the backend/strategy names
    early so misconfigurations surface before the first paper is evaluated.
    """
    ev_cfg = app_cfg.evaluator
    backend_type = ev_cfg.backend.type
    strategy_type = ev_cfg.strategy.type

    if backend_type == "keyword":
        return KeywordEvaluator()

    if backend_type not in BACKENDS:
        raise ValueError(
            f"Unknown evaluator backend '{backend_type}'. "
            f"Valid options: {sorted(BACKENDS.keys()) + ['keyword']}"
        )
    if strategy_type not in STRATEGIES:
        raise ValueError(
            f"Unknown evaluation strategy '{strategy_type}'. "
            f"Valid options: {sorted(STRATEGIES.keys())}"
        )

    backend = BACKENDS[backend_type](ev_cfg, app_cfg)
    strategy = STRATEGIES[strategy_type]()
    return CompositeEvaluator(backend, strategy)
