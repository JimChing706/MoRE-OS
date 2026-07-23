"""Tests for skill config injection and secret redaction."""

from more_core.skills.config_injection import (
    ConfigVar, ConfigSchema, is_secret_name,
    resolve_config, redact_secrets, inject_config_into_prompt,
    parse_config_schema,
)


def test_is_secret_name():
    assert is_secret_name("github_token")
    assert is_secret_name("api_key")
    assert is_secret_name("db_secret")
    assert is_secret_name("user_password")
    assert is_secret_name("AWS_CREDENTIAL")
    assert not is_secret_name("default_branch")
    assert not is_secret_name("timeout")
    assert not is_secret_name("model_name")


def test_resolve_config_user_priority():
    schema = ConfigSchema(vars=[
        ConfigVar(name="branch", default="main"),
    ])
    resolved, errors = resolve_config(schema, {"branch": "develop"})
    assert resolved["branch"] == "develop"
    assert not errors


def test_resolve_config_env_fallback(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    schema = ConfigSchema(vars=[
        ConfigVar(name="token", env="MY_TOKEN", required=True),
    ])
    resolved, errors = resolve_config(schema)
    assert resolved["token"] == "secret123"
    assert not errors


def test_resolve_config_default_fallback():
    schema = ConfigSchema(vars=[
        ConfigVar(name="port", default=8080),
    ])
    resolved, errors = resolve_config(schema)
    assert resolved["port"] == 8080


def test_resolve_config_required_missing():
    schema = ConfigSchema(vars=[
        ConfigVar(name="api_key", required=True),
    ])
    resolved, errors = resolve_config(schema)
    assert len(errors) == 1
    assert "api_key" in errors[0]


def test_redact_secrets_by_name():
    config = {"github_token": "ghp_abc123", "branch": "main"}
    redacted = redact_secrets(config)
    assert redacted["github_token"] == "***REDACTED***"
    assert redacted["branch"] == "main"


def test_redact_secrets_with_schema():
    schema = ConfigSchema(vars=[
        ConfigVar(name="custom_field", is_secret=True),
        ConfigVar(name="visible"),
    ])
    config = {"custom_field": "secret", "visible": "ok"}
    redacted = redact_secrets(config, schema)
    assert redacted["custom_field"] == "***REDACTED***"
    assert redacted["visible"] == "ok"


def test_inject_config_into_prompt():
    template = "Use branch {{branch}} with token {{api_key}}"
    config = {"branch": "main", "api_key": "secret123"}
    schema = ConfigSchema(vars=[
        ConfigVar(name="branch"),
        ConfigVar(name="api_key", is_secret=True),
    ])
    result = inject_config_into_prompt(template, config, schema)
    assert "main" in result
    assert "secret123" not in result
    assert "***REDACTED***" in result


def test_parse_config_schema():
    raw = {
        "github_token": {
            "description": "GitHub PAT",
            "env": "GITHUB_TOKEN",
            "required": True,
        },
        "default_branch": {
            "description": "Branch name",
            "default": "main",
        },
        "simple_val": 42,
    }
    schema = parse_config_schema(raw)
    assert len(schema.vars) == 3
    token_var = next(v for v in schema.vars if v.name == "github_token")
    assert token_var.required
    assert token_var.env == "GITHUB_TOKEN"
    assert token_var.is_secret  # auto-detected
    branch_var = next(v for v in schema.vars if v.name == "default_branch")
    assert branch_var.default == "main"
    assert not branch_var.is_secret
    simple_var = next(v for v in schema.vars if v.name == "simple_val")
    assert simple_var.default == 42
