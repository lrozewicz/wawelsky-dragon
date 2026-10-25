"""Testy integracyjne CLI rotacji klucza na MariaDB (brief E5-3/T1, kontrakt E5-3 C1/C2).

Wymagają stosu testowego (`eval "$(tools/dev/up.sh test env)"` + `up.sh test up mariadb-test`).
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from alembic import command
from app.core.config import Settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationFailed
from app.db.engine import database_url
from app.integrations.secrets import decrypt_secret, encrypt_secret
from app.tools import rotate_crypto_key
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

OLD = "a" * 64
NEW = "b" * 64
INTEGRATION_ID = 1
INTEGRATION_PLAIN = "sekret-integracji"

USER_ID = "u" * 32
DATASET_ID = "d" * 32
API_KEY_ID = "k" * 32
MODEL_ID = "m" * 32
INSTANCE_ID = "p" * 32
WEB_SEARCH_ID = "w" * 32
WEB_SEARCH_PLAIN = "ws-plain"

TIME_MS = 1790157600000
DATE = "2026-09-23 10:00:00.000"

ALL_ROWS = {
    "api_keys.token_enc": 1,
    "models.api_key_enc": 1,
    "provider_instances.api_key_enc": 1,
    "web_search_providers.api_key_enc": 1,
    "integrations.secret_enc": 1,
}
NO_ROWS = dict.fromkeys(ALL_ROWS, 0)


@pytest.fixture
def db(fresh_db: Settings) -> Iterator[Engine]:
    """Świeża baza po migracji do head + synchroniczny engine pymysql; dispose po teście."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    engine = create_engine(database_url(fresh_db, driver="pymysql"))
    yield engine
    engine.dispose()


def _provider_aad(instance_id: str) -> bytes:
    return b"provider-instance:" + instance_id.encode()


def _web_search_aad(provider_id: str) -> bytes:
    return b"web-search-provider:" + provider_id.encode()


