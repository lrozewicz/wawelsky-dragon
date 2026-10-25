"""Normalizacja wejścia tras ingestii i sprawdzenia embeddingu (zadanie DS2).

Parametry listy wg upstream ``dataset_api.py:1390`` (``list_ingestion_logs``): ``operation_status``
(powtarzalny), ``log_type`` (nie ``status``; domyślnie ``dataset``), ``keywords``,
``create_date_from``/``create_date_to``; ``page``/``page_size``/``orderby``/``desc`` przez
``parse_page``. ``embedding/check``: ``embd_id`` wymagane (upstream zwraca wtedy błąd danych 102),
``check_num`` liczba próbkowanych chunków.
"""

from collections.abc import Mapping

from pydantic import Field
from starlette.datastructures import QueryParams

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.normalize.common import Command, parse_model
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict
from app.services.dataset_ingestions import (
    DEFAULT_LOG_TYPE,
    LOG_TYPES,
    MSG_INVALID_LOG_TYPE,
    IngestionsQuery,
)

# Domyślna liczba próbkowanych chunków (upstream ``req.get("check_num", 5)``).
DEFAULT_CHECK_NUM = 5


class EmbeddingCheckCommand(Command):
    """Ciało POST …/embedding/check; ``embd_id`` puste → błąd danych 102 (upstream :1375).

    ``check_num`` musi być dodatni (upstream robi ``int(...)`` bez kontroli; WD nie
    dopuszcza wartości, która wysypałaby ``LIMIT`` w SQL).
    """

    embd_id: str = ""
    check_num: int = Field(default=DEFAULT_CHECK_NUM, ge=1)


def list_ingestions(
    query: QueryParams, profile: CompatProfile, *, max_size: int
) -> IngestionsQuery:
    """GET …/ingestions: paginacja + log_type (nieznany → błąd danych 102, upstream :830)."""
    page = parse_page(query, max_size=max_size)
    log_type = query.get("log_type") or DEFAULT_LOG_TYPE
    if log_type not in LOG_TYPES:
        raise Conflict(MSG_INVALID_LOG_TYPE)
    return IngestionsQuery(
        page=page.page,
        page_size=page.page_size,
        orderby=page.orderby,
        desc=page.desc,
        log_type=log_type,
        operation_status=tuple(query.getlist("operation_status")),
        keywords=query.get("keywords") or None,
        create_date_from=query.get("create_date_from") or None,
        create_date_to=query.get("create_date_to") or None,
    )


def embedding_check_command(
    body: Mapping[str, object], profile: CompatProfile
) -> EmbeddingCheckCommand:
    """Walidacja POST …/embedding/check."""
    return parse_model(EmbeddingCheckCommand, body)
