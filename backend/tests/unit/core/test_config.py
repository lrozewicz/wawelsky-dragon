"""Testy Settings wg kontraktu C1 — przykłady z briefu T1 (tabela wejście → wyjście)."""

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DEFAULT_DB_HOST = "mariadb"
DEFAULT_DB_PORT = 3306
DEFAULT_MAX_PAGE_SIZE = 1000
DEFAULT_LLM_VLM = "openai/gpt-4.1-mini"
DEFAULT_MIN_VECTOR_SIM = 0.25
DEFAULT_MIN_RERANK_SCORE = 0.1
DEFAULT_EXPORT_MAX_BYTES = 2_147_483_648
DEFAULT_KB_CATALOG_TOKENS = 1500
DEFAULT_KB_MAP_TOKENS = 6000
DEFAULT_OUTLINE_SWEEP_S = 600
OVERRIDDEN_EXPORT_MAX_BYTES = 1_073_741_824
OVERRIDDEN_DB_PORT = 3307
SECRET_KEY_OK = "x" * 32
SECRET_KEY_TOO_SHORT = "x" * 31
CRYPTO_KEY_OK = "ab" * 32
CRYPTO_KEY_BAD = "zz" * 32
PROD_DB_PASSWORD = "p"  # noqa: S105 — celowe atrapa hasła w teście
PROD_LLM_URL = "http://llm"


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od env procesu (verify.sh eksportuje WD_DB_* itd.)."""
    for name in [key for key in os.environ if key.startswith("WD_")]:
        monkeypatch.delenv(name, raising=False)


def test_dev_defaults() -> None:
    settings = Settings(env="dev")
    assert settings.db_host == DEFAULT_DB_HOST
    assert settings.db_port == DEFAULT_DB_PORT
    assert settings.max_page_size == DEFAULT_MAX_PAGE_SIZE
    assert settings.llm_default_vlm == DEFAULT_LLM_VLM
    assert settings.hub_compat_routes is True


def test_no_env_is_prod_and_requires_secrets() -> None:
    with pytest.raises(ValidationError) as err:
        Settings()
    message = str(err.value)
    for name in ("WD_DB_PASSWORD", "WD_SECRET_KEY", "WD_CRYPTO_KEY", "WD_LLM_BASE_URL"):
        assert name in message


def test_prod_with_secrets_is_valid() -> None:
    settings = Settings(
        env="prod",
        db_password=PROD_DB_PASSWORD,
        secret_key=SECRET_KEY_OK,
        crypto_key=CRYPTO_KEY_OK,
        llm_base_url=PROD_LLM_URL,
    )
    assert settings.env == "prod"


def test_prod_secret_key_too_short() -> None:
    with pytest.raises(ValidationError, match="WD_SECRET_KEY must be at least 32 bytes"):
        Settings(
            env="prod",
            db_password=PROD_DB_PASSWORD,
            secret_key=SECRET_KEY_TOO_SHORT,
            crypto_key=CRYPTO_KEY_OK,
            llm_base_url=PROD_LLM_URL,
        )


def test_prod_crypto_key_not_hex() -> None:
    with pytest.raises(ValidationError, match="WD_CRYPTO_KEY"):
        Settings(
            env="prod",
            db_password=PROD_DB_PASSWORD,
            secret_key=SECRET_KEY_OK,
            crypto_key=CRYPTO_KEY_BAD,
            llm_base_url=PROD_LLM_URL,
        )


def test_test_env_allows_empty_secrets() -> None:
    Settings(env="test", secret_key="")


def test_cors_wildcard_rejected() -> None:
    with pytest.raises(ValidationError, match="WD_CORS_ORIGINS"):
        Settings(env="dev", cors_origins="https://a.pl, *")


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WD_ENV", "dev")
    monkeypatch.setenv("WD_DB_PORT", str(OVERRIDDEN_DB_PORT))
    settings = Settings()
    assert settings.env == "dev"
    assert settings.db_port == OVERRIDDEN_DB_PORT


def test_model_dump_json_masks_secret() -> None:
    settings = Settings(env="dev", db_password="tajne")  # noqa: S106 — atrapa
    assert "tajne" not in settings.model_dump_json()


def test_retrieval_defaults() -> None:
    """Domyślne pola retrievalu wg K8 część A (brief T4)."""
    settings = Settings(env="dev")
    assert settings.retrieval_fusion == "weighted"
    assert settings.min_vector_sim == DEFAULT_MIN_VECTOR_SIM
    assert settings.min_rerank_score == DEFAULT_MIN_RERANK_SCORE


def test_retrieval_fusion_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WD_RETRIEVAL_FUSION=rrf` nadpisuje domyślne (brief T4)."""
    monkeypatch.setenv("WD_RETRIEVAL_FUSION", "rrf")
    settings = Settings(env="dev")
    assert settings.retrieval_fusion == "rrf"


def test_retrieval_fusion_outside_literal_rejected() -> None:
    """Wartość spoza `Literal["weighted", "rrf"]` → ValidationError (brief T4)."""
    with pytest.raises(ValidationError, match="retrieval_fusion"):
        Settings(env="dev", retrieval_fusion="max")


def test_export_max_bytes_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`export_max_bytes` domyślnie 2 GiB, `WD_EXPORT_MAX_BYTES` nadpisuje (K19 §6)."""
    assert Settings(env="dev").export_max_bytes == DEFAULT_EXPORT_MAX_BYTES
    monkeypatch.setenv("WD_EXPORT_MAX_BYTES", str(OVERRIDDEN_EXPORT_MAX_BYTES))
    assert Settings(env="dev").export_max_bytes == OVERRIDDEN_EXPORT_MAX_BYTES


def test_kb_catalog_map_and_sweep_defaults() -> None:
    """Domyślne budżety katalogu/mapy bazy i odstęp przeglądu spisu (K21 §3, §4, §2 p. 4).

    Fixture `_clean_wd_env` czyści `WD_*`, więc odczyt trafia w wartości domyślne kodu.
    """
    settings = Settings(env="dev")
    assert settings.chat_kb_catalog_tokens == DEFAULT_KB_CATALOG_TOKENS
    assert settings.chat_kb_map_tokens == DEFAULT_KB_MAP_TOKENS
    assert settings.outline_sweep_s == DEFAULT_OUTLINE_SWEEP_S
