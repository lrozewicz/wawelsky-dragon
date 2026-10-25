"""Bootstrap konta i modeli w RAGFlow dla contract-recordera (SP-5, kontrakt C2).

Sekwencja krokow odtwarza upstreamowe testy HTTP (test/testcases/conftest.py) danej wersji:
- v0.24.0: /v1/user/register, /v1/llm/add_llm, /v1/user/set_tenant_info, /v1/system/new_token;
- v0.27.2: /api/v1/users, /api/v1/providers + /instances, /api/v1/models/default, /api/v1/system/tokens.
Wersje API nie przyjmuje sie z parametru — rozpoznaje sie je po trasie /system/ping.
"""

import base64
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from Cryptodome.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
from Cryptodome.PublicKey import RSA

RECORD_EMAIL = "recorder@wd.test"
RECORD_NICKNAME = "recorder"
RECORD_PASSWORD = "recorder123"
# Drugi uzytkownik (C3): wlasny klucz API do scenariuszy z auth: second, bez modeli.
RECORD_EMAIL_2 = "recorder2@wd.test"
RECORD_NICKNAME_2 = "recorder2"
FACTORY = "OpenAI-API-Compatible"
INSTANCE_NAME = "recorder"
FAKE_CHAT_MODEL = "fake-chat"
FAKE_EMBEDDING_MODEL = "fake-embed-1024"
FAKE_LLM_BASE_URL = "http://fake-llm:8090/v1"
FAKE_LLM_API_KEY = "x"
POLL_INTERVAL_S = 5.0

