"""Tests for the optional crypto-signing path."""

from __future__ import annotations

import importlib.util

import pytest

if importlib.util.find_spec("cryptography") is None:
    pytest.skip("cryptography not installed (signing extras)", allow_module_level=True)


from skills_radar.signing import (
    SIG_FILENAME,
    generate_keypair,
    sign_skill,
    verify_skill,
)


def _write_skill(tmp_path):
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: test-skill\ndescription: Test.\n---\n\nBody content.")
    return skill_md


def test_generate_keypair_basic():
    pem, pub_b64 = generate_keypair()
    assert b"BEGIN PRIVATE KEY" in pem
    assert isinstance(pub_b64, bytes)
    # raw Ed25519 = 32 bytes → base64 ≈ 44 chars
    assert 40 <= len(pub_b64) <= 50


def test_sign_and_verify_round_trip(tmp_path):
    skill_md = _write_skill(tmp_path)
    pem, pub_b64 = generate_keypair()
    pem_path = tmp_path / "signing.key"
    pem_path.write_bytes(pem)

    sig_path = sign_skill(skill_md, pem_path, key_id="test-2026")
    assert sig_path.name == SIG_FILENAME
    assert sig_path.exists()

    result = verify_skill(skill_md, trust_roots={"test-2026": pub_b64.decode()})
    assert result.valid is True
    assert result.key_id == "test-2026"
    assert result.reason == "valid"


def test_verify_missing_signature(tmp_path):
    skill_md = _write_skill(tmp_path)
    result = verify_skill(skill_md, trust_roots={})
    assert result.valid is False
    assert result.reason == "missing_sig"


def test_verify_unknown_key(tmp_path):
    skill_md = _write_skill(tmp_path)
    pem, _pub_b64 = generate_keypair()
    pem_path = tmp_path / "signing.key"
    pem_path.write_bytes(pem)
    sign_skill(skill_md, pem_path, key_id="unknown-key")

    # Verifier doesn't know this key
    result = verify_skill(skill_md, trust_roots={"different-key": "AAAA"})
    assert result.valid is False
    assert result.reason == "key_unknown"
    assert result.key_id == "unknown-key"


def test_verify_hash_mismatch_after_tamper(tmp_path):
    skill_md = _write_skill(tmp_path)
    pem, pub_b64 = generate_keypair()
    pem_path = tmp_path / "signing.key"
    pem_path.write_bytes(pem)
    sign_skill(skill_md, pem_path, key_id="test-2026")

    # Tamper with the body
    skill_md.write_text("---\nname: test-skill\ndescription: Test.\n---\n\nTampered.")

    result = verify_skill(skill_md, trust_roots={"test-2026": pub_b64.decode()})
    assert result.valid is False
    assert result.reason == "hash_mismatch"


def test_verify_bad_signature_with_wrong_key(tmp_path):
    skill_md = _write_skill(tmp_path)
    pem, _pub_b64 = generate_keypair()
    pem_path = tmp_path / "signing.key"
    pem_path.write_bytes(pem)
    sign_skill(skill_md, pem_path, key_id="test-2026")

    # Trust root contains a DIFFERENT public key with the SAME id
    _other_pem, other_pub = generate_keypair()
    result = verify_skill(skill_md, trust_roots={"test-2026": other_pub.decode()})
    assert result.valid is False
    assert result.reason == "bad_signature"


def test_verify_bad_json_in_sig_file(tmp_path):
    skill_md = _write_skill(tmp_path)
    sig_path = skill_md.parent / SIG_FILENAME
    sig_path.write_text("not json at all")
    result = verify_skill(skill_md, trust_roots={})
    assert result.valid is False
    assert result.reason == "bad_signature"
