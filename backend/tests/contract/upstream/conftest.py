"""Harness portu testów upstream RAGFlow v0.27.2 (CONTRACT §1/§2/§4/§5).

Plik własny Wawelsky Dragon — zastępuje upstreamowy ``test/testcases/conftest.py``, którego nie
kopiujemy (CONTRACT §1). Stuby brakujących zależności dev (CONTRACT §5) instaluje na samym
początku, przed jakimkolwiek importem z upstreamu; fixture'y ``auth``/``token`` biorą sesję
z resetu K9 (``WdServer.reset_session``), a nie z rejestracji RSA i ``system/new_token`` upstreamu.
"""

from __future__ import annotations

import fnmatch
import importlib
import importlib.util
import os
import socket
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest
from tests.contract.ragflow.harness import ReplaySession, WdServer, start_server

HERE = Path(__file__).resolve().parent
UPSTREAM_HTTP_DIR = HERE / "test_http_api"
UPSTREAM_SDK_DIR = HERE / "test_sdk_api"
UPSTREAM_PATH_DIRS = (HERE, UPSTREAM_HTTP_DIR, UPSTREAM_SDK_DIR)

# Powód pominięcia testów `@given`, gdy pakietu `hypothesis` naprawdę brak (stub z sekcji 1).
# Od E2-3a1 `hypothesis` jest przypiętą zależnością dev (`backend/pyproject.toml`), więc wiersz
# S-001 zniknął z SKIPPED.md — w zsynchronizowanym środowisku ta ścieżka nigdy nie działa.
HYPOTHESIS_SKIPPED = "brak pakietu `hypothesis` w środowisku (stub harnessu, CONTRACT §5)"


# ---------------------------------------------------------------------------------------------
# 1. Stuby zależności dev nieobecnych w środowisku testowym (CONTRACT §5).
#    Instalowane w `sys.modules` PRZED importem czegokolwiek z upstreamu; wyłączają się same,
#    gdy prawdziwy pakiet da się zaimportować (po dodaniu go przez Architekta).
# ---------------------------------------------------------------------------------------------


