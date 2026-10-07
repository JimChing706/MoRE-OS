"""Settings loaded from environment variables or an explicit dict.

Lightweight alternative to pydantic-settings to keep dependencies minimal.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

try:
    from ..version import __version__
except ImportError:
    __version__ = "0.9.9"


def _load_dotenv() -> None:
    """Load .env file from project root if it exists (no-op if dotenv unavailable)."""
    try:
        from dotenv import load_dotenv as _ld

        # Walk upward from more_core/ to find .env
        candidate = Path(__file__).resolve().parent.parent
        while candidate != candidate.parent:
            env_file = candidate / ".env"
            if env_file.exists():
                _ld(env_file, override=False)
                return
            candidate = candidate.parent
    except ImportError:
        pass


_load_dotenv()


LLMProviderName = Literal[
    "ollama",
    "lmstudio",
    "openai",
    "anthropic",
    "custom",
    "deepseek",
    "azure",
    "google",
    "groq",
    "mistral",
    "cohere",
    "openrouter",
    "together",
    "xai",
    "sambanova",
    "fireworks",
    "perplexity",
    "cerebras",
    "huggingface",
    "replicate",
    "vllm",
    "llamacpp",
    "mock",
]


class LLMProviderConfig(BaseModel):
    name: str
    provider: LLMProviderName
    endpoint: str
    model: str
    api_key: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_s: int = 120


class Settings(BaseModel):
    """Platform-wide configuration.

    Industry-specific configuration should live in plugins, not here.
    """

    plugin_dir: str = "plugins"
    log_dir: str = "logs"

    # LLM providers and fallback order (names must match providers below).
    providers: list[LLMProviderConfig] = Field(default_factory=list)
    fallback_chain: list[str] = Field(default_factory=list)

    # Feature gates — *disabled by default* per G4.
    enable_evolution: bool = False  # L2 DGM
    enable_evolution_llm_variants: bool = False  # L2 uses LLM-driven variant proposal
    enable_metacognition: bool = False  # L5 HyperAgent self-modification
    enable_symbolic: bool = True  # L3 ontology/rule engine (safe default)

    # Pipeline overrides — map TaskType value -> list of LayerId values
    # e.g. {"nlp_task": ["L4", "L0"]} to skip symbolic + orchestration
    custom_pipelines: dict[str, list[str]] | None = None

    # Code generation — repo-aware context injection (repo map in L0 prompts)
    enable_codegen_context: bool = True

    # Code generation — best-of-k candidate validation. Default = 2: generates
    # two independent LLM generations, runs both through the sandbox, picks
    # the one that passes cleanly and cross-checks via differential agreement.
    # 1 = single generation (best-of-k disabled). Per-request override via
    # context["candidates"]. Capped at layers.l0_execution._MAX_CODE_CANDIDATES.
    codegen_candidates: int = 2

    # Code generation — multi-agent review panel (correctness/security/quality)
    # over the final code artifact. ON by default since Step-3 (P1 self-audit
    # gate); when a P1/P2 defect is found the fix loop re-runs with the
    # findings injected. P3-only findings → "partial" verdict allowed through.
    # Per-request override via context["review"].
    codegen_review: bool = True

    # Governance
    strict_ontology: bool = True
    audit_log_path: str = "logs/audit.jsonl"

    # Sandbox
    sandbox_timeout_s: int = 20
    sandbox_memory_mb: int = 512

    # Performance optimization
    cache_max_size: int = 1000
    cache_ttl_seconds: int = 3600
    rate_limit_rps: float = 10.0
    rate_limit_burst: int = 20

    # Version — sourced from version.py, overridable via env
    version: str = __version__

    # Project root for file operations (set by BFF / CLI)
    project_root: str | None = None

    # Step-4 P0: BaiLongma fusion (all disabled by default per G4 — opt in).
    #   bailongma_endpoint:  when non-empty, enables A2A delegation to the
    #                        chassis sidecar.  Default = empty = disabled.
    #   bailongma_bridge:    "a2a" (default) only supported transport at P0.
    #   bailongma_observability_path: SQLite file for the cross-runtime
    #                                 llm_calls + injection_hits tables.
    #                                 Defaults to <project_root>/logs/observability.sqlite.
    #   bailongma_enable_delegation: when True, eligible code-family tasks
    #                                 are handed off to the chassis.  Default
    #                                 False — start with telemetry only.
    bailongma_endpoint: str = ""
    bailongma_bridge: str = "a2a"
    bailongma_observability_path: str = ""
    bailongma_enable_delegation: bool = False

    @staticmethod
    def feature_register() -> dict[str, dict[str, str]]:
        """Central feature-flag registry.

        All opt-in flags with gated behaviour must have a row here so
        ``/api/v1/health`` can print their name/description/state without
        needing a flag-library dependency.  Keys are dotted paths that
        match the Settings attribute (or the most relevant one).
        """
        return {
            # Step-4 fusion flags
            "bailongma.endpoint": {
                "name": "BaiLongma A2A sidecar endpoint",
                "desc": "When set, enables chassis handshake (ping/echo) and (if delegation is on) code-family task delegation.  Default '' = disabled.",
                "default": "",
            },
            "bailongma.enable_delegation": {
                "name": "BaiLongma task delegation gate",
                "desc": "When True AND bailongma_endpoint is reachable, eligible tasks are delegated.  Default False = telemetry-only sidecar mode.",
                "default": "False",
            },
            # Step-3 codegen gates
            "codegen.candidates": {
                "name": "Default best-of-k",
                "desc": "Number of independent LLM generations tried for code tasks (differential verification).  1 disables best-of-k.  Overridable per-request via context['candidates'].",
                "default": "2",
            },
            "codegen.review": {
                "name": "Code review panel",
                "desc": "Enables the correctness/security/quality three-role review panel after every code generation.  P1/P2 defects re-enter the fix loop.",
                "default": "True",
            },
            # L2/L3/L5 meta gates
            "gates.evolution": {
                "name": "L2 evolution DGM",
                "desc": "Runs the Deep-Generalisation Model on task outputs to produce cross-task meta-rules.  Disabled by default (compute-heavy).",
                "default": "False",
            },
            "gates.symbolic": {
                "name": "L3 ontology/rule engine",
                "desc": "Injects type-safe symbolic rules into L2 decisions.  Enabled by default (low overhead, correctness impact).",
                "default": "True",
            },
            "gates.metacognition": {
                "name": "L5 HyperAgent self-modification",
                "desc": "Allows the meta-orchestrator to rewrite pipeline config.  Disabled by default (requires policy review).",
                "default": "False",
            },
        }

    @classmethod
    def from_env(cls) -> Settings:
        providers: list[LLMProviderConfig] = []
        # Ollama
        if os.getenv("MORE_OLLAMA_ENDPOINT"):
            providers.append(
                LLMProviderConfig(
                    name="ollama",
                    provider="ollama",
                    endpoint=os.getenv("MORE_OLLAMA_ENDPOINT", "http://localhost:11434"),
                    model=os.getenv("MORE_OLLAMA_MODEL", "qwen2.5:7b"),
                    timeout_s=int(os.getenv("MORE_OLLAMA_TIMEOUT") or "120"),
                )
            )
        # LMStudio
        if os.getenv("MORE_LMSTUDIO_ENDPOINT"):
            providers.append(
                LLMProviderConfig(
                    name="lmstudio",
                    provider="lmstudio",
                    endpoint=os.getenv("MORE_LMSTUDIO_ENDPOINT", "http://localhost:1234/v1"),
                    model=os.getenv("MORE_LMSTUDIO_MODEL", "ornith-1.5-35b-a3b"),
                    api_key=os.getenv("MORE_LMSTUDIO_API_KEY"),
                    timeout_s=int(os.getenv("MORE_LMSTUDIO_TIMEOUT") or "120"),
                )
            )
        # OpenAI-compatible (OpenAI / DeepSeek / Kimi / Zhipu ... )
        if os.getenv("MORE_OPENAI_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="openai",
                    provider="openai",
                    endpoint=os.getenv("MORE_OPENAI_ENDPOINT", "https://api.openai.com/v1"),
                    model=os.getenv("MORE_OPENAI_MODEL", "gpt-4o-mini"),
                    api_key=os.getenv("MORE_OPENAI_API_KEY"),
                )
            )
        # Groq
        if os.getenv("MORE_GROQ_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="groq",
                    provider="groq",
                    endpoint=os.getenv("MORE_GROQ_ENDPOINT", "https://api.groq.com/openai/v1"),
                    model=os.getenv("MORE_GROQ_MODEL", "llama-3.3-70b-versatile"),
                    api_key=os.getenv("MORE_GROQ_API_KEY"),
                )
            )
        # Anthropic (via OpenAI-compat proxy or native)
        if os.getenv("MORE_ANTHROPIC_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="anthropic",
                    provider="anthropic",
                    endpoint=os.getenv("MORE_ANTHROPIC_ENDPOINT", "https://api.anthropic.com/v1"),
                    model=os.getenv("MORE_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                    api_key=os.getenv("MORE_ANTHROPIC_API_KEY"),
                )
            )
        # Google Gemini
        if os.getenv("MORE_GOOGLE_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="google",
                    provider="google",
                    endpoint=os.getenv(
                        "MORE_GOOGLE_ENDPOINT",
                        "https://generativelanguage.googleapis.com/v1beta/openai",
                    ),
                    model=os.getenv("MORE_GOOGLE_MODEL", "gemini-2.0-flash"),
                    api_key=os.getenv("MORE_GOOGLE_API_KEY"),
                )
            )
        # Mistral
        if os.getenv("MORE_MISTRAL_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="mistral",
                    provider="mistral",
                    endpoint=os.getenv("MORE_MISTRAL_ENDPOINT", "https://api.mistral.ai/v1"),
                    model=os.getenv("MORE_MISTRAL_MODEL", "mistral-large-latest"),
                    api_key=os.getenv("MORE_MISTRAL_API_KEY"),
                )
            )
        # OpenRouter (access to 200+ models)
        if os.getenv("MORE_OPENROUTER_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="openrouter",
                    provider="openrouter",
                    endpoint=os.getenv("MORE_OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1"),
                    model=os.getenv("MORE_OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                    api_key=os.getenv("MORE_OPENROUTER_API_KEY"),
                )
            )
        # Together AI
        if os.getenv("MORE_TOGETHER_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="together",
                    provider="together",
                    endpoint=os.getenv("MORE_TOGETHER_ENDPOINT", "https://api.together.xyz/v1"),
                    model=os.getenv("MORE_TOGETHER_MODEL", "meta-llama/Llama-3-70b-chat-hf"),
                    api_key=os.getenv("MORE_TOGETHER_API_KEY"),
                )
            )
        # xAI (Grok)
        if os.getenv("MORE_XAI_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="xai",
                    provider="xai",
                    endpoint=os.getenv("MORE_XAI_ENDPOINT", "https://api.x.ai/v1"),
                    model=os.getenv("MORE_XAI_MODEL", "grok-2-latest"),
                    api_key=os.getenv("MORE_XAI_API_KEY"),
                )
            )
        # Fireworks AI
        if os.getenv("MORE_FIREWORKS_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="fireworks",
                    provider="fireworks",
                    endpoint=os.getenv(
                        "MORE_FIREWORKS_ENDPOINT", "https://api.fireworks.ai/inference/v1"
                    ),
                    model=os.getenv(
                        "MORE_FIREWORKS_MODEL", "accounts/fireworks/models/llama-v3p1-70b-instruct"
                    ),
                    api_key=os.getenv("MORE_FIREWORKS_API_KEY"),
                )
            )
        # vLLM (local)
        if os.getenv("MORE_VLLM_ENDPOINT"):
            providers.append(
                LLMProviderConfig(
                    name="vllm",
                    provider="vllm",
                    endpoint=os.getenv("MORE_VLLM_ENDPOINT", "http://localhost:8000/v1"),
                    model=os.getenv("MORE_VLLM_MODEL", "default"),
                    api_key=os.getenv("MORE_VLLM_API_KEY", "EMPTY"),
                )
            )
        # llama.cpp (local GGUF server)
        if os.getenv("MORE_LLAMACPP_ENDPOINT"):
            providers.append(
                LLMProviderConfig(
                    name="llamacpp",
                    provider="llamacpp",
                    endpoint=os.getenv("MORE_LLAMACPP_ENDPOINT", "http://localhost:8090/v1"),
                    model=os.getenv("MORE_LLAMACPP_MODEL", "qwen3.8-27b"),
                    api_key=os.getenv("MORE_LLAMACPP_API_KEY", "EMPTY"),
                    timeout_s=int(os.getenv("MORE_LLAMACPP_TIMEOUT", "120")),
                )
            )
        # DeepSeek (cloud)
        if os.getenv("MORE_DEEPSEEK_API_KEY"):
            providers.append(
                LLMProviderConfig(
                    name="deepseek",
                    provider="deepseek",
                    endpoint=os.getenv("MORE_DEEPSEEK_ENDPOINT", "https://api.deepseek.com"),
                    model=os.getenv("MORE_DEEPSEEK_MODEL", "deepseek-chat"),
                    api_key=os.getenv("MORE_DEEPSEEK_API_KEY"),
                )
            )

        # Mock provider — auto-enabled when no real providers are configured (dev mode)
        if not providers or os.getenv("MORE_USE_MOCK", "0") == "1":
            providers.append(
                LLMProviderConfig(
                    name="mock",
                    provider="mock",
                    endpoint="",
                    model="mock-dev-1.0",
                )
            )

        fallback = os.getenv("MORE_LLM_FALLBACK_CHAIN", "")
        fallback_chain = [p.strip() for p in fallback.split(",") if p.strip()] or [
            p.name for p in providers
        ]

        # Version override via env
        version = os.getenv("MORE_VERSION", __version__)

        return cls(
            plugin_dir=os.getenv("MORE_PLUGIN_DIR", "plugins"),
            log_dir=os.getenv("MORE_LOG_DIR", "logs"),
            providers=providers,
            fallback_chain=fallback_chain,
            version=version,
            enable_evolution=os.getenv("MORE_ENABLE_EVOLUTION", "0") == "1",
            enable_evolution_llm_variants=os.getenv("MORE_ENABLE_EVOLUTION_LLM_VARIANTS", "0")
            == "1",
            enable_metacognition=os.getenv("MORE_ENABLE_METACOGNITION", "0") == "1",
            enable_symbolic=os.getenv("MORE_ENABLE_SYMBOLIC", "1") == "1",
            enable_codegen_context=os.getenv("MORE_CODEGEN_CONTEXT", "1") == "1",
            codegen_candidates=int(os.getenv("MORE_CODEGEN_CANDIDATES", "2")),
            codegen_review=os.getenv("MORE_CODEGEN_REVIEW", "1") == "1",
            strict_ontology=os.getenv("MORE_STRICT_ONTOLOGY", "1") == "1",
            audit_log_path=os.getenv("MORE_AUDIT_LOG", "logs/audit.jsonl"),
            sandbox_timeout_s=int(os.getenv("MORE_SANDBOX_TIMEOUT", "20")),
            sandbox_memory_mb=int(os.getenv("MORE_SANDBOX_MEM_MB", "512")),
            project_root=os.getenv("MORE_PROJECT_ROOT") or str(Path.cwd().resolve()),
            # Step-4 P0 fusion — opt-in via env only.
            bailongma_endpoint=os.getenv("MORE_BAILONGMA_ENDPOINT", "").strip(),
            bailongma_bridge=os.getenv("MORE_BAILONGMA_BRIDGE", "a2a"),
            bailongma_observability_path=os.getenv("MORE_BAILONGMA_OBS_DB", "").strip(),
            bailongma_enable_delegation=os.getenv("MORE_BAILONGMA_DELEGATION", "0") == "1",
        )
