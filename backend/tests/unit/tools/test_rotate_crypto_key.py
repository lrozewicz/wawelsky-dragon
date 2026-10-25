"""Testy jednostkowe CLI rotacji klucza (brief E5-3/T1, kontrakt E5-3 C1/C2) — bez bazy."""

import contextlib

import pytest

from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationFailed
from app.integrations.secrets import decrypt_secret, encrypt_secret
from app.tools import rotate_crypto_key

OLD = "0" * 64
NEW = "1" * 64
_INTEGRATION_ID = 7
_EXIT_CONFIG = 2
_COLUMN_COUNT = 5
_BLOB_UPDATES = 3


def _provider_aad(instance_id: str) -> bytes:
    return b"provider-instance:" + instance_id.encode()


def _web_search_aad(provider_id: str) -> bytes:
    return b"web-search-provider:" + provider_id.encode()


class _Result:
    """Atrapa wyniku SELECT: tylko `fetchall`."""

    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, object]]:
        return list(self._rows)


class _FakeConn:
    """Atrapa połączenia SQLAlchemy — rejestruje SELECT-y i UPDATE-y, nie dotyka bazy."""

    def __init__(self, rows_by_table: dict[str, list[tuple[object, object]]] | None = None) -> None:
        self.rows_by_table = rows_by_table or {}
        self.selects: list[str] = []
        self.updates: list[tuple[str, dict[str, object]]] = []

    def exec_driver_sql(self, sql: str) -> _Result:
        self.selects.append(sql)
        table = sql.split(" FROM ")[1].split(" ", maxsplit=1)[0]
        return _Result(self.rows_by_table.get(table, []))

    def execute(self, statement: object, params: dict[str, object]) -> None:
        self.updates.append((str(statement), params))


