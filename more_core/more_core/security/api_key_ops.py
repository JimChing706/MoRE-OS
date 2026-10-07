"""MoRE OS API-Key generation, validation, and configuration-injection helpers.

These helpers are intentionally small, dependency-free (stdlib only), so the
``python -m more_core.cli api-key ...`` entry point keeps working *before* a
valid key or full runtime stack is present.  They live in a dedicated module
so they can be unit-tested without spinning up the API server.

Three key formats are supported:

* ``strength=compat`` (default when ``--compat``): 46 chars, url-safe base64
  alphabet, matches the 46-byte keys used in the v0.9.9 retrospective baselines
  (no strict prefix).  **Testing补缺场景默认走这个格式。**
* ``strength=modern``: 64 chars, ``sk-more-os-`` prefix + 48 url-safe chars,
  meets :data:`API_KEY_PREFIX` strict-mode rules (for production installs).
* ``strength=hex``: 64 hex chars (for tooling scripts that need regex-safe keys).
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import math
import os
import re
import secrets
import shutil
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: Minimum accepted length for MORE_API_KEY.
API_KEY_MIN_LENGTH: int = 16
#: Recommended key prefix, checked only in strict mode (advisory elsewhere).
API_KEY_PREFIX: str = "sk-more-os-"

__all__ = [
    "API_KEY_MIN_LENGTH",
    "API_KEY_PREFIX",
    "ENV_PATHS",
    "APIKeyKind",
    "APIKeyReport",
    "generate_api_key",
    "inject_api_key_into_env",
    "sign_rotation_proof",
    "validate_api_key_report",
    "verify_rotation_proof",
]

APIKeyKind = Literal["compat", "modern", "hex"]

_ENV_LINE_RE = re.compile(r"^\s*MORE_API_KEY\s*=\s*(.*?)\s*$", re.MULTILINE)
_MORE_HEADER_RE = re.compile(r"^MORE[._-][A-Z0-9]", re.IGNORECASE)
_B64URL_CHARS = set(string.ascii_letters + string.digits + "-_")
_HEX_CHARS = set(string.hexdigits)

# Candidate env-file locations, in order of preference during testing补缺.
ENV_PATHS: tuple[Path, ...] = (
    Path(__file__).resolve().parents[2] / ".env",
    Path(__file__).resolve().parents[1] / ".env",
    Path.cwd() / ".env",
    Path.home() / ".config" / "qnming-more-os" / ".env",
)


@dataclass
class APIKeyReport:
    """Result of validating a candidate API key."""

    valid: bool
    length: int
    entropy_bits: float
    has_prefix: bool
    charset_ok: bool
    kind_guess: str
    warnings: list[str]
    errors: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "length": self.length,
            "entropy_bits": round(self.entropy_bits, 2),
            "has_prefix": self.has_prefix,
            "charset_ok": self.charset_ok,
            "kind_guess": self.kind_guess,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _urlsafe_b64_no_pad(nbytes: int) -> str:
    raw = secrets.token_bytes(nbytes)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_api_key(
    strength: APIKeyKind = "compat",
    *,
    enforce_prefix: bool = False,
) -> str:
    """Generate a single API key string matching ``strength``.

    Parameters
    ----------
    strength:
        ``compat`` (46 chars, no prefix), ``modern`` (64 chars,
        ``sk-more-os-`` prefix), ``hex`` (64 hex chars).
    enforce_prefix:
        When True, ``compat`` keys also receive the ``sk-more-os-`` prefix
        (resulting in ~58 chars) so strict-mode deployments can accept them.
    """
    if strength == "hex":
        return secrets.token_hex(32)  # 64 chars
    if strength == "modern":
        body = _urlsafe_b64_no_pad(36)  # 48 chars
        return f"{API_KEY_PREFIX}{body}"  # 11 + 48 = 59-ish → padded to 59/60
    # compat: 46 chars, base64url (~ 258 bits of entropy)
    body = _urlsafe_b64_no_pad(34)  # 34 bytes → floor(34*8/6) = 45 chars, +1 → 46
    # Guarantee exactly 46 by appending a random urlsafe char if short.
    while len(body) < 46:
        body += secrets.choice(string.ascii_letters + string.digits + "-_")
    key = body[:46]
    if enforce_prefix:
        return f"{API_KEY_PREFIX}{key[: 46 - len(API_KEY_PREFIX)]}"
    return key


def _entropy_bits(key: str) -> float:
    if not key:
        return 0.0
    pool = 0
    if any(c in string.ascii_lowercase for c in key):
        pool += 26
    if any(c in string.ascii_uppercase for c in key):
        pool += 26
    if any(c in string.digits for c in key):
        pool += 10
    if any(c in "-_" for c in key):
        pool += 2
    if pool == 0:
        return 0.0
    return len(key) * math.log2(pool)


def _guess_kind(key: str) -> str:
    if key.startswith(API_KEY_PREFIX):
        return "modern"
    if len(key) == 64 and all(c in _HEX_CHARS for c in key):
        return "hex"
    if 44 <= len(key) <= 48 and all(c in _B64URL_CHARS for c in key):
        return "compat"
    return "custom"


def validate_api_key_report(
    key: str | None,
    *,
    require_prefix: bool = False,
    min_length: int | None = None,
) -> APIKeyReport:
    """Validate a key and return a detailed :class:`APIKeyReport`.

    This is the *business-logic* validator (not the startup one).  It checks
    length (``>= API_KEY_MIN_LENGTH``), charset (url-safe base64 / hex),
    entropy (>= 128 bits safe floor), and optionally the strict prefix.
    """
    key = (key or "").strip()
    warnings: list[str] = []
    errors: list[str] = []
    min_len = min_length if min_length is not None else API_KEY_MIN_LENGTH
    if not key:
        errors.append("empty key")
        return APIKeyReport(False, 0, 0.0, False, False, "empty", warnings, errors)

    length = len(key)
    has_prefix = key.startswith(API_KEY_PREFIX)
    body = key[len(API_KEY_PREFIX) :] if has_prefix else key
    if has_prefix:
        charset_ok = all(c in _B64URL_CHARS for c in body)
    else:
        charset_ok = all(c in _B64URL_CHARS for c in key) or all(c in _HEX_CHARS for c in key)
    kind = _guess_kind(key)
    entropy = _entropy_bits(key)

    if length < min_len:
        errors.append(f"invalid length: {length} < minimum {min_len}")
    if not charset_ok:
        errors.append("charset invalid — only base64url (-_A-Za-z0-9) or hex is allowed")
    if require_prefix and not has_prefix:
        errors.append(f"missing required prefix: {API_KEY_PREFIX!r}")
    if entropy < 128:
        warnings.append(f"low entropy: {entropy:.1f} bits (< 128 bits is guessable)")
    if _MORE_HEADER_RE.match(key):
        warnings.append("key starts with MORE. — rotate it to avoid config collisions")

    valid = not errors
    return APIKeyReport(valid, length, entropy, has_prefix, charset_ok, kind, warnings, errors)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".moreos-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def inject_api_key_into_env(
    new_key: str,
    env_path: str | os.PathLike[str] | None = None,
    *,
    backup: bool = True,
    strict: bool = False,
) -> tuple[Path, Path | None, str]:
    """Inject ``MORE_API_KEY=...`` into the chosen ``.env`` file atomically.

    Returns
    -------
    (env_path, backup_path, previous_key)
        previous_key = ``""`` when no prior value existed.
    """
    if not validate_api_key_report(new_key, require_prefix=strict).valid:
        # Refuse to inject a key that fails business-level validation — saves
        # testers from "inject → restart server → 401 surprise" loops.
        rep = validate_api_key_report(new_key, require_prefix=strict)
        raise ValueError(
            "refusing to inject invalid key: "
            + "; ".join(rep.errors)
            + ("; " + "; ".join(rep.warnings) if rep.warnings else "")
        )

    env = Path(env_path) if env_path else _resolve_default_env_path()
    env = env.resolve()
    previous = ""
    backup_path: Path | None = None

    if env.exists():
        text = env.read_text(encoding="utf-8")
        match = _ENV_LINE_RE.search(text)
        if match:
            previous = (match.group(1) or "").strip().strip('"').strip("'")
    else:
        text = "# qnming MoRE OS .env — generated by `more-os api-key inject`\n"

    if backup and (previous or env.exists()):
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = Path(str(env) + f".bak.{ts}")
        shutil.copy2(env, backup_path) if env.exists() else backup_path.write_text(
            text, encoding="utf-8"
        )

    new_line = f'MORE_API_KEY="{new_key}"'
    if previous:
        new_text = _ENV_LINE_RE.sub(new_line, text, count=1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + new_line + "\n"

    _atomic_write(env, new_text)
    try:
        # Best-effort: restrict .env visibility on the filesystem.
        os.chmod(env, 0o600)
    except OSError:  # pragma: no cover - chmod fails on some non-Unix filesystems
        pass
    return env, backup_path, previous


def _resolve_default_env_path() -> Path:
    """Pick the first ``ENV_PATHS`` that already exists, else ``more_core/.env``.

    补缺链路优先复用 existing v0.9.9 密钥目录：``$repo/more_core/.env``。
    """
    for cand in ENV_PATHS:
        if cand.exists():
            return cand
    # Fallback = more_core/.env (matches 46 len baseline).
    fallback = Path(__file__).resolve().parents[1] / ".env"
    return fallback


# ---------------------------------------------------------------------------
# Rotation proof (S4) — master-key HMAC so /admin/api-key/rotate is safe.
# ---------------------------------------------------------------------------

_ROTATION_SALT = b"more-os|api-key|rotate|v1"
ROTATION_PROOF_TTL_SECONDS = 5 * 60  # 5 minutes


def _int_bytes(n: int) -> bytes:
    return n.to_bytes(8, "big", signed=False)


def sign_rotation_proof(
    *,
    master_key: str,
    new_key: str,
    revoke_old_in_seconds: int,
    issued_at_unix: int | None = None,
) -> str:
    """Return a compact HMAC proof for admin rotation requests.

    Format (base64url): ``<issued_at_unix:8b><revoke_seconds:8b><hmac_sha256(32b)>``
    """
    if not master_key:
        raise ValueError("master_key is required to sign rotation proofs")
    issued = int(issued_at_unix or _dt.datetime.now(_dt.timezone.utc).timestamp())
    body = (
        _ROTATION_SALT
        + new_key.encode("utf-8")
        + _int_bytes(issued)
        + _int_bytes(int(revoke_old_in_seconds))
    )
    sig = hmac.new(master_key.encode("utf-8"), body, hashlib.sha256).digest()
    raw = _int_bytes(issued) + _int_bytes(int(revoke_old_in_seconds)) + sig
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_rotation_proof(
    *,
    master_key: str,
    proof: str,
    new_key: str,
    revoke_old_in_seconds: int,
    ttl_seconds: int = ROTATION_PROOF_TTL_SECONDS,
    now_unix: int | None = None,
) -> bool:
    """Validate a rotation proof produced by :func:`sign_rotation_proof`."""
    try:
        pad = "=" * (-len(proof) % 4)
        raw = base64.urlsafe_b64decode(proof + pad)
    except Exception:  # noqa: BLE001
        return False
    if len(raw) != 8 + 8 + 32:
        return False
    issued = int.from_bytes(raw[:8], "big", signed=False)
    revoke = int.from_bytes(raw[8:16], "big", signed=False)
    provided = raw[16:48]
    if revoke != int(revoke_old_in_seconds):
        return False
    now = int(now_unix or _dt.datetime.now(_dt.timezone.utc).timestamp())
    if now - issued > ttl_seconds or issued - now > 10:
        return False
    body = (
        _ROTATION_SALT
        + new_key.encode("utf-8")
        + _int_bytes(issued)
        + _int_bytes(int(revoke_old_in_seconds))
    )
    expected = hmac.new(master_key.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(provided, expected)
