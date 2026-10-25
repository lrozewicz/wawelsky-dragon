"""Prezenter odmowy dostępu per trasa (K11 §10c p. 9, kontrakt E2-1 C2).

Kod i komunikat odmowy bierze się z pliku złota danej trasy
(``backend/tests/contract/golden/<ver>/<katalog>/errors_access--NN.json``; opis:
``docs/contracts/golden-E2.md`` §„Nagrane pliki"). Trasy bez złota błędu zachowują 108
(``PermissionDenied`` z ``app.domain.policy`` — bez zmian).

Koperta odmowy nie ma pola ``data`` — w złocie występuje ono wyłącznie przy HTTP 401
(brak/zły ``Authorization``), którym zajmuje się ``app.api.errors`` — oraz przy odmowie
czatu i sesji (109; upstream ``get_json_result(data=False)``, ``chat_api.py:190``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.ragflow.compat import CompatProfile
from app.core.errors import PermissionDenied, WDError
from app.domain.policy import Principal

# Komunikaty dosłownie ze złota v0.27.2 (katalogi tras w złocie podają je per plik).
MSG_LACK_DATASET = "User '{user_id}' lacks permission for dataset '{dataset_id}'"
MSG_LACK_DATASETS = "User '{user_id}' lacks permission for datasets: '{ids}'"
# Komunikat listy i usuwania dokumentów datasetu ma w złocie spację na końcu
# (upstream skleja „You don't own the dataset <id>." z pustym sufiksem szczegółów).
MSG_NOT_OWN_DATASET_SPACE = "You don't own the dataset {dataset_id}. "
MSG_DOCUMENT_NOT_FOUND = "document not found"
MSG_DONT_OWN_DATASET = "you don't own the dataset"
MSG_NO_AUTHORIZATION = "no authorization"
# Trasa OpenAI-owa czatu odmawia inaczej niż ``chat_api`` (upstream ``openai_api.py:272``).
MSG_NOT_OWN_CHAT = "You don't own the chat {chat_id}"

# Komunikaty wyłącznie v0.24.0 (kontrakt E2-2f C2) — v0.27 ma dla tych tras własne warianty.
# Współdzielone z v0.24: powyższe MSG_LACK_*, MSG_NOT_OWN_DATASET_SPACE, MSG_NO_AUTHORIZATION.
MSG_DO_NOT_OWN_DATASET_DOT = "You do not own the dataset {dataset_id}."
MSG_DONT_OWN_DATASET_DOT = "You don't own the dataset {dataset_id}."
MSG_DONT_OWN_DATASET_NOUN_DOT = "You don't own the dataset."
MSG_DATASET_NOT_OWN_DOCUMENT_DOT = "The dataset not own the document {document_id}."
MSG_DONT_OWN_DOCUMENT_DOT = "You don't own the document {document_id}."
MSG_DO_NOT_OWN_CHAT = "You do not own the chat"
MSG_DONT_OWN_CHAT = "You don't own the chat {chat_id}"
MSG_DONT_OWN_CHAT_BARE = "You don't own the chat"
MSG_ASSISTANT_IDS_NOT_FOUND = "Assistant({ids}) not found."
MSG_DO_NOT_OWN_ASSISTANT_DOT = "You do not own the assistant."
MSG_DONT_OWN_ASSISTANT_DOT = "You don't own the assistant {chat_id}."
MSG_DO_NOT_OWN_SESSION = "You do not own the session"

# Kody koperty wyników z K3 §1 (RetCode), używane w profilach.
_CODE_DATA_ERROR = 102
_CODE_AUTHENTICATION_ERROR = 109

# Sentinel: ``RefusalProfile.data`` zostawiony na nim → koperta bez klucza ``data``.
_NO_DATA = object()


@dataclass(frozen=True)
class RefusalProfile:
    """Profil odmowy trasy: kod koperty, szablon komunikatu i wartość pola ``data``.

    ``message is None`` — komunikat bierze się z wyjątku trasy (upstream
    ``get_data_error_result`` przekazuje go dalej). ``data is _NO_DATA`` — koperta bez klucza
    ``data``; inaczej (upstream ``get_json_result(data=False)``) klucz jest z tą wartością.
    """

    code: int
    message: str | None = None
    data: object = _NO_DATA


# Odmowa czatu i sesji: upstream ``_ensure_owned_chat`` (chat_api.py:190) nie odróżnia czatu
# nieistniejącego od cudzego — w obu wypadkach 109 z ``data: false``.
_CHAT_NOT_OWNED = RefusalProfile(_CODE_AUTHENTICATION_ERROR, MSG_NO_AUTHORIZATION, data=False)

# Odmowa wyszukiwarki (PUT/DELETE/completion): upstream ``search_api.py`` nie odróżnia
# wyszukiwarki nieistniejącej od cudzej — 109 z ``data: false`` (złoto searches--18/29/30/31).
_SEARCH_NOT_OWNED = RefusalProfile(_CODE_AUTHENTICATION_ERROR, MSG_NO_AUTHORIZATION, data=False)

# Klucz = trasa nadana w miejscu wywołania ``refuse`` (nazwa zrozumiała sama w sobie,
# jedna trasa może obsłużyć kilka operacji, np. PATCH i PUT czatu albo dokumentu).
PROFILES: Mapping[str, RefusalProfile] = {
    "datasets_list": RefusalProfile(_CODE_DATA_ERROR),
    "datasets_get": RefusalProfile(_CODE_DATA_ERROR, MSG_LACK_DATASET),
    "datasets_update": RefusalProfile(_CODE_DATA_ERROR, MSG_LACK_DATASET),
    "datasets_delete": RefusalProfile(_CODE_DATA_ERROR, MSG_LACK_DATASETS),
    "documents_upload": RefusalProfile(_CODE_AUTHENTICATION_ERROR, MSG_NO_AUTHORIZATION),
    "documents_list": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    # Podsumowanie metadanych dzieli z listą dokumentów kod i komunikat (upstream
    # ``document_api.py:337``; v0.24.0 ``sdk/doc.py:644`` mówi to samo).
    "datasets_metadata_summary": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    "documents_download": RefusalProfile(_CODE_DATA_ERROR, MSG_DOCUMENT_NOT_FOUND),
    "documents_update": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET),
    "documents_delete": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    "documents_parse": RefusalProfile(_CODE_DATA_ERROR),
    "documents_stop": RefusalProfile(_CODE_DATA_ERROR),
    "chunks_list": RefusalProfile(_CODE_DATA_ERROR),
    "chunks_create": RefusalProfile(_CODE_DATA_ERROR),
    "chunks_delete": RefusalProfile(_CODE_DATA_ERROR),
    "retrieval_query": RefusalProfile(_CODE_DATA_ERROR),
    "chats_get": _CHAT_NOT_OWNED,
    "chats_update": _CHAT_NOT_OWNED,
    "chats_delete_many": RefusalProfile(_CODE_DATA_ERROR),
    "chats_completions": _CHAT_NOT_OWNED,
    "chat_completions": _CHAT_NOT_OWNED,
    # Rekomendacje z ``search_id`` (E4-4a T4): brakująca i cudza wyszukiwarka odmawiają
    # jak czat — 109 ``no authorization`` z ``data: false`` (CONTRACT §D7).
    "chat_recommendation": _CHAT_NOT_OWNED,
    "sessions_create": _CHAT_NOT_OWNED,
    "sessions_list": _CHAT_NOT_OWNED,
    "sessions_get": _CHAT_NOT_OWNED,
    "sessions_rename": _CHAT_NOT_OWNED,
    "sessions_delete": _CHAT_NOT_OWNED,
    # Trasy wyszukiwania dzielą z /retrieval ten sam przepływ upstream (chunk_api.py:333-334):
    # cudzy i nieistniejący dataset dają tam 102 z komunikatem „You don't own the dataset <id>.".
    "retrieval_search": RefusalProfile(_CODE_DATA_ERROR),
    "retrieval_search_dataset": RefusalProfile(_CODE_DATA_ERROR),
    # Wyszukiwarki (K15 §2): 109 ``no authorization`` z ``data: false`` (wzór czatu).
    "searches_update": _SEARCH_NOT_OWNED,
    "searches_delete": _SEARCH_NOT_OWNED,
    "searches_completions": _SEARCH_NOT_OWNED,
    # Menedżer plików (K16 §2 p. 3): cudzy plik to 102 ``no authorization`` bez ``data``
    # (złoto files--26…30, CONTRACT E4-5a §D1.8).
    "files_create": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_list": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_download": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_parent": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_ancestors": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_move": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
    "files_link_to_datasets": RefusalProfile(_CODE_DATA_ERROR, MSG_NO_AUTHORIZATION),
}


def refuse(  # noqa: PLR0913 — sygnatura dosłowna z kontraktu E2-2f C1
    request: Request,
    principal: Principal,
    route: str,
    err: WDError | None = None,
    *,
    ids: Sequence[str] = (),
    compat: CompatProfile,
) -> JSONResponse:
    """Koperta odmowy (HTTP 200) wg profilu trasy i profilu zgodności (K11 §10c p. 9).

    ``err`` — wyjątek domenowy trasy; profil bez własnego szablonu bierze z niego komunikat
    (i wtedy jest wymagany). ``ids`` — identyfikatory z ciała żądania; ``DELETE /datasets``
    i ``DELETE /chats`` nie mają ich w ścieżce, a złoto podaje je w komunikacie. Identyfikator
    datasetu/dokumentu/czatu bierze się ze ścieżki żądania, użytkownika z podmiotu
    (złoto: ``User '<tenant>' …``).

    ``compat`` wybiera mapę profili: ``PROFILES`` dla v0.27, ``PROFILES_V024`` dla v0.24.
    Klucz nieobecny w mapie danego profilu (trasa bez złota odmowy w tej wersji) → 108
    ``PermissionDenied`` z komunikatem wyjątku (albo ``no authorization`` bez wyjątku).
    """
    if compat == "ragflow_0_27":
        profiles: Mapping[str, RefusalProfile] = PROFILES
    else:
        # Import leniwy (kontrakt E2-2f C1): ``refusals_v024`` importuje stałe i
        # ``RefusalProfile`` z tego modułu, więc import na górze domknąłby cykl.
        from app.api.ragflow.refusals_v024 import PROFILES_V024  # noqa: PLC0415

        profiles = PROFILES_V024
    profile = profiles.get(route)
    if profile is None:
        raise PermissionDenied(err.message if err is not None else MSG_NO_AUTHORIZATION)
    if profile.message is None:
        if err is None:
            raise RuntimeError(f"profil trasy {route!r} wymaga wyjątku z komunikatem")
        message = err.message
    else:
        message = profile.message.format(
            user_id=principal.user_id,
            dataset_id=str(request.path_params.get("dataset_id", "")),
            chat_id=str(request.path_params.get("chat_id", "")),
            document_id=str(request.path_params.get("document_id", "")),
            ids=", ".join(ids),
        )
    body: dict[str, object] = {"code": profile.code, "message": message}
    if profile.data is not _NO_DATA:
        body["data"] = profile.data
    return JSONResponse(body)
