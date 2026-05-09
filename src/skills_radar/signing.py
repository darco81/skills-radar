"""Cryptographic signing for the VERIFIED trust tier.

Today's VERIFIED tier (in `sanitize.determine_trust_tier`) is path-based -
files under the Anthropic-official plugin cache get VERIFIED automatically.
This module adds an explicit signature path: a SKILL.md plus a `*.sig`
sibling can promote to VERIFIED across any path location, as long as the
signature validates against a configured trust root (Ed25519 public key).

Design:
- Ed25519 keys via `cryptography.hazmat.primitives.asymmetric.ed25519`
- Signature is over the SHA-256 hash of the SKILL.md UTF-8 bytes.
- Sidecar file format: `<skill-dir>/SKILL.md.sig` containing a single
  JSON line:
  {
    "version": 1,
    "key_id": "anthropic-2026",
    "algo": "ed25519",
    "content_hash": "<sha256-hex>",
    "signature": "<base64-bytes>"
  }
- Trust roots: dict of `key_id` → base64 public-key bytes, configurable
  via `signing.trust_roots` in config.

CLI: `skills-radar sign <skill-dir> --key <priv.pem>` (operator)
     `skills-radar verify <skill-dir>` (any user, against configured roots)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SIG_FILENAME = "SKILL.md.sig"
SIG_VERSION = 1


@dataclass
class SignatureResult:
    valid: bool
    key_id: str | None
    reason: str  # "valid" / "missing_sig" / "key_unknown" / "hash_mismatch" / "bad_signature"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_crypto_available() -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
            Ed25519PrivateKey,
        )
    except ImportError as exc:
        msg = "Signing requires the [signing] extras: `pip install skills-radar[signing]`."
        raise ImportError(msg) from exc


def sign_skill(skill_md_path: Path, private_key_pem: Path, key_id: str) -> Path:
    """Sign a SKILL.md and write the sidecar `SKILL.md.sig`.

    Returns the path to the written sidecar.
    """
    _ensure_crypto_available()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    skill_md_path = skill_md_path.resolve()
    if not skill_md_path.exists():
        msg = f"SKILL.md not found at {skill_md_path}"
        raise FileNotFoundError(msg)

    pem_bytes = private_key_pem.read_bytes()
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        msg = "Private key must be Ed25519 PEM."
        raise TypeError(msg)

    body = skill_md_path.read_bytes()
    digest = hashlib.sha256(body).digest()
    sig = key.sign(digest)

    payload = {
        "version": SIG_VERSION,
        "key_id": key_id,
        "algo": "ed25519",
        "content_hash": digest.hex(),
        "signature": base64.b64encode(sig).decode("ascii"),
    }
    sig_path = skill_md_path.parent / SIG_FILENAME
    sig_path.write_text(json.dumps(payload), encoding="utf-8")
    logger.info("Signed %s with key_id=%s", skill_md_path, key_id)
    return sig_path


def verify_skill(
    skill_md_path: Path,
    trust_roots: dict[str, str],
) -> SignatureResult:
    """Verify a SKILL.md signature against configured trust roots.

    `trust_roots` maps key_id → base64-encoded raw public key bytes
    (Ed25519 raw, 32 bytes). To convert a PEM public key to raw:
    `Ed25519PublicKey.public_bytes(Raw, Raw)`.

    Returns SignatureResult - caller decides what to do (e.g. promote
    to VERIFIED tier on valid).
    """
    skill_md_path = skill_md_path.resolve()
    sig_path = skill_md_path.parent / SIG_FILENAME

    if not sig_path.exists():
        return SignatureResult(valid=False, key_id=None, reason="missing_sig")

    try:
        manifest = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SignatureResult(valid=False, key_id=None, reason="bad_signature")

    if manifest.get("version") != SIG_VERSION or manifest.get("algo") != "ed25519":
        return SignatureResult(valid=False, key_id=manifest.get("key_id"), reason="bad_signature")

    key_id = manifest.get("key_id")
    if not key_id or key_id not in trust_roots:
        return SignatureResult(valid=False, key_id=key_id, reason="key_unknown")

    try:
        _ensure_crypto_available()
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return SignatureResult(valid=False, key_id=key_id, reason="bad_signature")

    body = skill_md_path.read_bytes()
    digest = hashlib.sha256(body).digest()
    if digest.hex() != manifest.get("content_hash"):
        return SignatureResult(valid=False, key_id=key_id, reason="hash_mismatch")

    try:
        pub_raw = base64.b64decode(trust_roots[key_id])
        sig_bytes = base64.b64decode(manifest["signature"])
        pub = Ed25519PublicKey.from_public_bytes(pub_raw)
        pub.verify(sig_bytes, digest)
    except (InvalidSignature, ValueError, TypeError):
        return SignatureResult(valid=False, key_id=key_id, reason="bad_signature")

    return SignatureResult(valid=True, key_id=key_id, reason="valid")


def generate_keypair() -> tuple[bytes, bytes]:
    """Helper for tests / docs: generate Ed25519 keypair.

    Returns (private_pem_bytes, public_raw_bytes_base64).
    """
    _ensure_crypto_available()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return pem, base64.b64encode(raw)
