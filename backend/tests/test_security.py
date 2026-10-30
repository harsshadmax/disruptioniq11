import jwt
import pytest

from app.auth.security import create_access_token, decode_token, hash_password, verify_password


def test_password_roundtrip_and_salting():
    h1 = hash_password("S3cret-pass", iterations=1000)
    h2 = hash_password("S3cret-pass", iterations=1000)
    assert h1 != h2  # random salt
    assert verify_password("S3cret-pass", h1)
    assert not verify_password("wrong", h1)


def test_verify_password_with_unknown_user_is_false_but_does_work():
    assert verify_password("anything", None) is False  # dummy hash path, no exception


def test_verify_password_rejects_malformed_hash():
    assert verify_password("x", "not-a-hash") is False


def test_token_roundtrip():
    payload = decode_token(create_access_token(7, "administrator"))
    assert payload["sub"] == "7"


def test_tampered_token_rejected():
    token = create_access_token(7, "administrator")
    with pytest.raises(jwt.PyJWTError):
        decode_token(token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
