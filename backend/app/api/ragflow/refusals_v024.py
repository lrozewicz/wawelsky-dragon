"""Mapa profili odmów v0.24.0 (kontrakt E2-2f C2) — kody i komunikaty ze złota v0.24.0.

Kody i szablony przepisane dosłownie z C2; profil bez własnego szablonu (``message is None``)
zachowuje komunikat wyjątku trasy. Wpisy v0.24 nie mają pola ``data`` (koperta ``{code, message}``),
tak jak i v0.27 poza odmową czatu i sesji. Trasy nieobecne w złocie v0.24.0 (``datasets_get``,
``chats_get``, ``sessions_get``, ``chat_completions``, ``retrieval_search``,
``retrieval_search_dataset``) nie mają tu wpisu — ``refuse`` zwraca dla nich 108.
"""

from collections.abc import Mapping

from app.api.ragflow.refusals import (
    MSG_ASSISTANT_IDS_NOT_FOUND,
    MSG_DATASET_NOT_OWN_DOCUMENT_DOT,
    MSG_DO_NOT_OWN_ASSISTANT_DOT,
    MSG_DO_NOT_OWN_CHAT,
    MSG_DO_NOT_OWN_DATASET_DOT,
    MSG_DO_NOT_OWN_SESSION,
    MSG_DONT_OWN_ASSISTANT_DOT,
    MSG_DONT_OWN_CHAT,
    MSG_DONT_OWN_CHAT_BARE,
    MSG_DONT_OWN_DATASET_DOT,
    MSG_DONT_OWN_DATASET_NOUN_DOT,
    MSG_DONT_OWN_DOCUMENT_DOT,
    MSG_LACK_DATASET,
    MSG_LACK_DATASETS,
    MSG_NO_AUTHORIZATION,
    MSG_NOT_OWN_DATASET_SPACE,
    RefusalProfile,
)

# ``refuse`` formatuje ``{dataset_id}`` tylko ze ścieżki; ask podaje id w ``ids`` (C4 p. 2).
MSG_DONT_OWN_DATASET_IDS_DOT = "You don't own the dataset {ids}."

# Trasa legacy ``DELETE /v1/system/token/{token}`` (E2-2a T3): złoto v0.24.0 nie ma pliku
# odmowy (upstream ``system_app.rm`` kasuje cicho po ``tenant_id`` i oddaje sukces także dla
# cudzego tokenu), a WD nie może zwrócić sukcesu na cudzym zasobie (CONTRACT C0 p. 9) —
# komunikat własny, kod 108 jak każda odmowa właściciela w tym profilu.
MSG_DONT_OWN_TOKEN = "You don't own the token."  # noqa: S105 — komunikat koperty, nie sekret

# Trasy legacy ``/v1/document/*`` (E2-2a T4): złoto v0.24.0 nie ma dla nich plików odmowy.
# Upstream ``document_app.py``: ``run`` odmawia komunikatem „No authorization." z kodem
# ``RetCode.AUTHENTICATION_ERROR`` = 109 (DOC:602), ``change_status`` wpisuje ten sam komunikat
# per dokument do koperty 500 „Partial failure" (DOC:516/523), a ``get`` (DOC:707) i
# ``thumbnails`` (DOC:482) nie sprawdzają właściciela wcale. WD odmawia we wszystkich czterech
# (CONTRACT C0 p. 9), zachowując komunikat upstreamu i kod odmowy właściciela tego profilu
# (108, jak ``v1_token_delete``) — kody 102/108/109 to cały zbiór kodów odmów v0.24 (C2).
MSG_NO_AUTHORIZATION_DOT = "No authorization."

# Kody kopert z K3 §1 (RetCode): 108 = odmowa właściciela (upstream ``RetCode.PERMISSION_ERROR``).
_CODE_DATA_ERROR = 102
_CODE_LACK_PERMISSION = 108
_CODE_AUTHENTICATION_ERROR = 109

PROFILES_V024: Mapping[str, RefusalProfile] = {
    "datasets_list": RefusalProfile(_CODE_LACK_PERMISSION),
    "datasets_update": RefusalProfile(_CODE_LACK_PERMISSION, MSG_LACK_DATASET),
    "datasets_delete": RefusalProfile(_CODE_LACK_PERMISSION, MSG_LACK_DATASETS),
    "documents_upload": RefusalProfile(_CODE_AUTHENTICATION_ERROR, MSG_NO_AUTHORIZATION),
    "documents_list": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    "datasets_metadata_summary": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    "documents_delete": RefusalProfile(_CODE_DATA_ERROR, MSG_NOT_OWN_DATASET_SPACE),
    "documents_download": RefusalProfile(_CODE_DATA_ERROR, MSG_DO_NOT_OWN_DATASET_DOT),
    "documents_download_missing_document": RefusalProfile(
        _CODE_DATA_ERROR, MSG_DATASET_NOT_OWN_DOCUMENT_DOT
    ),
    "documents_update": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_NOUN_DOT),
    "documents_parse": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_DOT),
    "documents_stop": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_DOT),
    "chunks_list": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_DOT),
    "chunks_list_missing_document": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DOCUMENT_DOT),
    "chunks_create": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_DOT),
    "chunks_delete": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_DOT),
    "retrieval_query": RefusalProfile(_CODE_DATA_ERROR),
    "chats_update": RefusalProfile(_CODE_DATA_ERROR, MSG_DO_NOT_OWN_CHAT),
    "chats_delete_many": RefusalProfile(_CODE_DATA_ERROR, MSG_ASSISTANT_IDS_NOT_FOUND),
    "chats_completions": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_CHAT),
    "sessions_create": RefusalProfile(_CODE_DATA_ERROR, MSG_DO_NOT_OWN_ASSISTANT_DOT),
    "sessions_list": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_ASSISTANT_DOT),
    "sessions_rename": RefusalProfile(_CODE_DATA_ERROR, MSG_DO_NOT_OWN_SESSION),
    "sessions_delete": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_CHAT_BARE),
    # ``/sessions/ask`` (upstream ask_about: cudzy/nieistniejący dataset → get_error_data_result).
    "sessions_ask": RefusalProfile(_CODE_DATA_ERROR, MSG_DONT_OWN_DATASET_IDS_DOT),
    # Legacy DELETE /v1/system/token/{token} (E2-2a T3) — cudzy/nieistniejący token.
    "v1_token_delete": RefusalProfile(_CODE_LACK_PERMISSION, MSG_DONT_OWN_TOKEN),
    # Legacy /v1/document/* (E2-2a T4) — cudzy/nieistniejący dokument na czterech trasach
    # (``upload_info`` nie ma dokumentu, więc nie ma czego sprawdzać).
    "v1_document_change_status": RefusalProfile(_CODE_LACK_PERMISSION, MSG_NO_AUTHORIZATION_DOT),
    "v1_document_run": RefusalProfile(_CODE_LACK_PERMISSION, MSG_NO_AUTHORIZATION_DOT),
    "v1_document_get": RefusalProfile(_CODE_LACK_PERMISSION, MSG_NO_AUTHORIZATION_DOT),
    "v1_document_thumbnails": RefusalProfile(_CODE_LACK_PERMISSION, MSG_NO_AUTHORIZATION_DOT),
}
