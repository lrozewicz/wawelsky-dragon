"""Harness złota v0.27.2 (K11 §5): procesy WD na świeżej bazie, replay runnerem recordera.

Runner recordera użyty bez kopiowania (``sys.path`` + leniwy ``load_runner()``); jedyna
dozwolona podmiana — ``runner._parse_body`` na wersję sortującą klucze — dzieje się
w fixture ``replay`` (conftest.py), plik recordera zostaje nietknięty.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

from alembic import command
from app.core.config import Settings
from tests.contract.ragflow.compare import SANCTIONED_UPLOAD_FILE  # noqa: F401 — re-eksport stałej
from tests.integration.conftest import _root_connection
from tests.integration.db.helpers import alembic_cfg, worker_db_name

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BACKEND_DIR.parent
RECORDER_DIR = REPO_DIR / "tools" / "contract-recorder"
SCENARIOS_DIR = RECORDER_DIR / "scenarios"
GOLDEN_DIR = BACKEND_DIR / "tests" / "contract" / "golden"
HERE = Path(__file__).resolve().parent
DEVIATIONS_DIR = HERE / "deviations"
DEVIATIONS_V024_DIR = DEVIATIONS_DIR / "v0.24.0"
SELFTEST_SCENARIOS_DIR = HERE / "scenarios_selftest"
SELFTEST_GOLDEN_DIR = HERE / "golden_selftest"

# Nagłówek zgodności shimu v0.24 (K11 §10d p. 15); dokładany do każdego żądania replayu v0.24.
COMPAT_HEADER: dict[str, str] = {"X-RAGFlow-Compat": "0.24"}


def v024_auth_headers(
    original: Callable[[Any, str], dict[str, str]],
) -> Callable[[Any, str], dict[str, str]]:
    """Opakowuje ``runner.auth_headers``: dokłada COMPAT_HEADER, zachowuje nagłówki oryginału.

    Oryginał jest zapamiętany przed podmianą (fixture ``replay``, monkeypatch) i wołany dla
    każdego kroku — dotyczy to także ``auth: none``/``bad`` (K11 §10d p. 15). Zwraca nowy dict,
    nie mutuje wyniku oryginału.
    """

    def wrapper(session: Any, mode: str) -> dict[str, str]:
        return {**original(session, mode), **COMPAT_HEADER}

    return wrapper


_READY_TIMEOUT_S = 60.0
_READY_INTERVAL_S = 0.5
_STOP_TIMEOUT_S = 15
_LOG_TAIL_LINES = 200

# Konto admina zakładane przez reset; te same wartości są domyślne w `app/api/wd/test_reset.py`.
ADMIN_EMAIL = "admin@wd.test"
ADMIN_PASSWORD = "wd-test-admin-1"  # noqa: S105 — stała testowa K9, nie sekret
# Drugie konto (bez modeli) — odpowiednik `recorder2` z `tools/contract-recorder/rf_bootstrap.py`;
# jego klucz API i JWT obsługują kroki `auth: second` i `auth: second_jwt`.
SECOND_EMAIL = "recorder2@wd.test"
SECOND_NICKNAME = "recorder2"
SECOND_PASSWORD = "wd-recorder2-1"  # noqa: S105 — stała testowa, nie sekret
_HTTP_TIMEOUT_S = 60.0


def load_runner() -> ModuleType:
    """Runner recordera (tools/contract-recorder/runner.py) importowany leniwie.

    Obraz test-ocr nie ma tools/ — modułowy import padał przy zbieraniu testów (krok binaries).
    """
    if str(RECORDER_DIR) not in sys.path:
        sys.path.insert(0, str(RECORDER_DIR))
    return importlib.import_module("runner")


def sorted_parse_body(response: httpx.Response) -> Any:
    """`response.json()` z rekurencyjnie posortowanymi kluczami dict (listy bez zmian)."""
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text
    return _sorted_keys(payload)


def _sorted_keys(value: Any) -> Any:
    """Rekurencyjne sortowanie kluczy dict; upstream Quart sortuje JSON, WD nie."""
    if isinstance(value, dict):
        return {key: _sorted_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_keys(item) for item in value]
    return value


@dataclass(frozen=True)
class ReplaySession:
    """Sesja przekazywana runnerowi scenariuszy.

    Pola są te same, których runner używa w ``RagflowSession`` recordera (``auth_headers``);
    modeli (``chat_model``/``embd_model``) nie ma, bo WD zasiewa je w resecie (K9 §3 p. 4),
    a runner ich nie czyta.
    """

    base_url: str
    api_key: str  # klucz API admina z resetu (krok `auth: key`)
    auth: str  # cały nagłówek Authorization z logowania admina (krok `auth: jwt`)
    api_key_2: str  # klucz API drugiego użytkownika (krok `auth: second`)
    auth_2: str  # cały nagłówek Authorization drugiego użytkownika (krok `auth: second_jwt`)


def _check(response: httpx.Response, step: str) -> dict[str, Any]:
    """Wymusza kopertę sukcesu WD (HTTP 200 i ``code == 0``); inaczej RuntimeError."""
    try:
        payload: Any = response.json()
    except ValueError as err:
        raise RuntimeError(
            f"{step}: HTTP {response.status_code}, odpowiedź nie jest JSON-em: "
            f"{response.text[:300]}"
        ) from err
    if (
        response.status_code != httpx.codes.OK
        or not isinstance(payload, dict)
        or payload.get("code") != 0
    ):
        raise RuntimeError(f"{step}: HTTP {response.status_code}: {response.text[:300]}")
    return payload


def _login(client: httpx.Client, email: str, password: str) -> str:
    """Logowanie lokalne (``POST /api/v1/auth/login``); zwraca całą wartość nagłówka Authorization.

    Hasło idzie jawnym tekstem — WD nie odtwarza szyfrowania RSA z ``rf_bootstrap``.
    """
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    _check(response, f"auth/login ({email})")
    auth = response.headers.get("Authorization")
    if not auth:
        raise RuntimeError(f"auth/login ({email}): brak nagłówka Authorization w odpowiedzi")
    return auth


def _register(client: httpx.Client, email: str, nickname: str, password: str) -> None:
    """Rejestracja konta (``POST /api/v1/users``) — wymaga ``WD_REGISTER_ENABLED=1`` w stosie."""
    _check(
        client.post(
            "/api/v1/users",
            json={"email": email, "nickname": nickname, "password": password},
        ),
        f"users/register ({email})",
    )


def _create_token(client: httpx.Client, auth: str) -> str:
    """Klucz API dla zalogowanego konta (``POST /api/v1/system/tokens``, ``data.token``)."""
    payload = _check(
        client.post("/api/v1/system/tokens", headers={"Authorization": auth}), "system/tokens"
    )
    data = payload["data"]
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError(f"system/tokens: brak data.token: {data}")
    return str(token)


@dataclass
class WdServer:
    """Działający stos WD: procesy api+worker na świeżej, zmigrowanej bazie."""

    base_url: str
    db_name: str
    storage_root: Path
    log_dir: Path

    def reset(self) -> str:
        """POST /api/wd/v1/test/reset (K9) z jawnymi danymi admina; zwraca `data.api_key`."""
        response = httpx.post(
            self.base_url + "/api/wd/v1/test/reset",
            json={"admin_email": ADMIN_EMAIL, "admin_password": ADMIN_PASSWORD},
            timeout=60,
        )
        if response.status_code != httpx.codes.OK:
            raise RuntimeError(
                f"reset: HTTP {response.status_code}: {response.text}\n{self.logs()}"
            )
        return str(response.json()["data"]["api_key"])

    def reset_session(self) -> ReplaySession:
        """Reset (K9) + sesja runnera: klucz i JWT admina oraz klucz i JWT drugiego użytkownika.

        Drugie konto powstaje publicznym API WD (rejestracja, login, klucz) — jak `recorder2`
        w `rf_bootstrap.py`; nie ma modeli i nie widzi zasobów admina.
        """
        api_key = self.reset()
        with httpx.Client(base_url=self.base_url, timeout=_HTTP_TIMEOUT_S) as client:
            auth = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
            _register(client, SECOND_EMAIL, SECOND_NICKNAME, SECOND_PASSWORD)
            auth_2 = _login(client, SECOND_EMAIL, SECOND_PASSWORD)
            api_key_2 = _create_token(client, auth_2)
        return ReplaySession(
            base_url=self.base_url,
            api_key=api_key,
            auth=auth,
            api_key_2=api_key_2,
            auth_2=auth_2,
        )

    def logs(self) -> str:
        """Ostatnie 200 linii logów api i worker — do komunikatów błędów."""
        parts: list[str] = []
        for name in ("api.log", "worker.log"):
            path = self.log_dir / name
            parts.append(f"--- {name} ---")
            if path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                parts.extend(lines[-_LOG_TAIL_LINES:])
        return "\n".join(parts)


def _free_port() -> int:
    """Wolny port TCP na 127.0.0.1: bind na 0, odczyt, zamknięcie."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _drop_db(name: str) -> None:
    """DROP DATABASE IF EXISTS jako root (sprzątanie po bazie testowej)."""
    conn = _root_connection()
    try:
        with conn.cursor() as cursor:
            # Nazwy bazy nie da się wiązać parametrem (identyfikator DDL); name z uuid4().hex.
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
    finally:
        conn.close()


