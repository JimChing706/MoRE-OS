"""LMStudio uses OpenAI-compatible endpoints locally."""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class LMStudioProvider(OpenAICompatProvider):
    """Thin subclass for naming and default endpoint."""

    def __init__(
        self,
        name: str,
        endpoint: str = "http://localhost:1234/v1",
        model: str = "local-model",
        api_key: str | None = None,
        timeout: int = 60,
    ) -> None:
        super().__init__(
            name=name,
            endpoint=endpoint,
            model=model,
            api_key=api_key or "lm-studio",
            timeout=timeout,
        )
