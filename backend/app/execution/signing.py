"""Kalshi request signing (docs: getting_started/quick_start_authenticated_requests,
read 2026-11-18).

  pre-sign text = timestamp_ms + METHOD + path
  path includes the /trade-api/v2 prefix and EXCLUDES the query string
  RSA: RSA-PSS, SHA-256, MGF1(SHA-256), salt length = digest length; Ed25519: sign directly
  headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE (base64)

Private keys are loaded from a file outside the repository and never logged or returned.
"""

from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

API_PREFIX = "/trade-api/v2"


class Signer:
    def __init__(self, key_id: str, private_key: rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey):
        if not key_id:
            raise ValueError("API key id is required")
        self._key_id = key_id
        self._key = private_key

    def __repr__(self) -> str:  # never reveal key material
        return "Signer(<redacted>)"

    @classmethod
    def from_pem_file(cls, key_id: str, path: Path) -> Signer:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey):
            raise ValueError("Unsupported key type (need RSA or Ed25519)")
        return cls(key_id, key)

    @staticmethod
    def signing_path(url_or_path: str) -> str:
        path = urlsplit(url_or_path).path  # strips any query string
        if not path.startswith(API_PREFIX):
            path = API_PREFIX + path
        return path

    def sign(self, timestamp_ms: int, method: str, url_or_path: str) -> str:
        message = f"{timestamp_ms}{method.upper()}{self.signing_path(url_or_path)}".encode()
        if isinstance(self._key, rsa.RSAPrivateKey):
            sig = self._key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        else:
            sig = self._key.sign(message)
        return base64.b64encode(sig).decode()

    def headers(self, timestamp_ms: int, method: str, url_or_path: str) -> dict[str, str]:
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "KALSHI-ACCESS-SIGNATURE": self.sign(timestamp_ms, method, url_or_path),
        }