# Klucz publiczny conf/public.pem z repo upstream — haslo przed wyslaniem szyfruje nim
# api/utils/crypt.py (crypt()), ten sam plik jest w tagach v0.24.0 i v0.27.2
# (identyczna suma md5 6a1b37f3204bcc64a463311c95ac4a81).
_PUBLIC_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArq9XTUSeYr2+N1h3Afl/
z8Dse/2yD0ZGrKwx+EEEcdsBLca9Ynmx3nIB5obmLlSfmskLpBo0UACBmB5rEjBp
2Q2f3AG3Hjd4B+gNCG6BDaawuDlgANIhGnaTLrIqWrrcm4EMzJOnAOI1fgzJRsOO
UEfaS318Eq9OVO3apEyCCt0lOQK6PuksduOjVxtltDav+guVAA068NrPYmRNabVK
RNLJpL8w4D44sfth5RvZ3q9t+6RTArpEtc5sh5ChzvqPOzKGMXW83C95TxmXqpbK
6olN4RevSfVjEAgCydH6HN6OhtOQEcnrU97r9H0iZOWwbw3pVrZiUkuRD1R56Wzs
2wIDAQAB
-----END PUBLIC KEY-----
"""


@dataclass(frozen=True)
class RagflowSession:
    base_url: str  # np. "http://host.docker.internal:18380"
    api_key: str  # token z /v1/system/new_token (Bearer dla /api/v1/*)
    auth: str  # nagłówek Authorization z /v1/user/login (dla /v1/*)
    chat_model: str  # llm_id ustawiony w tenant_info (dokładnie jak zwraca RAGFlow, np. "fake-chat___OpenAI-API@OpenAI-API-Compatible")
    embd_model: str  # embd_id ustawiony w tenant_info
    api_key_2: str = ""  # klucz API drugiego uzytkownika (auth: second)
    auth_2: str = ""  # JWT drugiego uzytkownika (auth: second_jwt)


def _encrypt_password(password: str) -> str:
    """Szyfruje haslo jak frontend upstream (api/utils/crypt.py: crypt())."""
    rsa_key = RSA.importKey(_PUBLIC_PEM, "Welcome")
    cipher = Cipher_pkcs1_v1_5.new(rsa_key)
    password_base64 = base64.b64encode(password.encode("utf-8")).decode("utf-8")
    encrypted = cipher.encrypt(password_base64.encode())
    return base64.b64encode(encrypted).decode("utf-8")


def _check(resp: httpx.Response, step: str) -> dict:
    """Wymusza JSON z code == 0; inaczej RuntimeError z nazwa kroku i trescia odpowiedzi."""
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"{step}: HTTP {resp.status_code}, odpowiedz nie jest JSON-em: {resp.text[:300]}"
        ) from exc
    if payload.get("code") != 0:
        raise RuntimeError(
            f"{step}: HTTP {resp.status_code}, code={payload.get('code')}: {str(payload.get('message'))[:300]}"
        )
    return payload


def wait_ready(base_url: str, timeout_s: float = 900.0) -> None:
    """Czeka (co 5 s), az GET /v1/system/healthz zwroci 200 — trasa istnieje w obu tagach
    (v0.24.0 natywnie, v0.27.2 jako trasa zgodnosci). Po timeout_s wyjatek TimeoutError."""
    deadline = time.monotonic() + timeout_s
    last = "nie odpytano"
    with httpx.Client(timeout=10.0) as client:
        while True:
            try:
                resp = client.get(f"{base_url}/v1/system/healthz")
                if resp.status_code == 200:
                    return
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except httpx.HTTPError as exc:
                last = repr(exc)
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"RAGFlow {base_url} nie gotowy po {timeout_s}s; ostatnia odpowiedz: {last}"
                )
            time.sleep(POLL_INTERVAL_S)


def _api_prefix(client: httpx.Client) -> str:
    """Rozpoznaje plyt API: 'api/v1' (v0.27.2, RESTful) albo 'v1' (v0.24.0, legacy)."""
    for prefix in ("api/v1", "v1"):
        try:
            resp = client.get(f"/{prefix}/system/ping")
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            return prefix
    raise RuntimeError(
        "Nie rozpoznano API RAGFlow: ani /api/v1/system/ping, ani /v1/system/ping nie odpowiadaja 200"
    )


def _register_and_login(
    client: httpx.Client,
    prefix: str,
    email: str = RECORD_EMAIL,
    nickname: str = RECORD_NICKNAME,
) -> str:
    """Rejestruje konto (jak conftest upstream, 'has already registered' tolerowane)
    i loguje sie; zwraca wartosc naglowka Authorization. Domyslnie konto 1 (recorder),
    a para (email, nickname) obsluguje tez konto 2 (recorder2)."""
    register_path = "/users" if prefix == "api/v1" else "/user/register"
    login_path = "/auth/login" if prefix == "api/v1" else "/user/login"
    encrypted = _encrypt_password(RECORD_PASSWORD)
    resp = client.post(
        f"/{prefix}{register_path}",
        json={
            "email": email,
            "nickname": nickname,
            "password": encrypted,
        },
    )
    try:
        _check(resp, "register")
    except RuntimeError as exc:
        if "has already registered" not in str(exc):
            raise
    resp = client.post(
        f"/{prefix}{login_path}", json={"email": email, "password": encrypted}
    )
    _check(resp, "login")
    auth = resp.headers.get("Authorization")
    if not auth:
        raise RuntimeError("login: brak naglowka Authorization w odpowiedzi")
    return auth


def _create_token(client: httpx.Client, prefix: str, auth: str) -> str:
    """Tworzy klucz API dla zalogowanego konta C3: v0.24.0 `POST /v1/system/new_token`,
    v0.27.2 `POST /api/v1/system/tokens`; klucz siedzi w ["data"]["token"]."""
    path = "/system/tokens" if prefix == "api/v1" else "/system/new_token"
    payload = _check(
        client.post(f"/{prefix}{path}", headers={"Authorization": auth}), "create_token"
    )
    return payload["data"]["token"]


def _bootstrap_legacy(client: httpx.Client, auth: str) -> tuple[str, str, str]:
    """v0.24.0: add_llm (czat + embedding), my_llms, set_tenant_info, new_token."""
    headers = {"Authorization": auth}
    for model_type, llm_name in (
        ("chat", FAKE_CHAT_MODEL),
        ("embedding", FAKE_EMBEDDING_MODEL),
    ):
        _check(
            client.post(
                "/v1/llm/add_llm",
                headers=headers,
                json={
                    "llm_factory": FACTORY,
                    "model_type": model_type,
                    "llm_name": llm_name,
                    "api_base": FAKE_LLM_BASE_URL,
                    "api_key": FAKE_LLM_API_KEY,
                    # kolumna tenant_llm.max_tokens jest NOT NULL — frontend zawsze wysyla wartosc
                    "max_tokens": 8192,
                },
            ),
            f"add_llm ({model_type})",
        )
    my_llms = _check(client.get("/v1/llm/my_llms", headers=headers), "my_llms")["data"]
    entries = my_llms.get(FACTORY, {}).get("llm", [])
    # RAGFlow dopisuje sufiks fabryki (np. "___OpenAI-API") — czytamy faktyczne nazwy.
    chat_name = next((e["name"] for e in entries if e.get("type") == "chat"), None)
    embd_name = next((e["name"] for e in entries if e.get("type") == "embedding"), None)
    if not chat_name or not embd_name:
        raise RuntimeError(
            f"my_llms: brak zarejestrowanych modeli {FACTORY}: {entries}"
        )
    tenant = _check(client.get("/v1/user/tenant_info", headers=headers), "tenant_info")[
        "data"
    ]
    _check(
        client.post(
            "/v1/user/set_tenant_info",
            headers=headers,
            json={
                "tenant_id": tenant["tenant_id"],
                "llm_id": f"{chat_name}@{FACTORY}",
                "embd_id": f"{embd_name}@{FACTORY}",
                "img2txt_id": "",
                "asr_id": "",
                "tts_id": None,
                "rerank_id": "",
            },
        ),
        "set_tenant_info",
    )
    token = _check(client.post("/v1/system/new_token", headers=headers), "new_token")[
        "data"
    ]["token"]
    return token, f"{chat_name}@{FACTORY}", f"{embd_name}@{FACTORY}"


def _bootstrap_restful(client: httpx.Client, auth: str) -> tuple[str, str, str]:
    """v0.27.2: providers + instances, models/default, system/tokens."""
    headers = {"Authorization": auth}
    resp = client.put(
        "/api/v1/providers", headers=headers, json={"provider_name": FACTORY}
    )
    try:
        _check(resp, f"providers PUT ({FACTORY})")
    except RuntimeError as exc:
        # Tolerancja jak w conftest upstream: dostawca moze juz istniec.
        if (
            "duplicated" not in str(exc).lower()
            and "already exist" not in str(exc).lower()
        ):
            raise
    _check(
        client.post(
            f"/api/v1/providers/{FACTORY}/instances",
            headers=headers,
            json={
                "instance_name": INSTANCE_NAME,
                "api_key": FAKE_LLM_API_KEY,
                "base_url": FAKE_LLM_BASE_URL,
                "region": "default",
                "model_info": [
                    {
                        "model_type": ["chat"],
                        "model_name": FAKE_CHAT_MODEL,
                        "max_tokens": 8192,
                    },
                    {
                        "model_type": ["embedding"],
                        "model_name": FAKE_EMBEDDING_MODEL,
                        "max_tokens": 8192,
                    },
                ],
            },
        ),
        "providers instances POST",
    )
    models = _check(client.get("/api/v1/models", headers=headers), "models GET")["data"]

    def _model_id(model_name: str, wanted_type: str) -> str:
        for entry in models:
            types = entry.get("model_type", [])
            types = types if isinstance(types, list) else [types]
            provider = entry.get("provider_name") or entry.get("model_provider")
            if (
                entry.get("name") == model_name
                and wanted_type in types
                and provider == FACTORY
            ):
                return entry["model_id"]
        raise RuntimeError(
            f"models GET: brak modelu {model_name} ({wanted_type}) u dostawcy {FACTORY}: {models}"
        )

    for model_type, model_id in (
        ("chat", _model_id(FAKE_CHAT_MODEL, "chat")),
        ("embedding", _model_id(FAKE_EMBEDDING_MODEL, "embedding")),
    ):
        _check(
            client.patch(
                "/api/v1/models/default",
                headers=headers,
                json={"model_type": model_type, "model_id": model_id},
            ),
            f"models/default PATCH ({model_type})",
        )
    defaults = _check(
        client.get("/api/v1/models/default", headers=headers), "models/default GET"
    )["data"]["models"]

    def _composite(model_type: str) -> str:
        for entry in defaults:
            if entry.get("model_type") == model_type:
                return f"{entry['model_name']}@{entry['model_instance']}@{entry['model_provider']}"
        raise RuntimeError(
            f"models/default GET: brak modelu domyslnego typu {model_type}: {defaults}"
        )

    token = _check(
        client.post("/api/v1/system/tokens", headers=headers), "system/tokens POST"
    )["data"]["token"]
    return token, _composite("chat"), _composite("embedding")


def bootstrap(base_url: str) -> RagflowSession:
    """Zaklada konto, rejestruje fake-llm jako OpenAI-API-Compatible (czat + embedding),
    ustawia modele domyslne tenanta i tworzy klucz API. Na koncu zaklada drugie konto
    (recorder2) z wlasnym kluczem API — bez modeli (C3)."""
    with httpx.Client(timeout=60.0, base_url=base_url) as client:
        prefix = _api_prefix(client)
        auth = _register_and_login(client, prefix)
        if prefix == "api/v1":
            api_key, chat_model, embd_model = _bootstrap_restful(client, auth)
        else:
            api_key, chat_model, embd_model = _bootstrap_legacy(client, auth)
        auth_2 = _register_and_login(client, prefix, RECORD_EMAIL_2, RECORD_NICKNAME_2)
        return RagflowSession(
            base_url=base_url,
            api_key=api_key,
            auth=auth,
            chat_model=chat_model,
            embd_model=embd_model,
            api_key_2=_create_token(client, prefix, auth_2),
            auth_2=auth_2,
        )


def session_path(version: str, directory: Path = Path("/tmp")) -> Path:
    """Sciezka pliku sesji zapisywanej przez `--keep` i czytanej przez `--attach` (C4)."""
    return directory / f"wd-rec-session-{version}.json"


def save_session(
    session: RagflowSession, version: str, directory: Path = Path("/tmp")
) -> Path:
    """Zapisuje sesje (dataclasses.asdict, plik chmod 600) i zwraca jej sciezke (C4)."""
    path = session_path(version, directory)
    path.write_text(
        json.dumps(asdict(session), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def load_session(version: str, directory: Path = Path("/tmp")) -> RagflowSession:
    """Wczytuje sesje z pliku; brak pliku -> FileNotFoundError (obsluga w record.py)."""
    path = session_path(version, directory)
    return RagflowSession(**json.loads(path.read_text(encoding="utf-8")))
