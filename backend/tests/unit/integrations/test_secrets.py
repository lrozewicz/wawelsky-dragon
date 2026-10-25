"""Testy sekretów integracji: format `v1:` z AAD per integracja (WP E4-2b, 09 §11)."""

import pytest

from app.core.errors import ValidationFailed
from app.integrations.secrets import decrypt_secret, encrypt_secret

KEY = "00" * 32
OTHER_KEY = "11" * 32
INTEGRATION_ID = 7
SECRET = "s3cret"  # noqa: S105 — sekret wyłącznie testowy
LAST4 = "cret"
PARTS = 3


def test_encrypt_secret_format() -> None:
    enc, last4 = encrypt_secret(KEY, INTEGRATION_ID, SECRET)
    assert enc.startswith("v1:")
    assert len(enc.split(":")) == PARTS
    assert last4 == LAST4


def test_encrypt_secret_hides_plaintext() -> None:
    enc, _ = encrypt_secret(KEY, INTEGRATION_ID, SECRET)
    assert SECRET not in enc


def test_roundtrip() -> None:
    enc, _ = encrypt_secret(KEY, INTEGRATION_ID, SECRET)
    assert decrypt_secret(KEY, INTEGRATION_ID, enc) == SECRET


def test_other_integration_id_rejected() -> None:
    enc, _ = encrypt_secret(KEY, INTEGRATION_ID, SECRET)
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt_secret(KEY, INTEGRATION_ID + 1, enc)
    assert exc_info.value.message == "cannot decrypt"


def test_wrong_key_rejected() -> None:
    enc, _ = encrypt_secret(KEY, INTEGRATION_ID, SECRET)
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt_secret(OTHER_KEY, INTEGRATION_ID, enc)
    assert exc_info.value.message == "cannot decrypt"


@pytest.mark.parametrize("enc", ["", "garbage", "v2:a:b", "v1:onlytwo", "v1:a:b:c", "v1:!!!:!!!"])
def test_malformed_enc_rejected(enc: str) -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt_secret(KEY, INTEGRATION_ID, enc)
    assert exc_info.value.message == "cannot decrypt"