class _FakeEngine:
    """Atrapa silnika: `begin()` daje atrapę połączenia, `dispose()` nic nie robi."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self.disposed = False

    def begin(self) -> contextlib.AbstractContextManager[_FakeConn]:
        return contextlib.nullcontext(self._conn)

    def dispose(self) -> None:
        self.disposed = True


def _rows_by_table() -> dict[str, list[tuple[object, object]]]:
    """Po jednym wierszu w każdej kolumnie, zaszyfrowanym starym kluczem z właściwą AAD."""
    instance_id = "p" * 32
    web_search_id = "w" * 32
    return {
        "api_keys": [("a" * 32, encrypt(OLD, b"token-tajny"))],
        "models": [("m" * 32, encrypt(OLD, b"model-tajny"))],
        "provider_instances": [
            (instance_id, encrypt(OLD, b"inst-tajny", _provider_aad(instance_id)))
        ],
        "web_search_providers": [
            (web_search_id, encrypt(OLD, b"ws-tajny", _web_search_aad(web_search_id)))
        ],
        "integrations": [(_INTEGRATION_ID, encrypt_secret(OLD, _INTEGRATION_ID, "sekret-int")[0])],
    }


def test_columns_are_all_encrypted_columns() -> None:
    keys = [spec.key for spec in rotate_crypto_key.COLUMNS]
    assert keys == [
        "api_keys.token_enc",
        "models.api_key_enc",
        "provider_instances.api_key_enc",
        "web_search_providers.api_key_enc",
        "integrations.secret_enc",
    ]


def test_rotate_dry_run_counts_every_column_without_update() -> None:
    conn = _FakeConn(_rows_by_table())
    counts = rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=True)
    assert counts == {
        "api_keys.token_enc": 1,
        "models.api_key_enc": 1,
        "provider_instances.api_key_enc": 1,
        "web_search_providers.api_key_enc": 1,
        "integrations.secret_enc": 1,
    }
    assert conn.updates == []
    assert len(conn.selects) == _COLUMN_COUNT


def test_rotate_rewrites_each_blob_with_its_aad() -> None:
    conn = _FakeConn(_rows_by_table())
    rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=False)

    by_column = {stmt.split(" SET ")[1].split(" = ")[0]: params for stmt, params in conn.updates}
    assert set(by_column) == {"token_enc", "api_key_enc", "secret_enc"}

    token = by_column["token_enc"]["v"]
    assert decrypt(NEW, token) == b"token-tajny"
    with pytest.raises(ValidationFailed):
        decrypt(OLD, token)

    # api_key_enc występuje dwa razy — rozróżniamy po AAD: instancja ma AAD, model nie ma.
    instance_id = "p" * 32
    blobs = [
        params["v"]
        for stmt, params in conn.updates
        if stmt.split(" SET ")[1].startswith("api_key_enc")
    ]
    assert len(blobs) == _BLOB_UPDATES
    aaded = decrypt(NEW, blobs[1], _provider_aad(instance_id))
    assert aaded == b"inst-tajny"
    with pytest.raises(ValidationFailed):
        decrypt(NEW, blobs[1], None)
    assert decrypt(NEW, blobs[0], None) == b"model-tajny"
    with pytest.raises(ValidationFailed):
        decrypt(NEW, blobs[0], _provider_aad(instance_id))
    web_search_id = "w" * 32
    assert decrypt(NEW, blobs[2], _web_search_aad(web_search_id)) == b"ws-tajny"
    with pytest.raises(ValidationFailed):
        decrypt(NEW, blobs[2], None)

    secret = by_column["secret_enc"]["v"]
    assert decrypt_secret(NEW, _INTEGRATION_ID, secret) == "sekret-int"
    with pytest.raises(ValidationFailed):
        decrypt_secret(OLD, _INTEGRATION_ID, secret)


def test_rotate_skips_null_rows() -> None:
    conn = _FakeConn({})
    counts = rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=False)
    assert counts == {
        "api_keys.token_enc": 0,
        "models.api_key_enc": 0,
        "provider_instances.api_key_enc": 0,
        "web_search_providers.api_key_enc": 0,
        "integrations.secret_enc": 0,
    }
    assert conn.updates == []


def test_rotate_reports_corrupt_row_without_leaking_content() -> None:
    instance_id = "p" * 32
    blob = bytearray(encrypt(OLD, b"inst-tajny", _provider_aad(instance_id)))
    blob[-1] ^= 0x01
    conn = _FakeConn({"provider_instances": [(instance_id, bytes(blob))]})
    with pytest.raises(ValidationFailed) as excinfo:
        rotate_crypto_key.rotate(conn, OLD, NEW, dry_run=False)
    message = str(excinfo.value)
    assert f"cannot decrypt provider_instances.api_key_enc id={instance_id}" == message
    assert OLD not in message
    assert NEW not in message


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (OLD, None),
        (OLD, OLD),
        (OLD, "not-hex"),
        (None, NEW),
        ("abc", NEW),
    ],
)
def test_main_rejects_bad_key_config_with_code_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    old: str | None,
    new: str | None,
) -> None:
    if old is None:
        monkeypatch.delenv("WD_CRYPTO_KEY", raising=False)
    else:
        monkeypatch.setenv("WD_CRYPTO_KEY", old)
    if new is None:
        monkeypatch.delenv("WD_CRYPTO_KEY_NEW", raising=False)
    else:
        monkeypatch.setenv("WD_CRYPTO_KEY_NEW", new)

    assert rotate_crypto_key.main([]) == _EXIT_CONFIG
    captured = capsys.readouterr()
    for value in (old, new):
        if value:
            assert value not in captured.out + captured.err


def test_main_prints_counts_and_ok_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _FakeConn(_rows_by_table())
    engine = _FakeEngine(conn)
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_CRYPTO_KEY", OLD)
    monkeypatch.setenv("WD_CRYPTO_KEY_NEW", NEW)
    monkeypatch.setattr(rotate_crypto_key, "create_engine", lambda _url: engine)

    assert rotate_crypto_key.main([]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "api_keys.token_enc: 1" in lines
    assert "models.api_key_enc: 1" in lines
    assert "provider_instances.api_key_enc: 1" in lines
    assert "web_search_providers.api_key_enc: 1" in lines
    assert "integrations.secret_enc: 1" in lines
    assert lines[-1] == "OK"
    combined = captured.out + captured.err
    assert OLD not in combined
    assert NEW not in combined
    assert "tajny" not in combined
    assert engine.disposed
