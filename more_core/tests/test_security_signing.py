"""请求签名测试（security/signing.py 覆盖补齐）。"""

from __future__ import annotations

import json
import time

from more_core.security.signing import RequestSigner, SignedRequest


def _signer(max_age=300.0) -> RequestSigner:
    return RequestSigner("s3cr3t", max_age_s=max_age)


def test_sign_produces_verifiable_request():
    s = _signer()
    signed = s.sign(b"payload")
    assert isinstance(signed, SignedRequest)
    assert signed.payload == b"payload"
    assert len(signed.signature) == 64 and signed.nonce
    assert s.verify(signed) == (True, "")


def test_verify_rejects_tampered_payload():
    s = _signer()
    signed = s.sign(b"payload")
    tampered = SignedRequest(
        payload=b"tampered",
        signature=signed.signature,
        timestamp=signed.timestamp,
        nonce=signed.nonce,
    )
    ok, err = s.verify(tampered)
    assert ok is False and err == "Invalid signature"


def test_verify_rejects_expired_request():
    s = _signer(max_age=1.0)
    signed = s.sign(b"p")
    signed.timestamp = time.time() - 100
    ok, err = s.verify(signed)
    assert ok is False and "expired" in err.lower()


def test_verify_rejects_future_request():
    s = _signer()
    signed = s.sign(b"p")
    signed.timestamp = time.time() + 120
    ok, err = s.verify(signed)
    assert ok is False and "future" in err.lower()


def test_verify_rejects_nonce_replay():
    s = _signer()
    signed = s.sign(b"p", nonce="fixed-nonce")
    assert s.verify(signed)[0] is True
    ok, err = s.verify(signed)
    assert ok is False and "replay" in err.lower()


def test_sign_dict_roundtrip():
    s = _signer()
    sig, ts, nonce = s.sign_dict({"b": 2, "a": 1})
    payload = json.dumps({"b": 2, "a": 1}, sort_keys=True, separators=(",", ":")).encode()
    assert s.verify(SignedRequest(payload=payload, signature=sig, timestamp=ts, nonce=nonce)) == (
        True,
        "",
    )


def test_sign_uses_explicit_nonce_when_given():
    s = _signer()
    assert s.sign(b"p", nonce="n1").nonce == "n1"


def test_nonce_store_is_trimmed():
    s = RequestSigner("k")
    s._nonce_max = 10
    for i in range(25):
        signed = s.sign(b"p", nonce=f"n{i}")
        assert s.verify(signed)[0] is True
    assert len(s._seen_nonces) <= s._nonce_max