def _spawn(log_dir: Path, env: dict[str, str], port: int) -> list[subprocess.Popen[bytes]]:
    """Start procesów api (uvicorn, --factory) i worker; logi obu do plików w log_dir."""
    procs: list[subprocess.Popen[bytes]] = []
    with (
        (log_dir / "api.log").open("wb") as api_log,
        (log_dir / "worker.log").open("wb") as worker_log,
    ):
        procs.append(
            subprocess.Popen(  # noqa: S603  (stała lista argumentów, bez wejścia z zewnątrz)
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=BACKEND_DIR,
                env=env,
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
        )
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "app.worker.main"],
                cwd=BACKEND_DIR,
                env=env,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
            )
        )
    return procs


def _wait_ready(server: WdServer, procs: list[subprocess.Popen[bytes]]) -> None:
    """Poll `/health/ready` co 0,5 s do 200 (max 60 s); pad procesu → RuntimeError z logami."""
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while True:
        for proc in procs:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"proces zakończony przedwcześnie (kod {proc.returncode}): "
                    f"{proc.args}\n{server.logs()}"
                )
        with contextlib.suppress(httpx.HTTPError):
            if (
                httpx.get(server.base_url + "/health/ready", timeout=5).status_code
                == httpx.codes.OK
            ):
                return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"brak gotowości /health/ready po {_READY_TIMEOUT_S} s\n{server.logs()}"
            )
        time.sleep(_READY_INTERVAL_S)