def _seed(
    engine: Engine, *, corrupt_instance: bool = False, wrong_secret_aad: bool = False
) -> None:
    """Wstawia po jednym wierszu w każdej kolumnie C1, zaszyfrowanym OLD z właściwą AAD."""
    token_enc = encrypt(OLD, b"token-plain")
    model_enc = encrypt(OLD, b"model-plain")
    instance_enc = encrypt(OLD, b"inst-plain", _provider_aad(INSTANCE_ID))
    web_search_enc = encrypt(OLD, WEB_SEARCH_PLAIN.encode(), _web_search_aad(WEB_SEARCH_ID))
    if corrupt_instance:
        instance_enc = bytearray(instance_enc)
        instance_enc[-1] ^= 0x01
        instance_enc = bytes(instance_enc)
    secret_id = 999 if wrong_secret_aad else INTEGRATION_ID
    secret_enc, last4 = encrypt_secret(OLD, secret_id, INTEGRATION_PLAIN)
    with engine.begin() as conn:
        time_cols = {"t": TIME_MS, "d": DATE}
        conn.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date, update_time,"
                " update_date) VALUES (:id, :email, :nick, :t, :d, :t, :d)"
            ),
            {"id": USER_ID, "email": "rotate@example.test", "nick": "rotate", **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tid, :by, 'Korpus', 'fake-embed-1024', 1024, :t, :d, :t, :d)"
            ),
            {"id": DATASET_ID, "tid": USER_ID, "by": USER_ID, **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO api_keys (id, user_id, token_hash, token_enc, prefix, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (:id, :uid, :hash, :enc, 'ragflow-', :t, :d, :t, :d)"
            ),
            {"id": API_KEY_ID, "uid": USER_ID, "hash": "h" * 64, "enc": token_enc, **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO models (id, name, model_type, api_key_enc, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, 'rotate-test', 'chat', :enc, :t, :d, :t, :d)"
            ),
            {"id": MODEL_ID, "enc": model_enc, **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO provider_instances (id, name, base_url, api_key_enc, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (:id, 'rotate-inst', 'http://llm.local/v1', :enc, :t, :d, :t, :d)"
            ),
            {"id": INSTANCE_ID, "enc": instance_enc, **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO web_search_providers (id, provider, name, config, api_key_enc,"
                " is_default, create_time, create_date, update_time, update_date)"
                " VALUES (:id, 'tavily', 'rotate-ws', '{\"base_url\": \"http://ws.local\"}',"
                " :enc, 0, :t, :d, :t, :d)"
            ),
            {"id": WEB_SEARCH_ID, "enc": web_search_enc, **time_cols},
        )
        conn.execute(
            text(
                "INSERT INTO integrations (id, type, name, dataset_id, owner_id, config,"
                " ignored_extensions, secret_enc, secret_last4, created_at, updated_at)"
                " VALUES (:id, 'fake', 'rot', :did, :oid, '{}', '[]', :enc, :last4, :t, :t)"
            ),
            {
                "id": INTEGRATION_ID,
                "did": DATASET_ID,
                "oid": USER_ID,
                "enc": secret_enc,
                "last4": last4,
                "t": TIME_MS,
            },
        )


def _set_key_env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """Środowisko dla `main()`: baza świeżego testu + stary/nowy klucz."""
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
    monkeypatch.setenv("WD_CRYPTO_KEY", OLD)
    monkeypatch.setenv("WD_CRYPTO_KEY_NEW", NEW)


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_rotate_rewrites_all_columns_with_same_aad(db: Engine) -> None:
    _seed(db)
    with db.begin() as conn:
        counts = rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=False)
    assert counts == ALL_ROWS

    token = _scalar(db, "SELECT token_enc FROM api_keys WHERE id = :id", id=API_KEY_ID)
    assert decrypt(NEW, bytes(token)) == b"token-plain"
    with pytest.raises(ValidationFailed):
        decrypt(OLD, bytes(token))

    model = _scalar(db, "SELECT api_key_enc FROM models WHERE id = :id", id=MODEL_ID)
    assert decrypt(NEW, bytes(model)) == b"model-plain"
    with pytest.raises(ValidationFailed):
        decrypt(NEW, bytes(model), _provider_aad(INSTANCE_ID))

    instance = _scalar(
        db, "SELECT api_key_enc FROM provider_instances WHERE id = :id", id=INSTANCE_ID
    )
    assert decrypt(NEW, bytes(instance), _provider_aad(INSTANCE_ID)) == b"inst-plain"
    with pytest.raises(ValidationFailed):
        decrypt(NEW, bytes(instance), None)
    with pytest.raises(ValidationFailed):
        decrypt(OLD, bytes(instance), _provider_aad(INSTANCE_ID))

    web_search = _scalar(
        db, "SELECT api_key_enc FROM web_search_providers WHERE id = :id", id=WEB_SEARCH_ID
    )
    assert decrypt(NEW, bytes(web_search), _web_search_aad(WEB_SEARCH_ID)) == (
        WEB_SEARCH_PLAIN.encode()
    )
    with pytest.raises(ValidationFailed):
        decrypt(NEW, bytes(web_search), None)
    with pytest.raises(ValidationFailed):
        decrypt(OLD, bytes(web_search), _web_search_aad(WEB_SEARCH_ID))

    secret = _scalar(db, "SELECT secret_enc FROM integrations WHERE id = :id", id=INTEGRATION_ID)
    assert decrypt_secret(NEW, INTEGRATION_ID, str(secret)) == INTEGRATION_PLAIN
    with pytest.raises(ValidationFailed):
        decrypt_secret(OLD, INTEGRATION_ID, str(secret))
    # `secret_last4` nie zmienia się (C1).
    assert (
        _scalar(db, "SELECT secret_last4 FROM integrations WHERE id = :id", id=INTEGRATION_ID)
        == (INTEGRATION_PLAIN[-4:])
    )


def test_dry_run_leaves_rows_untouched(db: Engine) -> None:
    _seed(db)
    before = _snapshot(db)
    with db.begin() as conn:
        counts = rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=True)
    assert counts == ALL_ROWS
    assert _snapshot(db) == before


