"""Skill config injection with secret redaction.

Reference: OpenFang v0.6.0 skill config injection.
Skills declare config vars in their metadata. Resolver order:
  1. User config (explicit) → 2. Environment var → 3. Default → 4. Error if required

Secrets auto-redacted in rendered skill prompts:
  Patterns: *_token, *_key, *_secret, *password*
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

# Patterns that indicate a secret value
_SECRET_PATTERNS = re.compile(
    r"(.*_token|.*_key|.*_secret|.*password.*|.*_credential|.*_auth)",
    re.IGNORECASE,
)


@dataclass
class ConfigVar:
    """A skill configuration variable declaration."""
    name: str
    description: str = ""
    env: str | None = None        # Environment variable to read from
    default: Any = None
    required: bool = False
    is_secret: bool = False       # Auto-detected if not explicit


@dataclass
class ConfigSchema:
    """Schema for skill configuration."""
    vars: list[ConfigVar] = field(default_factory=list)

    def var_names(self) -> list[str]:
        return [v.name for v in self.vars]


def is_secret_name(name: str) -> bool:
    """Check if a config var name looks like a secret."""
    return bool(_SECRET_PATTERNS.match(name))


def resolve_config(
    schema: ConfigSchema,
    user_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve skill config vars using the priority chain.

    Returns:
        (resolved_values, errors) — errors lists missing required vars.
    """
    user_config = user_config or {}
    resolved: dict[str, Any] = {}
    errors: list[str] = []

    for var in schema.vars:
        # Priority 1: User config
        if var.name in user_config:
            resolved[var.name] = user_config[var.name]
            continue

        # Priority 2: Environment variable
        if var.env:
            env_val = os.getenv(var.env)
            if env_val is not None:
                resolved[var.name] = env_val
                continue

        # Priority 3: Default
        if var.default is not None:
            resolved[var.name] = var.default
            continue

        # Priority 4: Error if required
        if var.required:
            errors.append(f"Missing required config: {var.name}")
        else:
            resolved[var.name] = None

    return resolved, errors


def redact_secrets(
    config: dict[str, Any],
    schema: ConfigSchema | None = None,
) -> dict[str, Any]:
    """Return a copy of config with secret values redacted.

    Used for logging and prompt injection to avoid leaking secrets.
    """
    redacted = {}
    explicit_secrets = set()
    if schema:
        for var in schema.vars:
            if var.is_secret or is_secret_name(var.name):
                explicit_secrets.add(var.name)

    for key, val in config.items():
        if key in explicit_secrets or is_secret_name(key):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = val

    return redacted


def inject_config_into_prompt(
    prompt_template: str,
    config: dict[str, Any],
    schema: ConfigSchema | None = None,
) -> str:
    """Inject resolved config into a skill prompt template.

    Automatically redacts secrets before injection.
    Uses {{var_name}} placeholder syntax.
    """
    safe_config = redact_secrets(config, schema)

    result = prompt_template
    for key, val in safe_config.items():
        placeholder = "{{" + key + "}}"
        if placeholder in result:
            result = result.replace(placeholder, str(val) if val else "")

    return result


def parse_config_schema(raw: dict[str, Any]) -> ConfigSchema:
    """Parse a config schema from a dict (e.g. from SKILL metadata).

    Expected format:
        {
            "github_token": {
                "description": "GitHub PAT",
                "env": "GITHUB_TOKEN",
                "required": true
            },
            "default_branch": {
                "description": "Default branch",
                "default": "main"
            }
        }
    """
    vars_list = []
    for name, spec in raw.items():
        if isinstance(spec, dict):
            is_secret = spec.get("is_secret", is_secret_name(name))
            vars_list.append(ConfigVar(
                name=name,
                description=spec.get("description", ""),
                env=spec.get("env"),
                default=spec.get("default"),
                required=spec.get("required", False),
                is_secret=is_secret,
            ))
        else:
            # Simple value = default
            vars_list.append(ConfigVar(name=name, default=spec))

    return ConfigSchema(vars=vars_list)