@contextlib.contextmanager
def start_server(tmp: Path, port: int | None = None) -> Iterator[WdServer]:
    """Stawia WD (api+worker) na świeżej bazie `wd_h_*`; sprząta procesy i bazę w finally.

    Kolejność: baza → migracja alembic → procesy → gotowość /health/ready. Sprzątanie
    zadziała także wtedy, gdy któryś krok rzuci wyjątek (procesy/baza już istnieją).
    `port=None` (domyślnie) bierze wolny port (`_free_port`); podany port jest wymagany przez
    harness `tests/contract/upstream` (E2-3f), który ustala `HOST_ADDRESS` przed importem `configs`.
    """
    name = worker_db_name("wd_h")
    conn = _root_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'wawelsky'@'%'")
    finally:
        conn.close()
    procs: list[subprocess.Popen[bytes]] = []
    try:
        settings = Settings(env="test", db_name=name)
        command.upgrade(alembic_cfg(settings), "head")
        log_dir = tmp / "logs"
        storage_root = tmp / "storage"
        log_dir.mkdir(parents=True, exist_ok=True)
        storage_root.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ) | {
            "WD_ENV": "test",
            "WD_DB_NAME": name,
            "WD_STORAGE_ROOT": str(storage_root),
            "WD_SECRET_KEY": "s" * 48,
            "WD_CRYPTO_KEY": "ab" * 32,
            "WD_ADMIN_EMAIL": "",
            "WD_ADMIN_PASSWORD": "",
            # Rejestracja otwarta — harness zakłada drugie konto przez `POST /api/v1/users`
            # (w compose recordera odpowiada temu `REGISTER_ENABLED: "1"`).
            "WD_REGISTER_ENABLED": "1",
            "WD_LOG_FORMAT": "console",
            # Replay porównuje tekst promptu ze złotem upstreamu, w którym katalogu bazy nie ma
            # (K21 §3). Katalog wyłączony w tym fixture (niezwiązanym z cechą mapy bazy);
            # zachowanie katalogu/mapy pokrywają testy T5 (DEC-366).
            "WD_CHAT_KB_CATALOG_TOKENS": "0",
        }
        server = WdServer(
            base_url=f"http://127.0.0.1:{port if port is not None else _free_port()}",
            db_name=name,
            storage_root=storage_root,
            log_dir=log_dir,
        )
        procs = _spawn(log_dir, env, int(server.base_url.rsplit(":", 1)[1]))
        _wait_ready(server, procs)
        yield server
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        _drop_db(name)
