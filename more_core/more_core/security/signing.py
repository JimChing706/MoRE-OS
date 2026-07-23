"""Request Signing — HMAC integrity verification.

Reference: OpenFang OFP protocol with HMAC-SHA256 mutual authentication.
Ensures request integrity for inter-service communication and
verifies that requests haven't been tampered with in transit.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class SignedRequest:
    """A request with HMAC signature."""

    payload: bytes
    signature: str
    timestamp: float
    nonce: str


class RequestSigner:
    """Signs and verifies requests using HMAC-SHA256.

    Used for:
    - API-to-API calls between core and BFF
    - Webhook delivery verification
    - Plugin communication integrity
    """

    def __init__(self, secret: str, max_age_s: float = 300.0) -> None:
        self._secret = secret.encode("utf-8")
        self._max_age = max_age_s
        self._seen_nonces: set[str] = set()
        self._nonce_max = 10000

    def sign(self, payload: bytes, nonce: str | None = None) -> SignedRequest:
        """Sign a payload."""
        ts = time.time()
        nonce = nonce or hashlib.sha256(f"{ts}{id(payload)}".encode()).hexdigest()[:16]
        message = f"{ts}:{nonce}:".encode() + payload
        sig = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return SignedRequest(payload=payload, signature=sig, timestamp=ts, nonce=nonce)

    def verify(self, request: SignedRequest) -> tuple[bool, str]:
        """Verify a signed request.

        Returns:
            (valid, error_message)
        """
        # Check timestamp freshness
        age = time.time() - request.timestamp
        if age > self._max_age:
            return False, f"Request expired ({age:.0f}s > {self._max_age:.0f}s)"
        if age < -30:  # Allow small clock skew
            return False, "Request from the future"

        # Check nonce replay
        if request.nonce in self._seen_nonces:
            return False, "Nonce replay detected"

        # Verify HMAC
        message = f"{request.timestamp}:{request.nonce}:".encode() + request.payload
        expected = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.signature):
            return False, "Invalid signature"

        # Record nonce (prevent replay)
        self._seen_nonces.add(request.nonce)
        if len(self._seen_nonces) > self._nonce_max:
            to_remove = len(self._seen_nonces) - self._nonce_max // 2
            for nonce in list(self._seen_nonces)[:to_remove]:
                self._seen_nonces.discard(nonce)

        return True, ""

    def sign_dict(self, data: dict[str, Any]) -> tuple[str, float, str]:
        """Convenience: sign a JSON-serializable dict.

        Returns:
            (signature, timestamp, nonce)
        """
        import json

        payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        signed = self.sign(payload)
        return signed.signature, signed.timestamp, signed.nonce