def test_main_dry_run_reports_ok_and_keeps_rows(
    db: Engine, fresh_db: Settings, monkeypatch, capsys
) -> None:
    _seed(db)
    before = _snapshot(db)
    _set_key_env(monkeypatch, fresh_db)
    assert rotate_crypto_key.main(["--dry-run"]) == 0
    captured = capsys.readouterr()
    assert "OK (dry-run)" in captured.out
    assert OLD not in captured.out + captured.err
    assert _snapshot(db) == before


def test_main_rolls_back_and_reports_corrupt_row(
    db: Engine, fresh_db: Settings, monkeypatch, capsys
) -> None:
    _seed(db, corrupt_instance=True)
    before = _snapshot(db)
    _set_key_env(monkeypatch, fresh_db)
    assert rotate_crypto_key.main([]) == 1
    captured = capsys.readouterr()
    assert f"cannot decrypt provider_instances.api_key_enc id={INSTANCE_ID}" in captured.err
    assert OLD not in captured.out + captured.err
    assert NEW not in captured.out + captured.err
    # Rollback: kolumny przetworzone wcześniej (api_keys, models) wciąż pod starym kluczem.
    assert _snapshot(db) == before
    assert (
        decrypt(
            OLD, bytes(_scalar(db, "SELECT token_enc FROM api_keys WHERE id = :id", id=API_KEY_ID))
        )
        == b"token-plain"
    )


def test_main_fails_when_integration_aad_lost(
    db: Engine, fresh_db: Settings, monkeypatch, capsys
) -> None:
    _seed(db, wrong_secret_aad=True)
    before = _snapshot(db)
    _set_key_env(monkeypatch, fresh_db)
    assert rotate_crypto_key.main([]) == 1
    captured = capsys.readouterr()
    assert f"cannot decrypt integrations.secret_enc id={INTEGRATION_ID}" in captured.err
    assert _snapshot(db) == before


def test_null_rows_are_skipped(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO models (id, name, model_type, create_time, create_date, update_time,"
                " update_date) VALUES (:id, 'nullable', 'embedding', :t, :d, :t, :d)"
            ),
            {"id": MODEL_ID, "t": TIME_MS, "d": DATE},
        )
    with db.begin() as conn:
        counts = rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=False)
    assert counts == NO_ROWS


def test_schema_guard_every_enc_column_is_in_columns(db: Engine, fresh_db: Settings) -> None:
    """Każda kolumna `*_enc` w schemacie po migracji musi być w COLUMNS (C1)."""
    with db.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA = :schema"
            ),
            {"schema": fresh_db.db_name},
        ).fetchall()
    found = {f"{table}.{column}" for table, column in rows if column.endswith("_enc")}
    assert found == {spec.key for spec in rotate_crypto_key.COLUMNS}


def _snapshot(engine: Engine) -> dict[str, object]:
    """Surowe wartości wszystkich 4 kolumn — do porównania „przed/po”."""
    return {
        "token_enc": bytes(
            _scalar(engine, "SELECT token_enc FROM api_keys WHERE id = :id", id=API_KEY_ID)
        ),
        "model_enc": bytes(
            _scalar(engine, "SELECT api_key_enc FROM models WHERE id = :id", id=MODEL_ID)
        ),
        "instance_enc": bytes(
            _scalar(
                engine,
                "SELECT api_key_enc FROM provider_instances WHERE id = :id",
                id=INSTANCE_ID,
            )
        ),
        "web_search_enc": bytes(
            _scalar(
                engine,
                "SELECT api_key_enc FROM web_search_providers WHERE id = :id",
                id=WEB_SEARCH_ID,
            )
        ),
        "secret_enc": str(
            _scalar(engine, "SELECT secret_enc FROM integrations WHERE id = :id", id=INTEGRATION_ID)
        ),
    }