class _Unavailable:
    """Nieobecna zależność dev: każde użycie (atrybut albo wywołanie) rzuca ``ImportError``."""

    def __init__(self, qualname: str) -> None:
        self._qualname = qualname

    def __call__(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise ImportError(
            f"{self._qualname}: zależność dev nie jest zainstalowana (stub harnessu, CONTRACT §5)"
        )

    def __getattr__(self, _name: str) -> _Unavailable:
        return self


class _NoOp:
    """No-op elementu stubu ``hypothesis`` (``strategies.*``, ``HealthCheck``) — zwraca siebie.

    Argumenty dekoratorów (np. ``st.text(...)``) są wyliczane już przy imporcie modułu testu,
    więc nie mogą rzucać: test ``@given`` i tak zostanie pominięty (CONTRACT §5).
    """

    def __call__(self, *_args: Any, **_kwargs: Any) -> _NoOp:
        return self

    def __getattr__(self, _name: str) -> _NoOp:
        return self


def _unavailable_getattr(module_name: str) -> Callable[[str], _Unavailable]:
    """``__getattr__`` modułu-stuba: każdy atrybut rzuca ``ImportError`` dopiero przy użyciu."""

    def getattr_(_attribute: str) -> _Unavailable:
        return _Unavailable(f"{module_name}.{_attribute}")

    return getattr_


def _noop_getattr(_attribute: str) -> _NoOp:
    """``__getattr__`` stubu ``hypothesis``: każdy atrybut to no-op (CONTRACT §5)."""
    return _NoOp()


def _install_stub(name: str, attribute_factory: Callable[[str], Any]) -> types.ModuleType:
    """Wstawia do ``sys.modules`` moduł-stub ``name`` (bez realnych podmodułów do znalezienia).

    Brakujący atrybut modułu buduje ``attribute_factory``: ``_Unavailable`` (użycie rzuca
    ``ImportError``) albo ``_NoOp`` (użycie nic nie robi).
    """
    module = types.ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    module.__getattr__ = attribute_factory  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _importable(name: str) -> bool:
    """Czy prawdziwy pakiet ``name`` da się zaimportować (stub tylko wtedy, gdy nie)."""
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


def _skip_hypothesis_test(*_args: Any, **_kwargs: Any) -> NoReturn:
    """Ciało testu ``@given`` bez pakietu ``hypothesis``: pominięcie z powodem z SKIPPED.md."""
    pytest.skip(HYPOTHESIS_SKIPPED)


def _given(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Stub ``hypothesis.given``: podmienia udekorowany test na pominięcie (CONTRACT §5)."""

    def decorator(_func: Callable[..., Any]) -> Callable[..., Any]:
        return _skip_hypothesis_test

    return decorator


def _identity_decorator(*_args: Any, **_kwargs: Any) -> Callable[[Any], Any]:
    """Stub fabryki dekoratorów (``@example(…)``, ``@settings(…)``): zwraca funkcję bez zmian."""

    def decorator(func: Any) -> Any:
        return func

    return decorator


def _composite(func: Any = None) -> Any:
    """Stub ``hypothesis.strategies.composite``: obsługuje ``@composite`` i ``@composite()``.

    ``utils/hypothesis_utils.py`` woła ``@st.composite`` jako dekorator bez nawiasów — na module
    funkcja dekoruje się sama (``st.composite(func)``), a wynik jest wołany przy definicji testu
    (``@given(name=valid_names())``). Wynik musi więc być wołalny i zwracać no-op strategię
    (``_NoOp``), żeby zbieranie testów nie padało, zanim ``@given`` zamieni go na pominięcie.
    """
    if func is None:
        return _composite

    def strategy_factory(*_args: Any, **_kwargs: Any) -> _NoOp:
        return _NoOp()

    return strategy_factory


def _install_hypothesis_stub() -> None:
    """Stub ``hypothesis`` razem z ``hypothesis.strategies`` (CONTRACT §5)."""
    strategies = _install_stub("hypothesis.strategies", _noop_getattr)
    # `utils/hypothesis_utils.py` woła `@st.composite` już przy imporcie modułu.
    strategies.composite = _composite  # type: ignore[attr-defined]
    hypothesis = _install_stub("hypothesis", _noop_getattr)
    hypothesis.strategies = strategies  # type: ignore[attr-defined]
    hypothesis.given = _given  # type: ignore[attr-defined]
    hypothesis.example = _identity_decorator  # type: ignore[attr-defined]
    hypothesis.settings = _identity_decorator  # type: ignore[attr-defined]


def _install_dependency_stubs() -> None:
    """Stuby ``hypothesis``/``requests_toolbelt``/``reportlab``, gdy pakietu brak (CONTRACT §5)."""
    if not _importable("hypothesis"):
        _install_hypothesis_stub()
    if not _importable("requests_toolbelt"):
        _install_stub("requests_toolbelt", _unavailable_getattr("requests_toolbelt"))
    if not _importable("reportlab"):
        # `utils/file_utils.py` robi `from reportlab.pdfgen import canvas` przy imporcie modułu,
        # a samo tworzenie PDF-a (`canvas.Canvas(...)`) rzuca ImportError dopiero przy użyciu.
        reportlab = _install_stub("reportlab", _unavailable_getattr("reportlab"))
        reportlab.pdfgen = _install_stub(  # type: ignore[attr-defined]
            "reportlab.pdfgen", _unavailable_getattr("reportlab.pdfgen")
        )


# ---------------------------------------------------------------------------------------------
# 2. `sys.path` (pytest działa z `--import-mode=importlib`, więc sam nie doda tych katalogów)
#    oraz `HOST_ADDRESS` przed importem `configs` — port z niego bierze fixture `wd_server`.
# ---------------------------------------------------------------------------------------------

_install_dependency_stubs()

for _path_dir in UPSTREAM_PATH_DIRS:
    if str(_path_dir) not in sys.path:
        sys.path.append(str(_path_dir))


# ---------------------------------------------------------------------------------------------
# 2b. Kolizja nazw `common` (CONTRACT WP E2-3b1): `test_http_api/common.py` i
#     `test_sdk_api/common.py` to RÓŻNE moduły o tej samej nazwie, a oba ich conftesty robią
#     `from common import …`. Kopii nie zmieniamy, więc `sys.modules["common"]` to moduł
#     dyspozytorski: każde `common.<nazwa>` (i `from common import <nazwa>`) rozwiązuje wariant
#     wg katalogu modułu, który import wykonuje.
#
#     Dlaczego nie hook `pytest_collectstart` (CONTRACT): pytest wczytuje conftesty katalogów
#     podanych w argumencie oraz ich podkatalogów `test*` już na starcie, w
#     `pytest_load_initial_conftests` → `_loadconftestmodules` — zanim odpali się jakikolwiek
#     hook zbierania. Bez dyspozytora `test_sdk_api/conftest.py` pada na
#     `ImportError: cannot import name 'delete_all_chats' from 'common' (…/test_http_api/common.py)`
#     jeszcze przed pierwszym `pytest_collectstart`. Dyspozytor działa w każdej kolejności
#     wczytywania (bieg samych `test_http_api/`, samych `test_sdk_api/` i pełny bieg razem).
# ---------------------------------------------------------------------------------------------

_COMMON_NAME = "common"


def _load_common_module(directory: Path) -> types.ModuleType:
    """Wczytuje `<directory>/common.py` pod prywatną nazwą — raz na bieg (CONTRACT p. 2b).

    Prywatna nazwa (nie `common`) trzyma wariant poza kolizją; `sys.modules` dostaje wpis przed
    `exec_module`, bo moduł może sięgać do siebie samego (importy cykliczne, adnotacje).
    """
    module_name = f"_wd_{directory.name}_common"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, directory / "common.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _common_importer_directory() -> Path | None:
    """Katalog kopii (`test_sdk_api`/`test_http_api`), z której pochodzi bieżące `common.<nazwa>`.

    Wchodzimy po stosie od własnych ramek: moduły importlib nie mają `__file__` w globalnych,
    a `_common_attr` ma w globalnych `__file__` tego conftestu (poza oboma katalogami), więc
    pierwsza pasująca ramka to moduł kopii wykonujący import.
    """
    frame: types.FrameType | None = sys._getframe(1)
    while frame is not None:
        module_file = frame.f_globals.get("__file__")
        if module_file is not None:
            path = Path(module_file)
            for directory in (UPSTREAM_SDK_DIR, UPSTREAM_HTTP_DIR):
                if path.is_relative_to(directory):
                    return directory
        frame = frame.f_back
    return None


def _common_attr(name: str) -> Any:
    """Atrybut `common` z modułu kopii, która go importuje (domyślnie `test_http_api`)."""
    directory = _common_importer_directory() or UPSTREAM_HTTP_DIR
    return getattr(_load_common_module(directory), name)


def _install_common_dispatcher() -> None:
    """Wstawia dyspozytora `common` do `sys.modules` — przed pierwszym `from common import …`."""
    module = types.ModuleType(_COMMON_NAME)
    module.__file__ = str(UPSTREAM_HTTP_DIR / "common.py")
    module.__getattr__ = _common_attr  # type: ignore[attr-defined]
    sys.modules[_COMMON_NAME] = module


_install_common_dispatcher()


def _free_port() -> int:
    """Wolny port TCP na 127.0.0.1 (bind na 0, odczyt, zamknięcie) — jak `harness._free_port`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


PORT = _free_port()
os.environ["HOST_ADDRESS"] = f"http://127.0.0.1:{PORT}"
# Upstreamowe `configs.py` kończy sesję (`pytest.exit`), gdy brak kluczy providerów
# ZHIPU/SILICONFLOW; harness WD nie rejestruje providerów (modele zasiewa reset K9,
# CONTRACT §1), więc dostarcza wartości zastępcze — `setdefault` nie nadpisuje kluczy
# z środowiska (DEC-064).
os.environ.setdefault("ZHIPU_AI_API_KEY", "wd-harness-unused")
os.environ.setdefault("SILICONFLOW_API_KEY", "wd-harness-unused")

# `sys.path` gotowy (p. 2) i `common` podstawiony (p. 2b); upstreamowe `common` importuje
# `configs` (czyta `HOST_ADDRESS`) — dyspozytor rozwiąże tu wariant HTTP.
from common import delete_all_datasets  # noqa: E402

# ---------------------------------------------------------------------------------------------
# 3. Fixture'y harnessu (CONTRACT §2) — nazwy jak upstream.
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def wd_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WdServer]:
    """Stos WD (api+worker) na świeżej bazie, na porcie z `HOST_ADDRESS` — jeden na sesję."""
    with start_server(tmp_path_factory.mktemp("upstream"), port=PORT) as server:
        yield server


@pytest.fixture(scope="session")
def wd_session(wd_server: WdServer) -> ReplaySession:
    """Reset K9 + sesja (klucz API i JWT admina) — raz na sesję, żeby klucz przeżył cały bieg."""
    return wd_server.reset_session()


@pytest.fixture(scope="session")
def auth(wd_session: ReplaySession) -> str:
    """Nagłówek Authorization admina (jak `auth` w upstreamowym `test/testcases/conftest.py`)."""
    return wd_session.auth


@pytest.fixture(scope="session")
def token(wd_session: ReplaySession) -> str:
    """Klucz API admina (jak `token` upstreamu; `test_http_api/conftest.py` buduje z niego auth)."""
    return wd_session.api_key


def _needs_server(request: pytest.FixtureRequest) -> bool:
    """Czy testy spod tego fixture'a biją do stosu WD (``test_http_api/``/``test_sdk_api/``).

    Od E2-3b1 także kopie SDK (`test_sdk_api/`, klient `ragflow_sdk` na tym samym stosie).
    """
    path = str(request.path).replace(os.sep, "/")
    return "/test_http_api/" in path or "/test_sdk_api/" in path


@pytest.fixture(autouse=True)
def _wd_up(request: pytest.FixtureRequest) -> None:
    """Startuje stos WD także dla testów ``test_http_api/`` bez fixture'u ``HttpApiAuth``.

    Upstream miał serwer pod ``HOST_ADDRESS`` od startu, więc np. klasy ``TestAuthorization``
    biją do niego bez żadnego fixture'u; u nas stos startuje leniwie z ``wd_server`` (session),
    więc bez tego testy autoryzacji padały na „connection refused". ``test_skipped_index.py``
    (korzeń ``upstream/``, bez serwera) nie jest tym dotknięty.
    """
    if _needs_server(request):
        request.getfixturevalue("wd_server")


def _dataset_cleanup(request: pytest.FixtureRequest) -> Callable[[], None] | None:
    """Kasowanie datasetów po module — wariant zależny od katalogu kopii (CONTRACT §2).

    Katalogi mają różne klienty: ``test_http_api/`` używa ``HttpApiAuth`` + ``common`` HTTP,
    ``test_sdk_api/`` — fixture'u ``client`` (``ragflow_sdk``) i ``common`` SDK. ``HttpApiAuth``
    żyje w kopiowanym ``test_http_api/conftest.py``, więc bieg samych ``test_sdk_api/`` go nie
    ma; moduły spoza obu katalogów (``test_skipped_index.py``, CONTRACT §4) nie startują stosu.
    Fixture'y bierzemy PRZED ``yield``, żeby nie sięgać do nich po zakończeniu testu modułu.
    """
    path = str(request.path).replace(os.sep, "/")
    if "/test_sdk_api/" in path:
        client = request.getfixturevalue("client")
        sdk_delete_all = _load_common_module(UPSTREAM_SDK_DIR).delete_all_datasets

        def cleanup_sdk() -> None:
            sdk_delete_all(client)

        return cleanup_sdk
    if "/test_http_api/" in path:
        http_api_auth = request.getfixturevalue("HttpApiAuth")

        def cleanup_http() -> None:
            delete_all_datasets(http_api_auth)

        return cleanup_http
    return None


@pytest.fixture(autouse=True, scope="module")
def _wd_clean_datasets(request: pytest.FixtureRequest) -> Iterator[None]:
    """Kasuje datasety po module — siatka bezpieczeństwa bez resetu bazy (CONTRACT §2).

    Scope `module`, nie `function` (DEC-064 „Uwaga do TL”, zmiana T2): funkcyjny kasował
    datasety fixture'ów class-scope (`add_datasets`, `add_dataset`) już po pierwszym teście
    klasy, więc kolejne testy widziały pustą bazę (odpowiedź 102 zamiast 0). Upstreamowe
    fixture'y class-scope same sprzątają w finalizerach; ten fixture jest tylko siatką
    bezpieczeństwa na koniec modułu.
    """
    cleanup = _dataset_cleanup(request)
    yield
    if cleanup is not None:
        cleanup()


# ---------------------------------------------------------------------------------------------
# 4. Markery upstreamu, marker `contract` i lista pominięć (CONTRACT §3/§4).
# ---------------------------------------------------------------------------------------------

# Opisy dosłownie jak w `pyproject.toml` upstreamu v0.27.2 (DEC-064); nasz `pyproject.toml`
# należy w tej fali do E4-2a, więc rejestrujemy je runtime'owo (inaczej `--strict-markers` pada).
UPSTREAM_MARKERS = {
    "p0": "critical priority test cases",
    "p1": "high priority test cases",
    "p2": "medium priority test cases",
    "p3": "low priority test cases",
}

# Pominięcia (CONTRACT §4): klucz = wzorzec nodeid względem `upstream/` (fnmatch, `*` dozwolone),
# wartość = `SKIPPED.md#<id>`. `SKIPPED_XFAIL` = wzorce pomijane jako `xfail(strict=True)`.
# Uwaga fnmatch: `[` w nodeidzie (parametryzacje) trzeba obejść jako `[[]`…`[]]`.
_TDM = "test_http_api/test_dataset_management/"
_TCRT = _TDM + "test_create_dataset.py::TestDatasetCreate::"
_TUPD = _TDM + "test_update_dataset.py::TestDatasetUpdate::"
_TSEARCH = _TDM + "test_search.py::TestDatasetSearch::"
# Wzorce parametrowane: `[` w nodeidzie to dla fnmatch klasa znaków, stąd `[[]…[]]`.
_S205 = (
    _TUPD + "test_embedding_model[[]*[]]",
    _TUPD + "test_embedding_model_none",
    _TUPD + "test_embedding_model_invalid[[]*[]]",
)
_S209 = (
    _TUPD + "test_parser_config_empty",
    _TUPD + "test_parser_config_none",
    _TUPD + "test_parser_config_empty_with_chunk_method_change",
    _TUPD + "test_parser_config_unset_with_chunk_method_change",
    _TUPD + "test_parser_config_none_with_chunk_method_change",
)
# Moduły spoza rejestru WD (builtin BAAI, tenant ZHIPU) — środowisko testowe (S-102).
_S102 = (
    _TCRT + "test_embedding_model[[]builtin_baai[]]",
    _TCRT + "test_embedding_model[[]tenant_zhipu[]]",
)

# E2-3a1/T2 (`test_file_management_within_dataset/`) — odchyłki WD i trasa bez odpowiednika.
_TFM = "test_http_api/test_file_management_within_dataset/"
_TDD = _TFM + "test_delete_documents.py::"
_TDL = _TFM + "test_download_document.py::"
_TLD = _TFM + "test_list_documents.py::"
# Parametr ``["", 100, "<MethodNotAllowed '405: Method Not Allowed'>"]`` — pusty dataset_id.
_405 = "test_invalid_dataset_id[[]-100-<MethodNotAllowed*"
# E2-3a2/T1 (`test_chat_assistant_management/`) — odchyłki i jedno `środowisko` (DEC-090 p. B-G).
_CHAT = "test_http_api/test_chat_assistant_management/"
_CHAT_CREATE = _CHAT + "test_create_chat_assistant.py::TestChatAssistantCreate::"
_CHAT_UPDATE = _CHAT + "test_update_chat_assistant.py::TestChatAssistantUpdate::"
_CHAT_LIST = _CHAT + "test_list_chat_assistants.py::TestChatAssistantsList::"
_CHAT_DELETE = _CHAT + "test_delete_chat_assistants.py::TestChatAssistantsDelete::"

# E2-3a1/T4: kopia unit-testów tras upstreamu — ładuje ``spec_from_file_location`` **źródła
# upstreamu** (``api/apps/restful_apis/{chunk,document}_api.py``) i plików z ``test_web_api/``,
# których WD nie ma, a na dodatek importuje ``numpy``/``api.db`` na poziomie modułu — nie da się
# jej nawet zebrać. Moduł dostaje kolektor ``_SkippedUpstreamModule`` (T5: jedna syntetyczna
# pozycja zamiast pominięcia kolektora), więc wzorzec opisuje sam plik (bez ``*``).
# E2-3a2/T3 dołącza ``test_session_sdk_routes_unit.py`` (S-377): moduł zbiera się, ale każdy test
# ładuje ``spec_from_file_location`` pliki ``api/apps/restful_apis/*_api.py`` upstreamu, licząc
# ``parents[4]`` z ``backend/tests`` — tych plików w WD nie ma, więc fixture pada w każdym teście;
# jedna syntetyczna pozycja daje ten sam efekt przy ``-m contract`` (CONTRACT WP E2-3a2).
_SESSIONS_B_SDK = "test_http_api/test_session_management/test_session_sdk_routes_unit.py"
_UNIMPORTABLE_MODULES = frozenset(
    {
        _TFM + "test_doc_sdk_routes_unit.py",
        # E2-3a2/T1: to samo dla czatów (``api/apps/restful_apis/chat_api.py`` +
        # ``common/constants`` z ``parents[4]``) — DEC-090 p. A, wzór S-341.
        _CHAT + "test_chat_sdk_routes_unit.py",
        # E2-3a2/T3: unit-testy tras sesji/agentów (S-377).
        _SESSIONS_B_SDK,
    }
)

# E2-3a2/T2 (`test_http_api/test_session_management/`).
_TSM = "test_http_api/test_session_management/"
# Kopie upstream wołają ``/api/v1/searchbots/related_questions`` (`common.py:338`) — przestrzeni
# `/searchbots/*` WD nie ma i nie będzie mieć w E2 (02-api §5.6 „Nigdy — stuby": v2, tokeny beta).
# Ta funkcja żyje pod ``POST /api/v1/sessions/related_questions`` — DEC-091 p. 2.
_S365 = _TSM + "test_related_questions.py::*"
# Pusty segment ścieżki: Quart skleja ``//`` i oddaje 405 z ``code 100``; router Starlette nie ma
# trasy dla pustego segmentu (404, a dla ``PATCH …/sessions/`` 405 z kopertą K3) — DEC-091 p. 3.
_TSM_CREATE = (
    _TSM + "test_create_session_with_chat_assistant.py::TestSessionWithChatAssistantCreate::"
)
_TSM_UPDATE = (
    _TSM + "test_update_session_with_chat_assistant.py::TestSessionWithChatAssistantUpdate::"
)
_SESSIONS_A_405 = {
    _TSM_CREATE + "test_invalid_chat_assistant_id[[]-100-<MethodNotAllowed*": "SKIPPED.md#S-366",
    _TSM_UPDATE + "test_invalid_session_id[[]-100-<MethodNotAllowed*": "SKIPPED.md#S-367",
}

# E2-3a2/T4 (`test_http_api/test_chat_management/`): odpowiedź asystenta ma być wynikiem rozumienia
# tabeli (SQL/naturalny opis) przez prawdziwy LLM; na stosie WD odpowiada recorder (fake-llm +
# fake-embed), więc asercje treści odpowiedzi nie mają szans się ziścić (S-390, `środowisko`).
_TCHM = "test_http_api/test_chat_management/"
_S390 = (
    _TCHM
    + "test_table_parser_dataset_chat.py::TestTableParserDatasetChat::"
    + "test_table_parser_dataset_chat[[]*[]]"
)
_ENVIRONMENT = {_S390: "SKIPPED.md#S-390"}
# E2-3a2/T3 (część B katalogu sesji): ``/agents*`` i ``/agents_openai/*`` są w 02-api §5.6
# „Nigdy — stuby" (v2, tokeny beta), a kopia unit-testów tras ładuje źródło upstreamu —
# jak S-341 (DEC-092 p. 3-4).
_SESSIONS_B = {
    _TSM + "test_agent_completions.py::*": "SKIPPED.md#S-375",
    _TSM + "test_agent_sessions.py::*": "SKIPPED.md#S-376",
    # Wzorzec to sam plik (bez ``*``) — hook ``pytest_pycollect_makemodule`` szuka go
    # w ``_UNIMPORTABLE_MODULES``; patrz komentarz przy tej stałej.
    _SESSIONS_B_SDK: "SKIPPED.md#S-377",
}

# Pliki/katalogi funkcji spoza WD (całość pominięta, CONTRACT §4 `poza-zakresem`).
_OUT_OF_SCOPE = {
    _S365: "SKIPPED.md#S-365",
    # E2-3a2/T4: kopia ładuje przez `spec_from_file_location` źródło upstreamu
    # (`api/apps/services/file_api_service.py`, ścieżka `parents[4]`), którego WD nie ma — trasy
    # `/api/v1/files*` (menedżer plików, E4-5) poza zakresem E2 (S-391).
    "test_http_api/test_file_app/test_file_routes.py::*": "SKIPPED.md#S-391",
    **_SESSIONS_B,
    _TDM + "test_dify_retrieval_routes_unit.py*": "SKIPPED.md#S-200",
    _TDM + "test_index_api.py*": "SKIPPED.md#S-201",
    _TDM + "test_knowledge_graph.py*": "SKIPPED.md#S-202",
    _TDM + "test_tags.py*": "SKIPPED.md#S-203",
    _TDM + "test_search.py::TestDatasetGraph*": "SKIPPED.md#S-204",
    # E2-3a1/T4: kopia unit-testów tras upstreamu (patrz `_UNIMPORTABLE_MODULES`).
    _TFM + "test_doc_sdk_routes_unit.py": "SKIPPED.md#S-341",
    # E2-3a2/T1: kopia unit-testów tras czatów (patrz `_UNIMPORTABLE_MODULES`), DEC-090 p. A.
    _CHAT + "test_chat_sdk_routes_unit.py": "SKIPPED.md#S-350",
}
# E2-3b1/T4: katalogi SDK spoza zakresu E2 (`test_agent_management/`, `test_memory_management/`,
# `test_message_management/`) nie mają kopii w `test_sdk_api/` — trasy `/agents*`, `/memories*`
# i `/messages*` są w 02-api §5.6 „Nigdy — stuby" (nie ma ich też w `backend/openapi.json`),
# implementacja to v2/graphrag. Miejsce w raporcie trzyma plik własny
# `test_sdk_api/test_out_of_scope.py` (jedna pozycja na katalog, wzór S-341/S-350).
_SDK_OUT_OF_SCOPE = {
    "test_sdk_api/test_out_of_scope.py::test_agent_management": "SKIPPED.md#S-440",
    "test_sdk_api/test_out_of_scope.py::test_memory_management": "SKIPPED.md#S-441",
    "test_sdk_api/test_out_of_scope.py::test_message_management": "SKIPPED.md#S-442",
}

# Odchyłki WD: złoto v0.27.2 ma pierwszeństwo przed testem upstream (CONTRACT §6).
_DEVIATIONS = {
    _TSEARCH + "test_search_without_question": "SKIPPED.md#S-207",
    _TUPD + "test_chunk_method[[]tag[]]": "SKIPPED.md#S-208",
    _TDM + "test_ingestion_logs.py::TestListIngestionLogsEdgeCases*": "SKIPPED.md#S-210",
    # E2-3a1: reguła z v0.24.0 (brief E1-9a rozstrz. 3) — WD blokuje zmianę `embedding_model`,
    # gdy `chunk_count > 0`; test (ujawniony po dodaniu `requests-toolbelt`) oczekuje `code == 0`.
    _TUPD + "test_embedding_model_with_existing_chunks": "SKIPPED.md#S-300",
    # T2 (`test_create_dataset.py`): domyślne parser_config/embedding_model WD z resetu K9,
    # komunikat rejestru modeli i metoda `tag` — jak T3, ale dla POST /datasets.
    _TCRT + "test_parser_config_unset": "SKIPPED.md#S-100",
    _TCRT + "test_parser_config_none": "SKIPPED.md#S-100",
    _TCRT + "test_parser_config_empty": "SKIPPED.md#S-100",
    _TCRT + "test_embedding_model_unset": "SKIPPED.md#S-101",
    _TCRT + "test_embedding_model_none": "SKIPPED.md#S-101",
    _TCRT + "test_embedding_model_invalid[[]*[]]": "SKIPPED.md#S-103",
    _TCRT + "test_chunk_method[[]tag[]]": "SKIPPED.md#S-104",
    # E2-3a1/T2: koperta uwierzytelnienia v0.27.2 to 401 + "<Unauthorized '401: Unauthorized'>"
    # (złoto ``datasets/errors_access--36/37``), a test trasy pobierania niesie kopertę v0.24.0
    # (brak nagłówka → ``code 0``, zły klucz → 109) — S-315.
    _TDL + "TestAuthorization::test_invalid_auth[[]*[]]": "SKIPPED.md#S-315",
    # E2-3a1/T2: trasa pobierania odpowiada „document not found" (102) zarówno dla dokumentu
    # nieistniejącego, jak i dla cudzego datasetu — tak mówi złoto
    # ``datasets___documents___/errors_access--15`` i kod v0.27.2 (DOC:2172-2184);
    # test oczekuje komunikatów v0.24.0 — S-316/S-317.
    _TDL + "TestDocumentDownload::test_invalid_document_id[[]*[]]": "SKIPPED.md#S-316",
    _TDL + "TestDocumentDownload::test_invalid_dataset_id[[]*[]]": "SKIPPED.md#S-317",
    # E2-3a1/T2: pusty dataset_id w ścieżce — Quart (Werkzeug) zwraca tu 405 z ``code 100``,
    # router Starlette nie ma trasy dla pustego segmentu (404 z kopertą K3) — DEC-087 p. 3.
    _TDD + "TestDocumentsDeletion::" + _405: "SKIPPED.md#S-318",
    _TLD + "TestDocumentsList::" + _405: "SKIPPED.md#S-319",
}
# Ślepe zaułki środowiska/modeli: katalog modeli upstream (S-205) i modele spoza rejestru (S-102).
_DEAD_ENDS = dict.fromkeys(_S205, "SKIPPED.md#S-205") | dict.fromkeys(_S102, "SKIPPED.md#S-102")
# Domyślny `parser_config` WD z złota E1-9a (S-209).
_PARSER_DEFAULTS = dict.fromkeys(_S209, "SKIPPED.md#S-209")

# T3 E2-3a1 (katalog chunków): oczekiwania testów sprzeczne ze złotem v0.27.2 — kod 100/`repr(e)`
# tam, gdzie złoto daje 102 lub WD świadomie nie ujawnia wyjątku (K3 „Nigdy repr(e)"), oraz
# koperta uwierzytelnienia z v0.24; powody i odsyłacze w SKIPPED.md.
_CHK = "test_http_api/test_chunk_management_within_dataset/"
_CHK_ADD = _CHK + "test_add_chunk.py::TestAddChunk::"
_CHK_AUTH = _CHK + "test_retrieval_chunks.py::TestAuthorization::"
_CHK_RET = _CHK + "test_retrieval_chunks.py::TestChunksRetrieval::"
_CHK_UPD = _CHK + "test_update_chunk.py::TestUpdatedChunk::"
_CHUNK_DEVIATIONS = {
    _CHK_ADD + "test_important_keywords[[]payload2*[]]": "SKIPPED.md#S-325",
    _CHK_ADD + "test_questions[[]payload2*[]]": "SKIPPED.md#S-326",
    _CHK_AUTH + "test_invalid_auth[[]*[]]": "SKIPPED.md#S-327",
    _CHK_RET + "test_vector_similarity_weight[[]payload2*[]]": "SKIPPED.md#S-328",
    _CHK_RET + "test_top_k[[]payload3*[]]": "SKIPPED.md#S-329",
    _CHK_UPD + "test_important_keywords[[]payload2*[]]": "SKIPPED.md#S-330",
    _CHK_UPD + "test_questions[[]payload2*[]]": "SKIPPED.md#S-331",
}

# E2-3a1/T4 (część B katalogu dokumentów): oczekiwania sprzeczne z zamrożonymi kontraktami WD
# (K5 §6.5 p. 5 — literał końca postępu, S-335) albo z frameworkiem (pusty segment ścieżki,
# jak S-318/S-319). Powody i odsyłacze w SKIPPED.md.
_TPA = _TFM + "test_parse_documents.py::"
_TUPD_FILES = _TFM + "test_update_document.py::"
_T4_DEVIATIONS: dict[str, str] = {
    # ``test_basic_scenarios[<lambda>-0-*]`` to jedyne dwa przypadki sukcesu „na żywo".
    _TPA + "TestDocumentsParse::test_basic_scenarios[[]<lambda>-0-*[]]": "SKIPPED.md#S-335",
    _TPA + "TestDocumentsParse::test_parse_partial_invalid_document_id[[]*[]]": "SKIPPED.md#S-335",
    _TPA + "TestDocumentsParse::test_duplicate_parse": "SKIPPED.md#S-335",
    _TPA + "test_parse_100_files": "SKIPPED.md#S-335",
    _TPA + "test_concurrent_parse": "SKIPPED.md#S-335",
    # Pusty ``dataset_id``: ``POST /api/v1/datasets//documents/parse`` — Starlette nie ma trasy
    # dla pustego segmentu (404 z kopertą K3), Quart skleja ``//`` — różnica frameworku.
    _TPA + "TestDocumentsParse::test_invalid_dataset_id[[]-102-*[]]": "SKIPPED.md#S-336",
    # ``name: null`` — test sprzeczny z kodem v0.27.2 (DOC:240-242 daje 102), a oczekiwany
    # literał to spreparowany ``repr`` wyjątku, którego K3 nie ujawnia.
    _TUPD_FILES + "TestDocumentsUpdated::test_name[[]None-100-*[]]": "SKIPPED.md#S-337",
    # ``chunk_method`` tag/knowledge_graph: WD świadomie ich nie obsługuje (S-104/S-208).
    _TUPD_FILES + "TestDocumentsUpdated::test_chunk_method[[]tag-0-[]]": "SKIPPED.md#S-338",
    _TUPD_FILES + "TestDocumentsUpdated::test_chunk_method[[]knowledge_graph-0-[]]": (
        "SKIPPED.md#S-338"
    ),
    # ``parser_config == {}`` → domyślny ``parser_config`` datasetu: różni się od upstreamowej
    # stałej ``DEFAULT_PARSER_CONFIG`` wyłącznie ``llm_id`` z resetu K9 (jak S-100/S-209).
    _TUPD_FILES
    + "TestUpdateDocumentParserConfig::test_parser_config[[]naive-parser_config0-0-[]]": (
        "SKIPPED.md#S-339"
    ),
}

# E2-3a2/T1 (katalog czatów): złoto v0.27.2 (S-351, S-353) albo kod v0.27.2 (S-354) przeczy
# testowi upstream — powody i odsyłacze w SKIPPED.md; S-352 to brak modelu w rejestrze
# (kategoria `środowisko`, więc zwykły `skip` — jak S-102, nie xfail strict).
_CHAT_SKIPS: dict[str, str] = {
    # Testy zakładają model providera (`glm-4`) w rejestrze modeli (jak S-102).
    _CHAT_CREATE + "test_llm[[]llm1-0-[]]": "SKIPPED.md#S-352",
    _CHAT_UPDATE + "test_llm[[]llm1-0-[]]": "SKIPPED.md#S-352",
}
_CHAT_DEVIATIONS: dict[str, str] = {
    # Wartość domyślna `llm_id` to `models.id` (E1-9b R1; złoto `chats/chat_session--01.json`),
    # a nie literał modelu z upstreamowego `set_tenant_info`.
    _CHAT_CREATE + "test_llm[[]llm0-0-[]]": "SKIPPED.md#S-351",
    # `_apply_prompt_defaults` v0.27.2 (chat_api.py:413-414) dokłada `{"key":"date",…}` — złoto też.
    _CHAT_CREATE + "test_prompt[[]prompt0-0-[]]": "SKIPPED.md#S-353",
    _CHAT_CREATE + "test_prompt[[]prompt11-0-[]]": "SKIPPED.md#S-353",
    _CHAT_CREATE + "test_prompt[[]prompt38-0-[]]": "SKIPPED.md#S-353",
    # Kopia `test_http_api` nie została zaktualizowana commitem `4b619f699` (nowe domyślne
    # `page`/`page_size` = 1/30) — test przeczy kodowi v0.27.2, który WD odtwarza.
    _CHAT_LIST + "test_page[[]params0-0-5-[]]": "SKIPPED.md#S-354",
    _CHAT_LIST + "test_page[[]params1-0-5-[]]": "SKIPPED.md#S-354",
    _CHAT_LIST + "test_page_size[[]params2-0-5-[]]": "SKIPPED.md#S-354",
    _CHAT_LIST + "test_page_size[[]params4-0-5-[]]": "SKIPPED.md#S-354",
    # Nieistniejący czat: 102 „Chat not found!" to świadoma odchyłka WD (E1-9b C10).
    _CHAT_LIST + "test_get_chat_assistant[[]unknown-109-no authorization[]]": "SKIPPED.md#S-355",
    # Ciało nie-dict (C9 → `{}`) i komunikat `repr(e)` zakazany przez K3.
    _CHAT_DELETE + "test_basic_scenarios[[]not json-*[]]": "SKIPPED.md#S-356",
}

# E2-3b1/T3: kopie 1:1 z v0.27.2 `test_sdk_api/test_dataset_mangement/test_create_dataset.py`
# i `test_update_dataset.py`. Powody te same, co wiersze HTTP katalogu `test_dataset_management`
# (S-100…S-104, S-205, S-208, S-209), ale własne wiersze SKIPPED.md (S-420…S-439, CONTRACT WP
# E2-3b1): SDK waliduje argumenty `beartype` i składa komunikat błędu z ``message`` odpowiedzi,
# więc część przypadków zachowuje się inaczej niż w HTTP. Rozstrzygnięcia: DEC-105.
_SDK_CU = "test_sdk_api/test_dataset_mangement/test_create_dataset.py::"
_SDK_CU_UPD = "test_sdk_api/test_dataset_mangement/test_update_dataset.py::"
_SDK_CU_CREATE = _SDK_CU + "TestDatasetCreate::"
_SDK_CU_UPDATE = _SDK_CU_UPD + "TestDatasetUpdate::"
_SDK_DATASETS_CU: dict[str, str] = {
    # POST /datasets: `chunk_method` `resume` odrzucany świadomie (jak `tag` w S-104/S-208).
    _SDK_CU_CREATE + "test_chunk_method[[]resume[]]": "SKIPPED.md#S-420",
    # POST /datasets: modele spoza rejestru WD (jak S-102) i domyślne z resetu K9 (jak S-101/S-100).
    _SDK_CU_CREATE + "test_embedding_model[[]builtin_baai[]]": "SKIPPED.md#S-421",
    _SDK_CU_CREATE + "test_embedding_model[[]tenant_zhipu[]]": "SKIPPED.md#S-421",
    _SDK_CU_CREATE + "test_embedding_model_unset": "SKIPPED.md#S-422",
    _SDK_CU_CREATE + "test_embedding_model_none": "SKIPPED.md#S-422",
    _SDK_CU_CREATE + "test_parser_config_unset": "SKIPPED.md#S-423",
    _SDK_CU_CREATE + "test_parser_config_none": "SKIPPED.md#S-423",
    _SDK_CU_CREATE + "test_parser_config_empty": "SKIPPED.md#S-423",
    _SDK_CU_CREATE + "test_chunk_method[[]tag[]]": "SKIPPED.md#S-424",
    # POST /datasets: `graphrag`/`raptor` zostają w odpowiedzi (DEC-105, jak zielona kopia HTTP).
    _SDK_CU_CREATE + "test_parser_config[[]graphrag_*[]]": "SKIPPED.md#S-425",
    _SDK_CU_CREATE + "test_parser_config[[]raptor_*[]]": "SKIPPED.md#S-425",
    _SDK_CU + "TestParserConfigBugFix::*": "SKIPPED.md#S-425",
    # PUT /datasets/{id}: katalog modeli upstreamu (jak S-205) i parser_config (jak S-208/S-209).
    _SDK_CU_UPDATE + "test_embedding_model[[]*[]]": "SKIPPED.md#S-426",
    _SDK_CU_UPDATE + "test_embedding_model_none": "SKIPPED.md#S-426",
    _SDK_CU_UPDATE + "test_embedding_model_invalid[[]*[]]": "SKIPPED.md#S-426",
    _SDK_CU_UPDATE + "test_chunk_method[[]tag[]]": "SKIPPED.md#S-427",
    _SDK_CU_UPDATE + "test_parser_config_empty": "SKIPPED.md#S-428",
    _SDK_CU_UPDATE + "test_parser_config_none": "SKIPPED.md#S-428",
    _SDK_CU_UPDATE + "test_parser_config_empty_with_chunk_method_change": "SKIPPED.md#S-428",
    _SDK_CU_UPDATE + "test_parser_config_unset_with_chunk_method_change": "SKIPPED.md#S-428",
    _SDK_CU_UPDATE + "test_parser_config_none_with_chunk_method_change": "SKIPPED.md#S-428",
    # PUT /datasets/{id}: `graphrag`/`raptor` jak w POST (DEC-105).
    _SDK_CU_UPDATE + "test_parser_config[[]graphrag_*[]]": "SKIPPED.md#S-429",
    _SDK_CU_UPDATE + "test_parser_config[[]raptor_*[]]": "SKIPPED.md#S-429",
}
# Wiersze SDK kategorii `środowisko` (S-421) i `poza-zakresem` (S-426) — zwykły skip; reszta to
# `odchyłka-WD`, czyli `xfail(strict=True)` (CONTRACT §4).
_SDK_DATASETS_CU_SKIP = frozenset({"SKIPPED.md#S-421", "SKIPPED.md#S-426"})
_SDK_DATASETS_CU_XFAIL = frozenset(
    pattern for pattern, reason in _SDK_DATASETS_CU.items() if reason not in _SDK_DATASETS_CU_SKIP
)

# E2-3b2/T3: kopie 1:1 z v0.27.2 `test_sdk_api/test_chunk_management_within_dataset/`. Dwie z pięciu
# odchyłek są nowe, bo kopia SDK przeczy zielonej kopii HTTP tego samego wydania: S-460 (kopia SDK
# żąda nadpisania wiersza po haszu treści, a kopia HTTP czyta licznik `chunk_count`, który rośnie)
# i S-461 (`keywords` trafia u upstreamu w tytuł dokumentu, WD filtruje listę po treści); pozostałe
# trzy mają odpowiednik HTTP (S-328/S-330/S-331). Powody w SKIPPED.md, rozstrzygnięcia w DEC-113.
# Wzorce muszą nieść **nazwę pliku**: `test_important_keywords[payload2]` i
# `test_questions[payload2]` są też w `test_add_chunk.py`, gdzie przechodzą — wzorzec bez pliku
# dałby XPASS strict (failed).
_SDK_CHUNKS_DIR = "test_sdk_api/test_chunk_management_within_dataset/"
_SDK_CHK_ADD = _SDK_CHUNKS_DIR + "test_add_chunk.py::TestAddChunk::"
_SDK_CHK_LIST = _SDK_CHUNKS_DIR + "test_list_chunks.py::TestChunksList::"
_SDK_CHK_RET = _SDK_CHUNKS_DIR + "test_retrieval_chunks.py::TestChunksRetrieval::"
_SDK_CHK_UPD = _SDK_CHUNKS_DIR + "test_update_chunk.py::TestUpdatedChunk::"
_SDK_CHUNKS: dict[str, str] = {
    # SDK czyta `len(list_chunks())` (nadpisanie wiersza), HTTP `doc.chunk_count` (+2).
    _SDK_CHK_ADD + "test_repeated_add_chunk": "SKIPPED.md#S-460",
    # `keywords="ragflow"`: brak chunku bazowego, a WD filtruje listę tylko po treści.
    _SDK_CHK_LIST + "test_keywords[[]params4*[]]": "SKIPPED.md#S-461",
    # Te same przyczyny, co wiersze HTTP katalogu chunków.
    _SDK_CHK_RET + "test_vector_similarity_weight[[]payload2*[]]": "SKIPPED.md#S-462",
    _SDK_CHK_UPD + "test_important_keywords[[]payload2*[]]": "SKIPPED.md#S-463",
    _SDK_CHK_UPD + "test_questions[[]payload2*[]]": "SKIPPED.md#S-464",
}
# Puste — wszystkie pięć pozycji katalogu to `odchyłka-WD` (`xfail(strict=True)`, CONTRACT §4).
# Stała zostaje dla jednolitego wzoru zadań T1/T2/T4/T5 (`_SDK_*_SKIP`/`_SDK_*_XFAIL`).
_SDK_CHUNKS_SKIP: frozenset[str] = frozenset()
_SDK_CHUNKS_XFAIL: frozenset[str] = frozenset(
    pattern for pattern, reason in _SDK_CHUNKS.items() if reason not in _SDK_CHUNKS_SKIP
)

# E2-3b2/T2: kopie 1:1 z v0.27.2 `test_sdk_api/test_file_management_within_dataset/`
# (`test_parse_documents.py`, `test_update_document.py`, `test_upload_documents.py`). Trzy
# czwarte to te same przyczyny, co wiersze HTTP tego katalogu (S-455→S-335: literał końca
# postępu z K5 §6.5 p. 5; S-456→S-338: `chunk_method` `tag`/`knowledge_graph`; S-457→S-339:
# domyślny `parser_config` z resetu K9). Czwarta (S-458) jest własna dla SDK: kopia v0.27.2
# pochodzi z naprawy upstream `6ec9c6a73` (`strip_graphrag_raptor_config`), po której
# `parser_config` odpowiedzi nie ma `graphrag`/`raptor` — jak S-425/S-429 dla datasetów.
# `test_upload_documents.py` przechodzi w całości, więc nie ma tu żadnego wzorca (wiersz bez
# użycia czerwieni `test_skipped_index.py::test_every_row_is_used`, DEC-112 p. 2).
_SDK_DOCS_B_DIR = "test_sdk_api/test_file_management_within_dataset/"
_SDK_DOCS_PARSE = _SDK_DOCS_B_DIR + "test_parse_documents.py::"
_SDK_DOCS_UPD = _SDK_DOCS_B_DIR + "test_update_document.py::"
_SDK_DOCS_B: dict[str, str] = {
    # Literał końca postępu: WD kończy `Indexing done (Xs). Done.` (K5 §6.5 p. 5), upstream
    # `Task done (Xs)` — jak S-335 dla HTTP.
    _SDK_DOCS_PARSE
    + "TestDocumentsParse::test_basic_scenarios[[]<lambda>-*[]]": "SKIPPED.md#S-455",
    _SDK_DOCS_PARSE + "TestDocumentsParse::test_parse_partial_invalid_document_id[[]<lambda>*[]]": (
        "SKIPPED.md#S-455"
    ),
    _SDK_DOCS_PARSE + "TestDocumentsParse::test_duplicate_parse": "SKIPPED.md#S-455",
    _SDK_DOCS_PARSE + "test_parse_100_files": "SKIPPED.md#S-455",
    _SDK_DOCS_PARSE + "test_concurrent_parse": "SKIPPED.md#S-455",
    # `chunk_method` tag/knowledge_graph: WD świadomie ich nie obsługuje (jak S-338/S-104/S-208).
    _SDK_DOCS_UPD + "TestDocumentsUpdated::test_chunk_method[[]tag-*[]]": "SKIPPED.md#S-456",
    _SDK_DOCS_UPD + "TestDocumentsUpdated::test_chunk_method[[]knowledge_graph-*[]]": (
        "SKIPPED.md#S-456"
    ),
    # `parser_config == {}` → domyślny `parser_config` dokumentu różni się od upstreamowej stałej
    # `DEFAULT_PARSER_CONFIG` wyłącznie `llm_id` z resetu K9 (jak S-339).
    _SDK_DOCS_UPD
    + "TestUpdateDocumentParserConfig::test_parser_config[[]naive-parser_config0-[]]": (
        "SKIPPED.md#S-457"
    ),
    # `graphrag`/`raptor` zostają w `parser_config` odpowiedzi (S-425/S-429), a kopia SDK
    # v0.27.2 wymaga ich braku — jak S-425/S-429.
    _SDK_DOCS_UPD
    + "TestUpdateDocumentParserConfig::test_parser_config[[]naive-parser_config20-[]]": (
        "SKIPPED.md#S-458"
    ),
    _SDK_DOCS_UPD
    + "TestUpdateDocumentParserConfig::test_parser_config[[]naive-parser_config21-[]]": (
        "SKIPPED.md#S-458"
    ),
}
# Puste — wszystkie dziesięć pozycji to `odchyłka-WD` (`xfail(strict=True)`, CONTRACT §4);
# `test_upload_documents.py` nie ma pominięć. Stała zostaje dla wzoru zadań T1/T4/T5.
_SDK_DOCS_B_SKIP: frozenset[str] = frozenset()
_SDK_DOCS_B_XFAIL: frozenset[str] = frozenset(
    pattern for pattern, reason in _SDK_DOCS_B.items() if reason not in _SDK_DOCS_B_SKIP
)

# E2-3b2/T4: kopie 1:1 z v0.27.2 `test_sdk_api/test_chat_assistant_management/`. S-466 i S-467 to
# te same przyczyny, co wiersze HTTP katalogu czatów (S-353: domyślny `{"key": "date"}` w pustej
# liście `prompt_config.parameters`; S-355: 102 „Chat not found!" na nieistniejący czat), a S-465
# jest własny dla SDK: przy **jawnie podanej nazwie** modelu WD oddaje `models.id` (upstream v0.27.2
# oddaje podaną nazwę, id tylko w `tenant_llm_id`) — wg zamrożonego R1 z E1-9b. Powody i odsyłacze
# w SKIPPED.md, rozstrzygnięcie w DEC-114. Wzorce niosą **nazwę pliku**: `test_llm_setting`
# i `test_prompt_config` są też w drugim pliku katalogu, gdzie przechodzą — wzorzec bez pliku
# dałby XPASS strict (already-failed).
_SDK_CHATS_DIR = "test_sdk_api/test_chat_assistant_management/"
_SDK_CHAT_CREATE = _SDK_CHATS_DIR + "test_create_chat_assistant.py::TestChatAssistantCreate::"
_SDK_CHAT_LIST = _SDK_CHATS_DIR + "test_list_chat_assistants.py::TestChatAssistantsList::"
_SDK_CHAT_UPDATE = _SDK_CHATS_DIR + "test_update_chat_assistant.py::TestChatAssistantUpdate::"
_SDK_CHATS: dict[str, str] = {
    # Jawna nazwa modelu wraca jako `models.id` (upstream: dosłownie nazwa; E1-9b R1, DEC-114 p. 1).
    _SDK_CHAT_CREATE + "test_llm_id[[]valid_chat_llm_id*[]]": "SKIPPED.md#S-465",
    _SDK_CHAT_UPDATE + "test_llm_setting[[]llm_setting0*[]]": "SKIPPED.md#S-465",
    # Pusta lista `parameters` dostaje domyślną pozycję `date` (S-353).
    _SDK_CHAT_CREATE + "test_prompt_config[[]prompt_config21*[]]": "SKIPPED.md#S-466",
    # Nieistniejący czat: 102 „Chat not found!" zamiast 109 „no authorization" (S-355).
    _SDK_CHAT_LIST + "test_get_chat[[]unknown*[]]": "SKIPPED.md#S-467",
}
# Puste — wszystkie pozycje katalogu to `odchyłka-WD` (`xfail(strict=True)`, CONTRACT §4). Stała
# zostaje dla jednolitego wzoru zadań T1/T2/T3/T5 (`_SDK_*_SKIP`/`_SDK_*_XFAIL`).
_SDK_CHATS_SKIP: frozenset[str] = frozenset()
_SDK_CHATS_XFAIL: frozenset[str] = frozenset(
    pattern for pattern, reason in _SDK_CHATS.items() if reason not in _SDK_CHATS_SKIP
)

# E2-3b2/T5: kopie 1:1 z v0.27.2 `test_sdk_api/test_session_management/`. Jedna odchyłka: S-470 —
# `page_size=0` na liście sesji (kopia SDK oczekuje 5 sesji). Odchyłka jest **własna dla SDK**:
# upstream v0.27.2 `validate_rest_api_page_size` mapuje wartość `<1` na 30 (pagination_utils.py),
# więc strażnik `if items_per_page == 0: convs = []` w `list_sessions` (`chat_api.py:864-890`) jest
# martwy, a commit `4b619f699` podniósł pod to oczekiwanie kopii SDK (0 → 5) — bez zmiany kopii HTTP
# tego katalogu, która nadal oczekuje 0 i jest w WD zielona. WD oddaje `[]` wg zamrożonego
# `work/wp/E1-9b/CONTRACT.md` l. 192/229 (`allow_zero_size=True`), K11 l. 70 i 02-api Q25 — dlatego
# kategoria `odchyłka-WD`, bez zmian w WD (rozstrzygnięcie: DEC-115). Wzorzec niesie **nazwę pliku**
# i parametr: `test_page_size` jest też w innych plikach katalogu, gdzie inne warianty przechodzą.
_SDK_SESSIONS_DIR = "test_sdk_api/test_session_management/"
_SDK_SESSIONS_LIST = (
    _SDK_SESSIONS_DIR
    + "test_list_sessions_with_chat_assistant.py::TestSessionsWithChatAssistantList::"
)
_SDK_SESSIONS: dict[str, str] = {
    _SDK_SESSIONS_LIST + "test_page_size[[]params1-*[]]": "SKIPPED.md#S-470",
}
# Puste — jedyna pozycja katalogu to `odchyłka-WD` (`xfail(strict=True)`, CONTRACT §4). Stała
# zostaje dla jednolitego wzoru zadań T1…T4 (`_SDK_*_SKIP`/`_SDK_*_XFAIL`). Zarezerwowane
# S-471…S-474 zostały niewykorzystane — katalog nie ujawnił dalszych odchyłek (DEC-115 p. 4).
_SDK_SESSIONS_SKIP: frozenset[str] = frozenset()
_SDK_SESSIONS_XFAIL: frozenset[str] = frozenset(
    pattern for pattern, reason in _SDK_SESSIONS.items() if reason not in _SDK_SESSIONS_SKIP
)

# E5-2a/T5: odchyłka H4 — limit 100 plików w JEDNYM żądaniu uploadu (`MAX_FILES_PER_REQUEST`,
# `app/api/ragflow/file_safety.py`, DEC-213). Obie kopie `test_delete_1k` (HTTP i SDK) wgrywają
# 1000 plików jednym żądaniem (`bulk_upload_documents` → jedno `upload_documents(...)`), więc WD
# odrzuca żądanie kodem 101, zanim test dojdzie do kasowania; upstream nie ma tego limitu.
_FM_1K: dict[str, str] = {
    _TFM + "test_delete_documents.py::test_delete_1k": "SKIPPED.md#S-471",
    _SDK_DOCS_B_DIR + "test_delete_documents.py::test_delete_1k": "SKIPPED.md#S-471",
}
# Puste — oba wzorce to `odchyłka-WD` (`xfail(strict=True)`, CONTRACT §4). Stała zostaje dla
# jednolitego wzoru zadań T1…T5 (`_*_SKIP`/`_*_XFAIL`).
_FM_1K_SKIP: frozenset[str] = frozenset()
_FM_1K_XFAIL: frozenset[str] = frozenset(
    pattern for pattern, reason in _FM_1K.items() if reason not in _FM_1K_SKIP
)

SKIPPED: dict[str, str] = (
    _OUT_OF_SCOPE
    | _SDK_OUT_OF_SCOPE
    | _DEAD_ENDS
    | _DEVIATIONS
    | _PARSER_DEFAULTS
    | _CHUNK_DEVIATIONS
    | _T4_DEVIATIONS
    | _SESSIONS_A_405
    | _CHAT_SKIPS
    | _CHAT_DEVIATIONS
    | _ENVIRONMENT
    | _SDK_DATASETS_CU
    | _SDK_CHUNKS
    | _SDK_DOCS_B
    | _SDK_CHATS
    | _SDK_SESSIONS
    | _FM_1K
)
SKIPPED_XFAIL: set[str] = (
    set(_DEVIATIONS)
    | set(_PARSER_DEFAULTS)
    | set(_CHUNK_DEVIATIONS)
    | set(_T4_DEVIATIONS)
    | set(_SESSIONS_A_405)
    | set(_CHAT_DEVIATIONS)
    | _SDK_DATASETS_CU_XFAIL
    | _SDK_CHUNKS_XFAIL
    | _SDK_DOCS_B_XFAIL
    | _SDK_CHATS_XFAIL
    | _SDK_SESSIONS_XFAIL
    | _FM_1K_XFAIL
)
# Powody nadawane w kodzie, poza wzorcami nodeid; czyta `test_skipped_index.py`. Puste od E2-3a1:
# stub `hypothesis` (`HYPOTHESIS_SKIPPED`) działa tylko bez przypiętej zależności dev, więc nie ma
# wiersza w SKIPPED.md (w zsynchronizowanym środowisku żaden test nie jest tak pomijany).
DYNAMIC_SKIPPED: tuple[str, ...] = ()


def pytest_configure(config: pytest.Config) -> None:
    """Rejestruje markery poziomów upstreamu (`p0`…`p3`) dla `--strict-markers`."""
    for name, description in UPSTREAM_MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")


def _upstream_prefix(config: pytest.Config) -> str:
    """Prefiks nodeid katalogu `upstream/` (nodeidy liczy pytest od `rootpath`)."""
    return os.path.relpath(HERE, config.rootpath).replace(os.sep, "/") + "/"


def _matching_pattern(relative_nodeid: str) -> str | None:
    """Wzorzec z `SKIPPED` pasujący do nodeidu względem `upstream/` (fnmatch), albo `None`."""
    for pattern in SKIPPED:
        if fnmatch.fnmatchcase(relative_nodeid, pattern):
            return pattern
    return None


class _SkippedUpstreamItem(pytest.Item):
    """Syntetyczna pozycja nieimportowalnego modułu: ``runtest`` pomija ją z powodem (T5).

    ``pytest.Item``, nie ``pytest.Function``: pozycja funkcji wymaga ``obj``, czyli wczytania
    modułu, którego właśnie nie da się zaimportować.
    """

    def __init__(self, *args: Any, reason: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reason = reason

    def runtest(self) -> NoReturn:
        pytest.skip(self._reason)


class _SkippedUpstreamModule(pytest.Module):
    """Kopia, której nie da się w WD zaimportować: daje JEDNĄ syntetyczną pozycję (CONTRACT §4).

    ``collect_ignore``/``pytest_ignore_collect`` odpada — takie pominięcie nie pojawia się
    w raporcie ``-rs``. Pominięcie KOLEKTORA (``pytest.skip`` w ``collect()``) widać w ``-rs``,
    ale dzieje się przy zbieraniu, więc trafia do każdego biegu — także do kroku ``binaries``
    verify-full (``-m binaries`` w obrazie test-ocr), którego wyrażenie ``-m`` zbioru nie dotyczy;
    krok kończył się wtedy „pominięte testy" (T5/E2-3a1). Pozycja z ``runtest``-em dostaje marker
    ``contract`` w ``pytest_collection_modifyitems`` (jak każda pozycja spod ``upstream/``), więc
    przy ``-m contract`` jest widoczna jako pominięta z powodem z ``SKIPPED.md``, a przy każdym
    innym ``-m`` (np. ``binaries``) jest odfiltrowana, zamiast raportować skip.
    """

    def __init__(self, *args: Any, reason: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reason = reason

    def collect(self) -> list[pytest.Item]:
        """Jedna pozycja ``_SkippedUpstreamItem`` — pominięcie raportuje dopiero jej bieg."""
        return [_SkippedUpstreamItem.from_parent(self, name=self.path.stem, reason=self._reason)]


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makemodule(
    module_path: Path, parent: pytest.Collector
) -> pytest.Module | None:
    """Pomija moduły z `_UNIMPORTABLE_MODULES`; pozostałe oddaje domyślnemu hookowi pytest.

    ``tryfirst`` + ``None`` dla pozostałych modułów: hook jest ``firstresult``, więc domyślna
    implementacja (z wczytywaniem modułu przez ``isinitpath``) działa bez zmian.
    """
    if not module_path.is_relative_to(HERE):
        return None
    relative = module_path.relative_to(HERE).as_posix()
    if relative not in _UNIMPORTABLE_MODULES:
        return None
    return _SkippedUpstreamModule.from_parent(parent, path=module_path, reason=SKIPPED[relative])


def pytest_collection_modifyitems(items: list[pytest.Item], config: pytest.Config) -> None:
    """Dodaje marker `contract` pozycjom spod `upstream/` i pominięcia (CONTRACT §3/§4)."""
    prefix = _upstream_prefix(config)
    for item in items:
        if not item.nodeid.startswith(prefix):
            continue
        item.add_marker(pytest.mark.contract)
        pattern = _matching_pattern(item.nodeid[len(prefix) :])
        if pattern is None:
            continue
        if pattern in SKIPPED_XFAIL:
            item.add_marker(pytest.mark.xfail(strict=True, reason=SKIPPED[pattern]))
        else:
            item.add_marker(pytest.mark.skip(reason=SKIPPED[pattern]))
