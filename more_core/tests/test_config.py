"""Tests for Settings.from_env provider wiring and toggle defaults."""

from __future__ import annotations

from more_core.core.config import Settings


def test_deepseek_provider_wired_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MORE_DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("MORE_OLLAMA_ENDPOINT", raising=False)
    monkeypatch.delenv("MORE_LMSTUDIO_ENDPOINT", raising=False)
    settings = Settings.from_env()
    deepseek = [p for p in settings.providers if p.provider == "deepseek"]
    assert len(deepseek) == 1
    assert deepseek[0].api_key == "sk-test"
    assert deepseek[0].endpoint == "https://api.deepseek.com"
    assert deepseek[0].model == "deepseek-chat"


def test_deepseek_provider_absent_without_key(monkeypatch) -> None:
    monkeypatch.delenv("MORE_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MORE_OLLAMA_ENDPOINT", raising=False)
    monkeypatch.delenv("MORE_LMSTUDIO_ENDPOINT", raising=False)
    settings = Settings.from_env()
    assert not [p for p in settings.providers if p.provider == "deepseek"]


def test_toggle_defaults_match_docs(monkeypatch) -> None:
    monkeypatch.delenv("MORE_ENABLE_EVOLUTION", raising=False)
    monkeypatch.delenv("MORE_ENABLE_METACOGNITION", raising=False)
    monkeypatch.delenv("MORE_ENABLE_SYMBOLIC", raising=False)
    settings = Settings.from_env()
    assert settings.enable_evolution is False
    assert settings.enable_metacognition is False
    assert settings.enable_symbolic is True


def test_toggle_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MORE_ENABLE_EVOLUTION", "1")
    monkeypatch.setenv("MORE_ENABLE_METACOGNITION", "1")
    settings = Settings.from_env()
    assert settings.enable_evolution is True
    assert settings.enable_metacognition is True
