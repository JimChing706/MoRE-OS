import os
from typing import Literal
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class LLMConfig(BaseModel):
    provider: Literal["openai", "anthropic", "ollama", "lmstudio", "azure"]
    model: str
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7

class AIConfig(BaseModel):
    code_generation: LLMConfig
    code_debugging: LLMConfig
    math_reasoning: LLMConfig
    data_analysis: LLMConfig
    nlp_task: LLMConfig
    multi_agent_orchestration: LLMConfig
    self_improvement: LLMConfig
    cross_domain_transfer: LLMConfig
    code_review: LLMConfig
    architecture_design: LLMConfig

def get_default_config() -> AIConfig:
    lm_studio_base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

    return AIConfig(
        code_generation=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "gemma-4-coder"),
            base_url=lm_studio_base_url,
            temperature=0.3
        ),
        code_debugging=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-35b-a3b"),
            base_url=lm_studio_base_url,
            temperature=0.2
        ),
        math_reasoning=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled"),
            base_url=lm_studio_base_url,
            temperature=0.1
        ),
        data_analysis=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-35b-a3b"),
            base_url=lm_studio_base_url,
            temperature=0.4
        ),
        nlp_task=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "gemma-4-coder"),
            base_url=lm_studio_base_url,
            temperature=0.5
        ),
        multi_agent_orchestration=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-35b-a3b"),
            base_url=lm_studio_base_url,
            temperature=0.6
        ),
        self_improvement=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled"),
            base_url=lm_studio_base_url,
            temperature=0.8
        ),
        cross_domain_transfer=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3.5-35b-a3b"),
            base_url=lm_studio_base_url,
            temperature=0.7
        ),
        code_review=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "gemma-4-coder"),
            base_url=lm_studio_base_url,
            temperature=0.3
        ),
        architecture_design=LLMConfig(
            provider="lmstudio",
            model=os.getenv("LMSTUDIO_MODEL", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled"),
            base_url=lm_studio_base_url,
            temperature=0.5
        )
    )

ai_config = get_default_config()
